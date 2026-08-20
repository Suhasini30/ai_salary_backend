"""
Dashboard service — aggregates per-user stats for the dashboard page.
Everything is scoped to the authenticated user.
"""
import logging

from app.models.schemas import DashboardStats
from app.repos import chats_repo, chunks_repo, documents_repo, messages_repo, profiles_repo

logger = logging.getLogger(__name__)


async def get_stats(user) -> DashboardStats:
    user_id = user["id"] if isinstance(user, dict) else user.id

    total_documents = await documents_repo.count_for_user(user_id)
    total_chunks = await chunks_repo.count_for_user(user_id)
    total_conversations = await chats_repo.count_for_user(user_id)
    total_messages = await messages_repo.count_for_user(user_id)
    completion = await profiles_repo.completion_percent(user_id)

    recent_documents = await documents_repo.list_documents(user_id, limit=5)
    recent_conversations = await chats_repo.list_for_user(user_id, limit=5)

    return DashboardStats(
        total_documents=total_documents,
        total_chunks=total_chunks,
        total_conversations=total_conversations,
        total_messages=total_messages,
        profile_completion=completion,
        recent_documents=recent_documents,
        recent_conversations=recent_conversations,
    )