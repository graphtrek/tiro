# =============================================================================
# gmail_utils.py — Gmail API helper functions
#
# Shared by:
#   - gmail_mcp_server.py  (FastMCP tools exposed to VS Code Copilot Agent)
#   - Chat.py              (OpenAI function-calling integration)
#
# First run: opens a browser for Google OAuth2 consent and writes token.json.
# Subsequent runs: loads and auto-refreshes token.json silently.
#
# Required files in the project root:
#   credentials.json  — downloaded from Google Cloud Console (OAuth 2.0 client)
#   token.json        — auto-generated on first run, never commit to git
# =============================================================================

import base64
import email as _email_lib
import json
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# gmail.modify: read, compose, send, label, trash — no permanent delete
_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

_ROOT            = os.path.dirname(os.path.abspath(__file__))
_CREDENTIALS_FILE = os.path.join(_ROOT, "credentials.json")
_TOKEN_FILE       = os.path.join(_ROOT, "token.json")


# ── Auth ──────────────────────────────────────────────────────────────────────

def get_gmail_service():
    """
    Build and return an authenticated Gmail API service object.

    Token is loaded from token.json if it exists and refreshed automatically
    when expired. If no valid token exists the OAuth2 browser flow is started.
    """
    creds = None

    if os.path.exists(_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(_TOKEN_FILE, _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(_CREDENTIALS_FILE):
                raise FileNotFoundError(
                    "credentials.json not found. Download your OAuth2 Desktop "
                    "client credentials from Google Cloud Console and place the "
                    f"file at: {_CREDENTIALS_FILE}"
                )
            flow = InstalledAppFlow.from_client_secrets_file(_CREDENTIALS_FILE, _SCOPES)
            creds = flow.run_local_server(port=0)

        with open(_TOKEN_FILE, "w") as token_file:
            token_file.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _decode_body(payload: dict) -> str:
    """Recursively extract plain-text body from a message payload."""
    mime_type = payload.get("mimeType", "")

    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

    if mime_type.startswith("multipart/"):
        for part in payload.get("parts", []):
            text = _decode_body(part)
            if text:
                return text

    return ""


def _header(headers: list, name: str) -> str:
    """Return the value of a named header, or empty string if absent."""
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


# ── Public API ────────────────────────────────────────────────────────────────

def list_emails(query: str = "in:inbox", max_results: int = 10) -> list[dict]:
    """
    Search Gmail and return a list of message summaries.

    Args:
        query:       Gmail search query (e.g. "is:unread", "from:boss@example.com").
        max_results: Maximum number of messages to return (1-50).

    Returns:
        List of dicts with keys: id, subject, from, date, snippet.
    """
    max_results = max(1, min(50, max_results))
    service = get_gmail_service()
    try:
        result = service.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
    except HttpError as e:
        return [{"error": str(e)}]

    messages = result.get("messages", [])
    summaries = []
    for msg in messages:
        try:
            full = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            ).execute()
            headers = full.get("payload", {}).get("headers", [])
            summaries.append({
                "id":      msg["id"],
                "subject": _header(headers, "Subject"),
                "from":    _header(headers, "From"),
                "date":    _header(headers, "Date"),
                "snippet": full.get("snippet", ""),
            })
        except HttpError:
            summaries.append({"id": msg["id"], "error": "failed to fetch metadata"})
    return summaries


def read_email(message_id: str) -> dict:
    """
    Fetch the full content of a single email.

    Args:
        message_id: Gmail message ID (from list_emails).

    Returns:
        Dict with keys: id, subject, from, to, date, body.
    """
    service = get_gmail_service()
    try:
        msg = service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()
    except HttpError as e:
        return {"error": str(e)}

    headers = msg.get("payload", {}).get("headers", [])
    body    = _decode_body(msg.get("payload", {}))

    return {
        "id":      message_id,
        "subject": _header(headers, "Subject"),
        "from":    _header(headers, "From"),
        "to":      _header(headers, "To"),
        "date":    _header(headers, "Date"),
        "body":    body,
    }


def send_email(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
) -> dict:
    """
    Compose and send a new email.

    Args:
        to:      Recipient address(es), comma-separated.
        subject: Email subject line.
        body:    Plain-text body.
        cc:      CC address(es), comma-separated (optional).
        bcc:     BCC address(es), comma-separated (optional).

    Returns:
        Dict with key 'id' on success, or 'error' on failure.
    """
    service = get_gmail_service()
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
        return {"id": sent["id"], "status": "sent"}
    except HttpError as e:
        return {"error": str(e)}


def reply_to_email(message_id: str, body: str) -> dict:
    """
    Reply to an existing email, preserving the thread.

    Args:
        message_id: The Gmail message ID to reply to.
        body:       Plain-text reply body.

    Returns:
        Dict with key 'id' on success, or 'error' on failure.
    """
    service = get_gmail_service()
    try:
        original = service.users().messages().get(
            userId="me", id=message_id, format="metadata",
            metadataHeaders=["Subject", "From", "Message-ID"],
        ).execute()
    except HttpError as e:
        return {"error": str(e)}

    headers    = original.get("payload", {}).get("headers", [])
    subject    = _header(headers, "Subject")
    sender     = _header(headers, "From")
    message_id_header = _header(headers, "Message-ID")
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
        return {"id": sent["id"], "status": "sent", "threadId": thread_id}
    except HttpError as e:
        return {"error": str(e)}


def list_labels() -> list[dict]:
    """
    Return all Gmail labels for the authenticated account.

    Returns:
        List of dicts with keys: id, name, type.
    """
    service = get_gmail_service()
    try:
        result = service.users().labels().list(userId="me").execute()
        return [
            {"id": lbl["id"], "name": lbl["name"], "type": lbl.get("type", "")}
            for lbl in result.get("labels", [])
        ]
    except HttpError as e:
        return [{"error": str(e)}]


def label_email(
    message_id: str,
    add_labels: Optional[list[str]] = None,
    remove_labels: Optional[list[str]] = None,
) -> dict:
    """
    Add and/or remove labels on a message.

    Args:
        message_id:    Gmail message ID.
        add_labels:    List of label IDs to add (e.g. ["STARRED"]).
        remove_labels: List of label IDs to remove (e.g. ["UNREAD"]).

    Returns:
        Dict with key 'id' on success, or 'error' on failure.
    """
    service = get_gmail_service()
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
        return {"error": str(e)}


def trash_email(message_id: str) -> dict:
    """
    Move a message to the Trash.

    Args:
        message_id: Gmail message ID.

    Returns:
        Dict with key 'id' on success, or 'error' on failure.
    """
    service = get_gmail_service()
    try:
        result = service.users().messages().trash(
            userId="me", id=message_id
        ).execute()
        return {"id": result["id"], "status": "trashed"}
    except HttpError as e:
        return {"error": str(e)}


def mark_as_read(message_id: str) -> dict:
    """
    Remove the UNREAD label from a message (mark as read).

    Args:
        message_id: Gmail message ID.

    Returns:
        Dict with key 'id' on success, or 'error' on failure.
    """
    return label_email(message_id, remove_labels=["UNREAD"])


def mark_as_unread(message_id: str) -> dict:
    """
    Add the UNREAD label to a message (mark as unread).

    Args:
        message_id: Gmail message ID.

    Returns:
        Dict with key 'id' on success, or 'error' on failure.
    """
    return label_email(message_id, add_labels=["UNREAD"])
