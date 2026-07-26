"""Debug entry point for the invoice-file-filter FastAPI app.

Run from VS Code (Run & Debug → "invoice-file-filter API") or directly:
    python run_api.py
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "invoice_file_filter.api.main:app",
        host="127.0.0.1",
        port=8001,
        reload=True,
        reload_dirs=["src"],
    )
