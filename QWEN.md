# QWEN.md — Workspace Context for python-for-ai

## Workspace Overview

This is a multi-project Python workspace for AI-powered applications and learning materials. It contains three distinct projects:

1. **[nothing-gets-out](nothing-gets-out/)** — GDPR-compliant, on-premise AI assistant with a Streamlit chat UI, FastAPI backend, and integrations (Gmail, Google Drive, PostgreSQL, web search, ChromaDB RAG).
2. **[tutorials](tutorials/)** — Practical tutorials for calling local (LM Studio) and cloud (Scaleway) AI models via the OpenAI SDK.
3. **[hikari-slides](hikari-slides/)** — PowerPoint generation toolkit for Hungarian SME AI strategy presentations (`python-pptx` + `Pillow` pipeline).

---

## Project 1: nothing-gets-out

**Purpose:** Private, on-premise AI chatbot that never sends data to the cloud (except LLM inference). GDPR-conscious architecture with vector-search context from uploads, email, drive, and databases.

### Architecture

```
Chat.py (Streamlit UI, :8501)
  │
   ├─ helpers/   (modular chat logic)
   │    ├─ chat_config.py        — AppConfig, OpenAI client factory
   │    ├─ chat_prompts.py       — System prompt templates
   │    ├─ chat_utils.py         — Token budget, message formatting
   │    ├─ chat_settings.py      — Persisted settings (ChromaDB)
   │    ├─ chat_context.py       — RAG + web search context builder
   │    ├─ chat_handlers.py      — GmailHandler, DriveHandler, PostgresHandler, StreamHandler
   │    ├─ chat_ui.py            — Streamlit UI components
   │    ├─ rag_utils_langchain.py — ChromaDB document indexing
   │    ├─ program_generator.py  — Qwen-driven code generation
   │    ├─ program_manager.py    — Lifecycle (start/stop/delete/restore)
   │    ├─ gmail_utils.py        — Gmail API wrapper
   │    ├─ drive_utils.py        — Google Drive API wrapper
   │    ├─ postgres_utils.py     — PostgreSQL query tools
   │    ├─ *_mcp_server.py       — MCP servers for VS Code Copilot integration
   │    └─ auth_*.py             — OAuth2 authentication helpers
   │
   └─ pages/                     — Streamlit multi-page sidebar
       ├─ Programs.py            — Dynamic program generator UI
       ├─ DropBox.py             — File upload + index management
       ├─ Logs.py                — Log viewer
       └─ About.py               — App info

manager_api.py (FastAPI, :8500)
   ├─ POST /programs/generate
   ├─ POST /programs/{id}/regenerate
   ├─ GET /programs
   ├─ GET /programs/{id}
   ├─ GET|PUT /programs/{id}/code
   ├─ POST /programs/{id}/start|stop
   ├─ DELETE /programs/{id}
   ├─ GET /programs/{id}/logs
   └─ GET /programs/{id}/download
```

### Key tech stack

| Component             | Choice                              |
|-----------------------|-------------------------------------|
| UI                    | Streamlit 1.55                      |
| API / Backend         | FastAPI + uvicorn                   |
| LLM client            | OpenAI SDK 2.30 (pluggable)         |
| Vector DB             | ChromaDB (ONNXMiniLM_L6_V2)         |
| RAG                   | LangChain + langchain-chroma        |
| Embeddings            | ONNX TinyBERT (pre-cached in Docker)|
| Integrations          | Gmail API, Google Drive, PostgreSQL, DuckDuckGo web search |
| MCP Servers           | FastMCP (stdio transport)           |
| Deployment            | Docker Compose + GHCR               |

### Chat Modes (context-isolated)

- **Internet** — real-time web search via DuckDuckGo
- **DropBox** — semantic search over uploaded documents (PDF, DOCX, XLSX, TXT, MD) via ChromaDB
- **Gmail** — full Gmail tool-calling (list, read, send, reply, label, trash)
- **Drive** — Google Drive operations (list, read, upload, move, share, trash)
- **Postgres** — database query tool-calling

Each mode is context-isolated: the model only sees data from the active mode's source.

### Building and Running

**Docker Compose (recommended):**
```bash
cd nothing-gets-out
docker-compose up
```
- Chat UI: http://localhost:8501
- Manager API docs: http://localhost:8500/docs

**Local development:**
```bash
cd nothing-gets-out
source .venv/bin/activate
pip install -r requirements.txt

# Terminal 1: Streamlit UI
streamlit run Chat.py

# Terminal 2: Manager API
uvicorn manager_api:app --host 0.0.0.0 --port 8500
```

**Build Docker image:**
```bash
cd nothing-gets-out
docker build -f Dockerfile -t python-for-ai .
```

### Environment variables (.env)

Required: `SCALEWAY_BASE_URL`, `SCALEWAY_API_KEY`, ChromaDB path, Gmail OAuth credentials, PostgreSQL credentials (optional), SCALEWAY settings (optional for fallback inference).

See `.env.example` at workspace root for the template.

### ChromaDB Collections

| Collection       | Purpose                          |
|------------------|----------------------------------|
| `dropbox_docs`   | Document chunks + embeddings     |
| `index_stats`    | Per-file indexing metadata       |
| `usage_history`  | Token usage per LLM call         |
| `chat_settings`  | User settings (model, chat mode) |

### CI/CD

`.github/workflows/deploy.yml` — builds and pushes to `ghcr.io/graphtrek/python-for-ai:latest` (and `sha-<sha>`) on push to `main` or manual dispatch. Build context is `nothing-gets-out/`.

---

## Project 2: tutorials

**Purpose:** Step-by-step learning materials for interacting with AI models via the OpenAI SDK.

### Available tutorials

| Folder                            | Focus                                 |
|-----------------------------------|---------------------------------------|
| `01_call_local_lmstudio_model`    | Local LLM inference via LM Studio (:1234) |
| `02_call_scaleway_model`          | Cloud inference via Scaleway API      |

Both tutorials use `openai==2.30.0` + `python-dotenv`.

### Running tutorials

```bash
cd tutorials
source .venv/bin/activate
pip install -r requirements.txt
python 01_call_local_lmstudio_model
python 02_call_scaleway_model
```

---

## Project 3: hikari-slides

**Purpose:** Tools for generating and editing Hungarian SME ("KKV") AI strategy PowerPoint presentations.

### Pipeline

```
.pptx (template) ──pptx_to_md.py──▶ .md (Marp source)
.md ──md_to_pptx.py──▶ .pptx (template-cloned slides)
.pptx ──insert_*.py──▶ .pptx (individual slide inserts)
```

### Key scripts

| Script                      | Purpose                                          | Dependencies    |
|----------------------------|--------------------------------------------------|-----------------|
| `pptx_to_md.py`            | PPTX → Markdown (Marp format)                    | python-pptx     |
| `md_to_pptx.py`            | Markdown → PPTX (clone template slide styles)    | python-pptx     |
| `generate_kkv_pptx.py`     | Full KKV presentation generation                 | python-pptx     |
| `generate_kkv_dark.py`     | Dark-theme KKV presentation                      | python-pptx     |
| `insert_ai_skills_slide.py`| Insert AI skills slide after slide 11            | python-pptx     |
| `insert_genai_slide.py`    | Insert GenAI explanation slide after slide 2     | python-pptx + Pillow |

All scripts save to new output files; none overwrite originals.

### Running

```bash
cd hikari-slides
source .venv/bin/activate
pip install -r requirements.txt
python generate_kkv_pptx.py
```

---

## Workspace-level notes

- **VS Code workspace:** `python-for-ai.code-workspace` — single folder mode (all sub-projects open).
- Each project maintains its own `.venv/` — activate per-project.
- `.env.example` at workspace root; copy per-project and fill secrets.
- Hungarian-language UI content throughout (nothing-gets-out) and presentations (hikari-slides).
- MCP servers (`gmail_mcp_server.py`, `drive_mcp_server.py`, `postgres_mcp_server.py`) enable VS Code Copilot Agent integration via stdio transport.
