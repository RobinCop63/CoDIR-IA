import os
import google.generativeai as genai

def call_gemini(prompt: str, system: str = "", model: str = None, temperature: float=0.4, max_tokens: int=1500):
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    m = genai.GenerativeModel(model or os.getenv("GOOGLE_MODEL","gemini-2.5-flash"),
                              system_instruction=system or None)
    resp = m.generate_content(prompt, generation_config={"temperature": temperature})
    text = getattr(resp, "text", "") or ""
    return {"provider":"gemini", "model": getattr(m, "model_name", model), "output": text}
