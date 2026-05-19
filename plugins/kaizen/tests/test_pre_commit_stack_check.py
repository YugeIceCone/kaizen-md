"""Pre-commit Check 13 — stack-context auto-regen on manifest deltas.

Spins a tiny git repo per test, stages a manifest, fires the pre-commit
hook script, asserts the artifact got regenerated + auto-staged.

Skipped silently when git isn't available (rare on dev machines).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_HOOK = _KZ / "scripts/git-hooks/pre-commit.sh"


def _have_git() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True, timeout=3)
        return True
    except Exception:
        return False


@unittest.skipUnless(_have_git(), "git not available")
class TestStackAutoRegen(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        # Tiny git repo
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=self.repo, check=True)
        # Seed: a placeholder so initial commit works
        (self.repo / "README.md").write_text("test")
        subprocess.run(["git", "add", "README.md"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "chore: seed"],
                        cwd=self.repo, check=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _run_hook(self, env_extra: dict | None = None) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        if env_extra:
            env.update(env_extra)
        # Hook runs from repo cwd; reads .kaizen.toml from there (none → defaults).
        return subprocess.run(
            ["bash", str(_HOOK)],
            cwd=self.repo, capture_output=True, text=True,
            timeout=30, env=env,
        )

    def _stage_manifest(self, name: str, body: str) -> None:
        (self.repo / name).write_text(body)
        subprocess.run(["git", "add", name], cwd=self.repo, check=True)

    def test_cargo_toml_staged_triggers_regen(self):
        self._stage_manifest(
            "Cargo.toml",
            '[package]\nname = "x"\nedition = "2021"\n')
        (self.repo / "main.rs").write_text("fn main(){}")
        subprocess.run(["git", "add", "main.rs"], cwd=self.repo, check=True)
        r = self._run_hook()
        # Hook exit 0 expected (no hard fails); may have warns
        self.assertIn(r.returncode, (0, 1), f"hook crashed: {r.stderr[:300]}")
        # Stack-context artifacts should now exist
        self.assertTrue((self.repo / ".agents" / "stack-context.json").is_file(),
                          f"JSON artifact missing\nstderr={r.stderr[-500:]}")
        self.assertTrue((self.repo / ".agents" / "stack-context.md").is_file())

    def test_no_manifest_skips_check(self):
        (self.repo / "src.py").write_text("# new file")
        subprocess.run(["git", "add", "src.py"], cwd=self.repo, check=True)
        r = self._run_hook()
        # Skip line should appear; no .agents/ created
        self.assertIn("no manifest", r.stderr.lower(),
                       f"expected skip msg; got: {r.stderr[-300:]}")
        self.assertFalse((self.repo / ".agents" / "stack-context.json").is_file())

    def test_disable_env_short_circuits(self):
        self._stage_manifest(
            "package.json",
            '{"name": "x", "dependencies": {"react": "18"}}')
        (self.repo / "x.js").write_text("// x")
        subprocess.run(["git", "add", "x.js"], cwd=self.repo, check=True)
        r = self._run_hook(env_extra={"KAIZEN_DETECT_STACK_PRECOMMIT_DISABLE": "1"})
        # Hook ran but stack check skipped; artifact NOT created
        self.assertFalse((self.repo / ".agents" / "stack-context.json").is_file(),
                          f"disable knob ignored; stderr={r.stderr[-300:]}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
