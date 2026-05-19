#!/usr/bin/env bash
# kaizen pre-commit gate — runs the 8-item checklist.
# Symlinked from ~/.claude/skills/workflow/ into a project's
# .kaizen/hooks/pre-commit via scripts/setup.sh.
#
# Config: .kaizen.toml at repo root (see SKILL.md PART 4).
# Bypass for emergencies: git commit --no-verify (agent must surface,
# not silently bypass).

set -u
# Don't 'set -e' — we want to run every check, then summarise.

# ─── Path resolution (used by multiple checks; hoist to avoid unbound) ─
_SCRIPT_REAL_DIR="$(cd "$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"

# ─── Shared helpers from lib.sh (M3 dedup) ───────────────────────────
. "$_SCRIPT_REAL_DIR/lib.sh"
color_init
PASS="${GREEN}✓${RESET}"
FAIL="${RED}✗${RESET}"
WARN="${YELLOW}!${RESET}"
SKIP="${DIM}∘${RESET}"

# ─── Counters ────────────────────────────────────────────────────────
HARD_FAILS=0
SOFT_WARNS=0
SUGGESTIONS=()

# Counter-aware wrappers (lib.sh's log_* don't count). pass/skip pure aliases.
emit() { printf '%s  %s\n' "$1" "$2" >&2; }
hard_fail() { HARD_FAILS=$((HARD_FAILS + 1)); emit "$FAIL" "$1"; }
warn()      { SOFT_WARNS=$((SOFT_WARNS + 1)); emit "$WARN" "$1"; }
pass()      { emit "$PASS" "$1"; }
skip()      { emit "$SKIP" "$1"; }
suggest()   { SUGGESTIONS+=("$1"); }

# ─── Repo discovery ──────────────────────────────────────────────────
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "kaizen: not a git repo" >&2; exit 0
}
cd "$REPO_ROOT"

CONFIG="$REPO_ROOT/.kaizen.toml"
TOML_PATH="$CONFIG"   # lib.sh's toml_get reads $TOML_PATH

# ─── Config + defaults ───────────────────────────────────────────────
COMPILE_CHECK_CMD=$(toml_get compile_check_cmd "")
ARCH_LOG=$(toml_get architecture_log ".kaizen/workflow/progress.md")
PLAN_DIR=$(toml_get plan_dir "plans")
VERIFY_CMD=$(toml_get verify_cmd "")
ALLOW_DELETE_ENV=$(toml_get allow_deletion_env "KAIZEN_ALLOW_DELETE")
SKIP_TDD_ENV=$(toml_get skip_tdd_check_env "KAIZEN_SKIP_TDD_CHECK")
BRAIN_PATH=$(toml_get brain_path "${KAIZEN_BRAIN_DIR:-$HOME/.claude/.kaizen/brain}")
PROJECT_MEMORY=$(toml_get project_memory_path "")
DELETIONS_LOG=$(toml_get deletions_log ".kaizen/workflow/deletions.jsonl")

# ─── Deletion-log helper ─────────────────────────────────────────────
# Append one JSON line per pre-commit event that allowed deletion(s) through.
# Usage:  log_deletion <mechanism> <files-space-separated> [reason]
# Mechanisms: allowlist | bypass-env | no-belief
log_deletion() {
    local mechanism="$1"
    local files="$2"
    local reason="${3:-}"
    local log_path="$DELETIONS_LOG"
    # Best-effort: skip silently if path is unreachable
    mkdir -p "$(dirname "$log_path")" 2>/dev/null || return 0
    python3 - "$log_path" "$mechanism" "$reason" "$ALLOW_DELETE_ENV" $files <<'PYEOF'
import json, os, sys, datetime, subprocess

log_path = sys.argv[1]
mechanism = sys.argv[2]
reason = sys.argv[3] or None
bypass_env_name = sys.argv[4]
files = sys.argv[5:]

# Capture HEAD sha (pre-commit) — useful for tracing back to the commit
# that came AFTER this row. Post-commit hook could augment with the new sha.
try:
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
    ).strip()
except Exception:
    head = None

# Capture branch
try:
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], stderr=subprocess.DEVNULL, text=True
    ).strip() or None
except Exception:
    branch = None

entry = {
    "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "mechanism": mechanism,
    "files_count": len(files),
    "files": files,
    "bypass_env": bypass_env_name if mechanism == "bypass-env" else None,
    "reason": reason,
    "branch": branch,
    "pre_commit_head": head,
    "post_commit_head": None,  # backfill via post-commit hook (future)
}
with open(log_path, "a", encoding="utf-8") as f:
    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
PYEOF
}

# Heuristic compile-cmd if config is silent.
if [ -z "$COMPILE_CHECK_CMD" ]; then
    if [ -f "Cargo.toml" ]; then
        COMPILE_CHECK_CMD="cargo check --workspace --offline"
    elif [ -f "tsconfig.json" ]; then
        COMPILE_CHECK_CMD="npx --no-install tsc --noEmit"
    elif [ -f "go.mod" ]; then
        COMPILE_CHECK_CMD="go build ./..."
    elif [ -f "pyproject.toml" ] || [ -f "requirements.txt" ] || [ -f "setup.py" ] || [ -f "setup.cfg" ]; then
        # Python: compose ruff (check + format --check) and optional ty (alpha as of 2026-05; opt-in).
        # v1.15.0: prefer ruff over pyright/mypy in detection order; ty (Astral) is appended when on PATH.
        # Empty COMPILE_CHECK_CMD remains the fallback if no Python tooling is installed.
        _py_parts=()
        if command -v ruff >/dev/null 2>&1; then
            _py_parts+=("ruff check .")
            _py_parts+=("ruff format --check .")
        fi
        if command -v ty >/dev/null 2>&1; then
            _py_parts+=("ty check")
        fi
        if [ ${#_py_parts[@]} -eq 0 ]; then
            # Last-resort: byte-compile staged .py files so the gate isn't silently disabled.
            COMPILE_CHECK_CMD="python3 -m compileall -q ."
        else
            COMPILE_CHECK_CMD="${_py_parts[0]}"
            for ((i=1; i<${#_py_parts[@]}; i++)); do
                COMPILE_CHECK_CMD="$COMPILE_CHECK_CMD && ${_py_parts[i]}"
            done
        fi
        unset _py_parts
    fi
fi

# ─── Stage analysis ──────────────────────────────────────────────────
STAGED=$(git diff --cached --name-only --diff-filter=ACMRT 2>/dev/null)
DELETED=$(git diff --cached --name-only --diff-filter=D 2>/dev/null)
RENAMED=$(git diff --cached --name-only --diff-filter=R 2>/dev/null)
DIFF_CONTENT=$(git diff --cached 2>/dev/null)

if [ -z "$STAGED" ] && [ -z "$DELETED" ] && [ -z "$RENAMED" ]; then
    echo "kaizen: nothing staged — skipping gate" >&2
    exit 0
fi

# NOTE on commit-message handling:
# Checks #2 (Conventional Commits) and #4 (plan-file checkbox tick) used
# to read .git/COMMIT_EDITMSG here. That file is stale at pre-commit time
# for `git commit -m "..."` invocations (git only writes the new message
# to it AFTER prepare-commit-msg, which fires AFTER pre-commit). Both
# checks now live in scripts/commit-msg.sh where git passes the message
# file path as $1 — the canonical hook for message validation.

# ─── Structural classifier ───────────────────────────────────────────
is_structural() {
    local file="$1"
    case "$file" in
        # Manifest edits — but skip pure version bumps later via content check
        */Cargo.toml|Cargo.toml|*/package.json|package.json|*/go.mod|go.mod|*/pyproject.toml|pyproject.toml|Gemfile|*/Gemfile)
            return 0 ;;
        # Crate / package roots
        crates/*/src/lib.rs|crates/*/src/main.rs|packages/*/src/index.ts|packages/*/src/index.js|*/__init__.py)
            # Structural only if pub mod / export / __all__ delta
            if echo "$DIFF_CONTENT" | grep -E "^[\+\-][[:space:]]*(pub mod|pub use|export|__all__)" >/dev/null 2>&1; then
                return 0
            fi
            return 1 ;;
        # CLAUDE.md (rulebook) is structural
        CLAUDE.md|*/CLAUDE.md) return 0 ;;
        # Skip-list
        Cargo.lock|package-lock.json|go.sum|TODO.md) return 1 ;;
    esac
    return 1
}

DIFF_IS_STRUCTURAL=0
for f in $STAGED $DELETED $RENAMED; do
    if is_structural "$f"; then
        DIFF_IS_STRUCTURAL=1
        break
    fi
done

# Extra signal: trait/interface move (impl Trait for X relocated between files).
# We approximate: same impl block added in one file AND deleted from another.
if echo "$DIFF_CONTENT" | grep -E "^\+impl[[:space:]]+([[:alnum:]_:<>'/, ]+[[:space:]]+for[[:space:]]+)?[[:alnum:]_]+" >/dev/null 2>&1 \
   && echo "$DIFF_CONTENT" | grep -E "^-impl[[:space:]]+([[:alnum:]_:<>'/, ]+[[:space:]]+for[[:space:]]+)?[[:alnum:]_]+" >/dev/null 2>&1; then
    DIFF_IS_STRUCTURAL=1
fi

# ─── Check 1: Compile barrier (cached by staged-content sha) ─────────
if [ -n "$COMPILE_CHECK_CMD" ]; then
    # Cache key = compile cmd + sha of staged content. Same staged
    # blob set + same cmd → re-use last green verdict. Failed runs
    # are NOT cached (stale failure is worse than re-running).
    STAGED_SHA=$(git diff --cached 2>/dev/null | python3 -c "import sys,hashlib; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest()[:16])" 2>/dev/null || echo "no-stage")
    CACHE_PY="$_SCRIPT_REAL_DIR/cache.py"
    CACHE_KEY=""
    if [ -x "$CACHE_PY" ]; then
        CACHE_KEY=$(python3 "$CACHE_PY" key "compile-barrier" "$COMPILE_CHECK_CMD" "$STAGED_SHA" 2>/dev/null || echo "")
    fi
    CACHED_PASS=0
    if [ -n "$CACHE_KEY" ]; then
        if python3 "$CACHE_PY" get "$CACHE_KEY" 2>/dev/null | grep -q '"status": "pass"'; then
            CACHED_PASS=1
        fi
    fi
    if [ "$CACHED_PASS" = "1" ]; then
        pass "compile barrier (cached): $COMPILE_CHECK_CMD"
    elif bash -c "$COMPILE_CHECK_CMD" >/tmp/kaizen-compile.log 2>&1; then
        pass "compile barrier: $COMPILE_CHECK_CMD"
        if [ -n "$CACHE_KEY" ]; then
            python3 "$CACHE_PY" put "$CACHE_KEY" '{"status":"pass","cmd":"'"$(echo "$COMPILE_CHECK_CMD" | sed 's/"/\\"/g')"'"}' 2>/dev/null || true
        fi
    else
        hard_fail "compile barrier failed: $COMPILE_CHECK_CMD"
        echo "${DIM}        → /tmp/kaizen-compile.log (last lines):${RESET}" >&2
        tail -10 /tmp/kaizen-compile.log | sed 's/^/        /' >&2
    fi
else
    skip "compile barrier: no command resolved (set compile_check_cmd in .kaizen.toml)"
fi

# ─── Check 2: Conventional Commits prefix ────────────────────────────
# Moved to scripts/commit-msg.sh — see NOTE above. Pre-commit cannot
# reliably read the staged message for `git commit -m` invocations.

# ─── Check 3: Structural change → architecture log row ───────────────
if [ "$DIFF_IS_STRUCTURAL" = "1" ]; then
    if echo "$STAGED" | grep -qF "$ARCH_LOG"; then
        pass "structural change includes $ARCH_LOG row"
    else
        hard_fail "structural change WITHOUT $ARCH_LOG row update"
        echo "${DIM}        → append a row: | YYYY-MM-DD | <scope> | <ΔLOC> | <summary> |${RESET}" >&2
        suggest "Run: skill load onion-ddd-workflow (structural change touched layer boundary?)"
    fi
else
    skip "structural classifier: not structural"
fi

# ─── Check 4: Plan-file mention → checkbox tick ──────────────────────
# Moved to scripts/commit-msg.sh — see NOTE above. Pre-commit cannot
# reliably read the staged message for `git commit -m` invocations.

# ─── Check 5: Pre-deletion gate ──────────────────────────────────────
if [ -n "$DELETED" ]; then
    OVERRIDE_VAL=${!ALLOW_DELETE_ENV:-}

    # Brain-rule allowlist: if EVERY staged deletion matches a
    # deletion-allow rule, skip the belief scan entirely.
    _SCRIPT_REAL_DIR="$(cd "$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"
    RULES_PY="$_SCRIPT_REAL_DIR/rules.py"
    ALL_ALLOWED=1
    ALLOWLIST_HITS=""
    if [ -x "$RULES_PY" ]; then
        for d in $DELETED; do
            if hit=$(python3 "$RULES_PY" deletion-allowed "$d" 2>/dev/null) && echo "$hit" | grep -q "^yes"; then
                ALLOWLIST_HITS="$ALLOWLIST_HITS  $d → $hit\n"
            else
                ALL_ALLOWED=0
                break
            fi
        done
    else
        ALL_ALLOWED=0
    fi

    if [ "$ALL_ALLOWED" = "1" ] && [ -n "$DELETED" ]; then
        pass "pre-deletion: all $(echo $DELETED | wc -w) deletion(s) allowlisted via brain rules"
        printf "%b" "${DIM}$ALLOWLIST_HITS${RESET}" >&2
        log_deletion "allowlist" "$DELETED" "brain-rules deletion-allowed"
    elif [ "$OVERRIDE_VAL" = "1" ]; then
        # Auto-backup before allowing the deletion through (reversibility net).
        _SCRIPT_REAL_DIR="$(cd "$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"
        BACKUP_SH="$_SCRIPT_REAL_DIR/backup.sh"
        if [ -x "$BACKUP_SH" ]; then
            bash "$BACKUP_SH" create --label "pre-delete-$(date -u +%Y%m%dT%H%M%SZ)" >&2 || true
        fi
        warn "deletion(s) detected — $ALLOW_DELETE_ENV=1 set, auto-backup taken before allowing"
        for d in $DELETED; do warn "  deleted: $d"; done
        log_deletion "bypass-env" "$DELETED" "user-authorized via $ALLOW_DELETE_ENV=1"
    else
        # Scan brain Top Beliefs + project memory for deletion-prevention rules
        BELIEF_HIT=""
        if [ -f "$BRAIN_PATH/Notes/pref-no-deletions.md" ]; then
            BELIEF_HIT="$BRAIN_PATH/Notes/pref-no-deletions.md"
        fi
        if [ -n "$PROJECT_MEMORY" ] && [ -d "$PROJECT_MEMORY" ]; then
            PROJECT_HIT=$(find "$PROJECT_MEMORY" -name "feedback_*delet*.md" -o -name "feedback_*no_delete*.md" 2>/dev/null | head -1)
            [ -n "$PROJECT_HIT" ] && BELIEF_HIT="$BELIEF_HIT $PROJECT_HIT"
        fi
        if [ -n "$BELIEF_HIT" ]; then
            hard_fail "deletion staged + matching deletion-prevention belief(s) found:"
            for b in $BELIEF_HIT; do echo "${DIM}        → $b${RESET}" >&2; done
            echo "${DIM}        Override: $ALLOW_DELETE_ENV=1 git commit ...${RESET}" >&2
            # NOTE: hard_fail exits — log_deletion not reached here intentionally
            #       (we only log ALLOWED deletions, not blocked ones)
        else
            warn "deletion(s) detected — no matching belief, allowing"
            log_deletion "no-belief" "$DELETED" "no matching deletion-prevention belief"
        fi
    fi
else
    skip "pre-deletion: no deletions staged"
fi

# ─── Check 6: No sha / date / LOC count in CLAUDE.md ─────────────────
# Canonical definition: iron-laws.yaml::claude-md-no-volatile-data. This
# pure-bash form is the portable, dependency-free implementation that
# runs in consumer repos; Check 7.5 runs the iron-laws checker form in
# the kaizen-md repo. Keep the two in sync — the iron law is the spec.
if echo "$STAGED" | grep -qE "(^|/)CLAUDE\.md$"; then
    CLAUDE_DIFF=$(git diff --cached -- '*CLAUDE.md' 2>/dev/null | grep -E "^\+" | grep -v "^+++")
    SHA_PATTERN='[0-9a-f]{7,40}'
    LOC_PATTERN='[0-9]+ (passed|failed|LOC|tests)'
    if echo "$CLAUDE_DIFF" | grep -qE "$SHA_PATTERN"; then
        # Allow shas inside code-fences / inline-code (heuristic: line starts with ` or contains 4+ backticks)
        BAD=$(echo "$CLAUDE_DIFF" | grep -E "$SHA_PATTERN" | grep -vE '^\+[[:space:]]*`|^\+[[:space:]]*```')
        if [ -n "$BAD" ]; then
            hard_fail "CLAUDE.md edit contains commit sha (rulebook must not carry shas — use progress.md instead)"
            echo "$BAD" | head -3 | sed 's/^/        /' >&2
        fi
    fi
    if echo "$CLAUDE_DIFF" | grep -qE "$LOC_PATTERN"; then
        BAD=$(echo "$CLAUDE_DIFF" | grep -E "$LOC_PATTERN" | grep -vE '^\+[[:space:]]*`')
        if [ -n "$BAD" ]; then
            warn "CLAUDE.md edit contains LOC/test count (volatile — use progress.md instead)"
            echo "$BAD" | head -3 | sed 's/^/        /' >&2
        fi
    fi
    pass "CLAUDE.md no-sha / no-LOC scan"
else
    skip "CLAUDE.md scan: no CLAUDE.md staged"
fi

# ─── Check 7: New code → paired test (SOFT by default) ───────────────
# Canonical definition: iron-laws.yaml::paired-tests. This bash form is
# the portable, language-general implementation (.rs/.ts/.go/.py) that
# runs in consumer repos; the iron-laws checker form (Check 7.5, kaizen-md
# repo only) is kaizen-plugin-Python-scoped. The iron law is the spec.
# Brain-rule severity override: check-severity rule with check_id=paired-test.
SKIP_TDD_VAL=${!SKIP_TDD_ENV:-}
PAIRED_TEST_SEV="default"
if [ -x "$_SCRIPT_REAL_DIR/rules.py" ]; then
    PAIRED_TEST_SEV=$(python3 "$_SCRIPT_REAL_DIR/rules.py" severity paired-test 2>/dev/null || echo default)
fi
if [ "$PAIRED_TEST_SEV" = "skip" ]; then
    skip "TDD-paired-test check (skipped by brain rule)"
elif [ "$SKIP_TDD_VAL" != "1" ]; then
    NEW_FILES=$(git diff --cached --name-only --diff-filter=A 2>/dev/null)
    for f in $NEW_FILES; do
        case "$f" in
            tests/*|*/tests/*|*_test.go|*.test.ts|*.test.tsx|*.spec.ts|test_*.py|*/test_*.py|*_test.py) continue ;;
            *.rs|*.ts|*.tsx|*.js|*.go|*.py)
                # Skip files that are themselves tests-only (cfg(test) etc.)
                if git show ":$f" 2>/dev/null | grep -qE "^#\[cfg\(test\)\]|^describe\(|^test\(|^def test_"; then
                    continue
                fi
                # Look for a paired test
                base=$(basename "$f" | sed -E 's/\.(rs|ts|tsx|js|go|py)$//')
                dir=$(dirname "$f")
                if find "$dir" "$dir/../tests" "tests" -name "${base}_test.*" -o -name "${base}.test.*" -o -name "test_${base}.*" 2>/dev/null | grep -q .; then
                    continue
                fi
                if git show ":$f" 2>/dev/null | grep -qE "#\[cfg\(test\)\][[:space:]]*mod tests"; then
                    continue
                fi
                warn "new file $f has no paired test (load skill: tdd — set $SKIP_TDD_ENV=1 to silence)"
                ;;
        esac
    done
else
    skip "TDD-paired-test check ($SKIP_TDD_ENV=1)"
fi

# ─── Check 7.5: iron-laws checker (kaizen-md plugin repo only) ───────
# The iron-laws registry (skills/iron-laws/domain/iron-laws.yaml) is the
# single source of truth for the kaizen-plugin iron laws; _iron_laws.py
# is its checker. Run it over the staged diff when committing IN the
# kaizen-md repo. Consumer repos have no plugins/kaizen/ tree — the
# checker is a no-op there, so we skip the subprocess entirely.
IRON_LAWS_CLI="$_SCRIPT_REAL_DIR/iron_laws.py"
if [ -f "$REPO_ROOT/plugins/kaizen/skills/iron-laws/domain/iron-laws.yaml" ] \
   && [ -f "$IRON_LAWS_CLI" ]; then
    IRON_OUT=$(python3 "$IRON_LAWS_CLI" check --staged 2>&1)
    IRON_RC=$?
    IRON_HARD=$(echo "$IRON_OUT" | grep -cE '^hard ' || true)
    IRON_SOFT=$(echo "$IRON_OUT" | grep -cE '^soft ' || true)
    if [ "$IRON_RC" -ne 0 ] && [ "$IRON_HARD" -gt 0 ]; then
        hard_fail "iron-laws: $IRON_HARD hard finding(s) in staged diff"
        echo "$IRON_OUT" | grep -E '^hard ' | head -5 | sed 's/^/        /' >&2
    elif [ "$IRON_SOFT" -gt 0 ]; then
        warn "iron-laws: $IRON_SOFT soft finding(s) in staged diff"
        echo "$IRON_OUT" | grep -E '^soft ' | head -3 | sed 's/^/        /' >&2
    else
        pass "iron-laws checker (no staged violations)"
    fi
else
    skip "iron-laws checker: not the kaizen-md plugin repo"
fi

# ─── Check 7.6: gatekeeper pre-flight (non-blocking, ~300ms) ─────────
# The gatekeeper aggregates iron-laws + efficient-tool-use anti-pattern
# scanner + karpathy diff scanners + plugin-validator into one verdict.
# Check 7.5 above already runs the iron-laws checker — this check adds
# the other three Python sub-gates in one shot.
#
# NON-BLOCKING by design: pre-commit's role is to refuse bad commits;
# the gatekeeper surfaces broader signal (smells, warnings) without
# stopping the commit. Yellow/red surfaces as a `warn` line.
#
# Disabled with KAIZEN_GATEKEEPER_DISABLE=1 (hook-bypass-knob iron-law).
GATEKEEPER_PY="$_SCRIPT_REAL_DIR/gatekeeper.py"
if [ -z "${KAIZEN_GATEKEEPER_DISABLE:-}" ] \
   && [ -f "$REPO_ROOT/plugins/kaizen/skills/iron-laws/domain/iron-laws.yaml" ] \
   && [ -f "$GATEKEEPER_PY" ] \
   && command -v python3 >/dev/null 2>&1; then
    GK_OUT=$(python3 "$GATEKEEPER_PY" check --staged --json 2>/dev/null)
    if [ -n "$GK_OUT" ]; then
        GK_VERDICT=$(echo "$GK_OUT" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('overall','unknown'))" 2>/dev/null)
        case "$GK_VERDICT" in
            green)
                pass "gatekeeper pre-flight (green: all sub-gates clean)" ;;
            yellow)
                GK_WARN=$(echo "$GK_OUT" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('counts',{}).get('warn',0))" 2>/dev/null)
                warn "gatekeeper pre-flight (yellow: $GK_WARN warn finding(s) — see kaizen-gatekeeper check --staged)"
                ;;
            red)
                GK_ERR=$(echo "$GK_OUT" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('counts',{}).get('error',0))" 2>/dev/null)
                # NON-BLOCKING: surface as warn, never fail. Check 7.5
                # already catches the iron-law hard failures.
                warn "gatekeeper pre-flight (red: $GK_ERR error finding(s) outside iron-laws — see kaizen-gatekeeper check --staged)"
                ;;
            *)
                skip "gatekeeper pre-flight: unparseable verdict" ;;
        esac
    else
        skip "gatekeeper pre-flight: gatekeeper.py produced no output"
    fi
else
    skip "gatekeeper pre-flight: not in kaizen-md repo OR disabled"
fi

# ─── Check 8.5: Backlog drift (.md regenerated from .json) ───────────
BACKLOG_PATH=$(toml_get backlog_path "")
if [ -n "$BACKLOG_PATH" ] && [ -f "$REPO_ROOT/$BACKLOG_PATH" ]; then
    # Resolve sibling backlog.py via this script's real path (works whether
    # installed at ~/.claude/skills/workflow/scripts/ OR as a plugin
    # under ~/.claude/local-marketplaces/.../plugins/.../scripts/).
    _SCRIPT_REAL_DIR="$(cd "$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"
    BACKLOG_PY="$_SCRIPT_REAL_DIR/backlog.py"
    if [ -x "$BACKLOG_PY" ] && command -v python3 >/dev/null 2>&1; then
        if python3 "$BACKLOG_PY" verify >/tmp/kaizen-backlog.log 2>&1; then
            pass "backlog: .md matches .json (no drift)"
        else
            hard_fail "backlog: .md drifted from .json"
            tail -3 /tmp/kaizen-backlog.log | sed 's/^/        /' >&2
            echo "${DIM}        → Fix: python3 $BACKLOG_PY render${RESET}" >&2
        fi
    else
        skip "backlog drift: backlog.py not found or python3 missing"
    fi
else
    skip "backlog: no backlog_path configured"
fi

# ─── Check 9: Committed-secret detection (HARD) ──────────────────────
# Regex scan over the staged diff for high-confidence secret patterns.
# Bypass via KAIZEN_ALLOW_SECRET=1 (e.g. an example/fixture file).
SECRET_OVERRIDE=${KAIZEN_ALLOW_SECRET:-}
# Single-pass scan: PCRE with `(?!^\+\+\+)` lookahead would be cleaner,
# but POSIX BRE/ERE has no lookaround. We collapse the prior 3-grep chain
# into a single ERE with an "anchored-but-not-+++" pattern via negation
# of the file-header marker. The leading `+` distinguishes added lines
# from the diff body; `+++` is the file header (not staged content).
SECRET_HITS=$(echo "$DIFF_CONTENT" | grep -chE \
    "^\+([^+].*)?((AKIA|ASIA)[0-9A-Z]{16}|-----BEGIN[ A-Z]+PRIVATE KEY-----|gh[oprsu]_[A-Za-z0-9_]{36,}|sk-[A-Za-z0-9]{32,}|xox[abprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,})" 2>/dev/null)
if [ -n "$SECRET_HITS" ] && [ "$SECRET_HITS" != "0" ]; then
    if [ "$SECRET_OVERRIDE" = "1" ]; then
        warn "secret-pattern match(es) but KAIZEN_ALLOW_SECRET=1 — gate bypassed"
    else
        hard_fail "committed-secret patterns detected in staged diff ($SECRET_HITS line(s))"
        echo "${DIM}        → patterns: AWS keys, private keys, GitHub tokens, OpenAI/Slack/Google API keys, JWTs${RESET}" >&2
        echo "${DIM}        → bypass for fixtures: KAIZEN_ALLOW_SECRET=1 git commit ...${RESET}" >&2
    fi
else
    pass "secret-pattern scan (no high-confidence hits)"
fi

# ─── Check 8: Project-specific verify ────────────────────────────────
if [ -n "$VERIFY_CMD" ]; then
    if bash -c "$VERIFY_CMD" >/tmp/kaizen-verify.log 2>&1; then
        pass "project verify: $VERIFY_CMD"
    else
        hard_fail "project verify failed: $VERIFY_CMD"
        tail -10 /tmp/kaizen-verify.log | sed 's/^/        /' >&2
    fi
else
    skip "project verify: no verify_cmd in .kaizen.toml"
fi

# ─── Check 11: Custom-pattern rules from brain ───────────────────────
if [ -x "$_SCRIPT_REAL_DIR/rules.py" ]; then
    CUSTOM_HITS=$(python3 - "$_SCRIPT_REAL_DIR/rules.py" "$DIFF_CONTENT" <<'PY' 2>/dev/null
import json, re, subprocess, sys
rules_py, diff = sys.argv[1], sys.argv[2]
patterns = json.loads(subprocess.check_output(["python3", rules_py, "custom-patterns"]).decode() or "[]")
fail = 0
for p in patterns:
    pat = p.get("pattern_regex", "")
    if not pat:
        continue
    try:
        if re.search(pat, diff, re.MULTILINE):
            action = p.get("pattern_action", "warn")
            msg = p.get("pattern_message", f"pattern matched: {pat}")
            print(f"{action}|{p['name']}|{msg}")
            if action == "block":
                fail = 1
    except re.error:
        continue
sys.exit(fail)
PY
)
    EXIT_CODE=$?
    if [ -n "$CUSTOM_HITS" ]; then
        while IFS='|' read -r action name msg; do
            if [ "$action" = "block" ]; then
                hard_fail "custom-pattern brain rule: $name — $msg"
            else
                warn "custom-pattern brain rule: $name — $msg"
            fi
        done <<< "$CUSTOM_HITS"
    else
        pass "custom-pattern brain rules (no hits)"
    fi
fi

# ─── Skill-weaving suggestions ───────────────────────────────────────
# Active workflow-routing routine? Surface the active stage so the
# committer knows whether to advance via /workflow or commit ad-hoc.
# v1.30.0+: workflow dir resolved via the _paths.sh SSOT helper (handles
# the .kaizen/workflow/ canonical → .workflow/ legacy fallback once, in one place).
if ! command -v kaizen_resolve_workflow_dir >/dev/null 2>&1; then
    # pre-commit.sh runs under git's CWD; source _paths.sh if not already loaded.
    # _paths.sh still lives at skills/workflow/scripts/ (deferred — see
    # DOMAIN-shells audit). Reach back from scripts/git-hooks/.
    _PC_REAL_DIR="$(cd "$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"
    source "$_PC_REAL_DIR/../../skills/workflow/scripts/_paths.sh"
fi
WORKFLOW_STATE_FILE="$(kaizen_resolve_workflow_dir)/state.json"
# Re-resolve relative to repo root if helper returned absolute path.
WORKFLOW_STATE_FILE="${WORKFLOW_STATE_FILE#$(git rev-parse --show-toplevel 2>/dev/null)/}"
if [ -f "$WORKFLOW_STATE_FILE" ] && command -v python3 >/dev/null 2>&1; then
    ACTIVE_STAGE=$(python3 -c "
import json, sys
try:
    s = json.load(open('$WORKFLOW_STATE_FILE'))
    cur = s.get('current', 0)
    stages = s.get('stages', [])
    if cur < len(stages):
        print(f\"{s.get('routine','?')} :: {stages[cur]} (stage {cur+1}/{len(stages)})\")
except Exception:
    pass
" 2>/dev/null)
    if [ -n "$ACTIVE_STAGE" ]; then
        suggest "Active workflow-routing routine: $ACTIVE_STAGE — advance via /workflow or surface deviation"
    fi
fi

# ─── Coding-skills suggestions (8 principles + TDD) ──────────────────
# Each trigger is heuristic on the staged diff. Fast, false-positive-tolerant:
# suggestions are advisory only, never block. Pair with the matching
# `coding-skills:<name>` skill to drive the fix.
#
# Active in this commit's staged diff. `+` line counts = added; we ignore
# context lines. Tests excluded from KISS/SOLID/DRY by convention.

ADDED_LINES=$(printf '%s' "$DIFF_CONTENT" | grep -c '^+[^+]' 2>/dev/null || echo 0)

# 1. onion-ddd-workflow — Cargo.toml / package.json / go.mod dep added/removed
if echo "$STAGED" | grep -qE "(^|/)(Cargo|package)\.toml$|(^|/)go\.mod$"; then
    if echo "$DIFF_CONTENT" | grep -E "^[\+\-][[:space:]]*[a-z][a-z0-9_-]*[[:space:]]*=[[:space:]]*" >/dev/null 2>&1; then
        suggest "Dep change → skill: onion-ddd-workflow (check dep direction, structural-lint authoring)"
    fi
fi

# 2. coding-skills:kiss + separation-of-concerns — large single-file diff
LARGE_FILE_DIFF=$(git diff --cached --numstat 2>/dev/null | awk '$1+$2 > 100 && $3 !~ /^tests\// {print $3 " (+" $1 " -" $2 ")"}')
if [ -n "$LARGE_FILE_DIFF" ]; then
    suggest "Large single-file diff → skill: coding-skills:kiss + coding-skills:separation-of-concerns"
    echo "$LARGE_FILE_DIFF" | while read l; do suggest "  $l"; done
fi

# 3. coding-skills:dry — same literal string >40 chars appearing 2+ times across staged additions
DUP_LITS=$(printf '%s' "$DIFF_CONTENT" \
    | grep -E '^\+[^+]' \
    | grep -oE '"[^"]{40,}"' 2>/dev/null \
    | sort | uniq -c | awk '$1 >= 2 {print $1 "× " substr($0, length($1)+3, 60) "..."}' | head -3)
if [ -n "$DUP_LITS" ]; then
    suggest "Repeated string literals in staged adds → skill: coding-skills:dry"
    echo "$DUP_LITS" | while read l; do suggest "  $l"; done
fi

# 4. coding-skills:solid — new trait + many methods (heuristic: 8+ pub fn in one staged file's adds)
HIGH_FN_FILES=$(git diff --cached --numstat 2>/dev/null | awk '$3 !~ /^tests\// {print $3}' \
    | while read f; do
        [ -z "$f" ] && continue
        n=$(git diff --cached -- "$f" 2>/dev/null | grep -cE '^\+[[:space:]]*pub[[:space:]]+(async[[:space:]]+)?fn[[:space:]]+' 2>/dev/null)
        n=${n:-0}
        [ "$n" -ge 8 ] 2>/dev/null && echo "$f (+$n pub fn)"
    done)
if [ -n "$HIGH_FN_FILES" ]; then
    suggest "File adds 8+ pub fn → skill: coding-skills:solid (interface segregation, single-responsibility)"
    echo "$HIGH_FN_FILES" | while read l; do suggest "  $l"; done
fi

# Helper: grep -c always prints a number (0 when no matches) — DON'T chain
# `|| echo 0` (that would append a second "0" on grep's exit-1, yielding
# "0\n0" which breaks `[ N -ge M ]` integer tests).

# 5. coding-skills:law-of-demeter — long chains `.a().b().c().d()` in additions
LONG_CHAINS=$(printf '%s' "$DIFF_CONTENT" | grep -E '^\+[^+]' \
    | grep -cE '\.[a-zA-Z_][a-zA-Z0-9_]*\([^)]*\)\.[a-zA-Z_][a-zA-Z0-9_]*\([^)]*\)\.[a-zA-Z_][a-zA-Z0-9_]*\([^)]*\)\.[a-zA-Z_][a-zA-Z0-9_]*\(' 2>/dev/null)
LONG_CHAINS=${LONG_CHAINS:-0}
if [ "$LONG_CHAINS" -ge 2 ] 2>/dev/null; then
    suggest "$LONG_CHAINS+ long method chains in additions → skill: coding-skills:law-of-demeter"
fi

# 6. coding-skills:yagni — new #[cfg(feature = "...")] gate OR new trait with no impl in same diff
NEW_FEATURE_FLAGS=$(printf '%s' "$DIFF_CONTENT" | grep -cE '^\+[[:space:]]*#\[cfg\(feature' 2>/dev/null)
NEW_FEATURE_FLAGS=${NEW_FEATURE_FLAGS:-0}
NEW_TRAITS=$(printf '%s' "$DIFF_CONTENT" | grep -cE '^\+[[:space:]]*pub[[:space:]]+(unsafe[[:space:]]+)?trait[[:space:]]+' 2>/dev/null)
NEW_TRAITS=${NEW_TRAITS:-0}
NEW_IMPLS_FOR=$(printf '%s' "$DIFF_CONTENT" | grep -cE '^\+[[:space:]]*impl[[:space:]]+[A-Z][[:alnum:]_]*[[:space:]]+for[[:space:]]' 2>/dev/null)
NEW_IMPLS_FOR=${NEW_IMPLS_FOR:-0}
if { [ "$NEW_FEATURE_FLAGS" -ge 1 ] 2>/dev/null; } || { [ "$NEW_TRAITS" -ge 1 ] 2>/dev/null && [ "$NEW_IMPLS_FOR" -eq 0 ] 2>/dev/null; }; then
    suggest "New feature-flag(s) or zero-impl trait → skill: coding-skills:yagni (justify the abstraction; 2+ consumers or named driver)"
fi

# 7. coding-skills:boy-scout-rule — TODO/FIXME/HACK/XXX in or adjacent to staged changes
TODOS_NEAR=$(git diff --cached -U10 2>/dev/null | grep -cE '\b(TODO|FIXME|HACK|XXX)\b' 2>/dev/null)
TODOS_NEAR=${TODOS_NEAR:-0}
if [ "$TODOS_NEAR" -ge 1 ] 2>/dev/null; then
    suggest "$TODOS_NEAR× TODO/FIXME/HACK/XXX near staged changes → skill: coding-skills:boy-scout-rule (consider improving in flight)"
fi

# 8. coding-skills:convention-over-configuration — new file diverges from sibling extension/case
NEW_FILES=$(git diff --cached --name-status 2>/dev/null | awk '$1 == "A" {print $2}')
if [ -n "$NEW_FILES" ]; then
    CONVENTION_FLAGS=""
    for new in $NEW_FILES; do
        dir=$(dirname "$new")
        base=$(basename "$new")
        ext="${base##*.}"
        [ "$ext" = "$base" ] && continue
        # Most common ext among siblings
        common_ext=$(ls "$dir" 2>/dev/null | grep -E '\.[^./]+$' | sed 's/.*\.//' | sort | uniq -c | sort -rn | head -1 | awk '{print $2}')
        if [ -n "$common_ext" ] && [ "$ext" != "$common_ext" ] && [ "$ext" != "md" ]; then
            CONVENTION_FLAGS="${CONVENTION_FLAGS}  $new (.$ext vs sibling .$common_ext)\n"
        fi
    done
    if [ -n "$CONVENTION_FLAGS" ]; then
        suggest "New file extension diverges from siblings → skill: coding-skills:convention-over-configuration"
        printf "$CONVENTION_FLAGS" | while read l; do [ -n "$l" ] && suggest "$l"; done
    fi
fi

# 9. tdd / test-driven-development — net-new non-test source file added
#    (Check #7 already catches missing paired tests as a warn; this is a positive nudge for new code.)
NEW_NON_TEST=$(echo "$NEW_FILES" | grep -vE '(^|/)(test_|tests/|_test\.|\.test\.|\.spec\.)' | grep -vE '\.(md|toml|json|lock|yml|yaml|sh)$' | head -5)
if [ -n "$NEW_NON_TEST" ]; then
    suggest "Net-new source file(s) added → skill: tdd (or coding-skills equivalent) — net-new code lands test-first"
    echo "$NEW_NON_TEST" | while read l; do [ -n "$l" ] && suggest "  $l"; done
fi

# Meta: if ANY of the above fired AND diff is structural, also suggest the workflow umbrella
if [ "${#SUGGESTIONS[@]}" -ge 3 ] && [ "$DIFF_IS_STRUCTURAL" = "1" ]; then
    suggest "Structural diff with multiple coding-skills triggers → review with onion-ddd-workflow checklist before committing"
fi

# ─── Check 13: Stack-context auto-regen on manifest deltas ──────────
# When a stack manifest (Cargo.toml / package.json / go.mod / pyproject.toml
# / rust-toolchain / .nvmrc / etc.) is staged, .agents/stack-context.{json,md}
# is a DERIVED artifact and should track the change. Auto-regen + auto-stage
# so the next session's SessionStart hook injects fresh stack context.
#
# Bypass: KAIZEN_DETECT_STACK_PRECOMMIT_DISABLE=1 (silent skip).
# The detect_stack.py script is also auto-disabled if KAIZEN_DETECT_STACK_DISABLE=1.
if [ -z "${KAIZEN_DETECT_STACK_PRECOMMIT_DISABLE:-}" ] \
   && [ -z "${KAIZEN_DETECT_STACK_DISABLE:-}" ]; then
    _MANIFEST_PATTERN='(^|/)(Cargo\.toml|package\.json|go\.mod|pyproject\.toml|requirements\.txt|Gemfile|Package\.swift|mix\.exs|build\.gradle(\.kts)?|pom\.xml|composer\.json|CMakeLists\.txt|rust-toolchain(\.toml)?|\.python-version|\.nvmrc|\.ruby-version|\.tool-versions|mise\.toml|Dockerfile|docker-compose\.ya?ml|pnpm-workspace\.yaml|lerna\.json|nx\.json|turbo\.json|\.pre-commit-config\.yaml)$'
    MANIFEST_HITS=$(echo "$STAGED" | grep -E "$_MANIFEST_PATTERN" || true)
    if [ -n "$MANIFEST_HITS" ]; then
        # detect_stack.py still lives at skills/workflow/scripts/ (DOMAIN-24 util cluster).
        DETECT_PY="$_SCRIPT_REAL_DIR/../../skills/workflow/scripts/detect_stack.py"
        if [ -f "$DETECT_PY" ]; then
            if python3 "$DETECT_PY" scan --force >/tmp/kaizen-stack-ctx.log 2>&1; then
                STACK_JSON="$REPO_ROOT/.agents/stack-context.json"
                STACK_MD="$REPO_ROOT/.agents/stack-context.md"
                STAGED_NEW=""
                for f in "$STACK_JSON" "$STACK_MD"; do
                    [ -f "$f" ] || continue
                    rel="${f#$REPO_ROOT/}"
                    if ! git diff --cached --quiet -- "$rel" 2>/dev/null \
                       || ! git diff --quiet -- "$rel" 2>/dev/null; then
                        git add -- "$rel" 2>/dev/null && STAGED_NEW="$STAGED_NEW $rel"
                    fi
                done
                if [ -n "$STAGED_NEW" ]; then
                    pass "stack-context regenerated + staged after manifest delta:$STAGED_NEW"
                else
                    pass "stack-context: manifest staged but artifact unchanged (no regen needed)"
                fi
            else
                warn "stack-context auto-regen failed — see /tmp/kaizen-stack-ctx.log"
            fi
        else
            skip "stack-context auto-regen: detect_stack.py not found"
        fi
    else
        skip "stack-context: no manifest in staged diff"
    fi
fi

# ─── Check 12: Context-window awareness (advisory) ───────────────────
# Only fires when CLAUDE_CONTEXT_TOKENS env is set by the harness.
# Without it, context state is unknown and the check is a no-op.
if [ -x "$_SCRIPT_REAL_DIR/context.py" ]; then
    CTX_ZONE=$(python3 "$_SCRIPT_REAL_DIR/context.py" zone 2>/dev/null || echo "unknown")
    case "$CTX_ZONE" in
        red)
            warn "context window in red zone (>=80%) — consider /compact after this commit; state could compact mid-task"
            ;;
        yellow)
            [ "${KAIZEN_VERBOSE:-0}" = "1" ] && warn "context window in yellow zone (60-79%)"
            ;;
        *)
            ;;
    esac
fi

# ─── Check 14: Affected-tests subset (HARD on failure) ──────────────
# Default-on per user choice; disable with KAIZEN_PRECOMMIT_TESTS=0.
# Direct map (scripts/foo.py → tests/test_foo.py); private helper or
# unmappable Python file → full suite. No `.py` staged → skip cleanly.
# Only fires inside the kaizen-md plugin repo (where the runner +
# helper actually live).
AFFECTED_PY="$_SCRIPT_REAL_DIR/_affected_tests.py"
RUNNER_PY="$_SCRIPT_REAL_DIR/run_tests_parallel.py"
KAIZEN_DIR="$REPO_ROOT/plugins/kaizen"
if [ "${KAIZEN_PRECOMMIT_TESTS:-1}" = "0" ]; then
    skip "affected-tests (KAIZEN_PRECOMMIT_TESTS=0)"
elif [ -z "${KAIZEN_CI_GATE_RECURSION:-}" ] \
   && [ -f "$AFFECTED_PY" ] \
   && [ -f "$RUNNER_PY" ] \
   && [ -d "$KAIZEN_DIR/tests" ] \
   && command -v python3 >/dev/null 2>&1; then
    # Derive subset from staged file list (one path per line on stdin).
    AT_OUT=$(echo "$STAGED" | KAIZEN_AFFECTED_PLUGIN_ROOT="$KAIZEN_DIR" \
                python3 "$AFFECTED_PY" 2>/tmp/kaizen-at.err)
    AT_REASON=$(cat /tmp/kaizen-at.err 2>/dev/null | sed 's/^\[_affected_tests\] //')
    if [ -z "$AT_OUT" ]; then
        skip "affected-tests: $AT_REASON"
    elif [ "$AT_OUT" = "FULL" ]; then
        # Full suite — opt-out path; long-running. Surface as warn (not
        # hard-fail target unless tests actually fail).
        if KAIZEN_CI_GATE_RECURSION=1 python3 "$RUNNER_PY" \
                --root "$KAIZEN_DIR" --tests-dir tests \
                >/tmp/kaizen-tests.log 2>&1; then
            pass "affected-tests (FULL: $AT_REASON)"
        else
            hard_fail "affected-tests FAILED (FULL suite; $AT_REASON) — see /tmp/kaizen-tests.log"
        fi
    else
        # Direct-map subset — fast path.
        if KAIZEN_CI_GATE_RECURSION=1 python3 "$RUNNER_PY" \
                --root "$KAIZEN_DIR" --tests-dir tests \
                --modules "$AT_OUT" >/tmp/kaizen-tests.log 2>&1; then
            pass "affected-tests ($AT_REASON)"
        else
            hard_fail "affected-tests FAILED ($AT_REASON) — see /tmp/kaizen-tests.log"
        fi
    fi
else
    skip "affected-tests: not in kaizen-md plugin repo OR recursion guard active"
fi

# ─── Final summary ───────────────────────────────────────────────────
echo "" >&2
if [ "$HARD_FAILS" -gt 0 ]; then
    echo "${BOLD}${RED}kaizen: $HARD_FAILS hard fail(s), $SOFT_WARNS warning(s)${RESET}" >&2
    if [ "${#SUGGESTIONS[@]}" -gt 0 ]; then
        echo "${BOLD}Suggested skills:${RESET}" >&2
        printf '  %s\n' "${SUGGESTIONS[@]}" >&2
    fi
    echo "${DIM}Bypass: git commit --no-verify (last resort — surface, don't silently skip)${RESET}" >&2
    exit 1
fi

if [ "$SOFT_WARNS" -gt 0 ]; then
    echo "${BOLD}${YELLOW}kaizen: 0 hard fails, $SOFT_WARNS warning(s)${RESET}" >&2
else
    echo "${BOLD}${GREEN}kaizen: gate passed${RESET}" >&2
fi
if [ "${#SUGGESTIONS[@]}" -gt 0 ]; then
    echo "${BOLD}Skills to consider:${RESET}" >&2
    printf '  %s\n' "${SUGGESTIONS[@]}" >&2
fi
exit 0
