---
name: Prefer handoff plans over raw conversation logs for orientation
description: When a session handoff plan and a raw conversation log both exist, read the handoff in full and grep the log on-demand. Don't blind-read multi-thousand-line conversation transcripts.
type: belief
confidence: 0.9
tags: [preference, workflow, orientation, context-efficiency]
sources_count: 2
freshness: stable
created: 2026-05-11
updated: 2026-05-15
---

# Prefer handoff plans over raw conversation logs for orientation

When the user opens a session with both a structured handoff plan
and a raw conversation log (e.g. `dual_stream_llm_session.md` at 8027
lines), **read the handoff in full, grep the log on-demand**. The
handoff is the distilled load-bearing context; the raw log is the
source-of-truth for specific lookups only.

## Why

A comprehensive handoff plan already captures: status, architecture,
commits, files, usage, known limitations, validation snapshot. Reading
the raw log on top of that is redundant context consumption with low
marginal value. User explicitly redirected mid-read:

> **[16:46] User:** read handoff, grep search only in session log

— after I had announced an intent to read the 8027-line log in chunks.

## How to apply

1. Read every handoff plan / orientation file in full first (the
   "Orientation read first" persona directive still holds).
2. For a multi-thousand-line raw conversation log mentioned alongside,
   **do not blind-read**. Use grep on specific queries when looking up
   verbatim quotes, decisions not in the handoff, or context for an
   ambiguous handoff line.
3. If you genuinely need wide swathes of the log (e.g. the handoff is
   shallow), ASK the user before chunked-reading rather than
   announcing intent and starting.
4. The 8027-line log → 2-line read decision: handoff was 271 lines and
   covered everything; reading the raw log would have consumed
   ~250K+ tokens for ~0 marginal context.

## Edge cases

- If a handoff exists but is brief / status-only (≤50 LOC), the raw
  log IS the load-bearing context — read it.
- If the user references a specific section of the raw log
  ("see the part about X"), read that section directly, not the whole.
- Never assume "handoff is comprehensive" without scanning it first.
  Quick handoff-read, then decide.

## Evidence

- source: Journal/2026-05-11.md
  quote: "read handoff, grep search only in session log"
  date: 2026-05-11
- source: Journal/2026-05-15.md
  quote: "use an agent to write a continuation handoff for a fresh new session"
  date: 2026-05-15
  context: Active creation of a handoff plan at session end — confirms handoff plans are this user's preferred orientation artifact in BOTH directions (read at session start, write at session end). Strengthens the broader claim that durable handoffs are how cross-session continuity happens for this user, beyond the original "read handoff vs raw log" framing.
