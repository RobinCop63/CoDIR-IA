"""
patches/pipeline_guards_b23.py — v17.1-B2.3-A

Gardes déterministes B2.3 (aucun hardcoding de fait/entité, aucune modification
de prompt). Elles SÉCURISENT la présentation et SIGNALENT les incohérences ;
elles ne fabriquent pas de faits. Toutes fail-open.

1. cotation_gate          — pas de « coté »/« non coté » sans source forte.
2. metric_coherence_gate  — pas de confusion EBITDA / résultat net / cash burn.
3. decision_reconciler    — une seule décision finale + divergence affichée.
4. roadmap_guard          — pas de jalon « futur » daté dans le passé du run.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Sources fortes (réutilise la doctrine du shaper, sans dépendance dure).
_STRONG_SRC = ("rfa", "urd", "universal-registration", "registration-document",
               "document d'enregistrement", "document d’enregistrement",
               "annual report", "rapport annuel", "fy-2025", "fy results",
               "press release", "communiqué", "communique", "-pr-", "isin",
               "euronext", "boursorama", "zonebourse", "bloomberg", "amf")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Cotation gate
# ─────────────────────────────────────────────────────────────────────────────
_COTATION_RE = re.compile(r"\bnon[\s\-]?cot[ée]e?s?\b|\bcot[ée]e?s?\b", re.IGNORECASE)
_ISIN_RE = re.compile(r"\b[A-Z]{2}[0-9A-Z]{9}[0-9]\b")


def _sentence_has_strong_cotation_source(sentence: str) -> bool:
    low = sentence.lower()
    if _ISIN_RE.search(sentence):
        return True
    return any(s in low for s in _STRONG_SRC)


def cotation_gate(text: str) -> Tuple[str, List[str]]:
    """Remplace toute assertion « coté / non coté » NON adossée à une source
    forte (ISIN, Euronext, RFA/URD, AMF…) par « statut boursier à vérifier
    (non sourcé) ». Renvoie (texte_corrigé, flags)."""
    if not text:
        return text, []
    flags: List[str] = []
    out_lines = []
    for line in text.splitlines():
        # On segmente par phrase pour juger la source au plus près.
        segs = re.split(r"(?<=[\.!?\|])\s+", line)
        new_segs = []
        for seg in segs:
            if _COTATION_RE.search(seg) and not _sentence_has_strong_cotation_source(seg):
                corrected = _COTATION_RE.sub("statut boursier à vérifier (non sourcé)", seg)
                flags.append("Statut boursier asserté sans source forte → neutralisé.")
                new_segs.append(corrected)
            else:
                new_segs.append(seg)
        out_lines.append(" ".join(new_segs))
    return "\n".join(out_lines), flags


# ─────────────────────────────────────────────────────────────────────────────
# 2. Metric coherence gate
# ─────────────────────────────────────────────────────────────────────────────
_METRIC_KEYS = {
    "ebitda": "EBITDA",
    "résultat net": "Résultat net", "resultat net": "Résultat net",
    "perte nette": "Résultat net",
    "cash burn": "Cash burn", "cash-burn": "Cash burn",
    "trésorerie": "Trésorerie", "tresorerie": "Trésorerie",
    "operating cash flow": "Operating cash flow", "flux de trésorerie": "Operating cash flow",
    "chiffre d'affaires": "Chiffre d'affaires", "chiffre d’affaires": "Chiffre d'affaires",
}
_AMT = re.compile(r"[-−]?\s*\d[\d\s\u202f.,]*\s*(?:Md|Mrd|bn|M|m|K|k)?\s*[€$£]")


def _norm_amount(a: str) -> str:
    return re.sub(r"\s+", "", a.lower().replace("−", "-").replace("\u202f", ""))


def metric_coherence_gate(text: str) -> List[str]:
    """Détecte la confusion métrique : un même MONTANT associé à des MÉTRIQUES
    canoniques différentes (ex. « -51 M€ » étiqueté EBITDA ici, résultat net là).
    v17.1-B2.3.4 — chaque montant est rattaché à la métrique la PLUS PROCHE
    (distance en caractères), pas à tous les mots-clés de la phrase. Cela évite
    les faux positifs du type « RN -51 M€ (vs -29 M€), EBITDA -22 M€ » où trois
    métriques distinctes coexistent légitimement dans une phrase. Ne réécrit
    rien (la cause est l'agent) : signale au consultant."""
    if not text:
        return []
    # v17.1-B2.3-C — IGNORER les lignes de tableau markdown : dans un comparatif,
    # chaque ligne porte son libellé métrique (col 0), donc la proximité montant↔
    # mots-clés y est structurelle, pas une confusion. La confusion réelle est en
    # PROSE. (Évite les faux positifs « 0 € EBITDA/RN », « 75 M€ cash burn/RN »
    # réveillés par la détection insensible à l'ordre.)
    text = "\n".join(ln for ln in text.split("\n")
                     if not ln.lstrip().startswith(("|", "⚠", ">")))
    if not text.strip():
        return []
    # Métriques P&L réellement non interchangeables (on EXCLUT trésorerie / cash /
    # CA des paires de confusion : un même montant peut légitimement n'être qu'un
    # solde de trésorerie, et CA n'est pas confondable avec EBITDA/RN par erreur
    # de signe). On ne garde que le triangle EBITDA / Résultat net / Cash burn /
    # Operating cash flow.
    _PNL = {"EBITDA", "Résultat net", "Cash burn", "Operating cash flow"}
    _MAX_DIST = 60  # un montant au-delà de 60 car. d'un mot-clé n'est pas rattaché

    # v17.1-B2.3-C — on tracke TOUS les mots-clés métriques pour l'attribution
    # (sinon « trésorerie 75 M€ » voyait « 75 » capté par « cash burn » P&L
    # précédent, faux positif). Le filtrage P&L se fait À LA FIN via _incompat :
    # un montant rattaché à Trésorerie / CA ne déclenchera aucune paire.
    kw_hits: List[tuple] = []  # (pos, canon)
    low = text.lower()
    for kw, canon in _METRIC_KEYS.items():
        start = 0
        while True:
            i = low.find(kw, start)
            if i < 0:
                break
            kw_hits.append((i, canon))
            start = i + len(kw)
    if not kw_hits:
        return []

    amount_to_metrics: Dict[str, set] = {}
    for m in _AMT.finditer(text):
        key = _norm_amount(m.group(0))
        if not re.search(r"\d", key):
            continue
        pos = m.start()
        # v17.1-B2.3-C — le LIBELLÉ précède typiquement la valeur (« EBITDA ajusté
        # -51 M€ »). On rattache donc au mot-clé le plus proche QUI PRÉCÈDE le
        # montant ; à défaut (aucun avant dans la limite), au plus proche absolu.
        # Corrige l'edge case « EBITDA ajusté -51 M€. Résultat net -51 M€. » où
        # « ajusté » éloignait EBITDA et le RN suivant captait le montant.
        nearest, best = None, _MAX_DIST + 1
        for (kpos, canon) in kw_hits:
            if kpos <= pos and (pos - kpos) < best:
                best, nearest = pos - kpos, canon
        if nearest is None:
            for (kpos, canon) in kw_hits:
                d = abs(kpos - pos)
                if d < best:
                    best, nearest = d, canon
        if nearest is not None and best <= _MAX_DIST:
            amount_to_metrics.setdefault(key, set()).add(nearest)

    flags: List[str] = []
    # v17.1-B2.3-C — paires insensibles à l'ordre. Avant, les tuples étaient
    # comparés après tri alphabétique (a < b) alors qu'ils n'étaient pas eux-mêmes
    # triés → EBITDA↔Cash burn, Résultat net↔Cash burn, Résultat net↔Operating CF
    # n'étaient JAMAIS flaggées. frozenset corrige.
    _incompat = {
        frozenset(("EBITDA", "Résultat net")), frozenset(("EBITDA", "Cash burn")),
        frozenset(("Résultat net", "Cash burn")), frozenset(("EBITDA", "Operating cash flow")),
        frozenset(("Résultat net", "Operating cash flow")),
    }
    for amt, mets in amount_to_metrics.items():
        for a in mets:
            for b in mets:
                if a < b and frozenset((a, b)) in _incompat:
                    flags.append(
                        f"Confusion métrique probable : le montant « {amt} » est "
                        f"rattaché à la fois à {a} et {b} dans des contextes proches "
                        f"— à arbitrer (métriques non interchangeables).")
    return sorted(set(flags))


# ─────────────────────────────────────────────────────────────────────────────
# 3. Decision reconciler
# ─────────────────────────────────────────────────────────────────────────────
_SEVERITY = {"NO-GO": 3, "GO CONDITIONNEL": 2, "GO": 1, "INDÉTERMINÉ": 0}


# ── P0-5 temps 2 (M.5.3) — Localisation EN du verdict (AFFICHAGE uniquement) ──
# Les tokens de décision restent FR dans la logique (clés _SEVERITY, comparaisons
# d'ensembles). On ne traduit qu'à l'affichage (ex. injection dans le registre EN).
_VERDICT_REPL_EN = [
    ("GO CONDITIONNEL", "CONDITIONAL GO"),
    ("INDÉTERMINÉ", "UNDETERMINED"),
    ("CADRAGE / PLAN D'ACTION", "FRAMING / ACTION PLAN"),
    ("point non décisionnel", "non-decision item"),
    ("pas de GO/NO-GO d'acquisition", "no acquisition GO/NO-GO"),
    ("engagement capitalistique immédiat", "immediate capital commitment"),
    ("engagement capitalistique", "capital commitment"),
    ("GO conditionnel due diligence", "conditional GO for due diligence"),
    ("DIVERGENCE entre agents", "DIVERGENCE between agents"),
    ("décision finale prudente", "prudent final decision"),
    ("Décision finale", "Final decision"),
]


def localize_verdict(text: str, lang: str = "fr") -> str:
    """Traduit un verdict/décision FR pour l'AFFICHAGE en EN (no-op en FR)."""
    if lang != "en" or not text:
        return text
    out = text
    for fr, en in _VERDICT_REPL_EN:
        out = out.replace(fr, en)
    return out


# ── M.5.10.6 — notes B2.3 bilingues (source unique). `localize_verdict` ne
# traduisait que le champ `final` (fragments) ; le paragraphe `note` fuyait en
# français dans un run EN (audit ChatGPT). On produit `note_en` à la SOURCE
# (decision_reconciler) pour chaque branche → le consommateur sélectionne par
# langue. Pas de mapping de paragraphe fragile.
_CLASS_EN = {
    "NO-GO": "NO-GO", "GO": "GO", "GO CONDITIONNEL": "CONDITIONAL GO",
    "INDÉTERMINÉ": "UNDETERMINED",
}


def _loc_class_en(cls: str) -> str:
    return _CLASS_EN.get(cls, cls)


def _note_options_plan_en() -> str:
    return ("Non-decision agenda item (market study / business development): no "
            "acquisition GO/NO-GO. Agent positions are ORIENTATIONS, not commitment "
            "verdicts. Distinguish a possible \u201cNO-GO\u201d for external presentation "
            "as-is from a \u201cGO\u201d on the internal action plan. Expected deliverable: "
            "framing + 2-3 options + action plan (owners, deadlines) + follow-up points.")


def _note_alerts_only_en() -> str:
    return ("Closing review / Audit Committee preparation: this item is NOT an M&A "
            "decision — no GO/NO-GO is issued. Agent positions are FINDINGS and ALERTS, "
            "not commitment verdicts. Expected deliverable: list of alerts above the "
            "materiality threshold, reservations, controls to perform, additional "
            "documents to request, and points to escalate to the Audit Committee "
            "(owners, deadlines).")


def _note_two_axis_en() -> str:
    return ("Two-axis decision (consistent — no real divergence): NO-GO on any immediate "
            "capital commitment; conditional GO to continue the instruction / in-depth "
            "due diligence. The agents' \u201cconditional GO\u201d positions concern the "
            "instruction, not the investment.")


def _classify_reco(text: str) -> str:
    if not text:
        return "INDÉTERMINÉ"
    low = text.lower()
    if "no-go" in low or "no go" in low or "nogo" in low:
        return "NO-GO"
    if "conditionn" in low:
        return "GO CONDITIONNEL"
    if re.search(r"\bgo\b", low):
        return "GO"
    return "INDÉTERMINÉ"


# v17.1-B2.3-E (P0-1 audit) — un « GO conditionnel » qualifié due diligence /
# « sans engagement capitalistique » ne porte PAS sur l'investissement : il porte
# sur l'INSTRUCTION. Le confondre avec le NO-GO (capital) de la finance crée une
# divergence artificielle. On distingue deux axes.
_DD_CUES = ("due diligence", "due-diligence", "duediligence", "instruction",
            "poursuite", "poursuivre", "approfondi", "sans engagement capitalistique",
            "audit complémentaire", "audit complementaire", "vérification", "verification")


def _is_dd_conditional(text: str) -> bool:
    low = (text or "").lower()
    return "conditionn" in low and any(c in low for c in _DD_CUES)


def decision_reconciler(agent_recos: Iterable[Dict[str, Any]],
                        decision_mode: str = "GO_NOGO", lang: str = "fr", genre: str = "",
                        board_option: str = "") -> Dict[str, Any]:
    """agent_recos : itérable de {'agent', 'reco', 'conviction'(optionnel)}.

    `decision_mode` (v17.1.0-B2.3-F) route l'OBJET produit selon le genre de point
    d'agenda (cf. patches/agenda_genre) :
      - GO_NOGO (défaut) : verdict d'engagement M&A — comportement historique,
        avec découplage à deux axes (capital vs due diligence).
      - OPTIONS_PLAN : point non décisionnel (étude / développement) — PAS de
        GO/NO-GO d'acquisition ; renvoie un cadrage + orientations + plan.
      - ARBITRATION : point générique — logique GO/NO-GO opérationnelle conservée.

    Ne masque jamais un désaccord réel."""
    parsed = []
    for r in agent_recos or []:
        cls = _classify_reco(r.get("reco", ""))
        parsed.append({"agent": r.get("agent", "?"), "class": cls,
                       "conviction": r.get("conviction", ""), "raw": r.get("reco", "")})

    # v17.1.0-B2.3-F — genre non décisionnel : on ne force PAS un GO/NO-GO.
    if decision_mode == "OPTIONS_PLAN":
        present_np = [p for p in parsed if p["class"] != "INDÉTERMINÉ"]
        orient = " ; ".join(f"{p['agent']}={p['class']}" for p in present_np) or "—"
        _en39 = str(lang or "").lower().startswith("en")   # v62.13.9.4.39 — note bilingue
        # v62.13.9.4.40 — un PLAN STRATÉGIQUE n'est pas un « point non décisionnel » : la
        # séance DÉCIDE d'une option. Dossier anglais réel du 21/09/2026 : §1 affichait « Non-
        # decisional agenda item (market study / business development) » au-dessus de deux
        # options dont une recommandée. Le cadrage « étude / développement » ne vaut que pour
        # les genres étude de marché et développement d'activité.
        _strat40 = str(genre or "").upper() in ("STRATEGIC_PLAN", "TURNAROUND", "CASH_REVIEW", "FINANCE_REVIEW")
        _note_strat_en40 = ("Strategic decision item: the Board is asked to choose among the options below; the "
                            "recommended option is an ORIENTATION to be validated, not a commitment until the Board "
                            "decides. Expected deliverable: options with their trade-offs, the recommended option, "
                            "the decisions it implies, and a dated action plan.")
        # 9.4.57 — contre-recette ChatGPT du 10/10 (§4.6) : l'option 2 était ADOPTÉE par le conseil (brief), mais la
        # rubrique annonçait encore « le conseil choisit… tant que le conseil n'a pas tranché ». Une orientation adoptée
        # n'est plus à choisir ; restent à arbitrer ses modalités (budget, calendrier, déploiement), jamais approuvées
        # en silence.
        if _strat40 and str(board_option or "").strip():
            _bo57 = str(board_option).strip()
            note = ((f"Strategic item — orientation ADOPTED by the Board: option {_bo57}. Still to be decided: its budget, "
                     f"schedule and rollout terms, which are not approved by the choice itself. The other options are "
                     f"recalled for reference.") if _en39 else
                    (f"Point stratégique — orientation ADOPTÉE par le conseil : option {_bo57}. Restent à arbitrer : son "
                     f"budget, son calendrier et ses modalités de déploiement, que le choix n'approuve pas. Les autres "
                     f"options sont rappelées pour mémoire."))
            return {"final": f"ORIENTATION ADOPTÉE PAR LE CONSEIL — option {_bo57} (budget, calendrier et déploiement à arbitrer)",
                    "divergent": False, "mode": "OPTIONS_PLAN", "by_agent": parsed, "orientations": orient,
                    "note": note,
                    "note_en": (f"Strategic item — orientation ADOPTED by the Board: option {_bo57}. Still to be decided: "
                                f"its budget, schedule and rollout terms, which are not approved by the choice itself."),
                    "final_en": f"ORIENTATION ADOPTED BY THE BOARD — option {_bo57} (budget, schedule and rollout to be decided)",
                    "board_option": _bo57}
        if _strat40:
            note = (("Strategic decision item: the Board is asked to choose among the options below; the "
                     "recommended option is an ORIENTATION to be validated, not a commitment until the Board "
                     "decides. Expected deliverable: options with their trade-offs, the recommended option, "
                     "the decisions it implies, and a dated action plan.") if _en39 else
                    ("Point d'agenda DÉCISIONNEL (plan stratégique) : le conseil choisit parmi les options "
                     "ci-dessous ; l'option recommandée est une ORIENTATION à valider, pas un engagement tant "
                     "que le conseil n'a pas tranché. Livrable attendu : options et arbitrages, option "
                     "recommandée, décisions qu'elle implique, plan d'action daté."))
        else:
          note = (("Non-decisional agenda item (market study / business development): no acquisition "
                 "GO/NO-GO. The agents' positions are ORIENTATIONS, not a commitment verdict. Distinguish "
                 "a possible 'NO-GO' on external presentation as-is from a 'GO' on the internal action "
                 "plan. Expected deliverable: framing + 2–3 options + action plan.") if _en39 else
                ("Point d'agenda NON décisionnel (étude de marché / développement "
                 "d'activité) : pas de GO/NO-GO d'acquisition. Les positions des agents "
                 "valent ORIENTATIONS, pas verdict d'engagement. Distinguer un éventuel "
                 "« NO-GO » de présentation externe en l'état d'un « GO » sur le plan "
                 "d'action interne. Livrable attendu : cadrage + 2-3 options + plan d'action."))
        # v62.13.9.4.40 — le rendu anglais lit « note_en » et « final_en » : ils suivent le genre comme
        # « note ». Sans cela, un run anglais affichait toujours « Non-decision agenda item » en §1.
        # Le libellé stratégique garde « ARBITR » : il reste neutre pour la cohérence des scénarios.
        return {"final": ("ARBITRAGE STRATÉGIQUE / PLAN D'ACTION (point décisionnel — orientation à valider par "
                          "le conseil ; pas de GO/NO-GO d'acquisition)" if _strat40 else
                          "CADRAGE / PLAN D'ACTION (point non décisionnel — pas de GO/NO-GO d'acquisition)"),
                "divergent": False, "mode": "OPTIONS_PLAN", "by_agent": parsed,
                "orientations": orient, "note": note,
                "note_en": (_note_strat_en40 if _strat40 else _note_options_plan_en()),
                "final_en": ("STRATEGIC CHOICE / ACTION PLAN (decision item — orientation to be validated by the "
                             "Board; no acquisition GO/NO-GO)" if _strat40 else
                             "FRAMING / ACTION PLAN (non-decision item — no acquisition GO/NO-GO)")}

    # F.6.7 — REVUE DE CLÔTURE / COMITÉ D'AUDIT : aucun verdict GO/NO-GO. L'objet
    # est une liste d'ALERTES / réserves / contrôles / points à remonter au Comité
    # d'audit. Les positions des agents valent CONSTATS, jamais décision d'engagement.
    if decision_mode == "ALERTS_ONLY":
        present_a = [p for p in parsed if p["class"] != "INDÉTERMINÉ"]
        constats = " ; ".join(f"{p['agent']}={p['class']}" for p in present_a) or "—"
        note = ("Revue de clôture / préparation Comité d'audit : ce point n'est PAS "
                "une décision M&A — aucun GO/NO-GO n'est rendu. Les positions des "
                "agents valent CONSTATS et ALERTES, pas verdict d'engagement. Livrable "
                "attendu : liste des alertes au-dessus du seuil de matérialité, "
                "réserves, contrôles à effectuer, pièces complémentaires à demander, "
                "et points à remonter au Comité d'audit (porteurs, échéances).")
        return {"final": "ALERTES & POINTS À REMONTER AU COMITÉ D'AUDIT (revue de clôture — pas de GO/NO-GO)",
                "divergent": False, "mode": "ALERTS_ONLY", "by_agent": parsed,
                "constats": constats, "note": note, "note_en": _note_alerts_only_en(),
                "final_en": "ALERTS & POINTS TO ESCALATE TO THE AUDIT COMMITTEE (closing review — no GO/NO-GO)"}

    present = [p for p in parsed if p["class"] != "INDÉTERMINÉ"]
    if not present:
        return {"final": "INDÉTERMINÉ", "divergent": False, "by_agent": parsed,
                "note": "Aucune recommandation exploitable détectée.",
                "note_en": "No actionable recommendation detected.",
                "final_en": "UNDETERMINED"}
    final = max(present, key=lambda p: _SEVERITY[p["class"]])["class"]
    classes = {p["class"] for p in present}
    divergent = len(classes) > 1

    # v17.1-B2.3-E (P0-1) — DÉCOUPLAGE À DEUX AXES. Si la « divergence » se résume à
    # NO-GO (capital) vs GO CONDITIONNEL qualifié due diligence / sans engagement
    # capitalistique, il n'y a PAS de divergence réelle : convergence sur « pas de
    # capital maintenant + poursuivre l'instruction ».
    dd_axis = any(_is_dd_conditional(p["raw"]) for p in present)
    capital_hold = any(p["class"] == "NO-GO" for p in present) or any(
        "sans engagement capitalistique" in (p["raw"] or "").lower() for p in present)
    if dd_axis and capital_hold and classes <= {"NO-GO", "GO CONDITIONNEL"}:
        note = ("Décision à deux axes (cohérente — pas de divergence réelle) : "
                "NO-GO sur tout engagement capitalistique immédiat ; GO conditionnel "
                "pour la poursuite de l'instruction / due diligence approfondie. Les "
                "positions « GO conditionnel » des agents portent sur l'instruction, "
                "pas sur l'investissement.")
        return {"final": "NO-GO engagement capitalistique / GO conditionnel due diligence",
                "divergent": False, "two_axis": True, "by_agent": parsed, "note": note,
                "note_en": _note_two_axis_en(),
                "final_en": "NO-GO on capital commitment / conditional GO on due diligence"}

    if divergent:
        detail = " ; ".join(f"{p['agent']}={p['class']}"
                            + (f" ({p['conviction']})" if p["conviction"] else "")
                            for p in present)
        detail_en = " ; ".join(f"{p['agent']}={_loc_class_en(p['class'])}"
                               + (f" ({p['conviction']})" if p["conviction"] else "")
                               for p in present)
        note = (f"DIVERGENCE entre agents — décision finale prudente = {final}. "
                f"Positions : {detail}. Arbitrage humain requis.")
        note_en = (f"DIVERGENCE between agents — prudent final decision = "
                   f"{_loc_class_en(final)}. Positions: {detail_en}. Human arbitration required.")
    else:
        note = f"Consensus agents = {final}."
        note_en = f"Agent consensus = {_loc_class_en(final)}."
    return {"final": final, "divergent": divergent, "by_agent": parsed,
            "note": note, "note_en": note_en, "final_en": _loc_class_en(final)}


# ─────────────────────────────────────────────────────────────────────────────
# 4. Roadmap guard (non rétroactive)
# ─────────────────────────────────────────────────────────────────────────────
_QUARTER_RE = re.compile(r"\bT([1-4])\s*[\-/ ]?\s*(20\d{2})\b", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_QUARTER_END_MONTH = {1: 3, 2: 6, 3: 9, 4: 12}


def roadmap_guard(text: str, run_date: Optional[date] = None) -> List[str]:
    """Signale les jalons « futurs » datés AVANT la date du run (ex. « T1 2026 »
    pour un run de juin 2026). Renvoie des flags. Ne réécrit pas (le consultant
    redatera)."""
    if not text:
        return []
    # Gate 12 - aucun flag temporel sans autorite fournie.
    if run_date is None:
        return []
    flags: List[str] = []
    for m in _QUARTER_RE.finditer(text):
        q, y = int(m.group(1)), int(m.group(2))
        end_m = _QUARTER_END_MONTH[q]
        last_day = 31 if end_m in (3, 12) else 30
        if date(y, end_m, last_day) < run_date:
            flags.append(f"Jalon « T{q} {y} » est déjà passé au {run_date.isoformat()} "
                         f"— roadmap rétroactive à redater depuis T0 réel.")
    for m in _ISO_DATE_RE.finditer(text):
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        if d < run_date:
            # B.1.3 (run dossier anglophone coté, point 8) — une date de COMPTES n'est pas
            # une échéance projet : « dernière clôture 2025-03-31 » flaguée
            # « antérieure au run » était un faux positif. Fenêtre de contexte
            # ±70 caractères autour du match.
            _ctx = text[max(0, m.start() - 70):m.end() + 70].lower()
            if re.search(r"cl[ôo]ture|comptes?\b|accounts?\b|filed|filing|"
                         r"d[ée]p[ôo]t|made up to|year[- ]end|exercice clos|"
                         r"period ending", _ctx):
                continue
            flags.append(f"Échéance « {m.group(0)} » est antérieure au run "
                         f"({run_date.isoformat()}) — à vérifier (jalon passé présenté comme à venir).")
    return sorted(set(flags))


# ─────────────────────────────────────────────────────────────────────────────
# 5. Contradiction gate financier (v17.1-B2.3-C, item 1 audit)
# ─────────────────────────────────────────────────────────────────────────────
_MISSING_MARKERS = (
    "non communiqué", "non communique", "non documenté", "non documente",
    "non disponible", "non publié", "non publie", "non calculable",
    "non renseigné", "non renseigne", "non chiffré", "non chiffre",
)
# Périmètre RESSERRÉ : métriques que la finance déclare typiquement « non
# communiquées » mais qu'un autre bloc chiffre quand même. On exclut CA /
# trésorerie / résultat net (souvent présents par entité → risque de faux
# positif cross-entités sponsor↔cible).
_CONTRA_METRICS = {"ebitda": "EBITDA", "cash burn": "Cash burn",
                   "cash-burn": "Cash burn", "capitaux propres": "Capitaux propres",
                   "operating cash flow": "Operating cash flow"}
_WIN = 55  # fenêtre de proximité (caractères)


def financial_contradiction_gate(text: str) -> List[str]:
    """Signale qu'une MÊME métrique est, à un endroit, déclarée « non communiquée »
    et, à un autre, chiffrée comme un fait (ex. EBITDA « non communiqué » côté
    finance vs « -42,4 M€ » côté stratégie). Ne tranche pas : signale au
    consultant. Aucune réécriture (doctrine : zéro latitude sur la présentation
    trompeuse, latitude maximale sur l'analyse)."""
    if not text:
        return []
    low = text.lower()
    missing: set = set()
    valued: set = set()
    for kw, canon in _CONTRA_METRICS.items():
        start = 0
        while True:
            i = low.find(kw, start)
            if i < 0:
                break
            start = i + len(kw)
            window = low[max(0, i - _WIN): i + len(kw) + _WIN]
            if any(mk in window for mk in _MISSING_MARKERS):
                missing.add(canon)
            # valeur monétaire chiffrée à proximité du mot-clé
            seg = text[max(0, i - 10): i + len(kw) + _WIN]
            if _AMT.search(seg):
                valued.add(canon)
    flags: List[str] = []
    for canon in sorted(missing & valued):
        flags.append(
            f"Contradiction à arbitrer : « {canon} » est présenté comme chiffré à "
            f"un endroit et « non communiqué » à un autre — un seul statut peut être "
            f"board-safe (probable reliquat d'une analyse initiale non corrigée).")
    return flags


# ─────────────────────────────────────────────────────────────────────────────
# 6. Cash-burn / runway gate (v17.1-B2.3-C, item 2 audit)
# ─────────────────────────────────────────────────────────────────────────────
_RUNWAY_RE = re.compile(r"runway[^.\n]{0,40}?\b\d[\d.,]*\s*(?:an|ans|mois)\b", re.IGNORECASE)


def cashburn_runway_gate(text: str) -> List[str]:
    """Si le cash burn est déclaré non documenté / sans source mais qu'un runway
    chiffré est présenté, signale que le runway est une HYPOTHÈSE dérivée, pas un
    fait. Signal-only."""
    if not text:
        return []
    low = text.lower()
    cb_undocumented = False
    start = 0
    for kw in ("cash burn", "cash-burn"):
        s = 0
        while True:
            i = low.find(kw, s)
            if i < 0:
                break
            s = i + len(kw)
            window = low[max(0, i - _WIN): i + len(kw) + _WIN]
            if any(mk in window for mk in _MISSING_MARKERS) or \
               "sans source" in window or "non étayé" in window or "non etaye" in window:
                cb_undocumented = True
    if cb_undocumented and _RUNWAY_RE.search(text):
        return ["Cohérence à arbitrer : un « runway » chiffré est présenté alors que "
                "le cash burn est déclaré non documenté / non étayé — le runway doit "
                "être traité comme une HYPOTHÈSE, pas un fait."]
    return []


# ─────────────────────────────────────────────────────────────────────────────
# 7. Deck scrub (v17.1-B2.3-C, item 3 audit) — chiffres commerciaux non sourcés
# ─────────────────────────────────────────────────────────────────────────────
# Unités COMMERCIALES / synergies (PAS les M€ financiers : on ne touche pas aux
# faits financiers promus). Un chiffre commercial présenté comme plan ferme sans
# source ni hedge est une présentation trompeuse → on le marque « à instruire ».
_COMMERCIAL_RE = re.compile(
    r"\d[\d.,\s]*\s*(?:gwh|mwh|\bmw\b|tonnes?\b|t/jour|t/j)"
    r"|\bppa\b"
    r"|\bhubs?\b"
    r"|off[\s\-]?take"
    r"|\d+\s*(?:[-–à]\s*\d+\s*)?contrats?\b"
    r"|(?:budget|marketing)[^.\n]{0,30}?\d[\d.,]*(?:\s*[-–]\s*\d[\d.,]*)?\s*k?\s*€",
    re.IGNORECASE,
)
_DECK_EXEMPT = ("à instruire", "a instruire", "à investiguer", "a investiguer",
                "[estim", "hypothèse", "hypothese", "non documenté", "non documente",
                "non communiqué", "non communique", "source", "communiqué",
                "communique", "❌", "à arbitrer", "a arbitrer", "[ref", "objectif",
                "cible", "à confirmer", "a confirmer")
# Abréviations de source en LIMITES DE MOT (« lourde » ne doit pas matcher « urd »).
_DECK_EXEMPT_ABBR = re.compile(r"\b(rfa|urd|cp|ddr|isin|lei|p\.?\s?\d)\b", re.IGNORECASE)
_INSTRUIRE_TAG = " [À INSTRUIRE]"


def deck_scrub_text(s: str) -> str:
    """Marque « [À INSTRUIRE] » un texte qui présente un chiffre commercial/
    synergie sans source ni hedge. Append-only, idempotent."""
    if not s or _INSTRUIRE_TAG.strip() in s:
        return s
    low = s.lower()
    if any(x in low for x in _DECK_EXEMPT) or _DECK_EXEMPT_ABBR.search(s):
        return s
    if _COMMERCIAL_RE.search(s):
        return s.rstrip() + _INSTRUIRE_TAG
    return s


def scrub_deck(payload: Dict[str, Any], decision_mode: str = "GO_NOGO") -> int:
    """Parcourt le deck (slides → bullets / actions) et marque les chiffres
    commerciaux non sourcés. Renvoie le nombre d'annotations. Fail-open, n'efface
    rien. N'altère pas les titres de slides (lisibilité).

    v17.1.0-B2.3-F.3 — genre-aware : le scrub commercial « [À INSTRUIRE] » a un
    sens pour une CIBLE d'acquisition sous scrutin board (GO_NOGO). Pour un point
    d'agenda non décisionnel (étude de marché, développement, cadrage), les
    chiffres commerciaux SONT le sujet — la gouvernance des sources passe par le
    WebFactsLedger, pas par un rabotage qui viderait le deck. On NE scrube donc
    PAS hors M&A (régression base CoDIR évitée)."""
    if not isinstance(payload, dict):
        return 0
    if decision_mode != "GO_NOGO":
        return 0
    n = 0
    for slide in payload.get("slides", []) or []:
        if not isinstance(slide, dict):
            continue
        bullets = slide.get("bullets")
        if isinstance(bullets, list):
            for i, b in enumerate(bullets):
                if isinstance(b, str):
                    nb = deck_scrub_text(b)
                    if nb != b:
                        bullets[i] = nb
                        n += 1
                elif isinstance(b, dict) and isinstance(b.get("text"), str):
                    nb = deck_scrub_text(b["text"])
                    if nb != b["text"]:
                        b["text"] = nb
                        n += 1
    return n


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrateur fail-open
# ─────────────────────────────────────────────────────────────────────────────
def apply_b23_guards(cr_text: str = "", agent_recos: Optional[list] = None,
                     run_date: Optional[date] = None,
                     decision_mode: str = "GO_NOGO", lang: str = "fr", genre: str = "",
                     board_option: str = "") -> Dict[str, Any]:
    """Applique toutes les gardes. Renvoie un dict additif (jamais d'exception).
    `decision_mode` (B2.3-F) est transmis au reconciler selon le genre du point."""
    res: Dict[str, Any] = {"flags": [], "cotation_text": cr_text,
                           "decision": None}
    try:
        scrubbed, cflags = cotation_gate(cr_text)
        res["cotation_text"] = scrubbed
        res["flags"] += cflags
    except Exception:
        pass
    try:
        res["flags"] += metric_coherence_gate(cr_text)
    except Exception:
        pass
    try:
        res["flags"] += roadmap_guard(cr_text, run_date=run_date)
    except Exception:
        pass
    try:
        res["flags"] += financial_contradiction_gate(cr_text)
    except Exception:
        pass
    try:
        res["flags"] += cashburn_runway_gate(cr_text)
    except Exception:
        pass
    try:
        if agent_recos:
            res["decision"] = decision_reconciler(agent_recos, decision_mode=decision_mode, lang=lang, genre=genre,
                                                  board_option=board_option)
            if res["decision"].get("divergent"):
                res["flags"].append(res["decision"]["note"])
    except Exception:
        pass
    res["flags"] = sorted(set(res["flags"]))
    return res
