---
description: "Start (or cancel) a self-correcting Ralph loop — cross-CLI"
argument-hint: "PROMPT [--max-iterations N] [--completion-promise TEXT] | --cancel"
allowed-tools: ["Bash(${CLAUDE_PLUGIN_ROOT}/skills/loop/scripts/setup-ralph-loop.sh:*)", "Bash(test -f .kaizen/loop.state.md:*)", "Bash(rm .kaizen/loop.state.md)", "Read(.kaizen/loop.state.md)"]
---

# /kaizen:loop — self-correcting Stop-hook loop

Starts (or cancels) a Ralph-pattern self-correcting loop. The Stop hook
intercepts session exit and feeds the same prompt back until the
completion promise is emitted or `--max-iterations` is reached.

**State file:** `.kaizen/loop.state.md` (shared between Claude Code and Codex
hosts). **Stop hooks:** auto-installed via the kaizen plugin
(`hooks/claude/stop-ralph.sh` on CC, `hooks/codex/stop-ralph.sh` on Codex).

## Usage

```bash
# Structured ledger (recommended) — items with verify commands
/kaizen:loop --max-iterations 30 \
  --item "Implement carve in shim.py|grep -q 'def carve' plugins/kaizen/skills/workflow/scripts/shim.py" \
  --item "Add tests in tests/test_shim.py|python3 -m unittest tests.test_shim 2>&1 | grep -q OK" \
  --item "Update SKILL.md"

# Or import a pre-built ledger JSON file
/kaizen:loop --ledger plan.json --max-iterations 30

# Legacy freeform (no verify gate — trust-based)
/kaizen:loop "Build a REST API for todos. Output <promise>DONE</promise> when complete." \
  --max-iterations 30 --completion-promise "DONE"

# Cancel the active loop
/kaizen:loop --cancel
```

## Behavior

1. **Start:** Writes `.kaizen/loop.state.md` with the prompt-as-ledger,
   iteration count, max-iterations limit, and (optional) completion-promise.
2. **Iterate:** When the assistant tries to exit, the Stop hook reads the
   state file and emits `{decision: "block", reason: <ledger>}` to feed the
   ledger back. Iteration count increments per turn.
3. **Stop:** Loop exits on ANY of:
   - **Ledger empty** — body of `.kaizen/loop.state.md` (after frontmatter)
     contains only whitespace. *This is the primary completion signal.*
   - **Promise match** — assistant emits `<promise>PHRASE</promise>` matching
     `--completion-promise` (alternate exit, kept for prompt-only workflows).
   - **Iteration cap** — `--max-iterations` reached.
   - **Manual cancel** — `/kaizen:loop --cancel`.

## Ledger discipline (primary mode)

`.kaizen/loop.state.md` has a YAML frontmatter + a JSON body. The body is
the structured ledger, owned jointly by the agent (write to `pending`)
and the Stop hook (writes to `completed`, cheat-proof):

```markdown
---
active: true
iteration: 3
session_id: ""
max_iterations: 20
completion_promise: null
started_at: "2026-05-13T22:00:00Z"
---
{
  "pending": [
    {"desc": "Implement carve",  "verify": "grep -q 'def carve' shim.py"},
    {"desc": "Add 5 tests",      "verify": "python3 -m unittest tests.test_shim 2>&1 | grep -q OK"},
    {"desc": "Update SKILL.md",  "verify": null}
  ],
  "completed": []
}
```

### How it works

Each iteration the Stop hook:

1. Parses the body. (Non-JSON falls back to legacy freeform.)
2. For each `pending` item with a `verify` command: runs `bash -c "$verify"`
   with a 30-second timeout.
3. **Items that exit 0** → moved to `completed` (with `iteration` + ISO
   `completed_at` timestamp). **Cheat-proof**: only the hook writes to
   `completed`; agent-injected entries without these fields are visibly
   forged.
4. Items that fail (or have `verify: null`) stay in `pending`.
5. Hook builds the next-iteration prompt from the remaining `pending`
   items and re-feeds it via `{decision: "block", reason: <list>}`.
6. When `pending: []` is empty, the loop ends and the state file is
   removed.

### The agent's contract

- **MAY append new items** to `pending` mid-loop (work discovered during
  iteration). Just JSON-edit the file.
- **MAY edit item descriptions** (clarify scope as you learn).
- **MAY remove `verify: null` items** by deleting them from `pending`
  (trust-based — these are tracked but un-gated).
- **MUST NOT add entries to `completed` directly** — the hook is the
  authoritative writer. Forged entries are obvious in the audit trail
  (missing `iteration` / `completed_at`).
- Setting `verify` on an item means *the hook will check it*. If you
  want trust-based completion, omit `verify` (or set it to `null`).

## Iron Laws

- **Always set `--max-iterations`** as a safety mechanism. The completion
  promise is exact-match — no glob, no regex.
- **Emit the promise only when the criteria are truly met.** False
  promises waste budget and corrupt the iteration data.
- **Write durable state to files.** The loop carries no in-memory context
  between iterations; the assistant relies on files + git history.
- **Loop prompts must be self-contained.** You cannot inject mid-loop.

## Behavior when invoked

If `$ARGUMENTS` is `--cancel`:

1. Check `test -f .kaizen/loop.state.md`.
2. If absent, report "No active Ralph loop found."
3. If present, read iteration via `grep '^iteration:' .kaizen/loop.state.md`,
   then `rm .kaizen/loop.state.md`. Report "Cancelled Ralph loop (was at
   iteration N)."

Otherwise, run the setup script with the given arguments:

```!
"${CLAUDE_PLUGIN_ROOT}/skills/loop/scripts/setup-ralph-loop.sh" $ARGUMENTS
```

Then begin work on the task. When you try to exit, the Stop hook will feed
the same prompt back for the next iteration. You'll see previous work in
files and git history, allowing you to iterate and improve.

**CRITICAL RULE:** If a completion promise is set, you may ONLY output it
when the statement is completely and unequivocally TRUE. Do not output
false promises to escape the loop, even if you think you're stuck or
should exit for other reasons. The loop is designed to continue until
genuine completion.

## Related

- **Workflow routine:** `/workflow schema=ralph-loop` composes the loop with
  workflow-stage discipline (verify gate between iterations).
- **Skill body:** `kaizen:loop` covers the discipline + prompt-writing
  best-practices in detail.
