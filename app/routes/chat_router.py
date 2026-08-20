"""
Chat / conversation routes.

  POST /api/chat                    → streaming RAG answer (SSE)
  POST /api/chat/regenerate         → re-answer the last user message
  GET  /api/conversations           → list the user's conversations
  GET  /api/conversations/{id}      → one conversation incl. messages
  DELETE /api/conversations/{id}    → delete a conversation + messages
"""
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth.dependencies import CurrentUser
from app.models.schemas import (
    ChatRequest,
    ConversationDetail,
    ConversationCreate,
    ConversationPublic,
    PublicUser,
)
from app.repos import chats_repo, messages_repo
from app.services.chat_service import ChatService, sse_format

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


def get_chat_service() -> ChatService:
    if get_chat_service._instance is None:
        get_chat_service._instance = ChatService()
    return get_chat_service._instance


get_chat_service._instance = None


class RegenerateRequest(BaseModel):
    conversation_id: str


@router.post("/chat")
async def chat_stream(request: ChatRequest, user: PublicUser = CurrentUser):
    service = get_chat_service()

    async def event_generator():
        async for event in service.stream_answer(
            user=user,
            message=request.message,
            conversation_id=request.conversation_id,
            regenerate=False,
        ):
            yield sse_format(event)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/regenerate")
async def chat_regenerate(body: RegenerateRequest, user: PublicUser = CurrentUser):
    service = get_chat_service()

    conv = await chats_repo.get_for_user(user.id, body.conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    async def event_generator():
        async for event in service.stream_answer(
            user=user,
            message="",
            conversation_id=body.conversation_id,
            regenerate=True,
        ):
            yield sse_format(event)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations", response_model=list[ConversationPublic])
async def list_conversations(user: PublicUser = CurrentUser):
    return await chats_repo.list_for_user(user.id)


@router.post("/conversations", response_model=ConversationPublic)
async def create_conversation(body: ConversationCreate, user: PublicUser = CurrentUser):
    return await chats_repo.create(user.id, body.title, body.title or "New conversation")


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str, user: PublicUser = CurrentUser):
    conv = await chats_repo.get_for_user(user.id, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    messages = await messages_repo.list_for_conversation(user.id, conversation_id)
    conv_public = ConversationPublic(
        id=str(conv["_id"]),
        title=conv.get("title") or "Untitled conversation",
        created_at=conv.get("created_at"),
        updated_at=conv.get("updated_at"),
        message_count=len(messages),
    )
    return ConversationDetail(**conv_public.model_dump(), messages=messages)


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, user: PublicUser = CurrentUser):
    removed = await chats_repo.delete_for_user(user.id, conversation_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"status": "deleted", "conversation_id": conversation_id}