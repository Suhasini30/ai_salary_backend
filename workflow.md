# AI Salary Backend — Workflow

## Architecture Overview

```
ai_salary_backend/
├── app/
│   ├── main.py               # FastAPI app entry, CORS, router mounting, vector-index bootstrap
│   ├── auth/
│   │   ├── routes.py         # /auth/verify, /auth/refresh, /auth/logout
│   │   └── dependencies.py   # Bearer JWT dependency resolution
│   ├── core/
│   │   ├── config.py         # Environment variables, settings singleton
│   │   ├── database.py       # Async Motor MongoDB client
│   │   └── security.py       # JWT creation/verification
│   ├── models/
│   │   └── schemas.py        # Pydantic schemas
│   ├── orchestration/
│   │   └── orchestrator.py   # Route → retrieve → generate pipeline
│   ├── prompt/
│   │   ├── system_prompt.py  # Main LLM system prompt
│   │   ├── router_prompt.py  # Intent classification prompt
│   │   ├── rag_prompt.py     # RAG-grounded answer prompt
│   │   └── prompt_builder.py # Prompt assembly from RAG + tool results
│   ├── rag/
│   │   ├── data_processor.py # CSV → text chunks (used by ingest script)
│   │   ├── embedder.py       # Voyage AI embeddings (1024 dims)
│   │   └── vector_store.py   # MongoDB Atlas vector search + index bootstrap
│   ├── repos/
│   │   ├── users_repo.py     # User records
│   │   ├── profiles_repo.py  # Profile CRUD
│   │   ├── chats_repo.py     # Conversation records
│   │   ├── messages_repo.py  # Message records
│   │   ├── documents_repo.py # Document metadata (read-only now; no upload API)
│   │   └── chunks_repo.py    # Chunk metadata (read-only now; no upload API)
│   ├── routes/
│   │   ├── chat_router.py    # /chat (SSE streaming)
│   │   ├── profile_router.py # /profile CRUD + avatar
│   │   └── dashboard_router.py # /dashboard stats
│   ├── routers/
│   │   └── llm_router.py     # Intent classifier (RAG / TOOL / BOTH / GENERAL)
│   ├── services/
│   │   ├── llm.py            # Async LLM streaming with model fallback
│   │   ├── chat_service.py   # Coordinates chat requests
│   │   ├── retriever.py      # MongoDB Atlas vector search retrieval
│   │   ├── fallback.py       # Model fallback logic
│   │   ├── retry_chat.py     # Retry wrapper for LLM calls
│   │   ├── embedding.py      # Embedding service wrapper (Voyage)
│   │   ├── dashboard_service.py # Dashboard statistics
│   │   └── voice.py          # STT/TTS services
│   └── tools/
│       └── jsearch.py        # JSearch (RapidAPI) live job search
├── scripts/
│   └── ingest.py             # CLI data ingestion (CSV → chunks → embeddings → Atlas)
├── server.py                 # Uvicorn runner
├── requirements.txt
└── .env                      # Environment variables (not committed)
```

## Setup Instructions

### Backend

1. **Create virtual environment:**
   ```bash
   cd ai_salary_backend
   python -m venv venv
   venv\Scripts\activate  # Windows
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your actual API keys and secrets
   ```
   Required secrets: `CLERK_SECRET_KEY`, `JWT_SECRET_KEY`, `GROQ_API_KEY`, `MONGO_URI`, `VOYAGE_API_KEY`, `JSEARCH_API_KEY`.

4. **Seed the knowledge base (required before chat RAG works):**
   ```bash
   python scripts/ingest.py path/to/salary_data.csv
   ```

5. **Start the server:**
   ```bash
   python server.py
   ```
   Server runs at `http://127.0.0.1:8000`

## Data Ingestion Flow (CLI — no upload API)

```
1. python scripts/ingest.py <salary_data.csv>
         ↓
2. DataProcessor loads + validates the CSV (job_title, salary_usd,
   experience_level, years_experience, company_location, industry, required_skills)
         ↓
3. DataProcessor.get_all_chunks() groups rows by job_title and batches
   them into readable text chunks
         ↓
4. Embedder.embed_texts() → Voyage AI embeddings (1024 dims)
         ↓
5. VectorStore.upsert_many() → MongoDB Atlas vector_documents collection
         ↓
6. Atlas Vector Search index (vector_index) is bootstrapped at server startup
   and again by the script before upserting
```

Note: Document upload endpoints and the HTTP ingestion pipeline were removed.
Ingestion is a backend CLI operation only — users do not upload files through the app.

## Authentication Flow

```
1. User signs in via Clerk UI (frontend)
         ↓
2. Frontend gets a Clerk session token
         ↓
3. Frontend calls GET /auth/verify with Bearer <clerk_token>
         ↓
4. Backend verifies token via Clerk JWKS
         ↓
5. Backend mints access JWT (15 min) + refresh JWT (30 days)
         ↓
6. Refresh token → HttpOnly cookie
   Access token → returned in JSON, stored in memory by frontend
         ↓
7. Frontend sends Bearer <access_token> on all protected requests
         ↓
8. On 401, frontend calls POST /auth/refresh (cookie auto-sent)
         ↓
9. On sign-out, frontend calls POST /auth/logout + clears local state
```

## Chat Request Flow

```
1. User sends question via chat UI
         ↓
2. Frontend calls POST /chat { message, conversation_id } with Bearer token
         ↓
3. chat_router.py → ChatService → Orchestrator.answer()
         ↓
4. LLMRouter.classify() — determines intent (RAG/TOOL/BOTH/GENERAL)
         ↓
5. If RAG/BOTH: Retriever queries MongoDB Atlas Vector Search (per-user filtered)
   If TOOL/BOTH: JSearchTool queries RapidAPI for live jobs
         ↓
6. PromptBuilder assembles prompt with RAG context + tool results
         ↓
7. LLMService.chat() streams response via litellm acompletion
   (fallback chain: Groq → xAI Grok → Mistral → Groq default)
         ↓
8. StreamingResponse sends SSE events (meta / sources / token / error) to frontend
         ↓
9. Frontend renders tokens as they arrive; sources panel shows citations
```

## API Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/` | Health check greeting | No |
| GET | `/health` | Backend health status | No |
| GET | `/auth/verify` | Exchange Clerk token for backend JWT | Clerk token |
| POST | `/auth/refresh` | Refresh access token | Refresh cookie |
| POST | `/auth/logout` | Clear refresh cookie | No |
| GET | `/chat` | List conversations | Bearer JWT |
| POST | `/chat` | Send message, get streaming response | Bearer JWT |
| GET | `/chat/{id}` | Get a conversation's messages | Bearer JWT |
| POST | `/chat/{id}/regenerate` | Regenerate the last assistant reply | Bearer JWT |
| DELETE | `/chat/{id}` | Delete a conversation | Bearer JWT |
| GET | `/profile` | Get own profile | Bearer JWT |
| PATCH | `/profile` | Update own profile | Bearer JWT |
| POST | `/profile/avatar` | Upload avatar | Bearer JWT |
| GET | `/dashboard` | Dashboard statistics | Bearer JWT |

## Environment Variables (backend .env)

| Variable | Required | Description |
|----------|----------|-------------|
| `CLERK_SECRET_KEY` | Yes | Clerk backend secret |
| `CLERK_JWKS_URL` | No | Derived from issuer if omitted |
| `JWT_SECRET_KEY` | Yes | Access token signing secret |
| `JWT_ALGORITHM` | No | Default HS256 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | Default 15 |
| `REFRESH_TOKEN_EXPIRE_DAYS` | No | Default 30 |
| `COOKIE_NAME` | No | Default rag_refresh_token |
| `COOKIE_SAMESITE` | No | Default lax |
| `COOKIE_SECURE` | No | Default false (dev) |
| `MONGO_URI` | Yes | MongoDB Atlas connection string |
| `MONGODB_DATABASE` | No | Default rag_db |
| `MONGODB_COLLECTION` | No | Default vector_documents |
| `MONGODB_VECTOR_INDEX` | No | Default vector_index |
| `VECTOR_DIMENSIONS` | No | Default 1024 |
| `VOYAGE_API_KEY` | Yes | Voyage AI embedding API key |
| `VOYAGE_MODEL` | No | Default voyage/voyage-4-large |
| `GROQ_API_KEY` | Yes | Groq API key for LLM |
| `MISTRAL_API_KEY` | No | Mistral API key |
| `GEMINI_API_KEY` | No | Google Gemini API key |
| `XAI_API_KEY` | No | xAI/Grok API key |
| `DEFAULT_MODEL` | No | Primary LLM model |
| `JSEARCH_API_KEY` | Yes | RapidAPI JSearch key |
| `RAPIDAPI_HOST` | No | Default jsearch.p.rapidapi.com |
| `JSEARCH_BASE_URL` | No | Default https://jsearch.p.rapidapi.com |
| `FRONTEND_ORIGINS` | No | Comma-separated CORS origins |
| `API_BASE_URL` | No | Default http://127.0.0.1:8000 |

## Key Design Decisions

- **Async throughout**: All backend I/O (LLM calls, HTTP requests, DB queries) uses async/await to avoid blocking the FastAPI event loop.
- **Model fallback chain**: If the primary LLM fails, requests cascade through Groq → xAI Grok → Mistral.
- **Intent routing**: A lightweight LLM classifier routes queries to RAG (internal dataset), TOOL (live job search), BOTH, or GENERAL (chitchat).
- **Per-user isolation**: Vector search filters by `user_id`; users can never see another user's data.
- **Backend JWT tokens**: The backend issues its own short-lived access tokens rather than trusting Clerk tokens directly on protected routes.
- **CLI ingestion only**: The knowledge base is seeded via `scripts/ingest.py` — there is no user-facing document upload path.