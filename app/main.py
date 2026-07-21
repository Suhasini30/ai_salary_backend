from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes.chat_router import router

app = FastAPI()

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
