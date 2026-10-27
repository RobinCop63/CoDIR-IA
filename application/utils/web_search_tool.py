"""
CoDIR-IA — utils/web_search_tool.py (v16.5.76 Phase 5 — correctif audit ChatGPT R5)

Module de réexport propre des API publiques du connecteur web search.

POURQUOI CE MODULE EXISTE
=========================

L'audit ChatGPT R5 du 15 mai 2026 a soulevé un écart d'architecture :
le document Word de phasage prévoyait `utils/web_search_tool.py`, mais
l'implémentation Phase 3 a livré `patches/web_search.py`.

Décision : conserver l'implémentation dans `patches/` (cohérent avec
les autres modules patches : sector_detector, briefcheck, confidence_scorer,
agent_output_schema), MAIS ajouter ce module de réexport dans `utils/`
pour aligner avec la documentation et offrir un point d'entrée stable
pour les usages externes.

Tout nouveau code peut importer depuis l'un ou l'autre :

    # Import direct (équivalent)
    from patches.web_search import run_competitor_scan
    from utils.web_search_tool import run_competitor_scan

Le module patches/ reste la source de vérité. Ce module utils/ est
strictement un alias.

CONTRAT
=======

Toute API publique de `patches.web_search` (i.e. listée dans son
`__all__`) DOIT être réexportée ici. Un test dédié vérifie l'égalité
des deux `__all__` pour éviter une dérive silencieuse.
"""

from __future__ import annotations

from patches.web_search import (
    CompetitorScanResult,
    is_web_search_available,
    run_competitor_scan,
    format_web_search_for_agent_context,
)

__all__ = [
    "CompetitorScanResult",
    "is_web_search_available",
    "run_competitor_scan",
    "format_web_search_for_agent_context",
]
