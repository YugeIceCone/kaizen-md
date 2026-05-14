# Contributing

The `kaizen` plugin eats its own dogfood — contributions go through the same gate, sizing rule, and backlog model that the plugin enforces on consumers.

> **Mandatory first step for any plugin-original code change:** load the
> [`plugin-development`](skills/plugin-development/SKILL.md) skill via
> the Skill tool. It encodes the canonical feature shape and the wiring
> checklist that this CONTRIBUTING.md assumes you've absorbed. The iron
> laws now live in their own [`iron-laws`](skills/iron-laws/SKILL.md)
> skill — registry + checker + CLI + MCP. Schema at
> [`skills/plugin-development/domain/`](skills/plugin-development/domain/);
> validate with
> `python3 skills/plugin-development/scripts/validate.py --staged`.

## Quick start

```bash
# 1. Clone + install locally
git clone https://github.com/YugeIceCone/kaizen-md
cd kaizen-md
bash plugins/kaizen/scripts/install.sh

# 2. Run the test pipeline before changing anything
bash plugins/kaizen/skills/workflow/scripts/test-pipeline.sh
# Should: 29/29 pass

# 3. Make changes, re-run test
# (it's fast — ~1s — run after every meaningful edit)
```

## Sizing rule (mandatory)

**Never grade work in hours.** Probe with trace + sem + grep first:

```
grep -rn "<symbol>" --include='*.sh' --include='*.py' --include='*.md' | wc -l    # file count
```

| Probe result | Action |
|---|---|
| ≤3 files, 0 manifest edits | micro item in `.workflow/backlog.json` |
| 4–15 files | split into sibling micros |
| ≥16 files OR ≥2 manifest OR new top-level concept | `plans/<date>-<slug>.md` plan file |

## Commit discipline

The plugin's own pre-commit gate enforces:

1. **Conventional Commits prefix:** `feat(scope): | fix: | docs: | refactor: | chore: | test: | perf: ...`
2. **Same-commit discipline:** A structural change (e.g. adding a new script or modifying `plugin.json`) ships with its CHANGELOG entry in the same commit. No follow-ups.
3. **No secrets:** committed AWS/GitHub/OpenAI/Slack tokens, private keys, JWTs blocked by Check #9.
4. **Paired tests:** new `.sh` / `.py` scripts should have coverage in `test-pipeline.sh` (warn only, but please).
5. **CLAUDE.md / config files** track rules; **CHANGELOG.md** tracks releases. Don't put commit SHAs or LOC counts in the rulebook.

## Pull-request checklist

- [ ] `bash plugins/kaizen/skills/workflow/scripts/test-pipeline.sh` → all green
- [ ] New scripts pass `bash -n` syntax check
- [ ] New commands have proper YAML frontmatter (`name:` + `description:`)
- [ ] `/kaizen:doctor` reports healthy
- [ ] Updated `CHANGELOG.md` under `[Unreleased]`
- [ ] Cross-platform: no GNU-only utilities (`readlink -f`, `find -printf`, `sed -i` without `''`) — use the `lib.sh` helpers
- [ ] Attribution preserved: if you copy/adapt code from elsewhere, update `ATTRIBUTIONS.md`

## Architecture rules

- **Bundled skills are vendored, not modified.** If a bundled skill needs a change, send the patch upstream first (Jordan Coin Jackson for coding-skills; Jesse Vincent for superpowers; Gabi Fratica for remember); the bundle here is a refresh of upstream.
- **Plugin-original code** lives in:
  - `skills/workflow/` (the discipline itself)
  - `scripts/`, `commands/`, `hooks/` (plugin entry points)
  - `LICENSE`, `README.md`, `ATTRIBUTIONS.md`, `CHANGELOG.md`, `CONTRIBUTING.md`
- **Cross-platform first.** Linux GNU + macOS BSD both supported. `python3` is the only hard dependency beyond `bash` + `git`.

## Testing

- **Unit tests** for `backlog.py`: add to `tests/test_backlog.py` (Python `unittest`). Not yet present — contributions welcome.
- **End-to-end tests** in `scripts/test-pipeline.sh` — TAP style, sandbox in `/tmp/gwtest-*`.
- **Hook schema tests** — each hook script is fed a sample event JSON and its stdout JSON is validated against the docs.anthropic.com hook schema.

## Issue / PR tags

- `bug` — gate produced wrong verdict / hook output malformed
- `feature` — new command, new check, new subcommand
- `bundle-refresh` — pulling latest from coding-skills/superpowers/remember
- `cross-platform` — macOS / BSD compatibility
- `docs` — README / CHANGELOG / SKILL.md / command descriptions
- `attribution` — fix author credit in `ATTRIBUTIONS.md`

## Bundle-refresh procedure

The plugin vendors 9 coding-skills, 14 superpowers, 5 remember skills + remember's
supporting Node scripts. To pull upstream changes:

```bash
# 1. Refresh the upstream cache (Claude Code's marketplace machinery)
#    coding-skills:
git -C ~/.claude/plugins/marketplaces/codingskills pull
#    superpowers (Anthropic's official marketplace):
git -C ~/.claude/plugins/marketplaces/claude-plugins-official pull
#    remember (local marketplace — git pull only if you cloned it):
#    (skip if you've made local edits — see "modified remember" section)

# 2. Identify what changed since last sync
diff -rq plugins/kaizen/skills/kiss/ \
         ~/.claude/plugins/cache/codingskills/coding-skills/*/skills/kiss/
# repeat for each vendored skill; review the diff

# 3. For each meaningful upstream change, copy the file with `cp -p`
cp -rp ~/.claude/plugins/cache/codingskills/coding-skills/*/skills/kiss/. \
       plugins/kaizen/skills/kiss/

# 4. Test pipeline regression (must stay 29/29+ green)
bash plugins/kaizen/skills/workflow/scripts/test-pipeline.sh

# 5. Update ATTRIBUTIONS.md if upstream versioning shifted (rare)
#    Update CHANGELOG.md with the refresh entry under [Unreleased]

# 6. Commit with: bundle-refresh prefix
git commit -m "bundle-refresh: pull coding-skills @ <upstream-sha>"
```

**Never edit vendored content in this repo.** Send patches upstream first:
- coding-skills → github.com/JordanCoin/codingskills
- superpowers → github.com/obra/superpowers
- remember → github.com/remember-md/remember

Then refresh here.

## Code of conduct

Be excellent. Open an issue before redesigning. Surface deviations from plans. The discipline this plugin enforces — explicit probes, same-commit tickets, no silent bypasses — applies to development of the plugin itself.
