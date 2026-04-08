import logging
import os
import re
import streamlit as st

import requests

from helpers.chat_config import AppConfig

_DROPBOX_KEYWORDS = re.compile(
    r"\b(dropbox|uploaded?\s+files?|from\s+uploads?)\b",
    re.IGNORECASE,
)
_URL_PATTERN = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)

try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False
from helpers.chat_prompts import SystemPrompts
from helpers.chat_utils import MessageUtils
from helpers.rag_utils_langchain import (
    search_web_langchain,
    get_file_chunks,
)

logger = logging.getLogger(__name__)


def _extract_urls(text: str) -> list[str]:
    return _URL_PATTERN.findall(text)


def _fetch_url_content(url: str, max_chars: int = 32768) -> str | None:
    """Fetch a URL and return its readable text content."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; NothingGetsOutAI/1.0)"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "text/html" in content_type:
            if _BS4_AVAILABLE:
                soup = BeautifulSoup(resp.text, "html.parser")
                for tag in soup(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                text = soup.get_text(separator="\n", strip=True)
            else:
                text = re.sub(r"<[^>]+>", " ", resp.text)
                text = re.sub(r"\s+", " ", text).strip()
        else:
            text = resp.text
        if len(text) > max_chars:
            text = text[:max_chars] + "\n... [truncated]"
        return text
    except Exception as e:
        logger.warning("_fetch_url_content failed for %s: %s", url, e)
        return None


class ContextBuilder:
    """Assembles the retrieval context and final API message list for a user turn."""

    @staticmethod
    def build_file_context(user_input: str) -> tuple[list | None, list | None]:
        """
        Returns (doc_chunks, dropbox_sources).

        If the user mentions a specific filename, loads only that file's chunks.
        Otherwise, when DropBox context is active, loads ALL files so the model
        can answer meta-questions (count, list, search across all files).
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

        # 2) All-files DropBox context when active OR user mentions dropbox keywords
        dropbox_mentioned = bool(_DROPBOX_KEYWORDS.search(user_input))
        if st.session_state.get("dropbox_context_enabled", False) or dropbox_mentioned:
            logger.info("DropBox context active — loading all file chunks")
            try:
                all_files = sorted(
                    f for f in os.listdir(upload_dir)
                    if os.path.isfile(os.path.join(upload_dir, f))
                ) if os.path.isdir(upload_dir) else []

                if all_files:
                    # Always-included file listing (small, never trimmed)
                    file_list_section = (
                        f"DropBox contains {len(all_files)} file(s):\n"
                        + "\n".join(f"- {f}" for f in all_files)
                    )
                    content_sections = []
                    for fname in all_files:
                        file_chunks = get_file_chunks(fname)
                        if file_chunks:
                            chunk_count = len(file_chunks)
                            token_count = sum(MessageUtils.estimate_tokens(c) for c in file_chunks)
                            logger.info(
                                "ALL-FILES | file=%-40s | chunks=%4d | tokens=%6d",
                                fname, chunk_count, token_count,
                            )
                            content_sections.append(
                                f"=== FILE: {fname} ===\n" + "\n\n".join(file_chunks)
                            )

                    per_file_budget = 50_000 // max(len(content_sections), 1)
                    trimmed_content = [
                        MessageUtils.trim_context(s, max_tokens=per_file_budget)
                        for s in content_sections
                    ]
                    doc_chunks      = [file_list_section] + trimmed_content
                    dropbox_sources = all_files
                    logger.info(
                        "ALL-FILES | total files=%d | content sections=%d",
                        len(all_files), len(content_sections),
                    )
                else:
                    logger.warning("DropBox context active but upload_dir is empty or missing")
            except Exception as e:
                logger.error("All-files context load failed: %s", e, exc_info=True)

        return doc_chunks, dropbox_sources

    @staticmethod
    def build_web_context(user_input: str) -> tuple[str | None, list | None, bool]:
        """
        Returns (web_results_text, web_sources, search_failed).
        Only called when DropBox context is inactive.

        If the user message contains URLs, those are fetched first and treated
        as the preferred source. DuckDuckGo results are always appended as
        supplemental context.
        """
        parts: list[str] = []
        sources: list[dict] = []

        # 1) Fetch user-provided URLs (preferred)
        urls = _extract_urls(user_input)
        for url in urls[:3]:
            content = _fetch_url_content(url)
            if content:
                logger.info("url_fetch_ok=%s, chars=%d", url, len(content))
                parts.append(f"--- Content from {url} ---\n{content}")
                sources.append({"title": url, "link": url})
            else:
                logger.warning("url_fetch_failed=%s", url)
                parts.append(f"--- A {url} weboldal tartalma nem tölthető le (hálózati hiba vagy hozzáféréstiltás). ---")

        # 2) DuckDuckGo supplemental search
        try:
            web_results, web_sources = search_web_langchain(user_input)
            if web_results:
                logger.info("web_search_completed=true, result_length=%s", len(str(web_results)))
                parts.append(web_results)
                if web_sources:
                    sources.extend(web_sources)
            else:
                logger.warning("web_search_returned_empty=true")
        except Exception as e:
            logger.info("web_search_failed=%s", e)

        if parts:
            return "\n\n".join(parts), sources or None, False
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
            if not dropbox_on:
                system_prompt += (
                    "\n\nAz alábbi tartalom automatikusan le lett töltve a szerver által. "
                    "NE mondd, hogy nem tudsz böngészni — a tartalom már elérhető. "
                    "Ha egy URL letöltése meghiúsult, ezt egyértelműen jelezd a felhasználónak.\n\n"
                    + trimmed_context
                )
            else:
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
