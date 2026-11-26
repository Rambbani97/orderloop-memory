# Methodology

Experiment design for ContextCon Theme 2. Full dataset rationale is in
`hidden_files/dataset-design.md` (repo-private); this file is the public,
reproducible version.

## Question

Does shared memory (Meko) make a support agent faster, cheaper and
shorter on **repeat** tickets — without losing quality, and without
mis-reusing fixes on look-alike problems?

## Design — A/B, everything locked except memory

| | Condition A | Condition B |
|---|---|---|
| Memory | none (local KB only) | Meko: 1 `context_search` / ticket |
| LLM | same model, temperature 0 | same model, temperature 0 |
| System prompt | same | same + one memory sentence |
| KB / mock | same 12 articles, same world | same |
| HITL | same queue | same queue |

## Dataset — 36 synthetic OrderLoop tickets

- **8 clusters × 3** — seed → near repeat → far repeat (24 tickets).
  Clusters: Stripe webhook secret rotation (C1), SSO/SAML cert expiry
  (C2), invoice proration/VAT (C3), iOS push lost after update (C4),
  Shopify sync stuck on 429 (C5), dashboard timeout on >90-day ranges
  (C6), CSV import encoding (C7), 2FA recovery codes (C8).
- **3 near-miss distractors** (D-01–D-03) — same symptoms as C1/C2/C5,
  different root cause. The correct behaviour is *abstention*.
- **9 unique tickets** (U-01–U-09) — no memory exists for them; they
  measure whether memory hurts first-time solving.

Channels: email 17, chat/Slack/X 16, form 3. Difficulty: easy 12,
medium 18, hard 6. Tickets carry deliberate editorial variation —
typos, abbreviations, different phrasings of the same problem — so
retrieval cannot rely on exact wording.

Ground truth (`root_cause`, `correct_fix`) lives in
`data/ground_truth.md` and in the ticket file's hidden fields. It is
**never** readable by the agent — only by `verify_fix()` and the
automatic scorer.

## Metrics M1–M10

| # | Metric | Definition |
|---|---|---|
| M1 | Wall-clock | seconds per ticket |
| M2 | Tokens in | LLM prompt tokens |
| M3 | Tokens out | LLM completion tokens |
| M4 | Total tokens | M2 + M3 |
| M5 | Steps | mock operations executed |
| M6 | Tool calls | count by tool/op |
| M7 | Retrieval | hit / miss / correct abstention / false reuse |
| M8 | Quality | rubric 0–100, pass ≥ 70 |
| M9 | Escalation | escalated to human, with reason |
| M10 | Cost | estimated USD (list price; $0 on free tiers) |

**M8 — two versions.** The automatic proxy (`score_auto` in the
harness: diagnosis 30 + steps 40 + hallucination 20 + tone 10, +5 if
verified) is for smoke tests and iteration only. Official quality is a
**human review of a 72-item stratified sample** (12 per run, 36 A +
36 B), rated by one human reviewer against `data/ground_truth.md`.
The review was **AI-assisted, not blind**: the reviewer saw Jarvis's
binary pre-label per item ("Tinggi"/"Rendah", derived from the auto
score) with the slider pre-set to 85/45, so it corroborates the auto
scores (pass/fail agreement 71/72) rather than independently
replicating them. Report it as AI-assisted human review — never as
blind human rating, and never report M8-auto as the official quality
number. Results: `results/m8-human-review.json`.

**Definitions.** First-time = seeds + uniques. Repeat = 2nd/3rd ticket
per cluster (16 tickets — the main proof population). Distractors are
analysed separately. Hit rate = repeats whose used memory's `memory_key`
matches the seed id. Abstention = distractors/uniques solved without
reusing a cluster memory.

## Runs

3 runs per condition (6 runs × 36 = 216 resolutions). Run 1 is the
headline; runs 2–3 are replication. **One run alone is never a claim.**
Tickets replay in file order (seeds before their repeats). In condition
B, a seed's fix only becomes memory after a human approves it in the
HITL queue — approve promptly between tickets during official runs,
or repeats in the same run will miss.

## Hypotheses (to test, not claims)

- Δtoken (repeat) −35% to −55% · Δtime −40% to −60% · Δsteps −30% to −50%
- Quality B ≥ A (a regression > 2 points is a problem, not a trade-off)
- Hit rate ≥ 85% · correct abstention ≥ 80% · seed approval rate ≥ 80%
- Break-even at repeat 1–2

**Hard rule:** hit rate < 70% → the savings must not be presented as a
"memory effect" until the retrieval failure is investigated.

## Threats to validity

- **Synthetic data.** Real tickets are messier; the dataset is a
  controlled stand-in, not a claim about production support.
- **Stub LLM ≠ Gemini.** Smoke-test numbers come from a keyword-driven
  stub; official numbers come only from Gemini runs.
- **Small N.** 16 repeat tickets is a small proof population; report
  ranges (min–max), not just means, and never over-claim from run 1.
- **HITL timing.** Manual approval between tickets is an operator
  variable; record approval latency in the run log.
- **Meko retrieval is a black box.** Embedding/reranker internals are
  not published; report match_quality as observed, do not claim a
  mechanism.
- **Cost is list price.** Free-tier runs cost $0; M10 is an estimate
  for the deck, not a bill.
