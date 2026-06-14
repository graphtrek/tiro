from attachment_downloader.base import EmailClient


def get_client(provider: str) -> EmailClient:
    if provider == "gmail":
        from attachment_downloader.providers.gmail.client import GmailClient
        return GmailClient()
    raise ValueError(f"Unknown provider: {provider!r}. Available: gmail")
