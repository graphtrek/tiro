import os
import re

from dotenv import load_dotenv
from openai import OpenAI

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
      source  — short identifier string (use the app/program name)
      level   — "INFO", "WARNING", or "ERROR"
      message — free-form string
    Writes to the shared ai.log file visible in the Logs page.
    Use this for significant events, errors, and audit trails.
"""


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
