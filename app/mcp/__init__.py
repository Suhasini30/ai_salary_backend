"""
Model Context Protocol (MCP) package.
Exposes MCP client lifecycle operations (connect, disconnect, get_tools).
"""
from app.mcp.client import connect, disconnect, get_tools

__all__ = ["connect", "disconnect", "get_tools"]
