"""patches/history_hygiene.py — M.5.10.10 — Hygiène de l'historique multi-séances.

Audit dossier anglophone coté (réel) : l'historique multi-séances réinjectait dans un dossier
d'analyse d'entreprise (dossier anglophone coté Group plc) de vieilles actions « solo /
consultant » d'une autre nature de session (publication LinkedIn hebdo, cabinets
de transition, newsletter de prospection, TJM, pipeline solo). Ces actions ne
sont JAMAIS des actions d'analyse d'une société cliente : ce sont des artefacts
du business development de l'opérateur, qui ont fui dans le dossier.

Deux leviers (doctrine audit Action 2) :
  - `ignore_history_enabled()` : mode « run propre sans historique » (test/clean).
  - `purge_solo_marketing()` : sort les actions solo-marketing du flux actif vers
    une quarantaine « legacy / not carried forward », sans toucher le journal
    append-only (on ne nettoie que la vue rendue).
"""
from __future__ import annotations

import os
import re
from typing import Optional

# Actions intrinsèquement « solo / business development de l'opérateur » : elles
# n'ont pas leur place dans l'analyse d'une société cliente et ne doivent jamais
# être reportées (carry-forward) ni ressortir comme axe/next step.
_SOLO_MARKETING_RE = re.compile(
    r"(?:publication|post(?:er|s)?|présence|campagne)\s+(?:hebdo\w*\s+)?linkedin"
    r"|linkedin\s+(?:weekly|hebdo)"
    r"|cabinets?\s+de\s+(?:transition|placement|recrutement)"
    r"|newsletter\s+(?:de\s+)?(?:prospection|mensuelle)"
    r"|newsletter\s+mensuelle"
    r"|\bTJM\b|taux\s+journalier"
    r"|pipeline\s+(?:solo|commercial\s+perso|de\s+prospection)"
    r"|ciblage\s+(?:prioritaire\s+)?des\s+cabinets",
    re.IGNORECASE,
)

_ACTION_KEYS = ("action", "sujet", "decision", "next_step", "echeance", "libelle", "titre")


def ignore_history_enabled(flag: Optional[bool] = None) -> bool:
    """True si le run doit IGNORER l'historique CoDIR précédent.

    Priorité : argument explicite `flag` > variable d'environnement
    `CODIR_IGNORE_HISTORY` (1/true/yes/on). Permet un « run propre sans
    historique » pour les tests de clôture, sans dépendre de l'UI.
    """
    if flag is not None:
        return bool(flag)
    val = (os.environ.get("CODIR_IGNORE_HISTORY") or "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _action_text(a) -> str:
    if isinstance(a, dict):
        return " ".join(str(a.get(k, "")) for k in _ACTION_KEYS)
    return str(a or "")


def is_solo_marketing(action) -> bool:
    """L'action relève-t-elle du business development solo de l'opérateur
    (LinkedIn hebdo, cabinets de transition, newsletter de prospection, TJM…) ?"""
    return bool(_SOLO_MARKETING_RE.search(_action_text(action)))


def purge_solo_marketing(history: dict) -> int:
    """Sort les actions solo-marketing du flux actif de `history` (open_actions /
    carried_in / reapparues) vers `history['quarantined_legacy']`. Renvoie le
    nombre d'actions mises en quarantaine. Ne touche pas le journal source.
    """
    if not isinstance(history, dict):
        return 0
    quarantined = []
    for key in ("carried_in", "open_actions", "reapparues"):
        lst = history.get(key)
        if not isinstance(lst, list):
            continue
        kept = []
        for a in lst:
            if is_solo_marketing(a):
                if isinstance(a, dict):
                    a["quarantine_reason"] = (
                        "action solo / business development de l'opérateur "
                        "(LinkedIn/cabinets/newsletter/TJM) — incompatible avec "
                        "l'analyse d'une société cliente ; non reportée")
                    a["statut"] = "Legacy (non reportée)"
                quarantined.append(a)
            else:
                kept.append(a)
        history[key] = kept
    if quarantined:
        history.setdefault("quarantined_legacy", []).extend(quarantined)
    return len(quarantined)


def apply(history: Optional[dict], ignore: Optional[bool] = None) -> Optional[dict]:
    """Applique l'hygiène : renvoie None si l'historique doit être ignoré, sinon
    `history` après purge des actions solo-marketing."""
    if ignore_history_enabled(ignore):
        return None
    if history:
        purge_solo_marketing(history)
    return history
