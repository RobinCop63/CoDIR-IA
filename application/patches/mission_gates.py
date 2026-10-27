"""
CoDIR-IA — mission_gates v1.0  (v17.1)

Point d'entrée UNIQUE des gardes mission, appelé une fois par run_codir_session
après le calcul du score. Fail-open par construction (toute exception ⇒ run
inchangé). Orchestre :

  - P0-03 LegalAlertGate  : scrub du vocabulaire juridique fort non étayé.
  - P0-04 (détection)     : multi-SIREN + intention comparative → couverture du
                            brief ; flag REQUESTED_DELIVERABLE_MISSING si une
                            demande explicite n'est pas exécutée (no silent drop).
  - P0-02 (signalement)   : si une alerte juridique forte est scrubée faute de
                            périmètre social, on lève HARD_METRIC_SCOPE_CONFLICT.
  - P0-05 MissionRiskGate : plafonnement du grade selon les flags collectés.

Le module est volontairement défensif : il lit des structures hétérogènes
(dicts agents {output:...}) sans présumer leur forme exacte.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

try:
    from patches.legal_alert_gate import (
        evaluate_legal_alert, scrub_unauthorized_legal_language,
    )
except Exception:  # pragma: no cover - fail-open
    evaluate_legal_alert = None  # type: ignore
    scrub_unauthorized_legal_language = None  # type: ignore

try:
    from patches.mission_risk_gate import apply_mission_risk_gate
except Exception:  # pragma: no cover - fail-open
    apply_mission_risk_gate = None  # type: ignore


_SIREN_RX = re.compile(r"\b(\d{3}\s?\d{3}\s?\d{3})\b")
_COMPARISON_RX = re.compile(
    r"comparatif|comparaison|comparer|\bvs\b|versus|concurrent|benchmark",
    flags=re.IGNORECASE,
)


def extract_sirens(brief: str) -> list[str]:
    """SIREN normalisés (9 chiffres, sans espaces), ordre d'apparition, dédupliqués."""
    out: list[str] = []
    for m in _SIREN_RX.finditer(brief or ""):
        s = re.sub(r"\s", "", m.group(1))
        if len(s) == 9 and s not in out:
            out.append(s)
    return out


def detect_comparison_intent(brief: str) -> bool:
    return bool(_COMPARISON_RX.search(brief or ""))


def _agent_text(res: Any) -> str:
    if isinstance(res, dict):
        return str(res.get("output", "") or "")
    return str(res or "")


def _set_agent_text(res: Any, text: str) -> None:
    if isinstance(res, dict):
        res["output"] = text




_MATERIAL_LEGAL_CLAIM_RX = re.compile(
    r"capitaux?\s+propres?\s+n[ée]gatifs?|L\.?\s*225[-–— ]?248|"
    r"augmentation\s+(?:du\s+)?capital|r[ée]duction\s+(?:du\s+)?capital|"
    r"dissolution|liquidation|cessation\s+des\s+paiements|"
    r"responsabilit[ée]\s+(?:p[ée]nale|civile)|infraction|contentieux|"
    r"mise\s+en\s+demeure|faillite|bankruptcy|insolvency", re.I)


def _material_legal_claim_present(agent_outputs: dict) -> bool:
    text = "\n".join(_agent_text(v) for v in (agent_outputs or {}).values())
    return bool(_MATERIAL_LEGAL_CLAIM_RX.search(text))
def assess_and_scrub_legal(agent_outputs: dict, legal_evidence: dict | None) -> tuple[int, bool]:
    """Scrub le vocabulaire juridique fort dans toutes les sorties agents si le
    gate L.225-248 n'est pas satisfait. Retourne (n_scrubs, gate_passed)."""
    if scrub_unauthorized_legal_language is None or evaluate_legal_alert is None:
        return 0, True
    gate = evaluate_legal_alert("L225-248", legal_evidence or {})
    gate_passed = bool(gate.get("emit"))
    n = 0
    if not gate_passed:
        for res in agent_outputs.values():
            txt = _agent_text(res)
            if not txt:
                continue
            cleaned, removed = scrub_unauthorized_legal_language(txt, gate_passed=False)
            if removed:
                _set_agent_text(res, cleaned)
                n += len(removed)
    return n, gate_passed


def _comparison_proof(full_text: str, sirens: list[str],
                      entity_names: Iterable[str] | None) -> tuple[bool, dict]:
    """Preuve qu'un comparatif a RÉELLEMENT été produit (pas juste 2 SIREN résolus).
    Exige : ≥2 entités identifiées + ≥3 métriques comparées + bloc comparatif explicite."""
    low = (full_text or "").lower()
    compact = re.sub(r"\s", "", full_text or "")
    n_by_siren = sum(1 for s in sirens if s in compact)
    names = {n.lower() for n in (entity_names or []) if n and n.lower() in low}
    n_entities = max(n_by_siren, len(names))

    metric_patterns = (
        r"chiffre d'affaires", r"chiffre d’affaires", r"\bca\b", r"\bca[,:]",
        r"r[ée]sultat", r"\bebitda\b", r"tr[ée]sorerie", r"\bdette",
        r"effectif", r"\bmarge", r"capitaux propres", r"b[ée]n[ée]fice")
    n_metrics = sum(1 for pat in metric_patterns if re.search(pat, low))
    has_block = bool(re.search(r"comparatif|tableau\s+comparatif|face\s+à|versus|\bvs\b|\|.*\|",
                               low))
    ok = (n_entities >= 2 and n_metrics >= 3 and has_block)
    return ok, {"entities_in_output": n_entities, "metrics_compared": n_metrics,
                "explicit_block": has_block}


def build_coverage(brief: str, agent_outputs: dict,
                   primary_resolved_sirens: Iterable[str],
                   entity_names: Iterable[str] | None = None,
                   engine_comparison: bool = False,
                   analysis_mode: str | None = None) -> dict:
    """Matrice de couverture du brief avec PREUVE MOTEUR du comparatif (A4.2).

    `DONE` exige désormais que le MOTEUR ait produit un bloc comparatif
    déterministe (`engine_comparison=True`) ET ≥2 entités résolues à la source.
    Une preuve seulement textuelle (LLM) ou seulement sourcée → `PARTIAL`.
    """
    sirens = extract_sirens(brief)
    # v62.13.9.4.36 — UN SECOND SIREN N'EST PAS UNE DEMANDE DE COMPARATIF. Run réel
    # du 17/09/2026 (dossier réseau de soins) : le brief disait « Mode : mono-entité,
    # périmètre social » et citait les comptes d'une filiale comme PIÈCE du périmètre
    # documentaire. Le gate en a déduit un comparatif inter-sociétés, l'a jugé PARTIEL
    # faute d'entités résolues, a levé REQUESTED_DELIVERABLE_MISSING et plafonné le
    # dossier à 45/100 — NON MISSION-GRADE pour une exigence que le brief ne formulait
    # pas. Un comparatif se demande, il ne se déduit pas d'un décompte de SIREN.
    # le MODE effectif du run prime sur le texte : les réglages (mono-entité,
    # périmètre social) ne figurent pas dans le corps du brief transmis au gate.
    _mono = str(analysis_mode or "").strip().lower() in ("mono", "mono_entite", "mono-entite", "mono-entité", "single", "single_entity")
    if not analysis_mode:
        _mono = bool(re.search(r"(?i)mode\s*[:=]?\s*mono[- ]?entit|single[- ]entity\s*mode", str(brief or "")))
    _asks = bool(re.search(r"(?i)comparatif|comparaison|comparer|benchmark(?:ing)?\s+interne"
                           r"|compare\s+(?:the\s+)?(?:two|both)|inter[- ]soci[ée]t[ée]s", str(brief or "")))
    # v62.13.9.4.38 — « UN COMPARATIF SE DEMANDE, IL NE SE DÉDUIT PAS » (Robin, 18/09) :
    # sur le run réel du 19/09/2026, le contexte inféré était « groupe » (le brief cite
    # la maison-mère) et le repli « not _mono » a de nouveau déduit un comparatif de
    # deux SIREN, levé une réserve de sourçage et, combinée à une contradiction interne,
    # plafonné le dossier à 45/100. Le seul critère est désormais la DEMANDE explicite.
    wants_comparison = len(sirens) >= 2 and _asks
    resolved = {re.sub(r"\s", "", s) for s in (primary_resolved_sirens or [])}
    unresolved = [s for s in sirens if s not in resolved]

    full_text = "\n".join(_agent_text(r) for r in agent_outputs.values())
    proof_ok, proof = _comparison_proof(full_text, sirens, entity_names)
    source_backed = len(resolved) >= 2
    comparison_executed = bool(engine_comparison and source_backed)

    requirements = []
    if wants_comparison:
        if engine_comparison and source_backed:
            status, reason = "DONE", (
                f"Comparatif DÉTERMINISTE produit par le moteur + {len(resolved)} "
                f"entités résolues à la source.")
        elif source_backed and proof_ok:
            status, reason = "PARTIAL", (
                "Comparatif sourcé et présent dans le texte, mais bloc moteur "
                "déterministe absent (preuve LLM ≠ preuve moteur).")
        elif source_backed and not proof_ok:
            status, reason = "PARTIAL", (
                f"Entités résolues ({sorted(resolved)}) mais comparatif non "
                f"matérialisé (ni bloc moteur, ni preuve texte : {proof}).")
        elif proof_ok and not source_backed:
            status, reason = "PARTIAL", (
                "Comparatif dans le TEXTE mais NON SOURCÉ : entités non résolues "
                f"({unresolved or sirens}).")
        elif proof["entities_in_output"] >= 2 or proof["metrics_compared"] >= 1:
            status, reason = "PARTIAL", (
                f"Comparatif amorcé mais ni moteur ni sourcé. Constaté : {proof}, "
                f"résolus : {sorted(resolved)}.")
        else:
            status, reason = "FAILED", (
                f"Comparatif non exécuté. Entité(s) non comparée(s) : {unresolved or sirens}.")
        requirements.append({
            "requirement": "Comparatif inter-sociétés demandé",
            "sirens": sirens, "resolved_sirens": sorted(resolved),
            "engine_comparison": bool(engine_comparison),
            "status": status, "reason": reason, "proof": proof,
        })

    return {
        "sirens_detected": sirens,
        "comparison_requested": wants_comparison,
        "comparison_executed": comparison_executed,
        "comparison_proof": proof,
        "unresolved_sirens": unresolved,
        "requirements": requirements,
        "has_failed_requirement": any(r["status"] == "FAILED" for r in requirements),
        "has_partial_requirement": any(r["status"] == "PARTIAL" for r in requirements),
    }


def build_legal_evidence_from_facts(facts: Any) -> dict:
    """Construit un dossier de preuve juridique depuis la table de faits, au lieu
    d'un dict vide codé en dur. Permet à une alerte L.225-248 LÉGITIME de passer
    quand les éléments existent vraiment (capitaux propres sociaux + capital
    social sourcés), tout en restant conservateur par défaut.

    Un fait n'est retenu comme 'FAIT' que s'il est solide (is_solid) ; les
    capitaux propres ne sont versés comme sociaux que si scope == SOCIAL_STANDALONE.
    """
    ev: dict = {}
    for f in facts or []:
        label = (getattr(f, "label", "") or "").lower()
        scope = getattr(f, "scope", None)
        value = getattr(f, "value", None)
        try:
            solid = bool(getattr(f, "is_solid", lambda: False)())
        except Exception:
            solid = False
        tag = "FAIT" if solid else "INCERTAIN"
        source = getattr(f, "source_doc", None)
        if "capitaux propres" in label and scope == "SOCIAL_STANDALONE":
            ev["capitaux_propres_sociaux"] = {"value": value, "tag": tag,
                                              "scope": scope, "source_ref": source}
        if "capital social" in label:
            ev["capital_social"] = {"value": value, "tag": tag, "source_ref": source}
        if "forme juridique" in label or "legal form" in label:
            ev["legal_form"] = value
    return ev


_SCOPE_MATH_RX = re.compile(
    r"(capitaux\s+propres|fonds\s+propres|equity)[^.\n]{0,40}?"
    r"[=:][^.\n]{0,40}?[-−–][^.\n]{0,40}",
    flags=re.IGNORECASE,
)
_SCOPE_MATH_REPLACEMENT = (
    "[CALCUL NON PUBLIABLE — les capitaux propres ne se déduisent pas par "
    "soustraction narrative ; périmètres potentiellement incompatibles "
    "(ScopeMathValidator)]"
)


def _apply_text_scrub(agent_outputs: dict, scrub_fn) -> tuple[int, list]:
    """v17.1-B2 — applique une fonction de scrub texte (txt)->(new_txt, n, samples)
    à toutes les sorties agents, en mutant in place. Retourne (total, samples)."""
    total = 0
    all_samples: list = []
    for res in agent_outputs.values():
        txt = _agent_text(res)
        if not txt:
            continue
        try:
            new, n, samples = scrub_fn(txt)
        except Exception:
            continue
        if n > 0 and new != txt:
            total += n
            all_samples.extend(samples or [])
            _set_agent_text(res, new)
    return total, all_samples


def scan_and_neutralize_scope_math(agent_outputs: dict) -> int:
    """Passe regex ciblée (A3) : neutralise tout calcul narratif du type
    « capitaux propres = X − Y » dans les sorties agents — c'est exactement la
    faute Lhyfe (déduire des CP par soustraction, souvent inter-périmètres).
    Branche concrètement l'esprit de ScopeMathValidator dans le pipeline.
    Retourne le nombre de neutralisations."""
    n = 0
    for res in agent_outputs.values():
        txt = _agent_text(res)
        if not txt:
            continue
        new = _SCOPE_MATH_RX.sub(_SCOPE_MATH_REPLACEMENT, txt)
        if new != txt:
            n += len(_SCOPE_MATH_RX.findall(txt))
            _set_agent_text(res, new)
    return n


def build_coverage_markdown(coverage: dict) -> str:
    """Section « Couverture du brief » lisible (DOCX/PPTX/CR)."""
    reqs = coverage.get("requirements", [])
    lines = ["## Couverture du brief", ""]
    if not reqs:
        lines.append("- Aucune exigence multi-entités détectée dans le brief.")
    else:
        _icon = {"DONE": "✅", "PARTIAL": "🟠", "FAILED": "❌"}
        for r in reqs:
            lines.append(f"- {_icon.get(r['status'], '•')} **{r['requirement']}** : "
                         f"{r['status']} — {r['reason']}")
    return "\n".join(lines)


def build_comparison_block(entities: list[dict], lang: str = "fr") -> str:
    """A4-04 — Bloc comparatif minimal inter-sociétés à partir d'entités résolues.

    Chaque entité : {siren, name, market, ca, net_income, effectif, tresorerie,
    source}. Produit un tableau markdown + une note de limites. Ne fabrique aucun
    chiffre : les champs absents sont rendus « n/d ».
    """
    if not entities or len(entities) < 2:
        return ""
    cols = [("name", "Société"), ("siren", "SIREN"), ("scope", "Périmètre"),
            ("exercice", "Exercice"), ("ca", "CA"), ("net_income", "Résultat net"),
            ("effectif", "Effectif"), ("tresorerie", "Trésorerie"),
            ("source", "Source")]
    lines = ["## Comparatif inter-sociétés", "",
             "| " + " | ".join(c[1] for c in cols) + " |",
             "|" + "|".join(["---"] * len(cols)) + "|"]
    for e in entities:
        row = [str(e.get(k, "") or "n/d") for k, _ in cols]
        lines.append("| " + " | ".join(row) + " |")
    lines += ["",
              "_Limites : comparatif sur données disponibles ; périmètres "
              "(social Pappers ≠ consolidé RFA/URD) et exercices à harmoniser ; "
              "toute case « n/d » = donnée non résolue à la source._"]
    return "\n".join(lines)


# Métriques financières considérées pour la richesse du comparatif (A4.3-06).
_COMPARISON_METRIC_FIELDS = ("ca", "net_income", "effectif", "tresorerie")


def comparison_metrics_filled_ratio(entities: list[dict] | None) -> float:
    """Part des cellules métriques réellement renseignées (≠ n/d / vide) dans le
    comparatif. Sert à éviter qu'un tableau majoritairement « n/d » soit traité
    comme pleinement mission-grade (A4.3-06)."""
    ents = entities or []
    if len(ents) < 2:
        return 0.0
    total = len(ents) * len(_COMPARISON_METRIC_FIELDS)
    if not total:
        return 0.0
    filled = 0
    for e in ents:
        for f in _COMPARISON_METRIC_FIELDS:
            v = str(e.get(f, "") or "").strip().lower()
            if v and v not in ("n/d", "nd", "n.d.", "—", "-"):
                filled += 1
    return filled / total


def run_mission_gates(
    *,
    brief: str,
    agent_outputs: dict,
    confidence_result: dict,
    legal_evidence: dict | None = None,
    primary_resolved_sirens: Iterable[str] | None = None,
    entity_names: Iterable[str] | None = None,
    engine_comparison: bool = False,
    comparison_sparse: bool = False,
    run_date: str | None = None,
    current_financial_state_established: bool | None = None,
    analysis_mode: str | None = None,
) -> dict:
    """Exécute toutes les gardes mission et retourne un rapport + le score coiffé.

    Mutation : scrub des sorties agents in place (agent_outputs).
    """
    risk_flags: set[str] = set()

    # P0-03 (scrub juridique). v62.6 distingue une vraie assertion juridique
    # matérielle d'un simple résidu lexical de l'agent. Le résidu est nettoyé
    # silencieusement ; il ne crée plus une « alerte critique » vide dans une
    # étude de marché.
    try:
        _material_legal_before = _material_legal_claim_present(agent_outputs)
        n_scrub, gate_passed = assess_and_scrub_legal(agent_outputs, legal_evidence)
        if n_scrub > 0 and _material_legal_before:
            risk_flags.add("CRITICAL_FALSE_LEGAL_ALERT")
    except Exception:
        n_scrub = 0

    # P0-02 (ScopeMathValidator branché : passe regex sur les claims agents)
    try:
        n_scope = scan_and_neutralize_scope_math(agent_outputs)
        if n_scope > 0:
            risk_flags.add("HARD_METRIC_SCOPE_CONFLICT")
    except Exception:
        n_scope = 0

    # B-06 — Temporal gate : « depuis <date future> » → formulation prudente.
    n_temporal = 0
    try:
        from patches.temporal_gate import neutralize_future_as_past as _tg
        n_temporal, _ = _apply_text_scrub(
            agent_outputs, lambda t: _tg(t, run_date))
    except Exception:
        n_temporal = 0

    # B-05 — Listing gate : « non cotée » non sourcée → « à vérifier ».
    n_listing = 0
    try:
        from patches.listing_gate import scrub_unverified_listing_claims as _lg
        n_listing, _ = _apply_text_scrub(agent_outputs, _lg)
    except Exception:
        n_listing = 0

    # F.6.7-04 — Gate anti-contradiction (même entité/métrique avec valeurs
    # incompatibles ; « aucune pièce » vs N pièces jointes). On DÉTECTE, on ne
    # corrige pas en silence : un Comité d'audit doit voir le conflit.
    contradictions = {"financial": [], "document": [], "n_total": 0}
    try:
        from patches.contradiction_gate import run_contradiction_gate as _rcg
        _combined = "\n\n".join(_agent_text(r) or "" for r in agent_outputs.values())
        contradictions = _rcg(_combined, entities=list(entity_names) if entity_names else None)
        if contradictions.get("n_total", 0) > 0:
            risk_flags.add("INTERNAL_CONTRADICTION")
    except Exception:
        contradictions = {"financial": [], "document": [], "n_total": 0}

    # P0-04 couverture du brief (preuve MOTEUR du comparatif en A4.2)
    try:
        coverage = build_coverage(brief, agent_outputs, primary_resolved_sirens or [],
                                  entity_names=entity_names,
                                  engine_comparison=engine_comparison,
                                  analysis_mode=analysis_mode)
        # v62.13.9.4.36 — « exécuté mais non sourcé » est une RÉSERVE DE SOURÇAGE, pas
        # un livrable absent : seul un requis réellement non exécuté porte le drapeau
        # « demande explicite non exécutée » et son plafond de score.
        if coverage.get("has_failed_requirement"):
            risk_flags.add("REQUESTED_DELIVERABLE_MISSING")
        elif coverage.get("has_partial_requirement"):
            risk_flags.add("REQUESTED_DELIVERABLE_UNSOURCED")
    except Exception:
        coverage = {"requirements": [], "has_failed_requirement": False, "sirens_detected": []}

    # P0-05 plafonnement
    confidence = confidence_result
    try:
        if apply_mission_risk_gate is not None and risk_flags:
            confidence = apply_mission_risk_gate(confidence_result, sorted(risk_flags))
    except Exception:
        confidence = confidence_result

    # D-01 minimal — statut mission
    grade = (confidence or {}).get("grade", "?")
    if risk_flags:
        mission_status = "NON MISSION-GRADE" if len(risk_flags) >= 2 else "MISSION-GRADE AVEC RÉSERVES"
    elif grade in ("A", "B"):
        mission_status = "MISSION-GRADE"
    else:
        mission_status = "MISSION-GRADE AVEC RÉSERVES"

    # v62.12.1 (ChatGPT §7) — le gate mission ne peut pas contredire le gate
    # de vérité financière : position courante NON établie ⇒ jamais
    # « MISSION-GRADE » plein.
    if current_financial_state_established is False and mission_status == "MISSION-GRADE":
        mission_status = "MISSION-GRADE AVEC RÉSERVES"

    # A4.3-06 — un comparatif produit mais majoritairement « n/d » ne peut pas
    # être « MISSION-GRADE » plein : il passe AVEC RÉSERVES.
    if comparison_sparse and mission_status == "MISSION-GRADE":
        mission_status = "MISSION-GRADE AVEC RÉSERVES"

    return {
        "risk_flags": sorted(risk_flags),
        "coverage": coverage,
        "coverage_markdown": build_coverage_markdown(coverage),
        "legal_scrubs": n_scrub,
        "scope_math_neutralized": n_scope,
        "temporal_scrubs": n_temporal,
        "listing_scrubs": n_listing,
        "contradictions": contradictions,
        "confidence": confidence,
        "mission_status": mission_status,
    }




# ── B.1.3.56 (scope B) — verdict mission visible dans le livrable ─────────────
# « Jamais un verdict dur uniquement dans le CSV » : le statut et ses raisons
# doivent apparaître en tête du CR (et être repris par le deck). Libellés
# alignés sur mission_risk_gate pour une source de vérité unique.

_FLAG_LABELS = {
    "fr": {
        "HARD_METRIC_SCOPE_CONFLICT": (
            "Conflit dur de métrique/périmètre — une même métrique est portée "
            "sur des périmètres ou des valeurs incompatibles"),
        "INTERNAL_CONTRADICTION": (
            "Contradiction interne détectée entre sections du dossier"),
        "REQUESTED_DELIVERABLE_MISSING": (
            "Livrable demandé dans le brief non exécuté par le moteur"),
        "CRITICAL_FALSE_LEGAL_ALERT": (
            "Alerte juridique critique non étayée par les pièces"),
    },
    "en": {
        "HARD_METRIC_SCOPE_CONFLICT": (
            "Hard metric/scope conflict — the same metric is asserted on "
            "incompatible perimeters or values"),
        "INTERNAL_CONTRADICTION": (
            "Internal contradiction detected across the deliverable"),
        "REQUESTED_DELIVERABLE_MISSING": (
            "Deliverable requested in the brief was not executed by the engine"),
        "CRITICAL_FALSE_LEGAL_ALERT": (
            "Critical legal alert not supported by the documents"),
    },
}


_STATUS_LABELS = {
    "en": {
        "MISSION-GRADE": "MISSION-GRADE",
        "MISSION-GRADE AVEC RÉSERVES": "MISSION-GRADE WITH RESERVATIONS",
        "NON MISSION-GRADE": "NON MISSION-GRADE",
        "MISSION_GATE_ERROR": "MISSION GATE ERROR",
    },
    "fr": {
        "MISSION-GRADE": "MISSION-GRADE",
        "MISSION-GRADE AVEC RÉSERVES": "MISSION-GRADE AVEC RÉSERVES",
        "NON MISSION-GRADE": "NON MISSION-GRADE",
        "MISSION_GATE_ERROR": "ERREUR MISSION GATE",
    },
}


def localize_mission_status(status: str, lang: str = "fr") -> str:
    key = str(status or "").strip().upper()
    return _STATUS_LABELS["en" if str(lang or "fr").lower().startswith("en") else "fr"].get(key, str(status or "").strip())


def build_mission_status_markdown(mission_gates_result, lang: str = "fr") -> str:
    """Bandeau Markdown déterministe du statut mission (vide si MISSION-GRADE).

    Injecté en tête du livrable par le moteur ; repris par les renderers.
    """
    mg = mission_gates_result or {}
    status = str(mg.get("mission_status", "") or "").strip()
    if not status or status == "MISSION-GRADE":
        return ""
    en = str(lang or "fr").lower().startswith("en")
    labels = _FLAG_LABELS["en" if en else "fr"]
    flags = [str(f) for f in (mg.get("risk_flags") or [])]
    reasons = [labels.get(f, f) for f in flags]
    hard = status.upper().startswith("NON MISSION-GRADE")
    # v62.8 — une réserve sans cause n'apporte aucune lucidité. Elle n'est pas
    # affichée. Un statut bloquant sans flag est, lui, une erreur moteur
    # explicite et non une pseudo-réserve métier.
    if not reasons and not hard:
        return ""
    if not reasons and hard:
        reasons = [
            "Internal gate inconsistency — review required" if str(lang or "fr").lower().startswith("en")
            else "Incohérence interne des gates — revue requise"
        ]
    icon = "⛔" if hard else "⚠"
    display_status = localize_mission_status(status, lang)
    if en:
        title = f"## {icon} Mission status: {display_status}"
        intro = ("Blocking conflicts raised by the engine gates:" if hard
                 else "Reservations raised by the engine gates:")
        conduct = ("Deliverable restricted to supervised internal use — do not "
                   "certify or circulate as is; resolve the conflicts above "
                   "before any decision." if hard else
                   "Supervised internal use recommended until the "
                   "reservations above are cleared.")
    else:
        title = f"## {icon} Statut mission : {display_status}"
        intro = ("Conflits bloquants détectés par les gates moteur :" if hard
                 else "Réserves détectées par les gates moteur :")
        conduct = ("Livrable à usage interne supervisé — ne pas certifier ni "
                   "diffuser en l'état ; lever les conflits listés ci-dessus "
                   "avant toute décision." if hard else
                   "Usage interne supervisé recommandé tant que les réserves "
                   "ci-dessus ne sont pas levées.")
    lines = [title, "", intro]
    lines += [f"- {r}" for r in reasons]
    lines += ["", conduct]
    return "\n".join(lines)


__all__ = [
    "extract_sirens", "detect_comparison_intent",
    "build_coverage", "build_coverage_markdown", "assess_and_scrub_legal",
    "scan_and_neutralize_scope_math", "run_mission_gates",
    "build_legal_evidence_from_facts", "build_comparison_block",
    "build_mission_status_markdown", "localize_mission_status",
    "comparison_metrics_filled_ratio",
]
