import json
import os
import re
from pathlib import Path

import requests
from dotenv import load_dotenv
from openai import OpenAI

try:
    from ddgs import DDGS
    _DDGS_AVAILABLE = True
except ImportError:
    _DDGS_AVAILABLE = False

try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False

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

Existing Programs Context:
If the user prompt contains a section starting with "=== Existing Programs ===",
it lists all programs that have already been generated in this workspace.
Study their code carefully to:
- Follow the same coding conventions, error-handling patterns, and import style.
- Reuse the same helper modules (e.g. get_gmail_service, get_drive_service) in the same way.
- Avoid functionality or naming conflicts with existing programs.
- Build on proven patterns rather than reinventing them.

Uploaded File Context (DropBox):
If the user prompt contains a section starting with "=== Uploaded Files Context ===",
it lists files the user has uploaded and provides relevant excerpts from their content.
USE this information to understand the data structure (column names, fields, document format,
example values) so the generated API correctly reads, parses, or processes those files.
Files are stored under the `uploads/` directory in the project root.

Web Research Context:
If the user prompt contains a section starting with "=== Referenced URL Content ===",
it contains content fetched from URLs the user specified — treat this as the PRIMARY source.
If the prompt contains a section starting with "=== Web Search Results ===",
it contains DuckDuckGo search snippets for supplemental context.
Use both to make the generated code accurate and aligned with the referenced resources.
"""


_DROPBOX_KEYWORDS = re.compile(
    r"\b(dropbox|uploaded?\s+files?|from\s+uploads?)\b",
    re.IGNORECASE,
)

_URL_PATTERN = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)


def _extract_urls(text: str) -> list[str]:
    """Return all HTTP/HTTPS URLs found in text."""
    return _URL_PATTERN.findall(text)


def _fetch_url_content(url: str, max_chars: int = 32768) -> str | None:
    """Fetch a URL and return its text content, stripping HTML if needed."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; ProgramGenerator/1.0)"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "text/html" in content_type:
            if _BS4_AVAILABLE:
                soup = BeautifulSoup(resp.text, "html.parser")
                for tag in soup(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                text = soup.get_text(separator="\n", strip=True)
            else:
                text = re.sub(r"<[^>]+>", " ", resp.text)
                text = re.sub(r"\s+", " ", text).strip()
        else:
            text = resp.text
        if len(text) > max_chars:
            text = text[:max_chars] + "\n... [truncated]"
        return text
    except Exception:
        return None


def _web_search_context(query: str, max_results: int = 3) -> str | None:
    """Run a DuckDuckGo search and return formatted snippets."""
    if not _DDGS_AVAILABLE:
        return None
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query[:200], max_results=max_results))
        if not results:
            return None
        lines = ["=== Web Search Results ==="]
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] {r.get('title', '')}")
            lines.append(f"URL: {r.get('href', '')}")
            lines.append(r.get("body", ""))
            lines.append("")
        lines.append("=== End Web Search Results ===")
        return "\n".join(lines)
    except Exception:
        return None


def _get_web_research_context(description: str, requirements: str) -> str | None:
    """Build a research context block from user-specified URLs and/or a web search.

    User-provided URLs are fetched first and treated as the preferred source.
    A DuckDuckGo search is always attempted for supplemental context.
    """
    combined = description + " " + requirements
    urls = _extract_urls(combined)

    sections: list[str] = []

    if urls:
        url_lines = ["=== Referenced URL Content ==="]
        for url in urls[:3]:
            content = _fetch_url_content(url)
            if content:
                url_lines.append(f"--- Content from {url} ---")
                url_lines.append(content)
                url_lines.append("")
        url_lines.append("=== End Referenced URL Content ===")
        if len(url_lines) > 2:  # only add if at least one URL yielded content
            sections.append("\n".join(url_lines))

    search_query = f"{description} {requirements}".strip()
    search_ctx = _web_search_context(search_query)
    if search_ctx:
        sections.append(search_ctx)

    return "\n\n".join(sections) if sections else None


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


_GENERATED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "generated_programs",
)


def _get_existing_programs_context(exclude_id: str | None = None) -> str | None:
    """Return a formatted context block describing all previously generated programs.

    Each entry includes the program name, description, requirements, and its
    full source code so Qwen can learn from and stay consistent with them.
    """
    root = Path(_GENERATED_DIR)
    if not root.exists():
        return None

    entries: list[str] = []
    for prog_dir in sorted(root.iterdir()):
        manifest_path = prog_dir / "manifest.json"
        code_path = prog_dir / "main.py"
        if not manifest_path.exists() or not code_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        prog_id = manifest.get("id", "")
        if exclude_id and prog_id == exclude_id:
            continue
        name = manifest.get("name", prog_dir.name)
        description = manifest.get("description", "")
        requirements = manifest.get("requirements", "")
        try:
            code = code_path.read_text()
        except OSError:
            code = "(code unavailable)"
        entry = (
            f"Program: {name}  (id: {prog_id})\n"
            f"Description: {description}\n"
            f"Requirements: {requirements}\n"
            f"--- main.py ---\n"
            f"{code}\n"
            f"--- end main.py ---"
        )
        entries.append(entry)

    if not entries:
        return None

    lines = ["=== Existing Programs ===", ""]
    for i, entry in enumerate(entries, 1):
        lines.append(f"[{i}]")
        lines.append(entry)
        lines.append("")
    lines.append("=== End Existing Programs ===")
    return "\n".join(lines)


def _get_client() -> OpenAI:
    base_url = os.environ["SCALEWAY_BASE_URL"]
    api_key = os.environ["SCALEWAY_API_KEY"]
    return OpenAI(base_url=base_url, api_key=api_key)


def generate_program_code(
    name: str,
    description: str,
    requirements: str,
    exclude_program_id: str | None = None,
) -> str:
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

    existing_ctx = _get_existing_programs_context(exclude_id=exclude_program_id)
    if existing_ctx:
        user_prompt += f"\n\n{existing_ctx}"

    if _detect_dropbox_mention(description, requirements):
        context = _get_dropbox_context(description + " " + requirements)
        if context:
            user_prompt += f"\n\n{context}"

    research = _get_web_research_context(description, requirements)
    if research:
        user_prompt += f"\n\n{research}"

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
