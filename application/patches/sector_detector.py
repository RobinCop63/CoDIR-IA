"""
CoDIR-IA — sector_detector v1 (v16.5.76 Phase 2 item 7)

Module de détection sectorielle heuristique à partir du NOM de société.

POURQUOI CE MODULE
==================

L'APE est un signal officiel mais souvent trompeur pour les holdings :
- dossier réseau de soins GROUPE a APE 70.21Z (Conseil en relations publiques) → classée services
  → supply_chain skippée
  → MAIS les filiales (centres dossier réseau de soins) ont APE 47.74Z (distribution médicale)
  avec gestion de stocks majeure (constat run #4 du 15 mai 2026).

Le nom "dossier réseau de soins" porte une information sectorielle que l'APE n'expose pas.
Idem pour Krys, Optic 2000, Boulanger, Sephora, McDonald's, Carrefour…

USAGE
=====

    from patches.sector_detector import detect_sector_from_name

    hint = detect_sector_from_name("dossier réseau de soins Groupe")
    # SectorHint(sector="distribution_sante", confidence="high",
    #            evidence=["dossier réseau de soins→audioprothèse/santé auditive"],
    #            implies_supply_chain=True)

    hint = detect_sector_from_name("La Française de l'Énergie")
    # None (pas de match dans la table — c'est OK, on ne hint pas)

ARCHITECTURE
============

Pure fonction sans I/O. Aucune dépendance hors stdlib.

La table `_SECTOR_PATTERNS` mappe des regex normalisées (insensibles à la casse,
sans accents) vers des `SectorHint`. Les patterns sont triés par spécificité
(plus spécifique → plus haute priorité).

INTERFACE AVEC LE RESTE DE CODIR-IA
====================================

1. `utils/company_profile.detect_profile_from_brief` peut appeler ce module
   pour pré-marquer un profil avant le lookup Pappers.

2. `codir_engine._resolve_supply_chain_decision` peut s'appuyer sur le hint
   pour court-circuiter le pré-filter LLM en cas de signal fort distribution.

3. La détection N'EST JAMAIS DÉCISIVE seule : c'est un signal de plus dans
   le faisceau (APE + nom + texte PJ + signaux Pappers).

DOCTRINE Q2 (4-TIER FACTS)
===========================

Les évidences retournées par ce module sont classées ESTIM-HYPOTHÈSE
(corrélation entre nom et secteur) car :
- Une société peut s'appeler "dossier réseau de soins" sans être dossier réseau de soins Groupe (homonymes possibles)
- Un nom peut être historiquement sectoriel mais l'entreprise a pivoté

C'est pourquoi ce hint est utilisé en complément, pas en remplacement,
des sources factuelles (APE Pappers, texte des PJ).


B.1.3.26 — STATUT : LEXIQUE DE CONNAISSANCES DÉCLARÉ (audit anti-hardcode).
Cette table sectorielle contient des noms d'entités connues. Ce n'est PAS
du raisonnement dynamique : c'est un référentiel versionné, assumé et
allowlisté au test contractuel anti-hardcode. Priorité d'usage : brief
déclaré > registres (Pappers/CH) > pièces > ce lexique (repli).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional


# ════════════════════════════════════════════════════════════════════════════
# TYPES
# ════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class SectorHint:
    """
    Hint sectoriel dérivé du nom de société.

    Champs :
    - sector : code interne CoDIR-IA (snake_case)
                ex : "distribution_sante", "distribution_optique", "retail_food",
                     "restauration_rapide", "distribution_electromenager", "luxury"
    - confidence : "high" / "medium" / "low" — basée sur la spécificité du match
    - evidence : liste de phrases courtes expliquant le match (pour audit/diag)
    - implies_supply_chain : True si ce secteur implique généralement une activité
                              de supply chain significative (stocks, distribution,
                              flux physiques)
    - implies_retail : True si secteur retail/réseau de points de vente
    - keywords_matched : liste des mots-clés du nom qui ont déclenché le match
    """
    sector: str
    confidence: str  # "high" | "medium" | "low"
    evidence: list[str] = field(default_factory=list)
    implies_supply_chain: bool = False
    implies_retail: bool = False
    keywords_matched: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "sector":               self.sector,
            "confidence":           self.confidence,
            "evidence":             list(self.evidence),
            "implies_supply_chain": self.implies_supply_chain,
            "implies_retail":       self.implies_retail,
            "keywords_matched":     list(self.keywords_matched),
        }


# ════════════════════════════════════════════════════════════════════════════
# TABLE DE PATTERNS SECTORIELS
# ════════════════════════════════════════════════════════════════════════════
# Chaque entrée : (regex_normalisée, sector, confidence, evidence, sc, retail)
# Triée par spécificité décroissante.
#
# IMPORTANT : les patterns matchent sur le nom NORMALISÉ (lowercase, sans accents,
# avec word boundaries). Voir _normalize_for_match().
#
# RÈGLE DE QUALITÉ : éviter les patterns trop génériques qui matcheraient
# des sociétés sans rapport. Préférer la précision (faux négatif) à la
# couverture (faux positif).

# v62.13.9.4.9 — interrupteur de connaissance sectorielle (contre-audit
# 30/08/2026, P1-948-05). Le fast-path nom→secteur court-circuite le
# prefilter LLM sur des enseignes nommées : un test final sur l'une d'elles
# n'est donc pas aveugle. L'interrupteur permet le SHADOW RUN — rejouer le
# même dossier sans la connaissance nommée, et comparer les deux sorties.
#
#   CODIR_SECTOR_KB=off        → base vide, décision par le prefilter LLM
#   CODIR_SECTOR_KB_EXCLUDE=x  → retire les entrées dont le libellé ou la
#                                regex contient « x » (comparés en minuscules,
#                                plusieurs valeurs séparées par des virgules)
#
# Par défaut, aucune variable : comportement de production inchangé.
SECTOR_KB_ENV = "CODIR_SECTOR_KB"
SECTOR_KB_EXCLUDE_ENV = "CODIR_SECTOR_KB_EXCLUDE"


def sector_kb_disabled() -> bool:
    import os as _os
    return str(_os.environ.get(SECTOR_KB_ENV, "")).strip().lower() in {
        "off", "0", "false", "disabled", "no"}


def sector_kb_exclusions() -> list[str]:
    import os as _os
    raw = str(_os.environ.get(SECTOR_KB_EXCLUDE_ENV, "") or "")
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def _load_sector_patterns() -> list[tuple[str, str, str, str, bool, bool]]:
    """v62.13.9.4.4 — la base nom→secteur est une donnée versionnée (config/), pas du code.
    v62.13.9.4.10 — gouvernée par un interrupteur, pour permettre un run aveugle."""
    import json as _json
    import os as _os
    if sector_kb_disabled():
        return []
    path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "config", "sector_knowledge_base.json")
    with open(path, "r", encoding="utf-8") as handle:
        entries = [tuple(entry) for entry in _json.load(handle)["patterns"]]
    drop = sector_kb_exclusions()
    if drop:
        entries = [e for e in entries
                   if not any(d in str(e[0]).lower() or d in str(e[3]).lower()
                              for d in drop)]
    return entries


_SECTOR_PATTERNS: list[tuple[str, str, str, str, bool, bool]] = _load_sector_patterns()


def reload_sector_patterns() -> int:
    """Recharge la base selon l'environnement courant ; renvoie sa taille.
    Sert au shadow run et aux tests de neutralité."""
    global _SECTOR_PATTERNS
    _SECTOR_PATTERNS = _load_sector_patterns()
    return len(_SECTOR_PATTERNS)


# ════════════════════════════════════════════════════════════════════════════
# NORMALISATION
# ════════════════════════════════════════════════════════════════════════════

def _normalize_for_match(name: str) -> str:
    """
    Normalise un nom de société pour matching :
    - lowercase
    - suppression des accents (NFD + filtre Mn)
    - suppression des formes juridiques (SA, SAS, SASU, SARL, etc.)
    - suppression des suffixes corporate (groupe, group, holding, sa, sas, etc.)
    - écrasement des espaces multiples
    """
    if not name:
        return ""
    # 1. Lowercase + suppression accents
    s = name.lower().strip()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    # 2. Suppression formes juridiques et corporate suffixes
    # On utilise des word boundaries pour ne pas casser "groupe" dans "groupement"
    legal_patterns = [
        r"\b(?:sa|sas|sasu|sarl|eurl|snc|scop|sci|sl|ag|gmbh|ltd|llc|inc|corp|plc)\b",
        r"\b(?:groupe|group|holding|holdings|company|co)\b",
        r"\b(?:l[ée]nergie)\b",  # ex: "La Française de l'Énergie" → on garde "francaise" qui n'est pas un secteur connu
    ]
    for p in legal_patterns:
        s = re.sub(p, " ", s, flags=re.IGNORECASE)
    # 3. Suppression ponctuation parasites (mais on garde & et ' qui peuvent être dans les patterns)
    s = re.sub(r"[!?.,;:()\[\]{}]", " ", s)
    # 4. Espaces multiples → 1
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ════════════════════════════════════════════════════════════════════════════
# API PUBLIQUE
# ════════════════════════════════════════════════════════════════════════════

def detect_sector_from_name(company_name: str) -> Optional[SectorHint]:
    """
    Détecte un secteur depuis le nom de société par pattern matching.

    Retourne :
      - SectorHint si match (peut être confidence high/medium/low)
      - None si aucun match

    Le caller décide quoi faire en fonction de la confidence :
      - high   : signal très fiable, peut être utilisé comme fast-path
      - medium : signal probable, à combiner avec d'autres sources
      - low    : signal faible, juste à titre indicatif (audit/diag)

    Cette fonction est pure (aucun I/O), thread-safe, déterministe.
    """
    if not company_name or not isinstance(company_name, str):
        return None

    normalized = _normalize_for_match(company_name)
    if not normalized:
        return None

    # Match séquentiel (premier match gagne — donc patterns par spécificité décroissante)
    for pattern, sector, confidence, evidence, sc, retail in _SECTOR_PATTERNS:
        m = re.search(pattern, normalized, re.IGNORECASE)
        if m:
            matched_kw = m.group(0)
            return SectorHint(
                sector=sector,
                confidence=confidence,
                evidence=[f"{matched_kw.strip()} → {evidence}"],
                implies_supply_chain=sc,
                implies_retail=retail,
                keywords_matched=[matched_kw.strip()],
            )

    return None


def is_supply_chain_implied_by_name(company_name: str) -> bool:
    """
    Helper de convenance : retourne True si le nom de société implique
    fortement une activité de supply chain significative.

    Utilisé par codir_engine._resolve_supply_chain_decision pour le fast-path.

    Règles :
      - confidence high + implies_supply_chain True → True
      - confidence medium + implies_supply_chain True → True
      - confidence low → False (trop incertain pour court-circuiter le LLM)
      - pas de match → False
    """
    hint = detect_sector_from_name(company_name)
    if hint is None:
        return False
    if hint.confidence == "low":
        return False
    return hint.implies_supply_chain


__all__ = [
    "SectorHint",
    "detect_sector_from_name",
    "is_supply_chain_implied_by_name",
]
