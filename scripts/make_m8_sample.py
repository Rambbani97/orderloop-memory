#!/usr/bin/env python3
"""Build stratified 72-item blind sample from the 216-item M8 rating pack.

Strata (per run, 12 items -> 72 total):
  - repeat clusters C1..C8: 1 ticket per cluster (8)
  - distractor: 1 of D-01..D-03 (1)
  - unique: 3 of U-01..U-09 (3)
Balanced A/B by construction (12 per run x 6 runs = 36 A + 36 B).
New blind ids S-001..S-072, shuffled. No run/condition labels in outputs.
Sample key (S-* -> run/condition + original blind_id) goes to a SEPARATE
hidden file, never into the sample files.
"""
import json, random, csv, sys
from pathlib import Path

BASE = Path.home() / "workspace/goals/contextcon-hackathon-tema-2-never-solve-it-twice"
PKG = BASE / "files/m8-rating/m8-rating-package.json"
KEY = BASE / "hidden_files/m8-rating-key.json"
SEED = 20261172

pkg = json.loads(PKG.read_text())
items = pkg if isinstance(pkg, list) else pkg.get("items", pkg.get("rows", []))
key = json.loads(KEY.read_text())
mapping = key["mapping"]

# attach run/condition/cluster from key (key is the only place that has them)
by_run = {}
for it in items:
    m = mapping[it["blind_id"]]
    it = dict(it)
    it["_run"] = m["run"]
    it["_condition"] = m["condition"]
    it["_cluster"] = m.get("cluster", "")
    it["_kind"] = m.get("kind", "")
    by_run.setdefault(m["run"], []).append(it)

rng = random.Random(SEED)
sample = []
for run in ["A1", "A2", "A3", "B1", "B2", "B3"]:
    pool = by_run[run]
    repeat = [i for i in pool if i["_kind"] in ("repeat", "first-time") or i["_cluster"].startswith("C")]
    # repeat clusters C1..C8: exactly 1 ticket per cluster
    clusters = {}
    for i in repeat:
        clusters.setdefault(i["_cluster"], []).append(i)
    assert sorted(clusters) == [f"C{n}" for n in range(1, 9)], (run, sorted(clusters))
    picked = []
    for c in sorted(clusters):
        picked.append(rng.choice(clusters[c]))
    distractors = [i for i in pool if i["ticket_id"].startswith("D-")]
    uniques = [i for i in pool if i["ticket_id"].startswith("U-")]
    assert len(distractors) == 3 and len(uniques) == 9, (run, len(distractors), len(uniques))
    picked.append(rng.choice(distractors))
    picked.extend(rng.sample(uniques, 3))
    assert len(picked) == 12, (run, len(picked))
    sample.extend(picked)

assert len(sample) == 72
rng.shuffle(sample)

# new blind ids, strip internal fields
out_items = []
sample_key = {"meta": {"warning": "UNBLINDING KEY SAMPEL 72 — jangan dibuka sebelum penilaian selesai.",
                       "shuffle_seed": SEED, "n_items": 72,
                       "design": "12 per run (A1/A2/A3/B1/B2/B3); per run: 1 tiket per repeat cluster C1-C8, 1 distractor, 3 unique"},
              "mapping": {}}
for n, it in enumerate(sample, 1):
    sid = f"S-{n:03d}"
    sample_key["mapping"][sid] = {"run": it["_run"], "condition": it["_condition"],
                                  "ticket_id": it["ticket_id"], "cluster": it["_cluster"],
                                  "kind": it["_kind"], "original_blind_id": it["blind_id"]}
    clean = {k: v for k, v in it.items() if not k.startswith("_")}
    clean["blind_id"] = sid
    # ensure score columns are empty
    for col in ("diagnosis_score", "steps_score", "hallucination_score", "tone_score",
                "bonus_score", "total_score", "notes"):
        clean[col] = ""
    out_items.append(clean)

out_dir = BASE / "files/m8-rating"
(out_dir / "m8-rating-sample-72.json").write_text(json.dumps(out_items, indent=2, ensure_ascii=False) + "\n")
with open(out_dir / "m8-rating-sample-72.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(out_items[0].keys()))
    w.writeheader()
    w.writerows(out_items)
(BASE / "hidden_files/m8-rating-sample-key.json").write_text(
    json.dumps(sample_key, indent=2, ensure_ascii=False) + "\n")

# verification (printed, no secrets beyond counts)
from collections import Counter
print("total:", len(out_items))
print("per run:", Counter(sample_key["mapping"][s]["run"] for s in sample_key["mapping"]))
print("per condition:", Counter(sample_key["mapping"][s]["condition"] for s in sample_key["mapping"]))
print("per kind:", Counter(sample_key["mapping"][s]["kind"] for s in sample_key["mapping"]))
print("per cluster:", Counter(sample_key["mapping"][s]["cluster"] for s in sample_key["mapping"]))
print("unique blind_ids:", len({i['blind_id'] for i in out_items}))
print("score cols empty:", all(not i["total_score"] for i in out_items))
# leakage check: no run/condition labels in output files
for p in ("m8-rating-sample-72.csv", "m8-rating-sample-72.json"):
    txt = (out_dir / p).read_text()
    leak = [t for t in ('"A1"', '"A2"', '"A3"', '"B1"', '"B2"', '"B3"', "condition") if t in txt]
    print(p, "leak markers:", leak or "none")
print("text_source:", Counter(i["text_source"] for i in out_items))
