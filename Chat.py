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
)

# ── Constants ──────────────────────────────────────────────────────────────────
BASE_URL   = os.environ["SCALEWAY_BASE_URL"]
API_KEY    = os.environ["SCALEWAY_API_KEY"]
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")


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
        "web_search_enabled": True,
        "msg_area": "",
    }
    try:
        result = _get_settings_collection().get(ids=["chat_settings"])
        if result and result["metadatas"] and result["metadatas"][0]:
            saved = result["metadatas"][0]
            # Validate that model is still in available models list
            if saved.get("selected_model") not in MODELS:
                saved["selected_model"] = MODELS[0]
            # Convert web_search_enabled string back to boolean
            if "web_search_enabled" in saved:
                saved["web_search_enabled"] = saved["web_search_enabled"].lower() in ("true", "1", "yes")
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
        "web_search_enabled": str(st.session_state.get("web_search_enabled", True)).lower(),
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

# web_search_enabled: restore from persistent settings
if "web_search_enabled" not in st.session_state:
    st.session_state.web_search_enabled = _persistent_settings["web_search_enabled"]

# ── Files modal ───────────────────────────────────────────────────────────────
# @st.dialog renders a modal overlay. When a filename button is clicked we
# append the name to msg_area and call st.rerun() which closes the modal and
# returns focus to the chat page with the updated text area content.
@st.dialog("📁 Files")
def files_modal():
    files = sorted(f for f in os.listdir(UPLOAD_DIR) if os.path.isfile(os.path.join(UPLOAD_DIR, f)))
    if not files:
        st.info("Nincs feltöltött fájl.")
        return
    for fname in files:
        if st.button(fname, use_container_width=True, key=f"file_modal_{fname}"):
            logger.info("file_selected=%s", fname)
            current = st.session_state.get("msg_area", "")
            sep = " " if current.strip() else ""
            st.session_state.msg_new_value = current + sep + fname
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
        "</style>",
        unsafe_allow_html=True,
    )

_inject_css()

# ── Sidebar ────────────────────────────────────────────────────────────────────
# Everything indented inside "with st.sidebar:" is rendered in the left panel.
with st.sidebar:
    st.title("⚙️ Settings")

    # The selectbox label shows the tasks supported by the currently selected model.
    # We read from session_state so it updates immediately when the user switches.
    _tasks = MODEL_LABELS.get(st.session_state.get("selected_model", MODELS[0]), "Chat & Code")
    selected_model = st.selectbox(
        f"Model: {_tasks}",
        MODELS,
        key="selected_model",
    )
    if st.session_state.get("selected_model") != st.session_state.get("_prev_model"):
        logger.info("model_selected=%s", selected_model)
        st.session_state._prev_model = st.session_state.get("selected_model")
        _save_persistent_settings()

    # st.text_area is a multi-line text box. The system prompt instructs the AI
    # how to behave before the user's first message.
    # Apply any pending reset (from the clear button) BEFORE the widget is
    # instantiated — Streamlit forbids changing widget-bound keys after render.
    _DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."
    if "system_prompt_reset" in st.session_state:
        st.session_state.system_prompt = st.session_state.pop("system_prompt_reset")
    if "system_prompt" not in st.session_state:
        st.session_state.system_prompt = _DEFAULT_SYSTEM_PROMPT
    system_prompt = st.text_area(
        "System prompt",
        key="system_prompt",
        height=120,
    )
    # Save system prompt changes to disk
    if system_prompt != st.session_state.get("_prev_system_prompt"):
        st.session_state._prev_system_prompt = system_prompt
        _save_persistent_settings()

    # Toggle for enabling/disabling internet search.
    web_search_enabled = st.toggle(
        "🌐 Internetes keresés",
        key="web_search_enabled"
    )
    if web_search_enabled != st.session_state.get("_prev_web_search"):
        logger.info("web_search_toggled=%s", web_search_enabled)
        st.session_state._prev_web_search = web_search_enabled
        _save_persistent_settings()

    # When this button is clicked, we reset all conversation data AND the system
    # prompt (model memory) back to defaults, then rerun to refresh the UI.
    if st.button("🗑️ Clear conversation", use_container_width=True):
        logger.info("conversation_cleared=true")
        st.session_state.messages = []
        st.session_state.system_prompt_reset = _DEFAULT_SYSTEM_PROMPT
        st.session_state.msg_area = ""
        _save_persistent_settings()
        st.rerun()

    # st.divider() draws a horizontal line to visually separate sections.
    st.divider()

    # ── Token usage metrics ────────────────────────────────────────────────────
    # st.metric renders a labelled number widget (large value + label).
    # We show "—" when no data is available yet.

    _history = st.session_state.usage_history
    _last    = _history[-1] if _history else None
    _total_in  = sum(e["input_tokens"]  for e in _history)
    _total_out = sum(e["output_tokens"] for e in _history)

    st.subheader("Last response tokens")
    if _last:
        st.caption(_last["timestamp"].strftime("%Y-%m-%d %H:%M:%S"))
    col1, col2 = st.columns(2)
    col1.metric("Input",  _last["input_tokens"]  if _last else "—")
    col2.metric("Output", _last["output_tokens"] if _last else "—")

    st.subheader("Cumulative tokens")
    col3, col4 = st.columns(2)
    col3.metric("Input",  _total_in  if _history else "—")
    col4.metric("Output", _total_out if _history else "—")

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

col_send, col_clear, col_files = st.columns([3, 1, 1])
with col_files:
    if st.button("📁 Files", use_container_width=True):
        files_modal()
with col_clear:
    if st.button("🗑️", use_container_width=True, help="Clear text area"):
        st.session_state.msg_area = ""
        _save_persistent_settings()
        st.rerun()
with col_send:
    send_clicked = st.button("📤 Küldés", use_container_width=True, type="primary")

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
    
    # Check if user mentioned a specific file
    if os.path.isdir(UPLOAD_DIR):
        for _fname in sorted(os.listdir(UPLOAD_DIR)):
            fpath = os.path.join(UPLOAD_DIR, _fname)
            if os.path.isfile(fpath) and _fname.lower() in user_input.lower():
                doc_chunks = get_file_chunks(_fname)
                logger.info("file_context_retrieved=%s, chunks_count=%s", _fname, len(doc_chunks) if doc_chunks else 0)
                source = "files"
                break
    
    # If no specific file mentioned, use semantic search with LangChain retriever
    # if not doc_chunks:
    #     try:
    #         retrieved = search_documents_langchain(user_input, k=4)
    #         if retrieved:
    #             doc_chunks = retrieved
    #             source = "files"
    #     except Exception:
    #         pass
    
    # Web search fallback or enhancement
    web_results = None
    if web_search_enabled:
        try:
            web_results = search_web_langchain(user_input)
            if web_results:
                logger.info("web_search_completed=true, result_length=%s", len(str(web_results)))
        except Exception as e:
            logger.info("web_search_failed=%s", str(e))
    
    # Combine doc chunks and web results
    context_parts = []
    if doc_chunks:
        if isinstance(doc_chunks, list):
            context_parts.append("\n\n".join(doc_chunks))
        else:
            context_parts.append(str(doc_chunks))
    
    if web_results:
        context_parts.append(web_results)
        source = "web" if web_results else source
    
    context_text = "\n\n".join(context_parts) if context_parts else None

    # 3) Build the full message list to send to the API.
    #    Augment the system prompt with the retrieved context (if any) so the
    #    model can ground its answer in the user's files or a live web search.
    augmented_system_prompt = system_prompt
    if context_text:
        augmented_system_prompt += (
            "\n\nUse the following context to answer the user's question:\n\n"
            + context_text
        )
    api_messages = [{"role": "system", "content": augmented_system_prompt}] + st.session_state.messages

    # 4) Stream the AI response token by token.
    with st.chat_message("assistant"):
        # st.empty() creates a placeholder we can update on every new token.
        placeholder = st.empty()
        full_text = ""  # accumulates the complete reply as tokens arrive

        # stream=True sends the response in small chunks instead of waiting
        # for the full reply. stream_options asks for token counts in the
        # final chunk.
        stream = client.chat.completions.create(
            model=selected_model,
            messages=api_messages,
            max_tokens=2048,
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

        # Remove the cursor and display the final clean text.
        placeholder.markdown(full_text)
        if source == "files":
            st.caption(f"📁 Answered from your uploaded files · `{selected_model}`")
        elif source == "web":
            st.caption(f"🌐 Answered from internet search · `{selected_model}`")
        else:
            st.caption(f"🤖 Answered by model · `{selected_model}`")

    # 5) Save the completed assistant reply so it becomes part of the next
    #    request's conversation history (multi-turn memory).
    #    'source' is stored so the label is preserved when history is re-rendered.
    st.session_state.messages.append({"role": "assistant", "content": full_text, "source": source, "model": selected_model})

    # Force Streamlit to re-run the script so the updated sidebar token
    # metrics are reflected immediately.
    st.rerun()