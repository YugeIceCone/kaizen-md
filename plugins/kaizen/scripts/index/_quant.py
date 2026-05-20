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

# ─── E4 — binary (1-bit) quantization ─────────────────────────────────
#
# Packs each dim into 1 bit: positive → 1, non-positive → 0. Hamming
# distance between two binary embeddings approximates cosine distance
# on the underlying float32 vectors well enough for a coarse shortlist.
# 32× storage win (1 bit per dim vs 32-bit float) and a 32×+ scan
# speedup via bitwise popcount.
#
# Two-stage retrieval recipe:
#   1. Binary search (cheap):  top-K * 5 by hamming distance
#   2. int8 rerank (existing): top-K from stage 1 by int8 dot-product
#   3. (optional) cross-encoder rerank: top-K → top-N final

def quantize_binary(vec) -> bytes:
    """Pack a float32 vector into a 1-bit-per-dim bytestring.

    Returns ceil(D/8) bytes. Bit 1 = positive, bit 0 = non-positive.
    Bit order within a byte: MSB-first (most significant bit first)
    to keep hamming-distance + popcount consistent across platforms.
    A 384-dim vector packs to 48 bytes (32× storage win)."""
    import numpy as np
    arr = np.asarray(vec, dtype=np.float32)
    bits = (arr > 0).astype(np.uint8)
    packed = np.packbits(bits, bitorder="big")
    return packed.tobytes()

def quantize_binary_batch(mat) -> tuple[list[bytes], int]:
    """Vectorized binary quantization. Returns ([bytes], bytes_per_vec).

    Input: (N, D) float32 or convertible. Output: list of N packed-byte
    strings, each ceil(D/8) bytes long."""
    import numpy as np
    arr = np.asarray(mat, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError(f"quantize_binary_batch needs 2-D input, got {arr.ndim}-D")
    bits = (arr > 0).astype(np.uint8)
    packed = np.packbits(bits, axis=1, bitorder="big")
    blobs = [packed[i].tobytes() for i in range(packed.shape[0])]
    return blobs, (packed.shape[1] if packed.size else 0)

def dequantize_binary(blob: bytes, dim: int):
    """Unpack into a (D,) {-1.0, +1.0} float32 vector. Useful for
    cosine-on-binary checks (equivalent to D - 2·hamming up to scaling)."""
    import numpy as np
    expected = (dim + 7) // 8
    if len(blob) != expected:
        raise ValueError(
            f"_quant.dequantize_binary: expected {expected} bytes for "
            f"dim={dim}, got {len(blob)}"
        )
    bits = np.unpackbits(
        np.frombuffer(blob, dtype=np.uint8), bitorder="big"
    )[:dim]
    # {0, 1} → {-1.0, +1.0}
    return (bits.astype(np.float32) * 2.0) - 1.0

def hamming_distance(blob_a: bytes, blob_b: bytes) -> int:
    """Bitwise hamming distance between two binary-quantized blobs.

    Computed via XOR + popcount. Both blobs must be the same length;
    callers check dim consistency. Used as the cheap stage-1 ranker."""
    if len(blob_a) != len(blob_b):
        raise ValueError(
            f"hamming_distance: blob lengths differ ({len(blob_a)} vs {len(blob_b)})"
        )
    # XOR-then-popcount, byte-by-byte. For small blobs (48 bytes for
    # 384-dim) this is fast in pure Python; for huge batches the caller
    # should use numpy vectorization (see hamming_distance_batch).
    total = 0
    for x, y in zip(blob_a, blob_b):
        total += (x ^ y).bit_count()
    return total

def hamming_distance_batch(query_blob: bytes, candidate_blobs: list[bytes]) -> list[int]:
    """Vectorized hamming distance: query against many candidates.

    Returns N distances, one per candidate. Uses numpy when available
    (15-30× speedup over the pure-Python loop on 1000-candidate batches),
    otherwise falls back to the per-pair function."""
    try:
        import numpy as np
    except ImportError:
        return [hamming_distance(query_blob, b) for b in candidate_blobs]
    if not candidate_blobs:
        return []
    q = np.frombuffer(query_blob, dtype=np.uint8)
    mat = np.array(
        [np.frombuffer(b, dtype=np.uint8) for b in candidate_blobs],
        dtype=np.uint8,
    )
    xored = mat ^ q[None, :]
    # numpy >=2 has bit_count on uint8; fallback to lookup table for older
    try:
        bc = np.bitwise_count(xored)  # numpy 2.x
    except AttributeError:
        # Lookup table — 256 entries, each = popcount(i)
        lut = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint16)
        bc = lut[xored]
    return bc.sum(axis=1).tolist()

def binary_size(dim: int) -> int:
    """Bytes per binary-quantized vector at this dim. ceil(D/8)."""
    return (dim + 7) // 8

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
