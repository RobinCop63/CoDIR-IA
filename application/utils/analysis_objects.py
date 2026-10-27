"""v62.13.9.4.23 — OBJETS D'ANALYSE (contrat produit du 06/09/2026, utilisateur +
ChatGPT) : la synthèse et la trame PPTX sont des PROJECTIONS des mêmes objets
extraits une fois du document de travail — décisions, options, risques,
arbitrages, actions (porteur, échéance, statut), hypothèses qualifiées,
questions ouvertes, sujets traités — jamais des projections d'un préfixe de
texte passé à un modèle. Extraction déterministe sur le TEXTE ENTIER des
sorties maintenues ; le modèle, s'il est disponible, ne sert qu'à formuler.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable, Mapping

_MD = re.compile(r"\*\*|__|`")
_TAG = re.compile(r"\s*⟨\s*(?:statut|status)\s*:[^⟩]*(?:⟩|$)\s*|\[NON SOURCÉ\]|\[REF_SECT\]|\[SOURCÉ\]|\[SOURCED\]|\[UNSOURCED\]", re.I)
_DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/20\d{2}|\d{1,2}(?:er)?\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)(?:\s+20\d{2})?|J\s*\+\s*\d{1,3}|S\d{1,2}\b|T[1-4]\s*20\d{2}|semaines?\s+\d{1,2}(?:\s*[-–]\s*\d{1,2})?)", re.I)
_NAME = r"[A-ZÀ-Ÿ][a-zà-ÿ'’\-]+(?:\s+[A-ZÀ-Ÿ][A-ZÀ-Ÿa-zà-ÿ'’\-]+){1,3}"
_OWNER = re.compile(
    r"\(\s*(" + _NAME + r")\s*\)"                                       # (Jeanne MARTIN)
    r"|(?:porteur|responsable|owner|pilote|lead|QUI|WHO)\s*:\s*(" + _NAME + r")"  # porteur : Jeanne MARTIN ; QUI : Robin SAUZET (v62.13.9.4.33)
    r"|(?:—|–|-)\s*(" + _NAME + r")\s*(?:$|[,;·|(])"                       # — Jeanne MARTIN
    r"|\bpar\s+(" + _NAME + r")\b", re.U)                                  # par Jeanne MARTIN


_ROLE_TOKEN = (r"(?:DG(?:\s+groupe)?|DAF|DSI|DRH|RH|DG\s*/\s*CEO|CEO|CFO|COO|CTO|CMO|CRO|PDG|COMEX|CODIR|Board|Conseil(?:\s+d['’]administration)?|"
               r"Direction(?:\s+[\w&'’-]+){0,2}|Dir\.?\s*[\w&'’-]+(?:\s+[\w&'’-]+)?|Directeur(?:\s+[\w&'’-]+){1,2}|Directrice(?:\s+[\w&'’-]+){1,2}|"
               r"Responsable(?:\s+[\w&'’-]+){1,2}|Dirigeant|Gérant|Comité(?:\s+[\w&'’-]+){1,2}|[A-ZÀ-Ÿ][a-zà-ÿ'’\-]+(?:\s+[A-ZÀ-Ÿ][A-ZÀ-Ÿa-zà-ÿ'’\-]+){1,3})")
_ROLE_OWNER_RE = re.compile(r"^\s*" + _ROLE_TOKEN + r"(?:\s*(?:\+|/|&|et|,)\s*" + _ROLE_TOKEN + r"){0,3}\s*$", re.U)


_ENGINE_CONTROL36 = re.compile(
    r"(?i)"
    r"non\s+[ée]tablie?\s+dans\s+(?:le\s+ledger|les\s+pi[èe]ces)"
    r"|valeur\s+du\s+[^.\n]{0,40}non\s+[ée]tablie"
    r"|tendance\s+du\s+[^.\n]{0,40}non\s+[ée]tablie"
    r"|rapprocher\s+les\s+sources\s+avant\s+calcul"
    r"|[àa]\s+[ée]tablir\s+depuis\s+le\s+reporting"
    r"|unsupported\s+quantified\s+(?:target|figure)"
    r"|quantified\s+target\s+withheld|proposition\s+quantifi[ée]e\s+[ée]cart[ée]e|cible\s+chiffr[ée]e\s+[ée]cart[ée]e"
    r"|baseline\s+and\s+provenance\s+required"
    r"|not\s+established\s+in\s+the\s+ledger"
    r"|to\s+be\s+established\s+from\s+(?:the\s+)?reporting")


_DECISION_VERB38 = re.compile(
    r"(?i)\b(?:d[ée]cider|arbitrer|choisir|lancer|valider|retenir|engager|mettre|prioriser|geler|"
    r"reconstituer|s[ée]curiser|renforcer|r[ée]duire|maintenir|adopter|approuver|suspendre|reporter|"
    r"decide|choose|select|launch|approve|endorse|prioritise|prioritize|commit|freeze|reduce|maintain|"
    r"secure|reconstitute|adopt|suspend|defer|submit|fund|formalize|formalise|establish|hold|pursue|"
    r"recommand[ée]e?s?|pr[ée]conis[ée]e?s?|retenue?s?|privil[ée]gi[ée]e?s?|recommended|advised|preferred|retained)\b")


def looks_like_a_decision(text: str) -> bool:
    """v62.13.9.4.38 — « Strategic option selection », « Dividend policy review »,
    « ARBITRAGE STRATÉGIQUE — Choix de l'option » : un libellé sans verbe, ou un
    intitulé en capitales suivi d'un tiret, est un TITRE de décision, pas une
    décision. Un dossier réel du 19/09/2026 livrait quatre titres pour quatre
    décisions ; un autre, un intitulé en capitales devant la flèche « → Décider … »."""
    t = " ".join(str(text or "").split())
    if not t:
        return False
    # intitulé en capitales (≥ 60 % des lettres) suivi d'un tiret : c'est un titre
    _head = t.split("—")[0].split(" - ")[0].split(" | ")[0]
    _letters = [c for c in _head if c.isalpha()]
    if "—" in t or " - " in t:
        if _letters and sum(1 for c in _letters if c.isupper()) / len(_letters) >= 0.6 and len(_head.split()) <= 6:
            return False
    if len(t.split()) >= 6 or _DECISION_VERB38.search(t):
        return True
    # une phrase courte qui COMMENCE par un infinitif français (« Fixer un positionnement
    # sectoriel », « Relancer les prospects ») ou un impératif anglais décide de quelque chose
    _first = re.sub(r"^[\W\d]+", "", t).split(" ")[0].lower()
    return bool(re.fullmatch(r"[a-zà-ÿ]{3,}(?:er|ir|re)", _first)) and _first not in ("hier", "notre", "votre", "leur", "entre", "contre", "autre", "encore", "toujours")


def is_engine_control_line(text: str) -> bool:
    """v62.13.9.4.36 — un CONSTAT DU MOTEUR n'est ni une décision ni un arbitrage.

    Runs réels du 17/09/2026 : « Valeur du chiffre d'affaires non établie dans les
    pièces exploitables — à vérifier. » ouvrait les DÉCISIONS PRIORITAIRES, « Tendance
    du chiffre d'affaires non établie dans le ledger » figurait en ARBITRAGE OUVERT, et
    « Unsupported quantified target — baseline and provenance required » était la SEULE
    décision prioritaire du dossier anglais.

    Ces phrases disent que le produit n'a pas pu établir une grandeur. Elles ont leur
    place dans les réserves et dans le registre de preuve ; elles n'en ont aucune là où
    le lecteur attend ce qu'il doit décider ou arbitrer.
    """
    t = " ".join(str(text or "").split())
    if not t:
        return False
    return bool(_ENGINE_CONTROL36.search(t))


_DECIDED45 = re.compile(r"(?i)d[ée]j[àa]\s+d[ée]cid[ée]e?s?|already\s+(?:decided|taken|approved)|"
                        r"d[ée]cision\s+(?:prise|act[ée]e)|decision\s+taken|approuv[ée]e?\s+par\s+le\s+(?:conseil|comit[ée]|codir)|"
                        r"approved\s+by\s+the\s+board")


# v62.13.9.4.41 — formules « à remplir » rencontrées dans les sorties d'agents, FR et EN.
_PLACEHOLDER41 = re.compile(
    r"(?i)^\W*(?:owner\s+to\s+(?:assign|be\s+(?:assigned|designated|confirmed|determined))|"
    r"to\s+be\s+(?:assigned|designated|confirmed|determined|defined|decided)|"
    r"tbd|tba|t\.b\.d\.?|n/?a|none|not\s+(?:assigned|specified|available|applicable)|"
    r"[àa]\s+(?:d[ée]signer|d[ée]finir|pr[ée]ciser|confirmer|arbitrer|d[ée]terminer)|"
    r"porteur\s+[àa]\s+d[ée]signer|responsable\s+[àa]\s+d[ée]signer|non\s+(?:d[ée]sign[ée]|pr[ée]cis[ée]|d[ée]fini)|"
    r"[àa]\s+compl[ée]ter|xxx+|\?+|-+|—+)\W*$")


def _owner_of(text: str) -> str:
    # v62.13.9.4.32 (B) — un PORTEUR est aussi un rôle : « DAF », « DSI + DG
    # groupe », « Dir. R&D + Dir. commercial », « RH + DG » (contre-audits du
    # 11/09/2026 : cellule porteur rendue « Porteur à désigner », porteur DG
    # effacé). Une cellule ou un champ « Porteur : … » entièrement fait de rôles
    # est le porteur ; la forme nominative (« Jeanne MARTIN ») reste reconnue.
    t = str(text or "").strip()
    m0 = re.search(r"(?i)(?:porteur|responsable|owner|pilote|lead)\s*:\s*([^|—–·;\n]{2,80})", t)
    cand = (m0.group(1) if m0 else t).strip(" .;")
    if 2 <= len(cand) <= 80 and _ROLE_OWNER_RE.fullmatch(cand) and not re.search(r"\d", cand):
        return re.sub(r"\s+", " ", cand)
    for mp in reversed(list(re.finditer(r"\(([^()]{2,80})\)", t))):       # « … (DSI + DG groupe) … »
        inner = mp.group(1).strip()
        if _ROLE_OWNER_RE.fullmatch(inner) and not re.search(r"\d", inner):
            return re.sub(r"\s+", " ", inner)
    m = _OWNER.search(t)
    if not m:
        return ""
    for g in m.groups():
        # v62.13.9.4.32 (B) — « DG », « DAF », « RH », « DSI » SONT des porteurs
        # (contre-audits du 11/09/2026 : porteur DG effacé, « DSI + DG groupe »
        # rendu « Porteur à désigner ») ; seuls les sigles d'unités ou de
        # métriques (CA, TJM, KPI…) ne le sont jamais.
        if g and not re.search(r"\d", g) and g.upper() not in ("CA", "TJM", "KPI", "CRM", "SEO", "ETI", "PME", "TPE", "BFR", "EBE", "ROI", "SLA"):
            return g.strip()
    return ""
_UNCERTAIN = re.compile(r"à\s+(?:investiguer|confirmer|v[ée]rifier|[ée]valuer|mesurer|documenter|arbitrer|valider|dimensionner)|non\s+(?:mesur|[ée]tabli|document|connu|v[ée]rifi)|inconnu|hypoth[èe]se|sc[ée]nario|estim", re.I)
_QUESTION = re.compile(r"^\s*(?:[-*•]\s*)?(?:\d+[.)]\s*)?(.{12,220}\?)\s*$")
_OPTION_HEAD = re.compile(r"^\s*#{0,6}\s*\**\s*(?:OPTION|Option|Sc[ée]nario|SCÉNARIO|Alternative|ALTERNATIVE)\s*(?:\[[^\]]*\]\s*)?(\d{1,2}|[A-D])\s*[—–\-:.)]\s*(.+?)\s*\**\s*$")   # v62.13.9.4.24 — A/B/C
_DECISION_HEAD = re.compile(r"^\s*(?:#{1,6}\s*)?(?:\d+[.)]\s*)?\**\s*(?:(?:immediate|urgent|key|main|core|critical|short[- ]term|imm[ée]diates?|urgentes?|principales?|cl[ée]s?|majeures?|structurantes?)\s+)?(?:d[ée]cisions?\s+prioritaires?|d[ée]cision|recommandations?\s+prioritaires?|orientations?\s+(?:recommand[ée]es?|prioritaires?|propos[ée]es?|strat[ée]giques?)|à\s+(?:soumettre|trancher|arbitrer|d[ée]cider)\b|priorit[ée]s?\s+strat[ée]giques?|arbitrages?\s+ouverts?|signaux\s+de\s+vigilance|risques?|points?\s+de\s+vigilance|priority\s+decisions?|open\s+decisions?|key\s+decisions?|proposed\s+decisions?|decisions?\b|recommendations?|priorities|trade[- ]offs?|open\s+(?:questions?|points?)|(?:cross[-\u2010-\u2015]?function\s+)?watch\s+signals?|risks?|red\s+flags?|points?\s+of\s+attention|next\s+steps?|action\s+plan|roadmap|prochaines?\s+[ée]tapes?|next\s+steps|plan\s+d['’]actions?|questions?\s+(?:ouvertes?|cl[ée]s?))\b", re.I)
_BARE_HEAD = re.compile(r"^\s*(?:\d+[.)]\s*)?\**\s*[A-ZÀ-Ÿ][A-ZÀ-Ÿ '’/&\-]{6,60}\**\s*(?:\(.*\))?\s*\**\s*[:.]?\s*$")   # « DÉCISIONS PRIORITAIRES (…) » sans dièse ; v62.13.9.4.25 : point final admis ; v62.13.9.4.26 : « **IMPACT COMMERCIAL (matériel)** »
_PIPE_ROW = re.compile(r"^\s*(?:\[\d{1,2}\]|\d{1,2}[.)])?\s*(.+?)\s*\|\s*(.+)$")            # « [1] texte | porteur | date | KPI »
_TOPIC_KEYS = {
    "marche": r"\bmarch[ée]s?\b|concurren|acteurs?\b|dynamique",
    "positionnement": r"positionnement|proposition de valeur|diff[ée]renci|expertise",
    # 9.4.52 — recette du 05/10 : « cibles d'émissions 2030 » tombait en « Développement commercial » (« missions » sans
    # frontière de mot à gauche) ; la présentation RSE au comité d'audit s'affichait en opportunité commerciale
    "commercial": r"prospect|pipeline|cabinets?|prescripteur|apporteur|leads?|\bmissions?\b|TJM|tarif",
    "rse": r"\bRSE\b|\bESG\b|[ée]missions|carbone|climat|scopes?\s*[123]|d[ée]carbon|CSRD|durabilit|biodiversit",
    "marketing": r"linkedin|visibilit|contenu|site web|seo|notori[ée]t",
    "finance": r"tr[ée]sorerie|marge|ebitda|chiffre d['’]affaires|budget|co[uû]t|financ",
    "rh_organisation": r"recrut|effectif|organisation|charge|capacit[ée]|temps disponible",
    "risques": r"risque|vigilance|d[ée]pendance",
    "supply_chain": r"stock|logisti|supply|approvisionn|entrep[oô]t",
    "juridique": r"juridique|contrat|assurance|conformit|rgpd|statut",
}


_SWOT_HEAD = re.compile(r"^\s*(?:#{1,6}\s*)?(?:\d+(?:\.\d+)*[.)]?\s*)?\**\s*(forces?|atouts?|points?\s+forts?|strengths?|faiblesses?|points?\s+faibles?|weaknesses?|"
                        r"opportunit[ée]s?|opportunities|menaces?|threats?)\b[^|]*$", re.I)
_SWOT_KIND = {"force": "strength", "atout": "strength", "point fort": "strength", "strength": "strength",
              "faiblesse": "weakness", "point faible": "weakness", "weakness": "weakness",
              "opportunit": "opportunity", "menace": "threat", "threat": "threat"}


def _swot_kind(label: str) -> str:
    l = str(label or "").lower()
    if re.search(r"forces?|atouts?|points?\s+forts?|strengths?", l):
        return "strength"
    if re.search(r"faiblesses?|points?\s+faibles?|weaknesses?", l):
        return "weakness"
    if re.search(r"opportunit", l):
        return "opportunity"
    if re.search(r"menaces?|threats?", l):
        return "threat"
    return ""


@dataclass
class AnalysisObject:
    kind: str                       # decision | option | risk | arbitration | action | hypothesis | question | fact
    text: str
    source: str                     # rôle / section d'origine
    owner: str = ""
    deadline: str = ""
    status: str = ""                # pour les actions : à lancer / en cours ; pour les hypothèses : la qualification
    topics: list[str] = field(default_factory=list)
    certainty: str = "established"  # established | proposed | uncertain
    ref: str = ""                   # identifiant stable (kind-NNN)
    start: str = ""                 # v62.13.9.4.27 — début d'une période (« 01/10/2026 - 30/11/2026 »), ISO


_AGENT_PREFIX = re.compile(r"^\s*(?:CHALLENGES?|D[ÉE]FIS?|ENJEUX?|POINTS?|ALERTES?)\s+(?:MKT|MARKETING|FIN|FINANCES?|COM|COMMERCIAL|RH|OPS?|SUPPLY|DG|STRAT[ÉE]GIE)\s*:\s*", re.I)   # v62.13.9.4.25


# v62.13.9.4.26 — run 13:10 sur la 9.4.25 : les agents numérotent (« [n1] »,
# « A1. », « R2 — », « D3 : ») et taguent la prose (« [ESTIM-HYPOTHÈSE] »).
# Un label d'ordre n'est jamais du texte de décision (le « 4 » de « [n4] »
# faisait retenir puis supprimer la décision) ; un tag d'agent reste dans le
# compte rendu, pas dans les objets projetés.
_ORDER_LABEL = re.compile(r"^\s*(?:\[\s*[nNdDaArR]?\s*\d{1,2}\s*\]|\(\s*[nN]\d{1,2}\s*\)|[nN]\d{1,2}\]|\b[ADRP]\d{1,2}(?=\s*[.:)—–-]))\s*[.:)\]—–-]*\s*")
_AGENT_TAG = re.compile(r"\s*\[(?:ESTIM(?:ATION)?|HYPOTH[ÈE]SE|FAIT|CIBLE|SC[ÉE]NARIO|SOURCE|CONTEXTE|D[ÉE]CLAR[ÉE]E?|A1)[^\]]{0,60}\]", re.I)


def _clean(s: str) -> str:
    # v62.13.9.4.36 — les ENTITÉS HTML ne doivent pas atteindre le document. Run réel
    # du 17/09/2026 (dossier industriel) : « contrainte dilution &lt;un niveau à
    # dimensionner » — neuf occurrences, séquelle du passage des sorties d'agents dans
    # un nettoyage de balises.
    s = str(s or "")
    for _e36, _c36 in (("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&"), ("&nbsp;", " "),
                       ("&quot;", '"'), ("&#39;", "'"), ("&apos;", "'")):
        if _e36 in s:
            s = s.replace(_e36, _c36)
    s = _TAG.sub(" ", s)
    s = _MD.sub("", s)
    s = re.sub(r"^\s*(?:[-*•▸►→]|\d+[.)]|[a-z][.)])\s*", "", s)   # v62.13.9.4.38 — la flèche « → » est une puce
    # v62.13.9.4.25 — contre-audit v24 (§3, PPTX) : « CHALLENGE MKT : … » est
    # une étiquette de l'agent Commercial, jamais le texte d'une question.
    s = _AGENT_PREFIX.sub("", s)
    s = _ORDER_LABEL.sub("", s)                    # v62.13.9.4.26
    s = _AGENT_TAG.sub("", s)                      # v62.13.9.4.26
    s = re.sub(r"\bvs\.(?=\s)", "vs", s)          # v62.13.9.4.29 — « Europe vs. segments » : « vs. » n'est pas une fin de phrase
    return re.sub(r"\s+", " ", s).strip(" :;-–—")


_FR_MONTHS = {"janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
              "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
              "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
              "september": 9, "october": 10, "november": 11, "december": 12}
_DATE_TOKEN = re.compile(
    r"\b(?P<iso>(?:19|20)\d{2}-\d{2}-\d{2})\b|\b(?P<d>\d{1,2})[/.\-](?P<m>\d{1,2})[/.\-](?P<y>(?:19|20)\d{2})\b|"
    r"\b(?P<d2>\d{1,2})(?:er)?\s+(?P<mn>janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|octobre|novembre|d[ée]cembre|"
    r"january|february|march|april|may|june|july|august|september|october|november|december)\s+(?P<y2>(?:19|20)\d{2})\b", re.I)


def _normalize_date_span(value: str) -> tuple[str, str]:
    """v62.13.9.4.27 — dates d'un texte d'échéance → (début ISO, fin ISO).
    « 15/09/2026 » → ("", "2026-09-15") ; « 01/10/2026 - 30/11/2026 » →
    ("2026-10-01", "2026-11-30") ; « 2026-09-30 » inchangé ; sinon ("", "")."""
    found: list[str] = []
    for m in _DATE_TOKEN.finditer(str(value or "")):
        if m.group("iso"):
            found.append(m.group("iso"))
        elif m.group("d"):
            d, mo, y = int(m.group("d")), int(m.group("m")), int(m.group("y"))
            if 1 <= mo <= 12 and 1 <= d <= 31:
                found.append(f"{y:04d}-{mo:02d}-{d:02d}")
        else:
            d, mo, y = int(m.group("d2")), _FR_MONTHS.get(m.group("mn").lower().replace("é", "é"), 0), int(m.group("y2"))
            if mo and 1 <= d <= 31:
                found.append(f"{y:04d}-{mo:02d}-{d:02d}")
    if not found:
        return "", ""
    if len(found) == 1:
        return "", found[0]
    return min(found), max(found)


_BOLD_LINE = re.compile(r"^\s*(?:\d{1,2}[.)]\s*)?\*\*[^*]{3,90}\*\*\s*:?\s*$")


_ACTION_HEAD = re.compile(
    r"^\s*(?:[A-ZÀ-Ÿa-zà-ÿ]+(?:er|ir|re|oir)\b"                       # infinitif français
    r"|(?:mise|mettre|lancement|lancer|d[ée]ploiement|d[ée]ployer|cr[ée]ation|cr[ée]er|"
    r"r[ée]alisation|r[ée]aliser|organisation|organiser|structuration|structurer|"
    r"formalisation|formaliser|pr[ée]paration|pr[ée]parer|revue|audit|arbitrage|arbitrer|"
    r"n[ée]gociation|n[ée]gocier|recrutement|recruter|constitution|constituer|"
    r"validation|valider|v[ée]rification|v[ée]rifier|collecte|collecter|"
    r"cartographie|cartographier|s[ée]curisation|s[ée]curiser|refonte|"
    r"r[ée]union|comit[ée]|atelier|s[ée]minaire|plan\b|programme\b|"
    r"launch|deploy|create|run|prepare|organise|organize|review|audit|negotiate|recruit|"
    r"validate|verify|collect|map|secure|meeting|workshop)\b)", re.I)


_REF_DATE50 = ""


def _today_iso() -> str:
    """v62.13.9.4.50 — date de référence = date d'ANALYSE du run (autorité temporelle), jamais l'horloge seule : le
    contrat 4.26 d'un run réel changeait de verdict d'un jour à l'autre (une échéance du 30/09 devenait
    « passée » le 01/10 et l'action sortait des objets). Horloge seulement si le run n'a pas de date d'analyse."""
    if _REF_DATE50:
        return _REF_DATE50
    from datetime import date
    return date.today().isoformat()


def _analysis_date_of50(result) -> str:
    import re as _re50
    r = result if isinstance(result, Mapping) else {}
    for cand in ((r.get("temporal_authority") or {}).get("analysis_date") if isinstance(r.get("temporal_authority"), Mapping) else None,
                 r.get("analysis_date"), (r.get("inputs") or {}).get("analysis_date") if isinstance(r.get("inputs"), Mapping) else None,
                 r.get("run_date"), r.get("generated_at")):
        m = _re50.match(r"((?:19|20)\d{2}-\d{2}-\d{2})", str(cand or ""))
        if m:
            return m.group(1)
    return ""


_PRODUCT_MARKER = re.compile(
    r"cible chiffr[ée]e (?:[ée]cart[ée]e|non [ée]tay[ée]e)|proposition chiffr[ée]e\s*[—-]|phrase chiffr[ée]e retir[ée]e|"
    r"[ée]l[ée]ment chiffr[ée] retir[ée]|voir l['’]annexe des sc|voir le registre des sc|baseline et provenance|"
    r"[ée]tats financiers structur[ée]s d[ée]tect[ée]s|p[ée]rim[èe]tre\s*:\s*social|comptes consolid[ée]s groupe fournis|"
    r"v[ée]rifier et parser|dynamique de march[ée] non [ée]tablie|tendance du chiffre d['’]affaires non [ée]tablie|"
    r"unsupported quantified|quantified propos|situation financi[èe]re actuelle non [ée]tablie|à [ée]tablir depuis le reporting|"
    r"^\s*sc[ée]nario\s*$|^\s*(?:hypoth[èe]se|option|colonne|valeur|libell[ée])\s*$", re.I)


_TEMPLATE_INSTRUCTION = re.compile(
    r"^\s*[_*]*\s*(?:format|template|gabarit|modèle|structure|syntaxe|exemple|example)\b\s*(?:de\s+ligne|ligne|line)?\s*[:：]"
    r"|\[\s*n\s*\]"                                        # « [n] QUOI », « [n] point »
    r"|\b(?:QUOI|QUI|QUAND|IMPACT)\b\s*\|\s*\b(?:QUOI|QUI|QUAND|IMPACT)\b"   # la ligne de gabarit elle-même
    r"|\b(?:WHAT|WHO|WHEN|IMPACT)\b\s*\|\s*\b(?:WHAT|WHO|WHEN|IMPACT)\b"
    r"|^\s*[_*]*\s*(?:max|min)\.?\s*\d+\s*(?:car|caract|char|mots|words)\b"
    r"|<\s*(?:votre|your|nom|name|date|chiffre|number)\s*>", re.I)


_BARE_METRIC_LINE = re.compile(
    r"^\s*[^:：]{3,60}\s*[:：]\s*[^\s:：]{0,6}[-+(]?\d[\d\s\u00A0\u202F.,]*\s*"
    r"(?:%|€|k€|M€|Md€|\$|£|m£|bn|k|M|pts?|points?|jours?|mois|ans?|salari[ée]s|ETP|FTE|x)?\s*"
    r"(?:\((?:FY)?(?:19|20)\d{2}(?:[-/](?:19|20)?\d{2})?\)|\b(?:FY)?(?:19|20)\d{2}\b)?\s*[.;]?\s*$", re.I)
_RISK_VERB = re.compile(
    r"(?i)\b(?:risque|menace|exposition|d[ée]pendance|vuln[ée]rab|tension|retard|d[ée]rive|perte|baisse|rupture|"
    r"incertitude|al[ée]a|fragilit|manque|absence|insuffisan|surco[ûu]t|litige|non[- ]conform|"
    r"risk|threat|exposure|dependen|shortfall|delay|breach|shortage|uncertain|weakness|lack|missing|overrun)\b")


def _is_bare_metric_line(s: str) -> bool:
    """« Free cash flow: £141m (FY2026) » : un libellé suivi d'une valeur est un
    fait, pas un risque (v62.13.9.4.34, lot 2). Une phrase qui formule un risque —
    même chiffrée — reste un risque."""
    t = str(s or "").strip()
    if not t or _RISK_VERB.search(t):
        return False
    return bool(_BARE_METRIC_LINE.match(t))


def _is_template_instruction(s: str) -> bool:
    """Une consigne de format recopiée par un agent n'est jamais un objet d'analyse
    (v62.13.9.4.34, lot 2)."""
    return bool(_TEMPLATE_INSTRUCTION.search(str(s or "")))


def _is_product_marker(s: str) -> bool:
    return bool(_PRODUCT_MARKER.search(str(s or "")))


def _looks_like_heading(s: str) -> bool:
    """v62.13.9.4.25 — « PRÉCONISATIONS COMMERCIALES. », « ARBITRAGES OU GO /
    NO-GO COMMERCIAUX. » : un titre en capitales écrit sans dièse dans une
    section SWOT n'est pas une opportunité."""
    t = _clean(s)
    core = re.sub(r"\s*\(.*?\)\s*$", "", t)          # v62.13.9.4.26 — « IMPACT COMMERCIAL (matériel) »
    letters = [c for c in core if c.isalpha()]
    return bool(letters) and len(core) >= 6 and len(t) <= 70 and sum(1 for c in letters if c.isupper()) >= 0.8 * len(letters)


def _topics(text: str) -> list[str]:
    t = str(text or "")
    return [k for k, pat in _TOPIC_KEYS.items() if re.search(pat, t, re.I)]


def _certainty(text: str) -> str:
    t = str(text or "")
    if _UNCERTAIN.search(t):
        return "uncertain"
    if re.search(r"\b(?:recommand|propos|cible|objectif|viser|prioris|d[ée]cid)", t, re.I):
        return "proposed"
    return "established"


_ESC_PIPE = "\u2016"   # remplace « \| » le temps du découpage


def _split_cells(line: str) -> list[str]:
    s = line.strip().strip("|").replace("\\|", _ESC_PIPE)
    return [c.strip().replace(_ESC_PIPE, "|") for c in s.split("|")]


def _table_rows(block: str) -> list[list[str]]:
    rows = []
    for line in block.splitlines():
        if line.strip().startswith("|") and not re.match(r"^\s*\|?\s*:?-{2,}", line.strip()):
            cells = _split_cells(line)                 # v62.13.9.4.24 — « \| » n'est pas une cellule
            if any(cells):
                rows.append(cells)
    return rows


def _header_index(header: list[str], *names: str) -> int:
    """Priorité SÉMANTIQUE : le premier nom de la liste gagne sur toutes les
    colonnes avant de passer au suivant (v62.13.9.4.24 — « Sujet | Action »
    donnait le sujet, « Étape | Action » donnait le numéro d'étape)."""
    for n in names:
        for i, h in enumerate(header):
            if n in h.lower():
                return i
    return -1



_SUBHEAD65 = re.compile(r"(?i)^\W*(?:constats?|parades?|horizon|situation|orientation|contexte|enjeux?|risques?|mitigations?|"
                        r"synth[èe]se|d[ée]cision|recommandation|exposition|vigilance|points?\s+de\s+vigilance|findings?|"
                        r"countermeasures?|context|stakes?|risks?|summary|recommendation|exposure)\s*[.:]?\s*"
                        r"(?:\[[^\]]{1,24}\])?\s*[.:]?\W*$")
_PAST_DECISION65 = re.compile(r"(?i)\b(?:a|ont)\s+[ée]t[ée]\s+(?:retenue?s?|adopt[ée]e?s?|d[ée]cid[ée]e?s?|valid[ée]e?s?|arr[êe]t[ée]e?s?|"
                              r"approuv[ée]e?s?|vot[ée]e?s?|r[ée]alis[ée]e?s?|effectu[ée]e?s?|sign[ée]e?s?)\b|"
                              r"\b(?:fusion|absorption|cession|acquisition|transmission)\s+(?:r[ée]alis[ée]e|intervenue|effective|"
                              r"sign[ée]e|conclue|achev[ée]e)\b|\beffet\s+r[ée]troactif\b|\b(?:a|ont)\s+eu\s+lieu\b|"
                              r"\b(?:was|were|has been|have been)\s+(?:adopted|selected|approved|decided|retained|completed|signed)\b|"
                              r"\b(?:merger|acquisition|disposal)\s+(?:completed|closed|took effect)\b|\bretroactive(?:ly)?\b")
# 9.4.65 (LM03) — une échéance explicite fait une vraie tâche, même si la phrase rappelle un événement accompli
_DEADLINE_CUE65 = re.compile(r"(?i)\b(?:avant|d['’]ici|au\s+plus\s+tard|[ée]ch[ée]ance|pour\s+le|[àa]\s+(?:pr[ée]senter|remettre|"
                             r"rendre|livrer|signer)|by|before|due|deadline)\b")
_DATE65 = re.compile(r"\b(?:\d{1,2}[/.-]\d{1,2}[/.-](?:19|20)\d{2}|(?:19|20)\d{2}-\d{2}-\d{2})\b")


def is_subheading65(text: str) -> bool:
    """Vrai pour un intertitre seul (« Constat. », « Parades. », « Horizon. ») — jamais pour une phrase."""
    return bool(_SUBHEAD65.match(str(text or "").strip()))


def is_past_decision_statement65(text: str) -> bool:
    """Vrai pour une phrase qui constate une décision passée (« l'option 2 a été retenue le 01/10/2026 ») sans autre
    échéance que la date de la décision ; faux pour une tâche qui porte sa propre échéance (« arbitrer le budget le D2 »)."""
    s = str(text or "")
    m = _PAST_DECISION65.search(s)
    if not m:
        return False
    # 9.4.65 (LM03) — « Fusion réalisée… effet rétroactif au 01/01/2025 » : un événement ACCOMPLI n'est pas une tâche ;
    # une échéance explicite (« avant le », « d'ici », « à présenter le »…) fait au contraire une vraie tâche
    if _DEADLINE_CUE65.search(s):
        return False
    return True

def extract_objects(result: Mapping[str, Any]) -> dict:
    """Extrait les objets d'analyse depuis les sorties maintenues (texte entier)."""
    global _REF_DATE50
    _prev50 = _REF_DATE50
    _REF_DATE50 = _analysis_date_of50(result) or _prev50
    try:
        return _extract_objects50(result)
    finally:
        _REF_DATE50 = _prev50


def _extract_objects50(result: Mapping[str, Any]) -> dict:
    outputs = (result or {}).get("outputs") or {}
    objs: list[AnalysisObject] = []
    seen: set[tuple[str, str]] = set()

    _TECH_TITLE = re.compile(r"OBJETS D['’]ANALYSE|IMPACT SUPPLY CHAIN|NOTE CEO|BRIEF CODIR|CADRE DE LECTURE|"
                             r"SUPPLY CHAIN\s*:\s*NON|non ex[ée]cut[ée]e|^ordres de grandeur financiers|"
                             r"reporting consolid[ée] avant usage|^aucun (?:chiffre|compte)|^sans pi[èe]ce|"
                             r"dimensionnement[^.]{0,40}n['’]est (?:pas )?[ée]tabli|voir l['’]annexe|voir le registre", re.I)

    _STATUS_ROW = re.compile(r"^\s*(?:(?:Statut|Status|État|State)\s*:\s*)?(?:[ÀA]\s+(?:ARBITRER|VALIDER|D[ÉE]CIDER|CONFIRMER|TRANCHER|LANCER|PLANIFIER)|EN\s+COURS|TERMIN[ÉE]E?|À\s+FAIRE|TO\s+DO|DONE)\b", re.I)
    # v62.13.9.4.29 — audit du dossier industriel v28 : « Phase 1 : Diagnostic », « Axe 3 : Monitoring
    # concurrentiel » sont des lignes de regroupement d'un tableau, pas des actions.
    _GROUP_ROW = re.compile(r"^\s*(?:phases?|axes?|volets?|piliers?|chantiers?|lots?|streams?|workstreams?|pillars?)\s*\d{1,2}\s*[:—–-]", re.I)

    def add(kind: str, text: str, source: str, **kw) -> None:
        # v62.13.9.4.41 — UN PLACEHOLDER N'EST PAS UNE VALEUR. Mesure du 23/09/2026 sur un
        # run réel : neuf actions déclaraient un responsable, mais sept portaient la chaîne
        # « Owner to assign » produite par l'agent. Le compte était faux dans les deux
        # sens — on croyait neuf porteurs, il y en avait deux — et le lecteur voyait un
        # nom là où il n'y avait personne. Un porteur, une échéance ou un statut à
        # remplir redeviennent une absence ; le rendu écrit alors « porteur à désigner ».
        for _k41 in ("owner", "deadline", "status", "start"):
            _v41 = str(kw.get(_k41) or "").strip()
            if _v41 and _PLACEHOLDER41.match(_v41):
                kw[_k41] = ""
        # v62.13.9.4.45 — AXE D'APPROBATION. Un texte qui dit « déjà décidée », « already
        # decided », « decision taken » porte un statut décidé, quelle que soit la
        # formulation de l'agent qui le reprend : le run réel du 26/09/2026 rendait
        # « RECOMMANDÉ » une action que le brief donnait pour décidée.
        if _DECIDED45.search(str(text or "")) and not str(kw.get("status") or "").strip():
            kw["status"] = "décidée"
        elif _DECIDED45.search(str(text or "")) and str(kw.get("status") or "").lower().startswith(("propos", "recommand", "suggest")):
            kw["status"] = "décidée"
        # v62.13.9.4.26 — registre : « À ARBITRER avant fin T4 2026 » est un statut,
        # pas une action ; « … LinkedIn intensif / IMPACT : … » garde l'action, pas
        # l'impact ; un premier champ en capitales est un libellé de dimension.
        raw = str(text or "")
        if kind in ("action", "decision", "arbitration") and re.match(
                r"(?i)^\s*(?:Statut|Status|État|State|Owner|Porteur|Responsable|Deadline|[ÉE]ch[ée]ance|Due|Impact|"
                r"Source|Sources|Confidence|Confiance|Horizon|KPI|Budget)\s*:", _clean(raw)):
            return          # v62.13.9.4.38/39 — une ligne d'étiquette (« Statut : », « Owner: », « Deadline: ») n'est pas un objet
        if kind in ("action", "decision", "arbitration") and (_STATUS_ROW.match(_clean(raw)) or _GROUP_ROW.match(_clean(raw))):
            return
        # v62.13.9.4.29 — audit du dossier industriel v28 : une bannière moteur, un placeholder de
        # neutralisation ou un statut de contrôle n'est jamais un objet d'analyse
        # (« Cible chiffrée écartée », « Proposition chiffrée — voir l'annexe »,
        # « États financiers structurés détectés : oui · Périmètre : … »).
        if _is_product_marker(_clean(raw)):
            return
        # v62.13.9.4.34 (lot 2) — UNE CONSIGNE DE GABARIT N'EST PAS UN CHOIX.
        # Run réel dossier agroalimentaire (308f1d, 13/09/2026) : « _Format : [n] QUOI | QUI |
        # QUAND | IMPACT », recopiée par l'agent depuis son prompt, devenait la
        # première décision et titrait « Orientation proposée » dans la synthèse.
        if _is_template_instruction(_clean(raw)):
            return
        # v62.13.9.4.34 (lot 2) — UN FAIT CHIFFRÉ N'EST PAS UN RISQUE. Contre-audit
        # de publication du 14/09/2026 (run réel dossier anglophone coté) : « Free cash flow: £141m
        # (FY2026) », relevé sous une tête de vigilance, entrait comme RIS-002 —
        # une donnée de contexte présentée comme un point de vigilance. Un libellé
        # suivi d'une valeur, sans verbe ni formulation de risque, est un fait.
        if kind == "risk" and _is_bare_metric_line(_clean(raw)):
            return
        # 9.4.65 — revue de publication du 16/10/2026 (F03) : un INTERTITRE de l'analyse (« Constat. », « Parades. »,
        # « Horizon. ») devenait un risque de la synthèse et une carte du deck (« Risque n°1 : Constat. ») ou une action.
        # Un intitulé seul n'est ni un risque, ni une action, ni une décision : le contenu métier est dans son paragraphe.
        if is_subheading65(_clean(raw)):
            return
        # 9.4.65 — F01 : « Orientation. L'option 2 a été retenue le 01/10/2026. Restent à arbitrer… » entrait comme action
        # datée du 01/10 et « en retard ». Une phrase qui CONSTATE une décision passée n'est pas un engagement ; une vraie
        # tâche à échéance passée reste une action (en retard).
        if kind == "action" and is_past_decision_statement65(_clean(raw)):
            return
        # v62.13.9.4.30 — contre-audit croisé du 09/09 : « Refonte statutaire :
        # mars 2023 (PV AGE du 30/03/2023) » entrait comme action « À lancer » et
        # occupait la première phase de la roadmap. Un événement accompli, daté
        # avant l'horizon du dossier et sourcé d'un acte (PV, décision, AGE), est
        # du contexte : il n'est ni une action ni une décision. Une action en
        # retard (échéance passée, verbe d'action, sans acte source) est conservée.
        # v62.13.9.4.31 — contre-audit v30 (§5) : « Effectif qualifié et capacité
        # d'innovation … marque enregistrée le 16 mai 2025 » entrait comme action
        # « À lancer » et ouvrait la roadmap. Une ACTION commence par un verbe ou
        # un nom d'action ; une phrase descriptive à date passée est du contexte.
        if kind == "action":
            _d31 = _clean(raw)
            if not _ACTION_HEAD.match(_d31):
                _due31 = _normalize_date_span(str(kw.get("deadline") or ""))[1]
                if _due31 and _due31 < _today_iso():
                    return
        if kind in ("action", "decision"):
            _t30 = _clean(raw)
            _m30 = re.search(r"\b(?:PV|proc[èe]s[- ]verbal|AGE?|AGO|d[ée]cisions?|d[ée]lib[ée]ration|assembl[ée]e|conseil)\b[^)\n]{0,40}?"
                             r"(?:du|le|de)\s+(\d{1,2}[/.-]\d{1,2}[/.-](?:19|20)\d{2}|(?:19|20)\d{2}-\d{2}-\d{2})", _t30, re.I)
            if _m30 and not re.search(r"(?i)\b(?:à\s+(?:lancer|réaliser|préparer|organiser)|prévoir|planifier|à venir|prochaine?)\b", _t30):
                _iso30 = _normalize_date_span(_m30.group(1))[1]
                if _iso30 and _iso30 < _today_iso():
                    return
        if kind in ("action", "decision", "arbitration"):
            raw = re.split(r"\s+(?:/|—|–|\|)\s*(?:IMPACT|ENJEU|KPI|R[ÉE]SULTAT)\s*:", raw, maxsplit=1)[0]
        if kind in ("arbitration", "decision", "action") and _looks_like_heading(raw):
            return
        t = _clean(raw)
        if len(t) < 8 or _TECH_TITLE.search(t):
            return
        # v62.13.9.4.27 — contre-audit v25 (§3) : « 15/09/2026 », « 01/10/2026 -
        # 30/11/2026 » étaient reconnus puis ignorés (roadmap en une phase,
        # conclusion sans échéance). Un objet date commun : ISO à l'extraction,
        # début et fin pour une période ; l'affichage se fait ensuite.
        if kw.get("deadline"):
            _s, _e = _normalize_date_span(str(kw.get("deadline")))
            if _e:
                kw["deadline"] = _e
                if _s and _s != _e and not kw.get("start"):
                    kw["start"] = _s
        key = (kind, t.lower()[:160])
        if key in seen:
            return
        seen.add(key)
        o = AnalysisObject(kind=kind, text=t[:400], source=source, topics=_topics(t), certainty=_certainty(t), **kw)
        objs.append(o)

    for role in ("direction_generale", "synthese_decisions", "strategie", "commercial", "marketing", "finance",
                 "supply_chain", "brief_codir", "agenda_register_markdown", "executive_synthesis"):
        text = outputs.get(role) if isinstance(outputs.get(role), str) else (result.get(role) if isinstance(result.get(role), str) else "")
        if not text:
            continue
        section = ""
        section_kind = ""
        section_deadline = ""       # « ### Semaine 1 (2026-09-06 → 2026-09-13) » : échéance des puces qui suivent
        lines = text.splitlines()
        handled_rows: set[str] = set()   # v62.13.9.4.24 — rangées consommées par le chemin tableau
        # tables : actions (porteur / échéance), risques (probabilité / impact)
        _tables_seen: list = []
        for m in re.finditer(r"((?:^\|[^\n]*\n?){2,})", text, re.M):
            rows = _table_rows(m.group(1))
            if len(rows) < 2:
                continue
            _tables_seen.append((m.group(1), len(objs)))
            head = [h.lower() for h in rows[0]]
            i_act = _header_index(head, "action", "chantier", "décision", "decision", "orientation", "levier", "sujet")
            i_step = _header_index(head, "étape", "etape", "step", "n°", "#")
            # v62.13.9.4.27 — contre-audit v25 (§2, P1) : « Étape (1…5) | Description |
            # Responsable | Date cible » — le texte de l'action est dans la colonne
            # descriptive quand la colonne étape est un numéro. Vocabulaire ouvert :
            # à défaut d'en-tête connu, la première colonne dont les cellules sont
            # du texte, hors porteur/date/statut, porte l'action.
            _step_numeric = (i_step >= 0 and all(re.fullmatch(r"\s*\d{1,2}[.)]?\s*", r[i_step] or "") for r in rows[1:] if len(r) > i_step))
            if (i_act < 0 or i_act == i_step) and (i_step < 0 or _step_numeric):
                i_desc = _header_index(head, "description", "libellé", "libelle", "intitulé", "intitule", "contenu", "détail", "detail",
                                       "objet", "tâche", "tache", "mesure", "activité", "activite", "task", "item")
                if i_desc < 0:
                    _own_i = _header_index(head, "porteur", "responsable", "owner", "pilote")
                    _due_i = _header_index(head, "échéance", "date", "délai", "deadline", "horizon", "quand")
                    _sta_i = _header_index(head, "statut", "status", "priorité", "priorite")
                    for ci in range(len(head)):
                        if ci in (i_step, _own_i, _due_i, _sta_i):
                            continue
                        cells_ci = [r[ci] for r in rows[1:] if len(r) > ci]
                        if cells_ci and sum(1 for c in cells_ci if len(_clean(c)) >= 8 and re.search(r"[A-Za-zÀ-ÿ]{3}", c)) >= max(1, len(cells_ci) // 2):
                            i_desc = ci
                            break
                if i_desc >= 0 and i_desc != i_step:
                    i_act = i_desc
            i_own = _header_index(head, "porteur", "responsable", "owner", "pilote")
            i_due = _header_index(head, "échéance", "date", "délai", "deadline", "horizon", "quand")
            i_sta = _header_index(head, "statut", "status", "priorité", "priorite")
            i_risk = _header_index(head, "risque")
            i_prob = _header_index(head, "probabilit", "impact", "gravit")
            swot_cols = {i: _swot_kind(h) for i, h in enumerate(head) if _swot_kind(h)}
            if len(swot_cols) == 1 and len(head) >= 2:
                # « | Force | Description | Levier | » sous « ### 2.1 Forces » : une rangée = un objet
                i0, k0 = next(iter(swot_cols.items()))
                for r in rows[1:]:
                    if len(r) > i0 and _clean(r[i0]):
                        desc = _clean(r[i0 + 1]) if len(r) > i0 + 1 else ""
                        add(k0, _clean(r[i0]) + (f" — {desc}" if desc else ""), f"{role}/swot")
                continue
            if len(swot_cols) >= 2:
                for r in rows[1:]:
                    for i, k in swot_cols.items():
                        if len(r) > i and _clean(r[i]):
                            add(k, r[i], f"{role}/swot")
                continue
            for r in rows[1:]:
                if i_risk >= 0 and i_prob >= 0 and len(r) > i_risk and _clean(r[i_risk]):
                    add("risk", r[i_risk], f"{role}/table", status=(r[i_prob] if len(r) > i_prob else ""))
                elif (i_own >= 0 or i_due >= 0) and (
                        (i_act >= 0 and i_act != i_step and len(r) > i_act and _clean(r[i_act]))
                        or (i_step >= 0 and (i_act < 0 or i_act == i_step) and len(r) > i_step
                            and len(_clean(r[i_step])) >= 8 and re.search(r"[A-Za-zÀ-ÿ]{3}", r[i_step]))):
                    # v62.13.9.4.25 — contre-audit v24 (§3, P1) : « Étape | Responsable |
                    # Échéance | Objectif » où l'étape EST l'action (« 1. Audit pipeline… »).
                    # La colonne TEXTE fait foi ; « Étape » n'est un numéro que si la
                    # cellule n'a pas de texte. Sept rangées DG = sept actions.
                    col = i_act if (i_act >= 0 and i_act != i_step) else i_step
                    _kind = "decision" if re.search(r"d[ée]cision|orientation", head[col]) else "action"
                    own = _clean(r[i_own]) if i_own >= 0 and len(r) > i_own else ""
                    due = _clean(r[i_due]) if i_due >= 0 and len(r) > i_due else ""
                    sta = _clean(r[i_sta]) if i_sta >= 0 and len(r) > i_sta else ""
                    if not own:
                        own = _owner_of(r[col])
                    add(_kind, r[col], f"{role}/table", owner=_clean(own), deadline=due, status=sta)
        # v62.13.9.4.27 — contre-audit v25 (§2) : une rangée n'est « consommée »
        # que si un objet en est sorti ; un tableau non reconnu retombe dans la
        # prose, où « texte | porteur | date » reste lisible sous son titre.
        for _tbl, _n0 in _tables_seen:
            if len(objs) > _n0:
                for ln in _tbl.splitlines():
                    handled_rows.add(ln.strip())
        # prose : sections, options, décisions, questions, hypothèses
        for line in lines:
            s = line.strip()
            if not s:
                continue
            if s.startswith("|"):
                if s in handled_rows:
                    continue
                # une rangée de tableau dans une section de décisions / arbitrages /
                # étapes : « | Fixer un positionnement… | Prénom NOM | 2026-09-20 | … | »
                if section_kind in ("decision", "arbitration", "action") and not re.match(r"^\|?\s*:?-{2,}", s):
                    cells = [c.strip() for c in s.strip("|").split("|")]
                    cells = [c for c in cells if c]
                    if cells and len(_clean(cells[0])) >= 8 and not re.match(r"^(?:action|d[ée]cision|sujet|porteur|risque)s?$", _clean(cells[0]).lower()):
                        own = next((_clean(c) for c in cells[1:] if _owner_of("(" + _clean(c) + ")") or re.match(r"^(?:DG|Direction|DAF|CEO|Dirigeant)\b", _clean(c))), "")
                        due = next((m.group(1) for c in cells[1:] for m in [_DATE.search(c)] if m), "")
                        # v62.13.9.4.38 — « 1. **Strategic option selection** | RECOMMENDED: Option 1
                        # (Margin Recovery…) as base case | Owner: Board | Deadline: … » : la première
                        # cellule est un TITRE, la décision est dans la cellule de recommandation.
                        # Dossier anglais réel du 19/09/2026 : quatre titres livrés pour quatre
                        # décisions. On garde « titre — recommandation » quand le titre seul ne
                        # décide de rien.
                        _text38 = cells[0]
                        if section_kind == "decision" and not looks_like_a_decision(_clean(cells[0])):
                            _reco38 = next((c for c in cells[1:] if len(_clean(c)) >= 20 and not _owner_of("(" + _clean(c) + ")")
                                            and not _DATE.search(c) and not re.match(r"(?i)^\**\s*(?:owner|porteur|deadline|[ée]ch[ée]ance)", _clean(c))), "")
                            if _reco38:
                                _text38 = f"{_clean(cells[0])} — {_clean(_reco38)}"
                        if section_kind == "decision" and (is_engine_control_line(_text38) or not looks_like_a_decision(_text38)):
                            continue
                        add(section_kind, _text38, f"{role}/{section[:40]}", owner=_clean(own), deadline=due)
                continue
            mo = _OPTION_HEAD.match(s)
            if mo:
                add("option", f"Option {mo.group(1)} — {mo.group(2)}", f"{role}/options")
                section_kind = "option"; section = s; continue
            if not s.startswith("#") and (_DECISION_HEAD.match(s) or _BARE_HEAD.match(s) or _BOLD_LINE.match(s)) and len(s) < 100 and "|" not in s:
                # titre écrit sans dièse : même traitement ; v62.13.9.4.27 (contre-audit
                # v25, §3) : une ligne ENTIÈREMENT en gras (« **Impact commercial** »)
                # est un titre quelle que soit sa casse — la catégorie d'un paragraphe
                # ne dépend plus de la typographie du titre qui le précède.
                s = "## " + re.sub(r"^\s*\d{1,2}[.)]\s*", "", s).strip("*# ")
            ms = _SWOT_HEAD.match(s)
            if ms and len(s) < 60:
                section = _clean(s); section_kind = _swot_kind(ms.group(1)); continue
            if s.startswith("#"):
                section = _clean(s)
                md0 = re.search(r"\(([^()]*20\d{2}-\d{2}-\d{2}[^()]*)\)", s) or re.search(r"\b(J\s*\+\s*\d{1,3}|S\d{1,2}|semaines?\s+\d{1,2}(?:\s*[-–]\s*\d{1,2})?)\b", s, re.I)
                section_deadline = _clean(md0.group(1)) if md0 else ""
                # v62.13.9.4.34 (lot 2) — tirets insécables/typographiques normalisés
                # avant toute reconnaissance de tête (run réel dossier anglophone coté :
                # « CROSS‑FUNCTION WATCH SIGNALS » porte un U+2011).
                mh = _DECISION_HEAD.match(re.sub(r"[\u2010-\u2015\u2212]", "-", s))
                sl = s.lower()
                # v62.13.9.4.28 — run 08/09 sur la 9.4.27 : « Next steps prioritaires »
                # était lu comme une section de DÉCISIONS (« prioritaires » l'emportait
                # sur « next steps ») : cinq étapes datées devenaient des décisions sans
                # porteur, et la première (une collecte) devenait l'orientation. Une
                # étape, un plan, une feuille de route sont des actions, quel que soit
                # l'adjectif ; « Recommandation d'orientation » est une section décision.
                # v62.13.9.4.29 — contre-audit v27/v28 : « ARBITRAGES OUVERTS (nécessitant
                # décision DG) » devenait une section de décisions parce que « décision »
                # l'emportait ; « À SOUMETTRE AU DG » n'était rien. Un arbitrage reste un
                # arbitrage : la section est arbitrage dès que le titre le dit, quel que
                # soit le mot qui l'accompagne ; « à soumettre / à trancher / à arbitrer /
                # à décider (au DG) » est une section d'arbitrages.
                # v62.13.9.4.32 (B) — le NOM DE TÊTE de la rubrique décide, pas une
                # sous-chaîne : « Décisions prioritaires (recommandées / à arbitrer) »
                # est une rubrique de décisions (contre-audit du dossier industriel :
                # classée arbitrage sur « à arbitrer », ses deux propositions devenaient
                # ARB-001/002) ; « Arbitrages ouverts (nécessitant décision DG) » reste
                # un arbitrage (9.4.29).
                _head32 = re.sub(r"^#{1,6}\s*(?:\d+[.)]\s*)?\**\s*", "", sl).strip()
                # v62.13.9.4.34 (lot 2) — LES MÊMES TÊTES EN ANGLAIS. Run réel
                # dossier anglophone coté (8064cb, 13/09/2026) : « PRIORITY DECISIONS (3–5) »,
                # « OPEN DECISIONS », « CROSS-FUNCTION WATCH SIGNALS » n'étaient
                # reconnues par aucune des trois expressions — zéro décision,
                # zéro risque, zéro arbitrage sur un dossier anglophone complet.
                # Les tirets d'un titre peuvent être insécables ou typographiques
                # (« CROSS‑FUNCTION », U+2011) : on normalise avant de comparer.
                _head32n = re.sub(r"[\u2010-\u2015\u2212]", "-", _head32)
                _head_arb32 = bool(re.match(
                    r"(?:arbitrages?\b|à\s+(?:soumettre|trancher|arbitrer|d[ée]cider)\b"
                    r"|open\s+(?:decisions?|questions?|points?)\b|trade[- ]offs?\b|to\s+(?:arbitrate|settle|decide)\b"
                    r"|pending\s+decisions?\b|decisions?\s+to\s+be\s+made\b|outstanding\s+decisions?\b)", _head32n, re.I))
                _head_dec32 = (not _head_arb32) and bool(re.match(
                    # v62.13.9.4.39 — « Immediate decisions », « Décisions structurantes » : un
                    # qualificatif devant le mot-clé ne fait pas sortir la rubrique (run réel
                    # anglais du 20/09/2026, rubrique vidée par un sous-titre daté).
                    r"(?:(?:immediate|urgent|key|main|core|critical|short[- ]term|imm[ée]diates?|urgentes?|principales?|cl[ée]s?|majeures?|structurantes?)\s+)?"
                    r"(?:d[ée]cisions?|recommandations?|orientations?|priorit[ée]s?"
                    r"|priority\s+decisions?|decisions?|recommendations?|priorities|proposed\s+decisions?"
                    r"|key\s+decisions?|directions?)\b", _head32n, re.I))
                _head_risk32 = bool(re.match(
                    r"(?:risques?|points?\s+de\s+vigilance|signaux\s+de\s+vigilance|vigilance"
                    r"|risks?|watch\s+(?:signals?|points?)|warning\s+signals?|red\s+flags?"
                    r"|(?:cross-function\s+)?watch\s+signals?|points?\s+of\s+attention)\b", _head32n, re.I))
                section_kind = ("action" if (mh and re.search(r"[ée]tape|next|plan d", sl)) or re.search(r"^#{1,6}\s*semaines?\s+\d|feuille de route|roadmap", sl) else
                                "arbitration" if _head_arb32 else
                                "risk" if (_head_risk32 and mh) else
                                "decision" if (_head_dec32 and mh) else
                                "arbitration" if re.search(r"arbitrages?\b|\bà\s+(?:soumettre|trancher|arbitrer|d[ée]cider)\b", sl) else
                                "decision" if (mh and re.search(r"d[ée]cision|recommandation|priorit|orientation", sl)) or (role in ("direction_generale", "synthese_decisions") and re.search(r"^#{1,6}\s*(?:\d+[.)]\s*)?\**\s*recommandation\b(?!s)", sl)) else
                                "risk" if mh and re.search(r"risque|vigilance", sl) else
                                "question" if re.search(r"questions?\s+(?:ouvertes?|cl[ée]s?)|à\s+trancher|points?\s+à\s+arbitrer", sl) else "")
                continue
            mq = _QUESTION.match(s)
            if mq or (section_kind == "question" and "?" in s):
                add("question", (mq.group(1) if mq else s), f"{role}/{section[:40]}")
                continue
            mp = _PIPE_ROW.match(s) if " | " in s and section_kind in ("decision", "arbitration", "action") else None
            if mp and len(_clean(mp.group(1))) >= 8:
                cells = [_clean(c) for c in mp.group(2).split("|")]     # « **Prénom NOM** » → « Prénom NOM »
                own = next((c for c in cells if re.match(r"^[A-ZÀ-Ÿ][a-zà-ÿ]+\s+[A-ZÀ-Ÿ]{2,}|^(?:DG|Direction|DAF|CEO|Dirigeant)\b", c)), "")
                due = next((m.group(1) for c in cells for m in [_DATE.search(c)] if m), "")
                # v62.13.9.4.38 — « **Strategic option selection** | RECOMMENDED: Option 1 … as
                # base case | Owner: Board | Deadline: … » : la tête est un TITRE, la décision
                # est dans la cellule de recommandation (dossier anglais réel du 19/09/2026 :
                # quatre titres livrés pour quatre décisions). On garde « titre — recommandation »
                # quand le titre seul ne décide de rien ; sans recommandation, on n'ajoute rien.
                _head38 = _clean(mp.group(1))
                _text38 = _head38
                # v62.13.9.4.39 — une cellule « RECOMMENDED: … » / « RECOMMANDÉ : … » est la décision
                # elle-même : elle accompagne toujours le titre, même quand le titre se suffit.
                _reco39 = next((re.sub(r"^\s*(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})\s*[—–\-:]\s*", "", c).strip()
                                for c in cells if re.search(r"(?i)(?:^|[—–\-:]\s*)(?:recommended|recommand[ée]e?)\s*:", c)), "")
                if section_kind == "decision" and _reco39 and _reco39.lower() not in _head38.lower():
                    _text38 = f"{_head38} — {_reco39}"
                elif section_kind == "decision" and not looks_like_a_decision(_head38):
                    # v62.13.9.4.39 — la recommandation peut suivre l'échéance dans la même cellule :
                    # « 2026-07-31 — RECOMMENDED: Select one of the three strategic options … »
                    # (run réel anglais du 20/09/2026, zéro décision livrée). On retire une date
                    # en tête de cellule avant de juger.
                    _cells39 = [re.sub(r"^\s*(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})\s*[—–\-:]\s*", "", c).strip() for c in cells]
                    _reco38 = next((c for c in _cells39 if len(c) >= 20 and not _DATE.search(c) and c != own
                                    and not re.match(r"(?i)^\**\s*(?:owner|porteur|deadline|[ée]ch[ée]ance)", c)), "")
                    if not _reco38:
                        continue
                    _text38 = f"{_head38} — {_reco38}"
                if section_kind == "decision" and is_engine_control_line(_text38):
                    continue
                add(section_kind, _text38, f"{role}/{section[:40]}", owner=_clean(own), deadline=due,
                    status=(cells[-1][:120] if len(cells) >= 3 else ""))
                continue
            # v62.13.9.4.38 — trois formes de plus, vues sur un dossier réel du 19/09/2026 :
            # une flèche « → Décider entre … » sous un intitulé, un item en gras
            # « **[1] Choisir … ** », et « QUOI : … » sous une décision (comme « Action : »).
            is_bullet = bool(re.match(r"^\s*(?:\**\s*)?(?:[-*•▸►→]|\d+[.)]|\[\d{1,2}\])\s+", s))
            # v62.13.9.4.36 — UNE DÉCISION PEUT ÊTRE PORTÉE PAR UN SOUS-TITRE. Run réel
            # du 17/09/2026 (dossier industriel) : dix rubriques de décisions, quarante-neuf
            # lignes candidates, UNE SEULE décision extraite, parce que les agents y
            # écrivent « ### Décision 1 : … » puis « **Action :** Arbitrer entre … » au
            # lieu de puces. On retient la PHRASE D'ACTION qui suit le sous-titre, jamais
            # le libellé du sous-titre seul, qui ne décide de rien.
            _m36b = re.match(r"^\s*\**\s*(?:Action|D[ée]cision|Decision|Recommandation|Recommendation|QUOI|WHAT)\s*\**\s*:\s*\**\s*(.+)$", s)
            if _m36b and section_kind in ("decision", "arbitration") and not is_bullet:
                _txt36 = _clean(_m36b.group(1))
                if len(_txt36) >= 12 and not is_engine_control_line(_txt36) and (section_kind != "decision" or looks_like_a_decision(_txt36)):
                    add(section_kind, _txt36, f"{role}/{section[:40]}", owner=_owner_of(_txt36))
                continue
            if section_kind in ("strength", "weakness", "opportunity", "threat") and (is_bullet or _looks_like_heading(s)):
                if _looks_like_heading(s):
                    section_kind = ""            # v62.13.9.4.25 — titre en capitales : la section SWOT est finie
                    continue
                add(section_kind, s, f"{role}/{section[:40]}")
            elif (section_kind in ("decision", "arbitration", "action", "risk") and _looks_like_heading(s)
                  and re.match(r"^\s*\d{1,2}[.)]\s*\**\s*[A-ZÀ-Ÿ]", s)):
                # v62.13.9.4.26 — « 4. **IMPACT COMMERCIAL (matériel)** » : un titre
                # NUMÉROTÉ en capitales ouvre un autre sujet, la section est finie.
                # Un sous-libellé non numéroté (« **ORIENTATIONS RECOMMANDÉES** »)
                # continue la section : les décisions qui le suivent restent.
                section_kind = ""
                continue
            elif section_kind == "decision" and is_bullet and re.match(r"^\s*(?:[-*•]|\d+[.)])\s*\**\s*(?:\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\**\s*:", s):
                add("action", s, f"{role}/{section[:40]}")      # v62.13.9.4.28 — une étape datée est une action
            elif section_kind == "decision" and is_bullet:
                # v62.13.9.4.35 (C3) — UNE DÉCISION A SON PORTEUR, comme une action.
                # Contre-audit du run réel du 16/09/2026 : les huit décisions
                # structurées sortaient avec un porteur vide alors que leurs phrases
                # portaient « QUI : … » ou un rôle entre parenthèses, et que les
                # actions du même run avaient le leur. L'extraction existait ; elle
                # n'était appelée que pour les actions.
                if is_engine_control_line(s) or not looks_like_a_decision(s):
                    continue
                add("decision", s, f"{role}/{section[:40]}", owner=_owner_of(s))
            elif (section_kind == "decision" and not is_bullet and role in ("direction_generale", "synthese_decisions")
                  and re.search(r"(?i)recommand|orientation", section)
                  and re.search(r"(?i)recommand[ée]|pr[ée]conis|privil[ée]gier|retenir|opter\s+pour|choisir|à\s+retenir", s)
                  and not re.match(r"^\s*(?:→|➜|⇒|statut\b)", s, re.I)
                  and not any(o.kind == "decision" and o.source == f"{role}/{section[:40]}" for o in objs)):
                # une seule recommandation par section : la première phrase qui recommande
                # v62.13.9.4.28 — la recommandation de la DG est un paragraphe (« il est
                # recommandé de privilégier la spécialisation… sous réserve de… »), pas une
                # puce : c'est une décision, la première phrase suffit, sous réserve comprise ;
                # l'amorce (« Au vu des données, il est recommandé de ») n'en fait pas partie.
                _sents = re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Ÿ«])", _clean(s))
                _first = _sents[0] if len(_sents[0].split()) >= 8 or len(_sents) < 2 else (_sents[0] + " " + _sents[1])
                _first = re.sub(r"(?i)^(?:au\s+vu\s+de[^,]{0,80},\s*|compte\s+tenu\s+de[^,]{0,80},\s*|dans\s+ce\s+contexte,\s*)?"
                                r"(?:il\s+est|nous|je|la\s+dg|la\s+direction\s+g[ée]n[ée]rale)?\s*(?:recommand[ée]|recommandons|recommande|pr[ée]conis[ée]|pr[ée]conise|pr[ée]conisons)\s+(?:de\s+|d['’])", "", _first).strip()
                _first = _first[:1].upper() + _first[1:]
                if is_engine_control_line(_first) or not looks_like_a_decision(_first):
                    continue
                add("decision", _first, f"{role}/{section[:40]}", owner=_owner_of(_first))
            elif section_kind == "arbitration" and is_bullet:
                if is_engine_control_line(s):
                    continue
                add("arbitration", s, f"{role}/{section[:40]}")
            elif section_kind == "risk" and is_bullet:
                add("risk", s, f"{role}/{section[:40]}")
            elif section_kind == "action" and is_bullet:
                md = _DATE.search(s)
                add("action", s, f"{role}/{section[:40]}", owner=_owner_of(s),
                    deadline=(md.group(1) if md else section_deadline))
            elif "⟨statut" in line or "⟨status" in line:
                add("hypothesis", s, f"{role}/{section[:40]}", status=_clean(re.search(r"⟨[^⟩]*⟩?", line).group(0)) if re.search(r"⟨[^⟩]*⟩?", line) else "")

    # v62.13.9.4.24 — repli SWOT quand l'agent n'en a pas écrit : forces et
    # faiblesses depuis les affirmations établies de la prose (marqueurs
    # lexicaux), opportunités depuis les options, menaces depuis les risques.
    # Le renderer applique le même repli pour O/M ; ici seulement F/f.
    if not any(o.kind in ("strength", "weakness") for o in objs):
        _POS = re.compile(r"\b(?:atouts?|expertise|exp[ée]rience|r[ée]seau|cr[ée]dibilit|r[ée]f[ée]rences?|agilit|"
                          r"r[ée]activit|reconnu|solide|ma[îi]trise|compétences?|senior|fid[ée]lis)", re.I)
        _NEG = re.compile(r"\b(?:d[ée]pendance|absence|manque|faible|limit|fragil|insuffisan|vuln[ée]rab|"
                          r"pas de|aucun[e]?|non (?:mesur|[ée]tabli|document))", re.I)
        seen_sw: set[str] = set()
        for role in ("strategie", "brief_codir", "marketing"):
            text = outputs.get(role) if isinstance(outputs.get(role), str) else ""
            for line in (text or "").splitlines():
                s = _clean(line)
                if not (12 <= len(s) <= 220) or line.strip().startswith(("|", "#")) or "?" in s:
                    continue
                if re.search(r"\d", s) and _UNCERTAIN.search(s):
                    continue                              # une hypothèse n'est pas une force
                k = "strength" if _POS.search(s) and not _NEG.search(s) else ("weakness" if _NEG.search(s) and not _POS.search(s) else "")
                if k and s.lower()[:80] not in seen_sw and not _TECH_TITLE.search(s):
                    seen_sw.add(s.lower()[:80])
                    objs.append(AnalysisObject(kind=k, text=s[:200], source=f"{role}/repli-swot", topics=_topics(s),
                                               certainty="established"))
                    if sum(1 for o in objs if o.kind == k) >= 5:
                        continue
    # repli faiblesses : les risques INTERNES (dépendance, capacité, absence de…)
    if not any(o.kind == "weakness" for o in objs):
        _INT = re.compile(r"d[ée]pendance|capacit[ée]|absence|manque|faible|limit|surcharge|temps disponible|"
                          r"un seul|unipersonnel|pas de (?:site|r[ée]f[ée]rence|process|crm)|non document", re.I)
        for o in [x for x in objs if x.kind in ("risk", "arbitration")]:
            if _INT.search(o.text) and sum(1 for x in objs if x.kind == "weakness") < 5:
                objs.append(AnalysisObject(kind="weakness", text=o.text[:200], source=o.source + "/repli-swot",
                                           topics=list(o.topics), certainty="established"))
    # v62.13.9.4.26 — dédoublonnage entre sources : « [n2] Mettre en place une
    # activation LinkedIn intensive » (tableau DG) et « Activation LinkedIn
    # intensive (2 posts/semaine) » (registre) sont la même décision. Le premier
    # objet (ordre des rôles : DG d'abord) est conservé ; porteur et date
    # manquants sont repris du doublon. Recouvrement de mots pleins, sans chiffre.
    def _content_words(txt: str) -> set[str]:
        return {w for w in re.findall(r"[a-zà-ÿ]{4,}", txt.lower())
                if w not in ("dans", "pour", "avec", "sans", "entre", "vers", "plus", "moins", "leur", "leurs", "cette", "elle", "elles",
                             "mettre", "place", "lancer", "créer", "faire", "définir", "structurer", "mise", "lancement", "création",
                             "with", "from", "that", "this", "into", "over")}
    kept: list = []
    for o in objs:
        if o.kind not in ("decision", "action", "arbitration"):
            kept.append(o); continue
        cw = _content_words(o.text)
        dup = None
        for k in kept:
            if k.kind != o.kind:
                continue
            kw = _content_words(k.text)
            if len(cw) >= 2 and len(kw) >= 2:
                inter = len(cw & kw)
                # v62.13.9.4.29 — audit du dossier industriel v28 : « Lancement de l'audit » (15/12) et
                # « Rapport d'audit » (31/01) sont deux étapes, pas un doublon : deux
                # échéances différentes ne fusionnent jamais.
                if o.deadline and k.deadline and o.deadline != k.deadline:
                    continue
                if inter >= 0.6 * min(len(cw), len(kw)) and inter >= 2:
                    dup = k; break
        if dup is None:
            kept.append(o)
        else:
            if not dup.owner and o.owner: dup.owner = o.owner
            if not dup.deadline and o.deadline: dup.deadline = o.deadline
            if not dup.status and o.status: dup.status = o.status
    objs = kept
    # identifiants stables et sujets traités
    counters: dict[str, int] = {}
    for o in objs:
        counters[o.kind] = counters.get(o.kind, 0) + 1
        o.ref = f"{o.kind[:3].upper()}-{counters[o.kind]:03d}"
    topics_present = sorted({t for o in objs for t in o.topics})
    by_kind = {k: [asdict(o) for o in objs if o.kind == k] for k in
               ("decision", "option", "risk", "arbitration", "action", "hypothesis", "question",
                "strength", "weakness", "opportunity", "threat")}
    return {"version": "analysis-objects-v1", "objects": [asdict(o) for o in objs],
            "by_kind": by_kind, "counts": {k: len(v) for k, v in by_kind.items()},
            "topics_present": topics_present}
