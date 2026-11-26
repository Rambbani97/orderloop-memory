"""Mock OrderLoop: world setup per ticket, fix ops, verification."""

import json
from pathlib import Path

import pytest

from app.mock_orderloop import FIX_RECIPES, MockOrderLoop

ROOT = Path(__file__).resolve().parent.parent

# Canonical args per op (mirrors the stub LLM's recipes in app/llm.py).
OP_ARGS: dict[str, dict] = {
    "customer_update_webhook_secret": {"secret": "whsec_NEW"},
    "webhook_send_test_event": {"event": "payment_intent.succeeded"},
    "saml_test_login": {"user": "staff"},
    "saml_assign_user": {"user": "Layla"},
    "apply_proration_credit": {"amount": 53.52},
    "customer_toggle_ios_permission": {"on": True},
    "send_test_push": {"device": "iPhone"},
    "enable_incremental_sync": {"batch_size": 250, "delay_seconds": 2},
    "run_report": {"range_days": 365, "aggregated": True},
    "verify_identity": {"evidence": {"email": "a@b.co", "id": "passport",
                                     "card_last4": "4242"}},
    "set_sync_direction": {"direction": "pos_wins"},
    "set_currency_rounding": {"mode": "total"},
    "merge_accounts": {"source": "melbourne", "target": "sydney"},
    "webhook_set_custom_fields": {"fields": ["loyalty_tier"]},
    "get_known_issue": {"ref": "MOB-2214"},
    "notify_release": {"version": "3.8.2"},
    "erase_customer_data": {"email": "j.dupont@example.fr"},
    "increase_rate_limit": {"new_limit": 2500, "days": 14},
    "set_scanner_mode": {"mode": "SPP"},
}


def load_tickets():
    return [json.loads(line) for line in
            (ROOT / "data" / "tickets.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]


def test_cluster_recipes_resolve_seeds():
    """Executing the documented fix recipe resolves each cluster seed."""
    tickets = load_tickets()
    seeds = [t for t in tickets if not t.get("memory_key")
             and t["cluster"].startswith("C")]
    assert len(seeds) == 8
    for ticket in seeds:
        mock = MockOrderLoop()
        mock.reset_for_ticket(ticket)
        for op in FIX_RECIPES[ticket["cluster"]]:
            res = mock.execute(op, OP_ARGS.get(op, {}))
            assert res["ok"], f"{ticket['id']} {op}: {res}"
        verify = mock.verify_fix(ticket)
        assert verify["resolved"], f"{ticket['id']}: {verify['checks']}"


def test_distractor_recipes_resolve():
    tickets = load_tickets()
    distractors = [t for t in tickets if t["cluster"] == "distractor"]
    assert len(distractors) == 3
    for ticket in distractors:
        mock = MockOrderLoop()
        mock.reset_for_ticket(ticket)
        for op in FIX_RECIPES[ticket["id"]]:
            res = mock.execute(op, OP_ARGS.get(op, {}))
            assert res["ok"], f"{ticket['id']} {op}: {res}"
        verify = mock.verify_fix(ticket)
        assert verify["resolved"], f"{ticket['id']}: {verify['checks']}"


def test_wrong_cluster_recipe_does_not_resolve():
    """The C1 fix must NOT resolve the D-01 distractor (wrong URL, not secret)."""
    tickets = load_tickets()
    d01 = next(t for t in tickets if t["id"] == "D-01")
    mock = MockOrderLoop()
    mock.reset_for_ticket(d01)
    for op in FIX_RECIPES["C1"]:
        mock.execute(op, {})
    assert not mock.verify_fix(d01)["resolved"]


def test_unknown_op_fails():
    mock = MockOrderLoop()
    mock.reset_for_ticket(load_tickets()[0])
    res = mock.execute("delete_everything", {})
    assert not res["ok"]
    assert res["message"].startswith("Unknown operation")


def test_2fa_reset_requires_identity_verification():
    """reset_2fa without verify_identity must fail (destructive guard)."""
    tickets = load_tickets()
    c8 = next(t for t in tickets if t["cluster"] == "C8" and not t.get("memory_key"))
    mock = MockOrderLoop()
    mock.reset_for_ticket(c8)
    assert not mock.execute("reset_2fa", {})["ok"]
    mock.execute("request_2fa_reset", {})
    mock.execute("verify_identity", {"evidence": {"email": "a@b.co", "id": "passport",
                                                   "card_last4": "4242"}})
    assert mock.execute("reset_2fa", {})["ok"]
