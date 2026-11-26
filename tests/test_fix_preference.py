"""Regression tests for the two pre-official-run fixes from the spike
(26 Nov 2026, build-log "Findings to decide BEFORE official runs"):

1. Fix-memory preference: Meko auto-extracts fact memories from
   conversation turns (1 explicit memory_add -> 7 memories: 1 fix + 6
   facts with empty metadata). Facts can outrank the fix in
   context_search, and the agent used a fact instead of the fix on T-003
   (classified miss). The harness must prefer hits with
   metadata.source == "agent" (or a memory_key) when picking memory_hit.
   Classification rules are unchanged — only the pick order changes.

2. Minimal conversation turns: the harness logged the full ticket body +
   full final answer to Meko on EVERY condition-B ticket, which is what
   the auto-extractor mined facts from. A Meko turn is now logged only
   when the ticket creates shared memory (a fix proposed to HITL), and
   its content is the decision only (ticket id + subject, diagnosis,
   executed ops, verification) — no ticket body, no final answer.
   Reuse/abstain decisions stay traced in the harness metrics, which is
   what the demo reads (app/server.py never reads Meko conversations).
"""

from app.agents import prefer_fix_memories
from app.factory import PROJECT_ROOT, build_kb
from app.harness import Harness, build_trace_messages, load_tickets
from app.hitl import HITLQueue
from app.llm import StubLLM
from app.meko_client import make_meko_client

# ---------------------------------------------------------------------------
# 1. Fix-memory preference (unit)
# ---------------------------------------------------------------------------

_FIX_META = {"ticket_id": "T-001", "cluster": "C1", "memory_key": "T-001",
             "source": "agent", "agent": "orderloop-triage", "run_id": "B99"}


def _hit(memory_id, text, metadata):
    return {"memory_id": memory_id, "text": text, "score": 0.9,
            "metadata": metadata}


def test_prefer_fix_memories_puts_agent_fix_first():
    hits = [
        _hit("fact-1", "Maya's team rotated keys.", {}),
        _hit("fix-1", "FIX [C1] rotate the webhook secret.", _FIX_META),
        _hit("fact-2", "9 orders stuck.", {}),
    ]
    ordered = prefer_fix_memories(hits)
    assert [h["memory_id"] for h in ordered] == ["fix-1", "fact-1", "fact-2"]


def test_prefer_fix_memories_keeps_relative_order_within_groups():
    hits = [
        _hit("fix-a", "fix A", {"source": "agent"}),
        _hit("fact-a", "fact A", {}),
        _hit("fix-b", "fix B", {"memory_key": "T-004"}),
        _hit("fact-b", "fact B", {}),
    ]
    ordered = prefer_fix_memories(hits)
    assert [h["memory_id"] for h in ordered] == [
        "fix-a", "fix-b", "fact-a", "fact-b"]


def test_memory_key_without_source_counts_as_fix():
    # A hit carrying a memory_key is a stored fix even without source.
    hits = [_hit("fact-1", "fact", {}),
            _hit("fix-1", "fix", {"memory_key": "T-001"})]
    assert prefer_fix_memories(hits)[0]["memory_id"] == "fix-1"


def test_source_agent_without_memory_key_counts_as_fix():
    hits = [_hit("fact-1", "fact", {}),
            _hit("fix-1", "fix", {"source": "agent"})]
    assert prefer_fix_memories(hits)[0]["memory_id"] == "fix-1"


def test_all_facts_keep_server_order():
    hits = [_hit("fact-1", "fact", {}), _hit("fact-2", "fact", {})]
    assert prefer_fix_memories(hits) == hits
    assert prefer_fix_memories([]) == []


# ---------------------------------------------------------------------------
# 1. Fix-memory preference (T-003 end-to-end regression)
# ---------------------------------------------------------------------------

# Realistic T-001 fix text, as the harness stores it via build_memory_text.
_FIX_TEXT = """FIX [C1 — Stripe webhooks stopped working after we rotated our API keys]
Diagnosis: Stripe webhook events failing with HTTP 400 after API key rotation — the webhook signing secret was rotated and not updated in OrderLoop.
Steps:
1. Execute the C1 fix steps and verify each one.
Verified in mock: resolved=True
Source ticket: T-001"""

# Auto-extracted-style facts. FakeMeko ranks by token overlap, so the facts
# are phrased in the ticket's own words to reproduce the real-Meko ranking
# inversion from the spike (a fact ranked above the fix for T-003). The
# property under test is the harness's pick, not FakeMeko's ranking.
_FACT_1 = ("Kemarin sore tim IT ganti kunci API Stripe buat keamanan; pagi ini "
           "customer yang sudah dibayar sukses statusnya masih menunggu "
           "pembayaran, orderan stuck, customer nanyain resi, endpoint error.")
_FACT_2 = ("Tim support mencatat orderan stuck, customer sudah dibayar tapi "
           "statusnya masih menunggu pembayaran.")


def _seeded_harness(tmp_path):
    kb = build_kb()
    meko = make_meko_client("B", "fake", None, kb)
    hitl = HITLQueue(tmp_path / "hitl.json")
    harness = Harness(condition="B", run_no=99, llm=StubLLM(), meko=meko,
                      kb=kb, hitl=hitl, hitl_mode="auto",
                      results_dir=tmp_path, model="stub-llm/1.0", verbose=False)
    return harness, meko


def test_t003_regression_fix_beats_ranking_fact(tmp_path):
    """Spike scenario: T-003's context_search returns facts above the fix.

    Raw FakeMeko ranking must put a fact first (otherwise the test proves
    nothing); the harness must still pick the T-001 fix and classify hit.
    """
    harness, meko = _seeded_harness(tmp_path)
    fix_id = meko.memory_add(_FIX_TEXT, dict(_FIX_META))["memory_id"]
    meko.memory_add(_FACT_1, {})
    meko.memory_add(_FACT_2, {})

    tickets = {t["id"]: t for t in
               load_tickets(PROJECT_ROOT / "data" / "tickets.jsonl")}
    t003 = tickets["T-003"]
    raw = meko.context_search(t003["subject"] + "\n" + t003["body"], limit=5)
    raw_ids = [h["memory_id"] for h in raw["buckets"]["memory"]]
    assert raw_ids[0] != fix_id, f"no ranking inversion to fix: {raw_ids}"

    rec = harness.run_ticket(t003)
    assert rec.m7_retrieval == "hit", (
        f"T-003 must reuse the T-001 fix, got {rec.m7_retrieval} "
        f"(memory_id={rec.memory_id})")
    assert rec.used_memory is True
    assert rec.memory_id == fix_id


# ---------------------------------------------------------------------------
# 2. Minimal conversation turns
# ---------------------------------------------------------------------------

def _turns_recorded(meko) -> list:
    return [c for c in meko.calls if c["tool"] == "conversation_add_message"]


def _run_b(tickets, tmp_path, limit=None):
    kb = build_kb()
    meko = make_meko_client("B", "fake", None, kb)
    hitl = HITLQueue(tmp_path / "hitl.json")
    harness = Harness(condition="B", run_no=99, llm=StubLLM(), meko=meko,
                      kb=kb, hitl=hitl, hitl_mode="auto",
                      results_dir=tmp_path, model="stub-llm/1.0", verbose=False)
    all_tickets = load_tickets(PROJECT_ROOT / "data" / "tickets.jsonl")
    chosen = [t for t in all_tickets if t["id"] in tickets]
    harness.run(chosen[:limit] if limit else chosen)
    return harness, meko


def test_turns_recorded_only_when_shared_memory_created(tmp_path):
    """T-001 proposes a fix (turn logged); T-002 reuses it and T-003
    reuses it — but reuse is traced in the harness metrics, not in Meko.
    Before the fix every condition-B ticket logged a turn (3 turns)."""
    harness, meko = _run_b(["T-001", "T-002", "T-003"], tmp_path)
    assert len(_turns_recorded(meko)) == 1, (
        f"expected 1 turn (T-001 proposal only), got {len(_turns_recorded(meko))}")
    by_id = {r.ticket_id: r for r in harness.recorder.records}
    assert by_id["T-002"].m7_retrieval == "hit"  # reuse still works
    assert by_id["T-003"].m7_retrieval == "hit"
    # ... and the reuse decisions are still fully traced in the metrics.
    assert by_id["T-002"].used_memory is True
    assert by_id["T-002"].trace, "decision trace must survive in metrics"


def test_full_run_records_one_turn_per_proposed_fix(tmp_path):
    """36 tickets, auto HITL: 8 seeds + 9 uniques propose fixes = 17 turns
    (was 36 — one per ticket)."""
    harness, meko = _run_b(
        [t["id"] for t in load_tickets(PROJECT_ROOT / "data" / "tickets.jsonl")],
        tmp_path)
    assert len(_turns_recorded(meko)) == 17
    assert len(harness.recorder.records) == 36


def test_recorded_turn_has_no_ticket_body_or_final_answer(tmp_path):
    """The recorded turn is the decision only: id + subject, diagnosis,
    executed ops, verification. The ticket body and the final answer —
    the fact-mining surface — must not be in it."""
    harness, meko = _run_b(["T-001"], tmp_path)
    assert len(_turns_recorded(meko)) == 1
    turns = meko.conversations.get("B99-T-001", [])
    assert len(turns) == 1
    recorded = turns[0]["user_message"] + "\n" + turns[0]["agent_reply"]

    tickets = {t["id"]: t for t in
               load_tickets(PROJECT_ROOT / "data" / "tickets.jsonl")}
    t001 = tickets["T-001"]
    assert "14 paid orders" not in recorded  # from the ticket body
    assert "ORD-88412" not in recorded  # order number from the body
    assert "Thanks — this matches a known issue" not in recorded  # final answer
    assert "Diagnosis:" in recorded and "verified:" in recorded
    assert "customer_update_webhook_secret" in recorded  # executed op
    # Old code logged subject + full body as the user turn AND the full
    # final answer as the assistant turn. The new turn (both messages
    # together) must be smaller than the old user message alone.
    old_user_message = t001["subject"] + "\n" + t001["body"]
    assert len(recorded) < len(old_user_message), (
        f"recorded turn ({len(recorded)} chars) must be smaller than the "
        f"old user message alone ({len(old_user_message)} chars)")


def test_build_trace_messages_is_minimal_and_complete():
    """Unit: the trace builder keeps the decision, drops the body."""
    from app.agents import AgentResult

    ticket = {"id": "T-001", "cluster": "C1",
              "subject": "Stripe webhooks stopped working"}
    result = AgentResult(
        agent="triage", diagnosis="Webhook secret rotated.",
        steps=["Rotate the secret."], actions=[
            {"op": "customer_update_webhook_secret", "args": {}, "ok": True,
             "message": ""}],
        used_memory=True, memory_id="mem-001", memory_cluster="C1",
        confidence=0.9, escalated=False, escalation_reason="",
        verified=True, verify_checks={}, final_answer="Thanks, all fixed!",
        input_tokens=10, output_tokens=10, tool_calls={}, trace=[],
        llm_calls=1, memory_key="T-001")
    msgs = build_trace_messages(ticket, result)
    text = "\n".join(m["content"] for m in msgs)
    assert "T-001" in text and "Stripe webhooks stopped working" in text
    assert "Webhook secret rotated." in text
    assert "customer_update_webhook_secret" in text
    assert "verified: True" in text
    assert "Thanks, all fixed!" not in text  # final answer is not traced
