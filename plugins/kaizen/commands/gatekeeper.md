---
name: gatekeeper
description: "Unified kaizen gate. Aggregates iron-laws + etu anti-patterns + karpathy diff scanners + plugin-dev validate + 7 sub-gates. One verdict."
argument-hint: "[check|list|only <gate>] [--staged|--all] [--json]"
---

# /kaizen:gatekeeper

Runs the unified gate. Aggregates every Python-callable kaizen check into one verdict.

## Sub-gates

- **`iron-laws`** — the 15 auto-enforced iron laws (no-modify-vendored, sandbox-tests, paired-tests, hook-bypass-knob, plugin-manifest-permissions, …) over the staged diff or full plugin.
- **`etu`** — efficient-tool-use anti-pattern scanner. Greps the 15 scanner-ready `detect` regexes from `skills/efficient-tool-use/domain/anti-patterns.yaml` over staged `.sh` / `.bash` files (or all shell scripts under cwd in `--all` mode). Catches `eval $user_input`, `find /`, `grep "X" | wc -l`, `sed -i` without diff, missing `set -o pipefail`, etc.
- **`karpathy`** — diff-level scanners (`complexity_checker.py`, `diff_surgeon.py`, `assumption_linter.py`, `goal_verifier.py`) over staged paths. Diff-oriented; `--all` skips it.
- **`validator`** — wraps `plugin-development/scripts/validate.py`. Reports hard / soft finding counts; surfaces non-zero exit codes.

## Verdict

- **green** — no findings of any severity
- **yellow** — only `warn` findings (perf / style)
- **red** — at least one `error` / `hard` finding (correctness / safety)

Exit code: 0 for green/yellow, 1 for red.

## CLI

```bash
/kaizen:gatekeeper check --staged         # default: pre-commit-equivalent check
/kaizen:gatekeeper check --all            # full-plugin audit
/kaizen:gatekeeper check --json           # machine-readable output
/kaizen:gatekeeper only etu --all         # run one sub-gate
/kaizen:gatekeeper list                   # enumerate sub-gates
```

Or directly: `kaizen-gatekeeper <args>` (when on PATH after `/kaizen:setup install`).

## When to invoke

- Before a commit that touches structural files (hooks, scripts, manifests, schemas)
- On demand to audit the plugin: `/kaizen:gatekeeper check --all`
- After a sub-gate-relevant edit (e.g. you authored a new shell script — `only etu --all` confirms it's anti-pattern-free)
- As a one-liner in CI ahead of `unittest discover` for fast-fail

## Comparison to existing gates

| Tool | Scope | What it covers |
|---|---|---|
| `pre-commit.sh` | bash, staged | The 12 bash-callable pre-commit gates (compile barrier, fresh-TODO check, backlog drift, etc.) — uses `_iron_laws.py` for Check 7.5 |
| `/kaizen:iron-laws check` | Python, staged or all | Just the 15 iron laws |
| `validate.py` | Python, all | Plugin-development feature validator |
| **`/kaizen:gatekeeper`** | **Python, staged or all** | **All of the above PLUS etu + karpathy in one verdict** |

The gatekeeper is the "every Python gate, one command" view. Pre-commit (`pre-commit.sh`) stays the canonical commit-time gate; `/kaizen:gatekeeper` is the orchestration-time view that overlaps + extends.

## Behind the scenes

`scripts/iron-laws/gatekeeper.py` is the entry point. Each sub-gate is a function that:

1. Lazy-loads its source module via explicit `importlib.spec_from_file_location` (avoids the `_loader.py` name-collision when iron-laws and efficient-tool-use both ship one).
2. Returns a list of normalized `GateFinding(gate, severity, rule_id, message, file, line)` records.
3. Has its own duration timer in `Verdict.durations_ms`.

Adding a sub-gate: register a `_gate_<name>` function + add to the `SUB_GATES` dict. No schema changes needed; the unified shape is `GateFinding`.
