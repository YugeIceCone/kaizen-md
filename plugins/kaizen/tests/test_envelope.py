"""Tests for the canonical tool-output envelope — every kaizen CLI
that supports `--json` must validate against
`assets/schemas/tool-output.schema.json`.

Regression guard: as new tools opt in to the envelope, add them to
`_RETROFIT_TOOLS` so a future change can't silently break the contract.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS = _REPO_ROOT / "plugins/kaizen/skills/workflow/scripts"
_SCHEMA = _REPO_ROOT / "plugins/kaizen/assets/schemas/tool-output.schema.json"
_ENVELOPE = _SCRIPTS / "_envelope.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


try:
    from jsonschema import Draft202012Validator, ValidationError
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False


# List of (subprocess args, expected verdict for clean state) tuples.
# `verdict=None` means "any verdict is fine" — the schema validates
# the SHAPE, not the value. Args run from REPO_ROOT.
_RETROFIT_TOOLS = [
    ("gatekeeper",      [str(_SCRIPTS / "gatekeeper.py"), "check", "--staged", "--json"]),
    ("surface validate", [str(_SCRIPTS / "surface.py"), "validate", "--json"]),
    ("surface list",    [str(_SCRIPTS / "surface.py"), "list", "--json"]),
    ("iron-laws check", [str(_SCRIPTS / "iron_laws.py"), "check", "--staged", "--json"]),
    ("iron-laws list",  [str(_SCRIPTS / "iron_laws.py"), "list", "--json"]),
    ("metrics session", [str(_SCRIPTS / "metrics.py"), "session", "--json"]),
    ("metrics top",     [str(_SCRIPTS / "metrics.py"), "top", "--json"]),
    ("metrics path",    [str(_SCRIPTS / "metrics.py"), "path"]),
    # roadmap_status needs a handoff file in the repo — skip from default
    # validation since not all repos have plans/. Manual smoke covered
    # the shape; re-enable here once a fixture is in place.
]


class TestEnvelopeHelper(unittest.TestCase):
    def setUp(self):
        self.env = _load("kaizen_env_test", _ENVELOPE)

    def test_wrap_minimal_produces_required_keys(self):
        out = self.env.wrap(tool="kaizen-test", data={"x": 1})
        self.assertEqual(out["kaizen"]["schema_version"], 1)
        self.assertEqual(out["kaizen"]["tool"], "kaizen-test")
        self.assertIn("plugin_version", out["kaizen"])
        self.assertEqual(out["data"], {"x": 1})

    def test_wrap_with_verdict_and_counts(self):
        out = self.env.wrap(
            tool="kaizen-test", data=[],
            verdict="green", counts={"error": 0, "warn": 2},
        )
        self.assertEqual(out["verdict"], "green")
        self.assertEqual(out["counts"], {"error": 0, "warn": 2})

    def test_render_deterministic_for_identical_input(self):
        a = self.env.wrap(tool="kaizen-test", data={"a": 1, "b": 2})
        b = self.env.wrap(tool="kaizen-test", data={"b": 2, "a": 1})
        # Same content, different insertion order — render() sorts keys
        # so output is byte-identical (reproducibility property).
        self.assertEqual(self.env.render(a), self.env.render(b))

    def test_render_omits_time_by_default(self):
        out = self.env.wrap(tool="kaizen-test", data={})
        self.assertNotIn("ran_at_utc", out["kaizen"])

    def test_render_includes_time_when_opted_in(self):
        out = self.env.wrap(tool="kaizen-test", data={}, include_time=True)
        self.assertIn("ran_at_utc", out["kaizen"])

    def test_argv_command_strips_absolute_path(self):
        out = self.env.wrap(
            tool="kaizen-test", data={},
            argv=["/abs/path/to/script.py", "--flag"],
        )
        # basename only — reproducible across machines
        self.assertEqual(out["kaizen"]["command"], "script.py --flag")


@unittest.skipUnless(_HAS_JSONSCHEMA, "jsonschema not installed")
class TestRetrofittedToolsValidate(unittest.TestCase):
    """Every retrofitted tool's --json output validates against the
    canonical envelope schema. Adding a new tool: append to
    _RETROFIT_TOOLS and the schema-validation will gate its shape."""

    def setUp(self):
        with _SCHEMA.open() as f:
            self.validator = Draft202012Validator(json.load(f))

    def _validate(self, name: str, cmd: list[str]):
        r = subprocess.run([sys.executable, *cmd],
                           cwd=_REPO_ROOT,
                           capture_output=True, text=True, timeout=30)
        # The tool may exit non-zero (red verdict) but should still
        # produce valid envelope JSON.
        out = r.stdout.strip()
        self.assertTrue(out, f"{name}: no stdout (stderr: {r.stderr[:200]})")
        try:
            doc = json.loads(out)
        except json.JSONDecodeError as e:
            self.fail(f"{name}: not valid JSON ({e}): {out[:200]}")
        errors = list(self.validator.iter_errors(doc))
        if errors:
            messages = "\n".join(f"  - {e.message} (at {list(e.absolute_path)})" for e in errors)
            self.fail(f"{name}: envelope-schema validation failed:\n{messages}")

    def test_all_retrofit_tools(self):
        for name, cmd in _RETROFIT_TOOLS:
            with self.subTest(tool=name):
                self._validate(name, cmd)


class TestReproducibility(unittest.TestCase):
    """Identical inputs must produce byte-identical outputs (no
    auto-timestamp in non-time fields, no random ids)."""

    def test_gatekeeper_json_byte_identical(self):
        cmd = [sys.executable, str(_SCRIPTS / "gatekeeper.py"),
               "check", "--staged", "--json"]
        # Two consecutive runs must agree
        r1 = subprocess.run(cmd, cwd=_REPO_ROOT, capture_output=True, text=True, timeout=15)
        r2 = subprocess.run(cmd, cwd=_REPO_ROOT, capture_output=True, text=True, timeout=15)
        # Strip duration_ms from comparison — it varies run-to-run by
        # nature. Everything else should be identical.
        def normalize(s: str) -> dict:
            d = json.loads(s)
            if "kaizen" in d and "duration_ms" in d["kaizen"]:
                d["kaizen"]["duration_ms"] = 0
            if "data" in d and "durations_ms" in d.get("data", {}):
                d["data"]["durations_ms"] = {k: 0 for k in d["data"]["durations_ms"]}
            return d
        self.assertEqual(normalize(r1.stdout), normalize(r2.stdout))


if __name__ == "__main__":
    unittest.main()
