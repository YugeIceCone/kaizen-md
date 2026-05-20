## What

<!-- One sentence per change. Verb-first. -->

## Sizing (per the rule)

<!-- Probe output: -->
- `grep -rn '<symbol>' | wc -l` → N files
- Manifest changes: 0 / Cargo.toml / package.json
- Trait/interface moves: 0

→ Stays MICRO / Split into siblings / Promoted to plans/

## Checklist

- [ ] `bash plugins/kaizen/scripts/ops/test-pipeline.sh` → 29/29 (or more) pass
- [ ] New scripts pass `bash -n`
- [ ] `/kaizen:doctor` reports healthy (or expected warnings only)
- [ ] CHANGELOG.md `[Unreleased]` entry added
- [ ] Cross-platform clean (no `readlink -f`, no `find -printf`, no `sed -i` without `''`)
- [ ] Attribution preserved (ATTRIBUTIONS.md updated if any upstream content changed)
- [ ] Commit message uses Conventional Commits prefix

## What this is NOT

<!-- Explicit scope-fence. Adjacent improvements you considered but didn't include. -->

## Reviewer notes

<!-- Anything non-obvious about the diff. Why a deviation from the plan, if any. -->
