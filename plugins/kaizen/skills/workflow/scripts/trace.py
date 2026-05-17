#!/usr/bin/env python3
"""kaizen trace — unified event log across hooks, agents, LLM, tool calls.

Append-only JSONL at `~/.claude/.kaizen-trace/events.jsonl`. Each line:

    {
      "ts":   "2026-05-12T00:30:00.123Z",
      "src":  "hook" | "agent" | "llm" | "tool" | "user" | "cc",
      "evt":  "PreToolUse" | "invoke" | "complete" | ...,
      "sid":  "<session_id or empty>",
      "tool": "<tool name if applicable>",
      "ms":   <duration_ms or null>,
      "data": { ...arbitrary structured detail... }
    }

Auto-rotate when file > KAIZEN_TRACE_MAX_MB (default 100). Rotated files
named `events-YYYYMMDD-HHMMSS.jsonl.gz`. Default retention: 7 days.

## Subcommands

    event --src <s> --evt <e> [--tool T] [--sid S] [--ms N] [--data JSON]
                                Append one event. From hooks, agents, scripts.
                                stdin JSON is merged into --data if both present.
    tail [-n N] [--src S] [--evt E]
                                Print last N events (default 20), optionally
                                filter by source/event.
    query [--since DURATION] [--src S] [--evt E] [--tool T] [--sid S]
                                Filter events. DURATION = `1h`, `30m`, `7d`, etc.
                                or ISO timestamp.
    stats [--since DURATION]
                                Counts by src/evt/tool, p50/p95 latency
                                where ms is set.
    clear                       Delete all trace data (current + rotated).
    path                        Print log file path.

## Env

    KAIZEN_TRACE_DIR     override dir (default ~/.claude/.kaizen-trace)
    KAIZEN_TRACE_MAX_MB  rotate threshold (default 100)
    KAIZEN_TRACE_RETENTION_DAYS  prune rotated files older than N (default 7)
    KAIZEN_TRACE_DISABLE 1 to silently no-op (for production)
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import os
import re
import shutil
import statistics
import sys
from pathlib import Path


def _trace_dir() -> Path:
    # v1.22.0+: default moved to ~/.claude/.kaizen/indexes/trace/. KAIZEN_TRACE_DIR still wins.
    env = os.environ.get("KAIZEN_TRACE_DIR")
    if env:
        return Path(env)
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _paths as _p  # noqa: E402
    return _p.TRACE_DIR


def _events_file() -> Path:
    return _trace_dir() / "events.jsonl"


def _max_mb() -> int:
    try:
        return int(os.environ.get("KAIZEN_TRACE_MAX_MB", "100"))
    except ValueError:
        return 100


def _retention_days() -> int:
    try:
        return int(os.environ.get("KAIZEN_TRACE_RETENTION_DAYS", "7"))
    except ValueError:
        return 7


def _disabled() -> bool:
    return os.environ.get("KAIZEN_TRACE_DISABLE") == "1"


from _time import iso  # M5 dedup
import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-trace", tool_version="1.0.0")


def _now_iso() -> str:
    return iso()


# ─── Append + rotation ───────────────────────────────────────────────


def append_event(record: dict) -> None:
    if _disabled():
        return
    d = _trace_dir()
    d.mkdir(parents=True, exist_ok=True)
    f = _events_file()
    # Rotate if file too big
    if f.exists():
        size_mb = f.stat().st_size / (1024 * 1024)
        if size_mb >= _max_mb():
            _rotate(f)
    try:
        with f.open("a") as fp:
            fp.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")
    except OSError:
        pass  # never raise from trace; tracing must not break the host


def _rotate(f: Path) -> None:
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    rotated = f.parent / f"events-{ts}.jsonl"
    try:
        f.rename(rotated)
    except OSError:
        return
    # Gzip the rotated file
    try:
        with rotated.open("rb") as src, gzip.open(str(rotated) + ".gz", "wb") as dst:
            shutil.copyfileobj(src, dst)
        rotated.unlink(missing_ok=True)
    except OSError:
        pass
    _prune_rotated()


def _prune_rotated() -> None:
    cutoff = dt.datetime.now(dt.timezone.utc).timestamp() - _retention_days() * 86400
    for p in _trace_dir().glob("events-*.jsonl.gz"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


# ─── Read + parse ────────────────────────────────────────────────────


def _iter_events(path: Path):
    if not path.exists():
        return
    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _all_event_files() -> list[Path]:
    d = _trace_dir()
    if not d.exists():
        return []
    files = sorted(d.glob("events-*.jsonl.gz"), key=lambda p: p.stat().st_mtime)
    if _events_file().exists():
        files.append(_events_file())
    return files


def _parse_duration(s: str) -> dt.datetime | None:
    """Parse `1h`, `30m`, `7d`, `5s`, or ISO timestamp."""
    m = re.fullmatch(r"(\d+)([smhd])", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        return dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=n * mult)
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _matches(ev: dict, src=None, evt=None, tool=None, sid=None, since=None) -> bool:
    if src and ev.get("src") != src:
        return False
    if evt and ev.get("evt") != evt:
        return False
    if tool and ev.get("tool") != tool:
        return False
    if sid and ev.get("sid") != sid:
        return False
    if since:
        try:
            ev_ts = dt.datetime.fromisoformat(ev.get("ts", "").replace("Z", "+00:00"))
            if ev_ts < since:
                return False
        except (ValueError, AttributeError):
            return False
    return True


# ─── Commands ────────────────────────────────────────────────────────


def cmd_event(args) -> None:
    record: dict = {
        "ts": _now_iso(),
        "src": args.src,
        "evt": args.evt,
    }
    if args.sid:
        record["sid"] = args.sid
    if args.tool:
        record["tool"] = args.tool
    if args.ms is not None:
        record["ms"] = args.ms

    data = {}
    if args.data:
        try:
            data = json.loads(args.data)
        except json.JSONDecodeError as e:
            print(f"trace: invalid --data JSON: {e}", file=sys.stderr)
    # Merge stdin JSON if present
    if not sys.stdin.isatty():
        try:
            stdin_text = sys.stdin.read().strip()
            if stdin_text:
                stdin_data = json.loads(stdin_text)
                if isinstance(stdin_data, dict):
                    data = {**data, **stdin_data}
        except (json.JSONDecodeError, OSError):
            pass
    if data:
        record["data"] = data

    append_event(record)


def do_tail(n: int = 20, src: str = "", evt: str = "") -> list[dict]:
    """Programmatic tail — returns most recent N events as dicts.

    Wraps the same iteration `cmd_tail` does so the CLI and the MCP
    server (`state_mcp.py`) serve identical results."""
    files = _all_event_files()
    if not files:
        return []
    buf = []
    for path in reversed(files[-2:]):
        for ev in _iter_events(path):
            if _matches(ev, src=src or None, evt=evt or None):
                buf.append(ev)
                if len(buf) > n * 2:
                    buf = buf[-n:]
    buf.sort(key=lambda e: e.get("ts", ""))
    return buf[-n:]


def cmd_tail(args) -> None:
    events = do_tail(n=args.n, src=args.src or "", evt=args.evt or "")
    if not events:
        print("(empty)")
        return
    for ev in events:
        print(_format_event(ev))


def cmd_query(args) -> None:
    since = None
    if args.since:
        since = _parse_duration(args.since)
        if since is None:
            sys.exit(f"trace: bad --since '{args.since}'")

    out = []
    for path in _all_event_files():
        for ev in _iter_events(path):
            if _matches(ev, src=args.src, evt=args.evt, tool=args.tool,
                        sid=args.sid, since=since):
                out.append(ev)

    if args.json:
        for ev in out:
            print(json.dumps(ev, separators=(",", ":")))
    else:
        for ev in out:
            print(_format_event(ev))
    if args.count:
        print(f"\n--- {len(out)} events", file=sys.stderr)


def cmd_stats(args) -> None:
    since = None
    if args.since:
        since = _parse_duration(args.since)
        if since is None:
            sys.exit(f"trace: bad --since '{args.since}'")

    by_src: dict = {}
    by_evt: dict = {}
    by_tool: dict = {}
    durations: list[int] = []
    total = 0

    for path in _all_event_files():
        for ev in _iter_events(path):
            if not _matches(ev, since=since):
                continue
            total += 1
            by_src[ev.get("src", "?")] = by_src.get(ev.get("src", "?"), 0) + 1
            by_evt[ev.get("evt", "?")] = by_evt.get(ev.get("evt", "?"), 0) + 1
            if ev.get("tool"):
                by_tool[ev["tool"]] = by_tool.get(ev["tool"], 0) + 1
            if isinstance(ev.get("ms"), (int, float)):
                durations.append(int(ev["ms"]))

    out = {
        "total": total,
        "window": args.since or "all",
        "by_src": dict(sorted(by_src.items(), key=lambda x: -x[1])),
        "by_evt": dict(sorted(by_evt.items(), key=lambda x: -x[1])[:15]),
        "by_tool": dict(sorted(by_tool.items(), key=lambda x: -x[1])[:15]),
    }
    if durations:
        out["latency_ms"] = {
            "count": len(durations),
            "p50": int(statistics.median(durations)),
            "p95": int(statistics.quantiles(durations, n=20)[-1]) if len(durations) >= 20 else max(durations),
            "max": max(durations),
        }
    _emit(out, counts={"total": total})


def cmd_clear(args) -> None:
    d = _trace_dir()
    if not d.exists():
        print("(nothing to clear)")
        return
    n = 0
    for p in list(d.glob("events*.jsonl")) + list(d.glob("events-*.jsonl.gz")):
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
    print(f"cleared {n} files from {d}")


def cmd_path(args) -> None:
    print(_events_file())


# ─── Formatting ──────────────────────────────────────────────────────


def _format_event(ev: dict) -> str:
    ts = ev.get("ts", "?")[:23]  # trim ms precision tail
    src = ev.get("src", "?")
    evt = ev.get("evt", "?")
    parts = [f"{ts} {src:6} {evt}"]
    if ev.get("tool"):
        parts.append(f"tool={ev['tool']}")
    if ev.get("ms") is not None:
        parts.append(f"ms={ev['ms']}")
    if ev.get("sid"):
        parts.append(f"sid={ev['sid'][:8]}")
    if ev.get("data"):
        data_str = json.dumps(ev["data"], separators=(",", ":"))
        if len(data_str) > 120:
            data_str = data_str[:117] + "..."
        parts.append(data_str)
    return "  ".join(parts)


# ─── CLI ─────────────────────────────────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser(prog="trace.py",
                                 description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=False)

    ev = sub.add_parser("event", help="append an event")
    ev.add_argument("--src", required=True,
                    choices=["hook", "agent", "llm", "tool", "user", "cc",
                             "plugin", "workflow"])
    ev.add_argument("--evt", required=True)
    ev.add_argument("--tool", default="")
    ev.add_argument("--sid", default="")
    ev.add_argument("--ms", type=int, default=None)
    ev.add_argument("--data", default="")
    ev.set_defaults(func=cmd_event)

    tl = sub.add_parser("tail", help="last N events (default 20)")
    tl.add_argument("-n", type=int, default=20)
    tl.add_argument("--src", default=None)
    tl.add_argument("--evt", default=None)
    tl.set_defaults(func=cmd_tail)

    qr = sub.add_parser("query", help="filter events")
    qr.add_argument("--since", default=None, help="duration (1h, 30m, 7d) or ISO ts")
    qr.add_argument("--src", default=None)
    qr.add_argument("--evt", default=None)
    qr.add_argument("--tool", default=None)
    qr.add_argument("--sid", default=None)
    qr.add_argument("--json", action="store_true")
    qr.add_argument("--count", action="store_true")
    qr.set_defaults(func=cmd_query)

    st = sub.add_parser("stats", help="counts + latency percentiles")
    st.add_argument("--since", default=None)
    st.set_defaults(func=cmd_stats)

    sub.add_parser("clear", help="delete all trace data").set_defaults(func=cmd_clear)
    sub.add_parser("path", help="print log file path").set_defaults(func=cmd_path)

    args = p.parse_args()
    if args.cmd is None:
        # Default: tail
        args.n = 20
        args.src = None
        args.evt = None
        cmd_tail(args)
        return
    args.func(args)


if __name__ == "__main__":
    main()
