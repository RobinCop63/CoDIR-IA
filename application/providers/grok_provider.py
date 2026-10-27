"""
Grok / xAI provider (API OpenAI-compatible).
Base URL : https://api.x.ai/v1
Clé env  : GROK_API_KEY
Modèle   : grok-4.3 (défaut, v62.13.9.4.50 — famille Grok 3 retirée de l'API le 15/05/2026, remplaçant désigné
           par xAI : grok-4.3).
"""
from __future__ import annotations
import os
import time
from typing import Any, Dict


DEFAULT_MODEL = "grok-4.3"
_RETIRED_GROK = ("grok-3", "grok-2", "grok-4-0709", "grok-4-fast", "grok-4-1-fast", "grok-code-fast")


def call_grok(
    prompt: str,
    system: str = "",
    temperature: float = 0.4,
    max_tokens: int = 2000,
    model: str = "",
) -> Dict[str, Any]:
    try:
        from openai import OpenAI
    except ImportError:
        return {
            "output": "[Grok ERROR] package openai non installé",
            "error": True,
            "model": model or DEFAULT_MODEL,
            "tokens": {},
            "duration_s": 0.0,
        }

    api_key = (os.getenv("GROK_API_KEY", "") or os.getenv("XAI_API_KEY", "")).strip()
    if not api_key:
        return {
            "output": "[Grok ERROR] GROK_API_KEY manquante",
            "error": True,
            "model": model or DEFAULT_MODEL,
            "tokens": {},
            "duration_s": 0.0,
        }

    _model = (model or DEFAULT_MODEL).strip()
    if _model.lower().startswith(_RETIRED_GROK):
        _model = DEFAULT_MODEL                      # migration des modèles retirés par xAI
    client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    t0 = time.time()
    try:
        _params = {"model": _model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens,
                   "reasoning_effort": (os.getenv("GROK_REASONING_EFFORT") or "medium")}   # 9.4.58 — était « low »
        try:
            response = client.chat.completions.create(**_params)
        except Exception as _e50:
            _m50 = str(_e50)
            for _k in ("reasoning_effort", "temperature"):
                if _k in _m50:
                    _params.pop(_k, None)
            if len(_params) == 5:
                raise
            response = client.chat.completions.create(**_params)
        message_content = response.choices[0].message.content
        if isinstance(message_content, list):
            output = "".join(
                part.get("text", "") if isinstance(part, dict) else getattr(part, "text", str(part))
                for part in message_content
            ).strip()
        else:
            output = (message_content or "").strip()
        tokens: Dict[str, Any] = {}
        if response.usage:
            tokens = {
                "input": response.usage.prompt_tokens,
                "output": response.usage.completion_tokens,
            }
        return {
            "provider": "grok",
            "output": output,
            "model": _model,
            "tokens": tokens,
            "duration_s": round(time.time() - t0, 3),
        }
    except Exception as e:
        return {
            "provider": "grok",
            "output": f"[Grok ERROR] {e}",
            "error": True,
            "model": _model,
            "tokens": {},
            "duration_s": round(time.time() - t0, 3),
        }
