"""Debug entry point for the invoice-core FastAPI app.

Run from VS Code (Run & Debug → "invoice-core API") or directly:
    python run_api.py
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("invoice_core.api.main:app", host="127.0.0.1", port=8004, reload=True)
