"""Tests for E4 — binary (1-bit) quantization.

Verifies quantize_binary / quantize_binary_batch / dequantize_binary /
hamming_distance / hamming_distance_batch. Requires numpy (kaizen indexes
do; numpy import is checked at the top of every test).

Run:
    python3 -m unittest tests.test_binary_quantization -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

import _quant as kz_quant  # noqa: E402

@unittest.skipUnless(HAS_NUMPY, "numpy required for binary-quant tests")
class TestQuantizeBinary(unittest.TestCase):
    def test_size_ceil_div_8(self):
        for dim, expected in [(8, 1), (16, 2), (384, 48), (1024, 128), (10, 2)]:
            with self.subTest(dim=dim):
                self.assertEqual(kz_quant.binary_size(dim), expected)

    def test_positive_values_pack_to_one_bits(self):
        vec = [1.0] * 8
        blob = kz_quant.quantize_binary(vec)
        self.assertEqual(blob, b"\xff")  # 0b11111111

    def test_negative_and_zero_pack_to_zero_bits(self):
        vec = [-1.0, 0.0, -2.0, 0.0, -0.5, 0.0, -3.0, -0.1]
        blob = kz_quant.quantize_binary(vec)
        self.assertEqual(blob, b"\x00")

    def test_mixed_signs_pack_correctly(self):
        # Pattern: +, -, +, -, +, +, -, +  → 10101101  = 0xAD
        vec = [1.0, -1.0, 1.0, -1.0, 1.0, 1.0, -1.0, 1.0]
        blob = kz_quant.quantize_binary(vec)
        self.assertEqual(blob, b"\xad")

    def test_dim_384_packs_to_48_bytes(self):
        vec = np.random.default_rng(42).standard_normal(384).astype(np.float32)
        blob = kz_quant.quantize_binary(vec)
        self.assertEqual(len(blob), 48)

    def test_round_trip_sign(self):
        """dequantize_binary maps positive bits → +1, zero bits → -1.
        Round-trip recovers the SIGN of the original vector."""
        vec = np.array([0.5, -0.3, 0.8, -0.1, 0.0, 0.9, -2.0, 0.4],
                       dtype=np.float32)
        blob = kz_quant.quantize_binary(vec)
        recovered = kz_quant.dequantize_binary(blob, dim=8)
        expected_signs = np.where(vec > 0, 1.0, -1.0)
        np.testing.assert_array_equal(recovered, expected_signs)

@unittest.skipUnless(HAS_NUMPY, "numpy required")
class TestQuantizeBinaryBatch(unittest.TestCase):
    def test_returns_blobs_and_size(self):
        mat = np.array([[1, -1, 1, -1, 1, -1, 1, -1]] * 5, dtype=np.float32)
        blobs, size = kz_quant.quantize_binary_batch(mat)
        self.assertEqual(len(blobs), 5)
        self.assertEqual(size, 1)
        # All rows have the same pattern → all blobs equal
        self.assertEqual(len(set(blobs)), 1)

    def test_rejects_1d_input(self):
        with self.assertRaises(ValueError):
            kz_quant.quantize_binary_batch(np.array([1.0, -1.0]))

    def test_empty_batch(self):
        mat = np.zeros((0, 8), dtype=np.float32)
        blobs, size = kz_quant.quantize_binary_batch(mat)
        self.assertEqual(blobs, [])
        self.assertEqual(size, 0)

    def test_dim_384_vectorized(self):
        rng = np.random.default_rng(7)
        mat = rng.standard_normal((10, 384)).astype(np.float32)
        blobs, size = kz_quant.quantize_binary_batch(mat)
        self.assertEqual(size, 48)
        self.assertEqual(len(blobs), 10)
        for b in blobs:
            self.assertEqual(len(b), 48)

@unittest.skipUnless(HAS_NUMPY, "numpy required")
class TestDequantizeBinaryEdgeCases(unittest.TestCase):
    def test_dim_mismatch_raises(self):
        blob = b"\xff"  # 1 byte = 8 dims
        with self.assertRaises(ValueError):
            kz_quant.dequantize_binary(blob, dim=16)

@unittest.skipUnless(HAS_NUMPY, "numpy required")
class TestHammingDistance(unittest.TestCase):
    def test_identical_blobs_distance_zero(self):
        self.assertEqual(kz_quant.hamming_distance(b"\xff", b"\xff"), 0)

    def test_inverted_blobs_distance_equals_dim(self):
        self.assertEqual(kz_quant.hamming_distance(b"\xff", b"\x00"), 8)
        self.assertEqual(kz_quant.hamming_distance(b"\xff\xff", b"\x00\x00"), 16)

    def test_partial_overlap(self):
        # 10101010 vs 11110000 → 1010 ^ ... → 4 bit flips
        self.assertEqual(kz_quant.hamming_distance(b"\xaa", b"\xf0"), 4)

    def test_blob_length_mismatch_raises(self):
        with self.assertRaises(ValueError):
            kz_quant.hamming_distance(b"\xff", b"\xff\xff")

@unittest.skipUnless(HAS_NUMPY, "numpy required")
class TestHammingDistanceBatch(unittest.TestCase):
    def test_query_against_self_gives_zero(self):
        q = b"\xff\x00"
        out = kz_quant.hamming_distance_batch(q, [q, q, q])
        self.assertEqual(out, [0, 0, 0])

    def test_matches_per_pair_function(self):
        rng = np.random.default_rng(1)
        # Build 5 random 48-byte blobs
        blobs = [
            kz_quant.quantize_binary(
                rng.standard_normal(384).astype(np.float32)
            )
            for _ in range(5)
        ]
        query = blobs[0]
        batch_dists = kz_quant.hamming_distance_batch(query, blobs)
        per_pair = [kz_quant.hamming_distance(query, b) for b in blobs]
        self.assertEqual(batch_dists, per_pair)

    def test_empty_candidates(self):
        self.assertEqual(kz_quant.hamming_distance_batch(b"\xff", []), [])

    def test_first_candidate_is_self(self):
        """A common shortlist pattern: query embedded as a candidate
        should have distance 0 to itself."""
        rng = np.random.default_rng(13)
        vec = rng.standard_normal(384).astype(np.float32)
        q = kz_quant.quantize_binary(vec)
        other = kz_quant.quantize_binary(-vec)  # flipped signs
        dists = kz_quant.hamming_distance_batch(q, [q, other])
        self.assertEqual(dists[0], 0)
        self.assertEqual(dists[1], 384)  # all bits flipped

@unittest.skipUnless(HAS_NUMPY, "numpy required")
class TestStorageRatio(unittest.TestCase):
    """End-to-end: binary quant is ~32× more compact than float32."""

    def test_storage_compression_ratio(self):
        rng = np.random.default_rng(0)
        vec = rng.standard_normal(384).astype(np.float32)
        float_bytes = vec.tobytes()
        binary_bytes = kz_quant.quantize_binary(vec)
        self.assertEqual(len(float_bytes), 384 * 4)  # 1536
        self.assertEqual(len(binary_bytes), 48)
        # 32:1 ratio
        self.assertEqual(len(float_bytes) // len(binary_bytes), 32)

class TestHammingDistancePurePython(unittest.TestCase):
    """hamming_distance uses int.bit_count() — pure Python (3.10+), no
    numpy required. These run even on minimal hosts."""

    def test_identical(self):
        self.assertEqual(kz_quant.hamming_distance(b"\xff", b"\xff"), 0)

    def test_all_flipped(self):
        self.assertEqual(kz_quant.hamming_distance(b"\xff", b"\x00"), 8)

    def test_multi_byte(self):
        # 4 bits different
        self.assertEqual(kz_quant.hamming_distance(b"\xaa\xff", b"\xf0\xff"), 4)

    def test_length_mismatch(self):
        with self.assertRaises(ValueError):
            kz_quant.hamming_distance(b"\xff", b"\xff\xff")

class TestBinarySizeFunction(unittest.TestCase):
    """binary_size is pure arithmetic — no numpy."""

    def test_known_dims(self):
        self.assertEqual(kz_quant.binary_size(8), 1)
        self.assertEqual(kz_quant.binary_size(16), 2)
        self.assertEqual(kz_quant.binary_size(15), 2)  # rounds up
        self.assertEqual(kz_quant.binary_size(1), 1)
        self.assertEqual(kz_quant.binary_size(384), 48)

if __name__ == "__main__":
    unittest.main()
