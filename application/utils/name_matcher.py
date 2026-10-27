"""
utils/name_matcher.py — Patch v16.5.72.11

Normalisation et matching de noms d'entreprises pour comparaison robuste
entre la saisie utilisateur (UI) et les retours des bases (Pappers, CH, GLEIF).

Cas réel observé sur FDE (v16.5.72.10) :
    UI Robin    : "Française de l'énergie"
    Pappers     : "LA FRANCAISE DE L'ENERGIE"
    Match v72.10 : 🚨 "incohérence UI ↔ Pappers" (FAUX — c'est la même entité)

Cause :
- Pas de strip d'accents (é vs e)
- Pas de strip d'articles (LA, LE, THE)
- Pas de strip des suffixes corporatifs (GROUPE, Group, plc, Ltd, SA, SAS, ...)

Approche v16.5.72.11 :
    1. Lowercase
    2. Strip accents (NFD + filter combining)
    3. Strip ponctuation et caractères spéciaux
    4. Strip articles (FR + EN)
    5. Strip suffixes corporatifs (FR + UK + US/global)
    6. Tokeniser et comparer

Match levels :
    - "exact"     : noms strictement identiques après normalisation
    - "contains"  : un nom contient l'autre (préfixe ou suffixe)
    - "shared"    : tokens significatifs partagés (≥1)
    - "none"      : aucune correspondance
"""
from __future__ import annotations

import re
import unicodedata
from typing import Set, Tuple


# ════════════════════════════════════════════════════════════════════════════
# Listes de strip
# ════════════════════════════════════════════════════════════════════════════

# Articles à retirer en début de chaîne
_ARTICLES = {
    "le", "la", "les", "l", "un", "une", "des",  # FR
    "the", "a", "an",  # EN
    "el", "los", "las",  # ES
    "der", "die", "das",  # DE
    "il", "lo", "i", "gli",  # IT
}

# Suffixes / formes juridiques à retirer (n'importe où)
_LEGAL_FORMS = {
    # FR
    "sa", "sas", "sasu", "sarl", "eurl", "sci", "scp", "snc",
    "selarl", "selas", "scop", "sem", "spfpl", "sccv",
    # UK
    "ltd", "limited", "plc", "llp", "lp", "company", "co",
    # US / global
    "inc", "incorporated", "corp", "corporation", "llc",
    # DE
    "gmbh", "ag", "kg", "ohg",
    # NL / BE
    "bv", "nv", "sprl",
    # IT
    "spa", "srl", "sapa",
    # ES
    "sl", "slu",
    # Communs (en plus des formes juridiques pures)
    "group", "groupe", "holding", "holdings", "international",
    "global", "europe", "european", "industries", "company",
}

# Mots vides très courts à ignorer dans la comparaison
_STOPWORDS_SHORT = {"de", "du", "la", "le", "et", "of", "and", "or", "for", "in", "on", "at"}


# ════════════════════════════════════════════════════════════════════════════
# Fonctions de normalisation
# ════════════════════════════════════════════════════════════════════════════


def strip_accents(s: str) -> str:
    """Retire tous les diacritiques. 'élève' → 'eleve'."""
    if not s:
        return ""
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if not unicodedata.combining(c))


def normalize_company_name(s: str) -> str:
    """
    Normalisation complète d'un nom d'entreprise pour comparaison.

    Étapes :
        1. Lowercase + strip accents
        2. Retirer ponctuation et caractères spéciaux
        3. Tokeniser
        4. Retirer articles en tête
        5. Retirer formes juridiques
        6. Joindre par espace

    Examples :
        "Française de l'énergie"      → "francaise energie"
        "LA FRANCAISE DE L'ENERGIE"   → "francaise energie"
        "Exemple Audition Groupe SAS"           → "exemple audition"
        "Example Fashion Group plc"          → "example fashion"
        "Société Générale SA"         → "societe generale"
    """
    if not s or not isinstance(s, str):
        return ""

    # 1. Lowercase + strip accents
    s = strip_accents(s).lower().strip()

    # 2. Retirer ponctuation (apostrophes, tirets, parenthèses, etc.)
    s = re.sub(r"[^\w\s]", " ", s)

    # 3. Tokeniser
    tokens = s.split()

    # 4. Retirer articles en tête (peut être plusieurs : "the la dossier réseau de soins")
    while tokens and tokens[0] in _ARTICLES:
        tokens.pop(0)

    # 5. Retirer formes juridiques (n'importe où)
    tokens = [t for t in tokens if t not in _LEGAL_FORMS]

    # 6. Retirer articles entre les mots aussi (cas "le LA energie" residual)
    tokens = [t for t in tokens if t not in _ARTICLES]

    return " ".join(tokens)


def get_significant_tokens(s: str, min_len: int = 3) -> Set[str]:
    """
    Retourne les tokens "significatifs" pour comparaison :
    - Normalisés
    - Longueur >= min_len
    - Pas dans les stopwords courts
    """
    normalized = normalize_company_name(s)
    return {
        t for t in normalized.split()
        if len(t) >= min_len and t not in _STOPWORDS_SHORT
    }


# ════════════════════════════════════════════════════════════════════════════
# Matching
# ════════════════════════════════════════════════════════════════════════════


def match_company_names(name_a: str, name_b: str) -> Tuple[str, float]:
    """
    Compare deux noms d'entreprise et retourne (level, score).

    Returns:
        ("exact",    1.0)  si normalized(a) == normalized(b)
        ("contains", 0.9)  si l'un contient strictement l'autre (≥3 chars)
        ("shared",   0.7)  si tokens significatifs partagés (au moins 1)
        ("none",     0.0)  sinon
    """
    if not name_a or not name_b:
        return ("none", 0.0)

    norm_a = normalize_company_name(name_a)
    norm_b = normalize_company_name(name_b)

    if not norm_a or not norm_b:
        return ("none", 0.0)

    # 1. Exact match après normalisation
    if norm_a == norm_b:
        return ("exact", 1.0)

    # 2. Contains (l'un dans l'autre, ≥3 chars pour éviter false positives)
    if len(norm_a) >= 3 and len(norm_b) >= 3:
        if norm_a in norm_b or norm_b in norm_a:
            return ("contains", 0.9)

    # 3. Tokens significatifs partagés
    tokens_a = get_significant_tokens(name_a)
    tokens_b = get_significant_tokens(name_b)
    shared = tokens_a & tokens_b
    if shared:
        # Score proportionnel au % de tokens partagés
        ratio = len(shared) / max(len(tokens_a), len(tokens_b))
        return ("shared", round(0.5 + 0.4 * ratio, 2))

    return ("none", 0.0)


def is_match(name_a: str, name_b: str, threshold: float = 0.5) -> bool:
    """Helper booléen : True si les deux noms matchent à seuil donné."""
    level, score = match_company_names(name_a, name_b)
    return score >= threshold


# ════════════════════════════════════════════════════════════════════════════
# Détection de faute de frappe (v17.1-B2.3-C, item 4 audit)
# ════════════════════════════════════════════════════════════════════════════
def _levenshtein(a: str, b: str) -> int:
    """Distance d'édition (insertions/suppressions/substitutions)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def is_probable_typo(name_a: str, name_b: str) -> bool:
    """True si deux noms sont à une faible distance d'édition (faute de frappe
    probable : « Khyfe » vs « Lhyfe »). Sert à DISTINGUER une coquille de saisie
    d'une vraie incohérence d'entité — quand le SIREN, lui, a résolu correctement.
    Conservateur : distance <= 2 ET <= ~⅓ de la longueur du plus court nom."""
    na, nb = normalize_company_name(name_a), normalize_company_name(name_b)
    if not na or not nb or na == nb:
        return False
    d = _levenshtein(na, nb)
    shorter = min(len(na), len(nb))
    if shorter < 3:
        return False
    return d <= 2 and d <= max(1, shorter // 3)
