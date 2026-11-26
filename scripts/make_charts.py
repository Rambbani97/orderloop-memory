#!/usr/bin/env python3
"""Render the A vs B comparison charts from run summaries.

Reads ``results/run-A*-summary.json`` and ``results/run-B*-summary.json`` and
writes PNG charts to ``docs/charts/`` (created if missing):

- tokens_repeat.png — mean total tokens per ticket, repeat group, A vs B
- time_repeat.png — mean wall-clock seconds, repeat group, A vs B
- quality.png — mean quality score by group, A vs B
- hit_rate.png — retrieval hit rate (repeat) + correct abstention (distractor)

Usage:
    python scripts/make_charts.py
    python scripts/make_charts.py --results results --out docs/charts
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.factory import PROJECT_ROOT


def load_summaries(results_dir: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(results_dir.glob("run-*-summary.json")):
        out[path.stem.replace("run-", "").replace("-summary", "")] = json.loads(
            path.read_text(encoding="utf-8"))
    return out


def _bar(ax, labels, a_vals, b_vals, title, ylabel):
    import numpy as np

    x = np.arange(len(labels))
    width = 0.35
    ax.bar(x - width / 2, a_vals, width, label="A — no memory")
    ax.bar(x + width / 2, b_vals, width, label="B — with Meko memory")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.legend()
    for bars in ax.containers:
        ax.bar_label(bars, fmt="%.1f", padding=2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render A vs B charts")
    parser.add_argument("--results", default=str(PROJECT_ROOT / "results"))
    parser.add_argument("--out", default=str(PROJECT_ROOT / "docs" / "charts"))
    args = parser.parse_args()

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    summaries = load_summaries(Path(args.results))
    a_runs = {k: v for k, v in summaries.items() if k.startswith("A")}
    b_runs = {k: v for k, v in summaries.items() if k.startswith("B")}
    if not a_runs or not b_runs:
        print("Need at least one A summary and one B summary in results/. "
              f"Found: {sorted(summaries)}", file=sys.stderr)
        return 2
    # Headline run = run 1 of each condition; replication runs averaged later.
    a = a_runs.get("A1") or next(iter(a_runs.values()))
    b = b_runs.get("B1") or next(iter(b_runs.values()))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    def group_mean(summary: dict, group: str, key: str, sub: str = "mean") -> float:
        g = summary.get(group, {})
        val = g.get(key, {})
        return float(val.get(sub, 0)) if isinstance(val, dict) else float(val or 0)

    groups = ["first-time", "repeat", "distractor", "unique"]

    # Tokens (repeat group is the headline proof)
    fig, ax = plt.subplots(figsize=(7, 4))
    _bar(ax, ["repeat"], [group_mean(a, "repeat", "m4_total_tokens")],
         [group_mean(b, "repeat", "m4_total_tokens")],
         "Mean total tokens per ticket — repeat tickets", "tokens")
    fig.tight_layout()
    fig.savefig(out_dir / "tokens_repeat.png", dpi=150)
    plt.close(fig)

    # Time
    fig, ax = plt.subplots(figsize=(7, 4))
    _bar(ax, ["repeat"], [group_mean(a, "repeat", "m1_seconds")],
         [group_mean(b, "repeat", "m1_seconds")],
         "Mean wall-clock seconds — repeat tickets", "seconds")
    fig.tight_layout()
    fig.savefig(out_dir / "time_repeat.png", dpi=150)
    plt.close(fig)

    # Quality by group
    fig, ax = plt.subplots(figsize=(8, 4))
    _bar(ax, groups,
         [group_mean(a, g, "m8_quality_auto") for g in groups],
         [group_mean(b, g, "m8_quality_auto") for g in groups],
         "Mean quality score (auto proxy) by group", "score 0–100")
    fig.tight_layout()
    fig.savefig(out_dir / "quality.png", dpi=150)
    plt.close(fig)

    # Retrieval
    fig, ax = plt.subplots(figsize=(7, 4))
    hit_a = a.get("repeat", {}).get("hit_rate") or 0
    hit_b = b.get("repeat", {}).get("hit_rate") or 0
    abst_a = a.get("distractor", {}).get("abstention_rate") or 0
    abst_b = b.get("distractor", {}).get("abstention_rate") or 0
    _bar(ax, ["hit rate (repeat)", "correct abstention (distractor)"],
         [hit_a * 100, abst_a * 100], [hit_b * 100, abst_b * 100],
         "Retrieval behaviour — condition B vs A", "percent")
    fig.tight_layout()
    fig.savefig(out_dir / "hit_rate.png", dpi=150)
    plt.close(fig)

    print(f"Charts written to {out_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
