---
name: proactive-auditing
description: Proactively hunts for bugs, weak contracts, and missing regression coverage. Use to scan code for concrete failure candidates, prove them, and either fix them or report findings.
metadata:
  version: "1.2"
---

# Proactive Auditing

Hunts for real bugs, weak contracts, and missing regression coverage in a target file, module, or subsystem.

## Audit Loop

1. If `.agents/stack-context.md` does not exist, run **detect-stack** first.
2. Explore the target area and identify likely risk surfaces.
3. List concrete bug candidates.
4. Triage for severity and confidence.
5. Prove each serious candidate with a failing test or equally concrete reproduction.
6. Fix minimally or report findings if the user asked for review only.
7. **Apply in-scope Boy-Scout findings inline, even in "report only" mode.** Any small cleanup surfaced during the audit (dead import, magic string, misleading rename, missing type annotation) that passes the **verify-before-execution** RED-GREEN gate gets applied in the same flow — it does not go into the findings list as a deferred item. "Report only" applies to the *proven bugs*, not to the small in-scope cleanups picked up along the way. See **boy-scout-rule** Rule 5 + Discovery-Time Application Protocol + **verify-before-execution** for the gate.
8. Run focused verification and then the broader project barrier when appropriate.

## Good Candidate Classes

- logic and control-flow bugs
- state leaks and stale caches
- error-handling gaps
- boundary and empty-input failures
- contract mismatches between callers and callees
- LoD violations that create hidden coupling and null-dereference risk
- knowledge duplication that allows logic to diverge silently

## Proof Standard

- If you cannot reproduce the failure or create a failing check, treat it as unproven.
- Drop speculative findings rather than padding the audit.
- If you report findings without fixing them, put the proven ones first.

## Companion Skills

- **verify-before-execution** -> RED-GREEN gate for every in-scope finding applied during the audit (Step 7)
- **boy-scout-rule** -> eligibility criteria for in-scope inline cleanups
- **detect-stack** -> identify the stack before applying language-appropriate checks
- **codebase-exploring** -> map the target area first
- **change-analyzing** -> understand blast radius and invariants
- **law-of-demeter** -> deep coupling as a bug candidate class
- **dry** -> duplicated business logic as a divergence risk
- **kiss** -> complexity that hides failures
- **fix** -> repair a proven bug
- **review** -> summarize verified findings first
- **validate** -> final confidence pass on risky fixes

## Agent Roles

Use the home agent catalog as role guidance:

- `change-plan-reviewing` -> general review and bug-hunt pass
- `code-reviewing` -> maintainability and contract issues
- `security-auditing` -> security-focused audit
- `performance-optimizing` -> performance and contention audit

Use delegation only if the user explicitly asks for it.

## Rules

- No fix without proof.
- No finding without evidence.
- Prefer the highest-leverage candidates first.
- Avoid Markdown tables.
- Boy-Scout findings get applied during the audit (Step 7), not deferred. The audit report names what was applied; only items that failed the boy-scout verification gate appear as deferred trail items.
