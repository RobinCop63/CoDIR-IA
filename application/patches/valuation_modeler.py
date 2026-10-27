"""
CoDIR-IA — valuation_modeler v1.0  (v17.1)

Valorisation d'entreprise par PLUSIEURS méthodes, sur demande. Module PUR
(aucun I/O, aucun LLM) : les hypothèses entrent, les fourchettes sortent, tout
est traçable et taguable (doctrine Q2 : entrées FAIT/ESTIM-*).

Méthodes couvertes :
  1. DCF (Discounted Cash Flow) — WACC via CAPM, projection FCF, valeur
     terminale de Gordon, pont Enterprise Value → Equity Value.
  2. Multiples de comparables (EV/EBITDA, EV/Sales, P/E).
  3. Actif net réévalué (ANR) — approche patrimoniale.

GARDE-FOU : une DCF n'est pertinente que sur des FCF normalisés positifs ou
convergents. Le module DÉTECTE et SIGNALE les cas inadaptés (FCF durablement
négatifs, pré-rentabilité) plutôt que de produire une fausse précision — cf.
cas type société en cash-burn : DCF non pertinente, comparables/ANR à
privilégier). Cohérent avec « Scope/Proof before math ».
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# =============================================================================
# 1. WACC via CAPM
# =============================================================================

def capm_cost_of_equity(rf: float, beta: float, erp: float) -> float:
    """Coût des fonds propres = rf + beta * prime de risque actions."""
    return rf + beta * erp


def wacc(*, equity_value: float, debt_value: float, cost_equity: float,
         cost_debt: float, tax_rate: float) -> float:
    """WACC pondéré. equity_value/debt_value : valeurs de marché ou proxies."""
    total = equity_value + debt_value
    if total <= 0:
        raise ValueError("equity_value + debt_value doit être > 0 pour le WACC.")
    we, wd = equity_value / total, debt_value / total
    return we * cost_equity + wd * cost_debt * (1 - tax_rate)


# =============================================================================
# 2. DCF
# =============================================================================

@dataclass
class DCFInputs:
    fcf_projection: list[float]       # FCF par année (n années explicites)
    wacc: float                       # ex. 0.10
    terminal_growth: float            # g de Gordon, ex. 0.02
    net_debt: float = 0.0             # dette nette (pont EV→Equity)
    minorities: float = 0.0
    shares_outstanding: float | None = None


def _gordon_terminal_value(last_fcf: float, wacc_: float, g: float) -> float:
    if wacc_ <= g:
        raise ValueError("WACC doit être strictement supérieur à g (Gordon).")
    return last_fcf * (1 + g) / (wacc_ - g)


def dcf_valuation(inp: DCFInputs) -> dict:
    """Retourne EV, equity value, prix par action + diagnostic d'applicabilité."""
    fcf = list(inp.fcf_projection)
    if not fcf:
        raise ValueError("fcf_projection vide.")

    # Applicabilité : DCF peu fiable si FCF majoritairement négatifs.
    n_neg = sum(1 for f in fcf if f < 0)
    applicable = n_neg <= len(fcf) // 2 and fcf[-1] > 0
    warnings: list[str] = []
    if not applicable:
        warnings.append(
            "DCF PEU FIABLE : FCF normalisés négatifs/non convergents — "
            "privilégier comparables et ANR (cas pré-rentabilité / cash-burn)."
        )

    pv_explicit = sum(f / (1 + inp.wacc) ** (i + 1) for i, f in enumerate(fcf))
    tv = _gordon_terminal_value(fcf[-1], inp.wacc, inp.terminal_growth)
    pv_tv = tv / (1 + inp.wacc) ** len(fcf)
    ev = pv_explicit + pv_tv
    equity_value = ev - inp.net_debt - inp.minorities
    tv_share = pv_tv / ev if ev else None
    if tv_share is not None and tv_share > 0.75:
        warnings.append(
            f"Valeur terminale = {tv_share:.0%} de l'EV : valorisation dominée "
            "par les hypothèses long terme (sensibilité élevée à g et WACC)."
        )

    per_share = (equity_value / inp.shares_outstanding
                 if inp.shares_outstanding else None)

    return {
        "method": "DCF",
        "applicable": applicable,
        "enterprise_value": round(ev, 2),
        "pv_explicit": round(pv_explicit, 2),
        "pv_terminal": round(pv_tv, 2),
        "terminal_value_share": round(tv_share, 4) if tv_share is not None else None,
        "equity_value": round(equity_value, 2),
        "value_per_share": round(per_share, 4) if per_share is not None else None,
        "warnings": warnings,
        "inputs": {
            "wacc": inp.wacc, "terminal_growth": inp.terminal_growth,
            "net_debt": inp.net_debt, "n_years": len(fcf),
        },
    }


def dcf_sensitivity(inp: DCFInputs, wacc_steps: list[float],
                    g_steps: list[float]) -> dict:
    """Matrice de sensibilité EV (lignes = WACC, colonnes = g)."""
    matrix = []
    for w in wacc_steps:
        row = []
        for g in g_steps:
            try:
                v = dcf_valuation(DCFInputs(
                    fcf_projection=inp.fcf_projection, wacc=w, terminal_growth=g,
                    net_debt=inp.net_debt, minorities=inp.minorities,
                    shares_outstanding=inp.shares_outstanding,
                ))["enterprise_value"]
            except ValueError:
                v = None
            row.append(v)
        matrix.append(row)
    return {"wacc_axis": wacc_steps, "g_axis": g_steps, "ev_matrix": matrix}


# =============================================================================
# 3. Multiples de comparables
# =============================================================================

def multiples_valuation(*, metric_value: float, multiple: float,
                        metric: str = "EBITDA", net_debt: float | None = 0.0,
                        shares_outstanding: float | None = None) -> dict:
    """EV (ou Equity) par multiple. EV/EBITDA & EV/Sales → EV ; P/E → Equity.

    AUDIT F.6.1 — pont EV→Equity honnête : si `net_debt is None` (dette nette
    inconnue), on NE fabrique PAS d'equity (pas de « equity = EV ») : equity
    reste None et seule l'EV indicative est produite."""
    metric = metric.upper()
    bridge = net_debt is not None
    if metric in ("EBITDA", "SALES", "EBIT"):
        ev = metric_value * multiple
        equity = (ev - net_debt) if bridge else None
        kind = f"EV/{metric}"
    elif metric in ("PE", "P/E", "EARNINGS"):
        equity = metric_value * multiple
        ev = (equity + net_debt) if bridge else None
        kind = "P/E"
    else:
        raise ValueError(f"Métrique de multiple non supportée : {metric}")
    per_share = (equity / shares_outstanding
                 if (shares_outstanding and equity is not None) else None)
    return {
        "method": "Multiples", "kind": kind,
        "enterprise_value": round(ev, 2) if ev is not None else None,
        "equity_value": round(equity, 2) if equity is not None else None,
        "net_debt_applied": net_debt if bridge else None,
        "value_per_share": round(per_share, 4) if per_share is not None else None,
    }


# =============================================================================
# 4. Actif net réévalué (ANR)
# =============================================================================

def asset_based_valuation(*, total_assets_fair_value: float,
                          total_liabilities: float) -> dict:
    """Approche patrimoniale : actifs réévalués − dettes."""
    equity = total_assets_fair_value - total_liabilities
    return {"method": "ANR (actif net réévalué)", "equity_value": round(equity, 2)}


# =============================================================================
# Synthèse multi-méthodes (football field)
# =============================================================================

def valuation_summary(results: list[dict], basis: str = "equity") -> dict:
    """Agrège plusieurs valeurs en fourchette (min/médiane/max) sur une BASE
    homogène — « equity » (equity_value) ou « enterprise_value » — en excluant
    les méthodes non applicables ou sans valeur sur cette base. On NE mélange
    PAS EV et equity (audit F.6.1)."""
    field = "equity_value" if basis == "equity" else "enterprise_value"
    usable = [r for r in results
              if r.get(field) is not None and r.get("applicable", True)]
    vals = sorted(r[field] for r in usable)
    if not vals:
        return {"low": None, "mid": None, "high": None, "methods_used": 0,
                "basis": basis,
                "note": "Aucune méthode applicable sur cette base — valorisation non concluante."}
    n = len(vals)
    mid = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    return {
        "low": round(vals[0], 2), "mid": round(mid, 2), "high": round(vals[-1], 2),
        "methods_used": n, "basis": basis,
        "excluded_non_applicable": [r["method"] for r in results
                                    if not r.get("applicable", True)],
    }


__all__ = [
    "capm_cost_of_equity", "wacc",
    "DCFInputs", "dcf_valuation", "dcf_sensitivity",
    "multiples_valuation", "asset_based_valuation", "valuation_summary",
    "detect_valuation_intent", "extract_financials_from_facts",
    "run_valuation_on_demand",
]


# =============================================================================
# Valorisation « à la demande » — détection d'intention + orchestration
# =============================================================================

_VALUATION_INTENT_RX = re.compile(
    r"valoris|valorisation|valoriser|combien\s+(?:vaut|ça\s+vaut|elle\s+vaut)|"
    r"que\s+vaut|enterprise\s+value|equity\s+value|\bDCF\b|multiples?|"
    r"EV/EBITDA|EV/Sales|fourchette\s+de\s+valo|prix\s+de\s+la\s+(?:soci[ée]t[ée]|bo[îi]te)",
    flags=re.IGNORECASE,
)


def detect_valuation_intent(brief: str) -> bool:
    """True si le brief demande explicitement une valorisation."""
    return bool(_VALUATION_INTENT_RX.search(brief or ""))


def _parse_amount(value_str: str | None) -> float | None:
    """Parse '9,8 M€', '-20 000 €', '2,383 M£', '-557 K€', '1,2 Md€' → float.
    Ignore les pourcentages et les ratios."""
    if not value_str or "%" in value_str:
        return None
    s = str(value_str).split("(")[0]
    m = re.search(r"(-?\s*\d[\d\s\u202f.,]*)\s*(Md|Mrd|bn|M|m|K|k)?\s*[€$£]?", s)
    if not m:
        return None
    num = m.group(1).replace(" ", "").replace("\u202f", "")
    if "," in num and "." in num:           # 1.234,56 → 1234.56
        num = num.replace(".", "").replace(",", ".")
    else:                                   # 9,8 → 9.8
        num = num.replace(",", ".")
    try:
        val = float(num)
    except ValueError:
        return None
    mult = {"md": 1e9, "mrd": 1e9, "bn": 1e9, "m": 1e6, "k": 1e3}.get(
        (m.group(2) or "").lower(), 1.0)
    return val * mult


_FIN_KEYWORDS = {
    "revenue":    ("chiffre d'affaires", "chiffre d’affaires", "revenue", "turnover"),
    "ebitda":     ("ebitda",),
    "net_income": ("résultat net", "resultat net", "net income", "net loss", "perte nette"),
    "equity":     ("capitaux propres", "equity", "shareholders"),
    # Pont EV→Equity (audit F.6.1/F.6.2) : intrants de dette nette.
    # CASH = SOLDE DE BILAN uniquement (pas un flux). On exige des libellés
    # qualifiés et on EXCLUT les flux (voir _FLOW_EXCLUSIONS) — un « flux de
    # trésorerie opérationnelle -22 M€ » n'est PAS du cash de bilan.
    "net_debt":   ("dette nette", "endettement net", "net debt", "net financial debt"),
    "cash":       ("trésorerie disponible", "tresorerie disponible",
                   "trésorerie et équivalents", "tresorerie et equivalents",
                   "trésorerie et équivalent", "trésorerie nette", "tresorerie nette",
                   "disponibilités", "disponibilites",
                   "cash and cash equivalents", "cash & equivalents",
                   "cash equivalents", "cash balance", "cash at bank"),
    "gross_debt": ("dette brute", "dette financière brute", "dettes financières",
                   "gross debt", "total debt", "financial debt"),
}

# Libellés de FLUX (à exclure des soldes de bilan cash/dette) — audit F.6.2/F.6.3.
_FLOW_EXCLUSIONS = (
    "flux de trésorerie", "flux de tresorerie", "flux net de trésorerie",
    "cash flow", "cash-flow", "fcf", "free cash flow", "free cash-flow",
    "cash burn", "cash-burn", "cashburn", "burn rate",
    "flux d'investissement", "flux d’investissement", "flux de financement",
    "flux opérationnel", "flux operationnel", "flux d'exploitation", "flux d’exploitation",
    "variation de trésorerie", "variation de la trésorerie", "variation de tresorerie",
    "tableau de flux", "capacité d'autofinancement", "caf",
)
_NET_DEBT_KEYS = ("cash", "gross_debt", "net_debt")


def extract_financials_from_facts(facts: Any) -> dict:
    """Best-effort : extrait revenue/ebitda/net_income/equity depuis une liste de
    FinancialFact (ou de dicts). Retient le périmètre rencontré.

    v17.1-B1 — PRÉCÉDENCE DE PÉRIMÈTRE : pour une métrique donnée, un fait
    CONSOLIDATED prime sur un SEGMENT, qui prime sur un SOCIAL_STANDALONE
    (évite qu'un CA social standalone ~0 supplante un CA consolidé).
    """
    out: dict = {}
    meta: dict = {}
    scopes: set[str] = set()
    _SCOPE_RANK = {"CONSOLIDATED": 3, "SEGMENT": 2, "SOCIAL_STANDALONE": 1}
    best_rank: dict[str, int] = {}
    for f in facts or []:
        label = (getattr(f, "label", None) or (f.get("label") if isinstance(f, dict) else "") or "").lower()
        value = getattr(f, "value", None) or (f.get("value") if isinstance(f, dict) else None)
        scope = getattr(f, "scope", None) or (f.get("scope") if isinstance(f, dict) else None)
        if scope:
            scopes.add(scope)
        amount = _parse_amount(value)
        if amount is None:
            continue
        is_flow = any(x in label for x in _FLOW_EXCLUSIONS)
        # statut + fidélité du fait (pour un bridge conscient du statut)
        _status = getattr(f, "status", None) or (f.get("status") if isinstance(f, dict) else None)
        _status = getattr(_status, "value", _status)            # FactStatus → str
        _fid = getattr(f, "fidelity", None) or (f.get("fidelity") if isinstance(f, dict) else None)
        _narr = (getattr(f, "fidelity_narrative_only", None)
                 if not isinstance(f, dict) else f.get("fidelity_narrative_only"))
        _fid_page = (getattr(f, "fidelity_page", None)
                     if not isinstance(f, dict) else f.get("fidelity_page"))
        rank = _SCOPE_RANK.get(scope or "", 0)
        for key, kws in _FIN_KEYWORDS.items():
            # un FLUX n'est jamais un solde de bilan cash/dette
            if is_flow and key in _NET_DEBT_KEYS:
                continue
            if any(kw in label for kw in kws) and rank >= best_rank.get(key, -1):
                if key not in out or rank > best_rank.get(key, -1):
                    out[key] = amount
                    best_rank[key] = rank
                    meta[key] = {"status": _status, "fidelity": _fid,
                                 "narrative_only": bool(_narr),
                                 "fidelity_page": _fid_page, "label": label}
    out["_scopes"] = sorted(scopes)
    out["_meta"] = meta
    return out


_VALUATION_USAGE = "non_board_safe"   # F.4.3 : une valorisation est TOUJOURS dérivée
_VALUATION_GOV_NOTE = (
    "Valorisation DÉRIVÉE (calcul à partir d'hypothèses) — INDICATIVE, jamais "
    "« board-safe » : à présenter en fourchette, avec hypothèses balisées ; ne "
    "remplace pas une due diligence."
)


def _inputs_fidelity(facts: Any) -> dict:
    """Conscience de la BRIQUE 1 (fidélité). Parmi les faits financiers porteurs
    d'une valeur, recense les niveaux de fidélité ligne-à-ligne déjà annotés.
    Renvoie {'levels', 'has_unconfirmed', 'available'}. P1-D4 : si AUCUN intrant
    financier ne porte d'annotation de fidélité, available=False (la valorisation
    doit le DIRE, et non laisser croire « rien à signaler »)."""
    levels: set = set()
    n_fin = 0
    narrative_only = 0
    for f in facts or []:
        label = (getattr(f, "label", None)
                 or (f.get("label") if isinstance(f, dict) else "") or "").lower()
        if not any(kw in label for kws in _FIN_KEYWORDS.values() for kw in kws):
            continue
        n_fin += 1
        fid = getattr(f, "fidelity", None) or (f.get("fidelity") if isinstance(f, dict) else None)
        if fid:
            levels.add(fid)
        no = (getattr(f, "fidelity_narrative_only", None)
              if not isinstance(f, dict) else f.get("fidelity_narrative_only"))
        if no:
            narrative_only += 1
    # « non retrouvée », « corpus indispo », ou « présent dans la synthèse mais
    # absent des documents d'entrée » = signaux de prudence.
    has_unconfirmed = ("not_found" in levels) or ("source_unavailable" in levels) or (narrative_only > 0)
    available = bool(levels)        # au moins un intrant annoté
    return {"levels": sorted(levels), "has_unconfirmed": has_unconfirmed,
            "available": available, "n_financial_inputs": n_fin,
            "narrative_only": narrative_only}


def _input_confirmed(meta_entry: dict | None) -> tuple[bool, str]:
    """Un intrant de dette nette est CONFIRMÉ seulement si : statut EXPLICITEMENT
    FAIT, fidélité verbatim/normalized, et pas de drapeau narrative_only. Un statut
    ABSENT n'est PAS une confirmation (audit F.6.4 : exiger status == FAIT)."""
    if not meta_entry:
        return False, "intrant non tracé (statut/fidélité inconnus)"
    status = (meta_entry.get("status") or "").upper()
    fid = meta_entry.get("fidelity")
    if meta_entry.get("narrative_only"):
        return False, "présent dans la synthèse mais absent des documents (hallucination possible)"
    if meta_entry.get("fidelity_page") == "not_found_on_cited_page":
        return False, "valeur absente de la page citée (citation erronée)"
    if status != "FAIT":
        return False, f"statut {meta_entry.get('status') or 'absent'} (FAIT requis)"
    if fid not in ("verbatim", "normalized"):
        return False, f"fidélité {fid or 'non vérifiée'}"
    return True, "FAIT + fidélité confirmée"


def _resolve_net_debt(fin: dict, assumptions: dict) -> dict:
    """Pont EV→Equity (audit F.6.1) : résout la DETTE NETTE depuis, par ordre de
    priorité, (1) une hypothèse explicite, (2) une dette nette du ledger, (3)
    dette brute − trésorerie du ledger. Sinon INCONNUE (pas de défaut à 0).
    Renvoie aussi `confirmed` (statut + fidélité des intrants) et `reason`."""
    meta = fin.get("_meta", {}) or {}
    if assumptions.get("net_debt") is not None:
        return {"value": float(assumptions["net_debt"]), "known": True,
                "basis": "hypothèse explicite", "confirmed": True,
                "reason": "fournie par l'utilisateur"}
    if fin.get("net_debt") is not None:
        ok, why = _input_confirmed(meta.get("net_debt"))
        return {"value": float(fin["net_debt"]), "known": True,
                "basis": "dette nette (ledger)", "confirmed": ok, "reason": why}
    if fin.get("gross_debt") is not None and fin.get("cash") is not None:
        ok_g, why_g = _input_confirmed(meta.get("gross_debt"))
        ok_c, why_c = _input_confirmed(meta.get("cash"))
        # Garde SÉMANTIQUE (audit F.6.6.1) : le per-page prouve qu'une valeur est
        # à la page citée, pas que le bon montant est sur le bon libellé. Si la
        # trésorerie et la dette brute portent le MÊME montant, c'est le symptôme
        # typique d'un montant mal associé (ex. « Trésorerie 74,7 / Dette 121,0 »
        # où 121,0 a été capté pour les deux) → dette nette À VÉRIFIER.
        same_amount = abs(float(fin["gross_debt"]) - float(fin["cash"])) < 1e-6
        ok = ok_g and ok_c and not same_amount
        if same_amount:
            why = ("trésorerie = dette brute (association libellé↔montant douteuse, "
                   "à vérifier : un même montant a pu être capté pour les deux)")
        else:
            why = "intrants confirmés" if ok else f"dette brute: {why_g} ; trésorerie: {why_c}"
        return {"value": float(fin["gross_debt"]) - float(fin["cash"]), "known": True,
                "basis": "dette brute − trésorerie (ledger)", "confirmed": ok,
                "reason": why, "semantic_warning": same_amount}
    return {"value": None, "known": False, "basis": None,
            "confirmed": False, "reason": "dette nette non disponible"}


def run_valuation_on_demand(*, brief: str, facts: Any = None,
                            assumptions: dict | None = None) -> dict | None:
    """Orchestrateur de valorisation déclenché par le brief.

    Retourne None si aucune intention de valorisation. Sinon, exécute les
    méthodes que les données disponibles permettent, en BALISANT chaque
    hypothèse et en REFUSANT la DCF sur FCF négatifs/absents.
    """
    if not detect_valuation_intent(brief):
        return None

    assumptions = dict(assumptions or {})
    fin = extract_financials_from_facts(facts or [])
    methods: list[dict] = []
    caveats: list[str] = [_VALUATION_GOV_NOTE]   # F.4.3 : gouvernance en tête

    # Brique 1 — fidélité des intrants : si une valeur financière n'a pas été
    # confirmée ligne-à-ligne dans la source, le signaler (sans bloquer).
    _fid = _inputs_fidelity(facts or [])
    if _fid["has_unconfirmed"]:
        caveats.append(
            "Certaines valeurs financières utilisées n'ont PAS été confirmées "
            "ligne-à-ligne (fidélité « non retrouvée » / corpus indisponible) — "
            "valorisation à recaler après vérification des intrants.")
    elif not _fid["available"]:
        # P1-D4 : ne pas laisser croire « rien à signaler » faute de contrôle.
        caveats.append(
            "Fidélité ligne-à-ligne NON DISPONIBLE sur les intrants financiers "
            "(brique 1 non exécutée ou faits non annotés) — l'absence de signal "
            "n'est PAS une validation des valeurs.")

    if "SOCIAL_STANDALONE" in fin.get("_scopes", []):
        caveats.append(
            "Chiffres disponibles = comptes SOCIAUX standalone (registre), non "
            "représentatifs d'un groupe consolidé. Valorisation INDICATIVE, à "
            "recaler sur les comptes consolidés [HYPOTHÈSE/à vérifier]."
        )

    # ── Pont EV→Equity (P0-D2) : résoudre la dette nette depuis le ledger ──
    nd = _resolve_net_debt(fin, assumptions)
    net_debt = nd["value"] if nd["known"] else None
    if not nd["known"]:
        caveats.append(
            "Pont EV→Equity INDISPONIBLE : dette nette absente du ledger "
            "(ni dette nette, ni dette brute + trésorerie). Seules des "
            "ENTERPRISE VALUES indicatives sont présentées — PAS d'equity value.")
    elif not nd.get("confirmed"):
        caveats.append(
            "Pont EV→Equity calculé sur des intrants NON CONFIRMÉS "
            f"({nd.get('reason')}) — l'equity en découlant est À VÉRIFIER, "
            "non un fait.")
    basis = "equity" if nd["known"] else "enterprise_value"

    # P1-D3 : multiples par défaut = SCÉNARIO TECHNIQUE, pas « sectoriel ».
    _user_mult = ("ev_ebitda_multiple" in assumptions or "ev_sales_multiple" in assumptions)
    ev_ebitda = assumptions.get("ev_ebitda_multiple", 8.0)
    ev_sales = assumptions.get("ev_sales_multiple", 2.0)
    shares = assumptions.get("shares_outstanding")
    _mult_tag = ("[hypothèse utilisateur]" if _user_mult else
                 "[SCÉNARIO TECHNIQUE par défaut — NON sectoriel, à remplacer par comparables sourcés]")

    # Multiples EV/EBITDA
    if fin.get("ebitda") is not None and fin["ebitda"] > 0:
        r = multiples_valuation(metric_value=fin["ebitda"], multiple=ev_ebitda,
                                metric="EBITDA", net_debt=net_debt, shares_outstanding=shares)
        r["assumption"] = f"multiple EV/EBITDA = {ev_ebitda}x {_mult_tag}"
        methods.append(r)
    elif fin.get("ebitda") is not None:
        caveats.append("EBITDA négatif → multiple EV/EBITDA non pertinent (écarté).")

    # Multiples EV/Sales
    if fin.get("revenue") is not None and fin["revenue"] > 0:
        r = multiples_valuation(metric_value=fin["revenue"], multiple=ev_sales,
                                metric="SALES", net_debt=net_debt, shares_outstanding=shares)
        r["assumption"] = f"multiple EV/Sales = {ev_sales}x {_mult_tag}"
        methods.append(r)

    # DCF (uniquement si projection FCF fournie ET pertinente)
    fcf = assumptions.get("fcf_projection")
    if fcf:
        try:
            r = dcf_valuation(DCFInputs(
                fcf_projection=fcf, wacc=assumptions.get("wacc", 0.10),
                terminal_growth=assumptions.get("terminal_growth", 0.02),
                net_debt=(net_debt or 0.0), shares_outstanding=shares))
            if not nd["known"]:
                r["equity_value"] = None       # pas de bridge → pas d'equity
                r["value_per_share"] = None     # ni de valeur par action (audit F.6.4)
            if not r.get("applicable", True):
                caveats.extend(r.get("warnings", []))
            methods.append(r)
        except ValueError as e:
            caveats.append(f"DCF non calculée : {e}")
    else:
        ni = fin.get("net_income")
        if ni is not None and ni < 0:
            caveats.append(
                "DCF NON APPLICABLE : société en perte / FCF non disponibles "
                "(cas pré-rentabilité / cash-burn). Privilégier multiples + ANR.")
        else:
            caveats.append("DCF non exécutée : projection de FCF à fournir par l'analyste.")

    # Référence patrimoniale (capitaux propres comptables) — base EQUITY native.
    if fin.get("equity") is not None:
        methods.append({
            "method": "Capitaux propres comptables (référence patrimoniale)",
            "equity_value": round(fin["equity"], 2),
            "enterprise_value": None, "applicable": True,
        })

    summary = valuation_summary(methods, basis=basis)

    # Table d'INTRANTS + pont (P0-D2 / D-3 : la chaîne de calcul compte autant
    # que le résultat). Valeurs None si non disponibles.
    inputs = {
        "revenue": fin.get("revenue"), "ebitda": fin.get("ebitda"),
        "net_income": fin.get("net_income"), "equity_book": fin.get("equity"),
        "cash": fin.get("cash"), "gross_debt": fin.get("gross_debt"),
        "net_debt": nd["value"], "net_debt_known": nd["known"],
        "net_debt_basis": nd["basis"],
        "net_debt_confirmed": nd.get("confirmed", False),
        "net_debt_reason": nd.get("reason"),
        "net_debt_semantic_warning": nd.get("semantic_warning", False),
        "ev_ebitda_multiple": ev_ebitda, "ev_sales_multiple": ev_sales,
        "multiples_source": ("utilisateur" if _user_mult else "scénario technique par défaut"),
    }

    return {
        "triggered": True,
        "board_safe": False,            # F.4.3 — une valorisation n'est JAMAIS board-safe
        "usage_level": _VALUATION_USAGE,
        "derived": True,
        "governance_note": _VALUATION_GOV_NOTE,
        "inputs_fidelity": _fid,
        "valuation_basis": basis,       # 'equity' (bridge ok) ou 'enterprise_value'
        "net_debt_known": nd["known"],
        "inputs": inputs,
        "financials_used": {k: v for k, v in fin.items() if k not in ("_scopes", "_meta")},
        "scopes": fin.get("_scopes", []),
        "methods": methods,
        "summary": summary,
        "assumptions": {"ev_ebitda_multiple": ev_ebitda, "ev_sales_multiple": ev_sales,
                        "net_debt": nd["value"], "net_debt_known": nd["known"],
                        "fcf_projection_provided": bool(fcf)},
        "caveats": caveats,
        "markdown": _valuation_markdown(methods, summary, caveats, inputs),
    }


def _valuation_markdown(methods: list[dict], summary: dict, caveats: list[str],
                        inputs: dict | None = None) -> str:
    basis = summary.get("basis", "equity")
    label = "equity value" if basis == "equity" else "Enterprise Value (EV) — pont vers equity indisponible"
    lines = ["## Valorisation indicative (multi-méthodes)", ""]
    if summary.get("methods_used"):
        lines.append(f"**Fourchette {label}** : {summary['low']} – {summary['high']} "
                     f"(médiane {summary['mid']}) sur {summary['methods_used']} méthode(s).")
    else:
        lines.append("**Valorisation non concluante** : données insuffisantes pour une méthode exploitable.")
    lines.append("")
    if inputs:
        nd = ("inconnue" if not inputs.get("net_debt_known")
              else f"{inputs.get('net_debt')} ({inputs.get('net_debt_basis')})")
        lines += ["**Intrants utilisés :** "
                  f"CA={inputs.get('revenue')} · EBITDA={inputs.get('ebitda')} · "
                  f"RN={inputs.get('net_income')} · trésorerie={inputs.get('cash')} · "
                  f"dette brute={inputs.get('gross_debt')} · dette nette={nd}", ""]
    for m in methods:
        # affiche equity si dispo, sinon EV (pont indisponible)
        eq = m.get("equity_value")
        val = (f"equity ≈ {eq}" if eq is not None
               else f"EV ≈ {m.get('enterprise_value')} (pas d'equity : pont indisponible)")
        tag = "" if m.get("applicable", True) else "  _(écartée : non applicable)_"
        assu = f" — {m['assumption']}" if m.get("assumption") else ""
        lines.append(f"- **{m['method']}** : {val}{assu}{tag}")
    if caveats:
        lines += ["", "**Réserves & hypothèses :**"]
        lines += [f"- {c}" for c in caveats]
    lines += ["", "_Valorisation produite par le module déterministe CoDIR-IA. "
              "Toute hypothèse est balisée ; ne remplace pas une due diligence._"]
    return "\n".join(lines)
