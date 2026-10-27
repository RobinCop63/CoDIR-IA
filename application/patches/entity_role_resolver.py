"""
patches/entity_role_resolver.py — v17.1-B2.3-A

ENTITY ROLE RESOLVER (priorité absolue B2.3).

Problème (run réel 06/06) : sur un brief M&A « Je suis DAF de FDE … rapprochement
avec Lhyfe », le moteur prenait FDE comme entité PRIMAIRE (premier SIREN / cité en
tête), alors que l'OBJET ANALYSÉ est Lhyfe. Conséquence en cascade : claims finance
orientés FDE social, consolidés Lhyfe absents, deck pauvre, recos contradictoires.

Doctrine (déterministe, lue dans le brief — AUCUN hardcoding d'entité) :
  - SPONSOR / acquéreur / client = l'entité que représente l'utilisateur
    (« je suis … de X », « notre groupe X », « comité de X », « covenants de X »).
  - CIBLE / objet analysé = l'entité instruite (« rapprochement avec Y »,
    « participation dans Y », « valorisation de Y », « due diligence Y »…).
  - L'entité PRIMAIRE d'analyse est la CIBLE, pas le sponsor.
  - Plus de « premier SIREN = primaire » : si l'on ne peut pas trancher,
    on le DIT (ambiguous=True) au lieu de choisir au hasard.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# Indices de RÔLE (génériques, pas de nom d'entreprise). {E} = emplacement entité.
_SPONSOR_CUES = [
    r"je\s+suis\s+(?:le\s+|la\s+|l['’])?[\w\s'’\-]{0,40}?\bde\s+(?:la\s+|l['’])?{E}",
    r"\bnotre\s+(?:groupe\s+|société\s+|entreprise\s+)?{E}",
    r"\b{E}\s+me\s+demande",
    r"comit[ée]\s+\w+\s+de\s+(?:la\s+|l['’])?{E}",
    r"covenants?\b[^.]{0,60}\bde\s+(?:la\s+|l['’])?{E}",
    r"financement\s+de\s+(?:la\s+|l['’])?{E}",
    r"pour\s+le\s+compte\s+de\s+(?:la\s+|l['’])?{E}",
    r"\bchez\s+{E}\b",
    r"\bDAF\b[^.]{0,30}\bde\s+(?:la\s+|l['’])?{E}",
    r"directeur\s+financier[^.]{0,40}\bde\s+(?:la\s+|l['’])?{E}",
]
_TARGET_CUES = [
    r"rapprochement\s+(?:potentiel\s+)?avec\s+(?:la\s+|l['’])?{E}",
    r"(?:prise\s+de\s+)?participation\s+(?:dans|en|au\s+capital\s+de)\s+(?:la\s+|l['’])?{E}",
    r"acquisition\s+de\s+(?:la\s+|l['’])?{E}",
    r"rachat\s+de\s+(?:la\s+|l['’])?{E}",
    r"valorisation\s+de\s+(?:la\s+|l['’])?{E}",
    r"due\s+diligence[^.]{0,40}{E}",
    r"\bcible\b[^.]{0,30}{E}",
    r"{E}\s*\(\s*(?:producteur|fabricant|société|éditeur|fournisseur)",
    r"analyser?\s+(?:la\s+|l['’])?{E}",
    r"instruire[^.]{0,40}{E}",
    r"fusion\s+(?:avec\s+|absorption\s+de\s+)?{E}",
]

_SIREN_RE = re.compile(r"\b(\d{9})\b")


def _is_siren(token: str) -> bool:
    return bool(re.fullmatch(r"\d{9}", (token or "").strip()))


def _name_for_siren(brief_text: str, siren: str) -> Optional[str]:
    """Nom d'entité associé à un SIREN dans le brief, ex.
    « Lhyfe (SIREN 850 415 290) » → 'Lhyfe'. On prend la dernière séquence de
    mots capitalisés située JUSTE AVANT la mention du SIREN."""
    digits = re.sub(r"\D", "", siren)
    if len(digits) != 9:
        return None
    spaced = r"\s*".join(digits[i:i+3] for i in range(0, 9, 3))
    m = re.search(r"(?:" + re.escape(digits) + r"|" + spaced + r")", brief_text)
    if not m:
        return None
    before = brief_text[max(0, m.start() - 55):m.start()]
    _NAME_STOP = {"SIREN", "RCS", "SIRET", "N", "NO", "REF", "ID"}
    names = [n for n in re.findall(
                r"[A-ZÀ-Ý][\w'’\.\-]+(?:\s+[A-ZÀ-Ý][\w'’\.\-]+)*", before)
             if n.upper().strip(".") not in _NAME_STOP]
    if names:
        return names[-1].strip(" (—-")
    return None


def _role_scores_for_name(brief_text: str, name: str) -> Tuple[int, int]:
    """(score_sponsor, score_target) pour un nom d'entité via les indices."""
    if not name:
        return (0, 0)
    e = re.escape(name)
    sp = sum(1 for pat in _SPONSOR_CUES
             if re.search(pat.replace("{E}", e), brief_text, re.IGNORECASE))
    tg = sum(1 for pat in _TARGET_CUES
             if re.search(pat.replace("{E}", e), brief_text, re.IGNORECASE))
    return (sp, tg)


def detect_roles(brief_text: str, candidates: List[str]) -> Dict[str, Any]:
    """Assigne un rôle à chaque candidat (nom OU SIREN) depuis la sémantique du
    brief. Renvoie un dict :
      roles      : {candidat: 'sponsor'|'target'|'unknown'}
      target     : candidat cible (ou None)
      sponsor    : candidat sponsor (ou None)
      ambiguous  : True si l'on ne peut pas désigner une cible unique fiable
      reasons    : explications courtes
    Aucune valeur ni entité codée en dur — tout vient du texte."""
    out = {"roles": {}, "target": None, "sponsor": None,
           "ambiguous": False, "reasons": []}
    if not brief_text or not candidates:
        out["ambiguous"] = True
        return out

    # Nom de travail pour chaque candidat (résout SIREN → nom).
    work_name: Dict[str, str] = {}
    for c in candidates:
        work_name[c] = (_name_for_siren(brief_text, c) if _is_siren(c) else c) or c

    sponsor_scores: Dict[str, int] = {}
    target_scores: Dict[str, int] = {}
    for c in candidates:
        sp, tg = _role_scores_for_name(brief_text, work_name[c])
        sponsor_scores[c], target_scores[c] = sp, tg
        if tg > sp and tg > 0:
            out["roles"][c] = "target"
        elif sp > tg and sp > 0:
            out["roles"][c] = "sponsor"
        else:
            out["roles"][c] = "unknown"

    targets = [c for c in candidates if out["roles"][c] == "target"]
    sponsors = [c for c in candidates if out["roles"][c] == "sponsor"]

    # Cible unique nette → on la prend.
    if len(targets) == 1:
        out["target"] = targets[0]
        out["reasons"].append(
            f"cible « {work_name[targets[0]]} » (signaux cible={target_scores[targets[0]]})")
    elif len(targets) > 1:
        # Plusieurs cibles → on prend la plus forte si écart net, sinon ambigu.
        targets.sort(key=lambda c: target_scores[c], reverse=True)
        if target_scores[targets[0]] > target_scores[targets[1]]:
            out["target"] = targets[0]
            out["reasons"].append(f"cible dominante « {work_name[targets[0]]} »")
        else:
            out["ambiguous"] = True
            out["reasons"].append("plusieurs cibles à signal égal — résolution non fiable")
    else:
        out["ambiguous"] = True
        out["reasons"].append("aucune cible détectée par la sémantique du brief")

    if len(sponsors) >= 1:
        sponsors.sort(key=lambda c: sponsor_scores[c], reverse=True)
        out["sponsor"] = sponsors[0]
        out["reasons"].append(f"sponsor « {work_name[sponsors[0]]} »")

    # Garde-fou : si la « cible » est aussi la mieux notée sponsor, c'est suspect.
    if out["target"] and out["target"] == out["sponsor"]:
        out["ambiguous"] = True
        out["reasons"].append("même entité notée sponsor ET cible — ambigu")
        out["target"] = None

    return out


def role_adjusted_primary(candidates: List[str], brief_text: str,
                          base_scores: Dict[str, float]) -> Tuple[Optional[str], Dict[str, Any]]:
    """Ajuste le choix du primaire d'analyse selon les rôles.

    Retourne (primary_or_None, roles_dict). Si une cible nette est identifiée,
    elle DEVIENT le primaire (override du « premier SIREN »). Si ambigu, renvoie
    None pour laisser la logique appelante décider, mais signale l'ambiguïté."""
    roles = detect_roles(brief_text, candidates)
    if roles["ambiguous"] or not roles["target"]:
        return None, roles
    # Cible nette → primaire = cible.
    return roles["target"], roles
