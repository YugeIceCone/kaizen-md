---
name: self-rag
description: Self-RAG retrieval discipline — when to retrieve, when to skip, when to trust what was retrieved. Adapted from Asai et al. 2023 (Self-Reflective Retrieval-Augmented Generation). Triggers on "self-rag", "rag discipline", "should I retrieve", "do I need context", "before answering", "is what I retrieved relevant", "verify retrieval", "knowledge search". Pairs with `/kaizen:knowledge` (corpus) and `kaizen-trace-search` (event log).
---

# Self-RAG — retrieval discipline

The core mistake of vanilla RAG: **always retrieve**, then **always trust** what came back. Self-RAG inserts metacognitive checks at three moments:

1. **Before retrieval** — should I retrieve at all?
2. **After retrieval** — is what I got actually relevant?
3. **After answering** — did the retrieved evidence actually support my response, and did I miss anything?

This skill encodes those three checks against kaizen's two corpora: `/kaizen:knowledge` (brain notes, plans, backlog, schemas, persona) and `kaizen-trace-search` (trace events). Apply BEFORE invoking either retrieval surface.

## The three decisions

### Decision 1 — Retrieve or skip?

**Retrieve when:**
- The question references project-specific things: backlog items, plan files, prior decisions, brain notes, schemas.
- The question hints at "have we done this before?" / "what's the convention here?" / "where did we land on X?"
- You're about to make a recommendation that contradicts something a user might have already decided (check brain notes first).
- Onboarding context: you've just entered the project and are still mapping it.

**Skip retrieval when:**
- The question is general programming — a JSON parser bug, a Rust borrow-checker question, a Python idiom. The answer lives in your training, not the corpus.
- The question is purely about the current diff / file content — Read + Grep is more direct than retrieval.
- The answer is mechanical (e.g. "what command runs the tests?" — usually answerable from `package.json` / `Cargo.toml` / `.kaizen.toml`).
- Time-sensitivity beats freshness — the user is mid-flow and waiting; retrieval adds latency. Use only on stable beliefs.

**The litmus test:** if your draft answer cites a project-specific noun (e.g. "the F-FINAL phase", "the borg-loop discipline", "the spec-driven schema's branch_high path") **and you're not 100% sure that noun is fresh in your context**, retrieve before answering.

### Decision 2 — Is what came back relevant?

After running `/kaizen:knowledge search "<query>"` or `kaizen-trace-search search "<query>"`:

For each top-K result, ask:

- **Topic match?** The title and snippet actually relate to the question, not just lexically overlap on a common word.
- **Freshness match?** The `updated_at` is recent enough that the belief / plan / decision still holds. Brain notes have a `freshness:` field; treat `stable` as load-bearing and `fresh-evidence` / `single-source` as advisory.
- **Source-tier match?** A `persona` belief from `Top Beliefs` outweighs a single project plan; a project plan outweighs an old backlog probe.

**If no result clears all three checks:** the corpus doesn't have what you need. Either widen the query (different keywords, broader `--top-k`) or accept that this answer isn't grounded in the corpus and answer from your general capability — **but signal that to the user**: "I didn't find an existing decision on this in your knowledge base; recommending fresh."

### Decision 3 — Did the evidence support your answer?

After drafting the response with retrieved context, do one final pass:

- **Citation check** — for each retrieved item I used, is the connection between *what it says* and *what I claim* tight? Or am I stretching?
- **Contradiction check** — does anything in the retrieved set contradict my recommendation? If yes, surface it explicitly to the user ("note: this conflicts with brain note `pref-X`; deferring to you").
- **Gap check** — is there an obvious adjacent retrieval I should have done? E.g. you retrieved plans but didn't check backlog for a sibling item. Run the second search.

## Concrete recipe

```bash
# 1. Pre-retrieval decision (do this mentally, not as a tool call).
#    If "retrieve" is the answer:

# 2. Retrieve from the knowledge corpus:
/kaizen:knowledge search "<focused query>" --top-k 5

# 3. Filter top results through the three Decision-2 checks. Discard
#    misses. If nothing survives, widen:
/kaizen:knowledge search "<broader query>" --top-k 10

# 4. (Optional) Also check trace history for recent activity in this area:
kaizen-trace-search search "<adjacent query>" --top-k 5

# 5. Draft the response citing the retained items by source_path.
#    Use this format: "(per brain note pref-X)" or "(per plan
#    2026-05-12-y.md status block)".

# 6. Final pass: citation + contradiction + gap checks before sending.
```

## When NOT to use this skill

- Mid-implementation, with no question to answer — you're writing code, not retrieving context.
- Inside an Agent / subagent — the subagent already has the corpus context; you've stepped into a different cognitive scope.
- For trace queries that are about *finding a specific past event* (e.g. "find the last cargo-test run"), use `kaizen-trace-search` directly without the self-rag overhead.

## Iron Laws

1. **Never retrieve and then ignore.** If you ran the search, the top results MUST be acknowledged — either used as citations or explicitly dismissed with a reason.
2. **Never claim a project convention you didn't verify.** "Kaizen uses X" requires a brain note or schema or plan citing X. Otherwise it's "I'd recommend X" (your opinion, not the project's).
3. **Never embed PII / secrets in queries.** The query string passes through the embedding model. Treat it as you would a search URL. The `/kaizen:knowledge` corpus is privacy-safe by default (signature-only embeddings), but your queries are still text.
4. **Stale beliefs decay.** If a brain note's `updated_at` is > 6 months old AND the note doesn't carry `freshness: stable`, treat it as advisory, not load-bearing. Surface the staleness to the user and ask whether to refresh.

## Related skills

- `/kaizen:knowledge` — the corpus + search surface this skill governs.
- `kaizen-trace-search` — semantic search over trace events.
- `/kaizen:vibe-check` — pre-commit AI-coding discipline (the answering-side analog).
- `kaizen:memory-state` — how to decide what to persist vs recall.
- `kaizen:remember` — capture-side counterpart (what goes into the corpus in the first place).
