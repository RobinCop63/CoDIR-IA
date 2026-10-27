"""
patches/contradiction_gate.py — v17.1.0-B2.3-F.6.7 (ticket F.6.7-04)

Run dossier réseau de soins FY2022 : la MÊME entité, le MÊME exercice portent deux valeurs
différentes selon la section (exemple synthétique : même entité, chiffre d’affaires et résultat différents selon la section),
et le CR dit « aucune pièce financière attachée » puis analyse 6 pièces jointes.
Inacceptable pour un Comité d'audit.

Ce gate déterministe DÉTECTE (il ne corrige pas en silence) :
  - financières : (entité, métrique) avec ≥2 valeurs incompatibles ;
  - documentaires : « aucune pièce (financière) attachée » co-présent avec « N
    pièce(s) jointe(s) », N ≥ 1.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple  # Tuple : hotfix B1.3.62.10.1 (F821)

# Métriques reconnues → libellé canonique
_METRICS = {
    "CA": (r"chiffre\s+d['’]affaires", r"\bCA\b"),
    "Résultat net": (r"r[ée]sultat\s+net",),
    "EBITDA": (r"\bebitda\b",),
    "Résultat d'exploitation": (r"r[ée]sultat\s+d['’]exploitation",),
    "Trésorerie": (r"tr[ée]sorerie",),
    "Stocks": (r"\bstocks?\b",),
}
_METRIC_RES = {k: re.compile("|".join(v), re.IGNORECASE) for k, v in _METRICS.items()}

# Valeur monétaire « 55,8 M€ », « -0,6 M€ », « +1,4 M€ », « 213,4 M€ », « 4,5M€ »
_VALUE_RE = re.compile(r"([+\-]?\d{1,4}(?:[.,]\d{1,3})?)\s*M\s*€", re.IGNORECASE)


def _norm_value(raw: str) -> Optional[float]:
    try:
        return round(float(raw.replace(",", ".")), 3)
    except Exception:
        return None


def _values_incompatible(values: List[float]) -> bool:
    """Vrai si l'ensemble contient deux valeurs réellement incompatibles
    (signe opposé, ou écart relatif > 5 %)."""
    uniq = sorted(set(values))
    if len(uniq) < 2:
        return False
    lo, hi = uniq[0], uniq[-1]
    if (lo < 0) != (hi < 0):          # signes opposés
        return True
    base = max(abs(lo), abs(hi)) or 1.0
    return (abs(hi - lo) / base) > 0.05


def scan_financial_contradictions(text: str, entities: Optional[List[str]] = None) -> List[Dict]:
    """Détecte, par (entité, métrique), des valeurs M€ incompatibles.

    Algorithme précis : chaque couple (métrique, valeur adjacente ≤ 25 car) est
    rattaché à l'entité mentionnée le plus PRÈS en amont (≤ 140 car) — évite la
    contamination inter-entités. Filet narratif : ne lit pas les colonnes de
    tableaux sans mot-clé métrique adjacent (limite assumée)."""
    if not text:
        return []
    if entities:
        ents = sorted(set(entities), key=len, reverse=True)
    else:
        ents = sorted(set(re.findall(
            r"\b[A-ZÀ-Þ][A-ZÀ-Þ’'\-]{3,}(?:\s+[A-ZÀ-Þ][A-ZÀ-Þ’'\-]{2,})?", text)),
            key=len, reverse=True)
    if not ents:
        return []
    ent_rx = re.compile("|".join(re.escape(e) for e in ents), re.IGNORECASE)
    # positions de toutes les mentions d'entité
    ent_pos = [(m.start(), m.group(0)) for m in ent_rx.finditer(text)]

    def _nearest_entity(pos: int) -> Optional[str]:
        best = None
        for start, name in ent_pos:
            if start <= pos and (pos - start) <= 140:
                if best is None or start > best[0]:
                    best = (start, name)
        # normalise vers le libellé canonique fourni
        if not best:
            return None
        nm = best[1].upper()
        for e in ents:
            if e.upper() in nm or nm in e.upper():
                return e
        return best[1]

    # collecte (entité, métrique) -> valeurs
    bucket: Dict[tuple, List[float]] = {}
    for metric, mrx in _METRIC_RES.items():
        for mm in mrx.finditer(text):
            seg = text[mm.end(): mm.end() + 25]
            vm = _VALUE_RE.search(seg)
            if not vm:
                continue
            v = _norm_value(vm.group(1))
            if v is None:
                continue
            ent = _nearest_entity(mm.start())
            if not ent:
                continue
            bucket.setdefault((ent, metric), []).append(v)

    findings: List[Dict] = []
    for (ent, metric), vals in bucket.items():
        if _values_incompatible(vals):
            findings.append({
                "entity": ent, "metric": metric,
                "values": sorted(set(vals)), "severity": "P0",
            })
    return findings


_NO_DOC_RE = re.compile(
    r"aucune\s+pi[èe]ce\s+(?:financi[èe]re\s+)?(?:n['’]a\s+[ée]t[ée]\s+)?(?:attach|jointe|fourni)",
    re.IGNORECASE)
_HAS_DOC_RE = re.compile(r"\b([1-9]\d?)\s+pi[èe]ces?(?:\(s\))?\s+jointes?(?:\(s\))?\b", re.IGNORECASE)


def scan_document_contradictions(text: str) -> List[Dict]:
    if not text:
        return []
    no_doc = _NO_DOC_RE.search(text)
    has_doc = _HAS_DOC_RE.search(text)
    if no_doc and has_doc:
        return [{
            "type": "attachments_presence",
            "values": ["aucune pièce attachée", f"{has_doc.group(1)} pièces jointes"],
            "severity": "P0",
        }]
    return []


# B.1.3 (run dossier industriel (composants), P2) — multiplicateurs contradictoires attachés à un
# même sujet (« R&D 5 à 10 fois supérieurs » vs « R&D 20-30x supérieure ») :
# deux plages DISJOINTES dans le même document = contradiction à signaler
# en Limites, pas à réécrire (le gate FLAGGE, il ne corrige pas).
_MULT_RE = re.compile(
    r"(?:\b1\s*(?:à|a|:|-)\s*)?(\d{1,3})\s*(?:à|a|–|—|-|to)\s*(\d{1,3})\s*"
    r"(?:x\b|fois\b|times\b)|(?:\bx|\b)(\d{1,3})\s*(?:x\b|fois\b|times\b)",
    re.IGNORECASE)
_MULT_SUBJECTS = ("r&d", "r & d", "recherche et développement",
                  "recherche & développement")


def scan_multiplier_contradictions(text: str) -> List[Dict]:
    if not text:
        return []
    ranges: List[Tuple[int, int, str]] = []
    low = text.lower()
    for m in _MULT_RE.finditer(text):
        _ctx = low[max(0, m.start() - 90):m.end() + 90]
        if not any(s in _ctx for s in _MULT_SUBJECTS):
            continue
        if m.group(1) and m.group(2):
            a, b = int(m.group(1)), int(m.group(2))
        elif m.group(3):
            a = b = int(m.group(3))
        else:
            continue
        if a > b:
            a, b = b, a
        if b > 500:            # garde anti-bruit (années, montants)
            continue
        ranges.append((a, b, m.group(0).strip()))
    findings: List[Dict] = []
    for i in range(len(ranges)):
        for j in range(i + 1, len(ranges)):
            (a1, b1, s1), (a2, b2, s2) = ranges[i], ranges[j]
            disjoint = b1 < a2 or b2 < a1
            if disjoint and {s1, s2} == {s1, s2} and s1 != s2:
                findings.append({
                    "type": "multiplier_range", "subject": "R&D",
                    "values": sorted({s1, s2}), "severity": "P2",
                })
    # dédoublonnage sur les paires de valeurs
    seen = set()
    out = []
    for f in findings:
        key = tuple(f["values"])
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def run_contradiction_gate(text: str, entities: Optional[List[str]] = None) -> Dict:
    fin = scan_financial_contradictions(text, entities)
    doc = scan_document_contradictions(text)
    mult = scan_multiplier_contradictions(text)
    return {"financial": fin, "document": doc, "multiplier": mult,
            "n_total": len(fin) + len(doc) + len(mult)}
