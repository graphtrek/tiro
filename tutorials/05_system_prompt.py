"""
Tutorial 05: System Prompt + RAG Pattern with Caching & Performance Timing
===========================================================================
Enhanced version of 04_system_prompt.py with:
- Module-level caching for slim prompt, KAN router, and ChromaDB client
- Comprehensive execution timing to identify bottlenecks
- Optional --clear-cache flag for testing

When run as a long-running service, caching reduces repeated I/O and connection overhead.
Performance metrics help identify whether bottlenecks are I/O, ChromaDB retrieval, or LLM.

Usage:
  python 05_system_prompt.py           # Run with caching
  python 05_system_prompt.py --clear-cache  # Clear caches and run fresh
"""

import logging
import json
import os
import re
import yaml
import sys
import time
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from datetime import datetime

import chromadb
from chromadb.utils import embedding_functions
from openai import OpenAI
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)
load_dotenv()

# ============================================================================
# MODULE-LEVEL CACHING
# ============================================================================

# Global cache dict for slim prompt and KAN router
_cache: dict = {
    "slim_prompt": None,
    "kan_router": None,
    "loaded_at": None,
}

# Singleton ChromaDB client (separate from _cache for simplicity)
_chroma_client_cache: Optional[chromadb.PersistentClient] = None


def _invalidate_cache() -> None:
    """Clear all module-level caches."""
    global _cache, _chroma_client_cache
    _cache = {
        "slim_prompt": None,
        "kan_router": None,
        "loaded_at": None,
    }
    _chroma_client_cache = None
    logger.info("[cache] Cleared all caches")


def _get_chroma_client() -> Optional[chromadb.PersistentClient]:
    """Get or lazily initialize the ChromaDB client (singleton pattern)."""
    global _chroma_client_cache
    
    if _chroma_client_cache is not None:
        logger.debug("[chroma_client] Cache HIT — returning cached client")
        return _chroma_client_cache
    
    logger.debug("[chroma_client] Cache MISS — initializing PersistentClient...")
    
    tutorials_dir = Path(__file__).parent.absolute()
    persist_path = str(tutorials_dir / "chroma_db")
    
    try:
        _chroma_client_cache = chromadb.PersistentClient(path=persist_path)
        collections = [c.name for c in _chroma_client_cache.list_collections()]
        logger.debug(f"[chroma_client] Connected to {persist_path}, collections: {collections}")
        return _chroma_client_cache
    except Exception as e:
        logger.error(f"[chroma_client] Failed to initialize: {e}")
        return None


# ============================================================================
# STEP 1: Load the slim base prompt (with caching)
# ============================================================================

def load_slim_prompt() -> str:
    """
    Load the lightweight system prompt from 00_slim.md.
    Cached at module level — only reads from disk on first call.
    
    Returns:
        Cached slim prompt string
    """
    if _cache["slim_prompt"] is not None:
        logger.info(f"[load_slim_prompt] Cache HIT — slim_prompt_cached ({len(_cache['slim_prompt'])} chars)")
        return _cache["slim_prompt"]
    
    logger.info("[load_slim_prompt] Cache MISS — Loading from disk...")
    prompt_path = Path("/Users/Imre/PythonProjects/python-for-ai/nothing-gets-out/docs/prompt/core/00_slim.md")
    
    if not prompt_path.exists():
        logger.warning(f"⚠️  Slim prompt not found at {prompt_path}")
        _cache["slim_prompt"] = "You are a helpful AI assistant."
        return _cache["slim_prompt"]
    
    content = prompt_path.read_text(encoding='utf-8')
    # Remove markdown heading
    content = re.sub(r'^#\s+.*\n', '', content, count=1).strip()
    
    _cache["slim_prompt"] = content
    _cache["loaded_at"] = datetime.now()
    
    logger.info(f"✅ Loaded slim prompt: {len(content)} chars, ~{len(content)//4} tokens")
    return content


# ============================================================================
# STEP 2: Load KAN router from index.md YAML frontmatter (with caching)
# ============================================================================

def load_kan_router() -> Dict[str, Dict[str, any]]:
    """
    Parse YAML from index.md to get KAN templates and their keywords.
    Cached at module level — only parses YAML on first call.
    
    Returns:
        {
            "KAN-1": {
                "description": "Legprofitábilisabb ügyfelek",
                "keywords": ["legprofitábilisabb", "top ügyfelek profit", ...]
            },
            ...
        }
    """
    if _cache["kan_router"] is not None:
        logger.info(f"[load_kan_router] Cache HIT — kan_router_cached ({len(_cache['kan_router'])} templates)")
        return _cache["kan_router"]
    
    logger.info("[load_kan_router] Cache MISS — Loading from disk...")
    index_path = Path("/Users/Imre/PythonProjects/python-for-ai/nothing-gets-out/docs/prompt/index.md")
    
    if not index_path.exists():
        logger.warning(f"⚠️  Index not found at {index_path}")
        _cache["kan_router"] = {}
        return _cache["kan_router"]
    
    content = index_path.read_text(encoding='utf-8')
    
    # Extract YAML frontmatter (between --- markers)
    match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not match:
        logger.warning("⚠️  No YAML frontmatter found in index.md")
        _cache["kan_router"] = {}
        return _cache["kan_router"]
    
    try:
        frontmatter = yaml.safe_load(match.group(1))
        kan_router = {}
        
        # Parse KAN entries (they may be nested under "kan_routes" key)
        if isinstance(frontmatter, dict):
            # Check for nested kan_routes
            if "kan_routes" in frontmatter:
                kan_data = frontmatter["kan_routes"]
                if isinstance(kan_data, dict):
                    kan_router = {k: v for k, v in kan_data.items() if k.startswith("KAN-")}
            else:
                # Otherwise look for KAN- keys at root level
                kan_router = {k: v for k, v in frontmatter.items() if k.startswith("KAN-")}
        
        _cache["kan_router"] = kan_router
        _cache["loaded_at"] = datetime.now()
        
        logger.info(f"✅ Loaded KAN router: {len(kan_router)} templates")
        return kan_router
    except yaml.YAMLError as e:
        logger.warning(f"⚠️  YAML parse error: {e}")
        _cache["kan_router"] = {}
        return _cache["kan_router"]


# ============================================================================
# STEP 3: Keyword matching strategy with timing
# ============================================================================

def match_query_to_kan(user_query: str, kan_router: Dict) -> Tuple[List[str], float]:
    """
    Match user query to KAN templates using hybrid strategy:
    1. Try exact substring match for each keyword
    2. Fall back to partial word matching (≥2 words from keyword in query)
    
    Args:
        user_query: The user's natural language query
        kan_router: Dict of KAN templates with keywords
    
    Returns:
        Tuple of (matched KAN IDs list, execution_time_ms float)
    """
    _start = time.time()
    
    matches = []
    query_lower = user_query.lower()
    query_words = set(query_lower.split())
    
    for kan_id, kan_info in kan_router.items():
        keywords = kan_info.get("keywords", [])
        
        for keyword in keywords:
            keyword_lower = keyword.lower()
            
            # Strategy 1: Exact substring match
            if keyword_lower in query_lower:
                matches.append(kan_id)
                logger.debug(f"  ✓ {kan_id}: exact match '{keyword}'")
                break
            
            # Strategy 2: Partial word matching (≥2 words from keyword in query)
            keyword_words = set(keyword_lower.split())
            matching_words = keyword_words & query_words
            
            if len(matching_words) >= 2:
                matches.append(kan_id)
                logger.debug(f"  ✓ {kan_id}: partial match ({len(matching_words)} words from '{keyword}')")
                break
    
    # Remove duplicates while preserving order
    seen = set()
    unique_matches = []
    for m in matches:
        if m not in seen:
            unique_matches.append(m)
            seen.add(m)
    
    _elapsed = time.time() - _start
    logger.debug(f"[match_query_to_kan] ⏱️ {_elapsed*1000:.1f}ms | matches: {len(unique_matches)}")
    
    return unique_matches, _elapsed * 1000


# ============================================================================
# STEP 4: Semantic search with dynamic search windows and timing
# ============================================================================

def search_chroma(
    query: str,
    chroma_client: chromadb.PersistentClient,
    collection_filter: Optional[str] = None,
    top_k: int = 3
) -> Tuple[List[Tuple[str, str, float]], float]:
    """
    Search ChromaDB with dynamic search windows based on filter type.
    
    Args:
        query: Search query
        chroma_client: ChromaDB client
        collection_filter: Filter by metadata (e.g., "kan", "KAN-1", "core")
        top_k: Number of results to return
    
    Returns:
        Tuple of (results list, execution_time_ms float)
        where results = [(chunk, source, score), ...]
    """
    _start = time.time()
    
    try:
        collection = chroma_client.get_collection(
            name="prompt_docs",
            embedding_function=embedding_functions.DefaultEmbeddingFunction()
        )
    except Exception as e:
        # Provide detailed diagnostic info
        try:
            available = [c.name for c in chroma_client.list_collections()]
            logger.error(f"❌ ChromaDB error: {e}")
            logger.error(f"   Available collections: {available}")
            logger.error(f"   Trying to access: 'prompt_docs'")
        except Exception as diag_error:
            logger.error(f"❌ ChromaDB error: {e}")
            logger.error(f"   Could not list collections: {diag_error}")
        return [], 0.0
    
    # Dynamic search_k based on filter type
    if collection_filter and collection_filter.startswith("KAN-"):
        search_k = 100
        logger.debug(f"  🔍 Searching with search_k={search_k} for specific {collection_filter}")
    elif collection_filter == "kan":
        search_k = top_k * 20
        logger.debug(f"  🔍 Searching with search_k={search_k} for 'kan' category")
    elif collection_filter:
        search_k = top_k * 10
        logger.debug(f"  🔍 Searching with search_k={search_k} for '{collection_filter}' category")
    else:
        search_k = top_k * 2
        logger.debug(f"  🔍 Searching with search_k={search_k} (no filter)")
    
    try:
        # Perform similarity search
        results = collection.query(
            query_texts=[query],
            n_results=search_k
        )
        
        # Extract and score results
        chunks = []
        filtered_out = 0
        
        for i, (doc, metadata, distance) in enumerate(zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0]
        )):
            source = metadata.get("source", "Unknown")
            
            # Post-filter by source path if filter specified
            if collection_filter:
                expected_filename = f"{collection_filter}.md"
                if not source.endswith(expected_filename) and expected_filename not in source:
                    filtered_out += 1
                    continue
            
            # Convert distance to similarity score (1.0 = most similar)
            similarity_score = 1.0 / (1.0 + distance)
            
            # Adjust score based on window size (penalize results deeper in the window)
            if search_k > 50:
                score = similarity_score * (1.0 - i * 0.01)  # Gentle penalty
            else:
                score = similarity_score * (1.0 - i * 0.05)  # Steeper penalty
            
            chunks.append((doc, source, score))
            
            if len(chunks) <= top_k:
                logger.debug(f"    [{len(chunks)}] {source}: {score:.3f}")
            
            # Early exit if we have enough chunks
            if len(chunks) >= top_k:
                break
        
        if collection_filter and filtered_out > 0:
            logger.debug(f"  ℹ️  Filtered out {filtered_out} results not matching '{collection_filter}'")
        
        # Sort by score and return top_k
        chunks.sort(key=lambda x: x[2], reverse=True)
        result_chunks = chunks[:top_k]
        
        _elapsed = time.time() - _start
        logger.debug(f"[search_chroma] ⏱️ {_elapsed*1000:.1f}ms | results: {len(result_chunks)} | filter: {collection_filter or 'none'}")
        
        return result_chunks, _elapsed * 1000
    
    except Exception as e:
        logger.error(f"❌ Search error: {e}")
        return [], 0.0


# ============================================================================
# STEP 5: Hybrid retrieval (keyword routing + semantic fallback) with timing
# ============================================================================

def retrieve_context(
    user_message: str,
    chroma_client: chromadb.PersistentClient,
    kan_router: Dict,
    topic: str = "auto",
    top_k: int = 3
) -> Tuple[List[str], List[str], Dict[str, float]]:
    """
    Hybrid retrieval strategy with performance timing:
    1. For KAN queries: try keyword routing first
    2. If no matches or for other topics: use semantic search
    3. Fall back to semantic search if not enough chunks found
    
    Args:
        user_message: User query
        chroma_client: ChromaDB client
        kan_router: KAN template router from index.md
        topic: Query topic ("kan", "core", "patterns", "auto")
        top_k: Number of chunks to retrieve
    
    Returns:
        Tuple of (chunks list, sources list, timing dict)
        where timing = {"keyword_ms": float, "semantic_ms": float, "total_ms": float}
    """
    _start_total = time.time()
    logger.info(f"📥 Retrieving context (topic={topic})...")
    
    chunks = []
    sources = []
    timing = {"keyword_ms": 0.0, "semantic_ms": 0.0, "total_ms": 0.0}
    
    # Step 1: Try keyword routing for KAN templates
    if topic == "kan" and kan_router:
        matched_kans, keyword_time = match_query_to_kan(user_message, kan_router)
        timing["keyword_ms"] = keyword_time
        logger.info(f"🔑 Keyword matching found: {matched_kans} ({keyword_time:.1f}ms)")
        
        if matched_kans:
            # For each matched KAN, get one chunk from that document
            kan_results_summary = {}
            for kan_id in matched_kans[:top_k]:
                results, search_time = search_chroma(
                    user_message,
                    chroma_client,
                    collection_filter=kan_id,
                    top_k=1
                )
                timing["semantic_ms"] += search_time
                
                if results:
                    logger.info(f"  ✓ {kan_id}: Retrieved from {results[0][1]} ({search_time:.1f}ms)")
                    kan_results_summary[kan_id] = "✓"
                    for chunk, source, score in results:
                        chunks.append(chunk)
                        sources.append(f"{source} (keyword match ✓)")
                else:
                    logger.info(f"  ✗ {kan_id}: No semantic match found (will be skipped)")
                    kan_results_summary[kan_id] = "✗"
            
            logger.info(f"  ℹ️  KAN results: {kan_results_summary} | Total: {len(chunks)} chunks")
            
            # If we found enough chunks via keyword routing, return them
            if len(chunks) >= top_k:
                _elapsed_total = (time.time() - _start_total) * 1000
                timing["total_ms"] = _elapsed_total
                logger.info(f"✅ Retrieved {len(chunks)} chunks via keyword routing ({_elapsed_total:.1f}ms total)")
                return chunks[:top_k], sources[:top_k], timing
    
    # Step 2: Fall back to semantic search for additional context
    remaining_needed = top_k - len(chunks)
    if remaining_needed > 0:
        logger.info(f"  ℹ️  Need {remaining_needed} more chunk(s) to reach top_k={top_k}, using semantic search...")
        
        _semantic_start = time.time()
        
        if topic == "auto":
            # Broad search across all categories
            for category in ["kan", "core", "patterns"]:
                results, search_time = search_chroma(user_message, chroma_client, category, top_k=2)
                timing["semantic_ms"] += search_time
                for chunk, source, score in results:
                    if not any(source in s for s in sources):  # Avoid duplicates
                        chunks.append(chunk)
                        sources.append(f"{source} (score: {score:.2f})")
                        if len(chunks) >= top_k:
                            break
        else:
            # Targeted semantic search
            results, search_time = search_chroma(user_message, chroma_client, topic, top_k=remaining_needed)
            timing["semantic_ms"] += search_time
            for chunk, source, score in results:
                if not any(source in s for s in sources):  # Avoid duplicates
                    chunks.append(chunk)
                    sources.append(f"{source} (score: {score:.2f})")
        
        _semantic_elapsed = (time.time() - _semantic_start) * 1000
        logger.info(f"  ℹ️  Semantic search added {len(chunks) - len([s for s in sources if 'keyword' in s])} chunk(s) ({_semantic_elapsed:.1f}ms)")
    
    _elapsed_total = (time.time() - _start_total) * 1000
    timing["total_ms"] = _elapsed_total
    
    keyword_count = len([s for s in sources if 'keyword' in s])
    semantic_count = len([s for s in sources if 'score' in s])
    logger.info(f"✅ Retrieved {len(chunks)} chunks total | keyword: {keyword_count} | semantic: {semantic_count} | ⏱️ {_elapsed_total:.1f}ms")
    
    return chunks[:top_k], sources[:top_k], timing


# ============================================================================
# Utility: Check Ollama availability
# ============================================================================

def check_ollama_available(timeout: int = 5) -> bool:
    """
    Check if Ollama is running and accessible.
    
    Returns:
        True if Ollama is available, False otherwise
    """
    try:
        import requests
        url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        response = requests.get(f"{url}/api/tags", timeout=timeout)
        return response.status_code == 200
    except Exception:
        return False


# ============================================================================
# STEP 6: Full RAG chat turn (system + context + user query) with timing
# ============================================================================

def run_rag_chat(
    user_query: str,
    slim_prompt: str,
    kan_router: Dict,
    chroma_client: Optional[chromadb.PersistentClient] = None,
    model_name: str = "gemma4:e4b",
    retrieval_topic: str = "auto"
) -> Dict:
    """
    Execute a complete RAG chat turn with performance timing:
    1. Retrieve context chunks via hybrid strategy
    2. Build messages: [system prompt, user query with context]
    3. Call LLM
    4. Return response with metadata and timing breakdown
    
    Args:
        user_query: The user's question
        slim_prompt: Lightweight system prompt (base instruction)
        kan_router: KAN template router
        chroma_client: ChromaDB client (optional; uses cached client if None)
        model_name: LLM model name (Ollama)
        retrieval_topic: What category to retrieve from
    
    Returns:
        {
            "response": str,
            "sources": List[str],
            "slim_prompt_tokens": int,
            "retrieved_context_tokens": int,
            "total_tokens": int,
            "execution_time_ms": {
                "retrieval_ms": float,
                "llm_ms": float,
                "total_ms": float
            }
        }
    """
    _start_total = time.time()
    logger.info(f"\n📨 RAG Chat Query: {user_query}")
    
    # Use cached client if not provided
    if chroma_client is None:
        chroma_client = _get_chroma_client()
        if chroma_client is None:
            logger.error("❌ ChromaDB client unavailable")
            return {
                "response": "(ChromaDB unavailable)",
                "sources": [],
                "slim_prompt_tokens": 0,
                "retrieved_context_tokens": 0,
                "total_tokens": 0,
                "execution_time_ms": {"retrieval_ms": 0.0, "llm_ms": 0.0, "total_ms": 0.0}
            }
    
    # Step 1: Retrieve context
    _start_retrieval = time.time()
    chunks, sources, retrieval_timing = retrieve_context(
        user_query,
        chroma_client,
        kan_router,
        topic=retrieval_topic,
        top_k=3
    )
    _retrieval_elapsed = (time.time() - _start_retrieval) * 1000
    
    # Build context string
    context_str = "\n\n".join(chunks) if chunks else "(No context found)"
    
    # Estimate tokens (rough: ~4 chars per token)
    slim_prompt_tokens = len(slim_prompt) // 4
    context_tokens = len(context_str) // 4
    total_tokens = slim_prompt_tokens + context_tokens + len(user_query) // 4
    
    # Step 2: Build LLM messages
    system_message = f"""{slim_prompt}

---
RETRIEVED CONTEXT:
{context_str}
---"""
    
    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_query}
    ]
    
    # Step 3: Call LLM (Ollama) with timing
    _start_llm = time.time()
    try:
        client = OpenAI(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
            timeout=30.0  # 30 second timeout to prevent hanging
        )
        
        logger.info(f"  🤖 Calling LLM (model={model_name}, timeout=30s)...")
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.7,
            max_tokens=500
        )
        
        result_text = response.choices[0].message.content
        logger.info(f"  ✅ LLM response received ({len(result_text)} chars)")
    except TimeoutError:
        logger.error(f"❌ LLM timeout: Ollama did not respond within 30 seconds")
        logger.error(f"   Is Ollama running? Check: curl http://localhost:11434/api/tags")
        result_text = "(LLM timeout: Ollama not responding. Is it running?)"
    except Exception as e:
        logger.error(f"❌ LLM error: {e}")
        result_text = f"(LLM unavailable: {str(e)})"
    
    _llm_elapsed = (time.time() - _start_llm) * 1000
    _total_elapsed = (time.time() - _start_total) * 1000
    
    # Step 4: Format output
    print("\n" + "="*70)
    print("📊 RAG CHAT RESULT")
    print("="*70)
    print(f"Query: {user_query}\n")
    
    print("Retrieved Sources:")
    for i, source in enumerate(sources, 1):
        print(f"  {i}. {source}")
    
    print(f"\n💭 Response:\n{result_text}")
    
    print(f"\n📈 Tokens Used:")
    print(f"  • System Prompt: ~{slim_prompt_tokens} tokens")
    print(f"  • Retrieved Context: ~{context_tokens} tokens")
    print(f"  • Query: ~{len(user_query)//4} tokens")
    print(f"  • TOTAL: ~{total_tokens} tokens")
    
    print(f"\n⏱️  Execution Time:")
    print(f"  • Retrieval: {_retrieval_elapsed:.1f}ms (keyword: {retrieval_timing['keyword_ms']:.1f}ms + semantic: {retrieval_timing['semantic_ms']:.1f}ms)")
    print(f"  • LLM: {_llm_elapsed:.1f}ms")
    print(f"  • TOTAL: {_total_elapsed:.1f}ms")
    print("="*70)
    
    logger.info(f"[run_rag_chat] ⏱️ Total: {_total_elapsed:.1f}ms (retrieval: {_retrieval_elapsed:.1f}ms + llm: {_llm_elapsed:.1f}ms)")
    
    return {
        "response": result_text,
        "sources": sources,
        "slim_prompt_tokens": slim_prompt_tokens,
        "retrieved_context_tokens": context_tokens,
        "total_tokens": total_tokens,
        "execution_time_ms": {
            "retrieval_ms": _retrieval_elapsed,
            "llm_ms": _llm_elapsed,
            "total_ms": _total_elapsed
        }
    }


# ============================================================================
# STEP 7: Main tutorial execution with cache statistics
# ============================================================================

def main():
    """Execute the RAG tutorial with example queries and performance summary."""
    
    # Parse command-line arguments
    if "--clear-cache" in sys.argv:
        logger.info("[main] Clearing caches due to --clear-cache flag")
        _invalidate_cache()
    
    logger.info("\n" + "="*70)
    logger.info("🎓 TUTORIAL 05: System Prompt + RAG Pattern (with Caching & Timing)")
    logger.info("="*70)
    
    # Step 0: Load KAN router (cached)
    logger.info("\n[STEP 0] Loading KAN router (with caching)...")
    kan_router = load_kan_router()
    if kan_router:
        logger.info(f"  ✅ Loaded {len(kan_router)} KAN templates")
        for kan_id in sorted(kan_router.keys())[:3]:
            desc = kan_router[kan_id].get("description", "N/A")
            logger.info(f"     • {kan_id}: {desc}")
    
    # Step 1: Load slim prompt (cached)
    logger.info("\n[STEP 1] Loading slim system prompt (with caching)...")
    slim_prompt = load_slim_prompt()
    
    # Step 2: Get ChromaDB client (cached singleton)
    logger.info("\n[STEP 2] Getting ChromaDB client (with caching)...")
    chroma_client = _get_chroma_client()
    if chroma_client is None:
        logger.error("❌ Failed to initialize ChromaDB client")
        return
    
    collections = [c.name for c in chroma_client.list_collections()]
    logger.info(f"  📦 Collections: {collections}")
    if not collections:
        logger.warning(f"  ⚠️  No collections found. Run 03_vector.py to create them.")
    
    # Step 3: Check Ollama availability
    logger.info("\n[STEP 3] Checking Ollama availability...")
    ollama_available = check_ollama_available()
    if ollama_available:
        logger.info("  ✅ Ollama is running at http://localhost:11434")
    else:
        logger.warning("  ⚠️  Ollama is not running!")
        logger.warning("     To see LLM responses, start Ollama with: ollama serve")
        logger.warning("     For now, responses will show as empty.")
    
    # Step 4: Run example queries with timing
    logger.info("\n[STEP 4] Running RAG queries with performance timing...")
    
    query_results = []
    
    # Query 1: KAN template (profitable customers)
    result1 = run_rag_chat(
        user_query="Melyik ügyfél a legjobb profitábilisabb?",
        slim_prompt=slim_prompt,
        kan_router=kan_router,
        chroma_client=chroma_client,
        retrieval_topic="kan"
    )
    query_results.append({
        "query": "Melyik ügyfél a legjobb profitábilisabb?",
        "retrieval_ms": result1["execution_time_ms"]["retrieval_ms"],
        "llm_ms": result1["execution_time_ms"]["llm_ms"],
        "total_ms": result1["execution_time_ms"]["total_ms"]
    })
    
    # Query 2: Core workflow question
    result2 = run_rag_chat(
        user_query="Mik a korlátok az SQL lekérdezéseknél?",
        slim_prompt=slim_prompt,
        kan_router=kan_router,
        chroma_client=chroma_client,
        retrieval_topic="core"
    )
    query_results.append({
        "query": "Mik a korlátok az SQL lekérdezéseknél?",
        "retrieval_ms": result2["execution_time_ms"]["retrieval_ms"],
        "llm_ms": result2["execution_time_ms"]["llm_ms"],
        "total_ms": result2["execution_time_ms"]["total_ms"]
    })
    
    # Step 5: Print performance summary
    logger.info("\n" + "="*70)
    logger.info("📊 PERFORMANCE SUMMARY")
    logger.info("="*70)
    print(f"\n{'Query':<50} {'Retrieval (ms)':<15} {'LLM (ms)':<15} {'Total (ms)':<15}")
    print("-" * 95)
    for i, result in enumerate(query_results, 1):
        query_short = result["query"][:47] + "..." if len(result["query"]) > 50 else result["query"]
        print(f"{query_short:<50} {result['retrieval_ms']:<15.1f} {result['llm_ms']:<15.1f} {result['total_ms']:<15.1f}")
    
    total_retrieval = sum(r["retrieval_ms"] for r in query_results)
    total_llm = sum(r["llm_ms"] for r in query_results)
    total_time = sum(r["total_ms"] for r in query_results)
    
    print("-" * 95)
    print(f"{'TOTAL':<50} {total_retrieval:<15.1f} {total_llm:<15.1f} {total_time:<15.1f}")
    print("="*70 + "\n")
    
    logger.info("✅ Tutorial complete!")
    logger.info(f"   Total execution: {total_time:.1f}ms (retrieval: {total_retrieval:.1f}ms, llm: {total_llm:.1f}ms)")


if __name__ == "__main__":
    main()
