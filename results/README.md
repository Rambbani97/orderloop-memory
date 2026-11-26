# results/

Official experiment data (ContextCon Theme 2, 26 Nov 2026).

- `run-A1/`, `run-A2/`, `run-A3/` — condition A (no memory), 36 tickets each.
- `run-B1/`, `run-B2/`, `run-B3/` — condition B (Meko shared memory), 36 tickets each.
- Each run dir: `run-<id>.jsonl` (one record per ticket, with trace),
  `run-<id>-summary.json` / `.csv` (aggregated metrics),
  `hitl_queue.json` (the 17 proposed fixes and their human decisions;
  condition A queues stay pending by design — A never writes memory).
- `m8-human-review.json` — the 72-item human-review sample (AI-assisted,
  not blind; see README).
- `spike-2026-11-26/spike-report.json` — pre-run spike proving cross-agent
  memory reuse works.

NOT in this repo (kept out deliberately): top-level `run-A1.jsonl` /
`run-B1.jsonl` and `run-A1-summary.*` / `run-B1-summary.*` (pre-run stub
smoke-test artifacts, m1 ~0.001s), `run-A1-partial-503*` (crash partials
from Gemini 503s, superseded by the resumed official A1), `run-B0.jsonl`
(spike test run).
