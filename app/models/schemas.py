"""Pydantic schemas used across the API (request/response bodies)."""
from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# PostgreSQL-style snake_case → Mongo-flavoured aliases are handled at serialization;
# here we keep clean API-facing field names and let repos choose DB keys.


# ── Auth ────────────────────────────────────────────────────────────────────

class AuthVerifyRequest(BaseModel):
    """Body sent by the frontend right after a successful Clerk sign-in.

    `clerk_token` is verified against Clerk JWKS. `email` / `username` are
    sent by the frontend from Clerk's user object because the session token
    itself only carries `sub` (the Clerk user id), not the email.
    """

    clerk_token: str = Field(min_length=10)
    email: Optional[str] = None
    username: Optional[str] = None


class TokenPairResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: "PublicUser"


class UserPublic(BaseModel):
    id: str
    clerk_id: str
    email: Optional[str] = None
    username: Optional[str] = None
    is_verified: bool = False

    model_config = ConfigDict(from_attributes=True)


class PublicUser(BaseModel):
    id: str
    clerk_id: str
    email: Optional[str] = None
    username: Optional[str] = None
    is_verified: bool = False
    is_banned: bool = False


# ── Profile ─────────────────────────────────────────────────────────────────

class SkillsUpdate(BaseModel):
    skills: list[str] = []


class ProfileUpdate(BaseModel):
    username: Optional[str] = None
    bio: Optional[str] = None
    location: Optional[str] = None
    avatar_url: Optional[str] = None
    skills: Optional[list[str]] = None
    full_name: Optional[str] = None


class ProfilePublic(BaseModel):
    user_id: str
    username: Optional[str] = None
    full_name: Optional[str] = None
    bio: Optional[str] = None
    location: Optional[str] = None
    avatar_url: Optional[str] = None
    skills: list[str] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Account info surfaced on the profile page (joined from `users`).
    email: Optional[str] = None
    is_verified: bool = False
    joined_at: Optional[datetime] = None


# ── Documents ───────────────────────────────────────────────────────────────

class DocumentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class DocumentPublic(BaseModel):
    id: str
    filename: str
    file_size: int
    content_type: str
    status: str
    error: Optional[str] = None
    chunk_count: int = 0
    page_count: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentListResponse(BaseModel):
    documents: list[DocumentPublic]
    total: int


# ── Chat / Conversations ────────────────────────────────────────────────────

class ConversationCreate(BaseModel):
    title: Optional[str] = None


class ConversationPublic(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class ChatMessagePublic(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    sources: list[dict] = []
    created_at: datetime


class ConversationDetail(ConversationPublic):
    messages: list[ChatMessagePublic] = []


class ChatRequest(BaseModel):
    """Body for posting a new question to a conversation."""

    message: str = Field(min_length=1, max_length=8000)
    conversation_id: Optional[str] = None  # None → start a new conversation


class ChatEventType(str, Enum):
    """SSE event types emitted by the streaming chat endpoint."""

    START = "start"
    TOKEN = "token"
    SOURCES = "sources"
    META = "meta"
    DONE = "done"
    ERROR = "error"


# ── Dashboard ───────────────────────────────────────────────────────────────

class DashboardStats(BaseModel):
    total_documents: int
    total_chunks: int
    total_conversations: int
    total_messages: int
    profile_completion: int  # percent 0..100
    recent_documents: list[DocumentPublic] = []
    recent_conversations: list[ConversationPublic] = []


class HealthResponse(BaseModel):
    status: str = "healthy"


# Re-export alias used by auth routes.
VerifyResponse = TokenPairResponse