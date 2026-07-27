import os
import sys
import logging

# Bootstrapping path for direct script execution
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.rag.retriever import Retriever
from app.rag.prompt_builder import PromptBuilder
from app.rag.vector_store import VectorStore
from app.rag.embedder import Embedder
from app.rag.rag_pipeline import sync_vector_store
from app.services.llm import LLMService
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ChatService:

    def __init__(self):
        self.vector_store = VectorStore(mongo_uri=settings.MONGO_URI, dimensions=1024)
        self.embedder = Embedder()
        self.retriever = Retriever(self.vector_store, self.embedder)
        self.prompt_builder = PromptBuilder()
        self.llm_service = LLMService()

        # Same model_type vocabulary as fallback.py: "fast" or "pro"/"slow"
        self.model_map = {
            "fast": settings.GEMINI_MODEL,
            "pro": settings.GROQ_MODEL,
        }

    async def initialize(self):
        """
        Runs on startup. Ensures the vector index exists, then does an
        incremental sync: only embeds chunks that are new or changed
        (by deterministic _id), regardless of whether the store was
        empty or already populated. Safe to call on every restart.
        """
        logger.info("Ensuring MongoDB Vector Search index exists...")
        await self.vector_store.ensure_index()

        dataset_path = os.path.join("app", "data", "ai_job_dataset_100.csv")
        logger.info(f"Syncing vector store against dataset: {dataset_path}")

        try:
            await sync_vector_store(
                csv_path=dataset_path,
                vector_store=self.vector_store,
                embedder=self.embedder,
            )
        except Exception as e:
            logger.error(f"Vector store sync encountered an error during startup: {e}")
            logger.warning("Continuing app startup with existing vector store data.")

        total = await self.vector_store.count_documents()
        logger.info(f"Vector store ready. Total documents: {total}")

    async def close(self):
        """
        Called on app shutdown (see main.py's lifespan). Closes the
        MongoDB connection owned by this service's VectorStore.
        """
        logger.info("Closing ChatService's MongoDB connection...")
        await self.vector_store.close()

    async def chat(self, question, model_type="pro"):
        """
        Streaming endpoint. Streams directly from the primary model for
        model_type.
        """
        results = await self.retriever.retrieve(question)

        prompt = self.prompt_builder.build_prompt(
            question,
            results
        )

        model = self.model_map.get(model_type, settings.DEFAULT_MODEL)

        return self.llm_service.chat(prompt, model)


if __name__ == "__main__":
    import asyncio
    from app.db.mongo_db import connect_to_mongo, close_mongo_connection

    async def main():
        logging.basicConfig(level=logging.INFO)
        await connect_to_mongo()
        chat_service = ChatService()
        await chat_service.initialize()
        await chat_service.close()
        await close_mongo_connection()

    asyncio.run(main())