"""quantity_ledger — v62.13.9.4.6

Socle de décision éditoriale « deny-by-default typé ».

Contrat (contre-audit du 29/08/2026, correctif n°1) :
    Sur les surfaces exécutives, TOUTE quantité — quel que soit son
    vocabulaire ou sa forme — est retenue par défaut, sauf si elle est
    rattachée avec certitude à un TYPE DESCRIPTIF AUTORISÉ (whitelist
    ci-dessous). Les signaux lexicaux (verbes d'action, marqueurs
    prospectifs) servent à DURCIR la décision, jamais à autoriser.

Types autorisés (whitelist fermée) :
    EVIDENCE_ROW      ligne du registre de preuve (statut|…|source|page)
    DATE_PERIOD       année, exercice, trimestre, plage d'années-bornes
    IDENTIFIER        SIREN, n°, version, fichier, section, page, code
    METHOD_SCORE      score méthodologique du produit (x/10, y/100)
    AUTHORITY         valeur d'horizon portée par l'autorité Temporal Core
    CLAIM_BOUND       composant lié à un claim (utils.claim_binding)
    REGISTRY_BAND     tranche d'effectif registre, hors action
    DURATION_ATTR     durée-attribut produit (24-Month, 3-year)
    STRUCTURE_COUNT   compte de structure documentaire STRICT, hors action
    ACCOMPLISHED_FACT assertion au passé sur période close, sans futur

Toute quantité sans type ⇒ retenue (raison UNTYPED_QUANTITY).
En cas d'ambiguïté entre un type et un signal d'action/futur ⇒ retenue
(fail-closed).
"""
from __future__ import annotations

import datetime as _dt
import re
from utils.non_quantity import non_quantity_spans as _nq_spans48, WITHOUT_PERIODS as _NQ_NO_PERIODS48
from dataclasses import dataclass, field

from utils import claim_binding as _CB

# ─────────────────────────────────────────────────────────────────────────────
# 1. EXTRACTION — toute forme de quantité, normalisée
# ─────────────────────────────────────────────────────────────────────────────

_UNICODE_FRACTIONS = "½⅓⅔¼¾⅕⅖⅗⅘⅙⅚⅐⅛⅜⅝⅞⅑⅒"

_WORDNUM_FR = (
    r"deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|"
    r"quatorze|quinze|seize|vingt|trente|quarante|cinquante|soixante|"
    r"cent(?:s)?|mille|million(?:s)?|milliard(?:s)?"
)
_WORDNUM_EN = (
    r"two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred(?:s)?|"
    r"thousand(?:s)?|million(?:s)?|billion(?:s)?"
)
_QUANTIFIER = (
    r"dizaines?|douzaines?|quinzaines?|vingtaines?|trentaines?|centaines?|"
    r"milliers?|(?:d[eu]\s|d['’]un\s|d['’]une\s)?(?:tiers|moiti[eé]|quarts?)|"
    r"dozens?|(?:a\s|one[-\s])?(?:third|half|quarter)s?"
)

# v62.13.9.4.32 (B) — UNE DATE EST UNE DATE, extraite AVANT toute autre lecture :
# « 2027-09-01 » était découpé en plage « 2027-09 », « le 10 décembre 2026 »
# laissait un « 10 » cardinal non typé — un jalon d'action daté devenait « Cible
# chiffrée écartée » (contre-audits du 11/09/2026 : séminaire du 31 octobre,
# plan de redressement du 10 décembre, plan innovation du 01/09/2027).
_MONTH_WORDS = (r"janv(?:ier|\.)?|f[ée]v(?:rier|\.)?|mars|avr(?:il|\.)?|mai|juin|juil(?:let|\.)?|ao[uû]t|sept(?:embre|\.)?|"
                r"oct(?:obre|\.)?|nov(?:embre|\.)?|d[ée]c(?:embre|\.)?|"
                r"jan(?:uary|\.)?|feb(?:ruary|\.)?|march|apr(?:il|\.)?|may|june|july|aug(?:ust|\.)?|sep(?:t|tember|\.)?|"
                r"oct(?:ober|\.)?|nov(?:ember|\.)?|dec(?:ember|\.)?")
_DATE_KIND_RE = re.compile(
    r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b"                                   # 2027-09-01
    r"|\b\d{1,2}[/.\-]\d{1,2}[/.\-](?:19|20)\d{2}\b"                      # 01/09/2027, 01-09-2027, 01.09.2027
    r"|\b\d{1,2}(?:er|st|nd|rd|th)?\s+(?:" + _MONTH_WORDS + r")(?:\s+(?:19|20)\d{2})?\b"   # 10 décembre 2026, 31 octobre
    r"|\b(?:" + _MONTH_WORDS + r")\s+\d{1,2}(?:st|nd|rd|th)?,?\s+(?:19|20)\d{2}\b",       # December 10, 2026
    re.I)

_Q_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("DATE", _DATE_KIND_RE),
    ("CURRENCY", re.compile(
        r"[€$£]\s?\d[\d\s\u00A0.,]*(?:[km]|bn|md|mds|m€|k€)?|"
        r"\b\d[\d\s\u00A0.,]*\s?(?:€|\$|£|k€|m€|md€|eur(?:os)?)\b", re.I)),
    ("PERCENT", re.compile(r"\d+(?:[.,]\d+)?\s?(?:%|pts?\b|points?\b)", re.I)),
    ("RATIO", re.compile(r"(?<![\w.])[x×]\s?\d+(?:[.,]\d+)?\b|\b\d+(?:[.,]\d+)?\s?[x×](?![\w])", re.I)),
    ("RANGE", re.compile(r"\b\d[\d\s\u00A0.,]*\s?(?:[–\-—]|à|to)\s?\d[\d\s\u00A0.,]*\b")),
    ("FRACTION", re.compile(rf"\b\d+\s?/\s?\d+\b|[{_UNICODE_FRACTIONS}]")),
    ("MAGNITUDE", re.compile(r"(?<![\w./-])[+\-±]?\d+(?:[.,]\d+)?\s?(?:k|K|M|bn|Bn|Md|mds?)\b(?!\s?[€$£])")),
    ("CARDINAL", re.compile(r"(?<![\w./-])[+\-±]?\d[\d\s\u00A0.,]*\d(?![\w/])|(?<![\w./-])[+\-±]?\d(?![\w/])")),
    ("WORDNUM", re.compile(rf"(?<![\w-])(?:{_WORDNUM_FR}|{_WORDNUM_EN})(?![\w-])", re.I)),
    ("QUANTIFIER", re.compile(rf"\b(?:{_QUANTIFIER})\b", re.I)),
    # v62.13.9.4.32 (A) — un chiffre romain est un romain ENTIER et VALIDE :
    # l'ancienne forme acceptait une correspondance VIDE devant « MDD » (marque
    # de distributeur) et retenait « Négociations annuelles, concurrence MDD »
    # comme ligne chiffrée non étayée (run réel ee08f0). « II », « XII », « IV »
    # restent des romains ; « MDD », « CD » (compact disc), « DIV » ne le sont pas.
    ("ROMAN", re.compile(r"\b(?=[IVXLCDM]{2,7}\b)(?=[IVX])(?:X{0,3})(?:IX|IV|V?I{1,3}|V)\b|\b[VX]\b(?=\s+[a-zà-ÿ])")),
    ("MULT", re.compile(r"(?<![\w-])(?:doubl(?:er|era|erons|é|ée|és|ées)?|tripl(?:er|é|ée|és|ées)?|"
                        r"quadrupl(?:er|é)?|double[ds]?|doubling|triple[ds]?|halv(?:e|ed|ing))(?![\w-])", re.I)),
]

# « un/une/a/an/one » : quantité UNIQUEMENT en objet direct immédiat d'une
# tête verbale d'action (héritage 9.4.5) — géré au typage, pas à l'extraction
# générale, pour ne pas inonder les articles.

_ART_ONE_RE = re.compile(r"\b(un|une|a|an|one)\b", re.I)
_ONE_ABSTRACT = {
    "réflexion", "reflexion", "discussion", "démarche", "demarche", "étude", "etude", "analyse", "revue", "audit",
    "consultation", "négociation", "negociation", "procédure", "procedure", "approche", "stratégie", "strategie",
    "politique", "campagne", "mission", "plan", "programme", "projet", "processus", "cadre", "vision", "réunion",
    "reunion", "point", "atelier", "comité", "comite", "décision", "decision", "action", "priorité", "priorite",
    "phase", "étape", "etape", "option", "scénario", "scenario", "orientation", "trajectoire", "dynamique",
    "logique", "culture", "gouvernance", "organisation", "méthode", "methode", "méthodologie", "methodologie",
    "roadmap", "feuille", "initiative", "réponse", "reponse", "opportunité", "opportunite", "alternative",
    "hypothèse", "hypothese", "proposition", "recommandation", "synthèse", "synthese", "note", "annexe",
    # v62.13.9.4.15 — « Sécuriser un pipeline commercial » : l'article
    # désigne un flux, pas un compte (run réel du 02/09/2026 15:04).
    "pipeline", "portefeuille", "réseau", "reseau", "positionnement", "socle", "dispositif", "suivi",
    "section", "question", "enveloppe", "ambition", "objectif", "cible",
    "gamme", "offre", "calendrier", "niveau", "volume", "partie", "montant", "délai", "delai",
    "horizon", "dimensionnement", "quantum", "base", "baseline", "trajectoire",
    # v62.13.9.4.29 — « Définir une grille de TJM », « un tableau de bord » : un
    # instrument ou un livrable, pas un compte de un (run 08/09 11:34, arbitrage perdu).
    # v62.13.9.4.31 — contre-audit v30 (§3) : « Lancer un mini-site vitrine » — un
    # support ou un livrable numérique n'est pas un compte de un ; l'arbitrage qui
    # le contenait disparaissait de la synthèse. « Ouvrir un centre » reste un compte.
    "site", "mini-site", "minisite", "site web", "page", "profil", "compte", "blog", "newsletter",
    "landing", "vitrine", "plateforme", "portail", "espace", "canal", "website", "webpage",
    "grille", "tableau", "matrice", "registre", "charte", "modèle", "modele", "template", "outil",
    "référentiel", "referentiel", "dossier", "document", "convention", "kit", "guide", "trame",
    "protocole", "barème", "bareme", "tarification", "grid", "dashboard", "matrix", "register",
    "charter", "model", "tool", "repository", "file", "document", "guide", "protocol", "scale",
    "review", "study", "analysis", "discussion", "process", "plan", "programme", "program",
    "project", "strategy", "campaign", "consultation", "tender", "initiative", "approach",
    "framework", "roadmap", "policy", "procedure", "assessment", "meeting",
    "workshop", "committee", "method", "methodology", "response", "opportunity",
    "alternative", "hypothesis", "proposal", "recommendation", "summary",
}


@dataclass
class Quantity:
    start: int
    end: int
    raw: str
    kind: str
    qtype: str | None = None      # type whitelist attribué, sinon None


@dataclass
class LineVerdict:
    withhold: bool
    untyped: list[Quantity] = field(default_factory=list)
    typed: list[Quantity] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def as_residual(self, line: str) -> dict:
        return {
            "line": line,
            "engines": ["L"],
            "reason": ";".join(self.reasons) or "untyped_quantity",
            "quantities": [q.raw for q in self.untyped],
        }


# v62.13.9.4.30 — contre-audit croisé du 09/09 : « Robert Half, Michael Page,
# Delville » — « Half » était typé QUANTIFIER et l'action entière était retirée.
# Un mot capitalisé précédé d'un autre mot capitalisé (ou suivi d'un marqueur
# d'entité) appartient à un nom propre : il n'est jamais une quantité. Règle
# générique, sans liste de sociétés.
_PROPER_NOUN_SPAN = re.compile(
    r"\b(?<![.!?]\s)(?<!^)[A-ZÀ-Ÿ][\wÀ-ÿ\'’-]*[a-zà-ÿ][\wÀ-ÿ\'’-]*(?:\s+(?:&|de|du|des|van|von|di|la|le)?\s*[A-ZÀ-Ÿ][\wÀ-ÿ\'’-]*[a-zà-ÿ][\wÀ-ÿ\'’-]*)+(?:\s*(?:S\.?A\.?S?|SARL|SA|GmbH|Ltd|Inc|LLC|BV|NV|AG|SE|SCI|SNC)\b)?")


def _proper_noun_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _PROPER_NOUN_SPAN.finditer(str(text or ""))]


_ORDINAL_HEAD_RE = re.compile(
    r"\b(?:phases?|chapitres?|titres?|parties?|[ée]tapes?|axes?|volets?|tomes?|actes?|sections?|annexes?|"
    r"livres?|articles?|classes?|niveaux?|paliers?|vagues?|sc[ée]narios?|options?|piliers?|leviers?|"
    r"chapters?|parts?|stages?|steps?|tiers?|levels?|volumes?)\s*$", re.I)


def extract_quantities(text: str) -> list[Quantity]:
    value = str(text or "")
    taken: list[tuple[int, int]] = []
    out: list[Quantity] = []
    proper = _proper_noun_spans(value)      # v62.13.9.4.30
    for kind, rx in _Q_PATTERNS:
        for m in rx.finditer(value):
            s, e = m.span()
            if kind in ("QUANTIFIER", "WORDNUM", "ROMAN", "MULT") and any(ps <= s and e <= pe for ps, pe in proper):
                continue                    # v62.13.9.4.30 — dans un nom propre
            if kind == "ROMAN" and _ORDINAL_HEAD_RE.search(value[max(0, s - 24):s]):
                continue                    # v62.13.9.4.32 (A) — « phase II », « chapitre XII » : un rang, pas une grandeur
            if any(not (e <= ts or s >= te) for ts, te in taken):
                continue
            taken.append((s, e))
            out.append(Quantity(s, e, m.group(0), kind))
    out.sort(key=lambda q: q.start)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 2. TYPAGE — whitelist fermée
# ─────────────────────────────────────────────────────────────────────────────

_LEADING_TAG_RE = re.compile(
    r"^\s*[A-ZÀ-Ÿ][A-ZÀ-Ÿ_ÉÈÊÀÂÎÔÛ -]{2,24}\s*\|\s*")
_EVIDENCE_ROW_RE = re.compile(
    r"^[✅✔️\s]*(?:FACT|FAIT|CONFIRMED|CONFIRM[ÉE]E?|VALIDATED|VALID[ÉE]E?|"
    r"VERIFIED|V[ÉE]RIFI[ÉE]E?|APPROVED|APPROUV[ÉE]E?)\b[^|]*\|(?:[^|]*\|){2,}[^|]*"
    r"\b[\w~-]+\.(?:pdf|docx?|xlsx?|pptx?|xhtml|html)\b[^|]*\|\s*\d{1,4}\s*$",
    re.I,
)
# v62.13.9.4.6 — registre tri-state du produit (doctrine OCR gravée) : un
# statut de preuve fermé + ≥3 séparateurs de cellules = couche de preuve.
_TRISTATE_ROW_RE = re.compile(
    r"^[\s✅✔️🔍⚠️❌✗✓]*(?:FACT|FAIT|À V[ÉE]RIFIER|TO VERIFY|NON SOURC[ÉE]|UNSOURCED)\b"
    r"[^|]*\|(?:[^|]*\|){2,}", re.I)
# v62.13.9.4.30 — contre-audit croisé du 09/09 : les rangées de modèle (CA,
# EBITDA, EBIT, marge brute) sortaient des tableaux tandis que leurs résultats
# restaient — la prudence dégradait la vérifiabilité. La rangée d'un tableau
# commence par « | » et son étiquette peut être en gras : le motif l'accepte.
_ACCOUNTING_LABEL_RE = re.compile(
    r"^\s*(?:chiffre d['’]affaires|ca\b|charges?|co[ûu]ts?|dont\b|marge|ebit(?:da)?|"
    r"r[ée]sultat|amortissements?|provisions?|is\b|imp[ôo]ts?|capex|opex|bfr|"
    r"tr[ée]sorerie|cash[- ]?flow|dettes?|capitaux|effectifs?|masse salariale|"
    r"actif|passif|total actif|total passif|variation|stocks?|cr[ée]ances?|"
    r"march[ée]s?|markets?|secteurs?|segments?|demande|"
    r"immobilisations?|fonds propres|"
    r"revenue|sales|costs?|expenses?|gross margin|operating|net income|d&a|"
    r"depreciation|tax|headcount|free cash)", re.I)
# v62.13.9.4.30 — les rangées de MODÈLE (compte de résultat, flux) sortaient des
# tableaux tandis que leurs résultats restaient : leur étiquette est précédée de
# la barre du tableau et écrite en gras. Vocabulaire volontairement plus étroit
# que celui de la prose : un tableau de répartition (« Marché direct | 40 % »)
# n'est pas un modèle et reste jugé comme avant.
_ACCOUNTING_ROW_LABEL_RE = re.compile(
    r"^\s*[|▌]\s*\**\s*(?:chiffre d['’]affaires|ca\b|charges?|co[ûu]ts?|marge(?:\s+brute|\s+op[ée]rationnelle)?|"
    r"ebit(?:da)?|r[ée]sultat|amortissements?|provisions?|imp[ôo]ts?|is\b|capex|opex|bfr|"
    r"tr[ée]sorerie|cash[- ]?flow|flux|besoin cumul[ée]|dettes?|capitaux|fonds propres|"
    r"immobilisations?|actif|passif|stocks?|cr[ée]ances?|masse salariale|"
    r"revenue|sales|costs?|expenses?|gross margin|operating|net income|d&a|depreciation|tax|"
    r"free cash|working capital|cumulative)\b", re.I)
_MODEL_ROW_RE = re.compile(r"\|(?:[^|]*\|){2,}")
_TRISTATE_CELL_RE = re.compile(
    r"\|\s*(?:À V[ÉE]RIFIER|TO VERIFY|FACT|FAIT|NON SOURC[ÉE]|UNSOURCED|OK|✓|✗)\s*\|?\s*$", re.I)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
# v62.13.9.4.49 — année suivie (dans les trois mots) d'un nom d'horizon : c'est un horizon, pas un effectif
_HORIZON_NOUN_AFTER49 = re.compile(
    r"\s+(?:[\w’'-]+\s+){0,2}(?:targets?|goals?|objectives?|ambitions?|plans?|strateg(?:y|ies)|roadmaps?|budgets?|"
    r"forecasts?|outlook|agenda|vision|milestones?|objectifs?|cibles?|ambitions?|feuilles?\s+de\s+route|stratégies?|"
    r"prévisions?|jalons?|trajectoires?|horizon)\b", re.I)
# (conservé pour référence, plus utilisé : noms qui se comptent)
_COUNTED_NOUN_AFTER49 = re.compile(
    r"\s+(?:people|persons?|employees?|staff|hires?|FTEs?|heads?|workers?|engineers?|salespeople|units?|pieces?|items?|"
    r"products?|SKUs?|clients?|customers?|stores?|shops?|sites?|points?|users?|subscribers?|members?|tons?|tonnes?|beds?|"
    r"personnes?|salariés?|collaborateurs?|postes?|recrues?|ingénieurs?|commerciaux|unités?|pièces?|articles?|produits?|"
    r"références?|magasins?|boutiques?|utilisateurs?|abonnés?|membres?|lits?)\b", re.I)
_PERIOD_RE = re.compile(
    r"\b(?:FY|H[12]|[QT][1-4])\s?(?:19|20)?\d{2}\b|\b(?:19|20)\d{2}\s?[–\-—/]\s?(?:19|20)?\d{2}\b", re.I)
_FULLDATE_RE = re.compile(
    r"\b\d{1,2}(?:er)?\s+(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|"
    r"septembre|octobre|novembre|d[ée]cembre|january|february|march|april|may|june|"
    r"july|august|september|october|november|december)(?:\s+\d{4})?\b|"
    # v62.13.9.4.25 — « sept. 2026 » : abréviation de mois suivie d'une année,
    # jamais le mot-nombre sept (contre-audit v24 : « Échéance . 2026 »).
    r"\b(?:\d{1,2}(?:er)?\s+)?(?:janv|f[ée]vr?|avr|juil|sept?|oct|nov|d[ée]c|jan|feb|mar|apr|jun|jul|aug|sep)\.?\s+(?:19|20)\d{2}\b|"
    r"\b\d{2}[-/]\d{2}[-/]\d{2,4}\b|\b(?:19|20)\d{2}-\d{2}-\d{2}\b", re.I)
_GUIDED_IDENT_RE = re.compile(
    r"\b(?:sections?|pages?|p\.|chapitres?|chapters?|fig(?:ures?)?\.?|art(?:icles?)?\.?|"
    r"§|annexes?|appendix|slides?|lignes?|lines?|étapes?|steps?|voir|see|cf\.?|"
    r"(?:company\s+)?numbers?|num[ée]ros?)\s*n?[°o]?\s*\d+(?:\.\d+)*\b(?:\s*\(\d+\))?|"
    r"\b(?:industrie|industry|web)\s?\d\.\d\b|"
    r"\b(?:acier|steel|inox|aluminium|alliage|alloy|norme|grade)\s+\d+\b|"
    r"[\w-]*\d[\d\w.-]*\.(?:pdf|docx?|xlsx?|pptx?|csv|txt|json)\b", re.I)
_IDENT_RE = re.compile(
    # v62.13.9.4.26 — labels d'ordre des agents : « [n4] », « n4] », « A1. », « R2 — »
    r"\[\s*[nNdDaArR]?\s*\d{1,2}\s*\]|\(\s*[nN]\d{1,2}\s*\)|\b[nN]\d{1,2}\]|\b[ADRP]\d{1,2}(?=\s*[.:)—–-])|"
    r"\b[A-Za-zÀ-ÿ&]{3,}\s+\d\.0\b|"      # v62.13.9.4.27 — « industrie 4.0 » : nom de génération
    r"§\s*\d{1,3}\s*[—–-]?|"                    # v62.13.9.4.31 — numéro de rubrique du sommaire
    r"\bOptions?\s+\d{1,2}(?:\s*(?:vs\.?|/|,|et|ou|and|or|[-–]|\+|&)\s*(?:Options?\s+)?\d{1,2})+\b|"      # v62.13.9.4.28 — « Option 1 vs 2 vs 3 » : numéros d'options
    r"(?:\b(?:avant|le|au|dès|d['’]ici|jusqu['’]au|du|entre|pour le|à partir du|before|by|on|until)\s+\d{1,2}/\d{1,2}\b|\b(?:1[3-9]|2\d|3[01])/(?:0?[1-9]|1[0-2])\b|\b(?:0?[1-9]|[12]\d|3[01])/0[1-9]\b)(?!\s*/)|"      # v62.13.9.4.29 — « avant 20/09 » : date courte, pas une fraction
    r"\bT0\b|\b[TJM]\s?[+\-]\s?\d{1,3}(?:\s?(?:j|jours?|d|days?|m|mois|months?|s|semaines?|weeks?))?\b|"      # v62.13.9.4.29 — « T0 → T+90 jours » : repère de planning
    r"\b\d{9}\b|\b(?:n[°o]|no\.?|ref\.?|réf\.?)\s?\d+|\bv\d+(?:\.\d+)+|"
    r"\b[\w~-]+\.(?:pdf|docx?|xlsx?|pptx?|csv|txt|json|xhtml|html)\b|"
    r"^\d{1,2}(?:\.\d{1,2})+\s|\bISO\s?\d+|\b[A-Z]{1,4}[-_]?\d{2,}\b|"
    r"(?:Regulation|R[èe]glement|Directive)\s*\((?:EU|UE|EC|CE)\)\s*(?:n[°o]\s*)?\d{4}/\d+|"
    r"(?<=\|)\s*\d{1,4}\s*$|\bT\s?\d\b|\bT\s?\+\s?\d+\s?[dwma]?\b", re.I | re.M)
_SCORE_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s?/\s?(?:10|20|100)\b")
_SCORE_CTX_RE = re.compile(r"score|signal pondéré|confiance|maturité|maturity|confidence", re.I)
_DURATION_ATTR_RE = re.compile(
    r"\b\d+(?:\s?[-–\u2011]\s?\d+)?[\s\u2011–-]*(?:month|year|week|day|mois|ans?|semaines?|jours?)s?\b|"
    r"\b\d+\s(?:month|year|mois|ans?)s?\s(?:warranty|garantie|contract|contrat|plan|lease|bail)\b", re.I)
_SIRENE_BANDS = {"1–2", "3–5", "6–9", "10–19", "20–49", "50–99", "100–199",
                 "200–249", "250–499", "500–999", "1000–1999", "2000–4999",
                 "5000–9999", "1-2", "3-5", "6-9", "10-19", "20-49", "50-99",
                 "100-199", "200-249", "250-499", "500-999", "1000-1999",
                 "2000-4999", "5000-9999"}
_BAND_RE = re.compile(r"\b\d{1,4}\s?[–\-]\s?\d{1,4}\s?(?:salari[ée]s|employees?|collaborateurs?|employ[ée]s|personnes)\b", re.I)

_TIME_RE = re.compile(r"\b\d{1,2}[:h]\d{2}\b")
_DOC_APPARATUS_RE = re.compile(
    r"~?\s?\d[\d\s\u00A0]*\s?(?:tokens?|Ko|KB|Mo|MB|Go|GB|octets?|bytes?)\b|"
    r"\b(?:PJ|pi[èe]ces? jointes?|attachments?|annexes?)\s?:?\s?\d+|"
    r"\b\d+\s?(?:lignes?|lines?|slides?)\s+(?:sur|of|on)\s+\d+\b|"
    r"\b\d+\s+(?:of|sur|on)\s+\d+\s+(?:lignes?|lines?|slides?)\b|"
    r"\b\d+\s+(?:questions?|points?)\s+(?:ouvert|open)[\w]*\s+maximum\b|"
    r"\bmaximum\b.{0,12}\b\d+\b|"
    r"\b(?:hits|misses|size|evictions|entries)\s?=\s?\d+|"
    r"\b\d+\s+(?:page|à la page|sans page|indispo)|per-page|"
    r"\bcache\b.{0,40}\d|"
    r"\b\d+\s+(?:PDF|documents?|fichiers?|files?|slides?|PJ|emails?|feuilles?|sheets?)s?\b|"
    r"\b(?:up to|jusqu['’]à)\s+\d+\s+(?:open\s+)?questions?\b|"
    r"\b[a-z_]{2,}=\d+\b|\bpass\s+\d\s?/\s?\d\b", re.I)
_SCORING_LEXICON_RE = re.compile(
    r"alertes?|alerts?|score|grade|plafonn|capped|renseign[ée]|provided|"
    r"leviers?|levers?|m[ée]triques?|metrics?|sourc[ée]s|sourced|"
    r"brief|qualifi[ée]|cross-checked|recoup[ée]|solidit[ée]|"
    r"risques? identifi|impact|pond[ée]r|weight|matrice|"
    r"usefulness|utilit[ée]|non r[ée]solu|unresolved|d[ée]tect[ée]", re.I)
_SCORING_QTY_RE = re.compile(
    r"[+\-±(]\s?\d+(?:[.,]\d+)?\s?(?:pts?|points?)\b|\b\d+\s?/\s?\d+\b|"
    r"[≥≤>]\s?\d+|\b\d+\s+(?:\w+\s+){0,2}(?:alertes?|alerts?|orange|red)\b", re.I)
_LAW_REF_RE = re.compile(
    r"\b(?:art(?:icles?)?\.?|§)\s?\d+(?:\s?\(\d+\))?(?:\s?\d*)?\b|"
    r"\b(?:CR|report|rapport)\s?§\s?\d+\b|§\s?\d+\b", re.I)
_CHECKLIST_RE = re.compile(r"^[✓✔️☑️\s]*\d{1,2}[.)]\s")
# v62.13.9.4.17 — REGISTRE EMBARQUÉ DES SCÉNARIOS (contre-audit ChatGPT du
# 03/09/2026, point 7 — amendement de no_annex_exception du 30/08/2026). Une
# formulation chiffrée retirée du corps est conservée dans l'annexe, sous un
# TAG EXPLICITE que seul le rédacteur d'annexe produit et que la maintenance
# retire de tout texte de corps. Les quatre juges exemptent une ligne qui
# porte ce tag EN TÊTE (après l'identifiant SCN et le rôle) : l'original est
# lisible, son statut est dit, il n'est jamais une assertion du corps.
# v62.13.9.4.49 — doctrine du 28/09/2026 : plus rien ne sort du corps ; le registre liste les passages
# SIGNALÉS, qui restent en place. L'ancien libellé « hors corps / off-body » est devenu faux ; il reste
# reconnu (documents archivés) mais n'est plus produit.
# v62.13.9.4.49 — TITRES de l'annexe du registre, anciens et nouveaux, en un seul endroit : tout code qui délimite
# le corps ou vérifie la présence du registre doit reconnaître les deux (audit du 29/09/2026 : le renommage du titre
# avait cassé l'idempotence du registre et l'audit de qualité).
REGISTER_HEADINGS_RE = re.compile(r"Registre embarqué|Embedded register|Registre des passages signalés|"
                                  r"Register of flagged passages|Registre exhaustif|Exhaustive register")
SCN_REGISTER_TAG_FR = "[SIGNALÉ — en place, à vérifier]"
SCN_REGISTER_TAG_EN = "[FLAGGED — in place, to verify]"
_SCN_TAGS_ALT49 = (r"SC[ÉE]NARIO NON VALID[ÉE] — hors corps|UNVALIDATED SCENARIO — off-body|"
                   r"SIGNAL[ÉE] — en place, à vérifier|FLAGGED — in place, to verify")
SCN_REGISTER_TAG_RE = re.compile(
    r"^\s*(?:SCN-[\w-]+\s*(?:[·|]\s*[\w_ -]+?)?\s*[·|]\s*)?"
    r"\[(?:" + _SCN_TAGS_ALT49 + r")\]", re.I)


# v62.13.9.4.18 — BENCHMARK NON VÉRIFIÉ (contre-audit ChatGPT du 03/09/2026,
# point 6). Un chiffre de marché qui cite sa source (Xerfi, INSEE, baromètre…)
# sans URL ni extrait vérifiable dans le dossier n'est ni un fait prouvé ni
# une cible : il reste dans le corps sous l'étiquette explicite
# « [benchmark non vérifié — source citée sans URL] », posée par la
# maintenance seulement quand la ligne porte une source nommée.
BENCHMARK_MARK_FR = "[benchmark non vérifié — source citée sans URL]"
BENCHMARK_MARK_EN = "[unverified benchmark — source cited without URL]"
_BENCHMARK_MARK_RE = re.compile(r"\[(?:benchmark non v[ée]rifi[ée][^\]]*|unverified benchmark[^\]]*)\]", re.I)
_SOURCE_LABEL_RE = re.compile(
    r"\b(?:Xerfi|INSEE|Insee|Banque de France|Eurostat|Baromètre|Barometer|France Transition|Bluebirds|"
    r"Syntec|Apec|APEC|Pôle emploi|France Travail|Statista|McKinsey|BCG|Bain|Deloitte|KPMG|EY|PwC|"
    r"étude\s+[A-Z][\w-]+|rapport\s+[A-Z][\w-]+|Source\s*:\s*[A-Z][\w -]+|Sources?\s*:\s*[A-Z])", re.U)


def has_source_label(text: str) -> bool:
    return bool(_SOURCE_LABEL_RE.search(str(text or "")))


_URL_RE = re.compile(r"https?://\S+", re.I)


def is_url_sourced_line(text: str) -> bool:
    """v62.13.9.4.21 — une ligne (ou rangée) qui porte une URL de source ET un
    chiffre est une provenance vérifiable : « 800 M€ | 2023 | ✓ |
    https://www.francetransition.org/… ». Le tableau « Faits marché sourcés »
    du run réel 22:34 était neutralisé cellule par cellule alors que chaque
    rangée citait son URL."""
    s = str(text or "")
    return bool(_URL_RE.search(s)) and bool(re.search(r"\d", _URL_RE.sub(" ", s)))


def is_labelled_benchmark_line(text: str) -> bool:
    """Ligne étiquetée benchmark ET portant une source nommée — les deux ;
    ou ligne portant une URL de source (provenance vérifiable)."""
    s = str(text or "")
    if is_url_sourced_line(s):
        return True
    return bool(_BENCHMARK_MARK_RE.search(s)) and has_source_label(s)


def strip_benchmark_mark(text: str) -> str:
    return re.sub(r"\s*" + _BENCHMARK_MARK_RE.pattern + r"\s*", " ", str(text or ""), flags=re.I).strip()


_REGISTER_TECH_LINE_RE = re.compile(
    r"^\s*(?:Statut de preuve|Proof status|Source|Raison du retrait|Reason|Remplacement dans le corps|"
    r"Body replacement|Décision requise|Decision required|Remplacement ex[ée]cutif|Executive replacement|"
    r"Validation requise|Validation required)\s*:", re.I)


# v62.13.9.4.21 — MARQUEUR D'OUTIL STRUCTUREL (contre-audit ChatGPT du 05/09/2026,
# point 1 : « protéger par typage les contenus système »). Chaque paragraphe
# ou cellule que le PRODUIT écrit lui-même (version, scores, seuils, bandeaux,
# compteurs, en-têtes techniques, registre) porte en tête le caractère
# invisible U+2063 ; il est retiré de tout texte d'agent avant rendu. Un juge
# ne lit jamais une unité qui le porte : le produit ne se juge plus lui-même,
# par construction et non par inventaire de regex.
TOOL_MARK = "\u2063"


def mark_tool_text(text: str) -> str:
    s = str(text or "")
    return s if s.startswith(TOOL_MARK) else TOOL_MARK + s


def is_tool_marked(text: str) -> bool:
    return TOOL_MARK in str(text or "")


def strip_tool_mark(text: str) -> str:
    return str(text or "").replace(TOOL_MARK, "")


def mark_tool_paragraphs(doc, start_index: int = 0) -> int:
    """Marque tous les paragraphes (et cellules de tableaux) ajoutés à ``doc``
    depuis ``start_index`` paragraphes / la position courante des tableaux."""
    n = 0
    try:
        for p in list(doc.paragraphs)[start_index:]:
            if p.text and not p.text.startswith(TOOL_MARK):
                if p.runs:
                    p.runs[0].text = TOOL_MARK + p.runs[0].text
                else:
                    p.add_run(TOOL_MARK)
                n += 1
    except Exception:
        pass
    return n


# v62.13.9.4.21 — STATUT EN MARGE (décision Robin du 05/09/2026 : dans le
# document de travail, « rien n'est retiré, chaque chiffre porte son statut »).
# Une ligne dont le chiffre n'est pas étayé n'est plus réécrite dans le Word
# de travail : elle reçoit en fin de ligne un tag de statut, écrit par le seul
# produit (retiré de tout texte d'agent), que les juges du document de
# travail exemptent. Les rendus dérivés (synthétique, deck) RETIRENT le tag
# et appliquent la neutralisation : le chiffre non étayé ne s'y affiche pas.
STATUS_OPEN, STATUS_CLOSE = "⟨", "⟩"
_STATUS_TAG_RE = re.compile(r"\s*⟨\s*(?:statut|status)\s*:[^⟩]*(?:⟩|$)\s*", re.I)   # tolère un tag tronqué en fin de ligne

STATUS_LABELS_FR = {                       # v62.13.9.4.23 — libellés courts : ~3 pages de moins sur un CR de travail
    "declared_target": "cible déclarée — non étayée",
    "unsupported": "non étayé — à documenter",
    "market": "marché non sourcé",
    "trend": "tendance non établie",
    "collision": "valeur non établie",
}
STATUS_LABELS_EN = {
    "declared_target": "declared target — unsupported",
    "unsupported": "unsupported — to document",
    "market": "unsourced market figure",
    "trend": "trend not established",
    "collision": "value not established",
}


def status_tag(kind: str, lang: str = "fr") -> str:
    labels = STATUS_LABELS_EN if str(lang).lower().startswith("en") else STATUS_LABELS_FR
    word = "status" if str(lang).lower().startswith("en") else "statut"
    return f"{STATUS_OPEN}{word} : {labels.get(kind, labels['unsupported'])}{STATUS_CLOSE}"


_RENDERED_FLAG_RE49 = re.compile(r"⚠\s*(?:à vérifier|to verify)\s*—")


def is_status_tagged(text: str) -> bool:
    """Étiquette de statut, ou marqueur déjà rendu « ⚠ à vérifier — motif » (v62.13.9.4.49) : un passage
    signalé n'est jamais rejugé."""
    s = str(text or "")
    # v62.13.9.4.50 — une étiquette COUPÉE par la troncature d'une puce du deck (« … ⟨statut ») reste une étiquette :
    # le passage est signalé, jamais rejugé (chaîne deck d'un run réel du 30/09)
    return bool(_STATUS_TAG_RE.search(s) or _RENDERED_FLAG_RE49.search(s) or re.search(r"⟨\s*statu[ts]\b", s))


def strip_status_tags(text: str) -> str:
    return _STATUS_TAG_RE.sub(" ", str(text or "")).strip()


# v62.13.9.4.19.6 — RÉSERVE ÉPISTÉMIQUE : une ligne qui cite un chiffre entre
# guillemets POUR DIRE QU'IL N'EST PAS SOURCÉ (« ⚠️ Alerte méthodologique :
# plusieurs sources mentionnent « 450 M€ » … mais cette valeur n'est pas
# sourcée ») n'affirme pas ce chiffre : elle met en garde. Run réel du
# 04/09/2026 14:48. Conditions cumulatives : négation explicite du sourçage
# ET chiffre entre guillemets. « Objectif « 450 M€ » à vérifier » ne passe pas.
_EPISTEMIC_NEGATION_RE = re.compile(
    r"n['’]est\s+pas\s+sourc|non\s+sourc|pas\s+sourc|sans\s+source|aucune\s+source(?:\s+publique)?|"
    r"absence\s+de\s+donn[ée]e|pas\s+de\s+donn[ée]e|non\s+consolid|ne\s+fournit\s+(?:pas|aucun)|"
    r"ne\s+(?:doit|peut)\s+pas\s+[êe]tre\s+(?:repris|retenu|utilis)|n['’]est\s+pas\s+(?:v[ée]rifi|[ée]tay|confirm|document)|"
    r"not\s+sourced|unsourced|no\s+source|cannot\s+be\s+(?:verified|relied|used)|not\s+(?:verified|substantiated|documented)", re.I)
_QUOTED_FIGURE_RE = re.compile(
    r"[«\"“]\s*[^»\"”]*\d[^»\"”]*\s*[»\"”]"
    r"|\d[\d\s\u00a0.,]*\s*(?:M€|k€|Md€|€|%|M\$|bn)\s*\((?:19|20)\d{2}\)")   # v62.13.9.4.20.1 — « 800 M€ (2023) » daté


def is_epistemic_caveat_line(text: str) -> bool:
    s = str(text or "")
    return bool(_EPISTEMIC_NEGATION_RE.search(s)) and bool(_QUOTED_FIGURE_RE.search(s))


def is_tagged_register_line(text: str) -> bool:
    """Ligne du registre embarqué : tag explicite en tête (après SCN-id · rôle),
    ou ligne technique du registre (statut, source, raison, remplacement,
    décision) — v62.13.9.4.18.2 : ces lignes sont écrites par le rédacteur
    d'annexe, jamais par un agent, et ne portent pas de chiffre."""
    s = str(text or "")
    if SCN_REGISTER_TAG_RE.match(s):
        return True
    # une ligne technique n'est exemptée que sans chiffre : « Source : 800 M€ »
    # écrit par un agent reste jugé.
    return bool(_REGISTER_TECH_LINE_RE.match(s)) and not re.search(r"\d", s)


def strip_register_tag_from_body(text: str) -> str:
    """Le tag ne peut pas être posé par un agent : hors annexe, il est retiré."""
    return re.sub(r"\s*\[(?:" + _SCN_TAGS_ALT49 + r")\]\s*",
                  " ", str(text or ""), flags=re.I).strip()


_PLANNING_MARKERS_RE = re.compile(
    r"\b\d{1,2}/(?:19|20)\d{2}\b"                                                    # v62.13.9.4.19.5 — mois/année « dès 10/2026 »
    r"|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\s*[–\-—]\s*\d{1,2}/\d{1,2}(?:/\d{2,4})?"    # plage de dates
    r"|\b(?:semaines?|weeks?|jours?|days?|mois|months?)\s+\d{1,2}(?:\s*[–\-]\s*\d{1,2})?(?=[\s,;:)])"  # index de semaine/jour
    r"|\((?:priorit[ée]|priority)\s+\d{1,2}\)"                                          # (PRIORITÉ 1)
    r"|\bP\d{1,2}\b(?=\s*[|)\]]|\s*$)"                                                 # P1 en fin de cellule
    r"|^\|?\s*\d{1,3}\s*(?=\|)"                                                          # numéro de rangée « | 1 | … »
    r"|\b[JD]\s*[+\-]\s*\d{1,3}\b",                                                      # v62.13.9.4.21 — jalons relatifs J+30
    re.I)


_ORDINAL_LABEL_RE = re.compile(
    r"\b(?:zones?|options?|piliers?|pillars?|phases?|sc[ée]narios?|axes?|volets?|"
    r"lots?|étapes?|steps?|niveaux?|levels?|tiers?|risques?|risks?|actions?|"
    r"couches?|layers?|modules?|paliers?|strates?|"
    r"d[ée]cisions?|decisions?|jalons?|milestones?)\s+\d{1,2}\b", re.I)
_DEPT_RE = re.compile(r"\b(?:dans le|du)\s(\d{2,3})\b(?=\s|,|\.|$)")
_BARE_REF_RE = re.compile(r"^\s*\d{1,3}\s*$")
# v62.13.9.4.15 — numéro de section en tête de ligne : « ## 1. », « ### 2.1 »,
# « 4.3 Axe », « 1) », avec ou sans marqueur markdown. Exige une majuscule ou
# un marqueur de titre après le numéro pour ne pas capturer « 450 M€ … ».
# Contrat : un titre de section est un numéro suivi d'un MOT (≥ 3 lettres,
# marqueur gras ou guillemet), ou d'un point/parenthèse de numérotation.
# « 24 M€ », « 24 MW », « 5 » nu ne sont pas des titres — le corpus N5
# (« CONFIRMED | Budget cible | 24 M€ ») l'a rappelé au premier essai.
_SECTION_HEAD_RE = re.compile(
    r"^\s*(?:#{1,6}\s+(?:\d{1,2}(?:\.\d{1,2}){0,3})[.)]?(?=\s|$)"        # titre markdown : le # fait foi
    r"|(?:\d{1,2}(?:\.\d{1,2}){0,3})"
    r"(?:[.)]\s+|\s+(?=[\*«]|[A-ZÀ-Ÿ][A-Za-zÀ-ÿ'’-]{2,})))")
# v62.13.9.4.15 — code NAF/APE (« 70.22Z », « 7022Z ») : identifiant de
# registre, jamais une grandeur. « (70.22Z) » comptait comme « 70 ».
_NAF_CODE_RE = re.compile(r"\b\d{2}\.?\d{2}[A-Z]\b")
_DECISION_HEAD_RE = re.compile(
    r"^\s*[✓✔️☑️\s]*(?:\d{1,2}[.)]\s*)?(?:confirmer|valider|arbitrer|maintenir|"
    r"poursuivre|acter|approve|validate|confirm|maintain|continue|endorse)\b", re.I)

_STRUCT_NOUNS = (
    r"piliers?|axes?|volets?|parties?|sections?|chapitres?|phases?|étapes?|"
    r"sc[ée]narios?|options?|hypoth[èe]ses?|annexes?|indicateurs?|leviers?|d[ée]cisions?|recommandations?|"
    r"risques?|arbitrages?|signaux|chiffres?(?:-cl[ée]s)?|questions?|priorit[ée]s?|"
    r"pillars?|axes|parts?|sections?|chapters?|phases?|steps?|scenarios?|options?|indicators?|levers?|decisions?|recommendations?|"
    r"risks?|trade-?offs?|signals?|figures?|questions?|priorit(?:y|ies)"
)
_STRUCT_RE = re.compile(
    rf"\b(\d{{1,2}}|{_WORDNUM_FR}|{_WORDNUM_EN}|one|un|une)[-\s]+(?:{_STRUCT_NOUNS})\b|"
    rf"\b(?:{_STRUCT_NOUNS})\s*\(\s?\d{{1,2}}\s?[–\-]\s?\d{{1,2}}\s?\)", re.I)

# ── fait accompli ──
_FR_PAST_RE = re.compile(
    r"\b(?:a|ont|avait|avaient|s['’]est|se sont|fut|furent)\s+(?:été\s+)?\w+(?:é|ée|és|ées|i|ie|is|ies|u|ue|us|ues|t|te|ts|tes)\b|"
    r"\bont?\s+(?:atteint|réalisé|enregistré|généré|dégagé|réduit|augmenté|baissé|progressé|reculé)\b|"
    # v62.13.9.4.7 — imparfait (constat historique), hors conditionnel -rait
    r"\b\w{3,}(?<!r)(?:ait|aient)\b|"
    # passé simple usuel des verbes d'état et de mesure
    r"\b(?:atteignit|atteignirent|compta|comptèrent|fut|furent|eut|eurent|"
    r"ouvrit|ouvrirent|ferma|fermèrent|s['’]établit)\b", re.I)
_EN_PAST_RE = re.compile(
    r"\b(?:was|were|had|reached|hit|achieved|met|delivered|declined|increased|decreased|"
    r"dropped|fell|rose|grew|gained|lost|recorded|posted|generated|reduced|improved|"
    r"contracted|expanded|totalled|totaled|amounted)\b|"
    r"\b\w{3,}ed\b(?!\s+(?:to|by)\s+(?:rise|grow|increase|decline|fall|reach))", re.I)
_FUTURE_RE = re.compile(
    r"\b(?:will|would|shall|may|might|could|should|expected to|due to|set to|plans? to|"
    r"aims? to|targets?|forecast|guidance|projected|planned|scheduled|slated|targeted|"
    r"(?:are|is)\s+to\s+be|"
    r"envisaged|anticipated|intended|prévoit|prévu[es]?|prévues|planifi[ée]e?s?|"
    r"programmée?s?|envisag[ée]e?s?|visera?|"
    r"visons|viser|ambition|objectif de|attendu[es]?|devrait|devraient|va |vont )\b", re.I)
_POSTNOM_DONE_RE = re.compile(
    r"\b(?:r[ée]alis[ée]e?s?|effectu[ée]e?s?|achev[ée]e?s?|finalis[ée]e?s?|"
    r"livr[ée]e?s?|sign[ée]e?s?|ouverts?|ouvertes?|c[ée]d[ée]e?s?|"
    r"completed|closed|delivered|signed|opened|achieved|finalised|finalized|"
    r"refurbished|renovated|r[ée]nov[ée]e?s?|modernis[ée]e?s?|converted|"
    r"converti[es]?s?|restructured|restructur[ée]e?s?|tenu[es]{0,2}|"
    r"men[ée]e?s?|conduite?s?|organis[ée]e?s?|constat[ée]e?s?|"
    r"conducted|organi[sz]ed|held|recorded|observed)\b", re.I)
# v62.13.9.4.9 — participes d'ENGAGEMENT effectif : un chantier engagé,
# lancé ou démarré est un fait (« Programme 24-Month Reset engagé en 2025 »,
# témoin conservé du corpus n°2), MAIS seulement hors futur dominant : « le
# programme SERA lancé avec 20 centres » reste une projection.
# futur simple / périphrastique FR, absent de _FUTURE_RE (anglocentrée) —
# borné à la garde d'engagement pour ne pas déplacer les autres branches
_FR_FUTURE_AUX_RE = re.compile(
    r"\b(?:sera|seront|serai|seras|serons|serez|"
    r"devra|devront|va\s+[êe]tre|vont\s+[êe]tre|"
    r"prochainement|[àa]\s+venir)\b", re.I)
_ENGAGED_DONE_RE = re.compile(
    r"\b(?:engag[ée]e?s?|lanc[ée]e?s?|d[ée]marr[ée]e?s?|initi[ée]e?s?|"
    r"entam[ée]e?s?|amorc[ée]e?s?|"
    r"launched|started|initiated|begun|commenced|undertaken)\b", re.I)
_VARIATION_FACT_RE = re.compile(
    r"\b(?:down|up)\s+from\b|\(\s*(?:down|up)\b|\bvs\.?\s|"
    r"\bcontre\s+[€$£\d]|\ben\s+(?:baisse|hausse)\s+de\b|"
    r"\b(?:compression|contraction|[ée]rosion|erosion|d[ée]gradation)\b.{0,40}"
    r"\b(?:over|sur)\b|\bcomparable sales\b", re.I)
_IMPERATIVE_TARGET_RE = re.compile(r"^\s*(?:objectifs?|targets?|cibles?|goals?|plan)\s*(?:\d{4})?\s*:", re.I)


# ── v62.13.9.4.7 — autorité structurée (contre-audit 30/08/2026) ─────────────
# Une autorité est {value, unit, semantic_role}. Une valeur nue ne blanchit
# jamais : l'unité locale de la quantité doit être compatible avec l'unité de
# l'item d'autorité (MONTH n'autorise ni COUNT, ni CURRENCY, ni PERCENT).

_UNIT_MONTH_RE = re.compile(r"^\s*(?:mois|months?)\b", re.I)
_UNIT_YEAR_RE = re.compile(r"^\s*(?:ans?|ann[ée]es?|years?)\b", re.I)
_UNIT_DAY_RE = re.compile(r"^\s*(?:jours?|days?)\b", re.I)
_UNIT_WEEK_RE = re.compile(r"^\s*(?:semaines?|weeks?)\b", re.I)
_DATE_LIKE_RE = re.compile(
    r"^(?:19|20)\d{2}-\d{2}-\d{2}$|^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}$"
    # v62.13.9.4.32 (A) — « 2026-2028 », « 2026 à 2028 » : une plage d'années est une période
    r"|^(?:19|20)\d{2}\s?(?:[–\-—]|à|to)\s?(?:19|20)\d{2}$")


def local_quantity_unit(value: str, start: int, end: int, raw: str) -> str:
    """Unité sémantique locale d'une quantité dans sa ligne."""
    raw_c = raw.strip()
    if _DATE_LIKE_RE.match(raw_c):
        return "DATE"
    if "%" in raw_c or re.match(r"\s*%", value[end:]):
        return "PERCENT"
    if re.search(r"[€$£]|\b(?:EUR|USD|GBP)\b", raw_c) or re.match(
            r"\s*(?:[€$£]|M€|m€|k€|M\$|EUR\b|Md?€)", value[end:], re.I):
        return "CURRENCY"
    after = value[end:]
    if _UNIT_MONTH_RE.match(after):
        return "MONTH"
    if _UNIT_YEAR_RE.match(after):
        return "YEAR"
    if _UNIT_DAY_RE.match(after):
        return "DAY"
    if _UNIT_WEEK_RE.match(after):
        return "WEEK"
    m = re.match(r"\s*([a-zà-ÿA-ZÀ-Ÿ][\wà-ÿÀ-Ÿ'-]*)", after)
    if m:
        return "COUNT:" + m.group(1).lower()
    return "BARE"


def _authority_items(authority_values) -> list:
    """Normalise l'autorité reçue en items structurés.

    - dicts {value, unit, semantic_role} : pris tels quels ;
    - chaînes date-complète : unit=DATE (sans ambiguïté) ;
    - toute autre chaîne nue : IGNORÉE — une valeur sans unité ne peut
      rien autoriser (contrat 9.4.7 : {"24"} doit échouer).
    """
    items = []
    for it in authority_values or []:
        if isinstance(it, dict) and it.get("value") is not None:
            _it = dict(it)                                  # v62.13.9.4.48 — champs des cibles du brief conservés
            _it.update({
                "value": str(it.get("value")).strip(),
                "unit": str(it.get("unit") or "").upper(),
                "role": str(it.get("semantic_role") or it.get("role") or ""),
            })
            items.append(_it)
        else:
            s = str(it).strip()
            if _DATE_LIKE_RE.match(s):
                items.append({"value": s, "unit": "DATE", "role": "TARGET_END_DATE"})
    return items


def _authority_match(raw: str, unit: str, items: list) -> bool:
    raw_n = re.sub(r"[\s\u00A0]", "", raw).strip(".,;: ")
    for it in items:
        if re.sub(r"[\s\u00A0]", "", it["value"]) != raw_n:
            continue
        if it["unit"] == "DATE" and unit == "DATE":
            return True
        if it["unit"] in ("MONTH", "YEAR", "DAY", "WEEK") and unit == it["unit"]:
            return True
    return False


def registry_claims(result) -> list[dict]:
    """v62.13.9.4.12.5 — les FAITS DE REGISTRE deviennent des claims.

    Le run réel du 01/09/2026 portait dans son registre moteur
    ``Effectif | 0 salariés | Pappers | FAIT`` — un fait public, sourcé,
    vérifiable — tandis que ``numeric_support_claims`` était VIDE. Le fait
    existait et ne protégeait rien : l'export a été refusé sur « effectif
    0 salarié ».

    Le registre du moteur est alimenté par l'extraction sur pièces et sources
    officielles ; ses entrées confirmées sont donc des preuves au même titre
    qu'un claim canonique. On les convertit, avec leur provenance — ce qui
    reste conforme à la doctrine : ce n'est pas une déclaration d'agent qui
    blanchit, c'est une pièce.
    """
    res = result if isinstance(result, dict) else {}
    facts = ((res.get("financial_facts_table") or {}).get("facts")) or []
    # l'entité du run, pour que le claim porte la SOCIÉTÉ et non sa source :
    # « Pappers » est une pièce, pas une entreprise.
    _entity = str(res.get("target_entity") or res.get("chosen_entity")
                  or res.get("company_name") or "").strip()
    out: list[dict] = []
    for f in facts:
        if not isinstance(f, dict):
            continue
        status = str(f.get("status") or "").upper()
        source = str(f.get("source_doc") or "").strip()
        value = str(f.get("value") or "").strip()
        label = str(f.get("label") or "").strip()
        # v62.13.9.4.48 — libellé AFFICHÉ dans la langue du run ; « label » reste la clé d'appariement
        try:
            from utils.financial_facts_table import monolingual_metric_label as _mml48
            _disp48 = _mml48(label, str(res.get("lang") or res.get("language") or "fr"))
        except Exception:
            _disp48 = label
        if not (value and label and source):
            continue
        if "FAIT" not in status and "CONFIRM" not in status:
            continue
        # v62.13.9.4.29 — audit du dossier industriel v28 : « Effectif déclaré : Entre
        # 500 et 999 salariés » avait été normalisé « 999 salariés » — la borne haute
        # d'une tranche n'est pas un dénombrement. Le claim porte la tranche telle
        # que l'extrait source l'écrit ; la borne haute reste la valeur normalisée.
        _src = " ".join(str(f.get(k) or "") for k in ("source_excerpt", "source_value_text"))
        _mb = re.search(r"(?i)(?:entre|between)\s+(\d[\d\s\u00A0]*)\s+(?:et|and|à)\s+(\d[\d\s\u00A0]*)\s*(?:salari|employ|personnes|collaborat|people|staff)", _src)
        if _mb and str(f.get("metric_canonical_id") or "").upper() == "HEADCOUNT":
            _lo = re.sub(r"\s", "", _mb.group(1)); _hi = re.sub(r"\s", "", _mb.group(2))
            _nm = re.search(r"\d[\d\s\u00A0.,]*", value)
            _noun = re.search(r"[a-zà-ÿ]{4,}", value[_nm.end():] if _nm else "", re.I)
            value = f"{_lo}–{_hi} {(_noun.group(0) if _noun else 'salariés')} (tranche)"
        m = re.search(r"-?\d[\d\s\u00A0.,]*", value)
        if not m:
            continue
        try:
            nv = float(re.sub(r"[^\d.-]", "", m.group(0).replace(",", ".")) or "0")
            if _mb and "(tranche)" in value:
                nv = float(re.sub(r"[^\d]", "", _mb.group(2)) or nv)      # borne haute = valeur normalisée
        except ValueError:
            continue
        # le libellé du registre et le mot du document diffèrent souvent —
        # « Effectif » côté registre, « salariés » dans la phrase. On fait
        # donc porter au claim le nom d'unité de sa propre valeur, sans quoi
        # la liaison échoue sur un synonyme (cas mesuré au run du 01/09).
        _unit_noun = re.search(r"[a-zà-ÿ]{4,}", value[m.end():] or "", re.I)
        _metric = label if not _unit_noun else f"{label} {_unit_noun.group(0)}"
        out.append({
            "claim_id": f"REGISTRY-{len(out) + 1:03d}",
            "claim_type": "FACT",
            "proof_status": "CONFIRMED_ON_PAGE",
            "label": label,
            "metric": _metric,
            "metric_id": label.upper().replace(" ", "_"),
            "value": value,
            "display_value": value,
            "normalized_value": nv,
            "source_doc": source,
            "source_page": str(f.get("source_page") or "registre"),
            "period": str(f.get("period") or ""),
            "scope": str(f.get("scope") or ""),
            "entity": _entity,
            "executive_line": (f"{_entity} — {_disp48} : {value}" if _entity
                               else f"{_disp48} : {value}"),
            "compact_executive_line": f"{_disp48} : {value}",
        })
    return out


def build_authority_items(result) -> list:
    """Producteur commun : items d'autorité structurés depuis un run."""
    items: list = []

    def _add_months(v) -> None:
        try:
            m = int(float(v))
        except Exception:
            return
        if 1 <= m <= 120:
            items.append({"value": str(m), "unit": "MONTH",
                          "semantic_role": "STRATEGIC_HORIZON"})

    def _add_date(v) -> None:
        s = str(v or "").strip()
        if not s:
            return
        items.append({"value": s, "unit": "DATE",
                      "semantic_role": "TARGET_END_DATE"})
        m = re.fullmatch(r"((?:19|20)\d{2})-(\d{2})-(\d{2})", s)
        if m:
            y, mo, d = m.groups()
            for var in (f"{d}/{mo}/{y}", f"{d}-{mo}-{y}", f"{d}.{mo}.{y}"):
                items.append({"value": var, "unit": "DATE",
                              "semantic_role": "TARGET_END_DATE"})

    try:
        top = (result or {}).get("strategic_horizon")
        if isinstance(top, dict):
            for key in ("explicit_months", "months", "horizon_months"):
                if top.get(key) is not None:
                    _add_months(top.get(key))
            _add_date(top.get("target_end_date"))
        elif top is not None:
            _add_months(top)
        for row in (result or {}).get("diagnostics_attempts") or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("role") or "") == "strategic_horizon":
                for key in ("explicit_months", "months", "horizon_months"):
                    if row.get(key) is not None:
                        _add_months(row.get(key))
                _add_date(row.get("target_end_date"))
    except Exception:
        pass
    # v62.13.9.4.48 — point 4 : les CIBLES DU BRIEF entrent au référentiel d'autorité. Le registre ne
    # les type « cible du brief » que sous un cadre de cible et hors passé factuel : présentée comme
    # atteinte, une valeur du brief reste un chiffre non étayé.
    try:
        from utils.declared_quantities import brief_declared_targets as _bdt48
        items.extend(_bdt48(result))
    except Exception:
        pass
    return items


# ── v62.13.9.4.7 — signaux de cible et de projection (primauté absolue) ──────
# Un signal de cible interdit les qualifications AUTHORITY, ACCOMPLISHED_FACT,
# METHOD_SCORE et les statifs sur la ligne : une cible reste une cible.
_TARGET_SIGNAL_RE = re.compile(
    r"\b(?:objectifs?|cibles?|ambitions?|targets?|goals?|"
    r"viser|visons|visez|vise|aspire|aspirons|aspirez|aspires?\s+to|"
    r"recommand\w*|recommend\w*|"
    r"souhait[ée]e?s?|pr[ée]vu(?:e?s)?\s*:|attendu[es]?\s*:|expected\s*:|"
    r"should\s+reach|to\s+be\s+reached|cap\s*:|vers\s+\d|à\s+terme|"
    r"aim(?:s|ed|ing)?\s+(?:for|at|to)|striv(?:e|es|ing)\s+(?:for|to)|"
    r"seek(?:s|ing)?\s+to|intend(?:s|ing)?\s+to|plan(?:s|ning)?\s+to|"
    r"committed\s+to\s+\d|tend(?:re|ons|ez)?\s+vers|en\s+route\s+(?:vers|pour)|"
    r"d['\u2019]ici\s+(?:20\d{2}|fin)|by\s+(?:FY)?20\d{2}|"
    r"(?:à|to)\s+(?:ouvrir|cr[ée]er|recruter|lancer|d[ée]ployer|construire|"
    r"livrer|atteindre|r[ée]aliser|open|create|hire|launch|build|deploy|"
    r"deliver|reach|achieve))\b",
    re.I)
_PLAN_SUBJECTS = (
    r"plans?|roadmaps?|feuilles?\s+de\s+route|programmes?|projets?|"
    r"trajectoires?|sch[ée]mas?\s+directeurs?|backlogs?|initiatives?")
_PLAN_VERBS = (
    r"comportent?|contien(?:t|nent)|contains?|includes?|pr[ée]voi(?:t|en)t?|"
    r"compte(?:nt)?|counts?|comprend(?:ent)?|comprises?|int[èe]gre(?:nt)?|"
    r"couvre(?:nt)?|covers?|liste(?:nt)?|lists?|recense(?:nt)?|features?")
_PLAN_CONTENT_RE = re.compile(
    rf"\b(?:{_PLAN_SUBJECTS})\b.{{0,40}}?\b(?:{_PLAN_VERBS})\b"
    rf"|\b(?:{_PLAN_VERBS})\b.{{0,40}}?\b(?:{_PLAN_SUBJECTS})\b",
    re.I | re.S)


# ── v62.13.9.4.9 — inversion de la charge sur les phrases de plan ──
# Contre-audit 30/08/2026 (P1-948-01) : la grille sujet × verbe des cycles
# précédents était une liste fermée ; il y aura toujours un verbe de plus
# (« regroupe », « possède », « owns », « has », « includes »). La charge
# est donc inversée : dès que le SUJET de la phrase est un artefact de
# planification, ou que la phrase porte une volition, ou que sa grandeur est
# qualifiée de future, TOUTE grandeur non exemptée de la phrase est
# prospective — quel que soit le verbe, y compris un verbe statif.
# Le garde-fou reste le passé factuel réel (« le programme A LIVRÉ 12
# centres en 2024 » demeure un fait), appliqué par les appelants.
_PLAN_ARTEFACTS = (
    r"plans?|business\s+plans?|strat[ée]gies?|strategy|strategies|"
    r"programmes?|programs?|projets?|projects?|roadmaps?|"
    r"feuilles?\s+de\s+route|trajectoires?|trajector(?:y|ies)|"
    r"sch[ée]mas?\s+directeurs?|backlogs?|initiatives?|"
    r"visions?|ambitions?|sc[ée]narios?|scenarios?|"
    r"mod[èe]les?\s+(?:futurs?|cibles?)|future\s+models?|target\s+models?|"
    r"d[ée]marches?|dispositifs?|chantiers?|transformations?|"
    r"blueprints?|frameworks?")
# v62.13.9.4.10 — un sujet QUALIFIÉ par un complément de croissance ou de
# transformation est un artefact de planification quel que soit son nom de
# tête (« le portefeuille D'EXPANSION », « the EXPANSION portfolio »). Les
# noms de tête forment une famille inépuisable ; les qualificatifs, non —
# c'est ce qui rend la règle tenable sans dictionnaire à rallonge.
_GROWTH_QUALIFIER_RE = re.compile(
    r"\b(?:d['\u2019](?:expansion|extension)|de\s+(?:croissance|"
    r"d[ée]veloppement|transformation|d[ée]ploiement|mont[ée]e\s+en\s+"
    r"(?:gamme|puissance))"
    r"|\b(?:expansion|growth|development|transformation|scale[-\s]?up|"
    r"roll[-\s]?out|ramp[-\s]?up)\s+"
    r"(?:portfolios?|pipelines?|plans?|programmes?|programs?|"
    r"portefeuilles?|strategies|strategy))\b", re.I)

_PLAN_SUBJECT_RE = re.compile(
    rf"(?:^|[\u2022\-–—:;(]|\b(?:le|la|les|l['\u2019]|notre|nos|ce|cette|ces|"
    rf"son|sa|ses|leur|leurs|the|our|this|these|its|their)\s+)"
    rf"(?:[a-z\u00e0-\u00ff]+\s+){{0,2}}?(?:{_PLAN_ARTEFACTS})\b", re.I)
_VOLITION_RE = re.compile(
    r"\b(?:veux|veut|voulons|voulez|veulent|vouloir|"
    r"souhaite|souhaites|souhaitons|souhaitez|souhaitent|souhaiter|"
    r"d[ée]sire|d[ée]sires|d[ée]sirons|d[ée]sirez|d[ée]sirent|"
    r"wants?|wanting|wish(?:es|ing)?|desires?|desiring)\b", re.I)
_FUTURE_QUALIFIER_RE = re.compile(
    r"\b(?:futur|future|futurs|futures|d[ée]sir[ée]e?s?|souhait[ée]e?s?|"
    r"envisag[ée]e?s?|projet[ée]e?s?|pr[ée]visionnels?|pr[ée]visionnelles?|"
    r"[àa]\s+venir|upcoming|desired|intended|planned|prospective)\b", re.I)
# zone du sujet : un artefact de planification n'inverse la charge que s'il
# gouverne la phrase (tête de proposition), pas s'il est un complément
# lointain (« … dans le cadre du plan » n'est pas une phrase de plan).
_PLAN_SUBJECT_ZONE = 60


# ── v62.13.9.4.10 — deux règles STRUCTURELLES, pas deux listes de mots ──
#
# Contre-audit 31/08/2026 : douze formulations ordinaires passaient encore.
# Elles ne forment que deux classes, et chacune se ferme par une règle de
# structure — c'est la sortie de la boucle « une version apprend un verbe,
# la suivante en manque un autre ».
#
# (a) AUTORITÉ DÉCISIONNAIRE. « Le conseil a validé 24 M€ de budget »,
#     « The board selected 15 openings » : le passé porte sur l'ACTE DE
#     DÉCIDER, pas sur la grandeur. Une instance qui décide engage l'avenir ;
#     le temps du verbe ne transforme pas une décision en constat. Le passé
#     factuel ne doit donc PAS exempter ces lignes.
_DECISION_BODY_RE = re.compile(
    r"\b(?:le\s+|la\s+|les\s+|notre\s+|nos\s+|the\s+|our\s+)?"
    r"(?:conseils?(?:\s+d['\u2019]administration)?|comit[ée]s?(?:\s+ex[ée]cutifs?)?|"
    r"comex|codirs?|directions?(?:\s+g[ée]n[ée]rales?)?|"
    r"assembl[ée]es?|actionnaires|gouvernances?|"
    r"boards?|committees?|management|executives?|shareholders?|"
    r"steering\s+committees?|leadership)\b", re.I)
_DECISION_ACT_RE = re.compile(
    r"\b(?:valid[ée]\w*|retenu\w*|approuv[ée]\w*|arr[êe]t[ée]\w*|adopt[ée]\w*|"
    r"ent[ée]rin[ée]\w*|vot[ée]\w*|d[ée]cid[ée]\w*|s[ée]lectionn[ée]\w*|"
    r"allou[ée]\w*|octroy[ée]\w*|mandat[ée]\w*|"
    r"approved?|approves|selected?|selects|validated?|adopted?|endorsed?|"
    r"ratified?|decided?|allocated?|mandated?|greenlit|signed\s+off|"
    r"expects?|expected|requires?|required)\b", re.I)
_DECISION_ZONE = 60

# (b) PRÉDICAT D'ASSIGNATION. « Le plafond est fixé à 8/10 », « The plan is
#     sized for 30 hires », « Maturity aspiration: 8/10 » : la grandeur est
#     POSÉE par quelqu'un, pas OBSERVÉE. Contrairement aux sujets (famille
#     ouverte, inépuisable), les prédicats d'assignation forment une classe
#     fermée et petite dans les deux langues — c'est ce qui rend la règle
#     tenable au lieu d'un dictionnaire à rallonge.
_ASSIGNMENT_PREDICATE_RE = re.compile(
    r"\b(?:est|sont|a\s+[ée]t[ée]|ont\s+[ée]t[ée])\s+"
    r"(?:fix[ée]e?s?|d[ée]fini[es]?s?|calibr[ée]e?s?|dimensionn[ée]e?s?|"
    r"plafonn[ée]e?s?|port[ée]e?s?|arr[êe]t[ée]e?s?|[ée]tabli[es]?s?)\b"
    r"|\b(?:is|are|has\s+been|have\s+been|was|were)\s+"
    r"(?:set|fixed|calibrated|sized|capped|pegged|targeted|scoped|budgeted)\b"
    # NB : « cap », « seuil », « plafond » et « threshold » nus sont EXCLUS —
    # ils désignent aussi l'appareil de notation du produit (« cap brief :
    # 70/100 »). Le plafond réellement cible est déjà pris par sa
    # construction (« le plafond … EST FIXÉ à »). Ne restent que les termes
    # sans double emploi.
    r"|\b(?:aspirations?|ambitions?\s+chiffr[ée]es?)\b", re.I)


def _decision_authority_signal(value: str) -> bool:
    """Une instance décisionnaire qui statue engage l'avenir, quel que soit
    le temps du verbe."""
    text = str(value or "")
    m = _DECISION_BODY_RE.search(text)
    if not m or m.start() >= _DECISION_ZONE:
        return False
    if not _DECISION_ACT_RE.search(text):
        return False
    # Une instance qui approuve un plan de 24 mois décide le PLAN ; la durée
    # en est l'horizon, pas la grandeur engagée. Si la ligne ne porte que des
    # durées, la règle d'autorité ne s'applique pas — sinon « KPI :
    # Board-approved 24-month plan » deviendrait une cible chiffrée.
    nums = re.findall(r"\d+(?:[.,]\d+)?\s*[-\s]?[a-zà-ÿ%€£$]*", text, re.I)
    if nums and all(
            re.search(r"(?:jours?|mois|semaines?|ans?|ann[ée]es?|trimestres?|"
                      r"days?|months?|weeks?|years?|quarters?)", n, re.I)
            for n in nums if re.search(r"\d", n)):
        return False
    return True


def _plan_frame_signal(value: str) -> bool:
    """Cadre de planification : sujet-artefact-de-plan, volition, ou
    grandeur qualifiée de future."""
    text = str(value or "")
    if _VOLITION_RE.search(text) or _FUTURE_QUALIFIER_RE.search(text):
        return True
    if _ASSIGNMENT_PREDICATE_RE.search(text):
        return True
    g = _GROWTH_QUALIFIER_RE.search(text)
    if g and g.start() < _PLAN_SUBJECT_ZONE:
        return True
    m = _PLAN_SUBJECT_RE.search(text)
    return bool(m and m.start() < _PLAN_SUBJECT_ZONE)


def line_has_target_signal(value: str, context=None) -> bool:
    """Signal de cible : analyse textuelle, ÉTENDUE par les grandeurs que les
    agents ont déclarées prospectives (v62.13.9.4.11, chantier A1).

    L'union est à sens unique. Une déclaration ajoute un signal — elle n'en
    retire jamais : un agent qui déclarerait « FAIT » ne peut pas éteindre
    l'analyse textuelle, sans quoi il pourrait s'auto-blanchir. Sans
    déclaration, le comportement est exactement celui du cycle précédent.

    C'est ce canal qui rend la FORMULATION secondaire : « Notre portefeuille
    intègre désormais 24 M€ » n'est couverte par aucune règle lexicale, mais
    la valeur a été déclarée CIBLE à la génération.
    """
    if (_TARGET_SIGNAL_RE.search(value)
            or _PLAN_CONTENT_RE.search(value)
            or _plan_frame_signal(value)
            or _decision_authority_signal(value)):
        return True
    if context is not None:
        try:
            # v62.13.9.4.12 — l'index LOCALISÉ tranche : une déclaration ne
            # vaut que pour sa métrique, sa période et son entité. La
            # comparaison par valeur nue du cycle précédent contaminait les
            # faits légitimes portant le même nombre.
            from utils.declared_quantities import declared_index
            idx = declared_index(context)
            if idx and idx.line_has_declared_target(value):
                return True
        except Exception:
            pass
    return False


def _normalize_amount(raw: str) -> str:
    return re.sub(r"[\s\u00A0,]", "", raw).strip("≈~+±(). ").lower()


def _claim_amounts(claims) -> frozenset:
    # v62.13.9.4.22 — la clé de cache était ``id(claims)`` : un identifiant
    # d'objet réutilisé après ramasse-miettes servait la liste d'un AUTRE run
    # (aléas de suite « dossier anglophone coté », « campagne 4.8 » — et, en production, un
    # jugement porté avec les claims d'un dossier précédent dans le même
    # processus). La clé est désormais le CONTENU.
    try:
        key = (len(claims or []), hash(tuple(str(c) for c in (claims or []))))
    except Exception:
        key = None
    cached = _CLAIM_AMOUNT_CACHE.get(key) if key is not None else None
    if cached is not None:
        return cached
    amounts: set[str] = set()
    try:
        for claim in claims or []:
            # v62.13.9.4.12 — STATUT PROBATOIRE EXIGÉ. Ce jeu de montants
            # autorise l'affichage d'une valeur nue : il ne doit contenir que
            # des grandeurs réellement certifiées. Il acceptait n'importe
            # quel claim, y compris un « claim_type: FACT » auto-déclaré —
            # dernier repli résiduel du runtime, relevé au contre-audit du
            # 31/08/2026 (P1 CLAIM-FALLBACK).
            if isinstance(claim, dict):
                _st = str(claim.get("proof_status") or "").upper().strip()
                if _st not in ("CONFIRMED_ON_PAGE",
                               "DERIVED_FROM_CONFIRMED_ON_PAGE"):
                    continue
            blob = " ".join(str(claim.get(k) or "") for k in (
                "value", "amount", "compact_executive_line", "display_value",
                "raw_value", "metric_value")) if isinstance(claim, dict) else str(claim)
            for m in re.finditer(r"[€$£]\s?\d[\d\s\u00A0.,]*m?n?|\d+(?:[.,]\d+)?\s?%|"
                                 r"\d[\d\s\u00A0.,]*\s?(?:M€|k€|m€|bn|Md€?)", blob):
                amounts.add(_normalize_amount(m.group(0)))
    except Exception:
        pass
    result = frozenset(amounts)
    if key is not None:
        if len(_CLAIM_AMOUNT_CACHE) > 512:
            _CLAIM_AMOUNT_CACHE.clear()
        _CLAIM_AMOUNT_CACHE[key] = result
    return result


_CLAIM_AMOUNT_CACHE: dict = {}


def _current_year(context) -> int:
    if context and context.get("current_year"):
        return int(context["current_year"])
    return _dt.date.today().year


_NON_FACT_PARTICIPLES = {
    "recommended", "proposed", "suggested", "advised", "expected", "intended",
    "projected", "targeted", "planned", "scheduled", "designed", "aimed",
    "required", "needed", "assumed", "estimated", "modelled", "modeled",
    "recommandé", "recommandée", "recommandés", "recommandées", "proposé",
    "proposée", "proposés", "proposées", "suggéré", "suggérée", "envisagé",
    "envisagée", "envisagés", "envisagées", "visé", "visée", "visés", "visées",
    # v62.13.9.4.9 — participes de VOLITION : « desired », « souhaité »
    # décrivent un vouloir, jamais un fait accompli (contre-audit
    # 30/08/2026 : « The desired maturity level is 8/10 » se blanchissait
    # en fait passé parce que « desired » finit par -ed).
    "desired", "wanted", "wished", "anticipated", "hoped", "sought",
    "souhaité", "souhaitée", "souhaités", "souhaitées",
    # v62.13.9.4.10 — participes d'ASSIGNATION : « is calibrated for »,
    # « est fixé à » décrivent une valeur POSÉE, pas OBSERVÉE. Les compter
    # comme passé factuel blanchissait « The plan is sized for 30 hires ».
    "set", "fixed", "calibrated", "sized", "capped", "pegged", "scoped",
    "budgeted", "fixé", "fixée", "fixés", "fixées", "défini", "définie",
    "définis", "définies", "calibré", "calibrée", "calibrés", "calibrées",
    "dimensionné", "dimensionnée", "dimensionnés", "dimensionnées",
    "plafonné", "plafonnée", "plafonnés", "plafonnées",
    "désiré", "désirée", "désirés", "désirées", "voulu", "voulue",
    "voulus", "voulues", "espéré", "espérée", "espérés", "espérées",
    # v62.13.9.4.11 — participes de PRÉFÉRENCE (« the preferred scenario »)
    # et d'AFFECTATION (« the envelope allocated to the plan ») : choisir ou
    # affecter n'est pas constater. Comptés comme passé factuel, ils
    # blanchissaient deux cibles du corpus aveugle du 31/08/2026.
    "preferred", "favoured", "favored", "chosen", "shortlisted",
    "allocated", "earmarked", "reserved", "dedicated", "assigned",
    "granted", "attributed", "apportioned", "ring-fenced",
    "privilégié", "privilégiée", "privilégiés", "privilégiées",
    "alloué", "allouée", "alloués", "allouées",
    "affecté", "affectée", "affectés", "affectées",
    "attribué", "attribuée", "attribués", "attribuées",
    "réservé", "réservée", "réservés", "réservées",
    "dédié", "dédiée", "dédiés", "dédiées",
}


# v62.13.9.4.11 — ÉTAT PASSÉ et VARIATION CONSTATÉE. Le contre-audit du
# 31/08/2026 a censuré trois faits parfaitement ordinaires — « l'effectif est
# passé de 200 à 220 personnes », « la marge était de 8 % en FY2025 », « the
# 2025 budget stood at £4m » — parce qu'aucun motif ne reconnaissait la
# copule d'état au passé ni la tournure de variation. Ce sont les formes les
# plus banales du récit financier ; leur absence rendait le produit
# censurant sur son propre terrain.
_STATE_PAST_RE = re.compile(
    r"\b(?:[ée]tai(?:t|ent)|fut|furent|"
    r"s['’]?[ée]levai(?:t|ent)|atteignai(?:t|ent)|comptai(?:t|ent)|"
    r"repr[ée]sentai(?:t|ent)|affichai(?:t|ent)|ressortai(?:t|ent)|"
    r"se\s+montai(?:t|ent)|s['’]?[ée]tablissai(?:t|ent)|"
    r"(?:est|sont|a|ont)\s+pass[ée]e?s?\s+(?:de|à)|"
    r"a\s+(?:progress[ée]|recul[ée]|augment[ée]|diminu[ée]|baiss[ée]|cr[ûu])|"
    r"stood\s+at|amounted\s+to|totall?ed|came\s+in\s+at|"
    r"went\s+from|moved\s+from|rose\s+(?:to|from)|fell\s+(?:to|from))\b",
    re.I)


def _has_factual_past(value: str, lang: str) -> bool:
    rxs = [_FR_PAST_RE, _EN_PAST_RE] if lang.startswith("fr") else [_EN_PAST_RE, _FR_PAST_RE]
    for rx in rxs:
        for m in rx.finditer(value):
            token = m.group(0).split()[-1].lower().strip(".,;:")
            if token in _NON_FACT_PARTICIPLES or re.fullmatch(r"un\w+ed", token) \
                    or re.fullmatch(r"non[-\s]?valid[ée]e?s?", token):
                continue
            return True
    if (_POSTNOM_DONE_RE.search(value) or _VARIATION_FACT_RE.search(value)
            or _STATE_PAST_RE.search(value)):
        return True
    # engagement effectif : fait seulement si aucun marqueur de futur ne
    # domine la ligne (v62.13.9.4.9)
    return bool(_ENGAGED_DONE_RE.search(value)
                and not _FUTURE_RE.search(value)
                and not _FR_FUTURE_AUX_RE.search(value))


def _line_is_accomplished(value: str, lang: str, context) -> bool:
    """Assertion au passé, période close, aucun marqueur de futur dominant."""
    if _FUTURE_RE.search(value):
        return False
    if _IMPERATIVE_TARGET_RE.search(value):
        return False
    years = [int(y) for y in _YEAR_RE.findall(value)]
    years += [int(m) for m in re.findall(r"\b(?:FY|H[12]|[QT][1-4])\s?((?:19|20)\d{2})\b", value, re.I)]
    cy = _current_year(context)
    if any(y > cy for y in years):
        return False
    if not _has_factual_past(value, lang):
        return False
    # période close exigée : une année/exercice ≤ courant, ou marqueur explicite
    if years and all(y <= cy for y in years):
        return True
    if re.search(r"\b(?:l['’]an dernier|last year|au\s?(?:31|30)/\d{2}|exercice clos)\b", value, re.I):
        return True
    if _PERIOD_RE.search(value) and not any(y > cy for y in years):
        return True
    # v62.13.9.4.6 — un prétérit/participe sans AUCUNE mention temporelle est
    # un constat : « Competitors sustained 5-8% price increases ». Une cible
    # sans verbe passé ne peut pas emprunter cette voie.
    return not years and not _PERIOD_RE.search(value)


_ACTION_HEAD_FR = re.compile(r"^\s*(?:[-–•→>]\s*)?(\w+(?:er|ir|re|oir))\b", re.I)
_INFINITIVE_STOP = {"être", "avoir", "pouvoir", "devoir", "falloir", "hier", "premier", "dernier",
                    "particulier", "cahier", "atelier", "chantier", "janvier", "février", "dossier",
                    "calendrier", "papier", "métier", "quartier", "envisager"}


_LABEL_WORDS = {
    "option", "options", "zone", "zones", "pilier", "piliers", "pillar", "pillars",
    "phase", "phases", "scenario", "scénario", "scenarios", "scénarios", "axe",
    "axes", "volet", "volets", "lot", "lots", "étape", "etape", "étapes", "step",
    "steps", "niveau", "niveaux", "level", "levels", "section", "sections",
    "slide", "slides", "page", "pages", "article", "articles", "question",
    "questions", "item", "items", "point", "points", "statut", "status",
    "priorité", "priorite", "priority", "part", "tier", "risque", "risk",
    "décision", "decision", "décisions", "decisions", "annexe", "annexes",
    "chapitre", "chapitres", "chapter", "chapters", "tableau", "table", "figure",
    "top", "rang", "rank", "no", "n",
}


def _action_head(value: str) -> bool:
    m = _ACTION_HEAD_FR.match(value)
    if m and m.group(1).lower() not in _INFINITIVE_STOP:
        return True
    m2 = re.match(r"^\s*(?:[-–•→>]\s*)?([A-Za-zà-ÿÀ-Ÿ]+)"
                  r"(?:\s+(?:up|out|off|in|into|from|of|for))?\s+(\d+)", value)
    if m2:
        if m2.group(1).lower() in _LABEL_WORDS:
            return False
        if m2.group(1).isupper() and len(m2.group(1)) >= 2:
            return False  # sigle (ISO, FY, EBITDA) : jamais une tête verbale
        if re.match(re.escape(m2.group(0)) + r"\s*[:.\u2014\-]", value):
            return False  # « Mot N : » = étiquette, pas une action
        return True
    return False


_NOT_A_VERB_HEAD = frozenset((
    "the", "a", "an", "this", "that", "these", "those", "our", "its", "their",
    "his", "her", "my", "your", "some", "over", "about", "around", "nearly",
    "only", "in", "at", "on", "by", "with", "from", "of", "for", "to", "and",
    "le", "la", "les", "l", "un", "une", "des", "du", "de", "d", "ce", "cet",
    "cette", "ces", "son", "sa", "ses", "notre", "nos", "votre", "vos", "leur",
    "leurs", "environ", "près", "plus", "moins", "soit", "dont", "avec", "sur",
    "en", "à", "au", "aux", "et", "ou", "entre", "depuis", "vers", "pour"))


def _action_head_strict(value: str) -> bool:
    """v62.13.9.4.15 — tête d'action pour la règle « jamais un fait accompli » :
    une tête VERBALE (infinitif FR, impératif EN), jamais un article ou une
    préposition suivie d'un nombre. « The 1,390 basis point margin
    compression … reflects » (dossier anglophone coté) est un constat, pas une action."""
    # v62.13.9.4.15.2 — une tête de liste (« [4] Activer… », « (2) Lancer… »,
    # « 3) Structurer… ») ne cache pas le verbe : le run réel du 03/09/2026
    # 05:38 typait « [4] Activer une prospection … 4 posts … 20 contacts »
    # en fait accompli, la maintenance laissait passer, l'oracle bloquait.
    value = re.sub(r"^\s*(?:\[\d{1,3}\]|\(\d{1,3}\)|\d{1,3}[.)])\s+", "", value)
    m = _ACTION_HEAD_FR.match(value)
    if (m and m.group(1).lower() not in _INFINITIVE_STOP
            and "_" not in m.group(1)                       # « brief_codir — … » : un rôle, pas un verbe
            and not re.match(re.escape(m.group(0)) + r"\s*[:\u2014\u2013|]", value)):
        return True
    m2 = re.match(r"^\s*(?:[-–•→>]\s*)?([A-Za-zà-ÿÀ-Ÿ]+)"
                  r"(?:\s+(?:up|out|off|in|into|from|of|for))?\s+(\d+)", value)
    if not m2:
        return False
    w = m2.group(1)
    if w.lower() in _NOT_A_VERB_HEAD or w.lower() in _LABEL_WORDS:
        return False
    if w.isupper() and len(w) >= 2:
        return False
    if re.match(re.escape(m2.group(0)) + r"\s*[:.\u2014\-]", value):
        return False
    return True


def _registry_bound_quantity62415(raw: str, after: str, claims) -> bool:
    """La grandeur ``raw`` suivie de son unité lexicale (« 0 salarié ») est-elle
    exactement un fait de registre (claim REGISTRY-*) ?"""
    try:
        m = re.match(r"\s*([\wà-ÿÀ-Ÿ-]+)", after or "")
        if not m:
            return False
        unit = m.group(1).lower()
        unit = unit[:-1] if len(unit) > 4 and unit.endswith("s") else unit
        val = _normalize_amount(raw)
        for c in claims or []:
            if not isinstance(c, dict):
                continue
            if not str(c.get("claim_id") or "").upper().startswith("REGISTRY-"):
                continue
            toks = set()
            for k in ("metric", "label", "value", "display_value"):
                for w in re.findall(r"[\wà-ÿÀ-Ÿ-]+", str(c.get(k) or "").lower()):
                    toks.add(w[:-1] if len(w) > 4 and w.endswith("s") else w)
            if unit not in toks:
                continue
            for k in ("value", "display_value", "normalized_value"):
                mv = re.search(r"\d[\d\s\u00A0.,]*", str(c.get(k) if c.get(k) is not None else ""))
                if mv and _normalize_amount(mv.group(0)) == val:
                    return True
    except Exception:
        return False
    return False


def classify_line(text: str, lang: str = "fr", *,
                  claims=None, authority_values=None, context=None) -> LineVerdict:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    v = LineVerdict(withhold=False)
    if not value:
        return v
    # v62.13.9.4.15.2 — repères de planification masqués AVANT le découpage
    # (run réel du 03/09/2026 05:38) : une plage de dates « 03/09 – 17/09/2026 »
    # et un index de semaine « semaine 1–2 » se lisaient « 09 – 17 » et
    # « 1–2, 03 » (fourchettes non typées) ; un libellé « (PRIORITÉ 1) »,
    # « P1 » est un ordinal, pas une grandeur. Longueur conservée pour les
    # positions.
    value = _PLANNING_MARKERS_RE.sub(lambda m: " " * len(m.group(0)), value)
    if TOOL_MARK in value:
        v.reasons.append("tool_marked")                # v62.13.9.4.21 — écrit par le produit
        return v
    if is_status_tagged(value):
        v.reasons.append("status_tagged")              # v62.13.9.4.21 — chiffre affiché AVEC son statut
        return v
    if is_tagged_register_line(value):
        v.reasons.append("scenario_register_tagged")   # v62.13.9.4.17 — registre embarqué
        return v
    if is_labelled_benchmark_line(value):
        v.reasons.append("labelled_benchmark")         # v62.13.9.4.18 — benchmark non vérifié, source citée
        return v
    if is_epistemic_caveat_line(value):
        v.reasons.append("epistemic_caveat")           # v62.13.9.4.19.6 — chiffre cité pour être récusé
        return v

    if _EVIDENCE_ROW_RE.match(value) or _TRISTATE_ROW_RE.match(value) \
            or _TRISTATE_CELL_RE.search(value):
        # v62.13.9.4.7 — une cible chiffrée sérialisée au format registre
        # (FACT | Objectif : 700 centres | …) n'est pas exemptée : chaque
        # segment utile est jugé comme une ligne à part entière.
        for seg in value.split("|")[1:]:
            seg = seg.strip()
            if len(seg) < 8 or re.fullmatch(r"p?\.?\s?\d+|[\w.-]+\.(?:pdf|docx|xlsx)", seg, re.I):
                continue
            # une rangée de preuve n'est inspectée que sur signal de cible :
            # les données comptables tracées (montants, stocks, scores de
            # détection) restent des preuves, pas des engagements.
            if not line_has_target_signal(seg):
                continue
            sub = classify_line(seg, lang, claims=claims,
                                authority_values=authority_values, context=context)
            if sub.withhold:
                v.withhold = True
                v.reasons.append("serialized_target_in_register")
                v.untyped.extend(sub.untyped)
                return v
        v.reasons.append("evidence_row")
        return v

    # v62.13.9.4.6 — ligne de modèle financier : libellé comptable en tête de
    # rangée + ≥3 séparateurs de cellules. La maquette P&L/cash est la surface
    # de modélisation supervisée du DAF, pas une cible narrative.
    if re.match(r"^\s*[⛔✅⚠️🔒]", value) or re.match(
            r"^\s*(?:RUN NOT VALIDATABLE|DELIVERABLE NOT DISTRIBUTABLE|"
            r"RUN NON VALIDABLE|LIVRABLE NON DISTRIBUABLE)\b", value, re.I):
        v.reasons.append("scenario_register_row")
        return v

    # Marqueurs de SORTIE DU PRODUIT (traçabilité de ce que le produit a
    # lui-même rangé) : idempotence totale. Les tags d'étiquetage de contenu
    # ([FACT], [ESTIM], …) ne sont PAS ici : une étiquette n'est jamais une
    # preuve — leur contenu est jugé normalement (v62.13.9.4.6).
    _illu62147 = re.match(
        r"^\s*[-–•→>*]?\s*\[(?:SCÉNARIO ILLUSTRATIF|ILLUSTRATIVE SCENARIO)[^\]]*\]\s*(?P<payload>.*)$",
        value, re.I)
    if _illu62147:
        # marqueur pédagogique explicite : inspection sur signal de cible
        # uniquement (l'assainissement des montants d'agents est assuré par
        # ailleurs) — un « Objectif : N » illustratif reste retenu.
        _pl62147 = (_illu62147.group("payload") or "").strip()
        if _pl62147 and line_has_target_signal(_pl62147):
            sub = classify_line(_pl62147, lang, claims=claims,
                                authority_values=authority_values, context=context)
            if sub.withhold:
                v.withhold = True
                v.reasons.append("serialized_target_in_register")
                v.untyped.extend(sub.untyped)
                return v
        v.reasons.append("scenario_register_row")
        return v

    _reg62147 = re.match(
        r"^\s*SCN-[\w-]*\d\s?[·.—–-]\s*(?P<payload>.*)$", value) \
        or re.match(r"^\s*\[SERIALIZED QUARANTINE[^\]]*\]\s*(?P<payload>.*)$", value) \
        or re.match(r"^\s*(?:Topic to qualify|Sujet à qualifier)\s*\|\s*(?P<payload>.*)$", value, re.I)
    if _reg62147:
        # v62.13.9.4.7 — plus aucune exception de registre : le payload d'une
        # entrée SCN/quarantaine est jugé comme une ligne à part entière ; une
        # cible chiffrée sérialisée reste une cible.
        _pl62147 = (_reg62147.group("payload") or "").strip()
        if _pl62147:
            sub = classify_line(_pl62147, lang, claims=claims,
                                authority_values=authority_values, context=context)
            if sub.withhold:
                v.withhold = True
                v.reasons.append("serialized_target_in_register")
                v.untyped.extend(sub.untyped)
                return v
        v.reasons.append("scenario_register_row")
        return v

    if (_ACCOUNTING_LABEL_RE.match(value) or _ACCOUNTING_ROW_LABEL_RE.match(value)) and _MODEL_ROW_RE.search(value) \
            and not _FUTURE_RE.search(value) and not _IMPERATIVE_TARGET_RE.search(value):
        v.reasons.append("financial_model_row")
        return v

    quantities = extract_quantities(value)

    # v62.13.9.4.32 (C) — LIGNE D'EN-TÊTE DE TABLEAU : « Poste | 2024 (réel) |
    # 2027 (proj.) | 2028 (proj.) | Évolution 2024-2028 » — des colonnes d'années
    # sont des périodes, jamais des grandeurs, même au-delà de l'horizon
    # d'autorité. (Un tableau prévisionnel gardé entier expose son en-tête au
    # contrôle final ; run réel du 11/09/2026.)
    if quantities and value.count("|") >= 2 and all(
            (q.kind == "CARDINAL" and _YEAR_RE.fullmatch(str(q.raw or "").strip()))
            or (q.kind == "RANGE" and all(_YEAR_RE.fullmatch(p_.strip()) for p_ in re.split(r"[–\-—/à]|to", str(q.raw or "")) if p_.strip()))
            for q in quantities):
        for q in quantities:
            q.qtype = "DATE_PERIOD"
        v.typed = list(quantities)
        return v

    # « un/une/a/an/one » en objet direct d'une tête verbale d'action
    if not quantities:
        m = _ART_ONE_RE.search(value)
        if m:
            head = value[:m.start()].strip()
            noun = re.match(r"\s*([\wà-ÿÀ-Ÿ-]+)", value[m.end():])
            head_word = re.sub(r"^[-–•→>\s]+", "", head)
            non_verbal_heads = {
                "the", "this", "that", "le", "la", "les", "un", "une", "des",
                "ce", "cet", "cette", "it", "he", "she", "we", "they", "i",
                "nous", "vous", "il", "elle", "on", "there", "here",
            }
            # v62.13.9.4.11 — CADENCE d'action. « Publier un post
            # LinkedIn/semaine » énonce un RYTHME opérationnel, pas un
            # engagement chiffré : l'article indéfini y désigne l'unité de
            # l'action, pas une grandeur d'affaires. Le contre-audit du
            # 31/08/2026 a relevé le blocage de cette ligne dans le deck
            # dossier de conseil réel — un faux rouge sur dossier de référence, donc
            # P0 au protocole. La règle est bornée : elle exige un marqueur
            # de périodicité ET l'absence de tout autre cardinal, si bien
            # que « Publier 3 posts/semaine » reste jugé.
            _cadence62411 = bool(
                re.search(r"(?:/|\bpar\s+|\bper\s+|\bchaque\s+|\ba\s+)"
                          r"(?:semaine|mois|jour|trimestre|an|année|"
                          r"week|month|day|quarter|year)\b", value, re.I)
                or re.search(r"\b(?:hebdomadaire|mensuel(?:le)?s?|quotidien(?:ne)?s?|"
                             r"trimestriel(?:le)?s?|weekly|monthly|daily|quarterly)\b",
                             value, re.I))
            if _cadence62411 and not re.search(r"\d", value):
                pass          # rythme d'action : l'article n'est pas une quantité
            elif (re.fullmatch(r"(?:[-–•→>]\s*)?[\wà-ÿÀ-Ÿ]+", head)
                    and head_word.lower() not in non_verbal_heads
                    and noun and noun.group(1).lower() not in _ONE_ABSTRACT):
                quantities = [Quantity(m.start(), m.end(), m.group(0), "ONE")]

    if not quantities:
        return v

    # v62.13.9.4.8 — un tag de preuve en tête de ligne (CONFIRMED |, FAIT |…)
    # n'est jamais un verbe : il est neutralisé, à longueur constante, pour
    # l'analyse verbale (accompli, statif, passé factuel).
    verbal62148 = _LEADING_TAG_RE.sub(lambda m: " " * len(m.group(0)), value, count=1)
    accomplished = _line_is_accomplished(verbal62148, lang, context)
    # v62.13.9.4.6 — état comptable daté : « Résultat net : −11,1 % en 2024 »
    # (libellé comptable + toutes années closes, sans verbe ni marqueur cible).
    if not accomplished and _ACCOUNTING_LABEL_RE.match(value) \
            and not _FUTURE_RE.search(value) and not _IMPERATIVE_TARGET_RE.search(value) \
            and not re.search(r"\b(?:objectifs?|cibles?|targets?|goals?)\b", value, re.I):
        _yrs = [int(y) for y in _YEAR_RE.findall(value)]
        _yrs += [int(m) for m in re.findall(r"\b(?:FY|H[12]|[QT][1-4])\s?((?:19|20)\d{2})\b", value, re.I)]
        if _yrs and all(y <= _current_year(context) for y in _yrs):
            accomplished = True
    action = _action_head(value)
    # v62.13.9.4.15 — une ligne à TÊTE D'ACTION (infinitif : « Structurer 3
    # offres packagées … avec tarifs affichés et livrables définis ») n'est
    # jamais un fait accompli : ses participes sont adjectivaux. Le rejeu du
    # run réel du 02/09/2026 15:04 typait ses grandeurs ACCOMPLISHED_FACT,
    # la protection de fait exemptait la ligne en amont, et le juge
    # indépendant la bloquait à l'export — faux vert amont, blocage aval.
    # Une rangée de plan d'actions sérialisée (« | A3.4 — … | Solliciter 3
    # clients … | ») porte sa tête d'action dans une cellule : chaque
    # segment est examiné.
    if accomplished and (_action_head_strict(value) or any(
            _action_head_strict(seg) for seg in value.split("|") if seg.strip())):
        accomplished = False
    auth_items = _authority_items(authority_values)
    auth = {it["value"] for it in auth_items if it["unit"] == "DATE"}
    # v62.13.9.4.7 — primauté absolue des signaux de cible/projection : sous
    # signal, une quantité ne peut être ni autorité, ni fait accompli, ni
    # statif, ni score méthodologique, ni durée-cadre (une cible reste une
    # cible, quelle que soit sa forme).
    target_signal = line_has_target_signal(value, context)
    # v62.13.9.4.9 — primauté du signal de cible, forme unique et réutilisable :
    # sous signal et sans passé factuel réel, aucune branche descriptive ne
    # peut requalifier la grandeur (ni accompli, ni STATIF — le statif
    # échappait à la primauté : « The desired maturity level IS 8/10 »).
    # v62.13.9.4.10 — le passé de l'ACTE de décider ne vaut pas passé de la
    # GRANDEUR : « le conseil a validé 24 M€ » reste un engagement.
    _decision62410 = _decision_authority_signal(value)
    _target_primacy = bool(target_signal
                           and (_decision62410
                                or not _has_factual_past(verbal62148, lang)))
    if target_signal and (_decision62410
                          or not _has_factual_past(verbal62148, lang)):
        # sans passé factuel réel, un signal de cible interdit l'accompli ;
        # « la cible a été atteinte » reste un fait accompli. (Le statif est
        # neutralisé après son calcul, plus bas.)
        accomplished = False

    bare_ref = bool(_BARE_REF_RE.match(value))
    attachment_size_line = bool(re.search(
        r"pi[èe]ces?\s+jointes?|\bPJ\b|attachments?", value, flags=re.I))
    telemetry_line = bool(re.search(
        r"per-page|per page|\bcache\b|\bhits\s?=|\bdurations?\b\s*\(|"
        r"\btimings?\b|à la page cit|on cited page|page (?:indispo|unavailable)|"
        r"(?:sans|without) page", value, flags=re.I))
    stative_line = bool(re.search(
        r"\b(?:compte|comptent|poss[èe]de|poss[èe]dent|dispose|disposent|"
        r"comprend|comprennent|inclut|incluent|emploie|emploient|exploite|"
        r"exploitent|d[ée]tient|d[ée]tiennent|regroupe|regroupent|totalise|"
        r"totalisent|includes?|comprises?|owns?|operates?|employs?|has|have|"
        r"contains?|consists?|couvre(?:nt)?|covers?)\b", verbal62148, flags=re.I)) and not _FUTURE_RE.search(value) \
        and not re.search(r"\b(?:objectifs?|cibles?|targets?|goals?|kpis?)\b", value, re.I)
    if target_signal and not _has_factual_past(value, lang):
        # v62.13.9.4.7 — primauté des signaux de cible : un statif sous
        # « plan/roadmap comporte/contains » reste une projection de contenu.
        stative_line = False
    registry_line = bool(re.search(
        r"\bSIREN\b|\bSIRET\b|\bRCS\b|\bcompany numbers?\b|\bregistry\b|"
        r"\bcompanies house\b|\bimmatricul", value, flags=re.I)) and not _FUTURE_RE.search(value)
    scoring_ctx = bool(_SCORING_LEXICON_RE.search(value)) and not _FUTURE_RE.search(value) \
        and not _IMPERATIVE_TARGET_RE.search(value)
    # pondération parenthésée de matrice de risques : méthodologique même
    # sous modaux (« pourrait ... (-3,5 points) »)
    risk_weight = bool(_SCORING_LEXICON_RE.search(value)) and bool(
        re.search(r"\([+\-±]\s?\d[\d,.]*\s?(?:pts?|points?)\)", value))
    decision_head = bool(_DECISION_HEAD_RE.match(value))
    # 13.9.2 — porte étroite : mot-cible + date complète dans la ligne ;
    # sous cette porte, seule une date de l'autorité peut typer DATE_PERIOD.
    # Les dates d'autorité sont comparées dans leurs variantes de format
    # (AAAA-MM-JJ ↔ JJ/MM/AAAA ↔ JJ-MM-AAAA).
    auth_ext = set(auth)
    for _a in list(auth):
        _m = re.fullmatch(r"((?:19|20)\d{2})-(\d{2})-(\d{2})", _a)
        if _m:
            _y, _mo, _d = _m.groups()
            auth_ext.update({f"{_d}/{_mo}/{_y}", f"{_d}-{_mo}-{_y}", f"{_d}.{_mo}.{_y}"})
    target_dated_line = bool(
        re.search(r"\b(?:objectifs?|cibles?|targets?|goals?)\b", value, re.I)
        and re.search(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b", value))
    # v62.13.9.4.30 — contre-audit croisé du 09/09 : sous mot-cible (« lancement »,
    # « lancer »), la règle 13.9.2 n'admettait que la date d'autorité du dossier et
    # reclassait toute autre date en grandeur non typée — « Lancement plan de
    # redressement · 2026-10-15 · À lancer » perdait action, porteur et échéance.
    # Une ÉCHÉANCE D'ACTION n'est pas une cible chiffrée : quand la ligne ne porte
    # aucune grandeur en dehors de ses dates, l'autorité ne s'applique pas.
    _only_dates62430 = not re.search(
        r"[€$£%]|\bk€|\bm€|\bmd€|\b(?:pts?|points?|bps|pp)\b|\bx\s?\d|"
        r"\b\d+(?:[.,]\d+)?\s*(?:%|k|K|M|Md|bn|mds?)\b|"
        r"(?<![\d/.-])\d{1,3}(?:[.,]\d+)?(?![\d/.-])",
        _FULLDATE_RE.sub(" ", re.sub(r"\b\d{4}-\d{2}(?:-\d{2})?\b|\b(?:19|20)\d{2}\b", " ", value)))
    # L'exemption vise une ACTION datée (verbe ou nom d'action, et le plus souvent
    # un porteur), pas une cible nue : « Target by 2027-08-15 » reste soumis au
    # contrat d'autorité de la 13.9.2 (une échéance de cible ne s'invente pas).
    _action_shape62430 = bool(
        re.search(r"(?i)\b(?:lancer|lancement|mettre en (?:place|œuvre|oeuvre)|mise en (?:place|œuvre|oeuvre)|"
                  r"structurer|formaliser|formalisation|organiser|organisation|d[ée]ployer|d[ée]ploiement|"
                  r"pr[ée]parer|pr[ée]paration|r[ée]aliser|r[ée]alisation|conduire|mener|auditer|audit\b|"
                  r"arbitrer|arbitrage|remettre|remise|collecter|collecte|clarifier|s[ée]curiser|"
                  r"[ée]valuer|[ée]valuation|cartographier|cartographie|contractualiser|"
                  r"launch|implement|set up|structure|formalise|formalize|organise|organize|deploy|"
                  r"prepare|conduct|run|audit|arbitrate|collect|clarify|secure|assess|map|"
                  # v62.13.9.4.32 (B) — noms d'action et participes : « présentation du plan … le 10 décembre »,
                  # « plan innovation produit lancé — … · 2027-09-01 », « négociation du financement — DAF · 31/12/2026 »
                  r"pr[ée]sentation|pr[ée]senter|n[ée]gociation|n[ée]gocier|lanc[ée]e?s?|finalis(?:[ée]e?s?|ation|er)|"
                  r"signature|signer|recrutement|recruter|ouverture|ouvrir|s[ée]minaire|comit[ée]|revue|r[ée]union|"
                  r"livraison|livrer|d[ée]marrage|d[ée]marrer|automatisation|automatiser|renforcement|renforcer|"
                  r"structuration|dimensionnement|validation|valider|jalon|"
                  r"negotiation|negotiate|launched|finalised|finalized|hiring|hire|opening|review|meeting|milestone|"
                  # v62.13.9.4.38 — verbes d'action anglais : « By 2026-12-31: CFO and Supply Chain to
                  # deliver … mitigation plan » perdait son échéance (run réel du 19/09/2026)
                  r"deliver|delivery|launch|complete|completion|submit|submission|present|approve|approval|sign|"
                  r"recruit|start|implement|implementation|roll[- ]?out|define|establish|quantify|quantification|"
                  r"mitigate|mitigation|plan|report|assess|assessment|audit|decide|decision|confirm|secure)\b", value)
        and not re.search(r"(?i)\b(?:objectifs?|cibles?|targets?|goals?)\b\s*:?\s*$", value))
    # v62.13.9.4.32 (B) — un porteur suivi d'une date (« — DAF · 31/12/2026 »,
    # « — Dir. R&D + Dir. commercial · 2027-09-01 ») est la forme d'un jalon d'action.
    if not _action_shape62430 and re.search(
            r"[—–-]\s*[A-ZÀ-Ÿ][^—–·|]{1,60}?\s*[·—–|]\s*(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{4})", value):
        _action_shape62430 = True
    if _only_dates62430 and _action_shape62430:
        target_dated_line = False
        _date_only_action62430 = True
    else:
        _date_only_action62430 = False
    milestone_line = bool(re.match(
        r"^\s*(?:[QTHS][1-4]?\s?\d{4}|\d{4}|\d+\s?[-–]\s?\d+\s?(?:d|j|jours?|mo|m|w|s|days?|months?|weeks?))\s*:", value)
        # v62.13.9.4.38 — « By 2026-12-31: … », « Avant le 31/12/2026 : … » : une échéance en
        # tête de ligne est un jalon, pas une grandeur non typée
        or re.match(r"(?i)^\s*(?:by|before|until|d'ici(?:\s+le)?|avant(?:\s+le)?|pour(?:\s+le)?)\s+"
                    r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{4})\s*[:—–-]", value))

    # v62.13.9.4.30 — contre-audit croisé du 09/09 : « se concentrer sur deux
    # segments : viticulture et espaces verts » — le compte introduit l'énumération
    # qui suit, il ne fixe aucune cible. Un mot-nombre devant un nom de
    # regroupement immédiatement suivi de ses éléments est un cadrage, pas une
    # grandeur. Sans énumération, « deux segments » reste une quantité.
    _enum62430: set = set()
    for _m62430 in re.finditer(
            rf"(?<![\w-])({_WORDNUM_FR}|{_WORDNUM_EN})\s+"
            r"(?:segments?|m[ée]tiers?|axes?|volets?|piliers?|familles?|gammes?|canaux|canal|"
            r"business\s+lines?|streams?|pillars?)\s*[:—–(]",
            value, re.I):
        _enum62430.add((_m62430.start(1), _m62430.end(1)))

    # v62.13.9.4.48 — non-quantités (nomenclature, noms à trait d'union, identifiants) : définition
    # PARTAGÉE avec la règle éditoriale et le mainteneur ; les repères de période restent typés ici.
    _nq48 = _nq_spans48(value, kinds=_NQ_NO_PERIODS48)
    _brief48 = [it for it in (auth_items or []) if it.get("unit") == "BRIEF_TARGET"]
    from utils import declared_quantities as _DQ48
    for q in quantities:
        raw = q.raw.strip()
        window = value[max(0, q.start - 30):min(len(value), q.end + 30)]
        base = max(0, q.start - 30)
        qpos = q.start - base

        # v62.13.9.4.49 — une année suivie d'un nom n'est un EFFECTIF que si ce nom se compte (« Recruter 2030
        # personnes ») ; suivie d'un nom qualifié par l'année (« Present 2030 emissions targets »), c'est un
        # horizon. Audit du 29/09/2026 : l'action RSE du brief était retirée du deck, puis signalée, pour « 2030 ».
        # (règle d'origine : action + année + nom = EFFECTIF, « Déployer 2026 capteurs », « Build 2026 homes » —
        # corpus adverse N2 ; exception 9.4.49 : l'année qualifie un nom d'HORIZON qui suit, « Present 2030 emissions
        # targets », « Approve the 2027 budget » — l'année est alors un horizon, pas un effectif)
        year_as_count = bool(
            action and _YEAR_RE.fullmatch(raw.lstrip("+-± "))
            and re.match(r"\s+[a-zà-ÿ]", value[q.end:])
            and not re.match(r"\s+(?:en|in|by|to|d['’]ici|avant|:)", value[q.end:], re.I)
            and not _HORIZON_NOUN_AFTER49.match(value[q.end:]))

        if q.kind == "DATE" and ((not target_dated_line and not target_signal)
                                 or _date_only_action62430          # v62.13.9.4.30 — échéance d'action
                                 or not auth_ext
                                 or any(a in value for a in auth_ext)):
            # v62.13.9.4.32 (B) — une date est une période ; sous un mot-cible
            # (« Target by … »), seule la date d'autorité du brief ou l'échéance
            # d'une action l'est (13.9.2 : une date inventée sous une cible reste retenue).
            q.qtype = "DATE_PERIOD"
        elif bare_ref:
            q.qtype = "IDENTIFIER"
        elif any(_s <= q.start < _e for _s, _e, _k in _nq48):
            q.qtype = "IDENTIFIER"          # v62.13.9.4.48 — « Scope 3 », « IFRS 16 », « A-320 », « CIK SEC nnnnnn »
        elif _brief48 and _target_primacy and _DQ48.brief_target_hit(value, raw, _brief48):
            # v62.13.9.4.48 — point 4 : la cible du BRIEF, citée comme cible, n'est pas un chiffre non
            # étayé du livrable : c'est la déclaration du dirigeant, signalée une fois (section du brief
            # et registre). Le corps garde la phrase telle quelle.
            q.qtype = "BRIEF_TARGET"
        # v62.13.9.4.15 — NUMÉROTATION DE TITRE markdown/plan (« ## 1. SYNTHÈSE »,
        # « ### 2.1 Taille du marché », « 4.3 Axe 3 »). Le rejeu du run réel du
        # 02/09/2026 15:04 retenait 121 lignes, dont TOUS les titres de section
        # numérotés de Stratégie : le numéro de section était compté comme
        # grandeur non typée. Un numéro de plan n'engage aucune grandeur.
        elif _SECTION_HEAD_RE.match(value) and q.start < _SECTION_HEAD_RE.match(value).end():
            q.qtype = "IDENTIFIER"
        elif any(m.start() <= q.start < m.end() for m in _NAF_CODE_RE.finditer(value)):
            q.qtype = "IDENTIFIER"  # code NAF / APE
        # v62.13.9.4.15 — MONTANT NUL (« 0 € (temps interne) », « 0 k€ »). Un
        # coût de zéro n'est pas une cible chiffrée : il dit l'absence de
        # dépense. Le rejeu 15:04 le comptait comme grandeur non typée, et
        # chaque rangée du plan d'actions en portait un.
        elif re.fullmatch(r"[+\-± ]*0(?:[.,]0+)?", raw) and re.match(
                r"\s?(?:€|k€|M€|Md€|\$|£|k\$|eur\b|euros?\b)", value[q.end:], re.I):
            q.qtype = "ZERO_AMOUNT"
        # v62.13.9.4.15 — DURÉE D'EXPÉRIENCE (« 11+ ans d'expérience », « 10 years
        # of experience ») : attribut de profil, pas engagement.
        elif re.match(r"\+?\s?(?:ans?|années?|years?)\s+(?:d['’]|of\s+)exp[ée]rience", value[q.end:], re.I) \
                or (re.match(r"\+\s?(?:ans?|années?|years?)\b", value[q.end:], re.I)
                    and not target_signal):
            q.qtype = "DURATION_ATTR"  # « 11+ ans » : ancienneté ouverte, attribut de profil
        elif telemetry_line:
            q.qtype = "DOC_APPARATUS"
        elif attachment_size_line and re.match(r"\s?k\b", value[q.end:]):
            q.qtype = "DOC_APPARATUS"  # taille « — 9 k » d'une ligne pièces jointes
        elif registry_line:
            q.qtype = "IDENTIFIER"
        elif q.end < len(value) and value[q.end:q.end + 1] in "\uFE0F\u20E3":
            q.qtype = "IDENTIFIER"  # emoji keycap 1️⃣
        elif _TIME_RE.search(window) and any(
                m.start() <= qpos < m.end() for m in _TIME_RE.finditer(window)):
            q.qtype = "DATE_PERIOD"
        elif any(m.start() <= qpos < m.end() for m in _DOC_APPARATUS_RE.finditer(window)):
            q.qtype = "DOC_APPARATUS"
        elif any(m.start() <= qpos < m.end() for m in _LAW_REF_RE.finditer(window)):
            q.qtype = "IDENTIFIER"
        elif any(m.start() <= q.start < m.end() for m in _GUIDED_IDENT_RE.finditer(value)):
            q.qtype = "IDENTIFIER"
        elif re.search(r"#\d", value[max(0, q.start - 1):q.end]):
            q.qtype = "IDENTIFIER"  # rang #1
        elif not action and re.search(r"\btop\s?\d+\b", window, re.I) and any(
                m.start() <= qpos < m.end()
                for m in re.finditer(r"\btop\s?\d+\b", window, flags=re.I)):
            q.qtype = "IDENTIFIER"  # rang de classement (Top 3)
        elif q.kind == "ROMAN" and re.match(r"^\s*[IVXLCDM]+[.)]\s", value):
            q.qtype = "IDENTIFIER"  # en-tête de section romaine
        elif _CHECKLIST_RE.match(value) and q.start <= 6:
            q.qtype = "IDENTIFIER"
        elif any(m.start() <= qpos and qpos + len(q.raw.rstrip()) <= m.end()
                 for m in _ORDINAL_LABEL_RE.finditer(window)):
            q.qtype = "IDENTIFIER"
        elif any(m.start(1) <= qpos < m.end(1) for m in _DEPT_RE.finditer(window)):
            q.qtype = "IDENTIFIER"
        elif risk_weight and any(
                m.start() <= q.start < m.end()
                for m in re.finditer(r"\([+\-±]\s?\d[\d,.]*\s?(?:pts?|points?)\)", value)) \
                and not target_signal:
            q.qtype = "METHOD_SCORE"
        elif scoring_ctx and (any(m.start() <= qpos < m.end()
                                  for m in _SCORING_QTY_RE.finditer(window))
                              or q.kind in ("WORDNUM",)) \
                and not target_signal:
            q.qtype = "METHOD_SCORE"
        elif (q.start, q.end) in _enum62430:
            q.qtype = "ENUMERATION_HEAD"       # v62.13.9.4.30 — cadrage d'une énumération
        elif q.kind == "CARDINAL" and _YEAR_RE.fullmatch(raw.lstrip("+-± ")) \
                and not year_as_count \
                and not re.search(rf"[+\-±]\s?{re.escape(raw.lstrip('+-± '))}", value):
            q.qtype = "DATE_PERIOD"
        elif q.kind == "RANGE" and all(
                _YEAR_RE.fullmatch(p.strip()) for p in re.split(r"[–\-—/à]|to", raw) if p.strip()) \
                and not any(o is not q and o.kind in ("CARDINAL", "PERCENT", "CURRENCY", "RANGE", "MULT", "WORDNUM")
                            and not _YEAR_RE.fullmatch(str(o.raw or "").strip())      # des années voisines ne sont pas des grandeurs
                            for o in quantities):
            # v62.13.9.4.32 (A) — « Plan stratégique 2026-2028 » : une plage
            # d'années SEULE dans la ligne est l'horizon, jamais une grandeur —
            # même sous un mot-cible (« plan », « objectif »), il n'y a rien
            # d'autre qui puisse être le montant visé (run réel ee08f0 : le
            # titre d'un plan retiré du corps).
            q.qtype = "DATE_PERIOD"
        elif (_PERIOD_RE.search(raw) or (q.kind == "RANGE" and all(
                _YEAR_RE.fullmatch(p.strip()) for p in re.split(r"[–\-—/à]|to", raw) if p.strip()))) \
                and ((not target_dated_line and not target_signal)
                     or _date_only_action62430          # v62.13.9.4.30 — échéance d'action
                     or not auth_ext
                     or any(a in value for a in auth_ext)):
            q.qtype = "DATE_PERIOD"
        elif any(m.start() <= q.start - max(0, q.start - 30) < m.end()
                 and ((not target_dated_line and not target_signal)
                     or _date_only_action62430          # v62.13.9.4.30 — échéance d'action
                     or not auth_ext
                     or any(a in value for a in auth_ext))
                 for m in _FULLDATE_RE.finditer(window)):
            q.qtype = "DATE_PERIOD"  # 13.9.2 : sous mot-cible, seule la date d'autorité
        elif any(m.start() <= q.start - max(0, q.start - 30) < m.end()
                 for m in _GUIDED_IDENT_RE.finditer(window)):
            q.qtype = "IDENTIFIER"
        elif _IDENT_RE.search(window) and any(
                m.start() <= q.start - max(0, q.start - 30) < m.end()
                or abs(m.start() - (q.start - max(0, q.start - 30))) <= 2
                for m in _IDENT_RE.finditer(window)):
            q.qtype = "IDENTIFIER"
        elif (_SCORE_RE.fullmatch(raw) or (_SCORE_RE.search(window) and _SCORE_CTX_RE.search(value))) \
                and not _IMPERATIVE_TARGET_RE.search(value) and not target_signal:
            q.qtype = "METHOD_SCORE"
        elif not target_signal and _authority_match(
                raw, local_quantity_unit(value, q.start, q.end, raw), auth_items):
            q.qtype = "AUTHORITY"
        elif any(m.start() <= qpos < m.end() for m in re.finditer(
                r"\bplans?\s+d['’]action\s+(?:à|de|sur)\s+\d+\s?(?:jours?|mois|semaines?)\b|"
                # v62.13.9.4.15 — « Objectifs marketing à 30 jours », « priorités à 90
                # jours » : la durée CADRE l'objectif, elle n'en est pas la grandeur
                # (les montants de la ligne restent jugés). Rejeu du run réel 15:04.
                r"\b(?:objectifs?|priorit[ée]s?|actions?|targets?|goals?|priorities)\b[^.\n:]{0,40}?"
                r"\b(?:à|sur|d['’]ici|sous|at|within|over)\s+\d+\s?(?:jours?|mois|semaines?|days?|months?|weeks?)\b|"
                r"\b\d+[-\s]?(?:day|month|year|jours?|mois)s?[-\s](?:\w+[-\s]){0,2}plans?\b|"
                # v62.13.9.4.25 — « prévisionnel de trésorerie glissant 12 mois » :
                # l'horizon GLISSANT d'un outil de pilotage est un attribut de
                # l'outil, pas une grandeur (contre-audit v24, §2). Borné à la
                # forme glissante : « Budget de 800 k€ sur 24 mois » reste un
                # engagement de plan (pendule 18/18 conservé).
                r"\b(?:glissante?s?|rolling)\s+(?:sur\s+|over\s+)?\d+\s?(?:mois|months?|semaines?|weeks?)\b|"
                r"\bT\+?\d+\s?[dj]\b", window, flags=re.I)) \
                and not re.match(r"\s*Horizon\s*:", value, flags=re.I):
            q.qtype = "DURATION_ATTR"  # durée-cadre du dispositif (plan d'action à 90 jours)
        elif any(m.start() <= qpos < m.end() for m in _DURATION_ATTR_RE.finditer(window)) \
                and not re.search(
                    r"\b(?:d[ée]lais?|[ée]ch[ée]ances?|deadlines?|delays?|lead ?times?|"
                    r"roadmaps?|phases?|plans?|planning|implementation|d[ée]ploiements?|"
                    r"rollout|timelines?|recruitments?|recrutements?)\b",
                    window, flags=re.I) \
                and not re.match(r"\s*Horizon\s*:", value, flags=re.I) \
                and (not target_signal or re.search(
                    r"\b\d+\s*[\u2013\u2014-]\s*\d+\s?(?:mois|months?|jours?|days?|"
                    r"semaines?|weeks?|ans?|years?)\b|\bwindows?\b|\bfen[êe]tres?\b",
                    value, flags=re.I)):
            # v62.13.9.4.7 — une PLAGE temporelle (« 12–24 month window ») est
            # un descripteur de cadre, même sous signal de plan ; une durée
            # nue en objet direct d'une cible reste refusée.
            q.qtype = "DURATION_ATTR"
        elif milestone_line and q.end <= len(value.split(":", 1)[0]) + 1:
            q.qtype = "DATE_PERIOD"  # fenêtre temporelle d'un jalon (0-30d :)
        elif milestone_line and re.search(
                rf"(?<![\w])({re.escape(raw)})\s+(?:ans?|mois|années?|years?|months?|semaines?|weeks?)\b", value):
            q.qtype = "DURATION_ATTR"
        elif q.kind == "RANGE" and _BAND_RE.search(window) and not action \
                and not _IMPERATIVE_TARGET_RE.search(value) and not _FUTURE_RE.search(value) \
                and not re.search(r"\b(?:cibles?|targets?)\b", value, re.I):
            q.qtype = "REGISTRY_BAND"
        elif q.kind == "RANGE" and re.sub(r"\s", "", raw) in _SIRENE_BANDS and not action \
                and not _IMPERATIVE_TARGET_RE.search(value) and not _FUTURE_RE.search(value) \
                and not re.search(r"\b(?:cibles?|targets?)\b", value, re.I) \
                and not re.match(r"\s*(?:mois|months?|ans?|ann[ée]es?|years?|semaines?|"
                                 r"weeks?|jours?|days?|h\b|heures?|hours?)",
                                 value[q.end:], flags=re.I):
            q.qtype = "REGISTRY_BAND"
        elif _STRUCT_RE.search(window) and (not action or decision_head) and not _FUTURE_RE.search(value):
            q.qtype = "STRUCTURE_COUNT"
        elif raw.replace(" ", "").replace("\u00A0", "") in ("100%",) and re.match(
                r"\s+(?!de\b|des\b|du\b|of\b)[a-zà-ÿA-ZÀ-Ÿ]", value[q.end:]) \
                and not _IMPERATIVE_TARGET_RE.search(value):
            q.qtype = "COMPARATOR_DESC"  # attribut qualificatif (100 % électrique)
        elif re.search(r"[<>≤≥]\s?$", value[:q.start]) and not _FUTURE_RE.search(value) \
                and not _IMPERATIVE_TARGET_RE.search(value) \
                and not any(int(y) > _current_year(context) for y in _YEAR_RE.findall(value)):
            q.qtype = "COMPARATOR_DESC"
        elif re.match(r"^\s*(?:Executive replacement|Remplacement exécutif)\s*:?\s*\d{1,2}[.)]", value) \
                and q.end <= 40:
            q.qtype = "IDENTIFIER"
        elif re.search(r"(?:^|[.:]\s)\d{1,2}[.)]\s", value[max(0, q.start - 3):q.end + 2]):
            q.qtype = "IDENTIFIER"
        elif any(m.start() <= qpos < m.end() for m in re.finditer(
                r"\b(?:r[ée]seaux?|parcs?|networks?|fleets?|flottes?|portefeuilles?|"
                r"portfolios?|effectifs?)\s+(?:de|d['’]|of)\s?\d[\d\s\u00A0]*",
                window, flags=re.I)) and not action and not _FUTURE_RE.search(value) \
                and not target_signal:
            q.qtype = "ACCOMPLISHED_FACT"  # état de parc nominal (Réseau de 600 centres)
        elif accomplished:
            q.qtype = "ACCOMPLISHED_FACT"
        elif not action and re.fullmatch(r"[+\-±]?\s?\d+(?:[.,]\d+)?\s?pts?", raw.strip()) \
                and not _FUTURE_RE.search(value) and not target_signal \
                and not re.search(r"\bkpis?\b", value, re.I):
            q.qtype = "ACCOMPLISHED_FACT"  # delta de points nominal (constat KPI)
        elif stative_line and not action and not _target_primacy:
            # v62.13.9.4.12 — DURCISSEMENT MESURÉ PUIS ÉCARTÉ.
            # Le contre-audit du 31/08/2026 exige qu'une grandeur nue non
            # déclarée (« Le réseau compte 24 centres ») ne survive pas
            # silencieusement. La seule règle possible sans déclaration est
            # un deny-by-default sur le statif présent. Elle a été
            # implémentée, bornée (date, passé factuel, claim), puis
            # MESURÉE : elle casse une douzaine de témoins légitimes du
            # contrat existant — « La société compte 600 centres en
            # France », « Le conseil compte 12 membres », « Le réseau compte
            # 24 centres en Bretagne ». Ce sont des faits, pas des cibles.
            # Échanger douze faux rouges contre trois faux verts est une
            # dégradation nette pour un outil de décision : la règle est
            # retirée et le point reste une LIMITE DÉCLARÉE, dont la
            # fermeture passe par la déclaration à la génération (A1), non
            # par une règle textuelle supplémentaire.
            q.qtype = "ACCOMPLISHED_FACT"  # état statif présent (compte N centres)
        elif claims is not None and len(quantities) == 1 and re.fullmatch(
                r"[\s≈~+\-±(]*" + re.escape(raw) + r"[\s.,%)]*", value.strip()) \
                and _claim_amounts(claims) and _normalize_amount(raw) in _claim_amounts(claims):
            q.qtype = "CLAIM_BOUND"  # valeur nue = affichage d'un fait confirmé
        elif claims is not None and _CB.supports(value, claims):
            q.qtype = "CLAIM_BOUND"
        elif claims is not None and _registry_bound_quantity62415(raw, value[q.end:], claims):
            # v62.13.9.4.15 — un fait de REGISTRE se lie grandeur par grandeur :
            # « structure solo (0 salarié) … depuis 11 ans » porte un fait
            # Pappers et une ancienneté ; la liaison de ligne entière (tous
            # les nombres) échouait sur le second et retenait le premier.
            q.qtype = "CLAIM_BOUND"

        if q.qtype is None:
            v.untyped.append(q)
        else:
            v.typed.append(q)

    if v.untyped:
        v.withhold = True
        v.reasons.append("untyped_quantity:" + ",".join(sorted({q.raw.strip() for q in v.untyped})))
    return v


def line_is_protected_fact(text: str, lang: str = "fr", context=None) -> bool:
    """Vrai si la ligne est un fait accompli intégralement typé : elle ne doit
    JAMAIS être réécrite ni retenue (protection P1-03)."""
    v = classify_line(text, lang, context=context)
    if v.withhold or not v.typed:
        return False
    return any(q.qtype == "ACCOMPLISHED_FACT" for q in v.typed) and not v.untyped
