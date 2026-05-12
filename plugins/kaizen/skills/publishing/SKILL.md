---
name: publishing
description: Use when publishing a Claude Code plugin/marketplace to GitHub — creating the remote repo, setting up auth, pushing initial state, tagging releases, verifying CI. Triggers on "publish plugin", "release plugin", "gh repo create", "push marketplace", "tag release", "create release", "repo not found", "SSH key mismatch", "ssh-askpass", "fresh upload", "rename plugin repo".
version: 1.0.0
---

# Publishing Claude Code plugins to GitHub

End-to-end recipe for pushing a Claude Code plugin/marketplace to GitHub, with the failure modes encountered in practice and their fixes.

## ⚠ Iron Law

**Use `gh auth setup-git` once on any new machine.** This is the single most common cause of `Repository not found` and `Permission denied (publickey)` errors. It configures `git` to use `gh`'s stored auth token, sidestepping SSH-key-vs-account mismatches entirely.

## Standard sequence (creating a new repo)

```bash
cd <plugin-or-marketplace-root>

# 1. One-time per machine: make git use gh's auth
gh auth setup-git

# 2. Create remote + add origin + push initial state — single call
gh repo create <owner>/<name> --public --source=. --remote=origin --push
```

That's it for the happy path. The rest of this skill is failure-mode triage.

## Failure modes (and their fixes)

### A. `Unable to add remote "origin"` from `gh repo create`

**Cause:** A remote named `origin` already exists locally (e.g. from a prior attempt).

**Fix:**
```bash
git remote remove origin
gh repo create <owner>/<name> --public --source=. --remote=origin --push
```

### B. `Repository not found` on push via SSH

**Cause:** The SSH key in your agent authenticates as a DIFFERENT GitHub user who has no access to the target repo. `gh` itself was authenticated as the right user (which is why `gh repo create` succeeded), but git's SSH path used a different identity.

**Diagnostic:**
```bash
ssh -T git@github.com           # → "Hi <username>!" — should match repo owner
gh auth status                   # → which account is gh using?
```

**Fix (HTTPS via gh credential helper):**
```bash
git remote set-url origin https://github.com/<owner>/<name>.git
gh auth setup-git                # one-time
git push -u --force origin master
```

### C. `fatal: could not read Username for 'https://github.com'`

**Cause:** Non-interactive shell can't prompt for credentials. Either `gh auth setup-git` wasn't run, OR the auth helper isn't found in the current PATH.

**Fix:**
```bash
gh auth setup-git
git config --get credential.helper   # → should show 'gh auth git-credential'
```

### D. `Host key verification failed` on SSH push

**Cause:** `~/.ssh/known_hosts` doesn't have github.com (fresh machine, or non-interactive shell).

**Fix:**
```bash
ssh-keyscan github.com >> ~/.ssh/known_hosts
```

### E. `ssh_askpass: exec(/usr/bin/ssh-askpass): No such file or directory`

**Cause:** Non-interactive shell can't run ssh-askpass. Tools that shell out to `git push` from inside agent contexts hit this regularly.

**Fix:** Switch to HTTPS via `gh auth setup-git` (see B). HTTPS works in non-interactive contexts where SSH agent forwarding doesn't.

## Renaming an already-published plugin

If you renamed the plugin (e.g. `git-workflow` → `kaizen`), and want the GitHub repo to follow:

```bash
# Option 1: Rename in place — keeps stars, watchers, fork-graph
gh repo rename <new-name> --repo <owner>/<old-name>

# Option 2: Delete + recreate (clean history, lose social signals)
gh repo delete <owner>/<old-name> --yes
# Then standard sequence above with the new name
```

## Fresh upload (single-commit history)

When iterating revealed too much rename-cruft / WIP commits and you want a clean published history:

```bash
cd <plugin-root>
REMOTE_URL=$(git remote get-url origin 2>/dev/null)

rm -rf .git
git init -q --initial-branch=master
git config user.email "<email>"
git config user.name "<name>"
git add -A
git commit -q -m "feat: <name> v<version> — <one-line summary>"
[ -n "$REMOTE_URL" ] && git remote add origin "$REMOTE_URL"

git push -u --force origin master
```

**This destroys local history.** Use only on a personal plugin before first publish, OR after explicit user authorization for a "fresh upload" reset.

## Tagging a release

```bash
cd <plugin-root>

# Read version from plugin.json (canonical source)
VERSION=$(python3 -c "import json; print(json.load(open('plugins/<plugin>/.claude-plugin/plugin.json'))['version'])")

# Tag + push tag
git tag -a "v${VERSION}" -m "Release v${VERSION}"
git push origin "v${VERSION}"

# Create a GitHub Release with the CHANGELOG entry as body
NOTES=$(awk "/## \[${VERSION}\]/,/## \[/" plugins/<plugin>/CHANGELOG.md \
        | sed '$d')   # strip the next-section header
gh release create "v${VERSION}" --title "v${VERSION}" --notes "$NOTES"
```

The release shows up on the repo's Releases page; the `v<N.M.K>` tag is referenced by `/plugin install <name>@<marketplace>@v<N.M.K>` for users who want version-pinned installs.

## Pre-publish checklist

Before pushing v1.0.0 (or any major release):

- [ ] `plugin.json` has `name`, `version`, `description`, `author`, `license`, `homepage`, `repository`
- [ ] `marketplace.json` has `name`, `description`, `owner`, `plugins[]`
- [ ] `LICENSE` present at both marketplace root AND plugin root
- [ ] `ATTRIBUTIONS.md` if any content is bundled from other plugins
- [ ] `CHANGELOG.md` has a `[<version>]` section
- [ ] `README.md` has install + quickstart sections at the top
- [ ] CI workflow at `.github/workflows/<name>.yml`
- [ ] `homepage` and `repository` URLs in `plugin.json` are CORRECT (the renaming bug bit me — easy to leave stale)
- [ ] `gh auth status` shows the intended account
- [ ] Local commit history is clean (squash WIP commits with `git rebase -i` before publish)

## CI verification post-push

```bash
gh run list --limit 1            # latest CI run
gh run watch                     # tail it live
gh repo view --web                # opens in browser
```

A failed CI run on the initial commit usually means a path issue from sed-rename (e.g. a hardcoded path didn't get caught). The pipeline test (`scripts/test-pipeline.sh`) catches most of these locally before push.

## Helper script

This skill ships with `scripts/publish.sh` — wraps the standard sequence + failure-mode handling as subcommands. See:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/publish.sh --help
```

Slash command: `/kaizen:publish`.
