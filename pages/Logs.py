import streamlit as st
import os
import re
from datetime import datetime

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Logs", page_icon="📋", menu_items={})

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
with st.sidebar:
    _PAGES = {"💬 Chat": "Chat.py", "📁 DropBox": "pages/DropBox.py", "📋 Logs": "pages/Logs.py"}
    _nav = st.selectbox("Page", list(_PAGES.keys()), index=2, label_visibility="collapsed")
    if _nav != "📋 Logs":
        st.switch_page(_PAGES[_nav])

# ── Page title ─────────────────────────────────────────────────────────────────
st.title("📋 Log Viewer")

# ── Get log file path ──────────────────────────────────────────────────────────
# When running inside Docker the log file is mounted from the host at /app/kage-ai.log
_is_docker = os.path.exists("/.dockerenv")
_LOG_FILE = "/app/kage-ai.log" if _is_docker else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kage-ai.log"
)

# ── Check if log file exists ───────────────────────────────────────────────────
if not os.path.exists(_LOG_FILE):
    st.warning("📭 No log file found yet. The log file will be created when the application runs.")
    st.stop()

# ── Read log file ──────────────────────────────────────────────────────────────
try:
    with open(_LOG_FILE, "r", encoding="utf-8") as f:
        log_content = f.read()
except Exception as e:
    st.error(f"❌ Error reading log file: {e}")
    st.stop()

# ── Parse log lines ────────────────────────────────────────────────────────────
log_lines = log_content.strip().split("\n") if log_content.strip() else []

if not log_lines:
    st.info("ℹ️ The log file is empty.")
    st.stop()

# ── Sidebar filters ────────────────────────────────────────────────────────────
st.sidebar.header("⚙️ Filters")

# Log level filter
log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
selected_levels = st.sidebar.multiselect(
    "Log Level",
    options=log_levels,
    default=log_levels,
    help="Select which log levels to display"
)

# Search filter
search_term = st.sidebar.text_input(
    "Search in logs",
    placeholder="e.g., function name or error message",
    help="Filter logs by keyword"
)

# Show file info
file_stats = os.stat(_LOG_FILE)
st.sidebar.markdown("---")
st.sidebar.subheader("📊 Log File Info")
st.sidebar.text(f"File size: {file_stats.st_size / 1024:.1f} KB")
st.sidebar.text(f"Last modified: {datetime.fromtimestamp(file_stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}")
st.sidebar.text(f"Total lines: {len(log_lines)}")

# ── Filter logs ────────────────────────────────────────────────────────────────
filtered_lines = []

for line in log_lines:
    # Check log level filter
    level_match = any(level in line for level in selected_levels)
    
    # Check search term filter
    search_match = True
    if search_term:
        search_match = search_term.lower() in line.lower()
    
    if level_match and search_match:
        filtered_lines.append(line)

# ── Display stats ──────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Total Lines", len(log_lines))
with col2:
    st.metric("Filtered Lines", len(filtered_lines))
with col3:
    if filtered_lines:
        # Count errors and warnings
        error_count = sum(1 for line in filtered_lines if any(lvl in line for lvl in ["ERROR", "CRITICAL"]))
        st.metric("Errors/Critical", error_count)
    else:
        st.metric("Errors/Critical", 0)

# ── Display logs ───────────────────────────────────────────────────────────────
st.subheader("📝 Log Messages")

if not filtered_lines:
    st.info("ℹ️ No logs match the current filters.")
else:
    # Option to show as code or formatted
    display_mode = st.radio("Display mode", options=["Formatted", "Code"], horizontal=True, index=1)
    
    if display_mode == "Code":
        # Display as a code block (easier to copy)
        st.code("\n".join(filtered_lines), language="log")
        if search_term:
            st.caption("💡 Switch to **Formatted** mode to see search highlights.")
    else:
        # Display as formatted text with color coding
        st.markdown('<div class="log-container">', unsafe_allow_html=True)
        
        for line in filtered_lines:
            # Determine log level and color
            if "DEBUG" in line:
                color_class = "log-debug"
            elif "INFO" in line:
                color_class = "log-info"
            elif "WARNING" in line:
                color_class = "log-warning"
            elif "CRITICAL" in line:
                color_class = "log-critical"
            elif "ERROR" in line:
                color_class = "log-error"
            else:
                color_class = ""
            
            # Escape HTML special characters
            safe_line = (
                line.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
            )
            
            # Highlight search term
            if search_term:
                safe_term = re.escape(
                    search_term.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                )
                safe_line = re.sub(
                    safe_term,
                    lambda m: f'<span class="log-highlight">{m.group(0)}</span>',
                    safe_line,
                    flags=re.IGNORECASE,
                )
            
            st.markdown(
                f'<div class="log-line {color_class}">{safe_line}</div>',
                unsafe_allow_html=True
            )
        
        st.markdown('</div>', unsafe_allow_html=True)

# ── Download option ───────────────────────────────────────────────────────────
st.sidebar.markdown("---")
if st.sidebar.button("📥 Download Filtered Logs"):
    if filtered_lines:
        st.sidebar.download_button(
            label="Download as .txt",
            data="\n".join(filtered_lines),
            file_name=f"logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            mime="text/plain"
        )
    else:
        st.sidebar.warning("No logs to download with current filters.")
