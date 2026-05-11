---
name: publish
description: Publish this plugin/marketplace to GitHub. Subcommands cover the full lifecycle — gh auth setup, remote create, push, release tagging, fresh-history reset, and diagnostic. Handles the failure modes (SSH user mismatch, stale origin, ssh-askpass missing) documented in the `publishing` skill.
---

# kaizen publish

GitHub publishing helper. Wraps `gh` + `git` for the standard flow + the failure modes.

## Argument router

Parse `$ARGUMENTS`:

- **No args** or `status` → repo + branch + auth + origin + version overview:
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/publish.sh status`
- `init` → run `gh auth setup-git` + sanity-check origin (idempotent):
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/publish.sh init`
- `create [owner/name]` → create the remote repo + add origin + push initial state (owner/name resolved from plugin.json if omitted):
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/publish.sh create $ARGUMENTS`
- `push [--force]` → push current branch to origin (or `--force` for clean-history overwrite):
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/publish.sh push $ARGUMENTS`
- `release [--version V]` → tag + push tag + create GitHub release (version + notes auto-read from plugin.json + CHANGELOG.md):
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/publish.sh release $ARGUMENTS`
- `diagnose` → SSH-T + gh auth + remotes + credential helper + ~/.ssh/config + known_hosts; everything you need when things break:
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/publish.sh diagnose`
- `reset` → DESTRUCTIVE: nuke `.git/`, single-commit reinit (preserves origin URL). Requires `--yes`:
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/publish.sh reset $ARGUMENTS`

For full help:
!`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/publish.sh --help`

## Typical flows

### First publish

```
/kaizen:publish init        # set up gh credential helper
/kaizen:publish create      # creates github.com/<owner>/<name>, pushes initial commit
```

After this, CI fires automatically via `.github/workflows/test.yml`.

### Subsequent updates

```
git commit -m "feat(scope): change description"
/kaizen:publish push
```

### Version release

```
# 1. Bump version in plugin.json
# 2. Add [<new-version>] section to CHANGELOG.md
# 3. Commit + push (normal flow)
# 4. Then:
/kaizen:publish release   # auto-reads version, tags, creates GH release with CHANGELOG notes
```

### Fresh-history reset (rare)

When WIP commits / mass-renames / experiments should not land upstream:

```
/kaizen:publish reset --yes        # nuke .git, single 'initial release' commit
/kaizen:publish push --force        # overwrite remote
```

## What this skill bundles

Loading `/kaizen:publish` activates the `publishing` skill, which documents:

- The standard `gh repo create` sequence
- 5 common failure modes (SSH user mismatch, stale origin, ssh-askpass missing, host-key verification, HTTPS no-credentials)
- Rename-in-place vs. delete-recreate trade-offs
- Pre-publish checklist
- CI verification

See `skills/publishing/SKILL.md` for full content.

## Requirements

- `gh` CLI authenticated (`gh auth status` shows your account)
- `git` configured with `user.email` + `user.name`
- `python3` (already required by the plugin)

If `gh` is missing: https://cli.github.com (one-line install on most systems).

## Safety

- `reset` requires explicit `--yes` flag. Otherwise it prints the destructive plan and exits 2.
- `push --force` is opt-in. Default `push` is non-forced.
- `init` is idempotent — safe to re-run.
- All subcommands except `reset` are non-destructive on the local working tree.
