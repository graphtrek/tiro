"""
rag_utils_langchain.py — LangChain-based RAG helpers.

Uses LangChain for document loading, text splitting, and retrieval while
maintaining the existing ChromaDB persistent storage.

Provides:
  - get_langchain_vectorstore() : LangChain Chroma wrapper around our collection
  - index_documents_langchain()  : load and index docs with LangChain loaders
  - search_documents_langchain() : semantic search via LangChain retriever
  - search_web_langchain()       : web search with LangChain DuckDuckGo tool
"""

import os
from datetime import datetime, timezone

# LangChain imports — loaders and text splitter only (no API key needed)
from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    Docx2txtLoader,
)
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma          # used only by get_langchain_vectorstore()
from langchain_community.tools import DuckDuckGoSearchRun
import chromadb

# ── Paths ──────────────────────────────────────────────────────────────────────
_ROOT       = os.path.dirname(os.path.abspath(__file__))
CHROMA_DIR  = os.path.join(_ROOT, "chroma_db")
UPLOAD_DIR  = os.path.join(_ROOT, "uploads")

COLLECTION_NAME       = "dropbox_docs"
STATS_COLLECTION_NAME = "index_stats"
USAGE_COLLECTION_NAME = "usage_history"

# Text splitting parameters
CHUNK_SIZE    = 500
CHUNK_OVERLAP = 50

SUPPORTED_EXTS = {".pdf", ".docx", ".txt"}


# ── Utilities ──────────────────────────────────────────────────────────────────
def _get_chroma_client():
    """Get or create ChromaDB persistent client."""
    return chromadb.PersistentClient(path=CHROMA_DIR)


def _get_collection():
    """Get the main ChromaDB collection for document storage."""
    client = _get_chroma_client()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def _get_stats_collection():
    """Get the stats collection for metadata."""
    client = _get_chroma_client()
    return client.get_or_create_collection(name=STATS_COLLECTION_NAME)


def _get_usage_collection():
    """Get the usage history collection (no embeddings needed)."""
    client = _get_chroma_client()
    return client.get_or_create_collection(name=USAGE_COLLECTION_NAME)


# ── Usage history ─────────────────────────────────────────────────────────────
def load_usage_history() -> list[dict]:
    """
    Load all token-usage entries from ChromaDB, sorted by timestamp.

    Each entry: {"input_tokens": int, "output_tokens": int, "timestamp": datetime}
    """
    from datetime import datetime
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

    Uses the ISO timestamp string as the unique ID so re-runs never duplicate.
    """
    ts = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
    _get_usage_collection().upsert(
        ids=[ts],
        documents=[ts],          # ChromaDB requires a non-empty document
        metadatas=[{
            "input_tokens":  input_tokens,
            "output_tokens": output_tokens,
            "timestamp":     ts,
        }],
    )


def _count_pages(path: str, ext: str) -> int:
    """Estimate the number of pages in a document."""
    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            return len(PdfReader(path).pages)
        if ext == ".docx":
            from docx import Document
            paragraphs = len(Document(path).paragraphs)
            return max(paragraphs // 10, 1)
        if ext == ".txt":
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                lines = sum(1 for _ in fh)
            return max(lines // 50, 1)
    except Exception:
        pass
    return 1


# ── LangChain Document Loading ─────────────────────────────────────────────────
def _load_document(file_path: str):
    """Load a document using LangChain loaders based on file extension."""
    ext = os.path.splitext(file_path)[1].lower()

    try:
        if ext == ".pdf":
            loader = PyPDFLoader(file_path)
            return loader.load()
        elif ext == ".docx":
            loader = Docx2txtLoader(file_path)
            return loader.load()
        elif ext == ".txt":
            loader = TextLoader(file_path, encoding="utf-8")
            return loader.load()
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
        return []

    return []


# ── Vector Store Retriever ────────────────────────────────────────────────────
def get_langchain_vectorstore(embedding_model):
    """
    Return a LangChain Chroma vectorstore wrapper around our ChromaDB collection.
    An explicit embedding_model (LangChain Embeddings instance) is required —
    e.g. OpenAIEmbeddings(openai_api_base=..., openai_api_key=...).
    """
    return Chroma(
        client=_get_chroma_client(),
        collection_name=COLLECTION_NAME,
        embedding_function=embedding_model,
    )


def get_langchain_retriever(k: int = 4, embedding_model=None):
    """
    Return a LangChain retriever. Requires an explicit embedding_model.
    When embedding_model is None the function returns None gracefully.
    """
    if embedding_model is None:
        return None
    vectorstore = get_langchain_vectorstore(embedding_model)
    return vectorstore.as_retriever(search_kwargs={"k": k})


# ── Document Indexing ─────────────────────────────────────────────────────────
def index_documents_langchain(
    uploads_dir: str,
    force_files: set[str] | None = None,
):
    """
    Index all supported documents using LangChain loaders and text splitter.

    Uses LangChain's RecursiveCharacterTextSplitter for better chunk quality,
    then stores chunks directly in ChromaDB using its built-in local embedding
    model (no external API key required).

    Returns:
        Dict mapping filename → "ok" | "no_text" | "no_chunks" | "unsupported"
    """
    results = {}

    if not os.path.isdir(uploads_dir):
        return results

    collection = _get_collection()
    stats_collection = _get_stats_collection()
    
    # Build indexed files map
    all_meta = collection.get(include=["metadatas"])["metadatas"]
    indexed = {}
    for meta in all_meta:
        if meta and "filename" in meta and "mtime" in meta:
            indexed[meta["filename"]] = meta["mtime"]
    
    # Initialize text splitter (LangChain best practice for general content)
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""],
    )
    
    disk_files = set()
    
    # Process each file in uploads directory
    for fname in os.listdir(uploads_dir):
        fpath = os.path.join(uploads_dir, fname)
        
        if not os.path.isfile(fpath):
            continue
        
        ext = os.path.splitext(fname)[1].lower()
        if ext not in SUPPORTED_EXTS:
            results[fname] = "unsupported"
            continue
        
        disk_files.add(fname)
        mtime = str(os.stat(fpath).st_mtime)
        
        # Skip unchanged files (unless explicitly forced)
        if indexed.get(fname) == mtime and fname not in (force_files or set()):
            continue
        
        # Remove old chunks before re-indexing
        if fname in indexed:
            collection.delete(where={"filename": fname})
        
        # Load document with LangChain
        docs = _load_document(fpath)
        if not docs:
            results[fname] = "no_text"
            continue
        
        # Split documents with LangChain text splitter
        # Add filename metadata so ChromaDB can filter by file later
        for doc in docs:
            doc.metadata["filename"] = fname

        chunks = text_splitter.split_documents(docs)
        if not chunks:
            results[fname] = "no_chunks"
            continue

        # Store directly in ChromaDB using its built-in local embedding model.
        # ChromaDB has a max batch size (~5461), so we upsert in chunks.
        chunk_texts = [c.page_content for c in chunks]
        ids = [f"{fname}_chunk_{i}" for i in range(len(chunks))]
        metadatas = [
            {"filename": fname, "mtime": mtime, "chunk_index": i}
            for i in range(len(chunks))
        ]
        _CHROMA_BATCH = 5000
        for batch_start in range(0, len(chunk_texts), _CHROMA_BATCH):
            batch_end = batch_start + _CHROMA_BATCH
            collection.upsert(
                documents=chunk_texts[batch_start:batch_end],
                ids=ids[batch_start:batch_end],
                metadatas=metadatas[batch_start:batch_end],
            )

        # Store indexing statistics
        total_text = "\n".join([doc.page_content for doc in docs])
        chars = len(total_text)
        tokens_approx = chars // 4
        pages = _count_pages(fpath, ext)
        indexed_at = datetime.now(timezone.utc).isoformat()
        
        stats_collection.upsert(
            ids=[fname],
            documents=[fname],
            metadatas=[{
                "filename": fname,
                "pages": pages,
                "chunks": len(chunks),
                "chars": chars,
                "tokens_approx": tokens_approx,
                "indexed_at": indexed_at,
            }],
        )
        
        results[fname] = "ok"
    
    # Remove chunks for deleted files
    for fname in set(indexed.keys()) - disk_files:
        collection.delete(where={"filename": fname})
        try:
            stats_collection.delete(ids=[fname])
        except Exception:
            pass
    
    return results


def get_index_stats() -> list[dict]:
    """Return per-file indexing statistics."""
    try:
        stats = _get_stats_collection().get(include=["metadatas"])["metadatas"]
        return [m for m in stats if m]
    except Exception:
        return []


# ── Search Functions ──────────────────────────────────────────────────────────
def search_documents_langchain(
    query: str,
    k: int = 4,
    threshold: float = 0.7,
) -> list[str] | None:
    """
    Search indexed documents using ChromaDB's built-in local embedding.

    Returns a list of relevant text chunks or None if nothing is found.
    threshold: maximum cosine distance (0 = identical, 1 = orthogonal).
    """
    collection = _get_collection()
    count = collection.count()
    if count == 0:
        return None

    try:
        results = collection.query(
            query_texts=[query],
            n_results=min(k, count),
        )
        distances = results["distances"][0]
        documents = results["documents"][0]
        relevant = [
            doc for doc, dist in zip(documents, distances)
            if dist <= threshold
        ]
        return relevant if relevant else None
    except Exception:
        return None


def search_web_langchain(query: str) -> str | None:
    """
    Search the web using LangChain's DuckDuckGo tool.
    
    Args:
        query: Search query
    
    Returns:
        Formatted search results or None if search fails.
    """
    try:
        tool = DuckDuckGoSearchRun()
        results = tool.run(query)
        return results if results else None
    except Exception:
        return None


# ── Backward Compatibility ────────────────────────────────────────────────────
# Keep the old function names for drop-in compatibility
def index_documents(uploads_dir: str, force_files: set[str] | None = None):
    """Legacy wrapper — use index_documents_langchain() directly."""
    return index_documents_langchain(uploads_dir, force_files)


def get_all_chunks() -> list[str] | None:
    """Return all indexed chunks (kept for compatibility)."""
    collection = _get_collection()
    if collection.count() == 0:
        return None
    
    try:
        results = collection.get(include=["documents", "metadatas"])
        docs = results.get("documents")
        metas = results.get("metadatas")
        
        if not docs:
            return None
        
        pairs = sorted(
            zip(metas, docs),
            key=lambda x: (x[0].get("filename", ""), x[0].get("chunk_index", 0)),
        )
        chunks = [doc for _, doc in pairs]
        return chunks if chunks else None
    except Exception:
        return None


def get_file_chunks(filename: str) -> list[str] | None:
    """Get all chunks for a specific file (backward compatibility)."""
    collection = _get_collection()
    if collection.count() == 0:
        return None
    
    try:
        results = collection.get(
            where={"filename": filename},
            include=["documents", "metadatas"],
        )
        docs = results.get("documents")
        if not docs:
            return None
        return docs
    except Exception:
        return None


# Keep old function names for full backward compatibility
def search_documents(query: str, n_results: int = 4, threshold: float = 0.7):
    """Legacy wrapper — use search_documents_langchain() directly."""
    return search_documents_langchain(query, k=n_results)


def search_web(query: str) -> str | None:
    """Legacy wrapper — use search_web_langchain() directly."""
    return search_web_langchain(query)
