"""
Profile repository — user application data (kept separate from `users`).

Profiles are keyed by the same Mongo _id as `users` (one profile per user),
so `user_id` IS the unique key here — there's no way to address another
user's profile except through their id.
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId

from app.core.database import profiles_collection as _p
from app.core.database import users_collection
from app.models.schemas import ProfilePublic


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_public(profile: dict | None) -> ProfilePublic | None:
    if not profile:
        return None
    return ProfilePublic(
        user_id=str(profile["user_id"]),
        username=profile.get("username"),
        full_name=profile.get("full_name"),
        bio=profile.get("bio"),
        location=profile.get("location"),
        avatar_url=profile.get("avatar_url"),
        skills=profile.get("skills") or [],
        created_at=profile.get("created_at"),
        updated_at=profile.get("updated_at"),
    )


async def ensure_profile(user: dict) -> ProfilePublic:
    """
    Guarantees a profile exists for a user (idempotent — called on every
    auth verify / login). Defaults come from the `users` record.
    """
    existing = await _p().find_one({"user_id": ObjectId(user["id"])})
    if existing:
        return _to_public(existing)

    now = _utcnow()
    profile = {
        "user_id": ObjectId(user["id"]),
        "username": user.get("username"),
        "full_name": None,
        "bio": None,
        "location": None,
        "avatar_url": None,
        "skills": [],
        "created_at": now,
        "updated_at": now,
    }
    await _p().insert_one(profile)
    logger_created(user["id"])
    return _to_public(profile)


def logger_created(user_id: str) -> None:
    import logging
    logging.getLogger(__name__).info("Created `profiles` record for user_id=%s", user_id)


async def get_profile(user_id: str) -> ProfilePublic | None:
    try:
        obj_id = ObjectId(user_id)
    except Exception:
        return None
    return _to_public(await _p().find_one({"user_id": obj_id}))


async def update_profile(user_id: str, data: dict) -> ProfilePublic | None:
    try:
        obj_id = ObjectId(user_id)
    except Exception:
        return None

    patch = {k: v for k, v in data.items() if v is not None}
    if not patch:
        return await get_profile(user_id)

    patch["updated_at"] = _utcnow()
    await _p().update_one({"user_id": obj_id}, {"$set": patch}, upsert=False)
    return await get_profile(user_id)


async def completion_percent(user_id: str) -> int:
    """Profile completion 0..100 based on how many optional fields are filled."""
    profile = await get_profile(user_id)
    if not profile:
        return 0
    weights = {
        "username": profile.username,
        "full_name": profile.full_name,
        "bio": profile.bio,
        "location": profile.location,
        "avatar_url": profile.avatar_url,
    }
    filled = sum(1 for v in weights.values() if v)
    if profile.skills:
        filled += 1
    return round(filled / (len(weights) + 1) * 100)


async def enrich_with_account(profile: ProfilePublic) -> ProfilePublic:
    """Adds joined-from-`users` info (email, verified, joined date) for the profile page."""
    user_doc = await users_collection().find_one(
        {"_id": ObjectId(profile.user_id)},
        {"email": 1, "is_verified": 1, "created_at": 1},
    )
    if user_doc:
        profile.email = user_doc.get("email")
        profile.is_verified = bool(user_doc.get("is_verified", False))
        profile.joined_at = user_doc.get("created_at")
    return profile