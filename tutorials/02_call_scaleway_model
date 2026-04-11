from openai import OpenAI
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Create a client with Scaleway's base URL and API key
# Get credentials from environment variables
base_url = os.environ["SCALEWAY_BASE_URL"]
api_key = os.environ["SCALEWAY_API_KEY"]

client = OpenAI(base_url=base_url, api_key=api_key)

# Create a chat completion using a Scaleway model
completion = client.chat.completions.create(
    model="mistral-small-3.2-24b-instruct-2506",  # or "qwen3-coder-30b-a3b-instruct"
    messages=[
        {"role": "system", "content": "You are my helpful assistant."},
        {"role": "user", "content": "How are you today?"},
    ],
    temperature=0.7,
)

# Print the chatbot's response
print(completion.choices[0].message.content)
