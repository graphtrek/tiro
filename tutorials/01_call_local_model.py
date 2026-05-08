from openai import OpenAI
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Create a client with Ollama's base URL and API key
# Get credentials from environment variables
base_url = os.environ["OLLAMA_BASE_URL"]
api_key = os.environ["OLLAMA_API_KEY"]

# Create a client with the base URL and API key for the OpenAI client
client = OpenAI(base_url=base_url, api_key=api_key)

# Create a chat completion
completion = client.chat.completions.create(
    model="gemma4:e2b",
    messages=[
        {"role": "system", "content": "You are my helpful assistant."},
        {"role": "user", "content": "How are you today?"},
    ],
    temperature=0.7,
)

# Print the chatbot's response
print(completion.choices[0].message.content)