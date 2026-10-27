"""patches/listed_forms.py — B.1.3.13 : formes cotées, DIAGNOSTICS SEULEMENT.

Préparation Annexe B décidée avec R. Sauzet : la table des formes juridiques
« cotables » vit en DONNÉES (forme → juridiction → force du signal), et ce
module n'est branché QUE sur l'observabilité (annotation des candidats vus
par la re-recherche Companies House ; détection de tokens de marché dans le
brief, JOURNALISÉE sans jamais basculer le hint). AUCUNE mutation de
résolution : le jour où un cas terrain (SE/NV/AG/ASA…) l'exige, la
préférence sera activée POUR CETTE FORME, avec un run derrière — jamais
spéculée avant. Module PUR (zéro import projet).

Force du signal :
- STRONG : la forme implique (quasi) toujours une société ouverte au public
  dans sa juridiction (UK plc, NO ASA) — utilisable un jour comme préférence.
- WEAK : la forme est portée par des millions de sociétés NON cotées
  (SA, AG, NV, AB, SpA…) — ne DOIT jamais voler un top à elle seule.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple, List

# forme (regex de fin de dénomination) → (juridictions, force)
LISTED_FORMS: tuple = (
    (r"\bplc\b",  ("UK", "IE"), "STRONG"),
    (r"\basa\b",  ("NO",),      "STRONG"),
    (r"\bse\b",   ("EU",),      "WEAK"),
    (r"\bnv\b",   ("NL", "BE"), "WEAK"),
    (r"\bag\b",   ("DE", "CH", "AT"), "WEAK"),
    (r"\bsa\b",   ("FR", "ES", "PT", "PL", "RO"), "WEAK"),
    (r"\bab\b",   ("SE",),      "WEAK"),
    (r"\bspa\b|\bs\.p\.a\.?\b", ("IT",), "WEAK"),
    (r"\boyj\b",  ("FI",),      "STRONG"),
    (r"\ba/s\b",  ("DK",),      "WEAK"),
    (r"\bas\b",   ("NO", "DK", "CZ"), "WEAK"),
)

_MARKET_TOKENS = re.compile(
    r"\b(LSE|EPA|AMS|ETR|XETRA|OMX|BIT|SIX|SWX|OSE|OSL|HEL|CPH|STO|WSE|"
    r"Euronext|NYSE|NASDAQ)\s*[:\-]",
    re.IGNORECASE,
)


def classify_entity_form(name: str) -> Optional[Tuple[str, str, tuple]]:
    """Retourne (forme_normalisée, force, juridictions) ou None."""
    low = " " + (name or "").strip().lower().rstrip(".") + " "
    for pat, jur, strength in LISTED_FORMS:
        m = re.search(pat + r"\s*$", low.strip()) or re.search(pat, low)
        if m and re.search(pat + r"[\s\.]*$", low.rstrip()):
            return (m.group(0).strip().upper(), strength, jur)
    return None


def annotate_candidates(titles: List[str]) -> List[str]:
    """['ACME PLC', 'ACME GMBH'] → ['ACME PLC [PLC/STRONG]', 'ACME GMBH']."""
    out = []
    for t in titles or []:
        c = classify_entity_form(t)
        out.append(f"{t} [{c[0]}/{c[1]}]" if c else str(t))
    return out


def detect_market_tokens(brief: str) -> List[str]:
    """Tokens de place de marché vus au brief — JOURNAL SEULEMENT."""
    return sorted({m.group(1).upper()
                   for m in _MARKET_TOKENS.finditer(brief or "")})


def strong_nonplc_present(titles: List[str]) -> bool:
    """Tripwire Annexe B : une forme STRONG ≠ plc est passée dans les
    candidats — le jour où c'est True au CSV, l'extension se décide."""
    for t in titles or []:
        c = classify_entity_form(t)
        if c and c[1] == "STRONG" and c[0] != "PLC":
            return True
    return False
