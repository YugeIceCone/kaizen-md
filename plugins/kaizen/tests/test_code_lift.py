"""Tests for code_lift.py — X4 code-lift engine (formerly _migrate.py).

Mirrors the Rust ``xtask/src/migrate/`` test cases (rewriter boundary
checks, longest-match-first, config round-trip, deps-gap regex)
plus integration tests for lift / preview / audit.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

import code_lift  # noqa: E402

# ─── Config parsing ───────────────────────────────────────────────────

class TestConfigParse(unittest.TestCase):
    def test_parses_minimal(self):
        cfg = code_lift.Config.from_dict({
            "targets": {"core": "core"},
            "paths": {"shodan_kernel": "shodan_core"},
            "required_deps": {"tools": ["dirs"]},
        })
        self.assertEqual(cfg.target_for("core"), "core")
        self.assertEqual(cfg.required_deps_for("tools"), ["dirs"])
        pairs = cfg.paths_longest_first()
        self.assertEqual(pairs[0], ("shodan_kernel", "shodan_core"))

    def test_longest_path_first(self):
        cfg = code_lift.Config.from_dict({
            "paths": {
                "shodan_protocol": "shodan_core",
                "shodan_protocol::ApprovalRequest": "shodan_core::ApprovalRequest",
            },
        })
        pairs = cfg.paths_longest_first()
        self.assertIn("ApprovalRequest", pairs[0][0])

    def test_siblings_parsed(self):
        cfg = code_lift.Config.from_dict({
            "siblings": [
                {
                    "file": "src/foo.rs",
                    "must_lift_with": ["src/bar.rs"],
                    "note": "shared types",
                },
            ],
        })
        c = cfg.siblings_for("src/foo.rs")
        self.assertIsNotNone(c)
        self.assertEqual(c.must_lift_with, ["src/bar.rs"])
        self.assertEqual(c.note, "shared types")

    def test_missing_sibling_returns_none(self):
        cfg = code_lift.Config.from_dict({})
        self.assertIsNone(cfg.siblings_for("nothing"))

    def test_target_skip(self):
        cfg = code_lift.Config.from_dict({"targets": {"old": "_skip"}})
        self.assertEqual(cfg.target_for("old"), "_skip")

    def test_empty_config(self):
        cfg = code_lift.Config.from_dict({})
        self.assertIsNone(cfg.target_for("anything"))
        self.assertEqual(cfg.paths_longest_first(), [])
        self.assertEqual(cfg.required_deps_for("any"), [])

    def test_crate_targets_alias(self):
        # Back-compat: shodan xtask uses `crate_targets` key
        cfg = code_lift.Config.from_dict({"crate_targets": {"a": "b"}})
        self.assertEqual(cfg.target_for("a"), "b")

    def test_meta_overrides_roots(self):
        cfg = code_lift.Config.from_dict({
            "meta": {"source_root": "vendor", "target_root": "packages"},
        })
        self.assertEqual(cfg.source_root, "vendor")
        self.assertEqual(cfg.target_root, "packages")

# ─── Rewriter ─────────────────────────────────────────────────────────

class TestRewriter(unittest.TestCase):
    def _cfg(self, pairs):
        return code_lift.Config.from_dict({"paths": dict(pairs)})

    def test_simple_rewrite(self):
        out, events = code_lift.rewrite(
            "use shodan_kernel::Foo;",
            self._cfg([("shodan_kernel", "shodan_core")]),
        )
        self.assertEqual(out, "use shodan_core::Foo;")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].occurrences, 1)

    def test_longer_wins_over_prefix(self):
        cfg = self._cfg([
            ("shodan_protocol", "shodan_core"),
            ("shodan_protocol::ApprovalRequest", "shodan_core::ApprovalRequest"),
        ])
        out, _ = code_lift.rewrite(
            "use shodan_protocol::ApprovalRequest;\n"
            "use shodan_protocol::other;",
            cfg,
        )
        self.assertIn("shodan_core::ApprovalRequest", out)
        self.assertIn("shodan_core::other", out)

    def test_boundary_blocks_partial_match(self):
        # `shodan_core_extension` must NOT match `shodan_core` —
        # next byte `_` isn't in the boundary set.
        out, _ = code_lift.rewrite(
            "shodan_core_extension",
            self._cfg([("shodan_core", "shodan_NEW")]),
        )
        self.assertEqual(out, "shodan_core_extension")

    def test_multiple_occurrences_counted(self):
        out, events = code_lift.rewrite(
            "old::a old::b old::c",
            self._cfg([("old", "new")]),
        )
        # Each "old" is followed by `::` (boundary), so 3 rewrites.
        self.assertEqual(out, "new::a new::b new::c")
        self.assertEqual(events[0].occurrences, 3)

    def test_no_match_emits_no_event(self):
        out, events = code_lift.rewrite(
            "nothing to see here",
            self._cfg([("foo", "bar")]),
        )
        self.assertEqual(out, "nothing to see here")
        self.assertEqual(events, [])

    def test_eof_is_boundary(self):
        out, _ = code_lift.rewrite("shodan_core", self._cfg([("shodan_core", "X")]))
        self.assertEqual(out, "X")

    def test_newline_is_boundary(self):
        out, _ = code_lift.rewrite(
            "shodan_core\nrest",
            self._cfg([("shodan_core", "X")]),
        )
        self.assertEqual(out, "X\nrest")

# ─── Manifest detection / deps_gap ───────────────────────────────────

class TestManifestDetection(unittest.TestCase):
    def test_cargo_dep_match_eq(self):
        manifest = code_lift.ManifestInfo(
            path=Path("Cargo.toml"),
            kind="cargo",
            body='[dependencies]\nserde = "1.0"\ntokio = { version = "1" }\n',
        )
        self.assertTrue(code_lift.manifest_has_dep(manifest, "serde"))
        self.assertTrue(code_lift.manifest_has_dep(manifest, "tokio"))
        self.assertFalse(code_lift.manifest_has_dep(manifest, "axum"))

    def test_cargo_workspace_dep(self):
        manifest = code_lift.ManifestInfo(
            path=Path("Cargo.toml"),
            kind="cargo",
            body="[dependencies]\nserde.workspace = true\n",
        )
        self.assertTrue(code_lift.manifest_has_dep(manifest, "serde"))

    def test_cargo_explicit_section(self):
        manifest = code_lift.ManifestInfo(
            path=Path("Cargo.toml"),
            kind="cargo",
            body='[dependencies.tokio]\nversion = "1"\n',
        )
        self.assertTrue(code_lift.manifest_has_dep(manifest, "tokio"))

    def test_npm_dep_match(self):
        manifest = code_lift.ManifestInfo(
            path=Path("package.json"),
            kind="npm",
            body=json.dumps({
                "dependencies": {"react": "^18"},
                "devDependencies": {"jest": "^29"},
            }),
        )
        self.assertTrue(code_lift.manifest_has_dep(manifest, "react"))
        self.assertTrue(code_lift.manifest_has_dep(manifest, "jest"))
        self.assertFalse(code_lift.manifest_has_dep(manifest, "vue"))

    def test_npm_invalid_json_returns_false(self):
        manifest = code_lift.ManifestInfo(
            path=Path("package.json"), kind="npm", body="not json",
        )
        self.assertFalse(code_lift.manifest_has_dep(manifest, "react"))

    def test_pyproject_pep631(self):
        manifest = code_lift.ManifestInfo(
            path=Path("pyproject.toml"),
            kind="pyproject",
            body='[project]\ndependencies = ["click>=8", "requests"]\n',
        )
        self.assertTrue(code_lift.manifest_has_dep(manifest, "click"))

    def test_pyproject_poetry(self):
        manifest = code_lift.ManifestInfo(
            path=Path("pyproject.toml"),
            kind="pyproject",
            body='[tool.poetry.dependencies]\nclick = "^8"\nrequests = "*"\n',
        )
        self.assertTrue(code_lift.manifest_has_dep(manifest, "click"))
        self.assertTrue(code_lift.manifest_has_dep(manifest, "requests"))

    def test_go_mod(self):
        manifest = code_lift.ManifestInfo(
            path=Path("go.mod"),
            kind="go-mod",
            body="require github.com/example/foo v1.2.3\n",
        )
        self.assertTrue(code_lift.manifest_has_dep(manifest, "github.com/example/foo"))

    def test_empty_dep_returns_false(self):
        manifest = code_lift.ManifestInfo(
            path=Path("Cargo.toml"), kind="cargo", body="anything",
        )
        self.assertFalse(code_lift.manifest_has_dep(manifest, ""))

    def test_detect_cargo_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "Cargo.toml").write_text("[package]\nname = \"x\"\n")
            (d / "package.json").write_text('{"name": "x"}')
            m = code_lift.detect_manifest(d)
            self.assertEqual(m.kind, "cargo")

    def test_detect_returns_none_when_no_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(code_lift.detect_manifest(Path(tmp)))

# ─── do_lift / do_preview / do_audit (end-to-end) ────────────────────

class TestLift(unittest.TestCase):
    def _scaffold(self):
        """Build a minimal repo with port/p1/src/foo.rs + Cargo.toml."""
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "port" / "p1" / "src").mkdir(parents=True)
        (root / "port" / "p1" / "Cargo.toml").write_text(
            '[package]\nname = "p1"\n'
        )
        (root / "port" / "p1" / "src" / "foo.rs").write_text(
            "use shodan_kernel::Foo;\npub fn bar() {}\n"
        )
        (root / "crates" / "p1").mkdir(parents=True)
        (root / "crates" / "p1" / "Cargo.toml").write_text(
            '[package]\nname = "p1"\n[dependencies]\nserde = "1"\n'
        )
        cfg = code_lift.Config.from_dict({
            "targets": {"p1": "p1"},
            "paths": {"shodan_kernel": "shodan_core"},
            "required_deps": {"p1": ["serde", "tokio"]},
        })
        return tmp, root, cfg

    def test_lift_dry_run_does_not_write(self):
        tmp, root, cfg = self._scaffold()
        try:
            src = root / "port" / "p1" / "src" / "foo.rs"
            tgt = root / "crates" / "p1"
            result = code_lift.do_lift(
                src, tgt, cfg, root / "port", apply=False,
            )
            self.assertEqual(len(result.pairs), 1)
            self.assertEqual(result.total_rewrites, 1)
            self.assertFalse(result.applied)
            # Dry-run: target file must not exist
            self.assertFalse((tgt / "src" / "foo.rs").exists())
        finally:
            tmp.cleanup()

    def test_lift_apply_writes_rewritten(self):
        tmp, root, cfg = self._scaffold()
        try:
            src = root / "port" / "p1" / "src" / "foo.rs"
            tgt = root / "crates" / "p1"
            result = code_lift.do_lift(src, tgt, cfg, root / "port", apply=True)
            written = (tgt / "src" / "foo.rs").read_text()
            self.assertIn("shodan_core::Foo", written)
            self.assertNotIn("shodan_kernel", written)
            self.assertTrue(result.applied)
        finally:
            tmp.cleanup()

    def test_lift_directory(self):
        tmp, root, cfg = self._scaffold()
        try:
            (root / "port" / "p1" / "src" / "bar.rs").write_text(
                "use shodan_kernel::Bar;\n"
            )
            src = root / "port" / "p1" / "src"
            tgt = root / "crates" / "p1"
            result = code_lift.do_lift(src, tgt, cfg, root / "port", apply=True)
            self.assertEqual(len(result.pairs), 2)
            self.assertTrue((tgt / "src" / "foo.rs").is_file())
            self.assertTrue((tgt / "src" / "bar.rs").is_file())
        finally:
            tmp.cleanup()

class TestPreview(unittest.TestCase):
    def _scaffold(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "port" / "p1" / "src").mkdir(parents=True)
        (root / "port" / "p1" / "src" / "foo.rs").write_text(
            "use shodan_kernel::Foo;\n"
        )
        (root / "crates" / "p1").mkdir(parents=True)
        (root / "crates" / "p1" / "Cargo.toml").write_text(
            '[dependencies]\nserde = "1"\n'
        )
        cfg = code_lift.Config.from_dict({
            "targets": {"p1": "p1"},
            "paths": {"shodan_kernel": "shodan_core"},
            "required_deps": {"p1": ["serde", "tokio"]},
        })
        return tmp, root, cfg

    def test_preview_shows_rewrites_and_missing_deps(self):
        tmp, root, cfg = self._scaffold()
        try:
            src = root / "port" / "p1" / "src" / "foo.rs"
            result = code_lift.do_preview(src, root, cfg)
            self.assertEqual(result.status, "ok")
            self.assertEqual(len(result.rewrite_events), 1)
            # serde present, tokio missing
            self.assertEqual(result.missing_deps, ["tokio"])
            self.assertFalse(result.target_exists)
        finally:
            tmp.cleanup()

    def test_preview_skipped(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            root = Path(tmp.name)
            (root / "port" / "skipped" / "src").mkdir(parents=True)
            f = root / "port" / "skipped" / "src" / "x.rs"
            f.write_text("pub fn x() {}\n")
            cfg = code_lift.Config.from_dict({
                "targets": {"skipped": "_skip"},
            })
            result = code_lift.do_preview(f, root, cfg)
            self.assertEqual(result.status, "skipped")
        finally:
            tmp.cleanup()

    def test_preview_no_mapping(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            root = Path(tmp.name)
            (root / "port" / "unknown" / "src").mkdir(parents=True)
            f = root / "port" / "unknown" / "src" / "x.rs"
            f.write_text("pub fn x() {}\n")
            cfg = code_lift.Config.from_dict({})  # no [targets]
            result = code_lift.do_preview(f, root, cfg)
            self.assertEqual(result.status, "no-mapping")
        finally:
            tmp.cleanup()

class TestAudit(unittest.TestCase):
    def test_audit_status_buckets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # p1: lifted (both port + crates with files)
            (root / "port" / "p1" / "src").mkdir(parents=True)
            (root / "port" / "p1" / "src" / "x.rs").write_text("pub fn x(){}")
            (root / "crates" / "p1" / "src").mkdir(parents=True)
            (root / "crates" / "p1" / "src" / "x.rs").write_text("pub fn x(){}")
            # p2: pending (port files, no crates files)
            (root / "port" / "p2" / "src").mkdir(parents=True)
            (root / "port" / "p2" / "src" / "y.rs").write_text("pub fn y(){}")
            (root / "crates" / "p2").mkdir(parents=True)
            # p3: skipped
            (root / "port" / "p3" / "src").mkdir(parents=True)
            (root / "port" / "p3" / "src" / "z.rs").write_text("pub fn z(){}")
            # p4: missing target dir
            (root / "port" / "p4" / "src").mkdir(parents=True)
            (root / "port" / "p4" / "src" / "w.rs").write_text("pub fn w(){}")
            cfg = code_lift.Config.from_dict({
                "targets": {"p1": "p1", "p2": "p2", "p3": "_skip", "p4": "p4"},
            })
            rows = code_lift.do_audit(root, cfg)
            statuses = {r.source_project: r.status for r in rows}
            self.assertEqual(statuses["p1"], "lifted")
            self.assertEqual(statuses["p2"], "pending")
            self.assertEqual(statuses["p3"], "skipped")
            self.assertEqual(statuses["p4"], "missing-target")

class TestDepsGap(unittest.TestCase):
    def test_deps_gap_lists_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "crates" / "x").mkdir(parents=True)
            (root / "crates" / "x" / "Cargo.toml").write_text(
                '[dependencies]\nserde = "1"\n'
            )
            cfg = code_lift.Config.from_dict({
                "required_deps": {"x": ["serde", "tokio", "anyhow"]},
            })
            result = code_lift.do_deps_gap("x", root, cfg)
            self.assertEqual(result.manifest_kind, "cargo")
            self.assertEqual(set(result.missing), {"tokio", "anyhow"})

    def test_deps_gap_no_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "crates" / "x").mkdir(parents=True)
            cfg = code_lift.Config.from_dict({
                "required_deps": {"x": ["serde"]},
            })
            result = code_lift.do_deps_gap("x", root, cfg)
            self.assertIsNone(result.manifest_path)
            self.assertEqual(result.missing, ["serde"])

    def test_deps_gap_no_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "crates" / "x").mkdir(parents=True)
            (root / "crates" / "x" / "Cargo.toml").write_text("[package]\n")
            cfg = code_lift.Config.from_dict({})
            result = code_lift.do_deps_gap("x", root, cfg)
            self.assertEqual(result.required, [])
            self.assertEqual(result.missing, [])

# ─── CLI integration (path + smoke) ──────────────────────────────────

class TestCli(unittest.TestCase):
    def test_path_command(self):
        # `path` doesn't need a real config — just reports detected paths
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            rc = code_lift.main(["--root", str(root), "path"])
            self.assertEqual(rc, 0)

if __name__ == "__main__":
    unittest.main()
