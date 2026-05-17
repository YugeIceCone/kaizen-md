#!/usr/bin/env bash
# kaizen setup — unified entry point for /kaizen:setup.
# Run inside a git repo:  bash ~/.claude/skills/workflow/scripts/setup.sh [subcommand]
#
# Subcommands (first positional):
#   install      per-repo pre-commit gate (default when omitted) — see "Does"
#   uninstall    reverse per-repo activation (delegates to uninstall.sh)
#   cache        per-repo hash-cache CRUD (delegates to cache.py)
# Flags --enable-all / --with-* / --no-* route to enable_all.sh (curated
# project + global stack).
#
# Super-menu (P1, v1.40+): commands/setup.md's empty-args interactive
# flow routes the user through a master action picker (Install / Uninstall
# / Health / Maintenance) → branched sub-flows. The agent assembles flags
# and re-invokes this script with the resolved args; setup.sh itself does
# NOT own the menu — only the install / uninstall / cache surface. The
# menu's "Default" mode pre-fills add-on flags from detect-stack output;
# "Reconfigure" is an idempotent re-run of install with new flags;
# "Maintenance" dispatches to sibling slashes (/kaizen:hygiene,
# /kaizen:update, /kaizen:backup) rather than wrapping them here.
#
# Does (install path):
#   1. mkdir .kaizen/hooks/
#   2. symlink .kaizen/hooks/pre-commit → skill's pre-commit.sh
#   3. git config core.hooksPath .kaizen/hooks  (LOCAL only)
#   4. write a starter .kaizen.toml if absent
#   5. add .kaizen/ to .gitignore if needed
#   6. cache check — surface the per-repo .kaizen/cache/ state

set -eu

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_ROOT="$(cd "$SKILL_DIR/../.." && pwd)"
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─── Subcommand dispatch (v1.37+) ────────────────────────────────────
#
# /kaizen:setup folds the former /kaizen:install + /kaizen:uninstall +
# /kaizen:cache + /kaizen:enable-all into one command. The first
# positional selects the path; no positional (or `install`) falls
# through to the install path below. The --enable-all / --with-* /
# --no-* FLAGS are handled by the delegation block right after.
case "${1:-}" in
  uninstall)
    shift
    exec bash "$_SCRIPT_DIR/uninstall.sh" "$@"
    ;;
  cache)
    shift
    exec python3 "$_SCRIPT_DIR/cache.py" "$@"
    ;;
  install)
    shift  # explicit subcommand — continue into the install path
    ;;
esac

# ─── --enable-all delegation (v1.33+) ────────────────────────────────
#
# When --enable-all (or any --with-* / --no-globals / --no-project flag)
# appears, hand off the whole arg list to enable_all.sh which calls back
# into THIS script (without the flag) for the per-repo install step.

for arg in "$@"; do
  case "$arg" in
    --enable-all|--with-index|--with-browser|--with-daemon|--with-trace-proxy|\
    --no-globals|--no-project|--dry-run|--yes|-y)
      # Strip --enable-all (only meaningful at the setup.sh entry); pass
      # the rest. enable_all.sh re-invokes setup.sh sans these flags.
      _FORWARD=()
      for a in "$@"; do
        [ "$a" = "--enable-all" ] && continue
        _FORWARD+=("$a")
      done
      exec bash "$_SCRIPT_DIR/enable_all.sh" "${_FORWARD[@]}"
      ;;
  esac
done
# v1.30.0+ — install log lives under the unified ~/.claude/.kaizen/ tree
# (was ~/.claude/kaizen-install.log). Source _paths.sh as the SSOT.
_SCRIPT_REAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_SCRIPT_REAL_DIR/_paths.sh"
INSTALL_LOG="$KAIZEN_INSTALL_LOG"
mkdir -p "$(dirname "$INSTALL_LOG")"

# ─── Preflight checks (v1.12.0+) ─────────────────────────────────────
# Validate prereqs BEFORE touching the repo. Required: git + python3.
# Optional warnings: uv (for trace-index + MCP servers), ~/.local/bin on PATH.

preflight_log() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$INSTALL_LOG"
}

preflight_log "=== /kaizen:setup install begin at $(pwd) ==="

REQUIRED=(git python3)
MISSING_REQ=""
for cmd in "${REQUIRED[@]}"; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        MISSING_REQ="$MISSING_REQ $cmd"
    fi
done
if [ -n "$MISSING_REQ" ]; then
    echo "kaizen setup: required commands missing:$MISSING_REQ" >&2
    echo "  install them, then re-run /kaizen:setup" >&2
    preflight_log "FAIL: missing required: $MISSING_REQ"
    exit 1
fi

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "kaizen setup: must run inside a git repo" >&2
    preflight_log "FAIL: not inside git repo (pwd=$(pwd))"
    exit 1
}

# Optional advisories (non-fatal)
ADVISORIES=()
if ! command -v uv >/dev/null 2>&1; then
    ADVISORIES+=("uv not on PATH — trace-index + MCP servers (browser, trace-search) won't auto-install deps")
    ADVISORIES+=("    install: curl -LsSf https://astral.sh/uv/install.sh | sh")
fi
case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) ADVISORIES+=("\$HOME/.local/bin NOT on \$PATH — kaizen-* symlinks won't be findable from your shell")
       ADVISORIES+=("    add to ~/.bashrc: export PATH=\"\$HOME/.local/bin:\$PATH\"") ;;
esac

if [ "${#ADVISORIES[@]}" -gt 0 ]; then
    echo "  ! Advisories (install will continue):" >&2
    for a in "${ADVISORIES[@]}"; do
        echo "    ${a}" >&2
        preflight_log "ADVISORY: $a"
    done
    echo "" >&2
fi

HOOKS_DIR="$REPO_ROOT/.kaizen/hooks"
CONFIG_PATH="$REPO_ROOT/.kaizen.toml"
GITIGNORE="$REPO_ROOT/.gitignore"

# ─── v1.22.0+: auto-migrate legacy paths before wiring ───────────────
# Moves ~/.claude/.kaizen-*, kaizen-inbox, backups/kaizen, kaizen-schemas
# under the unified ~/.claude/.kaizen/ tree, and <repo>/.workflow/ →
# <repo>/.kaizen/workflow/. Idempotent.
MIGRATOR="$SKILL_DIR/scripts/migrate_paths.sh"
if [ -x "$MIGRATOR" ]; then
    echo "  ▸ running path migrator (v1.22.0+ layout)..." >&2
    bash "$MIGRATOR" --project-root "$REPO_ROOT" 2>&1 | sed 's/^/    /' >&2 || true
    echo "" >&2
fi

mkdir -p "$HOOKS_DIR"

# Symlink hooks. Two are wired:
#   pre-commit  — staging-state checks (compile, structural, secrets, etc.)
#   commit-msg  — message-dependent checks (Conventional Commits, plan-file
#                 mention). Lives here because `git commit -m` does NOT
#                 pre-populate .git/COMMIT_EDITMSG for pre-commit to read.
for hook_name in pre-commit commit-msg; do
    HOOK_TARGET="$SKILL_DIR/scripts/${hook_name}.sh"
    HOOK_LINK="$HOOKS_DIR/$hook_name"
    if [ ! -f "$HOOK_TARGET" ]; then
        echo "  ! skill is missing $hook_name.sh — skipping" >&2
        continue
    fi
    if [ -e "$HOOK_LINK" ] && [ ! -L "$HOOK_LINK" ]; then
        echo "  ! existing $HOOK_LINK is not a symlink — backing up to $HOOK_LINK.bak"
        mv "$HOOK_LINK" "$HOOK_LINK.bak"
    fi
    ln -sf "$HOOK_TARGET" "$HOOK_LINK"
    echo "  ✓ linked $HOOK_LINK → $HOOK_TARGET"
done

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
    #
    # Order matters: .kaizen/workflow/ is the post-v1.22 unified layout
    # and the migrate's destination, so check it first. Legacy
    # .workflow/ is the second-best signal (project predates v1.22 or
    # migrate was skipped). Greenfield defaults to .kaizen/workflow/
    # so the install + migrate paths converge on one canonical location.
    if [ -f "$REPO_ROOT/.kaizen/workflow/progress.md" ] || [ -f "$REPO_ROOT/.kaizen/workflow/state.json" ]; then
        DEFAULT_BACKLOG=".kaizen/workflow/backlog.md"
        DEFAULT_ARCH_LOG=".kaizen/workflow/progress.md"
        echo "  ∘ detected .kaizen/workflow/ (unified layout)"
    elif [ -f "$REPO_ROOT/.workflow/state.json" ] || [ -f "$REPO_ROOT/.workflow/progress.md" ]; then
        DEFAULT_BACKLOG=".workflow/backlog.md"
        DEFAULT_ARCH_LOG=".workflow/progress.md"
        echo "  ∘ detected .workflow/ (legacy pre-v1.22 layout; migrate may move it)"
    elif [ -d "$REPO_ROOT/docs/workflow" ]; then
        DEFAULT_BACKLOG="docs/workflow/backlog.md"
        DEFAULT_ARCH_LOG="docs/workflow/progress.md"
    else
        DEFAULT_BACKLOG=".kaizen/workflow/backlog.md"
        DEFAULT_ARCH_LOG=".kaizen/workflow/progress.md"
        echo "  ∘ greenfield → defaulting to .kaizen/workflow/ (unified layout)"
    fi

    cat > "$CONFIG_PATH" <<TOML
#:schema https://raw.githubusercontent.com/YugeIceCone/kaizen-md/main/plugins/kaizen/assets/schemas/kaizen-config.schema.json
# kaizen config — generated $(date +%Y-%m-%d) by skill installer.
# Schema: kaizen-config.schema.json (Taplo / Even Better TOML auto-bind
# via the `#:schema` directive above; offline editors can also use the
# project-root taplo.toml shipped with the plugin).
# See ~/.claude/skills/workflow/SKILL.md PART 4 for the full field reference.

compile_check_cmd = "$DEFAULT_COMPILE"
architecture_log  = "$DEFAULT_ARCH_LOG"
plan_dir          = "plans"
backlog_path      = "$DEFAULT_BACKLOG"
verify_cmd        = ""

allow_deletion_env = "KAIZEN_ALLOW_DELETE"
skip_tdd_check_env = "KAIZEN_SKIP_TDD_CHECK"

# brain_path + project_memory_path omitted — defaults from _paths.py
# take over (~/.claude/.kaizen/brain and the per-cwd project-memory
# slug). Uncomment + set ONLY if you need a custom location for your
# machine (don't commit personal paths).
# brain_path           = "$HOME/.claude/.kaizen/brain"
# project_memory_path  = "$PMEM"
TOML
    echo "  ✓ wrote starter $CONFIG_PATH"
else
    echo "  ∘ $CONFIG_PATH already exists, leaving as-is"
fi

# gitignore policy — scoped to .kaizen/ via a per-dir .gitignore.
#
# Rationale: keeps the root .gitignore project-focused (Rust target,
# OS junk, etc.) and co-locates the kaizen rule with the dir it
# controls. The per-dir file ignores everything inside .kaizen/
# except its own .gitignore and the workflow/ subdir (durable
# artifacts — progress.md, backlog.{json,md}, audits/).
KAIZEN_GITIGNORE="$REPO_ROOT/.kaizen/.gitignore"
if [ ! -f "$KAIZEN_GITIGNORE" ]; then
    mkdir -p "$REPO_ROOT/.kaizen"
    cat > "$KAIZEN_GITIGNORE" <<'KIGNORE'
# kaizen — per-dir gitignore.
#
# Ignores ephemeral kaizen state (cache/, hooks/, trace/, daemon
# socket, etc.). Durable workflow artifacts under workflow/ stay
# tracked: progress.md (architecture log), backlog.{json,md},
# audits/ (durable reports). This keeps the rule local to .kaizen/
# so the repo root's .gitignore stays project-focused.
#
# Runtime artifacts (state.json, deletions.jsonl, snapshot.md) live
# under workflow/ but ARE ephemeral — explicitly re-ignored via the
# trailing rules below so the broad `!workflow/**` whitelist doesn't
# pick them up. They regenerate every workflow run.

*
!.gitignore
!workflow/
!workflow/**

# Re-ignore ephemeral runtime state under workflow/ that the broad
# whitelist above would otherwise pick up.
workflow/state.json
workflow/deletions.jsonl
workflow/snapshot.md
KIGNORE
    echo "  ✓ wrote $KAIZEN_GITIGNORE (ignore ephemeral, track workflow/)"
fi

# Clean up any legacy blanket-ignore from a pre-per-dir install. Old
# installs wrote `.kaizen/` (or the intermediate `.kaizen/*` +
# `!.kaizen/workflow/`) to the repo root .gitignore; both are now
# redundant since .kaizen/.gitignore owns the policy.
[ -f "$GITIGNORE" ] || touch "$GITIGNORE"
LEGACY_PATTERNS=('.kaizen/' '.kaizen/*' '!.kaizen/workflow/')
REMOVED_ANY=0
for pat in "${LEGACY_PATTERNS[@]}"; do
    if grep -qxF "$pat" "$GITIGNORE"; then
        grep -vxF "$pat" "$GITIGNORE" > "${GITIGNORE}.tmp" && mv "${GITIGNORE}.tmp" "$GITIGNORE"
        REMOVED_ANY=1
    fi
done
if [ "$REMOVED_ANY" = "1" ]; then
    echo "  ✓ pruned legacy .kaizen entries from root .gitignore (.kaizen/.gitignore owns the policy)"
fi

echo ""

# Seed backlog.json + backlog.md if absent.
# Resolve backlog_path via config.py (SSOT for .kaizen.toml parsing —
# replaces the per-script grep+sed pattern that lived in install/statusline/
# pre-commit pre-v1.8.x).
BACKLOG_REL=$(cd "$REPO_ROOT" && python3 "$SKILL_DIR/scripts/config.py" backlog_path --default "${DEFAULT_BACKLOG:-backlog.md}" 2>/dev/null)
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

# bin/ symlinks → ~/.local/bin/ (zero-config shell access). Skip with KAIZEN_NO_BIN=1.
USER_BIN="$HOME/.local/bin"
PLUGIN_BIN="$(cd "$SKILL_DIR/../.." && pwd)/bin"
if [ "${KAIZEN_NO_BIN:-0}" = "0" ] && [ -d "$PLUGIN_BIN" ]; then
    if [ ! -d "$USER_BIN" ]; then
        mkdir -p "$USER_BIN" 2>/dev/null || true
    fi
    if [ -d "$USER_BIN" ] && [ -w "$USER_BIN" ]; then
        BIN_COUNT=0
        for src in "$PLUGIN_BIN"/kaizen "$PLUGIN_BIN"/kaizen-*; do
            [ -f "$src" ] || continue
            target="$USER_BIN/$(basename "$src")"
            # Don't clobber a non-symlink the user may have created themselves
            if [ -e "$target" ] && [ ! -L "$target" ]; then
                echo "  ! $target exists and is not a symlink — skipping"
                continue
            fi
            ln -sf "$src" "$target"
            BIN_COUNT=$((BIN_COUNT + 1))
        done
        if [ "$BIN_COUNT" -gt 0 ]; then
            echo "  ✓ symlinked $BIN_COUNT kaizen-* into $USER_BIN/"
            case ":$PATH:" in
                *":$USER_BIN:"*) ;;
                *) echo "  ! $USER_BIN is NOT on \$PATH — add to your shell rc: export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
            esac
        fi
    fi
fi

# ─── Plugin-index seed (fine-grained line editing) ───────────────────
# Indexes the kaizen plugin source so Claude has line-level knowledge
# of it from any repo. loc is stdlib-only + fast; idempotent (skips if
# already seeded). Semantic + the watch daemon come with --enable-all.
if [ "${KAIZEN_PLUGIN_INDEX_DISABLE:-}" != "1" ]; then
    # shellcheck source=_paths.sh
    source "$_SCRIPT_DIR/_paths.sh"
    _PLUGIN_ROOT_IDX="$(kaizen_plugin_index_root)"
    if [ -f "$_PLUGIN_ROOT_IDX/.kaizen/loc.db" ]; then
        echo "  ∘ plugin index already seeded ($_PLUGIN_ROOT_IDX/.kaizen/loc.db)"
    elif [ -d "$_PLUGIN_ROOT_IDX" ]; then
        echo "  ▸ seeding plugin loc index ($_PLUGIN_ROOT_IDX)..."
        python3 "$_SCRIPT_DIR/loc_index.py" index --root "$_PLUGIN_ROOT_IDX" \
            >/dev/null 2>&1 \
            && echo "  ✓ plugin loc index seeded" \
            || echo "  ! plugin loc index seed failed (non-fatal)"
    fi
fi

# ─── Cache check (folded from /kaizen:cache) ─────────────────────────
# /kaizen:setup folds in the per-repo hash-cache surface. Surface its
# state at the end of an install so the user sees it exists + is
# healthy; non-fatal.
echo ""
echo "Cache check (.kaizen/cache/ — manage via /kaizen:setup cache):"
(cd "$REPO_ROOT" && python3 "$_SCRIPT_DIR/cache.py" stats 2>/dev/null | sed 's/^/  /') \
    || echo "  (cache check skipped)"

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
  /kaizen:setup uninstall

Backup before risky ops:
  /kaizen:backup create --label <what>
EOF
echo ""
echo "Uninstall:  git config --unset core.hooksPath && rm -rf .kaizen/"
