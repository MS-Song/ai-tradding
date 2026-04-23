import os
import requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")
url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"

response = requests.get(url)
if response.status_code == 200:
    models = response.json()
    for m in models.get('models', []):
        print(m['name'])
else:
    print(f"Error: {response.status_code} - {response.text}")
