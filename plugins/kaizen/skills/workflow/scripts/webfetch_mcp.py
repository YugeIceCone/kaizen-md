#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=3.0"]
# ///
"""kaizen MCP — WebFetch recall + policy + dedup.

Composes with the PostToolUse `posttool-webfetch-capture.sh` hook
(which fills ~/.claude/.kaizen/web-fetches.jsonl). This server queries
that store BEFORE the agent issues a real WebFetch, so:

- **Repeat fetches** (same url + prompt within TTL) get cached body
  back — saves API cost, avoids the 15-min cache miss cliff.
- **In-session re-reads** (same url already fetched this session) get
  a "you already saw this in context" reply — no second hit at all.
- **Semantic recall** lets the agent ask "what have I fetched about X"
  without grepping the JSONL.
- **Policy** denies blocked domains, rate-limits per-domain.

Tools:
  webfetch_cached(url, prompt, ttl_min=60)        → {hit, body?, ts?}
  webfetch_session_seen(url, prompt, session_id)  → {seen, ts?}
  webfetch_search(query, top_k=5)                 → {matches: [...]}
  webfetch_policy(url)                            → {verdict, reason}

Sandbox: KAIZEN_WEBFETCH_CAPTURE_LOG redirects the source jsonl.
"""
from __future__ import annotations

import json
import os
import re
import sys
import datetime as _dt
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

mcp = FastMCP("webfetch")


# ─── Pure helpers ────────────────────────────────────────────────────


def _jsonl_path() -> Path:
    env = os.environ.get("KAIZEN_WEBFETCH_CAPTURE_LOG")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("KAIZEN_DIR") or (Path.home() / ".claude" / ".kaizen")
    return Path(base) / "web-fetches.jsonl"


def _read_entries(limit: int | None = None) -> list[dict]:
    """Load fetches from the jsonl store (newest last). Empty when absent."""
    p = _jsonl_path()
    if not p.is_file():
        return []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if limit is not None:
        return out[-limit:]
    return out


def _parse_ts(ts: str) -> _dt.datetime | None:
    try:
        return _dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=_dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def _match_cache(entries: list[dict], url: str, prompt: str,
                  ttl_min: int) -> Optional[dict]:
    """Newest entry with same (url, prompt) within TTL. None if no hit."""
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=ttl_min)
    for e in reversed(entries):
        if e.get("url") != url or e.get("prompt") != prompt:
            continue
        ets = _parse_ts(e.get("ts", ""))
        if ets is None or ets >= cutoff:
            return e
    return None


def _domain_of(url: str) -> str:
    m = re.match(r"^[a-z]+://([^/]+)", url, re.I)
    return m.group(1).lower() if m else ""


def _policy_verdict(url: str) -> dict:
    """Read KAIZEN_WEBFETCH_DENY_DOMAINS (csv) + KAIZEN_WEBFETCH_RATE_LIMIT_PER_MIN."""
    deny_raw = os.environ.get("KAIZEN_WEBFETCH_DENY_DOMAINS", "")
    deny = {d.strip().lower() for d in deny_raw.split(",") if d.strip()}
    dom = _domain_of(url)
    if dom and dom in deny:
        return {"verdict": "deny", "reason": f"domain {dom!r} in deny-list"}
    # Rate-limit: count entries to this domain in last 60s
    try:
        rate_cap = int(os.environ.get("KAIZEN_WEBFETCH_RATE_LIMIT_PER_MIN", "0"))
    except ValueError:
        rate_cap = 0
    if rate_cap > 0 and dom:
        cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=60)
        recent = 0
        for e in _read_entries():
            if _domain_of(e.get("url", "")) != dom:
                continue
            ets = _parse_ts(e.get("ts", ""))
            if ets and ets >= cutoff:
                recent += 1
        if recent >= rate_cap:
            return {"verdict": "rate-limited",
                    "reason": f"domain {dom!r} fetched {recent}x in last 60s "
                              f"(cap {rate_cap})"}
    return {"verdict": "allow", "reason": ""}


# ─── MCP tools ───────────────────────────────────────────────────────


def webfetch_cached(url: str, prompt: str, ttl_min: int = 60) -> dict:
    """Recall a past WebFetch result for (url, prompt) if within TTL.

    Returns:
      {"hit": True, "body": "...", "ts": "..."} when a match within
      ttl_min minutes exists — agent uses the body directly, no real
      WebFetch needed.
      {"hit": False} when no recent fetch matches — agent should call
      the real WebFetch tool (which fires the capture hook → fills
      the cache for next time).
    """
    e = _match_cache(_read_entries(), url, prompt, ttl_min)
    if e is None:
        return {"hit": False}
    return {"hit": True, "body": e.get("response", ""),
            "ts": e.get("ts", ""), "session_id": e.get("session_id", "")}


def webfetch_session_seen(url: str, prompt: str = "",
                           session_id: str = "") -> dict:
    """In-session recall: was this (url, prompt) already fetched this session?

    Skips the TTL check entirely — just matches on session_id. Use when
    the agent is about to re-fetch within the same conversation;
    typically the response is still in context.
    """
    if not session_id:
        return {"seen": False, "reason": "session_id required"}
    for e in reversed(_read_entries()):
        if e.get("session_id") != session_id:
            continue
        if e.get("url") != url:
            continue
        if prompt and e.get("prompt") != prompt:
            continue
        return {"seen": True, "ts": e.get("ts", ""),
                "url": e.get("url", ""), "prompt": e.get("prompt", "")}
    return {"seen": False}


def webfetch_search(query: str, top_k: int = 5) -> dict:
    """Substring search across past fetches' (url, prompt, response).

    Newest-first. Stdlib-only (no embedding dependency); composes with
    kaizen-knowledge for semantic search when the corpus grows.
    """
    q = (query or "").strip().lower()
    if not q:
        return {"matches": []}
    out: list[dict] = []
    for e in reversed(_read_entries()):
        url = (e.get("url") or "").lower()
        prompt = (e.get("prompt") or "").lower()
        resp = (e.get("response") or "").lower()
        if q in url or q in prompt or q in resp:
            out.append({
                "ts": e.get("ts", ""),
                "url": e.get("url", ""),
                "prompt": e.get("prompt", ""),
                "snippet": _snippet(e.get("response") or "", q, 240),
            })
            if len(out) >= top_k:
                break
    return {"matches": out}


def _snippet(text: str, needle: str, width: int) -> str:
    """Return text around the first occurrence of needle (case-insensitive)."""
    low = text.lower()
    i = low.find(needle.lower())
    if i < 0:
        return text[:width]
    start = max(0, i - width // 4)
    end = min(len(text), i + width * 3 // 4)
    pre = "…" if start > 0 else ""
    post = "…" if end < len(text) else ""
    return f"{pre}{text[start:end]}{post}"


def webfetch_policy(url: str) -> dict:
    """Return the policy verdict for ``url``: allow / deny / rate-limited.

    Configure via env:
      KAIZEN_WEBFETCH_DENY_DOMAINS=foo.com,bar.io,internal.local
      KAIZEN_WEBFETCH_RATE_LIMIT_PER_MIN=10
    """
    return _policy_verdict(url)


# ─── Token-free storage (no-read) ────────────────────────────────────


def _atomic_append_jsonl(path: Path, entry: dict) -> None:
    """Append one JSON line to ``path`` atomically (POSIX < PIPE_BUF safe)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


def webfetch_store(url: str, prompt: str = "",
                    max_bytes: int = 20000,
                    timeout_sec: int = 15) -> dict:
    """Fetch ``url`` and store the raw body — return ONLY metadata, no body.

    Zero-token storage: agent never sees the fetched content in its
    context. Use webfetch_cached / webfetch_search / webfetch_semsearch
    afterward to recall just the slice you need.

    Bypasses Claude Code's WebFetch tool (which AI-summarizes + returns
    body to context). Uses stdlib urllib directly — no extra dep. Honors
    webfetch_policy (deny / rate-limit) before fetching.

    Returns:
      {"stored": True, "url", "size_bytes", "sha256", "ts"} on success.
      {"stored": False, "error": "..."} on failure (policy block, HTTP
      error, timeout — never raises).
    """
    pol = _policy_verdict(url)
    if pol["verdict"] != "allow":
        return {"stored": False, "error": f"policy: {pol['verdict']} "
                                          f"({pol['reason']})"}

    import hashlib as _hashlib
    import urllib.request as _urllib_request
    import urllib.error as _urllib_error

    try:
        req = _urllib_request.Request(
            url, headers={"User-Agent": "kaizen-webfetch-store/1.0"})
        with _urllib_request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read(max_bytes + 1)
    except (_urllib_error.URLError, _urllib_error.HTTPError, OSError) as e:
        return {"stored": False, "error": f"{type(e).__name__}: {e}"}

    truncated = len(raw) > max_bytes
    body = raw[:max_bytes]
    try:
        text = body.decode("utf-8", errors="replace")
    except Exception:
        text = body.decode("latin-1", errors="replace")
    if truncated:
        text += f"\n... [truncated at {max_bytes}B]"

    sha = _hashlib.sha256(body).hexdigest()[:16]
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = {
        "ts": ts,
        "session_id": "",  # tool-driven; no Claude Code session attached
        "tool": "webfetch_store",
        "url": url,
        "prompt": prompt,
        "response": text,
    }
    try:
        _atomic_append_jsonl(_jsonl_path(), entry)
    except OSError as e:
        return {"stored": False, "error": f"write failed: {e}"}

    return {
        "stored": True,
        "url": url,
        "size_bytes": len(body),
        "truncated": truncated,
        "sha256": sha,
        "ts": ts,
    }


# ─── Semantic search (lazy embed + substring fallback) ───────────────


def _cosine(a: bytes, b: bytes) -> float:
    """Cosine similarity for two float32-packed embeddings of equal dim.
    Stdlib-only; assumes len(a) == len(b) and len(a) % 4 == 0."""
    import struct as _struct
    n = len(a) // 4
    if n == 0 or len(a) != len(b):
        return 0.0
    av = _struct.unpack(f"{n}f", a)
    bv = _struct.unpack(f"{n}f", b)
    dot = sum(x * y for x, y in zip(av, bv))
    na = sum(x * x for x in av) ** 0.5
    nb = sum(x * x for x in bv) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def webfetch_semsearch(query: str, top_k: int = 5,
                       snippet_width: int = 240) -> dict:
    """Semantic-rank past fetches by similarity to ``query`` — snippets only.

    Embeds the query + each entry's response head (first 2KB) via
    ``_embed.embed_one``; ranks by cosine similarity; returns top-k as
    ``{ts, url, prompt, snippet, similarity}``. Snippets capped at
    ``snippet_width`` (NEVER returns full response — token-efficient).

    Graceful fallback when no embedding backend available: degrades to
    ``webfetch_search`` (substring match). Lazy-imports `_embed` so the
    fastmcp dep alone is enough.
    """
    q = (query or "").strip()
    if not q:
        return {"matches": [], "method": "noop", "reason": "empty query"}
    entries = _read_entries()
    if not entries:
        return {"matches": [], "method": "noop", "reason": "no stored fetches"}

    # Try semantic path; fall back to substring on any embed failure.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import _embed  # type: ignore
        q_vec, q_dim = _embed.embed_one(q)
    except Exception as e:  # noqa: BLE001
        sub = webfetch_search(q, top_k=top_k)
        sub["method"] = "fallback-substring"
        sub["reason"] = f"embed unavailable: {type(e).__name__}"
        return sub

    scored: list[tuple[float, dict]] = []
    for e in entries:
        body = (e.get("response") or "")[:2000]
        if not body:
            continue
        try:
            e_vec, e_dim = _embed.embed_one(body)
        except Exception:
            continue
        if e_dim != q_dim:
            continue
        sim = _cosine(q_vec, e_vec)
        scored.append((sim, e))

    scored.sort(key=lambda t: t[0], reverse=True)
    top = scored[:top_k]
    return {
        "method": "semantic",
        "matches": [
            {
                "ts":         e.get("ts", ""),
                "url":        e.get("url", ""),
                "prompt":     e.get("prompt", ""),
                "snippet":    _snippet(e.get("response") or "",
                                       q, snippet_width),
                "similarity": round(float(sim), 4),
            }
            for sim, e in top
        ],
    }


mcp.tool()(webfetch_cached)
mcp.tool()(webfetch_session_seen)
mcp.tool()(webfetch_search)
mcp.tool()(webfetch_policy)
mcp.tool()(webfetch_store)
mcp.tool()(webfetch_semsearch)


if __name__ == "__main__":
    mcp.run()
