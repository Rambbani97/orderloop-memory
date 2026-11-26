"""OrderLoop support agents — deterministic loop, LLM only for reasoning.

Two agents share one Meko datapack (condition B) with different ``agent_id``s:

- :class:`TriageAgent` (``orderloop-triage``) — first contact. In condition B
  it MUST call ``context_search`` before doing anything else (the harness
  enforces this). It classifies, reuses a strong memory hit, solves easy
  tickets, or hands off to the Specialist.
- :class:`SpecialistAgent` (``orderloop-specialist``) — deep diagnosis,
  executes the fix, verifies it.

Control flow is deterministic code; the LLM only produces a structured JSON
plan (diagnosis, steps, actions, confidence, needs_human). The agent never
sees ground truth: :func:`sanitize_ticket` strips ``root_cause``,
``correct_fix``, ``memory_key``, ``target_cluster`` and ``wrong_fix`` before
anything is shown to the agent or the LLM. The full ticket (with ground
truth) is only passed to :meth:`MockOrderLoop.verify_fix` by the harness —
never into a prompt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.kb import LocalKB
from app.llm import LLMClient
from app.meko_client import BaseMekoClient
from app.mock_orderloop import MockOrderLoop

SYSTEM_PROMPT_BASE = """You are a support agent for OrderLoop, a SaaS product for order, inventory \
and fulfilment management for online sellers (plans: Starter $29, Growth $79, \
Scale $199, Enterprise custom). You answer customer tickets in English.

Rules:
- Diagnose from evidence, not guesses. Use the retrieved context and knowledge \
base excerpts given to you.
- If a retrieved memory matches this ticket's problem, reuse its fix, adapt it \
to this customer's details (names, order numbers, plan), and say which memory \
you used. Do not copy a memory blindly when the details differ.
- If a memory looks similar but the facts differ (different error code, \
different symptom detail), do NOT use it — say why and diagnose fresh.
- Execute the fix with the tools available (mock admin operations) and verify \
each step before closing the ticket.
- If you cannot solve it confidently, escalate: set needs_human=true and \
explain what you tried.
- Never invent URLs, menu paths, order numbers, or invoice numbers. Never \
suggest deleting data, changing credentials, or refunding money without \
verification.
- Tool arguments: some operations need a value only the customer can supply. \
customer_update_webhook_secret takes args.secret (the new signing secret from \
the customer's Stripe dashboard) — when the customer confirms they rotated \
the secret, pass the value they provide; in this simulated environment use \
'whsec_NEW' as the confirmed new secret. apply_proration_credit needs a \
positive args.amount. Never call an operation with a required argument \
missing or empty — it will fail.
- Answer with a single JSON object only, no other text:
{"diagnosis": "...", "steps": ["..."], "actions": [{"op": "...", "args": {...}}], \
"confidence": 0.0-1.0, "needs_human": false, "used_memory": false, \
"memory_summary": null, "final_answer": "..."}
Available mock operations (op names): get_order, get_webhook_status, \
customer_update_webhook_secret, customer_fix_webhook_url, \
webhook_send_test_event, webhook_replay_failed_events, \
webhook_set_custom_fields, get_saml_status, customer_upload_saml_metadata, \
saml_test_login, saml_assign_user, get_invoice, apply_proration_credit, \
reissue_invoice, refund_charge, get_billing_record, get_device_status, \
customer_toggle_ios_permission, customer_relogin_app, send_test_push, \
get_sync_status, cancel_sync_job, enable_incremental_sync, run_manual_sync, \
set_sync_direction, get_inventory, run_report, schedule_report, \
activate_schedule, send_report_now, regenerate_report, set_currency_rounding, \
validate_csv, customer_convert_csv_utf8, import_products, request_2fa_reset, \
verify_identity, reset_2fa, reenroll_2fa, get_api_usage, increase_rate_limit, \
switch_to_webhooks, erase_customer_data, merge_accounts, set_scanner_mode, \
grant_permissions, pair_scanner_in_app, get_known_issue, \
apply_mobile_workaround, notify_release."""

SYSTEM_PROMPT_MEMORY_SENTENCE = (
    "You have access to shared memory via context_search; search before solving."
)


def sanitize_ticket(ticket: dict) -> dict:
    """Return the agent-visible view of a ticket (no ground truth)."""
    return {
        "id": ticket["id"],
        "persona": ticket["persona"],
        "channel": ticket["channel"],
        "subject": ticket["subject"],
        "body": ticket["body"],
        "date": ticket.get("date", ""),
    }


def parse_llm_json(text: str) -> dict | None:
    """Extract the first JSON object from LLM output; None on failure."""
    if not text:
        return None
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


@dataclass
class AgentContext:
    condition: str  # "A" | "B"
    meko: BaseMekoClient
    kb: LocalKB
    mock: MockOrderLoop
    llm: LLMClient
    agent_id: str
    conversation_id: str = ""
    trace: list = field(default_factory=list)

    def log(self, event: str, detail: dict | None = None) -> None:
        self.trace.append({"event": event, **(detail or {})})


@dataclass
class AgentResult:
    agent: str
    diagnosis: str
    steps: list
    actions: list  # [{op, args, ok, message}]
    used_memory: bool
    memory_id: str | None
    memory_cluster: str | None
    confidence: float
    escalated: bool
    escalation_reason: str
    verified: bool
    verify_checks: dict
    final_answer: str
    input_tokens: int
    output_tokens: int
    tool_calls: dict
    trace: list
    llm_calls: int
    memory_key: str | None = None
    parse_failed: bool = False


def _is_fix_memory(hit: dict) -> bool:
    """True when a memory hit is an agent-stored fix, not an auto-extracted fact.

    Fix memories carry metadata.source == "agent" (and a memory_key);
    auto-extracted facts carry empty metadata. A fix and a fact can match
    the same ticket, and the fact can rank higher — in the spike (26 Nov
    2026) a fact outranked the T-001 fix on T-003 and the agent reused the
    fact instead of the fix.
    """
    meta = hit.get("metadata") or {}
    return meta.get("source") == "agent" or bool(meta.get("memory_key"))


def prefer_fix_memories(hits: list) -> list:
    """Stable-sort memory hits: agent-stored fixes first, facts after.

    The relative order inside each group is preserved, so the server's
    ranking still decides among fixes and among facts. Classification is
    untouched — only which hit the agent is shown first (and picks) changes.
    """
    return sorted(hits, key=lambda h: 0 if _is_fix_memory(h) else 1)


def _format_search_results(search: dict) -> str:
    """Render context_search buckets as prompt text for the LLM."""
    buckets = search.get("buckets", {}) if isinstance(search, dict) else {}
    lines = [f"match_quality: {search.get('match_quality', 'unknown')}",
             f"agent_hint: {search.get('agent_hint', '')}"]
    for hit in buckets.get("memory", []) or []:
        meta = hit.get("metadata", {}) or {}
        cluster = meta.get("cluster", "?")
        lines.append(f"MEMORY HIT (cluster {cluster}, id {hit.get('memory_id')}): {hit.get('text', '')}")
    for hit in buckets.get("knowledge_base", []) or []:
        lines.append(f"KB ARTICLE [{hit.get('title', '')}]: {hit.get('excerpt', '')}")
    for hit in buckets.get("conversation", []) or []:
        lines.append(f"PAST CONVERSATION: {hit.get('excerpt', '')}")
    if len(lines) <= 2:
        lines.append("(no relevant memory, knowledge base article, or past conversation found)")
    return "\n".join(lines)


def _execute_actions(actions: list, ctx: AgentContext) -> tuple[list, dict]:
    """Run the LLM plan's mock ops. Returns (executed actions, tool counts)."""
    executed = []
    tool_calls: dict[str, int] = {}
    for action in actions or []:
        op = action.get("op")
        args = action.get("args") or {}
        if not isinstance(op, str):
            continue
        res = ctx.mock.execute(op, args)
        tool_calls[op] = tool_calls.get(op, 0) + 1
        ctx.log("mock_op", {"op": op, "ok": res.get("ok")})
        executed.append({"op": op, "args": args, "ok": bool(res.get("ok")),
                         "message": res.get("message", "")})
    return executed, tool_calls


def _fallback_plan(raw_text: str) -> dict:
    return {"diagnosis": "Could not parse a plan; escalating.",
            "steps": [], "actions": [], "confidence": 0.2,
            "needs_human": True, "used_memory": False,
            "memory_summary": None, "final_answer": raw_text[:500]}


class TriageAgent:
    """First contact: search (condition B), classify, solve or hand off."""

    def __init__(self, llm: LLMClient, agent_id: str = "orderloop-triage"):
        self.llm = llm
        self.agent_id = agent_id

    def handle(self, view: dict, ctx: AgentContext, full_ticket: dict) -> AgentResult:
        ctx.log("ticket_received", {"ticket_id": view["id"], "agent": "triage"})
        tool_calls: dict[str, int] = {}

        # 1. SEARCH BEFORE SOLVING (condition B only; harness enforces it).
        search_text = "(no memory search in condition A)"
        memory_hit = None
        if ctx.condition == "B":
            query = f"{view['subject']}\n{view['body']}"
            search = ctx.meko.context_search(query, limit=5,
                                             conversation_id=ctx.conversation_id,
                                             agent_id=self.agent_id)
            tool_calls["context_search"] = tool_calls.get("context_search", 0) + 1
            mem_hits = (search.get("buckets") or {}).get("memory", []) or []
            # Prefer agent-stored fixes over auto-extracted facts (spike
            # 26 Nov 2026: a fact outranked the fix on T-003). Reorder the
            # bucket too, so the prompt and the pick agree on which hit is
            # first — the stub (and the real model) reuse the first hit.
            mem_hits = prefer_fix_memories(mem_hits)
            if isinstance(search.get("buckets"), dict):
                search["buckets"]["memory"] = mem_hits
            ctx.log("context_search", {"match_quality": search.get("match_quality"),
                                       "memory_hits": len(mem_hits)})
            search_text = _format_search_results(search)
            if mem_hits:
                memory_hit = mem_hits[0]
        else:
            kb_hits = ctx.kb.search(f"{view['subject']} {view['body']}", limit=3)
            tool_calls["kb_search"] = tool_calls.get("kb_search", 0) + 1
            lines = [f"KB ARTICLE [{h['title']}]: {h['excerpt']}" for h in kb_hits]
            search_text = "\n".join(lines) if lines else "(no relevant knowledge base article found)"

        # 2. Ask the LLM for a plan.
        system = SYSTEM_PROMPT_BASE
        if ctx.condition == "B":
            system += "\n" + SYSTEM_PROMPT_MEMORY_SENTENCE
        user = (f"Ticket {view['id']} ({view['channel']}) from "
                f"{view['persona']['name']}, {view['persona']['role']} at "
                f"{view['persona']['company']} (plan {view['persona']['plan']}):\n"
                f"Subject: {view['subject']}\nBody:\n{view['body']}\n\n"
                f"Retrieved context:\n{search_text}\n\n"
                f"Return the JSON plan.")
        result = self.llm.generate(system, user, temperature=0.0)
        plan = parse_llm_json(result.text)
        parse_failed = plan is None
        if parse_failed:
            plan = _fallback_plan(result.text)

        # 3. Escalate to Specialist when unsure (or when the plan says so).
        if plan.get("needs_human") or float(plan.get("confidence", 0) or 0) < 0.6:
            ctx.log("handoff_to_specialist",
                    {"reason": "needs_human" if plan.get("needs_human") else "low confidence",
                     "confidence": plan.get("confidence")})
            specialist = SpecialistAgent(self.llm)
            spec = specialist.handle(view, ctx, full_ticket, handoff={
                "triage_diagnosis": plan.get("diagnosis", ""),
                "memory_hit": memory_hit,
            })
            spec.input_tokens += result.input_tokens
            spec.output_tokens += result.output_tokens
            spec.llm_calls += 1
            for k, v in tool_calls.items():
                spec.tool_calls[k] = spec.tool_calls.get(k, 0) + v
            # NB: spec.trace already contains the full trace (the specialist
            # logs into the shared ctx.trace, and its result returns a copy
            # of it). Do NOT concatenate ctx.trace again — that duplicated
            # every event (spike 2026-11-26).
            return spec

        # 4. Execute the plan's actions against the mock.
        actions, exec_calls = _execute_actions(plan.get("actions") or [], ctx)
        for k, v in exec_calls.items():
            tool_calls[k] = tool_calls.get(k, 0) + v
        verify = ctx.mock.verify_fix(full_ticket)
        ctx.log("verified", {"resolved": verify["resolved"], "checks": verify["checks"]})
        return AgentResult(
            agent="triage",
            diagnosis=str(plan.get("diagnosis", "")),
            steps=list(plan.get("steps") or []),
            actions=actions,
            used_memory=bool(plan.get("used_memory")) and memory_hit is not None,
            memory_id=(memory_hit or {}).get("memory_id") if memory_hit else None,
            memory_cluster=((memory_hit or {}).get("metadata") or {}).get("cluster"),
            memory_key=((memory_hit or {}).get("metadata") or {}).get("memory_key"),
            confidence=float(plan.get("confidence", 0) or 0),
            escalated=False, escalation_reason="",
            verified=bool(verify["resolved"]), verify_checks=verify["checks"],
            final_answer=str(plan.get("final_answer", "")),
            input_tokens=result.input_tokens, output_tokens=result.output_tokens,
            tool_calls=tool_calls, trace=list(ctx.trace), llm_calls=1,
            parse_failed=parse_failed,
        )


class SpecialistAgent:
    """Deep diagnosis: takes a handoff, solves, executes, verifies."""

    def __init__(self, llm: LLMClient, agent_id: str = "orderloop-specialist"):
        self.llm = llm
        self.agent_id = agent_id

    def handle(self, view: dict, ctx: AgentContext, full_ticket: dict,
               handoff: dict | None = None) -> AgentResult:
        handoff = handoff or {}
        ctx.log("specialist_received", {"ticket_id": view["id"]})
        memory_hit = handoff.get("memory_hit")
        search_lines = []
        if memory_hit:
            meta = memory_hit.get("metadata", {}) or {}
            search_lines.append(
                f"MEMORY HIT (cluster {meta.get('cluster', '?')}, "
                f"id {memory_hit.get('memory_id')}): {memory_hit.get('text', '')}")
        kb_hits = ctx.kb.search(f"{view['subject']} {view['body']}", limit=3)
        for h in kb_hits:
            search_lines.append(f"KB ARTICLE [{h['title']}]: {h['excerpt']}")
        search_text = "\n".join(search_lines) if search_lines else "(no relevant context found)"

        system = SYSTEM_PROMPT_BASE
        if ctx.condition == "B":
            system += "\n" + SYSTEM_PROMPT_MEMORY_SENTENCE
        user = (f"You are the specialist. Triage handed this ticket to you.\n"
                f"Triage diagnosis: {handoff.get('triage_diagnosis', '')}\n"
                f"Ticket {view['id']} ({view['channel']}) from "
                f"{view['persona']['name']}, {view['persona']['role']} at "
                f"{view['persona']['company']} (plan {view['persona']['plan']}):\n"
                f"Subject: {view['subject']}\nBody:\n{view['body']}\n\n"
                f"Retrieved context:\n{search_text}\n\n"
                f"Diagnose carefully, execute the fix with the mock operations, "
                f"and verify. Return the JSON plan.")
        result = self.llm.generate(system, user, temperature=0.0)
        plan = parse_llm_json(result.text)
        parse_failed = plan is None
        if parse_failed:
            plan = _fallback_plan(result.text)

        actions, tool_calls = _execute_actions(plan.get("actions") or [], ctx)
        verify = ctx.mock.verify_fix(full_ticket)
        ctx.log("verified", {"resolved": verify["resolved"], "checks": verify["checks"]})
        needs_human = bool(plan.get("needs_human")) or float(plan.get("confidence", 0) or 0) < 0.4
        return AgentResult(
            agent="specialist",
            diagnosis=str(plan.get("diagnosis", "")),
            steps=list(plan.get("steps") or []),
            actions=actions,
            used_memory=bool(plan.get("used_memory")) and memory_hit is not None,
            memory_id=(memory_hit or {}).get("memory_id") if memory_hit else None,
            memory_cluster=((memory_hit or {}).get("metadata") or {}).get("cluster"),
            memory_key=((memory_hit or {}).get("metadata") or {}).get("memory_key"),
            confidence=float(plan.get("confidence", 0) or 0),
            escalated=needs_human,
            escalation_reason="specialist could not solve confidently" if needs_human else "",
            verified=bool(verify["resolved"]), verify_checks=verify["checks"],
            final_answer=str(plan.get("final_answer", "")),
            input_tokens=result.input_tokens, output_tokens=result.output_tokens,
            tool_calls=tool_calls, trace=list(ctx.trace), llm_calls=1,
            parse_failed=parse_failed,
        )
