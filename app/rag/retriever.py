from app.rag.vector_store import VectorStore
from app.rag.embedder import Embedder


class Retriever:

    def __init__(self, vector_store: VectorStore, embedder: Embedder | None = None):
        self.vector_store = vector_store
        # Allow injecting a shared Embedder instance (recommended — avoids
        # creating a new one per request); falls back to a fresh one if not given.
        self.embedder = embedder or Embedder()

    async def retrieve(self, query: str, top_k: int = 5, filters: dict | None = None):
        """
        Embeds the query and fetches the top_k most relevant chunks.
        `filters` is optional metadata filtering, e.g.
        {"min_salary": {"$gte": 100000}}
        """
        query_embedding = await self.embedder.embed_query(query)

        results = await self.vector_store.search(
            query_vector=query_embedding,
            top_k=top_k,
            filters=filters,
        )

        return results
