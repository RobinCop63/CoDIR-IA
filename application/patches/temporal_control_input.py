# -*- coding: utf-8 -*-
"""Correctif TCR-v10 — TemporalControlInput : l'ENTRÉE TEMPORELLE COURANTE,
capturée AVANT toute transformation d'interface, et AUTORITÉ EFFECTIVE de
bout en bout.

Racine commune des trois P0 du verdict v9 : l'objet existait mais n'était
pas l'autorité. Trois règles le rendent effectif :

  1. PRÉSENCE DE CLÉ AVANT NON-VACUITÉ. Une clé de widget présente est une
     information de l'utilisateur, même vide : il vient d'effacer le champ.
     Une clé ABSENTE seule autorise le repli (Settings, copie canonique).
  2. AUCUNE NORMALISATION AVANT CLASSIFICATION. L'indentation est une
     information structurelle (masque code) : elle survit jusqu'au parser.
  3. UNE SEULE AUTORITÉ STRUCTURÉE PAR RERUN. Quand la clé du widget de
     date est présente, Settings est RÉCONCILIÉ sur elle immédiatement —
     le pré-gate et le contexte final ne peuvent plus lire deux vérités.

    valeurs COURANTES des widgets  (jamais les copies du rerun d'avant)
    + pending A5 consommé
    → TemporalControlInput (frozen)
    → resolve_temporal_context(...) UNE fois
    → policy : autorise (ou non) tout effet externe
    → les pivots UI s'appliquent au business_text SEUL
    → le brief est assemblé DEPUIS cet objet, sans re-parsing
    → input_fingerprint vérifié jusqu'au moteur

Ordre de priorité des sources, du plus courant au plus ancien :

  date structurée : pending A5 → CLÉ widget (même vide) → Settings
  texte principal : CLÉ widget (…_ta, même vide) → clé canonique
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Optional, Tuple

# Clés d'état — widget (valeur COURANTE) puis canonique (rerun précédent).
MAIN_KEYS = {
    "terrain": ("bui_t_fr_ta", "bui_t_fr"),
    "equipe": ("bui_e_fr_ta", "bui_e_fr"),
}
# Frontières de canal — caractères de contrôle STX : ni saisissables
# dans un widget, ni produits par un assembleur. La sérialisation est
# donc décodable sans ambiguïté ni heuristique.
CONTROL_CHANNEL_MARK = "\x02TEMPORAL-CONTROL\x02"
LEGACY_CHANNEL_MARK = "\x02BUSINESS-NARRATIVE\x02"

def _sanitize_channel_marks(text: str) -> str:
    """Correctif TCR-v12 (verdict v11, P0-B) — les frontières de canal
    sont réservées au SÉRIALISEUR : elles sont retirées de toute matière
    saisie. Un texte collé qui contiendrait la marque ne peut donc pas
    déplacer une ligne de contrôle vers le canal narratif (ni l'inverse)
    et faire diverger le chemin typé du chemin sérialisé."""
    if not text:
        return text
    for mark in (CONTROL_CHANNEL_MARK, LEGACY_CHANNEL_MARK):
        if mark in text:
            text = text.replace(mark, " ")
    return text


STRUCTURED_PENDING_KEY = "codir_analysis_as_of_date_pending"
STRUCTURED_WIDGET_KEY = "codir_analysis_as_of_date"
SIGNED_CONTROL_PREFIX = "analysis_as_of_date = "

# Correctif TCR-v10 — MATIÈRE NARRATIVE COURANTE. Le contexte temporel est
# résolu UNE seule fois, au pré-gate : son entrée doit donc couvrir tout ce
# que l'ancien préflight final lisait dans le brief assemblé — sinon une
# date legacy déposée dans un champ secondaire cesserait de produire sa
# candidate confirmable (rang 3). Table EXPLICITE canonique → clé widget :
# la convention de nommage de l'UI est irrégulière (bui_e_societe/bui_e_soc),
# une dérivation par suffixe serait fausse. `None` = champ sans widget propre.
NARRATIVE_KEYS = {
    "terrain": (
        ("bui_t_sit", None),
        ("bui_t_q1", "bui_t_q1_ti"),
        ("bui_t_soc", "bui_t_soc_ti"),
        ("bui_t_siren", "bui_t_siren_ti"),
        ("bui_t_intl_reg", "bui_t_intl_reg_ti"),
    ),
    "equipe": (
        ("bui_e_societe", "bui_e_soc"),
        ("bui_e_secteur", "bui_e_sec"),
        ("bui_e_taille", "bui_e_tai"),
        ("bui_e_geo", "bui_e_geo_ti"),
        ("bui_e_siren", "bui_e_siren_ti"),
        ("bui_e_sit", "bui_e_sit_ta"),
        ("bui_e_declencheur", "bui_e_decl_ti"),
        ("bui_e_q1", "bui_e_q1_ti"),
        ("bui_e_q2", "bui_e_q2_ti"),
        ("bui_e_deadline", "bui_e_dl_ti"),
        ("bui_e_echec", "bui_e_echec_ta"),
        ("bui_e_kpi_com", "bui_e_kpi_com_ta"),
        ("bui_e_kpi_fin", "bui_e_kpi_fin_ta"),
        ("bui_e_kpi_sc", "bui_e_kpi_sc_ta"),
        ("bui_e_kpi_rh", "bui_e_kpi_rh_ta"),
        ("bui_e_decisions", "bui_e_dec_ta"),
        ("bui_e_contraintes", "bui_e_con_ta"),
        ("bui_e_zh", "bui_e_zh_ta"),
    ),
}

_MISSING = object()


class TemporalControlInputError(RuntimeError):
    """Panne du producteur de l'entrée temporelle courante.

    N'est JAMAIS convertie en brief live : les consommateurs la traduisent
    en BLOCKED_ERROR (contrat « la panne de la frontière de vérité ferme
    la porte »).
    """


@dataclass(frozen=True)
class TemporalControlInput:
    """Instantané immuable de l'entrée temporelle d'une session."""

    ui_mode: str = "terrain"
    raw_main_text: str = ""
    structured_date: str = ""
    control_lines: Tuple[str, ...] = field(default_factory=tuple)
    business_text: str = ""
    narrative_text: str = ""
    source_widget_key: str = ""
    structured_widget_key: str = ""
    input_fingerprint: str = ""

    def as_control_snapshot(self) -> str:
        # ⚠ HÉRITÉ (pré-v11) — NE PAS utiliser pour DÉCIDER : cette forme
        # est APLATIE (date structurée + champ principal en une chaîne) et
        # ne porte aucune frontière de canal. L'entrée de décision est
        # `as_authority_text()` (sérialisation typée) ou, mieux, l'objet
        # lui-même : `resolve_temporal_context(temporal_input=...)`.
        # Conservée parce que les batteries permanentes v10 l'exercent.
        """Texte canonique de la ZONE DE CONTRÔLE courante.

        La date structurée courante y est portée comme ligne de contrôle
        signée : le pré-gate voit donc la saisie du rerun EN COURS, y
        compris une valeur mal formée qui doit bloquer (fail-closed),
        sans dépendre de Settings, écrit plus tard dans le script.
        Sans date structurée, le texte principal brut est rendu TEL QUEL —
        indentation comprise (correctif TCR-v10, finding P1-02).
        """
        if self.structured_date:
            return (SIGNED_CONTROL_PREFIX + self.structured_date + "\n"
                    + self.raw_main_text).rstrip()
        return self.raw_main_text

    @property
    def contractual_text(self) -> str:
        """CANAL DE CONTRÔLE — les seules sources qui peuvent produire une
        autorité directe : la date structurée COURANTE (rang 1, portée
        comme ligne signée pour qu'aucun appelant ne puisse la perdre en
        route) et les lignes de labels signés en tête du champ PRINCIPAL
        (rang 2). Rien d'autre n'entre jamais dans ce canal."""
        lines = []
        if self.structured_date:
            lines.append(SIGNED_CONTROL_PREFIX + self.structured_date)
        lines.extend(self.control_lines)
        return "\n".join(lines)

    @property
    def legacy_text(self) -> str:
        """CANAL MÉTIER/NARRATIF — contenu du champ principal après les
        lignes de contrôle, plus tous les champs secondaires. Ne peut
        produire qu'une CANDIDATE confirmable (rang 3), jamais une
        autorité directe, quelle que soit sa formulation."""
        parts = [x for x in (self.business_text, self.narrative_text) if x]
        return "\n".join(parts)

    def as_authority_text(self) -> str:
        """Entrée de LA résolution unique du rerun — SÉRIALISATION TYPÉE.

        Correctif TCR-v11 (verdict v10, P0) : les deux canaux ne sont plus
        aplatis en une chaîne unique. Ils sont sérialisés avec une
        frontière EXPLICITE et non ambiguë (caractères de contrôle STX,
        impossibles à saisir dans un widget) que le résolveur redécoupe
        exactement avant de décider. Aucun re-parsing global ne traverse
        cette frontière : un champ narratif ne peut donc plus devenir un
        label contractuel, même lorsque le champ principal est vide.

        Le chemin typé `resolve_temporal_context(temporal_input=...)` est
        équivalent et préférable ; cette sérialisation existe pour que
        TOUT appelant historique par chaîne hérite de la même décision à
        deux canaux.
        """
        # (import paresseux : temporal_context importe ce module)
        try:
            from patches.temporal_context import (
                TEMPORAL_INPUT_FAILURE_SENTINEL as _sent)
        except Exception:
            _sent = "\x00codir:temporal-control-input-failure\x00"
        if self.raw_main_text and _sent in self.raw_main_text:
            return self.raw_main_text
        return (CONTROL_CHANNEL_MARK + "\n"
                + _sanitize_channel_marks(self.contractual_text)
                + "\n" + LEGACY_CHANNEL_MARK + "\n"
                + _sanitize_channel_marks(self.legacy_text))

    # ── États d'entrée distincts (verdict v10, P1-1) ──────────────────
    def has_temporal_control(self) -> bool:
        """Une autorité temporelle explicite est-elle saisie ?"""
        return bool(self.structured_date or self.control_lines)

    def has_business_input(self) -> bool:
        """De la matière exploitable est-elle saisie, fil rouge ou non ?"""
        return bool(self.business_text or self.narrative_text)

    def is_run_ready(self) -> bool:
        return self.has_business_input() or self.has_temporal_control()

    def is_empty(self) -> bool:
        """VIDE = aucun canal renseigné. Un mode Équipe dont le fil rouge
        est vide mais dont la société, la situation ou Q1 sont remplies
        n'est PAS vide (il fermait à tort les aperçus)."""
        return not self.is_run_ready()


def _key_present(state: Any, key: str) -> bool:
    """La CLÉ existe-t-elle dans l'état — indépendamment de sa valeur ?"""
    try:
        return key in state
    except Exception:
        pass
    try:
        return state.get(key, _MISSING) is not _MISSING
    except Exception:
        return False


def _read_current(state: Any, keys) -> Tuple[str, str]:
    """PREMIÈRE CLÉ PRÉSENTE dans l'ordre donné — sa valeur, même vide.

    Correctif TCR-v10 (finding P0-02) : remplace `_first_present`, qui
    retenait la première valeur NON VIDE et confondait donc « clé absente »
    (rien à dire, on peut se replier) avec « clé présente et vidée »
    (l'utilisateur vient d'effacer le champ — c'est une information).
    """
    for key in keys:
        if not _key_present(state, key):
            continue
        try:
            value = state.get(key, "")
        except Exception:
            value = ""
        if not isinstance(value, str):
            value = "" if value is None else str(value)
        return value, key
    return "", (keys[-1] if keys else "")


def _normalize_main(text: str) -> str:
    """Lignes vides de tête et blancs de fin UNIQUEMENT.

    L'indentation de la première ligne est structurelle (masque code) :
    la retirer AVANT la classification promeut un extrait de code en champ
    contractuel (finding P1-02). Même normalisation que les assembleurs.
    """
    return (text or "").lstrip("\n\r").rstrip()


# Clés d'état qui ne sont PAS de la matière saisie (navigation, drapeaux
# internes) : seules exclusions du balayage exhaustif ci-dessous.
_NON_NARRATIVE_KEYS = frozenset((
    "bui_mode", "bui_eq_step", "bui_prefilled", "bui_t_step",
    "bui_e_sc_override",
))


def _sweep_unclassified(state: Any, mode: str) -> tuple:
    """Correctif TCR-v12 (verdict v11, P0-A) — DÉNOMINATEUR MÉCANIQUE.

    NARRATIVE_KEYS est une table déclarée ; un champ ajouté à l'interface
    sans y être inscrit devenait un ANGLE MORT : sa saisie n'entrait dans
    aucun canal, donc une demande de backtest écrite là restait invisible
    au résolveur alors qu'elle atteignait le brief et les agents (cas
    `bui_e_tai`). Ce balayage capture, en plus des clés déclarées, TOUTE
    valeur texte de l'espace `bui_<mode>_*` non classée ailleurs : le
    canal narratif est exhaustif par construction, aujourd'hui et après
    n'importe quel ajout d'interface.
    """
    prefix = "bui_t_" if mode == "terrain" else "bui_e_"
    known = set(_NON_NARRATIVE_KEYS)
    known.update(MAIN_KEYS.get(mode, ()))
    for canonical, widget in NARRATIVE_KEYS.get(mode, ()):
        known.add(canonical)
        if widget:
            known.add(widget)
    try:
        all_keys = sorted(k for k in state.keys() if isinstance(k, str))
    except Exception:
        return ()
    # Une valeur encore égale au DÉFAUT de l'interface n'est pas une
    # saisie : la capturer ferait passer un formulaire vierge pour une
    # entrée réelle (et rouvrirait les aperçus à tort).
    defaults = {}
    try:
        import brief_ui as _bu_defaults
        defaults.update(getattr(_bu_defaults, "_TERRAIN_DEFAULTS", {}) or {})
        defaults.update(getattr(_bu_defaults, "_EQUIPE_DEFAULTS", {}) or {})
    except Exception:
        pass
    out = []
    for key in all_keys:
        if key in known or not key.startswith(prefix):
            continue
        try:
            value = state.get(key, "")
        except Exception:
            continue
        if (isinstance(value, str) and value.strip()
                and value != defaults.get(key)):
            out.append(value)
    return tuple(out)


def _narrative_text(state: Any, mode: str) -> str:
    """Matière narrative COURANTE, dans un ordre déterministe :
    clés déclarées d'abord, puis balayage exhaustif du reste."""
    chunks = []
    for canonical, widget in NARRATIVE_KEYS.get(mode, ()):
        keys = (widget, canonical) if widget else (canonical,)
        value, _ = _read_current(state, keys)
        # Correctif TCR-v11 (verdict v10) — l'indentation est une
        # information STRUCTURELLE (bloc de code) : elle survit à la
        # capture, comme dans le champ principal.
        value = (value or "").lstrip("\n\r").rstrip()
        if value:
            chunks.append(value)
    for extra in _sweep_unclassified(state, mode):
        if extra not in chunks:
            chunks.append(extra)
    return "\n".join(_sanitize_channel_marks(c) for c in chunks)


def build_temporal_control_input(state, settings: Optional[Any] = None,
                                 ui_mode: Optional[str] = None,
                                 reconcile_settings: bool = True
                                 ) -> TemporalControlInput:
    """Construit l'instantané depuis l'état de session Streamlit.

    Lecture PURE de l'interface : aucun widget créé, aucune écriture d'état
    de session. La seule écriture possible est la RÉCONCILIATION de
    `settings.analysis_as_of_date` sur la valeur courante du widget de date
    (correctif TCR-v10, finding P1-03) : elle ne crée aucune autorité — elle
    supprime la seconde, périmée, que le rerun aurait sinon laissée vivre
    jusqu'à ce que `render_analysis_date_field` la rattrape, trop tard, après
    le pré-gate. En mémoire seulement : aucun `save_settings`.
    """
    try:
        mode = ui_mode or state.get("bui_mode") or "terrain"
    except Exception:
        mode = ui_mode or "terrain"
    if mode not in MAIN_KEYS:
        mode = "terrain"

    raw_main, widget_key = _read_current(state, MAIN_KEYS[mode])
    raw_main = _sanitize_channel_marks(_normalize_main(raw_main))

    # ── Date structurée : pending A5 (injection à consommer) → CLÉ widget
    # (même vide) → Settings SEULEMENT si la clé du widget est absente.
    structured = ""
    structured_key = ""
    pending_value = ""
    if _key_present(state, STRUCTURED_PENDING_KEY):
        try:
            pending_value = str(state.get(STRUCTURED_PENDING_KEY, "") or "")
        except Exception:
            pending_value = ""
    if pending_value.strip():
        # Le pending est une INJECTION ponctuelle (adoption A5), jamais un
        # vide autoritaire : il est supprimé — non vidé — à sa consommation.
        structured, structured_key = pending_value, STRUCTURED_PENDING_KEY
    elif _key_present(state, STRUCTURED_WIDGET_KEY):
        structured, structured_key = _read_current(
            state, (STRUCTURED_WIDGET_KEY,))
    elif settings is not None:
        structured = str(getattr(settings, "analysis_as_of_date", "") or "")
        structured_key = "settings.analysis_as_of_date"
    structured = (structured or "").strip()

    # ── UNE SEULE AUTORITÉ STRUCTURÉE PAR RERUN.
    if (reconcile_settings and settings is not None
            and structured_key not in ("", "settings.analysis_as_of_date")):
        try:
            if getattr(settings, "analysis_as_of_date", None) != structured:
                settings.analysis_as_of_date = structured
        except Exception:
            pass

    try:
        from patches.mission_governance import split_temporal_control_prefix
        ctrl, business = split_temporal_control_prefix(raw_main)
    except Exception:
        ctrl, business = [], raw_main

    narrative = _narrative_text(state, mode)

    fingerprint = hashlib.sha256(
        ("\x1f".join((mode, structured, raw_main, narrative)))
        .encode("utf-8")
    ).hexdigest()

    return TemporalControlInput(
        ui_mode=mode,
        raw_main_text=raw_main,
        structured_date=structured,
        control_lines=tuple(ctrl),
        business_text=business,
        narrative_text=narrative,
        source_widget_key=widget_key,
        structured_widget_key=structured_key,
        input_fingerprint=fingerprint,
    )
