# b1510fc4-f5f2-415e-8b1e-5183f89a09e3

from openai import OpenAI

client = OpenAI(
    base_url = "https://api.scaleway.ai/6e7ed3e0-900b-4121-a6f9-d14f736f811c/v1",
    api_key = "b1510fc4-f5f2-415e-8b1e-5183f89a09e3" # Replace SCW_SECRET_KEY with your IAM API key
)

response = client.chat.completions.create(
  #model="qwen3.5-397b-a17b",
  model="devstral-2-123b-instruct-2512",
  messages=[
    { "role": "system", "content": "You are a helpful assistant" },
    { "role": "user", "content": "What is LangChain" },
  ],
  max_tokens=2048,
  temperature=0.6,
  top_p=0.95,
  presence_penalty=0,
  stream=False,
  response_format={ "type": "text" }
)

print(response.choices[0].message.content)
print(f"Input tokens: {response.usage.prompt_tokens}")
print(f"Output tokens: {response.usage.completion_tokens}")