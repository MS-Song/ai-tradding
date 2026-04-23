import os
import requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GROQ_API_KEY")
model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
url = "https://api.groq.com/openai/v1/chat/completions"

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}
payload = {
    "model": model,
    "messages": [{"role": "user", "content": "Hello"}]
}

response = requests.post(url, headers=headers, json=payload)
if response.status_code == 200:
    print("Groq is working!")
    print(response.json()['choices'][0]['message']['content'])
else:
    print(f"Groq Error: {response.status_code} - {response.text}")
