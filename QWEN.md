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
  ├─ helpers/  (modular chat logic)
  │   ├─ chat_config.py       — AppConfig, OpenAI client factory
  │   ├─ chat_prompts.py      — System prompt templates
  │   ├─ chat_utils.py        — Token budget, message formatting
  │   ├─ chat_settings.py     — Persisted settings (ChromaDB)
  │   ├─ chat_context.py      — RAG + web search context builder
  │   ├─ chat_handlers.py     — GmailHandler, DriveHandler, PostgresHandler, StreamHandler
  │   ├─ chat_ui.py           — Streamlit UI components
  │   ├─ rag_utils_langchain.py — ChromaDB document indexing
  │   ├─ program_generator.py — Qwen-driven code generation
  │   └─ program_manager.py   — Lifecycle (start/stop/delete/restore)
  │
  └─ pages/                   — Streamlit multi-page sidebar
      ├─ about.py
      ├─ dropbox.py
      ├─ logs.py
      └─ programs.py

manager_api.py (FastAPI, :8500)
  ├─ POST /programs/generate
  ├─ GET /programs/{id}
  ├─ PUT /programs/{id}/code
  ├─ POST /programs/{id}/start|stop
  ├─ DELETE /programs/{id}
  └─ GET /programs/{id}/logs
```

### Key tech stack

| Component            | Choice                     |
|-----------------------|----------------------------|
| UI                    | Streamlit 1.55             |
| API / Backend         | FastAPI + uvicorn          |
| LLM client            | OpenAI SDK 2.30 (pluggable) |
| Vector DB             | ChromaDB (ONNXMiniLM_L6_V2) |
| RAG                   | LangChain + langchain-chroma |
| Embeddings            | ONNX TinyBERT (pre-cached) |
| Integrations          | Gmail API, Google Drive, PostgreSQL, DuckDuckGo web search |
| Deployment            | Docker Compose + GHCR      |

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

Required: OpenAI API key, ChromaDB path, Gmail OAuth credentials, PostgreSQL credentials (optional), SCALEWAY settings (optional for fallback inference).

### CI/CD

`.github/workflows/deploy.yml` — builds and pushes to `ghcr.io/graphtrek/python-for-ai:latest` (and `sha-<sha>`) on push to `main` or manual dispatch.

---

## Project 2: tutorials

**Purpose:** Step-by-step learning materials for interacting with AI models via the OpenAI SDK.

### Available tutorials

| Folder                           | Focus                            |
|----------------------------------|----------------------------------|
| `01_call_local_lmstudio_model`   | Local LLM inference via LM Studio (:1234) |
| `02_call_scaleway_model`         | Cloud inference via Scaleway API |

Both tutorials use `openai==2.30.0` + `python-dotenv`.

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

| Script                     | Purpose                                          | Dependencies   |
|----------------------------|--------------------------------------------------|----------------|
| `pptx_to_md.py`            | PPTX → Markdown (Marp format)                    | python-pptx    |
| `md_to_pptx.py`            | Markdown → PPTX (clone template slide styles)    | python-pptx    |
| `insert_ai_skills_slide.py`| Insert AI skills slide after slide 11            | python-pptx    |
| `insert_genai_slide.py`    | Insert GenAI explanation slide after slide 2     | python-pptx + Pillow |

All scripts save to new output files; none overwrite originals.

### Dependencies

```
python-pptx
Pillow
```

---

## Workspace-level notes

- **VS Code workspace:** `python-for-ai.code-workspace` — single folder mode (all sub-projects open).
- Each project maintains its own `.venv/` — activate per-project.
- `.env.example` at workspace root; copy per-project and fill secrets.
- Hungarian-language UI content throughout (nothing-gets-out) and presentations (hikari-slides).
