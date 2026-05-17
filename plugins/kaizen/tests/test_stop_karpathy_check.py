"""Tests for stop_karpathy_check.py — Stop-hook periodic complexity check."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "skills/workflow/scripts/stop_karpathy_check.py"


class _Sandbox(unittest.TestCase):
    def setUp(self):
        self._cwd0 = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.fake_home = self.tmp / "home"
        self.fake_home.mkdir()
        self.dxm_dir = self.tmp / "dxm"
        self.dxm_dir.mkdir()
        self.cwd = self.tmp / "repo"
        self.cwd.mkdir()
        self._orig = {}
        for k, v in (("HOME", str(self.fake_home)),
                      ("KAIZEN_DXM_DIR", str(self.dxm_dir))):
            self._orig[k] = os.environ.get(k)
            os.environ[k] = v
        os.chdir(self.cwd)

    def tearDown(self):
        try: os.chdir(self._cwd0)
        except OSError: pass
        self._tmp.cleanup()
        for k, v in self._orig.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v

    def _seed_jsonl(self, sid: str, files: list[str]):
        """Seed CC JSONL with assistant turns recording Edit tool_use on each file."""
        slug = str(self.cwd.resolve()).replace("/", "-")
        proj = self.fake_home / ".claude" / "projects" / slug
        proj.mkdir(parents=True, exist_ok=True)
        records = []
        for i, fp in enumerate(files):
            records.append({
                "type": "assistant",
                "timestamp": "2026-05-17T08:00:00Z",
                "message": {"content": [{
                    "type": "tool_use",
                    "id": f"tu_{i}",
                    "name": "Edit",
                    "input": {"file_path": fp, "old_string": "x", "new_string": "y"},
                }]},
            })
        (proj / f"{sid}.jsonl").write_text(
            "\n".join(json.dumps(r) for r in records) + "\n")

    def _make_py(self, name: str, complex: bool = False):
        p = self.cwd / name
        if complex:
            # Deeply nested function → triggers complexity_checker WARN
            body = "def f():\n" + "    if True:\n" * 10 + " " * 40 + "pass\n"
        else:
            body = "def f(): pass\n"
        p.write_text(body)
        return str(p)

    def _run(self, sid: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_SCRIPT), "check", "--session", sid],
            capture_output=True, text=True, timeout=15,
            env=os.environ.copy(),
        )

    def _events(self, sid: str) -> list[dict]:
        f = self.dxm_dir / f"events-{sid}.jsonl"
        if not f.is_file(): return []
        return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]


class TestNoModifiedFilesNoOp(_Sandbox):
    def test_empty_session_returns_empty(self):
        # No JSONL at all
        r = self._run("sid-empty")
        self.assertEqual(r.stdout.strip(), "{}")


class TestNoComplexityIssuesNoOp(_Sandbox):
    def test_simple_files_no_emit(self):
        clean = self._make_py("clean.py", complex=False)
        self._seed_jsonl("sid-clean", [clean])
        r = self._run("sid-clean")
        # No WARN → no emit
        self.assertEqual(r.stdout.strip(), "{}")


class TestComplexityWarnEmits(_Sandbox):
    def test_complex_file_triggers_systemMessage(self):
        clean = self._make_py("clean.py", complex=False)
        ugly = self._make_py("ugly.py", complex=True)
        self._seed_jsonl("sid-mix", [clean, ugly])
        r = self._run("sid-mix")
        out = json.loads(r.stdout)
        self.assertIn("systemMessage", out)
        self.assertIn("kaizen-karpathy", out["systemMessage"])
        # Mentions the modified ugly file
        self.assertIn("ugly.py", out["systemMessage"])


class TestDedupeOnlyFiresOnce(_Sandbox):
    def test_second_call_returns_empty(self):
        ugly = self._make_py("ugly.py", complex=True)
        self._seed_jsonl("sid-dedupe", [ugly])
        r1 = self._run("sid-dedupe")
        self.assertIn("systemMessage", json.loads(r1.stdout))
        r2 = self._run("sid-dedupe")
        self.assertEqual(r2.stdout.strip(), "{}")


class TestBypassEnv(_Sandbox):
    def test_disable_env_no_op(self):
        ugly = self._make_py("ugly.py", complex=True)
        self._seed_jsonl("sid-byp", [ugly])
        env = os.environ.copy()
        env["KAIZEN_KARPATHY_STOP_DISABLE"] = "1"
        r = subprocess.run(
            [sys.executable, str(_SCRIPT), "check", "--session", "sid-byp"],
            capture_output=True, text=True, timeout=10, env=env,
        )
        self.assertEqual(r.stdout.strip(), "{}")


class TestNonCodeFilesFiltered(_Sandbox):
    def test_md_files_skipped(self):
        # Only .md modified → no candidate files → no emit
        md = str(self.cwd / "README.md")
        Path(md).write_text("# hi\n")
        self._seed_jsonl("sid-md", [md])
        r = self._run("sid-md")
        self.assertEqual(r.stdout.strip(), "{}")


if __name__ == "__main__":
    unittest.main()
