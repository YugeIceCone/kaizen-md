"""Tests for `kaizen-debug check` — parse-validity per axis.

Four axes, all KISS parse-only:
  --python   ast.parse every .py
  --yaml     yaml.safe_load every .yaml
  --jsonl    every non-blank line of a .jsonl is a parseable JSON object
  --schema   every .schema.json is a valid JSON Schema (Draft 2020-12)

Each axis is independent: --python failures don't suppress --yaml findings.
--all is the default. Envelope: {passed, failed, results: [{axis, file,
line?, kind, detail}]}.

BK-018 — catches the kind of bug that silently broke the 2026-05-19
handoff (un-escaped `'` inside a single-quoted YAML scalar)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_KZ = Path(__file__).resolve().parent.parent
_DEBUG_PY = _KZ / "scripts" / "debug.py"


def _run(*args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        [sys.executable, str(_DEBUG_PY), *args],
        capture_output=True, text=True, timeout=60, env=env,
    )


class CheckBase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, rel: str, content: str) -> Path:
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p


# ─── Per-axis breakage ───────────────────────────────────────────────


class TestCheckPython(CheckBase):
    def test_bad_syntax_flagged(self):
        self._write("good.py", "x = 1\n")
        self._write("bad.py", "def broken(:\n    pass\n")
        r = _run("check", "--python", "--path", str(self.tmp), "--json")
        env = json.loads(r.stdout)
        kinds = {(f["axis"], f["kind"]) for f in env["results"]}
        self.assertIn(("python", "syntax-error"), kinds)
        flagged_files = {f["file"] for f in env["results"]}
        self.assertTrue(any("bad.py" in f for f in flagged_files))
        self.assertNotEqual(r.returncode, 0,
                            "non-zero exit when findings present")

    def test_clean_python_returns_zero(self):
        self._write("a.py", "x = 1\n")
        self._write("b.py", "y = 2\n")
        r = _run("check", "--python", "--path", str(self.tmp), "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["failed"], 0, env)
        self.assertEqual(r.returncode, 0)


class TestCheckYaml(CheckBase):
    def test_unescaped_apostrophe_flagged(self):
        """The exact pattern that silently broke the 2026-05-19 handoff."""
        self._write("clean.yaml", "key: value\n")
        self._write(
            "broken.yaml",
            "failed:\n"
            "  - 'Slash bodies need `!`bash -c 'exec ${BIN}'`` not "
            "`!`bash ${BIN}``.'\n",
        )
        r = _run("check", "--yaml", "--path", str(self.tmp), "--json")
        env = json.loads(r.stdout)
        flagged = [f for f in env["results"] if f["axis"] == "yaml"]
        self.assertTrue(flagged, "expected yaml parse-error finding")
        self.assertTrue(any("broken.yaml" in f["file"] for f in flagged))
        self.assertNotEqual(r.returncode, 0)


class TestCheckJsonl(CheckBase):
    def test_malformed_line_flagged(self):
        self._write("good.jsonl", '{"k": 1}\n{"k": 2}\n')
        # Line 2 is not a complete JSON object
        self._write("bad.jsonl", '{"k": 1}\n{not json}\n{"k": 3}\n')
        r = _run("check", "--jsonl", "--path", str(self.tmp), "--json")
        env = json.loads(r.stdout)
        flagged = [f for f in env["results"] if f["axis"] == "jsonl"]
        self.assertTrue(flagged)
        # Finding carries the bad line number
        bad_finding = next(f for f in flagged if "bad.jsonl" in f["file"])
        self.assertEqual(bad_finding.get("line"), 2)
        self.assertNotEqual(r.returncode, 0)

    def test_blank_lines_ok(self):
        self._write("with_blanks.jsonl", '{"k": 1}\n\n{"k": 2}\n')
        r = _run("check", "--jsonl", "--path", str(self.tmp), "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["failed"], 0, env)


class TestCheckSchema(CheckBase):
    def test_invalid_jsonschema_flagged(self):
        # `type` must be a string or array of strings; integer is invalid.
        self._write("bad.schema.json",
                    '{"$schema":"https://json-schema.org/draft/2020-12/schema",'
                    '"type": 42}')
        self._write("good.schema.json",
                    '{"$schema":"https://json-schema.org/draft/2020-12/schema",'
                    '"type": "object"}')
        r = _run("check", "--schema", "--path", str(self.tmp), "--json")
        env = json.loads(r.stdout)
        flagged = [f for f in env["results"] if f["axis"] == "schema"]
        self.assertTrue(flagged, env)
        self.assertTrue(any("bad.schema.json" in f["file"] for f in flagged))
        self.assertNotEqual(r.returncode, 0)

    def test_malformed_json_flagged(self):
        self._write("garbage.schema.json", "{not json}")
        r = _run("check", "--schema", "--path", str(self.tmp), "--json")
        env = json.loads(r.stdout)
        flagged = [f for f in env["results"] if f["axis"] == "schema"]
        self.assertTrue(flagged)


# ─── Cross-axis behavior ─────────────────────────────────────────────


class TestCheckAll(CheckBase):
    def test_all_axes_run_when_no_axis_flag(self):
        """Default (no flags) runs all 4 axes; each independent."""
        self._write("bad.py", "def broken(:\n")
        self._write("bad.yaml", "  - 'x 'y' z'\n")
        self._write("bad.jsonl", "{not json}\n")
        self._write("bad.schema.json", "{not json}")
        r = _run("check", "--path", str(self.tmp), "--json")
        env = json.loads(r.stdout)
        axes_with_findings = {f["axis"] for f in env["results"]}
        self.assertEqual(
            axes_with_findings,
            {"python", "yaml", "jsonl", "schema"},
            f"expected all 4 axes to find their breakage; got {axes_with_findings}",
        )

    def test_clean_tree_returns_zero(self):
        self._write("a.py", "x = 1\n")
        self._write("a.yaml", "k: v\n")
        self._write("a.jsonl", '{"k": 1}\n')
        self._write("a.schema.json",
                    '{"$schema":"https://json-schema.org/draft/2020-12/schema",'
                    '"type": "object"}')
        r = _run("check", "--path", str(self.tmp), "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["failed"], 0, env)
        self.assertEqual(r.returncode, 0)


class TestCheckSkipsPycache(CheckBase):
    def test_pycache_dir_skipped(self):
        """__pycache__ dirs should never be scanned."""
        self._write("__pycache__/a.cpython-313.pyc", "garbage")
        self._write("good.py", "x = 1\n")
        r = _run("check", "--python", "--path", str(self.tmp), "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["failed"], 0, env)


class TestCheckHelp(unittest.TestCase):
    def test_help_works(self):
        r = _run("check", "--help")
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
