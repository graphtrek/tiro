from attachment_downloader.base import EmailClient
from attachment_downloader.config import Settings


def get_client(provider: str, settings: Settings | None = None) -> EmailClient:
    if provider == "gmail":
        from attachment_downloader.providers.gmail.client import GmailClient

        return GmailClient(settings=settings)
    raise ValueError(f"Unknown provider: {provider!r}. Available: gmail")
