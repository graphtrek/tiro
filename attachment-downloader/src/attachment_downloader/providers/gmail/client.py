import base64
import logging
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from attachment_downloader.cache import TTLCache
from attachment_downloader.config import Settings, get_settings
from attachment_downloader.models import DownloadedFile, DownloadResult
from attachment_downloader.utils import sanitize_filename, scan_output

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

_Emit = Callable[[str, str], None]
_Part = tuple[str, str, int]  # (filename, attachment_id, size_bytes)
_Msg = tuple[int, str, list[_Part]]  # (internal_ms, message_id, parts)


class GmailClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._service = None
        self._cache: TTLCache = TTLCache(ttl_seconds=self._settings.cache_ttl_seconds)

    # --- Public cache management ---

    def cache_stats(self) -> dict:
        return self._cache.stats

    def cache_clear(self) -> int:
        return self._cache.clear()

    # --- Auth ---

    def _get_service(self):
        if self._service:
            return self._service

        creds = None
        token_path = self._settings.token_path
        credentials_path = self._settings.credentials_path

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("OAuth token expired — refreshing")
                creds.refresh(Request())
                logger.info("OAuth token refreshed")
            else:
                if not credentials_path.exists():
                    raise FileNotFoundError(
                        f"Credentials file not found at: {credentials_path}. "
                        "Please ensure the JSON file is in the project root."
                    )
                logger.info("Starting OAuth2 browser flow")
                flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
                creds = flow.run_local_server(port=8888)
                logger.info("OAuth2 authentication completed")

            with open(str(token_path), "w") as token_file:
                token_file.write(creds.to_json())

        self._service = build("gmail", "v1", credentials=creds)
        return self._service

    # --- Private helpers ---

    def _iter_message_ids(self, service, query: str) -> Iterator[str]:
        """Yield every message id matching ``query``, paging through results."""
        page_token = None
        while True:
            resp = (
                service.users()
                .messages()
                .list(userId="me", q=query, maxResults=100, pageToken=page_token)
                .execute()
            )
            for msg in resp.get("messages", []):
                yield msg["id"]
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

    def _extract_pdf_parts(self, payload: dict) -> list[_Part]:
        """Return (filename, attachment_id, size) for every PDF attachment in a payload."""
        results: list[_Part] = []

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

    @staticmethod
    def _build_query(start_dt: datetime, end_dt: datetime) -> str:
        # Gmail `before:` is exclusive by day, so add a day to include end_date.
        before_dt = end_dt + timedelta(days=1)
        return (
            f"has:attachment filename:pdf "
            f"after:{start_dt.strftime('%Y/%m/%d')} "
            f"before:{before_dt.strftime('%Y/%m/%d')}"
        )

    def _fetch_messages(self, service, query: str, emit: _Emit) -> list[_Msg]:
        """List and fetch full messages matching query; return sorted by date."""
        try:
            message_ids = list(self._iter_message_ids(service, query))
        except HttpError as exc:
            raise RuntimeError(f"Failed to list messages: {exc}") from exc
        emit("INFO", f"Found {len(message_ids)} matching email(s)")

        messages: list[_Msg] = []
        for message_id in message_ids:
            try:
                full = (
                    service.users()
                    .messages()
                    .get(userId="me", id=message_id, format="full")
                    .execute()
                )
            except HttpError as exc:
                emit("WARN", f"Skipping {message_id}: {exc}")
                continue
            parts = self._extract_pdf_parts(full.get("payload", {}))
            if parts:
                internal = int(full.get("internalDate", "0"))
                messages.append((internal, message_id, parts))

        messages.sort(key=lambda item: item[0])
        return messages

    def _save_attachment(self, service, msg_id: str, att_id: str, emit: _Emit) -> bytes | None:
        """Fetch and decode one attachment; returns None on error."""
        try:
            att = (
                service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=msg_id, id=att_id)
                .execute()
            )
            return base64.urlsafe_b64decode(att["data"])
        except (HttpError, KeyError) as exc:
            emit("WARN", f"Failed attachment on {msg_id}: {exc}")
            return None

    # --- Main entry point ---

    def download_pdf_attachments(
        self,
        start_date: str,
        end_date: str,
        output_dir: str | None = None,
        log: Callable[[str, str], None] | None = None,
    ) -> DownloadResult:
        """Download PDF attachments from emails received in [start_date, end_date].

        Dates are ``YYYY-MM-DD``. Files are saved as
        ``YYYY-MM-DD_NNNN_<original_name>.pdf`` where ``NNNN`` is a per-year
        running counter that increments continuously across the whole year
        (resetting only when the year changes). The counter resumes from the
        highest number already present in ``output_dir`` for that year, so
        separate runs keep counting instead of restarting at ``0001``.

        Attachments already present in ``output_dir`` (matched by original name
        and size, ignoring the counter) are skipped without re-downloading.
        """

        def _emit(level: str, message: str) -> None:
            getattr(logger, level.lower(), logger.info)(message)
            if log:
                log(level, message)

        out_path = (
            self._settings.download_root / output_dir
            if output_dir
            else self._settings.download_root
        )

        if not out_path.exists():
            _emit(
                "INFO",
                f"Output directory {out_path} does not exist — clearing cache and creating it",
            )
            self._cache.clear()
            out_path.mkdir(parents=True, exist_ok=True)

        cache_key = (start_date, end_date, output_dir)
        cached = self._cache.get(cache_key)
        if cached is not None:
            _emit("INFO", f"Cache hit for {start_date}..{end_date}")
            return cached

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")  # noqa: DTZ007 - calendar date
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")  # noqa: DTZ007 - calendar date

        query = self._build_query(start_dt, end_dt)
        _emit("INFO", f"Gmail query: {query}")

        service = self._get_service()
        messages = self._fetch_messages(service, query, _emit)

        seq_by_year, existing = scan_output(out_path)
        skipped = 0
        downloaded: list[DownloadedFile] = []

        for internal, message_id, parts in messages:
            # Gmail internalDate is a UTC epoch (ms); convert to local time, matching
            # the previous naive-fromtimestamp wall-clock date used for filenames.
            email_dt = datetime.fromtimestamp(internal / 1000, tz=UTC).astimezone()
            date_str = email_dt.strftime("%Y-%m-%d")
            year = email_dt.year

            for original_filename, attachment_id, att_size in parts:
                safe_name = sanitize_filename(original_filename)
                if not safe_name.lower().endswith(".pdf"):
                    safe_name += ".pdf"

                # Identity is (name, size); att_size==0 means Gmail didn't report one —
                # always download.
                if att_size > 0 and (safe_name, att_size) in existing:
                    skipped += 1
                    _emit("INFO", f"Skipping already-downloaded {safe_name} ({att_size} bytes)")
                    continue

                data = self._save_attachment(service, message_id, attachment_id, _emit)
                if data is None:
                    continue

                seq_by_year[year] = seq_by_year.get(year, 0) + 1
                filename = f"{date_str}_{seq_by_year[year]:04d}_{safe_name}"
                existing.add((safe_name, len(data)))

                dest = out_path / filename
                dest.write_bytes(data)
                _emit("INFO", f"Saved {filename} ({len(data)} bytes)")
                downloaded.append(
                    DownloadedFile(
                        filename=filename,
                        original_filename=original_filename,
                        message_id=message_id,
                        email_date=date_str,
                        size_bytes=len(data),
                        saved_path=str(dest),
                    )
                )

        if skipped:
            _emit("INFO", f"Skipped {skipped} already-downloaded file(s)")

        result = DownloadResult(
            total_emails=len(messages),
            total_files=len(downloaded),
            skipped_files=skipped,
            output_dir=str(out_path),
            files=downloaded,
        )
        self._cache.set(cache_key, result)
        return result
