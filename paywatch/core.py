"""PAYWATCH core engine: recurring-charge detection.

Pure standard-library. The detection pipeline:
  1. Parse CSV rows into Transaction records (debits only).
  2. Normalize merchant descriptions (strip dates, txn ids, store numbers).
  3. Group by (normalized merchant, rounded amount bucket).
  4. For each group with >= MIN_HITS charges, measure the median gap between
     charges and classify cadence (weekly / monthly / quarterly / annual).
  5. Predict the next charge date, flag price increases, and flag
     likely-forgotten subscriptions (no charge in > 1.5 cadences but historically
     regular).
"""

from __future__ import annotations

import csv
import datetime as _dt
import re
import statistics
from dataclasses import dataclass, field, asdict
from typing import Iterable

MIN_HITS = 3  # need at least this many charges to call it recurring

# cadence label -> (typical days, lower bound, upper bound)
_CADENCES = [
    ("weekly", 7, 5, 10),
    ("biweekly", 14, 11, 18),
    ("monthly", 30, 24, 38),
    ("quarterly", 91, 80, 100),
    ("semiannual", 182, 160, 205),
    ("annual", 365, 320, 410),
]

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%d-%b-%Y")


@dataclass
class Transaction:
    date: _dt.date
    description: str
    amount: float  # positive number = money out (a charge)
    merchant: str = ""


@dataclass
class Subscription:
    merchant: str
    cadence: str
    count: int
    typical_amount: float
    last_charge: str
    next_charge_estimate: str
    annualized_cost: float
    avg_interval_days: float
    price_increased: bool
    first_amount: float
    last_amount: float
    likely_forgotten: bool
    sample_descriptions: list = field(default_factory=list)


def _parse_date(raw: str) -> _dt.date:
    raw = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return _dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date format: {raw!r}")


def _parse_amount(raw: str) -> float:
    raw = raw.strip().replace("$", "").replace(",", "")
    neg = False
    if raw.startswith("(") and raw.endswith(")"):
        neg = True
        raw = raw[1:-1]
    val = float(raw)
    return -val if neg else val


def normalize_merchant(description: str) -> str:
    """Collapse a raw bank memo into a stable merchant key."""
    s = description.upper()
    # strip common Plaid / bank prefixes
    s = re.sub(r"\b(POS|ACH|DEBIT|PURCHASE|RECURRING|PAYMENT|PMT|WEB|PPD)\b", " ", s)
    # strip dates embedded in memo
    s = re.sub(r"\b\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?\b", " ", s)
    # strip long digit runs (txn ids, card tails, store numbers, phone)
    s = re.sub(r"#?\d{3,}", " ", s)
    # strip url tails and state/zip noise
    s = re.sub(r"\b[A-Z]{2}\s*\d{5}\b", " ", s)
    s = re.sub(r"\.(COM|NET|ORG|IO)\b", " ", s)
    # drop non-alphanumeric
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    tokens = [t for t in s.split() if len(t) > 1]
    # keep up to the first 3 meaningful tokens as the brand key
    key = " ".join(tokens[:3]).strip()
    return key or description.upper().strip()


def load_transactions(path: str) -> list[Transaction]:
    """Load a CSV with flexible column names.

    Recognized headers (case-insensitive): date; description/name/memo/merchant;
    amount. A separate debit/credit column is also supported.

    Raises:
        FileNotFoundError: if *path* does not exist.
        PermissionError: if the file cannot be read.
        ValueError: if the file is not a valid CSV or lacks required columns.
    """
    txns: list[Transaction] = []
    try:
        fh = open(path, newline="", encoding="utf-8-sig")
    except FileNotFoundError:
        raise
    except PermissionError:
        raise
    except OSError as exc:
        raise ValueError(f"cannot open file: {exc}") from exc

    try:
        try:
            reader = csv.DictReader(fh)
            if not reader.fieldnames:
                raise ValueError("CSV has no header row")
        except UnicodeDecodeError as exc:
            raise ValueError(f"CSV is not valid UTF-8: {exc}") from exc

        cols = {c.lower().strip(): c for c in reader.fieldnames}

        def pick(*names):
            for n in names:
                if n in cols:
                    return cols[n]
            return None

        date_col = pick("date", "posted", "transaction date", "post date")
        desc_col = pick("description", "name", "memo", "merchant", "payee", "details")
        amt_col = pick("amount", "debit", "value")
        if not date_col or not desc_col or not amt_col:
            raise ValueError(
                "CSV must have date, description, and amount columns; "
                f"found {reader.fieldnames}"
            )
        try:
            for row in reader:
                raw_date = (row.get(date_col) or "").strip()
                raw_desc = (row.get(desc_col) or "").strip()
                raw_amt = (row.get(amt_col) or "").strip()
                if not raw_date or not raw_amt:
                    continue
                try:
                    date = _parse_date(raw_date)
                    amount = _parse_amount(raw_amt)
                except ValueError:
                    continue
                # Treat money-out as a positive charge. Banks vary on sign
                # convention; a dedicated "debit" column is always money-out.
                if amt_col.lower() == "debit":
                    charge = abs(amount)
                else:
                    # negative = money out in most Plaid/bank exports
                    charge = -amount if amount < 0 else 0.0
                    if charge == 0.0 and amount > 0:
                        # some exports list charges as positive;
                        # keep if no negatives seen
                        charge = amount
                if charge <= 0:
                    continue
                txns.append(
                    Transaction(
                        date=date,
                        description=raw_desc,
                        amount=round(charge, 2),
                        merchant=normalize_merchant(raw_desc),
                    )
                )
        except UnicodeDecodeError as exc:
            raise ValueError(f"CSV contains non-UTF-8 data: {exc}") from exc
    finally:
        fh.close()
    return txns


def _classify_cadence(median_days: float) -> tuple[str, int] | None:
    for label, typical, lo, hi in _CADENCES:
        if lo <= median_days <= hi:
            return label, typical
    return None


def detect_subscriptions(
    txns: Iterable[Transaction], today: _dt.date | None = None
) -> list[Subscription]:
    today = today or _dt.date.today()
    # group by (merchant, amount bucket within ~10%)
    groups: dict[str, list[Transaction]] = {}
    for t in txns:
        groups.setdefault(t.merchant, []).append(t)

    subs: list[Subscription] = []
    for merchant, items in groups.items():
        items.sort(key=lambda x: x.date)
        # cluster by amount so a merchant with two distinct plans splits cleanly
        for cluster in _cluster_by_amount(items):
            if len(cluster) < MIN_HITS:
                continue
            dates = [c.date for c in cluster]
            gaps = [
                (dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)
            ]
            gaps = [g for g in gaps if g > 0]
            if not gaps:
                continue
            median_gap = statistics.median(gaps)
            cad = _classify_cadence(median_gap)
            if cad is None:
                continue
            label, typical = cad
            amounts = [c.amount for c in cluster]
            typical_amount = round(statistics.median(amounts), 2)
            last = cluster[-1]
            next_est = last.date + _dt.timedelta(days=round(median_gap))
            annual = round(typical_amount * (365.0 / typical), 2)
            first_amt = cluster[0].amount
            last_amt = cluster[-1].amount
            price_up = last_amt > first_amt * 1.05
            days_since = (today - last.date).days
            forgotten = days_since > median_gap * 1.5
            subs.append(
                Subscription(
                    merchant=merchant,
                    cadence=label,
                    count=len(cluster),
                    typical_amount=typical_amount,
                    last_charge=last.date.isoformat(),
                    next_charge_estimate=next_est.isoformat(),
                    annualized_cost=annual,
                    avg_interval_days=round(statistics.mean(gaps), 1),
                    price_increased=price_up,
                    first_amount=round(first_amt, 2),
                    last_amount=round(last_amt, 2),
                    likely_forgotten=forgotten,
                    sample_descriptions=[c.description for c in cluster[:3]],
                )
            )
    subs.sort(key=lambda s: s.annualized_cost, reverse=True)
    return subs


def _cluster_by_amount(items: list[Transaction]) -> list[list[Transaction]]:
    """Split a merchant's charges into clusters of similar amount (within 10%)."""
    by_amt = sorted(items, key=lambda x: x.amount)
    clusters: list[list[Transaction]] = []
    for t in by_amt:
        placed = False
        for cl in clusters:
            base = cl[0].amount
            if base > 0 and abs(t.amount - base) <= max(0.5, base * 0.10):
                cl.append(t)
                placed = True
                break
        if not placed:
            clusters.append([t])
    # restore chronological order inside each cluster
    for cl in clusters:
        cl.sort(key=lambda x: x.date)
    return clusters


def summarize(subs: list[Subscription]) -> dict:
    """Return aggregate statistics for a list of detected subscriptions.

    Safe to call with an empty list; all monetary values will be zero.
    """
    if not subs:
        return {
            "subscription_count": 0,
            "total_annualized_cost": 0.0,
            "estimated_monthly_cost": 0.0,
            "likely_forgotten_count": 0,
            "likely_forgotten_annual_waste": 0.0,
            "price_increase_count": 0,
        }
    total_annual = round(sum(s.annualized_cost for s in subs), 2)
    monthly = round(total_annual / 12.0, 2)
    forgotten = [s for s in subs if s.likely_forgotten]
    hikes = [s for s in subs if s.price_increased]
    return {
        "subscription_count": len(subs),
        "total_annualized_cost": total_annual,
        "estimated_monthly_cost": monthly,
        "likely_forgotten_count": len(forgotten),
        "likely_forgotten_annual_waste": round(
            sum(s.annualized_cost for s in forgotten), 2
        ),
        "price_increase_count": len(hikes),
    }


def subscription_to_dict(s: Subscription) -> dict:
    return asdict(s)
