"""
Standalone Streamlit chat client for Moneypenny Agent streaming endpoint.
No dependencies on existing codebase.
"""

import streamlit as st
import requests
import json
import uuid
import os
import logging
from datetime import datetime
from typing import Generator
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
STREAM_ENDPOINT_URL = os.getenv("STREAM_ENDPOINT_URL", "http://localhost:8600/stream")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "60"))

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
    page_title="Moneypenny Chat",
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


def init_session_state():
    """Initialize Streamlit session state."""
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
        logger.info(f"[INIT] New session_id={st.session_state.session_id}")
    if "messages" not in st.session_state:
        st.session_state.messages = []


def stream_chat_response(message: str) -> Generator[str, None, None]:
    """
    Stream response from the endpoint.
    
    Args:
        message: User message to send
        
    Yields:
        Text chunks from the assistant response
    """
    payload = {
        "message": message,
        "session_id": st.session_state.session_id,
    }
    
    logger.info(f"[SEND] session_id={st.session_state.session_id} | message={message[:100]}")
    
    try:
        response = requests.post(
            STREAM_ENDPOINT_URL,
            json=payload,
            stream=True,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        
        logger.info(f"[CONNECTED] endpoint={STREAM_ENDPOINT_URL} | status={response.status_code}")
        
        # Parse Server-Sent Events (SSE) format: "data: {json}\n\n"
        chunk_count = 0
        
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            
            logger.debug(f"[RAW_LINE] {line[:120]}")
            
            # Strip SSE "data: " prefix
            if line.startswith("data: "):
                json_str = line[6:]
            elif line.startswith("data:"):
                json_str = line[5:]
            else:
                # Not an SSE data line, skip
                continue
            
            try:
                event = json.loads(json_str)
            except json.JSONDecodeError:
                logger.warning(f"[JSON_ERROR] Could not parse: {json_str[:100]}")
                continue
            
            event_type = event.get("type", "")
            event_data = event.get("data", {})
            
            if event_type == "token":
                # LLM text chunk — stream to UI
                text = event_data.get("text", "")
                if text:
                    chunk_count += 1
                    yield text
            elif event_type == "tool_call":
                # Tool execution starting — log only, don't pollute response
                tool_name = event_data.get("tool", "unknown")
                logger.info(f"[TOOL_CALL] {tool_name}")
                if "_status" in st.session_state:
                    st.session_state._status.update(label=f"🔧 {tool_name}...", state="running")
            elif event_type == "tool_result":
                # Tool finished
                tool_name = event_data.get("tool", "unknown")
                logger.info(f"[TOOL_RESULT] {tool_name}")
            elif event_type == "done":
                # Agent finished — if no tokens were streamed, yield the final content
                if chunk_count == 0:
                    content = event_data.get("content", "")
                    if content:
                        yield content
                logger.info(f"[DONE] rounds={event_data.get('rounds')} | tools={event_data.get('tools')} | elapsed={event_data.get('elapsed_ms')}ms")
            elif event_type == "error":
                error_msg = event_data.get("message", "Unknown error")
                logger.error(f"[STREAM_ERROR] {error_msg}")
                yield f"\n\n❌ Error: {error_msg}"
            elif event_type == "step_complete":
                logger.debug(f"[STEP] round={event_data.get('round')} | {event_data.get('decision')}")
        
        logger.info(f"[COMPLETE] chunks={chunk_count}")
                    
    except requests.exceptions.ConnectionError as e:
        error_msg = f"Cannot connect to {STREAM_ENDPOINT_URL}"
        logger.error(f"[ERROR] ConnectionError: {error_msg}")
        yield f"❌ Error: {error_msg}"
    except requests.exceptions.Timeout:
        error_msg = f"Request timeout (>{REQUEST_TIMEOUT}s)"
        logger.error(f"[ERROR] Timeout: {error_msg}")
        yield f"❌ Error: {error_msg}"
    except requests.exceptions.HTTPError as e:
        error_msg = f"{e.response.status_code} - {e.response.text}"
        logger.error(f"[ERROR] HTTPError: {error_msg}")
        yield f"❌ Error: {error_msg}"
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[ERROR] {error_msg}")
        yield f"❌ Error: {error_msg}"


def render_chat_history():
    """Render all messages in chat history using native Streamlit chat UI."""
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])


def main():
    """Main app logic."""
    init_session_state()
    
    # Header
    st.title("💬 Moneypenny Chat")
    st.markdown("---")
    
    # Chat area
    chat_container = st.container()
    
    with chat_container:
        render_chat_history()
    
    # Input area
    st.markdown("---")
    
    user_input = st.text_input(
        "Your message:",
        placeholder="Type your message here...",
        key="user_input",
    )
    
    col1, col2 = st.columns([4, 1])
    with col1:
        send_button = st.button("Send", use_container_width=True)
    with col2:
        if st.button("🗑️ Clear", use_container_width=True):
            logger.info(f"[CLEAR] Cleared {len(st.session_state.messages)} messages")
            st.session_state.messages = []
            st.rerun()
    
    if send_button and user_input.strip():
        # Add user message to history
        timestamp = datetime.now().strftime("%H:%M:%S")
        st.session_state.messages.append({
            "role": "user",
            "content": user_input,
            "timestamp": timestamp,
        })
        logger.info(f"[USER] {user_input[:100]}")
        
        # Show user message immediately
        with st.chat_message("user"):
            st.markdown(user_input)
        
        # Stream response with real-time display
        with st.chat_message("assistant"):
            status = st.status("Thinking...", expanded=False)
            st.session_state._status = status
            full_response = st.write_stream(stream_chat_response(user_input))
            status.update(label="Done", state="complete")
            del st.session_state._status
        
        # Add assistant message to history
        if full_response:
            timestamp = datetime.now().strftime("%H:%M:%S")
            st.session_state.messages.append({
                "role": "assistant",
                "content": full_response,
                "timestamp": timestamp,
            })
            logger.info(f"[ASSISTANT] {full_response[:100]}")
        
        # Rerun to show updated chat
        st.rerun()


if __name__ == "__main__":
    logger.info("=" * 80)
    logger.info("🚀 Streamlit Chat Client Started")
    logger.info(f"   Endpoint: {STREAM_ENDPOINT_URL}")
    logger.info(f"   Timeout: {REQUEST_TIMEOUT}s")
    logger.info("=" * 80)
    main()
