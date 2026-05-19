#!/usr/bin/env bash
# kaizen refresh-cache — copy local-marketplace source → Claude Code's
# plugin cache for the current version.
#
# Solves: /plugin update doesn't auto-pull from local marketplaces on
# version bump, so /reload-plugins serves stale content. This script
# does the copy explicitly, version-named.
#
# Usage:
#   refresh-cache.sh                # detect everything
#   refresh-cache.sh --dry-run      # show what would happen, no write
#   refresh-cache.sh --force        # overwrite cache slot for current version
#
# Env:
#   KAIZEN_PLUGIN_SRC               source dir override (default: local-marketplaces/kaizen-md/plugins/kaizen)
#   KAIZEN_CACHE_BASE               cache base dir override (default: ~/.claude/plugins/cache/kaizen-md/kaizen)

set -uo pipefail

DRY=0
FORCE=0
for a in "$@"; do
    case "$a" in
        --dry-run) DRY=1 ;;
        --force)   FORCE=1 ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    esac
done

DEFAULT_SRC="$HOME/.claude/local-marketplaces/kaizen-md/plugins/kaizen"
SRC="${KAIZEN_PLUGIN_SRC:-$DEFAULT_SRC}"
CACHE_BASE="${KAIZEN_CACHE_BASE:-$HOME/.claude/plugins/cache/kaizen-md/kaizen}"

if [ ! -d "$SRC" ]; then
    echo "kaizen refresh-cache: source dir not found: $SRC" >&2
    exit 1
fi

VER=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['version'])" "$SRC/.claude-plugin/plugin.json" 2>/dev/null)
if [ -z "${VER:-}" ]; then
    echo "kaizen refresh-cache: could not parse version from $SRC/.claude-plugin/plugin.json" >&2
    exit 1
fi

DEST="$CACHE_BASE/$VER"

echo "kaizen refresh-cache"
echo "  source:  $SRC"
echo "  version: $VER"
echo "  cache:   $DEST"

if [ -d "$DEST" ] && [ "$FORCE" = "0" ]; then
    # Check if already in sync
    if command -v rsync >/dev/null 2>&1; then
        # grep -vc counts non-matching lines in one pass (no wc fork).
        CHANGES=$(rsync -a --dry-run --delete --itemize-changes "$SRC/" "$DEST/" 2>/dev/null | grep -vc '^cd' || echo 0)
        if [ "$CHANGES" = "0" ]; then
            echo "  ✓ cache already in sync ($VER)"
            exit 0
        fi
        echo "  ∘ cache exists but drifted ($CHANGES file changes pending)"
    else
        echo "  ∘ cache exists; --force to overwrite"
    fi
fi

if [ "$DRY" = "1" ]; then
    echo "  [dry-run] would copy $SRC/ → $DEST/"
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --dry-run --delete --itemize-changes "$SRC/" "$DEST/" | head -20
    fi
    exit 0
fi

mkdir -p "$CACHE_BASE"

if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete "$SRC/" "$DEST/"
else
    rm -rf "$DEST"
    mkdir -p "$DEST"
    cp -a "$SRC/." "$DEST/"
fi

echo "  ✓ refreshed cache to v$VER"
echo ""
echo "Run /reload-plugins to activate."
