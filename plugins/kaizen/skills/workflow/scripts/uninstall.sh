#!/usr/bin/env bash
# kaizen uninstall — reverse of setup.sh install. Invoked as
# `/kaizen:setup uninstall` (setup.sh dispatches the `uninstall` subcommand here).
# Removes per-repo activation only — leaves the plugin itself + the data
# (.workflow/backlog.{json,md}) in place. Plugin uninstall is via /plugin.

set -uo pipefail

_LIB_DIR="$(cd "$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"
. "$_LIB_DIR/lib.sh"
color_init

REPO=$(repo_root)
[ -z "$REPO" ] && { echo "uninstall: not in a git repo" >&2; exit 1; }
cd "$REPO"

# Flag parsing
KEEP_BACKLOG=1
KEEP_CONFIG=1   # default: keep config so re-install picks up your settings
DRY_RUN=1
for arg in "$@"; do
    case "$arg" in
        --execute)        DRY_RUN=0 ;;
        --remove-backlog) KEEP_BACKLOG=0 ;;
        --remove-config)  KEEP_CONFIG=0 ;;
        -h|--help)
            cat <<EOF
Usage: uninstall.sh [--execute] [--remove-backlog] [--remove-config]

Default is dry-run.

  --execute            Actually perform the uninstall.
  --remove-backlog     Also delete .kaizen/workflow/backlog.{json,md}. Default: keep
                       (it's project data; usually you want to preserve it).
  --remove-config      Also delete .kaizen.toml. Default: keep
                       (so re-install picks up your settings).

This NEVER touches:
  - .kaizen/workflow/progress.md, decisions.md, state.json, snapshot.md (project / workflow-routing state)
  - ~/.claude/.kaizen/backups/ (always preserved — restore source)
  - The plugin itself (use /plugin uninstall kaizen@kaizen-md)
EOF
            exit 0
            ;;
    esac
done

echo "${BOLD}kaizen uninstall (repo: $REPO)${RESET}"
echo ""

if [ "$DRY_RUN" = "1" ]; then
    echo "${YELLOW}DRY-RUN${RESET} — re-run with ${BOLD}--execute${RESET} to actually uninstall."
    echo ""
fi

ACTIONS=()

# 1. core.hooksPath
HP=$(git config core.hooksPath 2>/dev/null || true)
if [ "$HP" = ".kaizen/hooks" ]; then
    ACTIONS+=("git config --unset core.hooksPath")
fi

# 2. .kaizen/ directory (hooks symlink dir — generated)
if [ -d ".kaizen" ]; then
    ACTIONS+=("rm -rf .kaizen/")
fi

# 3. .kaizen.toml (config)
if [ "$KEEP_CONFIG" = "0" ] && [ -f ".kaizen.toml" ]; then
    ACTIONS+=("rm .kaizen.toml  ${DIM}(--remove-config)${RESET}")
fi

# 4. backlog.{json,md}
BACKLOG_MD=$(toml_get backlog_path "")
if [ -n "$BACKLOG_MD" ] && [ "$KEEP_BACKLOG" = "0" ]; then
    BACKLOG_JSON="${BACKLOG_MD%.md}.json"
    [ -f "$BACKLOG_JSON" ] && ACTIONS+=("rm $BACKLOG_JSON  ${DIM}(--remove-backlog)${RESET}")
    [ -f "$BACKLOG_MD" ]   && ACTIONS+=("rm $BACKLOG_MD  ${DIM}(--remove-backlog)${RESET}")
fi

# 5. .gitignore line
if grep -qxF ".kaizen/" .gitignore 2>/dev/null; then
    ACTIONS+=("sed -i '/^\\.kaizen\\/$/d' .gitignore  ${DIM}(or remove manually)${RESET}")
fi

if [ ${#ACTIONS[@]} -eq 0 ]; then
    echo "${DIM}Nothing to uninstall — repo not activated.${RESET}"
    exit 0
fi

echo "Plan:"
for a in "${ACTIONS[@]}"; do
    printf "  → %b\n" "$a"
done
echo ""
echo "${DIM}Preserved:${RESET}"
[ "$KEEP_BACKLOG" = "1" ] && [ -f "${BACKLOG_MD:-/dev/null}" ] && echo "  ${GREEN}✓${RESET} backlog.{json,md} (project data — pass --remove-backlog to delete)"
[ "$KEEP_CONFIG" = "0" ]  && [ -f ".kaizen.toml" ] && echo "  ${GREEN}✓${RESET} .kaizen.toml (re-install will reuse)"
echo "  ${GREEN}✓${RESET} ~/.claude/.kaizen/backups/$(echo "$REPO" | sed 's|^/||; s|/|-|g')/  (untouched)"
echo "  ${GREEN}✓${RESET} .kaizen/workflow/{progress.md,state.json,...} (workflow-routing + project state)"
echo ""

if [ "$DRY_RUN" = "1" ]; then
    exit 0
fi

# Auto-backup before mutation (safety net)
BACKUP_SH=$(find_sibling backup.sh "$_LIB_DIR") || true
if [ -x "$BACKUP_SH" ]; then
    bash "$BACKUP_SH" create --label "pre-uninstall" >&2 || true
fi

# Execute
[ "$HP" = ".kaizen/hooks" ] && git config --unset core.hooksPath
[ -d ".kaizen" ]            && rm -rf ".kaizen/"
[ "$KEEP_CONFIG" = "0" ] && [ -f ".kaizen.toml" ] && rm ".kaizen.toml"
if [ -n "${BACKLOG_MD:-}" ] && [ "$KEEP_BACKLOG" = "0" ]; then
    [ -f "${BACKLOG_MD%.md}.json" ] && rm "${BACKLOG_MD%.md}.json"
    [ -f "$BACKLOG_MD" ] && rm "$BACKLOG_MD"
fi
grep -qxF ".kaizen/" .gitignore 2>/dev/null && sed -i '/^\.kaizen\/$/d' .gitignore

echo "${GREEN}${BOLD}✓ uninstalled${RESET}"
echo "${DIM}Re-activate later: /kaizen:setup${RESET}"
echo "${DIM}Restore from backup: /kaizen:backup list  →  /kaizen:backup restore <id>${RESET}"
