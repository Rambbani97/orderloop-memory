#!/usr/bin/env python3
"""Add Jarvis's per-item verdict (saran_jarvis: Bagus/Kurang) to the simple
72-item sheet, at the user's explicit request.

Source of the verdict: the harness's own auto quality score
(m8_quality_auto, rubric 0-100) for that exact (run, ticket) record.
  auto >= 70 (pass line) -> "Bagus"
  auto <  70             -> "Kurang"
The label is Jarvis's suggestion only. The rater's own score
(skor_total) is the final word and may disagree with the label.

METHODOLOGY NOTE (recorded, not hidden): because the sample sheet now
shows Jarvis's pre-labels, the collected ratings are AI-assisted human
review, NOT a pure blind human rating. The final report must describe
the method that way.
"""
import csv, json
from pathlib import Path

BASE = Path.home() / "workspace/goals/contextcon-hackathon-tema-2-never-solve-it-twice"
RES = BASE / "build/orderloop-memory/results"
items = json.loads((BASE / "files/m8-rating/m8-rating-sample-72.json").read_text())
skey = json.loads((BASE / "hidden_files/m8-rating-sample-key.json").read_text())["mapping"]

auto = {}
for run in ["A1", "A2", "A3", "B1", "B2", "B3"]:
    p = RES / f"run-{run}" / f"run-{run}.jsonl"
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        auto[(run, r["ticket_id"])] = r["m8_quality_auto"]

rows, missing = [], []
for i in items:
    m = skey[i["blind_id"]]
    q = auto.get((m["run"], i["ticket_id"]))
    if q is None:
        missing.append((i["blind_id"], m["run"], i["ticket_id"]))
        continue
    rows.append({"blind_id": i["blind_id"], "saran": "Bagus" if q >= 70 else "Kurang", "auto": q})

assert not missing, missing
assert len(rows) == 72

# rebuild the simple sheet with the new column (same order, same blind_ids)
simple_path = BASE / "files/m8-rating/m8-rating-sample-72-simple.csv"
with open(simple_path, newline="") as f:
    old = list(csv.DictReader(f))
assert [r["blind_id"] for r in old] == [i["blind_id"] for i in items]
saran = {r["blind_id"]: (r["saran"], r["auto"]) for r in rows}
new_fields = ["blind_id", "ticket_id", "subjek_tiket", "isi_tiket", "teks_fix",
              "gt_ringkas", "saran_jarvis", "diagnosis_cocok", "langkah_lengkap",
              "tanpa_ngarang", "skor_total", "catatan"]
with open(simple_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=new_fields)
    w.writeheader()
    for r in old:
        r = dict(r)
        r["saran_jarvis"] = saran[r["blind_id"]][0]
        w.writerow({k: r.get(k, "") for k in new_fields})

from collections import Counter
print("rows:", len(rows))
print("saran:", Counter(r["saran"] for r in rows))
print("auto range:", min(r["auto"] for r in rows), "-", max(r["auto"] for r in rows))
print("near boundary 65-75:", sorted((r["blind_id"], r["auto"]) for r in rows if 65 <= r["auto"] <= 75))
