import base64
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Any, Dict, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from attachment_downloader.config import CREDENTIALS_PATH, TOKEN_PATH

logger = logging.getLogger(__name__)
from attachment_downloader.models import (
    EmailSummary,
    EmailDetail,
    Label,
    GmailResponse,
    DownloadedFile,
    DownloadResult,
)

# gmail.modify: read, compose, send, label, trash — no permanent delete
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

# Default output directory for downloaded PDF attachments.
DEFAULT_OUTPUT_DIR = "./downloads"

class GmailClient:
    def __init__(self):
        self._service = None

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

    def _decode_body(self, payload: dict) -> str:
        """Recursively extract plain-text body from a message payload."""
        mime_type = payload.get("mimeType", "")

        if mime_type == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

        if mime_type.startswith("multipart/"):
            for part in payload.get("parts", []):
                text = self._decode_body(part)
                if text:
                    return text

        return ""

    def _get_header(self, headers: list, name: str) -> str:
        """Return the value of a named header, or empty string if absent."""
        for h in headers:
            if h["name"].lower() == name.lower():
                return h["value"]
        return ""

    def list_emails(self, query: str = "in:inbox", max_results: int = 10) -> List[EmailSummary]:
        max_results = max(1, min(50, max_results))
        service = self._get_service()
        try:
            result = service.users().messages().list(
                userId="me", q=query, maxResults=max_results
            ).execute()
        except HttpError as e:
            return [] # Or raise custom exception

        messages = result.get("messages", [])
        summaries = []
        for msg in messages:
            try:
                full = service.users().messages().get(
                    userId="me", id=msg["id"], format="metadata",
                    metadataHeaders=["Subject", "From", "Date"],
                ).execute()
                headers = full.get("payload", {}).get("headers", [])
                summaries.append(EmailSummary(
                    id=msg["id"],
                    subject=self._get_header(headers, "Subject"),
                    from_address=self._get_header(headers, "From"),
                    date=self._get_header(headers, "Date"),
                    snippet=full.get("snippet", ""),
                ))
            except (HttpError, KeyError):
                continue
        return summaries

    def read_email(self, message_id: str) -> EmailDetail:
        service = self._get_service()
        try:
            msg = service.users().messages().get(
                userId="me", id=message_id, format="full"
            ).execute()
            headers = msg.get("payload", {}).get("headers", [])
            body = self._decode_body(msg.get("payload", {}))

            return EmailDetail(
                id=message_id,
                subject=self._get_header(headers, "Subject"),
                from_address=self._get_header(headers, "From"),
                to=self._get_header(headers, "To"),
                date=self._get_header(headers, "Date"),
                body=body,
            )
        except HttpError as e:
            raise Exception(f"Failed to read email: {str(e)}")

    def send_email(self, to: str, subject: str, body: str, cc: str = "", bcc: str = "") -> str:
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        service = self._get_service()
        mime_msg = MIMEMultipart()
        mime_msg["To"]      = to
        mime_msg["Subject"] = subject
        if cc:
            mime_msg["Cc"] = cc
        if bcc:
            mime_msg["Bcc"] = bcc
        mime_msg.attach(MIMEText(body, "plain", "utf-8"))

        raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()
        try:
            sent = service.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()
            return sent["id"]
        except HttpError as e:
            raise Exception(f"Failed to send email: {str(e)}")

    def reply_to_email(self, message_id: str, body: str) -> str:
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        
        service = self._get_service()
        try:
            original = service.users().messages().get(
                userId="me", id=message_id, format="metadata",
                metadataHeaders=["Subject", "From", "Message-ID"],
            ).execute()
        except HttpError as e:
            raise Exception(f"Failed to fetch original email: {str(e)}")

        headers    = original.get("payload", {}).get("headers", [])
        subject    = self._get_header(headers, "Subject")
        sender     = self._get_header(headers, "From")
        message_id_header = self._get_header(headers, "Message-ID")
        thread_id  = original.get("threadId", "")

        if not subject.lower().startswith("re:"):
            subject = "Re: " + subject

        mime_msg = MIMEMultipart()
        mime_msg["To"]         = sender
        mime_msg["Subject"]    = subject
        mime_msg["In-Reply-To"] = message_id_header
        mime_msg["References"]  = message_id_header
        mime_msg.attach(MIMEText(body, "plain", "utf-8"))

        raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()
        try:
            sent = service.users().messages().send(
                userId="me", body={"raw": raw, "threadId": thread_id}
            ).execute()
            return sent["id"]
        except HttpError as e:
            raise Exception(f"Failed to send reply: {str(e)}")

    def list_labels(self) -> List[Label]:
        service = self._get_service()
        try:
            result = service.users().labels().list(userId="me").execute()
            return [
                Label(id=lbl["id"], name=lbl["name"], type=lbl.get("type", ""))
                for lbl in result.get("labels", [])
            ]
        except HttpError as e:
            raise Exception(f"Failed to list labels: {str(e)}")

    def label_email(self, message_id: str, add_labels: Optional[List[str]] = None, remove_labels: Optional[List[str]] = None) -> Dict:
        service = self._get_service()
        body: dict = {}
        if add_labels:
            body["addLabelIds"] = add_labels
        if remove_labels:
            body["removeLabelIds"] = remove_labels
        try:
            result = service.users().messages().modify(
                userId="me", id=message_id, body=body
            ).execute()
            return {"id": result["id"], "labelIds": result.get("labelIds", [])}
        except HttpError as e:
            raise Exception(f"Failed to modify labels: {str(e)}")

    def trash_email(self, message_id: str) -> str:
        service = self._get_service()
        try:
            result = service.users().messages().trash(
                userId="me", id=message_id
            ).execute()
            return result["id"]
        except HttpError as e:
            raise Exception(f"Failed to trash email: {str(e)}")

    def mark_as_read(self, message_id: str):
        return self.label_email(message_id, remove_labels=["UNREAD"])

    def mark_as_unread(self, message_id: str):
        return self.label_email(message_id, add_labels=["UNREAD"])

    # --- PDF attachment download (graphtrek-email Moneypenny service) ---

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Strip any path component and replace unsafe characters."""
        name = os.path.basename(name or "")
        name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
        return name or "attachment.pdf"

    # Matches our naming scheme ``YYYY-MM-DD_NNN(N)_<name>`` and captures the
    # date, the (zero-padded) running counter, and the trailing name part.
    _NAME_RE = re.compile(r"^((\d{4})-\d{2}-\d{2})_(\d+)_(.+)$")

    @classmethod
    def _scan_output(
        cls, out_path: Path
    ) -> Tuple[Dict[int, int], set]:
        """Scan ``out_path`` once for previously downloaded files.

        Returns ``(max_seq_by_year, identities)`` where ``max_seq_by_year`` maps
        each year to the highest counter already used (so the per-year counter
        resumes across runs) and ``identities`` is a set of ``(date, name)``
        keys used to skip attachments that were already downloaded.
        """
        max_seq: Dict[int, int] = {}
        identities: set = set()
        if not out_path.is_dir():
            return max_seq, identities
        for entry in out_path.iterdir():
            match = cls._NAME_RE.match(entry.name)
            if not match:
                continue
            date_str, year, seq, name_part = match.groups()
            year, seq = int(year), int(seq)
            if seq > max_seq.get(year, 0):
                max_seq[year] = seq
            identities.add((date_str, name_part))
        return max_seq, identities

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

    def _extract_pdf_parts(self, payload: dict) -> List[Tuple[str, str]]:
        """Return (filename, attachment_id) for every PDF attachment in a payload."""
        results: List[Tuple[str, str]] = []

        def walk(part: dict) -> None:
            filename = part.get("filename", "") or ""
            mime_type = part.get("mimeType", "") or ""
            body = part.get("body", {}) or {}
            attachment_id = body.get("attachmentId")
            is_pdf = filename.lower().endswith(".pdf") or mime_type == "application/pdf"
            if attachment_id and is_pdf:
                results.append((filename or "attachment.pdf", attachment_id))
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

        output_dir = output_dir or DEFAULT_OUTPUT_DIR
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

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

        # Seed the per-year counter and the set of already-downloaded files from
        # output_dir so the sequence resumes across runs and attachments that
        # are already present are skipped.
        seq_by_year, existing = self._scan_output(out_path)
        skipped = 0
        downloaded: List[DownloadedFile] = []
        for internal, message_id, parts in messages:
            email_dt = datetime.fromtimestamp(internal / 1000)
            date_str = email_dt.strftime("%Y-%m-%d")
            year = email_dt.year
            for original_filename, attachment_id in parts:
                safe_original = self._sanitize_filename(original_filename)
                name_part = safe_original
                if not name_part.lower().endswith(".pdf"):
                    name_part += ".pdf"

                # Identity is (email date, name) — stable across runs since the
                # running counter is not part of it. Skip without fetching the
                # attachment bytes when we already have this file.
                if (date_str, name_part) in existing:
                    skipped += 1
                    log("INFO", f"Skipping already-downloaded {date_str} {name_part}")
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
                existing.add((date_str, name_part))

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

        return DownloadResult(
            total_emails=len(messages),
            total_files=len(downloaded),
            skipped_files=skipped,
            output_dir=str(out_path),
            files=downloaded,
        )