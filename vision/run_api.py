"""Debug entry point — run from the vision/ project root."""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("vision.api.main:app", host="127.0.0.1", port=8009, reload=True)
