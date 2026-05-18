"""kaizen handoff — CLI over the in-plugin handoff store.

The handoff skill's `create` flow writes a YAML file (the system of
record); this CLI indexes it into a SQLite store and answers
`latest` / `list` queries for the `resume` flow. Core logic lives in
``_handoff.py`` — this module is argparse + the ``_cmd_*`` handlers.

## Subcommands

::

   kaizen-handoff save --session SID --file PATH [--status STATUS]
       Index a handoff YAML into the store. Upserts on the file path —
       re-saving the same file (e.g. after Step 4 sets the outcome)
       updates the row, never duplicates.
   kaizen-handoff latest [--json]
       The most recent handoff — what `resume` with no args reads.
   kaizen-handoff list [--limit N] [--session SID] [--json]
       Recent handoffs, metadata only (no YAML content).
   kaizen-handoff bridge --file PATH [--apply]
       Extract a handoff's durable learnings (decisions / findings /
       worked / failed) as brain capture-candidates. Lists them for
       review by default; --apply captures every one into brain.
   kaizen-handoff path
       Print the store DB + handoffs-dir + domain-config paths.

Bare invocation (no subcommand) defaults to ``latest``. Exit 0 on
success — including "no handoffs", which is informational, not an
error. Non-zero only on bad arguments or an unreadable --file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import _handoff as _core  # noqa: E402
import _envelope  # noqa: E402
import schema_cli  # noqa: E402
import _session_jsonl as _sj  # noqa: E402
import _atomic  # noqa: E402
import _dxm_emit  # noqa: E402  — BK-001 per-handler trace events

_emit = _envelope.emitter("kaizen-handoff", tool_version="1.0.0")

# v2 lens manifest — loaded once at import time so a malformed manifest
# fails fast (not at first call). Verify + future migrations dispatch
# through this.
_MANIFEST_PATH = _core.DOMAIN_DIR / "handoff.yaml"
_MANIFEST = schema_cli.Manifest.load(_MANIFEST_PATH)
_VERIFY_RULES_PATH = _core.DOMAIN_DIR / "verify-rules.yaml"
_OUTCOME_RUBRIC_PATH = _core.DOMAIN_DIR / "outcome-rubric.yaml"
_OUTCOME_RUBRIC = schema_cli.BucketWalker.from_yaml(_OUTCOME_RUBRIC_PATH)

# Regex matching keywords that flag a `next:` item as blocking work
# (the kind that should KEEP a session from being SUCCEEDED). Case-
# insensitive.
_NEXT_BLOCKING_RE = re.compile(
    r"\b(must|critical|blocking|todo|fixme|fix.?before)\b",
    re.IGNORECASE,
)


def _cmd_save(args) -> int:
    fp = Path(args.file).expanduser()
    if not fp.is_file():
        print(json.dumps({"error": f"file not found: {fp}"}))
        return 1
    content = fp.read_text(encoding="utf-8")
    rid = _core.save_handoff(
        args.session, content, str(fp.resolve()), status=args.status
    )
    result = {
        "id": rid,
        "session_id": args.session,
        "file_path": str(fp.resolve()),
        "status": args.status,
    }
    if args.json:
        _emit(result, verdict="green")
    else:
        print(f"[kaizen-handoff] indexed #{rid} — {args.session} "
              f"({args.status})\n  {fp.resolve()}")
    return 0


def _cmd_latest(args) -> int:
    rows = _core.latest_handoffs(1)
    if args.json:
        _emit({"handoff": rows[0] if rows else None})
        return 0
    if not rows:
        print("[kaizen-handoff] no handoffs in the store yet.")
        return 0
    h = rows[0]
    print(f"[kaizen-handoff] latest — #{h['id']} {h['session_id']} "
          f"({h['status']}) @ {h['created_at']}")
    print(f"  file: {h['file_path']}")
    return 0


def _cmd_list(args) -> int:
    rows = _core.list_handoffs(limit=args.limit, session_id=args.session)
    if args.json:
        _emit({"handoffs": rows}, counts={"handoffs": len(rows)})
        return 0
    if not rows:
        print("[kaizen-handoff] no handoffs in the store yet.")
        return 0
    scope = f" for session {args.session}" if args.session else ""
    print(f"[kaizen-handoff] {len(rows)} handoff(s){scope}:")
    for h in rows:
        print(f"  #{h['id']:>4}  {h['created_at']}  {h['status']:<8} "
              f"{h['session_id']}")
        print(f"        {h['file_path']}")
    return 0


def _cmd_bridge(args) -> int:
    fp = Path(args.file).expanduser()
    if not fp.is_file():
        print(json.dumps({"error": f"file not found: {fp}"}))
        return 1
    candidates = _core.extract_brain_candidates(fp.read_text(encoding="utf-8"))

    if args.apply:
        # Onion-clean: handoff is a CLI *consumer* of brain — cross the
        # process boundary, no `_brain` import.
        brain_py = (_core.PLUGIN_ROOT / "skills" / "workflow"
                    / "scripts" / "brain.py")
        rows = []
        for c in candidates:
            try:
                r = subprocess.run(
                    ["python3", str(brain_py), "capture", c["text"]],
                    capture_output=True, text=True, timeout=30,
                )
                captured = r.returncode == 0
            except (subprocess.SubprocessError, OSError):
                captured = False
            rows.append({**c, "captured": captured})
        result = {"applied": rows, "count": len(rows)}
    else:
        result = {"candidates": candidates, "count": len(candidates)}

    if args.json:
        _emit(result, counts={"candidates": result.get("count", 0)})
        return 0
    if not candidates:
        print("[kaizen-handoff bridge] no durable learnings — "
              "decisions / findings / worked / failed are all empty.")
        return 0
    verb = "captured into brain" if args.apply else "brain capture-candidate(s)"
    rows = result.get("applied") or result.get("candidates")
    print(f"\n[kaizen-handoff bridge] {len(rows)} {verb}:")
    for c in rows:
        mark = ""
        if args.apply:
            mark = " ✓" if c.get("captured") else " ✗(failed)"
        print(f"  [{c['section']}]{mark} {c['text'][:100]}")
    if not args.apply:
        print("\n  Review these — capture the genuinely durable ones via")
        print("  `brain.py capture \"<text>\"`, or re-run with --apply for all.")
    return 0


def _cmd_path(args) -> int:
    _emit({
        "db": str(_core.handoff_db_path()),
        "yaml_dir": str(_core.handoffs_dir()),
        "domain": str(_core.DOMAIN_DIR / "handoff.yaml"),
    })
    return 0


# ─── verify — lens-wired structural verification (Task 6) ────────────


def _parse_handoff_yaml(text: str) -> dict:
    """Minimal handoff YAML parser — split frontmatter (between the two
    `---` markers) from body, then load each independently. PyYAML's
    safe_load can't handle the bare-document-with-frontmatter shape
    (sees two documents); using safe_load_all preserves order without
    forcing a multi-doc wrapper."""
    fm_text = ""
    body_text = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1]
            body_text = parts[2]

    # Frontmatter date — line-based, avoids forcing PyYAML on simple
    # k:v pairs (matches _handoff.update_frontmatter's parser).
    fm_date = ""
    for line in fm_text.splitlines():
        if line.strip().startswith("date:"):
            fm_date = line.split(":", 1)[1].strip()
            break

    try:
        import yaml as _yaml
        body = _yaml.safe_load(body_text) or {}
    except ImportError:
        body = {}
    except Exception:
        body = {}

    if not isinstance(body, dict):
        body = {}

    done_files: list[str] = []
    for entry in (body.get("done_this_session") or []):
        if isinstance(entry, dict):
            files = entry.get("files") or []
            if isinstance(files, list):
                done_files.extend(str(f) for f in files if f)

    def _string_list(key: str) -> list[str]:
        raw = body.get(key) or []
        return [str(x) for x in raw if isinstance(x, (str, int, float))]

    return {
        "date": fm_date or str(body.get("date", "")),
        "done_files": list(dict.fromkeys(done_files)),  # dedupe, preserve order
        "done_items": body.get("done_this_session") or [],  # raw list-of-dicts
        "worked":    _string_list("worked"),
        "failed":    _string_list("failed"),
        "next":      _string_list("next"),
        "questions": _string_list("questions"),
        "blockers":  _string_list("blockers"),
        "decisions": body.get("decisions") or [],
        "findings":  body.get("findings")  or [],
    }


def _compute_assessment_signals(parsed: dict) -> dict:
    """Compute the 5 signals the outcome rubric walks.

    The handoff YAML doesn't carry an explicit completion field per
    task — anything in done_this_session is by-convention "done".
    completed_ratio measures "what got done" against "what's still
    open" (blockers + next items). Test delta is supplied externally
    (agent / CI passes --test-delta); default 0 means "no test
    movement, neither regress nor improve"."""
    done = parsed.get("done_items") or []
    done_count = len(done)
    blockers = parsed.get("blockers") or []
    blocker_count = len(blockers)
    next_items = parsed.get("next") or []

    next_blocking_count = sum(
        1 for item in next_items
        if isinstance(item, str) and _NEXT_BLOCKING_RE.search(item)
    )

    denom = done_count + blocker_count + len(next_items)
    completed_ratio = (done_count / denom) if denom > 0 else 0.0

    return {
        "done_count":          done_count,
        "blocker_count":       blocker_count,
        "next_blocking_count": next_blocking_count,
        "completed_ratio":     round(completed_ratio, 4),
        "test_delta":          int(parsed.get("test_delta", 0)),
    }


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True, text=True, timeout=30,
    )


def _check_files(parsed: dict, repo_root: Path) -> list[dict]:
    """file-exists + file-modified-since-handoff checks per verify-rules.yaml."""
    out: list[dict] = []
    for path in parsed["done_files"]:
        full = repo_root / path
        if not full.exists():
            out.append({
                "path": path,
                "status": "missing",
                "severity": "warn",
            })
            continue
        # Check git log for modifications since handoff date.
        modified_since = None
        if parsed["date"]:
            r = _git(
                repo_root, "log", f"--since={parsed['date']}",
                "-1", "--format=%cI", "--", path,
            )
            if r.returncode == 0 and r.stdout.strip():
                modified_since = r.stdout.strip()
        entry: dict = {
            "path": path,
            "status": "modified" if modified_since else "present",
            "severity": "info" if modified_since else "info",
        }
        if modified_since:
            entry["modified_since"] = modified_since
        out.append(entry)
    return out


def _is_narrative_bullet(text: str) -> bool:
    """Heuristic: handoff worked/failed bullets following the
    'identifier — explanation' convention (em-dash separator) are
    session-discovery notes, not code patterns. Grep'ing them against
    the codebase always yields 0 hits and produces false-positive
    stale warns. Skip them in pattern_checks."""
    return " — " in text


def _check_patterns(parsed: dict, repo_root: Path) -> list[dict]:
    """pattern-still-present (worked) + failed-pattern-reintroduced
    (failed). Narrative bullets (em-dash separator) are skipped — they
    were never code patterns, so verify can't meaningfully grep them."""
    out: list[dict] = []

    def _grep_count(pattern: str) -> int:
        # Use git grep — respects .gitignore + tree state. -F = fixed string.
        r = _git(repo_root, "grep", "-Fc", pattern)
        if r.returncode > 1:
            return 0  # git error
        if not r.stdout.strip():
            return 0
        # Per-file hit-count lines: "path:N"
        total = 0
        for line in r.stdout.strip().splitlines():
            if ":" in line:
                _, n = line.rsplit(":", 1)
                try:
                    total += int(n)
                except ValueError:
                    pass
        return total

    for pattern in parsed["worked"]:
        if _is_narrative_bullet(pattern):
            continue
        hits = _grep_count(pattern)
        if hits > 0:
            out.append({
                "section": "worked", "pattern": pattern,
                "hit_count": hits, "severity": "info", "verdict": "confirmed",
            })
        else:
            out.append({
                "section": "worked", "pattern": pattern,
                "hit_count": 0, "severity": "warn", "verdict": "stale",
            })

    for pattern in parsed["failed"]:
        if _is_narrative_bullet(pattern):
            continue
        hits = _grep_count(pattern)
        if hits > 0:
            out.append({
                "section": "failed", "pattern": pattern,
                "hit_count": hits, "severity": "red", "verdict": "reintroduced",
            })
        else:
            out.append({
                "section": "failed", "pattern": pattern,
                "hit_count": 0, "severity": "info", "verdict": "clean",
            })

    return out


def _commit_delta(parsed: dict, repo_root: Path) -> dict:
    """commits-since-handoff — count + oneline summary."""
    since = parsed["date"] or ""
    if not since:
        return {"count": 0, "since": "", "commits": []}
    r = _git(repo_root, "log", f"--since={since}", "--oneline")
    if r.returncode != 0:
        return {"count": 0, "since": since, "commits": []}
    commits: list[dict] = []
    for line in r.stdout.strip().splitlines():
        if not line.strip():
            continue
        sha, _, subject = line.partition(" ")
        commits.append({"sha": sha, "subject": subject})
    return {"count": len(commits), "since": since, "commits": commits}


def _qualitative_residue(parsed: dict) -> list[dict]:
    """Sections the verify can't check mechanically — for agent attention.

    The list of qualitative sections is data-driven from verify-rules.yaml,
    but we keep the section→data lookup here since verify-rules is read
    once at module-load and not re-parsed per call."""
    out: list[dict] = []
    sections = [
        ("next",      "forward-looking — needs agent judgment",  parsed["next"]),
        ("questions", "open by definition; needs follow-up",     parsed["questions"]),
        ("decisions", "still-in-force check is qualitative",     parsed["decisions"]),
        ("findings",  "validity is qualitative",                 parsed["findings"]),
    ]
    for section, reason, items in sections:
        if items:
            out.append({"section": section, "reason": reason, "items": items})
    return out


def _rollup_verdict(file_checks: list[dict], pattern_checks: list[dict]) -> str:
    """First red → regression; else first warn → drift; else clean."""
    severities = (
        [c["severity"] for c in file_checks]
        + [c["severity"] for c in pattern_checks]
    )
    if "red" in severities:
        return "regression"
    if "warn" in severities:
        return "drift"
    return "clean"


def _cmd_verify(args) -> int:
    fp = Path(args.file).expanduser()
    if not fp.is_file():
        msg = f"file not found: {fp}"
        if args.json:
            print(json.dumps({"error": msg}), file=sys.stderr)
        else:
            print(f"[kaizen-handoff verify] {msg}", file=sys.stderr)
        return 1

    repo_root = Path(args.repo_root or ".").resolve()
    parsed = _parse_handoff_yaml(fp.read_text(encoding="utf-8"))

    file_checks    = _check_files(parsed, repo_root)
    pattern_checks = _check_patterns(parsed, repo_root)
    commit_delta   = _commit_delta(parsed, repo_root)
    qualitative    = _qualitative_residue(parsed)
    verdict        = _rollup_verdict(file_checks, pattern_checks)

    data = {
        "verdict": verdict,
        "handoff_file": str(fp.resolve()),
        "handoff_date": parsed["date"],
        "file_checks":  file_checks,
        "pattern_checks": pattern_checks,
        "commit_delta": commit_delta,
        "qualitative_residue": qualitative,
    }
    # BK-010: when caller passes --dxm-session, surface live tool churn
    # from the last 60s of dxm capture. Optional field.
    if args.dxm_session:
        data["recent_tool_churn"] = _query_dxm_recent_churn(
            args.dxm_session, back_seconds=60.0)

    # BK-001 per-handler trace event (best-effort, never raises)
    _dxm_emit.emit_subcommand_complete(
        "handoff", "verify",
        {"verdict": verdict,
         "files": len(file_checks),
         "patterns": len(pattern_checks)},
    )

    if args.json:
        # The lens validates output against verify-report.schema.json
        # before emit — failing closed if the data shape doesn't match.
        try:
            schema_cli.lens_emit(
                "kaizen-handoff", _MANIFEST, "verify",
                data=data,
                verdict=("green" if verdict == "clean" else
                         "yellow" if verdict == "drift" else "red"),
                counts={
                    "missing":      sum(1 for c in file_checks if c["status"] == "missing"),
                    "stale":        sum(1 for c in pattern_checks if c["verdict"] == "stale"),
                    "reintroduced": sum(1 for c in pattern_checks if c["verdict"] == "reintroduced"),
                },
                tool_version="1.0.0",
            )
        except schema_cli.SchemaValidationError as exc:
            print(f"[kaizen-handoff verify] internal: {exc}", file=sys.stderr)
            return 2
    else:
        print(f"[kaizen-handoff verify] {fp.resolve()}")
        print(f"  verdict: {verdict}")
        print(f"  file_checks: {len(file_checks)}, "
              f"pattern_checks: {len(pattern_checks)}, "
              f"commits_since: {commit_delta['count']}")
        if qualitative:
            print(f"  qualitative_residue: {[q['section'] for q in qualitative]}")
    return 0


# ─── BK-010: dxm integration helpers ─────────────────────────────────


def _dxm_events_path(session_id: str) -> Path:
    """Mirror dxm.py's _events_path so we don't shell out for a count."""
    env = os.environ.get("KAIZEN_DXM_DIR")
    if env:
        root = Path(os.path.expandvars(env)).expanduser()
    else:
        root = Path.home() / ".claude" / ".kaizen" / "dxm"
    return root / f"events-{session_id}.jsonl"


def _query_dxm_event_count(session_id: str) -> int:
    """Return the count of events in dxm for the given session. 0 when
    dxm dir/file is absent. Best-effort — never raises."""
    if os.environ.get("KAIZEN_DXM_DISABLE") == "1":
        return 0
    path = _dxm_events_path(session_id)
    if not path.is_file():
        return 0
    try:
        with path.open("r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


def _query_dxm_recent_churn(session_id: str, back_seconds: float = 60.0) -> dict:
    """Return {tool_name: count} of events in last back_seconds. Empty
    dict when dxm has nothing. Best-effort — never raises."""
    if os.environ.get("KAIZEN_DXM_DISABLE") == "1":
        return {}
    path = _dxm_events_path(session_id)
    if not path.is_file():
        return {}
    import time as _t
    cutoff = _t.time() - back_seconds
    out: dict[str, int] = {}
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = e.get("ts_unix")
                if not isinstance(ts, (int, float)) or ts < cutoff:
                    continue
                tn = e.get("tool_name")
                if not tn:
                    continue
                out[tn] = out.get(tn, 0) + 1
    except OSError:
        return {}
    return out


def _dxm_link(parent: str, child: str) -> bool:
    """Call kaizen-dxm link via subprocess. Returns True on success.
    Best-effort — failures don't propagate."""
    if os.environ.get("KAIZEN_DXM_DISABLE") == "1":
        return False
    try:
        r = subprocess.run(
            ["python3", str(_SCRIPT_DIR / "dxm.py"),
              "link", "--parent", parent, "--child", child],
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


# ─── scaffold — git-driven YAML pre-fill ─────────────────────────────


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _derive_slug(text: str, max_len: int = 40) -> str:
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return (s[:max_len].rstrip("-") or "session")


def _git_log_files(repo: Path, since: str) -> tuple[list[str], int]:
    """Return (changed_files_sorted, commit_count) since the given date."""
    # Commit count — `--oneline` gives one line per commit.
    r_count = _git(repo, "log", f"--since={since}", "--oneline")
    commits = (
        len([l for l in r_count.stdout.splitlines() if l.strip()])
        if r_count.returncode == 0 else 0
    )
    # Changed files — `--pretty=format:` suppresses commit headers; just
    # file paths remain (blank lines between commits).
    r_files = _git(repo, "log", f"--since={since}", "--name-only",
                    "--pretty=format:")
    if r_files.returncode != 0:
        return [], commits
    files = {line.strip() for line in r_files.stdout.splitlines() if line.strip()}
    return sorted(files), commits


def _git_created_files(repo: Path, since: str) -> list[str]:
    r = _git(repo, "log", f"--since={since}", "--diff-filter=A",
             "--name-only", "--pretty=format:")
    if r.returncode != 0:
        return []
    return sorted({line.strip() for line in r.stdout.splitlines() if line.strip()})


_HUNK_RE = __import__("re").compile(
    r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@"
)


def _git_head_sha(repo: Path) -> str:
    """Return short SHA at HEAD, or empty string if no commits / not a repo."""
    r = _git(repo, "rev-parse", "--short", "HEAD")
    if r.returncode != 0:
        return ""
    return r.stdout.strip()


def _split_by_project(files: list[str], projects: dict[str, str],
                       *, primary: str) -> dict[str, list[str]]:
    """Group file paths by which project's root they fall under.

    projects: name → absolute-or-~-anchored repo root path
    primary: project that owns paths not matching any explicit project root

    Returns dict[name, list[paths]] — only includes projects with ≥1 matched path.
    """
    import os as _os
    expanded = {name: _os.path.expanduser(root.rstrip("/"))
                 for name, root in projects.items()}
    groups: dict[str, list[str]] = {}
    for f in files:
        f_expanded = _os.path.expanduser(f) if f.startswith("~") else f
        matched: str | None = None
        for name, root in expanded.items():
            if f_expanded.startswith(root + "/") or f_expanded == root:
                matched = name
                break
        target = matched or primary
        groups.setdefault(target, []).append(f)
    return groups


def _build_session_meta(*, repos: dict[str, Path],
                          cc_jsonl: Path | None) -> dict:
    """Build session_meta dict: per-project HEAD SHAs + Claude Code session traceability.

    Auto-populates everything deterministic — no operator input needed:
    - handoff_generated_at (UTC ISO-8601)
    - primary_branch / head_at_handoff per repo (via git rev-parse)
    - cc_session_{uuid,jsonl,sha256,lines,size_bytes} when cc_jsonl given
    """
    import hashlib
    from datetime import datetime, timezone
    meta: dict = {
        "handoff_generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if repos:
        meta["primary_branch"] = {}
        meta["head_at_handoff"] = {}
        for name, repo in repos.items():
            br = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
            meta["primary_branch"][name] = br.stdout.strip() if br.returncode == 0 else "?"
            meta["head_at_handoff"][name] = _git_head_sha(repo)
    if cc_jsonl is not None and cc_jsonl.is_file():
        content = cc_jsonl.read_bytes()
        meta["cc_session_jsonl"]    = str(cc_jsonl)
        meta["cc_session_sha256"]   = hashlib.sha256(content).hexdigest()
        meta["cc_session_lines"]    = len([l for l in content.splitlines() if l.strip()])
        meta["cc_session_size_bytes"] = len(content)
        meta["cc_session_uuid"]     = cc_jsonl.stem
    return meta


def _auto_tag_commits(repo: Path, files: list[str], *, since: str) -> list[str]:
    """For the given file paths, return commits since `since` that touched any of them.

    Returns deduped short SHAs in chronological order (oldest first).
    """
    if not files:
        return []
    r = _git(repo, "log", f"--since={since}", "--reverse",
             "--format=%h", "--name-only", "--",  *files)
    if r.returncode != 0 or not r.stdout.strip():
        return []
    shas: list[str] = []
    seen: set[str] = set()
    current_sha: str | None = None
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if all(c in "0123456789abcdef" for c in line) and 7 <= len(line) <= 12:
            current_sha = line
        elif current_sha and current_sha not in seen:
            shas.append(current_sha)
            seen.add(current_sha)
    return shas


def _parse_hunk_header(line: str) -> tuple[int, int] | None:
    """Parse `@@ -A,B +C,D @@` → (start, end) line range on the new side.

    Returns None for malformed headers or zero-length hunks (pure deletions).
    """
    m = _HUNK_RE.match(line)
    if not m:
        return None
    start = int(m.group(1))
    length = int(m.group(2)) if m.group(2) else 1
    if length == 0:
        return None  # deletion-only hunk; no new lines to capture
    return (start, start + length - 1)


def _git_changed_line_ranges(repo: Path, since: str) -> dict[str, list[tuple[int, int]]]:
    """Return dict[path, [(start_line, end_line), ...]] for all changes since `since`.

    Uses `git log -U0 -p` to get hunk headers without context lines, then parses
    `@@ -A,B +C,D @@` per file. Captures the NEW-side line range — what the
    file looks like AFTER the change. Empty dict on no commits or git failure.

    Fine-grained code-context capture for D1 (explicit info in handoff).
    """
    r = _git(repo, "log", f"--since={since}", "-U0", "--no-color",
             "-p", "--pretty=format:%n%n%n")  # 3 newlines as commit separator
    if r.returncode != 0 or not r.stdout.strip():
        return {}
    ranges: dict[str, list[tuple[int, int]]] = {}
    current_file: str | None = None
    for line in r.stdout.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[len("+++ b/"):]
            ranges.setdefault(current_file, [])
        elif line.startswith("+++ ") and " /dev/null" in line:
            current_file = None  # file deletion
        elif line.startswith("@@ ") and current_file:
            parsed = _parse_hunk_header(line)
            if parsed:
                ranges[current_file].append(parsed)
    # Drop empty entries (no new-side hunks)
    return {p: rs for p, rs in ranges.items() if rs}


def _discover_active_session(cwd: Path):
    """Find the active Claude Code session JSONL for this cwd. Returns
    (jsonl_path, mined_dict) or (None, None) if unreachable. Graceful
    no-op when not running under Claude Code (e.g. CI, tests with no
    ~/.claude/projects/<slug>/)."""
    slug = _sj.cwd_to_slug(cwd)
    projects_root = Path.home() / ".claude" / "projects" / slug
    jsonl = _sj.discover_session_jsonl(projects_root)
    if jsonl is None:
        return None, None
    try:
        return jsonl, _sj.mine_session(jsonl)
    except Exception:
        return jsonl, None


def _cmd_scaffold(args) -> int:
    """Write a partially-filled handoff YAML; agent finishes the prose.

    When the Claude Code session JSONL is reachable AND --no-session-mine
    is not set, mines the JSONL to enrich the pre-fill:
      - latest ai-title → default --goal (if not supplied)
      - top pending TaskList item → default --now
      - completed TaskUpdate subjects → done_this_session entries
      - pending tasks → next[] entries
      - session_started_at → --since default for git queries
    Slashes ~80% of the agent's compose-from-memory cost.
    """
    import datetime as _dt
    repo = Path(args.repo_root or ".").resolve()
    session = args.session
    if not re.match(r"^[A-Za-z0-9._-]+$", session):
        print(f"[kaizen-handoff scaffold] invalid session name {session!r}",
              file=sys.stderr)
        return 2

    # ─── Optional: mine the active Claude Code session ────────────
    jsonl_path = None
    mined: dict = {}
    if not args.no_session_mine:
        jsonl_path, m = _discover_active_session(repo)
        if m:
            mined = m

    # ─── Resolve goal / now ──────────────────────────────────────
    goal = args.goal
    if not goal:
        goal = mined.get("ai_title")
    if not goal:
        print("[kaizen-handoff scaffold] --goal required (or run under "
              "a Claude Code session where ai-title is available)",
              file=sys.stderr)
        return 2

    now_text = args.now
    if not now_text:
        pending = mined.get("pending_tasks") or []
        if pending:
            now_text = pending[0]
    if not now_text:
        print("[kaizen-handoff scaffold] --now required (or run under a "
              "Claude Code session with a pending TaskList entry)",
              file=sys.stderr)
        return 2

    slug = args.description_slug or _derive_slug(goal)
    timestamp = args.at or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d_%H-%M")
    date_str = timestamp.split("_", 1)[0]  # YYYY-MM-DD

    # Use session-started_at as the git --since default when available
    # (more accurate than 7.days.ago for in-session work).
    since = args.since
    if not since:
        sa = mined.get("session_started_at")
        if sa:
            # Take just the YYYY-MM-DD portion for git --since.
            since = sa.split("T", 1)[0]
        else:
            since = "7.days.ago"

    handoffs_root = _core.handoffs_dir()
    session_dir = handoffs_root / session
    session_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = session_dir / f"{timestamp}_{slug}.yaml"

    changed, commits = _git_log_files(repo, since)
    created  = _git_created_files(repo, since)
    modified = sorted(set(changed) - set(created))
    # D1 explicit-info: capture per-file line ranges where work happened
    # so resume agents see code-context, not just paths.
    line_ranges = _git_changed_line_ranges(repo, since)

    # Auto-build session_meta: per-project HEAD + Claude Code session traceability.
    # Detects sibling repos via $HOME/workspace/* convention (cheap heuristic).
    import os as _os
    repos_for_meta: dict[str, Path] = {session: repo}
    sibling_root = Path(_os.path.expanduser("~/workspace"))
    if sibling_root.is_dir():
        for sib in sibling_root.iterdir():
            if sib.is_dir() and (sib / ".git").exists() and sib != repo:
                # Only include siblings whose name differs from the primary
                if sib.name != session:
                    repos_for_meta.setdefault(sib.name, sib)
    # Cap siblings — we only care about ones touched THIS session
    # (cheap filter: prune those with no recent commits)
    recent_repos: dict[str, Path] = {session: repo}
    for name, r in list(repos_for_meta.items())[1:]:
        head_check = _git(r, "log", f"--since={since}", "-1", "--oneline")
        if head_check.returncode == 0 and head_check.stdout.strip():
            recent_repos[name] = r
    session_meta = _build_session_meta(
        repos=recent_repos,
        cc_jsonl=Path(jsonl_path) if jsonl_path else None,
    )

    body_lines = [
        "---",
        f"session: {session}",
        f"date: {date_str}",
        "status: partial",
        "outcome: IN_PROGRESS",
        "---",
        "",
        "session_meta:",
    ]
    if session_meta.get("cc_session_uuid"):
        body_lines.append(f"  cc_session_uuid: {session_meta['cc_session_uuid']!r}")
        body_lines.append(f"  cc_session_jsonl: {session_meta['cc_session_jsonl']!r}")
        body_lines.append(f"  cc_session_sha256: {session_meta['cc_session_sha256']!r}")
        body_lines.append(f"  cc_session_lines: {session_meta['cc_session_lines']}")
        body_lines.append(f"  cc_session_size_bytes: {session_meta['cc_session_size_bytes']}")
    body_lines.append(f"  handoff_generated_at: {session_meta['handoff_generated_at']!r}")
    if session_meta.get("primary_branch"):
        body_lines.append("  primary_branch:")
        for n, br in session_meta["primary_branch"].items():
            body_lines.append(f"    {n}: {br!r}")
        body_lines.append("  head_at_handoff:")
        for n, sha in session_meta["head_at_handoff"].items():
            body_lines.append(f"    {n}: {sha!r}")
    body_lines += [
        "",
        f"goal: {_quote_if_unsafe(goal)}",
        f"now: {_quote_if_unsafe(now_text)}",
        "test: TBD",
        "",
    ]

    # done_this_session: prefer mined completed-tasks (per-task entries),
    # else fall back to one umbrella task with the git-touched files.
    completed = mined.get("completed_tasks") or []
    if completed:
        body_lines.append("done_this_session:")
        for task in completed:
            body_lines.append(f"  - task: {_quote_if_unsafe(task)}")
            body_lines.append(f"    files: []")
        if changed:
            # Stash a final synthetic entry holding the git-touched
            # files so reviewers can see what moved this session.
            body_lines.append(
                "  - task: (git-touched files this session)")
            body_lines.append(
                f"    files: [{', '.join(changed)}]")
    elif changed:
        body_lines.append("done_this_session:")
        body_lines.append("  - task: TBD (scaffolded — agent fills)")
        body_lines.append(f"    files: [{', '.join(changed)}]")
    else:
        body_lines.append("done_this_session: []")

    body_lines += [
        "",
        "blockers: []",
        "questions: []",
        "decisions: []",
        "findings: []",
        "worked: []",
        "failed: []",
    ]

    pending = mined.get("pending_tasks") or []
    if pending:
        body_lines.append("next:")
        for task in pending:
            body_lines.append(f"  - {_quote_if_unsafe(task)}")
    else:
        body_lines.append("next: []")

    # Per-project file splitting — paths grouped by which repo they belong to.
    # Reduces operator mental load; no cross-project mixing in file lists.
    project_roots = {name: str(p) for name, p in recent_repos.items()}
    created_grouped = _split_by_project(created, project_roots, primary=session)
    modified_grouped = _split_by_project(modified, project_roots, primary=session)
    project_names = sorted(set(created_grouped) | set(modified_grouped))
    body_lines += ["", "files:"]
    for pname in project_names:
        body_lines.append(f"  {pname}:")
        body_lines.append(f"    created: [{', '.join(created_grouped.get(pname, []))}]")
        body_lines.append(f"    modified: [{', '.join(modified_grouped.get(pname, []))}]")
    body_lines.append("")

    # D1 fine-grained code context — per-file line ranges from git hunks.
    # Format: code_context:
    #           - path: relative/file.py
    #             ranges: ["10:42", "55:80"]   # inclusive line ranges
    # Resume agents jump directly to where the work happened, not just which file.
    if line_ranges:
        body_lines.append("code_context:")
        for path in sorted(line_ranges):
            ranges_str = ", ".join(f'"{s}:{e}"' for s, e in line_ranges[path])
            body_lines.append(f"  - path: {_quote_if_unsafe(path)}")
            body_lines.append(f"    ranges: [{ranges_str}]")
        body_lines.append("")

    yaml_path.write_text("\n".join(body_lines), encoding="utf-8")

    prefilled = ["date", "test", "files.created", "files.modified"]
    if line_ranges:
        prefilled.append("code_context")
    if changed or completed:
        prefilled.append("done_this_session")
    if mined.get("ai_title") and not args.goal:
        prefilled.append("goal")
    if pending and not args.now:
        prefilled.append("now")
    if pending:
        prefilled.append("next")

    # agent_must_fill drops items the JSONL miner already populated.
    must_fill = ["test", "decisions", "findings", "worked", "failed"]
    if not (mined.get("ai_title") and not args.goal):
        must_fill.insert(0, "goal")
    if not pending:
        must_fill.append("next")
    if not (pending and not args.now):
        must_fill.insert(1 if "goal" in must_fill else 0, "now")

    data = {
        "yaml_path": str(yaml_path.resolve()),
        "session": session,
        "prefilled_sections": prefilled,
        "agent_must_fill": must_fill,
        "stats": {
            "commits_since": commits,
            "files_changed": len(changed),
            "since": since,
        },
    }
    if jsonl_path:
        import time as _time
        try:
            jsonl_lag = round(_time.time() - jsonl_path.stat().st_mtime, 3)
        except OSError:
            jsonl_lag = None
        # BK-010: query dxm for live event count of this session — best-effort
        # (dxm dir may not exist, session may have no events). Falls back to 0.
        dxm_event_count = _query_dxm_event_count(jsonl_path.stem)
        # BK-016: peak-aware context signal so the next session knows
        # the prior session compacted / hit red. Without this, post-
        # compact handoffs hide the context-pressure history.
        import context as _ctx
        usage = _ctx.get_usage_summary(cwd_path=repo)
        peak_tokens = usage["peak_tokens"]
        peak_pct = (peak_tokens * 100 // _ctx.get_limit()) if peak_tokens is not None else None
        data["mined_from_session"] = bool(mined)
        data["session_jsonl"] = str(jsonl_path)
        data["mined_summary"] = {
            "ai_title":           mined.get("ai_title"),
            "completed_count":    len(completed),
            "pending_count":      len(pending),
            "files_touched":      len(mined.get("files_touched") or set()),
            "skills_used":        sorted(mined.get("skills_used") or set()),
            "session_started_at": mined.get("session_started_at"),
            "jsonl_lag_seconds":  jsonl_lag,
            "dxm_event_count":    dxm_event_count,
            "peak_tokens":        peak_tokens,
            "peak_context_pct":   peak_pct,
            "peak_pre_compact":   usage["peak_pre_compact"],
            "compact_count":      usage["compact_count"],
        }
    _dxm_emit.emit_subcommand_complete(
        "handoff", "scaffold",
        {"yaml_path": str(yaml_path.resolve()),
         "files_changed": len(changed)},
    )
    if args.json:
        try:
            schema_cli.lens_emit(
                "kaizen-handoff", _MANIFEST, "scaffold",
                data=data, verdict="green",
                tool_version="1.0.0",
            )
        except schema_cli.SchemaValidationError as exc:
            print(f"[kaizen-handoff scaffold] internal: {exc}", file=sys.stderr)
            return 2
    else:
        print(f"[kaizen-handoff scaffold] {yaml_path.resolve()}")
        print(f"  prefilled: {prefilled}")
        print(f"  agent_must_fill: {must_fill}")
        print(f"  stats: commits_since={commits} files_changed={len(changed)}")
    return 0


# ─── create — typed one-shot YAML write + index ──────────────────────


def _quote_if_unsafe(value: str) -> str:
    """Quote a YAML scalar if it contains the `: ` colon-space sequence
    that PyYAML reads as a nested mapping. Single-quote escaping —
    embedded `'` doubled."""
    if ": " not in value and not value.startswith(("&", "*", "!", "|", ">", "%")):
        return value
    return "'" + value.replace("'", "''") + "'"


def _render_create_yaml(payload: dict, date_str: str) -> str:
    lines = [
        "---",
        f"session: {payload['session']}",
        f"date: {date_str}",
        "status: partial",
        "outcome: IN_PROGRESS",
        "---",
        "",
        f"goal: {_quote_if_unsafe(payload['goal'])}",
        f"now: {_quote_if_unsafe(payload['now'])}",
    ]
    if payload.get("test"):
        lines.append(f"test: {_quote_if_unsafe(payload['test'])}")
    lines.append("")

    done = payload.get("done_this_session") or []
    if done:
        lines.append("done_this_session:")
        for entry in done:
            lines.append(f"  - task: {_quote_if_unsafe(entry['task'])}")
            files = entry.get("files") or []
            lines.append(f"    files: [{', '.join(files)}]")
    else:
        lines.append("done_this_session: []")
    lines.append("")

    def _string_list(key: str) -> None:
        items = payload.get(key) or []
        if not items:
            lines.append(f"{key}: []")
        else:
            lines.append(f"{key}:")
            for item in items:
                lines.append(f"  - {_quote_if_unsafe(str(item))}")

    for k in ("blockers", "questions"):
        _string_list(k)

    for k in ("decisions", "findings"):
        items = payload.get(k) or []
        if not items:
            lines.append(f"{k}: []")
        else:
            lines.append(f"{k}:")
            for item in items:
                if isinstance(item, dict):
                    for kk, vv in item.items():
                        lines.append(f"  - {_quote_if_unsafe(str(kk))}: {_quote_if_unsafe(str(vv))}")
                else:
                    lines.append(f"  - {_quote_if_unsafe(str(item))}")

    for k in ("worked", "failed", "next"):
        _string_list(k)

    lines.append("")
    files_section = payload.get("files") or {}
    lines.append("files:")
    lines.append(f"  created: [{', '.join(files_section.get('created') or [])}]")
    lines.append(f"  modified: [{', '.join(files_section.get('modified') or [])}]")
    lines.append("")
    return "\n".join(lines)


def _cmd_create(args) -> int:
    """One-shot structured-input handoff write."""
    import datetime as _dt

    # Source the payload
    if args.stdin:
        payload_text = sys.stdin.read()
    elif args.data_file:
        payload_text = Path(args.data_file).expanduser().read_text(encoding="utf-8")
    else:
        print("[kaizen-handoff create] --stdin or --data-file required",
              file=sys.stderr)
        return 2

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        print(f"[kaizen-handoff create] payload not valid JSON: {exc}",
              file=sys.stderr)
        return 2

    # Validate via lens manifest's create subcommand
    try:
        _MANIFEST.get("create").validate_input(payload)
    except schema_cli.SchemaValidationError as exc:
        print(f"[kaizen-handoff create] payload rejected: {exc}", file=sys.stderr)
        return 2

    timestamp = payload.get("at") or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d_%H-%M")
    date_str = timestamp.split("_", 1)[0]
    slug = payload.get("description_slug") or _derive_slug(payload["goal"])

    handoffs_root = _core.handoffs_dir()
    session_dir = handoffs_root / payload["session"]
    session_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = session_dir / f"{timestamp}_{slug}.yaml"

    body = _render_create_yaml(payload, date_str)

    # Atomic write (shared util)
    _atomic.atomic_write(yaml_path, body)

    # Index into the store
    db_id = _core.save_handoff(
        payload["session"], body, str(yaml_path.resolve()), status="partial",
    )

    data = {
        "file_path":  str(yaml_path.resolve()),
        "session_id": payload["session"],
        "db_id":      int(db_id),
        "status":     "partial",
    }
    _dxm_emit.emit_subcommand_complete(
        "handoff", "create",
        {"file_path": data["file_path"], "db_id": data["db_id"]},
    )
    if args.json:
        try:
            schema_cli.lens_emit(
                "kaizen-handoff", _MANIFEST, "create",
                data=data, verdict="green",
                tool_version="1.0.0",
            )
        except schema_cli.SchemaValidationError as exc:
            print(f"[kaizen-handoff create] internal: {exc}", file=sys.stderr)
            return 2
    else:
        print(f"[kaizen-handoff create] #{db_id} → {yaml_path.resolve()}")
    return 0


def _cmd_assess(args) -> int:
    """Deterministic rubric walk — compute signals, return recommended bucket.

    Read-only — does NOT mutate the YAML or DB. The agent uses the
    recommendation as input to auto-finalize --outcome (or overrides
    it). When the rubric falls through (no rule matches), bucket is
    NEEDS_AGENT and the agent must decide qualitatively."""
    fp = Path(args.file).expanduser()
    if not fp.is_file():
        msg = f"file not found: {fp}"
        print(f"[kaizen-handoff assess] {msg}", file=sys.stderr)
        return 1

    parsed = _parse_handoff_yaml(fp.read_text(encoding="utf-8"))
    parsed["test_delta"] = int(getattr(args, "test_delta", 0) or 0)
    signals = _compute_assessment_signals(parsed)

    result = _OUTCOME_RUBRIC.evaluate(signals)
    data = {
        "bucket":      result.bucket,
        "method":      result.method,
        "confidence":  float(result.confidence),
        "handoff_file": str(fp.resolve()),
        "signals":     signals,
        "rationale":   result.rationale,
    }

    _dxm_emit.emit_subcommand_complete(
        "handoff", "assess",
        {"bucket": result.bucket, "method": result.method,
         "confidence": result.confidence},
    )

    if args.json:
        try:
            verdict = (
                "green" if result.bucket == "SUCCEEDED" else
                "red"   if result.bucket == "FAILED" else
                "yellow"
            )
            schema_cli.lens_emit(
                "kaizen-handoff", _MANIFEST, "assess",
                data=data, verdict=verdict,
                tool_version="1.0.0",
            )
        except schema_cli.SchemaValidationError as exc:
            print(f"[kaizen-handoff assess] internal: {exc}", file=sys.stderr)
            return 2
    else:
        print(f"[kaizen-handoff assess] {fp.resolve()}")
        print(f"  bucket:    {result.bucket}")
        print(f"  method:    {result.method}  (confidence {result.confidence:.2f})")
        print(f"  rationale: {result.rationale}")
        print(f"  signals:   {signals}")
    return 0


def _cmd_auto_finalize(args) -> int:
    """Agent-assigned Step 4 of the handoff create flow — no AskUserQuestion.

    Rewrites the YAML frontmatter status/outcome (+ optional justification
    and assigned_by audit fields) and re-indexes into the DB store. Used
    by:
      - Subagent contexts (no AskUserQuestion available)
      - KAIZEN_HANDOFF_AGENT=1 mode (explicit signal that an agent is
        finalizing the handoff)
      - The interactive default per current handoff skill — Claude
        self-assesses against the rubric in SKILL.md Step 4 before
        the YAML lands
    """
    fp = Path(args.file).expanduser()
    if not fp.is_file():
        msg = f"file not found: {fp}"
        if args.json:
            _emit({"error": msg}, verdict="red")
        else:
            print(f"[kaizen-handoff auto-finalize] {msg}", file=sys.stderr)
        return 1

    if args.outcome not in _core.VALID_OUTCOME:
        msg = (
            f"invalid --outcome {args.outcome!r} "
            f"(expected one of: {', '.join(_core.VALID_OUTCOME)})"
        )
        print(f"[kaizen-handoff auto-finalize] {msg}", file=sys.stderr)
        return 2

    if args.status not in _core.VALID_STATUS:
        msg = (
            f"invalid --status {args.status!r} "
            f"(expected one of: {', '.join(_core.VALID_STATUS)})"
        )
        print(f"[kaizen-handoff auto-finalize] {msg}", file=sys.stderr)
        return 2

    if args.assigned_by not in _core.VALID_ASSIGNED_BY:
        msg = (
            f"invalid --assigned-by {args.assigned_by!r} "
            f"(expected one of: {', '.join(_core.VALID_ASSIGNED_BY)})"
        )
        print(f"[kaizen-handoff auto-finalize] {msg}", file=sys.stderr)
        return 2

    updates: dict[str, str] = {
        "status": args.status,
        "outcome": args.outcome,
        "outcome_assigned_by": args.assigned_by,
    }
    if args.justification:
        updates["outcome_justification"] = args.justification

    original = fp.read_text(encoding="utf-8")
    try:
        rewritten = _core.update_frontmatter(original, updates)
    except ValueError as exc:
        msg = f"frontmatter rewrite failed: {exc}"
        if args.json:
            _emit({"error": msg}, verdict="red")
        else:
            print(f"[kaizen-handoff auto-finalize] {msg}", file=sys.stderr)
        return 1

    # Atomic write (shared util)
    _atomic.atomic_write(fp, rewritten)

    # Re-index. Session name = parent dir name (matches the skill's
    # "session-name groups handoffs into one folder" convention).
    session_id = args.session or fp.parent.name
    rid = _core.save_handoff(
        session_id, rewritten, str(fp.resolve()), status=args.status,
    )

    # BK-010: optionally record cross-session continuity in dxm
    dxm_linked = False
    if args.parent_session:
        dxm_linked = _dxm_link(args.parent_session, session_id)

    result = {
        "id": rid,
        "session_id": session_id,
        "file_path": str(fp.resolve()),
        "status": args.status,
        "outcome": args.outcome,
        "outcome_assigned_by": args.assigned_by,
        "outcome_justification": args.justification,
        "dxm_parent_session": args.parent_session,
        "dxm_linked": dxm_linked,
    }
    _dxm_emit.emit_subcommand_complete(
        "handoff", "auto-finalize",
        {"outcome": args.outcome, "status": args.status,
         "session_id": session_id,
         "assigned_by": args.assigned_by},
    )
    if args.json:
        verdict = "green" if args.outcome == "SUCCEEDED" else "yellow"
        _emit(result, verdict=verdict)
    else:
        print(
            f"[kaizen-handoff auto-finalize] indexed #{rid} — "
            f"{session_id} (status={args.status}, outcome={args.outcome}, "
            f"by={args.assigned_by})\n  {fp.resolve()}"
        )
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-handoff",
        description="CLI over the in-plugin handoff store — index + "
                    "query session handoff documents.",
    )
    # required=False so a bare invocation defaults to `latest` (the
    # resume hot path). `latest` takes no positional args, so the
    # slash command can pass bare $ARGUMENTS safely.
    sub = p.add_subparsers(dest="cmd", required=False)

    s_save = sub.add_parser("save", help="index a handoff YAML into the store")
    s_save.add_argument("--session", required=True, help="session/project name")
    s_save.add_argument("--file", required=True, help="path to the handoff YAML")
    s_save.add_argument("--status", choices=list(_core.VALID_STATUS),
                        default="partial")
    s_save.add_argument("--json", action="store_true")
    s_save.set_defaults(func=_cmd_save)

    s_latest = sub.add_parser("latest", help="the most recent handoff")
    s_latest.add_argument("--json", action="store_true")
    s_latest.set_defaults(func=_cmd_latest)

    s_list = sub.add_parser("list", help="recent handoffs (metadata only)")
    s_list.add_argument("--limit", type=int, default=20)
    s_list.add_argument("--session", help="filter by session/project")
    s_list.add_argument("--json", action="store_true")
    s_list.set_defaults(func=_cmd_list)

    s_bridge = sub.add_parser(
        "bridge",
        help="extract a handoff's durable learnings as brain "
             "capture-candidates")
    s_bridge.add_argument("--file", required=True,
                          help="path to the handoff YAML")
    s_bridge.add_argument("--apply", action="store_true",
                          help="capture every candidate into brain "
                               "(default: just list them for review)")
    s_bridge.add_argument("--json", action="store_true")
    s_bridge.set_defaults(func=_cmd_bridge)

    s_path = sub.add_parser("path", help="print store + yaml-dir paths")
    s_path.set_defaults(func=_cmd_path)

    s_create = sub.add_parser(
        "create",
        help="one-shot typed handoff write — accepts structured JSON "
             "(--stdin or --data-file), generates valid YAML, indexes",
    )
    src = s_create.add_mutually_exclusive_group(required=False)
    src.add_argument("--stdin", action="store_true",
                      help="read JSON payload from stdin")
    src.add_argument("--data-file", default=None,
                      help="read JSON payload from a file")
    s_create.add_argument("--json", action="store_true")
    s_create.set_defaults(func=_cmd_create)

    s_scaffold = sub.add_parser(
        "scaffold",
        help="git-driven YAML pre-fill — writes a partially-filled handoff "
             "YAML so the agent only writes the qualitative sections",
    )
    s_scaffold.add_argument("--session", required=True)
    s_scaffold.add_argument("--goal", default=None,
                             help="one-line summary; default: latest ai-title "
                                  "from active Claude Code session JSONL")
    s_scaffold.add_argument("--now", default=None,
                             help="next-step pointer; default: top pending "
                                  "TaskList item from session JSONL")
    s_scaffold.add_argument("--description-slug", default=None,
                             help="kebab-case slug; defaults to derived-from-goal")
    s_scaffold.add_argument("--since", default=None,
                             help="git --since filter (default: session_started_at "
                                  "from JSONL, else 7.days.ago)")
    s_scaffold.add_argument("--at", default=None,
                             help="override UTC timestamp YYYY-MM-DD_HH-MM (test aid)")
    s_scaffold.add_argument("--repo-root", default=None,
                             help="git working tree (default: cwd)")
    s_scaffold.add_argument("--no-session-mine", action="store_true",
                             help="skip mining the active Claude Code session "
                                  "JSONL (use git-only pre-fill)")
    s_scaffold.add_argument("--json", action="store_true")
    s_scaffold.set_defaults(func=_cmd_scaffold)

    s_assess = sub.add_parser(
        "assess",
        help="deterministic rubric walk — recommend outcome bucket from "
             "mechanical signals (read-only; no YAML mutation)",
    )
    s_assess.add_argument("--file", required=True, help="path to the handoff YAML")
    s_assess.add_argument(
        "--test-delta", type=int, default=0,
        help="tests-after minus tests-before (default 0 — assume no test change)",
    )
    s_assess.add_argument("--json", action="store_true")
    s_assess.set_defaults(func=_cmd_assess)

    s_verify = sub.add_parser(
        "verify",
        help="mechanical structural verification of a handoff YAML "
             "(replaces resume Step 3 sub-agent fan-out)",
    )
    s_verify.add_argument("--file", required=True, help="path to the handoff YAML")
    s_verify.add_argument(
        "--repo-root", default=None,
        help="git working tree root (default: cwd)",
    )
    s_verify.add_argument(
        "--dxm-session", default=None,
        help="when set, query kaizen-dxm for last 60s of this session's "
             "tool churn and include in envelope.data.recent_tool_churn",
    )
    s_verify.add_argument("--json", action="store_true")
    s_verify.set_defaults(func=_cmd_verify)

    s_auto = sub.add_parser(
        "auto-finalize",
        help="agent-assigned Step 4 — rewrite frontmatter outcome + status, "
             "re-index, no AskUserQuestion",
    )
    s_auto.add_argument("--file", required=True, help="path to the handoff YAML")
    s_auto.add_argument(
        "--outcome", required=True, choices=list(_core.VALID_OUTCOME),
        help="agent-assigned outcome bucket — see SKILL.md rubric",
    )
    s_auto.add_argument(
        "--status", default="complete", choices=list(_core.VALID_STATUS),
        help="work-lifecycle state (default: complete)",
    )
    s_auto.add_argument(
        "--assigned-by", default="agent", choices=list(_core.VALID_ASSIGNED_BY),
        help="audit field — who picked the outcome (default: agent)",
    )
    s_auto.add_argument(
        "--justification", default=None,
        help="one-line rationale for the outcome bucket "
             "(no `: ` colon-space inside — see SKILL.md)",
    )
    s_auto.add_argument(
        "--session", default=None,
        help="session/project name (default: parent-dir of --file)",
    )
    s_auto.add_argument(
        "--parent-session", default=None,
        help="when set, calls `kaizen-dxm link --parent PARENT --child <session>` "
             "to record cross-session continuity in dxm's sessions.jsonl",
    )
    s_auto.add_argument("--json", action="store_true")
    s_auto.set_defaults(func=_cmd_auto_finalize)

    args = p.parse_args(argv)
    if args.cmd is None:
        return _cmd_latest(argparse.Namespace(json=False))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
