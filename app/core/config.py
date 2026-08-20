from dotenv import load_dotenv
import os


load_dotenv()

# LiteLLM: skip loading the provider cost map at import time (saves ~10-20MB RAM).
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "False")

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
        self.MISTRAL_API_KEY = _clean_env(os.getenv("MISTRAL_API_KEY"))

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

        if self.MISTRAL_API_KEY:
            os.environ["MISTRAL_API_KEY"] = self.MISTRAL_API_KEY
        elif "MISTRAL_API_KEY" in os.environ and not os.environ["MISTRAL_API_KEY"]:
            del os.environ["MISTRAL_API_KEY"]

        # Models
        self.GROQ_MODEL = _clean_env(os.getenv("GROQ_MODEL")) or "groq/openai/gpt-oss-120b"
        self.DEFAULT_MODEL = _clean_env(os.getenv("DEFAULT_MODEL")) or self.GROQ_MODEL
        self.XAI_MODEL = _clean_env(os.getenv("XAI_MODEL")) or "xai/grok-2-latest"
        self.GEMINI_MODEL = _clean_env(os.getenv("GEMINI_MODEL"))  # Optional, Vertex/Gemini disabled by default
        self.MISTRAL_MODEL = _clean_env(os.getenv("MISTRAL_MODEL")) or "mistral/mistral-large-latest"

        # LLM router
        self.ROUTER_MODEL = _clean_env(os.getenv("ROUTER_MODEL")) or "groq/openai/gpt-oss-20b"
        self.ROUTER_MIN_CONFIDENCE = float(os.getenv("ROUTER_MIN_CONFIDENCE", "0.4"))

        # Router fallback chain (Groq & xAI, Vertex AI disabled)
        raw_fallback = os.getenv("ROUTER_FALLBACK_MODELS")
        if raw_fallback:
            self.ROUTER_FALLBACK_MODELS = [m.strip() for m in raw_fallback.split(",") if m.strip()]
        else:
            # Default fallback order: Primary Router -> xAI Grok -> Mistral -> Groq Default
            candidates = [self.ROUTER_MODEL, self.XAI_MODEL, self.MISTRAL_MODEL, self.DEFAULT_MODEL, self.GROQ_MODEL]
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

        # ── Clerk (external identity provider) ──────────────────────────────
        self.CLERK_SECRET_KEY = _clean_env(os.getenv("CLERK_SECRET_KEY"))
        self.CLERK_JWKS_URL = _clean_env(os.getenv("CLERK_JWKS_URL"))
        self.CLERK_ISSUER = _clean_env(os.getenv("CLERK_ISSUER"))

        # If no JWKS URL is set, derive one from the Clerk issuer or frontend URL.
        if not self.CLERK_JWKS_URL:
            base = (self.CLERK_ISSUER or os.getenv("CLERK_FRONTEND_API_URL") or "").removesuffix("/")
            if base:
                self.CLERK_JWKS_URL = f"{base}/.well-known/jwks.json"

        # If no issuer is set, derive one from the JWKS URL.
        if not self.CLERK_ISSUER and self.CLERK_JWKS_URL and self.CLERK_JWKS_URL.endswith("/.well-known/jwks.json"):
            self.CLERK_ISSUER = self.CLERK_JWKS_URL.removesuffix("/.well-known/jwks.json")

        # ── Own JWT tokens (access + refresh) ───────────────────────────────
        # Access token: sent by the frontend in the Authorization header.
        # Refresh token: stored in an HttpOnly cookie and rotated on expiry.
        self.JWT_SECRET_KEY = _clean_env(os.getenv("JWT_SECRET_KEY"))
        if not self.JWT_SECRET_KEY:
            raise RuntimeError(
                "JWT_SECRET_KEY is required. Generate one with: "
                "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        self.JWT_ALGORITHM = _clean_env(os.getenv("JWT_ALGORITHM")) or "HS256"
        # Recommended: short-lived access tokens (minutes) + long-lived refresh (days).
        self.ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
        self.REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
        self.TOKEN_TYPE_ACCESS = "access"
        self.TOKEN_TYPE_REFRESH = "refresh"

        # ── HttpOnly cookie for the refresh token ───────────────────────────
        self.COOKIE_NAME = _clean_env(os.getenv("COOKIE_NAME")) or "rag_refresh_token"
        # 'lax' is required so the cookie is sent on top-level navigation; 'strict'
        # is safer but breaks cross-site redirect redirects from Clerk.
        self.COOKIE_SAMESITE = _clean_env(os.getenv("COOKIE_SAMESITE")) or "lax"
        self.COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")
        # Restrict the cookie to a single domain (optional; empty = host-only).
        self.COOKIE_DOMAIN = _clean_env(os.getenv("COOKIE_DOMAIN"))
        self.COOKIE_PATH = _clean_env(os.getenv("COOKIE_PATH")) or "/"

        # ── Application / CORS ──────────────────────────────────────────────
        # Comma-separated list of allowed browser origins (no trailing slashes).
        self.FRONTEND_ORIGINS = [
            o.strip() for o in os.getenv("FRONTEND_ORIGINS", "").split(",") if o.strip()
        ] or ["http://localhost:3000", "http://127.0.0.1:3000"]
        self.API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")

        # ── Document uploads ────────────────────────────────────────────────
        self.UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
        # Max size in bytes per uploaded file (default 25 MB).
        self.MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "25")) * 1024 * 1024
        # Allowed content types & extensions.
        self.ALLOWED_EXTENSIONS = {
            ".csv": "text/csv",
        }
        # Chunking
        self.CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
        self.CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))

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
        if m.startswith("mistral/") or "mistral" in m:
            return self.MISTRAL_API_KEY
        if m.startswith("gemini/") or "gemini" in m:
            return self.GEMINI_API_KEY
        if "voyage" in m:
            return self.VOYAGE_API_KEY
        return None

settings = Settings()