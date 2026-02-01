import os
from typing import Optional, Dict, Any
from openai import OpenAI

def call_openai(prompt: str, system: Optional[str]=None, model: Optional[str]=None,
                temperature: float=0.4, max_tokens: int=1500) -> Dict[str, Any]:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    model = model or os.getenv("OPENAI_MODEL","gpt-4o")
    messages = []
    if system:
        messages.append({"role":"system","content":system})
    messages.append({"role":"user","content":prompt})
    resp = client.chat.completions.create(model=model, messages=messages,
                                          temperature=temperature, max_tokens=max_tokens)
    text = resp.choices[0].message.content
    return {"provider":"openai", "model": model, "output": text}
