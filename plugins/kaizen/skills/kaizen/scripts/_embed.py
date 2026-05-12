"""kaizen embedding backend — HTTP-first (llama-server /v1/embeddings),
sentence-transformers fallback (v1.25.0+).

Shared module used by trace_index / knowledge_index / onboard_index /
scrape_index. Was previously inlined in each indexer as `_load_model()`
+ `embed_one()`; consolidated here so swapping backend means editing
one file.

## Backend resolution

Priority (first match wins):

  1. KAIZEN_EMBED_BACKEND=local   → force sentence-transformers
  2. KAIZEN_EMBED_BACKEND=http +
       KAIZEN_EMBED_HTTP_BASE_URL +
       KAIZEN_EMBED_HTTP_MODEL    → force HTTP, no probe
  3. Cached endpoint at ~/.claude/.kaizen/embed_endpoint.json
  4. Live probe of the same endpoints scrape uses for chat
     (SCRAPE_LLM_PROBES) — but only accept hits whose model name
     matches an embedding-model pattern (nomic-embed, bge-*, gte-*,
     stella, jina-embed, minilm, *-embed, embedding)
  5. Fallback to sentence-transformers (heavy: ~3GB install)

## Dim handling

The HTTP backend doesn't pre-declare dim; we discover it via a tiny
test call on first use, then cache. The local backend uses
config.EMBED_DIM (384 for `all-MiniLM-L6-v2`). Each indexer stores
the actual dim in its DB meta; search refuses rows whose stored dim
doesn't match the current dim.

## Privacy

The HTTP path sends the embed input text to your local llama-server.
Treat the local server as you would the embedding model — text in,
vectors out, no logging unless the server is configured for it.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
import _paths as _p  # noqa: E402
import config as _cfg  # noqa: E402


# ─── Embedding-model name patterns ───────────────────────────────────

EMBEDDING_NAME_PATTERNS = [
    re.compile(r"nomic-?embed", re.I),
    re.compile(r"bge-(small|base|large|m3|micro|reranker)", re.I),
    re.compile(r"minilm", re.I),
    re.compile(r"gte-(small|base|large|qwen)", re.I),
    re.compile(r"stella-en", re.I),
    re.compile(r"jina-embed", re.I),
    re.compile(r"e5-(small|base|large|mistral)", re.I),
    re.compile(r"-embed(-|$|\.)", re.I),
    re.compile(r"embedding", re.I),
    re.compile(r"text-embedding", re.I),  # OpenAI naming
]


def is_embedding_model_name(name: str) -> bool:
    """Heuristic: does this model name look like an embedding model?

    Used by both /kaizen:scrape (to refuse picking an embed model as
    the chat backend) and the embedding backend resolver (to find
    candidates on a multi-model llama-server)."""
    return any(p.search(name or "") for p in EMBEDDING_NAME_PATTERNS)


# ─── Cache + resolver ────────────────────────────────────────────────

_EMBED_CACHE_PATH = _p.KAIZEN_USER_DIR / "embed_endpoint.json"
_cached_cfg: Optional[dict] = None


def _read_cache() -> Optional[dict]:
    if not _EMBED_CACHE_PATH.is_file():
        return None
    try:
        data = json.loads(_EMBED_CACHE_PATH.read_text())
        if data.get("kind") in {"http", "local"}:
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _write_cache(cfg: dict) -> None:
    try:
        _EMBED_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _EMBED_CACHE_PATH.write_text(json.dumps(cfg, indent=2))
    except OSError:
        pass


def _probe_for_embed_model(base_url: str, list_path: str, timeout: float) -> Optional[str]:
    """Hit a /v1/models endpoint; return the first embedding-shaped model name."""
    url = base_url.rstrip("/") + list_path
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return None
    items = []
    if isinstance(data, dict):
        if isinstance(data.get("data"), list):
            items = [it for it in data["data"] if isinstance(it, dict)]
        elif isinstance(data.get("models"), list):
            items = [it for it in data["models"] if isinstance(it, dict)]
    for it in items:
        name = it.get("id") or it.get("name") or ""
        if name and is_embedding_model_name(str(name)):
            return str(name)
    return None


def resolve_backend(refresh: bool = False) -> dict:
    """Return the active embedding backend config.

    Shape:
      {kind: "http", base_url: str, model: str, dim: int?}    OR
      {kind: "local", model: str, dim: int}
    """
    global _cached_cfg
    if _cached_cfg is not None and not refresh:
        return _cached_cfg

    # 1. Env force-local
    backend = os.environ.get("KAIZEN_EMBED_BACKEND", "auto").lower()
    if backend == "local":
        cfg = {"kind": "local", "model": _cfg.EMBED_MODEL, "dim": _cfg.EMBED_DIM}
        _cached_cfg = cfg
        return cfg

    # 2. Env force-http
    if backend == "http":
        base_url = os.environ.get("KAIZEN_EMBED_HTTP_BASE_URL", "")
        model = os.environ.get("KAIZEN_EMBED_HTTP_MODEL", "")
        if base_url and model:
            cfg = {"kind": "http", "base_url": base_url, "model": model}
            _cached_cfg = cfg
            return cfg
        sys.stderr.write(
            "kaizen embed: KAIZEN_EMBED_BACKEND=http but "
            "KAIZEN_EMBED_HTTP_BASE_URL / KAIZEN_EMBED_HTTP_MODEL not set\n"
        )

    # 3. Cache
    if not refresh:
        cached = _read_cache()
        if cached:
            _cached_cfg = cached
            return cached

    # 4. Live probe — only OpenAI-shaped endpoints serve /v1/embeddings
    for provider, base_url, list_path, _model_field in _cfg.SCRAPE_LLM_PROBES:
        if provider != "openai":
            continue
        model = _probe_for_embed_model(base_url, list_path, _cfg.SCRAPE_LLM_PROBE_TIMEOUT)
        if model:
            cfg = {"kind": "http", "base_url": base_url, "model": model}
            _write_cache(cfg)
            _cached_cfg = cfg
            return cfg

    # 5. Fallback to local sentence-transformers
    cfg = {"kind": "local", "model": _cfg.EMBED_MODEL, "dim": _cfg.EMBED_DIM}
    _cached_cfg = cfg
    return cfg


# ─── Embedding API ───────────────────────────────────────────────────

_local_model = None
_local_np = None


def _load_local_model():
    global _local_model, _local_np
    if _local_model is None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            import numpy as np  # type: ignore
        except ImportError as e:
            sys.stderr.write(
                f"kaizen embed: missing sentence-transformers: {e}\n"
                "Either install it (heavy), or set up a local embedding server:\n"
                "  llama-server -m nomic-embed-text-v2.gguf --embedding --port 8080\n"
                "Then re-run with the cache refreshed:\n"
                "  rm ~/.claude/.kaizen/embed_endpoint.json\n"
            )
            sys.exit(1)
        _local_np = np
        _local_model = SentenceTransformer(_cfg.EMBED_MODEL)
    return _local_model, _local_np


def _embed_http(text: str, base_url: str, model: str) -> tuple[bytes, int]:
    """POST to /v1/embeddings. Returns (float32_bytes, dim)."""
    try:
        import numpy as np  # type: ignore
    except ImportError as e:
        sys.stderr.write(f"kaizen embed: missing numpy: {e}\n")
        sys.exit(1)
    payload = json.dumps({"input": text, "model": model}).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/embeddings",
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    items = data.get("data") or []
    if not items:
        raise RuntimeError(f"empty embeddings response from {base_url}: {data}")
    vec = items[0].get("embedding")
    if not isinstance(vec, list):
        raise RuntimeError(f"unexpected response shape from {base_url}: {data}")
    arr = np.array(vec, dtype=np.float32)
    return arr.tobytes(), int(arr.shape[0])


def _embed_local(text: str) -> tuple[bytes, int]:
    model, np = _load_local_model()
    vec = model.encode(text, convert_to_numpy=True, show_progress_bar=False).astype(
        np.float32
    )
    return vec.tobytes(), int(vec.shape[0])


def embed_one(text: str) -> tuple[bytes, int]:
    """Embed a single string. Returns (float32 bytes, dim).

    Routes to HTTP if a llama-server (or other OpenAI-compatible)
    embedding endpoint is detected; falls back to sentence-transformers
    otherwise."""
    cfg = resolve_backend()
    if cfg["kind"] == "http":
        return _embed_http(text, cfg["base_url"], cfg["model"])
    return _embed_local(text)


def _embed_http_batch(texts: list[str], base_url: str, model: str) -> tuple[list[bytes], int]:
    """POST a batch of strings to /v1/embeddings. Returns ([bytes,...], dim)."""
    import numpy as np  # type: ignore
    payload = json.dumps({"input": texts, "model": model}).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/embeddings",
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    items = data.get("data") or []
    if len(items) != len(texts):
        raise RuntimeError(
            f"embeddings response length mismatch: requested {len(texts)}, got {len(items)}"
        )
    out_blobs: list[bytes] = []
    dim = 0
    for item in items:
        vec = item.get("embedding")
        if not isinstance(vec, list):
            raise RuntimeError(f"unexpected embeddings response shape: {item}")
        arr = np.array(vec, dtype=np.float32)
        out_blobs.append(arr.tobytes())
        dim = int(arr.shape[0])
    return out_blobs, dim


def _embed_local_batch(texts: list[str]) -> tuple[list[bytes], int]:
    model, np = _load_local_model()
    vecs = model.encode(texts, batch_size=64, show_progress_bar=False, convert_to_numpy=True)
    vecs = vecs.astype(np.float32)
    out = [vecs[i].tobytes() for i in range(vecs.shape[0])]
    return out, int(vecs.shape[1]) if vecs.ndim > 1 else int(vecs.shape[0])


def embed_batch(texts: list[str]) -> tuple[list[bytes], int]:
    """Batch-embed a list of strings. Returns ([float32 bytes, ...], dim).

    Batches via HTTP (single POST with list input) or local
    sentence-transformers (model.encode supports lists natively).
    Empty input returns ([], 0)."""
    if not texts:
        return [], 0
    cfg = resolve_backend()
    if cfg["kind"] == "http":
        return _embed_http_batch(texts, cfg["base_url"], cfg["model"])
    return _embed_local_batch(texts)


def get_dim() -> int:
    """Return the dim of the active embedding backend. Caches the
    discovered dim in resolve_backend()'s cache for next call."""
    cfg = resolve_backend()
    if cfg.get("dim"):
        return int(cfg["dim"])
    # HTTP path — probe with a one-token input
    _, dim = embed_one("hello")
    cfg["dim"] = dim
    _cached_cfg.update(cfg)
    _write_cache(cfg)
    return dim


# ─── Inspector / CLI helper ──────────────────────────────────────────


def describe() -> dict:
    """Return the resolved backend as a dict for `kaizen-scrape detect-llm`
    or other inspectors."""
    cfg = resolve_backend()
    out = dict(cfg)
    out["cache_path"] = str(_EMBED_CACHE_PATH)
    out["env_backend"] = os.environ.get("KAIZEN_EMBED_BACKEND", "auto")
    return out


if __name__ == "__main__":
    # Tiny CLI: kaizen-embed-resolve (for debugging)
    import argparse
    p = argparse.ArgumentParser(description="Resolve the kaizen embedding backend.")
    p.add_argument("--refresh", action="store_true", help="ignore cache, re-probe")
    p.add_argument("--probe-dim", action="store_true", help="also call embed_one to discover dim")
    args = p.parse_args()
    if args.refresh:
        _EMBED_CACHE_PATH.unlink(missing_ok=True)
        _cached_cfg = None  # noqa: F841
    info = describe()
    if args.probe_dim:
        try:
            info["dim"] = get_dim()
        except Exception as e:
            info["probe_error"] = f"{type(e).__name__}: {e}"
    print(json.dumps(info, indent=2))
