---
name: test
description: Run the full kaizen pipeline smoke-test (install → backlog → gate → hooks → backup → migrate). TAP-style output, detail only on failures. Low token usage by default. Pass -v / --keep for verbose / preserve sandbox.
---

# kaizen pipeline test

End-to-end smoke against every surface of the plugin. Designed for low token/context overhead: TAP-style (one line per test), detail only on failures, summary line at the bottom.

Run:

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/test-pipeline.sh $ARGUMENTS`

## What it tests (~22 checks)

| Stage | Checks |
|---|---|
| **install** | `install.sh` runs cleanly, writes `.kaizen.toml`, symlinks pre-commit hook, sets local `core.hooksPath`, adds gitignore entry |
| **backlog lifecycle** | `add` → `start` → `tick`, schema correctness in `backlog.json`, `verify` after auto-render |
| **gate scenarios** | Empty stage exits 0, trivial diff passes, hard-fails properly captured |
| **PreToolUse(Bash)** | `git rm` → ask, `ls` → allow, `git push --force` → ask |
| **backup** | `create` writes a tarball, `list` finds it, `prune --keep 1` cleans up |
| **migrate / disable-skill / status** | All scan/read-only paths run cleanly |
| **hook scripts** | Stop (no in_flight) → `{}`, PreCompact → systemMessage, PostToolUse(non-commit) → `{}`, SessionStart emits valid JSON, SessionStart with in_flight → additionalContext |

## Token efficiency

- **Default output**: ~25-30 lines (one TAP line per test + summary line). On all-pass: ~700 tokens.
- **Failures**: only failing tests get expanded (last 5 lines of captured output). On 1 fail: ~+100 tokens.
- **--verbose**: shows stdout of every sub-command. Use when debugging. ~3-5× the token cost.
- **Sandbox**: `/tmp/gwtest-XXXXXX/`, auto-deleted on exit. `--keep` preserves for inspection.

## Sample compact output

```
ok 1 - install.sh runs cleanly
ok 2 - .kaizen.toml exists
ok 3 - .kaizen/hooks/pre-commit is a symlink
ok 4 - core.hooksPath set to .kaizen/hooks
ok 5 - .kaizen/ added to .gitignore
ok 6 - backlog add
ok 7 - backlog.json has 1 item
... (etc)
Result: 22/22 pass in 6s
```

## Sample failure output

```
ok 1 - install.sh runs cleanly
not ok 2 - backlog tick BK-001 (exit=1)
    backlog: id not found: BK-001
    {...captured stderr...}
ok 3 - ...
...
Result: 21/22 pass, 1 FAIL in 6s

Failures:
  not ok 2: backlog tick BK-001
```

## Args

- `-v` / `--verbose` — show stdout of each sub-command (token-heavy; use when debugging)
- `--keep` — don't delete the `/tmp/gwtest-*/` sandbox (so you can inspect it manually)

## Exit code

- `0` — all tests pass
- `1` — at least one failure (CI-gate compatible)
