"""utils/json_scrub.py — v17.4.3.1-M6B-B1.3.1 : scrub PUR des blocs JSON d'agents.

Extrait de codir_engine._strip_agent_json_from_cr après l'audit du zip B.1.3
(bloquant 1, reproduit) : l'ordre des paires — JSON_START traité AVANT
AGENT_JSON_START — et l'absence de frontière gauche faisaient matcher le
sous-motif « JSON_START » AU MILIEU de « AGENT_JSON_START », supprimant le
bloc mais laissant les résidus « ---AGENT_ » / « AGENT_ » dans le CR.

Trois défenses, dans l'ordre :
  1. paires SPÉCIFIQUES avant GÉNÉRIQUES (AGENT_JSON > JSON > AUDIT) ;
  2. frontière gauche (?<![A-Za-z_]) : un tag ne matche jamais au milieu
     d'un autre tag ;
  3. scrub final des fragments orphelins (« ---AGENT_ », « AGENT_ »,
     ligne END isolée) — ceinture et bretelles.

Module PUR : zéro import projet, zéro streamlit — consommé par le moteur
(CR) ET par utils/pptx_from_cr (deck, défense en profondeur), testable
hermétiquement (audit B.1.3, point hygiène).
Le narratif hors blocs est intégralement préservé.
"""
from __future__ import annotations

import re

# ORDRE SIGNIFIANT — bloquant 1 de l'audit B.1.3 : spécifiques d'abord.
_PAIRS = (
    ("AGENT_JSON_START", "AGENT_JSON_END"),
    ("JSON_START", "JSON_END"),
    ("AUDIT_START", "AUDIT_END"),
)

# Fragments orphelins que les agents laissent parfois (tags cassés) :
# « ---AGENT_ », « AGENT_ », « ---JSON_ », ligne END isolée, etc.
_RESIDUE_LINE = re.compile(
    r"(?m)^[ \t]*-{0,3}\s?(?:AGENT_?(?:JSON_?)?|JSON_?|AUDIT_?)"
    r"(?:START|END)?\s?-{0,3}[ \t]*$"
)


_ANNOUNCE_RE = __import__("re").compile(
    r"(?mi)^[^\n]*(?:AGENT\s+JSON\s+BLOCK\s+BELOW|for\s+scoring\s+pipeline)[^\n]*\n?")


def strip_agent_json_blocks(text: str) -> str:
    """Retire TOUT bloc JSON d'agent : balisé exact, variante malformée
    (0-3 tirets de chaque côté), orphelin (START sans END → fin de texte),
    puis les fragments résiduels. Idempotent."""
    if not text:
        return text
    # B.1.3.6 — la PHRASE D'ANNONCE (« AGENT JSON BLOCK BELOW (for scoring
    # pipeline): ») écrite par l'agent avant le bloc n'était pas couverte :
    # les balises partaient, l'annonce restait dans le CR.
    text = _ANNOUNCE_RE.sub("", text)
    t = text
    for name_a, name_b in _PAIRS:
        a = r"-{0,3}\s?(?<![A-Za-z_])" + name_a + r"\s?-{0,3}"
        b = r"-{0,3}\s?(?<![A-Za-z_])" + name_b + r"\s?-{0,3}"
        t = re.sub(a + r"[\s\S]*?" + b, "", t, flags=re.IGNORECASE)
        t = re.sub(a + r"[\s\S]*$", "", t, flags=re.IGNORECASE)  # orphelin
    t = _RESIDUE_LINE.sub("", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()
