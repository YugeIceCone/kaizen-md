---
name: pref-debug-command-hygiene
description: Use kaizen-scratch (not ad-hoc /tmp + rm -rf) for one-off debug experiments. Gate-safe by construction.
type: belief
confidence: 0.9
freshness: stable
sources_count: 1
evidence:
  - "Recurring pattern in debugging — chained `cd /tmp && rm -rf X && git init` trips kaizen's bash-gate even though the resolved path is under /tmp. A gate-safe sandbox tool removes the temptation."
---

# Debug experiments use `kaizen-scratch`

For one-off debug experiments (test a CLI flag, init a throwaway git
repo, probe a regex), prefer **`kaizen-scratch run -c '...'`** over
hand-rolling tempdirs with `cd /tmp && rm -rf ...`.

## The rule in one line

If your debug script contains `rm -rf` with a relative path: use
`kaizen-scratch run` instead.

## Recipes

```bash
# Run a shell command in a fresh git-initialized tempdir, auto-clean
kaizen-scratch run --git -c 'git status && git log --oneline'

# Keep the sandbox for follow-up
kaizen-scratch run --git --keep -c '...'      # prints sandbox path
kaizen-scratch list                            # show active sandboxes
kaizen-scratch clean                           # remove orphans

# Print + ensure a path (caller cleans)
kaizen-scratch path --name my-experiment
```

## Why

kaizen's bash-gate ([hooks/claude/_bash_gate.py]) blocks `rm -rf`
unless the target path explicitly starts with `/tmp`, `/var/tmp`,
`~/.cache`, `$TMPDIR`, or `$HOME/.cache`. Chained `cd /tmp && rm -rf
.git` doesn't qualify — the gate sees the literal `rm` arg, not the
shell-resolved cwd. `kaizen-scratch` creates paths under
`/tmp/kaizen-scratch/` that always satisfy the gate.

## Not for everything

For in-repo investigation (real files, real history), use normal
paths. `kaizen-scratch` is for ISOLATED throwaway experiments.
