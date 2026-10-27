"""
CoDIR-IA — confidence_scorer v1.0

Module autonome de calcul du `delivery_confidence_score` pour les livrables
CoDIR-IA. Intègre les spécifications v4 (6 sous-scores pondérés, anti-manipulation
FAIT_VERIFIED vs FAIT_ASSERTED, cross-check inter-sous-scores, trace auditable)
et v5 addendum (decision_weight pondéré, cap contextuel 15%, source_quality_level
gradué).

USAGE MINIMAL
-------------
    from patches.confidence_scorer import compute_delivery_confidence_score

    result = compute_delivery_confidence_score(
        run_ctx={
            "all_metrics": [...],          # liste de dicts métriques taguées
            "attachments": [Path(...)],    # pièces attachées
            "financial_docs_attached": False,
            "internal_docs_count": 0,
            "red_alerts_unresolved": 1,
            "orange_alerts_unresolved": 2,
            "unresolved_conflicts": 0,
            "retry_count_total": 1,
            "agent_refusals_count": 1,
            "rejected_outputs_count": 0,
            "sector_unknown": False,
            "benchmark_available": True,
            "completeness_checks": {
                "daf_checklist_complete": True,
                "supply_present_if_triggered": True,
                "cmo_present_if_triggered": True,
                "commercial_present_if_triggered": True,
                "owners_present": True,
                "recommended_option_present": False,
                "primary_growth_driver_present": False,
                "execution_risk_present": False,
            },
        },
        previous_score=None,
    )

Le module est PURE : aucun effet de bord, aucun appel réseau, aucun I/O.
Testable unitairement sans mock.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


# =============================================================================
# CONSTANTES DE SCORING (v4 + v5)
# =============================================================================

# Pondérations des 6 sous-scores (doivent sommer à 1.0)
WEIGHTS: dict[str, float] = {
    "source_quality":    0.25,
    "content_mix":       0.20,
    "consistency":       0.20,
    "completeness":      0.15,
    "run_stability":     0.10,
    "sector_confidence": 0.10,
}

# Poids de décision par métrique (v5 addendum A)
DECISION_WEIGHTS: dict[str, float] = {
    "critical":   3.0,
    "structural": 1.0,
    "contextual": 0.3,
}

# Plafond de contribution contextuelle au score (v5 addendum A.3)
CONTEXTUAL_CAP: float = 0.15

# v16.5.65 — Plafonds de score par mode de briefing (briefcheck v1.1)
# Si le briefcheck détecte un mode GENERIC/PARTIAL, le score final est
# mécaniquement plafonné à ces seuils. Le détail est tracé dans les pénalités.
BRIEF_MODE_SCORE_CAP: dict[str, int] = {
    "GENERIC": 45,    # Grade D max — brief sans aucun levier renseigné
    "PARTIAL": 70,    # Grade B max — 1-3 leviers sur 4
    "FRAMED":  100,   # pas de plafond additionnel
}

# Multiplicateurs de qualité de source (v5 addendum B)
VERIFICATION_MULTIPLIER: dict[str, float] = {
    "strong":   1.00,
    "standard": 0.80,
    "weak":     0.50,
    "asserted": 0.25,
}

# Types de documents → source_quality_level (v5 addendum B.2)
DOCUMENT_EVIDENCE_WEIGHTS: dict[str, str] = {
    "signed_financial_statement":  "strong",
    "structured_xlsx":             "strong",
    "pappers_native_field":        "strong",
    "native_pdf_parseable":        "standard",
    "pappers_inferred":            "standard",
    "public_database_cited":       "standard",
    "scanned_pdf_ocr_only":        "weak",
    "image_or_partial_extract":    "weak",
    "no_verifiable_source":        "asserted",
}

# Champs Pappers considérés comme VERIFIED natifs
PAPPERS_VERIFIED_FIELDS: set[str] = {
    "ca_eur", "resultat_net", "resultat_exploitation", "capital_social",
    "effectif", "ape_code", "legal_form", "siren", "siret", "date_creation",
    "date_cloture", "capitaux_propres", "total_bilan",
}

# Seuil d'échantillon minimal
MIN_METRICS_SAMPLE: int = 20

# Mapping code pénalité → action corrective (v4 section 4.3.6.7)
NEXT_ACTION_MAP: dict[str, str] = {
    # source_quality
    "MISSING_FINANCIAL_DOCS": "Fournir les comptes et relancer le pipeline.",
    "LOW_SOURCED_FACT_RATIO": "Documenter la source de chaque fait numérique.",
    # content_mix
    "HIGH_ASSERTED_FACT_RATIO": "Passer les FAIT_ASSERTED en FAIT_VERIFIED via pièces sources.",
    "HIGH_HYPOTHESIS_RATIO": "Valider les hypothèses critiques en interne ou retirer.",
    "MEDIUM_HYPOTHESIS_RATIO": "Réduire la part d'hypothèses par validation interne.",
    "HIGH_INCERTAIN_RATIO": "Clarifier les données marquées INCERTAIN avant usage.",
    "LOW_METRIC_SAMPLE": "Enrichir le livrable (échantillon de métriques insuffisant).",
    "CROSS_CHECK_MIX_CAPPED": "Améliorer la qualité des sources pour débloquer le mix.",
    "HIGH_CONTEXTUAL_RATIO": "Concentrer l'analyse sur des métriques critiques / structurelles.",
    # consistency
    "RED_ALERTS_UNRESOLVED": "Lever les alertes rouges avant toute décision P1.",
    "ORANGE_ALERTS_UNRESOLVED": "Arbitrer les alertes orange en CoDIR interne.",
    "UNRESOLVED_AGENT_CONFLICTS": "Trancher les conflits inter-agents restants.",
    # completeness
    "MISSING_OWNERS_PRESENT": "Assigner un owner RACI à chaque décision P1/P2.",
    "MISSING_RECOMMENDED_OPTION_PRESENT": "Formuler une position DAF sur chaque arbitrage.",
    "MISSING_PRIMARY_GROWTH_DRIVER_PRESENT": "Identifier le levier dominant CMO.",
    "MISSING_EXECUTION_RISK_PRESENT": "Qualifier le risque d'exécution commercial.",
    "MISSING_DAF_CHECKLIST_COMPLETE": "Compléter la checklist DAF (bilan, cash, intra-groupe).",
    # run_stability
    "AGENT_REFUSALS": "Relancer les agents en échec après clarification du brief.",
    "OUTPUT_REJECTIONS": "Stabiliser les prompts agents pour éviter les rejets pipeline.",
    # sector_confidence
    "SECTOR_UNKNOWN": "Qualifier le secteur avant exécution marketing/commerciale.",
    "NO_SECTOR_BENCHMARK": "Définir un benchmark sectoriel de référence.",
    # v16.5.65 — brief mode cap
    "GENERIC_BRIEF_MODE_CAP": "Enrichir le brief (contexte société, chiffres, décision, enjeu) — voir template.",
    "PARTIAL_BRIEF_MODE_CAP": "Compléter les leviers manquants du brief pour passer en mode cadré.",
    # v16.5.66 — JSON agent manquant ou malformé (pilote Finance)
    "MISSING_AGENT_JSON_CLAIMS": "Relancer l'agent en clarifiant l'obligation de produire le bloc JSON en fin de réponse.",
}

# Wording DG déterministe (v5 amélioration du calculation_trace)
EXPLANATION_MAP_DG: dict[str, str] = {
    "MISSING_FINANCIAL_DOCS": "Aucune pièce comptable fournie ({impact:+d} points)",
    "LOW_SOURCED_FACT_RATIO": "Part insuffisante de faits sourcés ({impact:+d} points)",
    "RED_ALERTS_UNRESOLVED": "{n} alerte(s) rouge(s) non résolue(s) ({impact:+d} points)",
    "ORANGE_ALERTS_UNRESOLVED": "{n} alerte(s) orange non résolue(s) ({impact:+d} points)",
    "UNRESOLVED_AGENT_CONFLICTS": "{n} conflit(s) inter-agents non arbitrés ({impact:+d} points)",
    "HIGH_ASSERTED_FACT_RATIO": "Part élevée de faits auto-déclarés sans source vérifiable ({impact:+d} points)",
    "HIGH_HYPOTHESIS_RATIO": "Part d'hypothèses élevée ({impact:+d} points)",
    "MEDIUM_HYPOTHESIS_RATIO": "Part d'hypothèses significative ({impact:+d} points)",
    "HIGH_INCERTAIN_RATIO": "Données incertaines nombreuses ({impact:+d} points)",
    "LOW_METRIC_SAMPLE": "Échantillon de métriques limité ({impact:+d} points)",
    "CROSS_CHECK_MIX_CAPPED": "Mix de contenu plafonné par qualité des sources ({impact:+d} points)",
    "HIGH_CONTEXTUAL_RATIO": "Trop de métriques contextuelles vs critiques ({impact:+d} points)",
    "AGENT_REFUSALS": "Refus d'agent(s) pendant le run ({impact:+d} points)",
    "RETRIES_OCCURRED": "Rebouclages pipeline pendant le run ({impact:+d} points)",
    "OUTPUT_REJECTIONS": "Outputs agents rejetés par le pipeline ({impact:+d} points)",
    "SECTOR_UNKNOWN": "Secteur non résolu ({impact:+d} points)",
    "NO_SECTOR_BENCHMARK": "Benchmark sectoriel indisponible ({impact:+d} points)",
    "MISSING_FINANCIAL_DOCS_BASE": "",  # déjà couvert par MISSING_FINANCIAL_DOCS
    # bonuses
    "HIGH_VERIFIED_FAIT_RATIO": "Forte part de faits vérifiés ({impact:+d} points)",
    "NO_UNRESOLVED_ALERTS": "Aucune alerte non résolue ({impact:+d} points)",
    "SECTOR_BENCHMARK_AVAILABLE": "Benchmark sectoriel disponible ({impact:+d} points)",
    "MULTIPLE_INTERNAL_DOCS": "Plusieurs documents internes rapprochés ({impact:+d} points)",
    # v16.5.65 — brief mode cap (wording DG)
    "GENERIC_BRIEF_MODE_CAP": "Brief sans contexte client — score plafonné à Grade D ({impact:+d} points)",
    "PARTIAL_BRIEF_MODE_CAP": "Brief partiellement qualifié — score plafonné à Grade B ({impact:+d} points)",
    # v16.5.66 — JSON typé agent absent (pilote Finance)
    "MISSING_AGENT_JSON_CLAIMS": "{n} agent(s) n'ont pas produit de JSON typé exploitable ({impact:+d} points)",
}

# ── M.5.10 (Language Closure) — versions EN des wordings DG ───────────────────
NEXT_ACTION_MAP_EN: dict[str, str] = {
    "MISSING_FINANCIAL_DOCS": "Provide the accounts and re-run the pipeline.",
    "LOW_SOURCED_FACT_RATIO": "Document the source of every numeric fact.",
    "HIGH_ASSERTED_FACT_RATIO": "Move ASSERTED facts to VERIFIED with source documents.",
    "HIGH_HYPOTHESIS_RATIO": "Validate critical hypotheses internally or remove them.",
    "MEDIUM_HYPOTHESIS_RATIO": "Reduce the share of hypotheses through internal validation.",
    "HIGH_INCERTAIN_RATIO": "Clarify data flagged UNCERTAIN before use.",
    "LOW_METRIC_SAMPLE": "Enrich the deliverable (metric sample too small).",
    "CROSS_CHECK_MIX_CAPPED": "Improve source quality to unlock the content mix.",
    "HIGH_CONTEXTUAL_RATIO": "Focus the analysis on critical / structural metrics.",
    "RED_ALERTS_UNRESOLVED": "Clear red alerts before any P1 decision.",
    "ORANGE_ALERTS_UNRESOLVED": "Arbitrate orange alerts in internal CoDIR.",
    "UNRESOLVED_AGENT_CONFLICTS": "Settle the remaining inter-agent conflicts.",
    "MISSING_OWNERS_PRESENT": "Assign a RACI owner to each P1/P2 decision.",
    "MISSING_RECOMMENDED_OPTION_PRESENT": "State a CFO position on each trade-off.",
    "MISSING_PRIMARY_GROWTH_DRIVER_PRESENT": "Identify the dominant CMO driver.",
    "MISSING_EXECUTION_RISK_PRESENT": "Qualify the commercial execution risk.",
    "MISSING_DAF_CHECKLIST_COMPLETE": "Complete the CFO checklist (balance sheet, cash, intra-group).",
    "AGENT_REFUSALS": "Re-run the failed agents after clarifying the brief.",
    "OUTPUT_REJECTIONS": "Stabilise the agent prompts to avoid pipeline rejections.",
    "SECTOR_UNKNOWN": "Qualify the sector before marketing/commercial execution.",
    "NO_SECTOR_BENCHMARK": "Define a reference sector benchmark.",
    "GENERIC_BRIEF_MODE_CAP": "Enrich the brief (company context, figures, decision, stake) — see template.",
    "PARTIAL_BRIEF_MODE_CAP": "Complete the missing brief levers to reach scoped mode.",
    "MISSING_AGENT_JSON_CLAIMS": "Re-run the agent, clarifying the requirement to produce the JSON block at the end of the answer.",
}

EXPLANATION_MAP_DG_EN: dict[str, str] = {
    "MISSING_FINANCIAL_DOCS": "No accounting document provided ({impact:+d} points)",
    "LOW_SOURCED_FACT_RATIO": "Insufficient share of sourced facts ({impact:+d} points)",
    "RED_ALERTS_UNRESOLVED": "{n} unresolved red alert(s) ({impact:+d} points)",
    "ORANGE_ALERTS_UNRESOLVED": "{n} unresolved orange alert(s) ({impact:+d} points)",
    "UNRESOLVED_AGENT_CONFLICTS": "{n} unsettled inter-agent conflict(s) ({impact:+d} points)",
    "HIGH_ASSERTED_FACT_RATIO": "High share of self-declared facts without verifiable source ({impact:+d} points)",
    "HIGH_HYPOTHESIS_RATIO": "High share of hypotheses ({impact:+d} points)",
    "MEDIUM_HYPOTHESIS_RATIO": "Significant share of hypotheses ({impact:+d} points)",
    "HIGH_INCERTAIN_RATIO": "Many uncertain data points ({impact:+d} points)",
    "LOW_METRIC_SAMPLE": "Limited metric sample ({impact:+d} points)",
    "CROSS_CHECK_MIX_CAPPED": "Content mix capped by source quality ({impact:+d} points)",
    "HIGH_CONTEXTUAL_RATIO": "Too many contextual vs critical metrics ({impact:+d} points)",
    "AGENT_REFUSALS": "Agent refusal(s) during the run ({impact:+d} points)",
    "RETRIES_OCCURRED": "Pipeline retries during the run ({impact:+d} points)",
    "OUTPUT_REJECTIONS": "Agent outputs rejected by the pipeline ({impact:+d} points)",
    "SECTOR_UNKNOWN": "Sector not resolved ({impact:+d} points)",
    "NO_SECTOR_BENCHMARK": "Sector benchmark unavailable ({impact:+d} points)",
    "MISSING_FINANCIAL_DOCS_BASE": "",
    "HIGH_VERIFIED_FAIT_RATIO": "High share of verified facts ({impact:+d} points)",
    "NO_UNRESOLVED_ALERTS": "No unresolved alert ({impact:+d} points)",
    "SECTOR_BENCHMARK_AVAILABLE": "Sector benchmark available ({impact:+d} points)",
    "MULTIPLE_INTERNAL_DOCS": "Several internal documents cross-checked ({impact:+d} points)",
    "GENERIC_BRIEF_MODE_CAP": "Brief without client context — score capped at Grade D ({impact:+d} points)",
    "PARTIAL_BRIEF_MODE_CAP": "Partially qualified brief — score capped at Grade B ({impact:+d} points)",
    "MISSING_AGENT_JSON_CLAIMS": "{n} agent(s) did not produce usable typed JSON ({impact:+d} points)",
}


# =============================================================================
# HELPERS
# =============================================================================

def _clamp(v: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(v, hi))


def _safe_get(d: dict, key: str, default: Any = None) -> Any:
    if d is None:
        return default
    return d.get(key, default)


# =============================================================================
# CLASSIFICATION DES MÉTRIQUES (anti-manipulation v4 + v5)
# =============================================================================

def classify_source_quality_level(source: dict | None,
                                  attachments: list[Path] | None) -> str:
    """
    Détermine le source_quality_level d'une métrique [FAIT].
    Côté pipeline, PAS côté agent — un agent ne peut pas se promouvoir.
    
    Retourne: "strong" | "standard" | "weak" | "asserted"
    """
    if source is None:
        return "asserted"
    
    source_type = source.get("type", "unknown")
    attachments = attachments or []
    
    # Pappers natif : champ standard, vérifiable directement
    if source_type == "pappers":
        field = source.get("field", "")
        if field in PAPPERS_VERIFIED_FIELDS:
            return DOCUMENT_EVIDENCE_WEIGHTS["pappers_native_field"]  # strong
        return DOCUMENT_EVIDENCE_WEIGHTS["pappers_inferred"]  # standard
    
    # Document fourni : il faut que le fichier soit présent + coord précise
    if source_type == "document_fourni":
        doc_ref = source.get("doc_ref", "")
        coord = source.get("coord") or source.get("page") or source.get("line")
        if not doc_ref:
            return "asserted"
        
        # Le doc existe-t-il dans les attachments ?
        doc_base = doc_ref.split("#")[0]  # retirer "#p15.l22" éventuel
        doc_found = any(a.name.endswith(doc_base) for a in attachments)
        if not doc_found:
            return "asserted"
        
        # Qualifier par le type de fichier
        ext = Path(doc_base).suffix.lower()
        name_lower = doc_base.lower()
        
        # Heuristique de nom
        if any(kw in name_lower for kw in ("liasse", "kbis", "rapport_cac", "rapport_cc")):
            return DOCUMENT_EVIDENCE_WEIGHTS["signed_financial_statement"]  # strong
        
        if ext in (".xlsx", ".xlsm", ".csv"):
            return DOCUMENT_EVIDENCE_WEIGHTS["structured_xlsx"]  # strong
        
        if ext == ".pdf":
            # Sans content-check on se fie au nom uniquement (v5 niveau 1)
            # Les patterns pointant vers du scan restent en weak
            if any(kw in name_lower for kw in ("scan", "ocr", "photo")):
                return DOCUMENT_EVIDENCE_WEIGHTS["scanned_pdf_ocr_only"]  # weak
            return DOCUMENT_EVIDENCE_WEIGHTS["native_pdf_parseable"]  # standard
        
        if ext in (".png", ".jpg", ".jpeg", ".tiff"):
            return DOCUMENT_EVIDENCE_WEIGHTS["image_or_partial_extract"]  # weak
        
        if coord:
            return "standard"
        return "weak"
    
    # Base publique (INSEE, Xerfi...) avec URL et date
    if source_type == "base_publique":
        if source.get("url") and source.get("date_consultation"):
            return DOCUMENT_EVIDENCE_WEIGHTS["public_database_cited"]  # standard
        return "weak"
    
    # Inférence explicite : jamais mieux qu'asserted
    if source_type == "infer_explicit":
        return "asserted"
    
    return "asserted"


def reclassify_metrics(metrics: list[dict],
                       attachments: list[Path] | None) -> list[dict]:
    """
    Reclasse chaque métrique :
    - [FAIT] → FAIT_VERIFIED ou FAIT_ASSERTED selon source_quality_level
    - ajoute le champ 'effective_source_quality_level'
    - préserve decision_weight ou force 'structural' si absent (mode compat v4)
    """
    attachments = attachments or []
    out = []
    for m in metrics:
        copy = dict(m)
        original_tag = copy.get("tag", "INCERTAIN")
        source = copy.get("source", {})
        
        if original_tag == "FAIT":
            level = classify_source_quality_level(source, attachments)
            copy["effective_source_quality_level"] = level
            # Convention : FAIT avec level strong/standard/weak → FAIT_VERIFIED
            #              FAIT avec level asserted → FAIT_ASSERTED
            if level == "asserted":
                copy["tag"] = "FAIT_ASSERTED"
            else:
                copy["tag"] = "FAIT_VERIFIED"
        elif original_tag in ("FAIT_VERIFIED", "FAIT_ASSERTED"):
            # L'agent a déjà déclaré un tag v5, on vérifie/recalcule
            level = classify_source_quality_level(source, attachments)
            copy["effective_source_quality_level"] = level
            if level == "asserted":
                copy["tag"] = "FAIT_ASSERTED"
            else:
                copy["tag"] = "FAIT_VERIFIED"
        
        # Mode compat v4 : si pas de decision_weight → défaut 'structural'
        copy.setdefault("decision_weight", "structural")
        if copy["decision_weight"] not in DECISION_WEIGHTS:
            copy["decision_weight"] = "structural"
        
        out.append(copy)
    return out


def apply_contextual_cap(metrics: list[dict]) -> list[dict]:
    """
    Plafonne la contribution des métriques contextual au score à CONTEXTUAL_CAP.
    Les métriques contextual excédentaires restent dans la liste mais sont
    retirées du calcul du score (elles peuvent rester dans le livrable).
    
    Implémentation : on garde toutes les critical/structural, on n'inclut que
    les premières contextual dans la limite du budget (CONTEXTUAL_CAP du total).
    """
    core = [m for m in metrics if m["decision_weight"] in ("critical", "structural")]
    ctx = [m for m in metrics if m["decision_weight"] == "contextual"]
    
    if not core:
        # Si pas de core, on ne pénalise pas davantage
        return metrics
    
    core_weight = sum(DECISION_WEIGHTS[m["decision_weight"]] for m in core)
    # CONTEXTUAL_CAP : les contextuelles ne peuvent représenter plus de
    # CONTEXTUAL_CAP du poids total. Donc budget_ctx = cap * core / (1 - cap)
    budget_ctx = CONTEXTUAL_CAP * core_weight / (1 - CONTEXTUAL_CAP)
    
    running = 0.0
    kept_ctx = []
    unit_ctx = DECISION_WEIGHTS["contextual"]
    for m in ctx:
        if running + unit_ctx > budget_ctx:
            break
        kept_ctx.append(m)
        running += unit_ctx
    
    return core + kept_ctx


# =============================================================================
# CONTENT MIX (pondéré)
# =============================================================================

def compute_content_mix(metrics: list[dict]) -> dict[str, float]:
    """
    Retourne les ratios pondérés par decision_weight ET par source_quality_level.
    
    effective_weight(m) = decision_weight × verification_multiplier(source_quality_level)
    """
    if not metrics:
        return {
            "fait_verified_ratio": 0.0,
            "fait_asserted_ratio": 0.0,
            "calcul_ratio": 0.0,
            "hypothese_ratio": 0.0,
            "incertain_ratio": 0.0,
            "total_metrics_count": 0,
        }
    
    buckets = {"FAIT_VERIFIED": 0.0, "FAIT_ASSERTED": 0.0,
               "CALCUL": 0.0, "HYPOTHÈSE": 0.0, "INCERTAIN": 0.0}
    total_w = 0.0
    
    for m in metrics:
        tag = m.get("tag", "INCERTAIN")
        if tag not in buckets:
            tag = "INCERTAIN"
        dw = DECISION_WEIGHTS[m["decision_weight"]]
        
        # Pour FAIT_VERIFIED, on applique le verification_multiplier
        # pour graduer strong/standard/weak
        if tag == "FAIT_VERIFIED":
            level = m.get("effective_source_quality_level", "standard")
            mult = VERIFICATION_MULTIPLIER.get(level, 0.8)
            weighted = dw * mult
        elif tag == "FAIT_ASSERTED":
            weighted = dw * VERIFICATION_MULTIPLIER["asserted"]
        else:
            weighted = dw  # CALCUL, HYPOTHÈSE, INCERTAIN : pas de graduation
        
        buckets[tag] += weighted
        total_w += dw  # dénominateur = poids décisionnel brut
    
    total_w = total_w or 1.0
    return {
        "fait_verified_ratio": buckets["FAIT_VERIFIED"] / total_w,
        "fait_asserted_ratio": buckets["FAIT_ASSERTED"] / total_w,
        "calcul_ratio":        buckets["CALCUL"] / total_w,
        "hypothese_ratio":     buckets["HYPOTHÈSE"] / total_w,
        "incertain_ratio":     buckets["INCERTAIN"] / total_w,
        "total_metrics_count": len(metrics),
    }


# =============================================================================
# 6 SOUS-SCORES
# =============================================================================

def score_source_quality(
    has_financial_docs: bool,
    sourced_fact_ratio: float,
    internal_docs_count: int,
    *,
    # Since v16.5.70 — Sous-flags étendus pour distinguer les cas réels.
    # Tous optionnels : si non fournis → comportement identique v16.5.69.1.
    financial_statements_detected: bool | None = None,
    financial_tables_extracted: bool | None = None,
    n_pdfs_with_fs: int = 0,
    # Patch v16.5.71.1 P0 — Signal multi-format (audit ChatGPT round 9)
    # Bug v16.5.71 : le nouveau détecteur multi-format pilotait correctement
    # le prompt Finance (bridé/non bridé) mais le scorer continuait à ne
    # connaître que les bundles PDF FS. Conséquence sur dossier réseau de soins : Finance
    # produisait son business plan chiffré (bon) mais le score disait
    # "Pièces financières insuffisantes" (incohérent → livrable pollué).
    # Fix : nouveau bonus FINANCIAL_SIGNAL_SOLID_NON_PDF si signal détecté
    # dans attachments_block sans bundle PDF FS.
    financial_signal_in_attachments_solid: bool = False,
    financial_signal_score: int | None = None,
) -> tuple[int, list, list]:
    """
    Sous-score 1. Base 50 (défiance initiale).

    Patch v16.5.71.1 — Refonte avec 5 sous-flags pour granularité documentaire :
      1. has_financial_docs                       : PJ catégorisées comme financières (legacy)
      2. financial_statements_detected            : sections FS détectées dans PDF (v16.5.70)
      3. financial_tables_extracted               : tableaux comptables extraits texte
      4. financial_signal_in_attachments_solid    : signaux financiers solides détectés
                                                    dans attachments_block (Excel/Word/CSV) — Since v16.5.71.1
      5. (futur) financial_values_reconciled      : cohérence inter-sections

    Hiérarchie des bonus (du plus au moins fort) :
      - financial_statements_detected (PDF FS structuré) → +25
      - financial_signal_in_attachments_solid (Excel/Word/CSV solide) → +20
      - has_financial_docs legacy (sans détection structurée) → +15
      - Aucun → pénalité -25 MISSING_FINANCIAL_DOCS
    """
    score = 50.0
    pen: list[dict] = []
    bon: list[dict] = []

    # Patch v16.5.70 + v16.5.71.1 — Logique en cascade selon signaux disponibles
    if financial_statements_detected is True:
        # Cas optimal v16.5.70 : sections FS structurées détectées dans PDF
        score += 25
        bon.append({
            "code": "FINANCIAL_STATEMENTS_DETECTED",
            "impact": 25,
            "component": "source_quality",
            "reason": (f"États financiers structurés détectés dans "
                       f"{n_pdfs_with_fs} PDF(s) — Income / Balance / Cash Flow / Notes."),
        })
    elif financial_signal_in_attachments_solid:
        # Patch v16.5.71.1 — Signal financier solide multi-format
        # (Excel/Word/CSV avec ≥5 keywords + ≥10 montants + sigles)
        # Bonus +20 (légèrement < +25 PDF FS structuré pour distinguer)
        score += 20
        score_label = (f" (score {financial_signal_score}/100)"
                       if financial_signal_score is not None else "")
        bon.append({
            "code": "FINANCIAL_SIGNAL_SOLID_NON_PDF",
            "impact": 20,
            "component": "source_quality",
            "reason": (f"Signaux financiers exploitables détectés dans pièces "
                       f"jointes multi-format (Excel/Word/CSV){score_label}."),
        })
    elif has_financial_docs:
        # Cas legacy : has_financial_docs=True mais pas de détection structurée
        score += 15
        bon.append({
            "code": "FINANCIAL_DOCS_ATTACHED",
            "impact": 15,
            "component": "source_quality",
            "reason": ("Pièces financières fournies (mais sections états financiers "
                       "structurés non détectées — analyse à valider).")
            if financial_statements_detected is False
            else "Pièces financières fournies.",
        })
    else:
        # Cas legacy : pas de PJ financière du tout
        score -= 25
        pen.append({
            "code": "MISSING_FINANCIAL_DOCS",
            "impact": -25,
            "component": "source_quality",
            "reason": "Aucune pièce financière attachée.",
        })

    if sourced_fact_ratio >= 0.80:
        score += 15
        bon.append({"code": "HIGH_VERIFIED_FAIT_RATIO", "impact": 15,
                    "component": "source_quality",
                    "reason": f"Part élevée de faits vérifiés ({sourced_fact_ratio:.0%})."})
    elif sourced_fact_ratio < 0.50:
        score -= 15
        pen.append({"code": "LOW_SOURCED_FACT_RATIO", "impact": -15,
                    "component": "source_quality",
                    "reason": f"Part insuffisante de faits vérifiés ({sourced_fact_ratio:.0%})."})
    
    if internal_docs_count >= 3:
        score += 10
        bon.append({"code": "MULTIPLE_INTERNAL_DOCS", "impact": 10,
                    "component": "source_quality",
                    "reason": "Plusieurs documents internes rapprochés."})
    
    return int(_clamp(score)), pen, bon


def score_content_mix(mix: dict) -> tuple[int, list, list]:
    """Sous-score 2. Base 100. Inclut anti-manipulation + sample minimum."""
    score = 100.0
    pen: list[dict] = []
    bon: list[dict] = []
    
    # Part de FAIT vérifiés insuffisante
    if mix["fait_verified_ratio"] < 0.30:
        score -= 15
        pen.append({"code": "LOW_FAIT_VERIFIED_RATIO", "impact": -15,
                    "component": "content_mix",
                    "reason": f"Seulement {mix['fait_verified_ratio']:.0%} de faits vérifiés (pondéré)."})
    elif mix["fait_verified_ratio"] >= 0.60:
        score += 10
        bon.append({"code": "HIGH_VERIFIED_FAIT_RATIO", "impact": 10,
                    "component": "content_mix",
                    "reason": f"{mix['fait_verified_ratio']:.0%} de faits vérifiés."})
    
    # Anti-manipulation : trop de FAIT_ASSERTED
    if mix["fait_asserted_ratio"] > 0.30:
        score -= 10
        pen.append({"code": "HIGH_ASSERTED_FACT_RATIO", "impact": -10,
                    "component": "content_mix",
                    "reason": f"{mix['fait_asserted_ratio']:.0%} de faits auto-déclarés sans source vérifiable."})
    
    # Hypothèses
    if mix["hypothese_ratio"] > 0.40:
        score -= 15
        pen.append({"code": "HIGH_HYPOTHESIS_RATIO", "impact": -15,
                    "component": "content_mix",
                    "reason": f"{mix['hypothese_ratio']:.0%} d'hypothèses (pondéré)."})
    elif mix["hypothese_ratio"] > 0.20:
        score -= 8
        pen.append({"code": "MEDIUM_HYPOTHESIS_RATIO", "impact": -8,
                    "component": "content_mix",
                    "reason": f"{mix['hypothese_ratio']:.0%} d'hypothèses."})
    
    # Incertain
    if mix["incertain_ratio"] > 0.10:
        score -= 20
        pen.append({"code": "HIGH_INCERTAIN_RATIO", "impact": -20,
                    "component": "content_mix",
                    "reason": f"{mix['incertain_ratio']:.0%} d'incertain."})
    
    # Seuil minimal d'échantillon (v4)
    if mix["total_metrics_count"] < MIN_METRICS_SAMPLE:
        score -= 10
        pen.append({"code": "LOW_METRIC_SAMPLE", "impact": -10,
                    "component": "content_mix",
                    "reason": f"Échantillon réduit ({mix['total_metrics_count']} métriques, seuil {MIN_METRICS_SAMPLE})."})
    
    return int(_clamp(score)), pen, bon


def score_consistency(red_alerts: int,
                      orange_alerts: int,
                      unresolved_conflicts: int) -> tuple[int, list, list]:
    """Sous-score 3. Base 100."""
    score = 100.0
    pen: list[dict] = []
    bon: list[dict] = []
    
    if red_alerts > 0:
        impact = min(20 * red_alerts, 40)
        score -= impact
        pen.append({"code": "RED_ALERTS_UNRESOLVED", "impact": -impact,
                    "component": "consistency", "n": red_alerts,
                    "reason": f"{red_alerts} alerte(s) rouge(s) non résolue(s)."})
    
    if orange_alerts > 0:
        impact = min(5 * orange_alerts, 20)
        score -= impact
        pen.append({"code": "ORANGE_ALERTS_UNRESOLVED", "impact": -impact,
                    "component": "consistency", "n": orange_alerts,
                    "reason": f"{orange_alerts} alerte(s) orange non résolue(s)."})
    
    if unresolved_conflicts > 0:
        impact = min(7 * unresolved_conflicts, 21)
        score -= impact
        pen.append({"code": "UNRESOLVED_AGENT_CONFLICTS", "impact": -impact,
                    "component": "consistency", "n": unresolved_conflicts,
                    "reason": f"{unresolved_conflicts} conflit(s) inter-agents non arbitrés."})
    
    if red_alerts == 0 and orange_alerts == 0 and unresolved_conflicts == 0:
        score += 10
        bon.append({"code": "NO_UNRESOLVED_ALERTS", "impact": 10,
                    "component": "consistency",
                    "reason": "Aucune alerte ni conflit non résolu."})
    
    return int(_clamp(score)), pen, bon


def score_completeness(checks: dict) -> tuple[int, list, list]:
    """Sous-score 4. Base 100, -8 par élément manquant."""
    score = 100.0
    pen: list[dict] = []
    
    if not checks:
        return 100, [], []
    
    for key, ok in checks.items():
        if not ok:
            score -= 8
            pen.append({"code": f"MISSING_{key.upper()}", "impact": -8,
                        "component": "completeness",
                        "reason": f"Élément obligatoire absent: {key}"})
    
    return int(_clamp(score)), pen, []


def score_run_stability(retry_count_total: int,
                        refusals_count: int,
                        rejected_outputs_count: int,
                        missing_agent_json_count: int = 0) -> tuple[int, list, list]:
    """
    Sous-score 5. Base 100.
    v16.5.66 — Intègre missing_agent_json_count : nombre d'agents qui ont été
    sollicités avec l'instruction schema mais n'ont pas produit de bloc JSON
    parsable (MISSING ou MALFORMED).
    """
    score = 100.0
    pen: list[dict] = []
    
    if retry_count_total > 0:
        impact = min(retry_count_total * 3, 15)
        score -= impact
        pen.append({"code": "RETRIES_OCCURRED", "impact": -impact,
                    "component": "run_stability", "n": retry_count_total,
                    "reason": f"{retry_count_total} rebouclage(s) pipeline."})
    
    if refusals_count > 0:
        impact = min(refusals_count * 12, 36)
        score -= impact
        pen.append({"code": "AGENT_REFUSALS", "impact": -impact,
                    "component": "run_stability", "n": refusals_count,
                    "reason": f"{refusals_count} refus d'agent(s) détecté(s)."})
    
    if rejected_outputs_count > 0:
        impact = min(rejected_outputs_count * 8, 24)
        score -= impact
        pen.append({"code": "OUTPUT_REJECTIONS", "impact": -impact,
                    "component": "run_stability", "n": rejected_outputs_count,
                    "reason": f"{rejected_outputs_count} output(s) agent(s) rejeté(s)."})

    # v16.5.66 — Agents sans JSON exploitable (MISSING / MALFORMED)
    if missing_agent_json_count > 0:
        impact = min(missing_agent_json_count * 5, 15)
        score -= impact
        pen.append({"code": "MISSING_AGENT_JSON_CLAIMS", "impact": -impact,
                    "component": "run_stability", "n": missing_agent_json_count,
                    "reason": f"{missing_agent_json_count} agent(s) sans bloc JSON parsable."})
    
    return int(_clamp(score)), pen, []


def score_sector_confidence(sector_unknown: bool,
                            benchmark_available: bool) -> tuple[int, list, list]:
    """Sous-score 6. Base 100."""
    score = 100.0
    pen: list[dict] = []
    bon: list[dict] = []
    
    if sector_unknown:
        score -= 25
        pen.append({"code": "SECTOR_UNKNOWN", "impact": -25,
                    "component": "sector_confidence",
                    "reason": "Secteur non résolu par le filtre sectoriel."})
    
    if not benchmark_available:
        score -= 10
        pen.append({"code": "NO_SECTOR_BENCHMARK", "impact": -10,
                    "component": "sector_confidence",
                    "reason": "Aucun benchmark sectoriel fiable disponible."})
    else:
        score += 5
        bon.append({"code": "SECTOR_BENCHMARK_AVAILABLE", "impact": 5,
                    "component": "sector_confidence",
                    "reason": "Benchmark sectoriel disponible."})
    
    return int(_clamp(score)), pen, bon


# =============================================================================
# GRADES + USAGE (v4 section 4.3.6.6, grades A-E uniques)
# =============================================================================

_GRADE_TABLE = [
    (85, "A", "Preuve forte — usage professionnel supervisé",
     {"internal_codir": "OK", "client_presentation": "OK",
      "board": "OK_WITH_FINAL_REVIEW", "public_external_use": "LIMITED"}),
    (70, "B", "Preuve étayée — document de travail supervisé",
     {"internal_codir": "OK", "client_presentation": "OK_WITH_REVIEW",
      "board": "LIMITED", "public_external_use": "NO"}),
    (60, "C", "Document de travail interne — faits clés à étayer",
     {"internal_codir": "OK", "client_presentation": "LIMITED",
      "board": "NO", "public_external_use": "NO"}),
    (45, "D", "Cadrage interne uniquement",
     {"internal_codir": "LIMITED", "client_presentation": "NO",
      "board": "NO", "public_external_use": "NO"}),
    (0,  "E", "Livrable non fiabilisé",
     {"internal_codir": "NO", "client_presentation": "NO",
      "board": "NO", "public_external_use": "NO"}),
]

# M.5.10 — table de grades EN (mêmes seuils/usages neutres, labels traduits)
_GRADE_TABLE_EN = [
    (85, "A", "Strong evidence — supervised professional use",
     {"internal_codir": "OK", "client_presentation": "OK",
      "board": "OK_WITH_FINAL_REVIEW", "public_external_use": "LIMITED"}),
    (70, "B", "Substantiated evidence — supervised work product",
     {"internal_codir": "OK", "client_presentation": "OK_WITH_REVIEW",
      "board": "LIMITED", "public_external_use": "NO"}),
    (60, "C", "Internal work product — substantiate key facts",
     {"internal_codir": "OK", "client_presentation": "LIMITED",
      "board": "NO", "public_external_use": "NO"}),
    (45, "D", "Internal scoping only",
     {"internal_codir": "LIMITED", "client_presentation": "NO",
      "board": "NO", "public_external_use": "NO"}),
    (0,  "E", "Deliverable not reliable",
     {"internal_codir": "NO", "client_presentation": "NO",
      "board": "NO", "public_external_use": "NO"}),
]


def _grade_table(lang: str = "fr"):
    return _GRADE_TABLE_EN if (lang or "fr").lower() == "en" else _GRADE_TABLE


def _explanation_map(lang: str = "fr") -> dict:
    return EXPLANATION_MAP_DG_EN if (lang or "fr").lower() == "en" else EXPLANATION_MAP_DG


def _next_action_map(lang: str = "fr") -> dict:
    return NEXT_ACTION_MAP_EN if (lang or "fr").lower() == "en" else NEXT_ACTION_MAP


EVIDENCE_CAP_CEILING = 62   # M6-A3.2 — sans faits consolidés structurés, plafond
                            # bas-Grade C (un signal financier n'est PAS une preuve ;
                            # passe à un cap gradué piloté par les faits en M6-B)


def evidence_cap(final_score: int,
                 statements_detected: bool | None,
                 core_metrics_missing: bool | None,
                 statements_block_empty: bool | None = None) -> tuple[int, bool]:
    """M6-C — cap d'honnêteté preuve. Pas de Grade A/B sans preuve financière
    structurée : si le bloc de comptes structuré est vide (statements_block_empty
    is True) OU non détecté (statements_detected is False) OU métriques cœur
    manquantes (Revenue / Net income), le score est plafonné à Grade C.

    None = signal inconnu → ne déclenche JAMAIS le cap (zéro régression sur les
    scorings qui ne renseignent pas ces champs).

    Retour : (score_éventuellement_capé, cap_appliqué).
    """
    insufficient = (
        (statements_block_empty is True)
        or (statements_detected is False)
        or bool(core_metrics_missing)
    )
    if insufficient and final_score > EVIDENCE_CAP_CEILING:
        return EVIDENCE_CAP_CEILING, True
    return final_score, False


def grade_and_usage(score: int, lang: str = "fr") -> tuple[str, str, dict[str, str]]:
    """Retourne (grade, label, usage_recommendation) localisé selon lang."""
    table = _grade_table(lang)
    for threshold, grade, label, usage in table:
        if score >= threshold:
            return grade, label, usage
    # Théoriquement inatteignable car le dernier seuil est 0
    return "E", table[-1][2], table[-1][3]


# =============================================================================
# TREND (v5 addendum)
# =============================================================================

def compute_trend(current: int, previous: int | None) -> dict:
    if previous is None:
        return {"previous_score": None, "delta": None, "trend_label": "FIRST_RUN"}
    delta = current - previous
    if delta >= 10:   lbl = "STRONG_IMPROVEMENT"
    elif delta >= 3:  lbl = "IMPROVING"
    elif delta > -3:  lbl = "STABLE"
    elif delta > -10: lbl = "DEGRADING"
    else:             lbl = "STRONG_DEGRADATION"
    return {"previous_score": previous, "delta": delta, "trend_label": lbl}


# =============================================================================
# NEXT BEST ACTIONS (dynamique)
# =============================================================================

def build_next_best_actions(penalties: list[dict], max_actions: int = 3, lang: str = "fr") -> list[str]:
    """
    Dérive les actions depuis les pénalités, triées par impact décroissant.

    v16.5.65 — Les pénalités GENERIC_BRIEF_MODE_CAP / PARTIAL_BRIEF_MODE_CAP
    sont forcées en 1ère position de la liste (action racine). Sans elles,
    les actions recommandées adressent les symptômes (sources, alertes) et
    non la cause (brief lui-même).
    """
    MODE_PRIORITY_CODES = {"GENERIC_BRIEF_MODE_CAP", "PARTIAL_BRIEF_MODE_CAP"}
    mode_pen = [p for p in penalties if p.get("code") in MODE_PRIORITY_CODES]
    other_pen = [p for p in penalties if p.get("code") not in MODE_PRIORITY_CODES]
    sorted_other = sorted(other_pen, key=lambda p: p.get("impact", 0))  # plus négatif d'abord
    ordered = mode_pen + sorted_other

    seen = set()
    actions = []
    for p in ordered:
        code = p.get("code", "")
        action = _next_action_map(lang).get(code)
        if action and action not in seen:
            actions.append(action)
            seen.add(action)
        if len(actions) >= max_actions:
            break
    return actions


# =============================================================================
# CONFIDENCE EXPLANATION (wording DG déterministe)
# =============================================================================

def build_confidence_explanation(penalties: list[dict],
                                 bonuses: list[dict],
                                 max_items: int = 4, lang: str = "fr") -> list[str]:
    """
    Génère 3-4 phrases DG-ready expliquant le score. Déterministe (pas de LLM).
    Trie par |impact| décroissant.

    v16.5.65 — Les pénalités GENERIC_BRIEF_MODE_CAP / PARTIAL_BRIEF_MODE_CAP
    sont forcées en 1ère position (cause racine) indépendamment de leur |impact|,
    pour que l'utilisateur voie bien que le brief lui-même est la cause du plafond.
    """
    items = penalties + bonuses
    MODE_PRIORITY_CODES = {"GENERIC_BRIEF_MODE_CAP", "PARTIAL_BRIEF_MODE_CAP"}

    # Extraction de la pénalité mode si elle existe
    mode_items = [x for x in items if x.get("code") in MODE_PRIORITY_CODES]
    other_items = [x for x in items if x.get("code") not in MODE_PRIORITY_CODES]

    # Tri standard par |impact| décroissant pour les autres
    other_sorted = sorted(other_items, key=lambda x: abs(x.get("impact", 0)), reverse=True)

    # Mode en tête, puis le reste
    items_sorted = mode_items + other_sorted

    lines = []
    for item in items_sorted:
        code = item.get("code", "")
        if code not in _explanation_map(lang):
            continue
        template = _explanation_map(lang)[code]
        if not template:
            continue
        kwargs = {
            "impact": item.get("impact", 0),
            "n": item.get("n", 1),
        }
        try:
            lines.append(template.format(**kwargs))
        except (KeyError, ValueError):
            continue
        if len(lines) >= max_items:
            break
    return lines


# =============================================================================
# CALCULATION TRACE
# =============================================================================

def build_calculation_trace(components: dict[str, int],
                            penalties: list[dict],
                            bonuses: list[dict],
                            raw_mix: int,
                            source_quality: int,
                            final_score: int) -> list[dict]:
    """Trace auditable pas à pas, consommable en UI détaillée."""
    trace = []
    for comp_name, weight in WEIGHTS.items():
        comp_penalties = [p for p in penalties if p.get("component") == comp_name]
        comp_bonuses   = [b for b in bonuses   if b.get("component") == comp_name]
        adjustments = [{"code": x["code"], "delta": x["impact"]}
                       for x in (comp_penalties + comp_bonuses)]
        entry = {
            "step": comp_name,
            "adjustments": adjustments,
            "final": components[comp_name],
            "weight": weight,
            "contribution": round(components[comp_name] * weight, 2),
        }
        if comp_name == "content_mix" and raw_mix != components["content_mix"]:
            entry["raw"] = raw_mix
            entry["cap_applied_from"] = f"source_quality+20={source_quality + 20}"
        trace.append(entry)
    trace.append({
        "step": "aggregate",
        "sum_weighted": round(sum(components[k] * WEIGHTS[k] for k in WEIGHTS), 2),
        "rounded": final_score,
    })
    return trace


# =============================================================================
# FONCTION PRINCIPALE
# =============================================================================

def compute_delivery_confidence_score(
    run_ctx: dict,
    previous_score: int | None = None,
    lang: str = "fr",
) -> dict:
    """
    Calcule le delivery_confidence_score à partir du contexte de run.
    
    run_ctx doit contenir :
    - all_metrics: list[dict]  — métriques taguées produites par les agents
    - attachments: list[Path]  — pièces attachées au brief (optionnel)
    - financial_docs_attached: bool
    - internal_docs_count: int
    - red_alerts_unresolved: int
    - orange_alerts_unresolved: int
    - unresolved_conflicts: int
    - retry_count_total: int
    - agent_refusals_count: int
    - rejected_outputs_count: int
    - sector_unknown: bool
    - benchmark_available: bool
    - completeness_checks: dict[str, bool]  (facultatif)
    """
    # 1. Reclassification des métriques (anti-manipulation)
    raw_metrics = run_ctx.get("all_metrics", [])
    attachments = run_ctx.get("attachments", [])
    metrics = reclassify_metrics(raw_metrics, attachments)
    
    # 2. Cap contextuel (anti-bluff par inflation v5)
    metrics_capped = apply_contextual_cap(metrics)
    n_dropped = len(metrics) - len(metrics_capped)
    
    # 3. Content mix
    mix = compute_content_mix(metrics_capped)
    
    # 4. Sous-scores
    penalties: list[dict] = []
    bonuses: list[dict] = []
    
    s1, p1, b1 = score_source_quality(
        has_financial_docs=run_ctx.get("financial_docs_attached", False),
        sourced_fact_ratio=mix["fait_verified_ratio"],
        internal_docs_count=run_ctx.get("internal_docs_count", 0),
        # Since v16.5.70 — Sous-flags étendus pour granularité documentaire
        financial_statements_detected=run_ctx.get("financial_statements_detected"),
        financial_tables_extracted=run_ctx.get("financial_tables_extracted"),
        n_pdfs_with_fs=run_ctx.get("n_pdfs_with_fs", 0),
        # Patch v16.5.71.1 P0 — Signal multi-format (audit ChatGPT round 9)
        financial_signal_in_attachments_solid=run_ctx.get(
            "financial_signal_in_attachments_solid", False
        ),
        financial_signal_score=run_ctx.get("financial_signal_score"),
    )
    s2_raw, p2, b2 = score_content_mix(mix)
    s3, p3, b3 = score_consistency(
        red_alerts=run_ctx.get("red_alerts_unresolved", 0),
        orange_alerts=run_ctx.get("orange_alerts_unresolved", 0),
        unresolved_conflicts=run_ctx.get("unresolved_conflicts", 0),
    )
    s4, p4, b4 = score_completeness(run_ctx.get("completeness_checks", {}))

    # v16.5.66 — Compter les agents sans JSON exploitable
    agent_json_stats = run_ctx.get("agent_json_stats", {}) or {}
    n_missing_json = 0
    if isinstance(agent_json_stats, dict):
        n_missing_json = sum(
            1 for stats in agent_json_stats.values()
            if isinstance(stats, dict)
            and stats.get("parse_status") in ("MISSING", "MALFORMED")
        )

    s5, p5, b5 = score_run_stability(
        retry_count_total=run_ctx.get("retry_count_total", 0),
        refusals_count=run_ctx.get("agent_refusals_count", 0),
        rejected_outputs_count=run_ctx.get("rejected_outputs_count", 0),
        missing_agent_json_count=n_missing_json,
    )
    s6, p6, b6 = score_sector_confidence(
        sector_unknown=run_ctx.get("sector_unknown", False),
        benchmark_available=run_ctx.get("benchmark_available", True),
    )
    
    for pp in (p1, p2, p3, p4, p5, p6): penalties += pp
    for bb in (b1, b2, b3, b4, b5, b6): bonuses += bb
    
    # 5. Cross-check : content_mix ≤ source_quality + 20 (v4)
    s2 = min(s2_raw, s1 + 20)
    if s2 < s2_raw:
        penalties.append({
            "code": "CROSS_CHECK_MIX_CAPPED",
            "impact": s2 - s2_raw,
            "component": "content_mix",
            "reason": f"content_mix plafonné par source_quality+20 ({s1+20}) — brut {s2_raw} → {s2}.",
        })
    
    # 6. Pénalité cap contextuel si métriques droppées (v5)
    if n_dropped > 0:
        penalties.append({
            "code": "HIGH_CONTEXTUAL_RATIO",
            "impact": -5,
            "component": "content_mix",
            "reason": f"{n_dropped} métrique(s) contextuelle(s) excédentaire(s) (cap {CONTEXTUAL_CAP:.0%}).",
        })

    # Note: v16.5.66 — la pénalité MISSING_AGENT_JSON_CLAIMS est maintenant portée
    # directement par score_run_stability(), pas de double comptage ici.
    
    # 7. Agrégation pondérée
    components = {
        "source_quality":    s1,
        "content_mix":       s2,
        "consistency":       s3,
        "completeness":      s4,
        "run_stability":     s5,
        "sector_confidence": s6,
    }
    final_score_uncapped = int(round(_clamp(
        sum(components[k] * WEIGHTS[k] for k in WEIGHTS)
    )))

    # 7bis. v16.5.65 — Plafond mode de briefing
    # Si le briefcheck a détecté un mode GENERIC/PARTIAL, on plafonne le score
    # final ici. Le plafonnement est APRÈS agrégation (pas avant) : les sous-scores
    # restent lisibles dans la trace, c'est seulement le score global qui est capé.
    brief_mode = str(run_ctx.get("brief_mode", "")).upper()
    brief_mode_cap = BRIEF_MODE_SCORE_CAP.get(brief_mode)
    final_score = final_score_uncapped
    if brief_mode_cap is not None and final_score_uncapped > brief_mode_cap:
        capped_impact = brief_mode_cap - final_score_uncapped  # négatif
        final_score = brief_mode_cap
        code_suffix = "GENERIC_BRIEF_MODE_CAP" if brief_mode == "GENERIC" else "PARTIAL_BRIEF_MODE_CAP"
        present_count = run_ctx.get("brief_mode_present_count")
        reason_extra = ""
        if brief_mode == "GENERIC":
            reason_extra = "aucun levier qualifié (contexte, chiffres, décision, enjeu)"
        elif brief_mode == "PARTIAL" and isinstance(present_count, int):
            reason_extra = f"{present_count}/4 leviers qualifiés"
        elif brief_mode == "PARTIAL":
            reason_extra = "brief partiellement qualifié"
        penalties.append({
            "code": code_suffix,
            "impact": capped_impact,
            "component": "source_quality",  # rattachement logique
            "reason": (f"Mode brief {brief_mode} — score plafonné à {brief_mode_cap}/100 "
                       f"(brut {final_score_uncapped}) : {reason_extra}.") if reason_extra else
                      f"Mode brief {brief_mode} — score plafonné à {brief_mode_cap}/100 (brut {final_score_uncapped}).",
        })
    
    # 7ter. M6-C — cap d'honnêteté preuve (mesuré : financial_statements_block vide
    # + Revenue/Net income manquants coexistaient avec un Grade B → trompeur).
    _score_after_brief_mode_cap = final_score
    _fs_detected = run_ctx.get("financial_statements_detected")
    _core_missing = run_ctx.get("core_metrics_missing")
    _fs_block_empty = run_ctx.get("financial_statements_block_empty")
    final_score, _evidence_capped = evidence_cap(
        final_score, _fs_detected, _core_missing,
        statements_block_empty=_fs_block_empty)
    if _evidence_capped:
        penalties.append({
            "code": "EVIDENCE_CAP_NO_STRUCTURED_PROOF",
            "impact": EVIDENCE_CAP_CEILING - final_score_uncapped,
            "component": "source_quality",
            "reason": ("Preuve financière structurée insuffisante "
                       "(aucun bloc de comptes structuré ou Revenue/Net income manquants) "
                       f"— score plafonné à Grade C ({EVIDENCE_CAP_CEILING}/100)."
                       if (lang or "fr").lower() != "en" else
                       "Insufficient structured financial evidence "
                       "(no structured statements block or Revenue/Net income missing) "
                       f"— score capped at Grade C ({EVIDENCE_CAP_CEILING}/100)."),
        })

    # 8. Grade + usage
    grade, label, usage = grade_and_usage(final_score, lang)
    
    # 9. Trend
    trend = compute_trend(final_score, previous_score)
    
    # 10. Actions dérivées
    next_actions = build_next_best_actions(penalties, max_actions=3, lang=lang)
    
    # 11. Explanation DG (wording déterministe)
    explanation = build_confidence_explanation(penalties, bonuses, max_items=4, lang=lang)
    
    # 12. Trace auditable
    trace = build_calculation_trace(components, penalties, bonuses,
                                    raw_mix=s2_raw, source_quality=s1,
                                    final_score=final_score)
    
    # v16.5.76 item 9 — Exposer le score brut hors plafond de manière lisible
    # UX : permet d'afficher "Score: 77/100 (brut 84 avant cap PARTIAL)" plutôt
    # que de cacher la mécanique au DAF.
    cap_applied = bool(brief_mode_cap is not None and final_score_uncapped > brief_mode_cap)

    return {
        "score": final_score,
        "grade": grade,
        "label": label,
        "previous_score": trend["previous_score"],
        "delta": trend["delta"],
        "trend_label": trend["trend_label"],
        "component_scores": components,
        "content_mix": mix,
        # v16.5.65 — traçabilité mode brief
        "brief_mode": brief_mode or None,
        "brief_mode_cap": brief_mode_cap,
        "score_before_mode_cap": final_score_uncapped,
        # v16.5.76 item 9 — aliases lisibles pour l'UI et les tests
        "raw_score": final_score_uncapped,
        # v62.10 — named stages: no more ambiguous "raw" score.
        "pre_cap_weighted_score": final_score_uncapped,
        "post_brief_mode_cap_score": _score_after_brief_mode_cap,
        "post_structured_evidence_cap_score": final_score,
        "final_evidence_score": final_score,
        "cap_applied": cap_applied,
        "cap_delta": (final_score_uncapped - final_score) if cap_applied else 0,
        "run_metrics": {
            "orange_alerts_unresolved": run_ctx.get("orange_alerts_unresolved", 0),
            "red_alerts_unresolved":    run_ctx.get("red_alerts_unresolved", 0),
            "retry_count_total":        run_ctx.get("retry_count_total", 0),
            "agent_refusals_count":     run_ctx.get("agent_refusals_count", 0),
            "rejected_outputs_count":   run_ctx.get("rejected_outputs_count", 0),
            "sector_unknown":           run_ctx.get("sector_unknown", False),
            "benchmark_available":      run_ctx.get("benchmark_available", True),
            "financial_docs_attached":  run_ctx.get("financial_docs_attached", False),
            # Since v16.5.70 — 4 sous-flags pour granularité documentaire
            "financial_statements_detected": run_ctx.get("financial_statements_detected"),
            "financial_tables_extracted":    run_ctx.get("financial_tables_extracted"),
            "n_pdfs_with_fs":                run_ctx.get("n_pdfs_with_fs", 0),
            # Patch v16.5.71.1 P0 — Signal multi-format propagé
            "financial_signal_in_attachments_solid": run_ctx.get(
                "financial_signal_in_attachments_solid", False
            ),
            "financial_signal_score":        run_ctx.get("financial_signal_score"),
            "financial_signal_keywords":     run_ctx.get("financial_signal_keywords", 0),
            "financial_signal_amounts":      run_ctx.get("financial_signal_amounts", 0),
            "internal_docs_count":      run_ctx.get("internal_docs_count", 0),
            "contextual_dropped":       n_dropped,
        },
        "penalties": penalties,
        "bonuses":   bonuses,
        "confidence_explanation": explanation,
        "calculation_trace": trace,
        "usage_recommendation": usage,
        "next_best_actions": next_actions,
    }


__all__ = [
    "compute_delivery_confidence_score",
    "classify_source_quality_level",
    "reclassify_metrics",
    "apply_contextual_cap",
    "compute_content_mix",
    "grade_and_usage",
    "build_confidence_explanation",
    "build_next_best_actions",
    # constantes exportées pour tests et extensions
    "WEIGHTS", "DECISION_WEIGHTS", "VERIFICATION_MULTIPLIER",
    "CONTEXTUAL_CAP", "MIN_METRICS_SAMPLE",
    "BRIEF_MODE_SCORE_CAP",
    "NEXT_ACTION_MAP", "EXPLANATION_MAP_DG",
]
