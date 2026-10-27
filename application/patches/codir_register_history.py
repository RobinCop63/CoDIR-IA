"""Cycle C — Registre d'actions CoDIR MULTI-SÉANCES (cycle de vie inter-séances).

Le registre mono-séance (patches/agenda_register.py) extrait, pour UN run, les
actions d'un point d'ordre du jour. Le cycle C ajoute la MÉMOIRE entre séances :
un CoDIR n'est plus une réunion isolée mais un fil continu (un « dossier ») où les
actions ont un cycle de vie — créées, reportées, relancées, clôturées — d'un
CoDIR au suivant.

Architecture (décision verrouillée) : journal d'ÉVÉNEMENTS APPEND-ONLY en JSONL,
un fichier par dossier (`~/.codir_ia/codir_register/<dossier>.jsonl` par défaut
(repli `data/codir_register/`)), une ligne = un
événement horodaté. L'état courant (actions ouvertes, en retard, relances) est
DÉRIVÉ à la lecture en repliant les événements. On n'écrase JAMAIS le passé.

Doctrine portée de F.4.3 (NON négociable) :
  - append-only / historisé : aucune réécriture, aucune suppression ;
  - chaque action conserve run_id, date, société, sujet, décision associée,
    action, porteur, échéance, statut, prochaine revue, source textuelle,
    score/usage ;
  - un fait financier (et une action issue d'un run non board-safe) GARDE son
    niveau d'usage et son statut — jamais promu en « vérité validée » permanente ;
  - PAS de clôture automatique : une clôture exige un événement explicite (humain) ;
  - zéro hardcoding (aucune société/personne en dur).

Fail-open : toute erreur de lecture/écriture est silencieuse et renvoie un état
vide plutôt que de casser le pipeline.
"""
from __future__ import annotations

import json
import hashlib
import re
import types
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

# Réutilise les conventions de run_history (slug, run_id, stockage sécurisé).
try:
    from patches.run_history import _slugify_company as _slug, _make_run_id, _now_iso
except Exception:  # fail-open : helpers locaux équivalents
    def _slug(name: str) -> str:
        if not name:
            return "unknown"
        s = unicodedata.normalize("NFD", name.lower().strip())
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
        return s or "unknown"

    def _make_run_id(company_name: str, timestamp: str) -> str:
        import hashlib
        return hashlib.sha256(f"{company_name}|{timestamp}".encode("utf-8")).hexdigest()[:12]

    def _now_iso() -> str:
        # Gate 12 - l horloge d audit-trail vit dans le module de
        # metadonnees (seul lieu d horloge autorise par le contrat AST).
        from utils.metadata_clock import event_timestamp
        return event_timestamp()

def _default_storage_dir() -> str:
    """Stockage par défaut HORS dossier applicatif (P1 F.5.1) : ~/.codir_ia/
    codir_register — évite la synchro cloud (OneDrive/Dropbox) du dossier de
    l'app et garde l'historique local. Repli sur data/codir_register si le home
    n'est pas accessible. Fail-open."""
    try:
        from utils.config_paths import ensure_data_dir
        return str(ensure_data_dir() / "codir_register")
    except Exception:
        return "data/codir_register"


DEFAULT_STORAGE_DIR = _default_storage_dir()
SCHEMA_VERSION = "C0.1"

# ── Vocabulaire du cycle de vie ──────────────────────────────────────────────
STATUT_A_LANCER = "À lancer"
STATUT_EN_COURS = "En cours"
STATUT_REPORTEE = "Reportée"
STATUT_CLOTUREE = "Clôturée"
STATUT_REALISEE = "Réalisée"        # 9.4.51 — clôture qualifiée : réalisation déclarée
STATUT_ABANDONNEE = "Abandonnée"    # 9.4.51 — clôture qualifiée : abandon déclaré
STATUT_A_ARBITRER = "À arbitrer"
STATUT_EN_RETARD = "En retard"   # dérivé (échéance dépassée + non clôturée)
# P0-5 temps 2 (M.5.4) — statuts EN pour le rendu multi-séances.
_STATUT_EN = {
    "À lancer": "To start", "En cours": "In progress", "Reportée": "Deferred",
    "Clôturée": "Closed", "À arbitrer": "To arbitrate", "En retard": "Overdue",
}
# B.1.3.48-chatgpt — le journal conserve un vocabulaire CANONIQUE, jamais les
# traductions d'affichage. Sans ce repli, un run EN stockait « To start » et un
# run FR suivant réaffichait ce statut anglais ; les buckets ne reconnaissaient
# plus non plus « To arbitrate » comme À arbitrer.
_STATUS_CANONICAL_48 = {
    "a lancer": STATUT_A_LANCER, "to start": STATUT_A_LANCER,
    "en cours": STATUT_EN_COURS, "in progress": STATUT_EN_COURS,
    "reportee": STATUT_REPORTEE, "deferred": STATUT_REPORTEE,
    "cloturee": STATUT_CLOTUREE, "closed": STATUT_CLOTUREE,
    "a arbitrer": STATUT_A_ARBITRER, "to arbitrate": STATUT_A_ARBITRER,
    "en retard": STATUT_EN_RETARD, "overdue": STATUT_EN_RETARD,
    "bloque": "Bloqué", "blocked": "Bloqué",
}
_OPEN_STATUSES = {STATUT_A_LANCER, STATUT_EN_COURS, STATUT_REPORTEE,
                  STATUT_A_ARBITRER, STATUT_EN_RETARD}

EV_CREATED = "created"
EV_CARRIED = "carried"      # action toujours présente au CoDIR suivant
EV_UPDATED = "updated"      # champs modifiés (statut/échéance/porteur)
EV_RELANCE = "relance"      # action ouverte non traitée → relance
EV_REPORTED = "reported"    # échéance repoussée explicitement
EV_CLOSED = "closed"        # clôture EXPLICITE (validation humaine)
EV_REOPENED = "reopened"    # réouverture EXPLICITE (validation humaine)
EV_REAPPEARED = "reappeared_after_close"  # détectée auto : NE rouvre PAS, signale « à arbitrer »

# Niveaux d'usage hérités de la gouvernance (un run non board-safe ne devient
# jamais board-safe par historisation).
USAGE_BOARD_SAFE = "board_safe"
USAGE_NON_BOARD_SAFE = "non_board_safe"
USAGE_INDICATIF = "indicatif"


# ── Événement (une ligne JSONL) ──────────────────────────────────────────────
@dataclass
class RegisterEvent:
    event_type: str
    action_key: str
    run_id: str
    run_date: str                 # ISO (YYYY-MM-DD) — date RÉELLE d'exécution
    dossier_id: str
    # Gate 12 — autorité temporelle du raisonnement (scénario en mode
    # rétrospectif). Append-only : les anciens événements sans ce champ
    # reçoivent analysis_date = run_date À LA LECTURE (migration douce).
    analysis_date: str = ""
    societe: str = ""
    sujet: str = ""
    action: str = ""
    porteur: str = ""
    echeance: str = ""
    statut: str = STATUT_A_LANCER
    prochaine_revue: str = ""
    decision_associee: str = ""
    source_textuelle: str = ""
    # B.1.3.47-chatgpt — provenance structurée de la vérité opérationnelle.
    # Ces champs sont append-only comme le reste de l'événement ; ils évitent
    # qu'une chaîne libre générée par un agent soit prise pour une confirmation.
    statut_conflict: str = ""
    status_origin: str = ""
    status_evidence_ref: str = ""
    status_confirmed_by: str = ""
    status_confirmed_at: str = ""
    completed_at: str = ""
    score: Optional[float] = None
    usage_level: str = USAGE_INDICATIF
    note: str = ""
    ts: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)


# ── Normalisation de la clé d'action (rattachement inter-séances) ────────────
_KEY_STRIP = re.compile(r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b|\bt[1-4]\s*20\d{2}\b|\b20\d{2}\b")


def normalize_action_key(action: str) -> str:
    """Clé stable pour rattacher la MÊME action d'un CoDIR au suivant : minuscule,
    sans dates/marqueurs/ponctuation, espaces normalisés. Déterministe."""
    if not action:
        return ""
    k = unicodedata.normalize("NFD", action.lower())
    k = "".join(c for c in k if unicodedata.category(c) != "Mn")
    k = _KEY_STRIP.sub(" ", k)
    k = re.sub(r"[^a-z0-9 ]+", " ", k)
    k = re.sub(r"\s+", " ", k).strip()
    return k[:70]


def _partition_semantic_events(events: List[RegisterEvent]):
    """Sépare événements pilotables et pollution historique.

    Le journal reste strictement append-only : aucune ligne n'est supprimée.
    Les faits anciennement persistés comme actions sont simplement mis en
    quarantaine à la lecture. Les événements sans libellé (clôture/report
    explicites) restent recevables seulement si leur clé a déjà été établie par
    une action valide. Le marqueur ``__decision__`` est toujours conservé.
    """
    try:
        from patches.agenda_register import is_semantic_action
    except Exception:
        is_semantic_action = lambda _text: False
    kept: List[RegisterEvent] = []
    quarantined: List[RegisterEvent] = []
    valid_keys = set()
    for ev in events or []:
        key = str(getattr(ev, "action_key", "") or "")
        if key == "__decision__":
            kept.append(ev)
            continue
        action = str(getattr(ev, "action", "") or "").strip()
        _legacy_placeholder = bool(re.fullmatch(r"[A-Za-z]{1,3}", action))
        # Un action_key explicitement distinct du libellé traduit une identité
        # d'action structurée fournie par le moteur (ex. reformulation N/N-1).
        _explicit_key_basis = bool(
            action and key and key != normalize_action_key(action))
        if action and (is_semantic_action(action) or _legacy_placeholder
                       or _explicit_key_basis):
            valid_keys.add(key)
            kept.append(ev)
            continue
        if not action and key and key in valid_keys:
            kept.append(ev)
            continue
        quarantined.append(ev)
    return kept, quarantined


def _filter_semantic_action_rows(rows: List[dict]):
    """Gate d'ingestion partagé ; renvoie lignes et quarantaine."""
    try:
        from patches.agenda_register import filter_semantic_action_rows, is_semantic_action
        kept, quarantined = filter_semantic_action_rows(
            rows, preserve_separators=False)
        # Compatibilité des journaux/tests historiques ayant utilisé des labels
        # symboliques (« a », « x », « ok ») comme actions. Cette tolérance reste
        # confinée à l'historique et ne s'applique jamais à l'extracteur métier.
        for row in list(quarantined):
            action = str((row or {}).get("action", "") or "").strip() if isinstance(row, dict) else ""
            _explicit_basis = bool(isinstance(row, dict) and
                                   str(row.get("_action_key_basis") or "").strip())
            if re.fullmatch(r"[A-Za-z]{1,3}", action) or _explicit_basis:
                kept.append(row)
                quarantined.remove(row)
        return kept, quarantined
    except Exception:
        # Fail-closed : une panne du classifieur ne doit pas persister du bruit.
        return [], list(rows or [])


def compute_dossier_id(societe: str = "", sujet: str = "",
                       dossier_label: str = "") -> str:
    """Fil continu auquel se rattachent les runs successifs. Un label explicite
    (ex. « cible vs acquéreur ») prime ; sinon la société ; le sujet désambiguïse."""
    if dossier_label:
        return _slug(dossier_label)
    base = _slug(societe) if societe else "dossier"
    if sujet:
        suj = _slug(sujet)[:24]
        if suj and suj not in base:
            base = f"{base}--{suj}"
    return base or "dossier"


# ── Stockage append-only ─────────────────────────────────────────────────────
def _storage_path(dossier_id: str, storage_dir: Optional[str] = None) -> Path:
    base = Path(storage_dir) if storage_dir else Path(DEFAULT_STORAGE_DIR)
    return base / f"{_slug(dossier_id)}.jsonl"


def _ensure_dir(path: Path) -> None:
    try:
        from utils.config_paths import ensure_private_dir as _epd
        _epd(path.parent)
    except Exception:
        path.parent.mkdir(parents=True, exist_ok=True)


def _decisions_path50(dossier_id: str, storage_dir: Optional[str] = None) -> Path:
    base = Path(_storage_path(dossier_id, storage_dir))
    return base.with_name(base.stem + ".decisions.jsonl")


def record_human_decision(dossier_id: str, text: str, decided_on: str, run_id: str = "",
                          storage_dir: Optional[str] = None) -> bool:
    """9.4.51 — une décision écrite par le dirigeant dans son brief (« Décision du conseil du 01/10/2026 : option 2
    retenue ») devient un objet d'AUTORITÉ durable du dossier, réinjecté aux séances suivantes (contre-recette du 03/10 :
    la ratification de l'option 2 se perdait dès la séance 3). Append-only ; une même décision n'est écrite qu'une fois."""
    try:
        path = _decisions_path50(dossier_id, storage_dir)
        _ensure_dir(path)
        for d in load_human_decisions(dossier_id, storage_dir):
            if d.get("text") == text and d.get("decided_on") == decided_on:
                return True
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"text": text, "decided_on": decided_on, "run_id": run_id, "source": "brief"},
                               ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def latest_board_option60(dossier_id: str, storage_dir: Optional[str] = None) -> tuple:
    """9.4.60 — contre-recette du 11/10 (F59-03) : dernière option adoptée par le conseil, lue dans l'état STRUCTURÉ du
    dossier (décisions humaines enregistrées), et non par relecture lexicale du contexte mis en forme. (option, date)."""
    try:
        for _d in reversed(load_human_decisions(dossier_id, storage_dir) or []):
            m = re.search(r"(?i)\boption\s*(\d+)\b", str(_d.get("text", "")))
            if m:
                return m.group(1), str(_d.get("decided_on", "") or "")
    except Exception:
        pass
    return "", ""


def load_human_decisions(dossier_id: str, storage_dir: Optional[str] = None) -> List[dict]:
    try:
        path = _decisions_path50(dossier_id, storage_dir)
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    except Exception:
        return []


def append_events(dossier_id: str, events: List[RegisterEvent],
                  storage_dir: Optional[str] = None) -> bool:
    """Ajoute des événements en fin de fichier (append-only). Jamais d'écrasement.
    Fail-open : renvoie False sans lever en cas d'échec."""
    if not events:
        return True
    try:
        path = _storage_path(dossier_id, storage_dir)
        _ensure_dir(path)
        with open(path, "a", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev.to_dict(), ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def load_events(dossier_id: str,
                storage_dir: Optional[str] = None) -> List[RegisterEvent]:
    """Charge tous les événements d'un dossier (ordre du fichier = chronologique).
    Tolère les lignes corrompues (les ignore) — fail-open."""
    path = _storage_path(dossier_id, storage_dir)
    out: List[RegisterEvent] = []
    if not path.exists():
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    # Gate 12 — migration append-only à la lecture.
                    if isinstance(d, dict) and not d.get("analysis_date"):
                        d["analysis_date"] = d.get("run_date", "")
                    if not isinstance(d, dict) or "action_key" not in d:
                        continue
                    out.append(RegisterEvent(**{
                        k: d.get(k) for k in RegisterEvent.__dataclass_fields__
                        if k in d
                    }))
                except Exception:
                    continue  # ligne corrompue : on saute, on ne casse pas
    except Exception:
        return []
    return out


# ── État dérivé (repli des événements) ───────────────────────────────────────
@dataclass
class ActionState:
    action_key: str
    action: str = ""
    sujet: str = ""
    porteur: str = ""
    echeance: str = ""
    source_textuelle: str = ""
    statut_conflict: str = ""
    status_origin: str = ""
    status_evidence_ref: str = ""
    status_confirmed_by: str = ""
    status_confirmed_at: str = ""
    completed_at: str = ""
    statut: str = STATUT_A_LANCER
    prochaine_revue: str = ""
    decision_associee: str = ""
    usage_level: str = USAGE_INDICATIF
    score: Optional[float] = None
    relance_count: int = 0
    first_run_id: str = ""
    first_run_date: str = ""
    # Gate 14 — autorité de l'événement GAGNANT (le dernier appliqué dans
    # l'ordre ANALYTIQUE) ; clé de provenance et de vérité de la vue.
    analysis_date: str = ""
    # Gate 14 — autorité analytique de la clôture appliquée (interne) :
    # un événement OUVERT d'autorité STRICTEMENT supérieure la lève
    # (réouverture ANALYTIQUE — la réouverture MÉTIER reste humaine).
    closed_authority: str = ""
    last_run_id: str = ""
    last_run_date: str = ""
    closed: bool = False
    reappeared_after_close: bool = False   # réapparue après clôture — à arbitrer (humain)
    closed_origin: str = ""                # 9.4.51 — qui a clos : BRIEF_DECLARATION / USER_CONFIRMED / …
    closed_note: str = ""                  # 9.4.51 — nature et date de la clôture (« réalisée le 01/10/2026 »)

    def is_open(self) -> bool:
        return not self.closed

    def is_overdue(self, as_of: Optional[date] = None) -> bool:
        if self.closed:
            return False
        d = _parse_date(self.echeance)
        if d is None:
            return False
        # Gate 12 - sans autorite fournie, JAMAIS "en retard" (zero-horloge).
        if as_of is None:
            return False
        return d < as_of


def _parse_date(s: str) -> Optional[date]:
    """Parse une échéance avec la même grammaire que le garde de vérité.

    Important : la vue multi-séances ne doit pas avoir une seconde grammaire
    plus pauvre que l'ingestion (sinon « T4 2026 » est gouverné au run mais ne
    devient jamais en retard dans l'historique).
    """
    try:
        return parse_due_date_47(s)
    except Exception:
        return None


def _parse_iso_date_g14(s0) -> Optional[date]:
    """Gate 14 (P1-E) — parse STRICT d'une date d'événement : jamais de
    comparaison de chaînes arbitraires. Vide → None (legacy) ; malformée →
    ValueError (l'appelant met l'événement en quarantaine fail-closed)."""
    if s0 in (None, ""):
        return None
    return date.fromisoformat(str(s0)[:10])


def order_events_for_state(events: List[RegisterEvent]
                           ) -> List[RegisterEvent]:
    """Gate 14 (P0-C) — l'ÉTAT ANALYTIQUE est ordonné par l'AUTORITÉ des
    événements, jamais par leur seul ordre d'écriture : tri STABLE par
    (analysis_date, run_date, ts, ordre fichier). Un run rétrospectif
    exécuté en dernier ne remplace plus le présent ; la vue latest reflète
    l'autorité analytique MAXIMALE. Un événement à date malformée est mis
    en QUARANTAINE (exclu de l'état, fail-closed — P1-E)."""
    keyed = []
    for idx, ev in enumerate(events):
        try:
            auth = _parse_iso_date_g14(getattr(ev, "analysis_date", "") or
                                       getattr(ev, "run_date", ""))
            rund = _parse_iso_date_g14(getattr(ev, "run_date", ""))
        except Exception:
            continue  # quarantaine fail-closed : jamais dans l'état
        keyed.append(((auth or date.min, rund or date.min,
                       str(getattr(ev, "ts", "") or ""), idx), ev))
    keyed.sort(key=lambda kv: kv[0])
    return [ev for _k, ev in keyed]


def _month_of51(echeance: str) -> str:
    """« 2027-03-31 », « 31/03/2027 », « mars 2027 » → « 2027-03 » (comparable) ; « » si illisible."""
    s = str(echeance or "").strip().lower()
    m = re.match(r"((?:19|20)\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.match(r"(?:\d{1,2}/)?(\d{1,2})/((?:19|20)\d{2})", s)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    try:
        from patches.agenda_register import _month50 as _m50
        return _m50(s)
    except Exception:
        return ""


def derive_state(events: List[RegisterEvent]) -> Dict[str, ActionState]:
    """Replie le journal en état courant par action. Append-only respecté :
    l'état est RECONSTRUIT, jamais stocké."""
    events, _semantic_quarantine = _partition_semantic_events(events)
    states: Dict[str, ActionState] = {}
    for ev in events:
        _src47 = getattr(ev, 'source_textuelle', '') or ''  # B.1.3.47 [5]
        if ev.action_key == "__decision__":
            continue  # marqueur de décision (lu par decision_history), pas une action
        st = states.get(ev.action_key)
        if st is None:
            st = ActionState(action_key=ev.action_key, first_run_id=ev.run_id,
                             first_run_date=ev.run_date,
                             analysis_date=(ev.analysis_date or ev.run_date))
            states[ev.action_key] = st
        # Gate 14 — l'autorité de l'état = celle de l'événement GAGNANT
        # (le dernier appliqué dans l'ordre ANALYTIQUE), plus seulement
        # celle de la création.
        st.analysis_date = (ev.analysis_date or ev.run_date or
                            st.analysis_date)
        if _src47:
            st.source_textuelle = _src47
        # B.1.3.47-chatgpt — la provenance du statut doit survivre au repli
        # événementiel et rester disponible aux vues/diagnostics.
        for _pf in ("statut_conflict", "status_origin", "status_evidence_ref",
                    "status_confirmed_by", "status_confirmed_at", "completed_at"):
            _pv = getattr(ev, _pf, "") or ""
            if _pv:
                setattr(st, _pf, _pv)
        # champs descriptifs : dernière valeur non vide gagne
        for fld in ("action", "sujet", "porteur", "echeance", "prochaine_revue",
                    "decision_associee"):
            v = getattr(ev, fld, "")
            # 9.4.51 — un porteur CONNU n'est pas écrasé par un « à désigner » lors d'une reprise (contre-recette du 03/10 :
            # le plan Specialist perdait son Directeur commercial groupe) ; un report du dirigeant garde son échéance
            if fld == "porteur" and v and re.search(r"(?i)\b(?:[àa]\s+d[ée]signer|non\s+d[ée]sign|to\s+be\s+(?:assigned|named)|tbd)\b", str(v)) \
                    and str(getattr(st, "porteur", "") or "").strip():
                continue
            if fld == "echeance" and v and st.statut == STATUT_REPORTEE and ev.event_type in (EV_CARRIED, EV_UPDATED) \
                    and str(getattr(st, "status_origin", "") or "") == "BRIEF_DECLARATION" and _month_of51(v) < _month_of51(st.echeance):
                continue
            if v:
                setattr(st, fld, v)
        # Gate 14 — réouverture ANALYTIQUE : un événement d'état OUVERT
        # (created/carried/updated/reported) dont l'autorité est
        # STRICTEMENT supérieure à celle de la clôture appliquée lève le
        # closed — la vue reflète l'autorité maximale, jamais le seul
        # ordre d'écriture. (EV_REAPPEARED garde sa sémantique « à
        # arbitrer sans réouverture ».)
        if (st.closed and st.closed_authority and
                ev.event_type in (EV_CREATED, EV_CARRIED, EV_UPDATED,
                                  EV_REPORTED) and
                ev.statut and not _is_done_status_47(
                    _canonical_status_48(ev.statut))):
            _ev_auth14 = (ev.analysis_date or ev.run_date or "")
            if _ev_auth14 and _ev_auth14 > st.closed_authority:
                st.closed = False
                st.closed_authority = ""
        if ev.statut:
            _ev_status = _canonical_status_48(ev.statut)
            # Migration fail-closed des journaux 3.45–3.47 : un ancien événement
            # CREATED/CARRIED/UPDATED portant « Fait/Done » sans preuve ne doit
            # jamais rester visible comme accompli après mise à jour du produit.
            if ev.event_type != EV_CLOSED and _is_done_status_47(_ev_status):
                _legacy_row = {
                    "action": ev.action, "echeance": ev.echeance,
                    "statut": _ev_status, "statut_confirme": False,
                    "status_origin": ev.status_origin,
                    "status_evidence_ref": ev.status_evidence_ref,
                    "status_confirmed_by": ev.status_confirmed_by,
                    "status_confirmed_at": ev.status_confirmed_at,
                    "completed_at": ev.completed_at,
                    "source_textuelle": ev.source_textuelle,
                }
                govern_action_status_row(
                    _legacy_row,
                    run_date=(ev.analysis_date or ev.run_date or None))
                _ev_status = _canonical_status_48(_legacy_row.get("statut"))
                if _legacy_row.get("statut_conflict"):
                    st.statut_conflict = _legacy_row["statut_conflict"]
                if _legacy_row.get("status_origin"):
                    st.status_origin = _legacy_row["status_origin"]
            # 9.4.51 — un REPORT décidé par le dirigeant reste affiché « Reportée » tant qu'un agent reprend l'action sans
            # en changer l'échéance (contre-recette du 03/10 : le plan reporté s'affichait « À arbitrer »)
            if not (st.statut == STATUT_REPORTEE and ev.event_type in (EV_CARRIED, EV_UPDATED)
                    and str(getattr(st, "status_origin", "") or "") == "BRIEF_DECLARATION"
                    and (not ev.echeance or _month_of51(ev.echeance) == _month_of51(st.echeance))):
                st.statut = _ev_status
        if ev.score is not None:
            st.score = ev.score
        # Gouvernance : le niveau d'usage ne MONTE jamais (non_board_safe colle).
        st.usage_level = _min_usage(st.usage_level, ev.usage_level)
        st.last_run_id = ev.run_id or st.last_run_id
        st.last_run_date = ev.run_date or st.last_run_date
        if ev.event_type == EV_RELANCE:
            st.relance_count += 1
        elif ev.event_type == EV_CLOSED:
            st.closed = True
            st.statut = ev.statut if ev.statut in (STATUT_REALISEE, STATUT_ABANDONNEE) else STATUT_CLOTUREE
            st.reappeared_after_close = False
            st.closed_authority = (ev.analysis_date or ev.run_date or "")
            st.closed_origin = str(getattr(ev, "status_origin", "") or "")
            st.closed_note = str(getattr(ev, "note", "") or "")
            if getattr(ev, "completed_at", ""):
                st.completed_at = ev.completed_at
        elif ev.event_type == EV_REOPENED:
            st.closed = False
            st.reappeared_after_close = False
        elif ev.event_type == EV_REAPPEARED:
            # NE rouvre PAS : on garde closed=True et on lève un drapeau « à arbitrer ».
            st.reappeared_after_close = True
        elif ev.event_type == EV_REPORTED:
            st.statut = STATUT_REPORTEE
            # 9.4.52 — recette du 05/10 : le report déclaré par le dirigeant doit être transmis aux agents
            if str(getattr(ev, "status_origin", "") or "") == "BRIEF_DECLARATION":
                st.reported_by_leader52 = True
                st.reported_to52 = str(getattr(ev, "echeance", "") or getattr(ev, "new_echeance", "") or st.echeance or "")
    return states


_USAGE_RANK = {USAGE_NON_BOARD_SAFE: 0, USAGE_INDICATIF: 1, USAGE_BOARD_SAFE: 2}


def events_as_of(events: List[RegisterEvent], authority) -> List[RegisterEvent]:
    """Gate 13 — vue POINT-IN-TIME du journal : ne garde que les événements
    dont l'autorité d'analyse (analysis_date, sinon run_date) est ≤ à
    l'autorité demandée. C'est la SEULE façon légitime de construire une vue
    rétrospective : filtrer le JOURNAL puis dériver l'état — jamais filtrer
    un état déjà replié sur des événements futurs. authority None/"" →
    journal complet (vue latest)."""
    if authority in (None, ""):
        return list(events)
    if isinstance(authority, date):
        auth_d = authority
    else:
        try:
            auth_d = _parse_iso_date_g14(authority)
        except Exception:
            return []          # autorité malformée : AUCUN événement
        if auth_d is None:
            return list(events)
    out = []
    for ev in events:
        try:
            prov = _parse_iso_date_g14(
                getattr(ev, "analysis_date", "") or
                getattr(ev, "run_date", "") or "")
        except Exception:
            continue           # P1-E : événement malformé → quarantaine
        if prov is None or prov <= auth_d:
            out.append(ev)
    return out


def _min_usage(a: str, b: str) -> str:
    """Le niveau d'usage le plus FAIBLE l'emporte (un run non board-safe ne
    devient jamais board-safe par historisation — contrainte 4)."""
    ra, rb = _USAGE_RANK.get(a, 1), _USAGE_RANK.get(b, 1)
    return a if ra <= rb else b


# ── Réconciliation inter-séances ─────────────────────────────────────────────

_DONE_STATUSES_47 = {"fait", "cloturee", "clôturée", "done", "termine",
                     "terminé", "closed", "completed", "realise", "réalisé",
                     "realisee", "réalisée", "acheve", "achevé", "achevee", "achevée"}

# Seules ces origines peuvent porter une preuve positive de complétion. Une
# chaîne libre ("agent_llm", "narrative", etc.) n'est jamais une preuve.
_TRUSTED_STATUS_ORIGINS_47 = {
    "USER_CONFIRMED", "DOCUMENT_EVIDENCE", "TRUSTED_CONNECTOR",
    "MANUAL_HISTORY_EVENT",
}

# Aliases de mois atteignables par l'extracteur et les interfaces FR/EN.
# Les motifs sont bornés : « mai » ne doit jamais matcher « demain ».
_MONTH_PATTERNS_47 = (
    (r"jan(?:v(?:ier)?)?\.?", 1),
    (r"f[eé]v(?:r(?:ier)?)?\.?|feb(?:ruary)?\.?", 2),
    (r"mars|mar(?:ch)?\.?", 3),
    (r"avr(?:il)?\.?|apr(?:il)?\.?", 4),
    (r"mai|may", 5),
    (r"juin|jun(?:e)?\.?", 6),
    (r"juil(?:let)?\.?|jul(?:y)?\.?", 7),
    (r"ao[uû]t|aug(?:ust)?\.?", 8),
    (r"sept?(?:embre)?\.?|sep(?:tember)?\.?", 9),
    (r"oct(?:obre|ober)?\.?", 10),
    (r"nov(?:embre|ember)?\.?", 11),
    (r"d[eé]c(?:embre)?\.?|dec(?:ember)?\.?", 12),
)


def _status_token_47(value) -> str:
    """Normalise un statut sans confondre « À faire » et « Fait »."""
    import re as _re
    raw = unicodedata.normalize("NFD", str(value or "").strip().lower())
    raw = "".join(c for c in raw if unicodedata.category(c) != "Mn")
    raw = _re.sub(r"[^a-z]+", " ", raw).strip()
    return raw


def _canonical_status_48(value) -> str:
    """Retourne le statut interne canonique (FR) à partir d'une surface FR/EN."""
    raw = str(value or "").strip()
    tok = _status_token_47(raw)
    return _STATUS_CANONICAL_48.get(tok, raw)


def _is_done_status_47(value) -> bool:
    tok = _status_token_47(value)
    if not tok:
        return False
    done = {_status_token_47(x) for x in _DONE_STATUSES_47}
    return tok in done or any(tok.startswith(d + " ") for d in done)


def parse_due_date_47(s):
    """Parse les échéances réellement produites par l'application.

    Formes supportées : dates ISO/FR, T/Q/S + année, mois abrégé ou complet,
    « fin YYYY » et année seule. Les trimestres utilisent leur véritable dernier
    jour ; aucune recherche par simple sous-chaîne n'est autorisée.
    """
    import calendar as _cal
    import datetime as _dt
    import re as _re

    raw = str(s or "").strip()
    if not raw:
        return None
    low = raw.lower()

    # Date numérique, même lorsqu'elle est entourée de texte.
    for _rx, _fmts in (
        (r"\b(20\d{2}-\d{1,2}-\d{1,2})\b", ("%Y-%m-%d",)),
        (r"\b(20\d{2}/\d{1,2}/\d{1,2})\b", ("%Y/%m/%d",)),
        (r"\b(\d{1,2}[/.\-]\d{1,2}[/.\-]20\d{2})\b",
         ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y")),
    ):
        _m = _re.search(_rx, low)
        if _m:
            for _fmt in _fmts:
                try:
                    return _dt.datetime.strptime(_m.group(1), _fmt).date()
                except Exception:
                    pass

    # Trimestre / semestre : dernier jour réel de la période.
    _m = _re.search(r"\b[tq]\s*([1-4])(?:\s*[-/]?\s*)(20\d{2})\b", low)
    if _m:
        _q, _y = int(_m.group(1)), int(_m.group(2))
        _month = _q * 3
        return _dt.date(_y, _month, _cal.monthrange(_y, _month)[1])
    _m = _re.search(r"\bs\s*([12])(?:\s*[-/]?\s*)(20\d{2})\b", low)
    if _m:
        _sem, _y = int(_m.group(1)), int(_m.group(2))
        _month = 6 if _sem == 1 else 12
        return _dt.date(_y, _month, _cal.monthrange(_y, _month)[1])

    # Jour + mois + année, puis mois + année.
    for _pat, _num in _MONTH_PATTERNS_47:
        _m = _re.search(rf"\b(\d{{1,2}})\s+(?:{_pat})(?!\w)\s+(20\d{{2}})\b", low)
        if _m:
            try:
                return _dt.date(int(_m.group(2)), _num, int(_m.group(1)))
            except Exception:
                return None
        _m = _re.search(rf"(?<!\w)(?:{_pat})(?!\w)\s+(20\d{{2}})\b", low)
        if _m:
            _y = int(_m.group(1))
            return _dt.date(_y, _num, _cal.monthrange(_y, _num)[1])

    _m = _re.search(r"\b(?:fin|end\s+of)\s+(20\d{2})\b", low)
    if _m:
        return _dt.date(int(_m.group(1)), 12, 31)
    _m = _re.fullmatch(r"(20\d{2})", low)
    if _m:
        return _dt.date(int(_m.group(1)), 12, 31)
    return None


def _trusted_completion_47(row: dict, as_of=None) -> bool:
    """True uniquement pour une confirmation structurée et authentifiable.

    Une date de confirmation/complétion fournie dans le futur invalide la preuve :
    une action ne peut pas être clôturée aujourd'hui par un événement futur. Les
    acteurs automatiques connus ne peuvent pas se faire passer pour un humain.
    """
    # Gate 12 - la validation d une cloture est un chemin de VERITE :
    # sans autorite temporelle lisible, le controle anti-date-future ne
    # peut pas s exercer -> la confirmation est REFUSEE (fail-closed),
    # jamais evaluee contre l horloge systeme.
    as_of_date = parse_due_date_47(as_of) if as_of is not None else None
    if as_of_date is None:
        return False

    completed_raw = str(row.get("completed_at") or "").strip()
    confirmed_raw = str(row.get("status_confirmed_at") or "").strip()
    completed_date = parse_due_date_47(completed_raw) if completed_raw else None
    confirmed_date = parse_due_date_47(confirmed_raw) if confirmed_raw else None
    if (completed_raw and (completed_date is None or completed_date > as_of_date)) or \
       (confirmed_raw and (confirmed_date is None or confirmed_date > as_of_date)):
        return False

    # Contrat UI historique : un vrai booléen True est une confirmation humaine
    # explicite. Une chaîne "True"/"False" ne l'est jamais.
    if row.get("statut_confirme") is True:
        return True

    origin = str(row.get("status_origin") or row.get("confirmation_source") or "").strip().upper()
    if origin not in _TRUSTED_STATUS_ORIGINS_47:
        return False
    actor = str(row.get("status_confirmed_by") or row.get("confirmed_by") or "").strip()
    evidence = str(row.get("status_evidence_ref") or row.get("evidence_ref") or "").strip()
    if actor:
        actor_words = set(_status_token_47(actor).split())
        automated = {
            "agent", "llm", "model", "assistant", "chatgpt", "claude",
            "gemini", "bot", "system", "automation", "automated", "machine",
            "inferred", "narrative", "ai", "ia",
        }
        if actor_words & automated:
            actor = ""

    valid_confirmed_at = confirmed_date is not None
    valid_completed_at = completed_date is not None
    if origin == "USER_CONFIRMED":
        return bool(actor or valid_confirmed_at)
    if origin == "DOCUMENT_EVIDENCE":
        # Le document doit être référencé ; une date structurée est recommandée
        # mais n'est pas imposée pour préserver les pièces historiques déjà liées.
        return bool(evidence)
    if origin == "TRUSTED_CONNECTOR":
        return bool(evidence and (valid_completed_at or valid_confirmed_at))
    if origin == "MANUAL_HISTORY_EVENT":
        return bool(actor and (valid_completed_at or valid_confirmed_at))
    return False


def _accounting_safe_text_47(lang: str = "fr", generic: bool = False) -> str:
    """Formulation canonique d'une action comptable conditionnelle.

    ``generic=True`` couvre les cellules où le contexte (retraite/passif) est
    porté par une autre clé du même objet. C'est le cas réel d'un deck structuré
    ``titre=Engagements retraite`` + ``bullet=Provisionner 469 k€``.
    """
    if (lang or "fr").lower().startswith("en"):
        if generic:
            return ("Have Finance / the statutory auditor confirm the nature of the "
                    "obligation, the gross amount, any available coverage and the "
                    "existence and amount of any provision; then recognise only the confirmed "
                    "shortfall")
        return ("Have Finance / the statutory auditor confirm the gross actuarial "
                "obligation, the nature and availability of any coverage, the "
                "existence and amount of any provision and the residual net exposure; then "
                "recognise only the confirmed shortfall")
    if generic:
        return ("Action à faire confirmer par la DAF / le CAC : la nature de l’obligation, le "
                "montant brut, les couvertures disponibles, l’existence et le montant d’une "
                "éventuelle provision ; puis comptabiliser uniquement l’insuffisance confirmée")
    return ("Action à faire confirmer par la DAF / le CAC avant toute comptabilisation : le "
            "montant actuariel brut, la nature et la disponibilité de la couverture, "
            "l’existence et le montant d’une éventuelle provision et l’exposition nette résiduelle ; puis "
            "comptabiliser uniquement l’insuffisance confirmée")


def govern_accounting_commitment_text(text, lang: str = "fr"):
    """Gouverne les formulations de provision/passif sur toutes les surfaces.

    Le garde traite deux familles atteignables :
    - contexte explicite retraite/IFC/pension ;
    - cellule comptable courte dont le contexte est porté ailleurs dans l'objet
      (``Provisionner 469 k€``, ``Sous-provisionnement 327 k€``,
      ``Passif social latent 327 k€``).

    Il préserve la ligne de preuve détaillée mais interdit qu'un engagement brut,
    une couverture ou une exposition indicative soit transformé en instruction
    ferme de comptabilisation.
    """
    import re as _re
    if not isinstance(text, str) or not text:
        return text, 0

    kw_ret = _re.compile(
        r"engagements?\s+(?:de\s+)?retraite|\bretraite\b|\bifc\b|pension|"
        r"passif\s+(?:social|retraite)", _re.I)
    kw_action = _re.compile(
        r"\bprovisionner\b|\bcomptabilis(?:er|ation|e|é)\b|"
        r"^\s*(?:[-*•·]\s+|\[\d+\]\s*)?(?:≈\s*)?provision\b", _re.I)
    kw_assert = _re.compile(
        r"non\s+provisionn|provisions?\s+manquantes?|sous[-\s]?provisionn|"
        r"passif\s+(?:social|retraite)(?:\s+latent)?", _re.I)
    # Forme courte dans une structure éclatée : exige un vocabulaire comptable
    # ET un montant, pour ne pas réécrire le mot « provision » au sens logistique.
    kw_generic_amount = _re.compile(
        r"(?:\bprovision(?:ner|nement|née|ne|s)?\b|sous[-\s]?provisionn\w*|"
        r"passif\s+(?:social|retraite)(?:\s+latent)?)"
        r"[^\n|]{0,80}(?:[+\-−–—]?\s*(?:€|£|\$|EUR|GBP|USD)?\s*"
        r"\d[\d\s.,]*(?:\s*(?:k|m|bn|million|milliard))?\s*(?:€|£|\$)?)",
        _re.I)
    safe = _re.compile(
        r"faire\s+confirmer|si\s+confirm|sous\s+r[eé]serve|"
        r"if\s+confirmed|subject\s+to\s+confirm|have\s+finance|"
        r"provision\s+d[eé]j[aà]\s+comptabilis[eé]e\s+[aà]\s+confirmer|"
        r"existence\s+(?:et\s+montant\s+)?d[’']une\s+[ée]ventuelle\s+provision|existence\s+(?:and\s+amount\s+)?of\s+any\s+provision|"
        r"only\s+the\s+confirmed\s+shortfall|uniquement\s+l[’']insuffisance\s+confirm",
        _re.I)

    is_en = (lang or "fr").lower().startswith("en")
    # 9.4.65 — revue de publication du 18/10 (IFC) : « provision déjà comptabilisée » PRÉSUPPOSAIT une provision que la pièce
    # pouvait exclure (« non provisionné selon l'annexe »). La réserve ne présuppose rien : existence et montant à confirmer.
    factual_caveat_ret = ("existence and amount of any provision, accounting treatment and residual exposure to be confirmed"
                          if is_en else
                          "existence et montant d'une éventuelle provision, traitement comptable et exposition résiduelle à confirmer")
    factual_caveat_generic = ("accounting treatment and residual exposure to be confirmed"
                              if is_en else
                              "traitement comptable et exposition résiduelle à confirmer")
    neutral_ret = ("Retirement obligations: gross amount, available coverage and existence of any provision "
                   "to be confirmed" if is_en else
                   "Engagements retraite : montant brut, couverture disponible et existence d'une éventuelle "
                   "provision à confirmer")

    changed = 0
    out = []
    for line in text.splitlines():
        if safe.search(line):
            out.append(line)
            continue
        has_ret = bool(kw_ret.search(line))
        generic_amount = bool(kw_generic_amount.search(line))
        is_action = bool(kw_action.search(line))
        is_assert = bool(kw_assert.search(line))
        if not ((has_ret and (is_action or is_assert)) or generic_amount):
            out.append(line)
            continue

        m = _re.match(r"^(\s*(?:[-*•·]\s+|\[\d+\]\s*)?)", line)
        prefix = m.group(1) if m else ""
        if is_action or (generic_amount and _re.search(r"\bprovisionner\b", line, _re.I)):
            replacement = _accounting_safe_text_47(lang, generic=not has_ret)
        else:
            detailed = bool(_re.search(r"\d|contrat|source|31/12|au\s+\d", line, _re.I))
            if detailed:
                caveat = factual_caveat_ret if has_ret else factual_caveat_generic
                replacement = line.rstrip(" .") + " — " + caveat
                out.append(replacement)
                changed += 1
                continue
            replacement = neutral_ret if has_ret else _accounting_safe_text_47(lang, generic=True)

        if "|" in line:
            parts = line.split("|")
            parts[0] = prefix + replacement + " "
            if is_action and len(parts) >= 4:
                parts[3] = (" Accounting impact to be quantified after confirmation "
                            if is_en else
                            " Impact comptable à quantifier après confirmation ")
            line = "|".join(parts)
        else:
            line = prefix + replacement
        out.append(line)
        changed += 1
    result = "\n".join(out)
    if text.endswith("\n"):
        result += "\n"
    return result, changed

def _infer_action_lang_47(text: str) -> str:
    import re as _re
    return ("en" if _re.search(r"\b(retirement|pension|recognise|recognized|"
                                r"accounting|auditor|coverage)\b", str(text or ""), _re.I)
            else "fr")


def action_status_display(row: dict, lang: str = "fr") -> str:
    """Statut localisé et raison de gouvernance visible pour CR/PPT/Markdown."""
    st = _canonical_status_48((row or {}).get("statut", "") or "—")
    if (lang or "fr") == "en":
        st = _STATUT_EN.get(st, st)
    tag = str((row or {}).get("statut_conflict", "") or "")
    if not tag:
        return st
    if (lang or "fr") == "en":
        reasons = {
            "ACTION_STATUS_CONFLICT": "unconfirmed future completion",
            "ACTION_STATUS_UNSOURCED": "unproven completion",
            "ACTION_REAPPEARED_AFTER_CLOSE": "reappeared after closure — human arbitration required",
            "ACTION_STATUS_GUARD_FAILURE": "status guard failure — completion not accepted",
        }
    else:
        reasons = {
            "ACTION_STATUS_CONFLICT": "complétion future non confirmée",
            "ACTION_STATUS_UNSOURCED": "complétion non prouvée",
            "ACTION_REAPPEARED_AFTER_CLOSE": "réapparue après clôture — arbitrage humain requis",
            "ACTION_STATUS_GUARD_FAILURE": "échec du garde de statut — complétion refusée",
        }
    return f"{st} — {reasons.get(tag, tag)}"

def govern_action_status_row(row, run_date=None, lang: str = "fr"):
    """Garde de vérité partagée, idempotente et fail-closed.

    ``_action_key_basis`` et ``_statut_canonical`` sont des champs internes :
    les renderers peuvent localiser le texte, tandis que le journal persiste une
    identité et un vocabulaire stables entre runs FR/EN.
    """
    import datetime as _dt
    if not isinstance(row, dict) or row.get("_separator") or \
            row.get("_row_type") == "section_header":
        return row
    row.setdefault("_action_key_basis", str(row.get("action", "") or ""))
    # Gate 12 - sans autorite lisible, AUCUN jugement temporel (les autres
    # gardes de statut, non temporels, s appliquent normalement).
    rd = parse_due_date_47(run_date)
    st_raw = str(row.get("_statut_canonical") or row.get("statut", "") or "").strip()
    st = _canonical_status_48(st_raw)
    # Les statuts de complétion sont détectés sur la forme brute ; une forme
    # canonisée « Clôturée » reste elle aussi une complétion.
    if _is_done_status_47(st_raw) or st == STATUT_CLOTUREE:
        _bd51 = _brief_declared_done51(str(row.get("action", "") or ""))
        if _bd51 is not None:
            # 9.4.51 — réalisation déclarée par le dirigeant dans son brief : sourcée, jamais rétrogradée
            row["_completion_confirmed"] = True
            row["status_origin"] = "BRIEF_DECLARATION"
            row["status_evidence_ref"] = "brief"
            row["_statut_canonical"] = st_raw
            return row
        if _trusted_completion_47(row, rd):
            row["_completion_confirmed"] = True
            if not row.get("status_origin"):
                row["status_origin"] = "USER_CONFIRMED"
            row["_statut_canonical"] = st_raw
        else:
            due = parse_due_date_47(row.get("echeance"))
            tag = ("ACTION_STATUS_CONFLICT" if (due and rd and due > rd)
                   else "ACTION_STATUS_UNSOURCED")
            row["statut"] = STATUT_A_LANCER
            row["_statut_canonical"] = STATUT_A_LANCER
            row["statut_conflict"] = tag
            row["status_origin"] = "AGENT_GENERATED"
            src = str(row.get("source_textuelle", "") or "")
            marker = ("[" + tag + ": completion sans confirmation explicite — "
                      "rétrogradée À lancer] ")
            if tag not in src:
                row["source_textuelle"] = (marker + src)[:800]
    else:
        row["statut"] = st or row.get("statut", "")
        row["_statut_canonical"] = st or row.get("statut", "")

    act = str(row.get("action", "") or "")
    governed, _n = govern_accounting_commitment_text(act, lang=lang)
    if _n:
        row["action"] = governed
        row["accounting_guard"] = "ACCOUNTING_ACTION_CONDITIONALIZED"
    return row


def canonicalize_action_status(value) -> str:
    """API publique : statut interne canonique, indépendant de la langue."""
    return _canonical_status_48(value)


def reconcile_reappeared_rows(rows, events, lang: str = "fr"):
    """Aligne le registre courant sur les événements REAPPEARED.

    Une action clôturée qui réapparaît ne doit être ni rouverte ni montrée
    « À lancer ». Elle reste clôturée dans l'historique et devient « À arbitrer »
    dans la vue du run courant, avec une raison visible.
    """
    keys = {getattr(e, "action_key", "") for e in (events or [])
            if getattr(e, "event_type", "") == EV_REAPPEARED}
    if not keys:
        return 0
    n = 0
    for row in (rows or []):
        if not isinstance(row, dict) or row.get("_separator"):
            continue
        key = normalize_action_key(str(row.get("_action_key_basis") or row.get("action") or ""))
        if key in keys:
            row["_statut_canonical"] = STATUT_A_ARBITRER
            row["statut"] = (_STATUT_EN.get(STATUT_A_ARBITRER)
                             if (lang or "fr").lower().startswith("en")
                             else STATUT_A_ARBITRER)
            row["statut_conflict"] = "ACTION_REAPPEARED_AFTER_CLOSE"
            row["status_origin"] = "HISTORY_REAPPEARED"
            n += 1
    return n

_RECALL52 = re.compile(r"(?i)^\s*(?:\W*\s*)?(?:cl[ôo]tur[ée]e?s?|r[ée]alis[ée]e?s?|abandonn[ée]e?s?|termin[ée]e?s?)\s+(?:par\s+(?:le\s+)?(?:dirigeant|CoDIR|conseil|direction)|selon\s+le\s+brief|le\s+\d{1,2}/\d{1,2}/\d{4})"
                       r"|\((?:r[ée]alis[ée]e|abandonn[ée]e|cl[ôo]tur[ée]e)\s+le\s+\d{1,2}/\d{1,2}/\d{4}\)\s*$"
                       r"|\bselon\s+le\s+brief\s+du\s+dirigeant\b"
                       # 9.4.57 — M56-01/M56-02 : « …, déclarée réalisée le 01/10/2026 : correspondance non retrouvée… »,
                       # « Rappel de cohérence : le brief précédent mentionne… » — un rappel ou un commentaire, pas une tâche
                       r"|\bd[ée]clar[ée]e?s?\s+(?:r[ée]alis[ée]e?s?|cl[ôo]tur[ée]e?s?|close?s?|abandonn[ée]e?s?)\s+le\s+\d{1,2}/\d{1,2}/\d{4}"
                       r"|^\W*Rappel(?:\s+de\s+coh[ée]rence)?\s*[:—–-]"
                       # 9.4.61 — contre-recette du 12/10 (M60-03) : la date de RÉALISATION d'une action close devenait
                       # l'échéance d'un « rappel » en retard ; les constats et commentaires d'agent ne sont pas des tâches
                       r"|\b(?:r[ée]alis[ée]e?s?|livr[ée]e?s?|termin[ée]e?s?|cl[ôo]tur[ée]e?s?)\s+le\s+\d{1,2}/\d{1,2}/\d{4}\b"
                       r"|\(statut\s+(?:du\s+)?brief\)|\(statut\s*:\s*[ÀA]\s+ARBITRER\)|\best\s+une\s+proposition\b"
                       r"|^\W*(?:Documents?|Pi[èe]ces?)\s+(?:du\s+dossier\s+)?non\s+retrouv[ée]e?s?\b"
                       r"|^\W*Bilan\s+dat[ée]\b"
                       # 9.4.62 — recette 9.4.61 : constats et rappels qui traversaient les séances
                       r"|^\W*Bilan(?:\s+\w+){0,2}\s+au\s+\d{1,2}/\d{1,2}/\d{4}\b"
                       r"|^\W*V[ée]rifications?\s+(?:faites?|effectu[ée]es?|men[ée]es?)\b"
                       r"|\((?:[^()]{0,40},\s*)?statut\s+(?:du\s+)?brief\)")


_PERIOD52 = re.compile(r"\b(?:FY\s?)?(20[2-4]\d)\b|\b(?:T|Q|S|H)[1-4]\s?(20[2-4]\d)\b", re.I)


def _periods52(text: str) -> set:
    """Années / exercices cités : une action sur une AUTRE période n'est pas la même intention (témoin ChatGPT du 05/10 :
    une présentation RSE d'une nouvelle période reste une action nouvelle)."""
    return {a or b for a, b in _PERIOD52.findall(str(text or ""))}


def _other_period52(a: str, b: str) -> bool:
    pa, pb = _periods52(a), _periods52(b)
    return bool(pa and pb and not (pa & pb))


def _rank_intentions52(action: str, prior: dict, closed_only: bool = False) -> list:
    """[(score, clé)] des actions OUVERTES de même intention, meilleur d'abord (même règle que _same_intention50).
    closed_only=True : mêmes règles, sur les actions CLOSES (9.4.57 — « déjà appliqué »)."""
    try:
        from patches.agenda_register import _token_set as _ts
    except Exception:
        return []
    mine = _ts(action)
    if len(mine) < 2:
        return []
    out = []
    for k, s in (prior or {}).items():
        if s.is_open() == bool(closed_only):
            continue
        theirs = _ts(getattr(s, "action", "") or k)
        if not theirs or _other_period52(action, getattr(s, "action", "") or k):
            continue
        inter = len(mine & theirs)
        jac = inter / len(mine | theirs)
        contained = (len(theirs) >= 3 and inter >= 0.8 * len(theirs)) or (len(mine) >= 3 and inter >= 0.8 * len(mine))
        if jac >= 0.5 or contained:
            out.append((round(max(jac, inter / max(1, min(len(mine), len(theirs)))), 3), k))
    return sorted(out, reverse=True)


_KNOWN64 = re.compile(r"(?i)\b(?:r[ée]alis[ée]e?s?|termin[ée]e?s?|achev[ée]e?s?|livr[ée]e?s?|cl[ôo]tur[ée]e?s?|report[ée]e?s?|"
                      r"d[ée]cal[ée]e?s?|abandonn[ée]e?s?|annul[ée]e?s?|retir[ée]e?s?|maintenu(?:e?s?)|done|complet(?:ed|e)|"
                      r"delivered|postponed|deferred|dropped|cancell?ed|kept)\b")


def unrecognized_statuses64(brief: str) -> List[dict]:
    """9.4.64 — recette du 15/10 : « — … — Directeur commercial — décidée. » ou « — en cours. » n'étaient ni appliqués ni
    signalés. Une puce du bloc « État des actions » qui finit par un mot de statut NON reconnu est rendue au dirigeant."""
    out: List[dict] = []
    in_block = False
    lines: List[str] = []
    for raw in str(brief or "").splitlines():                 # mêmes continuations que parse_brief_statuses
        s = raw.strip()
        if lines and s and raw[:1] in (" ", "\t") and not re.match(r"[•\-–—*]\s", s) and re.match(r"\s*[•\-–—*]\s", lines[-1]) \
                and not re.match(r"(?i)(?:d[ée]cision\s+du\s+conseil|board\s+decision|▌)", s):
            lines[-1] = lines[-1].rstrip() + " " + s
        else:
            lines.append(raw)
    for raw in lines:
        s = raw.strip()
        if re.match(r"(?i)(?:[ÉE]tat\s+des\s+actions|state\s+of\s+actions|status\s+of\s+actions)", s):
            in_block = True
            continue
        if not in_block:
            continue
        if not s or re.match(r"▌", s):
            in_block = False if re.match(r"▌", s) else in_block
            continue
        if not re.match(r"[•\-–—*]\s", s) or _KNOWN64.search(s):
            continue
        segs = [x.strip(" .;") for x in re.split(r"\s+[—–]\s+", re.sub(r"^[•\-–—*\s]+", "", s)) if x.strip(" .;")]
        if len(segs) >= 2 and len(segs[-1].split()) <= 3:
            out.append({"action": segs[0], "word": segs[-1]})
    return out


def unrecognized_md64(brief: str, lang: str = "fr") -> str:
    items = unrecognized_statuses64(brief)
    if not items:
        return ""
    en = str(lang).lower().startswith("en")
    out = ["", "**Statuses declared in the brief and NOT recognised**" if en else "**Statuts déclarés dans le brief et NON reconnus**"]
    for it in items:
        out.append(f"- « {it['action']} » → « {it['word']} » : " + (
            "status not recognised, nothing applied — use completed, postponed to DD/MM/YYYY, dropped or kept" if en else
            "statut non reconnu, rien n'est appliqué — utiliser réalisée, reportée au JJ/MM/AAAA, abandonnée ou maintenue"))
    return "\n".join(out) + "\n"


def unmatched_statuses_md52(matches: list, lang: str = "fr") -> str:
    """Section du registre (CR) : statuts déclarés dans le brief que le produit n'a PAS appliqués, et pourquoi."""
    bad = [m for m in (matches or []) if m.get("quality") in ("ambiguë", "non retrouvée")]
    done_before = [m for m in (matches or []) if m.get("quality") == "déjà appliquée"]
    en = str(lang).lower().startswith("en")
    head57 = []
    if done_before:
        head57 = ["", "**Statuses already applied at a previous session**" if en else "**Statuts déjà appliqués lors d'une séance précédente**"]
        for m in done_before:
            when = f" ({m.get('closed_date')})" if m.get("closed_date") else ""
            head57.append(f"- « {m.get('action')} » → " + (f"already {str(m.get('closed_status') or 'closed').lower()}{when}; nothing changed"
                                                         if en else f"déjà {str(m.get('closed_status') or 'close').lower()}{when} ; rien n'est modifié"))
    if not bad:
        return ("\n".join(head57) + "\n") if head57 else ""
    w = {"DONE": ("completed", "réalisée"), "POSTPONED": ("postponed", "reportée"), "DROPPED": ("dropped", "abandonnée")}
    out = ["", "**Statuses declared in the brief and NOT applied**" if en else "**Statuts déclarés dans le brief et NON appliqués**"]
    for m in bad:
        st = w.get(m.get("status"), (m.get("status"), m.get("status")))[0 if en else 1]
        if m.get("quality") == "ambiguë":
            cand = " ; ".join(c for c in (m.get("candidates") or [])[:3] if c)
            out.append(f"- « {m.get('action')} » → {st} : " + (f"ambiguous match, several actions fit ({cand}) — to be specified"
                                                                if en else f"correspondance ambiguë, plusieurs actions possibles ({cand}) — à préciser"))
        else:
            out.append(f"- « {m.get('action')} » → {st} : " + ("no matching action in the register — to be checked" if en
                                                                else "aucune action correspondante au registre — à vérifier"))
    return "\n".join(head57 + out) + "\n"


# 9.4.57 — contre-recette ChatGPT du 10/10 (§4.4) : une instruction du dirigeant non rapprochée (report du plan Specialist,
# abandon des messages tests) disparaissait du contexte à la séance suivante. Elle est conservée, comme INSTRUCTION (pas
# comme action), jusqu'à ce qu'elle soit appliquée ou retirée par le dirigeant (« — … — retirée. »).
def _unresolved_path57(dossier_id: str, storage_dir: Optional[str] = None) -> Path:
    return _storage_path(dossier_id, storage_dir).with_suffix(".unresolved.json")


def load_unresolved57(dossier_id: str, storage_dir: Optional[str] = None) -> list:
    try:
        return json.loads(_unresolved_path57(dossier_id, storage_dir).read_text(encoding="utf-8"))
    except Exception:
        return []


def _same_instruction57(a: str, b: str) -> bool:
    try:
        from patches.agenda_register import _token_set as _ts
    except Exception:
        return str(a).strip().lower() == str(b).strip().lower()
    x, y = _ts(a), _ts(b)
    return bool(x and y) and len(x & y) >= 0.8 * min(len(x), len(y))


def record_unresolved57(dossier_id: str, matches: list, run_date: str, storage_dir: Optional[str] = None) -> list:
    """Met à jour la liste des instructions non résolues après une séance : ajoute les « non retrouvée » / « ambiguë »,
    retire celles que cette séance a appliquées ou constatées déjà appliquées, et celles que le dirigeant retire
    (« — … — retirée. », ou un abandon de l'instruction elle-même). Renvoie la liste à jour."""
    cur = load_unresolved57(dossier_id, storage_dir)
    for m in matches or []:
        q, st, act = m.get("quality"), m.get("status"), m.get("action", "")
        hit = [u for u in cur if _same_instruction57(u.get("action", ""), act)]
        if q in ("certaine", "déjà appliquée"):
            cur = [u for u in cur if u not in hit]
        elif q in ("non retrouvée", "ambiguë"):
            if hit and st == "DROPPED":
                cur = [u for u in cur if u not in hit]          # retrait d'une instruction en attente
            elif not hit:
                cur.append({"action": act, "status": st or "", "date": m.get("date", ""),
                            "declared_on": str(run_date or "")[:10], "quality": q})
    try:
        path = _unresolved_path57(dossier_id, storage_dir)
        _ensure_dir(path)
        path.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
    return cur


def unresolved_md57(pending: list, lang: str = "fr") -> str:
    """Section du CR : instructions du dirigeant restées non résolues lors de séances précédentes."""
    if not pending:
        return ""
    en = str(lang).lower().startswith("en")
    w = {"DONE": ("completed", "réalisée"), "POSTPONED": ("postponed", "reportée"), "DROPPED": ("dropped", "abandonnée")}
    out = ["", "**Leader's instructions still unresolved from previous sessions**" if en
           else "**Instructions du dirigeant toujours non résolues (séances précédentes)**"]
    for u in pending:
        st = w.get(u.get("status"), (u.get("status"), u.get("status")))[0 if en else 1]
        tail = f" {('to' if en else 'au')} {u['date']}" if u.get("status") == "POSTPONED" and u.get("date") else ""
        out.append(f"- « {u.get('action')} » → {st}{tail} ({'declared on' if en else 'déclarée le'} {u.get('declared_on', '')}) — "
                   + ("to be specified, or withdrawn (« — … — withdrawn. »)" if en
                      else "à préciser, ou à retirer (« — … — retirée. »)"))
    return "\n".join(out) + "\n"


def match_brief_statuses52(dossier_id: str, brief: str, storage_dir: Optional[str] = None,
                           analysis_authority: str = "") -> list:
    """Rapprochement de chaque statut déclaré dans le brief avec le registre : « certaine » (une action), « ambiguë » (deux
    actions de même intention à égalité : rien n'est appliqué), « non retrouvée » (contre-recette ChatGPT du 05/10 : les
    déclarations sans correspondance n'étaient pas signalées)."""
    out = []
    try:
        st = derive_state(order_events_for_state(events_as_of(load_events(dossier_id, storage_dir), analysis_authority or None)))
    except Exception:
        st = {}
    for d in parse_brief_statuses(brief):
        ranked = _rank_intentions52(d["action"], st)
        if not ranked:
            # 9.4.57 — contre-recette ChatGPT du 10/10 (M56-01, P56-01) : une déclaration répétée d'une séance à l'autre
            # visait une action déjà close ; elle était dite « non retrouvée ». Elle est « déjà appliquée », avec sa date.
            _cl57 = _rank_intentions52(d["action"], st, closed_only=True)
            if _cl57:
                _k57 = _cl57[0][1]; _s57 = st.get(_k57)
                out.append({"action": d["action"], "status": d["status"], "date": d.get("date", ""), "quality": "déjà appliquée",
                            "matched_key": _k57, "matched_action": getattr(_s57, "action", ""),
                            "closed_status": getattr(_s57, "statut", "") or "",
                            "closed_date": str(getattr(_s57, "completed_at", "") or getattr(_s57, "last_run_date", "") or "")[:10],
                            "candidates": []})
                continue
            q, key = "non retrouvée", ""
        elif len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.1:
            q, key = "ambiguë", ""
        else:
            q, key = "certaine", ranked[0][1]
        out.append({"action": d["action"], "status": d["status"], "date": d.get("date", ""), "quality": q,
                    "matched_key": key, "matched_action": getattr(st.get(key), "action", "") if key else "",
                    "candidates": [getattr(st.get(k), "action", "") for _s, k in ranked[:3]]})
    return out


_STATEMENT53 = re.compile(r"(?i)^\s*(?:bilan|constat|diagnostic|lecture|synth[èe]se)\s+\w*\s*:|"
                          r"^\s*(?:le|la|les|l['’]|un|une|ce|cette|ces|il|elle)\s+[^:.]{0,90}?\b(?:est|sont|reste|restent|"
                          r"constitue|constituent|repr[ée]sente|repr[ée]sentent|appara[iî]t|semble|demeure|demeurent)\b")
_ACTION_HEAD53 = re.compile(r"(?i)^\s*(?:[àa]\s+(?:arbitrer|d[ée]cider|soumettre|lancer|investiguer|fixer|valider)|"
                            r"(?:mettre|lancer|fixer|valider|arbitrer|d[ée]finir|pr[ée]senter|cadrer|r[ée]aliser|obtenir|"
                            r"construire|aligner|clarifier|confirmer|planifier|organiser|proposer|n[ée]gocier|d[ée]ployer)\b)")


def _same_intention50(action: str, echeance: str, prior: dict) -> str:
    """Clé de l'action ENCORE OUVERTE qui porte la même intention, ou "" (jamais une action close : une action close qui
    réapparaît reste « à arbitrer », décision humaine). Même règle de racines que le registre (agenda_register)."""
    try:
        from patches.agenda_register import _token_set as _ts
    except Exception:
        return ""
    mine = _ts(action)
    if len(mine) < 2:
        return ""
    best, best_score = "", 0.0
    for k, s in (prior or {}).items():
        if not s.is_open():
            continue
        theirs = _ts(getattr(s, "action", "") or k)
        if _other_period52(action, getattr(s, "action", "") or k):
            continue
        if not theirs:
            continue
        inter = len(mine & theirs)
        jac = inter / len(mine | theirs)
        contained = (len(theirs) >= 3 and inter >= 0.8 * len(theirs)) or \
                    (len(mine) >= 3 and inter >= 0.8 * len(mine))      # v62.13.9.4.50 — déclaration courte contenue
        same_due = bool(echeance) and echeance == (getattr(s, "echeance", "") or "") and inter >= 3
        score = max(jac, 0.8 if contained else 0.0, 0.7 if same_due else 0.0)
        if (jac >= 0.5 or contained or same_due) and score > best_score:
            best, best_score = k, score
    return best


def _clean_action_text51(text: str, row: Optional[dict] = None) -> str:
    """9.4.51 — texte d'action propre à l'entrée de l'historique (contre-recette du 03/10/2026) : sans emphase Markdown
    (« *avant* »), sans date en tête (« 31/03/2027 : cadrage… » ; la date devient l'échéance si elle manquait), et sans
    la critique ajoutée en seconde phrase (« Seuil d'arrêt à fixer avant l'engagement. Un jalon d'arrêt… »)."""
    s = re.sub(r"(?<!\w)[*_]{1,2}([^*_]+?)[*_]{1,2}(?!\w)", r"\1", str(text or "")).strip()
    # 9.4.61 — contre-recette du 12/10 (M60-03) : annotations d'agent, porteurs et dates écrits DANS le libellé fragmentaient
    # l'identité des actions (« … (RECOMMANDÉ) », « … (ajout proposé au registre) », « Arrêter … le 2026-12-11 », « (DG, DAF) »).
    # Les annotations sont retirées ; un porteur entre parenthèses et une date du libellé vont dans leurs champs s'ils sont vides.
    s = re.sub(r"\s*\((?:RECOMMAND[ÉE]E?S?|recommand[ée]e?s?|ajout\s+propos[ée]\s+au\s+registre|propos[ée]e?s?|statut\s+(?:du\s+)?brief)\)",
               "", s).strip()
    _own61 = re.search(r"\s*\(((?:DG|DAF|CEO|CFO|DRH|DSI|RSE|Directeur[^()]{0,60}|Direction[^()]{0,60}|Directrice[^()]{0,60})"
                       r"(?:\s*[,/+]\s*(?:DG|DAF|CEO|CFO|DRH|DSI|Directeur[^(),]{0,40}|Direction[^(),]{0,40}))*"
                       r"(?:,\s*avec\s+contribution[^()]*)?)\)", s)
    if _own61:
        if isinstance(row, dict) and str(row.get("porteur") or "").strip().lower() in ("", "porteur à désigner", "à désigner"):
            row["porteur"] = re.sub(r",\s*avec\s+contribution.*$", "", _own61.group(1)).strip()
        s = (s[:_own61.start()] + s[_own61.end():]).strip()
    _dt61 = re.search(r"\s+(?:(?:d['’]ici|d[èe]s|avant)\s+)?(?:le|au|du)\s+(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})\b", s)
    # 9.4.62 — une date de DÉBUT (« à partir du », « à compter du », « depuis le ») n'est jamais une échéance (M56-02)
    if _dt61 and not re.search(r"(?i)(?:\b(?:r[ée]alis[ée]e?s?|livr[ée]e?s?|clos(?:e|es)?|termin[ée]e?s?|depuis)|"
                               r"[àa]\s+partir|[àa]\s+compter)\s*$", s[:_dt61.start()]):
        if isinstance(row, dict) and not str(row.get("echeance") or "").strip():
            row["echeance"] = _dt61.group(1)
        s = (s[:_dt61.start()] + s[_dt61.end():]).strip()
    m = re.match(r"^\s*(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})\s*[:—–-]\s*(.+)$", s)
    if m:
        if isinstance(row, dict) and not str(row.get("echeance") or "").strip():
            row["echeance"] = m.group(1)
        s = m.group(2).strip()
    first = re.split(r"(?<=[a-zà-ÿ0-9»)])\.\s+(?=[A-ZÀ-Ý])", s, maxsplit=1)
    if len(first) == 2 and len(first[0]) >= 15:
        s = first[0].strip()
    # 9.4.52 — « ARBITRAGES & POINTS À ARBITRER : À ARBITRER le seuil… » : l'en-tête de section de l'agent n'est pas
    # l'action ; le statut « À ARBITRER » qui suit est conservé
    # une ÉTIQUETTE DE STATUT (« À ARBITRER : », « À DÉCIDER : », « À SOUMETTRE AU DG : ») porte le statut : jamais retirée
    while True:
        _mh52 = re.match(r"^\s*([A-ZÀ-Ý0-9&/'’\-]+(?:\s+[A-ZÀ-Ý0-9&/'’\-]+){1,8})\s*:\s*(?=\S)", s)
        if not _mh52 or re.match(r"(?i)^[ÀA]\s+(?:ARBITRER|D[ÉE]CIDER|SOUMETTRE|LANCER|INVESTIGUER|FIXER|VALIDER|TRANCHER)\b",
                                   _mh52.group(1)):
            break
        s = s[_mh52.end():].strip() or s
        if not _mh52.end():
            break
    # 9.4.53 — contre-recette du 06/10 : étiquettes d'agent et Markdown hors du texte d'action
    s = re.sub(r"\[(?:NON\s+SOURC[ÉE]E?|UNSOURCED|NON\s+V[ÉE]RIFI[ÉE]E?)\]\s*", "", s, flags=re.I)
    s = re.sub(r"^(?:Parades?|ORIENTATION|Orientation)\s+RECOMMAND[ÉE]E?S?\s*(?:[:—–-]\s*)?", "", s, flags=re.I).strip() or s
    # 9.4.55 — recette 9.4.53 du 07/10 : « Parade : bâtir… », « ACTION DÉJÀ DÉCIDÉE — reconstituer… », « ARBITRAGES OU GO /
    # NO-GO COMMERCIAUX. Option 2… » : étiquette ou titre de section d'agent en tête de l'action
    s = re.sub(r"^(?:Parades?|Contre-mesures?|Mitigation)\s*[:—–-]\s*", "", s, flags=re.I).strip() or s
    # 9.4.60 — contre-recette du 11/10 (F59-06) : « RECOMMANDÉ : aligner la communication financière… » — étiquette
    # de reformulation en tête de l'action (« À ARBITRER » reste : c'est un statut porté par le registre)
    s = re.sub(r"^(?:RECOMMAND[ÉE]E?S?|Recommand[ée]e?s?)\s*[:—–-]\s*", "", s).strip() or s
    # 9.4.59 — recette 9.4.58 : « Lancement vague 1 sur 5 pays pilotes [ESTIM-HYPOTHÈSE] » — étiquette d'agent dans le texte
    s = re.sub(r"\s*\[(?:ESTIM[-‑][A-ZÉÈ\-]+|NON\s+SOURC[ÉE]|SOURC[ÉE]|FAIT|HYPOTH[ÈE]SE|CALCUL|ESTIMATION)[^\]]{0,20}\]", "", s).strip() or s
    # (« ACTION DÉJÀ DÉCIDÉE — » est conservé : il porte l'autorité du dirigeant, cf. M04)
    s = re.sub(r"^(?:[A-ZÀ-Ý0-9&/'’\-]+(?:\s+[A-ZÀ-Ý0-9&/'’\-]+){1,8})\.\s+(?=[A-ZÀ-Ý])", "", s).strip() or s
    s = re.sub(r"\*\*|__|(?<!\w)\*(?!\s)|(?<!\s)\*(?!\w)", "", s).strip()
    return s[:1].upper() + s[1:] if s else s


def ingest_run(dossier_id: str, run_id: str, run_date: str, societe: str,
               actions: List[dict], decision_associee: str = "",
               usage_level: str = USAGE_INDICATIF, run_score: Optional[float] = None,
               storage_dir: Optional[str] = None,
               analysis_date: str = "",
               auto_relance_unconfirmed: bool = True) -> List[RegisterEvent]:
    """Réconcilie les actions d'un NOUVEAU run avec l'historique du dossier et
    APPEND les événements correspondants. Ne clôture JAMAIS automatiquement, ne
    rouvre JAMAIS automatiquement.

    actions : list de dicts {action, sujet, porteur, echeance, statut,
              prochaine_revue, source_textuelle, score}.
    run_score : score de confiance du run, propagé aux actions sans score propre.
    Renvoie la liste des événements émis (pour trace/diagnostic)."""
    # B.1.3.61 — les faits/constats sont mis en quarantaine AVANT clé,
    # réconciliation et persistance. Le journal n'enregistre que des objets
    # réellement pilotables.
    # 9.4.53 — les étiquettes d'agent (« Parade RECOMMANDÉE [NON SOURCÉ] : fixer… ») sont retirées AVANT le filtre des
    # actions : elles masquaient le verbe d'action et une vraie action partait en quarantaine « non actionnable »
    _pre53 = []
    for _r53 in (actions or []):
        if isinstance(_r53, dict) and _r53.get("action"):
            _r53 = dict(_r53)
            try:
                _r53["action"] = _clean_action_text51(str(_r53["action"]), _r53) or _r53["action"]
            except Exception:
                pass
        _pre53.append(_r53)
    actions, _semantic_quarantine = _filter_semantic_action_rows(_pre53)

    # Gate 13 — le « prior » se dérive du journal FILTRÉ à l'autorité du
    # run courant : un run rétrospectif 2023 ne voit pas (et ne relance
    # jamais) une action née sous autorité 2026.
    prior = derive_state(order_events_for_state(events_as_of(
        load_events(dossier_id, storage_dir), analysis_date or run_date)))
    open_keys_before = {k for k, s in prior.items() if s.is_open()}
    seen_now: set = set()
    events: List[RegisterEvent] = []

    def _mk(ev_type, a, key, statut=None):
        return RegisterEvent(
            event_type=ev_type, action_key=key, run_id=run_id, run_date=run_date,
            analysis_date=(analysis_date or run_date),
            dossier_id=dossier_id, societe=societe,
            sujet=a.get("sujet", ""), action=a.get("action", ""),
            porteur=a.get("porteur", ""), echeance=a.get("echeance", ""),
            statut=_canonical_status_48(statut or a.get("_statut_canonical") or a.get("statut", STATUT_A_LANCER)),
            prochaine_revue=a.get("prochaine_revue", ""),
            decision_associee=decision_associee,
            source_textuelle=(a.get("source_textuelle", "") or "")[:800],
            statut_conflict=str(a.get("statut_conflict", "") or ""),
            status_origin=str(a.get("status_origin", "") or ""),
            status_evidence_ref=str(a.get("status_evidence_ref") or a.get("evidence_ref") or ""),
            status_confirmed_by=str(a.get("status_confirmed_by") or a.get("confirmed_by") or ""),
            status_confirmed_at=str(a.get("status_confirmed_at", "") or ""),
            completed_at=str(a.get("completed_at", "") or ""),
            score=(a.get("score") if a.get("score") is not None else run_score),
            usage_level=usage_level)

    # B.1.3.47-chatgpt — le garde est appliqué AVANT la clé et avant toutes
    # les surfaces. La clé reste fondée sur l'action brute ; les reformulations
    # de prudence sont uniquement des attributs d'affichage.
    for _raw in (actions or []):
        a = dict(_raw) if isinstance(_raw, dict) else {}
        raw_action = str(a.get("_action_key_basis") or a.get("action", "") or "")
        a.setdefault("_action_key_basis", raw_action)
        # Gate 12 — les statuts « En retard » se jugent contre l'AUTORITÉ
        # d'analyse, jamais contre la date réelle d'exécution.
        a = govern_action_status_row(a, analysis_date or run_date)
        # v62.13.9.4.50 — étiquettes d'agent retirées à l'ENTRÉE (tous chemins d'extraction) : « QUOI : », « QUI : DAF »,
        # « porteur : Directeur commercial » (recette du 02/10 : elles restaient au registre)
        raw_action = _clean_action_text51(re.sub(r"(?i)\b(?:quoi|what)\s*[:：]\s*", "", raw_action).strip(), a)
        if a.get("action"):
            a["action"] = _clean_action_text51(re.sub(r"(?i)\b(?:quoi|what)\s*[:：]\s*", "", str(a["action"])).strip(), a)
        if a.get("porteur"):
            a["porteur"] = re.sub(r"(?i)^\s*(?:porteurs?|qui|who|owner|responsables?|pilote)\s*[:：]\s*", "", str(a["porteur"])).strip(" .;,")
            a["porteur"] = re.sub(r"\*+|_{2,}", "", a["porteur"]).strip(" .;,")          # 9.4.53 — « **DAF** »
            # 9.4.55 — « action déjà décidée, DAF » : une étiquette de statut n'est pas un porteur
            a["porteur"] = re.sub(r"(?i)^\s*actions?\s+d[ée]j[àa]\s+d[ée]cid[ée]es?\s*[,;:—–-]?\s*", "", a["porteur"]).strip(" .;,") \
                or "Porteur à désigner"
        # 9.4.53 — un CONSTAT n'est pas une action (« Bilan sain : trésorerie de 58,1 M$… », « Le plafond de 700 M$ est
        # atteignable sans accélération… ») : phrase déclarative sans verbe d'action en tête
        if _STATEMENT53.match(raw_action) and not _ACTION_HEAD53.match(raw_action):
            continue
        key = normalize_action_key(raw_action)
        if not key:
            continue
        # v62.13.9.4.50 — RECONNAISSANCE DES REPRISES (contre-recette du 30/09, M02 : aucune des 49 actions de la séance 1
        # n'a été reconnue en séance 2 ; six reprises nettes avaient été reformulées). Une action nouvelle qui porte la
        # MÊME intention qu'une action encore ouverte (racines communes, ou même échéance et trois racines communes)
        # reprend son identité : elle est reconduite, pas recréée.
        # 9.4.52 — recette du 05/10 : « Clôturé par le dirigeant : passerelle … (réalisée le 01/10/2026) », écrit par un
        # agent, était extrait comme action, échéance = date de réalisation, donc « En retard ». Une ligne de RAPPEL d'une
        # réalisation, d'un abandon ou d'une clôture n'est jamais une action à suivre.
        try:   # 9.4.65 — F01/F03 : ni une décision passée constatée, ni un intertitre ne sont des actions du registre
            from utils.analysis_objects import is_past_decision_statement65 as _pd65, is_subheading65 as _sh65
            if _pd65(raw_action) or _sh65(raw_action):
                continue
        except Exception:
            pass
        if _RECALL52.search(raw_action):
            continue
        # 9.4.57 — M56-02 : « Année 1 à partir du 2026-10-09 : budget à arbitrer… » prenait sa DATE DE DÉBUT pour échéance,
        # donc « En retard » le lendemain. Une date introduite par « à partir du / dès le / depuis le » n'est pas une échéance.
        try:
            _ech57 = str(a.get("echeance") or "").strip()
            if _ech57:
                _iso57 = _ech57[:10]
                _fr57 = (f"{_iso57[8:10]}/{_iso57[5:7]}/{_iso57[:4]}" if re.match(r"\d{4}-\d{2}-\d{2}", _iso57) else _ech57)
                if re.search(r"(?i)\b(?:à\s+partir\s+du|à\s+compter\s+du|dès\s+le|depuis\s+le|from|starting|as\s+of)\s+(?:"
                             + re.escape(_iso57) + "|" + re.escape(_fr57) + ")", raw_action):
                    a["echeance"] = ""
        except Exception:
            pass
        # 9.4.57 — §4.5 : « À PROPOSER au dirigeant : réouverture de… » est une proposition, à arbitrer, pas une tâche à lancer
        if re.match(r"(?i)^\W*(?:À|A)\s+PROPOSER\b|^\W*Proposition\s+de\s+r[ée]ouverture\b", raw_action):
            a["statut"] = STATUT_A_ARBITRER
        if key not in prior:
            _match50 = _same_intention50(raw_action, str(a.get("echeance") or ""), prior)
            if _match50:
                key = _match50
            else:
                # 9.4.52 — recette du 05/10 : la présentation RSE déclarée réalisée revenait ouverte, reformulée par les
                # agents (« Présenter au comité d'audit l'avancement… »). La reconnaissance des reprises vaut aussi pour
                # les actions CLOSES PAR LE DIRIGEANT : une reformulation est un rappel, sauf demande explicite de réouverture.
                _closed52 = {k2: types.SimpleNamespace(action=getattr(s2, "action", ""), echeance=getattr(s2, "echeance", ""),
                                                       is_open=lambda: True)
                             for k2, s2 in prior.items()
                             if getattr(s2, "closed", False) and str(getattr(s2, "closed_origin", "") or "") in ("BRIEF_DECLARATION", "USER_CONFIRMED")}
                # une demande EXPLICITE de réouverture reste une action nouvelle, tracée (jamais une réouverture silencieuse)
                _reopen52 = re.search(r"(?i)\b(?:rouvr|r[ée]ouvr|relanc|reprendre|r[ée]tabli|reopen|restart|refaire|redo|reinstate)", raw_action)
                _m52 = _same_intention50(raw_action, str(a.get("echeance") or ""), _closed52) if (_closed52 and not _reopen52) else ""
                if _m52:
                    key = _m52
                elif not _reopen52:
                    # 9.4.52 — contre-recette du 05/10 : une VARIANTE d'une action reportée par le dirigeant (« Lancement du
                    # pilote commercial et trade marketing » / « Lancer un pilote Specialist + trade marketing… ») suit le
                    # report : trois racines communes et les trois quarts de la variante, jamais un simple mot commun
                    try:
                        from patches.agenda_register import _token_set as _ts52
                        _mine52 = _ts52(raw_action)
                        for _k52, _s52 in prior.items():
                            if not (_s52.is_open() and getattr(_s52, "reported_by_leader52", False)):
                                continue
                            if _other_period52(raw_action, getattr(_s52, "action", "")):
                                continue
                            _in52 = len(_mine52 & _ts52(getattr(_s52, "action", "") or _k52))
                            if _in52 >= 3 and _in52 >= 0.75 * len(_mine52):
                                key = _k52
                                break
                    except Exception:
                        pass
                    # 9.4.57 — contre-recette du 10/10 (M56-03) : « Cadrage du périmètre SI (unité, périmètre, ROI) pour le
                    # budget » recréait, sous un autre intitulé, « Clarifier l'enveloppe SI (unité, périmètre, ROI) » que le
                    # dirigeant venait d'abandonner. Une variante proche d'une action ABANDONNÉE par le dirigeant n'est ni
                    # un rappel ni une tâche à lancer : c'est une PROPOSITION de reprise, à arbitrer, tracée comme telle.
                    if key not in prior:
                        try:
                            from patches.agenda_register import _token_set as _ts57
                            _mine57 = _ts57(raw_action)
                            for _k57, _s57 in prior.items():
                                if not (getattr(_s57, "closed", False) and str(getattr(_s57, "closed_origin", "") or "") ==
                                        "BRIEF_DECLARATION" and re.search(r"(?i)abandon", str(getattr(_s57, "statut", "")))):
                                    continue
                                _th57 = _ts57(getattr(_s57, "action", "") or _k57)
                                _in57 = len(_mine57 & _th57)
                                if _th57 and _in57 >= 3 and _in57 >= 0.6 * len(_th57) and not _other_period52(
                                        raw_action, getattr(_s57, "action", "")):
                                    a["statut"] = STATUT_A_ARBITRER
                                    a["status_origin"] = "PROPOSITION_REPRISE"          # trace de la nature de l'entrée
                                    a["status_evidence_ref"] = (f"Reprise proposée de « {getattr(_s57, 'action', '')} », "
                                                                f"abandonnée par le dirigeant : à arbitrer.")[:300]
                                    break
                        except Exception:
                            pass
        seen_now.add(key)

        # Une complétion authentifiée est un ÉVÉNEMENT DE CLÔTURE, pas une action
        # ouverte portant seulement le mot « Fait ». Cette distinction empêche le
        # paradoxe « Fait » puis « En retard ».
        if a.get("_completion_confirmed"):
            events.append(_mk(EV_CLOSED, a, key, statut=a.get("statut") or "Fait"))
            continue

        if key in prior and prior[key].is_open():
            # action déjà suivie et toujours ouverte → reconduite (continuité)
            _evc52 = _mk(EV_CARRIED, a, key)
            if getattr(prior[key], "reported_by_leader52", False):
                # 9.4.52 — une variante d'agent ne ramène jamais une action reportée par le dirigeant à une date plus tôt
                _evc52.echeance = str(prior[key].echeance or _evc52.echeance or "")
            events.append(_evc52)
        elif key in prior and prior[key].closed and \
                str(getattr(prior[key], "closed_origin", "") or "") in ("BRIEF_DECLARATION", "USER_CONFIRMED") and \
                not re.search(r"(?i)\b(?:rouvr|r[ée]ouvr|relanc|reprendre|reopen|restart)", str(a.get("action", "") or "")):
            # 9.4.51 — contre-recette du 03/10 : la passerelle réalisée et la présentation RSE réalisée, citées par les
            # agents de la séance suivante, revenaient « réapparues — à arbitrer ». Une clôture décidée par le dirigeant
            # n'est remise en cause que par une demande explicite de réouverture ; sinon c'est un rappel, sans événement.
            continue
        elif key in prior and prior[key].closed:
            # réapparaît après clôture → on NE rouvre PAS automatiquement : on signale
            # « à arbitrer » et on laisse la décision (réouverture/maintien) à l'humain.
            ev_r = _mk(EV_REAPPEARED, a, key, statut=STATUT_A_ARBITRER)
            ev_r.note = "Réapparue après clôture — à arbitrer (validation humaine requise, pas de réouverture auto)."
            events.append(ev_r)
        else:
            events.append(_mk(EV_CREATED, a, key))

    # Actions ouvertes au(x) CoDIR précédent(s) NON traitées dans ce run.
    # v62.6 : les propositions purement générées par les agents ne reçoivent
    # plus de relance automatique dans l'application. Une relance exige une
    # confirmation humaine structurée. Le défaut ``True`` conserve l'API
    # historique des harnais/unit-tests ; le moteur terrain passe ``False``.
    for key in (open_keys_before - seen_now):
        s = prior[key]
        _confirmed = bool(
            str(getattr(s, "status_confirmed_by", "") or "").strip()
            or str(getattr(s, "status_confirmed_at", "") or "").strip()
            or str(getattr(s, "status_evidence_ref", "") or "").strip()
            or str(getattr(s, "status_origin", "") or "").upper().startswith("MANUAL")
        )
        if not auto_relance_unconfirmed and not _confirmed:
            continue
        ev = RegisterEvent(
            event_type=EV_RELANCE, action_key=key, run_id=run_id,
            run_date=run_date, analysis_date=(analysis_date or run_date),
            dossier_id=dossier_id, societe=societe,
            sujet=s.sujet, action=s.action, porteur=s.porteur,
            echeance=s.echeance, statut=s.statut,
            prochaine_revue=s.prochaine_revue, usage_level=s.usage_level,
            decision_associee=decision_associee,
            note=("Non traitée à cette revue — relance d'une action confirmée."
                  if not auto_relance_unconfirmed else
                  "Non traitée à ce CoDIR — relance automatique (reste ouverte)."))
        events.append(ev)

    # La décision du run doit être tracée même si aucune action n'est portée par un
    # événement la véhiculant (ex. run sans action nouvelle ni relance) → marqueur.
    if decision_associee and not any(e.decision_associee for e in events):
        events.append(RegisterEvent(
            event_type=EV_UPDATED, action_key="__decision__", run_id=run_id,
            run_date=run_date, analysis_date=(analysis_date or run_date),
            dossier_id=dossier_id, societe=societe,
            decision_associee=decision_associee,
            note="Marqueur de décision du CoDIR (aucune action portée ce run)."))

    append_events(dossier_id, events, storage_dir)
    return events


def close_action(dossier_id: str, action_key: str, run_id: str, run_date: str,
                 note: str = "", storage_dir: Optional[str] = None) -> bool:
    """Clôture EXPLICITE (validation humaine). Aucune clôture n'est jamais
    automatique (contrainte 5)."""
    ev = RegisterEvent(event_type=EV_CLOSED, action_key=action_key, run_id=run_id,
                       run_date=run_date, dossier_id=dossier_id,
                       analysis_date=run_date,
                       statut=STATUT_CLOTUREE, status_origin="MANUAL_HISTORY_EVENT",
                       status_evidence_ref=note or "manual_close_action",
                       note=note or "Clôture validée (humain).")
    return append_events(dossier_id, [ev], storage_dir)


def reopen_action(dossier_id: str, action_key: str, run_id: str, run_date: str,
                  note: str = "", storage_dir: Optional[str] = None) -> bool:
    """Réouverture EXPLICITE (validation humaine) d'une action clôturée. Aucune
    réouverture n'est jamais automatique (P1 F.5.1)."""
    ev = RegisterEvent(event_type=EV_REOPENED, action_key=action_key, run_id=run_id,
                       run_date=run_date, analysis_date=run_date,
                       dossier_id=dossier_id,
                       statut=STATUT_EN_COURS, note=note or "Réouverture validée (humain).")
    return append_events(dossier_id, [ev], storage_dir)


def report_action(dossier_id: str, action_key: str, run_id: str, run_date: str,
                  new_echeance: str = "", note: str = "",
                  storage_dir: Optional[str] = None) -> bool:
    """Report EXPLICITE d'échéance."""
    ev = RegisterEvent(event_type=EV_REPORTED, action_key=action_key, run_id=run_id,
                       run_date=run_date, dossier_id=dossier_id,
                       echeance=new_echeance, statut=STATUT_REPORTEE,
                       note=note or "Échéance reportée.")
    return append_events(dossier_id, [ev], storage_dir)


# ── Vues ─────────────────────────────────────────────────────────────────────
def open_actions(dossier_id: str, as_of: Optional[date] = None,
                 storage_dir: Optional[str] = None) -> List[ActionState]:
    """Actions ouvertes du dossier, statut « En retard » dérivé à la lecture."""
    states = derive_state(order_events_for_state(
        events_as_of(load_events(dossier_id, storage_dir), as_of)))
    out = []
    for s in states.values():
        if s.is_open():
            if s.is_overdue(as_of):
                s.statut = STATUT_EN_RETARD
            # Les actions héritées d'un ancien build passent aussi par le garde
            # comptable avant toute vue multi-séances.
            try:
                s.action, _ = govern_accounting_commitment_text(
                    s.action, _infer_action_lang_47(s.action))
            except Exception:
                pass
            out.append(s)
    out.sort(key=lambda s: (not s.is_overdue(as_of), s.echeance or "9999"))
    return out


def dossier_timeline(dossier_id: str,
                     storage_dir: Optional[str] = None,
                     as_of: Optional[date] = None) -> List[dict]:
    """Historique CoDIR → CoDIR : par run, comptes nouvelles / reconduites /
    relances / clôturées / reportées. Gate 13 : vue point-in-time via as_of."""
    events = events_as_of(load_events(dossier_id, storage_dir), as_of)
    events, _semantic_quarantine = _partition_semantic_events(events)
    by_run: Dict[str, dict] = {}
    order: List[str] = []
    for ev in events:
        rid = ev.run_id or "?"
        if rid not in by_run:
            by_run[rid] = {"run_id": rid, "run_date": ev.run_date,
                           "created": 0, "carried": 0, "relance": 0,
                           "closed": 0, "reported": 0, "reopened": 0,
                           "reappeared_after_close": 0}
            order.append(rid)
        b = by_run[rid]
        if ev.event_type in b:
            b[ev.event_type] += 1
    return [by_run[r] for r in order]


def decision_history(dossier_id: str,
                     storage_dir: Optional[str] = None,
                     as_of: Optional[date] = None) -> List[dict]:
    """Décision associée par run (écarts N vs N-1). Gate 14 : point-in-time
    ET ordre ANALYTIQUE — la décision N-1 est celle de l'autorité maximale
    admissible, jamais du dernier append."""
    events = order_events_for_state(
        events_as_of(load_events(dossier_id, storage_dir), as_of))
    seen: Dict[str, str] = {}
    out: List[dict] = []
    for ev in events:
        if ev.decision_associee and ev.run_id not in seen:
            seen[ev.run_id] = ev.decision_associee
            out.append({"run_id": ev.run_id, "run_date": ev.run_date,
                        "decision": ev.decision_associee})
    return out


def decision_ecarts(dossier_id: str,
                    storage_dir: Optional[str] = None,
                    as_of: Optional[date] = None) -> List[dict]:
    """Signale un ÉCART quand la décision change d'un run au suivant."""
    hist = decision_history(dossier_id, storage_dir, as_of=as_of)
    out = []
    for prev, cur in zip(hist, hist[1:]):
        if normalize_action_key(prev["decision"]) ==                 normalize_action_key(cur["decision"]):
            continue
        # Gate 14 — un écart appartient à la CONTINUITÉ de pilotage : la
        # décision source doit avoir été réellement EXÉCUTÉE avant la
        # cible. Une décision rétrospective ajoutée après coup (analyse
        # ancrée avant, exécution après) ne réécrit pas la continuité.
        try:
            _pd = _parse_iso_date_g14(prev.get("run_date"))
            _cd = _parse_iso_date_g14(cur.get("run_date"))
            if _pd and _cd and _pd > _cd:
                continue
        except Exception:
            continue
        out.append({"from_run": prev["run_id"], "to_run": cur["run_id"],
                    "from": prev["decision"], "to": cur["decision"]})
    return out


# ── Rendu (markdown ; les renderers DOCX/PPTX consomment les buckets) ────────
def buckets(dossier_id: str, as_of: Optional[date] = None,
            storage_dir: Optional[str] = None) -> Dict[str, List[ActionState]]:
    """Regroupe les actions pour le rendu : nouvelles (ce dernier run), en retard,
    reportées, à arbitrer, clôturées récentes."""
    states = list(derive_state(order_events_for_state(
        events_as_of(load_events(dossier_id, storage_dir),
                     as_of))).values())
    last_run = ""
    dates = [s.last_run_date for s in states if s.last_run_date]
    if dates:
        last_run = max(dates)
    b = {"nouvelles": [], "en_retard": [], "reportees": [],
         "a_arbitrer": [], "cloturees": [], "reapparues": []}
    for s in states:
        if s.closed:
            b["cloturees"].append(s)
            if s.reappeared_after_close:
                b["reapparues"].append(s)   # clôturée mais réapparue → à arbitrer
            continue
        if s.is_overdue(as_of):
            b["en_retard"].append(s)
        if s.statut == STATUT_REPORTEE:
            b["reportees"].append(s)
        if s.statut == STATUT_A_ARBITRER:
            b["a_arbitrer"].append(s)
        if s.first_run_date == last_run and s.first_run_date:
            b["nouvelles"].append(s)
    return b


def format_prior_context_block(dossier_id: str, lang: str = "fr",
                               as_of: Optional[date] = None,
                               storage_dir: Optional[str] = None,
                               analysis_authority: str = "",
                               brief_text: str = "") -> str:
    """Cycle C (F.5.2) — bloc de CONTEXTE à injecter EN AMONT des agents pour que
    le CoDIR courant traite vraiment l'héritage du précédent : actions ouvertes à
    traiter, en retard, reportées, réapparues après clôture, décision N-1, écarts.
    Texte neutre (contexte de continuité, pas des faits à réasserter). Vide si pas
    d'historique. Fonction pure (testable hors-ligne)."""
    # Gate 13 — UNE autorité point-in-time pour tout le bloc : le journal
    # est filtré AVANT toute dérivation (events_as_of via les vues), ce qui
    # remplace et dépasse le filtre d'états gate 12 (un événement futur
    # n'existe même plus dans la vue). analysis_authority (ISO) et as_of
    # (date) désignent la même autorité ; le plus précis des deux gagne.
    _auth13 = as_of
    if analysis_authority and _auth13 is None:
        try:
            _auth13 = date.fromisoformat(str(analysis_authority)[:10])
        except Exception:
            _auth13 = None
    opens = open_actions(dossier_id, _auth13, storage_dir)
    if not opens:
        # rien d'ouvert : on regarde quand même la dernière décision pour continuité
        hist = decision_history(dossier_id, storage_dir, as_of=_auth13)
        if not hist and not load_human_decisions(dossier_id, storage_dir):
            return ""
    b = buckets(dossier_id, _auth13, storage_dir)
    hist = decision_history(dossier_id, storage_dir, as_of=_auth13)
    ecarts = decision_ecarts(dossier_id, storage_dir, as_of=_auth13)
    last_decision = hist[-1]["decision"] if hist else ""
    overdue = [s for s in opens if s.is_overdue(_auth13)]
    reportees = b.get("reportees", [])
    reapparues = b.get("reapparues", [])

    L = (lambda fr, en: fr if lang == "fr" else en)
    lines = [L("CONTEXTE — CoDIR PRÉCÉDENT (continuité, à traiter dans cette séance ; "
               "ne pas réinventer, ne pas réasserter comme faits nouveaux) :",
               "CONTEXT — PREVIOUS CoDIR (continuity, address in this session; "
               "do not reinvent, do not restate as new facts):")]
    if opens:
        # v62.13.9.4.50 — sélection ANNONCÉE (contre-recette du 30/09, M03 : 12 actions sur 49 injectées sans le dire) :
        # en retard d'abord, puis par échéance la plus proche ; le reste est au registre
        opens = sorted(opens, key=lambda s: (not s.is_overdue(_auth13), str(s.echeance or "9999-12-31")))
        if len(opens) > 12:
            lines.append(L(f"• Actions ouvertes à traiter ({12} sur {len(opens)} — en retard puis échéances les plus proches ; "
                           f"les autres restent au registre) :",
                           f"• Open actions to address ({12} of {len(opens)} — overdue first, then nearest deadlines; "
                           f"the others remain in the register):"))
        else:
            lines.append(L("• Actions ouvertes à traiter :", "• Open actions to address:"))
        for s in opens[:12]:
            tag = L(" [EN RETARD]", " [OVERDUE]") if s.is_overdue(_auth13) else ""
            ech = f" (éch. {s.echeance})" if s.echeance else ""
            rel = f" — relances: {s.relance_count}" if s.relance_count else ""
            lines.append(f"    - {s.action}{ech}{tag}{rel}")
    if reportees:
        lines.append(L("• Reportées (échéance repoussée) :", "• Reported (deadline moved):"))
        for s in reportees[:6]:
            lines.append(f"    - {s.action}")
    if reapparues:
        lines.append(L("• Réapparues après clôture — À ARBITRER (ne pas rouvrir sans décision) :",
                       "• Reappeared after closure — TO ARBITRATE (do not reopen without a decision):"))
        for s in reapparues[:6]:
            lines.append(f"    - {s.action}")
    # 9.4.51 — AUTORITÉ HUMAINE réinjectée (contre-recette du 03/10/2026) : les décisions écrites par le dirigeant et les
    # clôtures qu'il a déclarées traversent les séances ; elles priment sur toute recommandation antérieure
    _dec51 = load_human_decisions(dossier_id, storage_dir)
    if _dec51:
        lines.append(L("• DÉCISIONS ADOPTÉES par le dirigeant (autorité : brief) — à appliquer, non à rediscuter :",
                       "• DECISIONS ADOPTED by the leader (authority: brief) — to apply, not to reopen:"))
        for _d in _dec51[-6:]:
            lines.append(f"    - {_d.get('text', '')} — {L('décidée le', 'decided on')} {_d.get('decided_on', '')}")
        if any(re.search(r"(?i)\boption\s*\d", str(_d.get("text", ""))) for _d in _dec51):
            # 9.4.53 — contre-recette ChatGPT du 06/10 (M04) : le choix adopté ne se redemande pas ; son CADRE reste distinct
            lines.append(L("    (Option retenue : ne plus demander son statut ; seul son cadre d'exécution — plafond, jalons, "
                           "budget — reste à arbitrer, comme une question distincte du choix.)",
                           "    (Retained option: do not ask for its status again; only its execution framework — cap, "
                           "milestones, budget — remains to be decided, as a question separate from the choice.)"))
    try:
        _all51 = derive_state(order_events_for_state(events_as_of(load_events(dossier_id, storage_dir), _auth13)))
    except Exception:
        _all51 = {}
    _human_closed51 = [s for s in _all51.values() if s.closed and str(getattr(s, "closed_origin", "")) == "BRIEF_DECLARATION"]
    if _human_closed51:
        lines.append(L("• Clôturées par décision du dirigeant (rappel ; ne pas reprogrammer sans demande explicite de réouverture) :",
                       "• Closed by the leader's decision (reminder; do not reschedule without an explicit reopening request):"))
        for s in _human_closed51[-8:]:
            lines.append(f"    - {s.action} — {s.closed_note or s.statut}")
    # 9.4.52 — contre-recette ChatGPT du 05/10 : les statuts que le brief de CETTE séance déclare n'étaient appliqués
    # qu'en fin de séance, après les agents. Ils leur sont donnés dès maintenant, rapprochés du registre.
    if brief_text:
        try:
            _m52 = match_brief_statuses52(dossier_id, brief_text, storage_dir, analysis_authority)
        except Exception:
            _m52 = []
        if _m52:
            _w52 = {"DONE": L("réalisée", "completed"), "POSTPONED": L("reportée", "postponed"), "DROPPED": L("abandonnée", "dropped")}
            lines.append(L("• Statuts déclarés par le dirigeant dans le brief de cette séance (font autorité dès maintenant ; "
                           "une réouverture ne peut être que PROPOSÉE, à arbitrer) :",
                           "• Statuses declared by the leader in this session's brief (authoritative now; a reopening can only "
                           "be PROPOSED, to be decided):"))
            for m in _m52:
                if m["quality"] == "déjà appliquée":
                    # 9.4.57 — M56-01 : l'agent recevait « correspondance non retrouvée » pour une action déjà close et
                    # créait une « vérification » datée du jour de la réalisation ; il reçoit désormais l'état terminal
                    lines.append(f"    - {m['matched_action'] or m['action']} → " + L(
                        f"déjà {str(m.get('closed_status') or 'close').lower()} lors d'une séance précédente"
                        f"{(' (' + m['closed_date'] + ')') if m.get('closed_date') else ''} ; rien à recréer ni à vérifier "
                        f"sans demande du dirigeant",
                        f"already {str(m.get('closed_status') or 'closed').lower()} at a previous session"
                        f"{(' (' + m['closed_date'] + ')') if m.get('closed_date') else ''}; nothing to recreate or verify "
                        f"without the leader's request"))
                    continue
                # 9.4.61 — contre-recette du 12/10 (M60-01/M60-02) : c'est la DÉCLARATION du dirigeant (son verbe et son objet)
                # qui est transmise, et non l'intitulé du registre, plus large quand l'action réunit plusieurs travaux
                tgt = m["action"] or m["matched_action"]
                tail = (f" {L('au', 'to')} {m['date']}" if m["status"] == "POSTPONED" and m.get("date") else "")
                q = "" if m["quality"] == "certaine" else f" — {L('correspondance', 'match')} {m['quality']}"
                lines.append(f"    - {L('TÂCHE', 'TASK')} « {tgt} » → {_w52.get(m['status'], m['status'])}{tail}{q}")
            # 9.4.61 — M60-01 : « Présenter l'avancement des cibles 2030 — réalisée » était restitué « les cibles 2030 sont
            # réalisées » ; une tâche réalisée ne dit rien de l'atteinte de son objet
            if any(m.get("status") == "DONE" for m in _m52):
                lines.append(L("    (Une TÂCHE réalisée (présenter, mesurer, auditer, chiffrer, préparer X…) ne signifie pas que X est "
                               "atteint, conforme ou terminé : reprends le verbe et l'objet de la tâche, jamais « X réalisé ».)",
                               "    (A completed TASK (present, measure, audit, quantify, prepare X…) does not mean that X is "
                               "achieved, compliant or finished: keep the task's verb and object, never \"X achieved\".)"))
            # 9.4.57 — M56-03 / §4.3 de la contre-recette : un abandon porte sur la TÂCHE citée, pas sur l'objet qu'elle concerne
            if any(m.get("status") == "DROPPED" for m in _m52):
                lines.append(L("    (Un abandon porte sur la tâche citée, pas sur l'objet qu'elle concerne : abandonner une "
                               "clarification n'abandonne ni n'approuve le budget ou l'enveloppe visés ; une relance de la tâche "
                               "ne peut être que proposée.)",
                               "    (A dropped item concerns the cited task, not its object: dropping a clarification neither "
                               "cancels nor approves the budget concerned; restarting the task can only be proposed.)"))
    try:
        _pend57 = load_unresolved57(dossier_id, storage_dir)
        _now57 = [d.get("action", "") for d in (parse_brief_statuses(brief_text) if brief_text else [])]
        _pend57 = [u for u in _pend57 if not any(_same_instruction57(u.get("action", ""), x) for x in _now57)]
    except Exception:
        _pend57 = []
    if _pend57:
        _w57 = {"DONE": L("réalisée", "completed"), "POSTPONED": L("reportée", "postponed"), "DROPPED": L("abandonnée", "dropped")}
        lines.append(L("• Instructions du dirigeant non rapprochées lors d'une séance précédente (contraintes à respecter tant "
                       "qu'elles ne sont ni précisées ni retirées ; ne pas les traiter comme nulles) :",
                       "• Leader's instructions not matched at a previous session (constraints to respect until clarified or "
                       "withdrawn; do not treat them as void):"))
        for u in _pend57[-8:]:
            tail = (f" {L('au', 'to')} {u['date']}" if u.get("status") == "POSTPONED" and u.get("date") else "")
            lines.append(f"    - {u.get('action')} → {_w57.get(u.get('status'), u.get('status'))}{tail} "
                         f"({L('déclarée le', 'declared on')} {u.get('declared_on', '')})")
    _human_rep52 = [s for s in _all51.values() if s.is_open() and getattr(s, "reported_by_leader52", False)]
    if _human_rep52:
        lines.append(L("• Reportées par décision du dirigeant (nouvelle échéance à respecter ; ne pas replanifier plus tôt) :",
                       "• Postponed by the leader's decision (new due date to respect; do not reschedule earlier):"))
        for s in _human_rep52[-8:]:
            lines.append(f"    - {s.action} — {L('reportée au', 'postponed to')} {getattr(s, 'reported_to52', '') or s.echeance}")
    if last_decision:
        # 9.4.60 — contre-recette du 11/10 (F59-03) : quand le dirigeant a ADOPTÉ une option, la ligne n'est plus
        # présentée comme « non décidée par le CoDIR » (deux messages contraires dans le même contexte) ; elle dit
        # l'adoption, et la recommandation N-1 n'est rappelée que comme origine.
        _adopt60 = latest_board_option60(dossier_id, storage_dir)
        if _adopt60[0]:
            lines.append(L(f"• Orientation ADOPTÉE par le dirigeant : option {_adopt60[0]} (le {_adopt60[1]}) — à appliquer ; "
                           f"son budget, son calendrier et ses modalités restent à arbitrer. Recommandation de l'analyse "
                           f"précédente, pour mémoire : {last_decision}",
                           f"• Orientation ADOPTED by the leader: option {_adopt60[0]} (on {_adopt60[1]}) — to apply; its "
                           f"budget, schedule and terms remain to be decided. Previous analysis recommendation, for the "
                           f"record: {last_decision}"))
        else:
            if _dec51:
                last_decision = (f"{last_decision} — {L('ADOPTÉE par le dirigeant', 'ADOPTED by the leader')} : "
                                 f"{_dec51[-1].get('text', '')} ({_dec51[-1].get('decided_on', '')})")
            # v62.13.9.4.50 — la « décision » enregistrée par le produit est l'ORIENTATION RECOMMANDÉE par l'analyse
            # précédente, pas un arbitrage du CoDIR (contre-recette du 30/09, C01) ; seules les décisions que le dirigeant
            # écrit dans son brief sont des décisions
            lines.append(L(f"• Orientation recommandée par l'analyse précédente (N-1), non décidée par le CoDIR : {last_decision}",
                           f"• Orientation recommended by the previous analysis (N-1), not decided by the CoDIR: {last_decision}"))
    if ecarts:
        lines.append(L("• Écarts de décision déjà observés (à expliciter si la décision change) :",
                       "• Decision changes already observed (explain if the decision shifts):"))
        for e in ecarts[-4:]:
            lines.append(f"    - {e.get('from','')} → {e.get('to','')}")
    return "\n".join(lines)


def build_history_snapshot(dossier_id: str, authority=None,
                           storage_dir: Optional[str] = None,
                           lang: str = "fr") -> Dict[str, Any]:
    """Gate 15 (P0-2) — LE snapshot point-in-time UNIQUE : toutes les
    surfaces d'un run (moteur, Markdown, DOCX, PPTX, UI, prior context,
    décisions/écarts, relances) consomment CE même objet, jamais des
    reconstructions séparées. Pipeline canonique :
      events_as_of → order_events_for_state → derive_state (état)
      events_as_of → ordre RÉEL d'exécution (timeline : inclusion
      filtrée par l'autorité, ordre chronologique réel conservé).
    authority None → vue latest."""
    snap: Dict[str, Any] = {
        "authority": (authority.isoformat()
                      if isinstance(authority, date) else (authority or "")),
        "open_actions": [], "buckets": {}, "timeline": [],
        "decision_history": [], "decision_ecarts": [], "markdown": "",
        "semantic_quarantine_count": 0,
    }
    try:
        auth = authority
        if isinstance(auth, str) and auth:
            try:
                auth = date.fromisoformat(auth[:10])
            except Exception:
                auth = None
        _raw_events = events_as_of(load_events(dossier_id, storage_dir), auth)
        _kept_events, _quarantined_events = _partition_semantic_events(_raw_events)
        snap["semantic_quarantine_count"] = len(_quarantined_events)
        snap["open_actions"] = open_actions(dossier_id, auth, storage_dir)
        snap["buckets"] = buckets(dossier_id, auth, storage_dir)
        snap["timeline"] = dossier_timeline(dossier_id, storage_dir,
                                            as_of=auth)
        snap["decision_history"] = decision_history(dossier_id, storage_dir,
                                                    as_of=auth)
        snap["decision_ecarts"] = decision_ecarts(dossier_id, storage_dir,
                                                  as_of=auth)
        snap["markdown"] = to_markdown(dossier_id, lang=lang, as_of=auth,
                                       storage_dir=storage_dir)
    except Exception:
        pass
    return snap


def rebuild_history_view(dossier_id: str, lang: str = "fr",
                         as_of: Optional[date] = None,
                         storage_dir: Optional[str] = None) -> Dict[str, Any]:
    """Cycle C (F.5.2.1) — reconstruit les clés de VUE de codir_history depuis le
    stockage (après une opération manuelle de pilotage : clôture/report/réouverture).
    Permet à l'UI de rafraîchir l'affichage sans relancer un run complet. Renvoie
    open_actions / reapparues / timeline / decision_ecarts / markdown. Fail-open."""
    try:
        # Gate 15 — la vue est le snapshot central, jamais des
        # reconstructions séparées (timeline/écarts recevaient la vue
        # LATEST quelle que soit l'autorité : call-sites fermés).
        snap = build_history_snapshot(dossier_id, as_of, storage_dir, lang)
        return {
            "open_actions":    [a.__dict__ for a in snap["open_actions"]],
            "reapparues":      [a.__dict__ for a in
                                snap["buckets"].get("reapparues", [])],
            "timeline":        snap["timeline"],
            "decision_ecarts": snap["decision_ecarts"],
            "markdown":        snap["markdown"],
        }
    except Exception:
        return {}


def to_markdown(dossier_id: str, lang: str = "fr", as_of: Optional[date] = None,
                storage_dir: Optional[str] = None) -> str:
    """Vue multi-séances en markdown : ouvertes (avec relances + retard) + frise."""
    opens = open_actions(dossier_id, as_of, storage_dir)
    # Gate 15 — inclusion filtrée par l'autorité (l'ordre de la frise
    # reste l'ordre RÉEL d'exécution des runs admissibles).
    timeline = dossier_timeline(dossier_id, storage_dir, as_of=as_of)
    if not opens and not timeline:
        return ""
    h_open = ("| Sujet | Action | Porteur | Échéance | Statut | Relances | Prochaine revue |"
              if lang == "fr" else
              "| Topic | Action | Owner | Deadline | Status | Follow-ups | Next review |")
    sep = "|---|---|---|---|---|---|---|"
    lines = ["### " + ("Registre multi-séances — actions ouvertes" if lang == "fr"
                       else "Multi-session register — open actions"), h_open, sep]
    for s in opens:
        _rv = s.prochaine_revue or "—"
        if lang == "en" and _rv == "Prochain CoDIR":
            _rv = "Next CoDIR"
        _st = action_status_display(s.__dict__, lang)
        cells = [s.sujet or "—", s.action or "—", s.porteur or "—",
                 s.echeance or "—", _st, str(s.relance_count), _rv]
        lines.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
    if timeline:
        lines.append("")
        lines.append("### " + ("Historique CoDIR → CoDIR" if lang == "fr"
                              else "CoDIR → CoDIR history"))
        head = ("| Run | Date | Nouvelles | Reconduites | Relances | Reportées | Clôturées |"
                if lang == "fr" else
                "| Run | Date | New | Carried | Follow-ups | Reported | Closed |")
        lines += [head, "|---|---|---|---|---|---|---|"]
        for t in timeline:
            lines.append("| {run_id} | {run_date} | {created} | {carried} | "
                         "{relance} | {reported} | {closed} |".format(**t))
    return "\n".join(lines)


__all__ = [
    "RegisterEvent", "ActionState", "compute_dossier_id", "normalize_action_key",
    "append_events", "load_events", "derive_state", "ingest_run",
    "close_action", "reopen_action", "report_action", "open_actions", "dossier_timeline",
    "decision_history", "decision_ecarts", "buckets", "to_markdown",
    "format_prior_context_block", "rebuild_history_view",
    "build_history_snapshot", "events_as_of", "order_events_for_state",
    "parse_due_date_47", "govern_action_status_row",
    "govern_accounting_commitment_text", "action_status_display",
    "canonicalize_action_status", "reconcile_reappeared_rows",
    "make_run_id",
    "STATUT_A_LANCER", "STATUT_EN_COURS", "STATUT_REPORTEE", "STATUT_CLOTUREE",
    "STATUT_A_ARBITRER", "STATUT_EN_RETARD",
    "USAGE_BOARD_SAFE", "USAGE_NON_BOARD_SAFE", "USAGE_INDICATIF",
    "DEFAULT_STORAGE_DIR", "SCHEMA_VERSION",
]


def make_run_id(societe: str, run_date: str = "") -> str:
    """Run ID UNIQUE par run (P0-2 F.5.1). Deux runs de la même société le même
    jour ne collisionnent jamais : on mêle un horodatage haute résolution et un
    uuid court. run_date (jour) sert à l'affichage/au retard, pas à l'identité."""
    import uuid
    seed = f"{societe or 'unknown'}|{run_date}|{_now_iso()}|{uuid.uuid4().hex}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


# ── v62.13.9.4.50 — STATUTS DONNÉS PAR LE BRIEF (liste 9.4.49 bis, contre-recette du 30/09) ─────────────────────────
# Le brief du dirigeant est une VALIDATION HUMAINE : « … — réalisée le 15/10/2026 », « … reportée au 31/03/2027 »,
# « … abandonnée ». Ces statuts s'appliquent aux actions ENCORE OUVERTES qui portent la même intention (mêmes racines
# que le registre) ; le bloc de continuité injecté par le produit n'est jamais relu comme une déclaration.
_BRIEF_DONE50 = re.compile(r"(?i)\b(?:r[ée]alis[ée]e?s?|termin[ée]e?s?|achev[ée]e?s?|livr[ée]e?s?|cl[ôo]tur[ée]e?s?|done|completed|delivered)\b")
_BRIEF_POSTPONED50 = re.compile(r"(?i)\b(?:report[ée]e?s?|d[ée]cal[ée]e?s?|postponed|deferred)\b(?:\s+(?:au|à|to|until)\s+"
                                r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}))?")
_BRIEF_DROPPED50 = re.compile(r"(?i)\b(?:abandonn[ée]e?s?|annul[ée]e?s?|retir[ée]e?s?|dropped|cancell?ed)\b")


_ITEM_SPLIT50 = re.compile(r"(?:^|(?<=[.;:]))\s*[—–]\s+(?=[A-ZÀ-Ýa-zà-ÿ])")
_BOARD_DECISION50 = re.compile(r"(?i)\b(?:d[ée]cision\s+du\s+(?:conseil|CoDIR|comit[ée])|le\s+conseil|board(?:\s+decision)?)\b[^.]{0,80}?"
                               r"\boption\s*(\d)\b[^.]{0,30}?\b(?:retenue|choisie|valid[ée]e|adopt[ée]e|approuv[ée]e|selected|approved|chosen)")


def _status_items50(line: str) -> List[str]:
    """Une ligne qui porte plusieurs déclarations (copie à la souris : retours à la ligne perdus) est découpée en items,
    un par « — … », pour que chaque statut soit lu (recette du 02/10/2026)."""
    parts = [x.strip() for x in _ITEM_SPLIT50.split(line) if x and x.strip()]
    return parts or [line]


def parse_board_decision(brief: str) -> str:
    """« Décision du conseil du 01/10/2026 : option 2 retenue » → "2" ; "" sinon."""
    m = _BOARD_DECISION50.search(str(brief or ""))
    return m.group(1) if m else ""


def parse_brief_statuses(brief: str) -> List[dict]:
    """[{"action", "status": DONE|POSTPONED|DROPPED, "date"}] — lignes du brief qui déclarent un statut d'action."""
    out: List[dict] = []
    in_block = False
    _lines50 = []
    # 9.4.64 — recette du 15/10 : une déclaration coupée sur deux lignes (« — Reconstituer la passerelle … — DAF —⏎
    #     réalisée le 01/10/2026. », texte copié d'un courriel ou d'un document) était lue ligne à ligne : le statut tombait
    # sur la ligne de continuation, l'action devenait « DG avec DAF » ou n'était jamais close. Une ligne indentée qui ne
    # commence pas une nouvelle puce prolonge la déclaration précédente.
    _joined64: List[str] = []
    for raw in str(brief or "").splitlines():
        s = raw.strip()
        if (_joined64 and s and raw[:1] in (" ", "\t") and not re.match(r"[•\-–—*]\s", s)
                and re.match(r"\s*[•\-–—*]\s", _joined64[-1])
                and not re.search(r"(?i)\b(?:r[ée]alis[ée]e?s?|report[ée]e?s?|abandonn[ée]e?s?|maintenu(?:e?s?)|done|postponed|"
                                  r"dropped|kept)\b[^—–]*\.?\s*$", _joined64[-1])
                and not re.match(r"(?i)(?:d[ée]cision\s+du\s+conseil|board\s+decision|▌|[ÉE]tat\s+des\s+actions|state\s+of)", s)):
            _joined64[-1] = _joined64[-1].rstrip() + " " + s
        else:
            _joined64.append(raw)
    for raw in _joined64:
        _items = _status_items50(raw.strip()) if raw.strip() else [raw]
        # une ligne d'une seule déclaration garde sa forme d'origine (indentation comprise : le bloc injecté est
        # reconnu par elle) ; une ligne qui en porte plusieurs est découpée
        _lines50.extend([raw] if len(_items) <= 1 else _items)
    for raw in _lines50:
        line = raw.strip()
        if not line:
            continue
        if re.match(r"(?i)(?:CONTEXTE\s+[—-]\s+CoDIR\s+PR[ÉE]C[ÉE]DENT|CONTEXT\s+[—-]\s+PREVIOUS\s+CoDIR)", line):
            in_block = True
            continue
        if in_block:
            if raw.startswith(("  ", "\t")) or re.match(r"[•\-–—]\s", line):
                continue
            in_block = False
        status = date_ = ""
        mp = _BRIEF_POSTPONED50.search(line)
        if _BRIEF_DROPPED50.search(line):
            status = "DROPPED"
        elif mp:
            status, date_ = "POSTPONED", (mp.group(1) or "")
        elif _BRIEF_DONE50.search(line):
            status = "DONE"
            # 9.4.51 — la date de réalisation déclarée (« réalisée le 01/10/2026 ») est conservée (contre-recette du 03/10)
            _md51 = re.search(r"(?i)\b(?:r[ée]alis[ée]e?s?|termin[ée]e?s?|achev[ée]e?s?|livr[ée]e?s?|cl[ôo]tur[ée]e?s?|done|completed|delivered)"
                              r"\s+(?:le|on|au)?\s*(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})", line)
            if _md51:
                date_ = _md51.group(1)
        if not status:
            continue
        # 9.4.52 — recette du 05/10 : « — Réaliser un stress-test … — abandonnée » était coupé dès « Réalis(er) », pris pour
        # le statut « réalisée » : le séparateur ne reconnaît plus que des PARTICIPES (réalisée, reportée, abandonnée…)
        _parts50 = re.split(r"(?i)\s*[—–:\-]\s*(?:action\s+)?(?:d[ée]j[àa]\s+)?(?:r[ée]alis[ée]e?s?|termin[ée]e?s?|achev[ée]e?s?|"
                            r"livr[ée]e?s?|cl[ôo]tur[ée]e?s?|report[ée]e?s?|d[ée]cal[ée]e?s?|abandonn[ée]e?s?|annul[ée]e?s?|"
                            r"retir[ée]e?s?|maintenu(?:e?s?)|done|complet(?:ed|e)|delivered|postponed|deferred|dropped|cancell?ed|kept)\b", line)
        if len(_parts50) < 2:
            continue      # v62.13.9.4.50 — une phrase (« les actions ont été réalisées… ») n'est pas une déclaration de statut
        action = _parts50[0]
        action = re.sub(r"^[•\-–—*\s]+", "", action).strip(" .;:—–-")
        # 9.4.53 — recette Mac du 05/10 (M02) : « … au comité d'audit — Directeur RSE — réalisée » gardait le PORTEUR dans
        # l'action ; ses mots faisaient tomber la correspondance sous le seuil. Le dernier segment « — … » court (≤ 6 mots)
        # qui suit l'action est le porteur, pas l'intention.
        _segs53 = [x.strip() for x in re.split(r"\s+[—–]\s+", action) if x.strip()]
        if len(_segs53) >= 2 and len(_segs53[-1].split()) <= 6 and len(_segs53[0].split()) >= 3:
            action = " — ".join(_segs53[:-1]).strip()
        if len(action.split()) >= 3:
            out.append({"action": action, "status": status, "date": date_})
    return out


_BRIEF_DONE51: List[dict] = []


def set_brief_declarations51(brief: str) -> None:
    """9.4.51 — mémorise, pour la durée du run, les réalisations que le dirigeant déclare dans son brief : un agent qui
    les rapporte (« présentation RSE réalisée d'après le brief ») n'est plus rétrogradé « À lancer — complétion non
    prouvée » (contre-recette du 03/10/2026 : l'explication contredisait le brief humain)."""
    global _BRIEF_DONE51
    try:
        _BRIEF_DONE51 = [d for d in parse_brief_statuses(brief) if d.get("status") == "DONE"]
    except Exception:
        _BRIEF_DONE51 = []


def _brief_declared_done51(action: str) -> Optional[dict]:
    if not _BRIEF_DONE51 or not action:
        return None
    import types as _t
    for d in _BRIEF_DONE51:
        prior = {"k": _t.SimpleNamespace(action=action, echeance="", is_open=lambda: True)}
        if _same_intention50(d["action"], "", prior):
            return d
    return None


def _undeclared_parts55(action_text: str, declared: str) -> list:
    """Parties d'une action composite (« A ; B ; C ») que la déclaration du dirigeant ne vise PAS. Rien n'est découpé si
    l'action n'a qu'une intention, si la déclaration ne vise clairement aucune partie, ou si elle les vise toutes."""
    try:
        from patches.agenda_register import _token_set as _ts
    except Exception:
        return []
    parts = [x.strip(" .;—–-") for x in re.split(r"\s*;\s*|\s+\|\s+", str(action_text or "")) if x.strip(" .;—–-")]
    if len(parts) < 2:
        # 9.4.61 — contre-recette du 12/10 (M60-02) : « Chiffrer l'enveloppe SI (…) ET rattacher le budget commercial… » —
        # un « et » suivi d'un second VERBE à l'infinitif, absent de la déclaration, ouvre un second travail ; « préparer
        # le budget et son phasage » reste une seule intention (pas de verbe après « et »)
        _decl_w = {w.lower() for w in re.findall(r"[\wÀ-ÿ'’-]+", str(declared or ""))}
        _segs = re.split(r"\s+et\s+(?=(?:[a-zà-ÿœ]+(?:er|ir|re))\b)", str(action_text or ""), flags=re.I)
        if len(_segs) >= 2:
            _merged = [_segs[0]]
            for _sg in _segs[1:]:
                _vb = (re.match(r"\s*([\wÀ-ÿœ'’-]+)", _sg) or [None, ""])[1].lower()
                if _vb in _decl_w or len(_sg.split()) < 3:
                    _merged[-1] = _merged[-1] + " et " + _sg
                else:
                    _merged.append(_sg)
            parts = [x.strip(" .;—–-") for x in _merged if x.strip(" .;—–-")]
    parts = [x for x in parts if len(x.split()) >= 3]
    if len(parts) < 2:
        return []
    mine = _ts(declared)
    if not mine:
        return []
    scores = [(len(mine & _ts(x)) / max(1, len(_ts(x) | set())) if _ts(x) else 0.0, x) for x in parts]
    cover = [len(mine & _ts(x)) / max(1, len(_ts(x))) for x in parts]
    best = max(range(len(parts)), key=lambda i: cover[i])
    if cover[best] < 0.5:
        return []                                   # la déclaration ne vise clairement aucune partie : rien n'est découpé
    rest = [parts[i] for i in range(len(parts)) if i != best and cover[i] < 0.5]
    return rest


def apply_brief_statuses(dossier_id: str, brief: str, run_id: str, run_date: str,
                         storage_dir: Optional[str] = None, analysis_date: str = "") -> List[RegisterEvent]:
    """Applique les statuts du brief aux actions ouvertes de même intention ; renvoie les événements écrits."""
    decl = parse_brief_statuses(brief)
    _board50 = parse_board_decision(brief)
    if not decl and not _board50:
        return []
    if _board50:
        _bd = re.search(r"(?i)d[ée]cision\s+du\s+(?:conseil|CoDIR|comit[ée])\s+du\s+(\d{1,2}/\d{1,2}/\d{4})", str(brief or ""))
        record_human_decision(dossier_id, f"Option {_board50} retenue", (_bd.group(1) if _bd else str(analysis_date or run_date)),
                              run_id=run_id, storage_dir=storage_dir)
    auth = None
    try:
        auth = date.fromisoformat(str(analysis_date or run_date)[:10])
    except Exception:
        auth = None
    prior = derive_state(order_events_for_state(events_as_of(load_events(dossier_id, storage_dir), auth)))
    events: List[RegisterEvent] = []
    for d in decl:
        _rk52 = _rank_intentions52(d["action"], prior)
        if len(_rk52) > 1 and _rk52[0][0] - _rk52[1][0] < 0.1:
            continue                              # 9.4.52 — ambiguë : jamais de fusion approximative ; signalée au CR
        key = _rk52[0][1] if _rk52 else ""
        if not key:
            continue
        if d["status"] == "POSTPONED":
            ev = RegisterEvent(event_type=EV_REPORTED, action_key=key, run_id=run_id, run_date=run_date,
                               dossier_id=dossier_id, echeance=d.get("date") or "", statut=STATUT_REPORTEE,
                               status_origin="BRIEF_DECLARATION", status_evidence_ref="brief",
                               note="Reportée par le brief du dirigeant.")
        else:
            # 9.4.51 — nature (réalisée / abandonnée) et date de réalisation CONSERVÉES (contre-recette du 03/10 : statut
            # terminal générique « Clôturée », completed_at vide)
            _dt = str(d.get("date") or "")
            _m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", _dt)
            _iso = f"{_m.group(3)}-{int(_m.group(2)):02d}-{int(_m.group(1)):02d}" if _m else ""
            ev = RegisterEvent(event_type=EV_CLOSED, action_key=key, run_id=run_id, run_date=run_date,
                               dossier_id=dossier_id, analysis_date=str(analysis_date or run_date),
                               statut=(STATUT_REALISEE if d["status"] == "DONE" else STATUT_ABANDONNEE),
                               status_origin="BRIEF_DECLARATION", completed_at=(_iso if d["status"] == "DONE" else ""),
                               status_evidence_ref="brief",
                               note=((f"Réalisée le {_dt} selon le brief du dirigeant." if _dt else "Réalisée selon le brief du dirigeant.")
                                     if d["status"] == "DONE" else "Abandonnée selon le brief du dirigeant."))
        # 9.4.55 — contre-recette ChatGPT du 07/10 (M01) : « Présenter l'avancement des cibles d'émissions 2030 au comité
        # d'audit ; relecture juridique de toute communication RSE » — la déclaration « présentation RSE réalisée » fermait
        # aussi la relecture juridique. Une action COMPOSITE (intentions séparées par « ; ») n'est close que pour la partie
        # déclarée : les autres parties restent ouvertes, comme actions distinctes, avec le porteur et l'échéance d'origine.
        try:
            _rest55 = _undeclared_parts55(getattr(prior.get(key), "action", "") or "", d["action"])
        except Exception:
            _rest55 = []
        for _part55 in _rest55:
            # une partie nominale (« relecture juridique de… ») reçoit une tête d'action, sinon le filtre des actions la
            # mettrait en quarantaine et elle disparaîtrait du registre
            try:
                from patches.agenda_register import is_semantic_action as _isa55
                if not _isa55(_part55):
                    _part55 = "Mener à bien : " + _part55[:1].lower() + _part55[1:]
            except Exception:
                pass
            _k55 = normalize_action_key(_part55)
            if _k55 and _k55 != key and _k55 not in prior:
                events.append(RegisterEvent(event_type=EV_CREATED, action_key=_k55, action=_part55, run_id=run_id,
                                            run_date=run_date, dossier_id=dossier_id, analysis_date=str(analysis_date or run_date),
                                            porteur=str(getattr(prior.get(key), "porteur", "") or ""),
                                            echeance=str(getattr(prior.get(key), "echeance", "") or ""),
                                            statut=str(getattr(prior.get(key), "statut", "") or "À lancer"),
                                            note="Partie d'une action composite non couverte par la déclaration du dirigeant."))
        events.append(ev)
        prior.pop(key, None)                      # une action ne reçoit qu'un statut par brief
    if _board50:
        # « Décision du conseil : option 2 retenue » tranche les actions « arbitrer l'option 1, 2 ou 3 » (recette du 02/10)
        for key, s in list(prior.items()):
            txt = str(getattr(s, "action", "") or key).lower()
            # 9.4.51 — contre-épreuve ChatGPT du 03/10 : « option 2 retenue » fermait aussi « arbitrer le budget de l'option 2 ».
            # Seul un CHOIX ENTRE OPTIONS est tranché : au moins deux options nommées, ou « choisir/choix entre / quelle option ».
            _nums = set(re.findall(r"\b(?:option\s*)?([1-9])\b(?=[^.]{0,40}\boption|\s*(?:,|ou|or|et|/)\s*(?:option\s*)?[1-9]\b)", txt))
            # 9.4.53 — contre-recette ChatGPT du 06/10 (M01, bloquant d'autorité) : « lancer l'instruction de l'option 3 … EN
            # PARALLÈLE de l'option 2 » nommait deux options et a été close par « option 2 retenue ». Deux numéros ne font pas
            # un choix : seule une tournure EXPLICITE de choix est tranchée par la décision du conseil ; une action menée en
            # parallèle, en complément ou en repli de l'option retenue, son budget ou sa mise en œuvre ne le sont jamais.
            _explicit_choice53 = bool(re.search(
                r"(?:choisir|choix|arbitr\w*|trancher|d[ée]cider)\s+entre|quelle\s+(?:option|orientation)|which\s+option|"
                r"choose\s+between|choix\s+(?:d['’]|de\s+l['’]|de\s+la\s+|des\s+)(?:option|orientation)|"
                r"choisir\s+(?:l['’]|une\s+|son\s+)(?:option|orientation)|(?:option|orientation)\s+(?:strat[ée]gique\s+)?[àa]\s+retenir|"
                r"retenir\s+(?:une|l['’])\s*(?:option|orientation)\s+(?:parmi|entre)|option\s+strat[ée]gique\s+[1-9]\s*,\s*[1-9]\s+ou\s+[1-9]",
                txt))
            _parallel53 = bool(re.search(r"\ben\s+parall[èe]le\b|\ben\s+compl[ée]ment\b|\ben\s+plus\s+de\b|\ben\s+repli\b|"
                                         r"\bplan\s+b\b|\bfallback\b|\bin\s+parallel\b|\balongside\b", txt))
            _choice = _explicit_choice53 and not _parallel53 and \
                not re.search(r"(?i)\b(?:budget|enveloppe|mise\s+en\s+[œo]euvre|d[ée]ploiement|calendrier|plafond)\b", txt)
            if s.is_open() and _choice and re.search(r"arbitr|choisir|choix|retenir|trancher|d[ée]cider|choose|select", txt):
                events.append(RegisterEvent(event_type=EV_CLOSED, action_key=key, run_id=run_id, run_date=run_date,
                                            dossier_id=dossier_id, analysis_date=str(analysis_date or run_date),
                                            statut=STATUT_CLOTUREE, status_origin="BRIEF_DECLARATION", status_evidence_ref="brief",
                                            note=f"Tranchée par le conseil : option {_board50} retenue (brief du dirigeant)."))
                prior.pop(key, None)
    if events:
        append_events(dossier_id, events, storage_dir)
    return events
