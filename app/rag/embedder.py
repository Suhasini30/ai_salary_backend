import asyncio
import logging
import random

import litellm
from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 8
MIN_BATCH_INTERVAL_SECS = 21  # free Voyage tier allows ~3 requests/min


def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("429", "rate limit", "too many request", "rpm", "tpm"))


async def _embed_with_retry(model, texts, api_key):
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return await litellm.aembedding(
                model=model,
                input=texts,
                api_key=api_key,
            )
        except Exception as e:
            last_error = e
            if not _is_rate_limit(e):
                raise
            wait = min(60.0, 2.0 ** attempt + random.uniform(0, 1))
            logger.info(
                "Voyage rate limit hit (attempt %d/%d); retrying in %.1fs ...",
                attempt + 1, MAX_RETRIES + 1, wait,
            )
            await asyncio.sleep(wait)
    raise last_error


class Embedder:
    """
    Turns text into vectors (lists of numbers) so we can compare how
    similar two pieces of text are by comparing their vectors.

    Uses Voyage AI embeddings (voyage/voyage-4-large by default, 1024 dims).
    Model and dimensions are read from settings to stay consistent with stored
    embeddings — changing them here without re-ingesting will break retrieval.
    """

    def __init__(
        self,
        model_name: str | None = None,
        dimensions: int | None = None,
    ):
        # Default to settings so query-time model always matches ingestion model
        self.model_name = model_name or settings.VOYAGE_MODEL
        self.dimensions = dimensions or settings.VECTOR_DIMENSIONS
        logger.info(
            "Embedder initialised: model=%s  dimensions=%d",
            self.model_name,
            self.dimensions,
        )

    async def embed_texts(self, texts: list[str], batch_size: int = 100) -> list[list[float]]:
        """Embeds many chunks at once — used during ingestion."""
        embeddings = []

        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            response = await _embed_with_retry(self.model_name, batch, settings.VOYAGE_API_KEY)
            embeddings.extend(item["embedding"] for item in response.data)
            if start + batch_size < len(texts):
                await asyncio.sleep(MIN_BATCH_INTERVAL_SECS)

        return embeddings

    async def embed_query(self, text: str) -> list[float]:
        """Embeds a single piece of text — used for a user's question."""
        response = await _embed_with_retry(self.model_name, [text], settings.VOYAGE_API_KEY)
        return response.data[0]["embedding"]