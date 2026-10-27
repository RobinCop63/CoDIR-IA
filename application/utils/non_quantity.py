"""v62.13.9.4.48 — reconnaissance PARTAGÉE des non-quantités (programme 9.4.48, point 3, extension
validée par Robin Sauzet le 27/09/2026).

Pourquoi. Une même notion — « ce nombre n'est pas une quantité » — était décidée dans cinq
chemins par des règles différentes. La revue de méthode du 27/09/2026 l'a diagnostiqué ; le
corpus de frontières (tests/test_v62139_4_48_boundary_corpus.py) l'a mesuré : treize divergences
sur des lignes sans quantité (« Scope 3 … » retenu par le registre, le juge et le mainteneur alors
que la règle éditoriale l'exemptait depuis la 9.4.45 ; un identifiant étiqueté (« CIK SEC nnnnnn ») vu comme une quantité par
la règle éditoriale et le registre, etc.). Chaque correctif local laissait les autres chemins en
l'état — d'où les régressions voisines des cycles 9.4.44 à 9.4.47.

Ce module est la définition UNIQUE pour les chemins de PRODUCTION : règle éditoriale, registre,
mainteneur de surface, index déclaré. Le juge indépendant garde sa propre implémentation, par
doctrine (9.4.9 : aucune table partagée avec la production) ; le corpus vérifie que les deux
s'accordent aux frontières.

Règles de conception :
- les positions renvoyées portent sur le texte d'ORIGINE ; masquer ne sert qu'à ne pas compter un
  nombre, jamais à fournir au classement un texte amputé de son contexte (régression 9.4.46 :
  l'année d'une cible masquée, le cadre futur perdu) ;
- une période n'est pas une nomenclature : elle porte le CADRE temporel d'une cible et reste au
  registre, qui la type lui-même ; elle est offerte à part (``period_label``) ;
- un nombre suivi d'une unité ou d'une échelle (%, €, k€, M€, m, bn, pts) n'est jamais masqué par
  une nomenclature : « niveau 30 % » reste une grandeur.
"""
from __future__ import annotations

import re

_NOMEN_WORDS = (
    r"(?:scopes?|options?|phases?|tiers?|levels?|niveaux?|pillars?|piliers?|axes?|axis|waves?|vagues?|"
    r"lots?|steps?|[ée]tapes?|articles?|art\.|annex(?:es?)?|chapters?|chapitres?|sections?|iso|ifrs|ias|"
    r"ansi|tables?|tableaux?|figures?|fig\.|notes?|slides?|planches?|volets?|rounds?|tours?|sprints?|"
    # v62.13.9.4.50 — libellés d'agent numérotés (« PARADE 1 », « RECOMMANDATION 1 », « RISQUE 2 »), vrai CR du 30/09
    r"parades?|recommandations?|recommendations?|d[ée]cisions?|risques?|risks?|arbitrages?|priorit[ée]s?|priorities|"
    r"challenges?|leviers?|levers?|chantiers?|workstreams?|sc[ée]narios?|hypoth[èe]ses?|assumptions?)"
)
_NOT_A_UNIT = r"(?!\s*(?:%|‰|€|\$|£|k€|m€|md€|pts?\b|points?\b|bps?\b))"
# v62.13.9.4.48 — ni une DURÉE, ni une fourchette qui se prolonge : « recruitment phase 12-18
# months » est un horizon à juger (contrat 13.9.2), pas la « phase 12-18 » (attrapé par l'étage
# d'intégration le jour même : la règle éditoriale de la 9.4.45 avait ce défaut, invisible).
_NOT_A_DURATION_OR_RANGE = (r"(?!\s*(?:[-–/]\s*\d|%|‰|€|\$|£|k€|m€|pts?\b|points?\b|mois\b|months?\b|ans?\b|ann[ée]es?\b|"
                            r"years?\b|yrs?\b|jours?\b|days?\b|semaines?\b|weeks?\b|trimestres?\b|quarters?\b|heures?\b|hours?\b|h\b|min\b))")

# Nomenclature : numéro d'un libellé de structure ou de norme, chaînes comprises
# (« Option 1 vs 2 vs 3 », « Scope 1, 2 et 3 », « Phase 1 à 3 ») ; rang « #1 ».
NOMENCLATURE_RE = re.compile(
    rf"\b{_NOMEN_WORDS}\s*#?\s*\d{{1,5}}{_NOT_A_UNIT}"
    rf"(?:\s*(?:vs\.?|,|ou|or|/|et|and|à|to|\+|[-–])\s*(?:{_NOMEN_WORDS}\s*)?\d{{1,5}}{_NOT_A_UNIT})*\b{_NOT_A_DURATION_OR_RANGE}"
    r"|#\d{1,5}\b",
    re.IGNORECASE,
)
# Repère de période : cadre temporel, pas une quantité — offert à part (voir docstring).
PERIOD_LABEL_RE = re.compile(r"\b(?:Q|T|H|S)[1-4]\b(?:\s?(?:19|20)?\d{2})?\b|\bFY\s?\d{2,4}\b|\bCY\s?\d{4}\b", re.IGNORECASE)
# Nom comportant un nombre : A-320, COVID-19, B-52 — jamais une année (« mid-2027 » est un cadre).
HYPHEN_NAME_RE = re.compile(r"(?<=[A-Za-z])[-‑–](?!(?:19|20)\d{2}\b)\d{1,6}\b")
# Identifiant étiqueté, avec un mot intermédiaire possible (« CIK SEC nnnnnn », « SEC CIK … »).
LABELLED_ID_RE = re.compile(
    r"(?i)\b(?:LEI|SIREN|SIRET|ISIN|CIK|SEC|RCS|TVA|VAT|IBAN|BIC|DUNS|n[°º]|no\.|ref\.?|réf\.?|id)"
    r"(?:\s+\w{1,6})?\s*[:#]?\s*[A-Z0-9]{4,}\b")
# Jeton alphanumérique d'identifiant : au moins deux lettres et trois chiffres. Jamais un montant
# à suffixe d'échelle (999m, 12k, 1,2bn : une seule lettre ou pas assez de chiffres) ni un repère
# de période (FY2025, Q32026), qui reste au registre.
ALNUM_ID_RE = re.compile(
    r"\b(?!(?:FY|CY|Q[1-4]|H[12]|S[12]|T[1-4])\d{2,4}\b)"
    r"(?=(?:[A-Za-z0-9]*[A-Za-z]){2})(?=(?:[A-Za-z0-9]*\d){3})[A-Za-z0-9]{5,}\b")
# Ligne technique du produit : « Layer 1 status: ✓ OK (14 facts, 60 ms) ».
# v62.13.9.4.49 — pagination écrite par le produit (« 14 of 15 entries — detail: Report §4 »), audit du 29/09/2026.
TECHNICAL_RE = re.compile(r"(?i)\b(?:layer|couche)\s+\d\s+status.*$|\(\s*\d+\s*facts?,\s*\d+\s*ms\s*\)"
                          r"|\b\d+\s+(?:of|sur)\s+\d+\s+(?:entries|entrées|items|éléments|lines|lignes)\b")

# v62.13.9.4.49 — NOM DE FICHIER (pièce citée comme source : « STRATE~1.PDF p.29 », « …-25-000067_…20250831.pdf ») :
# ses chiffres ne sont pas des valeurs. Audit du 29/09/2026 : sans reformulation canonique, le nom de la pièce reste
# dans la ligne de fait, et « ~1 » ou « 000067 » étaient lus comme des grandeurs.
FILE_NAME_RE = re.compile(r"(?i)\b[\w~.\-]*\d[\w~.\-]*\.(?:pdf|docx?|xlsx?|pptx?|csv|txt|json|zip|xml|html?)\b")

# v62.13.9.4.50 — MARQUEUR ORDINAL d'une liste ou d'une rubrique (« [4] ORIENTATION… », « [PARADE 1 — … ] »,
# « 6. Présenter… ») : un rang, pas une grandeur (échantillon du vrai CR du 30/09 : un faux signalement sur deux).
# v62.13.9.4.50 — FORMULAIRES RÉGLEMENTAIRES (« 10-K », « 20-F », « 10-Q », « 8-K », « DEF 14A ») : un nom de pièce,
# pas une grandeur (vrai CR du 30/09 : « (source : 10-K FY2025 p.48) » rendait la ligne de trésorerie confirmée douteuse).
SEC_FORM_RE = re.compile(r"\b(?:10-K|10-Q|20-F|40-F|8-K|6-K|S-1|F-1|DEF\s?14A)(?:/A)?\b", re.IGNORECASE)

ORDINAL_RE = re.compile(r"(?m)^\s*\[\s*\d{1,2}\s*\]|\[\s*[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ’' ]{2,30}\s+\d{1,2}\b(?=[^\]]{0,60}\])"
                        r"|^\s*\d{1,2}[.)]\s+(?=[A-ZÀ-Ý])")

CATEGORIES = {
    "sec_form": SEC_FORM_RE,
    "ordinal": ORDINAL_RE,
    "file_name": FILE_NAME_RE,
    "nomenclature": NOMENCLATURE_RE,
    "period_label": PERIOD_LABEL_RE,
    "hyphen_name": HYPHEN_NAME_RE,
    "labelled_id": LABELLED_ID_RE,
    "alnum_id": ALNUM_ID_RE,
    "technical": TECHNICAL_RE,
}
# Ce que le registre et l'index déclaré masquent : tout sauf les repères de période.
WITHOUT_PERIODS = ("sec_form", "ordinal", "file_name", "nomenclature", "hyphen_name", "labelled_id", "alnum_id", "technical")
ALL = tuple(CATEGORIES)


def non_quantity_spans(text: str, kinds=WITHOUT_PERIODS) -> list[tuple[int, int, str]]:
    """Positions (dans le texte d'origine) de ce qui n'est pas une quantité, avec la catégorie."""
    t = str(text or "")
    spans: list[tuple[int, int, str]] = []
    for k in kinds:
        spans += [(m.start(), m.end(), k) for m in CATEGORIES[k].finditer(t)]
    return sorted(spans)


def mask_non_quantities(text: str, kinds=WITHOUT_PERIODS) -> str:
    """Même longueur, mêmes positions : les non-quantités sont remplacées par des espaces.
    À n'utiliser que pour décider si un nombre est une quantité — jamais comme texte à classer."""
    t = str(text or "")
    chars = list(t)
    for s, e, _ in non_quantity_spans(t, kinds):
        chars[s:e] = " " * (e - s)
    return "".join(chars)


def within_non_quantity(text: str, start: int, kinds=WITHOUT_PERIODS) -> bool:
    return any(s <= start < e for s, e, _ in non_quantity_spans(text, kinds))
