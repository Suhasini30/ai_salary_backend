from app.services.retry_chat import retry
from app.core.config import settings

def fallback(model_type: str, user: str):

    if model_type.lower() == "fast":
        primary = settings.GEMINI_MODEL
        backup = settings.GROQ_MODEL

    elif model_type.lower() in ("pro", "slow"):
        primary = settings.GROQ_MODEL
        backup = settings.GEMINI_MODEL

    else:
        raise ValueError("Invalid model type. Use 'fast' or 'pro'.")

    try:
        return retry(primary, user)

    except Exception:
        print("Switching to fallback model...")
        return retry(backup, user)