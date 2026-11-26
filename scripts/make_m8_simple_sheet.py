#!/usr/bin/env python3
"""Build the SIMPLIFIED phone-friendly 72-item rating sheet.

Same 72 rows, same order, same blind_ids (S-001..S-072) as
m8-rating-sample-72.csv — only the columns change:
  - gt_ringkas: ground truth shortened for quick phone reading
    (root cause + first 2 steps of the correct fix)
  - 3 check columns for the rater to fill Ya/Tidak:
    diagnosis_cocok, langkah_lengkap, tanpa_ngarang
  - skor_total: the 0-100 score (follows the check pattern, see guide)
  - catatan: optional
NO per-item score recommendation is included on purpose: a suggested
score would be the builder pre-scoring the item and would break the
blind human rating (M8). The rater judges each check himself.
"""
import csv, json, re
from pathlib import Path

BASE = Path.home() / "workspace/goals/contextcon-hackathon-tema-2-never-solve-it-twice"
items = json.loads((BASE / "files/m8-rating/m8-rating-sample-72.json").read_text())

def ringkas(cause, fix, limit=300):
    steps = re.split(r"\n?\d+\.\s+", fix.strip())
    steps = [s.strip() for s in steps if s.strip()][:2]
    txt = cause.strip() + " | Langkah benar: " + "; ".join(steps)
    return txt if len(txt) <= limit else txt[: limit - 1].rstrip() + "…"

rows = []
for i in items:
    rows.append({
        "blind_id": i["blind_id"],
        "ticket_id": i["ticket_id"],
        "subjek_tiket": i["ticket_subject"],
        "isi_tiket": i["ticket_body"],
        "teks_fix": i["fix_text"],
        "gt_ringkas": ringkas(i["ground_truth_root_cause"], i["ground_truth_correct_fix"]),
        "diagnosis_cocok": "",
        "langkah_lengkap": "",
        "tanpa_ngarang": "",
        "skor_total": "",
        "catatan": "",
    })

out = BASE / "files/m8-rating/m8-rating-sample-72-simple.csv"
with open(out, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

print("wrote", out, len(rows), "rows")
print("cols:", list(rows[0].keys()))
print("blind_ids match sample:", [r["blind_id"] for r in rows] == [i["blind_id"] for i in items])
print("checks empty:", all(not r["diagnosis_cocok"] and not r["skor_total"] for r in rows))
print("gt_ringkas len avg:", sum(len(r["gt_ringkas"]) for r in rows) // len(rows))
