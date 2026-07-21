from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.chat_service import ChatService


router = APIRouter()

chat_service = ChatService()


class ChatRequest(BaseModel):
    question: str
    model_type: str = "fast"


@router.post("/chat")
async def chat(request: ChatRequest):

    response = chat_service.chat(
        request.question,
        request.model_type
    )

    return StreamingResponse(
        response,
        media_type="text/event-stream"
    )