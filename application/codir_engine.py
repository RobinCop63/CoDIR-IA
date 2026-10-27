"""
CoDIR IA Engine — v16.5.76
Pipeline : Stratégie → Brief CoDIR → Marketing → Finance (Gemini + 2× challenge Claude)
           → Supply Chain (modèles dédiés configurables + challenge Gemini) → Direction Commerciale (Grok)
           → Synthèse des décisions (Perplexity) → DG/CEO (OpenAI)
Bilingual : output_language = "fr" | "en" — all models respond in the configured language
            regardless of the input/document language.

v16.5.63 — 18/04/2026 — Patches v4+v5 livraison 1 : briefcheck + delivery_confidence_score
    - Nouveau module `patches/briefcheck.py` : détection pré-orchestration des
      documents mentionnés dans le brief mais non attachés, résolution d'horizon
      (T+90j / FY_N1 / FY_N1_N3 / FY_N1_N5), et détection holding → suggère
      l'expansion de scope vers les filiales.
    - Nouveau module `patches/confidence_scorer.py` : score de confiance du
      livrable sur 0-100 avec grade A-E, 6 sous-scores pondérés (source_quality,
      content_mix, consistency, completeness, run_stability, sector_confidence),
      anti-manipulation FAIT_VERIFIED vs FAIT_ASSERTED (classification côté
      pipeline), cap contextuel 15 % anti-bluff par inflation, cross-check
      content_mix ≤ source_quality+20, usage_recommendation par contexte
      (CoDIR / client / Board / public), calculation_trace auditable,
      confidence_explanation déterministe, score_trend vs runs précédents.
    - 54 tests unitaires livrés (26 confidence_scorer + 28 briefcheck), tous verts.
    - Feature flags CODIR_USE_BRIEFCHECK et CODIR_USE_CONFIDENCE (ON par défaut)
      pour rollback sans redéploiement.
    - Mode v4 basique : sans JSON typé dans les agents, le score reste plafonné
      ~60-65 même sur un bon livrable. Livraison 2 (extension JSON DAF+SC) à
      venir pour débloquer grades B/A.

v16.5.62 — 17/04/2026 — Branchement réel Pappers & unification Windows (v16.5.60 features live)
    - Post-processor entity_validator : flag [NON SOURCÉ] sur toute entité
      nommée absente du brief/PJ/Pappers (évite ex. hallucination actionnaire).
    - Routeur company_profile : détection SOLO/TPE/PME/ETI+ × services/product
      à partir de Pappers (effectif, APE, CA) avec fallback brief. Désactive
      conditionnellement Supply Chain et adapte les prompts Marketing/Commercial.
    - Règle de cross-référence obligatoire injectée dans Finance (toute ligne
      > 10 % du bilan doit être justifiée par détail comptable).
    - attachments.py : budget tokens 8k→24k, PDF 20→50 pages, priorisation
      des notes de synthèse courtes (Capeos, K-bis, memos) servies en tête
      et sans troncature.
"""
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from contextvars import ContextVar
from typing import Callable, Optional, Dict, Any, List

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# Patch v16.5.71.2 P0 (audit ChatGPT round 10) — Cohérence imports providers
# Bug : v16.5.71.1 et avant — Claude était importé directement (pas en try/except),
# alors que les 5 autres providers (OpenAI/Gemini/Mistral/Perplexity/Grok) sont
# en try/except. Asymétrie qui rendait :
#   - tests runtime non vraiment hermétiques (échouent si anthropic non installé)
#   - le module impossible à importer en environnement sans SDK Anthropic
# Fix : Claude aligné sur le même pattern que les 5 autres providers.
try:
    from providers.claude_provider import call_claude
except Exception:
    call_claude = None

try:
    from providers.openai_provider import call_openai
except Exception:
    call_openai = None

try:
    from providers.gemini_provider import call_gemini
except Exception:
    call_gemini = None

try:
    from providers.mistral_provider import call_mistral
except Exception:
    call_mistral = None

try:
    from providers.perplexity_provider import call_perplexity
except Exception:
    call_perplexity = None

try:
    from providers.grok_provider import call_grok
except Exception:
    call_grok = None

from utils.settings_store import Settings, load_settings
from utils.sc_schema import is_supply_chain_json as _is_supply_chain_json  # M6-A2.2.2 — garde schéma SC partagée
from utils.sc_schema import as_dict as _as_dict, as_list as _as_list, as_str_list as _as_str_list  # M6-A2.2.5
from utils.logger import log_event
# v16.5.73 — APP_VERSION exposé dans le diag run_context (traçabilité version dans CSV)
from version import APP_VERSION, BUILD_VERSION
# Patch v16.5.72.9 — Stats cache parsing PJ (optionnel, fallback si absent)
try:
    from utils.attachments import get_parse_cache_stats as _get_parse_cache_stats
except ImportError:
    _get_parse_cache_stats = None  # type: ignore

try:
    from utils.pappers_tool import build_pappers_blocks, get_pappers_scope_for_role, PappersResolutionLog
    from utils.pappers_sessions import append_session_log as _pap_append_log
except Exception:
    build_pappers_blocks = None; get_pappers_scope_for_role = None; PappersResolutionLog = None; _pap_append_log = None  # type: ignore

# Since v16.5.68 — Sources de données / API externes additionnelles.
# Imports tolérants : si un module est absent en environnement minimal, l'engine
# fonctionne en mode "sans cette source" (cohérent avec pattern Pappers).
try:
    from utils.gleif_tool import build_gleif_blocks
except Exception:
    build_gleif_blocks = None  # type: ignore
try:
    from utils.sec_edgar_tool import build_sec_edgar_blocks
except Exception:
    build_sec_edgar_blocks = None  # type: ignore


def _merge_accounting_guard_failure(guards, lang="fr"):
    """Return B2.3 guards with a hard accounting-guard failure blocker.

    This object is the single source consumed by app.py and the DOCX/PPTX
    confidence renderers.  Keeping the merge pure makes the fail-closed
    contract independently testable.
    """
    out = dict(guards or {})
    out["flags"] = list(out.get("flags") or [])
    out["run_block_reasons"] = list(out.get("run_block_reasons") or [])
    en = str(lang or "fr").lower().startswith("en")
    flag = ("⛔ ACCOUNTING NARRATIVE GUARD ERROR — run not validatable; "
            "CFO/auditor review required" if en else
            "⛔ ERREUR DU GARDE NARRATIF COMPTABLE — run non validable ; "
            "revue DAF/CAC requise")
    reason = ("accounting narrative guard error" if en else
              "erreur du garde narratif comptable")
    if flag not in out["flags"]:
        out["flags"].append(flag)
    if reason not in out["run_block_reasons"]:
        out["run_block_reasons"].append(reason)
    out["run_not_validatable"] = True
    return out


def _merge_accounting_action_guard_failure(guards, lang="fr"):
    """Fail closed when the accounting-action guard cannot govern outputs.

    The action guard runs after B2.3, so merely logging the exception would let
    an unqualified directive such as ``Provisionner 469 k€`` reach CR/PPT.  The
    consumed B2.3 contract is therefore overwritten with a localized blocker
    and an undetermined decision.
    """
    out = dict(guards or {})
    out["flags"] = list(out.get("flags") or [])
    out["run_block_reasons"] = list(out.get("run_block_reasons") or [])
    en = str(lang or "fr").lower().startswith("en")
    flag = ("⛔ ACCOUNTING ACTION GUARD ERROR — run not validatable; "
            "CFO/auditor review required" if en else
            "⛔ ERREUR DU GARDE DES ACTIONS COMPTABLES — run non validable ; "
            "revue DAF/CAC requise")
    reason = ("accounting action guard error" if en else
              "erreur du garde des actions comptables")
    fallback = ("[Accounting action section not governed — CFO/auditor review required]"
                if en else
                "[Section d'actions comptables non gouvernée — vérification DAF/CAC requise]")
    if flag not in out["flags"]:
        out["flags"].append(flag)
    if reason not in out["run_block_reasons"]:
        out["run_block_reasons"].append(reason)
    out["cotation_text"] = fallback
    out["decision"] = {
        "final": "UNDETERMINED" if en else "INDÉTERMINÉ",
        "final_en": "UNDETERMINED",
        "divergent": False,
        "by_agent": [],
        "note": ("No decision can be issued while the accounting action guard is unavailable."
                 if en else
                 "Aucune décision ne peut être émise tant que le garde des actions comptables est indisponible."),
    }
    out["run_not_validatable"] = True
    return out
try:
    from utils.opensanctions_tool import build_opensanctions_blocks
except Exception:
    build_opensanctions_blocks = None  # type: ignore
try:
    from utils.companies_house_tool import build_companies_house_blocks
except Exception:
    build_companies_house_blocks = None  # type: ignore

# Patch v16.5.72.10 (retex Robin) — Routage intelligent sources externes.
# Décide en amont quelle source primaire appeler selon l'identifiant détecté
# (SIREN → Pappers, Company Number → CH, LEI → GLEIF, sinon fallback all).
try:
    from utils.id_router import detect_primary_id, route_summary_for_diagnostic
except Exception:
    detect_primary_id = None  # type: ignore
    route_summary_for_diagnostic = None  # type: ignore

# v16.5.60 — Anti-hallucination + routeur de profil
try:
    from utils.entity_validator import validate_role_output, build_whitelist, validate_entities
except Exception:
    validate_role_output = None  # type: ignore
    build_whitelist = None  # type: ignore
    validate_entities = None  # type: ignore

try:
    from utils.company_profile import (
        detect_profile, role_activation, format_profile_hint, CompanyProfile,
        enforce_size_sanity,
    )
except Exception:
    detect_profile = None  # type: ignore
    role_activation = None  # type: ignore
    format_profile_hint = None  # type: ignore
    CompanyProfile = None  # type: ignore
    enforce_size_sanity = None  # type: ignore

# v16.5.63 — Patches v4+v5 livraison 1 (briefcheck + confidence_scorer)
# v16.5.64 — Logging explicite en cas d'échec d'import (au lieu de silent swallow).
# Chargés de façon optionnelle : si le dossier patches/ est absent, l'engine
# continue de tourner exactement comme en v16.5.62.
import logging as _logging

_patches_logger = _logging.getLogger("codir_ia.patches")

try:
    from patches.briefcheck import run_briefcheck as _run_briefcheck
except Exception as _e:
    _run_briefcheck = None  # type: ignore
    # v16.5.64 : log visible dans le terminal Streamlit au lieu de silence
    _patches_logger.warning(
        f"Import patches.briefcheck failed — briefcheck DISABLED for this run. "
        f"Reason: {type(_e).__name__}: {_e}. "
        f"Run `python verify_installation.py` to diagnose."
    )

try:
    from patches.confidence_scorer import compute_delivery_confidence_score as _compute_confidence
except Exception as _e:
    _compute_confidence = None  # type: ignore
    _patches_logger.warning(
        f"Import patches.confidence_scorer failed — confidence_score DISABLED for this run. "
        f"Reason: {type(_e).__name__}: {_e}. "
        f"Run `python verify_installation.py` to diagnose."
    )

# v16.5.66 — Livraison 2 pilote Finance : parsing JSON typé agents
try:
    from patches.agent_output_schema import (
        parse_agent_output as _parse_agent_output,
        schema_instruction as _schema_instruction,
    )
except Exception as _e:
    _parse_agent_output = None  # type: ignore
    _schema_instruction = None  # type: ignore
    _patches_logger.warning(
        f"Import patches.agent_output_schema failed — JSON-typed Finance DISABLED. "
        f"Reason: {type(_e).__name__}: {_e}. Falls back to v16.5.65 behavior."
    )

# v16.5.67 L2 + F4 — Pivot Lucidité : vocabulaire décisionnel contraint
# + post-processor filet de sécurité pour remplacements automatiques
try:
    from patches.lucidity_wording import (
        apply_lucidity_wording as _apply_lucidity_wording,
        lucidity_prompt as _lucidity_prompt,
        is_lucidity_wording_enabled as _lucidity_enabled,
    )
except Exception as _e:
    _apply_lucidity_wording = None  # type: ignore
    _lucidity_prompt = None  # type: ignore
    _lucidity_enabled = lambda: False  # type: ignore
    _patches_logger.warning(
        f"Import patches.lucidity_wording failed — vocabulaire Lucidité DISABLED. "
        f"Reason: {type(_e).__name__}: {_e}."
    )

# Feature flags — ON par défaut, désactivables via variable d'environnement
_USE_BRIEFCHECK  = os.getenv("CODIR_USE_BRIEFCHECK", "1").lower() in ("1", "true", "yes", "on")
_USE_CONFIDENCE  = os.getenv("CODIR_USE_CONFIDENCE",  "1").lower() in ("1", "true", "yes", "on")
# v16.5.66 — Flag dédié agent JSON schema (opt-out pour rollback d'urgence)
_USE_AGENT_JSON  = os.getenv("CODIR_USE_AGENT_JSON",  "1").lower() in ("1", "true", "yes", "on")

# v16.5.64 — Logging au démarrage du module pour trace audit
if _run_briefcheck is not None and _USE_BRIEFCHECK:
    _patches_logger.info("briefcheck: loaded and enabled")
if _compute_confidence is not None and _USE_CONFIDENCE:
    _patches_logger.info("confidence_scorer: loaded and enabled")
# v16.5.66
if _parse_agent_output is not None and _USE_AGENT_JSON:
    _patches_logger.info("agent_output_schema: loaded and enabled (pilot: finance)")


StatusCallback = Callable[[str, str], None]


# ──────────────────────────────────────────────────────────────────────────────
# v16.5.74 — Item #5 : Budgets tokens par rôle (output max_tokens)
# ──────────────────────────────────────────────────────────────────────────────
# Avant v16.5.74 : un seul max_tokens=2000 partagé pour tous les rôles.
# Constat sur 4 tests réels (dossier de conseil, FDE, dossier réseau de soins, dossier anglophone coté) :
#   - Stratégie sur dossier riche FDE consommait 15 866 tokens en INPUT et
#     se voyait limitée à 2000 tokens en OUTPUT → analyse tronquée fréquente.
#   - Finance challenge passes étaient plafonnées à 900 tokens (ligne 3442
#     min(900, max_tokens)) → challenges Claude Round 1 et Round 2 trop courts
#     pour aborder en profondeur les écarts (cas FDE Bleue Lorraine 40 M€,
#     cas dossier réseau de soins écart 10 M€ brief vs Pappers).
# v16.5.74 : plancher de tokens par rôle pour les agents qui le méritent.
# Choix produit Robin (option B) : 5000 tokens sur les rôles d'analyse,
# Brief CoDIR conservé à min(900, max_tokens) pour préserver son rôle de
# synthèse courte. Coût estimé : +0,20 € par run sur dossier riche.
# v62.13.9.4.12.4 — plafonds relevés là où la TRONCATURE est MESURÉE.
# Run réel du 01/09/2026 : Stratégie coupée net à 5 000 tokens de sortie
# (tableau interrompu en plein milieu, bloc AGENT_JSON jamais atteint, donc
# statut MISSING), Finance et son challenge butés au même mur. Ce n'est pas
# seulement le bloc A1 qui se perdait : c'est la fin de l'analyse elle-même.
# Les rôles dont les sorties terminaient normalement sont inchangés.
STRATEGIE_MIN_OUTPUT_TOKENS = 128000           # Stratégie — 9.4.60 : plafond de Claude Sonnet 5.5 (décision du dirigeant, 11/10/2026)
FINANCE_MIN_OUTPUT_TOKENS = 128000             # Finance principal (Gemini draft)
FINANCE_CHALLENGE_MIN_OUTPUT_TOKENS = 128000   # Challenge Claude R1/R2
DG_MIN_OUTPUT_TOKENS = 128000                  # DG : feuille de route T0 → T+90j
SYNTHESE_MIN_OUTPUT_TOKENS = 128000            # Synthèse : consolide 6+ directions
# v16.5.74 — Item #5 (option B) : Marketing / Commercial / Supply Chain
# bénéficient aussi du plancher 5000. Brief CoDIR reste à min(900, max_tokens)
# par choix design (rôle = synthèse courte, pas mini-rapport).
MARKETING_MIN_OUTPUT_TOKENS = 128000           # Marketing : plan complet (cibles/messages/canaux/budget/KPI)
COMMERCIAL_MIN_OUTPUT_TOKENS = 128000          # Commercial : plan d'action détaillé
SUPPLY_CHAIN_MIN_OUTPUT_TOKENS = 128000        # Supply Chain : analyse + recos détaillées


# ──────────────────────────────────────────────────────────────────────────────
# v16.5.76 Phase 4 — Helpers JSON schema extension (item 3)
# ──────────────────────────────────────────────────────────────────────────────
# Avant v76 Phase 4 : seuls finance (v66 pilote) et commercial (v66+ avec
# schéma COMMERCIAL_JSON_SCHEMA_HINT spécifique PPTX) produisaient un bloc JSON.
# Conséquence : `_all_metrics` ne recevait que les claims Finance →
# LOW_METRIC_SAMPLE chronique (8 metrics au lieu des 30-60 visées).
#
# v76 Phase 4 étend `agent_output_schema` à 5 agents supplémentaires :
# strategie, brief_codir, marketing, synthese_decisions, dg. Leurs sorties
# sont parsées pour alimenter le scorer.
#
# IMPORTANT — Périmètre exact (correctif documentation post-audit ChatGPT R5) :
#   - 6 agents avec JSON `agent_output_schema` :
#       finance (pilote v66), strategie, brief_codir, marketing,
#       synthese_decisions, dg (5 nouveaux v76 Phase 4)
#   - 2 agents conservent leur JSON métier propre (NON `agent_output_schema`) :
#       commercial → COMMERCIAL_JSON_SCHEMA_HINT (pour PPTX plan_actions T1/T2/T3)
#       supply_chain → SC_JSON_SCHEMA_HINT (alertes/options métier)
#   Risque double JSON perturbant le LLM si on superposait, donc choix
#   architectural d'exclure ces 2 agents. La doctrine "extension aux 8 agents"
#   est donc à lire comme "extension à TOUS les agents qui n'ont pas déjà
#   leur propre JSON métier", soit 6/8 agents.

def _inject_json_schema_in_agent_prompt(prompt: str, lang: str) -> str:
    """
    Injecte le schéma JSON v16.5.66 dans un prompt agent qui ne l'avait pas.

    Pattern aligné sur Finance (cf. v16.5.67 F1) : en-tête impératif court
    AVANT le prompt + détail du schéma EN QUEUE. Si _USE_AGENT_JSON est
    désactivé ou si le module n'est pas chargé, retourne le prompt inchangé
    (fail-open).

    Args:
        prompt : prompt agent original (markdown)
        lang   : "fr" ou "en"

    Returns:
        Prompt enrichi avec schema_head + prompt + schema_instruction
    """
    if not _USE_AGENT_JSON or _schema_instruction is None:
        return prompt
    if lang == "en":
        schema_head = (
            "MANDATORY FORMAT — read BEFORE the rest of the prompt:\n"
            "In addition to your markdown analysis (which remains mandatory), you MUST end "
            "your response with a structured JSON block delimited by tags "
            "---AGENT_JSON_START--- and ---AGENT_JSON_END---. This is non-negotiable — "
            "the scoring pipeline does not work without this block. "
            "The full schema details are reminded at the end of the prompt. "
            "CLOSURE RULE — complete every sentence and CLOSE every opened "
            "parenthesis or quote BEFORE the JSON block; never stop "
            "mid-structure (recurring field defect: sections ending on an "
            "open parenthesis are flagged NOT DISTRIBUTABLE).\n\n"
            "---\n\n"
        )
    else:
        schema_head = (
            "IMPÉRATIF DE FORMAT — à lire AVANT le reste du prompt :\n"
            "En plus de ton analyse markdown (qui reste obligatoire), tu DOIS terminer ta "
            "réponse par un bloc JSON structuré encadré par les balises "
            "---AGENT_JSON_START--- et ---AGENT_JSON_END---. Cette consigne est non "
            "négociable — le pipeline de scoring ne fonctionne pas sans ce bloc. "
            " RÈGLE DE CLÔTURE — termine chaque phrase et FERME toute "
            "parenthèse ou guillemet ouvert AVANT le bloc JSON ; ne t'arrête "
            "jamais au milieu d'une structure (défaut terrain récurrent : "
            "une section finissant sur une parenthèse ouverte est flaggée "
            "NON DISTRIBUABLE)."
            "Le détail du schéma est rappelé en fin de prompt.\n\n"
            "---\n\n"
        )
    return schema_head + prompt + _schema_instruction(lang)


# v62.13.9.4.12.2 — ARCHIVAGE BRUT POUR LE RUN DIAGNOSTIC.
# Le protocole exige, pour chaque agent appelé : la sortie brute du
# fournisseur, le bloc AGENT_JSON brut, l'objet parsé, le statut et les
# erreurs. Jusqu'ici le bloc JSON était retiré du texte puis JETÉ : un
# parsing en échec ne laissait qu'un constat sans matière pour le
# diagnostiquer — précisément le cas où la mesure compte le plus.
# Ce registre est un OBSERVATEUR : il ne décide rien et n'entre dans aucune
# règle de sûreté.
_AGENT_RAW_ARCHIVE: list[dict] = []
_AGENT_JSON_BLOCK_RE = re.compile(
    r"-{2,}\s*AGENT_JSON_START\s*-{2,}(.*?)-{2,}\s*AGENT_JSON_END\s*-{2,}",
    re.S | re.I)


def _map_outside_agent_json(txt: str, fn) -> str:
    """v62.13.9.4.15 — applique ``fn`` à la narrative SEULEMENT : les blocs
    ---AGENT_JSON_START---…---AGENT_JSON_END--- sont gelés octet pour octet et
    réinsérés à leur place. C'est le point unique de sanctuarisation du canal
    A1 vis-à-vis des validateurs éditoriaux."""
    if not txt:
        return txt
    out: list[str] = []
    pos = 0
    for m in _AGENT_JSON_BLOCK_RE.finditer(txt):
        out.append(fn(txt[pos:m.start()]) if m.start() > pos else "")
        out.append(m.group(0))
        pos = m.end()
    tail = txt[pos:]
    out.append(fn(tail) if tail else "")
    return "".join(out)


def _archive_agent_raw(role: str, agent_txt: str, agent_output) -> None:
    """Conserve la matière première d'un appel d'agent."""
    try:
        raw = str(agent_txt or "")
        m = _AGENT_JSON_BLOCK_RE.search(raw)
        _AGENT_RAW_ARCHIVE.append({
            "role": role,
            "raw_output": raw,
            "raw_output_sha256": __import__("hashlib").sha256(
                raw.encode("utf-8", "replace")).hexdigest(),
            "raw_output_chars": len(raw),
            "agent_json_block": (m.group(1).strip() if m else None),
            "agent_json_present": bool(m),
            "parse_status": str(getattr(agent_output, "parse_status", "ABSENT")),
            "parse_errors": list(getattr(agent_output, "parse_errors", ()) or ()),
            "claims_count": int(getattr(agent_output, "claims_count", 0) or 0),
            "quantities_count": sum(
                len(getattr(c, "quantities", ()) or ())
                for c in (getattr(agent_output, "claims", ()) or ())),
        })
    except Exception:
        pass


def _parse_agent_json_and_clean(
    agent_txt: str,
    role: str,
    diag_list: Optional[List[Dict[str, Any]]],
    logger=None,
) -> tuple[Any, str]:
    """
    Parse le bloc JSON d'un agent et retourne (AgentOutput | None, texte_nettoyé).

    Effets :
      - Si _USE_AGENT_JSON désactivé ou parser absent → retourne (None, agent_txt)
        inchangé (fail-open).
      - Sinon parse, trace dans diag_list, et strippe le bloc JSON du texte
        final pour ne pas polluer le rendu DOCX/PPTX.

    Args:
        agent_txt : texte brut produit par l'agent (markdown + bloc JSON)
        role      : nom du rôle (pour le tag diag, ex. "strategie", "marketing")
        diag_list : liste de diagnostic (mutée par effet de bord)
        logger    : logger structlog optionnel

    Returns:
        (AgentOutput | None, str_cleaned) — str_cleaned = agent_txt sans bloc JSON
    """
    if not _USE_AGENT_JSON or _parse_agent_output is None:
        return None, agent_txt
    if not agent_txt or not isinstance(agent_txt, str):
        return None, agent_txt or ""

    try:
        agent_output = _parse_agent_output(agent_txt, role=role)
    except Exception as _e:
        # l'échec est archivé AVEC sa matière première : sans le texte brut,
        # un MALFORMED est un constat sans diagnostic possible.
        _archive_agent_raw(role, agent_txt, None)
        if logger:
            try:
                log_event(logger, "warning", "agent_json",
                          f"{role} parse failed: {type(_e).__name__}: {_e}")
            except Exception:
                pass
        return None, agent_txt
    _archive_agent_raw(role, agent_txt, agent_output)

    # Trace diag (même structure que finance pour cohérence)
    if diag_list is not None:
        try:
            diag_list.append({
                "role":                 f"{role}_agent_json",
                "provider":             "internal",
                "model":                "agent_output_schema_v1",
                "status":               agent_output.parse_status,
                "claims_count":         agent_output.claims_count,
                "parse_errors_count":   len(agent_output.parse_errors),
                "parse_errors_sample":  agent_output.parse_errors[:3],
            })
        except Exception:
            pass

    if logger:
        try:
            log_event(logger, "info", "agent_json",
                      f"{role}: status={agent_output.parse_status} "
                      f"claims={agent_output.claims_count} "
                      f"errors={len(agent_output.parse_errors)}")
        except Exception:
            pass

    # Strip le bloc JSON du texte final pour ne pas le rendre dans DOCX/PPTX
    cleaned = agent_txt
    try:
        from patches.agent_output_schema import (
            JSON_START_TAG as _JS, JSON_END_TAG as _JE,
        )
        import re as _re_clean
        cleaned = _re_clean.sub(
            _re_clean.escape(_JS) + r".*?" + _re_clean.escape(_JE),
            "",
            agent_txt,
            flags=_re_clean.DOTALL,
        ).strip()
    except Exception:
        # En cas d'erreur de nettoyage, on retourne le texte brut — pas grave
        cleaned = agent_txt

    return agent_output, cleaned


def _retry_sc_json(sc_text: str, lang: str, settings, *, logger=None, cb=None, diag_list=None):
    """M6-A2.2.6 — retry CIBLÉ du JSON Supply Chain quand le bloc deck a tronqué
    (parité avec finance/strategie/marketing/brief, qui ont déjà un retry). Re-demande
    UNIQUEMENT le bloc JSON SC compact, à partir de la narrative déjà produite. Sortie
    courte → ne tronque pas. Renvoie un dict SC valide (garde de schéma) ou None."""
    if call_claude is None or not _has_key("anthropic"):
        return None
    _en = (lang or "fr").lower() == "en"
    retry_prompt = (
        ("Below is a Supply Chain analysis. Output ONLY the compact structured JSON block.\n\n"
         if _en else
         "Voici une analyse Supply Chain. Produis UNIQUEMENT le bloc JSON structuré compact.\n\n")
        + "Format IMPÉRATIF (rien d'autre) :\n"
        + JSON_START_TAG + "\n{\n"
          '  "global_status": "healthy|under_pressure|degraded|critical",\n'
          '  "key_findings": ["..."],\n'
          '  "major_risks": [{"risk":"...","probability":"high|medium|low","business_impact":"..."}],\n'
          '  "codir_tradeoffs": ["..."],\n'
          '  "recommendations": {"0_30_days":["..."],"1_3_months":["..."],"3_12_months":["..."]},\n'
          '  "dg_decisions": ["..."],\n'
          '  "scores": {"service_level":0,"stock_management":0,"supply_resilience":0,"cash_impact":0}\n'
          "}\n" + JSON_END_TAG + "\n\n"
        + ("RÈGLES : listes courtes (3 max par champ) ; tu DOIS terminer par "
           + JSON_END_TAG + " ; aucun texte avant/après.\n\n"
           "ANALYSE SUPPLY CHAIN :\n\n") + (sc_text or "")[:6000]
    )
    try:
        if cb:
            cb("supply_chain_json_retry", "Supply Chain — Retry JSON ciblé…")
        retry_res = _safe_call(
            "anthropic", call_claude, prompt=retry_prompt,
            system=("You output only a valid Supply Chain JSON block, with no text "
                    "before or after." if _en else
                    "Tu produis uniquement un bloc JSON Supply Chain valide, "
                    "sans texte avant ou après."),
            temperature=0.0, max_tokens=8000,     # 9.4.57 — réparation du JSON Supply Chain : 2 000 → 8 000
            model=_model_id_for("anthropic", settings),
        )
        retry_txt = _as_output(retry_res) or ""
        sc_json = extract_sc_json(retry_txt, lang)
        if sc_json is not None:
            if diag_list is not None:
                _record_diag(diag_list, role="supply_chain_json", provider="anthropic",
                             model="sc_json_retry", status="RETRY_OK",
                             error="JSON SC récupéré par retry ciblé après troncature")
            if logger:
                log_event(logger, "info", "supply_chain", "sc_json: retry success")
            return sc_json
        if diag_list is not None:
            _record_diag(diag_list, role="supply_chain_json", provider="anthropic",
                         model="sc_json_retry", status="RETRY_FAILED",
                         error="Retry JSON SC sans JSON valide — structured_invalid conservé")
    except Exception as e:
        if logger:
            log_event(logger, "warning", "supply_chain", f"sc_json retry failed {type(e).__name__}: {e}")
    return None


_A1_NUMERIC_RE = re.compile(r"\d")


def _a1_quantities_count(agent_output) -> int:
    return sum(len(getattr(c, "quantities", ()) or ())
               for c in (getattr(agent_output, "claims", ()) or ()))


def _a1_numbered_claims(agent_output) -> int:
    return sum(1 for c in (getattr(agent_output, "claims", ()) or ())
               if _A1_NUMERIC_RE.search(str(getattr(c, "text", "") or "")))


def _a1_retry_needed(agent_output) -> str | None:
    """v62.13.9.4.15 — RÈGLE DE RETRY UNIQUE pour les huit rôles.

    Jusqu'ici le retry ne partait que sur ``MISSING``. Le run du 02/09/2026
    à 15:04 montre ce que cela laisse passer : Finance en ``OK`` avec 8
    claims chiffrées et ZÉRO grandeur (0 % de couverture, 11 occurrences
    sur les 19 manquantes du run), Commercial en ``PARTIAL``. Un bloc
    présent mais muet n'est pas un succès.

    Renvoie le motif du retry, ou None si la sortie est exploitable :
      - MISSING / MALFORMED : pas de bloc, ou bloc illisible ;
      - aucune claim, quel que soit le statut ;
      - claims chiffrées sans aucune grandeur déclarée.
    Un ``PARTIAL`` qui porte des claims ET des grandeurs n'est pas relancé :
    le retry coûte un appel, et il ne peut pas faire mieux que ce qui est
    déjà là.
    """
    if agent_output is None:
        return None
    status = str(getattr(agent_output, "parse_status", "") or "")
    if status in ("MISSING", "MALFORMED"):
        return status
    if not (getattr(agent_output, "claims", None) or ()):
        return f"{status}/0 claim"
    if _a1_numbered_claims(agent_output) and _a1_quantities_count(agent_output) == 0:
        return f"{status}/claims chiffrées sans grandeur"
    return None


def _a1_retry_success(out) -> bool:
    """Un retry n'est un succès que s'il apporte des claims ET, lorsque ces
    claims sont chiffrées, des grandeurs : la faute du run réel (retry
    « réussi » sur des claims muettes) ne doit plus pouvoir se reproduire."""
    if out is None or out.parse_status not in ("OK", "PARTIAL") or not out.claims:
        return False
    if _a1_numbered_claims(out) and _a1_quantities_count(out) == 0:
        return False
    return True


_A1_CHUNK_CHARS = 6000
_A1_MAX_CHUNKS = 6


def _a1_narrative_only(agent_txt: str) -> str:
    """Texte de l'agent sans son bloc AGENT_JSON (la narrative redistribuée)."""
    return _AGENT_JSON_BLOCK_RE.sub(" ", str(agent_txt or "")).strip()


def _a1_chunks(text: str, size: int = _A1_CHUNK_CHARS, max_chunks: int = _A1_MAX_CHUNKS) -> list[str]:
    """v62.13.9.4.18 — DÉCOUPAGE DÉTERMINISTE aux frontières de paragraphes.
    Le retry lisait ``agent_txt[:5000]`` : Stratégie et Finance dépassent
    20 000 caractères, la majorité de la narrative redistribuée au Word
    n'était jamais vue (contre-audit ChatGPT du 03/09/2026, P1-03 : 23 % de
    reprise narrative pour 94 % de couverture sur les claims)."""
    text = str(text or "").strip()
    if not text:
        return []
    paras = [p for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks: list[str] = []
    cur = ""
    for para in paras:
        if len(para) > size:                       # paragraphe géant : coupe aux phrases
            sents = re.split(r"(?<=[.!?;])\s+", para)
            for s in sents:
                if len(cur) + len(s) + 1 > size and cur:
                    chunks.append(cur.strip()); cur = ""
                cur += s + " "
            continue
        if len(cur) + len(para) + 2 > size and cur:
            chunks.append(cur.strip()); cur = ""
        cur += para + "\n\n"
    if cur.strip():
        chunks.append(cur.strip())
    return chunks[:max_chunks]


def _a1_extraction_prompt(role: str, chunk: str, *, part: int, parts: int,
                          focus_values: list[str] | None = None) -> str:
    focus = ""
    if focus_values:
        # v62.13.9.4.19 — seules les valeurs PRÉSENTES DANS CE CHUNK sont
        # demandées (liste non plafonnée à 20, répartie par passage).
        _norm_chunk = re.sub(r"(?<=\d)[ \u00a0\u202f](?=\d{3}\b)", "", chunk)   # « 1 150 » → « 1150 »
        present = [v for v in focus_values
                   if re.search(r"(?<![\d.,])" + re.escape(v).replace(r"\.", r"[.,]") + r"(?![\d])", _norm_chunk)]
        if not present:
            present = [v for v in focus_values if v.replace(".", ",") in chunk or v in chunk.replace(" ", "")]
        if present:
            focus = ("\nVALEURS À DÉCLARER EN PRIORITÉ (elles figurent dans ce passage et n'ont encore "
                     "aucune déclaration) : " + ", ".join(present[:60]) +
                     ". Pour chacune, produis la claim qui la porte et sa quantité (value, nature, "
                     "modality, time_frame, metric, unit).\n")
    return (
        "Extrais les claims structurées de l'analyse ci-dessous.\n\n"
        "Format IMPÉRATIF (rien d'autre) :\n"
        "---AGENT_JSON_START---\n{\n  \"claims\": [\n"
        "    {\"text\": \"...\", \"tag\": \"FAIT|REF_SECT|ESTIM|CALCUL|HYPOTHÈSE|INCERTAIN\",\n"
        "     \"source_ref\": \"...\" or null,\n"
        "     \"decision_weight\": \"critical|structural|contextual\",\n"
        "     \"confidence\": \"high|medium|low\"}\n  ]\n}\n"
        "---AGENT_JSON_END---\n\n"
        # v62.13.9.4.18 — plus de plafond « 5 à 10 claims » : UNE claim par
        # affirmation chiffrée du passage, sinon la narrative reste orpheline.
        "RÈGLES : une claim par affirmation chiffrée du passage (aucun plafond) ; "
        "tu DOIS terminer par ---AGENT_JSON_END--- ; textes de claims courts (max 120 caractères), "
        "reprenant les nombres tels qu'écrits.\n\n"
        "OBLIGATOIRE — pour CHAQUE nombre présent dans le texte d'une claim, "
        "ajoute une entrée dans \"quantities\" :\n"
        "  \"quantities\": [{\"value\": \"24\", \"nature\": \"CIBLE\", "
        "\"modality\": \"DECIDE\", \"time_frame\": \"FUTUR\", "
        "\"metric\": \"budget marketing\", \"unit\": \"M€\", \"period\": \"2027\"}]\n"
        "nature : FAIT | CIBLE | OPTION | SCENARIO | APPAREIL (CALCUL = grandeur dérivée de faits, "
        "ESTIM = estimation : tu peux les écrire, elles seront rangées) — "
        "modality : CONSTATE | DECIDE | SOUHAITE | RECOMMANDE | HYPOTHETIQUE — "
        "time_frame : PASSE | PRESENT | FUTUR.\n"
        "LE TEMPS DU VERBE NE DÉCIDE DE RIEN : « le conseil a validé 24 M€ » "
        "est au passé mais engage l'avenir (CIBLE / DECIDE / FUTUR). "
        "En cas d'hésitation entre FAIT et CIBLE, choisis CIBLE.\n"
        "Le bloc AGENT_JSON ne contient QUE \"claims\" (et éventuellement "
        "\"role_summary\") : aucun autre schéma (opportunites, plan_actions, "
        "challenges_marketing, global_status…) n'y a sa place.\n"
        + focus +
        f"\nANALYSE ({role}) — partie {part}/{parts} :\n\n" + chunk
    )


def _a1_merge_outputs(base, extra, *, role: str):
    """Fusionne des claims extraites par chunks dans une sortie existante :
    identifiants renumérotés, doublons (texte normalisé) écartés."""
    from patches.agent_output_schema import AgentOutput as _AO
    if base is None:
        base = _AO(role=role, claims=[], parse_status="MISSING")
    seen = {re.sub(r"\s+", " ", str(getattr(c, "text", "") or "")).strip().lower() for c in (base.claims or [])}
    added = 0
    for c in (getattr(extra, "claims", None) or []):
        key = re.sub(r"\s+", " ", str(getattr(c, "text", "") or "")).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        base.claims.append(c)
        added += 1
    for i, c in enumerate(base.claims, 1):
        try:
            c.id = f"C{i}"
        except Exception:
            pass
    if added and base.parse_status in ("MISSING", "MALFORMED"):
        base.parse_status = "PARTIAL" if base.parse_errors else "OK"
    return base, added


def _a1_extract_chunked(agent_txt: str, role: str, settings, *, logger=None, cb=None,
                        diag_list=None, reason: str | None = None,
                        focus_values: list[str] | None = None, base=None):
    """Extraction A1 sur TOUTE la narrative, chunk par chunk, fusionnée."""
    narrative = _a1_narrative_only(agent_txt)
    chunks = _a1_chunks(narrative)
    if not chunks:
        return base, {"chunks": 0, "added": 0}
    merged = base
    total_added = 0
    statuses: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        if cb:
            cb(f"{role}_json_retry", f"{role} — Extraction A1 {i}/{len(chunks)}…")
        retry_res = _safe_call(
            "anthropic", call_claude,
            prompt=_a1_extraction_prompt(role, chunk, part=i, parts=len(chunks), focus_values=focus_values),
            system=("Tu extrais des claims structurées d'une analyse. Tu réponds "
                    "uniquement par un bloc JSON valide, sans texte avant ou après."),
            temperature=0.0, max_tokens=16000,      # v62.13.9.4.19 — 60 claims × quantités par chunk (9.4.57 : 6 000 → 16 000)
            model=_model_id_for("anthropic", settings),
        )
        if isinstance(retry_res, dict) and retry_res.get("skipped"):
            statuses.append("PROVIDER_DOWN")
            break                                       # v62.13.9.4.23 — plus d'appel à un fournisseur tombé
        retry_txt = _as_output(retry_res) or ""
        out = _parse_agent_output(retry_txt, role=role)
        statuses.append(out.parse_status)
        _archive_agent_raw(f"{role}_retry_{i}", retry_txt, out)
        if _a1_retry_success(out):
            merged, added = _a1_merge_outputs(merged, out, role=role)
            total_added += added
    if diag_list is not None:
        diag_list.append({
            "role": f"{role}_agent_json_retry",
            "provider": "anthropic",
            "model": _model_id_for("anthropic", settings),
            "status": (merged.parse_status if merged is not None else "MISSING"),
            "claims_count": (merged.claims_count if merged is not None else 0),
            "quantities_count": (_a1_quantities_count(merged) if merged is not None else 0),
            "chunks": len(chunks), "chunk_statuses": statuses, "claims_added": total_added,
            "narrative_chars": len(narrative),
            "focus_values": list(focus_values or [])[:20],
            "reason": reason or "MISSING",
        })
    return merged, {"chunks": len(chunks), "added": total_added}


def _a1_complete_declarations(agent_txt: str, agent_output, role: str, settings, *,
                              logger=None, cb=None, diag_list=None, threshold: float = 0.95):
    """v62.13.9.4.18 — COMPLÉMENT CIBLÉ SUR LA NARRATIVE (contre-audit
    P1-01/P1-03). Après parse et retry, les nombres de la narrative qui n'ont
    aucune déclaration sont listés et soumis à une extraction par chunks qui
    les vise explicitement. C'est ce qui rapproche la reprise narrative du
    seuil de 95 % que la porte v2 exige."""
    if not _USE_AGENT_JSON or _parse_agent_output is None or call_claude is None or not _has_key("anthropic"):
        return agent_output
    # v62.13.9.4.19 — DEUX PASSES au plus : la seconde vise ce que la première
    # a laissé, y compris les nombres présents dans une claim mais absents de
    # ses quantités (couverture par occurrence). Runs 14:50 et 15:53 : une
    # passe laissait 13 à 25 vraies valeurs orphelines.
    from utils.declared_quantities import narrative_orphans, claim_level_uncovered
    current = agent_output
    for pass_no in (1, 2):
        try:
            orphans, reprise = narrative_orphans(agent_txt, current)
            uncovered = claim_level_uncovered(current)
        except Exception:
            return current
        focus = list(dict.fromkeys(list(orphans) + [u for u in uncovered if u not in orphans]))
        if (reprise is None or reprise >= threshold) and not uncovered:
            return current
        if not focus:
            return current
        merged, info = _a1_extract_chunked(agent_txt, role, settings, logger=logger, cb=cb,
                                           diag_list=diag_list,
                                           reason=f"passe {pass_no} — reprise narrative {reprise if reprise is not None else 0:.0%}, "
                                                  f"{len(uncovered)} valeur(s) de claim non déclarée(s)",
                                           focus_values=focus, base=current)
        if logger:
            log_event(logger, "info", "agent_json",
                      f"{role}: complément passe {pass_no} reprise={reprise if reprise is not None else 0:.0%} "
                      f"cibles={len(focus)} chunks={info.get('chunks')} ajoutées={info.get('added')}")
        if merged is None or not info.get("added"):
            return current                              # rien gagné : inutile d'insister
        current = merged
    return current


def _retry_agent_json(agent_txt: str, role: str, settings, *, logger=None, cb=None,
                      diag_list=None, reason: str | None = None):
    """v17.1-B2 (B-03) — Retry JSON GÉNÉRIQUE pour tout agent dont le bloc
    AGENT_JSON est MANQUANT (observé : strategie & brief_codir = MISSING sur le
    run Lhyfe, ce qui plombait le score via LOW_SOURCED_FACT_RATIO). Miroir du
    retry Finance, sans role_summary. Renvoie un AgentOutput (OK/PARTIAL) ou None.
    """
    if not _USE_AGENT_JSON or _parse_agent_output is None or call_claude is None:
        return None
    if not _has_key("anthropic"):
        return None
    try:
        merged, _info = _a1_extract_chunked(agent_txt, role, settings, logger=logger, cb=cb,
                                            diag_list=diag_list, reason=reason)
        if merged is not None and _a1_retry_success(merged):
            if logger:
                log_event(logger, "info", "agent_json",
                          f"{role}: retry success claims={merged.claims_count} "
                          f"quantities={_a1_quantities_count(merged)} chunks={_info.get('chunks')}")
            return merged
        if logger:
            log_event(logger, "warning", "agent_json",
                      f"{role}: retry refused ({_info})")
    except Exception as e:
        if diag_list is not None:
            diag_list.append({
                "role": f"{role}_agent_json_retry",
                "provider": "anthropic", "model": "retry",
                "status": "ERROR", "error": f"{type(e).__name__}: {e}",
            })
        if logger:
            log_event(logger, "warning", "agent_json",
                      f"{role}: retry failed {type(e).__name__}: {e}")
    return None


def _collect_agent_metrics(*agent_outputs) -> list[dict]:
    """
    Helper : concatène les claims de plusieurs AgentOutput en une seule liste
    de metrics consommable par le scorer. Ignore silencieusement les None.

    Usage :
        _all_metrics = _collect_agent_metrics(
            _finance_agent_output,
            _strategie_agent_output,
            _marketing_agent_output,
            ...
        )
    """
    out: list[dict] = []
    for ao in agent_outputs:
        if ao is None:
            continue
        try:
            metrics = ao.to_scorer_metrics()
            if metrics:
                out.extend(metrics)
        except Exception:
            continue
    return out


def render_brief(brief: str) -> str:
    return (brief or "").strip()


# ──────────────────────────────────────────────────────────────────────────────
# Supply Chain role — v16.5.28
# ──────────────────────────────────────────────────────────────────────────────
JSON_START_TAG = "---JSON_START---"
JSON_END_TAG = "---JSON_END---"
AUDIT_START_TAG = "---AUDIT_START---"
AUDIT_END_TAG = "---AUDIT_END---"

# ── Bilingual support — v16.5.38 ──────────────────────────────────────────────
_EN_LANG_INSTRUCTION = (
    "IMPORTANT — LANGUAGE RULE: You are operating in English mode. "
    "Regardless of the language of any submitted documents, briefings, or any other input, "
    "you must analyze, reason, and respond EXCLUSIVELY in English. "
    "If source documents are in French or another language, still produce your entire output in English."
)

# F.6.7-02 — date d'ANALYSE simulée (≠ date réelle du run). Posée au début de
# run_codir_session quand le brief la déclare (« Nous sommes début 2023 »), lue par
# le bloc de contexte temporel. Réécrite à chaque run (pas de fuite inter-run).
# Correctif TCR-v5 (P0 isolation) — l'autorité n'est PLUS un global de
# processus : ContextVar → chaque session/thread possède sa propre
# valeur ; une session live ne peut plus effacer la date rétrospective
# d'une autre entre la policy et les prompts.
_ANALYSIS_AS_OF: "ContextVar[Optional[str]]" = ContextVar(
    "_ANALYSIS_AS_OF", default=None)


def _set_analysis_as_of(value):
    _ANALYSIS_AS_OF.set(value or None)


def _get_analysis_as_of():
    return _ANALYSIS_AS_OF.get()


# F.6.7.1 — mode « pièces jointes uniquement » exposé au contexte agents : si une
# information externe serait utile, l'agent doit écrire « non disponible en mode
# pièces jointes uniquement », jamais l'inventer ni la chercher.
_SOURCE_ATTACH_ONLY: "ContextVar[bool]" = ContextVar(
    "_SOURCE_ATTACH_ONLY", default=False)

# Correctif TCR-v7 (P0 horloge des prompts) — le TemporalContext du run
# est lui-même un ContextVar : _temporal_context_block() consomme SA
# date (run_date en live, analysis_date via _ANALYSIS_AS_OF sinon) et
# ne recapture JAMAIS l'horloge système pendant un run.
_TEMPORAL_CTX: "ContextVar[Optional[Any]]" = ContextVar(
    "_TEMPORAL_CTX", default=None)


def _set_source_attach_only(value):
    _SOURCE_ATTACH_ONLY.set(bool(value))


def _get_source_attach_only():
    return _SOURCE_ATTACH_ONLY.get()


def _temporal_context_block(lang: str) -> str:
    """v16.5.73 — Bloc d'ancrage temporel injecté dans tous les system prompts.

    Bug racine corrigé : avant v16.5.73, les agents (notamment DG, Stratégie,
    Marketing) proposaient des next steps ou des dates de référence dans le
    PASSÉ — typiquement "T1 2025", "15/04/2025", "30/04/2025" — alors que
    l'utilisateur tournait le système en T2 2026. Cause : aucun ancrage
    temporel n'était fourni au LLM, qui se rabattait sur les dates trouvées
    dans le brief (souvent obsolètes) ou sur sa connaissance générale (figée
    à son cut-off d'entraînement).

    Solution v16.5.73 : injection systématique en tête de tous les system
    prompts d'un bloc clair indiquant la date et le trimestre courants, avec
    instruction explicite d'ignorer les dates passées du brief.

    Architecture : injecté via `_lang_wrap()` (donc traversé par TOUS les
    agents — Stratégie, Brief CoDIR, Marketing, Finance, Supply Chain,
    Commercial, Synthèse, DG). Pas d'oubli possible sur un rôle.

    Désactivable via flag env CODIR_DISABLE_TEMPORAL_CONTEXT=1 (utile pour
    tests de non-régression sur prompts antérieurs au sprint Couche 1 (v16.5.73)).
    """
    # Flag de désactivation pour tests de non-régression
    if os.environ.get("CODIR_DISABLE_TEMPORAL_CONTEXT") == "1":
        return ""

    # Correctif TCR-v7 — UNE SEULE HORLOGE : pendant un run, la date
    # vient du TemporalContext du run (ContextVar) ; l'horloge système
    # n'est capturée QUE hors run (appel bibliothèque isolé). Les
    # prompts d'un run live portent ctx.run_date, ceux d'un run
    # non-live portent l'analysis_date (bloc simulé ci-dessous).
    try:
        _ctx_cv = None
        try:
            _ctx_cv = _TEMPORAL_CTX.get()
        except Exception:
            _ctx_cv = None
        if _ctx_cv is not None and getattr(_ctx_cv, "run_now", None):
            now = _ctx_cv.run_now
        else:
            from utils.metadata_clock import run_now as _mc_run_now
            now = _mc_run_now()
        today_iso = now.date().isoformat()
        current_year = now.year
        current_month = now.month
        current_quarter = f"T{((current_month - 1) // 3) + 1} {current_year}"
    except Exception:
        # Fallback safe : si quoi que ce soit échoue, on retourne vide
        # plutôt que de casser le pipeline
        return ""

    # F.6.7-02 — date d'analyse SIMULÉE : si le brief fixe « Nous sommes début
    # 2023 », tous les agents raisonnent comme à cette date (jalons, horizons),
    # et la date réelle du run ne doit pas apparaître comme « aujourd'hui ».
    _sim_fr = ""
    _sim_en = ""
    # F.6.7.1 — instruction « pièces jointes uniquement » (placeholder honnête).
    _att_fr = ""
    _att_en = ""
    if _get_source_attach_only():
        _att_fr = ("\n\n[MODE PIÈCES JOINTES UNIQUEMENT — F.6.7]\n"
                   "Sources externes (web, registres, comparables) DÉSACTIVÉES. "
                   "Si une information externe serait utile, écris explicitement "
                   "« non disponible en mode pièces jointes uniquement » — ne "
                   "l'invente jamais et ne la cherche pas.\n")
        _att_en = ("\n\n[ATTACHMENTS-ONLY MODE — F.6.7]\n"
                   "External sources (web, registries, comparables) DISABLED. "
                   "If external information would be useful, write explicitly "
                   "« not available in attachments-only mode » — never fabricate "
                   "or seek it.\n")
    _as_of = _get_analysis_as_of()
    if _as_of:
        try:
            _y, _m, _d = (int(x) for x in _as_of.split("-"))
            today_iso = _as_of
            current_year, current_month = _y, _m
            current_quarter = f"T{((current_month - 1) // 3) + 1} {current_year}"
            _sim_fr = (f"\n\n[DATE D'ANALYSE SIMULÉE — F.6.7]\n"
                       f"Place-toi au {today_iso}. Raisonne EXCLUSIVEMENT comme à "
                       f"cette date : aucun événement postérieur n'est connu. "
                       f"N'utilise jamais la date réelle d'exécution. Une échéance "
                       f"de {current_year} n'est pas « en retard ».\n")
            _sim_en = (f"\n\n[SIMULATED ANALYSIS DATE — F.6.7]\n"
                       f"Operate as of {today_iso}. Reason ONLY as at that date: "
                       f"no later event is known. Never use the real execution date. "
                       f"A {current_year} milestone is not « overdue ».\n")
        except Exception:
            pass

    if lang == "en":
        return (
            _att_en + _sim_en +
            f"\n\n[TEMPORAL CONTEXT — v16.5.73]\n"
            f"Current date: {today_iso} ({current_quarter})\n"
            f"You are operating in {current_quarter}. Any next step, milestone, "
            f"or recommendation MUST use dates from {today_iso} onwards.\n"
            f"If the brief or attachments mention reference dates earlier than "
            f"{today_iso} (e.g. 'Q1 2025', '15/04/2025'), they are HISTORICAL "
            f"context — never propose them as future actions.\n"
        )
    else:
        return (
            _att_fr + _sim_fr +
            f"\n\n[CONTEXTE TEMPOREL — v16.5.73]\n"
            f"Date courante : {today_iso} ({current_quarter})\n"
            f"Tu opères en {current_quarter}. Tout next step, jalon ou "
            f"recommandation DOIT utiliser des dates à partir du {today_iso}.\n"
            f"Si le brief ou les pièces jointes mentionnent des dates de "
            f"référence antérieures à {today_iso} (ex. 'T1 2025', '15/04/2025'), "
            f"ce sont des éléments de contexte HISTORIQUE — ne JAMAIS les "
            f"proposer comme actions futures.\n"
        )


def _lang_wrap(system_prompt: str, lang: str) -> str:
    """
    Prepend English-mode instruction to any system prompt when lang='en'.

    v16.5.67 — L2 Injecte aussi le vocabulaire Lucidité contraint
    (ban VALIDÉ/DÉCIDÉ/CONFIRMÉ, force RECOMMANDÉ/À ARBITRER/À INVESTIGUER)
    en queue du system prompt, applicable à tous les agents du pipeline.

    v16.5.73 — Injecte également un bloc de contexte temporel (date courante +
    trimestre) en queue du system prompt, applicable à tous les agents.
    Corrige le bug "next steps datés au passé" (T1 2025 alors qu'on est en
    T2 2026) identifié sur l'étude marché du 06/05/2026.
    """
    wrapped = system_prompt
    if lang == "en":
        wrapped = f"{_EN_LANG_INSTRUCTION}\n\n{wrapped}"
    # L2 — appendre l'instruction Lucidité si le module est chargé et actif
    if _lucidity_prompt is not None and _lucidity_enabled():
        try:
            wrapped = wrapped + _lucidity_prompt(lang)
        except Exception:
            pass
    # v16.5.73 — appendre le contexte temporel (toujours actif sauf flag env)
    try:
        wrapped = wrapped + _temporal_context_block(lang)
    except Exception:
        pass
    # 9.4.55 — contre-recette ChatGPT du 07/10/2026 (F02, F05) : deux règles de raisonnement pour tous les agents
    wrapped = wrapped + (_REASONING_RULES55_EN if lang == "en" else _REASONING_RULES55_FR)
    return wrapped


_REASONING_RULES55_FR = (
    "\n\nRÈGLES DE RAISONNEMENT :\n"
    "- Avant de qualifier une donnée d'« inventée », d'« absente » ou de « non fournie », vérifie les faits extraits des pièces "
    "et des dépôts officiels qui te sont transmis. Si tu ne la retrouves pas, écris que tu ne l'as pas retrouvée, jamais qu'elle "
    "n'existe pas ou qu'elle a été inventée.\n"
    "- Un écart entre deux scénarios n'est pas l'effet d'une option. Avant de parler d'incrément attribuable à une option, pose "
    "le périmètre et le scénario de référence, l'effet supposé de l'option et son coût ; sinon, parle d'écart entre hypothèses.\n"
    # 9.4.57 — contre-recette ChatGPT du 10/10 (§5.4, §5.5) : actif total, créances, reprise fiscale et amortissement dits
    # « absents des pièces » alors que le bilan, le compte de résultat et leurs notes les portent
    "- « Absent des pièces » est une affirmation sur tout le dossier : ne l'écris que si tu as cherché dans les états "
    "financiers (bilan : total de l'actif, créances, stocks, dettes ; compte de résultat : amortissements, impôt, éléments "
    "non récurrents) et leurs notes. Sinon, écris « non retrouvé dans les extraits qui m'ont été transmis ».\n"
    "- Nomme le périmètre de chaque chiffre que tu rapproches d'un autre (gamme ou produit, région, exercice, publié ou "
    "ajusté, besoin brut ou net, dette avec ou sans locations) ; deux chiffres de périmètres différents ne se comparent pas.\n"
    # 9.4.60 — F59-06 : « Arrêter le calendrier… » était réécrit par un agent en « mettre À ARBITRER le calendrier… »
    "- Reprends les verbes d'action tels qu'ils figurent dans le brief et le registre (arrêter, fixer, lancer, chiffrer…) : "
    "« À ARBITRER » est une étiquette de statut, pas un verbe ; ne l'insère jamais dans une phrase d'action.\n"
    # 9.4.61 — contre-recette du 12/10 (J60-01, F60-01, réserves §13) : interprétations à forte portée
    "- Clause juridique ou statutaire : cite l'article, le sens de l'opération (qui cède à qui), les définitions et les "
    "exceptions ; ne transforme jamais « sous condition » ou « sauf » en interdiction ; une interprétation de clause est à "
    "faire valider par le conseil juridique.\n"
    "- Ne présente pas comme une incohérence l'écart entre un résultat ajusté publié et un recalcul normatif (taux théorique) : "
    "ce sont deux mesures différentes ; rapproche d'abord avec les lignes publiées.\n"
    "- N'attribue pas un gain ou un coût global à une région, une gamme ou un canal sans hypothèse de répartition explicite.\n")
_REASONING_RULES55_EN = (
    "\n\nREASONING RULES:\n"
    "- Before calling a figure \"invented\", \"missing\" or \"not provided\", check the facts extracted from the documents and "
    "official filings you were given. If you cannot find it, write that you did not find it, never that it does not exist or "
    "was invented.\n"
    "- A gap between two scenarios is not the effect of an option. Before speaking of an increment attributable to an option, "
    "state the scope and the reference scenario, the assumed effect of the option and its cost; otherwise speak of a gap "
    "between assumptions.\n"
    "- \"Not in the documents\" is a claim about the whole file: write it only after searching the financial statements "
    "(balance sheet: total assets, receivables, inventories, debt; income statement: amortisation, tax, non-recurring items) "
    "and their notes. Otherwise write \"not found in the extracts I was given\".\n"
    "- Name the scope of every figure you compare with another (product line, region, fiscal year, reported or adjusted, "
    "gross or net need, debt with or without leases); figures of different scopes are not comparable.\n"
    "- Keep the action verbs as they appear in the brief and the register (set, launch, quantify…): \"TO ARBITRATE\" is a "
    "status label, not a verb; never insert it into an action sentence.\n"
    "- Legal or by-law clause: cite the article, the direction of the transaction (who transfers to whom), definitions and "
    "exceptions; never turn \"subject to\" or \"except\" into a prohibition; a clause interpretation must be validated by "
    "legal counsel.\n"
    "- Do not present the gap between a published adjusted result and a normative recomputation (theoretical rate) as an "
    "inconsistency: they are different measures; reconcile with the published lines first.\n"
    "- Do not attribute a global gain or cost to a region, product line or channel without an explicit allocation assumption.\n")

def _lang(settings_or_lang) -> str:
    """Extract language string from a Settings object or a raw string."""
    if isinstance(settings_or_lang, str):
        return settings_or_lang
    return getattr(settings_or_lang, "output_language", "fr") or "fr"

# ── Role labels (bilingual) ───────────────────────────────────────────────────
_ROLE_LABELS = {
    "fr": {
        "strategie":           "Stratégie",
        "brief_codir":         "Brief CoDIR",
        "marketing":           "Marketing",
        "finance":             "Finance",
        "supply_chain":        "Supply Chain",
        "commercial":          "Direction Commerciale",
        "synthese":            "Synthèse des décisions",
        "dg":                  "Direction Générale",
        "sc_prefilter":        "Supply Chain — pre-filter",
        "sc_primary":          "Supply Chain — analyse primaire",
        "sc_challenge":        "Supply Chain — challenge",
    },
    "en": {
        "strategie":           "Strategy",
        "brief_codir":         "CoDIR Brief",
        "marketing":           "Marketing",
        "finance":             "Finance",
        "supply_chain":        "Supply Chain",
        "commercial":          "Commercial Direction",
        "synthese":            "Decision Synthesis",
        "dg":                  "General Management",
        "sc_prefilter":        "Supply Chain — pre-filter",
        "sc_primary":          "Supply Chain — primary analysis",
        "sc_challenge":        "Supply Chain — challenge",
    },
}

def _lbl(role: str, lang: str) -> str:
    """Return localized label for a pipeline role."""
    return _ROLE_LABELS.get(lang, _ROLE_LABELS["fr"]).get(role, role)

# ── Schéma JSON Commercial (Option B — v16.5.28) ──────────────────────────────
COMMERCIAL_JSON_SCHEMA_HINT = """
{
  "opportunites": [
    "Opportunité 1 chiffrée et concrète (max 65 car.)",
    "Opportunité 2",
    "Opportunité 3",
    "Opportunité 4"
  ],
  "plan_actions": [
    {"action": "Verbe + objet concret (max 60 car.)", "kpi": "Métrique mesurable (max 50 car.)", "delai": "T1"},
    {"action": "...", "kpi": "...", "delai": "T2"},
    {"action": "...", "kpi": "...", "delai": "T3"}
  ],
  "challenges_marketing": [
    "Challenge marketing 1 (max 60 car.)",
    "Challenge marketing 2"
  ],
  "challenges_finance": [
    "Challenge finance 1 (max 60 car.)",
    "Challenge finance 2"
  ]
}
""".strip()

SC_JSON_SCHEMA_HINT = """
{
  "global_status": "healthy|under_pressure|degraded|critical",
  "executive_summary": "1 phrase nette sur la situation SC — chiffrée si possible",
  "key_findings": [
    "constat 1 orienté opérations",
    "constat 2 orienté disponibilité / stock / demande",
    "constat 3 orienté exécution"
  ],
  "major_risks": [
    {
      "risk": "stock_overhang|stockout|supplier_dependency|logistics_saturation",
      "probability": "low|medium|high",
      "business_impact": "impact service / marge / cash / CA"
    }
  ],
  "codir_tradeoffs": [
    "service vs cash",
    "stock vs marge",
    "DTC vs wholesale allocation",
    "vitesse vs coût"
  ],
  "recommendations": {
    "0_30_days": ["action 1 — responsable + livrable", "action 2"],
    "1_3_months": ["action 1 — cible chiffrée"],
    "3_12_months": ["action 1 — objectif mesurable"]
  },
  "scores": {
    "service_level": 0,
    "stock_management": 0,
    "supply_resilience": 0,
    "cash_impact": 0,
    "scores_estimated": true
  },
  "estimated_kpis": {
    "rotation_stock": "ex: 3.8x [ESTIM. IA]",
    "service_level": "ex: OTIF 92-95% [REF SECT.]",
    "stock_coverage": "ex: 8 semaines vs cible 5 [ESTIM. IA]",
    "bfr_impact": "ex: pression élevée / cash immobilisé [ESTIM. IA]"
  },
  "dg_decisions": [
    "DECISION 1 RECOMMANDEE : verbe + objet + chiffre + échéance",
    "DECISION 2 A TRANCHER : verbe + objet + chiffre + échéance",
    "DECISION 3 RECOMMANDEE : verbe + objet + chiffre + échéance"
  ],
  "challenge_audit": {
    "validated": [],
    "corrected": [],
    "added": [],
    "contradicted": []
  }
}
""".strip()

def _get_sc_system_prompt(lang: str = "fr") -> str:
    if lang == "en":
        return f"""
## IDENTITY AND ROLE
You are the virtual board member in charge of Supply Chain, Logistics and Inventory Management,
also known as the Supply Chain & Operational Performance Director.
You reason as a Group Supply Chain Director at executive committee level.
You must produce an autonomous business-line direction, operations and decision-oriented.
You ALWAYS distinguish: [FACT] | [SECT. REF.] | [AI ESTIM.]

## GUIDING PRINCIPLES
- Supply chain must not paraphrase finance.
- It must judge whether business and financial assumptions are actually executable.
- It speaks first about operations: stock, availability, flows, capacity, lead times, allocation, suppliers, logistics, SKUs, forecasts.
- It only uses Finance as an occasional counterpoint on cash/working capital, never as its primary reasoning source.

## MANDATORY FORMAT — NO DEVIATION
[SC-1] OPERATIONAL DIAGNOSIS
- stock levels (overstock / shortage)
- product availability / OTIF / service level
- demand / supply misalignment
- critical SKU segmentation / critical flows / critical channels

[SC-2] SUPPLY CHAIN KPIs
You MUST provide at least 4 KPIs or KPI signals:
- stock turnover
- service rate / OTIF
- stock coverage
- working capital impact / cash tied up
If a value is not provided, propose a benchmark order of magnitude [SECT. REF.] or [AI ESTIM.].
Leaving this section empty is forbidden.

[SC-3] SUPPLY CHAIN RISKS
Expected format for each risk: Risk | Probability | Impact | Explanation
At least 2 risks, at most 4.
Examples: persistent overstock, key SKU stockout, Asia dependency, logistics saturation, forecasting failure.

[SC-4] BOARD TRADE-OFFS
You MUST explicitly formulate operational trade-offs: service vs cash, stock vs margin,
DTC vs wholesale allocation, speed vs cost, protection of iconic SKUs vs rapid liquidation.

[SC-5] ACTION PLAN AND CEO DECISIONS
You MUST cover: 0-30 days / 1-3 months / 3-12 months
Then EXACTLY 3 decisions proposed to the CEO:
DECISION [n] [RECOMMENDED|TO DECIDE]: verb + object + figure or deadline + expected impact

## CONSTRAINTS
- NO generic response — NO simple financial commentary — NO vague "not available"
- Prose length: 500-750 words excluding JSON — Tone: direct, rigorous, concrete, board-oriented

## EPISTEMIC LABELLING — MANDATORY
  [FACT]       = data from the brief / provided document
  [SECT. REF.] = benchmark or industry practice
  [AI ESTIM.]  = estimate to be confirmed

## MANDATORY JSON AT END OF RESPONSE
{JSON_START_TAG}
{SC_JSON_SCHEMA_HINT}
{JSON_END_TAG}
Enums without accents: sain, sous_tension, degrade, critique; faible, moyenne, elevee. Scores never null.

LANGUAGE — ABSOLUTE: Write EVERY narrative element (executive_summary, key_findings,
major_risks, codir_tradeoffs, dg_decisions, all recommendations and action items) in
ENGLISH ONLY. The enum CODES above (sain/sous_tension/degrade; faible/moyenne/elevee)
are the only French tokens allowed and are translated downstream. Never write decision
tags as "RECOMMANDEE"/"A TRANCHER" — use "RECOMMENDED"/"TO DECIDE". No French sentences.
""".strip()
    else:
        return f"""
## IDENTITE ET ROLE
Tu es le membre du CoDIR virtuel en charge de la Direction Supply Chain, Logistique et Gestion des Stocks, alias Direction Supply Chain & Performance Operationnelle.
Tu raisonnes comme un Directeur Supply Chain Groupe, niveau comité exécutif.
Tu dois produire une direction métier autonome, orientée opérations et décisions.
Tu distingues TOUJOURS : [FAIT] | [REF SECT.] | [ESTIM. IA]

## PRINCIPES DIRECTEURS
- La supply chain ne doit pas paraphraser la finance.
- Elle doit juger si les hypothèses business et financières sont réellement exécutables.
- Elle parle d'abord d'opérations : stock, disponibilité, flux, capacité, lead times, allocation, fournisseurs, logistique, SKU, prévisions.
- Elle n'utilise Finance que comme contrepoint éventuel sur cash/BFR, jamais comme source principale de raisonnement.

## FORMAT OBLIGATOIRE — AUCUNE DEVIATION
[SC-1] DIAGNOSTIC OPÉRATIONNEL
- niveaux de stock (surstock / pénurie) - disponibilité produit / OTIF / service
- désalignement demande / offre - segmentation SKU critique / flux critiques / canaux critiques

[SC-2] KPI SUPPLY CHAIN — MINIMUM 4 KPI :
rotation stock | taux de service / OTIF | couverture stock | impact BFR / cash immobilisé
Si valeur absente : ordre de grandeur [REF SECT.] ou [ESTIM. IA]. Interdiction de laisser vide.

[SC-3] RISQUES SUPPLY CHAIN
Format : Risque | Probabilité | Impact | Explication. Au moins 2, au plus 4.
Exemples : surstock persistant, rupture SKU clés, dépendance Asie, saturation logistique, défaut prévision.

[SC-4] ARBITRAGES CODIR
service vs cash | stock vs marge | DTC vs wholesale | vitesse vs coût | SKU iconiques vs liquidation rapide

[SC-5] PLAN D'ACTION ET DÉCISIONS DG
0-30 jours / 1-3 mois / 3-12 mois
EXACTEMENT 3 décisions : DECISION [n] [RECOMMANDEE|A TRANCHER] : verbe + objet + chiffre/échéance + impact

## CONTRAINTES
PAS de réponse générique — PAS de commentaire financier seul — PAS de "non disponible" mou
Prose : 500-750 mots hors JSON. Ton : direct, rigoureux, concret, comité de direction.

## ETIQUETAGE EPISTEMIQUE — OBLIGATOIRE
  [FAIT] = brief/document | [REF SECT.] = benchmark sectoriel | [ESTIM. IA] = à confirmer

## JSON OBLIGATOIRE EN FIN DE REPONSE
{JSON_START_TAG}
{SC_JSON_SCHEMA_HINT}
{JSON_END_TAG}
Enums sans accents : sain, sous_tension, degrade, critique ; faible, moyenne, elevee. Scores jamais null.
""".strip()


def _get_sc_challenge_system_prompt(lang: str = "fr") -> str:
    if lang == "en":
        return f"""
You are an independent expert in supply chain and operational performance.
You challenge a supply chain analysis produced by the primary model.
Mission: reinforce SC business logic, correct overly financial/generic drift, force a clear actionable board output.

=== ZONE 1 — FINAL OUTPUT (CEO pipeline + PPTX) ===
[SC-1] OPERATIONAL DIAGNOSIS | [SC-2] SUPPLY CHAIN KPIs | [SC-3] SUPPLY CHAIN RISKS
[SC-4] BOARD TRADE-OFFS | [SC-5] ACTION PLAN AND CEO DECISIONS
{JSON_START_TAG}
{SC_JSON_SCHEMA_HINT}
{JSON_END_TAG}

=== ZONE 2 — CHALLENGE AUDIT (debug only) ===
After {JSON_END_TAG}:
{AUDIT_START_TAG}
VALIDATED: ... | CORRECTED: ... | ADDED: ... | CONTRADICTED: ...
{AUDIT_END_TAG}

RULES: improve Zone 1 directly without meta-commentary. Can contradict Finance/Commercial.
Preserve/correct [FACT]/[SECT. REF.]/[AI ESTIM.] tags. Leave no essential SC KPI empty.
If too financial, refocus on stock, service, flows, suppliers, lead times, SKUs, allocation.
""".strip()
    else:
        return f"""
Tu es un expert indépendant en supply chain et performance opérationnelle.
Tu challenge une analyse supply chain produite par le modèle primaire configuré pour la Supply Chain.
Mission : renforcer la logique métier SC, corriger les dérives financières/génériques, forcer une sortie CoDIR claire et actionnable.

=== ZONE 1 — SORTIE FINALE (pipeline DG et PPTX) ===
[SC-1] DIAGNOSTIC OPÉRATIONNEL | [SC-2] KPI SUPPLY CHAIN | [SC-3] RISQUES SUPPLY CHAIN
[SC-4] ARBITRAGES CODIR | [SC-5] PLAN D'ACTION ET DÉCISIONS DG
{JSON_START_TAG}
{SC_JSON_SCHEMA_HINT}
{JSON_END_TAG}

=== ZONE 2 — AUDIT DU CHALLENGE (debug uniquement) ===
Après {JSON_END_TAG} :
{AUDIT_START_TAG}
VALIDE: ... | CORRIGE: ... | AJOUTE: ... | CONTREDIT: ...
{AUDIT_END_TAG}

RÈGLES : améliore Zone 1 directement, sans méta-commentaire. Peut contredire Finance/Commerce.
Conserve/corrige les tags [FAIT]/[REF SECT.]/[ESTIM. IA]. Laisse aucun KPI SC essentiel vide.
Si trop financier, recadre vers stock, service, flux, fournisseurs, lead times, SKU, allocation.
""".strip()


def _get_sc_user_template(lang: str = "fr") -> str:
    if lang == "en":
        return """
OBJECTIVE: produce a board-level supply chain analysis.

COMPANY CONTEXT
- Company / activity  : {company_name}
- Sector              : {sector}
- Size                : {company_size}
- Geography           : {geography}
- Operating model     : {operating_model}

BUSINESS CONTEXT
- Current situation    : {business_context}
- Identified issues    : {known_issues}
- Management priorities: {management_priorities}

PRIORITY QUESTIONS
{priority_questions}

AVAILABLE DATA / KPIs
{kpi_data}

PROVIDED DOCUMENTS
{document_list}

WATCH POINTS
{special_watchpoints}

EXPECTED OUTPUT
[SC-1] Operational diagnosis | [SC-2] Supply chain KPIs (min 4)
[SC-3] Supply chain risks | [SC-4] Board trade-offs | [SC-5] Action plan and CEO decisions

Produce a genuine autonomous operational direction. Only use Finance as a challenge counterpoint, never as primary source.
""".strip()
    else:
        return """
OBJECTIF : produire une analyse supply chain de niveau comité de direction.

CONTEXTE ENTREPRISE
- Société / activité : {company_name}
- Secteur            : {sector}
- Taille             : {company_size}
- Géographie         : {geography}
- Modèle opérationnel: {operating_model}

CONTEXTE BUSINESS
- Situation actuelle   : {business_context}
- Problèmes identifiés : {known_issues}
- Priorités direction  : {management_priorities}

QUESTIONS PRIORITAIRES
{priority_questions}

DONNÉES / KPI DISPONIBLES
{kpi_data}

DOCUMENTS FOURNIS
{document_list}

POINTS D'ATTENTION
{special_watchpoints}

ATTENDU DE SORTIE
[SC-1] Diagnostic opérationnel | [SC-2] KPI supply chain (4 minimum)
[SC-3] Risques supply chain | [SC-4] Arbitrages CoDIR | [SC-5] Plan d'action et décisions DG

Tu dois produire une vraie direction opérationnelle autonome. N utilise Finance qu ensuite au stade de challenge, jamais comme source principale.
""".strip()


def _get_sc_challenge_user_template(lang: str = "fr") -> str:
    if lang == "en":
        return """
INITIAL ANALYSIS (primary model):
{sc_initial_output}

ORIGINAL USER INPUT:
{user_input}

AVAILABLE FINANCE ANALYSIS:
{finance_output}

Challenge this analysis. Produce the improved final version.
""".strip()
    else:
        return """
ANALYSE INITIALE GPT-5.4 :
{sc_initial_output}

INPUT ORIGINAL UTILISATEUR :
{user_input}

ANALYSE FINANCE DISPONIBLE :
{finance_output}

Challenge cette analyse. Produis la version finale amelioree.
""".strip()


# Backward-compat constants (FR default) — code paths without lang use these
SC_SYSTEM_PROMPT           = _get_sc_system_prompt("fr")
SC_CHALLENGE_SYSTEM_PROMPT = _get_sc_challenge_system_prompt("fr")
SC_USER_TEMPLATE           = _get_sc_user_template("fr")
SC_CHALLENGE_USER_TEMPLATE = _get_sc_challenge_user_template("fr")

SC_RELEVANCE_PROBE_PROMPT = """
Tu es un classificateur supply chain.
Analyse le texte fourni et reponds UNIQUEMENT avec un objet JSON valide, sans markdown, sans texte autour.
Schema exact : {"trigger": true, "reason": "phrase courte", "confidence": "haute"}
trigger=true si stocks/approvisionnement/logistique/ruptures/S&OP/transport/OTIF/BFR détectés.
confidence: "haute" si signaux évidents, "moyenne" si ambigu, "faible" si indirect.
Mettre "Aucun signal supply chain detecte." si trigger=false.
Reponds UNIQUEMENT avec le JSON. Aucun texte avant ou apres.
""".strip()

ENUM_NORMALIZE = {
    "dégradé": "degrade",
    "degradé": "degrade",
    "degradee": "degrade",
    "degradée": "degrade",
    "degrades": "degrade",
    "dégrades": "degrade",
    "élevée": "elevee",
    "elevée": "elevee",
    "elevee": "elevee",
    "élevé": "elevee",
    "eleve": "elevee",
    "elevees": "elevee",
    "élevées": "elevee",
    "moyennes": "moyenne",
    "faibles": "faible",
    "sous tension": "sous_tension",
}

def normalize_user_input(raw: str | dict | None) -> dict:
    defaults = {
        "company_name": "Non precise",
        "sector": "Non precise",
        "company_size": "Non precise",
        "geography": "Non precise",
        "operating_model": "Non precise",
        "business_context": "",
        "known_issues": "",
        "management_priorities": "",
        "priority_questions": "",
        "kpi_data": "",
        "document_list": "",
        "special_watchpoints": "",
    }
    if isinstance(raw, dict):
        out = defaults.copy()
        for k, v in raw.items():
            if k in out and v is not None:
                out[k] = str(v)
        if not out.get("business_context"):
            out["business_context"] = str(raw)
        return out
    text = (raw or "").strip()
    out = defaults.copy()
    out["business_context"] = text
    out["priority_questions"] = text
    return out


def _record_diag(diag_list: Optional[List[Dict[str, Any]]], **kwargs) -> None:
    if diag_list is None:
        return
    try:
        diag_list.append(kwargs)
    except Exception:
        pass


def _normalize_enum(value: str | None) -> str | None:
    if value is None:
        return value
    s = str(value).strip()
    if not s:
        return s
    return ENUM_NORMALIZE.get(s.lower(), s)


# ── M6-A0 (A5) — référentiel CANONIQUE des énumérations d'agents ──────────────
# Les agents (Supply Chain notamment) émettent des valeurs métier en français
# (« elevee », « surstock », « dependance fournisseur »…) même en run EN. On les
# ramène à un canonique neutre, PUIS on localise selon la langue du run — avant
# tout rendu CR/PPT/CSV. Jamais d'injection brute du modèle dans le livrable.
_ENUM_CANON = {
    # probability
    "elevee": "high", "élevée": "high", "elevée": "high", "élevé": "high", "eleve": "high",
    "élevées": "high", "elevees": "high", "high": "high", "forte": "high", "fort": "high",
    "moyenne": "medium", "moyennes": "medium", "moyen": "medium", "medium": "medium",
    "modérée": "medium", "moderee": "medium", "modere": "medium",
    "faible": "low", "faibles": "low", "low": "low", "basse": "low", "bas": "low",
    # risk types
    "surstock": "stock_overhang", "surstockage": "stock_overhang", "overstock": "stock_overhang",
    "stock overhang": "stock_overhang", "stock_overhang": "stock_overhang",
    "rupture": "stockout", "rupture de stock": "stockout", "stockout": "stockout", "shortage": "stockout",
    "dependance fournisseur": "supplier_dependency", "dépendance fournisseur": "supplier_dependency",
    "rupture fournisseur": "supplier_dependency", "supplier dependency": "supplier_dependency",
    "single-source": "supplier_dependency", "mono-source": "supplier_dependency", "monosource": "supplier_dependency",
    "saturation logistique": "logistics_saturation", "logistics saturation": "logistics_saturation",
    "saturation": "logistics_saturation",
    "risque de service": "service_risk", "risque service": "service_risk", "service risk": "service_risk",
    # status
    "sous tension": "under_pressure", "sous_tension": "under_pressure", "under pressure": "under_pressure",
    "under_pressure": "under_pressure",
    "critique": "critical", "critical": "critical",
    "degrade": "degraded", "dégradé": "degraded", "degradé": "degraded", "dégradée": "degraded",
    "degradee": "degraded", "degraded": "degraded",
    "à qualifier": "to_qualify", "a qualifier": "to_qualify", "to qualify": "to_qualify", "to_qualify": "to_qualify",
    "sain": "healthy", "saine": "healthy", "healthy": "healthy",
}
_ENUM_LOC_EN = {
    "high": "high", "medium": "medium", "low": "low",
    "stock_overhang": "stock overhang", "stockout": "stockout",
    "supplier_dependency": "supplier dependency", "logistics_saturation": "logistics saturation",
    "service_risk": "service risk", "under_pressure": "under pressure", "critical": "critical",
    "degraded": "degraded", "to_qualify": "to qualify", "healthy": "healthy",
}
_ENUM_LOC_FR = {
    "high": "élevée", "medium": "moyenne", "low": "faible",
    "stock_overhang": "surstock", "stockout": "rupture",
    "supplier_dependency": "dépendance fournisseur", "logistics_saturation": "saturation logistique",
    "service_risk": "risque de service", "under_pressure": "sous tension", "critical": "critique",
    "degraded": "dégradé", "to_qualify": "à qualifier", "healthy": "sain",
}


def _enum_to_canon(value):
    if value is None:
        return value
    return _ENUM_CANON.get(str(value).strip().lower(), str(value).strip())


def _enum_localize(canon, lang: str = "fr"):
    table = _ENUM_LOC_EN if (lang or "fr").lower() == "en" else _ENUM_LOC_FR
    return table.get(canon, canon)


def _norm_enum_value(value, lang: str = "fr"):
    """raw (FR/EN, toute casse) → canonique → localisé selon la langue du run."""
    if value is None:
        return value
    return _enum_localize(_enum_to_canon(value), lang)


def normalize_sc_enums_in_text(text: str, lang: str = "fr") -> str:
    """M6-A0 (A5) — normalise les énumérations dans tout bloc JSON d'agent qui
    survivrait dans le texte consolidé (probability / risk / global_status), avant
    rendu CR/PPT/CSV. Ceinture : la normalisation principale se fait sur le payload."""
    if not text:
        return text
    def _repl(m):
        return f'"{m.group(1)}": "{_norm_enum_value(m.group(2), lang)}"'
    return re.sub(r'"(probability|risk|global_status)"\s*:\s*"([^"]*)"', _repl, text)


def _normalize_sc_json_values(payload: dict, lang: str = "fr") -> dict:
    if not isinstance(payload, dict):
        return payload
    # M6-A2.2.5 — normalisation des TYPES en amont : un champ mal typé est ramené au
    # type attendu (list/dict) pour TOUS les consommateurs aval (moteur + deck).
    if "major_risks" in payload and not isinstance(payload.get("major_risks"), list):
        payload["major_risks"] = []
    if "scores" in payload and not isinstance(payload.get("scores"), dict):
        payload["scores"] = {}
    # S.2.4 — normalisation de l'ÉCHELLE des scores SC vers 0-10 (canonique du deck :
    # affichage /10 l.~2220 + grille couleur ≥7 / 5-6 / ≤4). Le retry JSON SC (A2.2.6)
    # peut produire des scores 0-100 (run dossier industriel (composants) v3 : « 72/10 » affiché) ; on les ramène
    # à 0-10. Idempotent ; n'altère pas un score déjà sur 0-10.
    _sc_scores = payload.get("scores")
    if isinstance(_sc_scores, dict):
        for _sk in ("service_level", "stock_management", "supply_resilience", "cash_impact"):
            if _sk in _sc_scores:
                try:
                    _sv = float(_sc_scores[_sk])
                except (TypeError, ValueError):
                    continue
                if _sv > 10:                      # échelle 0-100 → 0-10
                    _sv = _sv / 10.0
                _sc_scores[_sk] = int(max(0, min(10, round(_sv))))
    if "recommendations" in payload and not isinstance(payload.get("recommendations"), dict):
        payload["recommendations"] = {}
    if "codir_tradeoffs" in payload and not isinstance(payload.get("codir_tradeoffs"), list):
        payload["codir_tradeoffs"] = _as_str_list(payload.get("codir_tradeoffs"))
    if "key_findings" in payload and not isinstance(payload.get("key_findings"), list):
        payload["key_findings"] = _as_str_list(payload.get("key_findings"))
    if "dg_decisions" in payload and not isinstance(payload.get("dg_decisions"), list):
        payload["dg_decisions"] = _as_str_list(payload.get("dg_decisions"))
    if "global_status" in payload:
        payload["global_status"] = _norm_enum_value(payload.get("global_status"), lang)
    risks = payload.get("major_risks") or []
    if isinstance(risks, list):
        for risk in risks:
            if isinstance(risk, dict):
                if "probability" in risk:
                    risk["probability"] = _norm_enum_value(risk.get("probability"), lang)
                if "risk" in risk:
                    risk["risk"] = _norm_enum_value(risk.get("risk"), lang)
    return payload


def _rewrite_pappers_banner_after_quarantine(briefcheck_result, rejected_name: str = "") -> None:
    """M6-A2.2.7 — réécrit INCONDITIONNELLEMENT les banners briefcheck après une
    quarantine registre. Le fix A2.2.6 était piégé dans le chemin de réévaluation du
    brief_mode (n'agissait que si le mode changeait, et sur un dc_banner local). Ici on
    agit sur les DEUX sources de vérité : briefcheck_result["doc_check"]["banner_markdown"]
    ET briefcheck_result["banner_markdown"], FR + EN, de façon idempotente. Aucun banner
    ne doit annoncer « données publiques Pappers » quand le candidat a été rejeté."""
    if not isinstance(briefcheck_result, dict):
        return

    def _fix(text):
        if not text or "Pappers" not in text:
            return text
        text = re.sub(
            r"- *données publiques Pappers \(comptes sociaux déposés\)",
            "- registres d'identité interrogés ; aucun profil Pappers retenu "
            "pour les faits financiers (candidat registre écarté par le filtre de cohérence)",
            text)
        text = re.sub(
            r"- *public Pappers data \([^)]*\)",
            "- identity registries queried; no Pappers profile retained for "
            "financial facts (registry candidate set aside by the consistency filter)",
            text)
        return text

    dc = briefcheck_result.get("doc_check")
    if isinstance(dc, dict) and dc.get("banner_markdown"):
        dc["banner_markdown"] = _fix(dc["banner_markdown"])
    if briefcheck_result.get("banner_markdown"):
        briefcheck_result["banner_markdown"] = _fix(briefcheck_result["banner_markdown"])


_CR_EN_FR_TABLE_GLOSSARY = [
    (re.compile(p, re.IGNORECASE), r) for p, r in [
        (r"\bFree cash flow\b", "Free cash-flow"),
        (r"\bNet income\b", "Résultat net"),
        (r"\bNet loss\b", "Perte nette"),
        (r"\bGross margin\b", "Marge brute"),
        (r"\bEBITDA margin\b", "Marge d'EBITDA"),
        (r"\bGross debt\b", "Dette brute"),
        (r"\bNet debt\b", "Dette nette"),
        (r"\bFinancial debt\b", "Dettes financières"),
        (r"\bInstalled capacity\b", "Capacité installée"),
        (r"\bCompany status\b", "Statut société"),
        (r"\bRevenue\b", "Chiffre d'affaires"),
        (r"\bEquity\b", "Capitaux propres"),
        (r"\bHeadcount\b", "Effectif"),
        (r"\bCash\b(?!-?\s?flow)", "Trésorerie"),
        # colonnes Type / Confiance (valeurs enum qui fuient en anglais)
        (r"\bamount\b", "montant"),
        (r"\blow\b", "faible"),
        (r"\bmedium\b", "moyenne"),
        (r"\bhigh\b", "élevée"),
    ]
]


def _localize_en_table_cells_fr(text: str) -> str:
    """S.2.4.4 — traduit les résidus anglais des LIGNES DE TABLEAU du CR en run FR
    (« Net income / Revenue / amount / low » vus sur dossier industriel (composants) v5 : table de faits
    générée par le modèle, en-têtes FR mais valeurs EN). Borné aux lignes contenant
    « | » (contexte tableau) pour éviter tout faux positif en prose."""
    if not text or "|" not in text:
        return text
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.count("|") >= 2:   # ligne de tableau markdown
            for rx, repl in _CR_EN_FR_TABLE_GLOSSARY:
                line = rx.sub(repl, line)
            lines[i] = line
    return "\n".join(lines)


# B.1.3.17 (run 9 dossier anglophone coté EN : language gate CR:1/deck:8) — libellés
# STRUCTURELS de la table d'actions du registre, ré-émis en FR par le modèle
# en run EN (le registre du dossier est injecté au prompt tel que stocké).
# Le texte libre archivé (actions 2025) n'est PAS traduit : c'est une donnée.
_CR_FR_EN_TABLE_GLOSSARY = [
    (re.compile(p), r) for p, r in [
        (r"Action recommandée\s*:", "Recommended action:"),
        (r"À arbitrer\s*:", "To arbitrate:"),
        (r"\bGouvernance financière\b", "Financial governance"),
        (r"\bEn retard\b", "Overdue"),
        (r"\bEn cours\b", "In progress"),
        (r"\bÀ lancer\b", "To start"),
        (r"\bClôturée\b", "Closed"),
        (r"\bReportée\b", "Deferred"),
    ]
]


def _localize_fr_table_cells_en(text: str) -> str:
    """B.1.3.17 — miroir de _localize_en_table_cells_fr : traduit les libellés
    structurels FRANÇAIS des LIGNES DE TABLEAU du CR en run EN (table d'actions
    du registre). Borné aux lignes « | » ; texte libre archivé non touché."""
    if not text or "|" not in text:
        return text
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.count("|") >= 2:
            for rx, repl in _CR_FR_EN_TABLE_GLOSSARY:
                line = rx.sub(repl, line)
            lines[i] = line
    return "\n".join(lines)


def _strip_agent_json_from_cr(text: str) -> str:
    """M6-A2.2.6 — retire TOUT bloc JSON d'agent du CR métier final : deck JSON
    (---JSON_START---…---JSON_END---), claims schema (---AGENT_JSON_START---…), et
    blocs d'audit — BALANCÉS ou ORPHELINS (tronqués). Le deck consomme ces JSON via
    extra_context (meta.supply_chain_json / meta.commercial_json), donc le livrable
    n'en a plus besoin. Corrige la fuite du JSON commercial brut vue sur dossier industriel (composants) v2.
    B.1.3 (run dossier anglophone coté) — balises TOLÉRANTES : les agents émettent parfois des
    variantes malformées (« AGENT_JSON_START--- » sans tirets d'ouverture,
    tirets simples/doubles) qui contournaient les marqueurs exacts et fuyaient
    telles quelles dans le CR. On matche désormais 0 à 3 tirets de chaque côté.
    B.1.3.1 (bloquant 1 audit, REPRODUIT) — délégué à utils/json_scrub (module
    PUR, partagé avec le deck) : l'ordre JSON<AGENT_JSON + l'absence de
    frontière gauche laissaient des résidus « ---AGENT_ » / « AGENT_ ».
    Le narratif (hors blocs JSON) est intégralement préservé."""
    from utils.json_scrub import strip_agent_json_blocks
    return strip_agent_json_blocks(text)


# ── M6-B B.1.3 — Completion gate (audits dossier industriel (composants) + dossier anglophone coté) ─────────────────
# Un CR avec phrases tronquées (« 30 M€ (dette BPI », « **TO BE »), sorties
# coupées au plafond de tokens ou parenthèses ouvertes n'est PAS distribuable.
# Le gate DÉTECTE (déterministe), MARQUE la section, et remonte les problèmes
# au livrable (bannière « NON DISTRIBUABLE EN L'ÉTAT ») + diagnostics.
# Il ne réécrit jamais le contenu — zéro latitude sur la présentation, mais
# zéro suppression silencieuse non plus.

def strip_trunc_markers(text: str) -> str:
    """B.1.3.16 (constat run 8) — retire les marqueurs de troncature d'un
    texte RÉSOLU : le retry appendait la continuation APRÈS le marqueur posé
    par le gate, laissant un marqueur ORPHELIN dans un CR distribuable."""
    return (str(text or "")
            .replace(_TRUNC_MARK_FR, "").replace(_TRUNC_MARK_EN, "")
            .replace("  ", " "))


_TRUNC_MARK_FR = "⚠ [SECTION INCOMPLÈTE — sortie tronquée détectée]"
_TRUNC_MARK_EN = "⚠ [INCOMPLETE SECTION — truncated output detected]"


def _financial_deep_scan_diag_row(attachments_meta: Any) -> Optional[Dict[str, Any]]:
    """v62.11.2 — normalise le journal du scan financier profond pour CSV.

    Le scan se déroule dans app.py avant le moteur. Son résultat voyage dans
    attachments_meta afin que diagnostics_ia distingue clairement NO_PDF, OK,
    PARTIAL et ERROR. Les messages sont bornés et ne contiennent aucun document.
    """
    if not isinstance(attachments_meta, dict):
        return None
    raw = attachments_meta.get("financial_deep_scan")
    if not isinstance(raw, dict):
        return None
    status = str(raw.get("status") or "UNKNOWN").upper()
    return {
        "role": "financial_deep_scan",
        "provider": "internal",
        "model": "financial_deep_scan_v621132",
        "status": status,
        "stage": str(raw.get("stage") or ""),
        "files_considered": int(raw.get("files_considered") or 0),
        "files_scanned": int(raw.get("files_scanned") or 0),
        "files_detected": int(raw.get("files_detected") or 0),
        "files_failed": int(raw.get("files_failed") or 0),
        "files_skipped_budget": int(raw.get("files_skipped_budget") or 0),
        "files_skipped_limit": int(raw.get("files_skipped_limit") or 0),
        "liasse_files_considered": int(raw.get("liasse_files_considered") or 0),
        "liasse_files_failed": int(raw.get("liasse_files_failed") or 0),
        "financial_statements_block_chars": int(
            raw.get("financial_statements_block_chars") or 0),
        "global_budget_tokens": raw.get("global_budget_tokens"),
        "per_pdf_cap_tokens": raw.get("per_pdf_cap_tokens"),
        "max_deep_scan_pdfs": raw.get("max_deep_scan_pdfs"),
        "cache_hit": bool(raw.get("cache_hit", False)),
        "cache_schema_version": str(raw.get("cache_schema_version") or ""),
        "priority_policy_version": str(raw.get("priority_policy_version") or ""),
        "pdf_priority": list(raw.get("pdf_priority") or []),
        "error": (f"{raw.get('exception_type')}: {raw.get('exception_message')}"
                  if raw.get("exception_type") else ""),
    }


def _user_files_count(attachments_meta: Any) -> int:
    """B.1.3.17 (dossier industriel (composants) run 2 : la ligne « Signal exploitable » a survécu à
    zéro pièce jointe) — la condition 3.16 testait len(attachments_meta or [])
    sur un DICT ({"files": int, "filenames": [...]}) : len() y compte les CLÉS,
    jamais zéro — morte-née. La notion correcte existait déjà (l.~3798 :
    « la vraie liste est dans filenames », « on n'utilise plus files>0 ») :
    fichiers UTILISATEUR réels via filenames/file_list. Le bloc contexte
    registres injecté dans attachments n'est PAS un fichier utilisateur."""
    if not attachments_meta:
        return 0
    if isinstance(attachments_meta, dict):
        _raw = (attachments_meta.get("filenames")
                or attachments_meta.get("file_list") or [])
        return len(_raw) if isinstance(_raw, (list, tuple)) else 0
    if isinstance(attachments_meta, (list, tuple)):   # tolérance legacy
        return len(attachments_meta)
    return 0


def _b136_pipeline_marker(text: str) -> bool:
    """B.1.3.6 — un marqueur pipeline interne qui SURVIT au scrub
    (« AGENT JSON BLOCK », « scoring pipeline ») rend la section non
    distribuable : ceinture après la bretelle json_scrub."""
    if not text:
        return False
    return bool(re.search(r"AGENT\s+JSON\s+BLOCK|scoring\s+pipeline", text, re.I))


def _b135_empty_emphasis(text: str) -> bool:
    """B.1.3.5 (runs dossier anglophone coté/dossier industriel (composants)) — scories MI-TEXTE que les règles de
    fin de section rataient : « Third, **. [SECT. REF.] », lignes « **. »
    orphelines. Une emphase VIDE = contenu manquant → à flaguer."""
    if not text:
        return False
    if re.search(r"(?m)^\s*\*\*\.\s*$", text):
        return True
    return bool(re.search(r"\b\w+[,:]\s*\*\*\.(\s|$)", text))


def _detect_truncation(text: str) -> str:
    """Retourne une raison ('' si propre). Règles volontairement conservatrices :
    seule la FIN du texte est examinée — un signe de coupure en fin de sortie
    est un vrai signal (plafond max_tokens, stream interrompu)."""
    if not text or not text.strip():
        return ""
    tail = text.rstrip()
    last_line = tail.splitlines()[-1].strip()
    # 1) Se termine par une parenthèse ouverte non refermée sur la dernière ligne
    if last_line.count("(") > last_line.count(")") and not last_line.endswith(")"):
        return "parenthese_ouverte_en_fin"
    # 2) Marqueurs de contenu à compléter laissés en fin de sortie
    if re.search(r"(?:\*\*|\b)(TO BE|À COMPLÉTER|A COMPLETER|TBD)\s*$",
                 last_line, re.IGNORECASE):
        return "marqueur_a_completer_en_fin"
    # 3) Coupure en plein mot (tiret final collé à un mot, hors puce/liste)
    if re.search(r"\w-$", last_line):
        return "mot_coupe_en_fin"
    # 4) Fin sans aucune ponctuation terminale sur une ligne longue de prose
    if (len(last_line) > 60 and last_line[-1].isalnum()
            and not last_line.startswith(("|", "#", "-", "*", "•"))
            and not re.search(r"\d$", last_line)):
        return "phrase_sans_terminaison"
    return ""


def _completion_issue_reason(text: str) -> str:
    # Keep the historical empty-emphasis rule explicit in the orchestration
    # expression: repository structural gates verify this exact wiring.
    return (_detect_truncation(text)
            or (
                "empty_emphasis" if _b135_empty_emphasis(text) else ""
            )
            or ("pipeline_marker" if _b136_pipeline_marker(text) else ""))


def _repair_empty_emphasis_fragment(text: str) -> str:
    """Remove only the deterministic empty-emphasis fragment before retry.

    The continuation model cannot repair a missing clause while the literal
    ``Third, **.`` remains in the retained prefix. Removing that malformed
    fragment prevents a false RESOLVED status followed by a final re-flag.
    """
    t = str(text or "")
    t = re.sub(r"(?im)^\s*[^\n*]{0,80}\*\*\.\s*(?:\[SECT\.\s*REF\.\])?\s*$", "", t)
    t = re.sub(r"(?i)\b(?:first|second|third|fourth|premi[èe]rement|deuxi[èe]mement|troisi[èe]mement)[,:]?\s*\*\*\.\s*(?:\[SECT\.\s*REF\.\])?", "", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _completion_gate_outputs(outputs: Dict[str, Any],
                             lang: str = "fr") -> List[Dict[str, str]]:
    """Applique le gate à chaque sortie d'agent (in place) : marque les
    sections tronquées et retourne la liste des problèmes pour la bannière
    livrable + diagnostics. Fail-open : jamais d'exception."""
    issues: List[Dict[str, str]] = []
    mark = _TRUNC_MARK_FR if lang != "en" else _TRUNC_MARK_EN
    try:
        for key, val in list(outputs.items()):
            if not isinstance(val, str) or not val.strip():
                continue
            reason = _completion_issue_reason(val)
            if reason:
                outputs[key] = val.rstrip() + "\n\n" + mark
                issues.append({"section": str(key), "reason": reason})
    except Exception:
        pass
    return issues


def _clean_sc_text(text: str) -> str:
    t = re.sub(r"---JSON_START---[\s\S]*?---JSON_END---", "", text or "", flags=re.IGNORECASE)
    t = re.sub(r"---AUDIT_START---[\s\S]*?---AUDIT_END---", "", t, flags=re.IGNORECASE)
    # M6-A2.2 — bloc JSON_START / AUDIT_START ORPHELIN (tronqué, sans balise de fin,
    # ex. run dossier industriel (composants) JSON_START×2 / JSON_END×1) : purger du tag orphelin jusqu'à la
    # fin, sinon le JSON cassé fuit dans le CR métier final.
    t = re.sub(r"---JSON_START---[\s\S]*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"---AUDIT_START---[\s\S]*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def is_sc_output_valid(sc_output: str | None) -> bool:
    if not isinstance(sc_output, str):
        return False
    # M6-A2.2.1 — PRIORITÉ AU JSON STRUCTURÉ : si un JSON SC valide est présent, la
    # sortie est exploitable, indépendamment du score heuristique narratif (qui était
    # FR-biaisé et pouvait rejeter une sortie EN valide avant d'en consommer le JSON).
    if extract_sc_json(sc_output) is not None:
        return True
    t = _clean_sc_text(sc_output)
    if not t or len(t) < 500:
        return False
    low = t.lower()
    if low.startswith("{") and "provider" in low and "model" in low and "output" in low:
        return False
    required = ["[sc-1]", "[sc-2]", "[sc-3]", "[sc-4]", "[sc-5]"]
    if not all(x in low for x in required):
        return False
    # M6-A2.2.1 — KPI Supply Chain BILINGUES (FR + EN). Le set d'origine était FR-only
    # (couverture / bfr / cash immobil) → rejetait une narrative SC anglaise valide.
    _SC_KPI = [
        # FR
        "rotation", "otif", "service", "couverture", "bfr", "cash immobil",
        "stock", "délai", "fournisseur", "prévision", "rupture",
        # EN
        "coverage", "working capital", "cash tied", "cash conversion",
        "inventory", "lead time", "supplier", "forecast", "stockout",
        "moq", "s&op", "s&oe", "aged", "fill rate", "service level",
    ]
    kpi_hits = sum(1 for k in _SC_KPI if k in low)
    if kpi_hits < 4:
        return False
    return True


def _split_sc_source_text(text: str) -> list[str]:
    if not text:
        return []
    chunks = []
    for raw in re.split(r"[\n\r]+|(?<=[\.!?;:])\s+", text):
        line = re.sub(r"^[#\-*•✓\d\.)\s]+", "", raw or "").strip()
        line = re.sub(r"\|", " ", line)
        line = re.sub(r"\s+", " ", line)
        if len(line) >= 18:
            chunks.append(line)
    return chunks


def _pick_sc_clues(text: str, keywords: list[str], limit: int = 3, maxlen: int = 150) -> list[str]:
    """v16.5.28 — filtre les lignes 'format agenda' (sujets à traiter, pas des constats).
    Ex: 'Direction Supply Chain / Production' ou 'capacité de livraison et montée en charge'
    sans verbe d'action ou constat factuel → ignoré.
    """
    # Marqueurs de lignes "agenda" — titres de section ou sujets sans constat
    _AGENDA_PATTERNS = [
        r"^direction\s+(supply|finance|commerci|market|stratégi)",
        r"^(approvisionnements?|composants?|robots?|goulots?|délais?)\s*(/|et)\s*",
        r"^(disponibilité|dépendance|délai|capacité|montée en charge)\s*(de|des|et|/|$)",
        r"^(concentration|sécurisation|arbitrage entre|financement du|délais clients)\s*(client|pipe|passage|long|$)",
        r"^(rentabilité retrouvée|trésorerie à surveiller|bfr\s*/|investissements)\s*$",
    ]
    import re as _re
    _agenda_re = _re.compile("|".join(_AGENDA_PATTERNS), _re.IGNORECASE)

    out, seen = [], set()
    for line in _split_sc_source_text(text):
        low = line.lower()
        # Filtrer lignes format agenda (< 8 mots ET pas de verbe d'action/constat chiffré)
        words = line.split()
        if len(words) < 5 and not any(c.isdigit() for c in line):
            continue  # trop court sans chiffre = probablement un titre
        if _agenda_re.match(low):
            continue  # pattern agenda détecté
        if not any(k in low for k in keywords):
            continue
        key = low[:90]
        if key in seen:
            continue
        seen.add(key)
        out.append(line[:maxlen] + ("…" if len(line) > maxlen else ""))
        if len(out) >= limit:
            break
    return out



def _estimate_sc_scores(source_text: str) -> dict[str, Any]:
    low = (source_text or "").lower()
    service = 6
    stock = 6
    supplier = 6
    cash = 6

    if any(k in low for k in ["rupture", "penurie", "pénurie", "service", "otif", "disponibil"]):
        service -= 2
    if any(k in low for k in ["audit", "allocation", "pilotage", "sku critique", "sku priorit"]):
        service += 1

    if any(k in low for k in ["surstock", "obsol", "stock record", "rotation", "stocks eleves", "stocks élevés"]):
        stock -= 2
    if any(k in low for k in ["destockage", "déstockage", "liquidation", "reduire stocks", "réduire stocks"]):
        stock += 1

    if any(k in low for k in ["dependance", "dépendance", "asie", "chine", "fourn", "lead time", "mexique", "nearshoring", "dual sourcing"]):
        supplier -= 2
    if any(k in low for k in ["sourcing alternatif", "dual sourcing", "nearshoring", "mexique", "europe"]):
        supplier += 1

    if any(k in low for k in ["bfr", "cash", "dso", "creances", "créances", "tresorerie", "trésorerie"]):
        cash -= 2
    if any(k in low for k in ["liberer", "libérer", "cash libere", "cash libéré", "rotation stock"]):
        cash += 1

    def clamp(v: int) -> int:
        return max(3, min(8, int(v)))

    return {
        "service_level": clamp(service),
        "stock_management": clamp(stock),
        "supply_resilience": clamp(supplier),
        "cash_impact": clamp(cash),
        "scores_estimated": True,
    }


def _first_nonempty(items: list[str]) -> str:
    for x in items:
        if isinstance(x, str) and x.strip():
            return x.strip()
    return ""

def build_sc_context_brief(user_input: str | dict) -> str:
    data = normalize_user_input(user_input)
    parts = [
        data.get("company_name", ""),
        data.get("sector", ""),
        data.get("company_size", ""),
        data.get("geography", ""),
        data.get("operating_model", ""),
        data.get("business_context", ""),
        data.get("known_issues", ""),
        data.get("management_priorities", ""),
        data.get("kpi_data", ""),
        data.get("document_list", ""),
        data.get("special_watchpoints", ""),
    ]
    return "\n".join(str(x).strip() for x in parts if str(x).strip())


def _build_sc_kpis_fr(source_text: str) -> dict[str, str]:
    """v16.5.28 — détection sectorielle générique (automobile, aéro, retail, agroalimentaire, etc.)
    en plus des entreprises nommées. Scalable vers tout nouveau contexte.
    """
    low = (source_text or "").lower()

    # ── Entreprises nommées (priorité absolue) ────────────────────────────────
    if any(k in low for k in ["nike", "wholesale", "dtc", "outlet", "8,2 md$", "8.2 md$", "8,3 md$", "8.3 md$", "sneakers", "sportswear"]):
        return {
            "rotation_stock": "3.8x → cible 4.5x [ESTIM. IA — sportswear DTC]",
            "service_level":  ">95% cible [REF SECT.]",
            "stock_coverage": "élevée sur textile / trop faible sur icôniques [ESTIM. IA]",
            "bfr_impact":     "pression élevée — cash immobilisé dans le surstock [ESTIM. IA]",
        }
    if any(k in low for k in ["til-ch", "groupe seb", "professional", "floor care", "cookware", "linen care"]):
        return {
            "rotation_stock": "45-75j équivalent stock [REF SECT. — PED multi-marques]",
            "service_level":  ">95% cible [REF SECT.]",
            "stock_coverage": "à sécuriser sur SKU critiques [ESTIM. IA]",
            "bfr_impact":     "BFR sous tension — réduction stocks prioritaire [ESTIM. IA]",
        }
    if any(k in low for k in ["stellantis", "boeing", "airbus", "737", "787", "spirit aerosystems"]):
        return {
            "rotation_stock": "production pilotée sur cadences [ESTIM. IA — industriel lourd]",
            "service_level":  "OTIF >98% contrats client [REF SECT. — aéro/auto]",
            "stock_coverage": "composants critiques : couverture 4-8 semaines [REF SECT.]",
            "bfr_impact":     "BFR lié aux en-cours production et stocks WIP [ESTIM. IA]",
        }

    # ── Détection sectorielle générique ──────────────────────────────────────
    # Automobile
    if any(k in low for k in ["automobile", "véhicule", "vehicule", "concessionnaire", "jours d'inventaire", "takt time", "usine d'assemblage"]):
        return {
            "rotation_stock": "45-60j cible (JIT) [REF SECT. — automobile]",
            "service_level":  "OTIF >97% [REF SECT. — standard OEM]",
            "stock_coverage": "surstock si >60j — cible 30-45j [REF SECT.]",
            "bfr_impact":     "stocks en jours de production — impact FCF direct [ESTIM. IA]",
        }
    # Aéronautique / défense
    if any(k in low for k in ["aéronautique", "aeronautique", "airbus", "safran", "thales", "défense", "composite", "pièce d'aéronef", "aéronef"]):
        return {
            "rotation_stock": "rotation longue — composants sur programme 5-10 ans [REF SECT.]",
            "service_level":  "OTIF >98% [REF SECT. — contrats aéro]",
            "stock_coverage": "composants critiques : 6-16 semaines [REF SECT. — aéro]",
            "bfr_impact":     "BFR élevé structurel (avances clients partielles) [ESTIM. IA]",
        }
    # Agroalimentaire / emballage
    # Retail / distribution — avant agroalim (e-commerce capturé ici)
    if any(k in low for k in ["retail", "grande distribution", "supermarché", "magasin", "e-commerce", "marketplace", "omnicanal"]):
        return {
            "rotation_stock": "5-10x/an [REF SECT. — retail alim. 20x+, non-alim 4-6x]",
            "service_level":  "taux de service linéaire >98% [REF SECT. — grande distrib.]",
            "stock_coverage": "3-6 semaines non-alim / 1-2 semaines alim [REF SECT.]",
            "bfr_impact":     "BFR alimenté par rotations rapides — sensible aux ruptures [ESTIM. IA]",
        }
    # Agroalimentaire / emballage — "natures" supprimé (collision avec NatureWorks)
    if any(k in low for k in ["agroalimentaire", "agro-alimentaire", "emballage", "pla", "pet", "bioplastique", "novamont", "fournisseur matière", "matière biosourcée"]):
        return {
            "rotation_stock": "rotation rapide 4-8x/an [REF SECT. — agroalimentaire]",
            "service_level":  ">96-97% taux de service livraison [REF SECT.]",
            "stock_coverage": "matière première : 4-10 semaines cible [REF SECT.]",
            "bfr_impact":     "BFR sensible aux délais fournisseurs matière [ESTIM. IA]",
        }
    # Pharmaceutique / santé
    if any(k in low for k in ["pharmaceu", "médicament", "medicament", "dispositif médical", "laboratoire", "fda", "ema", "gmp"]):
        return {
            "rotation_stock": "rotation contrainte par réglementation [REF SECT. — pharma]",
            "service_level":  ">99,5% taux de service [REF SECT. — obligation santé publique]",
            "stock_coverage": "stock sécurité réglementaire 2-4 mois [REF SECT.]",
            "bfr_impact":     "BFR structurel élevé (stocks réglementaires) [ESTIM. IA]",
        }
    # PME / générique
    return {
        "rotation_stock": "3.5x – cible 4.5x [ESTIM. IA]",
        "service_level":  ">95% cible [REF SECT.]",
        "stock_coverage": "8 semaines vs cible 5 [ESTIM. IA]",
        "bfr_impact":     "pression BFR — stocks et créances à surveiller [ESTIM. IA]",
    }


_SC_FALLBACK_EN = [
    # En-têtes / structure
    ("MODE BRIEFING — FALLBACK HEURISTIQUE (rôle SC indisponible sur ce run)",
     "BRIEFING MODE — HEURISTIC FALLBACK (SC role unavailable on this run)"),
    ("[SC-1] DIAGNOSTIC", "[SC-1] DIAGNOSIS"),
    ("[SC-2] KPIs IDENTIFIES [REF SECT.]", "[SC-2] IDENTIFIED KPIs [SECT. REF.]"),
    ("Taux de service cible : >95% [REF SECT. - standard PED]",
     "Target service level: >95% [SECT. REF. - PED standard]"),
    ("Stock days : 45-75j [REF SECT. - distribution multi-marques]",
     "Stock days: 45-75d [SECT. REF. - multi-brand distribution]"),
    ("OTIF : >92% [REF SECT. - benchmark industrie]",
     "OTIF: >92% [SECT. REF. - industry benchmark]"),
    ("KPIs reels a collecter en priorite avant decision.",
     "Actual KPIs to collect before decision."),
    ("[SC-3] RISQUES OPÉRATIONNELS", "[SC-3] OPERATIONAL RISKS"),
    ("[SC-4] ARBITRAGES CODIR", "[SC-4] CODIR TRADE-OFFS"),
    ("[SC-4b] ACTIONS 0-30 JOURS", "[SC-4b] ACTIONS 0-30 DAYS"),
    ("[SC-5] DÉCISIONS PROPOSÉES AU DG", "[SC-5] DECISIONS PROPOSED TO CEO"),
    ("⚠️ Note : analyse SC construite en fallback heuristique (provider indisponible). "
     "Scores estimés [ESTIM. IA] — à challenger avec les données terrain. "
     "Lancer une nouvelle session CoDIR avec supply chain disponible pour une analyse complète.",
     "⚠️ Note: SC analysis built through heuristic fallback (provider unavailable). "
     "Estimated scores [AI ESTIM.] — to be challenged with field data. "
     "Re-run a CoDIR session with the supply chain provider available for a full analysis."),
    # Diagnostic / risques / arbitrages / actions par défaut
    ("La matière disponible confirme un sujet supply chain à traiter au niveau CoDIR, "
     "avec des impacts potentiels sur le service, les stocks, le cash et la marge.",
     "Available material confirms a supply chain topic to review at CoDIR level, "
     "with potential impact on service, inventory, cash and margin."),
    ("Les éléments disponibles ne suffisent pas pour établir des KPI fiables, mais ils "
     "justifient une revue rapprochée des prévisions, de la disponibilité produit et du BFR.",
     "Available evidence is insufficient to establish reliable KPIs, but supports a close "
     "review of forecasts, product availability and working capital."),
    ("Risque de désalignement entre niveau de stock, disponibilité produit et objectifs de cash à court terme.",
     "Risk of misalignment between inventory levels, product availability and short-term cash objectives."),
    ("Risque de tension opérationnelle si les hypothèses commerciales et financières ne sont pas recalées avec les contraintes d'exécution.",
     "Risk of operational tension if commercial and financial assumptions are not reconciled with execution constraints."),
    ("Arbitrer explicitement entre niveau de service, discipline de stock, protection de marge et sécurisation du cash.",
     "Explicitly arbitrate between service level, inventory discipline, margin protection and cash preservation."),
    ("Prioriser les références, flux ou zones géographiques critiques avant toute accélération commerciale supplémentaire.",
     "Prioritise critical SKUs, flows or geographic areas before any further commercial acceleration."),
    ("Mettre en place un pilotage hebdomadaire stocks / disponibilité / cash sur les références critiques.",
     "Set up weekly stock / availability / cash steering on critical SKUs."),
    ("Recaler les hypothèses de demande et de pricing avec Finance et Commerce avant les prochains arbitrages DG.",
     "Reconcile demand and pricing assumptions with Finance and Sales before the next CEO trade-offs."),
    ("Identifier les points de fragilité logistique ou fournisseurs nécessitant un plan de contingence court terme.",
     "Identify logistics or supplier weak points requiring a short-term contingency plan."),
    ("La supply chain nécessite une revue urgente des stocks, du taux de service et du BFR "
     "avant la prochaine publication financière.",
     "The supply chain requires an urgent review of inventory, service level and working capital "
     "before the next financial release."),
    # Décisions
    ("DÉCISION 1 RECOMMANDÉE : Audit express stocks et disponibilité sur références critiques "
     "— responsable SC + Finance — avant J+7",
     "RECOMMENDED DECISION 1: Rapid inventory & availability audit on critical SKUs "
     "— SC + Finance lead — within 7 days"),
    ("DÉCISION 2 À TRANCHER : Arbitrer service client vs réduction BFR — impact cash estimé "
     "à quantifier en séance",
     "DECISION 2 TO ARBITRATE: Customer service vs working-capital reduction — estimated cash "
     "impact to be quantified in session"),
    ("DÉCISION 3 RECOMMANDÉE : Piloter hebdomadairement stocks / disponibilité / cash sur "
     "SKU prioritaires — DSC — dès J+3",
     "RECOMMENDED DECISION 3: Weekly stock / availability / cash steering on priority SKUs "
     "— SC lead — from day 3"),
    # Données deck (JSON payload)
    ("Couverture stock : ", "Stock coverage: "),
    ("Taux de service cible : ", "Target service level: "),
    ("BFR : ", "Working capital: "),
    ("Dépendances géographiques / fournisseurs", "Geographic / supplier dependencies"),
    ("Exposition tarifs, forex, délais", "Exposure to tariffs, forex, lead times"),
    ("Service client >95% vs réduction stocks", "Customer service >95% vs inventory reduction"),
    ("Vitesse exécution vs maîtrise des coûts supply", "Execution speed vs supply cost control"),
    ("Audit express situation SC — DSC — avant J+7", "Rapid SC situation audit — SC lead — within 7 days"),
    ("Lancer pilotage hebdo stocks/cash/service", "Launch weekly stock/cash/service steering"),
    ("Plan correctif structurel sur risque principal identifié",
     "Structural corrective plan on the main identified risk"),
    ("Programme résilience supply chain long terme", "Long-term supply chain resilience programme"),
    ('"probability": "moyenne"', '"probability": "medium"'),
    ('"probability": "élevée"', '"probability": "high"'),
    ('"probability": "faible"', '"probability": "low"'),
    # Données deck — variante _build_sc_fallback_json (non accentuée + composants)
    ("Supply chain sous tension — BFR et disponibilité produit à piloter en urgence",
     "Supply chain under pressure — working capital and product availability require urgent steering"),
    ("Impact BFR et disponibilité produit — pression BFR — stocks et créances à surveiller",
     "Working-capital & product-availability impact — working-capital pressure — inventory and receivables to monitor"),
    ("BFR et disponibilité produit à piloter en urgence",
     "working capital and product availability require urgent steering"),
    ("Audit express stocks et disponibilite sur references critiques",
     "Rapid inventory & availability audit on critical SKUs"),
    ("Pilotage hebdomadaire stocks/disponibilite/cash sur SKU prioritaires",
     "Weekly stock/availability/cash steering on priority SKUs"),
    ("Pilotage hebdomadaire stocks/disponibilite/DSO sur references prioritaires",
     "Weekly stock/availability/DSO steering on priority SKUs"),
    ("DECISION 1 RECOMMANDEE : ", "RECOMMENDED DECISION 1: "),
    ("DECISION 2 A TRANCHER : ", "DECISION 2 TO ARBITRATE: "),
    ("DECISION 3 RECOMMANDEE : ", "RECOMMENDED DECISION 3: "),
    ("DSC+Finance — avant J+7", "SC+Finance — within 7 days"),
    ("DSC — des J+3", "SC — from day 3"),
    ("DSC — dès J+3", "SC — from day 3"),
    ("references critiques", "critical SKUs"),
    ("Pilotage hebdomadaire", "Weekly steering"),
    ("pression BFR", "working-capital pressure"),
    ("stocks et créances à surveiller", "inventory and receivables to monitor"),
    ("disponibilité produit", "product availability"),
    ("disponibilité", "availability"),
    ("disponibilite", "availability"),
    # KPI sectoriels atomiques (build_sc_kpis — inventaire exhaustif brute-forcé)
    ("élevée sur textile / trop faible sur icôniques", "high on apparel / too low on icons"),
    ("pression élevée — cash immobilisé dans le surstock", "high pressure — cash tied up in overstock"),
    ("à sécuriser sur SKU critiques", "to secure on critical SKUs"),
    ("BFR sous tension — réduction stocks prioritaire", "working capital under pressure — inventory reduction priority"),
    ("production pilotée sur cadences", "production driven by takt rates"),
    ("OTIF >98% contrats client", "OTIF >98% customer contracts"),
    ("composants critiques : couverture 4-8 semaines", "critical components: 4-8 weeks coverage"),
    ("composants critiques : 6-16 semaines", "critical components: 6-16 weeks"),
    ("BFR lié aux en-cours production et stocks WIP", "working capital tied to WIP and production in progress"),
    ("surstock si >60j — cible 30-45j", "overstock if >60d — target 30-45d"),
    ("stocks en jours de production — impact FCF direct", "inventory in production days — direct FCF impact"),
    ("rotation longue — composants sur programme 5-10 ans", "long turnover — components on 5-10 year programmes"),
    ("BFR élevé structurel (avances clients partielles)", "high structural working capital (partial customer advances)"),
    ("taux de service linéaire >98%", "shelf service level >98%"),
    ("BFR alimenté par rotations rapides — sensible aux ruptures", "working capital driven by fast turns — sensitive to stockouts"),
    ("matière première : 4-10 semaines cible", "raw materials: 4-10 weeks target"),
    ("BFR sensible aux délais fournisseurs matière", "working capital sensitive to raw-material supplier lead times"),
    ("rotation contrainte par réglementation", "turnover constrained by regulation"),
    (">99,5% taux de service", ">99.5% service level"),
    ("stock sécurité réglementaire 2-4 mois", "regulatory safety stock 2-4 months"),
    ("BFR structurel élevé (stocks réglementaires)", "high structural working capital (regulatory inventory)"),
    ("pression BFR — stocks et créances à surveiller", "working-capital pressure — inventory and receivables to monitor"),
    ("rotation rapide 4-8x/an", "fast turnover 4-8x/yr"),
    (">96-97% taux de service livraison", ">96-97% delivery service level"),
    ("45-60j cible (JIT)", "45-60d target (JIT)"),
    ("45-75j équivalent stock", "45-75d stock equivalent"),
    ("3-6 semaines non-alim / 1-2 semaines alim", "3-6 weeks non-food / 1-2 weeks food"),
    ("3.8x → cible 4.5x", "3.8x → target 4.5x"),
    ("3.5x – cible 4.5x", "3.5x – target 4.5x"),
    ("8 semaines vs cible 5", "8 weeks vs target 5"),
    ("5-10x/an", "5-10x/yr"),
    ("retail alim. 20x+, non-alim 4-6x", "food retail 20x+, non-food 4-6x"),
    # Tags sectoriels
    ("[REF SECT. — PED multi-marques]", "[SECT. REF. — multi-brand SDA]"),
    ("[REF SECT. — standard OEM]", "[SECT. REF. — OEM standard]"),
    ("[REF SECT. — automobile]", "[SECT. REF. — automotive]"),
    ("[REF SECT. — contrats aéro]", "[SECT. REF. — aero contracts]"),
    ("[REF SECT. — aéro/auto]", "[SECT. REF. — aero/auto]"),
    ("[REF SECT. — aéro]", "[SECT. REF. — aero]"),
    ("[REF SECT. — grande distrib.]", "[SECT. REF. — mass retail]"),
    ("[REF SECT. — agroalimentaire]", "[SECT. REF. — food & beverage]"),
    ("[REF SECT. — pharma]", "[SECT. REF. — pharma]"),
    ("[REF SECT. — obligation santé publique]", "[SECT. REF. — public-health obligation]"),
    ("[ESTIM. IA — sportswear DTC]", "[AI ESTIM. — sportswear DTC]"),
    ("[ESTIM. IA — industriel lourd]", "[AI ESTIM. — heavy industry]"),
    ("[ESTIM. IA — industriel]", "[AI ESTIM. — industrial]"),
    # Jetons résiduels SC (après les phrases complètes)
    (" cible", " target"),
    ("semaines", "weeks"),
    (" mois", " months"),
    # Derniers résidus (risque SC + ligne debug JSON)
    ("Arbitrer taux service >95% vs reduction stocks cible — impact cash liberable a quantifier en seance",
     "Arbitrate service level >95% vs target inventory reduction — releasable cash impact to quantify in session"),
    ("Arbitrer taux service vs reduction BFR — impact cash a quantifier en seance",
     "Arbitrate service level vs working-capital reduction — cash impact to quantify in session"),
    ("Désalignement stock/service/cash", "stock/service/cash misalignment"),
    ("JSON fallback contextuel — situation:", "Contextual JSON fallback — situation:"),
    ("scores différenciés", "differentiated scores"),
    ("situation: generique", "situation: generic"),
    ("situation: générique", "situation: generic"),
    # Génériques (en dernier)
    ("[ESTIM. IA — fallback]", "[AI ESTIM. — fallback]"),
    ("[ESTIM. IA]", "[AI ESTIM.]"),
    ("[REF SECT.", "[SECT. REF."),
]


def _loc_sc_fallback(text: str, lang: str = "fr") -> str:
    """M.5.10.12 — localise À LA SOURCE le fallback SC heuristique (narratif + JSON
    deck) sur la chaîne complète, avant toute écriture DOCX/PPTX. Whole-string :
    pas de découpage en runs → pas d'hybrides FR/EN. No-op hors EN."""
    if not isinstance(text, str) or (lang or "fr").lower() != "en":
        return text
    for fr, en in _SC_FALLBACK_EN:
        text = text.replace(fr, en)
    return text



def build_sc_kpis(source_text: str, lang: str = "fr") -> dict[str, str]:
    """M.5.10.15 — KPI SC sectoriels. FR par défaut ; EN localisé sur les valeurs
    atomiques (table verrouillée par test) quand lang == 'en'."""
    d = _build_sc_kpis_fr(source_text)
    if (lang or "fr").lower() == "en":
        return {k: _loc_sc_fallback(v, "en") for k, v in d.items()}
    return d


def build_sc_fallback_narrative(user_input: str | dict, finance_output: str, lang: str = "fr") -> str:
    """Fallback SC quand GPT-5.4 échoue.
    v16.5.28 : fallback SC contextuel, isolé du contexte Finance par défaut, avec KPI obligatoires et décisions DG structurées.
    """
    user_data = normalize_user_input(user_input)
    # v16.5.23 : priority_questions EXCLU du corpus — contient des questions, pas des actions
    brief_text = "\n".join([
        user_data.get("business_context", ""),
        user_data.get("known_issues", ""),
        user_data.get("management_priorities", ""),
        user_data.get("kpi_data", ""),
        # NB : priority_questions délibérément exclu — ses verbes d'action (lancer, mettre en place)
        # appartiennent aux QUESTIONS du brief, pas aux recommandations SC
    ]).strip()
    # Cross-ref Finance : signaux BFR/stocks souvent présents dans la section finance
    source_text = "\n".join([brief_text, finance_output or ""])

    diag = _pick_sc_clues(source_text, [
        "supply chain", "stock", "stocks", "logistique", "disponibil", "prevision", "prévision",
        "til-ch", "bfr", "cash", "marge", "service", "sku", "fourn", "tarif", "pricing",
        "otif", "taux de service", "rotation", "rupture", "surstock"
    ], limit=3)
    risks = _pick_sc_clues(source_text, [
        "risque", "rupture", "surstock", "obsol", "retard", "fourn", "tarif", "devise", "til-ch",
        "disponibil", "dépendance", "dependance", "exposition", "volatil"
    ], limit=3)
    arbitrages = _pick_sc_clues(source_text, [
        "arbitrage", "cash", "marge", "service", "stock", "pricing", "volume", "bfr", "libérer"
    ], limit=2)
    # v16.5.23 : actions extraites uniquement depuis management_priorities et known_issues,
    # jamais depuis priority_questions
    actions_source = "\n".join([
        user_data.get("known_issues", ""),
        user_data.get("management_priorities", ""),
        finance_output or "",
    ])
    actions = _pick_sc_clues(actions_source, [
        "réduire", "reduire", "sécuriser", "securiser", "piloter", "optimiser",
        "renforcer", "accélérer", "accelerer", "geler", "mettre en place",
        "dual sourcing", "nearshoring", "plateforme", "til-ch"
    ], limit=3)

    if not diag:
        diag = [
            "La matière disponible confirme un sujet supply chain à traiter au niveau CoDIR, avec des impacts potentiels sur le service, les stocks, le cash et la marge.",
            "Les éléments disponibles ne suffisent pas pour établir des KPI fiables, mais ils justifient une revue rapprochée des prévisions, de la disponibilité produit et du BFR.",
        ]
    if not risks:
        risks = [
            "Risque de désalignement entre niveau de stock, disponibilité produit et objectifs de cash à court terme.",
            "Risque de tension opérationnelle si les hypothèses commerciales et financières ne sont pas recalées avec les contraintes d'exécution.",
        ]
    if not arbitrages:
        arbitrages = [
            "Arbitrer explicitement entre niveau de service, discipline de stock, protection de marge et sécurisation du cash.",
            "Prioriser les références, flux ou zones géographiques critiques avant toute accélération commerciale supplémentaire.",
        ]
    if not actions:
        actions = [
            "Mettre en place un pilotage hebdomadaire stocks / disponibilité / cash sur les références critiques.",
            "Recaler les hypothèses de demande et de pricing avec Finance et Commerce avant les prochains arbitrages DG.",
            "Identifier les points de fragilité logistique ou fournisseurs nécessitant un plan de contingence court terme.",
        ]

    msg_dg = diag[0] if diag else (
        "La supply chain nécessite une revue urgente des stocks, du taux de service et du BFR "
        "avant la prochaine publication financière. [ESTIM. IA — fallback]"
    )

    # v16.5.23 — SC-5 format décisions (3 décisions formulées même en fallback)
    sc5_decisions = [
        "DÉCISION 1 RECOMMANDÉE : Audit express stocks et disponibilité sur références critiques "
        "— responsable SC + Finance — avant J+7 [ESTIM. IA — fallback]",
        "DÉCISION 2 À TRANCHER : Arbitrer service client vs réduction BFR — impact cash estimé "
        "à quantifier en séance [ESTIM. IA — fallback]",
        "DÉCISION 3 RECOMMANDÉE : Piloter hebdomadairement stocks / disponibilité / cash sur "
        "SKU prioritaires — DSC — dès J+3 [ESTIM. IA — fallback]",
    ]

    _out = (
        "MODE BRIEFING — FALLBACK HEURISTIQUE (rôle SC indisponible sur ce run)\n"
        "[SC-1] DIAGNOSTIC\n"
        + "\n".join(f"- {x}" for x in diag[:3])
        + "\n[SC-2] KPIs IDENTIFIES [REF SECT.]\n"
        "- Taux de service cible : >95% [REF SECT. - standard PED]\n"
        "- Stock days : 45-75j [REF SECT. - distribution multi-marques]\n"
        "- OTIF : >92% [REF SECT. - benchmark industrie]\n"
        "- KPIs reels a collecter en priorite avant decision."
        + "\n\n[SC-3] RISQUES OPÉRATIONNELS\n"
        + "\n".join(f"- {x}" for x in risks[:3])
        + "\n\n[SC-4] ARBITRAGES CODIR\n"
        + "\n".join(f"- {x}" for x in arbitrages[:2])
        + "\n\n[SC-4b] ACTIONS 0-30 JOURS\n"
        + "\n".join(f"- {x}" for x in actions[:3])
        + "\n\n[SC-5] DÉCISIONS PROPOSÉES AU DG\n"
        + "\n".join(sc5_decisions)
        + "\n\n⚠️ Note : analyse SC construite en fallback heuristique (provider indisponible). "
        "Scores estimés [ESTIM. IA] — à challenger avec les données terrain. "
        "Lancer une nouvelle session CoDIR avec supply chain disponible pour une analyse complète."
        # v16.5.28 — JSON fallback contextuel via build_sc_kpis()
        + _build_sc_fallback_json(source_text, lang)
    )
    return _loc_sc_fallback(_out, lang)


_SC_SUMMARIES_EN = {
    "crise_qualite":     "Supply chain in quality crisis — production suspension and compliance to be restored urgently [AI ESTIM.]",
    "surstock_critique": "Supply chain hit by record overstock — urgent destocking and cash reallocation are priorities [AI ESTIM.]",
    "rupture_fournisseur": "Supply chain under pressure — critical supplier disruption, alternative sourcing to activate immediately [AI ESTIM.]",
    "cash_critique":     "Supply chain under major cash pressure — working capital and cash burn to control as absolute priority [AI ESTIM.]",
    "bfr_tension":       "Supply chain under working-capital pressure — inventory and product availability require urgent steering [AI ESTIM.]",
    "dependance_critique": "Supply chain weakened by critical dependencies — dual sourcing and resilience to build [AI ESTIM.]",
    "croissance_saine":  "Healthy supply chain in growth — capacity ramp-up and supplier robustness to anticipate [AI ESTIM.]",
    "generique":         "Supply chain under pressure — working capital and product availability require urgent steering [AI ESTIM.]",
}


def build_sc_scores(source_text: str, lang: str = "fr") -> dict:
    """v16.5.28 — Scores SC contextuels pour le fallback.
    Analyse les signaux du brief pour produire des scores différenciés.
    Boeing (crise FAA) ≠ BREIZHPack (rupture PLA) ≠ Nike (surstock) ≠ CORIOLIS (croissance saine).

    Retourne: {service_level, stock_management, supply_resilience, cash_impact, global_status,
               situation_type, executive_summary}
    """
    low = (source_text or "").lower()

    # ── Détecteurs de signaux ────────────────────────────────────────────────
    # Crise qualité critique (Boeing/aéro/pharma/médical)
    sig_qualite_critique = any(k in low for k in [
        "faa", "non-conformit", "non conformit", "suspension production",
        "inspection", "airworthiness", "defaut qualite", "défaut qualité",
        "rappel produit", "recall", "zero tolerance", "tolérance zéro",
        "certification suspendu", "audit qualité obligatoire",
    ])
    # Surstock majeur (Nike, Stellantis, auto)
    sig_surstock_majeur = any(k in low for k in [
        "stock record", "surstock", "115 jours", "100 jours",
        "8,3 md", "8.3 md", "8 milliard", "jours d'inventaire",
        "jours stock", "destockage", "déstockage", "liquidation stock",
        "écoulement stock", "stock excessif",
    ])
    # Rupture fournisseur ACTIVE (événement en cours) — déclencheur fort
    sig_rupture_fourn = any(k in low for k in [
        "force majeure", "rupture fournisseur", "incendie site",
        "approvisionnement réduit", "pénurie composant", "penurie composant",
        "fournisseur critique défaillant", "lead time critique",
        "semi-conducteur pénurie", "batterie pénurie", "livraison interrompue",
    ])
    # Dépendance critique (risque latent, pas rupture active) — déclencheur modéré
    sig_dependance_critique_source = any(k in low for k in [
        "source unique", "single source", "dual sourcing absent",
        "mono-source", "monosource",
    ])
    # BFR / cash critique
    sig_cash_critique = any(k in low for k in [
        "cash burn", "fcf négatif", "fcf negatif", "free cash flow négatif",
        "trésorerie nette <1", "tresorerie <1", "covenant", "runway",
        "liquidités <", "liquidites <", "-5 md", "-8 md", "-10 md",
        "cessation de paiement", "restructuration dette",
    ])
    # BFR sous tension (modéré)
    sig_bfr_tension = any(k in low for k in [
        "bfr", "besoin en fonds de roulement", "cash immobilisé",
        "cash immobilise", "trésorerie sous tension", "dso élevé",
        "délai paiement", "delai paiement", "stocks élevés", "stocks eleves",
        "bfr en hausse", "bfr tendu",
    ])
    # Dépendance géographique forte
    sig_dependance = any(k in low for k in [
        "dépendance asie", "dependance asie", "concentration fournisseur",
        "70% fourni par", "80% sourcing", "asie 80", "chine 70",
        "single sourcing", "fournisseur unique",
        "dépendance airbus", "dependance airbus",
    ])
    # Taux de service dégradé explicitement
    sig_service_degrade = any(k in low for k in [
        "91,3%", "91.3%", "88%", "89%", "90%",
        "service dégradé", "service degrade", "livraison en retard",
        "retards livraison", "rupture de stock client",
        "otif <90", "taux de service <92",
    ])
    # Croissance saine / pas de signal critique
    sig_croissance_saine = any(k in low for k in [
        "croissance rentable", "+30%", "+35%", "croissance 30",
        "rentabilité retrouvée", "trésorerie positive", "carnet de commandes solide",
    ]) and not (sig_qualite_critique or sig_surstock_majeur or sig_rupture_fourn or sig_cash_critique)
    # Si croissance saine mais dépendance critique latente → dependance_critique, pas sain
    if sig_croissance_saine and sig_dependance_critique_source:
        sig_croissance_saine = False

    # ── Calcul des scores ────────────────────────────────────────────────────
    # service_level (0-10)
    if sig_qualite_critique:
        svc = 3   # crise qualité = service très dégradé
    elif sig_service_degrade:
        svc = 4   # taux de service connu et mauvais
    elif sig_rupture_fourn:
        svc = 5   # rupture = risque service
    elif sig_surstock_majeur:
        svc = 6   # surstock ≠ mauvais service mais risque disponibilité
    elif sig_croissance_saine:
        svc = 7
    else:
        svc = 6   # défaut

    # stock_management (0-10)
    if sig_surstock_majeur:
        stk = 2   # surstock record = très mauvaise gestion stock
    elif sig_rupture_fourn:
        stk = 3   # rupture active = risque stock imminente
    elif sig_qualite_critique:
        stk = 4   # suspension production = gestion stock perturbée
    elif sig_bfr_tension:
        stk = 4   # BFR tendu = stocks trop élevés
    elif sig_dependance_critique_source:
        stk = 5   # dépendance latente, pas de rupture active
    elif sig_croissance_saine:
        stk = 7
    else:
        stk = 5

    # supply_resilience (0-10)
    if sig_qualite_critique:
        res = 2   # crise qualité = fragilité majeure supply
    elif sig_rupture_fourn:
        res = 3   # rupture active = résilience effondrée
    elif sig_dependance or sig_dependance_critique_source:
        res = 4   # dépendance identifiée (latente ou géographique)
    elif sig_surstock_majeur:
        res = 5   # surstock = supply OK mais mal pilotée
    elif sig_croissance_saine:
        res = 7
    else:
        res = 5

    # cash_impact (0-10)
    if sig_cash_critique:
        csh = 2   # cash burn / FCF négatif majeur
    elif sig_bfr_tension and sig_surstock_majeur:
        csh = 3   # double pression cash
    elif sig_bfr_tension or sig_surstock_majeur:
        csh = 4   # une source de pression cash
    elif sig_rupture_fourn:
        csh = 5   # rupture = surcoûts potentiels
    elif sig_croissance_saine:
        csh = 7
    else:
        csh = 5

    # ── global_status ────────────────────────────────────────────────────────
    scores_avg = (svc + stk + res + csh) / 4
    if sig_qualite_critique or sig_cash_critique or scores_avg < 3.5:
        status = "critique"
    elif sig_surstock_majeur or sig_rupture_fourn or scores_avg < 4.5:
        status = "degrade"
    elif sig_bfr_tension or sig_dependance or sig_service_degrade or scores_avg < 6:
        status = "sous_tension"
    else:
        status = "sain"

    # ── Situation type → décisions contextuelles ─────────────────────────────
    if sig_qualite_critique:
        situation_type = "crise_qualite"
    elif sig_surstock_majeur:
        situation_type = "surstock_critique"
    elif sig_rupture_fourn:
        situation_type = "rupture_fournisseur"
    elif sig_cash_critique:
        situation_type = "cash_critique"
    elif sig_bfr_tension:
        situation_type = "bfr_tension"
    elif sig_dependance or sig_dependance_critique_source:
        situation_type = "dependance_critique"
    elif sig_croissance_saine:
        situation_type = "croissance_saine"
    else:
        situation_type = "generique"

    # ── Executive summary contextuel ─────────────────────────────────────────
    summaries = {
        "crise_qualite":     "Supply chain en crise qualité — suspension production et conformité à rétablir en urgence [ESTIM. IA]",
        "surstock_critique": "Supply chain dégradée par un surstock record — déstockage urgent et réallocation cash prioritaires [ESTIM. IA]",
        "rupture_fournisseur": "Supply chain sous tension — rupture fournisseur critique, sourcing alternatif à activer immédiatement [ESTIM. IA]",
        "cash_critique":     "Supply chain sous pression cash majeure — BFR et cash burn à maîtriser en priorité absolue [ESTIM. IA]",
        "bfr_tension":       "Supply chain sous tension BFR — stocks et disponibilité produit à piloter en urgence [ESTIM. IA]",
        "dependance_critique": "Supply chain fragilisée par des dépendances critiques — dual sourcing et résilience à construire [ESTIM. IA]",
        "croissance_saine":  "Supply chain saine en croissance — montée en capacité et robustesse fournisseurs à anticiper [ESTIM. IA]",
        "generique":         "Supply chain sous tension — BFR et disponibilité produit à piloter en urgence [ESTIM. IA]",
    }

    return {
        "service_level":    svc,
        "stock_management": stk,
        "supply_resilience": res,
        "cash_impact":      csh,
        "global_status":    status,
        "situation_type":   situation_type,
        "executive_summary": (_SC_SUMMARIES_EN if (lang or "fr").lower() == "en" else summaries)[situation_type],
    }


# Table de décisions contextuelles selon situation_type
_SC_FALLBACK_DECISIONS = {
    "crise_qualite": [
        "DECISION 1 RECOMMANDEE : Cellule crise qualite quotidienne DSC+COO — cartographier composants non conformes et suspendre livraisons impactees — avant J+3 [ESTIM. IA]",
        "DECISION 2 A TRANCHER : Maintenir cadences vs suspension selective productions non conformes — impact cash et penalites clients a quantifier [ESTIM. IA]",
        "DECISION 3 RECOMMANDEE : Plan audit qualite 100% sur references critiques — DSC+Qualite — livrable J+30 [ESTIM. IA]",
    ],
    "surstock_critique": [
        "DECISION 1 RECOMMANDEE : Plan destockage urgent — identifier top 20% SKU surstock (volume et age) — DAF+DSC — avant J+7 [ESTIM. IA]",
        "DECISION 2 A TRANCHER : Destockage promotionnel vs cession canal outlet vs reduction cadences — arbitrage marge/image/cash [ESTIM. IA]",
        "DECISION 3 RECOMMANDEE : Gel commandes fournisseurs sur categories en surstock >60j — DSC — immediat [ESTIM. IA]",
    ],
    "rupture_fournisseur": [
        "DECISION 1 RECOMMANDEE : Activer fournisseur alternatif qualifie — DSC — avant J+3 meme si surchef +15-20% [ESTIM. IA]",
        "DECISION 2 A TRANCHER : Stock securite 10 semaines vs 6 semaines actuelles — arbitrage cash immobilise vs risque rupture client [ESTIM. IA]",
        "DECISION 3 RECOMMANDEE : Cartographier top 10 composants critiques source unique et lancer dual sourcing — DSC — J+30 [ESTIM. IA]",
    ],
    "cash_critique": [
        "DECISION 1 RECOMMANDEE : Revue tresorerie quotidienne — DAF+DSC — visibilite cash 90j — avant J+3 [ESTIM. IA]",
        "DECISION 2 A TRANCHER : Reduire BFR stocks -X M€ vs maintien service client — arbitrage a chiffrer en seance DG [ESTIM. IA]",
        "DECISION 3 RECOMMANDEE : Geler commandes fournisseurs non critiques et reporter CAPEX — DAF — immediat [ESTIM. IA]",
    ],
    "bfr_tension": [
        "DECISION 1 RECOMMANDEE : Audit express stocks et BFR — DSC+DAF — chiffrer cash immobilise par famille de produit — avant J+7 [ESTIM. IA]",
        "DECISION 2 A TRANCHER : Arbitrer taux service >95% vs reduction stocks cible — impact cash liberable a quantifier en seance [ESTIM. IA]",
        "DECISION 3 RECOMMANDEE : Pilotage hebdomadaire stocks/disponibilite/DSO sur references prioritaires — DSC — des J+3 [ESTIM. IA]",
    ],
    "dependance_critique": [
        "DECISION 1 RECOMMANDEE : Cartographier top 10 fournisseurs critiques (concentration, monosite, single-source) — DSC — avant J+7 [ESTIM. IA]",
        "DECISION 2 A TRANCHER : Investir dual sourcing +2% couts vs maintenir mono-source — arbitrage resilience/marge [ESTIM. IA]",
        "DECISION 3 RECOMMANDEE : Plan nearshoring ou sourcing alternatif geographie — DSC+Direction Achats — livrable J+90 [ESTIM. IA]",
    ],
    "croissance_saine": [
        "DECISION 1 RECOMMANDEE : Audit capacite SC pour objectif croissance +30% — DSC+DI — cartographier goulots — avant J+14 [ESTIM. IA]",
        "DECISION 2 A TRANCHER : Investir capacite propre vs sous-traitance flexible — arbitrage capex/agilite/marge [ESTIM. IA]",
        "DECISION 3 RECOMMANDEE : Pre-qualification fournisseurs alternatifs et stocks tampons sur composants longs — DSC — J+30 [ESTIM. IA]",
    ],
    "generique": [
        "DECISION 1 RECOMMANDEE : Audit express stocks et disponibilite sur references critiques — DSC+Finance — avant J+7 [ESTIM. IA]",
        "DECISION 2 A TRANCHER : Arbitrer taux service vs reduction BFR — impact cash a quantifier en seance [ESTIM. IA]",
        "DECISION 3 RECOMMANDEE : Pilotage hebdomadaire stocks/disponibilite/cash sur SKU prioritaires — DSC — des J+3 [ESTIM. IA]",
    ],
}


_SC_FALLBACK_DECISIONS_EN = {
    "crise_qualite": [
        "RECOMMENDED DECISION 1: Daily quality-crisis cell SC+COO — map non-conforming components and suspend impacted deliveries — within 3 days [AI ESTIM.]",
        "DECISION 2 TO ARBITRATE: Maintain output rates vs selective suspension of non-conforming production — cash impact and customer penalties to quantify [AI ESTIM.]",
        "RECOMMENDED DECISION 3: 100% quality audit plan on critical SKUs — SC+Quality — delivered day 30 [AI ESTIM.]",
    ],
    "surstock_critique": [
        "RECOMMENDED DECISION 1: Urgent destocking plan — identify top 20% overstock SKUs (volume and age) — CFO+SC — within 7 days [AI ESTIM.]",
        "DECISION 2 TO ARBITRATE: Promotional destocking vs outlet-channel disposal vs output-rate reduction — margin/image/cash trade-off [AI ESTIM.]",
        "RECOMMENDED DECISION 3: Freeze supplier orders on overstock categories >60d — SC — immediate [AI ESTIM.]",
    ],
    "rupture_fournisseur": [
        "RECOMMENDED DECISION 1: Activate qualified alternative supplier — SC — within 3 days even at +15-20% overcost [AI ESTIM.]",
        "DECISION 2 TO ARBITRATE: Safety stock 10 weeks vs 6 weeks current — cash tied up vs customer stockout risk [AI ESTIM.]",
        "RECOMMENDED DECISION 3: Map top 10 single-source critical components and launch dual sourcing — SC — day 30 [AI ESTIM.]",
    ],
    "cash_critique": [
        "RECOMMENDED DECISION 1: Daily cash review — CFO+SC — 90-day cash visibility — within 3 days [AI ESTIM.]",
        "DECISION 2 TO ARBITRATE: Reduce working-capital inventory -X EURm vs maintain customer service — trade-off to quantify in CEO session [AI ESTIM.]",
        "RECOMMENDED DECISION 3: Freeze non-critical supplier orders and defer CAPEX — CFO — immediate [AI ESTIM.]",
    ],
    "bfr_tension": [
        "RECOMMENDED DECISION 1: Rapid inventory & working-capital audit — SC+CFO — quantify cash tied up by product family — within 7 days [AI ESTIM.]",
        "DECISION 2 TO ARBITRATE: Arbitrate service level >95% vs target inventory reduction — releasable cash impact to quantify in session [AI ESTIM.]",
        "RECOMMENDED DECISION 3: Weekly inventory/availability/DSO steering on priority SKUs — SC — from day 3 [AI ESTIM.]",
    ],
    "dependance_critique": [
        "RECOMMENDED DECISION 1: Map top 10 critical suppliers (concentration, single-site, single-source) — SC — within 7 days [AI ESTIM.]",
        "DECISION 2 TO ARBITRATE: Invest in dual sourcing +2% cost vs keep single-source — resilience/margin trade-off [AI ESTIM.]",
        "RECOMMENDED DECISION 3: Nearshoring or alternative-geography sourcing plan — SC+Procurement — delivered day 90 [AI ESTIM.]",
    ],
    "croissance_saine": [
        "RECOMMENDED DECISION 1: SC capacity audit for +30% growth target — SC+Industrial — map bottlenecks — within 14 days [AI ESTIM.]",
        "DECISION 2 TO ARBITRATE: Invest in own capacity vs flexible subcontracting — capex/agility/margin trade-off [AI ESTIM.]",
        "RECOMMENDED DECISION 3: Pre-qualify alternative suppliers and buffer stocks on long-lead components — SC — day 30 [AI ESTIM.]",
    ],
    "generique": [
        "RECOMMENDED DECISION 1: Rapid inventory & availability audit on critical SKUs — SC+Finance — within 7 days [AI ESTIM.]",
        "DECISION 2 TO ARBITRATE: Arbitrate service level vs working-capital reduction — cash impact to quantify in session [AI ESTIM.]",
        "RECOMMENDED DECISION 3: Weekly inventory/availability/cash steering on priority SKUs — SC — from day 3 [AI ESTIM.]",
    ],
}


def _build_sc_fallback_json(source_text: str, lang: str = "fr") -> str:
    """Génère le bloc JSON fallback SC avec scores et décisions contextuels.
    v16.5.28 : scores différenciés (build_sc_scores) + décisions selon situation_type.
    Boeing ≠ Nike ≠ BREIZHPack ≠ CORIOLIS — chaque contexte produit des scores et décisions adaptés.
    """
    import json as _json
    _en = (lang or "fr").lower() == "en"
    kpis   = build_sc_kpis(source_text, lang)      # KPIs textuels contextuels
    sc_ctx = build_sc_scores(source_text, lang)    # Scores + status + situation_type

    _DEC = _SC_FALLBACK_DECISIONS_EN if _en else _SC_FALLBACK_DECISIONS
    decisions = _DEC.get(sc_ctx["situation_type"], _DEC["generique"])

    # Risque principal selon situation
    if _en:
        _risk_map = {
            "crise_qualite":      ("Critical production non-conformity",       "critical", "Certification halt, contractual penalties, brand image [AI ESTIM.]"),
            "surstock_critique":  ("Record overstock — major cash tied up",    "high",     "Inventory write-down, margin-destroying promotions [AI ESTIM.]"),
            "rupture_fournisseur":("Critical supplier disruption",             "high",     "Production halt, direct revenue shortfall [AI ESTIM.]"),
            "cash_critique":      ("Critical cash burn — runway <18 months",   "high",     "Liquidity risk, bank covenants, refinancing [AI ESTIM.]"),
            "bfr_tension":        ("Working capital under pressure — inventory and receivables", "medium", f"Cash tied up — {kpis['bfr_impact']}"),
            "dependance_critique":("Single-source supplier dependency",        "high",     "Whole-chain disruption on a single failure [AI ESTIM.]"),
            "croissance_saine":   ("Capacity bottlenecks on rapid growth",     "medium",   "Customer under-delivery and market-share loss risk [AI ESTIM.]"),
            "generique":          ("stock/service/cash misalignment",          "medium",   f"Working-capital & product-availability impact — {kpis['bfr_impact']}"),
        }
    else:
        _risk_map = {
        "crise_qualite":      ("Non-conformité production critique",       "critique",  "Arrêt certification, pénalités contractuelles, image marque [ESTIM. IA]"),
        "surstock_critique":  ("Surstock record — cash immobilisé majeur", "elevee",    "Dépréciation stocks, promotions destructrices de marge [ESTIM. IA]"),
        "rupture_fournisseur":("Rupture fournisseur critique",             "elevee",    "Arrêt production, manque à gagner CA direct [ESTIM. IA]"),
        "cash_critique":      ("Cash burn critique — runway <18 mois",     "elevee",    "Risque liquidité, covenants bancaires, refinancement [ESTIM. IA]"),
        "bfr_tension":        ("BFR sous tension — stocks et créances",    "moyenne",   f"Cash immobilisé — {kpis['bfr_impact']}"),
        "dependance_critique":("Dépendance fournisseur mono-source",       "elevee",    "Rupture supply chaîne entière sur défaillance unique [ESTIM. IA]"),
        "croissance_saine":   ("Goulots capacité sur croissance rapide",   "moyenne",   "Risque sous-livraison clients et perte part de marché [ESTIM. IA]"),
        "generique":          ("Désalignement stock/service/cash",         "moyenne",   f"Impact BFR et disponibilité produit — {kpis['bfr_impact']}"),
    }
    risk_label, risk_prob, risk_impact = _risk_map.get(
        sc_ctx["situation_type"], _risk_map["generique"]
    )

    payload = {
        "global_status":     sc_ctx["global_status"],
        "executive_summary": sc_ctx["executive_summary"],
        "key_findings": [
            f"Couverture stock : {kpis['stock_coverage']} [ESTIM. IA]",
            f"Taux de service cible : {kpis['service_level']}",
            f"BFR : {kpis['bfr_impact']}",
        ],
        "major_risks": [
            {"risk": risk_label, "probability": risk_prob,
             "business_impact": risk_impact},
            {"risk": "Dépendances géographiques / fournisseurs", "probability": "moyenne",
             "business_impact": "Exposition tarifs, forex, délais [ESTIM. IA]"},
        ],
        "codir_tradeoffs": [
            f"Service client >95% vs réduction stocks — {kpis['bfr_impact']}",
            "Vitesse exécution vs maîtrise des coûts supply [ESTIM. IA]",
        ],
        "dg_decisions": decisions,
        "recommendations": {
            "0_30_days": [decisions[0].split(":")[1].strip()[:80] + " [ESTIM. IA]"
                          if ":" in decisions[0] else "Audit express situation SC — DSC — avant J+7 [ESTIM. IA]",
                          "Lancer pilotage hebdo stocks/cash/service [ESTIM. IA]"],
            "1_3_months": ["Plan correctif structurel sur risque principal identifié [ESTIM. IA]"],
            "3_12_months": ["Programme résilience supply chain long terme [ESTIM. IA]"],
        },
        "scores": {
            "service_level":    sc_ctx["service_level"],
            "stock_management": sc_ctx["stock_management"],
            "supply_resilience":sc_ctx["supply_resilience"],
            "cash_impact":      sc_ctx["cash_impact"],
            "scores_estimated": True,
        },
        "estimated_kpis": {
            "rotation_stock": kpis["rotation_stock"],
            "service_level":  kpis["service_level"],
            "stock_coverage": kpis["stock_coverage"],
            "bfr_impact":     kpis["bfr_impact"],
        },
        "challenge_audit": {
            "validated": [], "corrected": [],
            "added": [f"JSON fallback contextuel — situation: {sc_ctx['situation_type']} — scores différenciés v16.5.28"],
            "contradicted": [],
        },
    }
    try:
        json_str = _json.dumps(payload, ensure_ascii=False, indent=2)
    except Exception:
        json_str = "{}"
    return f"\n\n{JSON_START_TAG}\n{json_str}\n{JSON_END_TAG}\n"


def _parse_sc_relevance_json(raw_output: str) -> dict | None:
    """
    Parse la réponse mini JSON du pre-filter SC.
    Retourne un dict {"trigger": bool, "reason": str, "confidence": str}
    ou None si le parsing échoue.
    """
    text = (raw_output or "").strip()
    # Chercher un objet JSON dans la réponse (robustesse si le modèle ajoute du texte)
    start = text.find("{")
    end   = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        payload = json.loads(text[start:end + 1])
        if not isinstance(payload, dict) or "trigger" not in payload:
            return None
        return {
            "trigger":    bool(payload.get("trigger", True)),
            "reason":     str(payload.get("reason", ""))[:120],
            "confidence": str(payload.get("confidence", "moyenne")).lower(),
        }
    except (json.JSONDecodeError, Exception):
        return None


def _parse_supply_chain_override(user_input: str | dict) -> bool | None:
    """
    v16.5.76 item 6 — Override manuel supply chain dans le brief.

    Cherche une balise explicite dans le brief :
      "SUPPLY CHAIN : oui/non/yes/no"
      "ANALYSE SUPPLY CHAIN : oui/non"
      "FORCER SUPPLY CHAIN : oui/non"
      "SUPPLY_CHAIN : true/false"

    Si trouvée → retourne True/False (override le prefilter automatique).
    Si pas trouvée → retourne None (laisse le prefilter décider).

    Cas d'usage : dossier réseau de soins a un APE 70.21Z trompeur (holding "conseil") qui fait
    que le prefilter classe en services et désactive supply chain. Le DAF qui
    sait qu'dossier réseau de soins est une chaîne de distribution peut forcer l'analyse via le
    wizard de brief.
    """
    if not user_input:
        return None
    if isinstance(user_input, dict):
        # Concaténer tous les champs de texte pour chercher la balise
        text = " ".join(str(v) for v in user_input.values() if isinstance(v, str))
    else:
        text = str(user_input)
    if not text.strip():
        return None

    import re as _re
    # Pattern : balise SUPPLY CHAIN / SUPPLY_CHAIN / ANALYSE SUPPLY CHAIN / FORCER SUPPLY CHAIN
    # suivie de : puis oui/non/yes/no/true/false (insensible à la casse)
    pattern = _re.compile(
        r"\b(?:FORCER\s+|ANALYSE\s+)?SUPPLY[\s_]CHAIN\s*[:\-=]\s*(oui|non|yes|no|true|false|on|off)\b",
        _re.IGNORECASE,
    )
    m = pattern.search(text)
    if not m:
        return None

    val = m.group(1).lower()
    if val in ("oui", "yes", "true", "on"):
        return True
    if val in ("non", "no", "false", "off"):
        return False
    return None


def _resolve_supply_chain_decision(
    user_input: str | dict,
    cb: Optional[StatusCallback],
    diag_list: Optional[List[Dict[str, Any]]],
    settings: Settings,
    logger=None,
    company_profile=None,
    attachments_text: str = "",
) -> bool:
    """
    v16.5.76 — Wrapper qui combine override manuel + fast-paths + prefilter LLM.

    Ordre de priorité (premier qui répond gagne) :
      1. Override explicite utilisateur (SUPPLY CHAIN : oui/non dans brief)  ← item 6
      2. Fast-path sector_detector : si nom = dossier réseau de soins/Krys/Carrefour/etc.    ← item 7 (Phase 2)
         avec confidence high + implies_supply_chain → True sans appeler le LLM
      3. Fast-path holding+filiales opérationnelles : si APE holding (70.10/
         70.21/64.20) + signaux physiques dans PJ → True sans appeler le LLM ← item 5 (Phase 2)
      4. Sinon → prefilter LLM (check_sc_relevance)

    Pourquoi des fast-paths : sur dossier réseau de soins (run #4 15/05/2026), le LLM s'est
    laissé tromper par l'APE 70.21Z (holding RP) malgré la signature évidente
    "dossier réseau de soins = audioprothèses". En court-circuitant le LLM avec un signal fort
    (nom + APE holding + signaux PJ), on évite ces faux négatifs.

    Args:
        company_profile: profil entité détecté (CompanyProfile ou None)
        attachments_text: texte concaténé des PJ (pour détecter signaux physiques)
    """
    # ──────────────────────────────────────────────────────────────────────
    # 1. Override explicite utilisateur (item 6 v76 Phase 1)
    # ──────────────────────────────────────────────────────────────────────
    override = _parse_supply_chain_override(user_input)
    if override is not None:
        _record_diag(
            diag_list, role="supply_chain_prefilter",
            provider="internal", model="user_override_v1", status="OK",
            attempt=1, duration_s=0, tokens={},
            error=f"override=manuel | trigger={override} | reason=Balise explicite SUPPLY CHAIN: {override} dans le brief",
        )
        if logger:
            log_event(logger, "info", "codir_engine", "supply_chain_override",
                      trigger=override, source="brief_explicit_balise")
        return override

    # ──────────────────────────────────────────────────────────────────────
    # 2. Fast-path sector_detector — item 7 v76 Phase 2
    #    Si le NOM porte un signal sectoriel fort (dossier réseau de soins, Krys, Boulanger…)
    #    avec confidence high + implies_supply_chain, on force True sans LLM.
    # ──────────────────────────────────────────────────────────────────────
    company_name = ""
    if company_profile is not None:
        company_name = getattr(company_profile, "company_name_official", "") or ""
    if not company_name and isinstance(user_input, dict):
        company_name = str(user_input.get("company_name", "") or "")
    if company_name:
        try:
            from patches.sector_detector import detect_sector_from_name
            hint = detect_sector_from_name(company_name)
            if hint and hint.confidence == "high" and hint.implies_supply_chain:
                _record_diag(
                    diag_list, role="supply_chain_prefilter",
                    provider="internal", model="sector_detector_v1", status="OK",
                    attempt=1, duration_s=0, tokens={},
                    error=f"fast_path=sector_detector | trigger=True | sector={hint.sector} | confidence={hint.confidence} | evidence={hint.evidence[0][:80]}",
                )
                if logger:
                    log_event(logger, "info", "codir_engine", "supply_chain_fast_path",
                              trigger=True, source="sector_detector",
                              sector=hint.sector, confidence=hint.confidence)
                return True
        except ImportError:
            # sector_detector absent (env de test léger) — fallback gracieux
            pass

    # ──────────────────────────────────────────────────────────────────────
    # 3. Fast-path holding+filiales opérationnelles — item 5 v76 Phase 2
    #    Si APE holding (70.10/70.21/64.20) + signaux physiques dans PJ,
    #    on force True sans LLM. La logique existe déjà dans
    #    company_profile.role_activation depuis v16.5.67.10 mais elle est
    #    contournée par le prefilter LLM. Ici on la promeut en fast-path.
    # ──────────────────────────────────────────────────────────────────────
    if company_profile is not None and attachments_text:
        ape = (getattr(company_profile, "ape_code", "") or "").upper()
        legal_form = (getattr(company_profile, "legal_form", "") or "").lower()
        _is_holding = (
            ("holding" in legal_form) or
            (ape in {"70.10Z", "70.10", "70.21Z", "70.21", "64.20Z", "64.20"})
        )
        if _is_holding:
            _physical_kw = (
                "stocks", "magasin", "magasins", "centre", "centres",
                "distribution", "réseau", "reseau", "audioprothèse",
                "audioprothèses", "audioprotheses", "entrepôt", "entrepot",
                "logistique", "livraison", "inventaire", "sku", "retail",
                "filiales opérationnelles", "filiales operationnelles",
            )
            att_lower = attachments_text.lower()
            matched_kw = [kw for kw in _physical_kw if kw in att_lower]
            if matched_kw:
                _record_diag(
                    diag_list, role="supply_chain_prefilter",
                    provider="internal", model="holding_subsidiaries_v1", status="OK",
                    attempt=1, duration_s=0, tokens={},
                    error=f"fast_path=holding+subsidiaries | trigger=True | ape={ape} | physical_signals={matched_kw[:5]}",
                )
                if logger:
                    log_event(logger, "info", "codir_engine", "supply_chain_fast_path",
                              trigger=True, source="holding_subsidiaries",
                              ape=ape, signals_count=len(matched_kw))
                return True

    # ──────────────────────────────────────────────────────────────────────
    # 4. Fast-path retail/ops keywords — B.1.3.18 (run 10 dossier anglophone coté) :
    #    le prefilter LLM (fenêtre ~687 tokens) a répondu « aucun signal »
    #    sur un brief inventory/stockout/markdowns/SKU. Signal déterministe
    #    fort (≥3 mots-clés distincts) sur le brief COMPLET + PJ → True sans
    #    LLM. Même famille que le fast-path dossier réseau de soins : faux négatif LLM
    #    court-circuité par un signal évident.
    # ──────────────────────────────────────────────────────────────────────
    try:
        if isinstance(user_input, dict):
            _txt18 = " ".join(str(v) for v in user_input.values()
                              if isinstance(v, str))
        else:
            _txt18 = str(user_input or "")
        _txt18 = (_txt18 + " " + (attachments_text or "")).lower()
        _retail_rx18 = re.compile(
            r"\b(inventor(?:y|ies)|stocks?|stockouts?|entrep[ôo]ts?|"
            r"warehouses?|markdowns?|skus?|dtc|e-?commerce|magasins?|"
            r"stores?|retail|supply\s*chains?|logistique|logistics)\b")
        _hits18 = sorted(set(_retail_rx18.findall(_txt18)))
        if len(_hits18) >= 3:
            _record_diag(
                diag_list, role="supply_chain_prefilter",
                provider="internal", model="retail_keywords_v1", status="OK",
                attempt=1, duration_s=0, tokens={},
                error=(f"fast_path=retail_keywords | trigger=True | "
                       f"signals={_hits18[:6]}"),
            )
            if logger:
                log_event(logger, "info", "codir_engine",
                          "supply_chain_fast_path", trigger=True,
                          source="retail_keywords",
                          signals_count=len(_hits18))
            return True
    except Exception:
        pass

    # ──────────────────────────────────────────────────────────────────────
    # 4 bis. 9.4.61 — décision du dirigeant (12/10/2026) : la Supply Chain fait partie du produit. Recette cas de recette (trois
    #    séances) : le préfiltre LLM a jugé le sujet « non pertinent » alors que le brief portait sur les COÛTS D'INTRANTS et
    #    l'EXPOSITION DOUANIÈRE — l'analyse complète n'a jamais tourné. Deux signaux distincts de chaîne d'approvisionnement
    #    industrielle dans le brief ou les pièces imposent l'analyse complète.
    # ──────────────────────────────────────────────────────────────────────
    try:
        _txt61 = (" ".join(str(v) for v in user_input.values() if isinstance(v, str)) if isinstance(user_input, dict)
                  else str(user_input or "")) + " " + (attachments_text or "")
        _sig61 = {
            "intrants": r"co[uû]ts?\s+(?:d['’]\s*|des?\s+)?intrants|input\s+costs?",
            "matieres": r"mati[èe]res?\s+premi[èe]res?|raw\s+materials?|commodit(?:y|ies)",
            "douane": r"douan\w*|droits?\s+de\s+douane|tarif(?:s|fs)?\s+(?:douaniers?|exposure)|tariffs?|customs\s+duties",
            "soustraitance": r"sous[- ]trait\w*|fabricants?\s+sous\s+contrat|fa[çc]onniers?|contract\s+manufactur\w*|co-?packers?",
            "approvisionnement": r"approvisionnements?|fournisseurs?|procurement|sourcing|suppliers?",
            "fret": r"\bfret\b|freight|transport\s+(?:maritime|routier)|lead\s+times?|d[ée]lais?\s+d['’]approvisionnement",
        }
        _hit61 = sorted(k for k, rx in _sig61.items() if re.search(rx, _txt61, re.I))
        if len(_hit61) >= 2:
            _record_diag(diag_list, role="supply_chain_prefilter", provider="internal", model="supply_signals_v61",
                         status="OK", attempt=1, duration_s=0, tokens={},
                         error=f"fast_path=supply_signals | trigger=True | signals={_hit61}")
            return True
    except Exception:
        pass

    # ──────────────────────────────────────────────────────────────────────
    # 5. Pas de fast-path → comportement normal (LLM prefilter)
    # ──────────────────────────────────────────────────────────────────────
    return check_sc_relevance(user_input, cb, diag_list, settings=settings, logger=logger)


def check_sc_relevance(
    user_input: str | dict,
    cb: Optional[StatusCallback],
    diag_list: Optional[List[Dict[str, Any]]],
    settings: Settings,
    logger=None,
) -> bool:
    """
    Pre-filter SC — mini JSON avec confidence.
    Retourne True (activer SC) ou False (ignorer).

    Réponse attendue du modèle :
        {"trigger": true/false, "reason": "...", "confidence": "haute|moyenne|faible"}

    Fallback OUI/NON binaire si le JSON est absent ou invalide.
    Si le pre-filter échoue complètement : activation SC par défaut (conservateur).
    """
    if not call_openai or not _has_key("openai"):
        _record_diag(
            diag_list, role="supply_chain_prefilter",
            provider="openai", model=_sc_model_id_for("prefilter", settings), status="SKIPPED",
            attempt=1, duration_s=0, tokens={},
            error="OPENAI indisponible — SC active par defaut",
        )
        return True

    raw_dict = normalize_user_input(user_input)
    ctx_parts = [raw_dict.get("business_context", "")]
    if raw_dict.get("known_issues"):
        ctx_parts.append(raw_dict["known_issues"])
    if raw_dict.get("management_priorities"):
        ctx_parts.append(raw_dict["management_priorities"])
    # B.1.3.19 (runs 9/10/11 : input prefilter CONSTANT ~687 tokens) — le
    # trio ci-dessus était la SEULE fenêtre du préfiltre : les champs
    # riches du formulaire (questions, KPI, points de vigilance) étaient
    # hors de sa vue. Il juge désormais le brief entier, borné en taille.
    for _k19 in ("priority_questions", "kpi_data", "special_watchpoints"):
        if raw_dict.get(_k19):
            ctx_parts.append(raw_dict[_k19])
    raw = "\n".join(p for p in ctx_parts if p).strip()[:40000]     # 9.4.57 — demande du 10/10 : 8 000 → 40 000 caractères
    context = f"BRIEFING SUPPLY CHAIN :\n{raw}"

    if cb:
        cb("supply_chain_prefilter", f"Supply Chain — pre-filter de pertinence ({_sc_model_id_for('prefilter', settings)})…")

    t0  = time.time()
    res = _safe_call(
        "openai", call_openai,
        prompt=context,
        system=SC_RELEVANCE_PROBE_PROMPT,
        temperature=0.0,
        max_tokens=80,          # Augmenté pour laisser place au JSON
        model=_sc_model_id_for("prefilter", settings),
    )
    dur    = round(time.time() - t0, 3)
    status = "ERROR" if res.get("error") else "OK"
    raw_answer = (res.get("output") or "").strip()

    # ── Parsing JSON ─────────────────────────────────────────────────────────
    parsed = _parse_sc_relevance_json(raw_answer) if not res.get("error") else None

    if parsed is not None:
        trigger    = parsed["trigger"]
        reason     = parsed["reason"]
        confidence = parsed["confidence"]
        diag_extra = f"trigger={trigger} | confidence={confidence} | reason={reason[:60]}"
    else:
        # ── Fallback OUI/NON binaire ────────────────────────────────────────
        answer_up = raw_answer.upper()
        if res.get("error") or not answer_up:
            trigger    = True       # Conservateur : activer si incertitude
            reason     = "Pre-filter en erreur — SC activee par defaut."
            confidence = "faible"
        else:
            trigger    = answer_up.startswith("OUI")
            reason     = "Reponse binaire (fallback)"
            confidence = "moyenne"
        diag_extra = f"fallback_binaire | trigger={trigger} | raw={raw_answer[:30]}"

    _record_diag(
        diag_list,
        role="supply_chain_prefilter",
        provider=res.get("provider", "openai"),
        model=res.get("model", _sc_model_id_for("prefilter", settings)),
        status=status,
        attempt=1,
        duration_s=dur,
        tokens=res.get("tokens") or {},
        error=diag_extra,
    )
    if logger:
        log_event(
            logger,
            "warning" if res.get("error") else "info",
            "codir_engine", "supply_chain_prefilter",
            status=status,
            trigger=trigger,
            confidence=confidence,
        )
    return trigger


def run_sc_primary(
    user_input: str | dict,
    finance_output: str,
    temperature: float,
    max_tokens: int,
    cb: Optional[StatusCallback],
    diag_list: Optional[List[Dict[str, Any]]],
    settings: Settings,
    logger=None,
    pappers_context: str = "",
) -> Dict[str, Any]:
    payload = normalize_user_input(user_input)
    _lang_sc = _lang(settings)
    user_message = _get_sc_user_template(_lang_sc).format(**payload, finance_output=finance_output or "")
    if pappers_context:
        user_message = pappers_context + user_message
    if cb:
        cb("supply_chain", f"Supply Chain — {_sc_model_id_for('primary', settings)} ({'primary analysis' if _lang_sc == 'en' else 'analyse primaire'})…")
    t0 = time.time()
    res = _safe_call("openai", call_openai, prompt=_inject_json_schema_in_agent_prompt(user_message, _lang_sc), system=_lang_wrap(_get_sc_system_prompt(_lang_sc), _lang_sc), temperature=temperature, max_tokens=min(max_tokens + 600, 3200), model=_sc_model_id_for("primary", settings))
    dur = round(time.time() - t0, 3)
    res["role"] = "supply_chain_primary"
    _record_diag(diag_list, role="supply_chain_primary", provider=res.get("provider", "openai"), model=res.get("model", _sc_model_id_for("primary", settings)), status="ERROR" if res.get("error") else "OK", attempt=1, duration_s=dur, tokens=res.get("tokens") or {}, error=(res.get("raw") or {}).get("exception", "") if res.get("error") and isinstance(res.get("raw"), dict) else (res.get("output", "") if res.get("error") else ""))
    if logger:
        log_event(logger, "warning" if res.get("error") else "info", "codir_engine", "supply_chain_primary", status="ERROR" if res.get("error") else "OK")
    return res


def run_sc_challenge(
    sc_initial_output: str,
    user_input: str | dict,
    finance_output: str,
    cb: Optional[StatusCallback],
    diag_list: Optional[List[Dict[str, Any]]],
    settings: Settings,
    logger=None,
    pappers_context: str = "",
) -> Dict[str, Any]:
    payload = normalize_user_input(user_input)
    raw_input = json.dumps(payload, ensure_ascii=False, indent=2)
    _lang_sc = _lang(settings)
    user_message = _get_sc_challenge_user_template(_lang_sc).format(sc_initial_output=sc_initial_output, user_input=raw_input, finance_output=finance_output or "")
    if pappers_context:
        user_message = pappers_context + user_message
    if cb:
        cb("supply_chain_challenge", f"Supply Chain — {_sc_model_id_for('challenge', settings)} ({'challenge' if _lang_sc == 'en' else 'challenge'})…")
    t0 = time.time()
    res = _safe_call("google", call_gemini, prompt=user_message, system=_lang_wrap(_get_sc_challenge_system_prompt(_lang_sc), _lang_sc), temperature=0.0, max_tokens=10000, model=_sc_model_id_for("challenge", settings))
    dur = round(time.time() - t0, 3)
    res["role"] = "supply_chain_challenge"
    _record_diag(diag_list, role="supply_chain_challenge", provider=res.get("provider", "gemini"), model=res.get("model", _sc_model_id_for("challenge", settings)), status="ERROR" if res.get("error") else "OK", attempt=1, duration_s=dur, tokens=res.get("tokens") or {}, error=(res.get("raw") or {}).get("exception", "") if res.get("error") and isinstance(res.get("raw"), dict) else (res.get("output", "") if res.get("error") else ""))
    if logger:
        log_event(logger, "warning" if res.get("error") else "info", "codir_engine", "supply_chain_challenge", status="ERROR" if res.get("error") else "OK")
    return res


def get_sc_final_output(sc_challenge_output: str) -> str:
    audit_start = (sc_challenge_output or "").find(AUDIT_START_TAG)
    if audit_start == -1:
        return (sc_challenge_output or "").strip()
    return (sc_challenge_output or "")[:audit_start].strip()


def extract_sc_audit(sc_challenge_output: str) -> str | None:
    if not sc_challenge_output:
        return None
    start = sc_challenge_output.find(AUDIT_START_TAG)
    end = sc_challenge_output.find(AUDIT_END_TAG)
    if start == -1 or end == -1 or end <= start:
        return None
    return sc_challenge_output[start + len(AUDIT_START_TAG):end].strip() or None


def _iter_sc_json_blocks(text: str | None):
    """M6-A2.2.2 — itère le contenu brut de chaque bloc ---JSON_START---...---JSON_END---
    ÉQUILIBRÉ. Un JSON_START orphelin (tronqué) n'est pas un bloc → non itéré."""
    if not text:
        return
    for m in re.finditer(r"---JSON_START---([\s\S]*?)---JSON_END---", text, flags=re.IGNORECASE):
        yield m.group(1).strip()


def extract_sc_json(sc_output: str | None, lang: str = "fr") -> dict | None:
    if not sc_output:
        return None
    # M6-A2.2.2 — PRIORITÉ AU JSON *SUPPLY CHAIN*, pas à n'importe quel JSON. On scanne
    # TOUS les blocs JSON équilibrés et on ne retient que le premier qui passe la garde
    # de schéma SC partagée (rejette un JSON commercial/générique syntaxiquement valide,
    # et gère le cas « JSON commercial d'abord + JSON SC ensuite »).
    for raw in _iter_sc_json_blocks(sc_output):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if _is_supply_chain_json(payload):
            return _normalize_sc_json_values(payload, lang)
    return None


def extract_commercial_json(commercial_output: str | None) -> dict | None:
    """
    Option B — v16.5.28.
    Parse le bloc JSON structuré généré directement par Grok dans sa note commerciale.
    Même mécanique que extract_sc_json pour le Supply Chain.
    Retourne un dict avec les clés : opportunites, plan_actions,
    challenges_marketing, challenges_finance — ou None si absent/invalide.
    """
    if not commercial_output:
        return None
    start = commercial_output.find(JSON_START_TAG)
    end   = commercial_output.find(JSON_END_TAG)
    if start == -1 or end == -1 or end <= start:
        return None
    raw = commercial_output[start + len(JSON_START_TAG):end].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        # Tentative de réparation simple : supprimer trailing commas
        import re as _re
        cleaned = _re.sub(r",\s*([}\]])", r"\1", raw)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, dict):
        return None
    # Valider structure minimale
    if not any(k in payload for k in ("opportunites", "plan_actions")):
        return None
    # Normaliser plan_actions : garantir 3 items avec délais progressifs
    pa = payload.get("plan_actions") or []
    if isinstance(pa, list):
        progressive_delais = ["T1", "T2", "T3"]
        for i, item in enumerate(pa[:3]):
            if isinstance(item, dict):
                d = str(item.get("delai", "")).strip()
                if not d or d in {"…", "None", "."}:
                    item["delai"] = progressive_delais[i]
        payload["plan_actions"] = pa[:3]
    return payload


def should_generate_sc_slide(sc_json: dict | None) -> bool:
    if not sc_json:
        return False
    if _enum_to_canon(sc_json.get("global_status", "healthy")) != "healthy":
        return True
    for risk in _as_list(sc_json.get("major_risks")):  # M6-A2.2.5 — type-safe (symétrie deck)
        if _enum_to_canon(_as_dict(risk).get("probability")) == "high":
            return True
    scores = _as_dict(sc_json.get("scores"))
    cash = scores.get("cash_impact")
    if cash is not None:
        try:
            if float(cash) <= 4:
                return True
        except Exception:
            pass
    service = scores.get("service_level")
    if service is not None:
        try:
            if float(service) <= 5:
                return True
        except Exception:
            pass
    tradeoffs = _as_str_list(sc_json.get("codir_tradeoffs"))
    if len([x for x in tradeoffs if str(x).strip()]) >= 2:
        return True
    return False




def run_supply_chain_seed(
    user_input: str | dict,
    temperature: float,
    max_tokens: int,
    cb: Optional[StatusCallback],
    diag_list: Optional[List[Dict[str, Any]]],
    settings: Settings,
    logger=None,
    pappers_context: str = "",
    company_profile=None,
) -> Dict[str, Any]:
    out = {"enabled": False, "triggered": False, "output": None, "json": None, "status": "not_triggered", "source": None, "warning": None, "raw": {}}
    try:
        # v16.5.76 — Wrapper combine override (item 6) + fast-paths (items 5+7 Phase 2) + LLM prefilter
        sc_trigger = _resolve_supply_chain_decision(
            user_input, cb, diag_list, settings=settings, logger=logger,
            company_profile=company_profile,
            attachments_text=pappers_context,  # pappers_context contient les filiales/APE/balances
        )
    except Exception as e:
        sc_trigger = True
        out["warning"] = f"Pre-filter SC en erreur — activation par défaut ({e})"
    out["triggered"] = bool(sc_trigger)
    if not sc_trigger:
        return out
    primary_res = run_sc_primary(user_input, "", temperature, max_tokens, cb, diag_list, settings=settings, logger=logger, pappers_context=pappers_context)
    out["raw"]["primary"] = primary_res
    sc_primary = None if primary_res.get("error") else _as_output(primary_res)
    if not is_sc_output_valid(sc_primary):
        sc_primary = build_sc_fallback_narrative(user_input, build_sc_context_brief(user_input), lang=getattr(settings, "output_language", "fr"))
        out["status"] = "narrative_fallback" if is_sc_output_valid(sc_primary) else "unavailable"
        out["source"] = "heuristic_fallback"
    else:
        out["status"] = "seed"
        out["source"] = f"{_sc_model_id_for('primary', settings)}-seed"
    _sc_lang = getattr(settings, "output_language", "fr")
    out["enabled"] = True
    out["output"] = normalize_sc_enums_in_text(sc_primary, _sc_lang)
    out["json"] = extract_sc_json(out["output"], _sc_lang)
    return out

def run_supply_chain_role(
    user_input: str | dict,
    finance_output: str,
    temperature: float,
    max_tokens: int,
    cb: Optional[StatusCallback],
    diag_list: Optional[List[Dict[str, Any]]],
    settings: Settings,
    logger=None,
    sc_seed_output: str | None = None,
    sc_seed_triggered: bool | None = None,
    pappers_context: str = "",
    company_profile=None,
) -> Dict[str, Any]:
    """v16.5.28 — sc_seed_triggered permet d'éviter la double invocation du pre-filter.
    Si fourni (depuis run_supply_chain_seed), le pre-filter n'est pas réexécuté.

    v16.5.76 Phase 2 — company_profile (optionnel) permet aux fast-paths
    holding+filiales et sector_detector d'agir sans appel LLM.
    """
    out = {
        "enabled": False,
        "triggered": False,
        "output": None,
        "json": None,
        "slide_flag": False,
        "audit": None,
        "source": None,
        "warning": None,
        "status": "not_triggered",
        "raw": {},
    }
    # v16.5.28 — déduplication pre-filter : réutiliser le résultat du seed si disponible
    if sc_seed_triggered is not None:
        sc_trigger = sc_seed_triggered
    else:
        try:
            # v16.5.76 — Wrapper combine override (item 6) + fast-paths (items 5+7 Phase 2) + LLM prefilter
            sc_trigger = _resolve_supply_chain_decision(
                user_input, cb, diag_list, settings=settings, logger=logger,
                company_profile=company_profile,
                attachments_text=pappers_context,
            )
        except Exception as e:
            if logger:
                log_event(logger, "warning", "codir_engine", "supply_chain_prefilter_error", error=str(e))
            sc_trigger = True
            out["warning"] = f"Pre-filter SC en erreur — activation par defaut ({e})"
    out["triggered"] = bool(sc_trigger)
    if not sc_trigger:
        return out

    primary_res = {"error": False, "output": sc_seed_output, "provider": "openai", "model": f"{_sc_model_id_for('primary', settings)}-seed"} if sc_seed_output else run_sc_primary(user_input, "", temperature, max_tokens, cb, diag_list, settings=settings, logger=logger, pappers_context=pappers_context)
    out["raw"]["primary"] = primary_res
    sc_primary = None if primary_res.get("error") else _as_output(primary_res)
    if primary_res.get("error"):
        fallback_text = build_sc_fallback_narrative(user_input, build_sc_context_brief(user_input), lang=getattr(settings, "output_language", "fr"))
        out.update({
            "enabled": True,
            "output": fallback_text,
            "json": None,
            "slide_flag": False,
            "audit": None,
            "source": "heuristic_fallback",
            "status": "narrative_fallback" if is_sc_output_valid(fallback_text) else "unavailable",
            "warning": ((out.get("warning") or "") + f" {_sc_model_id_for('primary', settings)} indisponible — fallback narratif SC injecte.").strip(),
        })
        return out

    final_text = sc_primary or ""
    source = _sc_model_id_for("primary", settings)
    audit_text = None

    if call_gemini and _has_key("google"):
        challenge_res = run_sc_challenge(sc_primary, user_input, finance_output, cb, diag_list, settings=settings, logger=logger, pappers_context=pappers_context)
        out["raw"]["challenge"] = challenge_res
        if not challenge_res.get("error"):
            raw_challenge = _as_output(challenge_res)
            final_text = get_sc_final_output(raw_challenge)
            audit_text = extract_sc_audit(raw_challenge)
            source = f"{_sc_model_id_for('primary', settings)}+{_sc_model_id_for('challenge', settings)}"
        else:
            out["warning"] = f"Challenge SC indisponible ({_sc_model_id_for('challenge', settings)}) — repli sur la sortie {_sc_model_id_for('primary', settings)}."
    else:
        out["warning"] = f"Google / Gemini indisponible — repli sur la sortie {_sc_model_id_for('primary', settings)}."

    sc_status = "final"
    resolved_text = final_text
    if not is_sc_output_valid(resolved_text) and is_sc_output_valid(sc_primary):
        resolved_text = sc_primary
        source = _sc_model_id_for("primary", settings)
        sc_status = "primary_fallback"
        warn = f"Sortie challenge SC inutilisable — conservation de la sortie {_sc_model_id_for('primary', settings)}."
        out["warning"] = (out["warning"] + " " + warn).strip() if out.get("warning") else warn
    elif not is_sc_output_valid(resolved_text):
        resolved_text = build_sc_fallback_narrative(user_input, build_sc_context_brief(user_input), lang=getattr(settings, "output_language", "fr"))
        source = "heuristic_fallback"
        sc_status = "narrative_fallback" if is_sc_output_valid(resolved_text) else "unavailable"
        warn = "Sortie SC inutilisable — fallback narratif construit depuis le brief SC isolé."
        out["warning"] = (out["warning"] + " " + warn).strip() if out.get("warning") else warn

    _sc_lang = getattr(settings, "output_language", "fr")
    resolved_text = normalize_sc_enums_in_text(resolved_text, _sc_lang)
    sc_json = extract_sc_json(resolved_text, _sc_lang)
    # M6-A2.2.6 — retry JSON SC ciblé si le bloc deck a tronqué (JSON_START présent
    # mais JSON inexploitable). Parité avec finance/strategie/marketing/brief. C'est
    # ce qui permet enfin de prouver « JSON SC valide → consommé » (run dossier industriel (composants) v2 :
    # le JSON SC tronquait sans recours → structured_invalid systématique).
    if sc_json is None and (JSON_START_TAG in (resolved_text or "")):
        _sc_retry_json = _retry_sc_json(resolved_text, _sc_lang, settings,
                                        logger=logger, cb=cb, diag_list=diag_list)
        if _sc_retry_json is not None:
            sc_json = _sc_retry_json
    out.update({
        "enabled": True,
        "output": resolved_text,
        "json": sc_json,
        "slide_flag": should_generate_sc_slide(sc_json),
        "audit": audit_text,
        "source": source,
        "status": sc_status,
    })
    if resolved_text and sc_json is None:
        warn = "JSON Supply Chain invalide ou absent — prose conservee, slide PPT desactivee."
        out["slide_flag"] = False
        out["warning"] = (out["warning"] + " " + warn).strip() if out.get("warning") else warn

    if out.get("triggered") and not is_sc_output_valid(out.get("output")):
        # M6-A1-probe.3 (P0-5) — texte d'indisponibilité SC localisé selon la langue
        # du run (fuite FR déterministe dans le deck EN corrigée) + suppression des
        # crochets [...] qui laissaient un « ] » parasite dans le PPT.
        _sc_lang_u = getattr(settings, "output_language", "fr")
        if str(_sc_lang_u).lower() == "en":
            out["output"] = (
                "SUPPLY CHAIN & OPERATIONAL PERFORMANCE\n"
                "Supply Chain analysis unavailable for this run — "
                "partially covered in the executive synthesis."
            )
        else:
            out["output"] = (
                "SUPPLY CHAIN & PERFORMANCE OPÉRATIONNELLE\n"
                "Analyse Supply Chain indisponible sur ce run — "
                "points partiellement repris dans la synthèse globale."
            )
        out["slide_flag"] = False
        out["status"] = "unavailable"
        out["warning"] = ((out.get("warning") or "") + " SC output vide — statut explicite injecte.").strip()

    return out

def _as_output(result):
    if isinstance(result, dict):
        for k in ("output", "text", "content", "message", "result"):
            v = result.get(k)
            if isinstance(v, str) and v.strip():
                return v
        raw = result.get("raw")
        if raw is not None:
            content = getattr(raw, "content", None)
            if content:
                parts = []
                for part in content:
                    if hasattr(part, "type") and getattr(part, "type") == "text":
                        parts.append(getattr(part, "text", ""))
                    elif isinstance(part, dict) and part.get("type") == "text":
                        parts.append(part.get("text", ""))
                    elif isinstance(part, str):
                        parts.append(part)
                if parts:
                    return "".join(parts).strip()
        return str(result)
    if isinstance(result, str):
        return result
    return str(result)


def _normalize_tokens(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        return {}
    tokens = payload.get("tokens")
    if isinstance(tokens, dict) and tokens:
        return tokens
    usage = payload.get("usage")
    if isinstance(usage, dict) and usage:
        return {
            "input": usage.get("prompt_tokens") or usage.get("input_tokens") or usage.get("input"),
            "output": usage.get("completion_tokens") or usage.get("output_tokens") or usage.get("output"),
            "total": usage.get("total_tokens") or usage.get("total"),
        }
    return {}


# v62.13.9.4.23 — SANTÉ DES FOURNISSEURS (contre-audit v22, §3 et §9.A). Un
# solde insuffisant ou une authentification refusée ne sont pas des réponses
# mal formées : on ne réessaie pas, on ne rappelle plus ce fournisseur dans
# le run, on le journalise (fournisseur / raison / première occurrence) et
# le dossier le porte. Campagne des 05-06/09 : quatorze retries Anthropic
# refusés pour solde, OpenAI à sec sur les cinq runs, sans qu'aucun statut
# ne le dise à l'opérateur.
_PROVIDER_HEALTH: dict = {}
_NON_TRANSIENT_RE = re.compile(
    r"insufficient_quota|credit_balance_exhausted|no credits remaining|credit balance is too low|"
    r"insufficient credits|billing|payment required|quota exceeded|exceeded your current quota|"
    r"invalid api key|incorrect api key|authentication_error|unauthori[sz]ed|permission_error|api key not valid|401\b|403\b",
    re.I)


def _classify_provider_error(text: str) -> str:
    s = str(text or "")
    if re.search(r"credit|quota|billing|payment required|no credits", s, re.I):
        return "insufficient_credit"
    if re.search(r"invalid api key|incorrect api key|authentication_error|unauthori[sz]ed|permission_error|api key not valid|\b401\b|\b403\b", s, re.I):
        return "auth"
    return ""


def provider_health_snapshot() -> dict:
    return {k: dict(v) for k, v in _PROVIDER_HEALTH.items()}


def reset_provider_health() -> None:
    _PROVIDER_HEALTH.clear()



# v62.13.9.4.40 — plafonds de sortie connus par famille de modèles (tokens). Valeur prudente
# par défaut quand le modèle n'est pas reconnu. À réviser quand un fournisseur relève ses limites.
_OUTPUT_CAPS40 = (
    # v62.13.9.4.50 — génération 5 : 128 000 jetons de sortie (fiche Claude Sonnet 5.5) ; avant « claude-opus » générique
    ("claude-sonnet-5", 128000), ("claude-opus-5", 128000), ("claude-fable-5", 128000),
    ("claude-opus", 32000), ("claude-sonnet-4", 64000), ("claude-3-7", 64000), ("claude-3-5", 8192),
    # anciens identifiants « claude-3-<famille> » : la ligne « claude-haiku » ne les couvre pas
    ("claude-3-opus", 4096), ("claude-3-sonnet", 4096), ("claude-3-haiku", 4096),
    ("claude-haiku", 8192), ("claude", 8192),
    ("gpt-4.1", 32768), ("gpt-4o-mini", 16384), ("gpt-4o", 16384), ("o3", 100000), ("o4", 100000), ("gpt-5", 128000),
    ("gpt-4-turbo", 4096), ("gpt", 16384),
    ("gemini-3", 65536),       # v62.13.9.4.50 — génération 3 (Flash GA) : 65 536 jetons de sortie
    ("gemini-2.5", 65536), ("gemini-2.0", 8192), ("gemini-1.5", 8192), ("gemini", 8192),
    ("mistral-large", 32768), ("mistral", 16384),
    # Perplexity : fiches modèles publiées à 8 000 ou 8 192 pour sonar-pro, 4 096 pour le
    # raisonnement — on retient la plus basse. xAI : contexte de 131 072 tokens entrée + sortie,
    # 16 000 en sortie au plus dans la console du fournisseur.
    ("perplexity/sonar", 8000),   # v62.13.9.4.50 — API Agent, même prudence que sonar-pro
    ("sonar-reasoning", 4096), ("sonar", 8000), ("grok", 16000),
)


def _model_output_cap40(tag: str, model: str) -> int:
    m = str(model or "").lower()
    for prefix, cap in _OUTPUT_CAPS40:
        if prefix in m:
            return cap
    t = str(tag or "").lower()
    return {"anthropic": 8192, "openai": 16384, "google": 8192, "mistral": 16384,
            "perplexity": 4096, "grok": 8192, "xai": 8192}.get(t, 4096)

def _safe_call(tag: str, func, *args, **kwargs) -> dict:
    # Refactor — frontière agents (A4, 2e couche) : AUCUN payload ne
    # part sous policy bloquée, même si un chemin ratait l'early-return.
    from patches.agent_prompt_boundary import (
        ensure_agent_payload_allowed as _eapa19)
    _eapa19(tag=tag)
    # v62.13.9.4.40 — BORNAGE AU PLAFOND RÉEL DU MODÈLE. Les planchers de sortie sont à la
    # dizaine de milliers supérieure (décision de Robin, 22/09/2026) ; un modèle qui n'accepte
    # que 8 192 ou 16 384 tokens de sortie REFUSE un appel qui en demande 20 000. On demande
    # donc le minimum entre le plancher et le plafond connu du modèle — jamais une erreur
    # d'API là où il y avait une coupure.
    try:
        if "max_tokens" in kwargs and kwargs["max_tokens"]:
            kwargs["max_tokens"] = min(int(kwargs["max_tokens"]), _model_output_cap40(tag, kwargs.get("model") or ""))
    except Exception:
        pass
    t0 = time.time()
    _down = _PROVIDER_HEALTH.get(tag)
    if _down and _down.get("down"):
        _PROVIDER_HEALTH[tag]["skipped"] = int(_down.get("skipped") or 0) + 1
        return {
            "output": f"[{tag} SKIPPED] fournisseur indisponible ({_down.get('reason')}) — aucun nouvel appel dans ce run",
            "provider": tag, "model": kwargs.get("model") or "", "tokens": {},
            "raw": {"skipped": True, "reason": _down.get("reason")}, "error": True, "skipped": True,
            "duration_s": 0.0,
        }
    try:
        resp = func(*args, **kwargs)
        output = None
        model = None
        provider = tag
        error = False
        raw = resp
        if isinstance(resp, dict):
            for k in ("output", "text", "content", "message", "result"):
                v = resp.get(k)
                if isinstance(v, str) and v.strip():
                    output = v
                    break
            if output is None:
                output = _as_output(resp)
            model = resp.get("model") or kwargs.get("model") or os.getenv(f"{tag.upper()}_MODEL", "")
            provider = resp.get("provider") or tag
            error = bool(resp.get("error"))
            tokens = _normalize_tokens(resp)
        else:
            output = _as_output(resp)
            model = kwargs.get("model") or os.getenv(f"{tag.upper()}_MODEL", "")
            tokens = {}
        if error:
            _kind = _classify_provider_error(str(output or "") + " " + str(raw or "")[:600])
            if _kind:
                _PROVIDER_HEALTH[tag] = {"down": True, "reason": _kind, "first_error": str(output or "")[:200],
                                         "at": round(time.time(), 0), "skipped": 0}
        return {
            "output": output,
            "truncated": bool(resp.get("truncated")) if isinstance(resp, dict) else False,   # v62.13.9.4.40
            "stop_reason": str(resp.get("stop_reason") or "") if isinstance(resp, dict) else "",
            "provider": provider,
            "model": model or "",
            "tokens": tokens,
            "raw": raw,
            "error": error,
            "duration_s": round(time.time() - t0, 3),
        }
    except Exception as e:
        tb = traceback.format_exc()
        _kind = _classify_provider_error(str(e))
        if _kind:
            _PROVIDER_HEALTH[tag] = {"down": True, "reason": _kind, "first_error": str(e)[:200],
                                     "at": round(time.time(), 0), "skipped": 0}
        return {
            "output": f"[{tag} ERROR] {e}",
            "provider": tag,
            "model": kwargs.get("model") or os.getenv(f"{tag.upper()}_MODEL", ""),
            "tokens": {},
            "raw": {"exception": repr(e), "traceback": tb},
            "error": True,
            "duration_s": round(time.time() - t0, 3),
        }


def _has_key(provider: str) -> bool:
    if provider == "openai":
        return bool(os.getenv("OPENAI_API_KEY", "").strip())
    if provider == "anthropic":
        return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())
    if provider in ("google", "gemini"):
        return bool(os.getenv("GOOGLE_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY", "").strip())
    if provider == "mistral":
        return bool(os.getenv("MISTRAL_API_KEY", "").strip())
    if provider == "perplexity":
        return bool(os.getenv("PERPLEXITY_API_KEY", "").strip())
    if provider == "grok":
        return bool(os.getenv("GROK_API_KEY", "").strip() or os.getenv("XAI_API_KEY", "").strip())
    return False


def _provider_callable(provider: str):
    if provider == "openai":
        return call_openai
    if provider == "anthropic":
        return call_claude
    if provider in ("google", "gemini"):
        return call_gemini
    if provider == "mistral":
        return call_mistral
    if provider == "perplexity":
        return call_perplexity
    if provider == "grok":
        return call_grok
    return None


def _model_id_for(provider: str, settings: Settings) -> str:
    # v62.13.9.4.50 — une variable d'environnement remplace toujours le réglage, mais elle est MIGRÉE comme lui : une
    # variable restée sur un modèle retiré (« ANTHROPIC_MODEL=claude-sonnet-4-5 ») ne rappelle plus ce modèle
    from utils.settings_store import env_model_override as _emo50, migrate_model_id as _mmi50
    if provider == "openai":
        return _emo50("openai") or _mmi50("openai", settings.openai_model_id)
    if provider == "anthropic":
        return _emo50("anthropic") or _mmi50("anthropic", settings.anthropic_model_id)
    if provider in ("google", "gemini"):
        return _emo50("google") or _mmi50("google", settings.google_model_id)
    if provider == "mistral":
        return _emo50("mistral") or settings.mistral_model_id
    if provider == "perplexity":
        return os.getenv("PERPLEXITY_MODEL") or settings.perplexity_model_id
    if provider == "grok":
        return os.getenv("GROK_MODEL") or settings.grok_model_id
    return ""


def _sc_model_id_for(stage: str, settings: Settings) -> str:
    """Dedicated model IDs for Supply Chain orchestration (v16.5.29+).

    IMPORTANT — provider lock by stage (v16.5.38):
      prefilter → always routed via OpenAI (call_openai)   → use an OpenAI model_id
      primary   → always routed via OpenAI (call_openai)   → use an OpenAI model_id
      challenge → always routed via Google  (call_gemini)  → use a Gemini model_id

    Env var overrides (CI/CD, advanced users):
      SC_PREFILTER_MODEL, SC_PRIMARY_MODEL, SC_CHALLENGE_MODEL
    """
    from utils.settings_store import migrate_model_id as _mmi50     # v62.13.9.4.50 — variables migrées aussi
    if stage == "prefilter":
        return _mmi50("openai", os.getenv("SC_PREFILTER_MODEL") or settings.sc_prefilter_model_id)
    if stage == "primary":
        return _mmi50("openai", os.getenv("SC_PRIMARY_MODEL") or settings.sc_primary_model_id)
    if stage == "challenge":
        return _mmi50("google", os.getenv("SC_CHALLENGE_MODEL") or settings.sc_challenge_model_id)
    return ""



def _line_lang40(text: str) -> str:
    """Langue dominante d'une réponse d'agent, pour la marque d'incomplétude (v62.13.9.4.40)."""
    try:
        from utils.editorial_quantity import line_language
        tail = " ".join(str(text or "").split()[-80:])
        return line_language(tail, "en")
    except Exception:
        return "fr"

# 9.4.57 — fenêtres de contexte prudentes par fournisseur (jetons), pour le filet d'ajustement ci-dessous
_WINDOW57 = {"anthropic": 1_000_000, "claude": 1_000_000,   # Claude Sonnet 5.5 : fenêtre de 1 M (documentation Anthropic)
             "openai": 400_000, "gpt": 400_000, "google": 1_000_000,
             "gemini": 1_000_000, "grok": 256_000, "xai": 256_000, "perplexity": 127_000, "mistral": 128_000}


def _fit_to_window57(provider: str, model_id: str, prompt: str, system: str, max_tokens: int):
    """Rend (prompt, None) si l'appel tient dans la fenêtre du modèle ; sinon coupe l'EXCÉDENT en fin de prompt (là où se
    trouvent les pièces jointes), insère une mention de coupe, et rend (prompt_ajusté, détail)."""
    p = str(prompt or "")
    win = _WINDOW57.get(str(provider or "").lower(), 128_000)
    budget = int(win * 0.92) - int(max_tokens or 0) - (len(str(system or "")) // 4) - 2_000
    est = len(p) // 4
    if budget <= 0 or est <= budget:
        return p, None
    keep = max(4_000, budget) * 4
    # la coupe porte sur le MILIEU du prompt (les pièces) : le début (contexte, brief) et la fin (consignes, format de
    # réponse attendu) sont toujours conservés
    head, tail = int(keep * 0.6), int(keep * 0.4)
    note = ("\n\n[… pièces coupées ici pour tenir dans la fenêtre du modèle " + str(model_id or provider)
            + " : " + str(est - budget) + " jetons environ non lus par cet appel ; le dossier complet en garde la trace]\n\n")
    return p[:head] + note + p[len(p) - tail:], {"tokens_before": est, "tokens_after": keep // 4, "window": win}


def _call_with_fallback(
    role: str,
    provider_order: List[str],
    prompt: str,
    system: str,
    temperature: float,
    max_tokens: int,
    settings: Settings,
    cb: Optional[StatusCallback] = None,
    diag_list: Optional[List[Dict[str, Any]]] = None,
    logger=None,
) -> Dict[str, Any]:
    # 9.4.53 — question du dirigeant (06/10/2026) : le réglage « Max output tokens » ne doit jamais brider un agent. Les
    # rôles principaux ont déjà leur plancher (10 000 à 20 000) sur le chemin nominal, mais les chemins de REPLI (Finance
    # par Claude quand Gemini est indisponible, par exemple) recevaient le réglage brut. Plancher par rôle ici, pour tous
    # les chemins ; le plafond réel du modèle reste appliqué dans _safe_call.
    try:
        # 9.4.58 — « qualité d'abord » (dirigeant, 10/10/2026) : la réflexion des modèles passe à un effort plus élevé ;
        # les planchers laissent la place à la réflexion ET à la réponse
        # 9.4.60 — décision du dirigeant (11/10/2026) : sortie au MAXIMUM de chaque modèle (128 000 pour Claude
        # Sonnet 5.5 et gpt-5.4, 65 536 pour Gemini 3, plafonds publiés pour Grok, Perplexity et Mistral) ; le bornage
        # au plafond réel du modèle se fait dans _safe_call, l'ajustement à la fenêtre juste avant l'appel
        _floor53 = 128000
        max_tokens = max(int(max_tokens or 0), _floor53)
    except Exception:
        pass
    attempts = 0
    last = None
    max_attempts = 1 if not settings.fallback_enabled else max(1, int(settings.fallback_max_attempts))
    for provider in provider_order:
        if attempts >= max_attempts:
            break
        fn = _provider_callable(provider)
        if not fn:
            continue
        if not _has_key(provider):
            continue
        attempts += 1
        if cb:
            cb(role, f"{role} — appel {provider} ({attempts}/{max_attempts})…")
        if logger:
            log_event(logger, "info", "codir_engine", "provider_request", role=role, provider=provider, attempt=attempts)
        model_id = _model_id_for(provider, settings)
        tag = provider if provider not in ("gemini",) else "google"
        t0 = time.time()
        # 9.4.57 — demande du dirigeant (10/10/2026) : aucune limite restrictive de lecture. Les budgets de lecture sont
        # relevés ; ce filet garantit qu'un appel tient dans la FENÊTRE du modèle appelé (repli compris) : seul l'excédent
        # des pièces est coupé, la coupe est signalée dans le texte et tracée au diagnostic — jamais un échec silencieux.
        _prompt57 = prompt
        # 9.4.59 — recette 9.4.58 : la synthèse des décisions (Perplexity, ~127 000 jetons) a été coupée de 181 000 à
        # 98 000 jetons. Qualité d'abord : si un fournisseur SUIVANT de la chaîne peut tout lire, on lui passe la main.
        # 9.4.60 — sortie effective = min(demande, plafond réel du modèle) ; si l'entrée et cette sortie ne tiennent pas
        # ensemble dans la fenêtre, c'est la SORTIE qui est réduite (8 000 jetons au moins), jamais les pièces
        _call_max60 = int(max_tokens or 0)
        try:
            _cap60 = min(int(max_tokens or 0), _model_output_cap40(tag, model_id))
            _in60 = (len(str(prompt or "")) + len(str(system or ""))) // 4 + 2_000
            _win60 = _WINDOW57.get(str(provider or "").lower(), 128_000)
            _call_max60 = max(8_000, min(_cap60, int(_win60 * 0.92) - _in60)) if _cap60 else _call_max60
        except Exception:
            _call_max60 = int(max_tokens or 0)
        try:
            _est59 = (len(str(prompt or "")) + len(str(system or ""))) // 4 + min(int(_call_max60 or 0), 8_000) + 2_000
            _win59 = _WINDOW57.get(str(provider or "").lower(), 128_000)
            if _est59 > int(_win59 * 0.92):
                _rest59 = list(provider_order)[list(provider_order).index(provider) + 1:] if provider in provider_order else []
                _better59 = [q for q in _rest59 if _WINDOW57.get(str(q).lower(), 128_000) * 0.92 >= _est59
                             and _provider_callable(q) and _has_key(q)]
                if _better59:
                    if isinstance(diag_list, list):
                        diag_list.append({"kind": "window_handoff59", "role": role, "from": provider, "to": _better59[0],
                                          "tokens": _est59})
                    attempts -= 1                 # le passage de main ne consomme pas une tentative
                    continue
        except Exception:
            pass
        try:
            _prompt57, _fit57 = _fit_to_window57(provider, model_id, prompt, system, _call_max60)
            if _fit57 and isinstance(diag_list, list):
                diag_list.append({"kind": "context_fit57", "role": role, "provider": provider, "model": model_id, **_fit57})
        except Exception:
            _prompt57 = prompt
        _LAST_CALL_KW40 = dict(prompt=_prompt57, system=system, temperature=temperature, max_tokens=_call_max60, model=model_id)
        res = _safe_call(tag, fn, prompt=_prompt57, system=system, temperature=temperature, max_tokens=_call_max60, model=model_id)
        # v62.13.9.4.40 — RÉPONSE COUPÉE PAR LA LIMITE DE SORTIE. Dossier réel du 21/09/2026 :
        # trois rôles s'arrêtaient en pleine phrase (sur un montant, au milieu d'une phrase) et le produit les
        # traitait comme complets. Une continuation unique est demandée (le modèle reprend là
        # où il s'est arrêté, sans répéter) ; si elle est encore coupée, la réponse est marquée
        # INCOMPLÈTE — jamais présentée comme une analyse close.
        try:
            if isinstance(res, dict) and res.get("truncated") and str(res.get("output") or "").strip():
                _prev40 = str(res.get("output") or "")
                _cont_prompt40 = (_prompt57 + "\n\n---\nYOUR PREVIOUS ANSWER WAS CUT BY THE OUTPUT LIMIT. Here is its end:\n"
                                  + _prev40[-1500:] + "\n---\nContinue EXACTLY where it stopped, without repeating anything "
                                  "already written, and finish the answer including any required final structured block.")
                try:
                    _res2 = _safe_call(tag, fn, prompt=_cont_prompt40, system=system, temperature=temperature, max_tokens=max_tokens,
                                       **({k: v for k, v in (_LAST_CALL_KW40 or {}).items() if k not in ("prompt", "system", "temperature", "max_tokens")}))
                except Exception:
                    _res2 = None
                if isinstance(_res2, dict) and str(_res2.get("output") or "").strip():
                    res = dict(res)
                    _nx40 = str(_res2.get("output") or "")
                    # reprise en pleine phrase (« $87 » + « m at … ») : pas de saut de ligne
                    _sep40 = "" if (_prev40[-1:].isalnum() and _nx40[:1].isalnum()) else ("" if _nx40[:1].isspace() else "\n")
                    res["output"] = _prev40 + _sep40 + _nx40
                    res["truncated"] = bool(_res2.get("truncated"))
                    res["continued"] = True
                if res.get("truncated"):
                    res["incomplete"] = True
                    res["output"] = str(res.get("output") or "").rstrip() + (
                        "\n\n[INCOMPLETE ANSWER — output limit reached; this section must be completed before use]"
                        if _line_lang40(_prev40) == "en" else
                        "\n\n[RÉPONSE INCOMPLÈTE — limite de sortie atteinte ; section à compléter avant usage]")
        except Exception:
            pass
        res["duration_s"] = round(time.time() - t0, 3)
        res["attempt"] = attempts
        res["role"] = role
        if diag_list is not None:
            try:
                diag_list.append({
                    "role": role,
                    "provider": res.get("provider", ""),
                    "model": res.get("model", ""),
                    "status": "ERROR" if res.get("error") else "OK",
                    "attempt": attempts,
                    "duration_s": res.get("duration_s", 0),
                    "tokens": res.get("tokens") or {},
                    "error": (res.get("raw") or {}).get("exception", "") if res.get("error") and isinstance(res.get("raw"), dict) else (res.get("output", "") if res.get("error") else ""),
                })
            except Exception:
                pass
        last = res
        if not res.get("error"):
            if logger:
                log_event(logger, "info", "codir_engine", "provider_success", role=role, provider=provider, model_id=model_id)
            return res
        if logger:
            log_event(logger, "warning", "codir_engine", "provider_error", role=role, provider=provider, model_id=model_id)
    return last or {"output": f"[{role} ERROR] Aucun provider disponible (clé manquante ?)", "error": True, "provider": "none", "model": ""}


def _continue_if_truncated60(tag, fn, prompt, system, temperature, max_tokens, model, res):
    """9.4.60 — reprise d'une réponse arrêtée sur la limite de sortie, pour les appels directs hors circuit commun.
    Jusqu'à deux reprises bornées ; si la réponse reste coupée, elle est marquée INCOMPLÈTE en place."""
    try:
        for _n60 in range(2):
            if not (isinstance(res, dict) and res.get("truncated") and str(res.get("output") or "").strip()):
                break
            prev = str(res.get("output") or "")
            cont = (str(prompt or "") + "\n\n---\nYOUR PREVIOUS ANSWER WAS CUT BY THE OUTPUT LIMIT. Here is its end:\n"
                    + prev[-1500:] + "\n---\nContinue EXACTLY where it stopped, without repeating anything already "
                    "written, and finish the answer including any required final structured block.")
            try:
                r2 = _safe_call(tag, fn, prompt=cont, system=system, temperature=temperature, max_tokens=max_tokens, model=model)
            except Exception:
                r2 = None
            if not (isinstance(r2, dict) and str(r2.get("output") or "").strip()):
                break
            nx = str(r2.get("output") or "")
            sep = "" if (prev[-1:].isalnum() and nx[:1].isalnum()) else ("" if nx[:1].isspace() else "\n")
            res = dict(res)
            res["output"] = prev + sep + nx
            res["truncated"] = bool(r2.get("truncated"))
            res["continued"] = int(res.get("continued") or 0) + 1
        if isinstance(res, dict) and res.get("truncated"):
            res["incomplete"] = True
            res["output"] = str(res.get("output") or "").rstrip() + (
                "\n\n[RÉPONSE INCOMPLÈTE — limite de sortie atteinte ; section à compléter avant usage]")
    except Exception:
        pass
    return res


def _claude_challenge_finance(
    gemini_output: str,
    brief_codir_txt: str,
    marketing_txt: str,
    brief: str,
    pass_num: int,
    previous_challenge: str,
    temperature: float,
    max_tokens: int,
    settings: Settings,
    cb: Optional[StatusCallback] = None,
    diag_list: Optional[List[Dict[str, Any]]] = None,
    logger=None,
) -> Dict[str, Any]:
    """Claude challenges and enriches Gemini finance output. 2 passes."""
    lang = _lang(settings)
    role = f"finance_challenge_claude_{pass_num}"
    if cb:
        cb(role, f"{'Finance' if lang == 'fr' else 'Finance'} — {'Challenge Claude' if lang == 'fr' else 'Claude challenge'} #{pass_num}/2…")

    source = gemini_output if pass_num == 1 else previous_challenge

    if lang == "en":
        prompt = (
            f"Role: Critical and rigorous CFO (pass {pass_num}/2).\n"
            "Objective: challenge and improve the Finance analysis below.\n"
            "Instructions:\n"
            "  - Identify gaps, unsubstantiated assumptions, forgotten risks, suspect figures.\n"
            "  - Correct, enrich and consolidate. Produce an IMPROVED FINAL version (not just a comment).\n"
            "  - Keep the format: bullets, explicit assumptions, 3 risks & mitigations.\n"
        )
        if pass_num == 2:
            prompt += "  - (Pass 2 final: incorporate the previous critique to produce the definitive synthesis.)\n"
        prompt += f"---\nFinance analysis to challenge:\n{source}\n"
        if pass_num == 2 and previous_challenge and previous_challenge != source:
            prompt += f"---\nPrevious challenge (pass 1):\n{previous_challenge}\n"
        prompt += f"---\nBoard Brief:\n{brief_codir_txt}\n---\nMarketing:\n{marketing_txt}\n---\nInitial brief:\n{brief}"
        system = "You are a demanding senior CFO. You challenge and then produce an improved and consolidated final Finance analysis."
    else:
        prompt = (
            f"Rôle: DAF critique et rigoureux (pass {pass_num}/2).\n"
            "Objectif: challenger et améliorer l'analyse Finance ci-dessous.\n"
            "Instructions:\n"
            "  - Identifie les lacunes, hypothèses non fondées, risques oubliés, chiffres suspects.\n"
            "  - Corrige, enrichis et consolide. Produis une version FINALE améliorée (pas un simple commentaire).\n"
            "  - Garde le format: bullets, hypothèses explicites, 3 risques & parades.\n"
        )
        if pass_num == 2:
            prompt += "  - (Pass 2 final: prends en compte la critique précédente pour produire la synthèse définitive.)\n"
        prompt += f"---\nAnalyse Finance à challenger:\n{source}\n"
        if pass_num == 2 and previous_challenge and previous_challenge != source:
            prompt += f"---\nChallenge précédent (pass 1):\n{previous_challenge}\n"
        prompt += f"---\nBrief CoDIR:\n{brief_codir_txt}\n---\nMarketing:\n{marketing_txt}\n---\nBrief initial:\n{brief}"
        system = "Tu es un DAF senior exigeant. Tu challenges puis produis une analyse Finance finale, améliorée et consolidée."

    # v16.5.67 F1 — schema_instruction EN TÊTE du challenge #2 final
    # (pas #1 pour ne pas fatiguer inutilement, mais #2 est la source de vérité du JSON)
    if pass_num == 2 and _USE_AGENT_JSON and _schema_instruction is not None:
        schema_head = (
            "IMPÉRATIF DE FORMAT — consigne non négociable :\n"
            "Tu dois terminer ta réponse par le bloc JSON structuré "
            "---AGENT_JSON_START--- ... ---AGENT_JSON_END---. "
            "Le pipeline de scoring en dépend. Schéma détaillé en fin de prompt.\n\n"
            "---\n\n"
        )
        prompt = schema_head + prompt + _schema_instruction(lang)

    if not call_claude or not _has_key("anthropic"):
        return {
            "output": source,
            "provider": "anthropic",
            "model": settings.anthropic_model_id,
            "tokens": {},
            "error": True,
            "role": role,
            "raw": {"exception": "ANTHROPIC_API_KEY manquante ou call_claude indisponible"},
        }

    model_id = _model_id_for("anthropic", settings)
    t0 = time.time()
    res = _safe_call("anthropic", call_claude, prompt=prompt, system=_lang_wrap(system, lang), temperature=temperature, max_tokens=max_tokens, model=model_id)
    # 9.4.60 — contre-recette du 11/10 (F59-02) : ce challenge appelle Claude en direct, hors du circuit commun ; une
    # réponse arrêtée sur la limite de sortie n'était jamais reprise (CR S2/S3 coupés en pleine phrase). Même règle
    # que le circuit commun : reprise sur le SIGNAL du fournisseur, sinon mention « réponse incomplète » en place.
    res = _continue_if_truncated60("anthropic", call_claude, prompt, _lang_wrap(system, lang), temperature, max_tokens,
                                   _model_id_for("anthropic", settings), res)
    res["duration_s"] = round(time.time() - t0, 3)
    res["attempt"] = 1
    res["role"] = role

    if diag_list is not None:
        try:
            diag_list.append({
                "role": role,
                "provider": "anthropic",
                "model": res.get("model", ""),
                "status": "ERROR" if res.get("error") else "OK",
                "attempt": 1,
                "duration_s": res.get("duration_s", 0),
                "tokens": res.get("tokens") or {},
                "error": (res.get("raw") or {}).get("exception", "") if res.get("error") else "",
            })
        except Exception:
            pass

    if logger:
        lvl = "warning" if res.get("error") else "info"
        log_event(logger, lvl, "codir_engine", "finance_challenge", pass_num=pass_num, status="ERROR" if res.get("error") else "OK")

    return res


def _b23b_prompt_rules_base(lang: str = "fr") -> dict:
    """v17.1-B2.3-B — Règles de DISCIPLINE de forme injectées dans les prompts
    agents (validées via le diff lecture seule + audit ChatGPT ; règle 5 amendée
    « tranche prudemment »). Elles n'injectent AUCUN fait/valeur/source (zéro
    hardcoding) : elles imposent la rigueur (métrique↔valeur↔périmètre↔source),
    l'orientation cible, le sourcing fort, la discipline cotation et décision.
    La latitude analytique de l'agent est préservée — on guide la forme, pas la
    conclusion. Réf : docs/B2.3-B_PROMPTS_DIFF_READONLY.md."""
    if lang == "en":
        return {
            "metric": ("\nMETRIC DISCIPLINE (non-negotiable): every figure = a tuple "
                       "(canonical metric, value, period, scope, source). A value identified "
                       "as NET INCOME must NEVER reappear labelled EBITDA, cash burn or "
                       "operating cash flow, and vice-versa. If unsure of a figure's metric, "
                       "say so ([TO ARBITRATE]) rather than guess.\n"),
            "orientation": ("\nANALYSIS OBJECT: the TARGET designated by the mandate (entity "
                            "being acquired / invested in / valued), NOT the sponsor's entity. "
                            "Orient the financial analysis on the target; treat the sponsor / "
                            "acquirer as a COUNTERPARTY whose figures do not substitute for the "
                            "target's.\n"),
            "sourcing": ("\nSOURCING: for EACH consolidated figure, cite the PRIMARY documentary "
                         "source (annual report / registration document / results press release "
                         "+ page if possible). The 'Brief' is NOT a sufficient source for a "
                         "consolidated figure presented as board-safe: if it's your only source, "
                         "mark [ESTIM-*] and state the missing data.\n"),
            "cotation": ("\nLISTING STATUS: only assert 'listed' / 'not listed' if a strong source "
                         "establishes it (ISIN, exchange, regulator, registration document). "
                         "Otherwise write 'listing status to be verified' — never infer "
                         "non-listing from the brief or from a company registry.\n"),
            "decision": ("\nRECOMMENDATION: a single final recommendation (GO / NO-GO / "
                         "conditional GO) with conviction. If roles diverge, MAKE the divergence "
                         "explicit and recommend PRUDENTLY; if data is blocking, the final "
                         "recommendation must be able to be NO-GO, or a conditional GO LIMITED to "
                         "an instruction / due diligence, WITHOUT authorising any equity "
                         "commitment. Do not let a firm NO-GO and a conditional GO coexist as if "
                         "compatible.\n"),
        }
    return {
        "metric": ("\nDISCIPLINE MÉTRIQUE (non négociable) : chaque chiffre = un couple "
                   "(métrique canonique, valeur, période, périmètre, source). Une valeur "
                   "identifiée comme RÉSULTAT NET ne doit JAMAIS réapparaître étiquetée EBITDA, "
                   "cash burn ou flux opérationnel, et inversement. Si tu n'es pas sûr de la "
                   "métrique d'un montant, dis-le ([À ARBITRER]) plutôt que de deviner.\n"),
        "orientation": ("\nOBJET DE L'ANALYSE : la CIBLE désignée par le mandat (entité faisant "
                        "l'objet d'une acquisition / prise de participation / valorisation), PAS "
                        "l'entité du donneur d'ordre. Oriente l'analyse financière sur la cible ; "
                        "traite le sponsor / acquéreur comme une CONTREPARTIE, dont les chiffres "
                        "ne se substituent pas à ceux de la cible.\n"),
        "sourcing": ("\nSOURCING : pour CHAQUE chiffre consolidé, cite la source documentaire "
                     "PRIMAIRE (RFA / URD / communiqué de résultats + page si possible). "
                     "« Brief CoDIR » n'est PAS une source suffisante pour un chiffre consolidé "
                     "présenté comme board-safe : si c'est ta seule source, marque [ESTIM-*] et "
                     "explicite la donnée manquante.\n"),
        "cotation": ("\nSTATUT BOURSIER : n'affirme « coté » / « non coté » que si une source "
                     "forte l'établit (ISIN, Euronext/marché, AMF, document d'enregistrement). À "
                     "défaut, écris « statut boursier à vérifier » — n'infère jamais la "
                     "non-cotation depuis le brief ou Pappers.\n"),
        "decision": ("\nRECOMMANDATION : une seule recommandation finale (GO / NO-GO / GO "
                     "conditionnel) avec conviction. Si les rôles divergent, EXPLICITE la "
                     "divergence et recommande PRUDEMMENT ; si les données sont bloquantes, la "
                     "recommandation finale doit pouvoir être NO-GO, ou GO conditionnel LIMITÉ à "
                     "une instruction / due diligence, SANS autoriser d'engagement capitalistique. "
                     "Ne laisse pas coexister un NO-GO ferme et un GO conditionnel comme s'ils "
                     "étaient compatibles.\n"),
    }


def _b23b_prompt_rules(lang: str = "fr", genre: str = "MA_DECISION") -> dict:
    """v17.1.0-B2.3-F — Wrapper conscient du GENRE de point d'agenda.

    Pour un point M&A (défaut) : comportement historique strictement inchangé.
    Pour un point NON décisionnel (étude de marché / développement d'activité) :
      - règle « décision » remplacée par une consigne CADRAGE / PLAN (pas de
        GO/NO-GO capitalistique) ;
      - règle « finance_tone » ajoutée (ton consultatif : Pappers est aveugle à
        l'activité réelle d'une structure de conseil — pas d'« anomalie critique »).
    Aucun fait n'est injecté : on guide la FORME de l'objet, pas la conclusion."""
    rules = dict(_b23b_prompt_rules_base(lang))
    if genre == "MA_DECISION":
        return rules
    # ── Objet de l'analyse : neutraliser le cadrage « cible d'acquisition ». ──
    # (Correctif B2.3-F.1 — la règle « orientation » de base impose d'orienter
    # l'analyse sur la CIBLE désignée par le mandat ; pour un point non-M&A, c'est
    # un faux cadre. Consommé par Stratégie ET Finance.)
    if lang == "en":
        rules["orientation"] = (
            "\nANALYSIS OBJECT: the SUBJECT of this agenda item (market, activity, project, "
            "management topic) — NOT an acquisition target. Do NOT apply any sponsor/target "
            "logic nor a 'target designated by the mandate' framing.\n")
        rules["decision"] = (
            "\nDELIVERABLE OBJECT: this agenda item is NOT an acquisition decision. Do NOT "
            "produce a capital GO/NO-GO. Produce a FRAMING: context/stakes, 2-3 argued options, "
            "an ACTION PLAN (owners, deadlines), follow-up points. Reserve any 'NO-GO' for "
            "'external presentation as-is' and distinguish it from a 'GO' on the internal action "
            "plan.\n")
    else:
        rules["orientation"] = (
            "\nOBJET DE L'ANALYSE : le SUJET de ce point d'agenda (marché, activité, chantier, "
            "sujet de direction) — PAS une cible d'acquisition. N'applique aucune logique "
            "sponsor/cible ni orientation « cible désignée par le mandat ».\n")
        rules["decision"] = (
            "\nOBJET DU LIVRABLE : ce point d'agenda n'est PAS une décision d'acquisition. Ne "
            "produis PAS de GO/NO-GO capitalistique. Produis un CADRAGE : contexte/enjeu, 2-3 "
            "options argumentées, un PLAN D'ACTION (porteurs, échéances), des points de suivi. "
            "Réserve tout « NO-GO » à l'usage « présentation externe en l'état » et distingue-le "
            "d'un « GO » sur le plan d'action interne.\n")
    # ── Ton financier consultatif : SEULEMENT pour les genres « advisory ». ──
    # FINANCE_REVIEW et TURNAROUND_REVIEW gardent la rigueur board (entité réelle
    # sous revue / situation de distress) → pas de softening « 0 salarié ≠ anomalie ».
    if genre not in ("FINANCE_REVIEW", "TURNAROUND_REVIEW", "STRATEGIC_PLAN"):
        if lang == "en":
            rules["finance_tone"] = (
                "\nFINANCIAL TONE: for an advisory / SME / single-person entity, do NOT read "
                "'0 employees' or a low/zero net result as a critical anomaly — public filings are "
                "structurally blind to real activity. Write 'public data insufficient to assess "
                "real activity', not 'critical anomaly'.\n")
        else:
            rules["finance_tone"] = (
                "\nTON FINANCIER : pour une structure de conseil / PME / unipersonnelle, "
                "n'interprète pas « 0 salarié » ou un résultat net faible/nul comme une anomalie "
                "critique — les données publiques (Pappers) sont structurellement aveugles à "
                "l'activité réelle. Formule « données publiques insuffisantes pour juger "
                "l'activité réelle », pas « anomalie critique ».\n")
    return rules


def _temporal_boundary_lifecycle19(fn):
    """Correctif TCR — cycle de vie de la frontière agents : la policy
    posée pour le run MEURT avec lui, y compris sur exception
    (finally). Aucun résidu ne peut armer ou désarmer la frontière
    d'un appel hors-run ou d'un run suivant. Décorateur (et non
    wrapper séparé) : le FunctionDef run_codir_session reste intact
    pour l'analyse statique (signature, clés de retour)."""
    import functools as _ft19

    @_ft19.wraps(fn)
    def _wrapped(*a, **k):
        # Correctif TCR-v6 (lifecycle) — cycle de vie par TOKENS : les
        # trois états contextuels (policy frontière + date d'analyse +
        # mode attach-only) sont RESTAURÉS à leur valeur d'entrée en
        # finally, sur tous les chemins (nominal, early-return,
        # exception). Zéro résidu après le run ; un run imbriqué
        # restaure la frontière de son appelant au lieu de l'effacer.
        _tok_pol19 = _tok_aod19 = _tok_src19 = None
        try:
            from patches.agent_prompt_boundary import (
                get_current_policy as _gcp19w,
                set_current_policy as _scp19w)
            _tok_pol19 = _scp19w(_gcp19w())
        except Exception:
            pass
        _tok_ctx19 = None
        try:
            _tok_aod19 = _ANALYSIS_AS_OF.set(_ANALYSIS_AS_OF.get())
            _tok_src19 = _SOURCE_ATTACH_ONLY.set(_SOURCE_ATTACH_ONLY.get())
            _tok_ctx19 = _TEMPORAL_CTX.set(_TEMPORAL_CTX.get())
        except Exception:
            pass
        try:
            return fn(*a, **k)
        finally:
            try:
                if _tok_aod19 is not None:
                    _ANALYSIS_AS_OF.reset(_tok_aod19)
                if _tok_src19 is not None:
                    _SOURCE_ATTACH_ONLY.reset(_tok_src19)
                if _tok_ctx19 is not None:
                    _TEMPORAL_CTX.reset(_tok_ctx19)
            except Exception:
                pass
            try:
                from patches.agent_prompt_boundary import (
                    reset_policy_token as _rpt19)
                if _tok_pol19 is not None:
                    _rpt19(_tok_pol19)
            except Exception:
                try:
                    from patches.agent_prompt_boundary import (
                        set_current_policy as _scp_fin19)
                    _scp_fin19(None)
                except Exception:
                    pass
    return _wrapped


@_temporal_boundary_lifecycle19
def run_codir_session(
    brief: str,
    temperature: float = 0.4,
    max_tokens: int = 2000,
    attachments_block: str = "",
    attachments_meta: Optional[Dict[str, Any]] = None,
    cb: Optional[StatusCallback] = None,
    settings: Optional[Settings] = None,
    logger=None,
    pappers_skip: bool = False,
    pappers_confirmed_entity: str = "",
    # Since v16.5.69 — Découplage Pappers : nouveaux flags indépendants.
    # Si non fournis, on garde la rétro-compatibilité : external_sources_skip
    # hérite de pappers_skip (comportement v16.5.68).
    external_sources_skip: Optional[bool] = None,
    confirmed_target_entity: Optional[Any] = None,  # TargetEntity ou None
    # Since v16.5.70 — Financial Statements Block (lecture états financiers PDF)
    # Bloc texte séparé issu de l'extraction prioritaire des sections financières
    # (Income Statement, Balance Sheet, Cash Flow, Notes) depuis les PDFs uploadés.
    # Préparé en amont par app.py via utils/financial_statement_extractor.py.
    # Injecté explicitement dans les prompts Finance / DG / Synthèse via le helper
    # _fs_ctx(role) — pas seulement dans attachments_block générique.
    financial_statements_block: str = "",
    # Bundles détaillés pour diagnostics (1 par PDF scanné). Optionnel.
    financial_statements_bundles: Optional[List[Any]] = None,
    # Correctif TCR-v5 (P0 contexte unique) — l'application transmet
    # l'instance TemporalContext construite par SON préflight ; le
    # moteur la consomme après vérification d'empreinte (brief +
    # champ structuré), sans recalcul. Absent (appels bibliothèque) :
    # le moteur construit le sien — même code, mêmes entrées.
    temporal_context: Optional[Any] = None,
    # Correctif TCR-v10 (verdict v9, P0-3) — empreinte de l'ENTRÉE
    # TEMPORELLE COURANTE (TemporalControlInput.input_fingerprint) telle
    # que l'application la déclare. Le moteur ne se contente plus de
    # recevoir un contexte : il exige la PREUVE que ce contexte a été
    # résolu sur cette photographie-là.
    temporal_input_fingerprint: str = "",
) -> Dict[str, Any]:
    settings = settings or load_settings()
    lang = _lang(settings)          # "fr" | "en" — v16.5.38
    reset_provider_health()         # v62.13.9.4.23 — l'état des fournisseurs est celui de CE run
    brief = render_brief(brief)
    try:   # 9.4.51 — réalisations déclarées par le dirigeant, connues du garde de statut pendant tout le run
        from patches.codir_register_history import set_brief_declarations51 as _sbd51
        _sbd51(brief)
    except Exception:
        pass
    # v62.8 — le texte explicite de l'utilisateur est l'autorité temporelle :
    # « plan stratégique à 2 ans » ne peut pas être réduit à « + 1 an » par
    # un champ structuré reconstruit en amont.
    _horizon_reconciliation = None
    try:
        from patches.strategic_horizon import reconcile_strategic_horizon as _rsh628
        # The application canonicalises and binds the exact assembled brief.
        # The engine may reconcile the horizon value idempotently, but must not
        # append a new target-end line after a TemporalContext has been signed.
        # Otherwise a valid bound context would fail its own brief fingerprint.
        brief, _horizon_reconciliation = _rsh628(
            brief,
            run_date=None,
            lang=lang,
        )
    except Exception:
        _horizon_reconciliation = None
    diag_list: List[Dict[str, Any]] = []
    # v62.13.9.4.12.2 — registre d'archivage vidé à chaque run : deux runs
    # successifs dans le même processus ne doivent pas se mélanger.
    _AGENT_RAW_ARCHIVE.clear()
    if _horizon_reconciliation is not None:
        try:
            _hrd = _horizon_reconciliation.to_dict()
            if _hrd.get("explicit_months"):
                diag_list.append({
                    "role": "strategic_horizon", "provider": "internal",
                    "model": "strategic_horizon_v628",
                    "status": "RECONCILED" if _hrd.get("changed") else "OK",
                    **_hrd,
                })
        except Exception:
            pass

    # ─── v17.1.0-B2.3-F — Détection du GENRE de point d'agenda ────────────────
    # Route l'objet produit (décision M&A vs cadrage/plan), le ton financier et
    # le web-sourcing. Fail-open : en cas d'erreur, on retombe sur le genre M&A
    # (comportement historique strictement préservé).
    try:
        from patches.agenda_genre import detect_agenda_genre as _detect_genre
        _genre = _detect_genre(brief)
    except Exception:
        from patches.agenda_genre import GenreResult as _GR
        _genre = _GR(genre="MA_DECISION", confidence=0.0, decision_mode="GO_NOGO",
                     finance_tone="BOARD_SCRUTINY")
    try:
        diag_list.append({
            "role": "agenda_genre", "provider": "internal",
            "model": "agenda_genre_v1", "status": "OK",
            "genre": _genre.genre, "decision_mode": _genre.decision_mode,
            "finance_tone": _genre.finance_tone,
            "research_topic": _genre.research_topic or "",
            "genre_confidence": round(_genre.confidence, 2),
        })
    except Exception:
        pass

    # ── F.6.7 — Gouvernance pilotée par le brief (source_mode + date d'analyse) ──
    _attachments_only = False
    try:
        from patches import a1_probe as _a1p
        _a1p.reset()
        _a1p.put(lang=lang, run_version=globals().get("BUILD_VERSION", ""))
    except Exception:
        pass
    _analysis_as_of = None
    _temporal_exception_type = ""
    _temporal_exception_message = ""
    _temporal_exception_stage = ""
    try:
        # ═══ Gate 17 — HORLOGE RACINE : la date réelle de la session est
        # capturée UNE SEULE fois, ici, AVANT toute détection et toute
        # policy, puis propagée bit-à-bit (policy, result, registre,
        # renderers). Aucune autre horloge directe dans la vérité.
        from utils.metadata_clock import run_now as _mc_run_now17
        _run_now = _mc_run_now17()
        from patches.mission_governance import (detect_source_mode as _dsm,
                                                detect_analysis_as_of_date as _daod)
        _source_mode = _dsm(brief)
        _attachments_only = (_source_mode == "ATTACHMENTS_ONLY")
        # ═══ Refactor Temporal Core — le CONTEXTE TEMPOREL remplace la
        # détection nue : entrée STRUCTURÉE (settings.analysis_as_of_date,
        # rang 1) > label contractuel (rang 2) > inférence legacy
        # qualifiée (rang 3) > live. Fail-closed : structuré malformé →
        # ERROR ; structuré vs label contractuel divergent → CONFLICT ;
        # directive certaine à valeur indéterminable → AMBIGUOUS.
        # L'horloge racine déjà capturée est INJECTÉE (jamais recapturée).
        from patches.temporal_context import (resolve_temporal_context
                                              as _rtc19)
        # Correctif TCR — TOUTES les sources vivent DANS le contexte :
        # la compatibilité « revue de clôture » (ex-F.6.8) y entre comme
        # CANDIDATE confirmable via closing_review_hint (le fallback
        # post-contexte est supprimé — plus aucune autorité hors
        # hiérarchie).
        _structured_in = str(getattr(settings, "analysis_as_of_date", "")
                             or "")
        _ctx_reused = False
        if temporal_context is not None:
            # v62.9 — contrat centralisé et testé de bout en bout. Le brief
            # a déjà été canonicalisé par l'application avant sa liaison ;
            # l'appel idempotent en tête du moteur ne doit donc plus changer
            # son empreinte.
            from patches.temporal_context import validate_bound_context as _vbc629
            _vbc629(temporal_context, brief, _structured_in,
                    temporal_input_fingerprint)
            # Instance app CONSOMMÉE telle quelle — un seul contexte
            # par session, aucune double résolution, et UNE SEULE HORLOGE.
            _tctx19 = temporal_context
            _ctx_reused = True
            try:
                _run_now = temporal_context.run_now
            except Exception:
                pass
        if not _ctx_reused:
            _tctx19 = _rtc19(brief,
                             _structured_in,
                             clock=lambda: _run_now,
                             closing_review_hint=bool(
                                 getattr(_genre, "forbids_go_nogo", False)))
        _scenario_probe = {
            "status": _tctx19.scenario_status,
            "value": _tctx19.scenario_value,
            "raw": _tctx19.scenario_raw,
            "error_code": _tctx19.error_code,
            "conflict": _tctx19.conflict,
            "candidates": list(_tctx19.candidates),
            "intent_source": _tctx19.intent_source,
            "candidate_value": _tctx19.candidate_value,
            "candidate_raw": _tctx19.candidate_raw,
        }
        _scenario_status = _scenario_probe.get("status", "NOT_REQUESTED")
        _scenario_raw = _scenario_probe.get("raw", "")
        _analysis_as_of = _scenario_probe.get("value")
    except Exception as _temporal_exc:
        _source_mode = "OPEN"
        # Gate 13 — une panne de la frontière temporelle est une panne de
        # VÉRITÉ : fail-closed ERROR (jamais interprétée comme « pas de
        # scénario »). v62.9 conserve toutefois le type et le message exacts
        # dans les diagnostics : l'utilisateur ne doit plus être invité à
        # corriger sa date lorsque l'incident est une incohérence interne.
        _temporal_exception_type = type(_temporal_exc).__name__
        _temporal_exception_message = str(_temporal_exc)[:500]
        _temporal_exception_stage = "temporal_context_reuse_or_resolution"
        _scenario_status = "ERROR"
        _scenario_raw = (_temporal_exception_message or "detector failure")
        _analysis_as_of = None
    # F.6.7-01 — mode pièces jointes : coupe TOUTES les sources externes en amont
    # (Pappers + GLEIF/SEC/OpenSanctions/Companies House + recherche web).
    if _attachments_only:
        pappers_skip = True
        external_sources_skip = True
    # F.6.7-02 — date d'analyse simulée propagée au contexte temporel des agents.
    _set_analysis_as_of(_analysis_as_of)
    # TCR-v7 — le contexte du run (consommé de l'app ou construit ici)
    # devient l'autorité des prompts pour TOUTE la durée du run.
    try:
        _TEMPORAL_CTX.set(_tctx19)
    except Exception:
        pass
    # ═══ Gate 16 → Correctif TCR : LA politique vient du CONTEXTE
    # (résolue UNE fois dans resolve_temporal_context). Le moteur ne
    # rappelle JAMAIS resolve_temporal_policy — TemporalContext est
    # l'autorité racine unique. Tous les sinks consultent can_persist.
    try:
        _temporal_policy16 = _tctx19.policy
    except Exception:
        from patches.temporal_policy import (TemporalExecutionPolicy
                                             as _TEP16)
        _temporal_policy16 = _TEP16()  # défaut v3 = BLOCKED_ERROR immuable
    # ═══ Gate 18 — une policy BLOQUÉE gouverne le RUN ENTIER : si le
    # résolveur a rendu (ou est retombé sur) BLOCKED_* alors que le
    # détecteur de scénario n'avait rien bloqué, c'est une PANNE de la
    # politique temporelle → le run devient ERROR fail-closed par le
    # CANAL UNIQUE existant (run_validatable=False, bandeau, zéro
    # lecture feed-forward, zéro bloc registre, zéro écriture).
    try:
        if (getattr(_temporal_policy16, "mode", "").startswith("BLOCKED")
                and _scenario_status not in ("INVALID", "ERROR",
                                             "AMBIGUOUS")):
            _scenario_status = "ERROR"
            _scenario_raw = "temporal policy unavailable"
            if isinstance(locals().get("_scenario_probe"), dict):
                _scenario_probe["error_code"] = "TEMPORAL_POLICY_ERROR"
            # Gate 19 — une panne EFFACE TOUTE autorité simulée : le
            # GLOBAL agents (blocs « DATE D'ANALYSE SIMULÉE » des
            # prompts) et la valeur locale (retards, hygiène) — aucun
            # agent ne raisonne sous une autorité que le run déclare
            # indisponible.
            _analysis_as_of = None
            _set_analysis_as_of(None)
    except Exception:
        _scenario_status = "ERROR"
        try:
            _analysis_as_of = None
            _set_analysis_as_of(None)
        except Exception:
            pass
    # ═══ Refactor Temporal Core — la policy du RUN est publiée à la
    # frontière agents (2e couche derrière l'early-return : même un
    # chemin futur qui raterait l'early-return ne peut pas émettre).
    try:
        from patches.agent_prompt_boundary import (set_current_policy
                                                   as _scp19)
        _scp19(_temporal_policy16)
    except Exception:
        pass
    # ═══ Refactor Temporal Core — EARLY-RETURN sous policy BLOQUÉE :
    # le run s'arrête ICI, avant TOUT assemblage de payload agent
    # (system ET user), toute lecture d'historique, toute source
    # externe, tout writer. Zéro appel provider, zéro coût, zéro fuite
    # du brief porteur d'une autorité en échec (la ligne « raw brief »
    # du verdict gate 19). Le résultat minimal reste STRUCTURELLEMENT
    # compatible avec les surfaces : mêmes formes run_block_reasons /
    # b23_guards / diagnostics que le canal gate 13.
    if getattr(_temporal_policy16, "mode", "").startswith("BLOCKED"):
        try:
            _analysis_as_of = None
            _set_analysis_as_of(None)  # purge idempotente
        except Exception:
            pass
        _rd_er = ""
        try:
            _rd_er = _run_now.date().isoformat()
        except Exception:
            pass
        _pol_ser = (_temporal_policy16.to_dict()
                    if hasattr(_temporal_policy16, "to_dict") else {})
        _msg_fr = getattr(_temporal_policy16, "user_message_fr", "")
        _msg_en = getattr(_temporal_policy16, "user_message_en", "")
        _probe_er = (_scenario_probe
                     if isinstance(locals().get("_scenario_probe"), dict)
                     else {})
        _code_er = (_probe_er.get("error_code")
                    or ("TEMPORAL_AUTHORITY_INVALID"
                        if _scenario_status == "INVALID"
                        else ("TEMPORAL_AUTHORITY_AMBIGUOUS"
                              if _scenario_status == "AMBIGUOUS"
                              else "TEMPORAL_AUTHORITY_ERROR")))
        _mode_er = getattr(_temporal_policy16, "mode", "")
        if _mode_er == "BLOCKED_AMBIGUOUS":
            _banner_fr = ("⛔ Demande temporelle ambiguë — le brief suggère "
                          "une date d'analyse sans permettre de la "
                          "déterminer sûrement (" + str(_scenario_raw)
                          + ") : présentation client, conseil et "
                            "diffusion BLOQUÉS. Saisissez la date dans "
                            "Réglages ou reformulez.")
            _banner_en = ("⛔ Ambiguous temporal request — the brief "
                          "suggests an analysis date that cannot be "
                          "determined safely (" + str(_scenario_raw)
                          + "): client presentation, advice and "
                            "distribution BLOCKED. Set the date in "
                            "Settings or rephrase.")
        elif _scenario_status == "ERROR":
            _internal_mismatch = (
                "mismatch" in str(_temporal_exception_message or "").lower()
                or "binding" in str(_temporal_exception_message or "").lower())
            if _internal_mismatch:
                _banner_fr = ("⛔ Incohérence interne du contexte temporel — "
                              "votre date et votre brief ne sont pas en cause. "
                              "Le run est arrêté sans appel IA ; relancez "
                              "l'application et transmettez le diagnostic si "
                              "l'incident persiste.")
                _banner_en = ("⛔ Internal temporal-context inconsistency — "
                              "your date and brief are not at fault. The run "
                              "was stopped before any AI call; restart the "
                              "application and share the diagnostic if it "
                              "persists.")
            else:
                _banner_fr = ("⛔ Autorité temporelle indisponible — panne du "
                              "détecteur de date d'analyse : présentation "
                              "client, conseil et diffusion BLOQUÉS.")
                _banner_en = ("⛔ Temporal authority unavailable — "
                              "analysis-date detector failure: client "
                              "presentation, advice and distribution BLOCKED.")
        elif _code_er == "TEMPORAL_AUTHORITY_CONFLICT":
            _banner_fr = ("⛔ Autorité temporelle en conflit — deux "
                          "dates d'analyse distinctes demandées ("
                          + str(_scenario_raw)
                          + ") : présentation client, conseil et "
                            "diffusion BLOQUÉS.")
            _banner_en = ("⛔ Temporal authority conflict — two "
                          "distinct analysis dates requested ("
                          + str(_scenario_raw)
                          + "): client presentation, advice and "
                            "distribution BLOCKED.")
        else:
            _banner_fr = ("⛔ Autorité temporelle invalide — date "
                          "d'analyse demandée illisible ("
                          + str(_scenario_raw)
                          + ") : présentation client, conseil et "
                            "diffusion BLOQUÉS.")
            _banner_en = ("⛔ Temporal authority invalid — requested "
                          "analysis date unreadable ("
                          + str(_scenario_raw)
                          + "): client presentation, advice and "
                            "distribution BLOCKED.")
        _banner_vis = (_banner_en if str(lang or "fr").lower()
                       .startswith("en") else _banner_fr)
        _ta_er = {
            "run_date": _rd_er,
            "analysis_date": None,
            "scenario_requested": _scenario_status != "NOT_REQUESTED",
            "scenario_raw_value": _scenario_raw,
            "scenario_status": _scenario_status,
            "status": _scenario_status,
            "policy": _pol_ser,
            "conflict": bool(_probe_er.get("conflict")),
            "candidates": _probe_er.get("candidates") or [],
            "error_code": _code_er,
            "intent_source": _probe_er.get("intent_source") or "NONE",
            "candidate_value": _probe_er.get("candidate_value"),
            "candidate_raw": _probe_er.get("candidate_raw") or "",
            # TCR-v16 (verdict v15, P0-5) — l'empreinte de l'entrée doit
            # atteindre l'interface AUSSI sur le chemin bloqué : c'est
            # précisément là que le bouton « ce n'est pas la date
            # d'analyse » doit pouvoir s'appuyer dessus.
            "input_fingerprint": (
                getattr(locals().get("_tctx19"), "input_fingerprint", "")
                or str(temporal_input_fingerprint or "") or None),
            "source": ("brief" if _scenario_status != "NOT_REQUESTED"
                       else "default_run"),
        }
        try:
            _scp19(None)  # le state frontière meurt avec le run
        except Exception:
            pass
        return {
            # Gate 15 (i18n) — le bandeau EST l'output visible : une
            # seule langue (celle du run), zéro contenu métier. Les
            # surfaces DOCX/deck générées depuis outputs le portent.
            "outputs": {"synthese": _banner_vis},
            "run_date": _rd_er,
            "analysis_date": None,
            "temporal_authority_date": None,
            "temporal_authority": _ta_er,
            "temporal_authority_error": _code_er,
            "completion_gate": [],
            "run_block_reasons": [{
                "code": _code_er,
                "raw_value": str(_scenario_raw),
                "message_fr": _banner_fr,
                "message_en": _banner_en}],
            "run_validatable": False,
            "lang": lang,
            "language_conflict": None,
            "inputs": {"brief": brief,
                       "dossier_label": getattr(settings, "dossier_label",
                                                ""),
                       # v62.9 — même en arrêt précoce, le CR doit refléter
                       # les pièces réellement chargées. Le run v62.8 disait
                       # à tort « Sans pièce jointe » alors que 20 fichiers
                       # avaient été fournis.
                       "attachments_meta": attachments_meta or {},
                       "attachments_count": _user_files_count(attachments_meta)},
            "meta": {"temporal_early_return": True},
            "diagnostics_summary": {},
            "diagnostics_attempts": [
                {"role": "temporal_authority", "provider": "internal",
                 "model": "temporal_core_refactor", "status": _code_er,
                 "raw_value": str(_scenario_raw),
                 "exception_type": _temporal_exception_type,
                 "exception_message": _temporal_exception_message,
                 "pipeline_stage": _temporal_exception_stage},
                # Gate 14 — la lecture d'historique et le bloc registre
                # SONT sautés sous autorité bloquée : le diag le dit.
                {"role": "codir_feed_forward", "provider": "internal",
                 "model": "temporal_core_refactor",
                 "status": "SKIPPED_TEMPORAL_AUTHORITY"},
                {"role": "codir_register", "provider": "internal",
                 "model": "temporal_core_refactor",
                 "status": "SKIPPED_TEMPORAL_AUTHORITY"}],
            "entity_scope": None,
            "temporal_frame": None,
            "financial_facts": [],
            "financial_facts_coverage": {},
            "company_profile": None,
            "pappers_resolution_log": None,
            "run_fingerprint": None,
            "b1_proof_layer": None,
            "briefcheck": None,
            "delivery_confidence_score": None,
            "financial_facts_table": None,
            "b23_guards": {"flags": [_banner_vis],
                           "run_not_validatable": True},
            "decision_reconciled": None,
            "accounting_narrative_guard": None,
            "agenda_register": [],
            "agenda_register_markdown": "",
            "codir_history": None,
            "extraction_fidelity": None,
            "valuation": None,
            "web_facts_ledger": None,
            "sc_decision": None,
            "financial_documents_status_message": "",
            "financial_facts_table_status": "",
            "financial_facts_table_error": "",
            "financial_facts_table_n_facts": 0,
            "financial_facts_table_duration_ms": 0,
            "financial_facts_table_degraded": False,
            "financial_facts_table_fait_metrics": 0,
            "financial_facts_table_estim_filings": 0,
            "source_mode": locals().get("_source_mode", "OPEN"),
            "perf_timings_ms": {},
            "parse_cache_stats": {},
            "id_routing_decision": None,
            "id_routing_summary": "",
            "mission_gates": None,
            "raw": {},
        }
    # ── B.1.3.5 (audit dossier industriel (composants) P1) — HARD-GUARD noms de PROGRAMME : « HEVO
    # est un PROGRAMME … PAS une entité juridique » (brief) ⇒ HEVO ne peut
    # JAMAIS devenir analysis_entity_candidate ni brief_company_name. Le
    # filtre lexical B.1.3 (_plan_re) ne pouvait pas l'attraper : le mot
    # « programme » est dans la PHRASE, pas dans le NOM. Neutralisé à la
    # source, AVANT la sonde a1 et les registres.
    try:
        from patches.program_names import extract_banned_program_names as _ebpn
        _banned_progs_b135 = _ebpn(brief or "")
        if (pappers_confirmed_entity or "").strip().upper() in _banned_progs_b135:
            if diag_list is not None:
                diag_list.append({
                    "role": "program_name_guard", "provider": "internal",
                    "model": "program_names_b135", "status": "REJECTED",
                    "summary": (f"candidat « {pappers_confirmed_entity} » = nom de "
                                f"PROGRAMME déclaré au brief (pas une entité "
                                f"juridique) — neutralisé avant sonde/registres"),
                })
            pappers_confirmed_entity = ""
    except Exception:
        pass
    try:
        from patches import a1_probe as _a1p
        _a1p.put(analysis_as_of_date=_analysis_as_of or "",
                 analysis_entity_candidate=(pappers_confirmed_entity or "") or None,
                 brief_company_name=(pappers_confirmed_entity or "") or None)
    except Exception:
        pass
    # F.6.7.1 — expose le mode pièces jointes au contexte agents (placeholder honnête).
    _set_source_attach_only(_attachments_only)
    # ── B.1.3.20 (P1-G) — exploitabilité des pièces au diagnostic CSV ───────
    try:
        _n_unex20 = int((attachments_meta or {}).get("n_unextractable", 0) or 0)
        if _n_unex20 > 0 and diag_list is not None:
            diag_list.append({
                "role": "attachments_extractability", "provider": "internal",
                "model": "attachments_b1320", "status": "PARTIAL",
                "summary": (f"{_n_unex20}/{(attachments_meta or {}).get('files', '?')} "
                            "pièce(s) fournie(s) non exploitables par extraction "
                            "texte (scan sans OCR probable) : "
                            + ", ".join(((attachments_meta or {})
                                         .get("unextractable_names") or [])[:4])),
            })
    except Exception:
        pass
    try:
        diag_list.append({
            "role": "mission_governance", "provider": "internal",
            "model": "mission_governance_v1", "status": "OK",
            "source_mode": _source_mode,
            "analysis_as_of_date": _analysis_as_of or "",
            "decision_mode": _genre.decision_mode,
            "summary": (f"source_mode={_source_mode}"
                        + (f" · as_of={_analysis_as_of}" if _analysis_as_of else "")
                        + (" · sources externes désactivées" if _attachments_only else "")),
        })
        if logger:
            log_event(logger, "info", "mission_governance",
                      f"source_mode={_source_mode} as_of={_analysis_as_of} "
                      f"decision_mode={_genre.decision_mode}")
    except Exception:
        pass

    # ─── F.5.2 (Cycle C) — FEED-FORWARD agents ────────────────────────────────
    # Si un LIBELLÉ DE DOSSIER explicite est fourni, le dossier est connu dès le
    # départ (sans résolution d'entité) → on charge le contexte du CoDIR précédent
    # (actions ouvertes / en retard / reportées / réapparues, décision N-1, écarts)
    # et on le PRÉPEND au brief, pour que les agents TRAITENT réellement l'héritage
    # au lieu de produire une analyse « nouvelle séance ». Activé uniquement avec
    # libellé explicite (zéro impact sur le chemin de résolution d'entité, qui ne
    # tourne pas ici). Fail-open : aucun échec ne bloque le run.
    try:
        _ff_label = ""
        if isinstance(settings, dict):
            _ff_label = settings.get("dossier_label", "") or ""
        else:
            _ff_label = getattr(settings, "dossier_label", "") or ""
        # Gate 14 — ISOLATION : une autorité INVALID/CONFLICT/ERROR ne
        # LIT pas l'historique (zéro feed-forward, zéro contexte injecté
        # aux agents). Diagnostic SKIPPED_TEMPORAL_AUTHORITY.
        _ta_blocked14 = locals().get("_scenario_status") in ("INVALID",
                                                             "ERROR")
        if _ff_label and _ta_blocked14:
            try:
                diag_list.append({
                    "role": "codir_feed_forward", "provider": "internal",
                    "model": "gate14",
                    "status": "SKIPPED_TEMPORAL_AUTHORITY"})
            except Exception:
                pass
        if _ff_label and not _ta_blocked14:
            from patches import codir_register_history as _crh_ff
            _ff_did = _crh_ff.compute_dossier_id(dossier_label=_ff_label)
            _ff_block = _crh_ff.format_prior_context_block(
                _ff_did, lang=lang,
                analysis_authority=(_analysis_as_of or ""),
                brief_text=str(brief or ""))      # 9.4.52 — statuts du brief courant donnés AVANT les agents
            if _ff_block:
                # F.6.8 (audit) — le feed-forward réinjecte d'anciennes actions
                # « GO sur… » ; en séance ALERTS_ONLY on les neutralise à la source.
                try:
                    from patches.alerts_only_scrubber import scrub_if_alerts_only as _scrub_ff
                    _ff_block = _scrub_ff(_ff_block, getattr(_genre, "decision_mode", ""))
                except Exception:
                    pass
                # F.6.10 (audit dossier réseau de soins F.6.9) — quarantaine temporelle du feed-forward :
                # en analyse historique (as_of passé), on NE réinjecte PAS dans le
                # contexte des agents des actions citant une année postérieure à
                # l'as_of (« dès 2026-06-15 » dans une séance 2023). Elles polluaient
                # le registre courant et les recommandations.
                # Gate 12 — plus AUCUN scan regex des années dans le
                # Markdown : le filtrage par provenance se fait en amont,
                # sur les événements structurés (format_prior_context_block
                # reçoit l'autorité et exclut les états de provenance
                # postérieure — jamais une action pour sa due date).
                brief = _ff_block + "\n\n---\n\n" + brief
                diag_list.append({
                    "role": "codir_feed_forward", "provider": "internal",
                    "model": "codir_register_history_C", "status": "OK",
                    "dossier_id": _ff_did, "injected_chars": len(_ff_block),
                })
    except Exception:
        pass

    # ─── v16.5.73 — Seed temporel dans diagnostics_ia.csv ─────────────────────
    # Trace la date/heure exactes du run dans le diagnostic, pour analyse
    # des drifts temporels (corrélation entre date de run et qualité des
    # sorties LLM, ex. "T1 2025" proposé en T2 2026).
    # Seed posé en tête : toutes les lignes du diag_list héritent de ce
    # contexte temporel pour les analyses post-mortem (groupby run_date).
    try:
        if "_run_now" not in locals():
            from utils.metadata_clock import run_now as _mc_run_now13
            _run_now = _mc_run_now13()
        _run_date_iso = _run_now.date().isoformat()
        _run_quarter = f"T{((_run_now.month - 1) // 3) + 1} {_run_now.year}"
        diag_list.append({
            "role":     "run_context",
            "provider": "internal",
            "model":    "temporal_seed_v1",
            "status":   "OK",
            "run_date":     _run_date_iso,
            "run_quarter":  _run_quarter,
            "run_version":  APP_VERSION,
            "build_version": BUILD_VERSION,
        })
    except Exception:
        # Si la capture date échoue, on continue silencieusement —
        # le pipeline métier prime sur le diagnostic.
        pass

    # v62.11.2 — journal de la plomberie PDF → deep scan, produit dans app.py.
    try:
        _fds_row = _financial_deep_scan_diag_row(attachments_meta)
        if _fds_row is not None:
            diag_list.append(_fds_row)
    except Exception:
        pass

    # Since v16.5.69 — Résolution rétro-compatible des nouveaux flags
    if external_sources_skip is None:
        external_sources_skip = pappers_skip  # héritage v16.5.68 par défaut

    # Since v16.5.69 — Reset compteur session Companies House Documents.
    # Garantit que chaque run dispose de sa pleine quote (ex. 10 docs),
    # indépendant de runs précédents. Cache disque permanent, lui, est conservé.
    try:
        from utils.companies_house_tool import reset_session_doc_counter
        reset_session_doc_counter()
    except Exception:
        pass

    # Since v16.5.70 — Diagnostic dédié Financial Statements
    # Si app.py a fait l'extraction en amont et passé les bundles, on les
    # log dans diag_list pour traçabilité (visible dans diagnostics_ia.csv).
    # Permet de savoir précisément quels PDFs ont eu des FS détectés.
    if financial_statements_bundles:
        for _bundle in financial_statements_bundles:
            try:
                _diag_fs_dict = _bundle.to_diag_dict() if hasattr(_bundle, "to_diag_dict") else {}
            except Exception:
                _diag_fs_dict = {}
            diag_list.append({
                "role":     "financial_statements_extraction",
                "provider": "internal",
                "model":    "financial_statement_extractor_v1",
                "status":   "OK" if _diag_fs_dict.get("financial_statements_detected") else "EMPTY",
                "fs_log":   _diag_fs_dict,
            })
            if logger:
                detected_str = "OK" if _diag_fs_dict.get("financial_statements_detected") else "EMPTY"
                log_event(logger, "info", "financial_statements",
                          f"{detected_str} | file={_diag_fs_dict.get('filename', '?')} | "
                          f"pages={_diag_fs_dict.get('total_pages', 0)} | "
                          f"sections={_diag_fs_dict.get('sections_detected', [])} | "
                          f"tokens_est={_diag_fs_dict.get('tokens_estimate', 0)}")

    # ── v16.5.63 — Briefcheck (pré-orchestration) ────────────────────────────
    # Détecte 3 situations à risque :
    #   1. Brief mentionne des documents mais aucune pièce financière attachée
    #      → banner_markdown de garde à injecter en tête du livrable
    #   2. Horizon implicite ≥ 1 an → suggère un plan pluriannuel (non bloquant)
    #   3. Société mère en APE holding → suggère l'expansion aux filiales
    # Tout est non bloquant : en cas d'erreur ou de flag off, le pipeline
    # continue à l'identique de v16.5.62.
    _briefcheck_result = None
    if _USE_BRIEFCHECK and _run_briefcheck is not None:
        try:
            # v16.5.67.10 P0 — fix bug dossier réseau de soins 19/04 :
            # attachments_meta["files"] est un ENTIER (nombre de fichiers),
            # pas une liste de chemins. Itérer sur un int levait TypeError
            # silencieusement avalé → briefcheck absent du CSV en FRAMED.
            # La vraie liste de noms est dans attachments_meta["filenames"]
            # si disponible, sinon on reste sur une liste vide (briefcheck
            # fonctionne sans attachments, il utilise juste le brief_text).
            _brief_attachments: List[Path] = []
            if attachments_meta and isinstance(attachments_meta, dict):
                _raw_files = attachments_meta.get("filenames") or attachments_meta.get("file_list") or []
                if isinstance(_raw_files, (list, tuple)):
                    for fname in _raw_files:
                        if not fname:
                            continue
                        try:
                            _brief_attachments.append(Path(str(fname)))
                        except Exception:
                            continue
            # F.6.7.1 (P2, audit ChatGPT) — « pièces financières DÉTECTÉES » ≠ « des
            # fichiers existent ». On n'utilise plus attachments_meta["files"]>0 (trop
            # large) : on s'appuie sur des blocs financiers réellement parsés OU un
            # signal financier de CONTENU solide dans les pièces.
            _fin_signal_solid = False
            try:
                from utils.financial_signal_detector import detect_financial_signal as _dfs_bc
                if attachments_block:
                    _fin_signal_solid = bool(_dfs_bc(attachments_block).financial_signal_solid)
            except Exception:
                _fin_signal_solid = False
            _fin_block_present = (
                bool(financial_statements_block)
                or bool(financial_statements_bundles)
                or _fin_signal_solid
            )
            _briefcheck_result = _run_briefcheck(
                brief_text=brief,
                attachments=_brief_attachments,
                lang=lang,
                company_profile=None,  # alimenté plus tard si besoin via _company_profile
                source_mode=_source_mode,
                financial_block_present=_fin_block_present,
            )
            if logger and _briefcheck_result.get("warnings"):
                log_event(logger, "info", "briefcheck",
                          f"warnings={_briefcheck_result['warnings']} horizon={_briefcheck_result['horizon']}")
            # v16.5.65 — Log explicite du mode détecté (audit)
            _bm_diag = _briefcheck_result.get("brief_mode") or {}
            if logger and _bm_diag:
                log_event(logger, "info", "briefcheck",
                          f"brief_mode={_bm_diag.get('mode')} "
                          f"present={_bm_diag.get('present_count')}/4 "
                          f"cap={_bm_diag.get('score_cap')} "
                          f"leviers={_bm_diag.get('leviers')}")
            if diag_list is not None:
                diag_list.append({
                    "role":     "briefcheck",
                    "provider": "internal",
                    "model":    "briefcheck_v1_1",
                    "status":   _briefcheck_result["doc_check"]["severity"],
                    "warnings": _briefcheck_result.get("warnings", []),
                    "horizon":  _briefcheck_result.get("horizon"),
                    "scope_expansion": _briefcheck_result.get("scope_expansion"),
                    # v16.5.65 — exposition brief_mode pour CSV diagnostics
                    "brief_mode":         _bm_diag.get("mode"),
                    "brief_mode_present": _bm_diag.get("present_count"),
                    "brief_mode_cap":     _bm_diag.get("score_cap"),
                })
        except Exception as _bc_err:
            if logger:
                log_event(logger, "warning", "briefcheck", f"error | {str(_bc_err)[:120]}")
            _briefcheck_result = None
            # Since v16.5.67.10 — P0 observabilité permanente : même en cas d'exception,
            # on trace l'incident dans diag_list pour qu'il apparaisse dans le CSV.
            # Sans ça, l'absence de la ligne briefcheck masquait le vrai problème
            # (format de brief Équipe non géré, etc.). Cf. run dossier réseau de soins du 19/04.
            if diag_list is not None:
                diag_list.append({
                    "role":     "briefcheck",
                    "provider": "internal",
                    "model":    "briefcheck_v1_1",
                    "status":   "ERROR",
                    "error":    f"{type(_bc_err).__name__}: {str(_bc_err)[:200]}",
                    "brief_mode":         None,
                    "brief_mode_present": None,
                    "brief_mode_cap":     None,
                })
    # ─────────────────────────────────────────────────────────────────────────

    # Patch v16.5.72.10 (retex Robin) — Routage intelligent sources externes.
    # Détermine en amont si on appelle Pappers, CH, GLEIF selon l'identifiant
    # détecté dans le brief ou confirmed_entity.
    # - SIREN détecté (9 chiffres) → Pappers seul (CH skipped)
    # - Company Number UK (8 chars) → CH seul (Pappers skipped)
    # - LEI seul → GLEIF seul (Pappers + CH skipped)
    # - Pas d'ID → fallback all sources (comportement v16.5.72.9 préservé)
    # Effet attendu : 3-5s économisées sur sociétés non-FR (skip Pappers inutile)
    _routing_decision = None
    if detect_primary_id is not None:
        try:
            _routing_decision = detect_primary_id(
                brief_text=brief or "",
                confirmed_entity=pappers_confirmed_entity or "",
            )
            if logger:
                try:
                    log_event(
                        logger, "info", "id_router",
                        "routing_decision_computed",
                        rationale=_routing_decision.rationale,
                        id_type=_routing_decision.id_type,
                        primary_id=_routing_decision.primary_id,
                        use_pappers=_routing_decision.use_pappers,
                        use_ch=_routing_decision.use_ch,
                        use_gleif=_routing_decision.use_gleif,
                    )
                except Exception:
                    pass
        except Exception:
            _routing_decision = None  # fallback safe

    try:
        from patches import a1_probe as _a1p
        _rd = _routing_decision
        if _rd is not None:
            _a1p.put(
                provided_identifier=getattr(_rd, "primary_id", None),
                provided_identifier_type=getattr(_rd, "id_type", None),
                routing_rationale=getattr(_rd, "rationale", None),
                use_ch=getattr(_rd, "use_ch", None),
                use_pappers=getattr(_rd, "use_pappers", None),
                use_gleif=getattr(_rd, "use_gleif", None),
                resolved_registry=("companies_house" if getattr(_rd, "use_ch", False)
                                   else "pappers" if getattr(_rd, "use_pappers", False)
                                   else "gleif" if getattr(_rd, "use_gleif", False)
                                   else "fallback_all"),
            )
    except Exception:
        pass

    # ── Enrichissement Pappers — v16.5.53 ────────────────────────────────────
    # full    → Stratégie, Finance, DG, Synthèse
    # summary → Marketing, Commercial, Supply Chain
    # resolution_log → objet audit-ready tracé dans diag_list
    _pap_full    = ""
    _pap_summary = ""
    _pap_primary = ""
    _pap_resolved_sirens = []   # v17.1-A4 — SIREN réellement résolus par Pappers
    _pap_resolved_entities = []  # v17.1-A4.2 — entités structurées résolues
    _comparison_block_md = ""    # v17.1-A4.2 — bloc comparatif déterministe
    _pap_rlog    = None   # PappersResolutionLog ou None
    # Patch v16.5.72.9 (retex Robin) — timing observable
    _pappers_t0 = time.time()
    _pappers_duration_ms = 0
    # Patch v16.5.72.10 — Skip Pappers si routage l'a explicitement écarté
    _pappers_use = (
        _routing_decision.use_pappers
        if _routing_decision is not None
        else True  # fallback : comportement v16.5.72.9
    )
    # ── M6-A2.1.2 — nom d'analyse FIABLE + init quarantine (hors bloc Pappers) ──
    # Calculé AVANT toute résolution registre, depuis une source indépendante
    # (cible confirmée → section IDENTITÉ du brief → entité UI non-numérique).
    # Jamais _pap_primary. Initialise aussi les flags pour éviter UnboundLocalError
    # sur le chemin pappers_skip (audit ChatGPT, faille n°3).
    _registry_quarantined = False
    _registry_rejected_name = ""
    _analysis_name_q = ""
    try:
        from patches.entity_scope import resolve_analysis_name_for_quarantine as _ranq
        _ctn = ""
        try:
            if confirmed_target_entity is not None:
                _ctn = getattr(confirmed_target_entity, "name", "") or ""
        except NameError:
            _ctn = ""
        _analysis_name_q = _ranq(_ctn, brief, pappers_confirmed_entity or "")
    except Exception:
        _analysis_name_q = ""
    if build_pappers_blocks is not None and not pappers_skip and _pappers_use:
        try:
            _pap_blocks  = build_pappers_blocks(
                brief, lang=lang,
                confirmed_entity=pappers_confirmed_entity or ""
            )
            _pap_full    = _pap_blocks.get("full", "")
            _pap_summary = _pap_blocks.get("summary", "")
            _pap_primary = _pap_blocks.get("primary", "")
            _pap_resolved_sirens = list(_pap_blocks.get("resolved_sirens", []) or [])
            _pap_resolved_entities = list(_pap_blocks.get("resolved_entities", []) or [])
            # ── M6-A2.1.1 — QUARANTINE REGISTRE EN AMONT ─────────────────────
            # AVANT toute injection Pappers (attachments_block, table de faits,
            # _pap_ctx, comparatif). Si le candidat registre (Pappers) ne partage
            # aucun token significatif avec l'entité d'ANALYSE (UI/brief, jamais le
            # nom Pappers lui-même), on purge les blocs BRUTS : ils ne contaminent
            # alors plus rien en aval. dossier anglophone coté (token « <marque> » partagé) intact.
            _registry_quarantined = False
            _registry_rejected_name = ""
            try:
                from patches.entity_scope import apply_registry_quarantine as _arq
                _q = _arq(_analysis_name_q, _pap_primary, _pap_full, _pap_summary, _pap_blocks)
                _registry_quarantined = _q["quarantined"]
                _registry_rejected_name = _q["rejected_name"]
                _pap_full = _q["pap_full"]; _pap_summary = _q["pap_summary"]
                _pap_primary = _q["pap_primary"]; _pap_blocks = _q["pap_blocks"]
                if _registry_quarantined:
                    _pap_resolved_sirens = []; _pap_resolved_entities = []
                    _record_diag(
                        diag_list, role="registry_quarantine", provider="pappers",
                        model="name_similarity", status="REJECTED",
                        error=(f"candidate='{_registry_rejected_name}' vs "
                               f"analysis='{_analysis_name_q}' — no shared significant token"))
                    if logger:
                        try:
                            logger.info(f"[M6-A2.1.2] registry candidate REJECTED — "
                                        f"'{_registry_rejected_name}' vs analysis '{_analysis_name_q}' "
                                        "-> Pappers blocks purged (agents/facts/attachments).")
                        except Exception:
                            pass
            except Exception:
                pass
            # ── B.1.3.20 (P1-D, run dossier industriel) — RETRY UNIQUE post-quarantaine ──
            # Racine reproduite : après purge du candidat rejeté (« CHARLET
            # ACTIONNARIAT »), AUCUN second appel n'existait (un seul call-site)
            # → sources_called=gleif seul, zéro enrichissement FR (profil vide,
            # SIREN/APE absents, cascade secteur/supply). Désormais : un retry
            # avec l'entité d'ANALYSE fiable (_analysis_name_q), re-quarantiné
            # à l'identique — si le retry mismatch encore, on reste purgé.
            if _registry_quarantined and (_analysis_name_q or "").strip():
                try:
                    _pap_blocks_r = build_pappers_blocks(
                        brief, lang=lang, confirmed_entity=_analysis_name_q)
                    _q_r = _arq(_analysis_name_q,
                                _pap_blocks_r.get("primary", ""),
                                _pap_blocks_r.get("full", ""),
                                _pap_blocks_r.get("summary", ""),
                                _pap_blocks_r)
                    if not _q_r["quarantined"] and (_q_r["pap_primary"] or "").strip():
                        _pap_blocks  = _q_r["pap_blocks"]
                        _pap_full    = _q_r["pap_full"]
                        _pap_summary = _q_r["pap_summary"]
                        _pap_primary = _q_r["pap_primary"]
                        _pap_resolved_sirens = list(
                            _pap_blocks.get("resolved_sirens", []) or [])
                        _pap_resolved_entities = list(
                            _pap_blocks.get("resolved_entities", []) or [])
                        _registry_quarantined = False
                        _record_diag(
                            diag_list, role="registry_retry", provider="pappers",
                            model="name_similarity", status="OK",
                            summary=(f"retry avec entité d'analyse "
                                     f"'{_analysis_name_q}' → primaire "
                                     f"'{_pap_primary}' retenu (candidat initial "
                                     f"'{_registry_rejected_name}' écarté)"))
                    else:
                        _record_diag(
                            diag_list, role="registry_retry", provider="pappers",
                            model="name_similarity", status="REJECTED",
                            summary=(f"retry '{_analysis_name_q}' → "
                                     f"'{(_q_r.get('rejected_name') or _pap_blocks_r.get('primary') or '—')}' "
                                     "toujours sans token partagé — blocs purgés maintenus"))
                except Exception:
                    pass
            # v17.1-A4.2 (A4.2-01/03) — bloc comparatif DÉTERMINISTE produit par le
            # moteur dès que ≥2 entités sont résolues, injecté dans le contexte
            # agents (les agents COMMENTENT un tableau, ils ne l'inventent pas).
            if len(_pap_resolved_entities) >= 2:
                try:
                    from patches.mission_gates import build_comparison_block as _bcb
                    _comparison_block_md = _bcb(_pap_resolved_entities, lang=lang)
                    if _comparison_block_md:
                        _pap_full = _comparison_block_md + "\n\n" + (_pap_full or "")
                except Exception:
                    _comparison_block_md = ""
            _pap_rlog    = _pap_blocks.get("resolution_log")
            _pappers_duration_ms = int((time.time() - _pappers_t0) * 1000)
            # Logger le chemin réel de résolution
            if logger:
                if _pap_rlog:
                    log_event(logger, "info", "pappers",
                              _pap_rlog.summary_line(),
                              duration_ms=_pappers_duration_ms)
                elif not _pap_full:
                    log_event(logger, "info", "pappers",
                              "enrichment_empty | no_entity_detected",
                              duration_ms=_pappers_duration_ms)
            # Injecter dans diag_list pour exposer dans le rapport de session
            if diag_list is not None and _pap_rlog:
                diag_list.append({
                    "role":     "pappers_resolution",
                    "provider": "pappers",
                    "model":    "pappers_api",
                    "status":   "OK" if _pap_full else "EMPTY",
                    "pappers_log": _pap_rlog.to_dict(),
                    "duration_ms": _pappers_duration_ms,  # v16.5.72.9
                })
        except Exception as _pe:
            _pappers_duration_ms = int((time.time() - _pappers_t0) * 1000)
            if logger:
                log_event(logger, "warning", "pappers",
                          f"enrichment_error | {str(_pe)[:120]}",
                          duration_ms=_pappers_duration_ms)
    elif pappers_skip and logger:
        log_event(logger, "info", "pappers", "enrichment_skipped | user_request")
    # Patch v16.5.72.10 — Skip explicite par routage intelligent
    elif (not _pappers_use) and logger:
        try:
            log_event(
                logger, "info", "pappers",
                "enrichment_skipped | routed_to_other_source",
                rationale=(_routing_decision.rationale
                           if _routing_decision else "unknown"),
                id_type=(_routing_decision.id_type
                         if _routing_decision else "unknown"),
            )
        except Exception:
            pass

    # ── Persistance du log de résolution (outputs/pappers_sessions.jsonl) ──────
    if _pap_rlog is not None and _pap_append_log is not None:
        try:
            _pap_append_log(_pap_rlog)
        except Exception:
            pass
    # ─────────────────────────────────────────────────────────────────────────

    def _pap_ctx(role: str) -> str:
        """Bloc Pappers adapté au scope du rôle, prêt à insérer dans son prompt."""
        if pappers_skip:
            return ""
        _fn = get_pappers_scope_for_role if get_pappers_scope_for_role else (lambda r: "full")
        scope = _fn(role)
        blk = _pap_full if scope == "full" else _pap_summary
        if not blk:
            return ""
        lbl = ("Company context (Pappers):" if lang == "en" else "Contexte société (Pappers) :")
        return f"{lbl}\n---\n{blk.strip()}\n---\n"

    # ── Since v16.5.68 — Enrichissement additif via 4 sources externes ─────────
    # Approche additive (pas refactor) : Pappers reste intact. Les 4 nouvelles
    # sources s'ajoutent côte-à-côte. Refacto unifiée prévue v16.5.70+.
    #
    # Stratégie de scope :
    #   - GLEIF, SEC EDGAR, Companies House : full pour Stratégie/Finance/DG/Synthèse,
    #     summary pour Marketing/Commercial/Supply Chain (mêmes rôles que Pappers).
    #   - OpenSanctions : full pour TOUS les rôles (signal critique LBC-FT à ne
    #     jamais omettre — cohérent avec philosophie due diligence).
    #
    # Toutes les sources sont silencieuses si :
    #   - module absent (None)
    #   - clé/UA absent (les modules retournent NOT_CONFIGURED ou NO_USER_AGENT
    #     et un block vide → _*_ctx() retourne "")
    _gleif_blocks: dict = {}
    _sec_blocks: dict = {}
    _os_blocks: dict = {}
    _ch_blocks: dict = {}

    # Since v16.5.69 — Helper unifié pour résoudre le nom à propager aux 4 sources externes.
    # Priorité :
    #   1. confirmed_target_entity.name — l'utilisateur a confirmé une cible cross-juridiction
    #   2. pappers_confirmed_entity — Since v16.5.68 rétro-compat (utilisateur a confirmé via UI Pappers)
    #   3. _pap_primary — résultat Pappers fraîchement remonté
    try:   # v62.13.9.4.32 (A) — un SIREN confirmé comme « nom » n'est jamais propagé comme nom
        from patches.entity_scope import is_bare_identifier as _ibi62432
    except Exception:
        _ibi62432 = lambda _v: False   # noqa: E731
    def _resolve_confirmed_name() -> str:
        if confirmed_target_entity is not None:
            name_attr = getattr(confirmed_target_entity, "name", "") or ""
            if name_attr:   # 9.4.32 (A) — un identifiant n'est pas un nom
                return name_attr if not _ibi62432(name_attr) else (_pap_primary or _analysis_name_q or "")
        # v62.8 — un SIREN explicite du brief prime sur une ancienne confirmation de session.
        try:
            if getattr(_pap_rlog, "source", "") == "BRIEF_SIREN":
                return _pap_primary or _analysis_name_q or ""
        except Exception:
            pass
        return pappers_confirmed_entity or _pap_primary or _analysis_name_q or ""
    _resolved_name = _resolve_confirmed_name()

    # B.1.3 — indice « société cotée » depuis le brief (Actionnariat coté,
    # ticker LSE, « (group) plc ») : calculé UNE fois, consommé par GLEIF
    # puis Companies House (préférence groupe coté sur les homonymes Ltd).
    _uk_listed_hint = bool(re.search(
        r"actionnariat\s*:\s*cot[ée]|LSE\s*:|\b(?:group\s+)?plc\b",
        brief, re.IGNORECASE))
    # B.1.3.6 — TRACE du hint : deux runs dossier anglophone coté où « Actionnariat : Coté »
    # figurait au brief SANS que la préférence plc ne tire (path NAME_EXACT).
    # Le CSV dira désormais la valeur calculée et l'extrait qui l'a (ou pas)
    # allumée — fini les hypothèses.
    if diag_list is not None:
        try:
            _m_hint = re.search(
                r"actionnariat\s*:\s*cot[ée]|LSE\s*:|\b(?:group\s+)?plc\b",
                brief, re.IGNORECASE)
            try:  # B.1.3.13 — places de marché VUES au brief (journal seul,
                # le hint ne bascule pas) : tripwire d'extension Annexe B.
                from patches.listed_forms import detect_market_tokens as _dmt13
                _mk13 = _dmt13(brief or "")
            except Exception:
                _mk13 = []
            diag_list.append({
                "role": "listed_hint_state", "provider": "internal",
                "model": "hint_b136", "status": "OK",
                "summary": (f"listed_hint={_uk_listed_hint} · "
                            f"match={_m_hint.group(0)[:40] if _m_hint else None} · "
                            f"brief_len={len(brief or '')}"
                            + (f" · markets={_mk13}" if _mk13 else "")),
            })
        except Exception:
            pass

    # GLEIF — pas de clé requise, toujours tenter
    if build_gleif_blocks is not None and not external_sources_skip:
        try:
            _gleif_blocks = build_gleif_blocks(
                brief, lang=lang,
                confirmed_name=(_analysis_name_q or _resolved_name),
                listed_hint=_uk_listed_hint,
            )
            # B.1.3.6 (run dossier anglophone coté) — le brief disait « Société : dossier anglophone coté »
            # sans « plc » : le hint coté était légitimement ÉTEINT, et la
            # re-recherche CH « <société> plc » ne pouvait pas tirer. Mais
            # GLEIF (appelé AVANT CH) a résolu le bon groupe coté : si le nom
            # légal GLEIF se termine par « PLC », le hint s'allume pour CH.
            try:
                if str((_gleif_blocks or {}).get("primary", "")).strip().lower().endswith(" plc"):
                    if not _uk_listed_hint and diag_list is not None:
                        diag_list.append({
                            "role": "listed_hint_gleif", "provider": "internal",
                            "model": "hint_b136", "status": "OK",
                            "summary": ("hint coté allumé par GLEIF (nom légal "
                                        "en PLC) — transmis à Companies House"),
                        })
                    _uk_listed_hint = True
            except Exception:
                pass
            if logger and _gleif_blocks.get("resolution_log"):
                log_event(logger, "info", "gleif", _gleif_blocks["resolution_log"].summary_line())
            if diag_list is not None and _gleif_blocks.get("resolution_log"):
                diag_list.append({
                    "role":     "gleif_resolution",
                    "provider": "gleif",
                    "model":    "gleif_api",
                    "status":   "OK" if _gleif_blocks.get("full") else "EMPTY",
                    "gleif_log": _gleif_blocks["resolution_log"].to_dict(),
                })
            # M6-A2.1.3 — quarantine GLEIF EN AMONT (symétrie Pappers). Purge le
            # bloc brut AVANT _gleif_ctx / _external_ctx / attachments_block / facts.
            try:
                from patches.entity_scope import apply_gleif_quarantine as _agq
                _gq = _agq(_analysis_name_q, _gleif_blocks)
                if _gq["quarantined"]:
                    _gleif_blocks = _gq["gleif_blocks"]
                    _record_diag(
                        diag_list, role="registry_quarantine", provider="gleif",
                        model="name_similarity", status="REJECTED",
                        error=(f"candidate='{_gq['rejected_name']}' vs "
                               f"analysis='{_analysis_name_q}' — no shared significant token"))
                    if logger:
                        try:
                            logger.info("[M6-A2.1.3] GLEIF candidate REJECTED — "
                                        f"'{_gq['rejected_name']}' vs analysis "
                                        f"'{_analysis_name_q}'.")
                        except Exception:
                            pass
            except Exception:
                pass
        except Exception as _ge:
            if logger:
                log_event(logger, "warning", "gleif", f"enrichment_error | {str(_ge)[:120]}")

    # SEC EDGAR — User-Agent requis ; si absent, le module retourne NO_USER_AGENT silencieusement
    if build_sec_edgar_blocks is not None and not external_sources_skip:
        try:
            _sec_blocks = build_sec_edgar_blocks(
                brief, lang=lang,
                confirmed_name=(_analysis_name_q or _resolved_name),
            )
            if logger and _sec_blocks.get("resolution_log"):
                _conf = _sec_blocks.get("confidence", "")
                # Ne logger que si pas NO_USER_AGENT (sinon bruit inutile pour utilisateurs FR-only)
                if _conf != "NO_USER_AGENT":
                    log_event(logger, "info", "sec_edgar", _sec_blocks["resolution_log"].summary_line())
            if diag_list is not None and _sec_blocks.get("resolution_log") and _sec_blocks.get("full"):
                diag_list.append({
                    "role":     "sec_edgar_resolution",
                    "provider": "sec_edgar",
                    "model":    "sec_edgar_api",
                    "status":   "OK",
                    "sec_edgar_log": _sec_blocks["resolution_log"].to_dict(),
                })
        except Exception as _se:
            if logger:
                log_event(logger, "warning", "sec_edgar", f"enrichment_error | {str(_se)[:120]}")

    # OpenSanctions — clé requise ; if absent, retourne NOT_CONFIGURED silencieusement
    if build_opensanctions_blocks is not None and not external_sources_skip:
        try:
            _os_query = _analysis_name_q or _resolved_name  # M6-A2.2 — seed gouverné (dette A2.1.3)
            if _os_query:
                _os_blocks = build_opensanctions_blocks(_os_query, lang=lang)
                if logger and _os_blocks.get("resolution_log"):
                    _conf = _os_blocks.get("confidence", "")
                    if _conf != "NOT_CONFIGURED":
                        log_event(logger, "info", "opensanctions", _os_blocks["resolution_log"].summary_line())
                if diag_list is not None and _os_blocks.get("resolution_log") and _os_blocks.get("full"):
                    diag_list.append({
                        "role":     "opensanctions_resolution",
                        "provider": "opensanctions",
                        "model":    "opensanctions_api",
                        "status":   "OK",
                        "opensanctions_log": _os_blocks["resolution_log"].to_dict(),
                    })
        except Exception as _oe:
            if logger:
                log_event(logger, "warning", "opensanctions", f"enrichment_error | {str(_oe)[:120]}")

    # Companies House — clé requise ; UK-spécifique
    # Patch v16.5.69.1 patch session 7 (audit terrain dossier de conseil) :
    # avant ce patch, on lançait toujours la recherche CH avec confirmed_name dès
    # qu'on avait un nom (typiquement venant de Pappers SIREN_DIRECT). Résultat
    # désastreux pour dossier de conseil (FR pure) : "dossier de conseil" → fuzzy match
    # silencieux sur "HI! AMBASSADORS LIMITED" → pollution de tous les agents.
    #
    # Garde-fou : on ne lance la recherche CH par nom QUE si on a un signal UK
    # explicite dans le brief OU si Pappers a confirmé une activité UK / lien
    # UK. Sinon on passe directement le confirmed_name vide à CH, qui retournera
    # NOT_FOUND propre (et le 2e garde-fou côté CH stricte fuzzy match prend
    # le relais en défense en profondeur).
    def _has_uk_signal(brief_str: str, name_str: str) -> bool:
        """
        Détecte si le brief ou le nom confirmé contient un signal UK explicite
        justifiant une recherche Companies House par nom.
        """
        haystack = (brief_str or "") + "\n" + (name_str or "")
        haystack_low = haystack.lower()
        # Mots-clés explicites UK / juridiction britannique
        uk_keywords = [
            "uk ", " uk", "u.k.", "u.k ",
            "royaume-uni", "royaume uni",
            "united kingdom", "great britain",
            "england", "angleterre",
            "scotland", "écosse",
            "wales", "pays de galles",
            "ireland du nord", "northern ireland",
            "london", "londres",
            "lse", "ftse",
            "companies house",
            "plc", "ltd", "limited",  # suffixes corporate UK
        ]
        for kw in uk_keywords:
            if kw in haystack_low:
                return True
        # Signal CN UK déjà extrait par target_entity_resolver
        try:
            from utils.target_entity_resolver import extract_signals_from_brief
            sig = extract_signals_from_brief(brief_str)
            if sig.cn_uk:
                return True
        except Exception:
            pass
        return False

    # Patch v16.5.72.10 — Skip CH si routage l'a écarté (Pappers primary détecté)
    _ch_use = (
        _routing_decision.use_ch
        if _routing_decision is not None
        else True  # fallback : comportement v16.5.72.9
    )
    if build_companies_house_blocks is not None and not external_sources_skip and _ch_use:
        try:
            # Patch v16.5.69.1 patch session 7 — confirmed_name passé à CH
            # SEULEMENT si signal UK détecté. Sinon on passe "" pour forcer
            # NOT_FOUND silencieux (CH a déjà son propre garde-fou strict
            # fuzzy match — défense en profondeur).
            _ch_confirmed_name = _resolved_name if _has_uk_signal(brief, _resolved_name) else ""
            _ch_blocks = build_companies_house_blocks(
                brief, lang=lang,
                confirmed_name=_ch_confirmed_name,
                listed_hint=_uk_listed_hint,
            )
            try:
                from patches import a1_probe as _a1p
                _a1p.put(analysis_entity_candidate=_resolved_name or None)
                if not (_resolved_name or "").strip():
                    pass
                _a1p.put_ch(_ch_blocks)   # vraie entité légale CH (≠ entité d'analyse)
            except Exception:
                pass
            if logger and _ch_blocks.get("resolution_log"):
                _conf = _ch_blocks.get("confidence", "")
                if _conf != "NOT_CONFIGURED":
                    log_event(logger, "info", "companies_house", _ch_blocks["resolution_log"].summary_line())
            if diag_list is not None and _ch_blocks.get("resolution_log") and _ch_blocks.get("full"):
                diag_list.append({
                    "role":     "companies_house_resolution",
                    "provider": "companies_house",
                    "model":    "companies_house_api",
                    "status":   "OK",
                    "companies_house_log": _ch_blocks["resolution_log"].to_dict(),
                })
        except Exception as _che:
            if logger:
                log_event(logger, "warning", "companies_house", f"enrichment_error | {str(_che)[:120]}")

    # Since v16.5.69 — Auto-download des filings UK (Companies House Document API)
    # Conditions cumulatives :
    #   1. settings.enable_uk_filings_download = True (opt-in utilisateur)
    #   2. CH a remonté un company_number valide
    #   3. Document API key configurée
    #   4. external_sources_skip = False
    # Stratégie : top 3 derniers filings de catégorie 'accounts' + 1 'confirmation-statement'
    # Les bytes téléchargés sont ajoutés à attachments_meta sous forme de _ch_filings.
    _ch_filings_downloaded: List[Dict[str, Any]] = []
    # Patch v16.5.69.1 — Bloc filings textuel réutilisable par tous les rôles décisionnels
    # (Stratégie, Finance, Synthèse, DG) via le helper _ch_filings_ctx() défini plus bas.
    # Initialisé à "" par défaut, rempli dans le bloc auto-download si conditions OK.
    _ch_filings_block_text: str = ""
    if (not external_sources_skip
            and getattr(settings, "enable_uk_filings_download", False)
            and _ch_blocks
            and _ch_blocks.get("company_number")):
        try:
            from utils.companies_house_tool import (
                fetch_filing_history, fetch_document_content,
                _document_api_key as _ch_doc_key,
            )
            if _ch_doc_key():
                _cn = _ch_blocks["company_number"]
                _fh = fetch_filing_history(_cn, items_per_page=20)
                _items = _fh.get("items", []) if isinstance(_fh, dict) else []

                # M6-A1-det — sélection DÉTERMINISTE : on trie par (date desc,
                # transaction_id) AVANT le [:N], sinon le set des 3 comptes dépend
                # de l'ordre renvoyé par l'API CH (non garanti) → bloc non reproductible.
                def _ch_filing_key(it):
                    return (str(it.get("date", "")), str(it.get("transaction_id", "")))
                _accounts = sorted(
                    [it for it in _items if it.get("category", "").lower() == "accounts"],
                    key=_ch_filing_key, reverse=True)[:3]
                _conf_stmt = sorted(
                    [it for it in _items if it.get("category", "").lower() == "confirmation-statement"],
                    key=_ch_filing_key, reverse=True)[:1]
                _to_download = _accounts + _conf_stmt

                for _filing in _to_download:
                    _links = _filing.get("links", {}) or {}
                    _doc_meta_url = _links.get("document_metadata", "")
                    if not _doc_meta_url:
                        continue
                    # Extraire le doc_id depuis l'URL
                    _doc_id = _doc_meta_url.rstrip("/").rsplit("/", 1)[-1]
                    if not _doc_id:
                        continue
                    _r = fetch_document_content(_doc_id, format="pdf")
                    if not _r.get("ok"):
                        # M6-A1-det — un retry : réduit la variance run-à-run due aux
                        # échecs réseau/rate-limit transitoires (un dépôt qui échoue un
                        # run et réussit l'autre fait diverger le bloc).
                        _r = fetch_document_content(_doc_id, format="pdf")
                    if _r.get("ok"):
                        _ch_filings_downloaded.append({
                            "doc_id": _doc_id,
                            "type": _filing.get("type", ""),
                            "category": _filing.get("category", ""),
                            "date": _filing.get("date", ""),
                            "description": _filing.get("description", "")[:120],
                            "local_path": _r.get("local_path", ""),
                            "bytes_length": _r.get("bytes_length", 0),
                            "from_cache": _r.get("from_cache", False),
                        })
                        if logger:
                            log_event(logger, "info", "companies_house_doc",
                                      f"downloaded | doc_id={_doc_id[:12]}… | "
                                      f"category={_filing.get('category', '')} | "
                                      f"bytes={_r.get('bytes_length', 0)} | "
                                      f"cache_hit={_r.get('from_cache', False)}")
                    else:
                        if logger:
                            log_event(logger, "warning", "companies_house_doc",
                                      f"download_failed | doc_id={_doc_id[:12]}… | "
                                      f"error={_r.get('error', '')}")

                # M6-A1-det — ordre d'injection DÉTERMINISTE (l'append suivait l'ordre
                # de téléchargement). Tri stable par (date desc, doc_id) → même bloc.
                _ch_filings_downloaded.sort(
                    key=lambda d: (str(d.get("date", "")), str(d.get("doc_id", ""))),
                    reverse=True)

                # Ajouter à attachments_meta pour intégration agents
                if _ch_filings_downloaded and attachments_meta is not None:
                    if "_ch_filings" not in attachments_meta:
                        attachments_meta["_ch_filings"] = []
                    attachments_meta["_ch_filings"].extend(_ch_filings_downloaded)

                # Since v16.5.69.1 — VRAIE INJECTION dans attachments_block
                # Avant : les filings étaient seulement référencés en metadata
                # (chemins de fichiers que les LLM ne peuvent pas lire).
                # Patch v16.5.69.1 (audit ChatGPT) — Bug structurel détecté :
                # avant ce patch, attachments_block n'était injecté QUE dans le
                # prompt Stratégie. Donc Finance / Synthèse / DG ne voyaient PAS
                # les filings UK directement — seulement indirectement via la
                # reformulation Stratégie. Pour dossier anglophone coté / due diligence, c'est
                # insuffisant : Finance doit lire les comptes annuels eux-mêmes.
                #
                # Correction : on stocke le bloc filings dans une variable locale
                # _ch_filings_block_text réutilisable, puis on l'injecte
                # explicitement via le helper _ch_filings_ctx(role) dans les
                # prompts des 4 rôles décisionnels (Stratégie + Finance + DG +
                # Synthèse). On garde la concaténation dans attachments_block
                # pour compatibilité avec Stratégie qui le reçoit déjà.
                _ch_filings_block_text = ""
                if _ch_filings_downloaded:
                    try:
                        from utils.companies_house_tool import build_filings_attachments_from_downloads
                        from utils.attachments import build_attachments_block
                        _ch_attachment_items = build_filings_attachments_from_downloads(
                            _ch_filings_downloaded, lang=lang
                        )
                        if _ch_attachment_items:
                            # Budget tokens dédié aux filings UK : 8 000 tokens
                            # (suffit pour 3 Annual Accounts + 1 Confirmation Statement
                            # avec troncature head+tail si dépassement)
                            _ch_block, _ch_stats = build_attachments_block(
                                _ch_attachment_items, token_budget=8000
                            )
                            if _ch_block.strip():
                                # Préfixe lisible pour que les agents identifient la source
                                _ch_block_prefix = (
                                    "📄 Documents Companies House téléchargés automatiquement (Since v16.5.69.1) :"
                                    if lang == "fr"
                                    else
                                    "📄 Companies House documents auto-downloaded (Since v16.5.69.1):"
                                )
                                _ch_filings_block_text = (
                                    _ch_block_prefix + "\n" + _ch_block
                                )
                                # Pour rétro-compat Stratégie : on continue à
                                # concaténer dans attachments_block
                                attachments_block = (
                                    (attachments_block or "")
                                    + ("\n\n" if attachments_block else "")
                                    + _ch_filings_block_text
                                )
                                if logger:
                                    log_event(logger, "info", "companies_house_doc",
                                              f"injected_into_attachments_block | "
                                              f"items={len(_ch_attachment_items)} | "
                                              f"tokens_est={_ch_stats.get('tokens_est', 0)} | "
                                              f"truncated={_ch_stats.get('truncated', False)}")
                    except Exception as _inj_e:
                        if logger:
                            log_event(logger, "warning", "companies_house_doc",
                                      f"injection_error | {str(_inj_e)[:120]}")

                # Diagnostic
                if diag_list is not None:
                    diag_list.append({
                        "role":     "companies_house_filings_download",
                        "provider": "companies_house_document",
                        "model":    "companies_house_document_api",
                        "status":   "OK" if _ch_filings_downloaded else "EMPTY",
                        "n_downloaded": len(_ch_filings_downloaded),
                        "company_number": _ch_blocks.get("company_number", ""),
                    })
        except Exception as _dl_e:
            if logger:
                log_event(logger, "warning", "companies_house_doc",
                          f"auto_download_error | {str(_dl_e)[:120]}")

    # Helpers d'injection — mêmes règles de scope que _pap_ctx
    _ROLES_FULL = {"strategie", "finance", "direction_generale", "synthese"}

    def _gleif_ctx(role: str) -> str:
        if external_sources_skip or not _gleif_blocks:
            return ""
        scope = "full" if role in _ROLES_FULL else "summary"
        blk = _gleif_blocks.get("full" if scope == "full" else "summary", "")
        if not blk:
            return ""
        lbl = ("Legal entity context (GLEIF):" if lang == "en" else "Contexte entité légale (GLEIF) :")
        return f"{lbl}\n---\n{blk.strip()}\n---\n"

    def _sec_ctx(role: str) -> str:
        if external_sources_skip or not _sec_blocks:
            return ""
        scope = "full" if role in _ROLES_FULL else "summary"
        blk = _sec_blocks.get("full" if scope == "full" else "summary", "")
        if not blk:
            return ""
        lbl = ("US listed-company context (SEC EDGAR):" if lang == "en" else "Contexte société cotée US (SEC EDGAR) :")
        return f"{lbl}\n---\n{blk.strip()}\n---\n"

    def _os_ctx(role: str) -> str:
        # OpenSanctions : full pour TOUS les rôles (signal critique LBC-FT,
        # ne JAMAIS omettre, même pour Marketing/Commercial qui pourraient
        # autrement engager la société sans connaître l'alerte).
        if external_sources_skip or not _os_blocks:
            return ""
        blk = _os_blocks.get("full", "")
        if not blk:
            return ""
        lbl = ("Sanctions/PEP signal (OpenSanctions):" if lang == "en" else "Signal sanctions/PEP (OpenSanctions) :")
        return f"{lbl}\n---\n{blk.strip()}\n---\n"

    def _ch_ctx(role: str) -> str:
        if external_sources_skip or not _ch_blocks:
            return ""
        scope = "full" if role in _ROLES_FULL else "summary"
        blk = _ch_blocks.get("full" if scope == "full" else "summary", "")
        if not blk:
            return ""
        lbl = ("UK company context (Companies House):" if lang == "en" else "Contexte société UK (Companies House) :")
        return f"{lbl}\n---\n{blk.strip()}\n---\n"

    # Patch v16.5.69.1 (audit ChatGPT) — _ch_filings_ctx :
    # Helper séparé qui injecte le bloc des filings UK téléchargés
    # (Annual Accounts + Confirmation Statement) dans les prompts des rôles
    # décisionnels (_ROLES_FULL : Stratégie + Finance + DG + Synthèse).
    # Avant ce patch, attachments_block n'allait qu'à Stratégie ; Finance ne
    # voyait pas le contenu effectif des comptes annuels — bug structurel
    # rendant la promesse "ajoutés aux pièces jointes pour Finance / Stratégie"
    # non tenue.
    # Sémantiquement séparé de _ch_ctx (qui passe le profil société CH) :
    # _ch_filings_ctx passe les *documents* (PDFs comptables effectifs).
    #
    # Convention de nommage : on accepte 'dg' comme alias de 'direction_generale'
    # pour rester cohérent avec _pap_ctx / _external_ctx du même fichier qui
    # utilisent 'dg' dans les appels prompts.
    _ROLES_FULL_ALIASES = {"strategie", "finance", "direction_generale", "synthese", "dg"}

    def _ch_filings_ctx(role: str) -> str:
        if external_sources_skip or not _ch_filings_block_text:
            return ""
        # Filings = documents lourds réservés aux rôles décisionnels.
        # Marketing, Commercial, Supply Chain n'en ont pas l'usage et leur
        # injection consommerait du budget tokens sans gain.
        if role not in _ROLES_FULL_ALIASES:
            return ""
        return f"{_ch_filings_block_text}\n"

    # Since v16.5.70 — _fs_ctx (Financial Statements context)
    # Bug racine corrigé : sur run terrain dossier anglophone coté v16.5.69.1, les Annual Reports
    # de 200 pages étaient tronqués à 50 pages par extract_text_from_upload, donc
    # les Financial Statements en fin de PDF n'étaient jamais lus par les agents.
    # Conséquence : Finance produisait des analyses entièrement [NON SOURCÉ] alors
    # que les chiffres auditées étaient présents dans les PJ uploadées.
    #
    # Correction v16.5.70 : nouveau bloc dédié `financial_statements_block` extrait
    # via utils/financial_statement_extractor.py en amont (app.py), passé en
    # paramètre du run, injecté ICI dans les prompts Finance / DG / Synthèse.
    # Sémantiquement séparé de attachments_block (qui agrège tous les PDFs en
    # tronquant à 50 pages) : ce bloc-ci contient EXCLUSIVEMENT les pages des
    # Financial Statements réellement détectées (Income/Balance/CashFlow/Notes).
    def _fs_ctx(role: str) -> str:
        if not financial_statements_block:
            return ""
        # Réservé aux rôles décisionnels : Finance prioritaire, DG/Synthèse
        # pour validation/synthèse, Stratégie pour cohérence pluriannuelle.
        # Marketing/Commercial/Supply Chain n'en ont pas besoin.
        if role not in _ROLES_FULL_ALIASES:
            return ""
        return f"{financial_statements_block}\n"

    def _external_ctx(role: str) -> str:
        """Concatène toutes les sources externes additionnelles (hors Pappers)
        pour un rôle donné, dans l'ordre déterministe :
        OpenSanctions (alerte critique en premier) → GLEIF → SEC EDGAR → Companies House.
        Pappers reste injecté séparément via _pap_ctx pour rétro-compatibilité.
        """
        parts = [_os_ctx(role), _gleif_ctx(role), _sec_ctx(role), _ch_ctx(role)]
        return "\n".join(p for p in parts if p)
    # ─── Fin Since v16.5.68 — enrichissement additif ────────────────────────────────────

    # attachments_block utilisateur maintenu pour Stratégie (rétrocompat)
    if _pap_full and not pappers_skip:
        attachments_block = _pap_full + "\n\n" + (attachments_block or "")
    # Since v16.5.68 — Sources externes additionnelles dans attachments_block
    # (pour Stratégie qui pilote la cascade et profite de tous les contextes).
    # Ordre : OpenSanctions (signal critique en premier), GLEIF, SEC, Companies House.
    if not external_sources_skip:
        _ext_for_strategy = _external_ctx("strategie")
        if _ext_for_strategy:
            attachments_block = (attachments_block or "") + "\n\n" + _ext_for_strategy
    # ─────────────────────────────────────────────────────────────────────────

    # ─── v16.5.73 — Couche 1 Source Traceability injectée dans les agents ────
    # Construction de la FinancialFactsTable Couche 1 EN AMONT (avant les agents).
    #
    # Avant v16.5.73, la table était construite UNIQUEMENT à la fin du pipeline
    # (~ligne 4486) pour le rendu DOCX/PPTX — aucun agent LLM ne la voyait.
    # Conséquence : incohérence des chiffres entre directions (Stratégie pouvait
    # écrire "Revenue ~2,9 Md£" pendant que Finance disait "Revenue 2,383 M£").
    #
    # Sprint v16.5.73 (cf. CHANGELOG) : la table devient le SOCLE FACTUEL PARTAGÉ
    # injecté dans tous les prompts agents via _facts_ctx(role). Tous les agents
    # — Stratégie, Brief CoDIR, Marketing, Finance, Supply Chain, Commercial,
    # Synthèse, DG — voient désormais EXACTEMENT les mêmes chiffres avec leur
    # traçabilité complète (source + page + statut FAIT/ESTIM_IA/HYPOTHÈSE/À_VÉRIFIER).
    #
    # La construction est faite UNE seule fois ici, le rendu final (~ligne 4486)
    # réutilise _facts_table_built au lieu de le rebuilder. Économie ~1-2s sur
    # dossiers riches et garantie que ce qui est dans le DOCX = ce qu'ont vu
    # les agents.
    #
    # Prérequis : déplacement de la détection _financial_signal_report depuis
    # ~ligne 3372 vers ICI pour disposer du signal au moment du build.

    # Détection signal financier (déplacé depuis l'ancienne ligne 3372).
    # Reste idempotent : si la détection a déjà eu lieu plus haut (refactor
    # futur), on la saute. En version courante (v16.5.73), premier point de calcul.
    _financial_signal_in_attachments_solid = False
    _financial_signal_report = None
    try:
        from utils.financial_signal_detector import detect_financial_signal
        if attachments_block and len(attachments_block) > 200:
            _financial_signal_report = detect_financial_signal(attachments_block)
            _financial_signal_in_attachments_solid = (
                _financial_signal_report.financial_signal_solid
            )
            try:
                from patches import a1_probe as _a1p
                _a1p.put_block("attachments_block", attachments_block)
                _a1p.put_block("financial_statements_block", financial_statements_block)
                _a1p.put_financial_signal(_financial_signal_report)
                _a1p.put(financial_statements_detected=bool(financial_statements_block))
            except Exception:
                pass
            if logger:
                log_event(logger, "info", "financial_signal_detector",
                          f"score={_financial_signal_report.confidence_score} | "
                          f"solid={_financial_signal_in_attachments_solid} | "
                          f"keywords={_financial_signal_report.n_keywords} | "
                          f"amounts={_financial_signal_report.n_amounts} | "
                          f"sigles={_financial_signal_report.n_sigles}")
    except Exception as _fs_e:
        if logger:
            log_event(logger, "warning", "financial_signal_detector",
                      f"detection_error | {str(_fs_e)[:120]}")

    # ── M6-B B.1 (v17.4.0) — Signal EFFECTIF après porte de périmètre ────────
    # Le fix du bug v5 (dossier industriel (composants)) : le signal BRUT du détecteur peut être porté
    # par des comptes SOCIAUX STANDALONE injectés dans attachments_block via
    # Pappers (_pap_full prépendé plus haut). B.1 : un fait MISMATCH ne peut
    # PAS alimenter financial_signal_solid. La valeur EFFECTIVE (posée par la
    # couche de preuve ci-dessous) pilote le scorer ; la valeur BRUTE reste
    # journalisée pour l'audit — jamais de changement de vérité silencieux.
    _fin_signal_solid_effective = _financial_signal_in_attachments_solid
    _b1_ctx = None
    _b1_conflicts = []
    _b1_result = None
    _b1_applied = False  # B.1.1 — vrai UNIQUEMENT si la couche de preuve a tourné

    # Construction Couche 1 — table de faits financiers structurée.
    # Si la construction échoue, les agents tournent comme avant v16.5.73
    # (pas d'injection) et la construction sera retentée à la fin du pipeline
    # pour le rendu final. Robustesse > performance.
    _facts_table_built = None
    _extraction_fidelity = None  # Cycle D brique 1 — récap fidélité ligne-à-ligne (signal-only)
    _valuation_report = None     # Cycle D brique 2 — rapport de valorisation (None si non déclenché)
    _scorer_ok = True  # v17.1-B2.2 — init avant le bloc scorer (qui peut être désactivé)
    _facts_table_md_for_agents = ""
    try:
        from utils.financial_facts_table import build_facts_table_from_sources
        _facts_table_built = build_facts_table_from_sources(
            lang=lang,
            pappers_blocks=_pap_blocks if _pap_full else None,
            ch_blocks=_ch_blocks,
            gleif_blocks=(None if (isinstance(_gleif_blocks, dict) and _gleif_blocks.get("status") == "rejected") else _gleif_blocks),
            financial_statements_bundles=financial_statements_bundles,
            financial_signal_report=_financial_signal_report,
            financial_statements_block=financial_statements_block,
            attachments_block=attachments_block,
        )
        # v62.12 — liasses/CERFA page-citées enter the typed ledger BEFORE
        # proof reconciliation and agent prompts.  The former post-run row
        # promotion could improve an appendix but never the narrative/KPIs.
        _liasse_ledger_report6212 = {"facts_received": 0, "facts_added": 0}
        try:
            _lf_raw6212 = ((attachments_meta or {}).get("liasse_facts") or [])
            _liasse_ledger_report6212["facts_received"] = len(_lf_raw6212)
            if _lf_raw6212:
                from patches.liasse_fact_extractor import build_liasse_financial_facts as _blff6212
                _lf_objs6212 = _blff6212(_lf_raw6212)
                _existing_ids6212 = {
                    str(getattr(_f, "fact_instance_id", "") or "")
                    for _f in (getattr(_facts_table_built, "facts", []) or [])
                }
                for _lf_obj6212 in _lf_objs6212:
                    _fid6212 = str(getattr(_lf_obj6212, "fact_instance_id", "") or "")
                    if _fid6212 and _fid6212 in _existing_ids6212:
                        continue
                    _facts_table_built.add(_lf_obj6212)
                    if _fid6212:
                        _existing_ids6212.add(_fid6212)
                    _liasse_ledger_report6212["facts_added"] += 1
                try:
                    _facts_table_built.sort_by_scope()
                except Exception:
                    pass
            if (_liasse_ledger_report6212.get("facts_received") and diag_list is not None):
                diag_list.append({
                    "role": "liasse_cerfa_ingestion", "provider": "internal",
                    "model": "liasse_cerfa_page_confirmed_v6212", "status": "OK",
                    **_liasse_ledger_report6212,
                    "documents": (attachments_meta or {}).get("liasse_documents") or [],
                })
        except Exception as _lf_err6212:
            _liasse_ledger_report6212 = {
                "status": "ERROR",
                "error": f"{type(_lf_err6212).__name__}: {str(_lf_err6212)[:180]}",
                **_liasse_ledger_report6212,
            }
            if diag_list is not None:
                diag_list.append({
                    "role": "liasse_cerfa_ingestion", "provider": "internal",
                    "model": "liasse_cerfa_page_confirmed_v6212",
                    **_liasse_ledger_report6212,
                })
        # ── M6-B B.1 (v17.4.0) — Couche de preuve : contexte d'analyse,
        # identité du fait, périmètre, conflits, garde conso, board-safe
        # blockers, run-fingerprint. Fail-open : toute erreur laisse la
        # table intacte et le signal brut inchangé.
        try:
            from patches.analysis_context import infer_analysis_context as _b1_infer
            from patches.proof_layer import apply_b1_proof_layer as _b1_apply
            _b1_ctx = _b1_infer(
                brief,
                resolved_entity_name=(_resolved_name or pappers_confirmed_entity or ""),
                resolved_entity_id=str(getattr(_pap_rlog, "siren_used", "") or ""),
                resolution_from_registry=bool(_pap_full),
            )
            try:
                # B.1.3.5 — les noms de PROGRAMME bannis voyagent avec le ctx
                # jusqu'au fingerprint (proof_layer les lit).
                from patches.program_names import extract_banned_program_names as _ebpn2
                _b1_ctx.banned_program_names = sorted(_ebpn2(brief or ""))
            except Exception:
                pass
            # ── M6-B B.1.3 (audit dossier anglophone coté, bloquant 2) — FAITS DU BRIEF ─────
            # Les chiffres déclarés dans le brief entrent dans la couche de
            # preuve : visibles, structurés, source=Brief, JAMAIS board-safe.
            # Fini le « Revenue missing » quand le brief dit GBP 2.46bn.
            try:
                from patches.brief_facts import inject_brief_facts_once
                _scope_map = {"consolide": "CONSOLIDATED",
                              "social": "SOCIAL_STANDALONE"}
                _bf_scope = _scope_map.get(
                    (getattr(_b1_ctx, "target_perimeter_level", "") or "").lower(),
                    "UNKNOWN")
                # B.1.3.1 (audit P2) — helper IDEMPOTENT partagé avec le
                # fallback de table : un seul point d'injection, zéro doublon.
                _brief_facts = inject_brief_facts_once(
                    _facts_table_built, brief, lang=lang, scope=_bf_scope,
                    perimeter_entity=getattr(_b1_ctx, "target_entity", "") or "")
                if _brief_facts:
                    diag_list.append({
                        "role": "brief_facts", "provider": "internal",
                        "model": "brief_facts_b13", "status": "OK",
                        "summary": (f"{len(_brief_facts)} fait(s) financiers "
                                    f"extraits du brief (non board-safe) : "
                                    + " | ".join(f"{f.label}={f.value}"
                                                 for f in _brief_facts[:5])),
                    })
            except Exception:
                pass
            # ── B.1.3.1 (audit P1) — RÉCONCILIATION PRÉCOCE : si entity_scope
            # porte un nom d'analyse PLUS PRÉCIS que la cible courte du brief
            # (« dossier anglophone coté Group plc » ⊃ « dossier anglophone coté »), il réalimente le
            # contexte ET les faits du brief AVANT _b1_apply — sinon les
            # stable_fact_key (calculées à l'apply) et Christopher indexent
            # « dossier anglophone coté » pendant que le CR affiche le groupe coté. Résolution
            # LOCALE ici : _ch_blocks/_resolved_name sont déjà disponibles ;
            # le _entity_scope_obj aval (M6-A2) reste inchangé pour ses autres
            # consommateurs. La brique zéro ne doit pas être le prochain
            # endroit où la vérité se décale.
            try:
                if _b1_ctx is not None:
                    from patches.entity_scope import \
                        resolve_entity_scope as _res_scope_b131
                    _ch_primary_early = ((_ch_blocks.get("primary") or "")
                                         if isinstance(_ch_blocks, dict) else "")
                    _ch_cn_early = ((_ch_blocks.get("company_number") or "")
                                    if isinstance(_ch_blocks, dict) else "")
                    _es_early = _res_scope_b131(
                        brief or "",
                        resolved_name=_resolved_name or "",
                        registry_name=_ch_primary_early,
                        registry_id=str(_ch_cn_early),
                        registry_source="companies_house",
                        lang=lang,
                    )
                    _es_name = str(getattr(_es_early, "analysis_entity", "")
                                   or "").strip()
                    _ctx_t = str(getattr(_b1_ctx, "target_entity", "")
                                 or "").strip()
                    if (_es_name and _ctx_t
                            and _es_name.lower() != _ctx_t.lower()
                            and _ctx_t.lower() in _es_name.lower()
                            and len(_es_name) > len(_ctx_t)):
                        _b1_ctx.target_entity = _es_name
                        try:
                            _b1_ctx.inference_signals = list(
                                getattr(_b1_ctx, "inference_signals", [])
                                or []) + ["target_refined_from_entity_scope"]
                        except Exception:
                            pass
                        for _bf_r in (getattr(_facts_table_built, "facts", [])
                                      or []):
                            if (str(getattr(_bf_r, "source_doc", "") or "")
                                    .strip().lower() == "brief"):
                                _bf_r.perimeter_entity = _es_name
                        if diag_list is not None:
                            diag_list.append({
                                "role": "analysis_context_refine",
                                "provider": "internal",
                                "model": "entity_scope",
                                "status": "OK",
                                "summary": (f"target_entity affiné : "
                                            f"« {_ctx_t} » → « {_es_name} » "
                                            f"(entity_scope, avant clés "
                                            f"stables)"),
                            })
            except Exception:
                pass
            # ── B.1.3 (audit dossier industriel (composants) P1) — fingerprint EXPLOITABLE : vrais
            # candidats multi-registres avec issue, quarantaine taguée,
            # raison de choix du registre effectivement retenu.
            _b1_candidates = []
            _b1_choice_reason = ""
            if _pap_rlog is not None:
                _pn = getattr(_pap_rlog, "primary_name", "") or ""
                if _pn:
                    _b1_candidates.append(f"{_pn} — pappers:retenu")
                for _s in (getattr(_pap_rlog, "secondaries", []) or []):
                    _b1_candidates.append(f"{_s} — pappers:secondaire")
                for _nf in (getattr(_pap_rlog, "entities_not_found", []) or []):
                    _b1_candidates.append(f"{_nf} — pappers:introuvable")
                _b1_choice_reason = str(getattr(_pap_rlog, "path", "") or "")
            try:
                if _ch_blocks and _ch_blocks.get("company_number"):
                    _cht = (_ch_blocks.get("primary")
                            or _ch_blocks.get("company_number"))
                    _b1_candidates.append(
                        f"{_cht} ({_ch_blocks.get('company_number')}) — "
                        f"ch:retenu[{_ch_blocks.get('confidence', '')}]")
                    if not _b1_choice_reason:
                        _b1_choice_reason = f"ch:{_ch_blocks.get('confidence','')}"
            except Exception:
                pass
            try:
                if isinstance(_gleif_blocks, dict) and _gleif_blocks.get("primary"):
                    _b1_candidates.append(
                        f"{_gleif_blocks.get('primary')} — gleif:retenu")
            except Exception:
                pass
            _b1_result = _b1_apply(
                _facts_table_built, _b1_ctx,
                raw_signal_solid=bool(_financial_signal_in_attachments_solid),
                diag_rows=diag_list,
                registry_entity=(_resolved_name or ""),
                registry_entity_id=str(getattr(_pap_rlog, "siren_used", "") or ""),
                registry_resolution_id=str(getattr(_pap_rlog, "siren_used", "") or ""),
                candidate_entities=_b1_candidates,
                choice_reason=_b1_choice_reason,
                lang=lang,
            )
            _b1_conflicts = _b1_result.get("conflicts") or []
            # B.1.2 (P0) — la clé existe par contrat, défaut fail-safe False :
            # sans preuve, jamais de signal effectif.
            _fin_signal_solid_effective = bool(
                _b1_result.get("signal_effective", False))
            for _b1_row in (_b1_result.get("journal_rows") or []):
                diag_list.append(_b1_row)
            # Signal brut gaté → la ligne « Signal financier exploitable
            # détecté » (Couche 1, l.~1849) est requalifiée HONNÊTEMENT :
            # montrée, mais À VÉRIFIER, avec la raison.
            # B.1.3.16 (dossier industriel (composants) run 1 : « Sans pièce jointe » + « Signal
            # exploitable détecté » dans le MÊME CR) — à ZÉRO fichier
            # utilisateur, la ligne signal disparaît du livrable (le signal
            # interne reste au diagnostic) ; le label « Pièces jointes
            # (multi-format…) » mentait sur un bloc contexte registres.
            # B.1.3.17 — la condition 3.16 len(attachments_meta or []) était
            # morte-née (len(dict) compte les CLÉS) : fichiers réels via
            # _user_files_count (filenames/file_list, notion préexistante).
            try:
                if _user_files_count(attachments_meta) == 0:
                    _sig_rm = [f for f in (getattr(_facts_table_built, "facts", []) or [])
                               if (getattr(f, "label", "") or "").startswith(
                                   "Signal financier exploitable")]
                    for _f_rm in _sig_rm:
                        _facts_table_built.facts.remove(_f_rm)
            except Exception:
                pass
            _b1323_zero_confirmed = False
            try:
                _b1323_zero_confirmed = (
                    int(((_extraction_fidelity or {}).get("per_page") or {})
                        .get("verbatim_on_page", 0) or 0) == 0
                    and _user_files_count(attachments_meta) > 0)
            except Exception:
                _b1323_zero_confirmed = False
            # B.1.3.23 P1-F' — contrat : 0 confirmé page ⇒ jamais « exploitable »,
            # indépendant du gate périmètre (un fait social FULL maintenait le
            # signal et le label brut restait — constaté ×2).
            if _financial_signal_in_attachments_solid and (
                    (not _fin_signal_solid_effective) or _b1323_zero_confirmed):
                try:
                    from utils.financial_facts_table import FactStatus as _FS_b1
                    for _f_b1 in (getattr(_facts_table_built, "facts", []) or []):
                        _lbl_b1 = (getattr(_f_b1, "label", "") or "")
                        if _lbl_b1.startswith("Signal financier exploitable"):
                            _f_b1.status = _FS_b1.A_VERIFIER
                            # B.1.3.17 (runs 9/2 : « Exploitable » contredit
                            # « 0 page-confirmed — not exploitable ») — label
                            # requalifié ; EN via _METRIC_LABEL_EN au rendu.
                            # Row partagée : corrige CR ET deck d'un coup.
                            _f_b1.label = ("Fragments à consonance financière "
                                           "détectés — non utilisés comme faits")
                            _f_b1.notes = list(getattr(_f_b1, "notes", []) or []) + [
                                ("Signal brut porté par des faits hors périmètre "
                                 "— exclu du score (règle B.1)")]
                except Exception:
                    pass
            # B.1.2 (P0) — le témoin de preuve fait foi : apply_b1_proof_layer
            # avale ses erreurs internes (fail-open exécution) ; « l'appel a
            # retourné » ne vaut PAS « la preuve a tourné ».
            _b1_applied = bool(_b1_result.get("proof_applied"))
            if logger:
                try:
                    log_event(
                        logger, "info", "proof_layer_b1",
                        "b1_applied",
                        summary=(
                            f"ctx={getattr(_b1_ctx, 'mode', '?')} "
                            f"conf={getattr(_b1_ctx, 'inference_confidence', '?')} "
                            f"conflicts={len(_b1_conflicts)} "
                            f"signal_raw={bool(_financial_signal_in_attachments_solid)} "
                            f"signal_effective={_fin_signal_solid_effective} "
                            f"gate={_b1_result.get('signal_gate_reason', '')}"
                        ),
                    )
                except Exception:
                    pass
        except Exception as _b1_e:
            if logger:
                try:
                    log_event(logger, "warning", "proof_layer_b1",
                              f"b1_error | {type(_b1_e).__name__}: {str(_b1_e)[:160]}")
                except Exception:
                    pass
        # Format markdown injecté tel quel dans tous les prompts agents :
        # cohérence totale entre ce que les agents voient et ce que
        # l'utilisateur lira dans le DOCX/PPTX final (même fonction de rendu).
        _facts_table_md_for_agents = _facts_table_built.to_markdown_table(
            lang=lang, analysis_context=_b1_ctx, conflicts=_b1_conflicts)
        try:
            from patches import a1_probe as _a1p
            _a1p.put(facts_table_n_facts_total=getattr(_facts_table_built, "n_facts_total", None),
                     facts_table_n_facts_solid=getattr(_facts_table_built, "n_facts_solid", None))
            for _f in (getattr(_facts_table_built, "facts", []) or []):
                _fact_label = (getattr(_f, "label", "") or "").lower()
                if any(_k in _fact_label for _k in ("chiffre d'affaires", "chiffre d affaires",
                                                    "revenue", "turnover", "ca consolid")):
                    _a1p.put(revenue_fact_status=getattr(_f, "status", None),
                             revenue_fact_value=getattr(_f, "value", None),
                             revenue_fact_source=getattr(_f, "source", None),
                             revenue_fact_page=getattr(_f, "page", None))
                    break
        except Exception:
            pass
        if logger:
            try:
                log_event(
                    logger, "info", "financial_facts_table",
                    "facts_table_built_upstream",
                    summary=(
                        f"facts={_facts_table_built.n_facts_total} "
                        f"solid={_facts_table_built.n_facts_solid} "
                        f"score={_facts_table_built.traceability_score}/100 "
                        f"injected_into_agents=True"
                    ),
                )
            except Exception:
                pass
    except Exception as _ft_e:
        if logger:
            try:
                log_event(
                    logger, "warning", "financial_facts_table",
                    "facts_table_build_upstream_error",
                    summary=f"{type(_ft_e).__name__}: {str(_ft_e)[:200]}",
                )
            except Exception:
                pass

    # ── M6-B B.1.1 (audit gate B.2, P2) — Prudence renforcée sans preuve ─────
    # Si la couche de preuve n'a PAS tourné (échec de la construction de table
    # ou du bloc B.1 lui-même), le signal brut ne peut pas être certifié en
    # périmètre : il ne doit pas débrider Finance. Fail-open sur l'EXÉCUTION
    # (le run continue), fail-SAFE sur la CERTIFICATION (signal effectif forcé
    # False, explicitement journalisé — jamais de prudence silencieuse).
    if not _b1_applied:
        _b1_raw_neutralized = bool(_fin_signal_solid_effective
                                   or _financial_signal_in_attachments_solid)
        _fin_signal_solid_effective = False
        try:
            diag_list.append({
                "role": "proof_layer_b1", "provider": "internal",
                "model": "proof_layer_b1", "status": "NOT_APPLIED",
                "summary": ("⚠️ Couche de preuve B.1 NON appliquée sur ce run "
                            "(échec table/B.1). Signal financier traité en "
                            "prudence renforcée"
                            + (" — signal brut présent NEUTRALISÉ (non "
                               "certifié périmètre)." if _b1_raw_neutralized
                               else " — aucun signal brut à neutraliser.")),
            })
        except Exception:
            pass
        if logger:
            try:
                log_event(
                    logger, "warning", "proof_layer_b1", "b1_not_applied",
                    summary=(f"prudence_renforcee | "
                             f"raw_neutralized={_b1_raw_neutralized}"),
                )
            except Exception:
                pass

    # Bloc complet injecté en tête de chaque prompt agent.
    # L'instruction est explicite : utiliser ces chiffres en priorité, tagger
    # toute valeur absente comme [ESTIM IA] ou [À VÉRIFIER]. Les agents qui
    # ignoreraient la consigne sont rattrapés en aval par le post-processeur
    # entity_validator + lucidity_wording.
    if _facts_table_md_for_agents:
        # v16.5.75 — Item #9 : sous-typologie ESTIM (3 sous-types).
        # Avant v16.5.75 : les agents marquaient toute donnée non-sourcée
        # comme [ESTIM IA] sans distinction. Or il y a 3 types très différents
        # d'estimations qu'un DAF rigoureux doit distinguer :
        #   1. ESTIM-FILINGS : reconstitution depuis comptes statutaires
        #      (Pappers, Companies House, SEC). Ex: "CA consolidé estimé
        #      depuis CA statutaire France 60 M€ × hypothèse perimeter 1.5".
        #      → fiable mais ≠ consolidé groupe.
        #   2. ESTIM-COMPARABLE : extrapolation depuis sociétés comparables
        #      du secteur (benchmark). Ex: "EBITDA marge estimée 12% via
        #      benchmark sectoriel sportswear DTC européen". → ordre de
        #      grandeur, à challenger sur spécificités du dossier.
        #   3. ESTIM-HYPOTHÈSE : pure hypothèse de l'agent (no anchor data).
        #      Ex: "BFR estimé en pression élevée par défaut sectoriel". →
        #      à challenger en priorité, plus fragile.
        # Cette précision permet au DG de hiérarchiser ses arbitrages :
        # ESTIM-FILINGS → décision presque possible, ESTIM-HYPOTHÈSE → action
        # première = aller chercher la vraie donnée.
        if lang == "en":
            _facts_preamble_lang = (
                "INSTRUCTION: use THESE figures as the priority source of truth. "
                "If you cite a figure absent from this table, you MUST tag it "
                "explicitly with one of these THREE estimation sub-types:\n"
                "  - [ESTIM-FILINGS] = reconstructed from statutory accounts "
                "(Pappers/Companies House/SEC). Reliable but not consolidated.\n"
                "  - [ESTIM-COMPARABLE] = extrapolated from sector peers / "
                "benchmark. Order of magnitude only, must be challenged.\n"
                "  - [ESTIM-HYPOTHÈSE] = your own hypothesis without anchor "
                "data. Most fragile, must be challenged first.\n"
                "An untagged figure will be treated as a claimed FACT and corrected "
                "by the post-processor.\n"
            )
        else:
            _facts_preamble_lang = (
                "INSTRUCTION : utilise CES chiffres en priorité absolue. Si tu cites "
                "un chiffre absent de cette table, tu DOIS le tagger explicitement "
                "avec l'un de ces TROIS sous-types d'estimation :\n"
                "  - [ESTIM-FILINGS] = reconstitué depuis comptes statutaires "
                "(Pappers/Companies House/SEC). Fiable mais ≠ consolidé groupe.\n"
                "  - [ESTIM-COMPARABLE] = extrapolé depuis comparables sectoriels / "
                "benchmark. Ordre de grandeur seulement, à challenger.\n"
                "  - [ESTIM-HYPOTHÈSE] = ta propre hypothèse sans donnée d'ancrage. "
                "Plus fragile, à challenger en priorité.\n"
                "Tout chiffre non taggé sera traité comme un FAIT prétendu et "
                "corrigé par le post-processeur.\n"
            )
        _facts_block_for_agents = (
            "\n---\n"
            + _facts_table_md_for_agents
            + "\n\n"
            + _facts_preamble_lang
            + "---\n"
        )
    else:
        _facts_block_for_agents = ""

    def _facts_ctx(role: str) -> str:
        """v16.5.73 — Retourne la table de faits Couche 1 + instruction d'usage.

        Contrairement à _fs_ctx() qui filtre par _ROLES_FULL_ALIASES, cette
        fonction retourne la même table à TOUS les rôles (Stratégie, Brief
        CoDIR, Marketing, Finance, Supply Chain, Commercial, Synthèse, DG).

        Objectif : garantir la cohérence des chiffres entre les 8 directions
        du CoDIR virtuel. Le _fs_ctx (FS bruts) reste réservé aux rôles FULL
        comme avant — la table Couche 1 = socle commun, les FS bruts =
        supplément pour décideurs.

        L'argument `role` est conservé pour permettre une éventuelle
        différenciation future (ex. omettre certains faits non pertinents
        pour Marketing). En v16.5.73, tous les rôles reçoivent la même chose.
        """
        return _facts_block_for_agents
    # ─── Fin v16.5.73 — Couche 1 Source Traceability injectée ──────────────

    # ── v16.5.60 — Détection du profil société + whitelist globale ───────────
    # Le profil est calculé une seule fois pour la session et pilote ensuite :
    #   (a) la désactivation/adaptation des rôles (ex. SC skip pour SASU solo),
    #   (b) l'injection d'un style_hint ciblé dans les prompts,
    #   (c) la construction d'un hint factuel en tête de prompt.
    _company_profile = None
    _profile_hint = ""
    if detect_profile is not None:
        try:
            _pap_fiche = None
            _pap_comptes = None
            # On tente de récupérer la fiche Pappers si disponible via le
            # resolution_log (qui porte les données structurées).
            if _pap_rlog is not None:
                _pap_fiche = getattr(_pap_rlog, "fiche", None) or {}
                _pap_comptes = getattr(_pap_rlog, "comptes", None) or {}
            _company_profile = detect_profile(
                pappers_fiche=_pap_fiche,
                pappers_comptes=_pap_comptes,
                brief=brief,
            )
            if _company_profile and format_profile_hint:
                _profile_hint = format_profile_hint(_company_profile, lang=lang)

            # ────────────────────────────────────────────────────────────────
            # Patch v16.5.72.2 P0-1 (audit ChatGPT round 17) — REFONTE
            # ────────────────────────────────────────────────────────────────
            # Bug v16.5.72.1 : on parsait `_ch_blocks["full"]` avec une
            # regex `company[\s_]?number` qui ne matchait QU'EN ANGLAIS.
            # En français le bloc dit "Numéro de société : 03458224" → 0
            # match → profil dossier anglophone coté retombait sur "size=pme nature=services".
            #
            # Solution v16.5.72.2 : utiliser les champs STRUCTURÉS exposés
            # par companies_house_tool / gleif_tool / pappers (langue-agnostiques) :
            #   _ch_blocks["company_number"], ["primary"], ["status"]
            #   _gleif_blocks["primary_lei"], ["primary"], ["primary_country"]
            # On ne parse plus le texte rendu ("full"), donc le branchement
            # marche identiquement en FR et EN.
            # B.1.3.23 P0-C — le SIREN Pappers n'était propagé au profil que
            # via SIREN_DIRECT ; sur name-search confirmé, company_number
            # restait None → rendu LEI-only. FR : SIREN/Pappers = primaire.
            try:
                if (_company_profile is not None
                        and not getattr(_company_profile, "company_number", None)
                        and _pap_resolved_sirens):
                    _company_profile.company_number = str(_pap_resolved_sirens[0])
                    _company_profile.company_number_kind = "siren"
                    _company_profile.registry = "Pappers"
                    if not getattr(_company_profile, "country", ""):
                        _company_profile.country = "FR"
            except Exception:
                pass
            _entity_scope_obj = None   # M6-A2 — périmètre entité (rempli si CH résout)
            _temporal_frame_obj = None # M6-A3 — cadre temporel (run/comptes/scénario)
            if _company_profile is not None:
                # CH — UK Company Number + nom officiel + statut
                if _ch_blocks and isinstance(_ch_blocks, dict):
                    _ch_cn = _ch_blocks.get("company_number") or ""
                    _ch_primary = _ch_blocks.get("primary") or ""
                    if _ch_cn and not _company_profile.company_number:
                        _company_profile.country = "UK"
                        _company_profile.company_number = str(_ch_cn)
                        _company_profile.company_number_kind = "ch_number"
                        _company_profile.registry = "Companies House"
                        _company_profile.source = "companies_house"
                        _company_profile.confidence = "high"
                        if _ch_primary:
                            _company_profile.company_name_official = str(_ch_primary)
                        # ── M6-A2.x — entité résolue via Companies House = UK :
                        # on pose le pays + la forme juridique CORRECTE et on
                        # neutralise toute forme française résiduelle (Pappers a pu
                        # matcher un homonyme FR « dossier anglophone coté SAS » sans identifiant).
                        _company_profile.country = "UK"
                        _lf_low = (_company_profile.legal_form or "").lower()
                        _FR_FORMS = ("sasu", "sas", "sarl", "eurl", "selarl", "sci",
                                     "scp", "société par actions", "société à responsabilité")
                        if _ch_primary and "plc" in _ch_primary.lower():
                            _company_profile.legal_form = "public limited company"
                        elif _ch_primary and ("limited" in _ch_primary.lower()
                                              or _ch_primary.lower().rstrip().endswith("ltd")):
                            _company_profile.legal_form = "private limited company"
                        elif any(_f in _lf_low for _f in _FR_FORMS):
                            # forme française sur entité UK → fausse → on la retire
                            _company_profile.legal_form = ""
                # ── M6-A2 — périmètre entité (lecture seule, n'altère pas la
                # résolution CH ; sépare analyse / registre / périmètre financier
                # pour un en-tête CR honnête + alimentation probe). ──
                try:
                    from patches.entity_scope import resolve_entity_scope as _resolve_scope
                    _ch_primary_for_scope = (_ch_blocks.get("primary") or "") if (_ch_blocks and isinstance(_ch_blocks, dict)) else ""
                    _ch_cn_for_scope = (_ch_blocks.get("company_number") or "") if (_ch_blocks and isinstance(_ch_blocks, dict)) else ""
                    _entity_scope_obj = _resolve_scope(
                        brief or "",
                        resolved_name=_resolved_name or "",
                        registry_name=_ch_primary_for_scope,
                        registry_id=str(_ch_cn_for_scope),
                        registry_source="companies_house",
                        lang=lang,
                    )
                except Exception:
                    _entity_scope_obj = None
                # ── M6-A3 — cadre temporel : trois dates distinctes (run réel /
                # derniers comptes registre / scénario demandé). Rend explicite que
                # la filing date n'est pas la date d'analyse, et qu'un scénario passé
                # est rétrospectif (le défaut FR « T2 2025 » présenté comme courant). ──
                try:
                    from patches.temporal_frame import build_temporal_frame as _btf
                    import datetime as _dt_a3
                    _lad = ""
                    _full_ch = (_ch_blocks.get("full") or "") if (_ch_blocks and isinstance(_ch_blocks, dict)) else ""
                    import re as _re_a3
                    _m_lad = _re_a3.search(r"(?:accounts|comptes)[^\n]{0,40}?(20\d\d-\d{2}-\d{2})",
                                           _full_ch, _re_a3.I)
                    if _m_lad:
                        _lad = _m_lad.group(1)
                    _temporal_frame_obj = _btf(
                        run_as_of_date=(_run_now.date().isoformat()
                                        if "_run_now" in locals() else ""),
                        latest_accounts_date=_lad,
                        scenario_date=(_analysis_as_of or ""),
                    )
                    # v62.12.2 — the deep-scan journal is the authority for the
                    # latest document year actually reached.  Keep this signal
                    # separate from the latest page-confirmed critical period.
                    try:
                        _fdscan62122 = ((attachments_meta or {}).get(
                            "financial_deep_scan") or {})
                        _years62122 = []
                        for _pdfd62122 in (_fdscan62122.get("pdf_priority") or []):
                            if str(_pdfd62122.get("outcome") or "").startswith("scanned"):
                                _yy62122 = int(_pdfd62122.get(
                                    "content_period_year") or 0)
                                _bucket62122 = str(_pdfd62122.get("fy_bucket") or "")
                                if _yy62122 and _bucket62122 == "current":
                                    _years62122.append(_yy62122)
                        if _years62122:
                            _temporal_frame_obj.latest_document_year_detected = str(
                                max(_years62122))
                    except Exception:
                        pass
                except Exception:
                    _temporal_frame_obj = None
                # ── M6-B couche 1 — extraction de faits financiers (LECTURE SEULE).
                # Expose la table de faits brute (label/valeur/période/scope/source/
                # page/confiance) pour validation terrain. N'altère NI le score NI
                # l'analyse à ce stade — le couplage au cap viendra ensuite.
                try:
                    from patches.financial_extractor import (
                        extract_financial_facts as _eff, facts_coverage as _fcov)
                    _fscope = ""
                    if _entity_scope_obj is not None:
                        _fs_raw = getattr(_entity_scope_obj, "financial_scope", "") or ""
                        _fscope = {"consolidated_group": "consolidated group",
                                   "solo": "solo entity"}.get(_fs_raw, "")
                    _fin_facts_obj = _eff(attachments_block or "", lang=lang,
                                          default_scope=_fscope)
                    _fin_facts_cov = _fcov(_fin_facts_obj)
                    try:
                        from patches import a1_probe as _a1pf
                        _a1pf.put_facts(_fin_facts_obj, _fin_facts_cov)
                    except Exception:
                        pass
                except Exception:
                    _fin_facts_obj, _fin_facts_cov = [], {}
                if _gleif_blocks and isinstance(_gleif_blocks, dict):
                    # M6-A2.1.2 — garde GLEIF symétrique : ne pas injecter un LEI/pays
                    # GLEIF si le nom GLEIF ne partage aucun token avec l'entité d'analyse.
                    # Sûr pour dossier industriel (composants) : GLEIF a résolu « <GROUPE> » → token partagé → injecté.
                    _gleif_name = (_gleif_blocks.get("primary")
                                   or _gleif_blocks.get("primary_name") or "")
                    _gleif_reject = False
                    try:
                        from patches.entity_scope import should_quarantine_registry as _sqr2
                        _gleif_reject = bool(_gleif_name) and _sqr2(_analysis_name_q, _gleif_name)
                    except Exception:
                        _gleif_reject = False
                    if _gleif_reject:
                        try:
                            _company_profile.notes.append(
                                f"M6-A2.1.2 — candidat GLEIF rejeté (mismatch entité) : "
                                f"« {_gleif_name} ». LEI/pays GLEIF non injectés.")
                        except Exception:
                            pass
                    _gleif_lei = "" if _gleif_reject else (_gleif_blocks.get("primary_lei") or "")
                    if _gleif_lei and len(_gleif_lei) == 20 and not _company_profile.lei:
                        _company_profile.lei = str(_gleif_lei)
                    # Si pas encore de country et GLEIF a un primary_country
                    if not _gleif_reject and not _company_profile.country:
                        _gleif_country = _gleif_blocks.get("primary_country") or ""
                        if _gleif_country:
                            _company_profile.country = str(_gleif_country).upper()
                # FR — Si pas international détecté mais SIREN Pappers, taguer FR
                if (_company_profile.country is None
                        and _pap_full
                        and _pap_rlog is not None
                        and getattr(_pap_rlog, "siren_used", "")):
                    _company_profile.country = "FR"
                    _company_profile.company_number = getattr(_pap_rlog, "siren_used", "")
                    _company_profile.company_number_kind = "siren"
                    _company_profile.registry = "Pappers"
                    _company_profile.company_name_official = getattr(
                        _pap_rlog, "primary_name", None,
                    )

                # Patch v16.5.72.11 (retex Robin sur FDE) — Backfill
                # company_name_official si Pappers a un primary_name MÊME si
                # country a déjà été défini par GLEIF avant (cas FDE : GLEIF
                # retourne FR → bloc ci-dessus skip → company_name_official
                # restait None alors que Pappers a "LA FRANCAISE DE L'ENERGIE").
                if (not _company_profile.company_name_official
                        and _pap_rlog is not None
                        and getattr(_pap_rlog, "primary_name", "")):
                    _pap_official_name = getattr(_pap_rlog, "primary_name", None)
                    if _pap_official_name:
                        _company_profile.company_name_official = str(_pap_official_name)

            # ── M6-A2.1 — QUARANTINE DE RÉSOLUTION REGISTRE ───────────────────
            # Si le nom registre résolu (Pappers/CH/GLEIF) ne partage AUCUN token
            # significatif avec l'entité d'analyse, c'est un faux candidat (ex. run
            # dossier industriel (composants) → <AUTRE SOCIÉTÉ> via SIREN confirmé par erreur). On NE contamine
            # PAS le profil injecté aux agents ni la table de faits : on neutralise
            # les champs registre et on conserve l'entité d'analyse du brief.
            # dossier anglophone coté (Group plc vs LIMITED, token « <marque> » partagé) n'est JAMAIS
            # quarantainé. Fail-open : en cas de doute, on ne quarantine pas.
            # M6-A2.1.1 — propage la quarantine AMONT au profil (flags + champs).
            # La décision et la purge des blocs bruts ont déjà eu lieu en amont
            # (avant attachments_block / facts table / _pap_ctx) ; ici on ne fait
            # que refléter l'état sur _company_profile pour les sorties structurées.
            if _company_profile is not None and _registry_quarantined:
                _company_profile.registry_quarantined = True
                _company_profile.registry_rejected_name = _registry_rejected_name
                _company_profile.company_name_official = None
                _company_profile.company_number = None
                _company_profile.company_number_kind = ""
                _company_profile.registry = None
                if (_company_profile.source or "") == "pappers":
                    _company_profile.headcount = None
                    _company_profile.ca_eur = None
                    _company_profile.ape_code = ""
                    _company_profile.legal_form = ""
                    _company_profile.source = "brief"
                try:
                    _company_profile.notes.append(
                        f"M6-A2.1.1 — candidat registre rejeté (mismatch entité) : "
                        f"« {_registry_rejected_name} ». Données registre exclues EN AMONT "
                        "des agents, de la table de faits et de attachments_block.")
                except Exception:
                    pass

            # P0-2 (M.5.2) — garde de cohérence TAILLE + réconciliation d'entité,
            # APRÈS enrichissement CH/GLEIF (nom officiel désormais connu) et AVANT
            # le recalcul du hint + le log diag (qui doivent refléter la correction).
            if enforce_size_sanity is not None and _company_profile is not None:
                try:
                    _company_profile = enforce_size_sanity(_company_profile, brief)
                except Exception:
                    pass

            # Patch v16.5.72.5 (audit ChatGPT round 20 P0) — RECALCUL CRITIQUE
            # de _profile_hint après l'enrichissement CH/GLEIF/Pappers.
            #
            # Bug v16.5.72.4 : _profile_hint était calculé ligne 2787 AVANT
            # l'enrichissement international. Conséquence : sur dossier anglophone coté, les
            # 5 prompts agents downstream (Strategie/Brief/Marketing/Finance/
            # Synthese/DG) recevaient un hint sans country=UK ni Company
            # Number ni LEI → le LLM pouvait halluciner SIREN ou mauvais
            # profil sectoriel.
            #
            # Solution : recalculer _profile_hint après que les champs
            # country/company_number/lei/registry/sector_label aient été
            # injectés depuis CH/GLEIF/Pappers.
            if _company_profile and format_profile_hint:
                _profile_hint = format_profile_hint(_company_profile, lang=lang)

            # M6-S.2.1.1 — verrou entité : _profile_hint est préfixé à TOUS les
            # prompts de rôle (Strategy/Marketing/Finance/Commercial/SC/DG…). On y
            # impose l'entité d'ANALYSE comme sujet métier (registre = identité seule).
            try:
                if _entity_scope_obj is not None:
                    from patches.entity_scope import entity_scope_for_agents as _esfa
                    _eblock = _esfa(_entity_scope_obj, lang=lang)
                    if _eblock:
                        _profile_hint = (_eblock + "\n" + _profile_hint) if _profile_hint else _eblock
            except Exception:
                pass

            if logger and _company_profile:
                log_event(logger, "info", "codir_engine", "profile_detected",
                          summary=_company_profile.summary_line())
            if diag_list is not None and _company_profile:
                diag_list.append({
                    "role":     "company_profile",
                    "provider": "internal",
                    "model":    "company_profile_v1",
                    "status":   "OK",
                    "profile":  _company_profile.to_dict(),
                })

            # v16.5.65 — Ré-évaluation du brief_mode après résolution profil
            # Le levier "context" peut basculer de False à True si Pappers a
            # enrichi le profil avec confidence >= medium. On recalcule donc
            # brief_mode avec le profil nouvellement disponible.
            if (_briefcheck_result is not None
                    and _company_profile is not None
                    and _company_profile.confidence in ("medium", "high")
                    and _company_profile.source not in ("default", "heuristic")):
                try:
                    from patches.briefcheck import compute_brief_mode as _recompute_mode
                    _new_mode = _recompute_mode(
                        brief, _company_profile.to_dict(), lang=lang)
                    _old_mode = (_briefcheck_result.get("brief_mode") or {}).get("mode")
                    if _new_mode["mode"] != _old_mode:
                        _briefcheck_result["brief_mode"] = _new_mode
                        # Mettre à jour la bannière concaténée
                        bparts = []
                        if _new_mode.get("banner_markdown"):
                            bparts.append(_new_mode["banner_markdown"])
                        dc_banner = (_briefcheck_result.get("doc_check") or {}).get("banner_markdown", "")
                        if dc_banner:
                            bparts.append(dc_banner)
                        _briefcheck_result["banner_markdown"] = "\n\n---\n\n".join(bparts)
                        if logger:
                            log_event(logger, "info", "briefcheck",
                                      f"brief_mode re-evaluated after profile resolution: "
                                      f"{_old_mode} → {_new_mode['mode']}")
                except Exception as _remo_err:
                    if logger:
                        log_event(logger, "warning", "briefcheck",
                                  f"mode re-evaluation failed: {str(_remo_err)[:100]}")
        except Exception as _pe:
            if logger:
                log_event(logger, "warning", "codir_engine", f"profile_error | {str(_pe)[:120]}")

    # M6-A2.2.7 — honnêteté Pappers : réécriture INCONDITIONNELLE des banners après
    # quarantine registre, hors du chemin de réévaluation du brief_mode (qui ne s'exécute
    # pas toujours). Avant tout assemblage CR, donc le livrable ne contredit jamais la purge.
    if _registry_quarantined and _briefcheck_result:
        _rewrite_pappers_banner_after_quarantine(_briefcheck_result, _registry_rejected_name)

    # Whitelist globale pour validator : brief + PJ + contextes Pappers
    # v16.5.74 — Ajouter aussi le markdown de la table Couche 1 pour que les
    # termes/entités sourcés dans la table de faits ne soient PAS flaggés
    # comme NON SOURCÉ par l'entity_validator.
    # Avant v16.5.74 : "CAPEX [NON SOURCÉ]" sur FDE alors que CAPEX figurait
    # dans la table Couche 1 avec valeur 250 → ~85 faux positifs cumulés sur
    # 4 tests (dossier de conseil, FDE, dossier réseau de soins, dossier anglophone coté).
    _whitelist_global: set[str] = set()
    if build_whitelist is not None:
        try:
            _whitelist_global = build_whitelist(
                brief,
                attachments_block,
                _pap_full,
                _pap_summary,
                _facts_table_md_for_agents,  # v16.5.74 — Couche 1 sourcée
            )
        except Exception:
            _whitelist_global = set()

    def _validate(txt: str, role: str) -> str:
        """
        Post-process un output de rôle :
          1. v16.5.60 — flagge les entités hallucinées avec [NON SOURCÉ]
          2. v16.5.67 — applique le vocabulaire Lucidité (VALIDÉE → RECOMMANDÉ,
             DÉCIDÉ → À ARBITRER, CONFIRMÉ → À INVESTIGUER) avec log auditable.

        Silent fallback : si une étape échoue, on retourne le texte à ce point.

        v62.13.9.4.15 — LE BLOC A1 EST SANCTUARISÉ À SA RÉCEPTION. Les
        validateurs de prose (entités, lucidité, garde juridique, hygiène)
        écrivaient leurs annotations À L'INTÉRIEUR du JSON structuré : le run
        du 02/09/2026 à 15:04 porte encore « CIBLE [NON SOURCÉ] » dans le
        champ ``tag`` de Commercial, « CONSTATE [NON SOURCÉ] » dans
        ``modality``, « FUTUR [NON SOURCÉ] » dans ``time_frame``. Le
        nettoyage 9.4.13/9.4.14 corrigeait les symptômes connus champ par
        champ ; la cause est ici. La chaîne est désormais : réponse brute →
        extraction et gel des blocs AGENT_JSON → validation de la narrative
        seule → réassemblage octet pour octet.
        """
        if not txt:
            return txt
        if _AGENT_JSON_BLOCK_RE.search(txt):
            return _map_outside_agent_json(txt, lambda seg: _validate(seg, role))

        # 1. Entity validator
        if validate_entities is not None:
            try:
                res = validate_entities(txt, _whitelist_global, mode="annotate", lang=lang)
                if res.flagged_count > 0:
                    if logger:
                        log_event(
                            logger, "warning", "codir_engine",
                            "entities_flagged",
                            role=role,
                            count=res.flagged_count,
                            entities=res.flagged_entities[:10],
                        )
                    if diag_list is not None:
                        diag_list.append({
                            "role":    f"{role}_entity_check",
                            "provider": "internal",
                            "model":   "entity_validator_v1",
                            "status":  "FLAGGED",
                            "flagged": res.flagged_entities,
                            "summary": res.summary_line(),
                        })
                txt = res.validated_text
            except Exception:
                pass  # on continue avec le texte non validé

        # 2. v16.5.67 L2+F4 — Vocabulaire Lucidité (post-processor filet de sécurité)
        # Même si les prompts bannissent VALIDÉ/DÉCIDÉ/CONFIRMÉ, certains LLM les
        # utilisent encore. On remplace systématiquement ici.
        # v62.13.9.4.50 — doctrine « tout livrer, tout signaler en place » : le vocabulaire n'est plus RÉÉCRIT dans
        # les sorties (contre-recette du 30/09, C02 : « action déjà décidée » du brief devenait « à arbitrer »). La
        # fonction de réécriture reste disponible et testée ; les statuts non établis par le brief sont signalés en
        # place par le mainteneur (patches.lucidity_wording.lucidity_flag_lines).
        _lucidity_flag_in_place50 = True
        if _apply_lucidity_wording is not None and _lucidity_enabled() and not _lucidity_flag_in_place50:
            try:
                txt_lucid, lucid_log = _apply_lucidity_wording(txt, role=role)
                if lucid_log.total_count > 0:
                    if logger:
                        log_event(
                            logger, "info", "codir_engine",
                            "lucidity_wording_replaced",
                            role=role,
                            count=lucid_log.total_count,
                            by_rule=lucid_log.by_rule,
                        )
                    if diag_list is not None:
                        diag_list.append({
                            "role":     f"{role}_lucidity_wording",
                            "provider": "internal",
                            "model":    "lucidity_wording_v1",
                            "status":   "REPLACED",
                            "replacements_count": lucid_log.total_count,
                            "by_rule":  lucid_log.by_rule,
                            "samples":  lucid_log.samples[:3],
                        })
                txt = txt_lucid
            except Exception:
                pass

        # 2.5 M.5.8 (FIX3) — Garde de citations légales : annote les références
        # d'articles non sourcées officiellement (« à valider »). Ne supprime rien.
        try:
            from patches.legal_citation_guard import neutralize_unsourced_legal_citations as _legal_guard
            txt_legal, _n_legal = _legal_guard(txt, lang=lang)
            if _n_legal > 0:
                txt = txt_legal
                if diag_list is not None:
                    diag_list.append({
                        "role":     f"{role}_legal_citation_guard",
                        "provider": "internal",
                        "model":    "legal_citation_guard_v1",
                        "status":   "ANNOTATED",
                        "replacements_count": _n_legal,
                    })
        except Exception:
            pass

        # 2.6 M.5.9 (FIX D) — Annotation des affirmations juridiques procédurales
        # trop assertives (formulaire M2 / annonce légale / provisionner NNN k€),
        # même sans numéro d'article. Renvoie vers guichet + CAPEOS/THAOS.
        try:
            from patches.legal_citation_guard import annotate_assertive_legal_statements as _legal_assert
            txt_assert, _n_assert = _legal_assert(txt, lang=lang)
            if _n_assert > 0:
                txt = txt_assert
                if diag_list is not None:
                    diag_list.append({
                        "role":     f"{role}_legal_assertiveness_guard",
                        "provider": "internal",
                        "model":    "legal_assertiveness_guard_v1",
                        "status":   "ANNOTATED",
                        "replacements_count": _n_assert,
                    })
        except Exception:
            pass

        # 2.7 v62.13.9.2 — Legal Claim Gate : une tranche d'effectif ne peut
        # devenir un seuil juridique, un coût ou une recommandation RH sans
        # qualification par la DRH / le conseil social.
        try:
            from patches.legal_citation_guard import (
                neutralize_unsupported_social_threshold_claims as _social_threshold_guard,
            )
            txt_social, _social_findings = _social_threshold_guard(
                txt, lang=lang, profile=_company_profile)   # v62.13.9.4.16 — profil réel, jamais une constante
            if _social_findings:
                txt = txt_social
                if diag_list is not None:
                    diag_list.append({
                        "role": f"{role}_social_threshold_legal_gate",
                        "provider": "internal",
                        "model": "social_threshold_legal_gate_v62139",
                        "status": "REQUALIFIED",
                        "replacements_count": len(_social_findings),
                        "findings": _social_findings[:10],
                    })
        except Exception:
            pass

        # 3. v17.1.0-B2.3-F.4.2 — Hygiène de sortie (fail-open) : retrait des
        # artefacts retail prototypés, de la contamination « social standalone »
        # marketing sur dossier M&A, et requalification des statuts « effectif
        # <date future> » en « prévu ». Constaté sur les reruns réels F.4.1.
        try:
            from patches.output_hygiene import apply_output_hygiene as _hygiene
            from datetime import date as _date
            try:
                _g = _genre.genre
            except Exception:
                _g = ""
            # B.1.3.56 Gate 11 — l'hygiène temporelle suit la même
            # autorité que les agents, B2.3, l'historique et les renderers :
            # date d'analyse simulée si elle existe, sinon date réelle du run.
            # Ne jamais requalifier un statut « effectif <date> » depuis
            # l'horloge de la machine lorsqu'un scénario rétrospectif est actif.
            # Gate 13 — INVALID/ERROR : AUCUNE autorité → l'hygiène ne
            # requalifie RIEN (today=None → fail-closed) ; jamais l'horloge.
            # NB closure : lectures LEXICALES directes (capture de freevars)
            # — les tests via locals() n'y voient pas l'englobante.
            try:
                _st13 = _scenario_status
            except NameError:
                _st13 = "NOT_REQUESTED"
            if _st13 in ("INVALID", "ERROR"):
                _hygiene_as_of = None
            else:
                try:
                    _hygiene_as_of = _run_now.date()
                except NameError:
                    _hygiene_as_of = None
                if _analysis_as_of:
                    try:
                        _hygiene_as_of = _date.fromisoformat(_analysis_as_of)
                    except Exception:
                        _hygiene_as_of = None
            txt = _hygiene(txt, role=role, genre=_g, today=_hygiene_as_of)
        except Exception:
            pass

        return txt

    def _is_active(role: str) -> tuple[bool, str, str]:
        """Retourne (active, note_si_skip, style_hint). Défaut : actif, vide, vide.

        Since v16.5.67.10 — P1bis skip_context passé pour que role_activation
        puisse détecter des signaux d'activité physique dans les pièces
        jointes (ex : holding + filiale distribution avec stocks).
        """
        if role_activation is None or _company_profile is None:
            return (True, "", "")
        # B.1.3 (run dossier anglophone coté, point 7) — le brief entre au contexte de skip :
        # un « services » retail/luxe avec inventaire matériel ne doit pas
        # sauter la Supply Chain mais passer en mode LIGHT.
        _skip_ctx = {"attachments_text": attachments_block or "",
                     "brief_text": brief or ""}
        try:
            act = role_activation(_company_profile, role, skip_context=_skip_ctx)
        except TypeError:
            # Rétro-compat : signature sans skip_context
            act = role_activation(_company_profile, role)
        return (act.active, act.note, act.style_hint)
    # ─────────────────────────────────────────────────────────────────────────

    if logger:
        log_event(logger, "info", "codir_engine", "session_started")

    # ─── v16.5.76 Phase 3 — Web search connector (item 2 du backlog) ────────
    # Scan concurrentiel via Perplexity Sonar AVANT les agents.
    # Résout INC-02 (concurrents pure-players absents) + LOW_SOURCED_FACT_RATIO.
    #
    # Conditions d'activation (toutes nécessaires) :
    #   1. PERPLEXITY_API_KEY présente dans l'environnement
    #   2. Nom de société identifié (via _company_profile ou brief)
    #   3. settings.web_search_enabled n'est pas False (défaut True)
    #
    # Si désactivé ou indisponible : fallback gracieux silencieux, le run
    # continue avec un _web_search_result = None et _web_ctx vide.
    _web_search_result = None
    _web_search_summary = ""
    _web_facts_ledger = None  # v17.1.0-B2.3-F.2 — ledger marché structuré
    _web_search_multi_source = None  # v16.5.76 Phase 6b — résultat cascade complet
    try:
        # v16.5.76 Phase 6b (post-audit ChatGPT R6/R7) — branchement multi-source.
        # AVANT Phase 6b : codir_engine appelait directement run_competitor_scan
        #                  (Perplexity unique, single point of failure).
        # APRÈS Phase 6b : on utilise run_competitor_scan_multi_source qui cascade
        #                  Perplexity (primary) → Tavily (fallback) → Brave (fallback).
        # Fail-open total : si web_search_providers absent OU tous providers échouent,
        # _web_search_result reste None (comportement v76 Phase 3 préservé).
        from patches.web_search import is_web_search_available
        try:
            from patches.web_search_providers import (
                run_competitor_scan_multi_source as _run_multi,
                get_default_providers as _get_providers,
            )
            _HAS_MULTI_SOURCE = True
        except ImportError:
            # Module Phase 6 absent (env test léger) → fallback Phase 3 single-source
            from patches.web_search import run_competitor_scan as _run_single
            _HAS_MULTI_SOURCE = False

        # Détermine le nom de société à scanner
        _ws_company_name = ""
        if _company_profile is not None:
            _ws_company_name = (getattr(_company_profile, "company_name_official", "") or "").strip()
        if not _ws_company_name and isinstance(brief, str):
            # Fallback : extraire un nom plausible du brief (recherche simple)
            import re as _re_ws
            _m = _re_ws.search(r"(?:soci[ée]t[ée]\s+analys[ée]e?\s*:?\s*|company\s*:?\s*)([^\n,]+)", brief, _re_ws.IGNORECASE)
            if _m:
                _ws_company_name = _m.group(1).strip()[:80]

        # M6-S.2 — verrou entité : les agents doivent analyser l'entité d'ANALYSE
        # (ex. dossier anglophone coté Group plc), pas la filiale registre (ex. dossier anglophone coté LIMITED).
        try:
            from patches.entity_scope import analysis_display_name as _adn
            _ws_company_name = _adn(_entity_scope_obj, _ws_company_name)
        except Exception:
            pass

        # Hint sectoriel via sector_detector v16.5.76 Phase 2
        _ws_sector_hint = ""
        if _ws_company_name:
            try:
                from patches.sector_detector import detect_sector_from_name
                _sh = detect_sector_from_name(_ws_company_name)
                if _sh:
                    _ws_sector_hint = f"{_sh.sector} (confidence={_sh.confidence})"
            except ImportError:
                pass

        # Toggle settings (défaut activé si au moins un provider dispo)
        _ws_enabled = getattr(settings, "web_search_enabled", True) if settings else True

        # F.6.7.1 (P0) — MODE PIÈCES JOINTES : couper AUSSI la veille web
        # concurrentielle (chemin distinct du market research). Sans ce gate, un
        # nom de société détecté + une clé Perplexity suffisaient à lancer un
        # web_search malgré « pièces jointes exclusivement ». Diag explicite.
        try:
            from patches.mission_governance import web_search_gate as _wsg
            _ws_ok, _ws_skip_diag = _wsg(external_sources_skip)
        except Exception:
            _ws_ok, _ws_skip_diag = (not external_sources_skip), None
        if not _ws_ok:
            _ws_enabled = False
            if diag_list is not None and _ws_skip_diag is not None:
                diag_list.append(_ws_skip_diag)

        # Pour activer le scan, il faut au moins UN provider disponible.
        # En mode multi-source : check des 3 providers ; sinon : check Perplexity uniquement.
        if _HAS_MULTI_SOURCE:
            _providers = _get_providers()
            _any_available = any(p.is_available() for p in _providers)
        else:
            _providers = None
            _any_available = is_web_search_available()

        if _ws_enabled and _ws_company_name and _any_available:
            if cb:
                if _HAS_MULTI_SOURCE:
                    _available_names = [p.name for p in _providers if p.is_available()]
                    _cb_label = (
                        f"{'Veille web concurrentielle' if lang == 'fr' else 'Web competitive watch'} "
                        f"— cascade {' → '.join(_available_names)}…"
                    )
                else:
                    _cb_label = f"{'Veille web concurrentielle' if lang == 'fr' else 'Web competitive watch'} — Perplexity Sonar…"
                cb("web_search", _cb_label)

            if _HAS_MULTI_SOURCE:
                # Mode Phase 6b : cascade multi-source
                _web_search_multi_source = _run_multi(
                    company_name=_ws_company_name,
                    sector_hint=_ws_sector_hint,
                    lang=lang,
                    providers=_providers,
                )
                _web_search_result = _web_search_multi_source.result
            else:
                # Fallback Phase 3 single-source
                _web_search_result = _run_single(
                    company_name=_ws_company_name,
                    sector_hint=_ws_sector_hint,
                    lang=lang,
                )

            if _web_search_result is not None:
                # Trace diag enrichie en mode multi-source
                if diag_list is not None:
                    _diag_entry = {
                        "role": "web_search",
                        "provider": _web_search_result.provider,
                        "model": _web_search_result.model,
                        "status": "ERROR" if _web_search_result.error else "OK",
                        "attempt": 1,
                        "duration_s": _web_search_result.duration_s,
                        "tokens": _web_search_result.tokens_used,
                        "error": _web_search_result.error_message if _web_search_result.error else (
                            f"competitors={len(_web_search_result.competitors)} | sources={len(_web_search_result.sources)} | market_metrics={list(_web_search_result.market_metrics.keys())}"
                        ),
                    }
                    # v16.5.76 Phase 6b — Enrichissement traçabilité multi-source
                    if _web_search_multi_source is not None:
                        _diag_entry["providers_tried"] = _web_search_multi_source.providers_tried
                        _diag_entry["providers_used"] = _web_search_multi_source.provider_used
                        _diag_entry["providers_failed_count"] = len(_web_search_multi_source.providers_failed)
                        _diag_entry["convergence_score"] = _web_search_multi_source.convergence_score
                    diag_list.append(_diag_entry)
                if logger:
                    log_event(
                        logger,
                        "warning" if _web_search_result.error else "info",
                        "codir_engine",
                        "web_search_completed",
                        error=_web_search_result.error,
                        competitors_count=len(_web_search_result.competitors),
                        sources_count=len(_web_search_result.sources),
                        provider_used=_web_search_result.provider,
                        multi_source=_HAS_MULTI_SOURCE,
                    )
                # Si OK, construit le bloc summary à injecter
                if not _web_search_result.error and _web_search_result.summary:
                    # v16.5.76 Phase 6c (audit ChatGPT R8 chantier 2.3) — Hardening
                    # sécurité : sanitization du contenu externe avant injection
                    # dans les prompts agents. Le contenu Perplexity/Tavily/Brave
                    # peut contenir des patterns de prompt injection indirecte
                    # ("ignore previous instructions", "you are chatgpt", etc.).
                    # Fail-open : si la sanitization échoue, on injecte le contenu
                    # brut (comportement pré-Phase 6c préservé).
                    try:
                        from patches.external_context_sanitizer import sanitize_external_context
                        _sanitized, _sanitize_diag = sanitize_external_context(
                            _web_search_result.summary,
                            lang=lang,
                            wrap=True,
                        )
                        _web_search_summary = _sanitized
                        # v62.13.9.4.15.1 — autorité du registre sur la veille :
                        # sous statut ACTIVE explicite, les phrases affirmant une
                        # extinction juridique ne rejoignent pas le contexte des
                        # agents ; le retrait est tracé dans le diagnostic.
                        try:
                            from patches.external_context_sanitizer import (
                                quarantine_registry_contradictions as _qrc62151)
                            _rs62151 = str(getattr(_company_profile, "registry_status", "") or "")
                            _web_search_summary, _qrc_diag62151 = _qrc62151(
                                _web_search_summary, _rs62151, lang=lang)
                            if diag_list is not None and _qrc_diag62151.get("sentences_removed"):
                                diag_list.append({
                                    "role": "registry_authority_on_web_context",
                                    "provider": "internal", "model": "n/a",
                                    "status": "CONTRADICTIONS_REMOVED",
                                    "registry_status": _qrc_diag62151["registry_status"],
                                    "sentences_removed": _qrc_diag62151["sentences_removed"],
                                    "samples": _qrc_diag62151["samples"],
                                    "error": (f"{_qrc_diag62151['sentences_removed']} phrase(s) de "
                                              "radiation/cessation retirée(s) de la veille web — "
                                              "contredites par le registre (ACTIVE)"),
                                })
                            if logger and _qrc_diag62151.get("sentences_removed"):
                                log_event(logger, "warning", "codir_engine",
                                          "registry_authority_on_web_context",
                                          sentences_removed=_qrc_diag62151["sentences_removed"])
                        except Exception:
                            pass
                        # Tracer dans diag si des patterns ont été détectés (audit)
                        if diag_list is not None and _sanitize_diag.get("patterns_count", 0) > 0:
                            diag_list.append({
                                "role": "external_context_sanitizer",
                                "provider": "n/a",
                                "model": "n/a",
                                "status": "PATTERNS_REDACTED",
                                "patterns_count": _sanitize_diag["patterns_count"],
                                "patterns_found": _sanitize_diag["patterns_found"],
                                "was_truncated": _sanitize_diag["was_truncated"],
                                "original_length": _sanitize_diag["original_length"],
                                "sanitized_length": _sanitize_diag["sanitized_length"],
                                "error": (
                                    f"Détecté {_sanitize_diag['patterns_count']} pattern(s) "
                                    f"d'injection dans le contenu web — redacted avant injection prompt"
                                ),
                            })
                        if logger and _sanitize_diag.get("patterns_count", 0) > 0:
                            log_event(logger, "warning", "codir_engine",
                                      "external_context_sanitized",
                                      patterns_count=_sanitize_diag["patterns_count"],
                                      patterns_found=_sanitize_diag["patterns_found"])
                    except ImportError:
                        # Module Phase 6c absent → injection sans sanitization (legacy)
                        _web_search_summary = _web_search_result.summary
                    except Exception as _e_san:
                        # Fail-open : tout échec sanitization → contenu brut
                        if logger:
                            log_event(logger, "warning", "codir_engine",
                                      "sanitizer_unexpected_error", error=str(_e_san))
                        _web_search_summary = _web_search_result.summary
            elif _web_search_multi_source is not None:
                # Tous les providers ont échoué — tracer dans diag pour audit
                if diag_list is not None:
                    diag_list.append({
                        "role": "web_search",
                        "provider": "multi_source_cascade",
                        "model": "n/a",
                        "status": "ALL_FAILED",
                        "providers_tried": _web_search_multi_source.providers_tried,
                        "providers_failed_count": len(_web_search_multi_source.providers_failed),
                        "error": "Tous les providers de web search ont échoué (fail-open)",
                    })
                if logger:
                    log_event(logger, "warning", "codir_engine",
                              "web_search_all_providers_failed",
                              providers_tried=_web_search_multi_source.providers_tried)
    except ImportError:
        # patches.web_search absent (env test léger) → silencieux
        pass
    except Exception as _e_ws:
        # Tout échec inattendu ne doit pas casser le run
        if logger:
            log_event(logger, "warning", "codir_engine", "web_search_unexpected_error", error=str(_e_ws))

    # ─── v17.1.0-B2.3-F — Recherche marché pilotée par le SUJET ───────────────
    # Pour un point d'agenda « marché », on interroge le web sur les QUESTIONS du
    # sujet (taille, croissance, prix, acteurs, tendances) — pas seulement sur la
    # société (qui, pour une PME/SASU sans empreinte web, ne renvoie rien d'utile).
    # Fail-open total ; le résultat enrichit le contexte web injecté aux agents.
    if getattr(_genre, "wants_market_research", False) and not _attachments_only:
        try:
            from patches.web_research import derive_research_questions as _drq
            from patches.web_search import (run_market_research as _rmr,
                                            is_web_search_available as _wsa,
                                            build_market_fallbacks as _bmf)
            _mr_questions = _drq(brief, _genre)
            if _mr_questions and _genre.research_topic and _wsa():
                if cb:
                    cb("web_search",
                       (f"Recherche marché web — sujet : {_genre.research_topic}…"
                        if lang == "fr" else
                        f"Web market research — topic: {_genre.research_topic}…"))
                try:
                    _mr_fallbacks = _bmf(_genre.research_topic, lang=lang)
                except Exception:
                    _mr_fallbacks = []
                _mr = _rmr(_genre.research_topic, _mr_questions, lang=lang,
                           fallback_call_fns=_mr_fallbacks)
                if _mr and not _mr.get("error") and _mr.get("output"):
                    _hdr = ((f"## Recherche marché (web) — sujet : {_genre.research_topic}\n\n")
                            if lang == "fr" else
                            (f"## Market research (web) — topic: {_genre.research_topic}\n\n"))
                    # B2.3-F.2 — WebFactsLedger structuré : métrique/valeur/année/
                    # source/fiabilité/board-safe, annexé sous la synthèse marché.
                    _ledger_block = ""
                    try:
                        from patches.web_research import (
                            build_web_facts_ledger as _bwl,
                            web_facts_ledger_to_markdown as _wlmd)
                        _wf_rows = _bwl(_mr["output"], sources=_mr.get("sources"))
                        if _wf_rows:
                            _web_facts_ledger = [r.as_row() for r in _wf_rows]
                            _ltitle = ("\n\n**Ledger de faits marché gouverné :**\n"
                                       if lang == "fr" else
                                       "\n\n**Governed market-facts ledger:**\n")
                            _rules = (("\n\nRÈGLES IMPÉRATIVES POUR LES AGENTS :\n"
                                       "- ne jamais agréger des années ou périmètres différents en une fourchette ;\n"
                                       "- une prévision reste une prévision, jamais un fait observé ;\n"
                                       "- la croissance d'un acteur ne mesure pas la croissance du marché ;\n"
                                       "- seules les lignes decision_safe peuvent soutenir une affirmation ferme.\n")
                                      if lang == "fr" else
                                      ("\n\nMANDATORY RULES FOR AGENTS:\n"
                                       "- never merge different years or scopes into one range;\n"
                                       "- a forecast remains a forecast, never an observed fact;\n"
                                       "- one provider's growth is not market growth;\n"
                                       "- only decision_safe rows may support a firm assertion.\n"))
                            _ledger_block = _ltitle + _wlmd(_wf_rows, lang) + _rules
                    except Exception:
                        _ledger_block = ""
                    _block = f"{_hdr}{_mr['output']}{_ledger_block}"
                    _web_search_summary = (
                        f"{_web_search_summary}\n\n{_block}".strip()
                        if _web_search_summary else _block)
                    if diag_list is not None:
                        diag_list.append({
                            "role": "market_research",
                            "provider": _mr.get("provider", "perplexity"),
                            "model": _mr.get("model", ""), "status": "OK",
                            "research_topic": _genre.research_topic,
                            "questions_count": len(_mr_questions),
                            "sources_count": len(_mr.get("sources", [])),
                            "web_facts_count": len(_web_facts_ledger),
                            "duration_s": _mr.get("duration_s", 0),
                        })
                elif _mr and _mr.get("error") and diag_list is not None:
                    diag_list.append({
                        "role": "market_research",
                        "provider": _mr.get("provider", "perplexity"),
                        "model": "", "status": "ERROR",
                        "research_topic": _genre.research_topic,
                        "error": str(_mr.get("error_message", ""))[:200],
                    })
        except ImportError:
            pass
        except Exception as _e_mr:
            if logger:
                log_event(logger, "warning", "codir_engine",
                          "market_research_unexpected_error", error=str(_e_mr))

    def _web_ctx(role: str) -> str:
        """v16.5.76 Phase 3 — Contexte web (Perplexity Sonar) injecté dans les agents.

        Disponible pour les rôles bénéficiant d'une veille concurrentielle :
        stratégie, marketing, commercial, dg, synthese_decisions, brief_codir.
        Pas pertinent pour : finance pure (sauf si la cible cite ses concurrents),
        supply_chain (focus opérationnel interne), RH.

        Si _web_search_summary est vide (pas de scan ou erreur) → retourne "".
        """
        if not _web_search_summary:
            return ""
        _ROLES_BENEFIT_WEB = {
            "strategie", "marketing", "commercial", "dg",
            "brief_codir", "synthese_decisions",
        }
        if role not in _ROLES_BENEFIT_WEB:
            return ""
        if lang == "en":
            return f"\n\n---\n## Web Watch (Perplexity Sonar) — Competitors & market\n\n{_web_search_summary}\n---\n"
        return f"\n\n---\n## Veille web (Perplexity Sonar) — Concurrents & marché\n\n{_web_search_summary}\n---\n"
    # ─── Fin v16.5.76 Phase 3 — Web search connector ────────────────────────

    # 1) STRATEGIE — Claude par défaut, y compris avec pièces jointes
    strategie_order = ["anthropic", "google", "openai", "mistral"]

    if cb:
        cb("strategie", f"{_lbl('strategie', lang)} — {'préparation' if lang == 'fr' else 'preparing'}…")

    if lang == "en":
        strategie_prompt = (
            "Role: Chief Strategy Officer.\n"
            "Required structure: a « ## SWOT » section with « ### Strengths », « ### Weaknesses », "
            "« ### Opportunities », « ### Threats » (3-5 factual bullets each, no invented figure), then "
            "« ## Strategic options » (Option 1, 2, 3 with a title) and « ## Priority decisions » "
            "(one bullet per decision: action | owner | deadline).\n"
            "Objective: propose a clear, prioritized and actionable strategy.\n"
            "Constraint: concise, data-driven style.\n"
            + (_profile_hint + "\n" if _profile_hint else "")
            # v16.5.73 — Couche 1 socle factuel partagé
            + _facts_ctx("strategie")
            # v16.5.76 Phase 3 — Veille web concurrentielle
            + _web_ctx("strategie")
        )
        if attachments_block.strip():
            strategie_prompt += (
                "Attachments (extracted text) — use as factual context. "
                "Do not invent: if information is not in the attachments, say so.\n"
                "---\n" + attachments_block.strip() + "\n---\n"
            )
        strategie_prompt += "Brief provided:\n---\n" + brief
        strategie_system = "You are an experienced Chief Strategy Officer. You produce a clear, quantified and prioritized plan."
    else:
        strategie_prompt = (
            "Rôle: Directeur de la stratégie.\n"
            "Objectif: proposer une stratégie claire, priorisée et exécutable.\n"
            "Contrainte: style sobre, concis, actionnable.\n"
            # v62.13.9.4.24 — la trame PPTX porte un SWOT : l'agent l'écrit
            # explicitement, depuis les faits du brief et du registre.
            "Structure imposée : inclure une section « ## SWOT » avec quatre sous-titres "
            "« ### Forces », « ### Faiblesses », « ### Opportunités », « ### Menaces », "
            "3 à 5 puces chacune, factuelles, tirées du brief, des pièces et du registre — "
            "sans chiffre inventé. Puis « ## Options stratégiques » (Option 1, 2, 3 avec intitulé) "
            "et « ## Décisions prioritaires » (une puce par décision : action | porteur | échéance).\n"
            + (_profile_hint + "\n" if _profile_hint else "")
            # v16.5.73 — Couche 1 socle factuel partagé
            + _facts_ctx("strategie")
            # v16.5.76 Phase 3 — Veille web concurrentielle
            + _web_ctx("strategie")
        )
        if attachments_block.strip():
            strategie_prompt += (
                "Pièces jointes (texte extrait) — à utiliser comme contexte factuel. "
                "Ne pas inventer : si une info n'est pas dans les pièces jointes, le dire.\n"
                "---\n" + attachments_block.strip() + "\n---\n"
            )
        strategie_prompt += "Brief fourni:\n---\n" + brief
        strategie_system = "Tu es un directeur de la stratégie expérimenté. Tu produis un plan clair, chiffré et priorisé."

    # v16.5.76 Phase 4 — Injection schema JSON (item 3)
    # v17.1-B2.3-B — discipline de forme (orientation cible + cotation).
    _b23b_s = _b23b_prompt_rules(lang, _genre.genre)
    strategie_prompt += _b23b_s["orientation"] + _b23b_s["cotation"]
    strategie_prompt = _inject_json_schema_in_agent_prompt(strategie_prompt, lang)

    strategie_res = _call_with_fallback(
        role="strategie",
        provider_order=strategie_order,
        prompt=strategie_prompt,
        system=_lang_wrap(strategie_system, lang),
        temperature=temperature,
        max_tokens=max(max_tokens, STRATEGIE_MIN_OUTPUT_TOKENS),  # v16.5.74
        settings=settings,
        diag_list=diag_list,
        cb=cb,
        logger=logger,
    )
    strategie_txt = _validate(_as_output(strategie_res), "strategie")
    # v16.5.76 Phase 4 — Parser le bloc JSON et nettoyer le texte
    _strategie_agent_output, strategie_txt = _parse_agent_json_and_clean(
        strategie_txt, role="strategie", diag_list=diag_list, logger=logger,
    )
    # B-03 — retry JSON si MISSING (sinon claims=0 → score dégradé à tort)
    _why62415 = _a1_retry_needed(_strategie_agent_output)
    if _why62415:
        _r62415 = _retry_agent_json(strategie_txt, "strategie", settings,
                                    logger=logger, cb=cb, diag_list=diag_list,
                                    reason=_why62415)
        if _r62415 is not None:
            _strategie_agent_output = _r62415

    # 2) BRIEF CoDIR
    if cb:
        cb("brief_codir", f"{_lbl('brief_codir', lang)} — {'synthèse' if lang == 'fr' else 'synthesis'}…")

    if lang == "en":
        brief_codir_prompt = (
            "Produce a structured BOARD BRIEF (max 15 bullets) from the elements below.\n"
            "Include: Context / Key Facts / Assumptions / Risks / Open Questions.\n"
            "Concise, factual response.\n"
            # v16.5.73 — Couche 1 socle factuel + Pappers summary (manquait avant)
            + _facts_ctx("brief_codir")
            + _pap_ctx("brief_codir")
            + f"---\nSTRATEGY:\n{strategie_txt}\n---\nBRIEF:\n{brief}\n"
        )
        brief_codir_system = "You are a Chief Strategy Officer. You synthesize into a working brief for a board of directors."
    else:
        brief_codir_prompt = (
            "Tu produis un BRIEF CoDIR structuré (max 15 bullets) à partir des éléments.\n"
            "Inclure: Contexte / Faits clés / Hypothèses / Risques / Questions ouvertes.\n"
            "Réponse concise, factuelle.\n"
            # v16.5.73 — Couche 1 socle factuel + Pappers summary (manquait avant)
            + _facts_ctx("brief_codir")
            + _pap_ctx("brief_codir")
            + f"---\nSTRATÉGIE:\n{strategie_txt}\n---\nBRIEF:\n{brief}\n"
        )
        brief_codir_system = "Tu es un directeur de la stratégie. Tu synthétises en brief de travail pour un comité de direction."

    # v16.5.76 Phase 4 — Injection schema JSON (item 3)
    # Note : Brief CoDIR a max_tokens=900 (rôle de synthèse courte). On injecte
    # quand même pour collecter ses claims si la place le permet ; sinon
    # parse_status=MISSING est attendu et c'est OK (rôle non-critique).
    brief_codir_prompt = _inject_json_schema_in_agent_prompt(brief_codir_prompt, lang)

    brief_codir_res = _call_with_fallback(
        role="brief_codir",
        provider_order=strategie_order,
        prompt=brief_codir_prompt,
        system=_lang_wrap(brief_codir_system, lang),
        temperature=0.2,
        max_tokens=max(10000, max_tokens),   # v62.13.9.4.40 — 900 coupait le brief en pleine phrase (dossier réel du 21/09/2026)
        settings=settings,
        diag_list=diag_list,
        cb=cb,
        logger=logger,
    )
    brief_codir_txt = _validate(_as_output(brief_codir_res), "brief_codir")
    # v16.5.76 Phase 4 — Parser le bloc JSON et nettoyer
    _brief_codir_agent_output, brief_codir_txt = _parse_agent_json_and_clean(
        brief_codir_txt, role="brief_codir", diag_list=diag_list, logger=logger,
    )
    # B-03 — retry JSON si MISSING
    _why62415 = _a1_retry_needed(_brief_codir_agent_output)
    if _why62415:
        _r62415 = _retry_agent_json(brief_codir_txt, "brief_codir", settings,
                                    logger=logger, cb=cb, diag_list=diag_list,
                                    reason=_why62415)
        if _r62415 is not None:
            _brief_codir_agent_output = _r62415

    # 3) MARKETING — OpenAI first
    if cb:
        cb("marketing", f"{_lbl('marketing', lang)} — {'préparation' if lang == 'fr' else 'preparing'}…")

    # v16.5.60 — adaptation selon profil
    _mk_active, _mk_note, _mk_hint = _is_active("marketing")
    # v16.5.76 Phase 4 — Init pour éviter NameError dans la collecte _all_metrics
    # (cas SOLO services : skip → _marketing_agent_output reste None)
    _marketing_agent_output = None
    if not _mk_active:
        marketing_txt = (
            f"[Rôle Marketing non applicable — {_mk_note}]"
            if lang == "fr" else
            f"[Marketing role not applicable — {_mk_note}]"
        )
        marketing_res = {
            "output": marketing_txt, "provider": "skipped", "model": "company_profile_v1",
            "error": False, "attempt": 0, "duration_s": 0.0, "tokens": {},
            "raw": {"skipped_reason": _mk_note},
        }
        if diag_list is not None:
            diag_list.append({
                "role": "marketing", "provider": "skipped",
                "model": "company_profile_v1", "status": "SKIPPED",
                "reason": _mk_note,
            })
    else:
        if lang == "en":
            marketing_prompt = (
                "Role: Marketing Director.\n"
                "Objective: marketing plan (targets, messages, channels, budget, timeline, KPIs) in max 6 points.\n"
                "Take the Board Brief into account.\n"
                + (_profile_hint + "\n" if _profile_hint else "")
                + (_mk_hint + "\n" if _mk_hint else "")
                + f"{_facts_ctx('marketing')}{_pap_ctx('marketing')}{_external_ctx('marketing')}{_web_ctx('marketing')}---\nBoard Brief:\n{brief_codir_txt}\n---\nInitial brief:\n{brief}"
            )
            marketing_system = "You are a data-driven Marketing Director. You produce a concrete and measurable plan."
        else:
            marketing_prompt = (
                "Rôle: Direction Marketing.\n"
                "Objectif: plan marketing (cibles, messages, canaux, budget, calendrier, KPI) en 6 points max.\n"
                "Prends en compte le Brief CoDIR.\n"
                + (_profile_hint + "\n" if _profile_hint else "")
                + (_mk_hint + "\n" if _mk_hint else "")
                + f"{_facts_ctx('marketing')}{_pap_ctx('marketing')}{_external_ctx('marketing')}{_web_ctx('marketing')}---\nBrief CoDIR:\n{brief_codir_txt}\n---\nBrief initial:\n{brief}"
            )
            marketing_system = "Tu es une directrice marketing data-driven. Tu produis un plan concret et mesurable."

        # v16.5.76 Phase 4 — Injection schema JSON (item 3)
        marketing_prompt = _inject_json_schema_in_agent_prompt(marketing_prompt, lang)

        marketing_res = _call_with_fallback(
            role="marketing",
            provider_order=["openai", "anthropic", "google", "mistral"],
            prompt=marketing_prompt,
            system=_lang_wrap(marketing_system, lang),
            temperature=temperature,
            max_tokens=max(max_tokens, MARKETING_MIN_OUTPUT_TOKENS),  # v16.5.74
            settings=settings,
            diag_list=diag_list,
            cb=cb,
            logger=logger,
        )
        marketing_txt = _validate(_as_output(marketing_res), "marketing")
        # v16.5.76 Phase 4 — Parser le bloc JSON et nettoyer
        _marketing_agent_output, marketing_txt = _parse_agent_json_and_clean(
            marketing_txt, role="marketing", diag_list=diag_list, logger=logger,
        )
        # v62.13.9.4.12.4 — retry généralisé : le rattrapage existait pour
        # Stratégie, Brief et Finance seulement. Il a fait ses preuves sur
        # Finance au run réel ; il coûte un appel court, et uniquement en
        # cas d'échec.
        _why62415 = _a1_retry_needed(_marketing_agent_output)
        if _why62415:
            _r62415 = _retry_agent_json(marketing_txt, "marketing", settings,
                                        logger=logger, cb=cb, diag_list=diag_list,
                                        reason=_why62415)
            if _r62415 is not None:
                _marketing_agent_output = _r62415

    # 4) SUPPLY CHAIN — seed prioritaire (brief seul, sans contamination Finance)
    # v16.5.60 — skip amont si company_profile indique aucune pertinence
    # (ex. SASU unipersonnelle de services). Le pre-filter LLM reste en place
    # comme second garde-fou pour les cas ambigus.
    _sc_active, _sc_note, _ = _is_active("supply_chain")
    # B-04 — Override par SIGNAUX DOCUMENTAIRES : si le corpus (brief + faits +
    # contexte) contient des signaux industriels forts (MW, électrolyseurs, sites,
    # tube trailers, EPC…), Supply Chain s'exécute MALGRÉ un APE Pappers « services ».
    if not _sc_active:
        try:
            from patches.supply_chain_router import has_supply_chain_signals as _has_sc
            _sc_signal_text = " ".join([
                brief or "",
                _facts_table_md_for_agents if "_facts_table_md_for_agents" in dir() else "",
                _pap_full if "_pap_full" in dir() else "",
            ])
            _sc_override, _sc_signals = _has_sc(_sc_signal_text)
            if _sc_override:
                _sc_active = True
                _sc_note = (f"Override B-04/F.6.8 : signaux Supply Chain détectés "
                            f"({', '.join(_sc_signals[:5])}) — Supply Chain forcée "
                            f"malgré APE/profil « services ».")
                if logger:
                    log_event(logger, "info", "supply_chain_router",
                              "sc_forced_by_signals", signals=_sc_signals[:8])
        except Exception:
            pass
    if not _sc_active:
        sc_seed_bundle = {
            "output":     "",
            "triggered":  False,
            "source":     "skipped_by_profile",
            "warning":    _sc_note,
            "status":     "SKIPPED",
            "json":       None,
            "slide_flag": False,
        }
        sc_seed_txt = ""
        if diag_list is not None:
            diag_list.append({
                "role":     "supply_chain_seed",
                "provider": "skipped",
                "model":    "company_profile_v1",
                "status":   "SKIPPED",
                "reason":   _sc_note,
            })
        if logger:
            log_event(logger, "info", "codir_engine", "sc_skipped_by_profile", reason=_sc_note)
    else:
        # v16.5.73 — injecter le bloc de faits Couche 1 EN TÊTE du pappers_context
        # passé à Supply Chain. Solution pragmatique : pas de modification de la
        # signature run_supply_chain_seed (qui reçoit déjà un texte libre dans
        # pappers_context). Le bloc de faits + l'instruction d'usage sont placés
        # avant le contexte Pappers proprement dit.
        _sc_pappers_ctx = _facts_ctx("supply_chain") + _pap_ctx("supply_chain")
        sc_seed_bundle = run_supply_chain_seed(
            user_input=brief,
            temperature=temperature,
            max_tokens=max_tokens,
            cb=cb,
            diag_list=diag_list,
            settings=settings,
            logger=logger,
            pappers_context=_sc_pappers_ctx,
            company_profile=_company_profile,  # v16.5.76 Phase 2 — fast-paths
        )
        sc_seed_txt = sc_seed_bundle.get("output") or ""

    # 5) FINANCE — Gemini primary + 2x challenge Claude (challenge la SC si utile)
    if cb:
        cb("finance", f"{_lbl('finance', lang)} — {'Gemini (analyse primaire)' if lang == 'fr' else 'Gemini (primary analysis)'}…")

    # ─────────────────────────────────────────────────────────────────────────
    # Patch v16.5.70.3 P0-1 (audit ChatGPT round 7) — FIX CRASH _attachments_count
    # ─────────────────────────────────────────────────────────────────────────
    # Bug runtime bloquant détecté en v16.5.70.2 : `_attachments_count` était
    # utilisée ligne 3142 (règle prudence) mais initialisée seulement ligne 4002
    # (scoring final). En Python, l'assignation tardive dans la même fonction
    # rend la variable LOCALE dès le premier usage → UnboundLocalError au
    # runtime. Crash sur run_codir_session() même brief minimaliste.
    #
    # Mes 611 tests (Since v16.5.70.2) ne l'avaient pas attrapé car ils sont 100%
    # statiques (lecture pattern code, AST). Aucun test n'appelait vraiment
    # run_codir_session(). Apprentissage v16.5.70.3 : ajout de smoke tests
    # runtime systématiques (cf. test_v16_5_70_3_smoke_runtime.py).
    #
    # Correctif : initialiser _attachments_count UNE FOIS, en tête, avant tout
    # usage. Le bloc redondant ligne ~4002 a été supprimé pour éviter deux
    # sources de vérité.
    _attachments_count = 0
    if attachments_meta and isinstance(attachments_meta, dict):
        # v16.5.67.11 — Fix TypeError: object of type 'int' has no len()
        # attachments_meta["files"] est un INT (nombre de fichiers), pas une
        # liste. On utilise filenames (liste) exposée par build_attachments_block
        # depuis v67.10. Défensif : fallback sur int direct si filenames absent.
        _fn = attachments_meta.get("filenames")
        if isinstance(_fn, (list, tuple)):
            _attachments_count = len(_fn)
        else:
            _fallback = attachments_meta.get("files", 0)
            _attachments_count = _fallback if isinstance(_fallback, int) else 0

    # ─────────────────────────────────────────────────────────────────────────
    # Patch v16.5.70 Phase 5 — Règle métier "Source Quality < 40"
    # Patch v16.5.70.1 P0-2 — Refonte 1 (alignement scorer)
    # Patch v16.5.70.2 P0-2 — Refonte 2 (audit ChatGPT round 6) :
    # ─────────────────────────────────────────────────────────────────────────
    # Bug v16.5.70.1 : le cas le plus dangereux n'activait pas la règle :
    #   - Si attachments_count > 0 mais financial_statements NON détectés
    #     → score = 25 + 25 = 50 (au-dessus du seuil 40)
    #   - Or c'est PRÉCISÉMENT le cas dossier anglophone coté v16.5.69.1 : 18 PDFs uploadés
    #     mais Annual Reports tronqués 50p donc FS jamais lus → Finance
    #     produit un business plan spéculatif (attachments=True faussement
    #     rassurant).
    #
    # Solution v16.5.70.2 : logique en cascade explicite + seuil <= 40 (pas <)
    #
    # 1. Si FS détectés → score = 75 (analyse pro autorisée, pas de cascade)
    # 2. Si attachments uploadés MAIS FS non détectés → score = 35 (PRUDENCE)
    #    C'est le cas dangereux : utilisateur a fourni des docs qui se révèlent
    #    non extractibles. Mieux vaut diagnostic qualitatif que business plan
    #    spéculatif sur fausse assurance.
    # 3. Si Pappers seul → score = 35 (sous le seuil, prudence active)
    # 4. Si rien → score = 25 (défiance forte initiale)
    #
    # Bonus mineurs : +10 si ≥ 1 source externe (GLEIF/SEC/CH/OS) en plus.
    # Seuil <= 40 (pas <) pour que Pappers seul = 40 active la prudence.
    _fs_detected_in_any = bool(financial_statements_bundles) and any(
        getattr(b, "financial_statements_detected", False)
        for b in financial_statements_bundles
    )
    _has_attachments_but_no_fs = (_attachments_count > 0) and not _fs_detected_in_any
    _has_pappers_full = bool(_pap_full) and not pappers_skip
    _has_external_sources = (not external_sources_skip) and any([
        bool(_gleif_blocks.get("full")) if _gleif_blocks else False,
        bool(_sec_blocks.get("full")) if _sec_blocks else False,
        bool(_ch_blocks.get("full")) if _ch_blocks else False,
        bool(_os_blocks.get("full")) if _os_blocks else False,
    ])

    # ─────────────────────────────────────────────────────────────────────────
    # Patch v16.5.71 — Anti-régression dossier réseau de soins (audit ChatGPT round 8)
    # ─────────────────────────────────────────────────────────────────────────
    # Bug v16.5.70.3 : la cascade Source Quality ne considérait QUE les
    # bundles FS PDF. Si l'utilisateur upload des Excel/Word/CSV financiers
    # auditées (cas dossier réseau de soins 5 Excel comptables), `_fs_detected_in_any=False`
    # → branche "PJ uploadées mais FS non détectés" → score 35 → règle prudence
    # → Finance bridé en diagnostic qualitatif → régression Grade B/70 → D/35.
    #
    # Solution v16.5.71 : nouveau détecteur multi-format `detect_financial_signal`
    # qui scanne attachments_block (qui agrège tous les uploads tous formats
    # confondus après extract_text_from_upload). Si signal financier solide
    # détecté (score >= 60), considéré comme "FS exploitable" même hors PDF.
    #
    # Patch v16.5.73 — La détection effective a été DÉPLACÉE en amont (~ligne 2855)
    # pour disposer du _financial_signal_report au moment de construire la
    # FinancialFactsTable Couche 1 injectée dans les prompts agents.
    # Les variables `_financial_signal_in_attachments_solid` et
    # `_financial_signal_report` sont déjà initialisées par le bloc amont
    # (toujours, même en cas d'échec de détection : fallback False/None).
    # On NE refait PAS la détection ici — elle serait redondante (3-5s
    # perdues sur dossiers riches). Le bloc original ligne 3372 a été supprimé.

    # _has_some_financial_signal : True si AU MOINS UNE des 2 sources est solide :
    # 1. FS PDF détectés (dossier anglophone coté Annual Reports lus correctement)
    # 2. Signal financier solide dans attachments_block (dossier réseau de soins Excel/Word)
    # B.1.1 (audit gate B.2, P0) — source 2 = signal EFFECTIF post-gate de
    # périmètre, PAS le brut. C'était la fuite la plus proche du bug dossier industriel (composants)
    # v5 : un signal porté uniquement par des faits MISMATCH poussait la
    # cascade à 75 → règle de prudence Finance désactivée → projections
    # chiffrées sur un chiffre hors périmètre. Le brut reste journalisé
    # (financial_signal_raw_solid) pour l'audit.
    _has_some_financial_signal = _fs_detected_in_any or _fin_signal_solid_effective

    # Cascade explicite v16.5.71 (refonte anti-régression dossier réseau de soins) :
    if _has_some_financial_signal:
        # Cas optimal : signaux financiers solides présents (PDF FS OU Excel/Word/CSV)
        # On ne distingue plus le format — l'important est l'EXPLOITABILITÉ.
        _src_quality_estimate = 75.0
        if _has_pappers_full:
            _src_quality_estimate += 15  # Pappers en plus
        if _has_external_sources:
            _src_quality_estimate += 10
    elif _has_attachments_but_no_fs:
        # Cas DANGEREUX : docs uploadés mais NI FS PDF NI signal financier solide
        # → prudence ACTIVE. C'est le cas dossier anglophone coté (Since v16.5.69.1) et les
        # scénarios "PDF scannés en image" / "documents narratifs sans chiffres".
        _src_quality_estimate = 35.0
    elif _has_pappers_full:
        # Pappers seul (pas de docs uploadés) : prudence ACTIVE (35 < 40)
        _src_quality_estimate = 35.0
        if _has_external_sources:
            _src_quality_estimate += 10  # 45 si sources externes en plus
    else:
        # Aucun signal : défiance forte
        _src_quality_estimate = 25.0

    # Patch v16.5.70.2 — seuil <= 40 (pas <) pour activer la prudence sur
    # cas Pappers seul (= 40 exactement) qui est aussi un cas borderline
    # B.1.3.6-HYBRID (audit ChatGPT) — pont fidélité-page → SQ AVANT prompts
    # agents. En 3.6 officiel, ce bloc lisait `result.get(...)` alors que
    # `result` n'existe qu'en FIN de run : exception avalée ⇒ bridge amont mort.
    # Ici on calcule la fidélité per-page depuis la table déjà construite et le
    # corpus disponible, puis on plafonne la source_quality AVANT la règle de
    # prudence Finance. Fail-open : toute donnée manquante laisse le score brut.
    try:
        from patches.source_quality_bridge import cap_source_quality as _csq136
        _npc = None; _nfc = None; _tst = ""
        try:
            if _facts_table_built is not None:
                from patches.extraction_fidelity import per_page_summary as _pp_sum136
                _input_corpus_sq = "\n\n".join(
                    s for s in (brief, attachments_block, financial_statements_block)
                    if isinstance(s, str) and s.strip())
                if _input_corpus_sq:
                    _pp_sq = _pp_sum136(_facts_table_built, _input_corpus_sq) or {}
                    _extraction_fidelity = dict(_extraction_fidelity or {})
                    _extraction_fidelity["per_page"] = _pp_sq
                    _npc = (int(_pp_sq.get("verbatim_on_page", 0))
                            + int(_pp_sq.get("normalized_on_page", 0)))
                    _nfc = (_npc
                            + int(_pp_sq.get("page_unavailable", 0))
                            + int(_pp_sq.get("no_citation", 0))
                            + int(_pp_sq.get("not_found_on_cited_page", 0)))
                    _tst = "DEGRADED" if (_nfc and not _npc) else ("OK" if _nfc else "")
        except Exception as _e_pp:
            _npc = None; _nfc = None; _tst = ""
            _pp_exc = f"{type(_e_pp).__name__}: {str(_e_pp)[:80]}"
        else:
            _pp_exc = ""
        _sq_new, _sq_reason = _csq136(_src_quality_estimate, _npc, _nfc, _tst)
        # B.1.3.8 — le bridge 3.7 est resté SILENCIEUX au run (per_page lisible
        # par le gate UI via le poseur Cycle D, cap amont jamais mordu, cause
        # invisible). Son ÉTAT est désormais TOUJOURS tracé — fail-open TRACÉ.
        if diag_list is not None:
            try:
                diag_list.append({
                    "role": "sq_bridge_state", "provider": "internal",
                    "model": "sq_bridge_b138",
                    "status": ("CAPPED" if _sq_reason else "PASS"),
                    "summary": (f"table_built={_facts_table_built is not None} "
                                f"npc={_npc} nfc={_nfc} tst={_tst or '—'} "
                                f"sq_in={_src_quality_estimate} sq_out={_sq_new} "
                                f"exc={_pp_exc or '—'}"),
                })
            except Exception:
                pass
        if _sq_reason:
            _src_quality_estimate = _sq_new
            if diag_list is not None:
                diag_list.append({"role": "source_quality_capped",
                                  "provider": "internal", "model": "sq_bridge_b136_hybrid",
                                  "status": "CAPPED", "summary": _sq_reason})
    except Exception:
        pass
    _source_quality_below_threshold = _src_quality_estimate <= 40

    # Construction de la règle "no business plan" — bilingue FR + EN.
    # Forcée seulement si _source_quality_below_threshold = True.
    # v62.13.9.4.49 — point 0 : UN SEUL RÉALISÉ. Contre-recette ChatGPT du 28/09/2026 (F4) : l'agent
    # Finance reconstruisait sa colonne « réalisé » à partir de composantes (une ligne d'amortissements
    # ajoutée à des charges qui l'incluaient déjà : résultat opérationnel faux de près de 10 %). Les
    # réalisés confirmés de la table de faits sont imposés tels quels ; le détecteur
    # utils/actuals_reconciliation49 signale tout écart résiduel.
    _finance_actuals_rule_fr = (
        "\nRÉALISÉ UNIQUE : pour tout exercice dont la table des faits ci-dessous porte des montants "
        "confirmés (chiffre d'affaires, marge brute, résultat d'exploitation, résultat net, trésorerie…), "
        "reprends ces montants À L'IDENTIQUE dans toute colonne « réalisé ». Ne reconstruis jamais un réalisé "
        "à partir de composantes (par exemple en ajoutant une ligne d'amortissements à des charges qui les "
        "incluent déjà). Si une ventilation n'est pas dans les faits confirmés, écris le total confirmé et "
        "indique « ventilation à sourcer ». Les projections partent de ce réalisé.\n")
    _finance_actuals_rule_en = (
        "\nSINGLE ACTUAL: for any fiscal year whose confirmed figures appear in the facts table below "
        "(revenue, gross profit, operating income, net income, cash…), use those figures VERBATIM in any "
        "'Actual' column. Never rebuild an actual from components (for instance by adding a depreciation "
        "line to expenses that already include it). If a breakdown is not among the confirmed facts, write "
        "the confirmed total and state 'breakdown to be sourced'. Projections start from this actual.\n")
    _finance_prudence_rule_fr = ""
    _finance_prudence_rule_en = ""
    if _source_quality_below_threshold:
        _finance_prudence_rule_fr = (
            "\n⚠️ RÈGLE DE PRUDENCE — SOURCE QUALITY FAIBLE (Patch v16.5.70 Phase 5) :\n"
            f"La qualité des sources est estimée à {int(_src_quality_estimate)}/100 (< 40). "
            "Tu DOIS suivre les contraintes suivantes :\n"
            "  ❌ INTERDIT : projections chiffrées détaillées (EBITDA, EBIT, FCF, scénarios pluriannuels)\n"
            "  ❌ INTERDIT : business plan FY+1 / FY+2 avec montants précis\n"
            "  ❌ INTERDIT : recommandations chiffrées (capex, opex, marketing budget en €/$/£ précis)\n"
            "  ✅ AUTORISÉ : diagnostic qualitatif (tendances, signaux faibles, axes de risque)\n"
            "  ✅ AUTORISÉ : risques majeurs identifiés sans valorisation précise\n"
            "  ✅ AUTORISÉ : questions à vérifier dans documents officiels (DAF Letter, comptes audités)\n"
            "  ✅ AUTORISÉ : liste explicite des tableaux financiers NÉCESSAIRES pour pousser plus loin\n"
            "  ✅ AUTORISÉ : scénarios qualitatifs (optimiste / pessimiste) sans montants\n"
            "Cette règle protège la crédibilité du livrable. La projection chiffrée détaillée "
            "sera produite dans un second passage UNE FOIS les Financial Statements obtenus.\n"
        )
        _finance_prudence_rule_en = (
            "\n⚠️ CAUTION RULE — LOW SOURCE QUALITY (Patch v16.5.70 Phase 5):\n"
            f"Source quality is estimated at {int(_src_quality_estimate)}/100 (< 40). "
            "You MUST follow the constraints below:\n"
            "  ❌ FORBIDDEN: detailed financial projections (EBITDA, EBIT, FCF, multi-year scenarios)\n"
            "  ❌ FORBIDDEN: FY+1 / FY+2 business plan with precise figures\n"
            "  ❌ FORBIDDEN: numerical recommendations (capex, opex, marketing budget in precise €/$/£)\n"
            "  ✅ ALLOWED: qualitative diagnostic (trends, weak signals, risk angles)\n"
            "  ✅ ALLOWED: major risks identified without precise valuation\n"
            "  ✅ ALLOWED: questions to verify in official documents (CFO letter, audited accounts)\n"
            "  ✅ ALLOWED: explicit list of financial tables NEEDED for deeper analysis\n"
            "  ✅ ALLOWED: qualitative scenarios (optimistic / pessimistic) without amounts\n"
            "This rule protects deliverable credibility. Detailed projections will be produced "
            "in a second pass ONCE the Financial Statements are obtained.\n"
        )
        if logger:
            log_event(logger, "info", "finance_prudence",
                      f"Source quality estimée {int(_src_quality_estimate)}/100 < 40 — "
                      f"règle prudence anti-business-plan injectée dans prompt Finance")

    # v16.5.60 — règle de cross-référence pour prévenir les mauvaises lectures
    # (ex. un "Autres créances" à 151 k€ qui est en réalité un CCA débiteur).
    if lang == "en":
        _finance_cross_ref_rule = (
            "\nMANDATORY CROSS-REFERENCE RULE (v16.5.60):\n"
            "Before projecting on any balance-sheet line that represents more than 10% "
            "of total assets/liabilities, you MUST explicitly cite its detailed ventilation "
            "(detailed account, auditor note, or management letter). "
            "If the detail is not available in the provided documents, say so verbatim: "
            "'Detail not available in provided documents — projection conditional on clarification.'\n"
            "Specifically scrutinize: 'Other receivables', 'Other payables', "
            "'Current accounts', any line > 10% of the balance sheet.\n"
        )
    else:
        _finance_cross_ref_rule = (
            "\nRÈGLE DE CROSS-RÉFÉRENCE OBLIGATOIRE (v16.5.60) :\n"
            "Avant toute projection sur une ligne de bilan représentant plus de 10 % "
            "du total actif/passif, tu DOIS citer explicitement sa ventilation détaillée "
            "(détail des comptes, note de l'expert-comptable, courrier de recommandation). "
            "Si le détail n'est pas disponible dans les documents fournis, dis-le textuellement : "
            "'Détail non disponible dans les documents fournis — projection conditionnée à clarification.'\n"
            "À scruter en particulier : 'Autres créances', 'Autres dettes', 'Comptes courants', "
            "toute ligne > 10 % du bilan. Un poste 'Autres créances' significatif peut être un "
            "compte courant d'associé (CCA) et non une créance tiers recouvrable.\n"
        )

    # v16.5.67.10 P1 — Règle de tagging sourcing [FAIT] pour pièces jointes client.
    # Bug observé run dossier réseau de soins 19/04 : Finance extrayait bien les chiffres des
    # 3 annexes légales (exemple synthétique : filiale A, filiale B, écart d’acquisition…)
    # mais les taggait HYPOTHÈSE/INCERTAIN faute de savoir qu'ils venaient de
    # documents client. Résultat : aucun [FAIT] dans le CR, perte de traçabilité
    # bilan↔analyse. On injecte maintenant explicitement la liste des fichiers
    # attachés + la règle "chiffre issu d'un fichier attaché → tag FAIT +
    # source_ref = nom du fichier".
    _attached_filenames = []
    if attachments_meta and isinstance(attachments_meta, dict):
        _raw = attachments_meta.get("filenames") or []
        if isinstance(_raw, (list, tuple)):
            _attached_filenames = [str(fn) for fn in _raw if fn]

    if _attached_filenames:
        _files_list_fr = "\n".join(f"  - {fn}" for fn in _attached_filenames)
        _finance_attachments_rule_fr = (
            "\nRÈGLE DE SOURCING (v16.5.67.10) — PIÈCES JOINTES CLIENT :\n"
            "Les documents suivants ont été fournis par le client et sont considérés "
            "comme SOURCES OFFICIELLES (comptes arrêtés, liasses fiscales, rapports, "
            "notes) :\n"
            f"{_files_list_fr}\n"
            "Pour CHAQUE chiffre que tu extrais de l'un de ces documents (via le "
            "bloc contexte qui en résume le contenu ci-dessous), tu DOIS :\n"
            "  1. Dans le texte markdown : indiquer '[FAIT]' juste après le chiffre.\n"
            "  2. Dans le bloc JSON final : utiliser tag='FAIT' ET renseigner "
            "source_ref avec le NOM EXACT du fichier d'origine.\n"
            "Exemple : \"CA EXEMPLE-SA 12,3 M€ [FAIT] (source: comptes_2025.pdf)\" "
            "→ dans le JSON : {\"text\":\"CA EXEMPLE-SA 12,3 M€\",\"tag\":\"FAIT\",\"source_ref\":\"comptes_2025.pdf\",...}\n"
            "À l'inverse, les chiffres que tu CALCULES (ratios, projections) "
            "restent tag=CALCUL ou ESTIM, et ceux que tu supposes sans source "
            "restent tag=HYPOTHÈSE ou INCERTAIN.\n"
            "Ne JAMAIS tagger FAIT un chiffre absent des documents fournis.\n"
        )
        _finance_attachments_rule_en = (
            "\nSOURCING RULE (v16.5.67.10) — CLIENT ATTACHMENTS:\n"
            "The following documents were provided by the client and are "
            "OFFICIAL SOURCES (approved accounts, tax filings, reports, notes):\n"
            f"{_files_list_fr}\n"
            "For EACH figure you extract from one of these documents (via the "
            "context block that summarizes their content below), you MUST:\n"
            "  1. In markdown: indicate '[FAIT]' right after the figure.\n"
            "  2. In the final JSON block: use tag='FAIT' AND fill source_ref "
            "with the EXACT filename of the source document.\n"
            "Example: \"EXEMPLE-SA revenue EUR 12.3M [FAIT] (source: comptes_2025.pdf)\" "
            "→ in JSON: {\"text\":\"EXEMPLE-SA revenue EUR 12.3M\",\"tag\":\"FAIT\",\"source_ref\":\"comptes_2025.pdf\",...}\n"
            "Conversely, figures you CALCULATE (ratios, projections) stay "
            "tag=CALCUL or ESTIM, and those you assume without source stay "
            "tag=HYPOTHÈSE or INCERTAIN.\n"
            "NEVER tag FAIT a figure absent from provided documents.\n"
        )
    else:
        # Pas de pièces jointes : la règle est vide, rien à injecter.
        _finance_attachments_rule_fr = ""
        _finance_attachments_rule_en = ""

    if lang == "en":
        # Patch v16.5.70.3 P0-2 (audit ChatGPT round 7) — Objectif Finance NON CONTRADICTOIRE
        # Bug v16.5.70.2 : prompt commençait par "Objective: synthetic projection
        # (revenue, margin, OPEX, CAPEX, cash) + plausible figures" PUIS ajoutait
        # plus loin "FORBIDDEN: detailed financial projections". Contradiction
        # interne → LLM peut suivre la 1ère consigne malgré la règle prudence.
        # Solution : remplacer L'OBJECTIF lui-même selon source quality.
        if _source_quality_below_threshold:
            finance_objective_en = (
                "Objective: PRUDENT QUALITATIVE DIAGNOSTIC, no detailed financial projection. "
                "Source quality is too weak for a full P&L / balance / cash flow projection. "
                "Produce: (1) qualitative diagnostic, (2) major risks identified, "
                "(3) explicit list of figures / tables that would be NEEDED to build the projection, "
                "(4) CFO questions to ask before next pass.\n"
            )
        else:
            finance_objective_en = (
                "Objective: synthetic projection (revenue, margin, OPEX, CAPEX, cash) + 3 risks & mitigations.\n"
                "Format: bullets, plausible figures, explicit assumptions.\n"
            )
        finance_prompt = (
            "Role: Chief Financial Officer (CFO).\n"
            + finance_objective_en
            + "Take the Board Brief into account.\n"
            + (_profile_hint + "\n" if _profile_hint else "")
            + _finance_cross_ref_rule
            + _finance_attachments_rule_en
            + _finance_prudence_rule_en  # règle de garde compatible avec l'objectif
            + _finance_actuals_rule_en   # v62.13.9.4.49 — réalisé unique
            + f"{_facts_ctx('finance')}{_pap_ctx('finance')}{_external_ctx('finance')}{_ch_filings_ctx('finance')}{_fs_ctx('finance')}---\nBoard Brief:\n{brief_codir_txt}\n---\nMarketing:\n{marketing_txt}\n---\nSupply Chain seed:\n{sc_seed_txt}\n---\nInitial brief:\n{brief}"
        )
        finance_gemini_system = "You are a rigorous CFO. You produce a clear and prudent projection with explicit assumptions."
    else:
        # Patch v16.5.70.3 P0-2 — Idem en FR : objectif conditionnel
        if _source_quality_below_threshold:
            finance_objective_fr = (
                "Objectif : DIAGNOSTIC QUALITATIF PRUDENT, sans projection financière chiffrée détaillée. "
                "La qualité des sources est trop faible pour produire un compte de résultat / bilan / "
                "tableau de flux complets. Produis : (1) diagnostic qualitatif, (2) risques majeurs "
                "identifiés, (3) liste explicite des chiffres / tableaux NÉCESSAIRES pour construire "
                "la projection, (4) questions au DAF à poser avant un second passage.\n"
            )
        else:
            finance_objective_fr = (
                "Objectif: projection synthétique (CA, marge, OPEX, CAPEX, cash) + 3 risques & parades.\n"
                "Format: bullets, chiffres plausibles, hypothèses explicites.\n"
            )
        finance_prompt = (
            "Rôle: Direction Financière (DAF / CFO).\n"
            + finance_objective_fr
            + "Prends en compte le Brief CoDIR.\n"
            + (_profile_hint + "\n" if _profile_hint else "")
            + _finance_cross_ref_rule
            + _finance_attachments_rule_fr
            + _finance_prudence_rule_fr  # règle de garde compatible avec l'objectif
            + _finance_actuals_rule_fr   # v62.13.9.4.49 — réalisé unique
            + f"{_facts_ctx('finance')}{_pap_ctx('finance')}{_external_ctx('finance')}{_ch_filings_ctx('finance')}{_fs_ctx('finance')}---\nBrief CoDIR:\n{brief_codir_txt}\n---\nMarketing:\n{marketing_txt}\n---\nSupply Chain seed:\n{sc_seed_txt}\n---\nBrief initial:\n{brief}"
        )
        finance_gemini_system = "Tu es un DAF rigoureux. Tu proposes une projection claire et prudente, avec hypothèses."

    # v16.5.67 F1 — schema_instruction EN TÊTE du prompt Finance
    # Retour du run 18/04 v16.5.66 : placée en queue, l'instruction était ignorée
    # par Claude Finance (prompt trop long, attention qui s'effrite). En tête, avant
    # le rôle, elle devient consigne impérative au lieu d'add-on formatting.
    if _USE_AGENT_JSON and _schema_instruction is not None:
        # Instruction impérative en tête, plus "Output requirement" en queue
        schema_head = (
            "IMPÉRATIF DE FORMAT — à lire AVANT le reste du prompt :\n"
            "En plus de ton analyse markdown (qui reste obligatoire), tu DOIS terminer ta "
            "réponse par un bloc JSON structuré encadré par les balises "
            "---AGENT_JSON_START--- et ---AGENT_JSON_END---. Cette consigne est non "
            "négociable — le pipeline de scoring ne fonctionne pas sans ce bloc. "
            "Le détail du schéma est rappelé en fin de prompt.\n\n"
            "---\n\n"
        )
        # v17.1-B2.3-B — discipline de forme finance (métrique, orientation cible,
        # sourcing fort, cotation). Aucun fait/valeur injecté : rigueur de forme.
        _b23b_f = _b23b_prompt_rules(lang, _genre.genre)
        finance_prompt += (_b23b_f["metric"] + _b23b_f["orientation"]
                           + _b23b_f["sourcing"] + _b23b_f["cotation"])
        if _b23b_f.get("finance_tone"):
            finance_prompt += _b23b_f["finance_tone"]
        finance_prompt = schema_head + finance_prompt + _schema_instruction(lang)

    gemini_available = _has_key("google") and (call_gemini is not None)

    if gemini_available:
        gemini_res = _call_with_fallback(
            role="finance_gemini",
            provider_order=["google"],
            prompt=finance_prompt,
            system=_lang_wrap(finance_gemini_system, lang),
            temperature=temperature,
            max_tokens=max(max_tokens, FINANCE_MIN_OUTPUT_TOKENS),  # v16.5.74
            settings=settings,
            diag_list=diag_list,
            cb=cb,
            logger=logger,
        )
        gemini_finance_txt = _as_output(gemini_res)

        if not gemini_res.get("error"):
            # Challenge #1 — Claude challenge Gemini
            ch1_res = _claude_challenge_finance(
                gemini_output=gemini_finance_txt,
                brief_codir_txt=brief_codir_txt,
                marketing_txt=marketing_txt,
                brief=brief,
                pass_num=1,
                previous_challenge="",
                temperature=temperature,
                max_tokens=max(max_tokens, FINANCE_CHALLENGE_MIN_OUTPUT_TOKENS),  # v16.5.74
                settings=settings,
                cb=cb,
                diag_list=diag_list,
                logger=logger,
            )
            ch1_txt = _as_output(ch1_res)

            if ch1_res.get("error"):
                finance_txt = gemini_finance_txt
                finance_res_final = dict(gemini_res)
                finance_res_final["role"] = "finance"
                finance_res_final["warning"] = "Claude challenge #1 indisponible — conservation du draft Gemini."
                finance_res_final["gemini_draft"] = gemini_finance_txt
                finance_res_final["challenge1"] = ch1_txt
            else:
                # Challenge #2 — Claude final consolidation
                ch2_res = _claude_challenge_finance(
                    gemini_output=gemini_finance_txt,
                    brief_codir_txt=brief_codir_txt,
                    marketing_txt=marketing_txt,
                    brief=brief,
                    pass_num=2,
                    previous_challenge=ch1_txt,
                    temperature=temperature,
                    max_tokens=max(max_tokens, FINANCE_CHALLENGE_MIN_OUTPUT_TOKENS),  # v16.5.74
                    settings=settings,
                    cb=cb,
                    diag_list=diag_list,
                    logger=logger,
                )
                if ch2_res.get("error"):
                    finance_txt = ch1_txt
                    finance_res_final = dict(ch1_res)
                    finance_res_final["role"] = "finance"
                    finance_res_final["warning"] = "Claude challenge #2 indisponible — conservation du challenge #1."
                    finance_res_final["gemini_draft"] = gemini_finance_txt
                    finance_res_final["challenge1"] = ch1_txt
                else:
                    finance_txt = _as_output(ch2_res)
                    finance_res_final = ch2_res
                    finance_res_final["role"] = "finance"
                    finance_res_final["gemini_draft"] = gemini_finance_txt
                    finance_res_final["challenge1"] = ch1_txt
        else:
            # Gemini KO → Claude fallback classique
            finance_res_final = _call_with_fallback(
                role="finance",
                provider_order=["anthropic", "openai", "mistral"],
                prompt=finance_prompt,
                system=_lang_wrap(finance_gemini_system, lang),
                temperature=temperature,
                max_tokens=max_tokens,
                settings=settings,
                diag_list=diag_list,
                cb=cb,
                logger=logger,
            )
            finance_txt = _as_output(finance_res_final)
    else:
        # Gemini non dispo → Claude en primaire
        finance_res_final = _call_with_fallback(
            role="finance",
            provider_order=["anthropic", "openai", "mistral"],
            prompt=finance_prompt,
            system=_lang_wrap(finance_gemini_system, lang),
            temperature=temperature,
            max_tokens=max_tokens,
            settings=settings,
            diag_list=diag_list,
            cb=cb,
            logger=logger,
        )
        finance_txt = _as_output(finance_res_final)

    # v16.5.60 — validation anti-hallucination post-Finance
    finance_txt = _validate(finance_txt, "finance")

    # v16.5.66 — Livraison 2 pilote Finance : parser le bloc JSON typé
    # Le parsing est fail-open : toute erreur retombe sur claims=[] sans bloquer.
    # Le résultat est stocké pour injection dans run_ctx plus tard (section scorer).
    _finance_agent_output = None

    # v16.5.67.6 — INSTRUMENTATION OBSERVABILITÉ FINANCE JSON
    # Objectif : comprendre pourquoi parse_status=MISSING apparaît dans 4 runs
    # consécutifs alors que F1 injecte schema_head + schema_instruction.
    # On capture des signaux structurés, sans modifier le comportement existant.
    _fin_diag = {
        "finance_txt_len":           len(finance_txt or ""),
        "has_start_tag":             "---AGENT_JSON_START---" in (finance_txt or ""),
        "has_end_tag":               "---AGENT_JSON_END---"   in (finance_txt or ""),
        "has_both_tags":             (
            "---AGENT_JSON_START---" in (finance_txt or "")
            and "---AGENT_JSON_END---" in (finance_txt or "")
        ),
        # Variantes de balises qui pourraient apparaître si le LLM a dérivé
        "has_start_no_dashes":       "AGENT_JSON_START"       in (finance_txt or "") and "---AGENT_JSON_START---" not in (finance_txt or ""),
        "has_single_dashes":         "-AGENT_JSON_START-"     in (finance_txt or "") and "---AGENT_JSON_START---" not in (finance_txt or ""),
        # JSON potentiellement là mais dans un bloc ```json ... ```
        "has_json_backticks_block":  bool(__import__("re").search(r"```\s*json", (finance_txt or ""), flags=__import__("re").IGNORECASE)),
        # Dernier segment de finance_txt — pour voir si Claude a clos sur JSON ou sur prose
        "finance_txt_tail":          (finance_txt or "")[-400:],
        # Schema flags actifs pour le pass
        "schema_injected":           (_USE_AGENT_JSON and _schema_instruction is not None),
    }

    if _USE_AGENT_JSON and _parse_agent_output is not None:
        try:
            _finance_agent_output = _parse_agent_output(finance_txt, role="finance")

            # v62.13.9.4.15 — LE RETRY FINANCE HISTORIQUE EST RETIRÉ. Il
            # datait de la v16.5.67 (avant A1) : il ne partait que sur
            # MISSING, demandait des claims sans grandeurs et tenait pour
            # succès tout bloc portant des claims. Au run réel du 02/09/2026
            # à 15:04, Finance est sorti « OK » avec 8 claims chiffrées et
            # ZÉRO grandeur — 0 % de couverture, sans qu'aucun retry ne
            # soit tenté et sans que sa sortie soit archivée. Finance passe
            # désormais par la règle et le prompt communs aux huit rôles,
            # avec les mêmes conditions de succès.
            _archive_agent_raw("finance", finance_txt, _finance_agent_output)
            _why62415 = _a1_retry_needed(_finance_agent_output)
            _fin_diag["retry_triggered"] = bool(_why62415)
            _fin_diag["retry_reason"] = _why62415
            if _why62415:
                _r62415 = _retry_agent_json(finance_txt, "finance", settings,
                                            logger=logger, cb=cb,
                                            diag_list=diag_list, reason=_why62415)
                if _r62415 is not None:
                    # le role_summary Finance (checklist DAF) vit dans la
                    # sortie primaire : on le conserve si le retry n'en a pas.
                    try:
                        _rs_prev = getattr(_finance_agent_output, "role_summary", None)
                        _rs_new = getattr(_r62415, "role_summary", None)
                        if _rs_prev is not None and (
                                _rs_new is None
                                or getattr(_rs_new, "daf_checklist_complete", None) is None):
                            _r62415.role_summary = _rs_prev
                    except Exception:
                        pass
                    _fin_diag["retry_parse_status"] = _r62415.parse_status
                    _fin_diag["retry_claims_count"] = _r62415.claims_count
                    _fin_diag["retry_quantities_count"] = _a1_quantities_count(_r62415)
                    _finance_agent_output = _r62415

            if logger:
                log_event(logger, "info", "agent_json",
                          f"finance: status={_finance_agent_output.parse_status} "
                          f"claims={_finance_agent_output.claims_count} "
                          f"errors={len(_finance_agent_output.parse_errors)}")
            if diag_list is not None:
                diag_list.append({
                    "role":     "finance_agent_json",
                    "provider": "internal",
                    "model":    "agent_output_schema_v1",
                    "status":   _finance_agent_output.parse_status,
                    "claims_count": _finance_agent_output.claims_count,
                    "parse_errors_count": len(_finance_agent_output.parse_errors),
                    "parse_errors_sample": _finance_agent_output.parse_errors[:3],
                    # v16.5.67.6 — Instrumentation observabilité (champ libre dans CSV)
                    "observability": _fin_diag,
                })
            # Nettoyer le bloc JSON du markdown final pour ne pas le montrer au DG
            # Il est bas-technique et pollue visuellement le livrable
            from patches.agent_output_schema import JSON_START_TAG as _JS, JSON_END_TAG as _JE
            import re as _re_clean
            finance_txt = _re_clean.sub(
                _re_clean.escape(_JS) + r".*?" + _re_clean.escape(_JE),
                "",
                finance_txt,
                flags=_re_clean.DOTALL,
            ).strip()
        except Exception as _ajson_err:
            if logger:
                log_event(logger, "warning", "agent_json",
                          f"finance parse failed: {type(_ajson_err).__name__}: {_ajson_err}")
            _finance_agent_output = None

    # 6) SUPPLY CHAIN — rôle final prioritaire, challengé par Finance puis Gemini
    # v16.5.60 — idem seed : skip si profil non pertinent
    if not _sc_active:
        supply_chain_bundle = {
            "output":     "",
            "triggered":  False,
            "source":     "skipped_by_profile",
            "warning":    _sc_note,
            "status":     "SKIPPED",
            "json":       None,
            "slide_flag": False,
        }
        supply_chain_txt = ""
    else:
        supply_chain_bundle = run_supply_chain_role(
            user_input=brief,
            finance_output=finance_txt,
            sc_seed_output=sc_seed_txt,
            sc_seed_triggered=sc_seed_bundle.get("triggered"),  # v16.5.28 — évite double pre-filter
            temperature=temperature,
            max_tokens=max(max_tokens, SUPPLY_CHAIN_MIN_OUTPUT_TOKENS),  # v16.5.74
            cb=cb,
            # v16.5.73 — injecter Couche 1 en tête du pappers_context (cf. seed plus haut)
            pappers_context=_facts_ctx("supply_chain") + _pap_ctx("supply_chain"),
            diag_list=diag_list,
            settings=settings,
            logger=logger,
            company_profile=_company_profile,  # v16.5.76 Phase 2 — fast-paths
        )
        supply_chain_txt = _validate(_clean_sc_text(supply_chain_bundle.get("output") or ""), "supply_chain")
        # v62.13.9.4.12 (A1) — idem pour la supply chain.
        _supply_chain_agent_output, supply_chain_txt = _parse_agent_json_and_clean(
            supply_chain_txt, "supply_chain", diag_list, logger=logger)
        _why62415 = _a1_retry_needed(_supply_chain_agent_output)
        if _why62415:
            _r62415 = _retry_agent_json(supply_chain_txt, "supply_chain", settings,
                                        logger=logger, cb=cb, diag_list=diag_list,
                                        reason=_why62415)
            if _r62415 is not None:
                _supply_chain_agent_output = _r62415
        # M6-A2.2 — hygiène JSON SC : si l'agent SC a émis un JSON_START mais que le
        # JSON est inexploitable (tronqué/malformé), on a déjà masqué le JSON brut du
        # CR (via _clean_sc_text) ; on trace explicitement le parse_error en diagnostics.
        _sc_raw_out = supply_chain_bundle.get("output") or ""
        _has_json_tag = JSON_START_TAG in _sc_raw_out
        if _has_json_tag and supply_chain_bundle.get("json") is None:
            # M6-A2.2.2 — distinguer schema_invalid (un bloc parse mais n'est PAS un JSON
            # Supply Chain, ex. JSON commercial) de parse_error (aucun bloc parsable).
            _parsed_any = False
            for _raw in _iter_sc_json_blocks(_sc_raw_out):
                try:
                    json.loads(_raw); _parsed_any = True; break
                except json.JSONDecodeError:
                    continue
            _json_status = "schema_invalid" if _parsed_any else "parse_error"
            _record_diag(
                diag_list, role="supply_chain_json",
                provider=supply_chain_bundle.get("provider", "openai"),
                model="sc_json_parser", status=_json_status,
                error=("JSON présent mais non Supply Chain (garde de schéma) — rejeté, "
                       "narrative conservée" if _json_status == "schema_invalid"
                       else "JSON_START présent mais JSON SC non parsable (tronqué/malformé) "
                       "— narrative conservée, JSON masqué du CR final"))
        # M6-A2.2.1 — décision SC explicite pour l'audit post-run
        _sc_decision = ("consumed_json" if supply_chain_bundle.get("json") is not None
                        else ("structured_invalid" if _has_json_tag
                              else ("narrative_only" if is_sc_output_valid(_sc_raw_out)
                                    else ("light_industrial"
                                          if str(getattr(_company_profile,
                                                         "nature", "")) == "product"
                                          else "not_covered"))))  # B.1.3.23 P1-G' — profil industriel/agro ⇒ jamais « non couverte »
        _record_diag(diag_list, role="supply_chain_decision", provider="codir",
                     model="sc_gate", status=_sc_decision)
        # B.1.3.26 — ne pas écrire dans result ici : le dict de retour n'existe
        # qu'en fin de fonction (écriture morte 3.25, NameError avalé par le
        # fail-open). Export à la racine du return, plus bas.

    # 7) DIRECTION COMMERCIALE — Grok (challenge Marketing + Finance + Supply Chain)
    if cb:
        cb("commercial", f"{_lbl('commercial', lang)} — Grok…")

    # v16.5.60 — adaptation selon profil (ex. SOLO services → raisonne
    # en jours facturés × TJM, pas en 'clients perdus')
    _com_active, _com_note, _com_hint = _is_active("commercial")

    if lang == "en":
        commercial_prompt = (
            "Role: Chief Commercial Officer.\n"
            "Objective: produce an actionable commercial brief for the CEO, challenging Marketing and Finance.\n"
            + (_profile_hint + "\n" if _profile_hint else "")
            + (_com_hint + "\n" if _com_hint else "")
            + "\n"
            "OUTPUT FORMAT — TWO MANDATORY ZONES:\n"
            "\n"
            "ZONE 1 — NARRATIVE NOTE (passed to the report)\n"
            "1. COMMERCIAL DIAGNOSIS (3-4 points).\n"
            "2. PRIORITY COMMERCIAL OPPORTUNITIES (3-4 points).\n"
            "3. COMMERCIAL RECOMMENDATIONS (3 actions).\n"
            "4. MARKETING CHALLENGES (2 points, prefixed 'CHALLENGE MKT:').\n"
            "5. FINANCE CHALLENGES (2 points, prefixed 'CHALLENGE FIN:').\n"
            "6. GO / NO-GO COMMERCIAL DECISIONS.\n"
            "\n"
            "ZONE 2 — STRUCTURED JSON BLOCK (mandatory, used for PowerPoint)\n"
            f"Place the JSON strictly between the following tags:\n"
            f"{JSON_START_TAG}\n"
            f"{COMMERCIAL_JSON_SCHEMA_HINT}\n"
            f"{JSON_END_TAG}\n"
            "\n"
            "ABSOLUTE RULES for JSON:\n"
            "- plan_actions: EXACTLY 3 items, DIFFERENT and PROGRESSIVE deadlines (T1, T2, T3).\n"
            "- All values are clean strings, NO markdown, NO stray apostrophes, NO \\n.\n"
            "- No text between the tags and the JSON. Pure JSON only.\n"
            "\n"
            "You must:\n"
            "  - Challenge Marketing assumptions (channels, targets, offers, budget).\n"
            "  - Challenge Finance projections (revenue, pricing, margins, conversion, pipeline).\n"
            "  - Take supply chain constraints into account where relevant.\n"
            "  - Propose concrete, actionable and where possible quantified actions.\n"
            "Take the Board Brief into account and stay results-oriented.\n"
            f"{_facts_ctx('commercial')}{_pap_ctx('commercial')}{_external_ctx('commercial')}{_web_ctx('commercial')}---\nBoard Brief:\n{brief_codir_txt}\n"
            f"---\nMarketing:\n{marketing_txt}\n"
            f"---\nFinance:\n{finance_txt}\n"
            f"---\nSupply Chain:\n{supply_chain_txt}\n"
            f"---\nInitial brief:\n{brief}"
        )
        commercial_system = "You are a senior Chief Commercial Officer, pragmatic and results-driven. You challenge and propose concrete actions."
    else:
        commercial_prompt = (
            "Rôle: Directeur Commercial.\n"
            "Objectif: produire une note commerciale exploitable par le dirigeant, en challengant Marketing et Finance.\n"
            + (_profile_hint + "\n" if _profile_hint else "")
            + (_com_hint + "\n" if _com_hint else "")
            + "\n"
            "FORMAT DE SORTIE — DEUX ZONES OBLIGATOIRES :\n"
            "\n"
            "ZONE 1 — NOTE NARRATIVE (transmise au compte-rendu)\n"
            "1. DIAGNOSTIC COMMERCIAL (3-4 points).\n"
            "2. OPPORTUNITÉS COMMERCIALES PRIORITAIRES (3-4 points).\n"
            "3. PRÉCONISATIONS COMMERCIALES (3 actions).\n"
            "4. CHALLENGES MARKETING (2 points, préfixés 'CHALLENGE MKT :').\n"
            "5. CHALLENGES FINANCE (2 points, préfixés 'CHALLENGE FIN :').\n"
            "6. ARBITRAGES OU GO / NO-GO COMMERCIAUX.\n"
            "\n"
            "ZONE 2 — BLOC JSON STRUCTURÉ (obligatoire, utilisé pour le PowerPoint)\n"
            f"Place le JSON strictement entre les balises suivantes :\n"
            f"{JSON_START_TAG}\n"
            f"{COMMERCIAL_JSON_SCHEMA_HINT}\n"
            f"{JSON_END_TAG}\n"
            "\n"
            "RÈGLES ABSOLUES pour le JSON :\n"
            "- plan_actions : EXACTEMENT 3 items, délais DIFFÉRENTS et PROGRESSIFS (T1, T2, T3).\n"
            "- Toutes les valeurs sont des strings propres, SANS markdown, SANS apostrophes parasites, SANS \\n.\n"
            "- Aucun texte entre les balises et le JSON. JSON pur uniquement.\n"
            "\n"
            "Tu dois impérativement :\n"
            "  - Challenger les hypothèses Marketing (canaux, cibles, offres, budget).\n"
            "  - Challenger les projections Finance (CA, pricing, marges, conversion, pipeline).\n"
            "  - Tenir compte des contraintes supply chain si pertinent.\n"
            "  - Proposer des actions concrètes, actionnables et si possible chiffrées.\n"
            "Prends en compte le Brief CoDIR et reste orienté résultats.\n"
            f"{_facts_ctx('commercial')}{_pap_ctx('commercial')}{_external_ctx('commercial')}{_web_ctx('commercial')}---\nBrief CoDIR:\n{brief_codir_txt}\n"
            f"---\nMarketing:\n{marketing_txt}\n"
            f"---\nFinance:\n{finance_txt}\n"
            f"---\nSupply Chain:\n{supply_chain_txt}\n"
            f"---\nBrief initial:\n{brief}"
        )
        commercial_system = "Tu es un Directeur Commercial senior, pragmatique et orienté résultats. Tu challenges et proposes des actions concrètes."

    commercial_res = _call_with_fallback(
        role="commercial",
        provider_order=["grok", "openai", "anthropic", "google", "mistral"],
        prompt=_inject_json_schema_in_agent_prompt(commercial_prompt, lang),
        system=_lang_wrap(commercial_system, lang),
        temperature=temperature,
        max_tokens=max(max_tokens, COMMERCIAL_MIN_OUTPUT_TOKENS),  # v16.5.74
        settings=settings,
        diag_list=diag_list,
        cb=cb,
        logger=logger,
    )
    commercial_txt = _validate(_as_output(commercial_res), "commercial")
    # v62.13.9.4.12 (A1) — l'agent commercial n'était pas branché sur le
    # canal de claims structurés : ses grandeurs n'étaient jamais déclarées.
    # Deux agents sur huit restaient muets (contre-audit du 31/08/2026).
    _commercial_agent_output, commercial_txt = _parse_agent_json_and_clean(
        commercial_txt, "commercial", diag_list, logger=logger)
    # v62.13.9.4.12.4 — retry généralisé : le rattrapage existait pour
    # Stratégie, Brief et Finance seulement. Il a fait ses preuves sur
    # Finance au run réel ; il coûte un appel court, et uniquement en
    # cas d'échec.
    _why62415 = _a1_retry_needed(_commercial_agent_output)
    if _why62415:
        _r62415 = _retry_agent_json(commercial_txt, "commercial", settings,
                                    logger=logger, cb=cb, diag_list=diag_list,
                                    reason=_why62415)
        if _r62415 is not None:
            _commercial_agent_output = _r62415
    # Option B — v16.5.28 : extraire le JSON commercial directement depuis la sortie Grok
    commercial_json = extract_commercial_json(commercial_txt)

    # 7) SYNTHESE DES DECISIONS — Perplexity
    if cb:
        cb("synthese_decisions", f"{_lbl('synthese', lang)} — Perplexity…")

    if lang == "en":
        synthese_prompt = (
            "Role: Senior Decision Analyst — Board Decision Synthesis.\n"
            "Objective: produce a concise and DECISION-ORIENTED synthesis, max 400 words, "
            "consolidating all board analyses.\n"
            "\n"
            "ABSOLUTE RULE: each decision must contain 4 elements:\n"
            "  - WHAT: concrete action (verb + object)\n"
            "  - WHO: designated department or responsible\n"
            "  - WHEN: precise deadline (date, week, before Q1, etc.)\n"
            "  - IMPACT: expected figure or KPI (revenue, margin, cash, service rate, etc.)\n"
            "  If an element is unknown: explicitly state [TO BE DEFINED].\n"
            "\n"
            "MANDATORY FORMAT:\n"
            "  1. PRIORITY DECISIONS (3 to 5)\n"
            "     → Line format: [n] WHAT | WHO | WHEN | IMPACT\n"
            "     → Distinguish: RECOMMENDED ORIENTATION / TO SUBMIT TO CEO / TO BE ARBITRATED\n"
            "  2. CROSS-FUNCTION WATCH SIGNALS (2 to 3 max)\n"
            "     → Risks or inconsistencies between departments (e.g. Finance vs SC, Mktg vs Commercial)\n"
            "  3. OPEN DECISIONS (2 to 3 max)\n"
            "     → Unresolved questions requiring CEO decision — with quantified stakes if possible\n"
            "  4. COMMERCIAL IMPACT — only if material (pricing, pipeline, go-to-market)\n"
            "  5. SUPPLY CHAIN IMPACT — only if material (service, stock, cash, execution)\n"
            "\n"
            "IMPORTANT: data from the brief or provided documents are FACTS. "
            "Pipeline estimates (not from provided data) must be flagged [ESTIM.].\n"
            "Style: concise, directive, no redundancy with detail sections.\n"
            f"{_facts_ctx('synthese')}{_pap_ctx('synthese')}{_external_ctx('synthese')}{_ch_filings_ctx('synthese')}{_fs_ctx('synthese')}---\nBoard Brief:\n{brief_codir_txt}\n"
            f"---\nStrategy:\n{strategie_txt}\n"
            f"---\nMarketing:\n{marketing_txt}\n"
            f"---\nFinance:\n{finance_txt}\n"
            f"---\nSupply Chain:\n{supply_chain_txt}\n"
            f"---\nCommercial:\n{commercial_txt}\n"
            f"---\nInitial brief:\n{brief}"
        )
        synthese_system = "You are a neutral and rigorous decision analyst. You produce a structured decision synthesis with what/who/when/impact for each decision. You do not repeat analyses — you structure decision options and recommend orientations."
    else:
        synthese_prompt = (
            "Rôle: Analyste décisionnel senior — Synthèse des décisions CoDIR.\n"
            "Objectif: produire une synthèse concise et DÉCISIONNELLE, max 400 mots, "
            "en consolidant l'ensemble des analyses du comité de direction.\n"
            "\n"
            "RÈGLE ABSOLUE : chaque décision doit comporter 4 éléments :\n"
            "  - QUOI : action concrète (verbe + objet)\n"
            "  - QUI : direction ou responsable désigné\n"
            "  - QUAND : échéance précise (date, semaine, avant T1, etc.)\n"
            "  - IMPACT : chiffre ou KPI attendu (CA, marge, cash, taux de service, etc.)\n"
            "  Si un élément est inconnu : indiquer explicitement [À DÉFINIR].\n"
            "\n"
            "FORMAT OBLIGATOIRE :\n"
            "  1. DÉCISIONS PRIORITAIRES (3 à 5)\n"
            "     → Format ligne : [n] QUOI | QUI | QUAND | IMPACT\n"
            "     → Distinguer : ORIENTATION RECOMMANDÉE / À SOUMETTRE AU DG / À ARBITRER\n"
            "  2. SIGNAUX DE VIGILANCE CROSS-FONCTIONS (2 à 3 max)\n"
            "     → Risques ou incohérences entre directions (ex: Finance vs SC, Mktg vs Commercial)\n"
            "  3. ARBITRAGES OUVERTS (2 à 3 max)\n"
            "     → Questions non résolues nécessitant une décision DG — avec enjeu chiffré si possible\n"
            "  4. IMPACT COMMERCIAL — uniquement si matériel (pricing, pipeline, go-to-market)\n"
            "  5. IMPACT SUPPLY CHAIN — uniquement si matériel (service, stock, cash, exécution)\n"
            "\n"
            "IMPORTANT : les données issues du brief ou de documents fournis sont des FAITS. "
            "Les estimations du pipeline (hors données fournies) doivent être signalées [ESTIM.].\n"
            "Style: synthétique, directif, sans redondance avec les sections de détail.\n"
            f"{_facts_ctx('synthese')}{_pap_ctx('synthese')}{_external_ctx('synthese')}{_ch_filings_ctx('synthese')}{_fs_ctx('synthese')}---\nBrief CoDIR:\n{brief_codir_txt}\n"
            f"---\nStratégie:\n{strategie_txt}\n"
            f"---\nMarketing:\n{marketing_txt}\n"
            f"---\nFinance:\n{finance_txt}\n"
            f"---\nSupply Chain:\n{supply_chain_txt}\n"
            f"---\nCommercial:\n{commercial_txt}\n"
            f"---\nBrief initial:\n{brief}"
        )
        synthese_system = "Tu es un analyste décisionnel neutre et rigoureux. Tu produis une synthèse décisionnelle structurée avec quoi/qui/quand/impact pour chaque décision. Tu ne répètes pas les analyses — tu structures les options de décision et proposes des orientations."

    # v16.5.76 Phase 4 — Injection schema JSON (item 3)
    # v17.1-B2.3-B — discipline décisionnelle (une reco finale, tranche prudemment).
    synthese_prompt += _b23b_prompt_rules(lang, _genre.genre)["decision"]
    synthese_prompt = _inject_json_schema_in_agent_prompt(synthese_prompt, lang)

    synthese_res = _call_with_fallback(
        role="synthese_decisions",
        provider_order=["perplexity", "openai", "anthropic", "google", "mistral"],
        prompt=synthese_prompt,
        system=_lang_wrap(synthese_system, lang),
        temperature=0.3,
        max_tokens=max(max_tokens, SYNTHESE_MIN_OUTPUT_TOKENS),  # v16.5.74
        settings=settings,
        diag_list=diag_list,
        cb=cb,
        logger=logger,
    )
    synthese_txt = _validate(_as_output(synthese_res), "synthese_decisions")
    # v16.5.76 Phase 4 — Parser le bloc JSON et nettoyer
    _synthese_agent_output, synthese_txt = _parse_agent_json_and_clean(
        synthese_txt, role="synthese_decisions", diag_list=diag_list, logger=logger,
    )
    # v62.13.9.4.12.4 — retry généralisé : le rattrapage existait pour
    # Stratégie, Brief et Finance seulement. Il a fait ses preuves sur
    # Finance au run réel ; il coûte un appel court, et uniquement en
    # cas d'échec.
    _why62415 = _a1_retry_needed(_synthese_agent_output)
    if _why62415:
        _r62415 = _retry_agent_json(synthese_txt, "synthese_decisions", settings,
                                    logger=logger, cb=cb, diag_list=diag_list,
                                    reason=_why62415)
        if _r62415 is not None:
            _synthese_agent_output = _r62415

    # 8) DIRECTION GENERALE / CEO — OpenAI
    if cb:
        cb("direction_generale", f"{_lbl('dg', lang)} — {'feuille de route T0→T+90j' if lang == 'fr' else 'T0→T+90d roadmap'}…")

    if lang == "en":
        dg_prompt = (
            "Role: CEO.\n"
            "Objective: note (10-15 lines) that structures decision options, recommends orientations and gives the T0→T+90d roadmap.\n"
            "Style: directive, clear, realistic. End with 5 dated next-steps.\n"
            "Explicitly incorporate commercial decisions when they have a material impact on revenue, pricing, pipeline, customer segmentation or execution plan.\n"
            "You have the decision synthesis and all analyses available.\n"
            + (_profile_hint + "\n" if _profile_hint else "")
            + f"---\nDecision Synthesis:\n{synthese_txt}\n"
            f"{_facts_ctx('dg')}{_pap_ctx('dg')}{_external_ctx('dg')}{_web_ctx('dg')}{_ch_filings_ctx('dg')}{_fs_ctx('dg')}---\nBoard Brief:\n{brief_codir_txt}\n"
            f"---\nStrategy:\n{strategie_txt}\n"
            f"---\nMarketing:\n{marketing_txt}\n"
            f"---\nFinance:\n{finance_txt}\n"
            f"---\nSupply Chain:\n{supply_chain_txt}\n"
            f"---\nCommercial:\n{commercial_txt}\n"
            f"---\nInitial brief:\n{brief}"
        )
        dg_system = "You are a pragmatic CEO. You structure options, recommend orientations, and assign follow-up owners clearly."
    else:
        dg_prompt = (
            "Rôle: CEO.\n"
            "Objectif: note (10-15 lignes) qui structure les options, recommande une orientation et donne la feuille de route T0->T+90j.\n"
            "Style: directif, clair, réaliste. Termine par 5 next-steps datées.\n"
            "Tu dois reprendre explicitement les décisions commerciales lorsqu'elles ont un impact matériel sur le chiffre d'affaires, le pricing, le pipeline, la segmentation clients ou le plan d'exécution.\n"
            "Tu disposes de la synthèse des décisions et de l'ensemble des analyses.\n"
            + (_profile_hint + "\n" if _profile_hint else "")
            + f"---\nSynthèse des décisions:\n{synthese_txt}\n"
            f"{_facts_ctx('dg')}{_pap_ctx('dg')}{_external_ctx('dg')}{_web_ctx('dg')}{_ch_filings_ctx('dg')}{_fs_ctx('dg')}---\nBrief CoDIR:\n{brief_codir_txt}\n"
            f"---\nStratégie:\n{strategie_txt}\n"
            f"---\nMarketing:\n{marketing_txt}\n"
            f"---\nFinance:\n{finance_txt}\n"
            f"---\nSupply Chain:\n{supply_chain_txt}\n"
            f"---\nCommercial:\n{commercial_txt}\n"
            f"---\nBrief initial:\n{brief}"
        )
        dg_system = "Tu es un CEO pragmatique. Tu structures les options, recommandes des orientations et proposes des responsables de suivi."

    # v16.5.76 Phase 4 — Injection schema JSON (item 3)
    # v17.1-B2.3-B — discipline décisionnelle (DG).
    dg_prompt += _b23b_prompt_rules(lang, _genre.genre)["decision"]
    dg_prompt = _inject_json_schema_in_agent_prompt(dg_prompt, lang)

    ceo_res = _call_with_fallback(
        role="direction_generale",
        provider_order=["openai", "anthropic", "google", "mistral"],
        prompt=dg_prompt,
        system=_lang_wrap(dg_system, lang),
        temperature=temperature,
        max_tokens=max(max_tokens, DG_MIN_OUTPUT_TOKENS),  # v16.5.74
        settings=settings,
        diag_list=diag_list,
        cb=cb,
        logger=logger,
    )
    ceo_txt = _validate(_as_output(ceo_res), "direction_generale")
    # v16.5.76 Phase 4 — Parser le bloc JSON et nettoyer
    _dg_agent_output, ceo_txt = _parse_agent_json_and_clean(
        ceo_txt, role="dg", diag_list=diag_list, logger=logger,
    )
    # v62.13.9.4.12.4 — retry généralisé : le rattrapage existait pour
    # Stratégie, Brief et Finance seulement. Il a fait ses preuves sur
    # Finance au run réel ; il coûte un appel court, et uniquement en
    # cas d'échec.
    _why62415 = _a1_retry_needed(_dg_agent_output)
    if _why62415:
        _r62415 = _retry_agent_json(ceo_txt, "dg", settings,
                                    logger=logger, cb=cb, diag_list=diag_list,
                                    reason=_why62415)
        if _r62415 is not None:
            _dg_agent_output = _r62415

    # Consolidation
    outputs = {
        "strategie":           strategie_txt,
        "brief_codir":         brief_codir_txt,
        "marketing":           marketing_txt,
        "finance":             finance_txt,
        "supply_chain":        supply_chain_txt,
        "commercial":          commercial_txt,
        "synthese_decisions":  synthese_txt,
        "ceo":                 ceo_txt,
        "direction_generale":  ceo_txt,
    }
    # 9.4.54 — écran traitement : les agents ont rendu leurs analyses ; l'étape 11 (« Contrôles et compte rendu ») commence
    try:
        if cb:
            cb("controles_cr", "Contrôles et compte rendu…" if lang == "fr" else "Checks and minutes…")
    except Exception:
        pass

    # F.6.8 (audit dossier réseau de soins) — séance CLOSING_REVIEW / ALERTS_ONLY : aucun vocabulaire
    # GO/NO-GO ne doit subsister dans les sorties rendues (agent Commercial,
    # synthèse, DG…). Scrub déterministe → langage d'alerte / recommandation.
    if getattr(_genre, "forbids_go_nogo", False):
        try:
            from patches.alerts_only_scrubber import scrub_go_nogo as _scrub_go
            outputs = {k: (_scrub_go(v) if isinstance(v, str) else v)
                       for k, v in outputs.items()}
        except Exception:
            pass

    # F.6.10 (audit dossier réseau de soins F.6.9) — GARDE COMPTABLE DAF (tous modes) : un
    # « résultat/CA consolidé groupe estimé » obtenu par ADDITION de résultats
    # sociaux (sans éliminations) est méthodologiquement faux et piège un DAF.
    # On réécrit le libellé en « somme indicative des résultats sociaux (NON
    # consolidé) » — le chiffre et le tag épistémique sont conservés.
    try:
        from patches.daf_accounting_guard import scrub_pseudo_consolidation as _scrub_daf
        outputs = {k: (_scrub_daf(v) if isinstance(v, str) else v)
                   for k, v in outputs.items()}
    except Exception:
        pass

    # B.1.3.51 candidat ChatGPT — GARDE NARRATIVE au vrai chokepoint :
    # la map `outputs` est la source commune du CR DOCX et du report_text PPT.
    # L'officielle 3.51 ne gouvernait qu'une copie locale `_b23_cr`, jamais rendue.
    _accounting_narrative_guard = None
    _accounting_guard_failed = False
    try:
        from patches.finance_shaper import govern_accounting_outputs as _gao51
        outputs, _accounting_narrative_guard = _gao51(outputs, lang=lang)
        _accounting_guard_failed = False
        if (_accounting_narrative_guard or {}).get("status") == "ERROR":
            # Explicit enforcement contract: accounting_narrative_guard ERROR
            # is merged below into run_validatable=False and client BLOCKED.
            _accounting_guard_failed = True
        if diag_list is not None:
            _n51 = int((_accounting_narrative_guard or {}).get("changes", 0))
            _status51 = ("ERROR" if _accounting_guard_failed else
                         ("REQUALIFIED" if _n51 else "OK"))
            diag_list.append({
                "role": "accounting_narrative_guard",
                "provider": "internal",
                "model": "accounting_narrative_guard_b1353_chatgpt_candidate",
                "status": _status51,
                "changes": _n51,
                "sections": (_accounting_narrative_guard or {}).get("sections", {}),
                "samples": (_accounting_narrative_guard or {}).get("samples", []),
            })
    except Exception as _ang51_exc:
        _accounting_guard_failed = True
        _accounting_narrative_guard = {"status": "ERROR",
                                       "error": f"{type(_ang51_exc).__name__}: {_ang51_exc}"}
        # TRUTH_FAIL_CLOSED — no ungoverned narrative reaches DOCX/PPTX.
        _fallback53 = ("[Accounting section not governed — CFO/auditor review required]"
                       if str(lang or "fr").lower().startswith("en") else
                       "[Section comptable non gouvernée — vérification DAF/CAC requise]")
        outputs = {k: (_fallback53 if isinstance(v, str) and v else v)
                   for k, v in (outputs or {}).items()}
        if diag_list is not None:
            diag_list.append({
                "role": "accounting_narrative_guard", "provider": "internal",
                "model": "accounting_narrative_guard_b1353_chatgpt_candidate",
                "status": "ERROR", "error": _accounting_narrative_guard["error"],
            })

    # M6-S.2.1.2 — verrou entité dans les TITRES markdown des sorties agents.
    # Les agents émettent parfois « # STRATEGIC ANALYSIS — dossier anglophone coté LIMITED » ;
    # rendu en paragraphe normal, ce titre échappe au verrou docx (style Heading).
    # On corrige ici, à la source : titres « # … » seulement, corps épargné. Ce
    # chokepoint alimente CR ET deck.
    try:
        if _entity_scope_obj is not None:
            from patches.entity_scope import lock_entity_in_titles as _lit
            _an_lock = (getattr(_entity_scope_obj, "analysis_entity", "") or "").strip()
            _rg_lock = (getattr(_entity_scope_obj, "registry_entity", "") or "").strip()
            if _an_lock and _rg_lock:
                outputs = {k: (_lit(v, _an_lock, _rg_lock) if isinstance(v, str) else v)
                           for k, v in outputs.items()}
    except Exception:
        pass

    inputs = {
        "brief":            brief,
        "temperature":      temperature,
        "max_tokens":       max_tokens,
        "attachments_meta": attachments_meta or {},
        "pappers_resolution_log": _pap_rlog.to_dict() if _pap_rlog else None,
        # B.1.3.13 (constat ChatGPT, cycle hybride #7) — le fingerprint n'était
        # exposé QUE dans le sous-dict b1_proof_layer ; les writers (Pappers
        # requalifié, Registry target, override Zone B) le lisent à la RACINE :
        # les wordings 3.10/3.12 étaient morts-nés. 6e bug « mauvais niveau ».
        "run_fingerprint": (
            _b1_result.get("run_fingerprint")
            if (isinstance(_b1_result, dict)
                and isinstance(_b1_result.get("run_fingerprint"), dict))
            else (_b1_result.get("fingerprint").to_dict()
                  if (_b1_result and _b1_result.get("fingerprint")
                      and hasattr(_b1_result.get("fingerprint"), "to_dict"))
                  else (_b1_result.get("fingerprint")
                        if (_b1_result
                            and isinstance(_b1_result.get("fingerprint"), dict))
                        else None))
        ),
        # M6-B B.1 (v17.4.0) — couche de preuve exposée (UI, débrief, B.4c)
        "b1_proof_layer": ({
            "analysis_context": (_b1_ctx.to_dict() if _b1_ctx is not None else None),
            "conflicts": [
                {"metric": _c.metric_canonical_id,
                 "severity": _c.conflict_severity,
                 "reason": _c.conflict_reason,
                 "resolution": _c.resolution,
                 "message": _c.user_visible_message,
                 "conflict_group_id": _c.conflict_group_id,
                 "competing_values": _c.competing_values}
                for _c in (_b1_conflicts or [])
            ],
            "fingerprint": (_b1_result.get("fingerprint").to_dict()
                            if (_b1_result and _b1_result.get("fingerprint")) else None),
            "coverage": (_b1_result.get("coverage") if _b1_result else {}),
            "signal_effective": _fin_signal_solid_effective,
            "signal_gate_reason": (_b1_result.get("signal_gate_reason", "")
                                   if _b1_result else ""),
        } if _b1_ctx is not None else None),
    }

    # v16.5.67.9 — Calcul anticipé de brief_mode pour alimentation de meta
    # (utilisé par app.py → extra_context → pptx_from_cr pour tag ⚠ pastilles GENERIC).
    # Le même _brief_mode_val est recalculé ligne ~3306 pour le scorer — c'est
    # intentionnel, le scorer vit dans un bloc try et pourrait ne pas s'exécuter.
    _brief_mode_for_meta = None
    if _briefcheck_result and isinstance(_briefcheck_result, dict):
        _bm_for_meta = _briefcheck_result.get("brief_mode") or {}
        _brief_mode_for_meta = _bm_for_meta.get("mode")

    meta = {
        "supply_chain_json": supply_chain_bundle.get("json"),
        "supply_chain_slide_flag": bool(supply_chain_bundle.get("slide_flag")),
        "supply_chain_source": supply_chain_bundle.get("source"),
        "supply_chain_warning": supply_chain_bundle.get("warning"),
        "supply_chain_status": supply_chain_bundle.get("status"),
        # Option B — v16.5.28 : JSON commercial extrait directement depuis Grok
        "commercial_json": commercial_json,
        # v16.5.67.9 — brief_mode propagé pour tagging visuel pastilles PPT GENERIC
        # (lu par app.py → extra_context → pptx_from_cr._slide_conclusion)
        "brief_mode": _brief_mode_for_meta,
    }

    # M6-A2.2.6 — masquage GÉNÉRAL des blocs JSON d'agent du CR métier final. Le deck
    # reçoit supply_chain_json / commercial_json via meta → extra_context (déjà extraits
    # ci-dessus), donc le livrable n'a plus besoin d'aucun bloc JSON brut. Corrige la
    # fuite du JSON commercial (opportunites/plan_actions/…) observée sur dossier industriel (composants) v2.
    outputs = {k: (_strip_agent_json_from_cr(v) if isinstance(v, str) else v)
               for k, v in outputs.items()}
    # ── M6-B B.1.3 — Completion gate : détecte les sorties tronquées
    # (plafond max_tokens, parenthèse ouverte, « TO BE » final), marque les
    # sections et remonte au livrable (bannière NON DISTRIBUABLE) + diag.
    _cg_lang = getattr(settings, "output_language", "fr") or "fr"
    _completion_issues = _completion_gate_outputs(outputs, lang=_cg_lang)
    # v62.13.1 — empty-emphasis fragments are deterministic corruption,
    # not missing prose. Remove them before any provider call, then run the
    # same completion gate again. This prevents a false RESOLVED diagnostic.
    _deterministic_completion_repairs = []
    try:
        for _ci in list(_completion_issues or []):
            if str(_ci.get("reason") or "") != "empty_emphasis":
                continue
            _sec = str(_ci.get("section") or "")
            _raw = strip_trunc_markers(str(outputs.get(_sec) or ""))
            _fixed = _repair_empty_emphasis_fragment(_raw)
            if _fixed and not _completion_issue_reason(_fixed):
                outputs[_sec] = _fixed
                _deterministic_completion_repairs.append(_sec)
        if _deterministic_completion_repairs:
            _completion_issues = _completion_gate_outputs(outputs, lang=_cg_lang)
            if diag_list is not None:
                diag_list.append({
                    "role": "completion_retry", "provider": "internal",
                    "model": "deterministic_empty_emphasis_v62131",
                    "status": "RESOLVED" if not _completion_issues else "PARTIAL",
                    "summary": (f"resolved={_deterministic_completion_repairs} "
                                f"persist={[i.get('section') for i in _completion_issues]}"),
                })
    except Exception:
        pass
    # ── B.1.3.12 — RÉGÉNÉRATION CIBLÉE (item prioritaire : 3 récidives
    # brief_codir:parenthese_ouverte_en_fin malgré la règle de clôture).
    # UN appel de continuation borné par section flaggée (max 2), fail-open
    # intégral, tracé au diag completion_retry. Le premier provider à clé
    # disponible est utilisé (anthropic > openai > google).
    if _completion_issues:
        _cr_pick = None
        try:
            for _cr_name, _cr_fn in (("anthropic", call_claude),
                                     ("openai", call_openai),
                                     ("google", call_gemini)):
                if _cr_fn is not None and _has_key(_cr_name):
                    _cr_pick = (_cr_name, _cr_fn)
                    break
        except Exception:
            _cr_pick = None
        if _cr_pick:
            _cr_name, _cr_fn = _cr_pick
            _cr_resolved, _cr_persist = [], []
            for _ci in list(_completion_issues)[:2]:
                _sec = str(_ci.get("section") or "")
                _txt = str(outputs.get(_sec) or "")
                if not _txt.strip():
                    _cr_persist.append(_ci)
                    continue
                _base_txt = strip_trunc_markers(_txt).strip()
                if str(_ci.get("reason") or "") == "empty_emphasis":
                    _base_txt = _repair_empty_emphasis_fragment(_base_txt)
                _tail = _base_txt[-700:]
                if _cg_lang == "en":
                    _cr_prompt = (
                        "The following section ending was cut mid-structure "
                        f"(reason: {_ci.get('reason','')}). Write ONLY the "
                        "missing ending (max 120 words): finish the sentence, "
                        "CLOSE every open parenthesis or quote, then stop. No "
                        "preamble, no JSON, do not repeat the given text.\n\n"
                        "--- SECTION ENDING ---\n" + _tail)
                    _cr_sys = "You complete truncated text. Output only the missing ending."
                else:
                    _cr_prompt = (
                        "La fin de section suivante est coupée en pleine "
                        f"structure (raison : {_ci.get('reason','')}). Écris "
                        "UNIQUEMENT la fin manquante (120 mots max) : termine "
                        "la phrase, FERME toute parenthèse ou guillemet "
                        "ouvert, puis arrête-toi. Sans préambule, sans JSON, "
                        "sans répéter le texte fourni.\n\n"
                        "--- FIN DE SECTION ---\n" + _tail)
                    _cr_sys = "Tu complètes un texte tronqué. Uniquement la fin manquante."
                try:
                    _cr_res = _safe_call(
                        _cr_name, _cr_fn, prompt=_cr_prompt, system=_cr_sys,
                        temperature=0.0, max_tokens=400,
                        model=_model_id_for(_cr_name, settings))
                    _cr_out = (_as_output(_cr_res) or "").strip()
                except Exception:
                    _cr_res, _cr_out = {"error": True}, ""
                if _cr_out and not _cr_res.get("error"):
                    _cand = (_base_txt.rstrip() + " " + _cr_out).strip()
                    if not _completion_issue_reason(_cand):
                        # B.1.3.16 — le marqueur posé à la coupure devient
                        # ORPHELIN une fois la section complétée : retiré.
                        outputs[_sec] = strip_trunc_markers(_cand)
                        _cr_resolved.append(_sec)
                        continue
                _cr_persist.append(_ci)
            if diag_list is not None:
                try:
                    diag_list.append({
                        "role": "completion_retry", "provider": _cr_name,
                        "model": "section_continuation_b1312",
                        "status": "ATTEMPTED",
                        "summary": (f"resolved={_cr_resolved} "
                                    f"persist={[c.get('section') for c in _cr_persist]}"),
                    })
                except Exception:
                    pass
            if _cr_resolved:
                _completion_issues = _completion_gate_outputs(outputs, lang=_cg_lang)
            # The diagnostic reflects the FINAL gate, not merely the model call.
            try:
                _remaining_sections = {str(i.get("section") or "") for i in (_completion_issues or [])}
                _resolved_final = [x for x in _cr_resolved if x not in _remaining_sections]
                _persist_final = [str(i.get("section") or "") for i in (_completion_issues or [])]
                for _row in reversed(diag_list or []):
                    if _row.get("role") == "completion_retry":
                        _row["status"] = ("RESOLVED" if not _persist_final else
                                          ("PARTIAL" if _resolved_final else "PERSISTS"))
                        _row["summary"] = f"resolved={_resolved_final} persist={_persist_final}"
                        break
            except Exception:
                pass
    # B.1.3.16 — FINAL HARD SCAN (ceinture, constat ChatGPT run 8) : si un
    # marqueur de troncature subsiste dans une sortie finale, la section est
    # (re)flaggée — le bandeau + usage bloqué suivent mécaniquement.
    try:
        _flagged_secs = {str(c.get("section") or "") for c in (_completion_issues or [])}
        for _fs_key, _fs_val in (outputs or {}).items():
            if (isinstance(_fs_val, str)
                    and (_TRUNC_MARK_FR in _fs_val or _TRUNC_MARK_EN in _fs_val)
                    and _fs_key not in _flagged_secs):
                _completion_issues.append(
                    {"section": _fs_key, "reason": "marker_in_final"})
    except Exception:
        pass
    # ── B.1.3.5 (audits dossier anglophone coté/dossier industriel (composants)) — les notes « ⚠ Entity validation /
    # Validation des entités » n'interrompent plus le corps métier :
    # collectées, dédupliquées, regroupées en UN bloc diagnostic en fin de
    # dernière section rendue. Le CSV garde le détail complet.
    try:
        _ev_rx = re.compile(
            r"(?m)^>?\s*⚠\s*(?:Entity validation|Validation des entités)[^\n]*\n?")
        _ev_collected = []
        for _k2, _v2 in list(outputs.items()):
            if not isinstance(_v2, str) or not _ev_rx.search(_v2):
                continue
            _ev_collected += [s.strip() for s in _ev_rx.findall(_v2)]
            outputs[_k2] = re.sub(r"\n{3,}", "\n\n", _ev_rx.sub("", _v2)).strip()
        if _ev_collected:
            _n_ev = 0
            for _s in _ev_collected:
                _m_ev = re.search(r"(\d+)\s+entit", _s)
                _n_ev += int(_m_ev.group(1)) if _m_ev else 0
            _ev_block = ((f"\n\n> ⚠ **Validation des entités (diagnostic regroupé)** : "
                          f"{_n_ev} entité(s) hors sources vérifiées détectée(s) au fil "
                          f"des sections (détail au CSV diagnostics) — à vérifier par "
                          f"le consultant avant diffusion.")
                         if _cg_lang == "fr" else
                         (f"\n\n> ⚠ **Entity validation (grouped diagnostic)**: "
                          f"{_n_ev} entit(y/ies) outside verified sources detected "
                          f"across sections (details in diagnostics CSV) — to be "
                          f"verified by the consultant before distribution."))
            # B.1.3.18 (run 10 ; dette UX présente aux runs 8/9/10) — le
            # diagnostic regroupé ne vit plus DANS le corps métier : clé
            # dédiée, rendue par l'app dans la zone Annexe du docx.
            outputs["entity_validation_annex"] = _ev_block.strip()
    except Exception:
        pass
    # ── B.1.3 (run dossier anglophone coté, requalifié) — CONFLIT écran/brief sur la langue.
    # L'écran l'emporte (contrat UI-1) mais un champ « Langue : Français »
    # dans le brief avec une sortie EN doit être SIGNALÉ, pas silencieux :
    # c'est ce silence qui a fait conclure l'auditeur à une régression.
    _language_conflict: Dict[str, str] = {}
    try:
        _blm = re.search(r"Langue\s*:\s*(Français|Francais|French|English|Anglais)",
                         brief or "", re.IGNORECASE)
        if _blm:
            _bl = ("fr" if _blm.group(1).lower().startswith(("fran", "fren"))
                   else "en")
            if _bl != (_cg_lang or "fr"):
                _language_conflict = {"brief": _bl, "active": _cg_lang,
                                      "source": "screen_selection"}
                diag_list.append({
                    "role": "language_conflict", "provider": "internal",
                    "model": "language_sync_b13", "status": "FLAGGED",
                    "summary": (f"brief={_bl} vs active={_cg_lang} "
                                f"(écran prime — contrat UI-1)"),
                })
    except Exception:
        pass
    if _completion_issues:
        diag_list.append({
            "role": "completion_gate", "provider": "internal",
            "model": "completion_gate_b13", "status": "FLAGGED",
            "summary": " | ".join(f"{i['section']}:{i['reason']}"
                                  for i in _completion_issues[:8]),
        })
        if logger:
            try:
                log_event(logger, "warning", "completion_gate",
                          "truncated_sections",
                          summary=f"n={len(_completion_issues)}")
            except Exception:
                pass
    # S.2.4.4 — en run FR, localise les résidus anglais des tableaux (table de faits
    # générée par le modèle). Borné aux lignes de tableau, donc sûr.
    if getattr(settings, "output_language", "fr") == "fr":
        outputs = {k: (_localize_en_table_cells_fr(v) if isinstance(v, str) else v)
                   for k, v in outputs.items()}
    # B.1.3.17 — miroir : en run EN, libellés structurels FR de la table
    # d'actions du registre (mêmes bornes lignes-tableau, même étage tardif).
    elif getattr(settings, "output_language", "fr") == "en":
        outputs = {k: (_localize_fr_table_cells_en(v) if isinstance(v, str) else v)
                   for k, v in outputs.items()}

    if logger:
        log_event(logger, "info", "codir_engine", "session_finished")

    role_results = [
        ("strategie",           strategie_res),
        ("brief_codir",         brief_codir_res),
        ("marketing",           marketing_res),
        ("finance",             finance_res_final),
        ("supply_chain", (
            {
                "provider": supply_chain_bundle.get("source", ""),
                "model":    supply_chain_bundle.get("source", ""),
                "error":    False,
                "attempt":  1,
                "duration_s": 0.0,
                "tokens":   {},
                "output":   supply_chain_txt,
                "raw":      {"warning": supply_chain_bundle.get("warning", "")},
            }
            if supply_chain_bundle.get("triggered")
            else {
                "provider": "", "model": "", "error": False,
                "attempt":  0,  "duration_s": 0, "tokens": {},
                "output":   "",
                "raw":      {"warning": "SC non pertinent"},
            }
        )),
        ("commercial",          commercial_res),
        ("synthese_decisions",  synthese_res),
        ("ceo",                 ceo_res),
    ]
    diagnostics_summary = []
    for k, v in role_results:
        if not isinstance(v, dict):
            continue
        diagnostics_summary.append({
            "role":       k,
            "provider":   v.get("provider", ""),
            "model":      v.get("model", ""),
            "status":     "OK" if not v.get("error") else "ERROR",
            "attempt":    v.get("attempt", ""),
            "duration_s": v.get("duration_s", ""),
            "tokens":     v.get("tokens", {}),
            "error":      (v.get("raw") or {}).get("exception", "") if v.get("error") and isinstance(v.get("raw"), dict) else (v.get("output", "") if v.get("error") else ""),
        })

    # ── v16.5.63 — Delivery confidence score ─────────────────────────────────
    # Mode v4 basique : sans métriques JSON typées dans les agents (livraison 2),
    # le score est calculé sur les signaux d'orchestration disponibles.
    # Le sous-score content_mix retombera sur LOW_METRIC_SAMPLE, ce qui plafonne
    # mécaniquement le score global ~60-65. C'est intentionnel — incitation à
    # fournir des pièces sources et à attendre la livraison 2 pour grimper plus haut.
    _confidence_score = None
    if _USE_CONFIDENCE and _compute_confidence is not None:
        try:
            # Signaux d'orchestration
            _red_alerts = 0
            _orange_alerts = 0
            _refusals = 0
            _rejected = 0
            _retries = 0
            for _d in diag_list or []:
                _status = str(_d.get("status", "")).upper()
                if _status == "ERROR":
                    _red_alerts += 1
                elif _status == "FLAGGED":
                    _orange_alerts += 1
                elif _status in ("SKIPPED",):
                    # skipped ≠ refusal : le pipeline a volontairement sauté ce rôle
                    pass
                # Détection refus textuel dans les outputs
                _out_text = str(_d.get("output", "") or "")
                if _out_text and re.search(
                    r"(je\s+ne\s+peux\s+pas\s+produire|impossibilit[ée]\s+de|"
                    r"cannot\s+(?:provide|produce|generate)|insufficient\s+data)",
                    _out_text, flags=re.IGNORECASE):
                    _refusals += 1
                _attempt = _d.get("attempt")
                if isinstance(_attempt, (int, float)) and _attempt > 1:
                    _retries += int(_attempt - 1)

            # v16.5.76 Phase 5 item 4 — Mécanisme de levée d'alertes orange par DAF
            # Si module patches.orange_alerts disponible ET company_name connue,
            # on filtre les alertes orange qui ont été résolues par un DAF
            # (justification écrite + initiales, stockées dans data/orange_alerts_resolved/)
            _orange_alerts_total_raw = _orange_alerts
            _orange_alerts_summary = None
            try:
                from patches.orange_alerts import count_unresolved_in_diag as _count_unresolved_oa
                _ws_company_name = ""
                if _company_profile is not None:
                    _ws_company_name = (getattr(_company_profile, "company_name_official", "") or "").strip()
                if _ws_company_name:
                    _unres, _total, _oa_summary = _count_unresolved_oa(
                        diag_list or [],
                        _ws_company_name,
                    )
                    if _total > 0:
                        # Mettre à jour le compteur pénalisé par le scorer
                        _orange_alerts = _unres
                        _orange_alerts_summary = _oa_summary
                        # Trace diag : liste des alertes résolues avec justification DAF
                        if diag_list is not None and _oa_summary.get("resolved_count", 0) > 0:
                            diag_list.append({
                                "role":         "orange_alerts_filter",
                                "provider":     "internal",
                                "model":        "orange_alerts_v1",
                                "status":       "OK",
                                "total_alerts": _oa_summary["total"],
                                "resolved_count": _oa_summary["resolved_count"],
                                "unresolved_count": _oa_summary["unresolved_count"],
                                "resolved_details_sample": _oa_summary["resolved_details"][:3],
                            })
                        if logger:
                            try:
                                log_event(logger, "info", "orange_alerts",
                                          f"company={_ws_company_name} total={_total} resolved={_oa_summary['resolved_count']} unresolved={_unres}")
                            except Exception:
                                pass
            except ImportError:
                # Module absent (env test léger) → fallback v75.5 : tous les FLAGGED comptent
                pass
            except Exception as _oa_err:
                if logger:
                    try:
                        log_event(logger, "warning", "orange_alerts",
                                  f"orange_alerts filter failed: {type(_oa_err).__name__}: {_oa_err}")
                    except Exception:
                        pass

            _bc_warn_banner = bool(
                _briefcheck_result
                and _briefcheck_result.get("doc_check", {}).get("severity") == "WARN_BANNER"
            )
            _fin_docs_attached = bool(
                _briefcheck_result
                and _briefcheck_result.get("doc_check", {}).get("has_financial_attachment")
            )
            # Patch v16.5.70.3 P0-1 — _attachments_count est désormais initialisé
            # PLUS HAUT (avant la règle prudence Source Quality, ligne ~3115)
            # pour éviter UnboundLocalError. Le bloc dupliqué ici a été supprimé
            # — une seule source de vérité pour la variable.

            _sector_unknown = True
            if _company_profile is not None:
                _nature = getattr(_company_profile, "nature", None) or ""
                _size   = getattr(_company_profile, "size", None) or ""
                try:
                    from patches import a1_probe as _a1p
                    _a1p.put(company_profile_size=_size or None)
                except Exception:
                    pass
                _sector_unknown = not (_nature and _size)

            _supply_ran     = bool(supply_chain_bundle.get("triggered"))
            _marketing_ran  = bool(marketing_txt) and not str(marketing_txt).startswith("[Rôle Marketing")
            _commercial_ran = bool(commercial_res and not (commercial_res or {}).get("error"))

            # v16.5.65 — Propagation du brief_mode au scorer (plafond automatique)
            _brief_mode_val = None
            _brief_mode_present = None
            if _briefcheck_result and isinstance(_briefcheck_result, dict):
                _bm = _briefcheck_result.get("brief_mode") or {}
                _brief_mode_val = _bm.get("mode")
                _brief_mode_present = _bm.get("present_count")

            # v16.5.66 — Collecte des metrics Finance (pilote livraison 2)
            # v16.5.76 Phase 4 — ÉTENDUE à tous les agents JSON-équipés.
            # Agents avec JSON agent_output_schema en v76 :
            #   - finance (pilote v66)
            #   - strategie, brief_codir, marketing, dg, synthese_decisions (v76 Phase 4)
            # Agents avec JSON métier propre (non agent_output_schema) :
            #   - commercial (COMMERCIAL_JSON_SCHEMA_HINT pour PPTX)
            #   - supply_chain (SC_JSON_SCHEMA_HINT pour le rendu métier)
            #   Ces 2 agents conservent leur format ; pas d'agrégation dans
            #   _all_metrics pour eux (risque double JSON perturbant le LLM).
            _all_metrics: list[dict] = []
            _agent_json_stats: dict[str, dict] = {}
            _finance_role_summary = None

            # Helper local : agrège claims + stats par agent (rétrocompatible)
            def _aggregate_agent_output(ao, role_key: str):
                if ao is None:
                    return
                try:
                    metrics = ao.to_scorer_metrics()
                    if metrics:
                        _all_metrics.extend(metrics)
                    _agent_json_stats[role_key] = {
                        "parse_status": ao.parse_status,
                        "claims_count": ao.claims_count,
                    }
                except Exception:
                    pass

            # Finance (rôle pilote depuis v66)
            if _finance_agent_output is not None:
                _aggregate_agent_output(_finance_agent_output, "finance")
                _finance_role_summary = _finance_agent_output.role_summary

            # v16.5.76 Phase 4 — 5 nouveaux agents JSON-équipés
            # Bloc try/except NameError pour défense en profondeur : si un
            # refactor futur supprime une variable, on dégrade gracieusement
            # au lieu de casser le run.
            try:
                _aggregate_agent_output(_strategie_agent_output, "strategie")
            except NameError:
                pass
            try:
                _aggregate_agent_output(_brief_codir_agent_output, "brief_codir")
            except NameError:
                pass
            try:
                _aggregate_agent_output(_marketing_agent_output, "marketing")
            except NameError:
                pass
            try:
                _aggregate_agent_output(_synthese_agent_output, "synthese_decisions")
            except NameError:
                pass
            try:
                _aggregate_agent_output(_dg_agent_output, "dg")
            except NameError:
                pass

            # Agents non-équipés agent_output_schema (commercial, supply_chain) :
            # conservent leur JSON métier dédié, ne contribuent pas à _all_metrics ici.

            # v16.5.66 — DAF checklist alimentée par role_summary si disponible,
            # sinon fallback sur le signal brut (pas d'erreur d'exécution Finance)
            _daf_checklist_ok: bool = not bool((finance_res_final or {}).get("error"))
            if (_finance_role_summary is not None
                    and _finance_role_summary.daf_checklist_complete is not None):
                _daf_checklist_ok = bool(_finance_role_summary.daf_checklist_complete)

            # owners_present : récupéré depuis role_summary Finance si présent
            # Since v16.5.67 — les autres agents l'alimenteront
            _owners_present: bool = False
            if (_finance_role_summary is not None
                    and _finance_role_summary.owners_assigned is True):
                _owners_present = True

            # recommended_option_present : idem
            _recommended_option_present: bool = False
            if (_finance_role_summary is not None
                    and _finance_role_summary.recommended_option):
                _recommended_option_present = True

            # ─────────────────────────────────────────────────────────────
            # v17.1-B1 — LEDGER CONSOLIDÉ UNIFIÉ (pivot Tranche B)
            # Promouvoir les FAITS financiers consolidés extraits par l'agent
            # finance dans la table de faits unique, puis enrichir l'entité
            # primaire du comparatif et rebâtir le bloc déterministe. Ce ledger
            # alimente ensuite deck + comparatif + valorisation (un seul cerveau).
            # ─────────────────────────────────────────────────────────────
            _consolidated_promoted = 0
            try:
                from patches.consolidated_ledger import (
                    promote_finance_facts as _promote_fin,
                    enrich_primary_entity_with_consolidated as _enrich_primary,
                )
                _fin_claims = (getattr(_finance_agent_output, "claims", None)
                               if "_finance_agent_output" in dir() and _finance_agent_output
                               else None)
                if _facts_table_built is not None and _fin_claims:
                    _consolidated_promoted = _promote_fin(_facts_table_built, _fin_claims)
                    # ── B.1.3.20 (P0-B, run dossier industriel) — RÉ-ANNOTATION PÉRIMÈTRE.
                    # Racine : la promotion ledger arrive APRÈS l'annotation
                    # B.1 → ses faits restaient MATCH_NA et se rendaient
                    # ✅ FAIT même en conflit (fait [CONSOLIDÉ] dans un run
                    # mono/social). Le fait Pappers social de dossier agroalimentaire,
                    # créé tôt, était lui bien annoté (⛔) — asymétrie
                    # d'ORDRE, pas de règle. On annote donc les promus
                    # contre le contexte d'analyse : le renderer unifié
                    # (⛔ HORS PÉRIMÈTRE — exclu du score) fait le reste.
                    if _consolidated_promoted:
                        try:
                            from patches.perimeter_match import (
                                annotate_facts_perimeter as _afp20)
                            try:
                                from patches.fact_identity import (
                                    canonical_metric_id as _cmi20)
                            except Exception:
                                _cmi20 = None
                            _ctx20 = None
                            try:
                                _ctx20 = (_b1_result or {}).get("context")
                            except Exception:
                                _ctx20 = None
                            _late20 = [f for f in (getattr(_facts_table_built,
                                                           "facts", []) or [])
                                       if getattr(f, "perimeter_match", None)
                                       in (None, "", "NA", "na")]
                            # même racine d'ordre : les faits tardifs n'avaient
                            # ni id canonique ni périmètre — les deux sont posés.
                            if _cmi20 is not None:
                                for _f20 in _late20:
                                    if not getattr(_f20, "metric_canonical_id", ""):
                                        try:
                                            _f20.metric_canonical_id = _cmi20(
                                                getattr(_f20, "label", "") or "")
                                        except Exception:
                                            pass
                            if _ctx20 is not None:
                                _afp20(_late20, _ctx20)
                        except Exception:
                            pass
                    if _consolidated_promoted:
                        # B1.1-02 — consolidé en tête du ledger (deck + markdown).
                        try:
                            _facts_table_built.sort_by_scope()
                        except Exception:
                            pass
                    if (_consolidated_promoted and "_pap_resolved_entities" in dir()
                            and _pap_resolved_entities
                            and _enrich_primary(_pap_resolved_entities, _facts_table_built)):
                        try:
                            from patches.mission_gates import build_comparison_block as _bcb2
                            if len(_pap_resolved_entities) >= 2:
                                _comparison_block_md = _bcb2(_pap_resolved_entities, lang=lang)
                        except Exception:
                            pass
                    if _consolidated_promoted and logger is not None:
                        log_event(logger, "info", "consolidated_ledger", "facts_promoted",
                                  detail=f"promoted={_consolidated_promoted} consolidated finance facts")

                # v17.1-B2.2 — SHAPER FINANCE GOUVERNÉ (mode AUTO, sans cible).
                # Comble le trou : les consolidés présents dans le tableau
                # comparatif NARRATIF mais absents de l'AGENT_JSON ne remontaient
                # pas au deck. Extraction déterministe (aucune valeur ni source
                # en dur) ; ne promeut que les faits CONSOLIDÉS sourcés. Pas de
                # dépendance à la résolution d'entité (toutes colonnes scannées,
                # seul le consolidé qualifie). Fail-open.
                try:
                    from patches.finance_shaper import promote_shaped_facts as _promote_shaped
                    if _facts_table_built is not None and finance_txt:
                        _shaped = _promote_shaped(_facts_table_built, finance_txt)  # target=None → auto
                        if _shaped:
                            try:
                                _facts_table_built.sort_by_scope()
                            except Exception:
                                pass
                            if logger is not None:
                                log_event(logger, "info", "finance_shaper", "shaped_facts_promoted",
                                          detail=f"promoted={_shaped} consolidated facts from narrative")
                except Exception as _she:
                    if logger is not None:
                        log_event(logger, "warning", "finance_shaper", "shaper_error",
                                  detail=f"{type(_she).__name__}: {_she}")

                # F.6.8 / F.6.7-05 — Promotion des faits NARRATIFS page-cités que
                # le shaper consolidé ne capte pas (entités sociales des filiales A et B,
                # comptes courants, produit exceptionnel, goodwill, provisions…).
                # Statut À VÉRIFIER + badge épistémique ESTIM-FILINGS : comble le
                # « narratif riche / ledger pauvre » sans mentir sur la provenance.
                try:
                    from patches.narrative_facts_promoter import (
                        promote_narrative_facts as _promote_narr)
                    if _facts_table_built is not None and finance_txt:
                        _narr_promoted = _promote_narr(
                            finance_txt, _facts_table_built,
                            allow_uncited=bool(str(attachments_block or "").strip()
                                               or str(financial_statements_block or "").strip()))
                        if _narr_promoted:
                            try:
                                _facts_table_built.sort_by_scope()
                            except Exception:
                                pass
                            if logger is not None:
                                log_event(logger, "info", "narrative_facts_promoter",
                                          "narrative_facts_promoted",
                                          detail=f"promoted={_narr_promoted} ESTIM-FILINGS facts")
                except Exception as _npe:
                    if logger is not None:
                        log_event(logger, "warning", "narrative_facts_promoter",
                                  "promoter_error", detail=f"{type(_npe).__name__}: {_npe}")

                # Cycle D — brique 1 : FIDÉLITÉ d'extraction ligne-à-ligne.
                # Après finalisation du ledger, on vérifie que chaque valeur de
                # fait est réellement présente (verbatim/normalisée) dans le
                # corpus source narratif (finance_txt). SIGNAL-ONLY : annote
                # .fidelity sans rien altérer ni supprimer. Une valeur non
                # retrouvée est un signal de prudence, pas un verdict (corpus
                # potentiellement partiel). Fail-open.
                try:
                    from patches.extraction_fidelity import fidelity_summary_dual as _fid_sum
                    # F.6.3-bis (audit) — le brief seul n'est PAS tout le corpus
                    # documentaire : les pièces jointes (attachments_block) et les
                    # états financiers (financial_statements_block) en font partie.
                    # Une valeur dans un PDF joint mais absente du brief serait
                    # faussement classée narrative_only. On confronte donc le
                    # corpus d'entrée COMPLET.
                    _input_corpus = "\n\n".join(
                        s for s in (brief, attachments_block, financial_statements_block)
                        if isinstance(s, str) and s.strip())
                    if _facts_table_built is not None and (_input_corpus or finance_txt):
                        _extraction_fidelity = _fid_sum(_facts_table_built, _input_corpus, finance_txt)
                        # F.6.6 — fidélité PER-PAGE : prouve que la valeur figure
                        # à LA page citée (source_doc/source_page), pas seulement
                        # dans le corpus concaténé. not_found_on_cited_page = mauvaise
                        # citation / hallucination de source.
                        try:
                            from patches.extraction_fidelity import per_page_summary as _pp_sum
                            if _input_corpus:
                                _extraction_fidelity["per_page"] = _pp_sum(
                                    _facts_table_built, _input_corpus)
                        except Exception:
                            pass
                        if _extraction_fidelity and logger is not None:
                            log_event(logger, "info", "extraction_fidelity", "line_by_line",
                                      detail=("verbatim={verbatim} normalized={normalized} "
                                              "not_found={not_found} narrative_only={narrative_only}"
                                              ).format(**_extraction_fidelity))
                except Exception as _fie:
                    if logger is not None:
                        log_event(logger, "warning", "extraction_fidelity", "fidelity_error",
                                  detail=f"{type(_fie).__name__}: {_fie}")
            except Exception as _bce:
                if logger is not None:
                    log_event(logger, "warning", "consolidated_ledger", "promote_error",
                              detail=f"{type(_bce).__name__}: {_bce}")

            _run_ctx = {
                # v16.5.66 — le scorer lit enfin de vraies metrics
                "all_metrics": _all_metrics,
                "attachments": [],  # reclassification des sources côté pipeline
                # Patch v16.5.71.1 P0 (audit ChatGPT round 9) — Anti-régression scorer
                # Bug : v16.5.71 corrigeait le prompt Finance (bridé/non bridé) via
                # _has_some_financial_signal, mais le scorer continuait à pénaliser
                # MISSING_FINANCIAL_DOCS si _fin_docs_attached était False et qu'il
                # n'y avait pas de bundle PDF FS. Conséquence : sur dossier réseau de soins Excel,
                # le rapport pouvait utiliser les chiffres mais le score disait
                # "pièces financières insuffisantes" → incohérence livrable.
                # Fix : financial_docs_attached = OR des 3 sources possibles.
                "financial_docs_attached": (
                    _fin_docs_attached
                    or any(
                        getattr(b, "financial_statements_detected", False)
                        for b in (financial_statements_bundles or [])
                    )
                    # M6-B B.1 — signal EFFECTIF (porte de périmètre) : un
                    # signal porté uniquement par des faits MISMATCH (dossier industriel (composants)
                    # v5) n'alimente plus le score. Valeur brute journalisée.
                    or _fin_signal_solid_effective
                ),
                "internal_docs_count":     _attachments_count,
                # Since v16.5.70 — Sous-flags étendus pour scoring documentaire fin
                "financial_statements_detected": (
                    any(
                        getattr(b, "financial_statements_detected", False)
                        for b in (financial_statements_bundles or [])
                    ) if financial_statements_bundles else None
                ),
                # M6-C — signal booleen SANS ambiguite (jamais None) : le bloc de
                # comptes structure est-il vide ? Sert au cap d'honnetete du score.
                # (financial_statements_detected vaut None quand il n'y a pas de
                # bundles, ce qui ne declenchait pas le cap None-safe.)
                "financial_statements_block_empty": (
                    not bool((financial_statements_block or "").strip())
                ),
                "financial_tables_extracted": (
                    bool(financial_statements_block.strip())
                    if financial_statements_block else None
                ),
                "n_pdfs_with_fs": sum(
                    1 for b in (financial_statements_bundles or [])
                    if getattr(b, "financial_statements_detected", False)
                ) if financial_statements_bundles else 0,
                # Patch v16.5.71.1 P0 — Nouveaux signaux multi-format pour traçabilité
                # M6-B B.1 — la valeur EFFECTIVE (porte de périmètre) pilote le
                # scorer ; la valeur BRUTE du détecteur reste exposée pour audit.
                "financial_signal_in_attachments_solid": _fin_signal_solid_effective,
                "financial_signal_raw_solid": (
                    _financial_signal_report.financial_signal_solid
                    if _financial_signal_report else False
                ),
                "financial_signal_score": (
                    _financial_signal_report.confidence_score
                    if _financial_signal_report else None
                ),
                "financial_signal_keywords": (
                    _financial_signal_report.n_keywords
                    if _financial_signal_report else 0
                ),
                "financial_signal_amounts": (
                    _financial_signal_report.n_amounts
                    if _financial_signal_report else 0
                ),
                "red_alerts_unresolved":   _red_alerts,
                "orange_alerts_unresolved": _orange_alerts,
                "unresolved_conflicts":    0,
                "retry_count_total":       _retries,
                "agent_refusals_count":    _refusals,
                "rejected_outputs_count":  _rejected,
                "sector_unknown":          _sector_unknown,
                "benchmark_available":     not _sector_unknown,
                # v16.5.65 — brief mode pour plafond mécanique
                "brief_mode":              _brief_mode_val,
                "brief_mode_present_count": _brief_mode_present,
                # v62.3 — autorité structurée pour le profil de preuve/utilité.
                # Le score secondaire ne repose plus sur des regex fragiles.
                "agenda_genre":            getattr(_genre, "genre", None),
                "decision_mode":           getattr(_genre, "decision_mode", None),
                "finance_tone":            getattr(_genre, "finance_tone", None),
                "agenda_genre_confidence": getattr(_genre, "confidence", None),
                "agenda_components":       list(getattr(_genre, "components", []) or []),
                # v16.5.66 — statuts parsing JSON agents (pour pénalités MISSING_AGENT_JSON_CLAIMS)
                "agent_json_stats":        _agent_json_stats,
                "completeness_checks": {
                    "daf_checklist_complete":        _daf_checklist_ok,
                    "supply_present_if_triggered":   _supply_ran or not _supply_ran,
                    "cmo_present_if_triggered":      _marketing_ran,
                    "commercial_present_if_triggered": _commercial_ran,
                    # v16.5.66 — alimentés par Finance role_summary (autres agents en v16.5.67)
                    "owners_present":                _owners_present,
                    "recommended_option_present":    _recommended_option_present,
                    "primary_growth_driver_present": False,  # v16.5.67 (marketing)
                    "execution_risk_present":        False,  # v16.5.67 (commercial)
                },
            }
            # v17.1-B2.2 — capture du statut scorer pour l'invariant deck
            # (« pas de Traçabilité 100/100 si le scorer n'a pas tourné »).
            _scorer_ok = True
            try:
                _confidence_score = _compute_confidence(_run_ctx, previous_score=None, lang=lang)
                # B.1.3.16 (runs 7/8 : « Signal richness » affichait le
                # fallback source_quality) — le VRAI score de signal est
                # exposé AU NIVEAU lu par le rendu.
                try:
                    _confidence_score["financial_signal_score"] = (
                        _financial_signal_report.confidence_score
                        if _financial_signal_report else None)
                except Exception:
                    pass
                try:
                    from patches import a1_probe as _a1p
                    import os as _os_a1
                    _cs = _confidence_score or {}
                    # probe.4 — la clé réelle des sous-scores est "component_scores"
                    # (et non "subscores"/"sub_scores") → source_quality remontait None.
                    _sub = (_cs.get("component_scores") or _cs.get("subscores")
                            or _cs.get("sub_scores") or {}) if isinstance(_cs, dict) else {}
                    _sq = (_sub.get("source_quality") if isinstance(_sub, dict) else None)
                    if _sq is None and isinstance(_cs, dict):
                        _sq = _cs.get("source_quality")
                    _gr = _cs.get("grade") if isinstance(_cs, dict) else None
                    # probe.4 — date du run, distincte de analysis_as_of_date /
                    # latest_accounts_date, pour rendre lisible la pollution temporelle.
                    try:
                        _run_as_of = (_run_now.date().isoformat()
                                      if "_run_now" in locals() else "")
                    except Exception:
                        _run_as_of = ""
                    _a1p.put(source_quality=_sq, grade=_gr, run_as_of_date=_run_as_of)
                    _a1p.flush(diag_list=diag_list,
                               out_dir=_os_a1.getenv("CODIR_A1_PROBE_DIR") or None,
                               lang=lang)
                except Exception:
                    pass
            except Exception as _sc_err:
                _scorer_ok = False
                _confidence_score = None
                if logger is not None:
                    log_event(logger, "warning", "confidence_score", "scorer_failed",
                              detail=f"{type(_sc_err).__name__}: {_sc_err}")

            # v17.1 — Gardes mission (fail-open) : scrub juridique non étayé,
            # couverture du brief (multi-SIREN / comparatif), plafonnement du
            # grade selon le risque mission. N'altère JAMAIS le run si le module
            # est absent ou lève une exception.
            _mission_gates_report = None
            try:
                from patches.mission_gates import (
                    run_mission_gates as _run_mission_gates,
                    build_legal_evidence_from_facts as _build_legal_evidence,
                    comparison_metrics_filled_ratio as _cmp_filled_ratio,
                )
                _agent_outputs_for_gates = {
                    "strategie": strategie_res,
                    "brief_codir": brief_codir_res,
                    "marketing": marketing_res,
                    "finance": finance_res_final,
                    "commercial": commercial_res,
                    "synthese_decisions": synthese_res,
                    "ceo": ceo_res,
                }
                # v17.1-A2 — legal_evidence nourri depuis la table de faits
                # Couche 1 (disponible en amont). Une alerte L.225-248 légitime
                # peut désormais passer si capitaux propres SOCIAUX + capital
                # social sont sourcés ; sinon scrub conservateur par défaut.
                _legal_ev = {}
                try:
                    # v62.13.9.4.44 — CONTRAT SUR TOUT LE CYCLE DE VIE (M1-03). Après le
                    # constructeur, la table reçoit des faits de liasse, du brief, et des
                    # promotions issues de la note Finance. Le validateur commun et la garde
                    # d'extrait repassent ICI, après la dernière mutation et avant tout usage
                    # de la table par le compte rendu, le diagnostic et les exports.
                    try:
                        if _facts_table_built is not None and getattr(_facts_table_built, "facts", None):
                            from utils.fact_contract42 import enforce_fact_contract42 as _efc44
                            from utils.financial_facts_table import _enforce_excerpt_supports_value41 as _eex44
                            _c44 = _efc44(_facts_table_built.facts, locals().get("financial_statements_block") or "")
                            _g44 = _eex44(_facts_table_built.facts)
                            try:
                                _facts_table_built.diag = dict(getattr(_facts_table_built, "diag", {}) or {})
                                _facts_table_built.diag["fact_contract_final_pass"] = {"rules": _c44, "excerpt_guard": _g44}
                            except Exception:
                                pass
                    except Exception:
                        pass
                    if _facts_table_built is not None and getattr(_facts_table_built, "facts", None):
                        _legal_ev = _build_legal_evidence(_facts_table_built.facts)
                except Exception:
                    _legal_ev = {}
                # v62.12.2 — le mission gate consomme la vérité financière
                # FINALE, pas le seul état du ledger. La date du dépôt registre,
                # les conflits courants et la période critique confirmée sont
                # réconciliés avant de prononcer MISSION-GRADE.
                _cfse = None
                _pre_mission_truth62122 = {}
                try:
                    from utils.current_financial_truth_guard import (
                        compute_final_current_financial_truth as _compute_truth62122,
                        apply_final_truth_to_temporal_frame as _apply_tf_truth62122,
                    )
                    _pre_mission_truth62122 = _compute_truth62122(
                        facts_table=_facts_table_built,
                        temporal_frame=_temporal_frame_obj,
                        mission_report=None,
                        financial_signal_solid=bool(_fin_signal_solid_effective),
                    )
                    _cfse = bool(_pre_mission_truth62122.get(
                        "current_financial_state_established"))
                    _apply_tf_truth62122(
                        _temporal_frame_obj, _pre_mission_truth62122, lang=lang)
                except Exception:
                    _cfse = None
                _mg = _run_mission_gates(
                    current_financial_state_established=_cfse,
                    brief=brief,
                    agent_outputs=_agent_outputs_for_gates,
                    confidence_result=_confidence_score,
                    legal_evidence=_legal_ev,
                    primary_resolved_sirens=(_pap_resolved_sirens
                                             if "_pap_resolved_sirens" in dir() else []),
                    entity_names=([e.get("name") for e in _pap_resolved_entities]
                                  if "_pap_resolved_entities" in dir() else None),
                    engine_comparison=bool("_comparison_block_md" in dir()
                                           and _comparison_block_md),
                    comparison_sparse=bool(
                        "_pap_resolved_entities" in dir() and _pap_resolved_entities
                        and _cmp_filled_ratio(_pap_resolved_entities) < 0.5),
                    run_date=(_run_date_iso if "_run_date_iso" in dir() else None),
                    # v62.13.9.4.36 — le MODE effectif du run (mono-entité) doit atteindre
                    # le gate de couverture : sans lui, deux SIREN cités dans le brief
                    # suffisaient à déduire un comparatif inter-sociétés jamais demandé.
                    analysis_mode=(getattr(_b1_ctx, "mode", None)
                                   if "_b1_ctx" in dir() and _b1_ctx is not None else None),
                )
                # A4.2-03 — bloc comparatif déterministe visible dans le livrable.
                if "_comparison_block_md" in dir() and _comparison_block_md:
                    for _tgt in (ceo_res, synthese_res):
                        if isinstance(_tgt, dict):
                            _tgt["output"] = (_comparison_block_md + "\n\n"
                                              + str(_tgt.get("output", "") or ""))
                            break
                _confidence_score = _mg["confidence"]
                _mission_gates_report = {
                    "mission_status": _mg["mission_status"],
                    "risk_flags": _mg["risk_flags"],
                    "legal_scrubs": _mg["legal_scrubs"],
                    "scope_math_neutralized": _mg.get("scope_math_neutralized", 0),
                    "coverage": _mg["coverage"],
                    "coverage_markdown": _mg.get("coverage_markdown", ""),
                }
                # v17.1-A3 — « Couverture du brief » visible dans le livrable
                # (No silent drop : rapport + deck, pas seulement diagnostic).
                _cov_md = _mg.get("coverage_markdown", "")
                if _cov_md and _mg.get("coverage", {}).get("requirements"):
                    for _tgt in (ceo_res, synthese_res):
                        if isinstance(_tgt, dict):
                            _tgt["output"] = (_cov_md + "\n\n"
                                              + str(_tgt.get("output", "") or ""))
                            break
                # B.1.3.56 (scope B) — le verdict mission n'est JAMAIS
                # uniquement dans le CSV : bandeau statut + raisons injecté en
                # tête du livrable (dernier préfixe = premier affiché). En cas
                # d'échec du builder, un bandeau minimal garantit la visibilité.
                _mission_lang = getattr(settings, "output_language", "fr") \
                    if "settings" in dir() else "fr"
                # B.1.3.56 (gate ChatGPT 3.3-3.5) — verdict mission de bout en
                # bout : un statut dur bloque le run via le CANAL UNIQUE
                # confidence_score (bandeau DOCX + slide confiance + usages
                # client/conseil/diffusion BLOQUÉS + run_validatable=False).
                # Le blocage dépend du STATUT, jamais du succès du builder de
                # bandeau : fail-closed par construction.
                _mission_hard_block = bool(str(_mg.get("mission_status", "")
                                               ).upper().startswith("NON MISSION-GRADE"))
                if _mission_hard_block:
                    try:
                        from patches.mission_gates import _FLAG_LABELS as _mfl
                        _mlang = "en" if str(_mission_lang).startswith("en") else "fr"
                        _cs56 = _confidence_score if isinstance(_confidence_score, dict) else {}
                        _cs56["run_not_validatable"] = True
                        _cs56["mission_status"] = _mg.get("mission_status", "")
                        _rs56 = _cs56.setdefault("run_block_reasons", [])
                        for _fl in (_mg.get("risk_flags") or []):
                            _mlbl56 = _mfl.get(_mlang, {}).get(str(_fl), str(_fl))
                            if _mlbl56 not in _rs56:
                                _rs56.append(_mlbl56)
                        _confidence_score = _cs56
                    except Exception:
                        pass
                try:
                    from patches.mission_gates import (
                        build_mission_status_markdown as _bmsm)
                    _mission_md = _bmsm(_mg, lang=_mission_lang)
                except Exception as _bmsm_exc:
                    _st = _mg.get("mission_status", "")
                    _mission_md = ("" if (not _st or _st == "MISSION-GRADE")
                                   else (f"## ⛔ Mission status: {_st}"
                                         if str(_mission_lang).startswith("en")
                                         else f"## ⛔ Statut mission : {_st}"))
                    if diag_list is not None:
                        diag_list.append({
                            "role": "mission_status_banner", "provider": "internal",
                            "model": "mission_banner_b1356", "status": "ERROR",
                            "error": f"{type(_bmsm_exc).__name__}: {str(_bmsm_exc)[:160]}",
                            "summary": "bandeau minimal de secours rendu ; "
                                       "blocage dur inchangé (fail-closed)",
                        })
                if _mission_md:
                    # B.1.3.56 correctif P1-B56-03 — la carte `outputs` est la
                    # source RÉELLEMENT rendue (construite avant ce bloc) : le
                    # détail mission y est préfixé directement ; les objets raw
                    # ceo_res/synthese_res sont synchronisés SECONDAIREMENT
                    # (les deux, plus de break). Garde anti-double bandeau.
                    for _ok in ("direction_generale", "synthese_decisions",
                                "ceo"):
                        _ov = outputs.get(_ok)
                        if isinstance(_ov, str) and not _ov.lstrip().startswith(
                                ("## ⛔ Statut mission",
                                 "## ⛔ Mission status")):
                            outputs[_ok] = _mission_md + "\n\n" + _ov
                    for _tgt in (ceo_res, synthese_res):
                        if isinstance(_tgt, dict):
                            _traw = str(_tgt.get("output", "") or "")
                            if not _traw.lstrip().startswith(
                                    ("## ⛔ Statut mission",
                                     "## ⛔ Mission status")):
                                _tgt["output"] = _mission_md + "\n\n" + _traw
                if diag_list is not None:
                    diag_list.append({
                        "role": "mission_gates",
                        "provider": "internal",
                        "model": "mission_gates_v1",
                        "status": _mg["mission_status"],
                        "flagged": _mg["risk_flags"],
                        "summary": (f"legal_scrubs={_mg['legal_scrubs']} | "
                                    f"comparatif={_mg['coverage'].get('comparison_requested')} "
                                    f"exécuté={_mg['coverage'].get('comparison_executed')}"),
                    })
                if logger:
                    log_event(logger, "info", "mission_gates",
                              f"status={_mg['mission_status']} flags={_mg['risk_flags']} "
                              f"score={_confidence_score['score']} grade={_confidence_score['grade']}")
            except Exception as _mg_exc:
                # B.1.3.56 correctif P0-B56-01 — FAIL-CLOSED : pour un garde de
                # vérité, une panne ne peut pas signifier « aucune alerte ».
                # Toute exception du Mission Gate invalide le run, bloque les
                # usages client/conseil/diffusion et laisse une raison visible
                # FR/EN + un diagnostic structuré.
                _mission_hard_block = True
                try:
                    # La langue du RUN est l'autorité. Ne jamais relire les
                    # réglages disque dans un chemin d'erreur : ils peuvent avoir
                    # changé depuis le démarrage de la session et produire un
                    # bandeau FR dans un run EN (ou l'inverse).
                    _mgl = getattr(settings, "output_language", "fr") \
                        if "settings" in dir() else "fr"
                except Exception:
                    _mgl = "fr"
                _mgl_en = str(_mgl or "fr").lower().startswith("en")
                _mg_reason = (
                    "Mission Gate error — truth not evaluated (fail-closed): "
                    if _mgl_en else
                    "Mission Gate en erreur — vérité non évaluée "
                    "(fail-closed) : ") + f"{type(_mg_exc).__name__}"
                _mission_gates_report = {
                    "mission_status": "MISSION_GATE_ERROR",
                    "risk_flags": ["MISSION_GATE_ERROR"],
                    "error": f"{type(_mg_exc).__name__}: {str(_mg_exc)[:200]}",
                }
                try:
                    if isinstance(_confidence_score, dict):
                        _confidence_score["run_not_validatable"] = True
                        _confidence_score["mission_status"] = (
                            "MISSION_GATE_ERROR")
                        _rbr = list(_confidence_score.get(
                            "run_block_reasons") or [])
                        if _mg_reason not in _rbr:
                            _rbr.append(_mg_reason)
                        _confidence_score["run_block_reasons"] = _rbr
                except Exception:
                    pass
                try:
                    _mg_banner = (
                        ("## ⛔ Mission status: MISSION_GATE_ERROR\n\n"
                         "- " + _mg_reason + "\n"
                         "- Client presentation, board and external "
                         "distribution BLOCKED — supervised internal use "
                         "only.") if _mgl_en else
                        ("## ⛔ Statut mission : MISSION_GATE_ERROR\n\n"
                         "- " + _mg_reason + "\n"
                         "- Présentation client, conseil et diffusion externe "
                         "BLOQUÉS — usage interne supervisé uniquement."))
                    for _ok in ("direction_generale", "synthese_decisions",
                                "ceo"):
                        _ov = outputs.get(_ok)
                        if isinstance(_ov, str) and not _ov.lstrip().startswith(
                                ("## ⛔ Statut mission",
                                 "## ⛔ Mission status")):
                            outputs[_ok] = _mg_banner + "\n\n" + _ov
                    for _tgt in (ceo_res, synthese_res):
                        if isinstance(_tgt, dict):
                            _traw = str(_tgt.get("output", "") or "")
                            if not _traw.lstrip().startswith(
                                    ("## ⛔ Statut mission",
                                     "## ⛔ Mission status")):
                                _tgt["output"] = _mg_banner + "\n\n" + _traw
                except Exception:
                    pass
                if diag_list is not None:
                    diag_list.append({
                        "role": "mission_gates", "provider": "internal",
                        "model": "mission_gates_v1", "status": "ERROR",
                        "error": f"{type(_mg_exc).__name__}: "
                                 f"{str(_mg_exc)[:160]}",
                        "summary": "MISSION_GATE_ERROR — run invalidé "
                                   "(fail-closed)",
                    })
                if logger:
                    log_event(logger, "warning", "mission_gates",
                              f"MISSION_GATE_ERROR (fail-closed): {_mg_exc}")

            # v62.11 — authoritative page-confirmed ledger reconciliation.
            # This is the last common point before usefulness, Word and PPTX.
            _financial_proof_layer_report = {}
            try:
                from utils.financial_proof_layer import (
                    quarantine_conflicting_ledger_facts as _qclf6211,
                    update_temporal_frame_from_ledger as _utfl6211,
                    reconcile_financial_narrative as _rfn6211,
                )
                _qrep6211 = _qclf6211(_facts_table_built)
                _temporal_frame_obj = _utfl6211(
                    _temporal_frame_obj, _facts_table_built, lang=lang)
                outputs, _nrep6211 = _rfn6211(
                    outputs, _facts_table_built, lang=lang)
                _financial_proof_layer_report = {**_qrep6211, **_nrep6211}
                if isinstance(synthese_res, dict):
                    synthese_res["output"] = str(outputs.get("synthese_decisions", "") or "")
                if isinstance(ceo_res, dict):
                    ceo_res["output"] = str(
                        outputs.get("ceo") or outputs.get("direction_generale") or "")
                if diag_list is not None:
                    diag_list.append({
                        "role": "financial_proof_layer", "provider": "internal",
                        "model": "financial_proof_layer_v6212",
                        "status": ("OK" if _financial_proof_layer_report.get(
                            "current_financial_state_established") else "DEGRADED"),
                        **_financial_proof_layer_report,
                    })
            except Exception as _fpl_exc6211:
                _financial_proof_layer_report = {
                    "status": "ERROR",
                    "error": f"{type(_fpl_exc6211).__name__}: {str(_fpl_exc6211)[:160]}",
                    "current_financial_state_established": False,
                }
                if diag_list is not None:
                    diag_list.append({
                        "role": "financial_proof_layer", "provider": "internal",
                        "model": "financial_proof_layer_v6212",
                        **_financial_proof_layer_report,
                    })

            # v62.10.2 — FAIL-CLOSED « situation financière actuelle ».
            # Le run dossier anglophone coté .62.10.1 savait que le dépôt registre le plus
            # récent n'était pas parsé, portait un HARD_METRIC_SCOPE_CONFLICT
            # et zéro fait critique page-confirmé, mais promouvait malgré tout
            # une situation chiffrée. Tant que v62.11 n'a pas construit le
            # ledger page-confirmé, les surfaces exécutives sont gouvernées ici.
            _current_financial_truth_report = {}
            try:
                # La période effectivement utilisée doit être connue AVANT le
                # calcul de l'utilité, sinon le cap arriverait trop tard.
                if (_temporal_frame_obj is not None and
                        not bool((_financial_proof_layer_report or {}).get(
                            "current_financial_state_established"))):
                    try:
                        from patches.temporal_frame import attach_parsed_financial_period as _apfp62102
                        _temporal_frame_obj = _apfp62102(
                            _temporal_frame_obj, outputs, lang=lang)
                    except Exception:
                        pass
                from utils.current_financial_truth_guard import (
                    govern_current_financial_truth as _gcft62102,
                    apply_truth_caps as _auc62102,
                )
                outputs, _current_financial_truth_report = _gcft62102(
                    outputs,
                    facts_table=_facts_table_built,
                    extraction_fidelity=_extraction_fidelity,
                    mission_report=_mission_gates_report,
                    temporal_frame=_temporal_frame_obj,
                    finance_tone=str(getattr(_genre, "finance_tone", "") or ""),
                    financial_signal_solid=bool(_fin_signal_solid_effective),
                    lang=lang,
                )
                _auc62102(_confidence_score, _current_financial_truth_report,
                             lang=lang)
                # v62.12.2 — une seule vérité finale sur toutes les surfaces.
                try:
                    from utils.current_financial_truth_guard import (
                        apply_final_truth_to_temporal_frame as _apply_final_tf62122)
                    _apply_final_tf62122(
                        _temporal_frame_obj, _current_financial_truth_report,
                        lang=lang)
                    if isinstance(_mission_gates_report, dict) and not bool(
                            _current_financial_truth_report.get(
                                "current_financial_state_established")):
                        _ms = str(_mission_gates_report.get("mission_status") or "")
                        if _ms == "MISSION-GRADE":
                            _mission_gates_report["mission_status"] = (
                                "MISSION-GRADE WITH RESERVATIONS"
                                if str(lang).lower().startswith("en") else
                                "MISSION-GRADE AVEC RÉSERVES")
                        _mission_gates_report["current_financial_truth"] = dict(
                            _current_financial_truth_report)
                        # Le bandeau mission a pu être injecté avant le truth
                        # guard ; réconcilier aussi les textes déjà produits.
                        import re as _re_mission62122
                        for _ok62122, _ov62122 in list(outputs.items()):
                            if not isinstance(_ov62122, str):
                                continue
                            _nv62122 = _re_mission62122.sub(
                                r"(Mission status\s*:\s*)MISSION-GRADE(?!\s+WITH)",
                                r"\1MISSION-GRADE WITH RESERVATIONS",
                                _ov62122, flags=_re_mission62122.I)
                            _nv62122 = _re_mission62122.sub(
                                r"(Statut mission\s*:\s*)MISSION-GRADE(?!\s+AVEC)",
                                r"\1MISSION-GRADE AVEC RÉSERVES",
                                _nv62122, flags=_re_mission62122.I)
                            outputs[_ok62122] = _nv62122
                        # Reconcile the already-emitted diagnostics row as well:
                        # CSV, report and mission object must expose one status.
                        if diag_list is not None and _ms == "MISSION-GRADE":
                            for _mr62122 in reversed(diag_list):
                                if (_mr62122.get("role") == "mission_gates"
                                        and _mr62122.get("status") == "MISSION-GRADE"):
                                    _mr62122["status"] = _mission_gates_report.get(
                                        "mission_status")
                                    _mr62122["current_financial_truth_reconciled"] = True
                                    _mr62122["current_financial_state_established"] = False
                                    break
                except Exception:
                    pass
                if _current_financial_truth_report.get("applied") and diag_list is not None:
                    diag_list.append({
                        "role": "current_financial_truth_guard",
                        "provider": "internal",
                        "model": "current_financial_truth_guard_v621132",
                        "status": "CURRENT_FINANCIAL_STATE_WITHHELD",
                        **_current_financial_truth_report,
                    })
            except Exception as _cft_exc62102:
                # Fail closed in BOARD_SCRUTINY: a broken truth guard cannot
                # silently permit quantified current-state claims.
                _current_financial_truth_report = {
                    "applied": True, "status": "FAILED_CLOSED",
                    "error": f"{type(_cft_exc62102).__name__}: {str(_cft_exc62102)[:160]}",
                    "usefulness_cap": 44,
                }
                try:
                    _cft_msg62102 = (
                        "CURRENT FINANCIAL POSITION NOT ESTABLISHED — truth guard unavailable; CFO/auditor review required."
                        if str(lang or "fr").lower().startswith("en") else
                        "SITUATION FINANCIÈRE ACTUELLE NON ÉTABLIE — garde de vérité indisponible ; revue DAF/CAC requise.")
                    if str(getattr(_genre, "finance_tone", "") or "").upper() == "BOARD_SCRUTINY":
                        for _k62102, _v62102 in list(outputs.items()):
                            if isinstance(_v62102, str) and _v62102:
                                outputs[_k62102] = _cft_msg62102 + "\n\n" + _v62102
                    from utils.current_financial_truth_guard import apply_truth_caps as _aucf62102
                    _aucf62102(_confidence_score, _current_financial_truth_report,
                               lang=lang)
                except Exception:
                    pass
                if diag_list is not None:
                    diag_list.append({
                        "role": "current_financial_truth_guard",
                        "provider": "internal",
                        "model": "current_financial_truth_guard_v621132",
                        "status": "FAILED_CLOSED",
                        **_current_financial_truth_report,
                    })

            # v62.3 — double lecture honnête : le score historique reste la
            # solidité probatoire ; un second indicateur mesure l'utilité du
            # document de travail pour le point d'agenda. Aucun bonus tardif,
            # aucun re-grade du score de preuve, aucune autorisation externe.
            try:
                from utils.decision_relative_confidence import (
                    attach_decision_usefulness as _attach_decision_usefulness)
                _attach_decision_usefulness(
                    _confidence_score, _run_ctx, brief_text=str(brief or ""),
                    lang=lang)
                if diag_list is not None and isinstance(_confidence_score, dict):
                    _du = _confidence_score.get("decision_usefulness") or {}
                    diag_list.append({
                        "role": "decision_usefulness",
                        "provider": "internal",
                        "model": "decision_usefulness_v623",
                        "status": f"BAND_{_du.get('band', '?')}",
                        "score": _du.get("score"),
                        "evidence_score": _confidence_score.get("score"),
                        "profile": _du.get("profile"),
                        "agenda_genre": _du.get("agenda_genre"),
                        "decision_mode": _du.get("decision_mode"),
                        "proof_score_unchanged": _du.get("proof_score_unchanged"),
                    })
            except Exception as _du_exc:
                if logger is not None:
                    log_event(logger, "warning", "decision_usefulness",
                              f"secondary score unavailable: {_du_exc}")

            # v17.1-A2 — Valorisation MULTI-MÉTHODES « à la demande » (fail-open).
            # Déclenchée uniquement si le brief le demande (valoris/DCF/multiples/
            # combien vaut…). Utilise les faits Couche 1 disponibles ; balise toute
            # hypothèse ; refuse la DCF sur FCF négatifs/absents (leçon Lhyfe).
            _valuation_report = None
            try:
                from patches.valuation_modeler import run_valuation_on_demand as _run_valuation
                _facts_for_valo = (getattr(_facts_table_built, "facts", None)
                                   if _facts_table_built is not None else None) or []
                _valuation_report = _run_valuation(brief=brief, facts=_facts_for_valo)
                if _valuation_report is not None:
                    # Injecte la section valo dans le livrable (sortie CEO/synthèse).
                    _valo_md = _valuation_report.get("markdown", "")
                    for _tgt in (ceo_res, synthese_res):
                        if isinstance(_tgt, dict) and _valo_md:
                            _tgt["output"] = (str(_tgt.get("output", "") or "")
                                              + "\n\n" + _valo_md)
                            break
                    if diag_list is not None:
                        _s = _valuation_report.get("summary", {})
                        diag_list.append({
                            "role": "valuation",
                            "provider": "internal",
                            "model": "valuation_modeler_v1",
                            "status": ("CONCLUANTE" if _s.get("methods_used")
                                       else "NON_CONCLUANTE"),
                            "summary": (f"methods={_s.get('methods_used', 0)} "
                                        f"range={_s.get('low')}–{_s.get('high')} "
                                        f"caveats={len(_valuation_report.get('caveats', []))}"),
                        })
                    if logger:
                        log_event(logger, "info", "valuation",
                                  f"valuation triggered: {_valuation_report.get('summary')}")
            except Exception as _valo_exc:  # pragma: no cover - fail-open
                if logger:
                    log_event(logger, "warning", "valuation",
                              f"valuation DISABLED this run: {_valo_exc}")
            if logger:
                log_event(logger, "info", "confidence_score",
                          f"score={_confidence_score['score']} grade={_confidence_score['grade']} "
                          f"metrics_injected={len(_all_metrics)} "
                          f"agent_json={_agent_json_stats}")
            if diag_list is not None:
                diag_list.append({
                    "role":     "confidence_score",
                    "provider": "internal",
                    "model":    "confidence_scorer_v1",
                    "status":   f"GRADE_{_confidence_score['grade']}",
                    "score":    _confidence_score["score"],
                    "top_penalties": [p.get("code") for p in _confidence_score.get("penalties", [])][:5],
                    # v16.5.66 — traçabilité agent JSON
                    "metrics_injected_count": len(_all_metrics),
                    "agent_json_stats": _agent_json_stats,
                })

            class _Gate16SkipRunHistory(Exception):
                pass
            # v16.5.76 Phase 5 item 10 — Run history & delta tracking
            # Persiste un snapshot du run en cours et calcule le delta vs le run
            # précédent du même dossier (rotation FIFO 20 runs par société).
            # Fail-open : si module absent ou stockage indisponible, run continue.
            _run_delta = None
            try:
                from patches.run_history import compute_and_persist_delta as _compute_delta
                # Gate 16 — le score/tendance du dossier n'est JAMAIS
                # persisté hors LIVE_MUTATING (un backtest ne pollue ni
                # l'historique des scores, ni le delta, ni FIRST_RUN).
                from patches.temporal_policy import (can_persist as _cph16,
                                                     SINK_RUN_HISTORY
                                                     as _SRH16)
                if not _cph16(locals().get("_temporal_policy16"), _SRH16):
                    if diag_list is not None:
                        diag_list.append({
                            "role": "run_history", "provider": "internal",
                            "model": "gate16",
                            "status": "SKIPPED_TEMPORAL_POLICY_READ_ONLY"})
                    raise _Gate16SkipRunHistory()
                _ws_company_name_rh = ""
                if _company_profile is not None:
                    _ws_company_name_rh = (getattr(_company_profile, "company_name_official", "") or "").strip()
                if _ws_company_name_rh:
                    _run_delta, _persist_ok = _compute_delta(
                        company_name=_ws_company_name_rh,
                        confidence_score=_confidence_score,
                        metrics_count=len(_all_metrics),
                        agent_claims_count=_agent_json_stats,
                        orange_alerts_total=_orange_alerts_total_raw if "_orange_alerts_total_raw" in dir() else _orange_alerts,
                        orange_alerts_unresolved=_orange_alerts,
                        duration_s=None,  # Pas de mesure de durée totale ici
                    )
                    if diag_list is not None:
                        diag_list.append({
                            "role":     "run_history",
                            "provider": "internal",
                            "model":    "run_history_v1",
                            "status":   "OK" if _persist_ok else "WARN_NOT_PERSISTED",
                            "has_previous":    _run_delta.has_previous,
                            "direction":       _run_delta.direction,
                            "score_delta":     _run_delta.score_delta,
                            "metrics_delta":   _run_delta.metrics_count_delta,
                            "unresolved_alerts_delta": _run_delta.orange_alerts_unresolved_delta,
                            "previous_run_id": _run_delta.previous_run_id,
                            "human_summary":   _run_delta.human_summary,
                        })
                    if logger:
                        try:
                            log_event(logger, "info", "run_history",
                                      f"company={_ws_company_name_rh} has_prev={_run_delta.has_previous} "
                                      f"score_delta={_run_delta.score_delta} direction={_run_delta.direction}")
                        except Exception:
                            pass
            except ImportError:
                pass
            except Exception as _rh_err:
                if logger:
                    try:
                        log_event(logger, "warning", "run_history",
                                  f"run_history failed: {type(_rh_err).__name__}: {_rh_err}")
                    except Exception:
                        pass
        except Exception as _cs_err:
            if logger:
                log_event(logger, "warning", "confidence_score", f"error | {str(_cs_err)[:200]}")
            _confidence_score = None
            # Since v16.5.67.10 — P0 observabilité permanente
            if diag_list is not None:
                diag_list.append({
                    "role":     "confidence_score",
                    "provider": "internal",
                    "model":    "confidence_scorer_v1",
                    "status":   "ERROR",
                    "error":    f"{type(_cs_err).__name__}: {str(_cs_err)[:200]}",
                    "score":    None,
                    "top_penalties": [],
                    "metrics_injected_count": len(_all_metrics) if "_all_metrics" in dir() else 0,
                    "agent_json_stats": _agent_json_stats if "_agent_json_stats" in dir() else {},
                })
    # ─────────────────────────────────────────────────────────────────────────

    # B.1.3.54 ChatGPT audit — FINAL truth-guard pass after completion retry
    # and every late mutation of `outputs`.  The continuation model can append
    # new text after the first guard; without this pass an exact accounting
    # assertion can reach DOCX/PPT with a stale "guard OK" diagnostic.
    try:
        from patches.finance_shaper import govern_accounting_outputs as _gao54_final
        outputs, _accounting_final_guard = _gao54_final(outputs, lang=lang)
        if (_accounting_final_guard or {}).get("status") == "ERROR":
            _accounting_guard_failed = True
        if diag_list is not None:
            _n54 = int((_accounting_final_guard or {}).get("changes", 0))
            diag_list.append({
                "role": "accounting_narrative_guard_final",
                "provider": "internal",
                "model": "accounting_narrative_guard_b1354_final",
                "status": ("ERROR" if (_accounting_final_guard or {}).get("status") == "ERROR"
                           else ("REQUALIFIED" if _n54 else "OK")),
                "changes": _n54,
                "sections": (_accounting_final_guard or {}).get("sections", {}),
                "samples": (_accounting_final_guard or {}).get("samples", []),
            })
    except Exception as _ang54_exc:
        _accounting_guard_failed = True
        _fallback54 = ("[Accounting section not governed — CFO/auditor review required]"
                       if str(lang or "fr").lower().startswith("en") else
                       "[Section comptable non gouvernée — vérification DAF/CAC requise]")
        outputs = {k: (_fallback54 if isinstance(v, str) and v else v)
                   for k, v in (outputs or {}).items()}
        if diag_list is not None:
            diag_list.append({
                "role": "accounting_narrative_guard_final",
                "provider": "internal",
                "model": "accounting_narrative_guard_b1354_final",
                "status": "ERROR",
                "error": f"{type(_ang54_exc).__name__}: {_ang54_exc}",
            })

    # ─────────────────────────────────────────────────────────────────────────
    # Patch v16.5.72 (audit ChatGPT round 15) — Source Traceability
    # ─────────────────────────────────────────────────────────────────────────
    # Construction de la FinancialFactsTable Couche 1 (déterministe) :
    # collecte les FAITS depuis Pappers/CH/GLEIF/FS bundles/signal detector.
    # Ces faits sont solides par construction (pas de LLM dans la boucle).
    # La Couche 2 (LLM) pourrait ajouter des faits complémentaires en ESTIM_IA
    # ou HYPOTHESE — pas implémenté en v16.5.72 P0 (sera v16.5.73+).
    _financial_facts_table_dict = None
    # F.6.8 / F.6.7-05 — couverture probante de la table.
    _facts_table_degraded = None
    _facts_table_fait_metrics = 0
    _facts_table_estim_filings = 0
    _b23_guards = None  # v17.1-B2.3-A — gardes pipeline (réconciliation + flags)
    _financial_documents_status_message = ""
    # Patch v16.5.72.9 (round 24 ChatGPT) — Observabilité Couche 1
    # Expose dans meta + diagnostics le statut de construction de la table de
    # faits financiers. Avant v16.5.72.9, une exception ici était silencieusement
    # masquée par le warning du logger — le diagnostic produit ne montrait rien.
    # Robin pouvait lancer une session "réussie" avec une table de faits vide
    # sans savoir pourquoi.
    _facts_table_status = "skipped"  # "ok" | "failed" | "skipped"
    _facts_table_error: Optional[str] = None
    _facts_table_n_facts: Optional[int] = None
    _facts_table_t0 = time.time()
    # ── v17.1-B2.3.5 — Gardes pipeline DÉCOUPLÉES de la FinancialFactsTable ──
    # (réserve audit ChatGPT) : les gardes ne dépendent que des narratifs agents
    # et de la date ; elles tournent donc AVANT et INDÉPENDAMMENT de la table
    # financière, pour s'exécuter même si la construction de la table échoue.
    # Fail-open. (Initialisé à None plus haut.)
    try:
        from patches.pipeline_guards_b23 import apply_b23_guards as _apply_b23
        from datetime import date as _b23_date

        def _b23_txt(v):
            if v is None:
                return ""
            if isinstance(v, str):
                return v
            try:
                return _as_output(v) or ""
            except Exception:
                return ""
        _lc = locals()
        # Même vérité que les renderers : les gardes B2.3 consomment la map
        # `outputs` déjà gouvernée, et non les objets agents bruts.
        _b23_pairs = (("strategie", "strategie"),
                      ("synthese", "synthese_decisions"),
                      ("direction_generale", "direction_generale"),
                      ("finance", "finance"))
        _b23_recos = [{"agent": _a, "reco": _b23_txt(outputs.get(_k))}
                      for _a, _k in _b23_pairs if _b23_txt(outputs.get(_k))]
        _b23_cr = "\n".join(_b23_txt(outputs.get(_k)) for _, _k in _b23_pairs)
        # Gate 12 — l'autorité B2.3 n'est JAMAIS l'horloge système ; sans
        # date réelle connue, aucune autorité (fail-closed).
        _b23_rd = _run_now.date() if "_run_now" in _lc else None
        if locals().get("_scenario_status") in ("INVALID", "ERROR"):
            # scénario demandé mais illisible → aucune autorité temporelle :
            # aucun garde d'échéance ne tourne contre la date réelle.
            _b23_rd = None
        # F.6.7.1 — l'« en retard » se calcule à la DATE D'ANALYSE SIMULÉE (scénario),
        # pas à la date réelle du run : un jalon 2023 n'est pas « déjà passé au 2026 ».
        _b23_aod = _get_analysis_as_of()
        if _b23_aod:
            try:
                _b23_rd = _b23_date.fromisoformat(_b23_aod)
            except Exception:
                pass
        try:   # 9.4.57 — §4.6 : la rubrique Décision suit l'orientation que le conseil a adoptée dans le brief
            from patches.codir_register_history import parse_board_decision as _pbd57
            _board57 = _pbd57(str(brief or ""))
        except Exception:
            _board57 = ""
        if not _board57:
            # 9.4.60 — F59-03 : décision prise lors d'une séance précédente, lue dans l'état structuré du dossier (le brief
            # courant, s'il en contient une, reste prioritaire)
            try:
                from patches.codir_register_history import latest_board_option60 as _lbo60, compute_dossier_id as _cdi60
                try:
                    _cp60 = _company_profile.to_dict() if _company_profile else {}
                except Exception:
                    _cp60 = {}
                _soc60 = str(_cp60.get("name") or _cp60.get("company_name") or _cp60.get("denomination") or "")
                _lab60 = (settings.get("dossier_label", "") if isinstance(settings, dict)
                          else getattr(settings, "dossier_label", "")) or ""
                _board57 = _lbo60(_cdi60(societe=_soc60, dossier_label=_lab60))[0]
            except Exception:
                _board57 = ""
        try:   # 9.4.65 — l'option adoptée, gardée pour le deck (même source que la rubrique Décision)
            if _board57:
                meta["board_option65"] = str(_board57).strip()
        except Exception:
            pass
        _b23_guards = _apply_b23(cr_text=_b23_cr, agent_recos=_b23_recos, run_date=_b23_rd, decision_mode=_genre.decision_mode, lang=lang, genre=str(getattr(_genre, "genre", "") or ""), board_option=_board57)
    except Exception:
        _b23_guards = None

    # B.1.3.53 ChatGPT candidate — an accounting truth-guard ERROR is a hard
    # run blocker, not a diagnostic footnote.  Merge it into the exact object
    # consumed by app.py and the DOCX/PPT confidence renderers.
    if locals().get("_accounting_guard_failed", False):
        _b23_guards = _merge_accounting_guard_failure(_b23_guards, lang=lang)
    # v17.1.0-B2.3-F.4.3 — Gouvernance : si le gate détecte une contradiction
    # critique (ex. EBITDA présenté chiffré ici / non communiqué là), on plafonne
    # la traçabilité de la table financière (jamais 100/100 board-safe avec une
    # contradiction non résolue). Fail-open ; rendu de la table après ce point.
    try:
        if _b23_guards and _facts_table_built is not None:
            _flags = _b23_guards.get("flags") or []
            if any(("présenté comme chiffré" in str(f)) or
                   ("Contradiction à arbitrer" in str(f)) for f in _flags):
                _facts_table_built.flag_coherence_issue(
                    "contradiction critique non résolue (gate B2.3)")
    except Exception:
        pass
    try:
        from utils.financial_facts_table import (
            build_facts_table_from_sources,
            build_financial_documents_status_message,
        )
        # Patch v16.5.73 — Réutilisation de la table déjà construite en amont
        # (~ligne 2855) pour économiser ~1-2s sur dossiers riches et garantir
        # que le rendu DOCX/PPTX = exactement ce qu'ont vu les agents.
        # Si la construction amont a échoué (table_built is None), on rebuild
        # ici en fallback — robustesse > performance.
        if _facts_table_built is not None:
            _facts_table = _facts_table_built
        else:
            _facts_table = build_facts_table_from_sources(
            lang=lang,
                pappers_blocks=_pap_blocks if _pap_full else None,
                ch_blocks=_ch_blocks,
                gleif_blocks=(None if (isinstance(_gleif_blocks, dict) and _gleif_blocks.get("status") == "rejected") else _gleif_blocks),
                financial_statements_bundles=financial_statements_bundles,
                financial_signal_report=_financial_signal_report,
                # Patch v16.5.72.1 P0 (audit ChatGPT round 16) — extraire vrais chiffres
                # depuis le bloc Financial Statements (Revenue, EBIT, FCF, etc.)
                financial_statements_block=financial_statements_block,
                attachments_block=attachments_block,
            )
            # ── M6-B B.1.1 (audit gate B.2, P2) — B.1 sur la table FALLBACK ──
            # La couche de preuve est RÉ-APPLIQUÉE ici pour que le rendu final
            # (🧭 contexte, ⛔ hors périmètre, ⚡ tensions, identité des faits)
            # existe même quand la construction amont a échoué. Le SCORE, lui,
            # est déjà arrêté : la prudence renforcée (signal effectif False,
            # journalisée plus haut) reste la vérité du run — on ne
            # re-certifie pas après coup. signal_gate_reason le dit.
            try:
                from patches.analysis_context import \
                    infer_analysis_context as _b1_infer_fb
                from patches.proof_layer import \
                    apply_b1_proof_layer as _b1_apply_fb
                if _b1_ctx is None:
                    _b1_ctx = _b1_infer_fb(
                        brief,
                        resolved_entity_name=(_resolved_name
                                              or pappers_confirmed_entity or ""),
                        resolved_entity_id=str(
                            getattr(_pap_rlog, "siren_used", "") or ""),
                        resolution_from_registry=bool(_pap_full),
                    )
                # B.1.3.1 (audit P2) — le FALLBACK réinjecte les faits du
                # brief avant de repasser la couche de preuve : une table
                # reconstruite ne doit pas « oublier » le déclaratif du brief
                # (visible, jamais board-safe). Idempotent — no-op si déjà là.
                try:
                    from patches.brief_facts import \
                        inject_brief_facts_once as _ibf_fb
                    _scope_map_fb = {"consolide": "CONSOLIDATED",
                                     "social": "SOCIAL_STANDALONE"}
                    _added_fb = _ibf_fb(
                        _facts_table, brief, lang=lang,
                        scope=_scope_map_fb.get(
                            (getattr(_b1_ctx, "target_perimeter_level", "")
                             or "").lower(), "UNKNOWN"),
                        perimeter_entity=getattr(_b1_ctx, "target_entity", "")
                        or "")
                    if _added_fb and diag_list is not None:
                        diag_list.append({
                            "role": "brief_facts", "provider": "internal",
                            "model": "brief_facts_b13", "status": "OK",
                            "summary": (f"{len(_added_fb)} fait(s) du brief "
                                        f"réinjectés (fallback table)"),
                        })
                except Exception:
                    pass
                _b1_result = _b1_apply_fb(
                    _facts_table, _b1_ctx,
                    raw_signal_solid=bool(_financial_signal_in_attachments_solid),
                    registry_entity=(_resolved_name or ""),
                    registry_entity_id=str(getattr(_pap_rlog, "siren_used", "") or ""),
                    registry_resolution_id=str(getattr(_pap_rlog, "siren_used", "") or ""),
                    lang=lang,
                )
                _b1_conflicts = _b1_result.get("conflicts") or []
                # La vérité du score reste la prudence posée en amont — et le
                # gate_reason ne prétend « ré-appliqué » que si la preuve a
                # RÉELLEMENT tourné (B.1.2 : témoin proof_applied ; sinon on
                # laisse "proof_layer_error" dire la vérité).
                _b1_result["signal_effective"] = bool(_fin_signal_solid_effective)
                if _b1_result.get("proof_applied"):
                    _b1_result["signal_gate_reason"] = (
                        "b1_reapplied_on_fallback_render_only"
                        "_score_already_set_to_prudence")
                if logger:
                    try:
                        log_event(logger, "info", "proof_layer_b1",
                                  "b1_reapplied_on_fallback",
                                  summary=(f"render_only | applied="
                                           f"{bool(_b1_result.get('proof_applied'))} | "
                                           f"conflicts={len(_b1_conflicts)}"))
                    except Exception:
                        pass
            except Exception:
                pass  # rendu non annoté — la prudence renforcée reste tracée
        # M6-B B.1 (E7) — le rendu final porte le contexte d'analyse et les
        # conflits détectés (même fonction de rendu que les agents).
        _facts_table_md = _facts_table.to_markdown_table(
            lang=lang, analysis_context=_b1_ctx, conflicts=_b1_conflicts)
        # B.1.3.56 correctif P0-F56-02 — le payload sépare les faits VISIBLES
        # des faits gouvernés diagnostics-only : « facts » n'expose jamais une
        # valeur non résolue ; « diagnostic_facts » la conserve intégralement.
        from utils.financial_facts_table import is_visible_fact as _ivf56e
        _all_rows56 = [f.to_row_dict() for f in _facts_table.facts]
        _financial_facts_table_dict = {
            "diag":     _facts_table.to_diag_dict(),
            "markdown": _facts_table_md,
            "facts":    [r for r in _all_rows56 if _ivf56e(r)],
            "diagnostic_facts": [r for r in _all_rows56
                                 if not _ivf56e(r)],
            # v17.1-B2.2 — l'invariant deck lit ce flag : pas de « Traçabilité
            # 100/100 » si le scorer n'a pas tourné (→ revue humaine requise).
            "scorer_ok": _scorer_ok,
            "proof_summary": (_facts_table.proof_summary()
                              if hasattr(_facts_table, "proof_summary") else {}),
        }
        # Patch v16.5.72.1 P0 (audit ChatGPT round 16) — Distinction identité vs financier
        # Bug v16.5.72 : `n_facts_solid > 0` déclenchait "Signaux financiers
        # exploitables" même avec uniquement UK Company Number / LEI
        # (qui sont des FAITS d'identité, pas de chiffres financiers).
        # Fix : utiliser has_financial_value_facts() qui exige de vrais
        # chiffres (CA, EBITDA, FCF, etc.) ou un signal multi-format solide.
        _financial_documents_status_message = build_financial_documents_status_message(
            n_unextractable=int((attachments_meta or {}).get("n_unextractable", 0) or 0),  # B.1.3.23 P2-I'
            has_some_financial_signal=(
                # B.1.1 (audit gate B.2, P0) — helper EN PÉRIMÈTRE : un fait
                # MISMATCH (visible mais exclu du score) ne fait plus afficher
                # « Signaux financiers exploitables ».
                _facts_table.has_in_perimeter_financial_value_facts()
                # M6-B B.1 — signal EFFECTIF (porte de périmètre), pas le brut.
                or _fin_signal_solid_effective
            ),
            # B.1.3 — chiffres présents mais TOUS issus du brief → message
            # honnête dédié, jamais « Signaux financiers exploitables ».
            brief_facts_only=_facts_table.financial_values_brief_only(),
            has_attachments_but_no_fs=(
                _attachments_count > 0
                and not _fin_signal_solid_effective
                and not any(
                    getattr(b, "financial_statements_detected", False)
                    for b in (financial_statements_bundles or [])
                )
            ),
            attachments_count=_attachments_count,
            n_pdfs_with_fs=sum(
                1 for b in (financial_statements_bundles or [])
                if getattr(b, "financial_statements_detected", False)
            ),
            financial_signal_score=(
                _financial_signal_report.confidence_score
                if _financial_signal_report else None
            ),
            # B.1.3.8 — fidélité-page transmise : « exploitable » réservé aux faits.
            n_page_confirmed=((int(((_extraction_fidelity or {}).get("per_page") or {}).get("verbatim_on_page", 0))
                               + int(((_extraction_fidelity or {}).get("per_page") or {}).get("normalized_on_page", 0)))
                              if isinstance(_extraction_fidelity, dict) else None),
            lang=lang,
        )
        if logger:
            # Patch v16.5.72.8 (audit ChatGPT round 23) — Fix appel log_event :
            # 'message' est positionnel (4ème arg), pas un kwarg. Avant cette
            # release, l'appel utilisait summary= ce qui faisait crasher
            # log_event() avec TypeError: missing 'message'.
            try:
                log_event(
                    logger, "info", "financial_facts_table",
                    "facts_table_built",
                    summary=(
                        f"facts={_facts_table.n_facts_total} "
                        f"solid={_facts_table.n_facts_solid} "
                        f"financial_values={_facts_table.n_financial_value_facts} "
                        f"score={_facts_table.traceability_score}/100"
                    ),
                )
            except Exception:
                # PATCH HOTFIX 2026-05-01 — log_event ne doit JAMAIS casser le pipeline.
                # Si le logger lui-meme echoue (mauvais appel, JSON IO), on
                # continue silencieusement. Le pipeline metier est plus
                # important que la trace de log.
                pass
        # Patch v16.5.72.9 (round 24) — observabilité succès
        _facts_table_status = "ok"
        _facts_table_n_facts = _facts_table.n_facts_total
        # F.6.8 / F.6.7-05 — couverture probante : une table « OK » exige AU MOINS
        # une vraie métrique financière déterministe (FAIT), pas seulement le
        # « Signal financier exploitable » générique ni des faits ESTIM-FILINGS
        # promus du narratif (À VÉRIFIER). Sinon → DEGRADED (honnêteté board-safe).
        try:
            from utils.financial_facts_table import FactStatus as _FS
            _facts_table_fait_metrics = sum(
                1 for f in _facts_table.facts
                if f.is_financial_value() and f.status == _FS.FAIT
                and "signal financier exploitable" not in str(f.label).lower())
            _facts_table_estim_filings = sum(
                1 for f in _facts_table.facts
                if f.status == _FS.A_VERIFIER and f.is_financial_value())
            _facts_table_degraded = (_facts_table_fait_metrics == 0)
        except Exception:
            _facts_table_degraded = None
    except Exception as _ft_e:
        # Patch v16.5.72.9 (round 24) — observabilité échec
        _facts_table_status = "failed"
        _facts_table_error = f"{type(_ft_e).__name__}: {str(_ft_e)[:200]}"
        if logger:
            # Patch v16.5.72.8 — Idem dans le bloc except : message en positionnel
            # + try/except autour du log pour qu'un crash de logging ne masque
            # jamais l'exception métier originale.
            try:
                log_event(
                    logger, "warning", "financial_facts_table",
                    "facts_table_build_error",
                    summary=f"build_error | {str(_ft_e)[:120]}",
                    error_type=type(_ft_e).__name__,
                )
            except Exception:
                pass
    finally:
        # Patch v16.5.72.9 (round 24) — duration measurement
        _facts_table_duration_ms = int((time.time() - _facts_table_t0) * 1000)

    # ── B.1.3.61 — chokepoint transversal des sorties agents ───────────────
    # Les fuites conversationnelles et les calculs Finance non défendables sont
    # neutralisés AVANT toute divergence vers Word, PPT, registre, historique ou
    # UI. Le brief utilisateur n'entre jamais dans ce gate.
    _agent_leakage_report = {"sentences_removed": 0, "fields_touched": 0}
    _finance_factual_safety_report = {}
    try:
        from utils.agent_leakage_gate import sanitize_agent_outputs as _sanitize_outputs61
        outputs, _agent_leakage_report = _sanitize_outputs61(outputs)
        if _agent_leakage_report.get("sentences_removed") and diag_list is not None:
            diag_list.append({
                "role": "agent_output_leakage_gate", "provider": "internal",
                "model": "agent_output_leakage_b1361", "status": "SANITIZED",
                "flagged": _agent_leakage_report.get("sentences_removed", 0),
                "summary": "méta-discours d'orchestration retiré avant les surfaces",
            })
    except Exception as _leak_err61:
        if diag_list is not None:
            diag_list.append({
                "role": "agent_output_leakage_gate", "provider": "internal",
                "model": "agent_output_leakage_b1361", "status": "FAILED_OPEN",
                "error": f"{type(_leak_err61).__name__}: {str(_leak_err61)[:160]}",
            })

    _market_evidence_safety_report = {}
    try:
        from utils.market_evidence_safety import sanitize_market_claims as _sanitize_market624
        # v62.13.9.4.38 — l'année d'analyse (politique temporelle) pilote la note de
        # réconciliation marché : plus de « 2026 » écrit par le produit dans une analyse
        # rétrospective au 15/02/2023 (run réel du 19/09/2026).
        try:
            _tp38 = locals().get("_temporal_policy16")
            _ay38 = int(str(getattr(_tp38, "analysis_date", "") or "")[:4]) if _tp38 is not None else None
        except Exception:
            _ay38 = None
        outputs, _market_evidence_safety_report = _sanitize_market624(
            outputs, _web_facts_ledger, lang=lang, analysis_year=_ay38)
        if (_market_evidence_safety_report.get("claims_rewritten") and
                diag_list is not None):
            diag_list.append({
                "role": "market_evidence_safety", "provider": "internal",
                "model": "market_evidence_safety_v624", "status": "RECONCILED",
                **_market_evidence_safety_report,
            })
    except Exception as _market_safe_err624:
        _market_error626 = (
            f"{type(_market_safe_err624).__name__}: {str(_market_safe_err624)[:160]}")
        try:
            from utils.market_evidence_safety import (
                fail_closed_market_outputs as _market_fallback626)
            outputs, _market_evidence_safety_report = _market_fallback626(
                outputs, lang=lang)
        except Exception:
            # Absolute last resort: suppress the two market-rich surfaces.
            _safe_market626 = (
                "MARKET EVIDENCE UNAVAILABLE — quantitative claims withheld."
                if str(lang).lower().startswith("en") else
                "PREUVES MARCHÉ INDISPONIBLES — affirmations quantitatives écartées.")
            for _mk626 in ("strategie", "synthese_decisions", "marketing", "commercial"):
                if isinstance(outputs.get(_mk626), str):
                    outputs[_mk626] = _safe_market626
            _market_evidence_safety_report = {"status": "FAILED_CLOSED"}
        _market_evidence_safety_report["error"] = _market_error626
        if diag_list is not None:
            diag_list.append({
                "role": "market_evidence_safety", "provider": "internal",
                "model": "market_evidence_safety_v626", "status": "FAILED_CLOSED",
                "error": _market_error626,
                **{k: v for k, v in _market_evidence_safety_report.items() if k != "error"},
            })

    try:
        from utils.finance_factual_safety import (
            has_primary_financial_evidence as _has_primary61,
            sanitize_finance_output as _sanitize_finance61,
            sanitize_cross_output_financial_claims as _sanitize_cross_fin624,
        )
        _primary_financials61 = _has_primary61(
            _financial_facts_table_dict, _facts_table_status)
        _entity_form624 = str(getattr(_company_profile, "legal_form", "") or "")
        if isinstance(outputs.get("finance"), str):
            outputs["finance"], _finance_factual_safety_report = _sanitize_finance61(
                outputs.get("finance", ""),
                has_primary_financials=_primary_financials61, lang=lang,
                entity_form=_entity_form624,
                company_profile=_company_profile)     # v62.13.9.4.34 (lot 2) — repli par nature d'activité
        outputs, _cross_fin624 = _sanitize_cross_fin624(
            outputs, has_primary_financials=_primary_financials61,
            lang=lang, entity_form=_entity_form624,
            company_profile=_company_profile)
        _finance_factual_safety_report["cross_output"] = _cross_fin624
        if ((sum(int(_finance_factual_safety_report.get(k, 0) or 0) for k in
                 ("tns_sasu_removed", "personalized_lines_removed",
                  "unsupported_company_lines_removed", "finance_output_replaced"))
             or int((_finance_factual_safety_report.get("cross_output") or {}).get(
                 "fields_touched", 0) or 0))
                and diag_list is not None):
            diag_list.append({
                "role": "finance_factual_safety", "provider": "internal",
                "model": "finance_factual_safety_v624", "status": "CALCULATIONS_REMOVED",
                "summary": "calculs sociaux/personnels ou besoins entreprise non prouvés écartés",
                **_finance_factual_safety_report,
            })
    except Exception as _fin_safe_err61:
        _fin_error626 = (
            f"{type(_fin_safe_err61).__name__}: {str(_fin_safe_err61)[:160]}")
        try:
            from utils.finance_factual_safety import (
                fail_closed_finance_outputs as _finance_fallback626)
            outputs, _finance_factual_safety_report = _finance_fallback626(
                outputs, lang=lang,
                entity_form=str(getattr(_company_profile, "legal_form", "") or ""))
        except Exception:
            _safe_fin626 = (
                "FINANCE — PRUDENT INTERNAL FRAME\nNo verified primary financial data; "
                "all personalized calculations were withheld."
                if str(lang).lower().startswith("en") else
                "FINANCE — CADRE INTERNE PRUDENT\nAucune donnée financière primaire "
                "vérifiée ; tous les calculs personnalisés ont été écartés.")
            outputs["finance"] = _safe_fin626
            _finance_factual_safety_report = {
                "status": "FAILED_CLOSED", "finance_output_replaced": True}
        _finance_factual_safety_report["error"] = _fin_error626
        if diag_list is not None:
            diag_list.append({
                "role": "finance_factual_safety", "provider": "internal",
                "model": "finance_factual_safety_v626", "status": "FAILED_CLOSED",
                "error": _fin_error626,
                **{k: v for k, v in _finance_factual_safety_report.items() if k != "error"},
            })

    # v62.10 — BOARD SCRUTINY : les cibles chiffrées non étayées ne doivent
    # jamais devenir des ancrages exécutifs dans le Word ou le Working Deck.
    # Les faits vérifiés restent disponibles ; les scénarios sans baseline sont
    # reformulés qualitativement. Le parseur de preuve page-confirmée demeure le
    # chantier séparé v62.11.
    _board_scrutiny_guard_report = {}
    _scenario_appendix6212 = []
    _numeric_support_claims62131 = []
    # v62.13.9.4.50 — FAITS EXTERNES DATÉS (décision Robin du 30/09/2026) : routés par les identifiants RÉSOLUS
    # (CIK → SEC, SIREN → Pappers, numéro britannique → Companies House, LEI → GLEIF pour l'identité), collectés une
    # fois, bornés par les garde-fous des connecteurs. Ils soutiennent les lignes qui citent une valeur publiée et
    # donnent l'exercice antérieur aux contrôles ; ils ne remplacent jamais un fait confirmé à la page.
    _external50 = {"facts": [], "sources": {}, "identity": {}}
    try:
        _ids50 = {}
        if isinstance(locals().get("_sec_blocks"), dict) and _sec_blocks.get("primary_cik"):
            _ids50["cik"] = str(_sec_blocks.get("primary_cik"))
        if isinstance(locals().get("_ch_blocks"), dict) and _ch_blocks.get("company_number"):
            _ids50["company_number"] = str(_ch_blocks.get("company_number"))
        _rd50 = locals().get("_routing_decision")
        if _rd50 is not None and str(getattr(_rd50, "id_type", "")).upper() == "SIREN" and getattr(_rd50, "primary_id", ""):
            _ids50["siren"] = str(_rd50.primary_id)
        # v62.13.9.4.50 — recette du 01/10 : la résolution SEC par le NOM (graphie du nom différente chez la SEC) n'a rendu
        # aucun CIK, alors que le 10-K joint le porte dans son numéro de dépôt (« <CIK à 10 chiffres>-AA-NNNNNN_… ») ou son en-tête
        # (« Central Index Key: 0000105132 »). Le CIK lu dans les pièces sert, sous réserve que la SEC confirme le nom.
        if "cik" not in _ids50:
            from utils.external_facts50 import cik_from_documents as _cfd50
            _c50 = _cfd50(str(locals().get("attachments_block") or ""))
            if _c50:
                _ids50["cik"], _ids50["cik_from_documents"] = _c50, "1"
        _lei50 = re.search(r"\b([A-Z0-9]{18}\d{2})\b", str(brief or ""))
        if _lei50:
            _ids50["lei"] = _lei50.group(1)
        if _ids50 and not locals().get("external_sources_skip"):
            from utils.external_facts50 import collect_external_facts as _cef50
            _external50 = _cef50(_ids50, allow_network=True,
                                 expected_name=str(locals().get("_analysis_name_q") or locals().get("_resolved_name") or ""))
            _external50["identifiers"] = _ids50
    except Exception as _ext_exc50:
        _external50 = {"facts": [], "sources": {"_": f"error: {type(_ext_exc50).__name__}"}, "identity": {}}
    try:
        try:
            from utils.financial_proof_layer import build_board_numeric_support_claims as _bbnsc62131
            _numeric_support_claims62131 = _bbnsc62131(_facts_table_built, lang=lang)
        except Exception:
            _numeric_support_claims62131 = []
        try:
            if _external50.get("facts"):
                from utils.external_facts50 import as_support_claims as _asc50
                _numeric_support_claims62131 = list(_numeric_support_claims62131) + _asc50(_external50["facts"], lang)
        except Exception:
            pass
        from utils.board_scrutiny_guard import (
            sanitize_board_scrutiny_outputs as _sanitize_board6210,
            collect_numeric_scenarios_from_mapping as _collect_scenarios6212,
            deduplicate_scenario_appendix as _dedup_scenarios6212,
        )
        _allow_lbl_62130 = False  # v62.13.2 Option B — single active policy
        # v62.13.9.4.45 — VALEURS PORTÉES PAR LES PAGES. Run réel du 26/09/2026 : « published
        # 55.1% » — le taux de marge de la fiche société — était brouillé en « a level to
        # size » parce que la table de faits ne le portait pas. Une valeur qui figure sur une
        # page à côté de sa grandeur n'est pas une cible non étayée : elle ne se brouille pas.
        _page_vals45 = set()
        try:
            from types import SimpleNamespace as _NS45
            from utils.claim_lineage41 import build_page_metric_index as _bpmi45
            _corpus45 = "\n".join(str(x or "") for x in (locals().get("financial_statements_block"), locals().get("attachments_block")))
            for _v45, _k45 in _bpmi45([_NS45(text=_corpus45, page=0)]):
                _page_vals45.add(str(_v45))
        except Exception:
            _page_vals45 = set()
        outputs, _board_scrutiny_guard_report = _sanitize_board6210(
            outputs,
            finance_tone=str(getattr(_genre, "finance_tone", "") or ""),
            lang=lang,
            allow_labelled_estimates=_allow_lbl_62130,
            numeric_support_claims=_numeric_support_claims62131,
            authoritative_horizon_values=_page_vals45 or None,
        )
        if str(getattr(_genre, "finance_tone", "") or "").upper() == "BOARD_SCRUTINY":
            from utils.board_scrutiny_guard import strip_numeric_targets_from_mapping as _strip_map6210
            _scenario_candidates6212 = list(
                _board_scrutiny_guard_report.get("withheld_scenarios") or [])
            if isinstance(commercial_json, dict):
                _scenario_candidates6212.extend(_collect_scenarios6212(
                    commercial_json, section="commercial_json", lang=lang,
                    numeric_support_claims=_numeric_support_claims62131))
                commercial_json = _strip_map6210(
                    commercial_json, lang=lang,
                    numeric_support_claims=_numeric_support_claims62131)
                _board_scrutiny_guard_report["commercial_json_sanitized"] = True
            if isinstance(supply_chain_bundle, dict):
                if isinstance(supply_chain_bundle.get("json"), dict):
                    _scenario_candidates6212.extend(_collect_scenarios6212(
                        supply_chain_bundle.get("json"), section="supply_chain_json", lang=lang,
                        numeric_support_claims=_numeric_support_claims62131))
                    supply_chain_bundle["json"] = _strip_map6210(
                        supply_chain_bundle.get("json"), lang=lang,
                        numeric_support_claims=_numeric_support_claims62131)
                    _board_scrutiny_guard_report["supply_chain_json_sanitized"] = True
                if isinstance(supply_chain_bundle.get("output"), str):
                    _sc_clean6210, _sc_rep6210 = _sanitize_board6210(
                        {"supply_chain": supply_chain_bundle.get("output")},
                        finance_tone="BOARD_SCRUTINY", lang=lang,
                        allow_labelled_estimates=_allow_lbl_62130,
                        numeric_support_claims=_numeric_support_claims62131)
                    supply_chain_bundle["output"] = _sc_clean6210.get("supply_chain", "")
            # ``meta`` was created before the governance pass: update its
            # structured payloads so the renderers consume the governed truth.
            if isinstance(meta, dict):
                meta["commercial_json"] = commercial_json
                meta["supply_chain_json"] = supply_chain_bundle.get("json") if isinstance(supply_chain_bundle, dict) else None
                meta["numeric_support_claims"] = list(_numeric_support_claims62131)
                meta["external_facts50"] = _external50           # v62.13.9.4.50 — faits externes datés
                try:   # v62.13.9.4.50 — date de clôture lue dans les pièces (recette du 01/10)
                    from utils.fiscal_year_end50 import detect_fiscal_year_end as _dfye50
                    meta["fiscal_year_end50"] = _dfye50(str(locals().get("attachments_block") or ""),
                                                        str(locals().get("analysis_date") or ""))
                except Exception:
                    meta["fiscal_year_end50"] = ""
                try:   # 9.4.51 — effectif lu dans les pièces (contre-recette du 03/10)
                    from utils.fiscal_year_end50 import detect_headcount as _dhc51
                    meta["headcount51"] = (str((locals().get("attachments_meta") or {}).get("headcount57") or "")
                                           or _dhc51(str(locals().get("attachments_block") or "")))
                except Exception:
                    meta["headcount51"] = ""
            _scenario_appendix6212 = _dedup_scenarios6212(
                _scenario_candidates6212, lang=lang)
            _board_scrutiny_guard_report["scenario_appendix_count"] = len(
                _scenario_appendix6212)
        if (_board_scrutiny_guard_report.get("lines_rewritten") and
                diag_list is not None):
            diag_list.append({
                "role": "board_scrutiny_guard",
                "provider": "internal",
                "model": "board_scrutiny_truth_contract_v6212",
                "status": "UNSUPPORTED_EXECUTIVE_NUMBERS_WITHHELD",
                **_board_scrutiny_guard_report,
            })
    except Exception as _bsg_exc6210:
        _board_scrutiny_guard_report = {
            "status": "ERROR",
            "error": f"{type(_bsg_exc6210).__name__}: {str(_bsg_exc6210)[:160]}",
        }
        # Fail closed for Board-scrutiny executive surfaces only.
        if str(getattr(_genre, "finance_tone", "") or "").upper() == "BOARD_SCRUTINY":
            _fallback_bsg = (
                "BOARD SCRUTINY — unsupported quantified targets withheld; "
                "establish baseline and provenance before use."
                if str(lang).lower().startswith("en") else
                "REVUE CONSEIL — cibles chiffrées non étayées écartées ; "
                "établir baseline et provenance avant usage."
            )
            for _bsg_key in ("synthese_decisions", "direction_generale", "ceo", "commercial"):
                if isinstance(outputs.get(_bsg_key), str):
                    outputs[_bsg_key] = _fallback_bsg
        if diag_list is not None:
            diag_list.append({
                "role": "board_scrutiny_guard", "provider": "internal",
                "model": "board_scrutiny_truth_contract_v6212",
                "status": "FAILED_CLOSED", **_board_scrutiny_guard_report,
            })

    # v62.10 — horizon prospectif transverse : le Word ne doit pas réduire
    # un plan explicite de 24 mois à un simple plan de redressement de 12 mois.
    _strategic_horizon_output_report = {}
    try:
        from patches.strategic_horizon import enforce_horizon_in_outputs as _eho6210
        _target_end6210 = str(getattr(_horizon_reconciliation, "target_end_date", "") or "")
        outputs, _strategic_horizon_output_report = _eho6210(
            outputs, target_end_date=_target_end6210, lang=lang)
        if _strategic_horizon_output_report.get("fields_touched") and diag_list is not None:
            diag_list.append({
                "role": "strategic_horizon_output", "provider": "internal",
                "model": "strategic_horizon_output_contract_v6210",
                "status": "ENFORCED", **_strategic_horizon_output_report,
            })
    except Exception:
        _strategic_horizon_output_report = {}

    # v62.12 — FINAL CURRENT-PERIOD AUTHORITY PASS.  Safety guards and
    # structured-output sanitation above may mutate narratives after the first
    # proof-layer pass.  Re-apply the same idempotent canonical claim contract
    # immediately before Word/PPTX divergence.
    _current_period_authority_report6212 = {}
    try:
        from utils.financial_proof_layer import reconcile_financial_narrative as _final_rfn6212
        outputs, _current_period_authority_report6212 = _final_rfn6212(
            outputs, _facts_table_built, lang=lang)
        if isinstance(synthese_res, dict):
            synthese_res["output"] = str(outputs.get("synthese_decisions", "") or "")
        if isinstance(ceo_res, dict):
            ceo_res["output"] = str(outputs.get("ceo") or outputs.get("direction_generale") or "")
        _financial_proof_layer_report = {
            **(_financial_proof_layer_report or {}),
            "final_authority_pass": _current_period_authority_report6212,
            "canonical_claims": (_current_period_authority_report6212.get("canonical_claims")
                                 or (_financial_proof_layer_report or {}).get("canonical_claims") or []),
        }
        if diag_list is not None:
            diag_list.append({
                "role": "current_period_authority", "provider": "internal",
                "model": "current_period_page_confirmed_authority_v6212",
                "status": "ENFORCED",
                **{k: v for k, v in _current_period_authority_report6212.items()
                   if k != "canonical_claims"},
                "canonical_claim_count": len(
                    _current_period_authority_report6212.get("canonical_claims") or []),
            })
    except Exception as _cpa_err6212:
        _current_period_authority_report6212 = {
            "status": "ERROR",
            "error": f"{type(_cpa_err6212).__name__}: {str(_cpa_err6212)[:180]}",
        }

    # v62.10 — temporalité de la PREUVE : distinguer le dernier dépôt
    # registre de la dernière période financière effectivement utilisée dans la
    # narration. Cette information est descriptive ; elle ne certifie aucun fait.
    try:
        if (_temporal_frame_obj is not None and
                not bool((_financial_proof_layer_report or {}).get(
                    "current_financial_state_established"))):
            from patches.temporal_frame import attach_parsed_financial_period as _apfp6210
            _temporal_frame_obj = _apfp6210(_temporal_frame_obj, outputs, lang=lang)
    except Exception:
        pass

    # Copie pré-garde comptable réservée à l'extraction des actions. Elle est
    # « RAW » uniquement vis-à-vis de la reformulation comptable, mais déjà
    # assainie des fuites, calculs invalides et cibles Board non étayées.
    _outputs_for_agenda48 = dict(outputs)

    # ── B.1.3.47-chatgpt — Action Guard comptable transversal ───────────────
    # Les outputs agents alimentent plusieurs surfaces (CR, deck, registre). Le
    # garde doit donc intervenir AVANT leur divergence, et non uniquement sur la
    # colonne « action » du registre.
    _accounting_action_guard_failed = False
    try:
        from patches.codir_register_history import govern_accounting_commitment_text as _gact47
        _acct_changed47 = 0
        for _ok47, _ov47 in list(outputs.items()):
            if isinstance(_ov47, str):
                _nv47, _nn47 = _gact47(_ov47, lang=lang)
                outputs[_ok47] = _nv47
                _acct_changed47 += _nn47
        if _acct_changed47 and diag_list is not None:
            diag_list.append({
                "role": "accounting_action_guard", "provider": "internal",
                "model": "accounting_action_guard_b1354_fail_closed",
                "status": "CONDITIONALIZED",
                "summary": f"{_acct_changed47} formulation(s) retraite/provision rendue(s) conditionnelle(s)",
            })
    except Exception as _acct_err47:
        _accounting_action_guard_failed = True
        _fallback_action54 = ("[Accounting action section not governed — CFO/auditor review required]"
                              if str(lang or "fr").lower().startswith("en") else
                              "[Section d'actions comptables non gouvernée — vérification DAF/CAC requise]")
        outputs = {k: (_fallback_action54 if isinstance(v, str) and v else v)
                   for k, v in (outputs or {}).items()}
        _b23_guards = _merge_accounting_action_guard_failure(_b23_guards, lang=lang)
        if diag_list is not None:
            diag_list.append({
                "role": "accounting_action_guard", "provider": "internal",
                "model": "accounting_action_guard_b1354_fail_closed",
                "status": "ERROR", "error": f"{type(_acct_err47).__name__}: {str(_acct_err47)[:160]}",
            })

    # v62.12 — authority must remain the final writer-facing truth even after
    # the accounting commitment guard.  This second pass is idempotent and
    # closes the last mutation point before the action register, Word and PPTX
    # consume the narratives.
    try:
        from utils.financial_proof_layer import reconcile_financial_narrative as _post_acct_rfn6212
        outputs, _post_acct_authority6212 = _post_acct_rfn6212(
            outputs, _facts_table_built, lang=lang)
        _current_period_authority_report6212 = {
            **(_current_period_authority_report6212 or {}),
            "post_accounting_guard": _post_acct_authority6212,
            "canonical_claims": (_post_acct_authority6212.get("canonical_claims")
                                 or (_current_period_authority_report6212 or {}).get("canonical_claims") or []),
        }
        _financial_proof_layer_report = {
            **(_financial_proof_layer_report or {}),
            "final_authority_pass": _post_acct_authority6212,
            "canonical_claims": _current_period_authority_report6212.get("canonical_claims") or [],
        }
        if isinstance(synthese_res, dict):
            synthese_res["output"] = str(outputs.get("synthese_decisions", "") or "")
        if isinstance(ceo_res, dict):
            ceo_res["output"] = str(outputs.get("ceo") or outputs.get("direction_generale") or "")
    except Exception as _post_acct_cpa_err6212:
        if diag_list is not None:
            diag_list.append({
                "role": "current_period_authority", "provider": "internal",
                "model": "current_period_page_confirmed_authority_v6212",
                "status": "POST_GUARD_ERROR",
                "error": f"{type(_post_acct_cpa_err6212).__name__}: {str(_post_acct_cpa_err6212)[:160]}",
            })

    # The action register must consume the same final governed narratives as
    # the Word and PPTX, never a pre-guard snapshot.
    _outputs_for_agenda48 = dict(outputs)

    # ─── v17.1.0-B2.3-F.2 — Registre d'actions d'agenda (minimal, fail-open) ──
    _agenda_register = None
    _agenda_register_md = ""
    try:
        from patches.agenda_register import build_register as _build_reg
        _dec_final = ""
        if _b23_guards and isinstance(_b23_guards.get("decision"), dict):
            _dec_final = _b23_guards["decision"].get("final", "") or ""
        # P0-5 temps 2 (M.5.3) — verdict affiché en EN dans le registre (token
        # de logique inchangé en amont ; traduction d'affichage uniquement).
        if lang == "en" and _dec_final:
            try:
                from patches.pipeline_guards_b23 import localize_verdict as _loc_verdict
                _dec_final = _loc_verdict(_dec_final, lang)
            except Exception:
                pass
        # S.2.4.1 — sources élargies : une action Supply Chain/Finance peut n'exister
        # que dans la sortie du rôle concerné (war room, dual sourcing, comptes
        # consolidés…) sans être reprise par la synthèse. La dédup + le filtre
        # _is_real_action gèrent le bruit.
        _reg_sources = [_outputs_for_agenda48.get("synthese_decisions", ""),
                        _outputs_for_agenda48.get("ceo", ""),
                        _outputs_for_agenda48.get("commercial", ""),
                        _outputs_for_agenda48.get("supply_chain", ""),
                        _outputs_for_agenda48.get("finance", ""),
                        _outputs_for_agenda48.get("strategie", ""),
                        _outputs_for_agenda48.get("marketing", "")]
        # FIX4 (M.5.8) — sous décision de RETRAIT, reformuler le vocabulaire
        # « GO / GO CONDITIONNEL » (trompeur sur un sommeil/sortie) en « À ARBITRER ».
        try:
            from patches.scenario_consistency import (
                is_winddown_recommended as _is_wd,
                reframe_winddown_decision as _reframe_wd,
            )
            if _is_wd(_dec_final, "\n".join(_reg_sources)):
                _new_final = _reframe_wd(_dec_final, lang)
                if _new_final != _dec_final:
                    _dec_final = _new_final
                    if _b23_guards and isinstance(_b23_guards.get("decision"), dict):
                        _b23_guards["decision"]["final"] = _dec_final
                        # M.5.10.7 — _reframe_wd est lang-aware : le final reframé est
                        # déjà dans la langue du run. On resynchronise final_en pour que
                        # le consommateur EN ne serve pas une valeur pré-reframe périmée.
                        if lang == "en":
                            _b23_guards["decision"]["final_en"] = _dec_final
                    if diag_list is not None:
                        diag_list.append({
                            "role": "decision_vocabulary", "provider": "internal",
                            "model": "decision_vocabulary_v1", "status": "REFRAMED",
                            "note": "Décision de retrait : « GO CONDITIONNEL » reformulé "
                                    "en « À ARBITRER » (vocabulaire cohérent).",
                        })
        except Exception:
            pass
        _reg = _build_reg(decision_final=_dec_final, sources_texts=_reg_sources,
                          genre=_genre.genre, lang=lang)
        # P0-3 (M.5.6) — si la décision est un RETRAIT, reclasser les actions de
        # croissance active HORS du plan principal (vers « axes conditionnels »).
        try:
            from patches.scenario_consistency import quarantine_incompatible_actions as _qia
            _n_quar = _qia(_reg, _dec_final, "\n".join(_reg_sources), lang)
            if _n_quar and diag_list is not None:
                diag_list.append({
                    "role": "scenario_consistency", "provider": "internal",
                    "model": "scenario_consistency_v1", "status": "RECLASSED",
                    "note": f"{_n_quar} action(s) de croissance active reclassée(s) hors "
                            f"plan principal (décision = retrait).",
                })
        except Exception:
            pass
        if len(_reg):
            _agenda_register = _reg.to_rows(lang)
            # Défense explicite au point de convergence + métrique de
            # quarantaine. Le même gate sera réappliqué avant persistance.
            try:
                from patches.agenda_register import (
                    filter_semantic_action_rows as _filter_actions61,
                    rows_to_markdown as _rows_to_md61,
                    is_separator_row as _is_sep61,
                )
                _agenda_register, _agenda_semantic_quarantine = _filter_actions61(
                    _agenda_register, preserve_separators=True)
                _agenda_register_md = _rows_to_md61(_agenda_register, lang)
                _semantic_visible61 = sum(
                    1 for _r61 in (_agenda_register or []) if not _is_sep61(_r61))
                _semantic_candidate61 = len(getattr(_reg, "items", []) or [])
                _semantic_quarantined_count61 = max(
                    len(_agenda_semantic_quarantine),
                    _semantic_candidate61 - _semantic_visible61)
                if _semantic_quarantined_count61 and diag_list is not None:
                    diag_list.append({
                        "role": "action_semantic_gate", "provider": "internal",
                        "model": "action_semantic_gate_b1361",
                        "status": "QUARANTINED",
                        "flagged": _semantic_quarantined_count61,
                        "summary": "faits/constats exclus du registre avant persistance",
                    })
            except Exception:
                _agenda_register_md = _reg.to_markdown(lang)
                _agenda_semantic_quarantine = []
                _semantic_quarantined_count61 = 0
            _status_conflicts47 = [r for r in (_agenda_register or [])
                                   if isinstance(r, dict) and r.get("statut_conflict")]
            if diag_list is not None:
                diag_list.append({
                    "role": "agenda_register", "provider": "internal",
                    "model": "agenda_register_v1", "status": "OK",
                    "actions_count": len(_reg), "genre": _genre.genre,
                })
                diag_list.append({
                    "role": "action_status_gate", "provider": "internal",
                    "model": "action_truth_guard_b1347_chatgpt",
                    "status": ("CONFLICTS_DEMOTED" if _status_conflicts47 else "OK"),
                    "flagged": len(_status_conflicts47),
                    "summary": (f"{len(_status_conflicts47)} statut(s) de complétion non prouvé(s) rétrogradé(s)"
                                if _status_conflicts47 else "aucun statut de complétion non prouvé"),
                    "samples": [
                        {"action": str(r.get("action", ""))[:120],
                         "echeance": str(r.get("echeance", ""))[:40],
                         "conflict": str(r.get("statut_conflict", ""))}
                        for r in _status_conflicts47[:5]
                    ],
                })
    except Exception:
        _agenda_register = None
        _agenda_register_md = ""

    # ── P0-3 (M.5.3) — Scenario Consistency Gate ─────────────────────────────
    # Confronte la décision réconciliée (retrait / mise en sommeil / sortie) aux
    # axes du plan (croissance active : marketing, prospection, recrutement…).
    # Cas dossier de conseil. Flag de lucidité — pas de correction silencieuse.
    try:
        from patches.scenario_consistency import attach_scenario_flag as _scc_attach
        _scc_decision = ""
        if _b23_guards and isinstance(_b23_guards.get("decision"), dict):
            _scc_decision = _b23_guards["decision"].get("final", "") or ""
        _scc_plan = "\n".join([
            outputs.get("strategie", "") or "",
            outputs.get("synthese_decisions", "") or "",
            outputs.get("ceo", "") or "",
            outputs.get("commercial", "") or "",
        ])
        # M.5.4 — calcule + ajoute le flag aux ALERTES PIPELINE (rendu CR).
        _scc_note = _scc_attach(_b23_guards, _scc_decision, _scc_plan, lang)
        if _scc_note:
            if logger:
                log_event(logger, "warning", "scenario_consistency", _scc_note[:160])
            if diag_list is not None:
                diag_list.append({
                    "role": "scenario_consistency", "provider": "internal",
                    "model": "scenario_consistency_v1", "status": "WARN",
                    "note": _scc_note,
                })
    except Exception:
        pass

    # ── B.1.3.20 (P0-B, run dossier industriel) — CONFLIT CONTEXTE/FAITS visible ────────
    # Post-promotion ledger (les faits tardifs sont désormais annotés) : si le
    # contexte est mono/social mais que des faits CONSOLIDÉ groupe existent,
    # bannière au canal ALERTES PIPELINE (rendu CR, comme P0-3) + diag CSV.
    # Le verdict des détecteurs touche enfin le livrable — plus seulement le
    # cap de score.
    try:
        from patches.perimeter_match import (
            context_facts_mismatch_note as _cfmn20)
        _ctxn20 = None
        try:
            _ctxn20 = (_b1_result or {}).get("context")
        except Exception:
            _ctxn20 = None
        if _ctxn20 is not None:
            # B.1.3.23 P0-B' — passe FINALE inconditionnelle : tout fait encore
            # MATCH_NA (shaper, ledger, créateurs tardifs) reçoit id canonique
            # + périmètre AVANT rendu (3.20 était conditionné au ledger : le
            # fait shaper « Valeur 2024 — CA consolidé » restait NA → ✅).
            try:
                from patches.perimeter_match import (
                    annotate_facts_perimeter as _afp23)
                from patches.fact_identity import (
                    canonical_metric_id as _cmi23)
                _late23 = [f for f in (getattr(_facts_table_built,
                                               "facts", []) or [])
                           if getattr(f, "perimeter_match", None)
                           in (None, "", "NA", "na")]
                for _f23 in _late23:
                    if not getattr(_f23, "metric_canonical_id", ""):
                        try:
                            _f23.metric_canonical_id = _cmi23(
                                getattr(_f23, "label", "") or "")
                        except Exception:
                            pass
                _afp23(_late23, _ctxn20)
            except Exception:
                pass
            _note20, _ncf20 = _cfmn20(
                getattr(_facts_table_built, "facts", []) or [], _ctxn20, lang)
            if _note20:
                if isinstance(_b23_guards, dict):
                    _b23_guards.setdefault("flags", [])
                    if _note20 not in _b23_guards["flags"]:
                        _b23_guards["flags"].append(_note20)
                    _b23_guards["run_not_validatable"] = True  # B.1.3.23 P0-D
                    _b23_guards.setdefault("run_block_reasons", []).append(
                        "conflit contexte/faits (périmètre)")
                if diag_list is not None:
                    diag_list.append({
                        "role": "context_contradiction", "provider": "internal",
                        "model": "perimeter_match_b1320", "status": "WARN",
                        "summary": (f"{_ncf20} fait(s) CONSOLIDÉ en contexte "
                                    "mono/social — contexte à requalifier "
                                    "(ambiguous_group)"),
                        "note": _note20[:300],
                    })
    except Exception:
        pass

    # ── B.1.3.20 (P1-C, run dossier agroalimentaire) — CONFLIT D'ENTITÉ AU BRIEF ──────────
    # Brique zéro : désignations de cible du brief vs entité résolue. Les
    # validateurs aval whitelistent les noms du brief par construction — une
    # contamination de gabarit (« situation de <société> » dans un brief Loc
    # Maria) leur est invisible. Bannière ALERTES PIPELINE + diag CSV.
    try:
        from patches.brief_entity_conflict import (
            detect_brief_entity_conflict as _dbec20)
        _resolved20 = ""
        try:
            _resolved20 = (_analysis_name_q or "").strip()
        except Exception:
            _resolved20 = ""
        if not _resolved20:
            try:
                _resolved20 = str(getattr(
                    (_b1_result or {}).get("context"), "target_entity", "") or "")
            except Exception:
                _resolved20 = ""
        _bec_note20, _bec_list20 = _dbec20(brief or "", _resolved20, lang)
        if _bec_note20:
            if isinstance(_b23_guards, dict):
                _b23_guards.setdefault("flags", [])
                if _bec_note20 not in _b23_guards["flags"]:
                    _b23_guards["flags"].append(_bec_note20)
                _b23_guards["run_not_validatable"] = True  # B.1.3.23 P0-D
                _b23_guards.setdefault("run_block_reasons", []).append(
                    "conflit d'entité au brief")
            if diag_list is not None:
                diag_list.append({
                    "role": "brief_entity_conflict", "provider": "internal",
                    "model": "brief_entity_conflict_b1320", "status": "WARN",
                    "summary": (f"désignation(s) contradictoire(s) au brief : "
                                f"{' ; '.join(_bec_list20[:3])} vs entité "
                                f"résolue '{_resolved20}' — clarification requise"),
                })
    except Exception:
        pass

    # ── Cycle C — Registre MULTI-SÉANCES ─────────────────────────────────────
    # Persiste les actions de CE run dans l'historique append-only du dossier et
    # réconcilie avec les CoDIR précédents (reconduites, relances, retard,
    # clôtures explicites). L'usage hérite de la gouvernance F.4.3 : si la table
    # financière est plafonnée (poste dérivé/contradiction), le run n'est PAS
    # board-safe et les actions gardent ce niveau. Fail-open.
    _codir_history = None
    try:
        # Gate 14 — ISOLATION : une autorité INVALID/CONFLICT/ERROR
        # n'ÉCRIT pas l'état persistant : zéro append JSONL, zéro
        # décision/relance, zéro mutation codir_history. Les actions du
        # run restent un BROUILLON (agenda_register au result seulement).
        _ta_blocked_reg14 = locals().get("_scenario_status") in ("INVALID",
                                                                 "ERROR")
        # Gate 16 — read-only par construction : un run rétrospectif ou
        # futur (policy non-LIVE) n'écrit NI journal, NI décision, NI
        # relance. Diagnostic dédié, distinct du blocage d'autorité.
        _tp16 = locals().get("_temporal_policy16")
        _ro_blocked16 = False
        try:
            from patches.temporal_policy import (can_persist as _cp16,
                                                 SINK_ACTION_JOURNAL
                                                 as _SAJ16)
            _ro_blocked16 = (not _ta_blocked_reg14 and
                             not _cp16(_tp16, _SAJ16))
        except Exception:
            _ro_blocked16 = not _ta_blocked_reg14
        if _agenda_register and _ro_blocked16:
            try:
                if diag_list is not None:
                    diag_list.append({
                        "role": "codir_register", "provider": "internal",
                        "model": "gate16",
                        "status": "SKIPPED_TEMPORAL_POLICY_READ_ONLY",
                        "policy_mode": getattr(_tp16, "mode", "")})
            except Exception:
                pass
        if _agenda_register and _ta_blocked_reg14:
            try:
                if diag_list is not None:
                    diag_list.append({
                        "role": "codir_register", "provider": "internal",
                        "model": "gate14",
                        "status": "SKIPPED_TEMPORAL_AUTHORITY"})
            except Exception:
                pass
        # Gate 18 — le snapshot ne dépend PLUS du brouillon : la lecture
        # s'exécute dès que le run n'est pas bloqué (l'utilisateur en
        # backtest voit son historique même si le run courant ne produit
        # aucune action) ; seule l'écriture exige des actions.
        if not _ta_blocked_reg14:
            from patches import codir_register_history as _crh
            from datetime import date as _date_c
            _soc = ""
            try:
                _cp = _company_profile.to_dict() if _company_profile else {}
                _soc = (_cp.get("name") or _cp.get("company_name")
                        or _cp.get("denomination") or "")
            except Exception:
                _soc = ""
            _dossier_label = ""
            try:
                # F.5.2 : settings est un objet (dataclass), pas un dict — lecture
                # par getattr (le .get() de F.5.1 était mort et renvoyait toujours "").
                if isinstance(settings, dict):
                    _dossier_label = settings.get("dossier_label", "") or ""
                else:
                    _dossier_label = getattr(settings, "dossier_label", "") or ""
            except Exception:
                _dossier_label = ""
            # B.1.3.19 (run 11 : action HEVO/dossier industriel (composants) dans le CR dossier anglophone coté —
            # contamination inter-dossiers, racine PROUVÉE) : sans profil ni
            # label, compute_dossier_id retombait sur le slug COMMUN
            # « dossier » — tous ces runs partageaient le même .jsonl.
            # Repli sur l'ENTITÉ RÉSOLUE B.1 (fingerprint, toujours posée) ;
            # sans AUCUNE identité, le registre est SKIPPÉ (ni lecture ni
            # écriture) : pas de registre plutôt qu'un registre partagé.
            if not _soc:
                _soc = str(_resolved_name or "").strip()
            if not (_soc or _dossier_label):
                if logger:
                    log_event(logger, "warning", "codir_engine",
                              "register_skipped_no_dossier_identity")
                raise RuntimeError("register skipped: no dossier identity")
            _dossier_source = "libellé explicite" if _dossier_label else ""
            # P0-1 (F.5.1) : en l'absence de libellé explicite, on synthétise un
            # discriminant STABLE = société + genre. Le « sujet » d'une séance change
            # chaque semaine → l'utiliser fragmenterait un CoDIR récurrent ; le genre,
            # lui, sépare une analyse standalone d'une décision M&A sur la même société
            # sans casser le fil hebdomadaire. Le libellé explicite reste prioritaire
            # (ex. « acquéreur X / cible Y » pour un dossier M&A précis).
            if not _dossier_label and _soc:
                try:
                    _gname = getattr(_genre, "genre", "") or ""
                except Exception:
                    _gname = ""
                _dossier_label = f"{_soc} [{_gname}]" if _gname else _soc
                _dossier_source = "repli société + genre"
            try:
                # Gate 12 — le run_id et l'ingestion utilisent la DATE
                # RÉELLE (traçabilité) ; l'AUTORITÉ voyage séparément dans
                # analysis_date. Le gate 11 écrivait l'autorité dans
                # run_date : le même événement portait deux dates
                # contradictoires (run_date=2023, ts=2026).
                _run_date_iso = (_run_now.date().isoformat()
                                 if "_run_now" in locals() else None)
                if not _run_date_iso:
                    _run_date_iso = ""
                _analysis_iso_c = (_b23_rd.isoformat()
                                   if hasattr(_b23_rd, "isoformat")
                                   else (str(_b23_rd) if _b23_rd else ""))
            except Exception:
                # fail-closed : jamais l'horloge système ici.
                _run_date_iso, _analysis_iso_c = "", ""
            _dec_assoc = _dec_final if "_dec_final" in locals() else ""
            _usage_c = _crh.USAGE_INDICATIF
            try:
                if (_facts_table_built is not None and
                        getattr(_facts_table_built, "_coherence_capped", False)):
                    _usage_c = _crh.USAGE_NON_BOARD_SAFE
            except Exception:
                pass
            # P0-4 (F.5.1) : score de confiance du run propagé sur les actions.
            _run_score = None
            try:
                if isinstance(_confidence_score, dict):
                    _run_score = _confidence_score.get("score")
            except Exception:
                _run_score = None
            _did_c = _crh.compute_dossier_id(societe=_soc, dossier_label=_dossier_label)
            _rid_c = _crh.make_run_id(_soc or _did_c, _run_date_iso)
            # P0-3 (F.5.1) : actions ouvertes AVANT ce run = ce qui vient du CoDIR
            # précédent et reste « à traiter dans ce CoDIR ». Capturé avant ingest.
            # F.6.8 (audit ChatGPT) — date d'analyse passée à l'historique : une
            # action datée 2023 ne doit pas être « en retard » par rapport au run 2026.
            # Gate 19 (P1-G18-05) — l'autorité du snapshot vient de la
            # POLICY canonique validée (convertie en date, le type des
            # lectures as_of), pas d'une variable de garde ; B2.3 la
            # consomme, il ne la recrée pas. Repli conservateur sur
            # _b23_rd si la policy est bloquée ou illisible.
            _tp19 = locals().get("_temporal_policy16")
            _hist_as_of = None
            try:
                from datetime import date as _d19
                if getattr(_tp19, "mode", "") in (
                        "LIVE_MUTATING", "RETROSPECTIVE_READ_ONLY",
                        "FUTURE_SIMULATION_READ_ONLY") and \
                        getattr(_tp19, "analysis_date", ""):
                    _hist_as_of = _d19.fromisoformat(
                        _tp19.analysis_date)
            except Exception:
                _hist_as_of = None
            if _hist_as_of is None:
                _hist_as_of = _b23_rd if "_b23_rd" in dir() else None
            try:
                from patches import history_hygiene as _hh626
                _ignore_history626 = bool(_hh626.ignore_history_enabled())
            except Exception:
                _ignore_history626 = False
            if _ignore_history626:
                _carried_in = []
            else:
                try:
                    _carried_in = [a.__dict__ for a in
                                   _crh.open_actions(_did_c, as_of=_hist_as_of)]
                except Exception:
                    _carried_in = []
            # M.5.9 (FIX E1) — ne JAMAIS ingérer le séparateur « Axes conditionnels »
            # (en-tête de section) dans l'historique du dossier : ce n'est pas une
            # action. Il fuyait en M.5.8 dans le suivi multi-séances.
            try:
                from patches.agenda_register import (
                    filter_semantic_action_rows as _filter_hist_actions61,
                    is_separator_row as _is_sep,
                )
                _hist_candidates61 = [r for r in (_agenda_register or []) if not _is_sep(r)]
                _hist_actions, _hist_semantic_quarantine61 = _filter_hist_actions61(
                    _hist_candidates61, preserve_separators=False)
                if _hist_semantic_quarantine61 and diag_list is not None:
                    diag_list.append({
                        "role": "history_semantic_gate", "provider": "internal",
                        "model": "history_semantic_gate_b1361",
                        "status": "QUARANTINED",
                        "flagged": len(_hist_semantic_quarantine61),
                        "summary": "lignes non pilotables exclues avant journal JSONL",
                    })
            except Exception:
                _hist_actions = []  # fail-closed : ne jamais persister du bruit
                _hist_semantic_quarantine61 = list(_agenda_register or [])
            # Gate 17 — SPLIT read/write : la LECTURE du snapshot
            # point-in-time (ci-dessus et ci-dessous) s'exécute pour
            # tout run non bloqué ; seule l'ÉCRITURE est gardée par la
            # policy. Un run rétro/futur restitue son état structuré
            # (codir_history) sans jamais persister.
            if not _ro_blocked16 and _hist_actions and not _ignore_history626:
                # v62.13.9.4.50 — les STATUTS que le brief du dirigeant donne aux actions (réalisée, reportée,
                # abandonnée) sont une validation humaine : appliqués AVANT l'ingestion du run, pour que la séance se
                # réconcilie avec l'état à jour (contre-recette du 30/09 : aucune action close en séance 2)
                try:   # 9.4.52 — rapprochement de chaque statut déclaré (certaine / ambiguë / non retrouvée), pour le CR
                    meta["brief_status_matches52"] = _crh.match_brief_statuses52(
                        _did_c, str(brief or ""), analysis_authority=_analysis_iso_c)
                except Exception:
                    meta["brief_status_matches52"] = []
                try:   # 9.4.57 — instructions non résolues des séances précédentes (§4.4), puis mise à jour après cette séance
                    _now57 = [d.get("action", "") for d in _crh.parse_brief_statuses(str(brief or ""))]
                    meta["unresolved57"] = [u for u in _crh.load_unresolved57(_did_c)
                                            if not any(_crh._same_instruction57(u.get("action", ""), x) for x in _now57)]
                    _crh.record_unresolved57(_did_c, meta.get("brief_status_matches52") or [], str(_analysis_iso_c or "")[:10])
                except Exception:
                    meta["unresolved57"] = []
                try:
                    _brief_st50 = _crh.apply_brief_statuses(
                        _did_c, str(brief or ""), _rid_c, _run_date_iso, analysis_date=_analysis_iso_c)
                except Exception:
                    _brief_st50 = []
                _hist_events48 = _crh.ingest_run(
                    _did_c, _rid_c, _run_date_iso, _soc,
                    actions=_hist_actions, decision_associee=_dec_assoc,
                    usage_level=_usage_c, run_score=_run_score,
                    analysis_date=_analysis_iso_c,
                    auto_relance_unconfirmed=False)
            else:
                _hist_events48 = []

            # B.1.3.48-chatgpt — une action clôturée qui réapparaît ne doit pas
            # rester « À lancer » dans le registre courant pendant que l'historique
            # la dit « À arbitrer ». On aligne les rows AVANT de construire result.
            try:
                _n_reapp48 = _crh.reconcile_reappeared_rows(
                    _agenda_register, _hist_events48, lang=lang)
                if _n_reapp48:
                    from patches.agenda_register import rows_to_markdown as _rows_md48
                    _agenda_register_md = _rows_md48(_agenda_register, lang)
                    if diag_list is not None:
                        diag_list.append({
                            "role": "action_reappeared_gate", "provider": "internal",
                            "model": "action_reappeared_b1348_chatgpt",
                            "status": "ARBITRATION_REQUIRED", "flagged": _n_reapp48,
                            "summary": (f"{_n_reapp48} action(s) clôturée(s) réapparue(s) : "
                                        "maintenues fermées et affichées À arbitrer"),
                        })
            except Exception as _reapp_err48:
                if diag_list is not None:
                    diag_list.append({
                        "role": "action_reappeared_gate", "provider": "internal",
                        "model": "action_reappeared_b1348_chatgpt",
                        "status": "FAILED",
                        "error": f"{type(_reapp_err48).__name__}: {str(_reapp_err48)[:160]}",
                    })
            try:
                _reapparues_c = [a.__dict__ for a in
                                 _crh.buckets(_did_c, as_of=_hist_as_of).get("reapparues", [])]
            except Exception:
                _reapparues_c = []
            if _ignore_history626:
                _codir_history = None
            else:
                _codir_history = {
                    "dossier_id":      _did_c,
                    "dossier_source":  _dossier_source,
                    "run_id":          _rid_c,
                    "carried_in":      _carried_in,
                    "open_actions":    [a.__dict__ for a in
                                        _crh.open_actions(_did_c, as_of=_hist_as_of)],
                    "reapparues":      _reapparues_c,
                    # Gate 15 — inclusion filtrée par l'autorité du run.
                    "timeline":        _crh.dossier_timeline(
                        _did_c, as_of=_hist_as_of),
                    "decision_ecarts": _crh.decision_ecarts(
                        _did_c, as_of=_hist_as_of),
                    "markdown":        _crh.to_markdown(_did_c, lang=lang, as_of=_hist_as_of) + _crh.unrecognized_md64(
                        str(brief or ""), lang) + _crh.unmatched_statuses_md52(
                    meta.get("brief_status_matches52") or [], lang) + _crh.unresolved_md57(meta.get("unresolved57") or [], lang),
                    "semantic_quarantine_count": _crh.build_history_snapshot(
                        _did_c, _hist_as_of, lang=lang).get(
                            "semantic_quarantine_count", 0),
                }
            # M.5.10.10 (audit dossier anglophone coté) — HYGIÈNE HISTORIQUE.
            # (1) Mode « run propre sans historique » (CODIR_IGNORE_HISTORY) :
            #     l'historique est ignoré, rien n'est reporté.
            # (2) Sinon, purge des actions solo/business-development de l'opérateur
            #     (LinkedIn hebdo, cabinets de transition, newsletter de prospection,
            #     TJM, pipeline solo) qui n'ont pas leur place dans l'analyse d'une
            #     société cliente. Elles sortent du flux actif vers une quarantaine
            #     « legacy / non reportée » (vue rendue seulement ; journal intact).
            try:
                from patches import history_hygiene as _hh
                if _hh.ignore_history_enabled():
                    _codir_history = None
                else:
                    _purged_legacy = _hh.purge_solo_marketing(_codir_history)
                    if _purged_legacy and isinstance(_codir_history.get("markdown"), str):
                        _codir_history["markdown"] += (
                            f"\n\n> ⚠ {_purged_legacy} action(s) « legacy » solo/business "
                            f"development (LinkedIn/cabinets/newsletter/TJM) écartée(s) du "
                            f"registre courant — non reportée(s) pour ce dossier.")
                    # M.5.10.10 (Action 3) — le bloc historique (markdown + actions)
                    # n'est pas dans result["outputs"] : il échappait au chokepoint
                    # épistémique. On localise [NON SOURCÉ]/… et « éch. » → « due » en EN.
                    if (lang or "fr").lower() == "en" and _codir_history:
                        try:
                            from patches.output_hygiene import localize_epistemic_tags as _let

                            def _loc_hist(_v):
                                if not isinstance(_v, str):
                                    return _v
                                return _let(_v, "en").replace("éch.", "due").replace("Éch.", "Due")
                            if isinstance(_codir_history.get("markdown"), str):
                                _codir_history["markdown"] = _loc_hist(_codir_history["markdown"])
                            for _k in ("open_actions", "carried_in", "reapparues"):
                                for _a in (_codir_history.get(_k) or []):
                                    if isinstance(_a, dict):
                                        for _f in ("action", "sujet", "decision",
                                                   "next_step", "echeance", "statut"):
                                            if isinstance(_a.get(_f), str):
                                                _a[_f] = _loc_hist(_a[_f])
                        except Exception:
                            pass
            except Exception:
                pass
            # F.6.8 (audit ChatGPT) — scrub d'AFFICHAGE de l'historique multi-séances
            # en séance ALERTS_ONLY : une ancienne action « GO sur… » du registre ne
            # doit pas réapparaître dans le suivi/registre/deck. Journal append-only
            # NON modifié — on ne nettoie que la vue rendue (result).
            if _codir_history and getattr(_genre, "forbids_go_nogo", False):
                try:
                    from patches.alerts_only_scrubber import scrub_go_nogo as _scrub_h

                    def _scrub_acts(_lst):
                        for _a in (_lst or []):
                            if isinstance(_a, dict):
                                for _k in ("action", "sujet", "decision", "next_step"):
                                    if isinstance(_a.get(_k), str):
                                        _a[_k] = _scrub_h(_a[_k])
                        return _lst
                    _scrub_acts(_codir_history.get("carried_in"))
                    _scrub_acts(_codir_history.get("open_actions"))
                    _scrub_acts(_codir_history.get("reapparues"))
                    for _tl in (_codir_history.get("timeline") or []):
                        if isinstance(_tl, dict) and isinstance(_tl.get("decision"), str):
                            _tl["decision"] = _scrub_h(_tl["decision"])
                    if isinstance(_codir_history.get("markdown"), str):
                        _codir_history["markdown"] = _scrub_h(_codir_history["markdown"])
                except Exception:
                    pass
            # F.6.10 (audit dossier réseau de soins F.6.9) — QUARANTAINE HISTORIQUE : en analyse
            # historique (as_of passé), une action citant une année POSTÉRIEURE à
            # l'analyse n'est plus seulement signalée : elle est SORTIE du flux actif
            # (open_actions / carried_in / réapparues) vers un bloc « historique
            # incohérent (ignoré) », pour ne jamais polluer le registre courant ni
            # les recommandations. Visible mais hors décision. Journal intact.
            try:
                _as_of_year = getattr(_hist_as_of, "year", None)
            except Exception:
                _as_of_year = None
            if _as_of_year and _codir_history:
                try:
                    import re as _re_tmp
                    _quarantined = []

                    # Gate 12 — la quarantaine juge la PROVENANCE de
                    # l'événement (l'autorité sous laquelle l'action a été
                    # créée), JAMAIS l'année de son échéance : dans un plan
                    # 2023, une échéance 2024 est une action FUTURE normale.
                    # Une action créée sous autorité 2026 réinjectée dans une
                    # séance 2023 reste exclue (provenance postérieure).
                    _auth_iso_q = (_b23_rd.isoformat()
                                   if hasattr(_b23_rd, "isoformat")
                                   else (str(_b23_rd) if _b23_rd else ""))

                    def _is_foreign_provenance(_a):
                        if not isinstance(_a, dict) or not _auth_iso_q:
                            return False
                        _prov = (_a.get("analysis_date")
                                 or _a.get("first_run_date") or "")
                        return bool(_prov) and str(_prov)[:10] > _auth_iso_q

                    def _quarantine(_key):
                        _lst = _codir_history.get(_key)
                        if not isinstance(_lst, list):
                            return
                        _kept = []
                        for _a in _lst:
                            if _is_foreign_provenance(_a):
                                if isinstance(_a, dict):
                                    _prov = (_a.get("analysis_date")
                                             or _a.get("first_run_date") or "")
                                    _a["quarantine_reason"] = (
                                        f"provenance {_prov} postérieure à "
                                        f"l'autorité d'analyse {_auth_iso_q} — "
                                        f"exclue du registre courant")
                                    _a["statut"] = "Ignorée (provenance postérieure)"
                                _quarantined.append(_a)
                            else:
                                _kept.append(_a)
                        _codir_history[_key] = _kept

                    _quarantine("carried_in")
                    _quarantine("open_actions")
                    _quarantine("reapparues")
                    if _quarantined:
                        _codir_history["quarantined_incoherent"] = _quarantined
                        _qn = len(_quarantined)
                        _note = (f"\n\n> ⚠ {_qn} action(s) d'historique de "
                                 f"provenance postérieure à l'autorité d'analyse "
                                 f"mise(s) en quarantaine — exclue(s) du registre "
                                 f"courant et des recommandations.")
                        if isinstance(_codir_history.get("markdown"), str):
                            _codir_history["markdown"] += _note
                except Exception:
                    pass
            if diag_list is not None and _codir_history:
                diag_list.append({
                    "role": "codir_register_history", "provider": "internal",
                    "model": "codir_register_history_C0", "status": "OK",
                    "dossier_id": _did_c,
                    "open_actions": len(_codir_history["open_actions"]),
                    "runs_in_history": len(_codir_history["timeline"]),
                })
    except Exception:
        _codir_history = None

    # B.1.3.56 Gate 11 — contrat temporel explicite au niveau racine.
    # ``run_date`` reste la date réelle d'exécution (traçabilité), tandis que
    # ``analysis_date`` / ``temporal_authority_date`` portent la date qui doit
    # gouverner les échéances dans tous les renderers. En scénario rétrospectif,
    # cette dernière est la date demandée par l'utilisateur.
    try:
        _actual_run_date_out = (_run_now.date().isoformat()
                                if "_run_now" in locals() else None)
    except Exception:
        _actual_run_date_out = None
    try:
        _temporal_authority_out = (_b23_rd.isoformat()
                                   if hasattr(_b23_rd, "isoformat")
                                   else str(_b23_rd) if _b23_rd else None)
    except Exception:
        _temporal_authority_out = (_analysis_as_of or _actual_run_date_out)

    # Gate 12 — objet TemporalAuthority unique (P0-A) ; en INVALID :
    # aucune autorité, run non validable, bandeau visible, diagnostic.
    _scn_status_out = locals().get("_scenario_status", "NOT_REQUESTED")
    _scn_raw_out = locals().get("_scenario_raw", "")
    _run_block_reasons_out = None
    if _scn_status_out in ("INVALID", "ERROR"):
        _temporal_authority_out = None
        try:
            _is_err = _scn_status_out == "ERROR"
            _probe14 = locals().get("_scenario_probe") or {}
            _code13 = (_probe14.get("error_code") or
                       ("TEMPORAL_AUTHORITY_ERROR" if _is_err
                        else "TEMPORAL_AUTHORITY_INVALID"))
            _is_conflict14 = _code13 == "TEMPORAL_AUTHORITY_CONFLICT"
            # Gate 13 — le TOKEN de motif ouvre le bandeau : même tronqué
            # par une slide, « autorité temporelle invalide » /
            # « temporal authority invalid » reste lisible.
            if _is_err:
                _banner_fr = ("⛔ Autorité temporelle indisponible — panne du "
                              "détecteur de date d'analyse : présentation "
                              "client, conseil et diffusion BLOQUÉS.")
                _banner_en = ("⛔ Temporal authority unavailable — "
                              "analysis-date detector failure: client "
                              "presentation, advice and distribution BLOCKED.")
            elif _is_conflict14:
                _banner_fr = ("⛔ Autorité temporelle en conflit — deux "
                              "dates d'analyse distinctes demandées ("
                              + str(_scn_raw_out)
                              + ") : présentation client, conseil et "
                                "diffusion BLOQUÉS.")
                _banner_en = ("⛔ Temporal authority conflict — two "
                              "distinct analysis dates requested ("
                              + str(_scn_raw_out)
                              + "): client presentation, advice and "
                                "distribution BLOCKED.")
            else:
                _banner_fr = ("⛔ Autorité temporelle invalide — date "
                              "d'analyse demandée illisible ("
                              + str(_scn_raw_out)
                              + ") : présentation client, conseil et "
                                "diffusion BLOQUÉS.")
                _banner_en = ("⛔ Temporal authority invalid — requested "
                              "analysis date unreadable ("
                              + str(_scn_raw_out)
                              + "): client presentation, advice and "
                                "distribution BLOCKED.")
            _run_block_reasons_out = [{
                "code": _code13, "raw_value": str(_scn_raw_out),
                "message_fr": _banner_fr, "message_en": _banner_en}]
            # Gate 15 (P1 i18n) — UN SEUL message visible, dans la langue
            # du run ; les deux traductions restent structurées dans
            # run_block_reasons (message_fr + message_en).
            _banner_vis = (_banner_en if str(locals().get("lang") or
                                             "fr").lower().startswith("en")
                           else _banner_fr)
            if isinstance(_b23_guards, dict):
                _b23_guards.setdefault("flags", []).append(_banner_vis)
                _b23_guards["run_not_validatable"] = True
            # Gate 13 — la raison doit être VISIBLE sur les surfaces : le
            # bandeau est injecté en tête du premier output (il descend au
            # CR/DOCX et au deck générés depuis les outputs).
            try:
                if isinstance(outputs, dict) and outputs:
                    _k0 = next(iter(outputs))
                    outputs[_k0] = (_banner_vis + "\n\n" +
                                    str(outputs.get(_k0) or ""))
            except Exception:
                pass
            if diag_list is not None:
                diag_list.append({
                    "role": "temporal_authority", "provider": "internal",
                    "model": "gate13", "status": _code13,
                    "raw_value": str(_scn_raw_out)})
        except Exception:
            pass
    _temporal_authority_obj = {
        # TCR-v16 — empreinte de l'entrée temporelle, indispensable au
        # refus de candidate côté interface (A5).
        "input_fingerprint": (
            getattr(locals().get("_tctx19"), "input_fingerprint", "")
            or str(temporal_input_fingerprint or "") or None),
        "run_date": _actual_run_date_out,
        "analysis_date": (_temporal_authority_out
                          if _scn_status_out not in ("INVALID", "ERROR")
                          else None),
        "scenario_requested": _scn_status_out != "NOT_REQUESTED",
        "scenario_raw_value": _scn_raw_out,
        "scenario_status": _scn_status_out,
        "status": _scn_status_out,
        "policy": (locals().get("_temporal_policy16").to_dict()
                   if hasattr(locals().get("_temporal_policy16"),
                              "to_dict") else {}),
        "conflict": bool((locals().get("_scenario_probe") or
                          {}).get("conflict")),
        "candidates": ((locals().get("_scenario_probe") or
                        {}).get("candidates") or []),
        "error_code": ((locals().get("_scenario_probe") or
                        {}).get("error_code") or
                       ("TEMPORAL_AUTHORITY_INVALID"
                        if _scn_status_out == "INVALID"
                        else ("TEMPORAL_AUTHORITY_ERROR"
                              if _scn_status_out == "ERROR" else ""))),
        "source": ("brief" if _scn_status_out != "NOT_REQUESTED"
                   else "default_run"),
        "intent_source": ((locals().get("_scenario_probe") or
                           {}).get("intent_source") or "NONE"),
        "candidate_value": ((locals().get("_scenario_probe") or
                             {}).get("candidate_value")),
        "candidate_raw": ((locals().get("_scenario_probe") or
                           {}).get("candidate_raw") or ""),
    }
    try:
        from patches.agent_prompt_boundary import (set_current_policy
                                                   as _scp19f)
        _scp19f(None)  # le state frontière meurt avec le run
    except Exception:
        pass
    # v62.13.9.4.11 (A1) — index des grandeurs DÉCLARÉES par les agents.
    # Les agents décrivent, au moment où ils l'écrivent, ce que chaque nombre
    # engage (fait, cible, option, scénario, appareil). La chaîne de sûreté
    # lit cet index par ``result["declared_quantities"]`` et l'ajoute à son
    # analyse textuelle — jamais en remplacement : une déclaration retient
    # davantage, elle ne relâche jamais. Fail-open sur la construction : sans
    # index, le comportement est celui du cycle précédent.
    # v62.13.9.4.18 — complément narratif pour chaque rôle, AVANT l'index
    # déclaré : les valeurs de la prose sans déclaration sont visées.
    def _a1_cd62418(var_value, role):
        try:
            txt = next((e.get("raw_output") or "" for e in _AGENT_RAW_ARCHIVE
                        if e.get("role") == role), "")
            if var_value is None or not txt:
                return var_value
            out = _a1_complete_declarations(txt, var_value, role, settings,
                                            logger=logger, cb=cb, diag_list=diag_list)
            try:                                       # v62.13.9.4.19.1 — rattachement intra-rôle
                from utils.declared_quantities import backfill_claim_quantities as _bcq
                n = _bcq(out)
                if n and diag_list is not None:
                    diag_list.append({"role": f"{role}_agent_json_backfill", "provider": "internal",
                                      "model": "n/a", "status": "OK", "quantities_backfilled": n})
            except Exception:
                pass
            return out
        except Exception as _ce62418:
            if logger:
                log_event(logger, "warning", "agent_json", f"{role}: complément narratif ignoré : {_ce62418}")
            return var_value
    _strategie_agent_output = _a1_cd62418(locals().get("_strategie_agent_output"), "strategie")
    _brief_codir_agent_output = _a1_cd62418(locals().get("_brief_codir_agent_output"), "brief_codir")
    _marketing_agent_output = _a1_cd62418(locals().get("_marketing_agent_output"), "marketing")
    _finance_agent_output = _a1_cd62418(locals().get("_finance_agent_output"), "finance")
    _commercial_agent_output = _a1_cd62418(locals().get("_commercial_agent_output"), "commercial")
    _supply_chain_agent_output = _a1_cd62418(locals().get("_supply_chain_agent_output"), "supply_chain")
    _synthese_agent_output = _a1_cd62418(locals().get("_synthese_agent_output"), "synthese_decisions")
    _dg_agent_output = _a1_cd62418(locals().get("_dg_agent_output"), "dg")
    _declared_index62411 = None
    try:
        from utils.declared_quantities import build_declared_index as _bdi62411
        _declared_index62411 = _bdi62411([
            locals().get("_strategie_agent_output"),
            locals().get("_brief_codir_agent_output"),
            locals().get("_marketing_agent_output"),
            locals().get("_finance_agent_output"),
            locals().get("_commercial_agent_output"),      # v62.13.9.4.12
            locals().get("_supply_chain_agent_output"),    # v62.13.9.4.12
            locals().get("_synthese_agent_output"),
            locals().get("_dg_agent_output"),
        ])
        # COVERAGE GATE — v62.13.9.4.12. Une claim qui porte des chiffres
        # sans aucune grandeur déclarée est une lacune de couverture, pas un
        # feu vert : le cycle précédent la laissait passer en silence
        # (fail-open). On la compte et on l'expose ; l'analyse textuelle
        # reste le filet, mais la lacune devient visible et mesurable.
        # v62.13.9.4.37 — NIVEAU 1 (posé APRÈS la construction de l'index déclaré) : tout fait déclaré FAIT/CONSTATÉ par un agent et
        # retrouvé à la page dans N'IMPORTE QUELLE pièce jointe (acte, statuts, rapport,
        # traité de fusion…) entre dans les faits de soutien avec pièce et page. Run
        # réel du 18/09/2026 : le compte rendu était retenu sur deux montants écrits en
        # clair dans le traité de fusion fourni — la preuve ne lisait que seize
        # métriques d'états financiers. Décision de Robin : la vérification est le
        # critère, pas la nature de la pièce.
        try:
            from utils.financial_proof_layer import (parse_paged_corpus as _ppc37,
                                                     confirm_declared_facts_in_corpus as _cdf37)
            _idx37 = locals().get("_declared_index62411")
            _decl37 = _idx37.all_entries() if hasattr(_idx37, "all_entries") else []
            _pages37 = _ppc37(locals().get("financial_statements_block") or "",
                              locals().get("attachments_block") or "")
            _extra37 = _cdf37(_decl37, _pages37, lang=lang) if (_decl37 and _pages37) else []
            # NIVEAU 2 — registre externe (Pappers, GLEIF, SEC) : le bloc de registre est
            # une « page » de plus, sous l'étiquette CONFIRMED_AT_REGISTRY, avec le
            # registre et la date de consultation pour pièce. INACTIF en mode
            # rétrospectif : une donnée de registre à la date du run n'a rien à faire
            # dans une analyse au 15/02/2023. Robin (18/09/2026) : option 1 — le bloc
            # comme page, sans parseur structuré.
            try:
                from utils.financial_proof_layer import PageRecord as _PR37, CONFIRMED_AT_REGISTRY as _CAR37
                _tp37 = locals().get("_temporal_policy16")
                _pol37 = str(getattr(_tp37, "mode", "") or (_tp37.get("mode") if isinstance(_tp37, dict) else "") or "")
                _retro37 = "RETROSPECTIVE" in _pol37.upper()
                if not _retro37:
                    # la date de consultation est la DATE DU RUN portée par la politique
                    # temporelle — jamais l'horloge de la machine (contrat d'autorité
                    # temporelle : aucun « aujourd'hui » sur un chemin de vérité).
                    _today37 = str(getattr(_tp37, "run_date", "") or (locals().get("_run_date_iso") or "") or "date du run")
                    _reg_pages37 = []
                    for _rname37, _rblock37 in (("Pappers", locals().get("_pap_full") or ""),
                                                ("GLEIF", (locals().get("_gleif_blocks") or {}).get("full", "") if isinstance(locals().get("_gleif_blocks"), dict) else ""),
                                                ("SEC EDGAR", (locals().get("_sec_blocks") or {}).get("full", "") if isinstance(locals().get("_sec_blocks"), dict) else "")):
                        if isinstance(_rblock37, str) and _rblock37.strip():
                            _reg_pages37.append(_PR37(f"{_rname37} — consulté le {_today37} (donnée à la date du dépôt)", 1, "registry", _rblock37, "registry"))
                    if _decl37 and _reg_pages37:
                        _reg37 = _cdf37(_decl37, _reg_pages37, lang=lang)
                        for _c37 in _reg37:
                            _c37["proof_status"] = _CAR37
                            _c37["provenance"] = "declared_fact_found_in_registry"
                        _extra37 = list(_extra37) + _reg37
            except Exception:
                pass
            if _extra37:
                _known37 = {(str(c.get("value")), str(c.get("metric_id"))) for c in _numeric_support_claims62131}
                _numeric_support_claims62131 = list(_numeric_support_claims62131) + [
                    c for c in _extra37 if (str(c.get("value")), str(c.get("metric_id"))) not in _known37]
        except Exception:
            pass
        _cov_total62412 = _cov_missing62412 = 0
        try:
            import re as _re62412
            for _ao62412 in (locals().get("_strategie_agent_output"),
                             locals().get("_brief_codir_agent_output"),
                             locals().get("_marketing_agent_output"),
                             locals().get("_finance_agent_output"),
                             locals().get("_commercial_agent_output"),
                             locals().get("_supply_chain_agent_output"),
                             locals().get("_synthese_agent_output"),
                             locals().get("_dg_agent_output")):
                for _cl62412 in (getattr(_ao62412, "claims", None) or ()):
                    if not _re62412.search(r"\d", str(getattr(_cl62412, "text", ""))):
                        continue
                    _cov_total62412 += 1
                    if not (getattr(_cl62412, "quantities", None) or ()):
                        _cov_missing62412 += 1
        except Exception:
            pass
        if diag_list is not None:
            diag_list.append({
                "role": "declared_quantities_index",
                "provider": "internal",
                "model": "declared_quantities_v62411",
                "status": "OK" if _declared_index62411 else "EMPTY",
                "claims_with_numbers": _cov_total62412,
                "claims_without_declaration": _cov_missing62412,
                "coverage_gate": ("OK" if _cov_missing62412 == 0
                                  else "INCOMPLETE"),
                **_declared_index62411.to_diagnostic(),
            })
    except Exception as _dq_exc62411:
        if diag_list is not None:
            diag_list.append({
                "role": "declared_quantities_index",
                "provider": "internal",
                "model": "declared_quantities_v62411",
                "status": "ERROR",
                "error": f"{type(_dq_exc62411).__name__}: {_dq_exc62411}",
            })

    _agents62421 = [
        locals().get("_strategie_agent_output"),
        locals().get("_brief_codir_agent_output"),
        locals().get("_marketing_agent_output"),
        locals().get("_finance_agent_output"),
        locals().get("_commercial_agent_output"),
        locals().get("_supply_chain_agent_output"),
        locals().get("_synthese_agent_output"),
        locals().get("_dg_agent_output"),
    ]
    try:
        from utils.declared_quantities import (
            audit_run_coverage, review_shortlist, audit_narrative_gap)
        _run_audit62421 = audit_run_coverage(_agents62421)
        _run_shortlist62421 = review_shortlist(_agents62421)
        # v62.13.9.4.12.2 — archive brute (protocole : pièces obligatoires par
        # agent) et mesure §3 (nombres de narrative sans claim).
        _raw_archive62422 = list(_AGENT_RAW_ARCHIVE)
        _narrative_gap62422 = audit_narrative_gap(_raw_archive62422, _agents62421)   # v62.13.9.4.18
        from utils.declared_quantities import a1_qualification_gate as _agq62413
        _a1_gate62413 = _agq62413({
            "run_coverage_audit": _run_audit62421,
            "declared_quantities": (_declared_index62411.to_transport()
                                    if _declared_index62411 is not None else {}),
            "run_narrative_gap": _narrative_gap62422,        # v62.13.9.4.16 — dans la décision
        })
        from utils.declared_quantities import review_shortlist_from_gate as _rsg62416
        _run_shortlist62421 = list(_run_shortlist62421) + _rsg62416(_a1_gate62413, _run_audit62421)
        # v62.13.9.4.16 — STATUTS COHÉRENTS (contre-audit point 4). Un run
        # dont A1 n'est pas qualifié ne peut pas afficher « stabilité
        # 100/100 » : la composante ``run_stability`` est plafonnée à 60,
        # la pénalité est tracée, et l'indicateur longitudinal (série des
        # dossiers de la même entité) est joint au résultat.
        try:
            if isinstance(_confidence_score, dict) and not _a1_gate62413.get("a1_qualifiable", False):
                _comp62416 = _confidence_score.get("components") or {}
                _prev62416 = _comp62416.get("run_stability")
                if isinstance(_prev62416, (int, float)) and _prev62416 > 60:
                    _comp62416["run_stability"] = 60
                    _confidence_score["components"] = _comp62416
                    _confidence_score.setdefault("penalties", []).append({
                        "code": "A1_NOT_QUALIFIED", "impact": -(int(_prev62416) - 60),
                        "component": "run_stability",
                        "reason": "canal A1 non qualifié : " + " ; ".join(_a1_gate62413.get("raisons") or [])[:300],
                    })
                    _confidence_score["a1_qualifiable"] = False
        except Exception:
            pass
        try:
            from utils.declared_quantities import a1_longitudinal as _a1l62416
            _a1_long62416 = _a1l62416({
                "run_coverage_audit": _run_audit62421, "a1_qualification_gate": _a1_gate62413,
                "company_profile": (_company_profile.to_dict() if _company_profile else {}),
                "run_id": locals().get("_run_id62422") or "", "build_version": BUILD_VERSION,
            })
        except Exception as _le62416:
            _a1_long62416 = {"error": f"{type(_le62416).__name__}: {_le62416}"}
    except Exception as _rc_exc62421:
        _run_audit62421 = {"error": f"{type(_rc_exc62421).__name__}: {_rc_exc62421}"}
        _run_shortlist62421 = []
        _raw_archive62422 = []
        _narrative_gap62422 = {"error": "non calculé"}
        _a1_long62416 = {"error": "non calculé"}
        _a1_gate62413 = {"a1_qualifiable": False,
                         "raisons": ["audit de couverture indisponible"]}

    # v62.13.9.4.41 — FILIATION DES CLAIMS. Un chiffre attribué aux pièces mais non
    # confirmé POUR SA GRANDEUR ne peut fonder ni risque, ni question, ni arbitrage, ni
    # action : ses descendants tombent avec lui, en laissant leur motif. Le registre du
    # retrait part dans le diagnostic, pour que rien ne disparaisse en silence.
    _lineage41 = {}
    try:
        from utils.claim_lineage41 import (build_page_metric_index as _bpmi41,
                                           unsupported_document_claims as _udc41,
                                           invalidate_descendants as _inv41)
        _pg41 = locals().get("_pages37") or []
        # v62.13.9.4.43 — la preuve d'une assertion est un FAIT QUALIFIÉ de la table
        # validée (valeur, grandeur, période, nature), pas un nombre lu dans une page.
        # L'index de page ne sert plus que de repli quand la table est absente, et la
        # trace dit lequel des deux a servi : un contrôle par repli n'est pas un contrôle.
        _fi42, _basis42 = {}, "none"
        try:
            from utils.claim_lineage41 import build_fact_index42 as _bfi42, confirm42 as _cf42
            _tbl42 = locals().get("_facts_table_built") or locals().get("_facts_table")
            _facts42 = list(getattr(_tbl42, "facts", []) or []) if _tbl42 is not None else []
            if _facts42:
                _fi42 = _bfi42(_facts42)
                _basis42 = "qualified_facts"
        except Exception:
            _fi42 = {}
        _idx41 = _bpmi41(_pg41) if _pg41 else set()
        if _idx41 and _basis42 == "none":
            _basis42 = "page_index_fallback"
        _lineage41["control"] = {"basis": _basis42, "facts_indexed": len(_fi42), "page_pairs": len(_idx41)}
        if isinstance(outputs, dict) and (_fi42 or _idx41):
            if True:
                def _confirm41(v, k, period=""):
                    if _fi42:
                        return _cf42(_fi42, v, k, period)
                    return (v, k) in _idx41
                for _role41 in list(outputs.keys()):
                    _txt41 = outputs.get(_role41)
                    if not isinstance(_txt41, str) or not _txt41.strip():
                        continue
                    _bad41 = _udc41(_txt41, _confirm41)
                    if not _bad41:
                        continue
                    _pairs41 = [(v, k) for _l41, v, _ks41 in _bad41 for k in _ks41]
                    _new41, _rm41 = _inv41(_txt41, _pairs41, lang=lang)
                    if _rm41:
                        outputs[_role41] = _new41
                        _lineage41[_role41] = {
                            "unsupported_claims": [l for l, _v41, _k41 in _bad41][:20],
                            "removed_descendants": _rm41[:40],
                        }
    except Exception as _lex41:
        _lineage41 = {"control": {"basis": "failed", "error": f"{type(_lex41).__name__}: {str(_lex41)[:120]}"}}

    return {
        "outputs":               outputs,
        "claim_lineage":         _lineage41,
        # transport COMPLET (dimensions préservées, aucune troncature) — le
        # diagnostic lisible reste dans diagnostics_attempts.
        "declared_quantities":   (_declared_index62411.to_transport()
                                  if _declared_index62411 is not None else None),
        "declared_quantities_coverage": {
            "claims_with_numbers": _cov_total62412,
            "claims_without_declaration": _cov_missing62412,
            "status": "OK" if _cov_missing62412 == 0 else "INCOMPLETE",
            # v62.13.9.4.12.1 — AVERTISSEMENT porté par la donnée elle-même :
            # ce compteur agrège des CLAIMS. Une claim de trois nombres est
            # comptée couverte avec une seule déclaration. Il ne suffit pas à
            # déclarer un run vert (protocole de run diagnostic).
            "note": ("compteur par claim — ne mesure ni les occurrences "
                     "numériques ni la justesse de la nature ; "
                     "voir run_coverage_audit"),
        },
        # v62.13.9.4.12.1 — mesures du protocole de run diagnostic, produites
        # automatiquement pour qu'elles n'aient pas à être recomptées à la
        # main : couverture par OCCURRENCE, ventilation PAR AGENT, agents
        # muets, et pré-tri des grandeurs à relire (erreurs critiques
        # d'abord).
        # v62.13.9.4.13 — la qualification A1 est une porte distincte de
        # l'exécution du run : un run peut s'exécuter et n'être pas
        # qualifiable. ``run_validatable`` ne dit rien d'A1.
        "a1_qualification_gate": _a1_gate62413,
        "run_coverage_audit":    _run_audit62421,
        "run_review_shortlist":  _run_shortlist62421,
        "run_agent_raw_archive": _raw_archive62422,
        "run_narrative_gap":     _narrative_gap62422,
        "a1_longitudinal":       _a1_long62416,          # v62.13.9.4.16 — stabilité inter-runs
        "provider_health":       provider_health_snapshot(),   # v62.13.9.4.23 — fournisseurs tombés (solde, auth)
        "run_date":              _actual_run_date_out,
        "analysis_date":         _temporal_authority_obj["analysis_date"],
        "temporal_authority_date": _temporal_authority_obj["analysis_date"],
        "temporal_authority":    _temporal_authority_obj,
        "temporal_authority_error": _temporal_authority_obj["error_code"],
        "completion_gate":       _completion_issues,  # B.1.3 — sections tronquées
        "run_block_reasons":     _run_block_reasons_out,
        "run_validatable":       (not bool(_completion_issues)
                                   and _scn_status_out not in ("INVALID", "ERROR")
                                   and not bool(locals().get("_accounting_guard_failed", False))
                                   and not bool(locals().get("_mission_hard_block", False))
                                   and not bool((_b23_guards or {}).get("run_not_validatable"))),
                                        # B.1.3.56 — un verdict mission dur
                                        # (NON MISSION-GRADE) rend le run non
                                        # validable de bout en bout.
                                        # (audit #1) — statut EXPLICITE : un
                                        # livrable flaggé ne peut pas être
                                        # marqué « run terrain vert ».
        "lang":                  lang,  # B.1.3.5 — langue du RUN : les writers et
                                        # blocs système du CR la suivent (plus jamais
                                        # la langue UI rechargée du disque).
        "language_conflict":     _language_conflict,  # B.1.3 — écran vs brief
        "inputs":                inputs,
        "meta":                  meta,
        "diagnostics_summary":   diagnostics_summary,
        "diagnostics_attempts":  diag_list,
        "entity_scope":          (_entity_scope_obj.to_dict()
                                  if ("_entity_scope_obj" in dir() and _entity_scope_obj)
                                  else None),
        "temporal_frame":        (_temporal_frame_obj.to_dict()
                                  if ("_temporal_frame_obj" in dir() and _temporal_frame_obj)
                                  else None),
        "financial_facts":       ([_f.to_dict() for _f in _fin_facts_obj]
                                  if ("_fin_facts_obj" in dir() and _fin_facts_obj)
                                  else []),
        "financial_facts_coverage": (_fin_facts_cov
                                  if ("_fin_facts_cov" in dir() and _fin_facts_cov)
                                  else {}),
        # v16.5.62 — expose le profil société au niveau racine pour affichage
        # du bandeau routing en tête du CR DOCX (alerte UI ↔ Pappers).
        "company_profile":       (_company_profile.to_dict() if _company_profile else None),
        # v62.11.3.2 — writers need the actual deep-scan result at root.  Before
        # this wiring, the Word could say "Consolidated accounts provided: no"
        # immediately before listing six detected financial statements.
        "n_pdfs_with_fs": int((_run_ctx or {}).get("n_pdfs_with_fs", 0) or 0),
        "financial_statements_detected": bool(
            (_run_ctx or {}).get("financial_statements_detected")),
        "pappers_resolution_log": _pap_rlog.to_dict() if _pap_rlog else None,
        # B.1.3.13 (constat ChatGPT, cycle hybride #7) — le fingerprint n'était
        # exposé QUE dans le sous-dict b1_proof_layer ; les writers (Pappers
        # requalifié, Registry target, override Zone B) le lisent à la RACINE :
        # les wordings 3.10/3.12 étaient morts-nés. 6e bug « mauvais niveau ».
        "run_fingerprint": (
            _b1_result.get("run_fingerprint")
            if (isinstance(_b1_result, dict)
                and isinstance(_b1_result.get("run_fingerprint"), dict))
            else (_b1_result.get("fingerprint").to_dict()
                  if (_b1_result and _b1_result.get("fingerprint")
                      and hasattr(_b1_result.get("fingerprint"), "to_dict"))
                  else (_b1_result.get("fingerprint")
                        if (_b1_result
                            and isinstance(_b1_result.get("fingerprint"), dict))
                        else None))
        ),
        # M6-B B.1 (v17.4.0) — couche de preuve exposée (UI, débrief, B.4c)
        "b1_proof_layer": ({
            "analysis_context": (_b1_ctx.to_dict() if _b1_ctx is not None else None),
            "conflicts": [
                {"metric": _c.metric_canonical_id,
                 "severity": _c.conflict_severity,
                 "reason": _c.conflict_reason,
                 "resolution": _c.resolution,
                 "message": _c.user_visible_message,
                 "conflict_group_id": _c.conflict_group_id,
                 "competing_values": _c.competing_values}
                for _c in (_b1_conflicts or [])
            ],
            "fingerprint": (_b1_result.get("fingerprint").to_dict()
                            if (_b1_result and _b1_result.get("fingerprint")) else None),
            "coverage": (_b1_result.get("coverage") if _b1_result else {}),
            "signal_effective": _fin_signal_solid_effective,
            "signal_gate_reason": (_b1_result.get("signal_gate_reason", "")
                                   if _b1_result else ""),
        } if _b1_ctx is not None else None),
        # v16.5.63 — briefcheck + delivery_confidence_score
        "briefcheck":            _briefcheck_result,
        "delivery_confidence_score": _confidence_score,
        # Patch v16.5.72 (audit ChatGPT round 15) — Source Traceability
        # Couche 1 déterministe : table de faits financiers construite
        # uniquement depuis les sources externes vérifiables (Pappers, CH,
        # GLEIF, FS bundles, signal detector). Pas de dépendance LLM —
        # ces faits sont solides par construction.
        # Le rendu DOCX/PPTX utilisera financial_facts_table.to_markdown_table().
        "financial_facts_table": _financial_facts_table_dict,
        "financial_proof_layer": (_financial_proof_layer_report
                                  if "_financial_proof_layer_report" in dir() else None),
        "canonical_financial_claims": (
            ((_financial_proof_layer_report or {}).get("canonical_claims") or [])
            if "_financial_proof_layer_report" in dir() else []),
        "numeric_support_claims": (
            _numeric_support_claims62131 if "_numeric_support_claims62131" in dir() else []),
        "current_period_authority": (
            _current_period_authority_report6212
            if "_current_period_authority_report6212" in dir() else None),
        "scenario_appendix": (
            _scenario_appendix6212 if "_scenario_appendix6212" in dir() else []),
        "liasse_cerfa_ingestion": (
            _liasse_ledger_report6212 if "_liasse_ledger_report6212" in dir() else None),
        # v17.1-B2.3-A — gardes pipeline : décision réconciliée + flags
        # (cotation non sourcée, confusion métrique, roadmap rétroactive).
        "b23_guards": _b23_guards,
        "decision_reconciled": (_b23_guards.get("decision") if _b23_guards else None),
        "accounting_narrative_guard": (_accounting_narrative_guard
                                       if "_accounting_narrative_guard" in dir() else None),
        "agent_leakage_gate": (_agent_leakage_report
                               if "_agent_leakage_report" in dir() else None),
        "finance_factual_safety": (_finance_factual_safety_report
                                   if "_finance_factual_safety_report" in dir() else None),
        "market_evidence_safety": (_market_evidence_safety_report
                                  if "_market_evidence_safety_report" in dir() else None),
        "board_scrutiny_guard": (_board_scrutiny_guard_report
                                  if "_board_scrutiny_guard_report" in dir() else None),
        "strategic_horizon": (_horizon_reconciliation.to_dict()
                               if "_horizon_reconciliation" in dir() and _horizon_reconciliation is not None else None),
        "strategic_horizon_output": (_strategic_horizon_output_report
                                      if "_strategic_horizon_output_report" in dir() else None),
        "agenda_genre": getattr(_genre, "genre", None),
        "decision_mode": getattr(_genre, "decision_mode", None),
        "finance_tone": getattr(_genre, "finance_tone", None),
        "action_semantic_quarantine_count": (
            _semantic_quarantined_count61
            if "_semantic_quarantined_count61" in dir() else 0),
        # v17.1.0-B2.3-F.2 — registre d'actions d'agenda (minimal) : sujet /
        # décision / action / porteur / échéance / statut / prochaine revue.
        "agenda_register":          _agenda_register,
        "agenda_register_markdown": _agenda_register_md,
        # Cycle C — registre MULTI-SÉANCES : historique du dossier (actions
        # ouvertes/reportées/en retard/clôturées, relances, frise CoDIR→CoDIR,
        # écarts de décision). None si pas d'actions ou hors-scope. Append-only.
        "codir_history":            _codir_history,
        # Cycle D — brique 1 : FIDÉLITÉ d'extraction ligne-à-ligne. Récap
        # {verbatim/normalized/not_found/no_numeric} : chaque valeur de fait est
        # cherchée dans le corpus source. Signal-only (n'altère rien). None si
        # indisponible (fail-open).
        "extraction_fidelity":      _extraction_fidelity,
        # Cycle D — brique 2 : VALORISATION multi-méthodes (DCF/multiples/ANR,
        # football field). Déclenchée sur intention du brief. DÉRIVÉE → jamais
        # board-safe (gouvernance F.4.3) : board_safe=False, fourchette + caveats.
        # None si non déclenchée. Fail-open.
        "valuation":                _valuation_report,
        # v17.1.0-B2.3-F.2 — WebFactsLedger marché structuré (métrique/valeur/
        # année/source/fiabilité/board-safe). None hors genre marché ou hors-réseau.
        "web_facts_ledger":         _web_facts_ledger,
        # B.1.3.26 — décision Supply Chain moteur exposée au niveau racine
        # (en 3.25 l'écriture précédait la création de result : flag jamais
        # sorti, deck aveugle malgré des tests renderer verts).
        "sc_decision": (_sc_decision if "_sc_decision" in dir() else None),
        "financial_documents_status_message": _financial_documents_status_message,
        # Patch v16.5.72.9 (round 24 ChatGPT) — Observabilité Couche 1.
        # Permet de remonter dans le DOCX/diagnostics_ia.csv le statut de
        # construction de la table (ok/failed/skipped), l'erreur métier
        # éventuelle et la durée. Avant v16.5.72.9, une exception ici était
        # silencieusement masquée — Robin pouvait avoir une session qui
        # "réussit" mais avec une table de faits vide sans savoir pourquoi.
        "financial_facts_table_status":   _facts_table_status,
        "financial_facts_table_error":    _facts_table_error,
        "financial_facts_table_n_facts":  _facts_table_n_facts,
        "financial_facts_table_duration_ms": _facts_table_duration_ms,
        # F.6.8 / F.6.7-05 — couverture probante (DEGRADED si 0 métrique FAIT).
        "financial_facts_table_degraded":     _facts_table_degraded,
        "financial_facts_table_fait_metrics": _facts_table_fait_metrics,
        "financial_facts_table_estim_filings": _facts_table_estim_filings,
        # F.6.8 (audit) — mode source EXPLICITE dans le livrable (OPEN vs
        # ATTACHMENTS_ONLY) : lève l'ambiguïté de la ligne « Pappers+GLEIF ».
        "source_mode": (_source_mode if "_source_mode" in dir() else "OPEN"),
        # Patch v16.5.72.9 (retex Robin) — Diagnostic perf : durées des
        # opérations lourdes pour identifier les goulets d'étranglement
        # (sous Streamlit qui ré-exécute tout le script à chaque interaction).
        "perf_timings_ms": {
            "pappers": _pappers_duration_ms,
            "financial_facts_table": _facts_table_duration_ms,
        },
        # Patch v16.5.72.9 — stats cache parsing PJ (hits/misses/evictions/size)
        # Permet de voir si le cache aide bien à réduire les re-parsings.
        "parse_cache_stats": (
            _get_parse_cache_stats() if _get_parse_cache_stats else None
        ),
        # Patch v16.5.72.10 (retex Robin) — Routage intelligent sources externes.
        # Permet de visualiser dans le DOCX/diag quelle source primaire a été
        # déclenchée (pour économiser les API calls inutiles).
        "id_routing_decision": (
            _routing_decision.to_dict() if _routing_decision else None
        ),
        "id_routing_summary": (
            route_summary_for_diagnostic(_routing_decision)
            if _routing_decision and route_summary_for_diagnostic
            else None
        ),
        # v17.1 — Rapport des gardes mission (statut, flags, couverture brief).
        "mission_gates": _mission_gates_report if "_mission_gates_report" in dir() else None,
        # v17.1-A2 — Rapport de valorisation multi-méthodes (None si non demandée).
        "valuation": _valuation_report if "_valuation_report" in dir() else None,
        "raw": {
            "strategie":           strategie_res,
            "brief_codir":         brief_codir_res,
            "marketing":           marketing_res,
            "finance":             finance_res_final,
            "supply_chain":        supply_chain_bundle,
            "commercial":          commercial_res,
            "synthese_decisions":  synthese_res,
            "ceo":                 ceo_res,
        },
    }
