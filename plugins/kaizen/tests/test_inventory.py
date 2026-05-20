"""Tests for kaizen-inventory — recursive walk + pattern recognition + dump.

Five batches map to the 20 features brainstormed in the v4 design:
  A — per-file enrichment (token count / sha256 / LOC / symbol extraction)
  B — smarter subverbs (map / tree / outline / grep-symbol / budget)
  C — filters (--not-type / --mtime-since / --git-since / --min-lines / --dedupe)
  D — output formats (html / --for-rag / --for-llm / --sqlite / --validate)
  E — import graph (cross-file imports / imported_by)

All tests run against a hermetic temp-dir sandbox; no host plugin mutation.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "scripts/util/inventory.py"


# ───────────────────────────── helpers ──────────────────────────────

def _run(*args, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True, text=True, timeout=30,
        cwd=cwd, env=os.environ.copy(),
    )


def _seed_sandbox(tmp: Path) -> Path:
    """Build a tiny plugin-shaped sandbox under tmp/plugins/kaizen/."""
    root = tmp / "plugins" / "kaizen"
    (root / "skills" / "demo").mkdir(parents=True)
    (root / "skills" / "demo" / "domain").mkdir()
    (root / "commands").mkdir()
    (root / "bin").mkdir()
    (root / "scripts" / "mcp").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "agents").mkdir()

    (root / "skills" / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: demo skill\n---\n# demo\n## section\nbody\n")
    (root / "skills" / "demo" / "domain" / "demo.yaml").write_text("key: value\n")
    (root / "skills" / "demo" / "domain" / "demo-rubric.yaml").write_text("rules: []\n")
    (root / "commands" / "demo.md").write_text("---\nname: demo\n---\n# /demo\n")
    (root / "bin" / "kaizen-demo").write_text("#!/usr/bin/env bash\necho hi\n")
    (root / "scripts" / "mcp" / "demo_mcp.py").write_text(
        '"""Demo MCP."""\nfrom fastmcp import FastMCP\nmcp = FastMCP("demo")\n'
        '@mcp.tool()\nasync def demo_ping(): return {"ok": True}\n'
        'if __name__ == "__main__": mcp.run()\n')
    (root / "scripts" / "small.py").write_text(
        '"""Small module with one class + one function."""\n\n'
        'class Widget:\n'
        '    """A widget."""\n'
        '    def hello(self):\n'
        '        return "hi"\n\n'
        'def make() -> Widget:\n'
        '    return Widget()\n'
        '\n'
        '# comment line\n')
    (root / "scripts" / "imports_small.py").write_text(
        "import small\nfrom small import Widget\n\n"
        "def use():\n    return Widget()\n")
    (root / "scripts" / "tiny.py").write_text("x = 1\n")  # 1 LOC
    (root / "scripts" / "duplicate.py").write_text("x = 1\n")  # same content as tiny
    (root / "tests" / "test_demo.py").write_text(
        "import unittest\nclass T(unittest.TestCase):\n    def test_x(self): pass\n")
    return root


# ─────────────────────── A. Per-file enrichment ──────────────────────

class TestPerFileEnrichment(unittest.TestCase):
    """Batch A — features 1, 2, 3, 4."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = Path(tempfile.mkdtemp(prefix="inv-A-"))
        cls.root = _seed_sandbox(cls._tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _jsonl_records(self) -> list[dict]:
        r = _run("dump", "--format", "jsonl", "--root", str(self.root))
        self.assertEqual(r.returncode, 0, r.stderr)
        return [json.loads(line) for line in r.stdout.splitlines() if line.strip()]

    # ── #1 token count per file ──
    def test_jsonl_has_token_count_per_file(self):
        for r in self._jsonl_records():
            self.assertIn("tokens", r, f"missing tokens field: {r['path']}")
            self.assertGreaterEqual(r["tokens"], 0)

    # ── #2 content sha256 ──
    def test_jsonl_has_sha256_64hex(self):
        for r in self._jsonl_records():
            self.assertIn("sha256", r, f"missing sha256: {r['path']}")
            self.assertEqual(len(r["sha256"]), 64)
            int(r["sha256"], 16)  # valid hex

    # ── #3 nonblank + comment LOC ──
    def test_py_files_have_nonblank_and_comment_counts(self):
        recs = {r["path"]: r for r in self._jsonl_records()}
        # small.py: 11 lines total; 1 comment line; 1 blank line
        small = next(r for k, r in recs.items() if k.endswith("/small.py"))
        self.assertIn("nonblank_lines", small)
        self.assertIn("comment_lines", small)
        self.assertGreaterEqual(small["comment_lines"], 1)
        self.assertLess(small["nonblank_lines"], small["lines"])

    # ── #4 symbol extraction (py) ──
    def test_py_file_has_symbol_list(self):
        recs = {r["path"]: r for r in self._jsonl_records()}
        small = next(r for k, r in recs.items() if k.endswith("/small.py"))
        self.assertIn("symbols", small)
        kinds = {s["kind"]: s["name"] for s in small["symbols"]}
        self.assertIn("class", kinds)
        self.assertEqual(kinds["class"], "Widget")
        names = {s["name"] for s in small["symbols"]}
        self.assertIn("hello", names)
        self.assertIn("make", names)

    # ── #4 symbol extraction (md) ──
    def test_md_file_has_heading_symbols(self):
        recs = {r["path"]: r for r in self._jsonl_records()}
        skill = next(r for k, r in recs.items() if k.endswith("SKILL.md"))
        names = {s["name"] for s in skill.get("symbols", [])}
        self.assertIn("demo", names)
        self.assertIn("section", names)


# ─────────────────────── B. Smarter subverbs ─────────────────────────

class TestSubverbs(unittest.TestCase):
    """Batch B — features 6, 7, 8, 9, 10."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = Path(tempfile.mkdtemp(prefix="inv-B-"))
        cls.root = _seed_sandbox(cls._tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    # ── #7 tree subverb ──
    def test_tree_prints_directory_layout(self):
        r = _run("tree", "--root", str(self.root))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("skills/demo/SKILL.md", r.stdout)
        self.assertIn("commands/demo.md", r.stdout)

    # ── #8 outline subverb ──
    def test_outline_collects_headings_and_docstrings(self):
        r = _run("outline", "--root", str(self.root))
        self.assertEqual(r.returncode, 0, r.stderr)
        # md headings
        self.assertIn("demo", r.stdout)
        # py docstrings
        self.assertIn("Small module with one class + one function", r.stdout)

    # ── #6 map subverb ──
    def test_map_emits_symbols_per_file(self):
        r = _run("map", "--root", str(self.root))
        self.assertEqual(r.returncode, 0, r.stderr)
        # one-line-per-symbol shape
        self.assertIn("class Widget", r.stdout)
        self.assertIn("def make", r.stdout)

    # ── #9 token budget ──
    def test_dump_token_budget_truncates(self):
        # tiny budget → should drop most files but stay non-empty
        r = _run("dump", "--root", str(self.root), "--budget", "50",
                 "--format", "jsonl")
        self.assertEqual(r.returncode, 0, r.stderr)
        recs = [json.loads(l) for l in r.stdout.splitlines() if l.strip()]
        self.assertGreater(len(recs), 0)
        total = sum(rec["tokens"] for rec in recs)
        self.assertLessEqual(total, 1000)  # generous bound

    # ── #10 grep-symbol ──
    def test_grep_symbol_finds_class(self):
        r = _run("grep-symbol", "Widget", "--root", str(self.root))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("small.py", r.stdout)


# ────────────────────────── C. Filters ─────────────────────────────

class TestFilters(unittest.TestCase):
    """Batch C — features 11, 12, 13, 14, 15."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = Path(tempfile.mkdtemp(prefix="inv-C-"))
        cls.root = _seed_sandbox(cls._tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    # ── #11 --not-type ──
    def test_not_type_excludes_tests(self):
        r = _run("list", "--root", str(self.root), "--not-type", "test")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("test_demo.py", r.stdout)
        self.assertIn("skills/demo/SKILL.md", r.stdout)

    # ── #12 --mtime-since ──
    def test_mtime_since_filters_old_files(self):
        # touch one file recently; another we'll backdate
        recent = self.root / "scripts" / "tiny.py"
        old = self.root / "scripts" / "duplicate.py"
        os.utime(recent, None)
        old_ts = time.time() - 30 * 86400  # 30 days ago
        os.utime(old, (old_ts, old_ts))
        r = _run("list", "--root", str(self.root), "--mtime-since", "7d")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("tiny.py", r.stdout)
        self.assertNotIn("duplicate.py", r.stdout)

    # ── #14 --min-lines / --max-lines ──
    def test_min_lines_filters_empty(self):
        r = _run("list", "--root", str(self.root), "--min-lines", "5")
        self.assertEqual(r.returncode, 0, r.stderr)
        # tiny.py (1 line) excluded
        self.assertNotIn("tiny.py", r.stdout)
        # small.py (>5 lines) included
        self.assertIn("small.py", r.stdout)

    # ── #15 --dedupe ──
    def test_dedupe_collapses_identical_content(self):
        # tiny.py and duplicate.py have identical content
        r = _run("list", "--root", str(self.root), "--dedupe", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = json.loads(r.stdout)
        paths = {row["path"] for row in rows}
        # Either tiny.py or duplicate.py is included; not both
        kept = paths & {"plugins/kaizen/scripts/tiny.py",
                          "plugins/kaizen/scripts/duplicate.py",
                          "kaizen/scripts/tiny.py",
                          "kaizen/scripts/duplicate.py"}
        self.assertEqual(len(kept), 1, f"dedupe should keep one; got {kept}")

    # ── #13 --git-since (depends on git, falls back if unavailable) ──
    def test_git_since_flag_recognized(self):
        # We just check the flag is accepted; full integration tested elsewhere.
        r = _run("list", "--root", str(self.root), "--git-since", "HEAD",
                 "--json")
        # Either returns empty (no git) with rc 0, or works.
        self.assertIn(r.returncode, (0, 1), r.stderr)


# ──────────────────────── D. Output formats ──────────────────────────

class TestOutputFormats(unittest.TestCase):
    """Batch D — features 16, 17, 18, 19, 20."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = Path(tempfile.mkdtemp(prefix="inv-D-"))
        cls.root = _seed_sandbox(cls._tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    # ── #16 html ──
    def test_html_format_emits_valid_html(self):
        out_file = self.root.parent / "dump.html"
        r = _run("dump", "--root", str(self.root), "--format", "html",
                 "--out", str(out_file))
        self.assertEqual(r.returncode, 0, r.stderr)
        text = out_file.read_text()
        self.assertIn("<!DOCTYPE html>", text)
        self.assertIn("<details>", text)
        self.assertIn("SKILL.md", text)

    # ── #17 --for-rag (chunked) ──
    def test_for_rag_emits_chunked_records(self):
        r = _run("dump", "--root", str(self.root), "--format", "jsonl",
                 "--for-rag")
        self.assertEqual(r.returncode, 0, r.stderr)
        recs = [json.loads(l) for l in r.stdout.splitlines() if l.strip()]
        self.assertGreater(len(recs), 0)
        # chunks have window metadata
        chunk = recs[0]
        self.assertIn("chunk_index", chunk)
        self.assertIn("line_start", chunk)
        self.assertIn("line_end", chunk)

    # ── #18 --for-llm (bundle with structure + ranked) ──
    def test_for_llm_includes_structure_header(self):
        r = _run("dump", "--root", str(self.root), "--for-llm",
                 "--format", "markdown")
        self.assertEqual(r.returncode, 0, r.stderr)
        # has a directory-tree header at the top
        self.assertIn("# inventory", r.stdout)
        self.assertRegex(r.stdout, r"##? (Structure|Tree|Layout)")

    # ── #19 SQLite catalog ──
    def test_sqlite_catalog_creates_queryable_db(self):
        db = self.root.parent / "catalog.db"
        r = _run("dump", "--root", str(self.root), "--sqlite", str(db))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(db.exists())
        con = sqlite3.connect(db)
        try:
            tables = {row[0] for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("files", tables)
            (count,) = con.execute("SELECT count(*) FROM files").fetchone()
            self.assertGreater(count, 0)
        finally:
            con.close()

    # ── #20 schema validation pass ──
    def test_validate_pass_emits_status(self):
        r = _run("dump", "--root", str(self.root), "--validate",
                 "--format", "jsonl")
        self.assertEqual(r.returncode, 0, r.stderr)
        recs = [json.loads(l) for l in r.stdout.splitlines() if l.strip()]
        # At least one record carries a validation_status field
        with_status = [r for r in recs if "validation_status" in r]
        self.assertGreater(len(with_status), 0)


# ─────────────────────── E. Import graph ──────────────────────────

class TestMarkdownStructure(unittest.TestCase):
    """Each file section in a markdown dump must follow the same
    shape so downstream parsers / LLMs can navigate reliably."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = Path(tempfile.mkdtemp(prefix="inv-MD-"))
        cls.root = _seed_sandbox(cls._tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _md(self) -> str:
        r = _run("dump", "--format", "markdown", "--root", str(self.root))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_md_has_bundle_header(self):
        # Top-level bundle header: `# inventory ... — <root>` + summary
        text = self._md()
        self.assertRegex(text, r"^# inventory")
        # Summary line with file count
        self.assertRegex(text, r"\d+ files? matched")

    def test_every_file_section_has_metadata_line(self):
        """Every `## ` file header must be followed (blank line, then)
        by a metadata blockquote: `> type: X · bytes: N · lines: N · ...`"""
        text = self._md()
        sections = re.split(r"^## `", text, flags=re.MULTILINE)[1:]
        self.assertGreater(len(sections), 0, "expected ≥1 file section")
        for sec in sections:
            self.assertRegex(sec, r"^[^\n]+`\s*\n\s*>\s*type:",
                             f"missing metadata line in section: {sec[:120]}")

    def test_metadata_carries_canonical_fields(self):
        text = self._md()
        # At least one section should have all canonical fields visible
        self.assertRegex(text, r">\s*type:\s*\S+")
        self.assertRegex(text, r"bytes:\s*\d+")
        self.assertRegex(text, r"lines:\s*\d+")
        self.assertRegex(text, r"tokens:\s*\d+")
        self.assertRegex(text, r"sha:\s*[a-f0-9]{8,}")

    def test_every_file_section_has_fenced_code_block(self):
        text = self._md()
        # Fenced blocks come in pairs (open + close); count opens
        opens = len(re.findall(r"^```\w*$", text, flags=re.MULTILINE))
        sections = len(re.findall(r"^## `", text, flags=re.MULTILINE))
        self.assertEqual(opens, sections * 2,
                         f"expected {sections * 2} fence lines for {sections} sections; "
                         f"got {opens}")


class TestImportGraph(unittest.TestCase):
    """Batch E — feature 5."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = Path(tempfile.mkdtemp(prefix="inv-E-"))
        cls.root = _seed_sandbox(cls._tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_py_records_carry_imports_and_imported_by(self):
        r = _run("dump", "--root", str(self.root), "--format", "jsonl",
                 "--with-graph")
        self.assertEqual(r.returncode, 0, r.stderr)
        recs = {Path(r["path"]).name: r for r in
                  (json.loads(l) for l in r.stdout.splitlines() if l.strip())}
        importer = recs["imports_small.py"]
        importee = recs["small.py"]
        self.assertIn("imports", importer)
        self.assertIn("small", importer["imports"])
        self.assertIn("imported_by", importee)
        self.assertIn("imports_small", importee["imported_by"])


if __name__ == "__main__":
    unittest.main()
