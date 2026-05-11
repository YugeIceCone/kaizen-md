#!/usr/bin/env bash
# kaizen backup — snapshot workflow state for restore-on-mistake.
#
# Backs up everything the gate manages + (optionally) brain + project memory:
#   .kaizen.toml
#   .workflow/                  (backlog.json, backlog.md, state.json,
#                                snapshot.md, progress.md, decisions.md,
#                                audit logs, migration-loop-state.md, ...)
#   ~/.claude/brain/            (optional, with --include-brain)
#   ~/.claude/projects/<slug>/memory/  (optional, with --include-memory)
#
# Backups land at: ~/.claude/backups/kaizen/<repo-slug>/<UTC>[-label].tar.gz
# Repo-slugged so multi-project backups don't collide.
#
# Subcommands:
#   create [--label LABEL] [--include-brain] [--include-memory]
#   list [--all-repos]
#   show <id>
#   restore <id> [--target <dir>]      (default: restore over current repo)
#   prune [--keep N]                    (default: keep last 10)

set -u

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "backup: not a git repo" >&2; exit 2
}
REPO_SLUG=$(echo "$REPO_ROOT" | sed 's|^/||; s|/|-|g')
BACKUP_BASE="$HOME/.claude/backups/kaizen/$REPO_SLUG"
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
    OUT="$BACKUP_BASE/$NAME.tar.gz"

    # Always-included: .kaizen.toml + .workflow/
    INCLUDES=()
    [ -f "$REPO_ROOT/.kaizen.toml" ] && INCLUDES+=(".kaizen.toml")
    [ -d "$REPO_ROOT/.workflow"          ] && INCLUDES+=(".workflow")
    [ -d "$REPO_ROOT/.kaizen"      ] && INCLUDES+=(".kaizen")
    if [ ${#INCLUDES[@]} -eq 0 ]; then
        echo "backup create: nothing to back up (no .workflow/ or .kaizen.toml)" >&2
        exit 1
    fi

    # Optional brain / project memory (separate tar in same archive)
    EXTRA=()
    if [ "$INCLUDE_BRAIN" = "1" ] && [ -d "$HOME/.claude/brain" ]; then
        EXTRA+=("$HOME/.claude/brain")
    fi
    if [ "$INCLUDE_MEMORY" = "1" ]; then
        MEM_DIR="$HOME/.claude/projects/$(echo "$REPO_ROOT" | sed 's|/|-|g')/memory"
        [ -d "$MEM_DIR" ] && EXTRA+=("$MEM_DIR")
    fi

    if [ ${#EXTRA[@]} -gt 0 ]; then
        # Use absolute paths for brain/memory (different root); the includes
        # are repo-relative. tar's --absolute-names flag is portable.
        tar czf "$OUT" -C "$REPO_ROOT" "${INCLUDES[@]}" \
            -C / "${EXTRA[@]/#\//}"  # strip leading slash so it stores relative
    else
        tar czf "$OUT" -C "$REPO_ROOT" "${INCLUDES[@]}"
    fi

    SIZE=$(du -h "$OUT" | awk '{print $1}')
    echo "  ✓ backup: $OUT ($SIZE)"
    echo "  ✓ includes: ${INCLUDES[*]}${EXTRA:+ + brain/memory}"
fi

# ─── list ─────────────────────────────────────────────────────────────

if [ "$cmd" = "list" ]; then
    ALL=0
    [ "${1:-}" = "--all-repos" ] && ALL=1
    if [ "$ALL" = "1" ]; then
        echo "All kaizen backups:"
        find "$HOME/.claude/backups/kaizen" -name "*.tar.gz" 2>/dev/null \
            | sort -r | while read f; do
                size=$(du -h "$f" | awk '{print $1}')
                echo "  $f  ($size)"
            done
    else
        echo "Backups for $REPO_SLUG:"
        ls -1t "$BACKUP_BASE"/*.tar.gz 2>/dev/null | while read f; do
            size=$(du -h "$f" | awk '{print $1}')
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
