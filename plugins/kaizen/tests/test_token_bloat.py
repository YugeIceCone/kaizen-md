"""Tests for token_bloat — the everything-Claude-sees bloat scanner."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "skills/workflow/scripts/token_bloat.py"


def _run(*args, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True, text=True, timeout=10,
        env={**os.environ, **(env or {})},
    )


class TestScriptHealth(unittest.TestCase):
    def test_script_present_and_parses(self):
        self.assertTrue(_SCRIPT.is_file())
        with open(_SCRIPT, "r") as f:
            compile(f.read(), str(_SCRIPT), "exec")

    def test_no_subcommand_exits_nonzero(self):
        r = _run()
        self.assertNotEqual(r.returncode, 0)


class TestScanAgainstRealPlugin(unittest.TestCase):
    """End-to-end: scan the real plugin, sanity-check the report."""

    def test_scan_text_runs_clean(self):
        r = _run("scan")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("kaizen-token-bloat", r.stdout)

    def test_scan_json_emits_findings_list(self):
        r = _run("scan", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertIn("findings", data)
        self.assertIn("total", data)
        self.assertIn("high", data)
        self.assertIn("medium", data)
        # The real plugin has at least one bloat finding (session-intake heredoc, big SKILLs)
        self.assertGreater(data["total"], 0)


class TestYamlTemplateScanner(unittest.TestCase):
    """Synthetic yaml fixtures to exercise the reason_template scanner."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Build minimal plugin layout
        (self.tmp / "skills/x/domain").mkdir(parents=True)
        (self.tmp / "skills").mkdir(exist_ok=True)
        (self.tmp / "commands").mkdir()
        (self.tmp / "hooks/claude").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _run_scan(self) -> dict:
        """Patch _plugin_root and call scan_all."""
        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        if "token_bloat" in sys.modules:
            del sys.modules["token_bloat"]
        import token_bloat
        findings = token_bloat.scan_all(root=self.tmp)
        return findings

    def test_short_template_not_flagged(self):
        (self.tmp / "skills/x/domain/cfg.yaml").write_text(
            "version: 1\n"
            "on_fire:\n"
            "  reason_template: |\n"
            "    one-line warning\n"
        )
        findings = self._run_scan()
        self.assertEqual(findings, [])

    def test_long_template_flagged_high(self):
        body = "\n".join(f"    line {i}" for i in range(20))
        (self.tmp / "skills/x/domain/cfg.yaml").write_text(
            "version: 1\n"
            "on_fire:\n"
            "  reason_template: |\n"
            f"{body}\n"
        )
        findings = self._run_scan()
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual(f["kind"], "yaml-template")
        self.assertEqual(f["severity"], "high")
        self.assertEqual(f["field"], "reason_template")
        self.assertGreater(f["tokens"], 0)


class TestCacheSurfacing(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.kaizen_dir = self.tmp / "kaizen"
        self.kaizen_dir.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_surface_empty_when_no_cache(self):
        r = _run("surface", env={"KAIZEN_DIR": str(self.kaizen_dir)})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")

    def test_scan_cache_then_surface_emits_one_line(self):
        # Scan against real plugin with --cache, then surface
        env = {"KAIZEN_DIR": str(self.kaizen_dir)}
        r1 = _run("scan", "--cache", env=env)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        cache = self.kaizen_dir / "token-bloat-findings.json"
        self.assertTrue(cache.is_file())

        r2 = _run("surface", env=env)
        self.assertEqual(r2.returncode, 0)
        # Real plugin has findings, so surface emits a one-liner
        self.assertIn("kaizen-token-bloat", r2.stdout)
        # Single line (one trailing newline)
        self.assertEqual(r2.stdout.count("\n"), 1,
                          f"surface should emit ONE line, got: {r2.stdout!r}")

    def test_surface_stale_cache_returns_empty(self):
        """When cache is older than TTL, surface emits nothing."""
        env = {"KAIZEN_DIR": str(self.kaizen_dir),
                "KAIZEN_TOKEN_BLOAT_TTL_HOURS": "0"}  # TTL = 0 → always stale
        _run("scan", "--cache", env=env)
        r = _run("surface", env=env)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")

    def test_surface_below_notice_threshold_returns_empty(self):
        """Findings exist but waste < threshold → no notice."""
        env = {"KAIZEN_DIR": str(self.kaizen_dir),
                "KAIZEN_BLOAT_NOTICE_THRESHOLD": "999999"}  # absurdly high
        _run("scan", "--cache", env=env)
        r = _run("surface", env=env)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")

    def test_surface_above_threshold_shows_waste_and_worst(self):
        """Real plugin findings should produce a substantive notice."""
        env = {"KAIZEN_DIR": str(self.kaizen_dir),
                "KAIZEN_BLOAT_NOTICE_THRESHOLD": "100"}  # easy to clear
        _run("scan", "--cache", env=env)
        r = _run("surface", env=env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("wasted tok", r.stdout)
        self.assertIn("top-cost:", r.stdout)  # cumulative-aware
        self.assertIn("q=", r.stdout)


class TestReportSubcommand(unittest.TestCase):
    def test_report_without_cache_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"KAIZEN_DIR": tmp}
            r = _run("report", env=env)
            self.assertEqual(r.returncode, 1)


class TestHookArtifacts(unittest.TestCase):
    """The two auto-invocation hooks must be present + executable."""

    def test_sessionend_hook_present(self):
        p = _KZ_DIR / "hooks/claude/sessionend-token-bloat.sh"
        self.assertTrue(p.is_file())
        self.assertTrue(os.access(p, os.X_OK))

    def test_sessionstart_hook_present(self):
        p = _KZ_DIR / "hooks/claude/session-start-token-bloat.sh"
        self.assertTrue(p.is_file())
        self.assertTrue(os.access(p, os.X_OK))

    def test_bin_wrapper_present(self):
        p = _KZ_DIR / "bin/kaizen-token-bloat"
        self.assertTrue(p.is_file())
        self.assertTrue(os.access(p, os.X_OK))


class TestQualityScore(unittest.TestCase):
    """Quality scoring — sanity-check the heuristic without claiming
    absolute precision. Tests pin RELATIVE ordering, not absolute scores."""

    def setUp(self):
        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        if "token_bloat" in sys.modules:
            del sys.modules["token_bloat"]
        import token_bloat
        self.q = token_bloat.quality_score

    def test_empty_body_is_100(self):
        score, hint = self.q("")
        self.assertEqual(score, 100)
        self.assertEqual(hint, "empty")

    def test_uniform_prose_high_quality(self):
        score, _ = self.q("Trim the template. Use kaizen-handoff to wrap up.\n")
        self.assertGreaterEqual(score, 90)

    def test_step_recipe_penalised(self):
        text = ("Do the thing:\n"
                "1. First step\n"
                "2. Second step\n"
                "3. Third step\n"
                "4. Fourth step\n")
        score, hint = self.q(text)
        self.assertLess(score, 90)
        self.assertIn("recipe", hint)

    def test_boilerplate_penalised(self):
        text = ("In order to do this, please note that as you can see "
                "it is important to note that we should proceed.")
        score, _ = self.q(text)
        self.assertLess(score, 90)

    def test_reference_bonus(self):
        plain = "Trim the template."
        with_ref = "Trim the template. See `auto_handoff.py` for details."
        s1, _ = self.q(plain)
        s2, _ = self.q(with_ref)
        self.assertGreaterEqual(s2, s1)

    def test_high_quality_outranks_low_in_waste_sort(self):
        """When two findings have similar tokens, the lower-quality one
        should rank first (more waste). scan_all does the sort."""
        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        if "token_bloat" in sys.modules:
            del sys.modules["token_bloat"]
        import token_bloat as tb

        # Two synthetic findings
        f_low_q  = {"severity": "high", "kind": "x", "path": "a", "field": "b",
                     "lines": 10, "tokens": 100, "quality": 20}
        f_high_q = {"severity": "high", "kind": "x", "path": "c", "field": "d",
                     "lines": 10, "tokens": 100, "quality": 90}
        findings = [f_high_q, f_low_q]
        # Mimic scan_all's sort key
        sev_rank = {"high": 0, "medium": 1, "low": 2}
        findings.sort(key=lambda f: (sev_rank.get(f["severity"], 9),
                                       -(f["tokens"] * (100 - f.get("quality", 50)))))
        self.assertEqual(findings[0]["path"], "a")  # low quality first


class TestFindingsHaveQualityFields(unittest.TestCase):
    """After scoring wire-up, every finding dict must carry quality + hint."""

    def test_yaml_finding_has_quality_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "skills/x/domain").mkdir(parents=True)
            body = "\n".join(f"    line {i}" for i in range(20))
            (tmp / "skills/x/domain/cfg.yaml").write_text(
                "version: 1\n"
                "on_fire:\n"
                "  reason_template: |\n"
                f"{body}\n"
            )
            sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
            if "token_bloat" in sys.modules:
                del sys.modules["token_bloat"]
            import token_bloat
            findings = token_bloat.scan_all(root=tmp)
            self.assertEqual(len(findings), 1)
            f = findings[0]
            self.assertIn("quality", f)
            self.assertIn("quality_hint", f)
            self.assertIsInstance(f["quality"], int)
            self.assertTrue(0 <= f["quality"] <= 100)


class TestExpandedScanners(unittest.TestCase):
    """Phase-2 horizontal scanners: agents/*.md + frontmatter description."""

    def setUp(self):
        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        if "token_bloat" in sys.modules:
            del sys.modules["token_bloat"]
        import token_bloat as tb
        self.tb = tb
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "skills").mkdir()
        (self.root / "agents").mkdir()
        (self.root / "commands").mkdir()
        (self.root / "hooks/claude").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_agent_md_flagged_when_oversized(self):
        body = "\n".join(f"line {i}" for i in range(300))
        (self.root / "agents/big.md").write_text(body)
        f = self.tb.scan_all(root=self.root)
        agent = [x for x in f if x["kind"] == "agent-md"]
        self.assertEqual(len(agent), 1)
        self.assertEqual(agent[0]["severity"], "medium")
        self.assertEqual(agent[0]["sensitivity"], "instruction")

    def test_frontmatter_desc_oversize_flagged(self):
        desc = "A " * 400  # ~800 chars
        (self.root / "skills/x").mkdir()
        (self.root / "skills/x/SKILL.md").write_text(
            f"---\nname: x\ndescription: {desc}\n---\nbody\n")
        f = self.tb.scan_all(root=self.root)
        fm = [x for x in f if x["kind"] == "frontmatter-desc"]
        self.assertEqual(len(fm), 1)
        self.assertEqual(fm[0]["field"], "description")
        self.assertEqual(fm[0]["sensitivity"], "system")

    def test_short_frontmatter_desc_not_flagged(self):
        (self.root / "skills/x").mkdir()
        (self.root / "skills/x/SKILL.md").write_text(
            "---\nname: x\ndescription: short and tight\n---\nbody\n")
        f = self.tb.scan_all(root=self.root)
        self.assertEqual([x for x in f if x["kind"] == "frontmatter-desc"], [])


class TestSensitivityTier(unittest.TestCase):
    """LLMLingua-inspired classification per finding."""

    def setUp(self):
        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        if "token_bloat" in sys.modules:
            del sys.modules["token_bloat"]
        import token_bloat as tb
        self.tier = tb.sensitivity_tier

    def test_yaml_template_is_instruction(self):
        self.assertEqual(self.tier({"kind": "yaml-template", "path": "x"}),
                          "instruction")

    def test_hook_heredoc_is_instruction(self):
        self.assertEqual(self.tier({"kind": "hook-heredoc", "path": "x"}),
                          "instruction")

    def test_agent_md_is_instruction(self):
        self.assertEqual(self.tier({"kind": "agent-md", "path": "x"}),
                          "instruction")

    def test_frontmatter_is_system(self):
        self.assertEqual(self.tier({"kind": "frontmatter-desc", "path": "x"}),
                          "system")

    def test_skill_md_is_context(self):
        self.assertEqual(self.tier({"kind": "skill-md", "path": "x"}),
                          "context")


class TestDxmFireWeighting(unittest.TestCase):
    """Fire-count weighting: cumulative_tokens = tokens × max(1, fires)."""

    def setUp(self):
        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        if "token_bloat" in sys.modules:
            del sys.modules["token_bloat"]
        import token_bloat as tb
        self.tb = tb
        self._tmp = tempfile.TemporaryDirectory()
        self.dxm = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_count_dxm_fires_empty_dir(self):
        env_path = self.dxm
        os.environ["KAIZEN_DXM_DIR"] = str(env_path)
        try:
            self.tb._FIRE_CACHE.clear()
            self.assertEqual(self.tb.count_dxm_fires("SessionStart"), 0)
        finally:
            os.environ.pop("KAIZEN_DXM_DIR", None)

    def test_count_dxm_fires_counts_lines(self):
        (self.dxm / "events-abc.jsonl").write_text(
            '{"evt_type":"SessionStart"}\n'
            '{"evt_type":"PreToolUse"}\n'
            '{"evt_type":"SessionStart"}\n'
        )
        os.environ["KAIZEN_DXM_DIR"] = str(self.dxm)
        try:
            self.tb._FIRE_CACHE.clear()
            self.assertEqual(self.tb.count_dxm_fires("SessionStart"), 2)
            self.assertEqual(self.tb.count_dxm_fires("PreToolUse"), 1)
        finally:
            os.environ.pop("KAIZEN_DXM_DIR", None)

    def test_estimate_fire_count_maps_hook_prefix_to_evt(self):
        (self.dxm / "events-abc.jsonl").write_text(
            '{"evt_type":"SessionStart"}\n' * 5
        )
        os.environ["KAIZEN_DXM_DIR"] = str(self.dxm)
        try:
            self.tb._FIRE_CACHE.clear()
            f = {"path": "hooks/claude/session-start-token-bloat.sh",
                 "kind": "hook-heredoc"}
            self.assertEqual(self.tb.estimate_fire_count(f), 5)
        finally:
            os.environ.pop("KAIZEN_DXM_DIR", None)

    def test_cumulative_tokens_scales_with_fires(self):
        """A 200-tok template fired 50× should report cumulative=10000."""
        (self.dxm / "events-abc.jsonl").write_text(
            '{"evt_type":"SessionStart"}\n' * 50
        )
        os.environ["KAIZEN_DXM_DIR"] = str(self.dxm)
        try:
            self.tb._FIRE_CACHE.clear()
            root = Path(self._tmp.name) / "plugin"
            (root / "skills").mkdir(parents=True)
            (root / "hooks/claude").mkdir(parents=True)
            body = "body=\"\"\"" + "\n".join(f"line {i}" for i in range(25)) + "\"\"\""
            (root / "hooks/claude/session-start-x.sh").write_text(body)
            findings = self.tb.scan_all(root=root)
            self.assertEqual(len(findings), 1)
            f = findings[0]
            self.assertEqual(f["fire_count"], 50)
            self.assertEqual(f["cumulative_tokens"], f["tokens"] * 50)
        finally:
            os.environ.pop("KAIZEN_DXM_DIR", None)


class TestSessionStateFile(unittest.TestCase):
    """Per-scan session state file with one short line per finding."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.state_file = self.tmp / "session-bloat.md"

    def tearDown(self):
        self._tmp.cleanup()

    def test_scan_cache_writes_session_state(self):
        env = {"KAIZEN_DIR": str(self.tmp),
                "KAIZEN_BLOAT_SESSION_FILE": str(self.state_file)}
        r = _run("scan", "--cache", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.state_file.is_file())

    def test_session_state_format_includes_line_ranges(self):
        env = {"KAIZEN_DIR": str(self.tmp),
                "KAIZEN_BLOAT_SESSION_FILE": str(self.state_file)}
        _run("scan", "--cache", env=env)
        text = self.state_file.read_text()
        # Header lines
        self.assertIn("# kaizen token-bloat — session state", text)
        self.assertIn("# scanned:", text)
        self.assertIn("# findings:", text)
        # At least one entry with the `path:start-end` shape
        import re
        m = re.search(r"`[^`]+:\d+-\d+`", text)
        self.assertIsNotNone(m, f"no `path:start-end` line in:\n{text[:500]}")

    def test_session_subcommand_prints_path(self):
        env = {"KAIZEN_BLOAT_SESSION_FILE": str(self.state_file)}
        r = _run("session", env=env)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), str(self.state_file))


class TestProjectAwarePath(unittest.TestCase):
    """Default location: $KAIZEN_DIR/token-bloat/<project-slug>/{session.md,history.jsonl}.
    User-global storage + per-project slugging."""

    def setUp(self):
        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        if "token_bloat" in sys.modules:
            del sys.modules["token_bloat"]
        import token_bloat as tb
        self.tb = tb
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Build a fake project with .git so _project_root resolves to it
        self.proj = self.tmp / "fake-project"
        (self.proj / ".git").mkdir(parents=True)
        # KAIZEN_DIR points at our temp home so paths land in tmp
        self._orig_env: dict[str, str | None] = {}
        for k in ("KAIZEN_DIR", "KAIZEN_BLOAT_SESSION_FILE",
                   "KAIZEN_BLOAT_HISTORY_FILE"):
            self._orig_env[k] = os.environ.get(k)
            os.environ.pop(k, None)
        os.environ["KAIZEN_DIR"] = str(self.tmp / "kaizen")
        self._cwd0 = os.getcwd()
        os.chdir(self.proj)

    def tearDown(self):
        os.chdir(self._cwd0)
        for k, v in self._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def test_session_path_uses_kaizen_dir_and_slug(self):
        # Re-import to pick up env
        if "token_bloat" in sys.modules:
            del sys.modules["token_bloat"]
        import token_bloat as tb
        p = tb._session_state_path()
        # Under $KAIZEN_DIR/token-bloat/<slug>/session.md
        self.assertEqual(p.parent.parent, Path(os.environ["KAIZEN_DIR"]) / "token-bloat")
        self.assertEqual(p.name, "session.md")
        # Slug encodes the project root
        slug = p.parent.name
        self.assertIn("fake-project", slug)

    def test_history_path_lives_beside_snapshot(self):
        if "token_bloat" in sys.modules:
            del sys.modules["token_bloat"]
        import token_bloat as tb
        snap = tb._session_state_path()
        hist = tb._session_history_path()
        self.assertEqual(snap.parent, hist.parent)
        self.assertEqual(hist.name, "history.jsonl")

    def test_session_subcommand_returns_user_global_path(self):
        r = _run("session")  # no env overrides
        self.assertEqual(r.returncode, 0)
        out = r.stdout.strip()
        self.assertIn(os.environ["KAIZEN_DIR"], out)
        self.assertIn("token-bloat", out)

    def test_explicit_session_file_env_still_wins(self):
        """KAIZEN_BLOAT_SESSION_FILE override keeps working."""
        custom = self.tmp / "custom-session.md"
        env = {"KAIZEN_DIR": str(self.tmp / "kaizen"),
                "KAIZEN_BLOAT_SESSION_FILE": str(custom)}
        r = _run("session", env=env)
        self.assertEqual(r.stdout.strip(), str(custom))


class TestSessionStateSurvival(unittest.TestCase):
    """Continuity + survival: snapshot is atomic; history JSONL grows;
    snapshot regenerable from history if lost."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.snap = self.tmp / "session-bloat.md"
        self.hist = self.tmp / "session-bloat.history.jsonl"
        self.env = {
            "KAIZEN_DIR":                str(self.tmp),
            "KAIZEN_BLOAT_SESSION_FILE": str(self.snap),
        }

    def tearDown(self):
        self._tmp.cleanup()

    def test_history_jsonl_appended_each_scan(self):
        _run("scan", "--cache", env=self.env)
        self.assertTrue(self.hist.is_file())
        # Each scan adds ONE line
        line_count_1 = sum(1 for _ in self.hist.open())
        _run("scan", "--cache", env=self.env)
        line_count_2 = sum(1 for _ in self.hist.open())
        self.assertEqual(line_count_2, line_count_1 + 1)

    def test_history_entry_includes_findings(self):
        _run("scan", "--cache", env=self.env)
        with self.hist.open() as f:
            entry = json.loads(f.readline())
        for k in ("scanned_at", "total", "high", "medium",
                   "waste_tokens", "cumulative_tokens", "findings"):
            self.assertIn(k, entry)

    def test_history_subcommand_prints_path(self):
        r = _run("history", env=self.env)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), str(self.hist))

    def test_restore_regenerates_snapshot_from_history(self):
        _run("scan", "--cache", env=self.env)
        prior = self.snap.read_text()
        # Snapshot lost (disk corruption / accidental delete)
        self.snap.unlink()
        self.assertFalse(self.snap.exists())
        # Restore from history
        r = _run("restore", env=self.env)
        self.assertEqual(r.returncode, 0)
        self.assertTrue(self.snap.is_file())
        # Content matches the prior snapshot byte-for-byte (rendered from
        # the same findings + scanned_at).
        self.assertEqual(self.snap.read_text(), prior)

    def test_restore_without_history_exits_1(self):
        r = _run("restore", env=self.env)
        self.assertEqual(r.returncode, 1)

    def test_snapshot_is_atomic_no_partial_file(self):
        """If atomic_write is used, the snapshot file is either fully
        old or fully new — never a half-written state with tempfile
        leftovers in the parent dir post-write."""
        _run("scan", "--cache", env=self.env)
        # No stray .part files left in the directory
        leftover = list(self.tmp.glob(".session-bloat.md.*.part"))
        self.assertEqual(leftover, [],
                          f"atomic_write left stray tempfiles: {leftover}")


class TestSplitPlan(unittest.TestCase):
    """Rubric-driven split-plan emitter — classifies SKILL.md sections."""

    def setUp(self):
        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        if "token_bloat" in sys.modules:
            del sys.modules["token_bloat"]
        import token_bloat as tb
        self.tb = tb

    def test_rubric_loads_with_known_keys(self):
        rubric = self.tb._load_split_rubric()
        self.assertIn("rules", rubric)
        self.assertGreater(len(rubric["rules"]), 0)
        # First rule should be the THEORY → extract pattern
        kinds = {r.get("kind") for r in rubric["rules"]}
        self.assertIn("theory", kinds)
        self.assertIn("iron-law", kinds)

    def test_classify_theory_heading_marks_extract(self):
        rubric = self.tb._load_split_rubric()
        section = {"heading": "PART 1 — THEORY (the why)", "lines": 200,
                    "body": "x" * 800, "start": 100, "end": 300, "level": 1}
        out = self.tb._classify_section(section, rubric)
        self.assertEqual(out["kind"], "theory")
        self.assertEqual(out["verdict"], "extract")
        self.assertIn("theory", out["extract_to"])

    def test_classify_iron_law_keeps_inline(self):
        rubric = self.tb._load_split_rubric()
        section = {"heading": "⚠ Iron Law — read in full", "lines": 8,
                    "body": "x" * 80, "start": 9, "end": 16, "level": 2}
        out = self.tb._classify_section(section, rubric)
        self.assertEqual(out["kind"], "iron-law")
        self.assertEqual(out["verdict"], "keep-inline")
        self.assertEqual(out["extract_to"], "")

    def test_classify_unknown_short_section(self):
        rubric = self.tb._load_split_rubric()
        section = {"heading": "Random heading", "lines": 5,
                    "body": "x" * 50, "start": 50, "end": 54, "level": 2}
        out = self.tb._classify_section(section, rubric)
        self.assertEqual(out["verdict"], "keep-inline")

    def test_build_split_plan_returns_schema_shape(self):
        # Run against onion-ddd-workflow (real plugin)
        plan = self.tb.build_split_plan("onion-ddd-workflow")
        for k in ("skill", "path", "current_lines", "current_tokens",
                   "estimated_tokens_saved", "candidates"):
            self.assertIn(k, plan)
        self.assertEqual(plan["skill"], "onion-ddd-workflow")
        self.assertIsInstance(plan["candidates"], list)

    def test_split_plan_subcommand_runs(self):
        r = _run("split-plan", "--skill", "onion-ddd-workflow")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("split-plan", r.stdout)

    def test_split_plan_json_emits_valid_json(self):
        r = _run("split-plan", "--skill", "onion-ddd-workflow", "--json")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data["skill"], "onion-ddd-workflow")
        self.assertIn("candidates", data)

    def test_scan_cache_appends_split_plans_to_session_md(self):
        """The session-state snapshot now includes the split-plans
        appendix automatically — no separate invocation required."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            snap = tmp / "session.md"
            env = {"KAIZEN_DIR": str(tmp),
                    "KAIZEN_BLOAT_SESSION_FILE": str(snap)}
            r = _run("scan", "--cache", env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            text = snap.read_text()
            self.assertIn("## Split plans", text)
            self.assertIn("split-plan:", text)

    def test_history_entry_carries_split_plans(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            snap = tmp / "session.md"
            env = {"KAIZEN_DIR": str(tmp),
                    "KAIZEN_BLOAT_SESSION_FILE": str(snap)}
            _run("scan", "--cache", env=env)
            hist = snap.with_suffix(".history.jsonl")
            with hist.open() as f:
                last = None
                for line in f:
                    if line.strip():
                        last = json.loads(line)
            self.assertIn("split_plans", last)
            self.assertIsInstance(last["split_plans"], list)

    def test_split_plan_all_oversized_runs(self):
        """Plan-all (no --skill) processes every SKILL.md > medium threshold."""
        r = _run("split-plan", "--json")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)


class TestArchiveAndSmartRead(unittest.TestCase):
    """Each scan archives the rendered snapshot to archive/<ts>.md and
    the `read` subcommand resolves `path:start-end` citations."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.snap = self.tmp / "session.md"
        self.env = {
            "KAIZEN_DIR":                str(self.tmp),
            "KAIZEN_BLOAT_SESSION_FILE": str(self.snap),
        }

    def tearDown(self):
        self._tmp.cleanup()

    def test_scan_writes_timestamped_archive(self):
        _run("scan", "--cache", env=self.env)
        archives = sorted((self.tmp / "archive").glob("*.md"))
        self.assertEqual(len(archives), 1)

    def test_two_scans_produce_two_archives(self):
        _run("scan", "--cache", env=self.env)
        import time; time.sleep(1.1)  # ensure timestamp granularity
        _run("scan", "--cache", env=self.env)
        archives = list((self.tmp / "archive").glob("*.md"))
        self.assertEqual(len(archives), 2)

    def test_snapshot_footer_links_to_archive(self):
        _run("scan", "--cache", env=self.env)
        text = self.snap.read_text()
        self.assertIn("# archived: archive/", text)
        self.assertIn("# history:  history.jsonl", text)

    def test_archives_subcommand_lists_them(self):
        _run("scan", "--cache", env=self.env)
        r = _run("archives", env=self.env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("archives", r.stdout)
        self.assertIn(".md", r.stdout)

    def test_archives_json_emits_list(self):
        _run("scan", "--cache", env=self.env)
        r = _run("archives", "--json", env=self.env)
        data = json.loads(r.stdout)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        for k in ("path", "name", "size", "mtime"):
            self.assertIn(k, data[0])


class TestSmartRead(unittest.TestCase):
    """smart_read / `read` subcommand — pure citation → snippet."""

    def setUp(self):
        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        if "token_bloat" in sys.modules:
            del sys.modules["token_bloat"]
        import token_bloat as tb
        self.tb = tb
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # Build a fixture file with known content
        self.fixture = self.root / "data.txt"
        self.fixture.write_text("\n".join(f"line {i}" for i in range(1, 11)))

    def tearDown(self):
        self._tmp.cleanup()

    def test_smart_read_range_returns_snippet(self):
        out = self.tb.smart_read("data.txt:3-5", root=self.root)
        self.assertTrue(out["ok"])
        self.assertIn("line 3", out["content"])
        self.assertIn("line 4", out["content"])
        self.assertIn("line 5", out["content"])
        # Line numbers prefixed
        self.assertIn("    3:", out["content"])

    def test_smart_read_single_line_works(self):
        out = self.tb.smart_read("data.txt:7", root=self.root)
        self.assertTrue(out["ok"])
        self.assertIn("line 7", out["content"])
        self.assertEqual(out["start"], 7)
        self.assertEqual(out["end"], 7)

    def test_smart_read_context_pads_above_and_below(self):
        out = self.tb.smart_read("data.txt:5", root=self.root, context_lines=2)
        # padded range = 3..7
        self.assertIn("line 3", out["content"])
        self.assertIn("line 7", out["content"])
        self.assertEqual(out["padded_start"], 3)
        self.assertEqual(out["padded_end"], 7)

    def test_smart_read_bad_citation_returns_error(self):
        out = self.tb.smart_read("not-a-valid-citation", root=self.root)
        self.assertFalse(out["ok"])
        self.assertIn("error", out)

    def test_smart_read_missing_file_returns_error(self):
        out = self.tb.smart_read("missing.txt:1-3", root=self.root)
        self.assertFalse(out["ok"])

    def test_read_cli_emits_snippet(self):
        cwd0 = os.getcwd()
        os.chdir(self.root)
        try:
            r = _run("read", "data.txt:2-4")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("line 2", r.stdout)
            self.assertIn("line 4", r.stdout)
        finally:
            os.chdir(cwd0)

    def test_read_cli_json_shape(self):
        cwd0 = os.getcwd()
        os.chdir(self.root)
        try:
            r = _run("read", "data.txt:2-4", "--json")
            data = json.loads(r.stdout)
            self.assertTrue(data["ok"])
            self.assertEqual(data["start"], 2)
            self.assertEqual(data["end"], 4)
        finally:
            os.chdir(cwd0)


class TestStaleEntryValidator(unittest.TestCase):
    """Stale / invalid finding detection + prune behavior."""

    def setUp(self):
        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        if "token_bloat" in sys.modules:
            del sys.modules["token_bloat"]
        import token_bloat as tb
        self.tb = tb
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _finding(self, path: str, start=1, end=100, lines=100) -> dict:
        return {
            "path": path, "start_line": start, "end_line": end, "lines": lines,
            "severity": "high", "kind": "skill-md",
        }

    def test_active_finding_when_file_unchanged(self):
        p = self.root / "x.md"
        p.write_text("\n".join(f"l{i}" for i in range(100)))
        self.assertEqual(
            self.tb.validate_finding(self._finding("x.md", end=100, lines=100),
                                      root=self.root),
            "active")

    def test_missing_when_file_gone(self):
        self.assertEqual(
            self.tb.validate_finding(self._finding("vanished.md"),
                                      root=self.root),
            "missing")

    def test_moved_when_range_exceeds_file(self):
        p = self.root / "shrunk.md"
        p.write_text("\n".join(f"l{i}" for i in range(40)))
        self.assertEqual(
            self.tb.validate_finding(
                self._finding("shrunk.md", end=100, lines=100),
                root=self.root),
            "moved")

    def test_resolved_when_file_shrunk_below_half(self):
        p = self.root / "trimmed.md"
        p.write_text("\n".join(f"l{i}" for i in range(20)))  # was 100, now 20
        self.assertEqual(
            self.tb.validate_finding(
                self._finding("trimmed.md", end=20, lines=100),
                root=self.root),
            "resolved")

    def test_partition_splits_buckets_correctly(self):
        p_active = self.root / "active.md"; p_active.write_text("x\n" * 100)
        p_trimmed = self.root / "trimmed.md"; p_trimmed.write_text("x\n" * 20)
        findings = [
            self._finding("active.md", end=100, lines=100),
            self._finding("missing.md"),
            self._finding("trimmed.md", end=20, lines=100),
        ]
        buckets = self.tb._validate_and_partition(findings, root=self.root)
        self.assertEqual(len(buckets["active"]), 1)
        self.assertEqual(len(buckets["missing"]), 1)
        self.assertEqual(len(buckets["resolved"]), 1)


class TestValidateCLI(unittest.TestCase):
    """CLI validate (read-only) + validate --prune (rewrites snapshot)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.snap = self.tmp / "session.md"
        self.env = {
            "KAIZEN_DIR":                str(self.tmp),
            "KAIZEN_BLOAT_SESSION_FILE": str(self.snap),
        }

    def tearDown(self):
        self._tmp.cleanup()

    def test_validate_with_no_history_exits_1(self):
        r = _run("validate", env=self.env)
        self.assertEqual(r.returncode, 1)

    def test_validate_active_after_fresh_scan(self):
        # Fresh scan against real plugin — every finding is active
        _run("scan", "--cache", env=self.env)
        r = _run("validate", env=self.env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("active", r.stdout)
        # No missing / moved / resolved expected on a fresh scan
        self.assertIn("0 missing", r.stdout)
        self.assertIn("0 resolved", r.stdout)

    def test_validate_prune_keeps_snapshot_only_with_active(self):
        """Synthetic case: history with mix of active+missing+resolved.
        --prune rewrites snapshot to drop missing/resolved, writes
        resolved.log for the audit trail."""
        _run("scan", "--cache", env=self.env)
        # Tamper with history: inject a missing finding alongside real ones
        hist = self.snap.with_suffix(".history.jsonl")
        with hist.open("r") as f:
            last = None
            for line in f:
                if line.strip():
                    last = json.loads(line)
        last["findings"].append({
            "path": "definitely-not-a-real-file.md",
            "start_line": 1, "end_line": 100, "lines": 100,
            "severity": "high", "kind": "skill-md",
        })
        # Append the tampered entry as the new "latest"
        with hist.open("a") as f:
            f.write(json.dumps(last) + "\n")

        before_count = len(last["findings"])
        r = _run("validate", "--prune", env=self.env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("pruned", r.stdout.lower())
        # Audit log written
        resolved_log = self.snap.parent / "resolved.log"
        self.assertTrue(resolved_log.is_file())
        # Snapshot regenerated with FEWER entries than tampered history
        snap_text = self.snap.read_text()
        for f_dict in last["findings"]:
            if f_dict["path"] == "definitely-not-a-real-file.md":
                self.assertNotIn("definitely-not-a-real-file.md", snap_text)


class TestLineRangePresence(unittest.TestCase):
    """Every finding must carry start_line + end_line so the session
    state file can render `path:start-end` jump targets."""

    def setUp(self):
        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        if "token_bloat" in sys.modules:
            del sys.modules["token_bloat"]
        import token_bloat as tb
        self.tb = tb

    def test_real_plugin_findings_all_have_line_ranges(self):
        findings = self.tb.scan_all()
        self.assertGreater(len(findings), 0)
        for f in findings:
            self.assertIn("start_line", f,
                          f"{f['path']}::{f['field']} missing start_line")
            self.assertIn("end_line", f,
                          f"{f['path']}::{f['field']} missing end_line")
            self.assertGreaterEqual(f["start_line"], 1)
            self.assertGreaterEqual(f["end_line"], f["start_line"])


class TestSkillBody(unittest.TestCase):
    def test_skill_md_present(self):
        p = _KZ_DIR / "skills/token-bloat/SKILL.md"
        self.assertTrue(p.is_file())

    def test_skill_lists_natural_lang_triggers(self):
        p = _KZ_DIR / "skills/token-bloat/SKILL.md"
        text = p.read_text()
        for trigger in ("token bloat", "scan for bloat", "what's bloated",
                         "find verbose templates"):
            self.assertIn(trigger, text,
                          f"SKILL.md missing trigger phrase {trigger!r}")


if __name__ == "__main__":
    unittest.main()
