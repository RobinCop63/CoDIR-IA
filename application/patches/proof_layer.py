"""
patches/proof_layer.py — v17.4.0-M6B-B1.0 (M6-B · B.1 · orchestrateur E1→E6)

COUCHE DE PREUVE B.1 — point d'entrée UNIQUE pour le moteur.

Le moteur (codir_engine) appelle apply_b1_proof_layer() UNE fois, après la
construction de la table de faits Couche 1 et l'inférence du contexte
d'analyse. Fail-open : toute exception interne laisse la table intacte
(aucune régression possible du pipeline existant).

Séquence :
    1. Identité (E1)   : metric_canonical_id, period, unit/currency/scale,
                         normalized_value, perimeter_entity par défaut,
                         consolidation_role, retrieved_at, stable_fact_key,
                         fact_instance_id, run_id, analysis_context_id.
    2. Périmètre (E3)  : perimeter_match FULL|COVERAGE|MISMATCH|NA + entity_match.
    3. Conflits (E4)   : détection + conflict_group_id posés.
    4. Garde conso (E5): agrégats SOUS réserve (mode consolidation) +
                         étiquette D4 obligatoire ; coverage_map (donnée brute).
    5. Board-safe (§8.3): blockers posés (le HARD GATE est enforcé en B.4a).
    6. Fingerprint (E6): structuré depuis diag_list + résolution.

Retour : dict {conflicts, fingerprint, coverage, signal_effective,
signal_gate_reason, journal_rows} — le moteur journalise et propage.

100 % déterministe, sans clé API.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from patches.analysis_context import AnalysisContext, MODE_CONSO, MODE_MONO
from patches.fact_identity import (
    canonical_metric_id, parse_value, stable_fact_key, fact_instance_id,
    provisional_source_ref, make_run_id,
)
from patches.perimeter_match import (
    annotate_facts_perimeter, gate_financial_signal, MATCH_COVERAGE,
)
from patches.fact_conflict import detect_fact_conflicts
from patches.conso_guard import (
    guard_aggregated_fact, aggregate_declared_entities, coverage_map,
    reserve_label,
)
from patches.board_safe import annotate_board_safe
from patches.run_fingerprint import build_run_fingerprint

# B.1.1 — les regex de période locales ont été retirées : la règle UNIQUE
# d'extraction (année marquée seulement) vit dans fact_identity.extract_marked_period.


def _extract_period(fact: Any) -> str:
    """
    Période B.1 : label, value, section — via la règle CENTRALE
    fact_identity.extract_marked_period (B.1.1). Une année nue dans une
    valeur (« Effectif : 2050 personnes ») n'est JAMAIS une période.
    """
    from patches.fact_identity import extract_marked_period
    for source in (getattr(fact, "label", ""), getattr(fact, "value", ""),
                   getattr(fact, "source_section", "") or ""):
        p = extract_marked_period(str(source or ""))
        if p:
            return p
    return ""


def _default_perimeter_entity(fact: Any, ctx: AnalysisContext,
                              registry_entity: str) -> str:
    """
    Entité de périmètre par défaut (B.1, enrichi en B.2) :
      · faits registre (SOCIAL_STANDALONE / HOLDING) → entité résolue registre ;
      · faits CONSOLIDATED → entité cible du contexte ;
      · sinon inchangé.
    """
    current = getattr(fact, "perimeter_entity", "") or ""
    if current:
        return current
    scope = (getattr(fact, "scope", "") or "").upper()
    if scope in ("SOCIAL_STANDALONE", "HOLDING") and registry_entity:
        return registry_entity
    if scope == "CONSOLIDATED":
        return ctx.target_entity or registry_entity
    return ""



_EXCERPT_ENTITY65 = re.compile(
    r"\b(?:de|d['’]|du|of)\s*((?:[A-ZÉÈÀÂÎÔÛ][\w'’\-]+\s+){0,3}[A-ZÉÈÀÂÎÔÛ][\w'’\-]+)\s+"
    r"(?:était|est|s['’]élevait|s['’]élève|atteignait|atteint|représentait|représente|was|is|amounted)\b")
_GENERIC_ENTITY65 = {"la", "le", "les", "l", "société", "societe", "groupe", "group", "entreprise", "company", "exercice",
                     "l’exercice", "l'exercice", "année", "periode", "période", "france", "it", "this", "the"}


def reattribute_facts_by_excerpt_entity65(facts, ctx, registry_entity: str = "") -> int:
    """9.4.65 — contre-recette du 17/10/2026 (LM01) : « L'effectif moyen de <filiale> était de <n> personnes »
    était attribué à l'entité cible ; le chiffre devenait l'effectif du groupe sur les cartes exécutives et un
    faux conflit avec l'effectif de la cible. Quand la phrase source NOMME explicitement une autre société comme sujet de la
    valeur, le fait est attribué à cette société, en comptes sociaux. Le nom de la cible (ou un de ses mots) ne change rien."""
    target = str(registry_entity or getattr(ctx, "target_entity", "") or "").strip()
    ttoks = {w for w in re.findall(r"[a-zà-ÿ]{3,}", target.lower())}
    changed = 0
    for f in facts or ():
        excerpt = str(getattr(f, "source_excerpt", "") or "")
        val = str(getattr(f, "source_value_text", "") or getattr(f, "value", "") or "").strip()
        if not excerpt or not val:
            continue
        num = re.match(r"[\d\s.,]+", val)
        key = (num.group(0).strip() if num else val)[:12]
        sent = next((s for s in re.split(r"(?<=[.;])\s+", excerpt) if key and key in s), "")
        if not sent:
            continue
        m = _EXCERPT_ENTITY65.search(sent)
        if not m:
            continue
        name = m.group(1).strip()
        ntoks = [w for w in re.findall(r"[a-zà-ÿ]{3,}", name.lower())]
        if not ntoks or all(w in _GENERIC_ENTITY65 for w in ntoks) or any(w in ttoks for w in ntoks):
            continue
        cur = str(getattr(f, "perimeter_entity", "") or "").strip()
        if cur.lower() == name.lower():
            continue
        try:
            f.perimeter_entity = name.upper()
            if (getattr(f, "scope", "") or "").upper() in ("", "UNKNOWN", "HOLDING", "CONSOLIDATED"):
                f.scope = "SOCIAL_STANDALONE"
            changed += 1
        except Exception:
            continue
    return changed


def reattribute_facts_by_source_document(facts, ctx, registry_entity: str = "") -> int:
    """v62.13.9.4.38 — UNE PIÈCE QUI PORTE LE NOM D'UNE AUTRE SOCIÉTÉ PORTE SES FAITS.

    Run réel du 19/09/2026 (réseau de soins) : les comptes sociaux joints de deux
    filiales (FILIALE_A~2.PDF, FILIALE_B~1.PDF) étaient imputés à la tête de groupe (HOLDING) ;
    leurs totaux de bilan et résultats devenaient des « conflits durs » entre valeurs
    « de la même entité » et plafonnaient le dossier à 45/100. Quand le nom de fichier
    d'une pièce commence par un nom d'entité DÉJÀ CONNU de la table (une filiale
    nommée dans une autre pièce), différent de l'entité cible, ses faits sont attribués
    à cette entité en périmètre SOCIAL_STANDALONE : tension de périmètre, pas
    contradiction interne. Un radical qui ne correspond à aucune entité connue ne
    change rien (« Fusion_… », « CA_… »).
    """
    target = str(registry_entity or getattr(ctx, "target_entity", "") or "").strip().lower()
    known: dict[str, str] = {}
    for f in facts or ():
        pe = str(getattr(f, "perimeter_entity", "") or "").strip()
        if pe and pe.lower() != target and len(pe) >= 3:
            known[pe.lower().split(" ")[0]] = pe
    if not known:
        return 0
    changed = 0
    for f in facts or ():
        doc = str(getattr(f, "source_doc", "") or "").strip()
        if not doc:
            continue
        stem = re.split(r"[~_\-. ]", doc, 1)[0].lower()
        if len(stem) < 4 or target.startswith(stem):
            continue
        match = next((v for k, v in known.items() if k == stem or k.startswith(stem) or stem.startswith(k)), "")
        if not match:
            continue
        if str(getattr(f, "perimeter_entity", "") or "").strip().lower() == match.lower():
            continue
        try:
            f.perimeter_entity = match
            if (getattr(f, "scope", "") or "").upper() == "HOLDING":
                f.scope = "SOCIAL_STANDALONE"
            changed += 1
        except Exception:
            continue
    return changed

def _consolidation_role(fact: Any, ctx: AnalysisContext) -> str:
    if ctx.mode == MODE_MONO:
        return "sans_objet"
    pm = getattr(fact, "perimeter_match", "")
    if pm == "FULL":
        return "est_le_groupe"
    if pm == MATCH_COVERAGE:
        return "contribue_au_groupe"
    scope = (getattr(fact, "scope", "") or "").upper()
    if scope in ("SOCIAL_STANDALONE", "HOLDING"):
        return "contribue_au_groupe"
    return "sans_objet"


def enrich_fact_identity(
    fact: Any,
    *,
    ctx: AnalysisContext,
    run_id: str,
    registry_entity: str = "",
    registry_entity_id: str = "",
    registry_resolution_id: str = "",
    retrieved_at: str = "",
) -> None:
    """E1 — pose l'identité complète sur UN fait (in place). Ne lève jamais."""
    try:
        if not getattr(fact, "metric_canonical_id", ""):
            fact.metric_canonical_id = canonical_metric_id(getattr(fact, "label", ""))
        if getattr(fact, "normalized_value", None) is None:
            nv, unit, currency, scale = parse_value(getattr(fact, "value", ""))
            fact.normalized_value = nv
            if not getattr(fact, "unit", ""):
                fact.unit = unit
            if not getattr(fact, "currency", ""):
                fact.currency = currency
            if not getattr(fact, "scale", ""):
                fact.scale = scale
        if not getattr(fact, "period", ""):
            fact.period = _extract_period(fact)
        fact.perimeter_entity = _default_perimeter_entity(fact, ctx, registry_entity)
        if not getattr(fact, "entity_id", ""):
            scope = (getattr(fact, "scope", "") or "").upper()
            if scope in ("SOCIAL_STANDALONE", "HOLDING") and registry_entity_id:
                fact.entity_id = registry_entity_id
        if not getattr(fact, "retrieved_at", ""):
            fact.retrieved_at = retrieved_at
        fact.run_id = run_id
        fact.analysis_context_id = ctx.analysis_context_id
        # Clé stable — indépendante du run et de la source (propriété E1).
        fact.stable_fact_key = stable_fact_key(
            metric_canonical_id=fact.metric_canonical_id,
            period=getattr(fact, "period", ""),
            perimeter_entity=getattr(fact, "perimeter_entity", ""),
            perimeter_level=(getattr(fact, "scope", "") or "UNKNOWN"),
            normalized_value=getattr(fact, "normalized_value", None),
            unit=getattr(fact, "unit", ""),
            currency=getattr(fact, "currency", ""),  # B.1.2
            scale=getattr(fact, "scale", ""),
        )
        src_ref = provisional_source_ref(
            registry_resolution_id=(registry_resolution_id
                                    if (getattr(fact, "scope", "") or "").upper()
                                    in ("SOCIAL_STANDALONE", "HOLDING") else ""),
            source_doc=getattr(fact, "source_doc", None),
            source_page=getattr(fact, "source_page", None),
            source_section=getattr(fact, "source_section", None),
            is_brief=not getattr(fact, "source_doc", None),
        )
        fact.fact_instance_id = fact_instance_id(fact.stable_fact_key, src_ref)
    except Exception:
        pass


def _make_aggregate_fact(agg: Dict[str, Any], ctx: AnalysisContext,
                         *, lang: str, run_id: str) -> Optional[Any]:
    """Construit le FinancialFact d'un agrégat sous réserve (E5)."""
    try:
        from utils.financial_facts_table import FinancialFact, FactStatus
        # Libellé canonique FR (clé d'affichage maison)
        label_map = {
            "REVENUE": "Chiffre d'affaires", "NET_INCOME": "Résultat net",
            "HEADCOUNT": "Effectif", "EBITDA": "EBITDA", "CASH": "Trésorerie",
            "NET_DEBT": "Dette nette", "EQUITY": "Capitaux propres",
        }
        base_label = label_map.get(agg["metric_canonical_id"],
                                   agg["metric_canonical_id"])
        n = agg["n_entities"]
        label = (f"{base_label} — somme brute {n} entités"
                 if lang != "en" else f"{base_label} — raw sum of {n} entities")
        nv = agg["normalized_value"]
        cur_sym = {"EUR": "€", "GBP": "£", "USD": "$"}.get(agg.get("currency", ""), "")
        if agg.get("unit") == "PERSONS":
            value = f"{nv:,.0f}".replace(",", " ") + (" personnes" if lang != "en" else " persons")
        elif abs(nv) >= 1e6:
            value = f"{nv/1e6:,.1f}".replace(",", " ").replace(".", ",") + f" M{cur_sym}"
        else:
            value = f"{nv:,.0f}".replace(",", " ") + f" {cur_sym}".rstrip()
        fact = FinancialFact(
            label=label,
            value=value,
            status=FactStatus.ESTIM_IA,
            scope="ESTIMATE",
            notes=[agg["reserve_label"]],
        )
        fact.metric_canonical_id = agg["metric_canonical_id"]
        fact.normalized_value = nv
        fact.unit = agg.get("unit", "")
        fact.currency = agg.get("currency", "")
        fact.scale = ""  # normalized_value est en base (convention parse_value)
        fact.period = agg.get("period", "") or ""
        fact.transformation = "agrégé"
        fact.perimeter_entity = ctx.target_entity
        fact.perimeter_match = MATCH_COVERAGE
        fact.consolidation_role = "contribue_au_groupe"
        fact.run_id = run_id
        fact.analysis_context_id = ctx.analysis_context_id
        # ── B.1.1 (audit gate B.2, P1) — identité STABLE de l'agrégat ────────
        # Principe B.1 : TOUT fait financier est rapprochable entre deux runs,
        # y compris une « somme brute sous réserve ». Sans quoi Christopher ne
        # distingue pas agrégat stable / modifié / corrigé.
        #   · stable_fact_key : indépendante du run (métrique, période commune,
        #     entité cible, niveau du contexte, valeur, unité) — deux runs
        #     identiques → MÊME clé (propriété testée).
        #   · fact_instance_id : clé × constituants — une brique change →
        #     instance différente, à contenu identique → instance identique.
        from patches.fact_identity import (
            stable_fact_key as _sfk, fact_instance_id as _fiid, _h as _fh)
        fact.stable_fact_key = _sfk(
            metric_canonical_id=fact.metric_canonical_id,
            period=fact.period,
            perimeter_entity=fact.perimeter_entity,
            perimeter_level=(ctx.target_perimeter_level or "UNKNOWN"),
            normalized_value=nv,
            unit=fact.unit,
            currency=fact.currency,  # B.1.2
            scale=fact.scale,
        )
        _constituents = "|".join(agg.get("constituent_keys", []) or [])
        fact.fact_instance_id = _fiid(
            fact.stable_fact_key, "AGG-" + _fh(_constituents))
        fact.retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        guard_aggregated_fact(fact, lang=lang)
        if agg.get("period_heterogeneous"):
            blockers = list(getattr(fact, "board_safe_blockers", []) or [])
            if "period_heterogeneous" not in blockers:
                blockers.append("period_heterogeneous")
            fact.board_safe_blockers = blockers
        return fact
    except Exception:
        return None


def _conso_periods_heterogeneous(facts: Iterable[Any]) -> bool:
    """Périodes hétérogènes parmi les briques COVERAGE d'une même métrique."""
    by_metric: Dict[str, set] = {}
    for f in facts or []:
        if getattr(f, "perimeter_match", "") != MATCH_COVERAGE:
            continue
        p = getattr(f, "period", "") or ""
        if not p:
            continue
        by_metric.setdefault(getattr(f, "metric_canonical_id", ""), set()).add(p)
    return any(len(periods) > 1 for periods in by_metric.values())


def apply_b1_proof_layer(
    facts_table: Any,
    ctx: AnalysisContext,
    *,
    raw_signal_solid: bool = False,
    diag_rows: Optional[List[Dict[str, Any]]] = None,
    registry_entity: str = "",
    registry_entity_id: str = "",
    registry_resolution_id: str = "",
    candidate_entities: Optional[List[str]] = None,
    choice_reason: str = "",
    lang: str = "fr",
    run_id: str = "",
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Applique la couche de preuve B.1 à une FinancialFactsTable (in place).
    Fail-open sur l'EXÉCUTION : ne lève jamais. Fail-SAFE sur la
    CERTIFICATION (B.1.2, audit gate B.2 P0) : les défauts du résultat
    disent « preuve NON appliquée, signal NON certifié » — signal_effective
    ne vaut True que si le chemin complet a réussi ET que la porte l'a
    laissé passer. proof_applied est LE témoin que le moteur doit consommer.
    """
    result: Dict[str, Any] = {
        "conflicts": [], "fingerprint": None, "coverage": {},
        "proof_applied": False,
        "proof_error": "",
        "signal_effective": False,
        "signal_gate_reason": "proof_layer_not_applied",
        "journal_rows": [],
        "run_id": run_id,
    }
    try:
        facts = list(getattr(facts_table, "facts", []) or [])
        rid = run_id or make_run_id(now)
        result["run_id"] = rid
        retrieved_at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")

        # 1 — Identité (E1)
        for f in facts:
            enrich_fact_identity(
                f, ctx=ctx, run_id=rid,
                registry_entity=registry_entity,
                registry_entity_id=registry_entity_id,
                registry_resolution_id=registry_resolution_id,
                retrieved_at=retrieved_at,
            )

        # 1bis — v62.13.9.4.38 : une pièce au nom d'une autre société porte ses faits
        try:
            result["facts_reattributed_by_document"] = reattribute_facts_by_source_document(
                facts, ctx, registry_entity=registry_entity)
        except Exception:
            result["facts_reattributed_by_document"] = 0
        try:   # 9.4.65 (LM01) — la société nommée dans la phrase source porte le fait
            result["facts_reattributed_by_excerpt65"] = reattribute_facts_by_excerpt_entity65(
                facts, ctx, registry_entity=registry_entity)
        except Exception:
            result["facts_reattributed_by_excerpt65"] = 0

        # 2 — Périmètre (E3)
        annotate_facts_perimeter(facts, ctx)
        for f in facts:
            try:
                f.consolidation_role = _consolidation_role(f, ctx)
            except Exception:
                pass

        # 3 — Conflits (E4), anchored to the same dossier authority as FPL.
        try:
            from utils.financial_proof_layer import compute_dossier_authoritative_period_end
            _authority_62131 = compute_dossier_authoritative_period_end(facts)
        except Exception:
            _authority_62131 = ""
        conflicts = detect_fact_conflicts(
            facts, ctx, lang=lang, authoritative_period_end=_authority_62131 or None)
        result["conflicts"] = conflicts

        # 4 — Garde conso (E5) : agrégats sous réserve + coverage_map
        period_hetero = False
        if ctx.mode == MODE_CONSO:
            period_hetero = _conso_periods_heterogeneous(facts)
            for metric in list(ctx.expected_metrics or []):
                agg = aggregate_declared_entities(
                    facts, ctx, metric_canonical_id=metric, lang=lang)
                if agg:
                    agg_fact = _make_aggregate_fact(agg, ctx, lang=lang, run_id=rid)
                    if agg_fact is not None:
                        try:
                            facts_table.add(agg_fact)
                            facts.append(agg_fact)
                        except Exception:
                            pass
            result["coverage"] = coverage_map(facts, ctx)
        # étiquette D4 sur toute agrégation préexistante, quel que soit le mode
        for f in facts:
            if (getattr(f, "transformation", "") or "") == "agrégé":
                guard_aggregated_fact(f, lang=lang)

        # 5 — Board-safe (§8.3) : blockers posés (gate enforcé en B.4a)
        annotate_board_safe(facts, conflicts, period_heterogeneous=period_hetero)

        # 6 — La porte du signal (le fix v5) + fingerprint (E6)
        eff, reason = gate_financial_signal(raw_signal_solid, facts, ctx)
        result["signal_effective"] = eff
        result["signal_gate_reason"] = reason

        fp = build_run_fingerprint(
            ctx_target=str(getattr(ctx, "target_entity", "") or ""),
            banned_names=(getattr(ctx, "banned_program_names", None) or []),
            run_id=rid,
            analysis_context_id=ctx.analysis_context_id,
            diag_rows=diag_rows,
            chosen_entity=registry_entity or ctx.target_entity,
            choice_reason=choice_reason,
            candidate_entities=candidate_entities,
            now=now,
        )
        # B.1.3.8 — le fingerprint devient LISIBLE par les writers (le conflit
        # d'override doit s'afficher au CR, pas seulement au CSV).
        try:
            result["run_fingerprint"] = fp.to_dict()
        except Exception:
            pass
        result["fingerprint"] = fp

        # Journal (diagnostics_ia.csv)
        rows: List[Dict[str, Any]] = [ctx.to_journal_row(), fp.to_journal_row()]
        for c in conflicts:
            rows.append(c.to_journal_row())
        if raw_signal_solid and not eff:
            rows.append({
                "role": "financial_signal_gate", "provider": "internal",
                "model": "perimeter_match_b1", "status": "GATED",
                "raw_solid": True, "effective_solid": False,
                "reason": reason,
                "detail": ("fait(s) hors périmètre : montrés mais exclus du "
                           "signal financier (règle B.1)"),
            })
        result["journal_rows"] = rows
        # B.1.3.20 (P0-B) — contexte exposé pour la ré-annotation périmètre
        # des faits promus APRÈS la couche B.1 (ledger consolidé, engine).
        result["context"] = ctx
        # ── B.1.2 — témoin de preuve : posé UNIQUEMENT ici, en toute fin du
        # chemin réussi. Tout échec antérieur laisse proof_applied=False et
        # signal_effective=False (défauts fail-safe).
        result["proof_applied"] = True
    except Exception as e:
        # Échec INTERNE de la couche de preuve : la certification tombe,
        # explicitement — jamais de brut re-servi comme effectif (B.1.2 P0).
        result["proof_applied"] = False
        result["proof_error"] = f"{type(e).__name__}: {str(e)[:200]}"
        result["signal_effective"] = False
        result["signal_gate_reason"] = "proof_layer_error"
        result["journal_rows"] = [{
            "role": "proof_layer_b1", "provider": "internal",
            "model": "proof_layer_b1", "status": "ERROR",
            "summary": ("⚠️ Couche de preuve B.1 en ERREUR interne — signal "
                        "financier NON certifié (effectif=False). "
                        + result["proof_error"]),
        }]
    return result
