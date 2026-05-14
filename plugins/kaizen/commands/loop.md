---
description: "Start (or cancel) a self-correcting Ralph loop — cross-CLI"
argument-hint: "PROMPT [--its N] [--promise TEXT] | --cancel"
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
/kaizen:loop --its 30 \
  --item "Implement carve in shim.py|grep -q 'def carve' plugins/kaizen/skills/workflow/scripts/shim.py" \
  --item "Add tests in tests/test_shim.py|python3 -m unittest tests.test_shim 2>&1 | grep -q OK" \
  --item "Update SKILL.md"

# Or import a pre-built ledger JSON file
/kaizen:loop --ledger plan.json --its 30

# Legacy freeform (no verify gate — trust-based)
/kaizen:loop "Build a REST API for todos. Output <promise>DONE</promise> when complete." \
  --its 30 --promise "DONE"

# Cancel the active loop
/kaizen:loop --cancel
```

**Flag aliases:** `--its` ≡ `--max-iterations`. `--promise` ≡ `--completion-promise`.
The short forms are the recommended spelling; long forms preserved for back-compat.

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
     `--promise` (alternate exit, kept for prompt-only workflows).
   - **Iteration cap** — `--its` reached.
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

### The agent's contract — USE THE TOOLS

Direct file edits are possible but discouraged — they bypass schema
validation and can break the loop. Use the controlled surface instead:

| Operation | MCP tool | CLI |
|---|---|---|
| Append a new pending item | `mcp__plugin_kaizen_loop__loop_add_item(desc, verify)` | `kaizen-loop add "desc" [--verify "cmd"]` |
| List pending items | `mcp__plugin_kaizen_loop__loop_list_pending()` | `kaizen-loop list` |
| List completed (audit log) | `mcp__plugin_kaizen_loop__loop_list_completed()` | `kaizen-loop list --completed` |
| Loop status / counts | `mcp__plugin_kaizen_loop__loop_status()` | `kaizen-loop status` |
| Manually complete a `verify: null` item | `mcp__plugin_kaizen_loop__loop_complete_item(id, note)` | `kaizen-loop complete <id> [--note "..."]` |
| **Emit the completion promise (structured)** | `mcp__plugin_kaizen_loop__loop_promise("PHRASE")` | `kaizen-loop promise PHRASE` |
| Cancel the loop | `mcp__plugin_kaizen_loop__loop_cancel()` | `kaizen-loop cancel` |

**Recommended completion signal: the `loop_promise(phrase)` MCP tool.**
The text-tag form (`<promise>PHRASE</promise>`) still works but requires
the tag to be at the message END (after stripping markdown code fences).
The 2026-05-14 incident showed that mid-text mentions in code examples
or Iron-Law docs can trigger the legacy regex; the tool path is
unambiguous because tool calls can't be confused with text content.

The tools enforce three guarantees the agent could otherwise circumvent
via raw file edits:

1. **Schema validation.** Every mutation re-validates the JSON body
   against the `{pending, completed}` schema before writing.
2. **`completed` is hook/tool-only.** `loop_complete_item` records
   `manual: true` + iteration + completed_at; the Stop hook records its
   own without `manual`. Direct edits adding entries are visibly forged
   (no iteration / no completed_at).
3. **Verify-bearing items are gate-locked.** `loop_complete_item` refuses
   any item with a non-null `verify` command — those MUST pass the hook's
   `bash -c "$verify"` exit-0 check. Cannot be manually skipped.

Behavior overrides via raw file edits:
- **MAY** append to pending via raw edit (same effect as `loop_add_item`,
  but no auto-ID; future tool calls may produce duplicate IDs).
- **MUST NOT** edit `completed` directly. Forged entries are visible.
- **MUST NOT** remove `verify`-bearing items without their verify
  passing. The audit log catches this — the user can `kaizen-loop list
  --completed` and see the missing entry.

## Iron Laws

- **Always set `--its`** as a safety mechanism. The completion
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
