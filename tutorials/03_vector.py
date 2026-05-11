#!/usr/bin/env python3
"""
03_vector.py - ChromaDB Indexing Tutorial

This tutorial demonstrates how to:
1. Scan markdown documentation from nothing-gets-out/docs/prompt/
2. Index documents into ChromaDB with incremental updates (only changed files)
3. Perform semantic search queries against the indexed documents

Key concepts:
- Document loading from markdown files
- Text chunking with overlap (LangChain)
- Change detection for efficient incremental indexing
- ChromaDB with cosine distance metric
- Semantic search and result retrieval

Run: python 03_vector.py
"""

import logging
import json
import os
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime

from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma

# ============================================================================
# SETUP & LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ============================================================================
# PATHS & CONFIGURATION
# ============================================================================

# Get the tutorials folder (where this script lives)
TUTORIALS_DIR = Path(__file__).parent.resolve()

# Source documentation folder
SOURCE_DOCS_DIR = TUTORIALS_DIR.parent / "nothing-gets-out" / "docs" / "prompt"

# Output ChromaDB folder
CHROMA_DB_DIR = TUTORIALS_DIR / "chroma_db_tutorial"

# Metadata file to track indexed files and their modification times
METADATA_FILE = CHROMA_DB_DIR / "index_metadata.json"

# ChromaDB collection name
COLLECTION_NAME = "prompt_docs"

# Chunking configuration (matches nothing-gets-out)
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 150
SEPARATORS = ["\n\n", "\n", " ", ""]

logger.info(f"📂 Source docs: {SOURCE_DOCS_DIR}")
logger.info(f"💾 ChromaDB output: {CHROMA_DB_DIR}")

# ============================================================================
# METADATA MANAGEMENT (For Incremental Indexing)
# ============================================================================


def load_metadata() -> Dict[str, Dict]:
    """
    Load metadata about previously indexed files.
    
    Returns dict like:
    {
        "docs/prompt/index.md": {"mtime": 1234567890.0, "chunk_count": 10},
        "docs/prompt/core/identity.md": {"mtime": 1234567891.0, "chunk_count": 15},
        ...
    }
    """
    if not METADATA_FILE.exists():
        return {}
    
    try:
        with open(METADATA_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"⚠️ Failed to load metadata: {e}. Starting fresh.")
        return {}


def save_metadata(metadata: Dict[str, Dict]) -> None:
    """Save metadata about indexed files."""
    CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)
    with open(METADATA_FILE, "w") as f:
        json.dump(metadata, f, indent=2)
    logger.info(f"✅ Metadata saved: {len(metadata)} files tracked")


# ============================================================================
# DOCUMENT SCANNING & CHANGE DETECTION
# ============================================================================


def scan_markdown_files() -> Dict[str, float]:
    """
    Scan for all .md files in the source docs folder.
    
    Returns dict like:
    {
        "docs/prompt/index.md": <mtime>,
        "docs/prompt/core/identity.md": <mtime>,
        ...
    }
    """
    if not SOURCE_DOCS_DIR.exists():
        logger.error(f"❌ Source docs folder not found: {SOURCE_DOCS_DIR}")
        raise FileNotFoundError(f"Source docs folder not found: {SOURCE_DOCS_DIR}")
    
    current_files = {}
    for md_file in SOURCE_DOCS_DIR.rglob("*.md"):
        # Store relative path as key for consistency
        rel_path = md_file.relative_to(SOURCE_DOCS_DIR.parent)
        mtime = md_file.stat().st_mtime
        current_files[str(rel_path)] = mtime
    
    if not current_files:
        logger.error(f"❌ No markdown files found in {SOURCE_DOCS_DIR}")
        raise FileNotFoundError(f"No markdown files found in {SOURCE_DOCS_DIR}")
    
    logger.info(f"🔍 Found {len(current_files)} markdown files")
    return current_files


def detect_changes(old_metadata: Dict[str, Dict], current_files: Dict[str, float]) -> Tuple[List[str], List[str], List[str]]:
    """
    Detect which files are new, modified, or deleted.
    
    Returns:
    - new_files: Files not in old metadata
    - modified_files: Files with different mtime
    - deleted_files: Files in old metadata but not in current_files
    """
    new_files = []
    modified_files = []
    
    for file_path, mtime in current_files.items():
        if file_path not in old_metadata:
            new_files.append(file_path)
        elif old_metadata[file_path]["mtime"] != mtime:
            modified_files.append(file_path)
    
    deleted_files = [f for f in old_metadata.keys() if f not in current_files]
    
    logger.info(f"📊 Changes detected:")
    logger.info(f"   ✨ New: {len(new_files)}")
    logger.info(f"   🔄 Modified: {len(modified_files)}")
    logger.info(f"   ❌ Deleted: {len(deleted_files)}")
    
    return new_files, modified_files, deleted_files


# ============================================================================
# DOCUMENT LOADING & CHUNKING
# ============================================================================


def load_documents(file_paths: List[str]) -> List:
    """Load and chunk markdown files."""
    if not file_paths:
        return []
    
    documents = []
    for file_path in file_paths:
        full_path = SOURCE_DOCS_DIR.parent / file_path
        if not full_path.exists():
            logger.warning(f"⚠️ File not found (skipping): {full_path}")
            continue
        
        try:
            loader = TextLoader(str(full_path), encoding="utf-8")
            docs = loader.load()
            # Add source metadata
            for doc in docs:
                doc.metadata["source"] = file_path
            documents.extend(docs)
            logger.info(f"📖 Loaded: {file_path} ({len(docs)} page(s))")
        except Exception as e:
            logger.error(f"❌ Failed to load {file_path}: {e}")
    
    return documents


def chunk_documents(documents: List) -> List:
    """Split documents into chunks with overlap."""
    if not documents:
        return []
    
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=SEPARATORS,
        length_function=len,
    )
    
    chunks = splitter.split_documents(documents)
    logger.info(f"✂️ Chunked {len(documents)} page(s) into {len(chunks)} chunk(s)")
    
    # Add chunk_index to metadata for tracking
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = i
    
    return chunks


# ============================================================================
# CHROMADB SETUP & INCREMENTAL INDEXING
# ============================================================================


def get_chroma_client():
    """Initialize ChromaDB Chroma instance."""
    CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)
    
    return Chroma(
        collection_name=COLLECTION_NAME,
        persist_directory=str(CHROMA_DB_DIR),
        collection_metadata={"hnsw:space": "cosine"}  # Cosine distance metric
    )


def delete_chunks_by_source(chroma_client, source_files: List[str]) -> None:
    """Delete all chunks from specific source files in ChromaDB."""
    if not source_files:
        return
    
    total_deleted = 0
    for source_file in source_files:
        # Use the internal ChromaDB collection via _collection
        if hasattr(chroma_client, '_collection'):
            collection = chroma_client._collection
            # Query for all chunks from this source
            results = collection.get(where={"source": {"$eq": source_file}})
            
            if results["ids"]:
                collection.delete(ids=results["ids"])
                total_deleted += len(results["ids"])
                logger.info(f"🗑️ Deleted {len(results['ids'])} chunk(s) from {source_file}")
    
    if total_deleted > 0:
        logger.info(f"📉 Total deleted: {total_deleted} chunk(s)")


def index_documents_incremental(chroma_client, new_files: List[str], modified_files: List[str]) -> int:
    """
    Index new and modified files into ChromaDB.
    
    Returns total number of chunks indexed.
    """
    files_to_index = new_files + modified_files
    
    if not files_to_index:
        logger.info("⏭️ No files to index (all unchanged)")
        return 0
    
    # Load documents from files to index
    documents = load_documents(files_to_index)
    
    # For modified files, delete old chunks first
    if modified_files:
        logger.info(f"🔄 Removing old chunks from modified files...")
        delete_chunks_by_source(chroma_client, modified_files)
    
    # Chunk and index
    chunks = chunk_documents(documents)
    
    if chunks:
        # Add chunks to ChromaDB (Chroma handles embedding automatically)
        chroma_client.add_documents(chunks)
        logger.info(f"📚 Indexed {len(chunks)} chunk(s) into ChromaDB")
    
    return len(chunks)


# ============================================================================
# SEARCH & QUERIES
# ============================================================================


def query_docs(chroma_client, query: str, k: int = 4) -> List[Tuple[str, str, float]]:
    """
    Perform semantic search on indexed documents.
    
    Returns list of (source_filename, chunk_text, distance) tuples.
    """
    try:
        # Similarity search with distance (Chroma returns distances, not similarity scores)
        results = chroma_client.similarity_search_with_score(query, k=k)
        
        formatted_results = []
        for doc, distance in results:
            source = doc.metadata.get("source", "unknown")
            formatted_results.append((source, doc.page_content, distance))
        
        return formatted_results
    except Exception as e:
        logger.error(f"❌ Search failed: {e}")
        return []


def display_search_results(query: str, results: List[Tuple[str, str, float]]) -> None:
    """Pretty-print search results."""
    print(f"\n{'='*80}")
    print(f"🔎 Query: {query}")
    print(f"{'='*80}")
    
    if not results:
        print("❌ No results found")
        return
    
    for i, (source, chunk_text, distance) in enumerate(results, 1):
        print(f"\n📄 Result {i} | Source: {source} | Distance: {distance:.4f}")
        print(f"-" * 80)
        
        # Show first 500 chars of chunk, with ellipsis if longer
        preview = chunk_text[:500]
        if len(chunk_text) > 500:
            preview += "\n... [truncated]"
        
        print(preview)
    
    print(f"\n{'='*80}\n")


# ============================================================================
# MAIN EXECUTION
# ============================================================================


def main():
    """Main orchestrator function."""
    logger.info("🚀 Starting ChromaDB Indexing Tutorial")
    logger.info(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # --------
    # Phase 1: Load metadata and scan current files
    # --------
    logger.info("\n" + "="*80)
    logger.info("PHASE 1: Scanning Files & Detecting Changes")
    logger.info("="*80)
    
    old_metadata = load_metadata()
    current_files = scan_markdown_files()
    new_files, modified_files, deleted_files = detect_changes(old_metadata, current_files)
    
    # --------
    # Phase 2: Initialize ChromaDB
    # --------
    logger.info("\n" + "="*80)
    logger.info("PHASE 2: Initializing ChromaDB")
    logger.info("="*80)
    
    chroma_client = get_chroma_client()
    logger.info(f"✅ ChromaDB initialized at {CHROMA_DB_DIR}")
    
    # --------
    # Phase 3: Delete chunks from deleted files
    # --------
    if deleted_files:
        logger.info("\n" + "="*80)
        logger.info("PHASE 3: Cleaning Up Deleted Files")
        logger.info("="*80)
        
        delete_chunks_by_source(chroma_client, deleted_files)
    
    # --------
    # Phase 4: Index new and modified files
    # --------
    logger.info("\n" + "="*80)
    logger.info("PHASE 4: Incremental Indexing")
    logger.info("="*80)
    
    total_indexed = index_documents_incremental(chroma_client, new_files, modified_files)
    
    # --------
    # Phase 5: Update metadata
    # --------
    logger.info("\n" + "="*80)
    logger.info("PHASE 5: Updating Metadata")
    logger.info("="*80)
    
    # Build new metadata: keep old data but update files and remove deleted
    new_metadata = {}
    
    for file_path, mtime in current_files.items():
        if file_path in old_metadata:
            # Keep old data for unchanged files
            new_metadata[file_path] = old_metadata[file_path]
        else:
            # Add new data for new/modified files
            new_metadata[file_path] = {
                "mtime": mtime,
                "chunk_count": 0,  # We don't track individual counts, but could
                "indexed_at": datetime.now().isoformat()
            }
    
    save_metadata(new_metadata)
    
    # --------
    # Phase 6: Get indexing statistics
    # --------
    logger.info("\n" + "="*80)
    logger.info("PHASE 6: Indexing Summary")
    logger.info("="*80)
    
    # Get total chunks in DB (use internal collection if available)
    total_chunks_in_db = 0
    if hasattr(chroma_client, '_collection'):
        try:
            total_chunks_in_db = chroma_client._collection.count()
        except Exception as e:
            logger.warning(f"⚠️ Could not count total chunks: {e}")
    
    logger.info(f"📊 Indexing Summary:")
    logger.info(f"   Total files in index: {len(current_files)}")
    logger.info(f"   Total chunks in DB: {total_chunks_in_db}")
    logger.info(f"   Chunks indexed this run: {total_indexed}")
    
    # --------
    # Phase 7: Example Queries
    # --------
    logger.info("\n" + "="*80)
    logger.info("PHASE 7: Example Queries")
    logger.info("="*80)
    
    example_queries = [
        "What are the core identity and values?",
        "Explain SQL patterns and best practices",
        "What are the key workflow rules?",
    ]
    
    for query in example_queries:
        results = query_docs(chroma_client, query, k=2)
        display_search_results(query, results)
    
    # --------
    # Done
    # --------
    logger.info("\n" + "="*80)
    logger.info("✅ Tutorial Complete!")
    logger.info("="*80)
    logger.info(f"\n💡 Next steps:")
    logger.info(f"   1. Try modifying a markdown file in {SOURCE_DOCS_DIR}")
    logger.info(f"   2. Run this script again to see incremental indexing")
    logger.info(f"   3. Try your own queries in the Python REPL:")
    logger.info(f"      >>> from 03_vector import *")
    logger.info(f"      >>> client = get_chroma_client()")
    logger.info(f"      >>> results = query_docs(client, 'your query here')")
    logger.info(f"      >>> display_search_results('your query here', results)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        exit(1)
