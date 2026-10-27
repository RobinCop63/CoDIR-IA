"""v62.13.9.4.49 — point 0 du programme : UN SEUL RÉALISÉ.

Contre-recette ChatGPT du 28/09/2026 (F4) : dans un tableau d'agent intitulé « All figures in thousands
of USD », la colonne « FY… (Actual) » portait un résultat opérationnel inférieur de près de 10 % à celui de la base
sourcée (rapport annuel, confirmé à la page) — le modèle avait reconstruit son réalisé en ajoutant une
ligne d'amortissements à des charges qui l'incluaient déjà. Les projections partaient de ce faux réalisé.

Ce module est un DÉTECTEUR (doctrine du 28/09 : tout livrer, tout signaler) : il lit les tableaux
Markdown d'une sortie d'agent, repère les colonnes de réalisé (« Actual », « Réalisé », « Historical »…,
avec une année), rattache chaque ligne à une métrique de la base de faits confirmés, et signale toute
valeur qui s'écarte de plus de 1 % de la valeur sourcée de même métrique et même exercice. Il ne réécrit
rien : le constat porte la valeur de la pièce, le rendu la place à côté du chiffre.

Garde-fous : aucune échelle devinée (sans mention explicite « en milliers / in thousands / m$ / k$ »,
la ligne n'est pas jugée) ; un taux (%) n'est jamais comparé à un montant ; seuls les faits confirmés
servent de référence. Aucune règle propre à un dossier, une société ou une valeur.
"""
from __future__ import annotations

import re
from typing import Any

_ACTUAL_COL = re.compile(r"(?i)\b(?:actuals?|réalisé|réel|historique|historical|published|publié|reported)\b")
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_SCALE_K = re.compile(r"(?i)\bin\s+thousands\b|\ben\s+milliers\b|thousands\s+of|milliers\s+d|\(\s*[$€£]?\s*000s?\s*\)|\bk\s?(?:usd|eur|gbp)\b|\bk[$€£]|[$€£]\s?k\b")
_SCALE_M = re.compile(r"(?i)\bin\s+millions\b|\ben\s+millions\b|millions\s+of|millions\s+d|\bm\s?(?:usd|eur|gbp)\b|\bm[$€£]|[$€£]\s?m\b|\bmds?\b")
_ROW_ROLE = (
    (re.compile(r"(?i)^(?:net\s+sales|total\s+(?:net\s+)?(?:sales|revenues?)|revenues?|chiffre\s+d['’]affaires)\b"), "REVENUE"),
    (re.compile(r"(?i)^(?:gross\s+profit|marge\s+brute)\b(?!.*%)"), "GROSS_PROFIT"),
    (re.compile(r"(?i)^(?:operating\s+(?:income|profit)|income\s+from\s+operations|résultat\s+(?:d['’]exploitation|opérationnel))\b"), "OPERATING_PROFIT"),
    (re.compile(r"(?i)^(?:net\s+income|net\s+earnings|résultat\s+net)\b"), "NET_INCOME"),
    (re.compile(r"(?i)^(?:cash\s+and\s+cash\s+equivalents|trésorerie)\b"), "CASH"),
    (re.compile(r"(?i)^(?:inventories|stocks)\b"), "STOCKS"),
    (re.compile(r"(?i)^(?:total\s+assets|total\s+(?:de\s+l['’])?actif)\b"), "TOTAL_ASSETS"),
    (re.compile(r"(?i)^(?:trade\s+receivables|accounts\s+receivable|créances\s+clients)\b"), "RECEIVABLES"),
)
_FACT_ROLE_BY_ID = {"REVENUE": "REVENUE", "GROSS_PROFIT": "GROSS_PROFIT", "GROSS_MARGIN": "GROSS_PROFIT",
                    "OPERATING_PROFIT": "OPERATING_PROFIT", "NET_INCOME": "NET_INCOME", "CASH": "CASH",
                    "STOCKS": "STOCKS", "INVENTORIES": "STOCKS", "TOTAL_ASSETS": "TOTAL_ASSETS",
                    "RECEIVABLES": "RECEIVABLES", "TRADE_RECEIVABLES": "RECEIVABLES"}
_CONFIRMED = ("CONFIRMED_ON_PAGE", "DERIVED_FROM_CONFIRMED_ON_PAGE", "CONFIRMED_IN_REGISTRY")


def _get(f: Any, k: str):
    return f.get(k) if isinstance(f, dict) else getattr(f, k, None)


def _fact_role(f: Any) -> str | None:
    if str(_get(f, "unit") or "").upper() in ("PCT", "%", "RATIO"):
        return None
    mid = str(_get(f, "metric_canonical_id") or "").upper()
    if mid in _FACT_ROLE_BY_ID:
        return _FACT_ROLE_BY_ID[mid]
    label = re.sub(r"\s*/.*$", "", str(_get(f, "label") or "")).strip()
    for rx, role in _ROW_ROLE:
        if rx.search(label):
            return role
    return None


def _confirmed_base(facts) -> dict[tuple[str, str], Any]:
    base: dict[tuple[str, str], Any] = {}
    for f in facts or []:
        role = _fact_role(f)
        ps = str(_get(f, "proof_status") or "").upper()
        val = _get(f, "normalized_value")
        years = _YEAR.findall(str(_get(f, "period") or ""))
        if role and ps in _CONFIRMED and val is not None and len(years) == 1:
            base.setdefault((role, years[0]), f)
    return base


_TAG49 = re.compile(r"\s*⟨\s*(?:statut|status)\s*:[^⟩]*(?:⟩|$)", re.I)


def _cells(line: str) -> list[str]:
    s = _TAG49.sub("", line).strip()                  # une étiquette posée en fin de rangée n'est pas une cellule
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _clean_label(c: str) -> str:
    return re.sub(r"[*_`]+", "", c).strip()


def _parse_amount(c: str) -> float | None:
    s = _clean_label(c)
    if not s or "%" in s or not re.search(r"\d", s):
        return None
    neg = bool(re.match(r"^\(.*\)$", s.replace(" ", ""))) or s.startswith(("-", "−", "–"))
    num = re.sub(r"[^\d.,]", "", s)
    if not num:
        return None
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", num):
        num = num.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", num):
        num = num.replace(".", "").replace(",", ".")
    else:
        num = num.replace(",", ".")
    try:
        v = float(num)
    except ValueError:
        return None
    return -v if neg else v


def _scale(context: str, header: str, cell: str) -> float | None:
    for txt in (cell, header, context):
        if _SCALE_K.search(txt or ""):
            return 1e3
        if _SCALE_M.search(txt or ""):
            return 1e6
    return None


def reconcile_table_actuals(text: str, facts, tolerance: float = 0.01) -> list[dict]:
    """Constats : lignes de colonnes « réalisé » qui contredisent la base sourcée confirmée."""
    base = _confirmed_base(facts)
    if not base or not text:
        return []
    lines = str(text).splitlines()
    out: list[dict] = []
    prev: dict | None = None
    i = 0
    while i < len(lines):
        if not lines[i].lstrip().startswith("|"):
            i += 1
            continue
        start = i
        while i < len(lines) and lines[i].lstrip().startswith("|"):
            i += 1
        block = lines[start:i]
        header = _cells(block[0])
        cols = [(k, _YEAR.findall(h)[0]) for k, h in enumerate(header)
                if _ACTUAL_COL.search(h) and len(_YEAR.findall(h)) == 1]
        rows = block[1:]
        context = " ".join(lines[max(0, start - 4):start])
        # Un tableau coupé par une ligne insérée (garde, note) reprend l'en-tête du morceau précédent
        # s'il suit de près et a le même nombre de colonnes (constat de la contre-recette du 28/09).
        if not cols and prev and start - prev["end"] <= 3 and len(header) == prev["ncols"]:
            header, cols, context, rows = prev["header"], prev["cols"], prev["context"], block
        if not cols:
            prev = None
            continue
        prev = {"header": header, "cols": cols, "context": context, "ncols": len(header), "end": i}
        for row in rows:
            if re.fullmatch(r"[\s|:\-]+", row):
                continue
            cells = _cells(row)
            if not cells:
                continue
            label = _clean_label(cells[0])
            role = next((r for rx, r in _ROW_ROLE if rx.search(label)), None)
            if not role:
                continue
            _own_hdr62 = _cells(block[0]) if block else []
            for k, year in cols:
                if k >= len(cells):
                    continue
                # 9.4.62 — recette 9.4.61 : des projections FY2026E à FY2028P marquées [HYP] étaient déclarées « réalisé
                # contredit par la pièce ». Une colonne ou une cellule de projection n'est jamais un réalisé.
                _hk62 = " ".join(str(x) for x in ((header[k] if k < len(header) else ""),
                                                   (_own_hdr62[k] if k < len(_own_hdr62) else ""), cells[k]))
                if re.search(r"(?i)\b(?:FY\s?)?20\d{2}\s?[EP]\b|pr[ée]vision|projection|budget|cible|target|forecast|"
                             r"rebaser|\[HYP|\[ESTIM|hypoth[èe]se|estimat", _hk62):
                    continue
                fact = base.get((role, year))
                amount = _parse_amount(cells[k])
                scale = _scale(context, header[k], cells[k])
                if fact is None or amount is None or scale is None:
                    continue
                table_value = amount * scale
                source_value = float(_get(fact, "normalized_value"))
                gap = abs(table_value - source_value) / max(abs(source_value), 1e-9)
                if gap > tolerance:
                    out.append({"kind": "ACTUAL_CONTRADICTS_SOURCE", "row": row.strip(), "col": k, "metric": role,
                                "period": f"FY{year}", "table_value": table_value, "source_value": source_value,
                                "source_label": str(_get(fact, "value") or ""),
                                "source_doc": str(_get(fact, "source_doc") or ""),
                                "source_page": _get(fact, "source_page"), "gap_pct": round(gap * 100, 2)})
    return out


def tag_contradicted_actuals(text: str, facts, lang: str = "fr") -> tuple[str, list[dict]]:
    """Pose, dans la cellule du réalisé contredit, l'étiquette « ⟨statut : réalisé contredit par la pièce
    (…) : valeur⟩ » ; le rendu la transforme en « ⚠ à vérifier — … » à côté du chiffre. Rien n'est remplacé :
    le chiffre de l'agent reste, la valeur de la pièce est écrite à côté."""
    found = reconcile_table_actuals(text, facts)
    if not found:
        return text, []
    en = str(lang or "fr").lower().startswith("en")
    word = "status" if en else "statut"
    lines = str(text).splitlines()
    for f in found:
        doc = f.get("source_doc") or ("source" if en else "pièce")
        page = f" p.{f['source_page']}" if f.get("source_page") else ""
        motif = (f"actual contradicted by the source ({doc}{page}): {f['source_label']}" if en else
                 f"réalisé contredit par la pièce ({doc}{page}) : {f['source_label']}")
        for i, line in enumerate(lines):
            if line.strip() == f["row"] and motif not in line:
                cells = line.split("|")
                j = f["col"] + (1 if line.lstrip().startswith("|") else 0)
                if 0 <= j < len(cells):
                    cells[j] = cells[j].rstrip() + f" ⟨{word} : {motif}⟩ "
                    lines[i] = "|".join(cells)
                break
    return "\n".join(lines) + ("\n" if str(text).endswith("\n") else ""), found
