"""
CoDIR-IA — utils/sec_edgar_tool.py — v16.5.68

Source de données : SEC EDGAR (US Securities and Exchange Commission)
URL : https://data.sec.gov/ et https://efts.sec.gov/LATEST/search-index

Couverture :
  - Sociétés cotées aux US (NYSE, NASDAQ, AMEX) : ~10 000 entités actives
  - Filings 10-K (annual report), 10-Q (quarterly), 8-K (current report)
  - Données : CIK, nom, ticker(s), SIC, état d'incorporation, adresses, derniers filings
  - **Aucune clé API requise**, MAIS User-Agent obligatoire (SEC.gov rate-limit 10 req/sec)
  - Format User-Agent imposé : « FirstName LastName email@domain.com »

Cas d'usage CoDIR-IA :
  - Identifier qu'une société est cotée aux US (signal due diligence majeure)
  - Récupérer son dernier 10-K pour Finance / Stratégie
  - Vérifier l'état d'incorporation (Delaware = signal classique de holding)
  - Compléter Pappers (FR-only) sur les maisons-mères US (cas Xylem, etc.)

Architecture :
  - Cache disque ExternalSourceCache (TTL 7 jours — submissions stables sauf 10-K récent)
  - Extraction CIK prioritaire depuis le brief
  - Recherche par nom via EFTS si pas de CIK (1 appel API)
  - Format dual : full / summary

Sécurité & conformité :
  - Refus de tout appel sans User-Agent (SEC.gov peut bannir l'IP sinon)
  - Headers fixes : {User-Agent, Accept-Encoding=gzip}
  - Aucune donnée perso saisie ni transmise sauf le User-Agent (que l'utilisateur a explicitement fourni dans la page Config)
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field, asdict
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

SEC_DATA_BASE_URL    = "https://data.sec.gov"
SEC_EFTS_SEARCH_URL  = "https://efts.sec.gov/LATEST/search-index"
SEC_TICKERS_URL      = "https://www.sec.gov/files/company_tickers.json"

_REQUEST_TIMEOUT     = DEFAULT_TIMEOUT_S
_TTL_SUBMISSIONS     = 7  * 24 * 3600    # 7 jours — submissions évoluent peu sauf récents
_TTL_TICKERS         = 30 * 24 * 3600    # 30 jours — table ticker→CIK très stable
_MAX_RECENT_FILINGS  = 5

# CIK témoin pour le test de connexion : Apple Inc. (très stable)
_CIK_HEALTHCHECK = "0000320193"

# Pattern CIK : 6 à 10 chiffres dans le brief, optionnellement préfixé "CIK"
_RE_CIK = re.compile(r"\bCIK[\s:#=]*0*(\d{1,10})\b", re.IGNORECASE)
# Pattern ticker : 1-5 lettres majuscules, isolé, et avec le mot 'ticker' à proximité
# (pour réduire les faux positifs comme "USA", "FR")
_RE_TICKER_LABELED = re.compile(r"\bticker\s*[:#=]?\s*([A-Z]{1,5})\b", re.IGNORECASE)

# Niveaux de confiance
CONFIDENCE_CIK_DIRECT     = "CIK_DIRECT"
CONFIDENCE_TICKER         = "TICKER"
CONFIDENCE_NAME_EXACT     = "NAME_EXACT"
CONFIDENCE_NAME_FUZZY     = "NAME_FUZZY"
CONFIDENCE_NOT_FOUND      = "NOT_FOUND"
CONFIDENCE_NO_USER_AGENT  = "NO_USER_AGENT"


# ── Cache disque ──────────────────────────────────────────────────────────────

_cache_submissions = ExternalSourceCache("sec_edgar_submissions_cache.json", ttl_default=_TTL_SUBMISSIONS)
_cache_tickers     = ExternalSourceCache("sec_edgar_tickers_cache.json",     ttl_default=_TTL_TICKERS)


# ── Log de résolution audit-ready ────────────────────────────────────────────

@dataclass
class SecEdgarResolutionLog:
    """Trace audit-ready de la résolution SEC EDGAR pour une session."""
    input_preview: str = ""
    path: str = ""              # CIK_DIRECT | TICKER | NAME_* | NOT_FOUND | NO_USER_AGENT
    source: str = ""            # BRIEF_CIK | BRIEF_TICKER | NAME_SEARCH | EMPTY
    cik_used: str = ""
    primary_name: str = ""
    primary_ticker: str = ""
    state_of_incorp: str = ""
    cache_hit: bool = False
    cache_age_h: Optional[float] = None
    tokens_est_full: int = 0
    tokens_est_summary: int = 0
    timestamp: str = field(default_factory=now_iso)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def summary_line(self) -> str:
        if self.error:
            return f"sec_edgar | path={self.path} | error={self.error[:80]}"
        return (f"sec_edgar | path={self.path} | source={self.source} | "
                f"cik={self.cik_used or '—'} | name={(self.primary_name or '—')[:40]} | "
                f"ticker={self.primary_ticker or '—'} | cache_hit={self.cache_hit}")


# ── User-Agent management ────────────────────────────────────────────────────

def _user_agent() -> str:
    """Récupère le User-Agent SEC depuis l'environnement (settings v16.5.68)."""
    return (os.getenv("SEC_EDGAR_USER_AGENT") or "").strip()


def _is_valid_user_agent(ua: str) -> bool:
    """
    Validation minimale : doit contenir un email-like (chiffres/lettres @ point).
    SEC.gov demande explicitement le format « Name email@domain.com ».
    """
    if not ua or len(ua) < 5:
        return False
    return bool(re.search(r"[\w._%+-]+@[\w.-]+\.[A-Za-z]{2,}", ua))


def _headers() -> Dict[str, str]:
    """Headers SEC requis : User-Agent (obligatoire) + Accept-Encoding."""
    return {
        "User-Agent":      _user_agent(),
        "Accept-Encoding": "gzip, deflate",
        "Accept":          "application/json",
    }


# ── Extraction CIK / ticker depuis brief ─────────────────────────────────────

def _extract_cik_from_text(text: str) -> Optional[str]:
    """Extrait un CIK normalisé (10 chiffres avec leading zeros) du texte."""
    if not text:
        return None
    m = _RE_CIK.search(text)
    if not m:
        return None
    cik_digits = m.group(1)
    if len(cik_digits) > 10:
        return None
    return cik_digits.zfill(10)


def _extract_ticker_from_text(text: str) -> Optional[str]:
    """Extrait un ticker labellisé (« ticker: AAPL ») du texte."""
    if not text:
        return None
    m = _RE_TICKER_LABELED.search(text)
    if m:
        return m.group(1).upper()
    return None


def _normalize_cik(cik: str) -> str:
    """Normalise un CIK à 10 chiffres avec leading zeros."""
    if not cik:
        return ""
    digits = re.sub(r"\D", "", str(cik))
    if not digits or len(digits) > 10:
        return ""
    return digits.zfill(10)


# ── Appels API ───────────────────────────────────────────────────────────────

def _fetch_tickers_table() -> Dict[str, Dict[str, Any]]:
    """
    Charge la table {ticker: {cik_str, ticker, title}} depuis SEC.
    Caché 30 jours. Retourne {} en cas d'erreur.
    """
    cached = _cache_tickers.get("tickers_table")
    if cached is not None:
        return cached

    if not _is_valid_user_agent(_user_agent()):
        return {}

    res = safe_get(SEC_TICKERS_URL, headers=_headers(), timeout=_REQUEST_TIMEOUT)
    if not res.get("ok"):
        return {}
    data = res.get("data", {})
    if not isinstance(data, dict):
        return {}

    # Format SEC : {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, "1": {...}}
    table: Dict[str, Dict[str, Any]] = {}
    for entry in data.values():
        if isinstance(entry, dict) and entry.get("ticker"):
            table[entry["ticker"].upper()] = entry
    _cache_tickers.set("tickers_table", table)
    return table


def _resolve_ticker_to_cik(ticker: str) -> Optional[str]:
    """Résout un ticker en CIK normalisé via la table SEC."""
    if not ticker:
        return None
    table = _fetch_tickers_table()
    entry = table.get(ticker.upper())
    if not entry:
        return None
    return _normalize_cik(str(entry.get("cik_str", "")))


def _resolve_name_to_cik(name: str) -> Optional[Dict[str, Any]]:
    """
    Résout un nom de société vers un record SEC (CIK + métadonnées).
    Utilise la table tickers (recherche locale, pas d'appel API supplémentaire).
    Retourne le premier match dont le titre contient le nom (case-insensitive).
    """
    if not name or len(name.strip()) < 3:
        return None
    table = _fetch_tickers_table()
    name_lower = name.strip().lower()
    # 1) Match exact sur title
    for entry in table.values():
        if entry.get("title", "").strip().lower() == name_lower:
            return {"entry": entry, "match": "exact"}
    # 2) Match contains
    for entry in table.values():
        if name_lower in entry.get("title", "").strip().lower():
            return {"entry": entry, "match": "fuzzy"}
    return None


@lru_cache(maxsize=64)
def _fetch_submissions(cik_padded: str) -> Dict[str, Any]:
    """
    Récupère les submissions JSON pour un CIK donné (10 chiffres paddés).
    Cache disque 7 jours + lru_cache intra-session.
    """
    if not re.fullmatch(r"\d{10}", cik_padded):
        return {}

    cache_key = f"sub_{cik_padded}"
    cached = _cache_submissions.get(cache_key)
    if cached is not None:
        cached["_from_cache"] = True
        cached["_cache_age_h"] = _cache_submissions.age_hours(cache_key)
        return cached

    if not _is_valid_user_agent(_user_agent()):
        return {"_error": "no_user_agent"}

    url = f"{SEC_DATA_BASE_URL}/submissions/CIK{cik_padded}.json"
    res = safe_get(url, headers=_headers(), timeout=_REQUEST_TIMEOUT)
    if not res.get("ok"):
        if res.get("status_code") == 404:
            return {"_not_found": True}
        return {"_error": res.get("error", "unknown"), "_message": res.get("message", "")[:120]}

    data = res.get("data", {})
    if isinstance(data, dict) and data.get("cik"):
        _cache_submissions.set(cache_key, data)
        return data
    return {}


# ── Format pour injection dans prompt agent ──────────────────────────────────

_LABELS = {
    "fr": {
        "header_full":     "DONNÉES SEC EDGAR — RÉGULATEUR US",
        "header_summary":  "SEC EDGAR — CONTEXTE US (résumé)",
        "footer":          "Source : SEC.gov EDGAR. Société cotée aux États-Unis. Filings publics et obligatoires.",
        "name":            "Raison sociale",
        "cik":             "CIK",
        "tickers":         "Tickers",
        "exchanges":       "Bourses",
        "sic":             "Secteur SIC",
        "category":        "Catégorie filer",
        "fye":             "Clôture exercice fiscal",
        "state":           "État d'incorporation",
        "address_business":"Adresse business",
        "phone":           "Téléphone",
        "filings_recent":  "Derniers filings",
        "no_user_agent":   "⚠️ User-Agent SEC non configuré — section non exploitée. Renseigner SEC_EDGAR_USER_AGENT en page Config.",
    },
    "en": {
        "header_full":     "SEC EDGAR DATA — US REGULATOR",
        "header_summary":  "SEC EDGAR — US CONTEXT (summary)",
        "footer":          "Source: SEC.gov EDGAR. Company listed in the United States. Public mandatory filings.",
        "name":            "Legal name",
        "cik":             "CIK",
        "tickers":         "Tickers",
        "exchanges":       "Exchanges",
        "sic":             "SIC sector",
        "category":        "Filer category",
        "fye":             "Fiscal year end",
        "state":           "State of incorporation",
        "address_business":"Business address",
        "phone":           "Phone",
        "filings_recent":  "Recent filings",
        "no_user_agent":   "⚠️ SEC User-Agent not configured — section not used. Set SEC_EDGAR_USER_AGENT on the Config page.",
    },
}


def _t(key: str, lang: str) -> str:
    return _LABELS.get(lang, _LABELS["en"]).get(key, key)


def _format_address(addr: Dict[str, Any]) -> str:
    if not isinstance(addr, dict):
        return ""
    parts = []
    s1 = addr.get("street1", "")
    s2 = addr.get("street2", "")
    city = addr.get("city", "")
    state = addr.get("stateOrCountry", "") or addr.get("state", "")
    zipc = addr.get("zipCode", "")
    if s1: parts.append(s1)
    if s2: parts.append(s2)
    loc = " ".join(p for p in [zipc, city, state] if p)
    if loc:
        parts.append(loc)
    return " — ".join(parts)


def _format_filings(filings_recent: Dict[str, Any], max_items: int = _MAX_RECENT_FILINGS) -> List[str]:
    """Extrait les N derniers filings sous forme de strings courtes."""
    if not isinstance(filings_recent, dict):
        return []
    forms     = filings_recent.get("form", []) or []
    dates     = filings_recent.get("filingDate", []) or []
    n = min(len(forms), len(dates), max_items)
    return [f"{forms[i]} ({dates[i]})" for i in range(n)]


def _format_submissions(data: Dict[str, Any], lang: str = "fr", scope: str = "full") -> str:
    """Formate un payload submissions SEC en texte structuré pour prompt agent."""
    if not data or not isinstance(data, dict):
        return ""

    name      = data.get("name", "")
    cik       = data.get("cik", "")
    tickers   = data.get("tickers", []) or []
    exchanges = data.get("exchanges", []) or []
    sic       = data.get("sicDescription", "") or data.get("sic", "")
    category  = data.get("category", "")
    fye       = data.get("fiscalYearEnd", "")
    state     = data.get("stateOfIncorporationDescription") or data.get("stateOfIncorporation", "")

    addresses = data.get("addresses", {}) if isinstance(data.get("addresses"), dict) else {}
    business_addr = _format_address(addresses.get("business", {}))

    filings = data.get("filings", {}).get("recent", {}) if isinstance(data.get("filings"), dict) else {}
    recent  = _format_filings(filings, max_items=_MAX_RECENT_FILINGS if scope == "full" else 3)

    header = _t("header_summary" if scope == "summary" else "header_full", lang)
    lines = [header, ""]
    if name:    lines.append(f"{_t('name', lang)} : {name}")
    if cik:     lines.append(f"{_t('cik', lang)} : {cik}")
    if tickers: lines.append(f"{_t('tickers', lang)} : {', '.join(tickers)}")
    if exchanges: lines.append(f"{_t('exchanges', lang)} : {', '.join(exchanges)}")
    if scope == "full":
        if sic:      lines.append(f"{_t('sic', lang)} : {sic}")
        if category: lines.append(f"{_t('category', lang)} : {category}")
        if fye:      lines.append(f"{_t('fye', lang)} : {fye}")
        if state:    lines.append(f"{_t('state', lang)} : {state}")
        if business_addr: lines.append(f"{_t('address_business', lang)} : {business_addr}")
        if recent:
            lines.append("")
            lines.append(f"{_t('filings_recent', lang)} :")
            for fl in recent:
                lines.append(f"  - {fl}")

    lines.append("")
    lines.append(_t("footer", lang))
    return "\n".join(lines).strip()


# ── Entry point principal ────────────────────────────────────────────────────

def build_sec_edgar_blocks(
    brief_text: str,
    lang: str = "fr",
    confirmed_name: str = "",
) -> Dict[str, Any]:
    """
    Entry point : extrait CIK/ticker/nom → résout via SEC EDGAR → blocs formatés.

    Retourne le même contrat que build_gleif_blocks / build_pappers_blocks :
      {
        "full": str, "summary": str, "primary": str, "primary_cik": str,
        "primary_ticker": str, "confidence": str, "resolution_log": SecEdgarResolutionLog,
      }

    Garantie : aucun appel API si User-Agent absent (renvoie NO_USER_AGENT).
    Ne lève jamais d'exception.
    """
    rlog = SecEdgarResolutionLog(input_preview=(brief_text or "")[:120])

    # 0) Garde-fou : User-Agent obligatoire
    if not _is_valid_user_agent(_user_agent()):
        rlog.path = CONFIDENCE_NO_USER_AGENT
        rlog.source = "EMPTY"
        rlog.error = "user_agent_missing_or_invalid"
        return {
            "full": "", "summary": "",
            "primary": "", "primary_cik": "", "primary_ticker": "",
            "confidence": CONFIDENCE_NO_USER_AGENT,
            "resolution_log": rlog,
        }

    cik_padded = ""
    confidence = CONFIDENCE_NOT_FOUND
    matched_entry: Optional[Dict[str, Any]] = None

    # 1) Priorité : CIK explicite dans le brief
    direct_cik = _extract_cik_from_text(brief_text or "")
    if direct_cik:
        cik_padded = direct_cik
        confidence = CONFIDENCE_CIK_DIRECT
        rlog.path = "CIK_DIRECT"
        rlog.source = "BRIEF_CIK"

    # 2) Sinon : ticker explicite
    if not cik_padded:
        ticker = _extract_ticker_from_text(brief_text or "")
        if ticker:
            resolved_cik = _resolve_ticker_to_cik(ticker)
            if resolved_cik:
                cik_padded = resolved_cik
                confidence = CONFIDENCE_TICKER
                rlog.path = "TICKER"
                rlog.source = "BRIEF_TICKER"
                rlog.primary_ticker = ticker

    # 3) Sinon : recherche par nom confirmé
    if not cik_padded and confirmed_name:
        match = _resolve_name_to_cik(confirmed_name)
        if match:
            entry = match["entry"]
            cik_padded = _normalize_cik(str(entry.get("cik_str", "")))
            confidence = CONFIDENCE_NAME_EXACT if match["match"] == "exact" else CONFIDENCE_NAME_FUZZY
            rlog.path = confidence
            rlog.source = "NAME_SEARCH"
            rlog.primary_ticker = entry.get("ticker", "")
            matched_entry = entry

    # 4) Si on a un CIK : récupérer les submissions
    if not cik_padded:
        rlog.path = "NOT_FOUND"
        rlog.source = rlog.source or "EMPTY"
        return {
            "full": "", "summary": "",
            "primary": "", "primary_cik": "", "primary_ticker": "",
            "confidence": CONFIDENCE_NOT_FOUND,
            "resolution_log": rlog,
        }

    rlog.cik_used = cik_padded
    submissions = _fetch_submissions(cik_padded)

    if not submissions or submissions.get("_not_found") or submissions.get("_error"):
        rlog.error = submissions.get("_error", "no_submissions") if isinstance(submissions, dict) else "no_submissions"
        return {
            "full": "", "summary": "",
            "primary": matched_entry.get("title", "") if matched_entry else "",
            "primary_cik": cik_padded, "primary_ticker": rlog.primary_ticker,
            "confidence": confidence,
            "resolution_log": rlog,
        }

    rlog.cache_hit = bool(submissions.get("_from_cache"))
    rlog.cache_age_h = submissions.get("_cache_age_h")

    full_block    = _format_submissions(submissions, lang=lang, scope="full")
    summary_block = _format_submissions(submissions, lang=lang, scope="summary")
    rlog.tokens_est_full    = len(full_block) // 4
    rlog.tokens_est_summary = len(summary_block) // 4
    rlog.primary_name    = submissions.get("name", "")
    if not rlog.primary_ticker:
        tk = submissions.get("tickers", [])
        rlog.primary_ticker = tk[0] if tk else ""
    rlog.state_of_incorp = submissions.get("stateOfIncorporationDescription", "") or submissions.get("stateOfIncorporation", "")

    return {
        "full":            full_block,
        "summary":         summary_block,
        "primary":         rlog.primary_name,
        "primary_cik":     cik_padded,
        "primary_ticker":  rlog.primary_ticker,
        "confidence":      confidence,
        "resolution_log":  rlog,
    }


# ── Status & test de connexion ───────────────────────────────────────────────

def get_sec_edgar_status() -> Dict[str, Any]:
    """Statut SEC EDGAR pour la page Config."""
    ua = _user_agent()
    valid = _is_valid_user_agent(ua)
    return {
        "configured":    valid,         # configuré = User-Agent valide
        "key_preview":   ua[:30] + ("…" if len(ua) > 30 else "") if ua else "",
        "requires_key":  False,
        "requires_user_agent": True,
        "user_agent_set":      bool(ua),
        "user_agent_valid":    valid,
    }


def test_connection(timeout: int = _REQUEST_TIMEOUT) -> Dict[str, Any]:
    """
    Test de connexion SEC EDGAR : appelle les submissions du CIK témoin
    (Apple Inc. CIK 0000320193) et vérifie la réponse.
    Persiste le résultat via save_test_result.
    """
    if not _is_valid_user_agent(_user_agent()):
        msg = "User-Agent SEC manquant ou invalide — saisir 'Prénom Nom email@domaine.com' dans Config."
        save_test_result("sec_edgar", ok=False, message=msg)
        return {"ok": False, "message": msg, "elapsed_ms": 0}

    t0 = time.time()
    res = safe_get(
        f"{SEC_DATA_BASE_URL}/submissions/CIK{_CIK_HEALTHCHECK}.json",
        headers=_headers(),
        timeout=timeout,
    )
    elapsed_ms = int((time.time() - t0) * 1000)

    if not res.get("ok"):
        msg = f"{res.get('error', 'unknown')} — {res.get('message', '')[:120]}"
        save_test_result("sec_edgar", ok=False, message=msg)
        return {"ok": False, "message": msg, "elapsed_ms": elapsed_ms}

    data = res.get("data", {})
    name = data.get("name", "") if isinstance(data, dict) else ""
    if "apple" in name.lower():
        msg = f"OK — healthcheck Apple Inc. (CIK {_CIK_HEALTHCHECK}) en {elapsed_ms}ms"
        save_test_result("sec_edgar", ok=True, message=msg)
        return {"ok": True, "message": msg, "elapsed_ms": elapsed_ms}
    msg = f"Réponse 200 mais format inattendu (name=«{name[:40]}»)"
    save_test_result("sec_edgar", ok=False, message=msg)
    return {"ok": False, "message": msg, "elapsed_ms": elapsed_ms}


__all__ = [
    "SEC_DATA_BASE_URL",
    "CONFIDENCE_CIK_DIRECT",
    "CONFIDENCE_TICKER",
    "CONFIDENCE_NAME_EXACT",
    "CONFIDENCE_NAME_FUZZY",
    "CONFIDENCE_NOT_FOUND",
    "CONFIDENCE_NO_USER_AGENT",
    "SecEdgarResolutionLog",
    "build_sec_edgar_blocks",
    "get_sec_edgar_status",
    "test_connection",
]
