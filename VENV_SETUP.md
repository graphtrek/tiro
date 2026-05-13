# Unified Python Environment Setup

This workspace uses a single Python virtual environment for all projects.

## One-Time Setup

```bash
cd /Users/Imre/PythonProjects/python-for-ai

# Create unified venv
python3 -m venv .venv

# Activate it
source .venv/bin/activate

# Install all dependencies
pip install -r requirements.txt
```

## Daily Usage

### Always activate the root venv first:
```bash
cd /Users/Imre/PythonProjects/python-for-ai
source .venv/bin/activate
```

### Run moneypenny-agent (backend)
```bash
cd moneypenny-agent
python run.py
# Or with uvicorn directly:
uvicorn main:app --reload --port 8600
```

### Run streamlit-chat-client (frontend)
```bash
cd streamlit-chat-client
streamlit run app.py
```

## Removing Old .venv Folders

You can safely remove the old individual .venv folders:
```bash
rm -rf moneypenny-agent/.venv
rm -rf streamlit-chat-client/.venv
rm -rf nothing-gets-out/.venv
rm -rf hikari-slides/.venv
rm -rf tutorials/.venv
```

They'll be replaced by the single `.venv` at the workspace root.

## Verify Setup

After activation, verify dependencies are installed:
```bash
pip list | grep -E "streamlit|fastapi|chromadb|pandas"
```

All packages should be listed.
