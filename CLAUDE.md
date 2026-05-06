# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This is a multi-project workspace. Each sub-project has its own `.venv`, `requirements.txt`, and `.env`.

| Directory | Purpose |
|---|---|
| `nothing-gets-out/` | Main project: GDPR-compliant on-premise AI assistant |
| `tutorials/` | OpenAI SDK examples (local LM Studio + Scaleway cloud) |
| `hikari-slides/` | PowerPoint generation for Hungarian SME AI strategy decks |

## nothing-gets-out — primary project

### Running the app

```bash
cd nothing-gets-out

# Activate venv (always needed)
source .venv/bin/activate

# Start Streamlit UI (port 8501)
streamlit run Chat.py

# Start FastAPI backend (port 8500) — required for MCP and program manager
uvicorn manager_api:app --host 0.0.0.0 --port 8500 --reload

# Or use Docker Compose for both together
docker compose up --build
```

### Dependencies

```bash
cd nothing-gets-out
source .venv/bin/activate
pip install -r requirements.txt
```

### Running utility scripts

```bash
cd nothing-gets-out
source .venv/bin/activate
python scripts/run_prompt_sql.py
python scripts/test_query.py
```

### Environment

Copy `.env.example` to `.env` and fill in values. Key variables:
- `SCALEWAY_API_KEY` — inference endpoint key
- `SCALEWAY_ENDPOINT_URL` — Scaleway OpenAI-compatible base URL
- `CHAT_MODEL` — default: `mistral-small-3.2-24b-instruct-2506`
- `CODER_MODEL` — default: `qwen3-coder-30b-a3b-instruct`
- `POSTGRES_*` — database connection details
- `GOOGLE_*` — OAuth credentials (credentials.json / token.json not committed)

## Architecture overview (nothing-gets-out)

### Two-process design
- **Streamlit UI** (`Chat.py`, `pages/`) — chat frontend, file uploads, settings, logs
- **FastAPI backend** (`manager_api.py`) — program lifecycle management (create/start/stop dynamically-generated FastAPI microservices)

### Chat modes & context isolation
Five modes, each with its own tool set and context builder (`helpers/chat_context.py`):
- **Internet** — DuckDuckGo web search
- **DropBox** — RAG over uploaded files (ChromaDB vector store)
- **Gmail** — Gmail API tool calls (read, search, send)
- **Drive** — Google Drive API tool calls
- **PostgreSQL** — SQL generation and execution against a configured DB

Mode-specific tool definitions live in `helpers/chat_*_tools.py`. Handlers for executing those tools live in `helpers/chat_handlers.py`.

### LLM integration
Uses the OpenAI SDK pointed at Scaleway's inference endpoint. Two model slots:
- Chat model (Mistral) for all conversation and tool-use
- Coder model (Qwen) for `program_generator.py` — generates full FastAPI programs from natural language

Client factories are in `helpers/chat_config.py` (`AppConfig`).

### RAG pipeline
`helpers/rag_utils_langchain.py` — LangChain + ChromaDB with ONNX embeddings. Documents (PDF, DOCX, XLSX, TXT) are indexed on upload via the DropBox page. Vector DB stored in `chroma_db/`.

### MCP servers
Three standalone FastMCP servers that expose tools to VS Code Copilot Agent:
- `helpers/gmail_mcp_server.py`
- `helpers/drive_mcp_server.py`
- `helpers/postgres_mcp_server.py`

### Dynamic program manager
`helpers/program_generator.py` — uses Qwen to generate FastAPI microservices from a user prompt. `helpers/program_manager.py` handles subprocess lifecycle. Generated programs land in `generated_programs/`. `manager_api.py` exposes REST endpoints to manage them.

### Persistence
- **ChromaDB** (`chroma_db/`) — vector embeddings and persisted user settings (`helpers/chat_settings.py`)
- **uploads/** — user-uploaded documents
- **ai.log** — application log (`helpers/log_utils.py`)

## CI/CD

`.github/workflows/deploy.yml` builds from `nothing-gets-out/` context and pushes to `ghcr.io/graphtrek/python-for-ai` on every push to `main`. The image runs Streamlit on port 8501.

## Docs prompt system (nothing-gets-out/docs/prompt/)

Structured prompt files used by the PostgreSQL assistant:
- `core/` — identity, schema, currency, tools, workflow rules, analysis areas
- `kan/` — KAN-1 through KAN-10 query templates
- `patterns/` — risk guide, SQL patterns, strategic advice
- `index.md` — prompt index
