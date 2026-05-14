"""
Moneypenny Agent - Multi-page Streamlit client.
Entry point with navigation to Chat, LLM, and RAG pages.
"""

import streamlit as st
import os
import logging
from datetime import datetime
from dotenv import load_dotenv

# Setup logging
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Setup logging
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

log_file = os.path.join(LOG_DIR, datetime.now().strftime("chat_%Y%m%d.log"))
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)-8s | %(filename)s:%(lineno)d | %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Log startup info
logger.info(f"📁 Log file: {log_file}")

# Page configuration
st.set_page_config(
    page_title="Moneypenny Agent",
    page_icon="💬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Minimal custom CSS
st.markdown("""
<style>
    .stChatMessage { max-width: 100%; }
</style>
""", unsafe_allow_html=True)


def main():
    """Main home page."""
    st.title("🤖 Moneypenny Agent")
    st.markdown("---")
    
    st.markdown("""
    ### Welcome to Moneypenny Agent
    
    Select a page from the menu above to get started:
    
    **📋 Chat** — Conversational chat with the Moneypenny Agent
    - Stream responses from the /stream endpoint
    - Full message history with timestamps
    - SQL results and visualizations
    
    **🤖 LLM Response** — Direct access to LLM endpoint
    - Send prompts to /llm-response endpoint
    - View structured JSON responses
    - Test LLM capabilities
    
    **🔍 RAG Search** — Document search via RAG
    - Search through documents with /search-documents endpoint
    - View search results in JSON format
    - Test document retrieval
    
    ---
    
    **Configuration:**
    - Base URL: http://localhost:8600
    - Request Timeout: 60s
    - Environment: Load from .env file
    """)
    
    st.markdown("---")
    st.info("💡 Use the horizontal menu bar at the top to navigate between pages.")


if __name__ == "__main__":
    logger.info("=" * 80)
    logger.info("🚀 Moneypenny Agent Started")
    logger.info("=" * 80)
    main()

