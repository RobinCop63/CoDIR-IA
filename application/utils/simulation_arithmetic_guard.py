"""v62.13.9.4.29 — cohérence arithmétique des simulations (audit du dossier industriel v28, P1).

Un tableau de projection qui affiche « FCF = EBITDA − CAPEX − Variation BFR »
et publie des FCF qui ne suivent pas cette formule (les amortissements retranchés
une fois de trop) reste dans le document de travail — mais statué : la ligne FCF
porte le recalcul selon la formule affichée, et les conclusions qui en dépendent
(« FCF structurellement négatif », « crise de liquidité ») portent un statut.
Aucune valeur de dossier dans ce module : seules des étiquettes de lignes de
simulation (EBITDA, EBIT, amortissements, CAPEX, variation de BFR, FCF).
"""
from __future__ import annotations
import re
from typing import Any

_LABELS = {
    "ebitda": re.compile(r"^\s*\**\s*ebitda\b", re.I),
    "ebit": re.compile(r"^\s*\**\s*(?:ebit|r[ée]sultat d['’]exploitation|rex)\b(?!da)", re.I),
    "da": re.compile(r"^\s*\**\s*(?:dotations?\s+aux\s+)?amortissements?|^\s*\**\s*d\s*&\s*a\b|^\s*\**\s*da\b", re.I),
    "capex": re.compile(r"^\s*\**\s*(?:capex|investissements?(?:\s+industriels?)?)\b", re.I),
    "dbfr": re.compile(r"^\s*\**\s*(?:variation|Δ|delta)\s*(?:du\s+|de\s+)?bfr|^\s*\**\s*bfr\s*\(?\s*variation", re.I),
    "fcf": re.compile(r"^\s*\**\s*(?:fcf|free\s*cash\s*-?flow|flux de tr[ée]sorerie (?:disponible|libre)s?)\b", re.I),
}
_FORMULA_RE = re.compile(r"fcf\s*=\s*ebitda\s*[−\-–]\s*capex\s*[−\-–]\s*(?:variation|Δ|delta)?\s*(?:du\s+|de\s+)?bfr", re.I)
_NUM_RE = re.compile(r"^\s*\(?\s*([+−\-–]?\s?\d[\d\s\u00a0\u202f]*(?:[.,]\d+)?)\s*\)?\s*(?:M€|k€|€|m|k)?\s*$", re.I)
# v62.13.9.4.31 — une cellule de budget peut porter une fourchette (« 5,8-5,9 M€ »)
# ou une périodicité (« 0,2-0,3/an ») : on lit la borne basse, sans rien inventer.
_RANGE_CELL_RE = re.compile(
    r"^\s*\**\s*([+−\-–]?\d[\d\s\u00a0\u202f]*(?:[.,]\d+)?)\s*[-–]\s*\d[\d\s\u00a0\u202f]*(?:[.,]\d+)?"
    r"\s*(?:M€|k€|€|m|k)?\s*(?:/\s*an|/\s*year|par\s+an)?\s*\**\s*$", re.I)


def _num(cell: str):
    # « -16,6 [CALCUL] », « +1,0 [ESTIM] » : le tag d'agent suit le nombre
    raw = re.sub(r"\s*\[[^\]]{1,30}\]\s*", " ", str(cell or "").replace("**", ""))
    mr = _RANGE_CELL_RE.match(raw)          # v62.13.9.4.31 — fourchette : borne basse
    if mr:
        try:
            return float(mr.group(1).replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
                         .replace("−", "-").replace("–", "-").replace(",", "."))
        except ValueError:
            return None
    m = _NUM_RE.match(raw)
    if not m:
        return None
    raw = m.group(1).replace("\u00a0", "").replace("\u202f", "").replace(" ", "").replace("−", "-").replace("–", "-").replace(",", ".")
    try:
        v = float(raw)
    except ValueError:
        return None
    return -v if str(cell).strip().startswith("(") else v


def _fmt(v: float) -> str:
    return f"{v:+.1f}".replace(".", ",").replace("+", "")


def _rows(table_lines: list[str]) -> list[list[str]]:
    out = []
    for ln in table_lines:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if cells and not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            out.append(cells)
    return out


def check_text(text: str) -> list[dict[str, Any]]:
    """Retourne les incohérences trouvées dans les tableaux markdown du texte."""
    findings: list[dict[str, Any]] = []
    if not text or not _FORMULA_RE.search(text):
        return findings
    for ti, m in enumerate(re.finditer(r"((?:^\|[^\n]*\n?){2,})", text, re.M)):
        rows = _rows(m.group(1).splitlines())
        if len(rows) < 3:
            continue
        found: dict[str, list[str]] = {}
        for r in rows:
            for key, rx in _LABELS.items():
                if key not in found and rx.search(r[0]):
                    found[key] = r
                    break
        if "fcf" not in found or "ebitda" not in found or "capex" not in found:
            continue
        ncol = min(len(found["fcf"]), len(found["ebitda"]), len(found["capex"]))
        mismatched, expected, published, alt_ok = [], [], [], []
        for ci in range(1, ncol):
            f, e, c = _num(found["fcf"][ci]), _num(found["ebitda"][ci]), _num(found["capex"][ci])
            if f is None or e is None or c is None:
                continue
            d = _num(found["dbfr"][ci]) if "dbfr" in found and len(found["dbfr"]) > ci else 0.0
            d = 0.0 if d is None else d
            exp = e - abs(c) - d
            if abs(exp - f) > max(0.15, 0.02 * abs(exp)):
                mismatched.append(rows[0][ci] if len(rows[0]) > ci else str(ci))
                expected.append(exp); published.append(f)
                da = _num(found["da"][ci]) if "da" in found and len(found["da"]) > ci else None
                ebit = _num(found["ebit"][ci]) if "ebit" in found and len(found["ebit"]) > ci else (e - abs(da) if da is not None else None)
                alt_ok.append(ebit is not None and abs((ebit - abs(c) - d) - f) <= max(0.15, 0.02 * abs(f)))
        if mismatched:
            findings.append({"table_index": ti, "columns": mismatched, "published": published, "expected": expected,
                             "explanation": ("EBIT retenu à la place de l'EBITDA : amortissements retranchés une fois de trop"
                                             if alt_ok and all(alt_ok) else "écart non expliqué par la formule affichée"),
                             "fcf_row": found["fcf"][0]})
    return findings


def tag_text(text: str, findings: list[dict[str, Any]], lang: str = "fr", mode: str = "work") -> str:
    """Statue la ligne FCF de chaque tableau incohérent et les conclusions qui en dépendent.
    En synthèse (pas de statut dans une projection lisible), la conclusion porte une
    réserve en clair au lieu d'un statut."""
    if not findings:
        return text
    en = str(lang or "fr").lower().startswith("en")
    if str(mode or "work") == "synthesis":
        dep = re.compile(r"(?im)^(?!\|)(?=.*(?:\bfcf\b|free\s*cash|flux de tr[ée]sorerie))(?=.*(?:n[ée]gatif|crise|liquidit[ée]|besoin de financement|insolvab)).*$")
        cav = (" — conclusion fondée sur une simulation à recalculer (formule affichée non respectée), pas un constat de liquidité réelle" if not en
               else " — conclusion based on a simulation to be recomputed (stated formula not followed), not an actual liquidity finding")
        return dep.sub(lambda mm: mm.group(0) if "simulation à recalculer" in mm.group(0) or "to be recomputed" in mm.group(0) else mm.group(0).rstrip(".") + cav + ".", text)
    out = text
    for f in findings:
        recalc = " ; ".join(_fmt(v) for v in f["expected"])
        tag = (f" ⟨statut : incohérent avec la formule affichée FCF = EBITDA − CAPEX − ΔBFR — recalcul {recalc} — {f['explanation']}⟩" if not en
               else f" ⟨status: inconsistent with the stated formula FCF = EBITDA − CAPEX − ΔWC — recomputed {recalc} — {f['explanation']}⟩")
        label = re.escape(f["fcf_row"])
        # une ligne déjà statuée garde son statut : la raison arithmétique s'y ajoute
        out, n = re.subn(rf"(?m)^(\|\s*{label}\s*\|[^\n]*?)(?:\s*⟨(?:statut|status)\s*:\s*([^⟩]*)⟩)?\s*$",
                         lambda mm: mm.group(1).rstrip() + (f" ⟨statut : {mm.group(2).strip()} ; " + tag.strip().replace("⟨statut : ", "", 1)
                                                            if mm.group(2) else tag), out, count=1)
    dep = re.compile(r"(?im)^(?!\|)(?=.*(?:\bfcf\b|free\s*cash|flux de tr[ée]sorerie))(?=.*(?:n[ée]gatif|crise|liquidit[ée]|besoin de financement|insolvab)).*$")
    dtag = (" ⟨statut : conclusion fondée sur une simulation à recalculer — non un constat de liquidité réelle⟩" if not en
            else " ⟨status: conclusion based on a simulation to be recomputed — not an actual liquidity finding⟩")
    def _dep_tag(mm):
        line = mm.group(0)
        if "simulation à recalculer" in line or "to be recomputed" in line:
            return line
        m2 = re.search(r"\s*⟨(?:statut|status)\s*:\s*([^⟩]*)⟩\s*$", line)
        if m2:
            return line[:m2.start()] + f" ⟨statut : {m2.group(1).strip()} ; " + dtag.strip().replace("⟨statut : ", "", 1)
        return line + dtag
    out = dep.sub(_dep_tag, out)
    return out


_LIQUIDITY_CLAIM_RE = re.compile(
    r"(?im)^(?!\|)(?=.*(?:d[ée]faillance|cessation de paiement|insolvab|faillite|"
    r"crise de liquidit[ée]|rupture de tr[ée]sorerie|capitaux propres n[ée]gatifs|"
    r"augmentation de capital|recapitalisation|refinancement))"
    r"(?=.*(?:\bdoit\b|\bdevra\b|\bfaut\b|\bnécessaire\b|\bimm[ée]diate\b|\burgen|\bpriorit[ée] absolue\b|"
    r"\bsera\b|\best en\b|\bsans\b|\bd[èe]s \d{4}\b|\brisque de\b)).*$")


def bound_liquidity_conclusions(text: str, established: bool, lang: str = "fr", mode: str = "work") -> tuple[str, int]:
    """v62.13.9.4.30 — contre-audit croisé du 09/09 : « Sans augmentation de capital…
    la société est en risque de défaillance dès 2027 » alors que le dossier déclare
    une situation financière courante NON ÉTABLIE. Une conclusion de défaillance ou
    de recapitalisation ne peut pas être formulée comme une nécessité actuelle si la
    trésorerie et la dette consolidées ne sont pas établies : elle porte alors une
    réserve de portée. Rien n'est supprimé, et si la situation est établie, rien
    n'est ajouté."""
    if established or not text:
        return text, 0
    en = str(lang or "fr").lower().startswith("en")
    tag = (" ⟨statut : conclusion sous hypothèses — trésorerie et dette consolidées non établies dans le dossier⟩" if not en
           else " ⟨status: conclusion under assumptions — consolidated cash and debt not established in the dossier⟩")
    cav = (" — sous hypothèses : la trésorerie et la dette consolidées ne sont pas établies dans le dossier" if not en
           else " — under assumptions: consolidated cash and debt are not established in the dossier")
    n = 0

    def _sub(m):
        nonlocal n
        line = m.group(0)
        if "non établies dans le dossier" in line or "not established in the dossier" in line:
            return line
        n += 1
        if str(mode) == "synthesis":
            return line.rstrip().rstrip(".") + cav + "."
        m2 = re.search(r"\s*⟨(?:statut|status)\s*:\s*([^⟩]*)⟩\s*$", line)
        if m2:
            return line[:m2.start()] + f" ⟨statut : {m2.group(1).strip()} ; " + tag.strip().replace("⟨statut : ", "", 1)
        return line.rstrip() + tag

    return _LIQUIDITY_CLAIM_RE.sub(_sub, text), n


_TOTAL_ROW = re.compile(r"^\s*\|?\s*\**\s*(?:total|somme|cumul|sous[- ]total|total\s+g[ée]n[ée]ral|grand\s+total|sum)\b", re.I)


# une ligne de RATIO se reconnaît à son libellé (taux, ratio, marge (%), rentabilité…) ou à une
# valeur en % — jamais à un simple « % » dans un libellé descriptif (« Marketing (5 % CA) » est un montant)
_RATIO_ROW = re.compile(r"(?i)\b(?:taux|ratio|pourcentage|rentabilit[ée]|ROCE|ROE|ROI|leverage|levier|gearing|coverage|couverture|DSO|DPO|DIO)\b"
                        r"|\bmarge\s*(?:brute|nette|op[ée]rationnelle|d['’]ebitda)?\s*(?:\(%\)|en\s*%|%\s*$)|\(\s*%\s*\)\s*$|\bBFR\s*/\s*CA\b")
_MEMO_ROW = re.compile(r"(?i)^\s*\|?\s*\**\s*(?:dont\b|of which\b|pour m[ée]moire|memo\b|rappel\b|dette nette|net debt|tr[ée]sorerie nette|net cash|variation\b|delta\b|[ée]cart\b)")


def _additive_candidates(rows: list[list[str]], ci: int, t_idx: int, total_rows: set[int]) -> list[list[float]]:
    """Groupes de lignes plausiblement additionnés dans un total (v62.13.9.4.32, C)."""
    def _val(i: int):
        r = rows[i]
        if len(r) <= ci or _RATIO_ROW.search(r[0]) or _MEMO_ROW.match(r[0]) or "%" in str(r[ci]):
            return None
        return _num(r[ci])
    # (a) les postes depuis le total précédent (un côté du bilan, une section)
    prev = max([i for i in total_rows if i < t_idx], default=0)
    block = [v for v in (_val(i) for i in range(prev + 1, t_idx) if i not in total_rows) if v is not None]
    # (b) les sous-totaux qui précèdent (total général de sections)
    subs = [v for v in (_num(rows[i][ci]) if len(rows[i]) > ci else None for i in sorted(total_rows) if i < t_idx) if v is not None]
    # (c) tous les postes depuis l'en-tête (ancien comportement : tableau à un seul total)
    alls = [v for v in (_val(i) for i in range(1, t_idx) if i not in total_rows) if v is not None]
    return [g for g in (block, subs, alls) if len(g) >= 2]


def check_totals(text: str) -> list[dict[str, Any]]:
    """v62.13.9.4.31 — contre-audit v30 (§4) : une ligne de budget retirée pendant
    la neutralisation laissait un TOTAL qui l'incluait encore ; l'addition des
    postes visibles ne retrouvait plus le total publié. On compare, dans chaque
    tableau, la somme des postes affichés au total publié : l'écart est signalé,
    jamais corrigé — recalculer un total à la place de l'auteur serait pire.

    v62.13.9.4.32 (C) — LE BON GROUPE, PAS TOUT LE TABLEAU. Contre-audit du
    dossier industriel (F1) : le contrôle additionnait actif, passif et dette
    nette contre le seul TOTAL ACTIF et annonçait des écarts de 165, 172 et
    180 M€ sur un bilan pourtant équilibré. Chaque total est confronté aux
    groupes plausibles — les postes depuis le total précédent (un côté du
    bilan, une section), les sous-totaux qui le précèdent, ou tous les postes
    depuis l'en-tête (tableau à un seul total) — ; les lignes de ratio, de
    pourcentage et les lignes « pour mémoire » (dont, dette nette, variation)
    ne sont jamais additionnées. Un écart n'est signalé que si AUCUN groupe ne
    retrouve le total publié ; il est alors mesuré sur le groupe le plus proche.
    """
    findings: list[dict[str, Any]] = []
    for ti, m in enumerate(re.finditer(r"((?:^\|[^\n]*\n?){3,})", str(text or ""), re.M)):
        rows = _rows(m.group(1).splitlines())
        if len(rows) < 3:
            continue
        ncol = max(len(r) for r in rows)
        total_rows = {i for i, r in enumerate(rows) if i > 0 and r and _TOTAL_ROW.match(r[0])}
        for ci in range(1, ncol):
            for t_idx in sorted(total_rows):
                total_row = rows[t_idx]
                if len(total_row) <= ci:
                    continue
                total = _num(total_row[ci])
                if total is None:
                    continue
                # 9.4.52 — contre-recette ChatGPT du 05/10 : un tableau RÉCAPITULATIF (ventes, marge brute, charges, résultat,
                # reprise fiscale, trésorerie, total actif) n'est pas une décomposition du total actif ; l'additionner
                # fabriquait un « écart de 996,2 » à investiguer. Un total de BILAN n'est confronté qu'à des postes de bilan.
                if _BS_TOTAL52.search(str(total_row[0] or "")) and any(
                        r and _PL_LABEL52.search(str(r[0] or "")) for r in rows[1:t_idx]):
                    continue
                cands = _additive_candidates(rows, ci, t_idx, total_rows)
                if not cands:
                    continue
                tol = max(0.05 * abs(total), 0.15)
                if any(abs(sum(g) - total) <= tol for g in cands):
                    continue
                best = min(cands, key=lambda g: abs(sum(g) - total))
                ssum = sum(best)
                findings.append({"table_index": ti, "column": (rows[0][ci] if len(rows[0]) > ci else str(ci)),
                                 "published_total": total, "sum_of_visible": round(ssum, 2),
                                 "gap": round(total - ssum, 2), "total_row": total_row[0]})
    return findings


_BS_TOTAL52 = re.compile(r"(?i)\b(?:actif|passif|bilan|assets|liabilities|equity|capitaux\s+propres)\b")
_PL_LABEL52 = re.compile(r"(?i)chiffre\s+d['’]affaires|\bventes\b|\brevenues?\b|\bsales\b|\bmarge\b|\bmargin\b|r[ée]sultat|"
                         r"\bincome\b|\bprofit\b|EBITDA|\bEBIT\b|\bcharges\b|\bexpenses\b|SG&A|imp[ôo]ts?\b|\btax\b|"
                         r"\breprise\b|\bBPA\b|\bEPS\b|dividende|co[uû]t\s+des\s+ventes|\bCOGS\b")


def tag_totals(text: str, findings: list[dict[str, Any]], lang: str = "fr", mode: str = "work") -> str:
    if not findings:
        return text
    en = str(lang or "fr").lower().startswith("en")
    out = text
    for f in findings:
        gap = f"{abs(f['gap']):.1f}".replace(".", ",")
        note = (f"la somme des postes affichés ne retrouve pas le total publié (écart {gap}) — poste retiré ou total à vérifier"
                if not en else
                f"the sum of the visible items does not match the published total (gap {gap}) — a line was withheld or the total needs checking")
        label = re.escape(f["total_row"])
        pat = rf"(?m)^(\|\s*{label}\s*\|[^\n]*?)(?:\s*⟨(?:statut|status)\s*:\s*([^⟩]*)⟩)?\s*$"
        if str(mode) == "synthesis":
            out = re.sub(pat, lambda mm: mm.group(1).rstrip() + f" — {note}", out, count=1)
        else:
            out = re.sub(pat, lambda mm: mm.group(1).rstrip() + (
                f" ⟨statut : {mm.group(2).strip()} ; {note}⟩" if mm.group(2) else f" ⟨statut : {note}⟩"), out, count=1)
    return out



# ── v62.13.9.4.32 (C) — rapprochement trésorerie du bilan ↔ flux net ────────
_CASH_ROW = re.compile(r"(?i)^\s*\|?\s*\**\s*(?:tr[ée]sorerie(?:\s+(?:nette|disponible|fin\s+de\s+p[ée]riode|de\s+cl[ôo]ture))?|disponibilit[ée]s|cash(?:\s+(?:at\s+)?(?:end|closing))?|liquidit[ée]s)\s*(?:\(|\[|\||$)")
_FLOW_ROW = re.compile(r"(?i)^\s*\|?\s*\**\s*(?:variation\s+(?:nette\s+)?de\s+(?:la\s+)?tr[ée]sorerie|flux\s+(?:net|total)(?:\s+de\s+tr[ée]sorerie)?|net\s+cash\s*flow|change\s+in\s+cash|tr[ée]sorerie\s+(?:nette\s+)?g[ée]n[ée]r[ée]e|cash\s+g[ée]n[ée]r[ée])\b")
_YEAR_HDR = re.compile(r"^\s*(?:FY|Exercice\s*)?((?:19|20)\d{2})\s*[eEpP]?\s*$")


def _year_columns(header: list[str]) -> dict[int, str]:
    out = {}
    for i, h in enumerate(header):
        m = _YEAR_HDR.match(str(h or "").replace("**", "").strip())
        if m:
            out[i] = m.group(1)
    return out


_UNIT_CTX_RE = re.compile(r"(?i)(?<![\w])(?:en\s+)?(?:(m€|millions?\s+d['’]euros|m\s*eur|meur|€m)|(k€|milliers?\s+d['’]euros|k\s*eur|keur|€k)|(€|eur|euros))(?![\w])")
_UNIT_FACTOR = {"M": 1000.0, "k": 1.0, "u": 0.001}


def _table_unit(table_text: str, context: str) -> str | None:
    """Unité d'un tableau — 'M', 'k', 'u' (euros) — depuis son en-tête ou son
    contexte proche ; None quand elle n'est pas déterminable (v62.13.9.4.33)."""
    cells = re.findall(r"\d[\d\s\u00a0\u202f.,]*\s*(M€|k€|€)", table_text)
    if cells:
        top = max(set(cells), key=cells.count)
        return {"M€": "M", "k€": "k", "€": "u"}[top]
    # l'en-tête du tableau d'abord, puis le contexte qui le précède — l'unité la
    # plus PROCHE du tableau fait foi (le contexte peut contenir le tableau précédent)
    m = _UNIT_CTX_RE.search("\n".join(table_text.splitlines()[:2]))
    if not m:
        ctx = (context or "").split("\n\n")
        ctx = [c for c in ctx if c.strip() and not c.lstrip().startswith("|")]
        ms = list(_UNIT_CTX_RE.finditer(ctx[-1])) if ctx else []
        m = ms[-1] if ms else None
    if not m:
        return None
    if m.group(1):
        return "M"
    if m.group(2):
        return "k"
    return "u"


def check_cash_reconciliation(text: str) -> list[dict[str, Any]]:
    """Contre-audit du dossier industriel (F2) : le bilan affichait une trésorerie
    de 8 M€ fin 2027 puis 7 M€ fin 2028 (−1,0) quand le tableau de flux
    annonçait −0,2 pour 2028 — écart 0,8, sans rapprochement. On confronte,
    d'un tableau à l'autre, la variation de trésorerie du bilan au flux net
    déclaré pour la même année : l'écart est SIGNALÉ sur la ligne de flux,
    jamais corrigé — expliciter la convention et les lignes manquantes revient
    à l'auteur, pas au contrôle."""
    findings: list[dict[str, Any]] = []
    cash: dict[str, float] = {}
    cash_unit: str | None = None
    flows: list[tuple[int, str, dict[str, float], str | None]] = []
    src = str(text or "")
    for ti, m in enumerate(re.finditer(r"((?:^\|[^\n]*\n?){3,})", src, re.M)):
        rows = _rows(m.group(1).splitlines())
        if len(rows) < 3:
            continue
        years = _year_columns(rows[0])
        if len(years) < 2:
            continue
        unit = _table_unit(m.group(1), src[max(0, m.start() - 240):m.start()])
        for r in rows[1:]:
            if not r:
                continue
            if _CASH_ROW.match(r[0]) and not _FLOW_ROW.match(r[0]):
                vals = {y: _num(r[i]) for i, y in years.items() if len(r) > i}
                if sum(1 for v in vals.values() if v is not None) >= 2 and not cash:
                    cash = {y: v for y, v in vals.items() if v is not None}
                    cash_unit = unit
            elif _FLOW_ROW.match(r[0]):
                vals = {y: _num(r[i]) for i, y in years.items() if len(r) > i}
                flows.append((ti, r[0], {y: v for y, v in vals.items() if v is not None}, unit))
    if not cash or not flows:
        return findings
    ys = sorted(cash)
    for ti, label, fl, unit in flows:
        # v62.13.9.4.33 (lot 2) — MÊME UNITÉ, ou pas de rapprochement : un bilan en M€
        # et des flux en k€ donnaient un faux écart de 999 (contre-audit du
        # 12/09/2026). Les deux unités connues → normalisées en k€ ; l'une
        # inconnue ou différente sans conversion sûre → « rapprochement non
        # effectué », jamais un écart fabriqué.
        if cash_unit is None or unit is None:
            findings.append({"table_index": ti, "year": None, "flow_row": label, "gap": None,
                             "not_reconciled": "unités non déterminées" })
            continue
        fc, ff = _UNIT_FACTOR[cash_unit], _UNIT_FACTOR[unit]
        for prev, cur in zip(ys, ys[1:]):
            if cur not in fl:
                continue
            delta = (cash[cur] - cash[prev]) * fc
            flow = fl[cur] * ff
            gap = delta - flow
            tol = max(0.05 * max(abs(delta), abs(flow)), 0.15 * max(fc, ff))
            if abs(gap) > tol:
                findings.append({"table_index": ti, "year": cur, "cash_prev": cash[prev], "cash_cur": cash[cur],
                                 "balance_delta": round(delta / fc, 2), "flow": fl[cur], "gap": round(gap / ff, 2),
                                 "flow_row": label, "unit": unit})
    return findings


def tag_cash_reconciliation(text: str, findings: list[dict[str, Any]], lang: str = "fr", mode: str = "work") -> str:
    if not findings:
        return text
    en = str(lang or "fr").lower().startswith("en")
    out = text
    seen: set[str] = set()
    for f in findings:
        if f["flow_row"] in seen:
            continue
        seen.add(f["flow_row"])
        same = [x for x in findings if x["flow_row"] == f["flow_row"]]
        if all(x.get("gap") is None for x in same):
            note = ("rapprochement avec la trésorerie du bilan non effectué — unités des tableaux non déterminées"
                    if not en else "reconciliation with balance-sheet cash not performed — table units not determined")
        else:
            same = [x for x in same if x.get("gap") is not None]
            yrs = ", ".join(str(x["year"]) for x in same)
            gaps = ", ".join(f"{x['gap']:+.1f}".replace(".", ",") for x in same)
            note = (f"non rapproché de la variation de trésorerie du bilan ({yrs} : écart {gaps}) — convention de passage et lignes manquantes à expliciter"
                    if not en else
                    f"not reconciled with the balance-sheet cash movement ({yrs}: gap {gaps}) — bridging convention and missing lines to state")
        label = re.escape(f["flow_row"])
        pat = rf"(?m)^(\|\s*{label}\s*\|[^\n]*?)(?:\s*⟨(?:statut|status)\s*:\s*([^⟩]*)⟩)?\s*$"
        if str(mode) == "synthesis":
            out = re.sub(pat, lambda mm: mm.group(1).rstrip() + f" — {note}", out, count=1)
        else:
            out = re.sub(pat, lambda mm: mm.group(1).rstrip() + (
                f" ⟨statut : {mm.group(2).strip()} ; {note}⟩" if mm.group(2) else f" ⟨statut : {note}⟩"), out, count=1)
    return out


# ── v62.13.9.4.32 (C) — pont EBITDA : marge brute − charges externes − personnel − impôts et taxes ──
_EBITDA_ROWS = {
    "marge_brute": re.compile(r"(?i)^\s*\|?\s*\**\s*(?:marge\s+brute|gross\s+(?:profit|margin))\b(?!.*%)"),   # v62.13.9.4.33 — EN
    "charges_externes": re.compile(r"(?i)^\s*\|?\s*\**\s*(?:charges?\s+externes?|autres\s+achats\s+et\s+charges\s+externes|external\s+(?:costs|expenses))\b"),
    "personnel": re.compile(r"(?i)^\s*\|?\s*\**\s*(?:(?:charges?\s+de\s+)?personnel|masse\s+salariale|frais\s+de\s+personnel|salaires?\s+et\s+charges|staff\s+costs|payroll)\b"),
    # v62.13.9.4.34 (lot 3) — « Taxes » seul, « Tax », « Duties » : le contre-audit
    # du 13/09/2026 a produit un faux écart de −272 sur un pont EBITDA anglais
    # dont la ligne s'appelait simplement « Taxes ».
    "impots_taxes": re.compile(r"(?i)^\s*\|?\s*\**\s*(?:imp[ôo]ts?(?:\s+et\s+taxes?)?|taxes?(?:\s+(?:and|et)\s+duties)?|duties|tax)\b"),
    "ebitda": re.compile(r"(?i)^\s*\|?\s*\**\s*(?:EBITDA|EBE|exc[ée]dent\s+brut\s+d['’]exploitation)\b(?!.*%)"),
}


def check_ebitda_bridge(text: str) -> list[dict[str, Any]]:
    """Contre-audit du dossier agroalimentaire (F, §4) : la source affichait un
    EBITDA que ses propres composantes ne reconstituaient pas — 1 000 k€ d'écart
    par an. Quand un tableau porte marge brute, charges externes, personnel,
    impôts et taxes ET un EBITDA, le solde des composantes est confronté à
    l'EBITDA publié ; l'écart est signalé sur la ligne EBITDA — charge omise ou
    convention de calcul à expliciter — jamais remplacé par le solde."""
    findings: list[dict[str, Any]] = []
    for ti, m in enumerate(re.finditer(r"((?:^\|[^\n]*\n?){3,})", str(text or ""), re.M)):
        rows = _rows(m.group(1).splitlines())
        if len(rows) < 4:
            continue
        found: dict[str, list[str]] = {}
        for r in rows[1:]:
            if not r:
                continue
            for key, rx in _EBITDA_ROWS.items():
                if key not in found and rx.match(r[0]):
                    found[key] = r
        if not all(k in found for k in ("marge_brute", "charges_externes", "personnel", "ebitda")):
            continue
        ncol = max(len(r) for r in rows)
        for ci in range(1, ncol):
            vals = {k: (_num(r[ci]) if len(r) > ci else None) for k, r in found.items()}
            if any(vals.get(k) is None for k in ("marge_brute", "charges_externes", "personnel", "ebitda")):
                continue
            taxes = vals.get("impots_taxes") or 0.0
            solde = vals["marge_brute"] - abs(vals["charges_externes"]) - abs(vals["personnel"]) - abs(taxes)
            gap = vals["ebitda"] - solde
            tol = max(0.05 * abs(vals["ebitda"]), 0.15)
            if abs(gap) > tol:
                findings.append({"table_index": ti, "column": (rows[0][ci] if len(rows[0]) > ci else str(ci)),
                                 "ebitda_published": vals["ebitda"], "components_balance": round(solde, 2),
                                 "gap": round(gap, 2), "ebitda_row": found["ebitda"][0]})
    return findings


def tag_ebitda_bridge(text: str, findings: list[dict[str, Any]], lang: str = "fr", mode: str = "work") -> str:
    if not findings:
        return text
    en = str(lang or "fr").lower().startswith("en")
    out = text
    seen: set[str] = set()
    for f in findings:
        if f["ebitda_row"] in seen:
            continue
        seen.add(f["ebitda_row"])
        cols = ", ".join(f"{x['column']} : {x['gap']:+.0f}" for x in findings if x["ebitda_row"] == f["ebitda_row"])
        note = (f"le solde des composantes affichées (marge brute − charges externes − personnel − impôts et taxes) ne retrouve pas l'EBITDA publié ({cols}) — charge omise ou convention de calcul à expliciter"
                if not en else
                f"the balance of the displayed components (gross margin − external costs − personnel − taxes) does not match the published EBITDA ({cols}) — omitted charge or calculation convention to state")
        label = re.escape(f["ebitda_row"])
        pat = rf"(?m)^(\|\s*{label}\s*\|[^\n]*?)(?:\s*⟨(?:statut|status)\s*:\s*([^⟩]*)⟩)?\s*$"
        if str(mode) == "synthesis":
            out = re.sub(pat, lambda mm: mm.group(1).rstrip() + f" — {note}", out, count=1)
        else:
            out = re.sub(pat, lambda mm: mm.group(1).rstrip() + (
                f" ⟨statut : {mm.group(2).strip()} ; {note}⟩" if mm.group(2) else f" ⟨statut : {note}⟩"), out, count=1)
    return out

# ── v62.13.9.4.33 (lot 2) — un flux est nommé selon son calcul ──────────────────
_CF_COL = re.compile(r"(?i)cash[\s-]?flow|\bCFO\b|\bFCF\b|flux\s+de\s+tr[ée]sorerie|free\s+cash")
_NI_COL = re.compile(r"(?i)r[ée]sultat\s+net|net\s+(?:income|profit|result)")
_INV_COL = re.compile(r"(?i)investissements?|capex|capital\s+expenditure")


def check_flow_naming(text: str) -> list[dict[str, Any]]:
    """Contre-audit du 12/09/2026 (run réel bf7167) : une colonne « Cash-flow
    opérationnel » valait résultat net − investissements — un solde illustratif
    après investissements, sans dotations, sans variation de BFR, sans flux de
    financement. Le calcul n'est pas faux ; le nom l'est. Quand une colonne de
    flux reproduit exactement résultat net − investissements sur les lignes du
    tableau, la note le dit — le montant n'est ni corrigé ni retiré."""
    findings: list[dict[str, Any]] = []
    for ti, m in enumerate(re.finditer(r"((?:^\|[^\n]*\n?){3,})", str(text or ""), re.M)):
        rows = _rows(m.group(1).splitlines())
        if len(rows) < 3:
            continue
        header = rows[0]
        cf = next((i for i, h in enumerate(header) if _CF_COL.search(h)), None)
        ni = next((i for i, h in enumerate(header) if _NI_COL.search(h)), None)
        inv = next((i for i, h in enumerate(header) if _INV_COL.search(h)), None)
        if cf is None or ni is None or inv is None:
            continue
        checked = matched = 0
        for r in rows[1:]:
            if len(r) <= max(cf, ni, inv):
                continue
            a, b, c = _num(r[ni]), _num(r[inv]), _num(r[cf])
            if a is None or b is None or c is None:
                continue
            checked += 1
            if abs((a - abs(b)) - c) <= max(0.05 * abs(c), 0.05):
                matched += 1
        if checked >= 2 and matched == checked:
            findings.append({"table_index": ti, "column": header[cf], "formula": "résultat net − investissements", "rows_checked": checked})
    return findings


def tag_flow_naming(text: str, findings: list[dict[str, Any]], lang: str = "fr", mode: str = "work") -> str:
    if not findings:
        return text
    en = str(lang or "fr").lower().startswith("en")
    out = text
    for f in findings:
        col = re.escape(f["column"])
        note = ((f"⟨statut : « {f['column']} » = résultat net − investissements dans ce tableau — solde illustratif après investissements, "
                 f"hors dotations, variation de BFR et flux de financement ; libellé à préciser, capacité de financement non établie⟩")
                if not en else
                (f"⟨status: \"{f['column']}\" = net income − investments in this table — illustrative balance after investments, "
                 f"excluding depreciation, working-capital change and financing flows; label to clarify, financing capacity not established⟩"))
        # la note suit le TABLEAU (jamais insérée entre l'en-tête et son séparateur)
        tables = list(re.finditer(r"((?:^\|[^\n]*\n?){3,})", out, re.M))
        for m in tables:
            if re.search(rf"^\|[^\n]*{col}", m.group(1), re.M) and note not in out[m.end():m.end() + len(note) + 4]:
                blk = m.group(1)
                out = out[:m.start()] + blk.rstrip("\n") + "\n\n" + note + "\n" + out[m.end():]
                break
    return out


def apply_to_outputs(outputs: dict, lang: str = "fr", mode: str = "work", source: dict | None = None,
                     current_financials_established: bool = True) -> dict[str, Any]:
    """Détecte sur le texte SOURCE (avant neutralisation, sinon les valeurs ont déjà
    disparu) et statue le texte livré."""
    report: dict[str, Any] = {"tables_checked": 0, "findings": []}
    for key, txt in list((outputs or {}).items()):
        if not isinstance(txt, str) or not txt.strip():
            continue
        src = (source or {}).get(key) if isinstance(source, dict) else None
        fs = check_text(src if isinstance(src, str) and src.strip() else txt)
        if fs:
            outputs[key] = tag_text(txt, fs, lang, mode)
            for f in fs:
                report["findings"].append({"role": key, **{k: v for k, v in f.items() if k != "fcf_row"}})
        report["tables_checked"] += 1
    totals: list = []
    for key, txt in list((outputs or {}).items()):
        if not isinstance(txt, str) or not txt.strip():
            continue
        src = (source or {}).get(key) if isinstance(source, dict) else None
        base = src if isinstance(src, str) and src.strip() else txt
        # v62.13.9.4.31 — l'écart est signalé sur le texte LIVRÉ, quelle qu'en soit
        # l'origine : le lecteur voit un total qui ne se retrouve pas, il doit
        # savoir pourquoi. La cause (poste retiré en amont ou addition d'origine)
        # n'est pas devinée ; seul l'écart est constaté.
        fs = check_totals(txt)
        if fs:
            outputs[key] = tag_totals(outputs[key], fs, lang, mode)
            for f in fs:
                totals.append({"role": key, **{k: v for k, v in f.items() if k != "total_row"}})
    report["totals_flagged"] = totals
    # v62.13.9.4.32 (C) — trésorerie du bilan ↔ flux net, par rôle, signalé jamais corrigé
    cashf: list = []
    for key, txt in list((outputs or {}).items()):
        if not isinstance(txt, str) or not txt.strip():
            continue
        src = (source or {}).get(key) if isinstance(source, dict) else None
        fs = check_cash_reconciliation(src if isinstance(src, str) and src.strip() else txt)
        if fs:
            outputs[key] = tag_cash_reconciliation(outputs[key], fs, lang, mode)
            for f in fs:
                cashf.append({"role": key, **f})
    report["cash_reconciliation_flagged"] = cashf
    ebf: list = []
    for key, txt in list((outputs or {}).items()):
        if not isinstance(txt, str) or not txt.strip():
            continue
        src = (source or {}).get(key) if isinstance(source, dict) else None
        fs = check_ebitda_bridge(src if isinstance(src, str) and src.strip() else txt)
        if fs:
            outputs[key] = tag_ebitda_bridge(outputs[key], fs, lang, mode)
            for f in fs:
                ebf.append({"role": key, **f})
    report["ebitda_bridge_flagged"] = ebf
    fnf: list = []                                     # v62.13.9.4.33 (lot 2) — un flux est nommé selon son calcul
    for key, txt in list((outputs or {}).items()):
        if not isinstance(txt, str) or not txt.strip():
            continue
        fs = check_flow_naming(txt)
        if fs:
            outputs[key] = tag_flow_naming(outputs[key], fs, lang, mode)
            for f in fs:
                fnf.append({"role": key, **f})
    report["flow_naming_flagged"] = fnf
    bounded = 0
    for key, txt in list((outputs or {}).items()):
        if isinstance(txt, str) and txt.strip():
            outputs[key], k = bound_liquidity_conclusions(txt, current_financials_established, lang, mode)
            bounded += k
    report["liquidity_conclusions_bounded"] = bounded
    return report
