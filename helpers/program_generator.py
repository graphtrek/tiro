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
