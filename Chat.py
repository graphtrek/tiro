# =============================================================================
# Chat.py — Main Streamlit entry point for NothingGetsOutAI
#
# Streamlit re-runs this entire script from top to bottom on every user
# interaction. All state that must survive between clicks is stored in
# st.session_state (a per-tab dictionary Streamlit keeps alive).
#
# Business logic is organised into focused classes in the helpers/ package:
#   helpers/chat_config.py    — AppConfig, cached LLM client factories
#   helpers/chat_prompts.py   — SystemPrompts
#   helpers/chat_utils.py     — MessageUtils  (token budget, message format)
#   helpers/chat_settings.py  — SettingsManager (ChromaDB persistence)
#   helpers/chat_context.py   — ContextBuilder (RAG + web search + API msgs)
#   helpers/chat_handlers.py  — GmailHandler, StreamHandler
#   helpers/chat_ui.py        — ChatUI, files_modal()
# =============================================================================

import warnings
warnings.filterwarnings("ignore", message="Core Pydantic V1 functionality")

import base64
import logging
import os
import threading

import streamlit as st
from dotenv import load_dotenv

# ── Page config — must be the very first Streamlit call ──────────────────────
st.set_page_config(page_title="Nothing Gets Out AI", page_icon="💬", menu_items={})

# ── Environment variables ─────────────────────────────────────────────────────
load_dotenv()

# ── Helpers ───────────────────────────────────────────────────────────────────
from helpers.chat_config   import AppConfig, get_openai_client, load_usage_history_cached
from helpers.chat_prompts  import SystemPrompts
from helpers.chat_settings import SettingsManager
from helpers.chat_context  import ContextBuilder
from helpers.chat_handlers import GmailHandler, DriveHandler, StreamHandler
from helpers.chat_ui       import ChatUI
from helpers.rag_utils_langchain import index_documents_langchain

# ── Logging setup ─────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    _log_fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(filename)s | %(funcName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _console = logging.StreamHandler()
    _console.setLevel(logging.INFO)
    _console.setFormatter(_log_fmt)
    logger.addHandler(_console)

    _file_h = logging.FileHandler(AppConfig.LOG_FILE)
    _file_h.setLevel(logging.INFO)
    _file_h.setFormatter(_log_fmt)
    logger.addHandler(_file_h)
    logger.propagate = False

    logging.getLogger("duckduckgo_search").setLevel(logging.DEBUG)
    logging.getLogger("urllib3").setLevel(logging.DEBUG)
    logging.getLogger("langchain_community").setLevel(logging.DEBUG)
    logging.getLogger("onnxruntime").setLevel(logging.ERROR)

logger.info("Chat.py app started")

# ── Shared OpenAI client ──────────────────────────────────────────────────────
client = get_openai_client()

# ── Session state initialisation ─────────────────────────────────────────────
_persistent = SettingsManager.load()

if "messages" not in st.session_state:
    st.session_state.messages = []

if "usage_history" not in st.session_state:
    st.session_state.usage_history = load_usage_history_cached()

if "docs_indexed" not in st.session_state:
    threading.Thread(
        target=index_documents_langchain,
        args=(AppConfig.UPLOAD_DIR,),
        daemon=True,
    ).start()
    st.session_state.docs_indexed = True

if "msg_area" not in st.session_state:
    st.session_state.msg_area = _persistent["msg_area"]

if "selected_model" not in st.session_state:
    st.session_state.selected_model = _persistent["selected_model"]

if "system_prompt" not in st.session_state:
    st.session_state.system_prompt = SystemPrompts.get_default(
        _persistent["dropbox_context_enabled"],
        _persistent["gmail_context_enabled"],
        _persistent["drive_context_enabled"],
    )

if "internet_context_enabled" not in st.session_state:
    st.session_state.internet_context_enabled = _persistent["internet_context_enabled"]

if "dropbox_context_enabled" not in st.session_state:
    st.session_state.dropbox_context_enabled = _persistent["dropbox_context_enabled"]

if "gmail_context_enabled" not in st.session_state:
    st.session_state.gmail_context_enabled = _persistent["gmail_context_enabled"]

if "drive_context_enabled" not in st.session_state:
    st.session_state.drive_context_enabled = _persistent["drive_context_enabled"]

if "_processing" not in st.session_state:
    st.session_state._processing = False

if "_pending_message" not in st.session_state:
    st.session_state._pending_message = None

if "_pending_image" not in st.session_state:
    st.session_state._pending_image = None

if "_img_uploader_rev" not in st.session_state:
    st.session_state._img_uploader_rev = 0

# ── Render UI ─────────────────────────────────────────────────────────────────
ChatUI.inject_css()

selected_model, internet_on, dropbox_on, gmail_on, drive_on = ChatUI.render_sidebar()

st.markdown("<h3 style='margin-bottom:0'>💬 Nothing Gets Out AI</h3>", unsafe_allow_html=True)
_ctx_label = (
    "DropBox" if dropbox_on else
    "Gmail"   if gmail_on  else
    "Drive"   if drive_on  else
    "Internet"
)
st.caption(f"{_ctx_label}: {AppConfig.get_model_label(selected_model)}")

ChatUI.render_messages()

send_clicked = ChatUI.render_input(dropbox_on, selected_model)

# ── Message dispatch ──────────────────────────────────────────────────────────
if send_clicked and st.session_state.get("msg_area", "").strip():
    st.session_state._pending_message = st.session_state.msg_area.strip()
    st.session_state._processing      = True
    st.session_state.msg_new_value    = ""
    SettingsManager.save()
    st.rerun()

if st.session_state._processing and st.session_state._pending_message:
    user_input = st.session_state._pending_message

    logger.info("user_message=%r, model=%s", user_input[:100], selected_model)

    _user_msg = {"role": "user", "content": user_input}
    _img = st.session_state.get("_pending_image")
    if _img:
        _user_msg["image_b64"]  = _img["b64"]
        _user_msg["image_name"] = _img["name"]
        logger.info("image_attached=true, name=%s", _img["name"])
    st.session_state.messages.append(_user_msg)

    with st.chat_message("user"):
        if _img:
            st.image(base64.b64decode(_img["b64"]), width=400, caption=_img["name"])
        st.markdown(user_input)

    # Gmail mode: tool-calling loop
    if gmail_on:
        logger.info("gmail_context_enabled=true, starting tool-calling loop")
        GmailHandler.handle(client, selected_model)

    # Drive mode: tool-calling loop
    if drive_on:
        logger.info("drive_context_enabled=true, starting tool-calling loop")
        DriveHandler.handle(client, selected_model)

    # DropBox guard: warn if no files are uploaded
    if dropbox_on:
        files_in_upload = []
        if os.path.isdir(AppConfig.UPLOAD_DIR):
            files_in_upload = [
                f for f in os.listdir(AppConfig.UPLOAD_DIR)
                if os.path.isfile(os.path.join(AppConfig.UPLOAD_DIR, f))
            ]
        if not files_in_upload:
            logger.warning("dropbox_context_enabled_but_no_files=true")
            with st.chat_message("assistant"):
                st.warning(
                    "📁 **A DropBox kontextus aktív, de nincs feltöltött fájl**\n\n"
                    "Kérlek, töltsd fel a fájljaidat a **DropBox** oldalon a szemantikus keresés engedélyezéséhez.\n\n"
                    "Lépések:\n"
                    "1. Menj a **📁 DropBox** oldalra\n"
                    "2. Töltsd fel a fájljaidat (PDF, DOCX, TXT, XLSX)\n"
                    "3. Várd meg az indexelés befejezését\n"
                    "4. Térj vissza ide és tedd fel a kérdésedet"
                )
                st.caption(f"🤖 · {AppConfig.get_model_label(selected_model)}")
            st.session_state.messages.append({
                "role":    "assistant",
                "content": "📁 A DropBox kontextus aktív, de nincs feltöltött fájl. Kérlek, töltsd fel a fájljaidat a DropBox oldalon.",
                "source":  "system",
                "model":   selected_model,
            })
            st.session_state._processing      = False
            st.session_state._pending_message = None
            st.rerun()

    # Regular mode: build context + stream response
    doc_chunks, dropbox_sources = ContextBuilder.build_file_context(user_input)

    web_results = web_sources = None
    web_search_failed = False
    if internet_on:
        web_results, web_sources, web_search_failed = ContextBuilder.build_web_context(user_input)

    api_messages, source = ContextBuilder.assemble_api_messages(
        doc_chunks, dropbox_sources, web_results, web_search_failed,
        st.session_state.messages,
    )

    StreamHandler.handle(
        client, selected_model, api_messages,
        source, web_sources, dropbox_sources, web_search_failed,
    )
