import os
from google import genai
from google.genai import types

def _pick_api_key() -> str | None:
    # Google GenAI SDK supports GEMINI_API_KEY or GOOGLE_API_KEY (GOOGLE_API_KEY takes precedence if both set).
    return os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

def call_gemini(
    prompt: str,
    system: str = "",
    model: str | None = None,
    temperature: float = 0.4,
    max_tokens: int = 1500,
):
    api_key = _pick_api_key()
    # If api_key is None, the SDK will still try to pick it up from env vars (GEMINI_API_KEY/GOOGLE_API_KEY).
    client = genai.Client(api_key=api_key) if api_key else genai.Client()

    model_id = model or os.getenv("GOOGLE_MODEL") or os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"

    resp = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system or None,
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    )

    text = getattr(resp, "text", "") or ""
    return {"provider": "gemini", "model": model_id, "output": text}
