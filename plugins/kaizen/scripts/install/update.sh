#!/usr/bin/env bash
# kaizen update — single-command maintenance flow.
#
# What it does:
#   1. cd to the local-marketplace clone
#   2. git fetch origin (network)
#   3. compare local HEAD with origin/master
#   4. if behind: git pull (fast-forward only — refuses non-ff)
#   5. run refresh-cache.sh to sync the version-named cache slot
#   6. (optional) prune old cache versions
#
# Subcommands:
#   (none) | pull   pull + refresh-cache
#   check           report status only (current vs remote), no network mutation
#   prune           remove old cache version slots (keep current + 1 previous)
#   path            print the marketplace dir
#
# Env:
#   KAIZEN_MARKETPLACE  override path (default ~/.claude/local-marketplaces/kaizen-md)
#   KAIZEN_KEEP_VERSIONS  prune retention (default: keep current + 1)

set -uo pipefail

CMD="${1:-pull}"

DEFAULT_MARKET="$HOME/.claude/local-marketplaces/kaizen-md"
MARKET="${KAIZEN_MARKETPLACE:-$DEFAULT_MARKET}"
PLUGIN_SRC="$MARKET/plugins/kaizen"
SCRIPT_DIR="$PLUGIN_SRC/scripts/install"  # DOMAIN-shells Wave C: refresh-cache.sh now in install/
CACHE_BASE="$HOME/.claude/plugins/cache/kaizen-md/kaizen"
KEEP="${KAIZEN_KEEP_VERSIONS:-2}"

case "$CMD" in
    path)
        echo "$MARKET"
        exit 0
        ;;
    -h|--help)
        sed -n '2,22p' "$0"
        exit 0
        ;;
esac

if [ ! -d "$MARKET/.git" ]; then
    echo "kaizen update: not a git repo: $MARKET" >&2
    echo "  hint: clone first via git clone <repo> $MARKET" >&2
    exit 1
fi

# Resolve version + commit info
SRC_VER=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['version'])" "$PLUGIN_SRC/.claude-plugin/plugin.json" 2>/dev/null || echo "?")
LOCAL_SHA=$(cd "$MARKET" && git rev-parse --short HEAD 2>/dev/null || echo "?")

# Probe remote head
echo "kaizen update — local: v$SRC_VER @ $LOCAL_SHA"

REMOTE_LINE=$(cd "$MARKET" && git ls-remote origin master 2>/dev/null | head -1)
if [ -z "$REMOTE_LINE" ]; then
    echo "  ! could not reach origin (offline?). Local-only operations still work." >&2
    REMOTE_SHA=""
else
    REMOTE_SHA=$(echo "$REMOTE_LINE" | awk '{print substr($1,1,7)}')
fi

if [ -n "$REMOTE_SHA" ]; then
    if [ "$LOCAL_SHA" = "$REMOTE_SHA" ]; then
        echo "  ✓ up to date with origin ($REMOTE_SHA)"
        UP_TO_DATE=1
    else
        BEHIND=$(cd "$MARKET" && git rev-list --count HEAD..origin/master 2>/dev/null || echo "?")
        echo "  ! origin master at $REMOTE_SHA (you're $BEHIND commits behind)"
        UP_TO_DATE=0
    fi
else
    UP_TO_DATE=0
fi

case "$CMD" in
    check)
        # Read-only report — exit with status reflecting up-to-date-ness
        exit $((1 - ${UP_TO_DATE:-0}))
        ;;

    prune)
        if [ ! -d "$CACHE_BASE" ]; then
            echo "  ∘ no cache dir to prune ($CACHE_BASE)"
            exit 0
        fi
        # Versions sorted, keep last N (lexical sort works for X.Y.Z up to single-digit components; semver-ish)
        VERSIONS=$(ls -1 "$CACHE_BASE" 2>/dev/null | sort -V)
        TOTAL=$(echo "$VERSIONS" | wc -l)
        if [ "$TOTAL" -le "$KEEP" ]; then
            echo "  ∘ $TOTAL cached versions, keeping $KEEP — nothing to prune"
            exit 0
        fi
        TO_REMOVE=$(echo "$VERSIONS" | head -n -"$KEEP")
        echo "  pruning $(echo "$TO_REMOVE" | wc -l) old cache versions (keeping $KEEP newest):"
        echo "$TO_REMOVE" | while read v; do
            [ -z "$v" ] && continue
            echo "    - $CACHE_BASE/$v"
            rm -rf "$CACHE_BASE/$v"
        done
        echo "  ✓ pruned"
        exit 0
        ;;

    pull|"")
        CHANGES_APPLIED=0

        if [ "${UP_TO_DATE:-0}" = "1" ]; then
            echo "  ∘ no pull needed"
        else
            echo "  pulling..."
            if ! (cd "$MARKET" && git pull --ff-only origin master 2>&1 | sed 's/^/    /'); then
                echo "  ✗ git pull failed (non-fast-forward? resolve manually in $MARKET)" >&2
                exit 1
            fi
            SRC_VER=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['version'])" "$PLUGIN_SRC/.claude-plugin/plugin.json" 2>/dev/null || echo "?")
            LOCAL_SHA=$(cd "$MARKET" && git rev-parse --short HEAD 2>/dev/null || echo "?")
            echo "  ✓ now at v$SRC_VER @ $LOCAL_SHA"
            CHANGES_APPLIED=1
        fi

        # refresh-cache always runs (catches local hand-edits even without pull).
        # Capture its output so we can detect whether the cache actually moved.
        echo ""
        REFRESH_OUT=$(bash "$SCRIPT_DIR/refresh-cache.sh" 2>&1)
        echo "$REFRESH_OUT"
        if echo "$REFRESH_OUT" | grep -q "✓ refreshed cache to"; then
            CHANGES_APPLIED=1
        fi

        echo ""
        if [ "$CHANGES_APPLIED" = "1" ]; then
            # Machine-parseable last line. The kaizen-update slash command
            # body reads this to decide whether to auto-emit /reload-plugins.
            echo "kaizen-update: needs-reload (changes applied)"
        else
            echo "kaizen-update: no-op (already current)"
        fi
        ;;

    *)
        echo "kaizen update: unknown subcommand '$CMD'" >&2
        echo "try: pull | check | prune | path" >&2
        exit 1
        ;;
esac
