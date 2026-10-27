# -*- coding: utf-8 -*-
"""B.1.3.20 (P1-C, run dossier agroalimentaire) — contradiction d'entité DANS le brief.

Racine constatée sur pièces : le brief désignait « le groupe dossier agroalimentaire
Biscuits » PUIS demandait « la situation de dossier industriel » (résidu de gabarit
copié). Le run a correctement analysé dossier agroalimentaire, mais AUCUN mécanisme ne
pouvait surfacer la contradiction : l'entity validator WHITELISTE par
construction les noms présents au brief — une contamination de brief est
donc invisible aux checks aval. Le gate vit à la BRIQUE ZÉRO : comparaison
directe des désignations de cible du brief contre l'entité résolue.

Déterministe, sans réseau. Ne bloque pas : bannière ALERTES PIPELINE
(canal P0-3) + ligne diagnostics — « clarification requise avant usage ».
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from patches.entity_scope import should_quarantine_registry

# Désignations de CIBLE — le nom capturé est présenté comme le sujet du run.
# (On ne capture PAS les mentions libres : concurrents, fournisseurs, etc.)
_DESIGNATION_RES = [
    re.compile(r"\bsituation\s+(?:de|du|des|d['’])\s*(?:la\s+soci[ée]t[ée]\s+|le\s+groupe\s+|l['’]entreprise\s+)?([A-ZÀ-Ü][\w'’&.\- ]{2,60})", re.UNICODE),
    re.compile(r"\bpour\s+(?:la\s+soci[ée]t[ée]|le\s+groupe|l['’]entreprise)\s+([A-ZÀ-Ü][\w'’&.\- ]{2,60})", re.UNICODE),
    re.compile(r"^\s*(?:Soci[ée]t[ée]|Company|Entreprise)\s*:\s*(.{2,60})$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"\banalys(?:er|e\s+de)\s+(?:la\s+soci[ée]t[ée]\s+|le\s+groupe\s+)?([A-ZÀ-Ü][\w'’&.\- ]{2,60})", re.UNICODE),
]

_TRAILING_NOISE_RE = re.compile(
    r"\s+(?:et|puis|ainsi|avec|dont|pour|dans|sur|aupr[èe]s|bas[ée]e?s?)\b.*$",
    re.IGNORECASE)

# B.1.3.22 (F3, relecture critique) — noms communs capitalisés qui suivent
# légitimement « situation de » sans désigner une entité (repro : « la
# situation de Trésorerie du groupe » levait un faux CONFLIT D'ENTITÉ).
# Rejet si le PREMIER token de la capture est dans ce lexique.
_COMMON_NOUN_STOP = {
    "trésorerie", "tresorerie", "marché", "marche", "ventes", "vente",
    "situation", "groupe", "société", "societe", "entreprise", "direction",
    "gouvernance", "finance", "finances", "résultats", "resultats",
    "stratégie", "strategie", "activité", "activite", "activités",
    "activites", "crise", "concurrence", "dette", "liquidité", "liquidite",
}


def _clean_designation(raw: str) -> str:
    s = (raw or "").strip().strip(" .;:,!?…")
    s = _TRAILING_NOISE_RE.sub("", s).strip(" .;:,")
    # coupe à la première ponctuation forte restante
    s = re.split(r"[.;:!?\n]", s)[0].strip()
    return s[:60]


def extract_target_designations(brief: str) -> List[str]:
    """Noms désignés comme CIBLE dans le brief (dédupliqués, ordre d'apparition)."""
    out: List[str] = []
    seen = set()
    for rx in _DESIGNATION_RES:
        for m in rx.finditer(brief or ""):
            name = _clean_designation(m.group(1))
            if len(name) < 3:
                continue
            # B.1.3.22 (F3) — premier token = nom commun → pas une entité.
            _first = name.split()[0].lower() if name.split() else ""
            if _first in _COMMON_NOUN_STOP:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(name)
    return out


def detect_brief_entity_conflict(brief: str, resolved_entity: str,
                                 lang: str = "fr") -> Tuple[Optional[str], List[str]]:
    """(note, conflits) — note d'alerte si une désignation de cible du brief
    ne partage AUCUN token significatif avec l'entité résolue (règle
    identique à la quarantaine registre M6-A2.1.1)."""
    resolved = (resolved_entity or "").strip()
    if not brief or not resolved:
        return None, []
    conflicts: List[str] = []
    for name in extract_target_designations(brief):
        try:
            if should_quarantine_registry(resolved, name):
                conflicts.append(name)
        except Exception:
            continue
    if not conflicts:
        return None, []
    listed = " ; ".join(f"« {c} »" for c in conflicts[:3])
    if lang == "en":
        note = ("⚠ BRIEF ENTITY CONFLICT (P1-C) — the brief designates both "
                f"« {resolved} » and {listed} as the target. The analysis was "
                f"conducted on « {resolved} »; clarify the intended entity "
                "before any use of this deliverable.")
    else:
        note = ("⚠ CONFLIT D'ENTITÉ AU BRIEF (P1-C) — le brief désigne à la "
                f"fois « {resolved} » et {listed} comme cible. L'analyse a été "
                f"conduite sur « {resolved} » ; clarifier l'entité visée avant "
                "tout usage de ce livrable.")
    return note, conflicts
