# Ralph Loop Commands

Platform-specific commands for the `loop` skill on Codex.

## Starting a Loop

```bash
/ralph-loop "<task prompt>" --max-iterations <n> --completion-promise "<phrase>"
```

Options:
- `--max-iterations <n>` -> stop after N iterations; always set this as a safety limit
- `--completion-promise <phrase>` -> exact phrase the agent must emit inside `<promise>` tags to signal success

## Cancelling a Loop

```bash
/cancel-ralph
```

## Loop State File

`.codex/ralph-loop.local.md` in the project root — do not rely on in-memory state between iterations.

## Platform Note

Hooks are currently disabled on Windows per the Codex hooks spec. The loop skill requires hooks and will not function on Windows until Codex re-enables hook support for that platform.
