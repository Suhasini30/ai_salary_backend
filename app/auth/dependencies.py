"""
FastAPI dependencies that inject the authenticated user.

`get_current_user` is the single choke-point for all protected routes:
it validates the access token and loads the matching `users` record, then
every repo is handed this user's id for scoping.
"""
import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request, status

from app.core.security import decode_token, get_bearer_token
from app.models.schemas import PublicUser
from app.repos import users_repo

logger = logging.getLogger(__name__)


async def get_current_user(request: Request) -> PublicUser:
    token = get_bearer_token(request)
    if not token:
        # Preview mode: no token at all → per-session anonymous guest.
        # The frontend sends a stable `X-Guest-Id` (UUID in localStorage) so
        # every browser gets its own isolated conversation history instead of
        # sharing one global guest account.
        guest_id = request.headers.get("X-Guest-Id")
        return await users_repo.get_or_create_guest_user(guest_id)

    try:
        claims = decode_token(token, expected_type="access")
    except HTTPException:
        raise
    except Exception:
        # A token WAS supplied but is invalid/corrupt → surface 401 so the
        # frontend refresh interceptor can rotate it. Never silently become
        # the shared guest, otherwise authenticated users see guest data.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await users_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.is_banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended.")

    return user



async def optional_user(request: Request) -> Optional[PublicUser]:
    """Like get_current_user but returns None instead of raising (health checks, etc.)."""
    try:
        return await get_current_user(request)
    except HTTPException:
        return None


CurrentUser = Depends(get_current_user)