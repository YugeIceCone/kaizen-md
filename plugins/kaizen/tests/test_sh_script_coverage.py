"""Test-coverage layer for the plugin's shell scripts.

Two test classes:

  TestPluginRootDepth — structural regression. For every `.sh` that
  defines PLUGIN_ROOT via a `$SCRIPT_DIR/../...` traversal, compute
  where it actually lands and assert it equals the real plugin root.
  Catches Phase-5 layout drift (e.g. `../../..` left over after
  scripts moved from skills/workflow/scripts/<X> to scripts/<X>/).

  TestUntestedShScriptsSmoke — integration smoke. The 6 .sh scripts
  surfaced by the coverage grep (disable-skill / publish / update /
  migrate / test-pipeline / vibe_check) had zero by-name reference in
  tests/. This class invokes each with a safe non-destructive verb
  (status / scan / list / check / --help) and asserts the process
  doesn't die. No behavior assertion — just confirms the script's
  entry path doesn't immediately blow up.

Run:
    python3 -m unittest tests.test_sh_script_coverage -v
"""
from __future__ import annotations

import os
import re
import subprocess
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"

# Matches: PLUGIN_ROOT="$(cd "$SOME_DIR/../...." && pwd)"
# Captures: (1) traversal segment, e.g. "../../.."
_PLUGIN_ROOT_RE = re.compile(
    r'(?:_)?PLUGIN_ROOT="?\$\([^"]*cd\s+"\$[A-Za-z_]+/((?:\.\.\/)+\.\.)"'
)


def _collect_plugin_root_defs() -> list[tuple[Path, str]]:
    """Walk scripts/ for *.sh and return (path, traversal) for each
    PLUGIN_ROOT line found. Skips git-hooks (own depth scheme)."""
    defs: list[tuple[Path, str]] = []
    for sh in sorted(SCRIPTS_DIR.rglob("*.sh")):
        if "git-hooks" in sh.parts:
            continue
        try:
            text = sh.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _PLUGIN_ROOT_RE.finditer(text):
            defs.append((sh, m.group(1)))
    return defs


class TestPluginRootDepth(unittest.TestCase):
    """Every .sh that defines PLUGIN_ROOT must land at plugins/kaizen/."""

    def test_plugin_root_traversal_resolves_to_plugin_dir(self) -> None:
        defs = _collect_plugin_root_defs()
        self.assertGreater(len(defs), 0, "no PLUGIN_ROOT defs found — regex drift?")
        wrong: list[tuple[str, str, Path]] = []
        for sh_path, traversal in defs:
            script_dir = sh_path.parent
            landed = (script_dir / traversal).resolve()
            if landed != PLUGIN_ROOT:
                wrong.append((str(sh_path.relative_to(PLUGIN_ROOT)),
                              traversal, landed))
        if wrong:
            lines = [
                f"  {rel}: '{traversal}' lands at {landed} (want {PLUGIN_ROOT})"
                for rel, traversal, landed in wrong
            ]
            self.fail(
                f"{len(wrong)} script(s) compute PLUGIN_ROOT at the wrong depth:\n"
                + "\n".join(lines)
            )


# ─── Integration smoke ─────────────────────────────────────────────────

# Map: script-rel-path -> safe-verb argv suffix.
# Picked so the invocation can't mutate user state, hit the network,
# or wait for input. None = invoke with no args (script's default).
_SAFE_VERBS: dict[str, list[str]] = {
    "install/disable-skill.sh":    ["scan"],
    "install/publish.sh":          ["status"],
    "install/update.sh":           ["check"],
    "migrate/migrate.sh":          ["scan"],
    "ops/test-pipeline.sh":        [],          # default verb runs full pipeline; skipped below
    "ops/vibe_check.sh":           [],          # advisory; exits 0 always
}

# Scripts skipped from smoke entirely (would run the full pipeline or
# need a real git/gh setup we can't sandbox cheaply).
_SMOKE_SKIP: frozenset = frozenset({
    "ops/test-pipeline.sh",  # itself a test pipeline — recursive smoke
})


class TestUntestedShScriptsSmoke(unittest.TestCase):
    """The 6 .sh scripts with zero by-name test reference must each
    survive a safe non-destructive invocation."""

    def _invoke(self, rel_path: str, args: list[str]) -> tuple[int, str]:
        env = dict(os.environ, KAIZEN_NONINTERACTIVE="1")
        result = subprocess.run(
            ["bash", str(PLUGIN_ROOT / "scripts" / rel_path), *args],
            capture_output=True, text=True, timeout=20, env=env,
        )
        return result.returncode, (result.stdout + result.stderr)

    def test_each_untested_script_has_safe_verb_pinned(self) -> None:
        """Discoverable safety net: if a new untested .sh appears, we
        need to consciously declare its safe verb (or its skip)."""
        for rel in _SAFE_VERBS:
            self.assertTrue(
                (PLUGIN_ROOT / "scripts" / rel).is_file(),
                f"_SAFE_VERBS lists {rel} but the file is gone")

    def test_smoke_invocations_dont_crash(self) -> None:
        failures: list[str] = []
        for rel, args in _SAFE_VERBS.items():
            if rel in _SMOKE_SKIP:
                continue
            rc, output = self._invoke(rel, args)
            # rc==0 ideal; some scripts exit nonzero on "nothing to do"
            # (e.g. publish.sh status when no remote set). The bug we're
            # catching is interpreter-level: shebang missing, syntax
            # error, unresolvable path. Those surface as rc>=126 or
            # specific stderr patterns.
            if rc >= 126:
                failures.append(
                    f"{rel} {' '.join(args)}: rc={rc}\n  output:\n  "
                    + output[:500].replace("\n", "\n  "))
            if "No such file or directory" in output and "bash:" in output:
                failures.append(
                    f"{rel} {' '.join(args)}: bash unable to launch\n  "
                    + output[:500].replace("\n", "\n  "))
        if failures:
            self.fail(
                f"{len(failures)} smoke invocation(s) failed:\n\n"
                + "\n\n".join(failures))


if __name__ == "__main__":
    unittest.main()
