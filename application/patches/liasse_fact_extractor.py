"""
patches/liasse_fact_extractor.py — v17.2 (Couche B : extraction structurée page-citée)

PROBLÈME (audit dossier réseau de soins, runs F.6.x) : les faits financiers de la FinancialFactsTable
venaient du NARRATIF des agents (« Narratif agents », sans page) → statut À VÉRIFIER,
preuve faible. La Couche A (`financial_statement_extractor`) trouve déjà OÙ sont les
états financiers et extrait leur texte page par page, mais s'arrête au texte.

Ce module est la Couche B : il lit les PIÈCES (liasse fiscale 2050-2053 + annexe des
comptes annuels) et en extrait des FAITS STRUCTURÉS page-cités
`{libellé, valeur, page, périmètre, entité}` — promus en FAIT (vérifiable à la page),
devant le narratif.

Stratégie (haute précision > rappel) :
  • pages d'ANNEXE propres (présentation, titres de participation, répartition impôt,
    engagements) → couples libellé/valeur fiables ;
  • table TITRES DE PARTICIPATION → extraction POSITIONNELLE (coordonnées x des mots)
    pour lever l'ambiguïté des séparateurs de milliers : CA + résultat par filiale ;
  • on NE touche PAS aux grilles 2050-2052 désordonnées (faible précision) — leurs
    chiffres clés sont de toute façon restitués proprement dans l'annexe.

Dépendance : pdfplumber (déjà utilisé par la Couche A).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# ── Parsing nombres FR ───────────────────────────────────────────────────────
def _num(s: str) -> Optional[int]:
    """« 103 384 978 » / « -557 096 » / « 12 235 806,56 » → int (euros, arrondi)."""
    if not s:
        return None
    s = s.strip().replace("\u202f", " ").replace("\xa0", " ")
    m = re.fullmatch(r"(-?\d[\d ]*)(?:,(\d+))?", s)
    if not m:
        return None
    try:
        return int(m.group(1).replace(" ", ""))
    except ValueError:
        return None


def _fmt_meur(eur: Optional[float]) -> str:
    """123 456 789 → « 123,5 M€ » ; 31 760 000 → « 31,8 M€ »."""
    if eur is None:
        return "—"
    m = eur / 1_000_000.0
    return f"{m:.1f} M€".replace(".", ",")


# ── Table TITRES DE PARTICIPATION — extraction positionnelle ─────────────────
_ENTITY_NAME = re.compile(r"^[A-ZÀ-Ÿ][A-ZÀ-Ÿ' ]{1,30}$")


def _cluster_numbers(frags: List[Dict[str, Any]], gap: float = 4.0) -> List[str]:
    """Regroupe des fragments de mots (triés par x) en NOMBRES. On utilise le VRAI
    blanc inter-mots (x0_courant − x1_précédent) : ~2 px à l'intérieur d'un nombre
    (séparateur de milliers), ≥ ~5 px entre deux colonnes. Bien plus robuste que
    l'écart de x0 (qui fusionnait « 36 409 389 » et « 202 800 162 »)."""
    frags = sorted(frags, key=lambda w: w["x0"])
    out: List[str] = []
    cur: List[str] = []
    prev_x1 = None
    for w in frags:
        if prev_x1 is not None and (w["x0"] - prev_x1) > gap:
            if cur:
                out.append(" ".join(cur))
            cur = []
        cur.append(w["text"])
        prev_x1 = w.get("x1", w["x0"])
    if cur:
        out.append(" ".join(cur))
    return out


def extract_titres_participation(page) -> List[Dict[str, Any]]:
    """Sur une page « TITRES DE PARTICIPATION », renvoie [{entity, ca_eur, rn_eur,
    page}] par filiale. Méthode : on repère les lignes-entités (nom en majuscules),
    on cluster leurs nombres, et APRÈS la quote-part « % » les 3 derniers nombres
    sont [valeur titres, CA HT, résultat] → CA = -2, résultat = -1."""
    try:
        words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    except Exception:
        return []
    page_no = page.page_number
    # 1) lignes-entités : un mot tout en majuscules valant un nom de société, dont
    #    la ligne porte une quote-part « N% » (signature d'une ligne de participation).
    by_top: Dict[int, List[Dict[str, Any]]] = {}
    for w in words:
        by_top.setdefault(round(w["top"]), []).append(w)

    out: List[Dict[str, Any]] = []
    seen = set()
    for top, frags in by_top.items():
        line_txt = " ".join(f["text"] for f in sorted(frags, key=lambda w: w["x0"]))
        if "%" not in line_txt:
            continue
        # nom = mots majuscules en tête (avant le 1er nombre)
        name_parts = []
        for f in sorted(frags, key=lambda w: w["x0"]):
            if re.fullmatch(r"[A-ZÀ-Ÿ][A-ZÀ-Ÿ'\-]+", f["text"]):
                name_parts.append(f["text"])
            elif re.search(r"\d", f["text"]):
                break
        entity = " ".join(name_parts).strip()
        if not entity or entity in ("TOTAL", "SOCIETES"):
            continue
        # fragments numériques (hors quote-part %)
        num_frags = [f for f in frags
                     if re.fullmatch(r"-?\d+", f["text"])]
        # position du token quote-part (contient « % »)
        pct_x = None
        for f in frags:
            if "%" in f["text"]:
                pct_x = f["x0"]
                break
        if pct_x is None:
            continue
        after = [f for f in num_frags if f["x0"] > pct_x]
        nums = _cluster_numbers(after)
        if len(nums) < 3:
            continue
        # [valeur titres, CA HT, résultat] = 3 derniers
        ca_eur = _num(nums[-2])
        rn_eur = _num(nums[-1])
        if entity in seen:
            continue
        seen.add(entity)
        out.append({"entity": entity, "ca_eur": ca_eur, "rn_eur": rn_eur, "page": page_no})
    return out


# ── Couples libellé/valeur sur pages propres ─────────────────────────────────
# Nombre FR « propre » : 1-3 chiffres puis groupes de 3 (séparateur espace/insécable)
# — évite la sur-capture de « 5 692 899 5 964 931 » en un seul nombre.
_N = r"-?\d{1,3}(?:[ \u00a0\u202f]\d{3})*"

# (libellé canonique, regex, périmètre, unité)  — unité « eur » ou « keur ».
_LABEL_PATTERNS = [
    ("Total du bilan",
     re.compile(r"total\s+du\s+bilan\s*:?\s*(" + _N + r")", re.I), "HOLDING", "eur"),
    ("Résultat net",
     re.compile(r"r[ée]sultat\s+avant\s+r[ée]partition\s*:?\s*(" + _N + r")", re.I),
     "HOLDING", "eur"),
    ("Résultat courant avant impôts",
     re.compile(r"r[ée]sultat\s+courant\s+(" + _N + r")", re.I), "HOLDING", "eur"),
    ("Résultat exceptionnel",
     re.compile(r"r[ée]sultat\s+exceptionnel\s+(" + _N + r")", re.I), "HOLDING", "eur"),
    ("Honoraires CAC",
     re.compile(r"honoraires\s+CAC[^.]*?s['’]?[ée]l[èe]vent\s+à\s+(" + _N + r")", re.I),
     "HOLDING", "eur"),
    ("Engagements retraite (IFC)",
     re.compile(r"engagements\s+au\s+31\s+d[ée]cembre\s+2022\s+s['’]?[ée]l[èe]ve\s+à\s+(" + _N + r")\s*K", re.I),
     "HOLDING", "keur"),
]


def extract_label_values(pages_text: List[str]) -> List[Dict[str, Any]]:
    """Couples libellé/valeur fiables (une valeur par ligne). pages_text[i] = page i+1."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for idx, txt in enumerate(pages_text):
        if not txt:
            continue
        page_no = idx + 1
        for label, rx, scope, unit in _LABEL_PATTERNS:
            m = rx.search(txt)
            if not m:
                continue
            eur = _num(m.group(1))
            if eur is None:
                continue
            if unit == "keur":
                eur *= 1000
            if label in seen:
                continue
            seen.add(label)
            out.append({"label": label, "value_eur": float(eur),
                        "page": page_no, "scope": scope, "entity": None})
    return out


# ── Compte courant débiteur intra-groupe (annexe engagements donnés) ─────────
_CC_DEBITEUR = re.compile(
    r"compte\s+courant\s+d[ée]biteur\s+envers\s+(\w+)[^.]*?s['’]?[ée]l[èe]ve\s+à\s+"
    r"(-?\d{1,3}(?:[ \u00a0]\d{3})*)\s+milliers[^.]*?au\s+31\s+d[ée]cembre\s+2021\s*,?\s*contre\s+"
    r"(-?\d{1,3}(?:[ \u00a0]\d{3})*)\s+milliers", re.I)


def extract_intragroup_cc(pages_text: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for idx, txt in enumerate(pages_text):
        if not txt:
            continue
        m = _CC_DEBITEUR.search(txt.replace("\n", " "))
        if m:
            envers = m.group(1)
            cc_2022 = _num(m.group(3))   # « contre X milliers au 31/12/2022 »
            if cc_2022 is not None:
                out.append({
                    "label": f"Compte courant débiteur envers {envers.capitalize()}",
                    "value_eur": float(cc_2022 * 1000), "page": idx + 1,
                    "scope": "SOCIAL_STANDALONE", "entity": (envers.capitalize() if envers else None)})  # B.1.3.23 P0-E
    return out


def _pretty_entity(name: str) -> str:
    """ALPHA→Alpha, BETA→Beta, mais IAV/ADB restent en capitales (sigles),
    dossier réseau de soins ALPES→dossier réseau de soins Alpes."""
    parts = []
    for w in (name or "").split():
        if len(w) <= 3 and w.isupper():        # sigle court : IAV, ADB
            parts.append(w)
        else:
            parts.append(w.capitalize())
    return " ".join(parts)


# ── Grilles CERFA 2050-2053 — extraction POSITIONNELLE ancrée sur les codes ──
# v17.2-L.2 (Couche B+) : lecture directe des liasses 2050 (bilan actif),
# 2051 (bilan passif), 2052 (compte de résultat en liste), 2053 (résultat suite).
# Stratégie haute précision : les chiffres tombent dans des BANDES x stables et
# les codes cellule CERFA (2 caractères, normalisés nationalement) sont des
# ANCRES fiables — bien plus robustes que les libellés (OCR/ordre de lecture
# désordonnés sur ces formulaires TDFC). On lit, par code, la valeur exercice N
# (colonne « Net N ») et N-1 (colonne « Net N-1 »). Parenthèses = négatif.

# Pied de page réglementaire : « DGFiP N° 2050 2023 © Invoke ... ».
_CERFA_FOOTER = re.compile(r"DGFiP\s*N[°ºo]?\s*(205[0-3])", re.I)

# Bandes x (x0 du 1er fragment du nombre) — validées sur liasse Invoke/TDFC réelle.
_BAND_NET_N  = (435.0, 505.0)   # colonne Net exercice N (clôture)
_BAND_NET_N1 = (515.0, 590.0)   # colonne Net exercice N-1 (comparatif)

# Cible canonique par formulaire : (code CERFA, libellé, périmètre).
# Périmètre HOLDING = comptes sociaux société mère (la note de garde le rappelle).
_CERFA_TARGETS: Dict[str, List[tuple]] = {
    "2050": [
        ("CO", "Total du bilan (actif net)",          "HOLDING"),
        ("BJ", "Total actif immobilisé",              "HOLDING"),
        ("CJ", "Total actif circulant",               "HOLDING"),
        ("CU", "Titres de participation (valeur nette)", "HOLDING"),
        ("CF", "Disponibilités",                      "HOLDING"),
    ],
    "2051": [
        ("DA", "Capital social",                      "HOLDING"),
        ("DH", "Report à nouveau",                    "HOLDING"),
        ("DL", "Total capitaux propres",              "HOLDING"),
        ("DI", "Résultat de l'exercice",              "HOLDING"),
        ("DR", "Total provisions pour risques et charges", "HOLDING"),
        ("DU", "Emprunts auprès des établissements de crédit", "HOLDING"),
        ("DX", "Dettes fournisseurs",                 "HOLDING"),
        ("DY", "Dettes fiscales et sociales",         "HOLDING"),
        ("EC", "Total dettes",                        "HOLDING"),
        ("EE", "Total du bilan (passif)",             "HOLDING"),
    ],
    "2052": [
        ("FL", "Chiffre d'affaires net",              "HOLDING"),
        ("FR", "Total produits d'exploitation",       "HOLDING"),
        ("FW", "Autres achats et charges externes",   "HOLDING"),
        ("FY", "Salaires et traitements",             "HOLDING"),
        ("FZ", "Charges sociales",                    "HOLDING"),
        ("GF", "Total charges d'exploitation",        "HOLDING"),
        ("GG", "Résultat d'exploitation",             "HOLDING"),
        ("GP", "Total produits financiers",           "HOLDING"),
        ("GU", "Total charges financières",           "HOLDING"),
        ("GV", "Résultat financier",                  "HOLDING"),
        ("GW", "Résultat courant avant impôts",       "HOLDING"),
    ],
    "2053": [
        ("HD", "Total produits exceptionnels",        "HOLDING"),
        ("HI", "Résultat exceptionnel",               "HOLDING"),
        ("HJ", "Participation des salariés",          "HOLDING"),
        ("HK", "Impôts sur les bénéfices",            "HOLDING"),
        ("HL", "Total des produits",                  "HOLDING"),
        ("HM", "Total des charges",                   "HOLDING"),
        ("HN", "Résultat net (bénéfice ou perte)",    "HOLDING"),
    ],
}


def detect_cerfa_form(page_text: str) -> Optional[str]:
    """Renvoie « 2050 »…« 2053 » si la page est une grille CERFA, sinon None."""
    if not page_text:
        return None
    m = _CERFA_FOOTER.search(page_text)
    return m.group(1) if m else None


def _detect_exercise_years(pages_text: List[str]) -> tuple:
    """(N, N-1) — N = année de CLÔTURE de l'exercice présenté.

    Priorité au libellé canonique « EXERCICE DU 1 JANVIER AAAA AU 31 DÉCEMBRE AAAA »
    (présent sur quasi toutes les pages d'annexe) — non ambigu. À défaut, on prend
    l'année de clôture la plus FRÉQUENTE (mode), jamais le max : une date isolée
    « 31 décembre 2023 » est typiquement un engagement post-clôture (soutien
    financier, échéance de remboursement), pas l'exercice analysé."""
    from collections import Counter
    rx_period = re.compile(
        r"1\s*(?:er)?\s*janvier\s*20\d{2}\s*au\s*31\s*d[ée]cembre\s*(20\d{2})", re.I)
    rx_close = re.compile(
        r"31\s*(?:/|\.|\s)?\s*(?:d[ée]cembre|12)\s*(?:/|\.|\s)?\s*(20\d{2})", re.I)
    period_years, close_years = Counter(), Counter()
    for t in pages_text:
        for m in rx_period.finditer(t or ""):
            period_years[int(m.group(1))] += 1
        for m in rx_close.finditer(t or ""):
            close_years[int(m.group(1))] += 1
    if period_years:
        n = period_years.most_common(1)[0][0]
    elif close_years:
        n = close_years.most_common(1)[0][0]
    else:
        return (None, None)
    return (n, n - 1)


def _num_paren(s: str) -> Optional[int]:
    """« (354 607) » → -354607 ; « 12 235 806 » → 12235806 ; sinon _num()."""
    if not s:
        return None
    s = s.strip().replace("\u202f", " ").replace("\xa0", " ")
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1].strip()
    v = _num(s)
    if v is None:
        return None
    return -v if neg else v


def _read_band_value(row_frags: List[Dict[str, Any]], band: tuple) -> Optional[int]:
    """Lit l'unique nombre d'une bande de colonne sur une ligne. On garde les
    fragments numériques (chiffres, espaces, parenthèses) dont x0 ∈ bande, on les
    cluster au vrai blanc inter-mots, et on retient le cluster (le plus « riche »
    en chiffres si plusieurs — précision > rappel)."""
    lo, hi = band
    cand = []
    for f in row_frags:
        t = (f.get("text") or "").replace("\u202f", " ").replace("\xa0", " ")
        if not re.fullmatch(r"\(?-?\d[\d ]*\)?", t):
            continue
        if lo <= f["x0"] <= hi:
            cand.append(f)
    if not cand:
        return None
    clusters = _cluster_numbers(cand)
    if not clusters:
        return None
    if len(clusters) == 1:
        return _num_paren(clusters[0])
    # plusieurs nombres dans la bande : on prend celui qui a le plus de chiffres
    best = max(clusters, key=lambda c: sum(ch.isdigit() for ch in c))
    return _num_paren(best)


def extract_cerfa_grid(page, form_id: str, year_n: Optional[int],
                       year_n1: Optional[int]) -> List[Dict[str, Any]]:
    """Extrait les agrégats canoniques d'une grille CERFA (2050-2053) par ancrage
    sur les codes cellule. Renvoie un fait par (métrique × exercice présent)."""
    targets = _CERFA_TARGETS.get(form_id) or []
    if not targets:
        return []
    try:
        words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    except Exception:
        return []
    page_no = page.page_number
    out: List[Dict[str, Any]] = []
    for code, label, scope in targets:
        anchors = [w for w in words if (w.get("text") or "") == code]
        if not anchors:
            continue
        a = anchors[0]
        row = [w for w in words if abs(w["top"] - a["top"]) <= 3.0]
        v_n  = _read_band_value(row, _BAND_NET_N)
        v_n1 = _read_band_value(row, _BAND_NET_N1)
        for val, yr in ((v_n, year_n), (v_n1, year_n1)):
            if val is None:
                continue
            lab = f"{label} {yr}" if yr else label
            out.append({"label": lab, "value_eur": float(val), "page": page_no,
                        "scope": scope, "entity": None,
                        "method": f"cerfa_{form_id}", "cerfa_code": code, "year": yr})
    return out


# ── Orchestration ────────────────────────────────────────────────────────────
def extract_liasse_facts(pdf_source, source_doc: Optional[str] = None) -> List[Dict[str, Any]]:
    """Extrait les faits structurés page-cités d'une liasse/plaquette PDF native.

    `pdf_source` accepte un CHEMIN (str) ou des OCTETS (bytes/BytesIO) — en app.py
    les PDF arrivent en octets dans la boucle de scan financier.

    Renvoie une liste de dicts :
      {label, value_eur, value_display, page, scope, entity, source_doc, method}
    """
    try:
        import pdfplumber
    except Exception:
        return []
    import io
    if isinstance(pdf_source, (bytes, bytearray)):
        opener = io.BytesIO(bytes(pdf_source))
        src = source_doc or "liasse PDF"
    elif hasattr(pdf_source, "read"):
        opener = pdf_source
        src = source_doc or "liasse PDF"
    else:
        opener = pdf_source
        src = source_doc or _short_name(pdf_source)
    facts: List[Dict[str, Any]] = []
    try:
        with pdfplumber.open(opener) as pdf:
            pages_text = [(p.extract_text() or "") for p in pdf.pages]
            year_n, year_n1 = _detect_exercise_years(pages_text)
            # 0) grilles CERFA 2050-2053 (bilan + compte de résultat), positionnel
            for i, p in enumerate(pdf.pages):
                form_id = detect_cerfa_form(pages_text[i] or "")
                if not form_id:
                    continue
                for d in extract_cerfa_grid(p, form_id, year_n, year_n1):
                    facts.append(_mk(d["label"], d["value_eur"], d["page"], d["scope"],
                                     d.get("entity"), src, d.get("method", "cerfa")))
            # 1) couples libellé/valeur propres
            for d in extract_label_values(pages_text):
                facts.append(_mk(d["label"], d["value_eur"], d["page"], d["scope"],
                                 d.get("entity"), src, "annexe"))
            # 2) compte courant intra-groupe
            for d in extract_intragroup_cc(pages_text):
                facts.append(_mk(d["label"], d["value_eur"], d["page"], d["scope"],
                                 d.get("entity"), src, "annexe"))
            # 3) titres de participation (positionnel) — CA + RN par filiale
            for i, p in enumerate(pdf.pages):
                if "TITRES DE PARTICIPATION" in (pages_text[i] or "").upper():
                    for row in extract_titres_participation(p):
                        ent = _pretty_entity(row["entity"])
                        if row.get("ca_eur") is not None:
                            facts.append(_mk(f"Chiffre d'affaires {ent}", row["ca_eur"],
                                             row["page"], "SOCIAL_STANDALONE", ent, src,
                                             "titres_participation"))
                        if row.get("rn_eur") is not None:
                            facts.append(_mk(f"Résultat net {ent}", row["rn_eur"],
                                             row["page"], "SOCIAL_STANDALONE", ent, src,
                                             "titres_participation"))
    except Exception:
        return facts
    return facts


def _short_name(path: str) -> str:
    import os
    base = os.path.basename(path or "")
    return (base[:40] + "…") if len(base) > 41 else (base or "liasse PDF")


def _mk(label, value_eur, page, scope, entity, src, method) -> Dict[str, Any]:
    return {
        "label": label,
        "value_eur": value_eur,
        "value_display": _fmt_meur(value_eur),
        "page": int(page),
        "scope": scope,
        "entity": entity,
        "source_doc": src,
        "method": method,
    }


_LIASSE_METRIC_IDS = {
    "ca": "REVENUE",
    "resultat_net": "NET_INCOME",
    "resultat_courant": "OPERATING_PROFIT",
    "bilan": "BALANCE_SHEET_TOTAL",
}


def build_liasse_financial_facts(liasse_facts):
    """Convert extracted liasse/CERFA rows into page-confirmed ledger facts.

    This is the pre-engine path used by v62.12.  The historical post-run row
    promotion remains for compatibility, but only these typed objects can feed
    the proof layer, KPI claims and current-period authority.
    """
    try:
        import hashlib
        from utils.financial_facts_table import FinancialFact, FactStatus
    except Exception:
        return []
    out = []
    for lf in liasse_facts or []:
        label = str(lf.get("label") or "").strip()
        _low_label = label.lower()
        if "chiffre d'affaires" in _low_label or "chiffre d’affaires" in _low_label:
            metric_id = "REVENUE"
        elif ("résultat d'exploitation" in _low_label or
              "resultat d'exploitation" in _low_label or
              "résultat courant" in _low_label or "resultat courant" in _low_label):
            metric_id = "OPERATING_PROFIT"
        elif ("résultat de l'exercice" in _low_label or
              "resultat de l'exercice" in _low_label or
              "résultat net" in _low_label or "resultat net" in _low_label):
            metric_id = "NET_INCOME"
        elif "bilan" in _low_label:
            metric_id = "BALANCE_SHEET_TOTAL"
        else:
            metric_key, _entity = _fact_key(label)
            metric_id = _LIASSE_METRIC_IDS.get(metric_key or "", "")
        if not metric_id:
            continue
        try:
            value_eur = float(lf.get("value_eur"))
            page = int(lf.get("page"))
        except Exception:
            continue
        years = [int(y) for y in re.findall(r"\b(20\d{2})\b", label)]
        year = max(years) if years else None
        period = f"FY{year}" if year else ""
        period_end = f"{year}-12-31" if year else ""
        source_doc = str(lf.get("source_doc") or "liasse PDF")
        scope = str(lf.get("scope") or "UNKNOWN")
        stable_raw = f"{metric_id}|{period}|{scope}|{lf.get('entity') or ''}"
        stable = "LF-" + hashlib.sha256(stable_raw.encode("utf-8")).hexdigest()[:20]
        inst_raw = f"{stable}|{source_doc}|{page}|{value_eur}"
        instance = "LFI-" + hashlib.sha256(inst_raw.encode("utf-8")).hexdigest()[:20]
        fact = FinancialFact(
            label=label,
            value=str(lf.get("value_display") or _fmt_meur(value_eur)),
            source_doc=source_doc,
            source_page=page,
            source_section="Liasse fiscale / CERFA",
            status=FactStatus.FAIT,
            confidence=0.99,
            scope=scope,
            allowed_uses=["narrative", "finance_model", "comparison"],
            metric_canonical_id=metric_id,
            period=period,
            unit="CUR",
            currency="EUR",
            scale="unit",
            normalized_value=value_eur,
            perimeter_entity=str(lf.get("entity") or ""),
            source_type="attachment_liasse",
            source_id=f"{source_doc}:p{page}",
            document_date=period_end,
            retrieved_at="",
            stable_fact_key=stable,
            fact_instance_id=instance,
            board_safe_candidate=True,
            proof_status="CONFIRMED_ON_PAGE",
            source_excerpt=f"{label}: {lf.get('value_display') or value_eur}",
            source_value_text=str(lf.get("value_display") or value_eur),
            period_end_date=period_end,
            source_document_date=period_end,
            proof_layer_version="v62.12-liasse",
            source_priority=5,
        )
        out.append(fact)
    return out


# ── Promotion vers la FinancialFactsTable (FAIT page-cité) ───────────────────
def _fact_key(label: str):
    """Normalise un libellé en (métrique, entité) pour dédupliquer narratif ↔ liasse.
    Précédence stricte : « compte courant » AVANT « courant »."""
    l = (label or "").lower()
    if "compte courant" in l or l.strip().startswith("cc "):
        metric = "cc"
    elif "bilan" in l:
        metric = "bilan"
    elif "honoraires" in l:
        metric = "honoraires_cac"
    elif "retraite" in l or "ifc" in l:
        metric = "ifc"
    elif "résultat courant" in l or "resultat courant" in l:
        metric = "resultat_courant"
    elif "exceptionnel" in l:
        metric = "resultat_exceptionnel"
    elif "résultat" in l or "resultat" in l or l.strip().startswith("rn "):
        metric = "resultat_net"
    elif "chiffre d'affaires" in l or "chiffre d’affaires" in l or "chiffre" in l \
            or l.strip().startswith("ca ") or "revenue" in l:
        metric = "ca"
    else:
        metric = None
    entity = None
    from utils.entity_aliases import get_entity_aliases
    for e in [a.lower() for a in get_entity_aliases()]:
        if e in l:
            entity = e
            break
    return (metric, entity)


def promote_liasse_facts(existing_rows, liasse_facts, source_doc: Optional[str] = None):
    """Promeut les faits liasse en FAIT page-cité et les place EN TÊTE de la table.
    Supersède (retire) les lignes narratives NON page-citées du même couple
    (métrique, entité) — la preuve lue à la page l'emporte.

    Args
      existing_rows : list[dict]  — lignes déjà sérialisées (FinancialFact.to_row_dict)
      liasse_facts  : list[dict]  — sortie de extract_liasse_facts()
    Returns
      (new_rows, n_added, n_superseded)
    """
    try:
        from utils.financial_facts_table import FinancialFact, FactStatus
    except Exception:
        return existing_rows, 0, 0

    promoted_rows = []
    promoted_keys = set()
    for lf in liasse_facts:
        try:
            eur = int(round(float(lf["value_eur"])))
        except Exception:
            eur = None
        note = (f"Lu à la source — page {lf['page']} (valeur exacte "
                f"{eur:,} €)".replace(",", " ")) if eur is not None else \
               f"Lu à la source — page {lf['page']}"
        ff = FinancialFact(
            label=lf["label"],
            value=lf.get("value_display", "—"),
            source_doc=lf.get("source_doc") or source_doc,
            source_page=int(lf["page"]),
            source_section="Liasse fiscale / Annexe des comptes annuels",
            status=FactStatus.FAIT,
            confidence=0.98,
            scope=lf.get("scope", "UNKNOWN"),
            notes=[note],
        )
        promoted_rows.append(ff.to_row_dict())
        k = _fact_key(lf["label"])
        if k[0] is not None:
            promoted_keys.add(k)

    fait_label = FactStatus.FAIT.value
    kept, n_super = [], 0
    for row in (existing_rows or []):
        k = _fact_key(row.get("label", ""))
        is_fait = str(row.get("status", "")).upper().startswith(fait_label.upper())
        if k[0] is not None and k in promoted_keys and not is_fait:
            n_super += 1
            continue
        kept.append(row)

    return promoted_rows + kept, len(promoted_rows), n_super
