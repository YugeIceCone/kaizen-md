"""Every bin/kaizen-* wrapper must `exec` a target file that exists on disk.

A wrapper that delegates via `exec bash`/`exec python3`/`exec uv run --script`
points at a script under `$PLUGIN_ROOT/...`. If that path doesn't resolve,
the wrapper is broken before it ever runs its target.

Run:
    python3 -m unittest tests.test_bin_wrapper_targets -v
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = PLUGIN_ROOT / "bin"

_EXEC_RE = re.compile(
    r'''^\s*exec\s+(?:bash|python3|uv\s+run\s+--script)\s+"\$_?PLUGIN_ROOT/([^"]+)"'''
)


def _extract_targets(wrapper: Path) -> list[str]:
    targets: list[str] = []
    for line in wrapper.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        m = _EXEC_RE.match(line)
        if m:
            targets.append(m.group(1))
    return targets


class TestBinWrapperTargetsExist(unittest.TestCase):
    def test_every_exec_target_resolves(self) -> None:
        wrappers = sorted(BIN_DIR.glob("kaizen-*"))
        self.assertGreater(len(wrappers), 0, "no bin/kaizen-* wrappers found")

        broken: list[tuple[str, str]] = []
        for wrapper in wrappers:
            if not wrapper.is_file():
                continue
            for target_rel in _extract_targets(wrapper):
                target_abs = PLUGIN_ROOT / target_rel
                if not target_abs.exists():
                    broken.append((wrapper.name, target_rel))

        if broken:
            lines = [f"  {name} -> {rel}" for name, rel in broken]
            self.fail(
                f"{len(broken)} bin wrapper(s) delegate to missing target file:\n"
                + "\n".join(lines)
            )


if __name__ == "__main__":
    unittest.main()
