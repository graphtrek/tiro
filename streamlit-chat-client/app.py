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
import re
from datetime import datetime
from typing import Generator, Optional
from dotenv import load_dotenv

# Setup logging first
logger = logging.getLogger(__name__)

try:
    import pandas as pd
    import plotly.express as px
    PANDAS_AVAILABLE = True
except ImportError as e:
    PANDAS_AVAILABLE = False
    logger.warning(f"[IMPORT_WARNING] pandas/plotly not available: {e}")

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


def filter_sensitive_columns(headers: list[str], data: list[list]) -> tuple[list[str], list[list]]:
    """
    Filter out sensitive columns (key, id, password variants).
    
    Args:
        headers: Column names
        data: Data rows
        
    Returns:
        Tuple of (filtered_headers, filtered_data)
    """
    # Columns to exclude (case-insensitive)
    exclude_patterns = ['key', 'id', 'password', '_key', '_id']
    
    # Find indices to keep
    keep_indices = []
    filtered_headers = []
    
    for idx, header in enumerate(headers):
        header_lower = header.lower()
        # Keep column if it doesn't match any exclude pattern
        should_exclude = any(
            pattern in header_lower or header_lower.endswith(pattern)
            for pattern in exclude_patterns
        )
        
        if not should_exclude:
            keep_indices.append(idx)
            filtered_headers.append(header)
            logger.debug(f"[FILTER] Keeping column: {header}")
        else:
            logger.debug(f"[FILTER] Excluding column: {header}")
    
    # Filter data
    filtered_data = []
    for row in data:
        filtered_row = [row[i] for i in keep_indices if i < len(row)]
        filtered_data.append(filtered_row)
    
    logger.info(f"[FILTER] Filtered {len(headers)} columns → {len(filtered_headers)} columns")
    return filtered_headers, filtered_data


def extract_markdown_tables(text: str) -> list[dict]:
    """
    Extract markdown tables from text and convert to DataFrames.
    Excludes sensitive columns (key, id, password).
    
    Args:
        text: Text containing markdown tables
        
    Returns:
        List of dicts with 'name' and 'df' keys
    """
    if not PANDAS_AVAILABLE:
        logger.warning("[EXTRACT_TABLES] pandas not available, skipping table extraction")
        return []
    
    tables = []
    # Pattern to match markdown tables: | ... | ... |
    # Tables should have at least 2 rows (header + separator + data)
    table_pattern = r'(\|[^\n]+\|\n\|[-:| ]+\|[^\n]*\n(?:\|[^\n]+\|\n?)+)'
    
    matches = re.finditer(table_pattern, text)
    logger.debug(f"[EXTRACT_TABLES] Found {len(list(re.finditer(table_pattern, text)))} table patterns")
    
    matches = re.finditer(table_pattern, text)  # Re-iterate since we consumed it
    for idx, match in enumerate(matches):
        table_text = match.group(1)
        try:
            # Parse markdown table
            lines = table_text.strip().split('\n')
            if len(lines) < 3:
                continue
            
            # Extract header
            header_line = lines[0]
            headers = [h.strip() for h in header_line.split('|')[1:-1]]
            
            # Skip separator line (lines[1])
            # Extract data rows
            data = []
            for line in lines[2:]:
                if line.strip():
                    values = [v.strip() for v in line.split('|')[1:-1]]
                    if len(values) == len(headers):
                        data.append(values)
            
            if data and headers:
                # Filter sensitive columns
                filtered_headers, filtered_data = filter_sensitive_columns(headers, data)
                
                if not filtered_headers:
                    logger.warning(f"[TABLE] All columns filtered out (sensitive data), skipping table {idx+1}")
                    continue
                
                # Create DataFrame
                df = pd.DataFrame(filtered_data, columns=filtered_headers)
                
                # Try to convert numeric columns
                for col in df.columns:
                    try:
                        df[col] = pd.to_numeric(df[col])
                    except (ValueError, TypeError):
                        pass
                
                tables.append({
                    'name': f'📋 Table {len(tables) + 1}',
                    'df': df,
                    'headers': filtered_headers,
                    'data': filtered_data
                })
                logger.info(f"[TABLE] Extracted table with {len(filtered_data)} rows, {len(filtered_headers)} columns (after filtering)")
        except Exception as e:
            logger.debug(f"[TABLE_PARSE_ERROR] {str(e)}")
            continue
    
    logger.info(f"[EXTRACT_TABLES] Total tables extracted: {len(tables)}")
    return tables


def visualize_tables(tables: list[dict]):
    """
    Display tables in tabular format with optional charts.
    
    Args:
        tables: List of table dicts with 'df' key
    """
    if not tables:
        logger.debug("[VISUALIZE] No tables to visualize")
        return
    
    if not PANDAS_AVAILABLE:
        logger.warning("[VISUALIZE] pandas/plotly not available, skipping visualization")
        return
    
    logger.info(f"[VISUALIZE] Starting visualization for {len(tables)} tables")
    st.markdown("---")
    st.subheader("📊 SQL Results")
    
    for idx, table_info in enumerate(tables):
        try:
            df = table_info['df']
            logger.debug(f"[VISUALIZE] Table {idx+1}: {df.shape}")
            
            # Always show table first
            st.markdown(f"### {table_info['name']} ({len(df)} rows × {len(df.columns)} columns)")
            st.dataframe(df, use_container_width=True, hide_index=True)
            
            # Try to auto-detect chart type based on data
            numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
            non_numeric_cols = df.select_dtypes(exclude=['number']).columns.tolist()
            
            # Create charts only if we have 2+ rows and relevant columns
            if len(df) >= 2:
                if len(numeric_cols) >= 1 and len(non_numeric_cols) >= 1:
                    # Bar chart: categorical vs numeric
                    try:
                        fig = px.bar(
                            df, 
                            x=non_numeric_cols[0], 
                            y=numeric_cols[0],
                            title=f"{non_numeric_cols[0]} vs {numeric_cols[0]}"
                        )
                        st.plotly_chart(fig, use_container_width=True)
                        logger.info(f"[VISUALIZE] Bar chart created for table {idx+1}")
                    except Exception as e:
                        logger.warning(f"[VISUALIZE_ERROR] Bar chart failed: {str(e)}")
                elif len(numeric_cols) >= 2:
                    # Scatter plot: two numeric columns
                    try:
                        fig = px.scatter(
                            df, 
                            x=numeric_cols[0], 
                            y=numeric_cols[1],
                            title=f"{numeric_cols[0]} vs {numeric_cols[1]}"
                        )
                        st.plotly_chart(fig, use_container_width=True)
                        logger.info(f"[VISUALIZE] Scatter chart created for table {idx+1}")
                    except Exception as e:
                        logger.warning(f"[VISUALIZE_ERROR] Scatter chart failed: {str(e)}")
                elif len(numeric_cols) == 1:
                    # Simple bar chart with index
                    try:
                        fig = px.bar(
                            df, 
                            y=numeric_cols[0],
                            title=numeric_cols[0]
                        )
                        st.plotly_chart(fig, use_container_width=True)
                        logger.info(f"[VISUALIZE] Single column chart created for table {idx+1}")
                    except Exception as e:
                        logger.warning(f"[VISUALIZE_ERROR] Single column chart failed: {str(e)}")
            else:
                logger.debug(f"[VISUALIZE] Table {idx+1} has {len(df)} rows, skipping chart (need ≥2 rows)")
            
            st.markdown("")
        except Exception as e:
            logger.error(f"[VISUALIZE_ERROR] Failed to visualize table {idx+1}: {str(e)}")
            continue
    
    logger.info(f"[VISUALIZE] Completed visualization for {len(tables)} tables")


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
            elif event_type == "sql":
                # SQL query executed — format and emit
                sql = event_data.get("sql", "")
                tool = event_data.get("tool", "unknown")
                if sql:
                    # Format as markdown code block
                    sql_block = f"\n\n**🔍 SQL ({tool}):**\n```sql\n{sql}\n```"
                    yield sql_block
                    logger.info(f"[SQL] {tool}: {sql[:80]}...")
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
            
            # Extract and visualize tables
            logger.info(f"[RESPONSE] Extracting tables from response ({len(full_response)} chars)")
            tables = extract_markdown_tables(full_response)
            logger.info(f"[RESPONSE] Found {len(tables)} tables")
            if tables:
                logger.info(f"[RESPONSE] Calling visualize_tables()")
                visualize_tables(tables)
            else:
                logger.debug(f"[RESPONSE] No tables found in response")


if __name__ == "__main__":
    logger.info("=" * 80)
    logger.info("🚀 Streamlit Chat Client Started")
    logger.info(f"   Endpoint: {STREAM_ENDPOINT_URL}")
    logger.info(f"   Timeout: {REQUEST_TIMEOUT}s")
    logger.info("=" * 80)
    main()
