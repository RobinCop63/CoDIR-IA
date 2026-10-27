"""
patches/streamlit_quiet.py — M.5.10.4 / hotfix M.5.10.5

Filet anti-bruit terminal. Quand le parsing PJ tourne en parallèle (threads par
défaut ; processus `spawn` sur Windows ARM), un `st.*` (souvent une fonction
décorée `@st.cache_*`) est appelé depuis un thread/process sans ScriptRunContext.
Streamlit émet alors en boucle :

    Thread 'MainThread': missing ScriptRunContext! This warning can be ignored
    when running in bare mode.

Ce warning est BÉNIN (Streamlit l'indique lui-même) et n'affecte aucun livrable.

Pourquoi un simple setLevel ne suffisait pas : le record est émis sur un logger
enfant de « streamlit », et Streamlit met le logger « streamlit » en
`propagate=False` → le record n'atteint JAMAIS le root logger. Un filtre posé sur
le root est donc inopérant. On pose donc le filtre sur le logger « streamlit »
LUI-MÊME et sur ses handlers, et on RÉ-APPLIQUE après l'init Streamlit (la fonction
est idempotente et appelée juste avant le pool de parsing).
"""
from __future__ import annotations

import logging

_SCRIPT_CTX_LOGGERS = (
    "streamlit.runtime.scriptrunner_utils.script_run_context",  # Streamlit récent
    "streamlit.runtime.scriptrunner.script_run_context",        # versions antérieures
)
_NEEDLE = "missing ScriptRunContext"
# M.5.10.9 — mêmes workers (spawn) en « bare mode » : Streamlit émet aussi ces
# deux avertissements bénins quand un st.* est touché hors `streamlit run` dans
# un sous-processus de parsing. Ils n'affectent aucun livrable (CR/deck/CSV sont
# produits par le process principal). On ne masque QUE ces messages bénins connus.
_BENIGN_NEEDLES = (
    _NEEDLE,                                       # missing ScriptRunContext
    "to view a Streamlit app on a browser",        # « use `streamlit run` » (bare mode)
    "Session state does not function",             # session_state_proxy hors streamlit run
)


class _ScriptCtxFilter(logging.Filter):
    """Jette les avertissements Streamlit bénins émis par les workers en bare mode
    (ScriptRunContext absent, bare-mode « use streamlit run », session_state hors
    runtime). On ne masque QUE ces messages connus et sans impact livrable ; tout
    autre avertissement Streamlit reste visible."""

    def filter(self, record: logging.LogRecord) -> bool:  # True = on garde
        try:
            msg = record.getMessage()
            return not any(n in msg for n in _BENIGN_NEEDLES)
        except Exception:
            return True


_FILTER = _ScriptCtxFilter()


def _attach_filter(logger: logging.Logger) -> None:
    try:
        if not any(isinstance(f, _ScriptCtxFilter) for f in logger.filters):
            logger.addFilter(_FILTER)
        for h in list(logger.handlers):
            try:
                if not any(isinstance(f, _ScriptCtxFilter) for f in h.filters):
                    h.addFilter(_FILTER)
            except Exception:
                pass
    except Exception:
        pass


def silence_script_run_context() -> None:
    """Silence le warning ScriptRunContext (idempotent, fail-open).

    1) niveau ERROR sur les loggers ScriptRunContext nommés ;
    2) filtre sur le logger « streamlit » (propagate=False) ET ses handlers ;
    3) filtre sur le root + ses handlers (au cas où la propagation est active) ;
    4) balayage du registre : tout logger « *script_run_context* » → ERROR + filtre.
    """
    # 1) niveau ERROR sur les loggers connus
    for _name in _SCRIPT_CTX_LOGGERS:
        try:
            logging.getLogger(_name).setLevel(logging.ERROR)
        except Exception:
            pass
    # 2-3) filtre sur « streamlit », ses parents, et le root (+ handlers)
    for _name in ("streamlit", "streamlit.runtime", ""):
        try:
            _attach_filter(logging.getLogger(_name))
        except Exception:
            pass
    # 4) balayage du registre des loggers déjà créés
    try:
        for _lname in list(logging.Logger.manager.loggerDict.keys()):
            if "script_run_context" in _lname:
                lg = logging.getLogger(_lname)
                lg.setLevel(logging.ERROR)
                _attach_filter(lg)
    except Exception:
        pass


# Pour l'initializer du ProcessPoolExecutor (doit être picklable au niveau module).
def worker_init() -> None:
    silence_script_run_context()


# Appliqué à l'import — utile dès le process parent et les enfants spawn.
silence_script_run_context()
