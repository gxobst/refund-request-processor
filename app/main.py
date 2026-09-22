"""AI Refund Request Processor - Application Entrypoint"""

from fastapi import FastAPI

from app.api.refunds import router as refunds_router

app = FastAPI(
    title="AI Refund Request Processor",
    description="Back-office e-commerce refund evaluation tool powered by LangGraph and AWS Bedrock",
    version="0.1.0",
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
