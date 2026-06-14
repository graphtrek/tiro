"""Debug entry point for the attachment-downloader FastAPI app.

Run from VS Code (Run & Debug → "attachment-downloader API") or directly:
    python run_api.py
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("attachment_downloader.api.main:app", host="127.0.0.1", port=8000)
