# KYC Screener — Project Conventions

## Overview
Multi-Agent KYC Screening System using LangGraph for orchestration and Google Gemini 2.5 Pro as the LLM. Four specialised agents (Research, Sanctions, UBO, Risk Assessment) are coordinated by an Orchestrator that produces a final KYC report.

## Tech Stack
- **LangGraph** — multi-agent graph-based workflow
- **Google Gemini 2.5 Pro** — LLM via `langchain-google-genai` / `google-genai`
- **Tavily** — web search for Research Agent
- **OpenSanctions API** — sanctions list lookups
- **FastAPI** — REST API backend (`src/api/main.py`)
- **Streamlit** — frontend (`frontend/app.py`)
- **Pydantic v2** — all structured data models in `src/models/`

## Project Layout
```
src/
  agents/          # Individual agent implementations
  orchestrator/    # LangGraph state machine (graph.py, state.py)
  tools/           # Shared tool wrappers (search, sanctions, company registry)
  models/          # Pydantic data models — single source of truth for all schemas
  api/             # FastAPI app
frontend/          # Streamlit UI
tests/             # pytest test suite
data/              # Sample sanctions lists and test fixtures
```

## Code Conventions

### General
- Python 3.11+; use `from __future__ import annotations` in every file
- All public functions and classes need type annotations; no `Any` unless unavoidable
- No bare `except`; always catch specific exceptions
- Use `structlog` for logging — never `print()`
- Constants in `UPPER_SNAKE_CASE`; everything else follows PEP 8

### Pydantic Models
- All models live in `src/models/`; import from there everywhere else
- Use `model_config = ConfigDict(frozen=True)` for value-object models (e.g. `RiskRating`)
- Validators go on the model, not in agent code
- Prefer `Literal` types over plain strings for enumerations (e.g. `RiskLevel`)

### LangGraph
- `GraphState` (TypedDict) is defined in `src/orchestrator/state.py` — all agents read/write only that
- Agent nodes are plain `async def` functions; no class-based agents unless necessary
- Each agent returns a partial state dict — only the keys it modifies
- Conditional edges use named routing functions for readability

### Agents
- Every agent module exposes a single coroutine: `async def run(state: GraphState) -> dict`
- Agents must never call each other directly — all coordination goes through the graph
- Structured LLM outputs use `with_structured_output()` bound to the relevant Pydantic model

### Tools
- All external API calls are wrapped in `src/tools/`
- Tool functions are `async`; use `httpx.AsyncClient` for HTTP calls
- Retry logic (max 3 attempts, exponential backoff) lives in the tool layer, not the agent layer

### Testing
- Tests live in `tests/`; mirror `src/` structure
- Use `pytest-asyncio` for async tests; mark with `@pytest.mark.asyncio`
- Mock external APIs (Tavily, OpenSanctions) in tests — never hit live endpoints in CI
- Fixture data lives in `data/`

## Environment Variables
See `.env.example`. Load with `python-dotenv` in `src/config.py` (to be created).

## Running the App
```bash
# API server
uvicorn src.api.main:app --reload

# Streamlit frontend
streamlit run frontend/app.py
```

## Running Tests
```bash
pytest tests/ -v
```
