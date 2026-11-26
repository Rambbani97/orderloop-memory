#!/usr/bin/env python3
"""Run the OrderLoop A/B experiment.

Usage (from the repo root):

    python scripts/run_experiment.py --condition A --run 1 --llm stub --meko null
    python scripts/run_experiment.py --condition B --run 1 --llm stub --meko fake --hitl-mode auto
    python scripts/run_experiment.py --condition B --run 1 --llm gemini --meko real

Credentials come from the registered connector CLIs only
(``custom.meko`` / ``custom.gemini`` — keys live in the Secure Vault, never
in env vars, files, arguments or logs). No key is ever read from a file or printed.

--hitl-mode auto approves every proposed fix immediately. It is TEST-ONLY
(it violates the human-in-the-loop rule) — never use it for official runs.
Official runs use --hitl-mode manual: fixes wait in the queue and a human
approves them via the dashboard (or scripts/approve_pending.py).

Crash-resume: if a run dies mid-way (e.g. Gemini 503), continue it with
--resume (skips tickets already recorded in the run JSONL — detected from
the file, no re-runs, no duplicates; the final summary is regenerated
from the whole JSONL) or --start-from <ticket-id> (skips all earlier
tickets in dataset order). Never re-run a crashed run from scratch into
the same results dir — that would duplicate records.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.factory import PROJECT_ROOT, build_kb, build_llm, build_meko, describe_setup
from app.harness import Harness, load_tickets
from app.hitl import HITLQueue
from app.metrics import write_summary_csv


def _check_resume_rows(harness, parser) -> None:
    """Refuse to resume if the loaded JSONL rows belong to another run."""
    bad = sorted({r.ticket_id for r in harness.recorder.records
                  if r.run_id != harness.run_id})
    if bad:
        parser.error(
            f"JSONL rows belong to another run (run_id != "
            f"{harness.run_id}): {bad} — refusing to resume into the "
            f"wrong results dir")


def main() -> int:
    parser = argparse.ArgumentParser(description="OrderLoop A/B experiment harness")
    parser.add_argument("--condition", required=True, choices=["A", "B"])
    parser.add_argument("--run", type=int, default=1)
    parser.add_argument("--llm", default="auto", choices=["auto", "gemini", "stub"])
    parser.add_argument("--meko", default="auto",
                        choices=["auto", "real", "fake", "null"])
    parser.add_argument("--hitl-mode", default="manual", choices=["manual", "auto"])
    parser.add_argument("--limit", type=int, default=None,
                        help="run only the first N tickets (smoke tests)")
    parser.add_argument("--resume", action="store_true",
                        help="resume a crashed run: skip tickets already "
                             "recorded in the run JSONL (detected from the "
                             "file); the final summary covers the whole file")
    parser.add_argument("--start-from", default=None, metavar="TICKET_ID",
                        help="resume from this ticket id: skip all earlier "
                             "tickets in dataset order")
    parser.add_argument("--results-dir", default=str(PROJECT_ROOT / "results"))
    args = parser.parse_args()

    if args.condition == "A" and args.meko in ("real", "fake"):
        parser.error("condition A never touches Meko — use --meko null (or auto)")
    if args.condition == "B" and args.meko == "null":
        parser.error("condition B needs Meko — use --meko fake (test) or real")
    if args.resume and args.start_from:
        parser.error("--resume and --start-from are mutually exclusive")
    if (args.resume or args.start_from) and args.limit is not None:
        parser.error("cannot combine --limit with --resume/--start-from")

    kb = build_kb()
    llm = build_llm(args.llm)
    meko = build_meko(args.condition, args.meko, kb)
    print("SETUP:", json.dumps(describe_setup(llm, meko)))
    if args.hitl_mode == "auto":
        print("WARNING: --hitl-mode auto is TEST-ONLY (auto-approves fixes). "
              "Never use for official runs.")

    tickets = load_tickets(PROJECT_ROOT / "data" / "tickets.jsonl")
    hitl = HITLQueue(Path(args.results_dir) / "hitl_queue.json")
    harness = Harness(condition=args.condition, run_no=args.run, llm=llm,
                      meko=meko, kb=kb, hitl=hitl, hitl_mode=args.hitl_mode,
                      results_dir=args.results_dir,
                      model=getattr(llm, "model", "stub-llm/1.0"),
                      limit=args.limit)
    # --- crash-resume: compute which tickets are already recorded ------
    # A crashed run always completes a prefix of the dataset in order, so
    # --resume requires exactly that; anything else means the JSONL does
    # not belong to this run (or the dataset changed) — refuse rather
    # than risk duplicates or a silently wrong summary.
    skip_ids: set[str] = set()
    if args.resume:
        completed = harness.recorder.load_existing()
        if not completed:
            parser.error(f"nothing to resume: {harness.recorder.path} "
                         f"has no records")
        _check_resume_rows(harness, parser)
        order = [t["id"] for t in tickets]
        if set(order[:len(completed)]) != completed:
            parser.error(
                f"recorded tickets are not a prefix of the dataset "
                f"(found {sorted(completed)}) — refusing to resume; "
                f"check that the results dir belongs to this run")
        skip_ids = completed
        print(f"RESUME: skipping {len(skip_ids)} already-recorded tickets")
    elif args.start_from:
        ids = [t["id"] for t in tickets]
        if args.start_from not in ids:
            parser.error(f"--start-from {args.start_from} is not a ticket id")
        cut = ids.index(args.start_from)
        skip_ids = set(ids[:cut])
        existing = harness.recorder.load_existing()
        _check_resume_rows(harness, parser)
        overlap = existing - skip_ids
        if overlap:
            parser.error(
                f"JSONL already contains tickets that would be re-run "
                f"({sorted(overlap)}) — refusing to duplicate records")
        print(f"RESUME: skipping {len(skip_ids)} tickets before "
              f"{args.start_from}")
    summary = harness.run(tickets, skip_ids=skip_ids or None)
    write_summary_csv(summary,
                      Path(args.results_dir) / f"run-{harness.run_id}-summary.csv")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
