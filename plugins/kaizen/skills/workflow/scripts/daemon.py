#!/usr/bin/env python3
"""kaizen daemon — one-shot worker that runs hash-compare + hygiene.

Designed for cron (or systemd timer). Each invocation:

  1. Hash-compares source dir vs cache dir
     → triggers refresh-cache if drift
  2. Reads remote HEAD via `git ls-remote` (network-light)
     → records notify-state (only auto-pulls if KAIZEN_DAEMON_AUTOPULL=1)
  3. Runs hygiene.py check + auto-applies safe fixes
  4. Appends a structured log line, updates state.json

State + log: `~/.claude/.kaizen-daemon/{state.json,log}`.

## Subcommands

    run                 default — single tick
    install [--interval N]  set up cron entry (default every 30 min)
    uninstall          remove cron entry
    status             print last-run summary + log tail
    log [N]            tail last N lines (default 20)

## Env

    KAIZEN_DAEMON_AUTOPULL   1 to enable auto `git pull origin master`
                              (default 0 — safer: notify only)
    KAIZEN_MARKETPLACE        marketplace dir (default ~/.claude/local-marketplaces/kaizen-md)
    KAIZEN_DAEMON_STATE       state dir (default ~/.claude/.kaizen-daemon)
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
DEFAULT_MARKET = HOME / ".claude" / "local-marketplaces" / "kaizen-md"

# v1.22.0+: state lives at ~/.claude/.kaizen/daemon/. KAIZEN_DAEMON_STATE still wins.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _paths as _p  # noqa: E402

STATE_DIR = Path(os.environ.get("KAIZEN_DAEMON_STATE", _p.DAEMON_DIR))
STATE_FILE = STATE_DIR / "state.json"
LOG_FILE = STATE_DIR / "log"


from _time import iso, utc_now  # M5 dedup


def now() -> dt.datetime:
    return utc_now()


def now_iso() -> str:
    return iso(precision="seconds")


def market_dir() -> Path:
    return Path(os.environ.get("KAIZEN_MARKETPLACE", DEFAULT_MARKET))


def plugin_src() -> Path:
    return market_dir() / "plugins" / "kaizen"


def scripts_dir() -> Path:
    return plugin_src() / "skills" / "kaizen" / "scripts"


# ─── State ───────────────────────────────────────────────────────────


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"runs": 0, "actions": {}}
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {"runs": 0, "actions": {}}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def log_line(level: str, msg: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a") as f:
        f.write(f"{now_iso()} [{level}] {msg}\n")


# ─── Hash compare ────────────────────────────────────────────────────


def dir_hash(p: Path, include_patterns: tuple[str, ...] = (".rs", ".py", ".sh", ".md", ".json", ".toml")) -> str:
    """SHA256 of all file contents under p, deterministic order."""
    h = hashlib.sha256()
    if not p.exists():
        return ""
    for f in sorted(p.rglob("*")):
        if not f.is_file():
            continue
        # Skip caches, state files, etc.
        if any(part in {"__pycache__", ".git", "node_modules"} for part in f.parts):
            continue
        if include_patterns and not any(str(f).endswith(ext) for ext in include_patterns):
            continue
        try:
            h.update(str(f.relative_to(p)).encode())
            h.update(b"\x00")
            h.update(f.read_bytes())
        except OSError:
            continue
    return h.hexdigest()[:16]


def remote_sha() -> str:
    if not (market_dir() / ".git").exists():
        return ""
    try:
        r = subprocess.run(
            ["git", "-C", str(market_dir()), "ls-remote", "origin", "master"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0 and r.stdout:
            return r.stdout.split()[0][:7]
    except Exception:
        pass
    return ""


def local_sha() -> str:
    if not (market_dir() / ".git").exists():
        return ""
    try:
        r = subprocess.run(
            ["git", "-C", str(market_dir()), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            return r.stdout.strip()[:7]
    except Exception:
        pass
    return ""


# ─── Actions ─────────────────────────────────────────────────────────


def run_refresh_cache() -> tuple[bool, str]:
    script = scripts_dir() / "refresh-cache.sh"
    if not script.exists():
        return False, "refresh-cache.sh not found"
    try:
        r = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=60)
        return r.returncode == 0, r.stdout.strip()
    except Exception as e:
        return False, str(e)


def run_pull() -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["git", "-C", str(market_dir()), "pull", "--ff-only", "origin", "master"],
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0, r.stdout.strip() + r.stderr.strip()
    except Exception as e:
        return False, str(e)


def run_hygiene_fix() -> tuple[bool, str]:
    hygiene = scripts_dir() / "hygiene.py"
    if not hygiene.exists():
        return False, "hygiene.py not found"
    try:
        r = subprocess.run(
            ["python3", str(hygiene), "fix"],
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0, r.stdout.strip()
    except Exception as e:
        return False, str(e)


# ─── Cron install ────────────────────────────────────────────────────


CRON_MARKER = "# kaizen daemon (auto-installed by /kaizen:daemon install)"


def cron_install(interval_min: int = 30) -> bool:
    """Install a crontab entry. Idempotent — removes existing first."""
    daemon = scripts_dir() / "daemon.py"
    cron_line = f"*/{interval_min} * * * * python3 {daemon} run >/dev/null 2>&1  {CRON_MARKER}"

    # Read existing crontab (may not exist)
    try:
        cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
        existing = cur.stdout if cur.returncode == 0 else ""
    except FileNotFoundError:
        print("crontab(1) not found — install cron first, or use systemd timer manually", file=sys.stderr)
        return False

    # Strip any existing kaizen daemon line
    kept = "\n".join(line for line in existing.splitlines() if CRON_MARKER not in line)
    new_crontab = (kept.rstrip() + "\n" + cron_line + "\n").lstrip("\n")

    p = subprocess.run(["crontab", "-"], input=new_crontab, text=True, capture_output=True, timeout=5)
    if p.returncode != 0:
        print(f"crontab install failed: {p.stderr}", file=sys.stderr)
        return False
    return True


def cron_uninstall() -> bool:
    try:
        cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
        existing = cur.stdout if cur.returncode == 0 else ""
    except FileNotFoundError:
        return True  # No cron, nothing to remove
    if CRON_MARKER not in existing:
        return True
    kept = "\n".join(line for line in existing.splitlines() if CRON_MARKER not in line)
    p = subprocess.run(["crontab", "-"], input=kept + ("\n" if kept else ""), text=True, capture_output=True, timeout=5)
    return p.returncode == 0


def cron_is_installed() -> bool:
    try:
        cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
        return CRON_MARKER in cur.stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


# ─── Main tick ───────────────────────────────────────────────────────


def tick() -> dict:
    state = load_state()
    state["runs"] = state.get("runs", 0) + 1
    state["last_run"] = now_iso()
    actions = state.setdefault("actions", {})

    log_line("INFO", "daemon tick start")

    # 1. Source vs cache hash
    src_hash = dir_hash(plugin_src())
    state["source_hash"] = src_hash

    # 2. Compare with cache for current version
    version = "?"
    plugin_json = plugin_src() / ".claude-plugin" / "plugin.json"
    if plugin_json.exists():
        try:
            version = json.loads(plugin_json.read_text())["version"]
        except (OSError, json.JSONDecodeError):
            pass
    cache_path = HOME / ".claude" / "plugins" / "cache" / "kaizen-md" / "kaizen" / version
    cache_hash = dir_hash(cache_path) if cache_path.exists() else ""
    state["cache_hash"] = cache_hash

    refresh_needed = (src_hash and (src_hash != cache_hash))
    if refresh_needed:
        log_line("INFO", f"cache drift detected (src={src_hash} cache={cache_hash or 'missing'}) — refreshing")
        ok, out = run_refresh_cache()
        actions["refresh-cache"] = actions.get("refresh-cache", 0) + 1
        log_line("INFO" if ok else "ERROR", f"refresh-cache: {'ok' if ok else 'failed'}")
    else:
        log_line("INFO", f"cache in sync (v{version}, hash={src_hash})")

    # 3. Remote sha (read-only by default)
    local = local_sha()
    remote = remote_sha()
    state["local_sha"] = local
    state["remote_sha"] = remote
    if local and remote and local != remote:
        log_line("INFO", f"upstream ahead (local={local}, remote={remote})")
        if os.environ.get("KAIZEN_DAEMON_AUTOPULL") == "1":
            ok, out = run_pull()
            actions["pull"] = actions.get("pull", 0) + 1
            log_line("INFO" if ok else "ERROR", f"auto-pull: {'ok' if ok else 'failed'} — {out[:200]}")
            if ok:
                # Re-refresh after pull
                run_refresh_cache()
                actions["refresh-cache"] = actions.get("refresh-cache", 0) + 1

    # 4. Hygiene
    ok, out = run_hygiene_fix()
    actions["hygiene"] = actions.get("hygiene", 0) + 1
    log_line("INFO", f"hygiene: {'ok' if ok else 'failed'}")
    for line in out.splitlines():
        if line.strip().startswith("✓") or line.strip().startswith("∘"):
            log_line("INFO", f"  {line.strip()}")

    save_state(state)
    log_line("INFO", "daemon tick complete")
    return state


# ─── Keep-alive watcher (hash-poll loop) ─────────────────────────────


PID_FILE = STATE_DIR / "watcher.pid"
DEFAULT_WATCH_INTERVAL_SEC = 5.0


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False


def watch_status() -> dict:
    if not PID_FILE.exists():
        return {"running": False}
    try:
        pid = int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return {"running": False, "stale_pid_file": True}
    if _pid_alive(pid):
        return {"running": True, "pid": pid}
    return {"running": False, "stale_pid_file": True, "dead_pid": pid}


def watch_stop() -> tuple[bool, str]:
    import time
    st = watch_status()
    if not st.get("running"):
        return False, "not running"
    pid = st["pid"]
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        PID_FILE.unlink(missing_ok=True)
        return False, "process already gone"
    # Wait up to 3s for graceful exit
    for _ in range(30):
        time.sleep(0.1)
        if not _pid_alive(pid):
            PID_FILE.unlink(missing_ok=True)
            return True, f"sent SIGTERM to pid {pid}, exited cleanly"
    # Still alive — force
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    PID_FILE.unlink(missing_ok=True)
    return True, f"SIGTERM ignored; SIGKILL'd pid {pid}"


async def watch_loop(interval: float) -> None:
    """Foreground async loop. Hashes plugin source at interval; runs
    tick() on drift. Stops on SIGTERM/SIGINT."""
    stop_event = asyncio.Event()

    def shutdown(*_):
        log_line("INFO", "watcher received shutdown signal")
        stop_event.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    last_hash = dir_hash(plugin_src())
    log_line("INFO", f"watcher started (pid={os.getpid()}, interval={interval}s, hash={last_hash})")

    # Initial tick — catch any drift accumulated while watcher was offline
    tick()
    state = load_state()
    last_hash = state.get("source_hash", last_hash)

    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break  # shutdown requested
        except asyncio.TimeoutError:
            pass

        h = dir_hash(plugin_src())
        if h != last_hash:
            log_line("INFO", f"hash drift {last_hash} → {h} — running tick")
            tick()
            last_hash = h

    log_line("INFO", "watcher exited cleanly")


def watch_foreground(interval: float) -> int:
    """Run the watcher in foreground (this process). Writes PID file."""
    st = watch_status()
    if st.get("running"):
        print(f"watcher already running (pid {st['pid']}). /kaizen:daemon watch-stop first.", file=sys.stderr)
        return 1
    if st.get("stale_pid_file"):
        PID_FILE.unlink(missing_ok=True)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    try:
        asyncio.run(watch_loop(interval))
        return 0
    finally:
        PID_FILE.unlink(missing_ok=True)


def watch_start(interval: float) -> tuple[bool, int | str]:
    """Spawn the watcher in the background via subprocess, detached
    from the current terminal. Returns (success, pid_or_reason)."""
    st = watch_status()
    if st.get("running"):
        return False, f"already running (pid {st['pid']})"
    if st.get("stale_pid_file"):
        PID_FILE.unlink(missing_ok=True)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    daemon_script = scripts_dir() / "daemon.py"
    log = LOG_FILE.open("a")
    try:
        p = subprocess.Popen(
            ["python3", str(daemon_script), "watch", "--interval", str(interval)],
            stdout=log, stderr=log, stdin=subprocess.DEVNULL,
            start_new_session=True,  # detach from controlling terminal (nohup-equivalent)
        )
    finally:
        log.close()

    # Give the child a moment to write its own PID file (overwrites the parent-recorded one)
    import time
    for _ in range(30):
        time.sleep(0.1)
        st = watch_status()
        if st.get("running") and st["pid"] == p.pid:
            return True, p.pid
    # Even if PID file isn't there yet, the subprocess may still be coming up
    return True, p.pid


# ─── CLI ─────────────────────────────────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser(prog="daemon.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("run", help="single tick")
    inst = sub.add_parser("install", help="install cron entry")
    inst.add_argument("--interval", type=int, default=30, help="minutes between ticks (default 30)")
    sub.add_parser("uninstall", help="remove cron entry")
    sub.add_parser("status", help="print state + last log lines")
    lg = sub.add_parser("log", help="tail log")
    lg.add_argument("n", type=int, nargs="?", default=20)

    # Keep-alive watcher subcommands
    w = sub.add_parser("watch", help="run foreground watcher (hash-poll loop)")
    w.add_argument("--interval", type=float, default=DEFAULT_WATCH_INTERVAL_SEC,
                   help=f"seconds between hash checks (default {DEFAULT_WATCH_INTERVAL_SEC})")
    ws = sub.add_parser("watch-start", help="spawn detached watcher")
    ws.add_argument("--interval", type=float, default=DEFAULT_WATCH_INTERVAL_SEC)
    sub.add_parser("watch-stop", help="stop watcher (SIGTERM, then SIGKILL after 3s)")
    sub.add_parser("watch-status", help="check if watcher is alive")

    args = p.parse_args()
    cmd = args.cmd or "run"

    if cmd == "run":
        state = tick()
        if "last_run" in state:
            print(f"kaizen daemon tick: {state['last_run']} (run #{state['runs']})")

    elif cmd == "install":
        if cron_install(args.interval):
            print(f"  ✓ cron entry installed (every {args.interval} min)")
            print(f"  log:    {LOG_FILE}")
            print(f"  state:  {STATE_FILE}")
            print(f"  unset KAIZEN_DAEMON_AUTOPULL=1 to enable auto-pull from origin (default: notify only)")
        else:
            sys.exit(1)

    elif cmd == "uninstall":
        if cron_uninstall():
            print("  ✓ cron entry removed")
        else:
            sys.exit(1)

    elif cmd == "status":
        installed = cron_is_installed()
        print(f"cron installed: {'yes' if installed else 'no'}")
        state = load_state()
        if state.get("runs"):
            print(f"runs:           {state['runs']}")
            print(f"last_run:       {state.get('last_run', '?')}")
            print(f"local_sha:      {state.get('local_sha', '?')}")
            print(f"remote_sha:     {state.get('remote_sha', '?')}")
            print(f"actions:        {state.get('actions', {})}")
        else:
            print("(no runs yet)")
        if LOG_FILE.exists():
            print("")
            print(f"--- log tail (last 10 lines, {LOG_FILE}) ---")
            with LOG_FILE.open() as f:
                lines = f.readlines()
                for line in lines[-10:]:
                    print(line.rstrip())

    elif cmd == "log":
        if not LOG_FILE.exists():
            print("(no log yet)")
            return
        with LOG_FILE.open() as f:
            lines = f.readlines()
        for line in lines[-args.n:]:
            print(line.rstrip())

    elif cmd == "watch":
        sys.exit(watch_foreground(args.interval))

    elif cmd == "watch-start":
        ok, info = watch_start(args.interval)
        if ok:
            print(f"  ✓ watcher started (pid {info}, interval {args.interval}s)")
            print(f"    log:   {LOG_FILE}")
            print(f"    stop:  kaizen daemon watch-stop")
        else:
            print(f"  ! watch-start: {info}", file=sys.stderr)
            sys.exit(1)

    elif cmd == "watch-stop":
        ok, info = watch_stop()
        if ok:
            print(f"  ✓ {info}")
        else:
            print(f"  ∘ {info}")
            sys.exit(1 if "not running" not in info else 0)

    elif cmd == "watch-status":
        st = watch_status()
        if st.get("running"):
            print(f"  running (pid {st['pid']})")
        else:
            extras = []
            if st.get("stale_pid_file"):
                extras.append("stale pid file present")
            if st.get("dead_pid"):
                extras.append(f"dead pid {st['dead_pid']}")
            tail = f" ({', '.join(extras)})" if extras else ""
            print(f"  not running{tail}")
            sys.exit(1)

    else:
        p.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
