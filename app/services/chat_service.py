import os
import logging
from app.services.retriever import Retriever
from app.services.llm import LLMService
from app.rag.vector_store import VectorStore
from app.rag.data_processor import DataProcessor
from app.rag.embedder import Embedder
from app.core.config import settings
from app.orchestration.orchestrator import SalesOrchestrator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ChatService:

    def __init__(self, vector_store_folder="vector_db"):
        vector_store = VectorStore()
        
        dataset_path = os.path.join("app", "data", "ai_job_dataset.csv")
        index_path = os.path.join(vector_store_folder, "faiss.index")
        chunks_path = os.path.join(vector_store_folder, "chunks.pkl")

        logger.info("Checking vector database...")
        
        if os.path.exists(vector_store_folder) and os.path.exists(index_path) and os.path.exists(chunks_path):
            logger.info("Existing vector database found.")
            logger.info("Loading FAISS index...")
            vector_store.load(vector_store_folder)
            logger.info("Vector database loaded successfully.")
        else:
            logger.info("Vector database not found. Rebuilding...")
            os.makedirs(vector_store_folder, exist_ok=True)
            
            logger.info("Loading dataset...")
            processor = DataProcessor(dataset_path)
            try:
                processor.load_data()
                processor.validate_data()
            except Exception as e:
                raise RuntimeError(f"Dataset loading failed: {e}") from e
            
            logger.info("Creating chunks...")
            chunks = processor.get_all_chunks()
            
            logger.info("Generating embeddings...")
            embedder = Embedder()
            try:
                embeddings = embedder.embed_chunks(chunks)
            except Exception as e:
                raise RuntimeError(f"Embedding generation failed: {e}") from e
            
            logger.info("Building FAISS index...")
            vector_store.add_embeddings(embeddings, chunks)
            
            logger.info("Saving vector database...")
            try:
                vector_store.save(vector_store_folder)
            except Exception as e:
                logger.error(f"Failed to save vector database: {e}")
                raise
            
            logger.info("Vector database created successfully.")

        self.retriever = Retriever(vector_store)
        self.orchestrator = SalesOrchestrator(retriever=self.retriever)

        # Maps request-facing model_type -> actual model string from .env
        self.model_map = {
            "fast": settings.GROQ_MODEL,
            "quality": settings.GEMINI_MODEL,
        }

    def chat(self, question, model_type="fast"):

        model = self.model_map.get(model_type, settings.DEFAULT_MODEL)

        yield from self.orchestrator.answer(question, model)