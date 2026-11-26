#!/usr/bin/env python3
"""Approve/reject pending HITL fixes from the terminal (chat-approval flow).

Usage (from the repo root):

    python scripts/approve_pending.py list
    python scripts/approve_pending.py approve hitl-abc12345
    python scripts/approve_pending.py reject hitl-abc12345 --reason wrong_fix

The run (``scripts/run_experiment.py --hitl-mode manual``, condition B)
waits for a decision on each proposed fix before the next ticket, so a fix
approved here is in Meko before its repeat tickets run.

Logic mirrors the dashboard exactly (``app/server.py`` hitl_approve /
hitl_reject): approve -> ``hitl.approve(item_id, decided_by="human-chat")``
+ ``meko.memory_add`` with ``"approved_by": "human-chat"`` in the metadata;
reject -> ``hitl.reject(item_id, reason, decided_by="human-chat")`` with no
memory_add. Agents never approve their own fixes; this CLI is the human.

The Meko client is built with ``factory.build_meko("B")`` (the key lives
in the Secure Vault and is used only via the registered connector CLI —
never from env, files, arguments or logs). The memory is written to the
same datapack as the run: run this script with the same MEKO_DATAPACK_ID
as the run, or pass --datapack. ``--meko fake`` uses the in-memory test
double (tests only, no cloud quota).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.factory import PROJECT_ROOT, build_meko
from app.hitl import HITLQueue, REJECT_REASONS

PREVIEW_CHARS = 200


def _queue(results_dir: str | Path) -> HITLQueue:
    return HITLQueue(Path(results_dir) / "hitl_queue.json")


def cmd_list(queue: HITLQueue) -> int:
    """Print pending items: item_id, ticket_id, cluster, first 200 chars."""
    pending = queue.pending()
    if not pending:
        print("No pending items.")
        return 0
    for item in pending:
        print(f"{item.item_id} | {item.ticket_id} | {item.cluster}")
        print(f"  {item.memory_text[:PREVIEW_CHARS]}")
    print(f"{len(pending)} pending.")
    return 0


def cmd_approve(queue: HITLQueue, item_id: str, meko) -> int:
    """Approve + write the fix to Meko (mirrors the dashboard endpoint)."""
    item = queue.approve(item_id, decided_by="human-chat")
    if item is None:
        print(f"error: no pending item {item_id}", file=sys.stderr)
        return 2
    meko.memory_add(item.memory_text,
                    {**item.metadata, "approved_by": "human-chat"},
                    agent_id="orderloop-triage")
    print(f"approved {item_id} ({item.ticket_id}) — fix written to Meko")
    return 0


def cmd_reject(queue: HITLQueue, item_id: str, reason: str) -> int:
    """Reject with a reason; nothing is written to Meko."""
    try:
        item = queue.reject(item_id, reason, decided_by="human-chat")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if item is None:
        print(f"error: no pending item {item_id}", file=sys.stderr)
        return 2
    print(f"rejected {item_id} ({item.ticket_id}) — reason: {reason}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Approve/reject pending HITL fixes (chat-approval flow)")
    parser.add_argument("--results-dir", default=str(PROJECT_ROOT / "results"),
                        help="directory holding hitl_queue.json")
    parser.add_argument("--meko", default=os.environ.get("ORDERLOOP_MEKO", "auto"),
                        choices=["auto", "real", "fake"],
                        help="Meko client kind (fake = in-memory test double)")
    parser.add_argument("--datapack", default=None,
                        help="datapack id to write to (default: MEKO_DATAPACK_ID)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show pending fixes")
    p_approve = sub.add_parser("approve", help="approve a fix into memory")
    p_approve.add_argument("item_id")
    p_reject = sub.add_parser("reject", help="reject a fix (no memory write)")
    p_reject.add_argument("item_id")
    p_reject.add_argument("--reason", required=True, choices=REJECT_REASONS)
    args = parser.parse_args(argv)

    queue = _queue(args.results_dir)
    if args.command == "list":
        return cmd_list(queue)
    if args.command == "reject":
        return cmd_reject(queue, args.item_id, args.reason)
    # approve: build the Meko client only now (list/reject never touch Meko).
    if args.datapack:
        os.environ["MEKO_DATAPACK_ID"] = args.datapack
    meko = build_meko("B", args.meko)
    return cmd_approve(queue, args.item_id, meko)


if __name__ == "__main__":
    raise SystemExit(main())
