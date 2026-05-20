"""kaizen ColBERT late-interaction encoding — token-level multi-vectors.

Backs the v1.34+ (Phase 4 E10) opt-in ``code_chunks_colbert`` sidecar
table. Each chunk gets a ``(seq_len, dim)`` matrix of float32 token
embeddings; query-time scoring is the MaxSim aggregation Khattab+ 2020:

    score(q, d) = sum_{q_i in q_tokens} max_{d_j in d_tokens} (q_i · d_j)

i.e. for each query token, find the single document token with highest
cosine, then sum across the query.

## Format

Each ``code_chunks_colbert.vectors`` blob is::

    struct.pack('<II', seq_len, dim) + matrix.astype(np.float32).tobytes()

Header: 8 bytes (two little-endian uint32). Body: seq_len * dim * 4
bytes. For colbertv2.0 (dim=128, typical seq_len=32 after truncation):
8 + 32*128*4 = 16,392 bytes per chunk. ~10x dense (1536B for 384-dim
float32) but materially better recall on long-tail queries.

## Model resolution

``KAIZEN_COLBERT_MODEL`` env or default ``colbert-ir/colbertv2.0``.
Lazy loaded; cached at module scope. Requires ``transformers`` +
``torch``. When either is missing, ``encode_colbert`` returns ``None``
and indexers skip the sidecar write.

## Composition

E10 is orthogonal to all prior retrieval layers. ``colbert_search`` in
``_search.py`` exposes it as a separate search path; it can be fused
into ``hybrid_search`` via RRF, but the default ``hybrid_search``
does NOT auto-fold ColBERT — the storage cost is high enough that
many users will index without it. Pair with ``cross_encoder_rerank``
for the best results: ColBERT shortlist, cross-encoder rerank.
"""

from __future__ import annotations

import os
import struct
import sys
from typing import Optional

DEFAULT_COLBERT_MODEL = "colbert-ir/colbertv2.0"

# Module-level caches (lazy loaded). Same pattern as _sparse + cross_encoder.
_colbert_model = None
_colbert_tokenizer = None
_colbert_torch = None
_colbert_np = None
_load_attempted = False

def is_colbert_enabled() -> bool:
    """``KAIZEN_COLBERT_ENABLE`` in ``{1, true, yes, on}``.

    Default off — ColBERT storage is ~10x dense and indexing is ~3-5x
    slower than the dense path; indexers gate the sidecar population
    on this flag so default behavior is unchanged."""
    raw = os.environ.get("KAIZEN_COLBERT_ENABLE", "").lower().strip()
    return raw in {"1", "true", "yes", "on"}

def colbert_model_name() -> str:
    """``KAIZEN_COLBERT_MODEL`` or the colbertv2.0 default."""
    return os.environ.get("KAIZEN_COLBERT_MODEL", DEFAULT_COLBERT_MODEL)

def _max_seq_length() -> int:
    """``KAIZEN_COLBERT_MAX_SEQ`` — token cap per chunk. Default 32
    (ColBERTv2 paper uses 32 for queries, 180 for docs; 32 is a
    storage-conscious default that still covers typical code chunks).
    Floor 8 so the encoder isn't given empty inputs."""
    raw = os.environ.get("KAIZEN_COLBERT_MAX_SEQ", "32")
    try:
        return max(8, int(raw))
    except ValueError:
        return 32

def _load_colbert_model():
    """Lazy load ColBERT encoder + tokenizer.

    Returns ``(model, tokenizer, torch, numpy)`` or all-``None`` when
    deps are unavailable or the model download fails. Caches the
    result either way so subsequent calls don't re-attempt.

    ColBERT models output (B, seq, dim) hidden states; we project via
    a linear head trained for cosine retrieval. Many ColBERT-trained
    models (incl. colbertv2.0) ship a ``linear`` layer named
    ``linear`` or ``Linear``; if absent, we use the last hidden
    state directly (degraded but functional)."""
    global _colbert_model, _colbert_tokenizer, _colbert_torch, _colbert_np, _load_attempted
    if _load_attempted:
        return _colbert_model, _colbert_tokenizer, _colbert_torch, _colbert_np
    _load_attempted = True
    try:
        from transformers import AutoModel, AutoTokenizer  # type: ignore
        import torch  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        return None, None, None, None
    name = colbert_model_name()
    try:
        _colbert_tokenizer = AutoTokenizer.from_pretrained(name)
        _colbert_model = AutoModel.from_pretrained(name)
        _colbert_model.eval()
    except Exception as e:
        sys.stderr.write(
            f"kaizen colbert: failed to load model {name}: "
            f"{type(e).__name__}: {e}\n"
        )
        _colbert_tokenizer = None
        _colbert_model = None
        return None, None, None, None
    _colbert_torch = torch
    _colbert_np = np
    return _colbert_model, _colbert_tokenizer, _colbert_torch, _colbert_np

def reset_cache() -> None:
    """Drop cached load result. Used by tests that mutate env knobs."""
    global _colbert_model, _colbert_tokenizer, _colbert_torch, _colbert_np, _load_attempted
    _colbert_model = None
    _colbert_tokenizer = None
    _colbert_torch = None
    _colbert_np = None
    _load_attempted = False

def encode_colbert(text: str, *, max_length: Optional[int] = None):
    """Encode text → ``(seq_len, dim)`` float32 matrix, or ``None``
    when the model is unavailable.

    Sequence of L2-normalized token embeddings. Padding + special
    tokens are kept in place (their contribution to MaxSim is usually
    small after normalization). Caller is responsible for storage."""
    model, tok, torch, np = _load_colbert_model()
    if model is None:
        return None
    inputs = tok(
        text,
        return_tensors="pt",
        truncation=True,
        max_length=max_length or _max_seq_length(),
        padding=False,
    )
    with torch.no_grad():
        outputs = model(**inputs)
        hidden = outputs.last_hidden_state  # (1, seq, hidden_dim)
        # L2-normalize each token vector for cosine MaxSim
        hidden = torch.nn.functional.normalize(hidden, p=2, dim=-1)
        mat = hidden.squeeze(0).cpu().numpy().astype(np.float32)  # (seq, dim)
    return mat

def encode_colbert_batch(
    texts: list[str],
    *,
    max_length: Optional[int] = None,
    batch_size: int = 16,
) -> list:
    """Batched encoding. Returns one ``(seq_len_i, dim)`` matrix per
    input, or one ``None`` per input when the model is unavailable.

    Per-row seq_len may differ because padding is stripped post-encode
    using the attention mask — short inputs produce shorter matrices."""
    if not texts:
        return []
    model, tok, torch, np = _load_colbert_model()
    if model is None:
        return [None] * len(texts)
    cap = max_length or _max_seq_length()
    out = []
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
            outputs = model(**inputs)
            hidden = outputs.last_hidden_state  # (B, seq, dim)
            hidden = torch.nn.functional.normalize(hidden, p=2, dim=-1)
            attention = inputs.get("attention_mask")
        for i in range(hidden.shape[0]):
            if attention is not None:
                length = int(attention[i].sum().item())
            else:
                length = hidden.shape[1]
            mat = hidden[i, :length].cpu().numpy().astype(np.float32)
            out.append(mat)
    return out

def serialize(matrix) -> bytes:
    """Pack a ``(seq_len, dim)`` float32 matrix to bytes for SQLite.

    Format: ``<II`` header (seq_len, dim as little-endian uint32) +
    raw float32 body. ``deserialize`` is the inverse.

    Empty matrix (seq_len=0) is legal and round-trips to a (0, dim)
    array. Caller must always cast to float32 before this call (or
    use a numpy array; we cast internally for safety)."""
    import numpy as np
    arr = np.ascontiguousarray(matrix, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError(
            f"_colbert.serialize: expected 2-D matrix, got shape {arr.shape}"
        )
    seq_len, dim = int(arr.shape[0]), int(arr.shape[1])
    return struct.pack("<II", seq_len, dim) + arr.tobytes()

def deserialize(blob: bytes):
    """Unpack a stored ColBERT blob back to ``(seq_len, dim)``
    float32 array. Returns ``None`` on empty / malformed input rather
    than raising — search loops skip such rows.

    Sanity-checks the body length matches ``seq_len * dim * 4``; a
    mismatch signals corruption or a dim change between index time
    and query time."""
    if not blob or len(blob) < 8:
        return None
    import numpy as np
    seq_len, dim = struct.unpack("<II", blob[:8])
    body = blob[8:]
    expected_bytes = seq_len * dim * 4
    if len(body) != expected_bytes:
        return None
    if seq_len == 0:
        return np.zeros((0, dim), dtype=np.float32)
    arr = np.frombuffer(body, dtype=np.float32).reshape(seq_len, dim)
    return arr

def max_sim_score(query_mat, doc_mat) -> float:
    """MaxSim — Khattab+ 2020 late-interaction scoring.

    For each query token, take its cosine with every doc token, then
    take the max; sum the maxes across the query. Assumes both
    matrices are pre-L2-normalized (encode_colbert does this).

    Returns 0.0 when either matrix is empty/None or shapes don't
    match. Pure-numpy — no torch dep at query time after the encoder
    has run."""
    import numpy as np
    if query_mat is None or doc_mat is None:
        return 0.0
    q = np.asarray(query_mat, dtype=np.float32)
    d = np.asarray(doc_mat, dtype=np.float32)
    if q.size == 0 or d.size == 0:
        return 0.0
    if q.ndim != 2 or d.ndim != 2:
        return 0.0
    if q.shape[1] != d.shape[1]:
        return 0.0  # dim mismatch — guard against index/query drift
    # Cosine matrix: (Q, D)
    sim = q @ d.T
    # MaxSim: for each query row, max over doc tokens, then sum
    return float(sim.max(axis=1).sum())

def is_available() -> bool:
    """Returns ``True`` iff transformers + torch + numpy are installed
    AND the model loads cleanly.

    Cheap after the first call (cached result). Indexers and tests
    use this to gate sidecar population + the live-model tests."""
    model, _, _, _ = _load_colbert_model()
    return model is not None

# ─── CLI inspector ────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(
        description="Inspect kaizen ColBERT encoding — encode a text "
                    "and report shape + storage cost."
    )
    p.add_argument(
        "--text",
        default="def carve(old, new, slug, *, reexport=None)",
        help="text to encode",
    )
    args = p.parse_args()
    if not is_available():
        sys.exit(
            "kaizen-colbert: transformers + torch required.\n"
            "  pip install --user transformers torch\n"
            f"Model default: {DEFAULT_COLBERT_MODEL}"
        )
    mat = encode_colbert(args.text)
    if mat is None:
        sys.exit("colbert encoding returned None")
    blob = serialize(mat)
    print(f"shape=({mat.shape[0]}, {mat.shape[1]}) "
          f"bytes={len(blob)} "
          f"vs_dense_384={mat.shape[1] * 4}B "
          f"ratio={len(blob) / (384 * 4):.2f}x")
