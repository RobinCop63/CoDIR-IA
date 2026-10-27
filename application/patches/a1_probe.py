"""
patches/a1_probe.py — v17.3.0-M6-UI.1

INSTRUMENTATION SEULE. Aucune logique métier, aucun effet sur le run.
Objectif (cadrage ChatGPT) : PROUVER où naît la divergence EN vs FR sur un même
corpus dossier anglophone coté, avant tout correctif A2/A1. On ne corrige plus une divergence
sans avoir d'abord prouvé où elle naît.

Activation : variable d'environnement CODIR_A1_PROBE=1 (sinon no-op total).
Sortie :
  1. une ligne « a1_probe » ajoutée à diag_list → visible dans le CSV diagnostics ;
  2. un sidecar JSON a1_probe_<lang>_<ts>.json dans le dossier de sortie.

Comparaison attendue : faire tourner EN puis FR sur le MÊME corpus, puis comparer
les deux enregistrements. Si attachments_block_hash / financial_statements_block_hash
diffèrent → la divergence naît AVANT le détecteur (input). S'ils sont identiques
mais financial_signal_solid / source_quality diffèrent → bug détecteur/scorer.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, Optional

_PROBE: Dict[str, Any] = {}

# Champs tracés (ordre = ordre de cadrage ChatGPT).
_FIELDS = [
    "lang",
    "run_version",
    "brief_company_name",
    "analysis_entity_candidate",
    "legal_entity_candidate",
    "provided_identifier",
    "provided_identifier_type",
    "resolved_registry",
    "routing_rationale",
    "use_ch",
    "use_pappers",
    "use_gleif",
    "resolved_company_name",
    "ch_company_number",
    "ch_company_status",
    "ch_resolution_path",
    "latest_accounts_date",
    "analysis_as_of_date",
    "run_as_of_date",
    "attachments_block_hash",
    "attachments_block_chars",
    "attachments_block_financial_signal_score",
    "attachments_block_financial_signal_solid",
    "financial_statements_block_hash",
    "financial_statements_block_chars",
    "financial_facts_total",
    "financial_facts_amount",
    "financial_facts_rate",
    "financial_facts_profile",
    "financial_facts_core_present",
    "financial_facts_core_missing",
    "financial_facts_rows_hash",
    "financial_statements_detected",
    "financial_signal_keywords",
    "financial_signal_amounts",
    "company_profile_size",
    "source_quality",
    "grade",
    "facts_table_n_facts_total",
    "facts_table_n_facts_solid",
    "revenue_fact_status",
    "revenue_fact_value",
    "revenue_fact_source",
    "revenue_fact_page",
]


def enabled() -> bool:
    # M6-A1-probe.3 — build DIAGNOSTIC : probe ACTIF PAR DÉFAUT. Désactivable
    # explicitement via CODIR_A1_PROBE=0 (ou false/no/off). Plus aucune variable
    # à poser pour obtenir la ligne a1_probe → fini le piège de propagation d'env.
    return os.getenv("CODIR_A1_PROBE", "1").strip().lower() not in ("0", "false", "no", "off")


def reset() -> None:
    """Réinitialise l'accumulateur en début de run (no-op si désactivé)."""
    if not enabled():
        return
    _PROBE.clear()
    _PROBE["_t0"] = time.time()


def put(**kw: Any) -> None:
    """Enregistre des champs (no-op si désactivé). Tolérant : ignore tout None."""
    if not enabled():
        return
    for k, v in kw.items():
        if v is not None:
            _PROBE[k] = v


def block_stats(text: Optional[str]) -> tuple[str, int]:
    """(hash court, longueur) d'un bloc texte — pour comparer EN vs FR sans
    exposer le contenu intégral."""
    t = text or ""
    h = hashlib.sha256(t.encode("utf-8", "ignore")).hexdigest()[:16]
    return h, len(t)


def put_block(name: str, text: Optional[str]) -> None:
    """Trace hash + longueur d'un bloc (attachments_block, financial_statements_block)."""
    if not enabled():
        return
    h, n = block_stats(text)
    _PROBE[f"{name}_hash"] = h
    _PROBE[f"{name}_chars"] = n


def put_financial_signal(report: Any) -> None:
    """Extrait les champs du FinancialSignalReport (détecteur langue-agnostique)."""
    if not enabled() or report is None:
        return
    _PROBE["attachments_block_financial_signal_score"] = getattr(report, "confidence_score", None)
    _PROBE["attachments_block_financial_signal_solid"] = getattr(report, "financial_signal_solid", None)
    _PROBE["financial_signal_keywords"] = getattr(report, "n_keywords", None)
    _PROBE["financial_signal_amounts"] = getattr(report, "n_amounts", None)


def put_ch(ch_blocks: Any) -> None:
    """Trace la VRAIE résolution Companies House depuis _ch_blocks (resolution_log
    + full block), pas le nom confirmé côté brief. C'est ici qu'on capte
    « dossier anglophone coté Limited / 00162636 » distinct de l'entité d'analyse du brief."""
    if not enabled() or not isinstance(ch_blocks, dict):
        return
    log = ch_blocks.get("resolution_log")
    name = (getattr(log, "primary_name", "") or "") if log is not None else ""
    if name:
        _PROBE["legal_entity_candidate"] = name
        _PROBE["resolved_company_name"] = name
    if log is not None:
        _PROBE["ch_company_number"] = getattr(log, "company_number", "") or None
        _PROBE["ch_company_status"] = getattr(log, "primary_status", "") or None
        _PROBE["ch_resolution_path"] = getattr(log, "path", "") or None
    full = ch_blocks.get("full") or ""
    import re as _re
    m = _re.search(r"(?:accounts|comptes)[^\n]{0,40}?(20\d\d-\d{2}-\d{2})", full, _re.I)
    if m:
        _PROBE["latest_accounts_date"] = m.group(1)


def put_facts(facts, coverage) -> None:
    """M6-B — compteurs de faits + hash des 20 premières lignes (déterminisme)."""
    try:
        import hashlib, json
        cov = coverage or {}
        rows = []
        for f in (facts or [])[:20]:
            d = f.to_dict() if hasattr(f, "to_dict") else dict(f)
            rows.append((d.get("label"), d.get("qualifier"), d.get("metric_kind"),
                         d.get("source_type"), d.get("dimension"), d.get("value_str"),
                         d.get("currency"), d.get("period"), d.get("confidence"),
                         d.get("source_file"), d.get("page")))
        rh = hashlib.sha256(json.dumps(rows, sort_keys=True,
                            ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
        _PROBE["financial_facts_total"] = cov.get("total_facts")
        _PROBE["financial_facts_amount"] = cov.get("amount_facts")
        _PROBE["financial_facts_rate"] = cov.get("rate_facts")
        _PROBE["financial_facts_profile"] = cov.get("profile_facts")
        _PROBE["financial_facts_core_present"] = ",".join(cov.get("core_present") or [])
        _PROBE["financial_facts_core_missing"] = ",".join(cov.get("core_missing") or [])
        _PROBE["financial_facts_rows_hash"] = rh
    except Exception:
        pass


def snapshot() -> Dict[str, Any]:
    if not enabled():
        return {}
    return {k: _PROBE.get(k) for k in _FIELDS}


def flush(diag_list: Optional[list] = None,
          out_dir: Optional[str] = None,
          lang: str = "fr") -> Optional[Dict[str, Any]]:
    """Émet l'enregistrement (ligne diag_list + sidecar JSON). No-op si désactivé."""
    if not enabled():
        return None
    _PROBE.setdefault("lang", lang)
    rec = snapshot()
    # 1) ligne diag_list (→ CSV)
    if diag_list is not None:
        try:
            diag_list.append({
                "role": "a1_probe",
                "provider": "internal",
                "model": "a1_probe_v1",
                "status": "OK",
                "summary": (f"lang={rec.get('lang')} | "
                            f"att_hash={rec.get('attachments_block_hash')} "
                            f"({rec.get('attachments_block_chars')}c) | "
                            f"fs_hash={rec.get('financial_statements_block_hash')} "
                            f"({rec.get('financial_statements_block_chars')}c) | "
                            f"signal_solid={rec.get('attachments_block_financial_signal_solid')} "
                            f"score={rec.get('attachments_block_financial_signal_score')} | "
                            f"size={rec.get('company_profile_size')} | "
                            f"source_quality={rec.get('source_quality')} | "
                            f"analysis_entity={rec.get('analysis_entity_candidate')} | "
                            f"legal_entity={rec.get('legal_entity_candidate')}"),
                "a1_probe": json.dumps(rec, ensure_ascii=False),
            })
        except Exception:
            pass
    # 2) sidecar JSON
    if out_dir:
        try:
            os.makedirs(out_dir, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(out_dir, f"a1_probe_{rec.get('lang', lang)}_{ts}.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(rec, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return rec
