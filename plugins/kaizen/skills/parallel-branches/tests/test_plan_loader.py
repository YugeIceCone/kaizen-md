"""Paired tests for _plan_loader.py — Mode A passthrough + Mode B glob resolution."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "scripts"))

from _plan_loader import load_plan  # noqa: E402


class TestPlanLoader(unittest.TestCase):
    def test_mode_a_inline_chunks_passthrough(self):
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan.yaml"
            plan.write_text(
                'version: 1\n'
                'date: "2026-05-18"\n'
                'chunks:\n'
                '  - id: chunk-1\n'
                '    items_count: 2\n'
                'merge:\n'
                '  actions: [consolidate_perms]\n'
            )
            loaded = load_plan(plan)
            self.assertIsInstance(loaded["chunks"], list)
            self.assertEqual(loaded["chunks"][0]["id"], "chunk-1")
            self.assertIsInstance(loaded["merge"], dict)
            self.assertEqual(loaded["merge"]["actions"], ["consolidate_perms"])

    def test_mode_b_glob_resolution(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "chunks").mkdir()
            (base / "chunks/chunk-01.yaml").write_text("id: chunk-01\nitems_count: 2\n")
            (base / "chunks/chunk-02.yaml").write_text("id: chunk-02\nitems_count: 3\n")
            (base / "merge.yaml").write_text("actions: [merge_commit, final_verify]\n")
            (base / "plan.yaml").write_text(
                'version: 1\n'
                'chunks: "./chunks/*.yaml"\n'
                'merge: "./merge.yaml"\n'
            )
            loaded = load_plan(base / "plan.yaml")
            self.assertEqual(len(loaded["chunks"]), 2)
            self.assertEqual(loaded["chunks"][0]["id"], "chunk-01")
            self.assertEqual(loaded["chunks"][1]["id"], "chunk-02")
            self.assertEqual(loaded["merge"]["actions"], ["merge_commit", "final_verify"])

    def test_mode_b_glob_zero_matches_raises(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "plan.yaml").write_text(
                'version: 1\nchunks: "./missing/*.yaml"\n'
            )
            with self.assertRaises(FileNotFoundError):
                load_plan(Path(td) / "plan.yaml")

    def test_mode_b_merge_path_missing_raises(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "plan.yaml").write_text(
                'version: 1\n'
                'chunks: []\n'
                'merge: "./nope.yaml"\n'
            )
            with self.assertRaises(FileNotFoundError):
                load_plan(Path(td) / "plan.yaml")

    def test_chunks_sorted_by_filename(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "chunks").mkdir()
            # Reverse-create to make sure sorted() is what gives order
            (base / "chunks/chunk-03.yaml").write_text("id: chunk-03\n")
            (base / "chunks/chunk-01.yaml").write_text("id: chunk-01\n")
            (base / "chunks/chunk-02.yaml").write_text("id: chunk-02\n")
            (base / "plan.yaml").write_text(
                'version: 1\nchunks: "./chunks/*.yaml"\n'
            )
            loaded = load_plan(base / "plan.yaml")
            self.assertEqual([c["id"] for c in loaded["chunks"]],
                              ["chunk-01", "chunk-02", "chunk-03"])


if __name__ == "__main__":
    unittest.main()
