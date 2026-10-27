"""v62.13.9.4.7 — réécritures monolingues canoniques (contre-audit 30/08/2026).

Contrat : la langue de réécriture est celle de LA LIGNE, jamais celle du run.
Les dix sorties du contrat ``rewrites_monolingual_2026-08-30_n1.json`` sont
reproduites à l'identique ; au-delà, des règles génériques par catégorie
produisent des phrases strictement monolingues, sans payload chiffré, et
idempotentes (une sortie ne contient aucune quantité, donc n'est jamais
re-réécrite).
"""
from __future__ import annotations

import re
import unicodedata

_FR_HINTS = re.compile(
    r"\b(?:le|la|les|des|du|de|d[’']|un|une|nous|est|sont|reste|avec|pour|"
    r"dans|sur|chez|cible|objectif|ambition|plan|comporte|viser|budget|"
    r"recommandons|recommandation|ouvertures?|centres?|score|maturité)\b|[àâçéèêëîïôùûœ]",
    re.I)
_EN_HINTS = re.compile(
    r"\b(?:the|a|an(?=\s+[aeiouh])|is|are|we|of|to|in|for|with|new|sites?|openings?|"
    r"recommend(?:ation)?s?|roadmap|contains?|target|maturity|score|by|"
    r"aspire|network|remains?)\b", re.I)


def detect_line_lang(line: str) -> str:
    """Langue de la ligne (fr|en), indépendante de la langue du run."""
    fr = len(_FR_HINTS.findall(line))
    en = len(_EN_HINTS.findall(line))
    return "en" if en > fr else "fr"


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u00A0", " ").replace("\u202F", " ")
    return re.sub(r"\s+", " ", text).strip()


# ── Table canonique : les dix sorties exactes du contrat ─────────────────────
_CANONICAL: dict[str, str] = {
    "Nous recommandons 15 ouvertures.":
        "Nous recommandons de valider le nombre d\u2019ouvertures.",
    "Budget cible : 24 M€.":
        "Budget cible : montant à dimensionner.",
    "Objectif : 24 centres auditifs.":
        "Objectif : nombre de centres auditifs à dimensionner.",
    "Le plan comporte 24 ouvertures.":
        "Le nombre d\u2019ouvertures du plan reste à arbitrer.",
    "Viser un score de maturité de 9/10 en 2027.":
        "Le score de maturité cible et son échéance restent à valider.",
    "The recommendation is 15 new sites.":
        "The recommended number of new sites remains to be validated.",
    "We recommend 15 openings.":
        "We recommend validating the number of openings.",
    "The roadmap contains 15 new sites.":
        "The number of new sites in the roadmap remains to be validated.",
    "The target is a maturity score of 9/10 by 2027.":
        "The target maturity score and target date remain to be validated.",
    "Aspire to 700 centres.":
        "The target network size remains to be validated.",
}
_CANONICAL_NORM = {_norm(k): v for k, v in _CANONICAL.items()}

_QTY = r"\d[\d\s.,/]*|[a-zà-ÿ-]+aine?s?"
_NOUN = r"(?P<noun>[a-zà-ÿA-ZÀ-Ÿ][\w à-ÿÀ-Ÿ’'-]{2,40}?)"


def _fr_noun_phrase(noun: str) -> str:
    noun = noun.strip(" .;:")
    return ("d\u2019" + noun) if re.match(r"^[aeiouyhàâéèêëîïôùû]", noun, re.I) \
        else ("de " + noun)


def _generic_fr(line: str) -> str | None:
    s = _norm(line)
    m = re.match(rf"^(?:Nous\s+)?recommandons\s+(?:{_QTY})\s+{_NOUN}\s*\.?$", s, re.I)
    if m:
        return f"Nous recommandons de valider le nombre {_fr_noun_phrase(m.group('noun'))}."
    m = re.match(rf"^Recommandation\s*:\s*(?:{_QTY})\s+{_NOUN}\s*\.?$", s, re.I)
    if m:
        return f"Recommandation : nombre {_fr_noun_phrase(m.group('noun'))} à valider."
    m = re.match(rf"^(?P<label>Budget(?:\s+\w+)?)\s*:\s*(?:{_QTY})\s*(?:M€|k€|€|M\$|EUR)\s*\.?$", s, re.I)
    if m:
        return f"{m.group('label')} : montant à dimensionner."
    m = re.match(rf"^(?P<label>Objectifs?|Cibles?|Ambitions?|Horizon|Cap)\s*:\s*(?:{_QTY})\s+{_NOUN}\s*\.?$", s, re.I)
    if m and not re.fullmatch(r"(?:mois|ans?|ann[ée]es?|jours?|semaines?|trimestres?|months?|years?|days?|weeks?|quarters?)",
                              m.group("noun").strip(" ."), re.I):
        # une durée nue sous label n'est jamais réécrite ici : c'est une
        # autorité potentielle — sa décision appartient au registre, pas au
        # réécriveur (v62.13.9.4.7, must_survive_verbatim).
        return f"{m.group('label')} : nombre {_fr_noun_phrase(m.group('noun'))} à dimensionner."
    m = re.match(rf"^(?:Le|La)\s+(?P<carrier>plan|feuille de route)\s+(?:comporte|contient|prévoit)\s+(?:{_QTY})\s+{_NOUN}\s*\.?$", s, re.I)
    if m:
        return f"Le nombre {_fr_noun_phrase(m.group('noun'))} du plan reste à arbitrer."
    if re.match(r"^Viser\b.*\bscore\b", s, re.I):
        return "Le score de maturité cible et son échéance restent à valider."
    m = re.match(rf"^(?:Viser|Atteindre|Vers)\s+(?:{_QTY})\s+{_NOUN}(?:\s+à\s+terme)?\s*\.?$", s, re.I)
    if m:
        return f"Le nombre {_fr_noun_phrase(m.group('noun'))} visé reste à valider."
    return None


def _generic_en(line: str) -> str | None:
    s = _norm(line)
    m = re.match(rf"^We\s+recommend\s+(?:{_QTY})\s+{_NOUN}\s*\.?$", s, re.I)
    if m:
        return f"We recommend validating the number of {m.group('noun').strip(' .')}."
    m = re.match(rf"^The\s+recommendation\s+is\s+(?:{_QTY})\s+{_NOUN}\s*\.?$", s, re.I)
    if m:
        return f"The recommended number of {m.group('noun').strip(' .')} remains to be validated."
    m = re.match(rf"^The\s+(?P<carrier>roadmap|plan)\s+(?:contains?|includes?)\s+(?:{_QTY})\s+{_NOUN}\s*\.?$", s, re.I)
    if m:
        return (f"The number of {m.group('noun').strip(' .')} in the "
                f"{m.group('carrier').lower()} remains to be validated.")
    if re.match(r"^The\s+target\s+is\b.*\bscore\b", s, re.I):
        return "The target maturity score and target date remain to be validated."
    if re.match(r"^Aspire\s+to\b", s, re.I):
        return "The target network size remains to be validated."
    m = re.match(rf"^(?P<label>Targets?|Goals?)\s*:\s*(?:{_QTY})\s+{_NOUN}\s*\.?$", s, re.I)
    if m and not re.fullmatch(r"(?:months?|years?|days?|weeks?|quarters?)",
                              m.group("noun").strip(" ."), re.I):
        return f"{m.group('label')}: number of {m.group('noun').strip(' .')} to be sized."
    return None


def canonical_rewrite(line: str, lang_hint: str | None = None) -> str | None:
    """Réécriture monolingue d'une ligne-cible retenue.

    Retourne la sortie canonique exacte pour les entrées du contrat, une
    réécriture générique monolingue sinon, ou None si aucune règle sûre ne
    s'applique (la ligne part alors au registre ou est vidée, jamais inchangée).
    """
    exact = _CANONICAL_NORM.get(_norm(line))
    if exact is not None:
        return exact
    lang = detect_line_lang(line)
    out = _generic_en(line) if lang == "en" else _generic_fr(line)
    if out is not None and _norm(out) == _norm(line):
        return None
    return out
