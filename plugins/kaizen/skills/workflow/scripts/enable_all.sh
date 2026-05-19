#!/usr/bin/env bash
# kaizen enable-all — one-shot setup that runs the curated project +
# best-default global installers. Each step is idempotent (the
# underlying installer already handles "already installed").
#
# Default scope: project (kaizen:setup install + kaizen:onboard index).
# Default globals: disable-dupes + statusline + env + knowledge index
# + trace-search index. These are the non-intrusive, broadly-useful
# global setup steps.
#
# Heavy / intrusive steps require explicit flags:
#   --with-index        run knowledge + trace + onboard indexers (slow on
#                       first run — pulls uv deps + sentence-transformers
#                       model + walks the codebase; can exceed CC's bash
#                       timeout. Run /kaizen:onboard index etc. manually
#                       if you skip this and need the indexes later.)
#   --with-browser      Playwright + Chromium (~200MB download)
#   --with-daemon       crontab entry for hygiene + cache-refresh
#   --with-trace-proxy  HTTP proxy wrapping the CC → Anthropic connection
#
# Other flags:
#   --no-globals        skip the default-global stack (project only)
#   --no-project        skip project-scope stack (globals only)
#   --dry-run           print FULL commands that would run, don't execute
#   --check             audit-only — show step labels with "would run"
#                       (terser than --dry-run; for status overview)
#   --fail-fast         abort with exit 1 on the first failing step
#                       (default: best-effort — every step runs, summary
#                       lists all failures at the end)
#   --yes               skip confirmation prompts (currently no-op; here
#                       for forward-compat if interactive prompts are added)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# ─── Args ────────────────────────────────────────────────────────────

DRY_RUN=0
CHECK_MODE=0
FAIL_FAST=0
SKIP_GLOBALS=0
SKIP_PROJECT=0
WITH_INDEX=0
WITH_BROWSER=0
WITH_DAEMON=0
WITH_TRACE_PROXY=0
YES=0

for arg in "$@"; do
  case "$arg" in
    --dry-run)         DRY_RUN=1 ;;
    --check)           CHECK_MODE=1 ;;          # audit-only — no execution
    --fail-fast)       FAIL_FAST=1 ;;           # abort on first failed step
    --no-globals)      SKIP_GLOBALS=1 ;;
    --no-project)      SKIP_PROJECT=1 ;;
    --with-index)      WITH_INDEX=1 ;;
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
#
# Each step's command runs in a SUBSHELL via `bash -c "$cmd"` — not
# `eval`. `bash -c` is safer than `eval`:
#   - command runs in a subshell (can't mutate the parent)
#   - no re-expansion of values (no $(touch /tmp/pwn) injection via
#     interpolated PLUGIN_ROOT or REPO_ROOT)
#   - the `efficient-tool-use::eval-on-user-input` anti-pattern is
#     silenced
#
# Per-step log goes to `mktemp` (unique-per-step), so multi-failure
# inspection works without overwrites. The previous global
# /tmp/kaizen-enable-all.log was overwritten on each step.
#
# --check mode short-circuits to a label-only summary (no exec).
# --fail-fast exits 1 immediately on the first step failure.

OK_COUNT=0
SKIP_COUNT=0
FAIL_COUNT=0
FAILED_STEPS=()
ALL_STEP_LOGS=()  # for tail-many-on-failure rendering

step() {
  local label="$1"; shift
  local cmd="$*"
  if [ "$CHECK_MODE" -eq 1 ]; then
    printf '  %s %-44s %swould run%s\n' "$DR" "$label" "$DIM" "$RESET"
    return 0
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '  %s %-44s %s%s%s\n' "$DR" "$label" "$DIM" "$cmd" "$RESET"
    return 0
  fi
  local logf
  logf="$(mktemp -t kaizen-enable-all.XXXXXX)" || logf="/tmp/kaizen-enable-all.$$"
  ALL_STEP_LOGS+=("$label::$logf")
  printf '  %s %s\n' "$BLUE→${RESET}" "$label"
  if bash -c "$cmd" >"$logf" 2>&1; then
    OK_COUNT=$((OK_COUNT + 1))
    printf '  %s %s\n' "$OK" "$label"
  else
    local rc=$?
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAILED_STEPS+=("$label (exit=$rc) [$logf]")
    printf '  %s %s ${DIM}exit=%s [%s]${RESET}\n' "$ER" "$label" "$rc" "$logf"
    sed 's/^/        /' "$logf" | tail -5 >&2
    if [ "$FAIL_FAST" -eq 1 ]; then
      echo ""
      echo "  ${RED}--fail-fast: aborting after first failure${RESET}" >&2
      exit 1
    fi
  fi
}

# step_stream — like step() but does NOT swallow stdout/stderr. For
# long-running commands (the indexers) so the user sees progress live
# in their terminal. The progress lines (from `_progress.Progress`)
# render as `\r` overwrites on a TTY or throttled single lines in a pipe.
# Same eval→bash-c hardening as step() (no per-step log because we're
# already streaming).
step_stream() {
  local label="$1"; shift
  local cmd="$*"
  if [ "$CHECK_MODE" -eq 1 ]; then
    printf '  %s %-44s %swould run (streams output)%s\n' "$DR" "$label" "$DIM" "$RESET"
    return 0
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '  %s %-44s %s%s%s\n' "$DR" "$label" "$DIM" "$cmd" "$RESET"
    return 0
  fi
  printf '  %s %s\n' "$BLUE→${RESET}" "$label"
  if bash -c "$cmd"; then
    OK_COUNT=$((OK_COUNT + 1))
    printf '  %s %s\n' "$OK" "$label"
  else
    local rc=$?
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAILED_STEPS+=("$label (exit=$rc)")
    printf '  %s %s ${DIM}exit=%s${RESET}\n' "$ER" "$label" "$rc"
    if [ "$FAIL_FAST" -eq 1 ]; then
      echo ""
      echo "  ${RED}--fail-fast: aborting after first failure${RESET}" >&2
      exit 1
    fi
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
[ "$CHECK_MODE" -eq 1 ] && mode="${BOLD}${BLUE}check${RESET}"
[ "$FAIL_FAST" -eq 1 ] && mode="$mode ${DIM}(fail-fast)${RESET}"

echo ""
echo "${BOLD}kaizen enable-all${RESET} — $mode"
[ "$IS_GIT_REPO" -eq 1 ] && echo "  repo:  $REPO_ROOT"
[ "$IS_GIT_REPO" -eq 0 ] && echo "  ${DIM}(not in a git repo — project-scope steps will be skipped)${RESET}"
echo "  globals:  $([ "$SKIP_GLOBALS" -eq 1 ] && echo "${DIM}skipped${RESET}" || echo "default stack")"
echo "  project:  $([ "$SKIP_PROJECT" -eq 1 ] && echo "${DIM}skipped${RESET}" || ([ "$IS_GIT_REPO" -eq 1 ] && echo "kaizen:setup install" || echo "${DIM}n/a (no git repo)${RESET}"))"
[ "$WITH_INDEX" -eq 1 ]      && echo "  opt-in:   ${YELLOW}+index (knowledge/trace/onboard)${RESET}"
[ "$WITH_BROWSER" -eq 1 ]    && echo "  opt-in:   ${YELLOW}+browser${RESET}"
[ "$WITH_DAEMON" -eq 1 ]     && echo "  opt-in:   ${YELLOW}+daemon${RESET}"
[ "$WITH_TRACE_PROXY" -eq 1 ] && echo "  opt-in:   ${YELLOW}+trace-proxy${RESET}"
echo ""

# ─── 0. Path migration (v1.22.0+) ────────────────────────────────────
# Move legacy ~/.claude/{.kaizen-trace,.kaizen-knowledge,...,kaizen-inbox,
# backups/kaizen,kaizen-schemas} into the unified ~/.claude/.kaizen/{trace,
# knowledge,daemon,inbox,backups,schemas}/ layout. Also moves <repo>/.workflow/
# → <repo>/.kaizen/workflow/ if applicable. Idempotent.
echo "${BOLD}path migration (v1.22.0+)${RESET}"
step "migrate legacy paths" \
  "bash '$PLUGIN_ROOT/skills/workflow/scripts/migrate_paths.sh'"
echo ""

# ─── 1. Globals (default stack) ──────────────────────────────────────

if [ "$SKIP_GLOBALS" -eq 0 ]; then
  echo "${BOLD}globals (default stack)${RESET}"

  # disable-dupes — hide loose ~/.claude/skills/* that duplicate plugin
  step "disable duplicate loose skills" \
    "bash '$PLUGIN_ROOT/skills/workflow/scripts/disable-skill.sh' all-loose-dupes"

  # statusline — adds the kaizen one-line status bar to CC settings
  step "install kaizen statusline" \
    "bash '$PLUGIN_ROOT/skills/workflow/scripts/statusline.sh' install"

  # env — appends KAIZEN_* exports + aliases to shell rc
  step "install shell env (KAIZEN_ROOT + aliases)" \
    "bash '$PLUGIN_ROOT/skills/workflow/scripts/kaizen-env.sh' install"

  # bootstrap — pre-warm every uv-script venv so first use is not a
  # cold download. Idempotent (uv caches); KAIZEN_BOOTSTRAP_DISABLE=1
  # skips the pre-warm. Runs before the watch daemon so daemon.py's
  # watchdog venv is warm when watch-start spawns it.
  step "bootstrap uv-script venvs" \
    "bash '$PLUGIN_ROOT/skills/workflow/scripts/bootstrap.sh'"

  # plugin-index watch daemon — on by default; KAIZEN_DAEMON_INDEX_DISABLE
  # opts out. watch-start is idempotent + cron-supervised (daemon install).
  if [ "${KAIZEN_DAEMON_INDEX_DISABLE:-}" != "1" ]; then
    step "start plugin-index watch daemon" \
      "bash -c 'uv run --script \"$PLUGIN_ROOT/scripts/daemon/daemon.py\" watch-start && uv run --script \"$PLUGIN_ROOT/scripts/daemon/daemon.py\" install'"
  fi

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
  else
    # kaizen:setup install — wires .kaizen/hooks/pre-commit + core.hooksPath
    step "install pre-commit gate (this repo)" \
      "bash '$PLUGIN_ROOT/skills/workflow/scripts/setup.sh' install"
  fi
  echo ""
else
  echo "${DIM}project: skipped (--no-project)${RESET}"
  echo ""
fi

# ─── 3. Opt-in heavy / intrusive steps ───────────────────────────────

if [ "$WITH_INDEX" -eq 1 ] || [ "$WITH_BROWSER" -eq 1 ] || [ "$WITH_DAEMON" -eq 1 ] || [ "$WITH_TRACE_PROXY" -eq 1 ]; then
  echo "${BOLD}opt-in${RESET}"

  if [ "$WITH_INDEX" -eq 1 ]; then
    # knowledge index — incremental over brain notes + plans + schemas + persona
    step_stream "index Remember knowledge surface" \
      "uv run --script '$PLUGIN_ROOT/scripts/indexers/knowledge_index.py' index"

    # trace-search index — incremental over the trace event log
    step_stream "index trace event log" \
      "uv run --script '$PLUGIN_ROOT/scripts/indexers/trace_index.py' index"

    # onboard index — semantic index of this project's source files
    if [ "$IS_GIT_REPO" -eq 1 ]; then
      step_stream "index project codebase" \
        "cd '$REPO_ROOT' && uv run --script '$PLUGIN_ROOT/scripts/indexers/onboard_index.py' index"
    else
      skip_step "index project codebase" "not in a git repo"
    fi
  fi

  if [ "$WITH_BROWSER" -eq 1 ]; then
    step "install Playwright browser MCP server" \
      "uv run --script '$PLUGIN_ROOT/scripts/mcp/browser_mcp.py' install"
  fi

  if [ "$WITH_DAEMON" -eq 1 ]; then
    step "install auto-daemon (crontab entry)" \
      "uv run --script '$PLUGIN_ROOT/scripts/daemon/daemon.py' install"
  fi

  if [ "$WITH_TRACE_PROXY" -eq 1 ]; then
    step "start LLM trace proxy" \
      "python3 '$PLUGIN_ROOT/skills/workflow/scripts/llm_proxy.py' start"
  fi

  echo ""
fi

# ─── Summary ─────────────────────────────────────────────────────────

echo "${BOLD}summary${RESET}"
if [ "$CHECK_MODE" -eq 1 ]; then
  echo "  (check — nothing executed; re-run without --check to apply)"
elif [ "$DRY_RUN" -eq 1 ]; then
  echo "  (dry-run — nothing executed; re-run without --dry-run to apply)"
elif [ "$FAIL_COUNT" -eq 0 ]; then
  echo "  ${OK} $OK_COUNT ok, ${SK} $SKIP_COUNT skipped"
else
  echo "  ${OK} $OK_COUNT ok, ${SK} $SKIP_COUNT skipped, ${ER} $FAIL_COUNT failed"
  for f in "${FAILED_STEPS[@]}"; do
    echo "      ${RED}→${RESET} $f"
  done
  echo "  ${DIM}per-step logs preserved at the paths above (mktemp'd; one per failing step)${RESET}"
fi

echo ""
echo "${DIM}Next:${RESET}"
echo "  /kaizen:status              confirm everything green"
echo "  /kaizen:help                full command reference (interactive)"
if [ "$WITH_INDEX" -eq 0 ]; then
  echo "  ${DIM}(indexers skipped — run /kaizen:setup --enable-all --with-index when you${RESET}"
  echo "  ${DIM} have a few minutes; or /kaizen:onboard index / /kaizen:knowledge${RESET}"
  echo "  ${DIM} index / /kaizen:trace-search index individually.)${RESET}"
elif [ "$IS_GIT_REPO" -eq 1 ] && [ "$SKIP_PROJECT" -eq 0 ]; then
  echo "  /kaizen:onboard search ...  query the new project index"
fi

[ "$FAIL_COUNT" -gt 0 ] && exit 1
exit 0
