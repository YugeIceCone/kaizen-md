#!/usr/bin/env bash
# kaizen backup — snapshot workflow state for restore-on-mistake.
#
# Backs up everything the gate manages + (optionally) brain + project memory:
#   .kaizen.toml
#   .workflow/                  (backlog.json, backlog.md, state.json,
#                                snapshot.md, progress.md, decisions.md,
#                                audit logs, migration-loop-state.md, ...)
#   $KAIZEN_BRAIN_DIR/          (optional, with --include-brain — default ~/.claude/.kaizen/brain)
#   ~/.claude/projects/<slug>/memory/  (optional, with --include-memory)
#
# Backups land at: ~/.claude/.kaizen/backups/<repo-slug>/<UTC>[-label].tar.gz
# Repo-slugged so multi-project backups don't collide. (v1.30.0+ unified
# layout; legacy ~/.claude/backups/kaizen/ migrated by migrate_paths.sh.)
#
# Subcommands:
#   create [--label LABEL] [--include-brain] [--include-memory]
#   list [--all-repos]
#   show <id>
#   restore <id> [--target <dir>]      (default: restore over current repo)
#   prune [--keep N]                    (default: keep last 10)

set -uo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "backup: not a git repo" >&2; exit 2
}
REPO_SLUG=$(echo "$REPO_ROOT" | sed 's|^/||; s|/|-|g')
# v1.30.0+ — backup base from _paths.sh (SSOT).
_SCRIPT_REAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SCRIPT_REAL_DIR/_paths.sh"
BACKUP_BASE="$KAIZEN_BACKUP_DIR/$REPO_SLUG"
mkdir -p "$BACKUP_BASE"

# ─── Subcommand dispatch ──────────────────────────────────────────────

cmd="${1:-list}"
shift || true

case "$cmd" in
    create) ;;
    list)   ;;
    show)   ;;
    restore) ;;
    prune)  ;;
    -h|--help)
        sed -n '2,/^set -u/p' "$0" | sed 's/^# \?//'
        exit 0 ;;
    *)
        echo "backup: unknown subcommand '$cmd'" >&2
        echo "       try: create | list | show <id> | restore <id> | prune" >&2
        exit 2 ;;
esac

# ─── create ───────────────────────────────────────────────────────────

if [ "$cmd" = "create" ]; then
    LABEL=""
    INCLUDE_BRAIN=0
    INCLUDE_MEMORY=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --label) LABEL="$2"; shift 2 ;;
            --include-brain) INCLUDE_BRAIN=1; shift ;;
            --include-memory) INCLUDE_MEMORY=1; shift ;;
            *) echo "create: unknown flag '$1'" >&2; exit 2 ;;
        esac
    done

    TS=$(date -u +%Y%m%dT%H%M%SZ)
    NAME="$TS"
    [ -n "$LABEL" ] && NAME="${TS}-${LABEL//[^A-Za-z0-9_-]/_}"
    REF="$BACKUP_BASE/$NAME.tar.gz"

    # Always-included: .kaizen.toml + .workflow/
    INCLUDES=()
    [ -f "$REPO_ROOT/.kaizen.toml" ] && INCLUDES+=(".kaizen.toml")
    [ -d "$REPO_ROOT/.workflow"          ] && INCLUDES+=(".workflow")
    [ -d "$REPO_ROOT/.kaizen"      ] && INCLUDES+=(".kaizen")
    if [ ${#INCLUDES[@]} -eq 0 ]; then
        echo "backup create: nothing to back up (no .kaizen/, .workflow/, or .kaizen.toml)" >&2
        exit 1
    fi

    # Optional brain / project memory (separate tar in same archive)
    EXTRA=()
    if [ "$INCLUDE_BRAIN" = "1" ]; then
        BRAIN_TO_BACKUP="${KAIZEN_BRAIN_DIR:-$HOME/.claude/.kaizen/brain}"
        [ -d "$BRAIN_TO_BACKUP" ] && EXTRA+=("$BRAIN_TO_BACKUP")
    fi
    if [ "$INCLUDE_MEMORY" = "1" ]; then
        MEM_DIR="$HOME/.claude/projects/$(echo "$REPO_ROOT" | sed 's|/|-|g')/memory"
        [ -d "$MEM_DIR" ] && EXTRA+=("$MEM_DIR")
    fi

    # v1.30.0+: tar to a temp file, then route through the blob store. The
    # final user-visible path is a symlink into ~/.claude/.kaizen/blobs/<sha>.
    # Same UX as before (tar/ls/restore resolve symlinks transparently) but
    # every tarball is content-addressed and dedup'd.
    TMP_TAR=$(mktemp --suffix=.tar.gz)
    # M2: ensure temp file is reaped on any exit path (success, error, signal).
    # Happy path: `_blobs.py put` moves the file → rm has no effect.
    trap 'rm -f "$TMP_TAR"' EXIT INT TERM
    if [ ${#EXTRA[@]} -gt 0 ]; then
        tar czf "$TMP_TAR" -C "$REPO_ROOT" "${INCLUDES[@]}" \
            -C / "${EXTRA[@]/#\//}"
    else
        tar czf "$TMP_TAR" -C "$REPO_ROOT" "${INCLUDES[@]}"
    fi

    # Ingest into blob store; --ref materialises the symlink at $REF.
    mkdir -p "$BACKUP_BASE"
    SHA=$(python3 "$_SCRIPT_REAL_DIR/_blobs.py" put "$TMP_TAR" \
        --kind backup \
        --name "$NAME.tar.gz" \
        --ref "$REF" \
        --context "repo=$REPO_SLUG includes=${INCLUDES[*]}")

    # L2: build the EXTRA suffix from array length (not the bash ${arr:+...}
    # gotcha which only inspects element 0).
    EXTRA_LABEL=""
    if [ ${#EXTRA[@]} -gt 0 ]; then
        EXTRA_LABEL=" + ${#EXTRA[@]} extra ($(printf '%s,' "${EXTRA[@]##*/}" | sed 's/,$//'))"
    fi
    SIZE=$(du -h "$REF" -L | awk '{print $1}')
    echo "  ✓ backup: $REF ($SIZE)"
    echo "  ✓ sha256: ${SHA:0:16}…  (full: $SHA)"
    echo "  ✓ includes: ${INCLUDES[*]}$EXTRA_LABEL"
fi

# ─── list ─────────────────────────────────────────────────────────────

if [ "$cmd" = "list" ]; then
    ALL=0
    [ "${1:-}" = "--all-repos" ] && ALL=1
    if [ "$ALL" = "1" ]; then
        echo "All kaizen backups:"
        find "$KAIZEN_BACKUP_DIR" -name "*.tar.gz" 2>/dev/null \
            | sort -r | while read f; do
                size=$(du -h -L "$f" | awk '{print $1}')
                echo "  $f  ($size)"
            done
    else
        echo "Backups for $REPO_SLUG:"
        ls -1t "$BACKUP_BASE"/*.tar.gz 2>/dev/null | while read f; do
            size=$(du -h -L "$f" | awk '{print $1}')
            id=$(basename "$f" .tar.gz)
            echo "  $id  ($size)"
        done
    fi
fi

# ─── show ─────────────────────────────────────────────────────────────

if [ "$cmd" = "show" ]; then
    [ $# -lt 1 ] && { echo "show: missing <id>" >&2; exit 2; }
    F="$BACKUP_BASE/$1.tar.gz"
    [ -f "$F" ] || { echo "show: backup not found: $F" >&2; exit 2; }
    echo "Contents of $F:"
    tar tzf "$F" | head -50
    total=$(tar tzf "$F" | wc -l)
    echo "  (... $total entries total)"
fi

# ─── restore ──────────────────────────────────────────────────────────

if [ "$cmd" = "restore" ]; then
    [ $# -lt 1 ] && { echo "restore: missing <id>" >&2; exit 2; }
    ID="$1"; shift
    TARGET="$REPO_ROOT"
    while [ $# -gt 0 ]; do
        case "$1" in
            --target) TARGET="$2"; shift 2 ;;
            *) echo "restore: unknown flag '$1'" >&2; exit 2 ;;
        esac
    done
    F="$BACKUP_BASE/$ID.tar.gz"
    [ -f "$F" ] || { echo "restore: backup not found: $F" >&2; exit 2; }

    # Safety: take an "auto-pre-restore" backup of the CURRENT state first.
    "$0" create --label "pre-restore-$ID" >&2 || true

    echo "Restoring $F → $TARGET ..."
    tar xzf "$F" -C "$TARGET"
    echo "  ✓ restored (current state was backed up as pre-restore-$ID)"
fi

# ─── prune ────────────────────────────────────────────────────────────

if [ "$cmd" = "prune" ]; then
    KEEP=10
    while [ $# -gt 0 ]; do
        case "$1" in
            --keep) KEEP="$2"; shift 2 ;;
            *) echo "prune: unknown flag '$1'" >&2; exit 2 ;;
        esac
    done
    # Newest first; tail -n +$((KEEP+1)) skips the first $KEEP
    REMOVED=0
    ls -1t "$BACKUP_BASE"/*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | while read f; do
        rm -f "$f"
        echo "  pruned: $(basename "$f")"
    done
    echo "  done (kept newest $KEEP)"
fi
