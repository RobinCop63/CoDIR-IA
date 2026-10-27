"""
patches/listing_gate.py — v17.1-B2 (ticket B-05)

Bug observé : FDE (cotée Euronext Paris, ISIN FR0013030152) affichée « Non cotée »
dans le comparatif. La couche déterministe n'a pas de source marché ; affirmer
« non cotée » sans preuve est faux et dangereux pour une note d'investissement.

Stratégie conservatrice : une assertion de NON-cotation NON étayée par une source
marché (ISIN, Euronext, bourse, source) est rabaissée à « statut de cotation à
vérifier ». On ne prétend jamais l'inverse (on ne déclare pas « cotée ») : on
neutralise une affirmation non vérifiée.
"""
from __future__ import annotations

import re
from typing import List, Tuple

# « non cotée », « non-cotée », « non cotee », « société non cotée », « not listed »
# y compris « non cotée sur Euronext Paris » (la mention du marché ne prouve rien —
# au contraire, dire « non cotée sur Euronext » est typiquement la fausse affirmation
# à neutraliser). On capture aussi un éventuel complément « sur <marché> ».
_NON_LISTED_RE = re.compile(
    r"\bnon[\s\-]?cot[ée]{1,2}\b(?:\s+(?:en\s+bourse|sur\s+[^.,;\n]{1,40}))?"
    r"|\bnot\s+listed\b(?:\s+on\s+[^.,;\n]{1,40})?",
    re.IGNORECASE,
)

_HEDGE = "statut de cotation à vérifier (non confirmé par source marché)"


def scrub_unverified_listing_claims(text: str) -> Tuple[str, int, List[str]]:
    """v17.1-B2.1 (B2.1-02) — Neutralise TOUTE affirmation de NON-cotation.

    Une non-cotation ne peut pas être confirmée hors source marché ; l'affirmer
    est dangereux pour une note d'investissement (cas FDE, réellement cotée). On
    hedge donc systématiquement, y compris « non cotée sur Euronext Paris » : la
    mention d'un marché n'est PAS une preuve (c'est souvent l'erreur elle-même).
    Conservateur : on ne déclare jamais l'inverse, on signale « à vérifier ».
    Retourne (texte, n_corrections, échantillons)."""
    if not text:
        return text, 0, []
    samples: List[str] = []

    def _repl(m: re.Match) -> str:
        samples.append(m.group(0))
        return _HEDGE

    new_text, _ = _NON_LISTED_RE.subn(_repl, text)
    return new_text, len(samples), samples
