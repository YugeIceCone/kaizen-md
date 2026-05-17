#!/usr/bin/env bash
# Shared path constants for kaizen shell scripts (v1.22.0 unification).
#
# Source this file at the top of any kaizen .sh script:
#
#     _SCRIPT_REAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#     source "$_SCRIPT_REAL_DIR/_paths.sh"
#
# Then use $KAIZEN_TRACE_DIR / $KAIZEN_KNOWLEDGE_DB / etc. instead of
# inlining ~/.claude/.kaizen-* paths.
#
# Mirrors the contract in _paths.py (Python SSOT). Keep both in sync.

# ─── User-global root ────────────────────────────────────────────────

KAIZEN_USER_DIR="${KAIZEN_DIR:-$HOME/.claude/.kaizen}"

# ─── v1.39.0 umbrella dirs ───────────────────────────────────────────

KAIZEN_INDEXES_DIR="${KAIZEN_INDEXES_DIR:-$KAIZEN_USER_DIR/indexes}"
KAIZEN_DATA_DIR="${KAIZEN_DATA_DIR:-$KAIZEN_USER_DIR/data}"
KAIZEN_SNAPSHOTS_DIR="${KAIZEN_SNAPSHOTS_DIR:-$KAIZEN_USER_DIR/snapshots}"
KAIZEN_ARCHIVE_DIR="${KAIZEN_ARCHIVE_DIR:-$KAIZEN_USER_DIR/archive}"

# ─── Indexes (search-style state) ────────────────────────────────────

KAIZEN_TRACE_DIR="${KAIZEN_TRACE_DIR:-$KAIZEN_INDEXES_DIR/trace}"
KAIZEN_TRACE_FILE="$KAIZEN_TRACE_DIR/events.jsonl"
KAIZEN_TRACE_DB="$KAIZEN_TRACE_DIR/index.db"

KAIZEN_KNOWLEDGE_DIR="${KAIZEN_KNOWLEDGE_DIR:-$KAIZEN_INDEXES_DIR/knowledge}"
KAIZEN_KNOWLEDGE_DB="$KAIZEN_KNOWLEDGE_DIR/index.db"

KAIZEN_SCRAPE_DIR="${KAIZEN_SCRAPE_DIR:-$KAIZEN_INDEXES_DIR/scrape}"
KAIZEN_SCRAPE_DB="$KAIZEN_SCRAPE_DIR/index.db"

KAIZEN_CLAUDE_DOCS_DIR="${KAIZEN_CLAUDE_DOCS_DIR:-$KAIZEN_INDEXES_DIR/claude-docs}"
KAIZEN_CLAUDE_DOCS_DB="$KAIZEN_CLAUDE_DOCS_DIR/index.db"
KAIZEN_CLAUDE_DOCS_SRC="${KAIZEN_CLAUDE_DOCS_SRC:-$KAIZEN_CLAUDE_DOCS_DIR/src}"

# ─── Data (operational state — singletons + daemon) ──────────────────

KAIZEN_DAEMON_DIR="${KAIZEN_DAEMON_DIR:-$KAIZEN_DATA_DIR/daemon}"
KAIZEN_DAEMON_STATE="$KAIZEN_DAEMON_DIR/state.json"

KAIZEN_HANDOFF_DB="${KAIZEN_HANDOFF_DB:-$KAIZEN_DATA_DIR/handoff.db}"
KAIZEN_MANIFEST_JSON="${KAIZEN_MANIFEST_JSON:-$KAIZEN_DATA_DIR/manifest.json}"
KAIZEN_MANIFEST_LOCK="${KAIZEN_MANIFEST_LOCK:-$KAIZEN_DATA_DIR/manifest.lock}"
KAIZEN_PROFILE_ENV="${KAIZEN_PROFILE_ENV:-$KAIZEN_DATA_DIR/profile.env}"

# ─── Snapshots (hoisted from observe/snapshots/) ─────────────────────

# v1.39.0+ — snapshots are now top-level. Legacy alias KAIZEN_OBSERVE_DIR
# kept for shell scripts that haven't been updated yet.
KAIZEN_OBSERVE_SNAPSHOTS="$KAIZEN_SNAPSHOTS_DIR"
KAIZEN_OBSERVE_DIR="$KAIZEN_SNAPSHOTS_DIR"

# ─── Singletons at user-global root ──────────────────────────────────

KAIZEN_INBOX_DIR="${KAIZEN_INBOX_DIR:-$KAIZEN_USER_DIR/inbox}"
KAIZEN_BACKUP_DIR="${KAIZEN_BACKUP_DIR:-$KAIZEN_USER_DIR/backups}"
KAIZEN_USER_SCHEMAS="${KAIZEN_USER_SCHEMAS:-$KAIZEN_USER_DIR/schemas}"

# v1.30.0+ — install log (kaizen install/setup events).
KAIZEN_INSTALL_LOG="${KAIZEN_INSTALL_LOG:-$KAIZEN_USER_DIR/install.log}"

# v1.38.0+ — Second Brain (PARA + Persona + Notes + index DB).
# Owned by kaizen post-Remember-retirement. Legacy REMEMBER_BRAIN_PATH
# is NOT consulted — only KAIZEN_BRAIN_DIR resolves the location.
KAIZEN_BRAIN_DIR="${KAIZEN_BRAIN_DIR:-$KAIZEN_USER_DIR/brain}"
KAIZEN_BRAIN_DB="$KAIZEN_BRAIN_DIR/brain.db"
KAIZEN_BRAIN_NOTES="$KAIZEN_BRAIN_DIR/Notes"
KAIZEN_BRAIN_PERSONA="$KAIZEN_BRAIN_DIR/Persona.md"

# v1.39.0+ — archive (was _legacy in v1.30–1.38).
KAIZEN_LEGACY_ARCHIVE_DIR="$KAIZEN_ARCHIVE_DIR"

# ─── Project-side (relative to the project root passed in or $PWD) ───

# kaizen_project_workflow_dir [<project-root>]   →   prints <root>/.kaizen/workflow
kaizen_project_workflow_dir() {
    local root="${1:-${CLAUDE_PROJECT_DIR:-$PWD}}"
    if [ -n "${WORKFLOW_STATE_DIR:-}" ]; then
        echo "$WORKFLOW_STATE_DIR"
    else
        echo "$root/.kaizen/workflow"
    fi
}

# kaizen_resolve_workflow_dir [<project-root>]   →   prints the ACTIVE workflow
# dir for a repo that may be mid-migration. Single source of truth for the
# v1.22.0 canonical-with-legacy-fallback rule:
#   1. WORKFLOW_STATE_DIR env override wins
#   2. <root>/.kaizen/workflow/  exists  → that
#   3. <root>/.workflow/         exists  → that  (legacy, will be retired)
#   4. otherwise default to canonical (greenfield)
# Call this instead of inlining the fallback ladder. When the legacy
# branch is removed, only this function needs to change.
kaizen_resolve_workflow_dir() {
    local root="${1:-${CLAUDE_PROJECT_DIR:-$PWD}}"
    if [ -n "${WORKFLOW_STATE_DIR:-}" ]; then
        echo "$WORKFLOW_STATE_DIR"
    elif [ -d "$root/.kaizen/workflow" ]; then
        echo "$root/.kaizen/workflow"
    elif [ -d "$root/.workflow" ]; then
        echo "$root/.workflow"
    else
        echo "$root/.kaizen/workflow"
    fi
}

# kaizen_project_schemas_dir [<project-root>]   →   prints <root>/.kaizen/workflow/schemas
kaizen_project_schemas_dir() {
    local root="${1:-${CLAUDE_PROJECT_DIR:-$PWD}}"
    echo "$(kaizen_project_workflow_dir "$root")/schemas"
}

# kaizen_project_kaizen_dir [<project-root>]   →   prints <root>/.kaizen
kaizen_project_kaizen_dir() {
    local root="${1:-${CLAUDE_PROJECT_DIR:-$PWD}}"
    echo "$root/.kaizen"
}

# kaizen_plugin_index_root   →   prints the kaizen-md repo root to index.
# KAIZEN_PLUGIN_INDEX_ROOT wins; else realpath of KAIZEN_MARKETPLACE
# (or the default symlink). Mirrors _paths.py::plugin_index_root().
kaizen_plugin_index_root() {
    local base
    if [ -n "${KAIZEN_PLUGIN_INDEX_ROOT:-}" ]; then
        base="$KAIZEN_PLUGIN_INDEX_ROOT"
    else
        base="${KAIZEN_MARKETPLACE:-$HOME/.claude/local-marketplaces/kaizen-md}"
    fi
    # realpath, with a python fallback for portability
    realpath "$base" 2>/dev/null \
        || python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$base"
}

# ─── Legacy paths (for the migrator) ─────────────────────────────────

KAIZEN_LEGACY_TRACE="$HOME/.claude/.kaizen-trace"
KAIZEN_LEGACY_KNOWLEDGE="$HOME/.claude/.kaizen-knowledge"
KAIZEN_LEGACY_DAEMON="$HOME/.claude/.kaizen-daemon"
KAIZEN_LEGACY_INBOX="$HOME/.claude/kaizen-inbox"
KAIZEN_LEGACY_BACKUPS="$HOME/.claude/backups/kaizen"
KAIZEN_LEGACY_SCHEMAS="$HOME/.claude/kaizen-schemas"
KAIZEN_LEGACY_OBSERVE="$HOME/.claude/.kaizen-observe"        # v1.30.0+
KAIZEN_LEGACY_INSTALL_LOG="$HOME/.claude/kaizen-install.log" # v1.30.0+ (file, not dir)
KAIZEN_LEGACY_BRAIN="$HOME/.claude/brain"                    # v1.38.0+ (Remember-owned location)
KAIZEN_LEGACY_PROJECT_WORKFLOW=".workflow"   # appended to project root
