"""v62.13.9.4.48 — RAPPROCHEMENT ARITHMÉTIQUE DÉTERMINISTE (programme 9.4.48, point 2).

Après extraction et contrat de fait, les identités comptables élémentaires sont vérifiées entre
faits CONFIRMÉS d'une même période, d'un même périmètre et d'une même devise :

    R1  chiffre d'affaires − coût des ventes = marge brute
    R2  marge brute − charges d'exploitation = résultat d'exploitation
        (appliquée seulement quand la table porte un total des charges d'exploitation)

Verdict, sans modèle :
- écart ≤ 0,1 % : le résultat porte la note « rapproché » ;
- écart ≤ 1 %   : note « rapproché à l'arrondi près » ;
- écart > 1 %   : le fait DISCORDANT — le résultat de l'identité, celui qui ne vaut pas le calcul —
  passe « à vérifier » et cesse de confirmer quoi que ce soit (statut de preuve non confirmant) ;
  ses deux opérandes portent une note qui nomme l'écart. Le calcul n'est jamais substitué à la
  valeur publiée : l'humain tranche.

Le signe littéral (arbitrage du 25/09) est respecté : un coût publié entre parenthèses est négatif ;
l'identité s'écrit donc avec sa valeur absolue.
"""
from __future__ import annotations

import re
from typing import Any

_CONFIRMED = {"CONFIRMED_ON_PAGE", "DERIVED_FROM_CONFIRMED_ON_PAGE", "CONFIRMED_IN_REGISTRY"}
_ROLE_BY_ID = {
    "REVENUE": "REVENUE",
    "COST_OF_SALES": "COST_OF_SALES",
    "GROSS_PROFIT": "GROSS_PROFIT", "GROSS_MARGIN": "GROSS_PROFIT",
    "OPERATING_EXPENSES": "OPEX", "TOTAL_OPERATING_EXPENSES": "OPEX", "OPEX": "OPEX",
    "OPERATING_PROFIT": "OPERATING_PROFIT",
}
_ROLE_BY_LABEL = (
    (re.compile(r"^\s*(?:revenue|net\s+sales|turnover|total\s+(?:net\s+)?sales|chiffre\s+d['’]affaires)", re.I), "REVENUE"),
    (re.compile(r"cost\s+of\s+(?:sales|goods\s+sold|products\s+sold|revenues?)|co[uû]t\s+des\s+ventes|"
                r"co[uû]t\s+d['’]achat\s+des\s+marchandises\s+vendues", re.I), "COST_OF_SALES"),
    (re.compile(r"gross\s+(?:profit|margin)|marge\s+brute", re.I), "GROSS_PROFIT"),
    (re.compile(r"total\s+operating\s+expenses|charges\s+d['’]exploitation|operating\s+expenses", re.I), "OPEX"),
    (re.compile(r"^(?!.*adjusted)(?:.*\b)?(?:operating\s+(?:profit|income)|income\s+from\s+operations|"
                r"r[ée]sultat\s+d['’]exploitation)", re.I), "OPERATING_PROFIT"),
)
_IDENTITIES = (
    ("R1", "REVENUE", "COST_OF_SALES", "GROSS_PROFIT",
     "chiffre d'affaires − coût des ventes = marge brute", "revenue − cost of sales = gross profit"),
    ("R2", "GROSS_PROFIT", "OPEX", "OPERATING_PROFIT",
     "marge brute − charges d'exploitation = résultat d'exploitation",
     "gross profit − operating expenses = operating profit"),
)


def _get(f: Any, k: str, default=None):
    return f.get(k, default) if isinstance(f, dict) else getattr(f, k, default)


def _set(f: Any, k: str, v) -> None:
    if isinstance(f, dict):
        f[k] = v
    else:
        setattr(f, k, v)


def _role(f: Any) -> str | None:
    mid = str(_get(f, "metric_canonical_id", "") or "").upper()
    if str(_get(f, "unit", "") or "").upper() in ("PCT", "%", "RATIO"):
        return None                                      # un taux n'entre pas dans une identité en montants
    if mid in _ROLE_BY_ID:
        return _ROLE_BY_ID[mid]
    label = str(_get(f, "label", "") or "")
    if "%" in str(_get(f, "value", "") or ""):
        return None
    for rx, role in _ROLE_BY_LABEL:
        if rx.search(label):
            return role
    return None


def _confirmed(f: Any) -> bool:
    st = str(getattr(_get(f, "status", ""), "value", _get(f, "status", "")) or "").upper()
    ps = str(_get(f, "proof_status", "") or "").upper()
    return ps in _CONFIRMED and "VERIF" not in st.replace("É", "E") and _get(f, "normalized_value") is not None


def _key(f: Any) -> tuple:
    period = re.sub(r"[^0-9A-Z]", "", str(_get(f, "period", "") or "").upper())
    scope = str(_get(f, "perimeter_entity", "") or _get(f, "scope", "") or "").strip().lower()
    cur = str(_get(f, "currency", "") or "").upper()
    return (period, scope, cur)


def _note(f: Any, text: str) -> None:
    notes = _get(f, "notes", None)
    if isinstance(notes, list):
        if text not in notes:
            notes.append(text)
    else:
        _set(f, "notes", [text])


def reconcile_facts48(facts: list, lang: str = "fr", tolerance: float = 0.01) -> dict:
    """Applique R1 et R2 sur les faits confirmés ; modifie en place ; renvoie le diagnostic."""
    en = str(lang or "fr").lower().startswith("en")
    groups: dict[tuple, dict[str, Any]] = {}
    for f in facts or []:
        r = _role(f)
        if r and _confirmed(f) and _key(f)[0]:
            groups.setdefault(_key(f), {}).setdefault(r, f)       # le premier fait confirmé du rôle
    diag = {"checked": 0, "reconciled": [], "rounding": [], "discordant": []}
    for key, g in groups.items():
        for code, a, b, c, txt_fr, txt_en in _IDENTITIES:
            if not all(x in g for x in (a, b, c)):
                continue
            va, vb, vc = (float(_get(g[x], "normalized_value")) for x in (a, b, c))
            expected = abs(va) - abs(vb)
            gap = abs(expected - vc) / max(abs(vc), abs(expected), 1e-9)
            diag["checked"] += 1
            entry = {"identity": code, "period": key[0], "scope": key[1], "currency": key[2],
                     "expected": expected, "published": vc, "gap_pct": round(gap * 100, 3)}
            what = txt_en if en else txt_fr
            if gap <= 0.001:
                _note(g[c], (f"Reconciled: {what}" if en else f"Rapproché : {what}"))
                diag["reconciled"].append(entry)
            elif gap <= tolerance:
                _note(g[c], (f"Reconciled within rounding ({entry['gap_pct']} %): {what}" if en
                             else f"Rapproché à l'arrondi près ({entry['gap_pct']} %) : {what}"))
                diag["rounding"].append(entry)
            else:
                try:
                    from utils.financial_facts_table import FactStatus as _FS
                    _set(g[c], "status", _FS.A_VERIFIER)
                except Exception:
                    _set(g[c], "status", "À VÉRIFIER")
                _set(g[c], "proof_status", "ARITHMETIC_CHECK_FAILED")
                msg = (f"To verify: {what} does not hold (gap {entry['gap_pct']} %)" if en
                       else f"À vérifier : {what} ne se vérifie pas (écart {entry['gap_pct']} %)")
                _note(g[c], msg)
                for x in (a, b):
                    _note(g[x], msg)
                diag["discordant"].append(entry)
    return diag
