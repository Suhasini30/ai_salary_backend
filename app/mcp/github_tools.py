"""
GitHub MCP tool runner with dynamic OAuth token support.

Invokes tools from the GitHub Remote MCP server (loaded by `app.mcp.client`)
to answer GitHub-related questions with LIVE user data — e.g. "list my repositories".
"""
import json
import logging

from app.mcp.client import get_tools_for_token

logger = logging.getLogger(__name__)

# Keywords that suggest a GitHub data request. Kept deliberately broad so the
# routed answer is backed by live data instead of the model guessing.
_GITHUB_KEYWORDS = (
    "repo", "repositor", "github", "pull request", "commit",
    "issue", "branch", "star", "fork", "collaborator", "release",
)


def _tool(tools: list, name: str):
    for t in tools:
        if getattr(t, "name", "") == name:
            return t
    return None


def _looks_github(question: str) -> bool:
    q = question.lower()
    return any(k in q for k in _GITHUB_KEYWORDS)


async def run_github_tools(question: str, github_token: str | None = None) -> str:
    """
    If the question is GitHub-related, invokes the remote MCP tools using the user's
    GitHub OAuth token and returns a plain-text snippet with live user data.
    Returns "" when there is nothing to fetch or MCP tools are unavailable.
    """
    if not _looks_github(question):
        return ""

    tools = await get_tools_for_token(github_token)
    if not tools:
        logger.warning("No GitHub MCP tools loaded for question.")
        return ""

    me = _tool(tools, "get_me")
    search = _tool(tools, "search_repositories")

    if not me:
        logger.warning("GitHub MCP tools available but 'get_me' is missing.")
        return ""

    try:
        me_res = await me.ainvoke({})
        me_text = me_res[0]["text"] if isinstance(me_res, list) and me_res else ""
        login = (json.loads(me_text) or {}).get("login", "")
    except Exception as exc:
        logger.error("GitHub MCP 'get_me' failed: %s", exc)
        return ""

    if not login:
        return ""

    if not search:
        logger.warning("GitHub MCP 'search_repositories' tool is missing.")
        return ""

    try:
        res = await search.ainvoke({"query": f"user:{login}", "limit": 30, "minimal_output": False})
        payload = res[0]["text"] if isinstance(res, list) and res else ""
        data = json.loads(payload)
    except Exception as exc:
        logger.error("GitHub MCP 'search_repositories' failed: %s", exc)
        return ""

    items = data.get("items", []) if isinstance(data, dict) else []
    if not items:
        return f"The authenticated GitHub user is `{login}` but no repositories were returned."

    lines = [f"Authenticated GitHub user: {login}", f"Repositories ({len(items)}):"]
    for r in items[:20]:
        desc = (r.get("description") or "").strip()
        lines.append(
            f"- {r.get('name')} | {r.get('html_url')} | language: {r.get('language') or 'n/a'} "
            f"| stars: {r.get('stargazers_count', 0)} | forks: {r.get('forks_count', 0)}"
            + (f" | {desc}" if desc else "")
        )
    return "\n".join(lines)