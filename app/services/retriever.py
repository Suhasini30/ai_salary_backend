from app.rag.vector_store import VectorStore
from app.rag.embedder import Embedder


class Retriever:

    def __init__(self, vector_store):
        self.vector_store = vector_store
        self.embedder = Embedder()


    def retrieve(self, query, top_k=5):

        query_embedding = self.embedder.embed_query(query)

        results = self.vector_store.search(
            query_embedding,
            top_k
        )

        return results