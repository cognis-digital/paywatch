# Demo 01 - Basic recurring-charge scan

A realistic 4-month checking-account export (`transactions.csv`) for a household
that has accumulated the usual creep of subscriptions plus normal one-off
spending (groceries, gas, an ATM withdrawal). The file mixes column-name and
sign conventions you actually see from Plaid / bank CSV downloads: negative
amounts are money out, descriptions carry store numbers, dates, and txn ids.

## What PAYWATCH should find

Recurring charges hidden in the noise:

- **Netflix** - monthly, ~$15.49, with a **price increase** mid-history
  (15.49 -> 16.99).
- **Spotify** - monthly, $10.99.
- **Planet Fitness** - monthly, $24.99, but the **last charge is old** ->
  flagged **likely forgotten**.
- **NYTimes** - monthly, $4.25.
- **Amazon Prime** - annual, $139.00.
- **Adobe Creative Cloud** - monthly, $54.99.

One-off purchases (Whole Foods, Shell, ATM, Target) should be ignored because
they do not repeat on a regular cadence.

## Run it

```bash
python -m paywatch scan demos/01-basic/transactions.csv
python -m paywatch scan demos/01-basic/transactions.csv --format json
python -m paywatch scan demos/01-basic/transactions.csv --forgotten-only
```

The table view ranks subscriptions by annualized cost, predicts the next charge
date, and surfaces total monthly/yearly spend plus a "potential waste" line for
forgotten subscriptions.
