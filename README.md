# python-for-ai Workspace

Multi-project workspace for Python-based AI applications.

---

## Overview

This workspace contains multiple Python projects developing AI-powered applications with various integrations and deployment strategies.

### Projects

1. **nothing-gets-out** — GDPR-compliant, on-premise AI assistant
   - Secure local storage, no cloud data transmission
   - Streamlit UI + FastAPI backend
   - Gmail, Google Drive, web search integrations
   - See [nothing-gets-out/README.md](nothing-gets-out/README.md) for detailed documentation

2. **tutorials** — Learning resources for AI model integration
   - Local model setup with LM Studio
   - Cloud inference with Scaleway API
   - OpenAI SDK examples
   - See [tutorials/README.md](tutorials/README.md) for detailed documentation

---

## Technology Stack

This workspace is built on Python and modern AI/web frameworks:

| Technology | Purpose |
|---|---|
| **Python 3.12** | Core language (slim Docker image) |
| **[Streamlit](https://streamlit.io)** | Interactive web UI |
| **[FastAPI](https://fastapi.tiangolo.com)** | REST API backend & program generation |
| **[LangChain](https://www.langchain.com)** | LLM pipelines & RAG workflows |
| **[ChromaDB](https://www.trychroma.com)** | Vector database for semantic search |
| **[Docker & Docker Compose](https://www.docker.com)** | Containerization & orchestration |
| **Google APIs** | Gmail, Google Drive integrations |
| **OpenAI SDK** | LLM API client (via Scaleway inference) |

---

## Quick Start: Running Projects from Terminal

### Prerequisites

- Python 3.12+
- Docker & Docker Compose (optional, for containerized deployment)
- Virtual environment (`.venv/` in each project folder)

### nothing-gets-out Project

**Option 1: Docker Compose (Recommended)**

```bash
cd nothing-gets-out
docker-compose up
```

Access:
- Chat UI: http://localhost:8501
- Manager API docs: http://localhost:8500/docs

**Option 2: Docker Build**

```bash
cd nothing-gets-out
docker build -f Dockerfile -t python-for-ai .
docker run -p 8501:8501 -p 8500:8500 python-for-ai
```

**Option 3: Local Development**

```bash
cd nothing-gets-out

# Activate virtual environment
source .venv/bin/activate  # macOS/Linux
# or: .venv\Scripts\activate  # Windows

# Install dependencies (first time only)
pip install -r requirements.txt

# Terminal 1: Run Streamlit Chat UI
streamlit run Chat.py
# Access at: http://localhost:8501

# Terminal 2: Run FastAPI Manager API
uvicorn manager_api:app --host 0.0.0.0 --port 8500
# Access API docs at: http://localhost:8500/docs
```

---

## Workspace Structure

```
python-for-ai/                          # Workspace root
├── README.md                           # This file (workspace overview)
├── python-for-ai.code-workspace        # VSCode workspace config
│
├── tutorials/                          # Tutorials for AI model integration
│   ├── README.md                       # Tutorial documentation
│   ├── requirements.txt                # Shared dependencies
│   ├── 01_call_local_lmstudio_model    # Tutorial: Local LM Studio
│   └── 02_call_scaleway_model          # Tutorial: Cloud inference (Scaleway)
│
└── nothing-gets-out/                   # Project: "Nothing Gets Out" (GDPR-compliant on-premise AI)
    ├── README.md                       # Project-specific documentation
    ├── Dockerfile                      # Build config for this project
    ├── docker-compose.yml              # Services for this project
    ├── .gitignore                      # Git ignore rules for this project
    ├── ai.log                          # Project logs
    │
    ├── Chat.py                         # Streamlit entry point
    ├── manager_api.py                  # FastAPI manager service
    ├── requirements.txt                # Python dependencies
    ├── .env                            # Environment variables
    │
    ├── helpers/                        # Application modules
    ├── pages/                          # Streamlit multi-page UI
    ├── .streamlit/                     # Streamlit configuration
    │
    ├── credentials.json                # OAuth2 credentials (not committed)
    ├── token.json                      # OAuth2 tokens (not committed)
    ├── chroma_db/                      # Vector database storage
    ├── uploads/                        # User file uploads
    ├── generated_programs/             # Dynamically generated FastAPI programs
    │
    ├── .venv/                          # Python virtual environment
    ├── .vscode/                        # VS Code configuration (project-specific)
    ├── .github/                        # GitHub workflows for this project
    ├── __pycache__/                    # Python bytecode cache
    └── docs/                           # Project documentation
```

---

## Adding a New Project

1. **Create project folder:**
   ```bash
   mkdir new-project
   mkdir -p new-project/{helpers,pages}
   ```

2. **Copy essentials from existing project:**
   ```bash
   cp nothing-gets-out/requirements.txt new-project/
   cp nothing-gets-out/.env new-project/.env.example
   cp -r nothing-gets-out/.streamlit new-project/
   ```

3. **Create project files:**
   - `new-project/Dockerfile` (adapt from [nothing-gets-out/Dockerfile](nothing-gets-out/Dockerfile))
   - `new-project/docker-compose.yml` (adapt from [nothing-gets-out/docker-compose.yml](nothing-gets-out/docker-compose.yml))
   - `new-project/.gitignore` (copy from [nothing-gets-out/.gitignore](nothing-gets-out/.gitignore))
   - `new-project/README.md` (project-specific docs)

4. **Update VSCode workspace** ([python-for-ai.code-workspace](python-for-ai.code-workspace)):
   ```json
   {
     "folders": [
       {"path": "nothing-gets-out"},
       {"path": "new-project"}
     ],
     "settings": {}
   }
   ```

5. **Deploy:**
   ```bash
   cd new-project
   docker-compose up
   ```

---

## Python Virtual Environment Setup

Each project contains its own `.venv/` virtual environment.

### Create a new virtual environment for a project:

```bash
cd project-name
python3 -m venv .venv
```

### Activate the virtual environment:

**macOS/Linux:**
```bash
source project-name/.venv/bin/activate
```

**Windows:**
```bash
project-name\.venv\Scripts\activate
```

### Install dependencies:

```bash
pip install -r requirements.txt
```

### Deactivate:

```bash
deactivate
```
