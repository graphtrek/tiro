# streamlit  — the library that turns this Python script into a web app.
#              Every time the user interacts with the UI, Streamlit re-runs
#              the whole script from top to bottom.
import streamlit as st

# st.set_page_config must be the first Streamlit call in the script.
# menu_items={} removes all entries from the hamburger menu (including the
# "Made with Streamlit" version footer that appears inside it).
st.set_page_config(page_title="Graphtrek AI Chat", page_icon="💬", menu_items={})

# openai  — the official OpenAI Python SDK. Scaleway exposes a compatible API,
#           so we can reuse the same client by just changing the base URL.
from openai import OpenAI

# dotenv  — loads key=value pairs from a .env file into environment variables
#           so secrets never have to be written in source code.
import os
from dotenv import load_dotenv

# Read the .env file from the same folder as this script.
load_dotenv()

# ── Constants ──────────────────────────────────────────────────────────────────
# os.environ reads values that were loaded from .env by load_dotenv() above.
# If a variable is missing, a clear error is raised immediately instead of
# failing later with a cryptic message.
BASE_URL = os.environ["SCALEWAY_BASE_URL"]
API_KEY  = os.environ["SCALEWAY_API_KEY"]

# The list of AI models the user can choose from in the sidebar.
MODELS = [
    "devstral-2-123b-instruct-2512",
    "qwen3.5-397b-a17b",
    "mistral-small-3.2-24b-instruct-2506"
]

# Tasks supported by each model — shown above the dropdown as a caption.
MODEL_LABELS = {
    "devstral-2-123b-instruct-2512": "Chat & Code",
    "qwen3.5-397b-a17b":            "Chat & Code",
    "mistral-small-3.2-24b-instruct-2506": "Chat & Vision",
}

# ── OpenAI client ──────────────────────────────────────────────────────────────
# Create one shared API client. We point it at Scaleway's endpoint instead of
# the default OpenAI URL so all requests go to Scaleway's servers.
client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

# ── Session state defaults ─────────────────────────────────────────────────────
# st.session_state is a dictionary Streamlit keeps alive between re-runs for the
# same browser tab. Without it, every click would wipe all data.
# The "not in" check ensures we only initialise each key once on first load.

# messages: the full conversation so far — a list of dicts, e.g.:
#   {"role": "user",      "content": "Hello!"}
#   {"role": "assistant", "content": "Hi there!"}
if "messages" not in st.session_state:
    st.session_state.messages = []

# last_usage: token counts from the most recent API response.
# Starts as None so we can show "—" before any message is sent.
if "last_usage" not in st.session_state:
    st.session_state.last_usage = None

# total_usage: running token totals across all messages in this session.
if "total_usage" not in st.session_state:
    st.session_state.total_usage = {"input_tokens": 0, "output_tokens": 0}

# ── Reduce sidebar top padding ────────────────────────────────────────────────
# Streamlit adds a large gap at the top of the sidebar by default.
# We inject a small CSS snippet to shrink it to 1 rem (~16 px).
# unsafe_allow_html=True is required whenever we pass raw HTML/CSS to Streamlit.
st.markdown(
    "<style>"
    "section[data-testid='stSidebar'] > div:first-child { padding-top: 0.25rem; }"
    "[data-testid='stSidebarHeader'] { display: none; }"
    "[data-testid='stAppDeployButton'] { display: none; }"
    "footer { display: none; }"
    ".stMenuVersionCopyButton { display: none; }"
    "</style>",
    unsafe_allow_html=True,
)

# ── Sidebar ────────────────────────────────────────────────────────────────────
# Everything indented inside "with st.sidebar:" is rendered in the left panel.
with st.sidebar:
    st.title("⚙️ Settings")

    # The selectbox label shows the tasks supported by the currently selected model.
    # We read from session_state so it updates immediately when the user switches.
    _tasks = MODEL_LABELS.get(st.session_state.get("selected_model", MODELS[0]), "Chat & Code")
    selected_model = st.selectbox(
        f"Model: {_tasks}",
        MODELS,
        index=0,
        key="selected_model",
    )

    # st.text_area is a multi-line text box. The system prompt instructs the AI
    # how to behave before the user's first message.
    system_prompt = st.text_area(
        "System prompt",
        value="You are a helpful assistant.",
        height=120,
    )

    # When this button is clicked, we reset all conversation data and call
    # st.rerun() so the UI refreshes immediately.
    if st.button("🗑️ Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.last_usage = None
        st.session_state.total_usage = {"input_tokens": 0, "output_tokens": 0}
        st.rerun()

    # st.divider() draws a horizontal line to visually separate sections.
    st.divider()

    # ── Token usage metrics ────────────────────────────────────────────────────
    # st.metric renders a labelled number widget (large value + label).
    # We show "—" when no data is available yet.

    st.subheader("Last response tokens")
    usage = st.session_state.last_usage
    # st.columns(2) splits the sidebar into two equal-width columns side by side.
    col1, col2 = st.columns(2)
    col1.metric("Input",  usage["input_tokens"]  if usage else "—")
    col2.metric("Output", usage["output_tokens"] if usage else "—")

    st.subheader("Cumulative tokens")
    total = st.session_state.total_usage
    col3, col4 = st.columns(2)
    col3.metric("Input",  total["input_tokens"]  if total["input_tokens"]  else "—")
    col4.metric("Output", total["output_tokens"] if total["output_tokens"] else "—")

# ── Page header ────────────────────────────────────────────────────────────────
st.title("💬 Graphtrek AI Chat")
# st.caption renders smaller, dimmer text — good for secondary info.
st.caption(f"Model: `{selected_model}`")

# ── Render existing messages ───────────────────────────────────────────────────
# Loop through the saved conversation and redraw every message bubble.
# st.chat_message("user")      → right-aligned user bubble
# st.chat_message("assistant") → left-aligned AI bubble
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ── Chat input ─────────────────────────────────────────────────────────────────
# st.chat_input shows a text box pinned to the bottom of the page.
# It returns the submitted text, or None if nothing has been typed yet.
user_input = st.chat_input("Send a message…")

if user_input:
    # 1) Save the user's message to history and show it immediately as a bubble.
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # 2) Build the full message list to send to the API.
    #    We prepend the system prompt (sets the AI's behaviour), then attach
    #    the entire conversation history so the AI has full context.
    api_messages = [{"role": "system", "content": system_prompt}] + st.session_state.messages

    # 3) Stream the AI response token by token.
    with st.chat_message("assistant"):
        # st.empty() creates a placeholder we can update on every new token.
        placeholder = st.empty()
        full_text = ""  # accumulates the complete reply as tokens arrive

        # stream=True sends the response in small chunks instead of waiting
        # for the full reply. stream_options asks for token counts in the
        # final chunk.
        stream = client.chat.completions.create(
            model=selected_model,
            messages=api_messages,
            max_tokens=2048,
            temperature=0.6,   # higher = more creative / random answers
            top_p=0.95,         # nucleus sampling: consider only top 95% probable tokens
            stream=True,
            stream_options={"include_usage": True},
        )

        # Each iteration receives one small chunk (a few tokens) from the API.
        for chunk in stream:
            # chunk.choices contains the new token(s). We guard against an
            # empty choices list (which happens on the final usage-only chunk).
            if chunk.choices and chunk.choices[0].delta.content:
                full_text += chunk.choices[0].delta.content
                # Show a blinking-cursor character "▌" while typing is in progress,
                # then overwrite the placeholder with the updated text.
                placeholder.markdown(full_text + "▌")

            # The very last chunk has no new tokens but carries usage statistics.
            if chunk.usage:
                # Save last-response counts for the sidebar metrics.
                st.session_state.last_usage = {
                    "input_tokens":  chunk.usage.prompt_tokens,
                    "output_tokens": chunk.usage.completion_tokens,
                }
                # Add to the running session totals.
                st.session_state.total_usage["input_tokens"]  += chunk.usage.prompt_tokens
                st.session_state.total_usage["output_tokens"] += chunk.usage.completion_tokens

        # Remove the cursor and display the final clean text.
        placeholder.markdown(full_text)

    # 4) Save the completed assistant reply so it becomes part of the next
    #    request's conversation history (multi-turn memory).
    st.session_state.messages.append({"role": "assistant", "content": full_text})

    # Force Streamlit to re-run the script so the updated sidebar token
    # metrics are reflected immediately.
    st.rerun()