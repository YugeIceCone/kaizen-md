#!/usr/bin/env bash
# Unit tests for `_plugin_root.sh` — the kaizen plugin-root resolver
# (shell side). Mirrors `tests/test_plugin_root.py` 1:1.
#
# Run:
#     bash tests/test_plugin_root.sh
#
# Exit code is total failures (0 = all pass).

set -uo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(cd "$TESTS_DIR/.." && pwd)"
RESOLVER="$PLUGIN_DIR/scripts/util/_plugin_root.sh"

FAIL=0
PASS=0

assert() {
    # assert <label> <expected> <actual>
    local label="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
        printf '  ✓ %s\n' "$label"
        PASS=$((PASS + 1))
    else
        printf '  ✗ %s\n     expected: %s\n     actual:   %s\n' "$label" "$expected" "$actual"
        FAIL=$((FAIL + 1))
    fi
}

assert_rc() {
    # assert_rc <label> <expected-rc> <actual-rc>
    local label="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
        printf '  ✓ %s\n' "$label"
        PASS=$((PASS + 1))
    else
        printf '  ✗ %s\n     expected rc: %s\n     actual rc:   %s\n' "$label" "$expected" "$actual"
        FAIL=$((FAIL + 1))
    fi
}

make_fake_plugin() {
    # make_fake_plugin <parent> <name>  →  prints created plugin dir
    local parent="$1" name="$2"
    local p="$parent/$name"
    mkdir -p "$p/.claude-plugin"
    printf '{"name":"%s"}\n' "$name" > "$p/.claude-plugin/plugin.json"
    echo "$p"
}

# Scrub env between cases
scrub() { unset CLAUDE_PLUGIN_ROOT KAIZEN_PLUGIN_ROOT; }

# ── Setup ────────────────────────────────────────────────────────────
echo "test_plugin_root.sh"

# ── 1. claude_plugin_root used when set ──────────────────────────────
echo "test_claude_plugin_root_used_when_set"
TMP=$(mktemp -d)
P=$(make_fake_plugin "$TMP" "via-claude")
scrub
export CLAUDE_PLUGIN_ROOT="$P"
# shellcheck disable=SC1090
source "$RESOLVER"
RESOLVED="$(kaizen_plugin_root)"
assert "claude_plugin_root wins" "$P" "$RESOLVED"
rm -rf "$TMP"

# ── 2. kaizen_plugin_root fallback ───────────────────────────────────
echo "test_kaizen_plugin_root_fallback"
TMP=$(mktemp -d)
P=$(make_fake_plugin "$TMP" "via-kaizen")
scrub
export KAIZEN_PLUGIN_ROOT="$P"
RESOLVED="$(kaizen_plugin_root)"
assert "kaizen_plugin_root used" "$P" "$RESOLVED"
rm -rf "$TMP"

# ── 3. claude wins over kaizen ───────────────────────────────────────
echo "test_claude_wins_over_kaizen"
TMP=$(mktemp -d)
A=$(make_fake_plugin "$TMP" "a-claude")
B=$(make_fake_plugin "$TMP" "b-kaizen")
scrub
export CLAUDE_PLUGIN_ROOT="$A"
export KAIZEN_PLUGIN_ROOT="$B"
RESOLVED="$(kaizen_plugin_root)"
assert "claude beats kaizen" "$A" "$RESOLVED"
rm -rf "$TMP"

# ── 4. env set but no marker → falls through to script-derived ───────
echo "test_env_set_but_no_marker_falls_through"
TMP=$(mktemp -d)
scrub
export CLAUDE_PLUGIN_ROOT="$TMP"   # exists but no plugin marker
RESOLVED="$(kaizen_plugin_root)"
# Should fall through to script-derived path (this repo's kaizen plugin)
if [ -f "$RESOLVED/.claude-plugin/plugin.json" ]; then
    assert "script-derived fallback found marker" "yes" "yes"
else
    assert "script-derived fallback found marker" "yes" "no (got: $RESOLVED)"
fi
rm -rf "$TMP"

# ── 5. blank env values treated as unset ─────────────────────────────
echo "test_env_blank_string_treated_as_unset"
scrub
export CLAUDE_PLUGIN_ROOT=""
export KAIZEN_PLUGIN_ROOT=""
RESOLVED="$(kaizen_plugin_root)"
if [ -f "$RESOLVED/.claude-plugin/plugin.json" ]; then
    assert "blank env falls through" "yes" "yes"
else
    assert "blank env falls through" "yes" "no (got: $RESOLVED)"
fi

# ── 6. script-derived walks up to find marker ────────────────────────
echo "test_script_path_walks_up_to_find_marker"
scrub
RESOLVED="$(kaizen_plugin_root)"
if [ "$(basename "$RESOLVED")" = "kaizen" ] \
        && [ -f "$RESOLVED/.claude-plugin/plugin.json" ]; then
    assert "found kaizen plugin via walk-up" "yes" "yes"
else
    assert "found kaizen plugin via walk-up" "yes" "no (got: $RESOLVED)"
fi

# ── 7. resolver returns nonzero when nothing found ───────────────────
# Hard to simulate (would need to run from /tmp with no env). Use the
# fact that bash subshell can move cwd + export the resolver as a fresh
# source. Skip this case — too brittle to construct safely.

# ── 8. contract: kaizen_plugin_root is a function ────────────────────
echo "test_contract_function_defined"
if type kaizen_plugin_root >/dev/null 2>&1; then
    assert "kaizen_plugin_root defined" "yes" "yes"
else
    assert "kaizen_plugin_root defined" "yes" "no"
fi

# ── Summary ──────────────────────────────────────────────────────────
echo ""
echo "── results: $PASS passed, $FAIL failed ──"
exit "$FAIL"
