"""
Authentication routes.

Handles the Clerk handshake:

  1. POST /api/auth/verify — receives the Clerk session token from the
     frontend, verifies it against Clerk's JWKS, upserts the `users` +
     `profiles` records, and issues our own access token (header) + refresh
     token (HttpOnly cookie).
  2. POST /api/auth/refresh — rotates the refresh cookie and returns a new
     access token.
  3. POST /api/auth/logout — clears the refresh cookie.
  4. GET  /api/auth/me     — returns the current user + profile.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.auth.dependencies import get_current_user
from app.core.config import settings
from app.core.security import (
    clear_refresh_cookie,
    create_access_token,
    create_refresh_token,
    get_refresh_token,
    rotate_refresh_token,
    set_refresh_cookie,
    verify_clerk_token,
)
from app.models.schemas import AuthVerifyRequest, ProfilePublic, PublicUser
from app.repos import profiles_repo, users_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _token_response(user: PublicUser) -> dict:
    access = create_access_token(user.id)
    return {
        "access_token": access,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": {
            "id": user.id,
            "clerk_id": user.clerk_id,
            "email": user.email,
            "username": user.username,
            "is_verified": user.is_verified,
            "is_banned": user.is_banned,
        },
    }


@router.post("/login", response_model=None)
@router.post("/verify", response_model=None)
async def verify_clerk_session(body: AuthVerifyRequest, response: Response):
    """
    Exchanges a Clerk session token for our own access token (Authorization
    header) + refresh token (HttpOnly cookie). `POST /api/auth/login` is the
    canonical path; `/api/auth/verify` remains as an alias.
    """
    claims = verify_clerk_token(body.clerk_token)

    user = await users_repo.upsert_from_clerk(
        claims, email=body.email, username=body.username
    )
    # Build a plain dict for the profile repo (repo uses the user id as key).
    user_dict = {
        "id": user.id,
        "clerk_id": user.clerk_id,
        "username": user.username,
        "email": user.email,
    }
    await profiles_repo.ensure_profile(user_dict)

    # Attach refresh token as HttpOnly cookie, return access token in JSON.
    set_refresh_cookie(response, create_refresh_token(user.id))
    logger.info("Authenticated user %s (clerk_id=%s)", user.id, user.clerk_id)
    return _token_response(user)


@router.post("/refresh")
async def refresh_access_token(request: Request, response: Response):
    """Rotates the refresh cookie and issues a fresh access token."""
    subject = rotate_refresh_token(request, response)
    user = await users_repo.get_by_id(subject)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Account not found.",
        )
    if user.is_banned:
        raise HTTPException(status_code=403, detail="Account suspended.")
    return _token_response(user)


@router.post("/logout")
async def logout(response: Response):
    """Invalidates the refresh token by clearing the HttpOnly cookie."""
    clear_refresh_cookie(response)
    return {"status": "logged_out"}


@router.get("/me")
async def me(user: PublicUser = Depends(get_current_user)):
    """Returns the authenticated user + their profile."""
    profile = await profiles_repo.get_profile(user.id)
    profile = await profiles_repo.enrich_with_account(profile) if profile else None
    return {"user": user.model_dump(), "profile": profile.model_dump() if profile else None}


@router.get("/session")
async def session_status(request: Request, response: Response):
    """Used by the frontend to check whether a refresh cookie exists."""
    has_cookie = bool(get_refresh_token(request))
    return {"authenticated": has_cookie}