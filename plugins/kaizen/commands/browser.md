---
name: browser
description: Manage the Playwright-backed MCP browser server that gives Claude real browser-driving tools (navigate, click, type, screenshot, extract). Subcommands: install | check | status | path | fg. After install + /reload-plugins, Claude can use mcp__kaizen-browser__* tools — every action traces through PreToolUse/PostToolUse to kaizen-trace.
---

# kaizen browser

Lets Claude drive a real Chromium window via Playwright. ~14 tools (navigate / click / type / screenshot / extract). Every call flows through CC's normal tool boundary → automatically traces to `kaizen-trace` like any other tool. No second LLM in the loop — Claude plans the selectors itself.

!`bash ${CLAUDE_PLUGIN_ROOT}/bin/kaizen-browser ${ARGUMENTS:-check}`

## First-time setup

Requires **`uv`** on PATH (not pip). uv handles the Python env + deps via PEP 723 inline script metadata at the top of `browser_mcp.py` — auto-installed on first MCP server launch.

```bash
# 1. Install uv if not already (one-time, system-wide)
curl -LsSf https://astral.sh/uv/install.sh | sh
# or: brew install uv | pipx install uv

# 2. Warm the uv cache + download Chromium binary
/kaizen:browser install
#   → uv resolves mcp + playwright, caches to ~/.cache/uv/
#   → playwright install chromium (~150 MB, one-time)

# 3. Activate
/reload-plugins              # CC picks up the new MCP server from .mcp.json
/kaizen:browser status       # verify wiring
```

The .mcp.json entry is `command: "uv"`, `args: ["run", "--script", "${CLAUDE_PLUGIN_ROOT}/.../browser_mcp.py"]` — uv reads the script's `# /// script ... ///` block and resolves deps without ever calling pip. Cold start: ~30 s on first install. Warm starts: <1 s.

Then in any CC conversation, Claude has these tools:

| Tool | Purpose |
|---|---|
| `mcp__kaizen-browser__open_browser` | launch Chromium (`headless=False` shows the window) |
| `mcp__kaizen-browser__navigate` | go to URL |
| `mcp__kaizen-browser__click` | click by CSS / `text=…` / `role=…` selector |
| `mcp__kaizen-browser__type_text` | fill input/textarea |
| `mcp__kaizen-browser__press_key` | Enter / Tab / Escape / Arrow keys |
| `mcp__kaizen-browser__wait_for` | wait for selector (attached / visible / detached / hidden) |
| `mcp__kaizen-browser__get_text` | inner_text of selector (default: whole body) |
| `mcp__kaizen-browser__get_html` | outerHTML of selector (default: whole document) |
| `mcp__kaizen-browser__screenshot` | PNG → file path → CC's Read tool renders as image |
| `mcp__kaizen-browser__list_links` | all visible `<a href>` (text + URL, capped at 50) |
| `mcp__kaizen-browser__list_inputs` | all form fields with name+type+value (capped at 30) |
| `mcp__kaizen-browser__evaluate` | run arbitrary JS in page (power-tool, use sparingly) |
| `mcp__kaizen-browser__current_url` | where the page is now |
| `mcp__kaizen-browser__close_browser` | tear down |

## Subcommands (this slash command)

| arg | effect |
|---|---|
| (none) or `check` | verify Python deps + Chromium binary; exit 0/1 |
| `install [pip args]` | `pip install --user mcp playwright` + `python -m playwright install chromium` |
| `status` | show MCP registration state from `.mcp.json` + script path |
| `path` | print absolute path to `browser_mcp.py` |
| `fg` | run the MCP server in foreground (debugging only — CC normally spawns it on-demand via .mcp.json) |

## Lifecycle

The MCP server is **spawned on-demand** by Claude Code when you first invoke any `mcp__kaizen-browser__*` tool. It stays alive for the rest of the CC session and is torn down at session exit. Between tool calls, browser state (current page, cookies, scroll position) persists — so multi-step workflows just work.

`open_browser()` is the explicit init (lets you set `headless`, viewport). After it, every other tool operates on the single live page. `close_browser()` ends the session — or just let it die with the MCP server at CC exit.

## Composition with other kaizen layers

- **Trace**: every tool call fires `PreToolUse-*` / `PostToolUse-*` hooks → `kaizen-trace --src hook tool=mcp__kaizen-browser__*` for replay + latency stats.
- **LLM proxy**: if you have `ANTHROPIC_BASE_URL=http://127.0.0.1:8765` set, Claude's planning (deciding which selector to click) also traces under `src=llm`. End-to-end visibility.
- **Inbox**: messages you type while Claude is mid-browser-workflow surface on the next tool boundary via the inbox hook.

## Why not browser-use / Stagehand / others

`browser-use` adds an AI-planning layer (uses its OWN model to decide actions). That's powerful but adds latency + cost + a second model to maintain. `kaizen-browser` exposes primitives only — Claude does the planning natively. Fewer moving parts, full visibility, fits the kaizen "minimum-correct + maximum-trace" style. If you find the primitives too low-level for a complex workflow, layer `browser-use` on top (its tools can call these as low-level ops — but YAGNI until proven).

## Caveats

- **First-run cost**: Playwright Chromium download is ~150 MB. One-time.
- **Display**: `headless=False` requires a display (`$DISPLAY` set, X11/Wayland running). On a headless server use `headless=True` (default-screenshot works regardless).
- **Site bans**: some sites detect automation and block. Use `headless=True` + custom user-agent + slow-typing if you hit this — but ethics first: respect robots.txt and ToS.
- **Auth**: cookies survive within one CC session via the persistent browser context. For longer-lived sessions, set Playwright `storage_state` (deferred — YAGNI).
