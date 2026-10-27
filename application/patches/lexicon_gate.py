"""
patches/lexicon_gate.py — Pack surface : vocabulaire « aide à la décision »

Doctrine produit : CoDIR-IA propose, n'arbitre pas. Vocabulaire autorisé —
RECOMMENDED · TO BE ARBITRATED · TO INVESTIGATE · TO VERIFY. Interdits (ils
laissent croire qu'une décision est PRISE) — VALIDATED · DECIDED · APPROVED ·
BLOCKING (et leurs équivalents FR).

Le prompt ne doit plus exiger ces mots (corrigé à la source). Ce gate est le
filet post-génération : il neutralise tout résidu dans les surfaces finales
(CR, deck). Ciblage chirurgical : phrases de décision (insensibles à la casse)
et labels de statut en MAJUSCULES — la prose courante (« confirmé par le
registre ») n'est pas touchée.
"""
from __future__ import annotations
import re
from typing import Tuple

# (motif, remplacement, flags) — phrases multi-mots d'abord.
_RULES = [
    (r"\bVALIDATED\s+DECISION\b", "RECOMMENDED ORIENTATION", re.I),
    (r"\bVALIDATED\s+RECOMMENDATION\b", "RECOMMENDED OPTION", re.I),
    (r"\bD[ÉE]CISION\s+VALID[ÉE]E\b", "ORIENTATION RECOMMANDÉE", re.I),
    # labels de statut en MAJUSCULES uniquement (préserve la prose en minuscules)
    (r"\bVALIDATED\b", "RECOMMENDED", 0),
    (r"\bDECIDED\b", "RECOMMENDED", 0),
    (r"\bAPPROVED\b", "RECOMMENDED", 0),
    (r"\bBLOCKING\b", "TO BE ARBITRATED", 0),
    (r"\bVALIDÉE?S?\b", "RECOMMANDÉE", 0),
    (r"\bDÉCIDÉE?S?\b", "RECOMMANDÉE", 0),
    (r"\bAPPROUVÉE?S?\b", "RECOMMANDÉE", 0),
    (r"\bBLOQUANTE?S?\b", "À ARBITRER", 0),
    (r"\bCONFIRMED\b", "ASSESSED", 0),
    (r"\bCONFIRM[ÉE]E?S?\b", "ÉVALUÉ", 0),
    # Labels de statut contextuels (Status: / Statut :) — neutralise Title Case
    # ET minuscules SANS toucher la prose (« confirmed by Companies House »).
    (r"(Status\s*:\s*)(?:Validated|Approved|Decided)\b", r"\1Recommended", re.I),
    (r"(Status\s*:\s*)Confirmed\b", r"\1Assessed", re.I),
    (r"(Status\s*:\s*)Blocking\b", r"\1To be arbitrated", re.I),
    (r"(Statut\s*:\s*)(?:Valid[ée]e?|Approuv[ée]e?|D[ée]cid[ée]e?)\b", r"\1Recommandé", re.I),
    (r"(Statut\s*:\s*)Confirm[ée]e?\b", r"\1Évalué", re.I),
    (r"(Statut\s*:\s*)Bloquante?s?\b", r"\1À arbitrer", re.I),
    # Wording trompeur sur des résultats absents des pièces (mode BYOD) : ne pas
    # laisser croire à un état public de publication qu'on n'a pas vérifié.
    (r"pending\s+(full[\s-]?year\s+)?(results?\s+)?publication", "not present in the provided attachments / not verified in this run", re.I),
    (r"awaiting\s+publication", "not present in the provided attachments", re.I),
    (r"results?\s+pending\s+publication", "results not present in the provided attachments", re.I),
    (r"en\s+attente\s+de\s+publication", "absents des pièces fournies", re.I),
]
_COMPILED = [(re.compile(p, f), r) for (p, r, f) in _RULES]

LEXICON_STATS = {"docx": 0, "pptx": 0, "status": "ok"}

def last_stats():
    return dict(LEXICON_STATS)

_FORBIDDEN_CHECK = re.compile(
    r"\b(VALIDATED|DECIDED|APPROVED|BLOCKING|CONFIRMED|VALID[ÉE]E?S?|"
    r"D[ÉE]CID[ÉE]E?S?|APPROUV[ÉE]E?S?|BLOQUANTE?S?|CONFIRM[ÉE]E?S?)\b")


# 9.4.54 — contre-recette ChatGPT du 07/10/2026 (M04, autorité) : « ACTION DÉJÀ DÉCIDÉE » écrit par le DIRIGEANT dans
# son brief devenait « ACTION DÉJÀ RECOMMANDÉE » dans le Word final. Ce filet vise les décisions que l'ANALYSE
# s'attribuerait ; une décision humaine (déjà décidée, décision du conseil, décidée par le dirigeant) n'est jamais
# requalifiée. Les passages protégés sont masqués le temps du filtrage, puis rendus tels quels.
_HUMAN_AUTHORITY54 = re.compile(
    r"(?i)\bACTIONS?\s+D[ÉE]J[ÀA]\s+D[ÉE]CID[ÉE]ES?(?:\s+PAR\s+(?:LA\s+DIRECTION|LE\s+DIRIGEANT|LE\s+CONSEIL))?|"
    r"\bD[ÉE]CISIONS?\s+(?:DU|DE\s+LA)\s+(?:CONSEIL|CoDIR|COMIT[ÉE]|DIRECTION)\b[^.\n]{0,90}|"
    r"\bD[ÉE]CID[ÉE]E?S?\s+(?:PAR\s+(?:LE|LA)\s+(?:DIRIGEANT|CONSEIL|CoDIR|DIRECTION|DG)|LE\s+\d{1,2}/\d{1,2}/\d{4})|"
    r"\bD[ÉE]CISIONS?\s+ADOPT[ÉE]ES?\b[^.\n]{0,90}|"
    r"\bALREADY\s+DECIDED\b|\bBOARD\s+DECISION\b[^.\n]{0,90}|\bDECIDED\s+BY\s+THE\s+(?:LEADER|BOARD|CEO)\b")


def _mask_human54(text: str):
    keep = []

    def _m(mm):
        keep.append(mm.group(0))
        return f"\uE000{len(keep) - 1}\uE001"
    return _HUMAN_AUTHORITY54.sub(_m, text), keep


def _unmask_human54(text: str, keep: list) -> str:
    return re.sub("\uE000(\\d+)\uE001", lambda mm: keep[int(mm.group(1))], text)


def enforce_lexicon(text: str) -> str:
    """Neutralise le vocabulaire de décision interdit dans un texte (jamais une décision du dirigeant)."""
    if not text:
        return text
    out, keep = _mask_human54(text)
    for rx, repl in _COMPILED:
        out = rx.sub(repl, out)
    return _unmask_human54(out, keep)


def contains_forbidden(text: str) -> bool:
    return bool(_FORBIDDEN_CHECK.search(_mask_human54(text or "")[0]))


def sanitize_docx(doc) -> int:
    """Applique le gate à tous les runs d'un document python-docx (paragraphes +
    cellules de tableau). Retourne le nombre de runs modifiés."""
    n = 0

    def _fix_runs(paragraph):
        nonlocal n
        for run in paragraph.runs:
            new = enforce_lexicon(run.text)
            if new != run.text:
                run.text = new; n += 1
        # fallback : terme coupé entre deux runs (gras/style au milieu) → on
        # reconstruit le texte du paragraphe si un interdit subsiste.
        if paragraph.runs and contains_forbidden(paragraph.text):
            fixed = enforce_lexicon(paragraph.text)
            if fixed != paragraph.text:
                paragraph.runs[0].text = fixed
                for r in paragraph.runs[1:]:
                    r.text = ""
                n += 1

    LEXICON_STATS["docx"] = 0
    for p in doc.paragraphs:
        _fix_runs(p)
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    _fix_runs(p)
    LEXICON_STATS["docx"] = n
    return n


def _fix_text_frame(tf) -> int:
    """Applique le gate aux paragraphes d'un text_frame (runs + fallback)."""
    n = 0
    for para in tf.paragraphs:
        for run in para.runs:
            new = enforce_lexicon(run.text)
            if new != run.text:
                run.text = new; n += 1
        _ptxt = "".join(r.text for r in para.runs)
        if para.runs and contains_forbidden(_ptxt):
            fixed = enforce_lexicon(_ptxt)
            if fixed != _ptxt:
                para.runs[0].text = fixed
                for r in para.runs[1:]:
                    r.text = ""
                n += 1
    return n


def sanitize_pptx(prs) -> int:
    """Applique le gate à tous les runs d'une présentation python-pptx :
    zones de texte ET cellules de tableau (l'action register est un tableau)."""
    n = 0
    for slide in prs.slides:
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                n += _fix_text_frame(shape.text_frame)
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    for cell in row.cells:
                        n += _fix_text_frame(cell.text_frame)
    LEXICON_STATS["pptx"] = n
    return n
