#!/usr/bin/env bash
# kaizen ci-gate — runs the CI-equivalent merge gate locally.
#
# This is the SSOT for "what CI checks" — .github/workflows/test.yml
# calls this script so the two never drift. It is the *merge* gate
# (heavy, whole-repo) — distinct from pre-commit.sh, the *staged* gate.
#
#   ci-gate.sh                run all checks (incl. the unittest suite)
#   ci-gate.sh --syntax-only  skip the slow unittest suite (static checks only)
#
# Exit 0 = all green; non-zero = first failing check.
# Bypass: KAIZEN_CI_GATE_DISABLE=1 (exits 0 immediately).

set -uo pipefail

if [ "${KAIZEN_CI_GATE_DISABLE:-}" = "1" ]; then
  echo "ci-gate: skipped (KAIZEN_CI_GATE_DISABLE=1)"
  exit 0
fi

SYNTAX_ONLY=0
[ "${1:-}" = "--syntax-only" ] && SYNTAX_ONLY=1

# Resolve the repo root (the kaizen-md checkout). This script lives at
# plugins/kaizen/skills/workflow/scripts/ — five levels below the root.
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$_SCRIPT_DIR/../../../../.." && pwd)"
cd "$REPO_ROOT"

fail() { echo "  ✗ $1" >&2; exit 1; }
ok()   { echo "  ✓ $1"; }

echo "kaizen ci-gate — $REPO_ROOT"

# 1. Shell scripts pass bash syntax check
for f in plugins/kaizen/skills/workflow/scripts/*.sh \
         plugins/kaizen/hooks/*.sh plugins/kaizen/hooks/claude/*.sh \
         plugins/kaizen/bin/kaizen plugins/kaizen/bin/kaizen-*; do
  [ -f "$f" ] || continue
  bash -n "$f" || fail "bash syntax: $f"
done
ok "shell scripts parse"

# 2. Python scripts parse
for f in plugins/kaizen/skills/workflow/scripts/*.py plugins/kaizen/tests/*.py; do
  [ -f "$f" ] || continue
  python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$f" \
    || fail "python parse: $f"
done
ok "python scripts parse"

# 3. JSON manifests valid
for f in .claude-plugin/marketplace.json \
         plugins/kaizen/.claude-plugin/plugin.json \
         plugins/kaizen/hooks/hooks.json plugins/kaizen/.mcp.json \
         plugins/kaizen/config.defaults.json; do
  [ -f "$f" ] || continue
  python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$f" \
    || fail "json invalid: $f"
done
ok "json manifests valid"

# 4. SKILL.md frontmatter
miss=0
for f in plugins/kaizen/skills/*/SKILL.md; do
  grep -qE '^name:' "$f"        || { echo "    missing name: $f" >&2; miss=1; }
  grep -qE '^description:' "$f" || { echo "    missing description: $f" >&2; miss=1; }
done
[ "$miss" = "0" ] || fail "SKILL.md frontmatter"
ok "SKILL.md frontmatter"

# 5. iron-laws codegen drift gate
if [ -f plugins/kaizen/skills/iron-laws/application/codegen.py ]; then
  python3 plugins/kaizen/skills/iron-laws/application/codegen.py --check \
    || fail "iron-laws codegen drift (run codegen.py to regenerate)"
  ok "iron-laws codegen in sync"
fi

if [ "$SYNTAX_ONLY" = "1" ]; then
  echo "ci-gate: static checks passed (--syntax-only; unittest suite skipped)"
  exit 0
fi

# 6. Full unittest suite
( cd plugins/kaizen && python3 -m unittest discover -s tests -p 'test_*.py' ) \
  || fail "unittest suite"
ok "unittest suite"

echo "ci-gate: all checks passed"
