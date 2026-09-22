"""AI Refund Request Processor - Application Entrypoint"""

from fastapi import FastAPI

app = FastAPI(
    title="AI Refund Request Processor",
    description="Back-office e-commerce refund evaluation tool powered by LangGraph and AWS Bedrock",
    version="0.1.0",
)


@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "refund-request-processor",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}
