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

from utils.settings_store import load_settings
from utils.secrets_store import apply_secrets_to_env, load_secrets

load_dotenv(override=True)

PROVIDERS = {
    "OpenAI": ("openai", call_openai),
    "Gemini": ("google", call_gemini),
    "Claude": ("anthropic", call_claude),
    "Mistral": ("mistral", call_mistral),
}

def _has_key(tag: str) -> bool:
    if tag == "openai":
        return bool(os.getenv("OPENAI_API_KEY","").strip())
    if tag == "anthropic":
        return bool(os.getenv("ANTHROPIC_API_KEY","").strip())
    if tag == "google":
        return bool(os.getenv("GOOGLE_API_KEY","").strip() or os.getenv("GEMINI_API_KEY","").strip())
    if tag == "mistral":
        return bool(os.getenv("MISTRAL_API_KEY","").strip())
    return False

def run_free_mode(
    prompt: str,
    system: str = "",
    providers: Optional[List[str]] = None,
    temperature: float = 0.4,
    max_tokens: int = 1500,
) -> Dict[str, Any]:
    # Ensure secrets.json keys are available in env
    apply_secrets_to_env(load_secrets(), override=False)
    settings = load_settings()

    providers = providers or list(PROVIDERS.keys())
    results: Dict[str, Any] = {}
    for p in providers:
        tag_fn = PROVIDERS.get(p)
        if not tag_fn:
            continue
        tag, fn = tag_fn
        if not _has_key(tag):
            results[p] = "[Clé API manquante — configurez-la dans l'écran Configuration]"
            continue
        try:
            model_id = (
                settings.openai_model_id if tag == "openai"
                else settings.google_model_id if tag == "google"
                else settings.anthropic_model_id if tag == "anthropic"
                else settings.mistral_model_id
            )
            out = fn(prompt, system=system, temperature=temperature, max_tokens=max_tokens, model=model_id)
            results[p] = out.get("output", "")
        except Exception as e:
            results[p] = f"[Erreur {p}] {e}"
    return results
