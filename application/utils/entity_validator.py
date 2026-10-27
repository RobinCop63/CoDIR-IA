"""
CoDIR IA — utils/entity_validator.py — v16.5.67
==================================================================
Post-processor anti-hallucination d'entités nommées.

Problème ciblé
--------------
Un LLM peut halluciner le nom d'un actionnaire, d'une filiale, d'une
contrepartie, d'un partenaire. Sur le cas dossier de conseil, le pipeline
a inventé « CABRE ACTIONNARIAT » alors que le capital est détenu à
100 % par le dirigeant personne physique (aucun actionnaire personne
morale dans le dossier).

Approche
--------
1. Construire une WHITELIST à partir des sources maîtrisées :
   - brief utilisateur
   - texte extrait des pièces jointes
   - bloc de contexte Pappers (full + summary)
2. Extraire du livrable LLM les candidats « entité nommée » par regex
   (séquences de Mots Capitalisés de 2+ mots, ou ACRONYMES 3+ lettres).
3. Comparer :
   - si l'entité candidate apparaît (insensible à la casse) dans la
     whitelist OU dans le DICTIONNAIRE_INSTITUTIONNEL → OK
   - sinon → flagger.
4. Modes de flagging configurables :
   - "annotate"  : insère `[NON SOURCÉ]` après chaque occurrence
   - "strip"     : remplace par `[entité non vérifiée]`
   - "log_only"  : ne modifie pas le texte, renvoie juste la liste

Design choices
--------------
- Pas de dépendance NER externe (spaCy, flair) — regex + stoplists.
- Case-insensitive pour la comparaison, préservation de la casse
  dans le texte sorti.
- Conservateur : si le mot est ambigu (ex. "Direction"), on le laisse
  passer. On flag uniquement ce qui est manifestement un nom propre.
- Idempotent : appeler plusieurs fois la même fonction donne le même
  résultat (on ne flag pas les entités déjà flaggées).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable


# ── Dictionnaires institutionnels / génériques (ne PAS flagger) ─────────────
# Termes qui ressemblent à des entités nommées mais sont génériques et
# attendus dans un rapport de CoDIR. Toute entrée ajoutée ici ne sera
# jamais flaggée comme hallucinée.
_INSTITUTIONAL_FR: set[str] = {
    # Administration / organismes
    "sie", "service des impôts", "service des impots",
    "urssaf", "dgfip", "direction générale des finances publiques",
    "insee", "cnil", "inpi", "rncs", "bodacc",
    "afnor", "adme", "ademe",
    "bpi", "bpifrance", "bpi france",
    "france travail", "pôle emploi", "pole emploi",
    "banque de france", "banque postale",
    "commissaire aux comptes", "cac",
    # Juridiques / fiscaux
    "conseil d'état", "conseil d'etat",
    "cour de cassation", "tribunal de commerce",
    "code de commerce", "code général des impôts", "code general des impots",
    "cgi", "rgpd", "gdpr",
    # Fonctions / rôles
    "daf", "cfo", "dg", "ceo", "coo", "cto", "cmo", "cto",
    "ressources humaines", "rh", "drh",
    "codir", "comex", "board",
    "président", "president", "directeur général", "directeur general",
    "gérant", "gerant", "associé", "associe",
    # Normes / référentiels
    "ifrs", "us gaap", "french gaap", "pcg", "plan comptable général",
    "anc", "autorité des normes comptables",
    # Formats / acronymes courants
    "sas", "sasu", "sarl", "sa", "eurl", "sci", "scp", "selarl",
    "tpe", "pme", "eti", "gafa", "cac 40", "sbf 120",
    "tva", "tva ca12", "is", "bic", "bnc", "urssaf",
    "ebitda", "ebit", "ebe", "bfr", "dso", "dpo",
    # Unités / zones géographiques
    "france", "europe", "union européenne", "union europeenne", "ue",
    "bretagne", "île-de-france", "ile-de-france", "paris", "lyon", "marseille",
    "g7", "g20", "oecd", "ocde",
    # Outils / canaux (rapports marketing sans sourcing requis)
    "linkedin", "email", "emailing", "crm", "kpi", "roi",
    # Jalons & temps
    "t1", "t2", "t3", "t4", "q1", "q2", "q3", "q4",
    "j+0", "j+1", "j+3", "j+7", "j+15", "j+30", "j+60", "j+90",
    "m+0", "m+1", "m+3", "m+6", "m+12",
    # Balises CoDIR IA internes
    "fait", "ref sect", "estim. ia", "estim ia", "à définir", "a definir",
    "décision validée", "decision validee", "à soumettre au dg", "a soumettre au dg",
    # ── v16.5.67.4 — Acronymes réglementaires / sécurité / métier modernes ──
    # Ajoutés suite aux runs du 19/04 où ces sigles standards étaient
    # systématiquement flaggés comme hallucinations alors qu'ils sont
    # connus et utilisés dans tout rapport de CoDIR français contemporain.
    # Réglementation & conformité
    "csrd", "corporate sustainability reporting directive",
    "dora", "digital operational resilience act",
    "nis2", "nis 2", "network and information security 2",
    "sapin ii", "sapin 2", "loi sapin",
    "rsi", "dac7", "dac6", "beps", "pillar 2", "pilier 2",
    "reach", "rohs",
    # Sécurité / cybersécurité
    "rssi", "ciso", "anssi", "mica", "cert", "soc", "siem",
    "pentest", "pca", "pra", "2fa", "mfa",
    # Fonctions modernes / RH
    "cdo", "chief digital officer", "cso", "cro", "cpo",
    "qvct", "qvt", "qwl",
    # Fédérations / institutions métier
    "fntm", "fédération nationale du management de transition",
    "federation nationale du management de transition",
    "feaco", "fédération européenne des consultants",
    "syntec", "syntec conseil", "syntec numérique", "syntec numerique",
    "afpa", "opco", "opco atlas", "opco 2i", "opco ep",
    "medef", "cpme", "u2p",
    # Opérations / supply (gardés ici même si souvent flaggés)
    "rc pro", "rcp", "rc professionnelle", "responsabilité civile professionnelle",
    # Financement / investissement
    "pge", "prêt garanti par l'état", "pret garanti par l'etat",
    "fcpr", "fpci", "fcpi", "sofica",
    "lbo", "obo", "mbi", "mbo", "m&a", "m & a", "ipo",
    "bpifrance", "bpi", "crédit d'impôt recherche", "cir", "cii",
    # Fiscalité
    "cfe", "cvae", "tascom", "taxe d'apprentissage",
    # Modèles économiques / tech
    "saas", "paas", "iaas", "baas", "fintech", "insurtech", "legaltech",
    "esn", "ssii", "editeur de logiciel",
    "arr", "mrr", "ltv", "cac", "churn", "nps", "csat",
    "tjm", "tjm moyen", "taux journalier moyen",
    # Normes ISO / qualité
    "iso 9001", "iso 27001", "iso 14001", "iso 45001",
    "rse", "rso", "esg", "ppp",
    "b corp", "bcorp",
    # PLF / budget État
    "plf", "plfss", "loi de finances", "projet de loi de finances",
    # ── v16.5.67.5 — Compléments suite au run v16.5.67.4 ──────────────
    # Supply Chain est une direction du pipeline CoDIR-IA elle-même :
    # les agents la mentionnent naturellement (parfois pour dire qu'elle
    # est inapplicable). Ne doit jamais être flaggée comme hallucination.
    "supply chain", "supply-chain", "chaîne logistique", "chaine logistique",
    # COVID : toujours cité dans les analyses post-2020, acronyme de fait.
    "covid", "covid-19", "covid 19", "sars-cov-2",
    # Directions CoDIR elles-mêmes (mentionnées par les autres agents)
    "direction stratégie", "direction strategie", "direction marketing",
    "direction finance", "direction commerciale",
    "direction synthèse", "direction synthese", "direction générale",
    "direction generale", "direction supply chain",
    # ── v16.5.67.9 — Compléments suite au run v16.5.67.7 ──────────────
    # Termes business anglophones devenus standards en français.
    "b2b", "b2c", "b2b2c", "c2c", "d2c",
    # Acronymes CoDIR-IA internes (produits par le pipeline lui-même,
    # mentionnés par les agents quand ils se référencent mutuellement).
    # CR5 = 5 compte-rendu (synthèse finale), structure template interne.
    "cr5", "cr-5", "cr 5", "cr1", "cr2", "cr3", "cr4",
    # Loi réelle française 2023 (observée dans run v67.5, absente whitelist)
    "loi industrie verte", "loi relative à l'industrie verte",
    # Fonctions RH modernes (observées en flag v67.7)
    "chro", "chief human resources officer",
    # FNE-Formation = dispositif public réel France Travail
    "fne-formation", "fne formation", "fne",
}

_INSTITUTIONAL_EN: set[str] = {
    "irs", "sec", "fca", "ecb", "fed", "federal reserve",
    "gaap", "ifrs", "us gaap",
    "cfo", "ceo", "coo", "cto", "cmo", "cco", "hr",
    "board", "executive committee",
    "q1", "q2", "q3", "q4", "h1", "h2",
    "ebitda", "ebit", "kpi", "roi", "dso", "dpo",
    "linkedin", "email", "emailing", "crm",
    "france", "europe", "european union", "eu", "uk", "us", "usa",
    "paris", "london", "new york", "berlin",
    "oecd", "g7", "g20",
    "fact", "estim. ai", "estim ai", "tbd", "to be defined",
    # v62.10 — English report headings / operating concepts are not named
    # entities.  Filtering them here preserves the signal for actual legal
    # entities, brands and people.
    "strategic analysis", "executive summary", "current situation",
    "situation summary", "two-year plan", "strategic plan",
    "three-year decline", "critical assessment", "critical analysis",
    "critical implication", "priority", "recommendation", "conclusion",
    "to investigate", "to decide", "working assumption", "major risks",
    "margin recovery", "profitability collapse", "operational diagnosis",
    "commercial diagnosis", "commercial recommendations", "action plan",
    "board brief", "methodological corrections", "corrected interpretation",
    "brand equity destruction", "strategic plan execution failure",
    "otif", "sku", "skus", "cogs", "sg&a", "sga",
}

INSTITUTIONAL_ALL: set[str] = _INSTITUTIONAL_FR | _INSTITUTIONAL_EN


# ── Regex d'extraction des candidats entité ─────────────────────────────────
# Pattern 1 : séquence de 2 à 5 mots Capitalisés ou tout-MAJUSCULE,
#             séparés par espace, trait d'union ou apostrophe.
#             Ex : "CABRE ACTIONNARIAT", "Total Energies", "La Française de l'Énergie"
# Pattern 2 : ACRONYMES de 3+ lettres majuscules.
#             Ex : "URSSAF", "SACEM" (sera filtré par whitelist si sourcé).
#
# On capture le segment complet pour pouvoir le remplacer proprement.
_CAPITALIZED_WORD = r"(?:[A-ZÀ-ÖØ-Ý][A-ZÀ-ÖØ-Ýa-zà-öø-ý'’\-]{1,}|[A-ZÀ-ÖØ-Ý]{2,})"
# Connecteurs internes à une entité UNIQUE (pas "et" / "&" / "ou" qui joignent
# deux entités distinctes — on split dessus).
# v16.5.67.5 — bug tokenisation corrigé :
#   Avant : `\s+` dans le connecteur → matchait `\n` → attrapait le premier mot
#   capitalisé de la ligne suivante, produisant des fragments comme
#   "DIAGNOSTIC COMMERCIAL\nLe" ou "NO-GO COMMERCIAUX\nIl".
#   Après : `[ \t]+` (espaces horizontaux uniquement) pour rester sur la même ligne.
_CONNECTOR_INTRA = r"(?:[ \t]+(?:de|du|des|la|le|les|l’|l'|d’|d'|von|van)[ \t]+|[ \t]+|-)"

# Match : 2+ mots capitalisés reliés, total 2-6 tokens (sans "et"/"&"/"ou")
_ENTITY_MULTIWORD_RE = re.compile(
    rf"\b{_CAPITALIZED_WORD}(?:{_CONNECTOR_INTRA}{_CAPITALIZED_WORD}){{1,5}}\b"
)
# Match : acronyme 3+ majuscules (peut contenir chiffres et tirets)
_ACRONYM_RE = re.compile(r"\b[A-ZÀ-ÖØ-Ý][A-ZÀ-ÖØ-Ý0-9\-]{2,}\b")

# ── v16.5.67.5 — Mots-outils UPPERCASE (connecteurs inter-entités) ──────────
# Ces mots en MAJUSCULES (OU, ET, AU, AUX, DE, DU, DES, LA, LE, LES, SOUS,
# SUR, NON, PAR) apparaissent à l'intérieur de titres de section et sont
# capturés par le regex multiword comme si c'étaient des mots d'entité.
# Observés dans run v16.5.67.4 : "ARBITRAGES OU GO", "INVESTIGUER SOUS".
# Stratégie : quand un match multiword contient un de ces mots SEPAREMENT,
# on le split en entités plus petites OU on rejette le match s'il est
# structurellement invalide (voir _is_malformed_multiword_with_connector).
_UPPERCASE_CONNECTOR_WORDS: set[str] = {
    "OU", "ET", "AU", "AUX", "À", "A",
    "DE", "DU", "DES", "LA", "LE", "LES", "L'", "L’", "D'", "D’",
    "SOUS", "SUR", "NON", "PAR", "POUR", "AVEC", "SANS", "DANS",
    "CE", "CES", "CETTE", "CET",
    "UN", "UNE", "DU",
    "OU/ET", "ET/OU",
}

# ── Stoplist de verbes d'action / mots-outils capitalisés ───────────────────
# Ces mots en tête de phrase ou en début de ligne après numérotation sont
# fréquemment capturés par le regex alors qu'ils ne sont PAS des entités.
# Si le premier token d'une capture multiword est dans cette liste, on le
# retire et on ré-évalue sur le reste. Si la capture devient vide ou mono-mot
# sans majuscule forte, on la rejette.
_ACTION_VERBS_FR: set[str] = {
    "contacter", "mobiliser", "obtenir", "négocier", "negocier",
    "appeler", "relancer", "lancer", "valider", "confirmer",
    "ouvrir", "fermer", "geler", "sécuriser", "securiser",
    "clarifier", "auditer", "produire", "proposer", "préparer", "preparer",
    "mettre", "engager", "suivre", "piloter", "faire", "éviter", "eviter",
    "rencontrer", "analyser", "présenter", "presenter",
    "demander", "adresser", "renégocier", "renegocier",
    "réduire", "reduire", "arrêter", "arreter",
    "note", "brief", "plan", "action", "objectif", "mesure",
    "directeur", "directrice", "direction",
    "monsieur", "madame",
    # Connecteurs de phrase fréquents
    "tout", "tous", "toute", "toutes", "aucun", "aucune",
    "premier", "première", "premiere", "deuxième", "deuxieme",
    "troisième", "troisieme", "quatrième", "quatrieme",
    "ensuite", "enfin", "par", "pour", "dans", "sans", "avec",
    "ce", "cette", "ces", "leur", "leurs", "notre", "nos", "votre", "vos",
    "avoir", "être", "etre", "faire", "dire",
    # Déclencheurs de phrase
    "si", "quand", "lorsque", "tandis", "bien", "cependant", "toutefois",
}

_ACTION_VERBS_EN: set[str] = {
    "contact", "mobilize", "obtain", "negotiate",
    "call", "follow", "launch", "validate", "confirm",
    "open", "close", "freeze", "secure",
    "clarify", "audit", "produce", "propose", "prepare",
    "engage", "track", "pilot", "do", "avoid",
    "meet", "analyze", "present",
    "request", "address", "renegotiate",
    "reduce", "stop",
    "note", "brief", "plan", "action", "objective", "measure",
    "director", "direction", "mister", "mrs", "mr",
    "all", "any", "first", "second", "third", "fourth",
    "then", "finally", "by", "for", "in", "without", "with",
    "if", "when", "while", "however", "moreover",
}

_ACTION_VERBS: set[str] = _ACTION_VERBS_FR | _ACTION_VERBS_EN

# v16.5.74 — Déterminants français usuels qui précèdent souvent un terme
# financier en majuscule dans les outputs agents.
# Ex: "Le CAPEX", "La marge EBITDA", "Les drivers", "Notre EBITDA".
# Ces déterminants doivent être strippés pour permettre la détection du
# terme effectif dans le set _COMMON_UPPERCASE_WORDS ou dans la whitelist.
# Identifié comme cause de faux positifs sur les 4 tests réalisés sous v16.5.73 (fix v16.5.74).
_LEADING_DETERMINERS: set[str] = {
    # Articles définis et indéfinis FR
    "le", "la", "les", "l", "l'", "un", "une", "des", "du",
    # Articles possessifs FR
    "mon", "ma", "mes", "ton", "ta", "tes", "son", "sa", "ses",
    "notre", "nos", "votre", "vos", "leur", "leurs",
    # Articles définis EN (pour textes EN)
    "the", "a", "an", "this", "that", "these", "those",
    "my", "our", "your", "their", "his", "her", "its",
}


def _strip_leading_action_word(candidate: str) -> str:
    """Strip un verbe d'action ou un déterminant en début de candidat.

    v16.5.74 — étendu aux déterminants français usuels (Le, La, Les, Notre,
    etc.) pour réduire les faux positifs du type "Le CAPEX [NON SOURCÉ]"
    alors que CAPEX figure dans la whitelist ou les mots usuels.

    Si le candidat commence par un verbe d'action OU un déterminant, on
    retourne le reste. Sinon on retourne le candidat tel quel.
    """
    tokens = candidate.split()
    if not tokens:
        return ""
    first = tokens[0].lower().strip(".,;:!?'’")
    if (first in _ACTION_VERBS or first in _LEADING_DETERMINERS) and len(tokens) >= 2:
        return " ".join(tokens[1:])
    return candidate
    """
    Retire le premier token s'il est dans la stoplist d'action/outil.
    Utile pour "Contacter BPI France" → "BPI France".
    Retourne "" si la capture devient vide ou mono-mot ambigu.
    """
    tokens = re.split(r"\s+", candidate.strip())
    if not tokens:
        return ""
    first = tokens[0].lower().strip(".,;:!?")
    if first in _ACTION_VERBS and len(tokens) >= 2:
        return " ".join(tokens[1:])
    return candidate


@dataclass
class EntityValidationResult:
    """Résultat d'une validation d'un texte LLM."""
    validated_text: str                  # texte potentiellement annoté
    flagged_entities: list[str] = field(default_factory=list)
    whitelist_size: int = 0
    candidates_count: int = 0
    flagged_count: int = 0

    def summary_line(self) -> str:
        return (
            f"entities | candidates={self.candidates_count} "
            f"flagged={self.flagged_count} whitelist={self.whitelist_size}"
        )


# ── Construction de la whitelist ────────────────────────────────────────────
def build_whitelist(*sources: str | None) -> set[str]:
    """
    Construit la whitelist en extrayant toutes les entités candidates
    des sources fournies. On est GÉNÉREUX : toute entité qui apparaît
    dans une source est considérée comme sourcée, même si elle est
    elle-même imparfaite (un SIREN mal orthographié dans le brief
    restera cohérent avec le brief — ce n'est pas le job du validator
    de corriger le brief).

    Les sources sont tolérantes à None.
    """
    wl: set[str] = set()
    for src in sources:
        if not src:
            continue
        for m in _ENTITY_MULTIWORD_RE.finditer(src):
            wl.add(_norm(m.group(0)))
        for m in _ACRONYM_RE.finditer(src):
            wl.add(_norm(m.group(0)))
        # On ajoute également les mots en minuscules qui sont clairement
        # des noms (mot de 4+ lettres qui apparaît plusieurs fois) —
        # utile quand un nom propre est cité en bas de casse dans le brief.
        # On ne le fait pas ici pour rester simple ; à ajouter si besoin.
    return wl


def _norm(s: str) -> str:
    """Normalisation pour comparaison (case + espaces)."""
    return re.sub(r"\s+", " ", s.strip().lower())


# ── Détection "est-ce institutionnel ?" ──────────────────────────────────────
def _is_institutional(candidate: str) -> bool:
    norm = _norm(candidate)
    if norm in INSTITUTIONAL_ALL:
        return True
    # Les acronymes très courts (≤ 3 lettres) courants sont tolérés —
    # on ne va pas flagger "DG" ou "RH" parce qu'ils ne sont pas sourcés.
    if len(norm) <= 3 and norm.isalpha():
        return True
    return False


def _is_numeric_or_amount(candidate: str) -> bool:
    """Ex : '100 000', '12 345 €' — à ignorer."""
    return bool(re.fullmatch(r"[\d\s.,€$£%+\-]+", candidate))


# v16.5.67 — F2 Exclusions patterns pour réduire les faux positifs
# Retour du run 18/04 v16.5.66 : ~70% des entities flaggées étaient en réalité
# des titres de section, des patterns temporels, ou des étiquettes méta.
# Exemple typique : "NON SOURCÉ", "INVENTION", "REJETÉ DÉFINITIVEMENT", "SEMAINE 3"
# étaient flagués comme hallucinations d'entités alors qu'ils sont le VOCABULAIRE
# du système lui-même.

_SECTION_TITLE_WORDS = {
    # 9.4.62 — recette 9.4.61 : « Parades » (en-tête de sous-liste des risques) relevé comme entité non vérifiée
    "parade", "parades", "contre-mesure", "contre-mesures", "mitigation", "mitigations",
    # Titres fréquents de sections de rapport CoDIR
    "SYNTHÈSE", "SYNTHÈSE EXÉCUTIVE", "STRATÉGIE", "RISQUES", "MITIGATIONS",
    "HYPOTHÈSES", "PROJECTION", "BUDGET", "BUDGET PRÉVISIONNEL",
    "RECOMMANDATION", "RECOMMANDATIONS", "DÉCISION ATTENDUE", "DÉCISIONS",
    "DÉCISIONS PRIORITAIRES", "ARBITRAGES", "ARBITRAGES OUVERTS",
    "ARBITRAGES CODIR", "PLAN D'ACTION", "PLAN D'ACTIONS",
    "INDICATEURS", "INDICATEURS DE SUCCÈS", "CONSTATS", "CONSTATS CLÉS",
    "OPPORTUNITÉS", "OPPORTUNITÉS COMMERCIALES", "OPPORTUNITÉS IDENTIFIÉES",
    "OPPORTUNITÉS COMMERCIALES PRIORITAIRES",
    "CHALLENGES", "CHALLENGE MKT", "CHALLENGE FIN", "CHALLENGE MARKETING",
    "CHALLENGE FINANCE", "CHALLENGES MARKETING", "CHALLENGES FINANCE",
    "RISQUES MAJEURS", "RISQUES IDENTIFIÉS", "RISQUES CRITIQUES",
    "PRÉCONISATIONS", "PRÉCONISATIONS COMMERCIALES",
    "DIAGNOSTIC", "DIAGNOSTIC COMMERCIAL",
    "ÉTAT DU MARCHÉ", "MANAGEMENT DE TRANSITION",
    # États qualifiés
    "SOUS TENSION", "TRÈS FAIBLE", "CRITIQUE", "ALERTE CRITIQUE",
    "RISQUE MAJEUR", "ÉQUATION ÉCONOMIQUE IMPOSSIBLE",
    # Phases / positions
    "PHASE PILOTE", "ZONE", "NARRATIVE",
    "NEXT STEPS", "IMPACT COMMERCIAL", "IMPACT SUPPLY CHAIN",
    # Labels de livrable
    "TOTAL", "N-1", "VERSION FINALE", "VERSION FINALE POST-CHALLENGE",
    "COÛT COMPLET", "COÛT COMPLET MISSION", "COÛT TOTAL", "COÛT TOTAL CHARGÉ",
    "PRICING MINIMUM VIABLE", "PRICING", "BUDGET FINAL",
}
_SECTION_TITLE_NORM = {_norm(s) for s in _SECTION_TITLE_WORDS}

_META_LABELS = {
    # Étiquettes auto-produites par le pipeline ou les agents eux-mêmes
    # (leur mention ne constitue pas une hallucination d'entité)
    "NON SOURCÉ", "NON SOURCE", "NON SOURCÉ]", "[NON SOURCÉ]",
    "FAIT", "FAITS", "REF SECT.", "REF SECT", "REF_SECT", "ESTIM", "ESTIM. IA", "ESTIM IA",
    # v16.5.75 — Item #9 : sous-typologie ESTIM
    "ESTIM-FILINGS", "ESTIM FILINGS", "[ESTIM-FILINGS]", "[ESTIM FILINGS]",
    "ESTIM-COMPARABLE", "ESTIM COMPARABLE", "[ESTIM-COMPARABLE]", "[ESTIM COMPARABLE]",
    "ESTIM-HYPOTHÈSE", "ESTIM HYPOTHÈSE", "[ESTIM-HYPOTHÈSE]", "[ESTIM HYPOTHÈSE]",
    "ESTIM-HYPOTHESE", "[ESTIM-HYPOTHESE]",  # Variante sans accent
    "CALCUL", "HYPOTHÈSE", "INCERTAIN",
    "INVENTION", "INVENTÉ",
    "REJETÉ", "REJETÉ DÉFINITIVEMENT", "CORRIGÉES", "CORRIGÉES MAIS FRAGILES",
    "CONFIRMÉE", "CUMULER", "MODÈLE",
    "CORRECTIFS OBLIGATOIRES", "INTERDICTION FORMELLE",
    "AVERTISSEMENT", "AVERTISSEMENT PRÉALABLE", "AVERTISSEMENT PRÉALABLE RENFORCÉ",
    "AVERTISSEMENT MÉTHODOLOGIQUE", "AVERTISSEMENT MÉTHODOLOGIQUE RENFORCÉ",
    "NON VALIDÉES", "HYPOTHÈSES CRITIQUÉES", "HYPOTHÈSES STRUCTURANTES",
    "HYPOTHÈSES CRITIQUES",
    "BLOC JSON STRUCTURÉ",
    # Patterns du briefcheck / confidence_scorer / mode
    "MODE GÉNÉRIQUE", "MODE PARTIEL", "MODE CADRÉ", "MODE BR", "MODE BRIEF",
    "GENERIC", "PARTIAL", "FRAMED",
    # Wording Lucidité
    "RECOMMANDÉ", "À ARBITRER", "À INVESTIGUER", "A ARBITRER", "A INVESTIGUER",
    "PROPOSÉ", "À VÉRIFIER",
    # ── v16.5.67.4 — Meta-labels auto-produits vus dans les runs du 19/04 ──
    # Le pipeline produit ces marqueurs structurels dans les outputs agents.
    # Ils n'ont rien d'entités nommées, ce sont des étiquettes de mise en forme
    # ou des mots-clés de section.
    "PASS", "PASS 1", "PASS 2", "PASS #1", "PASS #2",
    "CORRECTIONS FINALES PASS", "CORRECTIONS MAJEURES PASS",
    "AJUSTEMENTS CRITIQUES PASS", "RÉÉVALUATION PASS",
    "ÉCART AVEC PASS", "OUBLIÉ PASS", "NON BUDGÉTÉ PASS",
    "ARBITRER", "INVESTIGUER", "VÉRIFIER", "QUANTIFIER",
    "QUOI", "QUAND", "IMPACT", "COMMENT", "POURQUOI",
    "ALERTE", "ALERTES", "LACUNE CRITIQUE",
    "NO-GO", "NO GO", "GO", "GO/NO-GO",
    "MATÉRIEL", "NON MATÉRIEL", "MIXTE", "MODÉRÉE", "MODÉRÉ",
    "DIMENSIONNEMENT MARCHÉ", "DIMENSIONNEMENT DU MARCHÉ",
    "DONNÉES NON VÉRIFIABLES", "DONNÉES PARTIELLEMENT SOURCÉES",
    "NON SOURCÉE", "RISQUES MAJEURS NON PROVISIONNÉS",
    "PROJECTION PRUDENTE CORRIGÉE", "MODÈLE ÉCONOMIQUE",
    "FOURCHETTES CORRIGÉES ET RISQUES", "FOURCHETTES CORRIGÉES",
    "OBLIGATOIRES", "RECOMMANDÉE", "PRÉCONISÉ", "PRECONISE",
    "ARBITRAGES CRITIQUES REQUIS", "ARBITRAGE DG",
    "SEGMENTATION CLIENT", "CARTOGRAPHIE CONCURRENTIELLE",
    "OPPORTUNITÉS PRIORITAIRES", "SCORING",
    "FORT POTENTIEL", "POTENTIEL MOYEN", "POTENTIEL FAIBLE",
    "ÉTUDE DE MARCHÉ", "ÉTUDES DE MARCHÉ",
    # ── v16.5.67.5 — Meta-labels 1-2 mots observés en run v16.5.67.4 ──
    # Ne sont pas capturés par _is_structural_section_title (qui exige 3+ mots)
    # ni par _is_common_uppercase_word (car multi-mots ou trop spécifiques).
    "CORRECTION", "CORRECTION CRITIQUE", "CORRECTIONS",
    "ATTENTION", "ALERTE MÉTHODOLOGIQUE", "ALERTE METHODOLOGIQUE",
    "LACUNE", "LACUNE MAJEURE", "LACUNE CRITIQUE", "DÉTAIL MANQUANT", "DETAIL MANQUANT",
    "RISQUE IDENTIFIÉ", "RISQUE IDENTIFIE",
    "FREINS STRUCTURELS", "FREIN STRUCTUREL",
    "CARTOGRAPHIE GÉOGRAPHIQUE", "CARTOGRAPHIE GEOGRAPHIQUE",
    "SCÉNARIOS CORRIGÉS", "SCENARIOS CORRIGES", "SCÉNARIO CORRIGÉ",
    "DÉCISION DG REQUISE", "DECISION DG REQUISE",
    "INVESTIGUER SOUS",
    "JOURS", "JOUR", "HEURES", "HEURE", "MOIS", "ANNÉE", "ANNEE",
    "ZONE", "ZONES",
    # Templates génériques avec "Année" non-résolu (complément au filtre regex)
    "CONSULTATION FNMT",  # c'est le nom "FNMT" dans un template générique
}
_META_LABELS_NORM = {_norm(s) for s in _META_LABELS}

# Patterns temporels : J1-14, J22-30, T0, T+30, T1, T2, T3, SEMAINE 3, S1-S2,
# M1, M2-M6, J1-J30, W1-W4, etc.
_TEMPORAL_PATTERN_RE = re.compile(
    r"""^(
        [JTMW]\d{1,3}(?:[-–]\d{1,3})?(?:\s*·\s*[\w'’\s]+)?   |  # J1-14, T0, M2, etc.
        [JTMW]\d{1,3}[-–][JTMW]?\d{1,3}                       |  # J1-J30, T0-T6
        T\s*[+\-]\s*\d{1,3}                                   |  # T+30, T-15
        [JTMW]\s*\d{1,3}                                      |  # J 1, W 4
        SEMAINE\s*\d{1,3}                                     |  # SEMAINE 3
        [ST]\d{1,2}(?:[-–][ST]\d{1,2})?                       |  # S1, S1-S2
        PHASE\s*\w+                                           |  # PHASE PILOTE
        ZONE                                                  |
        NARRATIVE
    )$""",
    re.VERBOSE | re.IGNORECASE,
)

# v16.5.74 — Plages temporelles "Mois-Mois Année" (ex: "Mai-Juin 2026",
# "Juillet-Septembre 2026", "Janvier-Avril 2027") observées comme
# faux positifs sur 4 tests (dossier de conseil, FDE, dossier réseau de soins, dossier anglophone coté).
# Ces plages apparaissent dans les calendriers marketing et sont taggées
# à tort comme entités non sourcées.
_FRENCH_MONTHS = (
    "JANVIER|FÉVRIER|FEVRIER|MARS|AVRIL|MAI|JUIN|JUILLET|AOÛT|AOUT|"
    "SEPTEMBRE|OCTOBRE|NOVEMBRE|DÉCEMBRE|DECEMBRE"
)
_ENGLISH_MONTHS = (
    "JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|"
    "SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER"
)
_DATE_RANGE_RE = re.compile(
    rf"""^(
        ({_FRENCH_MONTHS})[-–\s]({_FRENCH_MONTHS})\s+\d{{4}}    |  # Mai-Juin 2026
        ({_FRENCH_MONTHS})\s+\d{{4}}                              |  # Mai 2026
        ({_ENGLISH_MONTHS})[-–\s]({_ENGLISH_MONTHS})\s+\d{{4}}  |  # May-June 2026
        ({_ENGLISH_MONTHS})\s+\d{{4}}                            |  # May 2026
        T\d\s+\d{{4}}                                             |  # T1 2026
        Q\d\s+\d{{4}}                                             |  # Q1 2026
        H\d\s+\d{{4}}                                             |  # H1 2026
        S\d\s+\d{{4}}                                             |  # S1 2026
        FY\s*\d{{2,4}}(?:[/-]\d{{2,4}})?                          |  # FY24, FY24/25, FY 2025
        H\d\s*FY\s*\d{{2,4}}(?:[/-]\d{{2,4}})?                    |  # H1 FY26, H2 FY24/25
        \d{{1,2}}M\s*FY\s*\d{{2,4}}(?:[/-]\d{{2,4}})?                # 9M FY2026, 12M FY24/25
    )$""",
    re.VERBOSE | re.IGNORECASE,
)

# v16.5.74 — Codes ligne liasse fiscale française 2050-2059
# (Ligne HI, Ligne HJ, Ligne FL, Ligne BT, Ligne GW, Ligne HN, etc.)
# Tout DAF reconnaît ces codes — ce ne sont PAS des entités à valider.
# Pattern : "Ligne" + 1 à 3 lettres majuscules (codes officiels DGFiP).
_LIASSE_FR_LINE_RE = re.compile(
    r"^(LIGNE|LIGNES|LINE)\s+[A-Z]{1,3}\d?$",
    re.IGNORECASE,
)


# ── v16.5.67.5 — Filtres structurels (au-delà des dictionnaires) ────────────

# Régions administratives françaises (13 régions métropole + DOM-TOM).
# Apparaissent fréquemment dans les analyses sectorielles ("marché porteur
# en Auvergne-Rhône-Alpes") et ne sont PAS des entités à flagger.
_FRENCH_REGIONS: set[str] = {
    "auvergne-rhône-alpes", "auvergne-rhone-alpes",
    "bourgogne-franche-comté", "bourgogne-franche-comte",
    "bretagne",
    "centre-val de loire", "centre-val-de-loire",
    "corse",
    "grand est",
    "hauts-de-france",
    "île-de-france", "ile-de-france",
    "normandie",
    "nouvelle-aquitaine",
    "occitanie",
    "pays de la loire",
    "provence-alpes-côte d'azur", "provence-alpes-cote d'azur",
    "paca",
    # DOM-TOM
    "guadeloupe", "martinique", "guyane", "la réunion", "la reunion",
    "mayotte", "saint-pierre-et-miquelon",
    # Anciennes régions encore citées
    "alsace", "aquitaine", "auvergne", "basse-normandie", "champagne-ardenne",
    "franche-comté", "franche-comte", "haute-normandie", "languedoc-roussillon",
    "limousin", "lorraine", "midi-pyrénées", "midi-pyrenees",
    "nord-pas-de-calais", "picardie", "poitou-charentes", "rhône-alpes",
    # Métropoles françaises principales (par taille, utilisées en analyse
    # territoriale). Les plus courantes sont déjà dans INSTITUTIONAL_FR.
    "toulouse", "nice", "nantes", "montpellier", "strasbourg", "bordeaux",
    "lille", "rennes", "reims", "toulon", "saint-étienne", "saint-etienne",
    "le havre", "grenoble", "dijon", "angers", "nîmes", "nimes",
    "villeurbanne", "aix-en-provence", "brest", "limoges", "tours", "amiens",
    "metz", "perpignan", "besançon", "besancon",
}
_FRENCH_REGIONS_NORM: set[str] = {_norm(r) for r in _FRENCH_REGIONS}


def _is_french_region(candidate: str) -> bool:
    """Since v16.5.67.5 — Région française ou métropole. Apparaissent naturellement
    dans les analyses sectorielles territoriales, ne sont PAS des hallucinations."""
    return _norm(candidate) in _FRENCH_REGIONS_NORM


# Template générique "NOM Année" / "NOM Annee" — patterns où un LLM a
# produit un template avec {année} non résolu, type "Scénario Année",
# "Projection CA Année", "Pipeline Année", "Cible Année".
# Observés en run v16.5.67.4 : 5 flags de cette nature.
_GENERIC_TEMPLATE_RE = re.compile(
    r"""^
        [A-ZÀ-Ýa-zà-ý][\w'’\s\-]{0,40}       # un mot ou groupe capitalisé
        \s+
        (?:Année|Annee|An|Exercice|Mois|Trim|Semestre)   # suffixe template
        \s*
        (?:\d{1,4}|N\+?\d?|N-?\d?)?                        # optionnel : 2024, N, N+1
    $""",
    re.VERBOSE | re.IGNORECASE,
)


def _is_generic_template_label(candidate: str) -> bool:
    """Since v16.5.67.5 — "Scénario Année", "Projection CA Année", "Cible Année N+1"…
    Ce sont des étiquettes de tableau où le LLM a laissé un template non-résolu.
    À distinguer d'une vraie entité."""
    return bool(_GENERIC_TEMPLATE_RE.match(candidate.strip()))


# Match multiword contenant un mot-outil UPPERCASE comme connecteur
# ("ARBITRAGES OU GO", "INVESTIGUER SOUS", "Développer DSI"…). Ces matches
# sont structurellement invalides comme entités nommées : un mot-outil ne
# peut pas être à l'intérieur d'un nom propre.
def _is_malformed_with_uppercase_connector(candidate: str) -> bool:
    """Since v16.5.67.5 — Match multi-mot contenant OU/ET/SOUS/PAR/etc. en
    majuscules comme l'un de ses tokens. Ce n'est pas une entité nommée,
    c'est un fragment de phrase capté par accident."""
    tokens = re.split(r"[\s\-]+", candidate.strip())
    if len(tokens) < 2:
        return False
    # Si un des tokens (mais pas le premier) est un mot-outil en UPPERCASE
    # ET que tout le reste est aussi en UPPERCASE → fragment de phrase
    for tok in tokens[1:]:
        if tok.upper() == tok and tok in _UPPERCASE_CONNECTOR_WORDS:
            return True
    return False


# Patterns "titre de section long" : 3+ mots UPPERCASE consécutifs forment
# un titre de section, pas une entité nommée. Exemples observés v67.4 :
# "SEGMENTATION DU MARCHÉ", "ACTEURS ET STRUCTURE CONCURRENTIELLE",
# "PROFIL TYPE DU MANAGER DE TRANSITION", "CARTOGRAPHIE GÉOGRAPHIQUE",
# "ZONES DE NON-SOURCÉ CRITIQUES", "RISQUES MAJEURS NON PROVISIONNÉS".
def _is_structural_section_title(candidate: str) -> bool:
    """Since v16.5.67.5 — Titre de section long (3+ mots, tout en UPPERCASE ou
    dominé par UPPERCASE). Structuralement un titre markdown/section, pas
    une entité nommée. Rejeté par défaut car un vrai nom propre français
    dépasse rarement 2 mots tout en capitales."""
    stripped = candidate.strip()
    if len(stripped) < 8:
        return False
    tokens = re.split(r"[\s\-]+", stripped)
    if len(tokens) < 3:
        return False
    # Tokens UPPERCASE (2+ lettres capitales contiguës)
    upper_tokens = [t for t in tokens if len(t) >= 2 and t.upper() == t and any(c.isalpha() for c in t)]
    # Tokens connecteurs reconnus (DE, DU, DES, ET, OU, LA, LE, NON, etc.)
    connector_tokens = [t for t in tokens if t.upper() in _UPPERCASE_CONNECTOR_WORDS]
    # Si tous les tokens non-connecteurs sont en UPPERCASE → titre de section
    non_connector_tokens = [t for t in tokens if t.upper() not in _UPPERCASE_CONNECTOR_WORDS]
    if not non_connector_tokens:
        return False
    all_upper = all(t.upper() == t and any(c.isalpha() for c in t) for t in non_connector_tokens)
    return all_upper and len(upper_tokens) >= 2


def _is_section_title_uppercase(candidate: str) -> bool:
    """
    v16.5.67 — F2 Exclusion "titre de section" RESTRICTIVE.

    On n'exclut comme titre de section QUE si la chaîne est dans le dictionnaire
    explicite `_SECTION_TITLE_NORM`. On n'utilise PAS l'heuristique "2+ mots en
    MAJUSCULES" parce qu'elle excluait à tort des vrais noms propres inventés
    comme "CABRE ACTIONNARIAT" (2 mots MAJ mais c'est une hallucination).

    Les titres de section du markdown (## Section) sont pré-strippés du texte
    agent avant validate_entities(), donc ce dictionnaire explicite suffit pour
    les cas résiduels (texte en maj dans le corps du rapport).
    """
    stripped = candidate.strip()
    if not stripped:
        return False
    # Dictionnaire explicite uniquement
    return _norm(stripped) in _SECTION_TITLE_NORM


def _is_meta_label(candidate: str) -> bool:
    """
    Étiquette méta auto-produite par le pipeline ou l'agent (NON SOURCÉ,
    INVENTION, REJETÉ, FAIT, ESTIM, etc.).
    """
    return _norm(candidate) in _META_LABELS_NORM


# ── v16.5.67.4 — Filtre mots-communs en UPPERCASE ────────────────────────
# Les agents LLM produisent régulièrement des mots courants en capitales
# pour l'emphase visuelle ("risque FORT", "position STABLE", "conclusion
# FAUSSE"). Ces mots n'ont rien d'entités nommées, ce sont des adjectifs
# ou des qualificatifs communs. Cette liste les exempte du flagging.
# Observés dans les runs du 19/04 : FORT, FORTE, FORTES, STABLE, MIXTE,
# FAUSSE, RISQUE, AUCUN, RISQUE ÉLEVÉ…
_COMMON_UPPERCASE_WORDS = {
    # Qualificatifs d'intensité
    "FORT", "FORTE", "FORTS", "FORTES", "FAIBLE", "FAIBLES",
    "ÉLEVÉ", "ÉLEVÉE", "ÉLEVÉS", "ÉLEVÉES", "ELEVE", "ELEVEE",
    "MOYEN", "MOYENNE", "MOYENS", "MOYENNES",
    "BAS", "BASSE", "HAUT", "HAUTE",
    "CRITIQUE", "CRITIQUES", "MAJEUR", "MAJEURE", "MINEUR", "MINEURE",
    # États / statuts
    "STABLE", "INSTABLE", "VOLATIL", "VOLATILE",
    "SAIN", "SAINE", "DÉGRADÉ", "DÉGRADÉE", "DEGRADE",
    "SOUS TENSION", "TENDU", "TENDUE",
    "ACTIF", "ACTIVE", "PASSIF", "PASSIVE",
    "ÉMERGENT", "ÉMERGENTE", "MATURE", "DÉCLINANT",
    # Évaluations qualitatives
    "FAUX", "FAUSSE", "VRAI", "VRAIE", "JUSTE", "INJUSTE",
    "COHÉRENT", "COHÉRENTE", "INCOHÉRENT", "INCOHÉRENTE",
    "COMPLET", "COMPLÈTE", "INCOMPLET", "INCOMPLÈTE",
    "PRUDENT", "PRUDENTE", "IRRÉALISTE", "RÉALISTE",
    "CONSERVATEUR", "CONSERVATRICE", "OPTIMISTE", "PESSIMISTE",
    "SOUS-ESTIMÉ", "SOUS-ESTIMÉE", "SURÉVALUÉ", "SURÉVALUÉE",
    "CORRIGÉ", "CORRIGÉE", "CORRIGÉS", "CORRIGÉES",
    # Quantifieurs / universels
    "AUCUN", "AUCUNE", "TOUT", "TOUTE", "TOUS", "TOUTES",
    "PARTIEL", "PARTIELLE", "TOTAL", "TOTALE", "COMPLET",
    # Mots-clés de structure (souvent en UPPERCASE dans les outputs agent)
    "RISQUE", "RISQUES", "OPPORTUNITÉ", "OPPORTUNITÉS",
    "REVENUS", "COÛTS", "COUTS", "MARGE", "MARGES",
    "IMPACT", "IMPACTS", "CONSÉQUENCE", "CONSEQUENCES",
    "OBJECTIF", "OBJECTIFS", "RÉSULTAT", "RÉSULTATS",
    "RECOMMANDATION", "RECOMMANDATIONS",
    "PRÉCONISATION", "PRÉCONISATIONS",
    "DÉCISION", "DÉCISIONS", "ARBITRAGE", "ARBITRAGES",
    "ACTEUR", "ACTEURS", "POSITIONNEMENT",
    "PRIORISER", "PRIORITAIRES", "PRIORITAIRE",
    # Types de contenu agent
    "DIAGNOSTIC", "DIAGNOSTICS", "SYNTHÈSE", "SYNTHÈSES",
    "ANALYSE", "ANALYSES", "CONSTAT", "CONSTATS",
    "TYPOLOGIE", "CATÉGORIE", "SEGMENT", "SEGMENTS",
    "TYPOLOGIE CLIENTS",

    # ─── v16.5.74 — Faux positifs identifiés sur 4 tests réels ──────────────
    # (dossier de conseil mai 2026 + FDE + dossier réseau de soins + dossier anglophone coté — ~85 FP cumulés)
    # Mots de structure éditoriale
    "PRIORITÉ", "PRIORITES", "PRIORITÉS", "PERIMETRE", "PÉRIMÈTRE",
    "ÉCART", "ECART", "ÉCARTS", "TENSIONS", "TENSIONS IDENTIFIÉS",
    "MARCHÉ", "MARCHE", "MARCHÉS", "MARCHES",
    "MISSION", "MISSIONS", "MAIS", "MARQUÉ", "MARQUE", "MARQUÉE",
    "ABSENT", "ABSENTE", "ABSENTS", "ABSENTES",
    "BLOQUANT", "BLOQUANTE", "BLOQUANTS",
    "SCÉNARIO", "SCENARIO", "SCÉNARIOS", "SCENARIOS",
    # Verbes d'action en majuscule (très fréquents en titre de section)
    "DOCUMENTER", "VENTILER", "CLARIFIER", "OPTIMISER", "AMÉLIORER", "AMELIORER",
    "SURVEILLER", "VÉRIFIER", "VERIFIER", "VÉRIFIER IMPÉRATIVEMENT",
    "À DOCUMENTER", "A DOCUMENTER", "À VENTILER", "A VENTILER",
    "À CLARIFIER", "A CLARIFIER", "À ARBITRER DG", "A ARBITRER DG",
    # Évaluations qualitatives complémentaires
    "POSITIF", "POSITIVE", "POSITIFS", "POSITIVES",
    "NÉGATIF", "NEGATIF", "NÉGATIVE", "NEGATIVE",
    "ACCEPTABLE", "ACCEPTABLES", "INACCEPTABLE",
    "RECOMMANDÉES", "RECOMMANDEES", "RECOMMANDÉ", "RECOMMANDE",
    # Patterns "NON + adjectif" (locutions de prudence du DAF)
    "NON SOURCÉ", "NON SOURCEE", "NON SOURCÉES", "NON SOURCEES",
    "NON VÉRIFIÉ", "NON VERIFIE", "NON VÉRIFIÉS", "NON VERIFIES",
    "NON VÉRIFIÉE", "NON VÉRIFIÉES",
    "NON DOCUMENTÉ", "NON DOCUMENTEE", "NON DOCUMENTÉE",
    "NON MODÉLISÉ", "NON MODELISE", "NON MODÉLISÉE",
    "NON ESTIMÉ", "NON ESTIME", "NON ESTIMÉE",
    "NON CHIFFRÉ", "NON CHIFFRE", "NON CHIFFRÉES",
    "NON FOURNI", "NON FOURNIS", "NON FOURNIE",
    "NON QUANTIFIÉ", "NON QUANTIFIE", "NON QUANTIFIÉE",
    "NON FIABILISÉ", "NON FIABILISE", "NON FIABILISÉE",
    "NON IDENTIFIÉ", "NON IDENTIFIE",
    # Termes financiers standards (jamais des entités)
    "CAPEX", "OPEX", "EBITDA", "EBIT", "FCF", "WCR", "BFR",
    "RATIO CP", "RATIO CP/TOTAL BILAN", "ROE", "ROIC", "ROCE", "ROA",
    "NET PROMOTER SCORE", "NPS",
    "FONDS DE ROULEMENT", "FOND DE ROULEMENT",
    "DRIVERS DE CA", "MOTEURS DE CA",
    # NOTE v16.5.74 : "Projections CA" et "Poids CA" volontairement EXCLUS
    # car ambigus (titre de section vs donnée chiffrée). Le test
    # test_004_vrais_noms_propres_restent_flagges les considère comme à flagger.
    # Si bug observé sur dossier réel, voir si ajout d'un pattern "Projections X"
    # est plus pertinent qu'une whitelist directe.
    # Méta / titres de sections fréquents en outputs agents
    "STRATÉGIQUE", "STRATEGIQUE", "STRATÉGIQUES",
    "PLAN STRATÉGIQUE", "CONCLUSION MÉTHODOLOGIQUE", "CONCLUSION METHODOLOGIQUE",
    "CALCUL IA", "HYPOTHÈSE IA", "HYPOTHESE IA",
    "POINT POSITIF", "POINT NEGATIF", "POINT NÉGATIF",
    "CORRECTION MAJEURE", "ANALYSE CORRIGÉE", "ANALYSE CORRIGEE",
    "HYPOTHÈSE CORRIGÉE", "HYPOTHESE CORRIGEE",
    # Verbes français usuels parfois capitalisés en début de phrase agent
    "JE RECOMMANDÉ", "JE RECOMMANDE", "LE CA", "L'EBITDA", "LA MARGE",
    # Termes commerciaux
    "CIBLAGE MILLENNIALS", "GEN Z", "GEN-Z", "MILLENNIALS",
    # Recours / instances françaises (non sourcés mais notoires)
    "RECOURS CONSEIL", "RECOURS CONSEIL D'ÉTAT", "CONSEIL D'ÉTAT", "CONSEIL D ETAT",
}
_COMMON_UPPERCASE_WORDS_NORM = {_norm(w) for w in _COMMON_UPPERCASE_WORDS}


def _is_common_uppercase_word(candidate: str) -> bool:
    """
    Since v16.5.67.4 — Mot-commun en UPPERCASE utilisé pour emphase visuelle.
    Les agents produisent régulièrement "risque FORT" ou "position STABLE"
    et l'extraction d'entités ramasse le mot capitalisé. Ces mots ne sont
    pas des entités nommées, ce sont des adjectifs/qualificatifs courants.
    """
    return _norm(candidate) in _COMMON_UPPERCASE_WORDS_NORM


_HORIZON_RE = re.compile(
    r"^[JTMWS]\d{0,3}"                    # T0, J3, M2, S1
    r"(?:[-–][JTMWS]?\d{0,3})?"       # -T, -T6, -J30
    r"(?:\s*[+\-]\s*\d{1,3}\s*[jJ]?)?$",  # +90j, +3
    re.IGNORECASE)


def _is_horizon_token(candidate: str) -> bool:
    """S.2.4.4 — jalon/horizon d'exécution (T0, T0-T+90j, T+90j, J+3…). Ces tokens
    ne sont PAS des entités : l'annotateur injectait « [NON SOURCÉ] » en plein milieu
    (« T0-T [NON SOURCÉ]+90j ») sur le run dossier industriel (composants) v5."""
    return bool(_HORIZON_RE.match((candidate or "").strip()))


def _is_temporal_pattern(candidate: str) -> bool:
    """Pattern temporel (J1-14, T+30, SEMAINE 3, S1-S2…)."""
    stripped = candidate.strip()
    if not stripped:
        return False
    return bool(_TEMPORAL_PATTERN_RE.match(stripped))


def _is_date_range(candidate: str) -> bool:
    """v16.5.74 — Plage temporelle / référence d'exercice.

    Exemples : "Mai-Juin 2026", "Juillet-Septembre 2026", "Janvier-Avril 2027",
    "T1 2026", "Q1 2026", "H1 2026", "FY24", "FY24/25", "FY 2025", "9M FY2026".

    Ces patterns ne sont PAS des entités à valider — ce sont des références
    temporelles standard du métier finance/contrôle de gestion.
    Identifié comme faux positif sur 4 tests cumulés (dossier de conseil, FDE,
    dossier réseau de soins, dossier anglophone coté — ~25 occurrences sur dossier anglophone coté seul avec FY24/FY25).
    """
    stripped = candidate.strip()
    if not stripped:
        return False
    return bool(_DATE_RANGE_RE.match(stripped))


def _is_liasse_fr_line(candidate: str) -> bool:
    """v16.5.74 — Code ligne liasse fiscale française 2050-2059.

    Exemples : "Ligne HI", "Ligne HJ", "Ligne FL", "Ligne BT", "Ligne GW",
    "Ligne HN", "Ligne HK", "Lignes BT", etc.

    Ces codes désignent des cellules officielles du formulaire CERFA
    2050-2059 (compte de résultat + bilan société individuelle).
    Tout DAF / contrôleur de gestion les reconnaît — ce ne sont pas des
    entités à valider mais des références techniques métier.

    Identifié sur dossier réseau de soins (8 occurrences flagguées : Ligne HI, HJ, HK,
    FL, GW, HN, BT — toutes sont des codes liasse standard).
    """
    stripped = candidate.strip()
    if not stripped:
        return False
    return bool(_LIASSE_FR_LINE_RE.match(stripped))


# ── API principale ──────────────────────────────────────────────────────────
def validate_entities(
    text: str,
    whitelist: Iterable[str],
    mode: str = "annotate",
    lang: str = "fr",
) -> EntityValidationResult:
    """
    Valide les entités nommées d'un texte LLM contre une whitelist.

    Paramètres
    ----------
    text : str
        Sortie brute du LLM à valider.
    whitelist : Iterable[str]
        Entités autorisées (construites via build_whitelist() depuis
        brief + attachments + contexte Pappers).
    mode : str
        "annotate" → ajoute ` [NON SOURCÉ]` après chaque occurrence
        "strip"    → remplace par ` [entité non vérifiée]`
        "log_only" → ne modifie pas le texte

    Retourne
    --------
    EntityValidationResult avec texte (potentiellement) annoté et
    liste des entités flaggées.
    """
    if not text:
        return EntityValidationResult(validated_text=text or "")

    whitelist_norm = {_norm(e) for e in whitelist if e}
    flagged: list[str] = []
    flagged_set: set[str] = set()

    # Collecte des matches avec positions (pour remplacement)
    matches: list[tuple[int, int, str]] = []
    seen_spans: list[tuple[int, int]] = []  # éviter doublons multiword+acronym

    for m in _ENTITY_MULTIWORD_RE.finditer(text):
        matches.append((m.start(), m.end(), m.group(0)))
        seen_spans.append((m.start(), m.end()))

    for m in _ACRONYM_RE.finditer(text):
        # ne pas doubler si déjà couvert par un match multiword
        overlap = any(
            (m.start() >= s and m.end() <= e)
            for (s, e) in seen_spans
        )
        if overlap:
            continue
        matches.append((m.start(), m.end(), m.group(0)))

    matches.sort(key=lambda x: x[0])
    candidates_count = len(matches)

    # Application des règles et construction du texte annoté
    out_parts: list[str] = []
    cursor = 0
    for start, end, candidate in matches:
        raw = candidate
        # skip si déjà suivi de notre marqueur (idempotence)
        tail = text[end:end + 20]
        if tail.lstrip().startswith(("[NON SOURCÉ]", "[entité non vérifiée]")):
            continue
        if _is_numeric_or_amount(raw):
            continue

        # v16.5.67 F2 — 3 nouvelles exclusions anti-faux-positif
        # (retour run 18/04 v16.5.66 : ~70% de bruit sur des titres / patterns / meta)
        if _is_section_title_uppercase(raw):
            continue
        if _is_meta_label(raw):
            continue
        if _is_temporal_pattern(raw):
            continue
        if _is_horizon_token(raw):   # S.2.4.4 — T0-T+90j, T+90j, J+3…
            continue
        # v16.5.74 — Plages de mois et codes liasse fiscale française
        if _is_date_range(raw):
            continue
        if _is_liasse_fr_line(raw):
            continue
        # v16.5.67.4 — mots-communs UPPERCASE (FORT, STABLE, FAUSSE, RISQUE…)
        if _is_common_uppercase_word(raw):
            continue
        # v16.5.67.5 — 4 nouveaux filtres structurels
        if _is_french_region(raw):
            continue
        if _is_generic_template_label(raw):
            continue
        if _is_malformed_with_uppercase_connector(raw):
            continue
        if _is_structural_section_title(raw):
            continue

        # Si le premier token est un verbe d'action / mot-outil, on le strip
        # et on travaille sur le reste — ce qui permet de détecter quand
        # l'entité réelle est dans la whitelist ("Contacter BPI France"
        # → "BPI France" qui est dans la whitelist).
        effective = _strip_leading_action_word(raw)
        if not effective or len(effective.split()) < 1:
            continue
        # Si le strip a réduit à un mono-mot non acronyme et non capitalisé
        # distinctement, on considère que ce n'était pas une entité.
        if effective != raw and len(effective.split()) == 1 and not effective.isupper():
            continue

        if _is_institutional(effective):
            continue
        # v16.5.67 F2 — appliquer aussi les nouvelles exclusions sur la version "effective"
        if _is_section_title_uppercase(effective):
            continue
        if _is_meta_label(effective):
            continue
        if _is_temporal_pattern(effective):
            continue
        # v16.5.74 — Plages de mois et codes liasse fiscale française (effective)
        if _is_date_range(effective):
            continue
        if _is_liasse_fr_line(effective):
            continue
        # v16.5.67.4 — mots-communs UPPERCASE sur la version effective aussi
        if _is_common_uppercase_word(effective):
            continue
        # v16.5.67.5 — les 4 nouveaux filtres sur la version effective aussi
        if _is_french_region(effective):
            continue
        if _is_generic_template_label(effective):
            continue
        if _is_malformed_with_uppercase_connector(effective):
            continue
        if _is_structural_section_title(effective):
            continue
        if _norm(effective) in whitelist_norm:
            continue
        # v62.13.9.4.49 — un libellé de nomenclature suivi de son numéro (« Option 2 », « Phase 1 »,
        # « Scope 3 ») n'est pas une entité : définition PARTAGÉE des non-quantités (run réel du
        # 28/09/2026 : « Is Option [UNSOURCED] 2 authorized… » dans la synthèse).
        try:
            from utils.non_quantity import NOMENCLATURE_RE as _NQ_NOMEN49
            if any(m.start() <= start < m.end() or m.start() < end <= m.end()
                   for m in _NQ_NOMEN49.finditer(text)):
                continue
        except Exception:
            pass
        # Sourcing par inclusion : si la partie effective (après strip) est
        # contenue dans une entrée de whitelist ou inversement, on considère
        # que c'est sourcé. Exemple : "BPI France" dans la whitelist
        # capture "Contacter BPI France" → effective="BPI France" → OK.
        eff_norm = _norm(effective)
        if any(eff_norm in w or w in eff_norm for w in whitelist_norm if len(w) >= 4):
            continue
        # Même test sur les institutional (ex. "BPI" institutional capture
        # "BPI France" non explicité dans la whitelist).
        if any(eff_norm in inst or inst in eff_norm for inst in INSTITUTIONAL_ALL if len(inst) >= 3):
            continue

        # Non sourcé → on flag
        if eff_norm not in flagged_set:
            flagged.append(effective)
            flagged_set.add(eff_norm)

        if mode == "annotate":
            out_parts.append(text[cursor:end])
            out_parts.append(" [NON SOURCÉ]")
            cursor = end
        elif mode == "strip":
            out_parts.append(text[cursor:start])
            out_parts.append("[entité non vérifiée]")
            cursor = end
        else:  # log_only
            pass

    # ── v17.1-B2.3-B — Garde de densité (anti-flood « [NON SOURCÉ] ») ───────
    # Sur une note industrielle riche, l'annotation inline de CHAQUE entité hors
    # whitelist (concurrents, technos, acronymes : Air Liquide, PEM, OTIF, IPCEI…)
    # inonde la prose et la rend illisible. Au-delà d'un seuil, on n'annote PLUS
    # inline : la liste flaggée reste dans le résultat (signal anti-hallucination
    # intégralement préservé) + une note de synthèse UNIQUE. La détection est
    # inchangée ; seul l'AFFICHAGE inline est densité-limité.
    _FLOOD_THRESHOLD = 12
    _flood = (mode == "annotate" and len(flagged) > _FLOOD_THRESHOLD)
    if _flood:
        # v62.13.9.4.38 — l'avis d'outil suit la langue du run : il apparaissait en
        # français dans les documents anglais (deux runs réels du 19/09/2026), et son
        # « É » faisait basculer la détection de langue de la ligne.
        _en38 = str(lang or "").lower().startswith("en")
        _note = ((f"\n\n> ⚠ Entity validation: {len(flagged)} entities outside verified "
                  f"sources detected (list in the diagnostic). Inline annotation removed "
                  f"for readability — entities to be checked by the consultant before "
                  f"distribution.") if _en38 else
                 (f"\n\n> ⚠ Validation des entités : {len(flagged)} entités hors "
                  f"sources vérifiées détectées (liste en diagnostic). Annotation "
                  f"inline supprimée pour lisibilité — entités à vérifier par le "
                  f"consultant avant diffusion."))
        validated_text = text + _note
    elif mode in ("annotate", "strip"):
        out_parts.append(text[cursor:])
        validated_text = "".join(out_parts)
    else:
        validated_text = text

    return EntityValidationResult(
        validated_text=validated_text,
        flagged_entities=flagged,
        whitelist_size=len(whitelist_norm),
        candidates_count=candidates_count,
        flagged_count=len(flagged),
    )


# ── Helper de haut niveau pour intégration pipeline ─────────────────────────
def validate_role_output(
    output: str,
    brief: str = "",
    attachments_text: str = "",
    pappers_context: str = "",
    facts_table_text: str = "",  # v16.5.74 — Couche 1 sourcée
    mode: str = "annotate",
) -> EntityValidationResult:
    """
    Helper qui combine build_whitelist + validate_entities en un seul appel.
    C'est cette fonction qui est branchée dans codir_engine._call_with_fallback.

    v16.5.74 — Le paramètre `facts_table_text` reçoit le markdown de la table
    de faits Couche 1 (cf. _facts_ctx dans codir_engine). Tout terme/entité
    présent dans cette table est ajouté à la whitelist : la règle
    structurelle "ne pas tagger NON SOURCÉ ce qui est déjà dans la Couche 1"
    est ainsi appliquée mécaniquement.

    Avant v16.5.74 : "CAPEX [NON SOURCÉ]" sur FDE alors que CAPEX figurait
    dans la table Couche 1 avec valeur 250. Bug corrigé en v16.5.74.
    """
    whitelist = build_whitelist(
        brief,
        attachments_text,
        pappers_context,
        facts_table_text,  # v16.5.74 — Couche 1 ajoutée à la whitelist
    )
    return validate_entities(output, whitelist, mode=mode)
