"""
GitHub OAuth routes for per-user dynamic MCP authentication.

Provides endpoints to:
  1. GET  /api/auth/github/authorize  - Build the GitHub OAuth redirect URL
  2. GET  /api/auth/github/callback   - Exchange OAuth authorization code for an access token
  3. GET  /api/auth/github/status     - Get current user's GitHub connection status
  4. POST /api/auth/github/disconnect - Remove stored GitHub credentials for current user
"""
import logging
from typing import Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth.dependencies import get_current_user
from app.core.config import settings
from app.models.schemas import PublicUser
from app.repos import profiles_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/github", tags=["github-oauth"])


@router.get("/authorize")
async def get_github_authorize_url(
    user: PublicUser = Depends(get_current_user),
    redirect: Optional[str] = Query(default=None),
    prompt: Optional[str] = Query(default="consent")
):
    """
    Returns the GitHub OAuth authorization URL for the user to initiate consent.
    """
    if not settings.GITHUB_CLIENT_ID:
        raise HTTPException(
            status_code=400,
            detail="GitHub OAuth App is not configured yet. Please set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in backend .env."
        )

    # State can carry the current user id for validation
    state = f"user_{user.id}"
    scope = "repo read:user"
    redirect_uri = settings.GITHUB_REDIRECT_URI

    auth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={settings.GITHUB_CLIENT_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scope}"
        f"&state={state}"
    )
    if prompt:
        auth_url += f"&prompt={prompt}"

    return {"url": auth_url}


@router.get("/callback")
async def github_oauth_callback(
    code: str = Query(...),
    state: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
):
    """
    GitHub OAuth callback endpoint. Exchanges the auth code for an access token,
    fetches the GitHub user profile, and stores credentials under the user's profile.
    """
    if error:
        logger.error("GitHub OAuth error returned in callback: %s", error)
        return HTMLResponse(
            content=f"<html><body><h2>GitHub Connection Error</h2><p>{error}</p><script>setTimeout(() => window.close(), 3000);</script></body></html>",
            status_code=400,
        )

    if not settings.GITHUB_CLIENT_ID or not settings.GITHUB_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="GitHub OAuth credentials (CLIENT_ID / CLIENT_SECRET) are not configured."
        )

    # Extract user_id from state param if present (state format: "user_<user_id>")
    user_id = None
    if state and state.startswith("user_"):
        user_id = state.replace("user_", "")

    # 1. Exchange authorization code for token
    token_url = "https://github.com/login/oauth/access_token"
    payload = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "client_secret": settings.GITHUB_CLIENT_SECRET,
        "code": code,
        "redirect_uri": settings.GITHUB_REDIRECT_URI,
    }
    headers = {"Accept": "application/json"}

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(token_url, data=payload, headers=headers)
        if token_resp.status_code != 200:
            logger.error("GitHub OAuth token exchange failed: %s", token_resp.text)
            raise HTTPException(status_code=400, detail="Failed to exchange code for GitHub token.")

        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            logger.error("No access_token returned by GitHub: %s", token_data)
            raise HTTPException(status_code=400, detail=token_data.get("error_description", "GitHub authorization failed."))

        # 2. Fetch authenticated GitHub username
        user_resp = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "FastAPI-RAG-App",
            },
        )
        github_username = ""
        if user_resp.status_code == 200:
            github_username = user_resp.json().get("login", "")

    # 3. Save token to user profile if user_id is known
    if user_id:
        saved = await profiles_repo.set_github_oauth(user_id, access_token, github_username)
        if saved:
            logger.info("GitHub OAuth token saved for user_id=%s (@%s)", user_id, github_username)

    # Return auto-closing popup / redirect script for smooth UI UX
    frontend_url = settings.FRONTEND_ORIGINS[0] if settings.FRONTEND_ORIGINS else "http://localhost:3000"
    html_content = f"""
    <!DOCTYPE html>
    <html>
      <head><title>GitHub Connected</title></head>
      <body style="font-family: sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; background: #09090b; color: #fff;">
        <div style="text-align: center;">
          <h2 style="color: #10b981;">GitHub Connected Successfully!</h2>
          <p>Authenticated as <strong>@{github_username}</strong></p>
          <p style="color: #a1a1aa; font-size: 0.85rem;">This window will close automatically...</p>
        </div>
        <script>
          if (window.opener) {{
            window.opener.postMessage({{ type: 'GITHUB_OAUTH_SUCCESS', username: '{github_username}' }}, '*');
            setTimeout(() => window.close(), 1200);
          }} else {{
            setTimeout(() => {{ window.location.href = '{frontend_url}'; }}, 1500);
          }}
        </script>
      </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@router.get("/status")
async def get_github_oauth_status(user: PublicUser = Depends(get_current_user)):
    """Returns whether the logged-in user has connected their GitHub account."""
    oauth_info = await profiles_repo.get_github_oauth(user.id)
    if not oauth_info:
        return {"connected": False, "github_username": None}

    return {
        "connected": True,
        "github_username": oauth_info.get("github_username"),
        "connected_at": oauth_info.get("connected_at"),
    }


@router.post("/disconnect")
async def disconnect_github_oauth(user: PublicUser = Depends(get_current_user)):
    """Disconnects the GitHub account for the logged-in user."""
    await profiles_repo.remove_github_oauth(user.id)
    logger.info("Disconnected GitHub account for user_id=%s", user.id)
    return {"status": "disconnected", "connected": False}
