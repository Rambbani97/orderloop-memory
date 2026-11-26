#!/usr/bin/env python3
"""Spike test: verify real Meko Cloud + Gemini wiring before official runs.

Answers (with real quota spent, kept minimal):
  (a) cross-agent memory visibility: memory_add as triage -> readable by
      specialist via memory_search AND context_search? Or is memory_promote
      needed?
  (b) KB upload via MCP knowledgebase_upload_document + S3 POST + indexing.
  (c) end-to-end condition B on 3 tickets (T-001 seed, T-002 near repeat,
      T-003 far repeat, all C1) with real Gemini + real Meko, in a FRESH
      datapack (so the spike memory from (a) cannot contaminate it).

Re-runnable: step (a) skips memory_add when the marker already exists;
datapacks are reused when present. Quota ledger is printed at the end
(counts from the clients' call logs + Gemini token usage from the harness
metrics). Run from the repo root:

    python scripts/spike_test.py [--skip-e2e]

Writes results to results/spike-2026-11-26/ (NOT results/ — official runs
need a clean results dir).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.factory import PROJECT_ROOT, build_kb, build_llm
from app.harness import Harness, load_tickets
from app.hitl import HITLQueue
from app.meko_client import MekoCLIClient, MekoConfig

SPIKE_DATAPACK = "orderloop-spike"
E2E_DATAPACK = "orderloop-spike-e2e"
SPIKE_RESULTS = PROJECT_ROOT / "results" / "spike-2026-11-26"
TRIAGE = "orderloop-triage"
SPECIALIST = "orderloop-specialist"
KB_DOCS = ("kb-01-webhook-secret-rotation.md",
           "kb-02-saml-setup-certificate-renewal.md")

MARKER = "SPIKE-MARKER-7Q3Z9"
MEMORY_TEXT = (
    f"FIX [C1 spike]: Stripe webhook 400 after API key rotation — rotate "
    f"the webhook signing secret in OrderLoop. {MARKER} This is a spike-test "
    f"memory, not a real fix."
)


def ledger(*clients: MekoCLIClient) -> dict:
    counts: dict[str, int] = {}
    for client in clients:
        for call in client.calls:
            counts[call["tool"]] = counts.get(call["tool"], 0) + 1
    return counts


def get_or_create_datapack(meko: MekoCLIClient, name: str) -> str:
    existing = meko.datapack_list()
    items = existing.get("data") or existing.get("datapacks") or []
    for dp in items:
        if isinstance(dp, dict) and dp.get("datapack_name") == name:
            print(f"reusing datapack {name}: {dp.get('datapack_id')}")
            return dp.get("datapack_id", "")
    created = meko.datapack_create(name)
    dp_id = created.get("datapack_id", "")
    print(f"created datapack {name}: {dp_id}")
    return dp_id


def upload_kb_docs(meko: MekoCLIClient) -> dict:
    docs: dict = {}
    for name in KB_DOCS:
        path = PROJECT_ROOT / "data" / "kb" / name
        text = path.read_text(encoding="utf-8")
        res = meko.knowledgebase_upload_document(name, text)
        docs[name] = {"upload": json.dumps(res)[:300]}
        print(f"uploaded {name}: ok={res.get('ok')}",
              f"key={(res.get('document_key') or '')[:60]}")
        key = res.get("document_key")
        if key:
            status = None
            for _ in range(12):
                status = meko.knowledgebase_document_status(key)
                state = json.dumps(status)
                if "complet" in state.lower() or "index" in state.lower():
                    break
                if "fail" in state.lower() or "error" in state.lower():
                    break
                time.sleep(5)
            docs[name]["status"] = json.dumps(status)[:400]
            print(f"status {name}:", json.dumps(status)[:400])
    return docs


def main() -> int:
    parser = argparse.ArgumentParser(description="Meko + Gemini spike test")
    parser.add_argument("--skip-e2e", action="store_true")
    args = parser.parse_args()

    SPIKE_RESULTS.mkdir(parents=True, exist_ok=True)
    meko = MekoCLIClient(MekoConfig())
    out: dict = {"steps": {}}

    # -- 0. datapack ----------------------------------------------------
    print("== 0. datapack ==")
    dp_id = get_or_create_datapack(meko, SPIKE_DATAPACK)
    if not dp_id:
        print("ERROR: no datapack id", file=sys.stderr)
        return 2
    meko.config.datapack_id = dp_id
    out["datapack_id"] = dp_id

    # -- (a) cross-agent memory visibility ------------------------------
    print("== (a) cross-agent memory visibility ==")
    step_a: dict = {}
    # Idempotency: skip the add when the marker is already stored.
    pre = meko.memory_search("Stripe webhook 400 errors after API key rotation",
                             limit=5, agent_id=SPECIALIST)
    pre_found = any(MARKER in (r.get("text", "") or r.get("memory", ""))
                    for r in (pre.get("results") or []) if isinstance(r, dict))
    if pre_found:
        print("marker memory already present — skipping memory_add")
        step_a["memory_add_as_triage"] = {"skipped": True, "reason": "already present"}
    else:
        added = meko.memory_add(
            MEMORY_TEXT,
            {"ticket_id": "SPIKE-001", "cluster": "C1", "memory_key": "SPIKE-001",
             "source": "agent"},
            agent_id=TRIAGE)
        step_a["memory_add_as_triage"] = added
        print("memory_add:", json.dumps(added)[:300])

    ms = meko.memory_search(
        "Stripe webhook 400 errors after API key rotation", limit=5,
        agent_id=SPECIALIST)
    ms_results = ms.get("results", []) if isinstance(ms, dict) else []
    found_ms = any(MARKER in (r.get("text", "") or r.get("memory", ""))
                   for r in ms_results if isinstance(r, dict))
    step_a["memory_search_as_specialist"] = {
        "found_marker": found_ms, "n_results": len(ms_results)}
    print("memory_search as specialist: found =", found_ms,
          "n =", len(ms_results))

    cs = meko.context_search(
        "Stripe webhook 400 errors after API key rotation", limit=5,
        conversation_id="spike-a", agent_id=SPECIALIST)
    mem_bucket = ((cs.get("buckets") or {}).get("memory") or [])
    found_cs = any(MARKER in (h.get("text", "") or "") for h in mem_bucket
                   if isinstance(h, dict))
    step_a["context_search_as_specialist"] = {
        "found_marker": found_cs, "n_memory_hits": len(mem_bucket),
        "match_quality": cs.get("match_quality"),
        "first_hit": mem_bucket[0] if mem_bucket else None}
    print("context_search as specialist: found =", found_cs,
          "match_quality =", cs.get("match_quality"))

    ga = meko.memory_get_all()
    ga_items = ga.get("results") or ga.get("data") or []
    step_a["memory_get_all_regular"] = {
        "found_marker": any(MARKER in json.dumps(i) for i in ga_items),
        "n": len(ga_items) if isinstance(ga_items, list) else "?"}
    print("memory_get_all (regular):", step_a["memory_get_all_regular"])

    step_a["verdict"] = (
        "cross-agent readable WITHOUT promote"
        if (found_ms and found_cs) else
        "NOT readable without promote — investigate")
    print("VERDICT (a):", step_a["verdict"])
    out["steps"]["a_cross_agent"] = step_a

    # -- (b) KB upload via MCP ------------------------------------------
    print("== (b) KB upload via MCP ==")
    out["steps"]["b_kb_upload"] = {"docs": upload_kb_docs(meko)}

    # -- (c) end-to-end: 3 tickets, condition B, real Gemini + Meko -----
    e2e_meko = None
    if not args.skip_e2e:
        print("== (c) end-to-end 3 tickets (T-001..T-003, condition B) ==")
        e2e_meko = MekoCLIClient(MekoConfig())
        e2e_dp = get_or_create_datapack(e2e_meko, E2E_DATAPACK)
        if not e2e_dp:
            print("ERROR: no e2e datapack id", file=sys.stderr)
            return 2
        e2e_meko.config.datapack_id = e2e_dp
        out["e2e_datapack_id"] = e2e_dp
        upload_kb_docs(e2e_meko)
        llm = build_llm("gemini")
        kb = build_kb()
        tickets = load_tickets(PROJECT_ROOT / "data" / "tickets.jsonl")[:3]
        hitl = HITLQueue(SPIKE_RESULTS / "hitl_queue.json")
        harness = Harness(condition="B", run_no=0, llm=llm, meko=e2e_meko, kb=kb,
                          hitl=hitl, hitl_mode="auto",
                          results_dir=str(SPIKE_RESULTS),
                          model=getattr(llm, "model", "gemini-3.5-flash-lite"),
                          limit=3)
        summary = harness.run(tickets)
        gemini_tokens = {"input": 0, "output": 0, "total": 0}
        for rec in (SPIKE_RESULTS / "run-B0.jsonl").read_text(
                encoding="utf-8").strip().splitlines():
            m = json.loads(rec)
            gemini_tokens["input"] += m.get("m2_input_tokens", 0)
            gemini_tokens["output"] += m.get("m3_output_tokens", 0)
            gemini_tokens["total"] += m.get("m4_total_tokens", 0)
        out["steps"]["c_e2e"] = {"summary": summary,
                                 "gemini_tokens": gemini_tokens}
        print("gemini tokens (3 tickets):", gemini_tokens)

    clients = [meko] + ([e2e_meko] if e2e_meko is not None else [])
    out["quota_ledger"] = ledger(*clients)
    out["quota_ledger"]["gemini_tokens"] = (
        out["steps"].get("c_e2e", {}).get("gemini_tokens", {}))
    (SPIKE_RESULTS / "spike-report.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8")
    print("\n== QUOTA LEDGER ==")
    print(json.dumps(out["quota_ledger"], indent=2))
    print("report ->", SPIKE_RESULTS / "spike-report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
