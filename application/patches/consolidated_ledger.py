"""
patches/consolidated_ledger.py — v17.1-B1

LEDGER CONSOLIDÉ UNIFIÉ (le pivot de la Tranche B).

Problème observé sur le run Lhyfe/FDE réel : deux couches de données qui ne se
parlent pas. L'agent finance extrait les vrais chiffres CONSOLIDÉS sourcés
(CA 9,8 M€, EBITDA -21,9 M€, RN -51 M€, trésorerie 74,7 M€ — RFA p.X), mais ils
restent dans le narratif/les claims. La couche déterministe (table de faits →
deck, comparatif, valorisation) ne lit que Pappers SOCIAL standalone (CA ~0/45 k€)
→ deck pauvre, comparatif faussé, valorisation « 0 méthode ».

Ce module promeut les FAITS financiers consolidés de l'agent finance dans la
table de faits unique, scope=CONSOLIDATED, sourcés. Ce ledger alimente ensuite
le deck, le comparatif déterministe et la valorisation — un seul cerveau.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional, Tuple

# Métriques financières reconnues. Le libellé canonique est choisi pour MATCHER
# les mots-clés de la valorisation (_FIN_KEYWORDS dans valuation_modeler) :
# « chiffre d'affaires » → revenue, « ebitda » → ebitda, « résultat net » →
# net_income, « capitaux propres » → equity.
_FACT_METRICS: list[tuple[str, str]] = [
    ("chiffre d'affaires", "Chiffre d'affaires"),
    ("chiffre d’affaires", "Chiffre d'affaires"),
    ("ebitda", "EBITDA"),
    ("résultat net", "Résultat net"),
    ("resultat net", "Résultat net"),
    ("perte nette", "Résultat net"),
    ("trésorerie", "Trésorerie"),
    ("tresorerie", "Trésorerie"),
    ("capitaux propres", "Capitaux propres"),
]

# Montant monétaire : exige un symbole de devise pour isoler « 9,8 M€ » et
# IGNORER les années (2025) et pourcentages (+92%).
_AMOUNT_RE = re.compile(
    r"-?\s*\d[\d\s\u202f.,]*\s*(?:Md|Mrd|bn|M|m|K|k)?\s*[€$£]"
)
_YEAR_RE = re.compile(r"\b(20\d\d)\b")
# B.1.3.20 (P0-A) — filings GROUPE : seuls porteurs du défaut CONSOLIDATED.
_GROUP_FILING_RE = re.compile(
    r"rfa|rapport\s+annuel|annual\s+report|comptes\s+consolid|"
    r"universal[\s\-]registration|urd|document\s+d['’]enregistrement",
    re.IGNORECASE)
# B.1.3.20 (P0-A) — sources PRIMAIRES (FAIT-éligibles) ; tout le reste
# (presse, article, magazine, web, interview…) → À VÉRIFIER.
_PRIMARY_SRC_RE = re.compile(
    r"comptes\s+(?:sociaux|annuels|consolid)|liasse|cerfa|rfa|"
    r"rapport\s+annuel|annual\s+report|urd|"
    r"universal[\s\-]registration|document\s+d['’]enregistrement|"
    r"prospectus|filing|amf\b|greffe|bodacc",
    re.IGNORECASE)
# B1.1-03 — extraire le n° de page d'une réf libre ("RFA 2025 p.118", "page 12").
_PAGE_RE = re.compile(r"\b(?:p\.?|pp\.?|page)\s*(\d{1,4})\b", re.IGNORECASE)


def _parse_source_ref(src: Optional[str]) -> Tuple[Optional[str], Optional[int]]:
    """'RFA 2025 p.118' → ('RFA 2025', 118). Sans page → (src, None)."""
    if not src:
        return (None, None)
    s = str(src).strip()
    m = _PAGE_RE.search(s)
    if not m:
        return (s, None)
    page = int(m.group(1))
    doc = _PAGE_RE.sub("", s).strip(" ,;:-—.")
    return (doc or s, page)


def extract_consolidated_fact(text: str) -> Optional[Tuple[str, str]]:
    """Depuis le texte d'un claim FAIT, renvoie (label_canonique, valeur) si on
    y reconnaît une métrique financière ET un montant monétaire ; sinon None.

    Ex. « CA 2025 : 9,8 M€ (+92% vs 2024) » → ("Chiffre d'affaires consolidé 2025", "9,8 M€")
    """
    if not text:
        return None
    low = text.lower()
    # B.1.3.20 (P0-A, run dossier industriel) — APPARIEMENT POSITIONNEL métrique↔montant.
    # Racine reproduite offline : « Comptes sociaux dossier industriel SAS 2021 : CA
    # 134,6 M€, résultat net 6,8 M€ » donnait ('Résultat net…', '134,6 M€') —
    # premier mot-clé de LISTE × premier montant du TEXTE, sans lien de
    # position. Désormais : métrique la plus PRÉCOCE dans le texte, appariée
    # au premier montant qui la SUIT (fallback : premier montant du texte si
    # la valeur précède la métrique — « 9,8 M€ de CA »).
    hits = []  # (start, end, canon)
    for kw, canon in _FACT_METRICS:
        i = low.find(kw)
        if i >= 0:
            hits.append((i, i + len(kw), canon))
    for m_ca in re.finditer(r"\bca\b", low):
        hits.append((m_ca.start(), m_ca.end(), "Chiffre d'affaires"))
    if not hits:
        return None
    hits.sort()
    # B.1.3.22 (F2, relecture critique) — règle d'ADJACENCE : une métrique
    # ne s'apparie qu'à un montant qui la suit SANS autre métrique entre les
    # deux (repro : « Résultat net en forte hausse. CA 2021 : 134,6 M€ » →
    # le RN précoce capturait le montant du CA). On prend la PREMIÈRE
    # métrique (ordre du texte) disposant d'un montant adjacent ; repli :
    # métrique la plus précoce + premier montant du texte (« 9,8 M€ de CA »).
    m_start = m_end = None
    metric = None
    m = None
    for i, (h_start, h_end, canon) in enumerate(hits):
        nxt = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        cand = _AMOUNT_RE.search(text, h_end)
        if cand and cand.start() < nxt:
            m_start, m_end, metric, m = h_start, h_end, canon, cand
            break
    if m is None:
        m_start, m_end, metric = hits[0]
        m = _AMOUNT_RE.search(text)
    if not m:
        return None
    value = re.sub(r"\s+", " ", m.group(0)).strip()
    ym = _YEAR_RE.search(text)
    # P0-A — plus de « consolidé » composé ici : le périmètre est résolu à la
    # promotion (preuve de source), le suffixe n'est ajouté que si CONSOLIDATED.
    label = metric + (f" {ym.group(1)}" if ym else "")
    return label, value


def _conf_to_float(conf: Any) -> Optional[float]:
    if conf is None:
        return None
    if isinstance(conf, (int, float)):
        try:
            return float(conf)
        except Exception:
            return None
    return {"high": 0.9, "haute": 0.9, "medium": 0.6, "moyenne": 0.6,
            "low": 0.3, "basse": 0.3}.get(str(conf).strip().lower())


def promote_finance_facts(table: Any, finance_claims: Iterable[Any]) -> int:
    """Promeut les claims FAIT financiers de l'agent finance dans la table de
    faits, scope=CONSOLIDATED. Retourne le nombre de faits promus.

    `table` : FinancialFactsTable (doit exposer .add(FinancialFact)).
    `finance_claims` : itérable d'objets claim (.tag, .text, .source_ref, .confidence)
                       ou de dicts équivalents.
    """
    if table is None or finance_claims is None:
        return 0
    try:
        from utils.financial_facts_table import FinancialFact, FactStatus
    except Exception:
        return 0

    def _g(c, k, default=None):
        return getattr(c, k, None) if not isinstance(c, dict) else c.get(k, default)

    # B.1.3.20 (P0-A, runs dossier industriel + dossier agroalimentaire) — le périmètre n'est PLUS
    # hardcodé CONSOLIDATED : il est résolu depuis le texte/la source (garde
    # F.6.8 réutilisée), et le statut suit la FORCE de la source (une presse
    # ancienne ne produit plus un ✅ FAIT consolidé fort).
    try:
        from patches.finance_shaper import detect_scope as _fs_detect_scope, \
            correct_perimeter as _fs_correct_perimeter
    except Exception:
        _fs_detect_scope = None
        _fs_correct_perimeter = None

    promoted = 0
    for c in finance_claims:
        if _g(c, "tag") != "FAIT":
            continue
        parsed = extract_consolidated_fact(_g(c, "text", "") or "")
        if not parsed:
            continue
        label, value = parsed
        src = _g(c, "source_ref")
        src_doc, src_page = _parse_source_ref(src)
        _blob = f"{_g(c, 'text', '') or ''} {src_doc or ''}"
        # 1) périmètre : détection sur pièces, défaut CONSOLIDATED réservé aux
        #    filings groupe (RFA / rapport annuel / comptes consolidés / URD) —
        #    l'hypothèse B-01 historique, désormais CONDITIONNÉE à la preuve.
        _scope = _fs_detect_scope(_blob) if _fs_detect_scope else "UNKNOWN"
        if _scope == "UNKNOWN" and _GROUP_FILING_RE.search(_blob):
            _scope = "CONSOLIDATED"
        if _fs_correct_perimeter:
            _scope = _fs_correct_perimeter(_scope, src_doc, label)
        # 2) statut : source primaire (comptes/liasse/filings) → FAIT ;
        #    presse / secondaire / non identifiée → À VÉRIFIER, non board-safe.
        _primary_src = bool(_PRIMARY_SRC_RE.search(_blob))
        _status = FactStatus.FAIT if _primary_src else FactStatus.A_VERIFIER
        _notes = ["Promu depuis l'extraction sourcée de l'agent finance (B-01)"]
        if not _primary_src:
            _notes.append("⚠ source secondaire (presse / non-filing) — "
                          "ordre de grandeur à confirmer, non board-safe")
        if _scope == "CONSOLIDATED":
            # suffixe d'affichage conservé pour la continuité Lhyfe
            _parts = label.rsplit(" ", 1)
            if _parts and _YEAR_RE.fullmatch(_parts[-1] or ""):
                label = f"{_parts[0]} consolidé {_parts[-1]}"
            else:
                label = f"{label} consolidé"
        fact = FinancialFact(
            label=label,
            value=value,
            source_doc=(src_doc or "Agent Finance — extraction consolidée sourcée"),
            source_page=src_page,
            status=_status,
            confidence=_conf_to_float(_g(c, "confidence")),
            scope=_scope,
            allowed_uses=(["narrative", "finance_model", "comparison"]
                          if _status == FactStatus.FAIT else ["narrative"]),
            notes=_notes,
        )
        try:
            before = len(getattr(table, "facts", []) or [])
            table.add(fact)
            if len(getattr(table, "facts", []) or []) > before:
                promoted += 1
        except Exception:
            continue
    return promoted


# Mapping métrique canonique → champ d'entité du comparatif.
_ENTITY_FIELD = {
    "Chiffre d'affaires": "ca",
    "Résultat net": "net_income",
    "Trésorerie": "tresorerie",
}


def enrich_primary_entity_with_consolidated(entities: list, table: Any) -> bool:
    """Met à jour l'entité PRIMAIRE du comparatif avec les chiffres CONSOLIDÉS
    du ledger (au lieu du social Pappers), et bascule son périmètre en
    CONSOLIDATED. L'entité secondaire reste en SOCIAL_STANDALONE : la colonne
    « Périmètre » du comparatif rend l'asymétrie explicite et honnête.

    Retourne True si l'entité primaire a été enrichie.
    """
    if not entities or table is None:
        return False
    # ── B.1.3.22 (F1, relecture critique post-3.21) — le comparatif ne
    # consomme que des faits PROBANTS. Racine reproduite : depuis P0-A, le
    # ledger contient des CONSOLIDATED **À VÉRIFIER** (presse, allowed_uses=
    # narrative seul) ; ce consommateur assumait « CONSOLIDATED = fiable »
    # (vrai en 3.19, tout promu était FAIT) et injectait « 76 M€ — Presse »
    # dans le comparatif déterministe servi aux agents. Filtre : statut FAIT
    # ET usage 'comparison' autorisé.
    try:
        from utils.financial_facts_table import FactStatus as _FS22
    except Exception:
        _FS22 = None

    def _fact_eligible_b1322(f) -> bool:
        st = getattr(f, "status", None)
        if _FS22 is not None:
            if st != _FS22.FAIT:
                return False
        else:  # repli sans import : « FAIT » strict, jamais À VÉRIFIER
            s = str(st)
            if not (s == "FAIT" or s.endswith(".FAIT")):
                return False
        uses = getattr(f, "allowed_uses", None)
        if uses is not None and "comparison" not in uses:
            return False
        return True

    facts = getattr(table, "facts", None) or []
    consolidated = {}
    sources: set[str] = set()
    for f in facts:
        if getattr(f, "scope", None) != "CONSOLIDATED":
            continue
        if not _fact_eligible_b1322(f):
            continue
        label = getattr(f, "label", "") or ""
        for canon, field in _ENTITY_FIELD.items():
            if canon.lower() in label.lower() and field not in consolidated:
                consolidated[field] = getattr(f, "value", None)
                ym = _YEAR_RE.search(label)
                if ym:
                    consolidated.setdefault("exercice", ym.group(1))
                sd = getattr(f, "source_doc", None)
                if sd:
                    sources.add(sd)
    if not consolidated:
        return False
    primary = entities[0]
    for field, val in consolidated.items():
        if val:
            primary[field] = val
    primary["scope"] = "CONSOLIDATED"
    # B1.1-01 — la source DOIT refléter l'origine consolidée (RFA/PR/agent
    # finance), jamais « Pappers » : Pappers ne fournit que le social/identité.
    if sources:
        primary["source"] = " / ".join(sorted(sources)) + " (consolidé) — identité : Pappers"
    else:
        primary["source"] = "Agent Finance (consolidé) — identité : Pappers"
    return True
