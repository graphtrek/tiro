#!/usr/bin/env bash
# Devcontainer setup: everything the agents need to build and test python-for-ai.
set -euo pipefail

echo "Installing system dependencies (OCR + Chromium + mc)..."
sudo apt-get update
sudo apt-get install -y chromium poppler-utils tesseract-ocr tesseract-ocr-hun tesseract-ocr-eng mc

echo "Installing uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

echo "Syncing each sub-project's isolated .venv..."
for pyproject in */pyproject.toml; do
  dir="$(dirname "$pyproject")"
  echo "  -> $dir"
  if [ "$dir" = "attachment-downloader" ]; then
    (cd "$dir" && uv sync --extra gmail)
  else
    (cd "$dir" && uv sync)
  fi
done

echo "Installing OpenCode and agent-browser..."
# Chrome for Testing has no Linux ARM64 builds, so Chromium is installed via
# apt above (alongside the OCR deps); agent-browser finds it via
# AGENT_BROWSER_EXECUTABLE_PATH (containerEnv).
npm install -g opencode-ai agent-browser

echo "Adding the agent-browser skill for OpenCode..."
npx -y skills add vercel-labs/agent-browser -a opencode -y

echo "Verifying the installs..."
uv --version
opencode --version
agent-browser doctor
mc --version | head -1

echo "Setup complete."
