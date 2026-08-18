import logging
from datetime import datetime, timezone

import certifi
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)


class VectorStore:
    """
    Handles all MongoDB Atlas interactions for the RAG pipeline:
    - connection management
    - existing-ID lookups (for incremental sync/diffing)
    - upserts (insert new / update changed documents)
    - Atlas Vector Search index creation
    - vector similarity search with optional metadata filters
    """

    def __init__(
        self,
        mongo_uri: str,
        db_name: str = "rag_db",
        collection_name: str = "vector_documents",
        index_name: str = "vector_index",
        dimensions: int = 1024,
    ):
        self.client = AsyncIOMotorClient(
            mongo_uri,
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=10000,
            connectTimeoutMS=10000,
        )
        self.db_name = db_name
        self.collection_name = collection_name
        self.db = self.client[db_name]
        self.collection = self.db[collection_name]
        self.index_name = index_name
        self.dimensions = dimensions
        logger.info(
            "VectorStore connected — db: %s | collection: %s | index: %s | dimensions: %d",
            db_name,
            collection_name,
            index_name,
            dimensions,
        )

    async def close(self):
        self.client.close()

    # ------------------------------------------------------------------
    # Index setup
    # ------------------------------------------------------------------

    async def ensure_index(self):
        """
        Creates the Atlas Vector Search index if it doesn't exist, or
        recreates it if the existing index has a mismatched dimension size.
        """
        existing_indexes = await self.collection.list_search_indexes().to_list(length=None)
        existing = next(
            (idx for idx in existing_indexes if idx.get("name") == self.index_name),
            None,
        )

        if existing:
            existing_dims = (
                existing.get("latestDefinition", {})
                .get("fields", [{}])[0]
                .get("numDimensions")
            )
            if existing_dims == self.dimensions:
                logger.info(f"Vector index '{self.index_name}' already exists with matching dimensions.")
                return
            logger.warning(
                f"Vector index '{self.index_name}' has {existing_dims} dims, "
                f"expected {self.dimensions}. Dropping and recreating."
            )
            await self.collection.drop_search_index(self.index_name)

        index_model = {
            "name": self.index_name,
            "type": "vectorSearch",
            "definition": {
                "fields": [
                    {
                        "type": "vector",
                        "path": "embedding",
                        "numDimensions": self.dimensions,
                        "similarity": "cosine",
                    },
                    {"type": "filter", "path": "job_title"},
                    {"type": "filter", "path": "min_salary"},
                    {"type": "filter", "path": "max_salary"},
                    {"type": "filter", "path": "avg_salary"},
                ]
            },
        }

        await self.db.command({
            "createSearchIndexes": self.collection.name,
            "indexes": [index_model],
        })
        logger.info(f"Created vector index '{self.index_name}' with {self.dimensions} dimensions.")

    # ------------------------------------------------------------------
    # Sync / diff support
    # ------------------------------------------------------------------

    async def get_existing_ids(self) -> set[str]:
        """Returns the set of all _id values currently stored."""
        cursor = self.collection.find({}, {"_id": 1})
        return {doc["_id"] async for doc in cursor}

    async def count_documents(self) -> int:
        return await self.collection.count_documents({})

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def upsert_many(self, docs: list[dict]) -> int:
        """
        Inserts new documents or updates existing ones by _id.
        Skips any doc missing an 'embedding' (e.g. failed embedding batch)
        so it gets retried on the next sync instead of being stored broken.
        """
        now = datetime.now(timezone.utc)
        written = 0

        for doc in docs:
            if not doc.get("embedding"):
                logger.warning(f"Skipping doc {doc.get('_id')} — no embedding present.")
                continue

            doc_id = doc["_id"]
            body = {k: v for k, v in doc.items() if k != "_id"}
            body["updated_at"] = now

            await self.collection.update_one(
                {"_id": doc_id},
                {"$set": body},
                upsert=True,
            )
            written += 1

        logger.info(f"Upserted {written} documents into '{self.collection.name}'.")
        return written

    # ------------------------------------------------------------------
    # Reads / search
    # ------------------------------------------------------------------

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        num_candidates: int = 100,
        filters: dict | None = None,
    ) -> list[dict]:
        """
        Runs Atlas Vector Search for the nearest chunks to query_vector.
        `filters` is an optional MongoDB match dict applied as a
        pre-filter within $vectorSearch (e.g. {"min_salary": {"$gte": 100000}}).
        """
        vector_search_stage = {
            "index": self.index_name,
            "path": "embedding",
            "queryVector": query_vector,
            "numCandidates": num_candidates,
            "limit": top_k,
        }
        if filters:
            vector_search_stage["filter"] = filters

        pipeline = [
            {"$vectorSearch": vector_search_stage},
            {
                "$project": {
                    "text": 1,
                    "job_title": 1,
                    "batch_number": 1,
                    "min_salary": 1,
                    "max_salary": 1,
                    "avg_salary": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]

        cursor = self.collection.aggregate(pipeline)
        return await cursor.to_list(length=top_k)