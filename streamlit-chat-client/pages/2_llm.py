"""
LLM Page - Direct LLM endpoint for testing.
"""

import streamlit as st
import requests
import json
import os
import logging
from datetime import datetime
from dotenv import load_dotenv

# Setup logging
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Configuration
BASE_URL = os.getenv("BASE_URL", "http://localhost:8600")
LLM_ENDPOINT = f"{BASE_URL}/llm-response"
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "300"))  # 5 minutes default

# Page configuration
st.set_page_config(
    page_title="LLM Endpoint",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Minimal custom CSS
st.markdown("""
<style>
    .stChatMessage { max-width: 100%; }
</style>
""", unsafe_allow_html=True)


def init_session_state():
    """Initialize Streamlit session state."""
    if "llm_messages" not in st.session_state:
        st.session_state.llm_messages = []
    if "llm_responses" not in st.session_state:
        st.session_state.llm_responses = []


def main():
    """Main LLM page logic."""
    init_session_state()
    
    # Header
    st.title("🤖 LLM Response")
    st.markdown("Direct access to /llm-response endpoint")
    
    # Show endpoint configuration
    with st.expander("⚙️ Configuration", expanded=False):
        st.code(f"Endpoint: {LLM_ENDPOINT}\nTimeout: {REQUEST_TIMEOUT}s", language="text")
        
        # Connection test button
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("🔌 Test Connection", key="test_llm"):
                with st.spinner("Testing connection..."):
                    try:
                        response = requests.get(
                            BASE_URL,
                            timeout=5,
                        )
                        st.success(f"✅ Server is reachable (status: {response.status_code})")
                    except requests.exceptions.ConnectionError:
                        st.error(f"❌ Cannot connect to {BASE_URL}")
                        st.info("Make sure the moneypenny-agent server is running on port 8600")
                    except Exception as e:
                        st.error(f"❌ Error: {str(e)}")
    
    st.markdown("---")
    
    # Chat area
    chat_container = st.container()
    
    with chat_container:
        # Display history
        if st.session_state.llm_messages:
            for i, resp in enumerate(st.session_state.llm_responses):
                if resp is None:
                    st.error("❌ Failed to get response")
                elif isinstance(resp, dict):
                    st.json(resp)
                elif isinstance(resp, str):
                    st.code(resp, language="json")
                else:
                    st.code(str(resp), language="json")
                
                st.divider()
        else:
            st.info("💡 No responses yet. Send a prompt to get started.")
    
    # Input area
    st.markdown("---")
    
    user_input = st.text_input(
        "Your prompt:",
        placeholder="Type your prompt here...",
        key="llm_user_input",
    )
    
    col1, col2 = st.columns([4, 1])
    with col1:
        send_button = st.button("Send", use_container_width=True)
    with col2:
        if st.button("🗑️ Clear", use_container_width=True):
            logger.info(f"[CLEAR] Cleared {len(st.session_state.llm_messages)} messages")
            st.session_state.llm_messages = []
            st.session_state.llm_responses = []
            st.rerun()
    
    if send_button and user_input.strip():
        # Add to history
        st.session_state.llm_messages.append(user_input)
        logger.info(f"[LLM_REQUEST] Calling {LLM_ENDPOINT} with prompt: {user_input[:100]}")
        
        # Show loading state
        with st.spinner(f"Calling {LLM_ENDPOINT}..."):
            try:
                payload = {"message": user_input}
                logger.info(f"[LLM_REQUEST] Payload: {payload}")
                
                response = requests.post(
                    LLM_ENDPOINT,
                    json=payload,
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                
                logger.info(f"[LLM_SUCCESS] status={response.status_code}")
                
                # Parse response
                try:
                    json_response = response.json()
                    st.session_state.llm_responses.append(json_response)
                    logger.info(f"[LLM_RESPONSE] {json.dumps(json_response)[:100]}")
                except json.JSONDecodeError:
                    # Response is not JSON, store as-is
                    st.session_state.llm_responses.append(response.text)
                    logger.warning(f"[LLM_NON_JSON] {response.text[:100]}")
                
                st.rerun()
                
            except requests.exceptions.ConnectionError as e:
                error_msg = f"❌ Cannot connect to {LLM_ENDPOINT}"
                logger.error(f"[ERROR] ConnectionError: {error_msg}")
                st.session_state.llm_responses.append(None)
                st.error(error_msg)
                st.info("Make sure the moneypenny-agent server is running:\n```bash\ncd nothing-gets-out && uvicorn manager_api:app --port 8600\n```")
                st.rerun()
            except requests.exceptions.Timeout:
                error_msg = f"❌ Request timeout (>{REQUEST_TIMEOUT}s)"
                logger.error(f"[ERROR] Timeout: {error_msg}")
                st.session_state.llm_responses.append(None)
                st.error(error_msg)
                st.info("The endpoint is taking too long to respond. Check if the server is processing a heavy request.")
                st.rerun()
            except requests.exceptions.HTTPError as e:
                error_msg = f"❌ HTTP {e.response.status_code}"
                details = e.response.text[:500]
                logger.error(f"[ERROR] HTTPError: {error_msg} - {details}")
                st.session_state.llm_responses.append(None)
                st.error(error_msg)
                with st.expander("📋 Error Details"):
                    st.code(details, language="json")
                st.rerun()
            except Exception as e:
                error_msg = f"❌ Error: {str(e)}"
                logger.error(f"[ERROR] {error_msg}")
                st.session_state.llm_responses.append(None)
                st.error(error_msg)
                with st.expander("📋 Full Error"):
                    st.code(str(e), language="text")
                st.rerun()


if __name__ == "__main__":
    logger.info("=" * 80)
    logger.info("🤖 LLM Page Started")
    logger.info(f"   Endpoint: {LLM_ENDPOINT}")
    logger.info(f"   Timeout: {REQUEST_TIMEOUT}s")
    logger.info("=" * 80)
    main()
