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


def _most_recent_prior_handoff(session_dir: Path,
                                  exclude: Path | None = None) -> Path | None:
    """Return the lexicographically-newest .yaml in session_dir, or None.

    `exclude` skips a specific path (the file we're about to write) so
    a fresh scaffold doesn't point its parent_handoff at itself.

    Filenames carry their own ordering — they're prefixed with
    `YYYY-MM-DD_HH-MM_*`, so sort-by-name is sort-by-time.
    """
    if not session_dir.is_dir():
        return None
    candidates = sorted(
        p for p in session_dir.glob("*.yaml")
        if p != exclude
    )
    return candidates[-1] if candidates else None


def _build_session_meta(*, repos: dict[str, Path],
                          cc_jsonl: Path | None,
                          parent_handoff: Path | None = None) -> dict:
    """Build session_meta dict: per-project HEAD SHAs + Claude Code session traceability.

    Auto-populates everything deterministic — no operator input needed:
    - handoff_generated_at (UTC ISO-8601)
    - primary_branch / head_at_handoff per repo (via git rev-parse)
    - cc_session_{uuid,jsonl,sha256,lines,size_bytes} when cc_jsonl given
    - parent_handoff (file path string) when prior handoff exists
      — closes the multi-handoff chain so resume agents see the lineage.
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
    if parent_handoff is not None:
        meta["parent_handoff"] = str(parent_handoff)
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
    # Multi-handoff chain — link to the previous handoff in the same
    # session_dir so a fresh session can walk the lineage.
    parent_handoff = _most_recent_prior_handoff(session_dir, exclude=yaml_path)
    session_meta = _build_session_meta(
        repos=recent_repos,
        cc_jsonl=Path(jsonl_path) if jsonl_path else None,
        parent_handoff=parent_handoff,
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
    if session_meta.get("parent_handoff"):
        body_lines.append(f"  parent_handoff: {session_meta['parent_handoff']!r}")
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
    # `commits:` auto-tagged via _auto_tag_commits — saves the agent the
    # hand-typing pass (prior session's handoff had 60+ SHAs typed manually).
    completed = mined.get("completed_tasks") or []
    all_window_shas = _auto_tag_commits(repo, changed, since=since) if changed else []
    if completed:
        body_lines.append("done_this_session:")
        for task in completed:
            body_lines.append(f"  - task: {_quote_if_unsafe(task)}")
            body_lines.append("    commits: []")
            body_lines.append("    files: []")
        if changed:
            # Stash a final synthetic entry holding the git-touched
            # files + ALL window commits so reviewers can see what moved
            # this session and re-distribute SHAs to the right tasks.
            body_lines.append(
                "  - task: (git-touched files this session)")
            body_lines.append(
                f"    commits: [{', '.join(all_window_shas)}]")
            body_lines.append(
                f"    files: [{', '.join(changed)}]")
    elif changed:
        body_lines.append("done_this_session:")
        body_lines.append("  - task: TBD (scaffolded — agent fills)")
        body_lines.append(f"    commits: [{', '.join(all_window_shas)}]")
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


def _maybe_auto_bridge(fp: Path, *, outcome: str, force: bool) -> dict | None:
    """Auto-bridge handoff durables to brain when appropriate.

    Per Task #40 brainstorm item #4 — closes the mental-load gap
    between auto-finalize and brain capture. Gating:

      - Triggered by `force=True` (--auto-bridge flag) OR
        `KAIZEN_HANDOFF_AUTO_BRIDGE=1` env (per-session)
      - Only fires when `outcome == "SUCCEEDED"` (high-confidence —
        partial / failed outcomes likely have non-durable noise mixed in)
      - Brain.py subprocess failures NEVER fail the parent finalize
        (errors counted in `failed`, finalize continues)

    Returns:
      - None when not triggered
      - {"skipped": True, "reason": "..."} when triggered but outcome filter blocks
      - {"applied": int, "failed": int, "total": int, "rows": [...]} on real run
    """
    import os as _os
    auto = force or _os.environ.get("KAIZEN_HANDOFF_AUTO_BRIDGE") == "1"
    if not auto:
        return None
    if outcome != "SUCCEEDED":
        return {"skipped": True,
                "reason": f"outcome {outcome} != SUCCEEDED — bridge gated"}
    candidates = _core.extract_brain_candidates(fp.read_text(encoding="utf-8"))
    if not candidates:
        return {"applied": 0, "failed": 0, "total": 0,
                "reason": "no durable candidates", "rows": []}
    brain_py = (_core.PLUGIN_ROOT / "skills" / "workflow"
                 / "scripts" / "brain.py")
    rows = []
    applied = 0
    failed = 0
    for c in candidates:
        try:
            r = subprocess.run(
                ["python3", str(brain_py), "capture", c["text"]],
                capture_output=True, text=True, timeout=30,
            )
            captured = r.returncode == 0
        except (subprocess.SubprocessError, OSError):
            captured = False
        if captured:
            applied += 1
        else:
            failed += 1
        rows.append({**c, "captured": captured})
    return {"applied": applied, "failed": failed,
            "total": len(candidates), "rows": rows}


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
    # Optional: auto-bridge durables to brain. Never fails the finalize.
    bridge_result = _maybe_auto_bridge(
        fp, outcome=args.outcome, force=getattr(args, "auto_bridge", False),
    )
    if bridge_result is not None:
        result["auto_bridge"] = bridge_result
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


# ─── get — surgical section extraction ────────────────────────────────

_FRONTMATTER_SECTIONS = {
    "status", "outcome", "outcome_assigned_by", "outcome_justification",
    "date", "session",
}
_BODY_SECTIONS = {
    "goal", "now", "test",
    "done_this_session", "blockers", "questions",
    "decisions", "findings", "worked", "failed",
    "next", "files", "code_context", "session_meta",
}
_ALL_SECTIONS = _FRONTMATTER_SECTIONS | _BODY_SECTIONS


def _load_raw_handoff(text: str) -> tuple[dict, dict]:
    """Return (frontmatter, body) as raw dicts. Lightweight line-parse of
    frontmatter (matches the rest of handoff.py's approach); PyYAML for body.
    """
    fm_text = ""
    body_text = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1]
            body_text = parts[2]

    fm: dict[str, str] = {}
    for line in fm_text.splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k:
                fm[k] = v

    try:
        import yaml as _yaml
        body = _yaml.safe_load(body_text) or {}
    except (ImportError, Exception):  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    return fm, body


def _render_section(value, *, as_json: bool) -> str:
    """Human-readable when --json off; canonical JSON when on."""
    if as_json:
        return json.dumps(value, indent=2, default=str)
    # Human format: scalars → raw; list of strings → one per line;
    # list of dicts / nested → JSON (else unreadable).
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, list):
        if all(isinstance(x, (str, int, float, bool)) for x in value):
            return "\n".join(str(x) for x in value)
        return json.dumps(value, indent=2, default=str)
    if isinstance(value, dict):
        return json.dumps(value, indent=2, default=str)
    return str(value)


# ─── append — mid-session list-section append (Task #40) ──────────────

_LIST_BODY_SECTIONS = {
    "done_this_session", "blockers", "questions",
    "decisions", "findings", "worked", "failed", "next",
}


def _format_entry_yaml(section: str, entry, indent: str = "  ") -> str:
    """Render one list item under `section:` with proper indent.

    dict entry → `  - key1: value1\\n    key2: value2\\n...`
    string entry → `  - 'value'\\n`
    """
    if isinstance(entry, dict):
        keys = list(entry.keys())
        if not keys:
            return f"{indent}- {{}}\n"
        lines = []
        first = keys[0]
        lines.append(f"{indent}- {first}: {_quote_if_unsafe(str(entry[first])) if isinstance(entry[first], str) else json.dumps(entry[first])}")
        for k in keys[1:]:
            v = entry[k]
            v_s = (_quote_if_unsafe(str(v)) if isinstance(v, str)
                    else json.dumps(v))
            lines.append(f"{indent}  {k}: {v_s}")
        return "\n".join(lines) + "\n"
    # string / scalar
    return f"{indent}- {_quote_if_unsafe(str(entry))}\n"


def _append_to_list_section(text: str, section: str, entry) -> str:
    """Insert entry at end of section's list-items. Returns mutated text.

    Handles 3 shapes:
    1. `section: []`  → replaces with `section:\\n  - <entry>\\n`
    2. `section:\\n  - item1\\n  - item2` → inserts after last item, before
       the next top-level key
    3. section missing → appends `\\nsection:\\n  - <entry>\\n` at EOF

    Raises ValueError if section is a known scalar/dict (not a list-section).
    """
    if section in {"goal", "now", "test", "files", "code_context",
                    "session_meta", "status", "outcome", "date", "session"}:
        raise ValueError(f"section {section!r} is not a list — append unsupported")
    entry_yaml = _format_entry_yaml(section, entry)
    lines = text.splitlines(keepends=True)
    # Find section start
    section_start = None
    for i, line in enumerate(lines):
        if line.startswith(f"{section}:"):
            section_start = i
            break
    if section_start is None:
        # Append new section at EOF
        suffix = f"\n{section}:\n{entry_yaml}"
        if not text.endswith("\n"):
            suffix = "\n" + suffix
        return text + suffix
    # Empty inline form `section: []`
    if lines[section_start].rstrip().endswith(": []"):
        lines[section_start] = lines[section_start].replace(": []", ":\n")
        return "".join(lines[:section_start + 1] + [entry_yaml]
                        + lines[section_start + 1:])
    # Populated form — find the END of this section (next top-level key).
    section_end = len(lines)
    for j in range(section_start + 1, len(lines)):
        s = lines[j]
        if s.rstrip() == "" or s.startswith((" ", "\t")):
            continue
        if s.startswith("---"):
            section_end = j
            break
        if ":" in s and not s.lstrip().startswith("#"):
            section_end = j
            break
    return "".join(lines[:section_end] + [entry_yaml] + lines[section_end:])


def _cmd_append(args) -> int:
    fp = Path(args.file)
    if not fp.is_file():
        sys.stderr.write(f"handoff append: file not found: {fp}\n")
        return 2
    section = args.section
    if section not in _LIST_BODY_SECTIONS:
        sys.stderr.write(
            f"handoff append: unknown list-section {section!r}\n"
            f"  supported: {sorted(_LIST_BODY_SECTIONS)}\n"
        )
        return 1
    if args.task and section == "done_this_session":
        entry: object = {"task": args.task}
        if args.files:
            entry["files"] = [f.strip() for f in args.files.split(",")
                               if f.strip()]
    elif args.entry:
        entry = args.entry
    elif args.task:
        # User passed --task for a string-section; treat as plain entry
        entry = args.task
    else:
        sys.stderr.write("handoff append: provide --task (done_this_session) "
                          "or --entry (other sections)\n")
        return 1
    text = fp.read_text(encoding="utf-8")
    try:
        new_text = _append_to_list_section(text, section, entry)
    except ValueError as e:
        sys.stderr.write(f"handoff append: {e}\n")
        return 1
    # Atomic write
    tmp = fp.with_suffix(fp.suffix + ".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(fp)
    if args.json:
        print(json.dumps({"file": str(fp), "section": section,
                           "appended": entry}, indent=2))
    else:
        print(f"appended to {section} in {fp}")
    return 0


# ─── cost — token-budget estimator (Task #40 brainstorm #1) ──────────

_COST_DEFAULT_BUDGET = 2000


def _approx_tokens(s: str) -> int:
    """Chars-divided-by-4 token estimate (kaizen convention).

    Ceiling division — avoids under-reporting on small strings. Empty
    string returns 0. Matches the estimate used in token-bloat reports
    and the skill-listing-budget analysis.
    """
    if not s:
        return 0
    return (len(s) + 3) // 4


def _cost_threshold() -> int:
    """Drift-resilient (re-read per call): env wins, else default."""
    try:
        return int(os.environ.get("KAIZEN_HANDOFF_COST_TOKEN_BUDGET",
                                    _COST_DEFAULT_BUDGET))
    except ValueError:
        return _COST_DEFAULT_BUDGET


def _compute_costs(text: str) -> dict:
    """Pure function: total size + per-section chars/tokens + threshold verdict.

    Per-section breakdown uses PyYAML body parse — same shape as
    `_load_raw_handoff` returns. Each section's serialized length is
    approximated via json.dumps (faithful enough for budget signaling).
    """
    size_bytes = len(text.encode("utf-8"))
    approx_total = _approx_tokens(text)
    _, body = _load_raw_handoff(text)
    per_section: dict[str, dict] = {}
    for section in sorted(_BODY_SECTIONS):
        value = body.get(section)
        if value is None:
            serialized = ""
        elif isinstance(value, str):
            serialized = value
        else:
            serialized = json.dumps(value, default=str)
        chars = len(serialized)
        tokens = _approx_tokens(serialized)
        pct = (chars / len(text) * 100.0) if text else 0.0
        per_section[section] = {
            "chars": chars,
            "approx_tokens": tokens,
            "pct": round(pct, 1),
        }
    threshold = _cost_threshold()
    over = approx_total > threshold
    if over:
        recommendation = ("over budget — scaffold a fresh handoff + link via "
                          "parent_handoff so the chain stays intact without bloat")
    else:
        recommendation = "ok — under budget"
    return {
        "size_bytes": size_bytes,
        "approx_tokens": approx_total,
        "threshold_tokens": threshold,
        "over_threshold": over,
        "per_section": per_section,
        "recommendation": recommendation,
    }


def _cmd_cost(args) -> int:
    fp = Path(args.file)
    if not fp.is_file():
        sys.stderr.write(f"handoff cost: file not found: {fp}\n")
        return 2
    text = fp.read_text(encoding="utf-8")
    result = _compute_costs(text)
    out = {"file": str(fp), **result}
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        verdict = "✗ over budget" if result["over_threshold"] else "✓ ok"
        print(f"handoff cost: {fp}")
        print(f"total: {result['size_bytes']:>7,} bytes  "
              f"~{result['approx_tokens']:>6,} tokens  "
              f"(threshold {result['threshold_tokens']:,})  {verdict}")
        print()
        print("per section (sorted by tokens):")
        sorted_sections = sorted(result["per_section"].items(),
                                  key=lambda kv: -kv[1]["approx_tokens"])
        for name, st in sorted_sections:
            if st["approx_tokens"] == 0:
                continue
            print(f"  {name:<22} {st['chars']:>6,} chars  "
                  f"~{st['approx_tokens']:>5,} tok  ({st['pct']:>4.1f}% of total)")
        print()
        print(f"  → {result['recommendation']}")
    return 0


# ─── tree — bidirectional commit↔task map (Task #40) ──────────────────

def _build_commit_task_map(entries: list, *, repo: Path, since: str) -> dict:
    """For each done_this_session entry with files, list commits since `since`
    that touched any of them. Returns bidirectional map.

    Entries without `files` (or empty list) surface in `skipped_no_files` —
    can't be tree-mapped without paths. Entries with files but zero
    matching commits still appear in `by_task` (empty list).

    Pure-ish: only side-effect is `git log` subprocess calls via
    `_auto_tag_commits`. Drift-resilient — no module-level state.
    """
    by_task: dict[str, list[str]] = {}
    by_commit: dict[str, list[str]] = {}
    skipped: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        task = entry.get("task") or "?"
        files = entry.get("files") or []
        if not files:
            skipped.append(task)
            continue
        commits = _auto_tag_commits(repo, files, since=since)
        by_task[task] = commits
        for c in commits:
            by_commit.setdefault(c, []).append(task)
    return {"by_task": by_task,
            "by_commit": by_commit,
            "skipped_no_files": skipped}


def _smart_since(text: str) -> str | None:
    """Pick the best `--since` cutoff for tree/queries on this handoff.

    Priority:
      1. parent_handoff's session_meta.handoff_generated_at (exact UTC
         timestamp — catches commits made AFTER the prior session ended)
      2. current handoff's `date:` field (broader day-bucket)
      3. None (caller falls back to its own default, typically "1 week ago")

    Graceful on:
      - missing parent_handoff in session_meta
      - parent file unreadable / missing
      - parent's session_meta without handoff_generated_at
    """
    fm, body = _load_raw_handoff(text)
    meta = body.get("session_meta") or {}
    parent_path = meta.get("parent_handoff")
    if parent_path:
        try:
            parent_text = Path(parent_path).read_text(encoding="utf-8")
            _, pbody = _load_raw_handoff(parent_text)
            pmeta = pbody.get("session_meta") or {}
            pts = pmeta.get("handoff_generated_at")
            if pts:
                return str(pts)
        except OSError:
            pass  # missing parent file → fall through
    return fm.get("date") or None


def _normalize_since(since: str) -> str:
    """Add `00:00:00` time component when `since` is bare YYYY-MM-DD.

    Git's `--since=2026-05-18` misses same-day commits in some configurations
    (likely TZ-related parse ambiguity); `--since='2026-05-18 00:00:00'`
    works reliably. Verified 2026-05-18 against author-dated commits.
    """
    import re as _re
    if _re.fullmatch(r"\d{4}-\d{2}-\d{2}", since.strip()):
        return f"{since.strip()} 00:00:00"
    return since


def _cmd_tree(args) -> int:
    fp = Path(args.file)
    if not fp.is_file():
        sys.stderr.write(f"handoff tree: file not found: {fp}\n")
        return 2
    text = fp.read_text(encoding="utf-8")
    fm, body = _load_raw_handoff(text)
    entries = body.get("done_this_session") or []
    # Default cutoff threading: --since wins, else smart pick from
    # parent_handoff (most precise) → date → "1 week ago" fallback.
    raw_since = args.since or _smart_since(text) or "1 week ago"
    since = _normalize_since(raw_since)
    repo = Path(args.repo or ".").resolve()
    result = _build_commit_task_map(entries, repo=repo, since=since)
    out = {"file": str(fp), "since": since, "repo": str(repo), **result}
    print(json.dumps(out, indent=2, default=str))
    return 0


def _cmd_get(args) -> int:
    fp = Path(args.file)
    if not fp.is_file():
        sys.stderr.write(f"handoff get: file not found: {fp}\n")
        return 2
    section = args.section
    if section not in _ALL_SECTIONS:
        sys.stderr.write(
            f"handoff get: unknown section {section!r}\n"
            f"  available frontmatter: {sorted(_FRONTMATTER_SECTIONS)}\n"
            f"  available body: {sorted(_BODY_SECTIONS)}\n"
        )
        return 1
    text = fp.read_text(encoding="utf-8")
    fm, body = _load_raw_handoff(text)
    if section in _FRONTMATTER_SECTIONS:
        value = fm.get(section, "")
    else:
        value = body.get(section)
    sys.stdout.write(_render_section(value, as_json=args.json) + "\n")
    return 0


# ─── verify-hash — finishes the half-built integrity check ────────────

def _cmd_verify_hash(args) -> int:
    """Re-hash the linked JSONL + compare against the handoff's captured
    cc_session_sha256. Verdicts: match / drift / missing / no-link.

    Exit codes:
      0 — match OR no-link (informational)
      1 — drift / missing JSONL / handoff file missing
    """
    import hashlib
    fp = Path(args.file)
    if not fp.is_file():
        msg = {"verdict": "no-handoff",
                "error": f"handoff file not found: {fp}"}
        if args.json:
            print(json.dumps(msg))
        else:
            print(f"no-handoff: {fp}")
        return 1

    fm, body = _load_raw_handoff(fp.read_text(encoding="utf-8"))
    session_meta = body.get("session_meta") or {}
    if not isinstance(session_meta, dict):
        session_meta = {}
    jsonl_path = session_meta.get("cc_session_jsonl")
    captured_sha = session_meta.get("cc_session_sha256")
    if not jsonl_path or not captured_sha:
        msg = {"verdict": "no-link",
                "reason": "handoff has no session_meta.cc_session_jsonl/sha256"}
        if args.json:
            print(json.dumps(msg))
        else:
            print(f"no-link: {msg['reason']}")
        return 0  # informational

    jp = Path(str(jsonl_path))
    if not jp.is_file():
        msg = {"verdict": "missing",
                "captured_jsonl": str(jp),
                "captured_sha": captured_sha}
        if args.json:
            print(json.dumps(msg))
        else:
            print(f"missing: linked JSONL no longer at {jp}")
        return 1

    current_sha = hashlib.sha256(jp.read_bytes()).hexdigest()
    if current_sha == captured_sha:
        msg = {"verdict": "match",
                "captured_sha": captured_sha,
                "current_sha": current_sha,
                "jsonl_path": str(jp)}
        if args.json:
            print(json.dumps(msg))
        else:
            print(f"match: sha256 {captured_sha[:12]}... — resume mining safe")
        return 0
    msg = {"verdict": "drift",
            "captured_sha": captured_sha,
            "current_sha": current_sha,
            "jsonl_path": str(jp)}
    if args.json:
        print(json.dumps(msg))
    else:
        print(f"drift: JSONL mutated since handoff was written. "
               f"captured={captured_sha[:12]}... current={current_sha[:12]}...")
    return 1


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
    s_auto.add_argument(
        "--auto-bridge", action="store_true",
        help="after finalize, run bridge --apply on the YAML to capture "
             "durable learnings (decisions / findings / worked / failed) "
             "into the brain. Gated to outcome=SUCCEEDED only — high-"
             "confidence finalizations. Subprocess failures don't block "
             "the finalize. Also honors KAIZEN_HANDOFF_AUTO_BRIDGE=1 env.",
    )
    s_auto.add_argument("--json", action="store_true")
    s_auto.set_defaults(func=_cmd_auto_finalize)

    s_get = sub.add_parser(
        "get",
        help="extract one named section from a handoff YAML — surgical "
             "read for resume agents (avoids the whole-file Read tax). "
             "Use --json for structured output.",
    )
    s_get.add_argument("--file", required=True, help="path to the handoff YAML")
    s_get.add_argument("--section", required=True,
                        help="section name — frontmatter (status/outcome/date/"
                             "session/outcome_assigned_by/outcome_justification) "
                             "OR body (goal/now/test/done_this_session/blockers/"
                             "questions/decisions/findings/worked/failed/next/"
                             "files/code_context/session_meta)")
    s_get.add_argument("--json", action="store_true",
                        help="JSON output (default: human-readable — one line "
                             "per list item, raw scalar for strings)")
    s_get.set_defaults(func=_cmd_get)

    s_ap = sub.add_parser(
        "append",
        help="append one entry to a list-section (done_this_session / blockers / "
             "questions / decisions / findings / worked / failed / next). "
             "Atomic write; preserves the rest of the file byte-for-byte."
    )
    s_ap.add_argument("--file", required=True, help="path to the handoff YAML")
    s_ap.add_argument("--section", required=True,
                       help="list-section name to append to")
    s_ap.add_argument("--task", default=None,
                       help="task text — used as {task: ...} for done_this_session, "
                            "or as plain string entry for other sections")
    s_ap.add_argument("--entry", default=None,
                       help="plain string entry (alt to --task for non-task sections)")
    s_ap.add_argument("--files", default=None,
                       help="comma-separated file paths — attached as files: [...] "
                            "when section is done_this_session")
    s_ap.add_argument("--json", action="store_true")
    s_ap.set_defaults(func=_cmd_append)

    s_co = sub.add_parser(
        "cost",
        help="token-budget estimator — total size + per-section breakdown + "
             "threshold verdict. Pure read; chars/4 approximation. "
             "Threshold via KAIZEN_HANDOFF_COST_TOKEN_BUDGET (default 2000)."
    )
    s_co.add_argument("--file", required=True, help="path to the handoff YAML")
    s_co.add_argument("--json", action="store_true")
    s_co.set_defaults(func=_cmd_cost)

    s_tr = sub.add_parser(
        "tree",
        help="bidirectional commit↔task map — for each done_this_session "
             "entry with files, list commits since the handoff date that "
             "touched them. Emits {by_task, by_commit, skipped_no_files}."
    )
    s_tr.add_argument("--file", required=True, help="path to the handoff YAML")
    s_tr.add_argument("--since", default=None,
                       help="git log --since cutoff (default: handoff `date:` field)")
    s_tr.add_argument("--repo", default=None,
                       help="repo path for git log (default: cwd)")
    s_tr.set_defaults(func=_cmd_tree)

    s_vh = sub.add_parser(
        "verify-hash",
        help="re-hash the linked JSONL + compare against captured sha256 — "
             "detects mid-flight rotation/truncation (verdict: match | "
             "drift | missing | no-link)",
    )
    s_vh.add_argument("--file", required=True, help="path to the handoff YAML")
    s_vh.add_argument("--json", action="store_true")
    s_vh.set_defaults(func=_cmd_verify_hash)

    args = p.parse_args(argv)
    if args.cmd is None:
        return _cmd_latest(argparse.Namespace(json=False))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
