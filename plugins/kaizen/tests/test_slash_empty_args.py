"""Regression — every /kaizen:<name> slash whose body invokes its
backing bin via `$ARGUMENTS` pass-through must NOT error when invoked
empty-args. The fix pattern is the `bash -c 'exec ... ${ARGUMENTS:-<safe-verb>}'`
wrapper that defaults to a safe read-only subcommand.

This defect bit us 3 times in one session (/kaizen:workflow,
/kaizen:gold, /kaizen:coverage, /kaizen:scrape) before this test.
Lock it in.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_CMDS = _KZ_DIR / "commands"
_BINS = _KZ_DIR / "bin"


def _bin_errors_empty_args(bin_path: Path) -> bool:
    """True iff invoking the bin with no args produces an argparse
    'required subcommand' error."""
    try:
        out = subprocess.run(
            [str(bin_path)], capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return out.returncode != 0 and bool(re.search(
        r"the following arguments are required|required:|missing required",
        out.stderr + out.stdout,
    ))


def _slash_passes_through_args(cmd_md: Path) -> bool:
    """True iff the slash body fires its bin with `$ARGUMENTS` directly
    (no `${ARGUMENTS:-<default>}` safety net)."""
    txt = cmd_md.read_text(encoding="utf-8")
    # The vulnerable form: `!`<exec> $ARGUMENTS`` with NO `${ARGUMENTS:-...}` default
    for line in txt.splitlines():
        if not line.startswith("!`"):
            continue
        if "$ARGUMENTS" in line and "${ARGUMENTS:-" not in line:
            return True
    return False


class TestNoBareArgumentsPassthrough(unittest.TestCase):
    """For every commands/<name>.md whose backing bin requires a
    subcommand, the slash body MUST use the `${ARGUMENTS:-<default>}`
    fallback — bare `$ARGUMENTS` pass-through leaks the argparse error
    to the user."""

    def test_no_slash_has_unprotected_args_passthrough_to_strict_bin(self):
        offenders: list[str] = []
        for cmd_md in sorted(_CMDS.glob("*.md")):
            name = cmd_md.stem
            bin_path = _BINS / f"kaizen-{name}"
            if not bin_path.is_file() or not bin_path.stat().st_mode & 0o111:
                continue  # no matching bin → can't apply
            if not _bin_errors_empty_args(bin_path):
                continue  # bin handles empty args itself → safe
            if _slash_passes_through_args(cmd_md):
                offenders.append(name)
        self.assertEqual(
            offenders, [],
            "These slashes pass-through $ARGUMENTS to a bin that errors "
            "on empty args — wrap with `bash -c 'exec ... "
            "${ARGUMENTS:-<safe-verb>}'`. Offenders: "
            f"{', '.join(offenders)}",
        )


if __name__ == "__main__":
    unittest.main()
