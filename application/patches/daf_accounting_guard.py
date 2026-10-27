"""
patches/daf_accounting_guard.py — F.6.10 (audit dossier réseau de soins F.6.9)

GARDE COMPTABLE DAF. Un agent peut écrire « Résultat consolidé groupe estimé :
<montant> (somme de résultats d’entités différentes) » — exemple synthétique : ne pas agréger des montants de périmètres ou d’entités différents sans rapprochement documenté — c'est méthodologiquement
FAUX : on ne consolide pas un groupe en additionnant des liasses sociales sans
éliminations intra-groupe. Même tagué [ESTIM-HYPOTHÈSE], le mot « consolidé »
est un piège qu'un DAF pressé pourrait reprendre.

Ce module RÉÉCRIT (déterministe, sans LLM) ces formulations en une mention
honnête : « Somme indicative des résultats sociaux (NON consolidé — sans
éliminations intra-groupe) ». Il ne supprime pas le chiffre (transparence), il
en corrige le LIBELLÉ et la portée.
"""
from __future__ import annotations

import re

# « Résultat consolidé groupe estimé », « résultat net consolidé estimé »,
# « CA consolidé estimé », « chiffre d'affaires consolidé (estimé) »… suivis (ou
# non) d'un tag épistémique, quand le contexte révèle une ADDITION de sociaux.
_PSEUDO_RN = re.compile(
    r"r[ée]sultat\s+(?:net\s+)?consolid[ée]\s+groupe\s+estim[ée]"
    r"|r[ée]sultat\s+(?:net\s+)?consolid[ée]\s+estim[ée]"
    r"|r[ée]sultat\s+consolid[ée]\s+(?:du\s+)?groupe",
    re.I,
)
_PSEUDO_CA = re.compile(
    r"(?:CA|chiffre\s+d['’]affaires)\s+consolid[ée]\s+(?:groupe\s+)?(?:estim[ée])?",
    re.I,
)
# Signature d'addition de sociaux : « (A 12,2 M€ + B 4,9 M€ - C -0,6 M€) » ou la
# présence explicite d'éliminations en hypothèse.
_ADDITION_SIG = re.compile(
    r"\([^)]*\d[^)]*[+\-][^)]*\d[^)]*\)"
    r"|[ée]liminations?\s+intra[\s-]?groupe",
    re.I,
)

_RN_REPLACEMENT = "Somme indicative des résultats sociaux (NON consolidé — sans éliminations intra-groupe)"
_CA_REPLACEMENT = "Somme indicative des CA sociaux (NON consolidé — sans éliminations intra-groupe)"


def scrub_pseudo_consolidation(text: str) -> str:
    """Réécrit les libellés de pseudo-consolidation par addition. Conserve le
    chiffre et l'éventuel tag épistémique ; ne touche qu'au libellé trompeur.
    N'agit QUE si une signature d'addition/élimination est présente dans la même
    phrase (évite de réécrire un vrai « résultat consolidé » sourcé)."""
    if not text or not isinstance(text, str):
        return text

    def _guard(line: str) -> str:
        if not _ADDITION_SIG.search(line):
            return line  # pas de signature d'addition → vrai consolidé possible, on ne touche pas
        line = _PSEUDO_RN.sub(_RN_REPLACEMENT, line)
        line = _PSEUDO_CA.sub(_CA_REPLACEMENT, line)
        return line

    # On raisonne par phrase/ligne pour que la signature d'addition soit locale.
    return "\n".join(_guard(ln) for ln in text.split("\n"))
