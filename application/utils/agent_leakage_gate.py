"""Gate anti-fuite du dialogue interne des agents.

Le gate vise des formulations conversationnelles d'orchestration à haute
précision (demande de reformulation, commentaire sur le prompt, promesse de
livrer un bloc JSON, etc.). Il ne censure jamais les termes techniques isolés
``prompt``, ``JSON`` ou ``markdown`` : ils peuvent faire partie du dossier
utilisateur (produit IA, API, cybersécurité, documentation).

Doctrine :
- assainir uniquement les SORTIES agents au point de convergence ;
- préserver intégralement le brief utilisateur ;
- retirer la phrase fautive, jamais le paragraphe métier qui l'entoure ;
- rester idempotent et fail-open.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Tuple

# Motifs reproduisant les fuites terrain dossier de conseil et variantes proches.
# Aucun mot technique isolé n'est interdit.
_PATTERNS = [
    r"\b(?:le|ce)\s+prompt\s+(?:fourni|reçu|initial)\s+(?:m[ée]lange|contient|comporte|impose)\b",
    r"\b(?:les?|plusieurs?)\s+consignes?\s+(?:sont\s+)?contradictoires?\b",
    r"\bd[ée]taille\s+(?:ta|votre)\s+demande\b",
    r"\breformule[rz]?\s+(?:ta|votre)\s+demande\b",
    r"\bje\s+peux\s+maintenant\s+(?:te|vous)\s+(?:livrer|fournir|g[ée]n[ée]rer)\b",
    r"\bsi\s+(?:tu|vous)\s+(?:veux|voulez)\s*,?\s*je\s+peux\b",
    r"\b(?:le|un)\s+bloc\s+json\s+final\b",
    r"\b(?:la|une)\s+r[ée]ponse\s+markdown\s+(?:de|sous|au)\b",
    r"\bformat\s+impos[ée]\s+(?:par|dans)\s+(?:le|la|les)\s+(?:prompt|consigne|instruction)\b",
    r"\ben\s+tant\s+qu['’e]\s+(?:ia|assistant)\s*,?\s+je\s+(?:ne\s+peux|peux)\b",
    # EN — mêmes fuites possibles dans un run anglophone.
    r"\bthe\s+(?:provided|initial)\s+prompt\s+(?:mixes|contains|includes|imposes)\b",
    r"\b(?:the|several)\s+instructions?\s+(?:are\s+)?contradictory\b",
    r"\bplease\s+(?:clarify|rephrase)\s+your\s+request\b",
    r"\bi\s+can\s+now\s+(?:deliver|provide|generate)\b",
    r"\bif\s+you\s+want\s*,?\s*i\s+can\b",
    r"\b(?:the|a)\s+final\s+json\s+block\b",
]
_RX = re.compile("|".join(_PATTERNS), re.IGNORECASE)
_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def strip_agent_leakage(text: str) -> Tuple[str, int]:
    """Retourne ``(texte_nettoyé, nb_phrases_retirées)``.

    Le découpage est volontairement conservateur : une ligne contenant une
    fuite est séparée en phrases ; seules celles qui portent un motif précis
    sont retirées. En cas d'erreur, le texte original est rendu intact.
    """
    try:
        if not text or not _RX.search(str(text)):
            return text, 0
        removed = 0
        out_lines = []
        for line in str(text).split("\n"):
            if not _RX.search(line):
                out_lines.append(line)
                continue
            sentences = [s for s in _SENT_SPLIT.split(line) if s]
            clean = [s for s in sentences if not _RX.search(s)]
            removed += len(sentences) - len(clean)
            if clean:
                out_lines.append(" ".join(clean))
        return "\n".join(out_lines), removed
    except Exception:
        return text, 0


def sanitize_agent_outputs(outputs: Mapping[str, Any] | None) -> Tuple[dict, dict]:
    """Assainit récursivement une copie des sorties agents.

    Cette fonction ne doit recevoir que ``result['outputs']`` (ou équivalent),
    jamais ``result['inputs']['brief']``. Les valeurs non textuelles sont
    conservées. Le rapport permet d'alimenter les diagnostics sans exposer le
    contenu retiré.
    """
    report = {"sentences_removed": 0, "fields_touched": 0}

    def _walk(value: Any) -> Any:
        if isinstance(value, str):
            clean, count = strip_agent_leakage(value)
            if count:
                report["sentences_removed"] += count
                report["fields_touched"] += 1
            return clean
        if isinstance(value, dict):
            return {k: _walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_walk(v) for v in value]
        if isinstance(value, tuple):
            return tuple(_walk(v) for v in value)
        return value

    try:
        return _walk(dict(outputs or {})), report
    except Exception:
        return dict(outputs or {}), report


__all__ = ["strip_agent_leakage", "sanitize_agent_outputs"]
