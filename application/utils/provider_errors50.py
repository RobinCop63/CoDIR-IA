"""v62.13.9.4.50 — erreur d'un fournisseur de modèles, dite en clair dans le test des Réglages (recette du 01/10/2026 :
« Tester Mistral » affichait le corps brut « API error occurred: Status 429 … rate_limited »). Le code HTTP dit où
chercher : la clé, l'accès au modèle, le plan du compte ou le service lui-même. Le message d'origine reste joint.
"""
from __future__ import annotations

import re

_CONSOLES = {"mistral": "console.mistral.ai", "openai": "platform.openai.com", "anthropic": "console.anthropic.com",
             "google": "aistudio.google.com", "gemini": "aistudio.google.com", "perplexity": "perplexity.ai/account/api",
             "grok": "console.x.ai"}


def explain_provider_error(provider: str, raw: str, lang: str = "fr") -> str:
    s = str(raw or "")
    en = str(lang).lower().startswith("en")
    console = _CONSOLES.get(str(provider or "").lower(), "")
    m = re.search(r"(?:Status|status|HTTP|code)[\s:=\"']*([1-5]\d\d)\b", s) or re.search(r"\b([45]\d\d)\b", s)
    code = m.group(1) if m else ""
    if code == "429" or re.search(r"(?i)rate.?limit|rate_limited|quota|RESOURCE_EXHAUSTED", s):
        why = ("clé valide, mais limite de débit ou quota du compte atteint (429) : vérifie le plan et les limites "
               f"du compte{' sur ' + console if console else ''} ; sur une offre gratuite, ajouter un moyen de paiement "
               "relève les limites" if not en else
               "key valid, but the account's rate limit or quota is reached (429): check the plan and limits"
               f"{' on ' + console if console else ''}; on a free tier, adding a payment method raises the limits")
    elif code in ("401",) or re.search(r"(?i)unauthori[sz]ed|invalid.?api.?key|authentication", s):
        why = "clé refusée (401) : vérifie la clé saisie" if not en else "key rejected (401): check the key entered"
    elif code == "403" or re.search(r"(?i)forbidden|permission", s):
        why = ("accès refusé (403) : la clé n'a pas accès à ce modèle ou à ce service" if not en
               else "access denied (403): the key has no access to this model or service")
    elif code == "404" or re.search(r"(?i)not.?found|no longer available", s):
        why = ("modèle introuvable pour ce compte (404) : vérifie l'identifiant du modèle dans les Réglages" if not en
               else "model not found for this account (404): check the model id in Settings")
    elif code.startswith("5") or re.search(r"(?i)unavailable|overloaded|high demand", s):
        why = ("service momentanément indisponible côté fournisseur : réessaie dans quelques minutes" if not en
               else "service temporarily unavailable on the provider's side: retry in a few minutes")
    else:
        return s[:200]
    return f"{why}. — {s[:120]}"
