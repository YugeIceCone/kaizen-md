#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "ollama>=0.4",
# ]
# ///
"""kaizen models — Ollama-backed local model management (v1.26.0+).

Wraps the official `ollama` Python client (https://github.com/ollama/ollama-python)
so users get a single slash command for the full model lifecycle without leaving
Claude Code. Pairs with the Ollama embedding backend in `_embed.py`.

## Subcommands

    models                     → list local models (default)
    models list                → same
    models ps                  → currently-loaded (in-memory) models
    models pull <name>         → download a model (progress streamed)
    models show <name>         → metadata + parameters
    models delete <name>       → remove from local cache
    models cp <src> <dst>      → clone with a new name
    models embed <model> <text> → quick smoke test, prints dim + first 8 floats
    models chat  <model> <text> → quick chat smoke test, prints response
    models pin-embed <model>   → write KAIZEN_EMBED_* to ~/.claude/.kaizen/data/profile.env
    models pin-chat  <model>   → write KAIZEN_SCRAPE_LLM_* to profile.env
    models host                → print the active Ollama host
    models --help              → this message

## Why this command exists

Before v1.26.0, kaizen probed for OpenAI-shape HTTP endpoints and required
either a running llama-server (user-managed) or a heavy sentence-transformers
install for the fallback. Ollama bundles model download / lifecycle / serving
into one process — `ollama pull nomic-embed-text` is the new "install an embed
model". This command surfaces that lifecycle inside Claude Code's slash UI.

## Env

    OLLAMA_HOST           default http://localhost:11434 (Ollama's default)
    KAIZEN_OLLAMA_HOST    kaizen-specific override, wins over OLLAMA_HOST
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable, Optional

# ─── Connect ──────────────────────────────────────────────────────────


def _host() -> str:
    return (
        os.environ.get("KAIZEN_OLLAMA_HOST")
        or os.environ.get("OLLAMA_HOST")
        or "http://localhost:11434"
    )


def _client():
    try:
        import ollama  # type: ignore
    except ImportError:
        sys.stderr.write(
            "kaizen models: ollama package not installed.\n"
            "Re-invoke through the wrapper: bin/kaizen-models (uses `uv run --script`).\n"
        )
        sys.exit(1)
    return ollama.Client(host=_host())


def _check_reachable() -> Optional[str]:
    """Return None if Ollama is reachable, else a human-readable error string."""
    try:
        import urllib.error
        import urllib.request
        with urllib.request.urlopen(_host() + "/api/version", timeout=2) as r:
            if r.status != 200:
                return f"Ollama at {_host()} returned HTTP {r.status}"
    except urllib.error.URLError as e:
        return f"Ollama at {_host()} unreachable ({e.__class__.__name__}: {e})"
    except OSError as e:
        return f"Ollama at {_host()} connection error ({e})"
    return None


# ─── Subcommands ──────────────────────────────────────────────────────


def _human_bytes(n: int) -> str:
    """Format byte size as KB/MB/GB."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n} B"


def _normalize_list(items: Iterable) -> list[dict]:
    """ollama-python returns ListResponse with .models; older / dict shapes differ."""
    if hasattr(items, "models"):
        items = items.models
    out = []
    for m in items:
        if hasattr(m, "model"):
            out.append({
                "name": m.model,
                "size": int(getattr(m, "size", 0) or 0),
                "modified_at": str(getattr(m, "modified_at", "") or ""),
                "digest": getattr(m, "digest", "")[:12],
                "family": (getattr(m, "details", None) and getattr(m.details, "family", "")) or "",
                "param_size": (getattr(m, "details", None) and getattr(m.details, "parameter_size", "")) or "",
                "quant": (getattr(m, "details", None) and getattr(m.details, "quantization_level", "")) or "",
            })
        elif isinstance(m, dict):
            d = m.get("details", {}) or {}
            out.append({
                "name": m.get("name") or m.get("model", ""),
                "size": int(m.get("size", 0) or 0),
                "modified_at": str(m.get("modified_at", "") or ""),
                "digest": (m.get("digest") or "")[:12],
                "family": d.get("family", ""),
                "param_size": d.get("parameter_size", ""),
                "quant": d.get("quantization_level", ""),
            })
    return out


def cmd_list(args) -> int:
    err = _check_reachable()
    if err:
        sys.stderr.write(f"kaizen models: {err}\n")
        sys.stderr.write("  Start Ollama: `ollama serve` (or `systemctl --user start ollama`)\n")
        return 1
    client = _client()
    models = _normalize_list(client.list())
    if args.json:
        print(json.dumps(models, indent=2))
        return 0
    if not models:
        print("(no local models — pull one with: /kaizen:models pull <name>)")
        print("  suggestions: nomic-embed-text  (embed, ~270MB)")
        print("               qwen2.5:3b        (chat, ~2GB)")
        print("               llama3.2:1b       (chat, ~1.3GB)")
        return 0
    # 5-column table
    print(f"{'NAME':<40} {'SIZE':>10}  {'FAMILY':<14} {'PARAMS':<8} QUANT")
    for m in models:
        print(
            f"{m['name']:<40} {_human_bytes(m['size']):>10}  "
            f"{m['family']:<14} {m['param_size']:<8} {m['quant']}"
        )
    return 0


def cmd_ps(args) -> int:
    err = _check_reachable()
    if err:
        sys.stderr.write(f"kaizen models: {err}\n")
        return 1
    client = _client()
    items = client.ps()
    if hasattr(items, "models"):
        items = items.models
    if not items:
        print("(no models currently loaded in memory)")
        return 0
    print(f"{'NAME':<40} {'SIZE':>10}  EXPIRES")
    for m in items:
        name = getattr(m, "model", None) or m.get("name", "")
        size = int(getattr(m, "size_vram", 0) or getattr(m, "size", 0) or 0)
        exp = getattr(m, "expires_at", None) or m.get("expires_at", "")
        print(f"{name:<40} {_human_bytes(size):>10}  {exp}")
    return 0


def cmd_pull(args) -> int:
    err = _check_reachable()
    if err:
        sys.stderr.write(f"kaizen models: {err}\n")
        return 1
    client = _client()
    last_status = ""
    try:
        for progress in client.pull(args.name, stream=True):
            status = getattr(progress, "status", None) or progress.get("status", "")
            completed = getattr(progress, "completed", None) or progress.get("completed", 0)
            total = getattr(progress, "total", None) or progress.get("total", 0)
            if total and isinstance(total, int) and total > 0:
                pct = (completed / total) * 100 if completed else 0
                line = f"\r  {status}: {_human_bytes(completed)} / {_human_bytes(total)} ({pct:.1f}%)"
                sys.stderr.write(line.ljust(80))
                sys.stderr.flush()
            elif status != last_status:
                sys.stderr.write(f"\n  {status}")
                sys.stderr.flush()
                last_status = status
    except Exception as e:
        # ollama._types.ResponseError ("pull model manifest: file does not
        # exist") + network errors. Catch broadly and surface cleanly so
        # callers see exit code 1 instead of a Python traceback.
        sys.stderr.write(f"\nkaizen models: pull failed — {e.__class__.__name__}: {e}\n")
        return 1
    sys.stderr.write("\n")
    print(f"✓ pulled {args.name}")
    return 0


def cmd_show(args) -> int:
    err = _check_reachable()
    if err:
        sys.stderr.write(f"kaizen models: {err}\n")
        return 1
    client = _client()
    info = client.show(args.name)
    if args.json:
        # ShowResponse → dict via vars() if not already; fall back to str
        try:
            payload = info.model_dump() if hasattr(info, "model_dump") else dict(info)
        except Exception:
            payload = {"raw": str(info)}
        print(json.dumps(payload, indent=2, default=str))
        return 0
    # Human-readable
    print(f"  model:        {args.name}")
    for attr in ("modelfile", "parameters", "template", "license"):
        v = getattr(info, attr, None) or (info.get(attr, "") if isinstance(info, dict) else "")
        if v:
            label = attr if attr != "modelfile" else "Modelfile"
            print(f"  {label}: (set)")
    details = getattr(info, "details", None) or (info.get("details", {}) if isinstance(info, dict) else {})
    if details:
        for k in ("family", "parameter_size", "quantization_level", "format"):
            v = getattr(details, k, None) or (details.get(k, "") if isinstance(details, dict) else "")
            if v:
                print(f"  {k}: {v}")
    return 0


def cmd_delete(args) -> int:
    err = _check_reachable()
    if err:
        sys.stderr.write(f"kaizen models: {err}\n")
        return 1
    client = _client()
    if not args.force:
        confirm = input(f"delete model '{args.name}'? [y/N] ")
        if confirm.strip().lower() not in ("y", "yes"):
            print("aborted")
            return 1
    client.delete(args.name)
    print(f"✓ deleted {args.name}")
    return 0


def cmd_cp(args) -> int:
    err = _check_reachable()
    if err:
        sys.stderr.write(f"kaizen models: {err}\n")
        return 1
    client = _client()
    client.copy(args.src, args.dst)
    print(f"✓ copied {args.src} → {args.dst}")
    return 0


def cmd_embed(args) -> int:
    err = _check_reachable()
    if err:
        sys.stderr.write(f"kaizen models: {err}\n")
        return 1
    client = _client()
    kwargs: dict = {"model": args.model, "input": args.text}
    if args.truncate is not None:
        kwargs["truncate"] = args.truncate
    if args.keep_alive:
        kwargs["keep_alive"] = args.keep_alive
    resp = client.embed(**kwargs)
    embeddings = getattr(resp, "embeddings", None) or resp.get("embeddings", [])
    if not embeddings:
        sys.stderr.write("kaizen models: no embeddings in response\n")
        return 1
    vec = embeddings[0]
    if args.json:
        print(json.dumps({"model": args.model, "dim": len(vec), "embedding": list(vec)}))
        return 0
    print(f"  model: {args.model}")
    print(f"  dim:   {len(vec)}")
    print(f"  first 8: [{', '.join(f'{v:.4f}' for v in vec[:8])}]")
    return 0


def _read_text_arg(text: str | None) -> str:
    """Allow piping text via stdin when the positional is omitted/empty."""
    if text:
        return text
    if not sys.stdin.isatty():
        return sys.stdin.read()
    sys.stderr.write("kaizen models: no input text (pass as arg or pipe via stdin)\n")
    sys.exit(2)


def _load_image(path: str) -> str | bytes:
    """Ollama-python accepts a filesystem path string OR raw bytes; pass path
    directly so the client streams it."""
    p = Path(path).expanduser()
    if not p.is_file():
        sys.stderr.write(f"kaizen models: --image not found: {p}\n")
        sys.exit(2)
    return str(p)


def _parse_format(spec: str | None):
    """Parse --format. Accepts:
      - 'json'        → Ollama's free-form JSON mode
      - '@schema.json' → load schema dict from file
      - inline JSON   → parse as schema dict"""
    if not spec:
        return None
    if spec == "json":
        return "json"
    if spec.startswith("@"):
        return json.loads(Path(spec[1:]).expanduser().read_text())
    try:
        return json.loads(spec)
    except json.JSONDecodeError:
        sys.stderr.write(
            f"kaizen models: --format must be 'json', '@path.json', or inline JSON; got: {spec[:60]}\n"
        )
        sys.exit(2)


def cmd_chat(args) -> int:
    err = _check_reachable()
    if err:
        sys.stderr.write(f"kaizen models: {err}\n")
        return 1
    client = _client()
    text = _read_text_arg(args.text)
    msg: dict = {"role": "user", "content": text}
    if args.image:
        msg["images"] = [_load_image(p) for p in args.image]

    kwargs: dict = {
        "model": args.model,
        "messages": [msg],
        "stream": args.stream,
    }
    if args.think:
        kwargs["think"] = True
    fmt = _parse_format(args.format)
    if fmt is not None:
        kwargs["format"] = fmt
    if args.keep_alive:
        kwargs["keep_alive"] = args.keep_alive
    options: dict = {}
    if args.temperature is not None:
        options["temperature"] = args.temperature
    if options:
        kwargs["options"] = options

    if args.stream:
        full_content = []
        full_thinking = []
        in_thinking_block = False
        for chunk in client.chat(**kwargs):
            m = getattr(chunk, "message", None) or chunk.get("message", {})
            content = getattr(m, "content", None) or (m.get("content", "") if isinstance(m, dict) else "")
            thinking = getattr(m, "thinking", None) or (m.get("thinking", "") if isinstance(m, dict) else "")
            if thinking:
                if not in_thinking_block:
                    sys.stderr.write("\x1b[2m<thinking>\n")
                    in_thinking_block = True
                sys.stderr.write(thinking)
                sys.stderr.flush()
                full_thinking.append(thinking)
            if content:
                if in_thinking_block:
                    sys.stderr.write("\n</thinking>\x1b[0m\n")
                    in_thinking_block = False
                sys.stdout.write(content)
                sys.stdout.flush()
                full_content.append(content)
        if in_thinking_block:
            sys.stderr.write("\n</thinking>\x1b[0m\n")
        sys.stdout.write("\n")
        return 0

    resp = client.chat(**kwargs)
    m = getattr(resp, "message", None) or resp.get("message", {})
    thinking = getattr(m, "thinking", None) or (m.get("thinking", "") if isinstance(m, dict) else "")
    content = getattr(m, "content", None) or (m.get("content", "") if isinstance(m, dict) else "")
    if thinking and args.think:
        sys.stderr.write(f"\x1b[2m<thinking>\n{thinking}\n</thinking>\x1b[0m\n")
    if args.json:
        out = {"model": args.model, "content": content}
        if thinking:
            out["thinking"] = thinking
        print(json.dumps(out, indent=2))
    else:
        print(content)
    return 0


def cmd_web_search(args) -> int:
    """Ollama Cloud web-search. Requires an Ollama Cloud account (sign in via
    `ollama signin`) — the client picks up credentials automatically. Reads
    OLLAMA_API_KEY from env if set."""
    try:
        import ollama  # type: ignore
    except ImportError:
        sys.stderr.write("kaizen models: ollama package missing (use bin/kaizen-models wrapper).\n")
        return 1
    if not hasattr(ollama, "web_search"):
        sys.stderr.write(
            "kaizen models: web_search not available in this ollama-python version.\n"
            "  Upgrade: pip install --upgrade 'ollama>=0.5'\n"
        )
        return 1
    try:
        result = ollama.web_search(query=args.query, max_results=args.max_results)
    except Exception as e:
        sys.stderr.write(f"kaizen models: web_search failed ({e.__class__.__name__}: {e})\n")
        sys.stderr.write(
            "  This requires Ollama Cloud auth. Run `ollama signin` or set OLLAMA_API_KEY.\n"
        )
        return 1
    results = getattr(result, "results", None) or (result.get("results", []) if isinstance(result, dict) else [])
    if args.json:
        out_items = []
        for r in results:
            out_items.append({
                "title": getattr(r, "title", None) or r.get("title", ""),
                "url": getattr(r, "url", None) or r.get("url", ""),
                "snippet": getattr(r, "content", None) or r.get("content", ""),
            })
        print(json.dumps(out_items, indent=2))
        return 0
    for r in results:
        title = getattr(r, "title", None) or r.get("title", "")
        url = getattr(r, "url", None) or r.get("url", "")
        snippet = getattr(r, "content", None) or r.get("content", "")
        print(f"• {title}")
        print(f"  {url}")
        if snippet:
            snippet_one_line = " ".join(snippet.split())[:200]
            print(f"  {snippet_one_line}")
        print()
    return 0


# ─── Pin helpers (write profile.env) ──────────────────────────────────


def _profile_env_path() -> Path:
    return Path(os.environ.get("KAIZEN_PROFILE_ENV")
                or (Path.home() / ".claude" / ".kaizen" / "profile.env"))


def _set_env_lines(path: Path, updates: dict[str, str]) -> None:
    """Idempotently set `export KEY=VALUE` lines in profile.env."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text().splitlines() if path.is_file() else []
    out: list[str] = []
    keys_seen: set[str] = set()
    for line in existing:
        stripped = line.lstrip()
        replaced = False
        for k, v in updates.items():
            if stripped.startswith(f"export {k}="):
                out.append(f"export {k}={v}")
                keys_seen.add(k)
                replaced = True
                break
        if not replaced:
            out.append(line)
    for k, v in updates.items():
        if k not in keys_seen:
            out.append(f"export {k}={v}")
    # Preserve a trailing newline.
    text = "\n".join(out)
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text)


def cmd_pin_embed(args) -> int:
    host = _host()
    base_url = host.rstrip("/") + "/v1"
    updates = {
        "KAIZEN_EMBED_BACKEND": "http",
        "KAIZEN_EMBED_HTTP_BASE_URL": base_url,
        "KAIZEN_EMBED_HTTP_MODEL": args.model,
    }
    path = _profile_env_path()
    _set_env_lines(path, updates)
    print(f"✓ pinned embed model {args.model} via {base_url}")
    print(f"  wrote {path}")
    print(f"  reload: source {path}")
    return 0


def cmd_pin_chat(args) -> int:
    """Pin a chat model for scrape. v1.29.4+: writes the native Ollama
    provider prefix (`ollama/<model>`) + base URL without `/v1`. This
    lets ScrapeGraphAI take its ollama/* branch where `format=json` and
    `model_tokens` are documented config keys (the openai/* branch
    forwards both to ChatOpenAI which rejects model_tokens)."""
    host = _host().rstrip("/")
    # scrape uses provider-prefixed names. Ollama's native path is
    # `ollama/<model>` against the un-prefixed host. The openai/*
    # path stays available for users who explicitly set the env vars
    # to point at vLLM / LM Studio / real OpenAI.
    prefixed = args.model if "/" in args.model else f"ollama/{args.model}"
    updates = {
        "KAIZEN_SCRAPE_LLM_BASE_URL": host,
        "KAIZEN_SCRAPE_LLM_MODEL": prefixed,
        "KAIZEN_SCRAPE_LLM_AUTO": "0",
    }
    path = _profile_env_path()
    _set_env_lines(path, updates)
    print(f"✓ pinned chat model {prefixed} via {host}")
    print(f"  wrote {path}")
    print(f"  reload: source {path}")
    return 0


def cmd_host(args) -> int:
    print(_host())
    return 0


# ─── CLI ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-models",
        description="Ollama-backed local model management for kaizen.",
    )
    sub = p.add_subparsers(dest="cmd")

    pl = sub.add_parser("list", help="list local models")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_list)

    pps = sub.add_parser("ps", help="currently-loaded models")
    pps.set_defaults(func=cmd_ps)

    ppull = sub.add_parser("pull", help="download a model")
    ppull.add_argument("name")
    ppull.set_defaults(func=cmd_pull)

    pshow = sub.add_parser("show", help="model metadata")
    pshow.add_argument("name")
    pshow.add_argument("--json", action="store_true")
    pshow.set_defaults(func=cmd_show)

    pdel = sub.add_parser("delete", help="remove a model")
    pdel.add_argument("name")
    pdel.add_argument("--force", "-f", action="store_true", help="skip confirmation")
    pdel.set_defaults(func=cmd_delete)

    pcp = sub.add_parser("cp", help="clone a model under a new name")
    pcp.add_argument("src")
    pcp.add_argument("dst")
    pcp.set_defaults(func=cmd_cp)

    pe = sub.add_parser("embed", help="run an embedding")
    pe.add_argument("model")
    pe.add_argument("text")
    pe.add_argument("--truncate", type=lambda s: s.lower() in ("1", "true", "yes"),
                    default=None, help="truncate over-long input (default: model default)")
    pe.add_argument("--keep-alive", help="how long to keep the model loaded (e.g. 5m, 1h, -1)")
    pe.add_argument("--json", action="store_true")
    pe.set_defaults(func=cmd_embed)

    pc = sub.add_parser(
        "chat",
        help="run a chat completion (supports streaming, thinking, structured outputs, vision)",
    )
    pc.add_argument("model")
    pc.add_argument("text", nargs="?", default=None,
                    help="prompt text (or pipe via stdin)")
    pc.add_argument("--stream", action="store_true",
                    help="stream tokens to stdout as they arrive")
    pc.add_argument("--think", action="store_true",
                    help="enable reasoning for thinking-capable models (qwen3, deepseek-r1)")
    pc.add_argument("--format", default=None,
                    help="'json' | '@schema.json' | inline JSON schema (structured outputs)")
    pc.add_argument("--image", action="append", default=None,
                    help="path to image file (multimodal/vision); pass multiple times")
    pc.add_argument("--temperature", type=float, default=None)
    pc.add_argument("--keep-alive", help="how long to keep the model loaded")
    pc.add_argument("--json", action="store_true",
                    help="emit response as JSON (ignored when --stream)")
    pc.set_defaults(func=cmd_chat)

    pws = sub.add_parser(
        "web-search",
        help="Ollama Cloud web search (requires `ollama signin` or OLLAMA_API_KEY)",
    )
    pws.add_argument("query")
    pws.add_argument("--max-results", type=int, default=5)
    pws.add_argument("--json", action="store_true")
    pws.set_defaults(func=cmd_web_search)

    ppe = sub.add_parser("pin-embed", help="write embed model into profile.env")
    ppe.add_argument("model")
    ppe.set_defaults(func=cmd_pin_embed)

    ppc = sub.add_parser("pin-chat", help="write chat model into profile.env")
    ppc.add_argument("model")
    ppc.set_defaults(func=cmd_pin_chat)

    ph = sub.add_parser("host", help="print active Ollama host")
    ph.set_defaults(func=cmd_host)

    args = p.parse_args(argv)
    # Default: list
    if not args.cmd:
        class _Args:
            json = False
        return cmd_list(_Args())
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
