#!/usr/bin/env python3
"""Unblind + analyze the 72-item M8 sample ratings (widget v2 state).

Inputs: widget scores (read 26 Nov ~12:57, all 72), sample key,
run JSONLs (auto scores + token counts).
Outputs: hidden_files/m8-rating-results.json + printed summary.
"""
import json, statistics
from collections import defaultdict
from pathlib import Path

BASE = Path.home() / "workspace/goals/contextcon-hackathon-tema-2-never-solve-it-twice"
RES = BASE / "build/orderloop-memory/results"

SCORES = {"S-001":70,"S-002":90,"S-003":85,"S-004":90,"S-005":85,"S-006":85,"S-007":85,"S-008":90,"S-009":90,"S-010":95,"S-011":85,"S-012":85,"S-013":85,"S-014":87,"S-015":100,"S-016":85,"S-017":45,"S-018":45,"S-019":85,"S-020":85,"S-021":45,"S-022":85,"S-023":90,"S-024":100,"S-025":40,"S-026":45,"S-027":45,"S-028":85,"S-029":85,"S-030":85,"S-031":95,"S-032":90,"S-033":85,"S-034":45,"S-035":85,"S-036":85,"S-037":45,"S-038":99,"S-039":85,"S-040":45,"S-041":89,"S-042":85,"S-043":40,"S-044":85,"S-045":85,"S-046":91,"S-047":85,"S-048":45,"S-049":45,"S-050":85,"S-051":85,"S-052":85,"S-053":85,"S-054":45,"S-055":85,"S-056":45,"S-057":100,"S-058":45,"S-059":45,"S-060":85,"S-061":90,"S-062":45,"S-063":45,"S-064":90,"S-065":85,"S-066":45,"S-067":85,"S-068":95,"S-069":85,"S-070":45,"S-071":85,"S-072":85}
assert len(SCORES) == 72

skey = json.loads((BASE / "hidden_files/m8-rating-sample-key.json").read_text())["mapping"]

auto, tokens = {}, {}
for run in ["A1", "A2", "A3", "B1", "B2", "B3"]:
    for line in (RES / f"run-{run}" / f"run-{run}.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            auto[(run, r["ticket_id"])] = r["m8_quality_auto"]
            tokens[(run, r["ticket_id"])] = r["m4_total_tokens"]

rows = []
for sid, score in SCORES.items():
    m = skey[sid]
    q = auto[(m["run"], m["ticket_id"])]
    rows.append({"blind_id": sid, "run": m["run"], "condition": m["condition"],
                 "ticket_id": m["ticket_id"], "cluster": m["cluster"], "kind": m["kind"],
                 "human": score, "auto": q, "tokens": tokens[(m["run"], m["ticket_id"])]})
rows.sort(key=lambda r: (r["condition"], r["run"], r["ticket_id"]))

def stats(rs):
    h = [r["human"] for r in rs]
    return {"n": len(rs), "mean": round(statistics.mean(h), 2),
            "median": statistics.median(h),
            "pass_n": sum(1 for v in h if v >= 70),
            "pass_rate": round(sum(1 for v in h if v >= 70) / len(h), 3) if h else None,
            "mean_tokens": round(statistics.mean([r["tokens"] for r in rs]), 1) if rs else None}

out = {"n": 72, "method": "AI-assisted human review (Jarvis pre-labels Tinggi/Rendah visible; slider pre-set 85/45)",
       "by_condition": {c: stats([r for r in rows if r["condition"] == c]) for c in "AB"},
       "by_run": {run: stats([r for r in rows if r["run"] == run]) for run in ["A1", "A2", "A3", "B1", "B2", "B3"]},
       "by_cluster_condition": {},
       "by_kind_condition": {},
       "anchoring": {}, "pass_both": {}, "rows": rows}

for cl in sorted({r["cluster"] for r in rows}):
    for c in "AB":
        rs = [r for r in rows if r["cluster"] == cl and r["condition"] == c]
        if rs:
            out["by_cluster_condition"][f"{cl}/{c}"] = stats(rs)
for k in sorted({r["kind"] for r in rows}):
    for c in "AB":
        rs = [r for r in rows if r["kind"] == k and r["condition"] == c]
        if rs:
            out["by_kind_condition"][f"{k}/{c}"] = stats(rs)

# anchoring: how often did the human score equal the slider default (85/45)?
defaults = sum(1 for r in rows if r["human"] in (85, 45))
diffs = [abs(r["human"] - r["auto"]) for r in rows]
agree_pass = sum(1 for r in rows if (r["human"] >= 70) == (r["auto"] >= 70))
out["anchoring"] = {"scores_at_default_85_or_45": defaults, "share": round(defaults / 72, 3),
                    "mean_abs_diff_human_auto": round(statistics.mean(diffs), 2),
                    "pass_agreement_with_auto": f"{agree_pass}/72"}

# pass-in-both-conditions (sample): tickets with >=1 A and >=1 B rating
by_ticket = defaultdict(lambda: {"A": [], "B": []})
for r in rows:
    by_ticket[r["ticket_id"]][r["condition"]].append(r["human"])
both, a_only, b_only, neither = [], [], [], []
n_both_conditions = 0
for t, d in by_ticket.items():
    if not d["A"] or not d["B"]:
        continue
    n_both_conditions += 1
    pa, pb = any(v >= 70 for v in d["A"]), any(v >= 70 for v in d["B"])
    (both if pa and pb else a_only if pa else b_only if pb else neither).append(t)
out["pass_both"] = {"tickets_in_sample": len(by_ticket),
                    "tickets_with_both_conditions": n_both_conditions,
                    "pass_both": len(both), "pass_A_only": len(a_only),
                    "pass_B_only": len(b_only), "pass_neither": len(neither)}
# token comparison restricted to pass-both tickets (mean tokens per run-record)
if both:
    ta = [tokens[(run, t)] for t in both for run in ["A1", "A2", "A3"] if (run, t) in tokens]
    tb = [tokens[(run, t)] for t in both for run in ["B1", "B2", "B3"] if (run, t) in tokens]
    out["pass_both"]["mean_tokens_A_pass_both_tickets"] = round(statistics.mean(ta), 1)
    out["pass_both"]["mean_tokens_B_pass_both_tickets"] = round(statistics.mean(tb), 1)
    out["pass_both"]["token_delta_pct_B_vs_A"] = round((statistics.mean(tb) / statistics.mean(ta) - 1) * 100, 1)

(BASE / "hidden_files/m8-rating-results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=2, ensure_ascii=False))
