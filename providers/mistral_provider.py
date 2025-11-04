import os
from mistralai import Mistral

def call_mistral(prompt: str, system: str = "", model: str = None, temperature: float=0.4, max_tokens: int=1500):
    client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))
    m = model or os.getenv("MISTRAL_MODEL","mistral-large-latest")
    messages = []
    if system:
        messages.append({"role":"system","content":system})
    messages.append({"role":"user","content":prompt})
    resp = client.chat.complete(model=m, messages=messages, temperature=temperature, max_tokens=max_tokens)
    text = resp.choices[0].message.content
    return {"provider":"mistral", "model": m, "output": text}
