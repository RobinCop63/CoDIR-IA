"""
Anthropic provider for CoDIR IA.

Ce module centralise tous les appels à l'API Anthropic (Claude).
Il utilise par défaut le modèle recommandé : ``claude-3-5-sonnet-latest``.

À configurer dans votre fichier .env :
    ANTHROPIC_API_KEY=...
    ANTHROPIC_MODEL=claude-sonnet-4-5   # (optionnel, valeur par défaut)
"""

import os
from typing import Optional

try:
    import anthropic
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Le package 'anthropic' n'est pas installé. "
        "Installe-le avec : pip install anthropic"
    ) from exc


# --- Configuration -------------------------------------------------------

ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY")
DEFAULT_ANTHROPIC_MODEL: str = os.getenv(
    "ANTHROPIC_MODEL",
    "claude-sonnet-4-5",  # ✅ modèle recommandé fin 2025
)

if not ANTHROPIC_API_KEY:
    # On laisse remonter une erreur claire au démarrage si la clé manque
    raise RuntimeError(
        "ANTHROPIC_API_KEY est manquant dans l'environnement (.env).\n"
        "Ajoute ta clé dans le fichier .env puis relance CoDIR IA."
    )

# Client global réutilisé pour éviter des reconnections inutiles
_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


class AnthropicProvider:
    """Client simple pour appeler Claude depuis CoDIR IA.

    Cette classe est volontairement minimale pour rester compatible
    avec la plupart des architectures utilisées jusqu'ici dans CoDIR IA.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> None:
        self.model = model or DEFAULT_ANTHROPIC_MODEL
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.client = _client

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Appelle Claude et renvoie le texte de la réponse.

        Parameters
        ----------
        system_prompt : str
            Contexte / rôle donné à Claude (instructions système).
        user_prompt : str
            Message utilisateur (question ou demande).
        temperature : float, optional
            Niveau de créativité. Si None, utilise la valeur par défaut.
        max_tokens : int, optional
            Nombre max de tokens générés. Si None, utilise la valeur par défaut.
        """
        temperature = self.temperature if temperature is None else temperature
        max_tokens = self.max_tokens if max_tokens is None else max_tokens

        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt or "",
            messages=[
                {
                    "role": "user",
                    "content": user_prompt,
                }
            ],
        )

        # Claude renvoie une liste de "content blocks" ; on prend le premier texte.
        # Si jamais la structure change, on essaie de rester robuste.
        parts = getattr(response, "content", None) or []
        if not parts:
            return ""

        first = parts[0]
        # Nouveau SDK Anthropic : chaque block a un attribut .text
        text = getattr(first, "text", None)
        if isinstance(text, str):
            return text

        # Fallback très défensif si jamais la structure est différente
        # (par exemple un dict ou autre)
        return str(first)


def call_anthropic(
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> str:
    """Fonction utilitaire compatible avec les anciens appels.

    Exemple d'utilisation dans ton code :
        from providers.anthropic_provider import call_anthropic

        reponse = call_anthropic(system_prompt, user_prompt)
    """
    provider = AnthropicProvider(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return provider.generate(system_prompt, user_prompt)


__all__ = ["AnthropicProvider", "call_anthropic"]
