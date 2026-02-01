import os, sys
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# codir_engine.py — v16.0 safe + outputs map + alias DG + inputs
import os
import traceback
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
    from providers.mistral_provider import call_mistral  # optionnel
except Exception:
    call_mistral = None


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


def _safe_call(tag, func, *args, **kwargs):
    try:
        resp = func(*args, **kwargs)
        if isinstance(resp, dict) and "output" in resp:
            return resp
        return {
            "output": _as_output(resp),
            "model": kwargs.get("model") or os.getenv(f"{tag.upper()}_MODEL", ""),
            "provider": tag,
            "tokens": {},
            "raw": resp,
        }
    except Exception as e:
        tb = traceback.format_exc()
        return {
            "output": f"[{tag} ERROR] {e}",
            "model": kwargs.get("model") or os.getenv(f"{tag.upper()}_MODEL", ""),
            "provider": tag,
            "tokens": {},
            "raw": {"exception": repr(e), "traceback": tb},
            "error": True,
        }


def run_codir_session(brief: str, temperature: float = 0.2, max_tokens: int = 1024):
    brief = render_brief(brief)

    # 1) STRATÉGIE — Claude
    strategie_prompt = (
        "Rôle: Directeur de la stratégie.\n"
        "Objectif: proposer une stratégie claire, priorisée et exécutable.\n"
        "Contrainte: style sobre, concis, actionnable.\n"
        "Brief fourni:\n---\n" + brief
    )
    strategie_res = _safe_call(
        "anthropic",
        call_claude,
        prompt=strategie_prompt,
        system="Tu es un directeur de la stratégie expérimenté. Tu produis un plan clair, chiffré et priorisé.",
        temperature=temperature,
        max_tokens=max_tokens,
    )
    strategie_txt = _as_output(strategie_res)

    # 2) MARKETING — OpenAI si dispo, sinon Claude ; fallback si erreur
    marketing_prompt = (
        "Rôle: Direction Marketing.\n"
        "Objectif: plan marketing (cibles, messages, canaux, budget, calendrier, KPI) en 6 points max.\n"
        "Prends en compte la Stratégie ci-dessous.\n"
        f"---\nStratégie:\n{strategie_txt}\n---\nBrief:\n{brief}"
    )
    if call_openai:
        marketing_res = _safe_call(
            "openai",
            call_openai,
            prompt=marketing_prompt,
            system="Tu es une directrice marketing data-driven. Tu produis un plan concret et mesurable.",
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if marketing_res.get("error"):
            marketing_res = _safe_call(
                "anthropic",
                call_claude,
                prompt=marketing_prompt,
                system="Tu es une directrice marketing data-driven. Tu produis un plan concret et mesurable.",
                temperature=temperature,
                max_tokens=max_tokens,
            )
    else:
        marketing_res = _safe_call(
            "anthropic",
            call_claude,
            prompt=marketing_prompt,
            system="Tu es une directrice marketing data-driven. Tu produis un plan concret et mesurable.",
            temperature=temperature,
            max_tokens=max_tokens,
        )
    marketing_txt = _as_output(marketing_res)

    # 3) FINANCE — Gemini si dispo, sinon Claude ; fallback si erreur
    finance_prompt = (
        "Rôle: Direction Financière (DAF / CFO).\n"
        "Objectif: projection synthétique (CA, marge, OPEX, CAPEX, cash) + 3 risques & parades.\n"
        "Format: bullets, chiffres plausibles, hypothèses explicites.\n"
        f"---\nStratégie:\n{strategie_txt}\n---\nMarketing:\n{marketing_txt}\n---\nBrief:\n{brief}"
    )
    if call_gemini:
        finance_res = _safe_call(
            "google",
            call_gemini,
            prompt=finance_prompt,
            system="Tu es un DAF rigoureux. Tu proposes une projection claire et prudente, avec hypothèses.",
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if finance_res.get("error"):
            finance_res = _safe_call(
                "anthropic",
                call_claude,
                prompt=finance_prompt,
                system="Tu es un DAF rigoureux. Tu proposes une projection claire et prudente, avec hypothèses.",
                temperature=temperature,
                max_tokens=max_tokens,
            )
    else:
        finance_res = _safe_call(
            "anthropic",
            call_claude,
            prompt=finance_prompt,
            system="Tu es un DAF rigoureux. Tu proposes une projection claire et prudente, avec hypothèses.",
            temperature=temperature,
            max_tokens=max_tokens,
        )
    finance_txt = _as_output(finance_res)

    # 4) SYNTHÈSE CEO — OpenAI si dispo, sinon Claude ; fallback si erreur
    synthese_prompt = (
        "Rôle: CEO.\n"
        "Objectif: note (10-15 lignes) qui tranche et donne la feuille de route T0->T+90j.\n"
        "Style: directif, clair, réaliste. Termine par 5 next-steps datées.\n"
        f"---\nStratégie:\n{strategie_txt}\n---\nMarketing:\n{marketing_txt}\n---\nFinance:\n{finance_txt}\n---\nBrief:\n{brief}"
    )
    if call_openai:
        ceo_res = _safe_call(
            "openai",
            call_openai,
            prompt=synthese_prompt,
            system="Tu es un CEO pragmatique. Tu décides et assignes clairement.",
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if ceo_res.get("error"):
            ceo_res = _safe_call(
                "anthropic",
                call_claude,
                prompt=synthese_prompt,
                system="Tu es un CEO pragmatique. Tu décides et assignes clairement.",
                temperature=temperature,
                max_tokens=max_tokens,
            )
    else:
        ceo_res = _safe_call(
            "anthropic",
            call_claude,
            prompt=synthese_prompt,
            system="Tu es un CEO pragmatique. Tu décides et assignes clairement.",
            temperature=temperature,
            max_tokens=max_tokens,
        )
    ceo_txt = _as_output(ceo_res)

    full_text = (
        "=== STRATÉGIE (Claude) ===\n" + strategie_txt + "\n\n"
        "=== MARKETING ===\n" + marketing_txt + "\n\n"
        "=== FINANCE ===\n" + finance_txt + "\n\n"
        "=== SYNTHÈSE CEO ===\n" + ceo_txt + "\n"
    )

    # Map 'outputs' pour compat app.py (+ alias DG)
    outputs = {
        "strategie":          strategie_txt,
        "marketing":          marketing_txt,
        "finance":            finance_txt,
        "ceo":                ceo_txt,
        "direction_generale": ceo_txt,  # alias
    }

    # 👉 Ajout pour compat app.py: bloc 'inputs'
    inputs = {
        "brief": brief,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    return {
        "strategie": strategie_res,
        "marketing": marketing_res,
        "finance":   finance_res,
        "ceo":       ceo_res,
        "full_text": full_text,
        "outputs":   outputs,
        "inputs":    inputs,   # <= demandé par app.py
    }
