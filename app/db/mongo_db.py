import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import certifi
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings
import logging

# Setup Logger (Critical for Cloud Debugging)
logger = logging.getLogger("uvicorn")

class Database:
    client: AsyncIOMotorClient = None

db_instance = Database()

def get_database_client():
    return db_instance.client


def get_vector_collection():
    db_name = settings.DB_NAME
    return db_instance.client[db_name]["vector_documents"]


async def connect_to_mongo():
    try:
        logger.info("⏳ Connecting to MongoDB Atlas...")
        db_instance.client = AsyncIOMotorClient(
            settings.MONGO_URI,
            serverSelectionTimeoutMS=10000,
            connectTimeoutMS=10000,
            tlsCAFile=certifi.where(),  # fixes TLSV1_ALERT_INTERNAL_ERROR on some Windows/Python setups
        )
        # THE PING TEST (Crucial for Cloud)
        await db_instance.client.admin.command('ping')
        logger.info("✅ MongoDB Atlas Connected Successfully!")
    except Exception as e:
        logger.error(f"❌ MongoDB Atlas Connection Failed: {e}")
        raise e


async def close_mongo_connection():
    if db_instance.client:
        db_instance.client.close()
        logger.info("🔒 MongoDB connection closed.")


if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    async def main():
        try:
            await connect_to_mongo()
        finally:
            await close_mongo_connection()

    asyncio.run(main())