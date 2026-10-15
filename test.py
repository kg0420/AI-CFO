from google import genai
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.environ.get("GEMINI_API_KEY")
if api_key:
    client = genai.Client(api_key=api_key)
    for m in client.models.list():
        print(m.name)
else:
    print("GEMINI_API_KEY not set.")