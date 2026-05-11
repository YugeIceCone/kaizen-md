---
name: trace-proxy
description: Wrap the Claude Code → api.anthropic.com connection in a logging HTTP proxy. Every LLM request/response (auth scrubbed) flows into kaizen-trace as src=llm with model, message count, input/output tokens, latency. Stdlib-only, opt-in. Subcommands: start | stop | status | log | fg.
---

# kaizen trace-proxy

Logging proxy that wraps the Anthropic API connection, recording each LLM call into `kaizen-trace` for cost analysis, latency debugging, and prompt replay.

!`bash ${CLAUDE_PLUGIN_ROOT}/bin/kaizen-trace-proxy ${ARGUMENTS:-status}`

## Setup (one-time per shell)

```bash
# 1. Start the proxy
kaizen-trace-proxy start              # default: 127.0.0.1:8765 → api.anthropic.com
kaizen-trace-proxy start --port 9000  # custom port
kaizen-trace-proxy start --upstream https://api.anthropic.com  # custom upstream

# 2. Redirect Claude Code at it (your shell only, NOT global)
export ANTHROPIC_BASE_URL=http://127.0.0.1:8765

# 3. Run Claude Code as usual — every LLM call traces
claude
```

## Subcommands

| arg | effect |
|---|---|
| (none) or `status` | running yes/no + export hint |
| `start [--port N] [--upstream URL]` | spawn detached background process |
| `stop` | SIGTERM → 3 s → SIGKILL fallback; remove PID file |
| `log [N]` | tail last N lines of proxy stdout (default 30) |
| `fg [--port N] [--upstream URL]` | run foreground (systemd `ExecStart`, manual testing) |

## What it logs (auth scrubbed)

Per request, a trace event lands at `~/.claude/.kaizen-trace/events.jsonl`:

```json
{
  "ts":   "...",
  "src":  "llm",
  "evt":  "call",
  "ms":   3142,
  "data": {
    "path":          "/v1/messages",
    "model":         "claude-opus-4-7",
    "messages":      12,
    "system_chars":  2034,
    "max_tokens":    8192,
    "stream":        true,
    "status":        200,
    "input_tokens":  18456,
    "output_tokens": 1027
  }
}
```

**Never logged**: `Authorization`, `x-api-key`, `anthropic-auth`, `Cookie`, `Set-Cookie` headers. They pass through to upstream untouched but are stripped from trace data.

## Streaming (SSE) handling

Response is streamed chunk-by-chunk to the client (`Connection: close` — no chunked re-encoding). The final SSE `message_delta` / `message_stop` event is parsed for `output_tokens` while intermediate chunks pass through unmodified. Streaming latency overhead: <1 ms per chunk.

## Failure modes

| Scenario | Effect | Recovery |
|---|---|---|
| Proxy crashes | CC requests fail with `Connection refused` | `kaizen-trace-proxy start` again, or `unset ANTHROPIC_BASE_URL` and reload |
| Upstream 5xx | Passed through to CC verbatim; trace records `call-error` | None — surface the upstream error |
| Trace fails | Proxy keeps working; trace events silently drop | `KAIZEN_TRACE_DISABLE=1` to permanently disable |

## Cost analysis

Once events accumulate, query with `kaizen-trace query --src llm --json` and pipe to `jq` for cost computation:

```bash
# Total tokens by model, last 24h
kaizen-trace query --src llm --since 24h --json \
  | jq -r '.data | "\(.model) \(.input_tokens // 0) \(.output_tokens // 0)"' \
  | awk '{i[$1]+=$2; o[$1]+=$3} END {for (m in i) print m, i[m], o[m]}'

# p95 latency
kaizen-trace stats --since 24h | jq '.latency_ms'
```

## Caveats

- **CC must respect `ANTHROPIC_BASE_URL`.** The Anthropic SDK does. CC uses the SDK. High confidence but if CC bypasses (e.g. uses its own keychain-based OAuth flow that hardcodes the URL), the proxy is invisible. Test: start proxy + export + send a message + check `kaizen-trace query --src llm`.
- **TLS termination.** Client → proxy = plain HTTP (localhost only). Proxy → Anthropic = HTTPS (`urllib.request` initiates TLS). No CA cert install needed.
- **HTTP/2.** `urllib.request` speaks HTTP/1.1. Anthropic accepts both; should be invisible.
- **Per-shell.** `export` only affects the shell where you run it. Make permanent in `.bashrc`/`.zshrc` if you want all CC sessions logged.

## Disable

```bash
kaizen-trace-proxy stop
unset ANTHROPIC_BASE_URL
```

CC reverts to direct connection. No trace events from LLM source; hook/tool/agent events still flow.
