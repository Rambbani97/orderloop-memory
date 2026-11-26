# Shopify Inventory Sync and Rate Limits

**Applies to:** All plans with the Shopify integration · **Last updated:** November 2026

## How sync works

OrderLoop keeps stock levels in sync with Shopify in two modes:

- **Incremental sync (recommended):** only SKUs that changed since the last
  sync are updated, in small batches. This is the default for day-to-day
  operation.
- **Full sync:** every SKU is re-fetched. Use it only after a major catalogue
  change, and schedule it outside peak hours.

## Rate limits

Shopify enforces an API rate limit on how many requests your store can make.
A full sync after a large import (thousands of SKUs) can hit HTTP **429**
responses. When that happens without backoff, the sync job can get stuck at
"Running" and stock levels stop updating — even though nothing is technically
"down".

## If sync is stuck at "Running"

1. Go to **Settings > Integrations > Shopify > Sync status** and check the
   last successful sync time.
2. **Cancel** the stuck full-sync job.
3. Turn on **Incremental sync** and set a batch size of **250** with a short
   delay between batches.
4. Run a **manual sync** for the affected SKUs (or wait for the next
   incremental cycle).
5. Verify a sample SKU matches in both systems (e.g. check the quantity in
   OrderLoop against Shopify).

## Preventing it next time

- Schedule large imports and full syncs outside peak hours.
- For bulk catalogue updates, use a scheduled CSV import instead of a manual
  full sync.
- Prefer incremental sync for routine changes; reserve full sync for
  migrations and major restructures.

## What a stuck sync is NOT

- **Sync status "Success, 4 minutes ago" with mismatched quantities:** the
  sync is healthy — the mismatch has another cause (for example, manual stock
  adjustments from a POS overwriting OrderLoop's numbers, or a conflicting
  sync direction). Cancelling the job will not help; check the sync-direction
  settings under **Settings > Inventory > Sync direction** instead.
- **Repeated HTTP 429 in your API logs:** this points at rate limiting, not
  at Shopify being down. Back off and switch to incremental batches.
