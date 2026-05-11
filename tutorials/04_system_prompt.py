"""
Tutorial 04: System Prompt + RAG Pattern
=========================================
Demonstrates that slim system prompts + smart context retrieval beats large monolithic prompts.

Key Concepts:
1. Load a lightweight base prompt (00_slim.md - ~431 tokens)
2. Implement hybrid keyword-based + semantic search routing (from index.md YAML)
3. Dynamically retrieve context from ChromaDB based on query type
4. Build LLM messages with system prompt + retrieved context + user query
5. Track token usage and retrieval performance

This tutorial shows RAG (Retrieval-Augmented Generation) is more effective than:
- Including all documentation in the system prompt (bloats token usage)
- Pure semantic search alone (can miss exact template matches)
- Static context routing (can't adapt to query variations)
"""

import logging
import json
import os
import re
import yaml
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
# STEP 1: Load the slim base prompt
# ============================================================================

def load_slim_prompt() -> str:
    """
    Load the lightweight system prompt from 00_slim.md.
    This is the base for all interactions - typically 300-500 tokens.
    """
    prompt_path = Path("/Users/Imre/PythonProjects/python-for-ai/nothing-gets-out/docs/prompt/core/00_slim.md")
    
    if not prompt_path.exists():
        logger.warning(f"⚠️  Slim prompt not found at {prompt_path}")
        return "You are a helpful AI assistant."
    
    content = prompt_path.read_text(encoding='utf-8')
    # Remove markdown heading
    content = re.sub(r'^#\s+.*\n', '', content, count=1).strip()
    
    logger.info(f"✅ Loaded slim prompt: {len(content)} chars, ~{len(content)//4} tokens")
    return content


# ============================================================================
# STEP 2: Load KAN router from index.md YAML frontmatter
# ============================================================================

def load_kan_router() -> Dict[str, Dict[str, any]]:
    """
    Parse YAML from index.md to get KAN templates and their keywords.
    Format: Each KAN has description and keywords list for keyword routing.
    
    Returns:
        {
            "KAN-1": {
                "description": "Legprofitábilisabb ügyfelek",
                "keywords": ["legprofitábilisabb", "top ügyfelek profit", ...]
            },
            ...
        }
    """
    index_path = Path("/Users/Imre/PythonProjects/python-for-ai/nothing-gets-out/docs/prompt/index.md")
    
    if not index_path.exists():
        logger.warning(f"⚠️  Index not found at {index_path}")
        return {}
    
    content = index_path.read_text(encoding='utf-8')
    
    # Extract YAML frontmatter (between --- markers)
    match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not match:
        logger.warning("⚠️  No YAML frontmatter found in index.md")
        return {}
    
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
        
        logger.info(f"✅ Loaded KAN router: {len(kan_router)} templates")
        return kan_router
    except yaml.YAMLError as e:
        logger.warning(f"⚠️  YAML parse error: {e}")
        return {}


# ============================================================================
# STEP 3: Keyword matching strategy (hybrid: exact + partial word matching)
# ============================================================================

def match_query_to_kan(user_query: str, kan_router: Dict) -> List[str]:
    """
    Match user query to KAN templates using hybrid strategy:
    1. Try exact substring match for each keyword
    2. Fall back to partial word matching (≥2 words from keyword in query)
    
    Args:
        user_query: The user's natural language query
        kan_router: Dict of KAN templates with keywords
    
    Returns:
        List of matched KAN IDs in priority order
    """
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
    
    return unique_matches


# ============================================================================
# STEP 4: Semantic search with dynamic search windows
# ============================================================================

def search_chroma(
    query: str,
    chroma_client: chromadb.PersistentClient,
    collection_filter: Optional[str] = None,
    top_k: int = 3
) -> List[Tuple[str, str, float]]:
    """
    Search ChromaDB with dynamic search windows based on filter type.
    
    Args:
        query: Search query
        chroma_client: ChromaDB client
        collection_filter: Filter by metadata (e.g., "kan", "KAN-1", "core")
        top_k: Number of results to return
    
    Returns:
        List of (chunk, source, score) tuples
    """
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
        return []
    
    # Dynamic search_k based on filter type
    # We search deeper when filtering to specific subsets
    if collection_filter and collection_filter.startswith("KAN-"):
        # For specific KAN templates: search aggressively through more results
        search_k = 100
        logger.debug(f"  🔍 Searching with search_k={search_k} for specific {collection_filter}")
    elif collection_filter == "kan":
        # For general "kan" category: search 60 results
        search_k = top_k * 20
        logger.debug(f"  🔍 Searching with search_k={search_k} for 'kan' category")
    elif collection_filter:
        # For other categories: search 30 results
        search_k = top_k * 10
        logger.debug(f"  🔍 Searching with search_k={search_k} for '{collection_filter}' category")
    else:
        # No filter: search 6 results
        search_k = top_k * 2
        logger.debug(f"  🔍 Searching with search_k={search_k} (no filter)")
    
    try:
        # Perform similarity search (no where filter - we'll filter after)
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
                # Check if source matches the filter exactly (e.g., "KAN-1" should match "prompt/kan/KAN-1.md" but NOT "KAN-11.md")
                # Use more precise matching to avoid KAN-1 matching KAN-11
                expected_filename = f"{collection_filter}.md"
                if not source.endswith(expected_filename) and expected_filename not in source:
                    filtered_out += 1
                    continue
            
            # Convert distance to similarity score (1.0 = most similar)
            # ChromaDB returns L2 Euclidean distance, so lower = better
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
        return chunks[:top_k]
    
    except Exception as e:
        logger.error(f"❌ Search error: {e}")
        return []


# ============================================================================
# STEP 5: Hybrid retrieval (keyword routing + semantic fallback)
# ============================================================================

def retrieve_context(
    user_message: str,
    chroma_client: chromadb.PersistentClient,
    kan_router: Dict,
    topic: str = "auto",
    top_k: int = 3
) -> Tuple[List[str], List[str]]:
    """
    Hybrid retrieval strategy:
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
        Tuple of (chunks list, sources list with indicators)
    """
    logger.info(f"📥 Retrieving context (topic={topic})...")
    
    chunks = []
    sources = []
    
    # Step 1: Try keyword routing for KAN templates
    if topic == "kan" and kan_router:
        matched_kans = match_query_to_kan(user_message, kan_router)
        logger.info(f"🔑 Keyword matching found: {matched_kans}")
        
        if matched_kans:
            # For each matched KAN, get one chunk from that document
            kan_results_summary = {}
            for kan_id in matched_kans[:top_k]:
                results = search_chroma(
                    user_message,
                    chroma_client,
                    collection_filter=kan_id,  # Use KAN-1 directly (not KAN_1)
                    top_k=1
                )
                if results:
                    logger.info(f"  ✓ {kan_id}: Retrieved from {results[0][1]}")
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
                logger.info(f"✅ Retrieved {len(chunks)} chunks via keyword routing")
                return chunks[:top_k], sources[:top_k]
    
    # Step 2: Fall back to semantic search for additional context
    remaining_needed = top_k - len(chunks)
    if remaining_needed > 0:
        logger.info(f"  ℹ️  Need {remaining_needed} more chunk(s) to reach top_k={top_k}, using semantic search...")
        
        if topic == "auto":
            # Broad search across all categories
            for category in ["kan", "core", "patterns"]:
                results = search_chroma(user_message, chroma_client, category, top_k=2)
                for chunk, source, score in results:
                    if not any(source in s for s in sources):  # Avoid duplicates
                        chunks.append(chunk)
                        sources.append(f"{source} (score: {score:.2f})")
                        if len(chunks) >= top_k:
                            break
        else:
            # Targeted semantic search
            results = search_chroma(user_message, chroma_client, topic, top_k=remaining_needed)
            for chunk, source, score in results:
                if not any(source in s for s in sources):  # Avoid duplicates
                    chunks.append(chunk)
                    sources.append(f"{source} (score: {score:.2f})")
        
        logger.info(f"  ℹ️  Semantic search added {len(chunks) - (len(sources) - remaining_needed)} chunk(s)")
    
    logger.info(f"✅ Retrieved {len(chunks)} chunks total ({len([s for s in sources if 'keyword' in s])} via keyword, {len([s for s in sources if 'score' in s])} via semantic)")
    return chunks[:top_k], sources[:top_k]


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
# STEP 6: Full RAG chat turn (system + context + user query)
# ============================================================================

def run_rag_chat(
    user_query: str,
    slim_prompt: str,
    chroma_client: chromadb.PersistentClient,
    kan_router: Dict,
    model_name: str = "gemma4:e4b",
    retrieval_topic: str = "auto"
) -> Dict:
    """
    Execute a complete RAG chat turn:
    1. Retrieve context chunks via hybrid strategy
    2. Build messages: [system prompt, user query with context]
    3. Call LLM
    4. Return response with metadata
    
    Args:
        user_query: The user's question
        slim_prompt: Lightweight system prompt (base instruction)
        chroma_client: ChromaDB client
        kan_router: KAN template router
        model_name: LLM model name (Ollama)
        retrieval_topic: What category to retrieve from
    
    Returns:
        {
            "response": str,
            "sources": List[str],
            "slim_prompt_tokens": int,
            "retrieved_context_tokens": int,
            "total_tokens": int
        }
    """
    logger.info(f"\n📨 RAG Chat Query: {user_query}")
    
    # Step 1: Retrieve context
    chunks, sources = retrieve_context(
        user_query,
        chroma_client,
        kan_router,
        topic=retrieval_topic,
        top_k=3
    )
    
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
    
    # Step 3: Call LLM (Ollama)
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
    print("="*70)
    
    return {
        "response": result_text,
        "sources": sources,
        "slim_prompt_tokens": slim_prompt_tokens,
        "retrieved_context_tokens": context_tokens,
        "total_tokens": total_tokens
    }


# ============================================================================
# STEP 7: Main tutorial execution
# ============================================================================

def main():
    """Execute the RAG tutorial with example queries."""
    logger.info("\n" + "="*70)
    logger.info("🎓 TUTORIAL 04: System Prompt + RAG Pattern")
    logger.info("="*70)
    
    # Step 0: Load KAN router
    logger.info("\n[STEP 0] Loading KAN router...")
    kan_router = load_kan_router()
    if kan_router:
        logger.info(f"  ✅ Loaded {len(kan_router)} KAN templates")
        for kan_id in sorted(kan_router.keys())[:3]:
            desc = kan_router[kan_id].get("description", "N/A")
            logger.info(f"     • {kan_id}: {desc}")
    
    # Step 1: Load slim prompt
    logger.info("\n[STEP 1] Loading slim system prompt...")
    slim_prompt = load_slim_prompt()
    
    # Step 2: Connect to ChromaDB
    logger.info("\n[STEP 2] Connecting to ChromaDB...")
    
    # Use absolute path to ensure it works from any directory
    tutorials_dir = Path(__file__).parent.absolute()
    persist_path = str(tutorials_dir / "chroma_db")
    
    try:
        chroma_client = chromadb.PersistentClient(path=persist_path)
        collections = [c.name for c in chroma_client.list_collections()]
        logger.info(f"  ✅ Connected to ChromaDB at {persist_path}")
        logger.info(f"  📦 Collections: {collections}")
        if not collections:
            logger.warning(f"  ⚠️  No collections found. Run 03_vector.py to create them.")
    except Exception as e:
        logger.error(f"  ❌ ChromaDB connection failed: {e}")
        return
    
    # Step 3: Check Ollama availability
    logger.info("\n[STEP 3] Checking Ollama availability...")
    ollama_available = check_ollama_available()
    if ollama_available:
        logger.info("  ✅ Ollama is running at http://localhost:11434")
    else:
        logger.warning("  ⚠️  Ollama is not running!")
        logger.warning("     To see LLM responses, start Ollama with: ollama serve")
        logger.warning("     For now, responses will show as empty.")
    
    # Step 4: Run example queries
    logger.info("\n[STEP 4] Running RAG queries...")
    
    # Query 1: KAN template (profitable customers)
    run_rag_chat(
        user_query="Melyik ügyfél a legjobb profitábilisabb?",
        slim_prompt=slim_prompt,
        chroma_client=chroma_client,
        kan_router=kan_router,
        retrieval_topic="kan"
    )
    
    # Query 2: Core workflow question
    run_rag_chat(
        user_query="Mik a korlátok az SQL lekérdezéseknél?",
        slim_prompt=slim_prompt,
        chroma_client=chroma_client,
        kan_router=kan_router,
        retrieval_topic="core"
    )
    
    logger.info("\n✅ Tutorial complete!")


if __name__ == "__main__":
    main()
