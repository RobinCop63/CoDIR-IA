"""
patches/temporal_frame.py — M6-A3 (modèle temporel : trois dates distinctes)

Défaut mesuré par le probe (run FR dossier anglophone coté) :
    analysis_as_of_date = 2025-03-29   (date d'analyse simulée)
    latest_accounts_date = 2025-03-31  (dernier dépôt Companies House)
    run_as_of_date      = 2026-06-27   (date réelle du run)
Le livrable ancrait tout sur 2025 (« T2 2025 », « T3 2025 ») présenté comme
courant, sans distinguer ces trois dates. Pour un lecteur pressé, c'est trompeur :
il croit lire une analyse actuelle alors que c'est une vue rétrospective.

Ce module ne change pas l'analyse. Il rend le cadre temporel EXPLICITE et honnête :
- run_as_of_date    : quand l'analyse a été produite (réel) ;
- latest_accounts_date : date du dernier dépôt registre (identité, pas analyse) ;
- scenario_date     : date à laquelle l'utilisateur a demandé d'ancrer l'analyse
                      (UNIQUEMENT si explicitement demandé) — « scenario lens ».

Règle cardinale : la date des derniers comptes (registre) ne doit jamais être
présentée comme la date d'analyse. Et une date de scénario passée doit être
signalée comme rétrospective, pas comme l'instant courant.

100 % déterministe, sans dépendance pipeline → testable en isolation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Dict, Any, List

_ISO = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})\s*$")


def _norm_date(s: str) -> str:
    if not s:
        return ""
    m = _ISO.match(str(s))
    return m.group(0).strip() if m else str(s).strip()


def _year(s: str) -> int | None:
    m = _ISO.match(str(s or ""))
    return int(m.group(1)) if m else None


@dataclass
class TemporalFrame:
    run_as_of_date: str = ""          # date réelle du run
    latest_accounts_date: str = ""    # dernier dépôt registre (identité)
    scenario_date: str = ""           # ancrage d'analyse demandé (explicite)
    has_scenario: bool = False
    is_retrospective: bool = False    # scenario_date antérieure au run
    registry_date_is_not_analysis: bool = True   # garde-fou doctrinal (toujours vrai)
    latest_parsed_financial_period: str = ""  # legacy: année/période documentaire détectée
    latest_document_year_detected: str = ""   # v62.12.2 : signal documentaire distinct
    parsed_period_source: str = ""
    parsed_period_note: str = ""
    # v62.12.1 (spec §6) — séparation stricte des trois notions temporelles
    latest_confirmed_critical_period: str = ""   # dernier fait critique page-confirmé
    current_established: bool | None = None      # position courante établie ?
    established_reason: str = ""                 # raison si non établie

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_temporal_frame(run_as_of_date: str = "",
                         latest_accounts_date: str = "",
                         scenario_date: str = "") -> TemporalFrame:
    """Construit le cadre temporel à partir des trois signaux. scenario_date ne
    doit être renseignée QUE si l'utilisateur a explicitement demandé un ancrage
    (sinon vide → pas de « date d'analyse simulée » fabriquée)."""
    tf = TemporalFrame()
    tf.run_as_of_date = _norm_date(run_as_of_date)
    tf.latest_accounts_date = _norm_date(latest_accounts_date)
    tf.scenario_date = _norm_date(scenario_date)
    tf.has_scenario = bool(tf.scenario_date)

    ry, sy = _year(tf.run_as_of_date), _year(tf.scenario_date)
    if tf.has_scenario and ry is not None and sy is not None and sy < ry:
        tf.is_retrospective = True
    elif tf.has_scenario and tf.scenario_date < tf.run_as_of_date and tf.run_as_of_date:
        tf.is_retrospective = True
    return tf


def attach_parsed_financial_period(tf: "TemporalFrame", outputs: Dict[str, Any] | None,
                                   lang: str = "fr") -> "TemporalFrame":
    """Record the latest factual financial period actually used by the agents.

    This does not certify the facts. It only makes the temporal gap explicit:
    registry metadata may point to a newer filing than the period successfully
    parsed into the narrative.
    """
    if tf is None:
        return tf
    texts = []
    for key in ("finance", "strategie", "synthese_decisions", "direction_generale"):
        value = (outputs or {}).get(key) if isinstance(outputs, dict) else None
        if isinstance(value, str):
            texts.append(value)
    blob = "\n".join(texts)
    candidates: list[tuple[int, str]] = []
    for line in blob.splitlines():
        if not re.search(r"\[(?:FACT|FAIT)\]|Source\s*:\s*Annual\s+Report|Annual\s+Reports?", line, re.I):
            continue
        # Mixed lines may contain a verified FY25 baseline followed by an FY27
        # target. When an explicit FACT tag exists, only the text through that
        # tag is eligible; otherwise cut before the first estimate marker.
        _fact_tag = re.search(r"\[(?:FACT|FAIT)\]", line, re.I)
        if _fact_tag:
            factual_segment = line[:_fact_tag.end()]
        else:
            factual_segment = re.split(
                r"\[(?:AI\s*)?ESTIM|\[UNSOURCED\]|\[NON\s+SOURC[ÉE]\]|"
                r"\bestimat(?:e|ed|ion)\b|\bhypoth[èe]se\b|≈",
                line, maxsplit=1, flags=re.I,
            )[0]
        for yy in re.findall(r"\bFY\s*(?:20)?(\d{2})(?:/\d{2})?\b", factual_segment, re.I):
            year = 2000 + int(yy)
            candidates.append((year, f"FY{yy}"))
        for yyyy in re.findall(r"\b(20\d{2})\b", factual_segment):
            candidates.append((int(yyyy), yyyy))
    if candidates:
        year, label = max(candidates, key=lambda x: x[0])
        tf.latest_parsed_financial_period = label
        # A deep-scan document year, when available, is more authoritative than
        # a year reconstructed from agent prose.  Keep the latter only as a
        # fallback for legacy/no-deep-scan sessions.
        if not tf.latest_document_year_detected:
            tf.latest_document_year_detected = label
        tf.parsed_period_source = "agent narrative — factual/source-tagged lines"
        lad_year = _year(tf.latest_accounts_date)
        if lad_year and lad_year > year:
            tf.parsed_period_note = (
                "Registry metadata is newer than the latest financial period actually parsed; the newer filing was not used as financial evidence."
                if str(lang or "fr").lower().startswith("en") else
                "La métadonnée registre est plus récente que la dernière période financière réellement parsée ; le dépôt plus récent n'a pas été utilisé comme preuve financière."
            )
    return tf

def header_lines(tf: "TemporalFrame", lang: str = "fr") -> List[str]:
    """Lignes d'en-tête CR explicites séparant les trois dates."""
    en = (lang or "fr").lower() == "en"
    out: List[str] = []
    if not (tf.run_as_of_date or tf.latest_accounts_date or tf.scenario_date):
        return out

    if en:
        if tf.run_as_of_date:
            out.append(f"Run date: {tf.run_as_of_date}")
        if tf.latest_accounts_date:
            out.append(f"Latest available accounts: {tf.latest_accounts_date} "
                       "(registry filing — identity, not the analysis date)")
        if tf.has_scenario:
            tag = " — retrospective view" if tf.is_retrospective else ""
            out.append(f"Scenario lens: as of {tf.scenario_date}{tag} "
                       "(analysis anchored here at the user's request)")
        _doc_year = (getattr(tf, "latest_document_year_detected", "")
                     or tf.latest_parsed_financial_period)
        if _doc_year:
            out.append(f"Latest document financial year detected/scanned: {_doc_year}")
        if getattr(tf, "latest_confirmed_critical_period", ""):
            out.append("Latest critical page-confirmed period: "
                       f"{tf.latest_confirmed_critical_period}")
        _est = getattr(tf, "current_established", None)
        if _est is not None:
            _line = ("Current financial position established: "
                     + ("yes" if _est else "no"))
            _reason = getattr(tf, "established_reason", "")
            if not _est and _reason:
                _line += f" — {_reason}"
            out.append(_line)
        if tf.parsed_period_note:
            out.append(tf.parsed_period_note)
    else:
        if tf.run_as_of_date:
            out.append(f"Date du run : {tf.run_as_of_date}")
        if tf.latest_accounts_date:
            out.append(f"Derniers comptes disponibles : {tf.latest_accounts_date} "
                       "(dépôt registre — identité, pas la date d'analyse)")
        if tf.has_scenario:
            tag = " — vue rétrospective" if tf.is_retrospective else ""
            out.append(f"Scénario d'analyse : au {tf.scenario_date}{tag} "
                       "(analyse ancrée ici à la demande de l'utilisateur)")
        _doc_year = (getattr(tf, "latest_document_year_detected", "")
                     or tf.latest_parsed_financial_period)
        if _doc_year:
            out.append("Dernier exercice documentaire détecté/scanné : "
                       f"{_doc_year}")
        if getattr(tf, "latest_confirmed_critical_period", ""):
            out.append("Dernière période critique confirmée sur pièce : "
                       f"{tf.latest_confirmed_critical_period}")
        _est = getattr(tf, "current_established", None)
        if _est is not None:
            _line = ("Position financière courante établie : "
                     + ("oui" if _est else "non"))
            _reason = getattr(tf, "established_reason", "")
            if not _est and _reason:
                _line += f" — {_reason}"
            out.append(_line)
        if tf.parsed_period_note:
            out.append(tf.parsed_period_note)
    return out
