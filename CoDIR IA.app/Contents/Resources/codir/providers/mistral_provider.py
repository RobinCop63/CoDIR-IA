import os
from typing import Optional, Dict, Any

# ─────────────────────────────────────────────────────────────────────────────
# Import SDK Mistral
# Structure du package mistralai a changé entre versions :
#   v1.x (≤1.12.x) : from mistralai import Mistral
#   v2.x (≥2.0.0)  : from mistralai.client import Mistral  (ou .client.sdk)
# La branche try/except couvre les deux, sans verrou de version dans requirements.
# ─────────────────────────────────────────────────────────────────────────────
try:
    from mistralai import Mistral                  # v1.x — chemin canonique
except (ImportError, AttributeError):
    try:
        from mistralai.client import Mistral       # v2.x — chemin déplacé
    except (ImportError, AttributeError) as e:
        raise ImportError(
            "Impossible d'importer Mistral depuis le package 'mistralai'. "
            "Vérifiez l'installation : pip install mistralai>=1.2.0"
        ) from e


def _extract_text(content) -> str:
    """
    Extrait le texte de réponse de manière robuste.
    Gère :
      - str brute (v1.x standard)
      - liste de content-blocks [{"type": "text", "text": "..."}] (v2.x possible)
      - objet avec attribut .text
    """
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif hasattr(block, "text"):
                parts.append(str(block.text))
        return "".join(parts).strip()

    if hasattr(content, "text"):
        return str(content.text)

    return str(content) if content is not None else ""


def call_mistral(
    prompt: str,
    system: str = "",
    model: Optional[str] = None,
    temperature: float = 0.4,
    max_tokens: int = 1500,
) -> Dict[str, Any]:
    """
    Appelle l'API Mistral et renvoie un dict normalisé :
      { "provider": "mistral", "model": str, "output": str }
    """
    api_key = os.getenv("MISTRAL_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "\u274C Clé API Mistral introuvable. "
            "Configurez MISTRAL_API_KEY dans l'écran Configuration."
        )

    client = Mistral(api_key=api_key)
    m = model or os.getenv("MISTRAL_MODEL", "mistral-large-latest")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    resp = client.chat.complete(
        model=m,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    raw_content = resp.choices[0].message.content
    text = _extract_text(raw_content)

    return {"provider": "mistral", "model": m, "output": text}
