import json
import logging
from datetime import datetime

import streamlit as st

from helpers.chat_config import AppConfig
from helpers.chat_gmail_tools import GmailTools
from helpers.chat_prompts import SystemPrompts
from helpers.chat_utils import MessageUtils
from helpers import gmail_utils
from helpers.rag_utils_langchain import save_usage_entry

logger = logging.getLogger(__name__)

_MAX_TOOL_ROUNDS = 10


class GmailHandler:
    """Runs the multi-round Gmail tool-calling loop and streams the final reply."""

    @staticmethod
    def handle(client, selected_model: str) -> None:
        """
        Execute the Gmail tool-calling loop for the current turn.

        Reads/writes st.session_state directly (messages, usage_history,
        _processing, _pending_message). Renders the assistant bubble inline.
        """
        messages = st.session_state.messages
        gmail_messages = [{"role": "system", "content": SystemPrompts.GMAIL}] + [
            MessageUtils.to_api_msg(m) for m in (
                messages[-40:] if len(messages) > 40 else messages
            )
        ]

        full_text  = ""
        tool_error = False

        with st.chat_message("assistant"):
            placeholder = st.empty()
            placeholder.markdown("⏳ Gmail feldolgozás…")

            for _round in range(_MAX_TOOL_ROUNDS):
                try:
                    response = client.chat.completions.create(
                        model=selected_model,
                        messages=gmail_messages,
                        tools=GmailTools.TOOLS,
                        tool_choice="auto",
                        max_tokens=4096,
                        temperature=0.2,
                        stream=False,
                    )
                except Exception as api_err:
                    logger.error("gmail_api_call_failed=%s", api_err, exc_info=True)
                    full_text  = f"⚠️ API hiba: {api_err}"
                    tool_error = True
                    break

                choice     = response.choices[0]
                finish     = choice.finish_reason
                assist_msg = choice.message

                if response.usage:
                    entry = {
                        "input_tokens":  response.usage.prompt_tokens,
                        "output_tokens": response.usage.completion_tokens,
                        "timestamp":     datetime.now(),
                    }
                    st.session_state.usage_history.append(entry)
                    save_usage_entry(entry["input_tokens"], entry["output_tokens"], entry["timestamp"])

                if finish == "tool_calls" and assist_msg.tool_calls:
                    gmail_messages.append(
                        assist_msg.to_dict() if hasattr(assist_msg, "to_dict") else {
                            "role":       "assistant",
                            "content":    assist_msg.content or "",
                            "tool_calls": [
                                {
                                    "id":       tc.id,
                                    "type":     "function",
                                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                                }
                                for tc in assist_msg.tool_calls
                            ],
                        }
                    )

                    for tc in assist_msg.tool_calls:
                        fn_name = tc.function.name
                        try:
                            fn_args = json.loads(tc.function.arguments)
                        except json.JSONDecodeError:
                            fn_args = {}

                        placeholder.markdown(f"🔧 **Végrehajtás:** `{fn_name}`…")
                        logger.info("gmail_tool_call=%s args=%r", fn_name, fn_args)

                        gmail_fn = getattr(gmail_utils, fn_name, None)
                        if gmail_fn is None:
                            tool_result = {"error": f"Unknown tool: {fn_name}"}
                        else:
                            try:
                                tool_result = gmail_fn(**fn_args)
                            except Exception as tool_err:
                                logger.error("gmail_tool_error=%s fn=%s", tool_err, fn_name, exc_info=True)
                                tool_result = {"error": str(tool_err)}

                        gmail_messages.append({
                            "role":         "tool",
                            "tool_call_id": tc.id,
                            "content":      json.dumps(tool_result, ensure_ascii=False),
                        })
                else:
                    full_text = assist_msg.content or ""
                    break
            else:
                full_text  = "⚠️ A Gmail-eszköz túllépte a maximális lépésszámot. Kérlek próbáld újra."
                tool_error = True  # noqa: F841

            if not full_text.strip():
                full_text = "⚠️ A modell üres választ küldött."
            placeholder.markdown(full_text)
            st.caption(f"📧 Gmail-ből válaszolt · {AppConfig.get_model_label(selected_model)}")

        st.session_state.messages.append({
            "role":    "assistant",
            "content": full_text,
            "source":  "gmail",
            "model":   selected_model,
        })
        st.session_state._processing      = False
        st.session_state._pending_message = None
        st.rerun()


class StreamHandler:
    """Streams the AI response token-by-token and persists the completed reply."""

    @staticmethod
    def handle(
        client,
        selected_model: str,
        api_messages: list,
        source: str,
        web_sources: list | None,
        dropbox_sources: list | None,
        web_search_failed: bool,
    ) -> None:
        """
        Stream the AI response for a regular (non-Gmail) turn.

        Reads/writes st.session_state directly. Renders the assistant bubble inline.
        """
        with st.chat_message("assistant"):
            if web_search_failed:
                st.info("⚠️ Webes keresés nem elérhető — a betanítási tudás alapján válaszolok.", icon="🔌")

            placeholder = st.empty()
            full_text   = ""

            _est = MessageUtils.estimate_tokens(str(api_messages))
            logger.info(
                "api_call_initiated=true, messages=%d, est_tokens=%d, source=%s",
                len(api_messages), _est, source,
            )

            try:
                if selected_model.startswith("qwen"):
                    model_params = dict(temperature=0.7, top_p=0.8, presence_penalty=0)
                else:
                    model_params = dict(temperature=0.15, top_p=1, presence_penalty=0)

                stream = client.chat.completions.create(
                    model=selected_model,
                    messages=api_messages,
                    max_tokens=4096,
                    **model_params,
                    stream=True,
                    stream_options={"include_usage": True},
                )

                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        full_text += chunk.choices[0].delta.content
                        placeholder.markdown(full_text + "▌")

                    if chunk.usage:
                        entry = {
                            "input_tokens":  chunk.usage.prompt_tokens,
                            "output_tokens": chunk.usage.completion_tokens,
                            "timestamp":     datetime.now(),
                        }
                        logger.info(
                            "response_completed=true, input_tokens=%s, output_tokens=%s, source=%s",
                            entry["input_tokens"], entry["output_tokens"], source,
                        )
                        st.session_state.usage_history.append(entry)
                        save_usage_entry(
                            entry["input_tokens"], entry["output_tokens"], entry["timestamp"]
                        )

            except Exception as api_err:
                logger.error("api_call_failed=%s, est_tokens=%d", api_err, _est, exc_info=True)
                full_text = f"⚠️ API error: {api_err}"
                placeholder.warning(full_text)

            if not full_text or not full_text.strip():
                logger.warning(
                    "empty_response=true, source=%s", source,
                )
                warning_message = (
                    "⚠️ A modell üres választ küldött. Lehetséges okok:\n"
                    "- A modell hibába ütközött\n"
                    "- Nem találtunk releváns kontextust (próbálj más kulcsszavakat)\n"
                    "- Próbáld meg másképp megfogalmazni a kérdésedet"
                )
                placeholder.warning(warning_message)
                full_text = warning_message
            else:
                placeholder.markdown(full_text)

            # Source attribution caption
            model_tag = AppConfig.get_model_label(selected_model)
            if source == "files":
                st.caption(f"📁 A feltöltött fájlokból válaszolt · {model_tag}")
                if dropbox_sources:
                    st.caption("Források: " + " · ".join(f"`{f}`" for f in dropbox_sources))
            elif source == "web":
                st.caption(f"🌐 Internetes keresésből válaszolt · {model_tag}")
                if web_sources:
                    links = " · ".join(f"[{s['title'][:50]}]({s['link']})" for s in web_sources)
                    st.caption(f"Források: {links}")
            else:
                st.caption(f"🤖 A modell válaszolt · {model_tag}")

        # Persist the completed reply
        msg = {
            "role":    "assistant",
            "content": full_text,
            "source":  source,
            "model":   selected_model,
        }
        if web_sources:
            msg["web_sources"]     = web_sources
        if dropbox_sources:
            msg["dropbox_sources"] = dropbox_sources
        st.session_state.messages.append(msg)
        st.session_state._processing      = False
        st.session_state._pending_message = None
        if st.session_state.get("_pending_image"):
            st.session_state._pending_image    = None
            st.session_state._img_uploader_rev += 1

        st.rerun()
