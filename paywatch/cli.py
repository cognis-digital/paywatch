"""PAYWATCH command-line interface.

Usage:
  paywatch scan transactions.csv
  paywatch scan transactions.csv --format json
  paywatch scan transactions.csv --forgotten-only
  paywatch --version
"""

from __future__ import annotations

import argparse
import json
import sys

from paywatch import TOOL_NAME, TOOL_VERSION
from paywatch.core import (
    load_transactions,
    detect_subscriptions,
    summarize,
    subscription_to_dict,
)


def _fmt_money(v: float) -> str:
    return f"${v:,.2f}"


def _render_table(subs, summary) -> str:
    lines = []
    lines.append("")
    lines.append(f"PAYWATCH  recurring-charge report")
    lines.append("=" * 78)
    if not subs:
        lines.append("No recurring charges detected.")
        return "\n".join(lines)
    header = f"{'MERCHANT':<26}{'CADENCE':<11}{'AMOUNT':>10}{'NEXT':>13}{'ANNUAL':>12}"
    lines.append(header)
    lines.append("-" * 78)
    for s in subs:
        flags = ""
        if s.likely_forgotten:
            flags += " [FORGOTTEN?]"
        if s.price_increased:
            flags += " [PRICE UP]"
        merch = (s.merchant[:24] + "..") if len(s.merchant) > 25 else s.merchant
        lines.append(
            f"{merch:<26}{s.cadence:<11}{_fmt_money(s.typical_amount):>10}"
            f"{s.next_charge_estimate:>13}{_fmt_money(s.annualized_cost):>12}"
        )
        if flags:
            lines.append(f"{'':<26}{flags.strip()}")
    lines.append("-" * 78)
    lines.append(
        f"{summary['subscription_count']} subscriptions  |  "
        f"~{_fmt_money(summary['estimated_monthly_cost'])}/mo  |  "
        f"{_fmt_money(summary['total_annualized_cost'])}/yr"
    )
    if summary["likely_forgotten_count"]:
        lines.append(
            f"Potential waste from {summary['likely_forgotten_count']} forgotten "
            f"sub(s): {_fmt_money(summary['likely_forgotten_annual_waste'])}/yr"
        )
    if summary["price_increase_count"]:
        lines.append(
            f"Price increases detected on {summary['price_increase_count']} "
            "subscription(s)."
        )
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description="Detect recurring charges and subscriptions from a bank/Plaid CSV.",
    )
    p.add_argument(
        "--version", action="version", version=f"{TOOL_NAME} {TOOL_VERSION}"
    )
    sub = p.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Scan a CSV for recurring charges.")
    scan.add_argument("csv", help="Path to the transactions CSV file.")
    scan.add_argument(
        "--format", choices=("table", "json"), default="table",
        help="Output format (default: table).",
    )
    scan.add_argument(
        "--forgotten-only", action="store_true",
        help="Only report subscriptions that look forgotten/unused.",
    )
    return p


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        try:
            txns = load_transactions(args.csv)
        except FileNotFoundError:
            print(f"error: file not found: {args.csv}", file=sys.stderr)
            return 2
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2

        subs = detect_subscriptions(txns)
        if args.forgotten_only:
            subs = [s for s in subs if s.likely_forgotten]
        summary = summarize(subs)

        if args.format == "json":
            payload = {
                "tool": TOOL_NAME,
                "version": TOOL_VERSION,
                "summary": summary,
                "subscriptions": [subscription_to_dict(s) for s in subs],
            }
            print(json.dumps(payload, indent=2))
        else:
            print(_render_table(subs, summary))
        return 0

    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
