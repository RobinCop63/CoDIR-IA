"""v17.1.0-B2.3-F.4.2 — Hygiène des sorties agents (scrubs doctrine-safe).

Trois nettoyages post-génération constatés sur les reruns réels F.4.1 :

1. scrub_retail_artifacts — des métaphores RETAIL prototypées fuitent dans des
   dossiers non-retail (« SKU iconiques vs liquidation rapide », « DTC vs
   wholesale », « transposable ici en sites vitrines vs sites rentables »). Ce
   sont des fuites de gabarit, jamais une analyse valable → on les retire.

2. scrub_marketing_contamination — sur un dossier M&A, le périmètre SOCIAL
   standalone Pappers (« SASU, services intellectuels, CA 45 k€ social
   standalone ») contamine le narratif marketing alors qu'un CA CONSOLIDÉ existe.
   On retire ce cadrage trompeur.

3. gate_temporal_effectif — un statut écrit « effectif <date future> » alors que
   la date n'est pas réalisée (ex. transfert Euronext « effectif juillet 2026 »
   au 7 juin 2026) doit devenir « prévu (sous réserve) ».

Doctrine : on n'invente AUCUN fait ; on RETIRE des artefacts faux ou on REQUALIFIE
un statut temporel. Tout est fail-open (le texte d'entrée est renvoyé en cas
d'échec) et idempotent.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional, Tuple

_I = re.IGNORECASE

# ── 1. Artefacts retail prototypés ──────────────────────────────────────────
_RETAIL_ARTIFACTS = (
    re.compile(r"SKU[\s\w’']*?\s+(?:vs|versus)\s+liquidation[^.\n]*", _I),
    re.compile(r"\bDTC\b\s*(?:vs|versus|/)\s*wholesale[^.\n]*", _I),
    re.compile(r"sites?\s+vitrines?\s*(?:vs|versus)\s*sites?\s+rentables[^.\n]*", _I),
    re.compile(r"\btransposable ici en[^.\n]*", _I),
    re.compile(r"\bSKU\s+iconiques?[^.\n]*", _I),
)


def scrub_retail_artifacts(text: str) -> Tuple[str, int]:
    """Retire les métaphores retail prototypées (fuites de gabarit). Renvoie
    (texte, nb_retraits). Fail-open."""
    if not text:
        return text, 0
    n = 0
    out = text
    try:
        for rx in _RETAIL_ARTIFACTS:
            out, k = rx.subn("", out)
            n += k
        if n:
            # nettoie les «  :  » ou « ; » orphelins laissés par le retrait
            out = re.sub(r"[ \t]*[;:][ \t]*(?=\n|$)", "", out)
            out = re.sub(r"[ \t]{2,}", " ", out)
    except Exception:
        return text, 0
    return out, n


# ── 2. Contamination marketing par le périmètre social standalone (M&A) ─────
_SOCIAL_STANDALONE = (
    re.compile(r"\s*\((?:SASU|SAS|SA|SARL|EURL)[^)]*social standalone[^)]*\)", _I),
    re.compile(r"\s*\([^)]*services intellectuels[^)]*social standalone[^)]*\)", _I),
    re.compile(r"\s*\([^)]*CA\s*\d[\d.,\s]*k€[^)]*social standalone[^)]*\)", _I),
    re.compile(r"\s*[—–-]\s*(?:SASU|SAS|SA|SARL)\s+de\s+services intellectuels[^.\n]*", _I),
)


def scrub_marketing_contamination(text: str) -> Tuple[str, int]:
    """Sur un dossier M&A, retire le cadrage « SASU / services intellectuels /
    CA k€ social standalone » qui contredit le périmètre consolidé. Ne touche pas
    aux chiffres consolidés. Renvoie (texte, nb_retraits). Fail-open."""
    if not text:
        return text, 0
    n = 0
    out = text
    try:
        for rx in _SOCIAL_STANDALONE:
            out, k = rx.subn("", out)
            n += k
    except Exception:
        return text, 0
    return out, n


# ── 3. Statut temporel « effectif <date future> » ──────────────────────────
_MOIS = {
    "janv": 1, "févr": 2, "fevr": 2, "mars": 3, "avr": 4, "mai": 5, "juin": 6,
    "juil": 7, "août": 8, "aout": 8, "sept": 9, "oct": 10, "nov": 11,
    "déc": 12, "dec": 12,
}
_EFFECTIF_MONTH = re.compile(
    r"effecti(?:f|ve)\s+(" + "|".join(_MOIS) + r")\w*\.?\s+(20\d{2})", _I)
_EFFECTIF_QUARTER = re.compile(r"effecti(?:f|ve)\s+(T[1-4]|S[12])\s*(20\d{2})", _I)
_EFFECTIF_YEAR = re.compile(r"effecti(?:f|ve)\s+(20\d{2})\b", _I)
_REPLACEMENT = "prévu (sous réserve, date non encore réalisée)"


def gate_temporal_effectif(text: str, today: Optional[date] = None) -> Tuple[str, int]:
    """Requalifie « effectif <date future> » en « prévu (sous réserve) ». Une date
    déjà passée est laissée intacte. Renvoie (texte, nb_corrections). Fail-open."""
    if not text:
        return text, 0
    # Gate 12 - jugement temporel UNIQUEMENT sous autorite fournie.
    if today is None:
        return text, 0
    n = 0
    out = text
    try:
        def _month_repl(m):
            nonlocal n
            mo = _MOIS.get(m.group(1).lower()[:4]) or _MOIS.get(m.group(1).lower()[:3])
            yr = int(m.group(2))
            if mo and date(yr, mo, 1) >= date(today.year, today.month, 1):
                n += 1
                return f"{_REPLACEMENT} {m.group(1)} {m.group(2)}"
            return m.group(0)

        def _quarter_repl(m):
            nonlocal n
            yr = int(m.group(2))
            q_first_month = {"T1": 1, "T2": 4, "T3": 7, "T4": 10,
                             "S1": 1, "S2": 7}.get(m.group(1).upper(), 1)
            if date(yr, q_first_month, 1) >= date(today.year, today.month, 1):
                n += 1
                return f"{_REPLACEMENT} {m.group(1)} {m.group(2)}"
            return m.group(0)

        def _year_repl(m):
            nonlocal n
            if int(m.group(1)) >= today.year:
                n += 1
                return f"{_REPLACEMENT} {m.group(1)}"
            return m.group(0)

        out = _EFFECTIF_MONTH.sub(_month_repl, out)
        out = _EFFECTIF_QUARTER.sub(_quarter_repl, out)
        out = _EFFECTIF_YEAR.sub(_year_repl, out)
    except Exception:
        return text, 0
    return out, n


def apply_output_hygiene(text: str, role: str = "", genre: str = "",
                         today: Optional[date] = None) -> str:
    """Orchestrateur fail-open appelé depuis le post-process des rôles.
    - supply_chain : scrub artefacts retail (toujours — ce sont des fuites de gabarit) ;
    - marketing/commercial sur genre M&A : scrub contamination social standalone ;
    - tous rôles : gate temporel « effectif <future> ».
    """
    if not text:
        return text
    out = text
    try:
        if role in ("supply_chain", "commercial", "marketing", "strategie",
                    "synthese_decisions", "direction_generale", "brief_codir"):
            out, _ = scrub_retail_artifacts(out)
        if genre == "MA_DECISION" and role in ("marketing", "commercial"):
            out, _ = scrub_marketing_contamination(out)
        out, _ = gate_temporal_effectif(out, today=today)
    except Exception:
        return text
    return out


# ── M.5.10.5 — Localisation EN des tags épistémiques INLINE ───────────────────
# Les agents injectent dans leur narratif des tags de sourçage en français
# ([NON SOURCÉ], [FAIT], [ESTIM-HYPOTHÈSE], [HYPOTHÈSE], [À VÉRIFIER], [ESTIM IA],
# [REF SECT.], [ESTIM-NARRATIF]). En run EN ils fuyaient tels quels dans le CR et
# le deck (audit dossier anglophone coté : 47 occurrences ≈ l'essentiel du résidu du gate).
# Vocabulaire CONTRÔLÉ → on le localise déterministiquement APRÈS toute analyse
# de statut (transform de display uniquement). On remplace le TOKEN après le
# crochet ouvrant, en préservant le reste (« : … » ou « ] »).
_EPISTEMIC_TAG_EN = [
    (re.compile(r"\[\s*NON\s*SOURC[EÉ]", _I),                 "[UNSOURCED"),
    (re.compile(r"\[\s*ESTIM[.\-\s]*HYPOTH[EÈ]SE", _I),       "[ESTIM-ASSUMPTION"),
    (re.compile(r"\[\s*ESTIM[.\-\s]*NARRATIF", _I),           "[ESTIM-NARRATIVE"),
    (re.compile(r"\[\s*HYPOTH[EÈ]SE", _I),                    "[ASSUMPTION"),
    (re.compile(r"\[\s*ESTIM[.\s]*IA\b", _I),                 "[AI ESTIM."),
    (re.compile(r"\[\s*[AÀ]\s*V[EÉ]RIFIER", _I),              "[TO VERIFY"),
    (re.compile(r"\[\s*REF[.\s]*SECT[.\s]*\]", _I),          "[SECT. REF.]"),
    (re.compile(r"\[\s*FAIT\b", _I),                          "[FACT"),
]


def localize_epistemic_tags(text: str, lang: str) -> str:
    """Localise les tags épistémiques inline en EN (no-op en FR / hors EN)."""
    if (lang or "fr").lower() != "en" or not text:
        return text
    out = str(text)
    for rx, repl in _EPISTEMIC_TAG_EN:
        out = rx.sub(repl, out)
    # M.5.10.5 — marqueur entité + note de validation entités (entity_validator,
    # sans lang) : localisés ici au chokepoint plutôt que threadés dans la chaîne.
    out = re.sub(r"\[\s*entit[ée]\s+non\s+v[ée]rifi[ée]e?\s*\]", "[unverified entity]",
                 out, flags=_I)
    out = re.sub(
        r"Validation des entit[ée]s\s*:\s*(\d+)\s+entit[ée]s\s+hors\s+sources\s+"
        r"v[ée]rifi[ée]es\s+d[ée]tect[ée]es\s*\(liste en diagnostic\)\.\s*"
        r"Annotation inline supprim[ée]e? pour lisibilit[ée]\s*[—\-]\s*entit[ée]s\s+"
        r"[àa]\s+v[ée]rifier par le consultant avant diffusion\.",
        lambda m: (f"Entity validation: {m.group(1)} entities outside verified sources "
                   f"detected (listed in diagnostics). Inline annotation suppressed for "
                   f"readability — entities to be verified by the consultant before distribution."),
        out, flags=_I | re.S)
    return out


def localize_epistemic_tags_in_outputs(outputs: dict, lang: str) -> dict:
    """Applique localize_epistemic_tags à toutes les sorties d'agents (in place)."""
    if (lang or "fr").lower() != "en" or not isinstance(outputs, dict):
        return outputs
    for k, v in list(outputs.items()):
        if isinstance(v, str) and v:
            outputs[k] = localize_epistemic_tags(v, lang)
    return outputs
