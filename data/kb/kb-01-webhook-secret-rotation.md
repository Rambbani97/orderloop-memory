# Rotating Your Stripe Webhook Signing Secret

**Applies to:** All plans · **Last updated:** November 2026

## What is the webhook signing secret?

OrderLoop receives payment events from Stripe through a webhook endpoint
(`https://api.orderloop.io/webhooks/stripe`). Stripe signs every event with a
signing secret (`whsec_...`). OrderLoop verifies that signature before
processing the event. If the secret on our side does not match the secret in
Stripe, every event is rejected with HTTP 400 and orders stay stuck on
"Awaiting payment".

## When to update the secret in OrderLoop

Update the secret in OrderLoop **every time** you rotate keys in Stripe —
including quarterly security rotations and incident-driven rotations. Rotating
the Stripe API key alone does not change the webhook secret, but rotating the
signing secret (or re-creating the webhook endpoint) does.

## Steps

1. In the Stripe dashboard, go to **Developers > Webhooks** and open the
   OrderLoop endpoint.
2. Click **Reveal** next to the signing secret and copy the new value (it
   starts with `whsec_`).
3. In OrderLoop, go to **Settings > Integrations > Stripe**.
4. Paste the new signing secret into the **Webhook signing secret** field and
   click **Save**.
5. Click **Send test event** and choose `payment_intent.succeeded`. You should
   see **200 OK**.
6. In Stripe, re-play any events that failed during the outage (select the
   failed events > **Resend**), then confirm the affected orders move to Paid.

## Symptoms of a stale secret

- Payments succeed in Stripe but orders stay "Awaiting payment" in OrderLoop.
- Stripe's webhook dashboard shows many HTTP 400 errors for the OrderLoop
  endpoint.
- Order confirmation emails stop going out.

## Important notes

- The webhook endpoint URL never changes when you rotate secrets. Do **not**
  change the URL in Stripe unless your store domain itself changed — the
  OrderLoop endpoint URL is independent of your store's domain.
- Record every rotation in your team's runbook so the next rotation also
  includes the OrderLoop update.
- If events show HTTP 200 in Stripe but nothing arrives in OrderLoop, the
  problem is not the secret — check that the webhook URL in Stripe is still
  `https://api.orderloop.io/webhooks/stripe`.
