"""
CoDIR-IA — utils/target_entity_resolver.py — Since v16.5.69

REFACTO MAJEURE — découplage Pappers
─────────────────────────────────────────────────────────────────────────────
Avant v16.5.69, l'enrichissement multi-sources était une cascade pilotée par
Pappers : si Pappers ne trouvait rien (cas dossier anglophone coté, Apple, Tesla UK…), GLEIF
+ SEC + OpenSanctions + Companies House restaient muets sauf saisie manuelle.

Depuis v16.5.69, chaque source est interrogée par son **signal natif** :
  - SIREN (9 chiffres FR)            → Pappers
  - LEI (20 chars ISO 17442)         → GLEIF
  - CIK (10 chiffres) / ticker US    → SEC EDGAR
  - Company Number UK (8 chiffres ou prefix SC/NI/OC…) → Companies House
  - Nom de société / personne        → OpenSanctions (toujours), + recherche
                                        par nom sur les autres sources

Ce module fournit :
  1. `TargetEntity` dataclass — identité cross-juridictions
  2. `extract_signals_from_brief(brief)` — détecte tous les signaux natifs
     présents dans le brief en une seule passe
  3. `resolve_candidates(brief, lang)` — appelle TOUTES les sources qui ont un
     signal natif, sans cascade. Retourne une liste de `TargetEntityCandidate`
     que l'utilisateur va choisir dans la UI "Confirmer la cible".
  4. `merge_candidates(candidates)` — fusionne les candidats référant
     manifestement la même entité (même LEI, même CIK, ou même nom normalisé)

Architecture :
  - Aucune dépendance circulaire : ce module importe les `*_tool` mais aucun
    `*_tool` n'importe ce module.
  - Imports tolérants : si un module externe est absent, sa partie est simplement
    skippée (pas d'erreur).
  - Pappers reste l'unique propriétaire de l'extraction SIREN-from-brief
    (déjà éprouvée v16.5.59), on ne duplique pas.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# Imports tolérants des extracteurs natifs déjà présents dans chaque module
try:
    from utils.pappers_tool import _extract_siren_from_brief as _pap_extract_siren
except Exception:
    _pap_extract_siren = None  # type: ignore

try:
    from utils.gleif_tool import _extract_lei_from_text as _gleif_extract_lei, is_valid_lei
except Exception:
    _gleif_extract_lei = None  # type: ignore
    is_valid_lei = None  # type: ignore

try:
    from utils.sec_edgar_tool import (
        _extract_cik_from_text as _sec_extract_cik,
        _extract_ticker_from_text as _sec_extract_ticker,
    )
except Exception:
    _sec_extract_cik = None  # type: ignore
    _sec_extract_ticker = None  # type: ignore

try:
    from utils.companies_house_tool import (
        _extract_company_number_from_text as _ch_extract_cn,
    )
except Exception:
    _ch_extract_cn = None  # type: ignore


# ── Types de signaux ─────────────────────────────────────────────────────────

SIGNAL_SIREN     = "siren"          # 9 chiffres — Pappers
SIGNAL_LEI       = "lei"            # 20 chars ISO 17442 — GLEIF
SIGNAL_CIK       = "cik"            # 10 chiffres — SEC EDGAR
SIGNAL_TICKER    = "ticker"         # 1-5 lettres — SEC EDGAR
SIGNAL_CN_UK     = "cn_uk"          # 8 chiffres ou prefix SC/NI/OC — Companies House
SIGNAL_NAME      = "name"           # nom textuel — fallback pour toutes


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class ExtractedSignals:
    """Signaux natifs extraits d'un brief en une passe."""
    siren: Optional[str]    = None
    lei: Optional[str]      = None
    cik: Optional[str]      = None
    ticker: Optional[str]   = None
    cn_uk: Optional[str]    = None

    def has_any(self) -> bool:
        return any([self.siren, self.lei, self.cik, self.ticker, self.cn_uk])

    def to_dict(self) -> Dict[str, Optional[str]]:
        return asdict(self)

    def summary_line(self) -> str:
        parts = []
        if self.siren:  parts.append(f"SIREN={self.siren}")
        if self.lei:    parts.append(f"LEI={self.lei}")
        if self.cik:    parts.append(f"CIK={self.cik}")
        if self.ticker: parts.append(f"ticker={self.ticker}")
        if self.cn_uk:  parts.append(f"CN_UK={self.cn_uk}")
        return " | ".join(parts) if parts else "no_signals"


@dataclass
class TargetEntity:
    """
    Identité cross-juridictions d'une entité cible CoDIR-IA.

    Chaque champ est facultatif — l'entité peut n'avoir qu'un seul identifiant
    (ex. dossier anglophone coté n'a pas de SIREN, Apple n'a pas de Companies House Number).
    Le `name` est obligatoire (au moins une raison sociale).

    `source` indique quelle source a fourni l'enregistrement principal qui
    permet l'identification (utile pour la UI).
    """
    name: str = ""
    country: str = ""           # Code ISO 3166-1 alpha-2 (FR, GB, US, …)
    siren: str = ""             # FR
    lei: str = ""               # mondial
    cik: str = ""               # US
    ticker: str = ""            # US
    cn_uk: str = ""             # UK
    source: str = ""            # "pappers" | "gleif" | "sec_edgar" | "companies_house"
    confidence: str = ""        # "EXACT" | "FUZZY" | "DIRECT_ID" | "NAME_ONLY"
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "TargetEntity":
        data = dict(payload or {})
        allowed = {"name", "country", "siren", "lei", "cik", "ticker", "cn_uk",
                   "source", "confidence", "extra"}
        clean = {k: data.get(k) for k in allowed if k in data}
        if not isinstance(clean.get("extra", {}), dict):
            clean["extra"] = {}
        return cls(**clean)

    def display_label(self) -> str:
        """Label court pour la UI 'Confirm target entity'."""
        ids = []
        if self.siren:  ids.append(f"SIREN {self.siren}")
        if self.lei:    ids.append(f"LEI {self.lei[:8]}…")
        if self.cik:    ids.append(f"CIK {self.cik}")
        if self.cn_uk:  ids.append(f"CN {self.cn_uk}")
        if self.ticker: ids.append(f"${self.ticker}")
        ids_str = " · ".join(ids) if ids else "—"
        country_str = f" 🇫🇷" if self.country == "FR" else (
            " 🇬🇧" if self.country == "GB" else (
            " 🇺🇸" if self.country == "US" else (
            f" {self.country}" if self.country else "")))
        return f"{self.name}{country_str}  ({ids_str})  via {self.source}"


@dataclass
class TargetEntityCandidate:
    """
    Un candidat retourné par la résolution — plusieurs candidats peuvent
    être proposés à l'utilisateur si plusieurs sources matchent indépendamment.
    """
    entity: TargetEntity
    score: float = 0.0          # heuristique 0..1 pour pré-tri
    raw_record: Dict[str, Any] = field(default_factory=dict)


# ── Extraction de signaux ────────────────────────────────────────────────────

def extract_signals_from_brief(brief: str) -> ExtractedSignals:
    """
    Détecte en une passe TOUS les signaux natifs présents dans le brief.

    Stratégie : on délègue à chaque module l'extraction de son signal natif
    (cohérent avec la séparation des responsabilités). Pappers a déjà
    `_extract_siren_from_brief`, GLEIF a `_extract_lei_from_text`, etc.

    Tolérant : si un module n'est pas disponible, son champ reste None.
    """
    sig = ExtractedSignals()
    if not brief:
        return sig

    if _pap_extract_siren is not None:
        try:
            sig.siren = _pap_extract_siren(brief)
        except Exception:
            pass

    if _gleif_extract_lei is not None:
        try:
            sig.lei = _gleif_extract_lei(brief)
        except Exception:
            pass

    if _sec_extract_cik is not None:
        try:
            sig.cik = _sec_extract_cik(brief)
        except Exception:
            pass
    if _sec_extract_ticker is not None:
        try:
            sig.ticker = _sec_extract_ticker(brief)
        except Exception:
            pass

    if _ch_extract_cn is not None:
        try:
            sig.cn_uk = _ch_extract_cn(brief)
        except Exception:
            pass

    return sig


# ── Construction de candidats à partir des sources ───────────────────────────

def _candidate_from_pappers_block(blocks: Dict[str, Any]) -> Optional[TargetEntityCandidate]:
    """Construit un TargetEntityCandidate depuis un retour build_pappers_blocks."""
    if not blocks or not blocks.get("primary"):
        return None
    primary = blocks.get("primary", "")
    rlog = blocks.get("resolution_log")
    siren = ""
    if rlog is not None:
        siren = getattr(rlog, "siren_used", "") or ""
    confidence = blocks.get("confidence", "") or "NAME_ONLY"
    entity = TargetEntity(
        name=primary, country="FR", siren=siren,
        source="pappers",
        confidence=confidence,
    )
    return TargetEntityCandidate(
        entity=entity,
        score=0.95 if siren else 0.7,
        raw_record={"summary": (blocks.get("summary") or "")[:200]},
    )


def _candidate_from_gleif_block(blocks: Dict[str, Any]) -> Optional[TargetEntityCandidate]:
    if not blocks or not blocks.get("primary"):
        return None
    primary = blocks.get("primary", "")
    lei = blocks.get("primary_lei", "") or ""
    country = blocks.get("primary_country", "") or ""
    confidence = blocks.get("confidence", "") or "NAME_ONLY"
    entity = TargetEntity(
        name=primary, country=country, lei=lei,
        source="gleif",
        confidence=confidence,
    )
    score = 0.95 if confidence == "LEI_DIRECT" else (0.85 if confidence == "NAME_EXACT" else 0.6)
    return TargetEntityCandidate(
        entity=entity, score=score,
        raw_record={"summary": (blocks.get("summary") or "")[:200]},
    )


def _candidate_from_sec_block(blocks: Dict[str, Any]) -> Optional[TargetEntityCandidate]:
    if not blocks or not blocks.get("primary"):
        return None
    primary = blocks.get("primary", "")
    cik = blocks.get("primary_cik", "") or ""
    ticker = blocks.get("primary_ticker", "") or ""
    confidence = blocks.get("confidence", "") or "NAME_ONLY"
    if confidence == "NO_USER_AGENT":
        return None  # pas de candidat si UA absent
    entity = TargetEntity(
        name=primary, country="US", cik=cik, ticker=ticker,
        source="sec_edgar",
        confidence=confidence,
    )
    score = 0.95 if confidence == "CIK_DIRECT" else (0.85 if confidence in ("TICKER", "NAME_EXACT") else 0.6)
    return TargetEntityCandidate(
        entity=entity, score=score,
        raw_record={"summary": (blocks.get("summary") or "")[:200]},
    )


def _candidate_from_ch_block(blocks: Dict[str, Any]) -> Optional[TargetEntityCandidate]:
    if not blocks or not blocks.get("primary"):
        return None
    primary = blocks.get("primary", "")
    cn = blocks.get("company_number", "") or ""
    confidence = blocks.get("confidence", "") or "NAME_ONLY"
    if confidence == "NOT_CONFIGURED":
        return None
    entity = TargetEntity(
        name=primary, country="GB", cn_uk=cn,
        source="companies_house",
        confidence=confidence,
    )
    score = 0.95 if confidence == "NUMBER_DIRECT" else (0.85 if confidence == "NAME_EXACT" else 0.6)
    return TargetEntityCandidate(
        entity=entity, score=score,
        raw_record={"summary": (blocks.get("summary") or "")[:200]},
    )


# ── Fusion de candidats référant la même entité ──────────────────────────────

def _normalize_name(name: str) -> str:
    """Normalisation pour comparaison de noms (lowercase, strip ponctuation, formes juridiques courantes)."""
    if not name:
        return ""
    n = name.lower().strip()
    n = re.sub(r"[\.,;:&\(\)]", " ", n)
    # Compresser espaces multiples avant le strip de suffixes
    n = re.sub(r"\s+", " ", n).strip()
    # Retirer suffixes corporates fréquents (en boucle car certains s'enchaînent)
    suffixes = (" plc", " ltd", " limited", " inc", " corp", " corporation",
                " sa", " sas", " sasu", " sarl", " gmbh", " ag", " bv", " group")
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if n.endswith(suffix):
                n = n[: -len(suffix)].strip()
                changed = True
                break
    return re.sub(r"\s+", " ", n).strip()


def merge_candidates(candidates: List[TargetEntityCandidate]) -> List[TargetEntityCandidate]:
    """
    Fusionne les candidats référant manifestement la même entité.

    Règles de fusion (par priorité décroissante) :
      1. Même LEI → fusion certaine
      2. Même nom normalisé ET pays compatible → fusion
      3. Sinon : candidats distincts

    Le candidat fusionné agrège les identifiants (siren + lei + cik + cn_uk),
    conserve le `source` du score le plus élevé, et garde le score max.
    """
    if not candidates:
        return []

    merged: List[TargetEntityCandidate] = []

    for cand in candidates:
        e = cand.entity
        target_idx = None

        for i, existing in enumerate(merged):
            ex = existing.entity
            # Règle 1 : même LEI
            if e.lei and ex.lei and e.lei == ex.lei:
                target_idx = i
                break
            # Règle 2 : nom normalisé identique + pays compatible
            if (_normalize_name(e.name) == _normalize_name(ex.name)
                    and _normalize_name(e.name)
                    and (not e.country or not ex.country or e.country == ex.country)):
                target_idx = i
                break

        if target_idx is None:
            merged.append(cand)
        else:
            # Fusion : agrège les identifiants
            target = merged[target_idx]
            tgt_e = target.entity
            if e.siren  and not tgt_e.siren:  tgt_e.siren  = e.siren
            if e.lei    and not tgt_e.lei:    tgt_e.lei    = e.lei
            if e.cik    and not tgt_e.cik:    tgt_e.cik    = e.cik
            if e.ticker and not tgt_e.ticker: tgt_e.ticker = e.ticker
            if e.cn_uk  and not tgt_e.cn_uk:  tgt_e.cn_uk  = e.cn_uk
            if not tgt_e.country and e.country:
                tgt_e.country = e.country
            # Si le nouveau candidat a un meilleur score, ses metadata gagnent
            if cand.score > target.score:
                tgt_e.source = e.source
                tgt_e.confidence = e.confidence
                target.score = cand.score
                # Mais on garde le nom le plus complet (le plus long, généralement plus officiel)
                if len(e.name) > len(tgt_e.name):
                    tgt_e.name = e.name

    return merged


# ── Entry point principal ────────────────────────────────────────────────────

def resolve_candidates(
    brief: str,
    lang: str = "fr",
    max_per_source: int = 3,
) -> List[TargetEntityCandidate]:
    """
    Résolution multi-sources cross-juridictions.

    Stratégie :
      1. Extraire les signaux natifs du brief (SIREN, LEI, CIK, ticker, CN_UK)
      2. Pour chaque source dont le signal natif est présent → appel direct
      3. Si aucun signal natif n'a matché → tenter résolution par nom sur
         OpenSanctions (toujours pertinent), GLEIF, SEC EDGAR, Companies House
         (best-effort, à partir d'un nom probablement extrait du brief par
         heuristique simple — délégué à chaque module pour la recherche réelle).
      4. Fusionner les candidats référant manifestement la même entité.

    Note : OpenSanctions n'est PAS retourné comme candidat d'identité — c'est
    un signal de risque, pas un identifiant. OpenSanctions est interrogé
    séparément après confirmation utilisateur, sur l'entité confirmée.

    Retourne une liste triée par score décroissant.
    """
    candidates: List[TargetEntityCandidate] = []
    signals = extract_signals_from_brief(brief)

    # 1. Si signal SIREN → Pappers
    if signals.siren:
        try:
            from utils.pappers_tool import build_pappers_blocks
            blocks = build_pappers_blocks(brief, lang=lang)
            cand = _candidate_from_pappers_block(blocks)
            if cand:
                candidates.append(cand)
        except Exception:
            pass

    # 2. Si signal LEI → GLEIF (sinon GLEIF aura sa chance via NAME plus bas)
    if signals.lei:
        try:
            from utils.gleif_tool import build_gleif_blocks
            blocks = build_gleif_blocks(brief, lang=lang)
            cand = _candidate_from_gleif_block(blocks)
            if cand:
                candidates.append(cand)
        except Exception:
            pass

    # 3. Si signal CIK ou ticker → SEC EDGAR
    if signals.cik or signals.ticker:
        try:
            from utils.sec_edgar_tool import build_sec_edgar_blocks
            blocks = build_sec_edgar_blocks(brief, lang=lang)
            cand = _candidate_from_sec_block(blocks)
            if cand:
                candidates.append(cand)
        except Exception:
            pass

    # 4. Si signal CN_UK → Companies House
    if signals.cn_uk:
        try:
            from utils.companies_house_tool import build_companies_house_blocks
            blocks = build_companies_house_blocks(brief, lang=lang)
            cand = _candidate_from_ch_block(blocks)
            if cand:
                candidates.append(cand)
        except Exception:
            pass

    # 5. Fusion (même LEI / même nom)
    merged = merge_candidates(candidates)

    # Tri final par score décroissant
    return sorted(merged, key=lambda c: c.score, reverse=True)


def resolve_with_confirmed_name(
    brief: str,
    confirmed_name: str,
    lang: str = "fr",
) -> List[TargetEntityCandidate]:
    """
    Variant : appelé après que l'utilisateur a confirmé un nom de cible
    (ex. saisi manuellement parce qu'aucun signal natif n'avait matché).

    Interroge GLEIF + SEC EDGAR + Companies House par nom.
    Pappers n'est PAS interrogé ici (Pappers part toujours du SIREN, pas du nom).
    """
    candidates: List[TargetEntityCandidate] = []
    if not confirmed_name or len(confirmed_name.strip()) < 3:
        return []

    try:
        from utils.gleif_tool import build_gleif_blocks
        blocks = build_gleif_blocks(brief, lang=lang, confirmed_name=confirmed_name)
        cand = _candidate_from_gleif_block(blocks)
        if cand:
            candidates.append(cand)
    except Exception:
        pass

    try:
        from utils.sec_edgar_tool import build_sec_edgar_blocks
        blocks = build_sec_edgar_blocks(brief, lang=lang, confirmed_name=confirmed_name)
        cand = _candidate_from_sec_block(blocks)
        if cand:
            candidates.append(cand)
    except Exception:
        pass

    try:
        from utils.companies_house_tool import build_companies_house_blocks
        blocks = build_companies_house_blocks(brief, lang=lang, confirmed_name=confirmed_name)
        cand = _candidate_from_ch_block(blocks)
        if cand:
            candidates.append(cand)
    except Exception:
        pass

    return sorted(merge_candidates(candidates), key=lambda c: c.score, reverse=True)


__all__ = [
    "SIGNAL_SIREN", "SIGNAL_LEI", "SIGNAL_CIK", "SIGNAL_TICKER", "SIGNAL_CN_UK", "SIGNAL_NAME",
    "ExtractedSignals", "TargetEntity", "TargetEntityCandidate",
    "extract_signals_from_brief",
    "resolve_candidates",
    "resolve_with_confirmed_name",
    "merge_candidates",
]
