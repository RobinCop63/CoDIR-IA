import os
import re
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


_NO_SAMPLING_PARAMS50 = re.compile(r"claude-(?:opus-4-[7-9]|opus-[5-9]|sonnet-[5-9]|haiku-[5-9]|fable|mythos)")


def _is_sonnet_5_5(model: str) -> bool:
    return str(model or "").lower().startswith("claude-sonnet-5-5")


def _sampling_kwargs(model: str, temperature) -> dict:
    """Paramètres d'échantillonnage admis pour ce modèle et ce SDK (vide pour Claude 4.7 et suivants)."""
    if temperature is None or _NO_SAMPLING_PARAMS50.search(str(model or "").lower()):
        return {}
    try:
        major = int(str(getattr(anthropic, "__version__", "0")).split(".")[0])
    except Exception:
        major = 0
    return {} if major >= 1 else {"temperature": temperature}


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
    m = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")   # v62.13.9.4.50 — Sonnet 4.5 retiré le 24/11/2026
    try:   # une variable ou un réglage resté sur un Sonnet retiré est migré (même règle que les réglages)
        from utils.settings_store import migrate_model_id as _mmi50
        m = _mmi50("anthropic", m)
    except Exception:
        pass

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
    # v62.13.9.4.50 — temperature, top_p et top_k renvoient une erreur 400 sur Claude Opus 4.7 et les modèles suivants
    # quand ils portent une valeur non par défaut (documentation Anthropic, « API parameter deprecations ») ; le SDK
    # Python 1.0 et suivants ne les accepte plus. Ils ne sont transmis qu'aux modèles antérieurs, avec un SDK qui les
    # connaît.
    kwargs.update(_sampling_kwargs(m, temperature))
    # Claude Sonnet 5.5 : réflexion adaptative active par défaut ; CoDIR IA garde le comportement de Sonnet 4.5 (sans
    # réflexion anticipée) — réglage le plus bas documenté pour ce modèle
    # 9.4.59 — « qualité d'abord » (dirigeant, 10/10/2026) : la réflexion adaptative de Sonnet 5.5 (active par défaut)
    # est laissée active ; CLAUDE_THINKING_MODE=between_tools rétablit l'ancien réglage minimal.
    _tm59 = (os.getenv("CLAUDE_THINKING_MODE") or "").strip()
    if _is_sonnet_5_5(m) and _tm59:
        kwargs.setdefault("thinking", {"type": _tm59})
    # 9.4.59 — recette 9.4.58 (séances 1 et 2) : avec un plafond de sortie de 32 000 jetons, la bibliothèque Anthropic
    # refusait l'appel (« Streaming is required for operations that may take longer than 10 minutes ») et la Stratégie
    # partait sur un modèle de repli. Les appels passent en FLUX CONTINU ; la réponse finale est la même que
    # messages.create (même objet Message : texte, usage, motif d'arrêt).
    _req59 = dict(model=m, max_tokens=max_tokens, messages=[{"role": "user", "content": user_blocks}], **kwargs)
    try:
        with client.messages.stream(**_req59) as _st59:
            response = _st59.get_final_message()
    except AttributeError:
        response = client.messages.create(**_req59)          # bibliothèque trop ancienne pour le flux continu

    text = _extract_text_from_response(response)
    usage = _extract_usage(response)

    _sr40 = str(getattr(response, "stop_reason", "") or "")   # v62.13.9.4.40 — motif d'arrêt
    return {
        "stop_reason": _sr40,
        "truncated": _sr40 == "max_tokens",
        "output": text,
        "model": m,
        "provider": "anthropic",
        "tokens": usage,
        "raw": response,  # utile pour debug si besoin
    }
