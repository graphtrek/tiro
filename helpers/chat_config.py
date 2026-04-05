import os

import streamlit as st
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from openai import OpenAI

# Load .env before the class body reads os.environ
load_dotenv()


class AppConfig:
    """Central place for all app-wide constants and helpers."""

    ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    LOG_FILE   = os.path.join(ROOT, "ai.log")
    UPLOAD_DIR = os.path.join(ROOT, "uploads")
    CHROMA_DIR = os.path.join(ROOT, "chroma_db")

    BASE_URL = os.environ["SCALEWAY_BASE_URL"]
    API_KEY  = os.environ["SCALEWAY_API_KEY"]

    MODELS = [
        "mistral-small-3.2-24b-instruct-2506",
        "qwen3-coder-30b-a3b-instruct",
    ]

    MODEL_LABELS = {
        "mistral-small-3.2-24b-instruct-2506": "Chat és képelemzés",
        "qwen3-coder-30b-a3b-instruct":        "Chat és kód",
    }

    VISION_MODELS = {"mistral-small-3.2-24b-instruct-2506"}

    @staticmethod
    def get_model_label(model_name: str) -> str:
        return AppConfig.MODEL_LABELS.get(model_name, model_name)


# ── Cached client factories ───────────────────────────────────────────────────
# @st.cache_resource must be at module level — Streamlit does not support it
# inside class bodies.

@st.cache_resource
def get_openai_client() -> OpenAI:
    """Direct OpenAI-compatible client — used for token-by-token streaming."""
    return OpenAI(base_url=AppConfig.BASE_URL, api_key=AppConfig.API_KEY)


@st.cache_resource
def get_langchain_llm(model_name: str) -> ChatOpenAI:
    """LangChain ChatOpenAI wrapper — used by RAG retrieval chains."""
    return ChatOpenAI(
        model=model_name,
        temperature=0.5,
        top_p=0.8,
        max_tokens=32768,
        openai_api_base=AppConfig.BASE_URL,
        openai_api_key=AppConfig.API_KEY,
        streaming=False,
    )


@st.cache_resource
def load_usage_history_cached():
    from helpers.rag_utils_langchain import load_usage_history
    return load_usage_history()
