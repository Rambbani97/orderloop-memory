# Architecture

OrderLoop Memory — ContextCon Theme 2: Never Solve It Twice.

## What it is

A support-agent system for **OrderLoop**, a fictional SaaS for order,
inventory and fulfilment management. Two agents share one Meko datapack as
collective memory. The experiment is an A/B: condition A (no memory) vs
condition B (one `context_search` per ticket before solving).

## Components

```
                    ┌────────────────────┐
                    │  Demo server (FastAPI)
                    │  inbox · trace · HITL · metrics
                    └──────┬─────────────┘
                           │ runs tickets through
                    ┌──────▼─────────────┐
                    │  Harness            │  replay in file order
                    │  - protocol checks  │  A: zero Meko calls
                    │  - M1–M10 metrics   │  B: search before any fix op
                    │  - HITL proposals   │  ground truth never to agent
                    └──────┬─────────────┘
              ┌────────────┼────────────┐
       ┌──────▼───┐ ┌─────▼────┐ ┌────▼───────┐
       │ Triage   │ │Specialist│ │ Mock       │
       │ agent    │ │ agent    │ │ OrderLoop  │
       └────┬─────┘ └────┬─────┘ └────────────┘
            │  search (B)│  execute + verify
       ┌────▼────────────▼────┐
       │  Meko datapack       │  context_search / memory_add
       │  + local KB          │  (condition A: local KB only)
       └──────────────────────┘
```

## Agents — deterministic loop, LLM only plans

Control flow is plain code, not an agent framework:

1. **Triage** (`orderloop-triage`) receives the sanitised ticket.
   Condition B: exactly one `context_search` (query = subject + body).
   Condition A: local KB search only.
2. The LLM returns a **structured JSON plan** — diagnosis, steps, actions,
   confidence, `needs_human`. It does not call tools itself.
3. If `needs_human` or confidence < 0.6, Triage hands off to the
   **Specialist** (`orderloop-specialist`), which re-plans with the same
   retrieved context and executes.
4. Actions run against the in-process mock (`app/mock_orderloop.py`).
   Every op is verified by `verify_fix()` against the ticket's root cause —
   verification is scorer-only, never shown to the agent.
5. The final answer is the plan's `final_answer` plus what was executed.

The LLM is Google Gemini (free tier, one locked model, temperature 0).
`StubLLM` is a deterministic test double used for smoke tests; it builds
plans from prompt keywords only and never reads ground truth.

## Memory — the part that matters

- **One datapack per run** (`orderloop-run-b1/b2/b3`), one shared datapack
  for the demo. Two agents, two `agent_id`s, one datapack — the brief
  requires demoing an agent reusing a fix learned by a *different* agent.
- **One `context_search` per ticket** in condition B, enforced by the
  harness. No separate `memory_search` / `knowledgebase_search` calls.
- **Only human-approved fixes become memory.** After each first-time
  ticket, the fix is proposed to the HITL queue (`app/hitl.py`, JSON-backed
  with an audit log). A human approves (dashboard) or rejects with a
  reason (too specific / duplicate / wrong fix / sensitive). Agents never
  approve their own fixes; human-escalation fixes are labelled
  `source: human-escalation`.
- Memory text is generic and customer-agnostic (diagnosis + steps +
  verification), with metadata `ticket_id`, `cluster`, `memory_key`
  (the seed ticket id), `source`, `agent`, `approved_by`.
- **Retrieval hit** = the used memory's `memory_key` equals the ticket's
  seed id. A repeat that reuses a memory from the wrong cluster is a
  **false reuse**; a distractor solved without touching a memory is a
  **correct abstention**.

## Mock OrderLoop

In-process deterministic world: orders, webhooks, SAML, billing, push,
Shopify sync, reports, CSV import, 2FA, API usage, GDPR, accounts.
`execute(op, args)` runs the fix operation and records state;
`verify_fix(ticket)` checks the root-cause condition per cluster.
Customer-only actions are named `customer_*` — the agent instructs, the
mock models the customer confirming. The mock is scorer-only knowledge:
the agent sees op names and results, never the recipes.

## Demo server

FastAPI (`app/server.py`) + vanilla JS (`static/index.html`):

- **Inbox** — the 36 tickets exactly as the agent sees them (sanitised).
- **Live Trace** — run one ticket, see the trace, tokens, retrieval class.
- **HITL Queue** — approve/reject fixes into memory.
- **Metrics** — A vs B summary tables from the latest run files.

The server runs the same harness as the CLI; a run started from the
dashboard writes the same `results/run-*.jsonl` files.

## Tech choices

Python 3.12, hand-rolled loop (no agent framework — the flow is small
enough that a framework would hide the protocol), `mcp` package for the
Meko client, FastAPI + vanilla HTML/JS for the demo, pandas/matplotlib
for charts, pytest for tests. Deployed later on Render free tier; the
public repo is `orderloop-memory`.

## What is NOT in scope

- No real customer data, no real OrderLoop — everything is synthetic.
- No autonomous memory writes, no bulk approve, no memory dedup by the
  agent (duplicates are a HITL rejection reason).
- No paid LLM calls in official runs (Gemini free tier); no Meko quota
  beyond the free tier (see `docs/MEKO_USAGE.md`).
