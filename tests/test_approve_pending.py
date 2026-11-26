"""Chat-approval flow for official runs (26 Nov 2026):

- scripts/approve_pending.py — list / approve / reject the HITL queue
  from the terminal, mirroring the dashboard endpoints exactly
  (approve writes the fix to Meko with "approved_by": "human-chat";
  reject writes nothing).
- Harness wait (manual mode, condition B only): after a ticket proposes
  a fix, run_ticket waits for a human decision on that item — polled
  from disk every 10 s, max 30 min — before the next ticket, so its
  repeats can actually reuse the approved fix. The wait happens after
  the ticket metrics are recorded, so M1 is never contaminated.
- HITLQueue.refresh(): the harness re-reads the queue from disk before
  each propose(), so a decision made by an external approver (this CLI)
  is never reverted to pending by a stale in-memory save.
"""

import threading
import time

import pytest

from app.factory import PROJECT_ROOT, build_kb
from app.harness import (Harness, load_tickets, ticket_kind,
                         wait_for_hitl_decision)
from app.hitl import HITLQueue
from app.llm import StubLLM
from app.meko_client import make_meko_client
from scripts.approve_pending import cmd_approve, cmd_list, cmd_reject, main

_META = {"ticket_id": "T-001", "cluster": "C1", "memory_key": "T-001",
         "source": "agent", "agent": "orderloop-triage", "run_id": "B99"}
_FIX = ("FIX [C1 — Stripe webhooks stopped working after we rotated our "
        "API keys]\nDiagnosis: rotate the webhook signing secret.\n"
        "Steps:\n1. Rotate the secret.\nVerified in mock: resolved=True\n"
        "Source ticket: T-001")


def _queue_with_fix(tmp_path):
    queue = HITLQueue(tmp_path / "hitl_queue.json")
    item = queue.propose("T-001", "C1", _FIX, dict(_META))
    return queue, item


def _fake_meko():
    return make_meko_client("B", "fake", None, build_kb())


def _memory_add_calls(meko):
    return [c for c in meko.calls if c["tool"] == "memory_add"]


# ---------------------------------------------------------------------------
# CLI helpers (approve / reject / list)
# ---------------------------------------------------------------------------

def test_approve_writes_memory_add_via_fake(tmp_path):
    queue, item = _queue_with_fix(tmp_path)
    meko = _fake_meko()
    assert cmd_approve(queue, item.item_id, meko) == 0
    # Queue file on disk says approved (re-read, like the harness does).
    assert HITLQueue(tmp_path / "hitl_queue.json").pending() == []
    adds = _memory_add_calls(meko)
    assert len(adds) == 1
    assert meko.memories[0]["text"] == _FIX
    assert meko.memories[0]["metadata"]["approved_by"] == "human-chat"
    assert meko.memories[0]["metadata"]["ticket_id"] == "T-001"


def test_approve_unknown_item_errors_without_memory_write(tmp_path):
    queue, _ = _queue_with_fix(tmp_path)
    meko = _fake_meko()
    assert cmd_approve(queue, "hitl-nope", meko) == 2
    assert _memory_add_calls(meko) == []
    assert len(queue.pending()) == 1  # the real item is untouched


def test_approve_twice_second_fails_and_writes_once(tmp_path):
    queue, item = _queue_with_fix(tmp_path)
    meko = _fake_meko()
    assert cmd_approve(queue, item.item_id, meko) == 0
    assert cmd_approve(queue, item.item_id, meko) == 2
    assert len(_memory_add_calls(meko)) == 1


def test_reject_writes_no_memory(tmp_path):
    queue, item = _queue_with_fix(tmp_path)
    meko = _fake_meko()
    assert cmd_reject(queue, item.item_id, "wrong_fix") == 0
    assert _memory_add_calls(meko) == []
    fresh = HITLQueue(tmp_path / "hitl_queue.json")
    assert fresh.pending() == []
    decided = [i for i in fresh.items if i.item_id == item.item_id][0]
    assert decided.status == "rejected"
    assert decided.reject_reason == "wrong_fix"
    assert decided.decided_by == "human-chat"


def test_reject_unknown_item_errors(tmp_path):
    queue, _ = _queue_with_fix(tmp_path)
    assert cmd_reject(queue, "hitl-nope", "other") == 2


# ---------------------------------------------------------------------------
# CLI end-to-end via main() — fake mode only, never the real Meko client
# ---------------------------------------------------------------------------

def test_cli_list_approve_list(tmp_path, capsys):
    queue, item = _queue_with_fix(tmp_path)
    queue.propose("T-004", "C2", "FIX [C2] another fix", dict(_META))
    assert main(["--results-dir", str(tmp_path), "list"]) == 0
    out = capsys.readouterr().out
    assert item.item_id in out and "T-001" in out and "C1" in out
    assert "2 pending." in out

    assert main(["--results-dir", str(tmp_path), "--meko", "fake",
                 "approve", item.item_id]) == 0
    capsys.readouterr()  # drain the "approved ..." confirmation line
    assert main(["--results-dir", str(tmp_path), "list"]) == 0
    out = capsys.readouterr().out
    assert f"{item.item_id} | T-001 | C1" not in out  # no longer listed
    assert "T-004" in out and "1 pending." in out


def test_cli_list_empty(tmp_path, capsys):
    assert main(["--results-dir", str(tmp_path), "list"]) == 0
    assert "No pending items." in capsys.readouterr().out


def test_cli_reject_bad_reason_exits_2(tmp_path):
    _, item = _queue_with_fix(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["--results-dir", str(tmp_path), "reject", item.item_id,
              "--reason", "not_a_reason"])
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# wait_for_hitl_decision (disk polling)
# ---------------------------------------------------------------------------

def _decide_later(path, item_id, delay, decide):
    """Simulate the chat approver: a separate process deciding from disk."""
    def _run():
        time.sleep(delay)
        decide(HITLQueue(path), item_id)
    threading.Thread(target=_run, daemon=True).start()


def test_wait_returns_when_decided(tmp_path):
    _, item = _queue_with_fix(tmp_path)
    _decide_later(tmp_path / "hitl_queue.json", item.item_id, 0.05,
                  lambda q, i: q.approve(i, decided_by="human-chat"))
    started = time.monotonic()
    assert wait_for_hitl_decision(tmp_path / "hitl_queue.json", item.item_id,
                                  timeout_s=5, poll_interval_s=0.02) == "approved"
    assert time.monotonic() - started < 2  # did not wait out the timeout


def test_wait_returns_rejected(tmp_path):
    _, item = _queue_with_fix(tmp_path)
    _decide_later(tmp_path / "hitl_queue.json", item.item_id, 0.05,
                  lambda q, i: q.reject(i, "duplicate", decided_by="human-chat"))
    assert wait_for_hitl_decision(tmp_path / "hitl_queue.json", item.item_id,
                                  timeout_s=5, poll_interval_s=0.02) == "rejected"


def test_wait_times_out(tmp_path):
    _, item = _queue_with_fix(tmp_path)
    started = time.monotonic()
    assert wait_for_hitl_decision(tmp_path / "hitl_queue.json", item.item_id,
                                  timeout_s=0.05, poll_interval_s=0.01) == "timeout"
    assert time.monotonic() - started < 1
    # Still pending on disk: the timeout only skips the wait, it decides nothing.
    assert len(HITLQueue(tmp_path / "hitl_queue.json").pending()) == 1


def test_wait_missing_item(tmp_path):
    assert wait_for_hitl_decision(tmp_path / "hitl_queue.json", "hitl-nope",
                                  timeout_s=5, poll_interval_s=0.01) == "missing"


# ---------------------------------------------------------------------------
# Harness: wait placement + refresh-before-propose
# ---------------------------------------------------------------------------

def _manual_harness(condition, tmp_path, timeout_s=0.3, wait=True):
    kb = build_kb()
    meko = make_meko_client(condition, "fake" if condition == "B" else "null",
                            None, kb)
    hitl = HITLQueue(tmp_path / "hitl_queue.json")
    harness = Harness(condition=condition, run_no=99, llm=StubLLM(), meko=meko,
                      kb=kb, hitl=hitl, hitl_mode="manual",
                      hitl_wait=wait,
                      hitl_wait_timeout_s=timeout_s, hitl_wait_poll_s=0.05,
                      results_dir=tmp_path, model="stub-llm/1.0", verbose=False)
    return harness


def _ticket(ticket_id):
    tickets = {t["id"]: t for t in
               load_tickets(PROJECT_ROOT / "data" / "tickets.jsonl")}
    return tickets[ticket_id]


def test_manual_b_waits_and_m1_is_not_contaminated(tmp_path):
    """T-001 proposes a fix in manual B: run_ticket must wait (nobody
    decides) and the recorded M1 must exclude the wait."""
    harness = _manual_harness("B", tmp_path)
    assert ticket_kind(_ticket("T-001")) == "first-time"
    started = time.monotonic()
    rec = harness.run_ticket(_ticket("T-001"))
    wall = time.monotonic() - started
    assert rec.hitl_status == "pending"
    assert wall >= 0.3, f"expected the run to wait, wall={wall:.2f}s"
    assert rec.m1_seconds < wall - 0.2, (
        f"M1 ({rec.m1_seconds}s) must exclude the {wall:.2f}s wait")


def test_manual_a_does_not_wait(tmp_path):
    """Condition A never writes memory, so no decision can unblock
    anything — and the default A smoke command runs in manual mode,
    so it must not hang."""
    harness = _manual_harness("A", tmp_path)
    started = time.monotonic()
    rec = harness.run_ticket(_ticket("T-001"))
    wall = time.monotonic() - started
    assert rec.hitl_status == "pending"
    assert wall < 0.2, f"condition A must not wait, wall={wall:.2f}s"


def test_refresh_before_propose_keeps_external_decision(tmp_path):
    """Race that the chat flow introduces: the CLI approves item-1 from a
    separate process; the harness's next propose() must not _save() the
    stale in-memory list and revert item-1 to pending."""
    harness = _manual_harness("B", tmp_path, wait=False)
    rec1 = harness.run_ticket(_ticket("T-001"))
    assert rec1.hitl_status == "pending"
    item1_id = HITLQueue(tmp_path / "hitl_queue.json").pending()[0].item_id

    # External approver (the chat CLI): separate object, same file.
    assert HITLQueue(tmp_path / "hitl_queue.json").approve(
        item1_id, decided_by="human-chat") is not None

    rec2 = harness.run_ticket(_ticket("T-004"))  # next first-time ticket
    assert rec2.hitl_status == "pending"
    fresh = HITLQueue(tmp_path / "hitl_queue.json")
    by_id = {i.item_id: i for i in fresh.items}
    assert by_id[item1_id].status == "approved", (
        "external approval was reverted by a stale propose() save")
    assert len(fresh.pending()) == 1  # only the T-004 item
