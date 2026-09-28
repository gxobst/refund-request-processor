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

## Project Structure
- `backend/`: FastAPI + LangGraph backend service, DynamoDB repositories, Bedrock agents, and test suite.
- `frontend/`: Web dashboard (React / Vite).

## Quickstart

### Option 1: PowerShell (Windows)
Run pure PowerShell script from root:
```powershell
# Start both Backend (FastAPI :8000) and Frontend (Vite :5173)
.\start.ps1

# Force restart services if ports are already listening
.\start.ps1 -Restart

# Stop running services on ports 8000 and 5173
.\start.ps1 -Mode stop

# Open them in separate dedicated PowerShell windows
.\start.ps1 -NewWindows

# Run setup (install deps & seed mock database)
.\start.ps1 -Mode setup

# Run test suites (pytest + vitest)
.\start.ps1 -Mode test

# View all options
.\start.ps1 -Mode help
```

### Option 2: Make (macOS / Linux / WSL / Git Bash)
```bash
# Setup dependencies and seed mock database
make setup

# Start backend server
make backend

# Start frontend server
make frontend

# Run full test suite
make test

# View all available targets
make help
```

## Project Structure
- `backend/`: FastAPI + LangGraph backend service, DynamoDB repositories, Bedrock agents, and test suite.
- `frontend/`: Web dashboard (React / TypeScript / Vite / Tailwind CSS).
- `start.ps1`: Pure PowerShell launcher for full-stack, backend, frontend, seeding, and tests.
- `Makefile`: Make targets for Unix / WSL / cross-platform environments.
- `openapi.yaml`: OpenAPI 3.1.0 contract specification.

