"""v62.13.9.4.50 — FAITS EXTERNES DATÉS ET MULTI-EXERCICES (décision Robin du 30/09/2026 : « on met tout »).

Les connecteurs existants (Pappers, SEC EDGAR, Companies House, GLEIF) produisent du TEXTE de contexte pour les
agents. Ce module en tire des FAITS STRUCTURÉS, un par métrique et par exercice, avec leur source, leur périmètre et
leur devise. Ils servent à trois choses, jamais à réécrire un texte :

1. la règle du DERNIER RÉALISÉ DATÉ (cartes clés, situation actuelle) quand les pièces fournies ne portent pas la
   métrique ;
2. le SOUTIEN d'une ligne qui cite une valeur publiée (claims de statut ``CONFIRMED_IN_FILING`` ou
   ``CONFIRMED_IN_REGISTRY``) ;
3. les contrôles qui exigent l'EXERCICE ANTÉRIEUR (variation en points de base, marge FY-1) — les pièces fournies
   n'en donnent volontairement que l'exercice courant.

Règles (contre-recette ChatGPT du 30/09, « le choix de la source dépend de l'entité, de la juridiction et du
périmètre ») :
- routage par identifiant et juridiction, jamais dans un ordre fixe : CIK → SEC (consolidé, 10-K) ; SIREN → Pappers
  (comptes déposés, sociaux sauf mention consolidée) ; numéro Companies House → comptes iXBRL déposés ;
  LEI → GLEIF, IDENTITÉ SEULEMENT (GLEIF ne publie aucun chiffre) ;
- les pièces fournies passent avant : un fait externe ne remplace jamais un fait confirmé à la page ; en cas d'écart,
  la pièce est affichée et l'écart signalé ;
- aucune valeur n'est inventée ni arrondie ici ; l'exercice est l'année de CLÔTURE (« FY2025 » = clos en 2025).

Les fonctions ``parse_*`` sont pures (testées hors réseau) ; les fonctions ``fetch_*`` passent par les connecteurs et
leurs garde-fous (clé, User-Agent SEC, cache, délai), et ne lèvent jamais d'exception.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Iterable, Mapping

FILING_STATUS = "CONFIRMED_IN_FILING"          # dépôt réglementaire (10-K, comptes déposés iXBRL)
REGISTRY_STATUS = "CONFIRMED_IN_REGISTRY"      # registre agrégé (Pappers)


@dataclass
class ExternalFact:
    metric: str                 # REVENUE, GROSS_PROFIT, OPERATING_PROFIT, NET_INCOME, CASH, INVENTORIES…
    period: str                 # « FY2025 » : année de clôture
    period_end: str             # « 2025-08-31 »
    value: float                # dans l'unité de la devise (pas de mise à l'échelle implicite)
    currency: str               # USD, EUR, GBP
    source: str                 # « SEC EDGAR — 10-K déposé le 2025-10-22 (0000105132-25-000067) »
    source_url: str = ""
    perimeter: str = ""         # « consolidé », « comptes sociaux », « comptes de groupe »
    status: str = FILING_STATUS
    concept: str = ""           # concept XBRL / champ du registre, pour la traçabilité
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ── SEC EDGAR : données XBRL « companyfacts » ──────────────────────────────────────────────────────
# Concepts us-gaap par métrique, par ordre de préférence (le premier présent pour l'exercice l'emporte).
SEC_CONCEPTS = {
    "REVENUE": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax"),
    "COST_OF_REVENUE": ("CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"),
    "GROSS_PROFIT": ("GrossProfit",),
    "OPERATING_PROFIT": ("OperatingIncomeLoss",),
    "NET_INCOME": ("NetIncomeLoss", "ProfitLoss"),
    "CASH": ("CashAndCashEquivalentsAtCarryingValue",),
    "INVENTORIES": ("InventoryNet",),
    "TRADE_RECEIVABLES": ("AccountsReceivableNetCurrent",),
    "TOTAL_ASSETS": ("Assets",),
    # 9.4.53 — contre-recette du 06/10 (F03) : la dette et le DSO étaient déclarés absents parce que les pages du 10-K joint
    # étaient illisibles (couche texte décalée). Le dépôt XBRL de la SEC, lu par le produit, les porte : ils en sont repris
    # avec leur source plutôt que déclarés absents.
    "LONG_TERM_DEBT": ("LongTermDebtNoncurrent", "LongTermDebt", "LongTermNotesPayable", "LongTermDebtAndCapitalLeaseObligations"),
    "SHORT_TERM_DEBT": ("ShortTermBorrowings", "LongTermDebtCurrent", "LinesOfCreditCurrent"),
    # 9.4.55 — contre-recette du 07/10 (F02, F03) : base avant impôt, impôt et nombre d'actions diluées déclarés
    # « inventés » ou absents alors que le dépôt officiel les porte
    "PRETAX_INCOME": ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic"),
    "INCOME_TAX": ("IncomeTaxExpenseBenefit",),
}
_FLOW = {"REVENUE", "COST_OF_REVENUE", "GROSS_PROFIT", "OPERATING_PROFIT", "NET_INCOME", "PRETAX_INCOME", "INCOME_TAX"}


def _days(a: str, b: str) -> int | None:
    try:
        y1, m1, d1 = (int(x) for x in a[:10].split("-"))
        y2, m2, d2 = (int(x) for x in b[:10].split("-"))
        return (date(y2, m2, d2) - date(y1, m1, d1)).days
    except Exception:
        return None


def parse_sec_companyfacts(data: Mapping[str, Any]) -> list[ExternalFact]:
    """Faits annuels des 10-K (et 10-K/A) : un par métrique et par exercice ; le dépôt le plus récent l'emporte."""
    out: dict[tuple, ExternalFact] = {}
    if not isinstance(data, Mapping):
        return []
    gaap = ((data.get("facts") or {}).get("us-gaap") or {}) if isinstance(data.get("facts"), Mapping) else {}
    cik = str(data.get("cik") or "").lstrip("0")
    for metric, concepts in SEC_CONCEPTS.items():
        for concept in concepts:
            node = gaap.get(concept)
            if not isinstance(node, Mapping):
                continue
            usd = ((node.get("units") or {}).get("USD") or []) if isinstance(node.get("units"), Mapping) else []
            found = False
            for row in usd:
                if not isinstance(row, Mapping):
                    continue
                form = str(row.get("form") or "")
                if form not in ("10-K", "10-K/A") or str(row.get("fp") or "") != "FY":
                    continue
                end = str(row.get("end") or "")
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end):
                    continue
                if metric in _FLOW:
                    span = _days(str(row.get("start") or ""), end)
                    if span is None or not (350 <= span <= 380):
                        continue                          # un exercice complet, jamais un trimestre
                try:
                    val = float(row.get("val"))
                except (TypeError, ValueError):
                    continue
                key = (metric, end)
                filed = str(row.get("filed") or "")
                prev = out.get(key)
                if prev is not None and prev.concept != concept:
                    continue                              # le concept préféré de la métrique l'emporte
                if prev is not None and str(prev.extras.get("filed") or "") >= filed:
                    continue
                accn = str(row.get("accn") or "")
                out[key] = ExternalFact(
                    metric=metric, period="FY" + end[:4], period_end=end, value=val, currency="USD",
                    source=f"SEC EDGAR — {form} déposé le {filed} ({accn})" if accn else f"SEC EDGAR — {form}",
                    source_url=(f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}/" if cik and accn else ""),
                    perimeter="consolidé", status=FILING_STATUS, concept=concept, extras={"filed": filed, "form": form})
                found = True
            if found:
                break                                     # concept préféré trouvé pour cette métrique
    return sorted(out.values(), key=lambda f: (f.metric, f.period_end))


def fetch_sec_companyfacts(cik: str) -> dict:
    """Appel réseau borné (User-Agent SEC obligatoire, cache du connecteur). Ne lève jamais d'exception."""
    try:
        from utils.sec_edgar_tool import (SEC_DATA_BASE_URL, _headers, _is_valid_user_agent, _normalize_cik,
                                          _user_agent, _REQUEST_TIMEOUT)
        from utils.external_sources_common import safe_get
        if not _is_valid_user_agent(_user_agent()):
            return {"_error": "no_user_agent"}
        cik10 = _normalize_cik(cik)
        if not re.fullmatch(r"\d{10}", cik10 or ""):
            return {"_error": "bad_cik"}
        res = safe_get(f"{SEC_DATA_BASE_URL}/api/xbrl/companyfacts/CIK{cik10}.json", headers=_headers(),
                       timeout=_REQUEST_TIMEOUT)
        if not res.get("ok"):
            return {"_error": res.get("error", "unknown")}
        return res.get("data") if isinstance(res.get("data"), Mapping) else {"_error": "not_json"}
    except Exception as exc:  # pragma: no cover - réseau
        return {"_error": f"{type(exc).__name__}"}


# ── Pappers : finances des comptes déposés (sociétés françaises) ──────────────────────────────────
PAPPERS_FIELDS = {"REVENUE": ("chiffre_affaires",), "NET_INCOME": ("resultat",),
                  "OPERATING_PROFIT": ("resultat_exploitation",), "HEADCOUNT": ("effectif",)}


def parse_pappers_finances(entreprise: Mapping[str, Any]) -> list[ExternalFact]:
    """``finances`` de la fiche Pappers : un fait par champ et par exercice clos. Comptes confidentiels : rien."""
    out: list[ExternalFact] = []
    if not isinstance(entreprise, Mapping) or entreprise.get("comptes_confidentiels"):
        return out
    for row in entreprise.get("finances") or []:
        if not isinstance(row, Mapping):
            continue
        end = str(row.get("date_de_cloture_exercice") or "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end):
            y = row.get("annee")
            if not isinstance(y, int):
                continue
            end = f"{y}-12-31"
        consolidated = bool(row.get("comptes_consolides") or row.get("consolide"))
        for metric, keys in PAPPERS_FIELDS.items():
            for k in keys:
                v = row.get(k)
                if isinstance(v, (int, float)):
                    out.append(ExternalFact(
                        metric=metric, period="FY" + end[:4], period_end=end, value=float(v),
                        currency="EUR" if metric != "HEADCOUNT" else "", perimeter="consolidé" if consolidated else "comptes sociaux",
                        source=f"Pappers — comptes déposés, exercice clos le {end}", status=REGISTRY_STATUS, concept=k))
                    break
    return out


# ── Companies House : comptes déposés au format iXBRL (Royaume-Uni) ──────────────────────────────
CH_CONCEPTS = {
    "REVENUE": ("Turnover", "TurnoverRevenue", "Revenue"),
    "GROSS_PROFIT": ("GrossProfitLoss",),
    "OPERATING_PROFIT": ("OperatingProfitLoss",),
    "NET_INCOME": ("ProfitLoss", "ProfitLossForPeriod"),
    "CASH": ("CashBankOnHand", "CashCashEquivalents"),
    "TOTAL_ASSETS": ("TotalAssets",),
    "NET_ASSETS": ("NetAssetsLiabilities",),
}


def parse_ch_ixbrl(xhtml: str, *, source: str = "Companies House — comptes déposés") -> list[ExternalFact]:
    """Lit les ``ix:nonFraction`` d'un compte iXBRL : période de chaque contexte, échelle, signe, format décimal.

    Un dépôt en PDF scanné n'a pas de balise : aucune valeur n'en sort (jamais d'OCR ni d'estimation)."""
    text = str(xhtml or "")
    if "nonFraction" not in text:
        return []
    ctx: dict[str, str] = {}
    for m in re.finditer(r"<xbrli:context[^>]*\bid=\"([^\"]+)\"[^>]*>(.*?)</xbrli:context>", text, re.S | re.I):
        body = m.group(2)
        end = re.search(r"<xbrli:(?:endDate|instant)>\s*(\d{4}-\d{2}-\d{2})", body, re.I)
        if end and "xbrldi:explicitMember" not in body:          # contexte sans dimension : la société elle-même
            ctx[m.group(1)] = end.group(1)
    group = bool(re.search(r"(?i)consolidated|group\s+accounts|comptes\s+de\s+groupe", text[:20000]))
    out: dict[tuple, ExternalFact] = {}
    for m in re.finditer(r"<ix:nonFraction\b([^>]*)>(.*?)</ix:nonFraction>", text, re.S | re.I):
        attrs, raw = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        name = re.search(r'\bname="(?:[\w-]+:)?([\w]+)"', attrs)
        cref = re.search(r'\bcontextRef="([^"]+)"', attrs)
        if not name or not cref or cref.group(1) not in ctx:
            continue
        metric = next((k for k, names in CH_CONCEPTS.items() if name.group(1) in names), None)
        if not metric:
            continue
        fmt = (re.search(r'\bformat="([^"]+)"', attrs) or [None, ""])[1] or ""
        s = raw.replace(" ", "").replace("\u00a0", "").strip("()")   # les parenthèses d'affichage ne sont pas le signe
        if raw in ("-", "—", "") or re.search(r"zerodash|fixed-zero", fmt, re.I):
            val = 0.0
        else:
            if "comma" in fmt.lower() or re.search(r"numcommadecimal", fmt, re.I):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
            try:
                val = float(s)
            except ValueError:
                continue
        scale = re.search(r'\bscale="(-?\d+)"', attrs)
        if scale:
            val *= 10 ** int(scale.group(1))
        if re.search(r'\bsign="-"', attrs):
            val = -val
        unit = re.search(r'\bunitRef="([^"]+)"', attrs)
        cur = "GBP" if not unit or "gbp" in unit.group(1).lower() else unit.group(1).upper()[:3]
        end = ctx[cref.group(1)]
        out.setdefault((metric, end), ExternalFact(
            metric=metric, period="FY" + end[:4], period_end=end, value=val, currency=cur,
            perimeter="comptes de groupe" if group else "comptes sociaux", source=source,
            status=FILING_STATUS, concept=name.group(1)))
    return sorted(out.values(), key=lambda f: (f.metric, f.period_end))


# ── Routage et sélection ───────────────────────────────────────────────────────────────────────────
def route_sources(identifiers: Mapping[str, str]) -> list[str]:
    """Sources à interroger, selon les identifiants DISPONIBLES (jamais un ordre fixe entre juridictions)."""
    ids = {k.lower(): str(v or "").strip() for k, v in (identifiers or {}).items() if str(v or "").strip()}
    out = []
    if ids.get("cik"):
        out.append("sec")
    if ids.get("siren"):
        out.append("pappers")
    if ids.get("company_number"):
        out.append("companies_house")
    if ids.get("lei"):
        out.append("gleif_identity")
    return out


def latest_by_metric(facts: Iterable[ExternalFact | Mapping[str, Any]]) -> dict[str, dict]:
    """Dernier réalisé connu par métrique (la clôture la plus récente)."""
    best: dict[str, dict] = {}
    for f in facts or ():
        d = f.to_dict() if isinstance(f, ExternalFact) else dict(f)
        m = d.get("metric")
        if m and (m not in best or str(d.get("period_end")) > str(best[m].get("period_end"))):
            best[m] = d
    return best


def as_support_claims(facts: Iterable[ExternalFact | Mapping[str, Any]], lang: str = "fr") -> list[dict]:
    """Claims de soutien tirés des faits externes (statut de dépôt ou de registre, provenance obligatoire)."""
    labels = {"REVENUE": ("Revenue", "Chiffre d'affaires"), "GROSS_PROFIT": ("Gross profit", "Marge brute"),
              "OPERATING_PROFIT": ("Operating profit", "Résultat d'exploitation"), "NET_INCOME": ("Net income", "Résultat net"),
              "CASH": ("Cash and cash equivalents", "Trésorerie"), "INVENTORIES": ("Inventories", "Stocks"),
              "TRADE_RECEIVABLES": ("Trade receivables", "Créances clients"), "TOTAL_ASSETS": ("Total assets", "Total actif"),
              "COST_OF_REVENUE": ("Cost of sales", "Coût des ventes"), "HEADCOUNT": ("Headcount", "Effectif"),
              "NET_ASSETS": ("Net assets", "Actif net")}
    out = []
    for f in facts or ():
        d = f.to_dict() if isinstance(f, ExternalFact) else dict(f)
        en, fr = labels.get(d.get("metric"), (d.get("metric"), d.get("metric")))
        cur = d.get("currency") or ""
        out.append({
            "claim_id": f"EXT-{d.get('metric')}-{d.get('period_end')}", "claim_type": "FACT",
            "metric_id": d.get("metric"), "label": f"{en} / {fr}", "period": d.get("period"),
            "proof_status": d.get("status") or FILING_STATUS, "source_doc": d.get("source"),
            "source_url": d.get("source_url") or "", "perimeter": d.get("perimeter") or "",
            "numeric_components": [{"kind": "money" if cur else "number", "value": float(d.get("value") or 0)}],
            "currency": cur, "external": True,
            "compact_executive_line": (f"{fr} : {float(d.get('value') or 0):,.0f} {cur} ({d.get('period')})" if cur
                                       else f"{fr} : {float(d.get('value') or 0):g} ({d.get('period')})"),
        })
    return out


CH_DOCUMENT_BASE_URL = "https://document-api.company-information.service.gov.uk"


def fetch_ch_latest_accounts_ixbrl(company_number: str) -> dict:
    """Derniers comptes déposés au format iXBRL : historique des dépôts (catégorie comptes) → métadonnées du
    document → contenu XHTML. Clé d'API Companies House obligatoire ; un dépôt sans version iXBRL (PDF scanné) est
    signalé comme tel, sans valeur. Ne lève jamais d'exception."""
    try:
        from utils.companies_house_tool import CH_BASE_URL, _api_key, _headers, _normalize_company_number
        from utils.external_sources_common import safe_get, safe_get_bytes
        if not _api_key():
            return {"_error": "no_api_key"}
        num = _normalize_company_number(company_number)
        if not num:
            return {"_error": "bad_company_number"}
        hist = safe_get(f"{CH_BASE_URL}/company/{num}/filing-history", params={"category": "accounts", "items_per_page": 5},
                        headers=_headers())
        if not hist.get("ok"):
            return {"_error": hist.get("error", "unknown")}
        items = ((hist.get("data") or {}).get("items") or []) if isinstance(hist.get("data"), Mapping) else []
        for it in items:
            meta_url = ((it.get("links") or {}).get("document_metadata") or "") if isinstance(it, Mapping) else ""
            if not meta_url:
                continue
            meta = safe_get(meta_url, headers=_headers())
            res = ((meta.get("data") or {}).get("resources") or {}) if meta.get("ok") and isinstance(meta.get("data"), Mapping) else {}
            if "application/xhtml+xml" not in res:
                return {"_error": "no_ixbrl", "made_up_to": str(it.get("description_values", {}).get("made_up_date") or "")}
            hdr = dict(_headers()); hdr["Accept"] = "application/xhtml+xml"
            # clé distincte de l'API documents si l'utilisateur l'a saisie (option avancée des réglages)
            import os as _os50, base64 as _b6450
            _dk50 = (_os50.getenv("COMPANIES_HOUSE_DOCUMENT_API_KEY") or "").strip()
            if _dk50:
                hdr["Authorization"] = "Basic " + _b6450.b64encode(f"{_dk50}:".encode()).decode()
            content = safe_get_bytes(meta_url.rstrip("/") + "/content", headers=hdr)
            if content.get("ok"):
                raw = content.get("data")
                text = raw.decode("utf-8", "ignore") if isinstance(raw, (bytes, bytearray)) else str(raw or "")
                return {"ixbrl": text, "date": str(it.get("date") or ""), "transaction_id": str(it.get("transaction_id") or "")}
            return {"_error": content.get("error", "unknown")}
        return {"_error": "no_accounts_filing"}
    except Exception as exc:  # pragma: no cover - réseau
        return {"_error": f"{type(exc).__name__}"}


def cik_from_documents(text: str) -> str:
    """CIK lu dans les pièces : numéro de dépôt EDGAR (« <CIK à 10 chiffres>-AA-NNNNNN ») ou en-tête « Central Index Key »."""
    s = str(text or "")[:400000]
    m = (re.search(r"(?<!\d)(\d{10})-\d{2}-\d{6}(?!\d)", s)       # « …-000067_wdfc… » : pas de \b avant « _ »
         or re.search(r"(?i)\b(?:central\s+index\s+key|CIK)\s*(?:no\.?|number)?\s*[:#]?\s*(\d{4,10})\b", s))
    return m.group(1).zfill(10) if m else ""


def _same_entity50(entity_name: str, expected: str) -> bool:
    """Le nom déclaré par le registre et la société analysée partagent leur premier mot distinctif."""
    norm = lambda s: [w for w in re.findall(r"[a-z0-9]+", str(s or "").lower().replace("-", "")) if w not in
                      {"the", "inc", "co", "corp", "corporation", "company", "plc", "sa", "sas", "ltd", "limited", "group", "groupe"}]
    a, b = norm(entity_name), norm(expected)
    return bool(a and b and (a[0] == b[0] or a[0].startswith(b[0]) or b[0].startswith(a[0])))


def collect_external_facts(identifiers: Mapping[str, str], *, allow_network: bool = True, expected_name: str = "") -> dict:
    """Collecte routée par identifiant ; renvoie {"facts": [...], "sources": {...}, "identity": {...}}. Sans réseau
    autorisé, rien n'est appelé (le résultat le dit)."""
    out: dict = {"facts": [], "sources": {}, "identity": {}}
    if not allow_network:
        out["sources"]["_"] = "network_disabled"
        return out
    ids = {k.lower(): str(v or "").strip() for k, v in (identifiers or {}).items()}
    for src in route_sources(ids):
        try:
            if src == "sec":
                data = fetch_sec_companyfacts(ids["cik"])
                facts = parse_sec_companyfacts(data) if not data.get("_error") else []
                # un CIK lu dans les pièces n'est retenu que si la SEC confirme qu'il s'agit bien de la société analysée
                if facts and ids.get("cik_from_documents") and expected_name and \
                        not _same_entity50(str(data.get("entityName") or ""), expected_name):
                    out["sources"]["sec"] = f"cik_mismatch ({str(data.get('entityName') or '')[:40]})"
                    facts = []
                else:
                    out["sources"]["sec"] = data.get("_error") or f"{len(facts)} faits"
            elif src == "pappers":
                from utils import pappers_tool as _pt
                fiche = (getattr(_pt, "_fetch_fiche", None) or (lambda s: {}))(ids["siren"]) or {}
                facts = parse_pappers_finances(fiche) if isinstance(fiche, Mapping) else []
                out["sources"]["pappers"] = f"{len(facts)} faits"
            elif src == "companies_house":
                doc = fetch_ch_latest_accounts_ixbrl(ids["company_number"])
                facts = parse_ch_ixbrl(doc.get("ixbrl", ""), source=f"Companies House — comptes déposés le {doc.get('date', '')}") if not doc.get("_error") else []
                out["sources"]["companies_house"] = doc.get("_error") or f"{len(facts)} faits"
            else:
                facts = []
                out["identity"]["lei"] = ids.get("lei")
                out["sources"]["gleif"] = "identité seulement"
            out["facts"].extend(f.to_dict() for f in facts)
        except Exception as exc:  # pragma: no cover
            out["sources"][src] = f"error: {type(exc).__name__}"
    return out


# ── Tests de lecture (bouton « Tester la lecture » des Réglages, décision Robin du 01/10/2026) ───────────────────
# Les boutons « Tester la connexion » vérifient l'accès (clé, réseau) ; ceux-ci vérifient en plus que la LECTURE
# nouvelle de ce cycle rend des faits datés, sur un témoin public : montants SEC d'un dépôt 10-K, finances Pappers
# par exercice, comptes iXBRL déposés chez Companies House. Rien n'est conservé ; le message dit ce qui a été lu.
def _fmt_value50(f: ExternalFact | Mapping[str, Any]) -> str:
    d = f.to_dict() if isinstance(f, ExternalFact) else dict(f)
    v = float(d.get("value") or 0)
    cur = {"USD": "$", "EUR": "€", "GBP": "£"}.get(str(d.get("currency") or ""), str(d.get("currency") or ""))
    return f"{v / 1e6:,.1f} M{cur}".replace(",", " ") if cur else f"{v:,.0f}".replace(",", " ")


def test_reading_sec(cik: str = "", lang: str = "fr") -> dict:
    en = str(lang).lower().startswith("en")
    try:
        from utils.sec_edgar_tool import _CIK_HEALTHCHECK
    except Exception:
        _CIK_HEALTHCHECK = "0000320193"
    data = fetch_sec_companyfacts(cik or _CIK_HEALTHCHECK)
    if data.get("_error"):
        why = {"no_user_agent": ("contact SEC (SEC_EDGAR_USER_AGENT) manquant", "SEC contact (SEC_EDGAR_USER_AGENT) missing")}.get(
            data["_error"], (str(data["_error"]), str(data["_error"])))
        return {"ok": False, "message": (f"SEC — lecture impossible : {why[0]}" if not en else f"SEC — reading failed: {why[1]}")}
    facts = parse_sec_companyfacts(data)
    rev = latest_by_metric(facts).get("REVENUE")
    if not facts or not rev:
        return {"ok": False, "message": ("SEC — accès OK mais aucun montant annuel lu" if not en
                                         else "SEC — access OK but no annual amount read")}
    years = sorted({f.period for f in facts if f.metric == "REVENUE"})
    return {"ok": True, "message": (f"SEC — {len(facts)} faits lus ; chiffre d'affaires {rev['period']} : {_fmt_value50(rev)} "
                                    f"({len(years)} exercices)" if not en else
                                    f"SEC — {len(facts)} facts read; revenue {rev['period']}: {_fmt_value50(rev)} ({len(years)} years)")}


def test_reading_pappers(siren: str = "", lang: str = "fr") -> dict:
    en = str(lang).lower().startswith("en")
    try:
        from utils import pappers_tool as _pt
        fiche = _pt._fetch_fiche(siren or _pt._PAPPERS_HEALTHCHECK_SIREN) or {}
    except Exception as exc:
        return {"ok": False, "message": f"Pappers — {type(exc).__name__}"}
    if not isinstance(fiche, Mapping) or fiche.get("_error") or fiche.get("_not_found"):
        why = (fiche or {}).get("_error") or ("introuvable" if not en else "not found")
        return {"ok": False, "message": (f"Pappers — lecture impossible : {why}" if not en else f"Pappers — reading failed: {why}")}
    if fiche.get("comptes_confidentiels"):
        return {"ok": True, "message": ("Pappers — accès OK ; comptes du témoin confidentiels (aucun montant publié)" if not en
                                        else "Pappers — access OK; the witness's accounts are confidential (no published amount)")}
    facts = parse_pappers_finances(fiche)
    rev = latest_by_metric(facts).get("REVENUE")
    if not facts:
        return {"ok": False, "message": ("Pappers — accès OK mais aucune finance lue" if not en else "Pappers — access OK but no financials read")}
    return {"ok": True, "message": (f"Pappers — {len(facts)} faits lus" + (f" ; chiffre d'affaires {rev['period']} : {_fmt_value50(rev)}" if rev else "")
                                    if not en else f"Pappers — {len(facts)} facts read" + (f"; revenue {rev['period']}: {_fmt_value50(rev)}" if rev else ""))}


def test_reading_companies_house(company_number: str = "", lang: str = "fr") -> dict:
    en = str(lang).lower().startswith("en")
    num = (company_number or "").strip()
    if not num:
        try:
            from utils.companies_house_tool import _CN_HEALTHCHECK
            num = str(_CN_HEALTHCHECK or "").strip()
        except Exception:
            num = ""
    if not num:
        return {"ok": None, "message": ("Companies House — saisis un numéro de société britannique pour tester la lecture" if not en
                                        else "Companies House — enter a UK company number to test the reading")}
    doc = fetch_ch_latest_accounts_ixbrl(num)
    err = doc.get("_error")
    if err == "no_ixbrl":
        return {"ok": True, "message": (f"Companies House — accès OK ; derniers comptes de {num} déposés sans iXBRL (PDF) : aucune valeur, comme prévu"
                                        if not en else f"Companies House — access OK; latest accounts of {num} filed without iXBRL (PDF): no value, as designed")}
    if err:
        why = {"no_api_key": ("clé COMPANIES_HOUSE_API_KEY manquante", "COMPANIES_HOUSE_API_KEY missing"),
               "no_accounts_filing": ("aucun dépôt de comptes", "no accounts filing")}.get(err, (str(err), str(err)))
        return {"ok": False, "message": (f"Companies House — lecture impossible : {why[0]}" if not en else f"Companies House — reading failed: {why[1]}")}
    facts = parse_ch_ixbrl(doc.get("ixbrl", ""))
    if not facts:
        return {"ok": False, "message": ("Companies House — compte iXBRL reçu mais aucune valeur reconnue" if not en
                                         else "Companies House — iXBRL accounts received but no value recognised")}
    rev = latest_by_metric(facts).get("REVENUE")
    return {"ok": True, "message": (f"Companies House — {len(facts)} faits lus (comptes déposés le {doc.get('date', '')})"
                                    + (f" ; chiffre d'affaires {rev['period']} : {_fmt_value50(rev)}" if rev else "")
                                    if not en else f"Companies House — {len(facts)} facts read (accounts filed {doc.get('date', '')})"
                                    + (f"; revenue {rev['period']}: {_fmt_value50(rev)}" if rev else ""))}
