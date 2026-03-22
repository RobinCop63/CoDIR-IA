import os
import sys
import time
import traceback
from typing import Callable, Optional, Dict, Any, List, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from providers.claude_provider import call_claude

try:
    from providers.openai_provider import call_openai
except Exception:
    call_openai = None

try:
    from providers.gemini_provider import call_gemini
except Exception:
    call_gemini = None

try:
    from providers.mistral_provider import call_mistral
except Exception:
    call_mistral = None

from utils.settings_store import Settings, load_settings
from utils.logger import log_event


StatusCallback = Callable[[str, str], None]
# callback(step_id, human_label)


def render_brief(brief: str) -> str:
    return (brief or "").strip()


def _as_output(result):
    if isinstance(result, dict):
        for k in ("output", "text", "content", "message", "result"):
            v = result.get(k)
            if isinstance(v, str) and v.strip():
                return v
        raw = result.get("raw")
        if raw is not None:
            content = getattr(raw, "content", None)
            if content:
                parts = []
                for part in content:
                    if hasattr(part, "type") and getattr(part, "type") == "text":
                        parts.append(getattr(part, "text", ""))
                    elif isinstance(part, dict) and part.get("type") == "text":
                        parts.append(part.get("text", ""))
                    elif isinstance(part, str):
                        parts.append(part)
                if parts:
                    return "".join(parts).strip()
        return str(result)
    if isinstance(result, str):
        return result
    return str(result)


def _safe_call(tag: str, func, *args, **kwargs) -> dict:
    """Call a provider function and normalize the response.

    Returns a dict with at least: output, provider, model, tokens, raw, duration_s.
    On error, returns error=True and keeps traceback in raw.
    """
    t0 = time.time()
    try:
        resp = func(*args, **kwargs)

        # Normalize
        output = None
        model = None
        tokens = {}
        raw = resp

        if isinstance(resp, dict):
            # common fields
            for k in ("output", "text", "content", "message", "result"):
                v = resp.get(k)
                if isinstance(v, str) and v.strip():
                    output = v
                    break
            if output is None:
                output = _as_output(resp)
            model = resp.get("model") or kwargs.get("model") or os.getenv(f"{tag.upper()}_MODEL", "")
            tokens = resp.get("tokens") or {}
        else:
            output = _as_output(resp)
            model = kwargs.get("model") or os.getenv(f"{tag.upper()}_MODEL", "")

        return {
            "output": output,
            "provider": tag,
            "model": model or "",
            "tokens": tokens,
            "raw": raw,
            "duration_s": round(time.time() - t0, 3),
        }

    except Exception as e:
        tb = traceback.format_exc()
        return {
            "output": f"[{tag} ERROR] {e}",
            "provider": tag,
            "model": kwargs.get("model") or os.getenv(f"{tag.upper()}_MODEL", ""),
            "tokens": {},
            "raw": {"exception": repr(e), "traceback": tb},
            "error": True,
            "duration_s": round(time.time() - t0, 3),
        }


def _has_key(provider: str) -> bool:
    if provider == "openai":
        return bool(os.getenv("OPENAI_API_KEY", "").strip())
    if provider == "anthropic":
        return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())
    if provider in ("google", "gemini"):
        return bool(os.getenv("GOOGLE_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY", "").strip())
    if provider == "mistral":
        return bool(os.getenv("MISTRAL_API_KEY", "").strip())
    return False


def _provider_callable(provider: str):
    if provider == "openai":
        return call_openai
    if provider == "anthropic":
        return call_claude
    if provider in ("google", "gemini"):
        return call_gemini
    if provider == "mistral":
        return call_mistral
    return None


def _model_id_for(provider: str, settings: Settings) -> str:
    if provider == "openai":
        return os.getenv("OPENAI_MODEL") or settings.openai_model_id
    if provider == "anthropic":
        return os.getenv("ANTHROPIC_MODEL") or settings.anthropic_model_id
    if provider in ("google", "gemini"):
        return os.getenv("GOOGLE_MODEL") or os.getenv("GEMINI_MODEL") or settings.google_model_id
    if provider == "mistral":
        return os.getenv("MISTRAL_MODEL") or settings.mistral_model_id
    return ""


def _call_with_fallback(
    role: str,
    provider_order: List[str],
    prompt: str,
    system: str,
    temperature: float,
    max_tokens: int,
    settings: Settings,
    cb: Optional[StatusCallback] = None,
    diag_list: Optional[List[Dict[str, Any]]] = None,
    logger=None,
) -> Dict[str, Any]:
    attempts = 0
    last = None
    for provider in provider_order:
        if attempts >= settings.fallback_max_attempts:
            break
        fn = _provider_callable(provider)
        if not fn:
            continue
        if not _has_key(provider):
            continue  # skip providers without keys configured
        attempts += 1
        if cb:
            cb(role, f"{role} — appel {provider} ({attempts}/{settings.fallback_max_attempts})…")
        if logger:
            log_event(logger, "info", "codir_engine", "provider_request", role=role, provider=provider, attempt=attempts)
        model_id = _model_id_for(provider, settings)
        tag = provider if provider != "gemini" else "google"
        t0 = time.time()
        res = _safe_call(tag, fn, prompt=prompt, system=system, temperature=temperature, max_tokens=max_tokens, model=model_id)
        res["duration_s"] = round(time.time() - t0, 3)
        res["attempt"] = attempts
        res["role"] = role

        # Record diagnostics for this attempt
        if diag_list is not None:
            try:
                diag_list.append({
                    "role": role,
                    "provider": res.get("provider",""),
                    "model": res.get("model",""),
                    "status": "ERROR" if res.get("error") else "OK",
                    "attempt": attempts,
                    "duration_s": res.get("duration_s", 0),
                    "tokens": res.get("tokens") or {},
                    "error": (res.get("raw") or {}).get("exception","") if res.get("error") else "",
                })
            except Exception:
                pass

        last = res
        if not res.get("error"):
            if logger:
                log_event(logger, "info", "codir_engine", "provider_success", role=role, provider=provider, model_id=model_id)
            return res
        if logger:
            log_event(logger, "warning", "codir_engine", "provider_error", role=role, provider=provider, model_id=model_id)
    return last or {"output": f"[{role} ERROR] Aucun provider disponible (clé manquante ?)", "error": True, "provider": "none", "model": ""}


def run_codir_session(
    brief: str,
    temperature: float = 0.4,
    max_tokens: int = 2000,
    attachments_block: str = "",
    attachments_meta: Optional[Dict[str, Any]] = None,
    cb: Optional[StatusCallback] = None,
    settings: Optional[Settings] = None,
    logger=None,
) -> Dict[str, Any]:
    settings = settings or load_settings()
    brief = render_brief(brief)
    diag_list: List[Dict[str, Any]] = []

    if logger:
        log_event(logger, "info", "codir_engine", "session_started")

    # Strategy provider order: prefer Google if attachments present (context), else Anthropic first.
    if attachments_block.strip():
        strategie_order = ["google", "anthropic", "openai", "mistral"]
    else:
        strategie_order = ["anthropic", "google", "openai", "mistral"]

    # 1) STRATÉGIE
    if cb:
        cb("strategie", "Stratégie — préparation…")
    strategie_prompt = (
        "Rôle: Directeur de la stratégie.\n"
        "Objectif: proposer une stratégie claire, priorisée et exécutable.\n"
        "Contrainte: style sobre, concis, actionnable.\n"
    )
    if attachments_block.strip():
        strategie_prompt += (
            "Pièces jointes (texte extrait) — à utiliser comme contexte factuel. "
            "Ne pas inventer : si une info n'est pas dans les pièces jointes, le dire.\n"
            "---\n"
            + attachments_block.strip()
            + "\n---\n"
        )
    strategie_prompt += "Brief fourni:\n---\n" + brief

    strategie_res = _call_with_fallback(
        role="strategie",
        provider_order=strategie_order,
        prompt=strategie_prompt,
        system="Tu es un directeur de la stratégie expérimenté. Tu produis un plan clair, chiffré et priorisé.",
        temperature=temperature,
        max_tokens=max_tokens,
        settings=settings,
        diag_list=diag_list,
        cb=cb,
        logger=logger,
    )
    strategie_txt = _as_output(strategie_res)

    # Brief CoDIR: small structured brief redistributed to roles
    if cb:
        cb("brief_codir", "Stratégie — synthèse Brief CoDIR…")
    brief_codir_prompt = (
        "Tu produis un BRIEF CoDIR structuré (max 15 bullets) à partir des éléments.\n"
        "Inclure: Contexte / Faits clés / Hypothèses / Risques / Questions ouvertes.\n"
        "Réponse concise, factuelle.\n"
        f"---\nSTRATÉGIE:\n{strategie_txt}\n---\nBRIEF:\n{brief}\n"
    )
    brief_codir_res = _call_with_fallback(
        role="brief_codir",
        provider_order=strategie_order,
        prompt=brief_codir_prompt,
        system="Tu es un directeur de la stratégie. Tu synthétises en brief de travail pour un comité de direction.",
        temperature=0.2,
        max_tokens=min(900, max_tokens),
        settings=settings,
        diag_list=diag_list,
        cb=cb,
        logger=logger,
    )
    brief_codir_txt = _as_output(brief_codir_res)

    # 2) MARKETING — prefer OpenAI then Anthropic then Google then Mistral
    if cb:
        cb("marketing", "Marketing — préparation…")
    marketing_prompt = (
        "Rôle: Direction Marketing.\n"
        "Objectif: plan marketing (cibles, messages, canaux, budget, calendrier, KPI) en 6 points max.\n"
        "Prends en compte le Brief CoDIR.\n"
        f"---\nBrief CoDIR:\n{brief_codir_txt}\n---\nBrief initial:\n{brief}"
    )
    marketing_res = _call_with_fallback(
        role="marketing",
        provider_order=["openai", "anthropic", "google", "mistral"],
        prompt=marketing_prompt,
        system="Tu es une directrice marketing data-driven. Tu produis un plan concret et mesurable.",
        temperature=temperature,
        max_tokens=max_tokens,
        settings=settings,
        diag_list=diag_list,
        cb=cb,
        logger=logger,
    )
    marketing_txt = _as_output(marketing_res)

    # 3) FINANCE — prefer Google then Anthropic then OpenAI then Mistral
    if cb:
        cb("finance", "Finance — préparation…")
    finance_prompt = (
        "Rôle: Direction Financière (DAF / CFO).\n"
        "Objectif: projection synthétique (CA, marge, OPEX, CAPEX, cash) + 3 risques & parades.\n"
        "Format: bullets, chiffres plausibles, hypothèses explicites.\n"
        "Prends en compte le Brief CoDIR.\n"
        f"---\nBrief CoDIR:\n{brief_codir_txt}\n---\nMarketing:\n{marketing_txt}\n---\nBrief initial:\n{brief}"
    )
    finance_res = _call_with_fallback(
        role="finance",
        provider_order=["google", "anthropic", "openai", "mistral"],
        prompt=finance_prompt,
        system="Tu es un DAF rigoureux. Tu proposes une projection claire et prudente, avec hypothèses.",
        temperature=temperature,
        max_tokens=max_tokens,
        settings=settings,
        diag_list=diag_list,
        cb=cb,
        logger=logger,
    )
    finance_txt = _as_output(finance_res)

    # 4) SYNTHÈSE CEO — prefer OpenAI then Anthropic then Google then Mistral
    if cb:
        cb("direction_generale", "Direction Générale — préparation…")
    synthese_prompt = (
        "Rôle: CEO.\n"
        "Objectif: note (10-15 lignes) qui tranche et donne la feuille de route T0->T+90j.\n"
        "Style: directif, clair, réaliste. Termine par 5 next-steps datées.\n"
        "Prends en compte le Brief CoDIR.\n"
        f"---\nBrief CoDIR:\n{brief_codir_txt}\n---\nMarketing:\n{marketing_txt}\n---\nFinance:\n{finance_txt}\n---\nBrief initial:\n{brief}"
    )
    ceo_res = _call_with_fallback(
        role="direction_generale",
        provider_order=["openai", "anthropic", "google", "mistral"],
        prompt=synthese_prompt,
        system="Tu es un CEO pragmatique. Tu décides et assignes clairement.",
        temperature=temperature,
        max_tokens=max_tokens,
        settings=settings,
        diag_list=diag_list,
        cb=cb,
        logger=logger,
    )
    ceo_txt = _as_output(ceo_res)

    outputs = {
        "strategie": strategie_txt,
        "brief_codir": brief_codir_txt,
        "marketing": marketing_txt,
        "finance": finance_txt,
        "ceo": ceo_txt,
        "direction_generale": ceo_txt,
    }

    inputs = {
        "brief": brief,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "attachments_meta": attachments_meta or {},
    }

    if logger:
        log_event(logger, "info", "codir_engine", "session_finished")

    
    # Diagnostics: summary (1 row per role) + attempts (all provider tries)
    diagnostics_summary = []
    for k, v in (('strategie', strategie_res), ('brief_codir', brief_codir_res), ('marketing', marketing_res), ('finance', finance_res), ('ceo', ceo_res)):
        if not isinstance(v, dict):
            continue
        diagnostics_summary.append({
            'role': k,
            'provider': v.get('provider',''),
            'model': v.get('model',''),
            'status': 'OK' if not v.get('error') else 'ERROR',
            'attempt': v.get('attempt',''),
            'duration_s': v.get('duration_s',''),
            'tokens': v.get('tokens',{}),
            'error': (v.get('raw') or {}).get('exception','') if v.get('error') else '',
        })

    return {
        "outputs": outputs,
        "inputs": inputs,
        "diagnostics_summary": diagnostics_summary,
        "diagnostics_attempts": diag_list,
        "raw": {
            "strategie": strategie_res,
            "brief_codir": brief_codir_res,
            "marketing": marketing_res,
            "finance": finance_res,
            "ceo": ceo_res,
        },
    }