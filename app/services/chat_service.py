import logging

from app.core.config import settings
from app.orchestration.orchestrator import SalesOrchestrator
from app.rag.vector_store import VectorStore
from app.services.retriever import Retriever

logger = logging.getLogger(__name__)


class ChatService:
    """
    Coordinates chat requests: initializes MongoDB Atlas vector store,
    retriever, and orchestrator, and streams responses.

    IMPORTANT: instantiate this ONCE, after the app's event loop is running
    (e.g. in a FastAPI startup event or as a module-level singleton created
    after app import), not per-request and not at cold import time.
    """

    def __init__(self):
        logger.info("Initializing MongoDB Atlas VectorStore...")
        logger.info(
            "VectorStore config — db: %s | collection: %s | index: %s | dimensions: %d",
            settings.MONGODB_DATABASE,
            settings.MONGODB_COLLECTION,
            settings.MONGODB_VECTOR_INDEX,
            settings.VECTOR_DIMENSIONS,
        )
        try:
            vector_store = VectorStore(
                mongo_uri=settings.MONGO_URI,
                db_name=settings.MONGODB_DATABASE,   # single source of truth
                collection_name=settings.MONGODB_COLLECTION,
                index_name=settings.MONGODB_VECTOR_INDEX,
                dimensions=settings.VECTOR_DIMENSIONS,
            )
            self.retriever = Retriever(vector_store)
            logger.info("MongoDB Atlas VectorStore and Retriever ready.")
        except Exception as e:
            logger.error("Failed to initialize MongoDB Atlas VectorStore: %s", e, exc_info=True)
            self.retriever = Retriever(None)

        self.orchestrator = SalesOrchestrator(retriever=self.retriever)

        # Maps request-facing model_type -> actual model string from .env
        self.model_map = {
            "fast": settings.GROQ_MODEL,
            "quality": settings.GEMINI_MODEL,
            "xai": settings.XAI_MODEL,
            "grok": settings.XAI_MODEL,
            "mistral": settings.MISTRAL_MODEL,
        }

    async def chat(self, question: str, model_type: str = "fast"):
        """
        Async generator — streams response chunks. Call with `async for`
        from an async FastAPI route, e.g.:

            async for chunk in chat_service.chat(question, model_type):
                ...
        """
        model = self.model_map.get(model_type, settings.DEFAULT_MODEL)
        async for chunk in self.orchestrator.answer(question, model):
            yield chunk