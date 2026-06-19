"""Debug entry point for the bank FastAPI app.

Run from VS Code (Run & Debug → "bank API") or directly:
    python run_api.py
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("bank.api.main:app", host="127.0.0.1", port=8005, reload=True)
