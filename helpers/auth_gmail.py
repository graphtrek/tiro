"""
Run this script ONCE to complete the Google OAuth2 consent flow and
create token.json. After that, Chat.py and gmail_mcp_server.py will
authenticate silently using the saved token.

Usage:
    python helpers/auth_gmail.py
"""
import os
import sys
# Allow running as a standalone script from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import gmail_utils

print("Opening browser for Gmail OAuth2 authorization...")
gmail_utils.get_gmail_service()
print("\u2705 Authorization successful! token.json has been created.")
print("You can now use Gmail in Chat.py and the MCP server in VS Code.")
