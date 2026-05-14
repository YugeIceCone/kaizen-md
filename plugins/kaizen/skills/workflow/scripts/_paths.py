"""Shared path constants for kaizen scripts (v1.22.0 unification).

Before v1.22.0, kaizen's user-global state lived in 6 sibling dirs under
~/.claude/. v1.22.0 unifies them under a single ~/.claude/.kaizen/ root
with named subdirs, plus moves <repo>/.workflow/ → <repo>/.kaizen/workflow/
on the project side.

This module is the SSOT for those paths. Every kaizen Python script that
touches state SHOULD import from here (instead of inlining constants).
The mirroring shell module is `_paths.sh` (source-compatible export shape).

## User-global layout (after v1.22.0)

    ~/.claude/.kaizen/
        trace/        events.jsonl, index.db
        knowledge/    index.db
        daemon/       state.json
        inbox/        <ts>-<n>.json
        backups/      <repo-slug>/<UTC>.tar.gz
        schemas/      <user-defined-name>/schema.yaml

## Project-side layout (after v1.22.0)

    <repo>/.kaizen/
        hooks/        pre-commit (symlink to plugin)
        cache/        compile-barrier verdict cache
        workflow/     state.json, snapshot.md, progress.md, backlog.{json,md}, decisions.md
        workflow/schemas/  project-pinned workflow schemas
        onboard.db    codebase index

## Legacy fallback

`LEGACY_PATHS` maps each kaizen-owned location to its pre-1.22 sibling.
The migrator `migrate_paths.sh` consults this to move OLD → NEW data
without loss. Scripts no longer auto-fallback at read time; users either
run the migrator (auto-invoked by `kaizen:setup` and `kaizen:setup --enable-all`)
or set the override env var.

## Env overrides

Each path is individually overridable so users can pin a custom location:

    KAIZEN_DIR              root of the user-global tree (default ~/.claude/.kaizen)
    KAIZEN_TRACE_DIR        override the trace subdir
    KAIZEN_KNOWLEDGE_DIR    override the knowledge subdir
    KAIZEN_DAEMON_DIR       override the daemon subdir
    KAIZEN_INBOX_DIR        override the inbox subdir
    KAIZEN_BACKUP_DIR       override the backup subdir
    KAIZEN_USER_SCHEMAS     override the user schemas subdir
    WORKFLOW_STATE_DIR      override the per-project workflow dir
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Single-source-of-truth: import the editable knobs from config.py.
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import config as _cfg  # noqa: E402  — relative import for self-contained scripts


HOME = Path(os.path.expanduser("~"))

# ─── Plugin index root (SSOT for the kaizen-md repo root) ────────────
# Consumed by daemon.py (watch + tick index refresh), setup.sh and
# enable_all.sh. KAIZEN_PLUGIN_INDEX_ROOT wins; else the marketplace
# dir, symlink-resolved (the default marketplace path is a symlink into
# ~/workspace/kaizen-md).
_DEFAULT_MARKETPLACE = HOME / ".claude" / "local-marketplaces" / "kaizen-md"


def plugin_index_root() -> Path:
    """Resolve the kaizen-md repo root to index. Override:
    KAIZEN_PLUGIN_INDEX_ROOT; else realpath(KAIZEN_MARKETPLACE | default)."""
    override = os.environ.get("KAIZEN_PLUGIN_INDEX_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    market = os.environ.get("KAIZEN_MARKETPLACE")
    base = Path(market).expanduser() if market else _DEFAULT_MARKETPLACE
    return base.resolve()


# ─── User-global root ────────────────────────────────────────────────

KAIZEN_USER_DIR = Path(
    os.environ.get("KAIZEN_DIR", HOME / ".claude" / _cfg.USER_DIR_NAME)
)


# ─── User-global subdirs ─────────────────────────────────────────────

TRACE_DIR = Path(
    os.environ.get("KAIZEN_TRACE_DIR", KAIZEN_USER_DIR / _cfg.USER_TRACE_NAME)
)
TRACE_FILE = TRACE_DIR / "events.jsonl"
TRACE_DB = TRACE_DIR / "index.db"

KNOWLEDGE_DIR = Path(
    os.environ.get("KAIZEN_KNOWLEDGE_DIR", KAIZEN_USER_DIR / _cfg.USER_KNOWLEDGE_NAME)
)
KNOWLEDGE_DB = KNOWLEDGE_DIR / "index.db"

DAEMON_DIR = Path(
    os.environ.get("KAIZEN_DAEMON_DIR", KAIZEN_USER_DIR / _cfg.USER_DAEMON_NAME)
)
DAEMON_STATE = DAEMON_DIR / "state.json"

INBOX_DIR = Path(
    os.environ.get("KAIZEN_INBOX_DIR", KAIZEN_USER_DIR / _cfg.USER_INBOX_NAME)
)

BACKUP_DIR = Path(
    os.environ.get("KAIZEN_BACKUP_DIR", KAIZEN_USER_DIR / _cfg.USER_BACKUPS_NAME)
)

USER_SCHEMAS = Path(
    os.environ.get("KAIZEN_USER_SCHEMAS", KAIZEN_USER_DIR / _cfg.USER_SCHEMAS_NAME)
)

# v1.24.0+ — scrape index (SmartScraperGraph extractions + embeddings).
SCRAPE_DIR = Path(
    os.environ.get("KAIZEN_SCRAPE_DIR", KAIZEN_USER_DIR / _cfg.USER_SCRAPE_NAME)
)
SCRAPE_DB = SCRAPE_DIR / "index.db"

# v1.30.0+ — observe snapshots (deterministic captures + per-layer queries).
OBSERVE_DIR = Path(
    os.environ.get("KAIZEN_OBSERVE_DIR", KAIZEN_USER_DIR / _cfg.USER_OBSERVE_NAME)
)
OBSERVE_SNAPSHOTS = OBSERVE_DIR / "snapshots"

# v1.30.0+ — Claude docs semantic index (ericbuess/claude-code-docs mirror + sem search).
CLAUDE_DOCS_DIR = Path(
    os.environ.get("KAIZEN_CLAUDE_DOCS_DIR", KAIZEN_USER_DIR / _cfg.USER_CLAUDE_DOCS_NAME)
)
CLAUDE_DOCS_DB = CLAUDE_DOCS_DIR / "index.db"
CLAUDE_DOCS_SRC = Path(
    os.environ.get("KAIZEN_CLAUDE_DOCS_SRC", CLAUDE_DOCS_DIR / "src")
)

# v1.30.0+ — install log (per-machine kaizen install/setup events).
INSTALL_LOG = Path(
    os.environ.get("KAIZEN_INSTALL_LOG", KAIZEN_USER_DIR / _cfg.INSTALL_LOG_NAME)
)

# v1.30.0+ — archive slot for stale legacy dirs migrated by `migrate_paths.sh`
# when the canonical location already has live data. Lets every kaizen state
# stay under the unified tree while preserving the legacy bits for inspection.
LEGACY_ARCHIVE_DIR = KAIZEN_USER_DIR / _cfg.LEGACY_ARCHIVE_NAME


# ─── Project-side (resolved at call time, per cwd) ───────────────────


def project_workflow_dir(project_root: Path | None = None) -> Path:
    """Return <repo>/.kaizen/workflow (or WORKFLOW_STATE_DIR override).

    Resolves at call time so cwd changes mid-script are honored. Pass an
    explicit project_root for non-cwd resolution."""
    env = os.environ.get("WORKFLOW_STATE_DIR")
    if env:
        return Path(env).expanduser()
    root = project_root or Path.cwd()
    return root / _cfg.PROJECT_KAIZEN_NAME / _cfg.PROJECT_WORKFLOW_NAME


def project_schemas_dir(project_root: Path | None = None) -> Path:
    """Per-project workflow schemas: <repo>/.kaizen/workflow/schemas/."""
    return project_workflow_dir(project_root) / "schemas"


def project_kaizen_dir(project_root: Path | None = None) -> Path:
    """Per-project kaizen root: <repo>/.kaizen/."""
    root = project_root or Path.cwd()
    return root / _cfg.PROJECT_KAIZEN_NAME


# ─── Legacy paths (consulted by the migrator only) ───────────────────

LEGACY_PATHS: dict[str, Path] = {
    "trace": HOME / ".claude" / ".kaizen-trace",
    "knowledge": HOME / ".claude" / ".kaizen-knowledge",
    "daemon": HOME / ".claude" / ".kaizen-daemon",
    "inbox": HOME / ".claude" / "kaizen-inbox",
    "backups": HOME / ".claude" / "backups" / "kaizen",
    "schemas": HOME / ".claude" / "kaizen-schemas",
    "observe": HOME / ".claude" / ".kaizen-observe",
    "install_log": HOME / ".claude" / "kaizen-install.log",
}

LEGACY_TO_NEW: dict[Path, Path] = {
    LEGACY_PATHS["trace"]: TRACE_DIR,
    LEGACY_PATHS["knowledge"]: KNOWLEDGE_DIR,
    LEGACY_PATHS["daemon"]: DAEMON_DIR,
    LEGACY_PATHS["inbox"]: INBOX_DIR,
    LEGACY_PATHS["backups"]: BACKUP_DIR,
    LEGACY_PATHS["schemas"]: USER_SCHEMAS,
    LEGACY_PATHS["observe"]: OBSERVE_DIR,
    LEGACY_PATHS["install_log"]: INSTALL_LOG,
}


# ─── Self-test ───────────────────────────────────────────────────────


def _self_test() -> None:
    assert TRACE_DIR.parent == KAIZEN_USER_DIR
    assert TRACE_FILE == TRACE_DIR / "events.jsonl"
    assert KNOWLEDGE_DB.parent == KNOWLEDGE_DIR
    assert DAEMON_STATE == DAEMON_DIR / "state.json"
    assert BACKUP_DIR.parent == KAIZEN_USER_DIR
    pwd_root = project_workflow_dir(Path("/tmp/x"))
    assert pwd_root == Path("/tmp/x/.kaizen/workflow"), pwd_root
    sch = project_schemas_dir(Path("/tmp/x"))
    assert sch == Path("/tmp/x/.kaizen/workflow/schemas"), sch
    print("✓ _paths.py self-test pass")
    print(f"  KAIZEN_USER_DIR = {KAIZEN_USER_DIR}")
    print(f"  TRACE_DIR       = {TRACE_DIR}")
    print(f"  KNOWLEDGE_DB    = {KNOWLEDGE_DB}")
    print(f"  INBOX_DIR       = {INBOX_DIR}")


if __name__ == "__main__":
    _self_test()
