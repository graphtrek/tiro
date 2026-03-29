# streamlit  — the library that turns this Python script into a web app.
#              Every time the user interacts with the UI, Streamlit re-runs
#              the whole script from top to bottom.
import warnings
warnings.filterwarnings("ignore", message="Core Pydantic V1 functionality")

import logging
import os
from datetime import datetime

# Setup logging to shared log file (only once)
_LOGGING_CONFIGURED = False
_ROOT = os.path.dirname(os.path.abspath(__file__))
_LOG_FILE = os.path.join(_ROOT, "kage-ai.log")

if not _LOGGING_CONFIGURED:
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)

    # Only add handlers if they don't exist yet (to avoid duplicates)
    if not logger.handlers:
        log_format = logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(filename)s | %(funcName)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(log_format)
        logger.addHandler(console_handler)
        
        # File handler (same file as rag_utils_langchain.py)
        file_handler = logging.FileHandler(_LOG_FILE)
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(log_format)
        logger.addHandler(file_handler)

    # Enable debug logging for web search operations
    logging.getLogger("duckduckgo_search").setLevel(logging.DEBUG)
    logging.getLogger("urllib3").setLevel(logging.DEBUG)
    logging.getLogger("langchain_community").setLevel(logging.DEBUG)
    
    # Suppress ONNX runtime warning about providers not being explicitly set
    logging.getLogger("onnxruntime").setLevel(logging.ERROR)
    _LOGGING_CONFIGURED = True
else:
    logger = logging.getLogger(__name__)
import streamlit as st

# st.set_page_config must be the first Streamlit call in the script.
st.set_page_config(page_title="Graphtrek AI Chat", page_icon="💬", menu_items={})

logger.info("Chat.py app started")

# LangChain imports for LLM integration
from langchain_openai import ChatOpenAI
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

import threading

# RAG utilities: LangChain-powered document indexing, search, and storage
from rag_utils_langchain import (
    index_documents_langchain,
    search_documents_langchain,
    search_web_langchain,
    get_langchain_retriever,
    get_file_chunks,
    load_usage_history,
    save_usage_entry,
    get_collection_diagnostics,
)

# ── Constants ──────────────────────────────────────────────────────────────────
BASE_URL   = os.environ["SCALEWAY_BASE_URL"]
API_KEY    = os.environ["SCALEWAY_API_KEY"]
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")


# ── Token counting utilities ──────────────────────────────────────────────────
def _estimate_tokens(text: str) -> int:
    """Rough estimate of token count (approximately 1 token per 4 chars)."""
    return len(text) // 4

def _trim_context(context_text: str, max_tokens: int = 8000) -> str:
    """Trim context to fit within token budget."""
    if not context_text:
        return ""
    
    # Estimate current tokens
    tokens = _estimate_tokens(context_text)
    if tokens <= max_tokens:
        return context_text
    
    # Progressively remove chunks until we fit
    chunks = context_text.split("\n\n")
    trimmed = []
    current_tokens = 0
    
    for chunk in chunks:
        chunk_tokens = _estimate_tokens(chunk)
        if current_tokens + chunk_tokens <= max_tokens:
            trimmed.append(chunk)
            current_tokens += chunk_tokens
        else:
            break
    
    return "\n\n".join(trimmed) if trimmed else chunks[0][:max_tokens*4]  # Fallback to first chunk

# ── LangChain LLM Setup ────────────────────────────────────────────────────────
# Create a LangChain-compatible LLM that points to Scaleway's OpenAI-compatible API
@st.cache_resource
def _get_langchain_llm(model_name: str):
    """Create a LangChain ChatOpenAI instance for the given model."""
    return ChatOpenAI(
        model=model_name,
        temperature=0.4,
        top_p=0.95,
        max_tokens=2048,
        openai_api_base=BASE_URL,
        openai_api_key=API_KEY,
        streaming=False,  # We handle streaming with the direct OpenAI client
    )


# ── OpenAI client (for streaming) ──────────────────────────────────────────────
from openai import OpenAI
@st.cache_resource
def _get_openai_client():
    """Create and cache the OpenAI client."""
    return OpenAI(base_url=BASE_URL, api_key=API_KEY)

client = _get_openai_client()

# The list of AI models the user can choose from in the sidebar.
MODELS = [
    "devstral-2-123b-instruct-2512",
    "qwen3.5-397b-a17b",
    "mistral-small-3.2-24b-instruct-2506"
]

# Tasks supported by each model — shown above the dropdown as a caption.
MODEL_LABELS = {
    "devstral-2-123b-instruct-2512":       "Chat & Code",
    "qwen3.5-397b-a17b":                   "Chat & Code",
    "mistral-small-3.2-24b-instruct-2506": "Chat & Vision",
}

# ── Persistent settings management ─────────────────────────────────────────────
import json
import chromadb

_CHROMA_DIR = os.path.join(_ROOT, "chroma_db")
_SETTINGS_COLLECTION_NAME = "chat_settings"

def _get_settings_collection():
    """Get the ChromaDB collection for chat settings."""
    client = chromadb.PersistentClient(path=_CHROMA_DIR)
    return client.get_or_create_collection(name=_SETTINGS_COLLECTION_NAME)

def _load_persistent_settings():
    """Load settings like model, system prompt, and web search toggle from ChromaDB."""
    default_settings = {
        "selected_model": MODELS[0],
        "system_prompt": "You are a helpful assistant.",
        "dropbox_context_enabled": True,
        "msg_area": "",
    }
    try:
        result = _get_settings_collection().get(ids=["chat_settings"])
        if result and result["metadatas"] and result["metadatas"][0]:
            saved = result["metadatas"][0]
            # Validate that model is still in available models list
            if saved.get("selected_model") not in MODELS:
                saved["selected_model"] = MODELS[0]
            # Convert dropbox_context_enabled string back to boolean
            if "dropbox_context_enabled" in saved:
                saved["dropbox_context_enabled"] = saved["dropbox_context_enabled"].lower() in ("true", "1", "yes")
            return {**default_settings, **saved}
        return default_settings
    except Exception as e:
        logger.warning("Failed to load persistent settings from ChromaDB: %s", str(e))
        return default_settings

def _save_persistent_settings():
    """Save current settings (model, system prompt, web search toggle, msg_area) to ChromaDB."""
    settings = {
        "selected_model": st.session_state.get("selected_model", MODELS[0]),
        "system_prompt": st.session_state.get("system_prompt", "You are a helpful assistant."),
        "dropbox_context_enabled": str(st.session_state.get("dropbox_context_enabled", False)).lower(),
        "msg_area": st.session_state.get("msg_area", ""),
    }
    try:
        _get_settings_collection().upsert(
            ids=["chat_settings"],
            documents=["chat_settings"],  # ChromaDB requires a non-empty document
            metadatas=[settings],
        )
        logger.info("Persistent settings saved to ChromaDB")
    except Exception as e:
        logger.warning("Failed to save persistent settings to ChromaDB: %s", str(e))

# ── Session state defaults ─────────────────────────────────────────────────────
# st.session_state is a dictionary Streamlit keeps alive between re-runs for the
# same browser tab. Without it, every click would wipe all data.
# The "not in" check ensures we only initialise each key once on first load.

# Load persistent settings from disk on first app run
_persistent_settings = _load_persistent_settings()

# messages: the full conversation so far — a list of dicts, e.g.:
#   {"role": "user",      "content": "Hello!"}
#   {"role": "assistant", "content": "Hi there!"}
if "messages" not in st.session_state:
    st.session_state.messages = []

# usage_history: list of token-count dicts, one entry per API response.
# Each entry: {"input_tokens": int, "output_tokens": int, "timestamp": datetime}
# Loaded from disk on first run so data survives app restarts.
@st.cache_resource
def _load_usage_history_cached():
    return load_usage_history()

if "usage_history" not in st.session_state:
    st.session_state.usage_history = _load_usage_history_cached()

# docs_indexed: index uploaded files once per server process in a background
# thread so the page renders immediately without waiting for ONNX inference.
if "docs_indexed" not in st.session_state:
    threading.Thread(
        target=index_documents_langchain,
        args=(UPLOAD_DIR,),
        daemon=True
    ).start()
    st.session_state.docs_indexed = True

# msg_area: the current text in the chat input area. Stored in session_state so
# the Files modal can programmatically append a filename before re-rendering.
if "msg_area" not in st.session_state:
    st.session_state.msg_area = _persistent_settings["msg_area"]

# selected_model: restore from persistent settings
if "selected_model" not in st.session_state:
    st.session_state.selected_model = _persistent_settings["selected_model"]

# system_prompt: restore from persistent settings
if "system_prompt" not in st.session_state:
    st.session_state.system_prompt = _persistent_settings["system_prompt"]

# dropbox_context_enabled: restore from persistent settings
if "dropbox_context_enabled" not in st.session_state:
    st.session_state.dropbox_context_enabled = _persistent_settings["dropbox_context_enabled"]

# ── Files modal ───────────────────────────────────────────────────────────────
# @st.dialog renders a modal overlay. When a filename button is clicked we
# append the name to msg_area and call st.rerun() which closes the modal and
# returns focus to the chat page with the updated text area content.
@st.dialog("📁 Files")
def files_modal():
    files = sorted(f for f in os.listdir(UPLOAD_DIR) if os.path.isfile(os.path.join(UPLOAD_DIR, f)))
    if not files:
        st.warning(
            "📁 **No files uploaded**\n\n"
            "Please go to the **DropBox** page to upload your files (PDF, DOCX, TXT, XLSX)."
        )
        return
    for fname in files:
        if st.button(fname, use_container_width=True, key=f"file_modal_{fname}"):
            logger.info("file_selected=%s", fname)
            current = st.session_state.get("msg_area", "")
            sep = " " if current.strip() else ""
            st.session_state.msg_new_value = current + sep + fname
            # Automatically activate DropBox context when a file is selected
            st.session_state.dropbox_context_enabled = True
            _save_persistent_settings()
            st.rerun()


# ── Reduce sidebar top padding ────────────────────────────────────────────────
# Streamlit adds a large gap at the top of the sidebar by default.
# We inject a small CSS snippet to shrink it to 1 rem (~16 px).
# unsafe_allow_html=True is required whenever we pass raw HTML/CSS to Streamlit.
@st.cache_resource
def _inject_css():
    st.markdown(
        "<style>"
        "section[data-testid='stSidebar'] > div:first-child { padding-top: 0.25rem; }"
        "[data-testid='stSidebarHeader'] { display: none; }"
        "[data-testid='stAppDeployButton'] { display: none; }"
        "footer { display: none; }"
        ".stMenuVersionCopyButton { display: none; }"
        "html, body, [class*='css'] { font-size: 18px; }"
        ".stMarkdown p, .stMarkdown li { font-size: 1.1rem; }"
        ".stChatMessage p { font-size: 1.1rem; }"
        "[data-testid='stSidebarNav'] a { font-size: 1.05rem; }"
        "section[data-testid='stSidebar'] textarea { font-size: 0.7rem; line-height: 1.2; }"
        "section[data-testid='stSidebar'] .stToggle label p { font-size: 0.78rem !important; }"
        "section[data-testid='stSidebar'] .stButton button { font-size: 0.78rem !important; }"
        "section[data-testid='stSidebar'] .stExpander summary { font-size: 0.85rem !important; }"
        "section[data-testid='stSidebar'] .stExpander [data-testid='stExpanderDetails'] { padding: 0.25rem 0.5rem; }"
        "[data-testid='stSidebarNav'] { display: none; }"
        "</style>",
        unsafe_allow_html=True,
    )

_inject_css()

# ── System Prompts ─────────────────────────────────────────────────────────────
_DROPBOX_SYSTEM_PROMPT = (
    "You are my personal assistant specialized in managing and understanding documents stored in my Dropbox.\n\n"
    "Your role is to:\n"
    "- Retrieve, organize, and summarize documents based on my requests\n"
    "- Maintain context across multiple files and conversations\n"
    "- Extract key information, insights, and action items\n"
    "- Answer questions using only the relevant document context when available\n"
    "- Be concise, accurate, and structured in responses\n\n"
    "If information is missing or unclear, ask clarifying questions before proceeding.\n"
    "Always prioritize relevance, privacy, and correctness."
)

_INTERNET_SYSTEM_PROMPT = (
    "You are my personal assistant specialized in understanding and analyzing information from the Internet.\n\n"
    "Your role is to:\n"
    "- Search, retrieve, and summarize relevant online information\n"
    "- Evaluate sources for credibility and accuracy\n"
    "- Provide clear, concise, and structured answers\n"
    "- Synthesize insights from multiple sources when needed\n"
    "- Highlight uncertainty or conflicting information\n\n"
    "Always prioritize relevance, reliability, and up-to-date information. Ask clarifying questions if the request is ambiguous."
)

_DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."

# ── Sidebar ────────────────────────────────────────────────────────────────────
# Everything indented inside "with st.sidebar:" is rendered in the left panel.
with st.sidebar:

    # ── Navigation dropdown ────────────────────────────────────────────────────
    _PAGES = {"💬 Chat": "Chat.py", "📁 DropBox": "pages/DropBox.py", "📋 Logs": "pages/Logs.py"}
    _nav = st.selectbox("Page", list(_PAGES.keys()), index=0, label_visibility="collapsed")
    if _nav != "💬 Chat":
        st.switch_page(_PAGES[_nav])

    # ── Pre-render logic (must run before any widget) ──────────────────────────
    # Dynamically update system prompt display based on DropBox Context toggle state.
    # This must precede the System Prompt expander since it writes to session_state.system_prompt.
    _current_dropbox_state = st.session_state.get("dropbox_context_enabled", False)
    _prev_dropbox_state_for_prompt = st.session_state.get("_dropbox_state_for_prompt", False)
    if _current_dropbox_state != _prev_dropbox_state_for_prompt:
        if _current_dropbox_state:
            st.session_state.system_prompt = _DROPBOX_SYSTEM_PROMPT
        else:
            st.session_state.system_prompt = _INTERNET_SYSTEM_PROMPT
        st.session_state._dropbox_state_for_prompt = _current_dropbox_state

    # Apply any pending reset (from the clear button) BEFORE the widget is
    # instantiated — Streamlit forbids changing widget-bound keys after render.
    if "system_prompt_reset" in st.session_state:
        st.session_state.system_prompt = st.session_state.pop("system_prompt_reset")
    if "system_prompt" not in st.session_state:
        st.session_state.system_prompt = _DROPBOX_SYSTEM_PROMPT

    # ── Model ──────────────────────────────────────────────────────────────────
    with st.expander("🤖 Model", expanded=True):
        _tasks = MODEL_LABELS.get(st.session_state.get("selected_model", MODELS[0]), "Chat & Code")
        selected_model = st.selectbox(
            f"Tasks: {_tasks}",
            MODELS,
            key="selected_model",
        )
        if st.session_state.get("selected_model") != st.session_state.get("_prev_model"):
            logger.info("model_selected=%s", selected_model)
            st.session_state._prev_model = st.session_state.get("selected_model")
            _save_persistent_settings()

    # ── System Prompt ──────────────────────────────────────────────────────────
    with st.expander("📝 System Prompt", expanded=False):
        system_prompt = st.text_area(
            "System prompt",
            key="system_prompt",
            height=120,
        )
        if system_prompt != st.session_state.get("_prev_system_prompt"):
            st.session_state._prev_system_prompt = system_prompt
            _save_persistent_settings()

    # ── Context ────────────────────────────────────────────────────────────────
    with st.expander("🌐 Context", expanded=True):
        dropbox_context_enabled = st.toggle(
            "DropBox Context",
            key="dropbox_context_enabled"
        )
        if dropbox_context_enabled != st.session_state.get("_prev_dropbox_context"):
            logger.info("dropbox_context_toggled=%s", dropbox_context_enabled)
            st.session_state._prev_dropbox_context = dropbox_context_enabled
            _save_persistent_settings()
        if st.button("🗑️ Clear context", use_container_width=True):
            logger.info("conversation_cleared=true")
            st.session_state.messages = []
            st.session_state.system_prompt_reset = _DEFAULT_SYSTEM_PROMPT
            st.session_state.msg_new_value = ""
            _save_persistent_settings()
            st.rerun()

    # ── Token Usage ────────────────────────────────────────────────────────────
    with st.expander("📊 Token Usage", expanded=False):
        _history = st.session_state.usage_history
        _last    = _history[-1] if _history else None
        _total_in  = sum(e["input_tokens"]  for e in _history)
        _total_out = sum(e["output_tokens"] for e in _history)

        _ts = _last["timestamp"].strftime("%Y-%m-%d %H:%M:%S") if _last else ""
        _li = _last["input_tokens"]  if _last else "—"
        _lo = _last["output_tokens"] if _last else "—"
        _ci = _total_in  if _history else "—"
        _co = _total_out if _history else "—"
        st.markdown(
            f"""<div style="font-size:0.85rem;line-height:1.7;color:inherit">
            <b>Last response tokens</b><br>
            {f'{_ts}<br>' if _ts else ""}
            In&nbsp;<b>{_li}</b> &nbsp;·&nbsp; Out&nbsp;<b>{_lo}</b><br><br>
            <b>Cumulative tokens</b><br>
            In&nbsp;<b>{_ci}</b> &nbsp;·&nbsp; Out&nbsp;<b>{_co}</b>
            </div>""",
            unsafe_allow_html=True,
        )

# ── Page header ────────────────────────────────────────────────────────────────
st.title("💬 Graphtrek AI Chat")
# st.caption renders smaller, dimmer text — good for secondary info.
st.caption(f"Model: `{selected_model}`")

# ── Render existing messages ───────────────────────────────────────────────────
# Loop through the saved conversation and redraw every message bubble.
# st.chat_message("user")      → right-aligned user bubble
# st.chat_message("assistant") → left-aligned AI bubble
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant":
            _src = msg.get("source")
            _mdl = msg.get("model", "")
            _mdl_tag = f" · `{_mdl}`" if _mdl else ""
            if _src == "files":
                st.caption(f"📁 Answered from your uploaded files{_mdl_tag}")
            elif _src == "web":
                st.caption(f"🌐 Answered from internet search{_mdl_tag}")
                _sources = msg.get("web_sources")
                if _sources:
                    _links = " · ".join(
                        f"[{s['title'][:50]}]({s['link']})" for s in _sources
                    )
                    st.caption(f"Sources: {_links}")
            else:
                st.caption(f"🤖 Answered by model{_mdl_tag}")

# ── Chat input ─────────────────────────────────────────────────────────────────
# text_area is used instead of chat_input so that the Files modal can inject
# a filename into the field programmatically via session_state.
# Apply any pending value (from Files modal or post-send clear) BEFORE the
# widget is instantiated — Streamlit forbids changing widget state after render.
if "msg_new_value" in st.session_state:
    st.session_state.msg_area = st.session_state.pop("msg_new_value")

st.text_area(
    "Üzenet",
    key="msg_area",
    height=80,
    label_visibility="collapsed",
    placeholder="Send a message…",
)

# Save msg_area changes to disk when it's modified
if st.session_state.get("msg_area") != st.session_state.get("_prev_msg_area"):
    st.session_state._prev_msg_area = st.session_state.get("msg_area")
    _save_persistent_settings()

col_send, col_clear, col_files = st.columns([2, 2, 2])
with col_files:
    if st.button("📁 Files", use_container_width=True):
        files_modal()
with col_clear:
    if st.button("🗑️ Clear chat", use_container_width=True, help="Clear chat"):
        st.session_state.msg_new_value = ""
        _save_persistent_settings()
        st.rerun()
with col_send:
    send_clicked = st.button("📤 Send message", use_container_width=True, type="primary")

user_input = None
if send_clicked and st.session_state.get("msg_area", "").strip():
    user_input = st.session_state.msg_area.strip()
    st.session_state.msg_new_value = ""  # applied on next rerun, before widget renders
    _save_persistent_settings()  # Save with cleared msg_area

if user_input:
    # 1) Save the user's message to history and show it immediately as a bubble.
    logger.info("user_message=%r, model=%s", user_input[:100], selected_model)
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # 2) Retrieve context using LangChain retriever and web search
    doc_chunks = None
    source = "model"
    
    logger.info("dropbox_context_enabled=%s, user_input=%r", st.session_state.get("dropbox_context_enabled", False), user_input[:100])
    
    # Check if DropBox context is active but no files are uploaded
    if st.session_state.get("dropbox_context_enabled", False):
        files_in_upload = []
        if os.path.isdir(UPLOAD_DIR):
            files_in_upload = [f for f in os.listdir(UPLOAD_DIR) if os.path.isfile(os.path.join(UPLOAD_DIR, f))]
        
        if not files_in_upload:
            logger.warning("dropbox_context_enabled_but_no_files=true")
            with st.chat_message("assistant"):
                st.warning(
                    "📁 **DropBox Context is active but no files uploaded**\n\n"
                    "Please upload files in the **DropBox** page to enable semantic search on your documents.\n\n"
                    "Steps:\n"
                    "1. Go to **📁 DropBox** page\n"
                    "2. Upload your files (PDF, DOCX, TXT, XLSX)\n"
                    "3. Wait for indexing to complete\n"
                    "4. Return here and ask your question"
                )
                st.caption(f"🤖 · `{selected_model}`")
            st.session_state.messages.append({"role": "assistant", "content": "📁 DropBox Context is active but no files uploaded. Please upload files in the DropBox page.", "source": "system", "model": selected_model})
            st.rerun()
    
    # Check if user mentioned one or more specific files
    file_sections = []  # list of labelled strings, one per matched file
    if os.path.isdir(UPLOAD_DIR):
        for _fname in sorted(os.listdir(UPLOAD_DIR)):
            fpath = os.path.join(UPLOAD_DIR, _fname)
            if os.path.isfile(fpath) and _fname.lower() in user_input.lower():
                file_chunks = get_file_chunks(_fname)
                if file_chunks:
                    chunk_count = len(file_chunks)
                    token_count = sum(_estimate_tokens(c) for c in file_chunks)
                    logger.info(
                        "FILE CONTEXT | file=%-40s | chunks=%4d | tokens=%6d",
                        _fname, chunk_count, token_count,
                    )
                    section = f"=== FILE: {_fname} ===\n" + "\n\n".join(file_chunks)
                    file_sections.append(section)
                else:
                    logger.warning("FILE CONTEXT | file=%-40s | no chunks found in index", _fname)
        if file_sections:
            total_chunks = sum(s.count("\n\n") + 1 for s in file_sections)
            total_tokens = sum(_estimate_tokens(s) for s in file_sections)
            logger.info(
                "FILE CONTEXT | TOTAL files=%d | chunks≈%d | tokens=%d",
                len(file_sections), total_chunks, total_tokens,
            )
            doc_chunks = file_sections  # one entry per file, already joined
            source = "files"
    
    # If no specific file mentioned and DropBox context is active,
    # use ChromaDB semantic search
    if not doc_chunks and st.session_state.get("dropbox_context_enabled", False):
        logger.info("DropBox context active - attempting semantic search on ChromaDB")
        try:
            retrieved = search_documents_langchain(user_input, k=4)
            if retrieved:
                doc_chunks = retrieved
                source = "files"
                logger.info("DropBox context search successful, retrieved %d chunks", len(doc_chunks))
            else:
                logger.warning("DropBox context search returned no results for query: %r", user_input[:100])
        except Exception as e:
            logger.error("DropBox context search failed: %s", str(e), exc_info=True)

    # Web search — only when DropBox context is inactive
    web_results = None
    web_sources = None
    web_search_failed = False
    if not st.session_state.get("dropbox_context_enabled", False):
        try:
            web_results, web_sources = search_web_langchain(user_input)
            if web_results:
                logger.info("web_search_completed=true, result_length=%s", len(str(web_results)))
            else:
                logger.warning("web_search_returned_empty=true")
                web_search_failed = True
        except Exception as e:
            logger.info("web_search_failed=%s", str(e))
            web_search_failed = True
    
    # Combine doc chunks and web results, trimming to fit token budget
    context_parts = []
    if doc_chunks:
        if isinstance(doc_chunks, list):
            context_parts.append("\n\n".join(doc_chunks))
        else:
            context_parts.append(str(doc_chunks))
    
    if web_results:
        # Trim web results to ~4000 tokens max
        trimmed_web = _trim_context(web_results, max_tokens=4000)
        context_parts.append(trimmed_web)
        source = "web" if web_results else source
    
    context_text = "\n\n".join(context_parts) if context_parts else None

    # Per-file sections are already labelled; ensure each file is represented
    # even when trim kicks in by splitting the budget equally across files.
    if file_sections:
        per_file_budget = 50_000 // max(len(file_sections), 1)
        trimmed_sections = [_trim_context(s, max_tokens=per_file_budget) for s in file_sections]
        context_text = "\n\n".join(trimmed_sections + ([_trim_context(web_results, max_tokens=4000)] if web_results else []))

    # 3) Build the full message list to send to the API.
    #    Augment the system prompt with the retrieved context (if any) so the
    #    model can ground its answer in the user's files or a live web search.
    if st.session_state.get("dropbox_context_enabled", False):
        augmented_system_prompt = _DROPBOX_SYSTEM_PROMPT
    else:
        augmented_system_prompt = _INTERNET_SYSTEM_PROMPT
    if context_text:
        # Allow up to 50 000 tokens for context (model window is 262 144;
        # conversation history + system prompt + reply fit in the remainder)
        trimmed_context = _trim_context(context_text, max_tokens=50_000)
        augmented_system_prompt += (
            "\n\nUse the following context to answer the user's question:\n\n"
            + trimmed_context
        )
    elif not st.session_state.get("dropbox_context_enabled", False):
        # Web search failed or returned no results — fall back to training knowledge
        augmented_system_prompt += (
            "\n\nNote: No web search results are available for this query. "
            "Answer based on your training knowledge and clearly indicate that "
            "this information may not reflect the most recent state."
        )
    
    # Build conversation history with sliding window to avoid token overflow
    # Keep more recent messages, drop older ones if needed
    conversation_msgs = st.session_state.messages
    
    # Estimate total tokens: system prompt + context + conversation
    system_tokens = _estimate_tokens(augmented_system_prompt)
    max_input_tokens = 245000  # Conservative limit (262144 - 2048 - buffer)
    
    # Keep recent ~40 messages (last ~100k tokens of conversation)
    if len(conversation_msgs) > 40:
        conversation_msgs = conversation_msgs[-40:]
    
    api_messages = [{"role": "system", "content": augmented_system_prompt}] + conversation_msgs
    
    # One more safety check: if we're still over budget, trim oldest user messages
    total_tokens = _estimate_tokens(str(api_messages))
    if total_tokens > max_input_tokens - 1000:  # Leave 1000 token buffer
        logger.warning("Token budget exceeded (%d), trimming conversation history", total_tokens)
        # Keep system + recent 20 messages
        api_messages = [api_messages[0]] + conversation_msgs[-20:]

    # 4) Stream the AI response token by token.
    with st.chat_message("assistant"):
        if web_search_failed:
            st.info("⚠️ Web search unavailable — answering from training knowledge.", icon="🔌")
        # st.empty() creates a placeholder we can update on every new token.
        placeholder = st.empty()
        full_text = ""  # accumulates the complete reply as tokens arrive

        # stream=True sends the response in small chunks instead of waiting
        # for the full reply. stream_options asks for token counts in the
        # final chunk.
        _est = _estimate_tokens(str(api_messages))
        logger.info("api_call_initiated=true, api_messages_count=%d, est_tokens=%d, source=%s",
                   len(api_messages), _est, source)

        try:
            stream = client.chat.completions.create(
                model=selected_model,
                messages=api_messages,
                max_tokens=4096,
                temperature=0.4,   # higher = more creative / random answers
                top_p=0.95,         # nucleus sampling: consider only top 95% probable tokens
                stream=True,
                stream_options={"include_usage": True},
            )

            # Each iteration receives one small chunk (a few tokens) from the API.
            for chunk in stream:
                # chunk.choices contains the new token(s). We guard against an
                # empty choices list (which happens on the final usage-only chunk).
                if chunk.choices and chunk.choices[0].delta.content:
                    full_text += chunk.choices[0].delta.content
                    # Show a blinking-cursor character "▌" while typing is in progress,
                    # then overwrite the placeholder with the updated text.
                    placeholder.markdown(full_text + "▌")

                # The very last chunk has no new tokens but carries usage statistics.
                if chunk.usage:
                    entry = {
                        "input_tokens":  chunk.usage.prompt_tokens,
                        "output_tokens": chunk.usage.completion_tokens,
                        "timestamp":     datetime.now(),
                    }
                    logger.info("response_completed=true, input_tokens=%s, output_tokens=%s, source=%s",
                               entry["input_tokens"], entry["output_tokens"], source)
                    st.session_state.usage_history.append(entry)
                    save_usage_entry(
                        entry["input_tokens"],
                        entry["output_tokens"],
                        entry["timestamp"],
                    )
        except Exception as api_err:
            logger.error("api_call_failed=%s, est_tokens=%d", str(api_err), _est, exc_info=True)
            full_text = f"⚠️ API error: {api_err}"
            placeholder.warning(full_text)

        # Remove the cursor and display the final clean text.
        # Log warning if response is empty and use warning message as content
        if not full_text or not full_text.strip():
            logger.warning("empty_response=true, source=%s, user_input=%r, context_available=%s", 
                         source, user_input[:100], context_text is not None)
            warning_message = (
                "⚠️ Received an empty response from the model. This could mean:\n"
                "- The model encountered an issue\n"
                "- No relevant context was found (try different keywords)\n"
                "- Try rephrasing your question"
            )
            placeholder.warning(warning_message)
            full_text = warning_message  # Save warning as content so it persists
        else:
            placeholder.markdown(full_text)
        
        if source == "files":
            st.caption(f"📁 Answered from your uploaded files · `{selected_model}`")
        elif source == "web":
            st.caption(f"🌐 Answered from internet search · `{selected_model}`")
            if web_sources:
                links = " · ".join(
                    f"[{s['title'][:50]}]({s['link']})" for s in web_sources
                )
                st.caption(f"Sources: {links}")
        else:
            st.caption(f"🤖 Answered by model · `{selected_model}`")

    # 5) Save the completed assistant reply so it becomes part of the next
    #    request's conversation history (multi-turn memory).
    #    'source' is stored so the label is preserved when history is re-rendered.
    _msg = {"role": "assistant", "content": full_text, "source": source, "model": selected_model}
    if web_sources:
        _msg["web_sources"] = web_sources
    st.session_state.messages.append(_msg)

    # Force Streamlit to re-run the script so the updated sidebar token
    # metrics are reflected immediately.
    st.rerun()