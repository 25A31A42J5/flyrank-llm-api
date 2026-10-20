import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    base_url=os.getenv("LLM_BASE_URL"),
    api_key=os.getenv("LLM_API_KEY"),
)

response = client.chat.completions.create(
    model=os.getenv("LLM_MODEL"),
    messages=[
        {
            "role": "user",
            "content": 'Reply with exactly this JSON: {"ready": true}',
        }
    ],
    temperature=0,
)

print(response.choices[0].message.content)
