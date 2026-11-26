"""Metrics M1–M10 (dataset-design.md §5.1) and run aggregation.

Every ticket handled by the harness produces one :class:`TicketMetrics`
record, written as JSONL to ``results/run-<condition><n>.jsonl``. The
aggregator produces the summary table used for slides and the dashboard
(means + medians + ranges, per group: first-time / repeat / distractor /
unique), plus Token per Ticket (TPT) for the token-efficiency angle.

Cost (M10) uses the price table below. All entries are $0 on free tiers;
fill in public pay-as-you-go list prices before official runs if M10 must
reflect list price rather than actual spend.
"""

from __future__ import annotations

import csv
import json
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path

# USD per 1k tokens (input, output). $0 = free tier (Gemini free tier, stub).
# TODO (before official runs): fill public list prices here if M10 should
# reflect list price; otherwise M10 stays $0 on the free tier.
PRICES_PER_1K: dict[str, tuple[float, float]] = {
    "gemini-3.5-flash-lite": (0.0, 0.0),
    "stub-llm/1.0": (0.0, 0.0),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    p_in, p_out = PRICES_PER_1K.get(model, (0.0, 0.0))
    return (input_tokens / 1000.0) * p_in + (output_tokens / 1000.0) * p_out


@dataclass
class TicketMetrics:
    run_id: str
    condition: str  # "A" | "B"
    run_no: int
    ticket_id: str
    cluster: str
    kind: str  # first-time | repeat | distractor | unique
    agent: str
    # M1–M10
    m1_seconds: float
    m2_input_tokens: int
    m3_output_tokens: int
    m4_total_tokens: int
    m5_steps: int
    m6_tool_calls: dict
    m7_retrieval: str  # hit | miss | correct_abstention | false_reuse | na
    m8_quality_auto: float
    m8_quality_breakdown: dict
    m9_escalated: bool
    m9_escalation_reason: str
    m10_cost_usd: float
    # extras
    protocol_violation: bool = False
    verified: bool = False
    verify_checks: dict = field(default_factory=dict)
    used_memory: bool = False
    memory_id: str | None = None
    hitl_status: str = ""  # approved | rejected | pending | not_proposed
    model: str = ""
    temperature: float = 0.0
    datapack_id: str = ""
    timestamp: str = ""
    trace: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class MetricsRecorder:
    """Append-only JSONL recorder for one run."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.records: list[TicketMetrics] = []

    def record(self, metrics: TicketMetrics) -> None:
        self.records.append(metrics)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(metrics.to_dict(), ensure_ascii=False) + "\n")

    def load_existing(self) -> set[str]:
        """Load records already in the JSONL file (crash-resume).

        Replaces ``self.records`` with the file contents and returns the
        ticket ids found. A missing file yields an empty set. Rows are
        reconstructed with :class:`TicketMetrics` (``to_dict`` round-trips
        exactly). Callers validate that the rows belong to this run.
        """
        self.records = []
        if not self.path.exists():
            return set()
        ids: set[str] = set()
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = TicketMetrics(**json.loads(line))
                self.records.append(rec)
                ids.add(rec.ticket_id)
        return ids

    # ------------------------------------------------------------------
    def summarize(self) -> dict:
        """Aggregate per group + overall. Means, medians, ranges."""
        groups: dict[str, list[TicketMetrics]] = {}
        for rec in self.records:
            groups.setdefault(rec.kind, []).append(rec)
        groups["all"] = list(self.records)

        def agg(recs: list[TicketMetrics]) -> dict:
            if not recs:
                return {"n": 0}
            def stats(vals: list[float]) -> dict:
                return {"mean": round(statistics.mean(vals), 2),
                        "median": round(statistics.median(vals), 2),
                        "min": round(min(vals), 2), "max": round(max(vals), 2)}
            passed = [r for r in recs if r.m8_quality_auto >= 70]
            return {
                "n": len(recs),
                "n_passed_quality": len(passed),
                "m1_seconds": stats([r.m1_seconds for r in recs]),
                "m4_total_tokens": stats([r.m4_total_tokens for r in recs]),
                "m5_steps": stats([float(r.m5_steps) for r in recs]),
                "m8_quality_auto": stats([r.m8_quality_auto for r in recs]),
                "m10_cost_usd": round(sum(r.m10_cost_usd for r in recs), 4),
                "hit_rate": _rate([r for r in recs if r.m7_retrieval in ("hit", "miss")],
                                  lambda r: r.m7_retrieval == "hit"),
                "abstention_rate": _rate(
                    [r for r in recs if r.m7_retrieval in ("correct_abstention", "false_reuse")],
                    lambda r: r.m7_retrieval == "correct_abstention"),
                "escalation_rate": _rate(recs, lambda r: r.m9_escalated),
                "verified_rate": _rate(recs, lambda r: r.verified),
                "protocol_violations": sum(1 for r in recs if r.protocol_violation),
                # Token per Ticket terselesaikan (passed quality only)
                "tpt_passed": (round(sum(r.m4_total_tokens for r in passed) / len(passed), 1)
                               if passed else None),
            }
        return {name: agg(recs) for name, recs in groups.items()}


def _rate(recs: list, pred) -> float | None:
    if not recs:
        return None
    return round(sum(1 for r in recs if pred(r)) / len(recs), 3)


def write_summary_csv(summary: dict, path: str | Path) -> None:
    """One row per group: the table that feeds slides and the dashboard."""
    rows = []
    for group, agg in summary.items():
        if agg.get("n", 0) == 0:
            continue
        rows.append({
            "group": group,
            "n": agg["n"],
            "n_passed_quality": agg["n_passed_quality"],
            "m1_seconds_mean": agg["m1_seconds"]["mean"],
            "m1_seconds_median": agg["m1_seconds"]["median"],
            "m4_tokens_mean": agg["m4_total_tokens"]["mean"],
            "m4_tokens_median": agg["m4_total_tokens"]["median"],
            "m5_steps_mean": agg["m5_steps"]["mean"],
            "m8_quality_mean": agg["m8_quality_auto"]["mean"],
            "tpt_passed": agg["tpt_passed"],
            "hit_rate": agg["hit_rate"],
            "abstention_rate": agg["abstention_rate"],
            "escalation_rate": agg["escalation_rate"],
            "verified_rate": agg["verified_rate"],
            "protocol_violations": agg["protocol_violations"],
            "m10_cost_usd_total": agg["m10_cost_usd"],
        })
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)
