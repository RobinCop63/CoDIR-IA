"""Gate 16/17 — TemporalExecutionPolicy : LA politique de mutation unique.

Gate 17 durcit le gate 16 sur quatre axes (verdict auditeur) :
  1. FAIL-CLOSED PAR DÉFAUT : l'objet nu, une policy absente, malformée,
     non versionnée ou de mode inconnu → BLOCKED_ERROR, zéro écriture.
  2. can_persist est MODE-AUTHORITATIVE : seul LIVE_MUTATING peut
     écrire ; les drapeaux ne peuvent jamais contredire le mode.
  3. AUCUNE horloge directe dans ce module : la date réelle est capturée
     UNE fois à la racine du run (utils.metadata_clock.run_now) et
     propagée ; resolve_temporal_policy sans run_date → BLOCKED_ERROR.
  4. policy_for_view CONSOMME la policy sérialisée du result (source de
     vérité) et ne recalcule JAMAIS ; sans policy sérialisée, dérivation
     stricte depuis result.run_date/analysis_date ; sans run_date →
     BLOCKED_ERROR.

Modes : LIVE_MUTATING / RETROSPECTIVE_READ_ONLY /
FUTURE_SIMULATION_READ_ONLY / BLOCKED_INVALID / BLOCKED_CONFLICT /
BLOCKED_ERROR. La persistance analytique (« politique C ») est retirée
de M6-B (branches v18). Les primitives directes de la bibliothèque
(ingest_run…) restent des outils de peuplement/test hors policy : la
policy gouverne les ENTRÉES runtime (moteur, Pilot UI).
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Optional

POLICY_VERSION = 2
POLICY_VERSIONS_READABLE = (1, 2)  # A1 — la v1 se migre en lecture

MODE_LIVE = "LIVE_MUTATING"
MODE_RETRO = "RETROSPECTIVE_READ_ONLY"
MODE_FUTURE = "FUTURE_SIMULATION_READ_ONLY"
MODE_BLOCKED_INVALID = "BLOCKED_INVALID"
MODE_BLOCKED_CONFLICT = "BLOCKED_CONFLICT"
MODE_BLOCKED_ERROR = "BLOCKED_ERROR"
MODE_BLOCKED_AMBIGUOUS = "BLOCKED_AMBIGUOUS"

ALL_MODES = (MODE_LIVE, MODE_RETRO, MODE_FUTURE, MODE_BLOCKED_INVALID,
             MODE_BLOCKED_CONFLICT, MODE_BLOCKED_ERROR,
             MODE_BLOCKED_AMBIGUOUS)

SINK_ACTION_JOURNAL = "ACTION_JOURNAL"
SINK_DECISION_HISTORY = "DECISION_HISTORY"
SINK_RELANCE = "RELANCE"
SINK_RUN_HISTORY = "RUN_HISTORY"
SINK_PILOT_MANUAL_EVENT = "PILOT_MANUAL_EVENT"

ALL_SINKS = (SINK_ACTION_JOURNAL, SINK_DECISION_HISTORY, SINK_RELANCE,
             SINK_RUN_HISTORY, SINK_PILOT_MANUAL_EVENT)

_MSG = {
    MODE_LIVE: ("", ""),
    MODE_RETRO: (
        "🔒 Analyse rétrospective — lecture seule : aucune écriture au "
        "registre, aux décisions, aux relances ni à l'historique des "
        "scores. Les contrôles de pilotage sont désactivés.",
        "🔒 Retrospective analysis — read-only: no writes to the "
        "register, decisions, follow-ups or score history. Piloting "
        "controls are disabled."),
    MODE_FUTURE: (
        "🔒 Simulation future — lecture seule : le scénario n'est jamais "
        "persisté et ne peut pas devenir l'état courant du dossier.",
        "🔒 Future simulation — read-only: the scenario is never "
        "persisted and can never become the dossier's current state."),
    MODE_BLOCKED_INVALID: (
        "⛔ Autorité temporelle invalide — run bloqué (aucune lecture "
        "injectée, aucune écriture).",
        "⛔ Temporal authority invalid — run blocked (no injected "
        "reads, no writes)."),
    MODE_BLOCKED_CONFLICT: (
        "⛔ Autorité temporelle en conflit — run bloqué (aucune lecture "
        "injectée, aucune écriture).",
        "⛔ Temporal authority conflict — run blocked (no injected "
        "reads, no writes)."),
    MODE_BLOCKED_ERROR: (
        "⛔ Autorité temporelle indisponible — run bloqué (aucune "
        "lecture injectée, aucune écriture).",
        "⛔ Temporal authority unavailable — run blocked (no injected "
        "reads, no writes)."),
    MODE_BLOCKED_AMBIGUOUS: (
        "⛔ Demande temporelle ambiguë — run bloqué : le texte suggère "
        "une date d'analyse sans permettre de la déterminer sûrement. "
        "Saisissez la date dans Réglages ou reformulez (aucune lecture "
        "injectée, aucune écriture).",
        "⛔ Ambiguous temporal request — run blocked: the text suggests "
        "an analysis date but it cannot be determined safely. Set the "
        "date in Settings or rephrase (no injected reads, no writes)."),
}


@dataclass(frozen=True)
class TemporalExecutionPolicy:
    """FAIL-CLOSED par défaut (gate 17) et IMMUABLE (gate 18) : l'objet
    nu est BLOCKED_ERROR sans aucune capacité, et aucune policy ne peut
    être mutée après construction pour élargir ses droits. Seules les
    factories de ce module produisent des policies ouvertes."""
    mode: str = MODE_BLOCKED_ERROR
    policy_version: int = POLICY_VERSION
    run_date: str = ""
    analysis_date: str = ""
    can_read_history: bool = False
    can_write_action_journal: bool = False
    can_write_decisions: bool = False
    can_write_relances: bool = False
    can_write_run_history: bool = False
    can_mutate_from_pilot: bool = False
    user_message_fr: str = _MSG[MODE_BLOCKED_ERROR][0]
    user_message_en: str = _MSG[MODE_BLOCKED_ERROR][1]

    def __post_init__(self):
        """Gate 19 — VALIDE PAR CONSTRUCTION : quel que soit ce que le
        constructeur reçoit, (a) un mode ouvert exige des dates ISO
        complètes et COHÉRENTES avec ce mode, sinon l'objet est
        rétrogradé BLOCKED_ERROR ; (b) TOUTES les capacités et les
        messages sont RE-DÉRIVÉS du mode final — jamais pris tels
        quels. Aucune policy ouverte incohérente ne peut exister."""
        mode = self.mode
        rd, ad = str(self.run_date or "")[:10], \
            str(self.analysis_date or "")[:10]
        if mode in (MODE_LIVE, MODE_RETRO, MODE_FUTURE):
            try:
                rd_d = date.fromisoformat(rd)
                ad_d = date.fromisoformat(ad)
                derived = (MODE_LIVE if ad_d == rd_d else
                           (MODE_RETRO if ad_d < rd_d else MODE_FUTURE))
            except Exception:
                derived = MODE_BLOCKED_ERROR
            if derived != mode:
                mode, rd, ad = MODE_BLOCKED_ERROR, "", ""
        elif mode not in ALL_MODES:
            mode, rd, ad = MODE_BLOCKED_ERROR, "", ""
        opened = mode in (MODE_LIVE, MODE_RETRO, MODE_FUTURE)
        write = mode == MODE_LIVE
        fr, en = _MSG[mode]
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "policy_version", POLICY_VERSION)
        object.__setattr__(self, "run_date", rd if opened else rd)
        object.__setattr__(self, "analysis_date", ad if opened else "")
        object.__setattr__(self, "can_read_history", opened)
        object.__setattr__(self, "can_write_action_journal", write)
        object.__setattr__(self, "can_write_decisions", write)
        object.__setattr__(self, "can_write_relances", write)
        object.__setattr__(self, "can_write_run_history", write)
        object.__setattr__(self, "can_mutate_from_pilot", write)
        object.__setattr__(self, "user_message_fr", fr)
        object.__setattr__(self, "user_message_en", en)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode, "policy_version": self.policy_version,
            "run_date": self.run_date,
            "analysis_date": self.analysis_date,
            "can_read_history": self.can_read_history,
            "can_write_action_journal": self.can_write_action_journal,
            "can_write_decisions": self.can_write_decisions,
            "can_write_relances": self.can_write_relances,
            "can_write_run_history": self.can_write_run_history,
            "can_mutate_from_pilot": self.can_mutate_from_pilot,
            "user_message_fr": self.user_message_fr,
            "user_message_en": self.user_message_en,
        }


def _mk(mode: str, run_date: str, analysis_date: str,
        read: bool, write: bool) -> TemporalExecutionPolicy:
    # Gate 19 — __post_init__ fait autorité : il re-dérive capacités et
    # messages et rétrograde toute incohérence. Les drapeaux passés ici
    # ne sont que documentaires.
    return TemporalExecutionPolicy(
        mode=mode, policy_version=POLICY_VERSION,
        run_date=run_date or "", analysis_date=analysis_date or "")


def resolve_temporal_policy(run_date, analysis_date,
                            scenario_status: str = "",
                            error_code: str = "") -> TemporalExecutionPolicy:
    """Classe le run. Fail-closed : run_date ABSENTE ou imparsable →
    BLOCKED_ERROR (la date réelle vient de l'horloge racine capturée une
    fois — jamais recalculée ici) ; statut inexploitable → BLOCKED_* ;
    analysis ≠ run → READ_ONLY. Seul un run live écrit."""
    rd = str(run_date or "")[:10]
    if not rd:
        return _mk(MODE_BLOCKED_ERROR, "", "", False, False)
    try:
        rd_d = date.fromisoformat(rd)
    except Exception:
        return _mk(MODE_BLOCKED_ERROR, "", "", False, False)
    st = (scenario_status or "").upper()
    if st == "ERROR":
        return _mk(MODE_BLOCKED_ERROR, rd, "", False, False)
    if st == "AMBIGUOUS":
        # Refactor — directive temporelle certaine, valeur
        # indéterminable : jamais LIVE silencieux, jamais RETRO deviné.
        return _mk(MODE_BLOCKED_AMBIGUOUS, rd, "", False, False)
    if st == "INVALID":
        mode = (MODE_BLOCKED_CONFLICT
                if (error_code or "").upper().endswith("CONFLICT")
                else MODE_BLOCKED_INVALID)
        return _mk(mode, rd, "", False, False)
    ad = str(analysis_date or "")[:10]
    if not ad or ad == rd:
        return _mk(MODE_LIVE, rd, ad or rd, True, True)
    try:
        retro = date.fromisoformat(ad) < rd_d
    except Exception:
        return _mk(MODE_BLOCKED_INVALID, rd, "", False, False)
    return _mk(MODE_RETRO if retro else MODE_FUTURE, rd, ad, True, False)


def from_dict(d) -> TemporalExecutionPolicy:
    """Désérialisation STRICTE, versionnée et COHÉRENTE (gate 18). Tout
    écart — policy absente, non-dict, version inconnue, mode inconnu —
    → BLOCKED_ERROR. Pour les modes ouverts (LIVE/RETRO/FUTURE), le
    mode est RE-DÉRIVÉ des dates sérialisées puis COMPARÉ au mode
    déclaré : dates absentes, imparsables ou incohérentes avec le mode
    → BLOCKED_ERROR. Les capacités sont RECONSTRUITES depuis le mode
    validé (mode-authoritative), jamais lues du dict."""
    try:
        if not isinstance(d, dict) or not d:
            return _mk(MODE_BLOCKED_ERROR, "", "", False, False)
        ver = d.get("policy_version")
        if ver not in POLICY_VERSIONS_READABLE:
            return _mk(MODE_BLOCKED_ERROR, "", "", False, False)
        mode = d.get("mode")
        if mode not in ALL_MODES:
            return _mk(MODE_BLOCKED_ERROR, "", "", False, False)
        # A1 — migration : un payload v1 ne connaît pas BLOCKED_AMBIGUOUS ;
        # s'il le déclare, il est forgé → fail-closed. L'écriture est
        # toujours en version courante (to_dict).
        if ver == 1 and mode == MODE_BLOCKED_AMBIGUOUS:
            return _mk(MODE_BLOCKED_ERROR, "", "", False, False)
        rd = str(d.get("run_date") or "")[:10]
        ad = str(d.get("analysis_date") or "")[:10]
        if mode in (MODE_LIVE, MODE_RETRO, MODE_FUTURE):
            derived = resolve_temporal_policy(rd, ad)
            if derived.mode != mode:
                return _mk(MODE_BLOCKED_ERROR, "", "", False, False)
            return derived
        return _mk(mode, rd, "", False, False)
    except Exception:
        return _mk(MODE_BLOCKED_ERROR, "", "", False, False)


def can_persist(policy: Optional[TemporalExecutionPolicy],
                sink: str) -> bool:
    """LA garde commune, MODE-AUTHORITATIVE (gate 17) : seul le mode
    LIVE_MUTATING peut écrire, et uniquement sur un sink connu dont le
    drapeau est vrai. Policy absente, mode inconnu, sink inconnu,
    drapeau contradictoire → refus."""
    if policy is None or sink not in ALL_SINKS:
        return False
    if getattr(policy, "mode", None) != MODE_LIVE:
        return False
    return bool({
        SINK_ACTION_JOURNAL: policy.can_write_action_journal,
        SINK_DECISION_HISTORY: policy.can_write_decisions,
        SINK_RELANCE: policy.can_write_relances,
        SINK_RUN_HISTORY: policy.can_write_run_history,
        SINK_PILOT_MANUAL_EVENT: policy.can_mutate_from_pilot,
    }[sink])


def policy_for_view(result: dict) -> TemporalExecutionPolicy:
    """Policy de la VUE affichée (Pilot UI). Gate 18 : CONSOMME la
    policy sérialisée du result (source de vérité, from_dict strict et
    cohérent) — AUCUN recalcul, AUCUNE horloge, et une policy ABSENTE
    n'est JAMAIS recalculée : elle est BLOCKED_ERROR. La policy
    désérialisée doit CORRESPONDRE aux dates racines du result (les
    champs présents des deux côtés doivent coïncider) ; toute
    divergence → BLOCKED_ERROR."""
    try:
        ta = (result or {}).get("temporal_authority") or {}
        ser = ta.get("policy")
        if not (isinstance(ser, dict) and ser):
            return _mk(MODE_BLOCKED_ERROR, "", "", False, False)
        pol = from_dict(ser)
        if pol.mode == MODE_BLOCKED_ERROR and \
                ser.get("mode") != MODE_BLOCKED_ERROR:
            return pol
        # Gate 19 — CROSS-CHECK statut racine : un scénario ERROR ou
        # INVALID au result ne peut JAMAIS coexister avec une policy
        # ouverte — divergence = corruption.
        st = str(ta.get("scenario_status") or "").upper()
        ec = str(ta.get("error_code") or "").strip()
        cf = bool(ta.get("conflict"))
        # Refactor — le cross-check couvre TOUT signal d'erreur
        # structuré : un statut bloquant, un error_code non vide ou un
        # drapeau de conflit ne peuvent JAMAIS coexister avec une
        # policy ouverte — l'incohérence est une corruption.
        if (st in ("ERROR", "INVALID") or ec or cf) and pol.mode in (
                MODE_LIVE, MODE_RETRO, MODE_FUTURE):
            return _mk(MODE_BLOCKED_ERROR, "", "", False, False)
        if pol.mode in (MODE_LIVE, MODE_RETRO, MODE_FUTURE):
            # Gate 19 — RACINES OBLIGATOIRES : un result sans run_date
            # racine (et, hors LIVE, sans analysis/authority racine)
            # ne peut pas porter une policy ouverte.
            r_rd = str((result or {}).get("run_date") or "")[:10]
            if not r_rd or r_rd != pol.run_date:
                return _mk(MODE_BLOCKED_ERROR, "", "", False, False)
            r_ad = str((result or {}).get("temporal_authority_date") or
                       (result or {}).get("analysis_date") or "")[:10]
            if pol.mode in (MODE_RETRO, MODE_FUTURE):
                if not r_ad or r_ad != pol.analysis_date:
                    return _mk(MODE_BLOCKED_ERROR, "", "", False, False)
            elif r_ad and r_ad != pol.analysis_date:
                return _mk(MODE_BLOCKED_ERROR, "", "", False, False)
        return pol
    except Exception:
        return _mk(MODE_BLOCKED_ERROR, "", "", False, False)


__all__ = [
    "TemporalExecutionPolicy", "resolve_temporal_policy", "from_dict",
    "can_persist", "policy_for_view", "POLICY_VERSION",
    "MODE_LIVE", "MODE_RETRO", "MODE_FUTURE", "MODE_BLOCKED_INVALID",
    "MODE_BLOCKED_CONFLICT", "MODE_BLOCKED_ERROR", "ALL_MODES",
    "ALL_SINKS", "SINK_ACTION_JOURNAL", "SINK_DECISION_HISTORY",
    "SINK_RELANCE", "SINK_RUN_HISTORY", "SINK_PILOT_MANUAL_EVENT",
]
