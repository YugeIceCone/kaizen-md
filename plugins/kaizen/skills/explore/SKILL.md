---
name: explore
description: Maps codebase structure, entry points, and existing patterns before acting. Use when entering an unfamiliar repo, module, or subsystem.
metadata:
  version: "1.1"
---

# Codebase Exploring

Maps what exists in the codebase before deciding what to change. This skill answers "what is here and how is it connected?"

## Exploration Targets

- entry points and top-level commands
- module boundaries and ownership
- imports, callers, and data flow
- configs, schemas, and environment assumptions
- nearby tests and fixtures
- existing patterns worth following

## Exploration Flow

1. Define the scope: repo, module, feature, or file set.
2. Search before reading large files.
3. Read the smallest set of files that explains the shape of the area.
4. Trace imports, callers, routes, and tests around the target.
5. Summarize the structure with concrete file references.

## Preferred Tactics

- use `rg --files`, `rg`, and targeted reads first
- inspect entry points before internals
- read tests to learn expected behavior quickly
- trace public interfaces before private helpers
- prefer a focused map over a full-file dump

## Output Modes

- quick orientation -> major folders, entry points, and important files
- focused module map -> responsibilities, interfaces, callers, tests
- architecture pass -> layers, boundaries, cross-cutting utilities, coupling risks

## Companion Skills

- **detect-stack** -> identify language, framework, and conventions when entering a new project
- **research** -> when outside docs or current standards are needed too
- **change-analyzing** -> when exploration should turn into impact and risk assessment
- **create-plan** -> when the explored area is about to change
- **review** -> when the user wants critique instead of orientation

## Agent Roles

Use the home agent catalog as role guidance:

- `codebase-pattern-scouting` -> codebase exploration and pattern search
- `codebase-onboarding` -> broader brownfield orientation

Use delegation only if the user explicitly asks for it.

## Rules

- Stay read-only unless the user clearly asks to proceed into implementation.
- Prefer direct summaries over writing docs unless the user wants a durable artifact.
- Avoid Markdown tables.
