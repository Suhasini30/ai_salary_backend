"""Profile routes — get, edit, avatar upload, skills."""
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.auth.dependencies import CurrentUser
from app.core.config import settings
from app.models.schemas import ProfilePublic, ProfileUpdate, PublicUser
from app.repos import profiles_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/profile", tags=["profile"])

# Avatar size & type guard.
MAX_AVATAR_BYTES = 5 * 1024 * 1024
ALLOWED_AVATAR_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _avatar_url(key: str) -> str:
    return f"{settings.API_BASE_URL}/api/profile/avatar/{key}"


@router.get("", response_model=ProfilePublic)
async def get_profile(user: PublicUser = CurrentUser):
    profile = await profiles_repo.get_profile(user.id)
    if not profile:
        profile = await profiles_repo.ensure_profile(user.model_dump())
    return await profiles_repo.enrich_with_account(profile)


@router.patch("", response_model=ProfilePublic)
async def update_profile(body: ProfileUpdate, user: PublicUser = CurrentUser):
    data = body.model_dump(exclude_unset=True)
    # Normalise skills to a clean list.
    if data.get("skills") is not None:
        data["skills"] = [s.strip() for s in data["skills"] if s and s.strip()]
    profile = await profiles_repo.update_profile(user.id, data)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")
    return await profiles_repo.enrich_with_account(profile)


@router.post("/avatar", response_model=ProfilePublic)
async def upload_avatar(file: UploadFile = File(...), user: PublicUser = CurrentUser):
    """Uploads an avatar image; returns the profile with the new avatar_url."""
    content = await file.read()
    if len(content) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=400, detail="Avatar image is too large (max 5 MB).")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_AVATAR_EXT:
        raise HTTPException(
            status_code=400,
            detail="Avatar must be png, jpg, jpeg, webp or gif.",
        )

    base = Path(settings.UPLOAD_DIR) / "avatars"
    base.mkdir(parents=True, exist_ok=True)
    key = f"{user.id}/{uuid.uuid4().hex}{ext}"
    dest = base / key
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)

    avatar_url = _avatar_url(key)
    profile = await profiles_repo.update_profile(user.id, {"avatar_url": avatar_url})
    return await profiles_repo.enrich_with_account(profile)


@router.get("/avatar/{key:path}")
async def get_avatar(key: str):
    """Serves an uploaded avatar image safely (path-traversal guarded)."""
    base = (Path(settings.UPLOAD_DIR) / "avatars").resolve()
    target = (base / key).resolve()
    if not target.is_relative_to(base) or not target.exists():
        raise HTTPException(status_code=404, detail="Avatar not found.")
    from fastapi.responses import FileResponse

    return FileResponse(target)