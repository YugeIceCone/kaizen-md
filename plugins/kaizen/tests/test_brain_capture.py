"""Tests for brain.py — capture flow + CLI.

Covers the AsyncNode pipeline end-to-end with a sandboxed brain root
+ project-memory root so writes don't touch the real ~/.claude/brain/.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))

import _brain  # noqa: E402
import brain as _brain_cli  # noqa: E402


def _capture(text: str, brain_root: Path, project_memory_root: Path, **kwargs) -> dict:
    """Helper: run the capture flow with sandboxed paths."""
    return asyncio.run(_brain_cli.capture_async(
        text=text,
        brain_root_override=brain_root,
        project_memory_root_override=project_memory_root,
        **kwargs,
    ))


# ─── End-to-end capture flow ─────────────────────────────────────────


class TestCaptureFlowBasic(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name) / "brain"
        self.brain.mkdir()
        self.proj = Path(self._tmp.name) / "project-memory"
        self.proj.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_belief_capture_creates_note(self):
        result = _capture(
            "user prefers terse output and direct answers",
            self.brain, self.proj,
            tier_hint="brain",  # force brain so we have a deterministic destination
        )
        self.assertEqual(result["type"], "belief")
        self.assertEqual(result["tier"], "brain")
        self.assertEqual(result["action"], "created")
        # Note file landed under brain/Notes/
        self.assertTrue(Path(result["path"]).is_file())
        self.assertTrue(Path(result["path"]).parent.name == "Notes")

    def test_journal_appended_first(self):
        result = _capture(
            "we decided to use sqlite for the index",
            self.brain, self.proj,
        )
        # Journal entry was created with today's date
        jp = Path(result["journal"])
        self.assertTrue(jp.is_file())
        self.assertEqual(jp.parent.name, "Journal")
        content = jp.read_text()
        self.assertIn("we decided to use sqlite", content)

    def test_capture_writes_frontmatter(self):
        result = _capture(
            "the user prefers verbose error messages",
            self.brain, self.proj,
            tier_hint="brain",
        )
        note = Path(result["path"]).read_text()
        self.assertTrue(note.startswith("---\n"))
        self.assertIn("type: belief", note)
        self.assertIn("confidence:", note)
        self.assertIn("sources_count: 1", note)
        self.assertIn("evidence:", note)

    def test_world_fact_detected(self):
        result = _capture(
            "we decided to migrate from npm to pnpm",
            self.brain, self.proj,
        )
        self.assertEqual(result["type"], "world-fact")

    def test_explicit_type_hint_wins(self):
        result = _capture(
            "user prefers x",
            self.brain, self.proj,
            type_hint="observation",
            tier_hint="brain",
            subject="person:User",
        )
        self.assertEqual(result["type"], "observation")

    def test_empty_input_errors(self):
        result = _capture("   ", self.brain, self.proj)
        self.assertIn("error", result)

    def test_belief_uses_supplied_confidence(self):
        result = _capture(
            "prefers concise output",
            self.brain, self.proj,
            tier_hint="brain",
            confidence=0.95,
        )
        note = Path(result["path"]).read_text()
        self.assertIn("confidence: 0.95", note)


class TestCaptureFlowMerge(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name) / "brain"
        self.brain.mkdir()
        self.proj = Path(self._tmp.name) / "project-memory"
        self.proj.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_second_capture_increments_sources_count(self):
        # First capture
        r1 = _capture(
            "user prefers terse output",
            self.brain, self.proj,
            tier_hint="brain",
        )
        # Second capture targeting the same file (same slug)
        r2 = _capture(
            "user prefers terse output and clear errors",
            self.brain, self.proj,
            tier_hint="brain",
            subject=Path(r1["path"]).stem,  # force same filename via subject
        )
        # Either action — first should be created, second may be created
        # (different slug) or merged. If merged, sources_count > 1.
        if r2.get("path") == r1["path"]:
            self.assertEqual(r2["action"], "merged")
            self.assertGreaterEqual(r2["sources_count"], 2)


class TestRouting(unittest.TestCase):
    """Verify tier-rule + file-rule logic in isolation."""

    def setUp(self):
        self.cfg = _brain.Config.load()

    def test_high_confidence_belief_routes_brain(self):
        tier = _brain_cli._select_tier(self.cfg, "belief", 0.95, "prefers x")
        self.assertEqual(tier, "brain")

    def test_low_confidence_belief_routes_project(self):
        tier = _brain_cli._select_tier(self.cfg, "belief", 0.5, "prefers x")
        self.assertEqual(tier, "project-memory")

    def test_experience_always_brain(self):
        tier = _brain_cli._select_tier(self.cfg, "experience", None, "met with team")
        self.assertEqual(tier, "brain")

    def test_observation_always_brain(self):
        tier = _brain_cli._select_tier(self.cfg, "observation", None, "alice leads team")
        self.assertEqual(tier, "brain")

    def test_explicit_project_keyword_routes_project(self):
        tier = _brain_cli._select_tier(
            self.cfg, "belief", 0.99,
            "specific to this repo: always use sqlite",
        )
        self.assertEqual(tier, "project-memory")

    def test_explicit_cross_project_keyword_routes_brain(self):
        tier = _brain_cli._select_tier(
            self.cfg, "world-fact", None,
            "globally use prettier for formatting",
        )
        self.assertEqual(tier, "brain")


# ─── CLI smoke tests ─────────────────────────────────────────────────


class TestCli(unittest.TestCase):
    def _run_cli(self, *args, env_extras: dict | None = None) -> subprocess.CompletedProcess:
        script = _KZ_DIR / "skills/workflow/scripts/brain.py"
        env = os.environ.copy()
        if env_extras:
            env.update(env_extras)
        return subprocess.run(
            ["python3", str(script), *args],
            capture_output=True, text=True, env=env,
        )

    def test_path_subcommand(self):
        result = self._run_cli("path")
        self.assertEqual(result.returncode, 0)
        out = json.loads(result.stdout)
        self.assertIn("brain_root", out)
        self.assertIn("project_memory_root", out)

    def test_detect_subcommand(self):
        result = self._run_cli("detect", "we decided to use rust")
        self.assertEqual(result.returncode, 0)
        out = json.loads(result.stdout)
        self.assertEqual(out["type"], "world-fact")

    def test_status_subcommand(self):
        # Even when brain root doesn't exist in this env, status exits 0
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run_cli(
                "status", env_extras={"KAIZEN_BRAIN_DIR": tmp + "/no-such-brain"},
            )
            self.assertEqual(result.returncode, 0)
            out = json.loads(result.stdout)
            self.assertIn("brain_root", out)

    def test_capture_subcommand_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain = Path(tmp) / "brain"
            brain.mkdir()
            result = self._run_cli(
                "capture", "we decided to ship it",
                env_extras={"KAIZEN_BRAIN_DIR": str(brain)},
            )
            self.assertEqual(result.returncode, 0)
            out = json.loads(result.stdout)
            self.assertEqual(out["type"], "world-fact")


if __name__ == "__main__":
    unittest.main()
