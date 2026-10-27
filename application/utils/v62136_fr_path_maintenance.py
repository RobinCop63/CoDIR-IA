from __future__ import annotations

"""v62.13.9.4.4 — generic editorial safety: cardinal-triggered decision, exit invariant, no dossier literal.

The module builds a delivery-only view from the current run.  It never rewrites
inputs, source names, evidence ledgers, canonical claims, diagnostics or CoDIR
history.  Raw diagnostics remain audit evidence; an explicit bridge row records
the effective delivery blockers and every requalification.
"""

from copy import deepcopy
from io import BytesIO
import json
from utils import editorial_quantity as _EQ
from utils import quantity_ledger as _QL
import re
from typing import Any, Iterable, Mapping, MutableMapping


_FALSE_LEGAL_CODE = "CRITICAL_FALSE_LEGAL_ALERT"
_SCOPE_CONFLICT_CODE = "HARD_METRIC_SCOPE_CONFLICT"
_SCOPE_NOT_EVIDENCED_CODE = "GROUP_PERIMETER_NOT_EVIDENCED"
_INTERNAL_CONTRADICTION_CODE = "INTERNAL_CONTRADICTION"
_INTERNAL_CONTRADICTION_INFO_CODE = "INTERNAL_CONTRADICTION_INFO"
_MAINTENANCE_ROLE = "editorial_truth_maintenance_v62138"
_FINAL_SAFETY_ROLE = "work_product_safety_v62139"

# Only these current-run surfaces may be rewritten.  Evidence and provenance
# subtrees are intentionally absent from this list.
_EDITORIAL_TOP_LEVEL_KEYS = {
    "outputs", "finance", "strategie", "strategy", "marketing", "commercial",
    "supply_chain", "synthese", "synthesis", "synthese_decisions",
    "brief_codir", "direction_generale", "score_text", "headcount_text",
    "scope_text", "corps", "report_text", "executive_summary",
    "executive_synthesis", "decision_reconciled", "agenda_register_markdown",
    "financial_documents_status_message",
}
_IMMUTABLE_TOP_LEVEL_KEYS = {
    "inputs", "sources", "source_documents", "attachments", "attachments_meta",
    "financial_facts", "financial_facts_table", "financial_proof_layer",
    "canonical_financial_claims", "canonical_claims", "numeric_support_claims",
    "b1_proof_layer", "run_fingerprint", "diagnostics_attempts",
    "diagnostics_summary", "codir_history", "run_history", "history",
    "pappers_resolution_log", "extraction_fidelity", "web_facts_ledger",
    "scenario_appendix", "liasse_cerfa_ingestion",
}


def _legal_scrub_evidence(result: Mapping[str, Any]) -> tuple[bool, str]:
    """Require current-run mission-gate evidence; history can never authorise a scrub."""
    current_fp = _current_run_fingerprint(result)
    for idx, row in enumerate(_current_diagnostics(result)):
        if str(row.get("role") or "") != "mission_gates":
            continue
        value = 0
        try:
            value = int(float(row.get("legal_scrubs") or 0))
        except Exception:
            value = 0
        if value < 1:
            match = re.search(r"legal_scrubs\s*=\s*(\d+)", str(row.get("summary") or ""))
            value = int(match.group(1)) if match else 0
        if value >= 1:
            model = str(row.get("model") or row.get("provider") or "mission_gates")
            return True, f"diagnostics_attempts[{idx}]/{model}/run={current_fp}"
    return False, "NONE_CURRENT_RUN"


def _legal_scrub_evidenced(result: Mapping[str, Any]) -> bool:
    return _legal_scrub_evidence(result)[0]


_FALSE_LEGAL_FR = "Alerte juridique critique non étayée par les pièces"
_FALSE_LEGAL_EN = "Critical legal alert unsupported by the documents"

_AMOUNT_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[€£$]\s*)?\(?[-−–+]?\d[\d\s.,]*\)?\s*"
    r"(?:k|m|bn|md|mio|million(?:s)?|milliard(?:s)?|%|pp|x|jours?|days?|h(?:eures?)?)?\s*(?:[€£$])?",
    re.I,
)
_DATE_RE = re.compile(
    r"\b(?:20\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])|"
    r"(?:0?[1-9]|[12]\d|3[01])[-/.](?:0?[1-9]|1[0-2])[-/.]20\d{2}|"
    r"T[1-4]\s*20\d{2}|Q[1-4]\s*20\d{2}|H[12]\s*20\d{2})\b",
    re.I,
)
_YEAR_RE = re.compile(r"\b(?:FY|exercice\s+)?20\d{2}\b", re.I)

_METRIC_PATTERNS = {
    "revenue": re.compile(r"\b(?:revenue|turnover|sales|chiffre\s+d['’]affaires|\bca\b)\b", re.I),
    "inventories": re.compile(r"\b(?:inventor(?:y|ies)|stocks?|stockage)\b", re.I),
    "net_income": re.compile(r"\b(?:net\s+income|résultat\s+net|resultat\s+net)\b", re.I),
    "equity": re.compile(r"\b(?:equity|capitaux\s+propres|fonds\s+propres)\b", re.I),
    "financial_debt": re.compile(r"\b(?:financial\s+debt|dettes?\s+financières?|endettement\s+financier)\b", re.I),
    "cash": re.compile(r"\b(?:cash|trésorerie|tresorerie|liquidit(?:é|e)s?)\b", re.I),
    "ebitda": re.compile(r"\b(?:ebitda|excédent\s+brut\s+d['’]exploitation)\b", re.I),
    "operating_profit": re.compile(r"\b(?:operating\s+profit|résultat\s+d['’]exploitation|resultat\s+d['’]exploitation)\b", re.I),
    "free_cash_flow": re.compile(r"\b(?:free\s+cash\s+flow|\bfcf\b|flux\s+de\s+trésorerie\s+disponible)\b", re.I),
    "headcount": re.compile(r"\b(?:headcount|employees?|salariés?|effectif)\b", re.I),
}

_TARGET_WORDS = re.compile(
    r"\b(?:objectif|cible|target|budget|probabilit(?:é|e)|probability|base\s+case|bear|bull|severe|"
    r"scénario|scenario|forecast|projection|prévision|prevision|ambition|kpi|seuil|threshold|indicateur\s+de\s+succès|"
    r"indicateur\s+de\s+succes|potentiel\s+de\s+réduction|potentiel\s+de\s+reduction|"
    r"ligne\s+de\s+crédit|ligne\s+de\s+credit|augmentation\s+de\s+capital|renforcement\s+des\s+fonds\s+propres|"
    r"moratoire|waiver|covenant|ouvrir|ouverture|lancer|lancement|déployer|deployer|déploiement|deploiement|commercialiser|recruter|recrutement|former|formation|train|training|réduire|reduire|"
    r"gagner|atteindre|ramener|améliorer|ameliorer|porter\s+à|porter\s+a|signer|signature|partenariats?|partenaires?|distributeurs?|distributors?|d[ée]lais?|lead\s*time)\b",
    re.I,
)

_PRODUCT_ATTRIBUTE = re.compile(
    r"\b(?:électri(?:que|ques)|electri(?:c|cal)|autonomie|batterie|productivit(?:é|e)|capacité|capacite|"
    r"puissance|heures?|\bh\b|km|kwh|voltage|recharge)\b",
    re.I,
)
_PRODUCT_ATTRIBUTE_STRICT = re.compile(
    r"\b(?:électri(?:que|ques)|electri(?:c|cal)|autonomie|batterie|batter(?:y|ies)|kwh|voltage|recharge)\b", re.I)
_PRODUCT_CONTEXT = re.compile(
    r"\b(?:produits?|products?|gamme|range|équipements?|equipment|machines?|engins?|v[ée]hicules?|vehicles?|"
    r"achats?|purchase|investissement\s+mat[ée]riel|capex|lancer|lancement|launch|commercialiser|fournisseurs?|suppliers?|"
    r"vendangeuses?|tracteurs?|outils?|tools?)\b", re.I)
_EXPANSION_COUNT = re.compile(r"\b(?:filiales?|sites?|usines?|magasins?|stores?|pays|marchés?|marches?|partenariats?|partenaires?|distributeurs?|distributors?|clients?|customers?)\b", re.I)
_FIN_TARGET = re.compile(
    r"\b(?:ebitda|bfr|fonds\s+propres|trésorerie|tresorerie|dette|crédit|credit|marge|revenu|revenue|"
    r"chiffre\s+d['’]affaires|\bca\b|capex|opex|ds[o0]|cash|résultat|resultat|stocks?)\b",
    re.I,
)
_DEADLINE_PREFIX = re.compile(r"\b(?:prochaine\s+échéance|échéance|deadline|date|quand|when|jalon|milestone)\b", re.I)
_FACT_MARKER = re.compile(r"\[(?:FACT|FAIT|DERIVED FROM FACTS|DÉRIVÉ DES FAITS|CALCUL)\]", re.I)
_SOURCE_MARKER = re.compile(r"\b(?:source|p\.?\s*\d+|page\s*\d+|pappers|annual\s+report|comptes?\s+sociaux|acte|filing|d[ée]p[ôo]t\s+registre)\b", re.I)


def _norm_space(value: Any) -> str:
    # v62.13.9.4.21 — le marqueur d'outil (U+2063) est un blanc pour la maintenance
    return re.sub(r"[\s\u2063]+", " ", str(value or "")).strip()


_DECORATIVE_PREFIX_RE = re.compile(r"^\s*[▌┃│|]+\s*")
_NON_QUANTITY_CODE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"[A-Za-z]{1,6}\d+[A-Za-z]+|"       # e.g. A3B / X7A
    r"[A-Za-z]{1,4}\d+(?:\.\d+)+|"  # B1.3
    r"§\s*\d+(?:\.\d+)*|"
    r"FY\s*20\d{2}|"
    r"[TQ][1-4](?:\s*20\d{2})?|"
    r"H[12](?:\s*20\d{2})?"
    r")(?![A-Za-z0-9])",
    re.I,
)
_ACTION_QUANTITY_RE = re.compile(
    r"(?:\b(?:former|formez|formation de|train|training|ouvrir|open|lancer|launch|"
    r"recruter|recruit|signer|sign|prospecter|contact(?:er)?|d[ée]ployer|deploy)\b"
    r"[^\n]{0,55}?\b\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?\s*"
    r"(?:clients?|customers?|distributeurs?|distributors?|magasins?|stores?|filiales?|"
    r"subsidiaries?|partenariats?|partenaires?|partners?|collaborateurs?|employees?|salari[ée]s?))|"
    r"(?:\b\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?\s*"
    r"(?:clients?|customers?|distributeurs?|distributors?|magasins?|stores?|filiales?|"
    r"subsidiaries?|partenariats?|partenaires?|partners?|collaborateurs?|employees?|salari[ée]s?)\b)",
    re.I,
)
_GENERIC_FALLBACK_RE = re.compile(
    r"(?:Proposition quantifi[ée]e [ée]cart[ée]e|Cible chiffr[ée]e [ée]cart[ée]e|"
    r"Quantified (?:proposal|target) withheld)", re.I
)

def _analysis_text(value: Any) -> str:
    """Text used by semantic gates: strip renderer decoration, preserve meaning."""
    return _DECORATIVE_PREFIX_RE.sub("", _norm_space(value))

def _mask_non_quantity_codes(value: str) -> str:
    """Remove product/release/section codes before numeric classification."""
    return _NON_QUANTITY_CODE_RE.sub(" CODE ", value or "")


def _norm_number_token(value: str) -> str:
    s = value.lower().replace("\u202f", " ").replace("\xa0", " ")
    s = s.replace("−", "-").replace("–", "-")
    s = re.sub(r"\s+", "", s)
    s = s.replace(",", ".")
    s = re.sub(r"[^0-9.\-+]", "", s)
    return s


def _metric_family(text: str) -> str | None:
    for family, pat in _METRIC_PATTERNS.items():
        if pat.search(text or ""):
            return family
    return None


def _iter_dicts(obj: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(obj, Mapping):
        yield obj
        for value in obj.values():
            yield from _iter_dicts(value)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            yield from _iter_dicts(value)


def _iter_strings(obj: Any) -> Iterable[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, Mapping):
        for value in obj.values():
            yield from _iter_strings(value)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            yield from _iter_strings(value)


def _fingerprint_value(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in ("fingerprint", "run_fingerprint", "run_id", "id", "digest", "sha256", "hash"):
            candidate = value.get(key)
            if candidate not in (None, "", {}):
                return _fingerprint_value(candidate)
        try:
            return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return str(value)
    return str(value or "").strip()


def _current_run_fingerprint(result: Mapping[str, Any]) -> str:
    for value in (
        result.get("run_fingerprint"),
        result.get("run_id"),
        (result.get("b1_proof_layer") or {}).get("fingerprint") if isinstance(result.get("b1_proof_layer"), Mapping) else None,
        (result.get("meta") or {}).get("run_fingerprint") if isinstance(result.get("meta"), Mapping) else None,
    ):
        fp = _fingerprint_value(value)
        if fp:
            return fp
    return "UNAVAILABLE"


def _row_fingerprint(row: Mapping[str, Any]) -> str:
    for key in ("run_fingerprint", "fingerprint", "run_id"):
        fp = _fingerprint_value(row.get(key))
        if fp:
            return fp
    return ""


def _current_diagnostics(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return only top-level diagnostics belonging to the current run.

    Historic/archived subtrees are never traversed.  Rows carrying an explicit
    fingerprint different from the current run are excluded.
    """
    rows = result.get("diagnostics_attempts")
    if not isinstance(rows, list):
        rows = result.get("diagnostics")
    if not isinstance(rows, list):
        return []
    current_fp = _current_run_fingerprint(result)
    out: list[Mapping[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        row_fp = _row_fingerprint(row)
        if current_fp != "UNAVAILABLE" and row_fp and row_fp != current_fp:
            continue
        out.append(row)
    return out


def _diagnostics(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Compatibility alias: diagnostics are current-run only since v62.13.8."""
    return _current_diagnostics(result)


def _jsonish(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s or s[0] not in "[{":
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def _priority_peek_by_filename(result: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for row in _diagnostics(result):
        if str(row.get("role") or "") != "financial_deep_scan":
            continue
        parsed = _jsonish(row.get("pdf_priority"))
        if not isinstance(parsed, list):
            continue
        for item in parsed:
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("filename") or "").strip()
            if name:
                out[name] = item
    return out


def classify_document_extractability(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return one truthful text/OCR status per scanned PDF.

    Precedence is deterministic: actual extracted sections/chars beat the
    one-page priority peek; an explicit scan/no-text result beats an ambiguous
    "not a financial statement" note.  Duplicate documents are not presented
    as OCR failures.
    """
    peek = _priority_peek_by_filename(result)
    records: dict[str, dict[str, Any]] = {}
    for row in _diagnostics(result):
        if str(row.get("role") or "") != "financial_statements_extraction":
            continue
        fs = _jsonish(row.get("fs_log"))
        if not isinstance(fs, Mapping):
            continue
        name = str(fs.get("filename") or "").strip()
        if not name:
            continue
        notes = " ".join(str(x or "") for x in (fs.get("notes") or []))
        notes_low = notes.lower()
        sections = [str(x) for x in (fs.get("sections_detected") or []) if x]
        total_chars = int(fs.get("total_chars") or 0)
        tokens = int(fs.get("tokens_estimate") or 0)
        detected = bool(fs.get("financial_statements_detected"))
        p = peek.get(name) or {}
        peek_chars = int(p.get("priority_peek_chars") or 0)
        peek_status = str(p.get("priority_peek_status") or "").upper()
        duplicate = "doublon" in notes_low or "duplicate" in notes_low
        explicit_scan = any(token in notes_low for token in (
            "pdf scanné détecté", "pdf scanné", "ocr requis", "peu/pas de texte extractible", "no text extractible",
            "scanned detected", "scan profond skippé", "deep scan skipped",
        ))
        actual_text = total_chars >= 200 or tokens >= 50 or bool(sections) or detected
        peek_text = peek_chars >= 200 and peek_status not in {"NO_TEXT", "ERROR"}
        if actual_text:
            status = "TEXT_EXTRACTED"
            reason = "financial text/sections extracted"
        elif duplicate:
            status = "PARTIALLY_EXTRACTABLE"
            reason = "duplicate skipped; use the retained source document"
        elif explicit_scan and not peek_text:
            status = "OCR_REQUIRED"
            reason = "no exploitable financial text"
        elif peek_text:
            status = "TEXT_EXTRACTED"
            reason = "text extracted; no structured financial statement confirmed"
        else:
            status = "PARTIALLY_EXTRACTABLE"
            reason = "extractability ambiguous or limited"
        records[name] = {
            "filename": name,
            "status": status,
            "reason": reason,
            "financial_statements_detected": detected,
            "sections_detected": sections,
            "total_chars": total_chars,
            "priority_peek_chars": peek_chars,
        }
    return sorted(records.values(), key=lambda item: item["filename"].casefold())


def collect_ocr_required_files(result: Mapping[str, Any]) -> list[str]:
    return [item["filename"] for item in classify_document_extractability(result)
            if item.get("status") == "OCR_REQUIRED"]


def collect_partially_extractable_files(result: Mapping[str, Any]) -> list[str]:
    return [item["filename"] for item in classify_document_extractability(result)
            if item.get("status") == "PARTIALLY_EXTRACTABLE"]


def collect_text_extracted_files(result: Mapping[str, Any]) -> list[str]:
    return [item["filename"] for item in classify_document_extractability(result)
            if item.get("status") == "TEXT_EXTRACTED"]

def collect_detected_sections(result: Mapping[str, Any]) -> list[str]:
    sections: set[str] = set()
    for row in _diagnostics(result):
        if str(row.get("role") or "") != "financial_statements_extraction":
            continue
        parsed = _jsonish(row.get("fs_log"))
        if isinstance(parsed, Mapping) and bool(parsed.get("financial_statements_detected")):
            for sec in parsed.get("sections_detected") or []:
                if sec:
                    sections.add(str(sec))
    return sorted(sections)


def _iter_current_evidence_rows(result: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    """Yield financial evidence containers only; never analysis context or history."""
    keys = (
        "canonical_financial_claims", "canonical_claims", "numeric_support_claims",
        "financial_facts", "financial_facts_table", "financial_proof_layer",
    )

    def walk(value: Any) -> Iterable[Mapping[str, Any]]:
        if isinstance(value, Mapping):
            yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                yield from walk(child)

    for key in keys:
        value = result.get(key)
        if value is not None:
            yield from walk(value)


def _explicit_group_consolidated_evidence(result: Mapping[str, Any]) -> bool:
    """Positive proof requires a page-confirmed consolidated financial fact.

    A requested target perimeter (``analysis_context.target_perimeter_level``)
    is not evidence and is deliberately ignored.
    """
    for row in _iter_current_evidence_rows(result):
        scope = str(row.get("scope") or row.get("perimeter") or row.get("scope_tag") or "").upper()
        if not ("GROUP_CONSOLIDATED" in scope or scope in {"CONSOLIDATED", "GROUPE_CONSOLIDE", "GROUPE CONSOLIDÉ"}):
            continue
        metric = row.get("metric") or row.get("metric_id") or row.get("label") or row.get("fact")
        value = row.get("value") or row.get("formatted_value") or row.get("amount")
        if metric in (None, "") or value in (None, ""):
            continue
        status = str(row.get("status") or row.get("proof_status") or row.get("evidence_status") or "").upper()
        confirmed = bool(row.get("page_confirmed") or row.get("confirmed_on_page")) or status in {
            "CONFIRMED_ON_PAGE", "PAGE_CONFIRMED", "PROVED_ON_PAGE", "CONFIRMED"
        }
        page = row.get("page") or row.get("source_page") or row.get("cited_page")
        source = str(row.get("source") or row.get("source_doc") or row.get("document") or row.get("filename") or "").lower()
        if not confirmed or not page or "web" in source:
            continue
        return True
    return False


def financial_scope_summary(result: Mapping[str, Any], lang: str = "fr") -> dict[str, Any]:
    sections = collect_detected_sections(result)
    document_extractability = classify_document_extractability(result)
    ocr_files = [x["filename"] for x in document_extractability if x.get("status") == "OCR_REQUIRED"]
    partial_files = [x["filename"] for x in document_extractability if x.get("status") == "PARTIALLY_EXTRACTABLE"]
    text_files = [x["filename"] for x in document_extractability if x.get("status") == "TEXT_EXTRACTED"]
    has_fs = bool(sections) or bool(result.get("financial_statements_detected"))
    has_group = _explicit_group_consolidated_evidence(result)
    analysis_context = result.get("analysis_context")
    if not isinstance(analysis_context, Mapping):
        b1 = result.get("b1_proof_layer")
        analysis_context = (b1 or {}).get("analysis_context") if isinstance(b1, Mapping) else {}
    target = ""
    if isinstance(analysis_context, Mapping):
        target = str(analysis_context.get("target_perimeter_level") or analysis_context.get("target_perimeter") or "")
    return {
        "structured_statements_detected": has_fs,
        "detected_sections": sections,
        "group_consolidated_accounts_provided": has_group,
        "target_perimeter": target or "unknown",
        "ocr_required_files": ocr_files,
        "partially_extractable_files": partial_files,
        "text_extracted_files": text_files,
        "document_extractability": document_extractability,
    }



def _period_year(row: Mapping[str, Any]) -> int | None:
    for key in ("period_end", "period", "fiscal_year", "fy", "year", "label", "fact"):
        value = str(row.get(key) or "")
        match = re.search(r"\b20\d{2}\b", value)
        if match:
            return int(match.group(0))
    return None


def _is_evidentiary_fact(row: Mapping[str, Any]) -> bool:
    status = str(row.get("status") or row.get("proof_status") or row.get("evidence_status") or "").upper()
    source = str(row.get("source") or row.get("source_doc") or row.get("document") or row.get("filename") or "").lower()
    return bool(
        row.get("page_confirmed") or row.get("confirmed_on_page")
        or status in {"CONFIRMED_ON_PAGE", "PAGE_CONFIRMED", "PROVED_ON_PAGE", "CONFIRMED", "FACT", "FAIT"}
        or any(token in source for token in ("pappers", "registry", "registre", "comptes sociaux", "annual report"))
    )


def supported_revenue_facts(result: Mapping[str, Any]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    for row in _iter_current_evidence_rows(result):
        blob = " ".join(str(row.get(k) or "") for k in ("metric", "metric_id", "label", "fact", "canonical_line"))
        if _metric_family(blob) != "revenue" or not _is_evidentiary_fact(row):
            continue
        year = _period_year(row)
        value = row.get("value") or row.get("formatted_value") or row.get("amount")
        if year and value not in (None, ""):
            out.setdefault(year, []).append({
                "value": str(value),
                "source": str(row.get("source") or row.get("source_doc") or row.get("document") or ""),
                "scope": str(row.get("scope") or row.get("perimeter") or row.get("scope_tag") or ""),
            })
    return out


_MARKET_GROWTH_RE = re.compile(
    r"(?:march[ée]s?|markets?|segments?|secteurs?|sectors?)\b[^.\n]{0,90}?"
    r"\b(?:croissances?|growth|progressions?|expansions?|dynamiques?)"
    r"|(?:croissances?|growth|progressions?|expansions?)\b[^.\n]{0,40}?"
    r"\b(?:march[ée]s?|markets?|segments?|secteurs?|sectors?)", re.I)
_MARKET_GROWTH_FR = "Dynamique de marché non établie — à documenter par source sectorielle."
_MARKET_GROWTH_EN = "Market momentum not established — to be documented from sector sources."


def _unsupported_market_growth(text: str, result: Mapping[str, Any]) -> bool:
    """v62.13.9.4.8 (terrain réel du 13/08/2026) — une affirmation de croissance
    de marché chiffrée (%) au présent/prospectif, sans claim qui la supporte,
    contredit la réconciliation du run : elle est réécrite qualitativement
    dans TOUTES les sorties. Le passé factuel réel prime et reste conservé."""
    t = _norm_space(text)
    if not _MARKET_GROWTH_RE.search(t):
        return False
    if not re.search(r"[+\-−]?\d+(?:[.,]\d+)?\s?%", t):
        return False
    # v62.13.9.4.18 — point 6 : une croissance de marché qui CITE sa source
    # n'est pas retirée ; elle est étiquetée « benchmark non vérifié » par
    # _benchmark_label_line (le corps garde le chiffre, jamais comme fait).
    try:
        from utils.quantity_ledger import has_source_label as _hsl62418
        if _hsl62418(t):
            return False
    except Exception:
        pass
    try:
        from utils.quantity_ledger import _has_factual_past as _hfp62148
        if _hfp62148(t, "fr") or _hfp62148(t, "en"):
            return False
    except Exception:
        pass
    support = list(result.get("numeric_support_claims")
                   or result.get("canonical_financial_claims")
                   or result.get("canonical_claims") or [])
    support += _registry_support62427(result)
    if support:
        try:
            from utils.claim_binding import supports as _sup62148
            if _sup62148(t, support):
                return False
        except Exception:
            pass
    return True


_FULL_DATE_MASK_RE = re.compile(
    r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b|\b\d{1,2}[-/.]\d{1,2}[-/.](?:19|20)\d{2}\b|\b\d{1,2}/(?:19|20)\d{2}\b|"
    r"\b\d{1,2}(?:er)?\s+(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|octobre|novembre|d[ée]cembre|"
    r"january|february|march|april|may|june|july|august|september|october|november|december)\s+(?:19|20)\d{2}\b", re.I)


_DATA_REQUEST_RE = re.compile(
    r"\b(?:fournir|communiquer|transmettre|collecter|obtenir|documenter|reconstituer|demander|calibrer|renseigner|"
    # v62.13.9.4.28 — formes nominales : « Collecte des données financières 2023-2025 »
    r"collecte|recueil|obtention|reconstitution|r[ée]cup[ée]ration|remont[ée]e|demande\s+de\s+(?:donn[ée]es|informations|comptes|liasses)|"
    r"à\s+(?:fournir|communiquer|collecter|documenter|obtenir|renseigner|reconstituer)|"
    r"donn[ée]es?\s+(?:à\s+\w+|manquantes?|n[ée]cessaires?|attendues?|demand[ée]es?)|informations?\s+(?:à\s+\w+|manquantes?)|"
    r"manque\s+de\s+donn[ée]es?|absence\s+de\s+(?:donn[ée]es?|comptes|liasses)|pour\s+calibrer|"
    r"provide|collect|obtain|supply|request|missing\s+data|data\s+(?:needed|required|to\s+collect))\b", re.I)


def _unsupported_revenue_trend(text: str, result: Mapping[str, Any]) -> bool:
    t = _norm_space(text)
    if not re.search(r"(?:chiffre\s+d['’]affaires|\bca\b|revenue|croissance|tcam|growth)", t, re.I):
        return False
    # v62.13.9.4.27 — contre-audit v25 (§5) : « CA, jours facturés et TJM réel
    # 2023-2025 pour calibrer… » est une DEMANDE DE DONNÉES, pas un calcul de
    # croissance : la règle de tendance ne s'applique pas à une ligne qui demande,
    # collecte ou signale des données manquantes.
    if _DATA_REQUEST_RE.search(t) and not re.search(r"[+\-−]\s?\d+(?:[.,]\d+)?\s?%|\bx\s?\d|\btcam\b|\bcagr\b|passe\s+de|passer\s+de|en\s+(?:hausse|baisse)\s+de", t, re.I):
        return False
    # v62.13.9.4.25 — contre-audit v24 (§3) : « 1. Audit pipeline et définition
    # CA cible | Robin SAUZET | 2026-09-30 | objectif CA 2027 chiffré » n'est pas
    # une tendance de CA entre 2026 et 2027 : 2026 est une DATE D'ÉCHÉANCE. Une
    # date complète est masquée avant de compter les années ; une tendance
    # exige deux années de CA, pas une année de CA et une échéance.
    years = {int(x) for x in re.findall(r"\b20\d{2}\b", _FULL_DATE_MASK_RE.sub(" ", t))}
    if len(years) < 2:
        return False
    supported = supported_revenue_facts(result)
    return any(year not in supported for year in years)


def _social_revenue_card(result: Mapping[str, Any]) -> dict[str, str] | None:
    facts = supported_revenue_facts(result)
    if not facts:
        return None
    for year in sorted(facts, reverse=True):
        for fact in facts[year]:
            scope = fact.get("scope", "").upper()
            source = fact.get("source", "")
            if "SOCIAL" in scope or "STANDALONE" in scope or "pappers" in source.lower() or "registre" in source.lower():
                return {"year": str(year), "value": fact["value"], "source": source or "Pappers", "scope": "SOCIAL_STANDALONE"}
    return None

def _canonical_claim_rows(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for d in _iter_dicts(result):
        claims = d.get("canonical_claims")
        if isinstance(claims, list):
            rows.extend(c for c in claims if isinstance(c, Mapping))
    return rows


def _claim_amount_metric_map(result: Mapping[str, Any]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for claim in _canonical_claim_rows(result):
        text = " ".join(str(claim.get(k) or "") for k in ("metric", "metric_id", "label", "text", "canonical_line"))
        family = _metric_family(text)
        values: list[str] = []
        for key in ("value", "formatted_value", "amount", "text", "canonical_line"):
            v = claim.get(key)
            if v is None:
                continue
            values.extend(m.group(0) for m in _AMOUNT_RE.finditer(str(v)))
        if family:
            for val in values:
                n = _norm_number_token(val)
                if n:
                    out.setdefault(n, set()).add(family)
    return out


def _numbers_in(text: str) -> list[str]:
    return [n for n in (_norm_number_token(m.group(0)) for m in _AMOUNT_RE.finditer(text or "")) if n]


_FYE_RE47 = re.compile(
    r"(?i)(?:fiscal\s+year[\s-]*end|year[\s-]*end|exercice\s+(?:social\s+)?clos|cl[ôo]ture\s+(?:de\s+l['’])?exercice)\s*:?\s*(?:le\s+)?"
    r"(?:(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}"
    r"|\d{1,2}\s+(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre)"
    r"|\d{1,2}/\d{1,2})\b")


def _date_only_numeric_line(line: str) -> bool:
    """True only when date/owner metadata is the whole semantic content."""
    text = _analysis_text(line)
    # v62.13.9.4.47 — la date de clôture d'un exercice (« Fiscal Year End: August 31 »,
    # « Exercice social clos le 31 août ») est une métadonnée de date, pas une quantité.
    text = _FYE_RE47.sub(" ", text)
    if not _DATE_RE.search(text):
        return not re.search(r"\d", text) and bool(_FYE_RE47.search(_analysis_text(line)))
    residual = _DATE_RE.sub(" ", text)
    residual = re.sub(
        r"\b(?:date\s+de\s+fin\s+cible|target\s+end\s+date|prochaine\s+échéance|prochaine\s+echeance|échéance|echeance|deadline|date|quand|when|jalon|milestone)\b\s*: ?",
        " ", residual, flags=re.I,
    )
    residual = re.sub(
        r"\b(?:responsable|owner|porteur)\b\s*:\s*[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .&'’/+-]*?(?=(?:\||;|—|$))",
        " ", residual, flags=re.I,
    )
    residual = re.sub(r"[|;,:.()\[\]{}—–\-]+", " ", residual)
    residual = re.sub(r"\s+", " ", residual).strip()
    # Any surviving word or digit means the line is not date-only.
    return residual == ""


_OPERATIONAL_DURATION_RE = re.compile(
    r"\b(?:delay|d[ée]lai|lead\s*time|implementation|mise\s+en\s+[œo]uvre|"
    r"rollout|recruitment|recrutement|homologation|launch|lancement|deployment|d[ée]ploiement)\b",
    re.I,
)
_DURATION_VALUE_RE = re.compile(
    r"\b\d{1,3}\s*(?:[-–]\s*\d{1,3}\s*)?"
    r"(?:minutes?|heures?|hours?|jours?|days?|semaines?|weeks?|mois|months?|ans?|years?)\b",
    re.I,
)


def _planning_contract_values(result: Mapping[str, Any] | None) -> tuple[set[int], set[str]]:
    """Return current-run strategic months and target end dates only."""
    months: set[int] = set()
    end_dates: set[str] = set()
    if not isinstance(result, Mapping):
        return months, end_dates
    candidates: list[Mapping[str, Any]] = [result]
    for key in ("strategic_horizon", "horizon_reconciliation", "temporal_context", "meta"):
        value = result.get(key)
        if isinstance(value, Mapping):
            candidates.append(value)
    # v62.13.9.3 / SCN-009 — real sessions expose the Temporal Core contract
    # as a current-run diagnostics row.  History remains excluded by
    # _current_diagnostics: an archived date can never authorise this run.
    for row in _current_diagnostics(result):
        role = str(row.get("role") or "").strip().lower()
        if role in {"strategic_horizon", "horizon_reconciliation", "temporal_context"} or row.get("target_end_date"):
            candidates.append(row)
    for obj in candidates:
        for key in ("explicit_months", "strategic_horizon_months", "horizon_months", "months"):
            try:
                value = int(float(obj.get(key)))
            except Exception:
                continue
            if 1 <= value <= 120:
                months.add(value)
        for key in ("target_end_date", "strategic_target_end_date", "end_date"):
            value = str(obj.get(key) or "")[:10]
            if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", value):
                end_dates.add(value)
    return months, end_dates


def _planning_horizon_line(line: str, result: Mapping[str, Any] | None = None) -> bool:
    """Allow only a shape-bound strategic planning contract.

    Operational durations (delay, implementation, rollout, recruitment,
    homologation or launch) are never exempted, even when prefixed by Horizon,
    Roadmap or Planning contract. When the run carries Temporal Core values,
    the duration/end date must match them.
    """
    text = _analysis_text(line)
    if not text or _OPERATIONAL_DURATION_RE.search(text):
        return False
    if re.search(
        r"(?:[€£$]|%|\b(?:clients?|customers?|salari[ée]s?|employees?|filiales?|"
        r"subsidiaries?|partenariats?|partenaires?|partners?|kpi|pdm|market\s+share)\b)",
        text, re.I,
    ):
        return False

    expected_months, expected_dates = _planning_contract_values(result)
    # Fail closed without the current-run Temporal Core contract. Shape alone
    # is not authority and was the bypass found during the v62.13.9.1 audit.
    if not expected_months and not expected_dates:
        return False
    dates = re.findall(r"\b20\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b", text)
    for day, month, year in re.findall(
        r"\b(0?[1-9]|[12]\d|3[01])/(0?[1-9]|1[0-2])/(20\d{2})\b", text
    ):
        dates.append(f"{year}-{int(month):02d}-{int(day):02d}")
    month_range = re.search(r"\b\d{1,3}\s*[-–]\s*\d{1,3}\s*(?:mois|months?)\b", text, re.I)
    month_value = re.search(r"\b(\d{1,3})\s*(?:mois|months?)\b", text, re.I)
    if month_range:
        return False

    if re.fullmatch(
        r"(?:target\s+by|target\s+end\s+date|date\s+de\s+fin\s+cible|cible\s+(?:au|le))\s*:?\s*"
        r"(?:20\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])|"
        r"(?:0?[1-9]|[12]\d|3[01])/(?:0?[1-9]|1[0-2])/20\d{2})",
        text, re.I,
    ):
        return bool(dates and dates[-1] in expected_dates)

    if re.fullmatch(
        r"(?:milestone|jalon)\s*:\s*20\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\s*"
        r"(?:to|au|–|—|-)\s*20\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])",
        text, re.I,
    ):
        return bool(dates and dates[-1] in expected_dates)

    if re.fullmatch(
        r"(?:strategic\s+plan|plan\s+strat[ée]gique)(?:\s+[A-Za-zÀ-ÖØ-öø-ÿ0-9&.'’_-]+){0,8}\s+"
        r"20\d{2}\s*[-–]\s*20\d{2}(?:\s*[—–-]\s*(?:target\s+end\s+date|date\s+de\s+fin\s+cible)\s*"
        r"20\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01]))?",
        text, re.I,
    ):
        if not expected_dates:
            return False
        if dates:
            return dates[-1] in expected_dates
        year_range = re.search(r"\b20\d{2}\s*[-–]\s*(20\d{2})\b", text)
        return bool(year_range and any(d.startswith(year_range.group(1) + "-") for d in expected_dates))

    if re.fullmatch(
        r"(?:horizon|strategic\s+horizon|horizon\s+strat[ée]gique)\s*:\s*\d{1,3}\s*(?:mois|months?)"
        r"(?:\s*\((?:contrat\s+de\s+planification|planning\s+contract)\))?",
        text, re.I,
    ):
        value = int(month_value.group(1)) if month_value else None
        return bool(expected_months and value in expected_months)

    if re.fullmatch(
        r"horizon\s*:\s*\d{1,3}\s*(?:mois|months?)\s*\(\s*(?:from|du)\s+"
        r"20\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\s+(?:to|au)\s+"
        r"20\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\s*\)",
        text, re.I,
    ):
        value = int(month_value.group(1)) if month_value else None
        if not expected_months or value not in expected_months:
            return False
        return bool(expected_dates and dates and dates[-1] in expected_dates)
    return False


_LEGAL_STATUS_CLAIM_RE = re.compile(
    r"\b(?:radiation|radi[ée]e?s?|cessation\s+d[e']activit[ée]|"
    r"mise\s+en\s+sommeil|liquidation|redressement\s+judiciaire|"
    r"proc[ée]dure\s+collective|dissolution|struck\s+off|dissolved|"
    r"wound\s+up|in\s+liquidation)\b", re.I)


def _registry_says_active62413(result) -> bool:
    """Le registre officiel atteste-t-il une entité EN ACTIVITÉ ?"""
    res = result if isinstance(result, dict) else {}
    prof = res.get("company_profile") or res.get("profile") or {}
    if not isinstance(prof, dict):
        return False
    if str(prof.get("source") or "").strip().lower() not in (
            "pappers", "gleif", "rne", "inpi"):
        return False
    blob = " ".join(str(prof.get(k) or "") for k in
                    ("status", "statut", "etat", "state", "notes")).lower()
    if _LEGAL_STATUS_CLAIM_RE.search(blob):
        return False
    # v62.13.9.4.15 — ACTIVE n'est jamais déduit d'un numéro ou d'une
    # forme juridique (préflight ChatGPT du 02/09/2026 : risque inverse de
    # supprimer une radiation véritable). Seul le statut EXPLICITE du
    # registre, lu dans la fiche, fait foi ; UNKNOWN ne neutralise rien.
    return str(prof.get("registry_status") or "").upper() == "ACTIVE"


def _contradicts_registry62413(line: str, result) -> bool:
    """v62.13.9.4.13 — AUTORITÉ DU REGISTRE sur la narration du modèle.

    Le run du 02/09/2026 a bâti tout son livrable sur une « radiation du RCS
    de Rennes » que le compte rendu marquait lui-même NON SOURCÉE, alors que
    la fiche de registre du même run donnait l'entreprise inscrite et active.
    Cette affirmation est devenue l'axe du document, le titre de plusieurs
    slides et une décision de retrait.

    Une affirmation d'extinction juridique contredite par le statut structuré
    du registre est neutralisée comme question à vérifier — jamais servir de
    fait directeur.
    """
    text = str(line or "")
    if not _LEGAL_STATUS_CLAIM_RE.search(text):
        return False
    return _registry_says_active62413(result)



def _registry_support62427(result) -> list:
    """v62.13.9.4.12.7 — les FAITS DE REGISTRE rejoignent les claims de support.

    ``registry_claims`` avait été écrit et validé isolément au cycle
    précédent, mais **jamais câblé dans la chaîne** : le run du 02/09/2026 a
    de nouveau bloqué sur « 0 salariés », le fait Pappers, alors que la
    conversion existait. Une fonction non appelée ne corrige rien.
    """
    try:
        from utils.quantity_ledger import registry_claims as _rc62427
        return list(_rc62427(result) or [])
    except Exception:
        return []


def _support_claims(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return only full canonical claims with numeric components and proof data."""
    for key in ("numeric_support_claims", "canonical_financial_claims", "canonical_claims"):
        value = result.get(key)
        if isinstance(value, list) and value:
            usable = [
                row for row in value
                if isinstance(row, Mapping)
                and row.get("numeric_components")
                and row.get("proof_status")
            ]
            if usable:
                return usable
    return []


def _canonical_fact_line(line: str, result: Mapping[str, Any]) -> str | None:
    from utils.board_scrutiny_guard import canonical_claim_line_for_text
    rendered, _claim_id = canonical_claim_line_for_text(line, _support_claims(result))
    return rendered


def _verified_fact_line(line: str, result: Mapping[str, Any]) -> bool:
    """A tag/source/page is metadata; only a matching canonical claim is proof."""
    if not (_FACT_MARKER.search(line) or _SOURCE_MARKER.search(line)):
        return False
    return _canonical_fact_line(line, result) is not None

# ── v62.13.9.4.2 — contrats éditoriaux bornés (généralisés en v62.13.9.4.3) ──
# Nomenclature fermée Sirene/INSEE. Une tranche est une donnée catégorielle,
# pas une cible prospective ; elle reste donc informative même si le profil
# structuré n'a pas encore été hydraté.
_V6213942_SIRENE_BANDS = (
    (1, 2), (3, 5), (6, 9), (10, 19), (20, 49), (50, 99),
    (100, 199), (200, 249), (250, 499), (500, 999),
    (1000, 1999), (2000, 4999), (5000, 9999),
)
_V6213942_RANGE_RE = re.compile(
    r"(?<!\d)(?P<lo>\d{1,5})\s*[-–—]\s*(?P<hi>\d{1,5})(?!\d)", re.I,
)
_V6213942_HEADCOUNT_NOUN_RE = re.compile(
    r"\b(?:effectif|tranche(?:\s+d['’]effectif)?|salari[ée]s?|collaborateurs?|"
    r"employ[ée]s?|workforce|employees?|headcount)\b", re.I,
)
_V6213942_HEADCOUNT_TARGET_RE = re.compile(
    r"\b(?:recrut(?:er|ement)|embauch(?:er|e|es)|porter\s+l['’]effectif|"
    r"atteindre|objectif|cible|prévoir|planifier|augmenter|réduire)\b", re.I,
)
_V6213942_COMPLETED_RE = re.compile(
    r"(?<![\w/.,:\-–])\d+(?:[.,]\d+)?\s+[^.\n;]{0,60}?\b(?:tenu|réalisé|realisé|signé|livré|achevé|clos|"
    r"effectué|terminé|finalisé|accompli|atteint|conclu|obtenu|held|completed|delivered|signed|"
    r"achieved|closed)(?:e|es|s)?\b", re.I,
)
_V6213943_FUTURE_TARGET_RE = re.compile(
    r"\b(?:d['’]ici|avant|by|objectifs?|cibles?|targets?|ambition|à\s+r[ée]aliser|à\s+livrer|à\s+atteindre|"
    r"to\s+deliver|to\s+achieve|to\s+reach|pr[ée]vu(?:e|s|es)?|planned|expected)\b", re.I,
)
_V6213942_PRODUCT_ATTRIBUTE_RE = re.compile(
    r"\b100\s*%\s*(?:électrique|electric|recyclé|recyclable|biosourcé|digital|numérique)\b", re.I,
)
_V6213942_NEW_TARGET_RE = re.compile(
    r"\b(?:convertir|conversion|réaliser|realiser|acquérir|acquerir|acquisition(?:s)?|"
    r"ouvrir|déployer|deployer|former|recruter|signer)\b.{0,90}\b\d+(?:[.,]\d+)?\b|"
    r"\b\d+(?:[.,]\d+)?\b.{0,60}\b(?:clients?\s+prioritaires?|acquisitions?\s+ciblées?)\b",
    re.I,
)
_V6213942_ALREADY_QUALIFIED_RE = re.compile(
    r"\b(?:à\s+dimensionner|à\s+valider|à\s+arbitrer|volume\s+à\s+valider|"
    r"niveau\s+à\s+valider|calendrier\s+à\s+arbitrer)\b", re.I,
)
_V6213942_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-ÞÉÈÊÎÔÛÇ])")
_V6213942_GENERIC_FALLBACK_RE = re.compile(
    r"^\s*(?:[-*•▌]+\s*)?(?:Proposition quantifi[ée]e [ée]cart[ée]e.*|"
    r"Cible chiffr[ée]e [ée]cart[ée]e.*|Quantified (?:proposal|target) withheld.*|"
    r"Cible chiffr[ée]e non [ée]tay[ée]e.*|(?:À|A) compl[ée]ter[.!]?$|"
    r"(?:À|A) arbitrer[.!]?$)", re.I,
)
_V6213942_ANNEX_HEADING_RE = re.compile(
    # v62.13.9.4.31 — les rubriques des Word sont numérotées « §N — » : le préfixe
    # ne change pas la nature du titre.
    r"^(?:§\s*\d{1,3}\s*[—–-]\s*)?(?:(?:annexe|annex)\b.{0,80}(?:sc[ée]narios?|scenarios?|unvalidated quantified)|"
    r"Complément v62\.13\.\d[^\n]{0,80}(?:scénarios|scenarios|Registre embarqué|Embedded register)|"
    # v62.13.9.4.49 — nouveau titre de l'annexe (plus de numéro de version interne)
    r"\u2063?(?:Registre des passages signalés|Register of flagged passages))", re.I,
)
_V6213942_ANNEX_TECHNICAL_RE = re.compile(
    r"^\s*(?:Remplacement ex[ée]cutif|Executive replacement|Validation requise|Validation required)\s*:", re.I,
)
_V6213942_PRUDENCE_NOTE = (
    "Note de prudence — Les cibles chiffrées non étayées ont été neutralisées "
    "sans supprimer les constats qualitatifs ; leur dimensionnement relève de l’arbitrage."
)
_V6213942_RESTORED_HEADING = "Contenus qualitatifs et faits qualifiés restaurés"
_V6213942_ANNEX_TREATMENT_LINE = (
    "Traitement : chaque passage chiffré non étayé reste en place dans le corps, signalé « ⚠ à vérifier — motif » ; "
    "toute cible chiffrée requiert baseline, provenance, formule et validation du porteur."
)
_V6213942_ANNEX_TREATMENT_LINE_EN = (
    "Treatment: every unsupported quantified passage stays in place in the body, flagged “⚠ to verify — reason”; "
    "every quantified target requires a baseline, provenance, formula and owner validation."
)


def _v6213942_band_pair(value: Any) -> tuple[int, int] | None:
    match = _V6213942_RANGE_RE.search(str(value or ""))
    if not match:
        return None
    pair = (int(match.group("lo")), int(match.group("hi")))
    return pair if pair in _V6213942_SIRENE_BANDS else None


def _v6213942_band_from_upper_bound(value: Any) -> tuple[int, int] | None:
    try:
        number = int(float(str(value).strip().replace(" ", "")))
    except (TypeError, ValueError):
        return None
    return next((pair for pair in _V6213942_SIRENE_BANDS if number == pair[1]), None)


def _v6213942_is_closed_headcount_descriptor(text: str) -> bool:
    value = str(text or "")
    if not _V6213942_HEADCOUNT_NOUN_RE.search(value):
        return False
    if _V6213942_HEADCOUNT_TARGET_RE.search(value):
        return False
    return _v6213942_band_pair(value) is not None


def _v6213942_is_completed_activity(text: str) -> bool:
    value = str(text or "")
    return bool(_V6213942_COMPLETED_RE.search(value)) and not _V6213943_FUTURE_TARGET_RE.search(value)


def _v6213942_is_product_attribute(text: str) -> bool:
    value = str(text or "")
    if not _V6213942_PRODUCT_ATTRIBUTE_RE.search(value):
        return False
    residual = _V6213942_PRODUCT_ATTRIBUTE_RE.sub("", value)
    return not re.search(r"\b\d+(?:[.,]\d+)?\b", _mask_non_quantity_codes(residual))


def _v6213942_rewrite_target_sentence(sentence: str, result: Mapping[str, Any] | None = None) -> str:
    """Compatibilité 9.4.2 : réécriture d'une phrase (voir _v6213943_rewrite_sentence)."""
    out = _v6213943_rewrite_sentence(sentence, result or {}, force=False)
    return out if out is not None else ""


def _v6213942_rewrite_text(text: str, result: Mapping[str, Any] | None = None, *, is_heading: bool = False,
                           lang: str = "fr") -> str:
    """Compatibilité 9.4.2 : réécriture d'un texte (voir _v6213943_rewrite_text).

    v62.13.9.4.37 — ce wrapper forçait « fr » quelle que soit la langue du run : les
    rubriques « orientation recommandée » et « lecture du dirigeant » des dossiers
    anglais (deux runs réels du 18/09/2026, 16 et 14 occurrences) recevaient
    « un calendrier à arbitrer » et « une enveloppe à dimensionner ». La langue est
    désormais transmise ; le défaut par « fr » ne sert qu'aux appelants historiques.
    """
    out = _v6213943_rewrite_text(text, result or {}, lang, is_heading=is_heading, force=False)
    return out if out is not None else ""


# ── v62.13.9.4.3 — invariant de sortie générique ──────────────────────────────
# Règle : une phrase retenue par la couche de décision ne revient JAMAIS sur une
# surface principale (corps Word, slide) avec un cardinal résiduel, quel que soit
# le vocabulaire du dossier. Aucun lexique n'est porteur : les noms comptés sont
# reconnus génériquement (cardinal + nom), et si un cardinal survit à la
# réécriture, la phrase est retirée du corps (elle reste intégralement en annexe).
_V6213943_UNIT_WORD_RE = re.compile(
    r"^(?:%|pts?|points?|pp|bps|x|k|m|bn|md|mio|million(?:s)?|milliard(?:s)?|mois|semaines?|"
    r"jours?|ans?|ann[ée]es?|h|heures?|hours?|days?|weeks?|months?|years?|km|kwh|kg|kw|mw|gw|"
    r"t|tonnes?|m²|m2|ha|€|£|\$|M€|k€|Md€|fois|times|x)$",
    re.I,
)
_V6213943_COUNT_RE = re.compile(
    r"(?<![\w/.,:\-–])(?P<num>\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?)\s+"
    r"(?P<adj>(?:nouveaux?|nouvelles?|new|premi(?:er|ers|ère|ères)|grands?|grandes?|"
    r"petit(?:s|es?)?|principa(?:l|ux|le|les)|autres?|additional|extra)\s+)?"
    r"(?P<noun>points?\s+de\s+vente|points?\s+of\s+sale|[a-zà-öø-ÿA-ZÀ-Ö][\w'’-]{2,})",
    re.I,
)
_V6213943_ACTION_INTENT_RE = re.compile(
    r"\b(?:"
    r"former|formez|ouvrir|ouvrez|lancer|lancez|recruter|recrutez|embaucher|signer|signez|"
    r"prospecter|contacter|d[ée]ployer|[ée]quiper|fermer|convertir|cr[ée]er|acqu[ée]rir|"
    r"r[ée]aliser|installer|implanter|d[ée]velopper|cibler|atteindre|livrer|vendre|produire|"
    r"doubler|tripler|conqu[ée]rir|fid[ée]liser|g[ée]n[ée]rer|gagner|obtenir|ajouter|"
    r"train|open|launch|recruit|hire|sign|deploy|equip|close|convert|create|acquire|"
    r"deliver|sell|produce|reach|win|add|"
    r"formation|ouverture|lancement|recrutement|embauche|signature|prospection|"
    r"d[ée]ploiement|[ée]quipement|fermeture|conversion|cr[ée]ation|acquisition|"
    r"r[ée]alisation|installation|implantation|d[ée]veloppement|ciblage|livraison|"
    r"production|conqu[êe]te|opening|launching|recruitment|hiring|deployment|closure|"
    r"creation|delivery"
    r")s?\b[^.\n;]{0,70}?(?<![\w/.,:\-–])(?!(?:19|20)\d\d(?![\d/.,]))\d+(?:[.,]\d+)?"
    r"(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?\s+(?!(?:%|pts?|points?(?!\s+(?:de\s+vente|of\s+sale))|pp|bps|M€|k€|Md€|€|£|\$|"
    r"mois|semaines?|jours?|ans?|ann[ée]es?|h\b|heures?|km|kwh|kg|t\b|tonnes?|x\b|fois|"
    r"days?|weeks?|months?|years?|hours?)(?![\w]))(?:points?\s+de\s+vente|points?\s+of\s+sale|[a-zà-öø-ÿA-ZÀ-Ö][\w'’-]{2,})",
    re.I,
)
# v62.13.9.4.36 — DOCTRINE DES SCÉNARIOS : le registre est EMBARQUÉ dans le dossier
# complet, il n'existe aucune « annexe des scénarios ». Les quatre runs du 17/09/2026
# portaient 4 à 15 renvois vers cette annexe fantôme, en contradiction directe avec la
# doctrine écrite dans les huit manuels, les contrats et les textes publics.
_V6213943_REMOVED_MARK = "(phrase chiffrée retirée du corps — conservée au registre du dossier complet)"
_V6213943_REMOVED_MARK_EN = "(quantified sentence withdrawn from the body — kept in the register of the complete file)"
_V6213943_TABLE_PLACEHOLDER_FR = "Élément chiffré retiré du tableau — conservé au registre du dossier complet."
_V6213943_TABLE_PLACEHOLDER_EN = "Quantified item withdrawn from the table — kept in the register of the complete file."
_UNCERTIFIED_ROW_RE = re.compile(
    r"🔍|⛔|\bSUSPECTS?\b|\bÀ\s+V[ÉE]RIFIER\b|\bA\s+VERIFIER\b|"
    r"NON\s+CERTIFIANTE?S?|\bTO\s+VERIFY\b|\bUNVERIFIED\b", re.I)
_CONFIRMED_ROW_RE = re.compile(r"✅|✔|\bFAITS?\b|\bFACTS?\b|CONFIRM", re.I)
_AMOUNT_CELL_RE = re.compile(
    r"[+\-−]?\d[\d\s\u00A0\u202F.,]*\s*(?:€|k€|M€|k\$|M\$|\$|£|(?:EUR|USD|GBP)\b)"
    r"|^\s*[+\-−]?\d{1,3}(?:[\s\u00A0\u202F]\d{3})+(?:[.,]\d+)?\s*$", re.I)
_AMOUNT_WITHHELD_FR = "montant retiré — à confirmer sur pièce"
_AMOUNT_WITHHELD_EN = "amount withheld — to be confirmed on source"
_VALUE_WITHHELD_FR = "valeur retirée — à confirmer sur pièce"
_VALUE_WITHHELD_EN = "value withheld — to be confirmed on source"


def _row_bound_to_claim(rendered: str, result) -> bool:
    """v62.13.9.4.10 — une rangée de tableau n'est exemptée du jugement que si
    elle est liée à un claim canonique EXACT (contre-audit 30/08/2026,
    P1-948-02). Un tag ✅/FAIT/CONFIRMED n'est JAMAIS une preuve : c'est la
    doctrine 13.9.2 (balise, source et page = métadonnées), que l'exemption
    de rangée du cycle 9.4.8 violait — « CONFIRMED | Budget cible | 24 M€ |
    source.pdf | 3 » se blanchissait avec une source inventée.

    L'exemption survit pour un fait réellement sourcé (« ✅ FAIT | Effectif |
    0 salariés | Pappers | — ») parce que le run porte le claim de registre
    correspondant, pas parce que la rangée porte une étiquette.
    """
    line = _norm_space(rendered or "")
    if not line:
        return False
    res = result if isinstance(result, dict) else {}
    claims = list(res.get("numeric_support_claims")
                  or res.get("canonical_claims") or [])
    if not claims:
        return False
    try:
        from utils.claim_binding import supports as _cb_supports
        return bool(_cb_supports(line, claims))
    except Exception:
        return False


def _fact_row_in_engine_ledger(cells: list[str], rendered: str, result) -> bool:
    """v62.13.9.4.10 — une rangée du tableau de faits n'est exemptée que si
    elle correspond à une entrée STRUCTURÉE du registre du moteur
    (``financial_facts_table.facts``) : même valeur, même libellé, même
    source. C'est une liaison de PROVENANCE, pas un tag — une rangée
    fabriquée dans un tableau au bon en-tête (« CONFIRMED | Budget cible |
    24 M€ | source.pdf | 3 ») ne correspond à aucune entrée du registre et
    repart au jugement (contre-audit 30/08/2026, P1-948-02).

    Une grandeur prospective n'est JAMAIS exemptée, fût-elle inscrite au
    registre : le registre atteste d'une déclaration, jamais d'une cible.
    """
    res = result if isinstance(result, dict) else {}
    facts = ((res.get("financial_facts_table") or {}).get("facts")) or []
    if not facts or len(cells) < 3:
        return False
    metric_cell = _norm_space(cells[1])
    value_cell = _norm_space(cells[2])
    if not value_cell:
        return False
    try:
        from utils import editorial_quantity as _EQx
        if _EQx.prospective_context(rendered) or _EQx.action_signal(rendered):
            return False
    except Exception:
        return False
    low_metric = metric_cell.lower()
    low_row = _norm_space(rendered).lower()
    for f in facts:
        if not isinstance(f, Mapping):
            continue
        fv = _norm_space(str(f.get("value") or ""))
        fl = _norm_space(str(f.get("label") or "")).lower()
        fs = _norm_space(str(f.get("source_doc") or "")).lower()
        if not fv or not fl:
            continue
        if fv != value_cell:
            continue
        if fl not in low_metric:
            continue
        if fs and fs not in low_row:
            continue
        return True
    return False


def _row_values_all_in_engine_ledger(cells: list[str], result) -> bool:
    """v62.13.9.4.10 — rangée de VALEURS seules issue du registre du moteur.

    Le rendu du tableau de faits produit aussi des rangées sans libellé
    (« GBP 2.46bn | GBP 1.03bn | 67.9% »). La liaison de provenance
    libellé+valeur ne les reconnaissait pas, et le gate les bloquait alors
    que la réparation les conservait — asymétrie mise au jour par le
    déconditionnement du contrôle final (cycle 9.4.10).

    Exemption seulement si TOUTE cellule porteuse de chiffre correspond
    exactement à une valeur du registre : une seule grandeur étrangère et la
    rangée repart au jugement.
    """
    res = result if isinstance(result, dict) else {}
    facts = ((res.get("financial_facts_table") or {}).get("facts")) or []
    if not facts:
        return False
    known = {_norm_space(str(f.get("value") or "")).lower()
             for f in facts if isinstance(f, Mapping) and f.get("value")}
    if not known:
        return False
    numeric_cells = [_norm_space(c) for c in cells
                     if c and re.search(r"\d", str(c))]
    if not numeric_cells:
        return False
    return all(c.lower() in known for c in numeric_cells)


_FLAG_IN_PLACE51 = True   # 9.4.51 — plus aucune grandeur effacée des tableaux du Word


def _neutralize_uncertified_amount_cells(row, rendered, lang, residual,
                                         result_ctx=None):
    """v62.13.9.4.8 (terrain réel du 13/08/2026) — une rangée de tableau
    qualifiée non certifiante (🔍/⛔/suspect/à vérifier) ne conserve jamais
    ses montants : la trace demeure, la grandeur disparaît des octets. C'est
    l'extension aux rangées tri-state du contrat 9.4.7 « plus aucune
    exception de registre » (les montants « à vérifier » restaient visibles
    et mémorisables — contre-audit terrain du 13/08/2026)."""
    if not _UNCERTIFIED_ROW_RE.search(rendered) or _CONFIRMED_ROW_RE.search(rendered):
        return False
    if _FLAG_IN_PLACE51:
        # 9.4.51 — contre-recette ChatGPT du 03/10/2026 : cette voie était le DERNIER réécrivain du Word (« montant retiré —
        # à confirmer sur pièce » là où la réponse Finance portait la valeur et sa qualification). Doctrine « tout livrer,
        # tout signaler en place » : la grandeur reste ; la rangée, déjà qualifiée non certifiée, reçoit une mention
        # visible sur chaque cellule chiffrée. Rien n'est effacé.
        # forme STANDARD du signalement en place (« ⚠ à vérifier — motif »), reconnue par les juges et les contrats
        _tag = " ⚠ to verify — to be confirmed on a document" if str(lang).lower().startswith("en") else " ⚠ à vérifier — à confirmer sur pièce"
        touched = False
        for cell in row.cells:
            txt = _norm_space(cell.text)
            if txt and re.search(r"\d", txt) and _AMOUNT_CELL_RE.search(txt) and _tag.strip(" —") not in txt:
                cell.text = txt + _tag
                touched = True
        return touched
    touched = False
    for cell in row.cells:
        txt = _norm_space(cell.text)
        if txt and _AMOUNT_CELL_RE.search(txt):
            cell.text = (_AMOUNT_WITHHELD_EN
                         if str(lang).lower().startswith("en")
                         else _AMOUNT_WITHHELD_FR)
            touched = True
    # v62.13.9.4.9 — parité réparation ↔ oracle : une rangée non certifiée
    # garde sa trace, mais AUCUNE grandeur non prouvée n'y survit. Le score
    # de confiance nu adossé à un montant retiré (« … | 172 500 € | … |
    # 40% ») restait visible et l'oracle le bloquait à raison : la
    # réparation laissait ce que le second juge refusait.
    for cell in row.cells:
        txt = _norm_space(cell.text)
        if not txt or txt in (_AMOUNT_WITHHELD_FR, _AMOUNT_WITHHELD_EN):
            continue
        if _date_only_numeric_line(txt) or _planning_horizon_line(txt, result_ctx):
            continue
        if not re.search(r"\d", txt):
            continue
        try:
            from utils.board_scrutiny_guard import (
                find_unsupported_executive_numeric_lines as _fu)
            _sup = list((result_ctx or {}).get("numeric_support_claims")
                        or (result_ctx or {}).get("canonical_claims") or [])
            bad = _fu(txt, lang=lang, numeric_support_claims=_sup,
                      authoritative_horizon_values=_QL.build_authority_items(result_ctx))
        except Exception:
            bad = []
        if bad or _should_withhold_line(txt, result_ctx):
            cell.text = (_VALUE_WITHHELD_EN
                         if str(lang).lower().startswith("en")
                         else _VALUE_WITHHELD_FR)
            touched = True
    if touched:
        residual.append({"original": rendered,
                         "replacement": "(grandeurs de rangée non certifiée retirées)",
                         "source_type": "table_row_uncertified"})
    return touched


_V6213943_TABLE_PLACEHOLDER_EN = "Quantified item withdrawn from the table — see the working-scenario annex."
_V6213943_DECK_PLACEHOLDER_FR = "Proposition chiffrée — voir l’annexe du compte rendu."
_V6213943_DECK_PLACEHOLDER_EN = "Quantified proposal — see the report annex."
_V6213943_MARK_FR = " — volume à valider"
_V6213943_MARK_EN = " — volume to validate"


_V6213943_NOT_A_QUANTITY_RE = re.compile(
    r"^\s*(?:[-*•▌]+\s*)?(?:\d+[.)]\s+)+|(?<![\w])(?:p\.?|pages?|art\.?|articles?|§|n°|no\.?|slides?|fig\.?)\s*\d+(?:[.,]\d+)*",
    re.I,
)
_V6213943_DATE_RE = re.compile(
    r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b|\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b|\b\d{1,2}/\d{4}\b|"
    r"\b(?:19|20)\d\d\s*[-–]\s*(?:19|20)\d\d\b|\b(?:19|20)\d\d\b",
    re.I,
)
_V6213943_BAND_RE = re.compile(
    r"\btranches?\s+\d{1,6}\s*[-–]\s*\d{1,6}\b|"
    r"\b\d{1,6}\s*[-–]\s*\d{1,6}\s+(?:salari[ée]s?|employees?|employ[ée]s?|personnes?|collaborateurs?|staff)\b",
    re.I,
)
_V6213943_NUMBER_RE = re.compile(
    r"(?<![\w.,])\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?"
    r"(?:\s*(?:x|h|k|m|M|bn|Md|km|kwh|kg|kW|MW|GW|t)(?!\w))?(?![\w])"
)


def _v6213943_blank_same_length(text: str, pattern: re.Pattern[str]) -> str:
    return pattern.sub(lambda m: " " * len(m.group(0)), text)


def _v6213943_number_spans(text: str) -> list[tuple[int, int, str]]:
    """Cardinaux (plages incluses) hors dates, années, codes, numérotations, références."""
    value = str(text or "")
    masked = _v6213943_blank_same_length(value, _NON_QUANTITY_CODE_RE)
    masked = _v6213943_blank_same_length(masked, _V6213943_DATE_RE)
    masked = _v6213943_blank_same_length(masked, _V6213943_NOT_A_QUANTITY_RE)
    masked = _v6213943_blank_same_length(masked, _V6213943_BAND_RE)
    return [(m.start(), m.end(), m.group(0)) for m in _V6213943_NUMBER_RE.finditer(masked)]


def _v6213943_is_year(token: str) -> bool:
    digits = token.replace(" ", "")
    return bool(re.fullmatch(r"(?:19|20)\d\d", digits))


def _v6213943_residual_cardinals(text: str) -> list[str]:
    """Cardinaux résiduels (chiffres, montants, nombres en lettres, plages, placeholders) hors exemptions — source partagée.

    v62.13.9.4.25 — « 0 salarié(s) » (fait de registre) n'est jamais un résidu de
    réécriture : la phrase qui le porte à côté d'une cible neutralisée reste
    (« mono-personnelle avec 0 salarié, vise des missions — volume à valider »).
    La liaison de claim, elle, continue de voir le zéro (pas de masque global)."""
    value = str(text or "")
    try:
        value = _EQ.REGISTRY_ZERO_RE.sub(lambda m: " " * len(m.group(0)), value)
    except Exception:
        pass
    return _EQ.residual_cardinals(value)


def _v6213944_reference_year(result: Mapping[str, Any] | None) -> int | None:
    """Année de référence du run (autorité temporelle) si elle est connue, sinon None (année courante)."""
    if not isinstance(result, Mapping):
        return None
    candidates: list[Any] = [result.get(k) for k in ("reference_date", "run_date", "as_of_date", "temporal_reference_date", "authority_date")]
    for diag in result.get("diagnostics_attempts") or []:
        if isinstance(diag, Mapping) and str(diag.get("role") or "").startswith(("temporal", "strategic_horizon")):
            candidates += [diag.get(k) for k in ("reference_date", "run_date", "as_of_date", "authority_date", "anchor_date")]
    for value in candidates:
        m = re.search(r"\b((?:19|20)\d\d)\b", str(value or ""))
        if m:
            return int(m.group(1))
    return None


def _v6213945_authoritative_values(result: Mapping[str, Any] | None) -> set[str]:
    """v62.13.9.4.5 — valeurs du contrat de planification (Temporal Core) qui font
    autorité pour CE run : mois d'horizon explicites des diagnostics courants.
    Une ligne d'horizon dont tous les cardinaux appartiennent à cette autorité
    n'est pas une cible non étayée (« Horizon : 24 mois »)."""
    values: set[str] = set()
    try:
        # v62.13.9.4.6 — le contrat peut aussi vivre en top-level du run
        # (dict {"months": N, "target_end_date": ...} ou entier nu).
        top = (result or {}).get("strategic_horizon")
        if isinstance(top, Mapping):
            for key in ("explicit_months", "months", "horizon_months"):
                try:
                    value = int(float(top.get(key)))
                except Exception:
                    continue
                if 1 <= value <= 120:
                    values.add(str(value))
            if top.get("target_end_date"):
                values.add(str(top.get("target_end_date")).strip())
        else:
            try:
                value = int(float(top))
                if 1 <= value <= 120:
                    values.add(str(value))
            except Exception:
                pass
        for row in _current_diagnostics(result):
            role = str(row.get("role") or "").strip().lower()
            if role not in {"strategic_horizon", "horizon_reconciliation", "temporal_context"} and not row.get("target_end_date"):
                continue
            for key in ("explicit_months", "strategic_horizon_months", "horizon_months", "months"):
                try:
                    value = int(float(row.get(key)))
                except Exception:
                    continue
                if 1 <= value <= 120:
                    values.add(str(value))
            if row.get("target_end_date"):
                values.add(str(row.get("target_end_date")).strip())
        # v62.13.9.4.15.1 — l'horizon du BRIEF fait autorité, en jours comme
        # en mois : « ▌ Horizon : 30 jours » est le contrat de planification
        # posé par l'utilisateur, pas une cible de l'agent. Le run réel du
        # 02/09/2026 19:53 réécrivait ce bandeau « un calendrier à arbitrer »
        # parce que seul un horizon en mois était reconnu.
        _brief62151 = str(((result or {}).get("inputs") or {}).get("brief") or "")
        for m in _HORIZON_BANNER_RE.finditer(_brief62151):
            values.add(m.group("n"))
    except Exception:
        return set()
    return values


_HORIZON_BANNER_RE = re.compile(
    r"(?im)^\W*Horizon\s*:\s*(?P<n>\d{1,3})\s*(?:jours?|mois|semaines?|ans?|days?|months?|weeks?|years?)\b")


def _v6213943_generic_action_quantity(text: str, result: Mapping[str, Any] | None = None) -> bool:
    value = str(text or "")
    if _V6213943_ACTION_INTENT_RE.search(_mask_non_quantity_codes(value)):
        return True
    return bool(_EQ.unsupported_quantity(
        value, reference_year=_v6213944_reference_year(result),
        authoritative_values=_v6213945_authoritative_values(result)))


def _v6213943_contract(text: str) -> str:
    out = text
    out = re.sub(r"\bde\s+des\b", "des", out, flags=re.I)
    out = re.sub(r"\bde\s+les\b", "des", out, flags=re.I)
    out = re.sub(r"\bde\s+une\b", "d’une", out, flags=re.I)
    out = re.sub(r"\bde\s+un\b", "d’un", out, flags=re.I)
    out = re.sub(r"\bà\s+les\b", "aux", out, flags=re.I)
    out = re.sub(r"\bà\s+le\b", "au", out, flags=re.I)
    return re.sub(r"\s{2,}", " ", out).strip()


def _v6213943_count_rewrite(text: str, lang: str) -> tuple[str, bool]:
    """« N <nom> » → « des <nom> » pour TOUT nom qui n'est pas une unité ; marqueur unique en fin."""
    marked = False

    def _sub(m: re.Match[str]) -> str:
        nonlocal marked
        noun = m.group("noun")
        if _V6213943_UNIT_WORD_RE.match(noun):
            return m.group(0)
        marked = True
        adj = m.group("adj") or ""
        num = m.group("num").replace(" ", "")
        if re.fullmatch(r"1(?:[.,]0+)?", num):
            article = "one" if lang.startswith("en") else "un"
        else:
            article = "some" if lang.startswith("en") else "des"
        return f"{article} {adj}{noun}"

    out = _V6213943_COUNT_RE.sub(_sub, text)
    if marked:
        mark = _V6213943_MARK_EN if lang.startswith("en") else _V6213943_MARK_FR
        out = out.replace(mark, "")
        out = re.sub(r"\s*—\s*volume (?:à valider|to validate)", "", out, flags=re.I)
        out = out.rstrip()
        tail = ""
        if out and out[-1] in ".!?":
            tail, out = out[-1], out[:-1].rstrip()
        out = out + mark + tail
    return out, marked


def _v6213943_rewrite_sentence(sentence: str, result: Mapping[str, Any], *, lang: str = "fr", force: bool = False) -> str | None:
    """Réécrit une phrase retenue. Renvoie None si l'invariant de sortie ne peut pas être tenu."""
    text = str(sentence or "").strip()
    if not text:
        return text
    if _V6213942_ALREADY_QUALIFIED_RE.search(text) and not [
        t for t in _v6213943_residual_cardinals(text) if t.lower() not in ("un", "une")
    ]:  # v62.13.9.4.5 — « un/une » de la qualification produit ne rouvre pas la ligne
        return text
    if not force and not _should_withhold_line(text, result or {}) and not _v6213943_generic_action_quantity(text):
        return text
    out = re.sub(
        r"(?P<subject>\b[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9 /'’._-]{1,55}?)\s*"
        r"(?:>=|<=|>|<|≥|≤|=)\s*[+−-]?\d+(?:[.,]\d+)?\s*"
        r"(?:%|pts?|points?|M€|k€|€|£|\$)?(?=\s|$)",
        lambda m: m.group("subject").rstrip() + (" to size" if lang.startswith("en") else " à dimensionner"),
        text, flags=re.I,
    )
    out = _EQ.rewrite_quantities(out, lang)
    if _v6213943_residual_cardinals(out) or _should_withhold_line(out, result or {}):
        return None
    return out


def _v6213943_strip_cardinals(text: str, lang: str) -> str:
    """Mode titre : réécriture générique puis, en dernier recours, retrait des cardinaux résiduels — jamais vide."""
    out = _EQ.rewrite_quantities(str(text or ""), lang)
    if _EQ.residual_cardinals(out):
        out = _EQ.strip_residual_cardinals(out)
    return out or text


def _v6213943_rewrite_text(text: str, result: Mapping[str, Any], lang: str = "fr", *, is_heading: bool = False, force: bool = True, hits: Any = None) -> str | None:
    """Réécriture phrase par phrase. None = rien ne peut revenir sur la surface principale.

    Un titre/heading n'est jamais retiré ni remplacé par une formule générique :
    en dernier recours ses cardinaux sont retirés, le sujet est conservé.
    """
    value = str(text or "")
    if not value.strip():
        return value
    if is_heading:
        out = _v6213943_rewrite_sentence(value.strip(), result, lang=lang, force=True)
        if out is None or _v6213943_residual_cardinals(out):
            out = _v6213943_strip_cardinals(value.strip(), lang)
        return out
    pieces = _V6213942_SENTENCE_SPLIT_RE.split(value.strip())
    try:
        from utils.board_scrutiny_guard import find_unsupported_executive_numeric_lines as _guard
    except Exception:  # pragma: no cover
        _guard = None
    faulty: list[bool] = []
    for piece in pieces:
        bad = bool(_v6213943_residual_cardinals(piece)) and (
            _should_withhold_line(piece, result or {})
            or _v6213943_generic_action_quantity(piece)
            or (_guard is not None and bool(_guard(piece, lang=lang, numeric_support_claims=[])))
        )
        faulty.append(bad)
    if force and not any(faulty):
        faulty = [bool(_v6213943_residual_cardinals(piece)) for piece in pieces]
    kept: list[str] = []
    for piece, bad in zip(pieces, faulty):
        if not bad:
            kept.append(piece)
            continue
        rewritten = _v6213943_rewrite_sentence(piece, result, lang=lang, force=True)
        if rewritten is None:
            continue
        kept.append(rewritten)
    out = " ".join(p for p in kept if p).strip()
    if not out:
        return None
    if _v6213943_residual_cardinals(out):
        return None
    return out


def _v6213943_is_heading_paragraph(paragraph: Any) -> bool:
    try:
        name = str(paragraph.style.name or "")
    except Exception:
        return False
    return bool(re.match(r"(?:Heading|Titre|Title|Subtitle|Sous-titre)", name, re.I))


def _v6213943_is_title_shape(slide: Any, shape: Any) -> bool:
    try:
        title = slide.shapes.title
        if title is not None and shape is title:
            return True
    except Exception:
        pass
    try:
        if shape.is_placeholder:
            kind = str(shape.placeholder_format.type or "")
            return bool(re.search(r"TITLE|SUBTITLE", kind, re.I))
    except Exception:
        pass
    return False


def _v6213942_is_annex_heading(text: str) -> bool:
    return bool(_V6213942_ANNEX_HEADING_RE.match(_norm_space(text)))


def _v6213942_is_extractability_surface(text: str) -> bool:
    """OCR tri-state inventory is observability, never an executive target."""
    lines = [_norm_space(line) for line in str(text or "").splitlines() if _norm_space(line)]
    if not lines:
        return False
    allowed = re.compile(
        r"^(?:Texte financier extrait|Partiellement extractible|OCR requis|"
        r"Financial text extracted|Partially extractable|OCR required)\s*[:—-]",
        re.I,
    )
    return all(allowed.match(line) for line in lines)


def _v6213942_parse_scenario(text: str) -> dict[str, str] | None:
    value = _norm_space(text)
    match = re.match(
        r"^SCN-(?P<sid>(?:V62139-)?[A-Z0-9_-]+)\s*(?:[·.]|[—–-])\s*(?P<payload>.*)$",
        value, re.I,
    )
    if not match:
        return None
    sid = match.group("sid")
    payload = match.group("payload").strip()
    role = ""
    original = payload
    sid_role = sid.upper().replace("V62139-", "")
    if sid_role in {"CEO", "DG", "DIRECTION_GENERALE", "DIRECTION-GENERALE"}:
        role = "ceo"
    else:
        role_match = re.match(
            r"(?P<role>(?:R\s*&\s*D|CEO|DG|DIRECTION(?:\s+|_)G[ÉE]N[ÉE]RALE|[A-Za-z_À-ÿ ]{2,40}))"
            r"\s*(?:[—-]|:)\s*(?P<text>.*)$", payload, re.I,
        )
        if role_match:
            candidate = _norm_space(role_match.group("role"))
            if candidate.casefold().startswith("conclusion de la direction"):
                role = "ceo"
            else:
                role = candidate.casefold()
                original = role_match.group("text").strip()
    original = original.lstrip("-• ")
    original = re.sub(
        r"\[(?:NON\s+SOURC[ÉE]|UNSOURCED|AI\s*ESTIM[^\]]*|ESTIM[^\]]*)\]",
        "", original, flags=re.I,
    )
    return {"id": sid, "role": role, "text": _norm_space(original)}


def _v6213942_select_restorations(entries: list[dict[str, str]], result: Mapping[str, Any]) -> tuple[str, str, str]:
    rd_candidates: list[tuple[int, int, str]] = []
    ceo_candidates: list[tuple[int, int, str]] = []
    dates: list[str] = []
    for entry in entries:
        text = entry.get("text", "")
        role = entry.get("role", "")
        low = text.casefold()
        if re.search(r"\br\s*&\s*d\b|recherche.{0,35}d[ée]veloppement", text, re.I):
            # v62.13.9.4.5 — la restauration remonte des contenus *qualitatifs* :
            # une ligne à cardinaux résiduels (tableau chiffré retenu au run courant)
            # n'est jamais candidate, sinon elle évince la phrase qualitative puis
            # se réécrit en vide et le fait R&D disparaît du corps.
            if not _v6213943_residual_cardinals(text):
                rd_candidates.append((0 if "non sourc" in low else 1, -len(text), text))
        if role in {"ceo", "dg", "direction_generale", "direction générale", "direction generale"} or (
            "impose une action" in low or
            ("conclusion" in low and re.search(r"direction\s+g[ée]n[ée]rale|directeur\s+g[ée]n[ée]ral|\bceo\b|\bdg\b", low))
        ):
            ceo_candidates.append((1 if role else 0, len(text), text))
        if re.search(r"date\s+de\s+fin\s+cible\s*:\s*20\d{2}-\d{2}-\d{2}", text, re.I):
            dates.append(text)
    rd = max(rd_candidates, default=(0, 0, ""))[2]
    ceo = max(ceo_candidates, default=(0, 0, ""))[2]
    date_line = dates[-1] if dates else ""
    if not date_line:
        _months, contract_dates = _planning_contract_values(result)
        if contract_dates:
            date_line = f"Date de fin cible : {sorted(contract_dates)[-1]}"
    return rd, ceo, date_line

def _registered_headcount_range_line(line: str, result: Mapping[str, Any]) -> bool:
    """A closed Sirene/INSEE band is registry metadata, never a target."""
    return _v6213942_is_closed_headcount_descriptor(_norm_space(line))



def _cross_metric_collision(line: str, result: Mapping[str, Any]) -> bool:
    family = _metric_family(line)
    if not family:
        return False
    mapping = _claim_amount_metric_map(result)
    for n in _numbers_in(line):
        families = mapping.get(n)
        if families and family not in families:
            return True
    return False


# NB : le « | » est EXCLU des séparateurs. C'est le séparateur de cellules
# des rangées de tableau, qui disposent de leur propre jugement cellule à
# cellule ; le traiter comme une proposition produisait des réécritures
# partielles de rangées (régression relevée sur deux campagnes terrain).
_CLAUSE_SPLIT_RE = re.compile(
    r"(\s*;\s*|\s+et\s+|\s+and\s+)")


_DANGLING_CONNECTOR_RE = re.compile(
    r"\s+(?:et|ou|and|or|avec|with|puis|then|ni|nor|mais|but|ainsi\s+que|as\s+well\s+as|de|du|des|d['’]|à|au|aux|"
    r"pour|for|en|in|sur|on|dans|par|by|vers|sous|entre|between|comme|like|que|qu['’]|qui|dont|où|of|to|the|le|la|les|l['’]|"
    r"un|une|a|an)\s*[,;:—–-]*\s*$", re.I)


def _strip_dangling_connector(text: str) -> str:
    """v62.13.9.4.25 — retire les connecteurs orphelins en fin de phrase
    (« … experte et », « … via »), itérativement, sans toucher au reste."""
    out = str(text or "").rstrip()
    prev = None
    while prev != out:
        prev = out
        out = _DANGLING_CONNECTOR_RE.sub("", out).rstrip(" ,;:—–-")
    return out


_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-Ÿ«(\d•\-])")


def _rule_local_rewrite(text: str, lang: str, result, support, rule, reserve: str) -> str | None:
    """v62.13.9.4.25 — LOCALITÉ PAR PHRASE pour les règles de tendance de CA et
    de croissance de marché (contre-audit v24, §2 : la conclusion de synthèse
    « se réduit à une réserve générique sur la dynamique de marché »). La
    réserve remplace la PHRASE fautive — le chiffre sort, pas le paragraphe ;
    les autres phrases restent et passent au jugement général de la ligne.
    None si le paragraphe n'a qu'une phrase (l'appelant garde son comportement)."""
    sents = [s for s in _SENT_SPLIT_RE.split(str(text or "")) if s.strip()]
    if len(sents) < 2:
        return None

    def _rewrite(s: str, verdict) -> str | None:
        rep = _clause_local_rewrite(s, lang, result, verdict=verdict)
        if rep is None:
            rep = _qualitative_replacement(s, lang, result)
        if rep is None:
            rep = _sentence_preserving_rewrite(s, lang)
        return rep

    out: list[str] = []
    for s in sents:
        sn = _norm_space(s)
        if rule(sn, result):
            rep = _rewrite(s, lambda c: bool(rule(_norm_space(c), result) or _should_withhold_line(_norm_space(c), result)))
            out.append(rep if rep else reserve)
            continue
        from utils.board_scrutiny_guard import find_unsupported_executive_numeric_lines as _fu62425
        hits = _fu62425(
            sn, lang=lang, numeric_support_claims=support,
            authoritative_horizon_values=_QL.build_authority_items(result))
        if hits or _should_withhold_line(sn, result):
            rep = _rewrite(s, None)
            if rep:
                out.append(rep)
        else:
            out.append(s)
    rebuilt = _norm_space(" ".join(x for x in out if x))
    return rebuilt or None


def _clause_local_rewrite(line: str, lang: str, result, verdict=None) -> str | None:
    """v62.13.9.4.12 — LOCALITÉ PAR MONTANT.

    Une phrase peut porter un fait et une cible : « Revenue was £24m in
    FY2025; the 2027 target margin is 12% ». La réécriture s'appliquait à la
    LIGNE ENTIÈRE, donc la cible partait avec le fait — le contre-audit du
    31/08/2026 l'a mesuré (3 phrases mixtes sur 3 perdant leur fait
    historique). C'est un faux rouge, et un faux rouge sur un fait daté et
    sourcé est un P0.

    On découpe la ligne en propositions, on ne réécrit que celles qui portent
    une grandeur non prouvée, et on conserve les autres verbatim. Renvoie
    None si le découpage n'apporte rien (une seule proposition, ou toutes
    fautives) : l'appelant retombe alors sur le comportement de ligne.
    """
    text = str(line or "")
    parts = _CLAUSE_SPLIT_RE.split(text)
    if len(parts) < 3:
        return None
    clauses = parts[0::2]
    seps = parts[1::2]
    if len([c for c in clauses if c.strip()]) < 2:
        return None

    # v62.13.9.4.12 — chaque étage juge avec SON critère. Sans ce paramètre,
    # une proposition conservée selon le juge de la réparation sémantique
    # était re-signalée par l'audit du guard, laissant un résidu après
    # réparation.
    _judge = verdict or (lambda c: _should_withhold_line(c, result))
    verdicts = [bool(c.strip()) and bool(_judge(c)) for c in clauses]
    if not any(verdicts) or all(verdicts):
        return None                      # rien à isoler, ou tout est fautif

    out = []
    for i, clause in enumerate(clauses):
        if verdicts[i]:
            rep = _qualitative_replacement(clause, lang, result)
            out.append(rep if rep else "")
        else:
            out.append(clause)
    rebuilt = ""
    for i, clause in enumerate(out):
        rebuilt += clause
        if i < len(seps):
            rebuilt += seps[i] if clause.strip() else ""
    rebuilt = _norm_space(rebuilt).strip(" ;,")
    # v62.13.9.4.25 — contre-audit v24 (§2) : la proposition supprimée laissait
    # son connecteur (« … acquisition organique — volume à valider et »). Un
    # connecteur de coordination ou une préposition en fin de phrase est retiré.
    rebuilt = _strip_dangling_connector(rebuilt)
    if not rebuilt:
        return None
    # v62.13.9.4.17 — contre-audit point 8 : une réécriture de clause qui ne
    # garde qu'un lambeau (« Investissement 4-6h/sem en animation LinkedIn et
    # prospection » → « prospection ») n'est pas une réécriture, c'est une
    # perte. Résidu < 40 % des mots ou < 3 mots → on rend la main.
    _w_in = len(_norm_space(line).split())
    _w_out = len(rebuilt.split())
    if _w_out < 3 or (_w_in >= 5 and _w_out < 0.4 * _w_in):
        return None
    # v62.13.9.4.12 — AUTO-VÉRIFICATION. Recomposer des propositions peut
    # produire une phrase hybride encore fautive (« … free cash flow of a
    # budget to size … still leaves net debt »). Si le juge de l'étage
    # signale toujours la ligne reconstruite, la réécriture locale n'a rien
    # apporté : on rend la main pour un remplacement de ligne entier.
    try:
        if _judge(rebuilt):
            return None
    except Exception:
        return None
    return rebuilt


def _qualitative_line_from_section62434(result, slide_index, lang: str = "fr"):
    """v62.13.9.4.34 (lot 2) — une phrase qualitative issue des sorties, sans chiffre
    et sans message de contrôle ; None si rien de tel n'existe (la case reste vide)."""
    try:
        import re as _re
        outs = (result or {}).get("outputs") if isinstance(result, dict) else None
        if not isinstance(outs, dict):
            return None
        _prudence434 = _re.compile(
            r"(?i)comparaison\s+directe|m[êe]me\s+p[ée]riode|nature\s+de\s+preuve|p[ée]rim[èe]tre\s+et\s+la\s+m[êe]me|"
            r"prudence|avertissement|m[ée]thodolog|rappel\s*:|à\s+v[ée]rifier\s+avant|non\s+[ée]tabli|"
            r"direct\s+comparison|same\s+period|epistemic|methodolog|caution|disclaimer|not\s+established")
        # les rôles métier d'abord : la matière vient de l'analyse, pas des blocs de prudence
        _order434 = ("strategie", "commercial", "marketing", "supply_chain", "finance", "rh", "juridique")
        _items434 = ([(k, outs.get(k)) for k in _order434 if isinstance(outs.get(k), str)]
                     + [(k, v) for k, v in outs.items() if k not in _order434])
        for _role, _txt in _items434:
            if not isinstance(_txt, str):
                continue
            for b in _re.findall(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+(.+)$", _txt):
                b = _re.sub(r"\s+", " ", _re.sub(r"\*\*|__", "", b)).strip(" -*•\t|")
                if not (28 <= len(b) <= 120):
                    continue
                if _re.search(r"\d", b) or "⟨" in b or "\u2063" in b:
                    continue
                if _GENERIC_FALLBACK_RE.search(_norm_space(b)) or _prudence434.search(b):
                    continue
                try:
                    from utils.analysis_objects import _is_product_marker as _ipm434, _is_template_instruction as _iti434
                    if _ipm434(b) or _iti434(b):
                        continue
                except Exception:
                    pass
                return b
    except Exception:
        return None
    return None


def _qualitative_replacement(line: str, lang: str = "fr", result: Mapping[str, Any] | None = None, *, is_heading: bool = False) -> str | None:
    """Réécriture d'une ligne retenue. None = la ligne ne revient pas sur la surface principale.

    Seule qualification fixe conservée : la spécification produit (contrat v62.13.6),
    formule générique de produit, jamais un texte de dossier.
    """
    # v62.13.9.4.7 — réécritures monolingues : la langue de réécriture est
    # celle de LA LIGNE, jamais celle du run ; les dix sorties du contrat
    # (rewrites_monolingual) sont reproduites à l'identique en priorité.
    from utils.monolingual_rewriter import canonical_rewrite as _mono_canon
    from utils.monolingual_rewriter import detect_line_lang as _mono_lang
    _canon62147 = _mono_canon(line)
    if _canon62147 is not None:
        return _canon62147
    lang = _mono_lang(line)
    # v62.13.9.4.16 — contre-audit P1-09 : le repli « cahier des charges
    # produit » partait sur « heures », « h », « capacité », « productivité »
    # — des mots de n'importe quel dossier — et remplaçait des arbitrages de
    # temps d'un dossier de conseil par un conseil d'achat d'équipement. Il ne
    # s'applique qu'à un vrai attribut de PRODUIT (autonomie/batterie/kWh/
    # voltage/recharge/électrique) ET dans un contexte d'engagement produit
    # (achat, lancement, gamme, équipement). Sinon, la ligne suit la
    # réécriture qualitative générale, qui garde la phrase et sort le chiffre.
    if (_PRODUCT_ATTRIBUTE_STRICT.search(line) and _PRODUCT_CONTEXT.search(line)
            and not is_heading):
        return (
            "Qualifier le cahier des charges produit, l’autonomie, le coût total et le marché avant engagement."
            if lang.startswith("fr") else
            "Qualify the product specification, autonomy, total cost and market before commitment."
        )
    rewritten = _v6213943_rewrite_text(line, result or {}, lang, is_heading=is_heading, force=True)
    # v62.13.9.4.5 — contrat de sortie : si aucune règle de réécriture ne
    # s'applique (ex. cible portée par une tranche « 200–249 »), le texte
    # ressortirait inchangé et la retenue serait silencieusement perdue dans
    # les octets finaux. Une ligne retenue non réécrite ne revient pas sur la
    # surface principale : None ⇒ annexe (DOCX) ou vidage dédupliqué (PPTX).
    if rewritten is not None and _norm_space(rewritten) == _norm_space(line):
        return None
    return rewritten


def _brief_targets48(result) -> list:
    """v62.13.9.4.48 — cibles du brief (données pour le second juge ; liste vide sans brief)."""
    try:
        from utils.declared_quantities import brief_declared_targets as _bdt48
        return _bdt48(result)
    except Exception:
        return []


def _second_judge_flags62415(text: str, result) -> bool:
    """Verdict du juge indépendant (utils.independent_content_judge), avec
    les mêmes déclarations A1 que l'oracle. Fail-open sur l'import : sans
    juge, l'exemption reste celle du cycle précédent."""
    try:
        from utils.independent_content_judge import judge_unit as _j2
        try:
            from utils.declared_quantities import declared_index
            _decl = declared_index(result) or None
        except Exception:
            _decl = None
        return bool(_j2(text, (result or {}).get("numeric_support_claims")
                        or (result or {}).get("canonical_claims") or None,
                        declared=_decl, brief=_brief_targets48(result)))
    except Exception:
        return False


# v62.13.9.4.48 — les non-quantités (nomenclature, repères de période, noms à trait d'union,
# identifiants étiquetés, jetons d'identifiant, lignes techniques) sont définies une seule fois,
# dans utils/non_quantity.py. Ce mainteneur laissait la nomenclature « au classement », qui ne
# l'exemptait pas : « Scope 3 … » était retenu (corpus de frontières du 27/09/2026).
from utils.non_quantity import mask_non_quantities as _mask_nq48, ALL as _NQ_ALL48


def _mask_non_quantities46(text: str) -> str:
    """Efface ce qui n'est pas une quantité, pour le seul test « reste-t-il une quantité ? » ;
    jamais un texte à classer (l'année d'une cible est son cadre futur)."""
    t = _mask_nq48(str(text or ""), kinds=_NQ_ALL48)
    return _FYE_RE47.sub(lambda m: " " * len(m.group(0)), t)   # la clôture d'exercice est une métadonnée


def _should_withhold_line(line: str, result: Mapping[str, Any]) -> bool:
    """Decide at the semantic layer, before any DOCX/PPTX byte repair."""
    text = _analysis_text(line)
    # v62.13.9.4.3 — une numérotation de titre/liste n'est pas une quantité ; une ligne
    # déjà qualifiée sans cardinal résiduel n'est jamais re-retenue (idempotence).
    # v62.13.9.4.15 — les titres markdown (« ## 1. », « ### 2.1 ») et la
    # numérotation à points (« 2.1 Taille du marché ») rejoignent la règle :
    # le rejeu du run réel du 02/09/2026 retenait tous les titres numérotés.
    text = re.sub(r"^\s*(?:#{1,6}\s*)?(?:[-*•▌✓]+\s*)?(?:\d+(?:\.\d+)*[.)]\s+)+", "", text)
    # « 2.1 Taille » est un titre ; « 24.5 M€ » ne l'est pas — exige un MOT.
    text = re.sub(r"^\s*(?:#{1,6}\s*)?\d+(?:\.\d+)+\s+(?=[\*«]|[A-ZÀ-Ÿ][A-Za-zÀ-ÿ'’-]{2,})", "", text)
    # v62.13.9.4.50 — une CIBLE DU BRIEF reprise par un agent (même valeur, même exercice, langage de cible, y compris
    # en reprise elliptique « objectif de 700 M$ en FY2028 ») est la cible du dirigeant : elle est dite une fois dans la
    # mention des cibles du brief et ne rend pas la ligne douteuse. Seuls les AUTRES nombres de la ligne sont jugés.
    try:
        _bt50 = _brief_targets48(result)
        if _bt50:
            from utils.declared_quantities import brief_target_hit as _bth50, _NUM_RE as _NUM50
            _masked50 = text
            for _m50 in list(_NUM50.finditer(text)):
                _raw50 = text[_m50.start():min(len(text), _m50.end() + 6)]
                if _bth50(text, _raw50, _bt50):
                    _masked50 = _masked50[:_m50.start()] + " " * (_m50.end() - _m50.start()) + _masked50[_m50.end():]
            text = _masked50
    except Exception:
        pass
    if _V6213942_ALREADY_QUALIFIED_RE.search(text) and not [
        t for t in _v6213943_residual_cardinals(text) if t.lower() not in ("un", "une")
    ]:  # v62.13.9.4.5 — « un/une » de la qualification produit ne rouvre pas la ligne
        return False
    # v62.13.9.4.6 — autorité temporelle 13.9.2 d'abord (contrat exempt si
    # et seulement si ses valeurs sont autorisées/datées), puis protection
    # des faits accomplis (P1-03), puis socle deny-by-default typé : ces
    # décisions priment sur les règles lexicales héritées.
    if _date_only_numeric_line(text):
        return False
    # v62.13.9.4.47 — une ligne dont les seuls nombres sont des identifiants, des dates,
    # des noms ou des repères techniques ne porte aucune quantité à retenir. Le masque ne
    # sert qu'à ce test : le classement lit le texte entier, parce que l'année d'une cible
    # (« EBITDA > 0 en 2027 ») est son cadre futur ; un cardinal en toutes lettres
    # (« a new centre ») est vu par le test de qualification acquise qui précède.
    _masked46 = _mask_non_quantities46(text)
    if re.search(r"\d", text) and not re.search(r"\d", _masked46) and not [
            t for t in _v6213943_residual_cardinals(_masked46) if t.lower() not in ("un", "une")]:
        return False
    # v62.13.9.4.18 — benchmark étiqueté (source nommée + étiquette) : jamais retenu.
    # v62.13.9.4.19.6 — réserve épistémique (chiffre cité pour être récusé) : jamais retenue.
    try:
        from utils.quantity_ledger import is_labelled_benchmark_line as _ilbl62418, is_epistemic_caveat_line as _iecl62419
        if _ilbl62418(line or "") or _iecl62419(line or ""):
            return False
    except Exception:
        pass
    # v62.13.9.4.15.1 — le BANDEAU D'HORIZON (« ▌ Horizon : 30 jours ») est le
    # contrat de planification du run, reproduit tel quel dans le CR ; il
    # n'est jamais une cible. Vérifié contre l'horizon du brief.
    if _HORIZON_BANNER_RE.match(line or "") and re.fullmatch(
            r"\W*Horizon\s*:\s*\+?\s*\d{1,3}\s*(?:jours?|mois|semaines?|ans?|days?|months?|weeks?|years?)\s*\.?\s*",
            line or "", flags=re.I):
        _n62151 = _HORIZON_BANNER_RE.match(line).group("n")
        if _n62151 in _v6213945_authoritative_values(result):
            return False
    # v62.13.9.4.13 — une affirmation d'extinction juridique contredite par
    # le registre est retenue quoi qu'il arrive : elle ne peut pas piloter un
    # livrable. Placé AVANT les exemptions — ce n'est pas une question de
    # grandeur, mais d'autorité de source.
    if _contradicts_registry62413(text, result):
        return True
    _lang62146 = str((result or {}).get("language") or (result or {}).get("lang") or "fr")
    _ry62146 = _v6213944_reference_year(result)
    _ctx62146 = {"current_year": _ry62146} if _ry62146 else {}
    # v62.13.9.4.11 (A1) — le contexte transmis au ledger était un
    # mini-contexte (année de référence) : les grandeurs déclarées par les
    # agents n'y arrivaient jamais, si bien que l'oracle bloquait en sortie
    # ce que la réparation n'avait pas corrigé. On propage la déclaration.
    _dq62411 = (result or {}).get("declared_quantities")
    if _dq62411:
        _ctx62146 = dict(_ctx62146)
        _ctx62146["declared_quantities"] = _dq62411
    _ctx62146 = _ctx62146 or None
    _lv62146 = _QL.classify_line(
        text, _lang62146,
        # v62.13.9.4.12.7 — les faits de REGISTRE (Pappers, sources
        # officielles) comptent parmi les preuves : sans eux, « 0 salariés »
        # restait retenu et bloquait l'export du run réel.
        claims=(list((result or {}).get("numeric_support_claims")
                     or (result or {}).get("canonical_claims") or [])
                + _registry_support62427(result)) or None,
        authority_values=_QL.build_authority_items(result),
        context=_ctx62146)
    if _planning_horizon_line(text, result) and not _lv62146.untyped:
        # v62.13.9.4.15 — PARITÉ AVEC L'ORACLE : l'exemption de contrat de
        # planification ne prime pas sur le second juge. Le run réel du
        # 02/09/2026 15:04 : « Structurer 3 offres packagées (… 6 mois, 10
        # jours) » était exempté ici comme ligne d'horizon, puis bloqué à
        # l'export par le juge indépendant (grandeur projetée non
        # certifiée). Ce que l'oracle refuse en sortie doit être retenu en
        # amont — sinon le document est indistribuable au lieu d'être réparé.
        if not _second_judge_flags62415(text, result):
            return False  # contrat d'autorité aux valeurs conformes uniquement
    # v62.13.9.4.12.6 — la DÉCLARATION PRIME sur la protection de fait.
    # Le run du 02/09/2026 a bloqué l'export sur deux lignes dont les
    # grandeurs avaient été déclarées prospectives par les agents
    # (« 2 posts/semaine », « objectif 5+ », « 1 400-1 600 € visé ») : le
    # second juge les signalait, la réparation les laissait passer parce que
    # ``line_is_protected_fact`` coupait AVANT lui. Retenu sans réécriture =
    # blocage garanti à l'export.
    # Un agent qui déclare une cible en sait plus que l'heuristique de fait :
    # sa déclaration lève la protection, jamais l'inverse — l'asymétrie du
    # canal est préservée.
    _declared_target62426 = False
    if _dq62411:
        try:
            from utils.declared_quantities import declared_index as _di62426
            _idx62426 = _di62426(result)
            _declared_target62426 = bool(
                _idx62426 and _idx62426.line_has_declared_target(text))
        except Exception:
            _declared_target62426 = False
    if (not _declared_target62426
            and _QL.line_is_protected_fact(text, _lang62146, context=_ctx62146)):
        # v62.13.9.4.15.3 — PARITÉ AVEC L'ORACLE, ici aussi. Le run réel du
        # 03/09/2026 08:24 : « hausse RECOMMANDÉE du TJM (cible 1 200–1 500
        # €/jour) … qu'en 2020–2022 » était typée fait accompli (la mention
        # d'une période passée levait la primauté du signal de cible), la
        # protection coupait avant le second juge, l'oracle bloquait en
        # sortie. Une « protection de fait » que le juge indépendant refuse
        # n'est pas une protection : elle garantit un document
        # indistribuable. Le second juge ne signale que des grandeurs
        # projetées ou déclarées ; un vrai fait accompli (« 1,390
        # basis point margin compression ») ne le déclenche pas.
        if not _second_judge_flags62415(text, result):
            return False
    if _lv62146.withhold:
        return True
    if any(r in ("evidence_row", "scenario_register_row", "financial_model_row")
           for r in _lv62146.reasons):
        return False  # sortie/registre du produit : hors surface exécutive
    # v62.13.9.4.9 — PARITÉ réparation ↔ oracle : le second juge (écrit hors
    # du guard) statue aussi à la couche de décision. Sans cela l'oracle
    # bloquerait en sortie ce que la réparation n'aurait pas corrigé — le
    # document deviendrait indistribuable au lieu d'être réparé. C'est la
    # même parité que celle exigée pour les rangées non certifiées.
    try:
        from utils.independent_content_judge import judge_unit as _j2
        # v62.13.9.4.11 (A1) — la réparation reçoit les mêmes déclarations que
        # l'oracle : ce que le second juge bloque en sortie doit être corrigé
        # en amont (parité établie au cycle 9.4.9).
        try:
            from utils.declared_quantities import declared_index
            _decl62411 = declared_index(result) or None
        except Exception:
            _decl62411 = None
        if _j2(text, (result or {}).get("numeric_support_claims")
               or (result or {}).get("canonical_claims") or None,
               declared=_decl62411, brief=_brief_targets48(result)):
            return True
    except Exception:
        pass
    if _lv62146.typed and not _lv62146.untyped:
        return False  # v62.13.9.4.6 — ligne intégralement typée : descriptive
    # v62.13.9.4.4 — les règles héritées ne voient plus les nombres exemptés (dates, normes,
    # numérotations descriptives, identifiants, tranches, contrats de planification).
    numeric_text = _mask_non_quantity_codes(_EQ.mask_exempt(text))
    # v62.13.9.4.4 — porte étroite : mot d'objectif explicite + date complète (jamais
    # année nue ni trimestre) pour que la règle 13.9.2 « seule la date d'autorité est
    # exempte » puisse trancher, sans re-capturer les faits datés (T4 2026, tableaux).
    _target_dated = bool(
        re.search(r"\b(?:objectifs?|cibles?|targets?|goals?|ambitions?|kpis?|milestones?|jalons?)\b", text, re.I)
        and re.search(r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b|\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b", text)
    )
    if not text or not (_AMOUNT_RE.search(numeric_text) or _EQ.residual_cardinals(text, action=True) or _target_dated):
        return False
    # v62.13.9.4.5 — un verbe statif au présent (« compte / possède / includes ») décrit
    # l'état, pas un engagement : la ligne est un fait, sauf cible datée/décision explicite.
    if (_EQ.is_stative_present_fact(text) and not _target_dated
            and not _EQ.TARGET_WORDS_RE.search(text) and not _EQ.DECISION_VERB_RE.search(text)):
        return False
    if _date_only_numeric_line(text):
        return False
    if _planning_horizon_line(text, result):
        return False
    if _registered_headcount_range_line(text, result):
        return False
    if _v6213942_is_completed_activity(text):
        return False
    if _v6213942_is_product_attribute(text):
        return False
    if _v6213943_generic_action_quantity(text, result):
        return True
    if _V6213942_NEW_TARGET_RE.search(text):
        return True
    if _ACTION_QUANTITY_RE.search(numeric_text):
        return True
    if _OPERATIONAL_DURATION_RE.search(text) and _DURATION_VALUE_RE.search(numeric_text):
        return True
    if _verified_fact_line(text, result) and not _cross_metric_collision(text, result):
        return False
    if (_FACT_MARKER.search(text) or _SOURCE_MARKER.search(text)) and _AMOUNT_RE.search(numeric_text):
        return True
    if _cross_metric_collision(text, result):
        return True
    if _TARGET_WORDS.search(text):
        return True
    if re.search(r"\b(?:20(?:27|28|29)|T[1-4]\s*20(?:27|28|29)|FY20(?:27|28|29))\b", text, re.I):
        if re.search(r"[€£$%]|\d\s*[-–]\s*\d", numeric_text):
            return True
    return False



# v62.13.9.4.21 — MODE STATUT (document de travail) : quand ``result`` porte
# ``_render_mode = "work"``, une ligne non étayée est conservée telle quelle
# et reçoit un tag de statut en fin de ligne, au lieu d'être réécrite. Les
# rendus dérivés (synthétique, deck) travaillent sur le texte sans tag et
# neutralisent comme avant. Les cas de MENSONGE (contradiction du registre,
# seuil social non prouvé) restent traités comme avant dans les deux modes.
def _has_declared_target_line(line: str, result, context: str = "") -> bool:
    """v62.13.9.4.48 — ADAPTATEUR vers le service unique « cible déclarée »
    (utils.declared_quantities.DeclaredQuantityIndex.declared_target_in). Ce chemin comparait
    la valeur nue jusqu'à la 9.4.46 (le « 40 » d'un nom de produit à trait d'union, 88 lignes d'un run réel), puis, en 9.4.47, un repli
    valeur + unité + année qui ne contrôlait ni la métrique ni la nature : une grandeur déclarée
    FAIT « marge brute 55 % » étiquetait « cible déclarée » une ligne de rétention à 55 % (corpus
    de frontières du 27/09/2026). Le repli est supprimé ; le contexte d'un bloc — titre de section,
    titre de phasage, en-tête de tableau — est transmis explicitement au service, qui y retrouve
    la métrique qu'une composante ne nomme pas. Aucune décision sur une valeur nue ici."""
    try:
        from utils.declared_quantities import declared_index as _di
        idx = _di({"declared_quantities": (result or {}).get("declared_quantities")})
        if not idx:
            return False
        return idx.declared_target_in(str(line or ""), context=str(context or "")) is not None
    except Exception:
        return False


def _sentence_preserving_rewrite(line: str, lang: str) -> str | None:
    """v62.13.9.4.22 — contre-audit v21 (§5.1) : dans la synthèse, une décision,
    un intitulé d'option ou une conclusion ne disparaissent plus parce qu'ils
    portaient un chiffre : la réécriture qualitative garde la phrase et sort le
    chiffre. Renvoie None si un chiffre subsiste (la marque de retrait reprend)."""
    try:
        from utils.editorial_quantity import (rewrite_quantities, mask_exempt,
                                              is_fully_dequantified_metric_line)
        out = rewrite_quantities(str(line or ""), lang)
    except Exception:
        return None
    if not out:
        return None
    # v62.13.9.4.36 — UNE LIGNE DE MÉTRIQUE ENTIÈREMENT VIDÉE NE DIT RIEN. Runs réels
    # du 17/09/2026 : « Adjusted operating margin a level to size → a level to size
    # (FY2025 vs FY2024) ». La doctrine des scénarios veut la ligne ENTIÈRE au
    # registre, pas une comparaison sans ses deux termes : on rend None, la marque de
    # retrait reprend la main.
    try:
        if is_fully_dequantified_metric_line(str(line or ""), out):
            return None
    except Exception:
        pass
    if _norm_space(out) == _norm_space(line):
        # rien réécrit : légitime seulement si tous les chiffres sont exemptés
        # par construction (« plan d'action à 90 jours ») — sinon ce n'est
        # pas une réécriture.
        try:
            if re.search(r"\d", mask_exempt(out)) or not re.search(r"\d", out):
                return None
        except Exception:
            return None
    # les chiffres restants ne comptent que s'ils ne sont pas exemptés par
    # construction (contrat de planification « plan d'action à 90 jours »,
    # dates, identifiants) : ceux-là ne sont pas des cibles.
    try:
        residual_digits = re.search(r"\d", mask_exempt(out))
    except Exception:
        residual_digits = re.search(r"\d", out)
    if residual_digits:
        return None
    # la phrase réécrite doit passer le typeur elle-même (« Open a new centre » :
    # « a » lu comme UN par le moteur anglais) — sinon la marque de retrait reprend.
    try:
        from utils.quantity_ledger import classify_line as _cl
        if _cl(out, lang).withhold:
            return None
    except Exception:
        pass
    return out



def _append_tag49(line: str, tag: str) -> str:
    """v62.13.9.4.49 — pose une étiquette en fin de ligne ; pour une rangée de tableau Markdown (« | … | »),
    l'étiquette va DANS la dernière cellule, avant la barre finale. Audit du 29/09/2026 : posée après la barre,
    elle devenait une cellule de plus, vide de contenu, signalée à part (sept cellules vides signalées dans le CR
    d'un run réel du 28/09)."""
    s = line.rstrip()
    # v62.13.9.4.50 — une ligne de séparation de tableau (« |---|:--:| ») n'est jamais étiquetée : l'étiquette la
    # transformait en rangée de contenu et le tableau retombait en paragraphes (contre-recette du 30/09, A05)
    if re.fullmatch(r"\s*\|?(?:\s*:?-{2,}:?\s*\|)+\s*:?-{0,}:?\s*\|?\s*", s):
        return s
    if s.lstrip().startswith("|") and s.endswith("|") and s.count("|") >= 3:
        return s[:-1].rstrip() + " " + tag + " |"
    return s + " " + tag


def _is_brief_echo49(line: str, result) -> bool:
    """v62.13.9.4.49 — une ligne qui reproduit le brief du dirigeant (son propre texte) n'est pas signalée ligne à
    ligne : la mention unique des cibles du brief (9.4.48, point 4) dit qu'il s'agit de déclarations non
    certifiées. Audit du 29/09/2026 : l'écho du brief portait six signalements dans le CR de la séance 2."""
    try:
        brief = str(((result or {}).get("inputs") or {}).get("brief") or "")
    except Exception:
        return False
    if not brief:
        return False
    def _n(s: str) -> str:
        s = re.sub(r"⟨[^⟩]*⟩", " ", str(s or ""))
        s = re.sub(r"^[\s>*•·—–\-|]+", "", s)
        # v62.13.9.4.50 — « 12 000 » et « 12000 » sont le même nombre (vrai CR du 30/09 : l'écho de la ligne
        # d'enveloppe du brief était signalé parce que l'agent avait ajouté l'espace des milliers)
        s = re.sub(r"(?<=\d)[\s\u202f\u00a0](?=\d{3}\b)", "", s)
        return re.sub(r"\s+", " ", s).strip(" .;:").lower()
    nl = _n(line)
    return len(nl) >= 12 and nl in _n(brief)


_PRODUCT_TABLE_HEADERS49 = (
    {"topic", "action", "owner", "deadline"}, {"sujet", "action", "porteur", "échéance"},
    {"date", "new", "carried"}, {"date", "nouvelles", "reprises"}, {"date", "nouvelles", "reconduites"},
    {"status", "fact", "value", "source"}, {"statut", "fait", "valeur", "source"},
)


def _is_product_table_header49(cells) -> bool:
    """v62.13.9.4.49 — tableaux écrits PAR LE PRODUIT (registre des actions, chronologie multi-séances, table
    de faits) : ils ne sont pas jugés comme du texte d'agent. Audit du 29/09/2026 : 78 rangées de ces tableaux
    étaient signalées dans le CR d'un run réel, jusqu'à la date du jour dans la chronologie."""
    names = {re.sub(r"[^\wéèêàç ]", "", str(c or "").replace("\u2063", "")).strip().lower() for c in cells}
    return any(h <= names for h in _PRODUCT_TABLE_HEADERS49)


def _amounts_contradict49(line: str, canonical: str) -> bool:
    """v62.13.9.4.49/50 — une ligne contredit un fait confirmé seulement si, POUR UNE MÊME NATURE de grandeur (montant,
    taux…) présente dans le fait, l'une de ses valeurs n'est couverte par aucune valeur du fait (tolérance d'arrondi
    du rattachement), et si la ligne parle du même exercice.

    Contre-recette du 30/09/2026 (A03) : « CA FY2025 : 620 M$, marge brute 55 % » sortait « contredit par la pièce :
    Chiffre d'affaires : 620 M$ » — les 55 % (une autre métrique) étaient opposés au seul fait du chiffre d'affaires ;
    une comparaison FY2024/FY2023 était opposée au chiffre FY2025. Audit du 29/09 : le nom du fichier et la page ne
    sont pas des valeurs (définition partagée des non-quantités)."""
    # 9.4.60 — contre-recette ChatGPT du 11/10/2026 (F59-05) : aucun « contredit » sans IDENTITÉ COMPARABLE (métrique,
    # nature, période, périmètre, échelle). Une évolution sur plusieurs exercices, un scénario, un seuil proposé, une
    # sensibilité ou une région ne sont pas réfutés par le réalisé groupe d'un exercice.
    import re as _re60
    _l60 = str(line or "")
    _fys60 = {y for y in _re60.findall(r"(?i)\bFY\s?(20\d{2}|\d{2})\b", _l60)} | set(_re60.findall(r"\b(20[12]\d)\b", _l60))
    _cfys60 = {y for y in _re60.findall(r"(?i)\bFY\s?(20\d{2}|\d{2})\b", str(canonical or ""))} | \
              set(_re60.findall(r"\b(20[12]\d)\b", str(canonical or "")))
    # une évolution sur plusieurs exercices n'est pas réfutée par le réalisé d'UN exercice ; elle reste comparable à un
    # fait qui décrit lui-même une évolution (« £2,461m→£2,420m, FY2026 vs FY2025 » : la baisse de 17 % est contredite)
    if len(_fys60) >= 2 and len(_cfys60) <= 1 and "→" not in str(canonical or ""):
        return False
    if _re60.search(r"(?i)\b(?:sc[ée]nario|seuil|sensibilit|hypoth[èe]se|cible|objectif|propos[ée]|choc|dilution|simul|"
                    r"projection|plafond|plancher|alerte|orange|si\s+(?:le|la|les|l')|scenario|threshold|sensitivity|target|"
                    r"assumption|shock|forecast)\w*", _l60):
        return False
    _seg60 = r"(?i)\b(?:asie[- ]pacifique|apac|asia[- ]pacific|eimea|emea|am[ée]riques?|americas?|r[ée]gion|zone|segment|gamme|specialist|multi[- ]use)\b"
    if _re60.search(_seg60, _l60) and not _re60.search(_seg60, str(canonical or "")):
        return False
    # « 103,793 k$ » dans un texte français : virgule anglaise de groupement des milliers, pas une décimale
    line = _re60.sub(r"(?<![\d,])(\d{1,3}),(\d{3})(?=\s*(?:k\s?\$|k\s?€|kUSD|kEUR|K\$))", r"\1\2", _l60)
    try:
        from utils.board_scrutiny_guard import _extract_numeric_components as _enc, _component_matches as _cm
        from utils.non_quantity import FILE_NAME_RE as _FNR
    except Exception:
        return False
    line = _FNR.sub(" ", str(line or ""))
    canonical = _FNR.sub(" ", str(canonical or ""))
    # 9.4.65 — contre-recette du 17/10 : « <poste> : <montant> € (<date de clôture>) » ou « <poste> : <n> M€ (<année>) » —
    # la période entre parenthèses était lue comme un MONTANT (l'année, voire son opposé à cause des parenthèses), et la
    # vraie valeur ignorée : toute ligne citant le bon chiffre était déclarée contredite. La période du fait sert à
    # comparer les exercices, jamais de montant.
    _per65 = " ".join(re.findall(r"\(([^()]*\b(?:19|20)\d{2}\b[^()]*)\)", canonical))
    canonical = re.sub(r"\((?:[^()]*\b(?:19|20)\d{2}\b[^()]*)\)", " ", canonical)
    # même exercice : si la ligne nomme des exercices et que celui du fait n'en fait pas partie, on ne compare pas
    _yr = lambda s: set(re.findall(r"(?i)\b(?:FY|CY|exercice\s+)?\s?((?:19|20)\d{2})\b", s))
    fy_fact, fy_line = _yr(canonical + " " + _per65), _yr(line)
    if fy_fact and fy_line and not (fy_fact & fy_line):
        return False
    ref = _enc(canonical)
    comps = _enc(line)
    if not comps or not ref:
        return False
    # Par nature de grandeur présente dans le fait : la ligne contredit le fait seulement si AUCUNE de ses valeurs de
    # cette nature ne le couvre. Une ligne qui cite le fait juste peut porter d'autres montants de la même nature pour
    # d'autres métriques (« marge brute 55,0 % du CA (341,3 M$ / 619,9 M$) ») : ce n'est pas une contradiction.
    # 9.4.57 — contre-recette ChatGPT du 10/10 (§5.3) : « 58,13 M$ » contre « 58,1 M$ », « 55,06 % » contre « 55,1 % » sont
    # le même chiffre à un autre arrondi ; « 79,1 M$ hors ajustement fiscal » est une AUTRE définition que le publié
    if re.search(r"(?i)\bhors\b|\bajust[ée]|\badjusted\b|\bexcluding\b|\bpro\s?forma\b|\bretrait[ée]|\bnormatif|"
                 r"\bsous-jacent|\bunderlying\b|\bcourant\b|\brécurrent", line):
        return False

    def _close57(c, r) -> bool:
        try:
            a, b = float(c.get("value")), float(r.get("value"))
        except Exception:
            return False
        if str(c.get("kind")) == "pct":
            return abs(a - b) <= 0.06
        return b != 0 and abs(a - b) <= 0.005 * abs(b)
    kinds = {str(r.get("kind")) for r in ref}
    for k in kinds:
        mine = [c for c in comps if str(c.get("kind")) == k]
        if mine and not any(_cm(c, r) or _close57(c, r) for c in mine for r in ref if str(r.get("kind")) == k):
            return True
    return False

def _canonical_display_values50(result) -> set:
    """v62.13.9.4.50 — valeurs affichées des faits confirmés (cartes clés du deck) : « $620m », « 619 985 k$ »…"""
    vals = set()
    for c in list((result or {}).get("numeric_support_claims") or []) + list((result or {}).get("canonical_claims") or []):
        if isinstance(c, Mapping):
            for k in ("display_value", "value"):
                v = _norm_space(str(c.get(k) or ""))
                if v:
                    vals.add(v)
    return vals


_PRESENTATION_WORDS50 = {
    "projection", "projections", "objectif", "objectifs", "cible", "cibles", "target", "targets", "scénario", "scenario",
    "scénarios", "scenarios", "option", "options", "hypothèse", "hypothèses", "assumption", "assumptions", "estimation",
    "estimate", "prévision", "prévisions", "forecast", "budget", "total", "synthèse", "summary", "risque", "risk",
    "action", "actions", "décision", "decision", "plan", "phase", "étape", "step", "marge", "margin", "chiffre",
    "revenue", "croissance", "growth", "engage", "engager", "finaliser", "finalize", "present", "présenter", "lancer",
    "launch", "déployer", "deploy", "valider", "validate", "recruter", "recruit", "piloter", "pilot", "mettre", "set",
    "émissions", "emissions", "intensité", "intensity", "taux", "rate", "indicateur", "indicator", "kpi",
}

def _status_mode(result) -> bool:
    """v62.13.9.4.49 — doctrine du 28/09/2026 : TOUS les documents sont en mode statut (le passage reste
    en place, étiqueté ; le rendu le signale). Le mode « synthesis » ne neutralise plus. Seul un appelant
    qui demande explicitement l'ancien comportement (``_render_mode = "legacy_neutralize"``, conservé pour
    les rejeux historiques) le retrouve."""
    try:
        return str((result or {}).get("_render_mode") or "") != "legacy_neutralize"
    except Exception:
        return True


_YEAR_COL_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_PROJ_CTX_RE = re.compile(r"(?i)pr[ée]visionnel|projection|projet[ée]|sc[ée]nario|simulation|budget|forecast|plan\s+(?:financier|d['’]affaires)|business\s+plan|trajectoire")


_CONSOLIDATION_CARD_RE = re.compile(
    r"^\s*(?:"
    # ligne historique du produit : « Comptes consolidés fournis : non — les chiffres hors faits
    # sourcés restent des hypothèses (jamais board-safe). » (glose du produit admise, pas une action)
    r"(?:Comptes consolidés(?: groupe)? fournis|Consolidated accounts provided)\s*(?::\s*(?:oui|non|yes|no|à confirmer|not established|non établis)"
    r"(?:\s*[—–-]\s*(?:les chiffres hors faits sourcés|figures outside sourced facts|chiffres|figures|hypoth[èe]ses?|assumptions?)[^\n]{0,160})?[^\n]{0,40})?"
    r"|(?:États financiers structurés détectés|Structured financial statements detected|Données de registre structurées détectées|Structured registry data detected)\s*:[^\n]*"
    r")\s*$", re.I)
_ACTION_SHAPE_RE = re.compile(
    r"(?i)\b(?:reconstituer|établir|produire|obtenir|collecter|demander|finaliser|préparer|auditer|réconcilier|consolider|"
    r"rebuild|produce|obtain|collect|request|finalise|finalize|prepare|audit|reconcile|consolidate)\b"
    r"|—\s*[A-ZÀ-Ÿ][^—·|]{1,60}\s*[·—|]\s*(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{4})"
    r"|\b(?:QUI|WHO|QUAND|WHEN|porteur|owner|échéance|deadline)\s*:")


def _is_product_consolidation_card(text: str) -> bool:
    """Vrai seulement pour une carte écrite par le produit — jamais pour une phrase
    d'action qui mentionne des comptes consolidés (v62.13.9.4.33, lot 1)."""
    t = _norm_space(text)
    if not t or _ACTION_SHAPE_RE.search(t):
        return False
    return bool(_CONSOLIDATION_CARD_RE.match(t))


_PHASE_LINE_RE = re.compile(
    r"^\s*[-•*]\s*(?P<period>(?:19|20)\d{2}(?:\s*\([TQSH]\d\)|\s+[TQSH]\d)?|[TQSH]\d\s*(?:19|20)\d{2}|"
    r"(?:janv|févr|mars|avr|mai|juin|juil|août|sept|oct|nov|déc)[a-zé.]*\s+(?:19|20)\d{2}|(?:phase|étape|vague|year|année)\s*\d)"
    r"\s*:\s*(?P<amount>[-+]?\d[\d\s\u00A0\u202F.,]*\s*(?:k€|m€|md€|€|k|m|%|k\$|m\$|\$|£)?)", re.I)


def _phasing_blocks(lines: list[str], result: Mapping[str, Any], lang: str) -> list[dict]:
    """v62.13.9.4.33 (lot 1) — UN PHASAGE SE GARDE ENTIER OU S'ÉCARTE ENTIER.
    Contre-audit du 12/09/2026 (run réel bf7167) : « - 2026 (T4) : 350 k€ (test &
    learn…) » disparaissait d'un phasage 350 + 900 + 750 = 2 000 k€ parce que la
    ligne ne portait aucun mot de la métrique déclarée, tandis que 900 et 750
    restaient — un scénario amputé sans que le reste soit réconcilié. Les
    composantes d'un montant déclaré héritent de sa déclaration : si une
    phase au moins est admise, toutes restent ; si aucune ne l'est, le phasage
    entier est retiré du corps et versé au registre."""
    blocks: list[dict] = []
    i, n = 0, len(lines)
    while i < n:
        if not _PHASE_LINE_RE.match(lines[i]):
            i += 1
            continue
        j = i
        while j < n and _PHASE_LINE_RE.match(lines[j]):
            j += 1
        rows = lines[i:j]
        if len(rows) >= 2:
            # v62.13.9.4.47 — les lignes d'un phasage (« 2026 (T4) : 350 ») ne nomment pas
            # leur grandeur : c'est le TITRE du bloc qui la porte. La déclaration se juge sur
            # le titre et la ligne ensemble, sinon l'index localisé — par métrique, période,
            # entité — ne retrouve jamais une composante nue, et le phasage entier tombe.
            _head = " ".join(l for l in lines[max(0, i - 3):i] if l.strip() and not _PHASE_LINE_RE.match(l))[-200:]
            # v62.13.9.4.48 — le titre de SECTION porte souvent la métrique (« ### … Budget
            # marketing … » au-dessus de « **Phasage** : ») : il entre dans le contexte.
            _sec = next((l for l in reversed(lines[max(0, i - 40):i]) if re.match(r"^\s*#{1,6}\s", l)), "")
            _ctx48 = (_sec + " \n " + _head).strip()
            undeclared = [r for r in rows if _should_withhold_line(r, result)
                          and not _has_declared_target_line(r, result, context=_ctx48)]
            en = str(lang or "fr").lower().startswith("en")
            if len(undeclared) < len(rows):
                blocks.append({"start": i, "end": j, "keep": True, "status_line": "", "undeclared": undeclared, "rows": rows})
            else:
                st = (("(phasage retiré du corps — scénario non validé, aucune phase déclarée ; conservé au registre du dossier complet)")
                      if not en else ("(phasing withdrawn from the body — unvalidated scenario, no declared phase; kept in the register of the complete file)"))
                blocks.append({"start": i, "end": j, "keep": False, "status_line": st, "undeclared": undeclared, "rows": rows})
        i = j
    return blocks


def _scenario_table_blocks(lines: list[str], result: Mapping[str, Any], lang: str) -> list[dict]:
    """Repère les tableaux prévisionnels et décide, par tableau, garder entier ou retirer entier."""
    blocks: list[dict] = []
    i, n = 0, len(lines)

    def _is_tbl(k: int) -> bool:
        ln = lines[k]
        if ln.lstrip().startswith("|"):
            return True
        # en-tête sans barre initiale (« Poste | 2024 | 2027 ») : c'est une ligne de
        # tableau si la ligne suivante est le séparateur markdown
        return ("|" in ln and k + 1 < n and re.match(r"^\s*\|?\s*:?-{3,}", lines[k + 1]) is not None)

    while i < n:
        if not _is_tbl(i):
            i += 1
            continue
        j = i
        while j < n and _is_tbl(j):
            j += 1
        tbl = lines[i:j]
        if len(tbl) >= 4:
            header = tbl[0]
            ctx = " ".join(lines[max(0, i - 3):i])
            years = len(set(_YEAR_COL_RE.findall(header)))
            projected = years >= 2 or bool(_PROJ_CTX_RE.search(ctx)) or bool(_PROJ_CTX_RE.search(header))
            data = [r for r in tbl[2:] if re.search(r"\d", r)]
            if projected and len(data) >= 3:
                undeclared = [r for r in data if _should_withhold_line(r, result)
                              and not _has_declared_target_line(r, result, context=(ctx + " \n " + header))]   # v62.13.9.4.48 — contexte du tableau
                admitted = len(data) - len(undeclared)
                en = str(lang or "fr").lower().startswith("en")
                labels = []
                for r in undeclared:
                    c = [x.strip() for x in r.strip().strip("|").split("|")]
                    if c and c[0]:
                        labels.append(c[0].strip("*"))
                if admitted >= 1:
                    if undeclared:
                        st = ((f"⟨statut : scénario de l'agent — lignes non déclarées ({', '.join(labels[:8])}) conservées pour la lisibilité du modèle ; "
                               f"hypothèses non étayées par pièce, à réconcilier avant tout usage chiffré⟩") if not en else
                              (f"⟨status: agent scenario — undeclared lines ({', '.join(labels[:8])}) kept for the readability of the model; "
                               f"assumptions not evidenced by a document, to be reconciled before any quantified use⟩"))
                    else:
                        st = ""
                    blocks.append({"start": i, "end": j, "keep": True, "status_line": st, "undeclared": undeclared, "rows": data})
                else:
                    st = (("(tableau prévisionnel retiré du corps — scénario non validé, aucune ligne déclarée ; conservé au registre du dossier complet)")
                          if not en else
                          ("(forecast table withdrawn from the body — unvalidated scenario, no declared line; kept in the register of the complete file)"))
                    blocks.append({"start": i, "end": j, "keep": False, "status_line": st, "undeclared": undeclared, "rows": data})
        i = j
    return blocks


def _sanitize_text(text: str, result: MutableMapping[str, Any], lang: str, path: tuple[str, ...]) -> str:
    text = str(text or "").replace("\u2063", "")      # v62.13.9.4.21 — le marqueur d'outil n'est jamais d'origine agent
    try:
        from utils.quantity_ledger import strip_status_tags as _sst62421
        text = _sst62421(text) if "⟨" in text else text  # un agent ne pose jamais de statut
    except Exception:
        pass
    if not text:
        return text
    # v62.13.7 (évidence) — les diagnostics, annexes et journaux sont des PREUVES :
    # aucune réécriture, d'aucune sorte, sur ces chemins.
    if any(re.search(r"diagnostic|raw|fs_log|pdf_priority|appendix|annexe|withheld|scenario|samples|observability|_log\b", p, re.I) for p in path):
        return text
    # v62.13.7 (H3) — la phrase d'alerte juridique n'est retirée que si un scrub est PROUVÉ.
    if _legal_scrub_evidenced(result):
        text = text.replace(_FALSE_LEGAL_FR, "").replace(_FALSE_LEGAL_EN, "")
    scope = financial_scope_summary(result, lang)
    if scope["group_consolidated_accounts_provided"]:
        fr_scope = "Comptes consolidés groupe fournis : oui — faits page-confirmés"
        en_scope = "Group consolidated accounts provided: yes — page-confirmed facts"
    else:
        fr_scope = "Comptes consolidés groupe fournis : non établis"
        en_scope = "Group consolidated accounts provided: not established"
    text = re.sub(r"Comptes\s+consolidés(?:\s+groupe)?\s+fournis\s*:\s*(?:oui|non(?:\s+établis?)?)", fr_scope, text, flags=re.I)
    text = re.sub(r"(?:Group\s+)?Consolidated\s+accounts\s+provided\s*:\s*(?:yes|no|not\s+established)", en_scope, text, flags=re.I)
    if not _has_financial_conflicts(result):
        text = text.replace("Conflit dur de métrique/périmètre — une même métrique est portée sur des périmètres ou des valeurs incompatibles", "Périmètre groupe non étayé par les pièces disponibles")
        text = text.replace("Hard metric/scope conflict", "Group perimeter not evidenced by the available documents")
        text = text.replace("Contradiction interne détectée entre sections du dossier", "")
        text = text.replace("Internal contradiction detected between dossier sections", "")
    # Correct the primary action when recent social accounts are present but OCR-only.
    if not scope["group_consolidated_accounts_provided"]:
        text = re.sub(
            r"Obtenir\s+(?:et\s+analyser\s+)?(?:les\s+)?comptes\s+consolidés\s+(?:19|20)\d{2}\s*[-–]\s*(?:19|20)\d{2}",
            "Fournir les comptes sociaux des exercices récents en PDF texte ou OCR, puis clarifier l’existence et le périmètre des comptes consolidés groupe",
            text,
            flags=re.I,
        )
    # Registry upper bounds/ranges must never become exact headcounts.
    text = _normalize_headcount_band_text(text)
    # Score chain: final value must be the actual displayed score, not the pre-truth cap.
    final_score = _final_confidence_score(result)
    if final_score is not None:
        text = re.sub(
            r"(Étapes\s+du\s+score\s*:[^\n]*?preuve\s+finale\s+)\d+(?:[.,]\d+)?/100",
            lambda m: m.group(1) + f"{int(round(final_score))}/100",
            text,
            flags=re.I,
        )
        if final_score < 60:
            text = re.sub(r"Preuve\s+étayée\s*[—-]\s*document\s+de\s+travail\s+supervisé", "Preuve insuffisante — usage exploratoire uniquement", text, flags=re.I)
    try:
        from patches.legal_citation_guard import neutralize_unsupported_social_threshold_claims
        text, _legal_findings62139 = neutralize_unsupported_social_threshold_claims(
            text, lang=lang, profile=(result or {}).get("company_profile"))
        if _legal_findings62139:
            result.setdefault("v62139_legal_claims_withheld", []).extend(_legal_findings62139)
    except Exception:
        _legal_findings62139 = []
    lines = text.splitlines()
    out: list[str] = []
    scenarios: list[dict[str, str]] = result.setdefault("v62136_withheld_scenarios", [])
    _work62421 = _status_mode(result)
    try:
        from utils.quantity_ledger import status_tag as _stag62421
    except Exception:
        _stag62421 = None
    # v62.13.9.4.32 (C) — UN SCÉNARIO SE GARDE ENTIER OU NE SE PRÉSENTE PAS.
    # Contre-audit du 11/09/2026 (run réel ee08f0) : le compte de résultat
    # prévisionnel de Finance comptait treize lignes ; le retrait ligne à ligne
    # des grandeurs non déclarées n'en laissait que six (achats, charges
    # externes, personnel, impôts, EBITDA, résultat d'exploitation, résultat net
    # disparus) — un modèle rendu moins vérifiable, son écart d'EBITDA masqué par
    # la suppression de ses opérandes. Un tableau prévisionnel (colonnes
    # d'années ou contexte projeté, trois lignes chiffrées au moins) est traité
    # comme UN bloc : si une ligne au moins est admise, toutes restent, et une
    # ligne de statut unique qualifie le tableau (scénario, lignes non déclarées
    # nommées, à réconcilier) ; si aucune n'est admise, le tableau entier est
    # retiré du corps et versé au registre — jamais un tableau à trous.
    _protected_rows62432: set[int] = set()
    _table_status62432: dict[int, str] = {}
    _blocks62432 = _scenario_table_blocks(lines, result, lang) + _phasing_blocks(lines, result, lang)   # v62.13.9.4.33 — phasages
    for _blk in _blocks62432:
        if _blk["keep"]:
            _protected_rows62432.update(range(_blk["start"], _blk["end"]))
            if _blk["status_line"]:
                _table_status62432[_blk["start"]] = _blk["status_line"]
            for _r in _blk["undeclared"]:
                scenarios.append({"section": "/".join(path), "original": _r, "replacement": _r,
                                  "status": ("SCENARIO_PHASING_KEPT_WHOLE_V62433" if _PHASE_LINE_RE.match(_r) else "SCENARIO_TABLE_KEPT_WHOLE_V62432")})
        else:
            for _i in range(_blk["start"], _blk["end"]):
                _protected_rows62432.add(_i)
            _table_status62432[_blk["start"]] = _blk["status_line"]
            for _r in _blk["rows"]:
                scenarios.append({"section": "/".join(path), "original": _r, "replacement": _blk["status_line"],
                                  "status": "SCENARIO_TABLE_WITHHELD_WHOLE_V62432"})
    _withheld_blocks62432 = {b["start"]: b for b in _blocks62432 if not b["keep"]}
    _product_table49 = False
    for _li, line in enumerate(lines):
        # v62.13.9.4.49 — tableau du produit : ses rangées passent telles quelles
        _st49 = line.strip()
        if _st49.startswith("|") and _st49.count("|") >= 3:
            if _is_product_table_header49(_st49.strip("|").split("|")):
                _product_table49 = True
            if _product_table49:
                out.append(line)
                continue
        else:
            _product_table49 = False
        if _li in _table_status62432:
            if out and out[-1].strip():
                out.append("")                       # un tableau markdown exige une ligne vide avant lui
            out.append(_table_status62432[_li])
            out.append("")                           # … et la ligne de statut ne doit pas le coller
        if _li in _protected_rows62432:
            _b = _withheld_blocks62432.get(_li) or next((b for b in _blocks62432 if b["start"] <= _li < b["end"]), None)
            if _b is not None and _b["keep"]:
                out.append(line)
            continue                                # tableau retiré entier : ses lignes ne passent pas
        canonical_fact = _canonical_fact_line(line, result)
        if canonical_fact and _status_mode(result):
            # v62.13.9.4.49 — la ligne de l'agent n'est plus remplacée par la formulation canonique (source des
            # libellés bilingues « Revenue / Chiffre d'affaires: … ») : elle reste ; si ses montants diffèrent du
            # fait confirmé, la formulation de la pièce est affichée à côté
            if _amounts_contradict49(_analysis_text(line), canonical_fact) and _stag62421 is not None:
                _src49 = re.sub(r"\s+", " ", canonical_fact).strip()[:100]
                out.append(_append_tag49(line, ("⟨status : contradicted by the source: " if str(lang).startswith("en")
                                                 else "⟨statut : contredit par la pièce : ") + _src49 + "⟩"))
            else:
                out.append(line)
        elif canonical_fact:
            out.append(canonical_fact)
        elif _work62421 and _stag62421 is not None and line.strip() and not _contradicts_registry62413(_analysis_text(line), result) and (
                _unsupported_revenue_trend(line, result) or _unsupported_market_growth(line, result)
                or _cross_metric_collision(line, result) or _should_withhold_line(line, result)):
            # mode statut : la ligne reste, son statut la suit
            if _unsupported_revenue_trend(line, result):
                kind = "trend"
            elif _unsupported_market_growth(line, result):
                kind = "market"
            elif _cross_metric_collision(line, result):
                kind = "collision"
            elif _has_declared_target_line(line, result):
                kind = "declared_target"
            else:
                kind = "unsupported"
            if _is_brief_echo49(line, result):             # v62.13.9.4.49 — texte du dirigeant
                out.append(line)
                continue
            tagged = _append_tag49(line, _stag62421(kind, lang))
            scenarios.append({"section": "/".join(path), "original": line, "replacement": tagged,
                              "status": "STATUS_TAGGED_V62421", "kind": kind})
            out.append(tagged)
        elif _unsupported_revenue_trend(line, result):
            _rl62425 = _rule_local_rewrite(line, lang, result, list(result.get("numeric_support_claims") or []),
                                           _unsupported_revenue_trend,
                                           "Tendance du chiffre d’affaires non établie dans le ledger — rapprocher les sources avant calcul.")
            out.append(_rl62425 or "Tendance du chiffre d’affaires non établie dans le ledger — rapprocher les sources avant calcul.")
        elif _unsupported_market_growth(line, result):
            _rl62425 = _rule_local_rewrite(line, lang, result, list(result.get("numeric_support_claims") or []),
                                           _unsupported_market_growth,
                                           _MARKET_GROWTH_EN if str(lang).lower().startswith("en") else _MARKET_GROWTH_FR)
            out.append(_rl62425 or (_MARKET_GROWTH_EN if str(lang).lower().startswith("en") else _MARKET_GROWTH_FR))
        elif _cross_metric_collision(line, result):
            fam = _metric_family(line)
            label = {
                "inventories": "des stocks",
                "revenue": "du chiffre d’affaires",
                "net_income": "du résultat net",
                "equity": "des capitaux propres",
            }.get(fam, "de la métrique")
            out.append(f"Valeur {label} non établie dans les pièces exploitables — à vérifier.")
        elif _should_withhold_line(line, result):
            replacement = _qualitative_replacement(line, lang, result)
            if replacement is None:
                replacement = _sentence_preserving_rewrite(line, lang)     # v62.13.9.4.22 — la phrase reste
            scenarios.append({"section": "/".join(path), "original": line, "replacement": replacement or (_V6213943_REMOVED_MARK_EN if str(lang).lower().startswith("en") else _V6213943_REMOVED_MARK), "status": "UNVALIDATED_SCENARIO_V62136"})
            if replacement:
                out.append(replacement)
        else:
            out.append(line)
    return "\n".join(out)


def _final_confidence_score(result: Mapping[str, Any]) -> float | None:
    """Resolve the score from current-run fields only; history is never consulted."""
    score_obj = result.get("delivery_confidence_score")
    if isinstance(score_obj, Mapping):
        for key in ("final_value", "final_score", "evidence_score", "score"):
            try:
                value = float(score_obj.get(key))
            except Exception:
                continue
            if 0 <= value <= 100:
                return value
    candidates: list[float] = []
    for row in _current_diagnostics(result):
        if str(row.get("role") or "") != "confidence_score":
            continue
        for key in ("final_value", "final_score", "evidence_score", "score"):
            try:
                value = float(row.get(key))
            except Exception:
                continue
            if 0 <= value <= 100:
                candidates.append(value)
                break
    return candidates[-1] if candidates else None


def _rewrite_tree(obj: Any, result: MutableMapping[str, Any], lang: str, path: tuple[str, ...] = ()) -> Any:
    """Rewrite a whitelisted editorial subtree.  Callers must not pass evidence trees."""
    if isinstance(obj, str):
        return _sanitize_text(obj, result, lang, path)
    if isinstance(obj, list):
        return [_rewrite_tree(value, result, lang, path + (str(idx),)) for idx, value in enumerate(obj)]
    if isinstance(obj, dict):
        return {key: _rewrite_tree(value, result, lang, path + (str(key),)) for key, value in obj.items()}
    return obj


def _has_financial_conflicts(result: Mapping[str, Any]) -> bool:
    for d in _diagnostics(result):
        if str(d.get("role") or "") == "financial_proof_layer":
            try:
                if int(float(d.get("conflicts") or 0)) > 0 or int(float(d.get("current_critical_conflicts") or 0)) > 0:
                    return True
            except Exception:
                pass
    return False


def _apply_profile_display(result: MutableMapping[str, Any]) -> None:
    profile = result.get("company_profile")
    if not isinstance(profile, MutableMapping):
        return
    pair = None
    for key in ("headcount_range", "headcount_display", "employee_range", "workforce_range"):
        pair = _v6213942_band_pair(profile.get(key))
        if pair:
            break
    if pair is None and not bool(profile.get("headcount_exact")):
        pair = _v6213942_band_from_upper_bound(profile.get("headcount"))
    if pair is None:
        return
    label = f"{pair[0]}–{pair[1]}"
    profile["headcount"] = None
    profile["headcount_range"] = label
    profile["headcount_display"] = f"{label} salariés"
    profile["headcount_exact"] = False
    for key in ("headcount_text", "scope_text"):
        if isinstance(result.get(key), str):
            result[key] = _normalize_headcount_band_text(result[key])



def _raw_current_blockers(result: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for candidate in (result.get("blockers"), result.get("run_block_reasons")):
        if isinstance(candidate, list):
            for item in candidate:
                code = item.get("code") if isinstance(item, Mapping) else item
                if code and str(code) not in values:
                    values.append(str(code))
    guards = result.get("b23_guards")
    if isinstance(guards, Mapping):
        for key in ("blockers", "run_block_reasons", "flags"):
            candidate = guards.get(key)
            if isinstance(candidate, list):
                for item in candidate:
                    code = item.get("code") if isinstance(item, Mapping) else item
                    if code and str(code) not in values:
                        values.append(str(code))
    for row in _current_diagnostics(result):
        if str(row.get("role") or "") != "mission_gates":
            continue
        for key in ("blockers", "flagged"):
            candidate = row.get(key)
            if isinstance(candidate, list):
                for item in candidate:
                    if item and str(item) not in values:
                        values.append(str(item))
    return values



def _pipeline_execution_grade(result: Mapping[str, Any], effective_blockers: list[str]) -> str:
    if effective_blockers:
        return "BLOCKED"
    for row in _current_diagnostics(result):
        if str(row.get("role") or "") == "mission_gates":
            status = str(row.get("status") or "").upper()
            if "RÉSERV" in status or "RESERV" in status:
                return "PASS_WITH_RESERVATIONS"
            if "MISSION-GRADE" in status or status == "OK":
                return "PASS"
    return "PASS_WITH_RESERVATIONS"


def _work_product_usability(result: Mapping[str, Any]) -> str:
    usefulness = None
    for row in _current_diagnostics(result):
        if str(row.get("role") or "") == "decision_usefulness":
            for key in ("decision_usefulness_score", "usefulness_score", "score", "final_value"):
                try:
                    usefulness = float(row.get(key))
                    break
                except Exception:
                    pass
    final_score = _final_confidence_score(result)
    if (usefulness is not None and usefulness < 50) or (final_score is not None and final_score < 50):
        return "NOT_MISSION_USABLE"
    if usefulness is not None and usefulness < 65:
        return "EXPLORATORY_ONLY"
    return "USABLE_UNDER_SUPERVISION"

def _effective_gate_state(result: Mapping[str, Any]) -> dict[str, Any]:
    raw = _raw_current_blockers(result)
    scrub_ok, scrub_source = _legal_scrub_evidence(result)
    has_conflicts = _has_financial_conflicts(result)
    effective: list[str] = []
    info: list[str] = []
    requalifications: list[dict[str, str]] = []
    for blocker in raw:
        new = blocker
        if blocker in {_FALSE_LEGAL_CODE, _FALSE_LEGAL_FR, _FALSE_LEGAL_EN} and scrub_ok:
            requalifications.append({"from": blocker, "to": "REMOVED", "reason": "CURRENT_RUN_LEGAL_SCRUB"})
            continue
        if blocker == _SCOPE_CONFLICT_CODE and not has_conflicts:
            new = _SCOPE_NOT_EVIDENCED_CODE
            requalifications.append({"from": blocker, "to": new, "reason": "NO_CURRENT_FPL_CONFLICT"})
        elif blocker == _INTERNAL_CONTRADICTION_CODE and not has_conflicts:
            info.append(_INTERNAL_CONTRADICTION_INFO_CODE)
            requalifications.append({"from": blocker, "to": _INTERNAL_CONTRADICTION_INFO_CODE, "reason": "INFORMATIONAL_ONLY"})
            continue
        if new not in effective:
            effective.append(new)
    return {
        "raw_blockers": raw,
        "effective_blockers": effective,
        "informational_flags": info,
        "requalifications": requalifications,
        "legal_scrub_evidenced": scrub_ok,
        "legal_scrub_evidence_source": scrub_source,
        "run_fingerprint": _current_run_fingerprint(result),
        "pipeline_execution_grade": _pipeline_execution_grade(result, effective),
        "work_product_usability": _work_product_usability(result),
    }


def _rewrite_gate_list(value: Any, state: Mapping[str, Any]) -> Any:
    if not isinstance(value, list):
        return value
    effective = list(state.get("effective_blockers") or [])
    # Preserve structured non-code reasons, but replace known code lists.
    if all(isinstance(item, str) for item in value):
        known = set(state.get("raw_blockers") or [])
        if any(item in known for item in value):
            return effective
    return deepcopy(value)


def _apply_effective_gate_view(editorial: MutableMapping[str, Any], state: Mapping[str, Any]) -> None:
    editorial["blockers"] = list(state.get("effective_blockers") or [])
    editorial["informational_flags"] = list(state.get("informational_flags") or [])
    editorial.setdefault("meta", {})["mission_gate_effective_v62138"] = deepcopy(dict(state))
    for key in ("run_block_reasons",):
        if key in editorial:
            editorial[key] = _rewrite_gate_list(editorial.get(key), state)
    for container_key in ("b23_guards", "delivery_confidence_score"):
        container = editorial.get(container_key)
        if not isinstance(container, MutableMapping):
            continue
        for key in ("blockers", "run_block_reasons", "flagged"):
            if key in container:
                container[key] = _rewrite_gate_list(container.get(key), state)
        container["effective_blockers_v62138"] = list(state.get("effective_blockers") or [])
        container["informational_flags_v62138"] = list(state.get("informational_flags") or [])


def _apply_editorial_surfaces(editorial: MutableMapping[str, Any], lang: str) -> None:
    # v62.13.9.4.29 — copie des sorties AVANT assainissement pour la garde
    # arithmétique (les valeurs neutralisées ne se recalculent plus) ; retirée en fin.
    try:
        _raw_outputs_62429 = deepcopy(editorial.get("outputs")) if isinstance(editorial.get("outputs"), dict) else None
    except Exception:
        _raw_outputs_62429 = None
    # v62.13.9.4.18 — point 6 : les chiffres de marché sourcés reçoivent leur
    # étiquette AVANT la sanitation, pour que la sanitation les reconnaisse.
    try:
        _nb62418 = _label_benchmarks_in_outputs(editorial, lang)
        if _nb62418:
            editorial["v62418_benchmarks_labelled"] = _nb62418
    except Exception:
        pass
    for key in _EDITORIAL_TOP_LEVEL_KEYS:
        if key not in editorial or key in _IMMUTABLE_TOP_LEVEL_KEYS:
            continue
        editorial[key] = _rewrite_tree(editorial[key], editorial, lang, (key,))
    # v62.13.9.4.29 — audit du dossier industriel v28 (P1) : cohérence arithmétique des
    # simulations APRÈS l'assainissement (un statut posé avant serait retiré
    # comme statut d'agent) — la ligne FCF incohérente et les conclusions qui
    # en dépendent portent leur statut (travail) ou leur réserve en clair
    # (synthèse). Aucune valeur de dossier dans la règle.
    try:
        from utils.simulation_arithmetic_guard import apply_to_outputs as _sag
        _src62429 = {"outputs": _raw_outputs_62429} if _raw_outputs_62429 else None
        _fpl30 = editorial.get("financial_proof_layer") or {}
        _est30 = bool(_fpl30.get("current_confirmed_on_page") or _fpl30.get("executive_confirmed_on_page")) \
            if isinstance(_fpl30, dict) and _fpl30 else True
        editorial["simulation_arithmetic"] = _sag(editorial.get("outputs") or {}, lang,
                                                  "work" if _status_mode(editorial) else "synthesis",
                                                  current_financials_established=_est30,
                                                  source=(_src62429.get("outputs") if isinstance(_src62429, dict) and isinstance(_src62429.get("outputs"), dict) else None))
    except Exception as _e62429:
        editorial["simulation_arithmetic"] = {"error": str(_e62429)[:120]}


def _upsert_maintenance_row(result: MutableMapping[str, Any], row: Mapping[str, Any]) -> None:
    rows = result.setdefault("diagnostics_attempts", [])
    if not isinstance(rows, list):
        return
    target_role = str(row.get("role") or _MAINTENANCE_ROLE)
    for idx, existing in enumerate(rows):
        if isinstance(existing, Mapping) and str(existing.get("role") or "") == target_role:
            rows[idx] = deepcopy(dict(row))
            return
    rows.append(deepcopy(dict(row)))


_HEADCOUNT_BAND_LINE_RE = re.compile(
    r"(?:Effectif exact non établi|Exact headcount not established)[^\n]{0,40}?"
    r"(?:tranche registre|registry band)\s*:\s*(\d[\d\s\u00a0]*)\s*[–\-]\s*(\d[\d\s\u00a0]*)\s*(?:salariés?|employees?)\.?", re.I)


_BENCHMARK_FIGURE_RE = re.compile(r"[+\-−]?\d+(?:[.,]\d+)?\s?(?:%|M€|Md€|k€|€|millions?|milliards?|M\$|bn)", re.I)


def _benchmark_label_line(line: str, language: str) -> str:
    """v62.13.9.4.18 — une ligne de MARCHÉ chiffrée qui cite une source nommée
    sans URL vérifiable reçoit l'étiquette « benchmark non vérifié » (une seule
    fois) : le chiffre reste lisible, il n'est ni un fait ni une cible."""
    try:
        from utils.quantity_ledger import (has_source_label, is_labelled_benchmark_line,
                                           BENCHMARK_MARK_FR, BENCHMARK_MARK_EN)
    except Exception:
        return line
    s = str(line or "")
    if not s.strip() or is_labelled_benchmark_line(s) or not has_source_label(s):
        return line
    if not _BENCHMARK_FIGURE_RE.search(s) or not re.search(r"\b(?:march[ée]|market|secteur|sector|segment|"
                                                            r"CA|chiffre d['’]affaires|revenue|croissance|growth|"
                                                            r"[ée]volution|historique|TCAM|CAGR|part de march[ée]|market share)\b", s, re.I):
        return line
    if re.search(r"https?://", s):
        return line                                  # URL présente : la provenance est vérifiable
    mark = BENCHMARK_MARK_EN if str(language).lower().startswith("en") else BENCHMARK_MARK_FR
    m = re.match(r"^(\s*\|.*\S)\s*\|\s*$", s)
    if m and s.count("|") >= 3:                         # rangée markdown : dans la dernière cellule
        return m.group(1) + " " + mark + " |"
    return s.rstrip() + " " + mark


def _label_benchmarks_in_outputs(editorial: MutableMapping[str, Any], language: str) -> int:
    n = 0
    for holder in (editorial, editorial.get("outputs")):
        if not isinstance(holder, dict):
            continue
        for k, v in list(holder.items()):
            if not isinstance(v, str) or not v or k in ("brief", "lang"):
                continue
            lines = v.split("\n")
            changed = False
            for i, ln in enumerate(lines):
                nl = _benchmark_label_line(ln, language)
                if nl != ln:
                    lines[i] = nl; changed = True; n += 1
            if changed:
                holder[k] = "\n".join(lines)
    return n


_HUMAN_ANNEX_MAX = 8      # v62.13.9.4.23 — pagination du document de travail
_ARBITRABLE_RE = re.compile(
    r"\b(?:cible|objectif|viser|atteindre|d['’]ici|recommand|arbitr|d[ée]cid|budget|TJM|CA\b|chiffre d['’]affaires|"
    r"marge|tr[ée]sorerie|prix|tarif|volume|missions?|contacts?|clients?|target|goal|budget|revenue|margin|pricing)",
    re.I)


def _select_arbitrable(entries: list[dict], limit: int) -> list[dict]:
    """Hypothèses réellement arbitrables : lignes chiffrées portant une cible,
    un budget, un prix, un volume ou une décision — dédupliquées par valeur et
    métrique, les plus longues (les plus riches) d'abord, au plus ``limit``."""
    scored: list[tuple[int, str, dict]] = []
    seen_keys: set[str] = set()
    for item in entries:
        orig = _norm_space(str(item.get("original") or ""))
        if not orig or not re.search(r"\d", orig):
            continue
        if not _ARBITRABLE_RE.search(orig):
            continue
        nums = tuple(re.findall(r"\d+(?:[.,]\d+)?", orig))[:3]
        key = " ".join(nums) + "|" + (_ARBITRABLE_RE.search(orig).group(0).lower())
        if key in seen_keys:
            continue
        seen_keys.add(key)
        score = (3 if re.search(r"\b(?:cible|objectif|target|goal)\b", orig, re.I) else 0) \
            + (2 if re.search(r"\b(?:budget|TJM|CA|prix|tarif|marge|revenue|margin)\b", orig, re.I) else 0) \
            + min(len(orig), 300) // 100
        scored.append((score, orig, item))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [it for _, _, it in scored[:limit]]


def _write_register_sidecar(entries: list[dict], lang: str, result) -> dict | None:
    """Fichier probatoire du registre exhaustif (JSON + CSV), à côté du dossier
    de run (``CODIR_RUN_DOSSIER_DIR`` ou ``outputs``). Le chemin est tracé dans
    le résultat (``register_sidecar``)."""
    import csv as _csv
    import json as _json
    import os as _os
    from datetime import datetime as _dt
    try:
        target = _os.environ.get("CODIR_RUN_DOSSIER_DIR") or "outputs"
        _os.makedirs(target, exist_ok=True)
        stamp = _dt.now().strftime("%Y%m%d-%H%M%S")
        base = f"registre_scenarios_{stamp}"
        rows = []
        for idx, item in enumerate(entries, 1):
            rows.append({
                "id": f"SCN-V62139-{idx:03d}",
                "original": _norm_space(str(item.get("original") or "")),
                "replacement": _norm_space(str(item.get("replacement") or "")),
                "source": str(item.get("section") or item.get("source_type") or ""),
                "status": "non validé — grandeur ou cible non rattachée à une pièce" if not str(lang).startswith("en")
                          else "unvalidated — quantity or target not tied to a source document",
                "decision": ("confirmer la baseline, la formule, la provenance et le porteur ; réintégrer ou retirer"
                             if not str(lang).startswith("en") else
                             "confirm baseline, formula, provenance and owner; reinstate or drop"),
            })
        jpath = _os.path.join(target, base + ".json")
        cpath = _os.path.join(target, base + ".csv")
        with open(jpath, "w", encoding="utf-8") as fh:
            _json.dump({"version": "register-sidecar-v1", "run_id": str((result or {}).get("run_id") or ""),
                        "entries": rows}, fh, ensure_ascii=False, indent=1)
        with open(cpath, "w", encoding="utf-8", newline="") as fh:
            w = _csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["id"], delimiter=";")
            w.writeheader()
            for r in rows:
                w.writerow(r)
        info = {"json": _os.path.basename(jpath), "csv": _os.path.basename(cpath), "dir": target, "entries": len(rows)}
        try:
            if isinstance(result, MutableMapping):
                result["register_sidecar"] = info
        except Exception:
            pass
        return info
    except Exception:
        return None


def _repair_headcount_contradictions(editorial: MutableMapping[str, Any], language: str) -> list[dict]:
    """Remplace, dans toutes les sorties texte, un cadrage d'effectif
    contredit par le profil réel (headcount connu hors de la tranche citée,
    ou tranche connue différente)."""
    prof = editorial.get("company_profile") or {}
    if not isinstance(prof, dict):
        return []
    hc = prof.get("headcount")
    rng = str(prof.get("headcount_range") or "").strip()
    if hc is None and not rng:
        return []
    try:
        from patches.legal_citation_guard import social_threshold_safe_text
        safe = social_threshold_safe_text(language, prof)
    except Exception:
        return []

    def _contradicts(lo: str, hi: str) -> bool:
        try:
            lo_i = int(re.sub(r"\D", "", lo)); hi_i = int(re.sub(r"\D", "", hi))
        except ValueError:
            return False
        if isinstance(hc, (int, float)):
            return not (lo_i <= int(hc) <= hi_i)
        if rng:
            return re.sub(r"\s", "", rng).replace("-", "–") != f"{lo_i}–{hi_i}"
        return False

    repairs: list[dict] = []

    def _fix(text: str, where: str) -> str:
        def _sub(m):
            if _contradicts(m.group(1), m.group(2)):
                repairs.append({"where": where, "before": m.group(0)[:160], "after": safe[:160]})
                return safe
            return m.group(0)
        return _HEADCOUNT_BAND_LINE_RE.sub(_sub, text)

    for holder_name, holder in (("result", editorial), ("outputs", editorial.get("outputs"))):
        if not isinstance(holder, dict):
            continue
        for k, v in list(holder.items()):
            if isinstance(v, str) and v:
                nv = _fix(v, f"{holder_name}/{k}")
                if nv != v:
                    holder[k] = nv
    return repairs


def apply_v62136_maintenance(result: MutableMapping[str, Any], lang: str | None = None) -> MutableMapping[str, Any]:
    """Build an idempotent delivery-only view and leave the evidence tree intact.

    The only mutation of the raw result is an explicit diagnostic bridge row.
    """
    if not isinstance(result, MutableMapping):
        return result
    if result.get("_v62138_editorial_view"):
        return result
    language = (lang or str(result.get("lang") or result.get("language") or "fr")).lower()
    scope = financial_scope_summary(result, language)
    state = _effective_gate_state(result)

    editorial = deepcopy(result)
    editorial["_v62138_editorial_view"] = True
    editorial["_v62136_maintenance_applied"] = True  # compatibility with prior contracts
    editorial["v62136_withheld_scenarios"] = []
    editorial["v62138_withheld_scenarios"] = editorial["v62136_withheld_scenarios"]
    editorial["v62139_legal_claims_withheld"] = []
    editorial.setdefault("meta", {})["financial_document_scope_v62138"] = deepcopy(scope)
    editorial.setdefault("meta", {})["document_extractability_v62139"] = deepcopy(scope.get("document_extractability") or [])
    editorial.setdefault("meta", {})["ocr_required_files"] = list(scope["ocr_required_files"])
    _apply_profile_display(editorial)
    # v62.13.9.4.6 — le spécialiste avant le généraliste : la sécurité
    # factuelle Finance tague/retire les simulations personnelles AVANT la
    # passe éditoriale générique ; les lignes taguées [SCÉNARIO ILLUSTRATIF]
    # traversent ensuite le registre du ledger.
    try:
        from utils.finance_factual_safety import (
            has_primary_financial_evidence as _hpfe62146,
            sanitize_finance_output as _sfo62146,
        )
        _hp62146 = _hpfe62146(
            editorial.get("financial_facts_table"),
            editorial.get("financial_facts_table_status"))
        _cp62146 = editorial.get("company_profile") or {}
        _lf62146 = (_cp62146.get("legal_form") if isinstance(_cp62146, dict) else "") or ""
        for _holder62146 in (editorial, editorial.get("outputs")):
            if isinstance(_holder62146, dict) and isinstance(_holder62146.get("finance"), str) \
                    and _holder62146["finance"].strip():
                _out62146, _rep62146 = _sfo62146(
                    _holder62146["finance"], has_primary_financials=_hp62146,
                    lang=language, entity_form=_lf62146)
                _rep62146 = _rep62146 if isinstance(_rep62146, dict) else {}
                if any(int(_rep62146.get(_k) or 0) > 0 for _k in (
                        "tns_sasu_flagged", "personalized_sim_tagged",
                        "illustrative_revenue_tagged")):
                    _holder62146["finance"] = _out62146
    except Exception:
        pass
    # v62.13.9.4.16 — COHÉRENCE D'ENTITÉ (contre-audit P0-01 / point 9) :
    # un cadrage d'effectif qui contredit le profil réel — « tranche
    # registre : 500–999 salariés » dans un dossier à 0 salarié — est
    # remplacé par le cadrage construit depuis le profil, dans toutes les
    # sorties. Couvre les runs déjà contaminés en amont (dossiers antérieurs
    # à la correction de la garde) et toute réinjection future.
    try:
        _rep62416 = _repair_headcount_contradictions(editorial, language)
        if _rep62416:
            editorial.setdefault("v62416_entity_coherence_repairs", []).extend(_rep62416)
    except Exception:
        pass
    _apply_editorial_surfaces(editorial, language)
    _apply_effective_gate_view(editorial, state)

    row = {
        "role": _MAINTENANCE_ROLE,
        "provider": "internal",
        "model": "current_run_editorial_truth_v62138",
        "status": "OK",
        "run_fingerprint": state["run_fingerprint"],
        "raw_blockers": list(state["raw_blockers"]),
        "effective_blockers": list(state["effective_blockers"]),
        "informational_flags": list(state["informational_flags"]),
        "requalifications": deepcopy(state["requalifications"]),
        "legal_scrub_evidence_source": state["legal_scrub_evidence_source"],
        "financial_scope": deepcopy(scope),
        "withheld_scenarios": len(editorial.get("v62136_withheld_scenarios") or []),
        "final_confidence_score": _final_confidence_score(result),
        "evidence_tree_mutated": False,
        "document_extractability": deepcopy(scope.get("document_extractability") or []),
        "pipeline_execution_grade": state.get("pipeline_execution_grade"),
        "work_product_usability": state.get("work_product_usability"),
        "legal_claims_withheld": len(editorial.get("v62139_legal_claims_withheld") or []),
    }
    # v62.13.9.4.49 — ENTITÉS NON VÉRIFIÉES : le validateur d'entités posait « [NON SOURCÉ] » au milieu de la
    # phrase (« Is Option [UNSOURCED] 2 authorized… », synthèse d'un run réel du 28/09), et en français dans les runs
    # anglais. Le marqueur du produit est retiré du milieu de la phrase et remplacé par UNE étiquette en fin
    # de ligne, nommant les entités ; le rendu la signale comme les autres (« ⚠ à vérifier — entité non
    # vérifiée : … »). Le texte de l'agent n'est pas touché.
    try:
        _ENT49 = re.compile(r"\s*\[(?:NON SOURC[ÉE]|UNSOURCED|NOT SOURCED)\]")
        _outs_e49 = editorial.get("outputs")
        if isinstance(_outs_e49, dict):
            _en_e49 = str(language or "fr").lower().startswith("en")
            for _k_e49, _v_e49 in list(_outs_e49.items()):
                if not isinstance(_v_e49, str) or not _ENT49.search(_v_e49):
                    continue
                _ls_e49 = _v_e49.split("\n")
                for _i_e49, _l_e49 in enumerate(_ls_e49):
                    if not _ENT49.search(_l_e49):
                        continue
                    _names49 = []
                    for _m49 in _ENT49.finditer(_l_e49):
                        _before49 = _l_e49[:_m49.start()]
                        _nm49 = re.search(r"((?:[A-ZÀ-Ý][\w&'’.-]*\s?){1,4})$", _before49)
                        _cand49 = _nm49.group(1).strip() if _nm49 else ""
                        # audit du 29/09/2026 : pas d'« entité » pour un repère entre crochets ([SC-1], [AI ESTIM.]),
                        # un mot tout en capitales (RECOMMENDED, ACTIONNAIRE) ou un code (SC-2) — ce sont des
                        # libellés d'agent, pas des noms propres à vérifier
                        # v62.13.9.4.50 — un libellé de présentation n'est pas une entité (« Projection CA »,
                        # contre-recette du 30/09, A06) : le premier mot de présentation est retiré, et il ne reste
                        # rien à vérifier s'il ne subsiste qu'un sigle
                        _w50 = _cand49.split()
                        while _w50 and _w50[0].lower().strip(".:;,") in _PRESENTATION_WORDS50:
                            _w50 = _w50[1:]
                        _cand49 = " ".join(_w50)
                        if (_cand49 and not re.search(r"\[[^\]]*$", _before49)
                                and not re.fullmatch(r"[A-ZÀ-Ý0-9 .&'’-]+", _cand49)):
                            _names49.append(_cand49)
                    _clean49 = _ENT49.sub("", _l_e49).rstrip()
                    if not _names49:
                        _ls_e49[_i_e49] = _clean49                   # rien à signaler : le marqueur est retiré
                        continue
                    # un titre de section ne reçoit pas d'étiquette (il cesserait d'être reconnu comme titre
                    # et sa section serait perdue : arbitrages d'un rejeu réel) ; le marqueur est seulement retiré
                    if (re.match(r"^\s*(?:#{1,6}\s|\d+[.)]\s+\*\*|\*\*[^*]+\*\*[\s:]*$)", _clean49)
                            or re.fullmatch(r"\s*(?:\[[^\]]*\]\s*)?[A-ZÀ-Ý0-9 .,:;&'’/()–-]{3,90}", _clean49)):
                        _ls_e49[_i_e49] = _clean49
                        continue
                    _motif49 = (("unverified entity: " if _en_e49 else "entité non vérifiée : ")
                                + ", ".join(dict.fromkeys(_names49))) if _names49 else (
                                "unverified entity" if _en_e49 else "entité non vérifiée")
                    _ls_e49[_i_e49] = _append_tag49(_clean49, ("⟨status : " if _en_e49 else "⟨statut : ") + _motif49 + "⟩")
                _outs_e49[_k_e49] = "\n".join(_ls_e49)
    except Exception:
        pass
    # v62.13.9.4.50 — CONTRÔLES D'ASSERTIONS (contre-recette du 30/09, A01) : une marge annoncée pour l'exercice des
    # faits est rapprochée du rapport des faits confirmés, et un montant publié présenté « hors ajustement » voit sa
    # qualification signalée. Le texte n'est jamais modifié.
    if _status_mode(result):
        try:
            from utils.assertion_checks50 import flag_lines as _acf50
            _outs_a50 = editorial.get("outputs")
            if isinstance(_outs_a50, dict):
                _en_a50 = str(language or "fr").lower().startswith("en")
                for _k_a50, _v_a50 in list(_outs_a50.items()):
                    if not isinstance(_v_a50, str) or not _v_a50:
                        continue
                    _hits_a50 = _acf50(_v_a50, result, language)
                    if not _hits_a50:
                        continue
                    _ls_a50 = _v_a50.split("\n")
                    for _i_a50, _m_a50 in _hits_a50:
                        # le motif PRÉCIS s'ajoute même si la ligne porte déjà un statut générique (« chiffre sans
                        # pièce ») : le rendu fusionne les motifs, le plus utile au consultant n'est plus perdu
                        if (0 <= _i_a50 < len(_ls_a50) and _m_a50 not in _ls_a50[_i_a50]
                                and not _is_brief_echo49(_ls_a50[_i_a50], result)):
                            _ls_a50[_i_a50] = _append_tag49(_ls_a50[_i_a50], ("⟨status : " if _en_a50 else "⟨statut : ") + _m_a50 + "⟩")
                    _outs_a50[_k_a50] = "\n".join(_ls_a50)
        except Exception:
            pass
    # v62.13.9.4.50 — STATUTS NON ÉTABLIS (contre-recette du 30/09, C02) : le module de vocabulaire ne réécrit plus
    # « décidée » en « à arbitrer » ; une ligne où un agent présente comme décidé, acté ou validé ce que le brief
    # n'établit pas est signalée en place. Un statut repris du brief (autorité du dirigeant) n'est pas signalé.
    if _status_mode(result):
        try:
            from patches.lucidity_wording import lucidity_flag_lines as _lfl50
            _brief50 = str(((result.get("inputs") or {}).get("brief")) or "")
            _outs50 = editorial.get("outputs")
            if isinstance(_outs50, dict):
                _en50 = str(language or "fr").lower().startswith("en")
                for _k50, _v50 in list(_outs50.items()):
                    if not isinstance(_v50, str) or not _v50:
                        continue
                    _ls50 = _v50.split("\n")
                    _hits50 = _lfl50(_v50, language, _brief50)
                    for _i50, _mot50 in _hits50:
                        if 0 <= _i50 < len(_ls50) and "⟨" not in _ls50[_i50] and not _is_brief_echo49(_ls50[_i50], result):
                            _ls50[_i50] = _append_tag49(_ls50[_i50], ("⟨status : " if _en50 else "⟨statut : ") + _mot50 + "⟩")
                    if _hits50:
                        _outs50[_k50] = "\n".join(_ls50)
        except Exception:
            pass
    # v62.13.9.4.49 — la garde de rigueur exécutive ne réécrit plus (doctrine du 28/09/2026) : ses constats
    # sont étiquetés ici, en place, quand le mainteneur ne l'a pas déjà fait. La couverture de détection
    # de la garde (formes de cibles, tableaux de cibles, blocs de scénario) est conservée intégralement.
    try:
        _bsg49 = ((result.get("board_scrutiny_guard") or {}).get("withheld_scenarios") or [])
        _lines49 = {}
        for _w49 in _bsg49:
            if isinstance(_w49, dict) and _w49.get("policy") == "FLAG_IN_PLACE":
                _o49 = re.sub(r"\s+", " ", str(_w49.get("original") or "")).strip()
                if _o49:
                    _lines49[_o49] = _w49
        if _lines49 and isinstance(editorial.get("outputs"), dict):
            from utils.quantity_ledger import status_tag as _stag49, is_status_tagged as _ist49
            _tag49 = _stag49("unsupported", language)
            _en49 = str(language or "fr").lower().startswith("en")
            _n49 = 0
            for _k49, _v49 in list(editorial["outputs"].items()):
                if not isinstance(_v49, str):
                    continue
                _ls49 = _v49.split("\n")
                _chg49 = False
                for _i49, _l49 in enumerate(_ls49):
                    _key49 = re.sub(r"\s+", " ", _l49).strip()
                    if _key49 in _lines49 and not _ist49(_l49):
                        _w49 = _lines49[_key49]
                        # 9.4.60 — F59-05 : même règle de comparabilité que les autres émetteurs (sinon signalement générique)
                        if (_w49.get("kind") == "contradicted_fact" and _w49.get("source_line")
                                and _amounts_contradict49(_l49, str(_w49.get("source_line")))):
                            _src49 = str(_w49.get("source_line"))
                            _t49 = (f"⟨status : contradicted by the source: {_src49}⟩" if _en49 else
                                    f"⟨statut : contredit par la pièce : {_src49}⟩")
                        else:
                            _t49 = _tag49
                        _ls49[_i49] = _append_tag49(_l49, _t49)
                        _chg49 = True
                        _n49 += 1
                if _chg49:
                    editorial["outputs"][_k49] = "\n".join(_ls49)
            row["board_guard_flags_placed"] = _n49
    except Exception:
        pass
    # v62.13.9.4.49 — point 0 : UN SEUL RÉALISÉ. Toute colonne « réalisé » d'un tableau d'agent qui
    # contredit la base confirmée à la page reçoit, dans la cellule du chiffre, l'étiquette qui porte la
    # valeur de la pièce ; le rendu l'affiche à côté du chiffre (contre-recette ChatGPT du 28/09, F4).
    try:
        from utils.actuals_reconciliation49 import tag_contradicted_actuals as _tca49
        _facts49 = ((result.get("financial_facts_table") or {}).get("facts") or [])
        _outs49 = editorial.get("outputs")
        if _facts49 and isinstance(_outs49, dict):
            _found49 = []
            for _k49, _v49 in list(_outs49.items()):
                if isinstance(_v49, str) and "|" in _v49:
                    _new49, _f49 = _tca49(_v49, _facts49, language)
                    if _f49:
                        _outs49[_k49] = _new49
                        _found49 += [dict(x, output=_k49) for x in _f49]
            if _found49:
                editorial["v62149_actuals_contradicted"] = _found49
                row["actuals_contradicted"] = len(_found49)
    except Exception:
        pass
    # v62.13.9.4.48 — point 4 : les CIBLES DU BRIEF sont signalées UNE fois, en tête de la section du
    # brief, avec leur statut ; le corps les cite sans étiquette (typées « cible du brief » au
    # registre). Liste vide sans brief : rien n'est ajouté.
    try:
        _bt48 = _brief_targets48(result)
        _outs48 = editorial.get("outputs")
        if _bt48 and isinstance(_outs48, dict) and _outs48:
            _en48 = language.startswith("en")
            _lines48 = []
            for _it in _bt48:
                _bl = re.sub(r"^[\s\-–—•*]+", "", str(_it.get("brief_line") or "")).rstrip(" ;.")
                if _bl and _bl not in _lines48:
                    _lines48.append(_bl)
            _quoted48 = " ; ".join(f"« {_bl} »" for _bl in _lines48[:8])
            _notice48 = ("ⓘ\u2063 Brief targets, quoted as such in the analysis — management's declarations, "
                         f"not certified by a document: {_quoted48}." if _en48 else
                         "ⓘ\u2063 Cibles du brief, citées telles quelles dans l'analyse — déclarations du dirigeant, "
                         f"non certifiées par une pièce : {_quoted48}.")
            _key48 = "brief_codir" if "brief_codir" in _outs48 else next(iter(_outs48))
            _txt48 = str(_outs48.get(_key48) or "")
            if "\u2063 Cibles du brief" not in _txt48 and "\u2063 Brief targets" not in _txt48:
                _outs48[_key48] = _notice48 + "\n\n" + _txt48
            editorial["v62148_brief_targets"] = [dict(_it) for _it in _bt48]
            row["brief_targets_flagged_once"] = len(_lines48)
    except Exception:
        pass
    _upsert_maintenance_row(result, row)
    _upsert_maintenance_row(result, {
        "role": _FINAL_SAFETY_ROLE,
        "provider": "internal",
        "model": "work_product_final_safety_v62139",
        "status": "OK",
        "run_fingerprint": state["run_fingerprint"],
        "pipeline_execution_grade": state.get("pipeline_execution_grade"),
        "work_product_usability": state.get("work_product_usability"),
        "quantity_kpi_policy": "OPTION_B_STRICT",
        "legal_claim_gate": "SOCIAL_THRESHOLD_REQUALIFIED",
        "ocr_status_policy": "TRI_STATE",
        "planning_date_policy": "PRESERVE",
        "social_revenue_card_policy": "QUALIFIED",
        "unsupported_revenue_trend_policy": "REMOVE_UNLESS_LEDGER_SUPPORTED",
        "evidence_tree_mutated": False,
    })
    editorial["diagnostics_attempts"] = deepcopy(result.get("diagnostics_attempts") or [])
    try:
        _scope_guard61(editorial, language)
    except Exception:
        pass
    return editorial


_SCOPE_STOP61 = {"avancement", "comité", "comite", "dirigeant", "conseil", "séance", "seance", "brief", "statut", "action"}


def _scope_guard61(editorial: MutableMapping[str, Any], language: str) -> None:
    """9.4.61 — contre-recette ChatGPT du 12/10/2026 (M60-01) : « Présenter l'avancement des cibles d'émissions 2030 —
    réalisée » devenait « les cibles d'émissions 2030 sont réalisées ». Une phrase qui déclare l'OBJET d'une tâche réalisée
    comme atteint, sans reprendre la tâche, est signalée EN PLACE (le texte de l'agent est conservé)."""
    en = str(language or "").lower().startswith("en")
    matches = ((editorial.get("meta") or {}).get("brief_status_matches52") or [])
    done = [str(m.get("action") or "").strip() for m in matches if m.get("status") == "DONE" and m.get("action")]
    outs = editorial.get("outputs")
    if not done or not isinstance(outs, MutableMapping):
        return
    rules = []
    for task in done:
        task = re.sub(r"\s+[—–-]\s+.*$", "", task).strip()
        mm = re.match(r"\s*([A-Za-zÀ-ÿœ'’-]+)\s+(.+)", task)
        if not mm:
            continue
        stem = mm.group(1).lower()[:5]
        keys = [w.lower() for w in re.findall(r"[A-Za-zÀ-ÿœ]{5,}", mm.group(2)) if w.lower() not in _SCOPE_STOP61][:4]
        keys += [n for n in re.findall(r"(?<!\d)\d{4}(?!\d)", mm.group(2))][:2]          # « 2030 » : repère de l'objet
        if len(keys) >= 2:
            rules.append((task, stem, keys))
    if not rules:
        return
    done_rx = re.compile(r"(?i)\b(?:r[ée]alis[ée]e?s?|atteinte?s?|achieved|completed|met)\b")
    for role, text in list(outs.items()):
        if not isinstance(text, str) or not text:
            continue
        lines = text.split("\n")
        changed = False
        for i, line in enumerate(lines):
            low = line.lower()
            if not done_rx.search(line) or "portée : seule la tâche" in low or "scope: only the task" in low:
                continue
            for task, stem, keys in rules:
                if sum(1 for k in keys if k in low) >= 2 and stem not in low:
                    lines[i] = line.rstrip() + (f" ⚠ to check — scope: only the task « {task} » was declared completed, "
                                                f"not the achievement of its object" if en else
                                                f" ⚠ à vérifier — portée : seule la tâche « {task} » a été déclarée réalisée, "
                                                f"pas l'atteinte de son objet")
                    changed = True
                    break
        if changed:
            outs[role] = "\n".join(lines)


def filter_numeric_leaks_dates_exempt(leaks: Iterable[Any], result: Mapping[str, Any] | None = None) -> list[Any]:
    """v62.13.7 (H2b) — SEULE exemption du dernier audit numérique PPTX :
    les lignes date-seules (échéances) restaurées par la réparation sémantique.
    Tout autre résidu numérique reste bloquant. Contrat : test_v62137."""
    kept: list[Any] = []
    for item in leaks or []:
        text = str(item.get("text") if isinstance(item, Mapping) else item)
        if _date_only_numeric_line(_norm_space(text)) or _planning_horizon_line(_norm_space(text), result):
            continue
        kept.append(item)
    return kept


def _replace_text_runs(paragraph: Any, new_text: str) -> None:
    if getattr(paragraph, "runs", None):
        paragraph.runs[0].text = new_text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.text = new_text


def _append_after(paragraph: Any, text: str, system: bool = False) -> Any:
    from docx.oxml import OxmlElement
    from docx.text.paragraph import Paragraph
    new_p = OxmlElement("w:p")
    paragraph._p.addnext(new_p)
    p = Paragraph(new_p, paragraph._parent)
    p.add_run(text)
    if system:
        _mark_system_paragraph(p)
    return p


def _mark_system_paragraph(paragraph: Any) -> None:
    """v62.13.9.4.31.1 — un texte que CE module écrit dans le livrable (carte
    d'extractibilité des pièces) est typé « CoDIR System » AU MOMENT où il est
    posé, y compris quand il est ajouté pendant la réparation. C'est le
    mécanisme de la 9.4.21 (utils.system_marks) : les juges de sortie — gate de
    surface, oracle de contenu, neutraliseur de dernier recours, audit de
    qualité — sautent ces paragraphes par leur style, sans lire leur texte.
    Incident du run réel du 11/09/2026 : la carte, posée ici sans ce style, était
    lue par l'oracle comme une assertion d'agent ; le « 18 » d'un nom de pièce
    (« Actes du jj-mm-aaaa.pdf ») y rencontrait une hypothèse déclarée
    « BFR / CA = 18 % » et l'export du Word était retenu. Aucune exception
    nominative (nom de dossier, « 18 », « OCR », « PDF ») : le type suffit.
    """
    try:
        from utils.system_marks import mark_paragraph_system as _mps
        _mps(paragraph)
    except Exception:
        pass


def _extractability_surface_text(scope: Mapping[str, Any], lang: str = "fr") -> str:
    records = list(scope.get("document_extractability") or [])
    text_ok = [x["filename"] for x in records
               if x.get("status") == "TEXT_EXTRACTED" and
               (x.get("financial_statements_detected") or x.get("sections_detected"))]
    partial = [x["filename"] for x in records if x.get("status") == "PARTIALLY_EXTRACTABLE"]
    ocr = [x["filename"] for x in records if x.get("status") == "OCR_REQUIRED"]
    if str(lang).lower().startswith("en"):
        parts = []
        if text_ok:
            parts.append("Financial text extracted: " + "; ".join(text_ok))
        if partial:
            parts.append("Partially extractable — OCR may help: " + "; ".join(partial))
        if ocr:
            parts.append("OCR required — no exploitable financial text: " + "; ".join(ocr))
        return "\n".join(parts)
    parts = []
    if text_ok:
        parts.append("Texte financier extrait : " + "; ".join(text_ok))
    if partial:
        parts.append("Partiellement extractible — OCR potentiellement utile : " + "; ".join(partial))
    if ocr:
        parts.append("OCR requis — aucun texte financier exploitable : " + "; ".join(ocr))
    return "\n".join(parts)


def _is_fact_table(cells: list[str]) -> bool:
    header = " | ".join(cells).lower()
    return (("statut" in header and "fait" in header and "valeur" in header)
            or ("status" in header and "fact" in header and "value" in header))


def _replace_table_row(row: Any, text: str) -> None:
    for idx, cell in enumerate(row.cells):
        cell.text = text if idx == 0 else ""


def _normalize_headcount_band_text(text: str) -> str:
    value = str(text or "")
    # Normalise already-rendered closed ranges first.
    for lo, hi in _V6213942_SIRENE_BANDS:
        value = re.sub(
            rf"\b{lo}\s*[-–—]\s*{hi}\b",
            f"{lo}–{hi}", value,
        )
        value = re.sub(
            rf"(?:tranche\s+{lo}–){2,}{hi}",
            f"tranche {lo}–{hi}", value, flags=re.I,
        )
    value = re.sub(
        r"(?:\s*\(effectif exact non communiqué\)){2,}",
        " (effectif exact non communiqué)", value, flags=re.I,
    )
    # Some registry adapters expose the upper bound as if it were exact. Map
    # only official upper bounds and only in a headcount/salaried context.
    for lo, hi in _V6213942_SIRENE_BANDS:
        pattern = re.compile(
            rf"(?<![\d–—-])\b{hi}\b\s+(?P<noun>salari[ée]s?|employees?|collaborateurs?|employ[ée]s?)\b",
            re.I,
        )
        value = pattern.sub(
            lambda m, lo=lo, hi=hi: f"tranche {lo}–{hi} {m.group('noun')} (effectif exact non communiqué)",
            value,
        )
    return value


def _v6213942_normalize_headcount_text(text: str, profile: Mapping[str, Any] | None = None) -> str:
    value = _normalize_headcount_band_text(text)
    if value != str(text or ""):
        return value
    pair = None
    if isinstance(profile, Mapping):
        for key in ("headcount_range", "headcount_display", "employee_range", "workforce_range"):
            pair = _v6213942_band_pair(profile.get(key))
            if pair:
                break
        if pair is None and not bool(profile.get("headcount_exact")):
            pair = _v6213942_band_from_upper_bound(profile.get("headcount"))
    if pair is None:
        return value
    return re.sub(
        r"(?i)(\b(?:effectif|headcount|salari[ée]s?|collaborateurs?|employees?)\b\s*[:=]?\s*)\d{1,5}\b",
        lambda m: m.group(1) + f"{pair[0]}–{pair[1]} salariés",
        value, count=1,
    )



def _iter_all_docx_paragraphs(doc: Any):
    """Yield body and table-cell paragraphs in document order."""
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph
    for element in doc.element.body.iter():
        if element.tag == qn("w:p"):
            yield Paragraph(element, doc)


def _remove_paragraph(paragraph: Any) -> None:
    element = paragraph._element
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)

def _insert_paragraph_before(paragraph: Any, text: str, style: str | None = None) -> Any:
    from docx.oxml import OxmlElement
    from docx.text.paragraph import Paragraph
    new_p = OxmlElement("w:p")
    paragraph._p.addprevious(new_p)
    created = Paragraph(new_p, paragraph._parent)
    if style:
        try:
            created.style = style
        except Exception:
            pass
    created.add_run(text)
    return created

def _aggregate_docx_fallbacks_and_restore(doc: Any, result: Mapping[str, Any], lang: str) -> dict[str, int]:
    """Aggregate placeholders without blanks and restore only from the true annex."""
    paragraphs = list(doc.paragraphs)
    annex_index = next((i for i, p in enumerate(paragraphs) if _v6213942_is_annex_heading(p.text)), len(paragraphs))
    annex = paragraphs[annex_index] if annex_index < len(paragraphs) else None

    entries: list[dict[str, str]] = []
    for p in paragraphs[annex_index + 1:]:
        parsed = _v6213942_parse_scenario(p.text)
        if parsed:
            # v62.13.9.4.7 — plus d'exception d'annexe : une entrée SCN
            # existante dont le payload reste une cible chiffrée est
            # neutralisée sur place (même juge que le gate), la trace du
            # retrait demeure, la formulation chiffrée disparaît des octets.
            if parsed.get("text") and _should_withhold_line(parsed["text"], result):
                # v62.13.9.4.17 — registre embarqué : l'original reste lisible
                # sous le tag explicite (exempté par les juges), au lieu d'être
                # neutralisé en « détail conservé hors fichier ».
                from utils.quantity_ledger import (SCN_REGISTER_TAG_FR, SCN_REGISTER_TAG_EN,
                                                   is_tagged_register_line, strip_register_tag_from_body)
                from utils.monolingual_rewriter import detect_line_lang as _ml
                if not is_tagged_register_line(p.text):
                    _tag = SCN_REGISTER_TAG_EN if _ml(parsed["text"]) == "en" else SCN_REGISTER_TAG_FR
                    _prefix = f"SCN-{parsed['id']}"
                    if parsed.get("role"):
                        _prefix += f" · {parsed['role']}"
                    _replace_text_runs(p, f"{_prefix} · {_tag} {strip_register_tag_from_body(parsed['text'])}")
            entries.append(parsed)
        else:
            _sq62147 = re.match(
                r"^\s*(?P<tag>\[SERIALIZED QUARANTINE[^\]]*\])\s*(?P<payload>.+)$",
                _norm_space(p.text))
            if _sq62147 and _should_withhold_line(_sq62147.group("payload"), result):
                from utils.quantity_ledger import (SCN_REGISTER_TAG_FR, SCN_REGISTER_TAG_EN,
                                                   is_tagged_register_line, strip_register_tag_from_body)
                from utils.monolingual_rewriter import detect_line_lang as _ml
                if not is_tagged_register_line(_sq62147.group("payload")):
                    _tag = SCN_REGISTER_TAG_EN if _ml(_sq62147.group("payload")) == "en" else SCN_REGISTER_TAG_FR
                    _replace_text_runs(p, f"{_sq62147.group('tag')} {_tag} "
                                          f"{strip_register_tag_from_body(_sq62147.group('payload'))}")
            standalone = _norm_space(p.text)
            if re.search(r"date\s+de\s+fin\s+cible\s*:\s*20\d{2}-\d{2}-\d{2}", standalone, re.I):
                entries.append({"id": "DATE", "role": "planning", "text": standalone})

    fallback_count = 0
    for p in list(paragraphs[:annex_index]):
        text = _norm_space(p.text)
        if text and _V6213942_GENERIC_FALLBACK_RE.match(text):
            _remove_paragraph(p)
            fallback_count += 1

    for table in doc.tables:
        # v62.13.9.4.49 — tableau écrit par le produit (registre, chronologie, table de faits) : non jugé
        if table.rows and _status_mode(result) and _is_product_table_header49([c.text for c in table.rows[0].cells]):
            continue
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    text = _norm_space(p.text)
                    if text and _V6213942_GENERIC_FALLBACK_RE.match(text):
                        _replace_text_runs(p, "Dimensionnement à valider")
                        fallback_count += 1

    paragraphs = list(doc.paragraphs)
    annex_index = next((i for i, p in enumerate(paragraphs) if _v6213942_is_annex_heading(p.text)), len(paragraphs))
    for p in list(paragraphs[annex_index + 1:]):
        text = _norm_space(p.text)
        if not text:
            continue
        technical = _V6213942_ANNEX_TECHNICAL_RE.match(text)
        if technical:
            label, _sep, payload = text.partition(":")
            is_replacement = bool(re.search(r"Remplacement ex[ée]cutif|Executive replacement", label, re.I))
            payload = payload.strip()
            # Preserve a scenario-specific qualitative replacement: it is part
            # of the inherited Word-appendix contract, not a generic warning.
            if is_replacement and payload and not _V6213942_GENERIC_FALLBACK_RE.match(payload):
                _replace_text_runs(p, payload)
            else:
                _remove_paragraph(p)
                fallback_count += 1
            continue
        if _V6213942_GENERIC_FALLBACK_RE.match(text):
            _remove_paragraph(p)
            fallback_count += 1

    treatment_seen = False
    for p in list(doc.paragraphs):
        if _norm_space(p.text).casefold() in (_V6213942_ANNEX_TREATMENT_LINE.casefold(),
                                               _V6213942_ANNEX_TREATMENT_LINE_EN.casefold()):
            if not treatment_seen:
                treatment_seen = True
            else:
                _remove_paragraph(p)
    if annex is not None and fallback_count and not treatment_seen:
        current = list(doc.paragraphs)
        current_annex = next((i for i, p in enumerate(current) if _v6213942_is_annex_heading(p.text)), len(current))
        anchor = next((p for p in current[current_annex + 1:] if _norm_space(p.text).startswith("SCN-")), None)
        if anchor is not None:
            _insert_paragraph_before(anchor, (_V6213942_ANNEX_TREATMENT_LINE_EN if str(lang).lower().startswith("en")
                                              else _V6213942_ANNEX_TREATMENT_LINE), "Normal")

    current = list(doc.paragraphs)
    boundary = next((i for i, p in enumerate(current) if _v6213942_is_annex_heading(p.text)), len(current))
    body_text = "\n".join(p.text for p in current[:boundary])
    body_key = _norm_space(body_text).casefold()
    rd, ceo, date_line = _v6213942_select_restorations(entries, result)
    # v62.13.9.4.50 — en mode statut, l'« orientation recommandée » et la « lecture du dirigeant » restaurées gardent le
    # texte de l'agent (plus de « un calendrier à arbitrer » / « une enveloppe à dimensionner ») ; leurs chiffres non
    # étayés sont étiquetés par la réparation comme tout paragraphe du corps
    if _status_mode(result):
        rd, ceo = (rd or ""), (ceo or "")
        # v62.13.9.4.50 — un passage RESTAURÉ du registre des scénarios arrive après l'étiquetage du corps : il porte
        # lui-même son étiquette s'il contient un chiffre non étayé (rejeu terrain d'un dossier coté britannique : une
        # décision chiffrée restaurée revenait nue dans le corps)
        from utils.quantity_ledger import status_tag as _stag50
        rd = _append_tag49(rd, _stag50("unsupported", lang)) if rd and "⟨statu" not in rd and _should_withhold_line(rd, result) else rd
        ceo = _append_tag49(ceo, _stag50("unsupported", lang)) if ceo and "⟨statu" not in ceo and _should_withhold_line(ceo, result) else ceo
    else:
        rd = _v6213942_rewrite_text(rd, result, lang=lang) if rd else ""
        ceo = _v6213942_rewrite_text(ceo, result, lang=lang) if ceo else ""
    restored: list[str] = []
    if rd and _norm_space(rd).casefold() not in body_key:
        restored.append(rd)
    if ceo and _norm_space(ceo).casefold() not in body_key:
        restored.append(ceo)
    if date_line and not re.search(r"date\s+de\s+fin\s+cible\s*:\s*20\d{2}-\d{2}-\d{2}", body_text, re.I):
        restored.append(date_line)

    for _fact in list(result.get("_v6213943_annex_canonical_facts") or []):
        _fact_line = _norm_space(str(_fact))
        if _fact_line and _fact_line.casefold() not in body_key:
            restored.append(_fact_line)
    social_card = _social_revenue_card(result)
    if social_card:
        social = (
            f"FAIT — SOCIAL · CA social : {social_card['value']} ({social_card['year']}) "
            f"· {social_card.get('source') or 'registre'} · non représentatif du consolidé groupe"
        )
        if social.casefold() not in body_key:
            restored.append(social)
    profile = result.get("company_profile")
    if isinstance(profile, Mapping):
        pair = _v6213942_band_pair(profile.get("headcount_range") or profile.get("headcount_display"))
        if pair:
            headcount = (
                f"FAIT — REGISTRE · Effectif : tranche {pair[0]}–{pair[1]} salariés "
                "(effectif exact non communiqué)"
            )
            if headcount.casefold() not in body_key:
                restored.append(headcount)

    current = list(doc.paragraphs)
    boundary = next((i for i, p in enumerate(current) if _v6213942_is_annex_heading(p.text)), len(current))
    body_values = {_norm_space(p.text).casefold() for p in current[:boundary] if _norm_space(p.text)}
    unique: list[str] = []
    for text in restored:
        cleaned = _norm_space(text)
        if cleaned and cleaned.casefold() not in body_values:
            unique.append(cleaned)
            body_values.add(cleaned.casefold())

    if annex is not None:
        if unique and _V6213942_RESTORED_HEADING.casefold() not in body_values:
            _insert_paragraph_before(annex, _V6213942_RESTORED_HEADING, "Heading 2")
        for text in unique:
            _insert_paragraph_before(annex, text, "Normal")
        if fallback_count and _V6213942_PRUDENCE_NOTE.casefold() not in body_values:
            _insert_paragraph_before(annex, _V6213942_PRUDENCE_NOTE, "Normal")
    else:
        if unique:
            doc.add_heading(_V6213942_RESTORED_HEADING, level=2)
            for text in unique:
                doc.add_paragraph(text)
        if fallback_count and _V6213942_PRUDENCE_NOTE.casefold() not in body_values:
            doc.add_paragraph(_V6213942_PRUDENCE_NOTE)
    return {"restored": len(unique), "fallbacks_aggregated": fallback_count}



_CELL_STATUS_FR = "À dimensionner — baseline requise"
_CELL_STATUS_EN = "To be sized — baseline required"


def _atomic_row_repair(row, lang: str, result, support, residual, force: bool = False) -> bool:
    """v62.13.9.4.21 — répare une rangée cellule par cellule : une cellule
    dont la valeur n'est pas étayée reçoit sa réécriture sans chiffre si elle
    garde des mots, sinon le statut typé ; les autres cellules ne bougent
    pas. ``force`` : toute cellule encore chiffrée reçoit le statut typé.
    Renvoie True si au moins une cellule a été traitée."""
    from utils.board_scrutiny_guard import find_unsupported_executive_numeric_lines
    touched = False
    en = str(lang).lower().startswith("en")
    status = _CELL_STATUS_EN if en else _CELL_STATUS_FR
    for cell in row.cells:
        ct = _norm_space(cell.text)
        if not ct or not re.search(r"\d", ct):
            continue
        if _date_only_numeric_line(ct) or _planning_horizon_line(ct, result):
            continue
        try:
            from utils.quantity_ledger import is_labelled_benchmark_line as _ilbl
            if _ilbl(ct):
                continue
        except Exception:
            pass
        bad = (force or find_unsupported_executive_numeric_lines(
            ct, lang=lang, numeric_support_claims=support,
            authoritative_horizon_values=_QL.build_authority_items(result))
            or _should_withhold_line(ct, result))
        if not bad:
            continue
        if _status_mode(result):
            # v62.13.9.4.22 — document de travail : la cellule garde sa valeur
            # et reçoit son statut ; jamais de placeholder dans une action.
            try:
                from utils.quantity_ledger import status_tag as _stag
                _kind = "declared_target" if _has_declared_target_line(ct, result) else "unsupported"
                rep = ct + " " + _stag(_kind, lang)
            except Exception:
                rep = ct
        else:
            rep = _qualitative_replacement(ct, lang, result)
            if not rep or re.search(r"\d", rep) or len(rep.split()) < 2:
                rep = _sentence_preserving_rewrite(ct, lang) or status
        residual.append({"original": ct, "replacement": rep, "source_type": "table_cell"})
        cell.text = rep
        touched = True
    return touched


_RESERVATION_HEAD37 = re.compile(
    r"(?i)r[ée]serves?|contr[ôo]les?|registre|register|reservations?|limites?|limitations?|"
    r"points?\s+de\s+vigilance|watch\s+signals|evidence|preuve|qualit[ée]|non\s+[ée]tabli|"
    r"mission\s+status|statut\s+de\s+(?:la\s+)?mission|reconciliation|rapprochement|"
    r"financial\s+baseline|base\s+financi[èe]re|page-(?:confirmed|assessed)")


def _withdraw_engine_control_lines_from_active_sections(doc: Any) -> int:
    """v62.13.9.4.37 — un constat du moteur n'a sa place que dans les réserves.

    Runs réels du 18/09/2026 : « Tendance du chiffre d'affaires non établie dans le
    ledger — rapprocher les sources avant calcul » figurait dans le PLAN D'ACTIONS, les
    HYPOTHÈSES DE TRAVAIL et la rubrique DIRECTION GÉNÉRALE ; « Unsupported quantified
    target — baseline and provenance required » dans EXECUTIVE MANAGEMENT et les
    signaux de veille. Ces phrases disent que le produit n'a pas pu établir une
    grandeur ; sous une rubrique d'action ou de décision, elles se lisent comme une
    action ou une décision. Passe finale sur le document : sous toute rubrique qui
    n'est pas une rubrique de réserves ou de contrôle, la ligne est retirée (elle
    reste au registre embarqué du dossier complet).
    """
    try:
        from utils.analysis_objects import is_engine_control_line as _iecl
    except Exception:
        return 0
    removed = 0
    current = ""
    for p in list(doc.paragraphs):
        t = (p.text or "").strip()
        if not t:
            continue
        style = str(getattr(getattr(p, "style", None), "name", "") or "")
        if style.startswith("Heading") or t.isupper() or t.startswith(("§", "\u2063§")):
            current = t
            continue
        if _iecl(t) and not _RESERVATION_HEAD37.search(current):
            p._p.getparent().remove(p._p)
            removed += 1
    return removed


def repair_docx_semantic_truth(docx_bytes: bytes, result: MutableMapping[str, Any]) -> bytes:
    """Final semantic repair for the exact DOCX bytes delivered.

    The function is intentionally downstream of agent generation and upstream
    of the blocking numeric post-control.  It repairs paragraphs *and tables*,
    preserves planning dates, quarantines unsupported quantities/KPIs, applies
    the social-threshold Legal Claim Gate and publishes truthful OCR tri-state
    information without touching the evidence tree.
    """

    # v62.13.9.4.49 — doctrine du 28/09/2026 : en mode statut, un paragraphe fautif garde son texte et reçoit
    # une étiquette dont le motif dit ce que l'ancienne réécriture aurait affirmé ; le rendu le signale.
    def _flag49(par, motif: str) -> None:
        if ("⟨statut" in (par.text or "") or "⟨status" in (par.text or "")
                or "⚠ à vérifier —" in (par.text or "") or "⚠ to verify —" in (par.text or "")):
            return
        word = "status" if str(lang).lower().startswith("en") else "statut"
        _replace_text_runs(par, _norm_space(par.text) + f" ⟨{word} : {motif}⟩")

    def _values_differ49(a: str, b: str) -> bool:
        return _amounts_contradict49(a, b)
    from docx import Document
    from utils.board_scrutiny_guard import find_unsupported_executive_numeric_lines
    from patches.legal_citation_guard import neutralize_unsupported_social_threshold_claims

    doc = Document(BytesIO(docx_bytes))
    _source_paragraphs = list(doc.paragraphs)
    _source_boundary = next((i for i, p in enumerate(_source_paragraphs) if _v6213942_is_annex_heading(p.text)), len(_source_paragraphs))
    _source_body_blank_count = sum(1 for p in _source_paragraphs[:_source_boundary] if not p.text.strip())
    lang = str(result.get("lang") or result.get("language") or "fr").lower()
    scope = financial_scope_summary(result, lang)
    final_score = _final_confidence_score(result)
    support = list(result.get("numeric_support_claims") or result.get("canonical_financial_claims") or [])
    support += _registry_support62427(result)
    annex_seen = False
    residual: list[dict[str, str]] = []
    inserted_extractability = any(
        _v6213942_is_extractability_surface(paragraph.text)
        for paragraph in doc.paragraphs
    )
    legal_count = 0
    trend_count = 0

    _legal_ctx62416: dict = {"threshold_context": 0}   # v62.13.9.4.16 — contexte de seuil inter-paragraphes
    try:                                                 # v62.13.9.4.17 — le tag de registre n'existe qu'en annexe
        from utils.quantity_ledger import strip_register_tag_from_body as _srt62417
    except Exception:
        _srt62417 = None
    try:                                                 # v62.13.9.4.21 — contenu de l'outil typé : jamais réparé
        from utils.system_marks import is_system_paragraph as _isp62421
    except Exception:
        _isp62421 = lambda _p: False   # noqa: E731
    for p in list(doc.paragraphs):
        if _isp62421(p) or "\u2063" in (p.text or ""):
            continue                                     # v62.13.9.4.21/22 — écrit par le produit : jamais réparé
        if ("⟨statut" in (p.text or "") or "⟨status" in (p.text or "")
                or "⚠ à vérifier —" in (p.text or "") or "⚠ to verify —" in (p.text or "")):
            continue                                     # v62.13.9.4.22 — déjà statué : pas de double annotation
        if _srt62417 is not None and not annex_seen and any(
                _k in p.text for _k in ("hors corps]", "off-body]", "en place, à vérifier]", "in place, to verify]")):
            _replace_text_runs(p, _srt62417(p.text))
        t = _norm_space(p.text)
        if not t:
            continue
        if _v6213942_is_annex_heading(t):
            annex_seen = True

        # Consolidated-account status, including the old bare card/line.
        # v62.13.9.4.33 (lot 1) — SEULE UNE CARTE DU PRODUIT est reconnue comme
        # carte : l'ancienne forme nue (« Comptes consolidés groupe fournis :
        # oui/non ») ou la carte de périmètre elle-même. Contre-audit du
        # 12/09/2026 (run réel bf7167) : « Reconstituer les comptes consolidés
        # groupe 2024-2025 (…) — DAF · 31/10/2026 » contenait « comptes
        # consolidés » et un deux-points ; l'action, ses porteurs et son
        # échéance étaient remplacés cinq fois par la carte de statut. Une phrase
        # d'action — verbe, porteur, date — n'est jamais une carte.
        if _is_product_consolidation_card(t):
            is_en = lang.startswith("en")
            if scope["group_consolidated_accounts_provided"]:
                repl = ("Structured financial statements detected: yes · Perimeter: consolidated group · Group consolidated accounts provided: yes — page-confirmed facts"
                        if is_en else
                        "États financiers structurés détectés : oui · Périmètre : groupe consolidé · Comptes consolidés groupe fournis : oui — faits page-confirmés")
            elif scope.get("structured_statements_detected"):
                repl = ("Structured financial statements detected: yes · Perimeter: standalone/to confirm · Group consolidated accounts provided: not established"
                        if is_en else
                        "États financiers structurés détectés : oui · Périmètre : social/à confirmer · Comptes consolidés groupe fournis : non établis")
            else:
                # v62.13.9.4.21 — contre-audit du 05/09/2026, point 7 : sans pièce
                # financière, dire « états financiers détectés : oui » contredit
                # « aucune pièce jointe ». Les données de registre sont des
                # données de registre, pas des états financiers.
                repl = ("Structured registry data detected: yes · Financial statements from attachments: none · Perimeter: standalone/to confirm"
                        if is_en else
                        "Données de registre structurées détectées : oui · États financiers issus de pièces jointes : non · Périmètre : social/à confirmer")
            _replace_text_runs(p, repl)
            if not inserted_extractability:
                extra = _extractability_surface_text(scope, lang)
                if extra:
                    _append_after(p, extra, system=True)   # v62.13.9.4.31.1 — typée à la création
                inserted_extractability = True
            continue

        if "États financiers structurés détectés" in t and ("Cash Flow" in t or "Notes extraits" in t):
            secs = ", ".join(scope["detected_sections"]) or "sections consignées dans le diagnostic"
            _replace_text_runs(p, f"États financiers structurés détectés — sections réellement détectées : {secs}.")
            continue

        if re.search(r"(?:Pièces financières non lisibles sans OCR|Financial documents unreadable without OCR)", t, re.I):
            # The old binary list is replaced by the tri-state inventory.  If
            # the tri-state was already inserted after the scope paragraph,
            # remove this obsolete duplicate.
            if inserted_extractability:
                _remove_paragraph(p)
            else:
                _replace_text_runs(p, _extractability_surface_text(scope, lang))
                _mark_system_paragraph(p)                  # v62.13.9.4.31.1 — typée à la création
                inserted_extractability = True
            continue

        if _v6213942_is_extractability_surface(p.text):
            _mark_system_paragraph(p)                      # v62.13.9.4.31.1 — carte déjà présente : typée aussi
            continue

        normalized_headcount = _normalize_headcount_band_text(p.text)
        if normalized_headcount != p.text:
            if _status_mode(result):                     # v62.13.9.4.49 — signaler, ne pas réécrire
                # audit du 29/09/2026 : un simple tiret normalisé (« 3-5 pilot distributors ») n'est pas une
                # question d'effectif ; seule la substitution d'un effectif exact par une tranche est signalée
                _band49 = re.search(r"tranche\s+(\d+[–-]\d+)", normalized_headcount, re.I)
                if _band49 and "effectif exact non communiqué" in normalized_headcount and \
                        "effectif exact non communiqué" not in p.text:
                    _flag49(p, ("exact headcount not proven — register band: " if str(lang).startswith("en")
                                else "effectif exact non prouvé — tranche du registre : ") + _band49.group(1))
            else:
                _replace_text_runs(p, normalized_headcount)
                t = _norm_space(normalized_headcount)
        # Legal Claim Gate — no unsupported threshold/consequence/action survives.
        legal_text, legal_findings = neutralize_unsupported_social_threshold_claims(
            p.text, lang=lang, profile=(result or {}).get("company_profile"),
            context_state=_legal_ctx62416)
        if legal_findings:
            legal_count += len(legal_findings)
            if _status_mode(result):                     # v62.13.9.4.49 — signaler, ne pas réécrire
                _flag49(p, "social threshold not proven" if str(lang).startswith("en") else "seuil social non prouvé")
            else:
                _replace_text_runs(p, legal_text)
            result.setdefault("v62139_legal_claims_withheld", []).extend(legal_findings)
            continue

        if _FALSE_LEGAL_FR.lower() in t.lower() and _legal_scrub_evidenced(result):
            new = re.sub(re.escape(_FALSE_LEGAL_FR), "", p.text, flags=re.I)
            new = re.sub(r"\s*;\s*;", ";", new)
            _replace_text_runs(p, new.strip(" ;,()"))
            continue
        if final_score is not None and re.search(r"Étapes\s+du\s+score", t, re.I):
            new = re.sub(r"(preuve\s+finale\s+)\d+(?:[.,]\d+)?/100", lambda m: m.group(1) + f"{int(round(final_score))}/100", p.text, flags=re.I)
            _replace_text_runs(p, new)
            continue
        if final_score is not None and final_score < 60 and re.search(r"Preuve\s+étayée", t, re.I):
            _replace_text_runs(p, "Preuve insuffisante — usage exploratoire uniquement")
            continue
        if _cross_metric_collision(t, result):
            _fam = _metric_family(t)
            _label = {"inventories": "des stocks", "revenue": "du chiffre d’affaires", "net_income": "du résultat net", "equity": "des capitaux propres"}.get(_fam, "de la métrique")
            if _status_mode(result):                     # v62.13.9.4.49 — signaler, ne pas réécrire
                _flag49(p, f"valeur {_label} non établie dans les pièces exploitables")
            else:
                _replace_text_runs(p, f"Valeur {_label} non établie dans les pièces exploitables — à vérifier.")
            continue
        if _unsupported_revenue_trend(t, result):
            trend_count += 1
            # v62.13.9.4.12 — localité par montant : la neutralisation de
            # tendance visait la ligne entière et emportait un constat daté
            # voisin (« le CA était de 15 M€ en 2025 ; le plan vise… »). On
            # isole d'abord la proposition fautive.
            # v62.13.9.4.25 — puis localité par PHRASE : un paragraphe de
            # plusieurs phrases ne devient pas une réserve d'une ligne.
            _loc62412 = _rule_local_rewrite(t, lang, result, support, _unsupported_revenue_trend,
                                            "Tendance du chiffre d’affaires non établie dans le ledger — rapprocher les sources avant calcul.")
            if _loc62412 is None:
                _loc62412 = _clause_local_rewrite(
                    t, lang, result,
                    verdict=lambda c: (_unsupported_revenue_trend(c, result)
                                       or _should_withhold_line(c, result)))
            if _status_mode(result):                     # v62.13.9.4.49 — signaler, ne pas réécrire
                _flag49(p, "revenue trend not established in the documents" if str(lang).startswith("en")
                        else "tendance du chiffre d’affaires non établie dans les pièces")
            else:
                _replace_text_runs(p, _loc62412 or
                                   "Tendance du chiffre d’affaires non établie dans le ledger — rapprocher les sources avant calcul.")
            continue
        if _unsupported_market_growth(t, result):
            trend_count += 1
            _mg62425 = _MARKET_GROWTH_EN if str(lang).lower().startswith("en") else _MARKET_GROWTH_FR
            _loc62425 = _rule_local_rewrite(t, lang, result, support, _unsupported_market_growth, _mg62425)
            if _loc62425 is None:
                _loc62425 = _clause_local_rewrite(
                    t, lang, result,
                    verdict=lambda c: (_unsupported_market_growth(c, result)
                                       or _should_withhold_line(c, result)))
            if _status_mode(result):                     # v62.13.9.4.49 — signaler, ne pas réécrire
                _flag49(p, "unsourced market growth" if str(lang).startswith("en") else "croissance de marché non sourcée")
            else:
                _replace_text_runs(p, _loc62425 or _mg62425)
            continue
        canonical_fact = _canonical_fact_line(t, result)
        if canonical_fact:
            if annex_seen:
                # v62.13.9.4.3 — un fait page-confirmé n'est jamais un scénario :
                # la ligne d'annexe est retirée et le fait remonte en section restaurée.
                result.setdefault("_v6213943_annex_canonical_facts", []).append(canonical_fact)
                _remove_paragraph(p)
            elif _status_mode(result):
                # v62.13.9.4.49 — la ligne de l'agent reste ; si ses montants diffèrent du fait confirmé,
                # la formulation de la pièce est affichée à côté (jamais substituée en silence).
                if _values_differ49(t, canonical_fact) and _amounts_contradict49(t, canonical_fact):   # 9.4.60 — F59-05
                    _flag49(p, ("contradicted by the source: " if str(lang).startswith("en")
                                else "contredit par la pièce : ") + _norm_space(canonical_fact)[:100])
            else:
                _replace_text_runs(p, canonical_fact)
            continue
        if annex_seen or _date_only_numeric_line(t) or _planning_horizon_line(t, result):
            continue
        hits = find_unsupported_executive_numeric_lines(t, lang=lang, numeric_support_claims=support,
                authoritative_horizon_values=_QL.build_authority_items(result))
        if ("⚠ à vérifier —" in t or "⚠ to verify —" in t) and _status_mode(result):
            continue          # v62.13.9.4.50 — passage déjà SIGNALÉ (marqueur rendu) : jamais rejugé (idempotence)
        if hits or _should_withhold_line(t, result):
            _is_head = _v6213943_is_heading_paragraph(p)
            # v62.13.9.4.49 — audit du 29/09/2026 : un titre n'est jamais signalé (numérotation « A.2 », « B.2 »),
            # et le texte du dirigeant (écho du brief) non plus — la mention unique des cibles du brief suffit
            # (un titre n'est exempté que si ses seuls chiffres sont sa NUMÉROTATION : « 3. Plan réseau : ouvrir 20
            # … » porte une vraie cible et reste signalé — contrat d'invariant de sortie)
            _rest49 = re.sub(r"^\s*(?:§\s*\d+(?:\.\d+)*|[A-Z]\.\d+(?:\.\d+)*|\d+(?:\.\d+)*[.)]?)\s*[—–:\-]?\s*", "", t)
            if _status_mode(result) and ((_is_head and not re.search(r"\d", _rest49)) or _is_brief_echo49(t, result)):
                continue
            # v62.13.9.4.21 — mode statut (document de travail) : le paragraphe
            # reste, son statut le suit ; jamais sur un mensonge de registre.
            if _status_mode(result) and _contradicts_registry62413(t, result):
                _flag49(p, "contradicted by the register" if str(lang).startswith("en") else "contredit par le registre")
                continue                                  # v62.13.9.4.49 — signaler aussi le mensonge de registre
            if _status_mode(result) and not _contradicts_registry62413(t, result):
                try:
                    from utils.quantity_ledger import status_tag as _stag
                    _kind = "declared_target" if _has_declared_target_line(t, result) else "unsupported"
                    _replace_text_runs(p, _norm_space(p.text) + " " + _stag(_kind, lang))
                    residual.append({"original": t, "replacement": _norm_space(p.text), "source_type": "paragraph",
                                     "status": "STATUS_TAGGED_V62421"})
                    continue
                except Exception:
                    pass
            # localité par montant : on tente d'abord d'isoler la seule
            # proposition fautive, pour ne pas emporter un fait avec elle.
            replacement = None
            if not _is_head:
                replacement = _clause_local_rewrite(p.text, lang, result)
            if replacement is None:
                replacement = _qualitative_replacement(p.text, lang, result, is_heading=_is_head)
            if replacement is None:
                replacement = _sentence_preserving_rewrite(p.text, lang)   # v62.13.9.4.22 — la phrase reste
            if replacement is None:
                residual.append({"original": p.text, "replacement": (_V6213943_REMOVED_MARK_EN if str(lang).lower().startswith("en") else _V6213943_REMOVED_MARK), "source_type": "paragraph"})
                _remove_paragraph(p)
            else:
                residual.append({"original": p.text, "replacement": replacement, "source_type": "paragraph"})
                _replace_text_runs(p, replacement)

    # Tables — the prior implementation only handled facts; v62.13.9.2 closes
    # action/KPI tables and legal-threshold tables too.
    seen_fact_keys: set[tuple[str, str]] = set()
    for table in list(doc.tables):
        # v62.13.9.4.49 — registre des actions et chronologie multi-séances : tableaux du produit, non jugés
        if table.rows and _status_mode(result) and _is_product_table_header49([c.text for c in table.rows[0].cells]) \
                and not _is_fact_table([_norm_space(c.text) for c in table.rows[0].cells]):
            continue
        rows = list(table.rows)
        if not rows:
            continue
        header_cells = [_norm_space(c.text) for c in rows[0].cells]
        fact_table = _is_fact_table(header_cells)
        for row_index, row in enumerate(list(table.rows)):
            if any(_isp62421(pp) for c in row.cells for pp in c.paragraphs):
                continue                                 # v62.13.9.4.21 — tableau de l'outil
            cells = [_norm_space(c.text) for c in row.cells]
            rendered = " | ".join(x for x in cells if x)
            if not rendered:
                continue
            if row_index == 0:
                continue
            if any("\u2063" in (c.text or "") for c in row.cells):
                continue                                 # v62.13.9.4.22 — rangée écrite par le produit (cartes de score)
            # v62.13.9.4.18 — rangée de marché sourcée et étiquetée benchmark :
            # aucune cellule n'est neutralisée (le chiffre reste, étiqueté).
            try:
                from utils.quantity_ledger import is_labelled_benchmark_line as _ilbl62418r
                if _ilbl62418r(rendered):
                    continue
            except Exception:
                pass
            legal_text, legal_findings = neutralize_unsupported_social_threshold_claims(rendered, lang=lang)
            if legal_findings:
                legal_count += len(legal_findings)
                concise = ("Headcount band — obligations to qualify with HR / employment counsel."
                           if lang.startswith("en") else
                           "Tranche d’effectif — obligations à qualifier avec DRH / conseil social.")
                _replace_table_row(row, concise)
                result.setdefault("v62139_legal_claims_withheld", []).extend(legal_findings)
                continue
            if fact_table:
                metric = cells[1] if len(cells) > 1 else ""
                value = cells[2] if len(cells) > 2 else ""
                family = _metric_family(metric) or metric.lower()
                key = (str(family), _norm_number_token(value))
                handled62148 = False
                # 9.4.51 — contre-recette du 03/10/2026 : les branches héritées qui visaient une VALEUR (« 10 » de stocks) et
                # une ANNÉE (« 2021 » de chiffre d'affaires) d'un dossier passé sont retirées. Une rangée non certifiée reçoit
                # la règle générale (valeur conservée, mention « à confirmer sur pièce »), quel que soit le dossier.
                if family == "headcount":
                    pair = _v6213942_band_pair(value) or _v6213942_band_from_upper_bound(
                        re.sub(r"\s*(?:salari[ée]s?|employees?|collaborateurs?|employ[ée]s?)\s*$", "", value, flags=re.I)
                    )
                    if pair:
                        row.cells[2].text = f"{pair[0]}–{pair[1]} salariés (tranche ; exact non communiqué)"
                        handled62148 = True
                if family == "net_income" and key in seen_fact_keys and ("Net income" in metric or "Résultat net" in metric):
                    row._element.getparent().remove(row._element)
                    continue
                _neutralize_uncertified_amount_cells(row, rendered, lang, residual, result)
                seen_fact_keys.add(key)
                # v62.13.9.4.8 (terrain réel du 13/08/2026) — une rangée de
                # fact-table NON confirmée et non traitée par un cas dédié
                # passe au jugement général de rangée : le « continue »
                # aveugle laissait des grandeurs non prouvées en annexe.
                if (handled62148
                        or _row_bound_to_claim(rendered, result)
                        or _fact_row_in_engine_ledger(cells, rendered, result)):
                    continue
                rendered = " | ".join(
                    _norm_space(c.text) for c in row.cells if _norm_space(c.text))
                if not rendered:
                    continue
            if _neutralize_uncertified_amount_cells(row, rendered, lang, residual, result):
                continue
            # v62.13.9.4.9 — l'exemption de rangée est liée au CLAIM, jamais
            # au tag : « ✅ FAIT | Effectif | 0 salariés | Pappers | — » reste
            # exemptée parce que le run porte le claim de registre, tandis que
            # « CONFIRMED | Budget cible | 24 M€ | source.pdf | 3 » repart au
            # jugement (contre-audit 30/08/2026, P1-948-02).
            if _row_bound_to_claim(rendered, result):
                continue
            if _unsupported_revenue_trend(rendered, result) or _unsupported_market_growth(rendered, result):
                # v62.13.9.4.25 — contre-audit v24 (§3, CR) : « Audit pipeline et
                # définition CA cible | Robin SAUZET | 2026-09-30 | … » perdait
                # responsable, date et livrable. La rangée garde ses cellules ;
                # seule la cellule qui porte la tendance ou la croissance non
                # étayée est statuée (document de travail) ou réécrite (synthèse).
                trend_count += 1
                _rule62425 = (_unsupported_revenue_trend if _unsupported_revenue_trend(rendered, result)
                              else _unsupported_market_growth)
                _res62425 = ("Tendance du chiffre d’affaires non établie dans le ledger — rapprochement requis."
                             if _rule62425 is _unsupported_revenue_trend
                             else (_MARKET_GROWTH_EN if lang.startswith("en") else _MARKET_GROWTH_FR))
                _touched62425 = False
                _rule_cells62425: list = []
                for _c62425 in row.cells:
                    _ct62425 = _norm_space(_c62425.text)
                    if not _ct62425 or not _rule62425(_ct62425, result):
                        continue
                    _rule_cells62425.append(_c62425)
                    if _status_mode(result):
                        try:
                            from utils.quantity_ledger import status_tag as _stag
                            _kind49 = "trend" if _rule62425 is _unsupported_revenue_trend else "market"
                            _c62425.text = _ct62425 + " " + _stag(_kind49, lang)
                            # v62.13.9.4.49 — la VALEUR de la rangée porte aussi le statut (campagne réelle de
                            # référence : la valeur restait nue dans sa cellule, le libellé seul étant étiqueté) ;
                            # une année seule n'est pas une valeur
                            for _cv49 in row.cells:
                                _tv49 = _norm_space(_cv49.text)
                                if (_cv49._tc is not _c62425._tc and _tv49 and "⟨" not in _tv49
                                        and re.search(r"\d", _tv49) and not re.fullmatch(r"(?:19|20)\d{2}", _tv49)):
                                    _cv49.text = _tv49 + " " + _stag(_kind49, lang)
                        except Exception:
                            _c62425.text = _ct62425
                    else:
                        _rep62425 = _clause_local_rewrite(
                            _ct62425, lang, result,
                            verdict=lambda c: (_rule62425(c, result) or _should_withhold_line(c, result)))
                        if _rep62425 is None:
                            _rep62425 = _qualitative_replacement(_ct62425, lang, result)
                        _c62425.text = _rep62425 or _res62425
                    _touched62425 = True
                if not _touched62425:
                    # la règle ne tient qu'à la rangée entière (années réparties
                    # sur plusieurs cellules) : statut sur la première cellule
                    # en mode travail, sinon repli d'avant.
                    if _status_mode(result):
                        try:
                            from utils.quantity_ledger import status_tag as _stag
                            _first49 = None
                            for _c62425 in row.cells:
                                if _norm_space(_c62425.text):
                                    _c62425.text = _norm_space(_c62425.text) + " " + _stag("trend", lang)
                                    _first49 = _c62425
                                    break
                            # v62.13.9.4.49 — la valeur de croissance de la rangée (taux ou nombre signé) porte aussi
                            # le statut (campagne réelle de référence : la valeur restait nue) ; ni année ni zéro
                            for _cv49 in row.cells:
                                _tv49 = _norm_space(_cv49.text)
                                if (_first49 is not None and _cv49._tc is not _first49._tc and _tv49 and "⟨" not in _tv49
                                        and re.search(r"[+−-]\s?\d|\d\s?%", _tv49)
                                        and not re.fullmatch(r"(?:19|20)\d{2}", _tv49)):
                                    _cv49.text = _tv49 + " " + _stag("trend", lang)
                            _touched62425 = True
                        except Exception:
                            pass
                    if not _touched62425:
                        _replace_table_row(row, _res62425)
                # Les AUTRES cellules de la rangée restent jugées une à une (parité
                # avec le chemin général) : la rangée entière disparaissait avec sa
                # cellule « 4 h » ; conservée, cette cellule doit porter son statut.
                for _c62425 in row.cells:
                    if any(_c62425._tc is _rc._tc for _rc in _rule_cells62425):
                        continue
                    _ct62425 = _norm_space(_c62425.text)
                    if (not _ct62425 or "⟨" in _ct62425 or _date_only_numeric_line(_ct62425)
                            or _planning_horizon_line(_ct62425, result)):
                        continue
                    _ch62425 = find_unsupported_executive_numeric_lines(
                        _ct62425, lang=lang, numeric_support_claims=support,
                        authoritative_horizon_values=_QL.build_authority_items(result))
                    if not (_ch62425 or _should_withhold_line(_ct62425, result)):
                        continue
                    if _status_mode(result):
                        try:
                            from utils.quantity_ledger import status_tag as _stag
                            _cr62425 = _ct62425 + " " + _stag(
                                "declared_target" if _has_declared_target_line(_ct62425, result) else "unsupported", lang)
                        except Exception:
                            _cr62425 = _ct62425
                    else:
                        _cr62425 = _qualitative_replacement(_ct62425, lang, result)
                        if _cr62425 is None:
                            _cr62425 = _sentence_preserving_rewrite(_ct62425, lang)
                        if _cr62425 is None:
                            _cr62425 = (_V6213943_TABLE_PLACEHOLDER_EN if lang.startswith("en")
                                        else _V6213943_TABLE_PLACEHOLDER_FR)
                    residual.append({"original": _ct62425, "replacement": _cr62425, "source_type": "table_cell"})
                    _c62425.text = _cr62425
                residual.append({"original": rendered,
                                 "replacement": " | ".join(_norm_space(c.text) for c in row.cells if _norm_space(c.text)),
                                 "source_type": "table_row_cells",
                                 "status": "STATUS_TAGGED_V62421" if _status_mode(result) else "RULE_LOCAL_V62425"})
                continue
            canonical_fact = _canonical_fact_line(rendered, result)
            if canonical_fact:
                _replace_table_row(row, canonical_fact)
                continue
            if _date_only_numeric_line(rendered) or _planning_horizon_line(rendered, result):
                continue
            # v62.13.9.4.49 — IDEMPOTENCE : une rangée déjà statuée (au moins une cellule étiquetée) n'est pas
            # rejugée ; sans cela, le second passage étiquetait le libellé de la rangée (contrat du rejeu réel).
            if _status_mode(result) and ("⟨statut" in rendered or "⟨status" in rendered
                                         or "⚠ à vérifier —" in rendered or "⚠ to verify —" in rendered):
                continue
            hits = find_unsupported_executive_numeric_lines(rendered, lang=lang, numeric_support_claims=support,
                authoritative_horizon_values=_QL.build_authority_items(result))
            if hits or _should_withhold_line(rendered, result):
                # v62.13.9.4.21 — ATOMICITÉ DES RANGÉES (contre-audit ChatGPT du
                # 05/09/2026, point 2) : une rangée d'action garde son libellé,
                # son porteur, son échéance et son statut ; SEULES les cellules
                # qui portent une valeur non étayée reçoivent un statut typé.
                # Plus jamais « Élément chiffré retiré du tableau » à la place
                # d'une action entière.
                _touched62421 = _atomic_row_repair(row, lang, result, support, residual)
                if not _touched62421 and _status_mode(result):
                    # v62.13.9.4.22 — document de travail : la première cellule
                    # non vide porte le statut de la rangée ; rien n'est vidé.
                    try:
                        from utils.quantity_ledger import status_tag as _stag
                        for _c in row.cells:
                            if _norm_space(_c.text):
                                _c.text = _norm_space(_c.text) + " " + _stag("unsupported", lang)
                                break
                        residual.append({"original": rendered, "replacement": rendered, "source_type": "table_row",
                                         "status": "STATUS_TAGGED_V62421"})
                        _touched62421 = True
                    except Exception:
                        pass
                if not _touched62421:
                    # aucune cellule chiffrée isolable : repli d'avant, tracé
                    replacement = _qualitative_replacement(rendered, lang, result)
                    if replacement is None:
                        replacement = _sentence_preserving_rewrite(rendered, lang)
                    if replacement is None:
                        replacement = _V6213943_TABLE_PLACEHOLDER_EN if lang.startswith("en") else _V6213943_TABLE_PLACEHOLDER_FR
                    residual.append({"original": rendered, "replacement": replacement, "source_type": "table_row"})
                    _replace_table_row(row, replacement)
                else:
                    residual.append({"original": rendered, "replacement": " | ".join(_norm_space(c.text) for c in row.cells if _norm_space(c.text)),
                                     "source_type": "table_row_cells"})
            else:
                # v62.13.9.4.8 — parité de granularité avec l'oracle runtime :
                # les cellules d'une rangée NON confirmée sont jugées une à
                # une. La dilution du jugement de rangée laissait passer des
                # cibles (« Gain net +5-10% », « 50/50 » sous colonne Cible,
                # « 450.0 … non sourcé » — terrain réel du 13/08/2026).
                _cells_touched62415 = False
                for _cell62148 in row.cells:
                    _ct62148 = _norm_space(_cell62148.text)
                    if (not _ct62148 or _date_only_numeric_line(_ct62148)
                            or _planning_horizon_line(_ct62148, result)):
                        continue
                    _ch62148 = find_unsupported_executive_numeric_lines(
                        _ct62148, lang=lang, numeric_support_claims=support,
                        authoritative_horizon_values=_QL.build_authority_items(result))
                    if _ch62148 or _should_withhold_line(_ct62148, result):
                        if _status_mode(result):
                            try:
                                from utils.quantity_ledger import status_tag as _stag
                                _cr62148 = _ct62148 + " " + _stag(
                                    "declared_target" if _has_declared_target_line(_ct62148, result) else "unsupported", lang)
                            except Exception:
                                _cr62148 = _ct62148
                        else:
                            _cr62148 = _qualitative_replacement(_ct62148, lang, result)
                            if _cr62148 is None:
                                _cr62148 = _sentence_preserving_rewrite(_ct62148, lang)
                        if _cr62148 is None:
                            _cr62148 = (_V6213943_TABLE_PLACEHOLDER_EN
                                        if lang.startswith("en")
                                        else _V6213943_TABLE_PLACEHOLDER_FR)
                        residual.append({"original": _ct62148,
                                         "replacement": _cr62148,
                                         "source_type": "table_cell"})
                        _cell62148.text = _cr62148
                        _cells_touched62415 = True
                # v62.13.9.4.15 — CONVERGENCE DE LA RÉPARATION DE RANGÉE. Le
                # run réel du 02/09/2026 15:04 : la rangée A3.4 passait le
                # juge en forme longue, la neutralisation d'une cellule la
                # raccourcissait, et l'oracle rejugeait la rangée RÉSIDUELLE
                # fautive (« 3 clients », « 0 € ») → export bloqué sur le
                # propre résidu de la réparation. La rangée réparée est donc
                # rejugée ; si elle échoue encore, elle est retenue entière.
                if _cells_touched62415:
                    _re62415 = " | ".join(
                        _norm_space(c.text) for c in row.cells if _norm_space(c.text))
                    _rh62415 = find_unsupported_executive_numeric_lines(
                        _re62415, lang=lang, numeric_support_claims=support,
                        authoritative_horizon_values=_QL.build_authority_items(result))
                    if _re62415 and (_rh62415 or _should_withhold_line(_re62415, result)):
                        # v62.13.9.4.21 — convergence SANS perdre la rangée : seconde
                        # passe cellule par cellule sur le résidu ; la rangée entière
                        # n'est remplacée que si aucune cellule ne peut l'être.
                        if not _atomic_row_repair(row, lang, result, support, residual, force=True):
                            _rr62415 = _qualitative_replacement(_re62415, lang, result)
                            if _rr62415 is None:
                                _rr62415 = (_V6213943_TABLE_PLACEHOLDER_EN
                                            if lang.startswith("en")
                                            else _V6213943_TABLE_PLACEHOLDER_FR)
                            residual.append({"original": _re62415,
                                             "replacement": _rr62415,
                                             "source_type": "table_row"})
                            _replace_table_row(row, _rr62415)

    # Final global pass also covers nested table-cell paragraphs, which are
    # not exposed by ``Document.paragraphs`` or top-level ``Document.tables``.
    global_annex = False
    for paragraph in _iter_all_docx_paragraphs(doc):
        current = _norm_space(paragraph.text)
        if not current:
            continue
        if re.search(r"(?:Annexe\s+[—-]\s+(?:Scénarios|Unvalidated quantified)|Complément v62\.13\.|"
                     r"Registre des passages signalés|Register of flagged passages)", current, re.I):
            global_annex = True
        if global_annex:
            continue
        normalized = _normalize_headcount_band_text(paragraph.text)
        legal_text, legal_findings = neutralize_unsupported_social_threshold_claims(normalized, lang=lang)
        if legal_findings:
            legal_count += len(legal_findings)
            result.setdefault("v62139_legal_claims_withheld", []).extend(legal_findings)
            _replace_text_runs(paragraph, legal_text)
        elif normalized != paragraph.text:
            _replace_text_runs(paragraph, normalized)

    # v62.13.9.4.17 — REGISTRE EMBARQUÉ (contre-audit ChatGPT du 03/09/2026,
    # point 7 ; amendement déclaré de no_annex_exception du 30/08/2026). Le
    # contre-auditeur constatait que l'annexe ne conservait « que la trace
    # qu'une suppression a eu lieu » et renvoyait le consultant aux sorties
    # brutes. Chaque entrée porte désormais : l'ORIGINAL sous tag explicite
    # (exempté par les quatre juges, retiré de tout texte de corps), le
    # statut de preuve, la source (section), la raison du retrait et la
    # décision requise. Le chiffre est lisible là, et seulement là.
    _embedded62417 = list(residual) + [
        {"original": s.get("original", ""), "replacement": s.get("replacement", ""),
         "source_type": "text", "section": s.get("section", "")}
        for s in (result.get("v62136_withheld_scenarios") or [])
        if isinstance(s, dict) and s.get("original")]
    _seen62417: set[str] = set()
    _dedup62417 = []
    from utils.quantity_ledger import REGISTER_HEADINGS_RE as _RHR49
    _register_exists62417 = any(_RHR49.search(p.text or "") for p in doc.paragraphs)
    from utils.quantity_ledger import is_tagged_register_line as _itrl62417b
    for item in _embedded62417:
        key = _norm_space(str(item.get("original") or ""))
        if not key or key in _seen62417:
            continue
        # idempotence : une ligne du registre, un titre d'annexe ou une ligne
        # technique d'annexe ne redeviennent jamais des entrées.
        if (_itrl62417b(key) or _v6213942_is_annex_heading(key)
                or _V6213942_ANNEX_TECHNICAL_RE.match(key)
                or re.match(r"^\s*(?:Statut de preuve|Proof status|Source|Raison du retrait|Reason|"
                            r"Remplacement dans le corps|Body replacement|Décision requise|Decision required)\s*:", key)
                or re.match(r"^\s*SCN-", key)):
            continue
        _seen62417.add(key)
        _dedup62417.append(item)
    # v62.13.9.4.50 — décision Robin du 30/09/2026 : en mode statut, le registre ne sort plus en annexe du Word (il
    # dupliquait les passages signalés en place et disait encore « ligne retirée du corps ») ; le registre complet
    # reste dans le fichier probatoire (JSON/CSV) et le diagnostic du paquet.
    if _dedup62417 and not _register_exists62417 and _status_mode(result):
        try:
            _write_register_sidecar(_dedup62417, lang, result)   # registre probatoire complet (JSON + CSV)
        except Exception:
            pass
        _dedup62417 = []
    if _dedup62417 and not _register_exists62417:
        from utils.quantity_ledger import SCN_REGISTER_TAG_FR, SCN_REGISTER_TAG_EN, strip_register_tag_from_body
        _en62417 = str(lang).lower().startswith("en")
        _tag62417 = SCN_REGISTER_TAG_EN if _en62417 else SCN_REGISTER_TAG_FR
        # v62.13.9.4.21 — LE REGISTRE EXHAUSTIF SORT DU WORD (décision Robin du
        # 05/09/2026 ; contre-audit ChatGPT point 3 : « le registre a absorbé le
        # document » — 71 % des 73 pages). Il est écrit dans un fichier
        # probatoire (JSON + CSV, à côté du dossier de run) ; le Word ne garde
        # qu'une ANNEXE HUMAINE dédupliquée, limitée aux hypothèses
        # réellement arbitrables (au plus _HUMAN_ANNEX_MAX), avec renvoi au
        # fichier. Le dossier de run porte le chemin du fichier.
        _sidecar62421 = _write_register_sidecar(_dedup62417, lang, result)
        _arbitrable62421 = _select_arbitrable(_dedup62417, _HUMAN_ANNEX_MAX)
        # v62.13.9.4.49 — plus aucun numéro de version interne dans un livrable (audit du 29/09/2026)
        doc.add_paragraph("\u2063Registre des passages signalés — hypothèses à arbitrer "
                          "(texte d'origine, statut de preuve, source, décision attendue)"
                          if not _en62417 else
                          "\u2063Register of flagged passages — hypotheses to arbitrate "
                          "(original text, proof status, source, decision required)")
        if _sidecar62421:
            doc.add_paragraph(("\u2063" + f"Registre exhaustif ({len(_dedup62417)} entrées) : fichier probatoire "
                               f"{_sidecar62421['json']} (JSON) et {_sidecar62421['csv']} (CSV), à côté du dossier de run."
                               if not _en62417 else
                               "\u2063" + f"Exhaustive register ({len(_dedup62417)} entries): evidence file "
                               f"{_sidecar62421['json']} (JSON) and {_sidecar62421['csv']} (CSV), next to the run dossier."))
        for idx, item in enumerate(_arbitrable62421, 1):
            _orig62417 = strip_register_tag_from_body(str(item.get("original") or ""))
            _src62417 = str(item.get("section") or item.get("source_type") or "corps du document")
            doc.add_paragraph(f"SCN-V62139-{idx:03d} · {_tag62417} {_orig62417}")
            # v62.13.9.4.23 — entrée compacte (trois lignes) : statut + source,
            # remplacement, décision requise. Le détail exhaustif est dans le sidecar.
            doc.add_paragraph(("Statut : non validé — non rattaché à une pièce · Source : " + _src62417
                               if not _en62417 else
                               "Status: unvalidated — not tied to a source document · Source: " + _src62417))
            # v62.13.9.4.18.2 — le remplacement affiché ne porte jamais de
            # chiffre ni de titre : le run réel du 03/09/2026 15:53 a été
            # bloqué sur « Remplacement dans le corps : ## 4. » et sur un
            # remplacement resté égal à l'original chiffré (« 1h/jour »).
            _rep62418 = _norm_space(str(item.get("replacement") or ""))
            if (not _rep62418 or re.search(r"\d", _rep62418) or _rep62418.startswith("#")
                    or _rep62418 == _norm_space(_orig62417)):
                _rep62418 = ("(ligne retirée du corps — voir le texte original ci-dessus)"
                             if not _en62417 else "(line withdrawn from the body — see original above)")
            doc.add_paragraph(("Remplacement dans le corps : " if not _en62417 else ("Replacement in the body: " if str(lang).lower().startswith("en") else "Remplacement dans le corps : "))
                              + _rep62418)
            doc.add_paragraph(("Décision requise : confirmer baseline, formule, provenance, porteur — réintégrer ou retirer."
                               if not _en62417 else
                               "Decision required: confirm baseline, formula, provenance, owner — reinstate or drop."))

    replay_stats = _aggregate_docx_fallbacks_and_restore(doc, result, lang)
    result.setdefault("meta", {})["docx_final_safety_v62139"] = {
        "scenario_or_kpi_rows_withheld": len(residual),
        "editorial_replay_v6213941": replay_stats,
        "legal_claims_requalified": legal_count,
        "unsupported_revenue_trends_removed": trend_count,
        "ocr_status_policy": "TRI_STATE",
    }
    _final_paragraphs = list(doc.paragraphs)
    _final_boundary = next((i for i, p in enumerate(_final_paragraphs) if _v6213942_is_annex_heading(p.text)), len(_final_paragraphs))
    _surplus_blanks = max(0, sum(1 for p in _final_paragraphs[:_final_boundary] if not p.text.strip()) - _source_body_blank_count)
    if _surplus_blanks:
        for _paragraph in reversed(_final_paragraphs[:_final_boundary]):
            if _surplus_blanks <= 0:
                break
            if not _paragraph.text.strip():
                _remove_paragraph(_paragraph)
                _surplus_blanks -= 1
    out = BytesIO()
    try:
        _withdraw_engine_control_lines_from_active_sections(doc)   # v62.13.9.4.37
    except Exception:
        pass
    # v62.13.9.4.49 — COMPLÉTION DES RANGÉES, en fin de passage (donc idempotente) : dans un tableau d'agent, une
    # rangée qui porte une étiquette voit ses valeurs chiffrées encore nues recevoir la même étiquette. Campagne
    # réelle de référence : une valeur de croissance restait nue à côté d'un libellé étiqueté « ⟨statut : tendance
    # non établie⟩ » (document produit par une version antérieure). Une année seule n'est pas une valeur ; les
    # tableaux écrits par le produit (registre, chronologie, table de faits) ne sont pas concernés.
    if _status_mode(result):
        for _tb49 in doc.tables:
            if not _tb49.rows:
                continue
            _hdr49 = [c.text for c in _tb49.rows[0].cells]
            if _is_product_table_header49(_hdr49) or _is_fact_table([_norm_space(x) for x in _hdr49]):
                continue
            for _rw49 in _tb49.rows:
                _cells49 = list(_rw49.cells)
                _tags49 = [re.search(r"⟨(?:statut|status)\s*:[^⟩]*⟩", c.text or "") for c in _cells49]
                _first49 = next((m.group(0) for m in _tags49 if m), None)
                if not _first49:
                    continue
                _seen49 = []
                for _cv49 in _cells49[1:]:
                    if any(_cv49._tc is s for s in _seen49):
                        continue
                    _seen49.append(_cv49._tc)
                    _tv49 = _norm_space(_cv49.text)
                    # v62.13.9.4.50 — un réalisé déclaré [FAIT]/[FACT] relève du rapprochement avec la pièce (réalisé
                    # unique), pas de la complétion : « 103 793 [FAIT] ⚠ chiffre sans pièce » (contre-recette, A02)
                    if re.search(r"\[(?:FAIT|FACT|FAITS|FACTS)\]", _tv49, re.I):
                        continue
                    if (_tv49 and "⟨" not in _tv49 and re.search(r"\d", _tv49)
                            and not re.fullmatch(r"(?:19|20)\d{2}", _tv49)):
                        _replace_text_runs(_cv49.paragraphs[-1], _norm_space(_cv49.paragraphs[-1].text) + " " + _first49)
    # v62.13.9.4.49 — une même étiquette posée deux fois sur une cellule ou un paragraphe (deux règles qui
    # statuent le même chiffre) n'est gardée qu'une fois : le rendu reste net et le passage suivant stable.
    _dup49 = re.compile(r"(⟨(?:statut|status) : ([^⟩]*)⟩)(?:\s*⟨(?:statut|status) : \2⟩)+")
    for _p49 in list(doc.paragraphs) + [q for _t in doc.tables for _r in _t.rows for _c in _r.cells for q in _c.paragraphs]:
        if "⟨" in (_p49.text or "") and _dup49.search(_p49.text or ""):
            _replace_text_runs(_p49, _dup49.sub(r"\1", _p49.text))
    doc.save(out)
    return out.getvalue()

def _target_entity_name(result: Mapping[str, Any]) -> str:
    for value in (
        (result.get("analysis_context") or {}).get("target_entity") if isinstance(result.get("analysis_context"), Mapping) else None,
        (result.get("company_profile") or {}).get("name") if isinstance(result.get("company_profile"), Mapping) else None,
        result.get("company_name"), result.get("target_entity"),
    ):
        if value:
            return _norm_space(value)
    return ""


def _repair_pptx_table(table, result, lang, support) -> int:
    """v62.13.9.4.10 — jugement des tables PPTX, en miroir exact du chemin
    Word : exemption de rangée liée au claim, puis jugement cellule à
    cellule. Lève la limite documentée en 9.4.8 (« tables PPTX non couvertes
    par la réparation ») : une cible en tableau n'était que bloquée par
    l'oracle, jamais neutralisée — le deck restait indistribuable au lieu
    d'être réparé."""
    from utils.board_scrutiny_guard import find_unsupported_executive_numeric_lines

    touched = 0
    en = str(lang).lower().startswith("en")
    for row in table.rows:
        cells = list(row.cells)
        rendered = " | ".join(_norm_space(c.text) for c in cells if _norm_space(c.text))
        if not rendered:
            continue
        if _row_bound_to_claim(rendered, result):
            continue
        if _FLAG_IN_PLACE51:
            # 9.4.51 — miroir du Word : les tableaux du deck ne perdent plus aucune grandeur. Rangée non certifiée → mention
            # « à confirmer sur pièce » sur ses cellules chiffrées ; cellule non étayée ailleurs → signalée sur place.
            _tag = " ⚠ to verify — to be confirmed on a document" if en else " ⚠ à vérifier — à confirmer sur pièce"
            _flag = " ⚠ to verify — figure without a document" if en else " ⚠ à vérifier — chiffre sans pièce"
            _uncert = bool(_UNCERTIFIED_ROW_RE.search(rendered))
            for cell in cells:
                txt = _norm_space(cell.text)
                if not txt or not re.search(r"\d", txt) or "⚠" in txt or _tag.strip(" —") in txt:
                    continue
                if _date_only_numeric_line(txt) or _planning_horizon_line(txt, result) or _canonical_fact_line(txt, result):
                    continue
                if _uncert and _AMOUNT_CELL_RE.search(txt):
                    cell.text = txt + _tag
                    touched += 1
                    continue
                try:
                    _hits = find_unsupported_executive_numeric_lines(
                        txt, lang=lang, numeric_support_claims=support,
                        authoritative_horizon_values=_QL.build_authority_items(result))
                except Exception:
                    _hits = []
                if _hits or _should_withhold_line(txt, result):
                    cell.text = txt + _flag
                    touched += 1
            continue
        if _UNCERTIFIED_ROW_RE.search(rendered):
            for cell in cells:
                txt = _norm_space(cell.text)
                if txt and _AMOUNT_CELL_RE.search(txt):
                    cell.text = (_AMOUNT_WITHHELD_EN if en else _AMOUNT_WITHHELD_FR)
                    touched += 1
                    continue
                if not txt or not re.search(r"\d", txt):
                    continue
                if _date_only_numeric_line(txt) or _planning_horizon_line(txt, result):
                    continue
                try:
                    bad = find_unsupported_executive_numeric_lines(
                        txt, lang=lang, numeric_support_claims=support,
                        authoritative_horizon_values=_QL.build_authority_items(result))
                except Exception:
                    bad = []
                if bad or _should_withhold_line(txt, result):
                    cell.text = (_VALUE_WITHHELD_EN if en else _VALUE_WITHHELD_FR)
                    touched += 1
            continue
        for cell in cells:
            ct = _norm_space(cell.text)
            if (not ct or _date_only_numeric_line(ct)
                    or _planning_horizon_line(ct, result)):
                continue
            if _canonical_fact_line(ct, result):
                continue
            try:
                hits = find_unsupported_executive_numeric_lines(
                    ct, lang=lang, numeric_support_claims=support,
                    authoritative_horizon_values=_QL.build_authority_items(result))
            except Exception:
                hits = []
            if hits or _should_withhold_line(ct, result):
                rep = _qualitative_replacement(ct, lang, result)
                if rep is None:
                    rep = (_V6213943_TABLE_PLACEHOLDER_EN if en
                           else _V6213943_TABLE_PLACEHOLDER_FR)
                cell.text = rep
                touched += 1
    return touched


def repair_pptx_semantic_truth(pptx_bytes: bytes, result: Mapping[str, Any], lang: str = "fr") -> bytes:
    """Final semantic repair for the exact PPTX bytes delivered."""
    from pptx import Presentation
    from utils.board_scrutiny_guard import find_unsupported_executive_numeric_lines
    from patches.legal_citation_guard import neutralize_unsupported_social_threshold_claims

    prs = Presentation(BytesIO(pptx_bytes))
    scope = financial_scope_summary(result, lang)
    support = list(result.get("numeric_support_claims") or result.get("canonical_financial_claims") or [])
    support += _registry_support62427(result)
    social_card = _social_revenue_card(result)
    entity = _target_entity_name(result) or ("target entity" if str(lang).lower().startswith("en") else "entité cible")
    legal_count = 0
    numeric_count = 0

    # v62.13.9.4.8 — doctrine 13.9.2 : la levée d'exemption des shapes
    # critiques HCRIT ne vaut que sous contexte de run réel ; un appel
    # outillé sans référentiel (tests, decks nus) conserve l'exemption
    # historique — le juge nu ne censure pas. L'oracle runtime applique
    # exactement la même condition.
    _ctx62148 = bool(result.get("run_fingerprint")
                     or result.get("diagnostics_attempts")
                     or result.get("canonical_claims")
                     or result.get("numeric_support_claims")
                     or result.get("strategic_horizon"))

    restore_map: dict[str, list[str]] = {}
    for d in _diagnostics(result):
        if str(d.get("role") or "") != "pptx_numeric_repair":
            continue
        changes = _jsonish(d.get("changes")) or _jsonish(d.get("samples")) or d.get("changes") or d.get("samples")
        if isinstance(changes, Mapping):
            changes = changes.get("samples") or []
        if not isinstance(changes, list):
            continue
        for item in changes:
            if not isinstance(item, Mapping):
                continue
            before, after = str(item.get("before") or ""), str(item.get("after") or "")
            if not before or not after:
                continue
            if _date_only_numeric_line(before) or _planning_horizon_line(before, result):
                restore_map.setdefault(after, []).append(before)
            elif _PRODUCT_ATTRIBUTE.search(before):
                _qr = _qualitative_replacement(before, lang, result)
                if _qr:
                    restore_map.setdefault(after, []).append(_qr)

    for slide_index, slide in enumerate(prs.slides, start=1):
        seen_fallbacks: set[str] = set()
        _slide_blob = "\n".join(
            getattr(shape, "text", "") or ""
            for shape in slide.shapes
            if getattr(shape, "has_text_frame", False)
        )
        _diagnostic_score_slide = bool(re.search(
            r"(?:SCORE DE CONFIANCE DU LIVRABLE|DELIVERY CONFIDENCE SCORE|"
            r"SCORE DE CONFIANCE.*UTILIT[ÉE] D[ÉE]CISIONNELLE|"
            r"CONFIDENCE SCORE.*DECISION USEFULNESS)",
            _slide_blob, re.I | re.S,
        ))
        for shape in slide.shapes:
            # v62.13.9.4.9 — les tables du deck sont jugées comme celles du
            # Word (rangée liée au claim, puis cellule à cellule).
            if getattr(shape, "has_table", False):
                try:
                    numeric_count += _repair_pptx_table(
                        shape.table, result, lang, support)
                except Exception:
                    pass
                continue
            if not hasattr(shape, "text_frame") or not shape.has_text_frame:
                continue
            for paragraph in shape.text_frame.paragraphs:
                original = paragraph.text
                t = _norm_space(original)
                if not t:
                    continue
                # 9.4.65 — huitième vérification du 21/10 : un texte de l'outil (marqueur U+2063, ou mention
                # « Généré par / Generated by CoDIR IA — version ») n'est ni réécrit ni signalé (doctrine du typage
                # à la construction) ; la couverture française recevait « ⟨statut : chiffre sans pièce⟩ ».
                if "\u2063" in original or re.match(r"(?i)^\W*(?:g[ée]n[ée]r[ée]\s+par|generated\s+by)\s+CoDIR\s+IA\b", t):
                    continue
                new = original
                # Restore a date/product attribute from the numeric-repair audit
                # before interpreting any remaining fallback. This preserves the
                # historical v62.13.6 contract and prevents a blank cover from
                # swallowing a legitimate deadline.
                for after, replacements in restore_map.items():
                    if after in new and replacements:
                        new = new.replace(after, replacements.pop(0), 1)
                # v62.13.9.4.3 — une étiquette technique héritée n'est jamais une
                # couverture ni un contenu : couverture → vide, ailleurs → renvoi
                # explicite à l'annexe (aucune formulation inventée).
                if _GENERIC_FALLBACK_RE.search(_norm_space(new)):
                    # v62.13.9.4.35 — run réel du 16/09/2026 (dossier réseau de soins) : huit
                    # « Proposition chiffrée — voir l'annexe du compte rendu » dans la
                    # trame, dont une sur une carte de décision. L'étiquette vient de
                    # l'agent, pas du produit ; le produit ne doit pas la transformer
                    # en renvoi vers une annexe qui n'existe plus depuis la doctrine
                    # des scénarios. Sur une carte qui porte une PROPOSITION, on va
                    # chercher une phrase qualitative de la même rubrique, et la case
                    # reste vide à défaut ; sur une carte de CHIFFRE (kpi, couverture),
                    # le message est conservé mais dit ce qui manque, sans annexe.
                    # Sur une carte qui porte une PROPOSITION, on cherche d'abord une
                    # phrase qualitative de la même rubrique ; partout ailleurs, et à
                    # défaut, la case est vidée. La note de couverture de la trame dit
                    # ce qui manque : une case vide vaut mieux qu'un message d'outil.
                    _role35 = str(getattr(shape, "name", "") or "")
                    _is_proposal35 = any(k in _role35 for k in
                                         (":decision", ":action", ":next-step", ":axis", ":roadmap", ":arbitration"))
                    _alt35 = (_qualitative_line_from_section62434(result, slide_index, lang)
                              if (_is_proposal35 and slide_index != 1) else None)
                    new = _alt35 or ""

                # Explicit consolidated-account value, including the old bare card.
                if re.fullmatch(r"Comptes consolidés(?: groupe)? fournis", _norm_space(new), re.I):
                    new = ("Comptes consolidés groupe : oui — faits page-confirmés"
                           if scope["group_consolidated_accounts_provided"] else
                           "Comptes consolidés groupe : non établis")
                elif re.fullmatch(r"(?:Group )?Consolidated accounts provided", _norm_space(new), re.I):
                    new = ("Group consolidated accounts: yes — page-confirmed facts"
                           if scope["group_consolidated_accounts_provided"] else
                           "Group consolidated accounts: not established")
                else:
                    scope_line = ("Comptes consolidés groupe : oui — faits page-confirmés" if scope["group_consolidated_accounts_provided"] else "Comptes consolidés groupe : non établis") if str(lang).lower().startswith("fr") else ("Group consolidated accounts: yes — page-confirmed facts" if scope["group_consolidated_accounts_provided"] else "Group consolidated accounts: not established")
                    new = re.sub(r"Comptes\s+consolidés(?:\s+groupe)?\s*(?:fournis)?\s*:\s*(?:oui|non(?:\s+établis?)?)", scope_line, new, flags=re.I)
                    new = re.sub(r"(?:Group\s+)?Consolidated\s+accounts(?:\s+provided)?\s*:\s*(?:yes|no|not\s+established)", scope_line, new, flags=re.I)

                # Legal Claim Gate, compacted for an executive slide.
                _legal_text, legal_findings = neutralize_unsupported_social_threshold_claims(new, lang=lang)
                if legal_findings:
                    legal_count += len(legal_findings)
                    new = ("Headcount band — obligations to qualify with HR / employment counsel."
                           if str(lang).lower().startswith("en") else
                           "Tranche d’effectif — obligations à qualifier avec DRH / conseil social.")

                # Social revenue cards must state scope/source, never imply group revenue.
                social_value_line = False
                if social_card:
                    value_norm = _norm_number_token(social_card["value"])
                    if value_norm and value_norm in _numbers_in(new):
                        if re.search(r"(?:M€|€|million|M\b)", new, re.I):
                            base_value = re.sub(r"\s*[·—-]\s*social\b", "", _norm_space(new), flags=re.I)
                            new = base_value + " · social"
                            social_value_line = True
                    if re.fullmatch(r"(?:Chiffre\s+d['’]affaires|CA)(?:\s*\(indicatif\))?", _norm_space(new), re.I):
                        short_entity = entity.replace("SASU", "").strip()
                        new = f"CA social {short_entity} · Pappers"
                        social_value_line = True

                new = _normalize_headcount_band_text(new)
                if _legal_scrub_evidenced(result):
                    new = new.replace(_FALSE_LEGAL_FR, "")
                if not scope["group_consolidated_accounts_provided"]:
                    new = re.sub(r"Obtenir\s+(?:et\s+analyser\s+)?(?:les\s+)?comptes\s+consolidés\s+(?:19|20)\d{2}\s*[-–]\s*(?:19|20)\d{2}", "Fournir les comptes sociaux des exercices récents en texte/OCR et clarifier le périmètre groupe", new, flags=re.I)
                _st50 = _status_mode(result)
                _en50 = str(lang).lower().startswith("en")
                _tags50: list[str] = []
                if _unsupported_revenue_trend(new, result):
                    if _st50:                                  # v62.13.9.4.50 — signaler, ne pas remplacer
                        _tags50.append("trend not established" if _en50 else "tendance non établie")
                    else:
                        new = "Tendance de CA non établie — rapprocher les sources avant calcul"
                if _unsupported_market_growth(new, result):
                    if _st50:
                        _tags50.append("unsourced market figure" if _en50 else "marché non sourcé")
                    else:
                        new = _MARKET_GROWTH_EN if str(lang).lower().startswith("en") else _MARKET_GROWTH_FR

                # Strict Option B on the actual final slide text.  A matching
                # canonical claim is rewritten cleanly; FACT/source/page labels
                # never self-authorise a number.
                _n = _norm_space(new)
                canonical_fact = _canonical_fact_line(_n, result)
                if canonical_fact:
                    if _st50:
                        # v62.13.9.4.50 — la diapositive garde le texte de l'agent ; un montant différent du fait
                        # confirmé porte la formulation de la pièce
                        if _amounts_contradict49(_n, canonical_fact):
                            _tags50.append(("contradicted by the source: " if _en50 else "contredit par la pièce : ")
                                           + _norm_space(canonical_fact)[:90])
                    else:
                        new = canonical_fact
                        _n = _norm_space(new)
                _fact_ok = canonical_fact is not None
                # v62.13.9.4.8 (terrain réel du 13/08/2026) — les shapes HCRIT ne
                # sont plus exemptées du jugement : des cibles non prouvées
                # survivaient dans la hiérarchie exec. Elles sont jugées comme
                # les autres ; leur réécriture n'est JAMAIS vide — un élément
                # critique conserve son rôle (réécriture qualitative de titre,
                # sinon renvoi explicite à l'annexe).
                _is_hcrit62148 = str(getattr(shape, "name", "")).startswith("HCRIT:")
                if (not _diagnostic_score_slide and not social_value_line and not _fact_ok
                        and not (_is_hcrit62148 and not _ctx62148)
                        and not (_date_only_numeric_line(_n) or _planning_horizon_line(_n, result))):
                    hits = find_unsupported_executive_numeric_lines(
                        new, lang=lang, numeric_support_claims=support,
                authoritative_horizon_values=_QL.build_authority_items(result))
                    _kpi50 = _n in _canonical_display_values50(result)
                    if (hits or _should_withhold_line(_norm_space(new), result)) and _st50:
                        # v62.13.9.4.50 — doctrine du 28/09/2026 : la diapositive garde son texte ; le passage est
                        # étiqueté, le rendu du deck le signale. Une valeur de carte clé issue d'un fait confirmé
                        # (« $620m ») n'est pas un chiffre sans pièce.
                        if not _kpi50:
                            _tags50.append("unsourced figure" if _en50 else "chiffre sans pièce")
                    elif hits or _should_withhold_line(_norm_space(new), result):
                        _is_title = _v6213943_is_title_shape(slide, shape)
                        # v62.13.9.4.12 — LOCALITÉ PAR MONTANT au deck, en
                        # parité avec le chemin Word : une phrase mixte
                        # conserve son fait daté et ne perd que sa cible.
                        # Un titre reste réécrit en entier (il ne se découpe
                        # pas en propositions sans devenir illisible).
                        _qr = None
                        if not (_is_title or _is_hcrit62148):
                            _qr = _clause_local_rewrite(new, lang, result)
                        if _qr is None:
                            _qr = _qualitative_replacement(new, lang, result,
                                                           is_heading=_is_title or _is_hcrit62148)
                        if _qr is None and _is_title:
                            # un TITRE ne peut pas disparaître : le message de contrôle
                            # tient sa place, faute de mieux.
                            _qr = (_V6213943_DECK_PLACEHOLDER_EN
                                   if str(lang).lower().startswith("en")
                                   else _V6213943_DECK_PLACEHOLDER_FR)
                        elif _qr is None and _is_hcrit62148:
                            # v62.13.9.4.34 (lot 2) — UNE CASE VIDE VAUT MIEUX QU'UN
                            # MESSAGE DE CONTRÔLE. Contre-audit de publication du
                            # 14/09/2026 : 11 à 15 « Proposition chiffrée — voir
                            # l'annexe » par trame (dossier industriel (composants), dossier agroalimentaire, dossier réseau de soins,
                            # dossier anglophone coté), y compris sur la feuille de route et les
                            # prochaines étapes, là où le professionnel attend un
                            # point à développer. On cherche d'abord une phrase
                            # qualitative de la MÊME rubrique dans les sorties ;
                            # à défaut, la case est laissée vide et la note de
                            # couverture dit ce qui manque.
                            _qr = _qualitative_line_from_section62434(result, slide_index, lang)
                        new = _qr if _qr is not None else ""
                        numeric_count += 1

                if _tags50 and "⟨" not in new:
                    new = _norm_space(new) + " ⟨" + ("status" if _en50 else "statut") + " : " + "; ".join(dict.fromkeys(_tags50)) + "⟩"
                if new != paragraph.text:
                    _replace_text_runs(paragraph, new)

        # Deduplicate identical prudence fallbacks within each slide.
        for shape in slide.shapes:
            if not hasattr(shape, "text_frame") or not shape.has_text_frame:
                continue
            for paragraph in shape.text_frame.paragraphs:
                t = _norm_space(paragraph.text)
                if not t or not re.search(r"(?:Cible chiffrée écartée|Réduire les stocks après baseline|Fixer le budget marketing|Proposition quantifiée écartée)", t, re.I):
                    continue
                if t in seen_fallbacks:
                    _replace_text_runs(paragraph, "")
                else:
                    seen_fallbacks.add(t)

    if isinstance(result, MutableMapping):
        result.setdefault("meta", {})["pptx_final_safety_v62139"] = {
            "numeric_targets_withheld": numeric_count,
            "legal_claims_requalified": legal_count,
            "social_revenue_card_qualified": bool(social_card),
            "consolidated_card_explicit": True,
        }
    out = BytesIO()
    prs.save(out)
    return out.getvalue()

