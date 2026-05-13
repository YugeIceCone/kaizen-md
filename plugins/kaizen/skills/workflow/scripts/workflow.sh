#!/usr/bin/env bash
# workflow.sh — state machine and hook handler for the /workflow skill.
#
# Subcommands:
#   init "<args>"        Parse free-form args, write .kaizen/workflow/state.json, print routine + first stage.
#   next                 Read state, print the next stage to run.
#   advance <stage> <msg> Mark stage complete, optionally store an artifact, print next stage.
#   artifact <key> <val> Record an artifact (e.g. plan_file=plans/2026-04-26-x.md).
#   status               Print current state in human-readable form.
#   reset                Delete state file.
#   stop-hook            Read Claude Code Stop event JSON from stdin; if a workflow is mid-flight,
#                        emit a system reminder that nudges the model to advance the next stage.
#                        Wire as a Stop hook in settings.json (see references/hooks-config.md).
#
# State file: $WORKFLOW_STATE_DIR/state.json (default: ./.kaizen/workflow/state.json post-v1.22).
# Pure-bash; no jq dependency. Handles concurrent reads safely; serial writes only.

set -euo pipefail

# v1.22.0+: state lives at <repo>/.kaizen/workflow/ (was <repo>/.workflow/).
# WORKFLOW_STATE_DIR override still wins. The migrator (migrate_paths.sh)
# moves legacy .workflow/ → .kaizen/workflow/ on plugin upgrade.
STATE_DIR="${WORKFLOW_STATE_DIR:-${CLAUDE_PROJECT_DIR:-.}/.kaizen/workflow}"
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
#
# v1.31.0+ — Stage sequences and verb-detection are sourced from
# skills/workflow/domain/routines.yaml via the application-layer loader.
# This eliminates the previous duplication (bash case statement, prose
# routines.md, schemas yamls, SKILL.md narrative all saying the same thing).
#
# Loader path resolution: workflow.sh is currently shipped from
# skills/workflow/scripts/ (legacy) but the loader sits under
# skills/workflow/application/. Phase 5 of the workflow-merge plan
# moves this script under skills/workflow/scripts/; until then we
# walk up to find the new application/ dir.

_kz_loader() {
  # Locate application/_loader.py — relative path stable across the merge.
  local d
  d="$(dirname "$0")/../../workflow/application/_loader.py"
  [ -f "$d" ] && { echo "$d"; return 0; }
  # Fallback: when this script has been moved under skills/workflow/scripts/
  d="$(dirname "$0")/../application/_loader.py"
  [ -f "$d" ] && { echo "$d"; return 0; }
  return 1
}

routine_stages() {
  # Delegate to the loader. Loader resolves unknown names via routines.yaml
  # `defaults.stages` (Phase B consolidation — yaml is the single source).
  # The baked-in fallback below only fires when the loader script itself is
  # unreachable, since we can't read the yaml without it.
  local loader; loader="$(_kz_loader)" || { echo "explore analyze create-plan create-tasks"; return; }
  python3 "$loader" stages "$1" 2>/dev/null || echo "explore analyze create-plan create-tasks"
}

detect_routine() {
  # Pick a routine from the prompt's verbs. Loader resolves no-match via
  # routines.yaml `defaults.routine`. Baked-in fallback only fires when the
  # loader script itself is unreachable.
  local loader; loader="$(_kz_loader)" || { echo "build-feature"; return; }
  python3 "$loader" detect "$1" 2>/dev/null || echo "build-feature"
}

verb_matched_explicitly() {
  # Returns 0 iff some hardcoded routine's trigger_words substring-match the prompt.
  local loader; loader="$(_kz_loader)" || return 1
  python3 "$loader" matched "$1" 2>/dev/null
}

# List available schemas across project/user/built-in tiers (one per line).
# Used by suggest_schemas at init time when the verb didn't match.
list_available_schemas() {
  local runner="$(dirname "$0")/workflow_runner.py"
  [ -f "$runner" ] || return 0
  python3 "$runner" list 2>/dev/null | awk '{print $1}' | sort -u
}

# Print a one-shot hint to stderr suggesting schema-driven routines. Called only
# when (a) no schema= flag was passed AND (b) the verb didn't match. Best-effort:
# silent if workflow_runner.py isn't reachable.
suggest_schemas() {
  local schemas
  schemas="$(list_available_schemas)"
  [ -z "$schemas" ] && return 0
  {
    echo "[workflow] no verb matched in prompt — defaulting to 'build-feature'."
    echo "[workflow] consider passing schema=<name>; available schemas:"
    echo "$schemas" | sed 's/^/  - /'
    echo "[workflow] run \`workflow.sh init \"<prompt> schema=<name>\"\` to use one."
  } >&2
}

# ---------- argparse (free-form prompt + key=value flags) ----------

parse_args() {
  # Sets globals: PROMPT, SKILL, SUBAGENT, AUTO, TDD, SCHEMA
  PROMPT=""
  SKILL=""
  SUBAGENT="no"
  AUTO="no"
  TDD="no"
  SCHEMA=""
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
      schema=*)   SCHEMA="${w#schema=}" ;;
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
  local stages_str
  if [ -n "$SCHEMA" ]; then
    # Schema-driven: topo-order stages via workflow_runner.py (v1.14.0+).
    local runner="$(dirname "$0")/workflow_runner.py"
    if [ ! -f "$runner" ]; then
      echo "[workflow] workflow_runner.py not found at $runner" >&2
      exit 1
    fi
    local stages_lines
    if ! stages_lines="$(python3 "$runner" stages "$SCHEMA" 2>&1)"; then
      echo "[workflow] failed to load schema '$SCHEMA':" >&2
      echo "$stages_lines" >&2
      exit 1
    fi
    stages_str="$(printf '%s' "$stages_lines" | tr '\n' ' ' | sed 's/ *$//')"
    routine="schema:$SCHEMA"
  else
    routine="$(detect_routine "$PROMPT")"
    stages_str="$(routine_stages "$routine")"
    # v1.30.0: if the verb didn't explicitly match, surface a schema-suggest
    # hint so the user knows declarative routines exist. Default behavior
    # (fall through to build-feature) is preserved — this is informational only.
    if ! verb_matched_explicitly "$PROMPT"; then
      suggest_schemas
    fi
  fi
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
  "schema_name": "$SCHEMA",
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
  # Usage: advance [--force] <stage> "<summary>"
  # When the active workflow is schema-driven AND the current stage declares
  # apply.gate.requires (a list of artifact-ids), every required artifact must
  # exist in state.artifacts before the stage can be advanced. --force bypasses
  # (with a warning) for cases where the agent legitimately needs to skip.
  local force=0
  if [ "$1" = "--force" ]; then force=1; shift; fi
  local stage="$1" msg="${2:-}"
  [ -f "$STATE_FILE" ] || { echo "[workflow] no active workflow"; exit 1; }
  local runner_path
  runner_path="$(dirname "$0")/workflow_runner.py"
  set +e
  WF_RUNNER="$runner_path" python3 - "$STATE_FILE" "$stage" "$msg" "$force" <<'PY'
import json, sys, datetime, os, pathlib, subprocess

path, stage, msg, force_s = sys.argv[1:]
force = force_s == "1"

with open(path) as f:
    state = json.load(f)

# Gate enforcement (schema-driven only). Text-only `gate:` strings are
# informational and not enforced — only `apply.gate.requires` lists are.
schema_name = state.get("schema_name", "")
routine = state.get("routine", "")
if schema_name and routine.startswith("schema:") and not force:
    runner = pathlib.Path(os.environ.get("WF_RUNNER", ""))
    if runner.exists():
        try:
            out = subprocess.check_output(
                ["python3", str(runner), "show", schema_name],
                stderr=subprocess.DEVNULL, text=True, timeout=10,
            )
            d = json.loads(out)
            requires = []
            for a in d.get("artifacts", []):
                if a.get("id") == stage:
                    # workflow_runner.py flattens `apply.gate.requires` to
                    # `a.requires` in the resolved JSON. Use the flattened
                    # form directly; the nested form is the YAML source-only.
                    requires = a.get("requires") or []
                    break
            if isinstance(requires, list) and requires:
                have = set((state.get("artifacts") or {}).keys())
                missing = [r for r in requires if r not in have]
                if missing:
                    print(f"[workflow] gate blocked: stage '{stage}' requires artifact(s) {missing}",
                          file=sys.stderr)
                    print(f"[workflow] record them first with `workflow.sh artifact <key> <value>` or pass --force",
                          file=sys.stderr)
                    sys.exit(4)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                json.JSONDecodeError, OSError):
            pass

now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
state.setdefault("completed", []).append({"stage": stage, "msg": msg, "at": now})
total = len(state.get("stages", []))
state["current"] = min(state.get("current", 0) + 1, total)
state["updated_at"] = now
if force:
    state.setdefault("gate_overrides", []).append({"stage": stage, "at": now})
with open(path, "w") as f:
    json.dump(state, f, indent=2)
nxt = state["stages"][state["current"]] if state["current"] < total else None
auto = state.get("auto_mode", "no")
sub = state.get("subagent_mode", "no")
rname = state.get("routine", "?")
if force:
    print(f"[workflow] gate force-bypassed for stage '{stage}'", file=sys.stderr)
if nxt is None:
    print(f"[workflow] all stages complete (routine: {rname})")
else:
    print(f"[workflow] {stage} -> {nxt}  (auto={auto}, subagent={sub})")
    print(f"next: {nxt}")
PY
  local rc=$?
  set -e
  if [ $rc -eq 4 ]; then
    return 1
  fi
  return $rc
}

_bash_advance_fallback() {
  # Used when python3 is unavailable. Less robust but functional for completed-list and current pointer.
  local stage="$1" msg="$2" new_idx="$3"
  json_set_scalar updated_at "$(now)"
  sed -i.bak "s/\"current\"[[:space:]]*:[[:space:]]*[0-9]\\+/\"current\": $new_idx/" "$STATE_FILE" && rm -f "$STATE_FILE.bak"
}

cmd_branch() {
  # v1.17.0: splice state.stages[current:] with the schema-declared branch_<key>.
  # Promotes the advisory Confidence-Score branching (v1.15.0) to runtime state mutation.
  local stage="$1" key="$2"
  [ -f "$STATE_FILE" ] || { echo "[workflow] no active workflow"; exit 1; }
  local runner="$(dirname "$0")/workflow_runner.py"
  [ -f "$runner" ] || { echo "[workflow] workflow_runner.py not found at $runner"; exit 1; }
  python3 - "$STATE_FILE" "$runner" "$stage" "$key" <<'PY'
import json, sys, subprocess, datetime
state_file, runner_path, stage, key = sys.argv[1:]
with open(state_file) as f: state = json.load(f)
schema_name = state.get('schema_name', '') or ''
if not schema_name:
    sys.exit(f"[workflow] branch only works for schema-driven workflows (current routine: {state.get('routine','?')})")
completed = state.get('completed', [])
if not completed or completed[-1].get('stage') != stage:
    last = completed[-1].get('stage') if completed else '(none)'
    sys.exit(f"[workflow] branch <stage> must match the just-completed stage; last completed: {last}")
result = subprocess.run(
    ['python3', runner_path, 'branches', schema_name, stage],
    capture_output=True, text=True,
)
if result.returncode != 0:
    sys.exit(f"[workflow] failed to load branches: {result.stderr.strip()}")
branches = json.loads(result.stdout)
if key not in branches:
    sys.exit(f"[workflow] unknown branch '{key}'; available: {sorted(branches.keys())}")
new_tail = branches[key]
state['stages'] = state['stages'][:state['current']] + new_tail
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
state['updated_at'] = now
state.setdefault('branch_decisions', []).append({
    'stage': stage,
    'key': key,
    'new_tail': new_tail,
    'at': now,
})
with open(state_file, 'w') as f: json.dump(state, f, indent=2)
nxt = state['stages'][state['current']] if state['current'] < len(state['stages']) else None
print(f"[workflow] branch {stage} -> {key}: tail rewritten to [{', '.join(new_tail)}]")
if nxt:
    print(f"next: {nxt}")
else:
    print(f"[workflow] tail is empty — routine complete after {stage}")
PY
}


cmd_artifact() {
  # Usage: artifact [--strict] <key> <value>
  # When the active workflow is schema-driven, validate <key> against
  # schema.artifacts[].id. Unknown keys warn (default) or error (--strict).
  # Hardcoded routines accept any key — schemas don't declare their keys.
  local strict=0
  if [ "$1" = "--strict" ]; then strict=1; shift; fi
  local key="$1" val="$2"
  if [ -z "$key" ]; then
    echo "[workflow] artifact: missing <key>" >&2
    exit 2
  fi
  local runner_path
  runner_path="$(dirname "$0")/workflow_runner.py"
  # set -e is on at script level; suspend it so we can read python's exit code
  # for strict-mode rejection (rc=3) without aborting the script.
  set +e
  WF_RUNNER="$runner_path" python3 - "$STATE_FILE" "$key" "$val" "$strict" <<'PY'
import json, sys, datetime, os, pathlib, subprocess

path, key, val, strict_s = sys.argv[1:]
strict = strict_s == "1"

with open(path) as f:
    state = json.load(f)

schema_name = state.get("schema_name", "")
routine = state.get("routine", "")
if schema_name and routine.startswith("schema:"):
    runner = pathlib.Path(os.environ.get("WF_RUNNER", ""))
    if runner.exists():
        try:
            out = subprocess.check_output(
                ["python3", str(runner), "show", schema_name],
                stderr=subprocess.DEVNULL, text=True, timeout=10,
            )
            d = json.loads(out)
            valid_ids = {a.get("id") for a in d.get("artifacts", []) if a.get("id")}
            if valid_ids and key not in valid_ids:
                msg = f"artifact key '{key}' not in schema '{schema_name}' (valid: {sorted(valid_ids)})"
                if strict:
                    print(f"[workflow] {msg}", file=sys.stderr)
                    sys.exit(3)
                print(f"[workflow] warning: {msg}", file=sys.stderr)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                json.JSONDecodeError, OSError):
            pass

state.setdefault("artifacts", {})[key] = val
state["updated_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
with open(path, "w") as f:
    json.dump(state, f, indent=2)
PY
  local rc=$?
  set -e
  if [ $rc -eq 3 ]; then
    echo "[workflow] strict mode: artifact write rejected" >&2
    return 1
  fi
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
  # to .kaizen/workflow/snapshot.md so PostCompact can re-inject it.
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
  local schema
  schema="$(json_get schema_name)"
  [ -n "$schema" ] && echo "schema:   $schema"
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
  branch)        shift; cmd_branch "$@" ;;
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
  init "<prompt> [skill=NAME] [subagent=no|yes|full] [auto=no|yes] [tdd=no|yes] [schema=NAME]"
  next
  advance <stage> "<one-line result>"
  artifact <key> <value>
  branch <stage> <key>            (v1.17.0+) splice state.stages[current:] with schema's
                                  branch_<key> for the just-completed <stage>. Requires
                                  schema-driven workflow (schema=NAME passed at init).
                                  Inspect available keys via:
                                    /kaizen:schema branches <name> <stage>
  dispatch <agent_id> <stage>     (record subagent assignment for SubagentStop auto-advance)
  status
  reset

  schema=NAME (v1.14.0+)          opt-in to a declarative schema-driven routine.
                                  Stages come from <plugin>/schemas/<name>/schema.yaml
                                  (or .kaizen/workflow/schemas/<name>/, or ~/.claude/.kaizen/schemas/<name>/).
                                  Inspect via: python3 workflow_runner.py list|show|validate|stages

hook handlers (invoked from settings.json, read stdin, emit JSON):
  stop-hook                       (Stop event — drives auto=yes chaining)
  subagent-stop                   (SubagentStop event — auto-advances on completion)
  pre-compact                     (PreCompact event — snapshots state to .kaizen/workflow/snapshot.md)
  post-compact                    (PostCompact event — re-injects snapshot as context)

state: $STATE_FILE
USAGE
    exit 2
    ;;
esac
