"""Unit tests for `knowledge_index.iter_arch_log`.

The arch-log source type extracts one item per row from
`.kaizen/workflow/progress.md` + `archive/*.md` so agents can query
historical architectural rows via semantic search instead of reading
the whole file.

Run:
    python3 -m unittest tests.test_knowledge_arch_log -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "workflow" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))


def _setup_repo(tmpdir: Path, *, live_rows: list[str], archive_rows: list[str] | None = None):
    """Create a fake repo tree with progress.md + optional archive."""
    arch = tmpdir / ".kaizen" / "workflow"
    arch.mkdir(parents=True)
    live = arch / "progress.md"
    live.write_text(
        "# Architecture Log\n\n"
        "| date | scope | Δ LOC | summary |\n"
        "|------|-------|------|---------|\n"
        + "\n".join(live_rows) + "\n",
        encoding="utf-8",
    )
    if archive_rows is not None:
        archive = arch / "archive"
        archive.mkdir()
        (archive / "2026-05-progress.md").write_text(
            "# Archive\n\n"
            "| date | scope | Δ LOC | summary |\n"
            "|------|-------|------|---------|\n"
            + "\n".join(archive_rows) + "\n",
            encoding="utf-8",
        )


class TestIterArchLog(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)

    def _run(self, **kwargs):
        # Import inside the test so cwd-relative paths resolve fresh.
        if "knowledge_index" in sys.modules:
            del sys.modules["knowledge_index"]
        import knowledge_index as ki  # noqa: E402
        return list(ki.iter_arch_log()), ki

    def test_yields_one_item_per_row(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _setup_repo(tmp, live_rows=[
                "| 2026-05-12 | feat     | +320 | impl SemanticRouterNode |",
                "| 2026-05-13 | xtask    | ±0   | rename ast-scan command |",
            ])
            os.chdir(tmp)
            items, _ = self._run()
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["source"], "arch-log")
        self.assertIn("SemanticRouterNode", items[0]["title"])
        self.assertIn("rename ast-scan", items[1]["title"])

    def test_walks_both_live_and_archive(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _setup_repo(
                tmp,
                live_rows=["| 2026-05-13 | feat | +10 | live row |"],
                archive_rows=[
                    "| 2026-05-09 | §F1.1 | -100 | archived A |",
                    "| 2026-05-10 | §F2.2 | -200 | archived B |",
                ],
            )
            os.chdir(tmp)
            items, _ = self._run()
        self.assertEqual(len(items), 3)
        titles = "|".join(it["title"] for it in items)
        self.assertIn("live row", titles)
        self.assertIn("archived A", titles)
        self.assertIn("archived B", titles)

    def test_skips_table_separator_and_non_data_lines(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            arch = tmp / ".kaizen" / "workflow"
            arch.mkdir(parents=True)
            (arch / "progress.md").write_text(
                "# Architecture Log\n\n"
                "Prose blah blah.\n\n"
                "| date | scope | Δ LOC | summary |\n"
                "|------|-------|------|---------|\n"
                "| 2026-05-12 | feat | +50 | only this should index |\n"
                "\n"
                "<!-- comment -->\n",
                encoding="utf-8",
            )
            os.chdir(tmp)
            items, _ = self._run()
        self.assertEqual(len(items), 1)
        self.assertIn("only this should index", items[0]["title"])

    def test_each_item_carries_scope_in_tags(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _setup_repo(tmp, live_rows=[
                "| 2026-05-10 | §F2.2 | -7101 | carve crates/quality/ |",
            ])
            os.chdir(tmp)
            items, _ = self._run()
        self.assertIn("§F2.2", items[0]["tags"])
        self.assertIn("arch-log", items[0]["tags"])

    def test_source_path_includes_date_and_scope_anchor(self):
        # Stable source_path lets multiple rows from the same file co-exist
        # in the sha-deduped index without collision.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _setup_repo(tmp, live_rows=[
                "| 2026-05-13 | xtask | ±0 | row A |",
                "| 2026-05-13 | xtask | ±0 | row B |",
            ])
            os.chdir(tmp)
            items, _ = self._run()
        # Both rows have same date+scope but different summaries → titles must differ
        self.assertNotEqual(items[0]["title"], items[1]["title"])
        # source_path encodes the file+anchor, not the summary; collision-tolerant
        # because the indexer's sha includes title (per item_sha contract).
        self.assertTrue(items[0]["source_path"].endswith("#2026-05-13-xtask"))

    def test_snippet_contains_full_row_fields(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _setup_repo(tmp, live_rows=[
                "| 2026-05-12 | feat | +320 | impl SemanticRouterNode |",
            ])
            os.chdir(tmp)
            items, _ = self._run()
        snip = items[0]["snippet"]
        self.assertIn("2026-05-12", snip)
        self.assertIn("feat", snip)
        self.assertIn("+320", snip)
        self.assertIn("SemanticRouterNode", snip)

    def test_empty_when_no_kaizen_workflow_dir(self):
        with tempfile.TemporaryDirectory() as td:
            os.chdir(td)
            items, _ = self._run()
        self.assertEqual(items, [])

    def test_iter_all_sources_includes_arch_log(self):
        """Lock the wire-up — arch-log must be in iter_all_sources()."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _setup_repo(tmp, live_rows=[
                "| 2026-05-13 | feat | +10 | unique-arch-row-marker |",
            ])
            os.chdir(tmp)
            if "knowledge_index" in sys.modules:
                del sys.modules["knowledge_index"]
            import knowledge_index as ki  # noqa: E402
            items = list(ki.iter_all_sources())
        # The row should appear via the all-sources generator.
        self.assertTrue(
            any("unique-arch-row-marker" in it.get("title", "") for it in items),
            msg=f"arch-log row not surfaced via iter_all_sources(); got {len(items)} items",
        )


if __name__ == "__main__":
    unittest.main()
