#!/usr/bin/env bash
# kaizen commit-msg gate — message-dependent checks.
#
# Symlinked from the skill into a project's .kaizen/hooks/commit-msg via
# scripts/setup.sh. Receives the path to the message file as $1 (the
# canonical commit-msg hook contract), which pre-commit does NOT — that
# is why these two checks live here:
#
#   • Conventional Commits prefix
#   • Plan-file mention → checkbox tick
#
# Split out from pre-commit.sh because git does NOT pre-populate
# .git/COMMIT_EDITMSG before pre-commit runs for `git commit -m "..."`
# invocations — the previous gate's fallback read of that file always
# saw the *previous* commit's message and either passed-or-failed on
# stale state (the "yarrr" reproducer).
#
# Bypass for emergencies: git commit --no-verify (agent must surface,
# not silently bypass).

set -u

# ─── Shared helpers from lib.sh (M3 dedup) ───────────────────────────
_SCRIPT_REAL_DIR="$(cd "$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"
. "$_SCRIPT_REAL_DIR/lib.sh"
color_init
PASS="${GREEN}✓${RESET}"
FAIL="${RED}✗${RESET}"
SKIP_GLYPH="${DIM}∘${RESET}"

HARD_FAILS=0
emit()      { printf '%s  %s\n' "$1" "$2" >&2; }
pass()      { emit "$PASS" "$1"; }
hard_fail() { HARD_FAILS=$((HARD_FAILS + 1)); emit "$FAIL" "$1"; }
skip()      { emit "$SKIP_GLYPH" "$1"; }

# ─── Resolve message file ─────────────────────────────────────────────
MSG_FILE="${1:-}"
if [ -z "$MSG_FILE" ] || [ ! -f "$MSG_FILE" ]; then
    # No path passed (shouldn't happen for commit-msg hook) — bail soft.
    echo "${DIM}kaizen commit-msg: no message file argument — skipping${RESET}" >&2
    exit 0
fi

# Strip comment lines the same way `git commit` does before recording.
RAW_MSG=$(grep -vE '^#' "$MSG_FILE")
FIRST_LINE=$(echo "$RAW_MSG" | sed '/^$/d' | head -1)

if [ -z "$FIRST_LINE" ]; then
    # Empty message — git itself will abort.
    exit 0
fi

# ─── Repo discovery + tiny TOML reader (mirrors pre-commit.sh) ────────
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "${DIM}kaizen commit-msg: not a git repo — skipping${RESET}" >&2
    exit 0
}
cd "$REPO_ROOT"
CONFIG="$REPO_ROOT/.kaizen.toml"
TOML_PATH="$CONFIG"   # lib.sh's toml_get reads $TOML_PATH

PLAN_DIR=$(toml_get plan_dir "plans")

# ─── Check 2: Conventional Commits prefix ─────────────────────────────
# The trailing `!` permits the breaking-change marker (`feat!:` / `fix(scope)!:`)
# per Conventional Commits §6.
if echo "$FIRST_LINE" | grep -qE '^(feat|fix|refactor|docs|chore|test|perf|build|ci|style|revert)(\([^)]+\))?(!)?: '; then
    pass "Conventional Commits prefix"
else
    hard_fail "commit message missing Conventional Commits prefix: $FIRST_LINE"
    echo "${DIM}        → expected: feat(scope): ... | fix: ... | docs: ... etc.${RESET}" >&2
fi

# ─── Check 4: Plan-file mention → checkbox tick ───────────────────────
STAGED=$(git diff --cached --name-only --diff-filter=ACMRT 2>/dev/null)
DIFF_CONTENT=$(git diff --cached 2>/dev/null)
PLAN_MENTIONS=$(echo "$RAW_MSG" | grep -oE "${PLAN_DIR}/[A-Za-z0-9._-]+\.md" | sort -u || true)

if [ -n "$PLAN_MENTIONS" ]; then
    for plan_path in $PLAN_MENTIONS; do
        # Cross-repo plan references: when the mentioned plan file doesn't
        # exist in THIS repo (e.g. a kaizen-md commit referencing shodan's
        # plans/), the gate has nothing to enforce locally — the plan
        # checkbox tick happens in the OTHER repo's commit. Treat as
        # informational; don't block. The original "I forgot to stage the
        # plan file" intent still fires when the file exists locally.
        if [ ! -f "$REPO_ROOT/$plan_path" ]; then
            skip "plan ${plan_path}: not present in this repo (cross-repo reference)"
            continue
        fi
        if echo "$STAGED" | grep -qF "$plan_path"; then
            if echo "$DIFF_CONTENT" | grep -E "^\+- \[x\]" >/dev/null 2>&1; then
                pass "plan ${plan_path}: checkbox tick present"
            else
                hard_fail "plan ${plan_path} mentioned but no ${BOLD}+- [x]${RESET} flip staged"
            fi
        else
            hard_fail "plan ${plan_path} mentioned in commit but file not staged"
        fi
    done
else
    skip "no plan-file mention in commit message"
fi

# ─── Verdict ──────────────────────────────────────────────────────────
if [ "$HARD_FAILS" -gt 0 ]; then
    echo "" >&2
    echo "${BOLD}kaizen commit-msg: $HARD_FAILS hard fail(s)${RESET}" >&2
    echo "${DIM}Bypass: git commit --no-verify (last resort — surface, don't silently skip)${RESET}" >&2
    exit 1
fi
exit 0
