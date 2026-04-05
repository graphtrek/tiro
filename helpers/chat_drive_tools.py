class DriveTools:
    """OpenAI function-calling tool definitions for the Google Drive integration."""

    TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": (
                    "List files in Google Drive, optionally filtered by search query or parent folder. "
                    "Returns id, name, mimeType, size, modifiedTime, webViewLink."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query":     {"type": "string",  "description": "Drive query string, e.g. \"name contains 'report'\", \"mimeType='application/pdf'\""},
                        "folder_id": {"type": "string",  "description": "Restrict to this folder's Drive file ID (optional)"},
                        "page_size": {"type": "integer", "description": "Number of files to return (1-100, default 20)"},
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_file_metadata",
                "description": "Return detailed metadata for a single Drive file: id, name, mimeType, size, createdTime, modifiedTime, webViewLink, parents, owners.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string", "description": "Google Drive file ID (from list_files)"},
                    },
                    "required": ["file_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file_content",
                "description": (
                    "Download and return the text content of a Drive file. "
                    "Google Docs are exported as plain text, Sheets as CSV, Slides as plain text. "
                    "Other files are decoded as UTF-8."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string", "description": "Google Drive file ID (from list_files)"},
                    },
                    "required": ["file_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "upload_file",
                "description": "Upload text content as a new file to Google Drive.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name":      {"type": "string", "description": "File name including extension"},
                        "content":   {"type": "string", "description": "Text content to upload"},
                        "parent_id": {"type": "string", "description": "Parent folder ID (optional, defaults to Drive root)"},
                        "mime_type": {"type": "string", "description": "MIME type of the content (default: text/plain)"},
                    },
                    "required": ["name", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_folder",
                "description": "Create a new folder in Google Drive.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name":      {"type": "string", "description": "Folder name"},
                        "parent_id": {"type": "string", "description": "Parent folder ID (optional, defaults to Drive root)"},
                    },
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "move_file",
                "description": "Move a file to a different folder in Google Drive.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id":        {"type": "string", "description": "Google Drive file ID of the file to move"},
                        "dest_folder_id": {"type": "string", "description": "Drive file ID of the destination folder"},
                    },
                    "required": ["file_id", "dest_folder_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "copy_file",
                "description": "Copy a file within Google Drive.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id":   {"type": "string", "description": "Google Drive file ID of the source file"},
                        "name":      {"type": "string", "description": "New file name for the copy (optional)"},
                        "parent_id": {"type": "string", "description": "Destination folder ID (optional)"},
                    },
                    "required": ["file_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "trash_file",
                "description": "Move a file to the Trash in Google Drive.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string", "description": "Google Drive file ID"},
                    },
                    "required": ["file_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "share_file",
                "description": "Share a Drive file with a Google account (reader, commenter, or writer).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string", "description": "Google Drive file ID"},
                        "email":   {"type": "string", "description": "Google account email address to share with"},
                        "role":    {"type": "string", "description": "Permission: 'reader', 'commenter', or 'writer'"},
                    },
                    "required": ["file_id", "email"],
                },
            },
        },
    ]
