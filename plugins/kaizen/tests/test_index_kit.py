"""Phase 4.A: shared primitives for the 7 kaizen semantic indexers.

Three primitives:
- compute_corpus_drift(root, glob, exclude_files) — stat-only hash
- daemon_drift_job(...) — factory returning a (state) → (ok, msg, action)
- atomic_open_with_migrations(...) — SQLite open + idempotent migrations
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(ROOT / "scripts" / "daemon"))

class TestComputeCorpusDrift(unittest.TestCase):

    def test_empty_dir_returns_empty_string(self):
        import _index_kit as ik
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(ik.compute_corpus_drift(Path(td), "*.md"), "")

    def test_returns_empty_when_root_missing(self):
        import _index_kit as ik
        self.assertEqual(
            ik.compute_corpus_drift(Path("/does/not/exist"), "*.md"), "")

    def test_same_files_same_hash(self):
        import _index_kit as ik
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a.md").write_text("a")
            (Path(td) / "b.md").write_text("b")
            h1 = ik.compute_corpus_drift(Path(td), "*.md")
            h2 = ik.compute_corpus_drift(Path(td), "*.md")
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 16)

    def test_drift_detected_when_file_added(self):
        import _index_kit as ik
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a.md").write_text("a")
            h1 = ik.compute_corpus_drift(Path(td), "*.md")
            time.sleep(0.01)
            (Path(td) / "b.md").write_text("b")
            h2 = ik.compute_corpus_drift(Path(td), "*.md")
        self.assertNotEqual(h1, h2)

    def test_exclude_files_skipped(self):
        import _index_kit as ik
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a.md").write_text("a")
            (Path(td) / "INDEX.md").write_text("index")
            h_with = ik.compute_corpus_drift(Path(td), "*.md")
            h_without = ik.compute_corpus_drift(Path(td), "*.md",
                                                  exclude_files=["INDEX.md"])
        self.assertNotEqual(h_with, h_without)

class TestDaemonDriftJob(unittest.TestCase):

    def test_disabled_via_env(self):
        import _index_kit as ik
        called = []
        job = ik.daemon_drift_job(
            "test-job", "KAIZEN_TEST_JOB_DISABLE",
            hash_fn=lambda: "abc", regen_fn=lambda: called.append("yes"),
        )
        with patch.dict(os.environ, {"KAIZEN_TEST_JOB_DISABLE": "1"}):
            ok, msg, action = job(state={})
        self.assertTrue(ok)
        self.assertEqual(action, "test-job")
        self.assertIn("disabled", msg.lower())
        self.assertEqual(called, [])

    def test_no_drift_skips_regen(self):
        import _index_kit as ik
        called = []
        job = ik.daemon_drift_job(
            "test-job", "DISABLE_KEY",
            hash_fn=lambda: "abc",
            regen_fn=lambda: called.append("ran"),
        )
        state = {"test_job_hash": "abc"}
        env_copy = {k: v for k, v in os.environ.items()
                    if k != "DISABLE_KEY"}
        with patch.dict(os.environ, env_copy, clear=True):
            ok, msg, _ = job(state)
        self.assertTrue(ok)
        self.assertIn("no drift", msg.lower())
        self.assertEqual(called, [])

    def test_drift_triggers_regen_and_stamps_state(self):
        import _index_kit as ik
        called = []
        job = ik.daemon_drift_job(
            "test-job", "DISABLE_KEY",
            hash_fn=lambda: "NEW",
            regen_fn=lambda: called.append("ran"),
        )
        state = {"test_job_hash": "OLD"}
        env_copy = {k: v for k, v in os.environ.items()
                    if k != "DISABLE_KEY"}
        with patch.dict(os.environ, env_copy, clear=True):
            ok, _, _ = job(state)
        self.assertTrue(ok)
        self.assertEqual(called, ["ran"])
        self.assertEqual(state["test_job_hash"], "NEW")

    def test_regen_exception_does_not_stamp(self):
        import _index_kit as ik
        def boom():
            raise OSError("disk full")
        job = ik.daemon_drift_job(
            "test-job", "DISABLE_KEY",
            hash_fn=lambda: "NEW",
            regen_fn=boom,
        )
        state = {"test_job_hash": "OLD"}
        env_copy = {k: v for k, v in os.environ.items()
                    if k != "DISABLE_KEY"}
        with patch.dict(os.environ, env_copy, clear=True):
            ok, msg, _ = job(state)
        self.assertFalse(ok)
        self.assertIn("OSError", msg)
        # State NOT stamped → next tick retries
        self.assertEqual(state["test_job_hash"], "OLD")

class TestAtomicOpenWithMigrations(unittest.TestCase):

    def test_creates_db_with_schema_and_runs_migrations(self):
        import _index_kit as ik
        schema = "CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, name TEXT);"
        migrations_called = []
        def m1(conn):
            migrations_called.append("m1")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_name ON t(name)")
        def m2(conn):
            migrations_called.append("m2")
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            conn = ik.atomic_open_with_migrations(
                db, schema, migrations=[m1, m2],
            )
        self.assertEqual(migrations_called, ["m1", "m2"])
        # Schema applied
        cols = {row[1] for row in conn.execute("PRAGMA table_info(t)")}
        self.assertEqual(cols, {"id", "name"})

if __name__ == "__main__":
    unittest.main()
