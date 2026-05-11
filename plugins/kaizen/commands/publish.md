---
name: publish
description: Publish this plugin/marketplace to GitHub. Subcommands cover the full lifecycle — gh auth setup, remote create, push, release tagging, fresh-history reset, and diagnostic. Handles the failure modes (SSH user mismatch, stale origin, ssh-askpass missing) documented in the `publishing` skill.
---

# kaizen publish

GitHub publishing helper. Wraps `gh` + `git` for the standard flow + the failure modes.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/publish.sh ${ARGUMENTS:-status}`

## Subcommands

- (no args) or `status` → repo + branch + auth + origin + version + remote sync overview
- `diagnose` → SSH-T + gh auth + remotes + credential helper + ssh config + known_hosts
- `init` → `gh auth setup-git` + remote sanity check (idempotent)
- `create [owner/name]` → `gh repo create --source=. --remote=origin --push` (auto-reads owner/name from plugin.json)
- `push [--force]` → push current branch to origin (`--force` for clean-history overwrite)
- `release [--version V]` → tag + push tag + GitHub release (version + notes auto-read from plugin.json + CHANGELOG.md)
- `reset --yes` → DESTRUCTIVE: nuke `.git/`, single-commit reinit (preserves origin URL; requires `--yes`)

## Typical flows

### First publish

```
/kaizen:publish init        # set up gh credential helper
/kaizen:publish create      # creates github.com/<owner>/<name>, pushes initial commit
```

### Subsequent updates

```
git commit -m "feat(scope): change"
/kaizen:publish push
```

### Version release

```
# 1. Bump version in plugin.json
# 2. Add [<new-version>] section to CHANGELOG.md
# 3. Commit + push
# 4. Then:
/kaizen:publish release
```

### Fresh-history reset (rare, requires --yes)

```
/kaizen:publish reset --yes
/kaizen:publish push --force
```

## Requirements

- `gh` CLI authenticated (`gh auth status`)
- `git` configured with `user.email` + `user.name`
- `python3`

If `gh` is missing: https://cli.github.com
