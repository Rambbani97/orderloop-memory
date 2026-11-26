# Large Reports and Aggregation

**Applies to:** All plans · **Last updated:** November 2026

## Why long-range reports time out

Reports that list every individual order ("raw" reports) over a range longer
than about 90 days can exceed the 30-second query timeout, especially with
tens of thousands of orders. Shorter ranges work fine because they scan far
less data.

## Use aggregated summaries for long ranges

For anything over 90 days — especially a full year — use the pre-aggregated
summary instead of the raw order list:

1. Go to **Reports > Sales > Aggregated yearly summary** (or the equivalent
   aggregated view for your report type).
2. The data is pre-aggregated per day/month, so it loads in seconds.
3. You still get totals, revenue by channel, and top SKUs.

## Other options

- **Split the range:** run the report per quarter and combine the exports.
- **Scheduled export:** use **Export > CSV (Scheduled export)**. It runs in
  the background and emails you a download link when ready — no timeout.
- **Scheduled reports:** save a recurring report (e.g. every Monday morning)
  so the numbers are waiting for you instead of being computed on demand.
- **Narrow the filters:** avoid "all stores + all SKUs + 12 months" in one
  report. Filter per store when you can.

## If you need a single annual overview

Use the aggregated yearly summary for the board/tax-advisor view (total
revenue, orders by channel, top 20 SKUs), and use scheduled CSV exports only
if you need row-level detail for audit.
