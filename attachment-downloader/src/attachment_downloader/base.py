from collections.abc import Callable
from typing import Protocol, runtime_checkable

from attachment_downloader.models import DownloadResult


@runtime_checkable
class EmailClient(Protocol):
    def download_pdf_attachments(
        self,
        start_date: str,
        end_date: str,
        output_dir: str | None = None,
        log: Callable[[str, str], None] | None = None,
    ) -> DownloadResult: ...
