"""Harness protocol: condition A = zero Meko calls; condition B =
context_search before any fix op. Full stub runs must produce zero
protocol violations and sane retrieval classifications."""

import json
from pathlib import Path

import pytest

from app.factory import PROJECT_ROOT, build_kb
from app.harness import Harness, load_tickets, ticket_kind
from app.hitl import HITLQueue
from app.llm import StubLLM
from app.meko_client import make_meko_client

RESULTS = PROJECT_ROOT / "results"


def _run_harness(condition: str, limit: int, tmp_path, hitl_mode: str = "auto"):
    kb = build_kb()
    meko = make_meko_client(condition, "fake" if condition == "B" else "null",
                            None, kb)
    hitl = HITLQueue(tmp_path / "hitl.json")
    harness = Harness(condition=condition, run_no=99, llm=StubLLM(), meko=meko,
                      kb=kb, hitl=hitl, hitl_mode=hitl_mode,
                      results_dir=tmp_path, model="stub-llm/1.0", verbose=False)
    tickets = load_tickets(PROJECT_ROOT / "data" / "tickets.jsonl")[:limit]
    summary = harness.run(tickets)
    return harness, summary


def test_condition_a_makes_zero_meko_calls(tmp_path):
    harness, _ = _run_harness("A", 6, tmp_path)
    for rec in harness.recorder.records:
        assert not rec.protocol_violation, f"{rec.ticket_id} violated protocol A"
        assert rec.m7_retrieval == "na"
    assert len(harness.meko.calls) == 0


def test_condition_b_searches_before_fix(tmp_path):
    harness, _ = _run_harness("B", 6, tmp_path)
    for rec in harness.recorder.records:
        assert not rec.protocol_violation, f"{rec.ticket_id} violated protocol B"
        # every ticket in B must have done exactly one context_search
        assert rec.m6_tool_calls.get("context_search", 0) == 1


def test_condition_b_repeats_hit_memory(tmp_path):
    # First 6 tickets: C1 seed + 2 repeats, C2 seed + 2 repeats.
    # With auto HITL the seed fixes become memory, so repeats must hit.
    harness, _ = _run_harness("B", 6, tmp_path)
    by_id = {r.ticket_id: r for r in harness.recorder.records}
    assert by_id["T-002"].m7_retrieval == "hit"
    assert by_id["T-003"].m7_retrieval == "hit"
    assert by_id["T-005"].m7_retrieval == "hit"
    assert by_id["T-006"].m7_retrieval == "hit"
    assert by_id["T-001"].m7_retrieval == "na"  # seed: no memory yet


def test_protocol_checker_catches_violations():
    from app.agents import AgentContext

    harness = Harness(condition="B", run_no=0, llm=StubLLM(),
                      meko=make_meko_client("B", "fake"), kb=build_kb(),
                      hitl=HITLQueue(RESULTS / "hitl-test.json"),
                      results_dir=RESULTS, verbose=False)
    ctx = AgentContext(condition="B", meko=harness.meko, kb=harness.kb,
                       mock=None, llm=StubLLM(), agent_id="x")
    ctx.log("ticket_received", {})
    ctx.log("mock_op", {"op": "get_order"})  # fix op BEFORE any search
    ctx.log("context_search", {})
    assert harness._check_protocol(ctx, 0, 0) is True

    ctx2 = AgentContext(condition="B", meko=harness.meko, kb=harness.kb,
                        mock=None, llm=StubLLM(), agent_id="x")
    ctx2.log("ticket_received", {})
    ctx2.log("context_search", {})
    ctx2.log("mock_op", {"op": "get_order"})
    assert harness._check_protocol(ctx2, 0, 0) is False


def test_ticket_kinds():
    tickets = load_tickets(PROJECT_ROOT / "data" / "tickets.jsonl")
    kinds = {ticket_kind(t) for t in tickets}
    assert kinds == {"first-time", "repeat", "distractor", "unique"}
