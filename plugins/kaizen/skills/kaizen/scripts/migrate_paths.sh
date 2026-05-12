#!/usr/bin/env bash
# kaizen migrate-paths — move v1.21-and-earlier scattered state into the
# v1.22.0+ unified ~/.claude/.kaizen/{trace,knowledge,daemon,inbox,backups,schemas}/
# layout, and per-project <repo>/.workflow/ → <repo>/.kaizen/workflow/.
#
# Idempotent: legacy paths that have already moved (or never existed) are
# no-ops. Refuses to overwrite NEW paths that already have content unless
# --force is passed.
#
# Usage:
#   migrate_paths.sh [--dry-run] [--force] [--user-only] [--project-only]
#                    [--project-root <path>]
#
# Defaults: migrate both user-global and project paths. Honor the project
# root from CLAUDE_PROJECT_DIR / git toplevel / cwd.

set -uo pipefail

_SCRIPT_REAL_DIR="$(cd "$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"
source "$_SCRIPT_REAL_DIR/_paths.sh"

DRY_RUN=0
FORCE=0
USER_ONLY=0
PROJECT_ONLY=0
PROJECT_ROOT=""

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)        DRY_RUN=1 ;;
    --force)          FORCE=1 ;;
    --user-only)      USER_ONLY=1 ;;
    --project-only)   PROJECT_ONLY=1 ;;
    --project-root)   PROJECT_ROOT="$2"; shift ;;
    -h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done

if [ -t 1 ]; then
  BOLD=$'\e[1m'; DIM=$'\e[2m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'
  RED=$'\e[31m'; BLUE=$'\e[34m'; RESET=$'\e[0m'
else
  BOLD=""; DIM=""; GREEN=""; YELLOW=""; RED=""; BLUE=""; RESET=""
fi

OK_COUNT=0
SKIP_COUNT=0
FAIL_COUNT=0

# move_if_present <legacy> <new>
move_if_present() {
  local from="$1" to="$2"
  if [ ! -e "$from" ]; then
    printf '  %s%s %s%s\n' "$DIM" "∘" " no legacy $from" "$RESET"
    SKIP_COUNT=$((SKIP_COUNT+1))
    return 0
  fi
  if [ -e "$to" ] && [ "$FORCE" -eq 0 ]; then
    printf '  %s %s\n    %sNEW already exists, leaving legacy in place. Use --force to override.%s\n' \
      "$YELLOW!$RESET" "$from → $to" "$DIM" "$RESET"
    SKIP_COUNT=$((SKIP_COUNT+1))
    return 0
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '  %s%s %s → %s%s\n' "$YELLOW" "≫" "$from" "$to" "$RESET"
    return 0
  fi
  mkdir -p "$(dirname "$to")"
  if [ -e "$to" ] && [ "$FORCE" -eq 1 ]; then
    rm -rf "$to"
  fi
  if mv "$from" "$to" 2>/dev/null; then
    printf '  %s %s → %s\n' "${GREEN}✓${RESET}" "$from" "$to"
    OK_COUNT=$((OK_COUNT+1))
  else
    printf '  %s %s → %s ${DIM}(mv failed; trying cp -r)${RESET}\n' "${RED}✗${RESET}" "$from" "$to"
    if cp -r "$from" "$to" 2>/dev/null; then
      rm -rf "$from"
      printf '    %s recovered via cp + rm\n' "${GREEN}✓${RESET}"
      OK_COUNT=$((OK_COUNT+1))
    else
      FAIL_COUNT=$((FAIL_COUNT+1))
    fi
  fi
}

# ─── Banner ──────────────────────────────────────────────────────────

mode="${BOLD}execute${RESET}"
[ "$DRY_RUN" -eq 1 ] && mode="${BOLD}${YELLOW}dry-run${RESET}"
echo ""
echo "${BOLD}kaizen migrate-paths${RESET} — $mode"

# ─── User-global migrations ──────────────────────────────────────────

if [ "$PROJECT_ONLY" -eq 0 ]; then
  echo ""
  echo "${BOLD}user-global${RESET} (~/.claude/)"
  move_if_present "$KAIZEN_LEGACY_TRACE"     "$KAIZEN_TRACE_DIR"
  move_if_present "$KAIZEN_LEGACY_KNOWLEDGE" "$KAIZEN_KNOWLEDGE_DIR"
  move_if_present "$KAIZEN_LEGACY_DAEMON"    "$KAIZEN_DAEMON_DIR"
  move_if_present "$KAIZEN_LEGACY_INBOX"     "$KAIZEN_INBOX_DIR"
  move_if_present "$KAIZEN_LEGACY_BACKUPS"   "$KAIZEN_BACKUP_DIR"
  move_if_present "$KAIZEN_LEGACY_SCHEMAS"   "$KAIZEN_USER_SCHEMAS"
fi

# ─── Project migration ───────────────────────────────────────────────

if [ "$USER_ONLY" -eq 0 ]; then
  echo ""
  echo "${BOLD}project${RESET}"

  if [ -z "$PROJECT_ROOT" ]; then
    PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-}"
    if [ -z "$PROJECT_ROOT" ]; then
      PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")"
    fi
  fi
  echo "  ${DIM}root: $PROJECT_ROOT${RESET}"

  legacy="$PROJECT_ROOT/$KAIZEN_LEGACY_PROJECT_WORKFLOW"
  new="$(kaizen_project_workflow_dir "$PROJECT_ROOT")"
  move_if_present "$legacy" "$new"

  # Rewrite .kaizen.toml paths if they still reference .workflow/.
  TOML="$PROJECT_ROOT/.kaizen.toml"
  if [ -f "$TOML" ] && grep -qE '\.workflow/' "$TOML"; then
    if [ "$DRY_RUN" -eq 1 ]; then
      printf '  %s%s %s%s\n' "$YELLOW" "≫" " rewrite .kaizen.toml paths .workflow/ → .kaizen/workflow/" "$RESET"
    else
      sed -i.bak 's|\.workflow/|.kaizen/workflow/|g' "$TOML" && rm -f "${TOML}.bak"
      printf '  %s rewrote .kaizen.toml paths\n' "${GREEN}✓${RESET}"
      OK_COUNT=$((OK_COUNT+1))
    fi
  fi
fi

# ─── Summary ─────────────────────────────────────────────────────────

echo ""
echo "${BOLD}summary${RESET}"
if [ "$DRY_RUN" -eq 1 ]; then
  echo "  (dry-run — nothing executed; re-run without --dry-run to apply)"
else
  echo "  ${GREEN}✓${RESET} $OK_COUNT moved, ${DIM}∘${RESET} $SKIP_COUNT skipped, ${RED}✗${RESET} $FAIL_COUNT failed"
fi

[ "$FAIL_COUNT" -gt 0 ] && exit 1
exit 0
