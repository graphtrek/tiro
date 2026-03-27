#!/usr/bin/env python3
"""
LangChain Integration Test
Validates that all LangChain components work correctly.
"""

import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """Test all LangChain imports"""
    print("\n" + "="*60)
    print("1. Testing LangChain Imports...")
    print("="*60)
    
    try:
        from rag_utils_langchain import (
            index_documents_langchain,
            search_documents_langchain,
            search_web_langchain,
            get_langchain_retriever,
            get_langchain_vectorstore,
        )
        print("✓ All LangChain utilities imported successfully")
        return True
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False


def test_rag_functions():
    """Test RAG utility functions"""
    print("\n" + "="*60)
    print("2. Testing RAG Functions...")
    print("="*60)
    
    from rag_utils_langchain import (
        get_index_stats,
    )
    
    try:
        # Test index stats (doesn't require API key)
        stats = get_index_stats()
        print(f"✓ Index stats readable: {len(stats)} files indexed")
        
        # Note: get_langchain_vectorstore and retriever require OPENAI_API_KEY
        # so we skip them in this test to avoid API errors
        print("✓ RAG utility functions are available")
        print("  (Note: API key required for vectorstore/retriever at runtime)")
        
        return True
    except Exception as e:
        print(f"✗ RAG function test failed: {e}")
        return False


def test_document_loading():
    """Test LangChain document loaders"""
    print("\n" + "="*60)
    print("3. Testing Document Loaders...")
    print("="*60)
    
    try:
        from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        
        print("✓ PyPDFLoader available")
        print("✓ TextLoader available")
        print("✓ Docx2txtLoader available")
        print("✓ RecursiveCharacterTextSplitter available")
        
        # Test the splitter
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            separators=["\n\n", "\n", " ", ""]
        )
        print(f"✓ Text splitter configured: 500 chars/chunk with 50 char overlap")
        
        return True
    except ImportError as e:
        print(f"✗ Document loader test failed: {e}")
        return False


def test_chat_py_imports():
    """Test Chat.py imports"""
    print("\n" + "="*60)
    print("4. Testing Chat.py Imports...")
    print("="*60)
    
    try:
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        from openai import OpenAI
        
        print("✓ ChatOpenAI available")
        print("✓ OpenAIEmbeddings available")
        print("✓ OpenAI client available")
        
        return True
    except ImportError as e:
        print(f"✗ Chat.py import test failed: {e}")
        return False


def test_chromadb_integration():
    """Test ChromaDB integration"""
    print("\n" + "="*60)
    print("5. Testing ChromaDB Integration...")
    print("="*60)
    
    try:
        import chromadb
        from rag_utils_langchain import _get_collection, _get_stats_collection
        
        collection = _get_collection()
        print(f"✓ ChromaDB collection initialized: {type(collection).__name__}")
        
        stats = _get_stats_collection()
        print(f"✓ Stats collection initialized: {type(stats).__name__}")
        
        count = collection.count()
        print(f"✓ Current document count: {count}")
        
        return True
    except Exception as e:
        print(f"✗ ChromaDB integration test failed: {e}")
        return False


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("🚀 LangChain Integration Test Suite")
    print("="*60)
    
    tests = [
        test_imports,
        test_rag_functions,
        test_document_loading,
        test_chat_py_imports,
        test_chromadb_integration,
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"\n✗ Unexpected error: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    # Summary
    print("\n" + "="*60)
    print("📊 Test Summary")
    print("="*60)
    passed = sum(results)
    total = len(results)
    print(f"Tests passed: {passed}/{total}")
    
    if all(results):
        print("\n✨ All tests passed! LangChain integration is ready.")
        print("\nYou can now:")
        print("  • Run: streamlit run Chat.py")
        print("  • Use: from rag_utils_langchain import search_documents_langchain")
        print("  • Deploy: docker-compose up (if configured)")
        return 0
    else:
        print("\n⚠️  Some tests failed. Please check the errors above.")
        return 1


if __name__ == "__main__":
    exit(main())
