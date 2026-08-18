import logging
from app.services.retry_chat import retry
from app.core.config import settings

logger = logging.getLogger(__name__)

def fallback(model_type: str, user: str):
    m = (model_type or "").lower()

    if m == "fast":
        primary = settings.GROQ_MODEL
        backups = [settings.XAI_MODEL, settings.GEMINI_MODEL]

    elif m in ("pro", "quality", "slow"):
        primary = settings.GEMINI_MODEL
        backups = [settings.XAI_MODEL, settings.GROQ_MODEL]

    elif m in ("xai", "grok"):
        primary = settings.XAI_MODEL
        backups = [settings.GROQ_MODEL, settings.GEMINI_MODEL]

    else:
        primary = settings.DEFAULT_MODEL
        backups = [settings.XAI_MODEL, settings.GROQ_MODEL, settings.GEMINI_MODEL]

    chain = [primary] + [b for b in backups if b and b != primary]
    last_err = None

    for idx, candidate in enumerate(chain):
        try:
            return retry(candidate, user)
        except Exception as e:
            last_err = e
            logger.warning(
                "Fallback model attempt %d (%s) failed: %s",
                idx + 1, candidate, e
            )

    raise last_err or RuntimeError("All fallback models failed.")