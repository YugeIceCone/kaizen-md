# <feature-name>

> Spec authored: <YYYY-MM-DD>
> Owner: <handle>
> Status: draft | review | accepted

## Acceptance criteria (Given / When / Then OR EARS)

Either form is fine for this schema — pick the one closer to how the feature
reads. Bigger / higher-risk work should use the **spec-driven** schema instead,
which requires EARS throughout.

### Given / When / Then (low-ceremony)

**Given** <pre-condition>
**When** <action>
**Then** <outcome>

### EARS notation (Easy Approach to Requirements Syntax)

- Ubiquitous:    THE SYSTEM SHALL <behavior>
- Event-driven:  WHEN <trigger>, THE SYSTEM SHALL <behavior>
- State-driven:  WHILE <state>, THE SYSTEM SHALL <behavior>
- Unwanted:      IF <condition>, THEN THE SYSTEM SHALL <response>
- Optional:      WHERE <feature is included>, THE SYSTEM SHALL <behavior>

(Add more blocks for additional criteria.)

## Out of scope

- <thing this spec deliberately does NOT cover>

## Notes / open questions

- <ambiguity to resolve before tasks land>
