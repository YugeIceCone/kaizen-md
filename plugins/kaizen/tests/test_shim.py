"""Unit tests for `shim.py` — the kaizen-shim CLI backing the
shim-and-sweep routine.

1:1 coverage of every public surface:

    manifest_init / manifest_append / manifest_read
    shim_contents          (per-language writers)
    carve()                (file move + shim + manifest)
    sweep()                (gated F-FINAL deletion)
    main(argv)             (CLI exit codes)

Run:
    python3 -m unittest tests.test_shim -v
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

import shim  # noqa: E402

def _make_fake_repo(tmpdir: Path) -> Path:
    """Build a minimal git-rooted repo tree for testing."""
    root = tmpdir / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / ".kaizen" / "workflow").mkdir(parents=True)
    return root

# ─── Manifest ────────────────────────────────────────────────────────

class TestManifest(unittest.TestCase):
    def test_init_creates_file_with_header(self):
        with tempfile.TemporaryDirectory() as td:
            root = _make_fake_repo(Path(td))
            p = shim.manifest_init("test-slug", root=root)
            self.assertTrue(p.is_file())
            text = p.read_text()
            self.assertIn("Deletion manifest", text)
            self.assertIn("test-slug", text)

    def test_init_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = _make_fake_repo(Path(td))
            p1 = shim.manifest_init("s", root=root)
            content1 = p1.read_text()
            p2 = shim.manifest_init("s", root=root)
            self.assertEqual(p1, p2)
            self.assertEqual(content1, p2.read_text())

    def test_append_adds_entry(self):
        with tempfile.TemporaryDirectory() as td:
            root = _make_fake_repo(Path(td))
            shim.manifest_append("s", "foo/bar.rs", root=root)
            entries = shim.manifest_read("s", root=root)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0][1], "foo/bar.rs")
        self.assertIsNone(entries[0][2])

    def test_append_with_keep(self):
        with tempfile.TemporaryDirectory() as td:
            root = _make_fake_repo(Path(td))
            shim.manifest_append("s", "back/compat.rs", root=root, keep="public surface")
            entries = shim.manifest_read("s", root=root)
        self.assertEqual(entries[0][2], "public surface")

    def test_read_skips_comments(self):
        with tempfile.TemporaryDirectory() as td:
            root = _make_fake_repo(Path(td))
            p = shim.manifest_init("s", root=root)
            with p.open("a") as f:
                f.write("\n# another comment\n2026-05-13 x.rs\n")
            entries = shim.manifest_read("s", root=root)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0][1], "x.rs")

# ─── Per-language shim writers ───────────────────────────────────────

class TestShimContents(unittest.TestCase):
    def test_rust_requires_reexport(self):
        with self.assertRaises(ValueError) as cx:
            shim.shim_contents(Path("a/foo.rs"), Path("b/foo.rs"), reexport=None)
        self.assertIn("--reexport", str(cx.exception))

    def test_rust_pub_use(self):
        body = shim.shim_contents(
            Path("a/foo.rs"), Path("b/foo.rs"),
            reexport="other_crate::foo",
        )
        self.assertIn("pub use other_crate::foo::*;", body)
        # Provenance comment references the new path.
        self.assertIn("b/foo.rs", body)

    def test_python_requires_reexport(self):
        with self.assertRaises(ValueError):
            shim.shim_contents(Path("a/foo.py"), Path("b/foo.py"), reexport=None)

    def test_python_import_star(self):
        body = shim.shim_contents(
            Path("a/foo.py"), Path("b/foo.py"),
            reexport="pkg.b.foo",
        )
        self.assertIn("from pkg.b.foo import *", body)

    def test_typescript_export_from_relative(self):
        body = shim.shim_contents(
            Path("a/sub/old.ts"), Path("b/sub/new.ts"),
            reexport=None,
        )
        # Reexport is computed; should resolve to a `./...` or `../...` path
        # (without extension).
        self.assertIn("export * from", body)
        self.assertTrue("./" in body or "../" in body)
        self.assertNotIn(".ts\";", body)  # extension stripped

    def test_javascript_supported(self):
        # Same as TS but .js
        body = shim.shim_contents(Path("a.js"), Path("b/a.js"), reexport=None)
        self.assertIn("export * from", body)

    def test_unsupported_extension_raises(self):
        with self.assertRaises(ValueError):
            shim.shim_contents(Path("a/foo.go"), Path("b/foo.go"), reexport=None)

# ─── carve() ─────────────────────────────────────────────────────────

class TestCarve(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = _make_fake_repo(Path(self.tmp.name))
        # Set up a source file with content
        self.src = self.root / "crates" / "old" / "src" / "foo.rs"
        self.src.parent.mkdir(parents=True)
        self.src.write_text("pub fn original() {}\n")
        self.dst = self.root / "crates" / "new" / "src" / "foo.rs"

    def test_carve_copies_content_to_new(self):
        shim.carve(self.src, self.dst, "f5", reexport="new_crate::foo", root=self.root)
        self.assertTrue(self.dst.is_file())
        self.assertIn("pub fn original()", self.dst.read_text())

    def test_carve_replaces_old_with_shim(self):
        shim.carve(self.src, self.dst, "f5", reexport="new_crate::foo", root=self.root)
        old_after = self.src.read_text()
        self.assertIn("pub use new_crate::foo::*;", old_after)
        self.assertNotIn("pub fn original()", old_after)

    def test_carve_appends_to_manifest(self):
        shim.carve(self.src, self.dst, "f5", reexport="new_crate::foo", root=self.root)
        entries = shim.manifest_read("f5", root=self.root)
        self.assertEqual(len(entries), 1)
        self.assertIn("foo.rs", entries[0][1])

    def test_carve_dry_run_changes_nothing(self):
        before_src = self.src.read_text()
        result = shim.carve(self.src, self.dst, "f5",
                            reexport="new_crate::foo", root=self.root, dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(self.src.read_text(), before_src)
        self.assertFalse(self.dst.exists())
        self.assertEqual(shim.manifest_read("f5", root=self.root), [])

    def test_carve_raises_when_source_missing(self):
        missing = self.root / "does" / "not" / "exist.rs"
        with self.assertRaises(ValueError) as cx:
            shim.carve(missing, self.dst, "f5", reexport="x", root=self.root)
        self.assertIn("source not found", str(cx.exception))

    def test_carve_raises_when_old_equals_new(self):
        with self.assertRaises(ValueError):
            shim.carve(self.src, self.src, "f5", reexport="x", root=self.root)

    def test_carve_handles_target_already_exists(self):
        # If new already exists (partial carve), we just install the shim
        # without overwriting.
        self.dst.parent.mkdir(parents=True, exist_ok=True)
        self.dst.write_text("// already here\n")
        result = shim.carve(self.src, self.dst, "f5",
                            reexport="new_crate::foo", root=self.root)
        self.assertFalse(result["copied"])
        self.assertIn("pub use new_crate::foo::*;", self.src.read_text())
        # New target NOT overwritten
        self.assertEqual(self.dst.read_text(), "// already here\n")

# ─── sweep() ─────────────────────────────────────────────────────────

class TestSweep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = _make_fake_repo(Path(self.tmp.name))
        # Init a real git repo so `git rm` works
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "t"], check=True)
        # Pre-commit a file that we'll later "shim" and then sweep
        self.shimmed = self.root / "old.rs"
        self.shimmed.write_text("pub use new::*;\n")
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-q", "-m", "seed"], check=True)
        shim.manifest_append("f5", "old.rs", root=self.root)

    def _scrub_env(self):
        os.environ.pop("KAIZEN_ALLOW_DELETE", None)

    def test_sweep_refused_without_authorization(self):
        self._scrub_env()
        with self.assertRaises(PermissionError) as cx:
            shim.sweep("f5", root=self.root)
        self.assertIn("KAIZEN_ALLOW_DELETE", str(cx.exception))

    def test_sweep_allowed_with_flag(self):
        self._scrub_env()
        result = shim.sweep("f5", root=self.root, allow_delete=True)
        self.assertEqual(result["deleted"], ["old.rs"])
        self.assertEqual(result["tag"], "pre-sweep-f5")

    def test_sweep_allowed_with_env(self):
        os.environ["KAIZEN_ALLOW_DELETE"] = "1"
        try:
            result = shim.sweep("f5", root=self.root)
            self.assertEqual(result["deleted"], ["old.rs"])
        finally:
            os.environ.pop("KAIZEN_ALLOW_DELETE", None)

    def test_sweep_skips_keep_entries(self):
        shim.manifest_append("f5", "keepme.rs", root=self.root, keep="backcompat")
        result = shim.sweep("f5", root=self.root, allow_delete=True)
        deleted_paths = result["deleted"]
        kept_paths = [k for k, _ in result["kept"]]
        self.assertIn("old.rs", deleted_paths)
        self.assertNotIn("keepme.rs", deleted_paths)
        self.assertIn("keepme.rs", kept_paths)

    def test_sweep_creates_safety_tag(self):
        shim.sweep("f5", root=self.root, allow_delete=True)
        tags = subprocess.check_output(
            ["git", "-C", str(self.root), "tag", "-l", "pre-sweep-*"],
            text=True,
        ).strip().splitlines()
        self.assertIn("pre-sweep-f5", tags)

    def test_sweep_dry_run_changes_nothing(self):
        result = shim.sweep("f5", root=self.root, allow_delete=True, dry_run=True)
        self.assertTrue(result["dry_run"])
        # File still tracked + present
        self.assertTrue(self.shimmed.is_file())
        # No safety tag in dry-run
        tags = subprocess.check_output(
            ["git", "-C", str(self.root), "tag", "-l", "pre-sweep-*"],
            text=True,
        ).strip()
        self.assertEqual(tags, "")

# ─── CLI ─────────────────────────────────────────────────────────────

class TestCli(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()

    def tearDown(self):
        try:
            os.chdir(self._cwd)
        except FileNotFoundError:
            # Original cwd was inside a tmpdir from another test; fall
            # back to a known-good location.
            os.chdir(Path.home())

    def test_init_subcommand(self):
        with tempfile.TemporaryDirectory() as td:
            root = _make_fake_repo(Path(td))
            os.chdir(root)
            rc = shim.main(["init", "demo"])
            self.assertEqual(rc, 0)
            self.assertTrue((root / ".kaizen" / "workflow" / "deletion-manifest-demo.txt").is_file())

    def test_unsupported_carve_returns_1(self):
        # .go is unsupported; main() should return 1 (not 0) on ValueError.
        with tempfile.TemporaryDirectory() as td:
            root = _make_fake_repo(Path(td))
            src = root / "x.go"
            src.write_text("package main")
            os.chdir(root)
            rc = shim.main(["carve", str(src), "y.go", "--slug", "s"])
            self.assertEqual(rc, 1)

    def test_sweep_without_authorization_returns_2(self):
        with tempfile.TemporaryDirectory() as td:
            root = _make_fake_repo(Path(td))
            shim.manifest_append("s", "x.rs", root=root)
            os.environ.pop("KAIZEN_ALLOW_DELETE", None)
            os.chdir(root)
            rc = shim.main(["sweep", "--slug", "s"])
            self.assertEqual(rc, 2)

if __name__ == "__main__":
    unittest.main()
