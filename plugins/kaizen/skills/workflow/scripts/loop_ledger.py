#!/usr/bin/env python3
"""Shared ledger-transition helper for kaizen Ralph-loop Stop hooks.

Called by hooks/{claude,codex}/stop-ralph.sh once per Stop event. Owns the
cheat-proof state transitions:

  1. Parse the state-file body. JSON → ledger mode; non-JSON → freeform mode.
  2. In ledger mode, run each pending item's `verify` command. Items that
     exit 0 are moved to `completed` (with iteration + timestamp). Items
     without `verify` or whose verify failed stay in `pending`.
  3. Re-serialize the state-file body. The `completed` array is append-only
     from the hook's perspective — the AGENT can only append to `pending`.
  4. Emit a JSON decision matching the CC/Codex Stop-hook contract:
       {"action": "complete", "reason": "..."}
       {"action": "complete-empty", "reason": "..."}        # warn — no work
       {"action": "block",    "reason": <prompt>, "iteration_note": "..."}

State-file body schema (JSON, after the YAML frontmatter and `---`):

    {
      "pending":   [{"desc": "...", "verify": "<bash cmd or null>"}, ...],
      "completed": [{"desc": "...", "verify": "...",
                     "iteration": 3,
                     "completed_at": "2026-05-13T22:00:00Z"}, ...],
      "added_during_loop": []   // optional — agent-tracked additions
    }

Freeform mode (backward compat): body that fails JSON parse is treated as
a single-prompt body. Empty body still ends the loop ("ledger empty").

Cheat-proofing properties:
  - Agent CANNOT add to `completed` directly — the hook is the only writer.
  - Agent CAN add to `pending` (append new work mid-loop).
  - Agent CAN edit `pending` item descriptions (no contract about content).
  - Items with `verify` only complete via passing exit-0 verify.
  - Items WITHOUT `verify` (legacy single-prompt) are agent-trusted: their
    removal from `pending` ends the loop, but the completion-with-no-evidence
    case emits a `complete-empty` warning.

Usage:
    python3 loop_ledger.py <state-file> <iteration>

    Prints decision JSON to stdout. Exit code 0 on success, 1 on parse
    failure (state file corrupted).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

VERIFY_TIMEOUT_SECONDS = 30

# ─── Failproof knobs (env-overridable) ───────────────────────────────
# Defaults chosen to be generous — these are last-resort safety rails,
# not normal-flow exits.

DEFAULT_MAX_AGE_DAYS = 30     # state file older than this → auto-cancel
DEFAULT_STUCK_ITERATIONS = 5   # same body sha for N iters → auto-end


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_block_with_delimiters, body). Body excludes both `---`."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return "", text
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return "", text
    fm = "\n".join(lines[: end_idx + 1])
    body = "\n".join(lines[end_idx + 1 :])
    return fm, body


def parse_body(body: str) -> tuple[dict | None, str]:
    """Return (ledger_dict, freeform_body). ledger_dict is None for freeform."""
    stripped = body.strip()
    if not stripped:
        return None, ""
    if not stripped.startswith("{"):
        return None, body
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return None, body
    if not isinstance(data, dict):
        return None, body
    return data, body


def run_verify(cmd: str) -> bool:
    """Run a bash verify command; return True iff exit code 0 within timeout."""
    try:
        result = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True,
            text=True,
            timeout=VERIFY_TIMEOUT_SECONDS,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── Promise matching (robust against code-fence + mid-text mentions) ─


import re as _re

_FENCED_CODE = _re.compile(r"```[\s\S]*?```", _re.MULTILINE)
_INLINE_CODE = _re.compile(r"`[^`\n]*`")
_TRAILING_PROMISE = _re.compile(
    r"<promise>\s*(.*?)\s*</promise>\s*\Z",
    _re.DOTALL,
)
_ANY_PROMISE = _re.compile(r"<promise>\s*(.*?)\s*</promise>", _re.DOTALL)


def check_completion_promise(
    last_output: str,
    expected_phrase: str,
) -> bool:
    """Return True iff `last_output` legitimately emits the completion phrase.

    Robust matching to prevent false positives like the 2026-05-14 incident
    where a `<promise>DONE</promise>` token in a code-fence example
    terminated the loop:

    1. Strip ```fenced``` and `inline` code blocks (the agent may discuss
       the promise pattern in code without intending to emit it).
    2. After stripping, require the promise tag to be at the END of the
       message (modulo trailing whitespace). Mid-text mentions don't
       count — if the agent meant to emit, they'd put it last.
    3. Exact-string match against the configured phrase (existing
       contract — no glob, no regex).
    """
    if not last_output or not expected_phrase:
        return False
    stripped = _FENCED_CODE.sub("", last_output)
    stripped = _INLINE_CODE.sub("", stripped)
    m = _TRAILING_PROMISE.search(stripped)
    if not m:
        return False
    found = " ".join(m.group(1).split())  # collapse whitespace
    want = " ".join(expected_phrase.split())
    return found == want


def has_unsafe_promise_mention(last_output: str) -> bool:
    """Diagnostic: True if the message contains a promise tag that is NOT
    at the end (i.e. would have triggered the old buggy regex). The hook
    surfaces this as a warning when present so the user can see why the
    loop did NOT end despite a mention."""
    if not last_output:
        return False
    stripped = _FENCED_CODE.sub("", last_output)
    stripped = _INLINE_CODE.sub("", stripped)
    if _TRAILING_PROMISE.search(stripped):
        return False  # legitimate trailing promise — not unsafe
    return bool(_ANY_PROMISE.search(stripped))


def transition(ledger: dict, iteration: int) -> tuple[dict, list[dict]]:
    """Run verify on each pending item; move passing ones to completed.

    Returns (new_ledger, just_completed_items).
    The hook OWNS the completed list — only this function writes to it."""
    pending_in = ledger.get("pending") or []
    completed_in = ledger.get("completed") or []
    new_pending: list[dict] = []
    just_completed: list[dict] = []
    for item in pending_in:
        if not isinstance(item, dict):
            # Malformed item — drop it (cheat-proof: agents can't smuggle
            # primitives into the ledger).
            continue
        verify_cmd = item.get("verify")
        if isinstance(verify_cmd, str) and verify_cmd.strip() and run_verify(verify_cmd):
            completed_entry = {
                **item,
                "iteration": iteration,
                "completed_at": iso_now(),
            }
            just_completed.append(completed_entry)
        else:
            new_pending.append(item)
    new_ledger = {
        "pending": new_pending,
        "completed": completed_in + just_completed,
    }
    # Preserve any agent-added optional keys (e.g. notes) so we don't strip them.
    for key in ledger:
        if key not in ("pending", "completed"):
            new_ledger[key] = ledger[key]
    return new_ledger, just_completed


def render_prompt(pending: list[dict]) -> str:
    """Build the next-iteration prompt from pending items.

    Format: numbered list with desc + (verify) annotation."""
    if not pending:
        return ""
    lines = []
    for i, item in enumerate(pending, 1):
        desc = item.get("desc") or "(no description)"
        verify = item.get("verify")
        if verify:
            lines.append(f"{i}. {desc}\n   verify: {verify}")
        else:
            lines.append(f"{i}. {desc}")
    return "\n".join(lines)


def _max_age_days() -> int:
    raw = os.environ.get("KAIZEN_LOOP_MAX_AGE_DAYS", str(DEFAULT_MAX_AGE_DAYS))
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MAX_AGE_DAYS


def _stuck_iterations() -> int:
    raw = os.environ.get("KAIZEN_LOOP_STUCK_ITERATIONS", str(DEFAULT_STUCK_ITERATIONS))
    try:
        return max(2, int(raw))
    except ValueError:
        return DEFAULT_STUCK_ITERATIONS


def _frontmatter_value(fm: str, key: str) -> str:
    """Plain extract of `key: <value>` from a frontmatter block. Strips
    surrounding quotes. Empty string when absent."""
    prefix = f"{key}:"
    for line in fm.split("\n"):
        s = line.strip()
        if s.startswith(prefix):
            v = s[len(prefix):].strip()
            if (len(v) >= 2) and v[0] == v[-1] and v[0] in ('"', "'"):
                v = v[1:-1]
            return v
    return ""


def _is_stale(fm: str) -> tuple[bool, int]:
    """Return (is_stale, age_days). True iff started_at is older than
    KAIZEN_LOOP_MAX_AGE_DAYS. Loop state files left behind by crashed
    sessions get auto-cleaned by this check on the next Stop event."""
    started_iso = _frontmatter_value(fm, "started_at")
    if not started_iso:
        return False, 0
    try:
        started = dt.datetime.fromisoformat(started_iso.replace("Z", "+00:00"))
    except ValueError:
        return False, 0
    if started.tzinfo is None:
        started = started.replace(tzinfo=dt.timezone.utc)
    age = (dt.datetime.now(dt.timezone.utc) - started).days
    return age > _max_age_days(), age


def _body_sha(body: str) -> str:
    """Stable sha of the body content (after stripping the framing
    frontmatter)."""
    import hashlib as _h
    return _h.sha256(body.strip().encode("utf-8")).hexdigest()[:16]


def _check_no_progress(fm: str, body_now_sha: str) -> tuple[bool, int]:
    """Return (is_stuck, run_count). Stuck when the body hasn't changed
    for KAIZEN_LOOP_STUCK_ITERATIONS consecutive iterations.

    The hook persists `last_body_sha:` and `stuck_run:` fields in the
    frontmatter (see _persist_progress_marks). When sha matches, the
    counter increments; when it differs, the counter resets to 0."""
    prior_sha = _frontmatter_value(fm, "last_body_sha")
    try:
        run = int(_frontmatter_value(fm, "stuck_run") or "0")
    except ValueError:
        run = 0
    if prior_sha and prior_sha == body_now_sha:
        run += 1
    else:
        run = 0
    return run >= _stuck_iterations(), run


def _persist_progress_marks(fm: str, body_now_sha: str, stuck_run: int) -> str:
    """Update or append `last_body_sha:` + `stuck_run:` in the
    frontmatter block (between the two `---` markers). Idempotent."""
    lines = fm.split("\n")
    out: list[str] = []
    saw_sha = False
    saw_run = False
    for line in lines:
        s = line.strip()
        if s.startswith("last_body_sha:"):
            out.append(f'last_body_sha: "{body_now_sha}"')
            saw_sha = True
        elif s.startswith("stuck_run:"):
            out.append(f"stuck_run: {stuck_run}")
            saw_run = True
        elif s == "---" and len(out) > 1:
            # Closing marker — inject fields just before it if not seen yet.
            if not saw_sha:
                out.append(f'last_body_sha: "{body_now_sha}"')
                saw_sha = True
            if not saw_run:
                out.append(f"stuck_run: {stuck_run}")
                saw_run = True
            out.append(line)
        else:
            out.append(line)
    return "\n".join(out)


def decide(state_path: Path, iteration: int) -> dict:
    """Main entry point. Returns the decision dict for the caller hook."""
    if not state_path.is_file():
        return {"action": "noop"}
    text = state_path.read_text()
    fm, body = split_frontmatter(text)

    # ─── Safety rail 1: stale state file (crashed session, abandoned loop) ──
    stale, age = _is_stale(fm)
    if stale:
        return {
            "action": "complete-empty",
            "reason": (
                f"Ralph loop auto-cancelled: state file is {age}d old "
                f"(> KAIZEN_LOOP_MAX_AGE_DAYS={_max_age_days()})."
            ),
            "mode": "stale",
        }

    # ─── Safety rail 2: no-progress detection ───────────────────────────────
    body_now_sha = _body_sha(body)
    stuck, run = _check_no_progress(fm, body_now_sha)
    if stuck:
        return {
            "action": "complete-empty",
            "reason": (
                f"Ralph loop auto-cancelled: body sha unchanged for "
                f"{run} consecutive iterations "
                f"(>= KAIZEN_LOOP_STUCK_ITERATIONS={_stuck_iterations()}). "
                "Either work is genuinely complete and the agent forgot to "
                "emit the promise, or the iteration is making no progress."
            ),
            "mode": "stuck",
            "stuck_run": run,
        }

    ledger, _ = parse_body(body)

    # ─── Freeform / legacy path ──────────────────────────────────────
    if ledger is None:
        if not body.strip():
            return {
                "action": "complete-empty",
                "reason": "Ralph loop completed: ledger empty.",
            }
        # Persist progress marks so the next decide() can detect stuck-state.
        new_fm = _persist_progress_marks(fm, body_now_sha, run)
        state_path.write_text(f"{new_fm}\n{body}".rstrip() + "\n")
        return {
            "action": "block",
            "reason": body.strip(),
            "mode": "freeform",
            "stuck_run": run,
        }

    # ─── Structured ledger path ──────────────────────────────────────
    new_ledger, just_completed = transition(ledger, iteration)
    # Persist updated ledger + progress marks
    new_body = json.dumps(new_ledger, indent=2)
    new_body_sha = _body_sha(new_body)
    new_fm = _persist_progress_marks(fm, new_body_sha, run)
    state_path.write_text(f"{new_fm}\n{new_body}\n")

    pending = new_ledger["pending"]
    completed = new_ledger["completed"]

    if not pending:
        if not completed:
            return {
                "action": "complete-empty",
                "reason": (
                    "Ralph loop ended: ledger empty BUT no items recorded as "
                    "completed by the verify gate (possible empty start or "
                    "agent removed unverified items)."
                ),
                "mode": "ledger",
            }
        return {
            "action": "complete",
            "reason": (
                f"Ralph loop completed: {len(completed)} item(s) verified "
                f"(see `.kaizen/loop.state.md` before deletion for the audit log)."
            ),
            "completed_count": len(completed),
            "mode": "ledger",
        }

    return {
        "action": "block",
        "reason": render_prompt(pending),
        "pending_count": len(pending),
        "just_completed_count": len(just_completed),
        "mode": "ledger",
    }


def main(argv: list[str]) -> int:
    # Subcommand mode: `loop_ledger.py promise-check <last_output_file> <expected_phrase>`
    # Exit code 0 iff promise matched, 1 otherwise. Used by stop-ralph.sh
    # to delegate the robust promise-match logic to Python.
    if len(argv) >= 2 and argv[1] == "promise-check":
        if len(argv) < 4:
            sys.stderr.write(
                "usage: loop_ledger.py promise-check <last-output-file> <expected-phrase>\n"
            )
            return 2
        try:
            last_output = Path(argv[2]).read_text()
        except (OSError, UnicodeDecodeError):
            return 1
        expected = argv[3]
        return 0 if check_completion_promise(last_output, expected) else 1

    if len(argv) < 3:
        sys.stderr.write(
            "usage: loop_ledger.py <state-file> <iteration>\n"
            "       loop_ledger.py promise-check <last-output-file> <phrase>\n"
        )
        return 2
    state_path = Path(argv[1])
    try:
        iteration = int(argv[2])
    except ValueError:
        sys.stderr.write("loop_ledger.py: iteration must be int\n")
        return 2
    result = decide(state_path, iteration)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
