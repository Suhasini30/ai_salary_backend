import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)


def get_chat_service():
    """
    Lazily create the ChatService singleton on first request.

    ChatService (and the heavy modules it pulls in — litellm, langchain-core,
    motor) are only imported after the app is already serving, so the port
    binds immediately at boot. This is important on platforms like Render
    that health-check the port right after startup.
    """
    from app.services.chat_service import ChatService
    if get_chat_service._instance is None:
        get_chat_service._instance = ChatService()
    return get_chat_service._instance


get_chat_service._instance = None


router = APIRouter()


class ChatRequest(BaseModel):
    question: str
    model_type: str = "fast"


@router.post("/chat")
async def chat(request: ChatRequest):

    response = get_chat_service().chat(
        request.question,
        request.model_type
    )

    return StreamingResponse(
        response,
        media_type="text/event-stream"
    )