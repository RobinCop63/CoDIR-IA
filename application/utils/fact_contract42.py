"""v62.13.9.4.43 — CONTRAT DE FAIT FINANCIER AU POINT DE PASSAGE OBLIGÉ.

Contre-audit indépendant du 25/09/2026. Le contrat de donnée posé les jours précédents
vivait dans UN producteur — le repli `build_facts_from_fs_block` — alors que les faits qui
atteignent le Word viennent d'abord de la couche de preuve primaire, puis des faits
documentaires, des registres, du brief et des calculs dérivés. Résultat mesuré sur
fixtures synthétiques : « Net debt (125) » servi en +125 M£ coché FAIT ; « Effect of
exchange rates on cash » servi comme un solde de trésorerie ; un tableau intitulé
« budget – forecast, not actual » servi en réalisé ; des stocks lus dans un compte de
résultat ; un périmètre inconnu qualifié.

Ce module est le validateur COMMUN : il s'applique à chaque fait de la table, quel que
soit le chemin qui l'a produit, avant toute confirmation et toute sérialisation. Aucune
règle par société, dossier, valeur ou nom de fichier : des règles de grandeur, de nature,
de signe, de période et de périmètre. Un fait qui ne passe pas n'est pas effacé : il est
déclassé, garde sa page, et porte la raison.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

__all__ = ["enforce_fact_contract42", "classify_line_nature42"]

# ── familles de grandeurs ─────────────────────────────────────────────────────
_BALANCE_METRICS = {"CASH", "STOCKS", "INVENTORIES", "RECEIVABLES", "TRADE_RECEIVABLES",
                    "PAYABLES", "NET_DEBT", "TOTAL_ASSETS", "EQUITY", "TOTAL_EQUITY",
                    "GROSS_DEBT", "DEBT"}
_PL_METRICS = {"REVENUE", "GROSS_PROFIT", "OPERATING_PROFIT", "EBITDA", "EBIT",
               "NET_INCOME", "PROFIT_BEFORE_TAX", "COST_OF_SALES", "OPERATING_MARGIN"}
_FLOW_METRICS = {"OPERATING_CASH_FLOW", "FREE_CASH_FLOW", "FCF", "CAPEX"}

_LABEL_TO_FAMILY = (
    (re.compile(r"cash|tr[ée]sorerie|disponibilit", re.I), "CASH"),
    (re.compile(r"inventor|stocks?\b", re.I), "STOCKS"),
    (re.compile(r"receivable|cr[ée]ances", re.I), "RECEIVABLES"),
    (re.compile(r"payable|dettes?\s+fournisseurs", re.I), "PAYABLES"),
    (re.compile(r"net\s+debt|dette\s+nette|endettement\s+net", re.I), "NET_DEBT"),
    (re.compile(r"total\s+assets|total\s+(?:de\s+l['’])?actif|total\s+du\s+bilan", re.I), "TOTAL_ASSETS"),
    (re.compile(r"equity|capitaux\s+propres", re.I), "EQUITY"),
    (re.compile(r"revenue|net\s+sales|turnover|chiffre\s+d['’]affaires", re.I), "REVENUE"),
    (re.compile(r"gross\s+profit|marge\s+brute", re.I), "GROSS_PROFIT"),
    (re.compile(r"operating\s+(?:profit|income)|r[ée]sultat\s+d['’]exploitation", re.I), "OPERATING_PROFIT"),
    (re.compile(r"\bEBITDA\b", re.I), "EBITDA"),
    (re.compile(r"net\s+income|net\s+profit|r[ée]sultat\s+net", re.I), "NET_INCOME"),
    (re.compile(r"free\s+cash\s+flow|\bFCF\b", re.I), "FREE_CASH_FLOW"),
    (re.compile(r"capex|capital\s+expenditure|investissements?", re.I), "CAPEX"),
)

# ── nature d'une ligne : variation, solde, flux ──────────────────────────────
_VARIATION_RE = re.compile(
    r"effects?\s+of\s+(?:exchange|foreign|fx)|exchange\s+rate|changes?\s+in|movements?\s+in|"
    r"net\s+(?:increase|decrease|change)|increase\s+in|decrease\s+in|\bvariations?\b|"
    r"\bmouvements?\b|working\s+capital|besoin\s+en\s+fonds|augmentation\s+d|diminution\s+d|"
    r"[ée]cart\s+de\s+(?:change|conversion)|impact\s+de\s+change", re.I)
_BALANCE_MARK_RE = re.compile(
    r"at\s+(?:the\s+)?(?:end|beginning|start)|at\s+\d{1,2}\s+\w+|as\s+(?:at|of)|closing|opening|"
    r"ending|beginning|year[-\s]end|à\s+la\s+(?:fin|clôture|cl[oô]ture)|en\s+fin\s+d|au\s+\d{1,2}[/ ]|"
    r"solde|balance\s+(?:at|as)", re.I)
_PROSPECTIVE_RE = re.compile(
    r"\bbudgets?\b|\bforecasts?\b|\bforecasted\b|pr[ée]vision|pr[ée]visionnel|not\s+actual|"
    r"\btargets?\b|\bobjectifs?\b|\bguidance\b|\boutlook\b|\bprojected\b|\bprojections?\b|"
    r"\bplan\s+\d{4}|\bestimates?\b|\bcibles?\b|atterrissage|\bpro\s*forma\b|\bscenario\b|sc[ée]nario", re.I)
_ACTUAL_MARK_RE = re.compile(r"\bactual\b|\br[ée]alis[ée]e?\b|\baudited\b|\baudit[ée]s?\b", re.I)

_CANON_ID_RE46 = [
    (re.compile(r"adjusted\s+operating\s+profit|r[ée]sultat\s+op[ée]rationnel\s+ajust", re.I), "ADJUSTED_OPERATING_PROFIT"),
    (re.compile(r"operating\s+(?:profit|income)|income\s+from\s+operations|r[ée]sultat\s+(?:d['’]exploitation|op[ée]rationnel)", re.I), "OPERATING_PROFIT"),
    (re.compile(r"gross\s+(?:profit|margin)|marge\s+brute", re.I), "GROSS_MARGIN"),
    (re.compile(r"\bebitda\b", re.I), "EBITDA"),
    (re.compile(r"net\s+(?:income|profit|earnings)|r[ée]sultat\s+net", re.I), "NET_INCOME"),
    (re.compile(r"^\s*(?:revenue|turnover|net\s+sales|chiffre\s+d['’]affaires)", re.I), "REVENUE"),
    (re.compile(r"net\s+debt|dette\s+nette", re.I), "NET_DEBT"),
    (re.compile(r"cash\s+and\s+cash\s+equivalents|tr[ée]sorerie", re.I), "CASH"),
    (re.compile(r"inventor(?:y|ies)|\bstocks?\b", re.I), "STOCKS"),
]

_PAGE_MARK_RE = re.compile(r"^\s*(?:--\s*p\.\s*\d+\s*--|---\s.*?---|#{1,3}\s)")
# Un titre d'état FORT sur la page — c'est lui qui rend l'état d'origine opposable. Une
# page de « faits marquants » qui mêle chiffre d'affaires, EBITDA, trésorerie et dette
# nette n'est pas un compte de résultat, même si le classement de page l'a rangée là :
# le rapport annuel réel d'un groupe britannique l'a rappelé dès la première suite.
_STRONG_TITLE_RE = {
    "income_statement": re.compile(r"income\s+statement|statements?\s+of\s+(?:profit|comprehensive\s+income|operations)|"
                                   r"profit\s+and\s+loss|compte\s+de\s+r[ée]sultat", re.I),
    "balance_sheet": re.compile(r"balance\s+sheet|statement\s+of\s+financial\s+position|\bbilan\b", re.I),
    "cash_flow": re.compile(r"cash\s*flow\s+statement|statements?\s+of\s+cash\s*flows?|tableau\s+des\s+flux", re.I),
}


def _family(fact) -> str:
    mid = str(getattr(fact, "metric_canonical_id", "") or "").upper()
    if mid in _BALANCE_METRICS or mid in _PL_METRICS or mid in _FLOW_METRICS:
        return mid
    label = str(getattr(fact, "label", "") or "")
    for rx, fam in _LABEL_TO_FAMILY:
        if rx.search(label):
            return fam
    return mid


def _is_balance(fam: str) -> bool:
    return fam in _BALANCE_METRICS


def _is_pl(fam: str) -> bool:
    return fam in _PL_METRICS


def classify_line_nature42(line: str) -> str:
    """« variation », « balance », « flow » ou « » (indéterminé) pour une ligne d'état."""
    t = str(line or "")
    if _BALANCE_MARK_RE.search(t):
        return "balance"
    if _VARIATION_RE.search(t):
        return "variation"
    return ""


_PAGE_BREAK_RE = re.compile(r"^\s*(?:--\s*p\.\s*\d+\s*--|---\s.*?---)\s*$")
_HEADING_RE = re.compile(r"^\s*#{1,3}\s")
_NUM_TOKEN_RE = re.compile(r"\(?-?\d[\d\s\u00a0\u202f.,]*\)?%?")


def _context_lines(block: str, excerpt: str, n: int = 10) -> List[str]:
    """v62.13.9.4.44 — LE TITRE GOUVERNE SA PAGE, QUELLE QUE SOIT LA DISTANCE.

    Contre-audit du 25/09/2026 (M1-01, M1-02) : le contexte était une fenêtre de dix lignes
    qui s'arrêtait à la première ligne « # ». Un budget de douze lignes perdait sa nature
    budgétaire à la treizième ; un titre écrit en Markdown n'était jamais lu. Le contexte
    est désormais structurel : tous les titres, en-têtes de section et lignes non
    chiffrées de la PAGE qui précèdent l'extrait — le titre de section « # » posé juste
    avant le repère de page compris.
    """
    if not block or not excerpt:
        return []
    lines = str(block).split("\n")
    key = str(excerpt).strip()[:60]
    idx = next((k for k, l in enumerate(lines) if key and key in l), None)
    if idx is None:
        return []
    start = 0
    for k in range(idx - 1, -1, -1):
        if _PAGE_BREAK_RE.match(lines[k]):
            start = k
            break
    out: List[str] = []
    # le titre de section « ### … » qui précède immédiatement le repère de page en fait partie
    for k in range(max(0, start - 3), start):
        if _HEADING_RE.match(lines[k]):
            out.append(lines[k])
    for k in range(start, idx):
        l = lines[k]
        if _PAGE_BREAK_RE.match(l):
            continue
        toks = _NUM_TOKEN_RE.findall(l)
        if _HEADING_RE.match(l) or len(toks) < 2 or re.search(r"\b(?:FY|Q[1-4]|S[12])\s?\d{2,4}\b|\b(?:19|20)\d{2}\b", l):
            out.append(l)
    return out


_COLUMN_QUAL_RE = re.compile(
    r"(?P<pro>\bbudgets?\b|\bforecasts?\b|pr[ée]vision(?:nel)?s?|\btargets?\b|\bplan\b|\bguidance\b|\bestimates?\b|\bproject(?:ed|ion)s?\b)"
    r"|(?P<act>\bactuals?\b|r[ée]alis[ée]s?|\baudited\b|\breported\b|\bhistoric(?:al)?\b)", re.I)
_PERIOD_TOKEN_RE = re.compile(r"\bFY\s?\d{2,4}\b|\b(?:19|20)\d{2}\b", re.I)


def _column_nature42(context: List[str], period: str) -> str:
    """« prospective », « actual » ou «» : la nature de LA COLONNE du fait, lue dans un
    en-tête qui qualifie ses colonnes — « FY2025 actual | FY2026 budget ». C'est ce qui
    empêche qu'un mot « budget » sur la page dégrade aussi la colonne réalisée (M1-05)."""
    per = re.sub(r"\D", "", str(period or ""))
    if len(per) == 2:
        per = "20" + per
    if not per:
        return ""
    for line in context:
        toks = list(_PERIOD_TOKEN_RE.finditer(line))
        quals = list(_COLUMN_QUAL_RE.finditer(line))
        if not toks or not quals:
            continue
        # chaque qualificatif va au repère de période LE PLUS PROCHE : dans
        # « FY2025 actual FY2026 budget », « actual » touche FY2025 et « budget » FY2026.
        # le style de l'en-tête est constant sur la ligne : « Budget FY2026 Actual FY2025 »
        # qualifie AVANT le repère, « FY2025 actual FY2026 budget » qualifie APRÈS.
        prefix_style = quals[0].start() < toks[0].start()
        verdict = {}
        for q in quals:
            if prefix_style:
                cands = [t for t in toks if t.start() >= q.end()]
                nearest = min(cands, key=lambda t: t.start() - q.end()) if cands else None
            else:
                cands = [t for t in toks if t.end() <= q.start()]
                nearest = max(cands, key=lambda t: t.end()) if cands else None
            if nearest is None:
                continue
            key = re.sub(r"\D", "", nearest.group(0))[-4:]
            verdict.setdefault(key, "prospective" if q.group("pro") else "actual")
        if per[-4:] in verdict:
            return verdict[per[-4:]]
    return ""


def _downgrade(fact, reason: str, blocker: str) -> None:
    try:
        from utils.financial_facts_table import FactStatus
        if getattr(fact, "status", None) == FactStatus.FAIT:
            fact.status = FactStatus.A_VERIFIER
    except Exception:
        pass
    if str(getattr(fact, "proof_status", "")) == "CONFIRMED_ON_PAGE":
        fact.proof_status = "DECLARED_UNCONFIRMED"
    fact.board_safe_candidate = False
    fact.board_safe_blockers = list(getattr(fact, "board_safe_blockers", []) or []) + [blocker]
    fact.notes = list(getattr(fact, "notes", []) or []) + [reason]


def _sign_of_source(fact) -> Optional[int]:
    """-1 si la valeur est parenthésée ou précédée d'un moins dans la source, +1 si
    explicitement positive, None si indéterminable."""
    raw = str(getattr(fact, "source_value_text", "") or "").strip()
    if raw:
        if re.match(r"^\(\s*[\d\s\u00a0\u202f.,]+\s*\)$", raw) or re.match(r"^[-−–]\s*\d", raw):
            return -1
        if re.match(r"^\d", raw):
            return 1
    exc = str(getattr(fact, "source_excerpt", "") or "")
    nv = getattr(fact, "normalized_value", None)
    digits = re.sub(r"\D", "", str(getattr(fact, "value", "") or ""))
    if exc and digits:
        head = digits[:3]
        m = re.search(r"([(\-−–]?)\s*" + head + r"[\d\s\u00a0\u202f.,]*\)?", exc)
        if m:
            span = exc[m.start():m.end()]
            if span.startswith("(") and span.rstrip().endswith(")"):
                return -1
            if span[:1] in "-−–":
                return -1
            return 1
    return None


def enforce_fact_contract42(facts: Iterable[Any], block_text: str = "") -> Dict[str, int]:
    """Applique le contrat à chaque fait, quel que soit son producteur. Retourne un compte
    par règle déclenchée, pour le diagnostic."""
    counts: Dict[str, int] = {}

    def bump(k: str) -> None:
        counts[k] = counts.get(k, 0) + 1

    for f in facts or []:
        try:
            fam = _family(f)
            exc = str(getattr(f, "source_excerpt", "") or "")
            sect = str(getattr(f, "source_section", "") or "").lower()
            nv = getattr(f, "normalized_value", None)
            is_amount = nv is not None and str(getattr(f, "unit", "") or "").upper() not in ("PCT", "PERSONS", "RATIO")

            # 0. IDENTIFIANT CANONIQUE — un fait du repli n'en portait pas : la situation
            # courante ne pouvait jamais s'établir sans la couche primaire (run réel de référence du
            # 26/09/2026). Le libellé donne la grandeur ; l'identifiant suit.
            if not str(getattr(f, "metric_canonical_id", "") or "").strip():
                _lab = str(getattr(f, "label", "") or "")
                for _rx, _mid in _CANON_ID_RE46:
                    if _rx.search(_lab):
                        f.metric_canonical_id = _mid
                        break

            # 1. SIGNE — LITTÉRAL, PARTOUT (arbitrage de Robin Sauzet, 25/09/2026). Une
            # parenthèse comptable ou un moins dans la source est un moins dans la valeur
            # normalisée et dans la valeur rendue, quel que soit le libellé — dette nette
            # comprise. Une dette « Net debt (852) » sort donc à −852 M£ : c'est ce que la
            # page écrit, et c'est le signe que le lecteur doit retrouver. La note dit
            # que le signe vient de la source, pour qu'aucune requalification ne soit
            # silencieuse dans l'autre sens non plus.
            if is_amount:
                s = _sign_of_source(f)
                if s == -1 and float(nv) > 0:
                    f.normalized_value = -abs(float(nv))
                    v = str(getattr(f, "value", "") or "")
                    if v and not v.lstrip().startswith(("-", "−", "(")):
                        f.value = "-" + v.lstrip()
                    f.sign_presentation = "negative_in_source"
                    f.notes = list(getattr(f, "notes", []) or []) + [
                        "Signe littéral : la source porte la valeur entre parenthèses ou avec un moins"]
                    bump("sign_restored")

            # 2. NATURE — une variation n'est pas un solde.
            nature = classify_line_nature42(exc)
            if _is_balance(fam) and nature == "variation":
                _downgrade(f, "Ligne de variation (effet de change, mouvement, besoin en fonds de "
                              "roulement) — ce n'est pas un solde", "variation_not_balance")
                f.nature = "VARIATION"
                bump("variation_not_balance")

            # 3. ÉTAT D'ORIGINE — un poste se lit dans son état, quand l'état est certain :
            # le titre fort de la page doit confirmer le classement de section.
            _ctx3 = " ".join(_context_lines(block_text, exc)) if block_text else ""
            # un titre fort peut aussi être le titre de section « ### … » de la page
            _strong = bool(_STRONG_TITLE_RE.get(sect) and _STRONG_TITLE_RE[sect].search(_ctx3)) if sect else False
            if sect and (_strong or not block_text):
                if _is_balance(fam) and sect == "income_statement":
                    _downgrade(f, "Poste de bilan lu dans un compte de résultat — état incompatible",
                               "statement_mismatch")
                    bump("statement_mismatch")
                elif _is_pl(fam) and sect == "balance_sheet":
                    _downgrade(f, "Poste de résultat lu dans un bilan — état incompatible",
                               "statement_mismatch")
                    bump("statement_mismatch")
                elif _is_balance(fam) and sect == "cash_flow" and nature != "balance":
                    _downgrade(f, "Poste de bilan lu dans un tableau des flux sans solde explicite "
                                  "(ouverture/clôture) — nature non établie", "cash_flow_not_a_balance")
                    bump("cash_flow_not_a_balance")

            # 4. PROSPECTIF — un budget n'est pas un réalisé ; la COLONNE tranche avant la page.
            _ctx_lines = _context_lines(block_text, exc)
            ctx = " ".join(_ctx_lines) + " " + exc
            _col = _column_nature42(_ctx_lines, str(getattr(f, "period", "") or ""))
            if _col == "actual":
                pass                                     # colonne réalisée explicitement : conservée
            elif _col == "prospective" or (
                    _PROSPECTIVE_RE.search(ctx) and not (_ACTUAL_MARK_RE.search(exc) and not _PROSPECTIVE_RE.search(exc))):
                _downgrade(f, "Tableau, colonne ou ligne prospectif (budget, prévision, cible, scénario) — "
                              "conservé comme tel, pas comme un réalisé", "prospective_not_actual")
                f.nature = "PROSPECTIVE"
                bump("prospective_not_actual")

            # 5. PÉRIMÈTRE — inconnu n'est pas un périmètre, pour TOUT chiffre présenté :
            # un ratio sans périmètre est aussi insuffisamment qualifié (M1-04).
            scope = str(getattr(f, "scope", "") or "").upper()
            has_value = nv is not None
            if has_value and scope in ("", "UNKNOWN", "NONE"):
                _downgrade(f, "Périmètre non établi — un fait sans périmètre reste à qualifier",
                           "scope_unknown")
                bump("scope_unknown")

            # 7. PROVENANCE — un chiffre du brief est une DÉCLARATION de l'utilisateur
            # (hypothèse, cible, décision), jamais un fait réalisé, tant qu'une page ne le
            # confirme pas (M1-03 : « FY2028 revenue 740m » du brief typé FAIT).
            _src = " ".join(str(getattr(f, a, "") or "") for a in ("source_doc", "source_type", "source_section", "label"))
            if re.search(r"\bbrief\b", _src, re.I) and str(getattr(f, "proof_status", "")) != "CONFIRMED_ON_PAGE":
                _downgrade(f, "Chiffre du brief : déclaration de l'utilisateur (hypothèse, cible ou décision), "
                              "pas un fait réalisé tant qu'aucune page ne le confirme", "brief_declared_not_fact")
                f.nature = getattr(f, "nature", "") or "DECLARED_BY_BRIEF"
                bump("brief_declared_not_fact")

            # 6. PÉRIODE — sans période, un montant ne se rattache à rien.
            if has_value and not str(getattr(f, "period", "") or "").strip():
                _downgrade(f, "Période non établie — à qualifier avant usage", "period_missing")
                bump("period_missing")
        except Exception:
            continue
    return counts
