#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["watchdog>=4.0"]
# ///
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
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

HOME = Path(os.path.expanduser("~"))

# Resolved uv binary. daemon.py is a `uv run --script` script (watchdog
# in its `# /// script` block); cron + the watch-start Popen re-invoke
# it through uv. Cron's PATH is minimal, so resolve to an absolute path
# at import time — falls back to bare "uv" when not found (interactive
# shells still resolve it via PATH).
UV = shutil.which("uv") or "uv"

# v1.22.0+: state lives at ~/.claude/.kaizen/data/daemon/. KAIZEN_DAEMON_STATE still wins.
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
    # SSOT: _paths.plugin_index_root() resolves KAIZEN_PLUGIN_INDEX_ROOT
    # / KAIZEN_MARKETPLACE. plugin_src() still appends plugins/kaizen.
    return _p.plugin_index_root()


def plugin_src() -> Path:
    return market_dir() / "plugins" / "kaizen"


def scripts_dir() -> Path:
    return plugin_src() / "skills" / "workflow" / "scripts"


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


def _run_index_refresh() -> tuple[bool, str]:
    """Step-5 of tick(): incremental loc + onboard index of the plugin
    root. Both indexers are sha/mtime incremental — cheap when nothing
    changed. Gated by KAIZEN_DAEMON_INDEX_DISABLE."""
    if os.environ.get("KAIZEN_DAEMON_INDEX_DISABLE") == "1":
        return True, "skipped (KAIZEN_DAEMON_INDEX_DISABLE=1)"
    root = _p.plugin_index_root()
    scripts = scripts_dir()
    results = []
    for label, argv in (
        ("loc", ["python3", str(scripts / "loc_index.py"),
                 "index", "--root", str(root)]),
        ("onboard", ["uv", "run", "--script", str(scripts / "onboard_index.py"),
                     "index", "--root", str(root)]),
    ):
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=600)
            results.append(f"{label}={'ok' if r.returncode == 0 else 'fail'}")
        except (FileNotFoundError, subprocess.SubprocessError) as e:
            results.append(f"{label}=err({e})")
    return True, " ".join(results)


def index_status(root: Path | None = None) -> dict:
    """Freshness self-check: compare loc.db's last_indexed_ts against the
    newest source-file mtime under root."""
    import sqlite3
    root = root or _p.plugin_index_root()
    db = root / ".kaizen" / "loc.db"
    if not db.exists():
        return {"fresh": False, "reason": "never indexed (no loc.db)"}
    try:
        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT value FROM loc_meta WHERE key = 'last_indexed_ts'"
        ).fetchone()
        conn.close()
    except sqlite3.Error as e:
        return {"fresh": False, "reason": f"loc.db unreadable: {e}"}
    if not row:
        return {"fresh": False, "reason": "no last_indexed_ts in loc.db"}
    indexed = dt.datetime.fromisoformat(row[0])
    newest = 0.0
    for p in root.rglob("*"):
        parts = set(p.parts)
        if {".kaizen", ".git", "__pycache__", "node_modules", "target"} & parts:
            continue
        if p.is_file():
            newest = max(newest, p.stat().st_mtime)
    newest_dt = dt.datetime.fromtimestamp(newest, dt.timezone.utc)
    behind = (newest_dt - indexed).total_seconds()
    if behind > 1.0:
        return {"fresh": False, "reason": f"stale ({int(behind)}s behind)"}
    return {"fresh": True, "reason": "up to date"}


# ─── Cron install ────────────────────────────────────────────────────


CRON_MARKER = "# kaizen daemon (auto-installed by /kaizen:daemon install)"


def cron_install(interval_min: int = 30) -> bool:
    """Install a crontab entry. Idempotent — removes existing first."""
    daemon = scripts_dir() / "daemon.py"
    # Cron supervises the persistent watch daemon. `watch-start` is
    # idempotent (pidfile check) — a no-op if alive, resurrect if dead.
    # daemon.py runs via `uv run --script` (watchdog dep); UV is the
    # absolute uv path since cron's PATH does not include ~/.local/bin.
    periodic = (f"*/{interval_min} * * * * {UV} run --script {daemon} watch-start "
                f">/dev/null 2>&1  {CRON_MARKER}")
    reboot = (f"@reboot {UV} run --script {daemon} watch-start "
              f">/dev/null 2>&1  {CRON_MARKER}")
    cron_line = periodic + "\n" + reboot

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

    # 5. Index refresh — keep the plugin loc/onboard index fresh.
    if os.environ.get("KAIZEN_DAEMON_INDEX_DISABLE") != "1":
        ok, out = _run_index_refresh()
        actions["index"] = actions.get("index", 0) + 1
        log_line("INFO", f"index-refresh: {out}")

    save_state(state)
    log_line("INFO", "daemon tick complete")
    return state


# ─── Keep-alive watcher (hash-poll loop) ─────────────────────────────


PID_FILE = STATE_DIR / "watcher.pid"
DEFAULT_WATCH_INTERVAL_SEC = 5.0

# Self-trigger guard: the index DBs live at <root>/.kaizen/*.db INSIDE
# the watched root — without these ignores the watcher would see its
# own DB write and loop forever. Also skip vcs / build noise.
_WATCH_IGNORE = ["*/.kaizen/*", "*/.git/*", "*/__pycache__/*",
                 "*/node_modules/*", "*/target/*"]
# 0.5s = 2Hz wake-up — was 0.05s (20Hz) which caused sustained 99% CPU
# from the threading.Event + lock + iteration overhead alone, even when
# `pending` was empty. 0.5s is indistinguishable from 0.05s in user
# perceived latency for index refresh. Override via env if needed.
_WATCH_DEBOUNCE_SEC = 0.5
_WATCH_DEBOUNCE_FLOOR = 0.05
_WATCH_DEBOUNCE_CEILING = 5.0
_SEMANTIC_THROTTLE_SEC = 5.0


def _resolve_debounce() -> float:
    """Return the actual debounce seconds — env override (clamped) or
    module default. Pure; safe to call repeatedly."""
    raw = os.environ.get("KAIZEN_WATCH_DEBOUNCE_SEC")
    if not raw:
        return _WATCH_DEBOUNCE_SEC
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return _WATCH_DEBOUNCE_SEC
    if v < _WATCH_DEBOUNCE_FLOOR:
        return _WATCH_DEBOUNCE_FLOOR
    if v > _WATCH_DEBOUNCE_CEILING:
        return _WATCH_DEBOUNCE_CEILING
    return v


def _should_spawn_semantic(
    *, prev_proc, last_spawn: float, now: float, throttle_sec: float,
) -> bool:
    """True iff we should spawn the next semantic refresh subprocess.
    Two short-circuits:
      - prev_proc still running (poll() is None) → skip; avoids zombie
        accumulation and concurrent torch processes.
      - throttle window still open → skip.
    Pure; the caller does the spawn + bookkeeping."""
    if prev_proc is not None and prev_proc.poll() is None:
        return False
    if (now - last_spawn) < throttle_sec:
        return False
    return True


def _watchdog_available() -> bool:
    try:
        import watchdog  # noqa: F401
        return True
    except ImportError:
        return False


def _run_watchdog_foreground(stop_event) -> None:
    """watchdog-backed watch path. Runs on the calling thread; the
    observer runs callbacks on its own background thread which only
    mutates `pending` under a lock. The loc.db conn is created and used
    ONLY on this thread (sqlite3 conns are thread-affine)."""
    import threading
    from watchdog.observers import Observer
    from watchdog.events import PatternMatchingEventHandler
    sys.path.insert(0, str(scripts_dir()))
    import loc_index  # noqa: E402

    root = _p.plugin_index_root()
    conn = loc_index.open_db(root, create=True)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=3000")

    pending: set[str] = set()
    lock = threading.Lock()

    class _Handler(PatternMatchingEventHandler):
        def on_any_event(self, event):
            if event.is_directory:
                return
            with lock:
                pending.add(event.src_path)
                dest = getattr(event, "dest_path", None)
                if dest:
                    pending.add(dest)

    handler = _Handler(ignore_patterns=_WATCH_IGNORE, ignore_directories=True)
    observer = Observer()
    observer.schedule(handler, str(root), recursive=True)
    observer.start()
    log_line("INFO", f"watchdog observer started on {root}")

    # Initial catch-up tick (full loc + onboard) for offline drift.
    tick()
    last_semantic = time.monotonic()
    semantic_dirty = False
    prev_semantic_proc = None   # tracked so we don't accumulate zombies
    debounce = _resolve_debounce()
    log_line("INFO", f"watch loop debounce={debounce}s semantic_throttle={_SEMANTIC_THROTTLE_SEC}s")
    _diag_iter = 0
    _diag_last_log = time.monotonic()
    _diag_paths_seen = 0
    try:
        # The debounce window IS the wait interval — coalesces a burst.
        while not stop_event.wait(debounce):
            with lock:
                paths = list(pending)
                pending.clear()
            _diag_iter += 1
            _diag_paths_seen += len(paths)
            now_d = time.monotonic()
            if (now_d - _diag_last_log) >= 10.0:
                # Sample a few paths so we can SEE what's spamming.
                sample = list(paths)[:3] if paths else []
                log_line(
                    "INFO",
                    f"watch-diag iter={_diag_iter} "
                    f"paths_processed={_diag_paths_seen} "
                    f"over {now_d - _diag_last_log:.1f}s "
                    f"sample={sample}",
                )
                _diag_iter = 0
                _diag_paths_seen = 0
                _diag_last_log = now_d
            # Reap finished semantic-refresh child (fire-and-forget had
            # been leaking zombies — see test_daemon_helpers).
            if prev_semantic_proc is not None and prev_semantic_proc.poll() is not None:
                prev_semantic_proc = None
            if not paths:
                continue
            for path in paths:
                try:
                    p = Path(path)
                    if p.exists():
                        loc_index.index_one_file(conn, root, p)
                    else:
                        rel = os.path.relpath(path, str(root))
                        loc_index.delete_file(conn, rel)
                except Exception as e:  # never let one bad file kill the loop
                    log_line("ERROR", f"watch index {path}: {e}")
            conn.commit()
            semantic_dirty = True
            # Throttled background semantic refresh — off the loc path.
            # The pure helper handles both the throttle window AND the
            # "previous still running" short-circuit.
            now = time.monotonic()
            if semantic_dirty and _should_spawn_semantic(
                prev_proc=prev_semantic_proc, last_spawn=last_semantic,
                now=now, throttle_sec=_SEMANTIC_THROTTLE_SEC,
            ):
                prev_semantic_proc = _spawn_semantic_refresh(root)
                last_semantic = now
                semantic_dirty = False
    finally:
        observer.stop()
        observer.join()
        conn.close()
        log_line("INFO", "watchdog observer stopped")


def _spawn_semantic_refresh(root: Path):
    """Background incremental onboard index — torch is seconds, runs
    detached, never on the loc critical path. Returns the Popen handle
    so the caller can poll() it (avoids zombie accumulation)."""
    scripts = scripts_dir()
    try:
        return subprocess.Popen(
            ["uv", "run", "--script", str(scripts / "onboard_index.py"),
             "index", "--root", str(root)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (FileNotFoundError, OSError) as e:
        log_line("ERROR", f"semantic refresh spawn failed: {e}")
        return None


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

    last_hash = dir_hash(_p.plugin_index_root())
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

        h = dir_hash(_p.plugin_index_root())
        if h != last_hash:
            log_line("INFO", f"hash drift {last_hash} → {h} — running tick")
            tick()
            last_hash = h

    log_line("INFO", "watcher exited cleanly")


def watch_foreground(interval: float) -> int:
    """Run the watcher in foreground (this process). Writes PID file.
    Uses watchdog (event-driven, ms-latency loc) when available; falls
    back to the async hash-poll loop otherwise."""
    st = watch_status()
    if st.get("running"):
        print(f"watcher already running (pid {st['pid']}). "
              f"/kaizen:daemon watch-stop first.", file=sys.stderr)
        return 1
    if st.get("stale_pid_file"):
        PID_FILE.unlink(missing_ok=True)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    try:
        if _watchdog_available():
            import threading
            stop_event = threading.Event()

            def shutdown(*_):
                log_line("INFO", "watcher received shutdown signal")
                stop_event.set()

            signal.signal(signal.SIGTERM, shutdown)
            signal.signal(signal.SIGINT, shutdown)
            _run_watchdog_foreground(stop_event)
        else:
            log_line("INFO", "watchdog not installed — using hash-poll fallback")
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
            [UV, "run", "--script", str(daemon_script),
             "watch", "--interval", str(interval)],
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


# ─── systems-check — keep-alive for the 4 runtime systems (2026-05-18) ──

_TRACKED_SYSTEMS = (
    # name, env_name (None → fall back to default), default segment(s)
    ("hooks",    None,                    None),
    ("trace",    "KAIZEN_TRACE_DIR",      ("indexes", "trace")),
    ("dxm",      "KAIZEN_DXM_DIR",        ("dxm",)),
    ("observer", "KAIZEN_OBSERVER_DIR",   ("observer",)),
)


def _check_one(name: str, env_name, default_segs) -> dict:
    """Probe a single runtime system; return state dict."""
    if name == "hooks":
        # Hooks aren't a sink — they're a config. Treat hooks.json presence
        # as the proxy. scripts_dir() = plugin_src/skills/workflow/scripts;
        # hooks.json lives at plugin_src/hooks/hooks.json — three .parents up.
        hooks_json = scripts_dir().parent.parent.parent / "hooks" / "hooks.json"
        st = {"name": name, "kind": "config",
               "exists": hooks_json.is_file(),
               "path": str(hooks_json), "count": 0}
        if hooks_json.is_file():
            st["size"] = hooks_json.stat().st_size
            st["last_mtime"] = hooks_json.stat().st_mtime
        return st
    # Append-only jsonl sink
    import os as _os
    env_val = _os.environ.get(env_name) if env_name else None
    if env_val:
        sink_dir = Path(env_val)
    else:
        sink_dir = Path.home() / ".claude" / ".kaizen"
        if default_segs:
            sink_dir = sink_dir.joinpath(*default_segs)
    sink = sink_dir / "events.jsonl"
    state = {"name": name, "kind": "sink",
             "exists": sink.is_file(),
             "path": str(sink), "count": 0}
    # DXM stores per-session files (events-<sid>.jsonl), not a single file
    if name == "dxm" and sink_dir.is_dir():
        files = sorted(sink_dir.glob("events-*.jsonl"))
        if files:
            sink = files[-1]
            state["path"] = str(sink)
            state["exists"] = True
    if sink.is_file():
        state["size"] = sink.stat().st_size
        state["last_mtime"] = sink.stat().st_mtime
        # Count VALID jsonl rows
        cnt = 0
        try:
            for line in sink.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    json.loads(line)
                    cnt += 1
                except json.JSONDecodeError:
                    continue
        except OSError:
            pass
        state["count"] = cnt
    return state


def _keepalive_dir() -> Path:
    import os as _os
    env = _os.environ.get("KAIZEN_KEEPALIVE_DIR")
    if env:
        return Path(env)
    return Path.home() / ".claude" / ".kaizen" / "keepalive"


def _cmd_systems_check(args) -> int:
    import time as _time
    systems = [_check_one(name, env_name, default_segs)
                for name, env_name, default_segs in _TRACKED_SYSTEMS]
    heartbeat = {
        "ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "systems": systems,
    }
    # Append to heartbeat.jsonl via the same shape as kaizen-progress/learn.
    try:
        hb_dir = _keepalive_dir()
        hb_dir.mkdir(parents=True, exist_ok=True)
        with (hb_dir / "heartbeat.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(heartbeat) + "\n")
    except OSError:
        pass
    if args.json:
        print(json.dumps(heartbeat, indent=2))
    else:
        print(f"systems-check {heartbeat['ts']}:")
        for s in systems:
            tag = "ok" if s.get("exists") else "absent"
            print(f"  {s['name']:<10} {tag:<6} count={s.get('count', 0)}")
    return 0


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
    sub.add_parser("index-status", help="report plugin-index freshness")

    # systems-check (2026-05-18) — pings 4 systems (hooks/trace/dxm/observer)
    # + appends heartbeat row. Fired by SessionStart hook + PostToolUse-periodic.
    sc = sub.add_parser("systems-check",
                          help="ping the 4 kaizen runtime systems + append heartbeat")
    sc.add_argument("--json", action="store_true")

    args = p.parse_args()
    cmd = args.cmd or "run"

    if cmd == "systems-check":
        sys.exit(_cmd_systems_check(args))
    # fall through to existing dispatch below

    if cmd == "run":
        state = tick()
        if "last_run" in state:
            print(f"kaizen daemon tick: {state['last_run']} (run #{state['runs']})")

    elif cmd == "install":
        if cron_install(args.interval):
            print(f"  ✓ cron entry installed (every {args.interval} min)")
            print(f"  log:    {LOG_FILE}")
            print(f"  state:  {STATE_FILE}")
            print("  unset KAIZEN_DAEMON_AUTOPULL=1 to enable auto-pull from origin (default: notify only)")
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
            ist = index_status()
            print(f"index:          {'fresh' if ist['fresh'] else 'stale'} — {ist['reason']}")
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
            print("    stop:  kaizen daemon watch-stop")
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

    elif cmd == "index-status":
        st = index_status()
        print(f"  plugin index: {'fresh' if st['fresh'] else 'STALE'} — {st['reason']}")
        sys.exit(0 if st["fresh"] else 1)

    else:
        p.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
