"""
Perplexity AI provider — API Agent (v62.13.9.4.50).
Endpoint : POST https://api.perplexity.ai/v1/agent
Clé env  : PERPLEXITY_API_KEY
Modèle   : perplexity/sonar (le modèle propre de Perplexity), avec l'outil web_search.

Perplexity a mis fin au support de l'API Sonar « chat completions » le 27/09/2026 (documentation officielle,
« Migrate from Sonar to the Agent API ») : les requêtes synchrones y sont reformulées en requêtes Agent, au fil
d'un déploiement progressif. CoDIR IA appelle directement l'API Agent. Le modèle est ÉPINGLÉ sur perplexity/sonar :
un « preset » sans modèle peut être servi par un modèle tiers (OpenAI, Google…) routé par Perplexity, ce qui
changerait le flux de données documenté. Les anciens identifiants (sonar, sonar-pro, sonar-reasoning-pro,
sonar-deep-research) sont migrés vers ce modèle.
Contraintes API (état 09/2026) :
  - max_tokens >= 16 exigé par l'API (400 invalid_request sinon) — plancher appliqué ici ;
  - « sonar-reasoning » retiré de l'API le 15/12/2025 — migré vers sonar-reasoning-pro.
"""
from __future__ import annotations
import os
import time
from typing import Any, Dict


DEFAULT_MODEL = "perplexity/sonar"
AGENT_URL = "https://api.perplexity.ai/v1/agent"
_LEGACY_SONAR = {"sonar", "sonar-pro", "sonar-reasoning", "sonar-reasoning-pro", "sonar-deep-research",
                 "perplexity/sonar-pro", "perplexity/sonar-reasoning-pro"}


def call_perplexity(
    prompt: str,
    system: str = "",
    temperature: float = 0.4,
    max_tokens: int = 2000,
    model: str = "",
) -> Dict[str, Any]:
    try:
        import requests as _rq
    except ImportError:
        return {
            "output": "[Perplexity ERROR] package requests non installé",
            "error": True,
            "model": model or DEFAULT_MODEL,
            "tokens": {},
            "duration_s": 0.0,
        }

    api_key = os.getenv("PERPLEXITY_API_KEY", "").strip()
    if not api_key:
        return {
            "output": "[Perplexity ERROR] PERPLEXITY_API_KEY manquante",
            "error": True,
            "model": model or DEFAULT_MODEL,
            "tokens": {},
            "duration_s": 0.0,
        }

    _model = (model or DEFAULT_MODEL).strip()
    if _model in _LEGACY_SONAR or _model.startswith("sonar"):
        _model = DEFAULT_MODEL                      # migration des identifiants Sonar retirés
    try:
        max_tokens = max(16, int(max_tokens))
    except (TypeError, ValueError):
        max_tokens = 16
    payload: Dict[str, Any] = {
        "model": _model,
        "input": prompt,
        "tools": [{"type": "web_search"}],          # un modèle choisi explicitement doit déclarer la recherche web
        "max_output_tokens": max_tokens,
    }
    if system:
        payload["instructions"] = system
    if temperature is not None:
        payload["temperature"] = temperature        # accepté ; effet selon le modèle (documentation Perplexity)
    t0 = time.time()
    try:
        r = _rq.post(AGENT_URL, json=payload, timeout=180,
                     headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        texts, citations = [], []
        for item in data.get("output") or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "message":
                for part in item.get("content") or []:
                    if isinstance(part, dict) and part.get("type") in ("output_text", "text"):
                        texts.append(str(part.get("text") or ""))
            elif item.get("type") == "search_results":
                for res in item.get("results") or []:
                    if isinstance(res, dict) and res.get("url"):
                        citations.append(str(res["url"]))
        output = ("".join(texts) or str(data.get("output_text") or "")).strip()
        usage = data.get("usage") or {}
        tokens: Dict[str, Any] = {}
        if isinstance(usage, dict) and usage:
            tokens = {"input": usage.get("input_tokens"), "output": usage.get("output_tokens")}
        out: Dict[str, Any] = {
            "provider": "perplexity",
            "output": output,
            "model": _model,
            "model_effective": str(data.get("model") or _model),   # modèle réellement servi, consigné au diagnostic
            "citations": citations,
            "tokens": tokens,
            "duration_s": round(time.time() - t0, 3),
        }
        if not output:
            out.update({"error": True, "output": "[Perplexity ERROR] réponse vide de l'API Agent"})
        if str(data.get("status") or "") == "incomplete":
            out["truncated"] = True
        return out
    except Exception as e:
        return {
            "provider": "perplexity",
            "output": f"[Perplexity ERROR] {e}",
            "error": True,
            "model": _model,
            "tokens": {},
            "duration_s": round(time.time() - t0, 3),
        }
