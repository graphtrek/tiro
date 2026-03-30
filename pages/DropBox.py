import streamlit as st
import os
import sys
import threading
import time
import uuid
from datetime import datetime

# Make the project root importable so rag_utils can be imported from pages/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rag_utils_langchain import index_documents_langchain as index_documents, get_index_stats, get_collection_diagnostics, delete_file_from_index

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
    "[data-testid='stSidebarNav'] { display: none; }"
    ".file-table-area button { font-size: 0.78rem !important; white-space: nowrap !important; overflow: hidden; padding: 0.15rem 0.4rem !important; }"
    "</style>",
    unsafe_allow_html=True,
)

# ── Navigation dropdown ────────────────────────────────────────────────────────
with st.sidebar:
    _PAGES = {"💬 Chat": "Chat.py", "📁 DropBox": "pages/DropBox.py", "📋 Logs": "pages/Logs.py", "ℹ️ Névjegy": "pages/About.py"}
    _nav = st.selectbox("Page", list(_PAGES.keys()), index=1, label_visibility="collapsed")
    if _nav != "📁 DropBox":
        st.switch_page(_PAGES[_nav])

# ── Constants ──────────────────────────────────────────────────────────────────
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "uploads")
ALLOWED_TYPES = ["docx", "xlsx", "pdf", "txt", "md"]
ALLOWED_MIME = [
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/pdf",
    "text/plain",
    "text/markdown",
]

SORT_COLS = ["name", "ext", "size_bytes", "uploaded"]

# ── Background indexing ─────────────────────────────────────────────────────────
@st.cache_resource
def _get_task_registry() -> dict:
    """Shared dict that survives Streamlit reruns and page navigation."""
    return {}


def _run_indexing(task_id: str, upload_dir: str, force_files: set, only_files: set) -> None:
    task = _get_task_registry()[task_id]
    try:
        results = index_documents(upload_dir, force_files=force_files, only_files=only_files)
        task["status"] = "done"
        task["results"] = results
    except Exception as exc:
        task["status"] = "failed"
        task["error"] = str(exc)

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
if "processed_file_ids" not in st.session_state:
    st.session_state.processed_file_ids = set()


def set_sort(col: str) -> None:
    if st.session_state.sort_col == col:
        st.session_state.sort_asc = not st.session_state.sort_asc
    else:
        st.session_state.sort_col = col
        st.session_state.sort_asc = True


def delete_file(path: str, filename: str) -> None:
    """Remove a file from disk and from ChromaDB, then refresh."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    delete_file_from_index(filename)
    st.session_state["_delete_msg"] = f"Törölve: {filename}"


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

        st.markdown(
            "<style>"
            "[data-testid='stSidebar'] [data-testid='stMetric'] label { font-size: 0.75rem !important; }"
            "[data-testid='stSidebar'] [data-testid='stMetric'] [data-testid='stMetricValue'] { font-size: 1rem !important; }"
            "</style>",
            unsafe_allow_html=True,
        )
        col1, col2 = st.columns(2)
        col1.metric("📄 Fájlok",   _fmt_num(total_files))
        col2.metric("📑 Oldalak",  _fmt_num(total_pages))
        col3, col4 = st.columns(2)
        col3.metric("🧩 Darabok",  _fmt_num(total_chunks))
        col4.metric("🔢 ≈ Tokenek", _fmt_num(total_tokens))

    # ── ChromaDB Diagnostics ───────────────────────────────────────────────────
    st.divider()
    st.subheader("🔍 ChromaDB állapot")
    diag = get_collection_diagnostics()

    if diag["status"] == "healthy":
        st.success(f"✅ Keresésre kész ({diag['total_chunks']} darab indexelve)")
    elif diag["status"] == "empty":
        st.warning("⚠️ Még nincs indexelt dokumentum\nTöltsd fel a fájlokat fent a DropBox kontextus engedélyezéséhez")
    else:
        st.error(f"❌ Hiba: {diag.get('error', 'Ismeretlen hiba')}")


# ── Page header ────────────────────────────────────────────────────────────────
st.title("📁 DropBox")
st.caption("Támogatott formátumok: DOCX · XLSX · PDF · TXT · MD")

# ── File uploader ──────────────────────────────────────────────────────────────
uploaded_files = st.file_uploader(
    "Válassz egy vagy több fájlt (DOCX · XLSX · PDF · TXT · MD)",
    type=ALLOWED_TYPES,
    accept_multiple_files=True,
    key="file_uploader",
)

if uploaded_files:
    # Filter out files already processed this session to avoid Streamlit rerun
    # re-triggering the same upload on every page interaction.
    new_uploads = [uf for uf in uploaded_files if uf.file_id not in st.session_state.processed_file_ids]

    if new_uploads:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        saved, replaced = [], []

        for uf in new_uploads:
            dest = os.path.join(UPLOAD_DIR, uf.name)
            exists = os.path.isfile(dest)
            with open(dest, "wb") as f:
                f.write(uf.getbuffer())
            (replaced if exists else saved).append(uf.name)
            st.session_state.processed_file_ids.add(uf.file_id)

        if saved:
            st.success(f"Mentve: {', '.join(saved)}")
        if replaced:
            st.info(f"Felülírva: {', '.join(replaced)}")

        # Launch indexing in a background thread so the user is not blocked.
        task_id = str(uuid.uuid4())
        _get_task_registry()[task_id] = {
            "status": "running",
            "saved": saved,
            "replaced": replaced,
            "results": {},
            "error": None,
        }
        st.session_state["indexing_task_id"] = task_id
        threading.Thread(
            target=_run_indexing,
            args=(task_id, UPLOAD_DIR, set(replaced), set(saved) | set(replaced)),
            daemon=True,
        ).start()

# ── Indexing status banner ──────────────────────────────────────────────────────
_task_id = st.session_state.get("indexing_task_id")
if _task_id:
    _task = _get_task_registry().get(_task_id)
    if _task:
        if _task["status"] == "running":
            _all_files = _task["saved"] + _task["replaced"]
            st.info(
                f"⏳ **{', '.join(_all_files)}** indexelése folyamatban a háttérben… "
                "Navigálhatsz más oldalakra — az indexelés automatikusan befejeződik."
            )
            time.sleep(1.5)
            st.rerun()
        else:
            # Done or failed — show result once, then clean up.
            if _task["status"] == "done":
                failed = [f for f, s in _task["results"].items() if s != "ok"]
                if failed:
                    st.warning(
                        f"⚠️ Nem sikerült szöveget kinyerni a következőkből: {', '.join(failed)}. "
                        "Ezek a fájlok szkennelt/képalapú dokumentumok lehetnek, és nem indexelhetők kereséshez."
                    )
                else:
                    st.success("✅ Indexelés kész.")
            else:
                st.error(f"❌ Indexelés sikertelen: {_task['error']}")
            _get_task_registry().pop(_task_id, None)
            del st.session_state["indexing_task_id"]

# ── File table ─────────────────────────────────────────────────────────────────
records = load_file_records()

# Build index-stats lookup keyed by filename for hover tooltips
_stats_lookup: dict[str, dict] = {}
_all_stats = get_index_stats()
if _all_stats:
    for _s in _all_stats:
        _stats_lookup[_s.get("filename", "")] = _s

st.divider()

if not records:
    st.info("Még nincs feltöltött fájl. Használd a fenti feltöltőt fájlok hozzáadásához.")
else:
    # ── Search bar ─────────────────────────────────────────────────────────────
    search = st.text_input(
        "🔍 Keresés fájlnév vagy típus alapján",
        placeholder="pl. riport vagy PDF",
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

    st.caption(f"{len(records)} fájl találva")

    # Show delete confirmation message if set
    if "_delete_msg" in st.session_state:
        st.success(st.session_state.pop("_delete_msg"))

    # ── Header row with sort buttons ───────────────────────────────────────────
    h1, h2, h3, h4, h5, h6 = st.columns([4, 1.5, 1.5, 2, 1, 1])
    h1.button(f"Fájlnév{arrow('name')}",        key="sh_name",     on_click=set_sort, args=("name",),       use_container_width=True)
    h2.button(f"Típus{arrow('ext')}",          key="sh_ext",      on_click=set_sort, args=("ext",),        use_container_width=True)
    h3.button(f"Méret{arrow('size_bytes')}",   key="sh_size",     on_click=set_sort, args=("size_bytes",), use_container_width=True)
    h4.button(f"Feltöltve{arrow('uploaded')}", key="sh_uploaded", on_click=set_sort, args=("uploaded",),   use_container_width=True)
    h5.html("<span style='font-size:0.85rem'>⬇</span>")
    h6.html("<span style='font-size:0.85rem'>🗑</span>")
    st.divider()

    # ── Data rows ──────────────────────────────────────────────────────────────
    cell = "<span style='font-size:0.8rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block'>{}</span>"
    for rec in records:
        c1, c2, c3, c4, c5, c6 = st.columns([4, 1.5, 1.5, 2, 1, 1])
        _si = _stats_lookup.get(rec["name"])
        if _si:
            _elapsed = _si.get('elapsed_seconds')
            _elapsed_str = f" &nbsp;·&nbsp; ⏱ {_elapsed}s" if _elapsed is not None else ""
            _tip_lines = (
                f"Oldalak: {_fmt_num(_si.get('pages', 0))}"
                f" &nbsp;·&nbsp; Darabok: {_fmt_num(_si.get('chunks', 0))}"
                f"<br>≈ Tokenek: {_fmt_num(_si.get('tokens_approx', 0))}"
                f" &nbsp;·&nbsp; Indexelve: {_si.get('indexed_at', '')[:16]}"
                f"{_elapsed_str}"
            )
            c1.markdown(
                f"<style>"
                f".ftip{{position:relative;display:inline-block;cursor:default;max-width:100%}}"
                f".ftip .ftip-box{{visibility:hidden;opacity:0;background:#2b2b2b;color:#f0f0f0;"
                f"border-radius:6px;padding:7px 11px;position:absolute;z-index:9999;bottom:130%;"
                f"left:0;white-space:nowrap;font-size:0.75rem;line-height:1.8;"
                f"box-shadow:0 2px 8px rgba(0,0,0,.4);transition:opacity .15s}}"
                f".ftip:hover .ftip-box{{visibility:visible;opacity:1}}"
                f"</style>"
                f"<div class='ftip'>"
                f"<span style='font-size:0.8rem;white-space:nowrap;overflow:hidden;"
                f"text-overflow:ellipsis;display:block'>{rec['name']}</span>"
                f"<div class='ftip-box'>{_tip_lines}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
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
        c6.button(
            label="🗑",
            key=f"del_{rec['name']}",
            on_click=delete_file,
            args=(rec["path"], rec["name"]),
            help=f"{rec['name']} törlése lemezről és indexből",
        )

