"""Debug entry point for the wise-szamla FastAPI app.

Run from VS Code (Run & Debug → "wise API") or directly:
    python run_api.py
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("wise_szamla.api.main:app", host="127.0.0.1", port=8004, reload=True)
