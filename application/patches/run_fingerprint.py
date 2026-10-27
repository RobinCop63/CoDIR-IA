"""
patches/run_fingerprint.py — v17.4.0-M6B-B1.0 (M6-B · B.1 · E6)

RUN-FINGERPRINT — rendre la VARIABILITÉ visible (note M6-B v3 §14.1 &
Partie II §9).

Non-but reformulé (acté) : M6-B ne stabilise PAS l'enrichissement
(résolution d'entité variable d'un run à l'autre) — il rend cette
variabilité VISIBLE et TRAÇABLE. ~70 % existe déjà dans diagnostics_ia.csv
(raison de quarantaine, pappers_resolution, gleif_resolution,
cache/timing) : B.1 le STRUCTURE, il ne le construit pas.

But : qu'un même brief relancé avec une résolution différente laisse une
TRACE COMPARABLE — jamais un changement de vérité silencieux.

    run_fingerprint
      run_id · analysis_context_id · retrieved_at
      candidate_entities : [ ... ]        # entités vues
      chosen_entity + choice_reason
      quarantine : [ {candidate, reason} ]
      sources_called : [ pappers | gleif | web | ch | sec | none ]
      cache : { hit, miss }

100 % déterministe, sans dépendance pipeline → testable en isolation.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import re
from typing import Any, Dict, Iterable, List, Optional

_SOURCE_ROLE_HINTS = {
    "pappers": "pappers",
    "gleif": "gleif",
    "companies_house": "ch",
    "ch_": "ch",
    "sec_edgar": "sec",
    "web_search": "web",
    "web_research": "web",
    "opensanctions": "opensanctions",
}


@dataclass
class RunFingerprint:
    run_id: str = ""
    analysis_context_id: str = ""
    retrieved_at: str = ""
    candidate_entities: List[str] = field(default_factory=list)
    chosen_entity: str = ""
    override_conflict: str = ""  # B.1.3.5 — USER_CONFIRMED ≠ cible d'analyse
    choice_reason: str = ""
    quarantine: List[Dict[str, str]] = field(default_factory=list)
    sources_called: List[str] = field(default_factory=list)
    cache: Dict[str, int] = field(default_factory=lambda: {"hit": 0, "miss": 0})

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_journal_row(self) -> Dict[str, Any]:
        """Une ligne diagnostics_ia.csv, comparable entre deux runs."""
        return {
            "role": "run_fingerprint",
            "provider": "internal",
            "model": "run_fingerprint_b1",
            "status": "OK",
            "run_id": self.run_id,
            "analysis_context_id": self.analysis_context_id,
            "retrieved_at": self.retrieved_at,
            "candidate_entities": " | ".join(self.candidate_entities),
            "chosen_entity": self.chosen_entity,
            "override_conflict": self.override_conflict,
            "choice_reason": self.choice_reason,
            "quarantine": " | ".join(
                f"{q.get('candidate','?')}:{q.get('reason','?')}"
                for q in self.quarantine),
            "sources_called": " | ".join(self.sources_called),
            "cache_hit": self.cache.get("hit", 0),
            "cache_miss": self.cache.get("miss", 0),
        }


def _diag_get(row: Dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = row.get(k)
        if v:
            return str(v)
    return ""


def build_run_fingerprint(
    *,
    run_id: str,
    analysis_context_id: str,
    diag_rows: Optional[Iterable[Dict[str, Any]]] = None,
    chosen_entity: str = "",
    choice_reason: str = "",
    candidate_entities: Optional[List[str]] = None,
    now: Optional[datetime] = None,

    ctx_target: str = "",
    banned_names=None,
) -> RunFingerprint:
    """
    Structure le fingerprint depuis les lignes diagnostics existantes
    (le ~70 % déjà logué) + les infos de résolution passées par le moteur.
    Tolère diag_rows=None et des lignes hétérogènes — jamais d'exception.
    """
    fp = RunFingerprint(
        run_id=run_id,
        analysis_context_id=analysis_context_id,
        retrieved_at=(now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        chosen_entity=(chosen_entity or "").strip(),
        choice_reason=(choice_reason or "").strip(),
        candidate_entities=list(dict.fromkeys(
            e.strip() for e in (candidate_entities or []) if e and e.strip())),
    )

    sources: List[str] = []
    for row in diag_rows or []:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role", "")).lower()

        # sources appelées
        for hint, name in _SOURCE_ROLE_HINTS.items():
            if hint in role and name not in sources:
                status = str(row.get("status", "")).upper()
                if status and status not in ("SKIP", "SKIPPED", "DISABLED"):
                    sources.append(name)

        # candidats / choix de résolution (pappers_resolution & co)
        if "resolution" in role or "entity" in role:
            cand = _diag_get(row, "candidates", "candidate_entities", "candidats")
            if cand:
                for c in str(cand).replace(";", "|").split("|"):
                    c = c.strip()
                    if c and c not in fp.candidate_entities:
                        fp.candidate_entities.append(c)
            chosen = _diag_get(row, "chosen", "chosen_entity", "resolved_name",
                               "entity", "target")
            if chosen and not fp.chosen_entity:
                fp.chosen_entity = chosen
            reason = _diag_get(row, "reason", "choice_reason", "resolution_path",
                               "path")
            if reason and not fp.choice_reason:
                fp.choice_reason = reason

        # quarantaine
        if "quarantine" in role or "quarantaine" in role \
                or _diag_get(row, "quarantine_reason"):
            _q_cand = _diag_get(row, "candidate", "entity", "name")
            _q_reason = _diag_get(row, "quarantine_reason", "reason")
            if not _q_cand or not _q_reason:
                # B.1.3 (run dossier industriel (composants) : quarantine="?:?") — les lignes réelles
                # registry_quarantine portent tout dans `error` :
                # "candidate='<AUTRE SOCIÉTÉ>' vs analysis='<GROUPE>' — raison".
                _err = str(_diag_get(row, "error", "summary") or "")
                m_c = re.search(r"candidate='([^']+)'", _err)
                if m_c and not _q_cand:
                    _q_cand = m_c.group(1)
                if "—" in _err and not _q_reason:
                    _q_reason = _err.split("—", 1)[1].strip()
                elif _err and not _q_reason:
                    _q_reason = _err[:120]
            fp.quarantine.append({
                "candidate": _q_cand or "?",
                "reason": _q_reason or "?",
            })

        # cache
        cache_field = str(_diag_get(row, "cache", "cache_status")).lower()
        if cache_field == "hit" or row.get("cache_hit") is True:
            fp.cache["hit"] = fp.cache.get("hit", 0) + 1
        elif cache_field == "miss" or row.get("cache_miss") is True:
            fp.cache["miss"] = fp.cache.get("miss", 0) + 1

    fp.sources_called = sources or ["none"]
    # ── B.1.3.5 (audit dossier industriel (composants) P1) — COHÉRENCE INTERNE du fingerprint :
    # on a vu candidate='<GROUPE> HYDRAULICS — gleif:retenu' avec
    # chosen='HEVO' (candidat de SONDE, pas la résolution). Règles :
    #  1. un nom BANNI (programme déclaré au brief) n'est jamais chosen ;
    #  2. chosen vide/banni/sans token commun avec un « :retenu » ⇒ le
    #     premier retenu devient chosen (reason=RESOLVED_<source>) ;
    #  3. USER_CONFIRMED ≠ cible d'analyse ⇒ conflit d'override tracé.
    _banned = {str(b).upper() for b in (banned_names or [])}
    _retenus = []
    for _c in fp.candidate_entities:
        if ":retenu" in _c:
            _nm = _c.split(" — ")[0].strip()
            _tag = _c.split(" — ", 1)[1].split(":", 1)[0].strip() if " — " in _c else "registry"
            _retenus.append((_nm, _tag))
    def _tok135(s):
        return {t for t in re.split(r"[^A-Za-z0-9]+", (s or "").upper()) if len(t) >= 3}
    _ch = (fp.chosen_entity or "").strip()
    _bad = (not _ch or _ch.upper() in _banned
            or (_retenus and not any(_tok135(_ch) & _tok135(nm) for nm, _ in _retenus)))
    # B.1.3.6 — plusieurs retenus en désaccord (pappers LIMITED vs ch/gleif
    # GROUP PLC) : le retenu au MEILLEUR recouvrement de tokens avec la
    # cible d'analyse gagne (déterministe, sans hiérarchie codée en dur).
    if ctx_target and len(_retenus) > 1:
        _retenus.sort(key=lambda nc: -len(_tok135(nc[0]) & _tok135(ctx_target)))
    # B.1.3.10 (run 5 : chosen=LIMITED alors que ch:retenu=GROUP PLC) — le
    # tri best-overlap ne s'appliquait que si chosen était INVALIDE ; quand
    # le clic matche un retenu FAIBLE pendant qu'un retenu STRICTEMENT
    # meilleur existe (overlap cible 3 vs 1), le meilleur gagne. Le clic
    # reste tracé (USER_CONFIRMED dans la raison + override_conflict).
    if (not _bad) and ctx_target and len(_retenus) > 1 and _ch:
        _best_nm, _best_tag = _retenus[0]
        if (len(_tok135(_best_nm) & _tok135(ctx_target))
                > len(_tok135(_ch) & _tok135(ctx_target))):
            _old_ch = _ch
            fp.chosen_entity = _best_nm
            fp.choice_reason = (f"RESOLVED_{(_best_tag or 'registry').upper()} "
                                f"(user-confirmed « {_old_ch} » kept as "
                                f"related candidate)")
    if _bad and _retenus:
        _old = _ch
        fp.chosen_entity, _tag = _retenus[0]
        fp.choice_reason = ("RESOLVED_" + (_tag or "registry").upper()
                            + ((" (candidat sonde « " + _old + " » écarté"
                                + (" — nom de programme banni)" if _old.upper() in _banned else ")"))
                               if _old else ""))
    # B.1.3.8 (audit #2) — la garde par INTERSECTION laissait le conflit muet
    # sur token partagé (« dossier anglophone coté Limited » vs « dossier anglophone coté Group plc ») ; on
    # passe en INÉGALITÉ D'ENSEMBLES : un clic sur une entité LIÉE mais
    # différente de la cible du brief produit un conflit VISIBLE.
    if (str(fp.choice_reason or "").upper().startswith("USER_CONFIRMED")
            and ctx_target
            and _tok135(fp.chosen_entity) != _tok135(ctx_target)):
        fp.override_conflict = (
            "⚠ Override utilisateur : « " + fp.chosen_entity + " » (clic widget)"
            + " · Conflit avec la cible du brief : « " + ctx_target + " »"
            + " · Conséquence : métadonnées registre = entité LIÉE, non cible, "
            + "non probantes pour le périmètre analysé.")
    return fp
