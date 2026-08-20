"""
Document repository — metadata for uploaded documents.

Every document is scoped to `user_id`; every query filters by it, so a user
can never see or delete another user's documents.
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId

from app.core.database import documents_collection
from app.models.schemas import DocumentPublic, DocumentStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_public(doc: dict) -> DocumentPublic:
    return DocumentPublic(
        id=str(doc["_id"]),
        filename=doc["filename"],
        file_size=doc.get("file_size", 0),
        content_type=doc.get("content_type", ""),
        status=doc.get("status", DocumentStatus.PENDING.value),
        error=doc.get("error"),
        chunk_count=doc.get("chunk_count", 0),
        page_count=doc.get("page_count"),
        created_at=doc.get("created_at"),
        updated_at=doc.get("updated_at"),
    )


async def create(user_id: str, filename: str, file_size: int, content_type: str) -> DocumentPublic:
    now = _now()
    doc = {
        "user_id": ObjectId(user_id),
        "filename": filename,
        "file_size": file_size,
        "content_type": content_type,
        "status": DocumentStatus.PENDING.value,
        "error": None,
        "chunk_count": 0,
        "page_count": None,
        "storage_key": None,  # path on disk / object storage reference
        "created_at": now,
        "updated_at": now,
    }
    result = await documents_collection().insert_one(doc)
    return _to_public({**doc, "_id": result.inserted_id})


async def list_documents(user_id: str, limit: int = 100) -> list[DocumentPublic]:
    cursor = (
        documents_collection()
        .find({"user_id": ObjectId(user_id)})
        .sort("created_at", -1)
        .limit(limit)
    )
    return [_to_public(d) async for d in cursor]


async def get_for_user(user_id: str, document_id: str) -> Optional[DocumentPublic]:
    try:
        obj_id = ObjectId(document_id)
    except Exception:
        return None
    doc = await documents_collection().find_one({"_id": obj_id, "user_id": ObjectId(user_id)})
    return _to_public(doc) if doc else None


async def update(user_id: str, document_id: str, patch: dict) -> Optional[DocumentPublic]:
    try:
        obj_id = ObjectId(document_id)
    except Exception:
        return None
    patch["updated_at"] = _now()
    result = await documents_collection().update_one(
        {"_id": obj_id, "user_id": ObjectId(user_id)},
        {"$set": patch},
    )
    if not result.matched_count:
        return None
    return await get_for_user(user_id, document_id)


async def set_status(user_id: str, document_id: str, status: str, error: str | None = None) -> None:
    patch = {"status": status}
    if error is not None:
        patch["error"] = error
    await update(user_id, document_id, patch)


async def delete_for_user(user_id: str, document_id: str) -> bool:
    try:
        obj_id = ObjectId(document_id)
    except Exception:
        return False
    result = await documents_collection().delete_one({"_id": obj_id, "user_id": ObjectId(user_id)})
    return result.deleted_count > 0


async def count_for_user(user_id: str) -> int:
    return await documents_collection().count_documents({"user_id": ObjectId(user_id)})


async def update_chunk_count(user_id: str, document_id: str, count: int) -> None:
    await update(user_id, document_id, {"chunk_count": count})