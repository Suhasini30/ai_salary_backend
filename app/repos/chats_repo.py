"""
Chat/Conversation repository — conversation headers, scoped by user.
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId

from app.core.database import chats_collection, messages_collection
from app.models.schemas import ConversationPublic


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_public(c: dict, message_count: int = 0) -> ConversationPublic:
    return ConversationPublic(
        id=str(c["_id"]),
        title=c.get("title") or "Untitled conversation",
        created_at=c.get("created_at"),
        updated_at=c.get("updated_at"),
        message_count=message_count,
    )


async def create(user_id: str, title: Optional[str], first_message: str) -> ConversationPublic:
    if not title:
        # Derive a friendly title from the first message.
        cleaned = " ".join(first_message.split())
        title = cleaned[:42] + ("…" if len(cleaned) > 42 else "")

    now = _now()
    conv = {
        "user_id": ObjectId(user_id),
        "title": title,
        "created_at": now,
        "updated_at": now,
    }
    result = await chats_collection().insert_one(conv)
    return _to_public({**conv, "_id": result.inserted_id})


async def list_for_user(user_id: str, limit: int = 50) -> list[ConversationPublic]:
    cursor = (
        chats_collection()
        .find({"user_id": ObjectId(user_id)})
        .sort("updated_at", -1)
        .limit(limit)
    )
    convos = []
    async for c in cursor:
        count = await messages_collection().count_documents(
            {"user_id": ObjectId(user_id), "conversation_id": c["_id"]}
        )
        convos.append(_to_public(c, count))
    return convos


async def get_for_user(user_id: str, conversation_id: str) -> Optional[dict]:
    try:
        obj_id = ObjectId(conversation_id)
    except Exception:
        return None
    return await chats_collection().find_one({"_id": obj_id, "user_id": ObjectId(user_id)})


async def touch(user_id: str, conversation_id: str) -> None:
    try:
        obj_id = ObjectId(conversation_id)
    except Exception:
        return
    await chats_collection().update_one(
        {"_id": obj_id, "user_id": ObjectId(user_id)},
        {"$set": {"updated_at": _now()}},
    )


async def delete_for_user(user_id: str, conversation_id: str) -> bool:
    try:
        obj_id = ObjectId(conversation_id)
    except Exception:
        return False
    result = await chats_collection().delete_one({"_id": obj_id, "user_id": ObjectId(user_id)})
    if result.deleted_count:
        await messages_collection().delete_many(
            {"user_id": ObjectId(user_id), "conversation_id": obj_id}
        )
        return True
    return False


async def count_for_user(user_id: str) -> int:
    return await chats_collection().count_documents({"user_id": ObjectId(user_id)})