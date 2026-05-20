# Contributing

The `kaizen` plugin eats its own dogfood — contributions go through the same gate, sizing rule, and backlog model that the plugin enforces on consumers.

> **Mandatory first step for any plugin-original code change:** load the
> [`plugin-development`](skills/plugin-development/SKILL.md) skill via
> the Skill tool. It encodes the canonical feature shape and the wiring
> checklist that this CONTRIBUTING.md assumes you've absorbed. The iron
> laws now live in their own [`iron-laws`](skills/iron-laws/SKILL.md)
> skill — registry + checker + CLI + MCP. Schema at
> [`schemas/plugin-development/`](schemas/plugin-development/);
> validate with
> `python3 skills/plugin-development/scripts/validate.py --staged`.

## Quick start

```bash
# 1. Clone + install locally
git clone https://github.com/YugeIceCone/kaizen-md
cd kaizen-md
bash plugins/kaizen/scripts/setup.sh

# 2. Run the test pipeline before changing anything
bash plugins/kaizen/scripts/ops/test-pipeline.sh
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

- [ ] `bash plugins/kaizen/scripts/ops/test-pipeline.sh` → all green
- [ ] New scripts pass `bash -n` syntax check
- [ ] New commands have proper YAML frontmatter (`name:` + `description:`)
- [ ] `/kaizen:doctor` reports healthy
- [ ] Updated `CHANGELOG.md` under `[Unreleased]`
- [ ] Cross-platform: no GNU-only utilities (`readlink -f`, `find -printf`, `sed -i` without `''`) — use the `lib.sh` helpers
- [ ] Attribution preserved: if you copy/adapt code from elsewhere, update `ATTRIBUTIONS.md`

## Architecture rules

- **All skills under `plugins/kaizen/skills/` are plugin-original derivatives.** As of 2026-05-17 the previously-vendored coding-skills / superpowers / claude-code-skills / remember bundles have been retired from active upstream-tracking — extensive kaizen-local alterations made the upstream-patch-first round-trip impractical. Original-author attribution is preserved in `ATTRIBUTIONS.md` (now framed as *originally based on / inspired by* rather than *bundled from*).
- **Cross-platform first.** Linux GNU + macOS BSD both supported. `python3` is the only hard dependency beyond `bash` + `git`.

## Testing

- **Unit tests** for `backlog.py`: add to `tests/test_backlog.py` (Python `unittest`). Not yet present — contributions welcome.
- **End-to-end tests** in `scripts/test-pipeline.sh` — TAP style, sandbox in `/tmp/gwtest-*`.
- **Hook schema tests** — each hook script is fed a sample event JSON and its stdout JSON is validated against the docs.anthropic.com hook schema.

## Issue / PR tags

- `bug` — gate produced wrong verdict / hook output malformed
- `feature` — new command, new check, new subcommand
- `cross-platform` — macOS / BSD compatibility
- `docs` — README / CHANGELOG / SKILL.md / command descriptions
- `attribution` — fix author credit in `ATTRIBUTIONS.md`

## Upstream provenance (retired 2026-05-17)

The plugin originally bundled three upstream marketplaces (9 coding-skills, 14 superpowers, 5 remember skills + supporting Node scripts) under a bundle-refresh discipline. After extensive kaizen-local alterations — schema-driven domain refactors (v1.32.0+), discipline integrations (verify-before-execution, onion-ddd-workflow), and per-skill enhancements — the upstream-patch-first round-trip became impractical and the skills are no longer one-to-one with their origins.

The bundles are now treated as plugin-original derivatives. Original-author attribution is preserved in `ATTRIBUTIONS.md` under the *originally based on / inspired by* framing. Future upstream changes from the source repos are no longer auto-pulled; if you want to selectively re-incorporate a specific upstream improvement, do it as a normal `feat(skills):` or `fix(skills):` commit with the upstream-sha cited in the body.

**Adding a NEW upstream-vendored skill.** If kaizen ever wires in fresh upstream-tracked content, restore the discipline:

1. Add the skill dir name to the `VENDORED` set in `plugins/kaizen/skills/workflow/scripts/_iron_laws.py` (and document in `schemas/iron-laws/iron-laws.yaml::no-modify-vendored`).
2. Mirror via `cp -rp` from the upstream cache, never hand-edit.
3. Re-sync via `git commit -m "bundle-refresh: pull <upstream> @ <sha>"`.

The iron-law machinery remains in place as infrastructure; only the active list is empty.

## Code of conduct

Be excellent. Open an issue before redesigning. Surface deviations from plans. The discipline this plugin enforces — explicit probes, same-commit tickets, no silent bypasses — applies to development of the plugin itself.
