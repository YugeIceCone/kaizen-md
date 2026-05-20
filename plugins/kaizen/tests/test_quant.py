#!/usr/bin/env python3
"""Tests for _quant.py — int8 symmetric per-vector quantization.

Run:
    python3 -m unittest tests.test_quant -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

try:
    import numpy as np  # noqa: F401
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

import _quant as q  # noqa: E402

requires_numpy = unittest.skipUnless(NUMPY_AVAILABLE, "numpy not installed")

class TestQuantSize(unittest.TestCase):
    def test_blob_size_formula(self) -> None:
        # 4-byte scale + D-byte int8
        self.assertEqual(q.quant_size(384), 388)
        self.assertEqual(q.quant_size(768), 772)
        self.assertEqual(q.quant_size(1), 5)

@requires_numpy
class TestRoundtrip(unittest.TestCase):
    def test_zero_vector(self) -> None:
        import numpy as np
        v = np.zeros(8, dtype=np.float32)
        blob = q.quantize(v)
        dq = q.dequantize(blob, 8)
        self.assertEqual(dq.shape, (8,))
        np.testing.assert_array_equal(dq, np.zeros(8))

    def test_unit_normalized_vec_recovers_within_1_percent(self) -> None:
        import numpy as np
        rng = np.random.default_rng(seed=42)
        for _ in range(20):
            v = rng.standard_normal(384).astype(np.float32)
            v /= np.linalg.norm(v) + 1e-12
            blob = q.quantize(v)
            self.assertEqual(len(blob), q.quant_size(384))
            dq = q.dequantize(blob, 384)
            # Cosine distance after round-trip is small for symmetric quant.
            cos = float(np.dot(v, dq) / (np.linalg.norm(v) * np.linalg.norm(dq)))
            self.assertGreater(cos, 0.99, f"cosine={cos} (expected > 0.99)")

    def test_batch_matches_single(self) -> None:
        import numpy as np
        rng = np.random.default_rng(seed=7)
        mat = rng.standard_normal((5, 16)).astype(np.float32)
        blobs_batch, _ = q.quantize_batch(mat)
        for i in range(5):
            blob_single = q.quantize(mat[i])
            self.assertEqual(blobs_batch[i], blob_single)

    def test_dequantize_batch_matches_single(self) -> None:
        import numpy as np
        rng = np.random.default_rng(seed=1)
        mat = rng.standard_normal((4, 32)).astype(np.float32)
        blobs, _ = q.quantize_batch(mat)
        out_batch = q.dequantize_batch(blobs, 32)
        for i in range(4):
            out_single = q.dequantize(blobs[i], 32)
            np.testing.assert_array_equal(out_batch[i], out_single)

    def test_wrong_dim_raises(self) -> None:
        import numpy as np
        v = np.ones(16, dtype=np.float32)
        blob = q.quantize(v)
        with self.assertRaises(ValueError):
            q.dequantize(blob, 32)  # wrong dim

if __name__ == "__main__":
    unittest.main(verbosity=2)
