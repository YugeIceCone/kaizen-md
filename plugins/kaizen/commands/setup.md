---
name: setup
description: "Unified kaizen setup. No-args → interactive QA super-menu (master action picker → branched install / uninstall / health / maintenance flows). With-args → direct dispatch (install / uninstall / cache + --enable-all / --with-* / --no-*). Triggers on \"install kaizen\", \"setup the plugin\", \"enable kaizen\", \"uninstall kaizen\", \"kaizen cache\", \"setup menu\", \"reconfigure kaizen\", \"kaizen maintenance\", \"first-time setup\"."
argument-hint: "(empty = interactive super-menu) | [install|uninstall|cache ...] [--enable-all] [--with-index] [--with-browser] [--with-daemon] [--with-trace-proxy] [--no-globals] [--no-project] [--dry-run]"
allowed-tools: ["AskUserQuestion", "Bash(bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/setup.sh:*)", "Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/detect_stack.py:*)", "Bash(kaizen-detect-stack:*)"]
---

# kaizen setup

One entry point for activating, deactivating, inspecting, **and maintaining**
kaizen in this repo. **Local-only** (per-clone `core.hooksPath`); never
touches global git config.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/setup.sh $ARGUMENTS`

## Interactive super-menu (when `$ARGUMENTS` is empty)

When the user invokes `/kaizen:setup` with **no arguments**, the body above
runs `setup.sh` with no args — which prints the help/status. The agent
SHOULD ALSO step the user through the AskUserQuestion super-menu below,
then re-call this command with the resolved args (or dispatch a sibling
slash for non-setup ops).

Follow the `/kaizen:workflow` orchestration pattern: the body is
instructional, the agent does the AskUserQuestion calls. The super-menu
is **branching** — Q1 is a single-question call; the per-branch
follow-ups run in a separate AskUserQuestion call once Q1 is answered.
This keeps every call within the 4-option-per-question / 4-question-per-call
contract.

### Question 1 — master action picker

```
question:    "What do you want to do?"
header:      "Action"
multiSelect: false
options:
  - label: "Install / re-install"
    description: "Set up (or refresh) the per-repo gate. Branches into Default / Custom / Reconfigure / Cache."
  - label: "Uninstall"
    description: "Reverse the per-repo install. Default dry-run; confirm to apply."
  - label: "Health check"
    description: "Run /kaizen:health (read-only diagnostic, no install changes)."
  - label: "Maintenance"
    description: "Hygiene / update / backup / cache ops on an existing install."
```

Routing:

- **Install / re-install** → Q2 (install-mode picker)
- **Uninstall** → Q-Uninstall (dry-run yes/no), then `/kaizen:setup uninstall [--execute]`
- **Health check** → dispatch `/kaizen:health` and stop
- **Maintenance** → Q-Maintenance (which op)

### Question 2 (install path) — install mode

```
question:    "Install mode?"
header:      "Mode"
multiSelect: false
options:
  - label: "Default (detect-stack)"
    description: "Auto-pick add-ons from the project stack (Rust → indexes; monorepo → browser; Dockerfile → daemon). Single confirm step."
  - label: "Custom"
    description: "Step through scope + opt-in add-ons + dry-run wizard."
  - label: "Reconfigure"
    description: "Re-run install over an existing one to change flags. Same wizard as Custom."
  - label: "Cache stats"
    description: "Inspect the per-repo .kaizen/cache/ state (no install changes)."
```

Routing:

- **Default** → resolve detect-stack defaults (see "Default-mode flag synthesis" below), then Q-Confirm
- **Custom** / **Reconfigure** → Q3 + Q4 + Q5 (the 3-question custom wizard, one AskUserQuestion call)
- **Cache stats** → dispatch `/kaizen:setup cache` and stop

### Question 3 (custom / reconfigure) — scope

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

### Question 4 (custom / reconfigure) — opt-in add-ons

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

### Question 5 — dry-run preview

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

Used by: Custom install (Q5), Reconfigure (Q5), Uninstall (Q-Uninstall),
Default confirm (Q-Confirm). Default install reuses the Q5 options verbatim
in its single follow-up call.

### Question 6 (maintenance path) — which op

```
question:    "Maintenance operation?"
header:      "Op"
multiSelect: false
options:
  - label: "Hygiene"
    description: "Run /kaizen:hygiene — prune stale cache/inbox, validate rules, render backlog."
  - label: "Update"
    description: "Run /kaizen:update — git pull marketplace + refresh CC cache + auto-reload."
  - label: "Backup"
    description: "Run /kaizen:backup create — snapshot .kaizen/ + optional brain to ~/.claude/backups/kaizen/."
  - label: "Cache CRUD"
    description: "Run /kaizen:setup cache — inspect / mutate the per-repo hash cache."
```

### Default-mode flag synthesis

When Q2 = **Default**, the agent assembles `--with-*` flags from the
project's stack signals BEFORE asking the confirm question. Two paths:

1. **Existing `.agents/stack-context.md`** (preferred — already mined):
   read it; map signals → flags per the table below.
2. **Fresh detect** (if no artifact): run
   `python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/detect_stack.py scan --force`
   (writes `.agents/stack-context.md`), then read it.

Signal → flag mapping:

| Detected signal              | Flag added                |
|------------------------------|---------------------------|
| Rust (Cargo.toml present)    | `--with-index`            |
| Monorepo (≥3 manifests OR `pnpm-workspace.yaml` / `workspaces` block) | `--enable-all --with-browser` |
| Dockerfile / docker-compose  | `--with-daemon`           |
| TypeScript / Next.js project | `--with-index`            |
| Python (pyproject.toml)      | `--with-index`            |
| (none detected)              | (no add-ons; base install) |

Always include `--enable-all` for Default (the curated path). Show the
resolved flag set in the confirm question's `description` so the user
sees what Default decided.

### Question 7 (uninstall path) — dry-run

Reuse Q5's options. Map: Yes → `--dry-run` (or omit; uninstall.sh
defaults to dry-run), No → `--execute`.

### Arg assembly

After the branch's question chain is answered, assemble the
`setup.sh` invocation and re-call this slash:

| Q1 answer       | Base command                              |
|-----------------|-------------------------------------------|
| Install         | `install` (or omit — same default)        |
| Uninstall       | `uninstall`                               |
| Health check    | (dispatch `/kaizen:health` instead)       |
| Maintenance     | (dispatch the Q6-picked sibling slash)    |

| Q2 answer (install path) | Behavior                                                              |
|--------------------------|-----------------------------------------------------------------------|
| Default                  | Append `--enable-all` + synthesized `--with-*` flags + Q-Confirm dry-run choice |
| Custom                   | Continue to Q3/Q4/Q5 → assemble flags                                  |
| Reconfigure              | Same as Custom (idempotent — install overwrites hook symlinks)         |
| Cache stats              | Dispatch `/kaizen:setup cache` (no further setup args)                 |

| Q3 answer            | Flags appended       |
|----------------------|----------------------|
| Project only         | (no `--enable-all`)  |
| Project + global     | `--enable-all`       |
| Globals only         | `--enable-all --no-project` |

| Q4 multi-select pick | Flag appended (per pick)        |
|----------------------|---------------------------------|
| Semantic indexes     | `--with-index`                  |
| Playwright browser   | `--with-browser`                |
| Auto-daemon          | `--with-daemon`                 |
| LLM trace proxy      | `--with-trace-proxy`            |

| Q5 answer            | Flag appended        |
|----------------------|----------------------|
| Yes (dry-run)        | `--dry-run`          |
| No (apply)           | `--execute` (or omit for default) |

| Q6 answer (maintenance) | Slash dispatched              |
|-------------------------|-------------------------------|
| Hygiene                 | `/kaizen:hygiene`             |
| Update                  | `/kaizen:update`              |
| Backup                  | `/kaizen:backup create`       |
| Cache CRUD              | `/kaizen:setup cache`         |

After assembly, RE-INVOKE: `/kaizen:setup <assembled-args>` (the
top-of-file `!` block fires `setup.sh` with the resolved flags). For
the Maintenance + Health branches, dispatch the sibling slash directly
— `setup.sh` does not own those surfaces.

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

## Reconfigure semantics

"Reconfigure" is **not a new subcommand** — it's re-running `install`
over an existing install with different `--with-*` / `--no-*` flags.
The install path is idempotent: hook symlinks get re-pointed, the
plugin loc index is skipped if already seeded, and `.kaizen.toml` is
left alone (won't clobber user edits). Use it to flip add-ons on/off
or change scope after the initial install.

## Maintenance dispatch — why it's not a subcommand

Hygiene / update / backup are existing first-class slashes
(`/kaizen:hygiene`, `/kaizen:update`, `/kaizen:backup`). The super-menu
routes there rather than wrapping them; setup.sh stays focused on
install/uninstall/cache. This keeps each tool's permissions narrow and
its surface independently testable.

## The cache subcommand

`/kaizen:setup cache` is the per-repo hash-keyed JSON cache at
`<repo>/.kaizen/cache/` — hash-invalidated, no TTL. Used by the
compile-barrier check to skip redundant `cargo check` / `tsc --noEmit`
runs when staged content is unchanged, and by agents to memoize
verdicts by diff sha. Programmatic access via the `kaizen-state` MCP
server: `state_cache_stats()` returns `{count, bytes, dir, exists}`.
Mutating ops (`put`, `delete`, `clear`) stay slash-only.
