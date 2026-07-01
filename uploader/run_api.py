"""Debug entry point for the uploader FastAPI app.

Run from VS Code (Run & Debug → "uploader API") or directly:
    python run_api.py
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("uploader.api.main:app", host="127.0.0.1", port=8006, reload=True)
