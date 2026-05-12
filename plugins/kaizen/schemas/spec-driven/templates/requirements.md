# Requirements — <feature-name>

> Authored: <YYYY-MM-DD>
> Owner: <handle>
> Status: draft | review | accepted
> Confidence Score: <0–100>% — <rationale (clarity, complexity, scope)>

## EARS notation reference

| Pattern        | Template                                                |
|----------------|---------------------------------------------------------|
| Ubiquitous     | THE SYSTEM SHALL <behavior>                             |
| Event-driven   | WHEN <trigger>, THE SYSTEM SHALL <behavior>             |
| State-driven   | WHILE <state>, THE SYSTEM SHALL <behavior>              |
| Unwanted       | IF <condition>, THEN THE SYSTEM SHALL <response>        |
| Optional       | WHERE <feature is included>, THE SYSTEM SHALL <behavior> |

Each requirement must be **testable**, **unambiguous**, **necessary**, **feasible**, and **traceable**.

## Functional requirements

- **REQ-001** WHEN <trigger>, THE SYSTEM SHALL <expected behavior>.
- **REQ-002** THE SYSTEM SHALL <invariant>.
- **REQ-003** IF <error condition>, THEN THE SYSTEM SHALL <recovery response>.

## Non-functional requirements

- **NFR-001** THE SYSTEM SHALL <performance / availability / security target>.
- **NFR-002** WHILE <load condition>, THE SYSTEM SHALL <latency / throughput target>.

## Dependencies + constraints

- <upstream system or library>
- <regulatory / compliance / contract constraint>

## Edge cases + failure modes

- <unusual input / boundary condition>
- <fault: dependency timeout, partial write, etc.>

## Out of scope

- <thing this spec deliberately does NOT cover>

## Open questions

- <ambiguity to resolve before tasks land>
