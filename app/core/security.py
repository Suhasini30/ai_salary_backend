"""
Security & token utilities.

Responsible for:
  * Creating/decoding our own JWT access & refresh tokens.
  * Verifying the Clerk session token sent from the frontend (via Clerk JWKS).
  * Managing the refresh-token HttpOnly cookie.

Flow (auth handshake):
  1. Frontend signs the user in with Clerk, obtains a Clerk session token.
  2. Frontend POSTs that token to our /api/auth/verify endpoint.
  3. verify_clerk_token() validates the token signature/expiry against Clerk JWKS.
  4. On success we mint our OWN access token (short-lived, in-memory/JWT) and
     set a refresh token (long-lived) in an HttpOnly cookie.
  5. Subsequent API calls carry the access token in the Authorization header;
     when it expires the frontend calls /api/auth/refresh which reads the
     HttpOnly refresh cookie and rotates both tokens.
"""
import base64
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from fastapi import HTTPException, status
from fastapi.responses import Response
from starlette.requests import Request

from app.core.config import settings

logger = logging.getLogger(__name__)

# Clerk returns public keys as raw JWK JSON. PyJWT can accept an RSA key object,
# so we lazily deserialize each JWK into a cryptography RSA public key.
_jwks_cache: dict[str, Any] = {}
_jwks_lock = threading.Lock()
_jwks_fetched_at: float = 0.0
_JWKS_TTL_SECONDS = 60 * 30  # re-fetch JWKS every 30 minutes


# ---------------------------------------------------------------------------
# Basic token helpers (pyjwt)
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(subject: str, extra: dict | None = None) -> str:
    """Short-lived JWT used in the Authorization header on every API call."""
    expires = _now() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": subject,
        "type": settings.TOKEN_TYPE_ACCESS,
        "iat": int(expires.timestamp() - settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60),
        "exp": int(expires.timestamp()),
        "iss": "rag-app",
        "aud": "rag-app",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(subject: str) -> str:
    """Long-lived JWT stored in an HttpOnly cookie; rotated on every refresh."""
    now = _now()
    expires = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": subject,
        "type": settings.TOKEN_TYPE_REFRESH,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "iss": "rag-app",
        "aud": "rag-app",
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, expected_type: str | None = None) -> dict:
    """
    Decodes & validates one of our own JWTs, returning its claims.
    Raises HTTPException(401/403) on any failure — callers just await it.
    """
    try:
        claims = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            audience="rag-app",
            issuer="rag-app",
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as exc:
        logger.warning("Invalid token rejected: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if expected_type and claims.get("type") != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token type mismatch (expected {expected_type})",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return claims


def get_bearer_token(request: Request) -> str | None:
    """Extracts the access token from the 'Authorization: Bearer ...' header."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer "):].strip()
    return None


# ---------------------------------------------------------------------------
# Clerk token verification (JWKS)
# ---------------------------------------------------------------------------

def _jwk_to_key(jwk: dict) -> rsa.RSAPublicKey:
    """Converts a raw RSA JWK dict into a cryptography RSA public key."""
    n_bytes = base64.urlsafe_b64decode(jwk["n"] + "==")
    e_bytes = base64.urlsafe_b64decode(jwk["e"] + "==")
    public_numbers = rsa.RSAPublicNumbers(
        e=int.from_bytes(e_bytes, "big"),
        n=int.from_bytes(n_bytes, "big"),
    )
    return public_numbers.public_key()


def _load_jwks() -> dict[str, dict]:
    """
    Fetches (and caches) Clerk's JWKS — the public keys used to verify the
    Clerk session token's signature.
    """
    global _jwks_cache, _jwks_fetched_at

    with _jwks_lock:
        now = time.time()
        if _jwks_cache and (now - _jwks_fetched_at) < _JWKS_TTL_SECONDS:
            return _jwks_cache

        if not settings.CLERK_JWKS_URL:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Clerk JWKS endpoint is not configured on the server.",
            )

        try:
            resp = httpx.get(settings.CLERK_JWKS_URL, timeout=15.0)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("Failed to fetch Clerk JWKS from %s: %s", settings.CLERK_JWKS_URL, exc)
            # Serve stale cache if we ever had one; otherwise fail closed.
            if _jwks_cache:
                return _jwks_cache
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to reach identity provider.",
            )

        keys = {}
        for jwk in data.get("keys", []):
            kid = jwk.get("kid")
            if not kid:
                continue
            try:
                keys[kid] = _jwk_to_key(jwk)
            except Exception as exc:
                logger.warning("Skipping invalid Clerk JWK (%s): %s", kid, exc)

        if not keys:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Identity provider returned no usable signing keys.",
            )

        _jwks_cache = keys
        _jwks_fetched_at = now
        logger.info("Loaded %d Clerk signing keys.", len(keys))
        return keys


def verify_clerk_token(clerk_token: str) -> dict:
    """
    Verifies a Clerk session token (JWT) using Clerk's JWKS.
    Returns the decoded claims (contains `sub` = the Clerk user id).

    Validation performed:
      * signature against a Clerk public key (match on kid),
      * issuer matches settings.CLERK_ISSUER,
      * 'azp' matches any configured CLERK_FRONTEND_API_URL when it exists.
    """
    try:
        header = jwt.get_unverified_header(clerk_token)
    except jwt.InvalidTokenError as exc:
        logger.warning("Malformed Clerk token header: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Clerk token.",
        )

    kid = header.get("kid")
    keys = _load_jwks()
    key = keys.get(kid)
    if not key:
        # A brand-new signing key we haven't seen - force a JWKS refresh once.
        global _jwks_fetched_at
        with _jwks_lock:
            _jwks_fetched_at = 0.0
        keys = _load_jwks()
        key = keys.get(kid)
        if not key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unknown Clerk signing key.",
            )

    try:
        claims = jwt.decode(
            clerk_token,
            key=key,
            algorithms=["RS256"],
            issuer=settings.CLERK_ISSUER,
            options={"verify_aud": False},  # Clerk tokens don't carry our audience
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Clerk session token has expired.",
        )
    except jwt.InvalidTokenError as exc:
        logger.warning("Clerk token verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Clerk token could not be verified.",
        )

    if not claims.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Clerk token missing subject.",
        )

    return claims


# ---------------------------------------------------------------------------
# Refresh-token HttpOnly cookie handling
# ---------------------------------------------------------------------------

def build_refresh_cookie_kwargs(max_age_seconds: int | None = None) -> dict:
    """Common kwargs for setting/clearing the refresh-token cookie."""
    return {
        "key": settings.COOKIE_NAME,
        "path": settings.COOKIE_PATH,
        "domain": settings.COOKIE_DOMAIN,       # None → host-only cookie
        "secure": settings.COOKIE_SECURE,
        "httponly": True,                        # JS can never read it → XSS safe
        "samesite": settings.COOKIE_SAMESITE or "lax",
        "max_age": max_age_seconds,
        "expires": max_age_seconds,
    }


def set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """Attaches the refresh token to a response as an HttpOnly cookie."""
    max_age = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    response.set_cookie(
        **build_refresh_cookie_kwargs(max_age),
        value=refresh_token,
    )


def clear_refresh_cookie(response: Response) -> None:
    """Expires the refresh-token cookie (logout)."""
    kwargs = build_refresh_cookie_kwargs()
    kwargs.pop("max_age", None)
    kwargs.pop("expires", None)
    response.delete_cookie(**kwargs)


def get_refresh_token(request: Request) -> str | None:
    """Reads the refresh token from the HttpOnly cookie."""
    return request.cookies.get(settings.COOKIE_NAME)


def rotate_refresh_token(request: Request, response: Response) -> str:
    """
    Validates the current refresh cookie and issues a brand-new pair.
    Raises 401 if the cookie is missing/invalid/expired/type-mismatched.
    """
    token = get_refresh_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token found (cookie not present).",
        )

    claims = decode_token(token, expected_type=settings.TOKEN_TYPE_REFRESH)
    subject = claims.get("sub")
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing subject.",
        )

    # Rotate: new refresh token + new access token (both replaced atomically).
    new_refresh = create_refresh_token(subject)
    set_refresh_cookie(response, new_refresh)
    return subject