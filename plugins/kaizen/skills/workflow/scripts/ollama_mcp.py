#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
#     "ollama>=0.4",
# ]
# ///
"""kaizen ollama MCP — expose the local Ollama daemon as MCP tools.

Lets Claude send direct chat/completion requests to local models
(granite4.1:8b, qwen2.5-coder:1.5b, etc.) without spawning a shell.
Pairs with `_ollama.py` (stdlib internal scorer) + `models.py` (CLI
management) — same backing daemon, three lenses:

  _ollama.py    → stdlib internal, gold-miner's optional path
  models.py     → CLI for users (kaizen models chat/list/pull/...)
  ollama_mcp.py → MCP for Claude (this file)

## Tools

  ollama_list()                              → installed models + metadata
  ollama_ps()                                → currently-loaded (in-memory)
  ollama_chat(model, prompt, format?, ...)   → single chat completion
  ollama_show(model)                         → model metadata + parameters
  ollama_reachable()                         → quick health probe

## Spawning

Mounted into the kaizen gateway via `gateway.py::SUBSERVERS`. Reachable
as `mcp__plugin_kaizen_kaizen__ollama_*(...)` once the gateway spawns.

## Defaults

- host: $OLLAMA_HOST (else http://localhost:11434)
- timeout: 60s for chat (covers small-model warmup); 5s for probes
- temperature: 0 (deterministic; override per-call)
- stream: False (MCP tool result is single-shot)

## Errors

Every tool returns `{"error": "<msg>"}` on failure (never raises).
Errors include: daemon-unreachable, model-not-found, malformed-format,
timeout. Empty `{}` returns are reserved for genuinely-empty success.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Optional


try:
    from fastmcp import FastMCP
except ImportError:
    sys.stderr.write("kaizen-ollama-mcp: fastmcp>=3.0 required\n")
    sys.exit(2)


_DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
_CHAT_TIMEOUT_S = float(os.environ.get("KAIZEN_OLLAMA_TIMEOUT", "60"))


_client = None


def _ollama_client():
    """Lazy-load the official ollama Python client. Returns the
    Client instance OR None if the package isn't installed (graceful
    fallback so an `import ollama_mcp` at module-load-time doesn't
    crash the gateway when ollama isn't present)."""
    global _client
    if _client is not None:
        return _client
    try:
        import ollama
    except ImportError:
        return None
    try:
        _client = ollama.Client(host=_DEFAULT_HOST)
    except Exception:
        return None
    return _client


def _normalize(model_obj: Any) -> dict:
    """Ollama returns model objects that may be dict or pydantic-y."""
    if isinstance(model_obj, dict):
        return model_obj
    out: dict[str, Any] = {}
    for attr in ("name", "model", "modified_at", "size", "digest", "details"):
        val = getattr(model_obj, attr, None)
        if val is not None:
            out[attr] = val if not hasattr(val, "model_dump") else val.model_dump()
    return out


mcp = FastMCP("kaizen-ollama")


# ─── reachable ────────────────────────────────────────────────────────


@mcp.tool()
async def ollama_reachable() -> dict:
    """Quick health probe — is the local Ollama daemon up?

    Returns:
      {"reachable": bool, "host": "<url>", "error"?: "<msg>"}
    """
    def _run() -> dict:
        client = _ollama_client()
        if client is None:
            return {"reachable": False, "host": _DEFAULT_HOST,
                    "error": "ollama python client not installed"}
        try:
            client.list()
            return {"reachable": True, "host": _DEFAULT_HOST}
        except Exception as e:
            return {"reachable": False, "host": _DEFAULT_HOST,
                    "error": str(e)}
    return await asyncio.to_thread(_run)


# ─── list ─────────────────────────────────────────────────────────────


@mcp.tool()
async def ollama_list() -> dict:
    """List all locally-installed Ollama models.

    Returns:
      {"models": [{"name": "...", "size": N, "modified_at": "...", ...}],
       "count": N}
      OR {"error": "<msg>"}
    """
    def _run() -> dict:
        client = _ollama_client()
        if client is None:
            return {"error": "ollama python client not installed"}
        try:
            resp = client.list()
            raw = getattr(resp, "models", resp.get("models", []) if isinstance(resp, dict) else [])
            models = [_normalize(m) for m in raw]
            return {"models": models, "count": len(models)}
        except Exception as e:
            return {"error": str(e)}
    return await asyncio.to_thread(_run)


# ─── ps ───────────────────────────────────────────────────────────────


@mcp.tool()
async def ollama_ps() -> dict:
    """List currently-loaded (in-memory) Ollama models.

    Returns:
      {"loaded": [{"name": "...", "size_vram": N, ...}], "count": N}
      OR {"error": "<msg>"}
    """
    def _run() -> dict:
        client = _ollama_client()
        if client is None:
            return {"error": "ollama python client not installed"}
        try:
            resp = client.ps()
            raw = getattr(resp, "models", resp.get("models", []) if isinstance(resp, dict) else [])
            loaded = [_normalize(m) for m in raw]
            return {"loaded": loaded, "count": len(loaded)}
        except Exception as e:
            return {"error": str(e)}
    return await asyncio.to_thread(_run)


# ─── show ─────────────────────────────────────────────────────────────


@mcp.tool()
async def ollama_show(model: str) -> dict:
    """Show metadata + parameters for a locally-installed model.

    Args:
      model: full model name (e.g. "granite4.1:8b", "qwen2.5-coder:1.5b")

    Returns:
      {"model": "...", "parameters": "...", "template": "...",
       "modelfile": "...", "details": {...}}  OR  {"error": "<msg>"}
    """
    def _run() -> dict:
        client = _ollama_client()
        if client is None:
            return {"error": "ollama python client not installed"}
        try:
            resp = client.show(model)
            if hasattr(resp, "model_dump"):
                return resp.model_dump()
            return dict(resp) if isinstance(resp, dict) else {"raw": str(resp)}
        except Exception as e:
            return {"error": str(e)}
    return await asyncio.to_thread(_run)


# ─── chat ─────────────────────────────────────────────────────────────


@mcp.tool()
async def ollama_chat(
    model: str,
    prompt: str,
    system: Optional[str] = None,
    format: Optional[dict] = None,
    temperature: float = 0.0,
    timeout: Optional[float] = None,
) -> dict:
    """Send a chat completion request to a local Ollama model.

    Args:
      model:       full model name (e.g. "granite4.1:8b")
      prompt:      user message content
      system:      optional system-role content (anchors behavior)
      format:      optional JSON Schema dict to constrain the response
                   (passes through to Ollama's `format` field).
                   When set, the response.content is itself JSON
                   matching the schema — parse it client-side.
      temperature: 0.0 = deterministic (default); higher = creative
      timeout:     seconds (defaults to KAIZEN_OLLAMA_TIMEOUT or 60)

    Returns:
      {"model": "...",
       "content": "<response text>",
       "done": bool,
       "total_duration_ms": N,
       "eval_count": N,
       "eval_duration_ms": N}
      OR {"error": "<msg>"}

    Notes:
      - Single-shot (stream=False); MCP tool results are atomic.
      - For structured output, set `format` to a JSON Schema dict;
        the model will emit JSON conforming to it. Parse the
        returned `content` field with json.loads().
      - Cost: ~3s on granite4.1:8b w/ schema; ~1s on qwen2.5-coder:1.5b.
    """
    t = timeout if timeout is not None else _CHAT_TIMEOUT_S

    def _run() -> dict:
        client = _ollama_client()
        if client is None:
            return {"error": "ollama python client not installed"}
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs: dict[str, Any] = {
            "model":    model,
            "messages": messages,
            "stream":   False,
            "options":  {"temperature": temperature},
            "keep_alive": "5m",
        }
        if format is not None:
            kwargs["format"] = format

        try:
            resp = client.chat(**kwargs)
        except Exception as e:
            return {"error": str(e)}

        # Resp is dict-like or pydantic-y
        msg = getattr(resp, "message", None) or (resp.get("message") if isinstance(resp, dict) else None)
        content = ""
        if msg is not None:
            content = getattr(msg, "content", None) or (msg.get("content", "") if isinstance(msg, dict) else "")

        def _g(key):
            return getattr(resp, key, None) or (resp.get(key) if isinstance(resp, dict) else None)

        out: dict[str, Any] = {
            "model":   model,
            "content": content,
            "done":    bool(_g("done")) if _g("done") is not None else True,
        }
        for ms_key, raw_key in (("total_duration_ms", "total_duration"),
                                  ("eval_duration_ms", "eval_duration")):
            val = _g(raw_key)
            if val is not None:
                # ollama returns ns; convert to ms for sanity
                out[ms_key] = int(val) // 1_000_000
        for k in ("eval_count", "prompt_eval_count"):
            v = _g(k)
            if v is not None:
                out[k] = v
        return out

    return await asyncio.wait_for(asyncio.to_thread(_run), timeout=t)


if __name__ == "__main__":
    # Standalone runtime — usually mounted into the gateway, but the
    # gateway calls __init__ via `mod.mcp`, not this entrypoint.
    mcp.run()
