#!/usr/bin/env bash
# PostToolUse hook (matcher: WebFetch) — capture fetched docs.
#
# Every WebFetch tool call (URL → prompt → AI-summarized response)
# is logged to a JSONL store + trace event. Lets you semantic-search
# past fetches without re-WebFetching (which is metered + cached only
# for 15 min).
#
# Two side-effects:
#   1. _trace.sh → kaizen-trace "webfetch-capture" event
#   2. Atomic-append JSONL: {ts, session_id, url, prompt, response, error?}
#      to ~/.claude/.kaizen/web-fetches.jsonl
#
# Bypass: KAIZEN_WEBFETCH_CAPTURE_DISABLE=1
# Sandbox: KAIZEN_WEBFETCH_CAPTURE_LOG points the log at a tempfile.
#
# Future tie-in: kaizen-knowledge can ingest this jsonl as a corpus
# (semantic search via the existing index pipeline).
#
# Design contract:
#   ADDITIVE     — never touches existing hook chain
#   NON-BLOCKING — exit 0 always
#   CHEAP        — single python3 spawn + atomic append
#   ATOMIC       — single-line append < PIPE_BUF is POSIX-safe

set -uo pipefail

[ "${KAIZEN_WEBFETCH_CAPTURE_DISABLE:-}" = "1" ] && exit 0

INPUT="$(cat 2>/dev/null || true)"

# Compose existing trace pipeline (no-op when KAIZEN_TRACE_DISABLE=1).
_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
printf '%s' "$INPUT" | bash "$_HOOK_DIR/_trace.sh" webfetch-capture 2>/dev/null || true

LOG_DIR="${KAIZEN_DIR:-$HOME/.claude/.kaizen}"
LOG_FILE="${KAIZEN_WEBFETCH_CAPTURE_LOG:-$LOG_DIR/web-fetches.jsonl}"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || exit 0

LINE="$(printf '%s' "$INPUT" | python3 -c '
import json, sys, datetime as dt
try:
    e = json.loads(sys.stdin.read() or "{}")
except Exception:
    sys.exit(0)
# Only capture WebFetch — matcher should guarantee this but defend.
tool_name = e.get("tool_name") or ""
if tool_name not in ("WebFetch", "mcp__claude_ai_Context7__query-docs"):
    sys.exit(0)
ti = e.get("tool_input") or {}
tr = e.get("tool_response") or e.get("tool_result") or {}
# tool_response shape varies by client; normalize.
if isinstance(tr, dict):
    response = tr.get("content") or tr.get("text") or tr.get("body") or ""
    error = tr.get("error") or ""
else:
    response = str(tr) if tr else ""
    error = ""
# Cap response size — full doc bodies get huge; store the head.
MAX_RESP = int((__import__("os").environ.get("KAIZEN_WEBFETCH_CAPTURE_MAX_BYTES") or "20000"))
if isinstance(response, str) and len(response) > MAX_RESP:
    response = response[:MAX_RESP] + f"\n... [truncated at {MAX_RESP}B]"
out = {
    "ts":         dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "session_id": e.get("session_id", ""),
    "tool":       tool_name,
    "url":        ti.get("url", ""),
    "prompt":     ti.get("prompt", ""),
    "response":   response,
}
if error:
    out["error"] = error
print(json.dumps(out, ensure_ascii=False))
' 2>/dev/null)"

if [ -n "$LINE" ]; then
    printf '%s\n' "$LINE" >> "$LOG_FILE" 2>/dev/null || true
fi

exit 0
