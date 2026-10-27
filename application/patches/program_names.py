"""patches/program_names.py — v17.4.3.5-M6B-B1.3.5 : noms de PROGRAMME bannis.

Audit terrain dossier industriel (composants) (B.1.3.4) : le brief déclare « HEVO est un PROGRAMME
interne … c'est un programme produit, PAS une entité juridique distincte »,
et pourtant `a1_probe.brief_company_name = "HEVO"` et
`run_fingerprint.chosen_entity = "HEVO"`. Le filtre lexical B.1.3
(`_plan_re` : forward/plan/programme/…) ne pouvait pas l'attraper : le mot
« programme » est dans la PHRASE de déclaration, pas dans le NOM lui-même.

Ce module PUR (zéro import projet, hermétique) extrait du brief l'ensemble
des noms EXPLICITEMENT déclarés comme programme/projet/plan « et pas une
entité juridique », pour les bannir de toute résolution d'entité :
candidat de sonde, candidats registres, chosen du fingerprint.

Prudence : on ne bannit que sur DÉCLARATION EXPLICITE (les deux signaux
dans un voisinage court), jamais sur simple proximité du mot « programme »
— « le programme HEVO » seul ne suffit pas si le brief ne nie pas
l'entité ; en revanche la négation seule (« X n'est pas une entité
juridique ») suffit.
"""
from __future__ import annotations

import re
from typing import Set

# Token capitalisé (HEVO, Athena) — les bigrammes sont reconstruits en aval.
_CAP = re.compile(r"\b(?:[A-Z][A-Za-z0-9]{2,}|[A-Z]{2,}[A-Z0-9]+)\b")

_PROG_WORD = re.compile(r"\b(?:programme|program|projet|project|plan)\b", re.IGNORECASE)

_NOT_ENTITY = re.compile(
    r"pas\s+une\s+entit[ée]\s+juridique|n['\u2019]est\s+pas\s+une\s+entit[ée]"
    r"|not\s+a\s+(?:separate\s+|distinct\s+)?legal\s+entity",
    re.IGNORECASE,
)

_STOP = {"LE", "LA", "LES", "UN", "UNE", "DES", "THE", "AND", "PAS",
         "PROGRAMME", "PROGRAM", "PROJET", "PROJECT", "PLAN", "SAS",
         "SA", "SARL", "PLC", "LTD", "GROUPE", "GROUP", "CODIR", "IA",
         "CONTEXTE", "STRATEGIQUE", "STRATÉGIQUE", "IDENTITE", "IDENTITÉ",
         "ENJEUX", "QUESTIONS", "FINANCIERS", "SUPPLY", "CHAIN"}


def _candidates(sent: str):
    """Tokens capitalisés hors STOP, bigrammes adjacents reconstitués."""
    toks = [(m.group(0), m.start()) for m in _CAP.finditer(sent)]
    out = []
    i = 0
    while i < len(toks):
        name, pos = toks[i]
        if (i + 1 < len(toks)
                and 0 < toks[i + 1][1] - (pos + len(name)) <= 2
                and toks[i + 1][0].upper() not in _STOP
                and name.upper() not in _STOP):
            out.append((f"{name} {toks[i+1][0]}", pos))
            i += 2
            continue
        if name.upper() not in _STOP:
            out.append((name, pos))
        i += 1
    return out


def extract_banned_program_names(brief: str) -> Set[str]:
    """Noms (UPPER) déclarés programme/plan-et-PAS-entité au brief.

    Brief terrain formaté ~80 colonnes : retours ligne normalisés en espaces
    AVANT le découpage en phrases. Règle : une phrase qui porte la NÉGATION
    d'entité ET un mot programme/plan/projet bannit ses candidats capitalisés
    situés à ≤60 caractères d'un de ces mots ; une négation directe bannit le
    dernier candidat des 80 caractères qui la précèdent.
    """
    if not brief:
        return set()
    flat = re.sub(r"[ \t]*\n[ \t]*", " ", brief)
    banned: Set[str] = set()
    for sent in re.split(r"(?<=[.;])", flat):
        neg = _NOT_ENTITY.search(sent)
        if not neg:
            continue
        cands = _candidates(sent)
        prog_pos = [m.start() for m in _PROG_WORD.finditer(sent)]
        for name, pos in cands:
            if any(abs(pos - p) <= 60 for p in prog_pos):
                banned.add(name.upper())
        before = [n for n, p in cands if p < neg.start() and neg.start() - p <= 80]
        if before:
            banned.add(before[-1].upper())
    return banned
