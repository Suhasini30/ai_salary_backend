import logging
from app.rag.embedder import Embedder
from app.core.config import settings

logger = logging.getLogger(__name__)


class Retriever:
    """
    Retrieves relevant job dataset chunks from MongoDB Atlas Vector Search
    using Voyage AI 1024-dimensional embeddings.
    """

    def __init__(self, vector_store=None, embedder=None):
        self.vector_store = vector_store
        self.embedder = embedder or Embedder()
        self.top_k = settings.TOP_K

    async def retrieve(self, query: str, top_k: int = None) -> list[dict]:
        """
        Embeds the query and queries MongoDB Atlas Vector Search.
        Gracefully handles errors and returns normalized result list.
        """
        k = top_k or self.top_k

        if not self.vector_store:
            logger.warning("Retriever called but vector_store is not configured.")
            return []

        try:
            query_embedding = await self.embedder.embed_query(query)
            if not query_embedding:
                logger.warning("Empty query embedding; skipping MongoDB vector search.")
                return []

            results = await self.vector_store.search(
                query_vector=query_embedding,
                top_k=k,
                num_candidates=max(100, k * 10),
            )

            formatted_results = []
            for r in results:
                chunk_text = r.get("text") or r.get("chunk") or ""
                formatted_results.append({
                    "chunk": chunk_text,
                    "text": chunk_text,
                    "job_title": r.get("job_title", ""),
                    "min_salary": r.get("min_salary"),
                    "max_salary": r.get("max_salary"),
                    "avg_salary": r.get("avg_salary"),
                    "score": r.get("score", 0.0),
                })
            return formatted_results

        except Exception as e:
            logger.error("MongoDB Atlas vector retrieval failed: %s", e, exc_info=True)
            return []