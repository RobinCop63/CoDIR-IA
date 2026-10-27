"""
patches/entity_scope.py — M6-A2 (modèle entité / périmètre, 4 slots)

Problème mesuré par le probe a1_probe (EN + FR, même corpus dossier anglophone coté) :
    analysis_entity_candidate == legal_entity_candidate == dossier anglophone coté LIMITED
    ch_resolution_path = NAME_EXACT, provided_identifier = None
Cause : aucun identifiant au brief → recherche Companies House par nom → match
« dossier anglophone coté LIMITED » (la filiale légale) → adopté comme entité d'ANALYSE, alors
que le sujet métier est le groupe coté « dossier anglophone coté Group plc ».

Ce module sépare quatre entités distinctes et expose un périmètre financier, pour
que ni le rendu (en-tête CR) ni la table probante (M6-B) ne présentent des chiffres
CONSOLIDÉS GROUPE sous l'étiquette d'une ENTITÉ LÉGALE filiale.

Doctrine : « zéro latitude sur la présentation trompeuse ». Le module ne change pas
l'analyse ; il rend le périmètre explicite et honnête.

100 % déterministe, sans dépendance pipeline → testable en isolation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field
from typing import Optional, Dict, Any


# ── Signaux « groupe coté » dans le brief ────────────────────────────────────
# Présence de l'un de ces marqueurs ⇒ le sujet d'analyse est un groupe coté et NE
# DOIT PAS être réduit à une filiale Companies House homonyme.
_LISTED_MARKERS = re.compile(
    r"\b(plc|p\.l\.c\.|\blisted\b|publicly\s+traded|stock\s+exchange|"
    r"LSE\s*:|NYSE\s*:|NASDAQ\s*:|Euronext|bourse|cot[ée]e?|cotation|"
    r"ticker|ISIN|annual\s+report|interim\s+report|consolidated\s+(?:accounts|financial))\b",
    re.IGNORECASE,
)

# Extraction d'un nom de groupe depuis le brief.  Les champs explicites
# « Company: … » / « Société: … » priment sur la prose libre afin de ne jamais
# transformer « We are working today for dossier anglophone coté Group plc » en raison sociale.
_EXPLICIT_COMPANY_RE = re.compile(
    r"(?im)^\s*(?:Company|Soci[ée]t[ée]|Entreprise|Identity|Identit[ée])\s*:\s*"
    r"(?P<name>[^\n·;]{2,100})"
)
_GROUP_NAME_RES = [
    re.compile(r"([A-Z][\w&'\.\- ]{1,60}?\bGroup\s+p\.?l\.?c\.?)", re.IGNORECASE),
    re.compile(r"([A-Z][\w&'\.\- ]{1,60}?\bp\.?l\.?c\.?)\b", re.IGNORECASE),
    re.compile(r"([A-Z][\w&'\.\- ]{1,60}?\bGroup)\b"),
]
_BOILERPLATE_PREFIX_RE = re.compile(
    r"^(?:we\s+are\s+working\s+today\s+for|we\s+work\s+today\s+for|"
    r"nous\s+travaillons\s+aujourd['’]hui\s+pour(?:\s+le\s+groupe)?|"
    r"working\s+today\s+for)\s+",
    re.I,
)

# Suffixes de forme légale → indiquent une ENTITÉ LÉGALE (filiale potentielle),
# à ne pas confondre avec le groupe coté.
_LEGAL_SUFFIX = re.compile(r"\b(limited|ltd|sas|sasu|sarl|gmbh|inc|llc|s\.?a\.?|b\.?v\.?)\b",
                           re.IGNORECASE)


def detect_listed_group(brief: str) -> bool:
    """True si le brief signale explicitement un groupe coté."""
    return bool(_LISTED_MARKERS.search(brief or ""))


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).strip(" ·-—").upper()


def _base_brand(name: str) -> str:
    """Racine de marque : retire Group / forme légale / ticker pour comparer
    « dossier anglophone coté Group plc » et « dossier anglophone coté Limited » comme même marque."""
    s = _norm(name)
    s = re.sub(r"\(.*?\)", " ", s)                      # (LSE: BRBY)
    s = re.sub(r"\b(GROUP|PLC|P\.L\.C\.|LIMITED|LTD|SAS|SASU|SARL|GMBH|INC|LLC|SA|BV)\b",
               " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _clean_analysis_name(value: str) -> str:
    cand = re.sub(r"\s+", " ", str(value or "")).strip(" ·-—,;:")
    cand = _BOILERPLATE_PREFIX_RE.sub("", cand).strip(" ·-—,;:")
    # Stop at narrative continuations accidentally captured after the legal name.
    cand = re.split(r"\b(?:the\s+London-listed|the\s+listed|based\s+in|bas[ée]\s+[àa])\b",
                    cand, maxsplit=1, flags=re.I)[0].strip(" ·-—,;:")
    return cand


def extract_group_analysis_name(brief: str) -> str:
    """Canonical group name extracted from explicit identity, then free prose.

    A short UI field such as ``Company: dossier anglophone coté`` must not hide the richer
    legal group name ``dossier anglophone coté Group plc`` stated later in the same brief.
    """
    explicit = ""
    m_explicit = _EXPLICIT_COMPANY_RE.search(brief or "")
    if m_explicit:
        explicit = _clean_analysis_name(m_explicit.group("name"))
    rich_candidates: list[str] = []
    for rx in _GROUP_NAME_RES:
        for m in rx.finditer(brief or ""):
            cand = _clean_analysis_name(m.group(1))
            if _base_brand(cand):
                rich_candidates.append(cand)
    if rich_candidates:
        # Prefer the most explicit group/legal suffix candidate sharing the
        # brand of the explicit field, otherwise the first rich candidate.
        for cand in rich_candidates:
            if (not explicit or _base_brand(cand) == _base_brand(explicit)) and re.search(r"\b(?:group|plc|p\.l\.c\.)\b", cand, re.I):
                return cand
        return rich_candidates[0]
    return explicit


@dataclass
class EntityScope:
    analysis_entity: str = ""              # sujet stratégique (ex. dossier anglophone coté Group plc)
    legal_entity: str = ""                 # entité légale (ex. dossier anglophone coté Limited)
    registry_entity: str = ""              # entité registre utilisée (CH/GLEIF)
    registry_id: str = ""                  # numéro registre (ex. 00162636)
    registry_source: str = ""              # companies_house / gleif / pappers / sec_edgar
    consolidated_source_entity: str = ""   # source des chiffres consolidés
    financial_scope: str = "unknown"       # consolidated_group | solo | unknown
    is_listed_group: bool = False
    entity_mismatch: bool = False          # analyse ≠ registre (périmètres distincts)
    scope_warning: str = ""                # note d'en-tête lisible

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _warning_text(scope: "EntityScope", lang: str) -> str:
    if not scope.entity_mismatch:
        return ""
    if (lang or "fr").lower() == "en":
        return (
            f"Analysis entity: {scope.analysis_entity} (listed group). "
            f"Registry entity used for identity (CH/GLEIF): {scope.registry_entity}"
            f"{(' — ' + scope.registry_id) if scope.registry_id else ''}. "
            f"Scope: consolidated group figures must come from "
            f"{scope.consolidated_source_entity}, not from the registry legal entity."
        )
    return (
        f"Entité d'analyse : {scope.analysis_entity} (groupe coté). "
        f"Entité registre utilisée pour l'identité (CH/GLEIF) : {scope.registry_entity}"
        f"{(' — ' + scope.registry_id) if scope.registry_id else ''}. "
        f"Périmètre : les chiffres consolidés groupe doivent provenir de "
        f"{scope.consolidated_source_entity}, pas de l'entité légale registre."
    )


def resolve_entity_scope(
    brief: str,
    resolved_name: str = "",
    registry_name: str = "",
    registry_id: str = "",
    registry_source: str = "",
    lang: str = "fr",
) -> EntityScope:
    """
    Construit le périmètre entité à partir des signaux disponibles.

    Règle cardinale : si le brief signale un groupe coté (plc / LSE / listed /
    annual report / consolidated…), l'entité d'ANALYSE ne doit JAMAIS être réduite
    à une filiale Companies House homonyme. Le registre reste tracé séparément.
    """
    s = EntityScope()
    s.registry_entity = registry_name or ""
    s.registry_id = registry_id or ""
    s.registry_source = registry_source or ""

    listed = detect_listed_group(brief)
    s.is_listed_group = listed

    group_name = extract_group_analysis_name(brief)
    registry_is_legal_subsidiary = bool(registry_name and _LEGAL_SUFFIX.search(registry_name))

    if listed:
        # v62.10 — un identifiant registre explicite et résolu est l'autorité du
        # NOM canonique. Le texte libre du brief ne peut jamais remplacer une
        # raison sociale Companies House/GLEIF par une phrase narrative.
        if registry_name and registry_id:
            same_brand = (not group_name or _base_brand(group_name) == _base_brand(registry_name))
            # A registry match ending in Limited/Ltd may be a legal subsidiary
            # of the listed group named in the brief. In that case the group
            # name remains the analysis authority. Conversely, an exact active
            # GROUP PLC resolution is the canonical name and must override the
            # prose wrapper around it.
            if registry_is_legal_subsidiary and group_name:
                s.analysis_entity = group_name
            else:
                s.analysis_entity = registry_name if same_brand else (group_name or registry_name)
        else:
            s.analysis_entity = group_name or (resolved_name or registry_name or "")
        s.analysis_entity = _clean_analysis_name(s.analysis_entity)
        s.legal_entity = registry_name or resolved_name or s.analysis_entity
        s.consolidated_source_entity = (
            s.analysis_entity
            + (" — annual/interim group reports" if (lang or "fr").lower() == "en"
               else " — rapports annuels/intermédiaires groupe")
        )
        s.financial_scope = "consolidated_group"
        # mismatch si l'entité registre est une filiale légale de marque identique
        # mais de dénomination distincte (Group plc ≠ Limited).
        if (registry_is_legal_subsidiary
                and _norm(s.analysis_entity) != _norm(registry_name)
                and _base_brand(s.analysis_entity) == _base_brand(registry_name)):
            s.entity_mismatch = True
    else:
        s.analysis_entity = resolved_name or registry_name or ""
        s.legal_entity = registry_name or resolved_name or s.analysis_entity
        s.consolidated_source_entity = ""
        s.financial_scope = "solo" if registry_name else "unknown"

    s.scope_warning = _warning_text(s, lang)
    return s


def analysis_display_name(scope, fallback: str = "") -> str:
    """Nom à utiliser dans les TITRES et prompts métier.

    Verrou entité : pour un groupe coté ou un mismatch analyse/registre, on renvoie
    l'entité d'ANALYSE — jamais la filiale registre. Le nom registre reste cantonné
    au bloc d'identité. Sinon on garde le fallback (nom résolu/registre).
    """
    if scope is None:
        return fallback
    ae = (getattr(scope, "analysis_entity", "") or "").strip()
    if ae and (getattr(scope, "entity_mismatch", False)
               or getattr(scope, "is_listed_group", False)):
        return ae
    return fallback or ae


def _registry_label(scope) -> str:
    reg = (getattr(scope, "registry_entity", "") or "").strip()
    rid = (getattr(scope, "registry_id", "") or "").strip()
    return f"{reg} — {rid}" if (reg and rid) else reg


def entity_scope_for_agents(scope, lang: str = "fr") -> str:
    """Bloc explicite à injecter dans TOUS les prompts métier : impose l'entité
    d'analyse comme sujet des titres/recommandations, registre = identité seule.
    Renvoie "" si pas de distinction (rien à imposer)."""
    if scope is None:
        return ""
    analysis = (getattr(scope, "analysis_entity", "") or "").strip()
    registry = _registry_label(scope)
    distinct = analysis and registry and (
        getattr(scope, "entity_mismatch", False)
        or getattr(scope, "is_listed_group", False))
    if not distinct:
        return ""
    if (lang or "fr").lower() == "en":
        return (
            "Entity scope (binding):\n"
            f"- Analysis entity: {analysis}\n"
            f"- Registry entity (identity only): {registry}\n"
            "- Use the ANALYSIS entity in ALL business titles and recommendations "
            "(strategy, marketing, finance, commercial, board, supply chain).\n"
            "- Do NOT title business sections with the registry entity unless "
            "explicitly discussing legal identity.")
    return (
        "Périmètre d'entité (impératif) :\n"
        f"- Entité d'analyse : {analysis}\n"
        f"- Entité registre (identité seule) : {registry}\n"
        "- Utiliser l'entité d'ANALYSE dans TOUS les titres et recommandations métier "
        "(stratégie, marketing, finance, commercial, board, supply chain).\n"
        "- Ne PAS titrer les sections métier avec l'entité registre sauf discussion "
        "explicite d'identité légale.")


_REGISTRY_CTX = re.compile(
    r"(registry|registre|company\s*profile|profil\s*société|company\s*number|"
    r"identity|identit[ée]|legal\s*identity|lei\b|siren|company\s*id|"
    r"raison\s*sociale|subsidiar|filiale)", re.I)

_SENT_END = (".", "!", "?", "…", "。")


def _looks_like_title(line: str) -> bool:
    """Heuristique « ligne de titre » : un titre Markdown (#…) OU une ligne courte
    de type en-tête (peu de mots, pas de ponctuation de fin de phrase). Évite de
    toucher la prose (phrases se terminant par un point)."""
    s = line.strip()
    if not s:
        return False
    if s.startswith("#"):
        return True
    if len(s) > 100 or len(s.split()) > 14:
        return False
    return s[-1] not in _SENT_END


def lock_entity_in_titles(text: str, analysis: str, registry: str) -> str:
    """Filet de sécurité : dans les TITRES (Markdown # … ou lignes courtes de type
    en-tête, ex. « CEO Directive Note — dossier anglophone coté Limited … »), remplace le nom
    registre par le nom d'analyse. Épargne la prose et les lignes d'identité."""
    if not text or not analysis or not registry:
        return text
    if _norm(analysis) == _norm(registry):
        return text
    rx = re.compile(re.escape(registry), re.I)
    out_lines = []
    for line in text.split("\n"):
        if _looks_like_title(line) and not _REGISTRY_CTX.search(line):
            line = rx.sub(analysis, line)
        out_lines.append(line)
    return "\n".join(out_lines)


def _is_heading_style(name: str) -> bool:
    n = (name or "")
    return ("Heading" in n) or ("Title" in n) or ("Titre" in n)


def lock_entity_in_docx_headings(doc, analysis: str, registry: str) -> int:
    """Filet de sécurité CR : dans les paragraphes de TITRE (style Heading/Title),
    remplace le nom registre par le nom d'analyse. Épargne les titres d'identité."""
    if not analysis or not registry or _norm(analysis) == _norm(registry):
        return 0
    rx = re.compile(re.escape(registry), re.I); n = 0
    for p in doc.paragraphs:
        if not _is_heading_style(getattr(p.style, "name", "")):
            continue
        if _REGISTRY_CTX.search(p.text):
            continue
        for run in p.runs:
            new = rx.sub(analysis, run.text)
            if new != run.text:
                run.text = new; n += 1
        if p.runs and rx.search(p.text):  # fallback titre coupé entre runs
            fixed = rx.sub(analysis, p.text)
            if fixed != p.text:
                p.runs[0].text = fixed
                for r in p.runs[1:]:
                    r.text = ""
                n += 1
    return n


def lock_entity_in_pptx_titles(prs, analysis: str, registry: str) -> int:
    """Filet de sécurité deck : remplace le nom registre par le nom d'analyse dans
    les titres de slides (placeholders titre + 1er bloc texte). Épargne l'identité."""
    if not analysis or not registry or _norm(analysis) == _norm(registry):
        return 0
    rx = re.compile(re.escape(registry), re.I); n = 0
    for slide in prs.slides:
        for shape in slide.shapes:
            if not getattr(shape, "has_text_frame", False):
                continue
            is_title = False
            try:
                ph = shape.placeholder_format
                is_title = ph is not None and ph.type is not None and "TITLE" in str(ph.type)
            except Exception:
                is_title = False
            for para in shape.text_frame.paragraphs:
                ptxt = "".join(r.text for r in para.runs)
                if not (is_title or ptxt.lstrip().startswith("#")):
                    continue
                if _REGISTRY_CTX.search(ptxt):
                    continue
                for run in para.runs:
                    new = rx.sub(analysis, run.text)
                    if new != run.text:
                        run.text = new; n += 1
                if para.runs and rx.search("".join(r.text for r in para.runs)):
                    cur = "".join(r.text for r in para.runs)
                    fixed = rx.sub(analysis, cur)
                    if fixed != cur:
                        para.runs[0].text = fixed
                        for r in para.runs[1:]:
                            r.text = ""
                        n += 1
    return n


def header_lines(scope: "EntityScope", lang: str = "fr") -> list:
    """Lignes d'en-tête CR explicites (séparation analyse / registre / périmètre)."""
    en = (lang or "fr").lower() == "en"
    out = []
    if not scope.analysis_entity:
        return out
    if en:
        out.append(f"Analysis entity: {scope.analysis_entity}")
        if scope.registry_entity:
            rid = f" — {scope.registry_id}" if scope.registry_id else ""
            out.append(f"Registry entity (identity only): {scope.registry_entity}{rid}")
        if scope.financial_scope == "consolidated_group":
            out.append("Financial scope: consolidated group "
                       "(figures must be sourced from group annual/interim reports)")
    else:
        out.append(f"Entité d'analyse : {scope.analysis_entity}")
        if scope.registry_entity:
            rid = f" — {scope.registry_id}" if scope.registry_id else ""
            out.append(f"Entité registre (identité seule) : {scope.registry_entity}{rid}")
        if scope.financial_scope == "consolidated_group":
            out.append("Périmètre financier : consolidé groupe "
                       "(chiffres à sourcer dans les rapports annuels/intermédiaires groupe)")
    return out


# ── M6-A2.1 — quarantine de résolution registre ──────────────────────────────
def should_quarantine_registry(analysis_name: str, registry_name: str) -> bool:
    """Renvoie True si le candidat registre (Pappers/CH/GLEIF) doit être mis en
    quarantine : il ne partage AUCUN token significatif avec l'entité d'analyse.
    Réutilise la similarité canonique (utils.name_matcher.is_match), la même qui
    pilote déjà l'alerte de mismatch UI↔Pappers. dossier anglophone coté Group plc vs dossier anglophone coté
    LIMITED partage « <marque> » → JAMAIS quarantainé. dossier industriel (composants) vs <AUTRE SOCIÉTÉ> →
    0 token commun → quarantainé. En cas de doute (noms vides, exception), on ne
    quarantine pas (fail-open : ne jamais bloquer une résolution légitime)."""
    a = (analysis_name or "").strip()
    r = (registry_name or "").strip()
    if not a or not r:
        return False
    try:
        from utils.name_matcher import is_match
        return not is_match(a, r, threshold=0.5)
    except Exception:
        return False


def apply_registry_quarantine(analysis_name: str, pap_primary: str,
                              pap_full: str, pap_summary: str, pap_blocks):
    """M6-A2.1.1 — quarantine EN AMONT. Si le candidat registre (pap_primary) doit
    être rejeté (cf. should_quarantine_registry), purge les blocs Pappers BRUTS pour
    qu'ils ne contaminent NI attachments_block, NI la table de faits, NI les prompts
    agents (_pap_ctx). Renvoie un dict avec les valeurs (purgées si rejet)."""
    if pap_primary and should_quarantine_registry(analysis_name, pap_primary):
        return {
            "quarantined": True, "rejected_name": pap_primary,
            "pap_full": "", "pap_summary": "", "pap_primary": "",
            "pap_blocks": {"status": "rejected", "rejected_name": pap_primary},
        }
    return {
        "quarantined": False, "rejected_name": "",
        "pap_full": pap_full, "pap_summary": pap_summary, "pap_primary": pap_primary,
        "pap_blocks": pap_blocks,
    }


# ── M6-A2.1.2 — source FIABLE du nom d'analyse (indépendante du registre) ─────
import re as _re_a212

def extract_analysis_entity_from_brief(brief: str) -> str:
    """Extrait l'entité d'analyse depuis la section IDENTITÉ du brief (champ
    « Société : … » / « Company : … » / « Raison sociale : … » …). Source
    INDÉPENDANTE de toute résolution registre (Pappers/GLEIF) : c'est ce que
    l'utilisateur déclare comme sujet, pas ce qu'un annuaire a résolu."""
    if not brief:
        return ""
    labels = (r"(?:soci[ée]t[ée]|company|raison sociale|"
              r"entit[ée] analys[ée]e?|nom de l['\u2019]entreprise)")
    m = _re_a212.search(rf"(?im)^\s*{labels}\s*[:\uFF1A]\s*(.+)$", brief)
    if not m:
        return ""
    val = m.group(1).strip()
    val = _re_a212.sub(r"\(.*?\)", "", val).strip()      # retire parenthèses
    val = _re_a212.sub(r"\s*[.;,].*$", "", val).strip()  # retire suite après ponctuation
    return val


_BARE_ID_RE = _re_a212.compile(r"^(?:[\d\s.\-]{9,}|FR\s?\d{2}\s?\d{9}|[A-Z0-9]{20}|[A-Z]{2}\d{6}|\d{8})$")


def is_bare_identifier(value: str) -> bool:
    """v62.13.9.4.32 (A) — un SIREN/SIRET, un numéro de TVA, un LEI, un numéro
    Companies House n'est pas un NOM. Run réel ee08f0 (11/09/2026) : la cible
    confirmée portait « <SIREN> » comme nom ; le registre résolvait bien
    « dossier agroalimentaire BISCUITS » mais le comparateur de NOMS l'a rejeté (aucun token
    commun avec le numéro), la trame a titré sur le numéro et annoncé un
    conflit d'entité. Un identifiant se compare à un identifiant, un nom à un nom."""
    v = (value or "").strip()
    return bool(v) and bool(_BARE_ID_RE.fullmatch(v.upper()))


def resolve_analysis_name_for_quarantine(confirmed_target_name: str, brief: str,
                                         pappers_confirmed_entity: str) -> str:
    """Nom à utiliser comme côté « analyse » de la quarantine. Priorité :
    1) cible d'analyse explicite (confirmed_target_entity) ;
    2) section IDENTITÉ du brief (indépendante du registre) ;
    3) entité confirmée UI — UNIQUEMENT si ce n'est pas un identifiant
       (SIREN/SIRET numérique). On n'utilise JAMAIS _pap_primary ici."""
    n = (confirmed_target_name or "").strip()
    if n and not is_bare_identifier(n):          # v62.13.9.4.32 (A) — un identifiant n'est pas un nom
        return n
    n = extract_analysis_entity_from_brief(brief)
    if n:
        return n
    p = (pappers_confirmed_entity or "").strip()
    # exclut un identifiant pur (SIREN 9 / SIRET 14 chiffres, espaces tolérés)
    if p and not is_bare_identifier(p):
        return p
    return ""


def apply_gleif_quarantine(analysis_name: str, gleif_blocks):
    """M6-A2.1.3 — quarantine GLEIF EN AMONT, symétrique à apply_registry_quarantine
    (Pappers). Si le nom GLEIF résolu ne partage aucun token significatif avec
    l'entité d'analyse, purge le bloc GLEIF brut pour qu'il ne contamine NI
    _gleif_ctx / _external_ctx, NI attachments_block, NI la table de faits, NI le
    profil. GLEIF « <GROUPE> » vs analyse « dossier industriel (composants) Hydraulics » → token partagé →
    conservé (cas réel du run dossier industriel (composants)). Fail-open."""
    if not isinstance(gleif_blocks, dict):
        return {"quarantined": False, "rejected_name": "", "gleif_blocks": gleif_blocks}
    name = gleif_blocks.get("primary") or gleif_blocks.get("primary_name") or ""
    if name and should_quarantine_registry(analysis_name, name):
        return {"quarantined": True, "rejected_name": name,
                "gleif_blocks": {"status": "rejected", "rejected_name": name}}
    return {"quarantined": False, "rejected_name": "", "gleif_blocks": gleif_blocks}
