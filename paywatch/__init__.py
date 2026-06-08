"""PAYWATCH - Recurring-charge and subscription detector from bank/Plaid CSV.

Reads a transaction CSV (date, description, amount) and surfaces recurring
charges, estimated cadence (weekly/monthly/annual), next-charge prediction,
price hikes, likely-forgotten subscriptions, and annualized spend.
"""

from paywatch.core import (
    Transaction,
    Subscription,
    load_transactions,
    detect_subscriptions,
    summarize,
)

TOOL_NAME = "paywatch"
TOOL_VERSION = "1.0.0"

__all__ = [
    "TOOL_NAME",
    "TOOL_VERSION",
    "Transaction",
    "Subscription",
    "load_transactions",
    "detect_subscriptions",
    "summarize",
]
