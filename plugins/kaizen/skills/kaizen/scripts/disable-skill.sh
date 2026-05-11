#!/usr/bin/env bash
# kaizen disable-skill — reversibly toggle loose-skill discovery.
#
# Mechanism: rename SKILL.md ↔ SKILL.md.disabled. Auto-discovery scans
# for SKILL.md only, so renaming hides the skill without moving any
# files. Reversible with one rename.
#
# Subcommands:
#   scan                                List loose skills that duplicate plugin bundle
#   disable <skill> [--loose|--plugin]  Disable one side (default: loose)
#   enable  <skill> [--loose|--plugin]  Re-enable
#   list-disabled                       Show currently-disabled skills
#   all-loose-dupes [--execute]         Disable every loose-side duplicate (dry-run default)
#   all-loose-dupes --restore           Re-enable every disabled loose-side duplicate

set -uo pipefail

_SCRIPT_REAL_DIR="$(cd "$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"

# Resolve plugin skills dir (this script lives inside it)
PLUGIN_SKILLS_DIR="$(cd "$_SCRIPT_REAL_DIR/../.." && pwd)"   # …/skills/
LOOSE_SKILLS_DIR="$HOME/.claude/skills"

if [ -t 1 ]; then
    BOLD=$'\e[1m'; DIM=$'\e[2m'; YELLOW=$'\e[33m'; GREEN=$'\e[32m'; RED=$'\e[31m'; RESET=$'\e[0m'
else
    BOLD=""; DIM=""; YELLOW=""; GREEN=""; RED=""; RESET=""
fi

# ─── helpers ──────────────────────────────────────────────────────────

list_bundled() {
    # Portable replacement for GNU `find -printf '%f\n'`.
    for d in "$PLUGIN_SKILLS_DIR"/*/; do
        [ -d "$d" ] && basename "$d"
    done | sort
}

is_disabled() {
    local path="$1"
    [ ! -f "$path/SKILL.md" ] && [ -f "$path/SKILL.md.disabled" ]
}

is_enabled() {
    local path="$1"
    [ -f "$path/SKILL.md" ]
}

resolve_path() {
    local side="$1" name="$2"
    case "$side" in
        loose)  echo "$LOOSE_SKILLS_DIR/$name" ;;
        plugin) echo "$PLUGIN_SKILLS_DIR/$name" ;;
        *)      echo "$LOOSE_SKILLS_DIR/$name" ;;   # default
    esac
}

# ─── subcommands ──────────────────────────────────────────────────────

scan() {
    echo "${BOLD}Duplicate skills (loose ↔ plugin bundle):${RESET}"
    echo ""
    local count_dup=0 count_dis=0
    while IFS= read -r name; do
        if [ -d "$LOOSE_SKILLS_DIR/$name" ]; then
            count_dup=$((count_dup + 1))
            if is_disabled "$LOOSE_SKILLS_DIR/$name"; then
                echo "  ${GREEN}✓${RESET} $name  ${DIM}(loose disabled — plugin version wins)${RESET}"
                count_dis=$((count_dis + 1))
            elif is_enabled "$LOOSE_SKILLS_DIR/$name"; then
                echo "  ${YELLOW}↻${RESET} $name  ${DIM}(both enabled — DUPLICATE in available-skills)${RESET}"
            fi
        fi
    done < <(list_bundled)
    echo ""
    echo "${DIM}Total dupes: $count_dup  |  loose-disabled: $count_dis${RESET}"
    if [ "$count_dup" -gt "$count_dis" ]; then
        echo ""
        echo "${DIM}Disable all loose-side: $0 all-loose-dupes --execute${RESET}"
    fi
}

disable_one() {
    [ $# -lt 1 ] && { echo "disable: missing <skill>" >&2; exit 2; }
    local name="$1" side="loose"; shift
    while [ $# -gt 0 ]; do
        case "$1" in --loose) side="loose" ;; --plugin) side="plugin" ;; esac
        shift
    done
    local p="$(resolve_path "$side" "$name")"
    [ -d "$p" ] || { echo "${RED}disable: not found:${RESET} $p" >&2; exit 2; }
    if is_disabled "$p"; then
        echo "  ${DIM}∘${RESET} $name [$side] already disabled"
        return
    fi
    if [ ! -f "$p/SKILL.md" ]; then
        echo "  ${RED}✗${RESET} $name [$side]: no SKILL.md to disable"
        return 1
    fi
    mv "$p/SKILL.md" "$p/SKILL.md.disabled"
    echo "  ${GREEN}✓${RESET} disabled: $p/SKILL.md → SKILL.md.disabled"
}

enable_one() {
    [ $# -lt 1 ] && { echo "enable: missing <skill>" >&2; exit 2; }
    local name="$1" side="loose"; shift
    while [ $# -gt 0 ]; do
        case "$1" in --loose) side="loose" ;; --plugin) side="plugin" ;; esac
        shift
    done
    local p="$(resolve_path "$side" "$name")"
    [ -d "$p" ] || { echo "${RED}enable: not found:${RESET} $p" >&2; exit 2; }
    if is_enabled "$p"; then
        echo "  ${DIM}∘${RESET} $name [$side] already enabled"
        return
    fi
    if [ ! -f "$p/SKILL.md.disabled" ]; then
        echo "  ${RED}✗${RESET} $name [$side]: no SKILL.md.disabled to re-enable"
        return 1
    fi
    mv "$p/SKILL.md.disabled" "$p/SKILL.md"
    echo "  ${GREEN}✓${RESET} enabled: $p/SKILL.md.disabled → SKILL.md"
}

list_disabled() {
    echo "${BOLD}Currently-disabled skills:${RESET}"
    local found=0
    for base in "$LOOSE_SKILLS_DIR" "$PLUGIN_SKILLS_DIR"; do
        [ -d "$base" ] || continue
        find "$base" -maxdepth 2 -name "SKILL.md.disabled" 2>/dev/null | while read f; do
            dir="$(dirname "$f")"
            name="$(basename "$dir")"
            location="loose"
            [ "$base" = "$PLUGIN_SKILLS_DIR" ] && location="plugin"
            echo "  $name [$location] — $f"
        done
        # Count via a sub-shell quirk — find inside while subshell loses counter
        if [ "$(find "$base" -maxdepth 2 -name SKILL.md.disabled 2>/dev/null | wc -l)" -gt "0" ]; then
            found=1
        fi
    done
    [ "$found" = "0" ] && echo "  ${DIM}(none disabled)${RESET}"
}

all_loose_dupes() {
    local execute=0 restore=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --execute) execute=1 ;;
            --restore) restore=1 ;;
            --dry-run) execute=0 ;;
        esac
        shift
    done

    if [ "$restore" = "1" ]; then
        echo "${BOLD}Re-enabling all loose-side disabled duplicates:${RESET}"
        while IFS= read -r name; do
            local p="$LOOSE_SKILLS_DIR/$name"
            if [ -f "$p/SKILL.md.disabled" ]; then
                if [ "$execute" = "1" ]; then
                    enable_one "$name" --loose
                else
                    echo "  ${DIM}DRY-RUN${RESET} would re-enable: $p/SKILL.md.disabled"
                fi
            fi
        done < <(list_bundled)
        [ "$execute" = "0" ] && echo "" && echo "${DIM}Re-run with --execute to apply.${RESET}"
        return
    fi

    echo "${BOLD}Disabling all loose-side duplicates:${RESET}"
    local n=0
    while IFS= read -r name; do
        local p="$LOOSE_SKILLS_DIR/$name"
        if is_enabled "$p"; then
            n=$((n + 1))
            if [ "$execute" = "1" ]; then
                disable_one "$name" --loose
            else
                echo "  ${DIM}DRY-RUN${RESET} would disable: $p/SKILL.md"
            fi
        fi
    done < <(list_bundled)
    if [ "$n" = "0" ]; then
        echo "  ${DIM}(no enabled loose duplicates found)${RESET}"
    elif [ "$execute" = "0" ]; then
        echo ""
        echo "${DIM}Re-run with --execute to apply. Restore with: $0 all-loose-dupes --restore --execute${RESET}"
    fi
}

# ─── dispatch ─────────────────────────────────────────────────────────

cmd="${1:-scan}"
shift || true

case "$cmd" in
    scan)             scan ;;
    disable)          disable_one "$@" ;;
    enable)           enable_one "$@" ;;
    list-disabled)    list_disabled ;;
    all-loose-dupes)  all_loose_dupes "$@" ;;
    -h|--help)
        sed -n '2,/^set -uo/p' "$0" | sed 's/^# \?//'
        ;;
    *)
        echo "disable-skill: unknown subcommand '$cmd'" >&2
        echo "       try: scan | disable | enable | list-disabled | all-loose-dupes" >&2
        exit 2
        ;;
esac
