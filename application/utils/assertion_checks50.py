"""v62.13.9.4.50 — contrôles bornés d'assertions contre la base sourcée (contre-recette du 30/09/2026, A01/B02).

Le signalement doit rapprocher l'ASSERTION COMPLÈTE avec la base : métrique, exercice, nature, qualification. Deux
contrôles sont faits ici, sur les seuls faits confirmés de l'exercice de référence, sans jamais toucher au texte :

1. TAUX DÉRIVÉS — une marge annoncée pour l'exercice des faits (marge brute, marge d'exploitation, marge nette) est
   comparée au rapport des faits confirmés (ex. 341 343 / 619 985 = 55,06 %). Écart > 0,15 pt : « contredit ».
2. QUALIFICATION — un montant égal au fait publié mais présenté « hors ajustement / excluding / ajusté » : la pièce le
   publie tel quel ; la qualification est à vérifier (cas réel : « Résultat net : 90,994 M USD (… hors ajustement
   fiscal exceptionnel) » alors que la pièce publie ce résultat en norme comptable, effet fiscal compris).

Les contrôles qui exigent l'exercice ANTÉRIEUR (variation en points de base, marge FY-1) s'appuient sur les faits
multi-exercices des sources externes (registres, dépôts) quand ils sont disponibles — voir external_facts50.
Aucune règle propre à un dossier : métriques reconnues par leurs libellés génériques FR/EN.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

_METRIC_WORDS = {
    "REVENUE": r"chiffre\s+d['’]affaires|\bCA\b|revenues?|net\s+sales|ventes\s+nettes",
    "GROSS_PROFIT": r"marge\s+brute|gross\s+(?:profit|margin)",
    "OPERATING_PROFIT": r"r[ée]sultat\s+(?:d['’]exploitation|op[ée]rationnel)|operating\s+(?:profit|income|margin)|marge\s+d['’]exploitation|marge\s+op[ée]rationnelle|\bEBIT\b",
    "NET_INCOME": r"r[ée]sultat\s+net|net\s+income|marge\s+nette|net\s+margin",
    "INVENTORIES": r"\bstocks?\b|inventor(?:y|ies)",
}
_CAGR = re.compile(r"(?i)\b(?:CAGR|TCAM|croissance\s+(?:annuelle\s+)?moyenne|taux\s+de\s+croissance\s+annuel(?:\s+moyen)?|"
                   r"compound\s+annual|average\s+annual\s+growth|%\s+par\s+an|%\s+per\s+year|%/an)")
_AMOUNT = re.compile(r"(\d{1,3}(?:[ ,.]\d{3})*(?:[.,]\d+)?)\s*(?:M|m|Md|bn|k)?\s*(?:\$|€|£|USD|EUR|GBP|M\$|M€|MUSD)")
_YEARS_SPAN = re.compile(r"(?i)\b(?:sur|over|en|in)\s+(\d{1,2})\s+(?:ans|années|years|exercices)\b")
_DAYS = re.compile(r"(?i)(\d{1,3})\s*jours?\s+de\s+(?:stocks?|couverture|COGS|co[uû]t\s+des\s+ventes)|"
                   r"(?:couverture\s+(?:des\s+)?)?stocks?\s*:?\D{0,20}?(\d{1,3})\s*jours|(\d{1,3})\s*days?\s+of\s+(?:inventory|stock|COGS)")
_MARGIN_OF = {"GROSS_PROFIT": r"marge\s+brute|gross\s+margin", "OPERATING_PROFIT": r"marge\s+(?:d['’]exploitation|op[ée]rationnelle)|operating\s+margin|marge\s+EBIT",
              "NET_INCOME": r"marge\s+nette|net\s+margin"}
_QUALIFIER = re.compile(r"(?i)\b(?:hors\s+(?:ajustement|[ée]l[ée]ments?|effet)|excluding|ex\.|ajust[ée]|adjusted|retrait[ée]|underlying|sous-jacent)")
_PCT = re.compile(r"(?<![\d.,])(\d{1,2}(?:[.,]\d{1,2})?)\s?%")
_FY = re.compile(r"(?i)\b(?:FY\s?|exercice\s+)?((?:19|20)\d{2})\b")


def _num(v: Any) -> float | None:
    s = re.sub(r"[^\d.,-]", "", str(v or ""))
    if not s:
        return None
    if s.count(",") == 1 and s.count(".") == 0 and len(s.split(",")[1]) == 3:
        s = s.replace(",", "")                  # 619,985 → 619985 (séparateur de milliers)
    s = s.replace(",", ".") if s.count(",") == 1 and "." not in s else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def confirmed_facts(result: Mapping[str, Any] | None) -> dict:
    """{(METRIC, 'FY2025'): valeur} depuis la base de faits confirmés à la page (libellés génériques FR/EN)."""
    out: dict = {}
    facts = ((result or {}).get("financial_facts_table") or {}).get("facts") or []
    for f in facts if isinstance(facts, list) else []:
        if not isinstance(f, Mapping) or not str(f.get("proof_status") or "").startswith("CONFIRMED"):
            continue
        per = str(f.get("period") or "")
        if not re.fullmatch(r"FY(?:19|20)\d{2}", per):
            continue
        label = str(f.get("label") or "")
        for m, rx in _METRIC_WORDS.items():
            if re.search(rx, label, re.I):
                v = _num(f.get("value"))
                if v is not None:
                    out.setdefault((m, per), v)
                break
    # v62.13.9.4.50 — faits EXTERNES datés (dépôts SEC, comptes déposés) : ils complètent la base, jamais ne la
    # remplacent — c'est d'eux que viennent les exercices ANTÉRIEURS (variation en points de base, marge FY-1)
    _map = {"REVENUE": "REVENUE", "GROSS_PROFIT": "GROSS_PROFIT", "OPERATING_PROFIT": "OPERATING_PROFIT",
            "NET_INCOME": "NET_INCOME", "INVENTORIES": "INVENTORIES", "COST_OF_REVENUE": "COST_OF_REVENUE"}
    for f in (((result or {}).get("external_facts50") or {}).get("facts") or []):
        if isinstance(f, Mapping) and f.get("metric") in _map and re.fullmatch(r"FY(?:19|20)\d{2}", str(f.get("period") or "")):
            key = (_map[f["metric"]], str(f["period"]))
            if key not in out:
                try:
                    out[key] = float(f.get("value")) / 1000.0     # la base de la page est en milliers : même échelle
                except (TypeError, ValueError):
                    pass
    return out


def _margin(facts: Mapping, metric: str, period: str) -> float | None:
    rev, num = facts.get(("REVENUE", period)), facts.get((metric, period))
    return 100.0 * num / rev if rev and num else None


_BP = re.compile(r"(?i)([+−-]\s?\d{1,4})\s?(?:pb|bps?|points?\s+de\s+base|basis\s+points?)\s*(?:vs\.?|versus|par\s+rapport\s+[àa]|compared\s+to)?\s*(?:FY\s?)?((?:19|20)\d{2})")
_PCT_YEAR = re.compile(r"(?i)(\d{1,2}(?:[.,]\d{1,2})?)\s?%\s*(?:en|in|for|au|à)?\s*(?:l['’]exercice\s+)?FY\s?((?:19|20)\d{2})")


def check_prior_year(line: str, facts: Mapping, lang: str = "fr") -> str | None:
    """Variation en points de base et marge d'un exercice ANTÉRIEUR, contre les faits de cet exercice (externes)."""
    s = str(line or "")
    en = str(lang or "").lower().startswith("en")
    periods = sorted({p for (_m, p) in facts})
    for metric, rx in _MARGIN_OF.items():
        mm = re.search(rx, s, re.I)
        if not mm:
            continue
        # « +260 pb vs FY2024 » : marge de l'exercice de la ligne (ou de référence) moins celle de l'exercice cité
        for b in _BP.finditer(s):
            stated = int(re.sub(r"[^\d-]", "", b.group(1).replace("−", "-").replace("+", "")) or 0)
            base = "FY" + b.group(2)
            later = [p for p in periods if p > base]
            if not later:
                continue
            m1, m0 = _margin(facts, metric, later[0]), _margin(facts, metric, base)
            if m1 is None or m0 is None:
                continue
            real = round((m1 - m0) * 100)
            if abs(stated - real) > 20:
                return (f"contradicted by the filings: {mm.group(0)} {later[0]} vs {base} ≈ {real:+d} bp" if en
                        else f"contredit par les dépôts : {mm.group(0)} {later[0]} vs {base} ≈ {real:+d} pb")
        # « 55,1 % en FY2024 » : la marge de CET exercice
        for pm in _PCT_YEAR.finditer(s):
            per = "FY" + pm.group(2)
            real = _margin(facts, metric, per)
            if real is None:
                continue
            stated = float(pm.group(1).replace(",", "."))
            if abs(stated - real) > 0.15:
                val = f"{real:.1f}".replace(".", "," if not en else ".")
                return (f"contradicted by the filings: {mm.group(0)} {per} {val}%" if en
                        else f"contredit par les dépôts : {mm.group(0)} {per} {val} %")
    return None


_OTHER_AMOUNT51 = re.compile(r"\d+(?:[.,]\d+)?\s*(?:M|k|Md|bn|m)?\s*(?:\$|€|£|USD|EUR|GBP)")   # un montant, pas un %


def _qualifier_next_to51(s: str, start: int, end: int) -> bool:
    after = s[end:end + 60]
    m = _QUALIFIER.search(after)
    if m and not _OTHER_AMOUNT51.search(after[:m.start()]):
        return True
    before = s[max(0, start - 45):start]
    hits = list(_QUALIFIER.finditer(before))
    return bool(hits) and not _OTHER_AMOUNT51.search(before[hits[-1].end():])


def check_line(line: str, facts: Mapping, lang: str = "fr") -> str | None:
    """Motif de signalement pour UNE ligne, ou None. Ne modifie rien."""
    s = str(line or "")
    en = str(lang or "").lower().startswith("en")
    # un exercice cité comme BASE DE COMPARAISON (« vs FY2024 ») ne change pas l'exercice dont parle la ligne
    _s_cmp = re.sub(r"(?i)\b(?:vs\.?|versus|par\s+rapport\s+[àa]|compared\s+(?:to|with)|contre)\s+(?:l['’]exercice\s+)?(?:FY\s?)?(?:19|20)\d{2}", " ", s)
    years = {"FY" + y for y in _FY.findall(_s_cmp)}
    # 9.4.61 — contre-recette du 12/10 (A60-01) : « 53,4 % en 2024 » (année sans « FY ») était lu comme un taux FY2025
    years |= {"FY" + y for y in re.findall(r"(?<![\d/.-])(20[0-4]\d)(?![\d/.-])", _s_cmp)}
    periods = sorted({p for (_m, p) in facts})
    if not periods:
        return None
    ref = periods[-1]                                   # exercice de référence des faits confirmés
    if years and ref not in years:
        return None                                     # la ligne parle d'un autre exercice
    rev = facts.get(("REVENUE", ref))
    # 9.4.62 — recette 9.4.61 (séance 1) : « | Marge brute | 51,0 % | 53,4 % | 55,1 % | » (colonnes FY2023 à FY2025)
    # était comparée en bloc au fait FY2025 — les trois cellules, 55,1 % compris, déclarées contredites. Une ligne de tableau
    # ne porte pas l'exercice de ses colonnes : elle relève de la réconciliation des réalisés, colonne par colonne.
    if s.lstrip().startswith("|") and s.count("|") >= 3:
        return None
    # 9.4.61 — contre-recette du 12/10 (A60-01, sixième émetteur) : même règle de comparabilité que les autres émetteurs.
    # Un seuil (≥ 16,0 %), une sensibilité (« un OPEX à +5 % ramène la marge à 15,7 % »), un scénario, une hypothèse ou
    # une projection (FY2026e) ne sont pas réfutés par le réalisé de l'exercice ; un vrai réalisé erroné reste signalé.
    _noncomp61 = bool(re.search(
        r"(?i)[≥≤]|>=|<=|\b(?:sc[ée]nario|seuil|sensibilit|hypoth[èe]s|cible|objectif|propos[ée]|choc|dilution|simul|"
        r"projection|plafond|plancher|alerte|provisoire|tol[ée]ranc|garde[- ]fou|palier|pourrait|ram[eè]n|ferait|serait|"
        r"passerait|atteindrait|scenario|threshold|sensitivity|target|assumption|shock|forecast|would|could)\w*|"
        r"\bsi\s+(?:le|la|les|l['’]|on|un|une)\b|\bFY\s?20\d{2}\s?e\b|\b(?:opex|sg&a|a&p|co[uû]ts?)\s*(?:[àa]\s*)?[+\-−]\s*\d", s))
    # 1. taux dérivés
    for metric, rx in (() if _noncomp61 else _MARGIN_OF.items()):
        m = re.search(rx, s, re.I)
        num = facts.get((metric, ref))
        if not m or not rev or not num:
            continue
        # 9.4.53 — contre-recette ChatGPT du 06/10 (G02) : « Marge brute passée de 51,9 % (FY2023) à 53,4 % (FY2024) puis
        # 55,1 % (FY2025) » était opposée au fait FY2025 sur son PREMIER pourcentage (celui de FY2023) ; « +24 % de marge
        # brute en valeur » (une croissance) l'était aussi. Seul un TAUX non signé, rattaché à l'exercice de référence quand
        # la ligne en cite plusieurs, est comparé — même nature, même exercice.
        pm = None
        for _pm53 in _PCT.finditer(s, m.end()):
            if _pm53.start() - m.end() > 140:
                break
            _pre53 = s[max(0, _pm53.start() - 3):_pm53.start()]
            _post53 = s[_pm53.end():_pm53.end() + 22].lower()
            if re.search(r"[+\-−–]\s*~?\s*$", _pre53) or re.match(r"\s*(?:de\s+(?:croissance|hausse|baisse)|en\s+valeur|/an|par\s+an|pts?\b|points?)", _post53):
                continue
            # 9.4.55 — contre-recette du 07/10 (F04) : « un point de marge pèse ~6 % du résultat d'exploitation » — une PART
            # d'une autre grandeur n'est pas un taux de marge brute
            if re.match(r"\s*(?:du|de\s+la|des|de\s+l['’]|of(?:\s+the)?)\s+(?:r[ée]sultat|ebit|ebitda|ca\b|chiffre|ventes|revenu|"
                        r"b[ée]n[ée]fice|operating|revenue|sales|net\s+income|total)", _post53):
                continue
            if re.search(r"~|≈|environ", _pre53 + s[max(0, _pm53.start() - 6):_pm53.start()]):
                continue
            if len(years) > 1:
                _ctx53 = s[max(0, _pm53.start() - 25):_pm53.end() + 25]
                _yrs53 = {"FY" + y for y in _FY.findall(_ctx53)} | {"FY" + y for y in re.findall(r"(?<![\d/.-])(20[0-4]\d)(?![\d/.-])", _ctx53)}
                if ref not in _yrs53:
                    continue
                # l'exercice le plus proche du taux doit être la référence
                _near53 = min(((abs(mm.start() - _pm53.start()), "FY" + mm.group(1)) for mm in re.finditer(r"(?i)(?:\bFY\s?|(?<![\d/.-]))((?:19|20)\d{2})(?![\d/.-])", _ctx53)
                               if True), default=(0, ref))
                if _near53[1] != ref:
                    continue
            pm = _pm53
            break
        if not pm:
            continue
        stated = float(pm.group(1).replace(",", "."))
        computed = 100.0 * num / rev
        if abs(stated - computed) > 0.15:
            val = f"{computed:.1f}".replace(".", "," if not en else ".")
            return (f"contradicted by the source: {m.group(0)} {ref} {val}%" if en
                    else f"contredit par la pièce : {m.group(0)} {ref} {val} %")
    # 1 bis. calculs types bornés (contre-recette B02) — seulement quand toutes les données sont dans la ligne ou la base
    if _CAGR.search(s):
        am = [_num(a) for a in _AMOUNT.findall(s)]
        am = [a for a in am if a]
        span = _YEARS_SPAN.search(s)
        pr = _PCT.findall(s)
        _fys = sorted({int(y) for y in re.findall(r"(?i)\bFY\s?((?:19|20)\d{2})\b", s)})
        n_years = int(span.group(1)) if span else (_fys[-1] - _fys[0] if len(_fys) >= 2 else 0)
        if len(am) >= 2 and n_years and pr:
            # le point de départ et d'arrivée : le plus petit et le plus grand montant cités (trajectoire)
            a0, a1, n = min(am[:3]), max(am[:3]), n_years
            # 9.4.51 — recette du 02/10/2026 : « 700→619985 ≈ 860,3 % » (unités mélangées) et un résultat d'exploitation
            # rapproché d'une cible de chiffre d'affaires. Le contrôle ne calcule plus que sur une trajectoire PLAUSIBLE
            # (rapport d'arrivée à départ entre 0,2 et 5) et quand la ligne ne cite pas plus de deux montants ; sinon il
            # se tait — un recalcul faux coûte plus qu'aucun recalcul.
            if len(set(am)) > 2 or not (0.2 <= (a1 / a0 if a0 else 0) <= 5.0):
                a0 = 0
            if a0 > 0 and a1 > 0 and 1 <= n <= 30:
                cagr = 100.0 * ((a1 / a0) ** (1.0 / n) - 1.0)
                stated = float(pr[-1].replace(",", "."))
                if abs(stated - cagr) > 0.3:
                    val = f"{cagr:.1f}".replace(".", "," if not en else ".")
                    return (f"calculation to verify: CAGR {a0:g}→{a1:g} over {n} years ≈ {val}%" if en
                            else f"calcul à vérifier : croissance annuelle moyenne {a0:g}→{a1:g} sur {n} ans ≈ {val} %")
    dm = _DAYS.search(s)
    inv, gp = facts.get(("INVENTORIES", ref)), facts.get(("GROSS_PROFIT", ref))
    if dm and inv and rev and gp and rev > gp:
        stated_d = int(next(g for g in dm.groups() if g))
        days = inv / ((rev - gp) / 365.0)
        if abs(stated_d - days) > 5:
            return (f"calculation to verify: inventory {ref} / (cost of sales / 365) ≈ {days:.0f} days" if en
                    else f"calcul à vérifier : stocks {ref} / (coût des ventes / 365) ≈ {days:.0f} jours")
    # 2. qualification d'un montant publié tel quel
    if _QUALIFIER.search(s):
        for metric in ("NET_INCOME", "OPERATING_PROFIT"):
            v = facts.get((metric, ref))
            if not v or not re.search(_METRIC_WORDS[metric], s, re.I):
                continue
            for tok_m in re.finditer(r"\d{1,3}(?:[ ,.]\d{3})+(?:[.,]\d+)?|\d+[.,]\d+", s):
                tok = tok_m.group(0)
                x = _num(tok)
                # 9.4.51 — recette du 02/10/2026 : « BPA publié 6,69 $, hors ajustement fiscal 5,82 $ » — la mention
                # « hors ajustement » qualifiait un AUTRE montant de la ligne. Elle doit être collée au montant publié :
                # dans les 45 caractères qui le suivent ou le précèdent, sans autre montant entre les deux.
                if not _qualifier_next_to51(s, tok_m.start(), tok_m.end()):
                    continue
                if x and any(abs(x * k - v) <= 0.005 * v for k in (1, 1000, 0.001)):
                    return ("qualification to verify: the source reports this amount as published (GAAP)" if en
                            else "qualification à vérifier : la pièce publie ce montant tel quel (norme comptable)")
    return None


# ── 9.4.51 — contrôles issus de la contre-recette ChatGPT du 03/10/2026 ─────────────────────────────────────────────
def decided_options51(result: Mapping[str, Any] | None) -> dict:
    """{numéro d'option : date} des options RETENUES par le dirigeant : décision réinjectée de la séance précédente
    (« ADOPTÉE par le dirigeant : Option 2 retenue (01/10/2026) ») ou écrite dans le brief de la séance."""
    b = str(((result or {}).get("inputs") or {}).get("brief") or "")
    out: dict = {}
    for m in re.finditer(r"(?i)ADOPT(?:É|E)E\s+par\s+le\s+dirigeant\s*:\s*option\s*(\d)\s+retenue\s*(?:\(([^)]*)\))?", b):
        out[m.group(1)] = (m.group(2) or "").strip()
    for m in re.finditer(r"(?i)\bd[ée]cision\s+du\s+(?:conseil|CoDIR|comit[ée])(?:\s+du\s+(\d{1,2}/\d{1,2}/\d{4}))?[^.\n]{0,60}?"
                         r"\boption\s*(\d)\b[^.\n]{0,30}?\b(?:retenue|choisie|valid[ée]e|adopt[ée]e)", b):
        out.setdefault(m.group(2), (m.group(1) or "").strip())
    return out


def check_decided_option51(line: str, decided: Mapping[str, str], lang: str = "fr") -> str | None:
    """Une option retenue par le dirigeant ne doit plus être présentée comme simple recommandation ou choix à arbitrer
    (contre-recette du 03/10 : séance 3, « Option 2 — … (orientation RECOMMANDÉE par la direction) »)."""
    s = str(line or "")
    for n, d in (decided or {}).items():
        # présenter le CHOIX comme une recommandation ou un arbitrage à venir (« orientation recommandée », « option 2
        # recommandée », « recommandation : option 2 », « à arbitrer ») — pas recommander une modalité de mise en œuvre
        if (re.search(rf"(?i)\boption\s*{n}\b", s) and re.search(
                r"(?i)(?:orientation|option\s*\d?)\s+(?:\S+\s+){0,3}?recommand|recommand\w*\s*(?::|de\s+retenir|l['’]option)|"
                r"recommandation\b[^.]{0,25}\boption|à\s+arbitrer|à\s+d[ée]cider|recommended\s+option|option\s*\d\s+(?:is\s+)?recommended|to\s+be\s+decided", s)
                and not re.search(r"(?i)retenue|adopt|d[ée]cid[ée]e|valid[ée]e|approuv|selected|approved|chosen", s)):
            when = (f" du {d}" if d else "") if not str(lang).startswith("en") else (f" of {d}" if d else "")
            return (f"board decision{when}: option {n} selected — present it as decided" if str(lang).startswith("en")
                    else f"décision du conseil{when} : option {n} retenue — à présenter comme décidée")
    return None


_GAP51 = re.compile(r"(?i)\b(?:[ée]cart|gap|diff[ée]rence|r[ée]siduel)\b[^.;\n]{0,25}?(\d+(?:[.,]\d+)?)\s*(k\s?\$|kUSD|k\s?€|kEUR|K\$|milliers?\s+de|thousand)")
# montants en millions de la ligne, y compris ceux d'un calcul écrit sans unité (« 90,994 − 11,9 = 79,094 M$ ») ; un
# pourcentage n'en est pas un
_AMT_DEC51 = re.compile(r"(?<![\d,.])(\d+[.,](\d+))(?!\s*%)(?![\d,.])")


def check_rounding_gap51(line: str, lang: str = "fr") -> str | None:
    """Un « écart » plus petit que la précision des montants cités n'est qu'un effet d'arrondi (contre-recette du 03/10 :
    « 90,994 − 11,9 = 79,094 ≠ 79,065 », écart de 29 kUSD à investiguer, alors que 90,994 − 11,928 = 79,066)."""
    s = str(line or "")
    g = _GAP51.search(s)
    if not g:
        return None
    gap_k = float(g.group(1).replace(",", "."))
    if not re.search(r"(?i)M\s?\$|MUSD|M\s?€|MEUR|millions?", s):
        return None                                         # pas de montants en millions : pas de comparaison d'arrondi
    precisions = [0.5 * 10 ** (3 - len(m.group(2))) for m in _AMT_DEC51.finditer(s[:g.start()]) if len(m.group(2)) <= 3]
    if not precisions or gap_k > max(precisions):
        return None
    return (f"gap of {g.group(1)} k smaller than the rounding of the amounts cited — check before investigating"
            if str(lang).startswith("en") else
            f"écart de {g.group(1)} k inférieur à l'arrondi des montants cités — à vérifier avant toute investigation")


_RATIO51 = re.compile(r"(?i)(\d+(?:[.,]\d+)?)\s*(?:M\s?\$|MUSD|M\s?€|MEUR|millions?(?:\s+de\s+(?:dollars|USD|euros))?)(?![A-Za-z])[^;\n]{0,80}?"
                      r"(\d+(?:[.,]\d+)?)\s*%\s*(?:du|of(?:\s+the)?)\s*(?:CA|chiffre\s+d['’]affaires|revenues?|(?:net\s+)?sales)")


def check_revenue_ratio51(line: str, facts: Mapping, lang: str = "fr") -> str | None:
    """« 12 M$ … 2,5 % du CA » rapproché du chiffre d'affaires confirmé : le motif désigne le RATIO, pas le CA
    (contre-recette du 03/10 : 12 / 620 = 1,9 %, et le signal accusait le chiffre d'affaires)."""
    s = str(line or "")
    m = _RATIO51.search(s)
    revs = {str(p): v for (k, p), v in (facts or {}).items() if k == "REVENUE" and v}
    if not m or not revs:
        return None
    # 9.4.52 — contre-recette ChatGPT du 05/10 : « 222,6 / 619985,0 = 0,0 % du CA » rapportait un SG&A PROJETÉ FY2028 au
    # chiffre d'affaires FY2025 exprimé en milliers. Même EXERCICE et même ÉCHELLE, sinon aucun contrôle.
    years = set(re.findall(r"\b(?:FY\s?)?(20[2-4]\d)\b", s))
    if re.search(r"(?i)projet|pr[ée]vu|pr[ée]visionnel|cible|objectif|budget|horizon|plan\b|forecast|target|projected", s):
        return None
    rev_years = {re.sub(r"\D", "", p)[-4:]: p for p in revs}
    if years:
        hit = [rev_years[y] for y in years if y in rev_years]
        if not hit:
            return None                                       # exercice sans chiffre d'affaires confirmé
        revenue = revs[hit[0]]
    else:
        revenue = revs[sorted(revs)[-1]]
    if revenue > 1e8:
        revenue = revenue / 1e6                                # valeur absolue → millions
    elif revenue > 1e5:
        revenue = revenue / 1e3                                # milliers → millions
    # 9.4.57 — contre-recette ChatGPT du 10/10 (§5.3) : « … SG&A de 199,9 M$ … dépenses A&P à 6,04 % du CA » était
    # « vérifié » par 199,9 / 620 = 32,2 % : le taux portait sur une AUTRE grandeur que le montant. Si une autre grandeur
    # ou un autre nombre s'intercale entre le montant et le taux, la relation n'est pas établie : aucun motif.
    _between57 = s[m.end(1):m.start(2)]
    if re.search(r"\d", _between57) or re.search(r"(?i)\b(?:A\s?&\s?P|publicit|promotion|advertising|marketing|SG\s?&\s?A|R\s?&\s?D|"
                                                r"frais|d[ée]penses|charges|co[ûu]ts?|marge|r[ée]sultat|EBIT|capex|investissements?)\b",
                                                _between57):
        return None
    amount, pct = float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
    if revenue <= 0 or amount <= 0:
        return None
    real = amount / revenue * 100
    if abs(real - pct) <= max(0.3, 0.1 * pct):
        return None
    f = lambda x: (f"{x:.1f}" if str(lang).startswith("en") else f"{x:.1f}".replace(".", ","))
    return (f"ratio to check: {f(amount)} / {f(revenue)} = {f(real)} % of revenue" if str(lang).startswith("en")
            else f"ratio à vérifier : {f(amount)} / {f(revenue)} = {f(real)} % du CA")


def check_false_absence51(line: str, result: Mapping[str, Any] | None, lang: str = "fr") -> str | None:
    """Une donnée fournie par les pièces ne doit pas être déclarée absente (contre-recette du 03/10 : effectif « Non
    communiqué » alors que le 10-K donne 714 salariés)."""
    s = str(line or "")
    if not re.search(r"(?i)non\s+communiqu|non\s+disponible|non\s+fourni|absent\s+des\s+pi[èe]ces|not\s+disclosed|not\s+available", s):
        return None
    meta = (result or {}).get("meta") or {}
    hc = str((result or {}).get("headcount51") or meta.get("headcount51") or "").strip()
    if hc and re.search(r"(?i)effectif|salari[ée]s|collaborateurs|headcount|employees|staff", s):
        return (f"data given by the documents: headcount {hc}" if str(lang).startswith("en")
                else f"donnée fournie par les pièces : effectif {hc}")
    return None


_UNIT_MIX55 = re.compile(r"(?i)[+\-−–]?\s?\d+(?:[.,]\d+)?\s*(?:M\s?\$|MUSD|M\s?€|MEUR|k\s?\$|k\s?€)\s+de\s+marge\s+en\s+%")


def check_unit_mix55(line: str, lang: str = "fr") -> str | None:
    """9.4.55 — contre-recette du 07/10 (F01) : « +2,3 M$ de marge en % » mélange un montant et un taux. Le motif nomme le
    mélange (variation en valeur ou en points ?) au lieu d'un générique « chiffre sans pièce »."""
    if _UNIT_MIX55.search(str(line or "")):
        return ("unit to check: a margin change is either an amount or points, not both" if str(lang).startswith("en")
                else "unité à vérifier : une variation de marge s'exprime en valeur (M$) ou en points, pas les deux")
    return None


def flag_lines(text: str, result: Mapping[str, Any] | None, lang: str = "fr") -> list:
    facts = confirmed_facts(result)
    decided = decided_options51(result)
    out = []
    for i, l in enumerate(str(text or "").splitlines()):
        mot = (check_decided_option51(l, decided, lang) or check_unit_mix55(l, lang) or check_rounding_gap51(l, lang)
               or check_false_absence51(l, result, lang)
               or (facts and (check_prior_year(l, facts, lang) or check_line(l, facts, lang) or check_revenue_ratio51(l, facts, lang))))
        if mot:
            out.append((i, mot))
    return out
