"""
ingest.py — One-shot ingestion pipeline
=======================================
Reads app/data/ai_job_dataset.csv, converts every job-title group into
text chunks, embeds them with Voyage AI, and upserts them into MongoDB
Atlas so the RAG pipeline has data to retrieve.

Run once (or whenever the dataset changes):

    python ingest.py

Environment requirements (.env must be present with):
    MONGO_URI, MONGODB_DATABASE, MONGODB_COLLECTION,
    MONGODB_VECTOR_INDEX, VOYAGE_API_KEY, VOYAGE_MODEL,
    VECTOR_DIMENSIONS
"""

import asyncio
import hashlib
import logging
import os
import sys
import time

# ── Make sure project root is on sys.path ──────────────────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))

from app.core.config import settings
from app.rag.data_processor import DataProcessor
from app.rag.embedder import Embedder
from app.rag.vector_store import VectorStore

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,`8`
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ingest")

# ── Config ──────────────────────────────────────────────────────────────────
CSV_PATH = os.path.join(ROOT, "app", "data", "ai_job_dataset.csv")
EMBED_BATCH = 10      # chunks per Voyage call (kept low for free-tier 10K TPM)
DRY_RUN = False       # set True to test without writing to MongoDB


async def main():
    logger.info("=" * 60)
    logger.info("INGESTION PIPELINE STARTING")
    logger.info("  DB         : %s", settings.MONGODB_DATABASE)
    logger.info("  Collection : %s", settings.MONGODB_COLLECTION)
    logger.info("  Index      : %s", settings.MONGODB_VECTOR_INDEX)
    logger.info("  Model      : %s", settings.VOYAGE_MODEL)
    logger.info("  Dimensions : %d", settings.VECTOR_DIMENSIONS)
    logger.info("  CSV        : %s", CSV_PATH)
    logger.info("=" * 60)

    # 1. Validate config ────────────────────────────────────────────────────
    missing = []
    if not settings.MONGO_URI:
        missing.append("MONGO_URI")
    if not settings.VOYAGE_API_KEY:
        missing.append("VOYAGE_API_KEY")
    if missing:
        logger.error("Missing required env vars: %s", ", ".join(missing))
        sys.exit(1)

    # 2. Load & process CSV ─────────────────────────────────────────────────
    logger.info("Loading dataset from CSV ...")
    processor = DataProcessor(CSV_PATH)
    processor.load_data()
    processor.validate_data()
    chunks = processor.get_all_chunks()   # list[str]
    logger.info("Built %d text chunks from CSV", len(chunks))

    if len(chunks) == 0:
        logger.error("No chunks generated — check DataProcessor or CSV path.")
        sys.exit(1)

    # 3. Connect to MongoDB & check existing docs ───────────────────────────
    store = VectorStore(
        mongo_uri=settings.MONGO_URI,
        db_name=settings.MONGODB_DATABASE,
        collection_name=settings.MONGODB_COLLECTION,
        index_name=settings.MONGODB_VECTOR_INDEX,
        dimensions=settings.VECTOR_DIMENSIONS,
    )

    existing_count = await store.count_documents()
    logger.info("MongoDB currently has %d documents in '%s'", existing_count, settings.MONGODB_COLLECTION)

    existing_ids = await store.get_existing_ids()
    logger.info("Found %d existing document IDs (will skip unchanged)", len(existing_ids))

    # 4. Build document dicts with deterministic _id ────────────────────────
    #    _id = sha256 of the chunk text so the same chunk is never duplicated.
    new_docs = []
    for chunk_text in chunks:
        doc_id = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()[:32]
        if doc_id not in existing_ids:
            new_docs.append({
                "_id": doc_id,
                "text": chunk_text,
                "job_title": _extract_field(chunk_text, "Job Role:"),
                "batch_number": _extract_field(chunk_text, "Batch Number:"),
                "min_salary": None,
                "max_salary": None,
                "avg_salary": None,
            })

    logger.info("%d chunks are new / changed and need embedding", len(new_docs))
    if len(new_docs) == 0:
        logger.info("Nothing to ingest — DB is already up to date.")
        await store.close()
        return

    if DRY_RUN:
        logger.info("[DRY RUN] Would embed and upsert %d docs. Exiting.", len(new_docs))
        await store.close()
        return

    # 5. Embed in batches ────────────────────────────────────────────────────
    embedder = Embedder()   # reads VOYAGE_MODEL + VECTOR_DIMENSIONS from settings
    texts_to_embed = [d["text"] for d in new_docs]

    logger.info("Embedding %d chunks with %s (this may take a while) ...", len(texts_to_embed), embedder.model_name)
    t0 = time.time()

    try:
        embeddings = await embedder.embed_texts(texts_to_embed, batch_size=EMBED_BATCH)
    except Exception as exc:
        logger.error("Embedding failed: %s", exc, exc_info=True)
        logger.error(
            "Check your VOYAGE_API_KEY and VOYAGE_MODEL in .env. "
            "Current key starts with: %s",
            (settings.VOYAGE_API_KEY or "")[:8] + "...",
        )
        await store.close()
        sys.exit(1)

    elapsed = time.time() - t0
    logger.info("Embedding done in %.1fs", elapsed)

    if len(embeddings) != len(new_docs):
        logger.error(
            "Mismatch: %d chunks but %d embeddings returned. Aborting.",
            len(new_docs), len(embeddings),
        )
        await store.close()
        sys.exit(1)

    # Attach embeddings ──────────────────────────────────────────────────────
    for doc, emb in zip(new_docs, embeddings):
        doc["embedding"] = emb

    # 6. Ensure vector index exists ──────────────────────────────────────────
    logger.info("Ensuring Atlas Vector Search index '%s' ...", settings.MONGODB_VECTOR_INDEX)
    try:
        await store.ensure_index()
    except Exception as exc:
        logger.warning(
            "ensure_index() raised: %s  "
            "(This is OK if you created the index manually in Atlas UI)", exc
        )

    # 7. Upsert into MongoDB ─────────────────────────────────────────────────
    logger.info("Upserting %d documents into MongoDB ...", len(new_docs))
    written = await store.upsert_many(new_docs)
    logger.info("Wrote %d documents.", written)

    # 8. Verify ──────────────────────────────────────────────────────────────
    final_count = await store.count_documents()
    logger.info("=" * 60)
    logger.info("INGESTION COMPLETE")
    logger.info("  Documents in DB : %d", final_count)
    logger.info("  Newly written   : %d", written)
    logger.info("=" * 60)

    await store.close()


def _extract_field(text: str, label: str) -> str | None:
    """Pull the value after 'Label: ' from the first line that matches."""
    for line in text.splitlines():
        if line.startswith(label):
            return line[len(label):].strip()
    return None


if __name__ == "__main__":
    asyncio.run(main())
