"""PAYWATCH MCP server — exposes scan() as an MCP tool for Cognis.Studio."""
from __future__ import annotations
from paywatch.core import scan, to_json

def serve() -> int:
    """Start an MCP stdio server. Requires the optional 'mcp' extra:
        pip install "cognis-paywatch[mcp]"
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        print("Install the MCP extra: pip install 'cognis-paywatch[mcp]'")
        return 1
    app = FastMCP("paywatch")

    @app.tool()
    def paywatch_scan(target: str) -> str:
        """Recurring-charge and subscription detector from bank/Plaid CSV. Returns JSON findings."""
        return to_json(scan(target))

    app.run()
    return 0
