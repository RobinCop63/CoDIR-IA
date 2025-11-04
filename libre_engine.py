import os
from typing import Dict, Any, List
from dotenv import load_dotenv
from providers.openai_provider import call_openai
from providers.gemini_provider import call_gemini
from providers.claude_provider import call_claude
from providers.mistral_provider import call_mistral

load_dotenv(override=True)

PROVIDERS = {
    "OpenAI": call_openai,
    "Gemini": call_gemini,
    "Claude": call_claude,
    "Mistral": call_mistral,
}

def run_free_mode(prompt: str, system: str = "", providers: List[str] = None,
                  temperature: float=0.4, max_tokens: int=1500) -> Dict[str, Any]:
    providers = providers or list(PROVIDERS.keys())
    results = {}
    for p in providers:
        fn = PROVIDERS.get(p)
        if not fn: 
            continue
        try:
            out = fn(prompt, system=system, temperature=temperature, max_tokens=max_tokens)
            results[p] = out.get("output","")
        except Exception as e:
            results[p] = f"[Erreur {p}] {e}"
    return results
