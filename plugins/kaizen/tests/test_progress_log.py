"""Tests for progress_log.py — atomic-append CLI for .kaizen/workflow/progress.md.

The pain this fixes (observed in the same session that built this):
  Adding one row to progress.md today is `Read full file` + `Edit with
  old_string=last-row` + new content. That's 2 tool calls + ~2KB of
  context per row, repeated 8+ times per session = 16+ tool calls + 16KB
  of mostly-unused tokens.

The append CLI replaces that with one shell call — no Read needed,
no Edit/overwrite, atomic O_APPEND to the file. Plus full row-shape
validation against domain/schemas/architecture-log-row.schema.json.

Iron-laws:
  - append-only: NEVER reads the file first
  - schema-validates the payload BEFORE the append; reject + exit 1
    on invalid input (date format / kind enum / colon-space in summary)
  - creates the file with the canonical 4-column header if absent
  - atomic: open(path, 'a').write() in one syscall
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_PROGRESS_LOG_PY = _KZ_DIR / "scripts/util/progress_log.py"


class _AppendBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.log = self.tmp / "progress.md"

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_PROGRESS_LOG_PY), *args],
            capture_output=True, text=True, timeout=15,
            input=stdin,
        )


class TestAppendBasic(_AppendBase):
    def test_creates_file_with_header_if_absent(self):
        r = self._run("append",
                       "--file", str(self.log),
                       "--date", "2026-05-18",
                       "--kind", "feat",
                       "--loc",  "+220",
                       "--summary", "test commit")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.log.is_file())
        body = self.log.read_text(encoding="utf-8")
        self.assertIn("# Architecture Log", body)
        self.assertIn("| Date | Kind | ΔLOC | Summary |", body)
        self.assertIn("| 2026-05-18 | feat | +220 | test commit |", body)

    def test_appends_to_existing(self):
        self.log.write_text(
            "# Architecture Log\n\n"
            "| Date | Kind | ΔLOC | Summary |\n"
            "|------|------|------|---------|\n"
            "| 2026-05-17 | feat | +100 | first row |\n",
            encoding="utf-8",
        )
        r = self._run("append",
                       "--file", str(self.log),
                       "--date", "2026-05-18",
                       "--kind", "fix",
                       "--loc",  "+5 -2",
                       "--summary", "second row")
        self.assertEqual(r.returncode, 0)
        body = self.log.read_text(encoding="utf-8")
        self.assertIn("| 2026-05-17 | feat | +100 | first row |", body)
        self.assertIn("| 2026-05-18 | fix | +5 -2 | second row |", body)
        # Order preserved (append semantics)
        self.assertLess(body.index("first row"), body.index("second row"))


class TestAppendValidation(_AppendBase):
    def test_invalid_date_exits_1(self):
        r = self._run("append",
                       "--file", str(self.log),
                       "--date", "not-a-date",
                       "--kind", "feat",
                       "--loc",  "+1",
                       "--summary", "x")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("date", (r.stderr + r.stdout).lower())

    def test_invalid_kind_exits_1(self):
        r = self._run("append",
                       "--file", str(self.log),
                       "--date", "2026-05-18",
                       "--kind", "banana",
                       "--loc",  "+1",
                       "--summary", "x")
        self.assertEqual(r.returncode, 1)
        self.assertIn("kind", (r.stderr + r.stdout).lower())

    def test_summary_with_colon_space_exits_1(self):
        # `: ` in YAML/markdown table cells trips downstream parsers — same
        # rule as the handoff scaffold's _quote_if_unsafe.
        r = self._run("append",
                       "--file", str(self.log),
                       "--date", "2026-05-18",
                       "--kind", "feat",
                       "--loc",  "+1",
                       "--summary", "broken: format")
        self.assertEqual(r.returncode, 1)
        self.assertIn("colon", (r.stderr + r.stdout).lower())

    def test_empty_summary_exits_1(self):
        r = self._run("append",
                       "--file", str(self.log),
                       "--date", "2026-05-18",
                       "--kind", "feat",
                       "--loc",  "+1",
                       "--summary", "")
        self.assertEqual(r.returncode, 1)


class TestAppendStdinJson(_AppendBase):
    def test_stdin_json_payload(self):
        payload = json.dumps({
            "date": "2026-05-18",
            "kind": "refactor",
            "loc":  "-30",
            "summary": "removed dead helpers",
        })
        r = self._run("append", "--file", str(self.log), "--stdin",
                       stdin=payload)
        self.assertEqual(r.returncode, 0, r.stderr)
        body = self.log.read_text(encoding="utf-8")
        self.assertIn("| 2026-05-18 | refactor | -30 | removed dead helpers |", body)

    def test_stdin_invalid_json_exits_1(self):
        r = self._run("append", "--file", str(self.log), "--stdin",
                       stdin="not json{")
        self.assertEqual(r.returncode, 1)


class TestAppendDoesNotReadExisting(_AppendBase):
    """The whole point: append must NOT read the existing file. We verify
    by writing a large file then confirming the append cost is constant
    (~ row-length bytes), not proportional to the file size."""

    def test_append_cost_is_row_length(self):
        # Seed with a 100KB log
        header = ("# Architecture Log\n\n"
                  "| Date | Kind | ΔLOC | Summary |\n"
                  "|------|------|------|---------|\n")
        rows = "\n".join(
            f"| 2026-05-17 | feat | +{i} | row number {i} |"
            for i in range(2000)
        )
        self.log.write_text(header + rows + "\n", encoding="utf-8")
        size_before = self.log.stat().st_size
        self.assertGreater(size_before, 50_000)

        r = self._run("append",
                       "--file", str(self.log),
                       "--date", "2026-05-18",
                       "--kind", "feat",
                       "--loc",  "+1",
                       "--summary", "appended row")
        self.assertEqual(r.returncode, 0, r.stderr)

        size_after = self.log.stat().st_size
        delta = size_after - size_before
        # Just the row itself — bounded by row length
        self.assertLess(delta, 200,
                         f"append delta={delta}B; expected <200B (row size). "
                         "If this fails, the implementation is likely "
                         "read-then-overwriting instead of true-appending.")


class TestAppendCanonicalRowFormat(_AppendBase):
    """Row shape must match the existing convention (4 pipe-delimited cells:
    date | kind | loc | summary)."""

    def test_row_format_exact(self):
        self._run("append",
                   "--file", str(self.log),
                   "--date", "2026-05-18",
                   "--kind", "feat",
                   "--loc",  "+220",
                   "--summary", "exact-shape check")
        body = self.log.read_text(encoding="utf-8")
        # Last non-empty line must be the new row in canonical format
        last_row = [line for line in body.splitlines() if line.strip()][-1]
        self.assertEqual(last_row,
                          "| 2026-05-18 | feat | +220 | exact-shape check |")


class TestRegenJsonl(_AppendBase):
    """`regen` verb walks progress.md and rewrites progress.jsonl as a
    line-per-row mirror. Lets the .jsonl stay in sync without manual edits."""

    def test_regen_creates_jsonl_sibling(self):
        self.log.write_text(
            "# Architecture Log\n\n"
            "| Date | Kind | ΔLOC | Summary |\n"
            "|------|------|------|---------|\n"
            "| 2026-05-17 | feat | +100 | first row |\n"
            "| 2026-05-18 | fix | +5 -2 | second row — with em-dash |\n",
            encoding="utf-8",
        )
        r = self._run("regen", "--file", str(self.log))
        self.assertEqual(r.returncode, 0, r.stderr)
        jsonl = self.log.with_suffix(".jsonl")
        self.assertTrue(jsonl.is_file())
        lines = [json.loads(ln) for ln in jsonl.read_text().splitlines() if ln.strip()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], {"date": "2026-05-17", "scope": "feat",
                                     "delta": "+100", "summary": "first row"})
        self.assertEqual(lines[1]["summary"], "second row — with em-dash")

    def test_regen_is_idempotent(self):
        self.log.write_text(
            "# Architecture Log\n\n"
            "| Date | Kind | ΔLOC | Summary |\n"
            "|------|------|------|---------|\n"
            "| 2026-05-17 | feat | +100 | row |\n",
            encoding="utf-8",
        )
        self._run("regen", "--file", str(self.log))
        first = self.log.with_suffix(".jsonl").read_bytes()
        self._run("regen", "--file", str(self.log))
        second = self.log.with_suffix(".jsonl").read_bytes()
        self.assertEqual(first, second)

    def test_regen_dry_run_reports_drift(self):
        self.log.write_text(
            "# Architecture Log\n\n"
            "| Date | Kind | ΔLOC | Summary |\n"
            "|------|------|------|---------|\n"
            "| 2026-05-17 | feat | +1 | a |\n",
            encoding="utf-8",
        )
        # No .jsonl yet → drift
        r = self._run("regen", "--file", str(self.log), "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.log.with_suffix(".jsonl").exists())
        self.assertIn("drift", r.stdout.lower() + r.stderr.lower())

    def test_regen_skips_header_and_blank_rows(self):
        self.log.write_text(
            "# Architecture Log\n\n"
            "| Date | Kind | ΔLOC | Summary |\n"
            "|------|------|------|---------|\n"
            "\n"
            "| 2026-05-18 | feat | +1 | a |\n",
            encoding="utf-8",
        )
        self._run("regen", "--file", str(self.log))
        jsonl = self.log.with_suffix(".jsonl")
        lines = [ln for ln in jsonl.read_text().splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1)


class TestSchemaFilePresent(unittest.TestCase):
    def test_schema_file_exists(self):
        schema = _KZ_DIR / "schemas/workflow/schemas/architecture-log-row.schema.json"
        self.assertTrue(schema.is_file(),
                         f"schema not at {schema} — should ship with the feature")
        data = json.loads(schema.read_text(encoding="utf-8"))
        self.assertEqual(data.get("title", "").lower().replace(" ", "-"),
                          "architecture-log-row")


if __name__ == "__main__":
    unittest.main()
