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
_ENVELOPE = _REPO_ROOT / "plugins/kaizen/scripts/io/_envelope.py"


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
    ("gatekeeper",      [str(_REPO_ROOT / "plugins/kaizen/scripts/iron-laws/gatekeeper.py"), "check", "--staged", "--json"]),
    ("surface validate", [str(_REPO_ROOT / "plugins/kaizen/scripts/iron-laws/surface.py"), "validate", "--json"]),
    ("surface list",    [str(_REPO_ROOT / "plugins/kaizen/scripts/iron-laws/surface.py"), "list", "--json"]),
    ("iron-laws check", [str(_REPO_ROOT / "plugins/kaizen/scripts/iron-laws/iron_laws.py"), "check", "--staged", "--json"]),
    ("iron-laws list",  [str(_REPO_ROOT / "plugins/kaizen/scripts/iron-laws/iron_laws.py"), "list", "--json"]),
    ("metrics session", [str(_REPO_ROOT / "plugins/kaizen/scripts/observe/metrics.py"), "session", "--json"]),
    ("metrics top",     [str(_REPO_ROOT / "plugins/kaizen/scripts/observe/metrics.py"), "top", "--json"]),
    ("metrics path",    [str(_REPO_ROOT / "plugins/kaizen/scripts/observe/metrics.py"), "path"]),
    ("trace stats",     [str(_REPO_ROOT / "plugins/kaizen/scripts/observe/trace.py"), "stats"]),
    ("loc-index report", [str(_REPO_ROOT / "plugins/kaizen/scripts/indexers/loc_index.py"), "report", "--json"]),
    # Phase D — observe / scrape / manifests / handoff / drift / config / docs_flow
    ("observe layers",   [str(_REPO_ROOT / "plugins/kaizen/scripts/observe/observe.py"), "layers"]),
    ("observe stats",    [str(_REPO_ROOT / "plugins/kaizen/scripts/observe/observe.py"), "stats"]),
    ("manifests audit",  [str(_REPO_ROOT / "plugins/kaizen/scripts/workflow/manifests_cli.py"), "audit", "--json"]),
    ("manifests unused", [str(_REPO_ROOT / "plugins/kaizen/scripts/workflow/manifests_cli.py"), "unused", "--json"]),
    ("handoff latest",   [str(_REPO_ROOT / "plugins/kaizen/scripts/handoff/handoff.py"), "latest", "--json"]),
    ("handoff path",     [str(_REPO_ROOT / "plugins/kaizen/scripts/handoff/handoff.py"), "path"]),
    ("config defaults",  [str(_SCRIPTS / "config.py"), "--defaults"]),
    ("config validate",  [str(_SCRIPTS / "config.py"), "--validate"]),
    ("config json",      [str(_SCRIPTS / "config.py"), "--json"]),
    # Phase D2 — trace_index / knowledge_index / validate / index_flow /
    # loop_state / models / self_audit_agent
    ("validate feature", [
        str(_REPO_ROOT / "plugins/kaizen/skills/plugin-development/scripts/validate.py"),
        "--feature", "kaizen", "--json",
    ]),
    ("loop_state status",   [str(_REPO_ROOT / "plugins/kaizen/scripts/state/loop_state.py"), "status", "--json"]),
    ("self_audit_agent path", [str(_REPO_ROOT / "plugins/kaizen/scripts/iron-laws/self_audit_agent.py"), "path"]),
    # scrape_index search needs numpy (skipped via _has_numpy)
    # trace_index search / knowledge_index search — also numpy
    # models list — needs ollama package
    # index_flow --json — runs full embed pipeline; heavy for CI smoke
    # drift_cli check needs baseline + current dirs (skipped — needs fixture)
    # docs_flow needs a workspace with manifests (skipped — needs fixture)
    # roadmap_status excluded — needs handoff fixture in plans/
]


class TestEmitterFactory(unittest.TestCase):
    """`_envelope.emitter(tool)` returns a tool-bound closure — DRY for
    multiple --json call sites in the same script."""

    def setUp(self):
        self.env = _load("kaizen_env_emitter_test", _ENVELOPE)

    def test_emitter_returns_callable(self):
        bound = self.env.emitter("kaizen-test", tool_version="0.1.0")
        self.assertTrue(callable(bound))

    def test_emitter_captures_tool_and_version(self):
        # Call the bound emitter and inspect what it would write.
        import io
        bound = self.env.emitter("kaizen-test-bound", tool_version="9.9.9")
        buf = io.StringIO()
        bound({"items": []}, verdict="green", file=buf)
        result = json.loads(buf.getvalue())
        self.assertEqual(result["kaizen"]["tool"], "kaizen-test-bound")
        self.assertEqual(result["kaizen"]["tool_version"], "9.9.9")
        self.assertEqual(result["verdict"], "green")

    def test_emitter_pulls_argv_at_call_time(self):
        """argv is grabbed from sys.argv at call time, not at emitter
        construction — so late argv mutations are respected."""
        import io
        bound = self.env.emitter("kaizen-late-argv")
        original = sys.argv
        try:
            sys.argv = ["fake-script", "--late-flag"]
            buf = io.StringIO()
            bound({}, file=buf)
            result = json.loads(buf.getvalue())
            self.assertEqual(result["kaizen"]["command"], "fake-script --late-flag")
        finally:
            sys.argv = original


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

    def _spawn(self, name: str, cmd: list[str]) -> tuple[str, "subprocess.CompletedProcess"]:
        """Just the subprocess.run — pure I/O bound, safe to parallelize."""
        return name, subprocess.run(
            [sys.executable, *cmd], cwd=_REPO_ROOT,
            capture_output=True, text=True, timeout=30,
        )

    def _validate_result(self, name: str, r) -> None:
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
        # Parallelize the subprocess spawns (I/O bound — safe).
        # Pre-opt: ~8 sequential spawns × ~300ms cold-start = ~2.4s.
        # Post-opt: max-worker concurrent → ~0.5s.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda pair: self._spawn(pair[0], pair[1]),
                _RETROFIT_TOOLS,
            ))
        for name, r in results:
            with self.subTest(tool=name):
                self._validate_result(name, r)


class TestReproducibility(unittest.TestCase):
    """Identical inputs must produce byte-identical outputs (no
    auto-timestamp in non-time fields, no random ids)."""

    def test_gatekeeper_json_byte_identical(self):
        cmd = [sys.executable, str(_REPO_ROOT / "plugins/kaizen/scripts/iron-laws/gatekeeper.py"),
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
