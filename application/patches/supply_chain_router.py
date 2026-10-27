"""
patches/supply_chain_router.py — v17.1-B2 (ticket B-04)

Bug observé : Lhyfe (producteur industriel d'hydrogène — 22 MW installés,
électrolyseurs, sites Le Cheylas/Croixrault, >80 tube trailers) sort avec
« Supply Chain : SKIPPED » parce que le code APE Pappers (71.12B, ingénierie) la
classe en « services sans flux physiques ».

Correctif : si le corpus (brief + faits + contexte) contient des SIGNAUX
INDUSTRIELS forts, Supply Chain s'exécute QUEL QUE SOIT l'APE Pappers.
"""
from __future__ import annotations

import re
from typing import List, Tuple

# Signaux d'une activité à flux physiques / industrielle.
_INDUSTRIAL_SIGNALS = [
    r"\bMW\b", r"\bGW\b", r"mégawatt", r"megawatt", r"gigawatt",
    r"électrolys", r"electrolys", r"electrolyz",
    r"tube\s*trailer", r"site[s]?\s+de\s+production", r"\busine[s]?\b",
    r"capacité\s+installée", r"\bEPC\b", r"unité[s]?\s+de\s+production",
    r"hydrogène\s+vert", r"\bH2\s+vert", r"ligne[s]?\s+de\s+production",
    r"tonnes?\s+par\s+(?:jour|an)", r"\bt/j\b", r"\bt/an\b",
    r"raffinerie", r"gigafactor", r"capacité\s+de\s+production",
]
_SIGNAL_RE = re.compile("|".join(_INDUSTRIAL_SIGNALS), re.IGNORECASE)


def has_industrial_signals(text: str, min_hits: int = 2) -> Tuple[bool, List[str]]:
    """True si ≥ min_hits signaux industriels DISTINCTS sont présents.
    Retourne (override, signaux_trouvés)."""
    if not text:
        return False, []
    found = []
    seen = set()
    for m in _SIGNAL_RE.finditer(text):
        key = m.group(0).lower().strip()
        if key not in seen:
            seen.add(key)
            found.append(m.group(0).strip())
    return (len(found) >= min_hits), found


# F.6.8 (audit dossier réseau de soins) — signaux RETAIL / STOCKS / BFR. dossier réseau de soins est du retail
# médical (stocks physiques, déstockage, provisions, rotation, BFR) classé
# « services » par l'APE → Supply Chain skippée à tort. Ces signaux documentaires
# doivent FORCER l'activation, même si le profil société est « services ».
_SUPPLY_CHAIN_SIGNALS = [
    r"sur[\s-]?stock", r"d[ée][\s-]?stockage", r"\bstocks?\b",
    r"rotation\s+(?:de\s+|des\s+)?stock", r"provisions?\s+sur\s+stocks?",
    r"d[ée]pr[ée]ciations?\s+(?:de\s+|des\s+)?stocks?", r"\binventaires?\b",
    r"\bBFR\b", r"besoin\s+en\s+fonds\s+de\s+roulement", r"\bDSO\b",
    r"approvisionnement", r"\bachats?\b", r"entrep[ôo]t", r"logistique",
    r"magasins?", r"points?\s+de\s+vente", r"\bSKU\b", r"\bretail\b",
    r"r[ée]seau\s+de\s+(?:centres?|magasins?|points)", r"flux\s+physiques?",
    r"approvisionnements?", r"rupture[s]?\s+de\s+stock",
]
_SC_RETAIL_RE = re.compile("|".join(_SUPPLY_CHAIN_SIGNALS), re.IGNORECASE)


def has_supply_chain_signals(text: str, min_hits: int = 2) -> Tuple[bool, List[str]]:
    """True si ≥ min_hits signaux Supply Chain DISTINCTS (industriels OU
    retail/stocks/BFR) sont présents. Sert à forcer l'activation Supply Chain
    quand le sujet est central, indépendamment de l'APE/profil « services »."""
    if not text:
        return False, []
    found = []
    seen = set()
    for rgx in (_SIGNAL_RE, _SC_RETAIL_RE):
        for m in rgx.finditer(text):
            key = m.group(0).lower().strip()
            if key not in seen:
                seen.add(key)
                found.append(m.group(0).strip())
    return (len(found) >= min_hits), found
