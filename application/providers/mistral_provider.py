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
    m = model or os.getenv("MISTRAL_MODEL", "mistral-medium-latest")   # v62.13.9.4.50 — aligné sur le réglage par défaut

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # v62.13.9.4.50 — un 429 (limite de débit) reçoit UN nouvel essai espacé : Mistral est le repli de dernier recours,
    # il ne doit pas tomber sur une rafale passagère ; un quota épuisé reste une erreur, dite en clair dans le test
    import time as _t50
    for _try50 in range(2):
        try:
            resp = client.chat.complete(
                model=m,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            break
        except Exception as _e50:
            if _try50 == 0 and ("429" in str(_e50) or "rate" in str(_e50).lower()):
                _t50.sleep(3)
                continue
            raise

    raw_content = resp.choices[0].message.content
    text = _extract_text(raw_content)

    try:   # v62.13.9.4.40 — motif d'arrêt
        _fr40 = str(getattr(resp.choices[0], "finish_reason", "") or "")
    except Exception:
        _fr40 = ""
    return {"provider": "mistral", "model": m, "output": text, "stop_reason": _fr40, "truncated": _fr40 == "length"}
