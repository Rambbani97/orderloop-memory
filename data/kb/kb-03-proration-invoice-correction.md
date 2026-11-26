# Proration and Invoice Corrections After a Mid-Cycle Plan Change

**Applies to:** All paid plans · **Last updated:** November 2026

## How proration works

When you change plans in the middle of a billing cycle, OrderLoop should give
you a **proration credit** for the unused days of your old plan. The credit is
calculated as:

```
credit = old plan monthly price × (unused days ÷ days in cycle)
```

Tax (VAT/GST) is then calculated on the **net** amount (new plan price minus
the credit), not on the full new plan price.

## Example

Growth ($79/month) to Scale ($199/month) on 10 December (31-day cycle):

- Unused Growth days: 21 (10–31 Dec)
- Credit: $79 × 21/31 ≈ $53.52
- Taxable amount: $199 − $53.52 = $145.48
- German VAT 19% on $145.48 ≈ $27.64 (not 19% on the full $199)

## If your invoice is missing the credit

1. Check the invoice date and the plan-change date in **Settings > Billing >
   Invoices**.
2. Contact support with the invoice number (e.g. `INV-2026-4417`) and the date
   of the plan change. We will:
   - Verify the unused days in the billing record.
   - Apply the proration credit to your account.
   - Cancel and reissue the invoice with tax calculated on the net amount.
   - Refund or credit any tax overpaid.
3. The corrected invoice is usually issued within 1 business day.

## This is not a double charge

An invoice that shows the full new plan price with no credit can *look* like a
double charge, but it is a missing proration credit — not two charges for the
same subscription. A genuine double charge (two identical card charges on
different days) is handled under our refunds process instead.

## For your accountant

Corrected invoices keep the original invoice number with a `-R1` suffix and a
note explaining the proration. The credit appears as a separate line item so
your books reconcile.
