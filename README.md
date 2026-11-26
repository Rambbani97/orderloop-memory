# OrderLoop Memory

**ContextCon hackathon — Theme 2: Never Solve It Twice.**

A support-agent system where two agents (Triage + Specialist) share one Meko
datapack as collective memory. The experiment measures whether an agent that
can reuse a fix learned by a *different* agent solves repeat tickets faster,
cheaper, and with fewer steps — without losing quality, and without ever
reusing a fix for a look-alike problem that is actually different.

## The idea in one paragraph

A customer reports a Stripe webhook 400. Triage searches shared memory,
finds nothing, escalates; the Specialist diagnoses a rotated webhook secret,
fixes it, and a human approves the fix into memory. A week later a different
customer hits the same 400 — Triage searches memory, finds the fix the
*Specialist* wrote, reuses it in one step. A third ticket *looks* the same
but is a wrong webhook URL, not a secret — the agent must notice the
difference and abstain. That is the whole demo: reuse where it helps,
abstention where it would hurt.

## Live demo

Deployed on Render (free tier) from this repo — see `render.yaml`.
The demo runs with the stub LLM + FakeMeko (no credentials, $0), so anyone
can open it, run a ticket in condition A or B, and approve a fix into
memory from the dashboard.

## Quick start (no keys needed)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Smoke test — stub LLM + FakeMeko (in-memory), no credentials, no cost
python scripts/run_experiment.py --condition A --run 1 --llm stub --meko null --limit 6
python scripts/run_experiment.py --condition B --run 1 --llm stub --meko fake --hitl-mode auto --limit 6

# Demo dashboard (same test doubles)
python -m app.server   # http://127.0.0.1:8000
```

## Official runs (needs keys)

```bash
cp .env.example .env   # fill MEKO_DATAPACK_ID (no keys — see below)
python scripts/seed_kb.py --dry-run
python scripts/seed_kb.py
# 3 runs per condition, Gemini free tier, Meko Cloud, manual HITL
python scripts/run_experiment.py --condition A --run 1 --llm gemini --meko null
python scripts/run_experiment.py --condition B --run 1 --llm gemini --meko real
# ... repeat --run 2 and --run 3 for each condition
python scripts/make_charts.py
```

> `--hitl-mode auto` approves fixes immediately. It is **test-only** — it
> violates the human-in-the-loop rule. Official runs always use `manual`:
> fixes wait in the queue and a human approves them in the dashboard.

## Results — official runs, 26 Nov 2026 (6 runs × 36 tickets = 216)

Gemini `gemini-3.5-flash-lite`, temperature 0, Meko Cloud (condition B
only), manual human approval between tickets. Cost $0 (free tiers).
Quality-auto is the rubric proxy; official quality is the human review
below. Full data in `results/` (per-run `.jsonl` + summaries).

| Run | Quality-auto mean | Passed (≥70) | Verified rate | Time/ticket | Tokens/ticket | TPT passed | Violations |
|-----|-------------------|--------------|---------------|-------------|---------------|------------|------------|
| A1 | 74.01 | 23/36 | 0.222 | 13.55 s | 2,203 | 1,935 | 0 |
| A2 | 77.81 | 26/36 | 0.278 | 6.76 s | 1,991 | 1,857 | 0 |
| A3 | 74.53 | 27/36 | 0.194 | 8.58 s | 2,100 | 2,004 | 0 |
| B1 | 71.57 | 24/36 | 0.250 | 23.75 s | 3,464 | 3,256 | 0 |
| B2 | 71.61 | 21/36 | 0.194 | 15.80 s | 3,022 | 2,892 | 0 |
| B3 | 76.52 | 28/36 | 0.250 | 17.95 s | 2,896 | 2,945 | 0 |

Repeat hit rate (condition B): B1 0.750, B2 0.625, B3 0.875.
Verified rate overall: **50/216 = 0.231** (re-checked from traces, no
corrections). Two clusters never verified in any run: C6 (report timeout)
and C8 (identity-verification chain never completed) — 0/18 each.

### Human review (M8) — AI-assisted, not blind

A 72-item stratified sample (12 per run; 36 A + 36 B) was rated by one
human reviewer on a phone widget. The reviewer saw Jarvis's binary
pre-label per item ("Tinggi"/"Rendah", derived from the auto score) and
the slider started at 85 (Tinggi) or 45 (Rendah). This is therefore
**AI-assisted human review, not a blind human rating** — it is reported
as such. Agreement with the auto scores was 71/72 on pass/fail, and
51/72 scores landed exactly on the slider defaults, so the review
largely corroborates the auto scores rather than independently
replicating them. Full data: `results/m8-human-review.json`.

| | Condition A | Condition B |
|---|-------------|-------------|
| Mean quality (human) | 74.33 | 76.67 |
| Passed (≥70) | 26/36 (72.2%) | 26/36 (72.2%) |
| Repeat tickets passed | 46.2% | **66.7%** |
| First-time tickets passed | **81.8%** | 66.7% |
| Mean tokens / ticket | 2,037 | 3,020 |

### Headline finding: memory buys repeat quality, not token savings

The original hypothesis (condition B saves 35–55% tokens per ticket)
is **reversed** on the data. On tickets that pass quality in *both*
conditions, B uses **41% more tokens** (2,887 vs 2,047). What B buys is
repeat quality: on repeat tickets the human pass rate is 66.7% vs
46.2% for A, at a token cost. "Never solve it twice" holds for quality
on repeats — not for the token bill.

## Layout

```
app/
  agents.py       Triage + Specialist (deterministic loop; LLM only plans)
  factory.py      client construction from connector CLIs (CLI + server share it)
  harness.py      A/B replay, protocol enforcement, auto quality proxy, HITL
  hitl.py         human approval queue + audit log
  kb.py           local KB retriever (condition A baseline)
  llm.py          Gemini client + deterministic StubLLM (test double)
  meko_client.py  real Meko MCP client + FakeMeko + NullMeko (test doubles)
  metrics.py      metrics M1–M10, aggregation, summary CSV
  mock_orderloop.py  in-process OrderLoop world (state, fix ops, verification)
  server.py       FastAPI demo: inbox, live trace, HITL queue, metrics
data/
  tickets.jsonl   36 synthetic tickets (8 clusters x 3, 3 distractors, 9 unique)
  kb/kb-01..12.md 12 knowledge-base articles
  ground_truth.md rater-only reference (never shown to the agent)
scripts/
  run_experiment.py  CLI harness
  seed_kb.py         upload the 12 KB articles to a Meko datapack (REST)
  make_charts.py     A vs B charts from run summaries
tests/            pytest suite (dataset, mock, harness protocol, meko, stub)
docs/
  ARCHITECTURE.md  system design
  METHODOLOGY.md   experiment design, metrics, threats to validity
  MEKO_USAGE.md    how Meko is used (tools, datapacks, quotas)
results/
  run-A1|A2|A3|B1|B2|B3/  official run data (.jsonl, summary, HITL queue)
  m8-human-review.json   human-review sample results (AI-assisted)
render.yaml       Render Blueprint (free-tier web service)
```

## Metrics (M1–M10)

M1 wall-clock · M2 tokens in · M3 tokens out · M4 total tokens ·
M5 steps · M6 tool calls · M7 retrieval (hit / miss / correct abstention /
false reuse) · M8 quality (rubric 0–100; automatic proxy for smoke tests,
AI-assisted human review for official runs) · M9 escalation · M10 estimated cost.

## Rules that are load-bearing

- Ground truth is never readable by the agent — only ticket + KB + HITL-formed memory.
- Condition B does exactly **one** `context_search` per ticket, before any fix op.
- Only human-approved fixes become memory. Agents never approve their own.
- 3 runs per condition; run 1 is the headline, runs 2–3 are replication.
- Hit rate < 70% → savings are not presented as a "memory effect".

## Credentials

No API keys, tokens, or private keys are in this repo — ever. The real
Meko/Gemini clients call registered connector CLIs that hold keys in a
Secure Vault; on any machine without them the factory falls back loudly
to the stub LLM + FakeMeko. See `.env.example`.

## License

MIT (see LICENSE).
