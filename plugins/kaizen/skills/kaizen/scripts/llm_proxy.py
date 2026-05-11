#!/usr/bin/env python3
"""kaizen llm-proxy — forwarding HTTP proxy for the Anthropic API.

Wraps the Claude Code ↔ api.anthropic.com connection so each request +
response is logged to `kaizen-trace --src llm`. Stdlib-only (http.server
+ urllib.request).

## Setup

    1. Start the proxy:
       kaizen-trace-proxy start [--port 8765] [--upstream https://api.anthropic.com]
    2. Point Claude Code at it:
       export ANTHROPIC_BASE_URL=http://127.0.0.1:8765
    3. Run CC. Every LLM call traces:
       kaizen-trace query --src llm --since 1h

## What it logs (auth scrubbed)

    Request:   path, model, message-count, max_tokens, stream flag
    Response:  status, input_tokens, output_tokens, ms

Auth headers (Authorization, x-api-key) are passed to upstream but
NEVER written to the trace event.

## Streaming (SSE)

Response is streamed chunk-by-chunk to the client (Connection: close
semantics — no chunked re-encoding hassles). The final SSE
`message_delta` event is captured for output_tokens; intermediate
chunks pass through untouched.

## Failure mode

If the proxy crashes or is unreachable, CC's requests fail with
connection refused. To recover: `unset ANTHROPIC_BASE_URL` and reload.
"""

from __future__ import annotations

import http.server
import json
import os
import re
import signal
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional


SCRIPTS_DIR = Path(__file__).resolve().parent
TRACE_PY = SCRIPTS_DIR / "trace.py"

DEFAULT_UPSTREAM = "https://api.anthropic.com"
DEFAULT_PORT = 8765
CHUNK_SIZE = 8192

# Header names to NEVER include in trace data (case-insensitive match)
SECRET_HEADER_RE = re.compile(
    r"^(authorization|x-api-key|anthropic-auth|cookie|set-cookie)$",
    re.IGNORECASE,
)


def trace_event(evt: str, ms: Optional[int] = None, **data) -> None:
    """Fire a kaizen-trace event with src=llm. Non-blocking, never raises."""
    if not TRACE_PY.exists():
        return
    cmd = ["python3", str(TRACE_PY), "event", "--src", "llm", "--evt", evt]
    if ms is not None:
        cmd += ["--ms", str(ms)]
    if data:
        # Drop None values to keep events compact
        clean = {k: v for k, v in data.items() if v is not None}
        if clean:
            cmd += ["--data", json.dumps(clean, separators=(",", ":"))]
    try:
        subprocess.run(cmd, timeout=2, capture_output=True)
    except (subprocess.SubprocessError, OSError):
        pass


# ─── Request / response parsing ──────────────────────────────────────


def parse_request_meta(body: bytes, path: str) -> dict:
    meta = {"path": path}
    if not body:
        return meta
    try:
        j = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return meta
    if isinstance(j, dict):
        meta["model"] = j.get("model")
        if isinstance(j.get("messages"), list):
            meta["messages"] = len(j["messages"])
        if isinstance(j.get("system"), str):
            meta["system_chars"] = len(j["system"])
        meta["max_tokens"] = j.get("max_tokens")
        meta["stream"] = j.get("stream")
    return meta


def parse_response_meta(buf: bytearray, content_type: str) -> dict:
    """Extract token usage from response body. Best-effort."""
    if not buf:
        return {}
    try:
        text = buf.decode("utf-8", errors="ignore")
    except Exception:
        return {}

    if "text/event-stream" in content_type:
        # Walk SSE backwards from the end for the final message_delta / message_stop
        # with usage.output_tokens.
        out: dict = {}
        for raw in reversed(text.splitlines()):
            line = raw.strip()
            if not line.startswith("data: "):
                continue
            try:
                evt = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            t = evt.get("type", "")
            usage = evt.get("usage") or evt.get("message", {}).get("usage")
            if isinstance(usage, dict):
                if usage.get("output_tokens") is not None:
                    out["output_tokens"] = usage["output_tokens"]
                if usage.get("input_tokens") is not None:
                    out.setdefault("input_tokens", usage["input_tokens"])
                if out:
                    break
            if t == "message_start":
                # Earliest usage info — input_tokens are here
                msg = evt.get("message", {})
                if isinstance(msg.get("usage"), dict):
                    if msg["usage"].get("input_tokens") is not None:
                        out.setdefault("input_tokens", msg["usage"]["input_tokens"])
        return out

    # Non-streaming: parse the full JSON body
    try:
        j = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(j, dict):
        return {}
    u = j.get("usage") or {}
    return {
        "input_tokens": u.get("input_tokens"),
        "output_tokens": u.get("output_tokens"),
    }


# ─── Proxy handler ───────────────────────────────────────────────────


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    server_version = "kaizen-llm-proxy/1.0"
    protocol_version = "HTTP/1.1"
    upstream_base: str = DEFAULT_UPSTREAM

    def log_message(self, fmt, *args):  # silence default logging
        pass

    def _forward(self):
        t0 = time.monotonic()

        # Read body if any
        content_len = 0
        try:
            content_len = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            pass
        body = self.rfile.read(content_len) if content_len > 0 else b""

        req_meta = parse_request_meta(body, self.path)

        # Build outbound headers — pass through everything except Host /
        # Content-Length (urllib sets these correctly).
        out_headers = {}
        for k, v in self.headers.items():
            if k.lower() in ("host", "content-length", "connection"):
                continue
            out_headers[k] = v
        # Ensure Host points at upstream
        from urllib.parse import urlparse
        upstream_host = urlparse(self.upstream_base).netloc
        out_headers["Host"] = upstream_host

        upstream_url = self.upstream_base.rstrip("/") + self.path
        req = urllib.request.Request(
            upstream_url,
            data=body if body else None,
            headers=out_headers,
            method=self.command,
        )

        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                status = resp.status
                # Reply status + headers
                # Strip transfer-encoding (we'll just close the connection
                # after streaming — Connection: close)
                self.send_response_only(status)
                content_type = resp.headers.get("Content-Type", "")
                for k, v in resp.headers.items():
                    kl = k.lower()
                    if kl in ("transfer-encoding", "content-length", "connection"):
                        continue
                    self.send_header(k, v)
                self.send_header("Connection", "close")
                self.end_headers()

                # Stream the body
                buf = bytearray()
                BUF_CAP = 1024 * 1024  # cap at 1 MB to keep parsing fast
                while True:
                    chunk = resp.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        # Client disconnected mid-stream
                        break
                    if len(buf) < BUF_CAP:
                        buf.extend(chunk[: BUF_CAP - len(buf)])

                resp_meta = parse_response_meta(buf, content_type)
                ms = int((time.monotonic() - t0) * 1000)
                trace_event("call", ms=ms, status=status, **req_meta, **resp_meta)

        except urllib.error.HTTPError as e:
            # Upstream returned non-2xx. Pass it through (already-formatted error response).
            ms = int((time.monotonic() - t0) * 1000)
            body_bytes = b""
            try:
                body_bytes = e.read()
            except Exception:
                pass
            self.send_response_only(e.code)
            for k, v in (e.headers or {}).items():
                if k.lower() in ("transfer-encoding", "content-length", "connection"):
                    continue
                self.send_header(k, v)
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                if body_bytes:
                    self.wfile.write(body_bytes)
            except (BrokenPipeError, ConnectionResetError):
                pass
            trace_event("call-error", ms=ms, status=e.code, **req_meta,
                        error=str(e.reason)[:200])

        except Exception as e:
            ms = int((time.monotonic() - t0) * 1000)
            trace_event("upstream-error", ms=ms, error=str(e)[:200], **req_meta)
            try:
                self.send_error(502, f"upstream error: {e}")
            except Exception:
                pass

    do_GET = _forward
    do_POST = _forward
    do_PUT = _forward
    do_PATCH = _forward
    do_DELETE = _forward
    do_HEAD = _forward
    do_OPTIONS = _forward


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# ─── Entry ───────────────────────────────────────────────────────────


def serve(port: int, upstream: str, host: str = "127.0.0.1") -> int:
    ProxyHandler.upstream_base = upstream
    srv = ThreadedHTTPServer((host, port), ProxyHandler)

    msg = (
        f"kaizen llm-proxy listening on http://{host}:{port}\n"
        f"  upstream: {upstream}\n"
        f"  trace:    src=llm in ~/.claude/.kaizen-trace/events.jsonl\n"
        f"\n"
        f"Now export to redirect Claude Code:\n"
        f"  export ANTHROPIC_BASE_URL=http://{host}:{port}\n"
        f"\n"
        f"Stop: SIGTERM / Ctrl-C\n"
    )
    print(msg, flush=True)

    trace_event("proxy-start", port=port, upstream=upstream)

    def shutdown(*_):
        trace_event("proxy-stop")
        try:
            srv.shutdown()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        shutdown()
    return 0


def main():
    import argparse
    p = argparse.ArgumentParser(prog="llm_proxy.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int,
                   default=int(os.environ.get("KAIZEN_LLM_PROXY_PORT", DEFAULT_PORT)))
    p.add_argument("--upstream",
                   default=os.environ.get("KAIZEN_LLM_PROXY_UPSTREAM", DEFAULT_UPSTREAM))
    p.add_argument("--host", default="127.0.0.1")
    args = p.parse_args()
    sys.exit(serve(args.port, args.upstream, args.host))


if __name__ == "__main__":
    main()
