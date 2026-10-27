"""9.4.65 — maintenir le poste éveillé pendant un run (recette du 15/10/2026).

Le dirigeant lance un run de 45 minutes et part en réunion : la mise en veille du PC coupait la connexion du navigateur ;
au-delà de la durée de vie d'une session déconnectée, Streamlit détruisait la session, le run en cours et ses résultats,
et l'application revenait à l'écran d'accueil. Pendant un run, CoDIR IA demande au système de ne pas se mettre en veille
(l'écran peut s'éteindre). Rien n'est modifié dans les réglages du poste ; la demande cesse à la fin du run.
"""
from __future__ import annotations

import os
import subprocess
import sys

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_caffeinate = None


def start() -> bool:
    """Demande au système de rester éveillé ; vrai si la demande a été posée."""
    global _caffeinate
    try:
        if os.name == "nt":
            import ctypes
            return bool(ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED))
        if sys.platform == "darwin" and _caffeinate is None:
            _caffeinate = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    except Exception:
        return False
    return False


def stop() -> None:
    """Rend la main au système (fin du run, réussi ou non)."""
    global _caffeinate
    try:
        if os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
        elif _caffeinate is not None:
            _caffeinate.terminate()
            _caffeinate = None
    except Exception:
        pass
