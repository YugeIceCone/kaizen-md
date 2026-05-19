#!/usr/bin/env bash
# kaizen bootstrap — provision the plugin's uv-managed Python surface.
#
# The kaizen plugin's Python scripts are PEP-723 `uv run --script`
# scripts: each declares its own dependencies in a `# /// script`
# block and uv builds + caches a per-script venv on first run. This
# script pre-warms every one of those venvs so the first real
# invocation is not a cold download.
#
#   bootstrap.sh            pre-warm every uv-script venv
#   bootstrap.sh --check    only verify uv is installed (no pre-warm)
#   bootstrap.sh --list     list the uv-script files, run nothing
#
# Exit 0 = uv present (+ pre-warm attempted); non-zero = uv missing.
# Bypass the pre-warm with KAIZEN_BOOTSTRAP_DISABLE=1.

set -uo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# bootstrap.sh lives at skills/workflow/scripts/ — plugin root is up 3.
PLUGIN_ROOT="$(cd "$_SCRIPT_DIR/../../.." && pwd)"

MODE="${1:-prewarm}"

# 1. uv must be installed — the one hard external dependency for the
#    plugin's Python surface.
if ! command -v uv >/dev/null 2>&1; then
    echo "  ✗ uv not found on PATH" >&2
    echo "    install it: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    echo "    (or: brew install uv  /  pipx install uv)" >&2
    exit 1
fi
echo "  ✓ uv $(uv --version 2>/dev/null | awk '{print $2}')"

# Every PEP-723 `uv run --script` file under skills/ (workflow/scripts/
# plus any skill-scoped scripts/).
_uv_scripts() {
    # Search BOTH legacy skills/workflow/scripts/ AND the migrated
    # scripts/ top-level (post-DOMAIN-1 layout). The two locations
    # coexist during the per-domain migration.
    {
        grep -rl '^# /// script' "$PLUGIN_ROOT/skills" --include='*.py' 2>/dev/null
        grep -rl '^# /// script' "$PLUGIN_ROOT/scripts" --include='*.py' 2>/dev/null
    } | sort -u
}

if [ "$MODE" = "--check" ]; then
    exit 0
fi

if [ "$MODE" = "--list" ]; then
    _uv_scripts
    exit 0
fi

if [ "${KAIZEN_BOOTSTRAP_DISABLE:-}" = "1" ]; then
    echo "  ∘ pre-warm skipped (KAIZEN_BOOTSTRAP_DISABLE=1)"
    exit 0
fi

# Portable timeout guard — GNU coreutils `timeout`, else `gtimeout`
# (macOS + brew), else run unguarded. A script that does not handle
# --help still gets its venv built before it is killed.
_TIMEOUT=""
if command -v timeout >/dev/null 2>&1; then
    _TIMEOUT="timeout 300"
elif command -v gtimeout >/dev/null 2>&1; then
    _TIMEOUT="gtimeout 300"
fi

# 2. Pre-warm: `uv run --script <f> --help` builds + caches the venv as
#    a side effect. Best-effort — uv resolves + installs deps before it
#    execs the script, so the venv is warm even when --help is non-zero.
echo "  pre-warming uv-script venvs (first run downloads deps)..."
total=0
while IFS= read -r f; do
    [ -n "$f" ] || continue
    total=$((total + 1))
    rel="${f#"$PLUGIN_ROOT"/}"
    if $_TIMEOUT uv run --script "$f" --help >/dev/null 2>&1; then
        echo "  ✓ $rel"
    else
        echo "  ∘ $rel (venv built; --help non-zero — non-fatal)"
    fi
done < <(_uv_scripts)

echo "  bootstrap: pre-warmed $total uv-script venv(s)"
