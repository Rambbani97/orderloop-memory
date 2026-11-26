"""Demo server — FastAPI + vanilla JS dashboard.

Views: Inbox (36 tickets as the agent sees them), Live Trace (one ticket,
step by step), HITL queue (approve/reject fixes into memory), Metrics
dashboard (A vs B summary from the latest run files).

Run: ``python -m app.server`` (defaults: stub LLM + FakeMeko unless keys
are in env) or ``uvicorn "app.server:create_app" --factory --port 8000``.

This is a DEMO surface for the hackathon judges. It never touches real
customer data; tickets are synthetic and the mock OrderLoop is in-process.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.agents import sanitize_ticket
from app.factory import PROJECT_ROOT, build_kb, build_llm, build_meko, describe_setup
from app.harness import Harness, load_tickets
from app.hitl import HITLQueue

RESULTS_DIR = PROJECT_ROOT / "results"
STATIC_DIR = PROJECT_ROOT / "static"


class RunTicketRequest(BaseModel):
    ticket_id: str
    condition: str = "B"


class RunAllRequest(BaseModel):
    condition: str = "B"
    run_no: int = 1


class RejectRequest(BaseModel):
    reason: str = "other"


class AppState:
    def __init__(self) -> None:
        self.kb = build_kb()
        self.llm = build_llm(os.environ.get("LLM_KIND", "auto"))
        self.tickets = load_tickets(PROJECT_ROOT / "data" / "tickets.jsonl")
        self.hitl = HITLQueue(RESULTS_DIR / "hitl_queue.json")
        self.setup = describe_setup(self.llm, None)
        self.meko_by_condition: dict[str, object] = {}
        self.run_status: dict = {"running": False, "run_id": "", "done": 0, "total": 0}
        self._lock = threading.Lock()

    def meko(self, condition: str):
        if condition not in self.meko_by_condition:
            client = build_meko(condition, os.environ.get("MEKO_KIND", "auto"), self.kb)
            self.meko_by_condition[condition] = client
            self.setup = describe_setup(self.llm, client)
        return self.meko_by_condition[condition]

    def harness(self, condition: str, run_no: int) -> Harness:
        return Harness(condition=condition, run_no=run_no, llm=self.llm,
                       meko=self.meko(condition), kb=self.kb, hitl=self.hitl,
                       hitl_mode=os.environ.get("HITL_MODE", "manual"),
                       results_dir=RESULTS_DIR,
                       model=getattr(self.llm, "model", "stub-llm/1.0"),
                       verbose=False)


def create_app() -> FastAPI:
    state = AppState()
    app = FastAPI(title="OrderLoop Memory — ContextCon Demo",
                  description="Support agents with shared memory (Meko).")

    @app.get("/", response_class=FileResponse)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/status")
    def status():
        return {"setup": state.setup,
                "n_tickets": len(state.tickets),
                "hitl": state.hitl.stats(),
                "run_status": state.run_status,
                "meko_usage": _meko_usage(state)}

    @app.get("/api/tickets")
    def tickets():
        # The inbox shows exactly what the agent sees (sanitized view).
        return [sanitize_ticket(t) for t in state.tickets]

    @app.get("/api/tickets/{ticket_id}")
    def ticket_detail(ticket_id: str):
        ticket = next((t for t in state.tickets if t["id"] == ticket_id), None)
        if ticket is None:
            raise HTTPException(404, f"unknown ticket {ticket_id}")
        out = sanitize_ticket(ticket)
        out["result"] = _last_result(ticket_id)
        return out

    @app.post("/api/run-ticket")
    def run_ticket(req: RunTicketRequest):
        ticket = next((t for t in state.tickets if t["id"] == req.ticket_id), None)
        if ticket is None:
            raise HTTPException(404, f"unknown ticket {req.ticket_id}")
        if req.condition not in ("A", "B"):
            raise HTTPException(400, "condition must be A or B")
        if state.run_status["running"]:
            raise HTTPException(409, "a run is already in progress")
        # Async by design: in manual HITL mode the harness blocks (up to
        # 30 min) waiting for a human decision on a proposed fix. A
        # synchronous endpoint would hang the request — and, on Render, the
        # platform would kill it first. The job runs in a background
        # thread; poll /api/run-status, and approve/reject the proposed
        # fix in the HITL tab — the wait resolves when you decide.
        def _job():
            harness = state.harness(req.condition, run_no=0)
            with state._lock:
                state.run_status.update({"running": True, "run_id": harness.run_id,
                                         "done": 0, "total": 1})
            try:
                harness.run_ticket(ticket)
            finally:
                # Never wedge the demo: a crashed job must clear `running`.
                with state._lock:
                    state.run_status.update({"running": False, "done": 1})

        threading.Thread(target=_job, daemon=True).start()
        return {"started": True, "run_id": f"{req.condition}0",
                "ticket_id": req.ticket_id, "condition": req.condition,
                "note": "If a fix is proposed, approve/reject it in the HITL "
                        "tab — the run finishes after your decision."}

    @app.post("/api/run-all")
    def run_all(req: RunAllRequest):
        if state.run_status["running"]:
            raise HTTPException(409, "a run is already in progress")
        if req.condition not in ("A", "B"):
            raise HTTPException(400, "condition must be A or B")

        def _job():
            harness = state.harness(req.condition, req.run_no)
            total = len(state.tickets)
            with state._lock:
                state.run_status.update({"running": True, "run_id": harness.run_id,
                                         "done": 0, "total": total})
            try:
                for i, ticket in enumerate(state.tickets):
                    harness.run_ticket(ticket)
                    with state._lock:
                        state.run_status["done"] = i + 1
                summary = harness.recorder.summarize()
                (RESULTS_DIR / f"run-{harness.run_id}-summary.json").write_text(
                    json.dumps(summary, indent=2), encoding="utf-8")
            finally:
                with state._lock:
                    state.run_status.update({"running": False})

        threading.Thread(target=_job, daemon=True).start()
        return {"started": True, "run_id": f"{req.condition}{req.run_no}",
                "total": len(state.tickets)}

    @app.get("/api/run-status")
    def run_status():
        return state.run_status

    @app.get("/api/hitl")
    def hitl_list():
        return {"pending": [i.__dict__ for i in state.hitl.pending()],
                "stats": state.hitl.stats()}

    @app.post("/api/hitl/{item_id}/approve")
    def hitl_approve(item_id: str):
        item = state.hitl.approve(item_id, decided_by="human-dashboard")
        if item is None:
            raise HTTPException(404, f"no pending item {item_id}")
        # Approved fix becomes memory (condition B datapack).
        meko = state.meko("B")
        meko.memory_add(item.memory_text, {**item.metadata, "approved_by": "human-dashboard"},
                        agent_id="orderloop-triage")
        return {"ok": True, "item_id": item_id, "status": "approved"}

    @app.post("/api/hitl/{item_id}/reject")
    def hitl_reject(item_id: str, req: RejectRequest):
        try:
            item = state.hitl.reject(item_id, req.reason, decided_by="human-dashboard")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if item is None:
            raise HTTPException(404, f"no pending item {item_id}")
        return {"ok": True, "item_id": item_id, "status": "rejected",
                "reason": req.reason}

    @app.get("/api/metrics")
    def metrics():
        out = {}
        for path in sorted(RESULTS_DIR.glob("run-*-summary.json")):
            out[path.stem.replace("run-", "")] = json.loads(path.read_text(encoding="utf-8"))
        return out

    return app


def _meko_usage(state: AppState) -> dict:
    usage: dict = {}
    for cond, client in state.meko_by_condition.items():
        calls = getattr(client, "calls", [])
        usage[cond] = {"tool_calls": len(calls),
                       "by_tool": {t: sum(1 for c in calls if c.get("tool") == t)
                                   for t in {c.get("tool") for c in calls}}}
        if hasattr(client, "token_usage"):
            usage[cond]["token_usage"] = client.token_usage
    return usage


def _last_result(ticket_id: str) -> dict | None:
    """Latest recorded result for a ticket across run files (newest first)."""
    for path in sorted(RESULTS_DIR.glob("run-*.jsonl"), reverse=True):
        try:
            lines = path.read_text(encoding="utf-8").strip().splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("ticket_id") == ticket_id:
                return rec
    return None


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.server:app", host="127.0.0.1", port=8000, reload=False)
