"""
Run this script ONCE to complete the Google OAuth2 consent flow for Drive
and update token.json with the combined scopes (gmail.modify + drive).

After running this script, both Chat.py (Gmail) and drive_mcp_server.py
(Drive) will authenticate silently using the saved token.

Usage:
    python helpers/auth_drive.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import drive_utils

print("Opening browser for Google Drive OAuth2 authorization...")
print("NOTE: This will also refresh Gmail authorization with combined scopes.")
drive_utils.get_drive_service()
print("✅ Authorization successful! token.json has been updated.")
print("You can now use Google Drive tools in the MCP server in VS Code.")
