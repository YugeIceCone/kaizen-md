#!/usr/bin/env bash
# kaizen plugin-root resolver — single source for "where is this plugin installed".
#
# Source this file at the top of any kaizen .sh script that needs to
# reference the plugin's own files (hooks, MCP entrypoints, scripts):
#
#     _SCRIPT_REAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#     source "$_SCRIPT_REAL_DIR/_plugin_root.sh"
#     ROOT="$(kaizen_plugin_root)"
#
# Resolution order (first hit wins):
#   1. $CLAUDE_PLUGIN_ROOT  if set and points at a kaizen plugin dir
#   2. $KAIZEN_PLUGIN_ROOT  if set and points at a kaizen plugin dir
#   3. derived from this file's own path by walking up to find
#      .claude-plugin/plugin.json
#
# A "kaizen plugin dir" is any dir containing .claude-plugin/plugin.json.
# This makes the helper work across Claude Code (sets $CLAUDE_PLUGIN_ROOT
# at hook-fire time), Codex CLI (no env at all → script-derived), or any
# other host that prefers to set $KAIZEN_PLUGIN_ROOT explicitly.

# Returns 0 + prints path on success; returns 1 + prints nothing on failure.
kaizen_plugin_root() {
    local candidate

    if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] \
            && [ -f "$CLAUDE_PLUGIN_ROOT/.claude-plugin/plugin.json" ]; then
        echo "$CLAUDE_PLUGIN_ROOT"
        return 0
    fi

    if [ -n "${KAIZEN_PLUGIN_ROOT:-}" ] \
            && [ -f "$KAIZEN_PLUGIN_ROOT/.claude-plugin/plugin.json" ]; then
        echo "$KAIZEN_PLUGIN_ROOT"
        return 0
    fi

    # Walk up from this file's directory looking for plugin.json.
    candidate="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    while [ "$candidate" != "/" ] && [ -n "$candidate" ]; do
        if [ -f "$candidate/.claude-plugin/plugin.json" ]; then
            echo "$candidate"
            return 0
        fi
        candidate="$(dirname "$candidate")"
    done

    return 1
}
