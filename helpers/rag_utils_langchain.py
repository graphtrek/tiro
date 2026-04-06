"""
rag_utils_langchain.py — LangChain-based RAG (Retrieval-Augmented Generation) helpers.

Uses LangChain for document loading, text splitting, and retrieval while
maintaining ChromaDB as the persistent vector store backend.

Public API:
  - get_langchain_vectorstore()  : LangChain Chroma wrapper around our ChromaDB collection
  - get_langchain_retriever()    : convenience retriever built on top of the vectorstore
  - index_documents_langchain()  : load, split, and index documents with LangChain loaders
  - search_documents_langchain() : semantic similarity search via ChromaDB
  - search_web_langchain()       : live web search using LangChain's DuckDuckGo tool
"""

import logging
import time
import os
from datetime import datetime, timezone


# ── Logging setup ──────────────────────────────────────────────────────────────
# Guard ensures handlers are registered only once even if the module is reloaded.
_LOGGING_CONFIGURED = False
# Log file and chroma_db live in the project root, one level above helpers/
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_FILE = os.path.join(_ROOT, "ai.log")

if not _LOGGING_CONFIGURED:
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)

    log_format = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(filename)s] [%(funcName)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Attach a shared file handler to the root logger so all third-party library
    # loggers (urllib3, langchain, etc.) also write to our log file.
    _root_logger = logging.getLogger()
    if not any(isinstance(h, logging.FileHandler) and h.baseFilename == _LOG_FILE
               for h in _root_logger.handlers):
        _root_file_handler = logging.FileHandler(_LOG_FILE)
        _root_file_handler.setLevel(logging.DEBUG)
        _root_file_handler.setFormatter(log_format)
        _root_logger.addHandler(_root_file_handler)
    _root_logger.setLevel(logging.DEBUG)

    # Add a console handler to our module logger (avoids duplicates on reload).
    if not logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(log_format)
        logger.addHandler(console_handler)

    # Verbose logs from key external libraries — useful for debugging RAG issues.
    logging.getLogger("urllib3").setLevel(logging.DEBUG)
    logging.getLogger("duckduckgo_search").setLevel(logging.DEBUG)
    logging.getLogger("langchain").setLevel(logging.DEBUG)
    logging.getLogger("langchain_community").setLevel(logging.DEBUG)
    # logging.getLogger("chromadb").setLevel(logging.DEBUG)  # uncomment if needed

    # Suppress noisy ONNX runtime warnings about unspecified execution providers.
    logging.getLogger("onnxruntime").setLevel(logging.ERROR)

    _LOGGING_CONFIGURED = True
else:
    logger = logging.getLogger(__name__)


# ── Imports ────────────────────────────────────────────────────────────────────
# LangChain loaders — one per supported file type; no API key needed.
from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    Docx2txtLoader,
)
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma              # used only by get_langchain_vectorstore()
from langchain_community.tools import DuckDuckGoSearchResults
import chromadb


# ── Paths & constants ──────────────────────────────────────────────────────────
CHROMA_DIR  = os.path.join(_ROOT, "chroma_db")   # persistent vector store on disk
UPLOAD_DIR  = os.path.join(_ROOT, "uploads")      # where user-uploaded files live

# ChromaDB collection names — each serves a distinct purpose.
COLLECTION_NAME       = "dropbox_docs"    # main document chunks + embeddings
STATS_COLLECTION_NAME = "index_stats"     # one entry per indexed file (pages, tokens, etc.)
USAGE_COLLECTION_NAME = "usage_history"   # per-conversation token usage log

# Text splitting — controls granularity of indexed chunks.
CHUNK_SIZE    = 1500  # characters per chunk
CHUNK_OVERLAP = 150   # overlap keeps context across chunk boundaries

SUPPORTED_EXTS = {".pdf", ".docx", ".xlsx", ".txt", ".md"}


# ── ChromaDB client helpers ────────────────────────────────────────────────────
# Module-level cache so we reuse a single PersistentClient across all calls.
_chroma_client_cache = None


def _get_chroma_client():
    """Return the shared ChromaDB PersistentClient, creating it on first call."""
    global _chroma_client_cache
    if _chroma_client_cache is None:
        logger.info("path=%s", CHROMA_DIR)
        _chroma_client_cache = chromadb.PersistentClient(path=CHROMA_DIR)
    return _chroma_client_cache


def _get_collection():
    """Return (or create) the main document-chunks collection with cosine distance."""
    logger.info("collection_name=%s", COLLECTION_NAME)
    return _get_chroma_client().get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},  # cosine similarity is standard for text embeddings
    )


def _get_stats_collection():
    """Return (or create) the per-file indexing-statistics collection."""
    logger.info("collection_name=%s", STATS_COLLECTION_NAME)
    return _get_chroma_client().get_or_create_collection(name=STATS_COLLECTION_NAME)


def _get_usage_collection():
    """Return (or create) the token-usage history collection (no embeddings needed)."""
    logger.info("collection_name=%s", USAGE_COLLECTION_NAME)
    return _get_chroma_client().get_or_create_collection(name=USAGE_COLLECTION_NAME)


# ── Diagnostics ────────────────────────────────────────────────────────────────
def get_collection_diagnostics() -> dict:
    """
    Return a summary of the ChromaDB collection state.

    Useful for debugging empty-search issues — shows total chunk count
    and a sample of which filenames are currently indexed.
    """
    try:
        collection = _get_collection()
        count = collection.count()

        # Fetch a small sample to discover which files are present.
        sample_meta = collection.get(include=["metadatas"], limit=10)
        files_indexed = {
            meta["filename"]
            for meta in sample_meta.get("metadatas", [])
            if meta and "filename" in meta
        }

        return {
            "total_chunks": count,
            "files_indexed": list(files_indexed),
            "status": "healthy" if count > 0 else "empty",
        }
    except Exception as e:
        logger.error("Failed to get collection diagnostics: %s", str(e))
        return {
            "total_chunks": 0,
            "files_indexed": [],
            "status": "error",
            "error": str(e),
        }


# ── Usage history ──────────────────────────────────────────────────────────────
def load_usage_history() -> list[dict]:
    """
    Load all token-usage entries from ChromaDB, sorted oldest → newest.

    Each returned dict: {"input_tokens": int, "output_tokens": int, "timestamp": datetime}
    Returns an empty list on any error.
    """
    logger.info("no params")
    try:
        result = _get_usage_collection().get(include=["metadatas"])
        entries = [
            {
                "input_tokens":  int(m["input_tokens"]),
                "output_tokens": int(m["output_tokens"]),
                "timestamp":     datetime.fromisoformat(m["timestamp"]),
            }
            for m in result["metadatas"]
            if m
        ]
        return sorted(entries, key=lambda e: e["timestamp"])
    except Exception:
        return []


def save_usage_entry(input_tokens: int, output_tokens: int, timestamp) -> None:
    """
    Persist a single token-usage entry to ChromaDB.

    The ISO-format timestamp string is used as the unique ID, so repeated
    saves for the same timestamp are idempotent (upsert semantics).
    """
    logger.info(
        "input_tokens=%s, output_tokens=%s, timestamp=%s",
        input_tokens, output_tokens, timestamp,
    )
    ts = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
    _get_usage_collection().upsert(
        ids=[ts],
        documents=[ts],          # ChromaDB requires a non-empty document string
        metadatas=[{
            "input_tokens":  input_tokens,
            "output_tokens": output_tokens,
            "timestamp":     ts,
        }],
    )


# ── Document utilities ─────────────────────────────────────────────────────────
def _count_pages(path: str, ext: str) -> int:
    """
    Estimate the page count of a document for display/stats purposes.

    - PDF  : exact count via PdfReader
    - DOCX : paragraphs ÷ 10 (rough estimate)
    - TXT  : lines ÷ 50 (rough estimate)
    Falls back to 1 on any error.
    """
    logger.info("path=%s, ext=%s", path, ext)
    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            return len(PdfReader(path).pages)
        if ext == ".docx":
            from docx import Document
            return max(len(Document(path).paragraphs) // 10, 1)
        if ext in (".txt", ".md"):
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                lines = sum(1 for _ in fh)
            return max(lines // 50, 1)
    except Exception:
        pass
    return 1


def _load_document(file_path: str):
    """
    Load a document from disk using the appropriate LangChain loader.

    Returns a list of LangChain Document objects, or [] on failure.
    Supported extensions: .pdf, .docx, .txt
    """
    logger.info("file_path=%s", file_path)
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == ".pdf":
            return PyPDFLoader(file_path).load()
        elif ext == ".docx":
            return Docx2txtLoader(file_path).load()
        elif ext in (".txt", ".md"):
            return TextLoader(file_path, encoding="utf-8").load()
    except Exception as e:
        logger.error("Error loading %s: %s", file_path, e)
    return []


# ── Vector store / retriever ───────────────────────────────────────────────────
def get_langchain_vectorstore(embedding_model):
    """
    Return a LangChain Chroma vectorstore wrapping our ChromaDB collection.

    `embedding_model` must be a LangChain Embeddings instance, e.g.:
        OpenAIEmbeddings(openai_api_base=..., openai_api_key=...)
    """
    logger.info("embedding_model=%s", type(embedding_model).__name__)
    return Chroma(
        client=_get_chroma_client(),
        collection_name=COLLECTION_NAME,
        embedding_function=embedding_model,
    )


def get_langchain_retriever(k: int = 4, embedding_model=None):
    """
    Return a LangChain retriever that fetches the top-k similar chunks.

    Returns None gracefully when no embedding model is provided (e.g. during
    app startup before the model is configured).
    """
    logger.info("k=%s, embedding_model=%s", k,
                type(embedding_model).__name__ if embedding_model else None)
    if embedding_model is None:
        return None
    return get_langchain_vectorstore(embedding_model).as_retriever(
        search_kwargs={"k": k}
    )


# ── Document indexing ──────────────────────────────────────────────────────────
def index_documents_langchain(
    uploads_dir: str,
    force_files: set[str] | None = None,
    only_files: set[str] | None = None,
):
    """
    Index supported documents into ChromaDB using LangChain loaders and splitter.

    Behaviour:
    - Skips files whose mtime hasn't changed since last index (unless in force_files).
    - Deletes and re-indexes files that have changed.
    - Removes chunks for files that no longer exist on disk.

    Parameters:
        uploads_dir : directory containing the files to index.
        force_files : filenames to re-index even if mtime is unchanged.
        only_files  : when provided, limits processing to just these filenames
                      (cheap path — avoids a full collection metadata scan).

    Returns:
        Dict mapping filename → "ok" | "no_text" | "no_chunks" | "unsupported"
    """
    logger.info(
        "uploads_dir=%s, force_files=%s, only_files=%s",
        uploads_dir, force_files, only_files,
    )
    results = {}

    if not os.path.isdir(uploads_dir):
        return results

    collection       = _get_collection()
    stats_collection = _get_stats_collection()

    # Build a filename → mtime map for already-indexed files.
    # When only_files is given, query per-file to avoid pulling all chunk metadata
    # for large collections (O(files) vs O(chunks)).
    indexed = {}
    if only_files:
        for fname in only_files:
            result = collection.get(where={"filename": fname}, include=["metadatas"])
            for meta in result["metadatas"]:
                if meta and "mtime" in meta:
                    indexed[fname] = meta["mtime"]
                    break  # all chunks for a file share the same mtime
    else:
        for meta in collection.get(include=["metadatas"])["metadatas"]:
            if meta and "filename" in meta and "mtime" in meta:
                indexed[meta["filename"]] = meta["mtime"]

    # RecursiveCharacterTextSplitter splits on paragraph → line → word → char,
    # producing chunks that respect natural language boundaries.
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""],
    )

    files_to_process = only_files if only_files else set(os.listdir(uploads_dir))
    disk_files = set()

    for fname in files_to_process:
        fpath = os.path.join(uploads_dir, fname)

        if not os.path.isfile(fpath):
            continue

        ext = os.path.splitext(fname)[1].lower()
        if ext not in SUPPORTED_EXTS:
            results[fname] = "unsupported"
            continue

        disk_files.add(fname)
        mtime = str(os.stat(fpath).st_mtime)
        logger.info("file=%s, mtime=%s", fname, mtime)

        # Skip files that haven't changed since the last index run.
        if indexed.get(fname) == mtime and fname not in (force_files or set()):
            continue

        # Remove stale chunks before re-indexing so we don't accumulate duplicates.
        if fname in indexed:
            collection.delete(where={"filename": fname})

        index_start = time.monotonic()
        docs = _load_document(fpath)
        if not docs:
            results[fname] = "no_text"
            continue

        # Attach filename to each document's metadata so we can filter by file later.
        for doc in docs:
            doc.metadata["filename"] = fname

        chunks = text_splitter.split_documents(docs)
        if not chunks:
            results[fname] = "no_chunks"
            continue

        # Upsert into ChromaDB in batches — the client has a hard limit (~5 461 items).
        chunk_texts = [c.page_content for c in chunks]
        ids         = [f"{fname}_chunk_{i}" for i in range(len(chunks))]
        metadatas   = [
            {"filename": fname, "mtime": mtime, "chunk_index": i}
            for i in range(len(chunks))
        ]
        _CHROMA_BATCH = 5000
        for start in range(0, len(chunk_texts), _CHROMA_BATCH):
            end = start + _CHROMA_BATCH
            collection.upsert(
                documents=chunk_texts[start:end],
                ids=ids[start:end],
                metadatas=metadatas[start:end],
            )

        # Store lightweight per-file stats (pages, char count, approximate tokens).
        total_text       = "\n".join(doc.page_content for doc in docs)
        chars            = len(total_text)
        tokens_approx    = chars // 4          # rough estimate: ~4 chars per token
        pages            = _count_pages(fpath, ext)
        indexed_at       = datetime.now(timezone.utc).isoformat()
        elapsed_seconds  = round(time.monotonic() - index_start, 3)

        stats_collection.upsert(
            ids=[fname],
            documents=[fname],
            metadatas=[{
                "filename":        fname,
                "pages":           pages,
                "chunks":          len(chunks),
                "chars":           chars,
                "tokens_approx":   tokens_approx,
                "indexed_at":      indexed_at,
                "elapsed_seconds": elapsed_seconds,
            }],
        )

        results[fname] = "ok"

    # Clean up chunks for files that have been removed from disk.
    # We compare against stats_collection IDs (one per file) rather than chunk
    # metadata to keep this O(files) instead of O(chunks).
    try:
        all_indexed_fnames = set(stats_collection.get()["ids"])
    except Exception:
        all_indexed_fnames = set(indexed.keys())

    current_disk_files = {
        f for f in os.listdir(uploads_dir)
        if os.path.isfile(os.path.join(uploads_dir, f))
    }
    for fname in all_indexed_fnames - current_disk_files:
        collection.delete(where={"filename": fname})
        try:
            stats_collection.delete(ids=[fname])
        except Exception:
            pass

    return results


def delete_file_from_index(filename: str) -> None:
    """Delete all chunks and stats for *filename* from ChromaDB."""
    logger.info("delete_file_from_index filename=%s", filename)
    collection       = _get_collection()
    stats_collection = _get_stats_collection()
    collection.delete(where={"filename": filename})
    try:
        stats_collection.delete(ids=[filename])
    except Exception:
        pass


def get_index_stats() -> list[dict]:
    """Return per-file indexing statistics (pages, chunks, chars, tokens, indexed_at)."""
    logger.info("no params")
    try:
        stats = _get_stats_collection().get(include=["metadatas"])["metadatas"]
        return [m for m in stats if m]
    except Exception:
        return []


# ── Search functions ───────────────────────────────────────────────────────────
def search_documents_langchain(
    query: str,
    k: int = 4,
    threshold: float = 0.5,
) -> tuple[list[str] | None, list[str] | None]:
    """
    Semantic search over indexed documents using ChromaDB's built-in embeddings.

    Parameters:
        query     : natural-language search query.
        k         : maximum number of chunks to return.
        threshold : maximum cosine distance to accept (0 = identical, 1 = orthogonal).
                    Values in [0.3, 0.5] work well for semantic search.

    Returns:
        (chunks, filenames) where chunks is a list of relevant text snippets and
        filenames is a deduplicated list of source filenames.
        Falls back to top-k results if no chunk passes the threshold, so that
        Dropbox mode always has context to work with.
        Returns (None, None) on error or empty collection.
    """
    logger.info("query=%r, k=%s, threshold=%s", query, k, threshold)
    collection = _get_collection()
    count = collection.count()
    if count == 0:
        logger.warning("No documents indexed in ChromaDB collection")
        return None, None

    try:
        logger.debug("Querying ChromaDB with %d total documents", count)
        results = collection.query(
            query_texts=[query],
            n_results=min(k, count),
            include=["documents", "distances", "metadatas"],
        )

        if not results or not results.get("documents"):
            logger.warning("Query returned no results")
            return None, None

        distances = results["distances"][0] if results["distances"] else []
        documents = results["documents"][0] if results["documents"] else []
        metadatas = results["metadatas"][0] if results.get("metadatas") else []

        logger.debug("Got %d results, distances: %s", len(documents), distances)

        # Keep only chunks within the similarity threshold.
        relevant_pairs = [
            (doc, meta)
            for doc, dist, meta in zip(
                documents, distances, metadatas or [{}] * len(documents)
            )
            if dist <= threshold
        ]

        if relevant_pairs:
            logger.info("Found %d chunks within threshold", len(relevant_pairs))
            chunks    = [p[0] for p in relevant_pairs]
            filenames = list(dict.fromkeys(
                p[1].get("filename") for p in relevant_pairs
                if p[1] and p[1].get("filename")
            ))
        else:
            # Nothing passed the threshold — return top-k anyway so Dropbox mode
            # always has at least some context to ground the answer.
            logger.warning(
                "No chunks passed threshold (%.2f); returning top %d results",
                threshold, min(k, len(documents)),
            )
            chunks    = documents or None
            filenames = list(dict.fromkeys(
                m.get("filename") for m in (metadatas or [])
                if m and m.get("filename")
            ))

        return chunks, filenames if filenames else None

    except Exception as e:
        logger.error("Search failed: %s", str(e), exc_info=True)
        return None, None


def search_web_langchain(query: str) -> tuple[str | None, list[dict] | None]:
    """
    Search the web using LangChain's DuckDuckGo tool (no API key required).

    Returns:
        (context_text, sources) where context_text is a newline-joined string of
        result snippets and sources is a list of {"title": str, "link": str} dicts.
        Returns (None, None) on failure or empty results.
    """
    logger.info("[WEB SEARCH] query=%r", query)
    try:
        tool = DuckDuckGoSearchResults(output_format="list", num_results=5)
        raw: list[dict] = tool.run(query)
        if not raw:
            logger.warning("[WEB SEARCH] No results for query=%r", query)
            return None, None

        text_parts = []
        sources    = []
        for item in raw:
            snippet = item.get("snippet", "")
            title   = item.get("title", "")
            link    = item.get("link", "")
            if snippet:
                text_parts.append(f"{title}\n{snippet}")
            if link:
                sources.append({"title": title or link, "link": link})

        text = "\n\n".join(text_parts) if text_parts else None
        logger.info("[WEB SEARCH] %d results, %d chars", len(raw), len(text) if text else 0)
        return text, sources if sources else None

    except Exception as e:
        logger.error("[WEB SEARCH] Failed: %s", str(e))
        return None, None


# ── Backward-compatibility wrappers ───────────────────────────────────────────
# These thin wrappers keep old call sites working without changes.

def index_documents(
    uploads_dir: str,
    force_files: set[str] | None = None,
    only_files: set[str] | None = None,
):
    """Legacy alias for index_documents_langchain()."""
    logger.info(
        "uploads_dir=%s, force_files=%s, only_files=%s",
        uploads_dir, force_files, only_files,
    )
    return index_documents_langchain(uploads_dir, force_files, only_files)


def get_all_chunks() -> list[str] | None:
    """Return all indexed chunks sorted by (filename, chunk_index). Legacy compat."""
    collection = _get_collection()
    if collection.count() == 0:
        return None
    try:
        results = collection.get(include=["documents", "metadatas"])
        docs    = results.get("documents")
        metas   = results.get("metadatas")
        if not docs:
            return None
        # Sort so chunks appear in document order rather than insertion order.
        pairs  = sorted(
            zip(metas, docs),
            key=lambda x: (x[0].get("filename", ""), x[0].get("chunk_index", 0)),
        )
        chunks = [doc for _, doc in pairs]
        return chunks if chunks else None
    except Exception:
        return None


def get_file_chunks(filename: str) -> list[str] | None:
    """Return all chunks for a specific file. Legacy compat."""
    collection = _get_collection()
    if collection.count() == 0:
        return None
    try:
        results = collection.get(
            where={"filename": filename},
            include=["documents", "metadatas"],
        )
        docs = results.get("documents")
        return docs if docs else None
    except Exception:
        return None


def search_documents(query: str, n_results: int = 4, threshold: float = 0.7):
    """Legacy alias for search_documents_langchain()."""
    return search_documents_langchain(query, k=n_results)


def search_web(query: str) -> str | None:
    """Legacy alias for search_web_langchain()."""
    return search_web_langchain(query)
