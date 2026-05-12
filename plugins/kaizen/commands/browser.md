---
name: browser
description: Manage the Playwright-backed MCP browser server that gives Claude real browser-driving tools (navigate, click, type, screenshot, extract). Subcommands: install | check | status | path | fg. After install + /reload-plugins, Claude can use mcp__kaizen-browser__* tools — every action traces through PreToolUse/PostToolUse to kaizen-trace.
argument-hint: [install|check|status|path|fg]
---

# kaizen browser

!`bash ${CLAUDE_PLUGIN_ROOT}/bin/kaizen-browser ${ARGUMENTS:-check}`
