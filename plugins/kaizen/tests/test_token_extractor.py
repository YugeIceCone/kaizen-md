"""TDD: tree-sitter slot extraction across Rust, Python, fallback,
exclusions, and LF normalization.

Two-tier test pattern (system python doesn't see uv-isolated tree-sitter
deps — same trick as test_token_db.py):

  * Pure helpers (`is_extractable`, `normalize_lf`, `detect_language`)
    tested in-process via direct import.
  * `extract_slots` tested via subprocess invocation of the script's
    `__main__ --test` JSON-dump mode, which runs inside the script's
    PEP-723 uv venv where tree-sitter IS available.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "skills" / "workflow" / "scripts" / "_token_extractor.py"
)

# In-process import of the pure helpers (no tree-sitter needed for these).
sys.path.insert(0, str(SCRIPT.parent))
from _token_extractor import is_extractable, normalize_lf, detect_language  # noqa: E402


def _extract_via_uv(path: str, body: bytes, language):
    """Invoke the extractor's __main__ --test mode via uv (which loads
    the PEP-723 tree-sitter deps). Returns the parsed JSON slot list.
    """
    payload = json.dumps({
        "path": path,
        "body_hex": body.hex(),
        "language": language,
    })
    r = subprocess.run(
        ["uv", "run", "--script", str(SCRIPT), "--test"],
        input=payload, capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise AssertionError(f"extractor failed: {r.stderr}")
    return json.loads(r.stdout)


# ─── Pure helper tests (in-process, no heavy deps) ───────────────────


class TestExclusions(unittest.TestCase):
    """V21/V22 exclusion regexes."""

    def test_target_dir_skipped(self):
        self.assertFalse(is_extractable(Path("target/debug/foo.rs")))

    def test_node_modules_skipped(self):
        self.assertFalse(is_extractable(Path("node_modules/foo/index.js")))

    def test_swp_skipped(self):
        self.assertFalse(is_extractable(Path("src/foo.rs.swp")))

    def test_normal_src_extractable(self):
        self.assertTrue(is_extractable(Path("src/foo.rs")))

    def test_dot_kaizen_root_skipped(self):
        self.assertFalse(is_extractable(Path(".kaizen/workflow/backlog.json")))

    def test_dot_kaizen_progress_skipped(self):
        self.assertFalse(is_extractable(Path(".kaizen/workflow/progress.md")))

    def test_dot_kaizen_nested_skipped(self):
        self.assertFalse(is_extractable(Path("repo/.kaizen/state.yaml")))


class TestLFNormalization(unittest.TestCase):
    """V23 — line-ending normalization for cross-platform blake3 stability."""

    def test_crlf_normalized(self):
        self.assertEqual(normalize_lf(b"line1\r\nline2\r\n"), b"line1\nline2\n")

    def test_lf_unchanged(self):
        self.assertEqual(normalize_lf(b"line1\nline2\n"), b"line1\nline2\n")


class TestDetectLanguage(unittest.TestCase):
    def test_rust_extension(self):
        self.assertEqual(detect_language(Path("x.rs")), "rust")

    def test_python_extension(self):
        self.assertEqual(detect_language(Path("x.py")), "python")

    def test_unknown_extension(self):
        self.assertIsNone(detect_language(Path("x.txt")))


# ─── Subprocess-driven extraction tests (uv-venv with tree-sitter) ───


class TestRustExtraction(unittest.TestCase):
    def test_fn_extracted_as_slot(self):
        src = b"fn bar() {}\nfn baz() {}\n"
        slots = _extract_via_uv("x.rs", src, "rust")
        kinds = [s["kind"] for s in slots]
        self.assertEqual(kinds[0], "body")
        self.assertEqual(kinds[1], "path")
        self.assertIn("fn", kinds[2:])
        names = [s["name"] for s in slots if s["kind"] == "fn"]
        self.assertEqual(sorted(names), ["bar", "baz"])

    def test_struct_extracted(self):
        src = b"struct Foo { x: i32 }\n"
        slots = _extract_via_uv("x.rs", src, "rust")
        kinds = [s["kind"] for s in slots if s["kind"] not in ("body", "path")]
        self.assertIn("struct", kinds)


class TestPythonExtraction(unittest.TestCase):
    def test_def_extracted(self):
        src = b"def foo():\n    return 1\n\ndef bar():\n    pass\n"
        slots = _extract_via_uv("x.py", src, "python")
        names = [s["name"] for s in slots if s["kind"] == "fn"]
        self.assertEqual(sorted(names), ["bar", "foo"])

    def test_class_method_has_parent_qualifier(self):
        src = b"class C:\n    def m(self): pass\n"
        slots = _extract_via_uv("x.py", src, "python")
        method = next((s for s in slots if s["kind"] == "fn" and s["name"] == "m"), None)
        self.assertIsNotNone(method)
        self.assertEqual(method["parent"], "C")


class TestFallback(unittest.TestCase):
    def test_no_grammar_returns_body_and_path_only(self):
        slots = _extract_via_uv("x.txt", b"hello", None)
        kinds = [s["kind"] for s in slots]
        self.assertEqual(kinds, ["body", "path"])


if __name__ == "__main__":
    unittest.main()
