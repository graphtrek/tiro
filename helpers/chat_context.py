import logging
import os
import streamlit as st

from helpers.chat_config import AppConfig
from helpers.chat_prompts import SystemPrompts
from helpers.chat_utils import MessageUtils
from helpers.rag_utils_langchain import (
    search_documents_langchain,
    search_web_langchain,
    get_file_chunks,
)

logger = logging.getLogger(__name__)


class ContextBuilder:
    """Assembles the retrieval context and final API message list for a user turn."""

    @staticmethod
    def build_file_context(user_input: str) -> tuple[list | None, list | None]:
        """
        Returns (doc_chunks, dropbox_sources).

        First checks if any uploaded filename is mentioned in the query and loads
        it in full; otherwise falls back to ChromaDB semantic search when DropBox
        context is active.
        """
        upload_dir = AppConfig.UPLOAD_DIR
        doc_chunks      = None
        dropbox_sources = None
        file_sections   = []

        # 1) Exact filename match in query
        if os.path.isdir(upload_dir):
            for fname in sorted(os.listdir(upload_dir)):
                fpath = os.path.join(upload_dir, fname)
                if os.path.isfile(fpath) and fname.lower() in user_input.lower():
                    file_chunks = get_file_chunks(fname)
                    if file_chunks:
                        chunk_count = len(file_chunks)
                        token_count = sum(MessageUtils.estimate_tokens(c) for c in file_chunks)
                        logger.info(
                            "FILE CONTEXT | file=%-40s | chunks=%4d | tokens=%6d",
                            fname, chunk_count, token_count,
                        )
                        file_sections.append(f"=== FILE: {fname} ===\n" + "\n\n".join(file_chunks))
                    else:
                        logger.warning("FILE CONTEXT | file=%-40s | no chunks found in index", fname)

        if file_sections:
            total_chunks = sum(s.count("\n\n") + 1 for s in file_sections)
            total_tokens = sum(MessageUtils.estimate_tokens(s) for s in file_sections)
            logger.info(
                "FILE CONTEXT | TOTAL files=%d | chunks≈%d | tokens=%d",
                len(file_sections), total_chunks, total_tokens,
            )
            per_file_budget = 50_000 // max(len(file_sections), 1)
            trimmed = [MessageUtils.trim_context(s, max_tokens=per_file_budget) for s in file_sections]
            doc_chunks = trimmed
            dropbox_sources = [
                f for f in sorted(os.listdir(upload_dir))
                if os.path.isfile(os.path.join(upload_dir, f)) and f.lower() in user_input.lower()
            ]
            return doc_chunks, dropbox_sources

        # 2) ChromaDB semantic search (only when DropBox context is active)
        if st.session_state.get("dropbox_context_enabled", False):
            logger.info("DropBox context active — attempting ChromaDB semantic search")
            try:
                retrieved, retrieved_filenames = search_documents_langchain(user_input, k=4)
                if retrieved:
                    doc_chunks      = retrieved
                    dropbox_sources = retrieved_filenames
                    logger.info("ChromaDB search succeeded, retrieved %d chunks", len(doc_chunks))
                else:
                    logger.warning("ChromaDB search returned no results for: %r", user_input[:100])
            except Exception as e:
                logger.error("ChromaDB search failed: %s", e, exc_info=True)

        return doc_chunks, dropbox_sources

    @staticmethod
    def build_web_context(user_input: str) -> tuple[str | None, list | None, bool]:
        """
        Returns (web_results_text, web_sources, search_failed).
        Only called when DropBox context is inactive.
        """
        try:
            web_results, web_sources = search_web_langchain(user_input)
            if web_results:
                logger.info("web_search_completed=true, result_length=%s", len(str(web_results)))
                return web_results, web_sources, False
            logger.warning("web_search_returned_empty=true")
            return None, None, True
        except Exception as e:
            logger.info("web_search_failed=%s", e)
            return None, None, True

    @staticmethod
    def assemble_api_messages(
        doc_chunks: list | None,
        dropbox_sources: list | None,
        web_results: str | None,
        web_search_failed: bool,
        conversation_msgs: list,
    ) -> tuple[list, str]:
        """
        Build the final OpenAI API message list.

        Returns (api_messages, source) where source is 'files' | 'web' | 'model'.
        """
        dropbox_on = st.session_state.get("dropbox_context_enabled", False)
        source = "model"

        # Determine base system prompt
        system_prompt = SystemPrompts.DROPBOX if dropbox_on else SystemPrompts.INTERNET

        # Assemble context text
        context_parts = []

        if doc_chunks:
            context_parts.append(
                "\n\n".join(doc_chunks) if isinstance(doc_chunks, list) else str(doc_chunks)
            )
            source = "files"

        if web_results:
            context_parts.append(MessageUtils.trim_context(web_results, max_tokens=4000))
            source = "web"

        context_text = "\n\n".join(context_parts) if context_parts else None

        if context_text:
            trimmed_context = MessageUtils.trim_context(context_text, max_tokens=50_000)
            system_prompt += (
                "\n\nA következő kontextus alapján válaszolj a felhasználó kérdésére:\n\n"
                + trimmed_context
            )
        elif not dropbox_on and web_search_failed:
            system_prompt += (
                "\n\nMegjegyzés: Ehhez a kérdéshez nem áll rendelkezésre webes keresési eredmény. "
                "Válaszolj a betanítási ismereteid alapján, és jelezd egyértelműen, hogy "
                "az információ esetleg nem tükrözi a legfrissebb állapotot."
            )

        # Sliding-window conversation history: at most the last 40 messages
        history = conversation_msgs[-40:] if len(conversation_msgs) > 40 else conversation_msgs
        api_messages = [{"role": "system", "content": system_prompt}] + [
            MessageUtils.to_api_msg(m) for m in history
        ]

        # Final safety trim to 20 messages if still over budget
        max_input_tokens = 245_000
        if MessageUtils.estimate_tokens(str(api_messages)) > max_input_tokens - 1_000:
            logger.warning("Token budget exceeded, trimming to last 20 messages")
            api_messages = [api_messages[0]] + [MessageUtils.to_api_msg(m) for m in history[-20:]]

        return api_messages, source
