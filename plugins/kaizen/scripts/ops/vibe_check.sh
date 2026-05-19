#!/usr/bin/env bash
# kaizen vibe-check — augment kaizen-precommit with AI-coding specific checks
# against the staged diff. Advisory; never blocks.
#
# Encapsulates the Presta vibe-coding checklist
# (wearepresta.com/vibe-coding-tips-checklist-avoid-breaking-builds)
# composed with kaizen's gate. Reports to stderr; exits 0 always (advisory).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "vibe-check: not in a git repo" >&2
    exit 0
}
cd "$REPO_ROOT"

echo "" >&2
echo "vibe-check on staged diff" >&2

# 1. Gate dry-run
if [ -x "$SCRIPT_DIR/pre-commit.sh" ]; then
    if bash "$SCRIPT_DIR/pre-commit.sh" >/dev/null 2>&1; then
        echo "  ✓ kaizen:precommit dry-run: green" >&2
    else
        echo "  ✗ kaizen:precommit dry-run: failed — run kaizen-precommit for details" >&2
    fi
fi

# 2. New exported fns vs new tests (Rust heuristic; extend per language)
DIFF=$(git diff --cached 2>/dev/null || echo "")
if [ -n "$DIFF" ]; then
    NEW_PUB_FN=$(printf '%s\n' "$DIFF" | grep -cE '^\+[[:space:]]*pub[[:space:]]+(async[[:space:]]+)?fn[[:space:]]+' 2>/dev/null)
    NEW_PUB_FN=${NEW_PUB_FN:-0}
    NEW_TEST_FN=$(printf '%s\n' "$DIFF" | grep -cE '^\+[[:space:]]*#\[(test|tokio::test|async_std::test)\]' 2>/dev/null)
    NEW_TEST_FN=${NEW_TEST_FN:-0}
    # Also count JS/TS test functions
    JSTS_TESTS=$(printf '%s\n' "$DIFF" | grep -cE '^\+[[:space:]]*(it|test|describe)\(' 2>/dev/null)
    JSTS_TESTS=${JSTS_TESTS:-0}
    TOTAL_TESTS=$((NEW_TEST_FN + JSTS_TESTS))

    if [ "$NEW_PUB_FN" -gt 0 ] 2>/dev/null; then
        IMBAL=$((NEW_PUB_FN - TOTAL_TESTS))
        if [ "$IMBAL" -gt 0 ] 2>/dev/null; then
            echo "  ! new exported fns: $NEW_PUB_FN / new tests: $TOTAL_TESTS (imbalance: $IMBAL)" >&2
            echo "    → add $IMBAL paired test(s) OR set KAIZEN_SKIP_TDD_CHECK=1 with justification" >&2
        else
            echo "  ✓ tests cover new exports ($TOTAL_TESTS tests / $NEW_PUB_FN exports)" >&2
        fi
    fi

    # 3. Orphan imports — new `use` referencing crate NOT in manifest
    if [ -f "Cargo.toml" ]; then
        # Heuristic: extract added `use foo::` lines; check if `foo` exists in any Cargo.toml dependencies
        RULES_PY="$SCRIPT_DIR/rules.py"
        ORPHANS=""
        ALLOWED=""
        for crate in $(printf '%s\n' "$DIFF" | grep -oE '^\+[[:space:]]*use[[:space:]]+[a-z_][a-z0-9_]*' | awk '{print $NF}' | sort -u); do
            # Skip std, core, alloc, crate, self, super
            case "$crate" in
                std|core|alloc|crate|self|super|use) continue ;;
            esac
            # Check workspace + all crate Cargo.tomls
            if grep -rqE "^${crate}[[:space:]]*=" --include=Cargo.toml . 2>/dev/null; then
                continue
            fi
            # Not in any manifest — consult dependency-allowlist brain rule
            if [ -f "$RULES_PY" ] && python3 "$RULES_PY" dependency-allowed "$crate" >/dev/null 2>&1; then
                ALLOWED="$ALLOWED $crate"
            else
                ORPHANS="$ORPHANS $crate"
            fi
        done
        if [ -n "$ORPHANS" ]; then
            echo "  ! orphan imports (not in any Cargo.toml):$ORPHANS" >&2
            echo "    → add to Cargo.toml + cargo update before committing" >&2
        else
            echo "  ✓ no orphan imports (Rust)" >&2
        fi
        if [ -n "$ALLOWED" ]; then
            echo "  ∘ allowlisted deps (brain rule):$ALLOWED" >&2
        fi
    fi
fi

# 4. Commit message marker check (only if .git/COMMIT_EDITMSG exists — mid-commit)
COMMIT_MSG_FILE="$REPO_ROOT/.git/COMMIT_EDITMSG"
if [ -f "$COMMIT_MSG_FILE" ] && [ -s "$COMMIT_MSG_FILE" ]; then
    MSG=$(cat "$COMMIT_MSG_FILE" 2>/dev/null)
    if printf '%s' "$MSG" | grep -qE '\[AI\]|AI-assisted|AI:generated'; then
        echo "  ✓ commit msg marks AI-assisted authorship" >&2
    else
        echo "  ∘ commit msg marker: absent" >&2
        echo "    → if AI-assisted, add [AI] to the scope or 'AI-assisted' to the body" >&2
    fi
fi

# 5. Diff size (sizing advisory)
FILES_CHANGED=$(git diff --cached --name-only 2>/dev/null | wc -l)
FILES_CHANGED=${FILES_CHANGED:-0}
if [ "$FILES_CHANGED" -gt 15 ] 2>/dev/null; then
    echo "  ! large diff ($FILES_CHANGED files) — per kaizen sizing rule, split into sibling micros" >&2
    echo "    → see Notes/pref-sizing-by-trace-not-hours.md" >&2
fi

echo "" >&2

exit 0
