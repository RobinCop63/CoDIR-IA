"""Sécurité factuelle des sorties Finance.

Correctifs terrain dossier de conseil :
- un président de SASU est assimilé salarié, jamais TNS ;
- un revenu personnel, l'IR/TMI ou les cotisations du dirigeant ne sont pas
  calculables depuis le chiffre d'affaires de la société ;
- une réserve de trésorerie ou un seuil de viabilité chiffré ne peut pas être
  présenté comme propre à l'entreprise sans données primaires structurées.

Le module neutralise les chaînes invalides, conserve les scénarios de chiffre
d'affaires brut (TJM × jours) comme illustrations explicites et s'appuie sur
la couche de faits structurée — jamais sur l'aveu textuel de l'agent.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Tuple

_TAG_FR = "[SCÉNARIO ILLUSTRATIF — NON PERSONNALISÉ] "
_TAG_EN = "[ILLUSTRATIVE SCENARIO — NOT PERSONALIZED] "

# Statuts et métriques qui constituent une donnée financière d'entreprise
# vérifiée. Les faits d'identité ou d'effectif ne suffisent pas.
_FACT_STATUSES = {"FAIT", "FACT", "CONFIRMED", "VERIFIED"}
_FIN_METRICS = {
    "REVENUE", "TURNOVER", "NET_INCOME", "NET_LOSS", "EBITDA", "EBIT",
    "OPERATING_PROFIT", "GROSS_MARGIN", "CASH", "CASH_EQUIVALENTS",
    "GROSS_DEBT", "NET_DEBT", "FINANCIAL_DEBT", "EQUITY", "FREE_CASH_FLOW",
    "WORKING_CAPITAL", "BFR", "CAPEX", "OPEX", "OPERATING_CASH_FLOW",
}
_FIN_LABEL_RX = re.compile(
    r"chiffre\s+d['’]affaires|revenu(?:e)?|turnover|ebitda|ebit|r[ée]sultat\s+net|"
    r"net\s+(?:income|loss)|tr[ée]sorerie|cash|dette|debt|capitaux\s+propres|equity|"
    r"free\s+cash|marge|margin|bfr|working\s+capital|capex|opex",
    re.IGNORECASE,
)
_UNRELIABLE_SOURCE_RX = re.compile(
    r"\bbrief\b|narratif|narrative|hypoth[èe]se|assumption|benchmark|market|march[ée]|"
    r"signal\s+financier|multi[- ]format|fragments?\s+[àa]\s+consonance",
    re.IGNORECASE,
)
_TRUSTED_PRIMARY_SOURCE_RX = re.compile(
    r"attachment|pi[èe]ce|document|annual|report|filing|liasse|registre|registry|"
    r"pappers|companies[_ ]house|excel|financial[_ ]statement|comptes?",
    re.IGNORECASE,
)

_TNS_SASU_RX = re.compile(
    r"(?=.*\bTNS\b)(?=.*\bSASU\b).*", re.IGNORECASE
)
_PERSONAL_RX = re.compile(
    r"\bTMI\b|\bIR\b\s*(?:\(|:|=|estim|\d)|imp[oô]t\s+sur\s+le\s+revenu|"
    r"revenu\s+(?:net|disponible|personnel)|r[ée]mun[ée]ration\s+(?:nette?|disponible)|"
    r"net\s+(?:income|available\s+income)|\d[\d\s.,]*\s*€\s+net\b|"
    r"net\s+pour\s+[A-ZÀ-Ý]|apr[èe]s\s+IR|after\s+(?:personal\s+)?income\s+tax|"
    r"cotisations?\s+(?:du\s+dirigeant|personnelles?)|"
    r"charges?\s+sociales?\s+(?:TNS|[^\n]{0,45}%\s*(?:du\s+)?CA)|"
    r"social\s+contributions?\s+[^\n]{0,45}%\s*(?:of\s+)?(?:revenue|turnover)|"
    r"\d[\d\s.,]*\s*€\s*/\s*mois|\d[\d\s.,]*\s*€\s+par\s+mois|"
    r"€\s*(?:/|par)\s*month",
    re.IGNORECASE,
)
_SEUIL_PERSONNEL_RX = re.compile(
    r"seuil\s+de\s+(?:viabilit[ée]|rentabilit[ée]).{0,100}(?:revenu\s+net|€\s*/\s*mois)|"
    r"viability\s+threshold.{0,100}(?:net\s+income|per\s+month)",
    re.IGNORECASE,
)
_UNSUPPORTED_COMPANY_RX = re.compile(
    r"charges?\s+fixes?.{0,70}\d|fixed\s+costs?.{0,70}\d|"
    r"r[ée]serve\s+(?:de\s+)?tr[ée]sorerie.{0,90}\d|cash\s+reserve.{0,90}\d|"
    r"besoin\s+(?:de\s+)?tr[ée]sorerie.{0,90}\d|cash\s+buffer.{0,90}\d|"
    r"seuil\s+de\s+(?:viabilit[ée]|rentabilit[ée]).{0,90}\d|"
    r"break[- ]?even.{0,90}\d",
    re.IGNORECASE,
)
_REVENUE_SCENARIO_RX = re.compile(
    r"(?:CA|chiffre\s+d['’]affaires|revenue|turnover).{0,100}(?:jours?|days?|TJM|daily\s+rate|[×x*])|"
    r"(?:jours?|days?).{0,100}(?:TJM|daily\s+rate).{0,100}(?:CA|revenue|turnover)|"
    r"\d+\s*(?:j|jours?|days?)\s*[×x*]\s*[\d\s.,]+\s*€",
    re.IGNORECASE,
)
_CHAIN_ITEM_RX = re.compile(
    r"^\s*(?:[-•*✓]|\d+[.)])?\s*(?:≥|>|<|ou\b|or\b|soit\b|either\b)?.*"
    r"(?:jours?|days?|TJM|daily\s+rate|revenu\s+net|net\s+income|€\s*/\s*mois)",
    re.IGNORECASE,
)
_CHAIN_END_RX = re.compile(
    r"^\s*(?:#{1,6}\s+|---+\s*$|parade|recommandation|risque\s+\d|"
    r"mitigation|recommendation|risk\s+\d)", re.IGNORECASE,
)


def _iter_fact_rows(table: Any) -> Iterable[Mapping[str, Any]]:
    if table is None:
        return []
    if isinstance(table, Mapping):
        rows = table.get("facts") or []
    elif isinstance(table, (list, tuple)):
        # v62.3 — une liste nue de lignes de faits est une forme légitime.
        # L'ignorer empêcherait le déblocage même sur des faits FAIT sourcés.
        rows = table
    else:
        rows = getattr(table, "facts", []) or []
    out = []
    for row in rows:
        if isinstance(row, Mapping):
            out.append(row)
        elif hasattr(row, "to_row_dict"):
            try:
                out.append(row.to_row_dict())
            except Exception:
                pass
        elif hasattr(row, "__dict__"):
            out.append(vars(row))
    return out


def has_primary_financial_evidence(financial_facts_table: Any = None,
                                   facts_table_status: str | None = None) -> bool:
    """True uniquement si la couche structurée contient un fait financier vérifié.

    Une simple phrase de l'agent, un fait de marché, l'effectif, un numéro de
    société ou une estimation ne débloquent jamais les calculs.
    """
    try:
        # v62.13.9.4.40 — « aucune donnée » ≠ « données présentes mais non qualifiées ». Dossier
        # réel du 21/09/2026 : des faits en table, tous écartés pour un périmètre mal inféré, et le
        # chapitre finance affirmait qu'aucune donnée n'était disponible.
        try:
            _PRESENT_UNQUALIFIED40["flag"] = any(True for _ in _iter_fact_rows(financial_facts_table))
        except Exception:
            _PRESENT_UNQUALIFIED40["flag"] = False
        if str(facts_table_status or "").lower() in {"failed", "error"}:
            return False
        for row in _iter_fact_rows(financial_facts_table):
            status = str(row.get("status") or "").strip().upper()
            if status not in _FACT_STATUSES:
                continue
            if str(row.get("perimeter_match") or "").upper() == "MISMATCH":
                continue
            # Un fait diagnostics-only/quarantiné ne débloque jamais Finance.
            if row.get("visible_fact") is False:
                continue
            metric = str(row.get("metric_canonical_id") or "").strip().upper()
            label = str(row.get("label") or row.get("metric") or "")
            source_type = str(row.get("source_type") or "")
            source = str(row.get("source_doc") or row.get("source") or "")
            if _UNRELIABLE_SOURCE_RX.search(source_type) or _UNRELIABLE_SOURCE_RX.search(source):
                continue
            # v62.8 — le canonical ID est l'autorité. Le fallback label est
            # conservé uniquement pour les anciennes rows, avec une source
            # primaire identifiable. Un simple signal de pièces/100 montants
            # n'est pas un fait financier primaire.
            if metric:
                if metric not in _FIN_METRICS:
                    continue
            else:
                if not _FIN_LABEL_RX.search(label):
                    continue
                if not _TRUSTED_PRIMARY_SOURCE_RX.search(f"{source_type} {source}"):
                    continue
            value = row.get("value")
            if value not in (None, "", "—", "-"):
                return True
        return False
    except Exception:
        return False


def _messages(lang: str) -> dict:
    en = str(lang or "fr").lower().startswith("en")
    if en:
        return {
            "tag": _TAG_EN,
            "title": "⚠ FACTUAL CORRECTION — CALCULATIONS REMOVED",
            "tns": ("- Social regime: a French SASU president is treated as an employee; "
                    "a TNS rate applied to company revenue is inapplicable."),
            "personal": ("- Personal income, social contributions and income tax cannot be "
                         "calculated without documented remuneration, dividends and tax status."),
            "company": ("- Cash reserve and break-even amounts must be sized from verified "
                        "accounts, fixed costs, payment terms and actual cash."),
        }
    return {
        "tag": _TAG_FR,
        "title": "⚠ CORRECTION FACTUELLE — CALCULS ÉCARTÉS",
        "tns": ("- Régime social : le président de SASU est assimilé salarié ; "
                "un taux TNS appliqué au chiffre d'affaires est inapplicable."),
        "personal": ("- Revenu personnel, cotisations et IR : non calculables sans "
                     "rémunération, dividendes et situation fiscale documentés."),
        "company": ("- Réserve de trésorerie et seuil de rentabilité : à dimensionner "
                    "depuis les comptes, charges fixes, délais de paiement et cash réels."),
    }


def _is_sasu(entity_form: str | None) -> bool:
    return bool(re.search(r"\bSASU\b|soci[ée]t[ée]\s+par\s+actions\s+simplifi[ée]e\s+unipersonnelle",
                          str(entity_form or ""), re.I))


_HARD_UNSUPPORTED_LINE_RX = re.compile(
    r"\b(?:EBE\s+estim|r[ée]sultat\s+net\s+(?:estim|disponible)|apr[èe]s\s+IS|"
    r"net\s+apr[èe]s\s+IS|charges?\s+sociales?\s+dirigeant|statut\s+TNS|"
    r"TNS\s+ou\s+assimil[ée]\s+salari[ée]|capital\s+social\s+probablement|"
    r"augmentation\s+(?:du\s+)?capital|flat\s+tax|option\s+fiscale|"
    r"zone\s+rouge|non\s+viable|probabilit[ée]\s+d['’]occurrence|"
    r"marge\s+brute\s+SASU|r[ée]mun[ée]ration\s+dirigeant\s*\+\s*IS|"
    r"assurance\s+(?:pr[ée]voyance|perte\s+d['’]exploitation).{0,50}\d)",
    re.I,
)
_CASH_TARGET_RX = re.compile(
    r"(?:constituer|maintenir|viser|recommand\w*|cible|objectif|seuil|matelas|r[ée]serve)"
    r".{0,80}tr[ée]sorerie.{0,60}\b\d[\d\s.,]*\s*k?€|"
    r"tr[ée]sorerie.{0,60}(?:>|≥|au\s+moins)\s*\d[\d\s.,]*\s*k?€",
    re.I,
)
_DAYS_TARGET_RX = re.compile(
    r"(?:objectif|cible|seuil|plancher|minimum|imp[ée]ratif|priorit[ée]\s+absolue|fixer|viser|garantir)"
    r".{0,80}\b\d{2,3}\s+jours?\s+factur", re.I)
_PIPELINE_TARGET_RX = re.compile(
    r"pipeline.{0,90}(?:95\s*k€|\d[\d\s.,]*\s*k€|2\s*[x×]\s*CA|2\s*[x×]\s*chiffre)", re.I)
_TJM_TARGET_RX = re.compile(
    r"(?:TJM\s+(?:plancher|minimum|d[ée]fensif)|fixer\s+(?:un\s+)?TJM|"
    r"ne\s+pas\s+descendre\s+(?:en\s+dessous|sous)).{0,80}\d[\d\s.,]*\s*€",
    re.I,
)
_CORPORATE_ESTIMATE_RX = re.compile(
    r"(?:CA|chiffre\s+d['’]affaires|EBITDA|EBIT|r[ée]sultat\s+net|dette|"
    r"tr[ée]sorerie|cash[- ]?flow|CAPEX|OPEX|rentabilit[ée]|marge|synergies?)"
    r".{0,90}(?:estim[ée]e?|hypoth[èe]se|projection|sc[ée]nario|ordre\s+de\s+grandeur)"
    r".{0,90}(?:\d[\d\s.,]*\s*(?:M€|k€|€|%))|"
    r"(?:\d[\d\s.,]*\s*(?:M€|k€|€|%)).{0,90}"
    r"(?:CA|EBITDA|EBIT|r[ée]sultat\s+net|CAPEX|OPEX|synergies?)",
    re.I,
)
_SYNERGY_RATE_RX = re.compile(
    r"synergies?.{0,100}\b\d+(?:[.,]\d+)?\s*(?:[-–]\s*\d+(?:[.,]\d+)?)?\s*%"
    r"(?:.{0,40}CA)?", re.I)
_MICRO_CORPORATE_BUDGET_RX = re.compile(
    r"budget\s+(?:marketing|commercial).{0,80}(?:<|inf[ée]rieur\s+[àa]|moins\s+de)\s*"
    r"(?:2\s*000|2000)\s*€(?:\s*/\s*an)?", re.I)


_DAYS_RATE_PATTERNS = (
    re.compile(r"(?P<days>\d{1,3})\s*(?:j|jours?|days?)\s*[×x*]\s*(?P<rate>\d[\d\s.,]*)\s*€", re.I),
    re.compile(r"(?P<rate>\d[\d\s.,]*)\s*€(?:\s*(?:HT)?\s*/?\s*(?:jour|day))?\s*[×x*]\s*(?P<days>\d{1,3})\s*(?:j|jours?|days?)", re.I),
    re.compile(r"(?P<days>\d{1,3})\s*(?:j|jours?|days?)\s+(?:à|at)\s+(?P<rate>\d[\d\s.,]*)\s*€", re.I),
)
_FORBIDDEN_SCENARIO_KIND_RX = re.compile(
    r"seuil\s+de\s+rentabilit[ée]|seuil\s+de\s+viabilit[ée]|break[- ]?even|"
    r"capital\s+cible|r[ée]serve\s+de\s+tr[ée]sorerie|cash\s+buffer", re.I)
_ILLUSTRATIVE_TAG_RX = re.compile(
    r"\[(?:SC[ÉE]NARIO\s+ILLUSTRATIF|ILLUSTRATIVE\s+SCENARIO)[^\]]*\]", re.I)


def _parse_number_token(token: str) -> float | None:
    raw = str(token or "").replace("\u202f", " ").replace("\xa0", " ").strip()
    raw = re.sub(r"\s+", "", raw).replace(",", ".")
    try:
        return float(raw)
    except Exception:
        return None


def _format_eur(value: float, lang: str) -> str:
    rounded = int(round(value))
    grouped = f"{rounded:,}".replace(",", " ")
    return f"€{grouped}" if str(lang or "fr").lower().startswith("en") else f"{grouped} €"


def _extract_gross_revenue_scenarios(text: str, lang: str, limit: int = 3) -> list[str]:
    """Reconstruct only gross revenue from a documented days × rate formula.

    The source line is *never* copied.  This is the critical v62.6 property:
    a line that also contains personal net income may provide the two neutral
    operands, but its tax/social tail is discarded. Break-even/cash/capital
    scenarios are rejected entirely.
    """
    en = str(lang or "fr").lower().startswith("en")
    tag = _TAG_EN if en else _TAG_FR
    out: list[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or _FORBIDDEN_SCENARIO_KIND_RX.search(line):
            continue
        match = next((rx.search(line) for rx in _DAYS_RATE_PATTERNS if rx.search(line)), None)
        if match is None:
            continue
        days_v = _parse_number_token(match.group("days"))
        rate_v = _parse_number_token(match.group("rate"))
        if days_v is None or rate_v is None or days_v <= 0 or rate_v <= 0:
            continue
        # Guard against accidentally selecting annual revenue as the daily rate.
        if days_v > 366 or rate_v > 10000:
            continue
        gross = days_v * rate_v
        days = int(round(days_v))
        rate = _format_eur(rate_v, lang)
        gross_txt = _format_eur(gross, lang)
        if en:
            clean = (f"{tag}{days} days × {rate}/day = {gross_txt} illustrative gross revenue")
        else:
            clean = (f"{tag}{days} jours × {rate}/jour = {gross_txt} CA annuel brut illustratif")
        if clean not in out:
            out.append(clean)
        if len(out) >= limit:
            break
    return out


_ACTIVITY_PATTERNS34 = (
    ("industrie", r"(?i)\b(?:industri|manufactur|usine|production|fabricat|m[ée]canique|hydraulique|[ée]quipementier|"
                  r"agroaliment|biscuiter|chimie|plasturgie|m[ée]tallurgie|automobile|a[ée]ronautique)"),
    ("reseau",    r"(?i)\b(?:r[ée]seau|franchis|succursal|magasin|boutique|point de vente|centre[s]? d[ée]|"
                  r"audioproth|optique|pharmaci|clinique|distribution de d[ée]tail|retail)"),
    ("conseil",   r"(?i)\b(?:conseil|consulting|cabinet|freelance|prestation intellectuelle|ing[ée]nierie de gestion|"
                  r"transition manag|SASU\b|micro[- ]entreprise)"),
)


def detect_activity_nature(entity_form: str | None = None, company_profile=None, hints: str = "") -> str:
    """v62.13.9.4.34 (lot 2) — nature d'activité pour le repli Finance : « industrie »,
    « reseau », « conseil » ou « generique ».

    Contre-audit de publication du 14/09/2026 : le gabarit de repli, écrit pour un
    cabinet de conseil (TJM × jours facturés, taux d'occupation), s'appliquait tel
    quel à un fabricant de composants hydrauliques, à une biscuiterie et à un réseau
    de centres auditifs — un gabarit de conseil sur un dossier industriel n'est pas
    une donnée fausse, c'est une question hors sujet. Le libellé, le secteur, le code
    d'activité et la forme juridique sont lus ensemble ; à défaut, cadre générique.
    """
    blob = " ".join(str(x or "") for x in (
        entity_form, hints,
        getattr(company_profile, "sector", "") if company_profile is not None else "",
        getattr(company_profile, "activity", "") if company_profile is not None else "",
        getattr(company_profile, "naf_label", "") if company_profile is not None else "",
        getattr(company_profile, "name", "") if company_profile is not None else "",
        (company_profile or {}).get("sector", "") if isinstance(company_profile, dict) else "",
        (company_profile or {}).get("activity", "") if isinstance(company_profile, dict) else "",
        (company_profile or {}).get("naf_label", "") if isinstance(company_profile, dict) else "",
    ))
    for kind, pat in _ACTIVITY_PATTERNS34:
        if re.search(pat, blob):
            return kind
    return "generique"


_REQUIRED_DATA34 = {
    "industrie": (["- Chiffre d'affaires et marge par ligne de produits ; volumes, prix moyen et mix.",
                   "- Coût de revient industriel : matières, main-d'œuvre directe, charges d'atelier, taux de rebut.",
                   "- Capacité et taux d'utilisation des lignes ; carnet de commandes et délai de livraison.",
                   "- Stocks (matières, en-cours, produits finis), besoin en fonds de roulement et investissements engagés."],
                  ["- Revenue and margin by product line; volumes, average price and mix.",
                   "- Industrial cost of goods: materials, direct labour, plant overheads, scrap rate.",
                   "- Line capacity and utilisation; order book and lead times.",
                   "- Inventories (raw, WIP, finished), working capital and committed capital expenditure."]),
    "reseau":    (["- Chiffre d'affaires et marge par point de vente ; nombre de points, ouvertures et fermetures.",
                   "- Panier moyen, fréquentation, taux de transformation et part des ventes récurrentes.",
                   "- Coûts par point : loyers, masse salariale, charges d'exploitation ; seuil de rentabilité unitaire.",
                   "- Stocks par point, délais fournisseurs et besoin en fonds de roulement du réseau."],
                  ["- Revenue and margin per outlet; number of outlets, openings and closures.",
                   "- Average basket, footfall, conversion rate and share of recurring sales.",
                   "- Cost per outlet: rent, payroll, operating charges; unit break-even point.",
                   "- Inventory per outlet, supplier terms and network working capital."]),
    "conseil":   (["- CA facturé et encaissé par mois ; jours facturés et TJM réels par mission.",
                   "- Charges fixes et variables ; politique de rémunération/dividendes ; situation fiscale.",
                   "- Trésorerie, créances, délais de paiement, impayés et pipeline en cours.",
                   "- Concentration clients et mix missions directes/intermédiées."],
                  ["- Revenue billed and collected by month; billed days and actual daily rates by mission.",
                   "- Fixed and variable costs; remuneration/dividend policy; tax position.",
                   "- Cash, receivables, payment terms, overdue invoices and current pipeline.",
                   "- Client concentration and direct/intermediated mission mix."]),
    "generique": (["- Chiffre d'affaires et marge par activité ou par segment, sur les trois derniers exercices.",
                   "- Structure de coûts fixes et variables ; principaux postes de charges.",
                   "- Trésorerie, créances, dettes, délais de paiement et engagements hors bilan.",
                   "- Concentration clients ou fournisseurs et saisonnalité de l'activité."],
                  ["- Revenue and margin by activity or segment, over the last three financial years.",
                   "- Fixed and variable cost structure; main expense lines.",
                   "- Cash, receivables, payables, payment terms and off-balance-sheet commitments.",
                   "- Client or supplier concentration and seasonality."]),
}
_SAFE_ORIENTATIONS34 = {
    "industrie": (["- Établir le coût de revient réel par ligne avant toute cible de marge.",
                   "- Rapprocher capacité installée et carnet de commandes avant tout plan d'investissement.",
                   "- Utiliser les comparables sectoriels comme ordres de grandeur, jamais comme comptes de l'entreprise."],
                  ["- Establish the actual cost of goods by line before setting any margin target.",
                   "- Reconcile installed capacity with the order book before any investment plan.",
                   "- Treat sector benchmarks as orders of magnitude, never as company accounts."]),
    "reseau":    (["- Mesurer la rentabilité par point de vente avant toute décision d'ouverture ou de fermeture.",
                   "- Distinguer croissance à périmètre constant et croissance par ouvertures.",
                   "- Utiliser les comparables sectoriels comme ordres de grandeur, jamais comme comptes de l'entreprise."],
                  ["- Measure profitability per outlet before any opening or closing decision.",
                   "- Separate like-for-like growth from growth through openings.",
                   "- Treat sector benchmarks as orders of magnitude, never as company accounts."]),
    "conseil":   (["- Mesurer le taux d'occupation réel et la distribution des TJM avant de fixer des objectifs.",
                   "- Dimensionner toute réserve de trésorerie depuis les charges, délais de paiement et flux réels.",
                   "- Utiliser les benchmarks marché comme comparables, jamais comme comptes de l'entreprise."],
                  ["- Measure the actual utilization rate and daily-rate distribution before setting targets.",
                   "- Size any cash buffer from verified costs, payment terms and actual cash-flow volatility.",
                   "- Treat market benchmarks as comparables, never as company accounts."]),
    "generique": (["- Établir la base de comparaison (périmètre, période, unité) avant toute cible chiffrée.",
                   "- Dimensionner toute réserve de trésorerie depuis les charges et les délais de paiement réels.",
                   "- Utiliser les comparables sectoriels comme ordres de grandeur, jamais comme comptes de l'entreprise."],
                  ["- Establish the comparison base (perimeter, period, unit) before any quantified target.",
                   "- Size any cash buffer from actual costs and payment terms.",
                   "- Treat sector benchmarks as orders of magnitude, never as company accounts."]),
}


_PRESENT_UNQUALIFIED40 = {'flag': False}


def _safe_finance_template(lang: str, entity_form: str | None,
                           revenue_scenarios: list[str], company_profile=None) -> str:
    _present_unqualified40 = bool(_PRESENT_UNQUALIFIED40.get('flag'))   # v62.13.9.4.40
    en = str(lang or "fr").lower().startswith("en")
    sasu = _is_sasu(entity_form)
    _nature34 = detect_activity_nature(entity_form, company_profile)
    _req34 = _REQUIRED_DATA34[_nature34][1 if en else 0]
    _ori34 = _SAFE_ORIENTATIONS34[_nature34][1 if en else 0]
    if en:
        lines = [
            "## FINANCE — PRUDENT INTERNAL FRAME",
            ("Company financial data was provided but could not be qualified for the requested perimeter "
             "(period, entity or scope not reconciled); it is not used for calculations below."
             if _present_unqualified40 else
             "No verified primary company financial data is available in this run."),
            "The Finance role may structure the questions, but may not calculate a company-specific net result, tax, social contributions, remuneration, break-even, cash reserve or capital target.",
            "- Net-result impact: undetermined at this stage (primary data unavailable).",
        ]
        if sasu:
            lines.append("- Legal/social regime: a remunerated French SASU president is treated as an employee, not TNS.")
        if revenue_scenarios:
            lines.extend(["", "### Illustrative gross-revenue scenarios", *[f"- {x}" for x in revenue_scenarios]])
        lines.extend([
            "", "### Data required before a personalized financial recommendation",
            *_req34,
            "", "### Safe working orientations",
            *_ori34,
        ])
        return "\n".join(lines)
    lines = [
        "## FINANCE — CADRE INTERNE PRUDENT",
        "⚠ CORRECTION FACTUELLE — CALCULS ÉCARTÉS",
        ("Des données financières de l’entreprise ont été fournies mais n’ont pas pu être qualifiées "
         "pour le périmètre demandé (période, entité ou périmètre non rapprochés) ; elles ne servent pas "
         "aux calculs ci-dessous." if _present_unqualified40 else
         "Aucune donnée financière primaire vérifiée de l’entreprise n’est disponible dans ce run."),
        "Le rôle Finance peut structurer les questions, mais ne doit pas calculer de résultat net, IS, charges sociales, rémunération, seuil de rentabilité, réserve de trésorerie ou capital cible propres à l’entreprise.",
        "- Impact résultat net : indéterminé à ce stade (données primaires absentes).",
    ]
    if sasu:
        lines.append("- Régime social : un président de SASU rémunéré est assimilé salarié, et non TNS.")
    if revenue_scenarios:
        lines.extend(["", "### Scénarios illustratifs de chiffre d’affaires brut",
                      *[f"- {x}" for x in revenue_scenarios]])
    lines.extend([
        "", "### Données requises avant toute recommandation financière personnalisée",
        *_req34,
        "", "### Orientations de travail sûres",
        *_ori34,
    ])
    return "\n".join(lines)


def sanitize_finance_output(text: str, has_primary_financials: bool | None = None,
                            lang: str = "fr",
                            allow_personalized_simulations: bool = False,
                            entity_form: str | None = None,
                            company_profile=None) -> Tuple[str, dict]:
    """Neutralise les calculs non défendables et retourne ``(texte, rapport)``.

    Sans preuve financière primaire structurée, la sortie Finance est remplacée
    par un cadre déterministe prudent. C'est volontairement fail-closed : les
    balises « scénario illustratif » ne suffisent plus à autoriser un résultat
    net, un IS, des charges sociales ou un besoin de cash propres à l'entreprise.
    """
    rep = {
        "tns_sasu_flagged": 0,
        "personalized_sim_tagged": 0,
        "notice_added": False,
        "tns_sasu_removed": 0,
        "personalized_lines_removed": 0,
        "unsupported_company_lines_removed": 0,
        "illustrative_revenue_tagged": 0,
        "finance_output_replaced": False,
        "has_primary_financials": bool(has_primary_financials),
    }
    try:
        if not text:
            return text, rep
        has_primary = bool(has_primary_financials) if has_primary_financials is not None else False
        if not has_primary:
            if not entity_form and re.search(r"\bSASU\b", str(text), re.I):
                entity_form = "SASU"
            raw_lines = str(text).splitlines()
            rep["tns_sasu_removed"] = sum(1 for x in raw_lines if re.search(r"\bTNS\b", x, re.I))
            rep["tns_sasu_flagged"] = rep["tns_sasu_removed"]
            rep["personalized_lines_removed"] = sum(
                1 for x in raw_lines if _PERSONAL_RX.search(x) or _HARD_UNSUPPORTED_LINE_RX.search(x))
            rep["unsupported_company_lines_removed"] = sum(
                1 for x in raw_lines if _UNSUPPORTED_COMPANY_RX.search(x)
                or _CASH_TARGET_RX.search(x) or _DAYS_TARGET_RX.search(x)
                or _PIPELINE_TARGET_RX.search(x) or _TJM_TARGET_RX.search(x))
            scenarios = _extract_gross_revenue_scenarios(text, lang)
            rep["illustrative_revenue_tagged"] = len(scenarios)
            rep["personalized_sim_tagged"] = rep["personalized_lines_removed"]
            rep["notice_added"] = True
            # 9.4.65 — contre-recette du 17/10/2026 (LM02) : la note Finance complète (réponse terminée) était
            # REMPLACÉE par le cadre prudent ; ses analyses bornées et utiles disparaissaient des deux Word. Doctrine du
            # 28/09 : tout livrer, points douteux signalés. Le cadre prudent est conservé EN TÊTE ; la note suit, sans les
            # calculs personnels (TNS, rémunération, dividendes : toujours écartés) et avec une réserve locale sur chaque ligne
            # chiffrée propre à l'entreprise non étayée par des états primaires. Une réponse vide ou très courte garde le cadre seul.
            _frame65 = _safe_finance_template(lang, entity_form, scenarios, company_profile)
            _en65 = str(lang or "fr").lower().startswith("en")
            # idempotence (contre-recette du 17/10, F01 résiduel) : une note déjà conservée n'est pas recadrée une seconde fois
            if ("Finance note kept under reservation" in str(text)) or ("NOTE CONSERVÉE SOUS RÉSERVE" in str(text)):
                rep["finance_output_replaced"] = False
                rep["finance_output_preserved65"] = True
                return str(text), rep
            # Barrière v62.6 maintenue : dossier d'une personne (SASU, EURL, EI, micro, TNS), la note mêle souvent des chaînes
            # de revenu personnel (net, charges sociales, IS) sans donnée : le cadre prudent REMPLACE toujours la note.
            # La conservation (LM02) vaut pour les sociétés et les groupes.
            if (str(entity_form or "").upper() in {"SASU", "EURL", "EI", "EIRL", "MICRO", "AUTO-ENTREPRENEUR", "AUTOENTREPRENEUR"}
                    or re.search(r"\b(?:SASU|EURL|TNS|micro-?entrepreneur|auto-?entrepreneur)\b", str(text), re.I)):
                rep["finance_output_replaced"] = True
                return _frame65, rep
            _body65 = []
            _tag65 = (" [TO VERIFY — no primary financial statements]" if str(lang or "fr").lower().startswith("en")
                      else " [À VÉRIFIER — sans états financiers primaires]")
            for _l65 in raw_lines:
                if re.search(r"\bTNS\b", _l65, re.I) or _PERSONAL_RX.search(_l65) or _HARD_UNSUPPORTED_LINE_RX.search(_l65):
                    continue                                   # calcul personnel : écarté, comme avec des faits primaires
                if (_UNSUPPORTED_COMPANY_RX.search(_l65) or _CASH_TARGET_RX.search(_l65) or _DAYS_TARGET_RX.search(_l65)
                        or _PIPELINE_TARGET_RX.search(_l65) or _TJM_TARGET_RX.search(_l65)) and _tag65.strip() not in _l65:
                    _l65 = _l65.rstrip() + _tag65
                _body65.append(_l65)
            _kept65 = "\n".join(_body65).strip()
            if len(re.sub(r"\s+", "", _kept65)) < 400:
                rep["finance_output_replaced"] = True
                return _frame65, rep
            rep["finance_output_replaced"] = False
            rep["finance_output_preserved65"] = True
            # une SEULE notice, cohérente avec la note conservée (le cadre « calculs écartés » la contredisait)
            _unq65 = bool(company_profile and getattr(company_profile, "present_unqualified", False))
            _notice65 = ("## FINANCE — Finance note kept under reservation\n"
                         "⚠ No verified primary financial statement of the requested perimeter is available in this run. The figures "
                         "below are standalone facts, assumptions or estimates from the analysis: check them against the documents "
                         "before any use. Personal calculations (remuneration, dividends, self-employed status) were removed."
                         if _en65 else
                         "## FINANCE — NOTE CONSERVÉE SOUS RÉSERVE\n"
                         "⚠ Aucun état financier primaire vérifié du périmètre demandé n'est disponible dans ce run. Les chiffres "
                         "ci-dessous sont des faits sociaux, des hypothèses ou des estimations de l'analyse : à vérifier sur pièce "
                         "avant tout usage. Les calculs personnels (rémunération, dividendes, travailleur non salarié) ont été écartés.")
            # les scénarios de chiffre d'affaires brut restent explicitement ILLUSTRATIFS (cas solo, TJM × jours)
            _scen65 = ""
            if scenarios:
                _blk65 = re.search(r"(?ms)^###\s+(?:Illustrative gross-revenue scenarios|Sc[ée]narios illustratifs[^\n]*)\n(?:(?!^###).*\n?)*",
                                   _frame65)
                if _blk65:
                    _scen65 = "\n\n" + _blk65.group(0).strip()
            return _notice65 + _scen65 + "\n\n" + _kept65, rep

        # Avec faits primaires, conserver la sortie mais retirer les calculs
        # personnels, qui exigent toujours rémunération/dividendes/fiscalité.
        msg = _messages(lang)
        out: list[str] = []
        for raw in str(text).splitlines():
            line = raw
            if _TNS_SASU_RX.search(line) or (_is_sasu(entity_form) and re.search(r"\bTNS\b", line, re.I)):
                rep["tns_sasu_flagged"] += 1
                rep["tns_sasu_removed"] += 1
                continue
            if not allow_personalized_simulations and (
                    _PERSONAL_RX.search(line) or _SEUIL_PERSONNEL_RX.search(line)):
                rep["personalized_lines_removed"] += 1
                rep["personalized_sim_tagged"] += 1
                continue
            out.append(line)
        corrections = []
        if rep["tns_sasu_removed"]:
            corrections.append(msg["tns"])
        if rep["personalized_lines_removed"]:
            corrections.append(msg["personal"])
        if corrections:
            out.extend(["", msg["title"], *corrections])
            rep["notice_added"] = True
        return "\n".join(out), rep
    except Exception:
        return text, rep


def sanitize_cross_output_financial_claims(outputs: Mapping[str, Any] | None,
                                            has_primary_financials: bool,
                                            lang: str = "fr",
                                            entity_form: str | None = None,
                                            company_profile: Any = None) -> tuple[dict[str, Any], dict]:
    """Assainit les répétitions financières injectées dans DG/Commercial/Stratégie.

    Le rôle Finance est déjà remplacé par le cadre prudent. Cette défense en
    profondeur empêche ses anciens seuils de survivre dans les synthèses et le
    registre. Les benchmarks marché restent autorisés ; seuls les objectifs
    personnalisés non prouvés sont neutralisés.
    """
    src = dict(outputs or {})
    rep = {"fields_touched": 0, "lines_removed": 0, "lines_replaced": 0}
    if has_primary_financials:
        return src, rep
    en = str(lang or "fr").lower().startswith("en")
    _is_solo_profile = bool(getattr(company_profile, "is_solo", False))
    _profile_size = str(getattr(company_profile, "size", "") or "").lower()
    _profile_nature = str(getattr(company_profile, "nature", "") or "").lower()
    _is_corporate_profile = bool(
        company_profile is not None and not _is_solo_profile and
        (_profile_size in {"pme", "eti_plus"} or _profile_nature == "product")
    )
    replacements = {
        "cash": ("- Cash buffer: size from verified costs, payment terms and actual cash-flow variability."
                 if en else "- Réserve de trésorerie : à dimensionner depuis les charges, délais de paiement et flux réels."),
        "days": ("- Billed-days target: calibrate from the actual mission history and remuneration objectives."
                 if en else "- Objectif de jours facturés : à calibrer depuis l’historique réel des missions et les objectifs de rémunération."),
        "pipeline": ("- Pipeline threshold: calibrate from actual sales-cycle and conversion data."
                     if en else "- Seuil de pipeline : à calibrer depuis le cycle de vente et les taux de conversion réels."),
        "tjm": ("- Daily-rate target: validate from actual rates, positioning and intermediation terms."
                if en else "- TJM cible : à valider depuis les TJM réels, le positionnement et les conditions d’intermédiation."),
        "sasu": ("- A remunerated French SASU president is treated as an employee, not TNS."
                 if en else "- Un président de SASU rémunéré est assimilé salarié, et non TNS."),
        "corporate": ("- Company financial ranges and synergies: establish them from the consolidated reporting before use."
                      if en else "- Ordres de grandeur financiers et synergies propres à l’entreprise : à établir depuis le reporting consolidé avant usage."),
        "budget": ("- Marketing budget: size by market/channel, expected ROI and available capacity."
                   if en else "- Budget marketing : à dimensionner par marché, canal, ROI attendu et capacité d’exécution."),
    }
    for key, value in list(src.items()):
        if not isinstance(value, str) or key == "finance":
            continue
        out: list[str] = []
        emitted: set[str] = set()
        changed = False
        for raw in value.splitlines():
            line = raw
            stripped = line.strip()
            repl = None
            # Les scénarios chiffrés restent confinés au cadre Finance canonique.
            # Une synthèse/DG/Commercial ne doit jamais re-promouvoir un montant
            # illustratif en décision, objectif ou KPI d'entreprise.
            if _ILLUSTRATIVE_TAG_RX.search(line):
                rep["lines_removed"] += 1
                changed = True
                continue
            if _HARD_UNSUPPORTED_LINE_RX.search(line) or _PERSONAL_RX.search(line):
                rep["lines_removed"] += 1
                changed = True
                continue
            if _is_sasu(entity_form) and re.search(r"\bTNS\b", line, re.I):
                repl = replacements["sasu"]
            elif _CASH_TARGET_RX.search(line):
                repl = replacements["cash"]
            elif _DAYS_TARGET_RX.search(line):
                repl = replacements["days"]
            elif _PIPELINE_TARGET_RX.search(line):
                repl = replacements["pipeline"]
            elif _TJM_TARGET_RX.search(line):
                repl = replacements["tjm"]
            elif _CORPORATE_ESTIMATE_RX.search(line) or _SYNERGY_RATE_RX.search(line):
                repl = replacements["corporate"]
            elif _is_corporate_profile and _MICRO_CORPORATE_BUDGET_RX.search(line):
                repl = replacements["budget"]
            if repl is not None:
                if repl not in emitted:
                    out.append(repl)
                    emitted.add(repl)
                rep["lines_replaced"] += 1
                changed = True
                continue
            # Suppression des lignes devenues orphelines après un tableau de
            # résultats/IS supprimé : elles n'apportent aucune orientation sûre.
            if re.search(r"^\s*(?:Central|Optimiste|Critique)\s+\d", stripped, re.I):
                rep["lines_removed"] += 1
                changed = True
                continue
            out.append(line)
        if changed:
            src[key] = "\n".join(out)
            rep["fields_touched"] += 1
    return src, rep


def fail_closed_finance_outputs(outputs: Mapping[str, Any] | None,
                                lang: str = "fr",
                                entity_form: str | None = None,
                                company_profile=None) -> tuple[dict[str, Any], dict]:
    """Deterministic last-resort replacement for any Finance-gate exception."""
    src = dict(outputs or {})
    src["finance"] = _safe_finance_template(lang, entity_form, [], company_profile)
    src, cross = sanitize_cross_output_financial_claims(
        src, has_primary_financials=False, lang=lang, entity_form=entity_form)
    return src, {
        "status": "FAILED_CLOSED",
        "finance_output_replaced": True,
        "cross_output": cross,
    }


__all__ = [
    "sanitize_finance_output",
    "sanitize_cross_output_financial_claims",
    "fail_closed_finance_outputs",
    "has_primary_financial_evidence",
]
