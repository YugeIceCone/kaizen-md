---
name: migrate
description: Manages framework, version, API, and infrastructure migrations. Use when technical freshness and compatibility risk matter.
metadata:
  version: "1.1"
---

# Code Migrating

Manages upgrades and migrations where technical freshness and compatibility risk matter.

## Core Flow
1. Research the target technology or version.
2. Analyze current usage and migration impact.
3. Plan phased, reversible changes.
4. Implement one phase at a time.
5. Review the result and validate breaking-change risk.

## Stage Map

- Research -> `external-researching`
- Analyze -> `migration-planning` and `codebase-pattern-scouting`
- Plan -> **create-plan** with `migration-planning` guidance and durable plans in `plans/`
- Implement -> **execute-plan** with **create-task**, `test-heavy-implementing`, or `scoped-implementing`
- Review -> **review**
- Validate -> **plan-validating**

## Rules

- Prefer official migration guides and current documentation.
- Treat breaking changes, data migrations, and rollback paths as first-class concerns.
- Keep work local unless the user explicitly asks for delegation.
- Avoid Markdown tables.
