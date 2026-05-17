"""Tests for session-inject-context.sh — the ported SessionStart
context injector.

The hook emits a JSON payload conforming to Claude Code's
``hookSpecificOutput.additionalContext`` schema. These tests verify:

  - JSON structure (parseable, correct event name)
  - Collectors fire when their inputs exist (workflow state, plans,
    git, CLAUDE.md, handoff)
  - Collectors silently skip when their inputs are absent
  - Bypass knob (KAIZEN_INJECT_CONTEXT_DISABLE=1) returns empty {}
  - Workflow path discovery prefers .kaizen/workflow over .workflow
    (the v1.22.0 modernization)

All tests sandbox via tempdir + CLAUDE_PROJECT_DIR env override —
never touches the real cwd or ~/.claude/.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_HOOK = _KZ_DIR / "hooks" / "claude" / "session-inject-context.sh"


def _run_hook(event: str, project_dir: Path, *,
              source: str = "",
              extra_env: dict | None = None) -> subprocess.CompletedProcess:
    """Invoke the hook with CLAUDE_PROJECT_DIR pointed at the tmpdir
    and stdin containing the source-field JSON."""
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)}
    if extra_env:
        env.update(extra_env)
    payload = json.dumps({"source": source})
    return subprocess.run(
        ["bash", str(_HOOK), event],
        input=payload, capture_output=True, text=True,
        env=env, timeout=15,
    )


def _parse(r: subprocess.CompletedProcess) -> dict:
    """Parse the hook's stdout as JSON, with helpful failure msg."""
    s = r.stdout.strip()
    if not s:
        raise AssertionError(f"empty stdout (stderr: {r.stderr[:200]})")
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        raise AssertionError(f"unparseable stdout: {e}\n{s[:400]}")


class _BaseHook(unittest.TestCase):
    """Per-test tempdir as the fake project root."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class StructuralContract(_BaseHook):
    """Output is always valid JSON conforming to CC's hook schema."""

    def test_emits_valid_json(self):
        r = _run_hook("session", self.root)
        self.assertEqual(r.returncode, 0)
        # Empty project → may emit {} (no content) or full envelope
        out = _parse(r)
        self.assertIsInstance(out, dict)

    def test_session_event_name(self):
        # Force some content so the full envelope is built
        (self.root / "CLAUDE.md").write_text("test\n")
        out = _parse(_run_hook("session", self.root))
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"],
                         "SessionStart")

    def test_prompt_event_name(self):
        (self.root / "CLAUDE.md").write_text("test\n")
        out = _parse(_run_hook("prompt", self.root))
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"],
                         "UserPromptSubmit")

    def test_unknown_event_defaults_to_session(self):
        (self.root / "CLAUDE.md").write_text("test\n")
        out = _parse(_run_hook("garbage-event", self.root))
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"],
                         "SessionStart")


class BypassKnob(_BaseHook):
    """KAIZEN_INJECT_CONTEXT_DISABLE=1 → empty {} regardless of inputs.
    Iron-law: every hook must have a per-feature bypass."""

    def test_bypass_returns_empty(self):
        (self.root / "CLAUDE.md").write_text("test\n")
        r = _run_hook("session", self.root,
                      extra_env={"KAIZEN_INJECT_CONTEXT_DISABLE": "1"})
        self.assertEqual(r.stdout.strip(), "{}")


class Collectors(_BaseHook):
    """Each collector fires when its input exists, skips when absent."""

    def test_claude_md_collector(self):
        (self.root / "CLAUDE.md").write_text("test\n")
        out = _parse(_run_hook("session", self.root))
        body = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Project memory files", body)
        self.assertIn("CLAUDE.md", body)

    def test_no_claude_md_means_no_section(self):
        # Truly empty project — no content
        r = _run_hook("session", self.root)
        # Either {} or envelope with no "Project memory files" section
        if r.stdout.strip() == "{}":
            return  # empty body — pass
        out = _parse(r)
        body = out["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("Project memory files", body)

    def test_plans_collector(self):
        (self.root / "plans").mkdir()
        (self.root / "plans" / "test-plan.md").write_text(
            "# Test plan\n\n## Status\n- Status: in-progress\n"
        )
        out = _parse(_run_hook("session", self.root))
        body = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Plans in this project", body)
        self.assertIn("test-plan.md", body)

    def test_workflow_state_prefers_kaizen_workflow_over_workflow(self):
        """Modernization vs the original: .kaizen/workflow/ wins over
        .workflow/ when both exist."""
        new_path = self.root / ".kaizen" / "workflow"
        old_path = self.root / ".workflow"
        new_path.mkdir(parents=True)
        old_path.mkdir()
        new_state = {"routine": "from-new", "stages": [], "current": 0,
                     "completed": [], "artifacts": {}}
        old_state = {"routine": "from-old", "stages": [], "current": 0,
                     "completed": [], "artifacts": {}}
        (new_path / "state.json").write_text(json.dumps(new_state))
        (old_path / "state.json").write_text(json.dumps(old_state))
        out = _parse(_run_hook("session", self.root))
        body = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("from-new", body)
        self.assertNotIn("from-old", body)

    def test_workflow_state_legacy_fallback(self):
        """When only legacy .workflow/ exists, still collected."""
        old_path = self.root / ".workflow"
        old_path.mkdir()
        (old_path / "state.json").write_text(json.dumps(
            {"routine": "legacy-only", "stages": [], "current": 0,
             "completed": [], "artifacts": {}}))
        out = _parse(_run_hook("session", self.root))
        body = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("legacy-only", body)


class HandoffCollector(_BaseHook):
    """Handoff collector prefers `kaizen-handoff latest --json` (the
    in-plugin store) over filesystem lookup. Falls back to the legacy
    filesystem locations when no store is available."""

    def test_legacy_handoff_md_in_project_root(self):
        # No kaizen-handoff on PATH for this test — use a clean PATH
        # missing the binary
        (self.root / ".handoff.md").write_text("session work\n")
        r = _run_hook("session", self.root,
                      extra_env={"PATH": "/usr/bin:/bin"})
        out = _parse(r)
        body = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Handoff document", body)
        self.assertIn(".handoff.md", body)


if __name__ == "__main__":
    unittest.main()
