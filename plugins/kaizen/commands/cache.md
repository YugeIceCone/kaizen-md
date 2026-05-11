---
name: cache
description: Inspect, clear, or query the kaizen per-repo cache at `<repo>/.kaizen/cache/`. Used by the compile-barrier check to skip redundant `cargo check` / `tsc --noEmit` / etc. runs when staged content is unchanged, and by agents (kaizen-reviewer) to memoize verdicts by diff sha.
---

# kaizen cache

Hash-keyed JSON cache, per-repo, gitignored under `.kaizen/`. No TTL — entries invalidate when their input hashes change.

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/cache.py ${ARGUMENTS:-stats}`

## Subcommands

- (no args) or `stats` → count + bytes + dir
- `key <part1> [part2] ...` → derive a key from parts (SHA1, 16-hex)
- `get <key>` → print cached value as JSON (exit 1 on miss)
- `put <key> <json>` → write a value
- `delete <key>` → remove one entry
- `clear` → remove ALL entries (no confirmation; cache will rebuild)

## What's cached today

| Cache key composition | Producer | Purpose |
|---|---|---|
| `compile-barrier + cmd + staged-sha` | `pre-commit.sh` Check #1 | Skip `cargo check` / `tsc` / `go build` if staged content unchanged |
| `agent-reviewer + diff-sha1` | `kaizen-reviewer` agent | Skip re-audit on identical diff |
| `agent-debt-auditor + scope + repo-tree-sha` | `kaizen-debt-auditor` agent | Skip re-scan if repo unchanged + same scope |

## Notes

- Cache writes are atomic-enough (write whole file, no partial writes — `Write` is single `Path.write_text`).
- Failed compile barrier runs are NOT cached — stale failures are worse than re-running.
- Cache survives `git commit` but is gitignored; never reaches the remote.
- Manual `clear` on disk corruption or schema migration. `cache.py` versions data via key composition, not by entry payload, so clear is the migration path.
