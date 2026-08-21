"""
MCP Client Manager for GitHub Remote MCP Server with dynamic OAuth token support.
"""

import logging
from typing import Any

try:
    from langchain_mcp_adapters.client import MultiServerMCPClient
except Exception as exc:
    MultiServerMCPClient = None
    logger.warning("MultiServerMCPClient import deferred/unavailable: %s", exc)

from app.core.config import settings

logger = logging.getLogger(__name__)

# Module-level static fallback singleton
_static_client: Any | None = None
_static_tools: list = []


def _build_server_config(github_token: str) -> dict:
    """
    Builds the MultiServerMCPClient config for GitHub's remote MCP server
    using a specific GitHub OAuth / Personal Access Token.
    """
    server_url = settings.GITHUB_MCP_SERVER_URL or "https://api.githubcopilot.com/mcp/"

    return {
        "github": {
            "transport": "streamable_http",
            "url": server_url,
            "headers": {
                "Authorization": f"Bearer {github_token}",
                "User-Agent": "FastAPI-RAG-App",
            },
        },
    }


async def connect():
    """Initialize the static fallback MCP client at app startup if GITHUB_PAT is set."""
    global _static_client, _static_tools

    if not settings.GITHUB_PAT:
        logger.info("GITHUB_PAT is not configured in .env; skipping static fallback MCP connection.")
        _static_tools = []
        return

    try:
        config = _build_server_config(settings.GITHUB_PAT)
        _static_client = MultiServerMCPClient(config)
        _static_tools = await _static_client.get_tools()
        logger.info("Static fallback MCP connected — %d tool(s) loaded.", len(_static_tools))
    except Exception as e:
        logger.warning("Failed to connect static fallback MCP server: %s", e)
        _static_client = None
        _static_tools = []


async def disconnect():
    """Close the MCP client connection at app shutdown."""
    global _static_client, _static_tools
    _static_client = None
    _static_tools = []
    logger.info("MCP client disconnected.")


async def get_tools_for_token(github_token: str | None = None) -> list:
    """
    Dynamically loads tools from the GitHub Remote MCP server for a specific OAuth token.
    If no token is provided, falls back to static GITHUB_PAT tools if available.
    """
    token = (github_token or "").strip()
    if not token:
        token = (settings.GITHUB_PAT or "").strip()

    if not token:
        logger.debug("No GitHub token available for MCP tools.")
        return []

    # If using static PAT and already loaded, return cached static tools
    if token == settings.GITHUB_PAT and _static_tools:
        return _static_tools

    if MultiServerMCPClient is None:
        logger.warning("MultiServerMCPClient is unavailable on this system.")
        return []

    try:
        config = _build_server_config(token)
        client = MultiServerMCPClient(config)
        tools = await client.get_tools()
        logger.info("Dynamically loaded %d GitHub MCP tools for token.", len(tools))
        return tools
    except Exception as exc:
        logger.error("Failed to load GitHub MCP tools for token: %s", exc)
        return []


def get_tools() -> list:
    """Return static fallback tools (backward compatibility)."""
    return _static_tools
