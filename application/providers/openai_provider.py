import os
from typing import Optional, Dict, Any
from openai import OpenAI


def _model_prefers_max_completion_tokens(model: str) -> bool:
    """Return True if the model likely requires `max_completion_tokens`.

    OpenAI has model families (notably some reasoning-capable models) that do not
    accept `max_tokens` and instead expect `max_completion_tokens`. When we hit
    that, we switch automatically.
    """
    m = (model or "").strip().lower()
    return m.startswith("o") or m.startswith("gpt-5")

def call_openai(prompt: str, system: Optional[str]=None, model: Optional[str]=None,
                temperature: float=0.4, max_tokens: int=1500) -> Dict[str, Any]:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    # v62.13.9.4.50 — gpt-4.1-mini / gpt-4o retirés de ChatGPT ; remplaçant désigné par OpenAI : gpt-5.4-mini
    model = model or os.getenv("OPENAI_MODEL", "gpt-5.4")      # 9.4.58 — qualité d'abord : modèle complet par défaut
    messages = []
    if system:
        messages.append({"role":"system","content":system})
    messages.append({"role":"user","content":prompt})
    params: Dict[str, Any] = {"model": model, "messages": messages}
    # Temperature is not supported by reasoning models (o*, gpt-5*) — skip entirely for them.
    if temperature is not None and not _model_prefers_max_completion_tokens(model):
        params["temperature"] = temperature

    # Token parameter: some models require `max_completion_tokens`.
    if _model_prefers_max_completion_tokens(model):
        params["max_completion_tokens"] = int(max_tokens)
        # v62.13.9.4.50 — modèle de raisonnement : effort « low » par défaut, pour que le budget de sortie serve la
        # réponse et non la réflexion (comportement proche de gpt-4.1-mini, qui ne réfléchissait pas)
        # 9.4.58 — « qualité d'abord » (dirigeant, 10/10/2026) : effort « medium » par défaut (était « low »)
        params["reasoning_effort"] = (os.getenv("OPENAI_REASONING_EFFORT") or "medium").strip()
    else:
        params["max_tokens"] = int(max_tokens)

    try:
        resp = client.chat.completions.create(**params)
    except Exception as e:
        msg = str(e)
        # Auto-retry if the model rejects max_tokens.
        if "Unsupported parameter" in msg and "max_tokens" in msg and "max_completion_tokens" in msg:
            params.pop("max_tokens", None)
            params["max_completion_tokens"] = int(max_tokens)
            resp = client.chat.completions.create(**params)
        # Auto-retry if the model rejects temperature (common on some reasoning models).
        elif "Unsupported" in msg and "temperature" in msg:
            params.pop("temperature", None)
            resp = client.chat.completions.create(**params)
        # v62.13.9.4.50 — modèle qui n'accepte pas reasoning_effort : nouvel essai sans
        elif "reasoning_effort" in msg:
            params.pop("reasoning_effort", None)
            resp = client.chat.completions.create(**params)
        else:
            raise
    text = resp.choices[0].message.content

    usage = None
    try:
        if getattr(resp, "usage", None) is not None:
            usage = {
                "prompt_tokens": getattr(resp.usage, "prompt_tokens", None),
                "completion_tokens": getattr(resp.usage, "completion_tokens", None),
                "total_tokens": getattr(resp.usage, "total_tokens", None),
            }
    except Exception:
        usage = None

    out: Dict[str, Any] = {"provider": "openai", "model": model, "output": text}
    # v62.13.9.4.40 — motif d'arrêt : une réponse coupée par la limite de sortie est signalée
    try:
        _fr40 = str(getattr(resp.choices[0], "finish_reason", "") or "")
        out["stop_reason"] = _fr40
        out["truncated"] = _fr40 == "length"
    except Exception:
        pass
    if usage:
        out["usage"] = usage
    return out
