import logging

from app.rag.data_processor import DataProcessor
from app.rag.embedder import Embedder
from app.rag.vector_store import VectorStore

logger = logging.getLogger(__name__)


async def sync_vector_store(
    csv_path: str,
    vector_store: VectorStore,
    embedder: Embedder,
) -> None:
    """
    Incremental sync: only embeds and stores chunks that don't already
    exist in the vector store (by deterministic _id). Safe to call on
    every server startup — a fully synced store does near-zero work.
    """
    processor = DataProcessor(csv_path)
    processor.load_data()
    processor.validate_data()
    all_chunks = processor.get_all_chunks()

    existing_ids = await vector_store.get_existing_ids()
    new_chunks = [c for c in all_chunks if c["_id"] not in existing_ids]

    logger.info(
        f"Sync check: {len(all_chunks)} total chunks, "
        f"{len(existing_ids)} already stored, {len(new_chunks)} new."
    )

    if not new_chunks:
        logger.info("Vector store already up to date. Nothing to embed.")
        return

    texts = [c["text"] for c in new_chunks]
    embeddings = await embedder.embed_texts(texts)  # <-- FIXED: was embed_chunks

    docs_to_write = []
    for chunk, vector in zip(new_chunks, embeddings):
        if vector is None:
            continue  # failed batch — will be retried on next sync
        docs_to_write.append({**chunk, "embedding": vector})

    written = await vector_store.upsert_many(docs_to_write)
    skipped = len(new_chunks) - len(docs_to_write)

    logger.info(f"Sync complete: {written} new chunks embedded and stored.")
    if skipped:
        logger.warning(
            f"{skipped} chunks failed to embed and were skipped — "
            "they will be retried automatically on the next sync/startup."
        )


async def run_query(
    user_query: str,
    vector_store: VectorStore,
    embedder: Embedder,
    top_k: int = 5,
    filters: dict | None = None,
) -> list[dict]:
    """
    Query-time RAG retrieval: embeds the user's question and fetches the
    top-K most relevant chunks, optionally pre-filtered on metadata
    (e.g. {"min_salary": {"$gte": 100000}}).
    """
    query_vector = await embedder.embed_query(user_query)
    results = await vector_store.search(
        query_vector=query_vector,
        top_k=top_k,
        filters=filters,
    )
    return results


if __name__ == "__main__":
    # Standalone runner: re-sync the vector store without booting the FastAPI app.
    # Useful for manual re-seeding, e.g. after a Gemini quota reset.
    #
    # Usage:
    #   python -m app.rag.rag_pipeline path/to/ai_job_dataset.csv
    #
    # Reads MONGO_URI / GEMINI_API_KEY etc. from app.core.config.settings
    # (same .env-backed settings used by the rest of the app), so there's
    # no need to export them manually in the shell first.

    import asyncio
    import sys

    from app.core.config import settings

    logging.basicConfig(level=logging.INFO)

    async def main():
        csv_path = sys.argv[1] if len(sys.argv) > 1 else "app/data/ai_job_dataset.csv"

        store = VectorStore(mongo_uri=settings.MONGO_URI, db_name=settings.DB_NAME)
        embedder = Embedder()

        await store.ensure_index()
        await sync_vector_store(csv_path, store, embedder)
        await store.close()

    asyncio.run(main())