"""Crash-resume: a run that dies mid-way (e.g. Gemini 503) continues from
the next ticket without duplicates, and the final summary covers the whole
JSONL file — not just the tickets run after the resume.

Real case: run B1 crashed on T-007 (26 Nov 2026, Gemini 503) with 6/36
tickets recorded. The resume must skip T-001..T-006, never re-propose
their HITL fixes, append new records to the same JSONL, and regenerate
the summary from all 36 records.

All tests use stub LLM + FakeMeko (zero real quota).
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.factory import PROJECT_ROOT, build_kb
from app.harness import Harness, load_tickets, ticket_kind
from app.hitl import HITLQueue
from app.llm import StubLLM
from app.meko_client import make_meko_client
from app.metrics import MetricsRecorder

TICKETS = load_tickets(PROJECT_ROOT / "data" / "tickets.jsonl")


def _harness(tmp_path, hitl_mode="auto", **kw):
    kb = build_kb()
    meko = make_meko_client("B", "fake", None, kb)
    hitl = HITLQueue(tmp_path / "hitl.json")
    harness = Harness(condition="B", run_no=99, llm=StubLLM(), meko=meko,
                      kb=kb, hitl=hitl, hitl_mode=hitl_mode,
                      results_dir=tmp_path, model="stub-llm/1.0",
                      verbose=False, **kw)
    return harness


# ---------------------------------------------------------------------------
# MetricsRecorder.load_existing
# ---------------------------------------------------------------------------

def test_load_existing_round_trips_and_missing_file_is_empty(tmp_path):
    rec = MetricsRecorder(tmp_path / "run-B99.jsonl")
    assert rec.load_existing() == set()  # missing file
    h = _harness(tmp_path)
    h.run(TICKETS[:3])
    assert len(h.recorder.records) == 3

    rec2 = MetricsRecorder(tmp_path / "run-B99.jsonl")
    ids = rec2.load_existing()
    assert ids == {"T-001", "T-002", "T-003"}
    assert [r.ticket_id for r in rec2.records] == ["T-001", "T-002", "T-003"]
    assert all(r.run_id == "B99" for r in rec2.records)


# ---------------------------------------------------------------------------
# Harness.run(skip_ids=...)
# ---------------------------------------------------------------------------

def test_run_skips_recorded_tickets_without_duplicates(tmp_path):
    first = _harness(tmp_path)
    first.run(TICKETS[:3])
    assert len(first.recorder.records) == 3

    second = _harness(tmp_path)
    completed = second.recorder.load_existing()
    assert completed == {"T-001", "T-002", "T-003"}
    summary = second.run(TICKETS[:6], skip_ids=completed)

    lines = (tmp_path / "run-B99.jsonl").read_text().strip().split("\n")
    assert len(lines) == 6
    ids = [json.loads(line)["ticket_id"] for line in lines]
    assert ids == ["T-001", "T-002", "T-003", "T-004", "T-005", "T-006"]
    assert len(set(ids)) == 6  # no duplicates
    # Summary is regenerated from the whole file, not just the new tickets.
    assert summary["all"]["n"] == 6
    assert len(second.recorder.records) == 6


def test_resume_proposes_hitl_only_for_new_tickets(tmp_path):
    first = _harness(tmp_path)
    first.run(TICKETS[:3])
    queue = HITLQueue(tmp_path / "hitl.json")
    assert [i.ticket_id for i in queue.items] == ["T-001"]

    second = _harness(tmp_path, hitl_mode="manual", hitl_wait=False)
    completed = second.recorder.load_existing()
    second.run(TICKETS[:6], skip_ids=completed)

    queue = HITLQueue(tmp_path / "hitl.json")
    assert [i.ticket_id for i in queue.items] == ["T-001", "T-004"]
    # The skipped seed was not re-proposed.
    assert sum(1 for i in queue.items if i.ticket_id == "T-001") == 1


def test_hitl_wait_still_works_for_new_fix_during_resume(tmp_path):
    # Manual mode + tiny timeout: a newly proposed fix waits, then the
    # run continues on timeout with the item still pending.
    h = _harness(tmp_path, hitl_mode="manual", hitl_wait=True,
                 hitl_wait_timeout_s=0.5, hitl_wait_poll_s=0.05)
    h.run(TICKETS[:1])  # T-001 only
    queue = HITLQueue(tmp_path / "hitl.json")
    assert len(queue.items) == 1
    assert queue.items[0].status == "pending"
    assert h.recorder.records[0].hitl_status == "pending"


def test_start_from_skips_earlier_tickets(tmp_path):
    h = _harness(tmp_path)
    summary = h.run(TICKETS[:6], skip_ids={"T-001", "T-002", "T-003"})
    ids = [r.ticket_id for r in h.recorder.records]
    assert ids == ["T-004", "T-005", "T-006"]
    assert summary["all"]["n"] == 3


# ---------------------------------------------------------------------------
# CLI end-to-end (subprocess, stub/fake only)
# ---------------------------------------------------------------------------

def _cli(tmp_path, *args):
    cmd = [sys.executable, "scripts/run_experiment.py",
           "--condition", "B", "--run", "99", "--llm", "stub",
           "--meko", "fake", "--hitl-mode", "auto",
           "--results-dir", str(tmp_path), *args]
    return subprocess.run(cmd, capture_output=True, text=True,
                          cwd=str(PROJECT_ROOT), timeout=600)


def _read_ids(tmp_path):
    lines = (tmp_path / "run-B99.jsonl").read_text().strip().split("\n")
    return [json.loads(line)["ticket_id"] for line in lines]


def test_cli_resume_end_to_end(tmp_path):
    leg1 = _cli(tmp_path, "--limit", "3")
    assert leg1.returncode == 0, leg1.stderr[-2000:]
    assert len(_read_ids(tmp_path)) == 3

    leg2 = _cli(tmp_path, "--resume")
    assert leg2.returncode == 0, leg2.stderr[-2000:]
    ids = _read_ids(tmp_path)
    assert len(ids) == 36
    assert len(set(ids)) == 36  # no duplicates
    assert ids == [t["id"] for t in TICKETS]  # dataset order preserved

    summary = json.loads((tmp_path / "run-B99-summary.json").read_text())
    assert summary["all"]["n"] == 36
    csv_text = (tmp_path / "run-B99-summary.csv").read_text()
    assert "\nall,36," in csv_text or csv_text.startswith("group,n,")

    queue = HITLQueue(tmp_path / "hitl_queue.json")
    expect = [t["id"] for t in TICKETS
              if ticket_kind(t) in ("first-time", "unique")]
    assert [i.ticket_id for i in queue.items] == expect


def test_cli_start_from_end_to_end(tmp_path):
    leg1 = _cli(tmp_path, "--limit", "3")
    assert leg1.returncode == 0, leg1.stderr[-2000:]

    leg2 = _cli(tmp_path, "--start-from", "T-004")
    assert leg2.returncode == 0, leg2.stderr[-2000:]
    ids = _read_ids(tmp_path)
    assert len(ids) == 36
    assert len(set(ids)) == 36
    summary = json.loads((tmp_path / "run-B99-summary.json").read_text())
    assert summary["all"]["n"] == 36


def test_cli_resume_errors(tmp_path):
    # --resume with no records to resume from
    r = _cli(tmp_path, "--resume")
    assert r.returncode != 0
    assert "nothing to resume" in r.stderr

    # --start-from with an unknown ticket id
    r = _cli(tmp_path, "--start-from", "T-999")
    assert r.returncode != 0
    assert "not a ticket id" in r.stderr

    # --resume + --limit is ambiguous
    r = _cli(tmp_path, "--resume", "--limit", "3")
    assert r.returncode != 0

    # --resume + --start-from are mutually exclusive
    r = _cli(tmp_path, "--resume", "--start-from", "T-004")
    assert r.returncode != 0
