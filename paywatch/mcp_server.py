"""PAYWATCH MCP server — exposes scan() as an MCP tool for Cognis.Studio."""
from __future__ import annotations

import json

from paywatch.core import (
    detect_subscriptions,
    load_transactions,
    subscription_to_dict,
    summarize,
)
from paywatch import TOOL_NAME, TOOL_VERSION


def _scan_to_json(csv_path: str) -> str:
    """Load *csv_path*, run detection, return a JSON string of findings."""
    txns = load_transactions(csv_path)
    subs = detect_subscriptions(txns)
    summary = summarize(subs)
    payload = {
        "tool": TOOL_NAME,
        "version": TOOL_VERSION,
        "summary": summary,
        "subscriptions": [subscription_to_dict(s) for s in subs],
    }
    return json.dumps(payload, indent=2)


def serve() -> int:
    """Start an MCP stdio server. Requires the optional 'mcp' extra:
        pip install "cognis-paywatch[mcp]"
    """
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore[import]
    except Exception:
        print("Install the MCP extra: pip install 'cognis-paywatch[mcp]'")
        return 1
    app = FastMCP("paywatch")

    @app.tool()
    def paywatch_scan(target: str) -> str:
        """Recurring-charge and subscription detector from bank/Plaid CSV.

        Returns JSON findings.
        """
        try:
            return _scan_to_json(target)
        except (FileNotFoundError, PermissionError, ValueError) as exc:
            return json.dumps({"error": str(exc)})

    app.run()
    return 0
