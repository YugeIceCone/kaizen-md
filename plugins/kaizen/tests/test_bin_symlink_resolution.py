"""Regression test for bin/kaizen-* symlink-resolution.

The `/kaizen:setup` command symlinks every `bin/kaizen-*` into
`~/.local/bin/`. The wrappers must resolve `BASH_SOURCE[0]` through that
symlink before computing the plugin root — otherwise the `source
$_BIN_DIR/../skills/workflow/scripts/_plugin_root.sh` fails with
"No such file or directory".

This was the bug that broke `kaizen-loop` mid-loop on 2026-05-14.
Verifies all kaizen plugin bin wrappers work end-to-end through a
symlinked invocation, not just direct.

Run:
    python3 -m unittest tests.test_bin_symlink_resolution -v
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = PLUGIN_ROOT / "bin"


def _bin_runs_through_symlink(bin_name: str) -> tuple[bool, str]:
    """Symlink the bin into a tmpdir, invoke it via the symlink, return
    (success, stderr). Success means exit 0 or exit 2 (argparse no-args)."""
    real = BIN_DIR / bin_name
    if not real.is_file():
        return False, f"{bin_name} not found at {real}"
    with tempfile.TemporaryDirectory() as td:
        link = Path(td) / bin_name
        link.symlink_to(real)
        env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT)}
        result = subprocess.run(
            [str(link), "--help"],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        # `--help` typically exits 0; some argparse setups exit 0 too.
        # Symlink-resolution failure → exit 1 with the "No such file" msg.
        if "No such file or directory" in result.stderr:
            return False, result.stderr
        return True, result.stderr


class TestBinSymlinkResolution(unittest.TestCase):
    """Every bin/kaizen-* with the new symlink-safe pattern must work
    when invoked via a symlink (mirrors /kaizen:setup's behavior)."""

    PATCHED_BINS = [
        "kaizen-shim", "kaizen-loc", "kaizen-loop",
        # Added 2026-05-18 after audit found 3 bins missing the readlink
        # resolver — kaizen-config / kaizen-export / kaizen-llm-proxy all
        # sourced _plugin_root.sh via $_BIN_DIR/.., resolving to ~/.local/
        # (the symlink dir) instead of the plugin tree.
        "kaizen-config", "kaizen-export", "kaizen-llm-proxy",
    ]

    def test_patched_bins_resolve_through_symlink(self):
        failures = []
        for name in self.PATCHED_BINS:
            ok, stderr = _bin_runs_through_symlink(name)
            if not ok:
                failures.append(f"{name}: {stderr.strip()}")
        self.assertFalse(
            failures,
            "the following patched bins failed symlink invocation:\n"
            + "\n".join(failures),
        )

    def test_patched_bins_contain_realpath_idiom(self):
        """Belt-and-suspenders: source-level check that the readlink idiom
        is present in each patched bin. Catches a future regression where
        someone reverts to the broken pattern."""
        for name in self.PATCHED_BINS:
            content = (BIN_DIR / name).read_text()
            self.assertIn(
                "readlink -f",
                content,
                f"{name} missing readlink -f symlink resolver",
            )


if __name__ == "__main__":
    unittest.main()
