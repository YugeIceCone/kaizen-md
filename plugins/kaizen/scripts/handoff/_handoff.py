"""kaizen _handoff — core for the handoff feature: paths, config, and
the SQLite handoff store.

Refactored from the recovered `~/.claude/scripts/stores.py` — the lost
handoff DB helper (see the provenance hunt + CHANGELOG 1.36.0). That
module was a 938-line session-logger god-file; this extracts ONLY the
handoff slice — the `handoffs` table + save / latest / list — into the
canonical kaizen feature shape, plugin-owned instead of depending on
an unshipped external script.

Division of labour: the filesystem YAML at
`<handoffs_dir>/<session>/<ts>.yaml` is the SYSTEM OF RECORD —
agent-authored, portable, human-readable. This SQLite store is the
queryable INDEX — fast `latest` / `list`. `save_handoff` upserts on
`file_path`, so re-saving the same handoff (e.g. after Step 4 sets the
final outcome) updates the row instead of duplicating it.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
# MIGRATION BRIDGE — _sqlite has a shim at legacy scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

import _sqlite as _kz_sqlite  # noqa: E402  — shared SQLite open/meta helpers

PLUGIN_ROOT = SCRIPT_DIR.parent.parent  # scripts/handoff/ → plugins/kaizen/
DOMAIN_DIR = PLUGIN_ROOT / "schemas" / "handoff"

# Mirrors domain/handoff.yaml::status — kept here too so the store can
# coerce defensively without a yaml load on the hot path.
VALID_STATUS = ("partial", "complete", "blocked")

# Outcome buckets the agent (or user) can assign at session-end. Mirrors
# the AskUserQuestion options the handoff skill historically used —
# adding new values here means updating SKILL.md's rubric in the same
# commit.
VALID_OUTCOME = ("SUCCEEDED", "PARTIAL_PLUS", "PARTIAL_MINUS", "FAILED")

# Audit field: who picked the outcome. Auto-finalize defaults to "agent";
# the legacy AskUserQuestion path can pass "user" explicitly.
VALID_ASSIGNED_BY = ("agent", "user")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS handoffs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    file_path   TEXT NOT NULL UNIQUE,
    content     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'partial'
);
CREATE INDEX IF NOT EXISTS idx_handoffs_created ON handoffs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_handoffs_session ON handoffs(session_id);
CREATE TABLE IF NOT EXISTS handoff_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# Handoffs are durable records — favour durability over write speed.
_PRAGMAS = "PRAGMA journal_mode=WAL;\nPRAGMA synchronous=FULL;\n"

# ─── Path resolution (env-aware, mirrors _brain.brain_root) ──────────

def handoff_db_path() -> Path:
    """SQLite handoff-index path. v1.39.0+: lives under data/ via the
    _paths SSOT. Env-overridable (KAIZEN_HANDOFF_DB) for test
    sandboxing — mirrors KAIZEN_BRAIN_DB / KAIZEN_KNOWLEDGE_DB."""
    env = os.environ.get("KAIZEN_HANDOFF_DB")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _paths
    return _paths.HANDOFF_DB.expanduser()

def handoffs_dir() -> Path:
    """Root dir for the canonical handoff YAML files — the system of
    record. Env-overridable (KAIZEN_HANDOFF_DIR)."""
    env = os.environ.get("KAIZEN_HANDOFF_DIR")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return Path("~/.claude/handoff").expanduser()

def now_iso() -> str:
    """UTC ISO-8601 timestamp, millisecond precision (matches the
    recovered stores.py::now_iso so existing rows stay comparable)."""
    return (
        dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )

# ─── Frontmatter rewrite (auto-finalize Step 4) ──────────────────────

# Keys auto-finalize is allowed to touch. Everything else in the
# frontmatter is preserved verbatim.
_FINALIZE_KEYS = (
    "status",
    "outcome",
    "outcome_assigned_by",
    "outcome_justification",
)

def update_frontmatter(text: str, updates: dict[str, str]) -> str:
    """Rewrite a YAML handoff's frontmatter in-place (line-based,
    no PyYAML dep). The handoff skill body's `: ` (colon-space) rule
    keeps every frontmatter line as a flat `key: value` pair, so this
    parser is reliable AND preserves comments / ordering verbatim.

    Behavior:
    - Updates each key in `updates` if it already exists in the frontmatter.
    - Appends new keys (in `updates` insertion order) at the bottom of the
      frontmatter block when absent.
    - Body (everything after the closing `---`) is preserved byte-for-byte.

    Raises ValueError if the input has no opening `---` line."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\n").strip() != "---":
        raise ValueError("handoff YAML missing opening `---` frontmatter delimiter")

    # Find the closing `---` line bounding the frontmatter.
    end_idx: Optional[int] = None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\n").strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        raise ValueError("handoff YAML missing closing `---` frontmatter delimiter")

    fm_lines = lines[1:end_idx]
    new_fm: list[str] = []
    pending = dict(updates)  # consumed as we walk; leftovers append at end
    newline = "\n"

    for line in fm_lines:
        stripped = line.rstrip("\n")
        if ":" in stripped:
            key = stripped.split(":", 1)[0].strip()
            if key in pending:
                new_fm.append(f"{key}: {pending.pop(key)}{newline}")
                continue
        new_fm.append(line)

    # Append any keys not already present, in insertion order.
    for key, value in pending.items():
        new_fm.append(f"{key}: {value}{newline}")

    rebuilt = (
        lines[0]
        + "".join(new_fm)
        + lines[end_idx]
        + "".join(lines[end_idx + 1:])
    )
    return rebuilt

# ─── Store ───────────────────────────────────────────────────────────

def open_db(create: bool = True) -> sqlite3.Connection:
    """Open the handoff index DB via the shared `_sqlite` helper.
    `create=False` skips dir + schema creation (read paths)."""
    return _kz_sqlite.open_indexer_db(
        handoff_db_path(), _SCHEMA_SQL, pragmas=_PRAGMAS, create=create
    )

def save_handoff(
    session_id: str,
    content: str,
    file_path: str,
    *,
    status: str = "partial",
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Index a handoff into the store. Upserts on `file_path` — calling
    this again for the same file (e.g. after Step 4 sets the outcome)
    updates the row rather than duplicating it. Returns the row id.

    The YAML file itself is written by the agent (the handoff skill's
    `create` flow); this only indexes it."""
    if not file_path:
        raise ValueError(
            "file_path is required — the YAML file is the handoff's identity"
        )
    if status not in VALID_STATUS:
        status = "partial"
    own = conn is None
    if own:
        conn = open_db(create=True)
    try:
        conn.execute(
            "INSERT INTO handoffs (session_id, created_at, file_path, content, status) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(file_path) DO UPDATE SET "
            "  session_id = excluded.session_id, "
            "  created_at = excluded.created_at, "
            "  content    = excluded.content, "
            "  status     = excluded.status",
            (session_id, now_iso(), file_path, content, status),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM handoffs WHERE file_path = ?", (file_path,)
        ).fetchone()
        return int(row["id"])
    finally:
        if own:
            conn.close()

def latest_handoffs(
    limit: int = 1, *, conn: Optional[sqlite3.Connection] = None
) -> list[dict]:
    """Most recent handoff(s), newest first — full rows incl. `content`.
    This is what `resume` with no args reads. Returns [] when no store
    exists yet (never raises on a missing/empty DB)."""
    own = conn is None
    if own:
        if not handoff_db_path().exists():
            return []
        conn = open_db(create=False)
    try:
        rows = conn.execute(
            "SELECT id, session_id, created_at, file_path, content, status "
            "FROM handoffs ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        if own:
            conn.close()

# ─── Bridge to brain ─────────────────────────────────────────────────
#
# A handoff carries two kinds of content. Session-EPHEMERAL state
# (goal / now / done_this_session / next / blockers) decays the moment
# the next session starts — it must NOT reach brain's semantic index.
# DURABLE learnings (decisions / findings / worked / failed) are
# exactly what brain wants. The bridge extracts only the second kind;
# it never auto-captures — handoffs are noisy, so the caller reviews.

_BRAIN_SECTIONS = ("decisions", "findings", "worked", "failed")

# A bare `decisions:` / `findings:` / `worked:` / `failed:` line opens a
# section; an indented `- ` line under it is one item.
_SECTION_RE = re.compile(r"^(decisions|findings|worked|failed):\s*$")
_ITEM_RE = re.compile(r"^\s+-\s+(.*\S)\s*$")

def _strip_frontmatter(text: str) -> str:
    """Return the body after a leading `---...---` frontmatter block."""
    if not text.lstrip().startswith("---"):
        return text
    lines = text.splitlines()
    fences = [i for i, ln in enumerate(lines) if ln.strip() == "---"]
    if len(fences) >= 2:
        return "\n".join(lines[fences[1] + 1:])
    return text

def extract_brain_candidates(yaml_text: str) -> list[dict]:
    """Pull the durable-learning items out of a handoff's decisions /
    findings / worked / failed sections — the session-ephemeral
    sections (goal / now / done_this_session / next / blockers) are
    deliberately skipped.

    Uses a lenient line-based section scan, NOT a strict
    ``yaml.safe_load`` of the body. Handoff bodies are prose-heavy —
    colons, em-dashes, quotes mid-sentence — and a single unquoted
    ``: `` anywhere would otherwise sink the whole parse, leaving the
    bridge to silently report "no learnings" (the bug the first live
    `update the handoff` run hit). The scan only cares about the four
    section headers and their ``- `` items, so it is robust to
    whatever prose the items carry. Returns ``[]`` only when those
    sections are genuinely empty.

    Each item: ``{"section": str, "text": str}``."""
    out: list[dict] = []
    section: Optional[str] = None
    cur: Optional[str] = None

    def _flush() -> None:
        nonlocal cur
        if cur is not None:
            text = " ".join(cur.split())
            if text:
                out.append({"section": section, "text": text})
        cur = None

    for line in _strip_frontmatter(yaml_text).splitlines():
        header = _SECTION_RE.match(line)
        if header:
            _flush()
            section = header.group(1)
            continue
        if section is None:
            continue
        # A non-indented, non-blank line closes the current section.
        if line.strip() and not line[0].isspace():
            _flush()
            section = None
            continue
        item = _ITEM_RE.match(line)
        if item:
            _flush()
            cur = item.group(1)
        elif cur is not None and line.strip():
            # continuation line of a multi-line item
            cur += " " + line.strip()
    _flush()
    return out

def list_handoffs(
    limit: int = 20,
    *,
    session_id: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """Recent handoffs, newest first — metadata only (no `content`;
    use `latest_handoffs` for the full YAML). Optionally filtered by
    `session_id`. Returns [] when no store exists yet."""
    own = conn is None
    if own:
        if not handoff_db_path().exists():
            return []
        conn = open_db(create=False)
    try:
        if session_id:
            rows = conn.execute(
                "SELECT id, session_id, created_at, file_path, status FROM handoffs "
                "WHERE session_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, session_id, created_at, file_path, status FROM handoffs "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        if own:
            conn.close()
