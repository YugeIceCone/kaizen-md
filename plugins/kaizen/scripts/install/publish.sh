#!/usr/bin/env bash
# kaizen publish — GitHub repo publish + release helper.
#
# Wraps `gh` + `git` for the standard publish flow, with handling for the
# failure modes documented in the `publishing` skill (SSH user mismatch,
# stale origin, ssh-askpass missing, force-push for clean history, etc.).
#
# Subcommands:
#   status                        Show auth, remote, branch, sync, CI state
#   diagnose                      Full troubleshooting output (ssh -T, gh auth, remotes, hooks)
#   init                          gh auth setup-git + reset origin if stale
#   create [owner/name]           Create remote repo via gh + push (resolves owner/name from plugin.json by default)
#   push [--force]                git push -u origin <current-branch>, with --force support
#   release [--version V]         Tag + push tag + create gh release (reads version from plugin.json)
#   reset                         DESTRUCTIVE: nuke .git, single-commit re-init (auth user confirmation)
#
# Default plugin manifest path: <repo-root>/plugins/<plugin-name>/.claude-plugin/plugin.json
# Auto-detects when the script is run from inside a plugin/marketplace tree.

set -uo pipefail

# ─── Sibling lib ─────────────────────────────────────────────────────
_SCRIPT_REAL_DIR="$(cd "$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"
_LIBSH="$_SCRIPT_REAL_DIR/../../scripts/git-hooks/lib.sh"  # DOMAIN-shells Wave C depth -1  # moved DOMAIN-shells Wave A
[ -f "$_LIBSH" ] && . "$_LIBSH" || {
    realpath_f() { python3 -c "import os, sys; print(os.path.realpath(sys.argv[1]))" "$1"; }
    repo_root()  { git rev-parse --show-toplevel 2>/dev/null || true; }
    color_init() { if [ -t 2 ]; then BOLD=$'\e[1m'; DIM=$'\e[2m'; RED=$'\e[31m'; YELLOW=$'\e[33m'; GREEN=$'\e[32m'; RESET=$'\e[0m'; else BOLD="" DIM="" RED="" YELLOW="" GREEN="" RESET=""; fi; }
    log_pass() { color_init; printf '%s✓%s  %s\n' "$GREEN" "$RESET" "$1" >&2; }
    log_fail() { color_init; printf '%s✗%s  %s\n' "$RED"   "$RESET" "$1" >&2; }
    log_warn() { color_init; printf '%s!%s  %s\n' "$YELLOW" "$RESET" "$1" >&2; }
    log_skip() { color_init; printf '%s∘%s  %s\n' "$DIM"    "$RESET" "$1" >&2; }
}
color_init

# ─── Manifest discovery ──────────────────────────────────────────────
# Find the plugin.json (canonical version + name source).
find_plugin_manifest() {
    local root="${1:-$(repo_root)}"
    [ -z "$root" ] && return 1
    # Look in standard locations
    for p in \
        "$root/plugins"/*/.claude-plugin/plugin.json \
        "$root/.claude-plugin/plugin.json"; do
        [ -f "$p" ] && { echo "$p"; return 0; }
    done
    return 1
}

manifest_field() {
    local manifest="$1" field="$2"
    python3 -c "import json; print(json.load(open('$manifest')).get('$field', ''))" 2>/dev/null
}

resolve_owner_name() {
    # Try repository URL first (most authoritative)
    local manifest
    manifest=$(find_plugin_manifest) || return 1
    local repo
    repo=$(manifest_field "$manifest" repository)
    if [[ "$repo" =~ github.com[/:]+([^/]+)/([^/.]+) ]]; then
        echo "${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
        return 0
    fi
    return 1
}

# ─── Subcommands ─────────────────────────────────────────────────────

cmd_status() {
    local root; root=$(repo_root) || { log_fail "not in a git repo"; return 2; }
    cd "$root"
    echo "${BOLD}Repo:${RESET}     $root"
    if BR=$(git branch --show-current 2>/dev/null) && [ -n "$BR" ]; then
        echo "${BOLD}Branch:${RESET}   $BR"
    else
        echo "${BOLD}Branch:${RESET}   ${DIM}(detached)${RESET}"
    fi
    local origin
    origin=$(git remote get-url origin 2>/dev/null) && echo "${BOLD}Origin:${RESET}   $origin" \
        || echo "${BOLD}Origin:${RESET}   ${DIM}(not set)${RESET}"
    echo ""

    if command -v gh >/dev/null 2>&1; then
        echo "${BOLD}gh auth:${RESET}"
        gh auth status 2>&1 | sed 's/^/  /' | head -10
    else
        log_warn "gh CLI not installed — install: https://cli.github.com"
    fi
    echo ""

    if [ -n "${origin:-}" ]; then
        echo "${BOLD}Remote sync (5s timeout):${RESET}"
        timeout 5 git ls-remote --heads origin 2>&1 | head -3 | sed 's/^/  /'
    fi
    echo ""

    local manifest
    if manifest=$(find_plugin_manifest); then
        local version; version=$(manifest_field "$manifest" version)
        echo "${BOLD}Plugin:${RESET}   $(manifest_field "$manifest" name) v${version}"
    fi
}

cmd_diagnose() {
    color_init
    echo "${BOLD}=== ssh -T git@github.com ===${RESET}"
    timeout 5 ssh -T git@github.com 2>&1 | head -5
    echo ""
    echo "${BOLD}=== gh auth status ===${RESET}"
    command -v gh >/dev/null && gh auth status 2>&1 || echo "gh not installed"
    echo ""
    echo "${BOLD}=== git remotes ===${RESET}"
    git remote -v
    echo ""
    echo "${BOLD}=== git config credential.helper ===${RESET}"
    git config --get-all credential.helper 2>&1 | sed 's/^/  /'
    echo ""
    echo "${BOLD}=== insteadOf URL rewrites ===${RESET}"
    git config --get-regexp '^url\.' 2>&1 | sed 's/^/  /'
    echo ""
    echo "${BOLD}=== ~/.ssh/config (first 30 lines) ===${RESET}"
    head -30 ~/.ssh/config 2>/dev/null || echo "  (no ~/.ssh/config)"
    echo ""
    echo "${BOLD}=== github.com in known_hosts? ===${RESET}"
    grep -l github.com ~/.ssh/known_hosts 2>/dev/null && echo "  yes" || echo "  no — run: ssh-keyscan github.com >> ~/.ssh/known_hosts"
}

cmd_init() {
    if ! command -v gh >/dev/null 2>&1; then
        log_fail "gh CLI not installed. See https://cli.github.com"
        return 1
    fi
    if ! gh auth status >/dev/null 2>&1; then
        log_warn "gh not authenticated — run: gh auth login"
        return 1
    fi
    gh auth setup-git
    log_pass "git configured to use gh's credential helper"

    local root; root=$(repo_root) || { log_fail "not in a git repo"; return 2; }
    cd "$root"
    local origin
    origin=$(git remote get-url origin 2>/dev/null || true)
    if [ -n "$origin" ]; then
        log_pass "origin already set: $origin"
        log_skip "init: nothing else to do (use 'create' or 'push' next)"
    else
        log_skip "no origin set — next: $0 create"
    fi
}

cmd_create() {
    local target="${1:-}"
    [ -z "$target" ] && target=$(resolve_owner_name) || true
    if [ -z "$target" ]; then
        log_fail "create: pass <owner/name> explicitly, OR ensure plugin.json's 'repository' field is set"
        return 2
    fi
    if ! command -v gh >/dev/null 2>&1; then
        log_fail "gh CLI not installed"
        return 1
    fi

    local root; root=$(repo_root); cd "$root"

    # Drop stale origin if any
    if git remote get-url origin >/dev/null 2>&1; then
        log_warn "origin already set — removing before recreate"
        git remote remove origin
    fi

    log_pass "creating + pushing: $target"
    gh repo create "$target" --public --source=. --remote=origin --push
}

cmd_push() {
    local force=0
    for arg in "$@"; do
        case "$arg" in --force|-f) force=1 ;; esac
    done
    local root; root=$(repo_root) || { log_fail "not in a git repo"; return 2; }
    cd "$root"
    local branch; branch=$(git branch --show-current)
    if [ -z "$branch" ]; then
        log_fail "detached HEAD — checkout a branch first"
        return 2
    fi
    if ! git remote get-url origin >/dev/null 2>&1; then
        log_fail "no origin set — run: $0 create  OR  git remote add origin <url>"
        return 2
    fi

    if [ "$force" = "1" ]; then
        log_warn "force push: $branch → origin/$branch"
        git push -u --force origin "$branch"
    else
        git push -u origin "$branch"
    fi
}

cmd_release() {
    local version=""
    while [ $# -gt 0 ]; do
        case "$1" in --version) version="$2"; shift 2 ;; *) shift ;; esac
    done
    local root; root=$(repo_root); cd "$root"
    local manifest; manifest=$(find_plugin_manifest) || { log_fail "no plugin.json found"; return 2; }
    [ -z "$version" ] && version=$(manifest_field "$manifest" version)
    [ -z "$version" ] && { log_fail "couldn't determine version"; return 2; }

    log_pass "release: v${version}"

    # Tag (annotated)
    if git rev-parse "v${version}" >/dev/null 2>&1; then
        log_warn "tag v${version} already exists — skipping tag creation"
    else
        git tag -a "v${version}" -m "Release v${version}"
        git push origin "v${version}"
        log_pass "pushed tag v${version}"
    fi

    # Extract CHANGELOG section for this version
    local changelog="${manifest%/.claude-plugin/plugin.json}/CHANGELOG.md"
    local notes=""
    if [ -f "$changelog" ]; then
        notes=$(awk "/^## \[${version}\]/{flag=1; next} /^## \[/{flag=0} flag" "$changelog")
    fi
    if [ -z "$notes" ]; then
        notes="Release v${version}"
    fi

    # gh release create
    if command -v gh >/dev/null 2>&1; then
        if gh release view "v${version}" >/dev/null 2>&1; then
            log_warn "GitHub release v${version} already exists — skipping"
        else
            gh release create "v${version}" --title "v${version}" --notes "$notes"
            log_pass "GitHub release v${version} created"
        fi
    else
        log_skip "gh not installed — tag pushed; create release manually on GitHub"
    fi
}

cmd_reset() {
    local root; root=$(repo_root) || { log_fail "not in a git repo"; return 2; }
    cd "$root"
    if [ "${1:-}" != "--yes" ]; then
        cat <<EOF >&2
${BOLD}${YELLOW}DESTRUCTIVE${RESET} — this will:

  1. rm -rf .git/  (delete local history entirely)
  2. git init      (fresh repo)
  3. git add -A    (stage everything currently on disk)
  4. git commit    (single 'feat: <name> v<version> — initial release')
  5. re-add origin remote if one was set

You will then need to: git push -u --force origin master

This is appropriate for:
  - First-time publishing where local WIP history should not land upstream
  - After a major rename (cleanup of refactor commits)
  - User has explicitly authorized via 'fresh upload' or equivalent

Re-run with --yes to confirm.
EOF
        return 2
    fi

    local manifest; manifest=$(find_plugin_manifest)
    local plugin_name="<plugin>"
    local version="0.0.1"
    if [ -n "$manifest" ]; then
        plugin_name=$(manifest_field "$manifest" name)
        version=$(manifest_field "$manifest" version)
    fi

    local origin
    origin=$(git remote get-url origin 2>/dev/null || true)
    local email; email=$(git config user.email 2>/dev/null || echo "you@example.com")
    local user;  user=$(git config user.name 2>/dev/null || echo "you")

    rm -rf .git
    git init -q --initial-branch=master
    git config user.email "$email"
    git config user.name "$user"
    git add -A
    git commit -q -m "feat: ${plugin_name} v${version} — initial release"
    [ -n "$origin" ] && git remote add origin "$origin"

    log_pass "reset complete: single commit, $(git ls-files | wc -l) files"
    echo "${DIM}Next:  $0 push --force${RESET}" >&2
}

# ─── Dispatch ─────────────────────────────────────────────────────────

cmd="${1:-status}"
shift || true

case "$cmd" in
    status)    cmd_status ;;
    diagnose)  cmd_diagnose ;;
    init)      cmd_init ;;
    create)    cmd_create "$@" ;;
    push)      cmd_push "$@" ;;
    release)   cmd_release "$@" ;;
    reset)     cmd_reset "$@" ;;
    -h|--help)
        sed -n '2,/^set -uo/p' "$0" | sed 's/^# \?//'
        ;;
    *)
        echo "publish: unknown subcommand '$cmd'" >&2
        echo "       try: status | diagnose | init | create | push | release | reset" >&2
        exit 2 ;;
esac
