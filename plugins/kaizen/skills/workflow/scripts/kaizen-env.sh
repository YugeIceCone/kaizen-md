#!/usr/bin/env bash
# kaizen-env — export shell vars + aliases for interactive use.
#
# Source this from your ~/.bashrc / ~/.zshrc to make kaizen scripts
# callable from any shell:
#
#   source /home/<you>/.claude/local-marketplaces/kaizen-md/plugins/kaizen/skills/workflow/scripts/kaizen-env.sh
#
# Or have /kaizen:env install do it for you (writes one line to your rc).
#
# Sets:
#   KAIZEN_ROOT       — plugin root (the dir with .claude-plugin/)
#   KAIZEN_SCRIPTS    — $KAIZEN_ROOT/scripts/  (post-v1.40 layout)
#   PATH              — prepends $KAIZEN_ROOT/bin so wrappers are callable
#
# Aliases (interactive shells only):
#   kaizen-flow       consolidated flow dispatcher (demo|docs|index|search)
#   kaizen-docs       generic workspace docs generator
#   kaizen-backlog    backlog CLI
#   kaizen-cache      cache inspect/clear
#   kaizen-context    context-window state
#   kaizen-inbox      message inbox
#   kaizen-rules      brain-sourced rule lookup

# Resolve THIS script's location → derive plugin root + scripts dir
_kz_resolve() {
    # Prefer realpath for symlink resolution; fall back to python3 if absent
    local src="${BASH_SOURCE[0]:-$0}"
    if command -v realpath >/dev/null 2>&1; then
        realpath "$src"
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c "import os, sys; print(os.path.realpath(sys.argv[1]))" "$src"
    else
        # Best-effort: assume no symlink
        cd "$(dirname "$src")" && pwd && cd - >/dev/null || true
    fi
}

_KZ_SCRIPT_PATH=$(_kz_resolve)
# This file lives at skills/workflow/scripts/kaizen-env.sh until Phase 6
# moves it to scripts/util/. Plugin root is 3 levels above its dir.
KAIZEN_ROOT="$(cd "$(dirname "$_KZ_SCRIPT_PATH")/../../.." && pwd)"
KAIZEN_SCRIPTS="$KAIZEN_ROOT/scripts"

export KAIZEN_ROOT
export KAIZEN_SCRIPTS

# Prepend bin/ to PATH so kaizen-* wrappers are directly callable.
case ":$PATH:" in
    *":$KAIZEN_ROOT/bin:"*) ;;  # already there
    *) PATH="$KAIZEN_ROOT/bin:$PATH" ;;
esac
export PATH

# Interactive aliases — guarded so non-interactive shells stay quiet.
# Aliases point at canonical scripts/<cluster>/ post-v1.40.
if [ -n "${PS1:-}" ] || [ -n "${ZSH_VERSION:-}" ]; then
    alias kaizen-flow='python3 "$KAIZEN_SCRIPTS/workflow/flow_cli.py"'
    alias kaizen-docs='python3 "$KAIZEN_SCRIPTS/index/docs_gen.py"'
    alias kaizen-backlog='python3 "$KAIZEN_SCRIPTS/backlog/backlog.py"'
    alias kaizen-cache='python3 "$KAIZEN_SCRIPTS/util/cache.py"'
    alias kaizen-context='python3 "$KAIZEN_SCRIPTS/util/context.py"'
    alias kaizen-inbox='python3 "$KAIZEN_SCRIPTS/intent/inbox.py"'
    alias kaizen-rules='python3 "$KAIZEN_SCRIPTS/rules/rules.py"'
fi

unset _KZ_SCRIPT_PATH
unset -f _kz_resolve
