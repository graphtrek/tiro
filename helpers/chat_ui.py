import base64
import logging
import os
from datetime import datetime

import streamlit as st

from helpers.chat_config import AppConfig
from helpers.chat_prompts import SystemPrompts
from helpers.chat_settings import SettingsManager

logger = logging.getLogger(__name__)


# ── Files modal ───────────────────────────────────────────────────────────────
# Must be module-level — @st.dialog does not work inside a class body.

@st.dialog("📁 Fájlok")
def files_modal() -> None:
    """
    Pop-up dialog listing every non-image file in the uploads folder.

    Clicking a filename appends it to the chat input, enables DropBox context,
    and closes the modal via st.rerun().
    """
    _IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"}
    upload_dir  = AppConfig.UPLOAD_DIR
    files = sorted(
        f for f in os.listdir(upload_dir)
        if os.path.isfile(os.path.join(upload_dir, f))
        and os.path.splitext(f)[1].lower() not in _IMAGE_EXTS
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
            st.session_state.msg_new_value = current + sep + fname
            st.session_state.dropbox_context_enabled = True
            SettingsManager.save()
            st.rerun()


# ── CSS ───────────────────────────────────────────────────────────────────────
# @st.cache_resource must also be module-level.

@st.cache_resource
def _inject_css_once() -> None:
    st.markdown(
        "<style>"
        "section[data-testid='stSidebar'] > div:first-child { padding-top: 0.25rem; }"
        "[data-testid='stSidebarHeader'] { display: none; }"
        "[data-testid='stAppDeployButton'] { display: none; }"
        "footer { display: none; }"
        ".stMenuVersionCopyButton { display: none; }"
        "[data-testid='stSidebarNav'] { display: none; }"
        "html, body, [class*='css'] { font-size: 18px; }"
        ".stMarkdown p, .stMarkdown li { font-size: 1.1rem; }"
        ".stChatMessage p { font-size: 1.1rem; }"
        "[data-testid='stSidebarNav'] a { font-size: 1.05rem; }"
        "section[data-testid='stSidebar'] textarea { font-size: 0.9rem; line-height: 1.4; }"
        "section[data-testid='stSidebar'] .stButton button { font-size: 0.78rem !important; padding: 0.25rem 0.5rem !important; line-height: 1.4 !important; min-height: unset !important; }"
        "section[data-testid='stSidebar'] [data-testid='stExpanderDetails'] .stButton button { justify-content: flex-start !important; text-align: left !important; }"
        "section[data-testid='stSidebar'] [data-testid='stExpanderDetails'] .stButton button p { text-align: left !important; }"
        "section[data-testid='stSidebar'] [data-testid='stExpanderDetails'] .stButton button div { justify-content: flex-start !important; text-align: left !important; }"
        "section[data-testid='stSidebar'] .stExpander summary { font-size: 0.85rem !important; }"
        "section[data-testid='stSidebar'] .stExpander [data-testid='stExpanderDetails'] { padding: 0.25rem 0.5rem; }"
        "section[data-testid='stSidebar'] .stMarkdown:has(hr) { margin-top: 0rem !important; margin-bottom: 0.8rem !important; }"
        "section[data-testid='stSidebar'] hr { margin: 0 !important; }"
        "</style>",
        unsafe_allow_html=True,
    )


_PAGES = {
    "💬 Chat":      "Chat.py",
    "📁 DropBox":   "pages/DropBox.py",
    "⚙️ Programs":  "pages/Programs.py",
    "📋 Logs":      "pages/Logs.py",
    "ℹ️ Névjegy":   "pages/About.py",
}


def render_page_nav(current: str) -> None:
    """Render the page navigation selectbox in the sidebar.

    Pass the label of the current page (must match a key in _PAGES) so it
    appears pre-selected. Switching to a different page calls st.switch_page.
    """
    _inject_css_once()
    with st.sidebar:
        nav = st.selectbox(
            "Page",
            list(_PAGES.keys()),
            index=list(_PAGES.keys()).index(current),
            label_visibility="collapsed",
        )
        if nav != current:
            st.switch_page(_PAGES[nav])


class ChatUI:
    """Renders all Streamlit UI components for the main chat page."""

    @staticmethod
    def inject_css() -> None:
        _inject_css_once()

    @staticmethod
    def render_sidebar() -> tuple[str, bool, bool, bool, bool]:
        """
        Render the full sidebar.

        Returns (selected_model, internet_context_enabled, dropbox_context_enabled, gmail_context_enabled, drive_context_enabled).
        """
        with st.sidebar:
            # Navigation
            render_page_nav("💬 Chat")

            st.markdown("<hr style='border-color:#444'>", unsafe_allow_html=True)

            # Always sync the system prompt to the active context mode
            st.session_state.system_prompt = SystemPrompts.get_default(
                st.session_state.get("dropbox_context_enabled", False),
                st.session_state.get("gmail_context_enabled", False),
                st.session_state.get("drive_context_enabled", False),
            )

            # Model expander
            with st.expander("🤖 Modell", expanded=False):
                st.selectbox(
                    "",
                    AppConfig.MODELS,
                    key="selected_model",
                    format_func=AppConfig.get_model_label,
                )
                if st.session_state.get("selected_model") != st.session_state.get("_prev_model"):
                    logger.info("model_selected=%s", st.session_state.selected_model)
                    st.session_state._prev_model = st.session_state.get("selected_model")
                    SettingsManager.save()

            # System prompt expander (read-only display)
            with st.expander("📝 Rendszerutasítás", expanded=False):
                _prompt_text = st.session_state.system_prompt
                _prompt_height = max(120, _prompt_text.count('\n') * 26 + 60)
                st.text_area(
                    "Rendszerutasítás",
                    value=_prompt_text,
                    height=_prompt_height,
                    disabled=True,
                )

            # Context expander
            with st.expander("🌐 Kontextus", expanded=False):
                _in_on    = st.session_state.get("internet_context_enabled", True)
                _in_label = "✅ Internet kontextus: BE" if _in_on else "🌐 Internet kontextus: KI"
                if st.button(_in_label, use_container_width=True,
                             type="primary" if _in_on else "secondary",
                             key="internet_context_btn"):
                    new_val = not _in_on
                    st.session_state.internet_context_enabled = new_val
                    if new_val:
                        st.session_state.dropbox_context_enabled = False
                        st.session_state.gmail_context_enabled   = False
                        st.session_state.drive_context_enabled   = False
                    logger.info("internet_context_toggled=%s", new_val)
                    SettingsManager.save()
                    st.rerun()

                _db_on    = st.session_state.get("dropbox_context_enabled", False)
                _db_label = "✅ DropBox kontextus: BE" if _db_on else "📁 DropBox kontextus: KI"
                if st.button(_db_label, use_container_width=True,
                             type="primary" if _db_on else "secondary",
                             key="dropbox_context_btn"):
                    new_val = not _db_on
                    st.session_state.dropbox_context_enabled = new_val
                    if new_val:
                        st.session_state.internet_context_enabled = False
                        st.session_state.gmail_context_enabled   = False
                        st.session_state.drive_context_enabled   = False
                    logger.info("dropbox_context_toggled=%s", new_val)
                    SettingsManager.save()
                    st.rerun()

                _gm_on    = st.session_state.get("gmail_context_enabled", False)
                _gm_label = "✅ Gmail kontextus: BE" if _gm_on else "📧 Gmail kontextus: KI"
                if st.button(_gm_label, use_container_width=True,
                             type="primary" if _gm_on else "secondary",
                             key="gmail_context_btn"):
                    new_val = not _gm_on
                    st.session_state.gmail_context_enabled = new_val
                    if new_val:
                        st.session_state.internet_context_enabled = False
                        st.session_state.dropbox_context_enabled  = False
                        st.session_state.drive_context_enabled    = False
                    logger.info("gmail_context_toggled=%s", new_val)
                    SettingsManager.save()
                    st.rerun()

                _dr_on    = st.session_state.get("drive_context_enabled", False)
                _dr_label = "✅ Drive kontextus: BE" if _dr_on else "📂 Drive kontextus: KI"
                if st.button(_dr_label, use_container_width=True,
                             type="primary" if _dr_on else "secondary",
                             key="drive_context_btn"):
                    new_val = not _dr_on
                    st.session_state.drive_context_enabled = new_val
                    if new_val:
                        st.session_state.internet_context_enabled = False
                        st.session_state.dropbox_context_enabled  = False
                        st.session_state.gmail_context_enabled    = False
                    logger.info("drive_context_toggled=%s", new_val)
                    SettingsManager.save()
                    st.rerun()

                if st.button("🗑️ Kontextus törlése", use_container_width=True):
                    logger.info("conversation_cleared=true")
                    st.session_state.messages    = []
                    st.session_state.msg_new_value = ""
                    SettingsManager.save()
                    st.rerun()

            # Token usage expander
            with st.expander("📊 Token használat", expanded=False):
                history    = st.session_state.usage_history
                last       = history[-1] if history else None
                total_in   = sum(e["input_tokens"]  for e in history)
                total_out  = sum(e["output_tokens"] for e in history)
                ts         = last["timestamp"].strftime("%Y-%m-%d %H:%M:%S") if last else ""
                li         = last["input_tokens"]  if last else "—"
                lo         = last["output_tokens"] if last else "—"
                ci         = total_in  if history else "—"
                co         = total_out if history else "—"
                st.markdown(
                    f"""<div style="font-size:1rem;line-height:1.7;padding-bottom:1rem;">
                    <span style="color:#a78bfa;font-weight:bold">Utolsó válasz tokenek</span><br>
                    {f'<span style="color:#94a3b8">{ts}</span><br>' if ts else ""}
                    <span style="color:#6ee7b7">Be</span>&nbsp;<b style="color:#34d399">{li}</b> &nbsp;·&nbsp; <span style="color:#fca5a5">Ki</span>&nbsp;<b style="color:#f87171">{lo}</b><br>
                    <span style="color:#a78bfa;font-weight:bold">Összesített tokenek</span><br>
                    <span style="color:#6ee7b7">Be</span>&nbsp;<b style="color:#34d399">{ci}</b> &nbsp;·&nbsp; <span style="color:#fca5a5">Ki</span>&nbsp;<b style="color:#f87171">{co}</b>
                    </div>""",
                    unsafe_allow_html=True,
                )

            # Download chat button
            st.markdown("<hr style='border-color:#444'>", unsafe_allow_html=True)
            has_messages = bool(st.session_state.get("messages"))
            st.download_button(
                label="⬇️ Chat letöltése (.md)",
                data=ChatUI._build_chat_markdown() if has_messages else "",
                file_name=f"chat_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.md",
                mime="text/markdown",
                use_container_width=True,
                disabled=not has_messages,
            )

        return (
            st.session_state.get("selected_model", AppConfig.MODELS[0]),
            st.session_state.get("internet_context_enabled", True),
            st.session_state.get("dropbox_context_enabled", False),
            st.session_state.get("gmail_context_enabled", False),
            st.session_state.get("drive_context_enabled", False),
        )

    @staticmethod
    def _build_chat_markdown() -> str:
        """Build a Markdown string of the full conversation."""
        lines = []
        lines.append(f"# Chat — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        messages = st.session_state.get("messages", [])
        for i, msg in enumerate(messages):
            role_label = "👤 User" if msg["role"] == "user" else "🤖 Assistant"
            lines.append(f"### {role_label}")
            lines.append("")
            if msg.get("image_b64"):
                lines.append(f"*[Attached image: {msg.get('image_name', 'image')}]*")
                lines.append("")
            lines.append(msg["content"])
            if i < len(messages) - 1:
                lines.append("")
                lines.append("---")
                lines.append("")
        return "\n".join(lines)

    @staticmethod
    def render_messages() -> None:
        """Redraw every message bubble from the saved conversation history."""
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                if msg.get("image_b64"):
                    st.image(
                        base64.b64decode(msg["image_b64"]),
                        width=400,
                        caption=msg.get("image_name", ""),
                    )
                st.markdown(msg["content"])

                if msg["role"] == "assistant":
                    src     = msg.get("source")
                    mdl     = msg.get("model", "")
                    mdl_tag = f" · {AppConfig.get_model_label(mdl)}" if mdl else ""
                    if src == "files":
                        st.caption(f"📁 A feltöltött fájlokból válaszolt{mdl_tag}")
                        if msg.get("dropbox_sources"):
                            st.caption("Források: " + " · ".join(f"`{f}`" for f in msg["dropbox_sources"]))
                    elif src == "web":
                        st.caption(f"🌐 Internetes keresésből válaszolt{mdl_tag}")
                        if msg.get("web_sources"):
                            links = " · ".join(
                                f"[{s['title'][:50]}]({s['link']})" for s in msg["web_sources"]
                            )
                            st.caption(f"Források: {links}")
                    elif src == "gmail":
                        st.caption(f"📧 Gmail-ből válaszolt{mdl_tag}")
                    elif src == "drive":
                        st.caption(f"📂 Drive-ból válaszolt{mdl_tag}")
                    else:
                        st.caption(f"🤖 A modell válaszolt{mdl_tag}")

    @staticmethod
    def render_input(dropbox_on: bool, selected_model: str) -> bool:
        """
        Render the chat input area (textarea + action buttons).

        Returns True when the Send button is clicked with non-empty text.
        Also handles the image attachment selector for vision models.
        """
        # Apply any pending value injection before the widget renders
        if "msg_new_value" in st.session_state:
            st.session_state.msg_area = st.session_state.pop("msg_new_value")

        st.text_area(
            "Message",
            key="msg_area",
            height=80,
            label_visibility="collapsed",
            placeholder="Üzenet küldése…",
        )

        # Persist draft on every keystroke
        if st.session_state.get("msg_area") != st.session_state.get("_prev_msg_area"):
            st.session_state._prev_msg_area = st.session_state.get("msg_area")
            SettingsManager.save()

        # Image attachment (vision models + DropBox mode only)
        if dropbox_on and selected_model in AppConfig.VISION_MODELS:
            upload_dir  = AppConfig.UPLOAD_DIR
            jpeg_files  = []
            if os.path.isdir(upload_dir):
                jpeg_files = sorted(
                    f for f in os.listdir(upload_dir)
                    if os.path.isfile(os.path.join(upload_dir, f))
                    and os.path.splitext(f)[1].lower() in {".jpg", ".jpeg"}
                )
            if jpeg_files:
                img_options = ["— nincs —"] + jpeg_files
                img_sel = st.selectbox(
                    "📷 Kép a DropBox-ból (opcionális)",
                    img_options,
                    key=f"chat_img_select_{st.session_state._img_uploader_rev}",
                )
                if img_sel and img_sel != "— nincs —" and not st.session_state._processing:
                    img_path = os.path.join(upload_dir, img_sel)
                    with open(img_path, "rb") as fh:
                        st.session_state._pending_image = {
                            "name": img_sel,
                            "b64":  base64.b64encode(fh.read()).decode(),
                        }
                elif img_sel == "— nincs —" and not st.session_state._processing:
                    st.session_state._pending_image = None

        # Action buttons
        if dropbox_on:
            col_send, col_clear, col_files = st.columns([2, 2, 2])
            with col_files:
                if st.button("📁 Fájlok", use_container_width=True):
                    files_modal()
        else:
            col_send, col_clear = st.columns([2, 2])

        with col_clear:
            if st.button("🗑️ Chat törlése", use_container_width=True, help="Chat törlése"):
                st.session_state.msg_new_value = ""
                SettingsManager.save()
                st.rerun()

        with col_send:
            send_clicked = st.button(
                "📤 Küldés",
                use_container_width=True,
                type="primary",
                disabled=st.session_state._processing,
            )

        return send_clicked
