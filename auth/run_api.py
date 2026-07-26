"""Debug entry point for the auth FastAPI app.

Run from VS Code (Run & Debug → "auth API") or directly:
    python run_api.py
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "auth_service.api.main:app", host="127.0.0.1", port=8007, reload=True, reload_dirs=["src"]
    )
