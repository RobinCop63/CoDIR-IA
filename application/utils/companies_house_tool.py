"""
CoDIR-IA — utils/companies_house_tool.py — v16.5.68

Source de données : UK Companies House
URL : https://api.company-information.service.gov.uk/

Couverture :
  - Toutes les sociétés enregistrées au Royaume-Uni (LSE et non cotées)
  - ~5 M+ entités (actives + dissoutes)
  - Données : numéro de société, nom, statut, adresse, date d'incorporation,
    type de société, SIC codes, accounts dates, dirigeants
  - **Clé API requise** — gratuite, 600 req/5min

Cas d'usage CoDIR-IA :
  - Identifier la structure légale d'une société UK (cas dossier anglophone coté, Rolls-Royce, etc.)
  - Compléter Pappers (FR-only) et GLEIF (LEI seulement) sur les filiales/maisons-mères UK
  - Vérifier le statut d'enregistrement (active / dissolved / liquidation)
  - Récupérer les SIC codes (équivalent NAF UK)

Architecture :
  - Cache disque ExternalSourceCache (TTL 7 jours)
  - Extraction company number prioritaire depuis le brief (8 chiffres ou format SC/NI)
  - Recherche par nom si pas de numéro
  - Format dual : full / summary

Sécurité :
  - Refus si pas de clé
  - Auth Basic : la clé API est utilisée comme username, password vide
"""

from __future__ import annotations

import os
import re
import time
from base64 import b64encode
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from typing import Optional, Dict, List, Any

from .external_sources_common import (
    safe_get_bytes,
    ExternalSourceCache,
    safe_get,
    now_iso,
    save_test_result,
    make_key_preview,
    DEFAULT_TIMEOUT_S,
)


# ── Constantes ────────────────────────────────────────────────────────────────

CH_BASE_URL = "https://api.company-information.service.gov.uk"
_REQUEST_TIMEOUT = DEFAULT_TIMEOUT_S
_TTL_PROFILE     = 7 * 24 * 3600    # 7 jours
_TTL_SEARCH      = 3 * 24 * 3600    # 3 jours
_DEFAULT_LIMIT   = 5

# v62.13.9.4.4 — numéro de société témoin du healthcheck : configuration (donnée), pas code.
def _cn_healthcheck_number() -> str:
    import json as _json
    import os as _os
    try:
        path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "config", "external_checks.json")
        with open(path, "r", encoding="utf-8") as handle:
            return str(_json.load(handle).get("companies_house_healthcheck_number") or "").strip()
    except Exception:
        return ""


_CN_HEALTHCHECK = _cn_healthcheck_number()

# Pattern numéro CH : 8 chiffres, ou préfixe SC (Scotland), NI (Northern Ireland), OC (LLP), etc.
# Avec préfixe : 5 à 8 chiffres tolérés (padding au moment de la normalisation)
# Sans préfixe : 6 à 8 chiffres
_RE_COMPANY_NUMBER = re.compile(
    r"\b(?:Companies?\s*House\s*(?:number|n°|no\.?)?\s*[:#]?\s*)?"
    r"((?:SC|NI|OC|SO|R|GE|FC|GS|LP|NL|RC|SF|SL|SR|SZ)?\s*\d{5,8})\b",
    re.IGNORECASE,
)
# Forme stricte : avec préfixe accepte 5-8 chiffres ; sans préfixe 6-8
_RE_CN_STRICT = re.compile(r"^([A-Z]{2})(\d{5,8})$|^()(\d{6,8})$", re.IGNORECASE)

# Niveaux de confiance
CONFIDENCE_NUMBER_DIRECT = "NUMBER_DIRECT"
CONFIDENCE_NAME_EXACT    = "NAME_EXACT"
CONFIDENCE_NAME_FUZZY    = "NAME_FUZZY"
CONFIDENCE_NOT_FOUND     = "NOT_FOUND"
try:  # B.1.3.13 — formes cotées en DONNÉES, diagnostics seulement
    from patches.listed_forms import annotate_candidates as _lf_annotate
    from patches.listed_forms import strong_nonplc_present as _lf_tripwire
except Exception:  # module absent : zéro impact résolution
    _lf_annotate = None
    _lf_tripwire = None

CONFIDENCE_NOT_CONFIGURED = "NOT_CONFIGURED"


# ── Cache disque ──────────────────────────────────────────────────────────────

_cache_profile = ExternalSourceCache("companies_house_profile_cache.json", ttl_default=_TTL_PROFILE)
_cache_search  = ExternalSourceCache("companies_house_search_cache.json",  ttl_default=_TTL_SEARCH)


# ── Log de résolution audit-ready ────────────────────────────────────────────

@dataclass
class CompaniesHouseResolutionLog:
    """Trace audit-ready de la résolution Companies House."""
    input_preview: str = ""
    path: str = ""              # NUMBER_DIRECT | NAME_* | NOT_FOUND | NOT_CONFIGURED
    source: str = ""            # BRIEF_NUMBER | NAME_SEARCH | EMPTY | NO_KEY
    company_number: str = ""
    primary_name: str = ""
    primary_status: str = ""
    company_type: str = ""
    cache_hit: bool = False
    cache_age_h: Optional[float] = None
    tokens_est_full: int = 0
    tokens_est_summary: int = 0
    timestamp: str = field(default_factory=now_iso)
    error: str = ""
    research: str = ""  # B.1.3.8 — trace de la re-recherche coté (requêtes, n, top, exc)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def summary_line(self) -> str:
        if self.error:
            return f"companies_house | path={self.path} | error={self.error[:80]}"
        return (f"companies_house | path={self.path} | source={self.source} | "
                f"cn={self.company_number or '—'} | name={(self.primary_name or '—')[:40]} | "
                f"status={self.primary_status or '—'} | cache_hit={self.cache_hit}")


# ── Clé API ──────────────────────────────────────────────────────────────────

def _api_key() -> str:
    return (os.getenv("COMPANIES_HOUSE_API_KEY") or "").strip()


def _headers() -> Dict[str, str]:
    """
    Headers Companies House : Auth Basic avec clé en username, password vide.
    Header Authorization: Basic base64(api_key:)
    """
    key = _api_key()
    if not key:
        return {}
    token = b64encode(f"{key}:".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


# ── Normalisation numéro de société ──────────────────────────────────────────

def _normalize_company_number(raw: str) -> Optional[str]:
    """
    Normalise un numéro CH : conserve les préfixes (SC, NI, OC, etc.) et pad les chiffres.
    Retourne None si format invalide.

    Règles :
      - Sans préfixe : doit avoir 6-8 chiffres → padded à 8
      - Avec préfixe : doit avoir 5-8 chiffres → padded à 6 (forme finale = prefix + 6 chiffres)

    Ex.:
      '12345' → None (sans préfixe, trop court)
      '12345678' → '12345678'
      '345678' → '00345678'
      'SC 12345' → 'SC012345'
      'SC12345' → 'SC012345'
      'SC123456' → 'SC123456'
    """
    if not raw:
        return None
    cleaned = re.sub(r"\s+", "", str(raw)).upper()
    m = _RE_CN_STRICT.match(cleaned)
    if not m:
        return None
    # Le regex a 4 groupes : (prefix, digits_with_prefix) | (empty, digits_no_prefix)
    prefix = m.group(1) or m.group(3) or ""
    digits = m.group(2) or m.group(4) or ""
    if not digits:
        return None
    if prefix:
        # Avec préfixe : padding à 6 chiffres
        digits_padded = digits.zfill(6)
    else:
        # Sans préfixe : padding à 8 chiffres
        if len(digits) < 6:
            return None
        digits_padded = digits.zfill(8)
    return f"{prefix}{digits_padded}"


def _extract_company_number_from_text(text: str) -> Optional[str]:
    """Extrait un numéro CH depuis le brief si présent. Retourne le numéro normalisé."""
    if not text:
        return None
    for m in _RE_COMPANY_NUMBER.finditer(text):
        candidate = m.group(1)
        normalized = _normalize_company_number(candidate)
        if normalized:
            return normalized
    return None


# ── Appels API ───────────────────────────────────────────────────────────────

@lru_cache(maxsize=64)
def _fetch_profile(company_number: str) -> Dict[str, Any]:
    """
    Récupère le profil société via /company/{number}.
    Cache disque 7 jours + lru_cache intra-session.
    """
    if not company_number or not _RE_CN_STRICT.match(company_number):
        return {}

    cache_key = f"prof_{company_number}"
    cached = _cache_profile.get(cache_key)
    if cached is not None:
        cached["_from_cache"] = True
        cached["_cache_age_h"] = _cache_profile.age_hours(cache_key)
        return cached

    if not _api_key():
        return {"_error": "no_api_key"}

    res = safe_get(
        f"{CH_BASE_URL}/company/{company_number}",
        headers=_headers(),
        timeout=_REQUEST_TIMEOUT,
    )
    if not res.get("ok"):
        if res.get("status_code") == 404:
            return {"_not_found": True}
        if res.get("status_code") in (401, 403):
            return {"_error": "auth_refused", "_message": res.get("message", "")[:120]}
        return {"_error": res.get("error", "unknown"), "_message": res.get("message", "")[:120]}

    data = res.get("data", {})
    if isinstance(data, dict) and data.get("company_number"):
        _cache_profile.set(cache_key, data)
        return data
    return {}


def _candidate_has_strong_match(search_name: str, candidate_title: str) -> bool:
    """
    Patch v16.5.69.1 patch session 7 (audit terrain dossier de conseil) — Helper de
    similarité pour fuzzy match strict.

    Bug détecté : "dossier de conseil" (search) vs "HI! AMBASSADORS LIMITED"
    (candidate) → match accepté en fuzzy, alors que ces 2 sociétés n'ont
    aucun rapport. Le seul mot commun "HI!" est trop court et trop générique.

    Critère retenu : au moins **2 mots significatifs** (longueur ≥ 4 chars
    après normalisation, hors mots-arrêts type SASU/LTD/PLC/SA/etc.) doivent
    être communs entre les 2 noms. Évite les faux positifs sur 1 mot court
    partagé tout en restant tolérant aux suffixes corporate / sigles.

    Exemples :
      - "dossier de conseil"        vs "HI! AMBASSADORS LIMITED"    → False (1 mot commun "HI" trop court < 4 chars)
      - "dossier de conseil"        vs "dossier de conseil LTD"            → True  (2+ mots communs)
      - "dossier anglophone coté Group plc"      vs "dossier anglophone coté GROUP PLC"         → True  (matchait via is_exact, ce helper n'est pas appelé)
      - "dossier anglophone coté"                vs "dossier anglophone coté GROUP PLC"         → False (1 seul mot, exigerait ≥2)
                                                                            → conservateur, force confirmation utilisateur
    """
    if not search_name or not candidate_title:
        return False

    # Mots-arrêts corporate (sigles juridiques, prefixes, articles)
    STOP_WORDS = {
        "sas", "sasu", "sa", "sarl", "eurl", "snc", "scs", "sca",
        "ltd", "limited", "plc", "llc", "inc", "corp", "corporation",
        "gmbh", "ag", "bv", "kg", "oy", "ab", "as",
        "the", "le", "la", "les", "de", "du", "des",
        "and", "et", "&",
        "co", "cie", "company",
        "group", "groupe", "holding", "holdings",
    }

    def _normalize_words(s: str) -> set:
        # Retirer ponctuation, lower, split, filtrer mots significatifs (≥4 chars hors stop)
        import re as _re
        s_clean = _re.sub(r"[^\w\s]", " ", s.lower())
        words = s_clean.split()
        return {w for w in words if len(w) >= 4 and w not in STOP_WORDS}

    search_words = _normalize_words(search_name)
    candidate_words = _normalize_words(candidate_title)

    if not search_words or not candidate_words:
        return False

    # Au moins 2 mots significatifs en commun
    # Si le search_name normalisé n'a qu'1 mot significatif, on exige
    # une correspondance exacte de ce mot dans candidate (pas une coïncidence
    # sur un fragment commun).
    common = search_words & candidate_words
    if len(search_words) <= 1:
        # Cas borderline : 1 seul mot significatif dans search → on exige
        # ce mot soit présent ET que candidate n'ait pas plus de 3 mots
        # significatifs (sinon trop de bruit, type "HI! AMBASSADORS LIMITED")
        if not common:
            return False
        return len(candidate_words) <= 3
    return len(common) >= 2


def _search_by_name(name: str, limit: int = _DEFAULT_LIMIT) -> List[Dict[str, Any]]:
    """
    Recherche par nom via /search/companies.
    Cache disque 3 jours.
    """
    if not name or len(name.strip()) < 2:
        return []

    if not _api_key():
        return []

    cache_key = f"search_{name.lower()[:120]}_{limit}"
    cached = _cache_search.get(cache_key)
    if cached is not None:
        return cached

    res = safe_get(
        f"{CH_BASE_URL}/search/companies",
        params={"q": name.strip(), "items_per_page": str(min(limit, 20))},
        headers=_headers(),
        timeout=_REQUEST_TIMEOUT,
    )
    if not res.get("ok"):
        return []

    data = res.get("data", {})
    items = data.get("items", []) if isinstance(data, dict) else []
    if not isinstance(items, list):
        items = []
    _cache_search.set(cache_key, items)
    return items


# ── Format pour injection dans prompt agent ──────────────────────────────────

_LABELS = {
    "fr": {
        "header_full":     "DONNÉES COMPANIES HOUSE — REGISTRE UK",
        "header_summary":  "COMPANIES HOUSE — CONTEXTE UK (résumé)",
        "footer":          "Source : UK Companies House (api.company-information.service.gov.uk). Registre officiel des sociétés britanniques.",
        "name":            "Raison sociale",
        "company_number":  "Numéro de société",
        "status":          "Statut",
        "type":            "Forme juridique",
        "jurisdiction":    "Juridiction",
        "incorporated":    "Date d'incorporation",
        "dissolved":       "Date de dissolution",
        "address":         "Adresse siège",
        "sic_codes":       "Codes SIC",
        "last_accounts":   "Derniers comptes déposés",
        "next_accounts":   "Prochains comptes attendus",
        "no_key":          "⚠️ Companies House non configuré — section non exploitée. Renseigner COMPANIES_HOUSE_API_KEY en page Config.",
        "not_found":       "Aucune entité trouvée pour cette recherche",
    },
    "en": {
        "header_full":     "COMPANIES HOUSE DATA — UK REGISTER",
        "header_summary":  "COMPANIES HOUSE — UK CONTEXT (summary)",
        "footer":          "Source: UK Companies House (api.company-information.service.gov.uk). Official UK companies register.",
        "name":            "Company name",
        "company_number":  "Company number",
        "status":          "Status",
        "type":            "Company type",
        "jurisdiction":    "Jurisdiction",
        "incorporated":    "Date of incorporation",
        "dissolved":       "Date of dissolution",
        "address":         "Registered office address",
        "sic_codes":       "SIC codes",
        "last_accounts":   "Last accounts filed",
        "next_accounts":   "Next accounts due",
        "no_key":          "⚠️ Companies House not configured — section not used. Set COMPANIES_HOUSE_API_KEY on the Config page.",
        "not_found":       "No entity found for this search",
    },
}


def _t(key: str, lang: str) -> str:
    return _LABELS.get(lang, _LABELS["en"]).get(key, key)


def _format_address(addr: Dict[str, Any]) -> str:
    """Formate registered_office_address en une ligne lisible."""
    if not isinstance(addr, dict):
        return ""
    parts = []
    for k in ("address_line_1", "address_line_2"):
        if addr.get(k):
            parts.append(str(addr[k]))
    locality_parts = []
    for k in ("postal_code", "locality", "region"):
        if addr.get(k):
            locality_parts.append(str(addr[k]))
    if locality_parts:
        parts.append(" ".join(locality_parts))
    if addr.get("country"):
        parts.append(str(addr["country"]))
    return " — ".join(parts)


def _format_profile(profile: Dict[str, Any], lang: str = "fr", scope: str = "full") -> str:
    """Formate un profil Companies House en texte structuré."""
    if not profile or not isinstance(profile, dict):
        return ""

    name           = profile.get("company_name", "")
    company_number = profile.get("company_number", "")
    status         = profile.get("company_status", "")
    company_type   = profile.get("type", "")
    jurisdiction   = profile.get("jurisdiction", "")
    incorporated   = profile.get("date_of_creation", "")[:10]
    dissolved      = profile.get("date_of_cessation", "")[:10] if profile.get("date_of_cessation") else ""
    sic_codes      = profile.get("sic_codes", []) or []
    address        = _format_address(profile.get("registered_office_address", {}))

    accounts       = profile.get("accounts", {}) if isinstance(profile.get("accounts"), dict) else {}
    last_accounts  = (accounts.get("last_accounts", {}) or {}).get("made_up_to", "")[:10]
    next_accounts  = accounts.get("next_due", "")[:10]

    header = _t("header_summary" if scope == "summary" else "header_full", lang)
    lines = [header, ""]
    if name:           lines.append(f"{_t('name', lang)} : {name}")
    if company_number: lines.append(f"{_t('company_number', lang)} : {company_number}")
    if status:         lines.append(f"{_t('status', lang)} : {status}")
    if scope == "full":
        if company_type:  lines.append(f"{_t('type', lang)} : {company_type}")
        if jurisdiction:  lines.append(f"{_t('jurisdiction', lang)} : {jurisdiction}")
        if incorporated:  lines.append(f"{_t('incorporated', lang)} : {incorporated}")
        if dissolved:     lines.append(f"{_t('dissolved', lang)} : {dissolved}")
        if address:       lines.append(f"{_t('address', lang)} : {address}")
        if sic_codes:     lines.append(f"{_t('sic_codes', lang)} : {', '.join(str(c) for c in sic_codes)}")
        if last_accounts: lines.append(f"{_t('last_accounts', lang)} : {last_accounts}")
        if next_accounts: lines.append(f"{_t('next_accounts', lang)} : {next_accounts}")

    lines.append("")
    lines.append(_t("footer", lang))
    return "\n".join(lines).strip()


# ── Entry point principal ────────────────────────────────────────────────────

def _best_listed_plc_candidate(results, base_token: str):
    """ChatGPT B.1.3.8 candidate — robustesse du resolver UK/listed.

    La préférence « listed group » ne doit jamais retenir un candidat dissous
    et doit privilégier le vrai groupe coté quand plusieurs PLC partagent le
    token de marque (ex. dossier anglophone coté PLC dissoute / dossier anglophone coté GROUP PLC active).
    Retourne le meilleur candidat PLC actif, ou None.
    """
    tok = str(base_token or "").strip().lower()
    if not tok:
        return None
    scored = []
    for idx, cand in enumerate((results or [])[:10]):
        if not isinstance(cand, dict):
            continue
        title = str(cand.get("title", "") or "").strip()
        t = title.lower()
        status = str(cand.get("company_status", "") or "").lower()
        if status == "dissolved":
            continue
        if not (t.endswith(" plc") and tok in t and cand.get("company_number")):
            continue
        # Préférence déterministe : <brand> GROUP PLC > tout titre contenant
        # GROUP PLC > <brand> PLC > autre PLC portant le token de marque.
        if re.search(r"\b" + re.escape(tok) + r"\s+group\s+plc\b", t):
            rank = 0
        elif " group plc" in t:
            rank = 1
        elif t == f"{tok} plc":
            rank = 2
        else:
            rank = 3
        scored.append((rank, idx, cand))
    if not scored:
        return None
    return sorted(scored, key=lambda x: (x[0], x[1]))[0][2]


def build_companies_house_blocks(
    brief_text: str,
    lang: str = "fr",
    confirmed_name: str = "",
    listed_hint: bool = False,
) -> Dict[str, Any]:
    """
    Entry point : extrait company number/nom → résout via Companies House → blocs formatés.

    Retourne le même contrat que les autres modules :
      {
        "full": str, "summary": str, "primary": str, "company_number": str,
        "status": str, "confidence": str, "resolution_log": CompaniesHouseResolutionLog,
      }

    Garantie : aucun appel API si clé absente. Ne lève jamais d'exception.
    """
    rlog = CompaniesHouseResolutionLog(input_preview=(brief_text or "")[:120])

    # 1) Garde-fou : clé API requise
    if not _api_key():
        rlog.path = CONFIDENCE_NOT_CONFIGURED
        rlog.source = "NO_KEY"
        rlog.error = "api_key_missing"
        return {
            "full": "", "summary": "",
            "primary": "", "company_number": "", "status": "",
            "confidence": CONFIDENCE_NOT_CONFIGURED,
            "resolution_log": rlog,
        }

    profile: Dict[str, Any] = {}
    confidence = CONFIDENCE_NOT_FOUND

    # 2) Priorité : numéro de société dans le brief
    direct_number = _extract_company_number_from_text(brief_text or "")
    if direct_number:
        profile = _fetch_profile(direct_number)
        if profile and not profile.get("_not_found") and not profile.get("_error"):
            confidence = CONFIDENCE_NUMBER_DIRECT
            rlog.path = "NUMBER_DIRECT"
            rlog.source = "BRIEF_NUMBER"
            rlog.company_number = direct_number
            rlog.cache_hit = bool(profile.get("_from_cache"))
            rlog.cache_age_h = profile.get("_cache_age_h")
        else:
            rlog.error = "number_in_brief_but_no_profile"
            profile = {}

    # 3) Sinon : recherche par nom
    if confidence == CONFIDENCE_NOT_FOUND:
        search_name = (confirmed_name or "").strip()
        if not search_name:
            rlog.path = "NOT_FOUND"
            rlog.source = "EMPTY"
            return {
                "full": "", "summary": "",
                "primary": "", "company_number": "", "status": "",
                "confidence": CONFIDENCE_NOT_FOUND,
                "resolution_log": rlog,
            }

        results = _search_by_name(search_name)
        if results:
            top = results[0]
            # ── B.1.3 (run dossier anglophone coté : LIMITED retenu au lieu de GROUP PLC) ──
            # Quand le brief signale une société COTÉE (Actionnariat : Coté,
            # LSE:, « plc »), un candidat « <NOM> GROUP PLC » ou « <NOM> PLC »
            # portant le nom cherché PRIME sur le premier match exact
            # (souvent une filiale Ltd historique). Traçé dans rlog.path.
            _listed_pref_applied = False
            if listed_hint:
                _sn_low = search_name.lower()
                _tok0_pref = _sn_low.split()[0] if _sn_low.split() else ""
                _cand_pref = _best_listed_plc_candidate(results, _tok0_pref)
                if _cand_pref:
                    if _cand_pref is not top:
                        top = _cand_pref
                    _listed_pref_applied = True
                # B.1.3.5 (run dossier anglophone coté) — la pref ne peut préférer que ce qui
                # est DANS les résultats : quand la recherche part du nom
                # confirmé « dossier anglophone coté LIMITED », aucun « … PLC » n'y figure et
                # path restait NAME_EXACT. Avec hint coté : RE-RECHERCHE
                # « <tok0> plc » avant d'accepter l'exact non coté.
                if not _listed_pref_applied and _sn_low.split():
                    # B.1.3.8 — le run dossier anglophone coté 3.7 a PROUVÉ (hint=True au CSV,
                    # test offline vert) que ce flux est correct : la défaillance
                    # était dans l'échange API réel, AVALÉE sans trace. Désormais
                    # chaque tentative est TRACÉE (rlog.research), on retente
                    # « <tok0> group plc », et les dissoutes sont écartées.
                    _tok0 = _sn_low.split()[0]
                    _research_log = []
                    for _q2 in (f"{_tok0} plc", f"{_tok0} group plc"):
                        if _listed_pref_applied:
                            break
                        try:
                            _res2 = _search_by_name(_q2)
                            _titles_full = [str((c or {}).get("title", ""))
                                            for c in (_res2 or [])[:3]]
                            # B.1.3.14 (watchpoint ChatGPT 3.13) — classer
                            # le titre COMPLET puis tronquer : une forme
                            # forte en fin de dénomination longue ne peut
                            # plus échapper au tripwire.
                            if _lf_tripwire and _lf_tripwire(_titles_full):
                                _research_log.append(
                                    "FORMS: STRONG non-plc candidate seen")
                            if _lf_annotate:
                                _titles = [t[:48] for t in _lf_annotate(_titles_full)]
                            else:
                                _titles = [t[:34] for t in _titles_full]
                            _research_log.append(
                                f"q='{_q2}' n={len(_res2 or [])} top={_titles}")
                            _cand2 = _best_listed_plc_candidate(_res2 or [], _tok0)
                            if _cand2:
                                top = _cand2
                                _listed_pref_applied = True
                                rlog.path = "NAME_LISTED_RESEARCH"
                                _research_log.append(
                                    f"RETAINED={_cand2.get('company_number')}")
                                break
                        except Exception as _e2:
                            _research_log.append(
                                f"q='{_q2}' EXC={type(_e2).__name__}: {str(_e2)[:60]}")
                    rlog.research = " | ".join(_research_log)[:400]
            top_number = top.get("company_number", "")
            if top_number:
                profile = _fetch_profile(top_number)
                if profile and not profile.get("_not_found") and not profile.get("_error"):
                    # Heuristique exact / fuzzy
                    top_name = top.get("title", "")
                    is_exact = top_name and top_name.strip().lower() == search_name.lower()
                    if _listed_pref_applied:
                        # B.1.3 — le candidat coté préféré est traité comme
                        # exact : « dossier anglophone coté GROUP PLC » POUR « dossier anglophone coté ».
                        is_exact = True

                    # Patch v16.5.69.1 patch session 7 (audit terrain dossier de conseil) :
                    # le fuzzy match était trop permissif. Pour le brief dossier de conseil
                    # avec Pappers SIREN_DIRECT confirmé "dossier de conseil", la
                    # recherche par nom CH retournait "HI! AMBASSADORS LIMITED"
                    # comme 1er candidat — match faussement positif sur le mot
                    # commun "HI!". Tous les agents ont ensuite halluciné des
                    # "synergies UK" qui n'existaient pas.
                    #
                    # Correction : si non-exact, exiger qu'AU MOINS 2 mots
                    # significatifs (≥4 chars) soient communs entre le nom
                    # cherché et le nom du candidat. Sinon → NOT_FOUND propre.
                    # Évite les faux positifs sur 1 mot court partagé.
                    if not is_exact:
                        if not _candidate_has_strong_match(search_name, top_name):
                            # Match trop faible — on REFUSE silencieusement
                            rlog.path = "NOT_FOUND"
                            rlog.source = "NAME_SEARCH"
                            rlog.error = "fuzzy_match_too_weak"
                            profile = {}  # invalide profile pour ne pas remonter le bloc
                            confidence = CONFIDENCE_NOT_FOUND
                        else:
                            rlog.company_number = top_number
                            rlog.cache_hit = bool(profile.get("_from_cache"))
                            rlog.cache_age_h = profile.get("_cache_age_h")
                            confidence = CONFIDENCE_NAME_FUZZY
                            rlog.path = "NAME_FUZZY"
                            rlog.source = "NAME_SEARCH"
                    else:
                        rlog.company_number = top_number
                        rlog.cache_hit = bool(profile.get("_from_cache"))
                        rlog.cache_age_h = profile.get("_cache_age_h")
                        confidence = CONFIDENCE_NAME_EXACT
                        # B.1.3.6 (watchpoint audit) — le path COMPOSE au lieu d'écraser :
                        # une re-recherche « <société> plc » reste lisible au log.
                        _p_prev = rlog.path if rlog.path == "NAME_LISTED_RESEARCH" else ""
                        rlog.path = ((_p_prev + "+") if _p_prev else "") + ("NAME_EXACT_LISTED_PREF"
                                     if _listed_pref_applied else "NAME_EXACT")
                        rlog.source = "NAME_SEARCH"
                else:
                    rlog.path = "NOT_FOUND"
                    rlog.source = "NAME_SEARCH"
                    rlog.error = "search_hit_but_no_profile"
        else:
            rlog.path = "NOT_FOUND"
            rlog.source = "NAME_SEARCH"

    # 4) Format
    if not profile or profile.get("_not_found") or profile.get("_error"):
        return {
            "full": "", "summary": "",
            "primary": "", "company_number": rlog.company_number, "status": "",
            "confidence": CONFIDENCE_NOT_FOUND,
            "resolution_log": rlog,
        }

    full_block    = _format_profile(profile, lang=lang, scope="full")
    summary_block = _format_profile(profile, lang=lang, scope="summary")
    rlog.tokens_est_full    = len(full_block) // 4
    rlog.tokens_est_summary = len(summary_block) // 4
    rlog.primary_name    = profile.get("company_name", "")
    rlog.primary_status  = profile.get("company_status", "")
    rlog.company_type    = profile.get("type", "")

    return {
        "full":            full_block,
        "summary":         summary_block,
        "primary":         rlog.primary_name,
        "company_number":  rlog.company_number,
        "status":          rlog.primary_status,
        "confidence":      confidence,
        "resolution_log":  rlog,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PREVIEW — Since v16.5.69 (confirmation utilisateur sur fuzzy match)
# ─────────────────────────────────────────────────────────────────────────────
# Pattern inspiré de preview_pappers_detection : ChatGPT avait raison de pointer
# que prendre silencieusement le premier résultat sur un match nom-fuzzy était
# dangereux en usage pro (ex. "dossier anglophone coté" vs "dossier anglophone coté Holdings" vs "dossier anglophone coté UK Ltd").
#
# Stratégie :
#   - NUMBER_DIRECT (CN dans le brief) → pas de preview, on prend le profil direct
#   - NAME_EXACT (1er match titre = nom confirmé exact) → pas de preview, fiable
#   - Match fuzzy ou ambigu → preview avec liste candidats pour confirmation UI
#
# La UI "Confirmer la cible cross-juridiction" v16.5.69 consomme cette preview
# pour proposer N candidats CH au lieu de prendre silencieusement le premier.

def preview_companies_house_detection(
    brief: str,
    lang: str = "fr",
    confirmed_name: str = "",
    max_candidates: int = 5,
) -> Dict[str, Any]:
    """
    Preview de résolution Companies House SANS appel à fetch_profile pour
    chaque candidat — économique en quota.

    Stratégie :
      1. Si CN détecté dans le brief → preview "direct", confidence_hint=NUMBER_DIRECT,
         un seul candidat
      2. Si confirmed_name fourni → recherche /search/companies, retourne jusqu'à
         max_candidates candidats avec : name, number, status, address, date.
         Si premier résultat = match exact (titre normalisé == nom normalisé) →
         confidence_hint=NAME_EXACT, sinon NAME_FUZZY.
      3. Sinon → "active": False, pas de candidats

    Retour :
      {
        "active": bool,
        "preview_method": "number_direct" | "name_search" | "skipped",
        "confidence_hint": "NUMBER_DIRECT" | "NAME_EXACT" | "NAME_FUZZY" | "NOT_FOUND",
        "candidates": [
            {"company_number": str, "title": str, "status": str,
             "address": str, "date_of_creation": str, "company_type": str}
        ],
        "auto_confirm_safe": bool,  # True ssi NUMBER_DIRECT ou NAME_EXACT (pas besoin UI)
      }

    Garantie : ne lève jamais d'exception, retourne dict cohérent même sans clé.
    """
    result: Dict[str, Any] = {
        "active": False,
        "preview_method": "skipped",
        "confidence_hint": "NOT_FOUND",
        "candidates": [],
        "auto_confirm_safe": False,
    }

    if not _api_key():
        return result

    # 1. CN direct dans le brief
    direct_number = _extract_company_number_from_text(brief or "")
    if direct_number:
        # Récupérer le profil pour vérifier que le CN existe
        profile = _fetch_profile(direct_number)
        if profile and not profile.get("_not_found") and not profile.get("_error"):
            result.update({
                "active": True,
                "preview_method": "number_direct",
                "confidence_hint": "NUMBER_DIRECT",
                "auto_confirm_safe": True,  # CN direct = fiable, pas besoin UI
                "candidates": [{
                    "company_number":    profile.get("company_number", direct_number),
                    "title":             profile.get("company_name", ""),
                    "status":            profile.get("company_status", ""),
                    "address":           _format_address(profile.get("registered_office_address", {})),
                    "date_of_creation":  profile.get("date_of_creation", "")[:10],
                    "company_type":      profile.get("type", ""),
                }],
            })
            return result

    # 2. Recherche par nom
    name = (confirmed_name or "").strip()
    if not name or len(name) < 2:
        return result

    items = _search_by_name(name, limit=max_candidates)
    if not items:
        result.update({
            "active": True,
            "preview_method": "name_search",
            "confidence_hint": "NOT_FOUND",
        })
        return result

    candidates: List[Dict[str, Any]] = []
    for it in items[:max_candidates]:
        candidates.append({
            "company_number":   it.get("company_number", ""),
            "title":            it.get("title", ""),
            "status":           it.get("company_status", ""),
            # Le résultat /search/companies renvoie une address abrégée
            "address":          (it.get("address_snippet", "") or
                                 _format_address(it.get("registered_office_address", {}))),
            "date_of_creation": (it.get("date_of_creation", "") or "")[:10],
            "company_type":     it.get("company_type", ""),
        })

    # Heuristique exact match : titre normalisé du 1er résultat == nom confirmé normalisé
    first_title = (candidates[0].get("title", "") or "").strip().lower()
    name_lower  = name.lower()
    is_exact = (first_title == name_lower)

    result.update({
        "active": True,
        "preview_method": "name_search",
        "confidence_hint": "NAME_EXACT" if is_exact else "NAME_FUZZY",
        "candidates": candidates,
        # NAME_EXACT seul candidat = safe ; NAME_EXACT + autres candidats = on demande quand même
        "auto_confirm_safe": (is_exact and len(candidates) == 1),
    })
    return result


# ── Status & test de connexion ───────────────────────────────────────────────

def get_companies_house_status() -> Dict[str, Any]:
    """Statut Companies House pour la page Config."""
    key = _api_key()
    return {
        "configured":   bool(key),
        "key_preview":  make_key_preview(key),
        "requires_key": True,
    }


def test_connection(timeout: int = _REQUEST_TIMEOUT) -> Dict[str, Any]:
    """
    Test de connexion Companies House : appelle le profil du numéro témoin
    configuré dans config/external_checks.json et vérifie la réponse.
    Aucun numéro configuré = healthcheck désactivé (distribution neutre).
    """
    if not _CN_HEALTHCHECK:
        msg = ("Healthcheck Companies House désactivé — aucun numéro témoin "
               "configuré (config/external_checks.json).")
        save_test_result("companies_house", ok=True, message=msg)
        return {"ok": True, "message": msg, "elapsed_ms": 0, "disabled": True}
    if not _api_key():
        msg = "Clé Companies House absente — saisir COMPANIES_HOUSE_API_KEY dans Config."
        save_test_result("companies_house", ok=False, message=msg)
        return {"ok": False, "message": msg, "elapsed_ms": 0}

    t0 = time.time()
    res = safe_get(
        f"{CH_BASE_URL}/company/{_CN_HEALTHCHECK}",
        headers=_headers(),
        timeout=timeout,
    )
    elapsed_ms = int((time.time() - t0) * 1000)

    if not res.get("ok"):
        sc = res.get("status_code", "")
        if sc in (401, 403):
            msg = f"Authentification refusée (HTTP {sc}) — vérifier la clé API."
        else:
            msg = f"{res.get('error', 'unknown')} — {res.get('message', '')[:120]}"
        save_test_result("companies_house", ok=False, message=msg)
        return {"ok": False, "message": msg, "elapsed_ms": elapsed_ms}

    data = res.get("data", {})
    name = data.get("company_name", "") if isinstance(data, dict) else ""
    if name.strip():  # v62.13.9.4.4 — connectivité validée : la fiche du numéro témoin répond
        msg = f"OK — healthcheck Companies House (CN {_CN_HEALTHCHECK}) en {elapsed_ms}ms"
        save_test_result("companies_house", ok=True, message=msg)
        return {"ok": True, "message": msg, "elapsed_ms": elapsed_ms}
    msg = f"Réponse 200 mais format inattendu (name=«{name[:40]}»)"
    save_test_result("companies_house", ok=False, message=msg)
    return {"ok": False, "message": msg, "elapsed_ms": elapsed_ms}


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENT API — Since v16.5.68
# ─────────────────────────────────────────────────────────────────────────────
# Companies House expose une 2e API totalement séparée pour le téléchargement
# des documents (filings PDF / XHTML). Elle nécessite une clé distincte créée
# côté Developer Hub comme une autre application.
#
# Architecture :
#   1. fetch_filing_history(cn)         — Public Data API → liste des filings
#   2. fetch_document_metadata(doc_id)  — Document API   → métadonnées + formats
#   3. fetch_document_content(doc_id)   — Document API   → bytes du document
#
# Sécurité : la clé Document est strictement séparée. Si elle est absente,
# uniquement les étapes (2) et (3) sont bloquées ; (1) reste possible avec
# la clé Public Data.

CH_DOCUMENT_BASE_URL = "https://document-api.company-information.service.gov.uk"
_TTL_FILING_HISTORY = 3 * 24 * 3600    # 3 jours — l'historique évolue avec les nouveaux filings
_TTL_DOCUMENT_META  = 30 * 24 * 3600   # 30 jours — les métadonnées d'un filing existant ne changent pas
_MAX_FILING_ITEMS   = 25

_cache_filings    = ExternalSourceCache("companies_house_filings_cache.json", ttl_default=_TTL_FILING_HISTORY)
_cache_doc_meta   = ExternalSourceCache("companies_house_doc_meta_cache.json", ttl_default=_TTL_DOCUMENT_META)


def _document_api_key() -> str:
    """
    Clé Document API.

    Patch v16.5.69 (cohérence) : si la clé Document n'est pas explicitement
    configurée, on tente la clé Public Data en fallback gracieux. Companies
    House accepte cette substitution dans la plupart des cas — c'est le
    comportement promis par la documentation v16.5.69.

    Ordre de résolution :
      1. COMPANIES_HOUSE_DOCUMENT_API_KEY (clé dédiée Document API)
      2. COMPANIES_HOUSE_API_KEY (fallback Public Data — fonctionne souvent)
      3. "" (rien)
    """
    return (
        os.getenv("COMPANIES_HOUSE_DOCUMENT_API_KEY")
        or os.getenv("COMPANIES_HOUSE_API_KEY")
        or ""
    ).strip()


def _document_headers() -> Dict[str, str]:
    """Headers pour Document API : Basic Auth, clé en username, password vide.
    Note : malgré la convention identique au Public Data, la clé EST différente."""
    key = _document_api_key()
    if not key:
        return {}
    token = b64encode(f"{key}:".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def fetch_filing_history(company_number: str, items_per_page: int = _MAX_FILING_ITEMS) -> Dict[str, Any]:
    """
    Récupère l'historique des filings d'une société via Public Data API.
    Endpoint : /company/{cn}/filing-history

    NB : utilise la clé COMPANIES_HOUSE_API_KEY (Public Data), pas la clé Document.
    """
    cn = _normalize_company_number(company_number) or ""
    if not cn:
        return {"_error": "invalid_company_number"}

    cache_key = f"filings_{cn}"
    cached = _cache_filings.get(cache_key)
    if cached is not None:
        cached["_from_cache"] = True
        cached["_cache_age_h"] = _cache_filings.age_hours(cache_key)
        return cached

    if not _api_key():
        return {"_error": "no_public_data_api_key", "items": [], "total_count": 0}

    res = safe_get(
        f"{CH_BASE_URL}/company/{cn}/filing-history",
        params={"items_per_page": str(min(items_per_page, 100))},
        headers=_headers(),
        timeout=_REQUEST_TIMEOUT,
    )
    if not res.get("ok"):
        sc = res.get("status_code", "")
        if sc == 404:
            return {"_not_found": True, "items": [], "total_count": 0}
        return {
            "_error": res.get("error", "unknown"),
            "_message": res.get("message", "")[:120],
            "items": [], "total_count": 0,
        }

    data = res.get("data", {}) or {}
    payload = {
        "items":       data.get("items", []) or [],
        "total_count": data.get("total_count", 0),
    }
    _cache_filings.set(cache_key, payload)
    return payload


def fetch_document_metadata(document_id: str) -> Dict[str, Any]:
    """
    Récupère les métadonnées d'un document filing via Document API.
    Endpoint : /document/{doc_id}

    NB : utilise la clé COMPANIES_HOUSE_DOCUMENT_API_KEY (séparée).
    """
    if not document_id or not isinstance(document_id, str) or len(document_id) < 5:
        return {"_error": "invalid_document_id"}

    cache_key = f"docmeta_{document_id[:120]}"
    cached = _cache_doc_meta.get(cache_key)
    if cached is not None:
        cached["_from_cache"] = True
        cached["_cache_age_h"] = _cache_doc_meta.age_hours(cache_key)
        return cached

    if not _document_api_key():
        return {"_error": "no_document_api_key"}

    res = safe_get(
        f"{CH_DOCUMENT_BASE_URL}/document/{document_id}",
        headers=_document_headers(),
        timeout=_REQUEST_TIMEOUT,
    )
    if not res.get("ok"):
        sc = res.get("status_code", "")
        if sc == 404:
            return {"_not_found": True}
        if sc in (401, 403):
            return {"_error": "auth_refused", "_message": res.get("message", "")[:120]}
        return {"_error": res.get("error", "unknown"), "_message": res.get("message", "")[:120]}

    data = res.get("data", {}) or {}
    if isinstance(data, dict):
        _cache_doc_meta.set(cache_key, data)
        return data
    return {}


def get_companies_house_document_status() -> Dict[str, Any]:
    """
    Statut de la Document API pour la page Config.

    Patch v16.5.69 : indique aussi si le fallback Public Data est utilisé,
    pour transparence dans la UI.
    """
    explicit_doc = (os.getenv("COMPANIES_HOUSE_DOCUMENT_API_KEY") or "").strip()
    fallback_pubdata = (os.getenv("COMPANIES_HOUSE_API_KEY") or "").strip()
    effective_key = explicit_doc or fallback_pubdata
    return {
        "configured":         bool(effective_key),
        "key_preview":        make_key_preview(effective_key),
        "requires_key":       True,
        "explicit_doc_key":   bool(explicit_doc),       # Patch v16.5.69
        "uses_fallback":      bool(fallback_pubdata) and not bool(explicit_doc),  # Patch v16.5.69
    }


def test_connection_document(timeout: int = _REQUEST_TIMEOUT) -> Dict[str, Any]:
    """
    Test de connexion Document API.
    Stratégie : (1) chercher un filing récent de dossier anglophone coté via Public Data,
                (2) tenter d'en récupérer les métadonnées via Document API.

    Si la Public Data API n'est pas configurée, on n'a pas de document_id stable
    à tester ; on retourne un message clair.
    """
    if not _document_api_key():
        msg = "Clé Document API absente — saisir COMPANIES_HOUSE_DOCUMENT_API_KEY dans Config."
        save_test_result("companies_house_document", ok=False, message=msg)
        return {"ok": False, "message": msg, "elapsed_ms": 0}

    if not _api_key():
        msg = ("Clé Public Data absente — nécessaire pour récupérer un document_id "
               "stable de test. Configurer aussi COMPANIES_HOUSE_API_KEY.")
        save_test_result("companies_house_document", ok=False, message=msg)
        return {"ok": False, "message": msg, "elapsed_ms": 0}

    t0 = time.time()
    # 1) Filing-history dossier anglophone coté
    if not _CN_HEALTHCHECK:
        return {"ok": True, "message": "diagnostic désactivé — aucun numéro témoin configuré", "disabled": True}
    fh = fetch_filing_history(_CN_HEALTHCHECK, items_per_page=5)
    if fh.get("_error") or not fh.get("items"):
        elapsed_ms = int((time.time() - t0) * 1000)
        msg = f"Filing-history indisponible pour le numéro témoin CN {_CN_HEALTHCHECK} ({fh.get('_error', 'no_items')})."
        save_test_result("companies_house_document", ok=False, message=msg)
        return {"ok": False, "message": msg, "elapsed_ms": elapsed_ms}

    # 2) Récupérer le document_id du premier filing qui en a un
    doc_id = ""
    for item in fh["items"]:
        links = item.get("links", {}) or {}
        doc_meta_url = links.get("document_metadata", "")
        if doc_meta_url:
            # Extraire l'identifiant : .../document/{id}
            doc_id = doc_meta_url.rstrip("/").rsplit("/", 1)[-1]
            if doc_id:
                break
    if not doc_id:
        elapsed_ms = int((time.time() - t0) * 1000)
        msg = "Aucun filing avec document_metadata trouvé sur les 5 derniers filings du numéro témoin."
        save_test_result("companies_house_document", ok=False, message=msg)
        return {"ok": False, "message": msg, "elapsed_ms": elapsed_ms}

    # 3) Tenter récup métadonnées
    meta = fetch_document_metadata(doc_id)
    elapsed_ms = int((time.time() - t0) * 1000)

    if meta.get("_error") == "auth_refused":
        msg = "Authentification Document API refusée (clé invalide ou non habilitée)."
        save_test_result("companies_house_document", ok=False, message=msg)
        return {"ok": False, "message": msg, "elapsed_ms": elapsed_ms}
    if meta.get("_error"):
        msg = f"Erreur Document API : {meta.get('_error', 'unknown')}"
        save_test_result("companies_house_document", ok=False, message=msg)
        return {"ok": False, "message": msg, "elapsed_ms": elapsed_ms}

    cn_in_meta = meta.get("company_number", "") if isinstance(meta, dict) else ""
    if cn_in_meta and str(cn_in_meta).lstrip("0") == _CN_HEALTHCHECK.lstrip("0"):
        msg = f"OK — métadonnées récupérées pour le filing du numéro témoin doc_id={doc_id[:12]}… en {elapsed_ms}ms"
        save_test_result("companies_house_document", ok=True, message=msg)
        return {"ok": True, "message": msg, "elapsed_ms": elapsed_ms}
    msg = f"Réponse 200 mais company_number inattendu (got=«{cn_in_meta}»)"
    save_test_result("companies_house_document", ok=False, message=msg)
    return {"ok": False, "message": msg, "elapsed_ms": elapsed_ms}


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENT CONTENT DOWNLOAD — Since v16.5.69
# ─────────────────────────────────────────────────────────────────────────────
# La Document API expose 2 endpoints :
#   1. GET /document/{id}            → métadonnées (déjà : fetch_document_metadata)
#   2. GET /document/{id}/content    → contenu binaire (PDF/XHTML/CSV selon Accept)
#
# Architecture du download :
#   - Cache disque permanent : ~/.codir_ia/companies_house_documents/{doc_id}.{ext}
#     Pas de TTL — un filing publié ne change jamais.
#   - Limite par session : max 10 docs (configurable via env CODIR_CH_DOC_MAX_PER_SESSION)
#     pour éviter aspiration involontaire. Cache hit = gratuit (ne compte pas).
#   - Formats acceptés : "application/pdf" (défaut), "application/xhtml+xml", "text/csv"
#   - Le module retourne à la fois les bytes ET le path local pour intégration
#     dans attachments_meta CoDIR-IA.

import hashlib
from pathlib import Path

# Compteur session — réinitialisé à chaque démarrage Python
_SESSION_DOC_DOWNLOAD_COUNT = {"count": 0}

# Limite par défaut (configurable via env)
_DEFAULT_MAX_DOCS_PER_SESSION = 10


def _get_max_docs_per_session() -> int:
    """Récupère la limite configurée (env > défaut)."""
    raw = os.getenv("CODIR_CH_DOC_MAX_PER_SESSION", "").strip()
    if raw:
        try:
            n = int(raw)
            if n > 0:
                return n
        except ValueError:
            pass
    return _DEFAULT_MAX_DOCS_PER_SESSION


def _documents_cache_dir() -> Path:
    """Répertoire de cache permanent des documents téléchargés."""
    from utils.config_paths import ensure_cache_dir
    base = ensure_cache_dir()
    cache_dir = base / "companies_house_documents"
    try:
        # v16.5.76 Phase 7a (VULN-5) — dossier 0o700 sur POSIX (fail-open)
        try:
            from utils.config_paths import ensure_private_dir as _epd
            _epd(cache_dir)
        except Exception:
            cache_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return cache_dir


def _safe_doc_filename(document_id: str, extension: str) -> str:
    """
    Construit un nom de fichier sûr pour le cache disque.
    document_id Companies House peut contenir des caractères spéciaux : on hash si besoin.
    """
    safe_id = re.sub(r"[^A-Za-z0-9_\-]", "_", document_id)[:80]
    if not safe_id or safe_id != document_id[:80]:
        # Fallback hash si caractères dangereux ou troncature
        h = hashlib.sha256(document_id.encode("utf-8")).hexdigest()[:16]
        safe_id = f"doc_{h}"
    ext_clean = re.sub(r"[^a-z]", "", extension.lower())[:5] or "bin"
    return f"{safe_id}.{ext_clean}"


def _format_to_accept_header(format_: str) -> str:
    """Convertit un format court en header Accept."""
    mapping = {
        "pdf":   "application/pdf",
        "xhtml": "application/xhtml+xml",
        "xml":   "application/xml",
        "json":  "application/json",
        "csv":   "text/csv",
    }
    return mapping.get(format_.lower(), "application/pdf")


def _format_to_extension(format_: str, content_type: str = "") -> str:
    """Détermine l'extension de fichier depuis format + content_type."""
    fmt = format_.lower()
    if fmt in ("pdf", "xhtml", "xml", "json", "csv"):
        return fmt if fmt != "xhtml" else "xhtml"
    # Fallback content_type
    if "pdf" in content_type:
        return "pdf"
    if "xhtml" in content_type:
        return "xhtml"
    if "xml" in content_type:
        return "xml"
    if "csv" in content_type:
        return "csv"
    if "json" in content_type:
        return "json"
    return "bin"


def reset_session_doc_counter() -> None:
    """Reset du compteur session — utile en début de run CoDIR ou en tests."""
    _SESSION_DOC_DOWNLOAD_COUNT["count"] = 0


def get_session_doc_counter() -> Dict[str, int]:
    """Retourne {count, max} pour affichage UI."""
    return {
        "count": _SESSION_DOC_DOWNLOAD_COUNT["count"],
        "max":   _get_max_docs_per_session(),
    }


def fetch_document_content(
    document_id: str,
    format: str = "pdf",
    *,
    use_cache: bool = True,
    enforce_session_limit: bool = True,
) -> Dict[str, Any]:
    """
    Télécharge le contenu d'un filing UK depuis Document API.

    Args:
        document_id : id retourné par fetch_document_metadata ou par
                      `links.document_metadata` du filing-history.
        format      : "pdf" (défaut) | "xhtml" | "xml" | "csv" | "json"
        use_cache   : si True, retourne le cache disque s'il existe (gratuit, pas de quota)
        enforce_session_limit : si True (défaut), refuse au-delà de la limite session

    Retourne :
      {
        "ok": bool,
        "from_cache": bool,                 # True si servi depuis cache disque
        "content": bytes,                   # contenu binaire (toujours présent si ok)
        "local_path": str,                  # chemin absolu du fichier en cache disque
        "content_type": str,                # Content-Type retourné par l'API
        "bytes_length": int,
        "session_count": int,               # compteur session après cet appel
        "session_max": int,                 # limite configurée
        "elapsed_ms": int,
      }
      ou en cas d'erreur :
      {"ok": False, "error": "<type>", "message": "<détails>", ...}

    error ∈ {invalid_document_id, no_document_api_key, session_limit_reached,
             not_found, auth_refused, http_error, timeout, connection_error,
             size_limit_exceeded, write_error, unexpected_error}

    Garantie : ne lève JAMAIS d'exception. Cache hit = pas de quota consommé.
    """
    # 1. Validations de base
    if not document_id or not isinstance(document_id, str) or len(document_id) < 5:
        return {"ok": False, "error": "invalid_document_id",
                "message": "document_id invalide ou trop court"}

    extension = _format_to_extension(format)
    cache_filename = _safe_doc_filename(document_id, extension)
    cache_path = _documents_cache_dir() / cache_filename

    # 2. Cache hit = gratuit
    if use_cache and cache_path.exists():
        try:
            content = cache_path.read_bytes()
            return {
                "ok": True,
                "from_cache": True,
                "content": content,
                "local_path": str(cache_path),
                "content_type": _format_to_accept_header(format),
                "bytes_length": len(content),
                "session_count": _SESSION_DOC_DOWNLOAD_COUNT["count"],
                "session_max": _get_max_docs_per_session(),
                "elapsed_ms": 0,
            }
        except Exception:
            # Cache corrompu : on continue vers download réseau
            pass

    # 3. Garde-fou clé Document API
    if not _document_api_key():
        return {"ok": False, "error": "no_document_api_key",
                "message": "Clé Document API absente — saisir COMPANIES_HOUSE_DOCUMENT_API_KEY"}

    # 4. Garde-fou limite session
    max_per_session = _get_max_docs_per_session()
    if enforce_session_limit and _SESSION_DOC_DOWNLOAD_COUNT["count"] >= max_per_session:
        return {
            "ok": False, "error": "session_limit_reached",
            "message": f"Limite session atteinte ({max_per_session} docs). "
                       f"Augmenter via CODIR_CH_DOC_MAX_PER_SESSION ou redémarrer la session.",
            "session_count": _SESSION_DOC_DOWNLOAD_COUNT["count"],
            "session_max": max_per_session,
        }

    # 5. Téléchargement réseau (Document API → suit la redirection vers signed URL S3)
    headers = _document_headers()
    headers["Accept"] = _format_to_accept_header(format)

    res = safe_get_bytes(
        f"{CH_DOCUMENT_BASE_URL}/document/{document_id}/content",
        headers=headers,
        timeout=30,
        max_size_mb=25,
        allow_redirects=True,
    )

    if not res.get("ok"):
        sc = res.get("status_code")
        if sc == 404:
            return {"ok": False, "error": "not_found",
                    "message": f"Document {document_id} introuvable"}
        if sc in (401, 403):
            return {"ok": False, "error": "auth_refused",
                    "message": "Authentification Document API refusée"}
        return {"ok": False, "error": res.get("error", "http_error"),
                "message": res.get("message", "")[:200]}

    # 6. Sauvegarde cache disque
    content = res["content"]
    try:
        tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
        tmp.write_bytes(content)
        tmp.replace(cache_path)
    except Exception as e:
        # Si on ne peut pas écrire, on retourne quand même les bytes
        # (l'utilisateur peut quand même les utiliser en mémoire)
        return {
            "ok": True,
            "from_cache": False,
            "content": content,
            "local_path": "",
            "content_type": res.get("content_type", ""),
            "bytes_length": res.get("bytes_length", len(content)),
            "session_count": _SESSION_DOC_DOWNLOAD_COUNT["count"],
            "session_max": max_per_session,
            "elapsed_ms": res.get("elapsed_ms", 0),
            "warning": f"Cache write failed: {str(e)[:100]}",
        }

    # 7. Incrémenter compteur session (download réussi, pas un cache hit)
    _SESSION_DOC_DOWNLOAD_COUNT["count"] += 1

    return {
        "ok": True,
        "from_cache": False,
        "content": content,
        "local_path": str(cache_path),
        "content_type": res.get("content_type", ""),
        "bytes_length": res.get("bytes_length", len(content)),
        "session_count": _SESSION_DOC_DOWNLOAD_COUNT["count"],
        "session_max": max_per_session,
        "elapsed_ms": res.get("elapsed_ms", 0),
    }


def clear_documents_cache() -> Dict[str, Any]:
    """
    Vide le cache disque des documents téléchargés.
    Retourne {count_deleted, total_size_freed_mb}.
    Utile pour bouton "Vider le cache documents" dans Config.
    """
    cache_dir = _documents_cache_dir()
    count = 0
    total = 0
    if cache_dir.exists():
        for path in cache_dir.iterdir():
            if path.is_file():
                try:
                    sz = path.stat().st_size
                    path.unlink()
                    count += 1
                    total += sz
                except Exception:
                    pass
    return {
        "count_deleted": count,
        "total_size_freed_mb": round(total / 1024 / 1024, 2),
    }


def get_documents_cache_info() -> Dict[str, Any]:
    """Renseigne sur l'état du cache disque (count, taille totale)."""
    cache_dir = _documents_cache_dir()
    count = 0
    total = 0
    if cache_dir.exists():
        for path in cache_dir.iterdir():
            if path.is_file():
                try:
                    total += path.stat().st_size
                    count += 1
                except Exception:
                    pass
    return {
        "path": str(cache_dir),
        "count": count,
        "total_size_mb": round(total / 1024 / 1024, 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# FILINGS → ATTACHMENTS — Since v16.5.69.1
# ─────────────────────────────────────────────────────────────────────────────
# Avant v16.5.69.1, fetch_document_content() téléchargeait bien les filings UK,
# mais ne les exposait que comme metadata dans attachments_meta["_ch_filings"]
# (chemins de fichiers). Les agents LLM ne pouvaient donc pas LIRE le contenu —
# ils voyaient seulement "il existe 4 PDFs ailleurs sur le disque".
#
# Cette fonction extrait le texte des PDFs / XHTML téléchargés et construit
# une liste d'AttachmentText réutilisable par build_attachments_block().
#
# C'est cette étape qui rend la promesse "ajoutés aux pièces jointes pour
# Finance / Stratégie" effective.

def build_filings_attachments_from_downloads(
    downloaded_filings: List[Dict[str, Any]],
    lang: str = "fr",
) -> List[Any]:
    """
    Construit une liste d'AttachmentText à partir des filings UK téléchargés
    par fetch_document_content().

    Args:
        downloaded_filings : liste retournée par codir_engine, chaque entrée
                              contient au minimum : doc_id, type, category,
                              date, description, local_path
        lang                : "fr" / "en" pour le préfixe descriptif

    Retourne une liste d'AttachmentText prête à être passée à
    build_attachments_block(). Filings illisibles (path manquant, extraction
    KO) sont silencieusement ignorés — pas d'exception levée.

    Les noms de fichiers générés sont **descriptifs** plutôt que techniques
    (`Annual Accounts 2025-08-15 — dossier anglophone coté Group plc.pdf` plutôt que
    `HMsKGYRQ0a12doc1.pdf`) pour que les agents puissent y faire référence
    naturellement dans le compte-rendu.
    """
    if not downloaded_filings:
        return []

    # Import local pour éviter dépendance circulaire au chargement du module
    try:
        from utils.attachments import AttachmentText, extract_text_from_upload
    except Exception:
        return []

    out: List[Any] = []
    for filing in downloaded_filings:
        if not isinstance(filing, dict):
            continue
        local_path = filing.get("local_path", "") or ""
        if not local_path:
            continue
        try:
            with open(local_path, "rb") as f:
                content = f.read()
        except Exception:
            continue
        if not content:
            continue

        # Construire un nom de fichier descriptif lisible par l'humain
        category = (filing.get("category", "") or "filing").lower()
        ftype    = (filing.get("type", "") or "").upper()
        date     = (filing.get("date", "") or "")[:10]

        if lang == "fr":
            label_map = {
                "accounts":              "Comptes annuels",
                "confirmation-statement":"Confirmation Statement",
                "incorporation":         "Incorporation",
                "officers":              "Dirigeants",
                "capital":               "Capital",
            }
        else:
            label_map = {
                "accounts":              "Annual Accounts",
                "confirmation-statement":"Confirmation Statement",
                "incorporation":         "Incorporation",
                "officers":              "Officers",
                "capital":               "Capital",
            }
        descriptive_label = label_map.get(category, ftype or category or "filing")

        # Extension à partir du path local
        ext = ""
        if "." in local_path:
            ext = local_path.rsplit(".", 1)[-1].lower()
        if not ext:
            ext = "pdf"
        ext = ext.replace("xhtml", "xhtml").replace("pdf", "pdf")[:5]

        descriptive_filename = f"{descriptive_label} {date} (Companies House).{ext}"

        # Mimetype d'inférence
        if ext == "pdf":
            mime = "application/pdf"
        elif ext in ("xhtml", "xml"):
            mime = "application/xhtml+xml" if ext == "xhtml" else "application/xml"
        elif ext == "csv":
            mime = "text/csv"
        else:
            mime = "application/octet-stream"

        # Extraire le texte via le pipeline existant
        try:
            text = extract_text_from_upload(descriptive_filename, mime, content)
        except Exception:
            text = ""

        if not text or len(text.strip()) < 30:
            # Trop court pour être utile — skip
            continue

        out.append(AttachmentText(
            filename=descriptive_filename,
            mimetype=mime,
            size_bytes=len(content),
            text=text,
        ))

    return out


__all__ = [
    "CH_BASE_URL",
    "CH_DOCUMENT_BASE_URL",
    "CONFIDENCE_NUMBER_DIRECT", "CONFIDENCE_NAME_EXACT", "CONFIDENCE_NAME_FUZZY",
    "CONFIDENCE_NOT_FOUND", "CONFIDENCE_NOT_CONFIGURED",
    "CompaniesHouseResolutionLog",
    "build_companies_house_blocks",
    "get_companies_house_status",
    "test_connection",
    # Since v16.5.68 — Document API metadata
    "fetch_filing_history",
    "fetch_document_metadata",
    "get_companies_house_document_status",
    "test_connection_document",
    # Since v16.5.69 — Document API content download
    "fetch_document_content",
    "reset_session_doc_counter",
    "get_session_doc_counter",
    "clear_documents_cache",
    "get_documents_cache_info",
    # Since v16.5.69 — Preview pour confirmation utilisateur sur fuzzy match
    "preview_companies_house_detection",
    # Since v16.5.69.1 — Vraie injection des filings dans attachments_block
    "build_filings_attachments_from_downloads",
]
