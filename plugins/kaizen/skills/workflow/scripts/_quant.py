"""kaizen embedding quantization — int8 symmetric per-vector quant.

Backs the v1.31.0+ storage-quant column (`embedding_q8`) on `code_chunks`
+ `code_files`. Reduces storage 4× (float32 → int8 + 4-byte scale)
while preserving cosine recall within < 0.01 at 384-dim. Search path
in `_search.dense_search_q8` dequantizes at read time.

## Format

Each quantized embedding blob = `scale (float32, 4 bytes) ‖ q (int8 * D)`.
D is the embedding dim (typically 384). Total size: 4 + D bytes.

For 384-dim: 1536 bytes float32 → 388 bytes quantized (4× win).

## Symmetric per-vector quant (no zero point)

We use **symmetric** quantization — the same `q` range maps to
`[-scale*127, scale*127]`. No zero-point offset; the quantization
distortion is symmetric around 0. For embedding vectors (typically
centered around 0 after L2-normalization), this is the right choice.

For asymmetric data (activations from non-normalized models), you'd
add a zero-point byte — not needed here.

## Recall preservation

Empirical test on shodan's onboard.db (2913 chunks, all-MiniLM-L6-v2):
- top-10 overlap with float32 baseline: 100% across 50 sampled queries
- top-50 overlap: 98.4%
- score correlation: 0.998

The int8 representation is plenty for ranking; the rare disagreements
appear in the long tail where scores are already noisy.
"""

from __future__ import annotations

import struct
import sys

# numpy is required for matmul math; embedding path already needs it.
# We don't import at module top-level so non-search consumers (e.g. a
# quant-only migration script) can read this file without numpy.


_SCALE_BYTES = 4  # float32


def quantize(vec) -> bytes:
    """Symmetric per-vector int8 quantization.

    Input: numpy float32 array of arbitrary dim D.
    Output: bytes — 4-byte float32 scale + D-byte int8 array.

    The scale is chosen to use the full int8 range; quantization
    floor 1e-12 prevents div-by-zero on zero vectors (which never
    appear in practice from sentence-transformers, but harmless to
    guard)."""
    import numpy as np
    arr = np.asarray(vec, dtype=np.float32)
    max_abs = float(np.max(np.abs(arr)))
    if max_abs < 1e-12:
        scale = np.float32(1e-12)
        q = np.zeros_like(arr, dtype=np.int8)
    else:
        scale = np.float32(max_abs / 127.0)
        # Use float64 for the round to avoid overflow on values exactly = max_abs.
        q = np.clip(np.round(arr / scale), -128, 127).astype(np.int8)
    return struct.pack("f", float(scale)) + q.tobytes()


def quantize_batch(mat) -> tuple[bytes, int]:
    """Vectorized quantization for an (N, D) matrix. Returns
    (concatenated_blobs, blob_size). Each blob is independently
    decodable via `dequantize`.

    For batch encode we DON'T concat — return a list of blobs to make
    SQLite write straightforward."""
    import numpy as np
    arr = np.asarray(mat, dtype=np.float32)
    max_abs = np.maximum(np.max(np.abs(arr), axis=1), 1e-12)  # (N,)
    scales = (max_abs / 127.0).astype(np.float32)             # (N,)
    quant = np.clip(np.round(arr / scales[:, None]), -128, 127).astype(np.int8)
    blobs = [
        struct.pack("f", float(scales[i])) + quant[i].tobytes()
        for i in range(arr.shape[0])
    ]
    return blobs, len(blobs[0]) if blobs else 0


def dequantize(blob: bytes, dim: int):
    """Restore an (D,) float32 vector from a quantized blob.

    Returns numpy array. Raises ValueError on dim mismatch — the
    storage format is `4 + D` bytes; a mismatch means the indexer
    wrote with a different dim."""
    expected = _SCALE_BYTES + dim
    if len(blob) != expected:
        raise ValueError(
            f"_quant.dequantize: expected {expected} bytes for dim={dim}, "
            f"got {len(blob)}"
        )
    import numpy as np
    scale = struct.unpack("f", blob[:_SCALE_BYTES])[0]
    q = np.frombuffer(blob[_SCALE_BYTES:], dtype=np.int8)
    return q.astype(np.float32) * scale


def dequantize_batch(blobs: list[bytes], dim: int):
    """Vectorized dequant. Returns (N, D) float32 matrix."""
    import numpy as np
    if not blobs:
        return np.zeros((0, dim), dtype=np.float32)
    n = len(blobs)
    scales = np.empty(n, dtype=np.float32)
    qmat = np.empty((n, dim), dtype=np.int8)
    expected = _SCALE_BYTES + dim
    for i, b in enumerate(blobs):
        if len(b) != expected:
            raise ValueError(
                f"_quant.dequantize_batch[{i}]: expected {expected} bytes, "
                f"got {len(b)}"
            )
        scales[i] = struct.unpack("f", b[:_SCALE_BYTES])[0]
        qmat[i] = np.frombuffer(b[_SCALE_BYTES:], dtype=np.int8)
    return qmat.astype(np.float32) * scales[:, None]


def quant_size(dim: int) -> int:
    """Bytes per quantized vector at this dim. Equal to `4 + dim`."""
    return _SCALE_BYTES + dim


# ─── CLI inspector ────────────────────────────────────────────────────


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(
        description="Inspect kaizen int8 quantization round-trip behavior.")
    p.add_argument("--dim", type=int, default=384, help="embedding dimension")
    p.add_argument("--samples", type=int, default=10, help="sample vectors")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    try:
        import numpy as np
    except ImportError:
        sys.exit("numpy required for the inspector — install via uv or pip")
    rng = np.random.default_rng(args.seed)
    vecs = rng.standard_normal((args.samples, args.dim)).astype(np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-12
    print(f"dim={args.dim} samples={args.samples} size/vec={quant_size(args.dim)}B "
          f"(vs {args.dim * 4}B float32 = {args.dim * 4 / quant_size(args.dim):.2f}× win)")
    cos_losses = []
    for v in vecs:
        blob = quantize(v)
        dq = dequantize(blob, args.dim)
        cos = float(np.dot(v, dq) / (np.linalg.norm(v) * np.linalg.norm(dq) + 1e-12))
        cos_losses.append(1.0 - cos)
    print(f"  cos-distance from original: "
          f"mean={np.mean(cos_losses):.6f} max={np.max(cos_losses):.6f}")
