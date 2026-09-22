"""AI Refund Request Processor - Application Entrypoint"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.refunds import router as refunds_router
from app.core.config import setup_langsmith_environment

# Initialize LangSmith tracing environment variables during module initialization
setup_langsmith_environment()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure tracing environment variables are refreshed during server startup
    setup_langsmith_environment()
    yield


app = FastAPI(
    title="AI Refund Request Processor",
    description="Back-office e-commerce refund evaluation tool powered by LangGraph and AWS Bedrock",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(refunds_router)



@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "refund-request-processor",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}
