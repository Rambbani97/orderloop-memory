"""Demo server: /api/run-ticket is async (regression test).

In manual HITL mode the harness blocks waiting for a human decision on a
proposed fix (up to 30 min). The endpoint must therefore return
immediately and run the ticket in a background thread — a synchronous
endpoint hangs the request (found by the Render smoke test, 26 Nov 2026:
POST /api/run-ticket never returned). The run finishes after the fix is
approved/rejected in the HITL tab.
"""

import json
import os
import time

os.environ.setdefault("LLM_KIND", "stub")
os.environ.setdefault("MEKO_KIND", "fake")
os.environ.setdefault("HITL_MODE", "manual")

import pytest
from fastapi.testclient import TestClient

from app.server import PROJECT_ROOT, app

RESULTS_DIR = PROJECT_ROOT / "results"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean_b0_runs():
    yield
    # The demo runs write run-B0.jsonl + a B0 queue item; keep the repo clean.
    for name in ("run-B0.jsonl", "run-B0-summary.json"):
        p = RESULTS_DIR / name
        if p.exists():
            p.unlink()
    qpath = RESULTS_DIR / "hitl_queue.json"
    if qpath.exists():
        q = json.loads(qpath.read_text(encoding="utf-8"))
        q["items"] = [i for i in q["items"]
                      if i.get("metadata", {}).get("run_id") != "B0"]
        qpath.write_text(json.dumps(q, indent=2), encoding="utf-8")


def _wait_until(fn, timeout_s=30.0, interval_s=0.2):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if fn():
            return True
        time.sleep(interval_s)
    return False


def test_run_ticket_returns_immediately_and_completes(client):
    # T-002 is a repeat ticket: no fix is proposed, no HITL wait.
    r = client.post("/api/run-ticket",
                    json={"ticket_id": "T-002", "condition": "B"})
    assert r.status_code == 200
    assert r.json()["started"] is True
    assert _wait_until(
        lambda: client.get("/api/run-status").json()["running"] is False)
    d = client.get("/api/tickets/T-002").json()
    assert d["result"] is not None
    assert d["result"]["ticket_id"] == "T-002"


def test_run_ticket_waits_for_hitl_then_finishes_on_approve(client):
    # T-001 is a first-time ticket: a fix is proposed and the background
    # job waits for a human decision. Approve it via the API, then the
    # run must finish and the ticket must have a result.
    r = client.post("/api/run-ticket",
                    json={"ticket_id": "T-001", "condition": "B"})
    assert r.status_code == 200
    assert r.json()["started"] is True

    def _proposed():
        data = client.get("/api/hitl").json()
        return next((i for i in data["pending"]
                     if i["ticket_id"] == "T-001"), None)

    assert _wait_until(lambda: _proposed() is not None, timeout_s=60.0), (
        "no fix proposed; run-status=",
        client.get("/api/run-status").json(),
    )
    item = _proposed()
    ar = client.post(f"/api/hitl/{item['item_id']}/approve")
    assert ar.status_code == 200
    assert _wait_until(
        lambda: client.get("/api/run-status").json()["running"] is False)
    # NOTE: GET /api/tickets/T-001 returns the newest record by filename
    # order, which is the official run-B1 record — not this demo run. Read
    # the demo run file directly for this run's record.
    recs = [json.loads(line) for line in
            (RESULTS_DIR / "run-B0.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    assert recs, "no B0 records written"
    assert recs[-1]["ticket_id"] == "T-001"
    assert recs[-1]["hitl_status"] == "pending"  # recorded pre-decision
