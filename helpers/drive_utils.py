# =============================================================================
# drive_utils.py — Google Drive API helper functions
#
# Shared by:
#   - drive_mcp_server.py  (FastMCP tools exposed to VS Code Copilot Agent)
#
# First run: opens a browser for Google OAuth2 consent and writes token.json.
# Subsequent runs: loads and auto-refreshes token.json silently.
#
# Required files in the project root:
#   credentials.json  — downloaded from Google Cloud Console (OAuth 2.0 client)
#   token.json        — auto-generated on first run, never commit to git
#
# NOTE: This module uses a COMBINED scope list (gmail.modify + drive) so that
# token.json remains valid for both Gmail and Drive simultaneously.
# Run helpers/auth_drive.py once to re-authorize with the extended scopes.
# =============================================================================

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# Combined scopes so this token is valid for both Gmail and Drive
_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
]

_ROOT             = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CREDENTIALS_FILE = os.path.join(_ROOT, "credentials.json")
_TOKEN_FILE       = os.path.join(_ROOT, "token.json")

# MIME types used for Google Workspace document exports
_EXPORT_MIME_MAP = {
    "application/vnd.google-apps.document":     ("text/plain",        ".txt"),
    "application/vnd.google-apps.spreadsheet":  ("text/csv",          ".csv"),
    "application/vnd.google-apps.presentation": ("text/plain",        ".txt"),
}


# ── Auth ──────────────────────────────────────────────────────────────────────

def get_drive_service():
    """
    Build and return an authenticated Google Drive API v3 service object.

    Uses the combined scope list (gmail.modify + drive).  Token is loaded from
    token.json and refreshed automatically when expired.  If no valid token
    exists the OAuth2 browser flow is started.
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

    return build("drive", "v3", credentials=creds)


# ── Public API ────────────────────────────────────────────────────────────────

def list_files(
    query: str = "",
    folder_id: str = "",
    page_size: int = 20,
) -> list[dict]:
    """
    List files in Google Drive, optionally filtered by query or parent folder.

    Args:
        query:     Drive query string (e.g. "name contains 'report'",
                   "mimeType='application/pdf'").  Combined with folder_id
                   filter using 'and' when both are provided.
        folder_id: Restrict results to this folder (Drive file ID).
                   Defaults to the entire Drive.
        page_size: Number of files to return (1-100).

    Returns:
        List of dicts with keys: id, name, mimeType, size, modifiedTime,
        webViewLink, parents.
    """
    page_size = max(1, min(100, page_size))
    service = get_drive_service()

    parts: list[str] = ["trashed = false"]
    if folder_id:
        parts.append(f"'{folder_id}' in parents")
    if query:
        parts.append(query)

    full_query = " and ".join(parts)

    try:
        result = service.files().list(
            q=full_query,
            pageSize=page_size,
            fields="files(id,name,mimeType,size,modifiedTime,webViewLink,parents)",
        ).execute()
    except HttpError as e:
        return [{"error": str(e)}]

    return result.get("files", [])


def get_file_metadata(file_id: str) -> dict:
    """
    Return metadata for a single Drive file.

    Args:
        file_id: Google Drive file ID.

    Returns:
        Dict with keys: id, name, mimeType, size, createdTime, modifiedTime,
        webViewLink, webContentLink, parents, owners.
    """
    service = get_drive_service()
    try:
        return service.files().get(
            fileId=file_id,
            fields=(
                "id,name,mimeType,size,createdTime,modifiedTime,"
                "webViewLink,webContentLink,parents,"
                "owners(emailAddress,displayName)"
            ),
        ).execute()
    except HttpError as e:
        return {"error": str(e)}


def read_file_content(file_id: str) -> dict:
    """
    Download and return the text content of a Drive file.

    For Google Workspace documents (Docs, Sheets, Slides) an export is used:
      - Google Docs       → text/plain
      - Google Sheets     → text/csv
      - Google Slides     → text/plain
    For all other files a direct media download is attempted and the bytes are
    decoded as UTF-8.

    Args:
        file_id: Google Drive file ID.

    Returns:
        Dict with keys: id, name, mimeType, content.
        On failure: dict with key 'error'.
    """
    service = get_drive_service()
    try:
        meta = service.files().get(
            fileId=file_id, fields="id,name,mimeType"
        ).execute()
    except HttpError as e:
        return {"error": str(e)}

    mime_type = meta.get("mimeType", "")
    buffer = io.BytesIO()

    try:
        if mime_type in _EXPORT_MIME_MAP:
            export_mime, _ = _EXPORT_MIME_MAP[mime_type]
            request = service.files().export_media(
                fileId=file_id, mimeType=export_mime
            )
        else:
            request = service.files().get_media(fileId=file_id)

        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    except HttpError as e:
        return {"error": str(e)}

    content = buffer.getvalue().decode("utf-8", errors="replace")
    return {
        "id":       file_id,
        "name":     meta.get("name", ""),
        "mimeType": mime_type,
        "content":  content,
    }


def upload_file(
    name: str,
    content: str,
    parent_id: str = "",
    mime_type: str = "text/plain",
) -> dict:
    """
    Upload text content as a new file to Google Drive.

    Args:
        name:      File name (including extension).
        content:   Text content to upload.
        parent_id: Parent folder ID.  Defaults to Drive root.
        mime_type: MIME type of the uploaded content (default: text/plain).

    Returns:
        Dict with keys: id, name, webViewLink on success, or 'error' on failure.
    """
    service = get_drive_service()
    metadata: dict = {"name": name}
    if parent_id:
        metadata["parents"] = [parent_id]

    media = MediaIoBaseUpload(
        io.BytesIO(content.encode("utf-8")),
        mimetype=mime_type,
        resumable=False,
    )
    try:
        result = service.files().create(
            body=metadata,
            media_body=media,
            fields="id,name,webViewLink",
        ).execute()
        return result
    except HttpError as e:
        return {"error": str(e)}


def create_folder(name: str, parent_id: str = "") -> dict:
    """
    Create a new folder in Google Drive.

    Args:
        name:      Folder name.
        parent_id: Parent folder ID.  Defaults to Drive root.

    Returns:
        Dict with keys: id, name, webViewLink on success, or 'error' on failure.
    """
    service = get_drive_service()
    metadata: dict = {
        "name":     name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]
    try:
        result = service.files().create(
            body=metadata,
            fields="id,name,webViewLink",
        ).execute()
        return result
    except HttpError as e:
        return {"error": str(e)}


def move_file(file_id: str, dest_folder_id: str) -> dict:
    """
    Move a file to a different folder.

    Args:
        file_id:        Google Drive file ID of the file to move.
        dest_folder_id: Drive file ID of the destination folder.

    Returns:
        Dict with keys: id, name, parents on success, or 'error' on failure.
    """
    service = get_drive_service()
    try:
        # Retrieve current parents so we can remove them
        file_meta = service.files().get(
            fileId=file_id, fields="parents"
        ).execute()
        previous_parents = ",".join(file_meta.get("parents", []))

        result = service.files().update(
            fileId=file_id,
            addParents=dest_folder_id,
            removeParents=previous_parents,
            fields="id,name,parents",
        ).execute()
        return result
    except HttpError as e:
        return {"error": str(e)}


def copy_file(
    file_id: str,
    name: str = "",
    parent_id: str = "",
) -> dict:
    """
    Copy a file within Google Drive.

    Args:
        file_id:   Google Drive file ID of the source file.
        name:      New file name for the copy.  Defaults to 'Copy of <original>'.
        parent_id: Destination folder ID.  Defaults to same folder as original.

    Returns:
        Dict with keys: id, name, webViewLink on success, or 'error' on failure.
    """
    service = get_drive_service()
    body: dict = {}
    if name:
        body["name"] = name
    if parent_id:
        body["parents"] = [parent_id]
    try:
        result = service.files().copy(
            fileId=file_id,
            body=body,
            fields="id,name,webViewLink",
        ).execute()
        return result
    except HttpError as e:
        return {"error": str(e)}


def trash_file(file_id: str) -> dict:
    """
    Move a file to the Trash.

    Args:
        file_id: Google Drive file ID.

    Returns:
        Dict with keys: id, name, trashed on success, or 'error' on failure.
    """
    service = get_drive_service()
    try:
        result = service.files().update(
            fileId=file_id,
            body={"trashed": True},
            fields="id,name,trashed",
        ).execute()
        return result
    except HttpError as e:
        return {"error": str(e)}


def share_file(
    file_id: str,
    email: str,
    role: str = "reader",
) -> dict:
    """
    Share a file with a specific Google account.

    Args:
        file_id: Google Drive file ID.
        email:   Google account email to share with.
        role:    Permission role: 'reader', 'commenter', or 'writer'.
                 Defaults to 'reader'.

    Returns:
        Dict with keys: id, role, emailAddress on success, or 'error' on failure.
    """
    valid_roles = {"reader", "commenter", "writer"}
    if role not in valid_roles:
        return {"error": f"Invalid role '{role}'. Must be one of: {', '.join(valid_roles)}"}

    service = get_drive_service()
    permission = {
        "type":         "user",
        "role":         role,
        "emailAddress": email,
    }
    try:
        result = service.permissions().create(
            fileId=file_id,
            body=permission,
            fields="id,role,emailAddress",
        ).execute()
        return result
    except HttpError as e:
        return {"error": str(e)}
