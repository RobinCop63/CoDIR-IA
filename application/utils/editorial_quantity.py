"""v62.13.9.4.5 — quantité éditoriale générique v3, partagée (maintenance / guard / gate).

Réponse au contre-audit ChatGPT du 28/08 (NO-GO 9.4.4) :
- le CARDINAL déclenche sous toutes ses formes : chiffres, décimaux à point ou
  virgule, grands entiers, montants avec ou sans devise, suffixes k/M/bn,
  nombres en lettres FR/EN (« one » inclus), approximations (dizaine, centaine,
  hundreds of), plages « N-M » et « N à M », fractions « 2/3 », chiffres romains
  devant un nom, placeholders XX/NN/TBD, années employées comme comptes
  (« 2026 capteurs ») ;
- le contexte prospectif est STRUCTUREL : infinitif FR par morphologie (casse
  respectée : « À VÉRIFIER » est un statut, pas une action), verbe initial EN
  structurel (au-delà de toute liste), futur ET conditionnel morphologiques,
  nominalisation, mot de cible, horizon, durée en contexte de planification ;
- les FAITS restent des faits : verbes statifs au présent (« compte 600
  centres », « possède 20 filiales », « includes 5 workstreams »), faits
  accomplis/validés/historiques (« declined », « reculé »), attributs produit,
  numérotations descriptives et grades matière (« Acier 304 », « niveau 2 »),
  normes, SIREN/SIRET, dates ; la tranche d'effectif n'est exemptée qu'en
  contexte de FAIT — portée par un verbe d'action, c'est une cible ;
- les valeurs d'autorité du contrat de planification (Temporal Core) peuvent
  être passées par l'appelant : une ligne d'horizon dont tous les cardinaux
  appartiennent à l'autorité n'est pas retenue (« Horizon : 24 mois ») ;
- la réécriture choisit la langue LIGNE par ligne (articles et marqueur EN sur
  une ligne EN, même dans un document FR).

Aucun nom de dossier, aucun lexique porteur : un verbe absent de toute liste
est reconnu par sa structure, et si la réécriture ne peut pas neutraliser un
cardinal, la phrase ne revient pas sur la surface principale.
"""
from __future__ import annotations

import datetime as _dt
import re

# ── Nombres en lettres ────────────────────────────────────────────────────────
_FR_UNITS = r"(?:z[ée]ro|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|quinze|seize|" \
            r"vingt|trente|quarante|cinquante|soixante|quatre-vingts?|cent|cents|mille|millions?|milliards?)"
_EN_UNITS = r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|" \
            r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|" \
            r"hundred|thousand|million|billion|dozen)"
NUMBER_WORDS_RE = re.compile(
    rf"\b(?:{_FR_UNITS}|{_EN_UNITS})(?:(?:[\s-]+(?:et|and)?[\s-]*)(?:{_FR_UNITS}|{_EN_UNITS}|un|une|one))*\b",
    re.I,
)
APPROX_QUANTITY_RE = re.compile(
    r"\b(?:dizaines?|douzaines?|quinzaines?|vingtaines?|trentaines?|quarantaines?|cinquantaines?|soixantaines?|"
    r"centaines?|milliers?|dozens?|hundreds?|thousands?)\b|"
    # v62.13.9.4.7 — « score » n'est un nombre-mot (vingtaine) que porté par
    # un déterminant numérique ; « le score de maturité » n'est pas un compte.
    r"\b(?:(?:a|one|two|three|four)\s+scores?(?:\s+of)?|scores?\s+of)\b",
    re.I,
)
ROMAN_RE = re.compile(r"\b(?:XL|XXX|XX|XIX|XVI{0,3}|XV|XIV|XI{1,3}|IX|VI{1,3}|IV|III|II|V|X)\b(?=\s+[a-zà-ÿ])")
# Les notations de score (« 79/100 », « 8/10 », « 18/20 ») sont des mesures, pas des fractions.
FRACTION_RE = re.compile(r"(?<![\d/.,])\b\d{1,3}\s*/\s*(?!100\b|10\b|20\b)\d{1,3}\b(?![\d/])")
SCORE_RE = re.compile(r"(?<![\d/.,])\b\d{1,3}\s*/\s*(?:100|10|20)\b(?![\d/])")

# ── Cardinaux ─────────────────────────────────────────────────────────────────
# v62.13.9.4.15.4 — les milliers à l'espace (« 1 200 € », « 24 000 € ») sont
# UN nombre : sans cela « TJM cible 1 200 €/jour » se réécrivait « 1 une
# enveloppe à dimensionner/jour » (run réel du 03/09/2026 08:24).
_DIGIT = r"(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
_CURRENCY = r"(?:[€£$]|M€|k€|K€|Md€|EUR|USD|GBP|CHF)"
_SUFFIX = r"(?:\s*(?:k|m|bn|md|mio|mrd|M)(?![a-zà-ÿA-Z]))?"
_UNIT_TAIL = r"(?:\s*(?:%|pts?|points?(?!\s+(?:de\s+vente|of\s+sale))|pp|bps|x|fois|h|km|kwh|kg|t)(?![\w]))?"
CARDINAL_RE = re.compile(
    rf"(?<![\w.,/:])(?:{_CURRENCY}\s*)?{_DIGIT}(?:\s*(?:[-–]|à|to)\s*{_DIGIT})?{_SUFFIX}(?:\s*{_CURRENCY})?{_UNIT_TAIL}(?![\w/])"
    rf"|\b(?:XX+|NN+|\[N\]|\[XX?\]|\[nombre\]|\[number\]|TBD|TBC)\b",
    re.I,
)

# ── Exemptions positionnelles (masquées par des espaces de même longueur) ─────
# Année : jamais masquée quand elle sert de COMPTE (« 2026 capteurs », « Build 2026 homes »).
_YEAR_COUNT_GUARD = r"(?!\s+(?!(?:les|des|ces|ses|nos|vos|leurs|the|these|those|their|his|her|its|is|was|are|were|has|have|had|et|and|ou|or|de|du|of)\b)[a-zà-ÿ]{3,}s\b)"
DATE_RE = re.compile(
    r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b|\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b|\b\d{1,2}/\d{4}\b|"
    r"\b\d{1,2}(?:er|e)?\s+(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre|"
    r"january|february|march|april|may|june|july|august|september|october|november|december)(?:\s+(?:19|20)\d\d)?\b|"
    r"\b(?:19|20)\d\d\s*[-–/]\s*(?:19|20)?\d\d\b|\b(?:19|20)\d\d\b" + _YEAR_COUNT_GUARD + r"|"
    r"\b[TQHS][1-4](?:\s*(?:19|20)\d\d)?\b|\bFY\s*(?:19|20)?\d\d\b|"
    # v62.13.9.4.29 — « avant 20/09 » : date courte (mois à deux chiffres), jamais une
    # fraction (« une partie ») ; « T0 → T+90 jours » : repère de planning, jamais un compte
    r"(?:\b(?:avant|le|au|dès|d['’]ici|jusqu['’]au|du|entre|pour le|à partir du|before|by|on|until)\s+\d{1,2}/\d{1,2}\b|\b(?:1[3-9]|2\d|3[01])/(?:0?[1-9]|1[0-2])\b|\b(?:0?[1-9]|[12]\d|3[01])/0[1-9]\b)(?!\s*/)|\bT0\b|\b[TJM]\s?[+\-]\s?\d{1,3}(?:\s?(?:j|jours?|d|days?|m|mois|months?|s|semaines?|weeks?))?\b",
    re.I,
)
CODE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]{1,6}-?\d+[A-Za-z]*\d*(?:-\d+)*|[A-Za-z]{1,4}\d+(?:\.\d+)+|\d+(?:\.\d+){2,}[A-Za-z]?|T\s*\+\s*\d+(?:\s*[-–]\s*\d+)?\s*[mMaA]?)(?![A-Za-z0-9])"
)
STANDARD_RE = re.compile(
    r"\b(?:ISO|IEC|EN|NF|DIN|BS|ASTM|IEEE|RFC|CE|UN|GS1|SAE|ANSI|IFRS|IAS|IPSAS|SOX|PCI[- ]DSS|GDPR|RGPD|HDS|HAS|LNE|NIS)\s*[-/]?\s*\d[\d.\-/: ]*\d\b|"
    r"\b(?:ISO|IEC|EN|NF|DIN|RFC)\s*[-/]?\s*\d+\b",
    re.I,
)
DESCRIPTIVE_NUMBER_RE = re.compile(
    r"(?<![\w])(?:niveau|niveaux|level|levels|tier|tiers|grade|grades|classe|classes|class|phase|phases|[ée]tape|[ée]tapes|step|steps|"
    r"version|versions|v|art\.?|articles?|§|slides?|pages?|p\.|lignes?|lines?|options?|sc[ée]narios?|scenarios?|axes?|piliers?|pillars?|"
    r"priorit[ée]s?|priorities|priority|risques?|risks?|n°|no\.?|#|lots?|chapitres?|chapters?|sections?|annexes?|annex|volets?|items?|"
    r"points?\s+n°|leviers?|levers?|questions?|q|zones?|codes?|figures?|fig\.?|tableaux?|tables?|notes?|r[ée]f\.?|r[ée]f[ée]rences?|"
    r"acier|aciers|inox|alliages?|aluminium|b[ée]tons?|types?|mod[èe]les?|modules?|s[ée]ries?|series|"
    r"strat[ée]gies?\s+en|plan\s+en|en)\s*\d+(?:[.,]\d+)*\b",
    re.I,
)
IDENTIFIER_RE = re.compile(
    # v62.13.9.4.26 — labels d'ordre des agents : « [n4] », « n4] », « A1. », « R2 — »
    r"\[\s*[nNdDaArR]?\s*\d{1,2}\s*\]|\(\s*[nN]\d{1,2}\s*\)|\b[nN]\d{1,2}\]|\b[ADRP]\d{1,2}(?=\s*[.:)—–-])|"
    r"\b[A-Za-zÀ-ÿ&]{3,}\s+\d\.0\b|"      # v62.13.9.4.27 — « industrie 4.0 » : nom de génération
    r"§\s*\d{1,3}\s*[—–-]?|"                    # v62.13.9.4.31 — « §6 — Plan d'actions » : numéro de rubrique
    r"\bOptions?\s+\d{1,2}(?:\s*(?:vs\.?|/|,|et|ou|and|or|[-–]|\+|&)\s*(?:Options?\s+)?\d{1,2})+\b|"      # v62.13.9.4.28 — « Option 1 vs 2 vs 3 » : numéros d'options
    r"\b(?:siren|siret|company\s+number|n°\s*(?:siren|siret|tva|rcs)|tva|rcs|naf|ape|eori|lei|cn)\s*[:#]?\s*[A-Z]{0,2}\s*\d[\d ]{4,}\b|"
    r"(?<![\d€£$.,])\b\d{9}\b(?!\s*(?:[€£$%]|k€|M€|Md€|k\b|m\b|bn\b))|"
    r"(?<![\d€£$.,])\b\d{14}\b(?!\s*(?:[€£$%]|k€|M€|Md€|k\b|m\b|bn\b))|"
    r"\b\d{2}(?:[ .]\d{2}){4}\b",
    re.I,
)
BAND_RE = re.compile(
    r"\btranches?\s+\d{1,6}\s*[-–]\s*\d{1,6}\b|\b\d{1,6}\s*[-–]\s*\d{1,6}\s+(?:salari[ée]s?|employees?|employ[ée]s?|personnes?|collaborateurs?|staff|ETP|FTE)\b",
    re.I,
)
ENUMERATOR_RE = re.compile(r"^\s*(?:[-*•▌✓]+\s*)?(?:\d+[.)]\s+|[a-z][.)]\s+)+", re.I)
PLANNING_CONTRACT_RE = re.compile(
    r"\bplan\s+d['’]action\s+à\s+\d+\s*(?:jours?|mois)\b|\b\d+[- ]day\s+(?:action\s+)?plan\b|\bplan\s+à\s+\d+\s*(?:jours?|mois|ans)\b",
    re.I,
)
# v62.13.9.4.31 — « 100 % coton », « 100 % électrique » est un attribut produit ;
# « rester 100 % réseau » est une exclusivité de modèle qui doit être réécrite en
# clair (contre-audit v30, §3). L'exemption d'attribut ne s'applique donc pas
# après un verbe d'état.
ATTRIBUTE_RE = re.compile(
    r"(?<!\brester )(?<!\brestons )(?<!\bdemeurer )(?<!\btravailler )(?<!\bopérer )(?<!\boperer )"
    r"(?<!\bremain )(?<!\bstay )\b100\s*%\s+[a-zà-ÿ-]{3,}\b|\b\d+(?:[.,]\d+)?\s*%\s+[a-zà-ÿ]{3,}(?:é|ée|és|ées|ique|iques|el|elle|els|elles|able|ables|ible|ibles)\b",
    re.I,
)
# v62.13.9.4.5 — attributs de durée hyphénés (« 24-Month Reset », « 3-year plan ») :
# adjectifs composés, jamais des quantités d'action.
DURATION_ATTR_RE = re.compile(
    r"\b\d+[-\u2013](?:months?|years?|weeks?|days?|mois|ans?|jours?|semaines?)\b"
    # v62.13.9.4.25 — contre-audit v24 (§2) : faits de contexte CONNUS du dossier
    # (registre, brief), jamais des cibles à réécrire — « 0 salarié » devenait
    # « des salarié », « 11 ans d'expérience » devenait « une expérience d'un
    # calendrier à arbitrer ». Liste fermée, sans mot de dossier. (L'horizon
    # d'un prévisionnel — « glissant 12 mois » — n'est PAS exempté ici : quand
    # un agent le déclare CIBLE, il doit pouvoir être réécrit en cadre.)
    r"|\b\d{1,2}\s*\+?\s*(?:ans|years?)\s+(?:d['\u2019]|of\s+)(?:exp[ée]rience|interventions?|pratique|m[ée]tier|carri[èe]re|experience|practice)\b"
    r"|\b(?:exp[ée]rience|pratique|carri[èe]re|anciennet[ée]|experience|track\s+record)\s+(?:de|of)\s+\d{1,2}\s*\+?\s*(?:ans|years?)\b"
    # v62.13.9.4.30 — « deux segments : viticulture et espaces verts » : le compte
    # cadre l'énumération qui suit, il ne fixe pas de cible.
    r"|(?<![\w-])(?:deux|trois|quatre|cinq|six|two|three|four|five|six|\d{1,2})\s+"
    r"(?:segments?|m[ée]tiers?|axes?|volets?|piliers?|familles?|gammes?|canaux|canal|business\s+lines?|streams?|pillars?)"
    r"(?=\s*[:—–(])", re.I,
)
# v62.13.9.4.25 — « sept. 2026 », « 15 sept. 2026 » : abréviation de mois, pas
# le nombre sept. Masquée AVANT la date (sinon l'année part d'abord et
# « sept. » reste seul, lu comme un mot-nombre → « . 2026 »).
# v62.13.9.4.25 — « 0 salarié(s) » est un fait de REGISTRE : il vit par son
# claim (liaison de rangée, typeur), jamais par un masque — masquer le zéro
# rendait la rangée « ✅ FAIT | Effectif | 0 salariés | Pappers » invisible à la
# liaison de claim. Le réécriveur, lui, le préserve quand la LIGNE est
# réécrite pour une autre grandeur (« mono-personnelle avec 0 salarié, … »).
REGISTRY_ZERO_RE = re.compile(r"\b0\s+salari[ée]s?\b|\bzero\s+employees?\b", re.I)
_REGISTRY_ZERO_SENTINEL = "\u2063ZEROSALARIE\u2063"
# v62.13.9.4.30 — un mot capitalisé dans un nom propre composé (« Robert Half »,
# « Michael Page ») n'est jamais une quantité : le nom propre est masqué avant
# toute réécriture. Règle générique, sans liste de sociétés.
PROPER_NOUN_RE = re.compile(
    r"\b(?<![.!?]\s)(?<!^)[A-ZÀ-Ÿ][\wÀ-ÿ\'’-]*[a-zà-ÿ][\wÀ-ÿ\'’-]*(?:\s+(?:&|de|du|des|van|von|di|la|le)?\s*[A-ZÀ-Ÿ][\wÀ-ÿ\'’-]*[a-zà-ÿ][\wÀ-ÿ\'’-]*)+(?:\s*(?:S\.?A\.?S?|SARL|SA|GmbH|Ltd|Inc|LLC|BV|NV|AG|SE|SCI|SNC)\b)?")
MONTH_ABBR_RE = re.compile(
    r"\b(?:\d{1,2}(?:er|e)?\s+)?(?:janv|f[ée]vr?|avr|juil|sept?|oct|nov|d[ée]c|jan|feb|mar|apr|jun|jul|aug|sep)\.?\s+(?:19|20)\d\d\b"
    r"|\b\d{1,2}(?:er|e)?\s+(?:janv|f[ée]vr?|avr|juil|sept?|oct|nov|d[ée]c|jan|feb|apr|jun|jul|aug|sep)\.(?!\w)", re.I,
)
# v62.13.9.4.5 — delta de KPI en points (« +4pts », « -3 bps », « +0,5 point ») :
# écart mesuré affiché, pas une cible ; une cible garde son verbe/target word.
PTS_DELTA_RE = re.compile(r"[+\-\u2212\u00b1]\s?\d+(?:[.,]\d+)?\s*(?:pts?|bps|points?)\b", re.I)
# v62.13.9.4.5 — numérotation d'énumération *inline* (« … mode. 2. Arbitrate … ») :
# petit entier après ponctuation forte, suivi d'une majuscule = numéro de liste.
ENUM_INLINE_RE = re.compile(r"(?<=[.;:!?])\s\d{1,2}[.)](?=\s+[A-ZÀ-Ÿ])")
# v62.13.9.4.5 — nom de fichier (extension documentaire, y compris 8.3 « ~1 ») :
# identifiant de source, jamais une quantité.
FILE_REF_RE = re.compile(r"\b[\w~-]+\.(?:pdf|docx?|xlsx?|pptx?|csv|txt|xhtml|html|json)\b", re.I)
# v62.13.9.4.5 — cellule terminale numérique nue d'une ligne de tableau
# (« … | financial_review | 29 ») : référence de page, pas une quantité.
PAGE_CELL_RE = re.compile(r"(?<=\|)\s*\d{1,4}\s*$")
# v62.13.9.4.5 — numérotation de titre de section (« 2.3 Plan d'investissement ») :
# structure documentaire, jamais une quantité.
SECTION_HEAD_RE = re.compile(r"^\s*\d+(?:\.\d+)+\.?\s+")
# v62.13.9.4.5 — compte de découpage conceptuel (« trois piliers », « 5 axes ») :
# structure narrative d'un plan, pas un livrable dénombrable d'action.
STRUCTURE_COUNT_RE = re.compile(
    r"\b(?:\d{1,2}|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|two|three|four|five|six|seven|eight|nine|ten)"
    r"\s+(?:grands?\s+|grandes?\s+|key\s+|main\s+|strategic\s+)?"
    r"(?:axes?|piliers?|volets?|leviers?|chantiers?|orientations?|priorit[ée]s?|pillars?|levers?|workstreams?|streams?)\b",
    re.I,
)
# v62.13.9.4.5 — « un/une » devant un nom de processus/abstraction reste un article ;
# devant un nom concret en contexte d'action, c'est la quantité 1 (P1-01, cas
# « Ouvrir un centre auditif »). Liste générique, versionnée, indépendante du dossier.
_FR_ABSTRACT_AFTER_UN = {
    # v62.13.9.4.31 — contre-audit v30 (§3) : « Lancer un mini-site vitrine » — un
    # support ou un livrable (numérique ou documentaire) n'est pas un compte de un,
    # et l'arbitrage qui le contenait ne doit pas disparaître. « Ouvrir un centre »,
    # « recruter un consultant » restent des comptes.
    "site", "mini-site", "minisite", "page", "profil", "compte", "blog", "newsletter", "landing",
    "vitrine", "plateforme", "portail", "espace", "canal", "website", "webpage", "grille",
    "tableau", "matrice", "registre", "charte", "modèle", "modele", "template", "outil",
    "référentiel", "referentiel", "dossier", "document", "convention", "kit", "guide", "trame",
    "réflexion", "reflexion", "discussion", "démarche", "demarche", "étude", "etude", "analyse", "revue", "audit",
    "consultation", "négociation", "negociation", "procédure", "procedure", "approche", "stratégie", "strategie",
    "politique", "campagne", "mission", "plan", "programme", "projet", "processus", "cadre", "vision", "réunion",
    "reunion", "point", "atelier", "comité", "comite", "décision", "decision", "action", "priorité", "priorite",
    "phase", "étape", "etape", "option", "scénario", "scenario", "orientation", "trajectoire", "dynamique",
    "logique", "culture", "gouvernance", "organisation", "méthode", "methode", "méthodologie", "methodologie",
    "roadmap", "feuille", "initiative", "réponse", "reponse", "opportunité", "opportunite", "alternative",
    "hypothèse", "hypothese", "proposition", "recommandation", "synthèse", "synthese", "note", "annexe",
    "section", "question", "enveloppe", "ambition", "objectif", "cible",
    "gamme", "offre", "calendrier", "niveau", "volume", "partie", "montant", "délai", "delai",
    "horizon", "dimensionnement", "quantum", "base", "baseline", "trajectoire",
    "review", "study", "analysis", "discussion", "process", "plan", "programme", "program",
    "project", "strategy", "campaign", "consultation", "tender", "initiative", "approach",
    "framework", "roadmap", "policy", "procedure", "assessment", "meeting",
    "workshop", "committee", "method", "methodology", "response", "opportunity",
    "alternative", "hypothesis", "proposal", "recommendation", "summary",
    # v62.13.9.4.29 — « Définir une grille de TJM », « un tableau de bord » : un
    # instrument ou un livrable, pas un compte de un (run 08/09 11:34, arbitrage perdu).
    "grille", "tableau", "matrice", "registre", "charte", "modèle", "modele", "template", "outil",
    "référentiel", "referentiel", "dossier", "document", "convention", "kit", "guide", "trame",
    "protocole", "barème", "bareme", "tarification", "grid", "dashboard", "matrix", "register",
    "charter", "model", "tool", "repository", "file", "protocol", "scale",
}
# Position stricte : le déterminant doit être l'objet direct *immédiat* d'un
# verbe d'action en tête de ligne — le français emploie « un/une » partout
# ailleurs (« une levée de fonds », « affiche une perte ») sans quantité.
UN_UNE_HEAD_RE = re.compile(
    r"^\s*(?:[-*•▌✓]+\s*)?"
    r"([A-Za-zà-ÿ][a-zà-ÿ]{2,}(?:er|ir|re|oir)"
    r"|open|launch|build|hire|recruit|invest|deploy|expand|acquire|create|add|sign|close"
    r"|install|equip|convert|integrate|lease|refurbish|onboard|decommission|migrate"
    r"|renovate|extend|renew|secure|win|sell|produce|generate|enter)"
    r"\s+(un|une|a|an|one)\s+"
    r"(?:nouvel(?:le)?s?\s+|nouveaux\s+|new\s+)?"
    r"([a-zà-ÿ][a-zà-ÿ'’-]{2,})",
    re.I,
)

# ── Contexte ──────────────────────────────────────────────────────────────────
COMPLETED_RE = re.compile(
    r"\b(?:tenu|r[ée]alis[ée]|sign[ée]|livr[ée]|achev[ée]|clos|effectu[ée]|termin[ée]|finalis[ée]|accompli|atteint|conclu|obtenu|"
    r"lanc[ée]|ouvert|recrut[ée]|d[ée]ploy[ée]|install[ée]|mis\s+en\s+place|recul[ée]|baiss[ée]|chut[ée]|diminu[ée]|"
    r"held|completed|delivered|signed|achieved|closed|launched|opened|hired|deployed|installed|implemented|"
    r"declined|fell|dropped|decreased|contracted|approuv[ée]|approved|valid[ée]|validated|vot[ée]|voted|"
    r"adopt[ée]|adopted|arr[êe]t[ée]|board-approved|constat[ée])(?:e|es|s)?\b",
    re.I,
)
FUTURE_TARGET_RE = re.compile(
    r"\b(?:d['’]ici|avant|by|objectifs?|cibles?|targets?|ambitions?|à\s+r[ée]aliser|à\s+livrer|à\s+atteindre|à\s+ouvrir|à\s+recruter|"
    r"to\s+deliver|to\s+achieve|to\s+reach|to\s+open|to\s+hire|pr[ée]vu(?:e|s|es)?|planned|expected|projected|forecast|pr[ée]vision(?:s|nel|nelle)?)\b",
    re.I,
)
TARGET_WORDS_RE = re.compile(
    r"\b(?:objectifs?|cibles?|targets?|ambitions?|kpis?|indicateurs?\s+de\s+(?:succ[èe]s|performance)|budgets?|enveloppes?|"
    r"pr[ée]visions?|forecasts?|projections?|sc[ée]narios?|scenarios?|seuils?|thresholds?|goals?|milestones?|jalons?|"
    r"base\s+case|bear|bull|severe|potentiel|potential|hypoth[èe]ses?|assumptions?)\b",
    re.I,
)
HORIZON_RE = re.compile(
    r"\b(?:d['’]ici|avant\s+(?:fin|la\s+fin)?|à\s+horizon|à\s+l['’]horizon|by|within|d['’]ici\s+à|sur\s+\d+\s*(?:mois|ans|ann[ée]es|semaines|trimestres)|"
    r"over\s+(?:the\s+next\s+)?\d+\s*(?:months?|years?|weeks?|quarters?)|in\s+the\s+next|au\s+cours\s+des\s+\d+\s+prochains?|prochains?\s+(?:mois|ans|trimestres))\b",
    re.I,
)
DURATION_RE = re.compile(
    r"(?<![\w/])\d+(?:[.,]\d+)?(?:\s*(?:[-–]|à|to)\s*\d+(?:[.,]\d+)?)?\s*(?:mois|ans?|ann[ée]es?|semaines?|jours?|trimestres?|"
    r"months?|years?|weeks?|days?|quarters?)\b",
    re.I,
)
MONEY_RE = re.compile(
    rf"(?:{_CURRENCY}\s*{_DIGIT}{_SUFFIX}|{_DIGIT}{_SUFFIX}\s*{_CURRENCY}|{_DIGIT}\s*(?:k|m|bn|md|mio)(?![a-zà-ÿA-Z])\b)",
    re.I,
)
PLANNING_WORD_RE = re.compile(
    r"\b(?:d[ée]lais?|delays?|implementation|mise\s+en\s+[œo]uvre|rollout|d[ée]ploiements?|deployments?|lead\s*time|"
    r"homologation|recrutements?|recruitment|lancements?|launch|horizon|calendrier|schedule|timeline|roadmap|feuille\s+de\s+route|"
    r"sur|over|within|d['’]ici|pendant|during)\b",
    re.I,
)
STATIVE_PRESENT_RE = re.compile(
    r"\b(?:compte|comptent|comptait|comptaient|poss[èe]de|poss[èe]dent|dispose|disposent|comprend|comprennent|"
    r"inclut|incluent|emploie|emploient|exploite|exploitent|op[èe]re|op[èe]rent|d[ée]tient|d[ée]tiennent|"
    r"regroupe|regroupent|totalise|totalisent|r[ée]unit|r[ée]unissent|rassemble|rassemblent|repr[ée]sente|repr[ée]sentent|"
    r"includes?|included|comprises?|owns?|operates?|employs?|consists?|contains?|counts?|numbers|has|have)\b",
    re.I,
)
FUTURE_VERB_RE = re.compile(
    r"\b(?:sera|seront|serait|seraient|aura|auront|aurait|auraient|fera|feront|ferait|feraient|devra|devront|devrait|devraient|"
    r"pourra|pourront|pourrait|pourraient|ira|iront|irait|iraient|va|vont|vise|visent|vis[ée]|"
    r"pr[ée]voit|pr[ée]voient|ambitionne|ambitionnent|souhaite|souhaitent|entend|entendent|veut|veulent|"
    r"will|shall|should|must|aims?|intends?|expects?|targets?|seeks?|wants?|commits?|plans?\s+to)\b|"
    r"\bcompt(?:e|ent)\s+(?=[a-zà-ÿ]{3,}(?:er|ir|oir)\b)|"
    r"\b[a-zà-ÿ]{2,}(?:era|eront|erons|erez|erait|eraient|ira|iront|irons|irez|irait|iraient|dra|dront|drons|drait|draient|rrait|rraient)\b",
    re.I,
)
EN_VERB_RE = re.compile(
    r"\b(?:open|launch|recruit|hire|sign|deploy|invest|budget|fund|finance|moderni[sz]e|renovate|migrate|build|expand|roll\s+out|"
    r"convert|acquire|close|reduce|increase|grow|double|triple|reach|deliver|sell|produce|train|equip|create|add|cut|raise|lower|"
    r"achieve|generate|win|secure|install|implement|scale|enter|exit|upgrade|replace|consolidate|optimi[sz]e|negotiate|renew|extend|"
    r"refurbish|onboard|lease|decommission|integrate|retrofit|relocate|"
    r"recruiting|hiring|opening|launching|investing|deploying|building|expanding|converting|acquiring|closing|reducing|increasing)\b",
    re.I,
)
_EN_INITIAL_STOP = {
    "the", "this", "that", "these", "those", "our", "their", "its", "his", "her", "a", "an", "it", "he", "she", "we", "they",
    "i", "you", "total", "net", "gross", "revenue", "revenues", "sales", "profit", "margin", "cash", "debt", "group", "board",
    "plan", "plans", "target", "targets", "focus", "update", "status", "summary", "overview", "context", "note", "notes",
    "page", "slide", "table", "figure", "source", "detail", "details", "horizon", "budget", "forecast", "outlook", "risk",
    "risks", "action", "actions", "next", "key", "item", "items", "agenda", "minutes", "section", "annex", "appendix",
    "fact", "facts", "kpi", "kpis", "scope", "team", "project", "phase", "step", "option", "scenario", "result", "results",
    "impact", "cost", "costs", "price", "prices", "volume", "volumes", "share", "growth", "performance", "capex", "opex",
    "ebitda", "network", "market", "company", "committee", "there", "here", "each", "every", "all", "some", "no", "not",
    # v62.13.9.4.5 — un mot-nombre initial est un cardinal, jamais un verbe.
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "fifteen", "twenty", "thirty", "forty", "fifty", "hundred", "thousand",
}
_FR_HINT_RE = re.compile(r"[àâäéèêëîïôöùûüç]|\b(?:le|la|les|des|du|de|et|ou|à|un|une|pour|dans|sur|par|avec|est|sont|d['’]|l['’])\b", re.I)
_EN_HINT_RE = re.compile(r"\b(?:the|of|and|to|in|for|with|new|is|are|was|were|by|per)\b", re.I)
_INFINITIVE_STOP = {
    "centre", "centres", "cadre", "cadres", "chiffre", "chiffres", "titre", "titres", "ordre", "ordres", "membre", "membres",
    "nombre", "nombres", "périmètre", "perimetre", "chapitre", "registre", "offre", "offres", "chambre", "livre", "arbre",
    "fenêtre", "ministre", "propre", "autre", "autres", "notre", "votre", "entre", "contre", "dossier", "dossiers", "atelier",
    "ateliers", "calendrier", "chantier", "chantiers", "cahier", "métier", "metier", "métiers", "quartier", "courrier",
    "dernier", "premier", "premiers", "plaisir", "loisir", "avenir", "désir", "souvenir", "plusieurs", "hier", "papier",
    "fichier", "panier", "pilier", "piliers", "financier", "immobilier", "particulier", "trésorerie", "tresorerie", "fer",
    "hiver", "cher", "clair", "leader", "manager", "cluster", "master", "sinistre", "cylindre", "spectre",
    "tendre", "encore", "mètre", "kilomètre", "baromètre", "théâtre", "orchestre", "semestre", "trimestre",
    "compte", "coûts", "genre", "moindre", "salaire", "salaires", "inventaire", "partenaire", "partenaires", "actionnaire",
    "actionnaires", "affaire", "affaires", "territoire", "laboratoire", "répertoire", "annuaire", "nécessaire",
    "gestionnaire", "gestionnaires", "prestataire", "prestataires", "propriétaire", "supplémentaire", "complémentaire",
    "prioritaire", "réglementaire", "sanitaire", "bancaire", "sommaire", "commentaire", "commentaires",
    "voir", "espoir", "soir", "miroir", "couloir", "trottoir", "pouvoir", "devoir", "savoir", "mémoire", "histoire",
    "victoire", "poire", "foire", "gloire", "obligatoire", "provisoire", "transitoire", "aléatoire",
    "acier", "palier", "escalier", "levier", "clavier", "sentier", "collier", "soulier", "boursier", "janvier", "février",
}
INFINITIVE_RE = re.compile(r"\b([a-zà-ÿ]{3,}(?:er|ir|re|oir))\b", re.I)
NOMINALISATION_RE = re.compile(
    r"\b([a-zà-ÿ]{4,}(?:tion|sion|ment|age|ure|isation|ement|ance|ence|ing))\s+(?:de|des|du|d['’]|sur|dans|vers|en|of|in|on|to|across)\s+", re.I,
)
_NOMINAL_STOP = {
    "situation", "position", "condition", "attention", "mention", "question", "notion", "fonction", "direction", "gestion",
    "information", "documentation", "présentation", "relation", "mission", "vision", "décision", "dimension", "commission",
    "réunion", "version", "pression", "occasion", "impression", "expression", "tradition", "édition",
    "département", "moment", "élément", "environnement", "gouvernement", "événement", "document", "règlement", "segment",
    "équipement", "traitement", "comportement", "compartiment", "fondement", "sentiment", "jugement", "instrument",
    "arrangement", "paiement", "chargement", "logement", "bâtiment", "avantage", "usage", "image", "message", "village",
    "voyage", "page", "étage", "stage", "pourcentage", "chômage", "nuage", "langage", "package", "mesure", "structure",
    "nature", "culture", "facture", "figure", "voiture", "lecture", "signature", "fermeture", "ouverture", "couverture",
    "procédure", "aventure", "candidature", "nourriture", "peinture", "température", "chance", "finance", "finances",
    "distance", "importance", "assurance", "balance", "confiance", "croissance", "instance", "puissance", "séance",
    "substance", "tendance", "conférence", "différence", "expérience", "influence", "présence", "référence", "science",
    "urgence", "agence", "audience", "concurrence", "essence", "évidence", "fréquence", "licence", "patience", "résidence",
    "existence", "compétence", "absence", "conséquence", "exigence", "meeting", "marketing", "holding", "pricing", "reporting",
    "sourcing", "consulting", "branding", "packaging", "leasing", "rating", "training", "building", "housing",
}
DECISION_VERB_RE = re.compile(
    r"\b(?:approuver|approuve[rz]?|valider|validez|autoriser|engager|d[ée]cider|voter|arbitrer|approve|authori[sz]e|"
    r"commit|sign[- ]off|decide|ratify|endorse)\b",
    re.I,
)

_ACTION_REASONS = {"infinitive", "mid_infinitive", "en_verb", "en_verb_structural", "future_verb"}


def _blank(text: str, pattern: re.Pattern[str]) -> str:
    return pattern.sub(lambda m: " " * len(m.group(0)), text)


# v62.13.9.4.48 — la nomenclature et les autres non-quantités sont désormais définies une seule
# fois, dans utils/non_quantity.py, pour tous les chemins de production (corpus de frontières :
# un identifiant étiqueté (« CIK SEC nnnnnn ») était une quantité ici, un identifiant dans l'index déclaré).
from utils.non_quantity import NOMENCLATURE_RE as _NOMENCLATURE_RE45, mask_non_quantities as _mask_nq48, ALL as _NQ_ALL48


def mask_exempt(text: str, *, action: bool = False) -> str:
    """Masque (même longueur) ce qui n'est jamais une quantité prospective.

    En contexte d'ACTION, la tranche d'effectif n'est plus une exemption : portée
    par un verbe (« Recruter 200–249 collaborateurs »), c'est une cible.
    """
    # v62.13.9.4.45 — NOMENCLATURE. Run réel du 26/09/2026 : « Scope 3 » est devenu
    # « Scope some ». Un numéro de nomenclature — Scope 1/2/3, Option 2, Phase 1, Q3, H1,
    # Tier 1, ISO 9001, IFRS 16, Pillar 2, Top 10 — n'est pas une quantité et ne se
    # neutralise jamais.
    text = _mask_nq48(str(text or ""), kinds=_NQ_ALL48)      # v62.13.9.4.48 — définition partagée
    masked = str(text or "")
    patterns = [PROPER_NOUN_RE, MONTH_ABBR_RE, STANDARD_RE, IDENTIFIER_RE, DATE_RE, CODE_RE, DESCRIPTIVE_NUMBER_RE, PLANNING_CONTRACT_RE, ATTRIBUTE_RE, SCORE_RE,
                DURATION_ATTR_RE, ENUM_INLINE_RE, SECTION_HEAD_RE, STRUCTURE_COUNT_RE, FILE_REF_RE, PAGE_CELL_RE]
    # v62.13.9.4.5 — le delta en points est un écart *mesuré* affiché, sauf sur une
    # ligne de cible/KPI explicite où il redevient une cible chiffrée à retenir.
    if not TARGET_WORDS_RE.search(masked):
        patterns.append(PTS_DELTA_RE)
    if not action:
        patterns.append(BAND_RE)
    for pattern in patterns:
        masked = _blank(masked, pattern)
    return ENUMERATOR_RE.sub(lambda m: " " * len(m.group(0)), masked)


def cardinal_spans(text: str, *, action: bool = False) -> list[tuple[int, int, str]]:
    """Cardinaux résiduels sous toutes leurs formes, hors exemptions."""
    original = str(text or "")
    masked = mask_exempt(original, action=action)
    spans = [(m.start(), m.end(), m.group(0)) for m in CARDINAL_RE.finditer(masked)]
    for m in NUMBER_WORDS_RE.finditer(masked):
        token = m.group(0)
        if len(token) >= 3 and token.lower() not in ("un", "une"):
            spans.append((m.start(), m.end(), token))
    for pattern in (APPROX_QUANTITY_RE, FRACTION_RE, ROMAN_RE):
        for m in pattern.finditer(masked):
            spans.append((m.start(), m.end(), original[m.start():m.end()]))
    if action:
        # v62.13.9.4.5 — « Ouvrir un centre auditif » : « un/une/a/an/one » en
        # objet direct immédiat d'un verbe d'action de tête est la quantité 1 ;
        # devant un nom de processus/abstraction (liste générique bilingue),
        # l'article reste un article. La position de tête élimine le « un/une »
        # narratif français (« une levée de fonds », « affiche une perte »).
        m = UN_UNE_HEAD_RE.match(masked)
        if m:
            head = m.group(1).lower()
            fr_head = bool(re.fullmatch(r"[a-zà-ÿ]+(?:er|ir|re|oir)", head))
            head_ok = (not fr_head) or (
                INFINITIVE_RE.fullmatch(head) is not None and head not in _INFINITIVE_STOP
            )
            noun = m.group(3).lower().replace("’", "'")
            if head_ok and noun not in _FR_ABSTRACT_AFTER_UN:
                spans.append((m.start(2), m.end(2), m.group(2)))
    spans.sort()
    merged: list[tuple[int, int, str]] = []
    for span in spans:
        if merged and span[0] < merged[-1][1]:
            continue
        merged.append(span)
    return merged


def residual_cardinals(text: str, *, action: bool = False) -> list[str]:
    return [tok for _, _, tok in cardinal_spans(text, action=action)]


def is_completed_fact(text: str) -> bool:
    value = str(text or "")
    return bool(COMPLETED_RE.search(value)) and not FUTURE_TARGET_RE.search(value)


def is_stative_present_fact(text: str) -> bool:
    """« compte / possède / includes / has » au présent = fait, pas engagement —
    sauf s'il introduit un infinitif (« compte ouvrir ») ou un marqueur futur."""
    value = str(text or "")
    m = STATIVE_PRESENT_RE.search(value)
    if not m:
        return False
    tail = value[m.end():m.end() + 34].strip().replace("’", "'")
    first_tail = re.match(r"[a-zà-ÿ'-]+", tail, re.I)
    if first_tail and INFINITIVE_RE.fullmatch(first_tail.group(0).lower()) and first_tail.group(0).lower() not in _INFINITIVE_STOP:
        return False
    if FUTURE_TARGET_RE.search(value) or HORIZON_RE.search(value):
        return False
    lexical_future = re.search(
        r"\b(?:sera|seront|aura|auront|fera|feront|devra|devront|pourra|pourront|va|vont|vise|visent|will|shall|must|aims?|plans?\s+to)\b",
        value, re.I)
    return not lexical_future


def _reference_year(reference_year: int | None) -> int:
    return int(reference_year) if reference_year else _dt.date.today().year


def _past_year_marker(text: str, reference_year: int | None) -> bool:
    ref = _reference_year(reference_year)
    years = [int(y) for y in re.findall(r"\b((?:19|20)\d\d)\b", text)]
    return bool(years) and all(y <= ref for y in years) and not FUTURE_TARGET_RE.search(text) and not HORIZON_RE.search(text)


def _first_content_word(text: str) -> str:
    stripped = ENUMERATOR_RE.sub("", str(text or "")).strip(" \t-–—•▌✓")
    m = re.match(r"[A-Za-zÀ-ÿ'’-]+", stripped)
    return m.group(0) if m else ""


def starts_with_infinitive(text: str) -> bool:
    raw = _first_content_word(text)
    if raw.isupper():  # « VALIDER », « À VÉRIFIER » : statuts, pas actions
        return False
    word = raw.lower().replace("’", "'")
    if len(word) < 4 or not INFINITIVE_RE.fullmatch(word) or word in _INFINITIVE_STOP:
        return False
    return True


def has_mid_infinitive(text: str, *, action_spans: list[tuple[int, int, str]] | None = None) -> bool:
    """Infinitif après de/à/pour/… suivi d'un cardinal : l'action porte sur la quantité.
    Les statuts en capitales (« À VÉRIFIER ») ne sont pas des actions."""
    spans = action_spans if action_spans is not None else cardinal_spans(text, action=True)
    for m in re.finditer(r"(?<![\w])(?:de|à|pour|afin\s+de|consiste\s+à|vise\s+à|permettant\s+de|en\s+vue\s+de|objectif\s+de|plan\s+(?:de|pour)|:|[—–-])\s+([a-zà-ÿA-ZÀ-Ÿ]{4,}(?:er|ir|re|oir|ER|IR|RE|OIR))\b", text):
        token = m.group(1)
        if token.isupper() or token.lower() in _INFINITIVE_STOP:
            continue
        if not INFINITIVE_RE.fullmatch(token.lower()):
            continue
        if any(start > m.end() and start - m.end() <= 80 for start, _end, _tok in spans):
            return True
    return False


def has_nominalisation_of(text: str) -> bool:
    for m in NOMINALISATION_RE.finditer(text):
        if m.group(1).lower() not in _NOMINAL_STOP:
            return True
    return False


def _en_structural_verb(text: str) -> bool:
    """Verbe impératif EN en tête de phrase, au-delà de toute liste : mot ASCII
    capitalisé, hors nominaux connus, sur une ligne sans indices FR, suivi d'un
    cardinal qui n'est pas un génitif (« of 600 »)."""
    value = ENUMERATOR_RE.sub("", str(text or "")).strip()
    # v62.13.9.4.5 — un marqueur de statut de fait en tête (« ✅ FACT | … »,
    # « FAIT — … ») désigne une ligne de preuve, jamais un impératif.
    if re.match(r"^[✅✔️☑️\s]*(?:FACT|FAIT)\b", str(text or "").strip(), re.I):
        return False
    m = re.match(r"([A-Z][a-z]{2,})\b", value)
    if not m:
        return False
    word = m.group(1).lower()
    if word in _EN_INITIAL_STOP or word in _INFINITIVE_STOP:
        return False
    if _FR_HINT_RE.search(value):
        return False
    # v62.13.9.4.8 (terrain réel du 13/08/2026) — l'euro collé à un cardinal,
    # sans aucun autre indice anglais dans la ligne, désigne une ligne
    # européenne : un unique mot capitalisé ambigu (« Arbitrage », « Budget »)
    # n'y vaut pas impératif EN, et la réécriture reste en français.
    if re.search(r"\d\s*(?:€|k€|M€)", value) and not _EN_HINT_RE.search(value):
        return False
    spans = cardinal_spans(value, action=True)
    for start, _end, _tok in spans:
        if m.end() <= start <= m.end() + 60:
            gap = value[m.end():start]
            # v62.13.9.4.5 — « | » (cellule de tableau) comme « : » : le nombre
            # appartient à un libellé technique, pas à un impératif.
            if re.search(r"\b(?:of|per|at|in|by|from|to|for)\s*$", gap, re.I) or ":" in gap or "|" in gap:
                continue
            return True
    return False


_FR_MORPH_RE = re.compile(r"\b[a-zà-ÿ]{3,}(?:eurs?|euses?|tions?|ments?|it[ée]s?|aires?|ismes?|ances?|ences?)\b|\b[a-zà-ÿ]{4,}(?:er|ir)\b\s+(?:\d|[IVX]{1,4}\b)")


_EN_ER_WORDS36 = frozenset((
    "whether", "other", "another", "never", "ever", "over", "under", "after", "together",
    "either", "neither", "rather", "further", "former", "latter", "later", "better", "order",
    "number", "member", "customer", "supplier", "partner", "manager", "leader", "driver",
    "player", "buyer", "seller", "offer", "cover", "deliver", "consider", "gather", "answer",
    "power", "water", "paper", "silver", "copper", "computer", "center", "centre", "user",
    "owner", "holder", "worker", "officer", "engineer", "quarter", "winter", "summer",
    "wider", "higher", "lower", "faster", "slower", "greater", "smaller", "larger", "fewer",
    "longer", "shorter", "stronger", "weaker", "earlier", "cheaper", "safer", "closer",
))


_AGENT_TAG38 = re.compile(r"\[(?:NON\s+SOURC[ÉE]|ESTIM(?:-|\s)HYPOTH[ÈE]SE|HYPOTH[ÈE]SE|[ÀA]\s+V[ÉE]RIFIER|FAIT|FACT|"
                          r"ESTIM\s+IA|UNSOURCED|TO\s+VERIFY|SC[ÉE]NARIO[^\]]*|SCENARIO[^\]]*|CIBLE\s+VALID[ÉE]E|"
                          r"VALIDATED\s+TARGET)\]", re.I)


def line_language(text: str, fallback: str = "fr") -> str:
    value = str(text or "")
    # v62.13.9.4.38 — LES ÉTIQUETTES D'AGENTS NE SONT PAS DES INDICES DE LANGUE. Deux
    # dossiers anglais réels du 19/09/2026 : « - Prioritize growth in Asia-Pacific
    # [NON SOURCÉ] … » était jugé FRANÇAIS sur le É de l'étiquette — vocabulaire fixe
    # des agents dans les deux langues — puis réécrit en français. Les étiquettes sont
    # retirées avant toute détection. Et dans un run anglais, un seul indice
    # MORPHOLOGIQUE (« clearance » pris pour un mot en -ance) ne l'emporte pas sur un
    # indice anglais net.
    if str(fallback).lower().startswith("en"):
        value = _AGENT_TAG38.sub(" ", value)
    # v62.13.9.4.37 — DANS UN RUN ANGLAIS, UN MOT EN -ER N'EST PAS UN INFINITIF FRANÇAIS.
    # Deux runs réels du 18/09/2026 : les questions ouvertes (« Whether the board
    # wants… ») basculaient en français — « whether » passait pour un verbe du premier
    # groupe — et recevaient « un niveau à dimensionner » (16 et 14 occurrences). Quand
    # le document est anglais et que la ligne porte un indice anglais net, la seule
    # morphologie ne suffit plus à la déclarer française.
    _run_en = str(fallback).lower().startswith("en")
    _first = _first_content_word(value).lower().strip(".,;:")
    _infinitive = starts_with_infinitive(value) and not (_run_en and _first in _EN_ER_WORDS36)
    if _run_en and _infinitive and _EN_HINT_RE.search(value) and not _FR_HINT_RE.search(value):
        _infinitive = False
    if _run_en:
        # DANS UN RUN ANGLAIS, seuls des MOTS-OUTILS FRANÇAIS déclarent une ligne
        # française : un accent (Hermès, Loewe, Zoë), une terminaison (-tion, -ment,
        # -ance : competition, investment, clearance) ou un mot en -er sont des
        # cognats et des noms propres ordinaires en anglais. Sur deux dossiers réels du
        # 19/09/2026, un tiers des lignes anglaises étaient jugées françaises par ces
        # seuls indices. Une vraie ligne française dans un document anglais porte ses
        # mots-outils.
        _fw = len(re.findall(r"(?i)\b(?:le|la|les|des|du|de|et|ou|à|un|une|pour|dans|sur|par|avec|est|sont|"
                             r"d['’]|l['’]|aux|au|ce|cette|ces|qui|que|nous|vous|ils|elles)\b", value))
        if _fw >= 2 or (_infinitive and _fw >= 1):
            return "fr"
        return "en"
    _fr_hint = bool(_FR_HINT_RE.search(value))
    _fr_morph = bool(_FR_MORPH_RE.search(value))
    if _fr_hint or _fr_morph or _infinitive:
        return "fr"
    if _EN_HINT_RE.search(value) or EN_VERB_RE.match(_first_content_word(value)):
        return "en"
    # v62.13.9.4.26 — run 13:10 sur la 9.4.25 : « Activation LinkedIn intensive
    # (2 posts/semaine) » et « Constitution liste 50 ETI » basculaient en anglais
    # (« some posts/semaine », « volume to validate ») : un nom déverbal français
    # capitalisé passait pour un impératif anglais. Dans un document français,
    # la forme structurelle seule ne suffit plus — il faut un verbe anglais
    # connu ou un mot-outil anglais ; la langue du document fait foi.
    if _en_structural_verb(value) and str(fallback).lower().startswith("en"):
        return "en"
    return "en" if str(fallback).lower().startswith("en") else "fr"


# v62.13.9.4.11 — CADENCE d'action : « Publier un post LinkedIn/semaine »
# énonce un rythme opérationnel dont l'unité est l'article indéfini, pas une
# grandeur d'affaires. Le contre-audit du 31/08/2026 a relevé le blocage de
# cette ligne dans le deck dossier de conseil réel : faux rouge sur dossier de
# référence, donc P0 au protocole. Règle bornée — marqueur de périodicité
# EXIGÉ et aucun chiffre ailleurs, si bien que « Publier 3 posts/semaine »
# reste jugé normalement.
_CADENCE_PERIOD_RE = re.compile(
    r"(?:/|\bpar\s+|\bper\s+|\bchaque\s+|\ba\s+)"
    r"(?:semaine|mois|jour|trimestre|an|ann[ée]e|week|month|day|quarter|year)\b"
    r"|\b(?:hebdomadaire|mensuel(?:le)?s?|quotidien(?:ne)?s?|trimestriel(?:le)?s?|"
    r"weekly|monthly|daily|quarterly)\b", re.I)


def is_action_cadence(text: str) -> bool:
    """Rythme d'action sans aucun cardinal : l'unité y est un article."""
    value = str(text or "")
    if re.search(r"\d", value):
        return False
    return bool(_CADENCE_PERIOD_RE.search(value))


def action_signal(text: str) -> bool:
    """Vrai si la phrase est portée par un verbe d'action/engagement (structure, pas liste)."""
    value = ENUMERATOR_RE.sub("", str(text or "")).strip()
    if not value or is_completed_fact(value) or is_stative_present_fact(value):
        return False
    if is_action_cadence(value):
        return False
    if starts_with_infinitive(value) or has_mid_infinitive(value):
        return True
    if EN_VERB_RE.match(_first_content_word(value)) or _en_structural_verb(value):
        return True
    if DECISION_VERB_RE.search(value):
        return True
    return bool(FUTURE_VERB_RE.search(value))


def prospective_context(text: str, *, reference_year: int | None = None) -> str | None:
    """Raison structurelle si la phrase porte un engagement/cible prospectif, sinon None."""
    value = ENUMERATOR_RE.sub("", str(text or "")).strip()
    if not value:
        return None
    if is_completed_fact(value):
        return None
    # v62.13.9.4.11 — cadence d'action : même exemption que dans
    # ``action_signal``. Le gate consulte cette fonction, pas l'autre : sans
    # la poser ici, « Publier un post LinkedIn/semaine » restait bloqué.
    if is_action_cadence(value):
        return None
    if is_stative_present_fact(value):
        return None
    if (_past_year_marker(value, reference_year) and not TARGET_WORDS_RE.search(value)
            and not starts_with_infinitive(value) and not EN_VERB_RE.match(_first_content_word(value))
            and not _en_structural_verb(value)):
        return None
    if TARGET_WORDS_RE.search(value):
        return "target_word"
    if starts_with_infinitive(value):
        return "infinitive"
    if has_mid_infinitive(value):
        return "mid_infinitive"
    if EN_VERB_RE.match(_first_content_word(value)):
        return "en_verb"
    if _en_structural_verb(value):
        return "en_verb_structural"
    if FUTURE_VERB_RE.search(value):
        return "future_verb"
    if has_nominalisation_of(value):
        return "nominalisation"
    if HORIZON_RE.search(value):
        return "horizon"
    masked = mask_exempt(value, action=action_signal(value))
    if DURATION_RE.search(masked) and PLANNING_WORD_RE.search(value):
        return "duration"
    return None


def _normalise_number(token: str) -> str:
    return re.sub(r"[^\d]", "", str(token or ""))


def unsupported_quantity(
    text: str,
    *,
    reference_year: int | None = None,
    authoritative_values: set[str] | list[str] | None = None,
) -> str | None:
    """Cardinal résiduel + contexte prospectif ⇒ quantité non étayée (raison), sinon None.

    ``authoritative_values`` : valeurs du contrat de planification (Temporal Core) —
    une ligne d'horizon/durée/cible dont TOUS les cardinaux appartiennent à
    l'autorité n'est pas retenue (« Horizon : 24 mois » quand l'autorité dit 24).
    """
    reason = prospective_context(text, reference_year=reference_year)
    if not reason:
        return None
    act = reason in _ACTION_REASONS or action_signal(text)
    residuals = residual_cardinals(text, action=act)
    if not residuals:
        return None
    if authoritative_values and reason in ("duration", "horizon", "target_word"):
        allowed = {_normalise_number(v) for v in authoritative_values if _normalise_number(v)}
        found = {_normalise_number(tok) for tok in residuals}
        found = {f for f in found if f}
        if found and found <= allowed:
            return None
    return reason


# ── Réécriture v3 ─────────────────────────────────────────────────────────────
_PREP_STOP = {
    "dans", "pour", "avec", "sans", "sur", "sous", "chez", "vers", "par", "de", "du", "des", "et", "ou", "à", "en", "les",
    "une", "un", "le", "la", "que", "qui", "dont", "afin", "selon", "entre", "après", "avant", "depuis", "pendant", "contre",
    "of", "in", "for", "with", "without", "on", "under", "by", "to", "and", "or", "the", "a", "an", "that", "which", "per",
    "from", "into", "over", "at", "as", "than", "then",
}
_FEMININE_HINT = re.compile(r"(?:e|ion|té|ance|ence|ure|ade|ée|ie|esse|ette|elle|ique)$", re.I)
_COUNT_NOUN_RE = re.compile(
    rf"(?<![\w.,/:])(?:(?:plus|moins|pr[èe]s|environ|autour|au\s+moins|au\s+plus|jusqu['’]à|about|around|at\s+least|up\s+to|over|more\s+than|less\s+than)\s+(?:de\s+|d['’])?)?"
    rf"(?P<num>{_DIGIT}(?:\s*(?:[-–]|à|to)\s*{_DIGIT})?{_SUFFIX}|{NUMBER_WORDS_RE.pattern}|XX+|NN+|[IVX]{{1,4}})\s+"
    r"(?P<adj>(?:nouveaux?|nouvelles?|new|premi(?:er|ers|ère|ères)|grands?|grandes?|petit(?:s|es?)?|principa(?:l|ux|le|les)|autres?|additional|extra)\s+)?"
    r"(?P<noun>points?\s+de\s+vente|points?\s+of\s+sale|[a-zà-öø-ÿA-ZÀ-Ö][\w'’-]{2,})",
    re.I,
)
_ARTICLE_BEFORE_RE = re.compile(r"\b(les|des|ces|ses|nos|vos|leurs|the|these|those|our|their)\s+$", re.I)
MARK_FR = " — volume à valider"
MARK_EN = " — volume to validate"


def contract_articles(text: str) -> str:
    out = text
    out = re.sub(r"\b(?:plus|moins|pr[èe]s|environ|au\s+moins|au\s+plus)\s+de\s+des\b", "des", out, flags=re.I)
    out = re.sub(r"\bde\s+des\b", "des", out, flags=re.I)
    out = re.sub(r"\bde\s+les\b", "des", out, flags=re.I)
    out = re.sub(r"\bde\s+une\b", "d’une", out, flags=re.I)
    out = re.sub(r"\bde\s+un\b", "d’un", out, flags=re.I)
    out = re.sub(r"\bà\s+les\b", "aux", out, flags=re.I)
    out = re.sub(r"\bà\s+le\b", "au", out, flags=re.I)
    out = re.sub(r"\bof\s+some\b", "of", out, flags=re.I)
    return re.sub(r"\s{2,}", " ", out).strip()


def rewrite_counts(text: str, lang: str = "fr") -> tuple[str, bool]:
    """« N <nom> » → « des <nom> » (tout nom, sauf identifiants/unités/prépositions), marqueur unique en fin."""
    lang = line_language(text, lang)
    act = action_signal(text)
    masked = mask_exempt(text, action=act)
    marked = False
    pieces: list[str] = []
    last = 0
    for m in _COUNT_NOUN_RE.finditer(masked):
        noun = text[m.start("noun"):m.end("noun")]
        if noun.lower() in _PREP_STOP or re.fullmatch(r"(?:%|pts?|points?|pp|bps|x|k|m|bn|md|mio|million(?:s)?|milliard(?:s)?|mois|semaines?|jours?|ans?|ann[ée]es?|h|heures?|hours?|days?|weeks?|months?|years?|km|kwh|kg|t|tonnes?|m²|m2|ha|fois|times)", noun, re.I):
            continue
        num = m.group("num").replace(" ", "").lower()
        adj = text[m.start("adj"):m.end("adj")] if m.group("adj") else ""
        if re.fullmatch(r"1(?:[.,]0+)?|one", num):
            if lang.startswith("en"):
                head = (adj or noun).lstrip()
                article = "an" if head[:1].lower() in "aeiou" else "a"
            else:
                article = "une" if _FEMININE_HINT.search(noun) else "un"
        else:
            article = "some" if lang.startswith("en") else "des"
        pieces.append(text[last:m.start()])
        if _ARTICLE_BEFORE_RE.search(text[:m.start()]):
            pieces.append(f"{adj}{noun}")  # « sur les 3 piliers » → « sur les piliers »
        else:
            pieces.append(f"{article} {adj}{noun}")
        last = m.end()
        marked = True
    pieces.append(text[last:])
    out = "".join(pieces)
    if marked:
        mark = MARK_EN if lang.startswith("en") else MARK_FR
        out = re.sub(r"\s*—\s*volume (?:à valider|to validate)", "", out, flags=re.I).rstrip()
        tail = ""
        if out and out[-1] in ".!?":
            tail, out = out[-1], out[:-1].rstrip()
        out = out + mark + tail
    return out, marked


_PERIOD_FR = {"j": "jour", "jour": "jour", "h": "heure", "heure": "heure", "mois": "mois",
              "semaine": "semaine", "day": "jour", "month": "mois", "hour": "heure", "week": "semaine"}
_PERIOD_EN = {"j": "day", "jour": "day", "h": "hour", "heure": "hour", "mois": "month",
              "semaine": "week", "day": "day", "month": "month", "hour": "hour", "week": "week"}


# v62.13.9.4.34 (lot 2, resserré après le contre-audit juridique v2 du 14/09/2026) —
# les guillemets ne protègent qu'un NOM, pas n'importe quel contenu cité :
# « DAF de crise 90 jours » est une dénomination ; « objectif : 20 % de marge dès
# 2027 » est une assertion chiffrée et doit être neutralisée comme telle. Un nom
# est court, sans verbe conjugué, sans deux-points, et son chiffre est collé à son
# libellé (« 90 jours », « 30 », « V2 »), pas introduit par un mot de visée.
_QUOTED_SPAN34 = re.compile(r"[«\u201C\"][^«»\u201C\u201D\"\n]{3,60}[»\u201D\"]")
_NOT_A_NAME34 = re.compile(
    r"(?i)[:;]|\b(?:objectif|cible|vise[rz]?|viser|atteindre|target|aim|reach|goal)\b"
    r"|\b(?:est|sont|sera|seront|doit|doivent|permet|génère|représente|s['’]élève|atteint"
    r"|is|are|will|shall|must|reaches|generates|represents)\b"
    r"|[%€$£]|\b(?:M€|k€|bn|m£)\b")


# v62.13.9.4.34 (lot 3) — UN FAIT SOURCÉ À LA PAGE N'EST PAS UNE CIBLE, mais la
# citation ne couvre QUE le fait. Contre-audit de publication du 14/09/2026 (run
# réel dossier réseau de soins) : « Résultat net IAV : 4,2 M€ (2022) — plaquette 2022, p.13 »,
# sous un titre « base financière confirmée à la page », était réécrit en « une
# enveloppe à dimensionner » : le contrôle des grandeurs contredisait la couche
# de preuve. Contre-audit juridique v2 : l'exemption ne peut pas être générale —
# une projection présente dans la même phrase (« viser 3 000 M£ en 2029 ») reste
# neutralisée. On protège donc le SEGMENT factuel : du début de la ligne jusqu'au
# séparateur qui introduit la source, et rien après.
_PAGE_CITED34 = re.compile(
    r"[—–\-|;]\s*(?=[^\n]{0,120}?\b(?:p\.?|page|pp\.?)\s*\d{1,4}\b)"
    r"|\((?=[^)\n]{0,80}?\b(?:p\.?|page)\s*\d{1,4}\))", re.I)
_PROJECTION_MARK34 = re.compile(
    r"(?i)\b(?:viser|vise[rz]?|objectif|cible|horizon|d['’]ici|à\s+terme|projection|pr[ée]visionnel|sc[ée]nario"
    r"|target|aim|by\s+20\d{2}|forecast|projected)\b")


def _page_cited_fact_span34(text: str) -> int:
    """Longueur du préfixe factuel protégé (0 si la ligne n'est pas une ligne de fait sourcé).

    Protège « Résultat net IAV : 4,2 M€ (2022) » dans « … — plaquette 2022, p.13 » ;
    ne protège rien si le préfixe porte lui-même une marque de projection.
    """
    m = _PAGE_CITED34.search(str(text or ""))
    if not m:
        return 0
    head = text[:m.start()]
    if not head.strip() or _PROJECTION_MARK34.search(head):
        return 0
    return m.start()


def _is_quoted_name34(span: str) -> bool:
    inner = span[1:-1].strip()
    if not inner or len(inner.split()) > 8:
        return False
    return not _NOT_A_NAME34.search(inner)


_HORIZON_RANGE36 = re.compile(
    r"(?<![\d.,])\d{1,2}\s*[–—-]\s*\d{1,2}\s*"
    r"(?:mois|months?|MOIS|MONTHS?|trimestres?|quarters?|semaines?|weeks?)\b",
    re.I)


def rewrite_quantities(text: str, lang: str = "fr") -> str:
    """Neutralise durées, horizons, montants, pourcentages, approximations, fractions puis comptes."""
    out = str(text or "")
    # v62.13.9.4.34 (lot 2) — UN NOM PROPRE ENTRE GUILLEMETS TRAVERSE LA
    # RÉÉCRITURE INTACT. Contre-audit de publication du 14/09/2026 : l'offre
    # « DAF de crise 90 jours » devenait « DAF de crise un calendrier à
    # arbitrer » (dossier de conseil), un nom d'offre mutilé au milieu d'une phrase.
    # Le chiffre est dans le NOM, pas dans l'assertion : on le protège par
    # sentinelle, comme le fait de registre ci-dessous.
    _quoted34: list = []

    def _keep_quoted34(m):
        if not _is_quoted_name34(m.group(0)):
            return m.group(0)          # assertion chiffrée entre guillemets : réécrite comme le reste
        _quoted34.append(m.group(0))
        return f"\u241F{len(_quoted34) - 1}\u241F"
    out = _QUOTED_SPAN34.sub(_keep_quoted34, out)
    # v62.13.9.4.36 — UNE PLAGE D'HORIZON N'EST PAS UNE GRANDEUR. Runs réels du
    # 17/09/2026 : « a milestone in the 12–24 month window » devenait « in the a
    # schedule to arbitrate window », et le titre « ## 12–24 MONTH HORIZON » était
    # coupé en son milieu (« 12–un calendrier à arbitrer HORIZON »). Une plage de
    # mois ou de trimestres qui décrit un HORIZON DE PLANIFICATION se lit comme une
    # plage d'années : elle traverse la réécriture intacte, protégée par sentinelle.
    _horizons36 = []

    def _keep_horizon36(m):
        _horizons36.append(m.group(0))
        return f"\x00H{len(_horizons36) - 1}\x00"

    out = _HORIZON_RANGE36.sub(_keep_horizon36, out)
    # v62.13.9.4.34 (lot 3) — le SEGMENT factuel d'une ligne sourcée à la page est
    # protégé par sentinelle ; le reste de la ligne suit le régime normal.
    _fact_head34 = ""
    _n34 = _page_cited_fact_span34(out)
    if _n34:
        _fact_head34, out = out[:_n34], out[_n34:]
    # v62.13.9.4.25 — le fait de registre « 0 salarié(s) » traverse la
    # réécriture intact (sentinelle sans chiffre, restaurée en sortie).
    _zeros = REGISTRY_ZERO_RE.findall(out)
    if _zeros:
        out = REGISTRY_ZERO_RE.sub(_REGISTRY_ZERO_SENTINEL, out)
    lang = line_language(out, lang)
    fr = not lang.startswith("en")
    act = action_signal(out)
    calendrier = "selon un calendrier à arbitrer" if fr else "on a schedule to arbitrate"
    un_calendrier = "un calendrier à arbitrer" if fr else "a schedule to arbitrate"
    enveloppe = "une enveloppe à dimensionner" if fr else "a budget to size"
    # v62.13.9.4.8 — « 3 300 €/an » se réécrit en enveloppe ANNUELLE, sans
    # laisser un « /an » orphelin après la neutralisation du montant.
    out = re.sub(r"[+\-−]?\d[\d\s\u00A0\u202F.,]*(?:\s*(?:€|k€|M€)?\s*(?:[–\-—]|à)\s*\d[\d\s\u00A0\u202F.,]*)?\s*(?:€|k€|M€)\s*/\s*an\b",
                 "une enveloppe annuelle à dimensionner" if fr else "an annual budget to size",
                 out)
    niveau = "un niveau à dimensionner" if fr else "a level to size"
    partie = "une partie" if fr else "a share"
    # v62.13.9.4.5 — l'année d'horizon se neutralise sur le texte BRUT (le masque
    # de dates la rendrait invisible) : « d'ici 2027 » / « by 2027 » / « en 2028 ».
    # v62.13.9.4.31 — « avant 2026-10-31 » est une DATE d'échéance, pas une année
    # d'horizon : la réécriture d'horizon ne s'applique pas à une date complète
    # (sinon « avant 2026-10-31 » devenait « … à arbitrer-10-31 »).
    out = re.sub(r"\b(?:d['’]ici|avant|by)\s+(?:la\s+fin\s+(?:de\s+)?)?(?:FY\s*)?(?:19|20)\d{2}\b(?![-/.]\d)", calendrier, out, flags=re.I)
    out = re.sub(r"\b(?:en|in)\s+(?:19|20)\d{2}\b(?=\s*[.,;:]|\s*$|\s+[a-zà-ÿ])", calendrier, out, flags=re.I) if action_signal(out) else out
    masked = mask_exempt(out, action=act)

    def _sub_on_masked(pattern: re.Pattern[str], repl) -> None:
        nonlocal out, masked
        pieces, last = [], 0
        for m in pattern.finditer(masked):
            pieces.append(out[last:m.start()])
            pieces.append(repl(m) if callable(repl) else repl)
            last = m.end()
        pieces.append(out[last:])
        out = "".join(pieces)
        masked = mask_exempt(out, action=act)

    _sub_on_masked(re.compile(r"\bplan\s+d['’]action\s+à\s+\d+(?:[.,]\d+)?\s*jours?\b", re.I), "plan d’action à court terme" if fr else "short-term action plan")
    _sub_on_masked(FRACTION_RE, partie)
    _sub_on_masked(re.compile(r"\b(?:une?\s+)?(?:" + APPROX_QUANTITY_RE.pattern[2:-2] + r")\s+(?:de\s+|d['’]|of\s+)", re.I), ("des " if fr else "some "))
    # v62.13.9.4.15.1 — « 180 jours facturables/an » : la durée emporte son
    # qualificatif et son « /an », sinon la réécriture laisse « un calendrier à
    # arbitrer facturables/an » (run réel du 02/09/2026 19:53).
    _sub_on_masked(re.compile(
        r"(?<![\w/])\d+(?:[.,]\d+)?(?:\s*(?:[-–]|à|to)\s*\d+(?:[.,]\d+)?)?\s*"
        r"(?:jours?|days?)\s+(?:factur(?:able|é)s?|ouvr[ée]s?|travaill[ée]s?|billable|worked)"
        r"(?:\s*/\s*an|\s+par\s+an|\s*/\s*year|\s+per\s+year|\s+a\s+year)?", re.I),
        "un volume annuel de jours facturables à arbitrer" if fr else "an annual volume of billable days to arbitrate")
    # v62.13.9.4.22 — durée-cadre d'un plan (« plan d'action à 90 jours », « horizon
    # 30 jours ») : reformulée en cadre, jamais laissée en chiffre nu.
    _sub_on_masked(re.compile(
        r"\b(plans?\s+d['’]actions?|horizon|feuille\s+de\s+route|roadmap|programme)\s+(?:à|de|sur|over|at)?\s*\d{1,3}\s*(?:jours?|mois|semaines?|ans?|days?|months?|weeks?|years?)\b", re.I),
        (lambda m: m.group(1) + (" à horizon cadré" if fr else " with a framed horizon")))
    # v62.13.9.4.25 — contre-audit v24 (§2) : « prévisionnel de trésorerie
    # glissant 12 mois » déclaré CIBLE par l'agent → l'horizon se réécrit en
    # cadre, la décision reste (« glissant à horizon cadré »), au lieu de
    # perdre la proposition entière.
    _sub_on_masked(re.compile(
        r"\b(pr[ée]visionnel|forecast|budget|reporting|plan\s+de\s+tr[ée]sorerie|cash\s+plan)((?:\s+(?:de\s+tr[ée]sorerie|de\s+cash|glissante?|rolling))*)"
        r"\s+(?:sur|à|over|de)?\s*\d{1,3}\s*(?:mois|months?|semaines?|weeks?)\b", re.I),
        (lambda m: m.group(1) + m.group(2) + (" à horizon cadré" if fr else " with a framed horizon")))
    # v62.13.9.4.19.2 — fourchette verbale (« entre 1 200 et 1 500 € »,
    # « de 800 € à 1 050 € HT/jour », « between 800 and 1,050 € ») réécrite
    # d'un bloc : le deck du run réel 20:23 portait « Repositionnement TJM
    # entre et — estim. à vérifier ».
    _NUMU = r"\d{1,3}(?:[ \u00a0\u202f.]\d{3})*(?:[.,]\d+)?\s*(?:€|k€|M€|Md€|\$|£|%)?"
    _sub_on_masked(re.compile(
        r"\b(?:entre|between)\s+" + _NUMU + r"\s+(?:et|and)\s+" + _NUMU +
        r"(?:\s*(?:HT|TTC|net|brut))?(?:\s*/\s*(?:jour|j|an|mois|h|heure|semaine|day|year|month|hour|week)\b)?", re.I),
        "dans une fourchette à dimensionner" if fr else "within a range to be sized")
    _sub_on_masked(re.compile(
        r"\b(?:de|from)\s+" + _NUMU + r"\s+(?:à|to)\s+" + _NUMU +
        r"(?:\s*(?:HT|TTC|net|brut))?(?:\s*/\s*(?:jour|j|an|mois|h|heure|semaine|day|year|month|hour|week)\b)?"
        r"(?=\s|$|[,;.)])", re.I),
        "d’une fourchette à dimensionner" if fr else "within a range to be sized")
    # v62.13.9.4.17 — cadence horaire (« 4-6h/sem », « 6 h/semaine »,
    # « 2h/jour ») : un volume de temps à arbitrer, période nommée, jamais
    # le fragment « -6h/sem » du deck réel du 03/09/2026.
    _sub_on_masked(re.compile(
        r"(?<![\w/])\d+(?:[.,]\d+)?(?:\s*[–\-—]\s*\d+(?:[.,]\d+)?)?\s*(?:h|heures?|hours?)\s*(?:/\s*|par\s+|per\s+)"
        r"(?P<per>sem|semaine|week|mois|month|jour|j|day)\b\.?", re.I),
        (lambda m: ("un volume horaire " + {"sem": "hebdomadaire", "semaine": "hebdomadaire", "week": "hebdomadaire",
                                              "mois": "mensuel", "month": "mensuel", "jour": "quotidien", "j": "quotidien",
                                              "day": "quotidien"}.get(m.group("per").lower(), "") + " à arbitrer").replace("  ", " ")
         if fr else
         ("a " + {"sem": "weekly", "semaine": "weekly", "week": "weekly", "mois": "monthly", "month": "monthly",
                  "jour": "daily", "j": "daily", "day": "daily"}.get(m.group("per").lower(), "") + " time budget to arbitrate")))
    # « 30 jours/an », « 2 semaines par an » : la durée annualisée ne laisse
    # pas son « /an » orphelin.
    _sub_on_masked(re.compile(
        r"(?<![\w/])\d+(?:[.,]\d+)?(?:\s*(?:[-–]|à|to)\s*\d+(?:[.,]\d+)?)?\s*"
        r"(?:jours?|days?|semaines?|weeks?|mois|months?)"
        r"(?:\s*/\s*an|\s+par\s+an|\s*/\s*year|\s+per\s+year|\s+a\s+year)", re.I),
        "un volume annuel à arbitrer" if fr else "an annual volume to arbitrate")
    # v62.13.9.4.29 — audit v27/v28 : « arbitrer le temps hebdomadaire dédié (0,5 vs 1
    # jour/semaine) » — un décimal de durée ou une alternative de cadence n'était
    # pas réécrit, la phrase (un arbitrage explicite) tombait entière. La cadence
    # se réécrit, l'arbitrage reste.
    _sub_on_masked(re.compile(
        r"(?<![\w/])\d+(?:[.,]\d+)?(?:\s*(?:vs\.?|ou|or|à|to|[-–])\s*\d+(?:[.,]\d+)?)*\s*(?:jours?|j|h|heures?|hours?|days?|mois|months?|semaines?|weeks?)"
        r"\s*(?:/|par|per)\s*(?:semaine|mois|an|jour|week|month|year|day)\b", re.I),
        "une cadence à arbitrer" if fr else "a cadence to arbitrate")
    _sub_on_masked(re.compile(
        r"(?<![\w/])\d+[.,]\d+(?:\s*(?:vs\.?|ou|or|à|to|[-–])\s*\d+(?:[.,]\d+)?)*\s*(?:jours?|j|h|heures?|hours?|days?|mois|months?|semaines?|weeks?)(?![\w/])", re.I),
        "une durée à cadrer" if fr else "a duration to frame")
    _sub_on_masked(DURATION_RE, un_calendrier)
    # v62.13.9.4.26 — run 13:10 sur la 9.4.25 : « (2-3 j, 2 000-2 500 € HT) » — le
    # « j » (jours) n'était pas une unité, la fourchette restait, la décision
    # entière était retirée. Durée abrégée = durée : « une durée à cadrer ».
    _sub_on_masked(re.compile(
        r"(?<![\w/])\d+(?:[.,]\d+)?(?:\s*(?:[-–]|à|to)\s*\d+(?:[.,]\d+)?)?\s*(?:j|h|hrs?|jrs?)(?![\w€%])", re.I),
        "une durée à cadrer" if fr else "a duration to frame")
    # v62.13.9.4.15.4 — une FOURCHETTE de montants (« 1 200–1 500 €/jour »,
    # « 3–5 k€ », « 24 000–72 000 €/an ») se réécrit d'un bloc, périodicité
    # comprise : le run réel du 03/09/2026 08:24 laissait « 1 200–1 une
    # enveloppe à dimensionner/jour », la réécriture était refusée et le
    # signal de vigilance Finance × Commercial disparaissait du corps.
    _sub_on_masked(re.compile(
        r"(?<![\w/])\d{1,3}(?:[ \u00a0\u202f.]\d{3})*(?:[.,]\d+)?\s*(?:€|k€|M€|\$|£)?\s*(?:[–\-—]|à|to)\s*"
        r"\d{1,3}(?:[ \u00a0\u202f.]\d{3})*(?:[.,]\d+)?\s*(?:€|k€|M€|Md€|\$|£)"
        r"(?:\s*/\s*(?:jour|j|an|mois|h|heure|semaine|day|year|month|hour|week)\b|\s+par\s+(?:jour|an|mois|heure|semaine))?", re.I),
        "une enveloppe à dimensionner" if fr else "a budget to size")
    # montant unique à périodicité (« 1 200 €/jour », « 500 €/mois ») : la
    # périodicité est reformulée, jamais laissée orpheline (« …/jour »).
    _sub_on_masked(re.compile(
        r"(?<![\w/])\d{1,3}(?:[ \u00a0\u202f.]\d{3})*(?:[.,]\d+)?\s*(?:€|k€|M€|\$|£)"
        r"\s*(?:/\s*|par\s+)(?P<per>jour|j|mois|h|heure|semaine|day|month|hour|week)\b", re.I),
        (lambda m: ("une enveloppe à dimensionner par " + _PERIOD_FR.get(m.group("per").lower(), m.group("per")))
         if fr else ("a budget to size per " + _PERIOD_EN.get(m.group("per").lower(), m.group("per")))))
    _sub_on_masked(MONEY_RE, enveloppe)
    # v62.13.9.4.31 — contre-audit v30 (§3) : « rester 100 % réseau/LinkedIn » exprime
    # une EXCLUSIVITÉ après un verbe d'état (tout ou rien), pas une cible chiffrée :
    # la question d'arbitrage entière disparaissait. Réécrit en « exclusivement » ;
    # « atteindre 100 % de couverture » ou « 100 % du CA » restent des grandeurs.
    _sub_on_masked(re.compile(
        r"(?<=\brester\s)100\s*%\s+(?!de\s|des\s|du\s|d['’])|"
        r"(?<=\brestons\s)100\s*%\s+(?!de\s|des\s|du\s|d['’])|"
        r"(?<=\bdemeurer\s)100\s*%\s+(?!de\s|des\s|du\s|d['’])|"
        r"(?<=\btravailler\s)100\s*%\s+(?!de\s|des\s|du\s|d['’])|"
        r"(?<=\bop[ée]rer\s)100\s*%\s+(?!de\s|des\s|du\s|d['’])|"
        r"(?<=\bremain\s)100\s*%\s+|(?<=\bstay\s)100\s*%\s+", re.I),
        ("exclusivement " if fr else "exclusively "))
    _sub_on_masked(re.compile(r"(?<![\w])[+−-]?\d+(?:[.,]\d+)?\s*(?:%|pts?|points?(?!\s+(?:de\s+vente|of\s+sale))|pp|bps|x|fois)(?![\w])", re.I), niveau)
    out, _ = rewrite_counts(out, lang)
    out = contract_articles(out)
    # v62.13.9.4.26 — « (≈50 cibles) » → « (≈des cibles) » : le signe
    # d'approximation ne survit pas à la neutralisation du nombre.
    out = re.sub(r"(?:[≈~]|\benv(?:iron)?\.?|\babout|\bapprox(?:\.|imately)?)\s*(?=(?:des|de|du|d['’]|une?|quelques|un\s+(?:nombre|volume|calendrier|niveau|montant)|some|a\s+few|an?\s+)\b)", "", out, flags=re.I)
    if _zeros:
        for z in _zeros:                                   # v62.13.9.4.25 — restauration, dans l'ordre
            out = out.replace(_REGISTRY_ZERO_SENTINEL, z, 1)
    if _fact_head34:                                    # v62.13.9.4.34 (lot 3) — fait sourcé restauré
        out = _fact_head34 + out
    if _quoted34:                                       # v62.13.9.4.34 — noms entre guillemets restaurés
        for _k34, _v34 in enumerate(_quoted34):
            out = out.replace(f"\u241F{_k34}\u241F", _v34)

    for _i36, _h36 in enumerate(_horizons36):
        out = out.replace(f"\x00H{_i36}\x00", _h36)
    return out


def strip_residual_cardinals(text: str) -> str:
    """Dernier recours (titres) : retire les cardinaux résiduels sans vider le texte."""
    out = str(text or "")
    pieces, last = [], 0
    for start, end, _tok in cardinal_spans(out, action=True):
        pieces.append(out[last:start]); last = end
    pieces.append(out[last:])
    cleaned = re.sub(r"\s{2,}", " ", "".join(pieces)).strip(" ,;:-–—")
    return contract_articles(cleaned) or out


NEUTRAL_STATUS_FR = "Cible chiffrée non étayée — baseline et provenance requises."
NEUTRAL_STATUS_EN = "Unsupported quantified target — baseline and provenance required."

_LOCUTIONS36 = (
    "un niveau à dimensionner", "une enveloppe à dimensionner", "un calendrier à arbitrer",
    "un volume à valider", "une part à établir", "un montant à établir",
    "a level to size", "a budget to size", "a schedule to arbitrate",
    "volume to validate", "a share to establish", "an amount to establish",
)


def is_fully_dequantified_metric_line(before: str, after: str) -> bool:
    """v62.13.9.4.36 — la ligne de métrique n'a plus AUCUN chiffre : elle ne dit rien.

    Runs réels du 17/09/2026 : « Adjusted operating margin a level to size → a level
    to size (FY2025 vs FY2024) » et son équivalent français. Une comparaison dont les
    deux termes ET l'écart sont retirés n'apprend rien au lecteur et abîme la
    crédibilité du document : la doctrine des scénarios veut qu'elle parte ENTIÈRE au
    registre du dossier complet, pas qu'elle soit rendue vidée.

    Vrai seulement si : la ligne d'origine portait au moins deux valeurs, la ligne
    réécrite ne porte plus de valeur (les millésimes et repères de période ne comptent
    pas), et au moins deux locutions de remplacement l'occupent.
    """
    b, a = str(before or ""), str(after or "")
    if not b or not a:
        return False
    import re as _re
    _vals = _re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)?\s*(?:%|k€|M€|Md€|€|£m|£|\$|m|bn)?")
    _periods = _re.compile(r"(?:FY|T[1-4]|Q[1-4]|S[12])\s*\d{2,4}|\b(?:19|20)\d{2}\b|\d{1,2}\s*[–—-]\s*\d{1,2}\s*(?:mois|months?|trimestres?|quarters?)", _re.I)
    def _count(t):
        return len([m for m in _vals.finditer(_periods.sub(" ", t)) if m.group(0).strip()])
    if _count(b) < 2 or _count(a) > 0:
        return False
    return sum(a.count(loc) for loc in _LOCUTIONS36) >= 2
