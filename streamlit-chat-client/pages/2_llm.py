"""
LLM Page - Direct LLM response endpoint (no tools, no multi-step reasoning).
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
AGENT_ENDPOINT = f"{BASE_URL}/llm-response"
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "300"))  # 5 minutes default

# Page configuration
st.set_page_config(
    page_title="LLM Response",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Minimal custom CSS
st.markdown("""
<style>
    .stChatMessage { max-width: 100%; }
    .response-field { 
        border-left: 4px solid #0066cc; 
        padding: 12px; 
        margin: 8px 0;
        background-color: #f0f7ff;
        border-radius: 4px;
    }
    .response-label {
        font-weight: bold;
        color: #0066cc;
        margin-bottom: 8px;
    }
</style>
""", unsafe_allow_html=True)


def display_llm_response(response_obj):
    """Display LLM response."""
    if response_obj is None:
        st.error("❌ Failed to get response")
        return
    
    if isinstance(response_obj, str):
        st.error(response_obj)
        return
    
    if not isinstance(response_obj, dict):
        st.json(response_obj)
        return
    
    # Display elapsed time
    st.metric("⏱️ Response Time (ms)", response_obj.get("elapsed_ms", 0))
    
    st.divider()
    
    # Display response content
    response_data = response_obj.get("response", {})
    
    # Extract message content from response
    if isinstance(response_data, dict):
        try:
            content = response_data.get("choices", [{}])[0].get("message", {}).get("content", "")
            st.markdown("### 🎯 Response")
            st.markdown(content)
        except (IndexError, KeyError, TypeError):
            st.markdown("### 🎯 Response")
            st.json(response_data)
    else:
        st.markdown("### 🎯 Response")
        st.markdown(str(response_data))
    
    # Show full response JSON in expander
    with st.expander("📊 Full Response Object", expanded=False):
        st.json(response_obj)


def init_session_state():
    """Initialize Streamlit session state."""
    if "llm_messages" not in st.session_state:
        st.session_state.llm_messages = []
    if "llm_responses" not in st.session_state:
        st.session_state.llm_responses = []


def main():
    """Main LLM response page logic."""
    init_session_state()
    
    # Header
    st.title("✨ LLM Response")
    st.markdown("Simple one-shot LLM call with system prompt")
    
    st.markdown("---")
    
    # Chat area
    chat_container = st.container()
    
    with chat_container:
        # Display history
        if st.session_state.llm_messages:
            for i, resp in enumerate(st.session_state.llm_responses):
                st.markdown(f"#### Response {i+1}")
                display_llm_response(resp)
                st.divider()
        else:
            st.info("💡 No responses yet. Send a prompt to get started.")
    
    # Input area
    st.markdown("---")
    
    user_input = st.text_input(
        "Your question:",
        placeholder="Ask me anything...",
        key="agent_user_input",
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
        logger.info(f"[LLM_REQUEST] Calling {AGENT_ENDPOINT} with prompt: {user_input[:100]}")
        
        try:
            payload = {
                "message": user_input,
            }
            logger.info(f"[LLM_REQUEST] Payload: {payload}")
            
            response = requests.post(
                AGENT_ENDPOINT,
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            
            logger.info(f"[LLM_SUCCESS] status={response.status_code}")
            
            # Parse response
            try:
                json_response = response.json()
                st.session_state.llm_responses.append(json_response)
                logger.info(f"[LLM_RESPONSE] elapsed_ms={json_response.get('elapsed_ms')}")
            except json.JSONDecodeError:
                # Response is not JSON, store as-is
                st.session_state.llm_responses.append(response.text)
                logger.warning(f"[LLM_NON_JSON] {response.text[:100]}")
            
            st.rerun()
            
        except requests.exceptions.ConnectionError as e:
            error_msg = f"❌ Cannot connect to {AGENT_ENDPOINT}"
            logger.error(f"[ERROR] ConnectionError: {error_msg}")
            st.session_state.llm_responses.append(None)
            st.error(error_msg)
            st.info("Make sure the moneypenny-agent server is running:\n```bash\ncd moneypenny-agent && uvicorn main:app --port 8600\n```")
            st.rerun()
        except requests.exceptions.Timeout:
            error_msg = f"❌ Request timeout (>{REQUEST_TIMEOUT}s)"
            logger.error(f"[ERROR] Timeout: {error_msg}")
            st.session_state.llm_responses.append(None)
            st.error(error_msg)
            st.info("The LLM is taking too long to respond. This might mean:\n- Server is overloaded\n- Network is slow")
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
    logger.info("✨ LLM Response Page Started")
    logger.info(f"   Endpoint: {AGENT_ENDPOINT}")
    logger.info(f"   Timeout: {REQUEST_TIMEOUT}s")
    logger.info("   Mode: Simple one-shot (no multi-step)")
    logger.info("=" * 80)
    main()
