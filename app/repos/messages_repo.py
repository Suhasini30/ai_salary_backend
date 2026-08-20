"""
Message repository — individual chat messages (with source citations) inside
a conversation, scoped by user.
"""
from datetime import datetime, timezone

from bson import ObjectId

from app.core.database import messages_collection
from app.models.schemas import ChatMessagePublic


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_public(m: dict) -> ChatMessagePublic:
    return ChatMessagePublic(
        id=str(m["_id"]),
        role=m["role"],
        content=m.get("content", ""),
        sources=m.get("sources") or [],
        created_at=m.get("created_at"),
    )


async def insert(
    user_id: str,
    conversation_id: str,
    role: str,
    content: str,
    sources: list[dict] | None = None,
) -> ChatMessagePublic:
    msg = {
        "user_id": ObjectId(user_id),
        "conversation_id": ObjectId(conversation_id),
        "role": role,
        "content": content,
        "sources": sources or [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    result = await messages_collection().insert_one(msg)
    return _to_public({**msg, "_id": result.inserted_id})


async def list_for_conversation(user_id: str, conversation_id: str) -> list[ChatMessagePublic]:
    try:
        conv_id = ObjectId(conversation_id)
    except Exception:
        return []
    cursor = (
        messages_collection()
        .find({"user_id": ObjectId(user_id), "conversation_id": conv_id})
        .sort("created_at", 1)
    )
    return [_to_public(m) async for m in cursor]


async def last_user_message(user_id: str, conversation_id: str) -> ChatMessagePublic | None:
    try:
        conv_id = ObjectId(conversation_id)
    except Exception:
        return None
    cursor = (
        messages_collection()
        .find({"user_id": ObjectId(user_id), "conversation_id": conv_id, "role": "user"})
        .sort("created_at", -1)
        .limit(1)
    )
    doc = await cursor.to_list(length=1)
    return _to_public(doc[0]) if doc else None


async def delete_last_assistant(user_id: str, conversation_id: str) -> None:
    """Removes the most recent assistant message (used by 'regenerate')."""
    try:
        conv_id = ObjectId(conversation_id)
    except Exception:
        return
    cursor = (
        messages_collection()
        .find({"user_id": ObjectId(user_id), "conversation_id": conv_id, "role": "assistant"})
        .sort("created_at", -1)
        .limit(1)
    )
    doc = await cursor.to_list(length=1)
    if doc:
        await messages_collection().delete_one({"_id": doc[0]["_id"]})


async def count_for_user(user_id: str) -> int:
    return await messages_collection().count_documents({"user_id": ObjectId(user_id)})