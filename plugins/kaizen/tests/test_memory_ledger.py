"""Tests for kaizen-memory-ledger — catalog + status + flow verbs.

The ledger is observability-only over the declarative manifest at
skills/memory-ledger/domain/memory-surfaces.yaml. v1 scope:
  - catalog: print every declared surface as a typed envelope
  - status: sample each surface on disk; flag missing
  - flow:   render the continuity-of-session flow phase-by-phase

Tests use --json for envelope stability; human-readable output is
out of scope here (smoke covers it)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_LEDGER_PY = _KZ / "scripts" / "memory_ledger" / "memory_ledger.py"
_MANIFEST = _KZ / "skills" / "memory-ledger" / "domain" / "memory-surfaces.yaml"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_LEDGER_PY), *args],
        capture_output=True, text=True, timeout=30,
    )


class TestManifestLoads(unittest.TestCase):
    """The yaml manifest is authoritative — it must load + have shape."""

    def test_manifest_file_exists(self):
        self.assertTrue(_MANIFEST.is_file(),
                        f"memory-surfaces.yaml missing at {_MANIFEST}")

    def test_manifest_has_surfaces_and_flow(self):
        import yaml
        m = yaml.safe_load(_MANIFEST.read_text(encoding="utf-8"))
        self.assertIn("surfaces", m)
        self.assertIn("continuity_flow", m)
        self.assertGreater(len(m["surfaces"]), 0)

    def test_every_surface_has_required_fields(self):
        import yaml
        m = yaml.safe_load(_MANIFEST.read_text(encoding="utf-8"))
        required = {"id", "name", "owner_feature", "scope", "path",
                    "auto_load", "role"}
        for s in m["surfaces"]:
            missing = required - set(s.keys())
            self.assertFalse(missing,
                             f"surface {s.get('id','?')} missing fields {missing}")
            self.assertIn(s["scope"], ("project", "global"),
                          f"surface {s['id']} has invalid scope {s['scope']}")


class TestCatalogVerb(unittest.TestCase):
    """`catalog --json` prints every declared surface as an envelope."""

    def test_catalog_returns_zero_with_surfaces(self):
        r = _run("catalog", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        env = json.loads(r.stdout)
        self.assertIn("surfaces", env)
        self.assertGreater(len(env["surfaces"]), 0)

    def test_catalog_envelope_per_surface_has_core_fields(self):
        r = _run("catalog", "--json")
        env = json.loads(r.stdout)
        for s in env["surfaces"]:
            for key in ("id", "owner_feature", "scope", "path", "auto_load"):
                self.assertIn(key, s, f"surface envelope missing {key}: {s}")

    def test_catalog_counts_summary(self):
        r = _run("catalog", "--json")
        env = json.loads(r.stdout)
        self.assertIn("counts", env)
        self.assertIn("by_scope", env["counts"])
        # both scopes should have at least one entry given the current manifest
        self.assertGreater(env["counts"]["by_scope"]["project"], 0)
        self.assertGreater(env["counts"]["by_scope"]["global"], 0)


class TestFlowVerb(unittest.TestCase):
    """`flow --json` renders the continuity phases."""

    def test_flow_returns_phases(self):
        r = _run("flow", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        env = json.loads(r.stdout)
        self.assertIn("phases", env)
        phase_names = {p["phase"] for p in env["phases"]}
        # Every kaizen session walks these — locked baseline
        for expected in ("session_start", "orientation", "mid_work",
                          "end_of_session", "between_sessions"):
            self.assertIn(expected, phase_names)


class TestStatusVerb(unittest.TestCase):
    """`status --json` samples each surface; missing-on-disk = warn."""

    def test_status_envelope_has_findings_and_summary(self):
        r = _run("status", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        env = json.loads(r.stdout)
        self.assertIn("findings", env)
        self.assertIn("summary", env)
        self.assertIn("present", env["summary"])
        self.assertIn("missing", env["summary"])

    def test_status_findings_carry_id_and_severity(self):
        r = _run("status", "--json")
        env = json.loads(r.stdout)
        for f in env["findings"]:
            self.assertIn("id", f)
            self.assertIn("severity", f)
            self.assertIn(f["severity"], ("info", "warn", "red"))


class TestDisableKnob(unittest.TestCase):
    """KAIZEN_MEMORY_LEDGER_DISABLE=1 short-circuits every verb."""

    def test_disable_knob_returns_zero_silently(self):
        env = {**os.environ, "KAIZEN_MEMORY_LEDGER_DISABLE": "1"}
        r = subprocess.run(
            [sys.executable, str(_LEDGER_PY), "catalog", "--json"],
            capture_output=True, text=True, timeout=10, env=env,
        )
        self.assertEqual(r.returncode, 0)


class TestHelp(unittest.TestCase):
    def test_help_works(self):
        r = _run("--help")
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
