import streamlit as st
import os
import re
from datetime import datetime

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Naplók", page_icon="📋", layout="wide", menu_items={})

# ── CSS (matches main app style) ───────────────────────────────────────────────
st.markdown(
    "<style>"
    "section[data-testid='stSidebar'] > div:first-child { padding-top: 0.25rem; }"
    "[data-testid='stSidebarHeader'] { display: none; }"
    "[data-testid='stAppDeployButton'] { display: none; }"
    "footer { display: none; }"
    ".stMenuVersionCopyButton { display: none; }"
    "html, body, [class*='css'] { font-size: 18px; }"
    ".stMarkdown p, .stMarkdown li { font-size: 0.9rem; }"
    "[data-testid='stSidebarNav'] { display: none; }"
    "section[data-testid='stSidebar'] .stToggle label p { font-size: 0.78rem !important; }"
    "section[data-testid='stSidebar'] .stButton button { font-size: 0.78rem !important; }"
    "section[data-testid='stSidebar'] .stExpander summary { font-size: 0.85rem !important; }"
    "section[data-testid='stSidebar'] h2 { font-size: 1rem !important; }"
    "section[data-testid='stSidebar'] pre { font-size: 0.85rem !important; }"
    "section[data-testid='stSidebar'] .stMultiSelect span[data-baseweb='tag'] { font-size: 0.7rem !important; padding: 0.1rem 0.35rem !important; }"
    "section[data-testid='stSidebar'] .stMultiSelect [data-testid='stWidgetLabel'] p { font-size: 0.78rem !important; }"
    "section[data-testid='stSidebar'] .stMultiSelect [data-baseweb='select'] { font-size: 0.78rem !important; }"
    ".log-container { background-color: #0d1117; color: #c9d1d9; padding: 0.8rem; border-radius: 0.4rem; font-family: 'Courier New', monospace; overflow-x: auto; font-size: 0.75rem; line-height: 1.4; }"
    ".log-line { margin: 0.2rem 0; padding: 0.15rem 0.4rem; border-radius: 0.2rem; }"
    ".log-debug { background-color: #1f2937; color: #60a5fa; font-weight: 500; }"
    ".log-info { background-color: #1f2d1f; color: #4ade80; }"
    ".log-warning { background-color: #332a1f; color: #fbbf24; font-weight: 500; }"
    ".log-error { background-color: #3f1f1f; color: #ff6b6b; font-weight: 600; }"
    ".log-critical { background-color: #4a1f1f; color: #ff4757; font-weight: 700; text-shadow: 0 0 3px rgba(255, 71, 87, 0.5); }"
    ".log-highlight { background-color: #fbbf24; color: #111; border-radius: 0.15rem; padding: 0 0.15rem; font-weight: 700; }"
    "</style>",
    unsafe_allow_html=True,
)

# ── Navigation dropdown ────────────────────────────────────────────────────────
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers.chat_ui import render_page_nav
render_page_nav("📋 Logs")

# ── Page title ─────────────────────────────────────────────────────────────────
st.markdown("<h3 style='margin-bottom:0'>📋 Naplónéző</h3>", unsafe_allow_html=True)

# ── Get log file path ──────────────────────────────────────────────────────────
# When running inside Docker the log file is mounted from the host at /app/ai.log
_is_docker = os.path.exists("/.dockerenv")
_LOG_FILE = "/app/ai.log" if _is_docker else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ai.log"
)

# ── Check if log file exists ───────────────────────────────────────────────────
if not os.path.exists(_LOG_FILE):
    st.warning("📭 Még nem található naplófájl. A naplófájl az alkalmazás futtatásakor jön létre.")
    st.stop()

# ── Read log file ──────────────────────────────────────────────────────────────
try:
    with open(_LOG_FILE, "r", encoding="utf-8") as f:
        log_content = f.read()
except Exception as e:
    st.error(f"❌ Hiba a naplófájl olvasásakor: {e}")
    st.stop()

# ── Parse log lines ────────────────────────────────────────────────────────────
log_lines = log_content.strip().split("\n") if log_content.strip() else []

if not log_lines:
    st.info("ℹ️ A naplófájl üres.")
    st.stop()

# ── Sidebar filters ────────────────────────────────────────────────────────────
st.sidebar.header("⚙️ Szűrők")

# Max lines to display (tail)
max_lines = st.sidebar.number_input(
    "Max sorok (legutóbbiak)",
    min_value=100,
    max_value=10000,
    value=1000,
    step=100,
    help="Az utolsó N sor megjelenítése teljesítmény-optimalizálás céljából"
)

# Log level filter
log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
selected_levels = st.sidebar.multiselect(
    "Naplószint",
    options=log_levels,
    default=[l for l in log_levels if l != "DEBUG"],
    help="Válaszd ki a megjelenítendő naplószinteket"
)

# Search filter
search_term = st.sidebar.text_input(
    "Keresés a naplóban",
    placeholder="pl. függvénynév vagy hibaüzenet",
    help="Naplók szűrése kulcsszó alapján"
)

# Show file info
file_stats = os.stat(_LOG_FILE)
with st.sidebar.expander("📊 Naplófájl adatok"):
    st.markdown(
        f"<p style='font-size:0.8rem;margin:0.15rem 0;'>📦 Fájlméret: <strong>{file_stats.st_size / 1024:.1f} KB</strong></p>"
        f"<p style='font-size:0.8rem;margin:0.15rem 0;'>🕒 Utoljára módosítva: <strong>{datetime.fromtimestamp(file_stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}</strong></p>"
        f"<p style='font-size:0.8rem;margin:0.15rem 0;'>📄 Összes sor: <strong>{len(log_lines)}</strong></p>",
        unsafe_allow_html=True,
    )

# ── Filter logs ────────────────────────────────────────────────────────────────
# Tail the log lines first for performance
tail_lines = log_lines[-int(max_lines):]

filtered_lines = []

for line in tail_lines:
    # Check log level filter — match | LEVEL | to avoid false positives in message text
    level_match = any(f"[{level}]" in line for level in selected_levels)

    # Check search term filter
    search_match = True
    if search_term:
        search_match = search_term.lower() in line.lower()

    if level_match and search_match:
        filtered_lines.append(line)

# ── Display stats ──────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Összes sor", len(log_lines))
with col2:
    st.metric("Szűrt sorok", len(filtered_lines))
with col3:
    if filtered_lines:
        # Count errors and warnings
        error_count = sum(1 for line in filtered_lines if any(f"[{lvl}]" in line for lvl in ["ERROR", "CRITICAL"]))
        st.metric("Hibák/Kritikus", error_count)
    else:
        st.metric("Hibák/Kritikus", 0)

# ── Display logs ───────────────────────────────────────────────────────────────
_hdr_col, _radio_col = st.columns([3, 2])
_hdr_col.subheader("📝 Naplóüzenetek")
display_mode = _radio_col.radio("Megjelenítési mód", options=["Formázott", "Kód"], horizontal=True, index=1, label_visibility="collapsed")

if not filtered_lines:
    st.info("ℹ️ Nincs a szűrőknek megfelelő naplóbejegyzés.")
else:
    if display_mode == "Kód":
        # Display as a code block (easier to copy)
        st.code("\n".join(filtered_lines), language="log")
        if search_term:
            st.caption("💡 Válts **Formázott** módra a keresési kiemelések megtekintéséhez.")
    else:
        # Display as formatted text with color coding — build all HTML in one pass
        html_parts = ['<div class="log-container">']

        safe_term_pattern = None
        if search_term:
            safe_term_pattern = re.compile(
                re.escape(search_term.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")),
                flags=re.IGNORECASE,
            )

        for line in filtered_lines:
            if "[DEBUG]" in line:
                color_class = "log-debug"
            elif "[INFO]" in line:
                color_class = "log-info"
            elif "[WARNING]" in line:
                color_class = "log-warning"
            elif "[CRITICAL]" in line:
                color_class = "log-critical"
            elif "[ERROR]" in line:
                color_class = "log-error"
            else:
                color_class = ""

            safe_line = (
                line.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
            )

            if safe_term_pattern:
                safe_line = safe_term_pattern.sub(
                    lambda m: f'<span class="log-highlight">{m.group(0)}</span>',
                    safe_line,
                )

            html_parts.append(f'<div class="log-line {color_class}">{safe_line}</div>')

        html_parts.append('</div>')
        st.markdown("".join(html_parts), unsafe_allow_html=True)

# ── Download option ───────────────────────────────────────────────────────────
if st.sidebar.button("📥 Szűrt naplók letöltése"):
    if filtered_lines:
        st.sidebar.download_button(
            label="Letöltés .txt formátumban",
            data="\n".join(filtered_lines),
            file_name=f"logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            mime="text/plain"
        )
    else:
        st.sidebar.warning("Nincs letölthető napló a jelenlegi szűrőkkel.")
