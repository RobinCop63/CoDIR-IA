"""
patches/perimeter_match.py — v17.4.0-M6B-B1.0 (M6-B · B.1 · E3)

LOGIQUE DE PÉRIMÈTRE — match, trois postures, exclusion (note M6-B v3,
Partie II §5). C'est LE GESTE CENTRAL de B.1 : en v5 (dossier industriel (composants)),
financial_signal_solid est passé à True sur des comptes SOCIAUX STANDALONE
d'une entité du groupe → score monté à 62/C sur la MAUVAISE donnée.

Règle de match (§5.1) :
    FULL      si fact.perimeter.level == ctx.target_perimeter_level
              ET entité du fait == entité cible (appariement NON NAÏF)
    COVERAGE  si ctx.mode == consolidation ET entité ∈ declared_entities
    MISMATCH  sinon (ex. SOCIAL_STANDALONE d'une filiale en analyse groupe)

Verrou ChatGPT — appariement d'entité NON NAÏF : ne PAS faire dépendre la
vérité métier d'une égalité brute de chaînes. Statuts :
    exact_id | exact_name | alias | same_group_probable | unresolved | mismatch
(ex. brief « Groupe Le Duff » vs registre « holding / filiale / marque » :
une égalité stricte produirait un FAUX mismatch.)

Garde de conception (héritée d'A2 / entity_scope) : le NIVEAU prime sur le
NOM. « dossier anglophone coté Limited » (social filiale) partage la marque avec
« dossier anglophone coté Group plc » — l'alias de nom n'ouvre JAMAIS un FULL si le niveau
de périmètre ne correspond pas déjà.

Effet B.1 sur le score (§8.1, seul comportement de score modifié) :
    un fait MISMATCH est MONTRÉ mais ne peut PAS alimenter
    financial_signal_solid → gate_financial_signal().

Valeur d'implémentation « NA » (à ratifier au débrief) : un fait SANS
périmètre financier évaluable (scope UNKNOWN/ESTIMATE, fait d'identité ou de
métadonnée) reçoit perimeter_match="NA" — il n'est ni FULL ni MISMATCH, il
est hors du champ de la règle. Taguer MISMATCH ces lignes créerait du bruit
d'exclusion (anti sur-alerte, §6) ; les taguer FULL serait faux.

100 % déterministe, sans dépendance pipeline → testable en isolation.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, List, Optional, Tuple

from patches.analysis_context import (
    AnalysisContext, MODE_CONSO, MODE_MONO, MODE_GROUPE,
    LEVEL_CONSOLIDE, LEVEL_SOCIAL, LEVEL_SEGMENT,
)

# ── Statuts de match (contrat) ────────────────────────────────────────────────
MATCH_FULL = "FULL"
MATCH_COVERAGE = "COVERAGE"
MATCH_MISMATCH = "MISMATCH"
MATCH_NA = "NA"  # hors du champ de la règle (fait sans périmètre financier)

ENTITY_EXACT_ID = "exact_id"
ENTITY_EXACT_NAME = "exact_name"
ENTITY_ALIAS = "alias"
ENTITY_SAME_GROUP = "same_group_probable"
ENTITY_UNRESOLVED = "unresolved"
ENTITY_MISMATCH = "mismatch"

# scope de fait (FinancialFact.scope) → niveau de périmètre du contexte
_SCOPE_TO_LEVEL = {
    "CONSOLIDATED": LEVEL_CONSOLIDE,
    "HOLDING": LEVEL_SOCIAL,           # comptes sociaux de la société mère
    "SOCIAL_STANDALONE": LEVEL_SOCIAL,
    "SEGMENT": LEVEL_SEGMENT,
    "MARKET": "benchmark",             # jamais égal à un niveau cible → MISMATCH
}
_NO_LEVEL_SCOPES = ("UNKNOWN", "ESTIMATE", "", None)


# ═════════════════════════════════════════════════════════════════════════════
# Appariement d'entité non naïf
# ═════════════════════════════════════════════════════════════════════════════

_LEGAL_SUFFIX = re.compile(
    r"\b(sasu|sas|sarl|sa|sca|sci|snc|eurl|gmbh|ag|plc|p\.l\.c\.|ltd|limited|"
    r"llc|inc|corp|co|bv|b\.v\.|nv|asa|as|ab|oy|spa|s\.p\.a\.|srl|holding[s]?)\b\.?",
    re.IGNORECASE,
)
_GROUP_PREFIX = re.compile(r"\b(groupe|group|the)\b", re.IGNORECASE)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.strip().lower())


def _base_name(s: str) -> str:
    """Nom « de marque » : sans suffixes légaux ni préfixe groupe/the."""
    t = _norm(s)
    t = _LEGAL_SUFFIX.sub(" ", t)
    t = _GROUP_PREFIX.sub(" ", t)
    return re.sub(r"[^\w]+", " ", t).strip()


def entity_match_status(
    fact_entity: str,
    target_entity: str,
    *,
    fact_entity_id: str = "",
    target_entity_id: str = "",
) -> str:
    """
    Statut d'appariement entre l'entité d'un fait et une entité de référence.
    S'appuie sur utils/name_matcher (levels exact/contains/shared/none) puis
    raffine avec les bases de marque (suffixes légaux retirés).
    """
    fid = (fact_entity_id or "").strip()
    tid = (target_entity_id or "").strip()
    if fid and tid:
        return ENTITY_EXACT_ID if fid == tid else ENTITY_MISMATCH

    fe, te = (fact_entity or "").strip(), (target_entity or "").strip()
    if not fe or not te:
        return ENTITY_UNRESOLVED

    try:
        from utils.name_matcher import match_company_names
        level, _score = match_company_names(fe, te)
    except Exception:
        level = "exact" if _norm(fe) == _norm(te) else "none"

    if level == "exact":
        # exact_name = identité stricte (casse/accents près). Si le matcher n'a
        # conclu « exact » qu'après retrait de forme légale ou préfixe groupe
        # (« LE DUFF SA » vs « Groupe Le Duff »), c'est un ALIAS : même marque,
        # habillage différent — traçable comme tel dans le journal.
        if _norm(fe) == _norm(te):
            return ENTITY_EXACT_NAME
        return ENTITY_ALIAS

    fb, tb = _base_name(fe), _base_name(te)
    if fb and tb:
        if fb == tb:
            # même marque, seule la forme légale / le préfixe groupe diffèrent
            return ENTITY_ALIAS
        if fb in tb or tb in fb:
            # « <groupe> hydraulics » ⊂ « <groupe> » : même famille, entité distincte
            return ENTITY_SAME_GROUP

    if level in ("contains", "shared"):
        return ENTITY_SAME_GROUP
    return ENTITY_MISMATCH


def _matches_any_declared(fact_entity: str, fact_entity_id: str,
                          ctx: AnalysisContext) -> Tuple[bool, str]:
    """(match?, entité déclarée touchée) pour le mode consolidation."""
    for decl in ctx.declared_entities or []:
        st = entity_match_status(fact_entity, decl, fact_entity_id=fact_entity_id)
        if st in (ENTITY_EXACT_ID, ENTITY_EXACT_NAME, ENTITY_ALIAS, ENTITY_SAME_GROUP):
            return True, decl
    return False, ""


# ═════════════════════════════════════════════════════════════════════════════
# La règle de match
# ═════════════════════════════════════════════════════════════════════════════

def perimeter_match(fact: Any, ctx: AnalysisContext) -> Tuple[str, str]:
    """
    Applique la règle §5.1 à un FinancialFact. Retourne
    (perimeter_match, entity_match_status).

    Lit sur le fait : scope, perimeter_entity (défaut : entité cible si le
    fait vient de la résolution registre du run — posé par le wiring moteur),
    entity_id, transformation.
    """
    scope = (getattr(fact, "scope", None) or "UNKNOWN").upper()
    fact_entity = getattr(fact, "perimeter_entity", "") or ""
    fact_entity_id = getattr(fact, "entity_id", "") or ""

    # Hors du champ : pas de périmètre financier évaluable.
    if scope in _NO_LEVEL_SCOPES:
        return MATCH_NA, ENTITY_UNRESOLVED

    fact_level = _SCOPE_TO_LEVEL.get(scope, "benchmark")
    ent_status = entity_match_status(
        fact_entity, ctx.target_entity,
        fact_entity_id=fact_entity_id, target_entity_id=ctx.target_entity_id,
    )

    # FULL — le NIVEAU d'abord, puis l'entité (alias accepté : même marque,
    # forme légale différente ; same_group_probable NON accepté : c'est
    # probablement une AUTRE entité de la même famille).
    if fact_level == ctx.target_perimeter_level and ent_status in (
            ENTITY_EXACT_ID, ENTITY_EXACT_NAME, ENTITY_ALIAS):
        return MATCH_FULL, ent_status

    # Mono-entité, entité de fait non renseignée : le run ne porte qu'une
    # entité (la cible) ; si le niveau colle, le fait la décrit.
    if (ctx.mode == MODE_MONO and fact_level == ctx.target_perimeter_level
            and ent_status == ENTITY_UNRESOLVED):
        return MATCH_FULL, ent_status

    # COVERAGE — consolidation : le fait décrit UNE entité du périmètre déclaré.
    if ctx.mode == MODE_CONSO:
        ok, _decl = _matches_any_declared(fact_entity, fact_entity_id, ctx)
        if ok:
            return MATCH_COVERAGE, ent_status
        # la tête de groupe elle-même compte pour la couverture
        if ent_status in (ENTITY_EXACT_ID, ENTITY_EXACT_NAME, ENTITY_ALIAS):
            return MATCH_COVERAGE, ent_status

    return MATCH_MISMATCH, ent_status


def annotate_facts_perimeter(facts: Iterable[Any], ctx: AnalysisContext) -> None:
    """
    Pose perimeter_match + entity_match sur chaque fait (in place).
    Un MISMATCH reçoit aussi la note d'exclusion visible (E7 s'appuie dessus).
    """
    for f in facts or []:
        pm, es = perimeter_match(f, ctx)
        try:
            f.perimeter_match = pm
            f.entity_match = es
        except Exception:
            continue


# ═════════════════════════════════════════════════════════════════════════════
# La porte du signal — le fix du bug v5
# ═════════════════════════════════════════════════════════════════════════════

def gate_financial_signal(
    raw_solid: bool,
    facts: Iterable[Any],
    ctx: AnalysisContext,
) -> Tuple[bool, str]:
    """
    Décide si financial_signal_solid peut rester True au vu des périmètres.

    Contrat (§5.2 + §7) :
      · un fait MISMATCH ne peut PAS alimenter financial_signal_solid ;
      · une agrégation (transformation=agrégé) ne le pose JAMAIS.

    Implémentation honnête et non régressive :
      · raw_solid=False → False (« perimeter gating ne crée jamais de signal »).
      · S'il existe au moins UN fait financier chiffré FULL (mono/groupe) ou
        FULL/COVERAGE (consolidation), hors agrégations → le signal tient.
      · Si TOUS les faits financiers à périmètre évaluable sont MISMATCH
        (le cas dossier industriel (composants) v5 : uniquement du SOCIAL_STANDALONE en analyse
        groupe) → effective=False, raison "perimeter_gated".
      · Aucun fait à périmètre évaluable (signal purement documentaire,
        ex. Excel interne sans entité) → le brut tient : B.1 ne dégrade pas
        les acquis dossier réseau de soins ; la qualification fine arrive en B.3.
    """
    if not raw_solid:
        return False, ""

    sustaining_ok = (MATCH_FULL, MATCH_COVERAGE) if ctx.mode == MODE_CONSO \
        else (MATCH_FULL,)

    n_perimeter_facts = 0
    n_sustaining = 0
    n_brief_only_sustainers = 0
    for f in facts or []:
        pm = getattr(f, "perimeter_match", MATCH_NA)
        if pm == MATCH_NA:
            continue
        if not _is_financial_value_fact(f):
            continue
        n_perimeter_facts += 1
        if pm in sustaining_ok and (getattr(f, "transformation", "") or "") != "agrégé":
            # B.1.3 (golden dossier industriel (composants)) — un fait DÉCLARATIF ne certifie pas :
            # « source = Brief » est visible et structuré, mais s'il devenait
            # porteur du signal, le brut (issu des pièces) serait blanchi par
            # une simple déclaration — le schéma v5, un cran plus haut.
            _src = str(getattr(f, "source_doc", "") or "").strip().lower()
            _blk = [str(b).lower() for b in
                    (getattr(f, "board_safe_blockers", None) or [])]
            if _src == "brief" or "brief_only" in _blk:
                n_brief_only_sustainers += 1
                continue
            n_sustaining += 1

    if n_perimeter_facts == 0:
        return True, "no_perimeter_facts"
    if n_sustaining > 0:
        return True, "sustained_by_perimeter"
    if n_brief_only_sustainers > 0:
        return False, "brief_facts_cannot_certify"
    return False, "perimeter_gated"


def _is_financial_value_fact(f: Any) -> bool:
    """Un fait « chiffré » : métrique canonique connue et valeur numérique."""
    mid = getattr(f, "metric_canonical_id", "") or ""
    if mid in ("", "OTHER"):
        return False
    nv = getattr(f, "normalized_value", None)
    if nv is not None:
        return True
    # repli : la valeur affichée contient un chiffre
    return bool(re.search(r"\d", str(getattr(f, "value", "") or "")))


# ═════════════════════════════════════════════════════════════════════════════
# B.1.3.20 (P0-B, run dossier industriel) — contradiction contexte/faits VISIBLE
# ═════════════════════════════════════════════════════════════════════════════
def context_facts_mismatch_note(facts, ctx, lang: str = "fr"):
    """Note de requalification si le contexte est MONO/social alors que des
    faits financiers de niveau CONSOLIDÉ groupe figurent au dossier.

    Racine (run dossier industriel) : les détecteurs voyaient le conflit
    (HARD_METRIC_SCOPE_CONFLICT → cap de score) mais AUCUN verdict ne
    touchait le livrable — le fait restait ✅ FAIT et le contexte silencieux.
    Désormais : bannière d'alerte CR (canal flags, comme P0-3) + les faits
    concernés sont déjà ⛔ via la ré-annotation périmètre.

    Renvoie (note, n_conflits) — (None, 0) si pas de contradiction.
    """
    try:
        _mode = str(getattr(ctx, "mode", "") or "").lower()
        _lvl = str(getattr(ctx, "target_perimeter_level", "") or "").lower()
    except Exception:
        return None, 0
    if "mono" not in _mode or "social" not in _lvl:
        return None, 0
    n = 0
    ex = []
    for f in facts or []:
        _scope = str(getattr(f, "scope", "") or "").upper()
        if _scope != "CONSOLIDATED":
            continue
        if getattr(f, "perimeter_match", None) not in (MATCH_MISMATCH,):
            continue
        n += 1
        if len(ex) < 2:
            ex.append(str(getattr(f, "label", "") or "?")[:60])
    if n == 0:
        return None, 0
    if lang == "en":
        note = ("⚠ Context/facts conflict (P0-B): analysis context is "
                f"mono-entity / social scope, yet {n} group-CONSOLIDATED "
                f"fact(s) are present ({'; '.join(ex)}). Context TO REQUALIFY "
                "(ambiguous_group, low confidence); the facts are shown "
                "⛔ OUT OF PERIMETER and excluded from the score. Do not "
                "circulate without clarifying the target perimeter.")
    else:
        note = ("⚠ Conflit contexte/faits (P0-B) : le contexte d'analyse est "
                f"mono-entité / périmètre social, mais {n} fait(s) de niveau "
                f"CONSOLIDÉ groupe figurent au dossier ({'; '.join(ex)}). "
                "Contexte À REQUALIFIER (ambiguous_group, confiance basse) ; "
                "ces faits sont rendus ⛔ HORS PÉRIMÈTRE et exclus du score. "
                "Ne pas diffuser sans clarification du périmètre cible.")
    return note, n
