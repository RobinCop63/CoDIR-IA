import os
import anthropic

try:
    # Versions récentes du SDK
    from anthropic.types import TextBlock
except Exception:  # pragma: no cover
    TextBlock = None  # fallback si pas dispo


def _extract_text_from_response(response) -> str:
    """
    Extrait proprement le texte de la réponse Anthropic.
    Compatible:
      - content = liste d'objets (ex: TextBlock)
      - content = liste de dicts {"type": "...", "text": "..."}
    """
    parts = []
    content = getattr(response, "content", []) or []
    for part in content:
        # Objet TextBlock (ou assimilé)
        if TextBlock and isinstance(part, TextBlock):
            if getattr(part, "type", None) == "text":
                parts.append(getattr(part, "text", ""))
            continue

        # Objet avec attributs .type/.text
        if hasattr(part, "type") and getattr(part, "type") == "text":
            parts.append(getattr(part, "text", ""))
            continue

        # Dict classique
        if isinstance(part, dict):
            if part.get("type") == "text":
                parts.append(part.get("text", ""))

        # String brute (cas rare)
        if isinstance(part, str):
            parts.append(part)

    return "".join(parts).strip()


def _extract_usage(response):
    """
    Essaie de récupérer les compteurs de tokens si fournis par le SDK.
    Retourne un petit dict stable.
    """
    usage = getattr(response, "usage", None)
    if not usage:
        return {}
    out = {}
    # Selon les versions du SDK, usage peut avoir ces attributs:
    for k in [
        "input_tokens", "output_tokens", "cache_creation_input_tokens",
        "cache_read_input_tokens", "total_tokens"
    ]:
        v = getattr(usage, k, None)
        if v is not None:
            out[k] = int(v)
    return out


def call_claude(
    prompt: str,
    system: str = "",
    model: str = None,
    temperature: float = 0.2,
    max_tokens: int = 1024,
):
    """
    Appelle Claude (Anthropic) avec content-blocks.
    RENVOIE UN DICT pour rester compatible avec codir_engine.py:
      {
        "output": <str>,
        "model": <str>,
        "provider": "anthropic",
        "tokens": {...},
        "raw": <response object>
      }
    """

    # Sélection modèle
    m = model or os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")

    # Clé API
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or len(api_key) < 20:
        raise RuntimeError("❌ Clé Anthropic introuvable ou invalide. Vérifie .env et load_dotenv(override=True).")

    client = anthropic.Anthropic(api_key=api_key)

    # Content-blocks pour l'API
    user_blocks = [{"type": "text", "text": prompt}]

    # On n'ajoute 'system' QUE s'il est fourni (et en liste de blocs)
    kwargs = {}
    if system and system.strip():
        kwargs["system"] = [{"type": "text", "text": system}]

    # Appel API
    response = client.messages.create(
        model=m,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": user_blocks}],
        **kwargs,
    )

    text = _extract_text_from_response(response)
    usage = _extract_usage(response)

    return {
        "output": text,
        "model": m,
        "provider": "anthropic",
        "tokens": usage,
        "raw": response,  # utile pour debug si besoin
    }
