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
    'required subcommand' error WITHIN 2 seconds.

    Argparse errors are immediate (sub-100ms). Any bin that takes
    longer is doing real work — by definition not a "subcommand
    required" offender, so we return False. Uses Popen +
    start_new_session so on timeout we can killpg() the specific
    child's process group (and any grandchildren it spawned)."""
    import os as _os
    try:
        proc = subprocess.Popen(
            [str(bin_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
    except OSError:
        return False
    try:
        out, err = proc.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            _os.killpg(_os.getpgid(proc.pid), 9)
        except (ProcessLookupError, OSError):
            pass
        proc.wait(timeout=1)
        return False
    if proc.returncode == 0:
        return False
    return bool(re.search(
        r"the following arguments are required|required:|missing required",
        (err or "") + (out or ""),
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
        # Two-stage optimization:
        # (1) cheap I/O FIRST — filter to slashes that pass $ARGUMENTS
        #     through without the `${ARGUMENTS:-<default>}` safety net.
        # (2) parallelize the remaining subprocess spawns. ThreadPool
        #     since subprocess.run is I/O bound (waiting on the child).
        # Pre-opt: ~50 sequential spawns (~15s). Post-opt: ~14 in parallel
        # → ~1s.
        from concurrent.futures import ThreadPoolExecutor

        candidates: list[tuple[str, Path]] = []
        for cmd_md in sorted(_CMDS.glob("*.md")):
            if not _slash_passes_through_args(cmd_md):
                continue
            name = cmd_md.stem
            bin_path = _BINS / f"kaizen-{name}"
            if not bin_path.is_file() or not bin_path.stat().st_mode & 0o111:
                continue
            candidates.append((name, bin_path))

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda pair: (pair[0], _bin_errors_empty_args(pair[1])),
                candidates,
            ))
        offenders = [name for name, errs in results if errs]
        self.assertEqual(
            offenders, [],
            "These slashes pass-through $ARGUMENTS to a bin that errors "
            "on empty args — wrap with `bash -c 'exec ... "
            "${ARGUMENTS:-<safe-verb>}'`. Offenders: "
            f"{', '.join(offenders)}",
        )


if __name__ == "__main__":
    unittest.main()
