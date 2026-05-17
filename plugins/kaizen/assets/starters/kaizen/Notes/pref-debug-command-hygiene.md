---
name: pref-debug-command-hygiene
description: Use kaizen-scratch (not ad-hoc /tmp + rm -rf) for one-off debug experiments. Gate-safe by construction.
type: belief
confidence: 0.95
freshness: stable
sources_count: 2
evidence:
  - "2026-05-17 debug pattern surfaced during scaffold subcommand work — `cd /tmp && rm -rf .git && ...` tripped the bash-gate's _RM_RF check (rm path was relative; shell-state inference is intentionally not done by the gate)."
  - "Same incident motivated building kaizen-scratch + this rule — pre-emptive codification rather than waiting for re-occurrence."
---

# Debug experiments use `kaizen-scratch`

When running a one-off debug experiment (init a tempfs git repo,
test a CLI flag, probe a regex, etc.), reach for **`kaizen-scratch
run -c '...'`** instead of hand-rolling `cd /tmp && mkdir ... && rm -rf ...`.

## Why

The bash-gate's `_RM_RF` check (`hooks/claude/_bash_gate.py:80`)
matches the LITERAL `rm` argument — it can't simulate `cd` chains.
So `cd /tmp/foo && rm -rf .git` prompts the user even though the
absolute path resolves under `/tmp`. The gate is RIGHT to be
conservative (chain-cd-then-rm is the exact obfuscation pattern an
exploit would use). Don't disable the gate; use a tool that emits
gate-safe paths by construction.

`kaizen-scratch` creates `/tmp/kaizen-scratch/<pid>-<id>-<slug>/` —
always under `/tmp`, so any internal cleanup matches `_RM_RF_SAFE`.
Auto-cleans on exit (or `--keep` to inspect).

## Canonical recipes

```bash
# Quick command in a fresh git repo, cleanup on exit
kaizen-scratch run --git -c 'git status && git log --oneline 2>&1 | head'

# Slug the sandbox dir for cross-run identification
kaizen-scratch run --git --name parser-test -c 'echo x > a && git add a && git diff --cached'

# Keep the sandbox for follow-up inspection
kaizen-scratch run --git --keep -c '...'   # prints sandbox path; clean later
kaizen-scratch list                         # see active sandboxes
kaizen-scratch clean                        # remove orphan dirs (process exited)
kaizen-scratch clean --all                  # nuke /tmp/kaizen-scratch/ entirely
```

## When NOT to use kaizen-scratch

- **The answer is in `--help` or man pages.** `git log --help | head -50`
  beats spinning up a sandbox to test a flag.
- **You need the result persisted.** kaizen-scratch is ephemeral by
  default; for durable artifacts, use a normal project dir.
- **The experiment depends on the repo under work.** kaizen-scratch
  is for ISOLATED experiments; in-repo investigation uses real paths.

## Anti-pattern (what this rule replaces)

```bash
# ❌ Chains cd into /tmp, then issues a relative rm. Bash-gate
# can't see the cwd resolution and emits a permission prompt.
cd /tmp && mkdir -p testfoo && cd testfoo && rm -rf .git && \
    git init -q && ...
```

```bash
# ✓ One call, no rm, no prompt.
kaizen-scratch run --git -c 'git ... && git ...'
```

## Reference

- CLI: `bin/kaizen-scratch` → `skills/workflow/scripts/scratch.py`
- Gate logic surfaced: `hooks/claude/_bash_gate.py:80` (`_RM_RF`,
  `_RM_RF_SAFE`)
- Tests: `tests/test_scratch.py`
