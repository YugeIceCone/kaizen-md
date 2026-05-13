#!/usr/bin/env python3
"""kaizen observe — unified observability across the 6 data-stream layers.

Implements the layer map from the v1.8.0 agent-brief skill + the drill-down
recipe surfaced during v1.9.0 design discussion. Uses v1.9.0's `schemas.py`
dataclasses for typed access where applicable.

## The 6 layers

  L1  Live UI / stderr            ephemeral — no persistent state, skipped
  L2  CC transcript               ~/.claude/projects/<slug>/<sid>.jsonl
  L3  Kaizen trace                ~/.claude/.kaizen-trace/events.jsonl
  L4  Domain logs                 daemon log, proxy log, inbox, compile log
  L5  Per-repo state              .workflow/*, .kaizen/cache/*, .kaizen.toml
  L6  Plugin + global state       installed_plugins, settings, backups, brain

## Dynamic vs deterministic

- **Dynamic**: `query`, `tail`, `stats` — live reads, filterable, real-time.
- **Deterministic**: `snapshot` + `compare` — hash-keyed captures stored to
  disk, byte-identical inputs produce byte-identical outputs. Replay
  arbitrary point-in-time analysis without re-querying.

## Subcommands

    layers                     summarize all 6 layers (size, count, last activity)
    query [--layer N] [--sid SID] [--since 1h] [--src S] [--evt E] [--json]
                               unified query across layers; L3 is the index
    drill <sid> [--out PATH]   guided drill-down — produces Markdown report
                               following the user-specified recipe
                               (L3 stats → L3 events → L2 transcript hint →
                                L4 logs if errors → L5 repo state → L6 plugin)
    snapshot [--name NAME]     deterministic capture of current state across
                               all 6 layers. SHA1-content-keyed.
    compare <snap-a> <snap-b>  diff two snapshots (added/removed/changed)
    report [--since 24h]       markdown summary suitable for handoffs

## Schema validation

Where a layer's records map to a `schemas.py` dataclass (L3 trace events,
L4 inbox messages, L4 daemon state), the reader validates via
`from_dict()`. Invalid records are reported with the validation error
rather than crashing. Unknown shapes fall through as raw JSON.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    import schemas  # type: ignore
except ImportError:
    schemas = None  # graceful — observe works without typed validation


HOME = Path(os.path.expanduser("~"))

# v1.22.0+ unified layout — paths come from _paths (SSOT) so an env override
# or a migration shift is honored everywhere. Falls back to the legacy
# locations if _paths is unavailable for any reason (very old install).
try:
    import _paths as _p  # type: ignore
    TRACE_FILE = _p.TRACE_FILE
    TRACE_DIR = _p.TRACE_DIR
    INBOX_DIR = _p.INBOX_DIR
    DAEMON_DIR = _p.DAEMON_DIR
    BACKUP_BASE = _p.BACKUP_DIR
    SNAPSHOT_DIR = _p.OBSERVE_SNAPSHOTS
except ImportError:
    TRACE_FILE = HOME / ".claude" / ".kaizen" / "trace" / "events.jsonl"
    TRACE_DIR = HOME / ".claude" / ".kaizen" / "trace"
    INBOX_DIR = HOME / ".claude" / ".kaizen" / "inbox"
    DAEMON_DIR = HOME / ".claude" / ".kaizen" / "daemon"
    BACKUP_BASE = HOME / ".claude" / ".kaizen" / "backups"
    SNAPSHOT_DIR = HOME / ".claude" / ".kaizen" / "observe" / "snapshots"

TRANSCRIPT_BASE = HOME / ".claude" / "projects"
PLUGINS_DIR = HOME / ".claude" / "plugins"
SETTINGS_FILE = HOME / ".claude" / "settings.json"
BRAIN_DIR = HOME / ".claude" / "brain"


# ─── Helpers ─────────────────────────────────────────────────────────


from _time import iso  # M5 dedup


def now_iso() -> str:
    return iso()


def parse_since(s: str) -> Optional[dt.datetime]:
    """Same parser as trace.py — supports 1h/30m/7d/Ns + ISO."""
    import re
    m = re.fullmatch(r"(\d+)([smhd])", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        return dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=n * mult)
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


from _jsonl import iter_jsonl  # noqa: E402 — shared helper (M4 dedup)


def dir_size_bytes(p: Path) -> int:
    if not p.exists():
        return 0
    total = 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n = n / 1024
    return f"{n:.1f}TB"


# ─── L2: CC transcript ───────────────────────────────────────────────


def l2_transcript_path(sid: str) -> Optional[Path]:
    """Find the transcript JSONL for a session_id. Walks projects/*/sid.jsonl."""
    if not TRANSCRIPT_BASE.exists():
        return None
    for proj in TRANSCRIPT_BASE.iterdir():
        if not proj.is_dir():
            continue
        candidate = proj / f"{sid}.jsonl"
        if candidate.exists():
            return candidate
    return None


def l2_transcript_summary(sid: str) -> dict:
    p = l2_transcript_path(sid)
    if p is None:
        return {"found": False}
    records = list(iter_jsonl(p))
    return {
        "found": True,
        "path": str(p),
        "records": len(records),
        "size_bytes": p.stat().st_size,
        "first_ts": records[0].get("timestamp") if records else None,
        "last_ts": records[-1].get("timestamp") if records else None,
    }


# ─── L3: Kaizen trace ────────────────────────────────────────────────


def l3_iter_events(since: Optional[dt.datetime] = None):
    """Iterate all trace events (current file + rotated .gz)."""
    files = []
    if TRACE_DIR.exists():
        files = sorted(TRACE_DIR.glob("events-*.jsonl.gz"), key=lambda p: p.stat().st_mtime)
    if TRACE_FILE.exists():
        files.append(TRACE_FILE)
    for f in files:
        for ev in iter_jsonl(f):
            if since is not None:
                try:
                    ev_ts = dt.datetime.fromisoformat(ev.get("ts", "").replace("Z", "+00:00"))
                    if ev_ts < since:
                        continue
                except (ValueError, AttributeError):
                    continue
            # Validate via schemas if available
            if schemas is not None:
                try:
                    te = schemas.from_dict(schemas.TraceEvent, ev)
                    errs = te.validate()
                    if errs:
                        ev["_validation_errors"] = errs
                except Exception:
                    pass
            yield ev


def l3_query(sid: str = "", src: str = "", evt: str = "", since: Optional[dt.datetime] = None) -> list[dict]:
    out = []
    for ev in l3_iter_events(since):
        if sid and ev.get("sid") != sid:
            continue
        if src and ev.get("src") != src:
            continue
        if evt and ev.get("evt") != evt:
            continue
        out.append(ev)
    return out


def l3_stats(since: Optional[dt.datetime] = None, sid: str = "") -> dict:
    by_src: dict = {}
    by_evt: dict = {}
    by_tool: dict = {}
    durations: list = []
    total = 0
    invalid = 0
    for ev in l3_iter_events(since):
        if sid and ev.get("sid") != sid:
            continue
        total += 1
        if "_validation_errors" in ev:
            invalid += 1
        by_src[ev.get("src", "?")] = by_src.get(ev.get("src", "?"), 0) + 1
        by_evt[ev.get("evt", "?")] = by_evt.get(ev.get("evt", "?"), 0) + 1
        if ev.get("tool"):
            by_tool[ev["tool"]] = by_tool.get(ev["tool"], 0) + 1
        if isinstance(ev.get("ms"), (int, float)):
            durations.append(int(ev["ms"]))
    out = {
        "total": total,
        "invalid": invalid,
        "by_src": dict(sorted(by_src.items(), key=lambda x: -x[1])),
        "by_evt": dict(sorted(by_evt.items(), key=lambda x: -x[1])[:10]),
        "by_tool": dict(sorted(by_tool.items(), key=lambda x: -x[1])[:10]),
    }
    if durations:
        import statistics
        out["latency_ms"] = {
            "count": len(durations),
            "p50": int(statistics.median(durations)),
            "p95": int(statistics.quantiles(durations, n=20)[-1]) if len(durations) >= 20 else max(durations),
            "max": max(durations),
        }
    return out


# ─── L4: Domain logs ─────────────────────────────────────────────────


def l4_summary() -> dict:
    out = {}
    daemon_log = DAEMON_DIR / "log"
    if daemon_log.exists():
        with daemon_log.open() as f:
            lines = f.readlines()
        out["daemon_log"] = {
            "path": str(daemon_log),
            "lines": len(lines),
            "size_bytes": daemon_log.stat().st_size,
            "last_line": lines[-1].strip() if lines else None,
        }
    proxy_log = DAEMON_DIR / "llm-proxy.log"
    if proxy_log.exists():
        out["proxy_log"] = {
            "path": str(proxy_log),
            "size_bytes": proxy_log.stat().st_size,
        }
    if INBOX_DIR.exists():
        files = list(INBOX_DIR.glob("*.json"))
        pending = drained = 0
        for f in files:
            try:
                m = json.loads(f.read_text())
                if m.get("drained"):
                    drained += 1
                else:
                    pending += 1
            except (OSError, json.JSONDecodeError):
                pass
        out["inbox"] = {
            "path": str(INBOX_DIR),
            "pending": pending,
            "drained": drained,
            "total": pending + drained,
        }
    compile_log = Path("/tmp/kaizen-compile.log")
    if compile_log.exists():
        out["compile_log"] = {
            "path": str(compile_log),
            "size_bytes": compile_log.stat().st_size,
        }
    return out


# ─── L5: Per-repo state ──────────────────────────────────────────────


def l5_summary(repo: Optional[Path] = None) -> dict:
    if repo is None:
        # Try cwd
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0:
                repo = Path(result.stdout.strip())
        except (subprocess.SubprocessError, OSError):
            pass
    if repo is None or not repo.exists():
        return {"found": False, "reason": "no repo (cwd not in a git tree)"}

    out = {"found": True, "repo": str(repo)}
    config = repo / ".kaizen.toml"
    out["config_present"] = config.exists()

    backlog_json = repo / ".workflow" / "backlog.json"
    if backlog_json.exists():
        try:
            data = json.loads(backlog_json.read_text())
            items = data.get("items", [])
            out["backlog"] = {
                "path": str(backlog_json),
                "items": len(items),
                "by_section": {s: sum(1 for i in items if i.get("section") == s)
                                for s in ("next_up", "in_flight", "done", "parked")},
                "decisions": len(data.get("decisions", [])),
            }
        except (OSError, json.JSONDecodeError):
            out["backlog"] = {"error": "parse failed"}

    state_json = repo / ".workflow" / "state.json"
    if state_json.exists():
        try:
            data = json.loads(state_json.read_text())
            stages = data.get("stages", []) or []
            cur = data.get("current", 0)
            stage = stages[cur] if (isinstance(stages, list) and 0 <= cur < len(stages)) else "(complete or out-of-range)"
            out["workflow_state"] = {
                "routine": data.get("routine"),
                "current_index": cur,
                "current_stage": stage,
                "total_stages": len(stages) if isinstance(stages, list) else 0,
            }
        except (OSError, json.JSONDecodeError):
            pass

    progress = repo / ".workflow" / "progress.md"
    if progress.exists():
        out["progress_log"] = {
            "path": str(progress),
            "size_bytes": progress.stat().st_size,
        }

    cache_dir = repo / ".kaizen" / "cache"
    if cache_dir.exists():
        cache_files = list(cache_dir.glob("*.json"))
        out["cache"] = {
            "path": str(cache_dir),
            "entries": len(cache_files),
            "size_bytes": sum(f.stat().st_size for f in cache_files),
        }
    return out


# ─── L6: Plugin + global state ───────────────────────────────────────


def l6_summary() -> dict:
    out = {}
    installed = PLUGINS_DIR / "installed_plugins.json"
    if installed.exists():
        try:
            data = json.loads(installed.read_text())
            plugins = data.get("plugins", {})
            out["installed_plugins"] = {
                "count": len(plugins),
                "names": sorted(plugins.keys())[:20],
            }
        except (OSError, json.JSONDecodeError):
            pass

    known_market = PLUGINS_DIR / "known_marketplaces.json"
    if known_market.exists():
        try:
            data = json.loads(known_market.read_text())
            out["marketplaces"] = sorted(data.keys()) if isinstance(data, dict) else []
        except (OSError, json.JSONDecodeError):
            pass

    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
            enabled = data.get("enabledPlugins", {})
            out["settings"] = {
                "enabled_count": sum(1 for v in enabled.values() if v),
                "disabled_count": sum(1 for v in enabled.values() if not v),
            }
        except (OSError, json.JSONDecodeError):
            pass

    if BRAIN_DIR.exists():
        notes_dir = BRAIN_DIR / "Notes"
        if notes_dir.exists():
            kaizen_notes = list(notes_dir.glob("*kaizen*"))
            pref_notes = list(notes_dir.glob("pref-*.md"))
            out["brain"] = {
                "kaizen_notes": len(kaizen_notes),
                "pref_notes": len(pref_notes),
            }

    if BACKUP_BASE.exists():
        repos = list(BACKUP_BASE.iterdir())
        total_size = sum(dir_size_bytes(r) for r in repos)
        out["backups"] = {
            "repos": len(repos),
            "total_size_bytes": total_size,
        }
    return out


# ─── Composite operations ────────────────────────────────────────────


def cmd_layers() -> dict:
    """Summary of all 6 layers."""
    return {
        "L1_live_ui": "ephemeral (terminal stderr) — not captured",
        "L2_cc_transcript": {
            "base": str(TRANSCRIPT_BASE),
            "sessions": len(list(TRANSCRIPT_BASE.rglob("*.jsonl"))) if TRANSCRIPT_BASE.exists() else 0,
            "size_bytes": dir_size_bytes(TRANSCRIPT_BASE),
        },
        "L3_kaizen_trace": {
            "current_file": str(TRACE_FILE),
            "current_exists": TRACE_FILE.exists(),
            "current_size_bytes": TRACE_FILE.stat().st_size if TRACE_FILE.exists() else 0,
            "rotated_count": len(list(TRACE_DIR.glob("events-*.jsonl.gz"))) if TRACE_DIR.exists() else 0,
        },
        "L4_domain_logs": l4_summary(),
        "L5_per_repo": l5_summary(),
        "L6_plugin_global": l6_summary(),
    }


def cmd_drill(sid: str) -> str:
    """Guided drill-down report following the canonical recipe."""
    lines = [
        f"# Drill-down report — session `{sid}`",
        f"_Generated: {now_iso()}_",
        "",
        "## Step 1 — L3 trace stats (the fast index)",
        "",
    ]
    stats = l3_stats(sid=sid)
    if stats["total"] == 0:
        lines.append(f"_No L3 events found for sid `{sid}`. Possibilities:_")
        lines.append("- session is in progress and hasn't fired a traced hook yet")
        lines.append("- `KAIZEN_TRACE_DISABLE=1` was set during the session")
        lines.append("- session predates v1.6.0 (when hook trace was added)")
        lines.append("")
    else:
        lines.append(f"- **total events**: {stats['total']}")
        if stats.get("invalid"):
            lines.append(f"- **invalid (schema)**: {stats['invalid']}")
        for src, n in stats["by_src"].items():
            lines.append(f"- src `{src}`: {n}")
        if "latency_ms" in stats:
            lat = stats["latency_ms"]
            lines.append(f"- latency p50/p95/max: {lat['p50']}ms / {lat['p95']}ms / {lat['max']}ms")
        lines.append("")

    lines.append("## Step 2 — L3 event sample (last 5)")
    lines.append("")
    events = l3_query(sid=sid)
    for ev in events[-5:]:
        ts = ev.get("ts", "?")[:23]
        src = ev.get("src", "?")
        evt = ev.get("evt", "?")
        tool = ev.get("tool", "")
        ms = ev.get("ms")
        bits = [f"`{ts}`", f"src={src}", f"evt={evt}"]
        if tool:
            bits.append(f"tool={tool}")
        if ms is not None:
            bits.append(f"ms={ms}")
        lines.append("- " + " ".join(bits))
    if not events:
        lines.append("_(no events)_")
    lines.append("")

    lines.append("## Step 3 — L2 CC transcript")
    lines.append("")
    tx = l2_transcript_summary(sid)
    if tx["found"]:
        lines.append(f"- path: `{tx['path']}`")
        lines.append(f"- records: {tx['records']}")
        lines.append(f"- size: {fmt_bytes(tx['size_bytes'])}")
        if tx.get("first_ts"):
            lines.append(f"- first/last ts: {tx['first_ts']} → {tx['last_ts']}")
    else:
        lines.append(f"_No transcript file found for sid `{sid}` under {TRANSCRIPT_BASE}/. The session may have been wiped or never existed._")
    lines.append("")

    lines.append("## Step 4 — L4 domain logs (if relevant)")
    lines.append("")
    l4 = l4_summary()
    # If any LLM events for this sid → proxy log relevant
    llm_events = [e for e in events if e.get("src") == "llm"]
    if llm_events:
        lines.append(f"- {len(llm_events)} LLM events found → check `~/.claude/.kaizen-daemon/llm-proxy.log`")
    if l4.get("inbox", {}).get("pending", 0):
        lines.append(f"- {l4['inbox']['pending']} pending inbox messages — possibly user input not yet drained")
    if "daemon_log" in l4:
        lines.append(f"- daemon log: {l4['daemon_log']['lines']} lines, last: `{l4['daemon_log'].get('last_line', '')[:80]}`")
    lines.append("")

    lines.append("## Step 5 — L5 per-repo state (cwd)")
    lines.append("")
    l5 = l5_summary()
    if l5["found"]:
        lines.append(f"- repo: `{l5['repo']}`")
        if "backlog" in l5:
            by_section = l5['backlog'].get('by_section', {})
            lines.append(f"- backlog: {l5['backlog']['items']} items "
                          f"(next_up={by_section.get('next_up',0)}, "
                          f"in_flight={by_section.get('in_flight',0)}, "
                          f"done={by_section.get('done',0)}, "
                          f"parked={by_section.get('parked',0)})")
        if "workflow_state" in l5:
            ws = l5["workflow_state"]
            lines.append(f"- workflow: `{ws.get('routine','?')}` at stage `{ws.get('current_stage','?')}`")
        if "cache" in l5:
            lines.append(f"- gate cache: {l5['cache']['entries']} entries, {fmt_bytes(l5['cache']['size_bytes'])}")
    else:
        lines.append(f"_{l5.get('reason', 'no repo state')}_")
    lines.append("")

    lines.append("## Step 6 — L6 plugin/global state")
    lines.append("")
    l6 = l6_summary()
    if "installed_plugins" in l6:
        lines.append(f"- installed plugins: {l6['installed_plugins']['count']}")
    if "settings" in l6:
        lines.append(f"- enabled: {l6['settings']['enabled_count']} / disabled: {l6['settings']['disabled_count']}")
    if "brain" in l6:
        lines.append(f"- brain: {l6['brain']['kaizen_notes']} kaizen-rules, {l6['brain']['pref_notes']} pref-notes")
    if "backups" in l6:
        lines.append(f"- backups: {l6['backups']['repos']} repos, {fmt_bytes(l6['backups']['total_size_bytes'])}")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Recommended next steps")
    lines.append("")
    if stats.get("invalid"):
        lines.append(f"- ⚠ {stats['invalid']} trace events failed schema validation — `kaizen-trace query --src <src> --json | jq` to inspect")
    if tx["found"]:
        lines.append(f"- For full payload, `cat {tx['path']} | jq -s 'map(select(.timestamp))'` — every Claude turn + tool result")
    if not events:
        lines.append("- No L3 events for this sid → look at L2 transcript directly or check if hooks are firing (`kaizen-trace tail`)")
    return "\n".join(lines)


def _hash_layer(d: dict) -> str:
    """SHA1 of the canonical-JSON serialization of a layer's summary."""
    s = json.dumps(d, sort_keys=True, default=str)
    return hashlib.sha1(s.encode()).hexdigest()[:16]


def cmd_snapshot(name: str = "") -> dict:
    """Capture all 6 layers to a content-keyed snapshot file.

    v1.30.0+: the snapshot is routed through the kaizen blob store. The
    user-visible `snapshots/<name>.json` becomes a symlink into
    `~/.claude/.kaizen/blobs/<sha256>`. Identical snapshots dedupe to one
    blob — common when capturing twice in quick succession with no state
    changes between captures."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    state = cmd_layers()
    captured_at = now_iso()
    bundle = {
        "captured_at": captured_at,
        "version": "kaizen-observe v1",
        "layers": state,
        "hashes": {
            "L2": _hash_layer(state["L2_cc_transcript"]),
            "L3": _hash_layer(state["L3_kaizen_trace"]),
            "L4": _hash_layer(state["L4_domain_logs"]),
            "L5": _hash_layer(state["L5_per_repo"]),
            "L6": _hash_layer(state["L6_plugin_global"]),
        },
    }
    bundle["composite_hash"] = _hash_layer(bundle["hashes"])
    fname = name or f"snap-{captured_at.replace(':', '').replace('-', '')[:15]}-{bundle['composite_hash'][:8]}.json"
    ref_path = SNAPSHOT_DIR / (fname if fname.endswith(".json") else fname + ".json")

    payload = json.dumps(bundle, indent=2, default=str).encode("utf-8")
    try:
        import _blobs as _bs  # local import: _blobs depends on _paths which is on sys.path here
        sha = _bs.put_bytes(
            payload,
            kind="observe-snapshot",
            name=ref_path.name,
            ref=ref_path,
            context=f"composite_hash={bundle['composite_hash']}",
        )
        return {"path": str(ref_path), "composite_hash": bundle["composite_hash"], "sha256": sha}
    except ImportError:
        # Very old install — fall back to a plain file write.
        ref_path.write_bytes(payload)
        return {"path": str(ref_path), "composite_hash": bundle["composite_hash"]}


def cmd_compare(a: Path, b: Path) -> dict:
    """Diff two snapshots — return added/removed/changed per layer."""
    try:
        sa = json.loads(a.read_text())
        sb = json.loads(b.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return {"error": f"failed to load: {e}"}

    out = {"a": sa.get("captured_at"), "b": sb.get("captured_at"),
           "composite_changed": sa.get("composite_hash") != sb.get("composite_hash"),
           "layers": {}}
    ha = sa.get("hashes", {})
    hb = sb.get("hashes", {})
    for layer in ("L2", "L3", "L4", "L5", "L6"):
        out["layers"][layer] = {
            "changed": ha.get(layer) != hb.get(layer),
            "a_hash": ha.get(layer),
            "b_hash": hb.get(layer),
        }
    return out


# ─── CLI ─────────────────────────────────────────────────────────────


def main():
    p = argparse.ArgumentParser(prog="observe.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("layers", help="summary of all 6 layers")

    q = sub.add_parser("query", help="unified L3-indexed query")
    q.add_argument("--sid", default="")
    q.add_argument("--src", default="")
    q.add_argument("--evt", default="")
    q.add_argument("--since", default=None)
    q.add_argument("--json", action="store_true")

    s = sub.add_parser("stats", help="L3 stats with schema validation")
    s.add_argument("--since", default=None)
    s.add_argument("--sid", default="")

    d = sub.add_parser("drill", help="guided drill-down report for one session")
    d.add_argument("sid")
    d.add_argument("--out", default="", help="write Markdown to this file (default: stdout)")

    sn = sub.add_parser("snapshot", help="deterministic capture of all 6 layers")
    sn.add_argument("--name", default="")

    cmp = sub.add_parser("compare", help="diff two snapshots")
    cmp.add_argument("a")
    cmp.add_argument("b")

    sub.add_parser("snapshots", help="list saved snapshots")

    args = p.parse_args()

    if not args.cmd or args.cmd == "layers":
        print(json.dumps(cmd_layers(), indent=2, default=str))

    elif args.cmd == "query":
        since = parse_since(args.since) if args.since else None
        results = l3_query(sid=args.sid, src=args.src, evt=args.evt, since=since)
        if args.json:
            for r in results:
                print(json.dumps(r, separators=(",", ":"), default=str))
        else:
            for r in results:
                ts = r.get("ts", "?")[:23]
                src = r.get("src", "?")
                evt = r.get("evt", "?")
                bits = [ts, src, evt]
                if r.get("tool"):
                    bits.append(f"tool={r['tool']}")
                if r.get("ms") is not None:
                    bits.append(f"ms={r['ms']}")
                print("  ".join(bits))
        print(f"\n--- {len(results)} events", file=sys.stderr)

    elif args.cmd == "stats":
        since = parse_since(args.since) if args.since else None
        print(json.dumps(l3_stats(since=since, sid=args.sid), indent=2, default=str))

    elif args.cmd == "drill":
        report = cmd_drill(args.sid)
        if args.out:
            Path(args.out).write_text(report)
            print(f"wrote {args.out}", file=sys.stderr)
        else:
            print(report)

    elif args.cmd == "snapshot":
        result = cmd_snapshot(args.name)
        print(json.dumps(result, indent=2))

    elif args.cmd == "compare":
        a = Path(args.a)
        b = Path(args.b)
        if not a.is_absolute():
            a = SNAPSHOT_DIR / a
        if not b.is_absolute():
            b = SNAPSHOT_DIR / b
        print(json.dumps(cmd_compare(a, b), indent=2, default=str))

    elif args.cmd == "snapshots":
        if not SNAPSHOT_DIR.exists():
            print("(no snapshots dir)")
            return
        snaps = sorted(SNAPSHOT_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
        for s in snaps:
            try:
                d = json.loads(s.read_text())
                print(f"  {s.name}  {d.get('captured_at', '?')}  composite={d.get('composite_hash', '?')[:8]}")
            except (OSError, json.JSONDecodeError):
                print(f"  {s.name}  (parse failed)")

    else:
        p.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
