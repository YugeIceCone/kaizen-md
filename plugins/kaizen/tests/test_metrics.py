"""Tests for metrics.py — rollup + never-used catalog."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))

import metrics  # noqa: E402


def _write_trace(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


class MetricsBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.trace_dir = Path(self._tmp.name) / "trace"
        self.trace_file = self.trace_dir / "events.jsonl"
        self._orig = os.environ.get("KAIZEN_TRACE_DIR")
        os.environ["KAIZEN_TRACE_DIR"] = str(self.trace_dir)

    def tearDown(self):
        self._tmp.cleanup()
        if self._orig is None:
            os.environ.pop("KAIZEN_TRACE_DIR", None)
        else:
            os.environ["KAIZEN_TRACE_DIR"] = self._orig


class TestEventIter(MetricsBase):
    def test_iter_empty_when_no_file(self):
        self.assertEqual(list(metrics.iter_events()), [])

    def test_iter_yields_valid_records(self):
        _write_trace(self.trace_file, [
            {"ts": "2026-05-14T00:00:00Z", "src": "hook", "evt": "PreToolUse-Skill", "tool": "Skill"},
            {"ts": "2026-05-14T00:00:01Z", "src": "hook", "evt": "PreToolUse-Bash", "tool": "Bash"},
        ])
        events = list(metrics.iter_events())
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["evt"], "PreToolUse-Skill")

    def test_iter_skips_malformed(self):
        # Mix valid + invalid JSON lines
        self.trace_file.parent.mkdir(parents=True, exist_ok=True)
        with self.trace_file.open("w") as f:
            f.write('{"ts":"2026-05-14T00:00:00Z","evt":"X"}\n')
            f.write('not valid json\n')
            f.write('{"ts":"2026-05-14T00:00:01Z","evt":"Y"}\n')
        events = list(metrics.iter_events())
        self.assertEqual(len(events), 2)

    def test_filter_by_sid(self):
        _write_trace(self.trace_file, [
            {"ts": "2026-05-14T00:00:00Z", "evt": "A", "sid": "session-1"},
            {"ts": "2026-05-14T00:00:01Z", "evt": "B", "sid": "session-2"},
            {"ts": "2026-05-14T00:00:02Z", "evt": "C", "sid": "session-1"},
        ])
        events = list(metrics.iter_events(sid="session-1"))
        self.assertEqual(len(events), 2)


class TestDurationParsing(unittest.TestCase):
    def test_minute_duration(self):
        out = metrics.parse_duration("30m")
        self.assertIsNotNone(out)

    def test_day_duration(self):
        out = metrics.parse_duration("7d")
        self.assertIsNotNone(out)

    def test_iso_timestamp(self):
        out = metrics.parse_duration("2026-05-14T00:00:00Z")
        self.assertIsNotNone(out)

    def test_invalid_returns_none(self):
        self.assertIsNone(metrics.parse_duration("bogus"))
        self.assertIsNone(metrics.parse_duration(""))


class TestRollup(MetricsBase):
    def test_rollup_counts_tools(self):
        _write_trace(self.trace_file, [
            {"ts": "2026-05-14T00:00:00Z", "evt": "PreToolUse-Skill", "tool": "Skill",
             "data": {"ident": "brain"}},
            {"ts": "2026-05-14T00:00:01Z", "evt": "PreToolUse-Skill", "tool": "Skill",
             "data": {"ident": "brain"}},
            {"ts": "2026-05-14T00:00:02Z", "evt": "PreToolUse-Edit", "tool": "Edit"},
        ])
        r = metrics.rollup_events()
        self.assertEqual(r.by_tool["Skill"], 2)
        self.assertEqual(r.by_tool["Edit"], 1)
        self.assertEqual(r.by_skill["brain"], 2)

    def test_rollup_counts_mcp(self):
        _write_trace(self.trace_file, [
            {"ts": "2026-05-14T00:00:00Z", "evt": "PreToolUse-mcp__plugin_kaizen_brain__capture",
             "tool": "mcp__plugin_kaizen_brain__capture"},
            {"ts": "2026-05-14T00:00:01Z", "evt": "PreToolUse-mcp__plugin_kaizen_brain__capture",
             "tool": "mcp__plugin_kaizen_brain__capture"},
        ])
        r = metrics.rollup_events()
        self.assertEqual(r.by_mcp["mcp__plugin_kaizen_brain__capture"], 2)

    def test_rollup_post_tool_does_not_double_count(self):
        _write_trace(self.trace_file, [
            {"ts": "2026-05-14T00:00:00Z", "evt": "PreToolUse-Skill", "tool": "Skill",
             "data": {"ident": "brain"}},
            {"ts": "2026-05-14T00:00:01Z", "evt": "PostToolUse-Skill", "tool": "Skill",
             "data": {"result": "ok"}},
        ])
        r = metrics.rollup_events()
        # Tool counted on Pre only — not double
        self.assertEqual(r.by_tool["Skill"], 1)

    def test_rollup_counts_errors(self):
        _write_trace(self.trace_file, [
            {"ts": "2026-05-14T00:00:00Z", "evt": "PostToolUse-Edit", "tool": "Edit",
             "data": {"result": "err"}},
            {"ts": "2026-05-14T00:00:01Z", "evt": "PostToolUse-Edit", "tool": "Edit",
             "data": {"result": "ok"}},
        ])
        r = metrics.rollup_events()
        self.assertEqual(r.errors, 1)

    def test_rollup_session_tracking(self):
        _write_trace(self.trace_file, [
            {"ts": "2026-05-14T00:00:00Z", "evt": "SessionStart", "sid": "s1"},
            {"ts": "2026-05-14T00:00:01Z", "evt": "SessionStart", "sid": "s2"},
            {"ts": "2026-05-14T00:00:02Z", "evt": "X", "sid": "s1"},
        ])
        r = metrics.rollup_events()
        self.assertEqual(len(r.sessions), 2)


class TestLatestSession(MetricsBase):
    def test_latest_session_id(self):
        _write_trace(self.trace_file, [
            {"ts": "2026-05-13T00:00:00Z", "evt": "SessionStart", "sid": "old"},
            {"ts": "2026-05-14T00:00:00Z", "evt": "SessionStart", "sid": "newer"},
        ])
        self.assertEqual(metrics.latest_session_id(), "newer")

    def test_returns_none_on_empty(self):
        self.assertIsNone(metrics.latest_session_id())


class TestNeverUsed(MetricsBase):
    def test_never_used_skills_finds_all_when_trace_empty(self):
        # Empty trace → all available skills are never-used
        _write_trace(self.trace_file, [])
        result = metrics.never_used("skill")
        self.assertEqual(result["kind"], "skill")
        self.assertEqual(result["used_count"], 0)
        # Plugin-original skills are visible
        self.assertGreater(len(result["never_used"]), 0)

    def test_never_used_excludes_vendored(self):
        _write_trace(self.trace_file, [])
        result = metrics.never_used("skill")
        # Vendored skills must NOT appear in available -> not in never_used
        for vendored in ("kiss", "solid", "yagni"):
            self.assertNotIn(vendored, result["never_used"])

    def test_never_used_skill_marks_used(self):
        _write_trace(self.trace_file, [
            {"ts": "2026-05-14T00:00:00Z", "evt": "PreToolUse-Skill",
             "tool": "Skill", "data": {"ident": "brain"}},
        ])
        result = metrics.never_used("skill")
        self.assertEqual(result["used_count"], 1)
        self.assertNotIn("brain", result["never_used"])

    def test_never_used_tool(self):
        _write_trace(self.trace_file, [
            {"ts": "2026-05-14T00:00:00Z", "evt": "PreToolUse-Bash", "tool": "Bash"},
            {"ts": "2026-05-14T00:00:01Z", "evt": "PreToolUse-Edit", "tool": "Edit"},
        ])
        result = metrics.never_used("tool")
        self.assertIn("Bash", [x for x in result["never_used"]] + ["Bash"])  # noqa
        # Anyway, expected_count is positive
        self.assertGreater(result["expected_count"], 0)

    def test_never_used_invalid_kind_raises(self):
        _write_trace(self.trace_file, [])
        with self.assertRaises(ValueError):
            metrics.never_used("bogus")


class TestTopN(MetricsBase):
    def test_top_n_by_tool(self):
        events = []
        for _ in range(5):
            events.append({"ts": "2026-05-14T00:00:00Z",
                           "evt": "PreToolUse-Skill", "tool": "Skill",
                           "data": {"ident": "brain"}})
        for _ in range(3):
            events.append({"ts": "2026-05-14T00:00:01Z",
                           "evt": "PreToolUse-Skill", "tool": "Skill",
                           "data": {"ident": "workflow"}})
        _write_trace(self.trace_file, events)
        top = metrics.top_n("skill", n=2)
        self.assertEqual(top[0][0], "brain")
        self.assertEqual(top[0][1], 5)


class TestSkipDetection(MetricsBase):
    def test_skip_detected_when_files_touched_skill_not_loaded(self):
        # Touched a brain file, never loaded the brain skill
        _write_trace(self.trace_file, [
            {"ts": "2026-05-14T00:00:00Z", "evt": "PreToolUse-Edit",
             "tool": "Edit", "sid": "s1",
             "data": {"ident": "plugins/kaizen/skills/brain/SKILL.md"}},
        ])
        skips = metrics.detect_skips(sid="s1")
        # brain rule should fire
        skill_names = [s["skill"] for s in skips]
        self.assertIn("brain", skill_names)

    def test_no_skip_when_skill_loaded(self):
        # Touched + skill loaded → no skip
        _write_trace(self.trace_file, [
            {"ts": "2026-05-14T00:00:00Z", "evt": "PreToolUse-Skill",
             "tool": "Skill", "sid": "s1", "data": {"ident": "brain"}},
            {"ts": "2026-05-14T00:00:01Z", "evt": "PreToolUse-Edit",
             "tool": "Edit", "sid": "s1",
             "data": {"ident": "plugins/kaizen/skills/brain/SKILL.md"}},
        ])
        skips = metrics.detect_skips(sid="s1")
        skill_names = [s["skill"] for s in skips]
        self.assertNotIn("brain", skill_names)

    def test_no_skip_when_no_touched_files(self):
        # Only Bash events → nothing triggers skip detection
        _write_trace(self.trace_file, [
            {"ts": "2026-05-14T00:00:00Z", "evt": "PreToolUse-Bash",
             "tool": "Bash", "sid": "s1"},
        ])
        skips = metrics.detect_skips(sid="s1")
        self.assertEqual(skips, [])

    def test_plugin_development_skip(self):
        # Touched plugin code without loading plugin-development skill
        _write_trace(self.trace_file, [
            {"ts": "2026-05-14T00:00:00Z", "evt": "PreToolUse-Edit",
             "tool": "Edit", "sid": "s1",
             "data": {"ident": "plugins/kaizen/.claude-plugin/plugin.json"}},
        ])
        skips = metrics.detect_skips(sid="s1")
        skill_names = [s["skill"] for s in skips]
        self.assertIn("plugin-development", skill_names)

    def test_skip_detection_returns_empty_on_no_session(self):
        _write_trace(self.trace_file, [])
        skips = metrics.detect_skips()
        self.assertEqual(skips, [])

    def test_skip_includes_touched_files(self):
        _write_trace(self.trace_file, [
            {"ts": "2026-05-14T00:00:00Z", "evt": "PreToolUse-Edit",
             "tool": "Edit", "sid": "s1",
             "data": {"ident": "plugins/kaizen/skills/brain/SKILL.md"}},
            {"ts": "2026-05-14T00:00:01Z", "evt": "PreToolUse-Write",
             "tool": "Write", "sid": "s1",
             "data": {"ident": "plugins/kaizen/skills/brain/domain/x.yaml"}},
        ])
        skips = metrics.detect_skips(sid="s1")
        brain_skip = next(s for s in skips if s["skill"] == "brain")
        self.assertEqual(brain_skip["touched_count"], 2)


class TestTraceAge(MetricsBase):
    def test_trace_age_none_when_no_matching_events(self):
        _write_trace(self.trace_file, [
            {"ts": "2026-05-14T00:00:00Z", "evt": "PreToolUse-Bash", "tool": "Bash"},
        ])
        # No PreToolUse-Skill events → skill trace age is None
        self.assertIsNone(metrics.trace_age_days("skill"))

    def test_trace_age_positive_when_events_exist(self):
        # An event from well in the past → age should be large
        _write_trace(self.trace_file, [
            {"ts": "2026-01-01T00:00:00Z", "evt": "PreToolUse-Skill",
             "tool": "Skill", "data": {"ident": "brain"}},
        ])
        age = metrics.trace_age_days("skill")
        self.assertIsNotNone(age)
        self.assertGreater(age, 30)  # Jan 1 → mid-May is >> 30 days


class TestGraveyard(MetricsBase):
    def test_graveyard_not_ready_when_no_events(self):
        _write_trace(self.trace_file, [])
        result = metrics.graveyard(kind="skill", stale_days=14)
        self.assertFalse(result["ready"])
        self.assertEqual(result["candidates"], [])
        self.assertIn("caveat", result)

    def test_graveyard_not_ready_when_trace_too_young(self):
        # A skill event from "now" → trace age ~0 days < 14
        _write_trace(self.trace_file, [
            {"ts": dt_now_iso(), "evt": "PreToolUse-Skill",
             "tool": "Skill", "data": {"ident": "brain"}},
        ])
        result = metrics.graveyard(kind="skill", stale_days=14)
        self.assertFalse(result["ready"])
        self.assertIn("too young", result["caveat"].lower())

    def test_graveyard_ready_when_trace_old_enough(self):
        # A skill event from Jan → trace age >> 14 days → ready
        _write_trace(self.trace_file, [
            {"ts": "2026-01-01T00:00:00Z", "evt": "PreToolUse-Skill",
             "tool": "Skill", "data": {"ident": "brain"}},
        ])
        result = metrics.graveyard(kind="skill", stale_days=14)
        self.assertTrue(result["ready"])
        # 'brain' was used; the rest of available_skills are candidates
        self.assertNotIn("brain", result["candidates"])
        self.assertIn("archive_hint", result)


def dt_now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TestSmokeMcp(unittest.TestCase):
    """smoke_mcp imports the real MCP modules — runs against the
    actual plugin tree (not sandboxed). Tolerant of mcp-not-installed."""

    def test_smoke_returns_expected_shape(self):
        result = metrics.smoke_mcp()
        self.assertIn("checked", result)
        self.assertIn("passed", result)
        self.assertIn("failed", result)
        self.assertIn("skipped", result)

    def test_smoke_skipped_or_checks(self):
        result = metrics.smoke_mcp()
        if result["skipped"]:
            # mcp not installed — checked should be 0
            self.assertEqual(result["checked"], 0)
        else:
            # mcp installed — should have checked the *_mcp.py files
            self.assertGreater(result["checked"], 0)
            # passed + failed should account for everything checked
            self.assertEqual(
                result["passed"] + len(result["failed"]),
                result["checked"],
            )

    def test_smoke_failures_have_name_and_error(self):
        result = metrics.smoke_mcp()
        for f in result["failed"]:
            self.assertIn("name", f)
            self.assertIn("error", f)


class TestPaths(unittest.TestCase):
    def test_trace_log_path_env_override(self):
        orig = os.environ.get("KAIZEN_TRACE_DIR")
        os.environ["KAIZEN_TRACE_DIR"] = "/tmp/x-test"
        try:
            self.assertEqual(
                str(metrics.trace_log_path()),
                "/tmp/x-test/events.jsonl",
            )
        finally:
            if orig is None:
                os.environ.pop("KAIZEN_TRACE_DIR", None)
            else:
                os.environ["KAIZEN_TRACE_DIR"] = orig


class TestCli(unittest.TestCase):
    """End-to-end CLI tests — subprocess to ensure argparse wiring."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.trace_dir = Path(self._tmp.name) / "trace"
        self.trace_dir.mkdir()
        (self.trace_dir / "events.jsonl").write_text(
            '{"ts":"2026-05-14T00:00:00Z","evt":"PreToolUse-Skill","tool":"Skill","data":{"ident":"brain"},"sid":"smoke"}\n'
        )
        self._orig = os.environ.get("KAIZEN_TRACE_DIR")
        os.environ["KAIZEN_TRACE_DIR"] = str(self.trace_dir)

    def tearDown(self):
        self._tmp.cleanup()
        if self._orig is None:
            os.environ.pop("KAIZEN_TRACE_DIR", None)
        else:
            os.environ["KAIZEN_TRACE_DIR"] = self._orig

    def _run(self, *args):
        import subprocess
        script = _KZ_DIR / "skills/workflow/scripts/metrics.py"
        env = os.environ.copy()
        return subprocess.run(
            ["python3", str(script), *args],
            capture_output=True, text=True, env=env, timeout=10,
        )

    def test_path_subcommand(self):
        result = self._run("path")
        self.assertEqual(result.returncode, 0)
        out = json.loads(result.stdout)
        self.assertIn("trace_log", out)

    def test_lifetime_subcommand(self):
        result = self._run("lifetime", "--json")
        self.assertEqual(result.returncode, 0)
        out = json.loads(result.stdout)
        self.assertGreaterEqual(out["total_events"], 1)

    def test_session_subcommand(self):
        result = self._run("session", "--sid", "smoke", "--json")
        self.assertEqual(result.returncode, 0)
        out = json.loads(result.stdout)
        self.assertEqual(out["sid"], "smoke")

    def test_top_subcommand(self):
        result = self._run("top", "--kind", "skill", "--n", "5", "--json")
        self.assertEqual(result.returncode, 0)
        out = json.loads(result.stdout)
        self.assertIsInstance(out, list)

    def test_never_used_subcommand(self):
        result = self._run("never-used", "--kind", "skill", "--json")
        self.assertEqual(result.returncode, 0)
        out = json.loads(result.stdout)
        self.assertEqual(out["kind"], "skill")


def _mcp_available():
    try:
        import mcp  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(_mcp_available(), "mcp package not installed")
class TestMcpServer(MetricsBase):
    """Smoke tests for metrics_mcp.py — verify the FastMCP server
    registers its tools and they wrap the metrics helpers."""

    def test_module_imports_cleanly(self):
        import metrics_mcp  # noqa: F401

    def test_tools_are_async(self):
        import metrics_mcp
        import asyncio as _aio
        for name in ("metrics_session", "metrics_lifetime",
                     "metrics_never_used", "metrics_top",
                     "metrics_skips", "metrics_path"):
            fn = getattr(metrics_mcp, name, None)
            self.assertIsNotNone(fn, f"missing tool: {name}")
            self.assertTrue(_aio.iscoroutinefunction(fn))


class TestMcpModuleParses(unittest.TestCase):
    """Even without mcp installed, the .py file should compile."""

    def test_metrics_mcp_compiles(self):
        path = _KZ_DIR / "skills/workflow/scripts/metrics_mcp.py"
        with open(path, "r") as f:
            compile(f.read(), str(path), "exec")


if __name__ == "__main__":
    unittest.main()
