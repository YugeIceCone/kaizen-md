---
name: enable-all
description: One-shot kaizen setup. Default scope is project (wires pre-commit gate + indexes the codebase) AND the curated best-default global stack (statusline, shell env, disable-dupes, knowledge index, trace-search index). Heavy / intrusive steps (browser, daemon, trace-proxy) opt-in via --with-* flags. Each underlying installer is idempotent; safe to re-run.
---

# kaizen enable-all

One command, full setup. Runs the curated project + best-default global installers in a deterministic order; each step reports OK / skip / fail; the underlying installers are idempotent so re-running is safe.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/enable_all.sh ${ARGUMENTS}`

## Default behavior (no flags)

**Globals — the curated stack** (run in this order):
1. `disable-dupes` — hide loose `~/.claude/skills/*` that duplicate plugin-bundled skills
2. `statusline install` — wire the kaizen one-line status bar into Claude Code
3. `env install` — append `KAIZEN_ROOT` + aliases to your shell rc
4. `knowledge index` — build the brain / plans / backlog / schemas / persona semantic index
5. `trace-search index` — build the trace event semantic index (uses whatever events exist)

**Project — only if in a git repo:**
6. `install` — wire `.kaizen/hooks/pre-commit` + `core.hooksPath` for this repo
7. `onboard index` — build the project's codebase semantic index at `<repo>/.kaizen/onboard.db`

## Flags

| Flag                  | Effect                                                                  |
|-----------------------|-------------------------------------------------------------------------|
| `--dry-run`           | Print the intended steps, don't execute. Inspect what would run.        |
| `--no-globals`        | Skip the global stack. Project-only run.                                |
| `--no-project`        | Skip the project stack. Global-only run.                                |
| `--with-browser`      | Also install Playwright + Chromium for `mcp__kaizen-browser__*`. ~200MB download. |
| `--with-daemon`       | Also install the auto-daemon (crontab entry for hygiene + cache refresh). |
| `--with-trace-proxy`  | Also start the LLM trace proxy (wraps CC → Anthropic connection).        |
| `--yes` / `-y`        | Skip confirmation prompts (currently no-op; reserved for future).       |

## Why these defaults

The default-global stack are the non-intrusive, broadly-useful steps every kaizen user wants:

- **disable-dupes** — fixes confusion from loose-skill / plugin-skill collisions before they cause silent override bugs.
- **statusline** — costs one line of `settings.json`; visible at a glance whether kaizen is active and what's in the backlog.
- **shell env** — one rc append; makes `kaizen-backlog`, `kaizen-onboard-index`, etc. usable directly from the terminal.
- **knowledge index** — needed for `/kaizen:knowledge search` to work; user-global so once is enough.
- **trace-search index** — same; idempotent re-runs are cheap.

The opt-in stack are the heavy / system-side steps:

- **browser** — downloads Chromium and a Playwright venv (~200MB+); only useful if you actually drive a browser via MCP.
- **daemon** — installs a crontab entry that runs background hygiene every N minutes. Not everyone wants cron-based agents.
- **trace-proxy** — intercepts the CC ↔ Anthropic HTTP connection. Powerful for debugging cost / latency, but it's a network man-in-the-middle and most users skip it.

## Idempotency

Every underlying installer is safe to re-run:

- `kaizen:install` — leaves an existing `.kaizen.toml` as-is.
- `statusline install` — checks if already wired before adding.
- `env install` — appends only if the marker block isn't present.
- `disable-dupes` — already-disabled skills are no-ops.
- All `*-index` runs are sha-deduped — unchanged files are skipped.

So `/kaizen:enable-all` doubles as a "make sure everything is current" command — run it after a fresh plugin update, or whenever you suspect drift.

## Examples

```
/kaizen:enable-all
```
→ Full default setup (globals + project, no heavy opt-ins).

```
/kaizen:enable-all --dry-run
```
→ Print intended steps, execute nothing.

```
/kaizen:enable-all --no-project
```
→ Just the global stack. Useful for setting up a fresh dev machine before cloning anything.

```
/kaizen:enable-all --no-globals
```
→ Just the per-repo stack. Useful when you've already done global setup on this machine.

```
/kaizen:enable-all --with-browser --with-daemon
```
→ Full setup + the Playwright stack + the cron daemon.
