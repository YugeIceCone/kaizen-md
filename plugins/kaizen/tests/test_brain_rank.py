"""Tests for brain_rank.py — score-based Top Beliefs auto-ranker.

Port of upstream remember-md/remember/tests/promote.test.js. Covers:
- score / filter_candidates / rank_and_take pure functions
- effective_thresholds (bootstrap mode)
- find_beliefs (walks Notes/, filters by type=belief)
- render_top_beliefs_section / write_top_beliefs (section replace)
- compute_deltas (promoted / demoted diff)
- load_evolution_config (kaizen path: $KAIZEN_BRAIN_DIR/evolution.json)
- run() end-to-end

Sandboxed via KAIZEN_BRAIN_DIR — no production brain touched.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_KZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_KZ / "scripts/brain"))
sys.path.insert(0, str(_KZ / "scripts"))  # for evolution_log
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))

import brain_rank as br  # noqa: E402


_PERSONA_WITH_TOP = """---
created: 2026-05-10
tags: [persona]
---

# Persona

## Mission

- Role: tester

## Directives

- **No deletions.** See [[Notes/pref-no-deletions]].

## Top Beliefs

1. [[Notes/pref-old.md]] — conf=0.90 sources=3 freshness=stable
2. [[Notes/pref-also-old.md]] — conf=0.88 sources=2 freshness=stable

## Evidence Log

- [2026-05-10] First evidence.
"""


def _write_belief(notes_dir: Path, slug: str, *, conf: float, sources: int,
                  freshness: str = "stable") -> Path:
    fm_lines = [
        "---",
        f"name: {slug}",
        f"description: belief desc for {slug}",
        "type: belief",
        f"confidence: {conf}",
        f"sources_count: {sources}",
        f"freshness: {freshness}",
        "---",
        "",
        f"# {slug}",
        "",
        "body",
    ]
    p = notes_dir / f"{slug}.md"
    p.write_text("\n".join(fm_lines), encoding="utf-8")
    return p


def _write_non_belief(notes_dir: Path, slug: str, type_: str = "world-fact") -> Path:
    fm_lines = [
        "---",
        f"name: {slug}",
        f"type: {type_}",
        "---",
        "",
        f"# {slug}",
    ]
    p = notes_dir / f"{slug}.md"
    p.write_text("\n".join(fm_lines), encoding="utf-8")
    return p


class TestScore(unittest.TestCase):
    """score(rec) = confidence * log(sources_count + 1). Mirrors upstream."""

    def test_score_proportional_to_confidence(self):
        a = br.score({"confidence": 0.5, "sources_count": 4})
        b = br.score({"confidence": 1.0, "sources_count": 4})
        self.assertAlmostEqual(b, 2 * a, places=5)

    def test_score_increases_with_sources(self):
        a = br.score({"confidence": 0.8, "sources_count": 1})
        b = br.score({"confidence": 0.8, "sources_count": 10})
        self.assertGreater(b, a)

    def test_score_zero_sources_is_zero(self):
        """log(0 + 1) = 0 → score = 0. Prevents NaN on log(0)."""
        s = br.score({"confidence": 1.0, "sources_count": 0})
        self.assertEqual(s, 0.0)


class TestFilterCandidates(unittest.TestCase):
    def setUp(self):
        self.thresholds = {
            "promotion_confidence": 0.85,
            "promotion_sources": 5,
        }

    def test_filters_low_confidence(self):
        beliefs = [
            {"confidence": 0.80, "sources_count": 5, "freshness": "stable"},
            {"confidence": 0.90, "sources_count": 5, "freshness": "stable"},
        ]
        out = br.filter_candidates(beliefs, self.thresholds)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["confidence"], 0.90)

    def test_filters_low_sources(self):
        beliefs = [
            {"confidence": 0.90, "sources_count": 4, "freshness": "stable"},
            {"confidence": 0.90, "sources_count": 5, "freshness": "stable"},
        ]
        out = br.filter_candidates(beliefs, self.thresholds)
        self.assertEqual(len(out), 1)

    def test_filters_ineligible_freshness(self):
        beliefs = [
            {"confidence": 0.95, "sources_count": 5, "freshness": "stale"},
            {"confidence": 0.95, "sources_count": 5, "freshness": "contradicted"},
            {"confidence": 0.95, "sources_count": 5, "freshness": "stable"},
            {"confidence": 0.95, "sources_count": 5, "freshness": "strengthening"},
        ]
        out = br.filter_candidates(beliefs, self.thresholds)
        self.assertEqual(len(out), 2,
            "only stable + strengthening should pass; stale + contradicted out")


class TestRankAndTake(unittest.TestCase):
    def test_sorts_by_score_desc(self):
        cands = [
            {"path": "a", "confidence": 0.85, "sources_count": 5, "freshness": "stable"},
            {"path": "b", "confidence": 0.95, "sources_count": 5, "freshness": "stable"},
            {"path": "c", "confidence": 0.90, "sources_count": 10, "freshness": "stable"},
        ]
        out = br.rank_and_take(cands, 3)
        # c has highest score (0.90 * log(11) ≈ 2.16) vs b (0.95 * log(6) ≈ 1.70)
        self.assertEqual(out[0]["path"], "c")
        self.assertEqual(out[1]["path"], "b")
        self.assertEqual(out[2]["path"], "a")

    def test_truncates_to_n(self):
        cands = [
            {"path": f"p{i}", "confidence": 0.9, "sources_count": 5, "freshness": "stable"}
            for i in range(20)
        ]
        out = br.rank_and_take(cands, 5)
        self.assertEqual(len(out), 5)


class TestEffectiveThresholds(unittest.TestCase):
    """Bootstrap mode: relaxed thresholds when beliefs_count < 20.

    Mirrors upstream promote.js::effectiveThresholds. Bootstrap takes the
    more-permissive value per-field so a user who relaxed thresholds
    keeps their setting."""

    def setUp(self):
        self.cfg = {
            "thresholds": dict(br.DEFAULT_THRESHOLDS),
            "auto_promote": True,
            "bootstrap": True,
        }

    def test_bootstrap_active_under_threshold(self):
        eff, boot = br.effective_thresholds(beliefs_count=5, config=self.cfg)
        self.assertTrue(boot)
        self.assertEqual(eff["promotion_confidence"], 0.7)
        self.assertEqual(eff["promotion_sources"], 1)

    def test_bootstrap_inactive_at_threshold(self):
        """beliefs_count >= bootstrap_max_beliefs (20) → normal mode."""
        eff, boot = br.effective_thresholds(beliefs_count=20, config=self.cfg)
        self.assertFalse(boot)
        self.assertEqual(eff["promotion_confidence"], 0.85)
        self.assertEqual(eff["promotion_sources"], 5)

    def test_bootstrap_disabled_explicitly(self):
        self.cfg["bootstrap"] = False
        eff, boot = br.effective_thresholds(beliefs_count=5, config=self.cfg)
        self.assertFalse(boot)
        self.assertEqual(eff["promotion_confidence"], 0.85)

    def test_bootstrap_keeps_user_more_permissive(self):
        """User explicitly set confidence=0.6 — bootstrap (0.7) shouldn't
        make it stricter. Bootstrap is for the COLD-START case, never a
        ceiling on user-relaxed values."""
        self.cfg["thresholds"]["promotion_confidence"] = 0.6
        eff, boot = br.effective_thresholds(beliefs_count=5, config=self.cfg)
        self.assertTrue(boot)
        self.assertEqual(eff["promotion_confidence"], 0.6,
            "user's 0.6 must win against bootstrap's 0.7")


class TestFindBeliefs(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name)
        self.notes = self.brain / "Notes"
        self.notes.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_returns_only_beliefs(self):
        _write_belief(self.notes, "pref-a", conf=0.9, sources=3)
        _write_belief(self.notes, "pref-b", conf=0.7, sources=2)
        _write_non_belief(self.notes, "fact-c", type_="world-fact")
        _write_non_belief(self.notes, "obs-d", type_="observation")
        out = br.find_beliefs(self.brain)
        self.assertEqual(len(out), 2)
        paths = {b["path"] for b in out}
        self.assertEqual(paths, {"Notes/pref-a.md", "Notes/pref-b.md"})

    def test_skips_beliefs_without_confidence(self):
        p = self.notes / "broken.md"
        p.write_text("---\nname: broken\ntype: belief\n---\nbody", encoding="utf-8")
        out = br.find_beliefs(self.brain)
        self.assertEqual(out, [])

    def test_returns_empty_when_no_notes_dir(self):
        empty_brain = Path(self._tmp.name) / "empty"
        empty_brain.mkdir()
        self.assertEqual(br.find_beliefs(empty_brain), [])

    def test_record_shape(self):
        _write_belief(self.notes, "pref-x", conf=0.92, sources=4,
                      freshness="strengthening")
        out = br.find_beliefs(self.brain)
        self.assertEqual(len(out), 1)
        r = out[0]
        self.assertEqual(r["path"], "Notes/pref-x.md")
        self.assertEqual(r["title"], "pref-x")
        self.assertAlmostEqual(r["confidence"], 0.92)
        self.assertEqual(r["sources_count"], 4)
        self.assertEqual(r["freshness"], "strengthening")


class TestRenderTopBeliefsSection(unittest.TestCase):
    def test_empty_renders_placeholder(self):
        out = br.render_top_beliefs_section([], beliefs_count=3)
        self.assertIn("## Top Beliefs", out)
        self.assertIn("None yet", out)
        self.assertIn("3 belief", out)

    def test_empty_with_bootstrap_includes_mode_marker(self):
        out = br.render_top_beliefs_section([], bootstrap=True, beliefs_count=2)
        self.assertIn("bootstrap mode", out)

    def test_renders_ranked_entries(self):
        top = [
            {"path": "Notes/pref-a.md", "confidence": 0.92, "sources_count": 5,
             "freshness": "stable"},
            {"path": "Notes/pref-b.md", "confidence": 0.88, "sources_count": 3,
             "freshness": "strengthening"},
        ]
        out = br.render_top_beliefs_section(top)
        self.assertIn("1. [[Notes/pref-a.md]] — conf=0.92 sources=5 freshness=stable", out)
        self.assertIn("2. [[Notes/pref-b.md]] — conf=0.88 sources=3 freshness=strengthening", out)


class TestWriteTopBeliefs(unittest.TestCase):
    """write_top_beliefs REPLACES the section; demoted entries disappear."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name)
        self.persona = self.brain / "Persona.md"
        self.persona.write_text(_PERSONA_WITH_TOP, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_replaces_section_not_appends(self):
        new_top = [
            {"path": "Notes/pref-new.md", "confidence": 0.95, "sources_count": 6,
             "freshness": "stable"},
        ]
        br.write_top_beliefs(self.persona, new_top)
        text = self.persona.read_text()
        # Old entries are GONE
        self.assertNotIn("pref-old.md", text)
        self.assertNotIn("pref-also-old.md", text)
        # New entry present
        self.assertIn("[[Notes/pref-new.md]]", text)

    def test_preserves_other_sections(self):
        new_top = [
            {"path": "Notes/pref-new.md", "confidence": 0.95, "sources_count": 6,
             "freshness": "stable"},
        ]
        br.write_top_beliefs(self.persona, new_top)
        text = self.persona.read_text()
        self.assertIn("## Mission", text)
        self.assertIn("## Directives", text)
        self.assertIn("## Evidence Log", text)
        self.assertIn("First evidence", text)

    def test_appends_section_when_missing(self):
        # Strip the Top Beliefs section + content up to Evidence Log
        no_top = _PERSONA_WITH_TOP.replace(
            """## Top Beliefs

1. [[Notes/pref-old.md]] — conf=0.90 sources=3 freshness=stable
2. [[Notes/pref-also-old.md]] — conf=0.88 sources=2 freshness=stable

""", "")
        self.persona.write_text(no_top, encoding="utf-8")
        br.write_top_beliefs(self.persona, [
            {"path": "Notes/pref-x.md", "confidence": 0.9, "sources_count": 5,
             "freshness": "stable"},
        ])
        text = self.persona.read_text()
        self.assertIn("## Top Beliefs", text)
        self.assertIn("[[Notes/pref-x.md]]", text)


class TestReadCurrentTopBeliefs(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.persona = Path(self._tmp.name) / "Persona.md"
        self.persona.write_text(_PERSONA_WITH_TOP, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_extracts_links_only_from_top_section(self):
        out = br.read_current_top_beliefs(self.persona)
        self.assertEqual(out, ["Notes/pref-old.md", "Notes/pref-also-old.md"])
        # The link from Directives section is NOT included
        self.assertNotIn("Notes/pref-no-deletions", out)

    def test_returns_empty_when_persona_missing(self):
        missing = Path(self._tmp.name) / "nope.md"
        self.assertEqual(br.read_current_top_beliefs(missing), [])


class TestComputeDeltas(unittest.TestCase):
    def test_promoted_and_demoted(self):
        current = ["Notes/old-a.md", "Notes/keep.md"]
        top = [
            {"path": "Notes/keep.md", "confidence": 0.9, "sources_count": 5},
            {"path": "Notes/new-b.md", "confidence": 0.95, "sources_count": 7},
        ]
        out = br.compute_deltas(current, top)
        self.assertEqual([p["path"] for p in out["promoted"]], ["Notes/new-b.md"])
        self.assertEqual(out["demoted"], ["Notes/old-a.md"])


class TestLoadEvolutionConfig(unittest.TestCase):
    """User overrides via $KAIZEN_EVOLUTION_CONFIG (kaizen path, not XDG)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_env = os.environ.get("KAIZEN_EVOLUTION_CONFIG")

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("KAIZEN_EVOLUTION_CONFIG", None)
        else:
            os.environ["KAIZEN_EVOLUTION_CONFIG"] = self._old_env
        self._tmp.cleanup()

    def test_missing_file_returns_defaults(self):
        os.environ["KAIZEN_EVOLUTION_CONFIG"] = str(Path(self._tmp.name) / "nope.json")
        cfg = br.load_evolution_config()
        self.assertEqual(cfg["thresholds"], br.DEFAULT_THRESHOLDS)
        self.assertTrue(cfg["auto_promote"])
        self.assertTrue(cfg["bootstrap"])

    def test_user_overrides_merge_onto_defaults(self):
        cfg_path = Path(self._tmp.name) / "evolution.json"
        cfg_path.write_text(json.dumps({
            "thresholds": {"promotion_confidence": 0.75},
            "auto_promote": False,
        }))
        os.environ["KAIZEN_EVOLUTION_CONFIG"] = str(cfg_path)
        cfg = br.load_evolution_config()
        self.assertEqual(cfg["thresholds"]["promotion_confidence"], 0.75)
        # Defaults for non-overridden fields preserved
        self.assertEqual(cfg["thresholds"]["promotion_sources"], 5)
        self.assertFalse(cfg["auto_promote"])

    def test_malformed_json_falls_back_to_defaults(self):
        cfg_path = Path(self._tmp.name) / "evolution.json"
        cfg_path.write_text("not json")
        os.environ["KAIZEN_EVOLUTION_CONFIG"] = str(cfg_path)
        cfg = br.load_evolution_config()
        self.assertEqual(cfg["thresholds"], br.DEFAULT_THRESHOLDS)


class TestRunEndToEnd(unittest.TestCase):
    """run() — find + filter + rank + write + log."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name)
        (self.brain / "Notes").mkdir()
        self.persona = self.brain / "Persona.md"
        self.persona.write_text(_PERSONA_WITH_TOP, encoding="utf-8")
        # Sandbox the evolution log
        self.log = Path(self._tmp.name) / "evolution.log"

    def tearDown(self):
        self._tmp.cleanup()

    def test_dry_run_does_not_write_persona(self):
        _write_belief(self.brain / "Notes", "pref-new", conf=0.95, sources=8)
        before = self.persona.read_text()
        result = br.run(brain=self.brain, dry_run=True)
        self.assertFalse(result["wrote"])
        # Persona unchanged
        self.assertEqual(self.persona.read_text(), before)

    def test_apply_rewrites_top_section_with_ranked_beliefs(self):
        # Bootstrap mode: only 3 beliefs → thresholds drop to conf>=0.7, sources>=1
        _write_belief(self.brain / "Notes", "pref-strong",
                      conf=0.95, sources=10)
        _write_belief(self.brain / "Notes", "pref-mid",
                      conf=0.80, sources=3)
        _write_belief(self.brain / "Notes", "pref-weak",
                      conf=0.75, sources=1)
        result = br.run(brain=self.brain, dry_run=False, log_path=self.log)
        self.assertTrue(result["wrote"])
        self.assertTrue(result["bootstrap"])
        text = self.persona.read_text()
        # All 3 land (bootstrap thresholds: conf>=0.7, sources>=1)
        self.assertIn("[[Notes/pref-strong.md]]", text)
        self.assertIn("[[Notes/pref-mid.md]]", text)
        self.assertIn("[[Notes/pref-weak.md]]", text)
        # Pref-strong has highest score → rank 1
        strong_idx = text.index("[[Notes/pref-strong.md]]")
        mid_idx = text.index("[[Notes/pref-mid.md]]")
        weak_idx = text.index("[[Notes/pref-weak.md]]")
        self.assertLess(strong_idx, mid_idx)
        self.assertLess(mid_idx, weak_idx)
        # Old beliefs from the seed Persona are gone
        self.assertNotIn("pref-old.md", text)

    def test_apply_logs_promote_demote_events(self):
        _write_belief(self.brain / "Notes", "pref-new",
                      conf=0.95, sources=10)
        result = br.run(brain=self.brain, dry_run=False, log_path=self.log)
        self.assertTrue(result["wrote"])
        log_text = self.log.read_text()
        # New belief promoted; both seed beliefs demoted
        self.assertIn("PROMOTE", log_text)
        self.assertIn("Notes/pref-new.md", log_text)
        self.assertIn("DEMOTE", log_text)
        self.assertIn("Notes/pref-old.md", log_text)

    def test_apply_auto_promote_false_skips_write(self):
        _write_belief(self.brain / "Notes", "pref-new",
                      conf=0.95, sources=10)
        result = br.run(brain=self.brain, dry_run=False,
                        config_override={
                            "thresholds": br.DEFAULT_THRESHOLDS,
                            "auto_promote": False,
                            "bootstrap": True,
                        }, log_path=self.log)
        self.assertFalse(result["wrote"])

    def test_disable_env_knob_short_circuits_main(self):
        """KAIZEN_BRAIN_RANK_DISABLE=1 → exit 0 without doing anything."""
        with mock.patch.dict(os.environ, {"KAIZEN_BRAIN_RANK_DISABLE": "1",
                                          "KAIZEN_BRAIN_DIR": str(self.brain)}):
            rc = br.main([])
        self.assertEqual(rc, 0)
        # Persona unchanged (Top Beliefs section still has the seed entries)
        self.assertIn("pref-old.md", self.persona.read_text())


class TestBeliefStats(unittest.TestCase):
    """belief_stats(): distribution over freshness / sources / confidence.

    Extracted from self_improving/brain_validator::cmd_belief_stats during
    the consolidation arc."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name)
        (self.brain / "Notes").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_empty_brain_returns_zero_count(self):
        stats = br.belief_stats(self.brain)
        self.assertEqual(stats["count"], 0)
        self.assertIsNone(stats["confidence"])

    def test_distribution_shape(self):
        _write_belief(self.brain / "Notes", "pref-a", conf=0.95, sources=8, freshness="stable")
        _write_belief(self.brain / "Notes", "pref-b", conf=0.80, sources=3, freshness="stable")
        _write_belief(self.brain / "Notes", "pref-c", conf=0.70, sources=1, freshness="strengthening")
        stats = br.belief_stats(self.brain)
        self.assertEqual(stats["count"], 3)
        self.assertEqual(stats["freshness"]["stable"], 2)
        self.assertEqual(stats["freshness"]["strengthening"], 1)
        self.assertEqual(stats["sources_distribution"][8], 1)
        self.assertEqual(stats["sources_distribution"][3], 1)
        self.assertEqual(stats["sources_distribution"][1], 1)
        self.assertAlmostEqual(stats["confidence"]["min"], 0.70)
        self.assertAlmostEqual(stats["confidence"]["max"], 0.95)
        self.assertAlmostEqual(stats["confidence"]["avg"], (0.95 + 0.80 + 0.70) / 3)


if __name__ == "__main__":
    unittest.main()
