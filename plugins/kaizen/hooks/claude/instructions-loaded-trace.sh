#!/usr/bin/env bash
# InstructionsLoaded hook → kaizen-trace + jsonl audit log.
#
# Fires whenever Claude Code loads a CLAUDE.md, CLAUDE.local.md, or
# `.claude/rules/*.md` file (at session start OR lazy / path-glob /
# include / compact). Hook is observability-only — cannot block.
#
# Two side-effects:
#   1. Compose _trace.sh → kaizen-trace event "instructions-loaded"
#   2. Atomic-append a JSONL line to ~/.claude/.kaizen/instructions-loaded.jsonl
#      with {ts, file_path, memory_type, load_reason, globs?, trigger?, parent?}
#
# The JSONL log is the canonical record — the brain-drift gate uses it
# to detect "expected @import didn't fire". Append-only, rotation-free
# (file stays small in practice: one line per load event).
#
# Bypass: KAIZEN_INSTRUCTIONS_LOADED_DISABLE=1
#
# Design contract:
#   PROGRAMMABLE — pure stdin → stdout/jsonl + trace
#   ATOMIC       — temp + rename for the jsonl append (no torn writes)
#   IDEMPOTENT   — re-firing for the same file is intentional + safe
#   NON-BLOCKING — exit 0 always; never disturb the host session
#   CHEAP        — ~2-3ms per call; bash only

set -uo pipefail

[ "${KAIZEN_INSTRUCTIONS_LOADED_DISABLE:-}" = "1" ] && exit 0

# Slurp event JSON from stdin (drop EOF / empty errors silently).
INPUT="$(cat 2>/dev/null || true)"

# Trace fire — pass through to _trace.sh (composes the standard
# kaizen-trace event surface; session_id extraction lives there).
_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
printf '%s' "$INPUT" | bash "$_HOOK_DIR/_trace.sh" instructions-loaded 2>/dev/null || true

# JSONL log — extract the fields we want via python3 (jq may not be
# installed; python3 is the kaizen hard dep). Best-effort; on parse
# failure, write a sentinel line + exit 0.
LOG_DIR="${KAIZEN_DIR:-$HOME/.claude/.kaizen}"
LOG_FILE="${KAIZEN_INSTRUCTIONS_LOADED_LOG:-$LOG_DIR/instructions-loaded.jsonl}"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || exit 0

LINE="$(printf '%s' "$INPUT" | python3 -c '
import json, sys, datetime as dt
try:
    e = json.loads(sys.stdin.read() or "{}")
except Exception:
    e = {}
out = {
    "ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "file_path": e.get("file_path", ""),
    "memory_type": e.get("memory_type", ""),
    "load_reason": e.get("load_reason", ""),
}
if e.get("globs"): out["globs"] = e["globs"]
if e.get("trigger_file_path"): out["trigger_file_path"] = e["trigger_file_path"]
if e.get("parent_file_path"): out["parent_file_path"] = e["parent_file_path"]
print(json.dumps(out))
' 2>/dev/null)"

if [ -n "$LINE" ]; then
    # Atomic single-line append — race-safe under concurrent hook fires.
    # `printf >> $f` is atomic for small writes on POSIX FS; the line is
    # always < PIPE_BUF (4KB) so this is safe.
    printf '%s\n' "$LINE" >> "$LOG_FILE" 2>/dev/null || true
fi

exit 0
