#!/bin/bash
cd /Users/Imre/PythonProjects/python-for-ai/invoice-file-filter
uv run python run_api.py &
PID=$!
echo "Started with PID: $PID"
wait $PID
