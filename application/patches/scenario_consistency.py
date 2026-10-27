"""patches/scenario_consistency.py — P0-3 (M.5.3) — Scenario Consistency Gate.

Cas dossier de conseil (débrief M.4) : le CR recommandait une **mise en sommeil** de la
société tout en poussant, en axe stratégique, un **marketing actif** (LinkedIn,
prospection, cabinets de placement). Ces deux orientations sont logiquement
incompatibles : on ne relance pas commercialement une structure qu'on met en
sommeil. Le moteur produisait les deux sans les confronter.

Doctrine (cf. débrief §3) : le gate ne « corrige » pas en inventant une décision.
Il DÉTECTE la contradiction et la fait remonter (flag/lucidité), pour que la
synthèse l'arbitre explicitement plutôt que de livrer un plan auto-contradictoire.
"""
from __future__ import annotations

import re
from typing import Optional

# Décision/scénario de type RETRAIT (sommeil, cessation, sortie, liquidation).
_WINDDOWN_RE = re.compile(
    r"\b(?:mise\s+en\s+sommeil|mises?\s+en\s+sommeil|sommeil|cessation\s+d['’]activit|"
    r"cesser\s+l['’]activit|arr[êe]t\s+de\s+l['’]activit|liquidation|dissolution|"
    r"radiation|fermeture\s+de\s+la\s+soci[ée]t|"
    r"wind[\s\-]?down|winding[\s\-]?up|dormancy|put\s+(?:the\s+)?company\s+dormant|"
    r"cease\s+(?:trading|operations|activity)|exit\s+the\s+business)\b",
    re.IGNORECASE,
)

# Axes de CROISSANCE ACTIVE / développement commercial incompatibles avec un retrait.
_ACTIVE_GROWTH_RE = re.compile(
    r"\b(?:marketing\s+actif|campagne\s+marketing|prospection|d[ée]veloppement\s+commercial|"
    r"business\s+development|go[\s\-]?to[\s\-]?market|relance\s+commerciale|acquisition\s+(?:de\s+)?clients?|"
    r"strat[ée]gie\s+de\s+croissance|plan\s+de\s+croissance|recrut(?:er|ement)|embauche|"
    r"campagne\s+linkedin|pr[ée]sence\s+linkedin|publication[s]?\s+linkedin|"
    r"cabinets?\s+de\s+placement|nouveaux?\s+march[ée]s?|expansion|scale\s+up|scaling|"
    r"active\s+marketing|sales\s+development|lead\s+generation|hiring\b|grow\s+the\s+business)\b",
    re.IGNORECASE,
)

# LinkedIn seul (souvent cité comme canal de relance) — signal d'appoint.
_LINKEDIN_RE = re.compile(r"\blinkedin\b", re.IGNORECASE)

# ── M.5.10.10 — détection SÉMANTIQUE du retrait (audit dossier anglophone coté P0-3) ──────────
# Le faux positif dossier anglophone coté venait d'une lecture trop lexicale : « exit » de
# catégories/marchés à faible marge était lu comme un « wind-down » de la société.
# Doctrine : on ne déclenche le retrait que si la fermeture vise la SOCIÉTÉ
# (company/entity/business/activity/operations/legal entity/dormancy/liquidation/
# cessation), JAMAIS si « exit/cease/cut » vise une sous-partie (SKU, catégorie,
# gamme, marché, géographie, canal, APAC footprint, non-core) = élagage de
# portefeuille, pas un sommeil.
# M6-A0 — idem pour « liquidation/dissolution » : liquidation de STOCK/inventory
# = opérationnel (turnaround), JAMAIS un wind-down de société.

# Termes INTRINSÈQUEMENT au niveau entreprise → comptent toujours.
_WINDDOWN_INTRINSIC_RE = re.compile(
    r"\b(?:mise\s+en\s+sommeil|mises?\s+en\s+sommeil|mettre\s+en\s+sommeil|"
    # B.1.3.20 (P1-F-bis, 11e lecture morte) — les radicaux tronqués « activit »
    # étaient tués par le \b final (t→é = mot→mot, pas de frontière) : branches
    # mortes depuis leur introduction. Radicaux complétés, \b final préservé.
    r"cessation\s+d['’]activit[ée]s?|cesser\s+l['’]activit[ée]s?|"
    r"arr[êe]t\s+(?:total\s+)?de\s+l['’]activit[ée]s?|"
    r"liquidation\s+judiciaire|mise\s+en\s+liquidation|"
    r"dissolution\s+de\s+l['’]?(?:a\s+)?(?:soci[ée]t|entreprise)|"
    r"radiation\s+(?:du\s+)?(?:rcs|registre)|fermeture\s+de\s+la\s+soci[ée]t|"
    r"wind[\s\-]?down\s+(?:the\s+)?(?:company|business|firm|entity|group)|"
    r"winding[\s\-]?up|dormancy|put\s+(?:the\s+)?company\s+dormant|go\s+dormant|"
    r"cease\s+trading|exit\s+the\s+business|"
    r"cessation\s+of\s+(?:the\s+)?(?:company|business)\s+activit(?:y|ies))\b",
    re.IGNORECASE,
)

# Verbes de fermeture AMBIGUS (peuvent viser une sous-partie).
_WINDDOWN_SCOPED_RE = re.compile(
    r"\b(?:exit|cease|discontinue|withdraw\s+from|pull\s+out\s+of|wind\s*down|"
    r"liquidation|dissolution|radiation|"
    r"sortie\s+d|se\s+retirer\s+d|retrait\s+d)\b",
    re.IGNORECASE,
)

# Sujet ENTREPRISE (l'objet fermé est la société elle-même).
_COMPANY_SCOPE_RE = re.compile(
    r"\b(?:the\s+(?:whole\s+|entire\s+)?company|the\s+(?:whole\s+|entire\s+)?business|"
    r"the\s+firm|the\s+group|the\s+(?:legal\s+)?entity|legal\s+entity|operations\s+entirely|"
    r"la\s+soci[ée]t[ée]|l['’]entreprise|la\s+structure|le\s+groupe|"
    r"l['’]activit[ée]\s+(?:globale|enti[èe]re|de\s+la\s+soci[ée]t))\b",
    re.IGNORECASE,
)

# Objet PARTIEL (sous-partie fermée → PAS un wind-down).
_PARTIAL_SCOPE_RE = re.compile(
    r"\b(?:sku|skus|cat[ée]gor|product\s+lines?|gammes?|low[\s\-]?margin|"
    r"march[ée]s?|markets?|geograph|g[ée]ographi|channel|canal|canaux|"
    r"footprint|apac|emea|region|r[ée]gion|non[\s\-]?core|segment|"
    r"store|outlet|magasin|boutique|brand\s+lines?|portfolio|portefeuille|"
    r"m[ée]tiers?|p[ôo]les?|divisions?|branches?|activit[ée]s?\s+secondaires?|"
    r"business\s+units?|\bbu\b|filiales?|"
    r"perimeter|p[ée]rim[èe]tre|wholesale|dtc|"
    r"stocks?|inventor(?:y|ies)|assortment|assortiment|markdown|d[ée]stock(?:age|ing)?)\b",
    re.IGNORECASE,
)


def _winddown_match(text: str):
    """Renvoie un match de RETRAIT *au niveau entreprise*, sinon None (M.5.10.10).

    1) Un terme intrinsèquement entreprise (mise en sommeil, dormancy,
       cessation d'activité, exit the business, liquidation JUDICIAIRE /
       dissolution DE LA SOCIÉTÉ…) compte toujours. M6-A0 : « liquidation »
       /« dissolution » nus ne sont PLUS intrinsèques (liquidation de STOCK).
    2) Un verbe ambigu (exit / cease / discontinue / wind down / retrait) ne
       compte QUE si un sujet entreprise est proche ET qu'aucun objet partiel
       (SKU/catégorie/marché/APAC footprint/non-core…) n'est dans la fenêtre.
    """
    if not text:
        return None
    # B.1.3.20 (P1-F, run dossier industriel) — les termes INTRINSÈQUES passent désormais
    # par la MÊME fenêtre de scope partiel que les verbes ambigus. Racine
    # reproduite offline : « cession ou mise en sommeil d'un MÉTIER (espaces
    # verts) » — option de portefeuille — tirait intrinsèquement et devenait
    # « décision = retrait » niveau société (slide MAINTIEN RELATIONNEL
    # MINIMAL). Règle : intrinsèque + objet PARTIEL dans la fenêtre, sans
    # sujet entreprise → élagage de portefeuille, PAS un sommeil société.
    for m in _WINDDOWN_INTRINSIC_RE.finditer(text):
        win = text[max(0, m.start() - 70):m.end() + 70]
        if _PARTIAL_SCOPE_RE.search(win) and not _COMPANY_SCOPE_RE.search(win):
            continue
        return m
    for m in _WINDDOWN_SCOPED_RE.finditer(text):
        win = text[max(0, m.start() - 70):m.end() + 70]
        if _PARTIAL_SCOPE_RE.search(win):
            continue  # exit/cut d'une sous-partie → élagage, pas un sommeil
        if _COMPANY_SCOPE_RE.search(win):
            return m
    return None
# ──────────────────────────────────────────────────────────────────────────────


def _note(lang: str, winddown_hit: str, growth_hits: list[str]) -> str:
    g = ", ".join(sorted(set(h.lower() for h in growth_hits))[:4])
    if lang == "en":
        return (
            "Scenario consistency flag (P0-3): the recommended scenario points to a "
            "WIND-DOWN / dormancy / exit, yet the plan also pushes ACTIVE-GROWTH axes "
            f"({g}). These are mutually exclusive. To arbitrate: either confirm the "
            "wind-down and DROP the growth/marketing axes, or keep the business active "
            "and the decision is NOT a wind-down. Do not deliver both as-is."
        )
    return (
        "Incohérence de scénario (P0-3) : la décision recommandée relève d'un RETRAIT "
        "(mise en sommeil / cessation / sortie), alors que le plan pousse des axes de "
        f"CROISSANCE ACTIVE ({g}). C'est logiquement incompatible. À arbitrer "
        "explicitement : soit on acte le sommeil et on RETIRE les axes "
        "marketing/développement, soit on maintient l'activité et la décision n'est "
        "pas un sommeil. Ne pas livrer les deux en l'état."
    )


def check_scenario_consistency(decision_text: str = "",
                               plan_text: str = "",
                               lang: str = "fr") -> Optional[str]:
    """Renvoie une note d'incohérence si la décision (retrait) contredit le plan
    (croissance active), sinon None. `decision_text` = décision réconciliée +
    éventuel résumé ; `plan_text` = axes stratégiques / synthèse / actions.

    Le retrait est cherché en priorité dans la DÉCISION ; la croissance active
    dans le PLAN. On tolère que les deux soient concaténés (fallback) : un retrait
    et une croissance active dans le même corpus suffisent à lever le flag.
    """
    decision_text = decision_text or ""
    plan_text = plan_text or ""
    full = decision_text + "\n" + plan_text

    winddown = _winddown_match(decision_text) or _winddown_match(full)
    if not winddown:
        return None

    growth_hits = [m.group(0) for m in _ACTIVE_GROWTH_RE.finditer(plan_text or full)]
    # LinkedIn seul compte comme signal de relance commerciale s'il y a aussi un
    # autre indice, ou s'il est explicitement présenté comme canal d'acquisition.
    if not growth_hits and _LINKEDIN_RE.search(plan_text or full):
        growth_hits = ["linkedin"]
    if not growth_hits:
        return None

    return _note(lang, winddown.group(0), growth_hits)


def attach_scenario_flag(b23_guards, decision_text: str = "",
                         plan_text: str = "", lang: str = "fr") -> Optional[str]:
    """M.5.4 — calcule le flag d'incohérence scénario et, s'il existe, l'ajoute à
    la liste ``flags`` des gardes pipeline (rendue dans le CR, section alertes).
    Idempotent. Renvoie la note (ou None) pour le log / les diagnostics."""
    note = check_scenario_consistency(decision_text, plan_text, lang)
    if note and isinstance(b23_guards, dict):
        b23_guards.setdefault("flags", [])
        flags = b23_guards.get("flags")
        if isinstance(flags, list) and note not in flags:
            flags.append(note)
    return note


def is_winddown_recommended(*texts: str) -> bool:
    """FIX4 (M.5.8) — un scénario de RETRAIT (sommeil / cessation / sortie) est-il
    présent dans l'un des textes fournis (décision, plan, actions) ?"""
    blob = " ".join(t or "" for t in texts)
    return _winddown_match(blob) is not None


def reframe_winddown_decision(label: str, lang: str = "fr") -> str:
    """FIX4 (M.5.8) — sous une décision de RETRAIT, « GO » / « GO CONDITIONNEL »
    est un vocabulaire trompeur (contradictoire avec un sommeil/sortie). On
    reformule en recommandation à ARBITRER sous validation du conseil. Ne touche
    jamais un « NO-GO » ni un libellé déjà neutre (À ARBITRER, CADRAGE, ALERTES)."""
    if not label:
        return label
    up = label.upper()
    if "NO-GO" in up or "ARBITR" in up or "CADRAGE" in up or "ALERTE" in up:
        return label
    if "GO" in up or "CONDITIONNEL" in up:
        return ("À ARBITRER — retrait recommandé (mise en sommeil / sortie) sous "
                "validation du conseil (fiscal/comptable)" if lang != "en" else
                "TO ARBITRATE — wind-down recommended (dormancy / exit), subject to "
                "advisory (tax/accounting) validation")
    return label


def quarantine_incompatible_actions(reg, decision_text: str = "",
                                    plan_text: str = "", lang: str = "fr") -> int:
    """P0-3 (M.5.7) — quand un scénario de RETRAIT (sommeil / cessation / sortie)
    est recommandé, marque les actions de CROISSANCE ACTIVE du registre comme
    INCOMPATIBLES → le rendu les sort du PLAN PRINCIPAL vers un bloc « axes
    conditionnels (à arbitrer) ». Ne supprime jamais une action (lucidité).
    Renvoie le nombre d'actions reclassées.

    M.5.7 — robustesse (retex audit) : le retrait est détecté dans la DÉCISION
    réconciliée OU dans le PLAN OU dans les ACTIONS du registre elles-mêmes. Ainsi
    la quarantaine se déclenche même si la décision réconciliée reste « GO
    CONDITIONNEL » alors que le plan recommande la mise en sommeil. L'action de
    retrait elle-même (« préparer la mise en sommeil ») n'est jamais reclassée.
    """
    if reg is None:
        return 0
    items = getattr(reg, "items", None) or []
    _action_blob = " ".join(
        (getattr(a, "action", "") or "") + " " + (getattr(a, "sujet", "") or "")
        for a in items)
    _winddown_corpus = " ".join([decision_text or "", plan_text or "", _action_blob])
    if not _WINDDOWN_RE.search(_winddown_corpus):
        return 0
    n = 0
    for a in items:
        blob = (getattr(a, "action", "") or "") + " " + (getattr(a, "sujet", "") or "")
        if _WINDDOWN_RE.search(blob):
            continue   # l'action de RETRAIT elle-même reste au plan principal
        if _ACTIVE_GROWTH_RE.search(blob) or _LINKEDIN_RE.search(blob):
            if not getattr(a, "incompatible_with_decision", False):
                a.incompatible_with_decision = True
                n += 1
    return n
