"""
Chat service — the RAG conversation engine.

Per workflow.md, the flow is:
  chat_router → ChatService.stream_answer → SalesOrchestrator.answer

The orchestrator:
  * classifies intent (RAG / TOOL / BOTH / GENERAL),
  * retrieves RAG context (scoped to the user) and/or runs the JSearch tool,
  * streams a grounded LLM answer.

This service layer adds the persistence layer around that stream:
  * resolving/creating the conversation,
  * persisting the user question and the assistant answer,
  * emitting SSE events (meta → sources → token* → done) for the frontend,
  * regenerating the last answer (repeat prior prompt, drop old reply).
"""
import json
import logging

from app.core.config import settings
from app.models.schemas import ChatEventType
from app.orchestration.orchestrator import SalesOrchestrator
from app.rag.vector_store import VectorStore
from app.repos import chats_repo, messages_repo
from app.services.llm import LLMService
from app.services.retriever import Retriever

logger = logging.getLogger(__name__)


class ChatService:
    _instance: "ChatService | None" = None

    def __init__(self):
        # Heavy deps are constructed lazily here (first request), not at import.
        vector_store = VectorStore(
            mongo_uri=settings.MONGO_URI,
            db_name=settings.MONGODB_DATABASE,
            collection_name=settings.MONGODB_COLLECTION,
            index_name=settings.MONGODB_VECTOR_INDEX,
            dimensions=settings.VECTOR_DIMENSIONS,
        )
        retriever = Retriever(vector_store)
        self.orchestrator = SalesOrchestrator(retriever)

    # ------------------------------------------------------------------
    # Public streaming generator
    # ------------------------------------------------------------------

    async def stream_answer(
        self,
        user,
        message: str,
        conversation_id: str | None,
        regenerate: bool = False,
    ):
        """
        Async generator yielding SSE event dicts:
          {"event": ChatEventType.XXX, "data": ...}
        The route wraps these into text/event-stream lines.
        """
        try:
            # ── Resolve / create the conversation ────────────────────────────
            if conversation_id:
                conv = await chats_repo.get_for_user(user.id, conversation_id)
                if not conv:
                    yield self._event(ChatEventType.ERROR, {"detail": "Conversation not found."})
                    return
            else:
                conv = await chats_repo.create(user.id, None, message)
                conversation_id = str(conv.id)
                yield self._event(ChatEventType.META, {"conversation_id": conversation_id})
            conv_id = conversation_id

            # ── Persist the user's question (only for new turns) ────────────
            if regenerate:
                user_msg = await messages_repo.last_user_message(user.id, conv_id)
                prompt_text = user_msg.content if user_msg else message
                await messages_repo.delete_last_assistant(user.id, conv_id)
            else:
                prompt_text = message
                await messages_repo.insert(user.id, conv_id, "user", message)
                await chats_repo.touch(user.id, conv_id)

            # ── Stream the orchestrator (meta/sources/token/done) ───────────
            accumulated = []
            sources = []

            async for event in self.orchestrator.answer(prompt_text, user=user):
                kind = event["event"]
                data = event["data"]

                if kind == ChatEventType.META.value:
                    # Merge conversation_id so the frontend keeps the active id.
                    data = {**data, "conversation_id": conv_id}
                    yield self._event(ChatEventType.META, data)
                elif kind == ChatEventType.SOURCES.value:
                    sources = data.get("sources", [])
                    yield self._event(ChatEventType.SOURCES, data)
                elif kind == ChatEventType.TOKEN.value:
                    accumulated.append(data["content"])
                    yield self._event(ChatEventType.TOKEN, data)
                elif kind == ChatEventType.DONE.value:
                    answer = "".join(accumulated)
                    assistant_msg = await messages_repo.insert(
                        user.id, conv_id, "assistant", answer, sources=sources
                    )
                    await chats_repo.touch(user.id, conv_id)
                    yield self._event(
                        ChatEventType.DONE,
                        {"conversation_id": conv_id, "message_id": assistant_msg.id},
                    )

        except Exception as exc:
            logger.error("Chat streaming failed for user %s: %s", user.id, exc, exc_info=True)
            yield self._event(ChatEventType.ERROR, {"detail": "Something went wrong while generating."})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _event(event_type: ChatEventType, data: dict) -> dict:
        return {"event": event_type.value, "data": data}


def sse_format(event: dict) -> str:
    """Serializes an SSE event dict into the wire format."""
    return (
        f"event: {event['event']}\n"
        f"data: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
    )