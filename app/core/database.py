"""
Async MongoDB connectivity (Motor).

A single long-lived AsyncIOMotorClient is created lazily on first use so the
FastAPI app still boots fast even if MongoDB is temporarily unreachable. Every
collection lives inside the existing `rag_db` database:

  * users            — authentication-related records (clerk_id, flags, tokens)
  * profiles         — user application/profile data (kept separate from auth)
  * documents        — metadata for each uploaded document
  * vector_documents — RAG chunks + embeddings (existing collection, reused)
  * chats            — conversation headers
  * messages         — individual chat messages (with sources)
"""
import logging

import certifi
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        if not settings.MONGO_URI:
            raise RuntimeError("MONGO_URI is not configured.")
        _client = AsyncIOMotorClient(
            settings.MONGO_URI,
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=10000,
            connectTimeoutMS=10000,
        )
        logger.info("MongoDB client initialised (db=%s).", settings.MONGODB_DATABASE)
    return _client


def get_db() -> AsyncIOMotorDatabase:
    return get_client()[settings.MONGODB_DATABASE]


def users_collection() -> AsyncIOMotorCollection:
    return get_db()["users"]


def profiles_collection() -> AsyncIOMotorCollection:
    return get_db()["profiles"]


def documents_collection() -> AsyncIOMotorCollection:
    return get_db()["documents"]


def chunks_collection() -> AsyncIOMotorCollection:
    return get_db()["vector_documents"]


def chats_collection() -> AsyncIOMotorCollection:
    return get_db()["chats"]


def messages_collection() -> AsyncIOMotorCollection:
    return get_db()["messages"]


async def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None