"""Meko clients: FakeMeko retrieval, NullMeko no-ops, config from env."""

import os

import pytest

from app.factory import build_kb
from app.meko_client import MekoConfig, make_meko_client


def test_fake_meko_memory_add_and_search():
    kb = build_kb()
    client = make_meko_client("B", "fake", MekoConfig(), kb)
    client.memory_add(
        "FIX [C1]: Stripe webhook 400 — rotate the webhook signing secret "
        "in OrderLoop after rotating Stripe API keys.",
        {"ticket_id": "T-001", "cluster": "C1", "memory_key": "T-001",
         "source": "agent"})
    # A repeat ticket with the same wording must find it.
    res = client.context_search(
        "Paid orders not updating — Stripe webhook 400 errors after key rotation",
        limit=5)
    mem = res["buckets"]["memory"]
    assert len(mem) >= 1
    assert mem[0]["metadata"]["memory_key"] == "T-001"
    assert res["match_quality"] in ("high", "medium")


def test_fake_meko_empty_search_has_no_memory():
    client = make_meko_client("B", "fake", MekoConfig(), build_kb())
    res = client.context_search("something completely unrelated xyz", limit=5)
    assert res["buckets"]["memory"] == []
    assert res["match_quality"] == "low"  # fake returns low, never "none"


def test_null_meko_records_but_no_ops():
    """NullMeko records every attempted call (protocol audit) but does nothing."""
    client = make_meko_client("A", "null", MekoConfig(), build_kb())
    res = client.context_search("anything", limit=5)
    assert res["buckets"]["memory"] == []
    assert res["disabled"] is True
    assert len(client.calls) == 1  # recorded for auditing, no real call made


def test_config_from_env(monkeypatch):
    # Config carries no API key, ever — only the datapack id (not a secret).
    monkeypatch.setenv("MEKO_DATAPACK_ID", "dp_test")
    monkeypatch.delenv("MEKO_API_KEY", raising=False)
    cfg = MekoConfig.from_env()
    assert cfg.datapack_id == "dp_test"
    assert not hasattr(cfg, "api_key")


def test_real_client_refuses_without_cli(tmp_path):
    from app.meko_client import MekoCLIClient, MekoConfigError

    with pytest.raises(MekoConfigError):
        MekoCLIClient(MekoConfig(cli=str(tmp_path / "no-such-client.py")))


def test_real_client_constructs_without_env_key():
    # The CLI client needs no env vars: auth lives in the connector CLI.
    from app.meko_client import MekoCLIClient

    client = MekoCLIClient(MekoConfig())
    assert client.cli.is_file()


def test_cli_result_envelope_parsing():
    from app.meko_client import MekoCLIClient

    raw = {"content": [{"type": "text", "text": "{\"id\": \"abc\", \"x\": 1}"}],
           "structuredContent": {"result": "{\"id\": \"abc\", \"x\": 1}"},
           "isError": False}
    parsed = MekoCLIClient._parse_tool_result(raw)
    assert parsed == {"id": "abc", "x": 1, "ok": True}

    err = MekoCLIClient._parse_tool_result(
        {"content": [{"type": "text", "text": "boom"}], "isError": True})
    assert err["ok"] is False
    assert "boom" in err["error"]


def test_cli_upload_payload_and_metadata_string(monkeypatch):
    """KB upload computes sha256/size/head, then POSTs to the presigned URL;
    memory metadata is a JSON string."""
    import base64
    import hashlib
    import json

    from app.meko_client import MekoCLIClient, MekoConfig

    captured: dict = {}
    posted: dict = {}

    def fake_run_cli(self, name, args):
        captured[name] = args
        if name == "conversation_create":
            return {"ok": True, "id": "conv-real-1"}
        if name == "knowledgebase_upload_document":
            return {"ok": True, "key": "doc-key-1",
                    "url": "https://example.invalid/s3",
                    "fields": {"key": "doc-key-1", "policy": "p"}}
        return {"ok": True}

    def fake_post(url, fields, filename, data):
        posted.update(url=url, fields=fields, filename=filename, data=data)

    monkeypatch.setattr(MekoCLIClient, "_run_cli", fake_run_cli)
    monkeypatch.setattr(MekoCLIClient, "_post_to_presigned_url",
                        staticmethod(fake_post))
    client = MekoCLIClient(MekoConfig(datapack_id="dp-spike"))

    res = client.knowledgebase_upload_document("kb-01.md", "hello world")
    assert res["ok"] is True
    assert res["document_key"] == "doc-key-1"
    assert posted["url"] == "https://example.invalid/s3"
    assert posted["filename"] == "kb-01.md"
    assert posted["data"] == b"hello world"
    up = captured["knowledgebase_upload_document"]
    assert up["filename"] == "kb-01.md"
    assert up["size"] == 11
    assert up["content_hash"] == hashlib.sha256(b"hello world").hexdigest()
    assert up["content_head_base64"] == base64.b64encode(b"hello world").decode()
    assert up["datapack_id"] == "dp-spike"

    client.memory_add("some fix", {"ticket_id": "T-001", "cluster": "C1"},
                      agent_id="orderloop-triage")
    add = captured["memory_add"]
    assert add["conversation_id"] == "conv-real-1"
    assert add["agent_id"] == "orderloop-triage"
    assert json.loads(add["metadata"]) == {"ticket_id": "T-001", "cluster": "C1"}
