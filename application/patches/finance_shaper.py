"""
patches/finance_shaper.py — v17.1-B2.1.2

SHAPER FINANCE GOUVERNÉ (complément du LEDGER CONSOLIDÉ de B1).

Problème résiduel du run Lhyfe/FDE (B2.1.1) : l'agent finance produit les bons
chiffres CONSOLIDÉS sourcés (CA 9,8 M€, EBITDA -21,9 M€, RN -51 M€, trésorerie
75 M€ — RFA/PR avec pages) DANS SON TABLEAU COMPARATIF NARRATIF, mais ne les
émet pas toujours dans son bloc AGENT_JSON de claims. Résultat : la table de
faits déterministe (→ deck) ne les promeut pas et affiche à la place le RN
SOCIAL Pappers (+1,2 M€) à côté d'un EBITDA consolidé -21,9 M€ — incohérent et
trompeur pour un lecteur board.

DOCTRINE (décision de design B2.1.2 — aucun hardcoding Lhyfe/FDE) :
  1. On extrait les faits du tableau Finance/comparatif NARRATIF de façon
     déterministe (pas de valeurs en dur).
  2. On ne promeut au ledger qu'après contrôle gouverné : métrique canonique,
     montant cohérent (devise), périmètre explicite, source présente ET de
     force suffisante.
  3. Force des sources (générique, pas spécifique Lhyfe) :
       STRONG   : RFA, URD, document d'enregistrement universel, annual report,
                  FY results, communiqué/press release de résultats.
       WEAK     : "Brief CoDIR" — utilisable en narratif, JAMAIS suffisant seul
                  pour une table financière board-safe primaire.
       IDENTITY : Pappers — identité/social standalone, non prioritaire si un
                  fait consolidé de source forte existe.
  4. Supersession = présentation, pas suppression. Le ledger conserve TOUS les
     faits (social ET consolidé). Le deck PRIMAIRE n'affiche que le consolidé
     quand il existe ; le social Pappers tombe en note de périmètre.
  5. Honnêteté : un libellé de traçabilité « N/100 » n'est affiché « board-safe »
     que si (a) le scorer a tourné sans erreur ET (b) les métriques consolidées
     critiques (CA, résultat net) sont présentes. Sinon → libellé gardé.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional, Tuple

# F.6.8 (audit dossier réseau de soins) — garde-fous périmètre.
# Source mono-entité : une liasse 2050 / des comptes sociaux ne sont JAMAIS un
# consolidé groupe. Pappers = social. Société/maison mère = entité unique.
_SINGLE_ENTITY_SRC = re.compile(
    r"liasse\s*(?:fiscale\s*)?2050|formulaire\s*2050|cerfa\s*2050|"
    r"comptes?\s+sociaux|comptes?\s+annuels\s+sociaux|\bpappers\b|"
    r"société\s+m[èe]re|maison\s+m[èe]re|liasse\s+fiscale",
    re.I,
)
# Preuve de consolidation RÉELLE (pas le simple mot « consolidé » d'un agent).
_CONSO_PROOF = re.compile(
    r"comptes?\s+consolid|[ée]tats?\s+financiers?\s+consolid|"
    r"p[ée]rim[èe]tre\s+de\s+consolidation|liasse\s+de\s+consolidation|"
    r"consolidation\s+(?:tagetik|ifrs)|reporting\s+consolid|bilan\s+consolid|"
    r"ifrs.{0,25}groupe",
    re.I,
)
# Indice « tête de groupe » (pour distinguer HOLDING de SOCIAL filiale).
_HOLDING_HINT = re.compile(
    r"holding|société\s+m[èe]re|maison\s+m[èe]re|t[êe]te\s+de\s+groupe",
    re.I,
)

# ─────────────────────────────────────────────────────────────────────────────
# 1. Métriques canoniques (alignées sur consolidated_ledger / valuation_modeler)
# ─────────────────────────────────────────────────────────────────────────────
_CANON: list[tuple[str, str]] = [
    (r"chiffre\s*d['’]affaires", "Chiffre d'affaires"),
    (r"\bca\b", "Chiffre d'affaires"),
    # B.1.3.6 (run dossier anglophone coté EN) — canonical_metric('Revenue') retournait
    # None : TOUT run EN avait « métriques critiques manquantes » par
    # construction (missing/weak/brief_covered comparent des canoniques).
    (r"\brevenue\b|net\s*sales|\bturnover\b", "Chiffre d'affaires"),
    (r"ebitda", "EBITDA"),
    (r"r[ée]sultat\s*net", "Résultat net"),
    (r"perte\s*nette", "Résultat net"),
    (r"\brn\b", "Résultat net"),
    (r"net\s*(?:income|profit|earnings)|profit\s*for\s*the\s*(?:year|period)",
     "Résultat net"),
    (r"tr[ée]sorerie", "Trésorerie"),
    (r"endettement\s*financier\s*brut", "Dette brute"),
    (r"endettement\s*(financier\s*)?net", "Dette nette"),
    (r"dette\s*nette", "Dette nette"),
    (r"dette\s*brute", "Dette brute"),
    (r"dettes?\s*financi[èe]re?s?", "Dette brute"),
    (r"capitaux\s*propres", "Capitaux propres"),
    (r"effectif", "Effectif"),
    (r"capacit[ée]\s*install", "Capacité installée"),
]

# Montant monétaire : exige une devise pour isoler « 9,8 M€ » / « €9,8M » /
# « -€51,0M » et IGNORER années (2025) et pourcentages (+92%).
_AMOUNT_RE = re.compile(
    r"[-−]?\s*(?:[€$£]\s*)?\d[\d\s\u202f.,]*\s*(?:Md|Mrd|bn|M|m|K|k)?\s*[€$£]?",
)
_HAS_CURRENCY = re.compile(r"[€$£]")
_PAGE_RE = re.compile(r"\b(?:p\.?|pp\.?|page)\s*(\d{1,4})\b", re.IGNORECASE)
_SOURCE_FILE_RE = re.compile(r"([A-Za-z0-9._\-]+\.(?:pdf|xlsx?|docx?|csv))", re.IGNORECASE)

# Force des sources — patterns GÉNÉRIQUES (aucun nom d'entreprise).
_STRONG_PATTERNS = (
    "rfa", "universal-registration", "registration-document",
    "document d'enregistrement", "document d’enregistrement", "urd",
    "annual report", "rapport annuel", "fy-2025", "fy results", "fy-results",
    "results", "résultats", "resultats", "press release", "communiqué",
    "communique", "-pr-", "comptes consolidés", "comptes consolides",
)
_WEAK_PATTERNS = ("brief", "ordre du jour", "agent finance", "estimation")
_IDENTITY_PATTERNS = ("pappers",)
# v17.1-B2.3-E — abréviations de sources fortes (limites de mot pour éviter les
# faux positifs : « cp » = communiqué de presse, « rfs » = rapport financier
# semestriel, « rfa » = rapport financier annuel). Le run réel source en « CP
# 03/02/2026 » / « RFS 2024 » → étaient classés NONE → faits non board-safe.
_STRONG_ABBR_RE = re.compile(r"\b(cp|rfs|rfa|urd|ddr)\b", re.IGNORECASE)

# v17.1-B2.3-E — année d'exercice (préférence récente) + marqueurs « non
# board-safe » : un CA « (ESTIM) », « intercompany » ou « (HYPOTHÈSE) » ne doit
# pas être promu comme un consolidé propre et écraser le vrai chiffre consolidé.
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_SOFT_MARKERS = ("estim", "hypoth", "intercompany", "inter-company", "non vérifié",
                 "non verifie", "non confirmé", "non confirme", "à confirmer",
                 "a confirmer", "lacune", "à instruire", "a instruire")


def _parse_year(*texts) -> Optional[int]:
    years = []
    for t in texts:
        if t:
            years += [int(y) for y in _YEAR_RE.findall(str(t))]
    return max(years) if years else None


def _is_soft(*texts) -> bool:
    blob = " ".join(str(t).lower() for t in texts if t)
    return any(m in blob for m in _SOFT_MARKERS)

_SCOPE_RANK = {"CONSOLIDATED": 0, "SEGMENT": 1, "SOCIAL_STANDALONE": 2,
               "MARKET": 3, "ESTIMATE": 4, "UNKNOWN": 5}
_STRENGTH_RANK = {"STRONG": 0, "WEAK": 2, "IDENTITY": 3, "NONE": 4}


# ─────────────────────────────────────────────────────────────────────────────
# 2. Helpers déterministes (testables isolément)
# ─────────────────────────────────────────────────────────────────────────────
def classify_source_strength(text: Optional[str]) -> str:
    """'lhyfe-rfa-...pdf' → STRONG ; 'Brief CoDIR' → WEAK ; 'Pappers' → IDENTITY."""
    if not text:
        return "NONE"
    low = str(text).lower()
    if any(p in low for p in _STRONG_PATTERNS) or _STRONG_ABBR_RE.search(low):
        return "STRONG"
    if any(p in low for p in _IDENTITY_PATTERNS):
        return "IDENTITY"
    if any(p in low for p in _WEAK_PATTERNS):
        return "WEAK"
    # Un nom de fichier .pdf non identifié reste une source faible mais réelle.
    if _SOURCE_FILE_RE.search(low):
        return "WEAK"
    return "NONE"


def canonical_metric(label: Optional[str]) -> Optional[str]:
    if not label:
        return None
    low = label.lower()
    for pat, canon in _CANON:
        if re.search(pat, low):
            return canon
    return None


def detect_scope(text: Optional[str]) -> str:
    """Périmètre depuis un libellé/colonne : 'consolidé groupe' → CONSOLIDATED.
    Priorité au social/standalone et à la négation 'non consolidé' pour ne pas
    se faire piéger par « FDE : social standalone (… non consolidé groupe) ».

    F.6.8 (audit dossier réseau de soins) — GARDE-FOU PÉRIMÈTRE : une source MONO-ENTITÉ (liasse
    fiscale 2050, comptes sociaux, Pappers, société mère) N'EST PAS un consolidé
    groupe, même si l'agent a écrit « consolidé ». Sans PREUVE de consolidation
    réelle (comptes consolidés / périmètre de consolidation / IFRS groupe), un tel
    fait est classé HOLDING (tête de groupe) ou SOCIAL — jamais CONSOLIDATED.
    Ne casse pas Lhyfe : ses chiffres viennent de vrais comptes consolidés."""
    if not text:
        return "UNKNOWN"
    low = text.lower()
    # B.1.3.23 P0-A' (run dossier industriel) — GARDE DE NÉGATION : « ne reflète pas le
    # CA groupe consolidé » / « pas représentatif du groupe » / « périmètre
    # France uniquement » étaient lus comme marqueurs CONSOLIDÉ (le mot y est).
    if re.search(r"ne\s+refl[èe]te\s+pas[^.]{0,80}consolid|"
                 r"pas\s+repr[ée]sentatif[^.]{0,60}(?:groupe|consolid)|"
                 r"france\s+uniquement|p[ée]rim[èe]tre\s+france", low):
        return "SOCIAL_STANDALONE"
    if "social" in low or "standalone" in low or "non consolid" in low or "pappers" in low:
        return "SOCIAL_STANDALONE"
    _single = bool(_SINGLE_ENTITY_SRC.search(text))
    _proof = bool(_CONSO_PROOF.search(text))
    if _single and not _proof:
        return "HOLDING" if _HOLDING_HINT.search(text) else "SOCIAL_STANDALONE"
    if "consolid" in low:
        return "CONSOLIDATED"
    return "UNKNOWN"


def correct_perimeter(scope: str, source_doc: Optional[str],
                      label: Optional[str] = "") -> str:
    """Re-qualifie un périmètre CONSOLIDATED en HOLDING/SOCIAL quand la SOURCE
    trahit une liasse mono-entité (2050, comptes sociaux) sans preuve de
    consolidation. Appliqué après extraction, sur le couple (source, libellé)."""
    if scope != "CONSOLIDATED":
        return scope
    blob = f"{source_doc or ''} {label or ''}"
    if _SINGLE_ENTITY_SRC.search(blob) and not _CONSO_PROOF.search(blob):
        return "HOLDING" if _HOLDING_HINT.search(blob) else "SOCIAL_STANDALONE"
    return scope


def extract_amount(text: Optional[str]) -> Optional[str]:
    """Renvoie le 1er montant MONÉTAIRE (avec devise) normalisé, sinon None.
    Refuse les valeurs sans devise (n/d, 188, 2025) pour ne pas polluer le ledger."""
    if not text:
        return None
    for m in _AMOUNT_RE.finditer(text):
        chunk = m.group(0)
        if _HAS_CURRENCY.search(chunk):
            return re.sub(r"\s+", " ", chunk).strip().replace("− ", "-").replace("−", "-")
    return None


def parse_source_ref(text: Optional[str]) -> Tuple[Optional[str], Optional[int]]:
    """'... (source : lhyfe-rfa-...pdf, p.120) ...' → ('lhyfe-rfa-...pdf', 120)."""
    if not text:
        return (None, None)
    s = str(text)
    page = None
    mp = _PAGE_RE.search(s)
    if mp:
        page = int(mp.group(1))
    mf = _SOURCE_FILE_RE.search(s)
    if mf:
        return (mf.group(1), page)
    # Pas de fichier : on garde une étiquette source lisible (sans la page).
    label = _PAGE_RE.sub("", s).strip(" ()|,;:-—.")
    return (label or None, page)


def parse_markdown_tables(text: str) -> List[List[List[str]]]:
    """Extrait les tableaux markdown (lignes '| a | b |') en listes de cellules.
    Ignore les lignes de séparation '|---|---|'."""
    tables: List[List[List[str]]] = []
    cur: List[List[str]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line.startswith("|") and line.count("|") >= 2:
            if re.fullmatch(r"\|[\s:\-|]+\|?", line):  # séparateur
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            cur.append(cells)
        else:
            if len(cur) >= 2:
                tables.append(cur)
            cur = []
    if len(cur) >= 2:
        tables.append(cur)
    return tables


def _clean_header(cell: str) -> str:
    return re.sub(r"\*\*|\(.*?\)", "", cell or "").strip().lower()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Extraction gouvernée depuis le comparatif narratif
# ─────────────────────────────────────────────────────────────────────────────
class FactCandidate:
    __slots__ = ("metric", "value", "scope", "source_doc", "source_page",
                 "strength", "source_raw", "entity", "year")

    def __init__(self, metric, value, scope, source_doc, source_page,
                 strength, source_raw, entity=None, year=None):
        self.metric = metric
        self.value = value
        self.scope = scope
        self.source_doc = source_doc
        self.source_page = source_page
        self.strength = strength
        self.source_raw = source_raw
        self.entity = entity  # v17.1-B2.2.2 — nom d'entité (lu sur l'en-tête colonne)
        self.year = year      # v17.1-B2.3-E — exercice (préférence année récente)

    def __repr__(self):
        return (f"FactCandidate({self.entity or '?'}:{self.metric}={self.value} "
                f"scope={self.scope} strength={self.strength} "
                f"src={self.source_doc}:{self.source_page})")


def _entity_display(header_cell: str) -> Optional[str]:
    """Nom d'entité lisible depuis un en-tête de colonne ('**Lhyfe**',
    'Lhyfe (consolidé groupe 2025)' → 'Lhyfe'). Lecture d'en-tête, pas de
    résolution d'entité — donc pas de hardcoding."""
    if not header_cell:
        return None
    s = re.sub(r"\*\*", "", header_cell)
    s = re.sub(r"\(.*?\)", "", s).strip()
    return s or None


def extract_target_facts(finance_text: str, target_name: str) -> List[FactCandidate]:
    """Parcourt les tableaux comparatifs du texte Finance et renvoie les faits
    de l'entité CIBLE (ex. 'Lhyfe'), avec périmètre + source + force.

    AUCUNE valeur en dur : tout vient du texte de l'agent."""
    out: List[FactCandidate] = []
    tname = (target_name or "").strip().lower()
    if not tname:
        return out

    for table in parse_markdown_tables(finance_text):
        header = table[0]
        if len(header) < 2:
            continue
        # Colonne cible = celle dont l'en-tête contient le nom de la cible.
        # v17.1-B2.3-C — FIX : ignorer les colonnes méta (« Périmètre Lhyfe »,
        # « Source Lhyfe »…) qui contiennent aussi le nom de la cible, sinon
        # target_col pointait sur la dernière (colonne source, sans montant) →
        # aucun fait extrait. On prend le PREMIER match non-méta (colonne valeur).
        _META_HDR = ("périmètre", "perimetre", "source", "commentaire", "comment", "scope")
        target_col = None
        for i, h in enumerate(header):
            hc = _clean_header(h)
            if any(m in hc for m in _META_HDR):
                continue
            if (tname in hc or hc in tname) and target_col is None:
                target_col = i
        if target_col is None:
            continue
        # v17.1-B2.3-C — Colonnes méta DE LA CIBLE. Les comparatifs B2.3-B ont des
        # colonnes par entité (« Source Lhyfe »/« Source FDE », « Périmètre Lhyfe »/
        # « Périmètre FDE »). On doit prendre celles de la cible, sinon on lisait la
        # source de la CONTREPARTIE (« Source FDE » = Pappers social) → scope/force
        # faux. Priorité : colonne méta contenant le nom cible ; sinon dernière
        # colonne méta générique (table à source unique).
        def _meta_col(kind_keys):
            for i, h in enumerate(header):
                hc = _clean_header(h)
                if any(k in hc for k in kind_keys) and tname in hc:
                    return i
            for i in range(len(header) - 1, 0, -1):
                hc = _clean_header(header[i])
                if any(k in hc for k in kind_keys):
                    return i
            return None
        src_col = _meta_col(("source", "commentaire", "comment"))
        scope_col = _meta_col(("périmètre", "perimetre", "scope"))
        # Scope de la colonne cible (depuis son en-tête : 'Lhyfe (consolidé groupe)').
        header_scope = detect_scope(header[target_col])

        for row in table[1:]:
            if len(row) <= target_col:
                continue
            metric = canonical_metric(row[0])
            if not metric:
                continue
            value = extract_amount(row[target_col])
            if not value:
                continue  # pas de montant monétaire pour la cible → on saute
            src_cell = row[src_col] if (src_col is not None and len(row) > src_col) else ""
            # Segment de la colonne source qui concerne la cible (avant/après '/').
            seg = src_cell
            for part in re.split(r"\s/\s|\s/(?=\s*[A-Z])", src_cell):
                if tname in part.lower():
                    seg = part
                    break
            # Périmètre : priorité à la colonne « Périmètre <cible> » dédiée,
            # segmentée par cible si la colonne agrège plusieurs entités.
            scope = "UNKNOWN"
            peri_seg = ""
            if scope_col is not None and len(row) > scope_col:
                peri_seg = row[scope_col]
                for part in re.split(r"\s/\s|\s/(?=\s*[A-Z])", row[scope_col]):
                    if tname in part.lower():
                        peri_seg = part
                        break
                scope = detect_scope(peri_seg)
            if scope == "UNKNOWN":
                scope = detect_scope(seg)
            if scope == "UNKNOWN":
                scope = header_scope
            doc, page = parse_source_ref(seg)
            strength = classify_source_strength(seg or src_cell)
            year = _parse_year(row[0], seg)
            if _is_soft(row[0], row[target_col], seg, peri_seg):
                scope = "ESTIMATE"
            out.append(FactCandidate(metric, value, scope, doc, page, strength, seg.strip(), entity=target_name, year=year))
    return out


def extract_all_entity_facts(finance_text: str) -> List[FactCandidate]:
    """Variante SANS cible : extrait les faits de TOUTES les colonnes-entités du
    comparatif (col 0 = métrique, dernière col = source/périmètre exclues).

    Permet de se passer de la résolution d'entité : dans un comparatif
    sponsor↔cible, seule la colonne consolidée porte des montants consolidés —
    le périmètre est dérivé de l'en-tête de colonne + du segment source. Aucune
    valeur ni source en dur."""
    out: List[FactCandidate] = []
    _META = ("source", "périmètre", "perimetre", "commentaire", "comment", "scope",
                 # B.1.3.23 P0-A' (run dossier industriel) — « Valeur 2024 » devenait ENTITÉ
                 # (fait « Valeur 2024 — CA consolidé »). Les colonnes de valeur/
                 # période/statut ne sont jamais des entités.
                 "valeur", "value", "montant", "amount", "exercice",
                 "année", "annee", "statut", "status", "période", "period")
    for table in parse_markdown_tables(finance_text):
        header = table[0]
        if len(header) < 3:
            continue
        # v17.1-B2.3-C — TOUTES les colonnes méta sont exclues des entités (avant,
        # seule la dernière l'était → « Périmètre Lhyfe »/« Source Lhyfe » étaient
        # prises pour des entités, et la colonne Lhyfe lisait la source de la
        # CONTREPARTIE → scope SOCIAL → fait consolidé jamais promu).
        meta_cols = [i for i, h in enumerate(header)
                     if any(k in _clean_header(h) for k in _META)]
        entity_cols = [i for i in range(1, len(header)) if i not in meta_cols]
        if not entity_cols:
            continue

        def _meta_for(col, kind_keys):
            """Colonne méta (source/périmètre) DÉDIÉE à l'entité de `col` :
            d'abord celle dont l'en-tête contient le nom de l'entité (« Source
            Lhyfe »), sinon la dernière colonne méta de ce type (table à source
            unique partagée)."""
            ent = _clean_header(header[col])
            for i in meta_cols:
                hc = _clean_header(header[i])
                if any(k in hc for k in kind_keys) and ent and ent[:5] in hc:
                    return i
            generic = [i for i in meta_cols
                       if any(k in _clean_header(header[i]) for k in kind_keys)]
            return generic[-1] if generic else None

        src_of = {col: (_meta_for(col, ("source",))
                        if _meta_for(col, ("source",)) is not None
                        else _meta_for(col, ("commentaire", "comment")))
                  for col in entity_cols}  # B.1.3.23 P0-A' — la vraie Source prime sur le Commentaire
        peri_of = {col: _meta_for(col, ("périmètre", "perimetre", "scope")) for col in entity_cols}

        def _seg_for(col, src_cell):
            ent = _clean_header(header[col])
            if ent:
                for part in re.split(r"\s/\s|\s/(?=\s*[A-Z])", src_cell):
                    if ent[:5] in part.lower():
                        return part
            return src_cell

        # Pass 1 — périmètre AU NIVEAU COLONNE : en-tête, sinon colonne périmètre
        # dédiée, sinon vote des segments source. Permet aux lignes sans
        # « consolidé » explicite d'hériter du périmètre de leur colonne.
        col_scope = {}
        for col in entity_cols:
            sc = detect_scope(header[col])
            if sc == "UNKNOWN":
                votes = []
                pe_i, sc_i = peri_of.get(col), src_of.get(col)
                for row in table[1:]:
                    if pe_i is not None and len(row) > pe_i:
                        votes.append(detect_scope(_seg_for(col, row[pe_i])))
                    elif sc_i is not None and len(row) > sc_i:
                        votes.append(detect_scope(_seg_for(col, row[sc_i])))
                if votes.count("CONSOLIDATED") > votes.count("SOCIAL_STANDALONE"):
                    sc = "CONSOLIDATED"
                elif votes.count("SOCIAL_STANDALONE") > 0:
                    sc = "SOCIAL_STANDALONE"
            col_scope[col] = sc

        # Pass 2 — émission des faits.
        for row in table[1:]:
            metric = canonical_metric(row[0]) if row else None
            if not metric:
                continue
            for col in entity_cols:
                if len(row) <= col:
                    continue
                value = extract_amount(row[col])
                if not value:
                    continue
                sc_i, pe_i = src_of.get(col), peri_of.get(col)
                src_cell = row[sc_i] if (sc_i is not None and len(row) > sc_i) else ""
                seg = _seg_for(col, src_cell)
                # Périmètre : priorité à la colonne « Périmètre <entité> » dédiée
                # (segmentée par entité si la colonne agrège plusieurs entités).
                scope = "UNKNOWN"
                if pe_i is not None and len(row) > pe_i:
                    scope = detect_scope(_seg_for(col, row[pe_i]))
                if scope == "UNKNOWN":
                    scope = detect_scope(seg)
                if scope == "UNKNOWN":
                    scope = col_scope.get(col, "UNKNOWN")
                doc, page = parse_source_ref(seg)
                strength = classify_source_strength(seg or src_cell)
                year = _parse_year(row[0], seg)
                _peri_cell = row[pe_i] if (pe_i is not None and len(row) > pe_i) else ""
                if _is_soft(row[0], row[col], seg, _peri_cell):
                    scope = "ESTIMATE"  # CA (ESTIM)/intercompany/(HYPOTHÈSE)/à confirmer non board-safe
                out.append(FactCandidate(metric, value, scope, doc, page,
                                         strength, seg.strip(),
                                         entity=_entity_display(header[col]), year=year))
    return out


def _value_magnitude(value: str) -> Optional[float]:
    """Ordre de grandeur en € pour contrôle de cohérence/dédup (signe ignoré)."""
    if not value:
        return None
    s = value.lower().replace("\u202f", "").replace(" ", "")
    num = re.search(r"[-−]?\d[\d.,]*", s)
    if not num:
        return None
    raw = num.group(0).replace("−", "-").replace(".", "").replace(",", ".")
    try:
        v = abs(float(raw))
    except ValueError:
        return None
    if "md" in s or "mrd" in s or "bn" in s:
        v *= 1e9
    elif re.search(r"m(?![a-z])", s):
        v *= 1e6
    elif re.search(r"k(?![a-z])", s):
        v *= 1e3
    return v


# ─────────────────────────────────────────────────────────────────────────────
# P0-1 (M.5) — Financial Fact Mapping Guard
# Empêche qu'un montant soit affecté au mauvais indicateur. Cas FDE : l'EBITDA
# de la table probante affichait 30,4 M€ (= le CA) estampillé FAIT/page-citée.
# Sur un dossier covenant Net Debt/EBITDA, c'est rédhibitoire. Garde ciblé et
# SÛR : on ne retire QUE l'EBITDA manifestement mésattribué, jamais le CA, et
# jamais un EBITDA négatif (perte) légitime.
# ─────────────────────────────────────────────────────────────────────────────
_COHERENCE_EQ_TOL = 0.005   # |EBITDA - CA| <= 0,5 % du CA  →  « même valeur »
_COHERENCE_GT_TOL = 1.02    # EBITDA positif > 102 % du CA  →  impossible


def _value_is_negative(value: str) -> bool:
    """Valeur négative (signe moins en tête ou parenthèses comptables), pour ne
    jamais déclasser un EBITDA de perte légitime."""
    if not value:
        return False
    s = str(value).strip().lower().replace("\u202f", "").replace(" ", "")
    if s.startswith("(") or "(-" in s:
        return True
    s = s.lstrip("€$£")
    return s.startswith("-") or s.startswith("−")


def enforce_financial_coherence(
    cands: Iterable[FactCandidate],
) -> Tuple[List[FactCandidate], List[Tuple[FactCandidate, str]]]:
    """P0-1 — déclasse les faits au mapping valeur↔indicateur incohérent.
    Renvoie (kept, dropped) où dropped = [(candidat, raison)].

    Règles (par couple entité×scope, EBITDA uniquement) :
      A. EBITDA dont la magnitude == celle du CA  →  mésattribution (cas FDE) ;
      B. EBITDA POSITIF dont la magnitude dépasse le CA (>102 %)  →  impossible.
    Le CA n'est jamais retiré ; un EBITDA négatif (perte) n'est jamais retiré.
    """
    cand_list = list(cands)
    by_key: dict = {}
    for c in cand_list:
        if getattr(c, "metric", None) in ("Chiffre d'affaires", "EBITDA") and getattr(c, "value", None):
            by_key.setdefault((c.entity, c.scope), {}).setdefault(c.metric, c)
    drops: dict = {}
    for (_ent, _scope), m in by_key.items():
        ca = m.get("Chiffre d'affaires")
        eb = m.get("EBITDA")
        if not ca or not eb:
            continue
        ca_mag = _value_magnitude(ca.value)
        eb_mag = _value_magnitude(eb.value)
        if ca_mag is None or eb_mag is None or ca_mag <= 0:
            continue
        if abs(eb_mag - ca_mag) <= _COHERENCE_EQ_TOL * ca_mag:
            drops[id(eb)] = (eb, f"EBITDA={eb.value} == CA (mésattribution probable)")
        elif (not _value_is_negative(eb.value)) and eb_mag > ca_mag * _COHERENCE_GT_TOL:
            drops[id(eb)] = (eb, f"EBITDA={eb.value} > CA={ca.value} (incohérent)")
    kept = [c for c in cand_list if id(c) not in drops]
    return kept, list(drops.values())


def govern_candidates(cands: Iterable[FactCandidate]) -> List[FactCandidate]:
    """Sélectionne, par métrique canonique, le meilleur candidat selon le rang
    (CONSOLIDATED+STRONG d'abord). Conserve aussi le meilleur SOCIAL pour la
    note de périmètre (renvoyé séparément n'est pas nécessaire : le ledger
    gardera les deux). Ici on renvoie l'ensemble dédupliqué (1 par couple
    métrique×scope), trié, pour promotion."""
    best: dict[tuple[str, str], FactCandidate] = {}
    for c in cands:
        if not c.metric or not c.value:
            continue
        key = (c.entity, c.metric, c.scope)
        cur = best.get(key)
        # v17.1-B2.3-E — meilleure FORCE d'abord, puis ANNÉE la plus récente
        # (sinon « CA 2024 » écrasait « CA 2025 » à force égale).
        cand_rank = (_STRENGTH_RANK.get(c.strength, 9), -(c.year or 0))
        cur_rank = (_STRENGTH_RANK.get(cur.strength, 9), -(cur.year or 0)) if cur else (99, 0)
        if cur is None or cand_rank < cur_rank:
            best[key] = c
    # P0-1 (M.5) — garde de cohérence valeur↔indicateur avant promotion.
    governed, _dropped = enforce_financial_coherence(best.values())
    if _dropped:
        try:
            import logging as _lg
            _log = _lg.getLogger("codir.finance_shaper")
            for _c, _why in _dropped:
                _log.warning("P0-1 cohérence — fait retiré : %s", _why)
        except Exception:
            pass
    return sorted(
        governed,
        key=lambda c: (_SCOPE_RANK.get(c.scope, 9), _STRENGTH_RANK.get(c.strength, 9), c.metric),
    )


def promote_shaped_facts(table: Any, finance_text: str,
                         target_name: Optional[str] = None) -> int:
    """Extrait → gouverne → promeut dans la table de faits. Renvoie le nb promu.

    - target_name fourni : extrait la colonne de cette entité (mode ciblé).
    - target_name None (mode AUTO) : extrait toutes les colonnes-entités et ne
      promeut que les faits CONSOLIDÉS — le social standalone est déjà au ledger
      via le chemin Pappers, le shaper comble seulement le trou consolidé. Aucune
      dépendance à la résolution d'entité.

    Les faits CONSOLIDATED de source STRONG sont marqués deck-eligibles ;
    les WEAK restent en ledger mais pas board-primary."""
    if table is None or not finance_text:
        return 0
    try:
        from utils.financial_facts_table import FinancialFact, FactStatus
    except Exception:
        return 0

    if target_name:
        cands = govern_candidates(extract_target_facts(finance_text, target_name))
        # B.1.3.23 P0-A' — la garde F.6.8 s'applique aussi en mode ciblé
        # (elle n'existait qu'en AUTO : seconde forme du P2 originel).
        for c in cands:
            c.scope = correct_perimeter(
                c.scope, c.source_doc,
                f"{getattr(c, 'metric', '')} {getattr(c, 'entity', '') or ''}")
    else:
        cands = govern_candidates(extract_all_entity_facts(finance_text))
        # F.6.8 (audit dossier réseau de soins) — corrige le périmètre AVANT promotion : une liasse
        # 2050 / un holding libellé « consolidé » par l'agent est rétrogradé HOLDING
        # (société mère social), jamais publié comme consolidé groupe sans preuve.
        for c in cands:
            c.scope = correct_perimeter(
                c.scope, c.source_doc,
                f"{getattr(c, 'metric', '')} {getattr(c, 'entity', '') or ''}")
        # On comble le trou consolidé ET on publie le holding social (mère) — mais
        # avec son vrai périmètre, jamais déguisé en consolidé groupe.
        cands = [c for c in cands if c.scope in ("CONSOLIDATED", "HOLDING")]
    promoted = 0
    for c in cands:
        uses = ["narrative", "comparison"]
        deck_primary = (c.scope == "CONSOLIDATED" and c.strength == "STRONG")
        if c.scope == "CONSOLIDATED":
            uses.append("finance_model")
        if deck_primary:
            uses.append("deck_primary")
        notes = [f"Shaper finance B2.1.2 — extrait du comparatif narratif "
                 f"(périmètre {c.scope}, source {c.strength})"]
        if c.scope == "CONSOLIDATED" and c.strength != "STRONG":
            notes.append("⚠ source non board-safe (faible) — non primaire deck")
        fact = FinancialFact(
            label=(
                (f"{c.entity} — " if c.entity else "")
                + (f"{c.metric} consolidé" if c.scope == "CONSOLIDATED"
                   else f"{c.metric} (holding social, mère)" if c.scope == "HOLDING"
                   else f"{c.metric} ({c.scope.split('_')[0].lower()})")
            ),
            value=c.value,
            source_doc=c.source_doc or ("Agent Finance — comparatif narratif"),
            source_page=c.source_page,
            status=FactStatus.FAIT,
            confidence=0.85 if c.strength == "STRONG" else 0.5,
            scope=c.scope,
            allowed_uses=uses,
            notes=notes,
        )
        try:
            before = len(getattr(table, "facts", []) or [])
            table.add(fact)
            if len(getattr(table, "facts", []) or []) > before:
                promoted += 1
        except Exception:
            continue
    return promoted


# ─────────────────────────────────────────────────────────────────────────────
# 4. Présentation deck : cascade de supersession (sans suppression)
# ─────────────────────────────────────────────────────────────────────────────
def _fact_attr(f, k, default=None):
    return getattr(f, k, default) if not isinstance(f, dict) else f.get(k, default)


def _row_strength(f) -> str:
    """Force de source d'un fait (objet OU row-dict du render).

    v62.12: a page-confirmed ledger fact is authoritative regardless of the
    legacy filename classifier.  This prevents messages such as ``Revenue
    weakly sourced`` immediately after the same Revenue was confirmed on its
    cited page by the Financial Proof Layer.
    """
    if str(_fact_attr(f, "proof_status", "") or "") == "CONFIRMED_ON_PAGE":
        return "STRONG"
    src = (_fact_attr(f, "source", "") or _fact_attr(f, "source_doc", "")
           or _fact_attr(f, "notes", "") or "")
    if isinstance(src, (list, tuple)):
        src = " ".join(str(x) for x in src)
    return classify_source_strength(str(src))


_CANONICAL_ID_TO_LEGACY_LABEL = {
    "REVENUE": "Chiffre d'affaires",
    "NET_INCOME": "Résultat net",
    "ATTRIBUTABLE_NET_INCOME": "Résultat net",
}


def _canonical_fact_metric(f) -> Optional[str]:
    metric_id = str(_fact_attr(f, "metric_canonical_id", "") or "").upper()
    if metric_id in _CANONICAL_ID_TO_LEGACY_LABEL:
        return _CANONICAL_ID_TO_LEGACY_LABEL[metric_id]
    return canonical_metric(_fact_attr(f, "label", "") or "")


def _fact_blockers(f) -> List[str]:
    """Return blockers for object facts and exported row dictionaries."""
    raw = _fact_attr(f, "board_safe_blockers", None)
    if not raw:
        return []
    if isinstance(raw, str):
        return [x.strip() for x in raw.split(",") if x.strip()]
    try:
        return [str(x).strip() for x in raw if str(x).strip()]
    except Exception:
        one = str(raw).strip()
        return [one] if one else []


def _set_fact_blockers(f, blockers: Iterable[str]) -> None:
    vals: List[str] = []
    for blocker in blockers or []:
        b = str(blocker).strip()
        if b and b not in vals:
            vals.append(b)
    if isinstance(f, dict):
        # FinancialFact.to_row_dict() serialises blockers as CSV text.
        f["board_safe_blockers"] = ",".join(vals)
    else:
        try:
            f.board_safe_blockers = vals
        except Exception:
            pass


def pairing_suspect_status(lang: str = "fr") -> str:
    """Localized status for raw-ledger rendering of pairing suspects."""
    if str(lang or "fr").lower().startswith("en"):
        return "⛔ SUSPECT METRIC/VALUE PAIRING — non-certifying"
    return "⛔ APPARIEMENT MÉTRIQUE/MONTANT SUSPECT — non certifiant"


def _fact_entity_key(f) -> str:
    explicit = str(_fact_attr(f, "perimeter_entity", "") or "").strip().lower()
    if explicit:
        return explicit
    label = str(_fact_attr(f, "label", "") or "")
    parts = re.split(r"\s[—\-]\s", label, maxsplit=1)
    return parts[0].strip().lower() if len(parts) > 1 else ""


def _fact_canonical_key(f) -> str:
    """Return the B.1 identity key for object and row paths.

    Older finance-shaper code used French display labels (``Chiffre
    d'affaires``), while B.1 facts carry structured identifiers such as
    ``REVENUE``.  Mixing both namespaces splits the same metric into two
    groups and lets SOCIAL rows escape the consolidated demotion.
    """
    explicit = str(_fact_attr(f, "metric_canonical_id", "") or "").strip().upper()
    if explicit and explicit != "OTHER":
        return explicit
    try:
        from patches.fact_identity import canonical_metric_id
        cid = str(canonical_metric_id(_fact_attr(f, "label", "") or "") or "").strip().upper()
        if cid and cid != "OTHER":
            return cid
    except Exception:
        pass
    legacy = canonical_metric(_fact_attr(f, "label", "") or "")
    if legacy:
        try:
            from patches.fact_identity import canonical_metric_id
            cid = str(canonical_metric_id(legacy) or "").strip().upper()
            if cid and cid != "OTHER":
                return cid
        except Exception:
            return str(legacy).strip().upper()
    return ""


def _normalize_pairing_scope(scope: Any) -> str:
    """Canonicalise scope aliases used by object and row paths."""
    import unicodedata
    raw = unicodedata.normalize("NFKD", str(scope or "UNKNOWN"))
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    key = re.sub(r"[^A-Z0-9]+", "_", raw.upper()).strip("_")
    aliases = {
        "": "UNKNOWN", "UNKNOWN": "UNKNOWN", "INDETERMINE": "UNKNOWN",
        "CONSOLIDATED": "CONSOLIDATED", "CONSOLIDATED_GROUP": "CONSOLIDATED",
        "GROUP_CONSOLIDATED": "CONSOLIDATED", "CONSOLIDE": "CONSOLIDATED",
        "GROUPE_CONSOLIDE": "CONSOLIDATED",
        "SOCIAL": "SOCIAL_STANDALONE", "STANDALONE": "SOCIAL_STANDALONE",
        "SOCIAL_STANDALONE": "SOCIAL_STANDALONE",
        "HOLDING": "HOLDING", "SEGMENT": "SEGMENT", "MARKET": "MARKET",
        "ESTIMATE": "ESTIMATE", "ESTIMATION": "ESTIMATE",
    }
    return aliases.get(key, key or "UNKNOWN")


def _normalize_pairing_period(period: Any) -> str:
    """Normalize annual/date aliases while preserving fiscal granularity."""
    raw = str(period or "").strip().upper().replace("’", "'")
    compact = re.sub(r"\s+", "", raw)
    if not compact:
        return ""
    # Annual facts may carry the actual fiscal closing date instead of an
    # FY alias (dossier anglophone coté: 2025-03-29, many French entities: 2024-12-31).
    # For the pairing guard, a full date and FY<year> are deliberately made
    # comparable.  This is fail-closed: a quarterly date may be over-demoted,
    # but a conflicting annual amount must never bypass the guard merely
    # because one producer emitted a closing date and another emitted FY.
    for rx in (r"(20\d{2})[-/]\d{2}[-/]\d{2}",
               r"\d{2}[-/]\d{2}[-/](20\d{2})"):
        m = re.fullmatch(rx, compact)
        if m:
            return m.group(1)
    for rx in (
        r"(?:FY)?'?((?:20)?\d{2})(H[12]|Q[1-4])([EFP]?)",
        r"(H[12]|Q[1-4])(?:FY)?'?((?:20)?\d{2})([EFP]?)",
    ):
        m = re.fullmatch(rx, compact)
        if m:
            if m.group(1).startswith(("H", "Q")):
                part, year, suffix = m.group(1), m.group(2), m.group(3)
            else:
                year, part, suffix = m.group(1), m.group(2), m.group(3)
            year = ("20" + year) if len(year) == 2 else year
            return f"{part}FY{year}{suffix}"
    m = re.fullmatch(r"(LTM|TTM|NTM|YTD)(?:FY)?'?((?:20)?\d{2})([EFP]?)", compact)
    if m:
        year = m.group(2); year = ("20" + year) if len(year) == 2 else year
        return f"{m.group(1)}FY{year}{m.group(3)}"
    m = re.fullmatch(r"(?:FY)?'?((?:20)?\d{2})[/\-]'?((?:20)?\d{2})([EFP]?)", compact)
    if m:
        y1, y2 = m.group(1), m.group(2)
        y1 = ("20" + y1) if len(y1) == 2 else y1
        y2 = ("20" + y2) if len(y2) == 2 else y2
        return f"FY{y1}/{y2}{m.group(3)}"
    m = re.fullmatch(r"(?:FY|Y)?'?((?:20)?\d{2})([AEFP]?)", compact)
    if m:
        year = m.group(1); year = ("20" + year) if len(year) == 2 else year
        suffix = "" if m.group(2) == "A" else m.group(2)
        return f"{year}{suffix}"
    return compact


def _fact_amount_key(f):
    """Return a signed, scale-normalised amount fingerprint and unit.

    A fingerprint is either a scalar ``Decimal`` or an ordered tuple of
    endpoints for a displayed range.  The parser receives ``label + value`` so
    real ledger rows such as ``-18.4 M`` / ``15-20 M`` (currency omitted but
    scale explicit) remain in the guard instead of silently falling back to
    arrival-order deduplication.
    """
    value = str(_fact_attr(f, "value", "") or "")
    label = str(_fact_attr(f, "label", "") or "")
    explicit = str(_fact_attr(f, "metric_canonical_id", "") or "")
    try:
        from decimal import Decimal
        from patches.executive_evidence_guard import (
            extract_amounts as _ega_extract_amounts,
            _comparison_amount_key as _ega_comparison_amount_key,
            _metric_families as _ega_metric_families,
            _semantic_polarity as _ega_semantic_polarity,
        )
        # The EGA intentionally accepts scale-only forms only when a nearby
        # financial metric exists.  Supplying the label makes that context
        # available without changing the displayed value.  A spaced dash
        # between two fully written amounts is a range separator, not a minus
        # sign (``15 M€ - 20 M€``).
        scan_value = re.sub(
            r"(?<=[0-9A-Za-z€£$])\s*[–—-]\s*"
            r"(?=(?:[€£$]|[A-Z]{3}\s*)?[+\-−]?\d)",
            " to ", value)
        scan_value = re.sub(
            r"(?<=[0-9mMkK])\s*(to|through|à|au)\s*(?=[+\-−]?\d)",
            r" \1 ", scan_value, flags=re.I)
        refs = _ega_extract_amounts(f"{label} {scan_value}".strip())
        if not refs:
            return None, ""
        metrics = _ega_metric_families(label, explicit)
        canon = _fact_canonical_key(f)
        monetary_metrics = {
            "REVENUE", "EBITDA", "EBIT", "NET_INCOME", "CASH",
            "GROSS_DEBT", "NET_DEBT", "FINANCIAL_DEBT", "EQUITY",
            "FREE_CASH_FLOW", "OPERATING_INCOME", "CAPEX", "OPEX",
            "MARKETING_SPEND", "SAVINGS", "WORKING_CAPITAL", "STOCKS",
            "PENSION_PROVISION",
        }
        if canon in monetary_metrics:
            selected = [r for r in refs if ("_" in str(r[1]) and
                        str(r[1]) not in {"PCT", "BPS", "HEADCOUNT", "RATIO", "DAYS"})]
            if selected:
                refs = selected
        elif canon == "HEADCOUNT":
            selected = [r for r in refs if r[1] == "HEADCOUNT"]
            if selected:
                refs = selected
        elif "MARGIN" in canon or "GROWTH" in canon:
            selected = [r for r in refs if r[1] in {"PCT", "BPS"}]
            if selected:
                refs = selected
        elif "RATIO" in canon or canon.endswith("_MULTIPLE"):
            selected = [r for r in refs if r[1] == "RATIO"]
            if selected:
                refs = selected
        values = []
        units = []
        for raw_amount, raw_unit in refs:
            polarity = _ega_semantic_polarity(
                f"{label} {value}", metrics, raw_amount, raw_unit)
            if raw_unit in {"PCT", "BPS", "HEADCOUNT", "RATIO", "DAYS"}:
                amount = Decimal(str(raw_amount))
                if polarity in ("NEG", "DOWN"):
                    amount = -abs(amount)
                elif polarity in ("POS", "UP"):
                    amount = abs(amount)
                unit = str(raw_unit)
            else:
                amount_raw, unit = _ega_comparison_amount_key(
                    raw_amount, raw_unit, polarity)
                amount = Decimal(str(amount_raw))
            values.append(amount)
            units.append(str(unit))
        # A range often writes the currency only once (``GBP 15m-20m`` or
        # ``15m to 20m EUR``).  Propagate the single explicit currency across
        # UNSPEC endpoints; genuinely mixed explicit currencies remain
        # incomparable and are not guessed.
        if len(set(units)) != 1 and len(values) > 1:
            explicit_money = {u for u in units
                              if re.fullmatch(r"[A-Z]{3}_MBASE", u)}
            if len(explicit_money) == 1 and all(
                    u in explicit_money or u == "UNSPEC_MBASE" for u in units):
                fill = next(iter(explicit_money))
                units = [fill if u == "UNSPEC_MBASE" else u for u in units]
        # A range must use one economic unit.  Genuinely mixed-unit cells are
        # too ambiguous to certify and therefore remain unparsed.
        if len(set(units)) != 1:
            return None, ""
        if len(values) == 1:
            return values[0], units[0]
        # Preserve all endpoints; two different ranges are never treated as
        # harmless scalar rounding.  Sorting neutralises endpoint order only.
        return tuple(sorted(values)), units[0]
    except Exception:
        return None, ""


def _fact_status_rank(f) -> int:
    status = str(_fact_attr(f, "status", "") or "").strip().upper()
    if status in ("FAIT", "FACT") or status.startswith(("FAIT", "FACT")):
        return 0
    if any(x in status for x in ("A_VERIFIER", "À VÉRIFIER", "TO VERIFY", "ESTIM", "HYPOTH")):
        return 2
    return 1


def _fact_evidence_rank(f, index: int) -> tuple:
    """Lower is stronger; numeric magnitude is never a truth criterion."""
    # Pappers/registry accounts are stronger than free narrative for this
    # conflict arbitration, even though they remain perimeter-limited.
    strength_order = {"STRONG": 0, "IDENTITY": 1, "WEAK": 2, "NONE": 3}
    strength = strength_order.get(_row_strength(f), 9)
    status = _fact_status_rank(f)
    perimeter_match = str(_fact_attr(f, "perimeter_match", "") or "").upper()
    perimeter = 0 if perimeter_match in ("", "FULL", "NA") else 2
    blockers = len(_fact_blockers(f))
    page = _fact_attr(f, "source_page", None)
    if page in (None, "", "—"):
        page = _fact_attr(f, "page", None)
    page_rank = 0 if page not in (None, "", "—") else 1
    try:
        conf = _fact_attr(f, "confidence", None)
        if isinstance(conf, str) and conf.endswith("%"):
            conf = float(conf[:-1]) / 100.0
        conf_rank = -float(conf) if conf is not None and conf != "—" else 0.0
    except Exception:
        conf_rank = 0.0
    return (strength, status, perimeter, blockers, page_rank, conf_rank, index)


def _facts_have_distinct_periods(a, b) -> bool:
    pa = str(_fact_attr(a, "period", "") or "").strip().upper()
    pb = str(_fact_attr(b, "period", "") or "").strip().upper()
    return bool(pa and pb and pa != pb)


def flag_divergent_duplicates(facts):
    """Fail closed on material metric/value pairing conflicts.

    The guard accepts FinancialFact objects and exported row dictionaries.  It
    compares signed, scale-normalised values inside the same metric/entity/
    scope/currency family.  Explicitly distinct periods remain independent.

    Arbitration is based on proof quality, never magnitude or arrival order:
      * a unique, strictly stronger proof may survive;
      * agreeing best proofs survive and only divergent weaker alternatives are
        marked;
      * divergent best proofs are all marked ``pairing_suspect``.

    A 10% relative band is retained solely for harmless display rounding (the
    historical 8.5 vs 8.0 test); zero/non-zero and opposite signs are always
    material conflicts.
    """
    from decimal import Decimal
    import re as _re42

    facts = list(facts or [])
    groups = {}
    for index, fact in enumerate(facts):
        canon = _fact_canonical_key(fact)
        if not canon or canon == "OTHER":
            continue
        amount, unit_key = _fact_amount_key(fact)
        if amount is None:  # zero is a valid amount and MUST remain comparable
            continue
        # Currency/unit compatibility is evaluated pairwise below.  Keeping
        # the unit out of the group key prevents an unspecified but otherwise
        # identical ``18.4 M`` row from bypassing an explicit ``18.4 M€`` row.
        key = (
            _fact_entity_key(fact),
            canon,
            _normalize_pairing_scope(_fact_attr(fact, "scope", "UNKNOWN")),
        )
        groups.setdefault(key, []).append((index, fact, amount, unit_key))

    def _norm_period(f):
        return _normalize_pairing_period(_fact_attr(f, "period", ""))

    def _periods_compatible(a, b):
        pa, pb = _norm_period(a), _norm_period(b)
        return not (pa and pb and pa != pb)

    def _unit_family(unit: str):
        u = str(unit or "")
        m = re.fullmatch(r"([A-Z]{3}|UNSPEC)_MBASE", u)
        if m:
            return ("MONEY", m.group(1))
        return (u, u)

    def _units_compatible(ua: str, ub: str) -> bool:
        if ua == ub:
            return True
        fa, fb = _unit_family(ua), _unit_family(ub)
        if fa[0] == fb[0] == "MONEY":
            # Explicitly different currencies never cross-compare.  An
            # unspecified currency is a wildcard but a source of uncertainty,
            # so it is compared fail-closed with the explicit row.
            return fa[1] == "UNSPEC" or fb[1] == "UNSPEC"
        return False

    def _scalar_materially_different(a: Decimal, b: Decimal, unit: str) -> bool:
        if a == b:
            return False
        if (a < 0) != (b < 0) or (a == 0) != (b == 0):
            return True
        aa, bb = abs(a), abs(b)
        high = max(aa, bb)
        diff = abs(a - b)
        rel = (diff / high) if high else Decimal("0")
        # Unit-aware display tolerance.  The old universal 0.5-unit floor
        # certified 1.0% vs 1.5% and 1.0x vs 1.5x.  Monetary facts retain the
        # historic 8.0/8.5 allowance only at non-trivial magnitudes.
        if str(unit).endswith("_MBASE"):
            return not (rel <= Decimal("0.01") or
                        (high >= Decimal("5") and diff <= Decimal("0.5")))
        if unit in {"PCT", "RATIO"}:
            return not (rel <= Decimal("0.01") or diff <= Decimal("0.1"))
        if unit == "BPS":
            return not (rel <= Decimal("0.01") or diff <= Decimal("1"))
        if unit == "HEADCOUNT":
            return not (rel <= Decimal("0.01") or
                        (high >= Decimal("100") and diff <= Decimal("1")))
        if unit == "DAYS":
            return not (rel <= Decimal("0.01") or
                        (high >= Decimal("30") and diff <= Decimal("1")))
        return rel > Decimal("0.01")

    def _materially_different(a, b, ua: str, ub: str) -> bool:
        if not _units_compatible(ua, ub):
            return False  # separate explicit currencies/physical units
        # Unspecified vs explicit currency/scale is itself a proof ambiguity.
        if ua != ub:
            return True
        a_complex = isinstance(a, tuple)
        b_complex = isinstance(b, tuple)
        if a_complex or b_complex:
            # A range/complex display is comparable only to the exact same
            # endpoint set.  A point cannot silently replace a range, nor can a
            # different range win by arrival order.
            return not (a_complex and b_complex and a == b)
        return _scalar_materially_different(a, b, ua)


    _hard_blockers = {
        "pairing_suspect", "unit_uncertain", "unresolved_conflict",
        "period_heterogeneous", "transformation_undocumented",
        "perimeter_mismatch", "social_aggregation_raw",
    }

    def _proof_profile(f):
        """Return ranking inputs plus whether a claim may certify a conflict.

        A hard-blocked registry claim must not be replaced by an arbitrary
        opaque/no-page narrative merely because the latter has no blocker.  In
        a conflicting component, only a clean FACT from a recognised strong or
        registry source, or a page-located FACT from an actual attachment, may
        act as the surviving proof.  If no such claim exists, the component
        fails closed and every conflicting row is marked suspect.
        """
        blockers = {str(x).strip().lower() for x in _fact_blockers(f)}
        hard = 1 if blockers & _hard_blockers else 0
        pm = str(_fact_attr(f, "perimeter_match", "") or "").upper()
        pm_rank = {"FULL": 0, "": 1, "NA": 1, "COVERAGE": 2,
                   "MISMATCH": 3}.get(pm, 2)
        strength_name = _row_strength(f)
        status = _fact_status_rank(f)
        page = _fact_attr(f, "source_page", None)
        if page in (None, "", "—"):
            page = _fact_attr(f, "page", None)
        page_rank = 0 if page not in (None, "", "—") else 1
        source_blob = str(_fact_attr(f, "source_doc", "") or
                          _fact_attr(f, "source", "") or "")
        is_attachment = bool(_SOURCE_FILE_RE.search(source_blob))
        # Opaque client filenames (e.g. BU50F3~1.PDF) are common in the real
        # corpus.  A page-located FACT from an actual attachment outranks a
        # registry identity row even when the filename lacks "annual report".
        if (page_rank == 0 and status == 0 and is_attachment and
                strength_name in {"WEAK", "NONE"}):
            strength_name = "STRONG"
        strength = {"STRONG": 0, "IDENTITY": 1, "WEAK": 2,
                    "NONE": 3}.get(strength_name, 9)
        try:
            conf = _fact_attr(f, "confidence", None)
            if isinstance(conf, str) and conf.endswith("%"):
                conf = float(conf[:-1]) / 100.0
            conf_rank = -float(conf) if conf not in (None, "", "—") else 0.0
        except Exception:
            conf_rank = 0.0
        eligible = (
            hard == 0
            and pm_rank <= 1
            and (
                # Historical rows may carry an empty/neutral status while the
                # source itself is structured and recognised.  Explicit
                # TO_VERIFY / estimate statuses (rank 2) never certify.
                (strength_name in {"STRONG", "IDENTITY"} and status <= 1)
                # An otherwise opaque attachment needs both a page locator and
                # an explicit FACT status before it may outrank a registry row.
                or (is_attachment and page_rank == 0 and status == 0)
            )
        )
        return (hard, pm_rank, strength, status, page_rank, conf_rank), eligible

    def _proof_rank(f):
        return _proof_profile(f)[0]

    def _mark(fact):
        blockers = _fact_blockers(fact)
        if "pairing_suspect" not in blockers:
            blockers.append("pairing_suspect")
            _set_fact_blockers(fact, blockers)
        # Do NOT replace FinancialFact.status with a string: to_row_dict()
        # expects the FactStatus enum.  Renderers localise the blocker.

    for entries in groups.values():
        if len(entries) < 2:
            continue

        # Build connected components of materially conflicting claims.  Periods
        # that are explicitly distinct do not create an edge.
        adjacency = {i: set() for i in range(len(entries))}
        for i in range(len(entries)):
            _idx_a, fact_a, amount_a, unit_a = entries[i]
            for j in range(i + 1, len(entries)):
                _idx_b, fact_b, amount_b, unit_b = entries[j]
                if not _periods_compatible(fact_a, fact_b):
                    continue
                if _materially_different(amount_a, amount_b, unit_a, unit_b):
                    adjacency[i].add(j)
                    adjacency[j].add(i)

        seen = set()
        for seed, neighbours in adjacency.items():
            if seed in seen or not neighbours:
                continue
            stack = [seed]
            component = []
            while stack:
                cur = stack.pop()
                if cur in seen:
                    continue
                seen.add(cur)
                component.append(cur)
                stack.extend(adjacency[cur] - seen)

            eligible = [i for i in component
                        if _proof_profile(entries[i][1])[1]]
            if not eligible:
                # A conflict with no certifying-quality evidence cannot be
                # resolved by arrival order or by a merely unblocked weak row.
                for i in component:
                    _mark(entries[i][1])
                continue

            best_rank = min(_proof_rank(entries[i][1]) for i in eligible)
            best = [i for i in eligible
                    if _proof_rank(entries[i][1]) == best_rank]

            # If the strongest eligible proofs disagree, nobody is allowed to
            # certify.
            best_conflict = any(
                _materially_different(entries[a][2], entries[b][2],
                                      entries[a][3], entries[b][3])
                for pos, a in enumerate(best) for b in best[pos + 1:])
            if best_conflict:
                for i in component:
                    _mark(entries[i][1])
                continue

            # The strongest proofs agree: retain that consensus and mark only
            # materially different alternatives.
            reference = entries[best[0]][2]
            reference_unit = entries[best[0]][3]
            for i in component:
                if _materially_different(entries[i][2], reference,
                                         entries[i][3], reference_unit):
                    _mark(entries[i][1])
    return facts

def select_deck_primary(facts: Iterable[Any], *,
                        demote_brief: bool = True) -> Tuple[List[Any], List[Any]]:
    """Partitionne les faits en (primaires_deck, relégués_note_d'intégrité).

    B.1.3.39 : les doublons divergents (appariement croisé à l'ingestion)
    sont flaggés `pairing_suspect` avant toute cascade.

    Cascade gouvernée (B2.2.1) — au-delà du seul périmètre :
      1. Dédoublonnage par (métrique canonique, périmètre) : on garde le fait de
         source la plus forte ; les doublons plus faibles sont relégués. Évite
         deux lignes EBITDA (« EBITDA consolidé 2025 / Brief » du ledger B1 +
         « EBITDA consolidé / PR p.10 » du shaper).
      2. Un fait CONSOLIDATED de source FAIBLE (Brief CoDIR) n'est PAS board-primary
         (doctrine : Brief CoDIR n'alimente pas la table primaire) → relégué.
      3. Un fait SOCIAL standalone dont la métrique existe en CONSOLIDATED est
         relégué. Rien n'est supprimé : tout reste au ledger."""
    # B.1.3.56 correctif P0-F56-02 — DÉFENSE EN PROFONDEUR : un fait gouverné
    # diagnostics-only (ex. valeur registre sans unité) ne peut être ni
    # primaire ni relégué visible, quelle que soit la forme (fact ou row).
    try:
        from utils.financial_facts_table import is_visible_fact as _ivf56
        facts = [f for f in facts if _ivf56(f)]
    except Exception:
        pass
    facts = flag_divergent_duplicates(list(facts))
    pairing_suspects = [f for f in facts if "pairing_suspect" in _fact_blockers(f)]
    selection_facts = [f for f in facts if "pairing_suspect" not in _fact_blockers(f)]

    def _canon_of(f):
        return _fact_canonical_key(f) or None

    def _entity_of(f):
        """Préfixe entité d'un label « Lhyfe — Résultat net consolidé » → 'lhyfe'.
        Évite de fusionner deux sociétés ayant chacune un consolidé."""
        lbl = str(_fact_attr(f, "label", "") or "")
        m = re.split(r"\s[—\-]\s", lbl, maxsplit=1)
        return m[0].strip().lower() if len(m) > 1 else ""

    # 1. Dédoublonnage par (entité, métrique, périmètre) sur la force de source.
    best: dict = {}
    keep_identity: List[Any] = []
    losers: List[Any] = []
    for f in selection_facts:
        canon = _canon_of(f)
        if not canon:  # identité (LEI, signal…) — toujours primaire, pas de dédup
            keep_identity.append(f)
            continue
        # B.1.3.10 (run 5 : Revenue H1 FY26 GBP 1.03bn relégué à tort) — la
        # clé ignorait la PÉRIODE : FY25 et H1 FY26 collisionnaient et le
        # second partait en « doublon ». Deux périodes distinctes = deux
        # lignes légitimes de la table de preuve.
        _amount_key, _unit_key = _fact_amount_key(f)
        key = (_entity_of(f), canon,
               _normalize_pairing_scope(_fact_attr(f, "scope", "UNKNOWN")),
               _normalize_pairing_period(_fact_attr(f, "period", "")),
               _unit_key or "")
        cur = best.get(key)
        if cur is None:
            best[key] = f
        elif _STRENGTH_RANK.get(_row_strength(f), 9) < _STRENGTH_RANK.get(_row_strength(cur), 9):
            losers.append(cur)
            best[key] = f
        else:
            losers.append(f)

    # Métriques disposant d'un consolidé (toutes entités confondues) : sert à
    # reléguer un social standalone dont l'équivalent consolidé existe.
    # B.1.3.25 P1-B (run dossier industriel 3.24) — un CONSOLIDÉ ⛔ HORS PÉRIMÈTRE
    # (perimeter_match == MISMATCH) ne compte pas comme « présence consolidée » :
    # il reléguait le CA social Pappers FULL au profit d'un fait lui-même exclu
    # → plus aucun CA visible en table primaire, alors que le narratif entier
    # reposait dessus. L'in-perimeter gagne.
    consolidated_metrics = {
        c for (_e, c, s, _p, _u), _f in best.items()
        if s == "CONSOLIDATED"
        and str(_fact_attr(_f, "perimeter_match", "") or "") != "MISMATCH"}

    primary: List[Any] = list(keep_identity)
    demoted: List[Any] = list(pairing_suspects) + list(losers)
    _r1_loser_ids = {id(x) for x in losers}  # B.1.3.12 — seuls les perdants
    # du DÉDOUBLONNAGE (règle 1) peuvent être réintégrés ; les relégations
    # doctrinales (règles 2/3) restent définitives.
    for (_entity, canon, scope, _period, _unit), f in best.items():
        if (scope in ("SOCIAL", "SOCIAL_STANDALONE")
                and canon in consolidated_metrics):
            demoted.append(f)                      # règle 3
        elif (demote_brief and scope == "CONSOLIDATED"
              and _row_strength(f) in ("WEAK", "IDENTITY")):
            # règle 2 (DECK board-primary uniquement) : consolidé faible
            # (Brief/Pappers) relégué. B.1.3.5 : la TABLE CR appelle avec
            # demote_brief=False — les faits du BRIEF restent VISIBLES en
            # Zone A, suffixés « brief non certifié » (contrat B.1.3),
            # doctrine B2.2.1 conservée côté deck.
            demoted.append(f)
        else:
            primary.append(f)

    primary.sort(key=lambda f: _SCOPE_RANK.get(_fact_attr(f, "scope", "UNKNOWN"), 9))
    # B.1.3.12 (run 6 : in_table=3 persistant) — un fait BRIEF perdant du
    # dédoublonnage ne doit pas DISPARAÎTRE si son vainqueur est lui-même
    # relégué ou absent de la table primaire : le (canon, période) doit
    # garder un représentant visible. Le brief remonte alors, marqué comme
    # toujours (brief, not certified).
    try:
        _prim_keys = {(_canon_of(f),
                       _normalize_pairing_period(_fact_attr(f, "period", "")))
                      for f in primary if _canon_of(f)}
        for _lf in list(demoted):
            if id(_lf) not in _r1_loser_ids:
                continue
            if str(_fact_attr(_lf, "source_doc", "") or "").strip().lower() != "brief":
                continue
            _k = (_canon_of(_lf),
                  _normalize_pairing_period(_fact_attr(_lf, "period", "")))
            if _k[0] and _k not in _prim_keys:
                demoted.remove(_lf)
                primary.append(_lf)
                _prim_keys.add(_k)
    except Exception:
        pass
    return primary, demoted


def integrity_note(demoted: Iterable[Any], lang: str = "fr") -> str:
    """Note d'intégrité pour les faits relégués hors table primaire board
    (transparence, jamais de suppression) : périmètre social standalone et/ou
    source non board-safe. Vide si rien à signaler."""
    demoted = list(demoted)
    if not demoted:
        return ""
    # B.1.3.16 (dossier industriel (composants) run 1 : « Effectif — relégué » ambigu, le lecteur
    # croit l'Effectif BRIEF visé) — chaque fait relégué est QUALIFIÉ
    # (source, périmètre, valeur) : « Effectif (Pappers, SOCIAL standalone,
    # 0 salariés) ».
    def _qual16(f):
        _lbl = (canonical_metric(_fact_attr(f, "label", "") or "")
                or _fact_attr(f, "label", "") or "")
        _srcd = str(_fact_attr(f, "source_doc", "") or "").strip()
        _scp = str(_fact_attr(f, "scope", "") or "").strip()
        _val = str(_fact_attr(f, "value", "") or "").strip()
        _det = ", ".join(x for x in (_srcd, _scp, _val) if x)
        return f"{_lbl} ({_det})" if _det else _lbl
    # B.1.3.39 R2 — les relégués `pairing_suspect` (appariement croisé à
    # l'ingestion) ne sont plus listés comme valeur de leur métrique.
    _suspects39 = [f for f in demoted if "pairing_suspect" in _fact_blockers(f)]
    demoted = [f for f in demoted if f not in _suspects39]
    if not demoted and _suspects39:
        if str(lang or "fr").lower().startswith("en"):
            return (f"⚠ {len(_suspects39)} claim(s) with suspect metric/value "
                    f"pairing excluded from the note (kept in ledger/diagnostics).")
        return (f"⚠ {len(_suspects39)} claim(s) à appariement métrique/montant "
                f"suspect écarté(s) de la note (conservés au ledger, voir "
                f"diagnostics).")
    metrics = sorted({_qual16(f) for f in demoted})
    # B.1.3.8 — labels LOCALISÉS : « Chiffre d'affaires » dans une note EN
    # était compté comme résidu FR par le language gate (CR:3/deck:3 au run
    # dossier anglophone coté 3.7 → auto-plafonnement résiduel).
    try:
        from utils.financial_facts_table import _localize_metric_label as _lml_in
        metrics = [_lml_in(m, lang) for m in metrics]
    except Exception:
        pass
    joined = ", ".join(m for m in metrics if m)
    # B.1.3.5 — la mention « Brief CoDIR » n'apparaît QUE si un fait relégué
    # vient réellement du brief (la table CR appelle demote_brief=False : y
    # citer le Brief en exemple serait faux et troublant).
    _has_brief = any("brief" in str(_fact_attr(f, "source_doc", "") or "").lower()
                     for f in demoted)
    if lang == "fr":
        _src_txt = ("périmètre SOCIAL standalone Pappers et/ou source non "
                    "board-safe" + (", ex. Brief CoDIR" if _has_brief else ""))
        return ("⚠ Périmètre / source : " + joined + " — fait(s) relégué(s) de la "
                "table primaire board (" + _src_txt + "). Conservé(s) au ledger, "
                "non comparable(s) au consolidé groupe."
            + (f" · {len(_suspects39)} claim(s) à appariement suspect "
               f"écarté(s) (ledger/diagnostics)" if _suspects39 else ""))
    _src_txt = ("SOCIAL standalone Pappers scope and/or non-board-safe source"
                + (", e.g. CoDIR Brief" if _has_brief else ""))
    return ("⚠ Scope / source: " + joined + " — fact(s) demoted from the board "
            "primary table (" + _src_txt + "). Kept in the ledger, not "
            "comparable to group consolidated."
            + (f" · {len(_suspects39)} suspect metric/value pairing claim(s) "
               f"excluded (ledger/diagnostics)" if _suspects39 else ""))


# ─────────────────────────────────────────────────────────────────────────────
# 5. Invariant d'honnêteté sur le libellé de traçabilité
# ─────────────────────────────────────────────────────────────────────────────
CRITICAL_METRICS = ("Chiffre d'affaires", "Résultat net")


def traceability_label(table: Any, *, scorer_ok: bool,
                       critical=CRITICAL_METRICS, lang: str = "fr") -> dict:
    """Décide si le score de traçabilité peut s'afficher tel quel (board-safe)
    ou doit être GARDÉ.

    Gardé si : (a) le scorer a échoué, OU (b) une métrique consolidée critique
    (CA, résultat net) manque dans la table. Le score d'une table incomplète ou
    incohérente ne doit pas se présenter comme '100/100 board-safe'."""
    score = getattr(table, "traceability_score", 0) if not isinstance(table, dict) \
        else table.get("traceability_score", 0)
    facts = getattr(table, "facts", None) if not isinstance(table, dict) else table.get("facts")
    facts = facts or []
    # v17.1-B2.2.3 — une métrique consolidée critique n'est « couverte » que si
    # elle dispose d'au moins une source FORTE (RFA/URD/FY/PR). Un CA consolidé
    # sourcé uniquement « Brief CoDIR » (faible) ne doit PAS éteindre l'alerte
    # « métrique critique manquante » : sinon le score se déclare board-safe sur
    # une base non board-safe.
    strong_consolidated = {
        _canonical_fact_metric(f)
        for f in facts
        if _fact_attr(f, "scope") == "CONSOLIDATED" and _row_strength(f) == "STRONG"
    }
    weak_consolidated = {
        _canonical_fact_metric(f)
        for f in facts
        if _fact_attr(f, "scope") == "CONSOLIDATED" and _row_strength(f) != "STRONG"
    }
    # B.1.3 (audit dossier anglophone coté) — métriques couvertes UNIQUEMENT par le brief :
    # motif dédié « issues du brief, non sourcées indépendamment ».
    # B.1.3.6 (run dossier anglophone coté 3.5 : « missing: Revenue » avec Revenue AFFICHÉ
    # depuis le brief) — l'appelant docx passe des ROW-DICTS (to_row_dict)
    # où la clé est « source » (pas « source_doc ») : brief_covered restait
    # VIDE et la métrique brief-only retombait en missing/weak. On reconnaît
    # les deux formats + le flag brief_only (posé par la couche de preuve,
    # présent objets ET rows — la source la plus fiable).
    def _is_brief_src(f):
        if _fact_attr(f, "brief_only") is True:
            return True
        s = (str(_fact_attr(f, "source_doc", "") or "")
             or str(_fact_attr(f, "source", "") or ""))
        return s.strip().lower() == "brief"
    brief_covered = {
        _canonical_fact_metric(f)
        for f in facts
        if _fact_attr(f, "scope") == "CONSOLIDATED" and _is_brief_src(f)
    }
    missing = [m for m in critical if m not in strong_consolidated]
    # Distingue « absente » de « présente mais faiblement sourcée » pour le motif.
    weak_only = [m for m in missing if m in weak_consolidated]
    # B.1.3.6 (fix B.1.3.5 FANTÔME, posé pour de vrai + testé) — TRI-ÉTAT :
    # une métrique couverte par le BRIEF n'est plus « manquante » : elle est
    # « présente via le brief uniquement, non certifiée ». truly_missing la
    # soustrait ; brief_part (ci-dessous) la porte.
    truly_missing = [m for m in missing
                     if m not in weak_consolidated and m not in brief_covered]
    guarded = (not scorer_ok) or bool(missing)
    reasons = []
    if not scorer_ok:
        reasons.append("scorer indisponible (ERROR)" if lang == "fr" else "scorer unavailable (ERROR)")
    if truly_missing:
        # M.5.10.5 — labels localisés en EN (sinon « Chiffre d'affaires » fuyait)
        _tm = truly_missing
        if lang == "en":
            try:
                from utils.financial_facts_table import _localize_metric_label as _lml
                _tm = [_lml(m, "en") for m in truly_missing]
            except Exception:
                _tm = truly_missing
        reasons.append(("métriques consolidées critiques manquantes : " if lang == "fr"
                        else "critical consolidated metrics missing: ") + ", ".join(_tm))
    brief_part = [m for m in missing if m in brief_covered]
    weak_only = [m for m in weak_only if m not in brief_covered]
    if brief_part:
        _bp = brief_part
        if lang == "en":
            try:
                from utils.financial_facts_table import _localize_metric_label as _lml
                _bp = [_lml(m, "en") for m in brief_part]
            except Exception:
                _bp = brief_part
        reasons.append(("métriques critiques présentes via le brief uniquement "
                        "(non sourcées indépendamment, non board-safe) : "
                        if lang == "fr" else
                        "critical metrics from the brief only "
                        "(not independently sourced, not board-safe): ")
                       + ", ".join(_bp))
    if weak_only:
        _wo = weak_only
        if lang == "en":
            try:
                from utils.financial_facts_table import _localize_metric_label as _lml
                _wo = [_lml(m, "en") for m in weak_only]
            except Exception:
                _wo = weak_only
        reasons.append(("métriques critiques consolidées sourcées faiblement (non board-safe) : "
                        if lang == "fr"
                        else "critical consolidated metrics weakly sourced (not board-safe): ")
                       + ", ".join(_wo))
    if not guarded:
        label = (f"Traçabilité {score}/100 — board-safe" if lang == "fr"
                 else f"Traceability {score}/100 — board-safe")
    else:
        why = " ; ".join(reasons)
        # v17.1-B2.3.4 — on retire le « N/100 » trompeur du cas NON board-safe :
        # afficher « 100/100 — INDICATIF » donnait une fausse impression de sécurité
        # alors que les faits critiques sont faiblement sourcés.
        label = (f"Traçabilité indicative — non board-safe (usage interne supervisé) : {why}"
                 if lang == "fr"
                 else f"Traceability indicative — not board-safe (supervised internal use): {why}")
    return {"score": score, "guarded": guarded, "label": label, "reasons": reasons,
            "missing_critical": missing}



def _accounting_strong_proof(line: str) -> bool:
    """Preuve POSITIVE d'un état comptable — liste fermée.

    Un simple nom de pièce, une page, « liasse » ou « source: » prouve au mieux
    le montant cité, pas nécessairement que la provision a déjà été passée ni
    que l'impact résultat / capitaux propres est acquis. Le fail-closed est
    volontaire sur ce chemin exécutif.
    """
    import re as _re
    return bool(_re.search(
        r"(?:\[FAIT\s+COMPTABLE\]|\[ACCOUNTING\s+FACT\]|"
        r"(?:comptabilisation|provision|impact)\s+(?:explicitement\s+)?"
        r"(?:confirm[ée]e?|certifi[ée]e?)\s+par\s+(?:le\s+)?"
        r"(?:CAC|DAF|auditeur|expert[- ]comptable)|"
        r"(?:confirmed|certified)\s+by\s+(?:the\s+)?"
        r"(?:auditor|CFO|chartered\s+accountant)|"
        r"status_origin\s*[:=]\s*(?:DOCUMENT_EVIDENCE|TRUSTED_CONNECTOR|"
        r"MANUAL_HISTORY_EVENT)\b.*?evidence_ref\s*[:=]\s*\S+)",
        str(line or ""), _re.I))


def _accounting_amount(line: str) -> str:
    """Premier montant monétaire lisible, sans signe directionnel."""
    import re as _re
    s = str(line or "")
    patterns = (
        r"[-−‒–—]?\s*(\d+(?:[\s\u00a0]\d{3})*(?:[.,]\d+)?)\s*"
        r"(k€|M€|Md€|€|kEUR|MEUR|EUR|k£|m£|£|kUSD|mUSD|USD)(?![\w€£$])",
        r"(?:EUR|GBP|USD|€|£|\$)\s*[-−‒–—]?\s*"
        r"(\d+(?:[\s\u00a0]\d{3})*(?:[.,]\d+)?)\s*(k|m|bn|b)?\b",
    )
    for idx, pat in enumerate(patterns):
        m = _re.search(pat, s, _re.I)
        if m:
            if idx == 0:
                unit = m.group(2) or ""
                return f"{m.group(1)} {unit}".strip()
            # Devise préfixée : restituer le match sans signe, compact.
            raw = m.group(0).strip()
            raw = _re.sub(r"[-−‒–—]\s*", "", raw, count=1)
            return raw
    return ""


def _accounting_money_matches(text: str):
    """Return monetary tokens in display order.

    The matcher deliberately requires an explicit currency marker.  Years,
    percentages and headcount values are therefore never mistaken for an
    accounting impact amount.
    """
    import re as _re
    pattern = _re.compile(
        r"(?:"
        r"(?:EUR|GBP|USD|€|£|\$)\s*[-−‒–—+]?\s*"
        r"\d(?:[\d\s\u00a0.,]*\d)?\s*(?:k|m|bn|b)?\b|"
        r"[-−‒–—+]?\s*\d(?:[\d\s\u00a0.,]*\d)?\s*"
        r"(?:k€|M€|Md€|€|kEUR|MEUR|EUR|k£|m£|£|kGBP|mGBP|GBP|"
        r"kUSD|mUSD|USD)(?![\w€£$])"
        r")",
        _re.I,
    )
    return list(pattern.finditer(str(text or "")))


def _accounting_clean_amount(raw: str) -> str:
    """Normalize a matched monetary token for a conservative template."""
    import re as _re
    out = str(raw or "").strip()
    # Preserve the currency and magnitude, but never turn a negative sign into
    # an asserted direction in the caveat template.
    out = _re.sub(r"^([-−‒–—+])\s*", "", out)
    out = _re.sub(r"^((?:EUR|GBP|USD|€|£|\$)\s*)[-−‒–—+]\s*", r"\1", out,
                  flags=_re.I)
    return _re.sub(r"\s+", " ", out).strip()


def _accounting_split_segments(line: str):
    """Split a narrative line into locally governable propositions.

    Separators are preserved verbatim.  A comma or a coordination only opens a
    new proposition when it is followed by an accounting proposition generator
    (``impact``, ``provision``, ``liability``...).  This keeps ordinary nominal
    compounds such as ``provisions et charges constatées d'avance`` intact.
    """
    import re as _re
    _det = (r"(?:l['’]|la\s+|le\s+|les\s+|une?\s+|des?\s+|du\s+|"
            r"son\s+|sa\s+|ses\s+|leurs?\s+|notre\s+|nos\s+|"
            r"cet(?:te)?\s+|ces\s+|the\s+|an?\s+|its\s+|their\s+|our\s+|"
            r"this\s+|that\s+|these\s+|those\s+)?")
    _agg = (r"(?:(?:net\s+income|equity|P&L|balance\s+sheet|"
            r"r[ée]sultat(?:\s+net)?|capitaux\s+propres|bilan)\s+)?")
    _gen = (r"(?:impact|effet|charge\s+exceptionnelle|"
            r"exceptional\s+(?:charge|expense)|one[- ]off\s+(?:charge|expense)|"
            r"dette|passif|obligation|exposition|provision|dotation|charge|"
            r"liability|accrual)")
    look = rf"(?={_det}{_agg}{_gen}\b)"
    splitter = _re.compile(
        r"(\s*;\s*|\s+[—–]\s+|(?<=[.!?])\s+(?=[A-Za-zÀ-ÖØ-öø-ÿ])|"
        rf"\s*,\s*{look}|\s+(?:et|and)\s+{look})",
        _re.I,
    )
    return splitter.split(str(line or ""))



def _accounting_is_hypothetical(segment: str) -> bool:
    """True only for an explicitly hypothetical/future *local proposition*."""
    import re as _re
    return bool(_re.search(
        r"(?:\[ESTIM(?:\.|-|_)?HYPOTH|\bHYPOTH[ÈE]SE\b|\bSC[ÉE]NARIO\b|"
        r"\bpotentiel(?:le)?\b|\bpotential\b|\bindicati(?:f|ve)\b|"
        r"\bindicative\b|\bestim(?:é|ée|és|ées|ated)\b|\bhypothesis\b|"
        r"\bscenario\b|\bà\s+confirmer\b|\bto\s+be\s+confirmed\b|"
        # B.1.3.55 — conditionals, liaison futures and EN modals are local
        # hypothetical markers: a co-occurrence guard must not requalify
        # ``l'impact pourrait atteindre -327 k€`` or ``will amount to``.
        r"\bpourrai(?:t|ent)\b|\bdevrai(?:t|ent)\b|\bserai(?:t|ent)\b|"
        r"\batteindrai(?:t|ent)\b|\bs[’']élèverai(?:t|ent)\b|"
        r"\bressortirai(?:t|ent)\b|\bs[’']établirai(?:t|ent)\b|"
        r"\bs[’']élèvera\b|\batteindra\b|\bressortira\b|"
        r"\bs[’']établira\b|\bconviendra\b|\bsera\b|\bseront\b|"
        r"\bwill\s+(?:be|amount|reach|stand|total|come)\b|"
        r"\bcould\b|\bwould\b|\bmight\b|\bmay\b|\bshould\b|"
        r"\bexpected\s+to\b|\bprojected\b)",
        str(segment or ""), _re.I))



def _accounting_replace_impacts(segment: str, lang: str):
    """Downgrade exact accounting impacts in one proposition.

    The monetary token is associated with the *local* impact label, never with
    the first amount found elsewhere in the proposition.  Only the span from
    the label to its amount is rewritten; surrounding context, Markdown and
    parenthetical explanations are preserved.
    """
    import re as _re
    src = str(segment or "")
    if not src or _accounting_is_hypothetical(src):
        return src, 0
    en = str(lang or "fr").lower().startswith("en")

    label = (
        r"(?:"
        r"(?:impact|effet)\s+(?:(?:sur|on)\s+)?(?:the\s+|le\s+|les\s+)?"
        r"(?:r[ée]sultat(?:\s+net)?(?:\s+\d{4})?|capitaux\s+propres"
        r"(?:\s+consolid[ée]s?)?|bilan(?:\s+consolid[ée])?|net\s+income|"
        r"profit\s+and\s+loss|P&L|equity|balance\s+sheet)|"
        r"(?:net\s+income|P&L|equity|balance\s+sheet)\s+impact|"
        r"(?:r[ée]duction|diminution|hausse|baisse)\s+(?:des|du|de\s+la)\s+"
        r"(?:capitaux\s+propres|r[ée]sultat(?:\s+net)?|bilan)|"
        r"equity\s+(?:reduced|decreased|increased)\s+by|"
        r"(?:charge\s+exceptionnelle|exceptional\s+(?:charge|expense)|"
        r"one[- ]off\s+(?:charge|expense))"
        r")"
    )
    labels = list(_re.finditer(label, src, _re.I))
    amounts = _accounting_money_matches(src)
    if not labels or not amounts:
        return src, 0

    # Prefer the closest amount following a label.  An amount before the label
    # is accepted only when no following amount exists and remains very close
    # (e.g. ``GBP 327k net-income impact``).
    candidates = []
    for lab in labels:
        after = [m for m in amounts if m.start() >= lab.end() - 1
                 and m.start() - lab.end() <= 220]
        if after:
            amt = min(after, key=lambda m: m.start() - lab.end())
            candidates.append((amt.start() - lab.end(), lab, amt))
            continue
        before = [m for m in amounts if m.end() <= lab.start()
                  and lab.start() - m.end() <= 90]
        if before:
            amt = min(before, key=lambda m: lab.start() - m.end())
            candidates.append((lab.start() - amt.end() + 1000, lab, amt))
    if not candidates:
        return src, 0
    _, m_label, m_amount = min(candidates, key=lambda item: item[0])

    start = min(m_label.start(), m_amount.start())
    end = max(m_label.end(), m_amount.end())
    raw_label = m_label.group(0).replace("**", "").strip().rstrip(":").strip()
    raw_amount = _accounting_clean_amount(m_amount.group(0))
    if en:
        body = (f"{raw_label}: undetermined at this stage — indicative amount "
                f"{raw_amount} to be confirmed (CFO/auditor)")
    else:
        body = (f"{raw_label} : indéterminé à ce stade — montant indicatif "
                f"{raw_amount} à confirmer (DAF/CAC)")
    return src[:start] + body + src[end:], 1




def _accounting_replace_unprovided(segment: str, lang: str):
    """Requalify an exact unprovided/underprovided liability as indicative.

    A qualitative risk such as ``risque de sous-provisionnement`` is not a
    monetary assertion and is therefore preserved.  Requalification requires a
    currency-bearing amount in the matched assertion.
    """
    import re as _re
    src = str(segment or "")
    if not src or _accounting_is_hypothetical(src):
        return src, 0
    en = str(lang or "fr").lower().startswith("en")
    patterns = [
        _re.compile(
            r"\b(?:dette|passif|obligation|exposition)[^;\n]{0,180}?"
            r"\bnon\s+provisionn(?:ées|és|ée|é)\b[^;\n]*", _re.I),
        _re.compile(
            r"\b(?:passif\s+retraite\s+latent|sous[- ]provisionnement)"
            r"[^;\n]{0,180}", _re.I),
        _re.compile(
            r"\b(?:unprovided|unfunded|underprovided)\s+"
            r"(?:pension\s+)?(?:liability|obligation|exposure)[^;\n]{0,180}",
            _re.I),
    ]

    total = 0
    out = src
    for pat in patterns:
        def repl(m):
            nonlocal total
            amount = _accounting_amount(m.group(0))
            if not amount:
                return m.group(0)
            total += 1
            if en:
                return (f"indicative arithmetic exposure of {amount} — accounting "
                        "qualification, provision status and effects on net income/equity "
                        "to be confirmed (CFO/auditor)")
            return (f"exposition arithmétique indicative de {amount} — qualification "
                    "comptable, statut de provision et effets sur résultat/capitaux propres "
                    "à confirmer (DAF/CAC)")
        out = pat.sub(repl, out)
    return out, total




def _accounting_replace_completions(segment: str, lang: str, terminal: bool = True):
    """Requalify free-text assertions that an accounting entry is booked.

    The whole local proposition is reconstructed from a deterministic template.
    Budget entries, prepaid/deferred-account labels and historical reversals are
    protected.  When the proposition follows ``et/and``, a lower-case embedded
    template is used so the resulting sentence remains grammatical.
    """
    import re as _re
    src = str(segment or "")
    if not src:
        return src, 0
    en = str(lang or "fr").lower().startswith("en")

    # Protected accounting vocabulary: budget is not the ledger; a booked
    # provision that is explicitly reversed is a different historical claim;
    # CCA/PCA are fixed balance-sheet labels rather than an assertion that a new
    # entry was posted by this run.
    protected = (
        r"\b(?:budget|budg[ée]taire|budg[ée]taires|budgeted)\b|"
        r"\b(?:charges?|produits?)\s+constat(?:ée?|és|ées)\s+d['’]avance\b|"
        r"\b(?:prepaid|deferred)\s+(?:expense|income|revenue)s?\b|"
        r"\b(?:repris(?:e|es)?|reprise|contrepass(?:é|ée|és|ées)|"
        r"revers(?:ed|al)|written\s+back)\b"
    )
    if _re.search(protected, src, _re.I):
        return src, 0

    _adj = r"(?!\s+(?:en\s+\d{4}\s+)?(?:a|ont|est|sont|avait|avaient|sera|seront)\b)"
    fr_patterns = (
        r"\b(?:a|ont|avons|avez|avait|avaient)\s+(?:déjà\s+)?"
        r"(?:constaté|comptabilisé|enregistré|constitué|doté|"
        r"inscrit(?!\s+(?:au|aux)\s+budgets?)|passé)\s+"
        r"(?:une?\s+|la\s+|le\s+|les\s+|des?\s+)?"
        r"(?:provision|dotation|charge|passif|obligation|dette)s?\b",
        r"\b(?:a|ont|avons|avez|avait|avaient)\s+(?:déjà\s+)?provisionné\b",
        r"\b(?:une?\s+|la\s+|le\s+|les\s+|des?\s+)?"
        r"(?:provision|dotation|charge|passif|obligation|dette)s?"
        r"[^;\n]{0,90}?\b(?:a\s+été|ont\s+été|avai(?:t|ent)\s+été|est|sont|était|étaient)\s+"
        r"(?:déjà\s+)?(?:constat(?:ée?|és|ées)|"
        r"inscrit(?:es?|s)?(?!\s+(?:au|aux)\s+budgets?)|"
        r"enregistr(?:ée?|és|ées)|comptabilis(?:ée?|és|ées)|"
        r"constitu(?:ée?|és|ées)|dot(?:ée?|és|ées)|provisionn(?:ée?|és|ées)|"
        r"pass(?:ée?|és|ées)\s+(?:au\s+bilan|en\s+charges?|"
        r"en\s+provision|en\s+comptabilit[ée]))\b",
        r"(?:provision\s+)?d[ée]j[aà]\s+comptabilis(?:ées|és|ée|é)\b" + _adj,
        r"\bprovision\s+comptabilis(?:ées|és|ée|é)\b" + _adj,
        r"\bprovision\s+(?:constitu(?:ées|és|ée|é)|dot(?:ées|és|ée|é))\b" + _adj,
        r"\bpass(?:ées|és|ée|é)\s+(?:au\s+bilan|en\s+(?:charges?|provision|"
        r"comptabilit[ée]))\b",
        r"\benregistr(?:ées|és|ée|é)\s+(?:dans|en)\s+(?:les\s+)?"
        r"compt(?:es?|abilit[ée])\b",
    )
    en_patterns = (
        r"\b(?:a\s+|an\s+|the\s+)?(?:pension\s+)?"
        r"(?:provision|liability|obligation|charge|accrual)s?"
        r"[^;\n]{0,90}?\b(?:has|have|had|was|were|is|are)\s+"
        r"(?:already\s+)?(?:been\s+)?"
        r"(?:booked|recorded|recogni[sz]ed|accrued|posted)\b",
        r"\b(?:has\s+|have\s+|had\s+)?"
        r"(?:booked|recorded|recogni[sz]ed|accrued|posted)\s+"
        r"(?:a|an|the)\s+(?:new\s+|pension\s+)?"
        r"(?:provision|charge|liability|obligation|accrual)\b",
        r"\balready\s+(?:booked|recorded|recogni[sz]ed)\b",
        r"\b(?:booked|recorded|recogni[sz]ed)\s+in\s+the\s+accounts?\b",
    )
    patterns = en_patterns if en else fr_patterns
    if not any(_re.search(pat, src, _re.I) for pat in patterns):
        return src, 0

    amount = _accounting_amount(src)
    prefix_m = _re.match(r"^(\s*(?:[-*•]\s*)?(?:\*\*)?)", src)
    prefix = prefix_m.group(1) if prefix_m else ""
    suffix = ""
    stripped = src.rstrip()
    if prefix.endswith("**") and stripped.endswith("**"):
        suffix = "**"
    first_alpha = _re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", src)
    embedded = bool(first_alpha and first_alpha.group(0).islower()
                    and not prefix.strip().startswith(("-", "*", "•")))

    if en:
        m_obj = _re.search(
            r"\b(provision|charge|liability|obligation|accrual)s?\b", src, _re.I)
        obj = m_obj.group(1).lower() if m_obj else "entry"
        head = f"the {amount} {obj}" if amount else f"the {obj}"
        if embedded:
            body = f"the booking status to be confirmed (CFO/auditor) for {head}"
        else:
            body = f"Booking status to be confirmed (CFO/auditor) for {head}"
    else:
        m_obj = _re.search(
            r"\b(provision|dotation|charge|passif|obligation|dette)s?\b", src, _re.I)
        articles = {"provision": "la provision", "dotation": "la dotation",
                    "charge": "la charge", "dette": "la dette",
                    "obligation": "l’obligation", "passif": "le passif"}
        head = articles.get(m_obj.group(1).lower(), "l’écriture") if m_obj else "l’écriture"
        if amount:
            head += f" de {amount}"
        if embedded:
            body = f"le statut de comptabilisation à confirmer (DAF/CAC) pour {head}"
        else:
            body = f"Statut de comptabilisation à confirmer (DAF/CAC) pour {head}"
    if terminal and not suffix:
        body += "."
    return prefix + body + suffix, 1



def requalify_accounting_completions(text, lang="fr", return_changes=False):
    """Fail-closed governance of accounting assertions in generated narrative.

    B.1.3.53 ChatGPT candidate.  Free narrative is *never* an evidence channel:
    textual claims such as ``confirmed by CFO`` or ``evidence_ref=fake`` cannot
    bypass this function.  Trusted evidence must eventually arrive through a
    structured AccountingClaim object outside the LLM-authored text.

    Governance is proposition-scoped, not line-scoped, so a hypothetical clause
    cannot exempt a neighbouring completion or exact-impact assertion.
    """
    en = str(lang or "fr").lower().startswith("en")
    degraded = ("[Accounting proposition not governed — CFO/auditor check required]"
                if en else
                "[Proposition comptable non gouvernée — vérification DAF/CAC requise]")
    changes = []
    if not text:
        return (text, changes) if return_changes else text

    governed_lines = []
    for line_no, line in enumerate(str(text).splitlines(), start=1):
        parts = _accounting_split_segments(line)
        governed_parts = []
        for idx, part in enumerate(parts):
            # Captured separators occupy odd positions and are not governed.
            if idx % 2 == 1:
                governed_parts.append(part)
                continue
            if not part:
                governed_parts.append(part)
                continue
            try:
                current = part
                # Specific liability claims first: later impact replacements add
                # their own cautious qualifiers and must not accidentally exempt
                # an unprovided-liability assertion in the same proposition.
                current, n_unprovided = _accounting_replace_unprovided(current, lang)
                current, n_impact = _accounting_replace_impacts(current, lang)
                terminal = not any(
                    str(p).strip() for p in parts[idx + 1:])
                current, n_completion = _accounting_replace_completions(
                    current, lang, terminal=terminal)
                governed_parts.append(current)
                for action, count in (
                    ("impact_undetermined", n_impact),
                    ("exposure_requalified", n_unprovided),
                    ("booking_status_unproven", n_completion),
                ):
                    for _ in range(count):
                        changes.append({"action": action, "line_no": line_no,
                                        "line": part.strip()[:160]})
            except Exception as exc:
                governed_parts.append(degraded)
                changes.append({"action": "degraded", "line_no": line_no,
                                "reason": type(exc).__name__,
                                "line": part.strip()[:160]})
        governed_lines.append("".join(governed_parts))

    result = "\n".join(governed_lines)
    return (result, changes) if return_changes else result


def govern_accounting_outputs(outputs, lang="fr"):
    """Govern every generated section before DOCX/PPT/history consumption.

    Any internal failure is surfaced as ``status=ERROR`` and replaces the
    affected section with a localized conservative placeholder.  The engine is
    responsible for converting that ERROR into a formal non-validatable run.
    """
    governed = dict(outputs or {})
    en = str(lang or "fr").lower().startswith("en")
    fallback = ("[Accounting section not governed — CFO/auditor review required]"
                if en else
                "[Section comptable non gouvernée — vérification DAF/CAC requise]")
    report = {"changes": 0, "sections": {}, "samples": [], "status": "OK"}
    for key, value in list(governed.items()):
        if not isinstance(value, str) or not value:
            continue
        try:
            new_value, section_changes = requalify_accounting_completions(
                value, lang=lang, return_changes=True)
        except Exception as exc:
            new_value = fallback
            section_changes = [{"action": "degraded", "reason": type(exc).__name__}]
        if any(ch.get("action") == "degraded" for ch in section_changes):
            report["status"] = "ERROR"
            # A partly governed section is not safe to render.  Replace it
            # wholesale rather than allowing a mixed trusted/untrusted output.
            new_value = fallback
        governed[key] = new_value
        if section_changes:
            report["sections"][str(key)] = len(section_changes)
            report["changes"] += len(section_changes)
            for change in section_changes[:3]:
                report["samples"].append({"section": str(key), **change})
    report["samples"] = report["samples"][:10]
    return governed, report
