"""AI Refund Request Processor - Application Entrypoint"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.policies import router as policies_router
from app.api.refunds import router as refunds_router
from app.core.config import setup_langsmith_environment

# Initialize LangSmith tracing environment variables during module initialization
setup_langsmith_environment()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure tracing environment variables are refreshed during server startup
    setup_langsmith_environment()
    yield


import os
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="AI Refund Request Processor",
    description="Back-office e-commerce refund evaluation tool powered by LangGraph and AWS Bedrock",
    version="0.1.0",
    lifespan=lifespan,
)

default_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

env_origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "").split(",")
    if origin.strip()
]

cors_origins = list(dict.fromkeys(default_origins + env_origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(refunds_router, prefix="/v1")
app.include_router(refunds_router)
app.include_router(policies_router, prefix="/v1")
app.include_router(policies_router)



@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "refund-request-processor",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}
