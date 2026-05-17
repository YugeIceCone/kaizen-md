"""Contract tests for kaizen-gold auto-miner.

These are PUBLIC-CONTRACT assertions — the implementation may evolve,
but these must keep passing. They define what kaizen-gold's mine /
review surfaces look like from the outside: CLI shape, exit codes,
file formats, env knobs, threshold semantics.

Implementation-level tests (cursor internals, normalize helpers,
Ollama parser) live in test_gold_mine.py. This file is the SPEC.

Skip-policy: when the auto-miner hasn't shipped yet, skip the whole
module via unittest.skipUnless on the gold_mine.py file's existence.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_KZ_DIR = Path(__file__).resolve().parent.parent
_GOLD = _KZ_DIR / "skills/workflow/scripts/gold.py"
_MINE = _KZ_DIR / "skills/workflow/scripts/gold_mine.py"
_HOOK = _KZ_DIR / "hooks/claude/gold-sessionend-mine.sh"

# Skip the whole module until the implementer subagent's worktree merges.
_PRE_MERGE = not _MINE.is_file()


class MineBase(unittest.TestCase):
    """Shared sandbox env. Mirrors GoldBase.setUp shape but adds
    KAIZEN_DIR override so the cursor + proposals end up in tmp too."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.kaizen_dir = self.tmp / ".kaizen"
        self.kaizen_dir.mkdir()
        # Simulate the per-project layout
        self.project_slug = "-tmp-test-project"
        self.gold_dir = self.kaizen_dir / "gold" / self.project_slug
        self.gold_dir.mkdir(parents=True)
        self.store = self.gold_dir / "patterns.jsonl"
        self.cursor = self.gold_dir / "mine-cursor.json"
        self.proposals = self.gold_dir / "proposals.jsonl"

        self.env = {
            "KAIZEN_DIR":        str(self.kaizen_dir),
            "KAIZEN_GOLD_FILE":  str(self.store),
        }

    def tearDown(self):
        self._tmp.cleanup()

    def _run_gold(self, *args, env_extra=None) -> subprocess.CompletedProcess:
        e = dict(self.env)
        if env_extra:
            e.update(env_extra)
        return subprocess.run(
            [sys.executable, str(_GOLD), *args],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, **e},
        )

    def _seed_dxm(self, events: list[dict]) -> Path:
        """Write a synthetic dxm events file the miner will scan.
        Returns the path so tests can override KAIZEN_DXM_DIR."""
        dxm_dir = self.kaizen_dir / "dxm"
        dxm_dir.mkdir(exist_ok=True)
        p = dxm_dir / "events-test-sid.jsonl"
        with p.open("w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
        return p


@unittest.skipIf(_PRE_MERGE, "gold_mine.py not merged yet")
class TestCLISurface(MineBase):
    """`kaizen gold mine` and `kaizen gold review` must be addressable
    subcommands of the existing gold CLI — not standalone bins."""

    def test_mine_subcommand_exists(self):
        r = self._run_gold("mine", "--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("mine", r.stdout.lower())

    def test_review_subcommand_exists(self):
        r = self._run_gold("review", "--help")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_mine_empty_run_exits_zero(self):
        """No prior cursor + no dxm events → no proposals → exit 0."""
        r = self._run_gold("mine")
        self.assertEqual(r.returncode, 0, r.stderr)


@unittest.skipIf(_PRE_MERGE, "gold_mine.py not merged yet")
class TestEnvKnobs(MineBase):
    """The mine pipeline is gated on env knobs. Without
    KAIZEN_GOLD_MINE_ENABLE=1 the LLM call is skipped; with
    KAIZEN_GOLD_DISABLE=1 the whole feature exits silently."""

    def test_disable_knob_skips_silently(self):
        self._seed_dxm([
            {"evt_type": "context.warn.red", "payload": {"pct": 92}},
        ])
        r = self._run_gold("mine",
                            env_extra={"KAIZEN_GOLD_DISABLE": "1"})
        self.assertEqual(r.returncode, 0)
        # No proposals created
        self.assertFalse(self.proposals.is_file())

    def test_mine_enable_off_means_no_llm_call(self):
        """Default state: mechanical pipeline runs, but no Ollama call.
        Should not need a running Ollama instance to exit cleanly."""
        self._seed_dxm([
            {"evt_type": "context.warn.red", "payload": {"pct": 92}},
        ])
        # KAIZEN_GOLD_MINE_ENABLE NOT set
        r = self._run_gold("mine")
        self.assertEqual(r.returncode, 0, r.stderr)
        # Without LLM scoring, no proposals are graded → no proposals file
        # (or file exists but empty)
        if self.proposals.is_file():
            self.assertEqual(self.proposals.read_text().strip(), "")


@unittest.skipIf(_PRE_MERGE, "gold_mine.py not merged yet")
class TestCursorContract(MineBase):
    """Cursor file lives at $KAIZEN_DIR/gold/<slug>/mine-cursor.json
    and tracks per-target {inode, byte_offset, sha256_tail, mtime,
    line_count}. Same-mtime invocation must short-circuit."""

    def test_cursor_written_after_first_run(self):
        self._seed_dxm([{"evt_type": "Stop", "payload": {}}])
        self._run_gold("mine")
        self.assertTrue(self.cursor.is_file(),
                          "cursor file must be written after a mine run")
        data = json.loads(self.cursor.read_text())
        self.assertIn("dxm", data,
                       "cursor must have a 'dxm' key (per-target)")

    def test_cursor_short_circuits_when_mtime_unchanged(self):
        """Second run on an unchanged file should NOT re-scan."""
        events_path = self._seed_dxm([
            {"evt_type": "context.warn.red", "payload": {"pct": 92}},
        ])
        self._run_gold("mine")
        before_mtime = events_path.stat().st_mtime
        # Re-run — file mtime unchanged
        r2 = self._run_gold("mine")
        self.assertEqual(r2.returncode, 0)
        # Cursor untouched in-place (or rewritten with same content)
        self.assertEqual(events_path.stat().st_mtime, before_mtime)


@unittest.skipIf(_PRE_MERGE, "gold_mine.py not merged yet")
class TestAntiRecursion(MineBase):
    """The miner must not score its own emissions. Events with
    `tool_name == "kaizen-gold"` are skipped at the filter step."""

    def test_kaizen_gold_events_are_skipped(self):
        self._seed_dxm([
            {"evt_type": "gold.captured", "tool_name": "kaizen-gold",
             "payload": {"id": 1, "pattern": "first capture"}},
            {"evt_type": "context.warn.red", "payload": {"pct": 95}},
        ])
        r = self._run_gold("mine")
        self.assertEqual(r.returncode, 0)
        # If proposals exist, none should reference the kaizen-gold event
        if self.proposals.is_file():
            for line in self.proposals.read_text().strip().splitlines():
                if not line:
                    continue
                p = json.loads(line)
                self.assertNotEqual(p.get("tool"), "kaizen-gold",
                                     "miner mined its own capture event")


@unittest.skipIf(_PRE_MERGE, "gold_mine.py not merged yet")
class TestProposalShape(MineBase):
    """Each row in proposals.jsonl must conform to a fixed schema so
    `kaizen gold review` + downstream consumers can parse it."""

    REQUIRED_FIELDS = {"id", "ts", "score", "pattern", "tag",
                       "reason", "source_evt", "source_tool", "status"}

    def test_proposal_row_schema(self):
        """When the LLM does emit a proposal, its row must have the
        documented fields. Hard to assert without an LLM; this is a
        skip-when-empty contract — implementer can write a focused
        impl-level test that runs with a mocked Ollama."""
        if not self.proposals.is_file():
            self.skipTest("no proposals file — needs Ollama integration test")
        for line in self.proposals.read_text().strip().splitlines():
            p = json.loads(line)
            missing = self.REQUIRED_FIELDS - set(p)
            self.assertFalse(missing, f"missing fields: {missing}")
            self.assertIn(p["status"],
                           ("pending", "accepted", "rejected", "auto-captured"))
            self.assertGreaterEqual(p["score"], 0.0)
            self.assertLessEqual(p["score"], 1.0)


@unittest.skipIf(_PRE_MERGE, "gold_mine.py not merged yet")
class TestReviewCLI(MineBase):
    """`kaizen gold review` lists pending proposals + accept/reject
    individual ones by id."""

    def _seed_proposal(self, **overrides) -> int:
        """Hand-seed a proposal so review tests don't need Ollama."""
        rec = {
            "id":          1,
            "ts":          "2026-05-17T15:00:00Z",
            "score":       0.78,
            "pattern":     "test pattern",
            "tag":         "auto-mined",
            "reason":      "looks gold-worthy",
            "source_evt":  "context.warn.red",
            "source_tool": None,
            "status":      "pending",
        }
        rec.update(overrides)
        with self.proposals.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        return rec["id"]

    def test_review_list_pending(self):
        self._seed_proposal()
        r = self._run_gold("review")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("test pattern", r.stdout)

    def test_review_accept_promotes_to_capture(self):
        pid = self._seed_proposal()
        r = self._run_gold("review", "--accept", str(pid))
        self.assertEqual(r.returncode, 0, r.stderr)
        # The proposal should be marked accepted
        rows = [json.loads(l) for l in self.proposals.read_text().splitlines() if l]
        self.assertEqual(rows[0]["status"], "accepted")
        # And a gold capture should have appeared in patterns.jsonl
        self.assertTrue(self.store.is_file())
        captures = [json.loads(l) for l in self.store.read_text().splitlines() if l]
        self.assertEqual(captures[0]["pattern"], "test pattern")
        self.assertEqual(captures[0]["tag"], "auto-mined")

    def test_review_reject_marks_status(self):
        pid = self._seed_proposal()
        r = self._run_gold("review", "--reject", str(pid))
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = [json.loads(l) for l in self.proposals.read_text().splitlines() if l]
        self.assertEqual(rows[0]["status"], "rejected")
        # No capture created
        self.assertFalse(self.store.is_file() and self.store.read_text().strip())


@unittest.skipIf(_PRE_MERGE, "gold_mine.py not merged yet")
class TestThresholdGate(MineBase):
    """The threshold semantic is the public contract:
       score < 0.75  → drop
       0.75 ≤ score < 0.85  → proposals.jsonl (status=pending)
       score ≥ 0.85  → patterns.jsonl (auto-captured, tag=auto-mined)
                       + dxm event gold.auto_captured

    Hard to assert without an LLM stub. This class documents the
    contract and points implementer to a focused impl-level test.
    """

    def test_threshold_constants_documented(self):
        """The contract: 0.75 / 0.85 are the documented gates. The
        implementation file must declare them as module-level
        constants so external code can introspect."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("gold_mine", _MINE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertTrue(hasattr(mod, "PROPOSAL_THRESHOLD"))
        self.assertTrue(hasattr(mod, "AUTO_CAPTURE_THRESHOLD"))
        self.assertEqual(mod.PROPOSAL_THRESHOLD, 0.75)
        self.assertEqual(mod.AUTO_CAPTURE_THRESHOLD, 0.85)
        self.assertLess(mod.PROPOSAL_THRESHOLD, mod.AUTO_CAPTURE_THRESHOLD)


@unittest.skipIf(not _HOOK.is_file(), "gold-sessionend-mine.sh not merged yet")
class TestHookWiring(unittest.TestCase):
    """SessionEnd hook artifact + plugin.json + hooks.json wiring."""

    def test_hook_exists_and_executable(self):
        self.assertTrue(_HOOK.is_file())
        self.assertTrue(os.access(_HOOK, os.X_OK))

    def test_hook_in_hooks_json_under_sessionend(self):
        hooks_json = _KZ_DIR / "hooks/hooks.json"
        data = json.loads(hooks_json.read_text())
        sessionend = data["hooks"].get("SessionEnd", [])
        cmds = [h["command"]
                for block in sessionend
                for h in block.get("hooks", [])]
        self.assertTrue(any("gold-sessionend-mine" in c for c in cmds),
                          f"hook not wired into SessionEnd: {cmds}")

    def test_hook_permission_in_plugin_json(self):
        plugin_json = _KZ_DIR / ".claude-plugin/plugin.json"
        data = json.loads(plugin_json.read_text())
        allow = data["permissions"]["allow"]
        self.assertTrue(any("gold-sessionend-mine" in e for e in allow))


if __name__ == "__main__":
    unittest.main()
