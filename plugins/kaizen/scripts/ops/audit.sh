#!/usr/bin/env bash
# kaizen audit — comprehensive periodic audit (the article's "code audit").
#
# Per synavos.com/blogs/code-review-vs-code-audit: audit is periodic,
# comprehensive, formal-report-producing, severity-classified. Distinct
# from /kaizen:review which is per-change + lightweight + inline.
#
# Default scope: whole repo. Writes a formal findings report to
# <repo>/.kaizen/workflow/audits/<UTC>-<scope>.md with Critical / High /
# Medium / Low / Info classification + actionable recommendations.
#
# Usage:
#   audit.sh [--scope <dir>] [--no-report] [--json] [--agent]
#
#   --scope <dir>   Limit the audit to a subdirectory (default: repo root).
#   --no-report     Print to stdout only; don't write the audit report file.
#   --json          Emit JSON instead of a markdown report / human text.
#   --agent         Dispatch agent-aegis (security) + kaizen-debt-auditor
#                   in parallel. The script still emits its own findings.

set -uo pipefail

_SCRIPT_REAL_DIR="$(cd "$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"
source "$_SCRIPT_REAL_DIR/../../skills/workflow/scripts/_paths.sh"  # _paths.sh deferred at legacy

# ─── Args ────────────────────────────────────────────────────────────

# ─── axis subcommand dispatch ─────────────────────────────────────────
# Lets users invoke per-axis audits via `kaizen audit axis <name>` —
# consolidates the 5 axis-specific slash commands (coverage /
# schema-coverage / name-quality / frontmatter / token-bloat) under the
# audit parent. The standalone /kaizen:<axis> commands stay as aliases
# for back-compat.
_SCRIPT_DIR="$(cd "$(dirname "$(python3 -c "import os, sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"
_PLUGIN_ROOT="$(cd "$_SCRIPT_DIR/../../.." && pwd)"

if [ "${1:-}" = "axis" ]; then
  shift
  axis_name="${1:-}"
  shift 2>/dev/null || true
  case "$axis_name" in
    coverage)        exec "$_PLUGIN_ROOT/bin/kaizen-coverage" "${@:-gaps}" ;;
    schema-coverage) exec "$_PLUGIN_ROOT/bin/kaizen-schema-coverage" "${@:-gaps}" ;;
    name-quality)    exec "$_PLUGIN_ROOT/bin/kaizen-name-quality" "${@:-gaps}" ;;
    frontmatter)     exec "$_PLUGIN_ROOT/bin/kaizen-frontmatter" "${@:-gaps}" ;;
    token-bloat)     exec "$_PLUGIN_ROOT/bin/kaizen-token-bloat" "${@:-scan}" ;;
    list|"")
      echo "kaizen audit axis — available axes:"
      echo "  coverage         1:1 code-to-test mapping"
      echo "  schema-coverage  feature-shape conformance"
      echo "  name-quality     filename ↔ docstring intent match"
      echo "  frontmatter      SKILL.md name/triggers"
      echo "  token-bloat      high-cost low-value content"
      echo ""
      echo "Usage: kaizen audit axis <name> [<axis-args>]"
      echo "       /kaizen:audit axis <name>"
      exit 0
      ;;
    *) echo "audit axis: unknown axis '$axis_name' — run 'audit axis list'" >&2; exit 2 ;;
  esac
fi

SCOPE=""
NO_REPORT=0
JSON=0
AGENT=0
while [ $# -gt 0 ]; do
  case "$1" in
    --scope)     SCOPE="$2"; shift ;;
    --no-report) NO_REPORT=1 ;;
    --json)      JSON=1 ;;
    --agent)     AGENT=1 ;;
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
  RED=$'\e[31m'; BLUE=$'\e[34m'; MAGENTA=$'\e[35m'; RESET=$'\e[0m'
else
  BOLD=""; DIM=""; GREEN=""; YELLOW=""; RED=""; BLUE=""; MAGENTA=""; RESET=""
fi

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "kaizen:audit: not in a git repo" >&2
  exit 1
}
cd "$REPO_ROOT"

if [ -n "$SCOPE" ]; then
  SCOPE_DIR="$REPO_ROOT/$SCOPE"
  [ ! -d "$SCOPE_DIR" ] && { echo "kaizen:audit: scope dir not found: $SCOPE_DIR" >&2; exit 1; }
  SCOPE_LABEL="$SCOPE"
else
  SCOPE_DIR="$REPO_ROOT"
  SCOPE_LABEL="(whole repo)"
fi

# ─── Findings collection (severity-classified) ───────────────────────

declare -a CRITICAL=()
declare -a HIGH=()
declare -a MEDIUM=()
declare -a LOW=()
declare -a INFO=()

# add <severity> <category> <message> [<ref>]
add() {
  local sev="$1" cat="$2" msg="$3" ref="${4:-}"
  local item="$cat | $msg"
  [ -n "$ref" ] && item="$item ($ref)"
  case "$sev" in
    critical) CRITICAL+=("$item") ;;
    high)     HIGH+=("$item") ;;
    medium)   MEDIUM+=("$item") ;;
    low)      LOW+=("$item") ;;
    info)     INFO+=("$item") ;;
  esac
}

# ─── Category: Security ──────────────────────────────────────────────

# Hardcoded secrets across the codebase (not just diff — full scan)
SECRET_FILES=$(grep -rlE '(api[_-]?key|secret|password|token|bearer)[[:space:]]*=[[:space:]]*["\047][a-zA-Z0-9]{16,}' \
  --include='*.rs' --include='*.py' --include='*.js' --include='*.ts' \
  --include='*.go' --include='*.java' --include='*.kt' --include='*.swift' \
  --include='*.rb' --include='*.php' --include='*.cs' \
  "$SCOPE_DIR" 2>/dev/null | grep -vE 'test|spec|fixture|example' | wc -l)
[ "$SECRET_FILES" -gt 0 ] && add "high" "security" \
  "potential hardcoded credentials in $SECRET_FILES non-test file(s) — scan with: grep -rE '(api[_-]?key|secret|password)[[:space:]]*=[[:space:]]*\"' $SCOPE_DIR"

# Unsafe Rust outside of dedicated unsafe modules (heuristic)
if find "$SCOPE_DIR" -name 'Cargo.toml' -print -quit | grep -q .; then
  UNSAFE_BLOCKS=$(grep -rlE '^\s*unsafe\s+(\{|fn)' --include='*.rs' "$SCOPE_DIR" 2>/dev/null \
    | grep -vE '(ffi|unsafe|bindings)\.rs' | wc -l)
  [ "$UNSAFE_BLOCKS" -gt 0 ] && add "medium" "security" \
    "unsafe { ... } in $UNSAFE_BLOCKS non-ffi file(s) — audit each block for soundness"
fi

# eval / exec / shell in Python (security smell)
# Pattern excludes:
#   - method calls (.eval() / .exec()) — preceded by `.` (PyTorch model.eval(), etc.)
#   - docstring/prose mentions — `shell=True` only matches when preceded by `(` or `,`
#     (i.e., real argument position in a call, not text inside a string)
if find "$SCOPE_DIR" -name 'pyproject.toml' -o -name '*.py' -print -quit | grep -q .; then
  EVAL_HITS=$(grep -rlE '(^|[^a-zA-Z_.])eval\(|(^|[^a-zA-Z_.])exec\(|[(,][[:space:]]*shell[[:space:]]*=[[:space:]]*True' \
    --include='*.py' "$SCOPE_DIR" 2>/dev/null | grep -vE 'test|spec' | wc -l)
  [ "$EVAL_HITS" -gt 0 ] && add "high" "security" \
    "eval/exec/shell=True in $EVAL_HITS Python file(s) — review for injection vectors"
fi

# ─── Category: Architecture ──────────────────────────────────────────

# Onion-DDD violations: outer-ring crates imported from core (Rust-specific)
if [ -d "$SCOPE_DIR/crates/core" ]; then
  for outer in clap tokio reqwest sqlx; do
    # noqa: etu — grep -l + wc -l counts matching FILES (legitimate idiom);
    # grep -c counts matching LINES per-file (different semantics).
    HITS=$(grep -rlE "^use[[:space:]]+$outer::" --include='*.rs' "$SCOPE_DIR/crates/core" 2>/dev/null | wc -l)
    [ "$HITS" -gt 0 ] && add "high" "architecture" \
      "onion violation: $HITS file(s) in crates/core/ import outer-ring crate '$outer'"
  done
fi

# Cyclic imports (Python) — heuristic: A imports B and B imports A
# (Skipped here as cycle detection is non-trivial; agent-warden does this better)

# Dead module mod-declarations not in any other file (rough check)
if find "$SCOPE_DIR" -name '*.rs' -print -quit | grep -q .; then
  # noqa: etu — counting total `pub mod` lines across the tree, not
  # per-file matches. The /10 heuristic immediately downstream confirms
  # the intent is a rough total, not actionable per-file output.
  ORPHAN_MODS=$(grep -rE '^pub mod [a-z_]+;' --include='*.rs' "$SCOPE_DIR" 2>/dev/null | wc -l)
  ORPHAN_MODS=$((ORPHAN_MODS / 10))  # very rough; pretend / 10 to suppress most noise
  [ "$ORPHAN_MODS" -gt 5 ] && add "low" "architecture" \
    "module declarations (pub mod) density is high — consider dead-code audit"
fi

# ─── Category: Tech Debt ─────────────────────────────────────────────

TODO_COUNT=$(grep -rE '(TODO|FIXME|XXX|HACK):' "$SCOPE_DIR" --include='*.rs' --include='*.py' \
  --include='*.js' --include='*.ts' --include='*.go' --include='*.java' \
  2>/dev/null | wc -l)
if [ "$TODO_COUNT" -gt 100 ]; then
  add "medium" "tech-debt" "$TODO_COUNT TODO/FIXME/XXX/HACK markers across the codebase — pick top 10 for backlog"
elif [ "$TODO_COUNT" -gt 20 ]; then
  add "low" "tech-debt" "$TODO_COUNT TODO/FIXME/XXX/HACK markers"
elif [ "$TODO_COUNT" -gt 0 ]; then
  add "info" "tech-debt" "$TODO_COUNT TODO/FIXME/XXX/HACK markers"
fi

# ─── Category: Dependencies ──────────────────────────────────────────

# Outdated lockfiles (older than 6 months → stale)
for lock in "$SCOPE_DIR"/Cargo.lock "$SCOPE_DIR"/package-lock.json "$SCOPE_DIR"/yarn.lock "$SCOPE_DIR"/poetry.lock; do
  [ ! -f "$lock" ] && continue
  if [ "$(find "$lock" -mtime +180 -print 2>/dev/null)" ]; then
    add "low" "dependencies" "lockfile older than 6 months: $(basename "$lock")"
  fi
done

# Direct deps count vs transitive (Rust)
if [ -f "$SCOPE_DIR/Cargo.toml" ]; then
  if command -v cargo >/dev/null 2>&1; then
    add "info" "dependencies" "run \`cargo tree --depth 1\` for direct-dep audit; \`cargo outdated\` for staleness"
  fi
fi

# ─── Category: Coverage / Tests ──────────────────────────────────────

TEST_FILES=$(find "$SCOPE_DIR" -path '*/target' -prune -o -path '*/node_modules' -prune -o \
  \( -name 'test_*.py' -o -name '*_test.py' -o -name '*.test.ts' -o -name '*.test.js' \
  -o -name '*.spec.ts' -o -name '*_test.go' \) -print 2>/dev/null | wc -l)
SRC_FILES=$(find "$SCOPE_DIR" -path '*/target' -prune -o -path '*/node_modules' -prune -o \
  \( -name '*.rs' -o -name '*.py' -o -name '*.ts' -o -name '*.go' \) -print 2>/dev/null | wc -l)
if [ "$SRC_FILES" -gt 10 ]; then
  RATIO=$((TEST_FILES * 100 / SRC_FILES))
  if [ "$RATIO" -lt 10 ]; then
    add "high" "coverage" "test-file ratio ${RATIO}% ($TEST_FILES tests / $SRC_FILES src) — below recommended 10%"
  elif [ "$RATIO" -lt 25 ]; then
    add "medium" "coverage" "test-file ratio ${RATIO}% — below recommended 25%"
  else
    add "info" "coverage" "test-file ratio ${RATIO}% ($TEST_FILES / $SRC_FILES) — healthy"
  fi
fi

# ─── Category: Documentation ─────────────────────────────────────────

[ ! -f "$SCOPE_DIR/README.md" ] && [ -z "$SCOPE" ] && \
  add "medium" "documentation" "no README.md at repo root"
[ ! -f "$REPO_ROOT/CLAUDE.md" ] && \
  add "low" "documentation" "no CLAUDE.md — agents lack durable orientation context; run /init to bootstrap"

# Architecture log presence
ARCH_LOG="$(python3 "$_SCRIPT_REAL_DIR/../../skills/workflow/scripts/config.py" architecture_log 2>/dev/null || echo "")"
[ -n "$ARCH_LOG" ] && [ ! -f "$REPO_ROOT/$ARCH_LOG" ] && \
  add "low" "documentation" "architecture_log configured ($ARCH_LOG) but file missing"

# ─── Category: Compliance / License ──────────────────────────────────

if [ ! -f "$REPO_ROOT/LICENSE" ] && [ ! -f "$REPO_ROOT/LICENSE.md" ] && [ ! -f "$REPO_ROOT/LICENSE.txt" ]; then
  add "medium" "compliance" "no LICENSE file — adopting an open-source license clarifies use"
fi

# ─── Optional agent dispatch ─────────────────────────────────────────

if [ "$AGENT" -eq 1 ]; then
  add "info" "agent" "agent-aegis (security) + kaizen-debt-auditor (architecture+debt) dispatched in parallel — Claude does this from the slash command body"
fi

# ─── Output ──────────────────────────────────────────────────────────

TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
TS_HUMAN=$(date -u +%Y-%m-%dT%H:%M:%SZ)
# Count only non-empty entries (bash arrays may carry an empty string).
count_real() { local n=0; for x in "$@"; do [ -n "$x" ] && n=$((n+1)); done; echo "$n"; }
TOTAL=$(( $(count_real "${CRITICAL[@]:-}") + $(count_real "${HIGH[@]:-}") + $(count_real "${MEDIUM[@]:-}") + $(count_real "${LOW[@]:-}") + $(count_real "${INFO[@]:-}") ))

render_section() {
  local label="$1" color="$2"
  shift 2
  # Filter empty elements (bash array passes empty string when array is unset+default-expanded).
  local items=()
  for x in "$@"; do
    [ -n "$x" ] && items+=("$x")
  done
  [ ${#items[@]} -eq 0 ] && return 0
  echo ""
  printf '%s ▸ %s (%d)%s\n' "$color$BOLD" "$label" "${#items[@]}" "$RESET"
  for item in "${items[@]}"; do
    printf '  • %s\n' "$item"
  done
}

if [ "$JSON" -eq 1 ]; then
  # v1.39.0+: pass arrays via env (newline-joined) instead of
  # interpolating into the heredoc. Mechanically identical output
  # but no shell-substitution into Python source.
  KAIZEN_TS="$TS_HUMAN" \
  KAIZEN_SCOPE="$SCOPE_LABEL" \
  KAIZEN_TOTAL="$TOTAL" \
  KAIZEN_CRITICAL="$(printf '%s\n' "${CRITICAL[@]:-}")" \
  KAIZEN_HIGH="$(printf '%s\n' "${HIGH[@]:-}")" \
  KAIZEN_MEDIUM="$(printf '%s\n' "${MEDIUM[@]:-}")" \
  KAIZEN_LOW="$(printf '%s\n' "${LOW[@]:-}")" \
  KAIZEN_INFO="$(printf '%s\n' "${INFO[@]:-}")" \
  python3 <<'PY'
import json, os
def _list(env_name):
    raw = os.environ.get(env_name, "")
    return [line for line in raw.split("\n") if line.strip()]
out = {
    "ts": os.environ.get("KAIZEN_TS", ""),
    "scope": os.environ.get("KAIZEN_SCOPE", ""),
    "total_findings": int(os.environ.get("KAIZEN_TOTAL", "0")),
    "critical": _list("KAIZEN_CRITICAL"),
    "high":     _list("KAIZEN_HIGH"),
    "medium":   _list("KAIZEN_MEDIUM"),
    "low":      _list("KAIZEN_LOW"),
    "info":     _list("KAIZEN_INFO"),
}
print(json.dumps(out, indent=2))
PY
  exit 0
fi

# Human-readable output (stdout)
echo ""
echo "${BOLD}kaizen audit${RESET} — $SCOPE_LABEL @ $TS_HUMAN"
echo "${DIM}$TOTAL finding(s) across critical / high / medium / low / info${RESET}"

render_section "CRITICAL" "$MAGENTA" "${CRITICAL[@]:-}"
render_section "HIGH"     "$RED"     "${HIGH[@]:-}"
render_section "MEDIUM"   "$YELLOW"  "${MEDIUM[@]:-}"
render_section "LOW"      "$BLUE"    "${LOW[@]:-}"
render_section "INFO"     "$DIM"     "${INFO[@]:-}"

if [ "$TOTAL" -eq 0 ]; then
  echo ""
  echo "  ${GREEN}✓${RESET} no findings — clean audit"
fi

# Write report file
if [ "$NO_REPORT" -eq 0 ]; then
  AUDIT_DIR="$(kaizen_project_workflow_dir "$REPO_ROOT")/audits"
  mkdir -p "$AUDIT_DIR"
  REPORT="$AUDIT_DIR/${TS}-${SCOPE:+${SCOPE//\//-}-}repo.md"
  {
    echo "# kaizen audit — $TS_HUMAN"
    echo ""
    echo "**Scope:** $SCOPE_LABEL"
    echo "**Total findings:** $TOTAL"
    echo ""
    echo "Per [synavos.com/code-review-vs-code-audit](https://synavos.com/blogs/code-review-vs-code-audit/):"
    echo "audit is comprehensive + periodic + severity-classified. For per-change"
    echo "lightweight review, use \`/kaizen:review\`."
    echo ""
    for sev in critical high medium low info; do
      case "$sev" in
        critical) items=("${CRITICAL[@]:-}") ;;
        high)     items=("${HIGH[@]:-}") ;;
        medium)   items=("${MEDIUM[@]:-}") ;;
        low)      items=("${LOW[@]:-}") ;;
        info)     items=("${INFO[@]:-}") ;;
      esac
      # Filter empty array element
      filtered=()
      for i in "${items[@]:-}"; do [ -n "$i" ] && filtered+=("$i"); done
      [ ${#filtered[@]} -eq 0 ] && continue
      echo "## $(echo "$sev" | tr '[:lower:]' '[:upper:]') — ${#filtered[@]}"
      echo ""
      for item in "${filtered[@]}"; do
        echo "- $item"
      done
      echo ""
    done
    echo "---"
    echo ""
    echo "_Generated by \`/kaizen:audit\` v1.23.0. Recommendations: prioritize Critical → High → Medium, file as kaizen backlog entries with \`/kaizen:backlog add\`._"
  } > "$REPORT"
  echo ""
  echo "${GREEN}→${RESET} report saved: ${BOLD}$REPORT${RESET}"
fi

echo ""
echo "${DIM}Audit is periodic + comprehensive. For per-change review run: /kaizen:review${RESET}"

exit 0
