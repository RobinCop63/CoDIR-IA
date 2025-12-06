
import os
import sys
from typing import Dict, Any, List

from dotenv import load_dotenv

# S'assurer que le dossier courant est dans le PYTHONPATH
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# Import des providers
from providers.openai_provider import call_openai
from providers.gemini_provider import call_gemini
from providers.claude_provider import call_claude
from providers.mistral_provider import call_mistral

# Chargement des variables d'environnement (.env)
load_dotenv(override=True)

# Mapping des providers utilisables en Mode Libre.
# Les clés sont alignées avec les valeurs proposées dans app.py :
#   - "openai"
#   - "gemini"
#   - "anthropic" (Claude)
#   - "mistral"
PROVIDERS: Dict[str, Any] = {
    "openai": call_openai,
    "gemini": call_gemini,
    "anthropic": call_claude,
    "mistral": call_mistral,
}


def _normalize_provider_name(name: str) -> str:
    """Normalise le nom du provider (casse, alias "claude" -> "anthropic")."""
    if not name:
        return ""
    n = name.strip().lower()
    if n == "claude":
        return "anthropic"
    return n


def run_libre_session(
    provider: str,
    prompt: str,
    system: str = "",
    temperature: float = 0.4,
    max_tokens: int = 1500,
) -> str:
    """Appelé par app.py en Mode Libre (1 IA au choix).

    Retourne directement le texte de la réponse (string) ou un message d'erreur lisible.
    """
    p = _normalize_provider_name(provider)
    fn = PROVIDERS.get(p)

    if not fn:
        return f"[Erreur] Provider inconnu : {provider}"

    try:
        out = fn(
            prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return (out.get("output", "") or "").strip()
    except Exception as e:  # pragma: no cover - protection runtime
        return f"[Erreur {provider}] {e}"


def run_free_mode(
    prompt: str,
    system: str = "",
    providers: List[str] | None = None,
    temperature: float = 0.4,
    max_tokens: int = 1500,
) -> Dict[str, Any]:
    """Mode "multi-providers" (non utilisé actuellement par app.py).

    Retourne un dict {provider_slug: texte_ou_message_d_erreur}.
    """
    providers = providers or list(PROVIDERS.keys())
    results: Dict[str, Any] = {}

    for p in providers:
        norm = _normalize_provider_name(p)
        fn = PROVIDERS.get(norm)
        if not fn:
            results[p] = f"[Erreur] Provider inconnu : {p}"
            continue

        try:
            out = fn(
                prompt,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            results[p] = (out.get("output", "") or "").strip()
        except Exception as e:  # pragma: no cover
            results[p] = f"[Erreur {p}] {e}"

    return results
