"""
Embedding service for document chunks.

Wraps the RAG `Embedder` (Voyage, 1024 dims — must match the existing Atlas
vector index). Used at ingestion time; the retriever uses `Embedder.embed_query`.
"""
import logging

from app.rag.embedder import Embedder

logger = logging.getLogger(__name__)


async def embed_chunks(chunks: list[dict]) -> None:
    """
    Embeds each chunk's text and attaches the vector to the chunk dict
    in-place under the `embedding` key.
    """
    if not chunks:
        return

    embedder = Embedder()
    texts = [c["text"] for c in chunks]
    vectors = await embedder.embed_texts(texts)

    if len(vectors) != len(chunks):
        logger.warning("Embedding count mismatch (%d vectors, %d chunks).", len(vectors), len(chunks))

    for chunk, vector in zip(chunks, vectors):
        chunk["embedding"] = vector
    logger.info("Embedded %d chunks.", len(chunks))