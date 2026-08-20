"""
User repository — auth-related records only (kept separate from profiles).

The `users` collection mirrors Clerk's identity: clerk_id is the natural key.
The repo NEVER surfaces sensitive fields like `hashed_refresh_token`.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from app.core.database import users_collection
from app.models.schemas import PublicUser

logger = logging.getLogger(__name__)

# Fields exposed to the API layer (never internals/details like token hashes).
SAFE_FIELDS = {"_id", "clerk_id", "email", "username", "is_verified", "is_banned"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_public(doc: dict) -> PublicUser:
    return PublicUser(
        id=str(doc["_id"]),
        clerk_id=doc["clerk_id"],
        email=doc.get("email"),
        username=doc.get("username"),
        is_verified=bool(doc.get("is_verified", False)),
        is_banned=bool(doc.get("is_banned", False)),
    )


async def upsert_from_clerk(claims: dict, email: str | None = None, username: str | None = None) -> PublicUser:
    """
    Creates or updates the `users` record from verified Clerk claims.
    Returns the public user. Never returns internal fields.

    The Clerk session token only carries `sub`; the frontend supplies the
    real email/username from Clerk's user object as a fallback when the
    token claims don't include them.
    """
    clerk_id = claims["sub"]
    email = (email or claims.get("email") or "").lower() or None
    username = username or claims.get("username") or (email.split("@")[0] if email else None)
    is_verified = bool(claims.get("email_verified", False) or claims.get("is_verified", False))
    now = _utcnow()

    doc = await users_collection().find_one({"clerk_id": clerk_id})

    if doc:
        updates = {"updated_at": now}
        if email:
            updates["email"] = email
        if username:
            updates["username"] = username
        if is_verified and not doc.get("is_verified"):
            updates["is_verified"] = True
        await users_collection().update_one({"_id": doc["_id"]}, {"$set": updates})
        return _to_public({**doc, **updates})

    user = {
        "clerk_id": clerk_id,
        "email": email,
        "username": username,
        "is_verified": is_verified,
        "is_banned": False,
        # Field exists in the real DB (per screenshots); default to None on new rows.
        "hashed_refresh_token": None,
        "created_at": now,
        "updated_at": now,
    }
    result = await users_collection().insert_one(user)
    logger.info("Created `users` record for clerk_id=%s", clerk_id)
    return _to_public({**user, "_id": result.inserted_id})


async def get_by_id(user_id: str) -> Optional[PublicUser]:
    try:
        from bson import ObjectId
        obj_id = ObjectId(user_id)
    except Exception:
        return None
    doc = await users_collection().find_one({"_id": obj_id}, SAFE_FIELDS)
    return _to_public(doc) if doc else None


async def get_by_clerk_id(clerk_id: str) -> Optional[PublicUser]:
    doc = await users_collection().find_one({"clerk_id": clerk_id}, SAFE_FIELDS)
    return _to_public(doc) if doc else None


async def is_banned(user_id: str) -> bool:
    try:
        from bson import ObjectId
        obj_id = ObjectId(user_id)
    except Exception:
        return True
    return bool((await users_collection().find_one({"_id": obj_id}, {"is_banned": 1}) or {}).get("is_banned", False))


async def get_or_create_guest_user(guest_id: str | None = None) -> PublicUser:
    """
    Returns a guest user for unauthenticated requests.

    Each browser session passes its own `guest_id` (a UUID stored in the
    frontend's localStorage). That id becomes a UNIQUE user record keyed by
    `clerk_id = "guest:<guest_id>"`, so every anonymous visitor gets their
    OWN isolated conversation history — no two guests ever share data.

    Falls back to the shared `guest_user_default` only when no id is given.
    """
    guest_key = f"guest:{guest_id}" if guest_id else "guest_user_default"
    doc = await users_collection().find_one({"clerk_id": guest_key}, SAFE_FIELDS)
    if doc:
        return _to_public(doc)
    now = _utcnow()
    guest = {
        "clerk_id": guest_key,
        "email": "guest@marketai.local",
        "username": "Guest User",
        "is_verified": True,
        "is_banned": False,
        "hashed_refresh_token": None,
        "created_at": now,
        "updated_at": now,
    }
    res = await users_collection().insert_one(guest)
    return _to_public({**guest, "_id": res.inserted_id})