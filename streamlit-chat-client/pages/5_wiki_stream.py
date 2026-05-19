import streamlit as st
import requests
import json
import logging

logger = logging.getLogger(__name__)

st.set_page_config(page_title="Wiki Stream Agent", page_icon="📖", layout="wide")

st.title("📖 Wiki Stream Agent")
st.markdown(
     "Ask a question and watch the agent stream its execution "
     "in real-time via Server-Sent Events."
)

if "session_id" not in st.session_state:
    st.session_state.session_id = None

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

user_query = st.text_input(
     "Your question",
    placeholder="e.g., What is the gene expression pattern for heart tissue?",
    key="wiki_query",
)

if st.button("Send", type="primary") and user_query.strip():
    session_id = st.session_state.session_id or f"session-{len(st.session_state.chat_history)}"
    st.session_state.session_id = session_id

    with st.chat_message("user"):
        st.write(user_query.strip())

    with st.chat_message("assistant", avatar="📖"):
        full_response = ""
        answer_placeholder = st.empty()
        answer_started = False  # Tracks whether we've seen the first reset_answer

        try:
            resp = requests.post(
                  "http://localhost:8600/llm-wiki-stream",
                json={"message": user_query.strip(), "session_id": session_id},
                stream=True,
                timeout=120,
             )

            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if line.startswith("data: "):
                    json_str = line[6:]
                elif line.startswith("data:"):
                    json_str = line[5:]
                else:
                    continue
                try:
                    # logger.info(f"Raw event JSON: {json_str}")
                    event = json.loads(json_str)
                    etype = event.get("type", "unknown")

                    if etype == "chunk":
                        # Display content chunks only after planning is complete.
                        # Ignore large chunks (>50 chars) — likely buffered, not true streaming.
                        text = event.get("data", {}).get("text", "")
                        if text and len(text) <= 50:
                            full_response += text
                            answer_placeholder.markdown(full_response)
                    elif etype == "reset_answer":
                        # First reset_answer signals planning is done, actual answer starts.
                        answer_started = True
                        full_response = ""
                        answer_placeholder.markdown("")
                        logger.info("Received reset_answer event: starting to display answer")
                    elif etype == "error":
                        raise RuntimeError(
                            event.get("data", {}).get("message", "Unknown error")
                        )
                    # done / reasoning / tool_call / tool_result events are
                    # ignored — what streamed in via chunk events is final.
                except json.JSONDecodeError:
                    pass

        except requests.exceptions.ConnectionError:
            st.error(
                 "Cannot connect to moneypenny-agent backend.\n"
                 "Ensure `uvicorn main:app --reload --port 8600` is running."
             )
        except requests.exceptions.Timeout:
            st.error("Stream timed out after 120 seconds.")
        except Exception as e:
            st.error(f"Error: {e}")

    st.session_state.chat_history.append({
         "role": "user",
        "content": user_query.strip(),
     })
    st.session_state.chat_history.append({
         "role": "assistant",
        "content": full_response,
     })
