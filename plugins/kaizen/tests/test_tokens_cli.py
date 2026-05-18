"""TDD: kaizen-tokens CLI surface (index / ls / show / get).

Cross-venv subprocess pattern (mirror of test_token_extractor.py):
system python does NOT see the PEP-723 tree-sitter deps that
`extract_slots` needs at index time. So every CLI invocation goes
through `uv run --script tokens.py …`, which spins up the script's
inline-deps venv before dispatching argparse.

Fixture mints a throwaway repo with:

  - `.git/`        — sentinel for the V3 CWD-walk discovery
  - `src/foo.rs`   — exercises tree-sitter Rust grammar
  - `src/bar.py`   — exercises tree-sitter Python grammar

The repo root is passed via `KAIZEN_PROJECT_ROOT_OVERRIDE` env so
no real `~/.kaizen/token-map.db` is ever touched (test discipline:
sandbox-via-env).
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_ROOT / "skills" / "workflow" / "scripts" / "tokens.py"


def _run(*args: str, project_root: Path) -> subprocess.CompletedProcess:
    """Invoke tokens.py via `uv run --script` so the PEP-723 venv loads."""
    env = {**os.environ, "KAIZEN_PROJECT_ROOT_OVERRIDE": str(project_root)}
    return subprocess.run(
        ["uv", "run", "--script", str(SCRIPT), *args],
        capture_output=True, text=True, env=env, timeout=120,
    )


class _Fixture(unittest.TestCase):
    """Shared tempdir + planted .git + 2 source files."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / ".git").mkdir()
        (self.root / "src").mkdir()
        (self.root / "src" / "foo.rs").write_bytes(
            b"fn alpha() {}\nfn beta() {}\n"
        )
        (self.root / "src" / "bar.py").write_bytes(b"def x(): pass\n")

    def tearDown(self):
        self._tmp.cleanup()


class TestIndex(_Fixture):
    def test_index_walks_repo_and_creates_db(self):
        r = _run("index", project_root=self.root)
        self.assertEqual(0, r.returncode, f"stderr={r.stderr}")
        self.assertTrue((self.root / ".kaizen" / "token-map.db").exists())


class TestLs(_Fixture):
    def test_ls_lists_files(self):
        _run("index", project_root=self.root)
        r = _run("ls", project_root=self.root)
        self.assertEqual(0, r.returncode, f"stderr={r.stderr}")
        self.assertIn("src/foo.rs", r.stdout)
        self.assertIn("src/bar.py", r.stdout)

    def test_ls_file_shows_slots(self):
        _run("index", project_root=self.root)
        r = _run("ls", "--json", project_root=self.root)
        self.assertEqual(0, r.returncode, f"stderr={r.stderr}")
        files = json.loads(r.stdout)
        foo_id = next(f["file_id"] for f in files if "foo.rs" in f["path"])
        r2 = _run("ls", "--file", str(foo_id), project_root=self.root)
        self.assertEqual(0, r2.returncode, f"stderr={r2.stderr}")
        self.assertIn("alpha", r2.stdout)
        self.assertIn("beta", r2.stdout)

    def test_ls_json_emits_array(self):
        _run("index", project_root=self.root)
        r = _run("ls", "--json", project_root=self.root)
        self.assertEqual(0, r.returncode, f"stderr={r.stderr}")
        payload = json.loads(r.stdout)
        self.assertIsInstance(payload, list)
        self.assertGreater(len(payload), 0)


class TestShow(_Fixture):
    def test_show_returns_body(self):
        _run("index", project_root=self.root)
        r = _run("ls", "--json", project_root=self.root)
        files = json.loads(r.stdout)
        foo_id = next(f["file_id"] for f in files if "foo.rs" in f["path"])
        r2 = _run("show", str(foo_id), "0", project_root=self.root)
        self.assertEqual(0, r2.returncode, f"stderr={r2.stderr}")
        self.assertIn("fn alpha", r2.stdout)


class TestGet(_Fixture):
    def test_get_emits_envelope(self):
        _run("index", project_root=self.root)
        r = _run("ls", "--json", project_root=self.root)
        files = json.loads(r.stdout)
        foo_id = next(f["file_id"] for f in files if "foo.rs" in f["path"])
        r2 = _run(
            "get", str(foo_id), "0", "--json", project_root=self.root,
        )
        self.assertEqual(0, r2.returncode, f"stderr={r2.stderr}")
        payload = json.loads(r2.stdout)
        self.assertEqual(payload["file_id"], foo_id)
        self.assertEqual(payload["slot"], 0)
        self.assertIn("content_hash", payload)
        self.assertIn("kind", payload)


if __name__ == "__main__":
    unittest.main()
