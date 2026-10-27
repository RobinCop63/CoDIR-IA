"""Fail-closed market-evidence reconciliation — v62.6.

The module never creates a market number. It uses the structured ledger to
prevent heterogeneous years/perimeters/natures and source-actor results from
being promoted as current aggregate market facts in Word, PPTX or the action
register.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

_SIZE_RANGE_RX = re.compile(r"(?:entre\s+)?(?:450\s*M€\s*(?:et|[-–—à])\s*800\s*M€|700\s*M€\s*(?:et|[-–—à])\s*850\s*M€|700[-–—]850\s*M€)", re.I)
_CURRENT_SIZE_RX = re.compile(r"march[ée].{0,90}(?:(?:19|20)\d{2}.{0,35})?(?:p[èe]se|taille|estim[ée]|se\s+situe|fourchette).{0,60}\b(?:450|600|700|800|850)\s*M€", re.I)
_GROWTH55_RX = re.compile(r"(?:croissance|cro[iî]t|dynamique|progression|march[ée]).{0,90}\+?55\s*%|\+?55\s*%.{0,90}(?:croissance|march[ée])", re.I)
_GROWTH30_RX = re.compile(r"(?:rebond|croissance|missions?|march[ée]).{0,90}\+?30\s*%|\+?30\s*%.{0,90}(?:S1|march[ée]|missions?)", re.I)
_STRONG_GROWTH_RX = re.compile(r"march[ée]\s+en\s+forte\s+croissance|acc[ée]l[ée]ration\s+nette", re.I)
_DERIVED_SPLIT_RX = re.compile(r"\b(?:285|155)\s*M€\b", re.I)
_BULLET_PREFIX_RX = re.compile(r"^(\s*(?:[-•*✓]|\d+[.)])?\s*)")


def _rows(ledger):
    return [dict(r) for r in (ledger or []) if isinstance(r, Mapping)]


def _central(row: Mapping[str, Any]) -> float | None:
    try:
        return float(row.get("valeur_centrale"))
    except Exception:
        return None


def _is_safe_current_size(row: Mapping[str, Any], current_year: int | None = None) -> bool:
    # v62.13.9.4.38 — l'année de référence n'est plus figée au millésime d'un ancien
    # dossier : c'est l'année d'analyse du run quand elle est connue ; sinon, une
    # taille de marché décision-safe de n'importe quel millésime compte.
    if str(row.get("metric_class")) != "MARKET_SIZE" or not bool(row.get("decision_safe")):
        return False
    try:
        y = int(row.get("annee") or 0)
    except Exception:
        y = 0
    return (y == int(current_year)) if current_year else (y > 0)


def build_market_reconciliation_note(ledger: list[Mapping[str, Any]] | None,
                                     lang: str = "fr", analysis_year: int | None = None) -> str:
    rows = _rows(ledger)
    en = str(lang or "fr").lower().startswith("en")
    has_safe_size = any(_is_safe_current_size(r, analysis_year) for r in rows)
    unsafe_growth = any(
        (str(r.get("metric_class")) == "GROWTH" or _central(r) in {30.0, 55.0})
        and not bool(r.get("decision_safe")) for r in rows)
    if en:
        lines = ["### MARKET-EVIDENCE RECONCILIATION"]
        if not has_safe_size:
            lines.append("- No homogeneous market size for the analysed year is decision-safe; references with different years or perimeters are not a range for the analysed year.")
        if unsafe_growth:
            lines.append("- Forecasts and source-actor results are not observed aggregate market growth.")
        lines.append("- Direct comparison requires the same period, perimeter and epistemic nature.")
        return "\n".join(lines)
    lines = ["### RÉCONCILIATION DES PREUVES MARCHÉ"]
    if not has_safe_size:
        lines.append("- Aucun dimensionnement homogène du marché pour l’année analysée n’est décision-safe ; des références d’années ou de périmètres différents ne constituent pas une fourchette pour l’année analysée.")
    if unsafe_growth:
        lines.append("- Un taux de croissance annoncé reste une prévision, non une croissance observée du marché ; les résultats propres à un acteur ne sont pas une croissance agrégée observée.")
    lines.append("- Toute comparaison directe exige la même période, le même périmètre et la même nature de preuve.")
    return "\n".join(lines)


def _safe_line(prefix: str, kind: str, lang: str) -> str:
    en = str(lang or "fr").lower().startswith("en")
    if kind == "size":
        body = ("No homogeneous market size for the analysed year is established; see the reconciled evidence in the register of the complete file."
                if en else "Aucun dimensionnement homogène du marché pour l’année analysée n’est établi ; voir les preuves réconciliées au registre du dossier complet.")
    elif kind == "actor":
        body = ("A growth figure reported by a single actor is that actor's result, not observed aggregate market growth."
                if en else "Un taux de croissance déclaré par un acteur source est le résultat de cet acteur, non une croissance agrégée observée du marché.")
    elif kind == "forecast":
        body = ("A forecast growth figure is an estimate, not observed aggregate market growth."
                if en else "Un taux de croissance prévisionnel est une estimation, non une croissance agrégée observée du marché.")
    else:
        body = ("Comparable market dynamics remain to be established."
                if en else "La dynamique comparable du marché reste à établir.")
    return prefix + body


def _replace_line(line: str, ledger: list[Mapping[str, Any]], lang: str,
                  analysis_year: int | None = None) -> tuple[str, int]:
    prefix = (_BULLET_PREFIX_RX.match(line).group(1) if _BULLET_PREFIX_RX.match(line) else "")
    rows = _rows(ledger)
    has_safe_size = any(_is_safe_current_size(r, analysis_year) for r in rows)
    has_actor_30 = any(str(r.get("scope")) == "SOURCE_ACTOR"
                       and _central(r) == 30.0 for r in rows)
    has_unsafe_55 = any(_central(r) == 55.0
                        and not bool(r.get("decision_safe")) for r in rows)
    out = line
    if not has_safe_size and (_SIZE_RANGE_RX.search(out) or _CURRENT_SIZE_RX.search(out)):
        return _safe_line(prefix, "size", lang), 1
    if has_actor_30 and _GROWTH30_RX.search(out):
        return _safe_line(prefix, "actor", lang), 1
    if has_unsafe_55 and _GROWTH55_RX.search(out):
        return _safe_line(prefix, "forecast", lang), 1
    if _STRONG_GROWTH_RX.search(out) and (has_actor_30 or has_unsafe_55):
        return _safe_line(prefix, "dynamics", lang), 1
    if _DERIVED_SPLIT_RX.search(out) and re.search(r"(?:65|35|70|30)\s*%|interm[ée]di|gr[ée].{0,8}gr[ée]", out, re.I):
        suffix = (" [derived order of magnitude; not an observed fact]"
                  if str(lang).lower().startswith("en")
                  else " [ordre de grandeur dérivé ; non observé]")
        if suffix.strip() not in out:
            return out + suffix, 1
    return out, 0


def sanitize_market_claims(outputs: Mapping[str, Any] | None,
                           ledger: list[Mapping[str, Any]] | None,
                           lang: str = "fr", analysis_year: int | None = None) -> tuple[dict[str, Any], dict]:
    """Sanitize every narrative surface; inject the note only at two anchors."""
    src = dict(outputs or {})
    report = {"fields_touched": 0, "claims_rewritten": 0, "note_injected": 0}
    note = build_market_reconciliation_note(ledger, lang, analysis_year=analysis_year)
    note_targets = {"strategie", "synthese_decisions"}
    note_markers = ("RÉCONCILIATION DES PREUVES MARCHÉ", "MARKET-EVIDENCE RECONCILIATION")
    for key, value in list(src.items()):
        if not isinstance(value, str):
            continue
        changed = 0
        out = []
        for line in value.splitlines():
            newline, n = _replace_line(line, ledger or [], lang, analysis_year=analysis_year)
            out.append(newline)
            changed += n
        text = "\n".join(out)
        if key in note_targets and note and not any(m in text for m in note_markers):
            text = note + "\n\n" + text
            report["note_injected"] += 1
            changed += 1
        if changed:
            src[key] = text
            report["fields_touched"] += 1
            report["claims_rewritten"] += changed
    return src, report


def fail_closed_market_outputs(outputs: Mapping[str, Any] | None,
                               lang: str = "fr") -> tuple[dict[str, Any], dict]:
    """Last-resort safety when the structured reconciliation itself fails.

    The product must never expose the raw quantitative market narrative after
    a safety-layer exception.  This fallback preserves qualitative/action
    lines, replaces quantitative market claims with an explicit uncertainty
    statement, and records every touched field.
    """
    src = dict(outputs or {})
    en = str(lang or "fr").lower().startswith("en")
    note = (
        "### MARKET EVIDENCE UNAVAILABLE\n"
        "- Quantitative market claims from agent output were withheld because "
        "the evidence reconciliation failed. Use only the qualitative framing "
        "until the structured ledger is restored."
        if en else
        "### PREUVES MARCHÉ INDISPONIBLES\n"
        "- Les affirmations quantitatives de marché produites par les agents "
        "ont été écartées car la réconciliation des preuves a échoué. Utiliser "
        "uniquement le cadrage qualitatif jusqu’au rétablissement du ledger."
    )
    quantitative_market = re.compile(
        r"(?:march[ée]|interm[ée]di|gr[ée].{0,8}gr[ée]|cabinet|TJM|missions?)"
        r".{0,120}(?:\b\d[\d\s.,]*\s*(?:M€|Md€|%|€/jour)|[+−-]\d[\d\s.,]*\s*%)|"
        r"(?:\b\d[\d\s.,]*\s*(?:M€|Md€|%|€/jour)|[+−-]\d[\d\s.,]*\s*%)"
        r".{0,120}(?:march[ée]|interm[ée]di|gr[ée].{0,8}gr[ée]|TJM|missions?)",
        re.I,
    )
    safe_line = (
        "Market quantitative evidence unavailable — see the structured ledger."
        if en else
        "Preuves quantitatives de marché indisponibles — voir le ledger structuré."
    )
    report = {"status": "FAILED_CLOSED", "fields_touched": 0, "lines_replaced": 0}
    for key, value in list(src.items()):
        if not isinstance(value, str):
            continue
        out: list[str] = []
        changed = False
        emitted = False
        for line in value.splitlines():
            if quantitative_market.search(line):
                if not emitted:
                    prefix = (_BULLET_PREFIX_RX.match(line).group(1)
                              if _BULLET_PREFIX_RX.match(line) else "")
                    out.append(prefix + safe_line)
                    emitted = True
                report["lines_replaced"] += 1
                changed = True
            else:
                out.append(line)
        text = "\n".join(out)
        if key in {"strategie", "synthese_decisions"} and note not in text:
            text = note + "\n\n" + text
            changed = True
        if changed:
            src[key] = text
            report["fields_touched"] += 1
    return src, report


__all__ = ["build_market_reconciliation_note", "sanitize_market_claims", "fail_closed_market_outputs"]
