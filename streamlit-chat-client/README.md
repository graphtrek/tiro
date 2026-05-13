# Moneypenny Chat Client

A standalone Streamlit chat application that connects to the Moneypenny Agent streaming endpoint.

## Setup

### Prerequisites
- Python 3.9+
- Moneypenny Agent running on `http://localhost:8600/stream`

### Installation

1. Create a Python virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

The app is ready to use! All configuration is in the `.env` file with sensible defaults.

## Running the App

```bash
streamlit run app.py
```

The app will open in your browser at `http://localhost:8501`.

## Features

- ✅ Chat interface with message history
- ✅ Automatic session ID generation and persistence
- ✅ Streaming responses from the endpoint
- ✅ Clear chat history button
- ✅ Session info display (session ID, endpoint URL)
- ✅ Error handling for connection failures and timeouts
- ✅ Simple, clean UI with message timestamps
- ✅ Comprehensive logging to `logs/` folder (daily log files)

## Configuration

The app reads environment variables from the `.env` file:
- `STREAM_ENDPOINT_URL` — Moneypenny Agent endpoint (default: `http://localhost:8600/stream`)
- `REQUEST_TIMEOUT` — Request timeout in seconds (default: `60`)

Edit `.env` to customize these values if needed. A `.env.example` template is provided as reference.

## Logging

All chat interactions are logged to the `logs/` folder with daily log files named `chat_YYYYMMDD.log`.

Log entries include:
- `[INIT]` — Session initialization with session ID
- `[SEND]` — User messages sent to the endpoint
- `[CONNECTED]` — Connection established with response status
- `[COMPLETE]` — Response streaming completed with chunk count
- `[USER]` — User message added to history
- `[ASSISTANT]` — Assistant response added to history
- `[CLEAR]` — Chat history cleared
- `[ERROR]` — Any connection or processing errors

Example log:
```
2026-05-13 14:32:15,123 | INFO     | app.py:42 | [INIT] New session_id=a1b2c3d4-e5f6-7890-abcd-ef1234567890
2026-05-13 14:32:22,456 | INFO     | app.py:187 | [SEND] session_id=a1b2c3d4-e5f6-7890-abcd-ef1234567890 | message=How are we financially?
2026-05-13 14:32:22,789 | INFO     | app.py:197 | [CONNECTED] endpoint=http://localhost:8600/stream | status=200
2026-05-13 14:32:25,012 | INFO     | app.py:208 | [COMPLETE] chunks=5
2026-05-13 14:32:25,123 | INFO     | app.py:215 | [ASSISTANT] We are doing well financially this quarter...
```

## Message Format

The app sends POST requests with this JSON format:
```json
{
  "message": "Your message here",
  "session_id": "uuid-string"
}
```

The endpoint should return newline-delimited JSON objects with a `content` field:
```json
{"content": "response chunk 1"}
{"content": "response chunk 2"}
```

## No Dependencies on Existing Codebase

This app is completely standalone and has zero imports from:
- `nothing-gets-out/`
- `moneypenny-agent/` (except via HTTP)
- `tutorials/`
- `hikari-slides/`

All logic is contained within `app.py`.

## Troubleshooting

### "Cannot connect to endpoint"
- Make sure Moneypenny Agent is running on `http://localhost:8600`
- Check the endpoint URL in `.env` matches your setup

### "Request timeout"
- Increase `REQUEST_TIMEOUT` in `.env` if responses take longer
- Check if the agent is slow to respond

### Chat history disappears when page reloads
- Streamlit session state is per-session; use the sidebar "Clear Chat History" button to explicitly clear
- Refresh the browser to start a new session

## Development

To add features:
1. Modify `app.py` directly
2. Streamlit hot-reloads on save (if running with `streamlit run`)
3. No build step required
