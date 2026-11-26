# API Limits and Webhooks

**Applies to:** Growth (API access), Scale, Enterprise · **Last updated:** November 2026

## API rate limits by plan

| Plan | Limit |
|---|---|
| Growth | 200 requests/min |
| Scale | 1,000 requests/min |
| Enterprise | 5,000 requests/min (or custom) |

Exceeding the limit returns HTTP **429** with `rate_limit_exceeded`. Polling
order status in a tight loop is the most common way to hit it.

## If you keep hitting the limit

- **Switch to webhooks.** Instead of polling for order status, subscribe to
  `order.created`, `order.updated`, and `order.fulfilled` events. Webhooks
  push changes to you — no polling, no limit problem. See the webhook docs
  for payload examples.
- **Request a temporary increase.** Support can raise your limit (e.g. to
  2,500 req/min) for a 14-day migration window while you move to webhooks.
- **Move to Enterprise** if you genuinely need 5,000 req/min sustained. Your
  CSM can quote it.

## Webhook payloads and custom fields

Webhook payloads contain the standard order fields by default. Custom fields
you added to orders (e.g. `loyalty_tier`) are **not** included unless you
enable them:

1. Go to **Settings > Integrations > Webhooks** and open your endpoint.
2. Enable **Include custom fields** and select the fields you want.
3. Send a test event and confirm the field appears in the payload.

Note: enabling custom fields only affects events sent *after* the change —
earlier events are not re-sent with the new fields.

## Webhook signing

Every webhook event is signed with your endpoint's signing secret. Always
verify the signature before processing an event. If you rotate secrets, update
OrderLoop the same day — see "Rotating Your Stripe Webhook Signing Secret".
