"""Mock OrderLoop — in-process simulation of the OrderLoop SaaS admin surface.

The mock is the system under test: agents "execute" fixes here and the mock
verifies whether the root cause is actually resolved. It is deliberately
ticket-scoped: :meth:`MockOrderLoop.reset_for_ticket` puts the world into the
broken state described by one ticket, and fixes do not leak across tickets.

Two kinds of ops:
- *check ops* (``get_*``) — read-only diagnosis.
- *execute ops* — state-changing actions support can take in the admin panel.
- *customer_* ops — actions only the customer can do (paste a new Stripe
  secret, upload SAML metadata, re-login on their phone...). The agent
  instructs the customer; the op models "the customer confirms they did it".

Ops return ``{"ok": bool, "message": str, ...}`` and are appended to
``op_log``. :meth:`verify_fix` checks the root-cause conditions for the
current ticket — this is what the harness uses for the verification bonus
and the automated quality score. It is NOT visible to the agent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Correct fix "recipes": the op names (in order) that resolve each cluster.
# Used by the automated scorer only (harness/tests), never shown to the agent.
FIX_RECIPES: dict[str, list[str]] = {
    "C1": ["customer_update_webhook_secret", "webhook_send_test_event", "webhook_replay_failed_events"],
    "C2": ["customer_upload_saml_metadata", "saml_test_login"],
    "C3": ["apply_proration_credit", "reissue_invoice"],
    "C4": ["customer_toggle_ios_permission", "customer_relogin_app", "send_test_push"],
    "C5": ["cancel_sync_job", "enable_incremental_sync", "run_manual_sync"],
    "C6": ["run_report"],  # must be called with aggregated=True
    "C7": ["customer_convert_csv_utf8", "import_products"],
    "C8": ["request_2fa_reset", "verify_identity", "reset_2fa", "reenroll_2fa"],
    "D-01": ["customer_fix_webhook_url", "webhook_send_test_event"],
    "D-02": ["saml_assign_user"],
    "D-03": ["set_sync_direction", "run_manual_sync"],
    "U-01": ["refund_charge"],
    "U-02": ["increase_rate_limit"],
    "U-03": ["erase_customer_data"],
    "U-04": ["set_scanner_mode", "grant_permissions", "pair_scanner_in_app"],
    "U-05": ["set_currency_rounding", "regenerate_report"],
    "U-06": ["activate_schedule", "send_report_now"],
    "U-07": ["merge_accounts"],
    "U-08": ["webhook_set_custom_fields", "webhook_send_test_event"],
    "U-09": ["get_known_issue", "apply_mobile_workaround", "notify_release"],
}

# Ops that are pure diagnosis (never count as hallucinated fix steps).
CHECK_OPS = {
    "get_order", "get_webhook_status", "get_saml_status", "get_invoice",
    "get_billing_record", "get_device_status", "get_sync_status",
    "get_inventory", "get_api_usage", "get_known_issue",
}


@dataclass
class World:
    """Mutable state for one ticket scenario."""

    # webhook
    secret_current: bool = True
    endpoint_url_correct: bool = True
    test_event_ok: bool = False
    failed_events_replayed: bool = False
    custom_fields_enabled: bool = False
    stuck_orders: list = field(default_factory=list)
    # saml
    cert_expired: bool = False
    metadata_uploaded: bool = False
    sso_login_ok: bool = False
    assigned_users: dict = field(default_factory=dict)
    # billing
    invoice_id: str = ""
    invoice_amount: float = 0.0
    invoice_tax_rate: float = 0.0
    credit_applied: float = 0.0
    invoice_corrected: bool = False
    double_charge: bool = False
    refund_issued: bool = False
    # push
    device_token_registered: bool = True
    ios_permission_on: bool = True
    test_push_ok: bool = False
    # sync
    sync_job_status: str = "success"  # success | stuck | running
    sync_last_success: str = "4 minutes ago"
    incremental_enabled: bool = False
    inventory_match: bool = True
    sync_direction: str = "orderloop_wins"
    # reports
    report_ok: bool = False
    # import
    csv_encoding: str = "UTF-8"
    import_ok: bool = False
    # 2fa
    failed_2fa_attempts: int = 0
    reset_requested: bool = False
    identity_verified: bool = False
    twofa_reset: bool = False
    twofa_reenrolled: bool = False
    # api
    api_limit: int = 1000
    api_limit_increased: bool = False
    webhook_mode: bool = False
    # gdpr / accounts / hardware / currency / schedule / mobile
    erasure_done: bool = False
    accounts_merged: bool = False
    scanner_mode: str = "SPP"
    device_permissions: bool = True
    scanner_paired_in_app: bool = False
    rounding_mode: str = "per-line"
    report_regenerated: bool = False
    schedule_active: bool = False
    report_sent: bool = False
    mobile_workaround: bool = False
    release_notified: bool = False


class MockOrderLoop:
    """Deterministic in-process OrderLoop admin API."""

    def __init__(self) -> None:
        self.world = World()
        self.current_ticket: dict | None = None
        self.op_log: list[dict] = []

    # ------------------------------------------------------------------ setup
    def reset_for_ticket(self, ticket: dict) -> None:
        """Put the world into the broken state described by ``ticket``."""
        self.current_ticket = ticket
        self.op_log = []
        w = World()
        cluster = ticket.get("cluster")
        body = ticket.get("body", "")
        orders = re.findall(r"ORD-\d+", body)
        invoices = re.findall(r"INV-2026-\d+", body)
        w.stuck_orders = sorted(set(orders))
        w.invoice_id = invoices[0] if invoices else ""

        if cluster == "C1":
            w.secret_current = False
        elif cluster == "C2":
            w.cert_expired = True
        elif cluster == "C3":
            w.invoice_amount = 199.0
            w.invoice_tax_rate = 0.19
        elif cluster == "C4":
            w.device_token_registered = False
            w.ios_permission_on = False
        elif cluster == "C5":
            w.sync_job_status = "stuck"
            w.sync_last_success = "2 days ago"
            w.inventory_match = False
        elif cluster == "C6":
            pass  # timeout is computed by run_report
        elif cluster == "C7":
            w.csv_encoding = "ANSI"
        elif cluster == "C8":
            pass  # authenticator not moved / recovery invalid is the default story
        elif cluster == "distractor":
            target = ticket.get("target_cluster")
            if target == "C1":
                w.endpoint_url_correct = False  # URL moved to new domain
            elif target == "C2":
                w.assigned_users = {"Layla": False}
            elif target == "C5":
                w.sync_job_status = "success"
                w.sync_last_success = "4 minutes ago"
                w.inventory_match = False  # POS overwrites, not a stuck job
        elif ticket["id"] == "U-01":
            w.double_charge = True
        elif ticket["id"] == "U-04":
            w.scanner_mode = "HID"
            w.device_permissions = False
        self.world = w

    # ------------------------------------------------------------------ utils
    def _log(self, op: str, args: dict, result: dict) -> dict:
        entry = {"op": op, "args": args, "ok": bool(result.get("ok"))}
        self.op_log.append(entry)
        return result

    def execute(self, op: str, args: dict | None = None) -> dict:
        """Execute one mock op by name. Unknown ops fail (hallucination)."""
        args = args or {}
        fn = getattr(self, f"op_{op}", None)
        if fn is None:
            return self._log(op, args, {"ok": False, "message": f"Unknown operation: {op}"})
        try:
            return self._log(op, args, fn(**args))
        except TypeError as exc:
            return self._log(op, args, {"ok": False, "message": f"Bad arguments for {op}: {exc}"})

    # ------------------------------------------------------------------ checks
    def op_get_order(self, order_id: str = "") -> dict:
        w = self.world
        stuck = order_id in w.stuck_orders and not w.failed_events_replayed
        return {"ok": True, "order_id": order_id,
                "status": "Awaiting payment" if stuck else "Paid"}

    def op_get_webhook_status(self) -> dict:
        w = self.world
        return {"ok": True,
                "endpoint": "https://api.orderloop.io/webhooks/stripe" if w.endpoint_url_correct
                            else "https://getbalticbeauty.com/webhooks/stripe",
                "secret_current": w.secret_current,
                "last_events": "HTTP 400 (signature mismatch)" if not w.secret_current
                              else "HTTP 200 OK",
                "failed_events": len(self.world.stuck_orders) if not w.secret_current else 0}

    def op_get_saml_status(self) -> dict:
        w = self.world
        return {"ok": True, "idp": "Okta / Azure AD (SAML 2.0)",
                "cert_expired": w.cert_expired,
                "metadata_uploaded": w.metadata_uploaded,
                "sso_login_ok": w.sso_login_ok}

    def op_get_invoice(self, invoice_id: str = "") -> dict:
        w = self.world
        net = w.invoice_amount - w.credit_applied
        return {"ok": True, "invoice_id": invoice_id or w.invoice_id,
                "amount": w.invoice_amount, "credit_applied": w.credit_applied,
                "net": round(net, 2), "tax_rate": w.invoice_tax_rate,
                "corrected": w.invoice_corrected,
                "double_charge": w.double_charge}

    def op_get_billing_record(self) -> dict:
        w = self.world
        txs = [{"date": "2026-12-01", "amount": 79.0, "payment_intent": "pi_1"},
               {"date": "2026-12-02", "amount": 79.0, "payment_intent": "pi_2"}] if w.double_charge else []
        return {"ok": True, "transactions": txs, "double_charge": w.double_charge}

    def op_get_device_status(self, device: str = "iPhone") -> dict:
        w = self.world
        return {"ok": True, "device": device,
                "token_registered": w.device_token_registered,
                "ios_permission_on": w.ios_permission_on}

    def op_get_sync_status(self) -> dict:
        w = self.world
        return {"ok": True, "job_status": w.sync_job_status,
                "last_success": w.sync_last_success,
                "rate_429_seen": w.sync_job_status == "stuck",
                "inventory_match": w.inventory_match}

    def op_get_inventory(self, sku: str = "") -> dict:
        w = self.world
        return {"ok": True, "sku": sku, "match": w.inventory_match,
                "orderloop_qty": 120 if not w.inventory_match else 34,
                "shopify_qty": 34}

    def op_get_api_usage(self) -> dict:
        w = self.world
        return {"ok": True, "limit_req_per_min": w.api_limit,
                "peak_usage": 1150, "webhook_mode": w.webhook_mode}

    def op_get_known_issue(self, ref: str = "") -> dict:
        if ref == "MOB-2214":
            return {"ok": True, "ref": ref, "status": "known issue",
                    "detail": "OrderLoop Mobile 3.8.0 crashes on Android 12 (API 31) "
                              "when opening the Orders tab. Fix in 3.8.2 (not yet released). "
                              "Workaround: use the web dashboard or Compact list mode."}
        return {"ok": False, "message": f"No known issue {ref}"}

    # ------------------------------------------------------------------ webhook
    def op_customer_update_webhook_secret(self, secret: str = "") -> dict:
        w = self.world
        if not secret:
            return {"ok": False, "message": "No secret provided by customer"}
        w.secret_current = True
        return {"ok": True, "message": "Signing secret updated in OrderLoop"}

    def op_customer_fix_webhook_url(self) -> dict:
        self.world.endpoint_url_correct = True
        return {"ok": True, "message": "Webhook URL in Stripe restored to https://api.orderloop.io/webhooks/stripe"}

    def op_webhook_send_test_event(self, event: str = "payment_intent.succeeded") -> dict:
        w = self.world
        if not w.endpoint_url_correct:
            return {"ok": False, "message": "Test event went to the wrong URL (endpoint not OrderLoop)"}
        if not w.secret_current:
            return {"ok": False, "message": "Test event rejected: HTTP 400 signature mismatch"}
        w.test_event_ok = True
        return {"ok": True, "message": f"Test event {event}: 200 OK"}

    def op_webhook_replay_failed_events(self) -> dict:
        w = self.world
        if not w.test_event_ok:
            return {"ok": False, "message": "Cannot replay: test event has not succeeded yet"}
        w.failed_events_replayed = True
        return {"ok": True, "message": f"Replayed {len(w.stuck_orders)} failed events; orders now Paid"}

    def op_webhook_set_custom_fields(self, fields: list | None = None) -> dict:
        self.world.custom_fields_enabled = True
        return {"ok": True, "message": f"Custom fields enabled on webhook payload: {fields or []}"}

    # ------------------------------------------------------------------ saml
    def op_customer_upload_saml_metadata(self) -> dict:
        w = self.world
        w.metadata_uploaded = True
        w.cert_expired = False
        return {"ok": True, "message": "New IdP metadata XML uploaded; certificate updated"}

    def op_saml_test_login(self, user: str = "staff") -> dict:
        w = self.world
        if w.cert_expired or not w.metadata_uploaded:
            return {"ok": False, "message": "SSO login failed: Signature validation failed"}
        w.sso_login_ok = True
        return {"ok": True, "message": f"SSO login for {user}: reached dashboard"}

    def op_saml_assign_user(self, user: str = "Layla") -> dict:
        self.world.assigned_users[user] = True
        return {"ok": True, "message": f"{user} assigned to the OrderLoop application in the IdP"}

    # ------------------------------------------------------------------ billing
    def op_apply_proration_credit(self, invoice_id: str = "", amount: float = 0.0) -> dict:
        w = self.world
        if amount <= 0:
            return {"ok": False, "message": "Credit amount must be positive"}
        w.credit_applied = round(amount, 2)
        return {"ok": True, "message": f"Proration credit ${w.credit_applied:.2f} applied"}

    def op_reissue_invoice(self, invoice_id: str = "") -> dict:
        w = self.world
        if w.credit_applied <= 0:
            return {"ok": False, "message": "Cannot reissue: no proration credit applied yet"}
        w.invoice_corrected = True
        return {"ok": True, "message": f"Invoice {invoice_id or w.invoice_id} reissued with tax on net amount"}

    def op_refund_charge(self, invoice_id: str = "") -> dict:
        w = self.world
        if not w.double_charge:
            return {"ok": False, "message": "No duplicate charge found for this invoice"}
        w.refund_issued = True
        return {"ok": True, "message": "Duplicate charge refunded (5-10 business days)"}

    # ------------------------------------------------------------------ push
    def op_customer_toggle_ios_permission(self, on: bool = True) -> dict:
        self.world.ios_permission_on = bool(on)
        return {"ok": True, "message": f"iOS notification permission {'ON' if on else 'OFF'}"}

    def op_customer_relogin_app(self) -> dict:
        self.world.device_token_registered = True
        return {"ok": True, "message": "Logged back in; APNs device token re-registered"}

    def op_send_test_push(self, device: str = "iPhone") -> dict:
        w = self.world
        if not w.device_token_registered:
            return {"ok": False, "message": "Test push failed: device token not registered"}
        if not w.ios_permission_on:
            return {"ok": False, "message": "Test push failed: iOS notification permission off"}
        w.test_push_ok = True
        return {"ok": True, "message": f"Test push delivered to {device}"}

    # ------------------------------------------------------------------ sync
    def op_cancel_sync_job(self) -> dict:
        w = self.world
        if w.sync_job_status != "stuck":
            return {"ok": False, "message": "No stuck sync job to cancel"}
        w.sync_job_status = "cancelled"
        return {"ok": True, "message": "Stuck full-sync job cancelled"}

    def op_enable_incremental_sync(self, batch_size: int = 250, delay_seconds: int = 2) -> dict:
        self.world.incremental_enabled = True
        return {"ok": True, "message": f"Incremental sync enabled (batch {batch_size}, delay {delay_seconds}s)"}

    def op_run_manual_sync(self, skus: list | None = None) -> dict:
        w = self.world
        if w.sync_job_status == "stuck":
            return {"ok": False, "message": "Cannot sync: stuck job still running — cancel it first"}
        w.inventory_match = True
        return {"ok": True, "message": f"Manual sync reconciled SKUs: {skus or 'affected'}"}

    def op_set_sync_direction(self, direction: str = "") -> dict:
        w = self.world
        if direction not in ("pos_wins", "shopify_pos_precedence"):
            return {"ok": False, "message": f"Unknown sync direction: {direction}"}
        w.sync_direction = direction
        return {"ok": True, "message": f"Sync direction set: {direction}"}

    # ------------------------------------------------------------------ reports
    def op_run_report(self, range_days: int = 30, aggregated: bool = False) -> dict:
        w = self.world
        if not aggregated and range_days > 90:
            return {"ok": False, "message": "Request timed out after 30s. Please try a smaller date range."}
        w.report_ok = True
        return {"ok": True, "message": f"Report ready ({'aggregated' if aggregated else 'raw'}, {range_days} days)"}

    def op_schedule_report(self, name: str = "weekly sales") -> dict:
        return {"ok": True, "message": f"Scheduled report '{name}' created (status: Draft)"}

    def op_activate_schedule(self) -> dict:
        self.world.schedule_active = True
        return {"ok": True, "message": "Scheduled report activated"}

    def op_send_report_now(self) -> dict:
        w = self.world
        if not w.schedule_active:
            return {"ok": False, "message": "Schedule is still Draft — activate it first"}
        w.report_sent = True
        return {"ok": True, "message": "Report sent now (test delivery OK)"}

    def op_regenerate_report(self) -> dict:
        self.world.report_regenerated = True
        return {"ok": True, "message": "Report regenerated"}

    def op_set_currency_rounding(self, mode: str = "total") -> dict:
        if mode not in ("total", "per-line"):
            return {"ok": False, "message": f"Unknown rounding mode: {mode}"}
        self.world.rounding_mode = mode
        return {"ok": True, "message": f"Currency rounding set to: {mode}"}

    # ------------------------------------------------------------------ import
    def op_validate_csv(self, encoding: str = "") -> dict:
        w = self.world
        enc = encoding or w.csv_encoding
        if enc.upper() in ("ANSI", "WINDOWS-1250", "WINDOWS-1252"):
            return {"ok": False, "message": "Invalid file format: file is ANSI-encoded, accented characters corrupted"}
        return {"ok": True, "message": "CSV encoding OK (UTF-8)"}

    def op_customer_convert_csv_utf8(self) -> dict:
        self.world.csv_encoding = "UTF-8"
        return {"ok": True, "message": "File re-saved as CSV UTF-8 in Excel"}

    def op_import_products(self) -> dict:
        w = self.world
        if w.csv_encoding.upper() != "UTF-8":
            return {"ok": False, "message": "Invalid file format: fix the encoding first"}
        w.import_ok = True
        return {"ok": True, "message": "Import started; preview rows show correct characters"}

    # ------------------------------------------------------------------ 2fa
    def op_request_2fa_reset(self, user: str = "") -> dict:
        self.world.reset_requested = True
        return {"ok": True, "message": f"2FA reset requested for {user or 'account owner'}"}

    def op_verify_identity(self, user: str = "", evidence: dict | None = None) -> dict:
        evidence = evidence or {}
        if not self.world.reset_requested:
            return {"ok": False, "message": "No reset request on file — request a reset first"}
        if not (evidence.get("email") and evidence.get("id") and (evidence.get("card_last4") or evidence.get("invoice"))):
            return {"ok": False, "message": "Identity evidence incomplete (need email + photo ID + card/invoice)"}
        self.world.identity_verified = True
        return {"ok": True, "message": "Identity verified"}

    def op_reset_2fa(self, user: str = "") -> dict:
        w = self.world
        if not w.identity_verified:
            return {"ok": False, "message": "Cannot reset 2FA: identity not verified (verification required first)"}
        w.twofa_reset = True
        return {"ok": True, "message": "Old 2FA disabled"}

    def op_reenroll_2fa(self, user: str = "") -> dict:
        w = self.world
        if not w.twofa_reset:
            return {"ok": False, "message": "Cannot re-enrol: old 2FA not reset yet"}
        w.twofa_reenrolled = True
        return {"ok": True, "message": "2FA re-enrolled on new phone; new recovery codes issued"}

    # ------------------------------------------------------------------ api/misc
    def op_increase_rate_limit(self, new_limit: int = 2500, days: int = 14) -> dict:
        w = self.world
        if new_limit <= w.api_limit:
            return {"ok": False, "message": "New limit must be above the current limit"}
        w.api_limit = new_limit
        w.api_limit_increased = True
        return {"ok": True, "message": f"Rate limit raised to {new_limit} req/min for {days} days"}

    def op_switch_to_webhooks(self) -> dict:
        self.world.webhook_mode = True
        return {"ok": True, "message": "Polling replaced by webhooks (order.created/updated/fulfilled)"}

    def op_erase_customer_data(self, email: str = "") -> dict:
        if not email:
            return {"ok": False, "message": "Email of data subject required"}
        self.world.erasure_done = True
        return {"ok": True, "message": f"Erasure completed for {email} (tax invoices anonymised, not deleted)"}

    def op_merge_accounts(self, source: str = "", target: str = "") -> dict:
        self.world.accounts_merged = True
        return {"ok": True, "message": f"Accounts merged into {target or 'surviving account'}; stores verified"}

    def op_set_scanner_mode(self, mode: str = "SPP") -> dict:
        if mode not in ("SPP", "HID"):
            return {"ok": False, "message": f"Unknown scanner mode: {mode}"}
        self.world.scanner_mode = mode
        return {"ok": True, "message": f"Scanner mode set to {mode}"}

    def op_grant_permissions(self) -> dict:
        self.world.device_permissions = True
        return {"ok": True, "message": "Nearby devices + Location permissions granted"}

    def op_pair_scanner_in_app(self) -> dict:
        w = self.world
        if w.scanner_mode != "SPP" or not w.device_permissions:
            return {"ok": False, "message": "Pairing failed: set SPP mode and grant permissions first"}
        w.scanner_paired_in_app = True
        return {"ok": True, "message": "Scanner paired in-app; test scan OK"}

    def op_apply_mobile_workaround(self) -> dict:
        self.world.mobile_workaround = True
        return {"ok": True, "message": "Workaround applied: using web dashboard / Compact list mode"}

    def op_notify_release(self, version: str = "3.8.2") -> dict:
        self.world.release_notified = True
        return {"ok": True, "message": f"Customer added to release notification list for {version}"}

    # ------------------------------------------------------------------ verify
    def verify_fix(self, ticket: dict) -> dict:
        """Check root-cause conditions for ``ticket``. Harness/scorer only."""
        w = self.world
        cluster = ticket.get("cluster")
        tid = ticket.get("id")
        checks: dict[str, bool] = {}
        if cluster == "C1":
            checks = {"secret_updated": w.secret_current, "test_event_200": w.test_event_ok,
                      "failed_events_replayed": w.failed_events_replayed}
        elif cluster == "C2":
            checks = {"metadata_uploaded": w.metadata_uploaded, "sso_login_ok": w.sso_login_ok}
        elif cluster == "C3":
            checks = {"credit_applied": w.credit_applied > 0, "invoice_corrected": w.invoice_corrected}
        elif cluster == "C4":
            checks = {"ios_permission_on": w.ios_permission_on,
                      "token_registered": w.device_token_registered, "test_push_ok": w.test_push_ok}
        elif cluster == "C5":
            checks = {"stuck_job_cancelled": w.sync_job_status in ("cancelled", "success"),
                      "incremental_enabled": w.incremental_enabled,
                      "inventory_match": w.inventory_match}
        elif cluster == "C6":
            checks = {"report_ready": w.report_ok}
        elif cluster == "C7":
            checks = {"encoding_utf8": w.csv_encoding == "UTF-8", "import_ok": w.import_ok}
        elif cluster == "C8":
            checks = {"twofa_reset": w.twofa_reset, "reenrolled": w.twofa_reenrolled}
        elif cluster == "distractor":
            target = ticket.get("target_cluster")
            if target == "C1":
                checks = {"endpoint_url_correct": w.endpoint_url_correct, "test_event_200": w.test_event_ok}
            elif target == "C2":
                checks = {"user_assigned": bool(w.assigned_users.get("Layla"))}
            else:
                checks = {"sync_direction_fixed": w.sync_direction in ("pos_wins", "shopify_pos_precedence"),
                          "inventory_reconciled": w.inventory_match}
        elif tid == "U-01":
            checks = {"refund_issued": w.refund_issued}
        elif tid == "U-02":
            checks = {"limit_or_webhook": w.api_limit_increased or w.webhook_mode}
        elif tid == "U-03":
            checks = {"erasure_done": w.erasure_done}
        elif tid == "U-04":
            checks = {"scanner_spp": w.scanner_mode == "SPP",
                      "permissions": w.device_permissions,
                      "paired_in_app": w.scanner_paired_in_app}
        elif tid == "U-05":
            checks = {"rounding_total": w.rounding_mode == "total",
                      "report_regenerated": w.report_regenerated}
        elif tid == "U-06":
            checks = {"schedule_active": w.schedule_active, "report_sent": w.report_sent}
        elif tid == "U-07":
            checks = {"accounts_merged": w.accounts_merged}
        elif tid == "U-08":
            checks = {"custom_fields_enabled": w.custom_fields_enabled,
                      "test_event_200": w.test_event_ok}
        elif tid == "U-09":
            checks = {"workaround_applied": w.mobile_workaround,
                      "release_notified": w.release_notified}
        return {"resolved": bool(checks) and all(checks.values()), "checks": checks}
