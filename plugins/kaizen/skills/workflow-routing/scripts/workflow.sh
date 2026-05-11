#!/usr/bin/env bash
# workflow.sh — state machine and hook handler for the /workflow skill.
#
# Subcommands:
#   init "<args>"        Parse free-form args, write .workflow/state.json, print routine + first stage.
#   next                 Read state, print the next stage to run.
#   advance <stage> <msg> Mark stage complete, optionally store an artifact, print next stage.
#   artifact <key> <val> Record an artifact (e.g. plan_file=plans/2026-04-26-x.md).
#   status               Print current state in human-readable form.
#   reset                Delete state file.
#   stop-hook            Read Claude Code Stop event JSON from stdin; if a workflow is mid-flight,
#                        emit a system reminder that nudges the model to advance the next stage.
#                        Wire as a Stop hook in settings.json (see references/hooks-config.md).
#
# State file: $WORKFLOW_STATE_DIR/state.json (default: ./.workflow/state.json).
# Pure-bash; no jq dependency. Handles concurrent reads safely; serial writes only.

set -euo pipefail

STATE_DIR="${WORKFLOW_STATE_DIR:-${CLAUDE_PROJECT_DIR:-.}/.workflow}"
STATE_FILE="$STATE_DIR/state.json"
mkdir -p "$STATE_DIR"

# ---------- helpers ----------

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

json_get() {
  # json_get <key> [file]  — extract a top-level scalar string field. Pure bash.
  local key="$1"
  local file="${2:-$STATE_FILE}"
  [ -f "$file" ] || { echo ""; return; }
  sed -n "s/.*\"$key\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p" "$file" | head -n1
}

json_get_array() {
  # json_get_array <key> [file] — extract a top-level string array, one element per line.
  local key="$1"
  local file="${2:-$STATE_FILE}"
  [ -f "$file" ] || return
  sed -n "/\"$key\"[[:space:]]*:[[:space:]]*\\[/,/\\]/p" "$file" \
    | tr -d '\n' \
    | sed "s/.*\"$key\"[[:space:]]*:[[:space:]]*\\[\\([^]]*\\)\\].*/\\1/" \
    | grep -oE '"[^"]*"' \
    | sed 's/^"//;s/"$//'
}

json_set_scalar() {
  # json_set_scalar <key> <value> [file]
  local key="$1" val="$2" file="${3:-$STATE_FILE}"
  local esc
  esc="$(printf '%s' "$val" | sed 's/[\\/&"]/\\&/g')"
  if grep -q "\"$key\"" "$file"; then
    sed -i.bak "s|\"$key\"[[:space:]]*:[[:space:]]*\"[^\"]*\"|\"$key\": \"$esc\"|" "$file" && rm -f "$file.bak"
  else
    sed -i.bak "s|^}|, \"$key\": \"$esc\"\n}|" "$file" && rm -f "$file.bak"
  fi
}

# ---------- routines ----------

# Stage sequences keyed by routine name. Tab-separated for portability.
routine_stages() {
  case "$1" in
    audit)         echo "explore detect-stack research audit analyze review create-plan create-tasks" ;;
    build-feature) echo "explore detect-stack research analyze create-plan create-tasks execute-tasks simplify review report" ;;
    fix-bug)       echo "debug analyze fix simplify review validate report" ;;
    refactor)      echo "explore analyze create-plan create-tasks execute-tasks simplify review validate" ;;
    migrate)       echo "research explore analyze create-plan create-tasks execute-tasks simplify review validate" ;;
    harden)        echo "explore audit analyze create-plan create-tasks execute-tasks simplify review validate" ;;
    batch-migrate) echo "research explore detect-stack analyze batch-fanout report" ;;
    custom)        echo "" ;;
    *)             echo "explore analyze create-plan create-tasks" ;;
  esac
}

detect_routine() {
  # Pick a routine from the prompt's verbs.
  local p
  p="$(echo "$1" | tr '[:upper:]' '[:lower:]')"
  case "$p" in
    *audit*|*"health check"*|*"find issues"*) echo "audit" ;;
    *"fix "*|*bug*|*broken*|*"flaky test"*) echo "fix-bug" ;;
    *refactor*|*"clean up"*|*restructure*) echo "refactor" ;;
    *"batch migrate"*|*"batch refactor"*|*"across all"*|*"every file"*|*"sweep "*) echo "batch-migrate" ;;
    *migrate*|*upgrade*|*"port to"*) echo "migrate" ;;
    *harden*|*secure*|*"threat model"*) echo "harden" ;;
    *build*|*add*|*implement*|*create*|*new*) echo "build-feature" ;;
    *) echo "build-feature" ;;
  esac
}

# ---------- argparse (free-form prompt + key=value flags) ----------

parse_args() {
  # Sets globals: PROMPT, SKILL, SUBAGENT, AUTO
  PROMPT=""
  SKILL=""
  SUBAGENT="no"
  AUTO="no"
  TDD="no"
  local raw="$1"
  local words=()
  # shellcheck disable=SC2206
  read -r -a words <<<"$raw"
  local prompt_parts=()
  for w in "${words[@]}"; do
    case "$w" in
      skill=*)    SKILL="${w#skill=}" ;;
      subagent=*) SUBAGENT="${w#subagent=}" ;;
      auto=*)     AUTO="${w#auto=}" ;;
      tdd=*)      TDD="${w#tdd=}" ;;
      *)          prompt_parts+=("$w") ;;
    esac
  done
  PROMPT="${prompt_parts[*]}"
  case "$SUBAGENT" in no|yes|full) ;; *) SUBAGENT="no" ;; esac
  case "$AUTO" in no|yes) ;; *) AUTO="no" ;; esac
  case "$TDD" in no|yes) ;; *) TDD="no" ;; esac
}

# ---------- subcommands ----------

cmd_init() {
  parse_args "${1:-}"
  local routine
  routine="$(detect_routine "$PROMPT")"
  local stages_str
  stages_str="$(routine_stages "$routine")"
  if [ -n "$SKILL" ]; then
    # User pinned a starting stage — drop earlier stages from the sequence.
    local trimmed=""
    local found=0
    for s in $stages_str; do
      if [ "$found" -eq 1 ] || [ "$s" = "$SKILL" ]; then
        trimmed="${trimmed}${s} "
        found=1
      fi
    done
    [ "$found" -eq 1 ] && stages_str="${trimmed% }"
  fi

  local id
  id="wf-$(date -u +%Y%m%d-%H%M%S)"

  local stages_json="["
  local first=1
  for s in $stages_str; do
    [ "$first" -eq 0 ] && stages_json+=", "
    stages_json+="\"$s\""
    first=0
  done
  stages_json+="]"

  local prompt_esc
  prompt_esc="$(printf '%s' "$PROMPT" | sed 's/\\/\\\\/g; s/"/\\"/g')"

  cat > "$STATE_FILE" <<EOF
{
  "id": "$id",
  "prompt": "$prompt_esc",
  "routine": "$routine",
  "stages": $stages_json,
  "current": 0,
  "completed": [],
  "subagent_mode": "$SUBAGENT",
  "auto_mode": "$AUTO",
  "tdd_mode": "$TDD",
  "artifacts": {},
  "started_at": "$(now)",
  "updated_at": "$(now)"
}
EOF

  local first_stage="${stages_str%% *}"
  cat <<EOF
[workflow] initialized
  id:          $id
  routine:     $routine
  stages:      $stages_str
  subagent:    $SUBAGENT
  auto:        $AUTO
  state file:  $STATE_FILE
  next stage:  $first_stage

Run the '$first_stage' skill now. When it finishes, run:
  $(realpath "$0" 2>/dev/null || echo "$0") advance $first_stage "<one-line result summary>"
EOF
}

current_stage() {
  [ -f "$STATE_FILE" ] || return 1
  python3 - "$STATE_FILE" <<'PY' 2>/dev/null
import json, sys
with open(sys.argv[1]) as f: state = json.load(f)
stages = state.get("stages", [])
i = state.get("current", 0)
if 0 <= i < len(stages):
    print(stages[i])
    sys.exit(0)
sys.exit(1)
PY
}

cmd_next() {
  if ! current_stage; then echo "[workflow] no active workflow"; exit 1; fi
}

cmd_advance() {
  local stage="$1" msg="${2:-}"
  [ -f "$STATE_FILE" ] || { echo "[workflow] no active workflow"; exit 1; }
  python3 - "$STATE_FILE" "$stage" "$msg" <<'PY'
import json, sys, datetime
path, stage, msg = sys.argv[1:]
with open(path) as f: state = json.load(f)
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
state.setdefault("completed", []).append({"stage": stage, "msg": msg, "at": now})
total = len(state.get("stages", []))
state["current"] = min(state.get("current", 0) + 1, total)
state["updated_at"] = now
with open(path, "w") as f: json.dump(state, f, indent=2)
nxt = state["stages"][state["current"]] if state["current"] < total else None
auto = state.get("auto_mode", "no")
sub = state.get("subagent_mode", "no")
routine = state.get("routine", "?")
if nxt is None:
    print(f"[workflow] all stages complete (routine: {routine})")
else:
    print(f"[workflow] {stage} -> {nxt}  (auto={auto}, subagent={sub})")
    print(f"next: {nxt}")
PY
}

_bash_advance_fallback() {
  # Used when python3 is unavailable. Less robust but functional for completed-list and current pointer.
  local stage="$1" msg="$2" new_idx="$3"
  json_set_scalar updated_at "$(now)"
  sed -i.bak "s/\"current\"[[:space:]]*:[[:space:]]*[0-9]\\+/\"current\": $new_idx/" "$STATE_FILE" && rm -f "$STATE_FILE.bak"
}

cmd_artifact() {
  local key="$1" val="$2"
  python3 - "$STATE_FILE" "$key" "$val" <<'PY'
import json, sys, datetime
path, key, val = sys.argv[1:]
with open(path) as f: state = json.load(f)
state.setdefault("artifacts", {})[key] = val
state["updated_at"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
with open(path, "w") as f: json.dump(state, f, indent=2)
PY
  echo "[workflow] artifact: $key=$val"
}

cmd_dispatch() {
  # Record an agent_id -> stage mapping when dispatching a subagent.
  # Used by SubagentStop handler to know which stage to advance.
  local agent_id="$1" stage="$2"
  [ -f "$STATE_FILE" ] || { echo "[workflow] no active workflow"; exit 1; }
  python3 - "$STATE_FILE" "$agent_id" "$stage" <<'PY'
import json, sys, datetime
path, agent_id, stage = sys.argv[1:]
with open(path) as f: state = json.load(f)
state.setdefault("subagents", {})[agent_id] = stage
state["updated_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
with open(path, "w") as f: json.dump(state, f, indent=2)
PY
  echo "[workflow] dispatch: $agent_id -> $stage"
}

cmd_subagent_stop() {
  # SubagentStop hook handler. Reads JSON from stdin, looks up the agent's
  # stage in state.subagents, and auto-advances if found and stop_reason=completed.
  # Emits {} if no mapping (this subagent wasn't part of the workflow).
  [ -f "$STATE_FILE" ] || { echo '{}'; exit 0; }
  local input
  input="$(cat)"
  python3 - "$STATE_FILE" "$input" <<'PY'
import json, sys, datetime
path, raw = sys.argv[1:]
try:
    payload = json.loads(raw)
except Exception:
    print("{}"); sys.exit(0)
agent_id = payload.get("agent_id", "")
stop_reason = payload.get("stop_reason", "")
with open(path) as f: state = json.load(f)
mapping = state.get("subagents", {})
stage = mapping.get(agent_id)
if not stage:
    print("{}"); sys.exit(0)
# Only auto-advance on clean completion. cancelled/failed needs human eyes.
if stop_reason != "completed":
    print(json.dumps({"systemMessage": f"Workflow subagent for stage '{stage}' did not complete cleanly (stop_reason={stop_reason}). Stage left open; surface to user."}))
    sys.exit(0)
# Find current index and advance if this stage is the active one.
stages = state.get("stages", [])
idx = state.get("current", 0)
if 0 <= idx < len(stages) and stages[idx] == stage:
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state.setdefault("completed", []).append({"stage": stage, "msg": f"auto-advanced via SubagentStop ({agent_id})", "at": now})
    state["current"] = min(idx + 1, len(stages))
    state["updated_at"] = now
    # Drop the agent_id from the mapping; it's done.
    state.get("subagents", {}).pop(agent_id, None)
    with open(path, "w") as f: json.dump(state, f, indent=2)
    nxt = state["stages"][state["current"]] if state["current"] < len(stages) else None
    if nxt:
        msg = f"Workflow auto-advanced: {stage} -> {nxt}. Run the '{nxt}' skill next."
    else:
        msg = f"Workflow auto-advanced: {stage} -> (complete). Routine '{state.get('routine','?')}' done."
    print(json.dumps({"systemMessage": msg}))
else:
    # Stage was completed out of order; leave state alone, just surface it.
    print(json.dumps({"systemMessage": f"Subagent {agent_id} (mapped to stage '{stage}') returned but workflow current stage is '{stages[idx] if 0<=idx<len(stages) else None}'. Not auto-advancing."}))
PY
}

cmd_pre_compact() {
  # PreCompact hook: snapshot the workflow state + the next-stage instruction
  # to .workflow/snapshot.md so PostCompact can re-inject it.
  [ -f "$STATE_FILE" ] || { echo '{}'; exit 0; }
  python3 - "$STATE_FILE" "$STATE_DIR/snapshot.md" <<'PY'
import json, sys, datetime
state_path, snap_path = sys.argv[1:]
with open(state_path) as f: state = json.load(f)
stages = state.get("stages", [])
i = state.get("current", 0)
nxt = stages[i] if 0 <= i < len(stages) else None
done = ", ".join(c.get("stage","?") for c in state.get("completed",[])) or "(none)"
arts = state.get("artifacts", {})
art_lines = "\n".join(f"- {k}: {v}" for k,v in arts.items()) or "(none)"
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
snap = f"""# Workflow snapshot (PreCompact {now})

- routine: {state.get('routine','?')}
- prompt: {state.get('prompt','')}
- subagent mode: {state.get('subagent_mode','no')}
- auto mode: {state.get('auto_mode','no')}
- stages: {' '.join(stages)}
- next stage: {nxt or '(complete)'}
- completed: {done}
- artifacts:
{art_lines}
- state file: {state_path}

To resume after compaction:
1. bash $HOME/.claude/skills/workflow/scripts/workflow.sh status
2. Run the next stage skill.
3. bash $HOME/.claude/skills/workflow/scripts/workflow.sh advance <stage> "<result>"
"""
with open(snap_path, "w") as f: f.write(snap)
PY
  # Don't block compaction; just snapshot.
  echo '{}'
}

cmd_post_compact() {
  # PostCompact hook: read the snapshot (if any) and re-inject as additionalContext.
  local snap="$STATE_DIR/snapshot.md"
  [ -f "$snap" ] || { echo '{}'; exit 0; }
  python3 - "$snap" <<'PY'
import json, sys
with open(sys.argv[1]) as f: body = f.read()
print(json.dumps({
  "hookSpecificOutput": {
    "hookEventName": "PostCompact",
    "additionalContext": body
  }
}))
PY
}

cmd_status() {
  [ -f "$STATE_FILE" ] || { echo "[workflow] no active workflow"; exit 1; }
  echo "id:       $(json_get id)"
  echo "routine:  $(json_get routine)"
  echo "subagent: $(json_get subagent_mode)"
  echo "auto:     $(json_get auto_mode)"
  echo "tdd:      $(json_get tdd_mode)"
  echo "stages:   $(json_get_array stages | tr '\n' ' ')"
  echo "current:  $(current_stage 2>/dev/null || echo "(complete)")"
  echo "updated:  $(json_get updated_at)"
}

cmd_reset() {
  rm -f "$STATE_FILE"
  echo "[workflow] state cleared"
}

cmd_stop_hook() {
  # Stop hook: invoked when the model finishes its turn.
  # If a workflow is mid-flight and auto=yes, emit a JSON response telling Claude
  # to keep advancing. If auto=no or the workflow is already complete, no-op.
  [ -f "$STATE_FILE" ] || { echo '{}'; exit 0; }
  local auto next
  auto="$(json_get auto_mode)"
  next="$(current_stage 2>/dev/null || echo "")"
  if [ "$auto" != "yes" ] || [ -z "$next" ]; then
    echo '{}'
    exit 0
  fi
  # Emit a hookSpecificOutput object asking Claude to continue.
  cat <<EOF
{
  "decision": "block",
  "reason": "Workflow auto-mode is active. Next stage: '$next'. Do not stop until the workflow is complete or blocked. Run the '$next' skill, then update state with: workflow.sh advance $next <result>."
}
EOF
}

# ---------- entrypoint ----------

case "${1:-}" in
  init)          shift; cmd_init "$*" ;;
  next)          cmd_next ;;
  advance)       shift; cmd_advance "$@" ;;
  artifact)      shift; cmd_artifact "$@" ;;
  dispatch)      shift; cmd_dispatch "$@" ;;
  status)        cmd_status ;;
  reset)         cmd_reset ;;
  stop-hook)     cmd_stop_hook ;;
  subagent-stop) cmd_subagent_stop ;;
  pre-compact)   cmd_pre_compact ;;
  post-compact)  cmd_post_compact ;;
  *)
    cat <<USAGE
usage: workflow.sh <subcommand> [args]

subcommands:
  init "<prompt> [skill=NAME] [subagent=no|yes|full] [auto=no|yes] [tdd=no|yes]"
  next
  advance <stage> "<one-line result>"
  artifact <key> <value>
  dispatch <agent_id> <stage>     (record subagent assignment for SubagentStop auto-advance)
  status
  reset

hook handlers (invoked from settings.json, read stdin, emit JSON):
  stop-hook                       (Stop event — drives auto=yes chaining)
  subagent-stop                   (SubagentStop event — auto-advances on completion)
  pre-compact                     (PreCompact event — snapshots state to .workflow/snapshot.md)
  post-compact                    (PostCompact event — re-injects snapshot as context)

state: $STATE_FILE
USAGE
    exit 2
    ;;
esac
