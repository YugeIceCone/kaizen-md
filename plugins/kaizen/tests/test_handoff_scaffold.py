"""Tests for handoff.py::scaffold — git-driven YAML pre-fill.

The scaffold subcommand cuts ~20–50% of the Step-2 token cost by
prefilling the mechanically-derivable fields (date, files.created,
files.modified, done_this_session.files) from git state. The agent
only has to write the qualitative content (goal, now, decisions,
findings, worked, failed, next).
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
_SCRIPTS = _KZ_DIR / "skills/workflow/scripts"
_HANDOFF_PY = _SCRIPTS / "handoff.py"
_DOMAIN = _KZ_DIR / "skills/handoff/domain"


class ScaffoldBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.handoffs_dir = self.tmp / "handoffs"
        self.handoffs_dir.mkdir()
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        for cmd in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "t@t"],
            ["git", "config", "user.name", "t"],
        ):
            subprocess.run(cmd, cwd=str(self.repo), check=True, capture_output=True)

        self._orig_dir = os.environ.get("KAIZEN_HANDOFF_DIR")
        self._orig_db = os.environ.get("KAIZEN_HANDOFF_DB")
        os.environ["KAIZEN_HANDOFF_DIR"] = str(self.handoffs_dir)
        os.environ["KAIZEN_HANDOFF_DB"] = str(self.tmp / "handoff.db")

    def tearDown(self):
        self._tmp.cleanup()
        for var, orig in (("KAIZEN_HANDOFF_DIR", self._orig_dir),
                          ("KAIZEN_HANDOFF_DB", self._orig_db)):
            if orig is None: os.environ.pop(var, None)
            else: os.environ[var] = orig

    def _commit(self, rel: str, content: str) -> None:
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", rel], cwd=str(self.repo), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", f"add {rel}"],
                        cwd=str(self.repo), check=True, capture_output=True)

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_HANDOFF_PY), "scaffold", *args],
            capture_output=True, text=True, timeout=30,
            cwd=str(self.repo),
            env=os.environ.copy(),
        )


class TestScaffoldHappy(ScaffoldBase):
    def test_writes_yaml_to_session_dir(self):
        self._commit("src/lib.py", "x\n")
        r = self._run(
            "--session", "demo",
            "--goal", "did the thing",
            "--now", "do the next thing",
            "--at", "2026-05-17_03-00",
            "--json",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        env = json.loads(r.stdout)
        yaml_path = Path(env["data"]["yaml_path"])
        self.assertTrue(yaml_path.is_file(), f"yaml not at {yaml_path}")
        self.assertEqual(yaml_path.parent.name, "demo")
        body = yaml_path.read_text(encoding="utf-8")
        self.assertIn("session: demo", body)
        self.assertIn("goal: did the thing", body)
        self.assertIn("now: do the next thing", body)
        self.assertIn("status: partial", body)
        self.assertIn("outcome: IN_PROGRESS", body)


class TestScaffoldSlugDerivation(ScaffoldBase):
    def test_slug_derived_from_goal_when_omitted(self):
        self._commit("a", "1")
        r = self._run("--session", "s", "--goal", "Refactor the WidgetFoo!",
                       "--now", "ship it", "--at", "2026-05-17_03-00", "--json")
        env = json.loads(r.stdout)
        yaml_path = Path(env["data"]["yaml_path"])
        # Kebab, lowercase, alnum+hyphen, no leading/trailing hyphen
        name = yaml_path.name
        # Expect "2026-05-17_03-00_refactor-the-widgetfoo.yaml" shape
        self.assertTrue(name.endswith(".yaml"))
        self.assertIn("_refactor-the-widgetfoo", name)

    def test_explicit_slug_overrides_derivation(self):
        self._commit("a", "1")
        r = self._run("--session", "s", "--goal", "ignored",
                       "--now", "x", "--description-slug", "my-explicit-slug",
                       "--at", "2026-05-17_03-00", "--json")
        env = json.loads(r.stdout)
        self.assertIn("my-explicit-slug.yaml", env["data"]["yaml_path"])


class TestScaffoldGitPrefill(ScaffoldBase):
    def test_modified_files_picked_up(self):
        self._commit("src/a.py", "1\n")
        self._commit("src/b.py", "1\n")
        r = self._run(
            "--session", "s", "--goal", "g", "--now", "n",
            "--since", "2000-01-01",  # wide net to include everything
            "--at", "2026-05-17_03-00", "--json",
        )
        env = json.loads(r.stdout)
        self.assertGreaterEqual(env["data"]["stats"]["files_changed"], 2)
        body = Path(env["data"]["yaml_path"]).read_text(encoding="utf-8")
        # files.modified or done_this_session.files should mention the paths
        self.assertTrue("src/a.py" in body and "src/b.py" in body,
                         f"git-touched files missing from YAML:\n{body}")

    def test_commits_since_count_in_stats(self):
        self._commit("a", "1")
        self._commit("b", "1")
        r = self._run("--session", "s", "--goal", "g", "--now", "n",
                       "--since", "2000-01-01",
                       "--at", "2026-05-17_03-00", "--json")
        env = json.loads(r.stdout)
        self.assertGreaterEqual(env["data"]["stats"]["commits_since"], 2)


class TestScaffoldEnvelopeShape(ScaffoldBase):
    def test_envelope_has_required_keys(self):
        self._commit("a", "1")
        r = self._run("--session", "s", "--goal", "g", "--now", "n",
                       "--at", "2026-05-17_03-00", "--json")
        env = json.loads(r.stdout)
        for key in ("yaml_path", "prefilled_sections", "agent_must_fill", "stats"):
            self.assertIn(key, env["data"], f"missing {key}")
        self.assertIn("date", env["data"]["prefilled_sections"])
        # The qualitative fields must surface as agent-must-fill
        for must in ("decisions", "findings", "worked", "failed", "next"):
            self.assertIn(must, env["data"]["agent_must_fill"])

    def test_envelope_validates_against_schema(self):
        import sys as _sys
        _sys.path.insert(0, str(_SCRIPTS))
        import schema_cli
        self._commit("a", "1")
        r = self._run("--session", "s", "--goal", "g", "--now", "n",
                       "--at", "2026-05-17_03-00", "--json")
        env = json.loads(r.stdout)
        m = schema_cli.Manifest.load(_DOMAIN / "handoff.yaml")
        m.get("scaffold").validate_output(env["data"])  # no raise


class TestScaffoldHelp(unittest.TestCase):
    def test_help_works(self):
        r = subprocess.run(
            [sys.executable, str(_HANDOFF_PY), "scaffold", "--help"],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
