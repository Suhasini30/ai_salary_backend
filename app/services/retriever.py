"""
Hybrid retriever.

Embeds the query and searches MongoDB Atlas Vector Search, always scoped to:
  * the authenticated user's own uploaded chunks (`doc_type: "user_document"`),
  * plus the shared knowledge base (`doc_type: "shared"`) — the pre-loaded
    salary/job dataset that every user can ask about.

A user's private chunks are still isolated: they can only ever match their own
`user_id` space.
"""
import logging

from bson import ObjectId

from app.core.config import settings
from app.rag.embedder import Embedder

logger = logging.getLogger(__name__)


class Retriever:
    def __init__(self, vector_store=None, embedder=None):
        self.vector_store = vector_store
        self.embedder = embedder or Embedder()
        self.top_k = settings.TOP_K

    async def retrieve_for_user(
        self,
        query: str,
        user_id: str,
        top_k: int | None = None,
        document_id: str | None = None,
    ) -> list[dict]:
        """
        Retrieves the top-k nearest chunks visible to `user_id`: their own
        uploaded documents plus the shared knowledge base.
        Optionally narrowed to a single uploaded document via `document_id`.

        Returns normalized records:
          {chunk, filename, page, document_id, chunk_index, score}
        """
        k = top_k or self.top_k

        if not self.vector_store:
            logger.warning("Retriever called but vector_store is not configured.")
            return []

        # Isolation is enforced in the database query itself. The shared
        # knowledge base has `doc_type: "shared"` and no owner, so it is
        # included for every user without leaking per-user private chunks.
        user_branch: dict = {"user_id": ObjectId(user_id), "doc_type": "user_document"}
        if document_id:
            try:
                user_branch["document_id"] = ObjectId(document_id)
            except Exception:
                logger.warning("Invalid document_id filter: %s", document_id)
        filters: dict = {
            "$or": [
                user_branch,
                {"doc_type": "shared"},
            ]
        }

        try:
            query_embedding = await self.embedder.embed_query(query)
            
            if hasattr(self.vector_store, "hybrid_search"):
                results = await self.vector_store.hybrid_search(
                    query_text=query,
                    query_vector=query_embedding,
                    top_k=k,
                    num_candidates=max(100, k * 20),
                    filters=filters,
                )
            else:
                if not query_embedding:
                    logger.warning("Empty query embedding; skipping vector search.")
                    return []
                results = await self.vector_store.search(
                    query_vector=query_embedding,
                    top_k=k,
                    num_candidates=max(100, k * 20),
                    filters=filters,
                )

            formatted = []
            for r in results:
                chunk_text = r.get("text") or r.get("chunk") or ""
                filename = r.get("filename")
                if r.get("doc_type") == "shared" and r.get("job_title"):
                    filename = r["job_title"]
                formatted.append(
                    {
                        "chunk": chunk_text,
                        "filename": filename or "unknown",
                        "page": r.get("page_number"),
                        "document_id": r.get("document_id"),
                        "chunk_index": r.get("chunk_index"),
                        "score": r.get("score", 0.0),
                    }
                )
            return formatted

        except Exception as exc:
            logger.error("Atlas vector retrieval failed for user %s: %s", user_id, exc, exc_info=True)
            return []