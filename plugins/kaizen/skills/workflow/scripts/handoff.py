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


def _check_patterns(parsed: dict, repo_root: Path) -> list[dict]:
    """pattern-still-present (worked) + failed-pattern-reintroduced (failed)."""
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

    # Atomic write: tempfile in same dir → rename.
    tmp = fp.with_suffix(fp.suffix + ".auto-finalize.tmp")
    tmp.write_text(rewritten, encoding="utf-8")
    tmp.replace(fp)

    # Re-index. Session name = parent dir name (matches the skill's
    # "session-name groups handoffs into one folder" convention).
    session_id = args.session or fp.parent.name
    rid = _core.save_handoff(
        session_id, rewritten, str(fp.resolve()), status=args.status,
    )

    result = {
        "id": rid,
        "session_id": session_id,
        "file_path": str(fp.resolve()),
        "status": args.status,
        "outcome": args.outcome,
        "outcome_assigned_by": args.assigned_by,
        "outcome_justification": args.justification,
    }
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
    s_auto.add_argument("--json", action="store_true")
    s_auto.set_defaults(func=_cmd_auto_finalize)

    args = p.parse_args(argv)
    if args.cmd is None:
        return _cmd_latest(argparse.Namespace(json=False))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
