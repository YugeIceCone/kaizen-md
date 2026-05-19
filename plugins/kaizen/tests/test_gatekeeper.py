"""Tests for skills/workflow/scripts/gatekeeper.py and
skills/efficient-tool-use/application/etu_scan.py — the unified gate."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GATEKEEPER = _REPO_ROOT / "plugins/kaizen/skills/workflow/scripts/gatekeeper.py"
_ETU_SCAN = _REPO_ROOT / "plugins/kaizen/skills/efficient-tool-use/application/etu_scan.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestEtuScan(unittest.TestCase):
    def setUp(self):
        self.etu = _load("etu_scan_test", _ETU_SCAN)

    def test_scan_detects_known_anti_pattern(self):
        """A bash file with a known anti-pattern (find /) is flagged."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.sh"
            p.write_text("#!/bin/bash\nfind / -name foo\n")
            findings = self.etu.scan_files([p])
            ids = {f.pattern_id for f in findings}
            self.assertIn("find-from-root", ids)

    def test_scan_clean_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "good.sh"
            p.write_text("#!/bin/bash\nset -euo pipefail\necho hello\n")
            findings = self.etu.scan_files([p])
            self.assertEqual(findings, [])

    def test_scan_ignores_non_existent_file(self):
        # Should not crash on a missing path
        findings = self.etu.scan_files([Path("/nonexistent/file.sh")])
        self.assertEqual(findings, [])

    def test_finding_includes_severity_and_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "eval.sh"
            p.write_text('#!/bin/bash\neval "$user_input"\n')
            findings = self.etu.scan_files([p])
            self.assertTrue(any(f.severity == "error" for f in findings))
            for f in findings:
                self.assertTrue(f.replacement, "replacement must be non-empty")


class TestGatekeeperAggregator(unittest.TestCase):
    def setUp(self):
        self.gk = _load("gatekeeper_test", _GATEKEEPER)

    def test_list_subgates(self):
        # 14 sub-gates: + claude-md-bloat (Phase L — CLAUDE.md
        # post-@import expansion size).
        self.assertEqual(
            set(self.gk.SUB_GATES.keys()),
            {"iron-laws", "etu", "karpathy", "validator",
             "token-bloat", "code-to-test-coverage", "schema-coverage",
             "name-quality-coverage", "frontmatter-coverage",
             "slash-collision", "menu-lint", "auto-load-budget",
             "brain-drift", "claude-md-bloat"},
        )

    def test_norm_sev_maps_to_canonical(self):
        self.assertEqual(self.gk._norm_sev("hard"), "error")
        self.assertEqual(self.gk._norm_sev("soft"), "warn")
        self.assertEqual(self.gk._norm_sev("info"), "info")
        self.assertEqual(self.gk._norm_sev("unknown"), "warn")  # safe default

    def test_verdict_with_no_findings_is_green(self):
        v = self.gk.Verdict(overall="green", findings=[], durations_ms={}, counts={})
        self.assertEqual(v.overall, "green")

    def test_render_text_includes_header_and_findings(self):
        f = self.gk.GateFinding(
            gate="etu", severity="error", rule_id="find-from-root",
            message="bad pattern", file="bad.sh", line=2,
        )
        v = self.gk.Verdict(
            overall="red", findings=[f],
            durations_ms={"etu": 5}, counts={"error": 1},
        )
        out = self.gk.render_text(v)
        self.assertIn("RED", out)
        self.assertIn("find-from-root", out)
        self.assertIn("bad.sh:2", out)

    def test_render_json_roundtrip(self):
        """render_json emits the canonical envelope (see
        assets/schemas/tool-output.schema.json) — `verdict` at top
        level, `findings` inside `data`."""
        import json
        f = self.gk.GateFinding(
            gate="iron-laws", severity="warn", rule_id="lazy-heavy-deps",
            message="msg", file="x.py",
        )
        v = self.gk.Verdict(
            overall="yellow", findings=[f],
            durations_ms={"iron-laws": 10}, counts={"warn": 1},
        )
        data = json.loads(self.gk.render_json(v))
        # Canonical envelope keys
        self.assertEqual(data["verdict"], "yellow")
        self.assertEqual(data["counts"], {"warn": 1})
        self.assertEqual(data["kaizen"]["tool"], "kaizen-gatekeeper")
        self.assertEqual(data["kaizen"]["schema_version"], 1)
        # Per-tool payload nested under `data`
        self.assertEqual(data["data"]["findings"][0]["gate"], "iron-laws")

    def test_gate_etu_returns_list(self):
        """The etu sub-gate returns a list (possibly empty), never crashes."""
        out = self.gk._gate_etu("staged", _REPO_ROOT)
        self.assertIsInstance(out, list)


class TestAutoLoadBudgetGate(unittest.TestCase):
    """The auto-load-budget gate warns when ~/.claude/.kaizen/auto-load.md
    exceeds KAIZEN_AUTO_LOAD_BUDGET (default 5120). Never blocks — auto-
    load is daemon-managed advisory content; an oversized file just
    means the daemon's truncation logic didn't fire (real fix is to
    raise the budget or reduce top_n).

    Sandbox: KAIZEN_AUTO_LOAD_PATH points the gate at a tempfile.
    """

    def setUp(self):
        self.gk = _load("gatekeeper_test_aulb", _GATEKEEPER)

    def test_no_file_returns_no_findings(self):
        from unittest.mock import patch
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "auto-load.md"
            with patch.dict(os.environ,
                            {"KAIZEN_AUTO_LOAD_PATH": str(target)}):
                findings = self.gk._gate_auto_load_budget(
                    "staged", _REPO_ROOT)
        self.assertEqual(findings, [])

    def test_within_budget_returns_no_findings(self):
        from unittest.mock import patch
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "auto-load.md"
            target.write_text("a" * 100, encoding="utf-8")
            with patch.dict(os.environ,
                            {"KAIZEN_AUTO_LOAD_PATH": str(target),
                             "KAIZEN_AUTO_LOAD_BUDGET": "5120"}):
                findings = self.gk._gate_auto_load_budget(
                    "staged", _REPO_ROOT)
        self.assertEqual(findings, [])

    def test_over_budget_emits_warn(self):
        from unittest.mock import patch
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "auto-load.md"
            target.write_text("a" * 8000, encoding="utf-8")
            with patch.dict(os.environ,
                            {"KAIZEN_AUTO_LOAD_PATH": str(target),
                             "KAIZEN_AUTO_LOAD_BUDGET": "5120"}):
                findings = self.gk._gate_auto_load_budget(
                    "staged", _REPO_ROOT)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "warn")
        self.assertEqual(findings[0].gate, "auto-load-budget")
        # Message includes actual and budget for diagnosis
        self.assertIn("8000", findings[0].message)
        self.assertIn("5120", findings[0].message)


class TestBrainDriftGate(unittest.TestCase):
    """The brain-drift gate detects 4 classes of stale state across the
    auto-recording flow:

    1. MEMORY.md count mismatch (sibling files vs index entries)
    2. auto-load.md stale (older mtime than Persona.md)
    3. gates/<slug>.md orphan (directive no longer in Persona)
    4. Pin references a Note that doesn't exist

    Advisory only — these are repair-by-next-tick conditions, not
    commit-blockers. Sandboxed via existing env knobs.
    """

    def setUp(self):
        self.gk = _load("gatekeeper_test_drift", _GATEKEEPER)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.brain = self.root / "brain"
        self.brain.mkdir()
        (self.brain / "Persona.md").write_text(
            "# Persona\n\n"
            "## Directives\n\n"
            "- **No deletions.** See [[Notes/pref-no-deletions]].\n\n"
            "## Top Beliefs\n\n"
            "1. [[Notes/pref-no-deletions.md]] — conf=0.98\n",
            encoding="utf-8",
        )
        (self.brain / "Notes").mkdir()
        (self.brain / "Notes" / "pref-no-deletions.md").write_text("ok")

        self.memory = self.root / "memory"
        self.memory.mkdir()
        self.auto_load = self.root / "auto-load.md"
        self.gates = self.root / "gates"
        self.gates.mkdir()
        self.pins = self.root / "pins.json"

    def tearDown(self):
        self._tmp.cleanup()

    def _env(self):
        # Point the expected-import-not-fired check at a non-existent
        # CLAUDE.md so it skips silently (this fixture doesn't seed one).
        return {
            "KAIZEN_BRAIN_DIR":             str(self.brain),
            "KAIZEN_BETTER_MEMORY_DIR":     str(self.memory),
            "KAIZEN_AUTO_LOAD_PATH":        str(self.auto_load),
            "KAIZEN_GATES_DIR":             str(self.gates),
            "KAIZEN_AUTO_LOAD_PINS_PATH":   str(self.pins),
            "KAIZEN_CLAUDE_MD_PATH":        str(self.root / "absent-CLAUDE.md"),
            "KAIZEN_INSTRUCTIONS_LOADED_LOG": str(self.root / "absent.jsonl"),
        }

    def test_clean_state_no_findings(self):
        # Seed minimal valid state
        import time
        self.auto_load.write_text("# auto-load\n")
        # Persona.md older than auto-load.md
        persona = self.brain / "Persona.md"
        os.utime(persona, (1000, 1000))
        os.utime(self.auto_load, (2000, 2000))
        (self.memory / "MEMORY.md").write_text("- empty\n")
        # No gate orphans, no pins
        from unittest.mock import patch
        with patch.dict(os.environ, self._env()):
            findings = self.gk._gate_brain_drift("staged", _REPO_ROOT)
        self.assertEqual(findings, [])

    def test_detects_stale_auto_load(self):
        """Persona mtime > auto-load mtime → auto-load is stale."""
        self.auto_load.write_text("# auto-load\n")
        persona = self.brain / "Persona.md"
        # Make Persona newer than auto-load
        os.utime(self.auto_load, (1000, 1000))
        os.utime(persona, (2000, 2000))
        (self.memory / "MEMORY.md").write_text("- empty\n")
        from unittest.mock import patch
        with patch.dict(os.environ, self._env()):
            findings = self.gk._gate_brain_drift("staged", _REPO_ROOT)
        kinds = [f.rule_id for f in findings]
        self.assertIn("auto-load-stale", kinds)

    def test_detects_memory_index_drift(self):
        """MEMORY.md index entry count != sibling *.md count."""
        # 2 siblings, but MEMORY.md indexes 0
        (self.memory / "project_a.md").write_text("body")
        (self.memory / "project_b.md").write_text("body")
        (self.memory / "MEMORY.md").write_text("# empty\n")
        # Persona newer is fine (we're not testing that here)
        self.auto_load.write_text("ok")
        from unittest.mock import patch
        with patch.dict(os.environ, self._env()):
            findings = self.gk._gate_brain_drift("staged", _REPO_ROOT)
        kinds = [f.rule_id for f in findings]
        self.assertIn("memory-index-drift", kinds)

    def test_detects_orphan_gate_files(self):
        """Gate file for a slug not in current Persona directives."""
        (self.gates / "pref-no-deletions.md").write_text("ok")  # current
        (self.gates / "pref-obsolete.md").write_text("ok")      # orphan
        self.auto_load.write_text("ok")
        (self.memory / "MEMORY.md").write_text("- empty\n")
        from unittest.mock import patch
        with patch.dict(os.environ, self._env()):
            findings = self.gk._gate_brain_drift("staged", _REPO_ROOT)
        kinds = [f.rule_id for f in findings]
        self.assertIn("gate-orphan", kinds)
        msgs = " ".join(f.message for f in findings)
        self.assertIn("pref-obsolete", msgs)

    def test_detects_pin_to_missing_note(self):
        """Pin references a Note file that doesn't exist."""
        import json
        self.pins.write_text(json.dumps([
            "Notes/pref-no-deletions",   # exists
            "Notes/pref-does-not-exist", # missing
        ]))
        self.auto_load.write_text("ok")
        (self.memory / "MEMORY.md").write_text("- empty\n")
        from unittest.mock import patch
        with patch.dict(os.environ, self._env()):
            findings = self.gk._gate_brain_drift("staged", _REPO_ROOT)
        kinds = [f.rule_id for f in findings]
        self.assertIn("pin-missing-note", kinds)
        msgs = " ".join(f.message for f in findings)
        self.assertIn("pref-does-not-exist", msgs)


class TestExpectedImportNotFired(unittest.TestCase):
    """brain-drift gate enrichment: detect CLAUDE.md @imports that
    never showed up in the InstructionsLoaded jsonl audit.

    A common silent failure: user adds `@~/some/path.md` to CLAUDE.md
    but the file is missing / declined / path-mistyped. Claude Code
    tolerates the bad import (leaves it as literal text) — no error
    surfaces. The hook never fires for that path, so the jsonl shows
    its absence. This rule catches it pre-commit.
    """

    def setUp(self):
        self.gk = _load("gatekeeper_test_eif", _GATEKEEPER)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.claude_md = self.root / "CLAUDE.md"
        self.jsonl = self.root / "loaded.jsonl"
        self.brain = self.root / "brain"
        self.brain.mkdir()
        # Minimal Persona so other rules don't trip
        (self.brain / "Persona.md").write_text(
            "# Persona\n\n## Directives\n\n- **X.** See [[Notes/x]].\n",
            encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _env(self):
        # Sandbox every drift surface so we test ONLY the new rule.
        return {
            "KAIZEN_CLAUDE_MD_PATH":           str(self.claude_md),
            "KAIZEN_INSTRUCTIONS_LOADED_LOG":  str(self.jsonl),
            "KAIZEN_BRAIN_DIR":                str(self.brain),
            "KAIZEN_BETTER_MEMORY_DIR":        str(self.root / "memory"),
            "KAIZEN_AUTO_LOAD_PATH":           str(self.root / "auto-load.md"),
            "KAIZEN_GATES_DIR":                str(self.root / "gates"),
            "KAIZEN_AUTO_LOAD_PINS_PATH":      str(self.root / "pins.json"),
        }

    def test_no_claude_md_no_findings(self):
        # File absent → rule silent
        from unittest.mock import patch
        with patch.dict(os.environ, self._env()):
            findings = self.gk._gate_brain_drift("staged", _REPO_ROOT)
        kinds = [f.rule_id for f in findings]
        self.assertNotIn("expected-import-not-fired", kinds)

    def test_no_imports_no_findings(self):
        self.claude_md.write_text("# CLAUDE\n\nno imports here\n")
        self.jsonl.write_text("")  # empty audit
        from unittest.mock import patch
        with patch.dict(os.environ, self._env()):
            findings = self.gk._gate_brain_drift("staged", _REPO_ROOT)
        kinds = [f.rule_id for f in findings]
        self.assertNotIn("expected-import-not-fired", kinds)

    def test_all_imports_fired_no_findings(self):
        target = self.root / "imported.md"
        target.write_text("imported content")
        self.claude_md.write_text(f"# CLAUDE\n\n@{target}\n")
        # Audit shows the import fired
        import json as _json
        self.jsonl.write_text(_json.dumps({
            "ts": "2026-05-19T00:00:00Z",
            "file_path": str(target),
            "memory_type": "User",
            "load_reason": "include",
        }) + "\n")
        from unittest.mock import patch
        with patch.dict(os.environ, self._env()):
            findings = self.gk._gate_brain_drift("staged", _REPO_ROOT)
        kinds = [f.rule_id for f in findings]
        self.assertNotIn("expected-import-not-fired", kinds)

    def test_missing_import_surfaces_warn(self):
        # CLAUDE.md @imports an existing file that the audit never recorded
        target = self.root / "missed.md"
        target.write_text("imported content")
        self.claude_md.write_text(f"# CLAUDE\n\n@{target}\n")
        self.jsonl.write_text("")  # nothing fired
        from unittest.mock import patch
        with patch.dict(os.environ, self._env()):
            findings = self.gk._gate_brain_drift("staged", _REPO_ROOT)
        kinds = [f.rule_id for f in findings]
        self.assertIn("expected-import-not-fired", kinds)
        msg = " ".join(f.message for f in findings)
        self.assertIn("missed.md", msg)

    def test_missing_import_target_not_flagged(self):
        """A typo-path @import (file doesn't exist) is a DIFFERENT
        problem (not load-fired-vs-not). This rule only flags paths
        that DO exist on disk but the audit didn't see fire."""
        self.claude_md.write_text("# CLAUDE\n\n@/does/not/exist.md\n")
        self.jsonl.write_text("")
        from unittest.mock import patch
        with patch.dict(os.environ, self._env()):
            findings = self.gk._gate_brain_drift("staged", _REPO_ROOT)
        kinds = [f.rule_id for f in findings]
        # Should NOT surface — different concern (missing file, not
        # missing load event).
        self.assertNotIn("expected-import-not-fired", kinds)


class TestGatekeeperCollisionResistance(unittest.TestCase):
    """Regression — both iron-laws and efficient-tool-use ship a
    `_loader.py`; the gatekeeper must load each without collision."""

    def test_etu_loads_when_iron_laws_already_loaded(self):
        gk = _load("gatekeeper_col_test", _GATEKEEPER)
        # Force iron-laws to load first (its sys.path hack would normally
        # poison _loader for whoever loads next).
        _ = gk._gate_iron_laws("staged", _REPO_ROOT)
        # ETU should still work.
        out = gk._gate_etu("staged", _REPO_ROOT)
        # Must not return an "import-error" finding.
        for f in out:
            self.assertNotEqual(
                f.rule_id, "import-error",
                f"etu_scan failed to load post iron-laws: {f.message}",
            )


if __name__ == "__main__":
    unittest.main()


class TestGateFrontmatterSplit(unittest.TestCase):
    """Quality-check brainstorm #1 + #2 — _gate_frontmatter must split
    its single warn-finding into TWO distinct findings:
      - name-mismatch  → severity=error (hard-gate, blocks commit)
      - weak-routing   → severity=warn  (soft-gate, advisory)
    """

    def setUp(self):
        self.gk = _load("gatekeeper_split_test", _GATEKEEPER)

    def test_no_gaps_returns_empty(self):
        out = self.gk._classify_frontmatter_findings([
            {"skill": "a", "name_match": True, "trigger_count": 5},
        ])
        self.assertEqual(out, [])

    def test_name_mismatch_emits_error(self):
        out = self.gk._classify_frontmatter_findings([
            {"skill": "analyze", "name_match": False,
             "name_field": "change-analyzing", "trigger_count": 5},
        ])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].severity, "error",
                          "name-mismatch must be ERROR — blocks commit")
        self.assertEqual(out[0].rule_id, "name-mismatch")
        # Sample name appears in the message so the user can find it
        self.assertIn("analyze", out[0].message)

    def test_weak_routing_alone_emits_warn(self):
        out = self.gk._classify_frontmatter_findings([
            {"skill": "brain", "name_match": True, "trigger_count": 1},
        ])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].severity, "warn",
                          "weak-routing alone is advisory")
        self.assertEqual(out[0].rule_id, "weak-routing")

    def test_both_kinds_emit_two_findings(self):
        out = self.gk._classify_frontmatter_findings([
            {"skill": "a", "name_match": False, "name_field": "wrong",
             "trigger_count": 5},
            {"skill": "b", "name_match": True, "trigger_count": 0},
        ])
        sevs = sorted(f.severity for f in out)
        self.assertEqual(sevs, ["error", "warn"])

    def test_name_mismatch_dominates_weak_routing_per_skill(self):
        """A single skill with BOTH problems surfaces in the
        name-mismatch (error) bucket — fixing the name often fixes
        the routing concern too."""
        out = self.gk._classify_frontmatter_findings([
            {"skill": "x", "name_match": False, "name_field": "wrong",
             "trigger_count": 0},
        ])
        # Two findings: one error (name), one warn (routing)
        sevs = sorted(f.severity for f in out)
        self.assertEqual(sevs, ["error", "warn"])
