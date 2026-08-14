from dotenv import load_dotenv
import os


load_dotenv()

class Settings:
    def __init__(self):
        # API Keys
        self.GROQ_API_KEY = os.getenv("GROQ_API_KEY")
        self.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        

        # Models
        self.GROQ_MODEL = os.getenv("GROQ_MODEL")
        self.GEMINI_MODEL = os.getenv("GEMINI_MODEL")
        self.DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", self.GEMINI_MODEL)

        # LLM router
        self.ROUTER_MODEL = os.getenv("ROUTER_MODEL") or self.GROQ_MODEL
        self.ROUTER_MIN_CONFIDENCE = float(os.getenv("ROUTER_MIN_CONFIDENCE", "0.4"))

        # JSearch (RapidAPI live job search)
        self.JSEARCH_API_KEY = os.getenv("JSEARCH_API_KEY")
        self.RAPIDAPI_HOST = os.getenv("RAPIDAPI_HOST", "jsearch.p.rapidapi.com")
        self.JSEARCH_BASE_URL = os.getenv("JSEARCH_BASE_URL", "https://jsearch.p.rapidapi.com")

        # Retrieval
        self.TOP_K = int(os.getenv("TOP_K", 4))

settings = Settings()