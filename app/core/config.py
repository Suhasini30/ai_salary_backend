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
        self.VOYAGE_API = os.getenv("VOYAGE_API")
        
        self.MONGO_URI = os.getenv("MONGO_URI")
        self.DB_NAME = os.getenv("DB_NAME")


settings = Settings()