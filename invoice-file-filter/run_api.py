"""Debug entry point for the pdf-szamla FastAPI app.

Run from VS Code (Run & Debug → "pdf-szamla API") or directly:
    python run_api.py
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("pdf_szamla.api.main:app", host="127.0.0.1", port=8001, reload=True)
