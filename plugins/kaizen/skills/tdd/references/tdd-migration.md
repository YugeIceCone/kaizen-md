# TDD Migration Pipeline

Orchestrator-only workflow for migrating or rewriting codebases with full TDD and agent delegation.

## When to Use

- Porting codebase from one language/framework to another
- Rewriting a system with TDD guarantees
- Creating N adapters/components following an existing pattern
- Large-scale refactoring with behavioral contracts
- Any migration where you want zero context growth in the orchestrator

## Core Principles

- **Zero orchestrator execution** — only instruct agents and pipe context (paths, not contents)
- **All work done by agents** — you never read/write/validate in main context
- **Context window stays flat** — pass paths, not file contents
- **New code in separate directory** — never modify source
- **Parallel where independent** — items, review + quality, analysis + planning

## Pipeline Phases

### Phase 0: Plan

Write a YAML plan to `thoughts/plans/<name>-tdd.yaml` listing all items with file paths, test paths, and dependencies.

### Phase 1: SPEC

Instruct scout/architect agent to analyze source using `tldr structure`, `tldr extract`, `tldr calls`. Output: `spec.md` with behavioral contracts, types, edge cases, dependencies.

### Phase 2: Failing Tests

Instruct arbiter agent to read spec.md and write failing tests defining expected behavior. Instruct critic to validate tests cover spec completely.

### Phase 3: Adversarial (3 iterations)

Instruct premortem agent to review spec + tests, identify failure modes, race conditions, edge cases. Each pass finds NEW issues. Add mitigations directly to spec.

### Phase 4: Phased Plan

Instruct architect to create `phased-plan.yaml` with dependency-ordered phases. Each phase = one testable unit with clear inputs/outputs.

### Phase 5: Build Loop (per phase or parallel per item)

**Per-item parallel (for independent items):**
For each item, launch ONE kraken agent that does full TDD: read pattern → write failing test → implement → run tests → quality check.

**Per-phase sequential (for dependent phases):**
For each phase in plan, instruct builder agent to write code passing that phase's tests, then critic reviews.

### Phase 6: Integration Validation

Instruct atlas/validator agent to: run full integration tests, `tldr` diff against reference, check for race conditions/hangs/breaking changes. Output: `validation-report.md`.

## Agent Mapping

- **Explore/analyze** → scout or architect
- **Write tests + implement** → kraken (large) or spark (small)
- **Run tests/validate** → arbiter or atlas
- **Code review** → critic or judge
- **Quick fixes** → spark
- **Premortem** → premortem skill

## Agent Prompt Templates

**Scout (analysis):**
```
Analyze <path> using tldr structure, tldr extract, tldr calls.
Create spec.md at <target>/spec.md with all behavioral contracts,
input/output types, edge cases, and component dependencies.
```

**Kraken (TDD per item):**
```
Implement <item> using TDD:
1. Read <pattern> for structure
2. Write failing test to <test_path>
3. Implement minimal to <impl_path>
4. Run: <test_command>
5. Run: qlty check <impl_path>
Report: status, issues, files created.
```

**Critic (review):**
```
Review <files> against <pattern>:
1. Pattern compliance
2. Type safety
3. Missing registrations
4. Security issues
DO NOT edit. Report issues only.
```

**Spark (fix):**
```
Fix <specific issue>:
1. Read <file>
2. Make minimal edit
3. Verify fix
```

## Anti-Patterns

- **Reading files in main context** → launch scout agent instead
- **Writing code in main context** → launch kraken/spark instead
- **Running tests in main context** → launch validator instead
- **Skipping review** → always launch critic
- **Sequential independent items** → parallel krakens
- **Fixing in main context** → launch spark
- **Skipping adversarial phase** → premortem catches real bugs

## Invocation

```
/tdd-migrate <source_path> <target_path> --pattern <reference> --items "item1,item2,item3"
```

Or specify in YAML:
```yaml
SOURCE: <path to source code>
TARGET_DIR: <new folder for migrated code>
TARGET_LANG: typescript|python
REFERENCE_REPO: <url or path for final diff comparison>
```

## Success Criteria

- [ ] All tests pass
- [ ] Quality reports clean
- [ ] tldr diff shows no breaking changes vs reference
- [ ] No race conditions or hangs
- [ ] All items registered/exported properly
- [ ] Validation report confirms behavioral equivalence
