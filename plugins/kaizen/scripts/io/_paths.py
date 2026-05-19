"""Shared path constants for kaizen scripts (v1.22.0 unification).

Before v1.22.0, kaizen's user-global state lived in 6 sibling dirs under
~/.claude/. v1.22.0 unifies them under a single ~/.claude/.kaizen/ root
with named subdirs, plus moves <repo>/.workflow/ → <repo>/.kaizen/workflow/
on the project side.

This module is the SSOT for those paths. Every kaizen Python script that
touches state SHOULD import from here (instead of inlining constants).
The mirroring shell module is `_paths.sh` (source-compatible export shape).

## User-global layout (after v1.39.0)

    ~/.claude/.kaizen/
        indexes/
            trace/        events.jsonl, index.db
            knowledge/    index.db
            scrape/       index.db
            claude-docs/  index.db + src/
        data/
            daemon/       state.json, log, watcher.pid, llm-proxy.log
            handoff.db
            manifest.json
            manifest.lock
            profile.env
        snapshots/        <name>.json (was observe/snapshots/)
        brain/            PARA + Persona + Notes + brain.db
        inbox/            <ts>-<n>.json
        backups/          <repo-slug>/<UTC>.tar.gz
        schemas/          <user-defined-name>/schema.yaml
        blobs/            <sha256-hex>
        archive/          stale legacy dirs (was _legacy/)
        install.log

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

Each path is individually overridable so users can pin a custom location
AND so tests can sandbox to a tempdir. The latter is the dominant
real-world consumer — most users don't touch these.

    KAIZEN_DIR              root of the user-global tree (default ~/.claude/.kaizen)
    KAIZEN_TRACE_DIR        override the trace subdir
    KAIZEN_KNOWLEDGE_DIR    override the knowledge subdir
    KAIZEN_DAEMON_DIR       override the daemon subdir
    KAIZEN_INBOX_DIR        override the inbox subdir
    KAIZEN_BACKUP_DIR       override the backup subdir
    KAIZEN_USER_SCHEMAS     override the user schemas subdir
    KAIZEN_BRAIN_DIR        override the Second Brain subdir (v1.38.0+)
    KAIZEN_INDEXES_DIR      override the indexes/ umbrella (v1.39.0+)
    KAIZEN_DATA_DIR         override the data/ umbrella (v1.39.0+)
    KAIZEN_SNAPSHOTS_DIR    override the snapshots/ dir (v1.39.0+)
    KAIZEN_ARCHIVE_DIR      override the archive/ dir (v1.39.0+)
    WORKFLOW_STATE_DIR      override the per-project workflow dir

## Test-surface knobs (kept intentionally despite low user-traffic)

The following env vars exist primarily so tests can sandbox path
resolution to a tempdir without monkeypatching constants:

    KAIZEN_BRAIN_DB         test-only: pin brain.db location independent
                            of KAIZEN_BRAIN_DIR (used by test_build_index,
                            test_brain_mcp)
    KAIZEN_HANDOFF_DB       same shape (used by test_handoff)

These are NOT user-facing knobs — set them only in test fixtures.

## Brain ownership (v1.38.0+)

The Second Brain (formerly owned by the Remember plugin at
``~/.claude/brain``) moves under kaizen's own ``.kaizen/brain``
subtree. ``KAIZEN_BRAIN_DIR`` is the ONLY env var that resolves the
location — legacy ``REMEMBER_BRAIN_PATH`` / ``KAIZEN_BRAIN`` /
``KAIZEN_BRAIN_PATH`` are no longer consulted (single-user clean cut).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Single-source-of-truth: import the editable knobs from config.py.
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
# MIGRATION BRIDGE — config.py + other legacy helpers still at skills/workflow/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "workflow" / "scripts"))
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


# ─── DRY helper for env-overridable feature dirs (consolidation 2026-05-18) ─

def env_overridable_dir(env_name: str, *default_segments: str,
                          base: Path | None = None) -> Path:
    """Resolve a feature directory: env wins; else `base / *default_segments`.

    Replaces the 5-site duplicated pattern:

        def _<feature>_dir() -> Path:
            env = os.environ.get("KAIZEN_<FEATURE>_DIR")
            if env:
                return Path(env)
            return Path.home() / ".claude" / ".kaizen" / "<feature>"

    Usage:
        env_overridable_dir("KAIZEN_OBSERVER_DIR", "observer")
            → $KAIZEN_OBSERVER_DIR or ~/.claude/.kaizen/observer

        env_overridable_dir("KAIZEN_BACKUP_DIR", "backups", "superpowers")
            → $KAIZEN_BACKUP_DIR or ~/.claude/.kaizen/backups/superpowers

    Empty-string env value is treated as unset (falls back to default).
    Per the drift-resilient-config-read iron-law: re-reads os.environ
    on every call (no module-level caching).
    """
    env = os.environ.get(env_name)
    if env:
        return Path(env)
    if base is None:
        base = Path.home() / ".claude" / ".kaizen"
    return base.joinpath(*default_segments)


# ─── v1.39.0 umbrella dirs ───────────────────────────────────────────
#
# Flatten + categorize: 4 search-style dirs go under `indexes/`,
# 5 operational singletons go under `data/`, observe snapshots
# hoist to `snapshots/`, `_legacy` → `archive`. Each umbrella has
# its own KAIZEN_*_DIR env override; the per-feature env overrides
# (KAIZEN_TRACE_DIR etc.) still work and shadow the umbrella.

INDEXES_DIR = Path(
    os.environ.get("KAIZEN_INDEXES_DIR", KAIZEN_USER_DIR / _cfg.USER_INDEXES_NAME)
)
DATA_DIR = Path(
    os.environ.get("KAIZEN_DATA_DIR", KAIZEN_USER_DIR / _cfg.USER_DATA_NAME)
)
SNAPSHOTS_DIR = Path(
    os.environ.get("KAIZEN_SNAPSHOTS_DIR", KAIZEN_USER_DIR / _cfg.USER_SNAPSHOTS_NAME)
)
ARCHIVE_DIR = Path(
    os.environ.get("KAIZEN_ARCHIVE_DIR", KAIZEN_USER_DIR / _cfg.ARCHIVE_NAME)
)


# ─── Indexes (search-style state — under indexes/) ───────────────────

TRACE_DIR = Path(
    os.environ.get("KAIZEN_TRACE_DIR", INDEXES_DIR / _cfg.USER_TRACE_NAME)
)
TRACE_FILE = TRACE_DIR / "events.jsonl"
TRACE_DB = TRACE_DIR / "index.db"

KNOWLEDGE_DIR = Path(
    os.environ.get("KAIZEN_KNOWLEDGE_DIR", INDEXES_DIR / _cfg.USER_KNOWLEDGE_NAME)
)
KNOWLEDGE_DB = KNOWLEDGE_DIR / "index.db"

# v1.24.0+ — scrape index (SmartScraperGraph extractions + embeddings).
SCRAPE_DIR = Path(
    os.environ.get("KAIZEN_SCRAPE_DIR", INDEXES_DIR / _cfg.USER_SCRAPE_NAME)
)
SCRAPE_DB = SCRAPE_DIR / "index.db"

# v1.30.0+ — Claude docs semantic index (ericbuess/claude-code-docs mirror + sem search).
CLAUDE_DOCS_DIR = Path(
    os.environ.get("KAIZEN_CLAUDE_DOCS_DIR", INDEXES_DIR / _cfg.USER_CLAUDE_DOCS_NAME)
)
CLAUDE_DOCS_DB = CLAUDE_DOCS_DIR / "index.db"
CLAUDE_DOCS_SRC = Path(
    os.environ.get("KAIZEN_CLAUDE_DOCS_SRC", CLAUDE_DOCS_DIR / "src")
)


# ─── Data (operational singletons — under data/) ─────────────────────

DAEMON_DIR = Path(
    os.environ.get("KAIZEN_DAEMON_DIR", DATA_DIR / _cfg.USER_DAEMON_NAME)
)
DAEMON_STATE = DAEMON_DIR / "state.json"

HANDOFF_DB = Path(
    os.environ.get("KAIZEN_HANDOFF_DB", DATA_DIR / "handoff.db")
)
MANIFEST_JSON = Path(
    os.environ.get("KAIZEN_MANIFEST_JSON", DATA_DIR / "manifest.json")
)
MANIFEST_LOCK = Path(
    os.environ.get("KAIZEN_MANIFEST_LOCK", DATA_DIR / "manifest.lock")
)
PROFILE_ENV = Path(
    os.environ.get("KAIZEN_PROFILE_ENV", DATA_DIR / "profile.env")
)


# ─── Snapshots (observe captures, hoisted from observe/snapshots/) ───

OBSERVE_SNAPSHOTS = SNAPSHOTS_DIR
# v1.39.0+ legacy alias — OBSERVE_DIR previously held observe/snapshots/;
# now snapshots are top-level. Code that imported OBSERVE_DIR for the
# parent dir of snapshots/ still gets a working path.
OBSERVE_DIR = SNAPSHOTS_DIR


# ─── Singletons at the user-global root ──────────────────────────────

INBOX_DIR = Path(
    os.environ.get("KAIZEN_INBOX_DIR", KAIZEN_USER_DIR / _cfg.USER_INBOX_NAME)
)

BACKUP_DIR = Path(
    os.environ.get("KAIZEN_BACKUP_DIR", KAIZEN_USER_DIR / _cfg.USER_BACKUPS_NAME)
)

USER_SCHEMAS = Path(
    os.environ.get("KAIZEN_USER_SCHEMAS", KAIZEN_USER_DIR / _cfg.USER_SCHEMAS_NAME)
)

# v1.30.0+ — install log (per-machine kaizen install/setup events).
# Stays at the user-global root (single user-visible log).
INSTALL_LOG = Path(
    os.environ.get("KAIZEN_INSTALL_LOG", KAIZEN_USER_DIR / _cfg.INSTALL_LOG_NAME)
)

# v1.38.0+ — Second Brain (PARA structure + Persona + Notes + index DB).
# Owned by kaizen post-Remember-retirement. Resolves ONLY via
# KAIZEN_BRAIN_DIR; legacy REMEMBER_BRAIN_PATH is no longer honored.
BRAIN_DIR = Path(
    os.environ.get("KAIZEN_BRAIN_DIR", KAIZEN_USER_DIR / _cfg.USER_BRAIN_NAME)
)
BRAIN_DB = BRAIN_DIR / "brain.db"
BRAIN_NOTES = BRAIN_DIR / "Notes"
BRAIN_PERSONA = BRAIN_DIR / "Persona.md"

# v1.39.0+ — archive slot for stale legacy dirs migrated by `path_migrate.py`.
# Replaces the v1.30 `_legacy` dir (kept reachable in LEGACY_PATHS).
LEGACY_ARCHIVE_DIR = ARCHIVE_DIR


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
    # pre-v1.22 sibling-dir legacy locations
    "trace": HOME / ".claude" / ".kaizen-trace",
    "knowledge": HOME / ".claude" / ".kaizen-knowledge",
    "daemon": HOME / ".claude" / ".kaizen-daemon",
    "inbox": HOME / ".claude" / "kaizen-inbox",
    "backups": HOME / ".claude" / "backups" / "kaizen",
    "schemas": HOME / ".claude" / "kaizen-schemas",
    "observe": HOME / ".claude" / ".kaizen-observe",
    "install_log": HOME / ".claude" / "kaizen-install.log",
    # v1.38.0 brain migration source
    "brain": HOME / ".claude" / "brain",
    # v1.39.0 restructure sources (formerly siblings under .kaizen/)
    "trace_v138":         KAIZEN_USER_DIR / _cfg.USER_TRACE_NAME,
    "knowledge_v138":     KAIZEN_USER_DIR / _cfg.USER_KNOWLEDGE_NAME,
    "scrape_v138":        KAIZEN_USER_DIR / _cfg.USER_SCRAPE_NAME,
    "claude_docs_v138":   KAIZEN_USER_DIR / _cfg.USER_CLAUDE_DOCS_NAME,
    "daemon_v138":        KAIZEN_USER_DIR / _cfg.USER_DAEMON_NAME,
    "observe_v138":       KAIZEN_USER_DIR / _cfg.USER_OBSERVE_NAME,
    "handoff_db_v138":    KAIZEN_USER_DIR / "handoff.db",
    "manifest_json_v138": KAIZEN_USER_DIR / "manifest.json",
    "manifest_lock_v138": KAIZEN_USER_DIR / "manifest.lock",
    "profile_env_v138":   KAIZEN_USER_DIR / "profile.env",
    "archive_v138":       KAIZEN_USER_DIR / _cfg.LEGACY_ARCHIVE_NAME,  # _legacy → archive
    # DEBT-3: vestigial embed pipeline (pre-v1.22). Zero referrers in
    # current code (`_adapters.py`, `embed_chunked.py`, etc. were
    # superseded by `_embed.py` / `_chunk.py` / `_ast_chunk.py` in
    # `scripts/`). Surfaces in `kaizen-migrate path status` so the user
    # can choose to archive it to ARCHIVE_DIR.
    "vestigial_scripts":  KAIZEN_USER_DIR / "scripts",
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
    LEGACY_PATHS["brain"]: BRAIN_DIR,
    # v1.39.0 restructure
    LEGACY_PATHS["trace_v138"]: TRACE_DIR,
    LEGACY_PATHS["knowledge_v138"]: KNOWLEDGE_DIR,
    LEGACY_PATHS["scrape_v138"]: SCRAPE_DIR,
    LEGACY_PATHS["claude_docs_v138"]: CLAUDE_DOCS_DIR,
    LEGACY_PATHS["daemon_v138"]: DAEMON_DIR,
    LEGACY_PATHS["observe_v138"]: SNAPSHOTS_DIR,
    LEGACY_PATHS["handoff_db_v138"]: HANDOFF_DB,
    LEGACY_PATHS["manifest_json_v138"]: MANIFEST_JSON,
    LEGACY_PATHS["manifest_lock_v138"]: MANIFEST_LOCK,
    LEGACY_PATHS["profile_env_v138"]: PROFILE_ENV,
    LEGACY_PATHS["archive_v138"]: ARCHIVE_DIR,
    # DEBT-3: vestigial scripts dir → archive/ subdir (preserves history)
    LEGACY_PATHS["vestigial_scripts"]: ARCHIVE_DIR / "scripts-pre-v1.22",
}


# ─── Self-test ───────────────────────────────────────────────────────


def _self_test() -> None:
    # v1.39.0 layout — TRACE / KNOWLEDGE / SCRAPE / CLAUDE_DOCS under indexes/
    assert TRACE_DIR.parent == INDEXES_DIR, TRACE_DIR
    assert KNOWLEDGE_DIR.parent == INDEXES_DIR
    assert SCRAPE_DIR.parent == INDEXES_DIR
    assert CLAUDE_DOCS_DIR.parent == INDEXES_DIR
    assert TRACE_FILE == TRACE_DIR / "events.jsonl"
    assert KNOWLEDGE_DB.parent == KNOWLEDGE_DIR
    # DAEMON + HANDOFF_DB + MANIFEST_{JSON,LOCK} + PROFILE_ENV under data/
    assert DAEMON_DIR.parent == DATA_DIR
    assert HANDOFF_DB.parent == DATA_DIR
    assert MANIFEST_JSON.parent == DATA_DIR
    assert PROFILE_ENV.parent == DATA_DIR
    assert DAEMON_STATE == DAEMON_DIR / "state.json"
    # SNAPSHOTS hoisted to top-level
    assert SNAPSHOTS_DIR.parent == KAIZEN_USER_DIR
    assert OBSERVE_SNAPSHOTS == SNAPSHOTS_DIR  # legacy alias still works
    # Singletons at user-global root (unchanged by v1.39.0)
    assert BACKUP_DIR.parent == KAIZEN_USER_DIR
    assert BRAIN_DIR.parent == KAIZEN_USER_DIR
    assert INBOX_DIR.parent == KAIZEN_USER_DIR
    assert BRAIN_DB == BRAIN_DIR / "brain.db"
    assert BRAIN_NOTES == BRAIN_DIR / "Notes"
    assert BRAIN_PERSONA == BRAIN_DIR / "Persona.md"
    # archive (was _legacy)
    assert ARCHIVE_DIR == KAIZEN_USER_DIR / "archive"
    pwd_root = project_workflow_dir(Path("/tmp/x"))
    assert pwd_root == Path("/tmp/x/.kaizen/workflow"), pwd_root
    sch = project_schemas_dir(Path("/tmp/x"))
    assert sch == Path("/tmp/x/.kaizen/workflow/schemas"), sch
    print("✓ _paths.py self-test pass (v1.39.0 layout)")
    print(f"  KAIZEN_USER_DIR = {KAIZEN_USER_DIR}")
    print(f"  INDEXES_DIR     = {INDEXES_DIR}")
    print(f"  DATA_DIR        = {DATA_DIR}")
    print(f"  SNAPSHOTS_DIR   = {SNAPSHOTS_DIR}")
    print(f"  TRACE_DIR       = {TRACE_DIR}")
    print(f"  HANDOFF_DB      = {HANDOFF_DB}")
    print(f"  BRAIN_DIR       = {BRAIN_DIR}")
    print(f"  ARCHIVE_DIR     = {ARCHIVE_DIR}")


if __name__ == "__main__":
    _self_test()
