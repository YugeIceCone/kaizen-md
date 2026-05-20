"""kaizen stop_karpathy_check — periodic karpathy diff-check at Stop.

Reads dxm events for the active session to find files modified this
turn (PreToolUse / PostToolUse with tool_name in Edit/Write). Runs
complexity_checker.py on each. Emits systemMessage when WARN-level
issues found. Once-per-session dedupe via dxm event.

Zero new latency on the hot path — only fires at Stop, which is
non-perceptible. Dedupe means at most one fire per session.

Bypass: KAIZEN_KARPATHY_STOP_DISABLE=1.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — kaizen modules still at skills/workflow/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "workflow" / "scripts"))

import _dxm_emit  # noqa: E402
import _session_jsonl as _sj  # noqa: E402

_PLUGIN_ROOT = _SCRIPT_DIR.parent.parent  # was .parent.parent.parent (legacy skills/workflow/scripts/ depth)
_COMPLEXITY_CHECKER = _PLUGIN_ROOT / "scripts" / "karpathy" / "complexity_checker.py"
_EVT_TYPE = "stop_karpathy_check.fired"
_FILE_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})
_EXTENSIONS = (".py", ".ts", ".tsx", ".js", ".jsx")


def _dxm_dir() -> Path:
    env = os.environ.get("KAIZEN_DXM_DIR")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return Path.home() / ".claude" / ".kaizen" / "dxm"


def _already_fired(session_id: str) -> bool:
    path = _dxm_dir() / f"events-{session_id}.jsonl"
    if not path.is_file():
        return False
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if _EVT_TYPE in line:
                    return True
    except OSError:
        pass
    return False


def _modified_files_this_session(session_id: str) -> list[str]:
    """Walk dxm events for Edit/Write tool calls + extract file_path
    inputs. dxm captures tool_name but NOT tool_input — so we fall
    back to the CC JSONL for the file_path."""
    slug = _sj.cwd_to_slug(Path(".").resolve())
    jsonl = Path.home() / ".claude" / "projects" / slug / f"{session_id}.jsonl"
    if not jsonl.is_file():
        return []
    seen: set[str] = set()
    try:
        with jsonl.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("type") != "assistant":
                    continue
                msg = rec.get("message") or {}
                for blk in msg.get("content") or []:
                    if not isinstance(blk, dict):
                        continue
                    if blk.get("type") != "tool_use":
                        continue
                    if blk.get("name") not in _FILE_TOOLS:
                        continue
                    inp = blk.get("input") or {}
                    if not isinstance(inp, dict):
                        continue
                    fp = inp.get("file_path")
                    if isinstance(fp, str) and fp.endswith(_EXTENSIONS):
                        seen.add(fp)
    except OSError:
        return []
    return sorted(seen)


def _run_checker(file_path: str) -> list[str]:
    """Returns lines containing `[WARN]` from complexity_checker output."""
    try:
        r = subprocess.run(
            ["python3", str(_COMPLEXITY_CHECKER), file_path,
             "--threshold", "medium"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [ln for ln in (r.stdout or "").splitlines() if "[WARN]" in ln]


def check(session_id: str | None = None) -> dict:
    if os.environ.get("KAIZEN_KARPATHY_STOP_DISABLE") == "1":
        return {}
    sid = session_id or _sj.discover_active_session_id()
    if not sid:
        return {}
    if _already_fired(sid):
        return {}

    files = _modified_files_this_session(sid)
    if not files:
        return {}

    findings: list[tuple[str, list[str]]] = []
    for f in files:
        warns = _run_checker(f)
        if warns:
            findings.append((f, warns))
    if not findings:
        return {}

    # Mark fired — dedupe FIRST so concurrent invocations don't double-fire.
    _dxm_emit.emit_event(
        _EVT_TYPE, tool_name="kaizen-karpathy-stop",
        payload={"files_checked": len(files),
                  "warn_files": len(findings)},
        session_id=sid,
    )

    lines = [
        f"🟡 kaizen-karpathy: complexity warnings in {len(findings)} of "
        f"{len(files)} file(s) modified this session:",
    ]
    for fp, warns in findings:
        lines.append(f"  • {fp}")
        for w in warns[:3]:  # cap noise
            lines.append(f"      {w.strip()}")
    lines.append(
        "Run `kaizen-karpathy-check` for the full 4-principle review.")
    return {"systemMessage": "\n".join(lines)}


def _cmd_check(args) -> int:
    print(json.dumps(check(session_id=args.session) or {}))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-karpathy-stop",
        description="Stop-hook periodic karpathy complexity check on session-modified files.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("check")
    sc.add_argument("--session", default=None)
    sc.set_defaults(func=_cmd_check)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
