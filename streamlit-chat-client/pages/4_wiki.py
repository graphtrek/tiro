"""
Wiki Agent page — conversational Q&A over the Moneypenny Obsidian wiki via POST /llm-wiki.
"""

import logging
import os
import uuid

import requests
import streamlit as st
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

BASE_URL = os.getenv("BASE_URL", "http://localhost:8600")
WIKI_ENDPOINT = f"{BASE_URL}/llm-wiki"
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "300"))

st.set_page_config(
    page_title="Wiki Agent",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
      .stChatMessage { max-width: 100%; }
</style>
""", unsafe_allow_html=True)


def init_session_state():
    if "wiki_messages" not in st.session_state:
        st.session_state.wiki_messages = []
    if "wiki_session_id" not in st.session_state:
        st.session_state.wiki_session_id = uuid.uuid4().hex[:12]


def main():
    init_session_state()

    st.title("📖 Wiki Agent")
    st.caption("Query your Moneypenny Obsidian knowledge base.")

    st.divider()

    # Render chat history
    for msg in st.session_state.wiki_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"], unsafe_allow_html=True)
            if msg.get("full_result"):
                with st.expander("🔍 View Full Result"):
                    st.json(msg["full_result"])
            if msg.get("elapsed_ms"):
                st.caption(f"⏱️ {msg['elapsed_ms']:.0f} ms")

    # Chat input via form (Enter-to-send + explicit buttons)
    with st.form("wiki_chat"):
        user_input = st.text_input(
            "Ask a question about your wiki:",
            placeholder="Type your question here and press Enter...",
            key="wiki_user_input",
        )

        col1, col2 = st.columns([4, 1])
        with col1:
            sent = st.form_submit_button("Send", use_container_width=True)
        with col2:
            clear = st.form_submit_button("Clear", use_container_width=True)

        if clear:
            st.session_state.wiki_messages = []
            st.session_state.wiki_session_id = uuid.uuid4().hex[:12]
            logger.info("[WIKI_CLEAR] Conversation cleared, new session started")
            st.rerun()

        if sent and user_input.strip():
            prompt = user_input
            # Show user message immediately
            st.session_state.wiki_messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            logger.info(f"[WIKI_REQUEST] session={st.session_state.wiki_session_id} | {WIKI_ENDPOINT} | msg={prompt[:100]}")

            with st.chat_message("assistant"):
                with st.spinner("Searching wiki…"):
                    try:
                        payload = {
                            "message": prompt,
                            "session_id": st.session_state.wiki_session_id,
                        }
                        response = requests.post(WIKI_ENDPOINT, json=payload, timeout=REQUEST_TIMEOUT)
                        response.raise_for_status()

                        data = response.json()
                        answer = data.get("response", "")
                        full_result = data.get("full_result")
                        elapsed_ms = data.get("elapsed_ms", 0)

                        logger.info(f"[WIKI_SUCCESS] session={data.get('session_id')} | ⏱️ {elapsed_ms:.0f}ms")

                        st.markdown(answer, unsafe_allow_html=True)
                        if full_result:
                            with st.expander("🔍 View Full Result"):
                                st.json(full_result)
                        st.caption(f"⏱️ {elapsed_ms:.0f} ms")

                        st.session_state.wiki_messages.append({
                            "role": "assistant",
                            "content": answer,
                            "full_result": full_result,
                            "elapsed_ms": elapsed_ms,
                        })
                        # Rerun to update history
                        st.rerun()

                    except requests.exceptions.ConnectionError:
                        error_msg = f"❌ Cannot connect to {WIKI_ENDPOINT}"
                        logger.error(f"[WIKI_ERROR] ConnectionError: {error_msg}")
                        st.error(error_msg)
                        st.info("Make sure the moneypenly-agent server is running:\n```bash\ncd moneypenny-agent && uvicorn main:app --port 8600\n```")
                        st.session_state.wiki_messages.append({"role": "assistant", "content": error_msg})
                        st.rerun()

                    except requests.exceptions.Timeout:
                        error_msg = f"❌ Request timed out (>{REQUEST_TIMEOUT}s)"
                        logger.error(f"[WIKI_ERROR] Timeout")
                        st.error(error_msg)
                        st.session_state.wiki_messages.append({"role": "assistant", "content": error_msg})
                        st.rerun()

                    except requests.exceptions.HTTPError as e:
                        error_msg = f"❌ HTTP {e.response.status_code}"
                        details = e.response.text[:500]
                        logger.error(f"[WIKI_ERROR] HTTPError: {error_msg} — {details}")
                        st.error(error_msg)
                        with st.expander("📋 Error Details"):
                            st.code(details, language="json")
                        st.session_state.wiki_messages.append({"role": "assistant", "content": error_msg})
                        st.rerun()

                    except Exception as e:
                        error_msg = f"❌ Error: {e}"
                        logger.error(f"[WIKI_ERROR] {error_msg}")
                        st.error(error_msg)
                        st.session_state.wiki_messages.append({"role": "assistant", "content": error_msg})
                        st.rerun()


if __name__ == "__main__":
    logger.info("=" * 80)
    logger.info("📖 Wiki Agent Page Started")
    logger.info(f"   Endpoint: {WIKI_ENDPOINT}")
    logger.info(f"   Timeout:  {REQUEST_TIMEOUT}s")
    logger.info("=" * 80)
    main()
