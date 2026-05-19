#!/usr/bin/env bash
# kaizen migrate — safe transitions between layouts.
#
# Auto-backs up before any destructive op (calls backup.sh under the hood).
# Default is --dry-run; --execute actually performs the operation.
#
# Subcommands:
#   scan                          List all migration candidates (dry-run by default)
#   retire-loose-skill <name>     Move ~/.claude/skills/<name> → backup (after auto-backup)
#   retire-marketplace <name>     Note steps to remove a separate marketplace (no auto-uninstall)
#   convert-backlog <md-path>     Parse a hand-written BACKLOG.md → backlog.json items
#   migrate-backlog-to-workflow   Move BACKLOG.md at repo root → .workflow/backlog.{json,md}
#
# Flags:
#   --dry-run    Default. Shows what would happen, doesn't do it.
#   --execute    Perform the operation (after auto-backup).

set -uo pipefail

# Resolve sibling backup.sh
_SCRIPT_REAL_DIR="$(cd "$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"
BACKUP_SH="$_SCRIPT_REAL_DIR/backup.sh"
BACKLOG_PY="$_SCRIPT_REAL_DIR/backlog.py"
# v1.30.0+ — unified path SSOT.
source "$_SCRIPT_REAL_DIR/_paths.sh"

# Colours
if [ -t 1 ]; then BOLD=$'\e[1m'; DIM=$'\e[2m'; YELLOW=$'\e[33m'; GREEN=$'\e[32m'; RESET=$'\e[0m'
else BOLD=""; DIM=""; YELLOW=""; GREEN=""; RESET=""; fi

cmd="${1:-scan}"
shift || true

# ─── scan ─────────────────────────────────────────────────────────────

scan() {
    echo "${BOLD}Migration candidates for this user:${RESET}"
    echo ""

    # Loose skills overlapping with the plugin bundle
    BUNDLED=(
        tdd onion-ddd-workflow detect-stack
        kiss yagni solid dry separation-of-concerns law-of-demeter
        boy-scout-rule convention-over-configuration
        kaizen workflow
        brainstorming dispatching-parallel-agents executing-plans
        finishing-a-development-branch receiving-code-review
        requesting-code-review subagent-driven-development
        systematic-debugging test-driven-development using-git-worktrees
        using-superpowers verification-before-completion writing-plans
        writing-skills
    )
    echo "${BOLD}1. Loose skills overlapping bundled equivalents${RESET}"
    FOUND_LOOSE=0
    for s in "${BUNDLED[@]}"; do
        if [ -d "$HOME/.claude/skills/$s" ]; then
            SIZE=$(du -sh "$HOME/.claude/skills/$s" 2>/dev/null | awk '{print $1}')
            echo "   ${YELLOW}↻${RESET} ~/.claude/skills/$s ($SIZE)"
            FOUND_LOOSE=1
        fi
    done
    [ "$FOUND_LOOSE" = "0" ] && echo "   ${DIM}(none)${RESET}"
    echo ""
    [ "$FOUND_LOOSE" = "1" ] && echo "   ${DIM}retire: $0 retire-loose-skill <name> --execute${RESET}"
    echo ""

    # Separate marketplaces (remember-md)
    echo "${BOLD}2. Marketplaces with bundled equivalents${RESET}"
    if [ -d "$HOME/.claude/local-marketplaces/remember-md" ]; then
        SIZE=$(du -sh "$HOME/.claude/local-marketplaces/remember-md" 2>/dev/null | awk '{print $1}')
        echo "   ${YELLOW}↻${RESET} ~/.claude/local-marketplaces/remember-md ($SIZE)"
        echo "      5 skills (remember/process/evolve/status/init) + scripts now bundled in kaizen"
        echo "   ${DIM}retire: $0 retire-marketplace remember-md${RESET}"
    else
        echo "   ${DIM}(none)${RESET}"
    fi
    echo ""

    # BACKLOG.md at non-canonical locations (repo root vs .workflow/)
    echo "${BOLD}3. Non-canonical BACKLOG locations (this repo)${RESET}"
    REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || true)
    if [ -n "$REPO_ROOT" ]; then
        if [ -f "$REPO_ROOT/BACKLOG.md" ]; then
            echo "   ${YELLOW}↻${RESET} $REPO_ROOT/BACKLOG.md (repo root — should live in .workflow/ if that dir exists)"
            echo "   ${DIM}migrate: $0 migrate-backlog-to-workflow --execute${RESET}"
        elif [ -f "$REPO_ROOT/.workflow/backlog.md" ] && [ ! -f "$REPO_ROOT/.workflow/backlog.json" ]; then
            echo "   ${YELLOW}↻${RESET} $REPO_ROOT/.workflow/backlog.md exists but no backlog.json — hand-written?"
            echo "   ${DIM}convert: $0 convert-backlog .workflow/backlog.md --execute${RESET}"
        else
            echo "   ${DIM}(canonical layout: .workflow/backlog.json + .workflow/backlog.md)${RESET}"
        fi
    else
        echo "   ${DIM}(not in a git repo)${RESET}"
    fi
    echo ""

    # Standalone kaizen skill that this plugin replaces
    echo "${BOLD}4. Standalone kaizen skill (this session created it)${RESET}"
    if [ -d "$HOME/.claude/skills/kaizen" ]; then
        echo "   ${YELLOW}↻${RESET} ~/.claude/skills/kaizen (predates this plugin)"
        echo "   ${DIM}retire after verifying plugin install:  $0 retire-loose-skill kaizen --execute${RESET}"
    else
        echo "   ${DIM}(already retired)${RESET}"
    fi
}

# ─── retire-loose-skill ───────────────────────────────────────────────

retire_loose_skill() {
    [ $# -lt 1 ] && { echo "retire-loose-skill: missing <name>" >&2; exit 2; }
    NAME="$1"; shift
    EXECUTE=0
    while [ $# -gt 0 ]; do
        case "$1" in --execute) EXECUTE=1 ;; --dry-run) EXECUTE=0 ;; esac
        shift
    done
    SRC="$HOME/.claude/skills/$NAME"
    [ -d "$SRC" ] || { echo "retire-loose-skill: not found: $SRC" >&2; exit 2; }

    if [ "$EXECUTE" = "0" ]; then
        echo "${BOLD}DRY-RUN${RESET} — would:"
        echo "  1. Back up $SRC via $0 backup create --label retire-$NAME"
        echo "  2. mv $SRC ~/.claude/skills/.retired/$NAME-$(date -u +%Y%m%dT%H%M%SZ)"
        echo "  3. Re-run available-skills check; plugin's bundled equivalent should still resolve"
        echo ""
        echo "  Re-run with --execute to actually retire."
        return
    fi

    # Auto-backup (skill content — global, not project-scoped, so use a special path)
    TS=$(date -u +%Y%m%dT%H%M%SZ)
    BAK="$KAIZEN_BACKUP_DIR/_loose-skills/$NAME-$TS.tar.gz"
    mkdir -p "$(dirname "$BAK")"
    tar czf "$BAK" -C "$HOME/.claude/skills" "$NAME"
    echo "  ${GREEN}✓${RESET} backed up: $BAK"

    # Move (not delete) to .retired/ — preserves restorability
    RETIRED="$HOME/.claude/skills/.retired"
    mkdir -p "$RETIRED"
    DEST="$RETIRED/$NAME-$TS"
    mv "$SRC" "$DEST"
    echo "  ${GREEN}✓${RESET} retired: $SRC → $DEST"
    echo "  ${DIM}restore: mv \"$DEST\" \"$SRC\"${RESET}"
}

# ─── retire-marketplace ───────────────────────────────────────────────

retire_marketplace() {
    [ $# -lt 1 ] && { echo "retire-marketplace: missing <name>" >&2; exit 2; }
    NAME="$1"
    SRC="$HOME/.claude/local-marketplaces/$NAME"
    [ -d "$SRC" ] || { echo "retire-marketplace: not found: $SRC" >&2; exit 2; }

    cat <<EOF
${BOLD}To retire the '$NAME' marketplace:${RESET}

  1. In Claude Code, uninstall any plugins from it:
     ${DIM}/plugin uninstall <plugin-name>@$NAME${RESET}

  2. Remove the marketplace:
     ${DIM}/plugin marketplace remove $NAME${RESET}

  3. (Optional) back up + remove the local source:
     $0 backup create --label retire-marketplace-$NAME --include-brain
     ${DIM}mv $SRC ${SRC}.retired-$(date -u +%Y%m%dT%H%M%SZ)${RESET}

  ${YELLOW}This script does not auto-uninstall plugins from Claude Code${RESET}
  ${YELLOW}— that's a UX action you should do via the /plugin command.${RESET}
EOF
}

# ─── convert-backlog ──────────────────────────────────────────────────

convert_backlog() {
    [ $# -lt 1 ] && { echo "convert-backlog: missing <md-path>" >&2; exit 2; }
    MD="$1"; shift
    EXECUTE=0
    while [ $# -gt 0 ]; do
        case "$1" in --execute) EXECUTE=1 ;; --dry-run) EXECUTE=0 ;; esac
        shift
    done
    [ -f "$MD" ] || { echo "convert-backlog: not found: $MD" >&2; exit 2; }

    # Naive parser: matches `- [ ] Title — probe: \`P\` — verify: \`V\``
    # Anything more complex requires hand-fix after.
    if [ "$EXECUTE" = "0" ]; then
        echo "${BOLD}DRY-RUN${RESET} — would parse:"
        python3 - "$MD" <<'PY'
import re, sys
text = open(sys.argv[1]).read()
section = None
for line in text.splitlines():
    if m := re.match(r"^## (In flight|Next up|Done|Parked)", line):
        section = m.group(1).lower().replace(" ", "_")
        print(f"  → section: {section}")
        continue
    if section and (m := re.match(r"^- \[([ x])\] (.+?)(?:\s+—\s+probe:\s*`([^`]+)`)?(?:\s+—\s+verify:\s*`([^`]+)`)?(?:\s+—\s+parked:\s*(.+))?$", line)):
        title = m.group(2).strip()
        probe = m.group(3) or ""
        verify = m.group(4) or ""
        print(f"    + [{section}] {title}")
PY
        echo "  Re-run with --execute to actually convert into backlog.json items."
        return
    fi

    # Execute path: parse, then call backlog.py add for each line
    python3 - "$MD" "$BACKLOG_PY" <<'PY'
import re, subprocess, sys
md, backlog_py = sys.argv[1], sys.argv[2]
text = open(md).read()
section = None
added = 0
section_map = {"in flight": "in_flight", "next up": "next_up", "done (this week)": "done", "parked / deferred": "parked"}
for line in text.splitlines():
    if m := re.match(r"^## (.+?)\s*$", line):
        section = section_map.get(m.group(1).lower().strip())
        continue
    if section and (m := re.match(r"^- \[([ x])\] (.+?)(?:\s+—\s+probe:\s*`([^`]+)`)?(?:\s+—\s+verify:\s*`([^`]+)`)?$", line)):
        title = m.group(2).strip()
        probe = m.group(3) or "(none captured)"
        verify = m.group(4) or "(none captured)"
        cmd = ["python3", backlog_py, "add",
               "--title", title, "--probe", probe, "--verify", verify,
               "--section", section]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            added += 1
print(f"  ✓ converted {added} items from {md} → backlog.json")
PY
}

# ─── migrate-backlog-to-workflow ──────────────────────────────────────

migrate_backlog_to_workflow() {
    EXECUTE=0
    while [ $# -gt 0 ]; do
        case "$1" in --execute) EXECUTE=1 ;; --dry-run) EXECUTE=0 ;; esac
        shift
    done
    REPO_ROOT=$(git rev-parse --show-toplevel)
    SRC="$REPO_ROOT/BACKLOG.md"
    DST_DIR="$REPO_ROOT/.workflow"
    DST="$DST_DIR/backlog.md"

    [ -f "$SRC" ] || { echo "migrate-backlog-to-workflow: no BACKLOG.md at repo root" >&2; exit 2; }
    [ -f "$DST" ] && { echo "migrate-backlog-to-workflow: $DST already exists; manual merge needed" >&2; exit 2; }

    if [ "$EXECUTE" = "0" ]; then
        echo "${BOLD}DRY-RUN${RESET} — would:"
        echo "  1. Back up current state via $0 backup create --label backlog-migrate"
        echo "  2. mkdir -p $DST_DIR"
        echo "  3. convert-backlog $SRC --execute (creates backlog.json + renders backlog.md)"
        echo "  4. mv $SRC $SRC.migrated"
        echo "  5. sed -i .kaizen.toml  backlog_path → .workflow/backlog.md"
        echo "  Re-run with --execute."
        return
    fi

    # Auto-backup
    bash "$BACKUP_SH" create --label "backlog-migrate" >&2

    mkdir -p "$DST_DIR"
    convert_backlog "$SRC" --execute
    mv "$SRC" "$SRC.migrated"
    if grep -q "^backlog_path" "$REPO_ROOT/.kaizen.toml" 2>/dev/null; then
        # sed -i.bak preserves a verification artifact (silences
        # efficient-tool-use::sed-in-place-no-diff). Diff post-edit so a
        # bad regex surfaces immediately instead of silently corrupting
        # the user's config.
        sed -i.bak 's|^backlog_path.*|backlog_path      = ".workflow/backlog.md"|' "$REPO_ROOT/.kaizen.toml"
        if ! diff -q "$REPO_ROOT/.kaizen.toml" "$REPO_ROOT/.kaizen.toml.bak" >/dev/null 2>&1; then
            rm "$REPO_ROOT/.kaizen.toml.bak"
            echo "  ✓ updated backlog_path in .kaizen.toml"
        else
            mv "$REPO_ROOT/.kaizen.toml.bak" "$REPO_ROOT/.kaizen.toml"
            echo "  ! backlog_path edit no-op'd (regex didn't match) — investigate"
        fi
    fi
    echo "  ✓ migrated BACKLOG.md → .workflow/backlog.{json,md}; original kept as ${SRC}.migrated"
}

# ─── dispatch ─────────────────────────────────────────────────────────

case "$cmd" in
    scan)                          scan ;;
    retire-loose-skill)            retire_loose_skill "$@" ;;
    retire-marketplace)            retire_marketplace "$@" ;;
    convert-backlog)               convert_backlog "$@" ;;
    migrate-backlog-to-workflow)   migrate_backlog_to_workflow "$@" ;;
    paths)
        # Pre-v1.22 path-restructure migrator; delegate to sibling script.
        # Kept here as a subcommand so `kaizen migrate` is the single
        # entry point — `kaizen-migrate-paths` slash was retired
        # 2026-05-17; users should invoke `kaizen migrate paths` instead.
        exec "$_SCRIPT_REAL_DIR/migrate_paths.sh" "$@" ;;
    -h|--help)
        echo "Usage: migrate.sh {scan|retire-loose-skill|retire-marketplace|convert-backlog|migrate-backlog-to-workflow|paths}"
        ;;
    *)
        echo "migrate: unknown subcommand '$cmd'" >&2; exit 2 ;;
esac
