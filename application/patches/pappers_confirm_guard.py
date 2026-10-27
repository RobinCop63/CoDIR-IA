# -*- coding: utf-8 -*-
"""B.1.3.20 (P1-D, run dossier industriel) — garde de fraîcheur du confirmé Pappers.

Racine reproduite offline : ``pappers_confirmed_entity`` écrit au clic
« Garder <candidat> » n'était JAMAIS invalidé au changement de brief. Un
candidat de brouillon (« Actionnariat », tête du top-3 alphabétique quand
toutes les fréquences valent 1) restait collé toute la session Streamlit et
primait (score 999) sur le champ « Société : » du brief final.

Règle : le confirmé n'est valide QUE pour le brief qui l'a produit —
identifié par la clé de cache du preview (une par contenu de brief). Brief
différent → confirmé caduc, l'utilisateur re-confirme sur le brief courant.
"""
from __future__ import annotations

from typing import Optional


def confirm_is_stale(confirmed_value: str,
                     stored_sig: Optional[str],
                     current_sig: Optional[str]) -> bool:
    """True si le confirmé doit être invalidé.

    - pas de confirmé → rien à invalider (False) ;
    - confirmé sans signature (legacy / écrit avant B.1.3.20) → stale ;
    - signature ≠ clé du brief courant → stale ;
    - signature == clé courante → frais.
    """
    if not (confirmed_value or "").strip():
        return False
    if not stored_sig:
        return True
    return stored_sig != current_sig
