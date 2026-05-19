# AGENTS.md

## Core Workspace Principles
- **Multi-project scope**: This is a workspace. Each sub-project (`nothing-gets-out/`, `tutorials/`, `hikari-slides/`) has its own `.venv`, `requirements.txt`, and `.env`.
- **Context Isolation**: Always `cd` into the specific project directory before running commands or inspecting `.env` files.

## nothing-gets-out (Primary Project)
### Running & Development
- **Local Dev (Two Processes Required)**:
  1. Terminal 1 (UI): `cd nothing-gets-out && source .venv/bin/activate && streamlit run Chat.py`
  2. Terminal 2 (Backend): `cd nothing-gets-out && source .venv/bin/activate && uvicorn manager_api:app --host 0.0.0.0 --port 8500 --reload`
- **Docker**: Use `cd nothing-gets-out && docker compose up` for a complete environment.
- **Environment**: Requires `.env` populated from `.env.example`. Key for: `SCALEWAY_API_KEY`, `SCALEWAY_ENDPOINT_URL`, `CHAT_MODEL`, `CODER_MODEL`.

### Architecture & Flow
- **Dynamic Programs**: The `packages/program/` module uses Qwen to generate FastAPI microservices at runtime. These land in `nothing-gets-out/generated_programs/`.
- **RAG Persistence**: ChromaDB vector store is located in `nothing-gets-out/chroma_db/`.
- **Tooling**: Tool definitions are in `packages/tools/`; execution logic is in `packages/chat/handlers.py`.

## Tooling & Deployment
- **Deployment**: CI/CD at `.github/workflows/deploy.yml` pushes the `nothing-gets-out` context to GHCR.
- **MCP Servers**: Standalone FastMCP servers in `packages/mcp/` can be used to expose tools to VS Code Copilot.
