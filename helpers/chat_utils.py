class MessageUtils:
    """Stateless utility methods for token budgeting and message formatting."""

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Rough token estimate: ~1 token per 4 characters."""
        return len(text) // 4

    @staticmethod
    def trim_context(context_text: str, max_tokens: int = 8000) -> str:
        """
        Truncate context text to stay within a token budget.

        Splits on blank lines and drops trailing chunks until the estimated
        token count fits. Falls back to the raw first chunk if nothing fits.
        """
        if not context_text:
            return ""

        if MessageUtils.estimate_tokens(context_text) <= max_tokens:
            return context_text

        chunks = context_text.split("\n\n")
        trimmed, current_tokens = [], 0
        for chunk in chunks:
            chunk_tokens = MessageUtils.estimate_tokens(chunk)
            if current_tokens + chunk_tokens <= max_tokens:
                trimmed.append(chunk)
                current_tokens += chunk_tokens
            else:
                break

        return "\n\n".join(trimmed) if trimmed else chunks[0][: max_tokens * 4]

    @staticmethod
    def to_api_msg(msg: dict) -> dict:
        """Convert a stored message dict to OpenAI API format, adding image content if present."""
        content = msg["content"]
        if msg.get("image_b64"):
            content = [
                {"type": "text", "text": msg["content"]},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{msg['image_b64']}"}},
            ]
        return {"role": msg["role"], "content": content}
