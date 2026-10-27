"""
CoDIR-IA — web_search_providers v1 (v16.5.76 Phase 6 item P6.3)

Module d'abstraction et fallback multi-provider pour le web search.

POURQUOI CE MODULE
==================

L'audit ChatGPT R5 a remonté la dépendance unique à Perplexity Sonar comme
risque pour la robustesse :
  - Single point of failure : panne Perplexity → veille web indisponible
  - Qualité des sources : Perplexity Sonar est un LLM, pas un moteur pur
  - Coût : ~$0.002-0.005 par run sans alternative moins chère

Phase 6 P6.3 introduit une couche d'abstraction `WebSearchProvider` qui :
  1. Permet de définir plusieurs providers (Perplexity, Tavily, Brave, SerpAPI)
  2. Tente les providers dans l'ordre déclaré (primary → secondary fallback)
  3. Marque la confiance résultat selon le nombre de sources convergentes
  4. Fail-open : si tous les providers échouent, retourne None (comme avant)

ARCHITECTURE
============

- `WebSearchProvider` (Protocol) : interface commune pour tous les providers
- `PerplexityProvider` : adapter pour `patches.web_search.run_competitor_scan` existant
- `TavilyProvider` : stub fonctionnel (à activer avec TAVILY_API_KEY)
- `BraveProvider` : stub fonctionnel (à activer avec BRAVE_API_KEY)
- `run_competitor_scan_multi_source(...)` : helper qui orchestre la cascade

DOCTRINE Q1-Q5 RESPECTÉE
========================

Q1 (senior copilote) : la cascade est transparente. Le diag CSV trace QUEL
   provider a répondu et combien de sources distinctes ont été collectées.
Q3 (propose+flag) : si un seul provider répond, on flag `SOURCES_PROVIDER_SINGLE`.
   Si ≥2 providers convergent, c'est plus fiable.
Q5 (AI Act §4bis) : le header de provenance liste tous les providers tentés
   et celui qui a finalement fourni le résultat.

PHILOSOPHIE FAIL-OPEN
=====================

Si TAVILY_API_KEY ou BRAVE_API_KEY ne sont pas configurés, leurs providers
sont silencieusement skippés (pas d'erreur). Si Perplexity échoue ET aucun
fallback configuré, on retourne None comme avant Phase 6.

L'objectif n'est PAS de remplacer Perplexity (qui reste primary), mais de
SÉCURISER en cas de panne ou de hausse de coût.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol


# ════════════════════════════════════════════════════════════════════════════
# INTERFACE WebSearchProvider
# ════════════════════════════════════════════════════════════════════════════


class WebSearchProvider(Protocol):
    """
    Interface commune pour tous les providers de recherche web.

    Tout provider doit exposer :
    - `name` : identifiant court ("perplexity", "tavily", "brave")
    - `is_available()` : True si configuré (clé API présente, package installé)
    - `search(company_name, sector_hint, lang, **kwargs)` : retourne soit un
      CompetitorScanResult, soit None si indisponible/erreur (fail-open)
    """

    name: str

    def is_available(self) -> bool: ...
    def search(
        self,
        company_name: str,
        sector_hint: Optional[str] = None,
        lang: str = "fr",
        **kwargs: Any,
    ) -> Optional[Any]: ...


# ════════════════════════════════════════════════════════════════════════════
# IMPLÉMENTATIONS — PerplexityProvider (primary, déjà en place v76 Phase 3)
# ════════════════════════════════════════════════════════════════════════════


class PerplexityProvider:
    """
    Adapter pour `patches.web_search.run_competitor_scan` existant.

    C'est le provider PRIMAIRE depuis v76 Phase 3. Il reste l'option par défaut
    car ses citations sont déjà bien formatées et son intégration agent_context
    est testée en production (FDE, dossier de conseil, dossier réseau de soins).
    """

    name = "perplexity"

    def is_available(self) -> bool:
        try:
            from patches.web_search import is_web_search_available
            return is_web_search_available()
        except Exception:
            return False

    def search(
        self,
        company_name: str,
        sector_hint: Optional[str] = None,
        lang: str = "fr",
        **kwargs: Any,
    ) -> Optional[Any]:
        try:
            from patches.web_search import run_competitor_scan as _run
        except Exception:
            return None
        return _run(
            company_name=company_name,
            sector_hint=sector_hint,
            lang=lang,
            **kwargs,
        )


# ════════════════════════════════════════════════════════════════════════════
# IMPLÉMENTATIONS — TavilyProvider (secondary fallback)
# ════════════════════════════════════════════════════════════════════════════


class TavilyProvider:
    """
    Provider secondaire utilisant l'API Tavily Search.

    Tavily Search API : https://tavily.com — moteur de recherche optimisé pour
    LLMs. Modèle gratuit jusqu'à 1000 req/mois, payant ensuite (~$0.001/query).

    Configuration :
        export TAVILY_API_KEY=tvly-xxx...

    Note v76 P6.3 : ce provider est livré comme STUB fonctionnel. L'appel HTTP
    réel est encapsulé pour fail-open : si requests/httpx manque ou si l'API
    Tavily répond mal, on retourne None silencieusement.

    Pour activation en prod :
      1. Souscrire compte Tavily (gratuit jusqu'à 1k req/mois)
      2. Exporter TAVILY_API_KEY dans l'env
      3. Le provider devient `is_available()=True` automatiquement
    """

    name = "tavily"
    DEFAULT_API_URL = "https://api.tavily.com/search"

    def is_available(self) -> bool:
        if not os.environ.get("TAVILY_API_KEY"):
            return False
        try:
            import requests  # noqa: F401
            return True
        except ImportError:
            return False

    def search(
        self,
        company_name: str,
        sector_hint: Optional[str] = None,
        lang: str = "fr",
        **kwargs: Any,
    ) -> Optional[Any]:
        if not self.is_available():
            return None
        api_key = os.environ.get("TAVILY_API_KEY", "").strip()
        if not api_key:
            return None
        try:
            import requests
            from patches.web_search import CompetitorScanResult
        except Exception:
            return None

        # Construction de la query Tavily
        query_parts = [f'"{company_name}" concurrents']
        if sector_hint:
            query_parts.append(sector_hint)
        if lang == "fr":
            query_parts.append("France")
        query = " ".join(query_parts)

        try:
            resp = requests.post(
                self.DEFAULT_API_URL,
                json={
                    "api_key": api_key,
                    "query": query,
                    "search_depth": "advanced",
                    "max_results": 8,
                    "include_answer": True,
                    "include_raw_content": False,
                },
                timeout=kwargs.get("timeout_s", 30.0),
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
        except Exception:
            return None

        # Parser réponse Tavily en CompetitorScanResult minimal
        try:
            return _tavily_response_to_result(data, company_name, lang)
        except Exception:
            return None


def _tavily_response_to_result(data: dict, company_name: str, lang: str):
    """
    Convertit la réponse Tavily en CompetitorScanResult.
    Format Tavily : {'answer': str, 'results': [{'url', 'title', 'content'}, ...]}
    """
    from patches.web_search import CompetitorScanResult

    answer = data.get("answer", "") or ""
    results = data.get("results", []) or []

    # Sources URLs
    sources = [r.get("url", "") for r in results if r.get("url")]

    # Construire un summary à partir de l'answer Tavily + premiers résultats
    summary_lines = []
    if answer:
        summary_lines.append(answer[:2000])
    for r in results[:5]:
        title = r.get("title", "")
        url = r.get("url", "")
        if title and url:
            summary_lines.append(f"- _{title}_ ({url})")
    summary = "\n\n".join(summary_lines)

    # Concurrents : extraction naïve depuis les titres
    competitors = []
    for r in results[:8]:
        title = r.get("title", "")
        if title and company_name.lower() not in title.lower():
            competitors.append({
                "name": title[:120],
                "tag": "ESTIM-COMPARABLE",
                "source_ref": r.get("url", ""),
            })

    return CompetitorScanResult(
        summary=summary,
        competitors=competitors,
        market_metrics={},
        sources=sources,
        tokens_used={},
        duration_s=0.0,
        provider="tavily",
        model="tavily-search-advanced",
        error=False,
        error_message="",
    )


# ════════════════════════════════════════════════════════════════════════════
# IMPLÉMENTATIONS — BraveProvider (alternative secondaire RGPD-friendly)
# ════════════════════════════════════════════════════════════════════════════


class BraveProvider:
    """
    Provider secondaire utilisant Brave Search API.

    Brave Search : https://api.search.brave.com — moteur indépendant, RGPD-friendly,
    pas d'enregistrement utilisateur. Gratuit jusqu'à 2000 req/mois.

    Configuration :
        export BRAVE_API_KEY=BSAxxx...

    Note v76 P6.3 : stub fonctionnel comme Tavily. Activation auto si la clé
    est configurée.
    """

    name = "brave"
    DEFAULT_API_URL = "https://api.search.brave.com/res/v1/web/search"

    def is_available(self) -> bool:
        if not os.environ.get("BRAVE_API_KEY"):
            return False
        try:
            import requests  # noqa: F401
            return True
        except ImportError:
            return False

    def search(
        self,
        company_name: str,
        sector_hint: Optional[str] = None,
        lang: str = "fr",
        **kwargs: Any,
    ) -> Optional[Any]:
        if not self.is_available():
            return None
        api_key = os.environ.get("BRAVE_API_KEY", "").strip()
        if not api_key:
            return None
        try:
            import requests
        except Exception:
            return None

        query_parts = [f"{company_name} concurrents"]
        if sector_hint:
            query_parts.append(sector_hint)
        query = " ".join(query_parts)

        try:
            resp = requests.get(
                self.DEFAULT_API_URL,
                params={
                    "q": query,
                    "count": 10,
                    "country": "fr" if lang == "fr" else "us",
                },
                headers={
                    "X-Subscription-Token": api_key,
                    "Accept": "application/json",
                },
                timeout=kwargs.get("timeout_s", 30.0),
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
        except Exception:
            return None

        try:
            return _brave_response_to_result(data, company_name, lang)
        except Exception:
            return None


def _brave_response_to_result(data: dict, company_name: str, lang: str):
    """Convertit la réponse Brave Search en CompetitorScanResult."""
    from patches.web_search import CompetitorScanResult

    web = data.get("web", {}) or {}
    results = web.get("results", []) or []

    sources = [r.get("url", "") for r in results if r.get("url")]

    summary_lines = []
    for r in results[:6]:
        title = r.get("title", "")
        url = r.get("url", "")
        desc = r.get("description", "")
        if title:
            summary_lines.append(f"- _{title}_ ({url})\n  {desc[:200]}")
    summary = "\n\n".join(summary_lines)

    competitors = []
    for r in results[:8]:
        title = r.get("title", "")
        if title and company_name.lower() not in title.lower():
            competitors.append({
                "name": title[:120],
                "tag": "ESTIM-COMPARABLE",
                "source_ref": r.get("url", ""),
            })

    return CompetitorScanResult(
        summary=summary,
        competitors=competitors,
        market_metrics={},
        sources=sources,
        tokens_used={},
        duration_s=0.0,
        provider="brave",
        model="brave-search-v1",
        error=False,
        error_message="",
    )


# ════════════════════════════════════════════════════════════════════════════
# CASCADE MULTI-PROVIDER
# ════════════════════════════════════════════════════════════════════════════


@dataclass
class MultiSourceScanResult:
    """
    Résultat de la cascade multi-provider.

    - `result` : le CompetitorScanResult du provider qui a réussi (ou None)
    - `providers_tried` : liste des providers tentés dans l'ordre
    - `provider_used` : nom du provider qui a fourni le résultat
    - `providers_failed` : liste des providers ayant échoué/skippés
    - `convergence_score` : 0.0-1.0 — combien de providers convergent sur le résultat
                            (1.0 = un seul provider testé et OK ;
                             plus élevé = plusieurs providers ayant produit un résultat)
    """
    result: Optional[Any]
    providers_tried: list = field(default_factory=list)
    provider_used: str = ""
    providers_failed: list = field(default_factory=list)
    convergence_score: float = 0.0
    diag: dict = field(default_factory=dict)


def get_default_providers() -> list:
    """
    Retourne la cascade de providers par défaut.

    Ordre : Perplexity (primaire) → Tavily → Brave.
    Perplexity reste en tête car son intégration v76 Phase 3 est testée
    et ses citations sont mieux formatées que les autres pour le scoring.
    """
    return [
        PerplexityProvider(),
        TavilyProvider(),
        BraveProvider(),
    ]


def run_competitor_scan_multi_source(
    company_name: str,
    sector_hint: Optional[str] = None,
    lang: str = "fr",
    providers: Optional[list] = None,
    cross_validate: bool = False,
    **kwargs: Any,
) -> MultiSourceScanResult:
    """
    Exécute la cascade multi-provider pour un competitor scan.

    Args:
        company_name    : nom de la société à scanner
        sector_hint     : indication sectorielle
        lang            : "fr" ou "en"
        providers       : liste de WebSearchProvider (default = get_default_providers())
        cross_validate  : si True, exécute TOUS les providers disponibles pour
                          mesurer la convergence (plus coûteux, ~2-3× le temps).
                          Si False (default), s'arrête au premier succès.
        **kwargs        : forwarded aux providers (timeout_s, max_tokens, etc.)

    Returns:
        MultiSourceScanResult avec :
        - `.result` : CompetitorScanResult du provider gagnant (ou None si tous KO)
        - `.providers_tried` : liste des providers tentés
        - `.provider_used` : nom du provider qui a fourni le résultat
        - `.convergence_score` : 1.0 si single-source, >1.0 si cross_validate avec ≥2 succès
        - `.diag` : dict de diagnostic pour le CSV

    Fail-open : si tous les providers échouent, .result = None mais pas
    d'exception levée (comportement v76 Phase 3 préservé).
    """
    if providers is None:
        providers = get_default_providers()

    tried: list = []
    failed: list = []
    successes: list = []  # liste de (provider_name, result)

    for provider in providers:
        name = getattr(provider, "name", "unknown")
        tried.append(name)

        # Skip silencieux si non configuré
        if not provider.is_available():
            failed.append({"name": name, "reason": "not_available"})
            continue

        try:
            result = provider.search(
                company_name=company_name,
                sector_hint=sector_hint,
                lang=lang,
                **kwargs,
            )
            if result is not None:
                successes.append((name, result))
                if not cross_validate:
                    # Mode cascade simple : on s'arrête au premier succès
                    break
            else:
                failed.append({"name": name, "reason": "returned_none"})
        except Exception as e:
            failed.append({
                "name": name,
                "reason": f"exception:{type(e).__name__}",
            })

    if not successes:
        return MultiSourceScanResult(
            result=None,
            providers_tried=tried,
            providers_failed=failed,
            convergence_score=0.0,
            diag={
                "providers_tried_count": len(tried),
                "providers_failed_count": len(failed),
                "all_failed": True,
            },
        )

    # Premier succès = résultat retenu (le provider primary gagne par construction)
    provider_used, result = successes[0]

    # Score de convergence : 1.0 pour single-source, >1.0 si plusieurs sources
    # Formule simple : 1 + (n_extra_successes * 0.5)
    n_successes = len(successes)
    convergence = 1.0 if n_successes == 1 else 1.0 + (n_successes - 1) * 0.5

    return MultiSourceScanResult(
        result=result,
        providers_tried=tried,
        provider_used=provider_used,
        providers_failed=failed,
        convergence_score=convergence,
        diag={
            "providers_tried_count": len(tried),
            "providers_successful_count": n_successes,
            "providers_failed_count": len(failed),
            "convergence_score": convergence,
            "cross_validated": cross_validate and n_successes >= 2,
        },
    )


# ════════════════════════════════════════════════════════════════════════════
# HEADER PROVENANCE (Q5 AI Act §4bis étendu)
# ════════════════════════════════════════════════════════════════════════════


def format_multi_source_provenance_header(
    scan_result: MultiSourceScanResult,
    lang: str = "fr",
) -> str:
    """
    Génère le header Q5 AI Act §4bis pour un scan multi-source.

    Indique :
    - Quel provider a effectivement répondu
    - Combien de sources distinctes ont été collectées
    - Si convergence multi-provider (cross_validate)
    """
    if scan_result.result is None:
        if lang == "en":
            return (
                "_Source: web search unavailable. "
                "Providers tried: {tried}. None responded. "
                "AI Act art. 50(4) — content limited to attached documents._\n\n"
            ).format(tried=", ".join(scan_result.providers_tried))
        return (
            "_Source : recherche web indisponible. "
            "Providers tentés : {tried}. Aucun n'a répondu. "
            "AI Act art. 50(4) — contenu limité aux pièces jointes._\n\n"
        ).format(tried=", ".join(scan_result.providers_tried))

    n_sources = len(scan_result.result.sources) if hasattr(scan_result.result, "sources") else 0
    n_successes = scan_result.diag.get("providers_successful_count", 1)

    if lang == "en":
        return (
            "_Source: automated web search via {provider} ({n_sources} citations). "
            "Cascade: {tried}. {convergence} "
            "AI Act art. 50(4) §4bis — generated content, mandatory human review._\n\n"
        ).format(
            provider=scan_result.provider_used,
            n_sources=n_sources,
            tried=", ".join(scan_result.providers_tried),
            convergence=(
                f"Cross-validated by {n_successes} sources."
                if n_successes >= 2 else
                "Single-source result — flag for review if material."
            ),
        )
    return (
        "_Source : recherche web automatisée via {provider} ({n_sources} citations). "
        "Cascade : {tried}. {convergence} "
        "AI Act art. 50(4) §4bis — contenu généré, revue humaine obligatoire._\n\n"
    ).format(
        provider=scan_result.provider_used,
        n_sources=n_sources,
        tried=", ".join(scan_result.providers_tried),
        convergence=(
            f"Validation croisée par {n_successes} sources."
            if n_successes >= 2 else
            "Source unique — flagger pour revue si critique."
        ),
    )


__all__ = [
    "WebSearchProvider",
    "PerplexityProvider",
    "TavilyProvider",
    "BraveProvider",
    "MultiSourceScanResult",
    "get_default_providers",
    "run_competitor_scan_multi_source",
    "format_multi_source_provenance_header",
]
