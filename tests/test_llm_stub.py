"""StubLLM: deterministic JSON plans from the prompt only; Gemini client
refuses without a key."""

import json
import os

import pytest

from app.agents import parse_llm_json
from app.llm import GeminiClient, MissingAPIKeyError, StubLLM


def test_stub_returns_valid_json_plan():
    stub = StubLLM()
    res = stub.generate(
        "You are a support agent.",
        "Ticket T-001: Stripe webhooks stopped working, 400 errors after "
        "rotating API keys. Retrieved context: (none)")
    plan = json.loads(res.text)
    assert plan["diagnosis"]
    assert plan["actions"], "stub should propose actions for a webhook ticket"
    assert any(a["op"] == "customer_update_webhook_secret" for a in plan["actions"])
    assert res.model == "stub-llm/1.0"


def test_stub_reuses_memory_hit():
    stub = StubLLM()
    res = stub.generate(
        "You are a support agent.",
        "Ticket T-002: Paid orders not updating.\nRetrieved context:\n"
        "MEMORY HIT (cluster C1, id mem-1): FIX [C1]: rotate webhook secret")
    plan = json.loads(res.text)
    assert plan["used_memory"] is True
    assert plan["confidence"] > 0.6


def test_stub_escalates_when_nothing_matches():
    stub = StubLLM()
    res = stub.generate("You are a support agent.",
                        "Ticket: the office coffee machine is broken.")
    plan = json.loads(res.text)
    assert plan["needs_human"] is True
    assert plan["actions"] == []


def test_parse_llm_json_tolerates_surrounding_text():
    text = 'Here is my plan:\n{"diagnosis": "x", "confidence": 0.9}\nHope that helps.'
    assert parse_llm_json(text) == {"diagnosis": "x", "confidence": 0.9}
    assert parse_llm_json("no json here") is None
    assert parse_llm_json("") is None


def test_gemini_needs_no_env_key_and_locks_model(monkeypatch):
    # The CLI client needs no env vars: auth lives in the connector CLI.
    # Locked model is gemini-3.5-flash-lite (2.5-flash is retired for new users).
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    client = GeminiClient()
    assert client.model == "gemini-3.5-flash-lite"


def test_gemini_generate_uses_cli_and_exact_tokens(monkeypatch):
    import json as _json
    import subprocess as _subprocess

    def fake_run(cmd, **kwargs):
        assert "custom.gemini" in cmd[1]  # connector CLI, never a key
        assert not any(a.startswith("AIza") or "mko_tkn" in a for a in cmd), \
            "no credential in argv"
        assert "--model" in cmd and "gemini-3.5-flash-lite" in cmd
        assert "--prompt" in cmd
        prompt = cmd[cmd.index("--prompt") + 1]
        assert "System:" in prompt and "User:" in prompt

        class Proc:
            returncode = 0
            stdout = _json.dumps({"text": "OK", "model": "gemini-3.5-flash-lite",
                                  "usage": {"input_tokens": 10,
                                            "output_tokens": 2,
                                            "total_tokens": 12}})
            stderr = ""

        return Proc()

    monkeypatch.setattr(_subprocess, "run", fake_run)
    res = GeminiClient().generate("You are a test.", "Say OK.")
    assert res.text == "OK"
    assert res.input_tokens == 10
    assert res.output_tokens == 2
    assert res.total_tokens == 12
    assert res.model == "gemini-3.5-flash-lite"
