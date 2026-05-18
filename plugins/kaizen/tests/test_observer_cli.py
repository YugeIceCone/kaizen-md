"""Tests for kaizen-observe — query the observer events.jsonl sink.

Closes the read-side of the observer: events flow in via the capture
hook (Phase 1.5); the agent + user query them via this CLI.

Subcommands:
  recent [--n N] [--json]                 — last N events (default 10)
  stats  [--json]                          — counts per event_kind + per tool
  filter [--tool T] [--source S] [--since DUR] [--n N] [--json]
                                            — selective query

Iron-laws:
  - READ-only (never writes the sink) — opposite of capture hook
  - graceful on missing sink (returns empty / "[]" / "no events")
  - human-readable default + --json for scripting
  - env-overridable via KAIZEN_OBSERVER_DIR
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
_OBS_PY = _KZ_DIR / "skills/workflow/scripts/observer_events.py"


class _ObserveBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._orig = os.environ.get("KAIZEN_OBSERVER_DIR")
        os.environ["KAIZEN_OBSERVER_DIR"] = str(self.tmp)
        self.sink = self.tmp / "events.jsonl"

    def tearDown(self):
        self._tmp.cleanup()
        if self._orig is None:
            os.environ.pop("KAIZEN_OBSERVER_DIR", None)
        else:
            os.environ["KAIZEN_OBSERVER_DIR"] = self._orig

    def _seed(self, events: list[dict]) -> None:
        with self.sink.open("a", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_OBS_PY), *args],
            capture_output=True, text=True, timeout=15,
            env=os.environ.copy(),
        )


def _evt(tool: str, source: str = "parent", ts: str = "2026-05-18T20:00:00Z",
          kind: str = "post_tool_use", sid: str = "s1") -> dict:
    return {
        "ts": ts, "event_kind": kind, "source": source,
        "sid": sid, "tool": tool, "params": {"file_path": f"/{tool}.py"},
    }


class TestRecent(_ObserveBase):
    def test_no_sink_returns_empty(self):
        r = self._run("recent", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), [])

    def test_default_returns_last_10(self):
        self._seed([_evt(f"Tool{i}") for i in range(15)])
        r = self._run("recent", "--json")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(len(data), 10)
        # last-N = entries 5..14 in input order
        self.assertEqual(data[0]["tool"], "Tool5")
        self.assertEqual(data[-1]["tool"], "Tool14")

    def test_n_override(self):
        self._seed([_evt(f"Tool{i}") for i in range(15)])
        r = self._run("recent", "--n", "3", "--json")
        data = json.loads(r.stdout)
        self.assertEqual(len(data), 3)
        self.assertEqual([d["tool"] for d in data],
                          ["Tool12", "Tool13", "Tool14"])

    def test_human_readable_default(self):
        self._seed([_evt("Read"), _evt("Edit")])
        r = self._run("recent")
        self.assertEqual(r.returncode, 0)
        # Default format: one line per event with key fields
        self.assertIn("Read", r.stdout)
        self.assertIn("Edit", r.stdout)
        self.assertIn("post_tool_use", r.stdout)


class TestStats(_ObserveBase):
    def test_counts_by_event_kind_and_tool(self):
        self._seed([
            _evt("Read", kind="pre_tool_use"),
            _evt("Read", kind="post_tool_use"),
            _evt("Edit", kind="post_tool_use"),
            _evt("Edit", kind="post_tool_use"),
            _evt("Bash", kind="post_tool_use"),
        ])
        r = self._run("stats", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        stats = json.loads(r.stdout)
        self.assertEqual(stats["total"], 5)
        self.assertEqual(stats["by_event_kind"]["post_tool_use"], 4)
        self.assertEqual(stats["by_event_kind"]["pre_tool_use"], 1)
        self.assertEqual(stats["by_tool"]["Read"], 2)
        self.assertEqual(stats["by_tool"]["Edit"], 2)
        self.assertEqual(stats["by_tool"]["Bash"], 1)

    def test_no_sink_zero_stats(self):
        r = self._run("stats", "--json")
        self.assertEqual(r.returncode, 0)
        stats = json.loads(r.stdout)
        self.assertEqual(stats["total"], 0)


class TestFilter(_ObserveBase):
    def test_filter_by_tool(self):
        self._seed([_evt("Read"), _evt("Edit"), _evt("Read"), _evt("Bash")])
        r = self._run("filter", "--tool", "Read", "--json")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(len(data), 2)
        for e in data:
            self.assertEqual(e["tool"], "Read")

    def test_filter_by_source(self):
        self._seed([
            _evt("Read", source="parent"),
            _evt("Edit", source="subagent"),
            _evt("Bash", source="subagent"),
        ])
        r = self._run("filter", "--source", "subagent", "--json")
        data = json.loads(r.stdout)
        self.assertEqual(len(data), 2)


class TestGracefulInvalid(_ObserveBase):
    def test_malformed_jsonl_lines_skipped(self):
        # Write 1 valid + 1 garbage line; recent should still return the valid
        self.sink.parent.mkdir(parents=True, exist_ok=True)
        with self.sink.open("w", encoding="utf-8") as f:
            f.write(json.dumps(_evt("Read")) + "\n")
            f.write("garbage non-json line\n")
            f.write(json.dumps(_evt("Edit")) + "\n")
        r = self._run("recent", "--json")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(len(data), 2)


if __name__ == "__main__":
    unittest.main()
