from typing import Callable, Optional, Protocol, runtime_checkable

from attachment_downloader.models import DownloadResult


@runtime_checkable
class EmailClient(Protocol):
    def download_pdf_attachments(
        self,
        start_date: str,
        end_date: str,
        output_dir: Optional[str] = None,
        log: Optional[Callable[[str, str], None]] = None,
    ) -> DownloadResult: ...
