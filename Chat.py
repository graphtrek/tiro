# =============================================================================
# Chat.py — Main Streamlit chat interface for NothingGetsOutAI
#
# Streamlit re-runs this entire script from top to bottom on every user
# interaction. All state that must survive between clicks is stored in
# st.session_state (a per-tab dictionary Streamlit keeps alive).
# =============================================================================

# Suppress noisy Pydantic v1 deprecation warnings from LangChain internals
import warnings
warnings.filterwarnings("ignore", message="Core Pydantic V1 functionality")

# ── Standard library ──────────────────────────────────────────────────────────
import logging
import os
import threading
from datetime import datetime

# ── Third-party ───────────────────────────────────────────────────────────────
import chromadb
import streamlit as st
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from openai import OpenAI

# ── Local utilities ───────────────────────────────────────────────────────────
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

# ── Logging setup ─────────────────────────────────────────────────────────────
# The `if not logger.handlers` guard prevents duplicate log handlers when
# Streamlit re-runs the script on every user interaction.
_ROOT     = os.path.dirname(os.path.abspath(__file__))
_LOG_FILE = os.path.join(_ROOT, "ai.log")

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    _log_fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(filename)s | %(funcName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Print INFO+ messages to the terminal
    _console = logging.StreamHandler()
    _console.setLevel(logging.INFO)
    _console.setFormatter(_log_fmt)
    logger.addHandler(_console)

    # Write INFO+ messages to a shared log file (same file as rag_utils_langchain.py)
    _file_h = logging.FileHandler(_LOG_FILE)
    _file_h.setLevel(logging.INFO)
    _file_h.setFormatter(_log_fmt)
    logger.addHandler(_file_h)
    logger.propagate = False  # root logger also has a FileHandler; prevent duplicate writes

    # Verbose debug logging for the web-search stack
    logging.getLogger("duckduckgo_search").setLevel(logging.DEBUG)
    logging.getLogger("urllib3").setLevel(logging.DEBUG)
    logging.getLogger("langchain_community").setLevel(logging.DEBUG)

    # ONNX Runtime prints unhelpful provider-selection warnings; silence them
    logging.getLogger("onnxruntime").setLevel(logging.ERROR)

# ── Page configuration ────────────────────────────────────────────────────────
# st.set_page_config must be the very first Streamlit call in the script.
st.set_page_config(page_title="Nothing Gets Out AI", page_icon="💬", menu_items={})
logger.info("Chat.py app started")

# ── Environment variables ─────────────────────────────────────────────────────
load_dotenv()  # Reads .env file into os.environ (safe no-op if file is missing)

# ── Constants ─────────────────────────────────────────────────────────────────
BASE_URL   = os.environ["SCALEWAY_BASE_URL"]  # Scaleway's OpenAI-compatible endpoint
API_KEY    = os.environ["SCALEWAY_API_KEY"]   # API credentials
UPLOAD_DIR = os.path.join(_ROOT, "uploads")  # Local folder for user-uploaded files

# Models available in the sidebar dropdown
MODELS = [
    "mistral-small-3.2-24b-instruct-2506",
    "qwen3-coder-30b-a3b-instruct",
]

# Human-readable capability label shown next to each model name in the sidebar
MODEL_LABELS = {
    "mistral-small-3.2-24b-instruct-2506":  "Chat és látás",
    "qwen3-coder-30b-a3b-instruct": "Chat és kód",
}


# ── Token counting utilities ──────────────────────────────────────────────────

def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~1 token per 4 characters."""
    return len(text) // 4


def _trim_context(context_text: str, max_tokens: int = 8000) -> str:
    """
    Truncate context text to stay within a token budget.

    Splits on blank lines and drops trailing chunks until the estimated
    token count fits. Falls back to the raw first chunk if nothing fits.
    """
    if not context_text:
        return ""

    if _estimate_tokens(context_text) <= max_tokens:
        return context_text  # Already within budget — nothing to do

    chunks = context_text.split("\n\n")
    trimmed, current_tokens = [], 0
    for chunk in chunks:
        chunk_tokens = _estimate_tokens(chunk)
        if current_tokens + chunk_tokens <= max_tokens:
            trimmed.append(chunk)
            current_tokens += chunk_tokens
        else:
            break  # Adding this chunk would exceed the budget

    # If even the first chunk was too big, hard-truncate it by character count
    return "\n\n".join(trimmed) if trimmed else chunks[0][: max_tokens * 4]


# ── LLM clients ───────────────────────────────────────────────────────────────
# @st.cache_resource keeps a single instance alive across all reruns and users,
# avoiding the overhead of re-creating the client on every interaction.

@st.cache_resource
def _get_langchain_llm(model_name: str):
    """LangChain ChatOpenAI wrapper — used by RAG retrieval chains."""
    return ChatOpenAI(
        model=model_name,
        temperature=0.5,
        top_p=0.8,
        max_tokens=32768,
        openai_api_base=BASE_URL,
        openai_api_key=API_KEY,
        streaming=False,  # Streaming is handled by the direct OpenAI client below
    )


@st.cache_resource
def _get_openai_client():
    """Direct OpenAI-compatible client — used for token-by-token streaming."""
    return OpenAI(base_url=BASE_URL, api_key=API_KEY)


# Shared client instance — cached by _get_openai_client() so only one
# connection pool is created regardless of how many times Streamlit reruns.
client = _get_openai_client()


# ── Persistent settings (ChromaDB) ────────────────────────────────────────────
# User preferences (model, system prompt, context toggle…) are stored in a
# ChromaDB collection so they survive browser refreshes and server restarts.

_CHROMA_DIR               = os.path.join(_ROOT, "chroma_db")
_SETTINGS_COLLECTION_NAME = "chat_settings"


def _get_settings_collection():
    """Return the ChromaDB collection used to persist chat settings."""
    return chromadb.PersistentClient(path=_CHROMA_DIR).get_or_create_collection(
        name=_SETTINGS_COLLECTION_NAME
    )


def _load_persistent_settings() -> dict:
    """
    Load saved settings from ChromaDB.

    Returns sensible defaults when no saved settings exist or when the
    stored model name is no longer in the available MODELS list.
    """
    defaults = {
        "selected_model":          MODELS[0],
        "system_prompt":           "Te egy hasznos asszisztens vagy.",
        "dropbox_context_enabled": True,
        "msg_area":                "",
    }
    try:
        result = _get_settings_collection().get(ids=["chat_settings"])
        if result and result["metadatas"] and result["metadatas"][0]:
            saved = result["metadatas"][0]
            # Fall back to the first model if the saved one was removed from MODELS
            if saved.get("selected_model") not in MODELS:
                saved["selected_model"] = MODELS[0]
            # ChromaDB metadata stores all values as strings; convert back to bool
            if "dropbox_context_enabled" in saved:
                saved["dropbox_context_enabled"] = (
                    saved["dropbox_context_enabled"].lower() in ("true", "1", "yes")
                )
            # Migrate old English system prompts to Hungarian default
            if saved.get("system_prompt", "").startswith("You are"):
                saved["system_prompt"] = "Te egy hasznos asszisztens vagy."
            return {**defaults, **saved}
    except Exception as e:
        logger.warning("Failed to load persistent settings: %s", e)
    return defaults


def _save_persistent_settings():
    """Write current session-state settings to ChromaDB for persistence."""
    settings = {
        "selected_model":  st.session_state.get("selected_model", MODELS[0]),
        "system_prompt":   st.session_state.get("system_prompt", "Te egy hasznos asszisztens vagy."),
        # ChromaDB metadata values must be str/int/float — store bool as string
        "dropbox_context_enabled": str(
            st.session_state.get("dropbox_context_enabled", False)
        ).lower(),
        "msg_area": st.session_state.get("msg_area", ""),
    }
    try:
        _get_settings_collection().upsert(
            ids=["chat_settings"],
            documents=["chat_settings"],  # ChromaDB requires a non-empty document field
            metadatas=[settings],
        )
        logger.info("Persistent settings saved")
    except Exception as e:
        logger.warning("Failed to save persistent settings: %s", e)


# ── Cached usage history loader ───────────────────────────────────────────────
# @st.cache_resource ensures the disk read happens only once per server
# process. All browser tabs share the same cached result until the server
# restarts, which is fine because new entries are appended to session_state
# (in-memory) rather than re-read from disk.
@st.cache_resource
def _load_usage_history_cached():
    return load_usage_history()


# ── Session state initialisation ──────────────────────────────────────────────
# Each `if "key" not in st.session_state` block runs only on the very first
# page load for a given browser tab; subsequent reruns skip it.

_persistent = _load_persistent_settings()

if "messages" not in st.session_state:
    # Full conversation history: list of {"role": "user"|"assistant", "content": str, …}
    st.session_state.messages = []

if "usage_history" not in st.session_state:
    # Token-usage log, pre-loaded from disk so data survives server restarts
    st.session_state.usage_history = _load_usage_history_cached()

if "docs_indexed" not in st.session_state:
    # Run document indexing in a background daemon thread so the page renders
    # immediately without waiting for potentially slow ONNX embedding inference
    threading.Thread(
        target=index_documents_langchain,
        args=(UPLOAD_DIR,),
        daemon=True,
    ).start()
    st.session_state.docs_indexed = True

if "msg_area" not in st.session_state:
    # Restore the last draft message the user left in the input box
    st.session_state.msg_area = _persistent["msg_area"]

if "selected_model" not in st.session_state:
    st.session_state.selected_model = _persistent["selected_model"]

if "system_prompt" not in st.session_state:
    st.session_state.system_prompt = _persistent["system_prompt"]

if "dropbox_context_enabled" not in st.session_state:
    st.session_state.dropbox_context_enabled = _persistent["dropbox_context_enabled"]

if "_dropbox_state_for_prompt" not in st.session_state:
    st.session_state._dropbox_state_for_prompt = _persistent["dropbox_context_enabled"]

if "_processing" not in st.session_state:
    st.session_state._processing = False

if "_pending_message" not in st.session_state:
    st.session_state._pending_message = None


# ── Files modal ───────────────────────────────────────────────────────────────
# @st.dialog renders a pop-up overlay. Clicking a filename appends it to the
# chat input, enables DropBox context, and closes the modal via st.rerun().
@st.dialog("📁 Fájlok")
def files_modal():
    """
    Pop-up dialog that lists every file in the uploads folder.

    Clicking a filename:
      1. Appends the name to whatever the user has already typed.
      2. Turns on DropBox context automatically (so the file gets searched).
      3. Saves settings and triggers a rerun to close the dialog.
    """
    files = sorted(
        f for f in os.listdir(UPLOAD_DIR) if os.path.isfile(os.path.join(UPLOAD_DIR, f))
    )
    if not files:
        st.warning(
            "📁 **Nincs feltöltött fájl**\n\n"
            "Kérlek, menj a **DropBox** oldalra, és töltsd fel a fájljaidat (PDF, DOCX, TXT, XLSX)."
        )
        return

    for fname in files:
        if st.button(fname, use_container_width=True, key=f"file_modal_{fname}"):
            logger.info("file_selected=%s", fname)
            current = st.session_state.get("msg_area", "")
            sep = " " if current.strip() else ""
            # Append the chosen filename to whatever is already typed
            st.session_state.msg_new_value = current + sep + fname
            # Automatically activate DropBox context when a file is selected
            st.session_state.dropbox_context_enabled = True
            _save_persistent_settings()
            st.rerun()


# ── CSS injection ─────────────────────────────────────────────────────────────
# Shrinks the default sidebar top padding, hides Streamlit's deploy button and
# footer, and adjusts font sizes for a cleaner look.
# unsafe_allow_html=True is required whenever raw HTML/CSS is passed to Streamlit.
@st.cache_resource
def _inject_css():
    """
    Inject custom CSS into the Streamlit app.

    @st.cache_resource runs this only once per server process — subsequent
    reruns skip it, so the <style> tag is never written twice.

    Changes applied:
      - Removes the default large top padding from the sidebar.
      - Hides Streamlit's deploy button, footer, and auto-generated nav links.
      - Sets a consistent base font size across the whole app.
      - Slightly enlarges text in chat bubbles and markdown for readability.
      - Shrinks sidebar controls (textarea, toggles, buttons, expanders) so
        they take less vertical space.
    """
    st.markdown(
        "<style>"
        # ── Sidebar spacing ──────────────────────────────────────────────────
        "section[data-testid='stSidebar'] > div:first-child { padding-top: 0.25rem; }"
        # ── Hide default Streamlit UI chrome ─────────────────────────────────
        "[data-testid='stSidebarHeader'] { display: none; }"
        "[data-testid='stAppDeployButton'] { display: none; }"
        "footer { display: none; }"
        ".stMenuVersionCopyButton { display: none; }"
        # Hide auto-generated page links — we use a custom selectbox instead
        "[data-testid='stSidebarNav'] { display: none; }"
        # ── Typography ────────────────────────────────────────────────────────
        "html, body, [class*='css'] { font-size: 18px; }"
        ".stMarkdown p, .stMarkdown li { font-size: 1.1rem; }"
        ".stChatMessage p { font-size: 1.1rem; }"
        "[data-testid='stSidebarNav'] a { font-size: 1.05rem; }"
        # ── Compact sidebar controls ──────────────────────────────────────────
        "section[data-testid='stSidebar'] textarea { font-size: 0.7rem; line-height: 1.2; }"
"section[data-testid='stSidebar'] .stButton button { font-size: 0.78rem !important; padding: 0.25rem 0.5rem !important; line-height: 1.4 !important; min-height: unset !important; }"
        "section[data-testid='stSidebar'] [data-testid='stExpanderDetails'] .stButton button { justify-content: flex-start !important; text-align: left !important; }"
        "section[data-testid='stSidebar'] [data-testid='stExpanderDetails'] .stButton button p { text-align: left !important; }"
        "section[data-testid='stSidebar'] [data-testid='stExpanderDetails'] .stButton button div { justify-content: flex-start !important; text-align: left !important; }"
        "section[data-testid='stSidebar'] .stExpander summary { font-size: 0.85rem !important; }"
        "section[data-testid='stSidebar'] .stExpander [data-testid='stExpanderDetails'] { padding: 0.25rem 0.5rem; }"
        "</style>",
        unsafe_allow_html=True,
    )


_inject_css()


# ── System prompts ────────────────────────────────────────────────────────────
# Pre-defined prompts that are swapped in automatically when the user toggles
# DropBox Context on/off. The user can still override them in the sidebar.

_DROPBOX_SYSTEM_PROMPT = (
    "Te az én személyes asszisztensem vagy, aki specializálódott a DropBox-ban tárolt dokumentumok kezelésére és megértésére.\n\n"
    "A feladataid:\n"
    "- Dokumentumok lekérése, rendszerezése és összefoglalása az igényeim alapján\n"
    "- Kontextus fenntartása több fájl és párbeszéd között\n"
    "- Kulcsinformációk, felismerések és teendők kiemelése\n"
    "- Kérdések megválaszolása kizárólag a releváns dokumentumkontextus alapján, ha elérhető\n"
    "- Tömör, pontos és strukturált válaszok adása\n\n"
    "Ha az információ hiányos vagy nem egyértelmű, kérj pontosítást a folytatás előtt.\n"
    "Mindig a relevanciát, az adatvédelmet és a pontosságot helyezd előtérbe."
)

_INTERNET_SYSTEM_PROMPT = (
    "Te az én személyes asszisztensem vagy, aki specializálódott az internetről származó információk megértésére és elemzésére.\n\n"
    "A feladataid:\n"
    "- Releváns online információk keresése, lekérése és összefoglalása\n"
    "- Források megbízhatóságának és pontosságának értékelése\n"
    "- Világos, tömör és strukturált válaszok adása\n"
    "- Felismerések szintézise több forrásból, ha szükséges\n"
    "- Bizonytalanság vagy ellentmondásos információ kiemelése\n\n"
    "Mindig a relevanciát, a megbízhatóságot és a naprakész információt helyezd előtérbe. "
    "Ha a kérés nem egyértelmű, kérj pontosítást."
)

_DEFAULT_SYSTEM_PROMPT = "Te egy hasznos asszisztens vagy."


# ── Sidebar ────────────────────────────────────────────────────────────────────
# Everything inside `with st.sidebar:` is rendered in the left panel.
with st.sidebar:

    # ── Navigation dropdown ────────────────────────────────────────────────────
    # Replace Streamlit's auto-generated nav links with a compact selectbox
    _PAGES = {"💬 Chat": "Chat.py", "📁 DropBox": "pages/DropBox.py", "📋 Logs": "pages/Logs.py", "ℹ️ Névjegy": "pages/About.py"}
    _nav = st.selectbox("Page", list(_PAGES.keys()), index=0, label_visibility="collapsed")
    if _nav != "💬 Chat":
        st.switch_page(_PAGES[_nav])

    # ── Auto-switch system prompt with DropBox toggle (only if not user-customized) ──
    # If the current prompt is one of the known auto-prompts, switch it when the
    # toggle changes. If the user wrote a custom prompt, leave it untouched.
    _current_dropbox = st.session_state.get("dropbox_context_enabled", False)
    _prev_dropbox    = st.session_state.get("_dropbox_state_for_prompt", _current_dropbox)
    if _current_dropbox != _prev_dropbox:
        _current_prompt = st.session_state.get("system_prompt", "")
        _auto_prompts   = {_DROPBOX_SYSTEM_PROMPT, _INTERNET_SYSTEM_PROMPT, _DEFAULT_SYSTEM_PROMPT, "Te egy hasznos asszisztens vagy."}
        if _current_prompt in _auto_prompts:
            st.session_state.system_prompt = (
                _DROPBOX_SYSTEM_PROMPT if _current_dropbox else _INTERNET_SYSTEM_PROMPT
            )
        st.session_state._dropbox_state_for_prompt = _current_dropbox

    # Apply any pending reset (triggered by the "Clear context" button) before
    # the text_area widget is instantiated
    if "system_prompt_reset" in st.session_state:
        st.session_state.system_prompt = st.session_state.pop("system_prompt_reset")
    if "system_prompt" not in st.session_state:
        st.session_state.system_prompt = _DROPBOX_SYSTEM_PROMPT

    # ── Model expander ─────────────────────────────────────────────────────────
    with st.expander("🤖 Modell", expanded=True):
        _tasks = MODEL_LABELS.get(st.session_state.get("selected_model", MODELS[0]), "Chat és kód")
        selected_model = st.selectbox(
            f"Feladatok: {_tasks}",
            MODELS,
            key="selected_model",
        )
        # Persist whenever the user picks a different model
        if st.session_state.get("selected_model") != st.session_state.get("_prev_model"):
            logger.info("model_selected=%s", selected_model)
            st.session_state._prev_model = st.session_state.get("selected_model")
            _save_persistent_settings()

    # ── System prompt expander ─────────────────────────────────────────────────
    with st.expander("📝 Rendszerutasítás", expanded=False):
        system_prompt = st.text_area(
            "Rendszerutasítás",
            key="system_prompt",
            height=120,
        )
        # Persist whenever the user edits the system prompt
        if system_prompt != st.session_state.get("_prev_system_prompt"):
            st.session_state._prev_system_prompt = system_prompt
            _save_persistent_settings()

    # ── Context expander ───────────────────────────────────────────────────────
    with st.expander("🌐 Kontextus", expanded=True):
        # Toggle rendered as a full-width button so it matches the Clear context button style.
        # Primary = active (blue), secondary = inactive (grey).
        _db_on = st.session_state.get("dropbox_context_enabled", False)
        _db_label = ("✅ DropBox kontextus: BE" if _db_on else "📁 DropBox kontextus: KI")
        if st.button(_db_label, use_container_width=True,
                     type="primary" if _db_on else "secondary",
                     key="dropbox_context_btn"):
            dropbox_context_enabled = not _db_on
            st.session_state.dropbox_context_enabled = dropbox_context_enabled
            logger.info("dropbox_context_toggled=%s", dropbox_context_enabled)
            st.session_state._prev_dropbox_context = dropbox_context_enabled
            _save_persistent_settings()
            st.rerun()
        else:
            dropbox_context_enabled = _db_on

        # Clear button: wipes conversation history only, leaves system prompt unchanged
        if st.button("🗑️ Kontextus törlése", use_container_width=True):
            logger.info("conversation_cleared=true")
            st.session_state.messages = []
            st.session_state.msg_new_value = ""
            _save_persistent_settings()
            st.rerun()

    # ── Token usage expander ───────────────────────────────────────────────────
    with st.expander("📊 Token használat", expanded=False):
        _history   = st.session_state.usage_history
        _last      = _history[-1] if _history else None
        _total_in  = sum(e["input_tokens"]  for e in _history)
        _total_out = sum(e["output_tokens"] for e in _history)

        _ts = _last["timestamp"].strftime("%Y-%m-%d %H:%M:%S") if _last else ""
        _li = _last["input_tokens"]  if _last else "—"
        _lo = _last["output_tokens"] if _last else "—"
        _ci = _total_in  if _history else "—"
        _co = _total_out if _history else "—"

        st.markdown(
            f"""<div style="font-size:1rem;line-height:1.7;padding-bottom:1rem;">
            <span style="color:#a78bfa;font-weight:bold">Utolsó válasz tokenek</span><br>
            {f'<span style="color:#94a3b8">{_ts}</span><br>' if _ts else ""}
            <span style="color:#6ee7b7">Be</span>&nbsp;<b style="color:#34d399">{_li}</b> &nbsp;·&nbsp; <span style="color:#fca5a5">Ki</span>&nbsp;<b style="color:#f87171">{_lo}</b><br>
            <span style="color:#a78bfa;font-weight:bold">Összesített tokenek</span><br>
            <span style="color:#6ee7b7">Be</span>&nbsp;<b style="color:#34d399">{_ci}</b> &nbsp;·&nbsp; <span style="color:#fca5a5">Ki</span>&nbsp;<b style="color:#f87171">{_co}</b>
            </div>""",
            unsafe_allow_html=True,
        )


# ── Page header ────────────────────────────────────────────────────────────────
st.markdown("<h3 style='margin-bottom:0'>💬 Nothing Gets Out AI</h3>", unsafe_allow_html=True)
st.caption(f"Modell: `{selected_model}`")


# ── Render existing messages ───────────────────────────────────────────────────
# Redraw every message bubble from the saved conversation history.
# st.chat_message("user")      → right-aligned user bubble
# st.chat_message("assistant") → left-aligned AI bubble
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

        # Show a source caption below each assistant reply
        if msg["role"] == "assistant":
            _src     = msg.get("source")
            _mdl     = msg.get("model", "")
            _mdl_tag = f" · `{_mdl}`" if _mdl else ""

            if _src == "files":
                st.caption(f"📁 A feltöltött fájlokból válaszolt{_mdl_tag}")
                _dropbox_sources = msg.get("dropbox_sources")
                if _dropbox_sources:
                    st.caption("Források: " + " · ".join(f"`{f}`" for f in _dropbox_sources))
            elif _src == "web":
                st.caption(f"🌐 Internetes keresésből válaszolt{_mdl_tag}")
                _sources = msg.get("web_sources")
                if _sources:
                    _links = " · ".join(
                        f"[{s['title'][:50]}]({s['link']})" for s in _sources
                    )
                    st.caption(f"Források: {_links}")
            else:
                st.caption(f"🤖 A modell válaszolt{_mdl_tag}")


# ── Chat input ─────────────────────────────────────────────────────────────────
# A text_area is used instead of st.chat_input so that the Files modal can
# inject a filename into the field programmatically via session_state.
# Any pending value (from the Files modal or post-send clear) must be applied
# BEFORE the widget is instantiated — Streamlit forbids changing widget-bound
# keys after render.
if "msg_new_value" in st.session_state:
    st.session_state.msg_area = st.session_state.pop("msg_new_value")

st.text_area(
    "Message",
    key="msg_area",
    height=80,
    label_visibility="collapsed",
    placeholder="Üzenet küldése…",
)

# Persist the draft whenever the user types (so it survives a page refresh)
if st.session_state.get("msg_area") != st.session_state.get("_prev_msg_area"):
    st.session_state._prev_msg_area = st.session_state.get("msg_area")
    _save_persistent_settings()

# ── Action buttons (Send / Clear / Files) ─────────────────────────────────────
col_send, col_clear, col_files = st.columns([2, 2, 2])

with col_files:
    if st.button("📁 Fájlok", use_container_width=True):
        files_modal()

with col_clear:
    if st.button("🗑️ Chat törlése", use_container_width=True, help="Chat törlése"):
        st.session_state.msg_new_value = ""
        _save_persistent_settings()
        st.rerun()

with col_send:
    send_clicked = st.button("📤 Küldés", use_container_width=True, type="primary", disabled=st.session_state._processing)


# ── Message handling ───────────────────────────────────────────────────────────
user_input = None
if send_clicked and st.session_state.get("msg_area", "").strip():
    st.session_state._pending_message = st.session_state.msg_area.strip()
    st.session_state._processing = True
    st.session_state.msg_new_value = ""  # Clear input on next rerun (before widget renders)
    _save_persistent_settings()
    st.rerun()

if st.session_state._processing and st.session_state._pending_message:
    user_input = st.session_state._pending_message

if user_input:
    # 1) Save the user's message to history and display it immediately
    logger.info("user_message=%r, model=%s", user_input[:100], selected_model)
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # 2) Determine context source ──────────────────────────────────────────────
    doc_chunks = None
    source     = "model"  # default: answer from training knowledge

    logger.info(
        "dropbox_context_enabled=%s, user_input=%r",
        st.session_state.get("dropbox_context_enabled", False),
        user_input[:100],
    )

    # Guard: DropBox context is on but no files have been uploaded yet
    if st.session_state.get("dropbox_context_enabled", False):
        files_in_upload = []
        if os.path.isdir(UPLOAD_DIR):
            files_in_upload = [
                f for f in os.listdir(UPLOAD_DIR)
                if os.path.isfile(os.path.join(UPLOAD_DIR, f))
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
                st.caption(f"🤖 · `{selected_model}`")
            st.session_state.messages.append({
                "role": "assistant",
                "content": "📁 A DropBox kontextus aktív, de nincs feltöltött fájl. Kérlek, töltsd fel a fájljaidat a DropBox oldalon.",
                "source": "system",
                "model": selected_model,
            })
            st.session_state._processing = False
            st.session_state._pending_message = None
            st.rerun()

    # 2a) Check if the user mentioned a specific filename in their message.
    #     If so, load that file's full content directly instead of doing a
    #     semantic search (more precise when a specific file is requested).
    dropbox_sources = None
    file_sections   = []  # One labelled text block per matched file

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
                    # Wrap chunks in a clearly labelled section so the model
                    # knows which file each piece of text comes from
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
            doc_chunks = file_sections
            source     = "files"
            dropbox_sources = [
                _fname for _fname in sorted(os.listdir(UPLOAD_DIR))
                if os.path.isfile(os.path.join(UPLOAD_DIR, _fname))
                and _fname.lower() in user_input.lower()
            ]

    # 2b) No specific file mentioned — fall back to ChromaDB semantic search
    #     (only when DropBox context is active)
    if not doc_chunks and st.session_state.get("dropbox_context_enabled", False):
        logger.info("DropBox context active — attempting ChromaDB semantic search")
        try:
            retrieved, retrieved_filenames = search_documents_langchain(user_input, k=4)
            if retrieved:
                doc_chunks      = retrieved
                source          = "files"
                dropbox_sources = retrieved_filenames
                logger.info("ChromaDB search succeeded, retrieved %d chunks", len(doc_chunks))
            else:
                logger.warning("ChromaDB search returned no results for: %r", user_input[:100])
        except Exception as e:
            logger.error("ChromaDB search failed: %s", e, exc_info=True)

    # 2c) Web search — only when DropBox context is inactive
    web_results      = None
    web_sources      = None
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
            logger.info("web_search_failed=%s", e)
            web_search_failed = True

    # 3) Assemble context text ─────────────────────────────────────────────────
    # Combine document chunks and web results, trimming each to fit the model's
    # context window (262 144 tokens; we budget up to 50 000 for context).
    context_parts = []

    if doc_chunks:
        context_parts.append(
            "\n\n".join(doc_chunks) if isinstance(doc_chunks, list) else str(doc_chunks)
        )

    if web_results:
        context_parts.append(_trim_context(web_results, max_tokens=4000))
        source = "web"

    context_text = "\n\n".join(context_parts) if context_parts else None

    # When multiple specific files were matched, split the budget equally so
    # every file gets fair representation even after trimming
    if file_sections:
        per_file_budget = 50_000 // max(len(file_sections), 1)
        trimmed_sections = [_trim_context(s, max_tokens=per_file_budget) for s in file_sections]
        context_text = "\n\n".join(
            trimmed_sections
            + ([_trim_context(web_results, max_tokens=4000)] if web_results else [])
        )

    # 4) Build the API message list ────────────────────────────────────────────
    # Start with the appropriate system prompt, then inject retrieved context
    # so the model can ground its answer in the user's files or a web search.
    if st.session_state.get("dropbox_context_enabled", False):
        augmented_system_prompt = _DROPBOX_SYSTEM_PROMPT
    else:
        augmented_system_prompt = _INTERNET_SYSTEM_PROMPT

    if context_text:
        trimmed_context = _trim_context(context_text, max_tokens=50_000)
        augmented_system_prompt += (
            "\n\nA következő kontextus alapján válaszolj a felhasználó kérdésére:\n\n"
            + trimmed_context
        )
    elif not st.session_state.get("dropbox_context_enabled", False):
        # Web search was skipped or returned nothing — tell the model explicitly
        augmented_system_prompt += (
            "\n\nMegjegyzés: Ehhez a kérdéshez nem áll rendelkezésre webes keresési eredmény. "
            "Válaszolj a betanítási ismereteid alapján, és jelezd egyértelműen, hogy "
            "az információ esetleg nem tükrözi a legfrissebb állapotot."
        )

    # Sliding-window conversation history: keep at most the last 40 messages
    # to avoid blowing the model's context window with very long sessions.
    conversation_msgs = st.session_state.messages
    if len(conversation_msgs) > 40:
        conversation_msgs = conversation_msgs[-40:]

    api_messages = [{"role": "system", "content": augmented_system_prompt}] + conversation_msgs

    # Final safety check: if we are still over budget, cut down to 20 messages
    max_input_tokens = 245_000  # Conservative limit (model max 262 144 − reply buffer)
    if _estimate_tokens(str(api_messages)) > max_input_tokens - 1_000:
        logger.warning("Token budget exceeded, trimming to last 20 messages")
        api_messages = [api_messages[0]] + conversation_msgs[-20:]

    # 5) Stream the AI response token by token ─────────────────────────────────
    with st.chat_message("assistant"):
        if web_search_failed:
            st.info("⚠️ Webes keresés nem elérhető — a betanítási tudás alapján válaszolok.", icon="🔌")

        # st.empty() creates a placeholder we overwrite on every new token
        placeholder = st.empty()
        full_text   = ""  # Accumulates the complete reply as tokens stream in

        _est = _estimate_tokens(str(api_messages))
        logger.info(
            "api_call_initiated=true, messages=%d, est_tokens=%d, source=%s",
            len(api_messages), _est, source,
        )

        try:
            if selected_model.startswith("qwen"):
                model_params = dict(temperature=0.7, top_p=0.8, presence_penalty=0)
            else:  # mistral
                model_params = dict(temperature=0.15, top_p=1, presence_penalty=0)
            stream = client.chat.completions.create(
                model=selected_model,
                messages=api_messages,
                max_tokens=4096,
                **model_params,
                stream=True,
                stream_options={"include_usage": True},  # Request token counts in final chunk
            )

            for chunk in stream:
                # Each chunk carries a small number of new tokens (or none on the last chunk)
                if chunk.choices and chunk.choices[0].delta.content:
                    full_text += chunk.choices[0].delta.content
                    # Append a blinking-cursor character "▌" while the reply is still streaming
                    placeholder.markdown(full_text + "▌")

                # The final chunk has no new tokens but carries usage statistics
                if chunk.usage:
                    entry = {
                        "input_tokens":  chunk.usage.prompt_tokens,
                        "output_tokens": chunk.usage.completion_tokens,
                        "timestamp":     datetime.now(),
                    }
                    logger.info(
                        "response_completed=true, input_tokens=%s, output_tokens=%s, source=%s",
                        entry["input_tokens"], entry["output_tokens"], source,
                    )
                    st.session_state.usage_history.append(entry)
                    save_usage_entry(
                        entry["input_tokens"],
                        entry["output_tokens"],
                        entry["timestamp"],
                    )

        except Exception as api_err:
            logger.error("api_call_failed=%s, est_tokens=%d", api_err, _est, exc_info=True)
            full_text = f"⚠️ API error: {api_err}"
            placeholder.warning(full_text)

        # Replace the streaming placeholder with the final, cursor-free text
        if not full_text or not full_text.strip():
            logger.warning(
                "empty_response=true, source=%s, user_input=%r, context_available=%s",
                source, user_input[:100], context_text is not None,
            )
            warning_message = (
                "⚠️ A modell üres választ küldött. Lehetséges okok:\n"
                "- A modell hibába ütközött\n"
                "- Nem találtunk releváns kontextust (próbálj más kulcsszavakat)\n"
                "- Próbáld meg másképp megfogalmazni a kérdésedet"
            )
            placeholder.warning(warning_message)
            full_text = warning_message  # Persist warning so it re-renders on the next run
        else:
            placeholder.markdown(full_text)

        # Display source attribution below the reply
        if source == "files":
            st.caption(f"📁 A feltöltött fájlokból válaszolt · `{selected_model}`")
            if dropbox_sources:
                st.caption("Források: " + " · ".join(f"`{f}`" for f in dropbox_sources))
        elif source == "web":
            st.caption(f"🌐 Internetes keresésből válaszolt · `{selected_model}`")
            if web_sources:
                links = " · ".join(f"[{s['title'][:50]}]({s['link']})" for s in web_sources)
                st.caption(f"Források: {links}")
        else:
            st.caption(f"🤖 A modell válaszolt · `{selected_model}`")

    # 6) Persist the completed reply ───────────────────────────────────────────
    # Appending to messages makes it part of the next request's conversation
    # history (multi-turn memory). source/model/sources are stored so the
    # attribution caption is preserved when history is re-rendered on reload.
    _msg = {
        "role":    "assistant",
        "content": full_text,
        "source":  source,
        "model":   selected_model,
    }
    if web_sources:
        _msg["web_sources"]     = web_sources
    if dropbox_sources:
        _msg["dropbox_sources"] = dropbox_sources
    st.session_state.messages.append(_msg)
    st.session_state._processing = False
    st.session_state._pending_message = None

    # Trigger a rerun so the sidebar token metrics update immediately
    st.rerun()
