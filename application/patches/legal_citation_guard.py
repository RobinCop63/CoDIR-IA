"""
patches/legal_citation_guard.py — M.5.8 (FIX3, retex run dossier de conseil)

Garde MINIMAL de citations légales. Sur le run dossier de conseil M.5.7, le livrable
asservait des articles de loi FAUX pour une SAS avec assurance :
  - « perte de la moitié des capitaux propres → art. L. 223-42 » (article SARL ;
    pour une SAS/SASU c'est L. 225-248 via L. 227-1) ;
  - « mise en sommeil → art. L. 526-28 » (article EIRL, pas cessation temporaire) ;
  - « durée max 2 ans renouvelable, soit 4 ans » (la limite société est 2 ans).

Doctrine : « zéro latitude sur la présentation trompeuse ». CoDIR-IA n'est pas
juriste : il ne doit pas ASSERTER une référence d'article qu'il ne peut pas
sourcer officiellement. Ce garde ne SUPPRIME rien (lucidité) : il ANNOTE toute
référence d'article non accompagnée d'une source officielle (Légifrance /
Service-Public / lien) par « [réf. à valider — conseil juridique] ». La validation
reste humaine (THAOS / CAPEOS / avocat).
"""
from __future__ import annotations

import re
from typing import Tuple

# Référence d'article : L./R./D. NNNN-NN (éventuellement préfixé « art. »/« article »).
# Le motif NN-NN (au moins un groupe « -NN ») évite les faux positifs (« L2 », dates).
_ART_RE = re.compile(
    r"(?:art(?:icle)?s?\.?\s*)?\b([LRD])\.\s?(\d{2,4}(?:[-\u2011]\d+){1,3})\b"
)

# Une source OFFICIELLE à proximité (≈ fenêtre) ⇒ on ne neutralise pas.
# NB : « Code de commerce » seul n'est PAS une source officielle vérifiable
# (c'est précisément le cas L. 526-28 mal attribué) — volontairement exclu.
_SOURCE_NEAR = re.compile(
    r"(l[ée]gifrance|service[\s\-]?public|jorf|bofip|https?://)", re.IGNORECASE
)
_ALREADY = re.compile(r"valider|to be validated|à v[ée]rifier aupr[èe]s", re.IGNORECASE)

_MARKER_FR = " [réf. à valider — conseil juridique]"
_MARKER_EN = " [ref. to be validated — legal counsel]"


def neutralize_unsourced_legal_citations(text: str, lang: str = "fr") -> Tuple[str, int]:
    """Annote (sans supprimer) toute référence d'article non sourcée officiellement.
    Renvoie (texte_modifié, nb_annotations)."""
    if not text:
        return text, 0
    marker = _MARKER_EN if lang == "en" else _MARKER_FR
    out = []
    last = 0
    count = 0
    for m in _ART_RE.finditer(text):
        ctx = text[max(0, m.start() - 80): min(len(text), m.end() + 40)]
        if _SOURCE_NEAR.search(ctx):
            continue  # source officielle proche → conservé tel quel
        if _ALREADY.search(text[m.end(): m.end() + 50]):
            continue  # déjà annoté / déjà marqué à valider
        out.append(text[last:m.end()])
        out.append(marker)
        last = m.end()
        count += 1
    if not count:
        return text, 0
    out.append(text[last:])
    return "".join(out), count


# ── M.5.9 (FIX D, retex run dossier de conseil M.5.8) ───────────────────────────────
# Même sans numéro d'article, le livrable restait trop ASSERTIF sur des formalités
# juridiques (« déposer formulaire M2 + annonce légale », « provisionner 252 k€ »).
# CoDIR-IA n'est pas juriste/expert-comptable : on ANNOTE ces affirmations
# procédurales pour renvoyer la formalité/le chiffrage vers le guichet des
# formalités et CAPEOS/THAOS. (Garde sémantique COMPLET = M.6.)
_FORMALITE_RE = re.compile(
    r"(formulaire\s+M2|annonce\s+l[ée]gale|"
    r"cessation\s+temporaire\s+d['\u2019]activit[ée])",
    re.IGNORECASE,
)
_PROVISION_RE = re.compile(
    r"provisionn\w*(?:\s+\S+){0,4}?\s*"
    r"(?:\d[\d\s.,]*\s*k?\s*€|contentieux|dgfip|litige|redressement)",
    re.IGNORECASE,
)
_FORMALITE_FR = " [formalité à confirmer via le guichet des formalités / CAPEOS]"
_FORMALITE_EN = " [formality to confirm via the business-formalities portal / CAPEOS]"
_PROVISION_FR = " [montant & traitement comptable à cadrer avec CAPEOS/THAOS]"
_PROVISION_EN = " [amount & accounting treatment to scope with CAPEOS/THAOS]"


def annotate_assertive_legal_statements(text: str, lang: str = "fr") -> Tuple[str, int]:
    """Annote (une fois par type, à la 1re occurrence) les affirmations juridiques
    procédurales trop sûres. Ne réécrit ni ne supprime. Renvoie (texte, nb)."""
    if not text:
        return text, 0
    count = 0

    def _ann_first(pattern, marker, s):
        nonlocal count
        m = pattern.search(s)
        if not m:
            return s
        tail = s[m.end(): m.end() + 80]
        if ("CAPEOS" in tail or "THAOS" in tail
                or "guichet" in tail.lower() or tail[:3].lstrip().startswith("[")):
            return s  # déjà cadré
        count += 1
        return s[:m.end()] + marker + s[m.end():]

    fm = _FORMALITE_EN if lang == "en" else _FORMALITE_FR
    pm = _PROVISION_EN if lang == "en" else _PROVISION_FR
    text = _ann_first(_FORMALITE_RE, fm, text)
    text = _ann_first(_PROVISION_RE, pm, text)
    return text, count


# ── v62.13.9.2 — Social-threshold legal claim gate ────────────────────────────
# A registry headcount band must not be converted into an exact headcount, a
# legal threshold or a behavioural HR recommendation.  This gate deliberately
# avoids stating which obligations apply: applicability depends on the legal
# perimeter, the statutory headcount calculation and the device concerned.
_SOCIAL_THRESHOLD_TRIGGER_RE = re.compile(
    r"(?:\bseuil\s+critique(?:\s+de\s+gestion)?\b|"
    r"\b(?:effectif|salari[ée]s?|employees?|headcount)\b[^\n]{0,120}\b(?:seuil|threshold)\b[^\n]{0,40}\b1\s*000\b|"
    r"\b(?:seuil|threshold)\b[^\n]{0,80}\b1\s*000\b(?:[^\n]{0,50}\b(?:salari[ée]s?|employees?|headcount)\b)?|"
    r"\b1\s*000\b[^\n]{0,50}\b(?:salari[ée]s?|employees?|headcount)\b|"
    r"\b(?:ma[îi]triser|éviter|eviter|maintain|keep)\b[^\n]{0,80}\b(?:seuil|threshold)\b)",
    re.IGNORECASE,
)
_SOCIAL_THRESHOLD_CONSEQUENCE_RE = re.compile(
    r"(?:comit[ée]\s+de\s+groupe|group\s+committee|participation\s+obligatoire|mandatory\s+profit[- ]sharing|"
    r"obligations?\s+CSE|CSE\s+obligations?|obligations?\s+sociales?\s+et\s+fiscales?|"
    r"social\s+and\s+tax\s+obligations?|repr[ée]sentation\s+des\s+salari[ée]s?\s+au\s+conseil|"
    r"employee\s+representation\s+on\s+the\s+board|co[ûu]ts?\s+administratifs?|administrative\s+costs?)",
    re.IGNORECASE,
)
_SOCIAL_THRESHOLD_ACTION_RE = re.compile(
    r"(?:gel\s+des\s+embauches|hiring\s+freeze|impact[^\n]{0,40}recrutement|tout\s+recrutement|plan\s+de\s+ma[îi]trise\s+des\s+effectifs|"
    r"workforce\s+containment|plan\s+de\s+flexibilisation|workforce\s+flexibilit|"
    r"int[ée]rim|temporary\s+staff|ch[ôo]mage\s+partiel|short[- ]time\s+work|"
    r"éviter\s+(?:le\s+)?franchissement|eviter\s+(?:le\s+)?franchissement|avoid\s+crossing)",
    re.IGNORECASE,
)
# v62.13.9.4.16 — P0 ÉTANCHÉITÉ INTER-DOSSIERS (contre-audit ChatGPT du
# 03/09/2026, P0-01). Le cadrage juridique portait EN DUR « tranche registre :
# 500–999 salariés » — héritage du dossier dossier industriel (v62.13.6) — et le
# déclencheur d'action contenait « intérim ». Une SASU à 0 salarié dont les
# mots-clés SEO disaient « directeur financier interim » recevait l'effectif
# d'un autre client. Règles :
#   1. le cadrage se construit depuis le PROFIL RÉEL (headcount,
#      headcount_range), jamais depuis une constante ; sans profil, il ne
#      cite aucun effectif ;
#   2. une action RH ou une conséquence sociale ne sont neutralisées QUE
#      dans le contexte d'un seuil non prouvé détecté sur les lignes
#      précédentes — « intérim » seul ne déclenche jamais rien.
_SOCIAL_THRESHOLD_REVIEW_FR = "Faire qualifier ce point par la DRH ou le conseil social avant toute recommandation."
_SOCIAL_THRESHOLD_REVIEW_EN = "Have HR or employment counsel qualify this point before any recommendation."


def _headcount_from_profile(profile) -> tuple[str, str]:
    """Renvoie (valeur, source) depuis le profil réel — ("", "") sans profil."""
    if profile is None:
        return "", ""
    get = (profile.get if isinstance(profile, dict) else lambda k, d=None: getattr(profile, k, d))
    src = str(get("registry") or get("source") or "").strip()
    hc = get("headcount")
    if isinstance(hc, (int, float)) and hc >= 0:
        return str(int(hc)), src
    rng = str(get("headcount_range") or get("headcount_band") or "").strip()
    if rng:
        return rng, src
    return "", src


def social_threshold_safe_text(lang: str = "fr", profile=None) -> str:
    """Cadrage juridique prudent, construit depuis le profil — jamais d'effectif
    inventé. C'est la seule source du message de seuil."""
    en = str(lang).lower().startswith("en")
    value, src = _headcount_from_profile(profile)
    if value:
        src_txt = f" ({src})" if src else ""
        if en:
            unit = "employee" if value == "1" else "employees"
            head = f"Registry headcount: {value} {unit}{src_txt}."
        else:
            unit = "salarié" if value in ("0", "1") else "salariés"
            head = f"Effectif au registre : {value} {unit}{src_txt}."
    else:
        head = ("Exact headcount not established in the file." if en
                else "Effectif exact non établi dans le dossier.")
    tail = (" Employment-law applicability depends on the statutory headcount method "
            "and the legal perimeter specific to each regime." if en else
            " L’applicabilité des obligations sociales dépend du mode de calcul de l’effectif "
            "et du périmètre juridique propre à chaque dispositif.")
    return head + tail


def neutralize_unsupported_social_threshold_claims(text: str, lang: str = "fr",
                                                   profile=None,
                                                   context_state: dict | None = None) -> Tuple[str, list[dict]]:
    """Neutralise les conséquences juridiques/RH déduites d'un seuil non prouvé.

    Le garde travaille par lignes pour préserver la structure des livrables. Il
    remplace le déclencheur et les conséquences/recommandations qui le SUIVENT
    par un cadrage juridique prudent construit depuis le profil réel. Une
    conséquence ou une action isolée, sans seuil détecté en amont, est laissée
    intacte (v62.13.9.4.16).
    """
    if not text:
        return text, []
    safe = social_threshold_safe_text(lang, profile)
    review = _SOCIAL_THRESHOLD_REVIEW_EN if str(lang).lower().startswith("en") else _SOCIAL_THRESHOLD_REVIEW_FR
    findings: list[dict] = []
    output: list[str] = []
    safe_emitted = False
    review_emitted = False
    # ``context_state`` porte le contexte de seuil d'un appel à l'autre quand
    # le garde est appliqué paragraphe par paragraphe (réparation DOCX/PPTX) :
    # la conséquence qui suit le seuil est dans le paragraphe suivant.
    threshold_context = int((context_state or {}).get("threshold_context", 0) or 0)
    for raw in str(text).splitlines():
        line = raw.strip()
        trigger = bool(_SOCIAL_THRESHOLD_TRIGGER_RE.search(line))
        consequence = bool(_SOCIAL_THRESHOLD_CONSEQUENCE_RE.search(line))
        action = bool(_SOCIAL_THRESHOLD_ACTION_RE.search(line))
        if trigger:
            findings.append({"kind": "unsupported_social_threshold", "text": raw})
            if not safe_emitted:
                output.append(safe)
                safe_emitted = True
            if not review_emitted:
                output.append(review)
                review_emitted = True
            threshold_context = 8
            continue
        if threshold_context > 0 and (consequence or action):
            findings.append({"kind": "unsupported_social_consequence" if consequence else "unsupported_hr_action", "text": raw})
            if not safe_emitted:
                output.append(safe)
                safe_emitted = True
            if not review_emitted:
                output.append(review)
                review_emitted = True
            threshold_context = max(threshold_context - 1, 0)
            continue
        output.append(raw)
        threshold_context = max(threshold_context - 1, 0)
    if context_state is not None:
        context_state["threshold_context"] = threshold_context
    return "\n".join(output), findings
