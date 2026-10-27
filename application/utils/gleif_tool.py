"""
CoDIR-IA — utils/gleif_tool.py — v16.5.68

Source de données : GLEIF (Global Legal Entity Identifier Foundation)
URL : https://api.gleif.org/api/v1/

Couverture :
  - 2,5 M+ entités juridiques dans le monde (multi-juridictions)
  - Format JSON:API standard
  - Aucune clé requise — accès libre, rate-limit raisonnable
  - Données : raison sociale, juridiction, statut, adresse siège, parent légal

Cas d'usage CoDIR-IA :
  - Identifier la structure légale d'un groupe multi-pays
  - Vérifier que l'entité analysée existe légalement (lutte anti-fraude)
  - Récupérer le LEI parent pour cartographier les holdings internationales
  - Compléter Pappers (FR-only) sur les filiales/maisons-mères hors France

Architecture :
  - Cache disque ExternalSourceCache (TTL 30 jours — données très stables)
  - Extraction LEI prioritaire depuis le brief (court-circuit recherche par nom)
  - Recherche par nom si pas de LEI (1 appel API par session)
  - Format dual : full (Stratégie/DG/Synthèse) + summary (autres rôles)
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional, Dict, List, Any

from .external_sources_common import (
    ExternalSourceCache,
    safe_get,
    now_iso,
    save_test_result,
    DEFAULT_TIMEOUT_S,
)


# ── Constantes ────────────────────────────────────────────────────────────────

GLEIF_BASE_URL = "https://api.gleif.org/api/v1"
_REQUEST_TIMEOUT = DEFAULT_TIMEOUT_S
_TTL_RECORD = 30 * 24 * 3600   # 30 jours — LEI très stables
_MAX_RESULTS_BY_NAME = 5

# LEI témoin pour les tests de connexion : Apple Inc. (très stable)
_LEI_HEALTHCHECK = "HWUPKR0MPOU8FGXBT394"

# Pattern LEI : 20 caractères alphanumériques, format ISO 17442
# Structure documentaire : 4 chars (LOU prefix) + 2 chars (réservés, souvent "00")
# + 12 chars (entity ID) + 2 chars (checksum).
# En pratique, certains LEIs anciens n'ont pas "00" en positions 5-6 (ex. Apple HWUP**KR**0M...),
# donc on accepte 18 alphanumeric + 2 digits, et on s'en remet à la checksum Mod-97-10
# pour valider l'authenticité (is_valid_lei).
_RE_LEI = re.compile(r"\b([A-Z0-9]{18}[0-9]{2})\b")

# Niveaux de confiance du matching (cohérent avec pappers_tool)
CONFIDENCE_LEI_DIRECT     = "LEI_DIRECT"      # LEI 20 chars trouvé dans le brief
CONFIDENCE_NAME_EXACT     = "NAME_EXACT"      # Recherche par nom — match exact
CONFIDENCE_NAME_FUZZY     = "NAME_FUZZY"      # Recherche par nom — premier résultat
CONFIDENCE_NOT_FOUND      = "NOT_FOUND"       # Aucun résultat


# ── Cache disque ──────────────────────────────────────────────────────────────

_cache = ExternalSourceCache("gleif_cache.json", ttl_default=_TTL_RECORD)


# ── Log de résolution audit-ready ────────────────────────────────────────────

@dataclass
class GleifResolutionLog:
    """Trace audit-ready de la résolution GLEIF pour une session."""
    input_preview: str = ""
    path: str = ""              # LEI_DIRECT | NAME_EXACT | NAME_FUZZY | NOT_FOUND | SKIPPED
    source: str = ""            # BRIEF_LEI | NAME_SEARCH | EMPTY
    lei_used: str = ""
    primary_name: str = ""
    primary_country: str = ""
    cache_hit: bool = False
    cache_age_h: Optional[float] = None
    tokens_est_full: int = 0
    tokens_est_summary: int = 0
    timestamp: str = field(default_factory=now_iso)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def summary_line(self) -> str:
        """One-liner pour les logs."""
        if self.error:
            return f"gleif_resolution | path={self.path} | error={self.error[:80]}"
        return (f"gleif_resolution | path={self.path} | source={self.source} | "
                f"lei={self.lei_used or '—'} | name={(self.primary_name or '—')[:40]} | "
                f"country={self.primary_country or '—'} | cache_hit={self.cache_hit}")


# ── Validation LEI (checksum ISO 17442 / Mod-97-10) ──────────────────────────

def is_valid_lei(lei: str) -> bool:
    """
    Vérifie qu'un LEI est syntaxiquement valide (format + checksum Mod-97-10).
    LEI = 20 chars alphanumériques. La checksum est calculée sur les 18 premiers,
    avec les 2 derniers chars représentant la checksum.

    Référence : ISO 17442:2020 — voir https://www.gleif.org/en/about-lei/iso-17442
    """
    if not lei or len(lei) != 20:
        return False
    lei = lei.upper()
    if not re.fullmatch(r"[A-Z0-9]{18}\d{2}", lei):
        return False
    # Convertir lettres en chiffres : A=10, B=11, ..., Z=35
    numeric = "".join(str(ord(c) - 55) if c.isalpha() else c for c in lei)
    try:
        return int(numeric) % 97 == 1
    except ValueError:
        return False


# ── Extraction LEI depuis brief ──────────────────────────────────────────────

def _extract_lei_from_text(text: str) -> Optional[str]:
    """
    Extrait le premier LEI valide trouvé dans le texte.
    Priorité : pattern matche + checksum valide.
    """
    if not text:
        return None
    for m in _RE_LEI.finditer(text):
        candidate = m.group(1)
        if is_valid_lei(candidate):
            return candidate
    return None


# ── Appels API (cachés) ──────────────────────────────────────────────────────

@lru_cache(maxsize=64)
def _fetch_by_lei(lei: str) -> Dict[str, Any]:
    """
    Récupère une fiche LEI par identifiant exact.
    Cache disque 30 jours + lru_cache intra-session.

    Retourne un dict {} si non trouvé ou erreur, ou la fiche brute GLEIF.
    """
    lei = lei.upper().strip()
    if not is_valid_lei(lei):
        return {}

    cache_key = f"lei_{lei}"
    cached = _cache.get(cache_key)
    if cached is not None:
        cached["_from_cache"] = True
        cached["_cache_age_h"] = _cache.age_hours(cache_key)
        return cached

    res = safe_get(
        f"{GLEIF_BASE_URL}/lei-records/{lei}",
        timeout=_REQUEST_TIMEOUT,
    )
    if not res.get("ok"):
        if res.get("status_code") == 404:
            return {"_not_found": True}
        return {"_error": res.get("error", "unknown"), "_message": res.get("message", "")}

    data = res.get("data", {})
    if isinstance(data, dict) and "data" in data:
        # JSON:API : la fiche est sous data.data
        record = data["data"]
        if isinstance(record, dict):
            _cache.set(cache_key, record)
            return record
    return {}


def _search_by_name(name: str, max_results: int = _MAX_RESULTS_BY_NAME) -> List[Dict[str, Any]]:
    """
    Recherche LEI par raison sociale (nom de l'entité).
    Pas caché car les résultats peuvent évoluer (nouvelles entités enregistrées).
    Retourne une liste de records LEI (peut être vide).
    """
    if not name or len(name.strip()) < 3:
        return []

    res = safe_get(
        f"{GLEIF_BASE_URL}/lei-records",
        params={
            "filter[entity.legalName]": name.strip(),
            "page[size]": str(min(max_results, 10)),
        },
        timeout=_REQUEST_TIMEOUT,
    )
    if not res.get("ok"):
        return []
    data = res.get("data", {})
    if not isinstance(data, dict):
        return []
    records = data.get("data", [])
    return records if isinstance(records, list) else []


# ── Extraction de champs de la fiche GLEIF (JSON:API) ────────────────────────

def _get_attr(record: Dict[str, Any], path: str, default: str = "") -> str:
    """
    Helper : extrait un champ via chemin pointé "entity.legalName".
    GLEIF utilise JSON:API : record["attributes"][...].
    """
    if not isinstance(record, dict):
        return default
    obj = record.get("attributes", {})
    if not isinstance(obj, dict):
        return default
    for key in path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(key, default)
        else:
            return default
    return str(obj) if obj is not None else default


def _format_address(addr: Dict[str, Any]) -> str:
    """Formate une adresse GLEIF en une ligne lisible."""
    if not isinstance(addr, dict):
        return ""
    parts = []
    line1 = addr.get("addressLines", [])
    if isinstance(line1, list) and line1:
        parts.append(", ".join(str(x) for x in line1 if x))
    city = addr.get("city", "")
    region = addr.get("region", "")
    postal = addr.get("postalCode", "")
    country = addr.get("country", "")
    loc = " ".join(p for p in [postal, city] if p)
    if loc:
        parts.append(loc)
    if region:
        parts.append(region)
    if country:
        parts.append(country)
    return " — ".join(parts)


# ── Format pour injection dans prompt agent ──────────────────────────────────

_LABELS = {
    "fr": {
        "header_full":     "DONNÉES GLEIF — IDENTIFIANT D'ENTITÉ JURIDIQUE (LEI)",
        "header_summary":  "GLEIF — CONTEXTE LÉGAL (résumé)",
        "footer":          "Source : Global Legal Entity Identifier Foundation (api.gleif.org). LEI = identifiant légal mondial ISO 17442.",
        "lei":             "LEI",
        "legal_name":      "Raison sociale légale",
        "other_names":     "Autres dénominations",
        "legal_form":      "Forme juridique",
        "country":         "Juridiction",
        "status":          "Statut LEI",
        "registration":    "Statut d'enregistrement",
        "headquarters":    "Adresse siège",
        "legal_address":   "Adresse légale",
        "parent_lei":      "LEI parent direct",
        "ultimate_parent": "LEI parent ultime",
        "next_renewal":    "Prochain renouvellement",
        "not_found":       "Aucune entité trouvée pour cette recherche",
        "no_input":        "Aucun LEI ni nom détecté pour requête GLEIF",
    },
    "en": {
        "header_full":     "GLEIF DATA — LEGAL ENTITY IDENTIFIER (LEI)",
        "header_summary":  "GLEIF — LEGAL CONTEXT (summary)",
        "footer":          "Source: Global Legal Entity Identifier Foundation (api.gleif.org). LEI = ISO 17442 worldwide legal identifier.",
        "lei":             "LEI",
        "legal_name":      "Legal name",
        "other_names":     "Other names",
        "legal_form":      "Legal form",
        "country":         "Jurisdiction",
        "status":          "LEI status",
        "registration":    "Registration status",
        "headquarters":    "Headquarters address",
        "legal_address":   "Legal address",
        "parent_lei":      "Direct parent LEI",
        "ultimate_parent": "Ultimate parent LEI",
        "next_renewal":    "Next renewal",
        "not_found":       "No entity found for this search",
        "no_input":        "No LEI nor name detected for GLEIF query",
    },
}


def _t(key: str, lang: str) -> str:
    return _LABELS.get(lang, _LABELS["en"]).get(key, key)


def _format_record(record: Dict[str, Any], lang: str = "fr", scope: str = "full") -> str:
    """
    Formate un record GLEIF en texte structuré pour injection dans prompt agent.
    scope ∈ {full, summary}.
    """
    if not record or not isinstance(record, dict):
        return ""

    legal_name   = _get_attr(record, "entity.legalName.name") or _get_attr(record, "entity.legalName")
    legal_form   = _get_attr(record, "entity.legalForm.id") or _get_attr(record, "entity.legalForm")
    country      = _get_attr(record, "entity.legalAddress.country") or _get_attr(record, "entity.jurisdiction")
    status       = _get_attr(record, "entity.status")
    lei_id       = record.get("id", "") or _get_attr(record, "lei")
    next_renew   = _get_attr(record, "registration.nextRenewalDate")[:10]
    reg_status   = _get_attr(record, "registration.status")

    # Adresses (GLEIF stocke headquartersAddress et legalAddress)
    attrs = record.get("attributes", {}) if isinstance(record, dict) else {}
    entity = attrs.get("entity", {}) if isinstance(attrs, dict) else {}
    hq_addr      = _format_address(entity.get("headquartersAddress", {})) if isinstance(entity, dict) else ""
    legal_addr   = _format_address(entity.get("legalAddress", {})) if isinstance(entity, dict) else ""

    # Header bilingue selon scope
    header = _t("header_summary" if scope == "summary" else "header_full", lang)
    lines = [header, ""]
    lines.append(f"{_t('lei', lang)} : {lei_id}")
    if legal_name:
        lines.append(f"{_t('legal_name', lang)} : {legal_name}")
    if country:
        lines.append(f"{_t('country', lang)} : {country}")
    if scope == "full":
        if legal_form:
            lines.append(f"{_t('legal_form', lang)} : {legal_form}")
        if status:
            lines.append(f"{_t('status', lang)} : {status}")
        if reg_status:
            lines.append(f"{_t('registration', lang)} : {reg_status}")
        if hq_addr:
            lines.append(f"{_t('headquarters', lang)} : {hq_addr}")
        if legal_addr and legal_addr != hq_addr:
            lines.append(f"{_t('legal_address', lang)} : {legal_addr}")
        if next_renew:
            lines.append(f"{_t('next_renewal', lang)} : {next_renew}")

    lines.append("")
    lines.append(_t("footer", lang))
    return "\n".join(lines).strip()


# ── Entry point principal — appelé par codir_engine ──────────────────────────

def build_gleif_blocks(
    brief_text: str,
    lang: str = "fr",
    confirmed_name: str = "",
    listed_hint: bool = False,
) -> Dict[str, Any]:
    """
    Entry point : extrait LEI ou nom → résout via GLEIF → retourne blocs formatés.

    Retourne :
      {
        "full":            <texte format full pour Stratégie/DG/Synthèse>,
        "summary":         <texte format summary pour autres rôles>,
        "primary":         <raison sociale légale ou ""=,
        "primary_lei":     <LEI ou ""=,
        "primary_country": <country code ou ""=,
        "confidence":      <CONFIDENCE_*>,
        "resolution_log":  <GleifResolutionLog>,
      }

    Si aucun LEI/nom détecté ou si la recherche échoue, retourne des blocs vides
    et confidence=NOT_FOUND. Ne lève jamais d'exception.
    """
    rlog = GleifResolutionLog(input_preview=(brief_text or "")[:120])

    record: Dict[str, Any] = {}
    confidence = CONFIDENCE_NOT_FOUND

    # 1) Priorité absolue : LEI dans le brief
    direct_lei = _extract_lei_from_text(brief_text or "")
    if direct_lei:
        record = _fetch_by_lei(direct_lei)
        if record and not record.get("_not_found") and not record.get("_error"):
            confidence = CONFIDENCE_LEI_DIRECT
            rlog.path = "LEI_DIRECT"
            rlog.source = "BRIEF_LEI"
            rlog.lei_used = direct_lei
            rlog.cache_hit = bool(record.get("_from_cache"))
            rlog.cache_age_h = record.get("_cache_age_h")
        else:
            rlog.error = "lei_in_brief_but_no_record"

    # 2) Sinon : recherche par nom (confirmed_name prioritaire)
    if confidence == CONFIDENCE_NOT_FOUND:
        search_name = (confirmed_name or "").strip()
        if not search_name:
            # Pas d'extraction Claude pour rester simple — Pappers fait déjà ce travail.
            # Si confirmed_name vide, on n'appelle pas GLEIF.
            rlog.path = "NOT_FOUND"
            rlog.source = "EMPTY"
            return {
                "full": "", "summary": "",
                "primary": "", "primary_lei": "", "primary_country": "",
                "confidence": CONFIDENCE_NOT_FOUND,
                "resolution_log": rlog,
            }

        results = _search_by_name(search_name)
        if results:
            record = results[0]
            # B.1.3 — préférence groupe coté (aligné Companies House) : si le
            # brief signale une cotation, un enregistrement « … GROUP PLC » /
            # « … PLC » portant le nom cherché prime sur le premier hit.
            if listed_hint:
                _tok0 = (search_name.split() or [""])[0].lower()
                for _r in results[:10]:
                    _n = str(_get_attr(_r, "entity.legalName.name")
                             or _get_attr(_r, "entity.legalName") or "").strip()
                    if (_n and _n.lower().endswith(" plc")
                            and _tok0 and _tok0 in _n.lower()):
                        record = _r
                        break
            # Heuristique exact match
            first_name = _get_attr(record, "entity.legalName.name") or _get_attr(record, "entity.legalName")
            if first_name and first_name.strip().lower() == search_name.lower():
                confidence = CONFIDENCE_NAME_EXACT
                rlog.path = "NAME_EXACT"
            else:
                confidence = CONFIDENCE_NAME_FUZZY
                rlog.path = "NAME_FUZZY"
            rlog.source = "NAME_SEARCH"
            rlog.lei_used = record.get("id", "")
        else:
            rlog.path = "NOT_FOUND"
            rlog.source = "NAME_SEARCH"

    # 3) Format des blocs
    if not record or record.get("_not_found") or record.get("_error"):
        return {
            "full": "", "summary": "",
            "primary": "", "primary_lei": "", "primary_country": "",
            "confidence": CONFIDENCE_NOT_FOUND,
            "resolution_log": rlog,
        }

    full_block    = _format_record(record, lang=lang, scope="full")
    summary_block = _format_record(record, lang=lang, scope="summary")
    rlog.tokens_est_full    = len(full_block) // 4
    rlog.tokens_est_summary = len(summary_block) // 4
    rlog.primary_name    = _get_attr(record, "entity.legalName.name") or _get_attr(record, "entity.legalName")
    rlog.primary_country = _get_attr(record, "entity.legalAddress.country") or _get_attr(record, "entity.jurisdiction")

    return {
        "full":            full_block,
        "summary":         summary_block,
        "primary":         rlog.primary_name,
        "primary_lei":     rlog.lei_used,
        "primary_country": rlog.primary_country,
        "confidence":      confidence,
        "resolution_log":  rlog,
    }


# ── Status & test de connexion (pour la page Config) ─────────────────────────

def get_gleif_status() -> Dict[str, Any]:
    """
    Statut GLEIF pour affichage UI. GLEIF n'a pas de clé : toujours "configured".
    """
    return {
        "configured": True,        # GLEIF est toujours accessible (pas de clé)
        "key_preview": "",         # rien à afficher
        "requires_key": False,
    }


def test_connection(timeout: int = _REQUEST_TIMEOUT) -> Dict[str, Any]:
    """
    Test de connexion GLEIF : appelle un LEI témoin (Apple Inc.) et vérifie la
    réponse. Persiste le résultat via save_test_result.

    Retourne :
      {"ok": bool, "message": str, "elapsed_ms": int}
    """
    t0 = time.time()
    res = safe_get(
        f"{GLEIF_BASE_URL}/lei-records/{_LEI_HEALTHCHECK}",
        timeout=timeout,
    )
    elapsed_ms = int((time.time() - t0) * 1000)
    if not res.get("ok"):
        msg = f"{res.get('error', 'unknown')} — {res.get('message', '')[:120]}"
        save_test_result("gleif", ok=False, message=msg)
        return {"ok": False, "message": msg, "elapsed_ms": elapsed_ms}

    # Vérifier qu'on a bien le record d'Apple
    data = res.get("data", {})
    record = data.get("data", {}) if isinstance(data, dict) else {}
    legal_name = ""
    if isinstance(record, dict):
        legal_name = _get_attr(record, "entity.legalName.name") or _get_attr(record, "entity.legalName")
    if "apple" in legal_name.lower():
        msg = f"OK — healthcheck Apple Inc. (LEI {_LEI_HEALTHCHECK}) en {elapsed_ms}ms"
        save_test_result("gleif", ok=True, message=msg)
        return {"ok": True, "message": msg, "elapsed_ms": elapsed_ms}
    else:
        msg = f"Réponse 200 mais format inattendu (legal_name=«{legal_name[:40]}»)"
        save_test_result("gleif", ok=False, message=msg)
        return {"ok": False, "message": msg, "elapsed_ms": elapsed_ms}


__all__ = [
    "GLEIF_BASE_URL",
    "CONFIDENCE_LEI_DIRECT",
    "CONFIDENCE_NAME_EXACT",
    "CONFIDENCE_NAME_FUZZY",
    "CONFIDENCE_NOT_FOUND",
    "GleifResolutionLog",
    "is_valid_lei",
    "build_gleif_blocks",
    "get_gleif_status",
    "test_connection",
]
