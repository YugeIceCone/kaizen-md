#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "scrapegraphai>=1.0",
#     "sentence-transformers>=2.7",
#     "numpy>=1.24",
#     "torch>=2.0",
# ]
#
# [[tool.uv.index]]
# name = "pytorch-cpu"
# url = "https://download.pytorch.org/whl/cpu"
# explicit = true
#
# [tool.uv.sources]
# torch = { index = "pytorch-cpu" }
# ///
"""kaizen scrape-index — scrape + synthesize web content into a semantic SQLite index.

Combines three kaizen patterns:

  1. PocketFlow async Node+Flow (from flow_demo.py) — pipeline of
     FetchURLs → ScrapeFanOut → Synthesize → Embed → Persist.
  2. ScrapeGraphAI SmartScraperGraph — LLM-driven extraction.
  3. trace/knowledge/onboard indexer shape — SQLite + sentence-transformers
     (`all-MiniLM-L6-v2`, 384-dim cosine) with uv-managed CPU torch.

## LLM provider (defaults)

Defaults to **Ollama local** (auto-detected at `http://localhost:11434`)
so no API keys are required out of the box. v1.29.0+ also picks the
best-installed chat model from a curated list (winner: `qwen2.5:7b`),
preferring it over arbitrary `/api/tags` ordering. See
`kaizen-scrape recommend` for the full ranked picks + per-model rationale.

Override via env:

  KAIZEN_SCRAPE_LLM_MODEL=openai/gpt-4o-mini   # then needs OPENAI_API_KEY
  KAIZEN_SCRAPE_LLM_BASE_URL=http://localhost:11434

Ollama setup (one-time):
  /kaizen:models pull granite4.1:8b       # the curated winner (2026-05-12)
  /kaizen:models pull nomic-embed-text    # for embedding (separate from scrape)

## SQLite schema (~/.claude/.kaizen/scrape/index.db)

    scrape_items:
        id          INTEGER PRIMARY KEY AUTOINCREMENT
        url         TEXT NOT NULL
        prompt      TEXT NOT NULL
        title       TEXT
        content_json TEXT NOT NULL          -- raw scrapegraph extraction
        text_extract TEXT NOT NULL          -- denormalized flat text for snippet + embedding
        embedding   BLOB NOT NULL
        sha         TEXT UNIQUE NOT NULL    -- sha1(url|prompt) — re-scrape replaces row
        ts          TEXT NOT NULL

    scrape_meta:
        key         TEXT PRIMARY KEY
        value       TEXT

## Subcommands

    scrape <url> [--prompt "..."] [--model NAME] [--no-embed] [--json]
        Run the PocketFlow pipeline once; persist + print result.
    batch <file>          Lines in <file> = one URL per line; fan-out scrape.
    search "<query>"      Semantic cosine search; --top-k, --json.
    stats                 Counts + model + last-indexed ts.
    get <id>              Print one row (incl. content_json + text_extract).
    list [--limit N]      Most-recent N rows.
    path                  Print db path.
    clear                 Drop the index.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

# ─── kaizen plugin SSOT imports ──────────────────────────────────────

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
import _paths as _p  # noqa: E402
import config as _cfg  # noqa: E402


DB_PATH = _p.SCRAPE_DB
DEFAULT_MODEL = _cfg.EMBED_MODEL
DEFAULT_DIM = _cfg.EMBED_DIM
SNIPPET_MAX = _cfg.SCRAPE_SNIPPET_MAX


# ─── Lazy ML + scrapegraph imports ───────────────────────────────────


import _embed  # noqa: E402 — v1.25.0+: HTTP-first embedding backend


def _load_scraper_cls():
    try:
        from scrapegraphai.graphs import SmartScraperGraph  # type: ignore
        # v1.29.4+: register our curated picks into scrapegraphai's
        # model_tokens table so the 8192-default warning doesn't fire and
        # the full context budget is honored on the openai/* path. Called
        # here because at this point scrapegraphai is guaranteed importable.
        _register_recommendation_tokens()
        return SmartScraperGraph
    except ImportError as e:
        sys.stderr.write(
            f"kaizen-scrape: missing scrapegraphai: {e}\n"
            "PEP 723 should auto-install via uv. If running with python3:\n"
            "  pip install --user scrapegraphai\n"
            "Also requires a reachable LLM endpoint — default is Ollama at\n"
            f"  {_cfg.SCRAPE_LLM_BASE_URL}\n"
        )
        sys.exit(1)


# ─── SQLite ──────────────────────────────────────────────────────────


def open_db(create: bool = True) -> sqlite3.Connection:
    if create:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    if create:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS scrape_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                prompt TEXT NOT NULL,
                title TEXT,
                content_json TEXT NOT NULL,
                text_extract TEXT NOT NULL,
                embedding BLOB NOT NULL,
                sha TEXT UNIQUE NOT NULL,
                ts TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_scrape_url ON scrape_items(url);
            CREATE INDEX IF NOT EXISTS idx_scrape_ts ON scrape_items(ts);
            CREATE TABLE IF NOT EXISTS scrape_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
    return conn


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO scrape_meta (key, value) VALUES (?, ?)", (key, value)
    )


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute(
        "SELECT value FROM scrape_meta WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else default


# ─── Helpers ─────────────────────────────────────────────────────────


def item_sha(url: str, prompt: str) -> str:
    return hashlib.sha1(f"{url}|{prompt}".encode()).hexdigest()[:16]


def denormalize(extraction: Any) -> str:
    """Flatten a scrapegraph extraction (dict/list/scalar) to plain text for
    embedding + snippet display. Privacy-safe: drops any field named
    'api_key' / 'secret' / 'token' / 'password' at any nesting depth."""
    SENSITIVE = {"api_key", "secret", "token", "password", "auth", "credential"}

    def walk(node: Any) -> list[str]:
        if isinstance(node, dict):
            out = []
            for k, v in node.items():
                if str(k).lower() in SENSITIVE:
                    continue
                out.append(f"{k}: " + " | ".join(walk(v)))
            return out
        if isinstance(node, list):
            return [" / ".join(walk(item)) for item in node]
        if node is None:
            return [""]
        return [str(node)]

    return "\n".join(walk(extraction)).strip()


def extract_title(extraction: Any) -> str:
    if isinstance(extraction, dict):
        for k in ("title", "name", "headline", "page_title"):
            if k in extraction and isinstance(extraction[k], str):
                return extraction[k][:200]
    return ""


_LLM_CACHE_PATH = _p.SCRAPE_DIR / "llm_endpoint.json"


# ─── Ollama-hosted chat-model recommendations for ScrapeGraphAI ──────
#
# Curated 2026-05-12 (see kaizen agent survey of ollama.com/search,
# ScrapeGraphAI README, and the Ollama model library). Ranked: the
# detect_llm Ollama branch prefers a recommended model over an
# arbitrarily-listed one when both are installed.
#
# Source for "why" + "tier" is the survey result; the picks reflect:
#   - Reliable JSON output under Ollama's `format=json` flag
#   - ≥32K context (full-page scrapes hit 5K–50K tokens of HTML)
#   - Tool-style structured-output discipline
#   - Local-friendly size (laptop tier through GPU-best)
#
# Order = preference rank (best first).
OLLAMA_SCRAPE_RECOMMENDATIONS = [
    {
        "name": "granite4.1:8b", "size_gb": 5.3, "ctx_k": 128, "tier": "winner",
        "why": "Apache 2.0, 128K ctx, model card explicitly cites 'structured JSON output' "
               "+ tool-calling + RAG-tuned + multilingual. The only pick whose official "
               "documentation matches ScrapeGraphAI's exact workload (HTML → JSON via "
               "format=json). Smallest of the strong picks too (5.3GB).",
    },
    {
        "name": "qwen3.5:9b", "size_gb": 6.6, "ctx_k": 256, "tier": "generalist",
        "why": "Apache 2.0, 256K ctx, unified vision-language + tools + thinking. Best "
               "all-rounder when you also use the model for general chat / coding / "
               "reasoning beyond scrape. Wider context than granite for long pages.",
    },
    {
        "name": "gemma4:e4b", "size_gb": 9.6, "ctx_k": 128, "tier": "multimodal",
        "why": "Apache 2.0, 128K ctx, 4.5B effective params (8B with embeddings), native "
               "function-calling, multimodal (text + image + audio). Use when scraping "
               "pages with significant image content.",
    },
    {
        "name": "qwen3.5:4b", "size_gb": 3.4, "ctx_k": 256, "tier": "sweet-small",
        "why": "Smaller qwen3.5 — same 256K ctx + vision/tools/thinking surface as :9b, "
               "fits in 4GB RAM. Good for mid-range laptops.",
    },
    {
        "name": "granite4.1:3b", "size_gb": 2.1, "ctx_k": 128, "tier": "laptop",
        "why": "≤4GB tier with the same JSON-output + tool-calling discipline as the "
               "winner. Slower / less accurate on dense HTML but the same documented "
               "structured-output reliability.",
    },
    {
        "name": "qwen3.6:27b", "size_gb": 17.0, "ctx_k": 256, "tier": "quality",
        "why": "Newest qwen (~2 weeks old as of 2026-05-12), agentic + coding focus, "
               "256K ctx. For users with 24GB+ RAM.",
    },
    {
        "name": "qwen3.5:35b", "size_gb": 24.0, "ctx_k": 256, "tier": "best-moe",
        "why": "Heaviest reasonable pick. 256K ctx + multimodal at 24GB. "
               "Quality ceiling for local-only ScrapeGraphAI workloads.",
    },
]
RECOMMENDED_NAMES = [r["name"] for r in OLLAMA_SCRAPE_RECOMMENDATIONS]


def _model_name_matches(installed: str, recommended: str) -> bool:
    """Loose match: Ollama lists models with optional `:tag` suffix.
    `qwen2.5:7b` should match an installed `qwen2.5:7b-instruct-q4_0`.
    Also handle the family-only case where someone pulled `qwen2.5` and
    we recommend `qwen2.5:7b`."""
    if installed == recommended:
        return True
    # qwen2.5:7b matches qwen2.5:7b-instruct-q4_0
    if installed.startswith(recommended + "-"):
        return True
    # qwen2.5:7b matches qwen2.5:7b-anything via `:`
    if installed.startswith(recommended + ":"):
        return True
    return False


def pick_best_chat_model(installed: list[str]) -> str | None:
    """Given a list of locally-installed Ollama model names, return the
    highest-ranked recommendation if one is installed, else the first
    chat-shaped (non-embed) installed model, else None."""
    # Prefer in recommendation order.
    for rec in RECOMMENDED_NAMES:
        for inst in installed:
            if _model_name_matches(inst, rec):
                return inst
    # Fall back: first non-embed.
    for inst in installed:
        if not _embed.is_embedding_model_name(inst):
            return inst
    return None


def _probe_ollama_all_models(base_url: str, timeout: float) -> list[str]:
    """List ALL installed Ollama models. Returns names, oldest-installed
    first (Ollama's default order). Empty list on connection failure or
    parse error — caller decides what to do.

    Stdlib-only — we don't import the `ollama` package here so this stays
    on the python3-only path of bin/kaizen-scrape. Richer metadata (size,
    digest, modified_at) is available via `/kaizen:models list`."""
    import urllib.request
    import urllib.error
    url = base_url.rstrip("/") + "/api/tags"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return []
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return []
    items = data.get("models") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return [str(it.get("name") or it.get("model") or "") for it in items if isinstance(it, dict)]


def _probe_endpoint(base_url: str, list_path: str, model_field: str, timeout: float) -> str | None:
    """Hit <base_url><list_path>; return the first model name or None.

    Stdlib-only (urllib). Used for zero-config detection of llama.cpp
    server / Ollama / LM Studio / vLLM / text-gen-webui."""
    import urllib.request
    import urllib.error
    url = base_url.rstrip("/") + list_path
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return None
    # OpenAI shape: {"data": [{"id": "..."}, ...]}
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        for item in data["data"]:
            if isinstance(item, dict) and item.get(model_field):
                return str(item[model_field])
    # Ollama shape: {"models": [{"name": "..."}, ...]}
    if isinstance(data, dict) and isinstance(data.get("models"), list):
        for item in data["models"]:
            if isinstance(item, dict) and item.get(model_field):
                return str(item[model_field])
    return None


def detect_llm(refresh: bool = False, verbose: bool = False) -> dict | None:
    """Zero-config probe of common local-LLM endpoints. Returns {provider,
    model, base_url} on success, None otherwise. Caches the result to
    SCRAPE_DIR/llm_endpoint.json so subsequent calls skip the probe.

    Args:
        refresh: ignore the cache and probe afresh.
        verbose: print each probe attempt to stderr.
    """
    if not refresh and _LLM_CACHE_PATH.is_file():
        try:
            cached = json.loads(_LLM_CACHE_PATH.read_text())
            if cached.get("model") and cached.get("base_url"):
                return cached
        except (OSError, json.JSONDecodeError):
            pass

    for provider, base_url, list_path, model_field in _cfg.SCRAPE_LLM_PROBES:
        if verbose:
            sys.stderr.write(f"  probing {base_url}{list_path}...")
        # v1.29.0+: for Ollama, list ALL installed models and pick the
        # highest-ranked recommended chat model. For other providers we
        # still take the first listed name (the provider's own ordering).
        if provider == "ollama":
            installed = _probe_ollama_all_models(base_url, _cfg.SCRAPE_LLM_PROBE_TIMEOUT)
            if not installed:
                if verbose:
                    sys.stderr.write(" ✗\n")
                continue
            model = pick_best_chat_model(installed)
            if not model:
                if verbose:
                    sys.stderr.write(f" ∘ only embedding models installed at {base_url}\n")
                continue
            ranked_against = next(
                (rec for rec in RECOMMENDED_NAMES if _model_name_matches(model, rec)),
                None,
            )
            if verbose:
                tag = f" (✓ recommended: {ranked_against})" if ranked_against else " (no recommended chat model installed; using first available)"
                sys.stderr.write(f" ✓ {provider}/{model}{tag}\n")
        else:
            model = _probe_endpoint(base_url, list_path, model_field, _cfg.SCRAPE_LLM_PROBE_TIMEOUT)
            if not model:
                if verbose:
                    sys.stderr.write(" ✗\n")
                continue
            if _embed.is_embedding_model_name(model):
                if verbose:
                    sys.stderr.write(f" ∘ {provider}/{model} (embedding-only — skipping for chat)\n")
                continue
            if verbose:
                sys.stderr.write(f" ✓ {provider}/{model}\n")
        kind = "chat"
        result = {"provider": provider, "model": model, "base_url": base_url, "kind": kind}
        try:
            _LLM_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _LLM_CACHE_PATH.write_text(json.dumps(result, indent=2))
        except OSError:
            pass
        return result
    return None


def llm_config() -> dict:
    """Resolve the LLM config for scrapegraph-ai. Priority order:
      1. Explicit env / config: KAIZEN_SCRAPE_LLM_MODEL + KAIZEN_SCRAPE_LLM_BASE_URL
      2. Auto-detect cache (zero-config) — re-uses last successful probe
      3. Live probe of SCRAPE_LLM_PROBES (one-time per cache miss)
      4. Hard failure with actionable error
    """
    model = _cfg.SCRAPE_LLM_MODEL
    base_url = _cfg.SCRAPE_LLM_BASE_URL

    # Auto-detect path (model unset OR auto enabled with model unset)
    if not model and _cfg.SCRAPE_LLM_AUTO:
        det = detect_llm()
        if det is None:
            sys.stderr.write(
                "kaizen-scrape: no local LLM endpoint detected and "
                "KAIZEN_SCRAPE_LLM_MODEL not set.\n"
                "  Start one of:\n"
                "    llama-server -m <model.gguf> --port 8080    (llama.cpp)\n"
                "    ollama serve                                 (ollama)\n"
                "  Or set explicitly:\n"
                "    export KAIZEN_SCRAPE_LLM_MODEL=openai/gpt-4o-mini\n"
                "    export OPENAI_API_KEY=...\n"
                "  Or probe manually: kaizen-scrape detect-llm --refresh\n"
            )
            sys.exit(2)
        model = f"{det['provider']}/{det['model']}"
        base_url = det["base_url"]

    cfg: dict = {"llm": {"model": model, "temperature": 0}}

    # v1.29.3+: pull model_tokens from the recommendations table when the
    # model is in our curated list. ScrapeGraphAI's default (8192) silently
    # truncates ≈90% of a full HTML page when the model supports 128K-256K.
    bare_model = model.split("/", 1)[1] if "/" in model else model
    ctx_tokens = 32_768  # sane non-truncating default
    for rec in OLLAMA_SCRAPE_RECOMMENDATIONS:
        if _model_name_matches(bare_model, rec["name"]):
            ctx_tokens = rec["ctx_k"] * 1024
            break

    if model.startswith("ollama/"):
        cfg["llm"]["base_url"] = base_url or "http://localhost:11434"
        cfg["llm"]["format"] = "json"
        # v1.29.4+: per https://docs.scrapegraphai.com (Context7 lookup),
        # model_tokens IS supported on the ollama/* path — the OllamaLLM
        # provider reads it and skips passing through to the underlying
        # client. Documented at:
        #   /scrapegraphai/scrapegraph-ai/llms.txt
        cfg["llm"]["model_tokens"] = ctx_tokens
    elif model.startswith("openai/"):
        api_key = os.environ.get("OPENAI_API_KEY")
        if base_url:
            # openai/* with base_url override = llama.cpp / LM Studio / vLLM /
            # Ollama-via-/v1/ etc. These don't validate the key, so a
            # placeholder works.
            cfg["llm"]["base_url"] = base_url
            cfg["llm"]["api_key"] = api_key or "sk-local-noop"
            # v1.29.3+: force JSON mode for OpenAI-compat endpoints. Without
            # this, granite4.1 / qwen3.5 return Markdown and ScrapeGraphAI's
            # parser raises OutputParserException.
            cfg["llm"]["model_kwargs"] = {
                "response_format": {"type": "json_object"},
            }
            # NB: model_tokens is NOT settable on the openai/* path — the
            # provider forwards every cfg["llm"] kwarg to ChatOpenAI which
            # rejects it with TypeError. We register the ctx via the
            # `models_tokens` global dict at scraper-load time instead.
            # See _register_recommendation_tokens() below.
        elif api_key:
            cfg["llm"]["api_key"] = api_key
            cfg["llm"]["model_kwargs"] = {
                "response_format": {"type": "json_object"},
            }
        else:
            sys.stderr.write(
                "kaizen-scrape: KAIZEN_SCRAPE_LLM_MODEL is openai/* with no "
                "base_url and OPENAI_API_KEY is not set.\n"
                "  Either set OPENAI_API_KEY, or set KAIZEN_SCRAPE_LLM_BASE_URL\n"
                "  to point at a local OpenAI-compatible server.\n"
            )
            sys.exit(2)
    cfg["headless"] = True
    cfg["verbose"] = False
    return cfg


def _register_recommendation_tokens() -> None:
    """Inject OLLAMA_SCRAPE_RECOMMENDATIONS into ScrapeGraphAI's hardcoded
    models_tokens dict (v1.29.4+).

    ScrapeGraphAI ships a static dict at `scrapegraphai.helpers.models_tokens
    .models_tokens` keyed by provider → model → max_tokens. If a model name
    is missing, the lookup falls through to the default 8192 and emits:

        "Max input tokens for model X not found, please specify the
         model_tokens parameter in the llm section of the graph
         configuration. Using default token size: 8192"

    Our curated picks (granite4.1, qwen3.5, qwen3.6, gemma4, qwen3-embedding)
    aren't in the upstream dict yet. Registering them at scraper load
    silences the warning AND honors the full context budget on the openai/*
    path (where cfg["llm"]["model_tokens"] would propagate to ChatOpenAI
    and raise TypeError).

    Idempotent — safe to call multiple times. Defensive — silent no-op if
    scrapegraphai isn't installed (e.g. running stats / detect-llm via
    plain python3 instead of `uv run --script`)."""
    try:
        from scrapegraphai.helpers.models_tokens import models_tokens  # type: ignore
    except ImportError:
        return
    entries = {rec["name"]: rec["ctx_k"] * 1024 for rec in OLLAMA_SCRAPE_RECOMMENDATIONS}
    for provider in ("openai", "ollama"):
        models_tokens.setdefault(provider, {}).update(entries)


# ─── PocketFlow async pipeline (vendored AsyncNode/AsyncFlow) ────────


class AsyncNode:
    async def prep_async(self, store: dict) -> Any: return None
    async def exec_async(self, prep: Any) -> Any: return None
    async def post_async(self, store: dict, prep: Any, res: Any) -> str | None: return "default"

    async def run_async(self, store: dict) -> str | None:
        prep = await self.prep_async(store)
        res = await self.exec_async(prep)
        return await self.post_async(store, prep, res)


class AsyncFlow:
    def __init__(self, start: AsyncNode) -> None:
        self.start = start
        self.successors: dict[tuple[AsyncNode, str], AsyncNode] = {}

    def add_successor(self, node: AsyncNode, action: str, succ: AsyncNode) -> None:
        self.successors[(node, action)] = succ

    async def run_async(self, store: dict) -> None:
        cur: AsyncNode | None = self.start
        while cur is not None:
            action = await cur.run_async(store) or "default"
            cur = self.successors.get((cur, action))


class FetchURLs(AsyncNode):
    """Trivial pass-through — validates urls + prompt are in the store."""

    async def post_async(self, store, prep, res):
        urls = store.get("urls") or []
        if not urls:
            store["error"] = "no urls provided"
            return None  # halt
        store["prompt"] = store.get("prompt") or _cfg.SCRAPE_DEFAULT_PROMPT
        return "default"


class ScrapeFanOut(AsyncNode):
    """Fan-out: SmartScraperGraph per URL via asyncio.to_thread."""

    async def exec_async(self, _prep):
        return None  # unused; we use prep_async + store directly

    async def prep_async(self, store):
        SmartScraperGraph = _load_scraper_cls()
        cfg = llm_config()
        urls: list[str] = store["urls"]
        prompt: str = store["prompt"]

        def _scrape_one(u: str) -> dict:
            try:
                g = SmartScraperGraph(prompt=prompt, source=u, config=cfg)
                result = g.run()
                return {"url": u, "ok": True, "extraction": result}
            except Exception as e:
                return {"url": u, "ok": False, "error": f"{type(e).__name__}: {e}"}

        tasks = [asyncio.to_thread(_scrape_one, u) for u in urls]
        return await asyncio.gather(*tasks)

    async def post_async(self, store, results, _exec):
        store["scrape_results"] = results
        return "default"


class Synthesize(AsyncNode):
    """Flatten + sanitize each extraction to {url, title, text, content_json}."""

    async def post_async(self, store, prep, res):
        synth = []
        for r in store["scrape_results"]:
            if not r.get("ok"):
                synth.append({"url": r["url"], "skip": True, "error": r.get("error", "?")})
                continue
            ext = r["extraction"]
            synth.append({
                "url": r["url"],
                "title": extract_title(ext),
                "text": denormalize(ext)[:SNIPPET_MAX * 4],  # keep more for embedding
                "content_json": json.dumps(ext, ensure_ascii=False, default=str),
            })
        store["synth"] = synth
        return "default"


class EmbedAndPersist(AsyncNode):
    """Compute embeddings + write rows to SQLite."""

    async def post_async(self, store, prep, res):
        if store.get("no_embed"):
            store["persisted"] = 0
            return None

        conn = open_db(create=True)
        prompt = store["prompt"]
        ts = dt.datetime.now(dt.timezone.utc).isoformat()
        written = 0
        actual_dim = 0
        actual_model = ""
        for item in store["synth"]:
            if item.get("skip"):
                continue
            text = item["text"]
            embed_input = (item["title"] + "\n" + text).strip()[:SNIPPET_MAX * 4]
            blob, dim = _embed.embed_one(embed_input)
            actual_dim = dim
            sha = item_sha(item["url"], prompt)
            conn.execute(
                """INSERT OR REPLACE INTO scrape_items
                   (url, prompt, title, content_json, text_extract, embedding, sha, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item["url"], prompt, item["title"],
                    item["content_json"], text[:SNIPPET_MAX],
                    blob, sha, ts,
                ),
            )
            written += 1
        backend = _embed.resolve_backend()
        actual_model = backend.get("model", DEFAULT_MODEL)
        set_meta(conn, "model", actual_model)
        set_meta(conn, "dim", str(actual_dim or DEFAULT_DIM))
        set_meta(conn, "backend_kind", backend.get("kind", "local"))
        set_meta(conn, "last_scrape_ts", ts)
        conn.commit()
        conn.close()
        store["persisted"] = written
        return None  # terminal


def build_flow() -> AsyncFlow:
    fetch = FetchURLs()
    scrape = ScrapeFanOut()
    synth = Synthesize()
    persist = EmbedAndPersist()
    flow = AsyncFlow(fetch)
    flow.add_successor(fetch, "default", scrape)
    flow.add_successor(scrape, "default", synth)
    flow.add_successor(synth, "default", persist)
    return flow


# ─── do_* helpers (mirror knowledge/onboard pattern) ─────────────────


async def do_scrape(urls: list[str], prompt: str, no_embed: bool = False) -> dict:
    store: dict = {"urls": urls, "prompt": prompt, "no_embed": no_embed}
    flow = build_flow()
    await flow.run_async(store)
    if store.get("error"):
        return {"ok": False, "error": store["error"]}
    return {
        "ok": True,
        "urls": len(urls),
        "persisted": store.get("persisted", 0),
        "results": store.get("synth", []),
        "db": str(DB_PATH),
    }


def do_search(query: str, top_k: int = 10) -> list[dict]:
    if not DB_PATH.is_file():
        return []
    conn = open_db(create=False)
    # v1.25.0+: use shared _embed backend (HTTP llama-server or fallback).
    np = _embed.require_numpy()
    qblob, _ = _embed.embed_one(query)
    qvec = np.frombuffer(qblob, dtype=np.float32).astype(
        np.float32
    )
    qnorm = qvec / (np.linalg.norm(qvec) + 1e-12)
    q_dim = qvec.shape[0]
    rows = conn.execute("SELECT * FROM scrape_items").fetchall()
    scored = []
    skipped_mismatch = 0
    for r in rows:
        evec = np.frombuffer(r["embedding"], dtype=np.float32)
        if evec.shape[0] != q_dim:
            # v1.25.0+: dim mismatch (e.g. backend switched from 384 → 768).
            # Skip but count; surface the count to the user.
            skipped_mismatch += 1
            continue
        score = float(np.dot(qnorm, evec / (np.linalg.norm(evec) + 1e-12)))
        scored.append((score, r))
    if skipped_mismatch:
        sys.stderr.write(
            f"kaizen-scrape: skipped {skipped_mismatch} row(s) with dim != {q_dim} — "
            f"reindex with `clear` + `scrape` after backend change\n"
        )
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for s, r in scored[:top_k]:
        out.append({
            "score": round(s, 4),
            "id": r["id"], "url": r["url"], "title": r["title"],
            "snippet": (r["text_extract"] or "")[:200],
            "ts": r["ts"],
        })
    conn.close()
    return out


def do_stats() -> dict:
    if not DB_PATH.is_file():
        return {"indexed": False, "db_path": str(DB_PATH)}
    conn = open_db(create=False)
    total = conn.execute("SELECT COUNT(*) FROM scrape_items").fetchone()[0]
    out = {
        "indexed": True,
        "db_path": str(DB_PATH),
        "model": get_meta(conn, "model", ""),
        "dim": get_meta(conn, "dim", ""),
        "last_scrape_ts": get_meta(conn, "last_scrape_ts", ""),
        "total": total,
    }
    conn.close()
    return out


def do_get(item_id: int) -> dict | None:
    if not DB_PATH.is_file():
        return None
    conn = open_db(create=False)
    r = conn.execute("SELECT * FROM scrape_items WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    if not r:
        return None
    out = {k: r[k] for k in r.keys() if k != "embedding"}
    try:
        out["content"] = json.loads(out["content_json"])
    except (json.JSONDecodeError, TypeError):
        pass
    return out


def do_list(limit: int = 20) -> list[dict]:
    if not DB_PATH.is_file():
        return []
    conn = open_db(create=False)
    rows = conn.execute(
        "SELECT id, url, title, ts FROM scrape_items ORDER BY ts DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [{k: r[k] for k in r.keys()} for r in rows]


# ─── CLI ─────────────────────────────────────────────────────────────


def cmd_scrape(args):
    urls = [args.url] if args.url else []
    prompt = args.prompt or _cfg.SCRAPE_DEFAULT_PROMPT
    result = asyncio.run(do_scrape(urls, prompt, no_embed=args.no_embed))
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        if not result["ok"]:
            print(f"kaizen-scrape: {result['error']}", file=sys.stderr)
            sys.exit(1)
        print(
            f"kaizen-scrape: persisted {result['persisted']}/{result['urls']} item(s) "
            f"to {result['db']}",
            file=sys.stderr,
        )
        for r in result["results"]:
            if r.get("skip"):
                print(f"  ! {r['url']}  ({r.get('error','skip')})", file=sys.stderr)
            else:
                print(f"  ✓ {r['url']}  ({r.get('title','(no title)')[:60]})", file=sys.stderr)


def cmd_batch(args):
    p = Path(args.file)
    if not p.is_file():
        sys.exit(f"kaizen-scrape: file not found: {args.file}")
    urls = [line.strip() for line in p.read_text().splitlines() if line.strip() and not line.startswith("#")]
    prompt = args.prompt or _cfg.SCRAPE_DEFAULT_PROMPT
    result = asyncio.run(do_scrape(urls, prompt, no_embed=args.no_embed))
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"kaizen-scrape: batch — {result['persisted']}/{result['urls']} persisted")


def cmd_search(args):
    results = do_search(args.query, top_k=args.top_k)
    if args.json:
        print(json.dumps(results, indent=2))
        return
    for r in results:
        print(f"  {r['score']:.3f}  [{r['id']}] {r['title'] or '(untitled)'}")
        print(f"           → {r['url']}")
        if r["snippet"]:
            print(f"           {r['snippet'][:120]}")


def cmd_stats(args):
    s = do_stats()
    if not s.get("indexed"):
        print(f"kaizen-scrape: no index at {s['db_path']} — run `scrape <url>` first")
        return
    print(f"db:        {s['db_path']}")
    print(f"model:     {s['model'] or '?'}")
    print(f"dim:       {s['dim'] or '?'}")
    print(f"last:      {s['last_scrape_ts'] or '?'}")
    print(f"total:     {s['total']}")


def cmd_get(args):
    r = do_get(args.id)
    if r is None:
        sys.exit(f"id {args.id} not found")
    print(json.dumps(r, indent=2, default=str))


def cmd_list(args):
    rows = do_list(limit=args.limit)
    if not rows:
        print("(empty)")
        return
    for r in rows:
        print(f"  [{r['id']}] {r['ts']}  {r['url']}")
        if r["title"]:
            print(f"           {r['title'][:80]}")


def cmd_path(args):
    print(DB_PATH)


def cmd_clear(args):
    if DB_PATH.is_file():
        DB_PATH.unlink()
        print(f"kaizen-scrape: cleared {DB_PATH}", file=sys.stderr)
    else:
        print("kaizen-scrape: no index to clear", file=sys.stderr)


def cmd_recommend(args):
    """List the Ollama-hosted chat-model picks for ScrapeGraphAI's
    JSON-extraction workload. Read-only — does not pull anything. To
    install, copy the `ollama pull` line OR run /kaizen:models pull <name>."""
    if args.json:
        print(json.dumps(OLLAMA_SCRAPE_RECOMMENDATIONS, indent=2))
        return

    # Detect what's already installed so we can mark them ✓.
    base_url = _cfg.SCRAPE_LLM_BASE_URL or "http://localhost:11434"
    installed = set(_probe_ollama_all_models(base_url, _cfg.SCRAPE_LLM_PROBE_TIMEOUT))

    print(f"Ollama chat-model picks for ScrapeGraphAI ({base_url})\n")
    print(f"{'STATUS':<8} {'NAME':<22} {'SIZE':>7}  {'CTX':>6}  TIER")
    print(f"{'-'*8} {'-'*22} {'-'*7}  {'-'*6}  ----")
    for rec in OLLAMA_SCRAPE_RECOMMENDATIONS:
        has_it = any(_model_name_matches(inst, rec["name"]) for inst in installed)
        status = "✓ pulled" if has_it else "·"
        print(f"{status:<8} {rec['name']:<22} {rec['size_gb']:>5.1f}GB  "
              f"{rec['ctx_k']:>4}K   {rec['tier']}")
    print()
    winner = OLLAMA_SCRAPE_RECOMMENDATIONS[0]["name"]
    print("Install the winner:")
    print(f"  /kaizen:models pull {winner}")
    print(f"  /kaizen:models pin-chat  {winner}")
    print("  source ~/.claude/.kaizen/profile.env")
    print()
    print("Why each pick:")
    for rec in OLLAMA_SCRAPE_RECOMMENDATIONS:
        print(f"  • {rec['name']:<18} — {rec['why']}")


def cmd_detect_llm(args):
    """Zero-config probe of common local-LLM endpoints."""
    det = detect_llm(refresh=args.refresh, verbose=True)
    if det is None:
        print("kaizen-scrape: no local LLM endpoint detected.", file=sys.stderr)
        print("Probed:", file=sys.stderr)
        for provider, base_url, list_path, _ in _cfg.SCRAPE_LLM_PROBES:
            print(f"  {provider:<8} {base_url}{list_path}", file=sys.stderr)
        print("Start one of:", file=sys.stderr)
        print("  llama-server -m <model.gguf> --port 8080    (llama.cpp)", file=sys.stderr)
        print("  ollama serve                                 (ollama)", file=sys.stderr)
        sys.exit(1)
    if args.json:
        print(json.dumps(det, indent=2))
    else:
        print(f"detected:  {det['provider']}/{det['model']}")
        print(f"base_url:  {det['base_url']}")
        print(f"cached at: {_LLM_CACHE_PATH}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kaizen-scrape",
        description="Scrape + synthesize web content into a semantic SQLite index. "
                    "PocketFlow pipeline + ScrapeGraphAI + sentence-transformers.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    psc = sub.add_parser("scrape", help="scrape one URL and index")
    psc.add_argument("url")
    psc.add_argument("--prompt", help=f"extraction prompt (default: {_cfg.SCRAPE_DEFAULT_PROMPT[:60]}…)")
    psc.add_argument("--no-embed", action="store_true", help="skip the embed + persist step")
    psc.add_argument("--json", action="store_true")
    psc.set_defaults(func=cmd_scrape)

    pb = sub.add_parser("batch", help="scrape a file of URLs (one per line)")
    pb.add_argument("file")
    pb.add_argument("--prompt")
    pb.add_argument("--no-embed", action="store_true")
    pb.add_argument("--json", action="store_true")
    pb.set_defaults(func=cmd_batch)

    psr = sub.add_parser("search")
    psr.add_argument("query")
    psr.add_argument("--top-k", type=int, default=10)
    psr.add_argument("--json", action="store_true")
    psr.set_defaults(func=cmd_search)

    pt = sub.add_parser("stats")
    pt.set_defaults(func=cmd_stats)

    pg = sub.add_parser("get")
    pg.add_argument("id", type=int)
    pg.set_defaults(func=cmd_get)

    pl = sub.add_parser("list")
    pl.add_argument("--limit", type=int, default=20)
    pl.set_defaults(func=cmd_list)

    pp = sub.add_parser("path")
    pp.set_defaults(func=cmd_path)

    pc = sub.add_parser("clear")
    pc.set_defaults(func=cmd_clear)

    pdl = sub.add_parser(
        "detect-llm",
        help="zero-config probe of common local-LLM endpoints (llama.cpp/Ollama/LM Studio/vLLM/text-gen-webui)",
    )
    pdl.add_argument("--refresh", action="store_true", help="ignore the cached endpoint, probe afresh")
    pdl.add_argument("--json", action="store_true")
    pdl.set_defaults(func=cmd_detect_llm)

    pre = sub.add_parser(
        "recommend",
        help="list curated Ollama chat-model picks for ScrapeGraphAI (qwen2.5:7b wins)",
    )
    pre.add_argument("--json", action="store_true")
    pre.set_defaults(func=cmd_recommend)

    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
