"""Regression tests for the two defects found in the real-Meko/Gemini spike
(26 Nov 2026): duplicated handoff traces, and the real model not knowing the
mock's argument convention for customer-supplied values."""

from app.agents import SYSTEM_PROMPT_BASE
from tests.test_harness_protocol import _run_harness


def test_handoff_trace_is_not_duplicated(tmp_path):
    # T-001 (first-time, no memory yet) hands off triage -> specialist.
    # Before the fix the record's trace repeated the whole event sequence
    # (ticket_received appeared twice).
    harness, _ = _run_harness("B", 3, tmp_path)
    for rec in harness.recorder.records:
        events = [t.get("event") for t in rec.trace]
        assert events.count("ticket_received") == 1, rec.ticket_id
        assert events.count("specialist_received") <= 1, rec.ticket_id
        # the trace must not be the same event sequence repeated twice
        n = len(events)
        if n % 2 == 0 and n >= 2:
            assert events[: n // 2] != events[n // 2:], rec.ticket_id


def test_system_prompt_documents_secret_arg():
    # The stub passes {"secret": "whsec_NEW"} for C1; the real model got
    # zero verifications in the spike because the prompt never said the op
    # needs a secret argument. The convention must be in the prompt.
    assert "customer_update_webhook_secret" in SYSTEM_PROMPT_BASE
    assert "whsec_NEW" in SYSTEM_PROMPT_BASE
    assert "args.secret" in SYSTEM_PROMPT_BASE
