#!/usr/bin/env bash
# kaizen installer.
# Run inside a git repo:  bash ~/.claude/skills/kaizen/scripts/install.sh
#
# Does:
#   1. mkdir .kaizen/hooks/
#   2. symlink .kaizen/hooks/pre-commit → skill's pre-commit.sh
#   3. git config core.hooksPath .kaizen/hooks  (LOCAL only)
#   4. write a starter .kaizen.toml if absent
#   5. add .kaizen/ to .gitignore if needed

set -eu

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "kaizen install: must run inside a git repo" >&2
    exit 1
}

HOOKS_DIR="$REPO_ROOT/.kaizen/hooks"
CONFIG_PATH="$REPO_ROOT/.kaizen.toml"
GITIGNORE="$REPO_ROOT/.gitignore"

mkdir -p "$HOOKS_DIR"

# Symlink the hook
HOOK_TARGET="$SKILL_DIR/scripts/pre-commit.sh"
HOOK_LINK="$HOOKS_DIR/pre-commit"
if [ -e "$HOOK_LINK" ] && [ ! -L "$HOOK_LINK" ]; then
    echo "  ! existing $HOOK_LINK is not a symlink — backing up to $HOOK_LINK.bak"
    mv "$HOOK_LINK" "$HOOK_LINK.bak"
fi
ln -sf "$HOOK_TARGET" "$HOOK_LINK"
echo "  ✓ linked $HOOK_LINK → $HOOK_TARGET"

# Local hooksPath
git config core.hooksPath .kaizen/hooks
echo "  ✓ git config core.hooksPath = .kaizen/hooks (local)"

# Starter config
if [ ! -f "$CONFIG_PATH" ]; then
    # Detect stack for a sensible default
    if [ -f "$REPO_ROOT/Cargo.toml" ]; then
        DEFAULT_COMPILE="cargo check --workspace --offline"
    elif [ -f "$REPO_ROOT/tsconfig.json" ]; then
        DEFAULT_COMPILE="npx --no-install tsc --noEmit"
    elif [ -f "$REPO_ROOT/go.mod" ]; then
        DEFAULT_COMPILE="go build ./..."
    elif [ -f "$REPO_ROOT/pyproject.toml" ]; then
        DEFAULT_COMPILE="ruff check ."
    else
        DEFAULT_COMPILE=""
    fi

    # Project memory slug guess
    SLUG=$(echo "$REPO_ROOT" | sed 's|/|-|g' | sed 's|^-||')
    PMEM="$HOME/.claude/projects/$SLUG/memory"

    # Detect canonical workflow-state dir for backlog placement.
    # Strongest signal: state.json from the workflow-routing skill
    # — proves the project actively uses .workflow/ for state.
    # Weaker signal: just the directory existing (project convention).
    if [ -f "$REPO_ROOT/.workflow/state.json" ] || [ -f "$REPO_ROOT/.workflow/progress.md" ]; then
        DEFAULT_BACKLOG=".workflow/backlog.md"
        DEFAULT_ARCH_LOG=".workflow/progress.md"
        echo "  ∘ detected .workflow/ (workflow-routing or project convention)"
    elif [ -d "$REPO_ROOT/docs/workflow" ]; then
        DEFAULT_BACKLOG="docs/workflow/backlog.md"
        DEFAULT_ARCH_LOG="docs/workflow/progress.md"
    else
        DEFAULT_BACKLOG="backlog.md"
        DEFAULT_ARCH_LOG=".workflow/progress.md"
    fi

    cat > "$CONFIG_PATH" <<TOML
# kaizen config — generated $(date +%Y-%m-%d) by skill installer.
# See ~/.claude/skills/kaizen/SKILL.md PART 4 for full schema.

compile_check_cmd = "$DEFAULT_COMPILE"
architecture_log  = "$DEFAULT_ARCH_LOG"
plan_dir          = "plans"
backlog_path      = "$DEFAULT_BACKLOG"
verify_cmd        = ""

allow_deletion_env = "KAIZEN_ALLOW_DELETE"
skip_tdd_check_env = "KAIZEN_SKIP_TDD_CHECK"

brain_path           = "$HOME/.claude/brain"
project_memory_path  = "$PMEM"
TOML
    echo "  ✓ wrote starter $CONFIG_PATH"
else
    echo "  ∘ $CONFIG_PATH already exists, leaving as-is"
fi

# .gitignore — create if missing so the local hooks dir is excluded by default
[ -f "$GITIGNORE" ] || touch "$GITIGNORE"
if ! grep -qxF ".kaizen/" "$GITIGNORE"; then
    echo ".kaizen/" >> "$GITIGNORE"
    echo "  ✓ added .kaizen/ to .gitignore"
fi

echo ""

# Seed backlog.json + backlog.md if absent.
# Resolve backlog_path from the (now-guaranteed-existing) config file
# rather than the DEFAULT_BACKLOG var, which is only set on the
# "config didn't exist" branch above.
BACKLOG_REL=$(grep -E '^backlog_path' "$CONFIG_PATH" 2>/dev/null \
    | head -1 \
    | sed -E 's/^[^=]*=[[:space:]]*"?([^"]*)"?.*$/\1/')
BACKLOG_REL="${BACKLOG_REL:-${DEFAULT_BACKLOG:-backlog.md}}"
BACKLOG_MD="$REPO_ROOT/$BACKLOG_REL"
BACKLOG_JSON="${BACKLOG_MD%.md}.json"
if [ ! -f "$BACKLOG_JSON" ]; then
    mkdir -p "$(dirname "$BACKLOG_JSON")"
    python3 "$SKILL_DIR/scripts/backlog.py" render >/dev/null 2>&1 || true
    if [ -f "$BACKLOG_JSON" ]; then
        echo "  ✓ seeded $BACKLOG_JSON"
        echo "  ✓ rendered $BACKLOG_MD"
    fi
fi

cat <<EOF
${BOLD:-}Install complete.${RESET:-}

Next steps:
  1. /kaizen:status     — confirm everything green
  2. /kaizen:menu       — full command reference
  3. (optional) /kaizen:disable-dupes  — hide loose duplicate skills

Test the gate:
  git commit --allow-empty -m 'test: gate smoke test'

Backlog quick reference:
  /kaizen:backlog list
  /kaizen:backlog add --title "..." --probe "..." --verify "..."

Diagnostic:
  /kaizen:health

Uninstall (per-repo only; keeps backlog + backups):
  /kaizen:uninstall

Backup before risky ops:
  /kaizen:backup create --label <what>
EOF
echo ""
echo "Uninstall:  git config --unset core.hooksPath && rm -rf .kaizen/"
