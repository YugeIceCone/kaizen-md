"""kaizen sparse embedding — SPLADE token-level activations.

Backs the v1.34+ (Phase 4 E9) opt-in sparse column `embedding_sparse`
on `code_chunks`. Sparse vectors are dict {token_id: weight}, JSON-
encoded for SQLite storage. Lazy loaded — only materialized when
KAIZEN_SPARSE_ENABLE=1 is set during indexing.

## Format

Each sparse vector is a JSON object: ``{"42": 1.23, "1024": 0.45, ...}``.
Typical SPLADE-cocondenser output: 100-200 non-zero tokens per chunk
(out of ~30K vocab). Storage: ~2-4 KB per chunk JSON-encoded.

## Model resolution

``KAIZEN_SPARSE_MODEL`` env or default
``naver/splade-cocondenser-ensembledistil``. Loaded once and cached at
module scope. Requires ``transformers`` + ``torch``; when either is
missing, ``encode_sparse`` returns ``None`` and indexers skip the
sparse column. No-op fallback mirrors ``_load_cross_encoder`` in
``_search.py``.

## Search

``dot_product(q, d)`` = sum over keys in both of ``q[k] * d[k]``. Docs
ranked by descending dot product. ``sparse_search`` in ``_search.py``
composes this into ``hybrid_search`` RRF alongside BM25 and dense
cosine.

## Composition with existing retrieval

E9 is orthogonal to E2 (cross-encoder rerank), E4 (binary quant), and
E5 (matryoshka). RRF fuses sparse + dense ranks; the cross-encoder
rerank operates on the fused top-K. Storage is additive — old indexes
keep working when ``KAIZEN_SPARSE_ENABLE`` is unset.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Optional

DEFAULT_SPARSE_MODEL = "naver/splade-cocondenser-ensembledistil"

# Module-level caches (lazy loaded). torch is captured so callers don't
# need a separate import to call no_grad().
_sparse_model = None
_sparse_tokenizer = None
_sparse_torch = None
_load_attempted = False  # avoid re-attempting load on every call when missing

def is_sparse_enabled() -> bool:
    """``KAIZEN_SPARSE_ENABLE`` in ``{1, true, yes, on}`` (case-insensitive).

    Default off — sparse adds storage + indexing time, and the model
    download is ~500 MB. Indexers gate the sparse column population on
    this flag so default behavior is unchanged."""
    raw = os.environ.get("KAIZEN_SPARSE_ENABLE", "").lower().strip()
    return raw in {"1", "true", "yes", "on"}

def sparse_model_name() -> str:
    """``KAIZEN_SPARSE_MODEL`` or the SPLADE-cocondenser default."""
    return os.environ.get("KAIZEN_SPARSE_MODEL", DEFAULT_SPARSE_MODEL)

def _max_length() -> int:
    """``KAIZEN_SPARSE_MAX_LENGTH`` — token cap per chunk. Default 256
    matches typical chunk sizes; longer chunks get truncated."""
    raw = os.environ.get("KAIZEN_SPARSE_MAX_LENGTH", "256")
    try:
        return max(32, int(raw))
    except ValueError:
        return 256

def _load_sparse_model():
    """Lazy load SPLADE encoder + tokenizer.

    Returns ``(model, tokenizer, torch)`` or ``(None, None, None)`` when
    transformers/torch unavailable or model download fails. Caches the
    result either way so subsequent calls don't re-attempt.

    Mirrors the lazy-loading pattern of ``_load_cross_encoder`` in
    ``_search.py``."""
    global _sparse_model, _sparse_tokenizer, _sparse_torch, _load_attempted
    if _load_attempted:
        return _sparse_model, _sparse_tokenizer, _sparse_torch
    _load_attempted = True
    try:
        from transformers import AutoModelForMaskedLM, AutoTokenizer  # type: ignore
        import torch  # type: ignore
    except ImportError:
        return None, None, None
    name = sparse_model_name()
    try:
        _sparse_tokenizer = AutoTokenizer.from_pretrained(name)
        _sparse_model = AutoModelForMaskedLM.from_pretrained(name)
        _sparse_model.eval()
    except Exception as e:  # network error, missing model, etc.
        sys.stderr.write(
            f"kaizen sparse: failed to load model {name}: "
            f"{type(e).__name__}: {e}\n"
        )
        _sparse_tokenizer = None
        _sparse_model = None
        return None, None, None
    _sparse_torch = torch
    return _sparse_model, _sparse_tokenizer, _sparse_torch

def reset_cache() -> None:
    """Drop the cached load result so the next call re-attempts. Used by
    tests that mutate ``KAIZEN_SPARSE_MODEL`` between cases."""
    global _sparse_model, _sparse_tokenizer, _sparse_torch, _load_attempted
    _sparse_model = None
    _sparse_tokenizer = None
    _sparse_torch = None
    _load_attempted = False

def encode_sparse(text: str, *, max_length: Optional[int] = None) -> Optional[dict[int, float]]:
    """Encode text → ``{token_id: weight}`` sparse dict, or ``None``
    when the model is unavailable.

    Standard SPLADE inference:

    1. ``logits = model(**inputs).logits``  shape ``(1, seq, vocab)``
    2. ``weights = log(1 + relu(logits))``  — SPLADE activation
    3. Mask out padding tokens (zero them out)
    4. ``sparse  = weights.max(dim=1).values``  max-pool over seq
    5. Filter to non-zero entries → ``{token_id: weight}``
    """
    model, tok, torch = _load_sparse_model()
    if model is None:
        return None
    inputs = tok(
        text,
        return_tensors="pt",
        truncation=True,
        max_length=max_length or _max_length(),
        padding=False,
    )
    with torch.no_grad():
        logits = model(**inputs).logits  # (1, seq, vocab)
        weights = torch.log1p(torch.relu(logits))
        attention = inputs.get("attention_mask")
        if attention is not None:
            mask = attention.unsqueeze(-1).bool()
            weights = weights.masked_fill(~mask, 0.0)
        sparse = weights.max(dim=1).values.squeeze(0)  # (vocab,)
    nz = torch.nonzero(sparse, as_tuple=True)[0]
    if nz.numel() == 0:
        return {}
    vals = sparse[nz]
    return {int(i): float(v) for i, v in zip(nz.tolist(), vals.tolist())}

def encode_sparse_batch(
    texts: list[str],
    *,
    max_length: Optional[int] = None,
    batch_size: int = 16,
) -> list[Optional[dict[int, float]]]:
    """Batched SPLADE encoding. Returns one sparse dict per input.

    Returns a list of ``None`` (same length as input) when the model
    can't be loaded — callers treat per-row ``None`` as "no sparse for
    this row" and skip the sparse column write."""
    if not texts:
        return []
    model, tok, torch = _load_sparse_model()
    if model is None:
        return [None] * len(texts)
    out: list[Optional[dict[int, float]]] = []
    cap = max_length or _max_length()
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        inputs = tok(
            batch,
            return_tensors="pt",
            truncation=True,
            max_length=cap,
            padding=True,
        )
        with torch.no_grad():
            logits = model(**inputs).logits  # (B, seq, vocab)
            weights = torch.log1p(torch.relu(logits))
            attention = inputs.get("attention_mask")
            if attention is not None:
                mask = attention.unsqueeze(-1).bool()
                weights = weights.masked_fill(~mask, 0.0)
            sparse = weights.max(dim=1).values  # (B, vocab)
        for i in range(sparse.shape[0]):
            row = sparse[i]
            nz = torch.nonzero(row, as_tuple=True)[0]
            if nz.numel() == 0:
                out.append({})
                continue
            vals = row[nz]
            out.append(
                {int(j): float(v) for j, v in zip(nz.tolist(), vals.tolist())}
            )
    return out

def serialize(sparse: dict[int, float]) -> bytes:
    """JSON-encode a sparse dict for SQLite blob storage.

    Keys are forced to strings (JSON requirement) and floats are cast
    via ``float()`` to make numpy scalars JSON-serializable. Compact
    separators keep storage tight."""
    return json.dumps(
        {str(int(k)): float(v) for k, v in sparse.items()},
        separators=(",", ":"),
    ).encode()

def deserialize(blob: bytes) -> dict[int, float]:
    """Decode a JSON sparse blob back to ``{int: float}``.

    Returns ``{}`` on empty input, invalid JSON, non-object payloads,
    or per-entry conversion failures — defensive because the SQLite
    column is opaque and could carry stale shapes from older builds."""
    if not blob:
        return {}
    try:
        raw = json.loads(blob)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[int, float] = {}
    for k, v in raw.items():
        try:
            out[int(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out

def dot_product(q: dict[int, float], d: dict[int, float]) -> float:
    """Sparse dot product: ``sum_{k in q ∩ d} q[k] * d[k]``.

    Iterates the smaller dict for efficiency (fewer ``d.get`` calls).
    Returns ``0.0`` for any empty input."""
    if not q or not d:
        return 0.0
    if len(q) > len(d):
        q, d = d, q
    total = 0.0
    for k, v in q.items():
        w = d.get(k)
        if w is not None:
            total += v * w
    return total

def dot_product_batch(
    q: dict[int, float],
    docs: list[dict[int, float]],
) -> list[float]:
    """One sparse query against many docs. Returns one score per doc.

    Pure-Python loop — sparse vectors are small (~100-200 entries) so
    the overhead is negligible compared to model inference. For a
    million-doc corpus, an inverted index would beat this; SQLite-
    scale (10K-100K docs) is fine with the linear scan."""
    if not q:
        return [0.0] * len(docs)
    return [dot_product(q, d) for d in docs]

def is_available() -> bool:
    """Returns ``True`` iff transformers + torch are installed AND the
    model loads cleanly.

    Cheap after the first call (cached result). Indexers and test
    suites use this to decide whether to materialize the sparse column
    or skip the sparse-dependent test cases."""
    model, _, _ = _load_sparse_model()
    return model is not None

# ─── CLI inspector ────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(
        description="Inspect kaizen SPLADE sparse encoding — encode text "
                    "and print the top-K weighted token IDs."
    )
    p.add_argument(
        "--text",
        default="def carve(old, new, slug, *, reexport=None)",
        help="text to encode",
    )
    p.add_argument("--top", type=int, default=10, help="show top-K terms")
    args = p.parse_args()
    if not is_available():
        sys.exit(
            "kaizen-sparse: transformers + torch required.\n"
            "  pip install --user transformers torch\n"
            f"Model default: {DEFAULT_SPARSE_MODEL}"
        )
    sparse = encode_sparse(args.text)
    if sparse is None:
        sys.exit("sparse encoding returned None")
    items = sorted(sparse.items(), key=lambda x: x[1], reverse=True)
    print(f"non_zero_terms={len(sparse)}")
    print(f"top_{args.top}_token_ids_by_weight:")
    for tid, w in items[: args.top]:
        print(f"  {tid}: {w:.4f}")
    blob = serialize(sparse)
    print(f"json_bytes={len(blob)}")
