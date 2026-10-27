"""
utils/id_router.py — Patch v16.5.72.10 (retex Robin)

Routage intelligent vers la source externe primaire selon l'identifiant détecté
dans le brief ou confirmed_entity.

Comportement avant v16.5.72.10 (force brute) :
    À chaque session : Pappers + CH + GLEIF appelés systématiquement
    → 3-5s perdues sur sociétés non-FR (Pappers inutile pour dossier anglophone coté)

Comportement v16.5.72.10 (routage intelligent) :
    SIREN détecté        → Pappers primary, CH skipped, GLEIF (toujours)
    UK Company Number    → CH primary, Pappers skipped, GLEIF (toujours)
    LEI seul détecté     → GLEIF primary, autres skipped
    Pas d'ID             → Comportement actuel (3 sources tentent)

GLEIF reste toujours appelé : rapide (1-3s), complémentaire, fournit le LEI
international utile quel que soit le pays primaire détecté.

API publique :
    detect_primary_id(brief, confirmed_entity) -> RoutingDecision
    RoutingDecision.use_pappers, .use_ch, .use_gleif, .id_type, .primary_id

Backward compatibility :
    Si l'utilisateur tape juste un nom (pas d'ID), comportement v16.5.72.9
    préservé (use_pappers=True, use_ch=True, use_gleif=True).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ════════════════════════════════════════════════════════════════════════════
# Patterns de détection
# ════════════════════════════════════════════════════════════════════════════


# SIREN FR : 9 chiffres exactement, peut être préfixé par "SIREN" ou avec
# espaces/tirets entre les chiffres. Capture le numéro normalisé.
# Attention au mot frontière pour éviter de matcher dans 1234567890 (10 chiffres).
_RE_SIREN_HARD = re.compile(
    r"\b(?:SIREN|RCS)?\s*[:#]?\s*"
    r"(\d{3}[\s\-.]?\d{3}[\s\-.]?\d{3})"
    r"(?!\d)",  # negative lookahead : pas de chiffre après (= pas un nombre + long)
    re.IGNORECASE,
)


# UK Company Number : 8 chars (avec/sans préfixe SC/NI/OC/etc.)
# - Sans préfixe : 6 à 8 chiffres
# - Avec préfixe : préfixe + 5-8 chiffres
# Pattern réutilisé de companies_house_tool.py
_RE_COMPANY_NUMBER_HARD = re.compile(
    r"\b(?:Companies?\s*House\s*(?:number|n°|no\.?)?\s*[:#]?\s*|"
    r"Company\s*Number\s*[:#]?\s*|"
    r"UK\s*Company\s*Number\s*[:#]?\s*|"
    r"CRN\s*[:#]?\s*|"
    r"Company\s*No\.?\s*[:#]?\s*)?"
    r"((?:SC|NI|OC|SO|R|GE|FC|GS|LP|NL|RC|SF|SL|SR|SZ)?\s*\d{5,8})\b",
    re.IGNORECASE,
)
# Pattern strict pour validation finale
_RE_CN_VALID = re.compile(r"^([A-Z]{2})(\d{5,8})$|^()(\d{6,8})$", re.IGNORECASE)


# LEI : 20 caractères alphanumériques (lettres majuscules + chiffres)
# Format Strict ISO 17442 : 4 chars LOU + 2 chars reserved + 12 chars entity + 2 chars checksum
_RE_LEI = re.compile(r"\b([A-Z0-9]{18}\d{2})\b")


# SEC CIK : 10 chiffres dans contexte US (préfixé "CIK" obligatoire pour disambiguation)
_RE_SEC_CIK = re.compile(r"\bCIK\s*[:#]?\s*(\d{6,10})\b", re.IGNORECASE)


# ════════════════════════════════════════════════════════════════════════════
# Decision dataclass
# ════════════════════════════════════════════════════════════════════════════


@dataclass
class RoutingDecision:
    """
    Décision de routage des sources externes pour une session.

    Champs :
        use_pappers     : appeler Pappers ? (FR, SIREN)
        use_ch          : appeler Companies House ? (UK, Company Number)
        use_gleif       : appeler GLEIF ? (LEI international)
        id_type         : type d'identifiant détecté (siren | company_number | lei | none)
        primary_id      : valeur normalisée de l'identifiant détecté
        rationale       : raison textuelle (pour diagnostic / DOCX)
    """
    use_pappers: bool = True
    use_ch: bool = True
    use_gleif: bool = True
    id_type: str = "none"  # siren | company_number | lei | none
    primary_id: Optional[str] = None
    rationale: str = "no_id_detected_fallback_all_sources"

    def to_dict(self) -> dict:
        return {
            "use_pappers": self.use_pappers,
            "use_ch": self.use_ch,
            "use_gleif": self.use_gleif,
            "id_type": self.id_type,
            "primary_id": self.primary_id,
            "rationale": self.rationale,
        }


# ════════════════════════════════════════════════════════════════════════════
# Helpers de normalisation et validation
# ════════════════════════════════════════════════════════════════════════════


def _normalize_siren(raw: str) -> Optional[str]:
    """Strip espaces/tirets/points → 9 chiffres exact."""
    if not raw:
        return None
    cleaned = re.sub(r"[\s\-.]", "", raw)
    if re.fullmatch(r"\d{9}", cleaned):
        return cleaned
    return None


def _normalize_company_number(raw: str) -> Optional[str]:
    """Strip espaces, padding 0 si nécessaire, validation format CH UK."""
    if not raw:
        return None
    cleaned = re.sub(r"\s", "", raw).upper()
    m = _RE_CN_VALID.match(cleaned)
    if not m:
        return None
    prefix = m.group(1) or m.group(3) or ""
    digits = m.group(2) or m.group(4) or ""
    if not digits:
        return None
    # Padding zéros pour atteindre 8 chars total (CH UK convention)
    if prefix:
        return prefix + digits.zfill(8 - len(prefix))
    return digits.zfill(8)


# ════════════════════════════════════════════════════════════════════════════
# API publique
# ════════════════════════════════════════════════════════════════════════════


def detect_primary_id(
    brief_text: Optional[str] = None,
    confirmed_entity: Optional[str] = None,
) -> RoutingDecision:
    """
    Détecte l'identifiant primaire (SIREN > Company Number > LEI) et retourne
    une décision de routage des sources externes.

    Ordre de priorité :
        1. confirmed_entity si elle ressemble à un ID
        2. SIREN dans le brief (signal hard FR)
        3. UK Company Number dans le brief (signal hard UK)
        4. LEI dans le brief (signal hard international)
        5. Pas d'ID → fallback all sources (backward-compat v16.5.72.9)

    Important : la priorité est ÉTABLIE dans cet ordre. Si SIREN ET Company
    Number sont tous deux présents (cas D04), le SIREN gagne (hypothèse :
    quand un FR mentionne un SIREN, c'est l'entité principale).
    Note : pour B-cases tests qui veulent CH primary avec ID UK seul, on
    s'assure que pas de SIREN n'est présent dans le brief.
    """
    # 1. Confirmed entity prioritaire si numérique pur
    confirmed_clean = (confirmed_entity or "").strip()
    if confirmed_clean:
        # SIREN ?
        siren = _normalize_siren(confirmed_clean)
        if siren:
            return RoutingDecision(
                use_pappers=True, use_ch=False, use_gleif=True,
                id_type="siren", primary_id=siren,
                rationale=f"siren_confirmed_entity:{siren}",
            )
        # UK Company Number ?
        cn = _normalize_company_number(confirmed_clean)
        if cn:
            return RoutingDecision(
                use_pappers=False, use_ch=True, use_gleif=True,
                id_type="company_number", primary_id=cn,
                rationale=f"company_number_confirmed_entity:{cn}",
            )

    text = (brief_text or "")

    # 2. SIREN dans le brief (priorité 1 — signal hard FR)
    # v17.1-B2.3.4 — si PLUSIEURS SIREN, prendre la CIBLE (role resolver), pas le
    # 1er : sinon le diagnostic de routage affiche le SIREN du sponsor (FDE) alors
    # que l'entité primaire résolue est la cible (Lhyfe). Aligne id_router sur la
    # résolution sponsor/cible de pappers_tool. Fail-open sur le 1er SIREN.
    _sirens: list = []
    _seen: set = set()
    for m in _RE_SIREN_HARD.finditer(text):
        s = _normalize_siren(m.group(1))
        if s and s not in _seen:
            _seen.add(s)
            _sirens.append(s)
    if _sirens:
        primary_siren = _sirens[0]
        if len(_sirens) > 1:
            try:
                from patches.entity_role_resolver import role_adjusted_primary
                _rp, _roles = role_adjusted_primary(_sirens, text, {})
                if _rp in _sirens:
                    primary_siren = _rp
            except Exception:
                pass
        return RoutingDecision(
            use_pappers=True, use_ch=False, use_gleif=True,
            id_type="siren", primary_id=primary_siren,
            rationale=f"siren_detected:{primary_siren}",
        )

    # 3. UK Company Number dans le brief (priorité 2 — signal hard UK)
    for m in _RE_COMPANY_NUMBER_HARD.finditer(text):
        cn = _normalize_company_number(m.group(1))
        if cn:
            return RoutingDecision(
                use_pappers=False, use_ch=True, use_gleif=True,
                id_type="company_number", primary_id=cn,
                rationale=f"company_number_detected:{cn}",
            )

    # 4. LEI dans le brief (priorité 3 — signal international)
    for m in _RE_LEI.finditer(text):
        lei = m.group(1).upper()
        return RoutingDecision(
            use_pappers=False, use_ch=False, use_gleif=True,
            id_type="lei", primary_id=lei,
            rationale=f"lei_detected:{lei}",
        )

    # 5. Pas d'ID → fallback comportement v16.5.72.9 (backward-compat)
    return RoutingDecision(
        use_pappers=True, use_ch=True, use_gleif=True,
        id_type="none", primary_id=None,
        rationale="no_id_detected_fallback_all_sources",
    )


def route_summary_for_diagnostic(decision: RoutingDecision) -> str:
    """
    Retourne un résumé court pour affichage diagnostic DOCX/CSV.

    Exemples :
        "siren:310612387 → Pappers (CH skipped)"
        "company_number:03458224 → Companies House (Pappers skipped)"
        "lei:213800XYZ... → GLEIF only"
        "no_id → all sources (fallback)"
    """
    sources_used = []
    if decision.use_pappers:
        sources_used.append("Pappers")
    if decision.use_ch:
        sources_used.append("CH")
    if decision.use_gleif:
        sources_used.append("GLEIF")

    sources_skipped = []
    if not decision.use_pappers:
        sources_skipped.append("Pappers")
    if not decision.use_ch:
        sources_skipped.append("CH")

    if decision.id_type == "none":
        return "no_id → all sources (fallback)"

    sources_str = "+".join(sources_used) if sources_used else "none"
    skipped_str = f" ({', '.join(sources_skipped)} skipped)" if sources_skipped else ""

    if decision.id_type == "siren":
        return f"siren:{decision.primary_id} → {sources_str}{skipped_str}"
    elif decision.id_type == "company_number":
        return f"company_number:{decision.primary_id} → {sources_str}{skipped_str}"
    elif decision.id_type == "lei":
        return f"lei:{decision.primary_id[:12]}... → {sources_str}{skipped_str}"
    return f"{decision.id_type} → {sources_str}{skipped_str}"
