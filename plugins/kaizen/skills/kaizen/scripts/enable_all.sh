#!/usr/bin/env bash
# kaizen enable-all — one-shot setup that runs the curated project +
# best-default global installers. Each step is idempotent (the
# underlying installer already handles "already installed").
#
# Default scope: project (kaizen:install + kaizen:onboard index).
# Default globals: disable-dupes + statusline + env + knowledge index
# + trace-search index. These are the non-intrusive, broadly-useful
# global setup steps.
#
# Heavy / intrusive steps require explicit flags:
#   --with-browser      Playwright + Chromium (~200MB download)
#   --with-daemon       crontab entry for hygiene + cache-refresh
#   --with-trace-proxy  HTTP proxy wrapping the CC → Anthropic connection
#
# Other flags:
#   --no-globals        skip the default-global stack (project only)
#   --no-project        skip project-scope stack (globals only)
#   --dry-run           print what would run, don't execute
#   --yes               skip confirmation prompts (currently no-op; here
#                       for forward-compat if interactive prompts are added)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# ─── Args ────────────────────────────────────────────────────────────

DRY_RUN=0
SKIP_GLOBALS=0
SKIP_PROJECT=0
WITH_BROWSER=0
WITH_DAEMON=0
WITH_TRACE_PROXY=0
YES=0

for arg in "$@"; do
  case "$arg" in
    --dry-run)         DRY_RUN=1 ;;
    --no-globals)      SKIP_GLOBALS=1 ;;
    --no-project)      SKIP_PROJECT=1 ;;
    --with-browser)    WITH_BROWSER=1 ;;
    --with-daemon)     WITH_DAEMON=1 ;;
    --with-trace-proxy) WITH_TRACE_PROXY=1 ;;
    --yes|-y)          YES=1 ;;
    -h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown flag: $arg (try --help)" >&2
      exit 2
      ;;
  esac
done

# ─── Colors ──────────────────────────────────────────────────────────

if [ -t 1 ]; then
  BOLD=$'\e[1m'; DIM=$'\e[2m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'
  RED=$'\e[31m'; BLUE=$'\e[34m'; RESET=$'\e[0m'
else
  BOLD=""; DIM=""; GREEN=""; YELLOW=""; RED=""; BLUE=""; RESET=""
fi

OK="${GREEN}✓${RESET}"
SK="${DIM}∘${RESET}"
ER="${RED}✗${RESET}"
DR="${YELLOW}≫${RESET}"

# ─── Step runner ─────────────────────────────────────────────────────

OK_COUNT=0
SKIP_COUNT=0
FAIL_COUNT=0
FAILED_STEPS=()

step() {
  local label="$1"; shift
  local cmd="$*"
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '  %s %-44s %s%s%s\n' "$DR" "$label" "$DIM" "$cmd" "$RESET"
    return 0
  fi
  printf '  %s %s\n' "$BLUE→${RESET}" "$label"
  if eval "$cmd" >/tmp/kaizen-enable-all.log 2>&1; then
    OK_COUNT=$((OK_COUNT + 1))
    printf '  %s %s\n' "$OK" "$label"
  else
    local rc=$?
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAILED_STEPS+=("$label (exit=$rc)")
    printf '  %s %s ${DIM}exit=%s${RESET}\n' "$ER" "$label" "$rc"
    sed 's/^/        /' /tmp/kaizen-enable-all.log | tail -5 >&2
  fi
}

skip_step() {
  local label="$1" reason="$2"
  SKIP_COUNT=$((SKIP_COUNT + 1))
  printf '  %s %-44s %s%s%s\n' "$SK" "$label" "$DIM" "$reason" "$RESET"
}

# ─── Preflight ───────────────────────────────────────────────────────

cd "${CLAUDE_PROJECT_DIR:-$PWD}" 2>/dev/null || true

IS_GIT_REPO=0
if git rev-parse --show-toplevel >/dev/null 2>&1; then
  IS_GIT_REPO=1
  REPO_ROOT="$(git rev-parse --show-toplevel)"
fi

mode="${BOLD}execute${RESET}"
[ "$DRY_RUN" -eq 1 ] && mode="${BOLD}${YELLOW}dry-run${RESET}"

echo ""
echo "${BOLD}kaizen enable-all${RESET} — $mode"
[ "$IS_GIT_REPO" -eq 1 ] && echo "  repo:  $REPO_ROOT"
[ "$IS_GIT_REPO" -eq 0 ] && echo "  ${DIM}(not in a git repo — project-scope steps will be skipped)${RESET}"
echo "  globals:  $([ "$SKIP_GLOBALS" -eq 1 ] && echo "${DIM}skipped${RESET}" || echo "default stack")"
echo "  project:  $([ "$SKIP_PROJECT" -eq 1 ] && echo "${DIM}skipped${RESET}" || ([ "$IS_GIT_REPO" -eq 1 ] && echo "kaizen:install + kaizen:onboard index" || echo "${DIM}n/a (no git repo)${RESET}"))"
[ "$WITH_BROWSER" -eq 1 ]    && echo "  opt-in:   ${YELLOW}+browser${RESET}"
[ "$WITH_DAEMON" -eq 1 ]     && echo "  opt-in:   ${YELLOW}+daemon${RESET}"
[ "$WITH_TRACE_PROXY" -eq 1 ] && echo "  opt-in:   ${YELLOW}+trace-proxy${RESET}"
echo ""

# ─── 1. Globals (default stack) ──────────────────────────────────────

if [ "$SKIP_GLOBALS" -eq 0 ]; then
  echo "${BOLD}globals (default stack)${RESET}"

  # disable-dupes — hide loose ~/.claude/skills/* that duplicate plugin
  step "disable duplicate loose skills" \
    "bash '$PLUGIN_ROOT/skills/kaizen/scripts/disable-skill.sh' --execute 2>&1 || bash '$PLUGIN_ROOT/skills/kaizen/scripts/disable-skill.sh' execute 2>&1"

  # statusline — adds the kaizen one-line status bar to CC settings
  step "install kaizen statusline" \
    "bash '$PLUGIN_ROOT/skills/kaizen/scripts/statusline.sh' install"

  # env — appends KAIZEN_* exports + aliases to shell rc
  step "install shell env (KAIZEN_ROOT + aliases)" \
    "bash '$PLUGIN_ROOT/skills/kaizen/scripts/kaizen-env.sh' install"

  # knowledge index — incremental over brain notes + plans + schemas + persona
  step "index Remember knowledge surface" \
    "uv run --script '$PLUGIN_ROOT/skills/kaizen/scripts/knowledge_index.py' index"

  # trace-search index — incremental over the trace event log
  step "index trace event log" \
    "uv run --script '$PLUGIN_ROOT/skills/kaizen/scripts/trace_index.py' index"

  echo ""
else
  echo "${DIM}globals: skipped (--no-globals)${RESET}"
  echo ""
fi

# ─── 2. Project (default if in git repo) ─────────────────────────────

if [ "$SKIP_PROJECT" -eq 0 ]; then
  echo "${BOLD}project${RESET}"
  if [ "$IS_GIT_REPO" -eq 0 ]; then
    skip_step "kaizen pre-commit gate" "not in a git repo"
    skip_step "codebase index (.kaizen/onboard.db)" "not in a git repo"
  else
    # kaizen:install — wires .kaizen/hooks/pre-commit + core.hooksPath
    step "install pre-commit gate (this repo)" \
      "bash '$PLUGIN_ROOT/skills/kaizen/scripts/install.sh'"

    # onboard index — semantic index of this project's source files
    step "index project codebase" \
      "cd '$REPO_ROOT' && uv run --script '$PLUGIN_ROOT/skills/kaizen/scripts/onboard_index.py' index"
  fi
  echo ""
else
  echo "${DIM}project: skipped (--no-project)${RESET}"
  echo ""
fi

# ─── 3. Opt-in heavy / intrusive steps ───────────────────────────────

if [ "$WITH_BROWSER" -eq 1 ] || [ "$WITH_DAEMON" -eq 1 ] || [ "$WITH_TRACE_PROXY" -eq 1 ]; then
  echo "${BOLD}opt-in${RESET}"

  if [ "$WITH_BROWSER" -eq 1 ]; then
    step "install Playwright browser MCP server" \
      "uv run --script '$PLUGIN_ROOT/skills/kaizen/scripts/browser_mcp.py' install"
  fi

  if [ "$WITH_DAEMON" -eq 1 ]; then
    step "install auto-daemon (crontab entry)" \
      "python3 '$PLUGIN_ROOT/skills/kaizen/scripts/daemon.py' install"
  fi

  if [ "$WITH_TRACE_PROXY" -eq 1 ]; then
    step "start LLM trace proxy" \
      "python3 '$PLUGIN_ROOT/skills/kaizen/scripts/llm_proxy.py' start"
  fi

  echo ""
fi

# ─── Summary ─────────────────────────────────────────────────────────

echo "${BOLD}summary${RESET}"
if [ "$DRY_RUN" -eq 1 ]; then
  echo "  (dry-run — nothing executed; re-run without --dry-run to apply)"
elif [ "$FAIL_COUNT" -eq 0 ]; then
  echo "  ${OK} $OK_COUNT ok, ${SK} $SKIP_COUNT skipped"
else
  echo "  ${OK} $OK_COUNT ok, ${SK} $SKIP_COUNT skipped, ${ER} $FAIL_COUNT failed"
  for f in "${FAILED_STEPS[@]}"; do
    echo "      ${RED}→${RESET} $f"
  done
  echo "  ${DIM}last failure log: /tmp/kaizen-enable-all.log${RESET}"
fi

echo ""
echo "${DIM}Next:${RESET}"
echo "  /kaizen:status              confirm everything green"
echo "  /kaizen:menu                full command reference"
[ "$IS_GIT_REPO" -eq 1 ] && [ "$SKIP_PROJECT" -eq 0 ] && \
  echo "  /kaizen:onboard search ...  query the new project index"

[ "$FAIL_COUNT" -gt 0 ] && exit 1
exit 0
