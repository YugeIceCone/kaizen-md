"""Tests for _sparse.py — SPLADE sparse encoding helpers.

The real SPLADE encoder requires transformers + torch + a ~500 MB
model download; those tests skip when the deps are missing (same
discipline as test_binary_quantization with numpy). The pure-logic
parts — serialize / deserialize / dot_product / env handling — are
unit-testable with synthetic dicts and run in every CI environment.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))

import _sparse  # noqa: E402


class TestSparseSerialization(unittest.TestCase):
    def test_serialize_roundtrip_basic(self):
        sparse = {42: 1.23, 1024: 0.45, 0: 0.0001}
        blob = _sparse.serialize(sparse)
        out = _sparse.deserialize(blob)
        self.assertEqual(set(out.keys()), set(sparse.keys()))
        for k in sparse:
            self.assertAlmostEqual(out[k], sparse[k], places=4)

    def test_serialize_empty_dict(self):
        blob = _sparse.serialize({})
        self.assertEqual(_sparse.deserialize(blob), {})

    def test_serialize_compact_separators(self):
        # Compact JSON — no whitespace between items
        blob = _sparse.serialize({1: 0.5, 2: 0.7})
        self.assertNotIn(b" ", blob)

    def test_deserialize_empty_blob(self):
        self.assertEqual(_sparse.deserialize(b""), {})
        self.assertEqual(_sparse.deserialize(b"{}"), {})

    def test_deserialize_invalid_json(self):
        self.assertEqual(_sparse.deserialize(b"not json"), {})

    def test_deserialize_non_object(self):
        self.assertEqual(_sparse.deserialize(b'[1, 2, 3]'), {})
        self.assertEqual(_sparse.deserialize(b"null"), {})
        self.assertEqual(_sparse.deserialize(b'"string"'), {})

    def test_deserialize_strips_non_numeric_keys(self):
        # If a tampered blob has non-numeric keys, drop them
        bad = b'{"foo": 1.0, "42": 1.5, "7": "not-a-float"}'
        out = _sparse.deserialize(bad)
        self.assertNotIn("foo", out)
        self.assertEqual(out[42], 1.5)
        self.assertNotIn(7, out)

    def test_serialize_handles_int_like_keys(self):
        # Caller might pass numpy int64 etc. — serialize should coerce
        sparse = {True: 0.5}  # bool is int subclass
        blob = _sparse.serialize(sparse)
        out = _sparse.deserialize(blob)
        self.assertEqual(out[1], 0.5)


class TestSparseDotProduct(unittest.TestCase):
    def test_dot_basic(self):
        q = {1: 0.5, 2: 0.4, 3: 0.3}
        d = {2: 1.0, 3: 1.0, 4: 1.0}
        # Intersection on keys 2 and 3
        self.assertAlmostEqual(_sparse.dot_product(q, d), 0.4 + 0.3, places=6)

    def test_dot_disjoint_keys(self):
        self.assertEqual(_sparse.dot_product({1: 1.0}, {2: 1.0}), 0.0)

    def test_dot_one_empty(self):
        self.assertEqual(_sparse.dot_product({}, {1: 1.0}), 0.0)
        self.assertEqual(_sparse.dot_product({1: 1.0}, {}), 0.0)

    def test_dot_both_empty(self):
        self.assertEqual(_sparse.dot_product({}, {}), 0.0)

    def test_dot_iterates_smaller_dict(self):
        # Smaller-side iteration is an internal efficiency; result must be
        # identical regardless of which side is bigger.
        q = {1: 0.1, 2: 0.2}
        d = {i: 0.5 for i in range(100)}
        self.assertAlmostEqual(_sparse.dot_product(q, d), 0.05 + 0.10, places=6)
        self.assertAlmostEqual(_sparse.dot_product(d, q), 0.05 + 0.10, places=6)

    def test_dot_negative_weights(self):
        # SPLADE weights are positive (log(1+ReLU(x))), but the dot
        # product math must work for any signed weight pair.
        q = {1: -0.5, 2: 1.0}
        d = {1: 1.0, 2: -1.0}
        self.assertAlmostEqual(_sparse.dot_product(q, d), -0.5 - 1.0, places=6)

    def test_dot_product_batch(self):
        q = {1: 1.0, 2: 1.0}
        docs = [
            {1: 0.5, 2: 0.5},   # 0.5 + 0.5 = 1.0
            {1: 1.0},           # 1.0
            {3: 1.0},           # disjoint → 0
            {},                 # empty → 0
        ]
        scores = _sparse.dot_product_batch(q, docs)
        self.assertEqual(scores, [1.0, 1.0, 0.0, 0.0])

    def test_dot_product_batch_empty_query(self):
        # Empty query → all-zero scores
        scores = _sparse.dot_product_batch({}, [{1: 1.0}, {2: 1.0}])
        self.assertEqual(scores, [0.0, 0.0])


class TestSparseEnv(unittest.TestCase):
    """Env-knob behavior — these don't load the model, just check
    the resolver returns the right value for each env state."""

    def _restore(self, name, val):
        if val is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = val

    def test_default_model_name(self):
        orig = os.environ.pop("KAIZEN_SPARSE_MODEL", None)
        try:
            self.assertIn("splade", _sparse.sparse_model_name().lower())
        finally:
            self._restore("KAIZEN_SPARSE_MODEL", orig)

    def test_env_override_model(self):
        orig = os.environ.get("KAIZEN_SPARSE_MODEL")
        os.environ["KAIZEN_SPARSE_MODEL"] = "custom/model"
        try:
            self.assertEqual(_sparse.sparse_model_name(), "custom/model")
        finally:
            self._restore("KAIZEN_SPARSE_MODEL", orig)

    def test_is_sparse_enabled_default_off(self):
        orig = os.environ.pop("KAIZEN_SPARSE_ENABLE", None)
        try:
            self.assertFalse(_sparse.is_sparse_enabled())
        finally:
            self._restore("KAIZEN_SPARSE_ENABLE", orig)

    def test_is_sparse_enabled_truthy_values(self):
        orig = os.environ.get("KAIZEN_SPARSE_ENABLE")
        try:
            for val in ("1", "true", "TRUE", "yes", "on"):
                os.environ["KAIZEN_SPARSE_ENABLE"] = val
                self.assertTrue(
                    _sparse.is_sparse_enabled(), f"failed for {val!r}"
                )
            for val in ("0", "false", "no", "off", ""):
                os.environ["KAIZEN_SPARSE_ENABLE"] = val
                self.assertFalse(
                    _sparse.is_sparse_enabled(), f"failed for {val!r}"
                )
        finally:
            self._restore("KAIZEN_SPARSE_ENABLE", orig)

    def test_max_length_default(self):
        orig = os.environ.pop("KAIZEN_SPARSE_MAX_LENGTH", None)
        try:
            self.assertEqual(_sparse._max_length(), 256)
        finally:
            self._restore("KAIZEN_SPARSE_MAX_LENGTH", orig)

    def test_max_length_floor(self):
        # Floor at 32 to keep the encoder from getting empty inputs
        orig = os.environ.get("KAIZEN_SPARSE_MAX_LENGTH")
        os.environ["KAIZEN_SPARSE_MAX_LENGTH"] = "1"
        try:
            self.assertEqual(_sparse._max_length(), 32)
        finally:
            self._restore("KAIZEN_SPARSE_MAX_LENGTH", orig)


class TestSparseGracefulFallback(unittest.TestCase):
    """When transformers/torch aren't installed, encode_sparse* must
    return None / [None, ...] without crashing — same discipline as
    cross_encoder_rerank when sentence_transformers is missing."""

    def setUp(self):
        # Force a cache reset so the test sees the real (or missing) deps.
        _sparse.reset_cache()

    def test_encode_returns_none_when_unavailable(self):
        # When deps are missing, encode_sparse returns None. When deps
        # are present, encode_sparse returns a dict. Either is allowed
        # by the contract — this test verifies the SHAPE doesn't crash.
        result = _sparse.encode_sparse("hello world")
        self.assertTrue(result is None or isinstance(result, dict))

    def test_encode_batch_returns_none_list_or_dicts(self):
        result = _sparse.encode_sparse_batch(["a", "b", "c"])
        self.assertEqual(len(result), 3)
        for r in result:
            self.assertTrue(r is None or isinstance(r, dict))

    def test_encode_batch_empty(self):
        self.assertEqual(_sparse.encode_sparse_batch([]), [])

    def test_is_available_returns_bool(self):
        self.assertIsInstance(_sparse.is_available(), bool)


try:
    import numpy  # noqa: F401
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

requires_numpy = unittest.skipUnless(NUMPY_AVAILABLE, "numpy not installed")


class TestSparseSchemaMigration(unittest.TestCase):
    """Migration + INSERT integration — covers the onboard_index path
    where `embedding_sparse` column is added and populated.

    Uses a mocked encoder + serializer so the test runs without
    transformers/torch + the 500 MB SPLADE model."""

    @requires_numpy
    def test_migration_adds_embedding_sparse_column(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        import onboard_index as oi

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = oi.open_db(root, create=True)
            cols = {row[1] for row in conn.execute(
                "PRAGMA table_info(code_chunks)"
            )}
            self.assertIn("embedding_sparse", cols,
                          "sparse migration must add embedding_sparse")
            conn.close()

    @requires_numpy
    def test_migration_idempotent_on_pre_v134_db(self):
        """Simulate a pre-v1.34 db (no embedding_sparse column), then
        run open_db; the migration must add the column without error."""
        import sqlite3
        import tempfile
        from pathlib import Path

        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        import onboard_index as oi

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # First open creates the v1.34 schema.
            conn = oi.open_db(root, create=True)
            conn.close()

            # Simulate pre-v1.34: manually drop the column. SQLite < 3.35
            # doesn't support DROP COLUMN, so we rebuild the table
            # without the sparse column instead.
            db = sqlite3.connect(oi.db_path(root))
            db.executescript("""
                CREATE TABLE code_chunks_old AS SELECT
                    id, file_id, chunk_idx, char_start, char_end,
                    text, embedding, embedding_q8, language, kind, symbol_name
                FROM code_chunks;
                DROP TABLE code_chunks;
                ALTER TABLE code_chunks_old RENAME TO code_chunks;
            """)
            db.commit()
            db.close()

            # Re-open — migration should add the column back.
            conn2 = oi.open_db(root, create=True)
            cols = {row[1] for row in conn2.execute(
                "PRAGMA table_info(code_chunks)"
            )}
            self.assertIn("embedding_sparse", cols)
            conn2.close()

    @requires_numpy
    def test_insert_skips_sparse_when_disabled(self):
        """Default behavior: KAIZEN_SPARSE_ENABLE unset → embedding_sparse
        rows are NULL across the board."""
        import struct
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        import onboard_index as oi
        import index_flow as ix

        orig = os.environ.pop("KAIZEN_SPARSE_ENABLE", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "x.py").write_text("def f(): pass\n" * 5)
                fake = lambda texts: (
                    [struct.pack("384f", *([i / 100.0] * 384))
                     for i in range(len(texts))],
                    384,
                )
                with patch.object(oi._kz_embed, "embed_batch", side_effect=fake):
                    ix.index(root, use_git=False)
                conn = oi.open_db(root, create=False)
                n_sparse = conn.execute(
                    "SELECT COUNT(*) FROM code_chunks "
                    "WHERE embedding_sparse IS NOT NULL"
                ).fetchone()[0]
                self.assertEqual(n_sparse, 0,
                                 "sparse should be NULL when KAIZEN_SPARSE_ENABLE unset")
                conn.close()
        finally:
            if orig is not None:
                os.environ["KAIZEN_SPARSE_ENABLE"] = orig

    @requires_numpy
    def test_insert_populates_sparse_when_enabled(self):
        """KAIZEN_SPARSE_ENABLE=1 + mocked encoder → rows have non-NULL
        embedding_sparse with valid JSON shape."""
        import struct
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        import onboard_index as oi
        import index_flow as ix

        os.environ["KAIZEN_SPARSE_ENABLE"] = "1"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "x.py").write_text("def f(): pass\n" * 5)
                fake_embed = lambda texts: (
                    [struct.pack("384f", *([i / 100.0] * 384))
                     for i in range(len(texts))],
                    384,
                )
                # Mock sparse encoder so we don't need transformers/torch.
                fake_sparse = lambda texts, **kw: [
                    {7: 1.0, 42: 0.5} for _ in texts
                ]
                with patch.object(oi._kz_embed, "embed_batch", side_effect=fake_embed), \
                     patch.object(oi._kz_sparse, "is_available", return_value=True), \
                     patch.object(oi._kz_sparse, "encode_sparse_batch", side_effect=fake_sparse):
                    ix.index(root, use_git=False)
                conn = oi.open_db(root, create=False)
                rows = conn.execute(
                    "SELECT embedding_sparse FROM code_chunks "
                    "WHERE embedding_sparse IS NOT NULL"
                ).fetchall()
                self.assertGreater(len(rows), 0,
                                   "sparse should be populated when enabled")
                # Each blob must deserialize to {int: float}
                for r in rows:
                    decoded = _sparse.deserialize(bytes(r[0]))
                    self.assertEqual(decoded, {7: 1.0, 42: 0.5})
                conn.close()
        finally:
            os.environ.pop("KAIZEN_SPARSE_ENABLE", None)


class TestSparseSearchReturnsEmpty(unittest.TestCase):
    """sparse_search must return [] (not crash) when:
       - column missing
       - sparse module unavailable
       - no rows populated"""

    @requires_numpy
    def test_sparse_search_empty_when_column_missing(self):
        import sqlite3
        import tempfile
        from pathlib import Path

        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        import _search as kz_search

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "t.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "CREATE TABLE pretend_chunks (id INTEGER PRIMARY KEY, "
                "text TEXT, embedding BLOB)"
            )
            # No embedding_sparse column on this table.
            result = kz_search.sparse_search(conn, "pretend_chunks", "query")
            self.assertEqual(result, [])
            conn.close()


@unittest.skipUnless(
    _sparse.is_available(),
    "transformers + torch + SPLADE model not available "
    "(skip integration tests — pure-logic tests above still run)",
)
class TestSparseEncodeReal(unittest.TestCase):
    """Live SPLADE-model tests. Skipped when the deps aren't installed.

    These tests verify the encoder produces the expected sparse shape
    (dict[int, float] with positive weights) when the model is loaded.
    """

    def test_encode_returns_dict(self):
        out = _sparse.encode_sparse("def carve(old, new):")
        self.assertIsInstance(out, dict)
        self.assertGreater(len(out), 0)
        for k, v in out.items():
            self.assertIsInstance(k, int)
            self.assertIsInstance(v, float)
            self.assertGreater(v, 0)

    def test_encode_batch_lengths(self):
        out = _sparse.encode_sparse_batch(["hello world", "another text"])
        self.assertEqual(len(out), 2)
        for d in out:
            self.assertIsInstance(d, dict)

    def test_encode_roundtrip_via_storage(self):
        sparse = _sparse.encode_sparse("def func(x): return x + 1")
        self.assertIsNotNone(sparse)
        blob = _sparse.serialize(sparse)
        restored = _sparse.deserialize(blob)
        self.assertEqual(set(restored.keys()), set(sparse.keys()))


if __name__ == "__main__":
    unittest.main()
