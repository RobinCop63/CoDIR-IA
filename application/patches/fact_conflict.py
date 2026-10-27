"""
patches/fact_conflict.py — v17.4.0-M6B-B1.0 (M6-B · B.1 · E4)

CONTRADICTIONS COMME OBJETS VISIBLES (D9, note M6-B v3 §7 & Partie II §6).

On passe d'un système qui « corrige » à un système qui VOIT la tension.
dossier industriel (composants) n'est pas seulement « deux faits de périmètres différents » : c'est
un CONFLIT APPARENT (235 M€ groupe vs 2,4 M€ social) qui doit être porté à
la surface. Un bon consultant ne veut pas qu'on cache la mauvaise donnée —
il veut voir que la tension a été détectée. B.1 DÉTECTE et pose l'objet ;
l'affichage riche est en B.4c.

Sévérités :
    hard          : même métrique + même période + même périmètre + même
                    entité, valeurs incompatibles (2 sources divergent)
    apparent      : même métrique, périmètres/entités différents
                    (dossier industriel (composants) 235 M€ groupe vs 2,4 M€ social)
    informational : différence structurelle ATTENDUE (holding 0 salarié vs
                    effectif groupe)

Verrou de matérialité (double garde) :
    same metric_canonical_id · période comparable · unit/scale normalisés ·
    relation de périmètre connue · ET (relative_delta > seuil OU
    absolute_delta > seuil).
    → pas d'alerte sur les petits écarts normaux ; ne PAS rater
      « 235 M€ vs 235 k€ » (unité mal comprise → reason=unit).

Anti sur-alerte — NON NÉGOCIABLE :
    role=holding + metric=HEADCOUNT + value≈0 → informational, JAMAIS
    hard/apparent. Deux valeurs d'ANNÉES PROUVÉES différentes ne sont pas
    un conflit (série temporelle normale). Un RN NÉGATIF n'est jamais, en
    soi, un conflit. On surface les vraies tensions, pas le bruit.

Complément à patches/contradiction_gate.py (F.6.7, détection TEXTE du CR) :
ici la détection est au niveau du FAIT STRUCTURÉ de la table probante.

100 % déterministe, sans dépendance pipeline → testable en isolation.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from patches.analysis_context import AnalysisContext

# ── Vocabulaire du contrat ────────────────────────────────────────────────────
SEV_HARD = "hard"
SEV_APPARENT = "apparent"
SEV_INFORMATIONAL = "informational"

REASON_PERIMETER = "perimeter"
REASON_PERIOD = "period"
REASON_UNIT = "unit"
REASON_SOURCE = "source"
REASON_EXTRACTION = "extraction"
REASON_SEMANTIC = "semantic"

RES_RETENU = "retenu"
RES_EXCLU = "exclu"
RES_SOUS_RESERVE = "affiche_sous_reserve"
RES_NON_RESOLU = "non_resolu"

# ── Seuils de matérialité (documentés, ajustables au débrief B.1) ────────────
REL_DELTA_MIN = 0.15          # 15 % d'écart relatif
ABS_DELTA_MIN = {             # plancher absolu par unité (valeurs NORMALISÉES)
    "CUR": 500_000.0,         # 500 k (euros/£/$ en base)
    "PERSONS": 50.0,
    "PCT": 5.0,
    "DAYS": 15.0,
    "RATIO": 0.5,
}
NOISE_FLOOR = {               # sous ce niveau, on ne compare même pas
    "CUR": 1_000.0,
    "PERSONS": 1.0,
}
# ×1000 / ×1e6 à ±2 % → suspicion d'unité mal comprise (M vs k)
_UNIT_MISREAD_FACTORS = (1e3, 1e6)
_UNIT_MISREAD_TOL = 0.02


@dataclass
class FactConflict:
    """L'objet conflit (contrat §7 / Partie II §6)."""
    metric_canonical_id: str
    competing_values: List[Dict[str, Any]] = field(default_factory=list)
    conflict_severity: str = SEV_INFORMATIONAL
    conflict_reason: str = REASON_SOURCE
    resolution: str = RES_NON_RESOLU
    user_visible_message: str = ""
    conflict_group_id: str = ""

    def to_journal_row(self) -> Dict[str, Any]:
        return {
            "role": "fact_conflict",
            "provider": "internal",
            "model": "fact_conflict_b1",
            "status": "OK",
            "conflict_group_id": self.conflict_group_id,
            "metric": self.metric_canonical_id,
            "severity": self.conflict_severity,
            "reason": self.conflict_reason,
            "resolution": self.resolution,
            "values": " vs ".join(
                f"{v.get('value')} [{v.get('perimeter')}·{v.get('entity') or '—'}"
                f"·{v.get('period_end') or v.get('period') or '—'}"
                f"·{v.get('canonical_role') or '—'}]"
                for v in self.competing_values),
            "message": self.user_visible_message,
        }


# ═════════════════════════════════════════════════════════════════════════════
# Helpers de comparabilité
# ═════════════════════════════════════════════════════════════════════════════

_YEAR_RE = re.compile(r"\b(?:FY\s*)?((?:19|20)\d{2})\b", re.IGNORECASE)


def _year_of(period: str) -> Optional[int]:
    m = _YEAR_RE.search(period or "")
    return int(m.group(1)) if m else None


def _periods_proven_different(pa: str, pb: str) -> bool:
    ya, yb = _year_of(pa), _year_of(pb)
    return ya is not None and yb is not None and ya != yb


# B.1.1 — Repli période quand fact.period est vide (appel direct de
# detect_fact_conflicts, hors enrichissement) : délégué à LA règle centrale
# fact_identity.extract_marked_period. Une année n'est lue dans value/label
# QUE si elle est marquée (parenthèses, FY, exercice, au JJ/MM/AAAA) — un
# « 2050 » nu (effectif, montant) ne doit JAMAIS être pris pour une année.


def _effective_period(f: Any) -> str:
    p = getattr(f, "period", "") or ""
    if _year_of(p) is not None:
        return p
    from patches.fact_identity import extract_marked_period
    for attr in ("value", "label"):
        m = extract_marked_period(getattr(f, attr, "") or "")
        if m:
            return m
    return p


def _side_perimeter(f: Any, ctx: AnalysisContext) -> Tuple[str, str, bool]:
    """
    (niveau de périmètre du côté, entité du côté, relation_connue?).

    Provisoire B.1 (source_type réel → B.2) : un fait déclaratif SANS pièce
    (status HYPOTHÈSE / À VÉRIFIER, aucun source_doc) porte le périmètre
    DÉCLARÉ du contexte — c'est le côté « brief » du cas dossier industriel (composants).
    """
    scope = (getattr(f, "scope", None) or "UNKNOWN").upper()
    entity = getattr(f, "perimeter_entity", "") or ""
    if scope not in ("UNKNOWN", "ESTIMATE", ""):
        return scope, entity, True
    status = str(getattr(getattr(f, "status", None), "value", getattr(f, "status", "")) or "")
    is_declarative = (not getattr(f, "source_doc", None)) and (
        "HYPOTH" in status.upper() or "VÉRIF" in status.upper()
        or "VERIF" in status.upper() or "NON SOURC" in status.upper())
    if is_declarative and ctx.target_entity:
        # côté brief : la revendication porte sur la CIBLE au NIVEAU visé
        lvl = "CONSOLIDATED" if ctx.target_perimeter_level == "consolide" \
            else "SOCIAL_STANDALONE"
        return f"DECLARED:{lvl}", entity or ctx.target_entity, True
    return scope, entity, False


def _same_perimeter(pa: str, ea: str, pb: str, eb: str) -> bool:
    la = pa.replace("DECLARED:", "")
    lb = pb.replace("DECLARED:", "")
    if la != lb:
        return False
    try:
        from patches.perimeter_match import entity_match_status, \
            ENTITY_EXACT_ID, ENTITY_EXACT_NAME, ENTITY_ALIAS, ENTITY_UNRESOLVED
        st = entity_match_status(ea, eb)
        return st in (ENTITY_EXACT_ID, ENTITY_EXACT_NAME, ENTITY_ALIAS,
                      ENTITY_UNRESOLVED)
    except Exception:
        return (ea or "").strip().lower() == (eb or "").strip().lower()


def _material_delta(va: float, vb: float, unit: str) -> Tuple[bool, float, bool]:
    """(matériel?, delta_relatif, suspicion_unité?)."""
    hi, lo = max(abs(va), abs(vb)), min(abs(va), abs(vb))
    floor = NOISE_FLOOR.get(unit, 0.0)
    if hi < floor:
        return False, 0.0, False
    abs_delta = abs(va - vb)
    rel = abs_delta / hi if hi else 0.0
    unit_suspect = False
    if lo > 0:
        ratio = hi / lo
        for fct in _UNIT_MISREAD_FACTORS:
            if abs(ratio - fct) / fct <= _UNIT_MISREAD_TOL:
                unit_suspect = True
                break
    material = (rel > REL_DELTA_MIN) or (abs_delta > ABS_DELTA_MIN.get(unit, float("inf")))
    return material, rel, unit_suspect


def _is_holding_headcount_zero(f: Any) -> bool:
    role = (getattr(f, "perimeter_role", "") or "").lower()
    scope = (getattr(f, "scope", "") or "").upper()
    mid = getattr(f, "metric_canonical_id", "") or ""
    nv = getattr(f, "normalized_value", None)
    return (mid == "HEADCOUNT" and nv is not None and abs(nv) <= 1.0
            and ("holding" in role or scope == "HOLDING"))


def _fmt_value(f: Any) -> str:
    return str(getattr(f, "value", "") or "").strip()


def _conflict_group_id(metric: str, keys: List[str]) -> str:
    payload = metric + "|" + "|".join(sorted(k for k in keys if k))
    return "CFL-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]



# v62.13.1 — period authority is wired into the original B1 conflict layer.
_STOCK_METRICS_62131 = {"CASH", "CASH_AND_EQUIVALENTS", "CASH_NET_OF_OVERDRAFTS",
                        "NET_DEBT", "GROSS_DEBT", "FINANCIAL_DEBT", "EQUITY", "STOCKS"}
_DEF_AXES_62131 = (
    ("pre_ifrs16", re.compile(r"pre[- ]?ifrs\s*16|hors\s+ifrs\s*16|excluding\s+ifrs\s*16", re.I)),
    ("post_ifrs16", re.compile(r"post[- ]?ifrs\s*16|including\s+ifrs\s*16|ifrs\s*16\s+incluse?", re.I)),
    ("adjusted_apm", re.compile(r"\badjust(?:ed|é)e?s?\b|\bunderlying\b|\bapm\b", re.I)),
    ("statutory", re.compile(r"\bstatutory\b|\breported\b|\bcomptable\b|\bpubli[ée]e?\b", re.I)),
)
_RESTATED_62131 = re.compile(r"\brestated\b|\bre[- ]?presented\b|\bretrait[ée]e?s?\b", re.I)

def _period_end_62131(f: Any) -> str:
    try:
        from utils.financial_proof_layer import normalize_period_end
        return normalize_period_end(getattr(f, "period_end_date", "") or getattr(f, "document_date", ""))
    except Exception:
        return ""

def _definition_axis_62131(f: Any) -> str:
    hay=" ".join(str(getattr(f,a,"") or "") for a in ("label","source_excerpt","source_value_text"))
    for axis,rx in _DEF_AXES_62131:
        if rx.search(hay): return axis
    return ""

def _is_restated_62131(f: Any) -> bool:
    return bool(_RESTATED_62131.search(" ".join(str(getattr(f,a,"") or "") for a in ("label","source_excerpt"))))

def _set_role_62131(f: Any, role: str) -> None:
    try:
        f.canonical_role = role
    except Exception:
        pass


def _resolved_conflict_62131(mid: str, fa: Any, fb: Any, ctx: AnalysisContext, *,
                              reason: str, resolution: str, lang: str) -> FactConflict:
    lva, ea, _ = _side_perimeter(fa, ctx)
    lvb, eb, _ = _side_perimeter(fb, ctx)
    sides = [_side_dict(fa, lva, ea), _side_dict(fb, lvb, eb)]
    keys = [getattr(fa, "stable_fact_key", "") or _fmt_value(fa),
            getattr(fb, "stable_fact_key", "") or _fmt_value(fb),
            str(sides[0].get("period_end") or ""),
            str(sides[1].get("period_end") or "")]
    gid = _conflict_group_id(mid + "|resolved|" + reason, keys)
    if lang == "en":
        message = (f"Resolved evidence tension on {mid}: "
                   f"{sides[0]['value']} ({sides[0].get('period_end') or 'period n/a'}, "
                   f"{sides[0].get('canonical_role') or 'role n/a'}) vs "
                   f"{sides[1]['value']} ({sides[1].get('period_end') or 'period n/a'}, "
                   f"{sides[1].get('canonical_role') or 'role n/a'}); {resolution}.")
    else:
        message = (f"Tension de preuve résolue sur {mid} : "
                   f"{sides[0]['value']} ({sides[0].get('period_end') or 'période n/a'}, "
                   f"{sides[0].get('canonical_role') or 'rôle n/a'}) vs "
                   f"{sides[1]['value']} ({sides[1].get('period_end') or 'période n/a'}, "
                   f"{sides[1].get('canonical_role') or 'rôle n/a'}) ; {resolution}.")
    return FactConflict(
        metric_canonical_id=mid,
        competing_values=sides,
        conflict_severity=SEV_INFORMATIONAL,
        conflict_reason=reason,
        resolution=RES_RETENU,
        user_visible_message=message,
        conflict_group_id=gid,
    )

# ═════════════════════════════════════════════════════════════════════════════
# Détection
# ═════════════════════════════════════════════════════════════════════════════

def detect_fact_conflicts(
    facts: Iterable[Any],
    ctx: AnalysisContext,
    *,
    lang: str = "fr",
    authoritative_period_end: str | None = None,
) -> List[FactConflict]:
    """
    Détecte les conflits entre faits d'une même métrique canonique et pose
    conflict_group_id sur les faits concernés (in place).

    Ne compare que des faits CHIFFRÉS (normalized_value présent) d'une
    métrique connue. Ne lève jamais.
    """
    fact_rows = list(facts or [])
    # Assign the dossier role once, even when a metric has only one observed
    # period and therefore never enters a pairwise comparison. This keeps the
    # original B1 layer consistent with the Financial Proof Layer: an older
    # page-confirmed row cannot remain implicitly CURRENT merely because no
    # competing value exists for that metric.
    auth = ""
    try:
        from utils.financial_proof_layer import normalize_period_end
        auth = normalize_period_end(authoritative_period_end)
    except Exception:
        auth = ""
    if auth:
        for f in fact_rows:
            pe = _period_end_62131(f)
            if pe == auth:
                _set_role_62131(f, "CURRENT")
            elif pe and pe > auth:
                _set_role_62131(f, "POST_CLOSE_INDICATION")
            elif pe:
                _set_role_62131(f, "CONTRIBUTING_HISTORY")
            axis = _definition_axis_62131(f)
            if axis:
                try:
                    f.definition_axis = axis
                except Exception:
                    pass

    by_metric: Dict[str, List[Any]] = {}
    for f in fact_rows:
        mid = getattr(f, "metric_canonical_id", "") or ""
        if mid in ("", "OTHER"):
            continue
        if getattr(f, "normalized_value", None) is None:
            continue
        by_metric.setdefault(mid, []).append(f)

    conflicts: List[FactConflict] = []
    for mid, group in by_metric.items():
        if len(group) < 2:
            continue
        n = len(group)
        for i in range(n):
            for j in range(i + 1, n):
                c = _compare_pair(mid, group[i], group[j], ctx, lang=lang,
                                  authoritative_period_end=authoritative_period_end)
                if c:
                    conflicts.append(c)
    unique: List[FactConflict] = []
    seen: set[tuple[Any, ...]] = set()
    for c in conflicts:
        key = (c.metric_canonical_id, c.conflict_severity, c.conflict_reason,
               c.resolution, tuple(sorted(
                   (str(v.get("stable_fact_key") or v.get("value") or ""),
                    str(v.get("period_end") or v.get("period") or ""),
                    str(v.get("definition_axis") or ""))
                   for v in c.competing_values)))
        if key not in seen:
            seen.add(key); unique.append(c)
    return unique


def _compare_pair(mid: str, fa: Any, fb: Any, ctx: AnalysisContext,
                  *, lang: str, authoritative_period_end: str | None = None) -> Optional[FactConflict]:
    va, vb = fa.normalized_value, fb.normalized_value
    ua = getattr(fa, "unit", "") or ""
    ub = getattr(fb, "unit", "") or ""
    # v62.13.9.4.45 — un fait SANS UNITÉ ne se compare à rien : run réel du 26/09/2026,
    # « 31 » (le 31 d'une échéance, repris par un agent) opposé à « 55 % » et à
    # « 341 343 k$ » sous la même grandeur, et le tableau de bord déclaré non établi.
    # De même, un fait non qualifié (prospectif, variation, déclaré non confirmé) ne
    # fonde pas un conflit dur.
    if not ua or not ub:
        return None
    # un conflit DUR oppose deux faits confirmés à la page ; une claim d'agent non
    # confirmée ne peut pas éteindre un fait de page — elle est déjà traitée par la
    # filiation (déclarée non confirmée) et n'a pas voix au tableau de bord.
    _pc = lambda f: str(getattr(f, "proof_status", "") or "") == "CONFIRMED_ON_PAGE"
    if _pc(fa) != _pc(fb):
        return None
    _nat = lambda f: str(getattr(f, "nature", "") or "").upper()
    if _nat(fa) in ("PROSPECTIVE", "VARIATION", "DECLARED_BY_BRIEF") or _nat(fb) in ("PROSPECTIVE", "VARIATION", "DECLARED_BY_BRIEF"):
        return None
    if ua and ub and ua != ub:
        return None  # unités hétérogènes non normalisables → pas de comparaison v1

    unit = ua or ub or "CUR"
    material, rel, unit_suspect = _material_delta(float(va), float(vb), unit)

    auth = ""
    try:
        from utils.financial_proof_layer import normalize_period_end
        auth = normalize_period_end(authoritative_period_end)
    except Exception:
        auth = ""
    pea, peb = _period_end_62131(fa), _period_end_62131(fb)
    if auth and pea and peb and pea != peb:
        for fact, pe in ((fa, pea), (fb, peb)):
            if pe == auth:
                _set_role_62131(fact, "CURRENT")
            elif pe > auth:
                _set_role_62131(fact, "POST_CLOSE_INDICATION")
            else:
                _set_role_62131(fact, "CONTRIBUTING_HISTORY")
        if not material:
            return None
        # Two historical observations are an ordinary time series and do not
        # need a pairwise "conflict" journal row. Keep the auditable resolution
        # only when the comparison touches the current authority or a post-close
        # indication.
        roles = {str(getattr(fa, "canonical_role", "") or ""),
                 str(getattr(fb, "canonical_role", "") or "")}
        if roles == {"CONTRIBUTING_HISTORY"}:
            return None
        return _resolved_conflict_62131(
            mid, fa, fb, ctx, reason=REASON_PERIOD,
            resolution="resolved_by_period_authority", lang=lang)

    axa, axb = _definition_axis_62131(fa), _definition_axis_62131(fb)
    if axa and axb and axa != axb:
        try:
            fa.definition_axis = axa; fb.definition_axis = axb
        except Exception:
            pass
        if not material:
            return None
        return _resolved_conflict_62131(
            mid, fa, fb, ctx, reason=REASON_SEMANTIC,
            resolution="split_by_definition_axis", lang=lang)

    # Série temporelle normale : années PROUVÉES différentes → pas un conflit.
    # Période effective = fact.period, sinon année MARQUÉE dans value/label
    # (parenthèses/FY/exercice) — jamais un nombre nu.
    pa, pb = _effective_period(fa), _effective_period(fb)
    if _periods_proven_different(pa, pb):
        return None

    if not material:
        return None

    if auth and (pea == peb or (not pea and not peb)):
        ra, rb = _is_restated_62131(fa), _is_restated_62131(fb)
        if ra != rb:
            _set_role_62131(fa if ra else fb, "CURRENT")
            _set_role_62131(fb if ra else fa, "SUPERSEDED")
            return _resolved_conflict_62131(
                mid, fa, fb, ctx, reason=REASON_SOURCE,
                resolution="superseded_by_restated", lang=lang)
        ranka=int(getattr(fa,"source_priority",999) or 999); rankb=int(getattr(fb,"source_priority",999) or 999)
        if ranka != rankb:
            _set_role_62131(fa if ranka < rankb else fb, "CURRENT")
            _set_role_62131(fb if ranka < rankb else fa, "SUPERSEDED")
            return _resolved_conflict_62131(
                mid, fa, fb, ctx, reason=REASON_SOURCE,
                resolution="superseded_by_document_hierarchy", lang=lang)

    # ── B.1.1 (audit gate B.2, P1/P2) — garde DEVISE ─────────────────────────
    # Deux faits CUR en devises différentes (EUR vs GBP) ne sont PAS
    # normalisés : la comparaison de valeur brute n'a pas de sens. Posture
    # B.1 : pas de conversion automatique, pas de conflit HARD — une réserve
    # INFORMATIONNELLE visible quand l'écart brut aurait alerté (sinon
    # silence : anti sur-alerte). La conversion documentée arrive avec les
    # transformations B.2+ (devises alors alignées en amont).
    ca = (getattr(fa, "currency", "") or "").upper()
    cb = (getattr(fb, "currency", "") or "").upper()
    if unit == "CUR" and ca and cb and ca != cb:
        # Décision d'implémentation B.1.1 (à ratifier au débrief, comme NA) :
        # entre devises différentes, le plancher ABSOLU n'a pas de sens
        # dimensionnel (500 k€ vs quoi, en £ ?). La réserve ne se déclenche
        # que sur l'écart RELATIF (> REL_DELTA_MIN) : 100 M€ vs 88 M£ est
        # vraisemblablement du change (≈ parité réelle) → silence ;
        # 3 100 M€ vs 2 400 M£ (> 15 %) → réserve visible.
        if rel <= REL_DELTA_MIN:
            return None
        keys = [getattr(fa, "stable_fact_key", "") or _fmt_value(fa),
                getattr(fb, "stable_fact_key", "") or _fmt_value(fb)]
        gid = _conflict_group_id(mid, keys)
        for f in (fa, fb):
            try:
                f.conflict_group_id = gid
            except Exception:
                pass
        lva_c, ea_c, _ = _side_perimeter(fa, ctx)
        lvb_c, eb_c, _ = _side_perimeter(fb, ctx)
        conflict = FactConflict(
            metric_canonical_id=mid,
            competing_values=[_side_dict(fa, lva_c, ea_c),
                              _side_dict(fb, lvb_c, eb_c)],
            conflict_severity=SEV_INFORMATIONAL,
            conflict_reason=REASON_UNIT,
            resolution=RES_NON_RESOLU,
            conflict_group_id=gid,
        )
        conflict.user_visible_message = (
            (f"Devises différentes ({ca} vs {cb}) — comparaison non "
             f"normalisée, écart apparent non qualifiable sans conversion "
             f"documentée.") if lang != "en" else
            (f"Different currencies ({ca} vs {cb}) — comparison not "
             f"normalized; apparent gap cannot be qualified without a "
             f"documented conversion."))
        return conflict

    # Anti sur-alerte non négociable : holding 0 salarié vs effectif —
    # différence structurelle ATTENDUE.
    holding_case = _is_holding_headcount_zero(fa) or _is_holding_headcount_zero(fb)

    lva, ea, ka = _side_perimeter(fa, ctx)
    lvb, eb, kb = _side_perimeter(fb, ctx)
    relation_known = ka and kb
    if not relation_known and not holding_case:
        return None  # verrou de matérialité : relation de périmètre inconnue

    same_perim = _same_perimeter(lva, ea, lvb, eb)

    if holding_case and mid == "HEADCOUNT":
        severity, reason = SEV_INFORMATIONAL, REASON_PERIMETER
    elif same_perim:
        severity = SEV_HARD
        reason = REASON_UNIT if unit_suspect else REASON_SOURCE
    else:
        severity = SEV_APPARENT
        reason = REASON_UNIT if unit_suspect else REASON_PERIMETER

    keys = [getattr(fa, "stable_fact_key", "") or _fmt_value(fa),
            getattr(fb, "stable_fact_key", "") or _fmt_value(fb)]
    gid = _conflict_group_id(mid, keys)
    for f in (fa, fb):
        try:
            f.conflict_group_id = gid
        except Exception:
            pass

    conflict = FactConflict(
        metric_canonical_id=mid,
        competing_values=[_side_dict(fa, lva, ea), _side_dict(fb, lvb, eb)],
        conflict_severity=severity,
        conflict_reason=reason,
        resolution=RES_NON_RESOLU,
        conflict_group_id=gid,
    )
    conflict.user_visible_message = _message(conflict, lang=lang)
    return conflict


def _side_dict(f: Any, level: str, entity: str) -> Dict[str, Any]:
    return {
        "value": _fmt_value(f),
        "perimeter": level,
        "entity": entity,
        "source_type": "brief" if level.startswith("DECLARED:") else
                       ("registre/pièce" if getattr(f, "source_doc", None) else ""),
        "stable_fact_key": getattr(f, "stable_fact_key", ""),
        "period": _effective_period(f),
        "period_end": _period_end_62131(f),
        "canonical_role": getattr(f, "canonical_role", ""),
        "definition_axis": getattr(f, "definition_axis", ""),
        "source_doc": getattr(f, "source_doc", ""),
        "source_page": getattr(f, "source_page", None),
    }


def _message(c: FactConflict, *, lang: str = "fr") -> str:
    a, b = c.competing_values[0], c.competing_values[1]
    if lang == "en":
        head = {"hard": "Hard conflict", "apparent": "Apparent tension",
                "informational": "Structural difference"}[c.conflict_severity]
        return (f"{head} detected on {c.metric_canonical_id}: "
                f"{a['value']} [{a['perimeter']}] vs {b['value']} [{b['perimeter']}] "
                f"(reason: {c.conflict_reason}).")
    head = {"hard": "Conflit dur", "apparent": "Tension apparente",
            "informational": "Différence structurelle"}[c.conflict_severity]
    return (f"{head} détecté(e) sur {c.metric_canonical_id} : "
            f"{a['value']} [{a['perimeter']}] vs {b['value']} [{b['perimeter']}] "
            f"(raison : {c.conflict_reason}).")


def has_unresolved_blocking_conflict(conflicts: Iterable[FactConflict],
                                     fact: Any) -> bool:
    """Le fait appartient-il à un conflit hard/apparent non résolu ? (board-safe)"""
    gid = getattr(fact, "conflict_group_id", "") or ""
    if not gid:
        return False
    for c in conflicts or []:
        if (c.conflict_group_id == gid and c.resolution == RES_NON_RESOLU
                and c.conflict_severity in (SEV_HARD, SEV_APPARENT)):
            return True
    return False
