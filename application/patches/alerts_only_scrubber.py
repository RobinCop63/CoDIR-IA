"""
patches/alerts_only_scrubber.py — F.6.8 (audit dossier réseau de soins, ticket Feed-forward Scrubber)

Une séance CLOSING_REVIEW / ALERTS_ONLY (revue de clôture, Comité d'audit) ne rend
PAS de décision GO/NO-GO. Le genre gate F.6.7 corrige la décision CENTRALE, mais :
  - l'agent Commercial émet encore « ARBITRAGES OU GO / NO-GO COMMERCIAUX » ;
  - le feed-forward réinjecte d'anciennes actions « GO sur le plan… ».

Ce scrubber convertit DÉTERMINISTEMENT ce vocabulaire décisionnel en langage
d'alerte / recommandation, sans toucher au fond métier.
"""
from __future__ import annotations

import re
from typing import List, Tuple

_RULES: List[Tuple[re.Pattern, str]] = [
    # En-têtes de section « ARBITRAGES OU GO / NO-GO (COMMERCIAUX) »
    (re.compile(r"ARBITRAGES?\s+(?:OU|ET|&)\s+GO\s*/?\s*NO[\s\-]?GO(\s+COMMERCIAUX?)?",
                re.IGNORECASE),
     "ARBITRAGES & POINTS À ARBITRER"),
    (re.compile(r"\bGO\s*/?\s*NO[\s\-]?GO\s+COMMERCIAUX?\b", re.IGNORECASE),
     "arbitrages commerciaux"),
    # « GO conditionnel » → à arbitrer
    (re.compile(r"\bGO\s+conditionnel(?:le)?\b", re.IGNORECASE),
     "à arbitrer (sous conditions)"),
    # « NO-GO sur X » → point de vigilance
    (re.compile(r"\bNO[\s\-]?GO\s+sur\b", re.IGNORECASE),
     "Point de vigilance (non recommandé en l'état) :"),
    # « GO sur X » → action ouverte recommandée / à arbitrer
    (re.compile(r"\bGO\s+sur\b", re.IGNORECASE),
     "Action ouverte (recommandée, à arbitrer) :"),
    # Reste de « GO / NO-GO » générique
    (re.compile(r"\bGO\s*/?\s*NO[\s\-]?GO\b", re.IGNORECASE),
     "arbitrage (alerte, pas de décision d'engagement)"),
]


def scrub_go_nogo(text: str) -> str:
    """Remplace le vocabulaire GO/NO-GO par du langage d'alerte/recommandation.
    Idempotent et sûr : ne touche que des motifs explicitement décisionnels."""
    if not text or not isinstance(text, str):
        return text
    out = text
    for rgx, repl in _RULES:
        out = rgx.sub(repl, out)
    return out


def scrub_if_alerts_only(text: str, decision_mode: str) -> str:
    """Applique le scrub uniquement quand la séance est en mode ALERTS_ONLY."""
    if not text:
        return text
    if str(decision_mode or "").upper() == "ALERTS_ONLY":
        return scrub_go_nogo(text)
    return text
