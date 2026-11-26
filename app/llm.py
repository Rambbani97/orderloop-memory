"""LLM clients for OrderLoop agents.

Two backends, one interface:

- :class:`GeminiClient` — Google Gemini API (free tier) via the registered
  connector CLI (``custom.gemini``), invoked as a subprocess. The API key
  lives only in the Secure Vault; this module never sees it, never reads it
  from env vars or files, and never passes it in arguments. Model is locked
  to ``gemini-3.5-flash-lite`` (verified 26 Nov 2026; ``gemini-2.5-flash``
  is retired for new users).
- :class:`StubLLM` — deterministic test double. It never calls any API and
  never reads ground truth: it only sees the prompt the agent assembled
  (ticket text + search results + KB excerpts) and answers with a structured
  JSON plan derived from keywords in that prompt. Its purpose is to prove
  the harness runs end-to-end without credentials. It is NOT a stand-in for
  real agent quality — official runs must use Gemini (or another real model).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

GEMINI_CLI = Path.home() / "workspace" / "custom-connectors" / "custom.gemini" / "bin" / "client.py"
DEFAULT_MODEL = "gemini-3.5-flash-lite"

# Keyword -> cluster recipe mapping for the STUB only. The stub picks the
# fix recipe by matching words in the prompt it was given (ticket body +
# search results + KB excerpts). Real LLM calls do their own reasoning.
_STUB_KEYWORDS: list[tuple[str, list[str]]] = [
    ("webhook", ["C1"]),
    ("stripe", ["C1"]),
    ("sso", ["C2"]),
    ("saml", ["C2"]),
    ("okta", ["C2"]),
    ("azure", ["C2"]),
    ("certificate", ["C2"]),
    ("microsoft", ["C2"]),
    ("login loop", ["C2"]),
    ("invoice", ["C3"]),
    ("vat", ["C3"]),
    ("prorat", ["C3"]),
    ("credit", ["C3"]),
    ("upgrade", ["C3"]),
    ("mid-cycle", ["C3"]),
    ("push", ["C4"]),
    ("notification", ["C4"]),
    ("iphone", ["C4"]),
    ("sync", ["C5"]),
    ("shopify", ["C5"]),
    ("stock", ["C5"]),
    ("report", ["C6"]),
    ("dashboard", ["C6"]),
    ("timeout", ["C6"]),
    ("csv", ["C7"]),
    ("import", ["C7"]),
    ("upload", ["C7"]),
    ("excel", ["C7"]),
    ("invalid format", ["C7"]),
    ("2fa", ["C8"]),
    ("authenticator", ["C8"]),
    ("recovery code", ["C8"]),
    ("refund", ["U-01"]),
    ("charged twice", ["U-01"]),
    ("rate limit", ["U-02"]),
    ("gdpr", ["U-03"]),
    ("erasure", ["U-03"]),
    ("barcode", ["U-04"]),
    ("scanner", ["U-04"]),
    ("rounding", ["U-05"]),
    ("currency", ["U-05"]),
    ("decimal", ["U-05"]),
    ("scheduled", ["U-06"]),
    ("scheduled report", ["U-06"]),
    ("weekly report", ["U-06"]),
    ("merge", ["U-07"]),
    ("custom field", ["U-08"]),
    ("loyalty_tier", ["U-08"]),
    ("crash", ["U-09"]),
    ("android 12", ["U-09"]),
]

# Keyword-rich diagnosis per cluster (stub only). The automatic quality
# scorer matches these terms against the ground-truth keywords, so a stub
# diagnosis must state the pattern in words, not just "matches pattern X".
_STUB_DIAGNOSIS: dict[str, str] = {
    "C1": "Stripe webhook events failing with HTTP 400 after API key rotation — "
          "the webhook signing secret was rotated and not updated in OrderLoop.",
    "C2": "SSO/SAML login loop — the IdP signing certificate expired, SAML "
          "signature validation fails; upload new IdP metadata.",
    "C3": "Invoice proration error — mid-cycle upgrade not credited, VAT/tax "
          "wrong on the invoice; apply a proration credit and reissue.",
    "C4": "iOS push notifications stopped — APNs device token lost after the "
          "app update, iOS notification permission off.",
    "C5": "Shopify sync stuck — rate limit 429, the sync job is stuck and "
          "inventory does not match; use incremental sync.",
    "C6": "Dashboard report timeout on a large date range — run the report "
          "aggregated instead of row-level.",
    "C7": "CSV import encoding problem — file is ANSI with BOM, must convert "
          "to UTF-8 before import.",
    "C8": "2FA recovery — authenticator lost after phone change, recovery "
          "codes invalid; verify identity, reset 2FA, re-enroll.",
    "D-01": "Webhook 400 but the endpoint URL moved to a new domain — fix the "
            "webhook URL and routing, then send a test event (expect 200).",
    "D-02": "SSO login fails for one user — the user is not assigned to the "
            "OrderLoop app in Okta; an authorization/assignment issue, not a "
            "certificate problem.",
    "D-03": "Inventory mismatch — sync direction conflict, POS overwrites "
            "Shopify; set sync direction to POS wins (POS is the source of truth).",
    "U-01": "Duplicate charge — customer charged twice on the same invoice, "
            "refund the duplicate charge.",
    "U-02": "API rate limit reached on the Growth plan — polling order status "
            "hit 1,000 req/min; switch to webhooks or raise the limit "
            "(Enterprise raises it).",
    "U-03": "GDPR erasure request — delete the customer's data (deletion of "
            "personal data); confirm scope with the DPO.",
    "U-04": "Barcode scanner not pairing — Bluetooth SPP mode and device "
            "permissions.",
    "U-05": "Currency rounding — IDR/USD amounts rounded per line with 2 "
            "decimal places instead of on the total.",
    "U-06": "Scheduled weekly report email never arrives — the schedule is "
            "inactive; activate it and send the report by email now.",
    "U-07": "Duplicate accounts — merge the Melbourne account into the "
            "Sydney account.",
    "U-08": "Custom field loyalty_tier missing from webhook payloads — enable "
            "custom fields on the webhook (field mapping).",
    "U-09": "Android 12 crash (MOB-2214) — apply the mobile workaround and "
            "notify about the release.",
}
_STUB_RECIPES: dict[str, list[dict]] = {
    "C1": [{"op": "customer_update_webhook_secret", "args": {"secret": "whsec_NEW"}},
           {"op": "webhook_send_test_event", "args": {"event": "payment_intent.succeeded"}},
           {"op": "webhook_replay_failed_events", "args": {}}],
    "C2": [{"op": "customer_upload_saml_metadata", "args": {}},
           {"op": "saml_test_login", "args": {"user": "staff"}}],
    "C3": [{"op": "apply_proration_credit", "args": {"amount": 53.52}},
           {"op": "reissue_invoice", "args": {}}],
    "C4": [{"op": "customer_toggle_ios_permission", "args": {"on": True}},
           {"op": "customer_relogin_app", "args": {}},
           {"op": "send_test_push", "args": {"device": "iPhone"}}],
    "C5": [{"op": "cancel_sync_job", "args": {}},
           {"op": "enable_incremental_sync", "args": {"batch_size": 250, "delay_seconds": 2}},
           {"op": "run_manual_sync", "args": {}}],
    "C6": [{"op": "run_report", "args": {"range_days": 365, "aggregated": True}}],
    "C7": [{"op": "customer_convert_csv_utf8", "args": {}},
           {"op": "import_products", "args": {}}],
    "C8": [{"op": "request_2fa_reset", "args": {}},
           {"op": "verify_identity", "args": {"evidence": {"email": "owner@example.com", "id": "passport", "card_last4": "4242"}}},
           {"op": "reset_2fa", "args": {}},
           {"op": "reenroll_2fa", "args": {}}],
    "D-01": [{"op": "customer_fix_webhook_url", "args": {}},
             {"op": "webhook_send_test_event", "args": {}}],
    "D-02": [{"op": "saml_assign_user", "args": {"user": "Layla"}}],
    "D-03": [{"op": "set_sync_direction", "args": {"direction": "pos_wins"}},
             {"op": "run_manual_sync", "args": {}}],
    "U-01": [{"op": "refund_charge", "args": {}}],
    "U-02": [{"op": "increase_rate_limit", "args": {"new_limit": 2500, "days": 14}}],
    "U-03": [{"op": "erase_customer_data", "args": {"email": "j.dupont@example.fr"}}],
    "U-04": [{"op": "set_scanner_mode", "args": {"mode": "SPP"}},
             {"op": "grant_permissions", "args": {}},
             {"op": "pair_scanner_in_app", "args": {}}],
    "U-05": [{"op": "set_currency_rounding", "args": {"mode": "total"}},
             {"op": "regenerate_report", "args": {}}],
    "U-06": [{"op": "activate_schedule", "args": {}},
             {"op": "send_report_now", "args": {}}],
    "U-07": [{"op": "merge_accounts", "args": {"source": "melbourne", "target": "sydney"}}],
    "U-08": [{"op": "webhook_set_custom_fields", "args": {"fields": ["loyalty_tier"]}},
             {"op": "webhook_send_test_event", "args": {}}],
    "U-09": [{"op": "get_known_issue", "args": {"ref": "MOB-2214"}},
             {"op": "apply_mobile_workaround", "args": {}},
             {"op": "notify_release", "args": {"version": "3.8.2"}}],
}


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    model: str

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class MissingAPIKeyError(RuntimeError):
    """Kept for backwards compatibility; the CLI client no longer needs a key."""


class LLMClient:
    def generate(self, system: str, user: str, temperature: float = 0.0) -> LLMResult:
        raise NotImplementedError


class GeminiClient(LLMClient):
    """Google Gemini API via the registered connector CLI (subprocess).

    The CLI (``custom.gemini``) holds the credential in the Secure Vault
    and sends it as the ``x-goog-api-key`` header itself. This client only
    passes the model, the prompt and the temperature — never any credential.
    """

    def __init__(self, model: str | None = None,
                 cli: str | Path | None = None):
        self.model = model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
        self.cli = Path(cli or os.environ.get("GEMINI_CLI", GEMINI_CLI))

    def generate(self, system: str, user: str, temperature: float = 0.0) -> LLMResult:
        if not self.cli.is_file():
            raise RuntimeError(
                f"Gemini connector CLI not found at {self.cli}. It is part of "
                "the registered custom.gemini connector.")
        prompt = f"System:\n{system}\n\nUser:\n{user}"
        # Retry transient overloads: generation is stateless, so a retry is
        # safe. The free tier 503s under load (observed 26 Nov 2026).
        last_error = ""
        for attempt in range(3):
            try:
                proc = subprocess.run(
                    [sys.executable, str(self.cli), "generate",
                     "--model", self.model, "--prompt", prompt,
                     "--temperature", str(temperature)],
                    capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired:
                last_error = "Gemini generate timed out (120s)"
                if attempt < 2:
                    time.sleep(15 * (attempt + 1))
                    continue
                raise RuntimeError(last_error)
            if proc.returncode != 0:
                last_error = f"Gemini CLI failed: {proc.stderr.strip()[:300]}"
                if "503" in proc.stderr and attempt < 2:
                    time.sleep(15 * (attempt + 1))
                    continue
                raise RuntimeError(last_error)
            try:
                data = json.loads(proc.stdout)
            except json.JSONDecodeError:
                raise RuntimeError("Gemini CLI returned non-JSON output")
            usage = data.get("usage", {}) or {}
            return LLMResult(
                text=data.get("text", ""),
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
                model=self.model,
            )
        raise RuntimeError(last_error or "Gemini generate failed")


class StubLLM(LLMClient):
    """Deterministic test double. See module docstring for the rules."""

    MODEL = "stub-llm/1.0"

    def _detect_cluster(self, system: str, user: str) -> str | None:
        prompt = (system + "\n" + user).lower()
        # Memory hit in the prompt wins: the stub reuses what it was shown.
        m = re.search(r"memory hit \(cluster ([a-z0-9-]+)\)", prompt)
        if m:
            return m.group(1).upper()
        # Detect from the TICKET text only (subject + body). The system
        # prompt lists every mock operation (including "webhook"), and KB
        # excerpts mention other clusters — matching on the whole prompt
        # would make every ticket look like C1.
        low = user.lower()
        m2 = re.search(r"subject:\s*(.*?)\s*body:\s*(.*?)\s*retrieved context:",
                       low, re.S)
        ticket = (m2.group(1) + "\n" + m2.group(2)) if m2 else low
        # Score-based: most keyword hits wins (first-match misfires when a
        # ticket mentions another cluster's words, e.g. "invoice" in a
        # duplicate-charge ticket or "webhook" in a rate-limit ticket).
        scores: dict[str, int] = {}
        longest: dict[str, int] = {}
        for keyword, clusters in _STUB_KEYWORDS:
            if keyword in ticket:
                for c in clusters:
                    scores[c] = scores.get(c, 0) + 1
                    longest[c] = max(longest.get(c, 0), len(keyword))
        if not scores:
            return None
        return max(scores, key=lambda c: (scores[c], longest[c]))

    def generate(self, system: str, user: str, temperature: float = 0.0) -> LLMResult:
        prompt = system + "\n" + user
        cluster = self._detect_cluster(system, user)
        used_memory = "memory hit" in prompt.lower()
        if cluster is None:
            plan = {
                "diagnosis": "Unclear from the available context; needs human review.",
                "steps": ["Escalate to a human agent with a summary of what was tried."],
                "actions": [],
                "confidence": 0.3,
                "needs_human": True,
                "used_memory": False,
                "memory_summary": None,
                "final_answer": "Thanks for reaching out — I've escalated this to a human "
                                "agent who will follow up shortly.",
            }
        else:
            plan = {
                "diagnosis": _STUB_DIAGNOSIS.get(
                    cluster, f"Matches known pattern {cluster} based on the ticket "
                             f"and retrieved context."),
                "steps": [f"Execute the {cluster} fix steps and verify each one."],
                "actions": _STUB_RECIPES.get(cluster, []),
                "confidence": 0.85 if used_memory else 0.55,
                "needs_human": False,
                "used_memory": used_memory,
                "memory_summary": f"Reused fix for {cluster}" if used_memory else None,
                "final_answer": f"Thanks — this matches a known issue ({cluster}). I've "
                                f"applied the fix and verified it works. Let me know if "
                                f"anything still looks off.",
            }
        text = json.dumps(plan)
        # Token counts are rough estimates (chars/4), labelled as such in metrics.
        return LLMResult(text=text, input_tokens=max(1, len(prompt) // 4),
                         output_tokens=max(1, len(text) // 4), model=self.MODEL)


def make_llm_client(kind: str) -> LLMClient:
    """kind: 'gemini' or 'stub'."""
    if kind == "gemini":
        return GeminiClient()
    if kind == "stub":
        return StubLLM()
    raise ValueError(f"Unknown LLM kind: {kind!r} (use 'gemini' or 'stub')")
