import os
import sys
from typing import Dict, Any, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from dotenv import load_dotenv
from providers.openai_provider import call_openai
from providers.gemini_provider import call_gemini
from providers.claude_provider import call_claude
from providers.mistral_provider import call_mistral

try:
    from providers.perplexity_provider import call_perplexity
except Exception:
    call_perplexity = None

try:
    from providers.grok_provider import call_grok
except Exception:
    call_grok = None

from utils.settings_store import load_settings
from utils.secrets_store import apply_secrets_to_env, load_secrets

load_dotenv(override=True)

PROVIDERS = {
    "OpenAI":     ("openai",      call_openai),
    "Gemini":     ("google",      call_gemini),
    "Claude":     ("anthropic",   call_claude),
    "Mistral":    ("mistral",     call_mistral),
    "Perplexity": ("perplexity",  call_perplexity),
    "Grok":       ("grok",        call_grok),
}

def _has_key(tag: str) -> bool:
    if tag == "openai":
        return bool(os.getenv("OPENAI_API_KEY", "").strip())
    if tag == "anthropic":
        return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())
    if tag == "google":
        return bool(os.getenv("GOOGLE_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY", "").strip())
    if tag == "mistral":
        return bool(os.getenv("MISTRAL_API_KEY", "").strip())
    if tag == "perplexity":
        return bool(os.getenv("PERPLEXITY_API_KEY", "").strip())
    if tag == "grok":
        return bool(os.getenv("GROK_API_KEY", "").strip() or os.getenv("XAI_API_KEY", "").strip())
    return False

def run_free_mode(
    prompt: str,
    system: str = "",
    providers: Optional[List[str]] = None,
    temperature: float = 0.4,
    max_tokens: int = 1500,
) -> Dict[str, Any]:
    apply_secrets_to_env(load_secrets(), override=False)
    settings = load_settings()

    providers = providers or list(PROVIDERS.keys())
    results: Dict[str, Any] = {}
    for p in providers:
        tag_fn = PROVIDERS.get(p)
        if not tag_fn:
            continue
        tag, fn = tag_fn
        if not fn:
            results[p] = "[Provider non disponible (import échoué)]"
            continue
        if not _has_key(tag):
            results[p] = "[Clé API manquante — configurez-la dans l'écran Configuration]"
            continue
        try:
            if tag == "openai":
                model_id = settings.openai_model_id
            elif tag == "google":
                model_id = settings.google_model_id
            elif tag == "anthropic":
                model_id = settings.anthropic_model_id
            elif tag == "mistral":
                model_id = settings.mistral_model_id
            elif tag == "perplexity":
                model_id = settings.perplexity_model_id
            elif tag == "grok":
                model_id = settings.grok_model_id
            else:
                model_id = ""
            out = fn(prompt, system=system, temperature=temperature, max_tokens=max_tokens, model=model_id)
            results[p] = out.get("output", "") if isinstance(out, dict) else str(out)
        except Exception as e:
            results[p] = f"[Erreur {p}] {e}"
    return results
