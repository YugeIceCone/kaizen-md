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

# ─── User-global subdirs ─────────────────────────────────────────────

KAIZEN_TRACE_DIR="${KAIZEN_TRACE_DIR:-$KAIZEN_USER_DIR/trace}"
KAIZEN_TRACE_FILE="$KAIZEN_TRACE_DIR/events.jsonl"
KAIZEN_TRACE_DB="$KAIZEN_TRACE_DIR/index.db"

KAIZEN_KNOWLEDGE_DIR="${KAIZEN_KNOWLEDGE_DIR:-$KAIZEN_USER_DIR/knowledge}"
KAIZEN_KNOWLEDGE_DB="$KAIZEN_KNOWLEDGE_DIR/index.db"

KAIZEN_DAEMON_DIR="${KAIZEN_DAEMON_DIR:-$KAIZEN_USER_DIR/daemon}"
KAIZEN_DAEMON_STATE="$KAIZEN_DAEMON_DIR/state.json"

KAIZEN_INBOX_DIR="${KAIZEN_INBOX_DIR:-$KAIZEN_USER_DIR/inbox}"

KAIZEN_BACKUP_DIR="${KAIZEN_BACKUP_DIR:-$KAIZEN_USER_DIR/backups}"

KAIZEN_USER_SCHEMAS="${KAIZEN_USER_SCHEMAS:-$KAIZEN_USER_DIR/schemas}"

KAIZEN_SCRAPE_DIR="${KAIZEN_SCRAPE_DIR:-$KAIZEN_USER_DIR/scrape}"
KAIZEN_SCRAPE_DB="$KAIZEN_SCRAPE_DIR/index.db"

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

# ─── Legacy paths (for the migrator) ─────────────────────────────────

KAIZEN_LEGACY_TRACE="$HOME/.claude/.kaizen-trace"
KAIZEN_LEGACY_KNOWLEDGE="$HOME/.claude/.kaizen-knowledge"
KAIZEN_LEGACY_DAEMON="$HOME/.claude/.kaizen-daemon"
KAIZEN_LEGACY_INBOX="$HOME/.claude/kaizen-inbox"
KAIZEN_LEGACY_BACKUPS="$HOME/.claude/backups/kaizen"
KAIZEN_LEGACY_SCHEMAS="$HOME/.claude/kaizen-schemas"
KAIZEN_LEGACY_PROJECT_WORKFLOW=".workflow"   # appended to project root
