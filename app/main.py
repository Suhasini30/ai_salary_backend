import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes.chat_router import router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("suhasini")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("BOOT: app started, light imports only (litellm/motor lazy)")
    yield
    logger.info("SHUTDOWN: app stopping")


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

@app.get("/")
def home():
    return {
        "message":"hi I'm suhasini, sales assistant"
        }

@app.get("/health")
def health():
    return {
        "status":"healthy"
        }
