#!/usr/bin/env bash
# kaizen pipeline test — end-to-end smoke against all surfaces.
#
# Designed for low token/context overhead:
#   - TAP-style: one line per test (ok / not ok N - description)
#   - Detail only on FAIL (--verbose for everything)
#   - Runs in /tmp/gwtest-<PID> sandbox, deleted at end
#   - Single summary line at the bottom
#
# Usage:
#   test-pipeline.sh           default (compact output)
#   test-pipeline.sh -v        verbose (show stdout of each sub-command)
#   test-pipeline.sh --keep    don't delete the sandbox

set -uo pipefail

_SCRIPT_REAL_DIR="$(cd "$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"

# Plugin root (scripts/ → workflow/ → skills/ → kaizen plugin root)
PLUGIN_ROOT="$(cd "$_SCRIPT_REAL_DIR/../../.." && pwd)"
HOOKS_DIR="$PLUGIN_ROOT/hooks/claude"
GW_SCRIPTS="$_SCRIPT_REAL_DIR"

# v1.30.0+ — unified path SSOT.
source "$_SCRIPT_REAL_DIR/_paths.sh"

# Hook scripts read CLAUDE_PLUGIN_ROOT at run time (Claude Code's harness
# sets it). The test harness simulates that here so hook stdout stays
# valid JSON instead of "unbound variable" stderr noise.
export CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT"

VERBOSE=0
KEEP_SANDBOX=0
for arg in "$@"; do
    case "$arg" in
        -v|--verbose) VERBOSE=1 ;;
        --keep)       KEEP_SANDBOX=1 ;;
    esac
done

# Sandbox
SANDBOX=$(mktemp -d "/tmp/gwtest-XXXXXX")
trap '[ "$KEEP_SANDBOX" = "0" ] && rm -rf "$SANDBOX"' EXIT
cd "$SANDBOX"
git init -q
git config user.email "t@t" && git config user.name "t"
git commit --allow-empty -q -m "feat(init): bootstrap" 2>/dev/null

if [ -t 1 ]; then GREEN=$'\e[32m'; RED=$'\e[31m'; DIM=$'\e[2m'; BOLD=$'\e[1m'; RESET=$'\e[0m'
else GREEN=""; RED=""; DIM=""; BOLD=""; RESET=""; fi

# Counters
N=0; PASS=0; FAIL=0
FAILS=()

# tap <description> <command...>
# Runs command, captures exit + output. PASS if exit 0; FAIL otherwise.
# Detail on FAIL: shows last 5 lines of captured output.
tap() {
    local desc="$1"; shift
    N=$((N + 1))
    local out
    out=$("$@" 2>&1)
    local ec=$?
    if [ $ec -eq 0 ]; then
        PASS=$((PASS + 1))
        printf "%sok %d -%s %s\n" "$GREEN" "$N" "$RESET" "$desc"
        [ "$VERBOSE" = "1" ] && [ -n "$out" ] && echo "$out" | sed 's/^/    /'
    else
        FAIL=$((FAIL + 1))
        printf "%snot ok %d -%s %s %s(exit=%d)%s\n" "$RED" "$N" "$RESET" "$desc" "$DIM" "$ec" "$RESET"
        echo "$out" | tail -5 | sed 's/^/    /'
        FAILS+=("$N: $desc")
    fi
}

# assert <description> — pass=0, fail=non-zero; pre-evaluated by caller via [ ... ]
assert() {
    local desc="$1" ec="$2"
    N=$((N + 1))
    if [ "$ec" -eq 0 ]; then
        PASS=$((PASS + 1))
        printf "%sok %d -%s %s\n" "$GREEN" "$N" "$RESET" "$desc"
    else
        FAIL=$((FAIL + 1))
        printf "%snot ok %d -%s %s\n" "$RED" "$N" "$RESET" "$desc"
        FAILS+=("$N: $desc")
    fi
}

START_TS=$(date +%s)

# ──────────────────────────────────────────────────────────────────────
# Stage 1 — install in sandbox
# ──────────────────────────────────────────────────────────────────────
tap "setup.sh runs cleanly" bash "$GW_SCRIPTS/setup.sh"
assert ".kaizen.toml exists" $([ -f "$SANDBOX/.kaizen.toml" ] && echo 0 || echo 1)
assert ".kaizen/hooks/pre-commit is a symlink" $([ -L "$SANDBOX/.kaizen/hooks/pre-commit" ] && echo 0 || echo 1)
assert "core.hooksPath set to .kaizen/hooks" $([ "$(git config core.hooksPath)" = ".kaizen/hooks" ] && echo 0 || echo 1)
assert ".kaizen/.gitignore policy file written" $([ -f .kaizen/.gitignore ] && echo 0 || echo 1)

# Resolve backlog_path from .kaizen.toml so we test what install set up
BACKLOG_MD=$(grep -E '^backlog_path' .kaizen.toml 2>/dev/null \
    | head -1 | sed -E 's/^[^=]*=[[:space:]]*"?([^"]*)"?.*$/\1/')
BACKLOG_JSON="${BACKLOG_MD%.md}.json"

# ──────────────────────────────────────────────────────────────────────
# Stage 2 — backlog.py lifecycle
# ──────────────────────────────────────────────────────────────────────
tap "backlog add" python3 "$GW_SCRIPTS/backlog.py" add --title "test item" --probe "grep x" --verify "make t"
assert "backlog.json has 1 item" $(python3 -c "import json; d=json.load(open('$BACKLOG_JSON')); exit(0 if len(d['items'])==1 else 1)"; echo $?)
tap "backlog start BK-001" python3 "$GW_SCRIPTS/backlog.py" start BK-001
assert "BK-001 in_flight" $(python3 -c "import json; d=json.load(open('$BACKLOG_JSON')); exit(0 if d['items'][0]['section']=='in_flight' else 1)"; echo $?)
tap "backlog tick BK-001" python3 "$GW_SCRIPTS/backlog.py" tick BK-001 --committed abc1234
assert "BK-001 done with sha" $(python3 -c "import json; d=json.load(open('$BACKLOG_JSON')); exit(0 if d['items'][0]['section']=='done' and d['items'][0]['committed']=='abc1234' else 1)"; echo $?)
tap "backlog verify (no drift)" python3 "$GW_SCRIPTS/backlog.py" verify

# ──────────────────────────────────────────────────────────────────────
# Stage 3 — pre-commit gate scenarios
# ──────────────────────────────────────────────────────────────────────

# 3a. Empty stage → exits 0, no fails
EMPTY_OUT=$(bash "$GW_SCRIPTS/pre-commit.sh" 2>&1); EC=$?
assert "gate: empty stage exits 0" $EC

# 3b. Stage a trivial file with no structural smell
echo "feat(test): smoke" > /tmp/cm-test.txt
echo "console.log('hi')" > test.js
git add test.js
COMMIT_MSG_FILE=/tmp/cm-test.txt bash "$GW_SCRIPTS/pre-commit.sh" >/tmp/gw-trivial.log 2>&1
EC=$?
git restore --staged test.js >/dev/null 2>&1
# May warn (no compile cmd set in fresh repo) but should not hard-fail
assert "gate: trivial diff exits 0 or warnings-only" $([ $EC -eq 0 ] && echo 0 || ([ $EC -eq 1 ] && grep -q "warning(s)" /tmp/gw-trivial.log && echo 0) || echo 1)

# 3c. PreToolUse(Bash) for git rm → should yield 'ask'
PT_OUT=$(echo '{"tool_input":{"command":"git rm crates/foo.rs"}}' | bash "$HOOKS_DIR/pretooluse-bash-gate.sh")
echo "$PT_OUT" | grep -q '"permissionDecision": "ask"'
assert "PreToolUse(git rm) → ask" $?

# 3d. PreToolUse(Bash) for `ls -la` → no opinion (empty {})
PT_OUT=$(echo '{"tool_input":{"command":"ls -la"}}' | bash "$HOOKS_DIR/pretooluse-bash-gate.sh")
echo "$PT_OUT" | grep -q '^{}'
assert "PreToolUse(ls) → allow ({})" $?

# 3e. PreToolUse(Bash) for `git push --force` → ask
PT_OUT=$(echo '{"tool_input":{"command":"git push --force origin main"}}' | bash "$HOOKS_DIR/pretooluse-bash-gate.sh")
echo "$PT_OUT" | grep -q '"permissionDecision": "ask"'
assert "PreToolUse(git push --force) → ask" $?

# ──────────────────────────────────────────────────────────────────────
# Stage 4 — backup lifecycle
# ──────────────────────────────────────────────────────────────────────
SANDBOX_SLUG=$(echo "$SANDBOX" | sed 's|^/||; s|/|-|g')
BAK_DIR="$KAIZEN_BACKUP_DIR/$SANDBOX_SLUG"

tap "backup create" bash "$GW_SCRIPTS/backup.sh" create --label test
assert "backup tarball exists" $([ "$(ls -1 $BAK_DIR/*.tar.gz 2>/dev/null | wc -l)" -ge "1" ] && echo 0 || echo 1)
tap "backup list" bash "$GW_SCRIPTS/backup.sh" list
tap "backup prune --keep 1" bash "$GW_SCRIPTS/backup.sh" prune --keep 1

# ──────────────────────────────────────────────────────────────────────
# Stage 5 — migrate / disable-skill / status (read-only)
# ──────────────────────────────────────────────────────────────────────
tap "migrate scan" bash "$GW_SCRIPTS/migrate.sh" scan
tap "disable-skill scan" bash "$GW_SCRIPTS/disable-skill.sh" scan
tap "status report" bash "$GW_SCRIPTS/status.sh"

# ──────────────────────────────────────────────────────────────────────
# Stage 6 — hook scripts schema correctness
# ──────────────────────────────────────────────────────────────────────

# Stop hook (no in_flight after we ticked BK-001) → empty {}
STOP_OUT=$(echo '{}' | bash "$HOOKS_DIR/stop-backlog-reminder.sh")
echo "$STOP_OUT" | grep -q '^{}'
assert "Stop hook (no in_flight) → {}" $?

# PreCompact → systemMessage
PC_OUT=$(echo '{}' | bash "$HOOKS_DIR/precompact-snapshot.sh")
echo "$PC_OUT" | grep -q '"systemMessage"'
assert "PreCompact → systemMessage" $?

# PostToolUse on non-commit → {}
PT_OUT=$(echo '{"tool_input":{"command":"ls"},"tool_result":{"type":"text"}}' \
    | bash "$HOOKS_DIR/posttooluse-bash-commit.sh")
echo "$PT_OUT" | grep -q '^{}'
assert "PostToolUse (non-commit) → {}" $?

# SessionStart surface — should be silent in our sandbox (no in_flight items now)
SS_OUT=$(bash "$HOOKS_DIR/session-surface-backlog.sh" 2>/dev/null)
# Either {} or a JSON with additionalContext — both valid; just check it parses
echo "$SS_OUT" | python3 -c "import json, sys; json.loads(sys.stdin.read())" 2>/dev/null
assert "SessionStart surface emits valid JSON" $?

# Add a fresh in_flight item, re-run session-surface, expect non-empty additionalContext
python3 "$GW_SCRIPTS/backlog.py" add --title "demo" --probe "p" --verify "v" --section in_flight >/dev/null
SS_OUT=$(bash "$HOOKS_DIR/session-surface-backlog.sh" 2>/dev/null)
echo "$SS_OUT" | grep -q "additionalContext"
assert "SessionStart with in_flight item → additionalContext" $?

# ──────────────────────────────────────────────────────────────────────
# Stage 7 — Python unit suite (the full suite CI's `unittest discover` runs)
# ──────────────────────────────────────────────────────────────────────
if [ -d "$PLUGIN_ROOT/tests" ]; then
    tap "Python unit suite" python3 -m unittest discover -s "$PLUGIN_ROOT/tests" -p "test_*.py"
fi

# ──────────────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────────────
END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))

echo ""
if [ "$FAIL" = "0" ]; then
    printf "%sResult: %d/%d pass%s in %ds%s\n" "$BOLD$GREEN" "$PASS" "$N" "$RESET" "$ELAPSED" ""
else
    printf "%sResult: %d/%d pass, %d FAIL%s in %ds\n" "$BOLD$RED" "$PASS" "$N" "$FAIL" "$RESET" "$ELAPSED"
    echo ""
    echo "${BOLD}Failures:${RESET}"
    for f in "${FAILS[@]}"; do echo "  not ok $f"; done
fi

[ "$KEEP_SANDBOX" = "1" ] && echo "${DIM}sandbox kept: $SANDBOX${RESET}"

[ "$FAIL" = "0" ]
