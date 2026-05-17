#!/usr/bin/env bash
# kaizen health — diagnostic health check.
# Reports broken symlinks, missing scripts, schema mismatch, config errors,
# stale hook paths. Read-only. Exits 0 if all green, 1 if any RED issue.
#
# v1.30.0+: renamed from doctor.sh → health.sh so the script file matches
# the `/kaizen:health` user-facing slash command (the `/kaizen:doctor`
# command was retired in v1.18.0 — see CHANGELOG).

set -uo pipefail

_LIB_DIR="$(cd "$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"
. "$_LIB_DIR/lib.sh"
# v1.30.0+ — unified path SSOT.
source "$_LIB_DIR/_paths.sh"
color_init

REPO=$(repo_root)
[ -z "$REPO" ] && { echo "health: not in a git repo" >&2; exit 0; }
cd "$REPO"

# Counters
FAIL=0; WARN=0

check_fail() { FAIL=$((FAIL + 1)); log_fail "$1"; }
check_warn() { WARN=$((WARN + 1)); log_warn "$1"; }

echo "${BOLD}kaizen health — diagnostic health check${RESET}"
echo ""

# ─── Section 1: Config ────────────────────────────────────────────────
echo "${BOLD}[ config ]${RESET}"
if [ ! -f .kaizen.toml ]; then
    check_fail ".kaizen.toml missing — run /kaizen:setup"
else
    log_pass ".kaizen.toml present"
    # Validate referenced paths
    BACKLOG_MD=$(toml_get backlog_path "")
    ARCH_LOG=$(toml_get architecture_log "")
    VERIFY=$(toml_get verify_cmd "")

    if [ -n "$BACKLOG_MD" ]; then
        BACKLOG_JSON="${BACKLOG_MD%.md}.json"
        [ -f "$BACKLOG_JSON" ] && log_pass "backlog source: $BACKLOG_JSON" \
            || check_warn "backlog_path → $BACKLOG_JSON not on disk (run /kaizen:backlog list to seed)"
    fi
    [ -n "$ARCH_LOG" ] && [ -f "$ARCH_LOG" ] && log_pass "architecture log: $ARCH_LOG" \
        || log_skip "architecture log: $ARCH_LOG (will be created by first structural commit)"
    [ -n "$VERIFY" ] && log_pass "verify_cmd: $VERIFY" || log_skip "verify_cmd: (none)"
fi

echo ""

# ─── Section 2: Hook ──────────────────────────────────────────────────
echo "${BOLD}[ hook ]${RESET}"
HOOKS_PATH=$(git config core.hooksPath 2>/dev/null)
if [ "$HOOKS_PATH" = ".kaizen/hooks" ]; then
    log_pass "core.hooksPath = .kaizen/hooks (local)"
    # pre-commit is required; commit-msg is optional for older installs
    # that pre-date the v1.25.1 hook split. Re-running /kaizen:setup
    # adds it.
    for hook_name in pre-commit commit-msg; do
        HOOK_LINK=".kaizen/hooks/$hook_name"
        if [ -L "$HOOK_LINK" ]; then
            TGT=$(realpath_f "$HOOK_LINK" 2>/dev/null)
            if [ -x "$TGT" ]; then
                log_pass "$hook_name → $TGT (executable)"
            else
                check_fail "$hook_name symlink points at non-executable $TGT"
            fi
        elif [ -f "$HOOK_LINK" ]; then
            check_warn "$hook_name is a regular file, not a symlink (manual install?)"
        else
            if [ "$hook_name" = "pre-commit" ]; then
                check_fail "pre-commit hook missing — re-run /kaizen:setup"
            else
                check_warn "commit-msg hook missing — re-run /kaizen:setup for Conventional Commits + plan-mention checks"
            fi
        fi
    done
else
    check_warn "core.hooksPath = '${HOOKS_PATH:-<unset>}' (expected .kaizen/hooks)"
    log_info "run /kaizen:setup to activate"
fi

echo ""

# ─── Section 3: Scripts ───────────────────────────────────────────────
echo "${BOLD}[ scripts ]${RESET}"
for s in backlog.py pre-commit.sh commit-msg.sh setup.sh migrate.sh backup.sh status.sh disable-skill.sh test-pipeline.sh health.sh; do
    p="$_LIB_DIR/$s"
    if [ -x "$p" ]; then
        log_pass "$s"
    elif [ -f "$p" ]; then
        check_warn "$s exists but not executable (chmod +x missing)"
    else
        check_fail "$s missing"
    fi
done

echo ""

# ─── Section 4: Backlog schema ─────────────────────────────────────────
echo "${BOLD}[ backlog schema ]${RESET}"
if [ -f "${BACKLOG_JSON:-}" ]; then
    python3 - "$BACKLOG_JSON" <<'PY' && log_pass "backlog.json schema valid" || check_fail "backlog.json schema invalid"
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    assert data.get("schema_version") == 1, "schema_version != 1"
    assert data.get("kind") == "kaizen.backlog", "kind mismatch"
    assert isinstance(data.get("items", []), list), "items not a list"
    for i, it in enumerate(data.get("items", [])):
        for f in ("id", "section", "title"):
            assert f in it, f"item {i} missing {f}"
        assert it["section"] in ("in_flight", "next_up", "done", "parked"), f"item {i} bad section"
    sys.exit(0)
except Exception as e:
    print(f"schema error: {e}", file=sys.stderr)
    sys.exit(1)
PY

    # Drift check
    BACKLOG_PY="$_LIB_DIR/backlog.py"
    if [ -x "$BACKLOG_PY" ]; then
        if python3 "$BACKLOG_PY" verify >/dev/null 2>&1; then
            log_pass "backlog .md matches .json (no drift)"
        else
            check_warn "backlog .md drifted from .json (run: python3 backlog.py render)"
        fi
    fi
else
    log_skip "backlog schema: no ${BACKLOG_JSON:-(unconfigured)} yet"
fi

echo ""

# ─── Section 5: Plugin bundle integrity ───────────────────────────────
echo "${BOLD}[ plugin bundle ]${RESET}"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$_LIB_DIR/../../.." 2>/dev/null && pwd)}"
if [ -d "$PLUGIN_ROOT/skills" ]; then
    SKILL_COUNT=$(find "$PLUGIN_ROOT/skills" -maxdepth 2 -name "SKILL.md" | wc -l)
    log_pass "plugin skills: $SKILL_COUNT bundled"
    # Spot-check critical scripts
    for f in "$PLUGIN_ROOT/scripts/build-index.js" "$PLUGIN_ROOT/scripts/extract.js"; do
        if [ -f "$f" ]; then log_pass "$(basename $f) present"
        else log_skip "$(basename $f) missing (remember tooling won't work)"; fi
    done
elif [ -d "$_LIB_DIR/../references" ]; then
    log_skip "standalone install (no plugin bundle)"
else
    check_warn "plugin bundle path unclear"
fi

echo ""

# ─── Section 6: Brain / project memory ─────────────────────────────────
echo "${BOLD}[ memory ]${RESET}"
BRAIN=$(toml_get brain_path "${KAIZEN_BRAIN_DIR:-$HOME/.claude/.kaizen/brain}")
PMEM=$(toml_get project_memory_path "")
if [ -f "$BRAIN/Persona.md" ]; then
    log_pass "brain Persona.md: $BRAIN/Persona.md"
    if [ -f "$BRAIN/Notes/pref-no-deletions.md" ]; then
        log_pass "pre-deletion belief present (gate scan will block git rm)"
    else
        log_skip "no pref-no-deletions.md in brain (deletion gate will pass-through)"
    fi
else
    log_skip "no brain at $BRAIN (run kaizen-brain-migrate or kaizen-brain init)"
fi
[ -n "$PMEM" ] && [ -d "$PMEM" ] && log_pass "project memory: $PMEM" \
    || log_skip "no project memory configured"

echo ""

# ─── Section 7: Backups ────────────────────────────────────────────────
echo "${BOLD}[ backups ]${RESET}"
SLUG=$(echo "$REPO" | sed 's|^/||; s|/|-|g')
BAK_DIR="$KAIZEN_BACKUP_DIR/$SLUG"
COUNT=$(ls -1 "$BAK_DIR"/*.tar.gz 2>/dev/null | wc -l)
if [ "$COUNT" -gt "0" ]; then
    LAST=$(ls -1t "$BAK_DIR"/*.tar.gz 2>/dev/null | head -1 | xargs -I {} basename {} .tar.gz 2>/dev/null)
    log_pass "$COUNT backup(s) | latest: $LAST"
    [ "$COUNT" -gt "20" ] && check_warn "$COUNT backups accumulated — consider /kaizen:backup prune --keep 10"
else
    log_skip "no backups yet"
fi

echo ""

# ─── Summary ──────────────────────────────────────────────────────────
if [ "$FAIL" = "0" ] && [ "$WARN" = "0" ]; then
    printf "%sResult: healthy (no issues)%s\n" "$BOLD$GREEN" "$RESET" >&2
    exit 0
elif [ "$FAIL" = "0" ]; then
    printf "%sResult: %d warning(s), 0 errors%s\n" "$BOLD$YELLOW" "$WARN" "$RESET" >&2
    exit 0
else
    printf "%sResult: %d error(s), %d warning(s)%s\n" "$BOLD$RED" "$FAIL" "$WARN" "$RESET" >&2
    exit 1
fi
