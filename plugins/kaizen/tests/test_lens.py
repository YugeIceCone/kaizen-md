"""Tests for lens.py — schema-driven CLI runtime helper.

The lens pattern (skills/schema-driven-cli/SKILL.md):
- Manifest declares a feature's subcommands + per-subcommand input/output schemas
- Subcommand objects validate I/O against those schemas
- lens_emit wraps validated output in the canonical _envelope shape
- BucketWalker walks data-driven rule yamls (rubric / classifier shape)

TDD coverage written before implementation. Each test class targets one
public surface; the failing skeleton runs first (RED), then lens.py
implementation lands (GREEN).
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS = _KZ_DIR / "skills/workflow/scripts"
sys.path.insert(0, str(_SCRIPTS))


# ─── Manifest ────────────────────────────────────────────────────────


class TestManifestLoad(unittest.TestCase):
    """A v2 manifest declares subcommands → schema paths."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_manifest(self, content: str) -> Path:
        p = self.tmp / "manifest.yaml"
        p.write_text(content, encoding="utf-8")
        return p

    def test_load_returns_manifest_with_version_and_feature(self):
        import lens
        p = self._write_manifest(textwrap.dedent("""\
            version: 2
            feature: handoff
            subcommands:
              verify:
                input_schema: schemas/verify-in.schema.json
                output_schema: schemas/verify-out.schema.json
        """))
        m = lens.Manifest.load(p)
        self.assertEqual(m.version, 2)
        self.assertEqual(m.feature, "handoff")
        self.assertIn("verify", m.subcommands)

    def test_v1_manifest_is_rejected(self):
        import lens
        p = self._write_manifest("version: 1\nfeature: handoff\nsubcommands: {}\n")
        with self.assertRaises(lens.ManifestError):
            lens.Manifest.load(p)

    def test_missing_required_key_raises(self):
        import lens
        p = self._write_manifest("version: 2\nsubcommands: {}\n")  # no `feature`
        with self.assertRaises(lens.ManifestError):
            lens.Manifest.load(p)


class TestManifestGet(unittest.TestCase):
    """`get(name)` returns Subcommand or raises KeyError."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        (self.tmp / "manifest.yaml").write_text(textwrap.dedent("""\
            version: 2
            feature: handoff
            subcommands:
              verify:
                description: structural verification
                input_schema: schemas/v-in.json
                output_schema: schemas/v-out.json
        """), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_get_known_subcommand_returns_subcommand(self):
        import lens
        m = lens.Manifest.load(self.tmp / "manifest.yaml")
        sub = m.get("verify")
        self.assertEqual(sub.name, "verify")
        self.assertEqual(sub.description, "structural verification")
        # input/output schema paths are resolved relative to manifest dir
        self.assertEqual(
            sub.input_schema_path,
            self.tmp / "schemas" / "v-in.json",
        )
        self.assertEqual(
            sub.output_schema_path,
            self.tmp / "schemas" / "v-out.json",
        )

    def test_get_unknown_subcommand_raises(self):
        import lens
        m = lens.Manifest.load(self.tmp / "manifest.yaml")
        with self.assertRaises(KeyError):
            m.get("does-not-exist")


# ─── Subcommand input/output validation ──────────────────────────────


class TestSubcommandValidate(unittest.TestCase):
    """Subcommand wraps jsonschema validate against the declared schemas."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        (self.tmp / "schemas").mkdir()
        (self.tmp / "schemas" / "v-in.json").write_text(json.dumps({
            "type": "object",
            "required": ["file"],
            "properties": {"file": {"type": "string"}},
        }))
        (self.tmp / "schemas" / "v-out.json").write_text(json.dumps({
            "type": "object",
            "required": ["verdict"],
            "properties": {"verdict": {"enum": ["clean", "drift"]}},
        }))
        (self.tmp / "manifest.yaml").write_text(textwrap.dedent("""\
            version: 2
            feature: handoff
            subcommands:
              verify:
                input_schema: schemas/v-in.json
                output_schema: schemas/v-out.json
        """), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_valid_input_passes(self):
        import lens
        sub = lens.Manifest.load(self.tmp / "manifest.yaml").get("verify")
        sub.validate_input({"file": "x.yaml"})  # no raise

    def test_invalid_input_raises(self):
        import lens
        sub = lens.Manifest.load(self.tmp / "manifest.yaml").get("verify")
        with self.assertRaises(lens.SchemaValidationError):
            sub.validate_input({})  # missing required "file"

    def test_valid_output_passes(self):
        import lens
        sub = lens.Manifest.load(self.tmp / "manifest.yaml").get("verify")
        sub.validate_output({"verdict": "clean"})

    def test_invalid_output_raises(self):
        import lens
        sub = lens.Manifest.load(self.tmp / "manifest.yaml").get("verify")
        with self.assertRaises(lens.SchemaValidationError):
            sub.validate_output({"verdict": "not-a-bucket"})

    def test_no_schema_declared_is_passthrough(self):
        """Subcommands may omit one or both schemas — validation no-ops."""
        import lens
        manifest = self.tmp / "manifest2.yaml"
        manifest.write_text("version: 2\nfeature: x\nsubcommands:\n  s: {}\n")
        sub = lens.Manifest.load(manifest).get("s")
        sub.validate_input({})    # no raise
        sub.validate_output({})   # no raise


# ─── lens_emit — the canonical wrap+emit helper ──────────────────────


class TestLensEmit(unittest.TestCase):
    """lens_emit validates output, then emits canonical envelope to stdout."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        (self.tmp / "schemas").mkdir()
        (self.tmp / "schemas" / "out.json").write_text(json.dumps({
            "type": "object",
            "required": ["verdict"],
            "properties": {"verdict": {"enum": ["clean", "drift"]}},
        }))
        (self.tmp / "manifest.yaml").write_text(textwrap.dedent("""\
            version: 2
            feature: demo
            subcommands:
              do:
                output_schema: schemas/out.json
        """), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_valid_output_emits_envelope(self):
        import lens
        m = lens.Manifest.load(self.tmp / "manifest.yaml")
        buf = io.StringIO()
        lens.lens_emit(
            "kaizen-demo", m, "do",
            data={"verdict": "clean"},
            verdict="green",
            tool_version="1.0.0",
            file=buf,
        )
        env = json.loads(buf.getvalue())
        # Canonical envelope shape — kaizen + data wrapper
        self.assertIn("kaizen", env)
        self.assertEqual(env["kaizen"]["tool"], "kaizen-demo")
        self.assertEqual(env["data"]["verdict"], "clean")
        # verdict lands at envelope top-level (not under kaizen meta)
        self.assertEqual(env["verdict"], "green")

    def test_invalid_output_raises_before_emit(self):
        import lens
        m = lens.Manifest.load(self.tmp / "manifest.yaml")
        buf = io.StringIO()
        with self.assertRaises(lens.SchemaValidationError):
            lens.lens_emit(
                "kaizen-demo", m, "do",
                data={"verdict": "bogus"},
                file=buf,
            )
        # Nothing should have been written — fail closed.
        self.assertEqual(buf.getvalue(), "")


# ─── BucketWalker — data-driven rubric/classifier ────────────────────


class TestBucketWalkerFromYaml(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _rubric(self, content: str) -> Path:
        p = self.tmp / "rubric.yaml"
        p.write_text(content, encoding="utf-8")
        return p

    def test_loads_bucketed_rules(self):
        import lens
        p = self._rubric(textwrap.dedent("""\
            rules:
              - bucket: SUCCEEDED
                require_all:
                  - {signal: completed_ratio, op: ">=", value: 1.0}
              - bucket: FAILED
                require_any:
                  - {signal: completed_ratio, op: "<", value: 0.3}
            confidence_threshold: 0.85
            fallback: NEEDS_AGENT
        """))
        w = lens.BucketWalker.from_yaml(p)
        self.assertEqual(len(w.rules), 2)
        self.assertEqual(w.confidence_threshold, 0.85)
        self.assertEqual(w.fallback, "NEEDS_AGENT")


class TestBucketWalkerEvaluate(unittest.TestCase):
    """Walker applies require_all / require_any per-rule, first match wins."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.rubric = self.tmp / "rubric.yaml"
        self.rubric.write_text(textwrap.dedent("""\
            rules:
              - bucket: SUCCEEDED
                require_all:
                  - {signal: completed_ratio, op: ">=", value: 1.0}
                  - {signal: test_delta,     op: ">=", value: 0}
                  - {signal: blocker_count,  op: "==", value: 0}
              - bucket: PARTIAL_PLUS
                require_all:
                  - {signal: completed_ratio, op: ">=", value: 0.7}
                  - {signal: blocker_count,   op: "==", value: 0}
              - bucket: PARTIAL_MINUS
                require_any:
                  - {signal: completed_ratio, op: ">=", value: 0.3}
                  - {signal: blocker_count,   op: ">",  value: 0}
              - bucket: FAILED
                require_any:
                  - {signal: completed_ratio, op: "<",  value: 0.3}
                  - {signal: test_delta,      op: "<",  value: 0}
            confidence_threshold: 0.85
            fallback: NEEDS_AGENT
        """), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_all_clean_picks_succeeded(self):
        import lens
        w = lens.BucketWalker.from_yaml(self.rubric)
        result = w.evaluate({
            "completed_ratio": 1.0,
            "test_delta": 0,
            "blocker_count": 0,
        })
        self.assertEqual(result.bucket, "SUCCEEDED")
        self.assertEqual(result.method, "deterministic")
        self.assertGreaterEqual(result.confidence, 0.85)

    def test_partial_progress_picks_partial_plus(self):
        import lens
        w = lens.BucketWalker.from_yaml(self.rubric)
        result = w.evaluate({
            "completed_ratio": 0.8,
            "test_delta": 0,
            "blocker_count": 0,
        })
        self.assertEqual(result.bucket, "PARTIAL_PLUS")

    def test_blocker_picks_partial_minus(self):
        """PARTIAL_MINUS uses require_any — any of completed≥0.3 OR blocker>0."""
        import lens
        w = lens.BucketWalker.from_yaml(self.rubric)
        result = w.evaluate({
            "completed_ratio": 0.5,
            "test_delta": 0,
            "blocker_count": 1,
        })
        # Note: PARTIAL_PLUS condition fails (blocker > 0); PARTIAL_MINUS matches.
        self.assertEqual(result.bucket, "PARTIAL_MINUS")

    def test_test_regression_picks_failed(self):
        import lens
        w = lens.BucketWalker.from_yaml(self.rubric)
        result = w.evaluate({
            "completed_ratio": 0.1,
            "test_delta": -5,
            "blocker_count": 0,
        })
        self.assertEqual(result.bucket, "FAILED")

    def test_no_rule_matches_falls_back(self):
        """Edge case where no bucket's require_* clears."""
        import lens
        rubric = self.tmp / "narrow.yaml"
        rubric.write_text(textwrap.dedent("""\
            rules:
              - bucket: NARROW
                require_all:
                  - {signal: x, op: "==", value: 999}
            confidence_threshold: 0.85
            fallback: NEEDS_AGENT
        """))
        w = lens.BucketWalker.from_yaml(rubric)
        result = w.evaluate({"x": 1})
        self.assertEqual(result.bucket, "NEEDS_AGENT")
        self.assertEqual(result.method, "fallback")

    def test_missing_signal_treated_as_unsatisfied(self):
        """A rule that references a signal not in the input fails to match."""
        import lens
        w = lens.BucketWalker.from_yaml(self.rubric)
        result = w.evaluate({"completed_ratio": 1.0})  # missing test_delta, blocker_count
        # Can't match SUCCEEDED (needs test_delta + blocker_count); falls
        # through to PARTIAL_MINUS via require_any on completed_ratio.
        self.assertNotEqual(result.bucket, "SUCCEEDED")

    def test_rationale_explains_matched_rule(self):
        import lens
        w = lens.BucketWalker.from_yaml(self.rubric)
        result = w.evaluate({
            "completed_ratio": 1.0, "test_delta": 0, "blocker_count": 0,
        })
        self.assertIn("SUCCEEDED", result.rationale)


class TestBucketWalkerOperators(unittest.TestCase):
    """The op vocabulary: >= > <= < == != contains in not_in."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _make(self, op_pairs: list[tuple[str, str, int]]) -> "object":
        """Build a rubric with one require_all rule using the given (signal, op, value) triples."""
        import lens
        import yaml as _yaml
        rules = [
            {
                "bucket": "MATCH",
                "require_all": [
                    {"signal": sig, "op": op, "value": val}
                    for sig, op, val in op_pairs
                ],
            },
            {
                "bucket": "ELSE",
                "require_any": [{"signal": "_fallthrough", "op": "==", "value": 1}],
            },
        ]
        p = self.tmp / "ops.yaml"
        p.write_text(_yaml.safe_dump({
            "rules": rules,
            "confidence_threshold": 0.85,
            "fallback": "NEEDS_AGENT",
        }))
        return lens.BucketWalker.from_yaml(p)

    def test_ge_op(self):
        w = self._make([("x", ">=", 5)])
        self.assertEqual(w.evaluate({"x": 5, "_fallthrough": 1}).bucket, "MATCH")
        self.assertEqual(w.evaluate({"x": 4, "_fallthrough": 1}).bucket, "ELSE")

    def test_gt_op(self):
        w = self._make([("x", ">", 5)])
        self.assertEqual(w.evaluate({"x": 6, "_fallthrough": 1}).bucket, "MATCH")
        self.assertEqual(w.evaluate({"x": 5, "_fallthrough": 1}).bucket, "ELSE")

    def test_le_lt_eq_neq(self):
        for op, hit, miss in (
            ("<=", 5, 6),
            ("<", 4, 5),
            ("==", 5, 4),
            ("!=", 4, 5),
        ):
            w = self._make([("x", op, 5)])
            self.assertEqual(
                w.evaluate({"x": hit, "_fallthrough": 1}).bucket, "MATCH",
                msg=f"op {op} hit={hit}",
            )
            self.assertEqual(
                w.evaluate({"x": miss, "_fallthrough": 1}).bucket, "ELSE",
                msg=f"op {op} miss={miss}",
            )

    def test_unknown_op_raises_at_load_time(self):
        import lens
        import yaml as _yaml
        p = self.tmp / "bad.yaml"
        p.write_text(_yaml.safe_dump({
            "rules": [{
                "bucket": "X",
                "require_all": [{"signal": "y", "op": "approximately", "value": 1}],
            }],
            "fallback": "NEEDS_AGENT",
        }))
        with self.assertRaises(lens.RuleError):
            lens.BucketWalker.from_yaml(p)


# ─── End-to-end: lens_dispatch (manifest+handler+envelope) ───────────


class TestLensDispatch(unittest.TestCase):
    """Convenience: validate input → call handler → validate + emit output."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        (self.tmp / "schemas").mkdir()
        (self.tmp / "schemas" / "in.json").write_text(json.dumps({
            "type": "object",
            "required": ["n"],
            "properties": {"n": {"type": "integer"}},
        }))
        (self.tmp / "schemas" / "out.json").write_text(json.dumps({
            "type": "object",
            "required": ["doubled"],
            "properties": {"doubled": {"type": "integer"}},
        }))
        (self.tmp / "manifest.yaml").write_text(textwrap.dedent("""\
            version: 2
            feature: math
            subcommands:
              double:
                input_schema: schemas/in.json
                output_schema: schemas/out.json
        """), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_happy_path_runs_handler_emits_envelope(self):
        import lens
        m = lens.Manifest.load(self.tmp / "manifest.yaml")
        buf = io.StringIO()
        rc = lens.lens_dispatch(
            "kaizen-math", m, "double",
            input_data={"n": 3},
            handler=lambda d: {"doubled": d["n"] * 2},
            file=buf,
        )
        env = json.loads(buf.getvalue())
        self.assertEqual(env["data"]["doubled"], 6)
        self.assertEqual(rc, 0)

    def test_invalid_input_returns_nonzero_no_handler_call(self):
        import lens
        m = lens.Manifest.load(self.tmp / "manifest.yaml")
        buf = io.StringIO()
        called = []
        rc = lens.lens_dispatch(
            "kaizen-math", m, "double",
            input_data={"n": "not-an-integer"},
            handler=lambda d: called.append(True) or {"doubled": 0},
            file=buf,
        )
        self.assertNotEqual(rc, 0)
        self.assertEqual(called, [], "handler must not run on invalid input")

    def test_invalid_output_returns_nonzero_does_not_emit_partial(self):
        import lens
        m = lens.Manifest.load(self.tmp / "manifest.yaml")
        buf = io.StringIO()
        rc = lens.lens_dispatch(
            "kaizen-math", m, "double",
            input_data={"n": 3},
            handler=lambda d: {"wrong_key": 6},
            file=buf,
        )
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
