#!/usr/bin/env bash
# kaizen shared library — common helpers sourced by other scripts.
# Provides: realpath_f, repo_root, toml_get, color_init, log_pass/log_fail/log_warn/log_skip.
#
# Source from a sibling script:
#   _LIB_DIR="$(cd "$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"
#   . "$_LIB_DIR/lib.sh"

# Portable real-path (replaces GNU `readlink -f`)
realpath_f() {
    python3 -c "import os, sys; print(os.path.realpath(sys.argv[1]))" "$1"
}

# This script's real directory (works through symlinks)
script_dir() {
    local source="${1:-${BASH_SOURCE[1]}}"
    cd "$(dirname "$(realpath_f "$source")")" && pwd
}

# Git repo root or empty if not a repo
repo_root() {
    git rev-parse --show-toplevel 2>/dev/null || true
}

# Read a key from .kaizen.toml (key = "value" only, no nested tables)
# Usage: val=$(toml_get key [default])
toml_get() {
    local key="$1" default="${2:-}"
    local cfg="${TOML_PATH:-$(repo_root)/.kaizen.toml}"
    [ -f "$cfg" ] || { echo "$default"; return; }
    local v
    v=$(grep -E "^${key}[[:space:]]*=" "$cfg" 2>/dev/null \
        | head -1 \
        | sed -E 's/^[^=]*=[[:space:]]*//; s/^"(.*)"$/\1/; s/^'\''(.*)'\''$/\1/; s/[[:space:]]*#.*$//')
    [ -n "$v" ] && echo "$v" || echo "$default"
}

# ANSI colors (initialised on first call; idempotent)
color_init() {
    if [ -t 2 ] && [ -z "${_GW_COLORS_INIT:-}" ]; then
        BOLD=$'\e[1m'; DIM=$'\e[2m'
        RED=$'\e[31m'; YELLOW=$'\e[33m'; GREEN=$'\e[32m'; BLUE=$'\e[34m'
        RESET=$'\e[0m'
        _GW_COLORS_INIT=1
    elif [ -z "${_GW_COLORS_INIT:-}" ]; then
        BOLD=""; DIM=""; RED=""; YELLOW=""; GREEN=""; BLUE=""; RESET=""
        _GW_COLORS_INIT=1
    fi
}

# Standard log glyphs
log_pass() { color_init; printf '%s✓%s  %s\n' "$GREEN" "$RESET" "$1" >&2; }
log_fail() { color_init; printf '%s✗%s  %s\n' "$RED"   "$RESET" "$1" >&2; }
log_warn() { color_init; printf '%s!%s  %s\n' "$YELLOW" "$RESET" "$1" >&2; }
log_skip() { color_init; printf '%s∘%s  %s\n' "$DIM"    "$RESET" "$1" >&2; }
log_info() { color_init; printf '   %s\n' "$1" >&2; }

# Resolve a sibling script via 3-tier search
# Usage: sibling=$(find_sibling backlog.py)
find_sibling() {
    local name="$1"
    local hint_dir="${2:-${BASH_SOURCE[1]%/*}}"
    hint_dir=$(cd "$hint_dir" 2>/dev/null && pwd)
    for candidate in \
        "${CLAUDE_PLUGIN_ROOT:-/__unset__}/skills/kaizen/scripts/$name" \
        "$hint_dir/$name" \
        "$HOME/.claude/skills/kaizen/scripts/$name"; do
        if [ -f "$candidate" ]; then
            echo "$candidate"
            return
        fi
    done
    return 1
}
