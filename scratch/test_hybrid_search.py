import asyncio
import logging
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings
from app.rag.vector_store import VectorStore
from app.services.retriever import Retriever

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_hybrid")


async def main():
    logger.info("Initializing VectorStore for Hybrid Search test...")
    vs = VectorStore(
        mongo_uri=settings.MONGO_URI,
        db_name=settings.MONGODB_DATABASE,
        collection_name=settings.MONGODB_COLLECTION,
        index_name=settings.MONGODB_VECTOR_INDEX,
        dimensions=settings.VECTOR_DIMENSIONS,
    )

    query = "Data Scientist salary experience"
    logger.info("Testing hybrid_search directly on VectorStore...")

    # Test text_search
    text_res = await vs.text_search(query_text=query, top_k=3)
    logger.info("Text search returned %d items.", len(text_res))
    for idx, doc in enumerate(text_res):
        logger.info("  [%d] Title/File: %s | Score: %.4f", idx + 1, doc.get("job_title") or doc.get("filename"), doc.get("score", 0))

    # Test hybrid search via Retriever
    retriever = Retriever(vector_store=vs)
    fake_user_id = "650000000000000000000001"
    
    logger.info("Testing retriever.retrieve_for_user with hybrid search...")
    retrieved = await retriever.retrieve_for_user(query=query, user_id=fake_user_id, top_k=5)

    logger.info("Retrieved %d hybrid results:", len(retrieved))
    for idx, item in enumerate(retrieved):
        logger.info("  [%d] %s | RRF Score: %.6f | Preview: %s...", idx + 1, item["filename"], item["score"], item["chunk"][:80])

    await vs.close()
    logger.info("Hybrid search test completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
