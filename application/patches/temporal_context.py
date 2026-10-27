# -*- coding: utf-8 -*-
"""Temporal Core Refactor — contexte temporel UNIQUE du run.

Correctif TCR (audit 26/07/2026) : ce module est la SEULE autorité.
Toutes les sources y sont intégrées — y compris la compatibilité
« revue de clôture » (rétrogradée en candidate confirmable) — et le
moteur consomme TemporalContext.policy sans jamais rappeler le
résolveur.

Priorités contractuelles (contrat contresigné, amendements A1-A5) :
  1. entrée STRUCTURÉE  — settings.analysis_as_of_date (ISO strict) ;
  2. labels CONTRACTUELS A3 (les quatre, seuls décisionnaires) ;
  3. inférence legacy = CANDIDATE confirmable → BLOCKED_AMBIGUOUS,
     jamais une autorité silencieuse ;
  4. rien → LIVE.

Fail-closed JAMAIS masqué : une panne (ERROR), un label illisible
(INVALID) ou un conflit de labels (CONFLICT) BLOQUENT même si une
valeur structurée est présente. Le structuré ne domine que l'absence
d'autorité textuelle (NOT_REQUESTED) et les candidates (AMBIGUOUS) —
c'est le flux de confirmation : candidate adoptée → champ structuré →
nouveau run où le structuré gouverne le même brief.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
import hashlib as _hashlib
from datetime import date, datetime
from typing import Callable, Optional

from patches import mission_governance as _mg
from patches import temporal_policy as _tp

# Correctif TCR — validation calendaire réelle : format YYYY-MM-DD puis
# date.fromisoformat (toute année valide ; 1999-12-31 est une date).
_ISO_FORMAT = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Correctif TCR-v10 (finding P0-01) — SENTINELLE DE PANNE DU PRODUCTEUR.
# `peek_control_input` ne peut plus rendre un texte permissif quand la
# frontière de vérité tombe : il rend CE jeton, et le résolveur — seule
# autorité — le traduit en BLOCKED_ERROR. Un jeton, pas une exception :
# le porteur reste une chaîne, donc TOUT consommateur du peek hérite du
# fail-closed, y compris un consommateur écrit demain qui ignorerait la
# convention. Caractères de contrôle : insaisissable dans un brief.
TEMPORAL_INPUT_FAILURE_SENTINEL = "\x00codir:temporal-control-input-failure\x00"

SOURCE_STRUCTURED = "STRUCTURED"
SOURCE_CONTRACTUAL = "CONTRACTUAL_LABEL"
SOURCE_LEGACY_CANDIDATE = "LEGACY_CANDIDATE"
SOURCE_NONE = "NONE"


class TemporalContextError(RuntimeError):
    """Panne interne de la construction du contexte (jamais silencieuse)."""


@dataclass(frozen=True)
class TemporalContext:
    run_now: datetime
    run_date: str
    structured_date: str
    scenario_status: str
    scenario_value: Optional[str]
    scenario_raw: str
    error_code: str
    conflict: bool
    intent_source: str
    analysis_date: Optional[str]
    policy: _tp.TemporalExecutionPolicy
    # Correctif TCR-v5 — empreinte canonique des ENTRÉES du contexte :
    # permet au moteur de vérifier que l'instance transmise par
    # l'application a été construite sur exactement le même brief et le
    # même champ structuré (contrat « une session = un contexte »).
    brief_sha: str = ""
    # Correctif TCR-v10 (finding P0-03) — empreinte de l'ENTRÉE TEMPORELLE
    # COURANTE (TemporalControlInput.input_fingerprint). Le moteur vérifie
    # que le contexte qu'il consomme a été résolu sur la photographie que
    # l'application lui déclare : l'objet devient l'autorité PROUVÉE de
    # bout en bout, pas seulement l'objet d'origine.
    input_fingerprint: str = ""
    candidate_value: Optional[str] = None
    candidate_raw: str = ""
    candidates: tuple = field(default_factory=tuple)

    @property
    def is_blocked(self) -> bool:
        return self.policy.mode not in (_tp.MODE_LIVE, _tp.MODE_RETRO,
                                        _tp.MODE_FUTURE)

    def authority_fragment(self) -> dict:
        """Forme CANONIQUE du fragment « temporal_authority », cohérente
        par construction avec la policy (candidate incluse, bandeau A5).

        ⚠ Surface de contrat EXTERNE : exercée par l'instrument d'audit
        `REPRO_CHATGPT_TEMPORAL_CORE_REFACTOR.py`, qui vit hors de
        l'arbre. Le moteur compose aujourd'hui son propre fragment dans
        le résultat ; cette méthode reste la référence de forme et NE
        DOIT PAS être retirée sur la seule foi d'un scan interne à
        l'arbre (leçon de la passe de nettoyage v13).
        """
        return {
            "scenario_status": self.scenario_status,
            "scenario_value": self.scenario_value,
            "raw": self.scenario_raw,
            "error_code": self.error_code,
            "conflict": self.conflict,
            "intent_source": self.intent_source,
            "candidate_value": self.candidate_value,
            "candidate_raw": self.candidate_raw,
            # Correctif TCR-v16 (verdict v15, P0-5) — l'empreinte de
            # l'entrée doit atteindre l'interface : sans elle, le bouton
            # « ce n'est pas la date d'analyse » stocke une chaîne vide
            # et ne débloque jamais le même brief.
            "input_fingerprint": self.input_fingerprint,
            "policy": self.policy.to_dict(),
        }


def _validate_structured(structured: str) -> Optional[str]:
    """ISO STRICT (calendaire réel) ou None. Toute autre forme est un
    échec — l'entrée structurée est un contrat machine."""
    sd = (structured or "").strip()
    if not sd:
        return None
    if not _ISO_FORMAT.match(sd):
        raise ValueError(f"structured date malformed: {sd!r}")
    date.fromisoformat(sd)  # 2023-02-30 → ValueError ; 1999-12-31 OK
    return sd


def blocked_error_context(brief, structured_date="", clock=None,
                          reason="application preflight failure",
                          input_fingerprint=""):
    """Correctif TCR-v6 — fabrique un TemporalContext BLOCKED_ERROR
    RÉEL (empreinte comprise) pour les pannes du préflight applicatif :
    l'application transmet TOUJOURS un contexte au moteur, jamais
    None après une panne — le moteur consomme ce contexte fail-closed
    au lieu de recalculer une autorité que le préflight n'a pas su
    produire."""
    now = (clock or datetime.now)()
    rd = now.date().isoformat()
    _bsha = _hashlib.sha256((brief or '').encode('utf-8')).hexdigest()
    pol = _tp.resolve_temporal_policy(rd, None, "ERROR",
                                      "TEMPORAL_AUTHORITY_ERROR")
    return _ctx(now, rd, (structured_date or "").strip(), "ERROR", None,
                str(reason), "TEMPORAL_AUTHORITY_ERROR", False,
                SOURCE_NONE, None, pol, brief_sha=_bsha,
                input_fingerprint=input_fingerprint)


def _ctx(now, rd, structured, st, val, raw, code, conflict, src, ad, pol,
         cand_v=None, cand_r="", cands=(), brief_sha="",
         input_fingerprint=""):
    return TemporalContext(
        brief_sha=brief_sha, input_fingerprint=input_fingerprint,
        run_now=now, run_date=rd, structured_date=structured,
        scenario_status=st, scenario_value=val, scenario_raw=raw,
        error_code=code, conflict=conflict, intent_source=src,
        analysis_date=ad, policy=pol, candidate_value=cand_v,
        candidate_raw=cand_r, candidates=tuple(cands))


from patches.temporal_control_input import (CONTROL_CHANNEL_MARK,
                                            LEGACY_CHANNEL_MARK)


def resolve_temporal_context(brief=None,
                             structured_date: str = "",
                             clock: Optional[Callable[[], datetime]] = None,
                             closing_review_hint: bool = False,
                             input_fingerprint: str = "",
                             temporal_input=None,
                             declined_candidate_fingerprint: str = ""
                             ) -> TemporalContext:
    """Point d'entrée UNIQUE — À DEUX CANAUX depuis le correctif v11.

    Trois formes d'appel, une seule sémantique :

      resolve_temporal_context(temporal_input=tci)      ← typé (préféré)
      resolve_temporal_context(tci)                     ← typé positionnel
      resolve_temporal_context(tci.as_authority_text()) ← sérialisé

    Dans les trois cas la décision est prise CANAL PAR CANAL :

      canal de contrôle  = date structurée + lignes de labels signés
                           → SEULES sources d'une autorité DIRECTE
                             (rang 1 STRUCTURED, rang 2 CONTRACTUAL_LABEL,
                              et leurs états bloquants)
      canal métier/narratif = reste du champ principal + champs
                           secondaires → au mieux une CANDIDATE
                           confirmable (rang 3), JAMAIS une autorité

    Un appel par chaîne nue (sans sérialisation) conserve l'ancien
    comportement mono-canal : compatibilité des appels bibliothèque et
    des instruments d'audit historiques.
    """
    # ── Entrée TYPÉE ou SÉRIALISÉE → décision à deux canaux.
    _tci = temporal_input
    if _tci is None and brief is not None and not isinstance(brief, str):
        _tci = brief
    if _tci is not None:
        _fp = (input_fingerprint
               or getattr(_tci, "input_fingerprint", "") or "")
        if (declined_candidate_fingerprint
                and declined_candidate_fingerprint == _fp):
            # Correctif TCR-v15 (addendum A5) — l'utilisateur a
            # explicitement refusé la candidate POUR CETTE ENTRÉE :
            # rang 3 neutralisé, les rangs 1 et 2 restent souverains.
            return _resolve_two_channel(
                getattr(_tci, "contractual_text", "") or "", "",
                structured_date or getattr(_tci, "structured_date", "") or "",
                clock, closing_review_hint, _fp,
                raw_for_sentinel=getattr(_tci, "raw_main_text", "") or "")
        return _resolve_two_channel(
            getattr(_tci, "contractual_text", "") or "",
            getattr(_tci, "legacy_text", "") or "",
            structured_date or getattr(_tci, "structured_date", "") or "",
            clock, closing_review_hint,
            input_fingerprint or getattr(_tci, "input_fingerprint", "") or "",
            raw_for_sentinel=getattr(_tci, "raw_main_text", "") or "")
    if isinstance(brief, str) and brief.startswith(CONTROL_CHANNEL_MARK):
        head, _, rest = brief.partition("\n")
        contractual, _, legacy = rest.partition(LEGACY_CHANNEL_MARK)
        return _resolve_two_channel(
            contractual.strip("\n"), legacy.lstrip("\n"),
            structured_date, clock, closing_review_hint, input_fingerprint,
            raw_for_sentinel=brief)
    _ctx_single = _resolve_single_channel(brief or "", structured_date,
                                          clock, closing_review_hint,
                                          input_fingerprint)
    if _ctx_single.scenario_status == "NOT_REQUESTED":
        # Même rattrapage structurel sur le chemin mono-canal : un
        # appelant bibliothèque ou le moteur sans contexte hérite de la
        # même protection contre le run live silencieux.
        _late = _detect_natural_intent(brief or "", _ctx_single.run_date)
        if isinstance(_late, tuple):
            return blocked_error_context(
                brief or "", structured_date,
                lambda: _ctx_single.run_now, reason=_late[1],
                input_fingerprint=input_fingerprint)
        if _late is not None:
            return _as_candidate_context(_ctx_single, _late.value,
                                         _late.raw, structured_date,
                                         input_fingerprint)
    return _ctx_single


def _detect_natural_intent(text: str, run_date: str = ""):
    """Correctif TCR-v15 — signal d'intention temporelle NATURELLE.

    Renvoie l'objet du détecteur structurel dès qu'il émet un SIGNAL —
    candidate datée, intention sans date exploitable (AMBIGUOUS) — et
    une sentinelle d'ERREUR si le détecteur tombe.

    FAIL-CLOSED (verdict v14, P0-3) : ce composant est une frontière de
    vérité. Sa panne ne peut pas rendre un run live ; elle devient
    BLOCKED_ERROR, comme toute panne du producteur temporel."""
    try:
        from patches import legacy_temporal_intent as _lti
        intent = _lti.detect_legacy_temporal_intent(text or "", run_date)
    except Exception as exc:  # panne du détecteur → frontière en erreur
        return ("ERROR", str(exc) or "legacy intent detector failure")
    if intent.is_signal():
        return intent
    return None


def _as_candidate_context(base, cand_value, cand_raw, structured_date,
                          input_fingerprint, cands=()):
    """Construit LE contexte candidate (AMBIGUOUS + BLOCKED_AMBIGUOUS) —
    forme unique pour tous les chemins de démotion."""
    pol = _tp.resolve_temporal_policy(base.run_date, None, "AMBIGUOUS", "")
    return _ctx(base.run_now, base.run_date,
                (structured_date or "").strip(), "AMBIGUOUS", None,
                cand_raw or "", "", False, SOURCE_LEGACY_CANDIDATE, None,
                pol, cand_v=cand_value, cand_r=cand_raw or "",
                cands=tuple(cands),
                brief_sha=base.brief_sha,
                input_fingerprint=input_fingerprint)


def _resolve_two_channel(contractual_text: str, legacy_text: str,
                         structured_date: str, clock, closing_review_hint,
                         input_fingerprint: str,
                         raw_for_sentinel: str = "") -> TemporalContext:
    """Décision à deux canaux — le cœur du correctif v11.

    Phase 1 : le canal de CONTRÔLE seul. Il peut produire une autorité
    directe (ou un état bloquant : conflit de labels, date illisible).
    Phase 2 : le canal MÉTIER/NARRATIF, consulté seulement si le canal de
    contrôle est muet, et DÉMOTÉ — tout ce qu'il produit de décisionnaire
    devient une candidate confirmable (A5). L'amendement A3 est ainsi
    tenu par construction : seuls les quatre labels signés, saisis dans
    le canal de contrôle, décident directement.
    """
    if raw_for_sentinel and TEMPORAL_INPUT_FAILURE_SENTINEL in raw_for_sentinel:
        return blocked_error_context(
            raw_for_sentinel, structured_date, clock,
            reason="temporal control input producer failure",
            input_fingerprint=input_fingerprint)

    ctrl = _resolve_single_channel(contractual_text, structured_date, clock,
                                   closing_review_hint, input_fingerprint)
    if (ctrl.intent_source in (SOURCE_STRUCTURED, SOURCE_CONTRACTUAL)
            or ctrl.scenario_status in ("INVALID", "ERROR") or ctrl.conflict):
        return ctrl  # autorité (ou blocage) tranchée dans le bon canal

    if not (legacy_text or "").strip():
        return ctrl

    # Rank 3 has exactly ONE semantic authority: the pure, typed legacy
    # detector. The historical mission-governance parser is deliberately not
    # run on business/narrative text here: its enumerative cues can mistake an
    # operational phrase such as « remettre l'analyse au conseil le <date> »
    # for a global analysis frame. Contractual labels were already resolved
    # above from the dedicated control channel.
    _late = _detect_natural_intent(legacy_text, ctrl.run_date)
    if isinstance(_late, tuple):              # detector failure → fail-closed
        return blocked_error_context(
            legacy_text, structured_date, lambda: ctrl.run_now,
            reason=_late[1], input_fingerprint=input_fingerprint)
    if _late is not None:
        return _as_candidate_context(
            ctrl, _late.value, _late.raw, structured_date,
            input_fingerprint,
            cands=tuple(getattr(_late, "mentions", ()) or ()))

    # Compatibility « revue de clôture » remains rank-3 and confirmable, but
    # is evaluated only when the semantic detector found no temporal request.
    if closing_review_hint:
        try:
            _cr = _mg.infer_closing_review_as_of(legacy_text or "")
        except Exception:
            _cr = None
        if _cr:
            return _as_candidate_context(
                ctrl, _cr, "closing review FY inference", structured_date,
                input_fingerprint)

    return ctrl  # no rank-3 temporal signal → live verdict from control channel


def _resolve_single_channel(brief: str,
                            structured_date: str = "",
                            clock: Optional[Callable[[], datetime]] = None,
                            closing_review_hint: bool = False,
                            input_fingerprint: str = ""
                            ) -> TemporalContext:
    """Résolution mono-canal historique — capture l'horloge racine une fois,
    classe l'intention, résout LA policy. Aucun consommateur ne
    recalcule quoi que ce soit derrière (le moteur ne rappelle jamais
    resolve_temporal_policy)."""
    # ── Correctif TCR-v10 (P0-01) — PANNE DU PRODUCTEUR = BLOCKED_ERROR.
    # Avant toute classification : une frontière de vérité tombée ne peut
    # pas produire un run live, quelle que soit la suite du texte.
    if brief and TEMPORAL_INPUT_FAILURE_SENTINEL in brief:
        return blocked_error_context(
            brief, structured_date, clock,
            reason="temporal control input producer failure",
            input_fingerprint=input_fingerprint)
    _bsha = _hashlib.sha256((brief or '').encode('utf-8')).hexdigest()
    if clock is None:
        from utils.metadata_clock import run_now as clock  # horloge racine
    now = clock()
    rd = now.date().isoformat()

    # ── Parser (rangs 2 et 3) — tourne TOUJOURS.
    try:
        intent = _mg.detect_analysis_as_of(brief or "")
    except Exception:
        intent = {"status": "ERROR", "value": None, "raw": "detector failure",
                  "error_code": "TEMPORAL_AUTHORITY_ERROR",
                  "conflict": False, "candidates": [],
                  "candidate_value": None, "candidate_raw": "",
                  "intent_source": SOURCE_NONE}

    st = str(intent.get("status") or "NOT_REQUESTED")
    val = intent.get("value")
    raw = str(intent.get("raw") or "")
    code = str(intent.get("error_code") or "")
    conflict = bool(intent.get("conflict"))
    cands = tuple(intent.get("candidates") or ())

    # ── Fail-closed JAMAIS masqué (correctif TCR) : panne, label
    # illisible ou conflit de labels bloquent AVANT toute considération
    # de la valeur structurée.
    if st in ("ERROR", "INVALID"):
        pol = _tp.resolve_temporal_policy(rd, None, st, code)
        return _ctx(now, rd, (structured_date or "").strip(), st, None,
                    raw, code or ("TEMPORAL_AUTHORITY_ERROR"
                                  if st == "ERROR"
                                  else "TEMPORAL_AUTHORITY_INVALID"),
                    conflict, SOURCE_NONE, None, pol, cands=cands, brief_sha=_bsha,
                    input_fingerprint=input_fingerprint)

    # ── Rang 1 : entrée structurée (validée calendaire).
    try:
        sd = _validate_structured(structured_date)
    except Exception:
        pol = _tp.resolve_temporal_policy(rd, None, "ERROR",
                                          "TEMPORAL_AUTHORITY_ERROR")
        return _ctx(now, rd, (structured_date or "").strip(), "ERROR", None,
                    "structured analysis_as_of_date malformed",
                    "TEMPORAL_AUTHORITY_ERROR", False, SOURCE_NONE, None,
                    pol, brief_sha=_bsha,
                    input_fingerprint=input_fingerprint)

    if sd:
        if (st == "VALID"
                and intent.get("intent_source") == SOURCE_CONTRACTUAL
                and val and val != sd):
            pol = _tp.resolve_temporal_policy(
                rd, None, "INVALID", "TEMPORAL_AUTHORITY_CONFLICT")
            return _ctx(now, rd, sd, "INVALID", None,
                        f"structured {sd} vs contractual {val}",
                        "TEMPORAL_AUTHORITY_CONFLICT", True, SOURCE_NONE,
                        None, pol, brief_sha=_bsha,
                        input_fingerprint=input_fingerprint)
        # Le structuré domine l'absence d'autorité textuelle ET les
        # candidates AMBIGUOUS (flux de confirmation) — jamais un état
        # bloquant (traités plus haut).
        pol = _tp.resolve_temporal_policy(rd, sd, "VALID", "")
        return _ctx(now, rd, sd, "VALID", sd,
                    f"analysis_as_of_date = {sd} (settings)", "", False,
                    SOURCE_STRUCTURED, sd, pol, brief_sha=_bsha,
                    input_fingerprint=input_fingerprint)

    # ── Rang 3 : compatibilité revue de clôture — CANDIDATE confirmable
    # (plus jamais une autorité hors hiérarchie).
    # Correctif TCR-v4 — AUTO-DÉTECTION : le hint « revue de clôture »
    # est calculé PAR le contexte lui-même (même source que le moteur :
    # detect_agenda_genre().forbids_go_nogo). Le paramètre explicite ne
    # peut qu'AJOUTER ; app et moteur obtiennent ainsi le même verdict
    # sur le même brief — plus aucun recalcul divergent.
    if not closing_review_hint:
        try:
            from patches.agenda_genre import detect_agenda_genre as _dag
            closing_review_hint = bool(
                getattr(_dag(brief or ""), "forbids_go_nogo", False))
        except Exception:
            pass
    if st == "NOT_REQUESTED" and closing_review_hint:
        try:
            _cr = _mg.infer_closing_review_as_of(brief or "")
        except Exception:
            _cr = None
        if _cr:
            st, code = "AMBIGUOUS", "TEMPORAL_AUTHORITY_AMBIGUOUS"
            intent = dict(intent)
            intent["candidate_value"] = _cr
            intent["candidate_raw"] = "closing review FY inference"
            raw = "closing review FY inference"

    # ── Rangs 2-4 : la sortie du parser gouverne.
    pol = _tp.resolve_temporal_policy(rd, val, st, code)
    return _ctx(now, rd, "", st, val, raw, code, conflict,
                str(intent.get("intent_source") or SOURCE_NONE),
                (val if st == "VALID" else None), pol,
                cand_v=intent.get("candidate_value"),
                cand_r=str(intent.get("candidate_raw") or ""),
                cands=cands, brief_sha=_bsha,
                    input_fingerprint=input_fingerprint)


def validate_bound_context(context, brief: str, structured_date: str = "",
                           declared_fingerprint: str = ""):
    """Valide qu'un TemporalContext lié décrit exactement le brief consommé.

    v62.9 centralise ici le contrat auparavant dupliqué dans le moteur. Le
    même helper est exercé par le test end-to-end dossier agroalimentaire : canonicalisation
    de l'horizon -> liaison -> consommation moteur. Toute dérive reste
    fail-closed via TemporalContextError.
    """
    if context is None:
        raise TemporalContextError("missing temporal context")
    b_sha = _hashlib.sha256((brief or "").encode("utf-8")).hexdigest()
    ctx_fp = str(getattr(context, "input_fingerprint", "") or "")
    dec_fp = str(declared_fingerprint or "")
    fp_ok = (not ctx_fp and not dec_fp) or (ctx_fp == dec_fp)
    if getattr(context, "brief_sha", None) != b_sha:
        raise TemporalContextError("temporal_context mismatch (brief hash)")
    if getattr(context, "structured_date", None) != str(structured_date or ""):
        raise TemporalContextError("temporal_context mismatch (structured date)")
    if not fp_ok:
        raise TemporalContextError("temporal_context mismatch (input fingerprint)")
    return context


def bind_assembled_brief(context, brief: str, expected_fingerprint: str = "",
                         current_fingerprint: Optional[str] = None,
                         clock: Optional[Callable[[], datetime]] = None):
    """Correctif TCR-v10 (P0-03) — LIAISON, jamais seconde résolution.

    L'application résout UN contexte au pré-gate, sur la photographie
    courante ; le moteur, lui, analyse le BRIEF ASSEMBLÉ. Cette fonction
    rattache l'un à l'autre :

      * elle vérifie que l'entrée temporelle n'a pas dérivé pendant le
        rendu (`current_fingerprint` recapturé APRÈS `render`) ;
      * elle inscrit l'empreinte du brief assemblé dans le contexte, de
        sorte que la vérification du moteur (« ce contexte a-t-il été
        construit sur CE brief ? ») reste exigible ;
      * toute incohérence produit un BLOCKED_ERROR — jamais un contexte
        recalculé en douce.

    Aucun appel à `resolve_temporal_context` : le parser ne tourne pas une
    seconde fois, l'autorité n'est pas re-classée, la policy ne bouge pas.
    """
    from dataclasses import replace as _replace

    if context is None:
        return blocked_error_context(
            brief, "", clock, reason="missing temporal context",
            input_fingerprint=expected_fingerprint)

    if (current_fingerprint is not None
            and expected_fingerprint
            and current_fingerprint != expected_fingerprint):
        # L'entrée temporelle a changé entre le pré-gate et l'assemblage :
        # le contexte porté ne décrit plus la saisie de l'utilisateur.
        return blocked_error_context(
            brief, getattr(context, "structured_date", ""), clock,
            reason="temporal control input drifted during render",
            input_fingerprint=expected_fingerprint)

    ctx_fp = getattr(context, "input_fingerprint", "") or ""
    if expected_fingerprint and ctx_fp and ctx_fp != expected_fingerprint:
        return blocked_error_context(
            brief, getattr(context, "structured_date", ""), clock,
            reason="temporal context / control input fingerprint mismatch",
            input_fingerprint=expected_fingerprint)

    _bsha = _hashlib.sha256((brief or "").encode("utf-8")).hexdigest()
    try:
        return _replace(context, brief_sha=_bsha,
                        input_fingerprint=(expected_fingerprint or ctx_fp))
    except Exception:
        return blocked_error_context(
            brief, getattr(context, "structured_date", ""), clock,
            reason="temporal context binding failure",
            input_fingerprint=expected_fingerprint)
