import logging

import chromadb
import streamlit as st

from helpers.chat_config import AppConfig

logger = logging.getLogger(__name__)

_SETTINGS_COLLECTION_NAME = "chat_settings"


class SettingsManager:
    """Persist and load user preferences (model, context toggles) via ChromaDB."""

    @staticmethod
    def _get_collection():
        return chromadb.PersistentClient(path=AppConfig.CHROMA_DIR).get_or_create_collection(
            name=_SETTINGS_COLLECTION_NAME
        )

    @staticmethod
    def load() -> dict:
        """
        Load saved settings from ChromaDB.

        Returns sensible defaults when no saved settings exist or when the
        stored model name is no longer in the available MODELS list.
        """
        defaults = {
            "selected_model":          AppConfig.MODELS[0],
            "dropbox_context_enabled": True,
            "gmail_context_enabled":   False,
            "msg_area":                "",
        }
        try:
            result = SettingsManager._get_collection().get(ids=["chat_settings"])
            if result and result["metadatas"] and result["metadatas"][0]:
                saved = result["metadatas"][0]
                if saved.get("selected_model") not in AppConfig.MODELS:
                    saved["selected_model"] = AppConfig.MODELS[0]
                # ChromaDB stores all values as strings; convert back to bool
                for key in ("dropbox_context_enabled", "gmail_context_enabled"):
                    if key in saved:
                        saved[key] = saved[key].lower() in ("true", "1", "yes")
                return {**defaults, **saved}
        except Exception as e:
            logger.warning("Failed to load persistent settings: %s", e)
        return defaults

    @staticmethod
    def save() -> None:
        """Write current session-state settings to ChromaDB for persistence."""
        settings = {
            "selected_model": st.session_state.get("selected_model", AppConfig.MODELS[0]),
            "dropbox_context_enabled": str(
                st.session_state.get("dropbox_context_enabled", False)
            ).lower(),
            "gmail_context_enabled": str(
                st.session_state.get("gmail_context_enabled", False)
            ).lower(),
            "msg_area": st.session_state.get("msg_area", ""),
        }
        try:
            SettingsManager._get_collection().upsert(
                ids=["chat_settings"],
                documents=["chat_settings"],
                metadatas=[settings],
            )
            logger.info("Persistent settings saved")
        except Exception as e:
            logger.warning("Failed to save persistent settings: %s", e)
