import base64
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from attachment_downloader.cache import TTLCache
from attachment_downloader.config import CACHE_TTL_SECONDS, DOWNLOAD_ROOT_DIR
from attachment_downloader.models import DownloadedFile, DownloadResult
from attachment_downloader.providers.gmail.config import CREDENTIALS_PATH, TOKEN_PATH
from attachment_downloader.utils import sanitize_filename, scan_output

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailClient:
    def __init__(self):
        self._service = None
        self._cache = TTLCache(ttl_seconds=CACHE_TTL_SECONDS)

    def _get_service(self):
        if self._service:
            return self._service

        creds = None
        if TOKEN_PATH.exists():
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("OAuth token expired — refreshing")
                creds.refresh(Request())
                logger.info("OAuth token refreshed")
            else:
                if not CREDENTIALS_PATH.exists():
                    raise FileNotFoundError(
                        f"Credentials file not found at: {CREDENTIALS_PATH}. "
                        "Please ensure the JSON file is in the project root."
                    )
                logger.info("Starting OAuth2 browser flow")
                flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
                creds = flow.run_local_server(port=8888)
                logger.info("OAuth2 authentication completed")

            with open(str(TOKEN_PATH), "w") as token_file:
                token_file.write(creds.to_json())

        self._service = build("gmail", "v1", credentials=creds)
        return self._service

    def _iter_message_ids(self, service, query: str) -> Iterator[str]:
        """Yield every message id matching ``query``, paging through results."""
        page_token = None
        while True:
            resp = service.users().messages().list(
                userId="me", q=query, maxResults=100, pageToken=page_token
            ).execute()
            for msg in resp.get("messages", []):
                yield msg["id"]
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

    def _extract_pdf_parts(self, payload: dict) -> List[Tuple[str, str, int]]:
        """Return (filename, attachment_id, size) for every PDF attachment in a payload."""
        results: List[Tuple[str, str, int]] = []

        def walk(part: dict) -> None:
            filename = part.get("filename", "") or ""
            mime_type = part.get("mimeType", "") or ""
            body = part.get("body", {}) or {}
            attachment_id = body.get("attachmentId")
            is_pdf = filename.lower().endswith(".pdf") or mime_type == "application/pdf"
            if attachment_id and is_pdf:
                results.append((filename or "attachment.pdf", attachment_id, body.get("size", 0)))
            for sub in part.get("parts", []) or []:
                walk(sub)

        walk(payload)
        return results

    def download_pdf_attachments(
        self,
        start_date: str,
        end_date: str,
        output_dir: Optional[str] = None,
        log: Optional[Callable[[str, str], None]] = None,
    ) -> DownloadResult:
        """Download PDF attachments from emails received in [start_date, end_date].

        Dates are ``YYYY-MM-DD``. Files are saved as
        ``YYYY-MM-DD_NNNN_<original_name>.pdf`` where ``NNNN`` is a per-year
        running counter that increments continuously across the whole year
        (resetting only when the year changes). The counter resumes from the
        highest number already present in ``output_dir`` for that year, so
        separate runs keep counting instead of restarting at ``0001``.

        Attachments already present in ``output_dir`` (matched by email date and
        original name, ignoring the counter) are skipped without re-downloading.
        """
        _callback = log

        def log(level: str, message: str) -> None:
            getattr(logger, level.lower(), logger.info)(message)
            if _callback:
                _callback(level, message)

        out_path = DOWNLOAD_ROOT_DIR / output_dir if output_dir else DOWNLOAD_ROOT_DIR

        if not out_path.exists():
            log("INFO", f"Output directory {out_path} does not exist — clearing cache and creating it")
            self._cache.clear()
            out_path.mkdir(parents=True, exist_ok=True)

        cache_key = (start_date, end_date, output_dir)
        cached = self._cache.get(cache_key)
        if cached is not None:
            log("INFO", f"Cache hit for {start_date}..{end_date}")
            return cached

        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"Invalid date (expected YYYY-MM-DD): {exc}") from exc
        if end_dt < start_dt:
            raise ValueError("end_date must not be before start_date")

        # Gmail `before:` is exclusive by day, so add a day to include end_date.
        before_dt = end_dt + timedelta(days=1)
        query = (
            f"has:attachment filename:pdf "
            f"after:{start_dt.strftime('%Y/%m/%d')} "
            f"before:{before_dt.strftime('%Y/%m/%d')}"
        )
        log("INFO", f"Gmail query: {query}")

        service = self._get_service()
        try:
            message_ids = list(self._iter_message_ids(service, query))
        except HttpError as exc:
            raise Exception(f"Failed to list messages: {exc}") from exc
        log("INFO", f"Found {len(message_ids)} matching email(s)")

        # Fetch full messages, keep only those with PDF parts, sort by date so
        # the per-day sequence numbering is deterministic (oldest first).
        messages: List[Tuple[int, str, List[Tuple[str, str]]]] = []
        for message_id in message_ids:
            try:
                full = service.users().messages().get(
                    userId="me", id=message_id, format="full"
                ).execute()
            except HttpError as exc:
                log("WARN", f"Skipping {message_id}: {exc}")
                continue
            parts = self._extract_pdf_parts(full.get("payload", {}))
            if parts:
                internal = int(full.get("internalDate", "0"))
                messages.append((internal, message_id, parts))
        messages.sort(key=lambda item: item[0])

        seq_by_year, existing = scan_output(out_path)
        skipped = 0
        downloaded: List[DownloadedFile] = []
        for internal, message_id, parts in messages:
            email_dt = datetime.fromtimestamp(internal / 1000)
            date_str = email_dt.strftime("%Y-%m-%d")
            year = email_dt.year
            for original_filename, attachment_id, att_size in parts:
                safe_original = sanitize_filename(original_filename)
                name_part = safe_original
                if not name_part.lower().endswith(".pdf"):
                    name_part += ".pdf"

                # Identity is (name, size) — skips re-downloads across dates and
                # avoids false positives when different files share the same name.
                # att_size == 0 means Gmail didn't report a size; always download.
                if att_size > 0 and (name_part, att_size) in existing:
                    skipped += 1
                    log("INFO", f"Skipping already-downloaded {name_part} ({att_size} bytes)")
                    continue

                try:
                    att = service.users().messages().attachments().get(
                        userId="me", messageId=message_id, id=attachment_id
                    ).execute()
                    data = base64.urlsafe_b64decode(att["data"])
                except (HttpError, KeyError) as exc:
                    log("WARN", f"Failed attachment on {message_id}: {exc}")
                    continue

                seq_by_year[year] = seq_by_year.get(year, 0) + 1
                seq = seq_by_year[year]
                filename = f"{date_str}_{seq:04d}_{name_part}"
                existing.add((name_part, len(data)))

                dest = out_path / filename
                with open(dest, "wb") as fh:
                    fh.write(data)
                log("INFO", f"Saved {filename} ({len(data)} bytes)")
                downloaded.append(DownloadedFile(
                    filename=filename,
                    original_filename=original_filename,
                    message_id=message_id,
                    email_date=date_str,
                    size_bytes=len(data),
                    saved_path=str(dest),
                ))

        if skipped:
            log("INFO", f"Skipped {skipped} already-downloaded file(s)")

        result = DownloadResult(
            total_emails=len(messages),
            total_files=len(downloaded),
            skipped_files=skipped,
            output_dir=str(out_path),
            files=downloaded,
        )
        self._cache.set(cache_key, result)
        return result
