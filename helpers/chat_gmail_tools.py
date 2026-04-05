class GmailTools:
    """OpenAI function-calling tool definitions for the Gmail integration."""

    TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "list_emails",
                "description": "Search Gmail and return a list of message summaries (id, subject, from, date, snippet).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query":       {"type": "string",  "description": "Gmail search query, e.g. 'is:unread', 'from:boss@example.com'"},
                        "max_results": {"type": "integer", "description": "Number of messages to return (1-50)"},
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_email",
                "description": "Fetch the full content (subject, from, to, date, body) of a single email by its ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string", "description": "Gmail message ID from list_emails"},
                    },
                    "required": ["message_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "send_email",
                "description": "Compose and send a new email.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to":      {"type": "string", "description": "Recipient address(es), comma-separated"},
                        "subject": {"type": "string", "description": "Subject line"},
                        "body":    {"type": "string", "description": "Plain-text message body"},
                        "cc":      {"type": "string", "description": "CC address(es), comma-separated (optional)"},
                        "bcc":     {"type": "string", "description": "BCC address(es), comma-separated (optional)"},
                    },
                    "required": ["to", "subject", "body"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "reply_to_email",
                "description": "Reply to an existing email, staying in the same thread.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string", "description": "Gmail message ID of the email to reply to"},
                        "body":       {"type": "string", "description": "Plain-text reply body"},
                    },
                    "required": ["message_id", "body"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_labels",
                "description": "Return all Gmail labels for the authenticated account.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "label_email",
                "description": "Add and/or remove labels on an email (e.g. add STARRED, remove UNREAD).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message_id":    {"type": "string", "description": "Gmail message ID"},
                        "add_labels":    {"type": "array",  "items": {"type": "string"}, "description": "Label IDs to add"},
                        "remove_labels": {"type": "array",  "items": {"type": "string"}, "description": "Label IDs to remove"},
                    },
                    "required": ["message_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "trash_email",
                "description": "Move an email to the Trash.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string", "description": "Gmail message ID"},
                    },
                    "required": ["message_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "mark_as_read",
                "description": "Mark an email as read (removes the UNREAD label).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string", "description": "Gmail message ID"},
                    },
                    "required": ["message_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "mark_as_unread",
                "description": "Mark an email as unread (adds the UNREAD label).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string", "description": "Gmail message ID"},
                    },
                    "required": ["message_id"],
                },
            },
        },
    ]
