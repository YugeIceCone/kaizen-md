"""Tests for R1: hooks are wired ONLY via plugin-level `hooks/hooks.json`.

The kaizen install MUST NOT inject hooks into the user's
``~/.claude/settings.json``. Plugin-level hooks (auto-discovered by
Claude Code when the plugin is enabled) are the single wiring point.

This guard scans installer / hook / script files for any mutation of
``settings.json`` and any pattern that would write a JSON `hooks` block
to a user-global config. Documentation strings are excluded (a comment
mentioning ``.claude/settings.json`` for context is fine).

Run:
    python3 -m unittest tests.test_hooks_invariant -v
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


# Files allowed to *mention* settings.json (docs, references, changelogs).
# Anything outside this allowlist that mentions settings.json is a candidate
# for review.
DOC_ALLOWLIST_SUFFIXES = (".md", ".txt")
DOC_ALLOWLIST_DIRS = ("references/", "docs/", "CHANGELOG", "README", "ATTRIBUTIONS")


def _is_doc_file(path: Path) -> bool:
    rel = path.relative_to(PLUGIN_ROOT).as_posix()
    if path.suffix in DOC_ALLOWLIST_SUFFIXES:
        return True
    return any(allow in rel for allow in DOC_ALLOWLIST_DIRS)


# Pattern that would indicate a write/mutation, not just a mention.
# Allow `cat`, `read`, `grep`, `echo … to stdout` — block redirection-to-file,
# `python -c "...open(...settings.json...,'w')`, `jq -i settings.json`, etc.
WRITE_PATTERNS = [
    re.compile(r"(?:>>?|tee|>\s*[\"']?)\s*[^|]*?settings\.json", re.IGNORECASE),
    re.compile(r"json\.dump\([^)]*settings\.json", re.IGNORECASE),
    re.compile(r"open\([^)]*settings\.json[^)]*['\"][wax]", re.IGNORECASE),
    re.compile(r"jq\s+[^|]*\.(hooks|plugins|enabledPlugins)[^|]*settings\.json", re.IGNORECASE),
    re.compile(r"sed\s+-i[^|]*settings\.json", re.IGNORECASE),
]


class TestNoSettingsInjection(unittest.TestCase):
    """Guard: kaizen ships hooks via plugin-level hooks.json only."""

    def _scan_files(self) -> list[tuple[Path, str]]:
        """Return (path, line) tuples where a write-to-settings.json was detected."""
        hits: list[tuple[Path, str]] = []
        for sub in ("hooks", "skills/workflow/scripts", "scripts", "bin"):
            base = PLUGIN_ROOT / sub
            if not base.exists():
                continue
            for path in base.rglob("*"):
                if not path.is_file() or _is_doc_file(path):
                    continue
                if path.suffix not in (".sh", ".py"):
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for n, line in enumerate(text.splitlines(), 1):
                    # Skip comments — they explain context, don't execute writes.
                    stripped = line.lstrip()
                    if stripped.startswith("#") or stripped.startswith("//"):
                        continue
                    for pat in WRITE_PATTERNS:
                        if pat.search(line):
                            hits.append((path.relative_to(PLUGIN_ROOT), f"L{n}: {line.strip()}"))
                            break
        return hits

    def test_no_script_writes_settings_json(self):
        hits = self._scan_files()
        msg = (
            "kaizen R1 invariant violated — these scripts appear to write to "
            "settings.json. Hooks must ship via plugin-level hooks.json only.\n"
            + "\n".join(f"  {p}  {line}" for p, line in hits)
        )
        self.assertEqual(hits, [], msg)


class TestPluginHooksManifest(unittest.TestCase):
    """The plugin-level `hooks/hooks.json` is the single hook wiring point."""

    def setUp(self):
        self.manifest = PLUGIN_ROOT / "hooks" / "hooks.json"

    def test_manifest_exists(self):
        self.assertTrue(self.manifest.is_file(), f"missing {self.manifest}")

    def test_manifest_is_valid_json(self):
        json.loads(self.manifest.read_text(encoding="utf-8"))

    def test_manifest_has_hooks_block(self):
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertIn("hooks", data)
        self.assertIsInstance(data["hooks"], dict)
        self.assertGreater(len(data["hooks"]), 0, "no hook events declared")

    def test_manifest_commands_reference_plugin_root(self):
        """Every command in the manifest must use the ${CLAUDE_PLUGIN_ROOT}
        substitution (not an absolute path baked at install time)."""
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        unrooted: list[str] = []
        for event, configs in data["hooks"].items():
            for cfg in configs:
                for h in cfg.get("hooks", []):
                    cmd = h.get("command", "")
                    if cmd and "${CLAUDE_PLUGIN_ROOT}" not in cmd:
                        unrooted.append(f"{event}: {cmd}")
        self.assertEqual(
            unrooted,
            [],
            "every hook command must reference ${CLAUDE_PLUGIN_ROOT} (allows "
            "cross-install portability). Found unrooted: " + ", ".join(unrooted),
        )

    def test_manifest_commands_point_at_existing_files(self):
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        missing: list[str] = []
        for event, configs in data["hooks"].items():
            for cfg in configs:
                for h in cfg.get("hooks", []):
                    cmd = h.get("command", "")
                    # Extract first arg after the interpreter (bash X.sh / node X.js / python3 X.py).
                    m = re.search(r"\$\{CLAUDE_PLUGIN_ROOT\}(\S+)", cmd)
                    if not m:
                        continue
                    rel = m.group(1).lstrip("/")
                    candidate = PLUGIN_ROOT / rel
                    if not candidate.is_file():
                        missing.append(f"{event}: {rel}")
        self.assertEqual(missing, [], f"hooks.json points at missing files: {missing}")


if __name__ == "__main__":
    unittest.main()
