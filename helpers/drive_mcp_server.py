# =============================================================================
# drive_mcp_server.py — FastMCP server wrapping drive_utils
#
# Exposes all Google Drive functions as MCP tools so VS Code GitHub Copilot
# Agent can call them directly in chat.
#
# Run once to complete OAuth consent (opens browser):
#   python helpers/auth_drive.py
#
# VS Code registers this via .vscode/mcp.json (stdio transport).
# =============================================================================

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP
from helpers import drive_utils

mcp = FastMCP("gdrive")


@mcp.tool()
def list_files(
    query: str = "",
    folder_id: str = "",
    page_size: int = 20,
) -> list:
    """
    List files in Google Drive.

    Args:
        query:     Drive query string (e.g. "name contains 'report'",
                   "mimeType='application/pdf'").
        folder_id: Restrict results to this folder (Drive file ID).
                   Leave empty to search the entire Drive.
        page_size: Number of files to return (1-100).
    """
    return drive_utils.list_files(query=query, folder_id=folder_id, page_size=page_size)


@mcp.tool()
def get_file_metadata(file_id: str) -> dict:
    """
    Return detailed metadata for a single Drive file.

    Args:
        file_id: Google Drive file ID (obtained from list_files).
    """
    return drive_utils.get_file_metadata(file_id=file_id)


@mcp.tool()
def read_file_content(file_id: str) -> dict:
    """
    Download and return the text content of a Drive file.

    Google Workspace documents are exported as plain text / CSV.
    Binary files are decoded as UTF-8.

    Args:
        file_id: Google Drive file ID (obtained from list_files).
    """
    return drive_utils.read_file_content(file_id=file_id)


@mcp.tool()
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
        parent_id: Parent folder ID.  Leave empty to upload to Drive root.
        mime_type: MIME type of the content (default: text/plain).
    """
    return drive_utils.upload_file(
        name=name, content=content, parent_id=parent_id, mime_type=mime_type
    )


@mcp.tool()
def create_folder(name: str, parent_id: str = "") -> dict:
    """
    Create a new folder in Google Drive.

    Args:
        name:      Folder name.
        parent_id: Parent folder ID.  Leave empty to create in Drive root.
    """
    return drive_utils.create_folder(name=name, parent_id=parent_id)


@mcp.tool()
def move_file(file_id: str, dest_folder_id: str) -> dict:
    """
    Move a file to a different folder.

    Args:
        file_id:        Google Drive file ID of the file to move.
        dest_folder_id: Drive file ID of the destination folder.
    """
    return drive_utils.move_file(file_id=file_id, dest_folder_id=dest_folder_id)


@mcp.tool()
def copy_file(file_id: str, name: str = "", parent_id: str = "") -> dict:
    """
    Copy a file within Google Drive.

    Args:
        file_id:   Google Drive file ID of the source file.
        name:      New file name for the copy (optional).
        parent_id: Destination folder ID (optional, defaults to same folder).
    """
    return drive_utils.copy_file(file_id=file_id, name=name, parent_id=parent_id)


@mcp.tool()
def trash_file(file_id: str) -> dict:
    """
    Move a file to the Trash.

    Args:
        file_id: Google Drive file ID.
    """
    return drive_utils.trash_file(file_id=file_id)


@mcp.tool()
def share_file(file_id: str, email: str, role: str = "reader") -> dict:
    """
    Share a Drive file with a Google account.

    Args:
        file_id: Google Drive file ID.
        email:   Google account email address to share with.
        role:    Permission level: 'reader', 'commenter', or 'writer'.
    """
    return drive_utils.share_file(file_id=file_id, email=email, role=role)


if __name__ == "__main__":
    mcp.run(transport="stdio")
