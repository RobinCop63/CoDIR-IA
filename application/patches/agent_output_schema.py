"""
CoDIR-IA — agent_output_schema v1.0 (v16.5.66 — livraison 2 pilote Finance)

Module autonome de parsing et validation des sorties agents typées JSON.

Contexte
--------
Avant v16.5.66, les agents métier (Stratégie, Marketing, Finance, Commercial, Synthèse)
produisaient uniquement du markdown. Le scorer devait inférer les métriques par regex
sur le markdown, avec trois limites :
  1. Les tags [FAIT]/[REF SECT.]/[ESTIM. IA] étaient auto-déclarés par l'agent sans
     contrôle pipeline → risque de self-promotion.
  2. Aucune information de decision_weight (critical/structural/contextual) n'était
     disponible → cap contextuel inopérant.
  3. Le scorer tournait en "mode v4 basique" avec all_metrics=[], plafonnant à ~65.

À partir de v16.5.66, chaque agent pilote produit EN PLUS de son markdown un bloc
JSON structuré encadré par les balises ---AGENT_JSON_START--- / ---AGENT_JSON_END---
contenant une liste de claims typées, consommable directement par le scorer.

Philosophie
-----------
- FAIL-OPEN : si le bloc JSON est absent ou malformé, le pipeline retombe sur le
  comportement v16.5.65 (scorer en mode basique). Pas de blocage, juste une pénalité
  MISSING_AGENT_JSON_CLAIMS ajoutée.
- MARKDOWN TOUJOURS PRÉSENT : le JSON est en SUS, jamais en remplacement. Un humain
  doit toujours pouvoir lire le livrable.
- RECLASSIFICATION CÔTÉ PIPELINE : même si l'agent déclare un tag "FAIT", le scorer
  reclassifie via classify_source_quality_level. Un agent ne peut pas se promouvoir.

Schéma
------
    ---AGENT_JSON_START---
    {
      "claims": [
        {
          "id": "C1",
          "text": "Le marché pèse 950-1050 M€ en 2026",
          "tag": "REF_SECT",
          "source_ref": "Xerfi - Conseil en transition 2026",
          "decision_weight": "structural",
          "confidence": "high"
        },
        ...
      ],
      "role_summary": {
        "owners_assigned": true,
        "recommended_option": "Spécialisation ETI",
        "primary_growth_driver": null,
        "execution_risk": null,
        "daf_checklist_complete": true
      }
    }
    ---AGENT_JSON_END---

Module PUR — aucun I/O réseau, aucune dépendance externe.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from typing import Any


# =============================================================================
# CONSTANTES
# =============================================================================

# Balises d'encadrement dans la sortie agent
JSON_START_TAG = "---AGENT_JSON_START---"
JSON_END_TAG   = "---AGENT_JSON_END---"

# Tags valides pour une claim (doivent rester alignés avec le scorer)
VALID_TAGS = {"FAIT", "REF_SECT", "ESTIM", "CALCUL", "HYPOTHÈSE", "INCERTAIN"}

# Mapping vers les tags internes du scorer (compat v4/v5)
TAG_TO_SCORER = {
    "FAIT":      "FAIT",         # sera reclassé FAIT_VERIFIED/FAIT_ASSERTED par pipeline
    "REF_SECT":  "FAIT",         # référence sectorielle = fait avec source publique
    "ESTIM":     "HYPOTHÈSE",    # inférence modèle
    "CALCUL":    "CALCUL",
    "HYPOTHÈSE": "HYPOTHÈSE",
    "INCERTAIN": "INCERTAIN",
}

VALID_DECISION_WEIGHTS = {"critical", "structural", "contextual"}
VALID_CONFIDENCE_LEVELS = {"high", "medium", "low"}

# Limites de sécurité
MAX_CLAIMS_PER_AGENT = 50     # garde-fou contre dump JSON géant
MAX_CLAIM_TEXT_LEN   = 500    # caractères max dans claim.text
MIN_CLAIM_TEXT_LEN   = 10     # trop court = probable bruit


# =============================================================================
# DATACLASSES
# =============================================================================

# =============================================================================
# v62.13.9.4.11 (A1) — DIMENSIONS QUANTITATIVES DÉCLARÉES À LA GÉNÉRATION
# =============================================================================
#
# Contre-audit du 31/08/2026 : « tant que ces questions ne sont pas
# représentées explicitement, nous continuerons à trouver une nouvelle
# formulation qui échappe aux règles ». Qui décide ? Passé, présent ou
# futur ? Le nombre est-il un fait, une hypothèse, une option ou une cible ?
# Quelle métrique, quelle entité, quelle preuve ?
#
# Ces questions ne se devinent pas de manière fiable à partir du texte
# sérialisé — six cycles de règles l'ont montré. En revanche, l'agent qui
# ÉCRIT la phrase les connaît au moment où il l'écrit. On les lui fait donc
# déclarer, au lieu de les reconstituer en aval.
#
# LIGNE DE PARTAGE, non négociable : l'agent déclare ce qu'il VEUT DIRE
# (nature, modalité, métrique, période, entité) ; il ne déclare JAMAIS que
# c'est PROUVÉ. Le statut probatoire reste établi par la chaîne de preuve à
# partir des pièces. Un agent ne peut pas se promouvoir — c'est la règle qui
# gouverne déjà les tags de ce module, étendue aux grandeurs.

VALID_NATURES = {
    "FAIT",        # grandeur constatée, rattachable à une pièce
    "CIBLE",       # engagement chiffré sur l'avenir
    "OPTION",      # alternative soumise à décision
    "SCENARIO",    # projection conditionnelle
    "APPAREIL",    # mesure de l'outil sur lui-même (score, compte de preuves)
}
VALID_MODALITIES = {
    "CONSTATE",    # observé dans une pièce
    "DECIDE",      # arrêté par une instance
    "SOUHAITE",    # voulu, sans décision
    "RECOMMANDE",  # proposé par l'analyse
    "HYPOTHETIQUE",
}
VALID_TIME_FRAMES = {"PASSE", "PRESENT", "FUTUR"}


@dataclass
class Quantity:
    """Une grandeur chiffrée, décrite par l'agent qui l'écrit.

    Deux formulations différentes du même engagement doivent produire le même
    objet : « Le conseil a validé 24 M€ de budget marketing » et « The board
    approved a £24m marketing budget » se décrivent identiquement, au libellé
    et à la devise près. Le texte devient secondaire.
    """
    value: str                          # tel qu'écrit : « 24 », « 2,46 »
    nature: str = "FAIT"                # FAIT | CIBLE | OPTION | SCENARIO | APPAREIL
    modality: str = "CONSTATE"          # CONSTATE | DECIDE | SOUHAITE | RECOMMANDE | HYPOTHETIQUE
    time_frame: str = "PRESENT"         # PASSE | PRESENT | FUTUR
    metric: str | None = None           # « chiffre d'affaires », « ouvertures »
    unit: str | None = None             # « M€ », « centres », « % »
    period: str | None = None           # « FY2026 », « 2027 », « 24 mois »
    entity: str | None = None           # « dossier réseau de soins France », « groupe »
    source_doc: str | None = None       # pièce invoquée par l'agent
    source_page: str | None = None
    decided_by: str | None = None       # instance, quand modality == DECIDE
    nature_raw: str | None = None       # v62.13.9.4.16 — nature écrite par l'agent avant rangement (CALCUL, ESTIM)

    def is_prospective(self) -> bool:
        """Vrai si la grandeur engage l'avenir — indépendamment du VERBE
        employé, et indépendamment du temps grammatical de la phrase : « le
        conseil A VALIDÉ 24 M€ » est au passé mais décide l'avenir.

        v62.13.9.4.13 — une déclaration MALFORMED est traitée comme
        prospective : on ne sait pas ce qu'elle engage, donc on retient.
        C'est le sens fail-closed, à l'inverse du repli vers FAIT.
        """
        return (self.nature in {"CIBLE", "OPTION", "SCENARIO", "MALFORMED"}
                or self.modality in {"DECIDE", "SOUHAITE", "RECOMMANDE",
                                     "HYPOTHETIQUE", "MALFORMED"}
                or self.time_frame in {"FUTUR", "MALFORMED"})

    def is_malformed(self) -> bool:
        return "MALFORMED" in (self.nature, self.modality, self.time_frame)

    def normalised(self) -> dict:
        """Forme comparable, indépendante de la formulation."""
        return {
            "value": _norm_value(self.value),
            "nature": self.nature,
            "modality": self.modality,
            "time_frame": self.time_frame,
            "metric": (self.metric or "").strip().lower() or None,
            "unit": (self.unit or "").strip() or None,
            "period": (self.period or "").strip().upper() or None,
            "entity": (self.entity or "").strip().lower() or None,
        }


def _norm_value(raw: str) -> str:
    """« 2,46 » et « 2.46 » sont la même valeur ; « 1 200 » et « 1200 » aussi."""
    s = re.sub(r"[\s\u00A0\u202F]", "", str(raw or ""))
    return s.replace(",", ".")


# v62.13.9.4.13 — NETTOYAGE DES ANNOTATIONS ÉDITORIALES.
# Le run du 02/09/2026 a établi que les annotateurs de prose écrivent leurs
# marques À L'INTÉRIEUR des champs du bloc JSON : 44 occurrences de
# « CIBLE [NON SOURCÉ] », 42 de « FUTUR [NON SOURCÉ] », 30 de
# « CONSTATE [NON SOURCÉ] ». Ces valeurs ne correspondent plus aux
# énumérations, et le repli les ramenait à FAIT / CONSTATE / PRESENT : une
# cible correctement produite par le modèle devenait un fait.
# On retire l'annotation avant de comparer — le fond de la déclaration est
# intact, seule la marque éditoriale s'y était collée.
_EDITORIAL_MARK_RE = re.compile(
    r"\s*[\[(]\s*(?:NON\s+SOURC[ÉE]|NOT\s+SOURCED|À\s+V[ÉE]RIFIER|"
    r"TO\s+VERIFY|ESTIM\.?|ESTIMATION|NON\s+[ÉE]TABLIE?)\s*[\])]\s*",
    re.I)


def _clean_enum(raw: Any) -> str:
    """Valeur d'énumération débarrassée des annotations éditoriales.

    v62.13.9.4.22 — les ACCENTS ne font pas une valeur hors contrat :
    « RECOMMANDÉ », « HYPOTHÉTIQUE », « DÉCIDÉ », « PASSÉ », « PRÉSENT » sont
    les valeurs du contrat écrites en français (run réel du 05/09/2026 :
    12 modalités DG en MALFORMED pour un accent).
    """
    import unicodedata
    s = _EDITORIAL_MARK_RE.sub(" ", str(raw or ""))
    s = re.sub(r"\s+", " ", s).strip().upper()
    s = "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")
    return s.replace("_", "").replace("-", "") if s in ("NON_SOURCE", "NON-SOURCE") else s


def _coerce_quantity(raw: Any) -> "Quantity | None":
    """Strict sur les valeurs : une énumération invalide n'est JAMAIS ramenée
    au défaut le plus favorable.

    v62.13.9.4.13 — le repli d'origine (« nature inconnue → FAIT ») était une
    permissivité de fond documentée comme une tolérance de forme. Il
    contredisait la doctrine fail-closed appliquée partout ailleurs et a
    détruit 21 déclarations sur 63 au run réel. Une valeur illisible produit
    désormais une entrée MALFORMED, comptée et exposée, jamais un fait.
    """
    if not isinstance(raw, dict):
        return None
    value = str(raw.get("value") or "").strip()
    value = _EDITORIAL_MARK_RE.sub(" ", value).strip()
    if not value:
        return None
    nature = _clean_enum(raw.get("nature")) or "MALFORMED"
    modality = _clean_enum(raw.get("modality")) or "MALFORMED"
    tf = _clean_enum(raw.get("time_frame")) or "MALFORMED"
    # v62.13.9.4.16 — TAXONOMIE ÉTENDUE, décision Robin + ChatGPT du 03/09/2026.
    # Les modèles écrivent « CALCUL » (grandeur dérivée de faits sourcés :
    # 800 M€ × 70 % = 560 M€) et « ESTIM » (estimation). Ce sont des nuances
    # exactes, pas des erreurs : 10 MALFORMED sur le run 09:55 pour ces deux
    # seuls mots. Rangement, tracé dans ``nature_raw`` :
    #   ESTIM / ESTIMATION / ESTIMATE  → SCENARIO (projection ou ordre de grandeur)
    #   CALCUL / CALC / DERIVED / COMPUTED → FAIT si la modalité est CONSTATE
    #     (calcul sur des constats), sinon SCENARIO. Un calcul n'est jamais
    #     promu au-dessus de ses entrées.
    nature_raw = nature
    if nature in ("ESTIM", "ESTIMATION", "ESTIMATE", "ESTIMATED"):
        nature = "SCENARIO"
    elif nature in ("CALCUL", "CALC", "CALCULE", "CALCULÉ", "DERIVED", "COMPUTED", "DERIVE", "DÉRIVÉ"):
        nature = "FAIT" if modality == "CONSTATE" else "SCENARIO"
    # v62.13.9.4.19.2 — run réel 20:23 : « HYPOTHESE » écrit comme nature (5
    # MALFORMED, tous HYPOTHETIQUE/FUTUR). Une hypothèse est un scénario ;
    # un objectif ou une projection, une cible. Tracé dans nature_raw.
    elif nature in ("HYPOTHESE", "HYPOTHÈSE", "HYPOTHESIS", "ASSUMPTION", "PROJECTION", "PROJECTED", "FORECAST", "PREVISION", "PRÉVISION"):
        nature = "SCENARIO"
    elif nature in ("OBJECTIF", "OBJECTIVE", "TARGET", "GOAL", "SEUIL", "THRESHOLD"):
        nature = "CIBLE"
    return Quantity(
        value=value,
        nature=nature if nature in VALID_NATURES else "MALFORMED",
        nature_raw=(nature_raw if (nature_raw != nature or nature not in VALID_NATURES) else None),
        modality=modality if modality in VALID_MODALITIES else "MALFORMED",
        time_frame=tf if tf in VALID_TIME_FRAMES else "MALFORMED",
        metric=(str(raw.get("metric")).strip() if raw.get("metric") else None),
        unit=(str(raw.get("unit")).strip() if raw.get("unit") else None),
        period=(str(raw.get("period")).strip() if raw.get("period") else None),
        entity=(str(raw.get("entity")).strip() if raw.get("entity") else None),
        source_doc=(str(raw.get("source_doc")).strip() if raw.get("source_doc") else None),
        source_page=(str(raw.get("source_page")).strip() if raw.get("source_page") else None),
        decided_by=(str(raw.get("decided_by")).strip() if raw.get("decided_by") else None),
    )


@dataclass
class Claim:
    """Une affirmation produite par un agent, destinée au scorer."""
    text: str
    tag: str                            # FAIT | REF_SECT | ESTIM | CALCUL | HYPOTHÈSE | INCERTAIN
    id: str = ""
    source_ref: str | None = None       # ex: "Liasse 2024 p.7", "Xerfi 2026"
    decision_weight: str = "structural" # critical | structural | contextual
    confidence: str = "medium"          # high | medium | low
    quantities: list[Quantity] = field(default_factory=list)  # A1

    def prospective_quantities(self) -> list[Quantity]:
        return [q for q in self.quantities if q.is_prospective()]

    def to_scorer_metric(self, role: str = "") -> dict:
        """
        Convertit la claim au format attendu par confidence_scorer.reclassify_metrics().
        Le tag FAIT sera reclassé FAIT_VERIFIED ou FAIT_ASSERTED selon la source.
        """
        scorer_tag = TAG_TO_SCORER.get(self.tag, "INCERTAIN")

        # Construction du source dict attendu par classify_source_quality_level
        source: dict[str, Any] = {}
        if self.tag == "REF_SECT" and self.source_ref:
            # Référence sectorielle publique → base_publique niveau standard
            source = {
                "type": "base_publique",
                "url": self.source_ref,
                "date_consultation": None,  # pas toujours fourni
            }
        elif self.source_ref and self.tag == "FAIT":
            # Fait avec source → document_fourni (sera reclassé par le pipeline
            # selon que le fichier est réellement attaché ou non)
            source = {
                "type": "document_fourni",
                "doc_ref": self.source_ref,
            }
        elif self.tag in ("ESTIM", "HYPOTHÈSE", "INCERTAIN"):
            source = {"type": "infer_explicit"}
        else:
            source = {"type": "unknown"}

        return {
            "tag": scorer_tag,
            "source": source,
            "decision_weight": self.decision_weight,
            "text": self.text,
            "agent_role": role,
            "agent_declared_tag": self.tag,  # pour traçabilité
            "agent_confidence": self.confidence,
        }


@dataclass
class RoleSummary:
    """
    Signaux meta de l'agent destinés aux completeness_checks du scorer.
    Chaque champ est optionnel — les champs None ne sont pas pris en compte.
    """
    owners_assigned: bool | None = None
    recommended_option: str | None = None
    primary_growth_driver: str | None = None
    execution_risk: str | None = None
    daf_checklist_complete: bool | None = None


@dataclass
class AgentOutput:
    """Sortie typée d'un agent, parsée depuis le bloc JSON balisé."""
    role: str                            # finance | marketing | strategie | ...
    claims: list[Claim] = field(default_factory=list)
    role_summary: RoleSummary = field(default_factory=RoleSummary)
    parse_status: str = "OK"             # OK | MISSING | MALFORMED | PARTIAL
    parse_errors: list[str] = field(default_factory=list)

    @property
    def claims_count(self) -> int:
        return len(self.claims)

    def to_scorer_metrics(self) -> list[dict]:
        return [c.to_scorer_metric(role=self.role) for c in self.claims]

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "parse_status": self.parse_status,
            "parse_errors": self.parse_errors,
            "claims_count": self.claims_count,
            "claims": [asdict(c) for c in self.claims],
            "role_summary": asdict(self.role_summary),
        }


# =============================================================================
# PARSING
# =============================================================================

def _extract_json_block(raw_text: str) -> str | None:
    """
    Extrait le contenu entre les balises JSON_START_TAG et JSON_END_TAG.
    Retourne None si aucune balise trouvée, ou si le bloc est vide.

    Since v16.5.67.7 — Mode tolérant : si JSON_START_TAG est présent mais pas
    JSON_END_TAG (cas observé en prod : LLM coupé par max_tokens avant la
    balise de fin), on tente d'équilibrer les accolades et de récupérer un
    JSON syntaxiquement valide depuis le contenu disponible.
    """
    if not raw_text:
        return None

    # Recherche non gourmande du premier bloc bien formé
    pattern = re.escape(JSON_START_TAG) + r"(.*?)" + re.escape(JSON_END_TAG)
    m = re.search(pattern, raw_text, flags=re.DOTALL)
    if m:
        block = m.group(1).strip()
        if not block:
            return None
        # Tolérance : certains modèles entourent le JSON de backticks ```json ... ```
        if block.startswith("```"):
            block = re.sub(r"^```(?:json)?\s*", "", block)
            block = re.sub(r"\s*```$", "", block)
            block = block.strip()
        return block or None

    # v16.5.67.7 — FALLBACK : START présent, END absent (réponse tronquée)
    # Observé sur 4 runs consécutifs : le LLM produit un JSON valide à 90%
    # puis est coupé par max_tokens avant ---AGENT_JSON_END---.
    # On tente de récupérer un JSON parsable en équilibrant les accolades.
    start_idx = raw_text.find(JSON_START_TAG)
    if start_idx < 0:
        return None

    partial = raw_text[start_idx + len(JSON_START_TAG):].strip()
    if not partial:
        return None

    # Strip backticks ```json si présents
    if partial.startswith("```"):
        partial = re.sub(r"^```(?:json)?\s*", "", partial).strip()
        # ne pas stripper ``` de fin ici car la réponse est tronquée

    # Trouver le premier '{' qui ouvre le JSON
    brace_start = partial.find("{")
    if brace_start < 0:
        return None

    # Parcourir caractère par caractère pour équilibrer { } en respectant
    # les guillemets et échappements (JSON peut contenir des {} dans des strings)
    depth = 0
    in_string = False
    escape_next = False
    last_balanced_close = -1
    for i in range(brace_start, len(partial)):
        ch = partial[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last_balanced_close = i
                break

    if last_balanced_close > brace_start:
        # JSON complètement équilibré trouvé dans les caractères avant la coupure
        candidate = partial[brace_start:last_balanced_close + 1].strip()
        return candidate or None

    # Aucun JSON équilibré complet → tenter une réparation minimaliste.
    # Stratégie : parcourir les { } [ ] en gérant strings/escapes, et
    # mémoriser toutes les positions où une structure pourrait se fermer
    # proprement. Pour un JSON de forme {"claims": [...], "role_summary": {...}},
    # on cherche la dernière position où un objet (une claim) se ferme
    # à l'intérieur du tableau claims (depth_curly retombe de 2 à 1 avec
    # depth_square == 1). C'est le bon point de coupure pour garder toutes
    # les claims complètes et abandonner role_summary tronqué.
    in_string = False
    escape_next = False
    depth_curly = 0
    depth_square = 0
    last_claim_close = -1   # position (inclusif) du } qui ferme une claim complète
    for i in range(brace_start, len(partial)):
        ch = partial[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth_curly += 1
        elif ch == "}":
            depth_curly -= 1
            # Fermeture d'une claim : on était dans un tableau (depth_square>=1)
            # et le } ramène à depth_curly == 1 (root encore ouvert, tableau ouvert)
            if depth_curly == 1 and depth_square >= 1:
                last_claim_close = i
        elif ch == "[":
            depth_square += 1
        elif ch == "]":
            depth_square -= 1

    if last_claim_close < 0:
        return None

    # Tronquer au dernier } de claim complète et fermer proprement
    # "claims": [ ... ] } — pas de role_summary si incomplet.
    truncated = partial[brace_start:last_claim_close + 1]
    # À ce point, depth_curly dans truncated doit être 1 (root ouvert) et
    # depth_square doit être 1 (tableau claims ouvert).
    repair = truncated + "]}"

    try:
        json.loads(repair)
        return repair.strip()
    except Exception:
        return None


def _validate_claim(raw: dict, index: int) -> tuple[Claim | None, list[str]]:
    """
    Valide un dict claim et retourne (Claim, errors).
    Si la claim est irrécupérable, retourne (None, errors) et l'ignore.
    """
    errors: list[str] = []

    if not isinstance(raw, dict):
        return None, [f"claim[{index}] n'est pas un objet JSON"]

    # text : obligatoire, non vide
    text = raw.get("text", "")
    if not isinstance(text, str):
        text = str(text) if text is not None else ""
    text = text.strip()
    if not text:
        return None, [f"claim[{index}] sans champ 'text' — ignorée"]
    if len(text) < MIN_CLAIM_TEXT_LEN:
        # Trop court mais on garde quand même (souvent des valeurs numériques isolées)
        errors.append(f"claim[{index}] text très court ({len(text)} chars)")
    if len(text) > MAX_CLAIM_TEXT_LEN:
        text = text[:MAX_CLAIM_TEXT_LEN] + "…"
        errors.append(f"claim[{index}] text tronqué à {MAX_CLAIM_TEXT_LEN} chars")

    # tag : obligatoire, valeur dans VALID_TAGS
    tag = raw.get("tag", "")
    if not isinstance(tag, str):
        tag = str(tag)
    # v62.13.9.4.15 — le champ ``tag`` recevait lui aussi les annotations
    # éditoriales (« CIBLE [NON SOURCÉ] » au run du 02/09/2026 15:04 →
    # fallback INCERTAIN et statut PARTIAL). La sanctuarisation du bloc
    # A1 en amont rend le cas improbable ; le nettoyage reste, par symétrie
    # avec nature/modality/time_frame. Un agent qui met une NATURE A1
    # (CIBLE/OPTION/SCENARIO) dans le tag de claim exprime une prospective :
    # elle est rangée en HYPOTHÈSE, jamais blanchie en FAIT.
    tag = _EDITORIAL_MARK_RE.sub(" ", tag)
    tag = tag.strip().upper().replace(" ", "_")
    if tag in ("CIBLE", "OPTION", "SCENARIO", "SCÉNARIO", "APPAREIL"):
        tag = "HYPOTHÈSE"
    # Normalisations tolérantes
    tag = tag.replace("-", "_").replace(".", "")
    if tag in ("REFSECT", "REFSECTORIEL", "REFSECTO"):
        tag = "REF_SECT"
    if tag in ("ESTIMATION", "ESTIMIA", "ESTIMIA_"):
        tag = "ESTIM"
    if tag in ("HYPOTHESE", "HYPO"):
        tag = "HYPOTHÈSE"
    # v17.1 (P1-09) — Tags doctrine Q2 hyphénés normalisés vers la taxonomie
    # interne du schéma. Corrige le fallback INCERTAIN observé sur le run Lhyfe
    # (l'agent DG émettait ESTIM-FILINGS / ESTIM-HYPOTHÈSE, rejetés faute de
    # mapping). Note : l'upstream a déjà fait .upper() + remplacé '-' par '_'.
    if tag in ("ESTIM_FILINGS", "ESTIMFILINGS"):
        tag = "REF_SECT"        # estimation étayée par comptes publiés = sourcée
    if tag in ("ESTIM_COMPARABLE", "ESTIMCOMPARABLE"):
        tag = "ESTIM"           # estimation par comparables
    if tag in ("ESTIM_HYPOTHÈSE", "ESTIM_HYPOTHESE", "ESTIMHYPOTHÈSE", "ESTIMHYPOTHESE"):
        tag = "HYPOTHÈSE"       # estimation hypothétique
    # v17.1-B2 (B-03) — synonymes de tags INVENTÉS par les agents (observé : DG
    # émettait « RECOMMANDÉ » → fallback INCERTAIN, pénalisé à tort). On mappe les
    # familles reconnaissables vers la taxonomie au lieu de tout jeter en INCERTAIN.
    _TAG_SYNONYMS = {
        "RECOMMANDÉ": "ESTIM", "RECOMMANDE": "ESTIM", "RECOMMANDATION": "ESTIM",
        "RECO": "ESTIM", "RECOMMENDED": "ESTIM", "RECOMMENDATION": "ESTIM",
        "FACT": "FAIT", "FACTUEL": "FAIT", "FACTUAL": "FAIT", "FAITS": "FAIT",
        "REFERENCE": "REF_SECT", "RÉFÉRENCE": "REF_SECT", "REF": "REF_SECT",
        "SECTION": "REF_SECT", "SOURCE": "REF_SECT", "SOURCÉ": "REF_SECT",
        "ESTIMATE": "ESTIM", "ESTIMÉ": "ESTIM", "ESTIME": "ESTIM",
        "CALCULÉ": "CALCUL", "CALCULE": "CALCUL", "CALCULATED": "CALCUL",
        "COMPUTED": "CALCUL", "CALC": "CALCUL",
        "HYPOTHESIS": "HYPOTHÈSE", "ASSUMPTION": "HYPOTHÈSE", "HYP": "HYPOTHÈSE",
        "UNCERTAIN": "INCERTAIN", "INCERTAINE": "INCERTAIN", "DOUTE": "INCERTAIN",
    }
    if tag not in VALID_TAGS and tag in _TAG_SYNONYMS:
        tag = _TAG_SYNONYMS[tag]
    if tag not in VALID_TAGS:
        errors.append(f"claim[{index}] tag '{raw.get('tag')}' invalide → fallback INCERTAIN")
        tag = "INCERTAIN"

    # source_ref : optionnel, str | null
    source_ref = raw.get("source_ref")
    if source_ref is not None:
        if not isinstance(source_ref, str):
            source_ref = str(source_ref)
        source_ref = source_ref.strip() or None

    # decision_weight : optionnel, défaut structural
    dw = raw.get("decision_weight", "structural")
    if not isinstance(dw, str):
        dw = "structural"
    dw = dw.strip().lower()
    if dw not in VALID_DECISION_WEIGHTS:
        errors.append(f"claim[{index}] decision_weight '{dw}' invalide → structural")
        dw = "structural"

    # confidence : optionnel, défaut medium
    conf = raw.get("confidence", "medium")
    if not isinstance(conf, str):
        conf = "medium"
    conf = conf.strip().lower()
    if conf not in VALID_CONFIDENCE_LEVELS:
        errors.append(f"claim[{index}] confidence '{conf}' invalide → medium")
        conf = "medium"

    # id : optionnel
    claim_id = raw.get("id", "") or f"C{index+1}"
    if not isinstance(claim_id, str):
        claim_id = str(claim_id)

    # v62.13.9.4.11 (A1) — grandeurs déclarées. Fail-open sur la forme :
    # une liste absente ou mal typée n'invalide pas la claim, elle laisse
    # simplement la chaîne aval retomber sur l'analyse textuelle.
    quantities: list[Quantity] = []
    raw_q = raw.get("quantities")
    if isinstance(raw_q, list):
        for qi, item in enumerate(raw_q):
            q = _coerce_quantity(item)
            if q is None:
                errors.append(f"claim[{index}].quantities[{qi}] ignorée (forme invalide)")
                continue
            quantities.append(q)
    elif raw_q is not None:
        errors.append(f"claim[{index}] quantities n'est pas une liste → ignoré")

    return Claim(
        id=claim_id,
        text=text,
        tag=tag,
        source_ref=source_ref,
        decision_weight=dw,
        confidence=conf,
        quantities=quantities,
    ), errors


def _validate_role_summary(raw: dict | None) -> tuple[RoleSummary, list[str]]:
    """Valide la section role_summary. Tolère les valeurs absentes."""
    if raw is None:
        return RoleSummary(), []
    if not isinstance(raw, dict):
        return RoleSummary(), [f"role_summary n'est pas un objet JSON — ignoré"]

    errors: list[str] = []

    def _bool_or_none(v: Any, field_name: str) -> bool | None:
        if v is None:
            return None
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            if v.lower() in ("true", "yes", "oui"):
                return True
            if v.lower() in ("false", "no", "non"):
                return False
        errors.append(f"role_summary.{field_name} type inattendu ({type(v).__name__}) — ignoré")
        return None

    def _str_or_none(v: Any, field_name: str) -> str | None:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s or None
        errors.append(f"role_summary.{field_name} type inattendu ({type(v).__name__}) — ignoré")
        return None

    return RoleSummary(
        owners_assigned=_bool_or_none(raw.get("owners_assigned"), "owners_assigned"),
        recommended_option=_str_or_none(raw.get("recommended_option"), "recommended_option"),
        primary_growth_driver=_str_or_none(raw.get("primary_growth_driver"), "primary_growth_driver"),
        execution_risk=_str_or_none(raw.get("execution_risk"), "execution_risk"),
        daf_checklist_complete=_bool_or_none(raw.get("daf_checklist_complete"), "daf_checklist_complete"),
    ), errors


def parse_agent_output(raw_text: str, role: str = "") -> AgentOutput:
    """
    Fonction principale — parse la sortie texte d'un agent et retourne un AgentOutput.

    Comportement fail-open :
    - Pas de bloc JSON → parse_status=MISSING, claims=[]
    - JSON malformé    → parse_status=MALFORMED, claims=[]
    - JSON parsable mais certaines claims invalides → parse_status=PARTIAL,
      claims = celles qui ont pu être validées
    - Tout OK → parse_status=OK

    Jamais de levée d'exception — toujours un AgentOutput utilisable (même vide).
    """
    output = AgentOutput(role=role)

    # Extraction du bloc
    block = _extract_json_block(raw_text)
    if block is None:
        output.parse_status = "MISSING"
        output.parse_errors.append(f"Aucun bloc {JSON_START_TAG}…{JSON_END_TAG} trouvé.")
        return output

    # Parsing JSON
    try:
        data = json.loads(block)
    except json.JSONDecodeError as e:
        output.parse_status = "MALFORMED"
        output.parse_errors.append(f"JSON invalide ligne {e.lineno} col {e.colno} : {e.msg}")
        # Tentative de récupération : extraire la partie claims si possible
        return output

    if not isinstance(data, dict):
        output.parse_status = "MALFORMED"
        output.parse_errors.append(f"Racine JSON n'est pas un objet (type {type(data).__name__}).")
        return output

    # Validation claims
    raw_claims = data.get("claims", [])
    claims_type_error = False
    if not isinstance(raw_claims, list):
        claims_type_error = True
        output.parse_errors.append("Champ 'claims' n'est pas une liste.")
        raw_claims = []

    if len(raw_claims) > MAX_CLAIMS_PER_AGENT:
        output.parse_errors.append(
            f"Trop de claims ({len(raw_claims)} > {MAX_CLAIMS_PER_AGENT}) — troncature."
        )
        raw_claims = raw_claims[:MAX_CLAIMS_PER_AGENT]

    had_error = False
    for i, raw in enumerate(raw_claims):
        claim, errors = _validate_claim(raw, i)
        output.parse_errors.extend(errors)
        if claim is None:
            had_error = True
            continue
        output.claims.append(claim)

    # Validation role_summary
    summary, summary_errors = _validate_role_summary(data.get("role_summary"))
    output.role_summary = summary
    output.parse_errors.extend(summary_errors)

    # Statut final (priorité : erreur structurelle > erreur partielle > OK)
    if claims_type_error:
        output.parse_status = "MALFORMED"
    elif had_error or output.parse_errors:
        output.parse_status = "PARTIAL"
    elif not output.claims:
        # JSON valide mais aucune claim → on laisse PARTIAL pour signaler
        # qu'il y a eu du contenu extrait mais rien d'exploitable
        output.parse_status = "PARTIAL" if "claims" not in data else "OK"
    else:
        output.parse_status = "OK"

    return output


# =============================================================================
# HELPER — documentation du schéma à injecter dans les prompts agents
# =============================================================================

SCHEMA_INSTRUCTION_FR = (
    "\n\n---\n"
    "SORTIE OBLIGATOIRE — BLOC JSON STRUCTURÉ (v16.5.66) :\n\n"
    "En plus de ton analyse en markdown ci-dessus, tu DOIS produire en FIN de réponse "
    "un bloc JSON encadré par des balises précises, listant tes affirmations numériques "
    "et factuelles clés (5 à 15 claims). Ce bloc est consommé par le pipeline pour le "
    "scoring de confiance — il ne remplace PAS ton analyse markdown.\n\n"
    "FORMAT EXACT :\n"
    "---AGENT_JSON_START---\n"
    "{\n"
    '  "claims": [\n'
    "    {\n"
    '      "id": "C1",\n'
    '      "text": "Le marché français pèse 950-1050 M€ en 2026",\n'
    '      "tag": "REF_SECT",\n'
    '      "source_ref": "Xerfi - Conseil en transition 2026",\n'
    '      "decision_weight": "structural",\n'
    '      "confidence": "high"\n'
    "    }\n"
    "  ],\n"
    '  "role_summary": {\n'
    '    "owners_assigned": true,\n'
    '    "recommended_option": "Spécialisation sur ETI",\n'
    '    "daf_checklist_complete": true\n'
    "  }\n"
    "}\n"
    "---AGENT_JSON_END---\n\n"
    "RÈGLES :\n"
    "- tag ∈ {FAIT, REF_SECT, ESTIM, CALCUL, HYPOTHÈSE, INCERTAIN}\n"
    "  • FAIT      = donnée tirée d'un document fourni (cite la source dans source_ref)\n"
    "  • REF_SECT  = benchmark sectoriel public vérifiable (Xerfi, INSEE, FNMT, etc.)\n"
    "  • ESTIM     = inférence du modèle sans source (source_ref = null)\n"
    "  • CALCUL    = dérivé arithmétiquement d'autres claims\n"
    "  • HYPOTHÈSE = hypothèse de travail explicite\n"
    "  • INCERTAIN = donnée dont la fiabilité est incertaine\n"
    "- decision_weight ∈ {critical, structural, contextual}\n"
    "  • critical   = la décision CoDIR dépend directement de cette claim\n"
    "  • structural = ordre de grandeur qui cadre la décision\n"
    "  • contextual = information de contexte secondaire\n"
    "- confidence ∈ {high, medium, low}\n"
    "- source_ref = string décrivant la source (\"Liasse 2024 p.7\") ou null\n"
    "- 5 à 15 claims — privilégier la qualité à la quantité\n"
    "- TOUS tes chiffres-clés doivent être une claim\n"
    "- Le bloc JSON doit être valide syntaxiquement — TESTE mentalement avant d'envoyer\n"
)

SCHEMA_INSTRUCTION_EN = (
    "\n\n---\n"
    "MANDATORY OUTPUT — STRUCTURED JSON BLOCK (v16.5.66):\n\n"
    "In addition to your markdown analysis above, you MUST produce at the END of your "
    "response a JSON block delimited by specific tags, listing your key numeric and "
    "factual claims (5 to 15 claims). This block is consumed by the pipeline for "
    "confidence scoring — it does NOT replace your markdown analysis.\n\n"
    "EXACT FORMAT:\n"
    "---AGENT_JSON_START---\n"
    "{\n"
    '  "claims": [\n'
    "    {\n"
    '      "id": "C1",\n'
    '      "text": "The French market is worth 950-1050 M€ in 2026",\n'
    '      "tag": "REF_SECT",\n'
    '      "source_ref": "Xerfi - Transition consulting 2026",\n'
    '      "decision_weight": "structural",\n'
    '      "confidence": "high"\n'
    "    }\n"
    "  ],\n"
    '  "role_summary": {\n'
    '    "owners_assigned": true,\n'
    '    "recommended_option": "Focus on mid-caps",\n'
    '    "daf_checklist_complete": true\n'
    "  }\n"
    "}\n"
    "---AGENT_JSON_END---\n\n"
    "RULES:\n"
    "- tag ∈ {FAIT, REF_SECT, ESTIM, CALCUL, HYPOTHÈSE, INCERTAIN}\n"
    "  • FAIT      = data taken from a provided document (cite source in source_ref)\n"
    "  • REF_SECT  = verifiable public sector benchmark (Xerfi, INSEE, industry body)\n"
    "  • ESTIM     = model inference without source (source_ref = null)\n"
    "  • CALCUL    = arithmetically derived from other claims\n"
    "  • HYPOTHÈSE = explicit working hypothesis\n"
    "  • INCERTAIN = data of uncertain reliability\n"
    "- decision_weight ∈ {critical, structural, contextual}\n"
    "- confidence ∈ {high, medium, low}\n"
    "- 5 to 15 claims — prefer quality over quantity\n"
    "- ALL your key figures must be a claim\n"
    "- The JSON block MUST be syntactically valid\n"
)


SCHEMA_INSTRUCTION_FR += (
    "\n\nRÈGLE DES GRANDEURS CHIFFRÉES (v62.13.9.4.11 — obligatoire dès qu'une "
    "claim contient un nombre) :\n"
    "Pour CHAQUE nombre du texte de la claim, ajoute une entrée dans \"quantities\". "
    "Tu décris ce que tu VEUX DIRE ; tu ne déclares jamais qu'un chiffre est prouvé — "
    "la chaîne de preuve en décide seule, sur pièces.\n\n"
    "  \"quantities\": [\n"
    "    {\n"
    "      \"value\": \"24\",              // tel qu'écrit, sans l'unité\n"
    "      \"nature\": \"CIBLE\",          // FAIT | CIBLE | OPTION | SCENARIO | APPAREIL\n"
    "      \"modality\": \"DECIDE\",       // CONSTATE | DECIDE | SOUHAITE | RECOMMANDE | HYPOTHETIQUE\n"
    "      \"time_frame\": \"FUTUR\",      // PASSE | PRESENT | FUTUR\n"
    "      \"metric\": \"budget marketing\",\n"
    "      \"unit\": \"M€\", \"period\": \"2027\", \"entity\": \"groupe\",\n"
    "      \"source_doc\": null, \"source_page\": null,\n"
    "      \"decided_by\": \"conseil\"     // si modality = DECIDE\n"
    "    }\n"
    "  ]\n\n"
    "Comment choisir :\n"
    "- FAIT : grandeur constatée dans une pièce ou un historique.\n"
    "- CIBLE : engagement chiffré sur l'avenir, QUEL QUE SOIT LE VERBE.\n"
    "- OPTION : alternative soumise à arbitrage (« 10 M€/an vs 15 M€/an »).\n"
    "- SCENARIO : projection conditionnelle.\n"
    "- APPAREIL : score ou compteur portant sur l'analyse elle-même.\n\n"
    "LE TEMPS DU VERBE NE DÉCIDE DE RIEN. « Le conseil a validé 24 M€ » est au "
    "passé mais engage l'avenir : nature CIBLE, modality DECIDE, time_frame FUTUR. "
    "« Le chiffre d'affaires a atteint 118 M€ en 2025 » est FAIT / CONSTATE / PASSE.\n"
    "Deux formulations différentes du même engagement doivent produire le MÊME objet. "
    "En cas d'hésitation entre FAIT et CIBLE, choisis CIBLE.\n"
    # v62.13.9.4.12.4 — le run réel du 01/09/2026 a montré des claims
    # parfaitement formées mais SANS aucune entrée « quantities », et un taux
    # de reprise de 23 % seulement entre les nombres écrits et les nombres
    # déclarés. La consigne doit être impérative, pas indicative.
    "\nRÈGLE IMPÉRATIVE — AUCUNE EXCEPTION : une claim dont le texte contient "
    "un chiffre DOIT porter une entrée \"quantities\" par chiffre. Une claim "
    "chiffrée sans \"quantities\" est une réponse INCOMPLÈTE. Cela vaut aussi "
    "pour les montants en toutes lettres, les pourcentages, les effectifs, les "
    "délais et les volumes. Si un chiffre du texte ne mérite pas d'être "
    "déclaré, retire-le du texte de la claim.\n"
)

SCHEMA_INSTRUCTION_EN += (
    "\n\nQUANTIFIED-MAGNITUDE RULE (v62.13.9.4.11 — mandatory whenever a claim "
    "contains a number):\n"
    "For EVERY number in the claim text, add an entry to \"quantities\". You describe "
    "what you MEAN; you never declare a figure proven — only the evidence chain "
    "decides that, on documents.\n\n"
    "  \"quantities\": [\n"
    "    {\n"
    "      \"value\": \"24\",              // as written, without the unit\n"
    "      \"nature\": \"CIBLE\",          // FAIT | CIBLE | OPTION | SCENARIO | APPAREIL\n"
    "      \"modality\": \"DECIDE\",       // CONSTATE | DECIDE | SOUHAITE | RECOMMANDE | HYPOTHETIQUE\n"
    "      \"time_frame\": \"FUTUR\",      // PASSE | PRESENT | FUTUR\n"
    "      \"metric\": \"marketing budget\",\n"
    "      \"unit\": \"£m\", \"period\": \"FY2027\", \"entity\": \"group\",\n"
    "      \"source_doc\": null, \"source_page\": null,\n"
    "      \"decided_by\": \"board\"       // when modality = DECIDE\n"
    "    }\n"
    "  ]\n\n"
    "How to choose:\n"
    "- FAIT: magnitude observed in a document or historical record.\n"
    "- CIBLE: quantified commitment about the future, WHATEVER THE VERB.\n"
    "- OPTION: alternative put to arbitration (\"£10m/yr vs £15m/yr\").\n"
    "- SCENARIO: conditional projection.\n"
    "- APPAREIL: score or counter about the analysis itself.\n\n"
    "VERB TENSE DECIDES NOTHING. \"The board approved £24m\" is past tense but commits "
    "the future: nature CIBLE, modality DECIDE, time_frame FUTUR. \"Revenue reached "
    "£2,420m in FY2026\" is FAIT / CONSTATE / PASSE.\n"
    "Two different wordings of the same commitment must produce the SAME object. "
    "When hesitating between FAIT and CIBLE, choose CIBLE.\n"
    "\nMANDATORY RULE — NO EXCEPTION: a claim whose text contains a figure MUST "
    "carry one \"quantities\" entry per figure. A numeric claim without "
    "\"quantities\" is an INCOMPLETE answer. This also applies to amounts "
    "written in words, percentages, headcounts, deadlines and volumes. If a "
    "figure in the text does not deserve a declaration, remove it from the "
    "claim text.\n"
)


def schema_instruction(lang: str = "fr") -> str:
    """Retourne les instructions de schéma à concaténer à un prompt agent."""
    return SCHEMA_INSTRUCTION_EN if lang == "en" else SCHEMA_INSTRUCTION_FR


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "Claim",
    "RoleSummary",
    "AgentOutput",
    "parse_agent_output",
    "schema_instruction",
    "SCHEMA_INSTRUCTION_FR",
    "SCHEMA_INSTRUCTION_EN",
    "JSON_START_TAG",
    "JSON_END_TAG",
    "VALID_TAGS",
    "VALID_DECISION_WEIGHTS",
    "VALID_CONFIDENCE_LEVELS",
    "TAG_TO_SCORER",
    "MAX_CLAIMS_PER_AGENT",
    "MAX_CLAIM_TEXT_LEN",
]
