#!/usr/bin/env bash
# kaizen session-inject-context.sh — project-context injector.
#
# Ported from ~/.claude/scripts/inject-context.sh (user-global, retired
# 2026-05-17) so kaizen owns its slice end-to-end. Two modernizations vs
# the original:
#   1. Workflow state path: .workflow/ → .kaizen/workflow/ (with
#      legacy fallback so consumer repos on the old layout still work)
#   2. Handoff collector: filesystem lookup → `kaizen-handoff latest
#      --json` (uses the in-plugin handoff store)
#
# Wired into hooks.json for both SessionStart + UserPromptSubmit. Both
# event types share the same JSON payload schema (additionalContext);
# the subcommand only flips the `hookEventName` field for Claude Code
# routing.
#
# Bypass: KAIZEN_INJECT_CONTEXT_DISABLE=1

set -uo pipefail
# Note: deliberately not using -e because individual `[ ]` tests that return
# false (e.g. "no unpushed commits") would otherwise abort the whole script.

# Bypass-knob iron-law
[ "${KAIZEN_INJECT_CONTEXT_DISABLE:-}" = "1" ] && { echo "{}"; exit 0; }

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo "{}"; exit 0; }

EVENT="${1:-session}"
case "$EVENT" in
  session) HOOK_EVENT="SessionStart" ;;
  prompt)  HOOK_EVENT="UserPromptSubmit" ;;
  *)       HOOK_EVENT="SessionStart" ;;
esac

# Trace firing (iron-law: observability)
STDIN_JSON=""
if [ ! -t 0 ]; then
  STDIN_JSON="$(cat 2>/dev/null || true)"
fi
printf '%s' "$STDIN_JSON" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" "$HOOK_EVENT"

# Read source (startup|resume|clear|compact) for verbosity decisions.
SOURCE=""
if [ -n "$STDIN_JSON" ]; then
  SOURCE="$(printf '%s' "$STDIN_JSON" | python3 -c 'import json,sys
try: d=json.load(sys.stdin); print(d.get("source",""))
except: print("")' 2>/dev/null || true)"
fi
export SOURCE

ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
emit_empty() { echo '{}'; exit 0; }
[ -d "$ROOT" ] || emit_empty

# ---------- collectors ----------

# Workflow state — post-v1.22.0 canonical at .kaizen/workflow/, legacy
# at .workflow/ still honored for repos mid-migration.
collect_workflow() {
  local state
  if [ -f "$ROOT/.kaizen/workflow/state.json" ]; then
    state="$ROOT/.kaizen/workflow/state.json"
  elif [ -f "$ROOT/.workflow/state.json" ]; then
    state="$ROOT/.workflow/state.json"
  else
    return
  fi
  local snap_dir snap
  snap_dir="$(dirname "$state")"
  snap="$snap_dir/snapshot.md"
  # If we're recovering from a compact, prefer snapshot.md (more detail).
  if [ "${SOURCE:-}" = "compact" ] && [ -f "$snap" ]; then
    echo "## Active /workflow run (recovered from compaction)"
    cat "$snap"
    return
  fi
  python3 - "$state" "${SOURCE:-}" 2>/dev/null <<'PY' || true
import json, sys
try:
    with open(sys.argv[1]) as f: s = json.load(f)
except Exception:
    sys.exit(0)
source = sys.argv[2] if len(sys.argv) > 2 else ""
stages = s.get("stages", [])
i = s.get("current", 0)
# Suppress completed runs — current >= len(stages) means all stages
# done; the "next stage: (complete)" line is pure noise per-prompt.
# Use kaizen:status or read the state.json directly to view history.
if stages and i >= len(stages):
    sys.exit(0)
nxt = stages[i] if 0 <= i < len(stages) else None
completed = s.get("completed", [])
done = ", ".join(c.get("stage", "?") for c in completed) or "(none)"
arts = s.get("artifacts", {})
art_lines = "\n".join(f"  - {k}: {v}" for k, v in arts.items()) or "  (none)"
print("## Active /workflow run")
print(f"- routine: {s.get('routine', '?')}")
print(f"- next stage: {nxt or '(complete)'}")
print(f"- completed: {done}")
print(f"- subagent mode: {s.get('subagent_mode', 'no')}")
print(f"- auto mode: {s.get('auto_mode', 'no')}")
print(f"- prompt: {s.get('prompt', '')[:140]}")
print(f"- artifacts:\n{art_lines}")
print(f"- state file: {sys.argv[1]}")
if source in ("resume", "clear") and completed:
    print("- completed history:")
    for c in completed[-10:]:
        print(f"  - {c.get('at','?')} {c.get('stage','?')}: {c.get('msg','')[:120]}")
print("- to advance: kaizen workflow advance <stage> \"<result>\"")
PY
}

collect_plans() {
  local plans_dir="$ROOT/plans"
  [ -d "$plans_dir" ] || return
  local count
  count=$(find "$plans_dir" -maxdepth 1 -type f -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
  [ "$count" -eq 0 ] && return
  echo "## Plans in this project"
  # 5 most-recently modified plans. Use BSD-safe stat (no -printf — banned).
  find "$plans_dir" -maxdepth 1 -type f -name '*.md' 2>/dev/null | while read -r p; do
    local mtime
    mtime=$(stat -c %Y "$p" 2>/dev/null || stat -f %m "$p" 2>/dev/null || echo 0)
    echo "$mtime $p"
  done | sort -nr | head -5 | awk '{print $2}' | while read -r p; do
    local rel status
    rel="${p#$ROOT/}"
    status=$(grep -m1 -E '^- Status:' "$p" 2>/dev/null | sed 's/^- Status:[[:space:]]*//' || true)
    [ -z "$status" ] && status=$(grep -m1 -E '^Status:' "$p" 2>/dev/null | sed 's/^Status:[[:space:]]*//' || true)
    [ -z "$status" ] && status="(no status field)"
    echo "- \`$rel\` — $status"
  done
}

# Handoff — use the kaizen handoff store via `kaizen-handoff latest --json`.
# Falls back to legacy filesystem locations for projects that haven't
# adopted the store yet.
collect_handoff() {
  # Prefer kaizen-handoff (post-Phase-D it emits the canonical envelope).
  if command -v kaizen-handoff >/dev/null 2>&1; then
    local h
    h=$(kaizen-handoff latest --json 2>/dev/null | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    h = d.get("data", {}).get("handoff")
    if h:
        print(h.get("file_path", ""), h.get("session_id", ""),
              h.get("created_at", ""), h.get("status", ""), sep="|")
except Exception:
    pass
' 2>/dev/null || true)
    if [ -n "$h" ]; then
      local fp sid created status
      IFS='|' read -r fp sid created status <<< "$h"
      [ -n "$fp" ] && [ -f "$fp" ] || return
      echo "## Handoff document (kaizen store)"
      echo "- session: \`$sid\` (status: $status, created: $created)"
      echo "- file: \`$fp\`"
      echo "- resume: \`/kaizen:handoff resume\`"
      return
    fi
  fi
  # Legacy filesystem fallback
  local f
  for f in "$ROOT/.handoff.md" "$ROOT/HANDOFF.md" "$ROOT/.claude/handoff.md"; do
    [ -f "$f" ] || continue
    local age_days
    age_days=$(( ( $(date +%s) - $(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null || echo 0) ) / 86400 ))
    echo "## Handoff document (legacy)"
    echo "- \`${f#$ROOT/}\` (age: ${age_days}d) — read this before starting work."
    return
  done
}

collect_git() {
  command -v git >/dev/null 2>&1 || return
  git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 || return
  local branch dirty unpushed
  branch=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
  dirty=$(git -C "$ROOT" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  unpushed=$(git -C "$ROOT" log '@{u}..' --oneline 2>/dev/null | wc -l | tr -d ' ')
  echo "## Git state"
  echo "- branch: \`$branch\`"
  [ "$dirty" -gt 0 ] && echo "- working tree: $dirty modified/untracked file(s)"
  [ "$unpushed" -gt 0 ] && echo "- unpushed commits: $unpushed"
}

collect_claude_md() {
  local found=()
  for f in CLAUDE.md WORKFLOW.md RULES.md .claude/CLAUDE.md; do
    [ -f "$ROOT/$f" ] && found+=("$f")
  done
  [ ${#found[@]} -eq 0 ] && return
  echo "## Project memory files"
  for f in "${found[@]}"; do echo "- \`$f\` is present — already loaded."; done
}

# ---------- assemble ----------

BODY=""
append() { local s; s="$(eval "$1")"; if [ -n "$s" ]; then BODY+="$s"$'\n\n'; fi; }

# Token-cost optimization: UserPromptSubmit fires every turn, but the
# stable sections (workflow / handoff / plans / project-memory)
# don't change between prompts — SessionStart already injected them
# once at startup (or after compact). Only the git state is volatile
# turn-to-turn. So on `prompt` we emit just git, saving ~1.4KB per
# user prompt × N turns per session.
if [ "$EVENT" = "prompt" ]; then
    append collect_git
else
    append collect_workflow
    append collect_handoff
    append collect_plans
    append collect_git
    append collect_claude_md
fi

BODY="${BODY%$'\n\n'}"
[ -z "$BODY" ] && emit_empty

python3 - "$HOOK_EVENT" "$BODY" <<'PY'
import json, sys
event, body = sys.argv[1], sys.argv[2]
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": event,
        "additionalContext": body
    }
}))
PY
