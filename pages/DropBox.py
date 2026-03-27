import streamlit as st
import os
import sys
from datetime import datetime

# Make the project root importable so rag_utils can be imported from pages/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rag_utils import index_documents, get_index_stats

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="DropBox", page_icon="📁", menu_items={})

# ── CSS (matches main app style) ───────────────────────────────────────────────
st.markdown(
    "<style>"
    "section[data-testid='stSidebar'] > div:first-child { padding-top: 0.25rem; }"
    "[data-testid='stSidebarHeader'] { display: none; }"
    "[data-testid='stAppDeployButton'] { display: none; }"
    "footer { display: none; }"
    ".stMenuVersionCopyButton { display: none; }"
    "html, body, [class*='css'] { font-size: 18px; }"
    ".stMarkdown p, .stMarkdown li { font-size: 1.1rem; }"
    "[data-testid='stSidebarNav'] a { font-size: 1.05rem; }"
    ".file-table-area button { font-size: 0.78rem !important; white-space: nowrap !important; overflow: hidden; padding: 0.15rem 0.4rem !important; }"
    "</style>",
    unsafe_allow_html=True,
)

# ── Constants ──────────────────────────────────────────────────────────────────
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "uploads")
ALLOWED_TYPES = ["docx", "xlsx", "pdf", "txt"]
ALLOWED_MIME = [
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/pdf",
    "text/plain",
]

SORT_COLS = ["name", "ext", "size_bytes", "uploaded"]

# ── Helpers ────────────────────────────────────────────────────────────────────
def fmt_size(n_bytes: int) -> str:
    if n_bytes >= 1_048_576:
        return f"{n_bytes / 1_048_576:.1f} MB"
    if n_bytes >= 1_024:
        return f"{n_bytes / 1_024:.1f} KB"
    return f"{n_bytes} B"


def load_file_records() -> list[dict]:
    records = []
    if not os.path.isdir(UPLOAD_DIR):
        return records
    for fname in sorted(os.listdir(UPLOAD_DIR)):
        fpath = os.path.join(UPLOAD_DIR, fname)
        if not os.path.isfile(fpath):
            continue
        stat = os.stat(fpath)
        ext = os.path.splitext(fname)[1].lstrip(".").lower()
        records.append(
            {
                "name": fname,
                "ext": ext.upper(),
                "size": fmt_size(stat.st_size),
                "size_bytes": stat.st_size,
                "uploaded": datetime.fromtimestamp(stat.st_mtime).strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "path": fpath,
            }
        )
    return records


# ── Session state defaults ─────────────────────────────────────────────────────
if "sort_col" not in st.session_state:
    st.session_state.sort_col = "name"
if "sort_asc" not in st.session_state:
    st.session_state.sort_asc = True


def set_sort(col: str) -> None:
    if st.session_state.sort_col == col:
        st.session_state.sort_asc = not st.session_state.sort_asc
    else:
        st.session_state.sort_col = col
        st.session_state.sort_asc = True


# ── Sidebar — indexing statistics ─────────────────────────────────────────────
def _fmt_num(n: int) -> str:
    """Format a large integer with thousands separator."""
    return f"{n:,}"


with st.sidebar:
    st.title("📊 Index statisztikák")
    stats = get_index_stats()

    if not stats:
        st.info("Még nincs indexelt fájl.")
    else:
        total_files  = len(stats)
        total_pages  = sum(s.get("pages", 0) for s in stats)
        total_chunks = sum(s.get("chunks", 0) for s in stats)
        total_tokens = sum(s.get("tokens_approx", 0) for s in stats)

        col1, col2 = st.columns(2)
        col1.metric("📄 Fájlok",   _fmt_num(total_files))
        col2.metric("📑 Oldalak",  _fmt_num(total_pages))
        col3, col4 = st.columns(2)
        col3.metric("🧩 Chunkok",  _fmt_num(total_chunks))
        col4.metric("🔢 ≈ Tokenek", _fmt_num(total_tokens))

        with st.expander("📄 Fájlonkénti részletek"):
            for s in sorted(stats, key=lambda x: x.get("filename", "")):
                fname   = s.get("filename", "?")
                pages   = s.get("pages", 0)
                chunks  = s.get("chunks", 0)
                tokens  = s.get("tokens_approx", 0)
                indexed = s.get("indexed_at", "")[:10]  # just the date part

                st.markdown(
                    f"**{fname}**  \n"
                    f"Oldalak: {_fmt_num(pages)} · Chunkok: {_fmt_num(chunks)} · "
                    f"≈ Tokenek: {_fmt_num(tokens)} · Indexelve: {indexed}"
                )
                st.divider()


# ── Page header ────────────────────────────────────────────────────────────────
st.title("📁 DropBox")
st.caption("Supported formats: DOCX · XLSX · PDF · TXT")

# ── File uploader ──────────────────────────────────────────────────────────────
uploaded_files = st.file_uploader(
    "Choose one or more files",
    type=ALLOWED_TYPES,
    accept_multiple_files=True,
    label_visibility="collapsed",
    key="file_uploader",
)

if uploaded_files:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    saved, replaced = [], []

    for uf in uploaded_files:
        dest = os.path.join(UPLOAD_DIR, uf.name)
        exists = os.path.isfile(dest)
        with open(dest, "wb") as f:
            f.write(uf.getbuffer())
        (replaced if exists else saved).append(uf.name)

    # Re-index immediately so the new files are searchable in Chat right away.
    index_documents(UPLOAD_DIR)

    if saved:
        st.success(f"Saved: {', '.join(saved)}")
    if replaced:
        st.info(f"Replaced: {', '.join(replaced)}")

# ── File table ─────────────────────────────────────────────────────────────────
records = load_file_records()

st.divider()

if not records:
    st.info("No files uploaded yet. Use the uploader above to add files.")
else:
    # ── Search bar ─────────────────────────────────────────────────────────────
    search = st.text_input(
        "🔍 Search by file name or type",
        placeholder="e.g. report or PDF",
        label_visibility="collapsed",
    )

    # Apply search filter
    if search:
        q = search.strip().lower()
        records = [r for r in records if q in r["name"].lower() or q in r["ext"].lower()]

    # Apply sort
    col = st.session_state.sort_col
    asc = st.session_state.sort_asc
    records = sorted(records, key=lambda r: r[col].lower() if isinstance(r[col], str) else r[col], reverse=not asc)

    arrow = lambda c: (" ▲" if asc else " ▼") if st.session_state.sort_col == c else ""

    st.caption(f"{len(records)} file(s) found")

    # ── Header row with sort buttons ───────────────────────────────────────────
    h1, h2, h3, h4, h5 = st.columns([4, 1.5, 1.5, 2, 1])
    h1.button(f"File name{arrow('name')}",     key="sh_name",     on_click=set_sort, args=("name",),       use_container_width=True)
    h2.button(f"Type{arrow('ext')}",           key="sh_ext",      on_click=set_sort, args=("ext",),        use_container_width=True)
    h3.button(f"Size{arrow('size_bytes')}",    key="sh_size",     on_click=set_sort, args=("size_bytes",), use_container_width=True)
    h4.button(f"Uploaded{arrow('uploaded')}",  key="sh_uploaded", on_click=set_sort, args=("uploaded",),   use_container_width=True)
    h5.html("<span style='font-size:0.85rem'>⬇</span>")
    st.divider()

    # ── Data rows ──────────────────────────────────────────────────────────────
    cell = "<span style='font-size:0.8rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block'>{}</span>"
    for rec in records:
        c1, c2, c3, c4, c5 = st.columns([4, 1.5, 1.5, 2, 1])
        c1.html(cell.format(rec["name"]))
        c2.html(cell.format(rec["ext"]))
        c3.html(cell.format(rec["size"]))
        c4.html(cell.format(rec["uploaded"]))
        with open(rec["path"], "rb") as fh:
            c5.download_button(
                label="⬇",
                data=fh,
                file_name=rec["name"],
                key=f"dl_{rec['name']}",
            )

