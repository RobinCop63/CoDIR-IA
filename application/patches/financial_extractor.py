"""
patches/financial_extractor.py — M6-B couches 1 + 1.1 (extraction de faits financiers)

Transforme le `attachments_block` (déterministe) en TABLE DE FAITS candidats avec
provenance fichier/page. M6-B.1.1 ajoute le TYPAGE SÉMANTIQUE révélé nécessaire par
le run réel : un pourcentage n'est PAS un montant.

Familles (metric_kind) :
    amount  — valeur monétaire absolue (Revenue, Operating profit, Net income, FCF…)
    growth  — variation en % (Revenue growth, Comparable sales growth…)
    margin  — ratio résultat/CA en % (Gross margin, Operating margin…)
    ratio   — multiple (Leverage 1.6x…)

Règle cardinale : seul un fait `amount` peut satisfaire un « fait cœur » (Revenue /
Operating profit / Net income / FCF). « Revenue -4% » est une croissance, pas du CA.

Pertes : « operating loss », parenthèses comptables « (£3m) », signes « -£3m » →
valeur NÉGATIVE. Carry-forward d'étiquette : « adjusted £160m, reported £115m » →
deux faits Operating profit. Période absente → confiance plafonnée à « low ».

100 % déterministe (tri stable, 0 LLM). Lecture seule : ne touche pas au score.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional

# ── Étiquettes canoniques (spécifique d'abord ; Comparable sales AVANT Revenue) ──
_LABELS: List[tuple] = [
    ("Free cash flow",   r"free[\s-]?cash[\s-]?flow|flux\s+de\s+tr[ée]sorerie\s+disponible|\bFCF\b"),
    ("EBITDA",           r"\bEBITDA\b"),
    ("Comparable sales", r"comparable\s+(?:store\s+|retail\s+)?sales|ventes?\s+comparables|"
                         r"like[\s-]for[\s-]like|\bLFL\b|comp\.?\s+sales"),
    ("Gross margin",     r"gross\s+margin|marge\s+brute"),
    ("Operating margin", r"operating\s+margin|marge\s+op[ée]rationnelle"),
    ("Operating profit", r"operating\s+(?:profit|income|loss|profit/?\(?loss\)?)|income\s+from\s+operations|"
                         r"r[ée]sultat\s+op[ée]rationnel|r[ée]sultat\s+d['e]exploitation|\bEBIT\b"),
    ("Net income",       r"net\s+(?:income|profit|loss|earnings)|profit\s+for\s+the\s+year|"
                         r"profit\s+attributable|r[ée]sultat\s+net|b[ée]n[ée]fice\s+net|perte\s+nette"),
    ("Gross profit",     r"gross\s+profit|profit\s+brut|marge\s+commerciale"),
    ("Revenue",          r"\brevenue\b|\bturnover\b|\bnet\s+sales\b|\bsales\b|"
                         r"chiffre\s+d['e]affaires|\bCA\b|produit\s+des\s+activit[ée]s"),
    ("Net debt",         r"net\s+debt|dette\s+nette|endettement\s+net"),
    ("Leverage",         r"leverage|levier|gearing|net\s+debt\s*/\s*ebitda"),
]
_LABEL_RES = [(canon, re.compile(pat, re.I)) for canon, pat in _LABELS]

# Métriques intrinsèquement monétaires vs intrinsèquement en taux.
_AMOUNT_METRICS = {"Revenue", "Operating profit", "Net income", "Free cash flow",
                   "Gross profit", "EBITDA", "Net debt"}
_RATE_METRICS = {"Gross margin", "Operating margin", "Comparable sales", "Leverage"}
_CORE_LABELS = ("Revenue", "Operating profit", "Net income", "Free cash flow")

_LOSS_RE = re.compile(r"\bloss\b|\bperte\b|profit/?\(?loss\)?|\(loss\)", re.I)
_GROWTH_CTX_RE = re.compile(r"growth|croissance|change|variation|increase|decrease|"
                            r"decline|\bup\b|\bdown\b|year[\s-]on[\s-]year|\bYoY\b|"
                            r"vs\.?\s+(?:prior|last|FY)|en\s+(?:hausse|baisse|repli)", re.I)
_MARGIN_CTX_RE = re.compile(r"margin|marge", re.I)

_QUAL_RE = re.compile(r"\b(adjusted|ajust[ée]e?|underlying|sous[\s-]?jacent|"
                      r"reported|publi[ée]e?|statutory|comparable|like[\s-]for[\s-]like)\b", re.I)

_CCY = r"(?P<ccy>£|€|\$|\bGBP\b|\bEUR\b|\bUSD\b|\bCHF\b|US\$)"
_NUM = r"(?P<num>\d{1,3}(?:[ ,.\u00a0]\d{3})*(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
_SCALE = r"(?P<scale>bn|md?s?|mn|m|k|billion|milliard|million|millions)?"
# montant : signe optionnel, parenthèses comptables optionnelles
_MONEY_RE = re.compile(r"(?P<par>\()?(?P<sign>[-+])?\s*" + _CCY + r"\s?(?P<sign2>[-+])?\s?"
                       + _NUM + r"\s?" + _SCALE + r"\)?", re.I)
# montant suffixe : ÉCHELLE OBLIGATOIRE (le « M » de « M€ » est l'échelle).
# Sans échelle, « 26 £ » (issu de « FY26 £… ») n'est plus capté comme montant.
_MONEY_SUFFIX_RE = re.compile(r"(?P<par>\()?(?P<sign>[-+])?\s*" + _NUM
                              + r"\s?(?P<scale2>bn|mds?|md|mn|m|k|million|milliard)\s?"
                              + r"(?P<ccy2>£|€|\$|GBP|EUR|USD)\)?", re.I)
_PCT_RE = re.compile(r"(?P<pct>[+\-]?\d{1,3}(?:[.,]\d+)?)\s?%|(?P<bps>[+\-]?\d{1,4})\s?bps|"
                     r"(?P<x>\d{1,2}(?:[.,]\d+)?)\s?x\b", re.I)


# montant « devise au milieu » : « 2,420 £m », « 2,420 GBPm », « 2,420 €m »
# (nombre + devise + échelle, échelle obligatoire pour ne pas re-capter « FY26 £ »).
_MONEY_MID_RE = re.compile(r"(?P<par>\()?(?P<sign>[-+])?\s*" + _NUM
                           + r"\s?(?P<ccy3>£|€|\$|GBP|EUR|USD)\s?"
                           + r"(?P<scale3>bn|mds?|md|mn|m|k|million|milliard)\)?", re.I)

# Gardes « faux amis » Revenue : un coût ou un ratio de rotation n'est pas du CA.
_REV_FALSE_FRIEND_RE = re.compile(
    r"cost\s+of\s+(sales|revenue|goods)|sales\s+costs?|selling\s+costs?|"
    r"costs?\s+related\s+to\s+sales|revenue\s+costs?|co[ûu]t\s+des\s+ventes|"
    r"(inventory|stock|asset|capital|receivables?)\s+turnover|rotation\s+des", re.I)
_LEVERAGE_CTX_RE = re.compile(
    r"leverage|gearing|net\s+debt|levier|dette\s+nette|debt\s*/\s*ebitda", re.I)
# Découpage par dimension : un CA « by region / par segment » n'est pas le CA total.
_BREAKDOWN_RE = re.compile(
    r"by\s+region|by\s+segment|by\s+category|by\s+channel|by\s+geography|"
    r"par\s+r[ée]gion|par\s+segment|EMEIA|Americas|Asia[\s-]?Pacific|Greater\s+China|"
    r"\bAPAC\b|\bEMEA\b|wholesale|retail\s+revenue|by\s+division", re.I)
# Inférence de signe négatif sur variation « down/decline/fell/baisse ».
_DOWN_RE = re.compile(r"\bdown\b|decline|decreas|\bfell\b|\bfall\b|\bdrop\b|"
                      r"baisse|repli|recul|en\s+retrait", re.I)
# Période fiscale (prioritaire sur une date calendaire proche).
_FISCAL_RE = re.compile(r"H[12]\s?FY\s?\d{2,4}|FY\s?\d{2,4}|Q[1-4]\s?FY?\s?\d{2,4}|"
                        r"exercice\s+\d{4}", re.I)

# v62.13.9.4.40 — échelle déclarée en tête d'un tableau d'états, périodes d'en-tête, lignes de tableau
_TABLE_SCALE_RE = re.compile(
    r"^\s*\(\s*(?:(?:amounts|dollars|figures|montants|chiffres)\s+)?(?:in|en)\s+"
    r"(?:(?:u\.?s\.?\s+)?dollars?\s+)?(?P<w>thousands|millions|billions|milliers|millions|milliards)\b[^)]*\)\s*$", re.I)
_TABLE_SCALE_UNITS = {"thousands": ("k", 1e3), "milliers": ("k", 1e3), "millions": ("m", 1e6),
                      "billions": ("bn", 1e9), "milliards": ("bn", 1e9)}
_TABLE_SCALE_CCY_RE = re.compile(r"d['’]euros|euros?|u\.?s\.?\s+dollars|dollars|pounds|sterling|\bUSD\b|\bEUR\b|\bGBP\b", re.I)
_TABLE_SCALE_CCY = {"d'euros": "EUR", "euros": "EUR", "euro": "EUR", "eur": "EUR", "dollars": "USD",
                    "u.s. dollars": "USD", "us dollars": "USD", "usd": "USD", "pounds": "GBP",
                    "sterling": "GBP", "gbp": "GBP"}
_HEADER_PERIOD_LINE_RE = re.compile(
    r"^\s*(?:(?:fiscal|years?|ended|as|of|at|exercices?|clos|le|au|du|"
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    r"janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre|"
    r"\d{1,2}(?:er)?|(?:19|20)\d{2}|FY\s?(?:19|20)?\d{2})[\s,.]*)+$", re.I)
_TABLE_CELL = r"\(?-?\$?\s?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?|[—–]"
_TABLE_CELL_RE = re.compile(_TABLE_CELL)
_TABLE_ROW_RE = re.compile(r"^(?P<label>[A-Za-z][A-Za-z ,'’&/\-]*?):?\s+(?P<cells>(?:(?:" + _TABLE_CELL
                           + r")\s*){1,6})$")
_PER_SHARE_RE = re.compile(r"per\s+(?:common\s+|ordinary\s+)?share|per\s+unit\b|par\s+action", re.I)
_PER_SHARE_AFTER_RE = re.compile(r"\s*(?:per\s+(?:common\s+|ordinary\s+)?share|a\s+share|par\s+action)", re.I)
_SCALE_FACTOR = {"bn": 1e9, "billion": 1e9, "milliard": 1e9, "md": 1e9, "mds": 1e9,
                 "m": 1e6, "mn": 1e6, "million": 1e6, "millions": 1e6,
                 "k": 1e3, "": 1.0, None: 1.0}
_CCY_NORM = {"£": "GBP", "€": "EUR", "$": "USD", "us$": "USD", "m€": "EUR",
             "md€": "EUR", "€m": "EUR", "gbp": "GBP", "eur": "EUR",
             "usd": "USD", "chf": "CHF"}


@dataclass
class FinancialFact:
    label: str = ""
    raw_label: str = ""
    metric_kind: str = "amount"        # amount | growth | margin | ratio
    source_type: str = "attachment"    # attachment (fichier+page) | profile (registre)
    dimension: str = "total"           # total | region | segment | channel
    value: float = 0.0
    value_str: str = ""
    unit: str = ""
    currency: str = ""
    period: str = ""
    scope: str = ""
    qualifier: str = ""
    source_file: str = ""
    page: int = 0
    raw_line: str = ""
    confidence: str = "low"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _num_to_float(num: str) -> Optional[float]:
    if not num:
        return None
    s = num.replace("\u00a0", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        s = re.sub(r",(\d{3})\b", r"\1", s)
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _iter_lines_with_provenance(block: str):
    """(source_file, page, line) en suivant « ### Fichier: » et « ## Page/Slide N »."""
    cur_file, cur_page = "", 0
    for raw in (block or "").splitlines():
        mf = re.match(r"###\s*Fichier:\s*(.+?)(?:\s*\[.*\])?\s*$", raw)
        if mf:
            cur_file = mf.group(1).strip(); cur_page = 0; continue
        mp = re.match(r"##\s*(?:Page|Slide)\s+(\d+)", raw)   # PPTX → « ## Slide N »
        if mp:
            cur_page = int(mp.group(1)); continue
        # v62.13.9.4.40 — le bloc des états financiers porte ses propres marqueurs
        # (« --- 📄 fichier (total N pages) --- », « -- p.N -- ») : sans eux, ses faits
        # n'avaient ni fichier ni page et passaient pour des données de registre.
        mf2 = re.match(r"^-{3}\s*(?:\S\s+)?(.+?)\s*\(total\s+\d+\s+pages?\)\s*-{3}\s*$", raw)
        if mf2:
            cur_file = mf2.group(1).strip(); cur_page = 0; continue
        mp2 = re.match(r"^--\s*p\.\s*(\d+)\s*--\s*$", raw)
        if mp2:
            cur_page = int(mp2.group(1)); continue
        if raw.strip():
            yield cur_file, cur_page, raw


def _classify_pct(label: str, value_str: str, context: str) -> tuple:
    """% sur métrique → (label_affiné, metric_kind). Un % n'est jamais un montant."""
    signed = value_str.strip().startswith(("+", "-"))
    if label in _RATE_METRICS:                      # déjà un taux par nature
        if label == "Comparable sales":
            return (label + " growth", "growth")
        return (label, "margin" if label in ("Gross margin", "Operating margin") else "ratio")
    if label == "Revenue":                          # un % de CA = croissance
        return ("Revenue growth", "growth")
    if label in ("Operating profit", "Net income", "Gross profit", "EBITDA"):
        # B.1.3.6 (run dossier anglophone coté PJ) — « profit fell -25% CER … with margins
        # 15.5% » sortait « Operating margin -25% » : le contexte-marge était
        # testé AVANT le signe/mouvement. Un % SIGNÉ ou porté par un verbe de
        # variation (fell/down/CER/vs) est une VARIATION, jamais un niveau.
        if signed or _GROWTH_CTX_RE.search(context) or _DOWN_RE.search(context):
            return (label + " growth", "growth")
        if _MARGIN_CTX_RE.search(context):
            return (label.replace("profit", "margin") if "profit" in label
                    else label + " margin", "margin")
        # % nu sur un résultat = très probablement une marge
        base = "Operating margin" if label == "Operating profit" else label + " margin"
        return (base, "margin")
    return (label + " (rate)", "growth")            # FCF/Net debt en % → taux


def _confidence(kind: str, label: str, currency: str, period: str) -> str:
    """Période obligatoire pour medium+. Haute = montant cœur + devise + période."""
    if not period:
        return "low"
    core_amount = (kind == "amount" and label in _CORE_LABELS)
    if core_amount and currency:
        return "high"
    if kind == "amount" and currency:
        return "medium"
    if kind in ("growth", "margin", "ratio"):
        return "medium"
    return "low"


def extract_financial_facts(attachments_block: str, lang: str = "fr",
                            default_scope: str = "") -> List[FinancialFact]:
    facts: List[FinancialFact] = []
    if not attachments_block:
        return facts

    _pg40 = {"key": None, "unit": "", "factor": 1.0, "periods": [], "ccy": "", "rows": False}
    for src_file, page, line in _iter_lines_with_provenance(attachments_block):
        # v62.13.9.4.40 — ÉTATS EN TABLEAU (comptes américains, et tout tableau qui déclare son
        # échelle). Une page d'états déclare son échelle en tête — « (In thousands, except per share
        # amounts) » — et ses périodes en en-tête de colonnes. Sans cela, un chiffre d'affaires
        # déclaré en milliers était lu en unités (facteur mille), sans période.
        if _pg40["key"] != (src_file, page):
            _pg40.update(key=(src_file, page), unit="", factor=1.0, periods=[], ccy="", rows=False)
        _ts40 = _TABLE_SCALE_RE.match(line)
        if _ts40:
            _w = _ts40.group("w").lower()
            _pg40["unit"], _pg40["factor"] = _TABLE_SCALE_UNITS.get(_w, ("", 1.0))
            _c40 = _TABLE_SCALE_CCY_RE.search(line)
            if _c40:
                _pg40["ccy"] = _TABLE_SCALE_CCY.get(_c40.group(0).lower().replace("’", "'"), "")
            continue
        if not _pg40["rows"] and _HEADER_PERIOD_LINE_RE.match(line):
            _pg40["periods"].extend(re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", line))
            continue
        _cm40 = re.search(r"[$£€]", line)
        if _cm40 and not _pg40["ccy"]:
            _pg40["ccy"] = _CCY_NORM.get(_cm40.group(0), "")
        if _pg40["factor"] != 1.0 and "|" not in line:
            _rw40 = _TABLE_ROW_RE.match(line.strip())
            if _rw40:
                _pg40["rows"] = True
                _cells40 = _TABLE_CELL_RE.findall(_rw40.group("cells"))
                _lab40 = _rw40.group("label").strip().rstrip(":").strip()
                _canon40 = next((c for c, rx in _LABEL_RES if rx.fullmatch(_lab40)), "")
                if (_canon40 and _canon40 in _AMOUNT_METRICS | {"Gross profit"} and _pg40["ccy"]
                        and _pg40["periods"] and len(_cells40) == len(_pg40["periods"])
                        and not _PER_SHARE_RE.search(_lab40)
                        and not (_canon40 == "Revenue" and _REV_FALSE_FRIEND_RE.search(_lab40))):
                    _raw40 = _cells40[0]
                    _v40 = _num_to_float(_raw40.strip("()$ ").replace("$", ""))
                    if _v40 is not None:
                        _v40 = _v40 * _pg40["factor"]
                        if _raw40.startswith("(") or _raw40.startswith("-"):
                            _v40 = -abs(_v40)
                        _per40 = "FY" + _pg40["periods"][0]
                        facts.append(FinancialFact(
                            label=_canon40, raw_label=_lab40, metric_kind="amount",
                            source_type="attachment" if (src_file and page) else "profile",
                            dimension="total", value=_v40, value_str=_raw40, unit=_pg40["unit"],
                            currency=_pg40["ccy"], period=_per40,
                            scope=(default_scope or "") if (src_file and page) else "registry/profile",
                            qualifier="", source_file=src_file, page=page, raw_line=line.strip()[:240],
                            confidence=_confidence("amount", _canon40, _pg40["ccy"], _per40)))
                continue
        vhits = []
        for m in _MONEY_RE.finditer(line):
            if m.group("num"): vhits.append((m.start(), m.end(), "money", m))
        for m in _MONEY_SUFFIX_RE.finditer(line):
            if m.group("num"): vhits.append((m.start(), m.end(), "money2", m))
        for m in _MONEY_MID_RE.finditer(line):
            if m.group("num"): vhits.append((m.start(), m.end(), "money3", m))
        for m in _PCT_RE.finditer(line):
            vhits.append((m.start(), m.end(), "pct", m))
        if not vhits:
            continue
        # dédoublonnage de spans qui se chevauchent (money vs pct sur même zone)
        vhits.sort(key=lambda x: (x[0], -(x[1] - x[0])))
        dedup, last_end = [], -1
        for v in vhits:
            if v[0] >= last_end:
                dedup.append(v); last_end = v[1]
        vhits = dedup

        line_period_m = _PERIOD_RE.search(line)
        line_period = line_period_m.group(0).strip() if line_period_m else ""
        # toutes les périodes de la ligne (pour rattacher la PLUS PROCHE de chaque valeur)
        _line_periods = [(pm.start(), pm.end(), pm.group(0).strip())
                         for pm in _PERIOD_RE.finditer(line)]

        def _pick_period(vs_, ve_):
            # 1) clause contenant la valeur (bornée par ; | et « and »)
            _seps = [0] + [mm.end() for mm in re.finditer(r"[;|]|\sand\s", line)] \
                    + [mm.start() for mm in re.finditer(r"[;|]", line)] + [len(line)]
            _seps = sorted(set(_seps))
            cs = max((s for s in _seps if s <= vs_), default=0)
            ce = min((s for s in _seps if s >= ve_), default=len(line))
            in_clause = [(ps, pe, pv) for (ps, pe, pv) in _line_periods if cs <= ps < ce]
            cands = in_clause or _line_periods
            if not cands:
                return ""
            # 2) priorité aux périodes fiscales (FY/H1/Q) sur les dates calendaires
            fiscal = [c for c in cands if _FISCAL_RE.search(c[2])]
            pool = fiscal or cands
            # 3) la plus proche de la valeur dans le pool retenu
            best, bestd = "", 10 ** 9
            for (ps, pe, pv) in pool:
                d = abs((ps - ve_) if ps >= ve_ else (vs_ - pe))
                if d < bestd:
                    bestd, best = d, pv
            return best

        def _closest_period(vs_, ve_):
            return _pick_period(vs_, ve_)

        prev_end, prev_label, prev_raw = 0, "", ""
        for (vs, ve, kind, m) in vhits:
            segment = line[prev_end:vs]
            before = line[:vs]
            after = line[ve:ve + 40]                 # fenêtre locale après la valeur
            prev_end = ve

            label = raw_label = ""
            for canon, rx in _LABEL_RES:
                lm = rx.search(segment)
                if lm:
                    label, raw_label = canon, lm.group(0); break
            if not label and vs == vhits[0][0]:
                for canon, rx in _LABEL_RES:
                    lm = rx.search(before)
                    if lm:
                        label, raw_label = canon, lm.group(0); break
            # ratio « 1.6x » dont l'étiquette (leverage) est APRÈS la valeur
            if not label and kind == "pct" and m.group("x"):
                _ctx = (segment + " " + after).lower()
                if any(w in _ctx for w in ("leverage", "gearing", "net debt",
                                           "levier", "ebitda")):
                    label, raw_label = "Leverage", m.group(0)
            # carry-forward : valeur de comparaison (qualificatif OU « vs »/période)
            if not label and prev_label and (
                    _QUAL_RE.search(segment)
                    or re.search(r"\bvs\.?\b|\bversus\b|compared|against|\ben\b", segment, re.I)
                    or _PERIOD_RE.search(segment)):
                label, raw_label = prev_label, prev_raw
            if not label:
                continue
            # garde « faux amis » : « cost of sales », « inventory turnover »… ne sont
            # pas du Revenue (le mot générique « sales »/« turnover » matchait à tort).
            if label == "Revenue" and _REV_FALSE_FRIEND_RE.search(
                    line[max(0, vs - 60):ve + 10]):
                continue
            prev_label, prev_raw = label, raw_label

            # qualificatif LE PLUS PROCHE de la valeur (pas le premier de la ligne) —
            # « ...(-5% reported), adjusted operating profit £19m » → adjusted, pas reported.
            _quals = list(_QUAL_RE.finditer(before))
            qualifier = _quals[-1].group(0).lower() if _quals else ""
            # période : une période ENTRE PARENTHÈSES juste après la valeur lui
            # appartient (« £2,461m (2025) ») ; sinon la plus proche ; sinon ligne.
            _pa = re.match(r"\s*\(([^)]{2,14})\)", after)
            if _pa and _PERIOD_RE.search(_pa.group(1)):
                period = _PERIOD_RE.search(_pa.group(1)).group(0).strip()
            else:
                period = _closest_period(vs, ve) or line_period

            if kind in ("money", "money2", "money3"):
                val = _num_to_float(m.group("num"))
                if val is None:
                    continue
                scale = (m.groupdict().get("scale") or m.groupdict().get("scale2")
                         or m.groupdict().get("scale3") or "").lower()
                ccy_raw = (m.groupdict().get("ccy") or m.groupdict().get("ccy2")
                           or m.groupdict().get("ccy3") or "")
                currency = _CCY_NORM.get(ccy_raw.lower().strip(), ccy_raw.upper())
                value = val * _SCALE_FACTOR.get(scale, 1.0)
                # v62.13.9.4.40 — valeur par action : jamais un résultat ni un chiffre d'affaires
                if _PER_SHARE_RE.search(segment) or _PER_SHARE_AFTER_RE.match(after):
                    continue
                # v62.13.9.4.40 — sans échelle explicite, l'échelle déclarée en tête de la page s'applique
                if not scale and _pg40["factor"] != 1.0:
                    value = val * _pg40["factor"]; scale = _pg40["unit"]
                    _pg40["rows"] = True
                    _nv40 = [h for h in vhits if h[2] in ("money", "money2", "money3")]
                    if not period and _pg40["periods"] and len(_nv40) == len(_pg40["periods"]):
                        _ix40 = [h[0] for h in _nv40].index(vs) if vs in [h[0] for h in _nv40] else -1
                        if _ix40 >= 0:
                            period = "FY" + _pg40["periods"][_ix40]
                # signe NÉGATIF : LOCAL — parenthèses, signe explicite, « loss/perte »
                # AVANT la valeur (segment) ou COLLÉ juste après (« 47m loss »), en
                # EXCLUANT l'en-tête neutre « profit/(loss) ». Fenêtre après serrée
                # (~10 car.) pour ne pas inverser un profit suivi d'une perte comparative.
                _ctx_loss = (segment + " " + after[:10]).lower()
                _local_loss = (("loss" in _ctx_loss or "perte" in _ctx_loss)
                               and "profit/(loss)" not in _ctx_loss
                               and "profit/loss" not in _ctx_loss
                               and "profit / (loss)" not in _ctx_loss)
                # B.1.3.6 (run dossier anglophone coté PJ) — « Reported operating LOSS £3m »
                # sortait +£3m : le mot « loss » était CONSOMMÉ par le match
                # du label (operating\s+(?:profit|…|loss)) donc absent du
                # segment. Le raw_label porte le texte matché : on le teste.
                _local_loss = _local_loss or bool(_LOSS_RE.search(raw_label or ""))
                neg = bool(m.groupdict().get("par")) \
                    or (m.groupdict().get("sign") in ("-",)) \
                    or (m.groupdict().get("sign2") in ("-",)) \
                    or (_local_loss and label in ("Operating profit", "Net income", "Gross profit"))
                if neg:
                    value = -abs(value)
                unit, value_str = (scale or ""), m.group(0).strip()
                metric_kind = "amount" if label in _AMOUNT_METRICS else "ratio"
                if label in _RATE_METRICS and label != "Leverage":
                    metric_kind = "amount"   # marge donnée en montant : rare, on garde
            else:
                raw_pct = (m.group("pct") or m.group("bps") or m.group("x") or "")
                currency = ""
                if m.group("x"):
                    # « x » → Leverage UNIQUEMENT avec contexte dette/levier ;
                    # sinon non promouvable (on n'invente pas un ratio de levier).
                    _ctx = (segment + " " + after).lower()
                    if not _LEVERAGE_CTX_RE.search(_ctx):
                        continue
                    unit = "x"; value = _num_to_float(raw_pct) or 0.0
                    value_str = m.group(0).strip()
                    label, metric_kind = ("Leverage", "ratio")
                else:
                    unit = "%" if m.group("pct") else "bps"
                    value = _num_to_float(raw_pct) or 0.0
                    value_str = m.group(0).strip()
                    # « sales down ~12% » : variation non signée + contexte baissier → négatif
                    if value > 0 and not value_str.strip().startswith(("+", "-")) \
                            and _DOWN_RE.search((segment + " " + after)):
                        value = -value
                    label, metric_kind = _classify_pct(label, value_str, line)

            # P0 — provenance : un fait SANS fichier+page vient du profil registre
            # (« Net income : 43 k€ »), pas d'une pièce. On le marque « profile » et
            # on ne lui attribue PAS le périmètre consolidé.
            _stype = "attachment" if (src_file and page) else "profile"
            _dim = "region" if _BREAKDOWN_RE.search(line[max(0, vs - 50):ve + 20]) else "total"
            _scope = (default_scope or "") if _stype == "attachment" else "registry/profile"
            facts.append(FinancialFact(
                label=label, raw_label=raw_label, metric_kind=metric_kind,
                source_type=_stype, dimension=_dim,
                value=value, value_str=value_str, unit=unit, currency=currency,
                period=period, scope=_scope, qualifier=qualifier,
                source_file=src_file, page=page, raw_line=line.strip()[:240],
                confidence=_confidence(metric_kind, label, currency, period),
            ))

    # déduplication des faits identiques (même label/valeur/période/source/page)
    seen, uniq = set(), []
    for f in facts:
        key = (f.label, f.qualifier, f.value_str, f.period, f.source_file, f.page)
        if key not in seen:
            seen.add(key); uniq.append(f)
    uniq.sort(key=lambda f: (f.source_file, f.page, f.label, f.qualifier, f.value_str))
    return uniq


_PERIOD_RE = re.compile(
    r"\b(H[12]\s?FY\s?\d{2,4}|FY\s?\d{2,4}|Q[1-4]\s?FY?\s?\d{2,4}|"
    r"exercice\s+\d{4}|year\s+ended[^\n]{0,30}\d{4}|\d{4}/\d{2,4}|"
    r"S[12]\s?\d{4}|T[1-4]\s?\d{4}|20\d{2})\b", re.I)


def facts_coverage(facts: List[FinancialFact]) -> Dict[str, Any]:
    """Cœur = MONTANT sourcé (fichier+page), périmètre total (pas un % , pas un
    breakdown régional, pas une ligne de profil registre)."""
    def _is_core_amount(f):
        return (f.metric_kind == "amount" and f.source_type == "attachment"
                and f.dimension == "total" and f.source_file and f.page)
    amount_present = {f.label for f in facts if _is_core_amount(f)}
    missing = [l for l in _CORE_LABELS if l not in amount_present]
    high = [f for f in facts if f.confidence == "high"]
    return {
        "total_facts": len(facts),
        "amount_facts": len([f for f in facts if f.metric_kind == "amount"]),
        "rate_facts": len([f for f in facts if f.metric_kind != "amount"]),
        "profile_facts": len([f for f in facts if f.source_type == "profile"]),
        "core_present": [l for l in _CORE_LABELS if l in amount_present],
        "core_missing": missing,
        "high_confidence_count": len(high),
        "has_any_core_fact": len(missing) < len(_CORE_LABELS),
    }


def facts_table_rows(facts: List[FinancialFact]) -> List[Dict[str, str]]:
    rows = []
    for f in facts:
        val = f.value_str
        # ne pas préfixer la devise si un symbole est déjà présent (évite « GBP £63m »)
        if f.currency and not any(sym in val for sym in ("£", "€", "$")) \
                and f.currency not in val:
            val = f"{f.currency} {val}"
        rows.append({
            "label": (f.label + (f" ({f.qualifier})" if f.qualifier else "")),
            "kind": f.metric_kind,
            "value": val,
            "period": f.period or "—",
            "scope": f.scope or "—",
            "source": (f"{f.source_file} p.{f.page}" if f.page else (f.source_file or "—")),
            "confidence": f.confidence,
            "raw_line": (f.raw_line or "")[:80],
        })
    return rows
