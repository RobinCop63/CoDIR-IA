"""
CoDIR-IA — web_search v1 (v16.5.76 Phase 3 item 2)

Module de scan concurrentiel et marché via Perplexity Sonar (LLM + web search natif).

POURQUOI CE MODULE
==================

Le run FDE FRAMED du 15 mai 2026 (run #2) a révélé que les concurrents
pure-players français H₂/biogaz (Lhyfe, Waga Energy, HDF Energy, McPhy,
Climeworks) sont ABSENTS de l'analyse stratégique — alors qu'ils sont
des concurrents directs majeurs de La Française de l'Énergie.

Cause racine : les agents (stratégie, marketing, commercial) raisonnent
sur les PJ + leur training data. Sans connecteur web, ils ne savent rien
des concurrents récents, des annonces de levées de fonds, des fusions/
acquisitions, des nouveaux entrants sectoriels.

Conséquences observées :
  - LOW_SOURCED_FACT_RATIO (peu de FAITS sourcés, beaucoup d'ESTIM-HYPOTHÈSE)
  - Concurrent gap : on cite Air Liquide et Engie (training data), pas
    les pure-players levés en 2023-2025
  - INC-02 dans RISK_MANAGEMENT.md (« Absence de connecteur web search »)

CE QUE FAIT CE MODULE
=====================

`run_competitor_scan(company_name, sector_hint, lang, settings, ...)` :

  1. Vérifie que Perplexity est disponible (clé API + provider chargé)
     → si non, retourne None gracieusement, le run continue sans web search.

  2. Construit un prompt structuré qui demande à Perplexity Sonar :
     - Top 5-10 concurrents directs avec brève description (1 ligne chacun)
     - Métriques clés du secteur (taille du marché FR, croissance, tendances)
     - Annonces récentes pertinentes (levées de fonds, M&A, réglementations)
     - Sources web citées (Perplexity les retourne nativement dans l'output)

  3. Parse la réponse en sections structurées et tag chaque fait selon
     Q2 doctrine :
       - FAIT : citation directe avec source web identifiée
       - ESTIM-FILINGS : information de filing/comptes annuels
       - ESTIM-COMPARABLE : benchmark sectoriel sourcé
       - ESTIM-HYPOTHÈSE : déduction LLM sans source explicite

  4. Retourne un dict avec :
     - `summary` : synthèse markdown injectable dans le pappers_context
     - `competitors` : liste structurée (pour audit)
     - `market_metrics` : dict des métriques clés
     - `sources` : URLs citées par Perplexity
     - `diag` : entrée de diagnostic CSV
     - `error` : message d'erreur si échec

DOCTRINE Q2-Q5 RESPECTÉE
========================

  Q1 (senior copilote) : le module annonce ses sources et limites, ne tranche pas
  Q2 (4-tier facts)    : chaque fait est tagué FAIT/ESTIM-FILINGS/COMPARABLE/HYPOTHÈSE
  Q3 (propose+flag)    : les concurrents sont proposés "À VÉRIFIER" si confiance modérée
  Q5 (AI Act §4bis)    : l'output mentionne explicitement « source web automatisée »

FALLBACK GRACIEUX
=================

Si Perplexity absent (pas de clé, panne API) → `None` retourné, le run
continue normalement. Aucun appel à ce module ne doit casser l'engine.

INTÉGRATION DANS run_codir_session
===================================

L'appel est fait AVANT les agents stratégie/marketing/commercial, et le
résultat est intégré au `pappers_context` (sous-section "Veille web") ainsi
qu'à la Couche 1 (facts_table) comme bloc dédié _external_ctx.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ════════════════════════════════════════════════════════════════════════════
# TYPES
# ════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CompetitorScanResult:
    """Résultat structuré d'un scan concurrentiel via Perplexity.

    Champs :
    - summary : synthèse markdown prête à être injectée dans le contexte agents
    - competitors : liste de dicts {name, description, evidence_tag, source_hint}
    - market_metrics : dict des métriques sectorielles ({market_size, growth_pct, ...})
    - sources : liste des URLs citées par Perplexity (peut être vide selon le modèle)
    - tokens_used : compteur de tokens consommés (audit coût)
    - duration_s : durée de l'appel
    - provider : "perplexity" en général
    - model : "sonar-pro" en général
    - error : bool indiquant un échec
    - error_message : message d'erreur si error=True
    """
    summary: str = ""
    competitors: list[dict] = field(default_factory=list)
    market_metrics: dict = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    tokens_used: dict = field(default_factory=dict)
    duration_s: float = 0.0
    provider: str = ""
    model: str = ""
    error: bool = False
    error_message: str = ""

    def to_dict(self) -> dict:
        return {
            "summary":         self.summary,
            "competitors":     list(self.competitors),
            "market_metrics":  dict(self.market_metrics),
            "sources":         list(self.sources),
            "tokens_used":     dict(self.tokens_used),
            "duration_s":      self.duration_s,
            "provider":        self.provider,
            "model":           self.model,
            "error":           self.error,
            "error_message":   self.error_message,
        }


# ════════════════════════════════════════════════════════════════════════════
# DISPONIBILITÉ DU CONNECTEUR
# ════════════════════════════════════════════════════════════════════════════

def is_web_search_available() -> bool:
    """
    Vérifie si le connecteur web search (Perplexity) est disponible.

    Conditions :
    - PERPLEXITY_API_KEY présente dans l'environnement
    - providers.perplexity_provider importable
    """
    if not os.getenv("PERPLEXITY_API_KEY", "").strip():
        return False
    try:
        from providers.perplexity_provider import call_perplexity  # noqa: F401
        return True
    except ImportError:
        return False


# ════════════════════════════════════════════════════════════════════════════
# CONSTRUCTION DES PROMPTS
# ════════════════════════════════════════════════════════════════════════════

# Le system prompt cadre la demande pour Perplexity Sonar : recherche concurrents
# sectoriels avec sources, format structuré, doctrine CoDIR-IA.

_SYSTEM_PROMPT_FR = """Tu es un analyste sectoriel senior pour un comité de direction (CODIR).

Mission : produire une cartographie concurrentielle et un état du marché à partir d'informations publiques récentes (web, presse économique, communiqués officiels, filings).

Contraintes strictes :
1. SOURCES OBLIGATOIRES : chaque fait significatif doit être suivi d'une mention de source (nom du média, URL si possible). Si pas de source identifiable, marquer "[NON-SOURCÉ]".
2. RÉCENCE : privilégier les informations 2024-2026. Marquer "[ANCIEN]" pour les données antérieures à 2023.
3. NEUTRALITÉ : pas de jugement de valeur, juste des faits et chiffres.
4. PÉRIMÈTRE GÉOGRAPHIQUE : France + Europe en priorité. Mentionner USA/Asie si dominant.
5. ABSENCE D'INFORMATION : si tu ne trouves pas, dis "Aucune information publique récente trouvée sur ce point" plutôt que d'inventer.

Format de sortie obligatoire en markdown :

## Top concurrents directs
(5 à 10 entrées, format : « **Nom** — description en 1 ligne — _source/date_ »)

## Métriques de marché
(taille du marché FR/EU, croissance %, segments clés — chiffres sourcés)

## Annonces récentes pertinentes
(2024-2026, format : « **YYYY-MM** — fait — _source_ »)

## Sources principales utilisées
(liste à puces des URLs/médias)
"""

_SYSTEM_PROMPT_EN = """You are a senior sector analyst for a board of directors.

Mission: produce a competitive mapping and market overview from recent public information (web, business press, official press releases, filings).

Strict constraints:
1. SOURCES REQUIRED: every significant fact must be followed by source mention (media name, URL if possible). If no identifiable source, mark "[UNSOURCED]".
2. RECENCY: prioritise 2024-2026 information. Mark "[OLD]" for data prior to 2023.
3. NEUTRALITY: no value judgements, only facts and figures.
4. GEOGRAPHIC SCOPE: France + Europe priority. Mention USA/Asia if dominant.
5. NO INFORMATION: if you can't find it, say "No recent public information found on this point" rather than inventing.

Mandatory output format in markdown:

## Top direct competitors
(5 to 10 entries, format: "**Name** — description in 1 line — _source/date_")

## Market metrics
(FR/EU market size, growth %, key segments — sourced figures)

## Recent relevant announcements
(2024-2026, format: "**YYYY-MM** — fact — _source_")

## Main sources used
(bullet list of URLs/media)
"""


def _build_user_prompt(
    company_name: str,
    sector_hint: Optional[str],
    lang: str,
    additional_context: str = "",
) -> str:
    """Construit le prompt utilisateur pour Perplexity."""
    if lang == "en":
        parts = [
            f"Subject company: {company_name}",
        ]
        if sector_hint:
            parts.append(f"Detected sector hint: {sector_hint}")
        if additional_context:
            parts.append(f"Additional context:\n{additional_context}")
        parts.append(
            "Produce the structured competitive mapping for this company. "
            "Focus on companies that COMPETE DIRECTLY (same business, same target customers, same geographic markets). "
            "Avoid generic players if their main activity is elsewhere."
        )
    else:
        parts = [
            f"Société analysée : {company_name}",
        ]
        if sector_hint:
            parts.append(f"Indice sectoriel détecté : {sector_hint}")
        if additional_context:
            parts.append(f"Contexte additionnel :\n{additional_context}")
        parts.append(
            "Produis la cartographie concurrentielle structurée pour cette société. "
            "Focalise sur les acteurs qui CONCURRENCENT DIRECTEMENT (même métier, mêmes clients cibles, mêmes marchés géographiques). "
            "Évite les acteurs génériques si leur activité principale est ailleurs."
        )
    return "\n\n".join(parts)


# ════════════════════════════════════════════════════════════════════════════
# PARSING DE LA RÉPONSE
# ════════════════════════════════════════════════════════════════════════════

# Extrait les URLs présentes dans le texte (Perplexity les inclut souvent
# sous forme Markdown [texte](url) ou nues https://...)
_URL_RE = re.compile(r"https?://[^\s)\]]+", re.IGNORECASE)

# Détecte une ligne de concurrent au format markdown :
# « * **Nom** — description — _source_ »
# Tolérant à : -, *, •, à la présence ou non de _italiques_ pour la source
_COMPETITOR_LINE_RE = re.compile(
    r"^[\s]*[-*•]?\s*\*\*([^*]+?)\*\*\s*[—–\-:]\s*(.+?)(?:\s*[—–\-]\s*_([^_]+)_)?\s*$",
    re.MULTILINE,
)


def _extract_sources(text: str) -> list[str]:
    """Extrait toutes les URLs citées dans le texte."""
    urls = _URL_RE.findall(text or "")
    # Déduplication en préservant l'ordre
    seen = set()
    out = []
    for u in urls:
        u_clean = u.rstrip(".,;:!?")
        if u_clean not in seen:
            seen.add(u_clean)
            out.append(u_clean)
    return out


def _extract_section(text: str, header_pattern: str) -> str:
    """
    Extrait le contenu d'une section markdown (entre 2 headers ## ou ## et fin).

    header_pattern est une regex (insensible casse) qui matche le titre, ex : r"top concurrents".
    """
    if not text:
        return ""
    # Cherche le header puis tout jusqu'au prochain header de même niveau
    pattern = rf"^##\s+[^\n]*{header_pattern}[^\n]*\n(.*?)(?=^##\s|\Z)"
    m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    return m.group(1).strip() if m else ""


def _parse_competitors(section_text: str) -> list[dict]:
    """
    Parse la section "Top concurrents directs" en liste structurée.

    Format attendu (souple) : « **Nom** — description — _source_ »
    """
    if not section_text:
        return []
    out = []
    for m in _COMPETITOR_LINE_RE.finditer(section_text):
        name = m.group(1).strip()
        desc = m.group(2).strip()
        source = (m.group(3) or "").strip()
        # Détermine le tag Q2 selon présence de source
        if source and source.upper() not in ("[NON-SOURCÉ]", "[UNSOURCED]", "[ANCIEN]", "[OLD]"):
            evidence_tag = "ESTIM-COMPARABLE"  # sourcé externe = comparable
        else:
            evidence_tag = "ESTIM-HYPOTHÈSE"   # non-sourcé = hypothèse LLM
        out.append({
            "name": name,
            "description": desc[:200],  # garde court pour l'audit
            "source_hint": source,
            "evidence_tag": evidence_tag,
        })
        if len(out) >= 15:
            break
    return out


def _parse_market_metrics(section_text: str) -> dict:
    """
    Parse la section "Métriques de marché" en dict.

    Extraction heuristique : nombres + unités courantes (€/M€/Md€/%/Md/Bn).
    """
    if not section_text:
        return {}
    metrics = {}
    # Taille marché : "X Md€" ou "X M€" ou "X milliards d'euros"
    m = re.search(r"(\d+[\d,. ]*)\s*(M[€$]?|Md[€$]?|milliard[s]?|million[s]?\s+d['']euros?|bn|billion)", section_text, re.IGNORECASE)
    if m:
        metrics["market_size_raw"] = m.group(0).strip()
    # Croissance : "X%" ou "+X%"
    m = re.search(r"([+\-]?\d+[\d,.]*)\s*%\s*(?:de\s+croissance|growth|annuel|annuelle|CAGR|TCAM)?", section_text, re.IGNORECASE)
    if m:
        metrics["growth_pct_raw"] = m.group(0).strip()
    # Période / horizon
    m = re.search(r"(20\d{2}[-–]20\d{2}|20\d{2})", section_text)
    if m:
        metrics["reference_period"] = m.group(0).strip()
    return metrics


# ════════════════════════════════════════════════════════════════════════════
# API PUBLIQUE — APPEL PERPLEXITY
# ════════════════════════════════════════════════════════════════════════════

def run_competitor_scan(
    company_name: str,
    sector_hint: Optional[str] = None,
    lang: str = "fr",
    additional_context: str = "",
    timeout_s: float = 30.0,
    max_tokens: int = 1500,
    temperature: float = 0.2,
    perplexity_call_fn: Optional[Callable] = None,
) -> Optional[CompetitorScanResult]:
    """
    Lance un scan concurrentiel pour `company_name` via Perplexity Sonar.

    Args:
        company_name : nom de l'entreprise (obligatoire, non vide)
        sector_hint : hint sectoriel (ex. "distribution_sante" de sector_detector_v1)
        lang : "fr" ou "en" (langue du prompt et de la réponse attendue)
        additional_context : contexte additionnel à inclure dans le prompt
        timeout_s : timeout pour l'appel Perplexity (note : géré par le provider)
        max_tokens : budget tokens de sortie
        temperature : faible (0.2) pour favoriser des faits sourcés, pas de créativité
        perplexity_call_fn : injection de dépendance pour les tests (mock).
                              Si None, charge providers.perplexity_provider.call_perplexity

    Returns:
        CompetitorScanResult avec summary, competitors, sources, etc.
        OU None si :
          - company_name vide
          - Perplexity indisponible (pas de clé API) → fallback gracieux

    Cette fonction est sûre à appeler : aucune exception n'est propagée
    (en cas d'erreur, retourne un CompetitorScanResult(error=True)).
    """
    # Garde-fou : nom de société requis
    if not company_name or not company_name.strip():
        return None

    # Charge la fonction d'appel (production ou mock test)
    if perplexity_call_fn is None:
        if not is_web_search_available():
            return None  # Fallback gracieux silencieux
        from providers.perplexity_provider import call_perplexity as perplexity_call_fn

    # Construit prompts
    lang = lang if lang in ("fr", "en") else "fr"
    system = _SYSTEM_PROMPT_FR if lang == "fr" else _SYSTEM_PROMPT_EN
    user_prompt = _build_user_prompt(company_name, sector_hint, lang, additional_context)

    # Appel Perplexity (with safety net)
    t0 = time.time()
    try:
        result = perplexity_call_fn(
            prompt=user_prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as e:
        return CompetitorScanResult(
            error=True,
            error_message=f"Exception lors de l'appel Perplexity : {type(e).__name__}: {str(e)[:200]}",
            duration_s=round(time.time() - t0, 3),
        )

    # Vérif erreur retournée par le provider
    if not isinstance(result, dict) or result.get("error"):
        return CompetitorScanResult(
            error=True,
            error_message=str(result.get("output", "Erreur Perplexity inconnue"))[:300] if isinstance(result, dict) else "Réponse Perplexity invalide",
            duration_s=round(time.time() - t0, 3),
            provider=result.get("provider", "perplexity") if isinstance(result, dict) else "perplexity",
            model=result.get("model", "") if isinstance(result, dict) else "",
        )

    # Parse la réponse
    output_text = (result.get("output") or "").strip()
    if not output_text:
        return CompetitorScanResult(
            error=True,
            error_message="Réponse Perplexity vide",
            duration_s=round(time.time() - t0, 3),
            provider=result.get("provider", "perplexity"),
            model=result.get("model", ""),
        )

    # Extractions structurées
    if lang == "en":
        competitors_section = _extract_section(output_text, r"top\s+direct\s+competitors")
        market_section = _extract_section(output_text, r"market\s+metrics")
        announcements_section = _extract_section(output_text, r"recent.*announcements")
        sources_section = _extract_section(output_text, r"main\s+sources")
    else:
        competitors_section = _extract_section(output_text, r"top\s+concurrents")
        market_section = _extract_section(output_text, r"m[ée]triques\s+de\s+march[ée]")
        announcements_section = _extract_section(output_text, r"annonces\s+r[ée]centes")
        sources_section = _extract_section(output_text, r"sources\s+principales")

    competitors = _parse_competitors(competitors_section)
    market_metrics = _parse_market_metrics(market_section)

    # Sources : on prend ce qu'on trouve dans la section dédiée ET dans le reste du texte
    sources = _extract_sources(sources_section + "\n" + output_text)

    # Summary : on garde le markdown complet (les agents le réinjectent dans leur contexte)
    # Ajout d'un en-tête traçant la provenance pour la doctrine Q5 (AI Act §4bis)
    if lang == "en":
        provenance_header = (
            "⚠️ **Web search source — Perplexity Sonar (automated)** — "
            "These facts originate from automated web search and require human review (AI Act art. 50(4)).\n\n"
        )
    else:
        provenance_header = (
            "⚠️ **Source web — Perplexity Sonar (automatisé)** — "
            "Ces faits proviennent d'une recherche web automatisée et requièrent une revue humaine (AI Act art. 50(4)).\n\n"
        )
    summary = provenance_header + output_text

    return CompetitorScanResult(
        summary=summary,
        competitors=competitors,
        market_metrics=market_metrics,
        sources=sources,
        tokens_used=result.get("tokens", {}) or {},
        duration_s=round(time.time() - t0, 3),
        provider=result.get("provider", "perplexity"),
        model=result.get("model", ""),
        error=False,
        error_message="",
    )


# ════════════════════════════════════════════════════════════════════════════
# v17.1.0-B2.3-F — RECHERCHE MARCHÉ PILOTÉE PAR LES QUESTIONS DU SUJET
# (et non par le nom de société). Réutilise le transport Perplexity Sonar avec
# un prompt « marché » qui IMPOSE valeur/fourchette + année + source + URL.
# ════════════════════════════════════════════════════════════════════════════
_MARKET_SYSTEM_FR = (
    "Tu es un analyste de marché rigoureux. Réponds UNIQUEMENT avec des données "
    "réellement sourcées sur le web. Pour CHAQUE chiffre : valeur (ou fourchette "
    "basse-haute), ANNÉE, SOURCE nommée et URL. Distingue explicitement une donnée "
    "publiée d'une estimation. Si une donnée est inconnue ou non sourçable, écris-le "
    "— n'invente AUCUN chiffre, ne comble aucune lacune par extrapolation."
)
_MARKET_SYSTEM_EN = (
    "You are a rigorous market analyst. Answer ONLY with data genuinely sourced from "
    "the web. For EACH figure: value (or low-high range), YEAR, named SOURCE and URL. "
    "Explicitly distinguish a published datum from an estimate. If a datum is unknown "
    "or cannot be sourced, say so — never invent a figure or fill a gap by extrapolation."
)


def run_market_research(
    topic: str,
    questions,
    lang: str = "fr",
    max_tokens: int = 1600,
    temperature: float = 0.2,
    perplexity_call_fn: Optional[Callable] = None,
    fallback_call_fns: Optional[list] = None,
) -> Optional[dict]:
    """Recherche marché sur un SUJET (pas une société), en CASCADE ordonnée et
    fail-open. `questions` : objets exposant .question/.query (cf.
    patches/web_research.ResearchQuery) ou chaînes.

    Cascade (v17.1.0-B2.3-F.2) : on essaie les transports marché dans l'ordre et
    on retient la première réponse exploitable. Le primaire est Perplexity Sonar
    (LLM + search — le bon outil de synthèse marché). `fallback_call_fns` permet
    d'enchaîner d'autres transports search-grounded : liste de (nom, call_fn) où
    call_fn(prompt, system, temperature, max_tokens) -> dict {output, ...}.
    (NB : Tavily/Brave n'exposent aujourd'hui qu'un scan « concurrents », pas un
    transport requête-brute ; leur adaptateur marché est le prochain ajout — le
    mécanisme de cascade, lui, est en place.)

    Fail-open : None si aucun transport disponible, {error:True} si tous échouent,
    sinon {error:False, output, sources, provider, model, duration_s}. Sans exception."""
    if not topic or not questions:
        return None

    # Construit la liste ordonnée des transports marché.
    transports: list = []
    if perplexity_call_fn is not None:
        transports.append(("perplexity", perplexity_call_fn))
    elif is_web_search_available():
        try:
            from providers.perplexity_provider import call_perplexity as _cp
            transports.append(("perplexity", _cp))
        except Exception:
            pass
    for item in (fallback_call_fns or []):
        try:
            name, fn = item
            if callable(fn):
                transports.append((str(name), fn))
        except Exception:
            continue
    if not transports:
        return None

    lang = lang if lang in ("fr", "en") else "fr"
    system = _MARKET_SYSTEM_FR if lang == "fr" else _MARKET_SYSTEM_EN

    def _qline(q) -> str:
        question = getattr(q, "question", None) or (q if isinstance(q, str) else str(q))
        query = getattr(q, "query", "")
        return f"- {question}" + (f"  [requête: {query}]" if query else "")

    q_block = "\n".join(_qline(q) for q in questions)
    if lang == "en":
        user_prompt = (f"Subject: {topic}\n\nAnswer EACH question with value/range + year + "
                       f"named source + URL:\n{q_block}")
    else:
        user_prompt = (f"Sujet : {topic}\n\nRéponds à CHAQUE question avec valeur/fourchette + "
                       f"année + source nommée + URL :\n{q_block}")

    t0 = time.time()
    last_error = ""
    tried = []
    for name, fn in transports:
        tried.append(name)
        try:
            result = fn(prompt=user_prompt, system=system,
                        temperature=temperature, max_tokens=max_tokens)
        except Exception as e:
            last_error = f"{name}: {type(e).__name__}: {str(e)[:160]}"
            continue
        if not isinstance(result, dict) or result.get("error"):
            last_error = (f"{name}: " + (str(result.get("output", "erreur"))[:200]
                          if isinstance(result, dict) else "réponse invalide"))
            continue
        output_text = (result.get("output") or "").strip()
        if not output_text:
            last_error = f"{name}: réponse vide"
            continue
        return {"error": False, "topic": topic, "output": output_text,
                "sources": _extract_sources(output_text),
                "provider": result.get("provider", name),
                "model": result.get("model", ""),
                "providers_tried": tried,
                "duration_s": round(time.time() - t0, 3)}

    return {"error": True, "topic": topic, "error_message": last_error or "tous transports KO",
            "providers_tried": tried, "duration_s": round(time.time() - t0, 3)}


def build_market_fallbacks(topic: str, lang: str = "fr", providers=None) -> list:
    """v17.1.0-B2.3-F.3 — Construit des adaptateurs marché (nom, call_fn) à partir
    des providers de recherche DISPONIBLES (Tavily, Brave…) hors Perplexity, pour
    alimenter la cascade de run_market_research. Chaque call_fn interroge le
    provider sur le SUJET et renvoie {output, sources, provider}. Fail-open : []
    si aucun provider exploitable."""
    out: list = []
    if not topic:
        return out
    try:
        from patches.web_search_providers import get_default_providers
        provs = providers if providers is not None else get_default_providers()
    except Exception:
        return out
    for p in (provs or []):
        name = getattr(p, "name", "") or "fallback"
        if name == "perplexity":
            continue  # primaire géré par le transport principal
        try:
            if not p.is_available():
                continue
        except Exception:
            continue

        def _make(prov, pname):
            def _call(prompt=None, system=None, temperature: float = 0.2,
                      max_tokens: int = 1600):
                try:
                    res = prov.search(company_name=topic, sector_hint=None, lang=lang)
                except Exception as e:
                    return {"error": True, "output": f"{type(e).__name__}: {str(e)[:120]}"}
                if res is None or getattr(res, "error", False):
                    return {"error": True, "output": f"{pname} indisponible"}
                return {"output": getattr(res, "summary", "") or "",
                        "sources": list(getattr(res, "sources", []) or []),
                        "provider": getattr(prov, "name", pname)}
            return _call

        out.append((name, _make(p, name)))
    return out


# ════════════════════════════════════════════════════════════════════════════
# HELPER POUR INJECTION DANS LE CONTEXTE AGENTS
# ════════════════════════════════════════════════════════════════════════════

def format_web_search_for_agent_context(
    result: Optional[CompetitorScanResult],
    role: str = "stratégie",
    lang: str = "fr",
) -> str:
    """
    Formate un CompetitorScanResult pour injection dans le contexte d'un agent.

    Retourne une chaîne markdown commençant par un en-tête sectionnel, prête à
    être concaténée dans _pap_ctx ou _external_ctx du codir_engine.

    Si result est None ou en erreur, retourne une chaîne vide (signal que la
    veille web n'a pas pu être réalisée).
    """
    if result is None or result.error:
        return ""
    if not result.summary or not result.summary.strip():
        return ""

    if lang == "en":
        header = f"\n\n---\n## Web Watch (Perplexity Sonar) — relevant for {role}\n\n"
    else:
        header = f"\n\n---\n## Veille web (Perplexity Sonar) — pertinente pour {role}\n\n"
    return header + result.summary


__all__ = [
    "CompetitorScanResult",
    "is_web_search_available",
    "run_competitor_scan",
    "format_web_search_for_agent_context",
]
