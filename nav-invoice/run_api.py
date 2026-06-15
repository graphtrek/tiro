"""Debug entry point for the nav-invoice FastAPI app.

Run from VS Code (Run & Debug → "nav-invoice API") or directly:
    python run_api.py
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("nav_invoice.api.main:app", host="127.0.0.1", port=8002, reload=True)
