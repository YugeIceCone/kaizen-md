"""Tests for kaizen-plugin-docs umbrella subcommands.

Per user 2026-05-18 — "consolidate docs related systems/logic under
this new one." Adds dispatch subcommands that delegate to existing
docs-related bins:

  kaizen-plugin-docs frontmatter     → kaizen-frontmatter
  kaizen-plugin-docs links           → kaizen-md-link-rot
  kaizen-plugin-docs dupes           → kaizen-md-dupes
  kaizen-plugin-docs whitespace      → kaizen-md-whitespace
  kaizen-plugin-docs heading-depth   → kaizen-md-heading-depth

Sibling bins stay for back-compat (consolidated-CLI-parent pattern,
matches kaizen-brain / kaizen-statusline shape).
"""
from __future__ import annotations

import sys
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))


def test_umbrella_registry_has_all_5_subcommands():
    from plugin_docs import UMBRELLA_BINS
    assert set(UMBRELLA_BINS) == {
        "frontmatter", "links", "dupes", "whitespace", "heading-depth",
    }


def test_each_subcommand_maps_to_existing_bin():
    """Every umbrella subcommand points at a real bin file."""
    from plugin_docs import UMBRELLA_BINS
    bin_dir = _KZ_DIR / "bin"
    for sub, bin_name in UMBRELLA_BINS.items():
        bin_path = bin_dir / bin_name
        assert bin_path.is_file(), \
            f"{sub} maps to {bin_name} but bin doesn't exist"


def test_subcommand_dispatch_uses_correct_bin_name():
    """The dispatcher fn resolves the bin name + passes args through."""
    from plugin_docs import resolve_umbrella_bin
    assert resolve_umbrella_bin("frontmatter") == "kaizen-frontmatter"
    assert resolve_umbrella_bin("links") == "kaizen-md-link-rot"
    assert resolve_umbrella_bin("dupes") == "kaizen-md-dupes"
    assert resolve_umbrella_bin("whitespace") == "kaizen-md-whitespace"
    assert resolve_umbrella_bin("heading-depth") == "kaizen-md-heading-depth"


def test_unknown_subcommand_resolves_to_none():
    from plugin_docs import resolve_umbrella_bin
    assert resolve_umbrella_bin("nope") is None


def test_help_lists_umbrella_subcommands():
    """`kaizen-plugin-docs --help` should mention all umbrella subcommands
    so users discover the consolidation."""
    import subprocess
    r = subprocess.run(
        [sys.executable, str(_KZ_DIR / "skills/workflow/scripts/plugin_docs.py"),
         "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert r.returncode == 0
    out = r.stdout + r.stderr
    for sub in ("frontmatter", "links", "dupes", "whitespace", "heading-depth"):
        assert sub in out, f"--help missing umbrella subcommand: {sub}"


def test_scan_and_list_still_work():
    """Pre-existing subcommands (scan + list) are NOT shadowed by the
    new umbrella subcommands."""
    import subprocess
    for sub in ("scan", "list"):
        r = subprocess.run(
            [sys.executable, str(_KZ_DIR / "skills/workflow/scripts/plugin_docs.py"),
             sub, "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert r.returncode == 0, f"{sub} broke: {r.stderr}"
