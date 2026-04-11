# Tutorials

Getting started with AI models and the OpenAI SDK.

---

## Overview

This directory contains practical tutorials demonstrating how to call and interact with different AI models using the OpenAI SDK.

---

## Available Tutorials

### 01. Local Model via LM Studio

**File:** `01_call_local_lmstudio_model`

Learn how to run a local LLM using LM Studio and interact with it via the OpenAI SDK.

- **Setup:** Run LM Studio locally on port `1234`
- **Model:** Google Gemma 3 (4B) or similar
- **Key Concepts:**
  - OpenAI client with custom base URL
  - Local model inference
  - No API key required (local execution)

**Quick Start:**
```bash
# 1. Install LM Studio and load a model on port 1234
# 2. Run the tutorial
python 01_call_local_lmstudio_model
```

---

### 02. Cloud Model via Scaleway

**File:** `02_call_scaleway_model`

Learn how to call a cloud-hosted LLM using Scaleway Inference API and the OpenAI SDK.

- **Setup:** Scaleway account with API credentials
- **Models:** Mistral Small 3.2, Qwen3 Coder, or others
- **Key Concepts:**
  - OpenAI client with cloud provider base URL
  - API key authentication
  - Environment variable configuration
  - Production-ready inference

**Quick Start:**
```bash
# 1. Set up environment variables in .env
#    SCALEWAY_BASE_URL=<your_scaleway_endpoint>
#    SCALEWAY_API_KEY=<your_api_key>

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the tutorial
python 02_call_scaleway_model
```

---

## Requirements

```
openai==2.30.0
python-dotenv>=1.0.0
```

Install with:
```bash
pip install -r requirements.txt
```

---

## Environment Setup

For cloud-based tutorials (like Scaleway), create a `.env` file in this directory:

```env
SCALEWAY_BASE_URL=https://api.scaleway.com/inference/v1
SCALEWAY_API_KEY=your_api_key_here
```

**Note:** Never commit `.env` files to version control. They contain sensitive information.

---

## Next Steps

- Explore model parameters (temperature, top_p, etc.)
- Implement error handling and retry logic
- Build multi-turn conversations
- Integrate with the main `nothing-gets-out` project
