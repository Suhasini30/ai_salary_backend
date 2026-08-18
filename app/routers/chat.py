import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)
router = APIRouter()

# Created once, after import — NOT inside the request handler.
# If you already do this elsewhere (e.g. in main.py's startup event
# or as a module global here), keep it there instead of duplicating it.
chat_service = ChatService()


class ChatRequest(BaseModel):
    question: str
    model_type: str = "fast"


@router.post("/chat")
async def chat_endpoint(payload: ChatRequest):
    return StreamingResponse(
        chat_service.chat(payload.question, payload.model_type),
        media_type="text/plain",
    )