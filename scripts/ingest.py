"""
Data ingestion CLI script.

Usage:
    cd ai_salary_backend
    python scripts/ingest.py path/to/salary_data.csv

Loads a CSV with salary/job data, chunks it via the RAG pipeline,
embeds with Voyage AI, and upserts into MongoDB Atlas.
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.rag.data_processor import DataProcessor
from app.rag.embedder import Embedder
from app.rag.vector_store import VectorStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ingest")


async def ingest(csv_path: str) -> None:
    # ── 1. Load & validate CSV ────────────────────────────────────────────
    processor = DataProcessor(csv_path)
    processor.load_data()
    processor.validate_data()
    logger.info("Loaded %d rows from %s", len(processor.df), csv_path)

    # ── 2. Build text chunks (grouped by job_title) ──────────────────────
    row_chunks = processor.get_all_chunks()
    if not row_chunks:
        logger.error("No chunks produced from the CSV.")
        return
    logger.info("Produced %d text chunks.", len(row_chunks))

    # ── 3. Embed chunks ──────────────────────────────────────────────────
    embedder = Embedder()
    embeddings = await embedder.embed_texts(row_chunks, batch_size=20)
    if len(embeddings) != len(row_chunks):
        logger.error("Embedding count mismatch (%d vs %d). Aborting.", len(embeddings), len(row_chunks))
        return
    logger.info("Embedded %d chunks.", len(embeddings))

    # ── 4. Build documents for MongoDB ───────────────────────────────────
    # doc_type must be "shared" so the retriever's shared-knowledge-base
    # branch ({doc_type: "shared"}) matches these chunks. The old "dataset"
    # label was invisible to retrieval and made ingested data unqueryable.
    docs = []
    for i, (text, vec) in enumerate(zip(row_chunks, embeddings)):
        docs.append({
            "_id": f"dataset_{i}",
            "text": text,
            "embedding": vec,
            "doc_type": "shared",
            "filename": Path(csv_path).name,
            "chunk_index": i,
            "page": 0,
            "source": "dataset",
        })

    # ── 5. Upsert into MongoDB Atlas ─────────────────────────────────────
    store = VectorStore(
        mongo_uri=settings.MONGO_URI,
        db_name=settings.MONGODB_DATABASE,
        collection_name=settings.MONGODB_COLLECTION,
        index_name=settings.MONGODB_VECTOR_INDEX,
        dimensions=settings.VECTOR_DIMENSIONS,
    )
    try:
        count = await store.upsert_many(docs)
        logger.info("Done — %d documents upserted into '%s'.", count, settings.MONGODB_COLLECTION)
    finally:
        await store.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/ingest.py <csv_file>")
        sys.exit(1)
    asyncio.run(ingest(sys.argv[1]))
