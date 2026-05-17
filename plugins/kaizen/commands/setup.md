---
name: setup
description: "Unified kaizen setup. No-args → interactive QA menu (4 AskUserQuestion steps). With-args → direct dispatch (install / uninstall / cache + --enable-all / --with-* / --no-*). Triggers on \"install kaizen\", \"setup the plugin\", \"enable kaizen\", \"uninstall kaizen\", \"kaizen cache\", \"setup menu\", \"first-time setup\"."
argument-hint: "(empty = interactive menu) | [install|uninstall|cache ...] [--enable-all] [--with-index] [--with-browser] [--with-daemon] [--with-trace-proxy] [--no-globals] [--no-project] [--dry-run]"
allowed-tools: ["AskUserQuestion", "Bash(bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/setup.sh:*)"]
---

# kaizen setup

One entry point for activating, deactivating, and inspecting kaizen in
this repo. **Local-only** (per-clone `core.hooksPath`); never touches
global git config.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/setup.sh $ARGUMENTS`

## Interactive menu (when `$ARGUMENTS` is empty)

When the user invokes `/kaizen:setup` with **no arguments**, the body
above runs `setup.sh` with no args — which prints the help/status.
The agent SHOULD ALSO step the user through a 4-question
AskUserQuestion flow to assemble the right invocation, then re-call
this command with the resolved args.

Follow the `/kaizen:session-mode` orchestration pattern: the body is
instructional, the agent does the AskUserQuestion calls.

### Question 1 — top-level action

```
question:    "What do you want to do?"
header:      "Action"
multiSelect: false
options:
  - label: "Install (gate this repo)"
    description: "Activate the per-repo pre-commit gate. Recommended for new clones."
  - label: "Uninstall"
    description: "Reverse the per-repo install. Default dry-run; --execute to apply."
  - label: "Cache stats"
    description: "Inspect the per-repo hash cache (compile-barrier memo)."
  - label: "Health-check only"
    description: "Run /kaizen:health (no install changes)."
```

- **Install** → continue to Q2/Q3/Q4 below
- **Uninstall** → ask Q4 (dry-run?) only, then `/kaizen:setup uninstall [--execute]`
- **Cache stats** → dispatch `/kaizen:setup cache` and stop
- **Health-check** → dispatch `/kaizen:health` and stop

### Question 2 (install path) — scope

```
question:    "Install scope?"
header:      "Scope"
multiSelect: false
options:
  - label: "Project only"
    description: "Per-repo gate (pre-commit hook + .kaizen.toml). Default for clones."
  - label: "Project + global stack"
    description: "Gate PLUS the curated globals (disable-dupes, statusline, shell env)."
  - label: "Globals only"
    description: "Skip per-repo install — set up the user-global stack only."
```

### Question 3 (install path) — opt-in add-ons

```
question:    "Optional add-ons?"
header:      "Add-ons"
multiSelect: true
options:
  - label: "Semantic indexes (knowledge + trace + onboard)"
    description: "First-run downloads sentence-transformers; slow but cached after."
  - label: "Playwright browser"
    description: "Chromium for MCP browser tools (~200MB download)."
  - label: "Auto-daemon (cron)"
    description: "Hygiene + cache-refresh on a schedule."
  - label: "LLM trace proxy"
    description: "Wraps CC → Anthropic in a logging proxy. Useful for debugging."
```

### Question 4 — dry-run preview

```
question:    "Run as dry-run first?"
header:      "Dry-run"
multiSelect: false
options:
  - label: "Yes (recommended)"
    description: "Print what would happen, don't change anything."
  - label: "No — apply now"
    description: "Skip preview, run the install/uninstall directly."
```

### Arg assembly

Map answers to `setup.sh` flags:

| Q1 answer            | Base command         |
|----------------------|----------------------|
| Install              | `install` (default — omit) |
| Uninstall            | `uninstall`          |
| Cache stats          | `cache`              |
| Health-check         | (dispatch `/kaizen:health` instead) |

| Q2 answer            | Flags appended       |
|----------------------|----------------------|
| Project only         | (no `--enable-all`)  |
| Project + global     | `--enable-all`       |
| Globals only         | `--enable-all --no-project` |

| Q3 multi-select pick | Flag appended (per pick)        |
|----------------------|---------------------------------|
| Semantic indexes     | `--with-index`                  |
| Playwright browser   | `--with-browser`                |
| Auto-daemon          | `--with-daemon`                 |
| LLM trace proxy      | `--with-trace-proxy`            |

| Q4 answer            | Flag appended        |
|----------------------|----------------------|
| Yes (dry-run)        | `--dry-run`          |
| No (apply)           | `--execute` (or omit for default) |

After assembly, RE-INVOKE: `/kaizen:setup <assembled-args>` (the
top-of-file `!` block fires `setup.sh` with the resolved flags).

## Subcommands

| Invocation | What runs |
|---|---|
| `/kaizen:setup` *(or)* `/kaizen:setup install` | Per-repo gate (pre-commit + commit-msg hooks, `.kaizen.toml`, backlog seed) + a cache check. Default. |
| `/kaizen:setup --enable-all` | The gate **plus** the curated global stack (disable-dupes, statusline, shell env). Any `--with-*` / `--no-*` flag also triggers this path. |
| `/kaizen:setup uninstall` | Reverse per-repo activation. Default dry-run; `--execute` to apply, auto-backs up first. Does NOT uninstall the plugin (use `/plugin uninstall`). |
| `/kaizen:setup cache [stats\|key\|get\|put\|delete\|clear]` | Inspect / mutate the per-repo hash cache at `<repo>/.kaizen/cache/`. No arg = `stats`. |

## Opt-in flags (forwarded to the `--enable-all` path)

- `--with-index` — knowledge + trace + onboard indexers (slow first run)
- `--with-browser` — Playwright + Chromium (~200MB download)
- `--with-daemon` — crontab entry for hygiene + cache-refresh
- `--with-trace-proxy` — HTTP proxy wrapping CC → Anthropic
- `--no-globals` — skip the curated global stack (project only)
- `--no-project` — skip per-repo install (globals only)
- `--dry-run` — print what would run, don't execute

## What the per-repo install does

1. Creates `.kaizen/hooks/` and symlinks `pre-commit` + `commit-msg` → the plugin's hook scripts
2. Sets `git config core.hooksPath .kaizen/hooks` (LOCAL only)
3. Auto-detects workflow-state dir (priority: `.kaizen/workflow/` post-v1.22 unify, then legacy `.workflow/`, then `docs/workflow/`, greenfield defaults to `.kaizen/workflow/`)
4. Writes a starter `.kaizen.toml` if absent
5. Seeds `.kaizen/workflow/backlog.json` + renders `backlog.md` at the detected location
6. Writes `.kaizen/.gitignore` per-dir policy (ignores ephemeral cache/hooks/trace/, tracks durable workflow/ artifacts)
7. Cache check — surfaces the per-repo `.kaizen/cache/` state
8. Seeds the **plugin loc index** — a fast, stdlib-only line/function
   index of the kaizen plugin source itself (`KAIZEN_PLUGIN_INDEX_DISABLE=1`
   to skip). `--enable-all` additionally starts the watch daemon that
   keeps both the loc and semantic indexes continuously fresh.

After install: smoke-test with `git commit --allow-empty -m 'test(gate): smoke'`. Reverse with `/kaizen:setup uninstall`.

## The cache subcommand

`/kaizen:setup cache` is the per-repo hash-keyed JSON cache at
`<repo>/.kaizen/cache/` — hash-invalidated, no TTL. Used by the
compile-barrier check to skip redundant `cargo check` / `tsc --noEmit`
runs when staged content is unchanged, and by agents to memoize
verdicts by diff sha. Programmatic access via the `kaizen-state` MCP
server: `state_cache_stats()` returns `{count, bytes, dir, exists}`.
Mutating ops (`put`, `delete`, `clear`) stay slash-only.
