import os
from google import genai
from google.genai import types

def _pick_api_key() -> str | None:
    # Google GenAI SDK supports GEMINI_API_KEY or GOOGLE_API_KEY (GOOGLE_API_KEY takes precedence if both set).
    return os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

def call_gemini(
    prompt: str,
    system: str = "",
    model: str | None = None,
    temperature: float = 0.4,
    max_tokens: int = 1500,
):
    api_key = _pick_api_key()
    # If api_key is None, the SDK will still try to pick it up from env vars (GEMINI_API_KEY/GOOGLE_API_KEY).
    client = genai.Client(api_key=api_key) if api_key else genai.Client()

    # v62.13.9.4.50 — la famille 2.5 n'est plus ouverte aux nouveaux comptes (404 « no longer available to new
    # users ») ; modèle stable (GA) de la génération 3 par défaut
    model_id = model or os.getenv("GOOGLE_MODEL") or os.getenv("GEMINI_MODEL") or "gemini-3.6-flash"
    _gen3 = str(model_id).lower().startswith("gemini-3")
    _cfg = {"system_instruction": system or None, "max_output_tokens": max_tokens}
    if not _gen3:
        _cfg["temperature"] = temperature      # génération 3 : température laissée à sa valeur par défaut (Google)
    try:
        if _gen3 and hasattr(types, "ThinkingConfig"):
            # 9.4.58 — qualité d'abord : réflexion « high » (était « low ») ; repli sans réflexion si refusée
            _cfg["thinking_config"] = types.ThinkingConfig(thinking_level=(os.getenv("GEMINI_THINKING_LEVEL") or "high"))
        config = types.GenerateContentConfig(**_cfg)
    except Exception:
        _cfg.pop("thinking_config", None)
        config = types.GenerateContentConfig(**_cfg)
    # v62.13.9.4.50 — recette du 01/10 : « 503 UNAVAILABLE — model currently experiencing high demand » ; deux
    # nouveaux essais espacés sur une surcharge passagère, jamais sur une erreur de requête
    import time as _t50
    for _try50 in range(3):
        try:
            resp = client.models.generate_content(model=model_id, contents=prompt, config=config)
            break
        except Exception as _e50:
            _m50 = str(_e50)
            if _try50 < 2 and any(k in _m50 for k in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "overloaded")):
                _t50.sleep((4, 12)[_try50])
                continue
            raise

    text = getattr(resp, "text", "") or ""
    try:   # v62.13.9.4.40 — motif d'arrêt
        _fr40 = str(getattr(resp.candidates[0], "finish_reason", "") or "")
    except Exception:
        _fr40 = ""
    return {"provider": "gemini", "model": model_id, "output": text,
            "stop_reason": _fr40, "truncated": "MAX_TOKENS" in _fr40.upper()}
