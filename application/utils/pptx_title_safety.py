"""Deterministic safety helpers for executive PPTX titles.

Critical slide titles must never be delivered with an ellipsis.  A source can
still arrive pre-truncated (provider output, historical payload, or legacy local
compaction), so titles are repaired both at render time and at the final PPTX
choke point.
"""
from __future__ import annotations

import re
from typing import Any

_ELLIPSIS_RE = re.compile(r"(?:…|\.\.\.)")


def has_truncation_marker(text: Any) -> bool:
    return bool(_ELLIPSIS_RE.search(str(text or "")))


def safe_hcrit_title(text: Any, lang: str = "fr") -> str:
    """Return a complete qualitative title when *text* is pre-truncated.

    The fallback preserves the slide's semantic role without guessing the
    missing suffix.  Non-truncated titles are returned byte-for-byte unchanged.
    """
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw or not has_truncation_marker(raw):
        return raw

    en = str(lang or "fr").lower().startswith("en")
    prefix = raw.split(":", 1)[0].strip().lower()
    fr = {
        "commercial": "Commercial : priorités et financement à qualifier",
        "supply chain": "Supply chain : diagnostic détaillé disponible dans le CR",
        "situation": "Situation : diagnostic détaillé disponible dans le CR",
        "décision": "Décision : arbitrage à confirmer après revue du CR",
        "decision": "Décision : arbitrage à confirmer après revue du CR",
        "risque clé": "Risque clé : qualification détaillée disponible dans le CR",
        "key risk": "Risque clé : qualification détaillée disponible dans le CR",
        "priorité": "Priorité : action à confirmer après revue du CR",
        "priority": "Priorité : action à confirmer après revue du CR",
        "arbitrage": "Arbitrage : décision à confirmer après revue du CR",
        "prochaine action": "Prochaine action : compléter la qualification",
        "next action": "Prochaine action : compléter la qualification",
        "question clé": "Question clé : arbitrage à préciser",
        "key question": "Question clé : arbitrage à préciser",
    }
    en_map = {
        "commercial": "Commercial: priorities and funding to qualify",
        "supply chain": "Supply chain: detailed diagnosis available in the report",
        "situation": "Situation: detailed diagnosis available in the report",
        "décision": "Decision: trade-off to confirm after report review",
        "decision": "Decision: trade-off to confirm after report review",
        "risque clé": "Key risk: detailed qualification available in the report",
        "key risk": "Key risk: detailed qualification available in the report",
        "priorité": "Priority: action to confirm after report review",
        "priority": "Priority: action to confirm after report review",
        "arbitrage": "Decision: trade-off to confirm after report review",
        "prochaine action": "Next action: complete the qualification",
        "next action": "Next action: complete the qualification",
        "question clé": "Key question: trade-off to clarify",
        "key question": "Key question: trade-off to clarify",
    }
    mapping = en_map if en else fr
    if prefix in mapping:
        return mapping[prefix]

    core = _ELLIPSIS_RE.split(raw, maxsplit=1)[0].rstrip(" ,;:–—-")
    # The last token may be cut mid-word.  Drop it rather than reconstruct it.
    if " " in core:
        core = core.rsplit(" ", 1)[0].rstrip(" ,;:–—-")
    if len(core) < 8:
        return ("Detailed executive point available in the report" if en
                else "Point exécutif détaillé disponible dans le CR")
    return f"{core} — see report" if en else f"{core} — voir CR"


def repair_hcrit_title_ellipses(prs: Any, lang: str = "fr") -> list[dict[str, str]]:
    """Repair every ``HCRIT:slide:title`` shape while preserving run styling."""
    repairs: list[dict[str, str]] = []
    for slide_index, slide in enumerate(getattr(prs, "slides", []), 1):
        for shape in getattr(slide, "shapes", []):
            if str(getattr(shape, "name", "") or "") != "HCRIT:slide:title":
                continue
            old = str(getattr(shape, "text", "") or "")
            new = safe_hcrit_title(old, lang)
            if new == old:
                continue
            try:
                tf = shape.text_frame
                first = tf.paragraphs[0]
                if first.runs:
                    first.runs[0].text = new
                    for run in first.runs[1:]:
                        run.text = ""
                else:
                    first.text = new
                for paragraph in tf.paragraphs[1:]:
                    paragraph.text = ""
            except Exception:
                shape.text = new
            repairs.append({"slide": str(slide_index), "before": old, "after": new})
    return repairs
