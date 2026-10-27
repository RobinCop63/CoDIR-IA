"""
CoDIR-IA — utils/opensanctions_tool.py — v16.5.68

Source de données : OpenSanctions
URL : https://api.opensanctions.org/

Couverture :
  - 200+ listes de sanctions internationales agrégées (OFAC, EU, UN, UK, FR, etc.)
  - PEP (Personnes Exposées Politiquement) et leurs proches
  - Watchlists (criminalité organisée, terrorisme, etc.)
  - Données : nom, alias, datasets concernés, score de matching
  - **Clé API requise** — plan gratuit limité, plans payants pour usage commercial

Cas d'usage CoDIR-IA :
  - Vérifier la conformité KYC/AML d'une société, ses dirigeants, ses investisseurs
  - Identifier les risques de sanctions internationales (signal go/no-go critique)
  - Détecter les PEP dans la chaîne de propriété (PE, M&A, due diligence)

Architecture :
  - Cache disque ExternalSourceCache (TTL 7 jours — listes mises à jour quotidiennement)
  - Recherche par nom uniquement (pas d'identifiant universel comme LEI)
  - Format dual : full / summary
  - Gestion gracieuse des cas négatifs (pas de match = signal positif !)

Sécurité :
  - Refus si pas de clé
  - Header Authorization: ApiKey {key}
  - Aucune donnée perso transmise sauf le nom recherché (qui est dans le brief)

Particularité importante :
  - Un brief CoDIR ne contient PAS toujours un nom de personne à vérifier.
  - On utilise OpenSanctions principalement sur la **société analysée**, et optionnellement
    sur les dirigeants si Pappers en a remonté (intégration codir_engine en Phase 4).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from typing import Optional, Dict, List, Any

from .external_sources_common import (
    ExternalSourceCache,
    safe_get,
    now_iso,
    save_test_result,
    make_key_preview,
    DEFAULT_TIMEOUT_S,
)


# ── Constantes ────────────────────────────────────────────────────────────────

OPENSANCTIONS_BASE_URL = "https://api.opensanctions.org"
_REQUEST_TIMEOUT = DEFAULT_TIMEOUT_S
_TTL_SEARCH      = 7 * 24 * 3600    # 7 jours — listes mises à jour quotidiennement
_DEFAULT_DATASET = "default"        # agrégateur de toutes les sources
_DEFAULT_LIMIT   = 5                # max 5 résultats par recherche

# Schéma OpenSanctions (FollowTheMoney)
SCHEMA_PERSON         = "Person"
SCHEMA_COMPANY        = "Company"
SCHEMA_ORGANIZATION   = "Organization"
SCHEMA_LEGAL_ENTITY   = "LegalEntity"

# Niveaux de confiance
CONFIDENCE_HIGH_RISK    = "HIGH_RISK"      # Match score >= 0.85 → préoccupation
CONFIDENCE_POSSIBLE     = "POSSIBLE_MATCH" # 0.65 <= score < 0.85
CONFIDENCE_WEAK         = "WEAK_MATCH"     # 0.45 <= score < 0.65
CONFIDENCE_NO_MATCH     = "NO_MATCH"       # < 0.45 ou aucun résultat
CONFIDENCE_NOT_CONFIGURED = "NOT_CONFIGURED"  # pas de clé API

# Seuils
_THRESHOLD_HIGH      = 0.85
_THRESHOLD_POSSIBLE  = 0.65
_THRESHOLD_WEAK      = 0.45


# ── Cache disque ──────────────────────────────────────────────────────────────

_cache = ExternalSourceCache("opensanctions_cache.json", ttl_default=_TTL_SEARCH)


# ── Log de résolution audit-ready ────────────────────────────────────────────

@dataclass
class OpenSanctionsResolutionLog:
    """Trace audit-ready de la résolution OpenSanctions."""
    input_preview: str = ""
    path: str = ""              # CONFIDENCE_*
    source: str = ""            # NAME_SEARCH | EMPTY | NO_KEY
    query: str = ""
    schema_searched: str = ""
    n_results: int = 0
    top_score: float = 0.0
    top_match_name: str = ""
    top_datasets: List[str] = field(default_factory=list)
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
            return f"opensanctions | path={self.path} | error={self.error[:80]}"
        ds_str = ",".join(self.top_datasets[:3]) if self.top_datasets else "—"
        return (f"opensanctions | path={self.path} | source={self.source} | "
                f"query={(self.query or '—')[:30]} | n={self.n_results} | "
                f"score={self.top_score:.2f} | datasets={ds_str} | cache_hit={self.cache_hit}")


# ── Clé API ──────────────────────────────────────────────────────────────────

def _api_key() -> str:
    return (os.getenv("OPENSANCTIONS_API_KEY") or "").strip()


def _headers() -> Dict[str, str]:
    """Headers OpenSanctions : Authorization ApiKey scheme."""
    key = _api_key()
    if not key:
        return {}
    return {"Authorization": f"ApiKey {key}", "Accept": "application/json"}


# ── Appels API ───────────────────────────────────────────────────────────────

def _classify_score(score: float) -> str:
    """Classifie un score de matching OpenSanctions en niveau de confiance."""
    if score >= _THRESHOLD_HIGH:
        return CONFIDENCE_HIGH_RISK
    if score >= _THRESHOLD_POSSIBLE:
        return CONFIDENCE_POSSIBLE
    if score >= _THRESHOLD_WEAK:
        return CONFIDENCE_WEAK
    return CONFIDENCE_NO_MATCH


@lru_cache(maxsize=64)
def _search_by_name(name: str, schema: str = SCHEMA_LEGAL_ENTITY,
                    limit: int = _DEFAULT_LIMIT) -> Dict[str, Any]:
    """
    Recherche OpenSanctions par nom + schéma (Person / Company / LegalEntity).
    Cache disque 7 jours + lru_cache intra-session.

    Retourne un dict avec les clés :
      - 'results': list de records
      - 'total': int (peut être > limit)
      - '_from_cache' / '_cache_age_h' si cache hit
      - '_error' / '_message' si erreur
    """
    name = (name or "").strip()
    if not name or len(name) < 2:
        return {"results": [], "total": 0}

    if not _api_key():
        return {"_error": "no_api_key", "results": [], "total": 0}

    cache_key = f"search_{schema}_{name.lower()[:120]}"
    cached = _cache.get(cache_key)
    if cached is not None:
        cached["_from_cache"] = True
        cached["_cache_age_h"] = _cache.age_hours(cache_key)
        return cached

    res = safe_get(
        f"{OPENSANCTIONS_BASE_URL}/search/{_DEFAULT_DATASET}",
        params={
            "q":      name,
            "schema": schema,
            "limit":  str(limit),
        },
        headers=_headers(),
        timeout=_REQUEST_TIMEOUT,
    )

    if not res.get("ok"):
        return {
            "_error": res.get("error", "unknown"),
            "_message": res.get("message", "")[:200],
            "results": [],
            "total": 0,
        }

    data = res.get("data", {}) or {}
    if not isinstance(data, dict):
        return {"results": [], "total": 0}

    payload = {
        "results": data.get("results", []) or [],
        "total":   data.get("total", {}).get("value", len(data.get("results", []))) if isinstance(data.get("total"), dict) else data.get("total", 0),
    }
    _cache.set(cache_key, payload)
    return payload


# ── Format pour injection dans prompt agent ──────────────────────────────────

_LABELS = {
    "fr": {
        "header_full":      "DONNÉES OPENSANCTIONS — VÉRIFICATION SANCTIONS / PEP",
        "header_summary":   "OPENSANCTIONS — RÉSUMÉ CONFORMITÉ",
        "footer":           "Source : OpenSanctions (api.opensanctions.org). Agrégateur 200+ listes (OFAC, UE, ONU, FR, UK).",
        "query":            "Requête",
        "n_results":        "Nombre de matches",
        "highest_score":    "Score le plus élevé",
        "verdict":          "Verdict",
        "verdict_high":     "🔴 HAUT RISQUE — match fort sur listes de sanctions",
        "verdict_possible": "🟠 MATCH POSSIBLE — vérification humaine recommandée",
        "verdict_weak":     "🟡 MATCH FAIBLE — probablement homonyme",
        "verdict_no":       "🟢 Aucun match détecté dans OpenSanctions à ce stade. Ce résultat ne constitue pas une validation KYC/AML ni une absence certaine de risque.",
        "no_key":           "⚠️ OpenSanctions non configuré — section non exploitée. Renseigner OPENSANCTIONS_API_KEY en page Config.",
        "match_name":       "Nom matché",
        "match_score":      "Score",
        "match_datasets":   "Listes (datasets)",
        "match_topics":     "Topics",
        "match_countries":  "Pays",
        "match_first_seen": "Première référence",
        "match_last_seen":  "Dernière mise à jour",
    },
    "en": {
        "header_full":      "OPENSANCTIONS DATA — SANCTIONS / PEP CHECK",
        "header_summary":   "OPENSANCTIONS — COMPLIANCE SUMMARY",
        "footer":           "Source: OpenSanctions (api.opensanctions.org). Aggregator of 200+ lists (OFAC, EU, UN, FR, UK).",
        "query":            "Query",
        "n_results":        "Number of matches",
        "highest_score":    "Highest score",
        "verdict":          "Verdict",
        "verdict_high":     "🔴 HIGH RISK — strong match on sanctions lists",
        "verdict_possible": "🟠 POSSIBLE MATCH — human verification recommended",
        "verdict_weak":     "🟡 WEAK MATCH — likely a namesake",
        "verdict_no":       "🟢 No match detected in OpenSanctions at this stage. This result does not constitute KYC/AML validation nor a certain absence of risk.",
        "no_key":           "⚠️ OpenSanctions not configured — section not used. Set OPENSANCTIONS_API_KEY on the Config page.",
        "match_name":       "Match name",
        "match_score":      "Score",
        "match_datasets":   "Lists (datasets)",
        "match_topics":     "Topics",
        "match_countries":  "Countries",
        "match_first_seen": "First seen",
        "match_last_seen":  "Last seen",
    },
}


def _t(key: str, lang: str) -> str:
    return _LABELS.get(lang, _LABELS["en"]).get(key, key)


def _verdict_label(confidence: str, lang: str) -> str:
    mapping = {
        CONFIDENCE_HIGH_RISK: "verdict_high",
        CONFIDENCE_POSSIBLE:  "verdict_possible",
        CONFIDENCE_WEAK:      "verdict_weak",
        CONFIDENCE_NO_MATCH:  "verdict_no",
    }
    return _t(mapping.get(confidence, "verdict_no"), lang)


def _get_props_list(record: Dict[str, Any], key: str) -> List[str]:
    """Extrait une liste de strings depuis record['properties'][key]."""
    if not isinstance(record, dict):
        return []
    props = record.get("properties", {})
    if not isinstance(props, dict):
        return []
    val = props.get(key, [])
    if isinstance(val, list):
        return [str(x) for x in val if x]
    if val:
        return [str(val)]
    return []


def _format_match(record: Dict[str, Any], lang: str, scope: str = "full") -> List[str]:
    """Formate un record OpenSanctions en quelques lignes."""
    if not isinstance(record, dict):
        return []
    name      = record.get("caption", "") or " / ".join(_get_props_list(record, "name")[:1])
    score     = float(record.get("score", 0))
    datasets  = record.get("datasets", []) or []
    topics    = _get_props_list(record, "topics")
    countries = _get_props_list(record, "country")
    first_seen = (record.get("first_seen", "") or "")[:10]
    last_seen  = (record.get("last_seen", "") or "")[:10]

    lines = []
    if name:
        lines.append(f"  • {_t('match_name', lang)} : {name}")
    lines.append(f"    {_t('match_score', lang)} : {score:.2f}")
    if datasets:
        ds_str = ", ".join(str(d) for d in datasets[:5])
        if len(datasets) > 5:
            ds_str += f" (+{len(datasets) - 5})"
        lines.append(f"    {_t('match_datasets', lang)} : {ds_str}")
    if scope == "full":
        if topics:
            lines.append(f"    {_t('match_topics', lang)} : {', '.join(topics[:5])}")
        if countries:
            lines.append(f"    {_t('match_countries', lang)} : {', '.join(countries[:5])}")
        if first_seen:
            lines.append(f"    {_t('match_first_seen', lang)} : {first_seen}")
        if last_seen and last_seen != first_seen:
            lines.append(f"    {_t('match_last_seen', lang)} : {last_seen}")
    return lines


def _format_results(query: str, results: List[Dict[str, Any]], confidence: str,
                    lang: str = "fr", scope: str = "full") -> str:
    """Formate les résultats OpenSanctions en texte structuré."""
    header = _t("header_summary" if scope == "summary" else "header_full", lang)
    lines = [header, ""]
    lines.append(f"{_t('query', lang)} : {query}")
    lines.append(f"{_t('n_results', lang)} : {len(results)}")
    if results:
        top_score = max((float(r.get("score", 0)) for r in results), default=0.0)
        lines.append(f"{_t('highest_score', lang)} : {top_score:.2f}")
    lines.append("")
    lines.append(f"{_t('verdict', lang)} : {_verdict_label(confidence, lang)}")

    if scope == "full" and results and confidence != CONFIDENCE_NO_MATCH:
        lines.append("")
        # Trier par score desc et n'afficher que les 3 meilleurs
        sorted_results = sorted(results, key=lambda r: float(r.get("score", 0)), reverse=True)[:3]
        for rec in sorted_results:
            lines.extend(_format_match(rec, lang, scope=scope))
            lines.append("")

    lines.append(_t("footer", lang))
    return "\n".join(lines).strip()


# ── Entry point principal ────────────────────────────────────────────────────

def build_opensanctions_blocks(
    target_name: str,
    schema: str = SCHEMA_LEGAL_ENTITY,
    lang: str = "fr",
) -> Dict[str, Any]:
    """
    Vérifie un nom contre les listes OpenSanctions.

    Args:
        target_name : raison sociale ou nom de personne à vérifier
        schema      : "Person" / "Company" / "LegalEntity" (défaut)
        lang        : "fr" / "en"

    Retourne :
      {
        "full":           <texte format full>,
        "summary":        <texte format summary>,
        "primary":        <target_name>,
        "n_results":      <int>,
        "top_score":      <float>,
        "confidence":     <CONFIDENCE_*>,
        "resolution_log": <OpenSanctionsResolutionLog>,
      }

    Garantie : si pas de clé API, retourne NOT_CONFIGURED. Ne lève jamais d'exception.
    """
    rlog = OpenSanctionsResolutionLog(input_preview=(target_name or "")[:120])
    rlog.query = target_name
    rlog.schema_searched = schema

    # 1) Garde-fou : clé requise
    if not _api_key():
        rlog.path = CONFIDENCE_NOT_CONFIGURED
        rlog.source = "NO_KEY"
        rlog.error = "api_key_missing"
        return {
            "full": "", "summary": "",
            "primary": target_name, "n_results": 0, "top_score": 0.0,
            "confidence": CONFIDENCE_NOT_CONFIGURED,
            "resolution_log": rlog,
        }

    # 2) Garde-fou : nom trop court (évite spam API)
    name = (target_name or "").strip()
    if not name or len(name) < 2:
        rlog.path = CONFIDENCE_NO_MATCH
        rlog.source = "EMPTY"
        return {
            "full": "", "summary": "",
            "primary": "", "n_results": 0, "top_score": 0.0,
            "confidence": CONFIDENCE_NO_MATCH,
            "resolution_log": rlog,
        }

    # 3) Recherche
    payload = _search_by_name(name, schema=schema)
    if "_error" in payload:
        rlog.path = CONFIDENCE_NO_MATCH
        rlog.source = "NAME_SEARCH"
        rlog.error = payload.get("_error", "unknown")
        return {
            "full": "", "summary": "",
            "primary": name, "n_results": 0, "top_score": 0.0,
            "confidence": CONFIDENCE_NO_MATCH,
            "resolution_log": rlog,
        }

    rlog.cache_hit = bool(payload.get("_from_cache"))
    rlog.cache_age_h = payload.get("_cache_age_h")

    results = payload.get("results", []) or []
    rlog.n_results = len(results)

    if not results:
        confidence = CONFIDENCE_NO_MATCH
        top_score = 0.0
    else:
        top_score = max((float(r.get("score", 0)) for r in results), default=0.0)
        confidence = _classify_score(top_score)
        # Récupérer top match metadata
        top = max(results, key=lambda r: float(r.get("score", 0)))
        rlog.top_match_name = top.get("caption", "")[:120]
        rlog.top_datasets = list(top.get("datasets", []) or [])[:5]

    rlog.path = confidence
    rlog.source = "NAME_SEARCH"
    rlog.top_score = round(top_score, 4)

    full_block    = _format_results(name, results, confidence, lang=lang, scope="full")
    summary_block = _format_results(name, results, confidence, lang=lang, scope="summary")
    rlog.tokens_est_full    = len(full_block) // 4
    rlog.tokens_est_summary = len(summary_block) // 4

    return {
        "full":           full_block,
        "summary":        summary_block,
        "primary":        name,
        "n_results":      len(results),
        "top_score":      round(top_score, 4),
        "confidence":     confidence,
        "resolution_log": rlog,
    }


# ── Status & test de connexion ───────────────────────────────────────────────

def get_opensanctions_status() -> Dict[str, Any]:
    """Statut OpenSanctions pour la page Config."""
    key = _api_key()
    return {
        "configured":   bool(key),
        "key_preview":  make_key_preview(key),
        "requires_key": True,
    }


def test_connection(timeout: int = _REQUEST_TIMEOUT) -> Dict[str, Any]:
    """
    Test de connexion OpenSanctions :
      - Vérifie présence de la clé
      - Appelle un endpoint /search avec un nom témoin connu (« Vladimir Putin »)
      - Vérifie qu'on a bien au moins 1 résultat (donc API joignable + clé valide)

    Note : le nom témoin doit retourner un résultat (Putin est listé).
    Si l'API retourne 0 résultat sur Putin, c'est probablement un problème de clé/quota.
    """
    if not _api_key():
        msg = "Clé OpenSanctions absente — saisir OPENSANCTIONS_API_KEY dans Config."
        save_test_result("opensanctions", ok=False, message=msg)
        return {"ok": False, "message": msg, "elapsed_ms": 0}

    t0 = time.time()
    res = safe_get(
        f"{OPENSANCTIONS_BASE_URL}/search/{_DEFAULT_DATASET}",
        params={"q": "Vladimir Putin", "schema": SCHEMA_PERSON, "limit": "1"},
        headers=_headers(),
        timeout=timeout,
    )
    elapsed_ms = int((time.time() - t0) * 1000)

    if not res.get("ok"):
        sc = res.get("status_code", "")
        if sc == 401 or sc == 403:
            msg = f"Authentification refusée (HTTP {sc}) — vérifier la clé API."
        else:
            msg = f"{res.get('error', 'unknown')} — {res.get('message', '')[:120]}"
        save_test_result("opensanctions", ok=False, message=msg)
        return {"ok": False, "message": msg, "elapsed_ms": elapsed_ms}

    data = res.get("data", {})
    n = len(data.get("results", []) or []) if isinstance(data, dict) else 0
    if n >= 1:
        msg = f"OK — healthcheck Putin (dataset {_DEFAULT_DATASET}) en {elapsed_ms}ms"
        save_test_result("opensanctions", ok=True, message=msg)
        return {"ok": True, "message": msg, "elapsed_ms": elapsed_ms}
    msg = f"API joignable mais 0 résultat sur Putin — quota ou clé invalide ?"
    save_test_result("opensanctions", ok=False, message=msg)
    return {"ok": False, "message": msg, "elapsed_ms": elapsed_ms}


__all__ = [
    "OPENSANCTIONS_BASE_URL",
    "SCHEMA_PERSON", "SCHEMA_COMPANY", "SCHEMA_ORGANIZATION", "SCHEMA_LEGAL_ENTITY",
    "CONFIDENCE_HIGH_RISK", "CONFIDENCE_POSSIBLE", "CONFIDENCE_WEAK",
    "CONFIDENCE_NO_MATCH", "CONFIDENCE_NOT_CONFIGURED",
    "OpenSanctionsResolutionLog",
    "build_opensanctions_blocks",
    "get_opensanctions_status",
    "test_connection",
]
