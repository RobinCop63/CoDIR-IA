"""v17.1.0-B2.3-F — Détecteur de GENRE de point d'agenda CoDIR.

POSTULAT PRODUIT (rappel). CoDIR-IA est un assistant d'AGENDA DE CoDIR pour
dirigeant de PME/ETI, consultant, manager de transition DAF/CFO : des points,
des sujets, des plans d'action, du suivi. La décision M&A (GO/NO-GO sur une
cible) n'est qu'UN GENRE de point d'agenda — pas l'identité du produit.

Un run « étude de marché + préconisations de développement » a montré
que le moteur plaquait le gabarit « décision d'acquisition » sur un point qui
n'en est pas un : NO-GO de catégorie erronée, ton de contrôleur financier,
sourcing pointé sur la société au lieu du sujet.

Ce module est un ROUTEUR déterministe, fail-open. Il ne décide RIEN sur le fond :
il dit seulement quel OBJET produire, quel MODE de décision appliquer, quel TON
financier adopter, et — pour les genres « marché » — quel SUJET de recherche web
dériver. Doctrine inchangée : latitude maximale sur l'analyse, zéro latitude sur
la présentation trompeuse ; aucun fait n'est codé en dur ici.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

# ─────────────────────────────────────────────────────────────────────────────
# Genres
# ─────────────────────────────────────────────────────────────────────────────
MA_DECISION = "MA_DECISION"        # acquisition / fusion / cession / prise de participation
MARKET_STUDY = "MARKET_STUDY"      # étude / analyse de marché, taille, tendances
BIZDEV_PLAN = "BIZDEV_PLAN"        # développer / renforcer une activité, préconisations
STRATEGIC_PLAN = "STRATEGIC_PLAN"  # plan stratégique corporate, horizon pluriannuel
FINANCE_REVIEW = "FINANCE_REVIEW"  # cash / trésorerie / budget / forecast / clôture / covenant
CLOSING_REVIEW = "CLOSING_REVIEW"  # F.6.7 — revue de clôture / préparation Comité d'audit
LEGAL_TAX_REVIEW = "LEGAL_TAX_REVIEW"    # P0-4 — contentieux fiscal/DGFiP, litige, sommeil/dissolution
TURNAROUND_REVIEW = "TURNAROUND_REVIEW"  # P0-4 — retournement / restructuration / distress
GENERIC_CODIR = "GENERIC_CODIR"    # point d'agenda générique (arbitrage, sujet, suivi)

# Modes de décision
#   GO_NOGO       : verdict d'engagement (M&A) — comportement historique.
#   OPTIONS_PLAN  : cadrage + 2-3 options + plan d'action + suivi — PAS de GO/NO-GO capitalistique.
#   ARBITRATION   : point générique ; un GO/NO-GO opérationnel reste possible mais sans cadre acquisition.
#   ALERTS_ONLY   : F.6.7 — revue de clôture / Comité d'audit. AUCUN verdict GO/NO-GO :
#                   l'objet est une liste d'alertes/réserves/contrôles/points à remonter.
DECISION_GO_NOGO = "GO_NOGO"
DECISION_OPTIONS_PLAN = "OPTIONS_PLAN"
DECISION_ARBITRATION = "ARBITRATION"
DECISION_ALERTS_ONLY = "ALERTS_ONLY"

# Tons financiers
#   BOARD_SCRUTINY : cible d'acquisition sous scrutin board — anomalies = signaux durs.
#   ADVISORY       : structure de conseil / PME / unipersonnelle — Pappers est structurellement
#                    aveugle ; « données publiques insuffisantes », pas « anomalie critique ».
FINANCE_BOARD = "BOARD_SCRUTINY"
FINANCE_ADVISORY = "ADVISORY"


@dataclass
class GenreResult:
    genre: str
    confidence: float
    decision_mode: str
    finance_tone: str
    components: List[str] = field(default_factory=list)  # genres secondaires détectés
    signals: List[str] = field(default_factory=list)     # mots-déclencheurs (traçabilité)
    research_topic: Optional[str] = None                 # sujet pour le web-sourcing marché
    topic_tags: List[str] = field(default_factory=list)  # B2.3-F.1 — sujets CoDIR reconnus (RH, SI, risque…)

    @property
    def is_ma_decision(self) -> bool:
        return self.genre == MA_DECISION

    @property
    def forbids_go_nogo(self) -> bool:
        # F.6.7 — une revue de clôture / Comité d'audit ne produit jamais de verdict.
        return self.decision_mode == DECISION_ALERTS_ONLY

    @property
    def wants_market_research(self) -> bool:
        return MARKET_STUDY in ([self.genre] + self.components)


# ─────────────────────────────────────────────────────────────────────────────
# Signaux (limites de mot ; insensibles à la casse/accents simples)
# ─────────────────────────────────────────────────────────────────────────────
_MA_CUES = (
    r"acqui(?:sition|érir|erir)", r"\brachat\b", r"\bfusion\b", r"\bcession\b",
    r"prise de participation", r"prendre une participation", r"participation (?:minoritaire|majoritaire)",
    r"investissement minoritaire", r"ticket d['’]investissement",
    r"entrer au capital", r"entrée au capital", r"partenariat capitalistique",
    r"joint[\s\-]?venture", r"\bJV\b", r"rapprochement stratégique",
    r"partenariat industriel structurant",
    r"\bLBO\b", r"\bOPA\b", r"build[\s\-]?up", r"investir dans",
    r"\bcible\b.*\bacqu", r"\btarget\s+(?:company|firm|business|entity)\b",
    r"\bacquisition\s+target\b", r"\bmerger\b", r"\bbuyout\b", r"\binvestir dans\b",
)
_MARKET_CUES = (
    r"étude (?:de|du) march[ée]", r"analyse (?:de|du) march[ée]",
    r"taille (?:de|du) march[ée]", r"march[ée] (?:français|fr|européen|mondial)",
    r"\btendances?\b", r"état (?:de|du) march[ée]", r"market study",
    r"market (?:analysis|sizing|size)", r"market overview", r"étude sectorielle",
)
_BIZDEV_CUES = (
    r"d[ée]velopper (?:l[ae']|son|notre|votre)?\s*activit", r"renforcer (?:l[ae']|son|notre|votre)?\s*activit",
    r"d[ée]veloppement (?:d['’]|de l['’])?activit", r"pr[ée]conisation", r"recommandation",
    r"plan de d[ée]veloppement", r"feuille de route", r"go[\s\-]?to[\s\-]?market",
    r"strat[ée]gie commerciale", r"d[ée]velopper ou renforcer", r"business development",
)

_MA_RE = re.compile("|".join(_MA_CUES), re.IGNORECASE)

# P0-4 (M.5.6) — garde de négation : un cue M&A précédé d'une négation proche
# (« not acquisition », « pas d'acquisition », « not a target ») ne compte PAS.
# Sens d'erreur volontairement sûr : en cas de doute on N'impose PAS de GO/NO-GO.
_MA_NEG_RE = re.compile(
    r"\b(?:not|no|non|sans|aucune?|pas|hors|isn['’]?t|won['’]?t|doesn['’]?t|"
    r"n['’]est\s+pas|ne\s+sera\s+pas|ne\s+pas)\b[\w\s'’,\-]{0,15}$",
    re.IGNORECASE,
)


def _ma_hits(text: str) -> List[str]:
    text = text or ""
    out: List[str] = []
    for m in _MA_RE.finditer(text):
        pre = text[max(0, m.start() - 30):m.start()]
        if _MA_NEG_RE.search(pre):
            continue   # cue M&A nié → ignoré
        out.append(m.group(0))
    return out

_MARKET_RE = re.compile("|".join(_MARKET_CUES), re.IGNORECASE)
_BIZDEV_RE = re.compile("|".join(_BIZDEV_CUES), re.IGNORECASE)

_STRATEGIC_CUES = (
    r"plan\s+strat[ée]gique", r"strat[ée]gie\s+[àa]\s+(?:2|deux)\s+ans",
    r"horizon\s+(?:24\s+mois|(?:2|deux)\s+ans)",
    r"actionnaires?\s+et\s+(?:le\s+)?(?:codir|comex)",
    r"diagnostic\s+de\s+situation.{0,80}plan\s+strat[ée]gique",
    r"strategic\s+plan", r"two[-\s]?year\s+plan",
    # v62.13.9.4.40 — plans pluriannuels et arbitrage d'options (brief réel du 21/09/2026 :
    # un plan de croissance pluriannuel à arrêter par le conseil)
    r"plan\s+de\s+(?:croissance|transformation|redressement|d[ée]veloppement)",
    r"(?:growth|transformation|turnaround|three[-\s]?year|multi[-\s]?year)\s+plan",
    r"arr[êe]ter\s+le\s+plan", r"exercices\s+FY\s?\d{2,4}\s+[àa]\s+FY\s?\d{2,4}",
    r"FY\s?\d{4}\s*[–-]\s*FY\s?\d{4}\s+(?:plan|strategy|strat[ée]gie)",
    r"strategic\s+options?", r"options?\s+strat[ée]giques?",
)
_STRATEGIC_RE = re.compile("|".join(_STRATEGIC_CUES), re.IGNORECASE)

# B2.3-F.1 — Revue financière (cash/budget/forecast/clôture/covenant) : ton de
# rigueur board, mais SANS cadre acquisition.
_FINANCE_CUES = (
    r"\btr[ée]sorerie\b", r"\bcash\b", r"cash[\s\-]?flow", r"\bBFR\b", r"\bDSO\b",
    r"\bbudget\b", r"\bforecast\b", r"atterrissage", r"\bcl[ôo]ture\b", r"\bcovenant",
    r"plan de financement", r"besoin en fonds de roulement", r"\bliquidit",
)
_FINANCE_RE = re.compile("|".join(_FINANCE_CUES), re.IGNORECASE)

# F.6.7 — Revue de CLÔTURE / préparation COMITÉ D'AUDIT. Genre prioritaire : un
# brief de clôture peut citer un « pipeline M&A » comme PIÈCE documentaire — ce
# n'est pas une décision d'acquisition. Ces signaux priment donc sur les cues M&A.
_CLOSING_CUES = (
    r"revue\s+de\s+cl[ôo]ture", r"cl[ôo]ture\s+(?:annuelle|comptable|FY\s*\d{2,4}|des\s+comptes)",
    r"comit[ée]\s+d['’]?audit", r"audit\s+committee", r"closing\s+review",
    r"pr[ée]paration\s+du\s+(?:prochain\s+)?comit[ée]\s+d['’]?audit",
    r"revue\s+de\s+(?:la\s+)?cl[ôo]ture\s+FY", r"financial\s+closing\s+review",
    r"arr[êe]t[ée]\s+des\s+comptes", r"liasse\s+de\s+consolidation",
)
_CLOSING_RE = re.compile("|".join(_CLOSING_CUES), re.IGNORECASE)

# P0-4 (M.5.3) — Mission types additionnels.
# RETOURNEMENT / restructuration / distress : scénarios + ton board (urgence).
_TURNAROUND_CUES = (
    r"retournement", r"turnaround", r"restructuration", r"restructuring",
    r"redressement\s+judiciaire", r"proc[ée]dure\s+collective", r"\bsauvegarde\b",
    r"plan\s+de\s+continuation", r"cessation\s+de\s+paiement", r"\bdistress\b",
    r"soci[ée]t[ée]\s+en\s+difficult", r"entreprise\s+en\s+difficult",
    r"crise\s+de\s+(?:tr[ée]sorerie|liquidit)", r"\bCIRI\b", r"mandat\s+ad\s+hoc",
    r"\bconciliation\b", r"continuit[ée]\s+d['’]exploitation\s+menac",
)
# LEGAL / TAX REVIEW : contentieux fiscal, DGFiP/URSSAF, sommeil/dissolution (cas dossier de conseil).
_LEGAL_TAX_CUES = (
    r"contentieux\s+(?:fiscal|dgfip|urssaf|social)?", r"\bDGFiP\b", r"\bDGFIP\b",
    r"redressement\s+fiscal", r"contr[ôo]le\s+fiscal", r"litige\s+fiscal",
    r"rectification\s+fiscale", r"proposition\s+de\s+rectification",
    r"v[ée]rification\s+de\s+comptabilit", r"\bURSSAF\b",
    r"tax\s+(?:litigation|dispute|audit|adjustment|reassessment)",
    r"provision\s+pour\s+(?:risque|litige|contentieux)",
    r"mise\s+en\s+sommeil", r"\bdissolution\b", r"liquidation\s+amiable",
    r"avocat\s+fiscaliste", r"\bTHAOS\b",
)
_TURNAROUND_RE = re.compile("|".join(_TURNAROUND_CUES), re.IGNORECASE)
_LEGAL_TAX_RE = re.compile("|".join(_LEGAL_TAX_CUES), re.IGNORECASE)

# B2.3-F.1 — Reconnaissance (tags) de la palette large des sujets d'agenda CoDIR.
# Routage par défaut (générique) pour l'instant ; tags tracés pour traitement
# bespoke ultérieur. On reconnaît, on ne prétend pas (encore) un objet dédié.
_TOPIC_TAGS = {
    "HR": r"\bRH\b|recrut|effectif|masse salariale|tur[\s\-]?over|talents?|paie\b",
    "IT_ERP": r"\bERP\b|système d'information|système d’information|\bSI groupe\b|\bDSI\b|migration SI|Sage X3|\bD365\b|\bSAP\b|déploiement (?:outil|logiciel|ERP)",
    "RISK_COMPLIANCE": r"\brisques?\b|conformit|compliance|contentieux|litige|audit interne|contr[ôo]le interne",
    "ORG": r"\borganisation\b|r[ée]organisation|gouvernance|comitologie|processus",
    "ACTION_FOLLOWUP": r"suivi (?:du|de) plan|plan d'action|relance|jalons?|avancement|reste[\s\-]?à[\s\-]?faire",
    "BOARD_PREP": r"\bboard\b|conseil d'administration|comit[ée] strat[ée]gique|pr[ée]paration (?:du )?(?:codir|comex|board)",
}
_TOPIC_TAG_RES = {k: re.compile(v, re.IGNORECASE) for k, v in _TOPIC_TAGS.items()}


def _detect_topic_tags(text: str) -> List[str]:
    return [tag for tag, rx in _TOPIC_TAG_RES.items() if rx.search(text or "")]


def _hits(rx: re.Pattern, text: str) -> List[str]:
    return [m.group(0) for m in rx.finditer(text or "")]


# Sujet de recherche marché : « marché français du management de transition »,
# « étude du marché X », etc. → on isole le domaine après « marché … de/du ».
_TOPIC_RE = re.compile(
    r"march[ée]\s+(?:fran[çc]ais|europ[ée]en|mondial)?\s*(?:du|de la|de l['’]|des|de)\s+"
    r"([a-zàâäéèêëïîôöùûüç' \-]{4,60})",
    re.IGNORECASE,
)
_TOPIC_RE2 = re.compile(
    r"étude (?:de|du) march[ée]\s+(?:fran[çc]ais|europ[ée]en|mondial)?\s*"
    r"(?:du|de la|de l['’]|des|de)\s+([a-zàâäéèêëïîôöùûüç' \-]{4,60})",
    re.IGNORECASE,
)


def _extract_research_topic(brief: str) -> Optional[str]:
    for rx in (_TOPIC_RE2, _TOPIC_RE):
        m = rx.search(brief or "")
        if m:
            topic = m.group(1).strip(" .,;:'\u2019-")
            # coupe à un connecteur éventuel
            topic = re.split(r"\b(?:pour|sachant|en|afin|svp|s['’]il)\b", topic, maxsplit=1)[0].strip()
            if len(topic) >= 4:
                return topic
    return None


def _strip_injected_context52(brief: str) -> str:
    """Retire le bloc de continuité que le produit injecte en tête du brief (« CONTEXTE — CoDIR PRÉCÉDENT … --- ») : il
    décrit l'historique (clôtures, décisions, alertes), pas l'objet de la séance (contre-recette ChatGPT du 05/10)."""
    out, skip = [], False
    for l in str(brief or "").splitlines():
        if re.match(r"(?i)\s*(?:CONTEXTE\s+[—-]\s+CoDIR\s+PR|CONTEXT\s+[—-]\s+PREVIOUS)", l):
            skip = True
            continue
        if skip:
            if l.strip() == "---":
                skip = False
            continue
        out.append(l)
    return "\n".join(out)


def detect_agenda_genre(brief: str, company_name: str = "") -> GenreResult:
    """Route un point d'agenda. Fail-open : en l'absence de signal, GENERIC_CODIR
    (jamais un faux GO/NO-GO d'acquisition imposé)."""
    text = _strip_injected_context52(brief or "")    # 9.4.52 — l'objet de la séance se lit dans le brief du dirigeant seul
    ma = _ma_hits(text)
    market = _hits(_MARKET_RE, text)
    bizdev = _hits(_BIZDEV_RE, text)
    strategic = _hits(_STRATEGIC_RE, text)
    fin = _hits(_FINANCE_RE, text)
    # v62.13.9.4.40 — un signal de CLÔTURE cité dans une LIGNE D'ACTION (un livrable
    # daté à présenter au comité d'audit, avec son porteur)
    # est un livrable, pas l'objet de la séance. Brief réel du 21/09/2026 : cette seule ligne
    # classait un plan de croissance pluriannuel en revue de clôture, mode ALERTES SEULES —
    # zéro action, feuille de route vide. On ne compte que les signaux hors lignes d'action.
    # 9.4.52 — contre-recette ChatGPT du 05/10 : la séance 3, un suivi de plan de croissance, devenait « revue de clôture /
    # alertes seules ». Les déclarations de STATUT du dirigeant (« — Présenter … au comité d'audit — Directeur RSE —
    # réalisée. », sans date) et le bloc de continuité injecté décrivent l'état des actions, pas l'objet de la séance :
    # ils ne comptent jamais comme signal de clôture. Clore une action n'est pas demander une clôture comptable.
    _status_line52 = re.compile(r"[—–\-]\s*(?:r[ée]alis[ée]e?s?|report[ée]e?s?|abandonn[ée]e?s?|maintenue?s?|cl[ôo]tur[ée]e?s?|"
                                r"termin[ée]e?s?|annul[ée]e?s?|completed|postponed|dropped|kept)\b", re.I)
    _lines52, _skip52 = [], False
    for l in text.splitlines():
        if re.match(r"(?i)\s*(?:CONTEXTE\s+[—-]\s+CoDIR\s+PR|CONTEXT\s+[—-]\s+PREVIOUS)", l):
            _skip52 = True                         # bloc de continuité injecté : jusqu'au séparateur
            continue
        if _skip52:
            if l.strip() == "---":
                _skip52 = False
            continue
        if re.match(r"(?i)\s*(?:[ÉE]tat\s+des\s+actions|D[ée]cision\s+du\s+(?:conseil|CoDIR|comit[ée]))", l) or _status_line52.search(l):
            continue
        _lines52.append(l)
    _body_no_actions = "\n".join(
        l for l in _lines52
        if not re.match(r"^\s*(?:[—–\-•*]|\d+[.)])\s", l) or not re.search(r"·|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b", l))
    closing = _hits(_CLOSING_RE, _body_no_actions)
    turnaround = _hits(_TURNAROUND_RE, text)
    legaltax = _hits(_LEGAL_TAX_RE, text)
    tags = _detect_topic_tags(text)
    topic = _extract_research_topic(text)

    # Priorité 0 — F.6.7 — REVUE DE CLÔTURE / COMITÉ D'AUDIT. Prime sur M&A : un
    # « pipeline M&A » cité dans un brief de clôture est une PIÈCE, pas l'objet.
    # Mode ALERTS_ONLY : aucun GO/NO-GO ; ton board (l'entité est sous revue).
    # un plan stratégique EXPLICITE l'emporte sur un signal de clôture isolé
    if closing and strategic and len(closing) <= 1:
        closing = []
    if closing:
        comps = []
        if ma:
            comps.append(MA_DECISION)   # tracé comme pièce documentaire, pas comme objet
        return GenreResult(
            genre=CLOSING_REVIEW, confidence=min(1.0, 0.65 + 0.1 * len(closing)),
            decision_mode=DECISION_ALERTS_ONLY, finance_tone=FINANCE_BOARD,
            components=comps, signals=closing[:6], research_topic=None, topic_tags=tags,
        )

    # Priorité 1 — décision M&A (engagement capitalistique explicite).
    if ma:
        comps = []
        if market:
            comps.append(MARKET_STUDY)
        if bizdev:
            comps.append(BIZDEV_PLAN)
        return GenreResult(
            genre=MA_DECISION, confidence=min(1.0, 0.6 + 0.1 * len(ma)),
            decision_mode=DECISION_GO_NOGO, finance_tone=FINANCE_BOARD,
            components=comps, signals=ma[:6], research_topic=topic, topic_tags=tags,
        )

    # Priorité 1.2 — plan stratégique corporate pluriannuel. Ce genre
    # conserve un ton de rigueur board et un horizon OPTIONS_PLAN ; il ne doit
    # pas être dégradé en simple BIZDEV_PLAN advisory.
    if strategic:
        comps = []
        if market:
            comps.append(MARKET_STUDY)
        if bizdev:
            comps.append(BIZDEV_PLAN)
        if fin:
            comps.append(FINANCE_REVIEW)
        return GenreResult(
            genre=STRATEGIC_PLAN, confidence=min(1.0, 0.68 + 0.08 * len(strategic)),
            decision_mode=DECISION_OPTIONS_PLAN, finance_tone=FINANCE_BOARD,
            components=comps, signals=strategic[:6], research_topic=topic, topic_tags=tags,
        )

    # Priorité 1.5 (P0-4) — RETOURNEMENT / restructuration (distress). Prime sur
    # la revue financière classique : l'objet est un plan de redressement, pas un
    # simple suivi de cash. Scénarios (OPTIONS_PLAN), ton board (urgence/risque).
    if turnaround:
        comps = [FINANCE_REVIEW] if fin else []
        return GenreResult(
            genre=TURNAROUND_REVIEW, confidence=min(1.0, 0.6 + 0.1 * len(turnaround)),
            decision_mode=DECISION_OPTIONS_PLAN, finance_tone=FINANCE_BOARD,
            components=comps, signals=turnaround[:6], research_topic=topic, topic_tags=tags,
        )

    # Priorité 1.6 (P0-4) — LEGAL / TAX REVIEW (contentieux fiscal/DGFiP, sommeil,
    # dissolution). Cas dossier de conseil. Prime sur market/bizdev/finance : un brief de
    # contentieux peut citer un volet « relance commerciale » (axe), mais l'OBJET
    # est l'arbitrage juridico-fiscal. ARBITRATION, ton advisory (entité concernée,
    # pas une cible d'acquisition sous scrutin board).
    if legaltax:
        comps = []
        if bizdev:
            comps.append(BIZDEV_PLAN)   # tracé comme axe, pas comme objet
        if fin:
            comps.append(FINANCE_REVIEW)
        return GenreResult(
            genre=LEGAL_TAX_REVIEW, confidence=min(1.0, 0.6 + 0.1 * len(legaltax)),
            decision_mode=DECISION_ARBITRATION, finance_tone=FINANCE_ADVISORY,
            components=comps, signals=legaltax[:6], research_topic=topic, topic_tags=tags,
        )

    # Priorité 2 — étude de marché (avec ou sans volet développement).
    if market:
        comps = [BIZDEV_PLAN] if bizdev else []
        return GenreResult(
            genre=MARKET_STUDY, confidence=min(1.0, 0.55 + 0.12 * len(market)),
            decision_mode=DECISION_OPTIONS_PLAN, finance_tone=FINANCE_ADVISORY,
            components=comps, signals=(market + bizdev)[:6],
            research_topic=topic, topic_tags=tags,
        )

    # Priorité 3 — plan de développement / préconisations.
    if bizdev:
        return GenreResult(
            genre=BIZDEV_PLAN, confidence=min(1.0, 0.55 + 0.12 * len(bizdev)),
            decision_mode=DECISION_OPTIONS_PLAN, finance_tone=FINANCE_ADVISORY,
            components=[], signals=bizdev[:6], research_topic=topic, topic_tags=tags,
        )

    # Priorité 4 — revue financière (cash/budget/forecast/clôture/covenant).
    # Ton de rigueur board (l'entité est sous revue), mais PAS de cadre acquisition.
    if fin:
        return GenreResult(
            genre=FINANCE_REVIEW, confidence=min(1.0, 0.55 + 0.12 * len(fin)),
            decision_mode=DECISION_ARBITRATION, finance_tone=FINANCE_BOARD,
            components=[], signals=fin[:6], research_topic=topic, topic_tags=tags,
        )

    # Défaut — point d'agenda générique (sujets RH/SI/risque/orga/suivi reconnus
    # via topic_tags, routés ici pour l'instant ; objet bespoke = chantier futur).
    return GenreResult(
        genre=GENERIC_CODIR, confidence=0.4,
        decision_mode=DECISION_ARBITRATION, finance_tone=FINANCE_ADVISORY,
        components=[], signals=[], research_topic=topic, topic_tags=tags,
    )
