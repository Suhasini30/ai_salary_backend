"""
Chunk repository — RAG chunks + embeddings stored in the existing
`vector_documents` collection.

Everything here is scoped by `user_id`, and the same `user_id` is stamped on
every chunk so Atlas vector search can pre-filter by it at query time.
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId

from app.core.database import chunks_collection


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def insert_many(user_id: str, document_id: str, chunks: list[dict]) -> int:
    """
    Persists chunk documents into `vector_documents`.
    Each item:
      {text, embedding, metadata{filename, page, chunk_index, doc_id}, user_id, ...}
    """
    if not chunks:
        return 0

    now = _now()
    docs = []
    for c in chunks:
        md = c.get("metadata") or {}
        docs.append(
            {
                "user_id": ObjectId(user_id),
                "document_id": ObjectId(document_id),
                "doc_type": "user_document",
                "text": c["text"],
                "embedding": c.get("embedding"),
                "chunk_index": md.get("chunk_index"),
                "page_number": md.get("page"),
                "filename": md.get("filename") or c.get("filename"),
                "created_at": now,
                "updated_at": now,
            }
        )

    result = await chunks_collection().insert_many(docs, ordered=False)
    return len(result.inserted_ids)


async def delete_by_document(user_id: str, document_id: str) -> int:
    """Deletes all chunks belonging to one of the user's documents."""
    try:
        doc_id = ObjectId(document_id)
    except Exception:
        return 0
    result = await chunks_collection().delete_many(
        {"user_id": ObjectId(user_id), "document_id": doc_id}
    )
    return result.deleted_count


async def count_for_user(user_id: str) -> int:
    return await chunks_collection().count_documents({"user_id": ObjectId(user_id)})


async def count_for_document(user_id: str, document_id: str) -> int:
    try:
        doc_id = ObjectId(document_id)
    except Exception:
        return 0
    return await chunks_collection().count_documents(
        {"user_id": ObjectId(user_id), "document_id": doc_id}
    )


async def count_all() -> int:
    return await chunks_collection().count_documents({})