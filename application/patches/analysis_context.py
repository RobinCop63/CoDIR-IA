"""
patches/analysis_context.py — v17.4.0-M6B-B1.0 (M6-B · B.1.0 · E2)

CONTEXTE D'ANALYSE — la brique zéro (D6, note référente M6-B v3, §5 & Partie II §2).

Un compte social n'est ni bon ni mauvais en soi : il dépend du MODE d'analyse.
Le système fige donc son contexte d'analyse AVANT de juger le moindre fait.

Trois modes :
    mono_entite                  : le compte social DÉCRIT l'entité analysée
    groupe                       : un social d'UNE filiale ≠ le groupe
    consolidation_multi_entites  : le groupe se CONSTRUIT depuis N entités déclarées

Verrou ChatGPT (acté) — LE CONTEXTE PORTE SA PROPRE PREUVE : puisque le
contexte est inféré, il journalise inferred_from, inference_confidence,
user_override, override_reason. JAMAIS de bascule de mode silencieuse —
sinon demain c'est le CONTEXTE qui serait faux, et tous les faits seraient
« bien qualifiés » dans le mauvais monde.

Nuance actée (Claude) — INFÉRÉ + SURCHARGEABLE d'un clic, jamais un
formulaire obligatoire : on protège l'UX du patron de PME qui écrit un
brief, pas un schéma.

Règles d'inférence testables (Partie II §2.1) :
    · une seule entité nommée, pas de mention groupe/filiales → mono_entite
    · « groupe », « consolidé », ordres de grandeur groupe, sans liste
      d'entités → groupe
    · plusieurs entités nommées / « consolidation de X, Y, Z » / carve-out
      → consolidation_multi_entites
    · ambigu → groupe par défaut, inference_confidence=low, PAS de conso
      automatique

100 % déterministe, sans dépendance pipeline → testable en isolation.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# ── Modes / niveaux / cibles (vocabulaire du contrat) ─────────────────────────
MODE_MONO = "mono_entite"
MODE_GROUPE = "groupe"
MODE_CONSO = "consolidation_multi_entites"
_MODES = (MODE_MONO, MODE_GROUPE, MODE_CONSO)

LEVEL_CONSOLIDE = "consolide"
LEVEL_SOCIAL = "social"
LEVEL_SEGMENT = "segment"

OUTPUT_EXPLORATOIRE = "exploratoire"
OUTPUT_INTERNE = "interne"
OUTPUT_BOARD_SAFE = "board_safe"

INFERRED_BRIEF = "brief"
INFERRED_USER = "user_override"
INFERRED_DOCUMENT = "document"
INFERRED_REGISTRY = "registry"

CONF_HIGH = "high"
CONF_MEDIUM = "medium"
CONF_LOW = "low"

# Métriques attendues par défaut (expected_metrics) — clés canoniques
# cohérentes avec patches/fact_identity.CANONICAL_METRICS.
DEFAULT_EXPECTED_METRICS = ["REVENUE", "HEADCOUNT", "NET_INCOME", "EBITDA",
                            "NET_DEBT", "CASH"]


# ═════════════════════════════════════════════════════════════════════════════
# Dataclass
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class AnalysisContext:
    """Le contexte d'analyse figé AVANT tout fait — avec sa preuve."""
    mode: str = MODE_GROUPE
    target_entity: str = ""
    target_entity_id: str = ""            # SIREN / LEI si connu (registre)
    target_perimeter_level: str = LEVEL_CONSOLIDE
    declared_entities: List[str] = field(default_factory=list)  # requis si conso
    expected_metrics: List[str] = field(default_factory=lambda: list(DEFAULT_EXPECTED_METRICS))
    output_target: str = OUTPUT_INTERNE
    # ── preuve du contexte (jamais de changement silencieux) ──────────────────
    inferred_from: str = INFERRED_BRIEF
    inference_confidence: str = CONF_MEDIUM
    user_override: bool = False
    override_reason: str = ""
    # signaux d'inférence conservés pour le débrief (pas pour le score)
    inference_signals: List[str] = field(default_factory=list)

    # ── identité ───────────────────────────────────────────────────────────────
    @property
    def analysis_context_id(self) -> str:
        payload = "|".join([
            self.mode, _norm(self.target_entity), self.target_perimeter_level,
            ";".join(sorted(_norm(e) for e in self.declared_entities)),
            self.output_target,
        ])
        return "CTX-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

    # ── journalisation (diagnostics_ia.csv) ───────────────────────────────────
    def to_journal_row(self) -> Dict[str, Any]:
        """Ligne diagnostics : le run journalise le contexte retenu (§2.1)."""
        return {
            "role": "analysis_context",
            "provider": "internal",
            "model": "analysis_context_b1",
            "status": "OK",
            "analysis_context_id": self.analysis_context_id,
            "mode": self.mode,
            "target_entity": self.target_entity,
            "target_perimeter_level": self.target_perimeter_level,
            "declared_entities": " | ".join(self.declared_entities),
            "output_target": self.output_target,
            "inferred_from": self.inferred_from,
            "inference_confidence": self.inference_confidence,
            "user_override": self.user_override,
            "override_reason": self.override_reason,
            "signals": " | ".join(self.inference_signals[:6]),
        }

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["analysis_context_id"] = self.analysis_context_id
        return d


# ═════════════════════════════════════════════════════════════════════════════
# Inférence depuis le brief
# ═════════════════════════════════════════════════════════════════════════════

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.strip().lower())


# Marqueurs « groupe » (FR/EN) — sans liste d'entités déclarée → mode groupe.
_GROUP_MARKERS = re.compile(
    r"\b(groupe|group\b|consolid[ée]s?|consolidated|consolidation|holding|"
    r"filiales?|subsidiar(?:y|ies)|maison[- ]m[eè]re|parent company|"
    r"p\.?l\.?c\.?|conglom[ée]rat)\b",
    re.IGNORECASE,
)

# Marqueurs « mono-entité » explicites.
_MONO_MARKERS = re.compile(
    r"\b(mono[- ]entit[ée]|entit[ée] unique|soci[ée]t[ée] unique|"
    r"pas de filiales?|aucune filiale|sans filiales?|single entity|"
    r"standalone company|SAS unique|SARL unique)\b",
    re.IGNORECASE,
)

# Déclencheurs de consolidation multi-entités : « consolidation de X, Y et Z »,
# « intégration post-acquisition », « carve-out », « périmètre : X, Y, Z »,
# « ENTITÉS DÉCLARÉES : ... ».
_CONSO_VERB = re.compile(
    r"\b(consolidation\s+(?:de|des|du|of)|conso\s+multi|carve[- ]?out|"
    r"int[ée]gration\s+post[- ]acquisition|revue\s+de\s+filiales|"
    r"p[ée]rim[eè]tre\s+de\s+consolidation)\b",
    re.IGNORECASE,
)

# Ligne « ENTITÉS DÉCLARÉES : A, B, C » ou « PÉRIMÈTRE : ... A, B, C » du
# format de brief maison (IDENTITÉ / PÉRIMÈTRE / CHIFFRES / QUESTION CODIR).
_DECLARED_LINE = re.compile(
    r"^\s*(?:ENTIT[ÉE]S?\s+D[ÉE]CLAR[ÉE]ES?|DECLARED\s+ENTITIES)\s*:\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)

_PERIMETRE_LINE = re.compile(
    r"^\s*(?:P[ÉE]RIM[ÈE]TRE|PERIMETER|SCOPE)\s*:\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)

_IDENTITE_LINE = re.compile(
    r"^\s*(?:IDENTIT[ÉE]|IDENTITY|SOCI[ÉE]T[ÉE]|COMPANY|ENTREPRISE)\s*:\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)

# Séparateurs d'une liste d'entités « A, B, C et D » / « A, B, C and D »
_LIST_SPLIT = re.compile(r"\s*(?:,|;|\bet\b|\band\b|\+|·)\s*", re.IGNORECASE)

# Bruit à retirer d'un nom d'entité extrait d'une liste
_ENTITY_NOISE = re.compile(r"\(.*?\)|\bà confirmer\b|\bto confirm\b|\.\.\.|…",
                           re.IGNORECASE)


def _clean_entity(token: str) -> str:
    t = _ENTITY_NOISE.sub("", token or "").strip(" .;:—-")
    return re.sub(r"\s+", " ", t)


def _extract_declared_entities(brief: str) -> List[str]:
    """Extrait une liste d'entités déclarées si le brief en porte une."""
    out: List[str] = []
    m = _DECLARED_LINE.search(brief or "")
    if m:
        # Ligne explicite « ENTITÉS DÉCLARÉES : … » = liste de confiance de
        # l'utilisateur : on accepte les noms courts (codes internes « A », « B »).
        for tok in _LIST_SPLIT.split(m.group(1)):
            t = _clean_entity(tok)
            if len(t) >= 1:
                out.append(t)
    if not out:
        # « consolidation de X, Y et Z » inline
        m2 = re.search(
            r"consolidation\s+(?:de|des|du|of)\s+([^\n\.]{3,160})",
            brief or "", re.IGNORECASE)
        if m2:
            for tok in _LIST_SPLIT.split(m2.group(1)):
                t = _clean_entity(tok)
                if len(t) >= 2:
                    out.append(t)
    # dédoublonnage en conservant l'ordre
    seen, dedup = set(), []
    for e in out:
        k = _norm(e)
        if k and k not in seen:
            seen.add(k)
            dedup.append(e)
    return dedup


def _extract_target_entity(brief: str) -> str:
    """Nom d'entité cible depuis la ligne IDENTITÉ du brief maison, sinon ''. """
    m = _IDENTITE_LINE.search(brief or "")
    if not m:
        return ""
    line = m.group(1)
    # retirer le contenu parenthésé AVANT la découpe (une virgule à l'intérieur
    # d'une parenthèse tronquerait le nom : « dossier industriel (composants) (groupe familial, … ) »)
    line = re.sub(r"\([^)]*\)?", "", line)
    head = _LIST_SPLIT.split(line)[0]
    return _clean_entity(head)[:80]



_EXPLICIT_SOCIAL40 = re.compile(
    r"(?i)(?:au\s+)?p[ée]rim[èe]tre\s+(?:social|statutaire)|comptes\s+sociaux\s+(?:de\s+la\s+soci[ée]t[ée]|uniquement|seuls)|"
    r"(?:standalone|statutory|entity[- ]level)\s+(?:perimeter|scope|accounts\s+only)|"
    r"hors\s+consolid|distingu\w*\s+(?:explicitement\s+)?ce\s+qui\s+rel[èe]ve\s+du\s+consolid|"
    r"jamais\s+pr[ée]sent[ée]s?\s+comme\s+des\s+faits\s+du\s+p[ée]rim[èe]tre")


def _explicit_social40(text: str) -> bool:
    """Le brief demande-t-il EXPLICITEMENT le périmètre social (en citant éventuellement le
    groupe pour l'en distinguer) ? Une demande explicite de consolidation l'emporte."""
    t = str(text or "")
    if re.search(r"(?i)\b(?:consolider|consolidate|produire\s+(?:le|un)\s+consolid|build\s+(?:the|a)\s+consolidat)", t):
        return False
    return bool(_EXPLICIT_SOCIAL40.search(t))

def infer_analysis_context(
    brief: str,
    *,
    resolved_entity_name: str = "",
    resolved_entity_id: str = "",
    resolution_from_registry: bool = False,
) -> AnalysisContext:
    """
    Infère le contexte d'analyse depuis le brief (+ résolution d'entité si
    disponible). Ne lève jamais — un brief vide produit un contexte
    groupe/low honnête plutôt qu'un crash.

    Règles §2.1 (testables) :
      1) déclencheur conso (liste déclarée OU verbe de consolidation avec
         ≥ 2 entités) → consolidation_multi_entites (high si liste explicite)
      2) marqueur mono explicite, sans marqueur groupe → mono_entite (high)
      3) marqueur groupe sans liste → groupe (high)
      4) une seule entité nommée, aucun marqueur groupe → mono_entite (medium)
      5) ambigu → groupe par défaut, confidence=low, PAS de conso automatique
    """
    text = brief or ""
    signals: List[str] = []

    declared = _extract_declared_entities(text)
    has_conso_verb = bool(_CONSO_VERB.search(text))
    has_mono = bool(_MONO_MARKERS.search(text))
    # « pas de filiales » / « sans filiale » sont des marqueurs MONO : le mot
    # « filiales » qu'ils contiennent ne doit pas compter comme marqueur groupe.
    # On évalue donc les marqueurs groupe sur le texte APRÈS retrait des spans
    # mono ; « SAS unique du groupe X » garde son « groupe » (coexistence §2.1).
    text_wo_mono = _MONO_MARKERS.sub(" ", text)
    has_group = bool(_GROUP_MARKERS.search(text_wo_mono))

    _target_from_brief = _extract_target_entity(text)
    target = _target_from_brief or (resolved_entity_name or "").strip()

    ctx = AnalysisContext()
    ctx.target_entity = target
    ctx.target_entity_id = (resolved_entity_id or "").strip()
    # B.1.3 (run dossier anglophone coté) — PROVENANCE HONNÊTE : si l'entité cible vient du
    # fallback registre (extraction brief vide), inferred_from le DIT, quel
    # que soit le registre source. L'ancienne condition (`not target`) était
    # inatteignable : target absorbait déjà le resolved.
    _target_via_registry = bool(target) and not _target_from_brief
    ctx.inferred_from = (INFERRED_REGISTRY if _target_via_registry
                         else INFERRED_BRIEF)

    # 1) Consolidation multi-entités — jamais « automatique » sans signal fort
    if declared and (len(declared) >= 2 or has_conso_verb):
        ctx.mode = MODE_CONSO
        ctx.declared_entities = declared
        ctx.target_perimeter_level = LEVEL_CONSOLIDE
        ctx.inference_confidence = CONF_HIGH
        signals.append(f"declared_entities:{len(declared)}")
        if has_conso_verb:
            signals.append("conso_verb")
    elif has_conso_verb and len(declared) >= 1:
        ctx.mode = MODE_CONSO
        ctx.declared_entities = declared
        ctx.target_perimeter_level = LEVEL_CONSOLIDE
        ctx.inference_confidence = CONF_MEDIUM
        signals.append("conso_verb+partial_list")
    # 2bis) v62.13.9.4.40 — CONSIGNE EXPLICITE DE PÉRIMÈTRE SOCIAL. « au périmètre social
    # France, en distinguant explicitement ce qui relève du consolidé groupe » : le brief
    # NOMME le groupe pour l'EXCLURE. Dossier réel du 21/09/2026 : la seule mention du groupe
    # actionnaire basculait l'analyse en consolidé, les comptes sociaux étaient rejetés du
    # périmètre demandé et le chapitre finance affirmait « aucune donnée ». Une consigne
    # explicite l'emporte sur un marqueur de groupe ; le groupe reste un contexte, pas la cible.
    elif _explicit_social40(brief):
        ctx.mode = MODE_MONO
        ctx.target_perimeter_level = LEVEL_SOCIAL
        ctx.inference_confidence = CONF_HIGH
        signals.append("explicit_social_perimeter")
        if has_group:
            signals.append("group_named_as_context_only")
    # 2) Mono explicite
    elif has_mono and not has_group:
        ctx.mode = MODE_MONO
        ctx.target_perimeter_level = LEVEL_SOCIAL
        ctx.inference_confidence = CONF_HIGH
        signals.append("mono_marker")
    # 3) Groupe explicite
    elif has_group:
        ctx.mode = MODE_GROUPE
        ctx.target_perimeter_level = LEVEL_CONSOLIDE
        ctx.inference_confidence = CONF_HIGH
        signals.append("group_marker")
    # 4) Une seule entité nommée, aucun marqueur groupe
    elif target:
        ctx.mode = MODE_MONO
        ctx.target_perimeter_level = LEVEL_SOCIAL
        ctx.inference_confidence = CONF_MEDIUM
        signals.append("single_named_entity")
    # 5) Ambigu — groupe par défaut, low, pas de conso automatique
    else:
        ctx.mode = MODE_GROUPE
        ctx.target_perimeter_level = LEVEL_CONSOLIDE
        ctx.inference_confidence = CONF_LOW
        signals.append("ambiguous_default_groupe")

    # Cas conso déclaré : mono/groupe markers ne dégradent pas — la liste prime.
    # Cas mono avec marqueur groupe co-présent (« SAS unique du groupe X ») :
    if has_mono and has_group and ctx.mode == MODE_GROUPE:
        ctx.inference_confidence = CONF_MEDIUM
        signals.append("mono+group_markers_coexist")

    # B.1.3 — cible héritée du registre (pas du brief) : la confiance de
    # l'inférence est DÉGRADÉE d'un cran — le contexte ne peut pas prétendre
    # « brief / high » sur une entité que le brief n'a pas nommée ainsi.
    if _target_via_registry:
        if ctx.inference_confidence == CONF_HIGH:
            ctx.inference_confidence = CONF_MEDIUM
        signals.append("target_from_registry_fallback")

    ctx.inference_signals = signals
    return ctx


# ═════════════════════════════════════════════════════════════════════════════
# Surcharge utilisateur — un clic, avec preuve
# ═════════════════════════════════════════════════════════════════════════════

def apply_override(
    ctx: AnalysisContext,
    *,
    mode: Optional[str] = None,
    target_entity: Optional[str] = None,
    target_perimeter_level: Optional[str] = None,
    declared_entities: Optional[List[str]] = None,
    output_target: Optional[str] = None,
    reason: str = "",
) -> AnalysisContext:
    """
    Surcharge explicite par l'utilisateur. Pose user_override=True +
    override_reason + inferred_from=user_override. Ne mute pas l'objet
    d'origine (le contexte inféré reste comparable au journal).
    """
    new = AnalysisContext(**{**asdict(ctx)})
    if mode in _MODES:
        new.mode = mode
        if mode == MODE_MONO:
            new.target_perimeter_level = LEVEL_SOCIAL
        elif mode in (MODE_GROUPE, MODE_CONSO):
            new.target_perimeter_level = LEVEL_CONSOLIDE
    if target_entity is not None:
        new.target_entity = target_entity.strip()
    if target_perimeter_level in (LEVEL_CONSOLIDE, LEVEL_SOCIAL, LEVEL_SEGMENT):
        new.target_perimeter_level = target_perimeter_level
    if declared_entities is not None:
        new.declared_entities = [e.strip() for e in declared_entities if e and e.strip()]
    if output_target in (OUTPUT_EXPLORATOIRE, OUTPUT_INTERNE, OUTPUT_BOARD_SAFE):
        new.output_target = output_target
    new.user_override = True
    new.override_reason = (reason or "").strip() or "surcharge utilisateur"
    new.inferred_from = INFERRED_USER
    new.inference_confidence = CONF_HIGH
    new.inference_signals = list(ctx.inference_signals) + ["user_override"]
    return new
