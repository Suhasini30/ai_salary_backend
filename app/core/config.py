from dotenv import load_dotenv
import os


load_dotenv()

def _clean_env(val: str | None) -> str | None:
    if not val:
        return None
    cleaned = val.strip('"\n\r ')
    return cleaned if cleaned else None


class Settings:
    def __init__(self):
        # API Keys
        self.GROQ_API_KEY = _clean_env(os.getenv("GROQ_API_KEY"))
        self.GEMINI_API_KEY = _clean_env(os.getenv("GEMINI_API_KEY"))
        self.XAI_API_KEY = _clean_env(os.getenv("XAI_API_KEY"))

        # Sync non-empty API keys to environment for LiteLLM
        if self.GROQ_API_KEY:
            os.environ["GROQ_API_KEY"] = self.GROQ_API_KEY
        elif "GROQ_API_KEY" in os.environ and not os.environ["GROQ_API_KEY"]:
            del os.environ["GROQ_API_KEY"]

        if self.GEMINI_API_KEY:
            os.environ["GEMINI_API_KEY"] = self.GEMINI_API_KEY
        elif "GEMINI_API_KEY" in os.environ and not os.environ["GEMINI_API_KEY"]:
            del os.environ["GEMINI_API_KEY"]

        if self.XAI_API_KEY:
            os.environ["XAI_API_KEY"] = self.XAI_API_KEY
        elif "XAI_API_KEY" in os.environ and not os.environ["XAI_API_KEY"]:
            del os.environ["XAI_API_KEY"]

        # Models
        self.GROQ_MODEL = _clean_env(os.getenv("GROQ_MODEL")) or "groq/openai/gpt-oss-120b"
        self.DEFAULT_MODEL = _clean_env(os.getenv("DEFAULT_MODEL")) or self.GROQ_MODEL
        self.XAI_MODEL = _clean_env(os.getenv("XAI_MODEL")) or "xai/grok-2-latest"
        self.GEMINI_MODEL = _clean_env(os.getenv("GEMINI_MODEL"))  # Optional, Vertex/Gemini disabled by default

        # LLM router
        self.ROUTER_MODEL = _clean_env(os.getenv("ROUTER_MODEL")) or "groq/openai/gpt-oss-20b"
        self.ROUTER_MIN_CONFIDENCE = float(os.getenv("ROUTER_MIN_CONFIDENCE", "0.4"))

        # Router fallback chain (Groq & xAI, Vertex AI disabled)
        raw_fallback = os.getenv("ROUTER_FALLBACK_MODELS")
        if raw_fallback:
            self.ROUTER_FALLBACK_MODELS = [m.strip() for m in raw_fallback.split(",") if m.strip()]
        else:
            # Default fallback order: Primary Router -> xAI Grok -> Groq Default
            candidates = [self.ROUTER_MODEL, self.XAI_MODEL, self.DEFAULT_MODEL, self.GROQ_MODEL]
            seen = set()
            self.ROUTER_FALLBACK_MODELS = []
            for c in candidates:
                if c and c not in seen:
                    seen.add(c)
                    self.ROUTER_FALLBACK_MODELS.append(c)

        # MongoDB Atlas
        self.MONGO_URI = os.getenv("MONGO_URI")
        # MONGODB_DATABASE is the single source of truth for the database name.
        # Do NOT add a separate DB_NAME env var; it drifts silently.
        self.MONGODB_DATABASE = os.getenv("MONGODB_DATABASE") or os.getenv("DB_NAME", "rag_db")
        self.MONGODB_COLLECTION = os.getenv("MONGODB_COLLECTION", "vector_documents")
        self.MONGODB_VECTOR_INDEX = os.getenv("MONGODB_VECTOR_INDEX", "vector_index")
        self.VECTOR_DIMENSIONS = int(os.getenv("VECTOR_DIMENSIONS", "1024"))

        # Voyage AI embeddings — must match the model used at ingestion time.
        # LiteLLM requires the 'voyage/' provider prefix.
        self.VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY")
        self.VOYAGE_MODEL = os.getenv("VOYAGE_MODEL", "voyage/voyage-4-large")

        # JSearch (RapidAPI live job search)
        self.JSEARCH_API_KEY = os.getenv("JSEARCH_API_KEY")
        self.RAPIDAPI_HOST = os.getenv("RAPIDAPI_HOST", "jsearch.p.rapidapi.com")
        self.JSEARCH_BASE_URL = os.getenv("JSEARCH_BASE_URL", "https://jsearch.p.rapidapi.com")

        # Retrieval
        self.TOP_K = int(os.getenv("TOP_K", 4))

    @staticmethod
    def format_model_identifier(model: str) -> str:
        """
        Ensures the exact LiteLLM model identifier is returned without duplicate provider prefixes.
        Does not prepend 'groq/' if 'groq/' is already present.
        """
        if not model:
            return ""
        cleaned = model.strip('"\n\r ')
        return cleaned

    def get_api_key_for_model(self, model: str):
        """Returns the appropriate API key for a given model string."""
        if not model:
            return None
        m = model.lower().strip()
        if m.startswith("groq/") or "groq" in m or "llama" in m or "gpt-oss" in m:
            return self.GROQ_API_KEY
        if m.startswith("xai/") or "grok" in m or "xai" in m:
            return self.XAI_API_KEY
        if m.startswith("gemini/") or "gemini" in m:
            return self.GEMINI_API_KEY
        if "voyage" in m:
            return self.VOYAGE_API_KEY
        return None

settings = Settings()