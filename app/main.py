import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.routes import router as auth_router
from app.core.config import settings
from app.core.database import close_client
from app.routes.chat_router import router as chat_router
from app.routes.dashboard_router import router as dashboard_router
from app.routes.profile_router import router as profile_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rag-app")


async def ensure_vector_index() -> None:
    """Ensures the Atlas vector index includes the per-user filter fields."""
    try:
        from app.rag.vector_store import VectorStore

        vs = VectorStore(
            mongo_uri=settings.MONGO_URI,
            db_name=settings.MONGODB_DATABASE,
            collection_name=settings.MONGODB_COLLECTION,
            index_name=settings.MONGODB_VECTOR_INDEX,
            dimensions=settings.VECTOR_DIMENSIONS,
        )
        await vs.ensure_index()
        await vs.close()
        logger.info("Vector index '%s' ready.", settings.MONGODB_VECTOR_INDEX)
    except Exception as exc:
        logger.error("Could not ensure vector index: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("BOOT: starting RAG application")
    try:
        import asyncio
        await asyncio.wait_for(ensure_vector_index(), timeout=10.0)
    except Exception as exc:
        logger.warning("Vector index setup timed out or deferred: %s", exc)

    # Initialize remote MCP client connections
    try:
        from app.mcp import connect as mcp_connect, disconnect as mcp_disconnect
        await mcp_connect()
    except Exception as exc:
        logger.warning("MCP initialization error: %s", exc)

    yield

    try:
        from app.mcp import disconnect as mcp_disconnect
        await mcp_disconnect()
    except Exception as exc:
        logger.warning("MCP shutdown error: %s", exc)

    await close_client()
    logger.info("SHUTDOWN: RAG application stopped")


app = FastAPI(
    title="RAG Knowledge Assistant API",
    version="1.0.0",
    description="User-scoped RAG over uploaded documents with Clerk auth.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.FRONTEND_ORIGINS,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(profile_router)
app.include_router(dashboard_router)


@app.get("/")
def home():
    return {"message": "RAG Knowledge Assistant API is running"}


@app.get("/health")
def health():
    return {"status": "healthy"}