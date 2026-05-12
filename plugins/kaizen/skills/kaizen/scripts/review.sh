#!/usr/bin/env bash
# kaizen review — fast, focused diff-time review (the article's "code review").
#
# Per synavos.com/blogs/code-review-vs-code-audit: review is per-change,
# lightweight, peer-style, immediate inline feedback. Distinct from
# /kaizen:audit which is periodic + comprehensive + severity-classified.
#
# Default scope: the current diff (HEAD vs base; staged if HEAD is clean).
# Detects logic-error patterns, coding-skill violations, paired-test gaps,
# style/format drift, minor security smells. Output is an inline checklist
# with file:line refs.
#
# Usage:
#   review.sh [--base <ref>] [--staged] [--agent] [--json]
#
#   --base <ref>    Compare against <ref> (default: main if exists, else master, else HEAD~1).
#   --staged        Review the staged diff only (git diff --cached).
#   --agent         Dispatch the agent-critic subagent for a smarter pass.
#                   The script still emits its own findings; --agent is additive.
#   --json          Emit findings as JSON instead of inline-style text.

set -uo pipefail

_SCRIPT_REAL_DIR="$(cd "$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"
source "$_SCRIPT_REAL_DIR/_paths.sh"

# ─── Args ────────────────────────────────────────────────────────────

BASE=""
STAGED=0
AGENT=0
JSON=0
while [ $# -gt 0 ]; do
  case "$1" in
    --base)   BASE="$2"; shift ;;
    --staged) STAGED=1 ;;
    --agent)  AGENT=1 ;;
    --json)   JSON=1 ;;
    -h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown flag: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

if [ -t 1 ]; then
  BOLD=$'\e[1m'; DIM=$'\e[2m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'
  RED=$'\e[31m'; BLUE=$'\e[34m'; RESET=$'\e[0m'
else
  BOLD=""; DIM=""; GREEN=""; YELLOW=""; RED=""; BLUE=""; RESET=""
fi

# ─── Repo + diff ─────────────────────────────────────────────────────

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "kaizen:review: not in a git repo" >&2
  exit 1
}
cd "$REPO_ROOT"

if [ "$STAGED" -eq 1 ]; then
  DIFF_RANGE="--cached"
  DIFF_LABEL="staged"
elif [ -n "$BASE" ]; then
  DIFF_RANGE="$BASE...HEAD"
  DIFF_LABEL="$BASE...HEAD"
else
  # Resolve base: main → master → HEAD~1
  if git rev-parse --verify main >/dev/null 2>&1; then
    BASE="main"
  elif git rev-parse --verify master >/dev/null 2>&1; then
    BASE="master"
  else
    BASE="HEAD~1"
  fi
  DIFF_RANGE="$BASE...HEAD"
  DIFF_LABEL="$BASE...HEAD"
fi

DIFF="$(git diff $DIFF_RANGE 2>/dev/null)"
CHANGED_FILES="$(git diff --name-only $DIFF_RANGE 2>/dev/null | grep -vE '\.lock$|package-lock\.json|Cargo\.lock|go\.sum' || true)"
FILE_COUNT="$(printf '%s\n' "$CHANGED_FILES" | grep -c '.' || true)"

if [ -z "$DIFF" ]; then
  echo "kaizen:review: no diff for $DIFF_LABEL — nothing to review" >&2
  exit 0
fi

# ─── Findings collection ─────────────────────────────────────────────

declare -a FINDINGS=()

add_finding() {
  # severity (info|warn|smell) + message + optional file:line ref
  local sev="$1" msg="$2" ref="${3:-}"
  if [ -n "$ref" ]; then
    FINDINGS+=("$sev|$msg|$ref")
  else
    FINDINGS+=("$sev|$msg|")
  fi
}

# Check 1 — new exports without paired tests
NEW_PUB_FN=$(printf '%s\n' "$DIFF" | grep -cE '^\+[[:space:]]*pub[[:space:]]+(async[[:space:]]+)?fn[[:space:]]+' 2>/dev/null || echo 0)
NEW_TS_EXPORT=$(printf '%s\n' "$DIFF" | grep -cE '^\+[[:space:]]*export[[:space:]]+(async[[:space:]]+)?function|^\+[[:space:]]*export[[:space:]]+const[[:space:]]+' 2>/dev/null || echo 0)
NEW_PY_DEF=$(printf '%s\n' "$DIFF" | grep -cE '^\+def[[:space:]]+[a-z_][a-z0-9_]*\(' 2>/dev/null || echo 0)
NEW_TESTS=$(printf '%s\n' "$DIFF" | grep -cE '^\+[[:space:]]*(#\[test\]|#\[tokio::test\]|it\(|test\(|describe\(|def[[:space:]]+test_)' 2>/dev/null || echo 0)
NEW_EXPORTS=$((NEW_PUB_FN + NEW_TS_EXPORT + NEW_PY_DEF))
if [ "$NEW_EXPORTS" -gt 0 ] && [ "$NEW_TESTS" -lt "$NEW_EXPORTS" ]; then
  IMBAL=$((NEW_EXPORTS - NEW_TESTS))
  add_finding "warn" "paired-test gap: $NEW_EXPORTS new exports vs $NEW_TESTS new tests (imbal: $IMBAL)" ""
fi

# Check 2 — coding-skills smells: deep nesting (>4 levels in added code)
DEEP_NEST=$(printf '%s\n' "$DIFF" | grep -cE '^\+[[:space:]]{16,}' 2>/dev/null || echo 0)
if [ "$DEEP_NEST" -gt 3 ]; then
  add_finding "smell" "deep nesting hot-spot: $DEEP_NEST added lines indented ≥16 spaces — consider extracting (KISS)" ""
fi

# Check 3 — TODO / FIXME / XXX introduced in this diff
NEW_TODO=$(printf '%s\n' "$DIFF" | grep -cE '^\+.*(TODO|FIXME|XXX|HACK):' 2>/dev/null || echo 0)
if [ "$NEW_TODO" -gt 0 ]; then
  add_finding "smell" "$NEW_TODO new TODO/FIXME/XXX marker(s) introduced — file an issue or resolve" ""
fi

# Check 4 — Long functions (rough heuristic: added blocks with >80 lines of "+" between two unchanged anchors)
LONG_HUNK=$(printf '%s\n' "$DIFF" | awk '/^@@/{n=0; next} /^\+/{n++; if(n>80){print; n=0}}' | wc -l)
if [ "$LONG_HUNK" -gt 0 ]; then
  add_finding "smell" "long-function smell: hunks of >80 added lines detected ($LONG_HUNK occurrence(s)) — consider splitting (SoC)" ""
fi

# Check 5 — Hardcoded secrets / credentials (minor security)
SECRET_HITS=$(printf '%s\n' "$DIFF" | grep -cE '^\+.*(api[_-]?key|secret|password|token|bearer)[[:space:]]*=[[:space:]]*["\047][a-zA-Z0-9]{16,}' 2>/dev/null || echo 0)
if [ "$SECRET_HITS" -gt 0 ]; then
  add_finding "warn" "potential hardcoded secret: $SECRET_HITS line(s) match api_key/secret/password=<literal> pattern — move to env or kaizen brain rule" ""
fi

# Check 6 — Diff size advisory (per kaizen sizing rule)
if [ "$FILE_COUNT" -gt 15 ]; then
  add_finding "warn" "large diff: $FILE_COUNT files — kaizen sizing rule recommends splitting at 15+ (multi-PR or micro split)" ""
fi

# Check 7 — Compile barrier dry-run (delegates to kaizen:gate if compile_check_cmd set)
COMPILE_CMD="$(python3 "$_SCRIPT_REAL_DIR/config.py" compile_check_cmd 2>/dev/null || echo "")"
if [ -n "$COMPILE_CMD" ]; then
  add_finding "info" "compile barrier configured: \`$COMPILE_CMD\` — run /kaizen:gate to verify" ""
fi

# Check 8 — Style: trailing whitespace introduced
TRAILING_WS=$(printf '%s\n' "$DIFF" | grep -cE '^\+.*[[:space:]]+$' 2>/dev/null || echo 0)
if [ "$TRAILING_WS" -gt 0 ]; then
  add_finding "smell" "trailing whitespace: $TRAILING_WS added line(s) end with whitespace — run formatter" ""
fi

# ─── Optional agent dispatch ─────────────────────────────────────────

if [ "$AGENT" -eq 1 ]; then
  add_finding "info" "--agent flag set: dispatch the 'agent-critic' subagent for a deeper smart-review pass (Claude does this from the slash command body)" ""
fi

# ─── Output ──────────────────────────────────────────────────────────

if [ "$JSON" -eq 1 ]; then
  printf '{\n'
  printf '  "base": "%s",\n' "$DIFF_LABEL"
  printf '  "files_changed": %s,\n' "$FILE_COUNT"
  printf '  "findings": [\n'
  first=1
  for f in "${FINDINGS[@]}"; do
    IFS='|' read -r sev msg ref <<<"$f"
    [ $first -eq 0 ] && printf ',\n'
    first=0
    printf '    {"severity": "%s", "message": "%s", "ref": "%s"}' "$sev" "$msg" "$ref"
  done
  printf '\n  ]\n}\n'
  exit 0
fi

echo ""
echo "${BOLD}kaizen review${RESET} — $DIFF_LABEL (${FILE_COUNT} file$([ "$FILE_COUNT" != "1" ] && echo "s"))"
echo ""

if [ ${#FINDINGS[@]} -eq 0 ]; then
  echo "  ${GREEN}✓${RESET} no findings — diff looks clean"
else
  for f in "${FINDINGS[@]}"; do
    IFS='|' read -r sev msg ref <<<"$f"
    case "$sev" in
      warn)  marker="${YELLOW}!${RESET}" ;;
      smell) marker="${YELLOW}~${RESET}" ;;
      info)  marker="${BLUE}i${RESET}" ;;
      *)     marker="${DIM}∘${RESET}" ;;
    esac
    if [ -n "$ref" ]; then
      printf '  %s %s ${DIM}(%s)${RESET}\n' "$marker" "$msg" "$ref"
    else
      printf '  %s %s\n' "$marker" "$msg"
    fi
  done
fi

echo ""
echo "${DIM}Review is per-change + lightweight. For comprehensive periodic checks${RESET}"
echo "${DIM}(security, architecture, tech debt) run: /kaizen:audit${RESET}"

exit 0
