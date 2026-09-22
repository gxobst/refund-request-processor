# AI Refund Request Processor

A back-office e-commerce tool that receives a refund request, evaluates it with a LangGraph multi-agent system, and produces one of three decisions:
- `auto_approve`
- `deny`
- `escalate`

## Architecture & Stack
- **Agents**: LangGraph multi-agent orchestration
- **LLM**: AWS Bedrock (`amazon.nova-2-lite-v1:0`) via `langchain-aws`
- **Database**: AWS DynamoDB for persistence and checkpointing
- **Backend API**: FastAPI
- **Frontend**: React + TypeScript + Vite + Tailwind CSS + shadcn/ui
- **Observability**: LangSmith
