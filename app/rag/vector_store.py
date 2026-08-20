import asyncio
import logging
import re
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
        recreates it if the existing index has a mismatched dimension size
        or is missing the per-user filter fields.
        """
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
                    # Legacy job-dataset filters (kept for backwards compatibility).
                    {"type": "filter", "path": "job_title"},
                    {"type": "filter", "path": "min_salary"},
                    {"type": "filter", "path": "max_salary"},
                    {"type": "filter", "path": "avg_salary"},
                    # Per-user RAG isolation filters.
                    {"type": "filter", "path": "user_id"},
                    {"type": "filter", "path": "document_id"},
                    {"type": "filter", "path": "doc_type"},
                ]
            },
        }

        required_filter_paths = {"user_id", "document_id", "doc_type"}
        existing_indexes = await self.collection.list_search_indexes().to_list(length=None)
        existing = next(
            (idx for idx in existing_indexes if idx.get("name") == self.index_name),
            None,
        )

        if existing:
            definition = existing.get("latestDefinition") or existing.get("definition") or {}
            fields = definition.get("fields", [])
            existing_dims = fields[0].get("numDimensions") if fields else None
            existing_filter_paths = {
                f.get("path") for f in fields if f.get("type") == "filter"
            }

            dims_ok = existing_dims == self.dimensions
            filters_ok = required_filter_paths.issubset(existing_filter_paths)

            if dims_ok and filters_ok:
                logger.info(
                    "Vector index '%s' already exists with matching dimensions and user filters.",
                    self.index_name,
                )
                return

            logger.warning(
                "Vector index '%s' outdated (dims=%s expected=%s, filters=%s). Recreating.",
                self.index_name,
                existing_dims,
                self.dimensions,
                sorted(existing_filter_paths),
            )
            await self.collection.drop_search_index(self.index_name)

        await self.db.command({
            "createSearchIndexes": self.collection.name,
            "indexes": [index_model],
        })
        logger.info("Created vector index '%s' with %d dimensions and user filters.", self.index_name, self.dimensions)

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
        pre-filter within $vectorSearch (e.g. {"min_salary": {"$gte": 100000}}
        or {"user_id": ObjectId(...), "doc_type": "user_document"}).
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

        # Project all fields the retriever / frontend sources panel needs.
        project_fields = {
            "text": 1,
            "filename": 1,
            "document_id": 1,
            "page_number": 1,
            "chunk_index": 1,
            "user_id": 1,
            "doc_type": 1,
            "score": {"$meta": "vectorSearchScore"},
            # legacy job fields (kept for the old dataset)
            "job_title": 1,
            "min_salary": 1,
            "max_salary": 1,
            "avg_salary": 1,
        }

        pipeline = [
            {"$vectorSearch": vector_search_stage},
            {"$project": project_fields},
        ]

        cursor = self.collection.aggregate(pipeline)
        return await cursor.to_list(length=top_k)

    async def text_search(
        self,
        query_text: str,
        top_k: int = 5,
        filters: dict | None = None,
    ) -> list[dict]:
        """
        Runs text / keyword search on MongoDB collection.
        Matches keywords across text, job_title, and filename fields.
        `filters` is an optional MongoDB match dict (scoping by user_id/doc_type).
        """
        if not query_text or not query_text.strip():
            return []

        project_fields = {
            "text": 1,
            "filename": 1,
            "document_id": 1,
            "page_number": 1,
            "chunk_index": 1,
            "user_id": 1,
            "doc_type": 1,
            "job_title": 1,
            "min_salary": 1,
            "max_salary": 1,
            "avg_salary": 1,
        }

        match_criteria = {}
        if filters:
            match_criteria.update(filters)

        # Build regex matching pattern for text search
        words = [w.strip() for w in query_text.split() if len(w.strip()) > 2]
        if words:
            pattern = "|".join([r"\b" + re.escape(w) + r"\b" for w in words[:5]])
        else:
            pattern = re.escape(query_text)

        text_filter = {
            "$or": [
                {"text": {"$regex": pattern, "$options": "i"}},
                {"job_title": {"$regex": pattern, "$options": "i"}},
                {"filename": {"$regex": pattern, "$options": "i"}},
            ]
        }

        if "$or" in match_criteria:
            combined_match = {"$and": [match_criteria, text_filter]}
        else:
            combined_match = {**match_criteria, **text_filter}

        cursor = self.collection.find(combined_match, project_fields).limit(top_k)
        results = await cursor.to_list(length=top_k)

        for idx, doc in enumerate(results):
            doc["score"] = 1.0 / (idx + 1)
        return results

    async def hybrid_search(
        self,
        query_text: str,
        query_vector: list[float] | None = None,
        top_k: int = 5,
        num_candidates: int = 100,
        filters: dict | None = None,
        alpha: float = 0.5,
        rrf_k: int = 60,
    ) -> list[dict]:
        """
        Performs Hybrid Search using Reciprocal Rank Fusion (RRF) combining:
        1. Dense Vector Similarity Search ($vectorSearch)
        2. Keyword / Full-Text Search (Regex / Text Matching)

        RRF Score Formula:
          RRF_Score(doc) = alpha / (rrf_k + rank_vector) + (1 - alpha) / (rrf_k + rank_text)
        """
        candidate_k = max(top_k * 3, 20)

        # Execute vector search & text search in parallel
        async def _vec_task():
            if not query_vector:
                return []
            try:
                return await self.search(
                    query_vector=query_vector,
                    top_k=candidate_k,
                    num_candidates=num_candidates,
                    filters=filters,
                )
            except Exception as exc:
                logger.warning("Vector search branch in hybrid_search failed: %s", exc)
                return []

        async def _text_task():
            if not query_text:
                return []
            try:
                return await self.text_search(
                    query_text=query_text,
                    top_k=candidate_k,
                    filters=filters,
                )
            except Exception as exc:
                logger.warning("Text search branch in hybrid_search failed: %s", exc)
                return []

        vector_results, text_results = await asyncio.gather(_vec_task(), _text_task())

        if not vector_results and not text_results:
            return []

        if not text_results:
            return vector_results[:top_k]

        if not vector_results:
            return text_results[:top_k]

        # Reciprocal Rank Fusion (RRF)
        doc_map = {}
        rrf_scores = {}

        # 1. Rank vector results
        for rank, doc in enumerate(vector_results, start=1):
            doc_id = str(doc["_id"])
            doc_map[doc_id] = doc
            rrf_scores[doc_id] = alpha / (rrf_k + rank)

        # 2. Rank text results
        for rank, doc in enumerate(text_results, start=1):
            doc_id = str(doc["_id"])
            if doc_id not in doc_map:
                doc_map[doc_id] = doc

            text_score = (1.0 - alpha) / (rrf_k + rank)
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + text_score

        # 3. Sort by aggregated RRF score descending
        sorted_ids = sorted(rrf_scores.keys(), key=lambda d_id: rrf_scores[d_id], reverse=True)

        fused_results = []
        for doc_id in sorted_ids[:top_k]:
            doc = doc_map[doc_id]
            doc["score"] = rrf_scores[doc_id]
            fused_results.append(doc)

        logger.info(
            "Hybrid search fused %d vector & %d text candidates -> %d top results.",
            len(vector_results), len(text_results), len(fused_results)
        )
        return fused_results