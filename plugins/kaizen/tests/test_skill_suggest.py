"""Tests for skill_suggest.py — prompt → skill matcher.

Sandbox via KAIZEN_SKILL_SUGGEST_ROOT — point the matcher at a
tempdir holding synthetic SKILL.md files so tests don't depend on
real catalog content (which can change as skills are added/removed).
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
_SCRIPT = _KZ_DIR / "scripts/util/skill_suggest.py"


class _Sandbox(unittest.TestCase):
    def setUp(self):
        self._cwd0 = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._orig = os.environ.get("KAIZEN_SKILL_SUGGEST_ROOT")
        os.environ["KAIZEN_SKILL_SUGGEST_ROOT"] = str(self.tmp)

    def tearDown(self):
        try: os.chdir(self._cwd0)
        except OSError: pass
        self._tmp.cleanup()
        if self._orig is None:
            os.environ.pop("KAIZEN_SKILL_SUGGEST_ROOT", None)
        else:
            os.environ["KAIZEN_SKILL_SUGGEST_ROOT"] = self._orig

    def _add_skill(self, name: str, description: str):
        d = self.tmp / name
        d.mkdir()
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\nbody\n",
            encoding="utf-8",
        )

    def _run(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_SCRIPT), *args],
            capture_output=True, text=True, timeout=10,
            env=os.environ.copy(),
        )


class TestMatchQuotedTriggers(_Sandbox):
    def test_matches_skill_with_quoted_trigger(self):
        self._add_skill("onion",
                         'Use for layered. Triggers on "onion architecture", '
                         '"ports and adapters".')
        r = self._run("match", "--prompt",
                       "let's apply onion architecture here",
                       "--json")
        data = json.loads(r.stdout)
        names = [m["name"] for m in data["matches"]]
        self.assertEqual(names, ["onion"])
        self.assertIn("onion architecture", data["matches"][0]["matched"])


class TestSkillWithoutQuotedTriggersSkipped(_Sandbox):
    """Precision-over-recall: skills with no quoted phrases in their
    description don't get matched (would be too noisy)."""
    def test_no_quoted_triggers_no_match(self):
        self._add_skill("vague",
                         "Use this when you want a vague helper for things.")
        r = self._run("match", "--prompt", "I want a vague helper for things",
                       "--json")
        data = json.loads(r.stdout)
        self.assertEqual(data["matches"], [])


class TestRankByMatchCount(_Sandbox):
    def test_skill_with_more_matches_ranks_higher(self):
        self._add_skill("a",
                         'Triggers on "alpha-pat", "beta-pat".')
        self._add_skill("b",
                         'Triggers on "alpha-pat", "beta-pat", "gamma-pat".')
        # Prompt hits 2 triggers in BOTH; tiebreak goes to b (more total triggers)
        r = self._run("match", "--prompt", "alpha-pat and beta-pat", "--json")
        data = json.loads(r.stdout)
        names = [m["name"] for m in data["matches"]]
        # Both should match; b has more triggers so it sorts first on tiebreak
        # (we sort by match_count desc, then trigger_count desc)
        self.assertEqual(set(names), {"a", "b"})
        # Verify b is FIRST (more total triggers → more authoritative)
        self.assertEqual(names[0], "b")

    def test_higher_match_count_wins(self):
        self._add_skill("low", 'Triggers on "alpha-pat".')
        self._add_skill("high", 'Triggers on "alpha-pat", "beta-pat".')
        r = self._run("match", "--prompt", "alpha-pat beta-pat", "--json")
        data = json.loads(r.stdout)
        names = [m["name"] for m in data["matches"]]
        self.assertEqual(names[0], "high")  # 2 matches > 1 match


class TestCaseInsensitive(_Sandbox):
    def test_case_does_not_block_match(self):
        self._add_skill("x", 'Triggers on "Onion Architecture".')
        r = self._run("match", "--prompt", "use ONION architecture", "--json")
        data = json.loads(r.stdout)
        self.assertEqual(len(data["matches"]), 1)


class TestMaxResultsCap(_Sandbox):
    def test_max_results_limits_output(self):
        for i in range(5):
            self._add_skill(f"s{i}", f'Triggers on "tag-pat-{i}".')
        prompt = " ".join(f"tag-pat-{i}" for i in range(5))
        r = self._run("match", "--prompt", prompt, "--max", "2", "--json")
        data = json.loads(r.stdout)
        self.assertEqual(len(data["matches"]), 2)


class TestNoPromptNoMatches(_Sandbox):
    def test_empty_prompt_returns_no_matches(self):
        self._add_skill("x", 'Triggers on "alpha".')
        r = self._run("match", "--prompt", "", "--json")
        data = json.loads(r.stdout)
        self.assertEqual(data["matches"], [])


class TestListSubcommand(_Sandbox):
    def test_list_shows_all_skills_with_trigger_counts(self):
        self._add_skill("with-triggers",
                         'Triggers on "alpha-trig", "beta-trig", "gamma-trig".')
        self._add_skill("no-triggers", 'Just a vague description.')
        r = self._run("list", "--json")
        data = json.loads(r.stdout)
        names = {s["name"] for s in data["skills"]}
        self.assertEqual(names, {"with-triggers", "no-triggers"})
        for s in data["skills"]:
            if s["name"] == "with-triggers":
                self.assertEqual(len(s["triggers"]), 3)
            else:
                self.assertEqual(len(s["triggers"]), 0)


class TestFromDxmPostHoc(_Sandbox):
    """`from-dxm` reads dxm events + inbox post-hoc and reports
    prompt-vs-skill misses. Zero UserPromptSubmit latency cost."""

    def setUp(self):
        super().setUp()
        # Add a sandboxed dxm dir + inbox dir
        self.dxm = self.tmp / "dxm"
        self.dxm.mkdir()
        self.inbox = self.tmp / "inbox"
        self.inbox.mkdir()
        os.environ["KAIZEN_DXM_DIR"] = str(self.dxm)
        os.environ["KAIZEN_INBOX_DIR"] = str(self.inbox)

    def tearDown(self):
        os.environ.pop("KAIZEN_DXM_DIR", None)
        os.environ.pop("KAIZEN_INBOX_DIR", None)
        super().tearDown()

    def _seed_inbox_prompt(self, session_id: str, prompt: str, ts: str):
        path = self.inbox / f"{ts.replace(':', '-').replace('T', '-')}-001.json"
        path.write_text(json.dumps({
            "ts":         ts,
            "session_id": session_id,
            "prompt":     prompt,
            "drained":    False,
        }))

    def _seed_dxm_event(self, session_id: str, evt: str, tool_name: str = "",
                         ts_unix: float = 0):
        f = self.dxm / f"events-{session_id}.jsonl"
        rec = {"ts_unix": ts_unix, "session_id": session_id, "evt_type": evt}
        if tool_name:
            rec["tool_name"] = tool_name
        with f.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")

    def test_reports_miss_when_prompt_matched_no_skill_loaded(self):
        self._add_skill("alpha-skill", 'Triggers on "alpha-trigger".')
        sid = "sess-miss"
        self._seed_inbox_prompt(sid, "use alpha-trigger now",
                                  "2026-05-17T08:00:00Z")
        self._seed_dxm_event(sid, "UserPromptSubmit", ts_unix=1747465200)
        # NO Skill load follows
        r = self._run("from-dxm", "--session", sid, "--json")
        data = json.loads(r.stdout)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["misses"][0]["skill"], "alpha-skill")
        self.assertFalse(data["misses"][0]["any_skill_loaded_after"])

    def test_skill_loaded_after_prompt_marks_loaded(self):
        self._add_skill("beta-skill", 'Triggers on "beta-trigger".')
        sid = "sess-loaded"
        # ISO "2026-05-17T08:00:00Z" = 1779004800 UTC. Skill load 10s later.
        self._seed_inbox_prompt(sid, "use beta-trigger now",
                                  "2026-05-17T08:00:00Z")
        self._seed_dxm_event(sid, "PreToolUse", tool_name="Skill",
                              ts_unix=1779004810)
        r = self._run("from-dxm", "--session", sid, "--json")
        data = json.loads(r.stdout)
        # Still recorded as a miss candidate, but flag indicates a load happened
        self.assertEqual(data["count"], 1)
        self.assertTrue(data["misses"][0]["any_skill_loaded_after"])

    def test_no_matching_prompts_returns_zero(self):
        self._add_skill("any-skill", 'Triggers on "totally-unrelated".')
        sid = "sess-clean"
        self._seed_inbox_prompt(sid, "do something completely different",
                                  "2026-05-17T08:00:00Z")
        r = self._run("from-dxm", "--session", sid, "--json")
        data = json.loads(r.stdout)
        self.assertEqual(data["count"], 0)

    def test_no_session_returns_error_no_crash(self):
        # No session-id supplied + no cwd discovery → graceful empty
        r = self._run("from-dxm", "--json")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data["misses"], [])

    def test_text_output_format(self):
        self._add_skill("text-skill", 'Triggers on "text-tag".')
        sid = "sess-text"
        self._seed_inbox_prompt(sid, "use text-tag here",
                                  "2026-05-17T08:00:00Z")
        r = self._run("from-dxm", "--session", sid)
        self.assertIn("text-skill", r.stdout)
        self.assertIn("matched: text-tag", r.stdout)


class TestRealCatalogParses(unittest.TestCase):
    """Smoke test against the REAL skills/ — confirms the parser
    doesn't crash on any production SKILL.md."""

    def test_real_index_completes(self):
        # No env override → uses default skills/ dir
        env = os.environ.copy()
        env.pop("KAIZEN_SKILL_SUGGEST_ROOT", None)
        r = subprocess.run(
            [sys.executable, str(_SCRIPT), "list", "--json"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        # We have 87 SKILL.md files; at minimum some must have triggers
        with_triggers = [s for s in data["skills"] if s["triggers"]]
        self.assertGreater(len(with_triggers), 5,
                            "expected at least 5 production skills with quoted triggers")


if __name__ == "__main__":
    unittest.main()
