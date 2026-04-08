import os
import re

from dotenv import load_dotenv
from openai import OpenAI

try:
    from helpers.rag_utils_langchain import search_documents_langchain, get_collection_diagnostics
    _RAG_AVAILABLE = True
except Exception:
    _RAG_AVAILABLE = False

load_dotenv()

QWEN_MODEL = "qwen3-coder-30b-a3b-instruct"

_CODE_SYSTEM_PROMPT = """\
You are an expert Python developer. Generate a complete, working FastAPI application.

Rules:
- Output ONLY valid Python source code — no explanations, no markdown, no code fences.
- The app variable must be named `app = FastAPI(...)`.
- Include all necessary imports at the top.
- Use Pydantic models for request/response bodies where appropriate.
- Always include a GET /health endpoint that returns {"status": "ok"}.
- Keep the code clean and production-ready.
- ALWAYS import `log_to_file` from `helpers.log_utils` and use it for ALL logging.
  Do NOT import or use Python's built-in `logging` module.
  Log INFO at the start and successful end of every endpoint handler.
  Log ERROR (with the exception message) in every except block.

Available Google helper modules (PYTHONPATH already includes the project root):
Use these ONLY when the requirements explicitly call for Google Drive or Gmail functionality.

  Google Drive — `from helpers.drive_utils import get_drive_service`
    list_files(service, query=None, folder_id=None)          -> list of file dicts
    read_file_content(service, file_id)                      -> str
    upload_file(service, name, content_bytes, mime_type, folder_id=None) -> file dict
    create_folder(service, name, parent_id=None)             -> folder dict
    trash_file(service, file_id)                             -> None
    share_file(service, file_id, email, role="reader")       -> None

  Gmail — `from helpers.gmail_utils import get_gmail_service`
    list_emails(service, query="", max_results=10)           -> list of message dicts
    read_email(service, message_id)                          -> dict with subject/from/to/body
    send_email(service, to, subject, body)                   -> None
    reply_to_email(service, message_id, body)                -> None
    label_email(service, message_id, label_ids)              -> None
    mark_as_read(service, message_id)                        -> None
    mark_as_unread(service, message_id)                      -> None

  Authentication is handled automatically by the helpers — no credentials needed in generated code.
  Call get_drive_service() / get_gmail_service() once per request handler or at module level.

  Logging — `from helpers.log_utils import log_to_file`
    log_to_file(source, level, message)
      source  — use the program name passed in the description
      level   — "INFO", "WARNING", or "ERROR"
      message — free-form string
    Writes to the shared ai.log file visible in the Logs page.

Uploaded File Context (DropBox):
If the user prompt contains a section starting with "=== Uploaded Files Context ===",
it lists files the user has uploaded and provides relevant excerpts from their content.
USE this information to understand the data structure (column names, fields, document format,
example values) so the generated API correctly reads, parses, or processes those files.
Files are stored under the `uploads/` directory in the project root.
"""


_DROPBOX_KEYWORDS = re.compile(
    r"\b(dropbox|uploaded?\s+files?|from\s+uploads?)\b",
    re.IGNORECASE,
)


def _detect_dropbox_mention(description: str, requirements: str) -> bool:
    combined = description + " " + requirements
    return bool(_DROPBOX_KEYWORDS.search(combined))


def _get_dropbox_context(query: str) -> str | None:
    if not _RAG_AVAILABLE:
        return None
    try:
        diagnostics = get_collection_diagnostics()
        files_indexed: list[str] = diagnostics.get("files_indexed", [])

        chunks, filenames = search_documents_langchain(query, k=6)
        if not chunks:
            if not files_indexed:
                return None
            return (
                "=== Uploaded Files Context ===\n"
                f"Available uploaded files: {', '.join(files_indexed)}\n"
                "(No relevant content chunks found for this query.)\n"
                "=== End Uploaded Files Context ==="
            )

        lines = [
            "=== Uploaded Files Context ===",
            f"Available uploaded files: {', '.join(files_indexed)}",
            "",
            "Relevant content excerpts:",
        ]
        for i, (chunk, fname) in enumerate(zip(chunks, filenames), start=1):
            lines.append(f"[{i}] (source: {fname})")
            lines.append(chunk.strip())
            lines.append("")
        lines.append("=== End Uploaded Files Context ===")
        return "\n".join(lines)
    except Exception:
        return None


def _get_client() -> OpenAI:
    base_url = os.environ["SCALEWAY_BASE_URL"]
    api_key = os.environ["SCALEWAY_API_KEY"]
    return OpenAI(base_url=base_url, api_key=api_key)


def generate_program_code(name: str, description: str, requirements: str) -> str:
    """Call Scaleway Qwen to generate a FastAPI program.

    Returns pure Python source code ready to be saved as main.py.
    """
    client = _get_client()

    user_prompt = (
        f"Create a FastAPI application with the following specifications:\n\n"
        f"Name: {name}\n"
        f"Description: {description}\n"
        f"Requirements: {requirements}\n\n"
        f"Output only the Python source code."
    )

    if _detect_dropbox_mention(description, requirements):
        context = _get_dropbox_context(description + " " + requirements)
        if context:
            user_prompt += f"\n\n{context}"

    response = client.chat.completions.create(
        model=QWEN_MODEL,
        messages=[
            {"role": "system", "content": _CODE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=8192,
    )

    raw = response.choices[0].message.content or ""
    return _strip_code_fences(raw)


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences if the model wraps the output in them."""
    text = text.strip()
    text = re.sub(r"^```(?:python)?\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()
