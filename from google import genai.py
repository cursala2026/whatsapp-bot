from google import genai
import os

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

response = client.models.generate_content(
    model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite"),
    contents="Respondé en una sola línea: hola desde Gemini"
)

print(response.text)