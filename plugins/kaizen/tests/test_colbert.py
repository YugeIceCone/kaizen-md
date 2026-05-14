"""Tests for _colbert.py — ColBERT late-interaction encoding helpers.

The real ColBERT encoder requires transformers + torch + ~440MB model
download; those tests skip when the deps are missing. Pure-logic
parts — serialize / deserialize / max_sim_score / env handling — run
in every CI environment (provided numpy is available; the matrix
math hard-requires it).
"""

from __future__ import annotations

import os
import struct
import sys
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))

import _colbert  # noqa: E402

try:
    import numpy as np  # noqa: F401
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

requires_numpy = unittest.skipUnless(NUMPY_AVAILABLE, "numpy not installed")


class TestColbertEnv(unittest.TestCase):
    def _restore(self, name, val):
        if val is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = val

    def test_default_model_name(self):
        orig = os.environ.pop("KAIZEN_COLBERT_MODEL", None)
        try:
            self.assertIn("colbert", _colbert.colbert_model_name().lower())
        finally:
            self._restore("KAIZEN_COLBERT_MODEL", orig)

    def test_env_override(self):
        orig = os.environ.get("KAIZEN_COLBERT_MODEL")
        os.environ["KAIZEN_COLBERT_MODEL"] = "custom/colbert"
        try:
            self.assertEqual(_colbert.colbert_model_name(), "custom/colbert")
        finally:
            self._restore("KAIZEN_COLBERT_MODEL", orig)

    def test_is_enabled_default_off(self):
        orig = os.environ.pop("KAIZEN_COLBERT_ENABLE", None)
        try:
            self.assertFalse(_colbert.is_colbert_enabled())
        finally:
            self._restore("KAIZEN_COLBERT_ENABLE", orig)

    def test_is_enabled_truthy(self):
        orig = os.environ.get("KAIZEN_COLBERT_ENABLE")
        try:
            for val in ("1", "true", "yes", "ON"):
                os.environ["KAIZEN_COLBERT_ENABLE"] = val
                self.assertTrue(
                    _colbert.is_colbert_enabled(), f"failed for {val!r}"
                )
            for val in ("0", "false", "off", ""):
                os.environ["KAIZEN_COLBERT_ENABLE"] = val
                self.assertFalse(
                    _colbert.is_colbert_enabled(), f"failed for {val!r}"
                )
        finally:
            self._restore("KAIZEN_COLBERT_ENABLE", orig)

    def test_max_seq_default(self):
        orig = os.environ.pop("KAIZEN_COLBERT_MAX_SEQ", None)
        try:
            self.assertEqual(_colbert._max_seq_length(), 32)
        finally:
            self._restore("KAIZEN_COLBERT_MAX_SEQ", orig)

    def test_max_seq_floor(self):
        orig = os.environ.get("KAIZEN_COLBERT_MAX_SEQ")
        os.environ["KAIZEN_COLBERT_MAX_SEQ"] = "1"
        try:
            self.assertEqual(_colbert._max_seq_length(), 8)
        finally:
            self._restore("KAIZEN_COLBERT_MAX_SEQ", orig)


@requires_numpy
class TestColbertSerialization(unittest.TestCase):
    def test_roundtrip_basic(self):
        mat = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=np.float32)
        blob = _colbert.serialize(mat)
        out = _colbert.deserialize(blob)
        self.assertEqual(out.shape, (2, 3))
        np.testing.assert_array_almost_equal(out, mat)

    def test_header_format(self):
        mat = np.zeros((5, 8), dtype=np.float32)
        blob = _colbert.serialize(mat)
        seq_len, dim = struct.unpack("<II", blob[:8])
        self.assertEqual(seq_len, 5)
        self.assertEqual(dim, 8)
        # Body must be exactly seq_len * dim * 4 bytes
        self.assertEqual(len(blob) - 8, 5 * 8 * 4)

    def test_empty_matrix_roundtrip(self):
        mat = np.zeros((0, 128), dtype=np.float32)
        blob = _colbert.serialize(mat)
        out = _colbert.deserialize(blob)
        self.assertEqual(out.shape, (0, 128))

    def test_serialize_casts_to_float32(self):
        # int input must be cast — caller may pass float64 or int arrays
        mat_i64 = np.array([[1, 2], [3, 4]], dtype=np.int64)
        blob = _colbert.serialize(mat_i64)
        out = _colbert.deserialize(blob)
        np.testing.assert_array_almost_equal(out, np.array([[1, 2], [3, 4]]))

    def test_serialize_rejects_non_2d(self):
        with self.assertRaises(ValueError):
            _colbert.serialize(np.array([1.0, 2.0, 3.0], dtype=np.float32))
        with self.assertRaises(ValueError):
            _colbert.serialize(np.zeros((2, 3, 4), dtype=np.float32))

    def test_deserialize_empty_blob(self):
        self.assertIsNone(_colbert.deserialize(b""))
        self.assertIsNone(_colbert.deserialize(b"abc"))  # too short for header

    def test_deserialize_body_length_mismatch(self):
        # Header claims (4, 8) but body is too short
        bad = struct.pack("<II", 4, 8) + b"\x00" * 10  # need 128 bytes
        self.assertIsNone(_colbert.deserialize(bad))


@requires_numpy
class TestColbertMaxSim(unittest.TestCase):
    def test_max_sim_basic_orthonormal(self):
        # Two orthonormal queries vs same two orthonormal docs → each
        # query matches exactly one doc with sim 1.0 → total 2.0
        q = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
        d = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
        self.assertAlmostEqual(_colbert.max_sim_score(q, d), 2.0, places=5)

    def test_max_sim_query_subset(self):
        # Query has 2 tokens, doc has 3 — both query tokens find their
        # match in doc → score = 1.0 + 1.0 = 2.0
        q = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)
        d = np.array(
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            dtype=np.float32,
        )
        self.assertAlmostEqual(_colbert.max_sim_score(q, d), 2.0, places=5)

    def test_max_sim_dim_mismatch_returns_zero(self):
        q = np.zeros((2, 4), dtype=np.float32)
        d = np.zeros((2, 8), dtype=np.float32)
        self.assertEqual(_colbert.max_sim_score(q, d), 0.0)

    def test_max_sim_none_inputs(self):
        self.assertEqual(_colbert.max_sim_score(None, None), 0.0)
        self.assertEqual(
            _colbert.max_sim_score(None, np.zeros((1, 4), dtype=np.float32)),
            0.0,
        )
        self.assertEqual(
            _colbert.max_sim_score(np.zeros((1, 4), dtype=np.float32), None),
            0.0,
        )

    def test_max_sim_empty_matrices(self):
        q = np.zeros((0, 4), dtype=np.float32)
        d = np.zeros((2, 4), dtype=np.float32)
        self.assertEqual(_colbert.max_sim_score(q, d), 0.0)

    def test_max_sim_non_2d_returns_zero(self):
        q = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        d = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        self.assertEqual(_colbert.max_sim_score(q, d), 0.0)

    def test_max_sim_partial_overlap(self):
        # Query has unrelated token → contributes 0 to sum
        q = np.array([[1.0, 0.0], [0.0, 0.0]], dtype=np.float32)
        d = np.array([[1.0, 0.0]], dtype=np.float32)
        # First query: max sim 1.0; second: zero vector → max sim 0.0
        self.assertAlmostEqual(_colbert.max_sim_score(q, d), 1.0, places=5)


class TestColbertGracefulFallback(unittest.TestCase):
    """When transformers/torch are missing, encode_colbert* return
    None / [None, ...] without crashing."""

    def setUp(self):
        _colbert.reset_cache()

    def test_encode_returns_none_or_array(self):
        result = _colbert.encode_colbert("hello world")
        if result is None:
            self.assertIsNone(result)
        else:
            self.assertEqual(result.ndim, 2)

    def test_encode_batch_returns_none_list(self):
        result = _colbert.encode_colbert_batch(["a", "b"])
        self.assertEqual(len(result), 2)
        for r in result:
            self.assertTrue(r is None or hasattr(r, "shape"))

    def test_encode_batch_empty(self):
        self.assertEqual(_colbert.encode_colbert_batch([]), [])

    def test_is_available_returns_bool(self):
        self.assertIsInstance(_colbert.is_available(), bool)


class TestColbertSchemaMigration(unittest.TestCase):
    """Sidecar table creation + indexer integration. Uses a mocked
    encoder so no transformers/torch needed."""

    @requires_numpy
    def test_migration_creates_sidecar_table(self):
        import tempfile
        from pathlib import Path

        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        import onboard_index as oi

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = oi.open_db(root, create=True)
            row = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='code_chunks_colbert'"
            ).fetchone()
            self.assertIsNotNone(row, "code_chunks_colbert sidecar must exist")
            cols = {r[1] for r in conn.execute(
                "PRAGMA table_info(code_chunks_colbert)"
            )}
            self.assertEqual(
                cols, {"chunk_id", "vectors", "seq_len", "dim"}
            )
            conn.close()

    @requires_numpy
    def test_insert_skips_colbert_when_disabled(self):
        import struct as _struct
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        import onboard_index as oi
        import index_flow as ix

        orig = os.environ.pop("KAIZEN_COLBERT_ENABLE", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "x.py").write_text("def f(): pass\n" * 5)
                fake = lambda texts: (
                    [_struct.pack("384f", *([i / 100.0] * 384))
                     for i in range(len(texts))],
                    384,
                )
                with patch.object(oi._kz_embed, "embed_batch", side_effect=fake):
                    ix.index(root, use_git=False)
                conn = oi.open_db(root, create=False)
                n = conn.execute(
                    "SELECT COUNT(*) FROM code_chunks_colbert"
                ).fetchone()[0]
                self.assertEqual(n, 0,
                                 "colbert sidecar should be empty when disabled")
                conn.close()
        finally:
            if orig is not None:
                os.environ["KAIZEN_COLBERT_ENABLE"] = orig

    @requires_numpy
    def test_insert_populates_colbert_when_enabled(self):
        import struct as _struct
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        import onboard_index as oi
        import index_flow as ix

        os.environ["KAIZEN_COLBERT_ENABLE"] = "1"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "x.py").write_text("def f(): pass\n" * 5)
                fake_embed = lambda texts: (
                    [_struct.pack("384f", *([i / 100.0] * 384))
                     for i in range(len(texts))],
                    384,
                )
                # Mock ColBERT encoder: produce a (4, 8) matrix per text
                fake_colbert = lambda texts, **kw: [
                    np.eye(4, 8, dtype=np.float32) for _ in texts
                ]
                with patch.object(oi._kz_embed, "embed_batch", side_effect=fake_embed), \
                     patch.object(oi._kz_colbert, "is_available", return_value=True), \
                     patch.object(oi._kz_colbert, "encode_colbert_batch", side_effect=fake_colbert):
                    ix.index(root, use_git=False)
                conn = oi.open_db(root, create=False)
                rows = conn.execute(
                    "SELECT chunk_id, vectors, seq_len, dim "
                    "FROM code_chunks_colbert"
                ).fetchall()
                self.assertGreater(len(rows), 0,
                                   "colbert sidecar should be populated")
                for r in rows:
                    self.assertEqual(r[2], 4)  # seq_len
                    self.assertEqual(r[3], 8)  # dim
                    mat = _colbert.deserialize(bytes(r[1]))
                    self.assertEqual(mat.shape, (4, 8))
                conn.close()
        finally:
            os.environ.pop("KAIZEN_COLBERT_ENABLE", None)


class TestColbertSearchEmpty(unittest.TestCase):
    @requires_numpy
    def test_colbert_search_empty_when_sidecar_missing(self):
        import sqlite3
        import tempfile
        from pathlib import Path

        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        import _search as kz_search

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "t.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "CREATE TABLE chunks (id INTEGER PRIMARY KEY, text TEXT)"
            )
            # No code_chunks_colbert table — search must return []
            result = kz_search.colbert_search(conn, "chunks", "query")
            self.assertEqual(result, [])
            conn.close()


@unittest.skipUnless(
    _colbert.is_available(),
    "transformers + torch + ColBERT model not available "
    "(skip integration tests — pure-logic tests above still run)",
)
class TestColbertEncodeReal(unittest.TestCase):
    """Live ColBERT-model tests."""

    def test_encode_returns_2d_matrix(self):
        mat = _colbert.encode_colbert("def carve(old, new): pass")
        self.assertEqual(mat.ndim, 2)
        self.assertGreater(mat.shape[0], 0)
        self.assertGreater(mat.shape[1], 0)

    def test_encode_l2_normalized(self):
        mat = _colbert.encode_colbert("hello world")
        # Each row L2-normalized
        norms = np.linalg.norm(mat, axis=1)
        np.testing.assert_array_almost_equal(norms, np.ones_like(norms), decimal=3)

    def test_encode_roundtrip_via_storage(self):
        mat = _colbert.encode_colbert("def func(x): return x + 1")
        blob = _colbert.serialize(mat)
        restored = _colbert.deserialize(blob)
        np.testing.assert_array_almost_equal(restored, mat)

    def test_self_score_higher_than_unrelated(self):
        # Query against itself should score higher than against an
        # unrelated text — sanity check for the MaxSim implementation
        q = _colbert.encode_colbert("python function carve files")
        d_self = q
        d_other = _colbert.encode_colbert("the quick brown fox jumps over")
        self.assertGreater(
            _colbert.max_sim_score(q, d_self),
            _colbert.max_sim_score(q, d_other),
        )


if __name__ == "__main__":
    unittest.main()
