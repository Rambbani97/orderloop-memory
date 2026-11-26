"""Experiment harness — replay the 36-ticket dataset, condition A vs B.

Protocol (dataset-design.md §5.2, §5.3):
- Tickets replayed in file order (seeds before their repeats).
- Condition B: the agent MUST call ``context_search`` before any fix op;
  a violation is recorded in the metrics (and the run continues).
- Condition A: zero Meko calls allowed.
- Same model, temperature 0, same system prompt (except the one memory
  sentence in B), same KB/mock for both conditions.
- Ground truth is NEVER shown to the agent — only to
  :meth:`MockOrderLoop.verify_fix` and the automatic quality scorer, which is
  a PROXY for the human blind rubric (dataset-design.md §5.1 M8). Official
  quality numbers come from blind human rating; M8-auto is for smoke tests
  and iteration only.
- HITL: after each first-time ticket the fix is proposed to the approval
  queue. In ``auto`` mode it is approved immediately (TEST-ONLY — violates
  the HITL rule, never use for official runs). In ``manual`` mode it stays
  pending and the run WAITS (condition B only) for a human decision on
  that item before the next ticket — polled from disk every 10 s, max
  30 min per item, then it continues and the repeat honestly misses.
  The wait happens after the ticket metrics are recorded, so M1 (seconds
  per ticket) is never contaminated by waiting. Approve via the dashboard
  or scripts/approve_pending.py (chat flow). The queue is refreshed from
  disk before each propose() so an external decision is never reverted
  by a stale in-memory save.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.agents import AgentContext, TriageAgent, sanitize_ticket
from app.hitl import HITLQueue
from app.kb import LocalKB
from app.llm import LLMClient
from app.meko_client import BaseMekoClient
from app.metrics import MetricsRecorder, TicketMetrics, cost_usd, write_summary_csv
from app.mock_orderloop import FIX_RECIPES, MockOrderLoop

# ---------------------------------------------------------------------------
# Dataset helpers
# ---------------------------------------------------------------------------

def load_tickets(path: str | Path) -> list[dict]:
    tickets = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                tickets.append(json.loads(line))
    return tickets


def ticket_kind(ticket: dict) -> str:
    """first-time | repeat | distractor | unique (dataset-design.md §5.1).

    Schema: clusters C1–C8; distractors have cluster "distractor" with
    ids D-01..D-03 and a target_cluster; uniques have cluster "unique"
    with ids U-01..U-09.
    """
    if ticket["cluster"] == "distractor":
        return "distractor"
    if ticket["cluster"] == "unique":
        return "unique"
    if ticket.get("memory_key"):
        return "repeat"
    return "first-time"


# ---------------------------------------------------------------------------
# Automatic quality scorer (M8 proxy — NOT the official human rubric)
# ---------------------------------------------------------------------------

DIAGNOSIS_KEYWORDS: dict[str, list[str]] = {
    "C1": ["webhook", "secret", "stripe", "signing", "400"],
    "C2": ["saml", "certificate", "expired", "idp", "signature", "metadata"],
    "C3": ["proration", "credit", "invoice", "vat", "tax"],
    "C4": ["push", "apns", "token", "ios", "notification", "permission"],
    "C5": ["sync", "shopify", "rate limit", "429", "stuck"],
    "C6": ["report", "timeout", "aggregat", "range"],
    "C7": ["csv", "utf-8", "encoding", "ansi", "bom"],
    "C8": ["2fa", "authenticator", "recovery", "reset", "code"],
    "D-01": ["endpoint", "url", "domain", "200", "routing"],
    "D-02": ["assign", "user", "authoris", "okta", "app"],
    "D-03": ["sync direction", "pos", "overwrite", "source of truth"],
    "U-01": ["duplicate", "charge", "refund", "invoice"],
    "U-02": ["rate limit", "webhook", "polling", "enterprise", "plan"],
    "U-03": ["gdpr", "erasure", "deletion", "data", "dpo"],
    "U-04": ["barcode", "scanner", "bluetooth", "permission", "spp"],
    "U-05": ["rounding", "currency", "decimal", "idr", "usd"],
    "U-06": ["scheduled", "report", "active", "email"],
    "U-07": ["merge", "account", "duplicate"],
    "U-08": ["custom field", "webhook", "loyalty_tier", "mapping"],
    "U-09": ["crash", "android 12", "mob-2214", "workaround", "release"],
}

# Expected mock ops for the correct fix, per cluster / ticket. Uniques and
# distractors are keyed by ticket id; clusters by cluster id.
EXPECTED_OPS: dict[str, list[str]] = {
    **{c: list(ops) for c, ops in FIX_RECIPES.items()},
    "D-01": ["customer_fix_webhook_url", "webhook_send_test_event"],
    "D-02": ["saml_assign_user", "saml_test_login"],
    "D-03": ["set_sync_direction", "run_manual_sync"],
    "U-01": ["get_invoice", "refund_charge"],
    "U-02": ["get_api_usage", "switch_to_webhooks"],  # or increase_rate_limit
    "U-03": ["erase_customer_data"],
    "U-04": ["set_scanner_mode", "pair_scanner_in_app"],
    "U-05": ["set_currency_rounding"],
    "U-06": ["schedule_report", "activate_schedule", "send_report_now"],
    "U-07": ["merge_accounts"],
    "U-08": ["webhook_set_custom_fields"],
    "U-09": ["get_known_issue", "apply_mobile_workaround", "notify_release"],
}

# U-02 accepts either the webhook switch or a rate-limit increase.
U02_ALTERNATIVE = {"switch_to_webhooks", "increase_rate_limit"}

CHECK_OPS = {"get_order", "get_webhook_status", "get_saml_status", "get_invoice",
             "get_billing_record", "get_device_status", "get_sync_status",
             "get_inventory", "get_api_usage", "get_known_issue"}


def _content_words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9][a-z0-9\-]+", text.lower()))


def score_auto(ticket: dict, result, verify: dict) -> dict:
    """M8 proxy: diagnosis 30 + steps 40 + hallucination 20 + tone 10 (+5 bonus)."""
    text = f"{result.diagnosis} {result.final_answer}".lower()
    key = ticket["cluster"] if ticket["cluster"] in DIAGNOSIS_KEYWORDS else ticket["id"]
    keywords = DIAGNOSIS_KEYWORDS.get(key, [])
    matched = sum(1 for kw in keywords if kw.lower() in text)
    diagnosis = 30.0 * (matched / len(keywords)) if keywords else 0.0

    # Wrong-direction check (distractors): if the agent's text matches the
    # target cluster's keywords better than the correct ones, diagnosis = 0.
    wrong = 0.0
    if ticket.get("target_cluster"):
        wrong_kw = DIAGNOSIS_KEYWORDS.get(ticket["target_cluster"], [])
        wrong_matches = sum(1 for kw in wrong_kw if kw.lower() in text)
        if wrong_matches >= 2 and wrong_matches > matched:
            diagnosis = 0.0
            wrong = 1.0

    executed_ops = [a["op"] for a in result.actions]
    expected = EXPECTED_OPS.get(key, [])
    if ticket["id"] == "U-02":
        expected = ["get_api_usage"] + (["switch_to_webhooks"]
                                         if "switch_to_webhooks" in executed_ops
                                         else ["increase_rate_limit"])
    matched_ops = sum(1 for op in expected if op in executed_ops)
    steps = 40.0 * (matched_ops / len(expected)) if expected else 0.0
    if ticket.get("target_cluster"):
        wrong_ops = FIX_RECIPES.get(ticket["target_cluster"], [])
        if any(op in executed_ops for op in wrong_ops) and matched_ops == 0:
            steps = 0.0

    unknown = sum(1 for a in result.actions
                  if a.get("message", "").startswith("Unknown operation"))
    failed = sum(1 for a in result.actions if not a.get("ok") and not a.get("message", "").startswith("Unknown"))
    hallucination = max(0.0, 20.0 - 10.0 * unknown - 5.0 * min(failed, 2))

    answer = result.final_answer or ""
    if len(answer) > 50 and any(w in answer.lower() for w in
                                ("verif", "confirm", "let me know", "next step", "please")):
        tone = 10.0
    elif answer.strip():
        tone = 5.0
    else:
        tone = 0.0

    bonus = 5.0 if verify.get("resolved") else 0.0
    total = min(100.0, diagnosis + steps + hallucination + tone + bonus)
    return {"total": round(total, 1),
            "diagnosis": round(diagnosis, 1), "steps": round(steps, 1),
            "hallucination": round(hallucination, 1), "tone": round(tone, 1),
            "bonus": round(bonus, 1), "wrong_direction": bool(wrong)}


def build_trace_messages(ticket: dict, result) -> list[dict]:
    """Minimal Meko conversation turn: the decision only.

    Meko auto-extracts fact memories from every recorded turn; logging the
    full ticket body + final answer produced 6 fact memories from 1 ticket
    in the spike (26 Nov 2026), and one of those facts outranked the real
    fix on T-003. Keep only what the decision trace needs — ticket id +
    subject (the label, not the body), the diagnosis, the executed ops and
    the verification outcome. Customer names, order numbers, symptom
    details and the final answer are NOT logged. The full trace (including
    the body) stays in the harness metrics, which is what the demo reads.
    """
    ops = ", ".join(a["op"] for a in result.actions) or "no ops"
    diagnosis = (result.diagnosis or "").strip()
    if len(diagnosis) > 200:
        diagnosis = diagnosis[:197] + "..."
    return [
        {"role": "user",
         "content": f"Ticket {ticket['id']} ({ticket['cluster']}): {ticket['subject']}"},
        {"role": "assistant",
         "content": f"Diagnosis: {diagnosis} | ops: {ops} | verified: {result.verified}"},
    ]


def build_memory_text(ticket: dict, result, verify: dict) -> str:
    """Human-readable fix text proposed to HITL (generic, customer-agnostic)."""
    lines = [
        f"FIX [{ticket['cluster']} — {ticket['subject']}]",
        f"Diagnosis: {result.diagnosis}",
        "Steps:",
    ]
    for i, step in enumerate(result.steps or [], 1):
        lines.append(f"{i}. {step}")
    if not result.steps:
        lines.append("1. (no steps recorded — see executed operations)")
        for a in result.actions:
            lines.append(f"   - {a['op']}")
    checks = ", ".join(f"{k}={v}" for k, v in (verify.get("checks") or {}).items())
    lines.append(f"Verified in mock: {checks or 'not verified'}")
    lines.append(f"Source ticket: {ticket['id']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HITL wait (manual mode, condition B only)
# ---------------------------------------------------------------------------

def wait_for_hitl_decision(queue_path, item_id: str, timeout_s: float = 1800.0,
                           poll_interval_s: float = 10.0,
                           sleep=time.sleep) -> str:
    """Poll the HITL queue file from disk until ``item_id`` is decided.

    Returns ``"approved"`` | ``"rejected"`` | ``"timeout"`` | ``"missing"``.

    The queue is re-read from disk on every poll (a fresh ``HITLQueue``),
    because the decision is made by a separate process — the dashboard or
    scripts/approve_pending.py (chat flow) — never by this process's
    in-memory queue. ``"missing"`` means the item is no longer in the file
    (queue reset); waiting for it would be pointless.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        queue = HITLQueue(queue_path)
        item = next((i for i in queue.items if i.item_id == item_id), None)
        if item is None:
            return "missing"
        if item.status != "pending":
            return item.status  # "approved" or "rejected"
        if time.monotonic() >= deadline:
            return "timeout"
        sleep(poll_interval_s)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

@dataclass
class Harness:
    condition: str  # "A" | "B"
    run_no: int
    llm: LLMClient
    meko: BaseMekoClient
    kb: LocalKB
    hitl: HITLQueue
    hitl_mode: str = "manual"  # manual | auto (auto = test-only)
    hitl_wait: bool = True  # manual B: wait for the decision before next ticket
    hitl_wait_timeout_s: float = 1800.0  # max wait per proposed fix (30 min)
    hitl_wait_poll_s: float = 10.0  # disk poll interval while waiting
    results_dir: str | Path = "results"
    model: str = "stub-llm/1.0"
    temperature: float = 0.0
    limit: int | None = None
    verbose: bool = True

    def __post_init__(self) -> None:
        self.results_dir = Path(self.results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = f"{self.condition}{self.run_no}"
        self.recorder = MetricsRecorder(self.results_dir / f"run-{self.run_id}.jsonl")
        self.triage = TriageAgent(self.llm)

    # ------------------------------------------------------------------
    def run(self, tickets: list[dict],
            skip_ids: set[str] | frozenset | None = None) -> dict:
        """Replay tickets; ``skip_ids`` (crash-resume) skips tickets whose
        record already exists in the run JSONL — they are never re-run, so
        no fix is re-proposed and no record is duplicated.

        The summary is regenerated from the whole JSONL file when
        resuming, so it covers every ticket (recorded + newly run), not
        just this process's tickets. Fresh runs summarize from memory
        (identical content — the file holds exactly what this process
        wrote).
        """
        tickets = tickets[: self.limit] if self.limit else tickets
        resuming = bool(skip_ids)
        if resuming:
            skipped = [t for t in tickets if t["id"] in skip_ids]
            todo = [t for t in tickets if t["id"] not in skip_ids]
            if self.verbose:
                print(f"[{self.run_id}] resuming: skipping {len(skipped)} "
                      f"already-recorded tickets "
                      f"({', '.join(t['id'] for t in skipped)})")
        else:
            todo = list(tickets)
        for ticket in todo:
            self.run_ticket(ticket)
        if resuming:
            # Re-read the file: the durable record, not this process's
            # memory, is what the final summary must describe.
            final = MetricsRecorder(self.recorder.path)
            final.load_existing()
            summary = final.summarize()
        else:
            summary = self.recorder.summarize()
        summary_path = self.results_dir / f"run-{self.run_id}-summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        write_summary_csv(summary, self.results_dir / f"run-{self.run_id}-summary.csv")
        if self.verbose:
            print(f"\n[{self.run_id}] done: {len(tickets)} tickets, "
                  f"summary -> {summary_path}")
        return summary

    # ------------------------------------------------------------------
    def run_ticket(self, ticket: dict) -> TicketMetrics:
        started = time.monotonic()
        kind = ticket_kind(ticket)
        mock = MockOrderLoop()
        mock.reset_for_ticket(ticket)
        view = sanitize_ticket(ticket)
        ctx = AgentContext(condition=self.condition, meko=self.meko, kb=self.kb,
                           mock=mock, llm=self.llm, agent_id="orderloop-triage",
                           conversation_id=f"{self.run_id}-{ticket['id']}")

        calls_before = len(getattr(self.meko, "calls", []) or [])
        result = self.triage.handle(view, ctx, full_ticket=ticket)
        elapsed = time.monotonic() - started
        calls_after = len(getattr(self.meko, "calls", []) or [])

        # --- protocol enforcement --------------------------------------
        violation = self._check_protocol(ctx, calls_before, calls_after)

        # --- retrieval classification (condition B only) ---------------
        retrieval = self._classify_retrieval(ticket, kind, result)

        # --- quality (automatic proxy) ---------------------------------
        score = score_auto(ticket, result, {"resolved": result.verified})
        verify_checks = result.verify_checks

        # --- HITL: first-time fixes are proposed as new memory --------
        hitl_status = "not_proposed"
        proposed_item = None
        if kind in ("first-time", "unique"):
            text = build_memory_text(ticket, result, {"resolved": result.verified,
                                                      "checks": verify_checks})
            metadata = {"ticket_id": ticket["id"], "cluster": ticket["cluster"],
                        "memory_key": ticket["id"], "source": "agent",
                        "agent": result.agent, "run_id": self.run_id}
            # Refresh from disk first: an external approver (chat CLI /
            # dashboard) may have decided earlier items in another process;
            # proposing on a stale in-memory list would _save() those
            # decisions back to pending.
            self.hitl.refresh()
            item = self.hitl.propose(ticket["id"], ticket["cluster"], text,
                                     metadata, proposed_by=result.agent)
            proposed_item = item
            if self.hitl_mode == "auto":
                # TEST-ONLY: violates the HITL rule; never for official runs.
                self.hitl.approve(item.item_id, decided_by="auto-test")
                if self.condition == "B":
                    # Condition A never writes memory (no Meko at all).
                    self.meko.memory_add(text, metadata, agent_id="orderloop-triage")
                hitl_status = "approved"
            else:
                hitl_status = "pending"

        # --- minimal conversation trace (condition B) -------------------
        # A Meko turn is logged only when the ticket created shared memory
        # (a fix was proposed to HITL). Every recorded turn is mined for
        # auto-extracted facts, so logging all 36 tickets (full bodies)
        # seeded the datapack with facts that outrank fixes. Reuse and
        # abstain decisions are traced in the harness metrics — which is
        # what the demo reads — not in Meko.
        if self.condition == "B" and hitl_status != "not_proposed":
            try:
                self.meko.conversation_capture(
                    ctx.conversation_id,
                    build_trace_messages(ticket, result),
                    agent_id="orderloop-triage")
            except Exception:
                pass

        metrics = TicketMetrics(
            run_id=self.run_id, condition=self.condition, run_no=self.run_no,
            ticket_id=ticket["id"], cluster=ticket["cluster"], kind=kind,
            agent=result.agent,
            m1_seconds=round(elapsed, 3),
            m2_input_tokens=result.input_tokens,
            m3_output_tokens=result.output_tokens,
            m4_total_tokens=result.input_tokens + result.output_tokens,
            m5_steps=len(result.actions),
            m6_tool_calls=result.tool_calls,
            m7_retrieval=retrieval,
            m8_quality_auto=score["total"], m8_quality_breakdown=score,
            m9_escalated=result.escalated,
            m9_escalation_reason=result.escalation_reason,
            m10_cost_usd=round(cost_usd(self.model, result.input_tokens,
                                         result.output_tokens), 6),
            protocol_violation=violation,
            verified=result.verified, verify_checks=verify_checks,
            used_memory=result.used_memory, memory_id=result.memory_id,
            hitl_status=hitl_status,
            model=self.model, temperature=self.temperature,
            datapack_id=getattr(self.meko, "config", None) and
                        getattr(self.meko.config, "datapack_id", "") or "",
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            trace=result.trace,
        )
        self.recorder.record(metrics)
        if self.verbose:
            print(f"[{self.run_id}] {ticket['id']} {kind:12} agent={result.agent:10} "
                  f"q={score['total']:5.1f} ret={retrieval:19} "
                  f"tok={metrics.m4_total_tokens:4} t={elapsed:5.2f}s "
                  f"{'VIOLATION' if violation else ''}")

        # --- HITL wait (manual mode, condition B only) ------------------
        # Metrics are already recorded above, so the wait can never
        # contaminate M1. Condition A never writes memory, so waiting
        # there could unblock nothing (and the default A smoke command
        # runs in manual mode — it must not hang). The harness never
        # writes memory_add while waiting: whoever approves (dashboard /
        # chat CLI) is the one who writes, exactly like the dashboard.
        if (self.condition == "B" and self.hitl_mode == "manual"
                and hitl_status == "pending" and proposed_item is not None
                and self.hitl_wait):
            if self.verbose:
                print(f"[{self.run_id}] waiting for HITL decision on "
                      f"{proposed_item.item_id} ({ticket['id']}) — "
                      f"approve/reject via dashboard or approve_pending.py")
            waited_from = time.monotonic()
            outcome = wait_for_hitl_decision(
                self.hitl.path, proposed_item.item_id,
                timeout_s=self.hitl_wait_timeout_s,
                poll_interval_s=self.hitl_wait_poll_s)
            waited = time.monotonic() - waited_from
            if self.verbose:
                if outcome == "timeout":
                    print(f"[{self.run_id}] WARNING: HITL {proposed_item.item_id} "
                          f"undecided after {waited:.0f}s — continuing; "
                          f"its repeats will honestly miss")
                else:
                    print(f"[{self.run_id}] HITL {proposed_item.item_id}: "
                          f"{outcome} (waited {waited:.0f}s)")
        return metrics

    # ------------------------------------------------------------------
    def _check_protocol(self, ctx: AgentContext, before: int, after: int) -> bool:
        """True if the protocol was violated."""
        # Condition A: zero Meko calls.
        if self.condition == "A":
            if after - before > 0:
                return True
            return any(e.get("event") == "context_search" for e in ctx.trace)
        # Condition B: context_search before any fix op.
        search_idx = next((i for i, e in enumerate(ctx.trace)
                           if e.get("event") == "context_search"), None)
        op_idx = next((i for i, e in enumerate(ctx.trace)
                       if e.get("event") == "mock_op"), None)
        if search_idx is None:
            return True  # no search at all
        if op_idx is not None and op_idx < search_idx:
            return True
        return False

    # ------------------------------------------------------------------
    def _classify_retrieval(self, ticket: dict, kind: str, result) -> str:
        if self.condition == "A":
            return "na"
        if kind == "first-time":
            return "na"
        if kind == "repeat":
            # Hit = the used memory's memory_key is this ticket's seed.
            if result.used_memory and result.memory_key == ticket.get("memory_key"):
                return "hit"
            return "miss"
        # distractor / unique: any reuse of a cluster memory is false reuse.
        wrong_ops = FIX_RECIPES.get(ticket.get("target_cluster", ""), [])
        used_wrong_op = any(a["op"] in wrong_ops for a in result.actions)
        if (result.used_memory and result.memory_cluster == ticket.get("target_cluster")) \
                or used_wrong_op:
            return "false_reuse"
        if result.used_memory:
            return "false_reuse"
        return "correct_abstention"
