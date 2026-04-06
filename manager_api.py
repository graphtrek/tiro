"""Manager API — FastAPI service for dynamic program generation and lifecycle.

Run with:
    uvicorn manager_api:app --host 0.0.0.0 --port 8500

Endpoints:
    POST   /programs/generate           Generate a new program via Qwen
    GET    /programs                    List all programs
    GET    /programs/{id}               Get program details
    GET    /programs/{id}/code          Get generated source code
    PUT    /programs/{id}/code          Update source code
    POST   /programs/{id}/start         Start the program
    POST   /programs/{id}/stop          Stop the program
    DELETE /programs/{id}               Delete the program
    GET    /programs/{id}/logs          Get stdout/stderr logs
    GET    /health                      Health check
"""

from dotenv import load_dotenv

load_dotenv()

from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from helpers.program_generator import generate_program_code
from helpers.program_manager import (
    create_program,
    delete_program,
    get_logs,
    get_program,
    list_programs,
    start_program,
    stop_program,
    update_code,
)

app = FastAPI(
    title="Python Program Manager",
    description="Dynamically generate and manage FastAPI programs via Qwen.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ─────────────────────────────────────────────────


class GenerateRequest(BaseModel):
    name: str
    description: str
    requirements: str
    mode: str = "service"  # "service" | "on_demand"


class UpdateCodeRequest(BaseModel):
    code: str


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/programs/generate", status_code=201)
async def generate(request: GenerateRequest):
    """Generate a FastAPI program using Qwen and store it on disk."""
    code = generate_program_code(
        request.name, request.description, request.requirements
    )
    manifest = create_program(
        request.name, request.description, code, request.mode
    )
    return manifest


@app.get("/programs")
async def list_all():
    return list_programs()


@app.get("/programs/{program_id}")
async def get_detail(program_id: str):
    program = get_program(program_id)
    if not program:
        raise HTTPException(status_code=404, detail="Program not found")
    return program


@app.get("/programs/{program_id}/code")
async def get_code(program_id: str):
    from helpers.program_manager import _find_prog_dir

    prog_dir = _find_prog_dir(program_id)
    if not prog_dir:
        raise HTTPException(status_code=404, detail="Program not found")
    code_path = prog_dir / "main.py"
    if not code_path.exists():
        raise HTTPException(status_code=404, detail="Program not found")
    return {"code": code_path.read_text()}


@app.put("/programs/{program_id}/code")
async def put_code(program_id: str, body: UpdateCodeRequest):
    try:
        update_code(program_id, body.code)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Program not found")
    return {"status": "updated"}


@app.post("/programs/{program_id}/start")
async def start(program_id: str):
    try:
        return start_program(program_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Program not found")


@app.post("/programs/{program_id}/stop")
async def stop(program_id: str):
    try:
        return stop_program(program_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Program not found")


@app.delete("/programs/{program_id}")
async def delete(program_id: str):
    try:
        delete_program(program_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Program not found")
    return {"status": "deleted"}


@app.get("/programs/{program_id}/logs")
async def logs(program_id: str, lines: int = 100):
    return {"logs": get_logs(program_id, lines)}
