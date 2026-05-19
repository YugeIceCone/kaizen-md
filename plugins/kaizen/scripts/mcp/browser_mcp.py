#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
#     "playwright>=1.40",
# ]
# ///
"""kaizen browser-mcp — FastMCP server wrapping Playwright for Claude.

Exposes a minimal browser-driving tool surface so Claude (the LLM in
Claude Code) can navigate real web pages, click, type, screenshot, and
extract content. Every tool call flows through Claude Code's normal
PreToolUse/PostToolUse boundary → automatically traces into
`kaizen-trace src=hook tool=mcp__kaizen-browser__*`.

## Install

This script is **PEP 723** + uv. Deps auto-install on first run via the
inline script-metadata block above. You only need:

    1. uv on PATH                 (curl -LsSf https://astral.sh/uv/install.sh | sh)
    2. Chromium binary            uv run --with playwright python -m playwright install chromium

Or invoke `kaizen-browser install` which handles both. Subsequent runs
hit the uv cache and start in milliseconds.

## Tools exposed

    open_browser(headless=False)        Launch Chromium + page
    close_browser()                     Tear down (auto-runs on shutdown)
    navigate(url)                       Go to URL, wait for load
    click(selector)                     CSS / text= / role= selector
    type_text(selector, text)           Fill an input
    press_key(key)                      Enter, Tab, Escape, ArrowDown, …
    get_text(selector=None)             inner_text of selector or whole page
    get_html(selector=None)             outerHTML of selector or document
    screenshot(path=None,
               full_page=False)         PNG, returns path; CC's Read tool
                                        renders it as an image
    evaluate(js)                        Run JS in page context
    wait_for(selector,
             timeout_ms=10000)          Wait for selector to attach
    current_url()                       Where are we?
    list_links()                        All href targets on the page
    list_inputs()                       All form fields (name+type+value)

## Why this shape

KISS: 14 tools covering 95% of browser work without bloating Claude's
tool list. No ai-native `act(intent)` semantics — that lives in
browser-use; this one is primitives. Combine with Claude's planning
(it knows CSS / DOM patterns) for full control without a second LLM
in the loop.

State: single browser, single page, persists across tool calls until
`close_browser()` or MCP server shutdown. Multi-tab is one tool call
away if needed (deferred — YAGNI).

## Dependencies

Hard: uv on PATH, Python 3.10+ (uv manages this — its cache pulls the
right interpreter), `mcp` (FastMCP API), `playwright` (sync_api),
Chromium installed via `playwright install chromium`.

When the MCP server is launched by Claude Code (`command: "uv"` in
`.mcp.json`), uv reads the inline-script-metadata block at the top of
this file, resolves a cached venv at `~/.cache/uv/...`, and starts the
server. Cold-start (first ever launch): ~30 s for dep install. Warm
starts: under a second.

Tracing: trace events fire via the normal CC hook chain — no
in-script trace calls needed (the kaizen PreToolUse / PostToolUse
hooks pick up every mcp__* invocation).
"""

from __future__ import annotations

import sys

from fastmcp import FastMCP

try:
    from playwright.async_api import async_playwright, Browser, Page, Playwright
    _PLAYWRIGHT_AVAILABLE = True
    _PLAYWRIGHT_ERR = ""
except ImportError as e:  # pragma: no cover
    _PLAYWRIGHT_AVAILABLE = False
    _PLAYWRIGHT_ERR = str(e)


mcp = FastMCP("browser")

# Module-global state — single browser per server lifetime.
# FastMCP runs in an asyncio event loop; we use async_playwright accordingly.
_pw_cm = None  # the context manager (so we can __aexit__ on close)
_pw: Playwright | None = None
_browser: Browser | None = None
_page: Page | None = None


def _ensure_page() -> Page:
    if _page is None:
        raise RuntimeError(
            "browser not open — call open_browser() first"
        )
    return _page


# ─── Lifecycle ────────────────────────────────────────────────────────


@mcp.tool()
async def open_browser(headless: bool = False, viewport_width: int = 1280, viewport_height: int = 800) -> str:
    """Launch Chromium and open a fresh page.

    headless=False shows the browser window (helpful for development /
    debugging); headless=True runs invisible (best for CI / batch work).
    Idempotent: calling again returns "already open" without relaunching.
    """
    if not _PLAYWRIGHT_AVAILABLE:
        return (
            f"error: playwright not installed ({_PLAYWRIGHT_ERR}). "
            "Run: uv run --with playwright python -m playwright install chromium"
        )
    global _pw_cm, _pw, _browser, _page
    if _page is not None:
        return f"already open at {_page.url}"
    _pw_cm = async_playwright()
    _pw = await _pw_cm.__aenter__()
    _browser = await _pw.chromium.launch(headless=headless)
    ctx = await _browser.new_context(viewport={"width": viewport_width, "height": viewport_height})
    _page = await ctx.new_page()
    return f"opened (headless={headless}, viewport={viewport_width}x{viewport_height})"


@mcp.tool()
async def close_browser() -> str:
    """Tear down browser + Playwright. Safe to call when already closed."""
    global _pw_cm, _pw, _browser, _page
    if _browser is not None:
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None
    if _pw_cm is not None:
        try:
            await _pw_cm.__aexit__(None, None, None)
        except Exception:
            pass
        _pw_cm = None
    _pw = None
    _page = None
    return "closed"


# ─── Navigation ───────────────────────────────────────────────────────


@mcp.tool()
async def navigate(url: str, wait_until: str = "load") -> str:
    """Navigate to URL. wait_until: load | domcontentloaded | networkidle | commit."""
    page = _ensure_page()
    await page.goto(url, wait_until=wait_until)  # type: ignore[arg-type]
    return f"navigated to {page.url}"


@mcp.tool()
async def current_url() -> str:
    return _ensure_page().url


# ─── Interaction ──────────────────────────────────────────────────────


@mcp.tool()
async def click(selector: str, timeout_ms: int = 10000) -> str:
    """Click an element. Selector: CSS, `text=...`, `role=...`, or any Playwright locator syntax."""
    page = _ensure_page()
    await page.locator(selector).click(timeout=timeout_ms)
    return f"clicked {selector!r}"


@mcp.tool()
async def type_text(selector: str, text: str, timeout_ms: int = 10000) -> str:
    """Fill an input/textarea with the given text (clears existing value first)."""
    page = _ensure_page()
    await page.locator(selector).fill(text, timeout=timeout_ms)
    return f"typed {len(text)} chars into {selector!r}"


@mcp.tool()
async def press_key(key: str) -> str:
    """Press a keyboard key. Common: Enter, Tab, Escape, ArrowDown, ArrowUp, Backspace."""
    await _ensure_page().keyboard.press(key)
    return f"pressed {key}"


@mcp.tool()
async def wait_for(selector: str, timeout_ms: int = 10000, state: str = "visible") -> str:
    """Wait for selector. state: attached | detached | visible | hidden."""
    page = _ensure_page()
    await page.locator(selector).wait_for(state=state, timeout=timeout_ms)  # type: ignore[arg-type]
    return f"saw {selector!r} ({state})"


# ─── Extraction ───────────────────────────────────────────────────────


@mcp.tool()
async def get_text(selector: str = "body") -> str:
    """inner_text of the selector (default: whole page body)."""
    return await _ensure_page().locator(selector).inner_text()


@mcp.tool()
async def get_html(selector: str = "html") -> str:
    """outerHTML of the selector (default: whole document)."""
    return await _ensure_page().locator(selector).evaluate("e => e.outerHTML")


@mcp.tool()
async def screenshot(path: str = "/tmp/kaizen-browser.png", full_page: bool = False) -> str:
    """Save PNG screenshot. Read with the Read tool to view as image in CC."""
    await _ensure_page().screenshot(path=path, full_page=full_page)
    return path


@mcp.tool()
async def list_links() -> list[dict]:
    """All anchor hrefs visible in the document."""
    page = _ensure_page()
    return await page.evaluate(
        "() => Array.from(document.querySelectorAll('a[href]'))"
        "  .map(a => ({text: a.innerText.trim().slice(0, 80), href: a.href}))"
        "  .filter(l => l.text)"
        "  .slice(0, 50)"
    )


@mcp.tool()
async def list_inputs() -> list[dict]:
    """All form inputs (input/select/textarea) with name+type+current-value."""
    page = _ensure_page()
    return await page.evaluate(
        "() => Array.from(document.querySelectorAll('input, select, textarea'))"
        "  .map(e => ({"
        "    tag: e.tagName.toLowerCase(),"
        "    type: e.type || null,"
        "    name: e.name || e.id || null,"
        "    placeholder: e.placeholder || null,"
        "    value: e.value || null,"
        "  }))"
        "  .filter(i => i.name || i.placeholder)"
        "  .slice(0, 30)"
    )


# ─── Power tool ───────────────────────────────────────────────────────


@mcp.tool()
async def evaluate(js_expression: str) -> str:
    """Run an arbitrary JS expression in the page; return JSON-serializable result as string.

    Use sparingly — prefer the typed tools above. Useful for: scrollTo,
    custom DOM queries, accessing page state not covered elsewhere.
    """
    result = await _ensure_page().evaluate(js_expression)
    return repr(result)


# ─── Entry ────────────────────────────────────────────────────────────


if __name__ == "__main__":
    if not _PLAYWRIGHT_AVAILABLE:
        sys.stderr.write(
            f"kaizen-browser-mcp: missing dependency: {_PLAYWRIGHT_ERR}\n"
            "This script uses PEP 723 inline metadata — deps should auto-install\n"
            "via uv when launched as `uv run --script <path>`.\n"
            "\n"
            "If you're running it directly with python3, install manually:\n"
            "  pip install --user mcp playwright\n"
            "  python -m playwright install chromium\n"
            "\n"
            "Or run: kaizen-browser install (uses uv).\n"
        )
        sys.exit(1)
    mcp.run()
