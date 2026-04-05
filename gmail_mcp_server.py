# =============================================================================
# gmail_mcp_server.py — FastMCP server wrapping gmail_utils
#
# Exposes all Gmail functions as MCP tools so VS Code GitHub Copilot Agent
# can call them directly in chat.
#
# Run once to complete OAuth consent (opens browser):
#   python gmail_mcp_server.py
#
# VS Code registers this via .vscode/mcp.json (stdio transport).
# =============================================================================

from mcp.server.fastmcp import FastMCP

import gmail_utils

mcp = FastMCP("gmail")


@mcp.tool()
def list_emails(query: str = "in:inbox", max_results: int = 10) -> list:
    """
    Search Gmail and return message summaries.

    Args:
        query:       Gmail search query string (e.g. "is:unread", "from:someone@example.com").
        max_results: Number of messages to return (1-50).
    """
    return gmail_utils.list_emails(query=query, max_results=max_results)


@mcp.tool()
def read_email(message_id: str) -> dict:
    """
    Fetch the full content of an email by its ID.

    Args:
        message_id: Gmail message ID obtained from list_emails.
    """
    return gmail_utils.read_email(message_id=message_id)


@mcp.tool()
def send_email(to: str, subject: str, body: str, cc: str = "", bcc: str = "") -> dict:
    """
    Compose and send a new email.

    Args:
        to:      Recipient address(es), comma-separated.
        subject: Subject line.
        body:    Plain-text message body.
        cc:      CC address(es), comma-separated (optional).
        bcc:     BCC address(es), comma-separated (optional).
    """
    return gmail_utils.send_email(to=to, subject=subject, body=body, cc=cc, bcc=bcc)


@mcp.tool()
def reply_to_email(message_id: str, body: str) -> dict:
    """
    Reply to an existing email, staying in the same thread.

    Args:
        message_id: Gmail message ID of the email to reply to.
        body:       Plain-text reply body.
    """
    return gmail_utils.reply_to_email(message_id=message_id, body=body)


@mcp.tool()
def list_labels() -> list:
    """Return all Gmail labels for the authenticated account."""
    return gmail_utils.list_labels()


@mcp.tool()
def label_email(
    message_id: str,
    add_labels: list[str] | None = None,
    remove_labels: list[str] | None = None,
) -> dict:
    """
    Add and/or remove labels on a message.

    Args:
        message_id:    Gmail message ID.
        add_labels:    List of label IDs to add (e.g. ["STARRED"]).
        remove_labels: List of label IDs to remove (e.g. ["UNREAD"]).
    """
    return gmail_utils.label_email(
        message_id=message_id,
        add_labels=add_labels,
        remove_labels=remove_labels,
    )


@mcp.tool()
def trash_email(message_id: str) -> dict:
    """
    Move a message to the Trash.

    Args:
        message_id: Gmail message ID.
    """
    return gmail_utils.trash_email(message_id=message_id)


@mcp.tool()
def mark_as_read(message_id: str) -> dict:
    """
    Mark a message as read (removes the UNREAD label).

    Args:
        message_id: Gmail message ID.
    """
    return gmail_utils.mark_as_read(message_id=message_id)


@mcp.tool()
def mark_as_unread(message_id: str) -> dict:
    """
    Mark a message as unread (adds the UNREAD label).

    Args:
        message_id: Gmail message ID.
    """
    return gmail_utils.mark_as_unread(message_id=message_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
