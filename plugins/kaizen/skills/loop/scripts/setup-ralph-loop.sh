#!/bin/bash

# Ralph Loop Setup Script
# Creates loop state for a cross-CLI Stop hook (Claude Code + Codex).
# State is written to .kaizen/loop.state.md so the same file is consumed by
# whichever Stop hook fires (hooks/claude/stop-ralph.sh or hooks/codex/stop-ralph.sh).

set -euo pipefail

PROMPT_PARTS=()
MAX_ITERATIONS=0
COMPLETION_PROMISE="null"
ITEMS=()        # repeated --item "desc|verify" pairs (verify optional, "|" separator)
LEDGER_FILE=""  # --ledger <file>: read full JSON ledger from a file

die() {
  echo "Error: $*" >&2
  exit 1
}

escape_yaml_double_quoted() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

while [[ $# -gt 0 ]]; do
  case $1 in
    -h|--help)
      cat << 'HELP_EOF'
Ralph Loop - cross-CLI self-correcting Stop-hook loop (CC + Codex)

USAGE:
  /ralph-loop [PROMPT...] [OPTIONS]

ARGUMENTS:
  PROMPT...    Initial prompt to start the loop (can be multiple words without quotes)

OPTIONS:
  --its <n>                      Maximum iterations before auto-stop (default: unlimited).
                                 Long form: --max-iterations
  --promise '<text>'             Promise phrase (USE QUOTES for multi-word).
                                 Long form: --completion-promise
  --item 'desc|verify'           Add a ledger item (repeatable). verify is a bash
                                 command run by the Stop hook; item moves to
                                 completed only when verify exits 0. Omit the
                                 verify part (and the "|") for a trust-based item.
  --ledger <file>                Read structured ledger from a JSON file. The file
                                 must contain {"pending":[{"desc":..,"verify":..}...]}.
  -h, --help                     Show this help message

DESCRIPTION:
  Writes .kaizen/loop.state.md for the Ralph Stop hook.
  The Stop hook reads that file and continues the session with the same
  prompt until a completion promise matches or the iteration limit is reached.

  To signal completion, you must output: <promise>YOUR_PHRASE</promise>

EXAMPLES:
  /ralph-loop Build a todo API --promise 'DONE' --its 20
  /ralph-loop --its 10 Fix the auth bug
  /ralph-loop Refactor cache layer  (runs forever — discouraged)
  /ralph-loop --promise 'TASK COMPLETE' Create a REST API

STOPPING:
  Use /cancel-ralph to remove the state file manually, or let the hook stop
  after --its or --promise.

MONITORING:
  # View current iteration:
  grep '^iteration:' .kaizen/loop.state.md

  # View full state:
  head -10 .kaizen/loop.state.md
HELP_EOF
      exit 0
      ;;
    --its|--max-iterations)
      if [[ -z "${2:-}" ]]; then
        die "$1 requires a number"
      fi
      if ! [[ "$2" =~ ^[0-9]+$ ]]; then
        die "$1 must be a non-negative integer"
      fi
      MAX_ITERATIONS="$2"
      shift 2
      ;;
    --promise|--completion-promise)
      if [[ -z "${2:-}" ]]; then
        die "$1 requires text"
      fi
      COMPLETION_PROMISE="$2"
      shift 2
      ;;
    --item)
      if [[ -z "${2:-}" ]]; then
        die "--item requires 'desc|verify' (verify part optional)"
      fi
      ITEMS+=("$2")
      shift 2
      ;;
    --ledger)
      if [[ -z "${2:-}" ]]; then
        die "--ledger requires a file path"
      fi
      LEDGER_FILE="$2"
      shift 2
      ;;
    *)
      PROMPT_PARTS+=("$1")
      shift
      ;;
  esac
done

PROMPT="${PROMPT_PARTS[*]:-}"

# Ralph brainstorm #6 — implicit ledger from `- [ ]` checkboxes in the
# prompt. Only kicks in when no explicit --item / --ledger was given.
# Each unchecked `- [ ]` line becomes one trust-based pending item
# (verify=null); checked `- [x]` / `- [X]` lines are skipped (already
# done). When at least one unchecked item is found, ITEMS is populated
# and PROMPT is cleared so the ledger-mode body is built.
if [[ -z "$LEDGER_FILE" ]] && [[ ${#ITEMS[@]} -eq 0 ]] && [[ -n "$PROMPT" ]]; then
  IMPLICIT_OUT=$(python3 - <<PY
import re, sys
text = """$PROMPT"""
descs = []
for line in text.splitlines():
    m = re.match(r"^\s*-\s*\[\s*\]\s*(.+?)\s*$", line)
    if m:
        descs.append(m.group(1))
for d in descs:
    print(d)
PY
)
  if [[ -n "$IMPLICIT_OUT" ]]; then
    while IFS= read -r line; do
      [[ -n "$line" ]] && ITEMS+=("$line")
    done <<< "$IMPLICIT_OUT"
    PROMPT=""
    echo "[setup-ralph-loop] seeded ${#ITEMS[@]} implicit item(s) from \`- [ ]\` checkboxes in prompt" >&2
  fi
fi

# Ralph brainstorm #4 — workflow-config default for --its when not given.
# Reads `loop.max_iterations` from the merged workflow config (project ←
# global). Silent skip when the helper or config is missing. KISS lookup:
# resolve the workflow_config.py path relative to THIS script.
if [[ "$MAX_ITERATIONS" -eq 0 ]]; then
  _SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  WC_PY="$_SCRIPT_DIR/../../workflow/scripts/workflow_config.py"
  if [[ -f "$WC_PY" ]] && command -v python3 >/dev/null 2>&1; then
    DEFAULT_ITS=$(python3 "$WC_PY" get-key loop.max_iterations 2>/dev/null)
    if [[ -n "$DEFAULT_ITS" ]] && [[ "$DEFAULT_ITS" =~ ^[0-9]+$ ]] \
            && [[ "$DEFAULT_ITS" -gt 0 ]]; then
      MAX_ITERATIONS="$DEFAULT_ITS"
      echo "[setup-ralph-loop] --its defaulted to $MAX_ITERATIONS (from workflow-config loop.max_iterations)" >&2
    fi
  fi
fi

# Validate inputs: must have at least ONE source of work (prompt, items, or ledger file).
if [[ -z "$PROMPT" ]] && [[ ${#ITEMS[@]} -eq 0 ]] && [[ -z "$LEDGER_FILE" ]]; then
  die "No prompt, --item, or --ledger provided"
fi

# Auto-load file-path-as-prompt. When the bare PROMPT is a single token
# that happens to be an existing readable file path (e.g.
#   /kaizen:loop handoff.md --its 30
# ), expand it to the file's contents. This prevents the 2026-05-14 mistake
# where the literal string "handoff.md" became the iteration prompt.
if [[ -n "$PROMPT" ]] && [[ ${#PROMPT_PARTS[@]} -eq 1 ]] \
        && [[ -z "$LEDGER_FILE" ]] && [[ ${#ITEMS[@]} -eq 0 ]] \
        && [[ -f "$PROMPT" ]] && [[ -r "$PROMPT" ]]; then
  LOADED_PATH="$PROMPT"
  PROMPT="$(cat "$LOADED_PATH")"
  echo "[setup-ralph-loop] auto-loaded prompt from file: $LOADED_PATH ($(printf '%s' "$PROMPT" | wc -l) lines)" >&2
fi

mkdir -p .kaizen

if [[ -n "$COMPLETION_PROMISE" ]] && [[ "$COMPLETION_PROMISE" != "null" ]]; then
  COMPLETION_PROMISE_YAML="\"$(escape_yaml_double_quoted "$COMPLETION_PROMISE")\""
else
  COMPLETION_PROMISE_YAML="null"
fi

# Build the body. Modes (mutually exclusive):
#   1. --ledger <file>         → use file contents (must be {"pending":[...]})
#   2. --item ... [--item ...] → build a structured ledger from --item pairs
#   3. PROMPT only             → legacy freeform body (single string)
build_ledger_body() {
  if [[ -n "$LEDGER_FILE" ]]; then
    if [[ ! -f "$LEDGER_FILE" ]]; then
      die "--ledger file does not exist: $LEDGER_FILE"
    fi
    # Validate it parses as JSON and contains the required pending array;
    # also auto-assign IDs to items that lack them (so loop_state.add_item's
    # _next_id can track them, and `kaizen-loop complete i3` works).
    python3 - "$LEDGER_FILE" <<'PY'
import json, sys
path = sys.argv[1]
try:
    d = json.load(open(path))
except (OSError, json.JSONDecodeError) as e:
    sys.exit(f"--ledger file is not valid JSON: {e}")
if not isinstance(d.get("pending"), list):
    sys.exit("--ledger file lacks a 'pending' array")
d.setdefault("completed", [])
# Auto-ID pending items that lack one. Pick i<N> avoiding existing IDs.
used = {it.get("id") for it in d["pending"] if isinstance(it, dict) and it.get("id")}
n = 1
for it in d["pending"]:
    if not isinstance(it, dict) or it.get("id"):
        continue
    while f"i{n}" in used:
        n += 1
    it["id"] = f"i{n}"
    used.add(f"i{n}")
    n += 1
print(json.dumps(d, indent=2))
PY
    return
  fi
  if [[ ${#ITEMS[@]} -gt 0 ]]; then
    # Build JSON from --item arguments. Each arg is "desc|verify" or just "desc".
    # IDs are auto-assigned as i1, i2, ... so `kaizen-loop complete <id>` works.
    python3 - "${ITEMS[@]}" <<'PY'
import json, sys
items = []
for i, raw in enumerate(sys.argv[1:], 1):
    if "|" in raw:
        desc, verify = raw.split("|", 1)
        items.append({"id": f"i{i}", "desc": desc.strip(), "verify": verify.strip() or None})
    else:
        items.append({"id": f"i{i}", "desc": raw.strip(), "verify": None})
print(json.dumps({"pending": items, "completed": []}, indent=2))
PY
    return
  fi
  # Legacy freeform: just emit the prompt string.
  printf '%s\n' "$PROMPT"
}

BODY=$(build_ledger_body)

cat > .kaizen/loop.state.md <<EOF
---
active: true
iteration: 1
session_id: ${CLAUDE_SESSION_ID:-${CODEX_SESSION_ID:-}}
last_turn_id: ""
max_iterations: $MAX_ITERATIONS
completion_promise: $COMPLETION_PROMISE_YAML
started_at: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
---

$BODY
EOF

cat <<EOF
Ralph loop activated.

Iteration: 1
Max iterations: $(if [[ $MAX_ITERATIONS -gt 0 ]]; then echo $MAX_ITERATIONS; else echo "unlimited"; fi)
Completion promise: $(if [[ "$COMPLETION_PROMISE" != "null" ]]; then echo "${COMPLETION_PROMISE//\"/}"; else echo "none"; fi)

State file: .kaizen/loop.state.md

Stop hooks are auto-installed by the kaizen plugin:
  Claude Code: \${CLAUDE_PLUGIN_ROOT}/hooks/claude/stop-ralph.sh
  Codex:       \${CODEX_PLUGIN_ROOT}/hooks/codex/stop-ralph.sh

The hook will continue the session with the same prompt until the loop stops.

To monitor: head -10 .kaizen/loop.state.md
EOF

if [[ -n "$PROMPT" ]]; then
  echo ""
  echo "$PROMPT"
fi

if [[ "$COMPLETION_PROMISE" != "null" ]]; then
  echo ""
  echo "Completion rule:"
  echo ""
  echo "Output this exact text only when it is true:"
  echo "  <promise>$COMPLETION_PROMISE</promise>"
fi
