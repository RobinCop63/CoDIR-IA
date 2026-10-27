"""
patches/narrative_facts_promoter.py — F.6.8 / ticket F.6.7-05

Problème (audit dossier réseau de soins) : la FinancialFactsTable est construite uniquement à partir
de sources DÉTERMINISTES (Pappers + financial_statement_extractor). Quand l'extraction
structurée des pièces échoue, la table ne contient qu'un « Signal financier exploitable »
générique, alors que le NARRATIF des agents regorge de faits chiffrés ET page-cités
(produit exceptionnel 15,6 M€ p.2, goodwill 99,5 M€ p.1, comptes courants 35,4/67,1 M€...).

Ce module PROMEUT ces faits narratifs vers la table, mais SANS mentir sur leur provenance :
- ils ne sont PAS des FAIT déterministes → statut À VÉRIFIER ;
- ceux qui portent une citation de page reçoivent le badge épistémique « ESTIM-FILINGS »
  (valeur énoncée dans une liasse/annexe, remontée via le narratif, à confirmer vs source) ;
- les autres reçoivent « ESTIM-NARRATIF ».

Doctrine Q2 respectée : FAIT > ESTIM-FILINGS > ESTIM-NARRATIF > hypothèse.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

# ── Libellés financiers reconnus (FR), avec forme canonique ──────────────────
_LABELS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"produits?\s+exceptionnels?|résultat\s+exceptionnel", re.I), "Produit exceptionnel"),
    (re.compile(r"comptes?\s+courants?", re.I), "Compte courant"),
    (re.compile(r"goodwill|écart\s+d['’]acquisition|fonds\s+de\s+commerce", re.I), "Goodwill / fonds de commerce"),
    (re.compile(r"provisions?\s+(?:sur\s+)?stocks?|dépréciations?\s+(?:de\s+)?stocks?", re.I), "Provision sur stocks"),
    (re.compile(r"sur[\s-]?stock|stock\s+brut|stocks?\s+brut", re.I), "Stock brut / surstock"),
    (re.compile(r"résultat\s+net|\bRN\b", re.I), "Résultat net"),
    (re.compile(r"chiffre\s+d['’]affaires|\bCA\b", re.I), "Chiffre d'affaires"),
    (re.compile(r"trésorerie", re.I), "Trésorerie"),
    (re.compile(r"\bBFR\b|besoin\s+en\s+fonds\s+de\s+roulement", re.I), "BFR"),
    (re.compile(r"\bEBITDA\b", re.I), "EBITDA"),
    (re.compile(r"dette\s+nette|net\s+debt", re.I), "Dette nette"),
    (re.compile(r"marge\s+(?:nette|brute|opérationnelle)", re.I), "Marge"),
]

# Montant : 15,6 M€ / -557 K€ / +12,2 M€ / 4,8 M€ / 99,5 M€  (accepte . , espaces)
_AMOUNT = re.compile(
    r"[+\-]?\d{1,4}(?:[ .,]\d{3})*(?:[.,]\d{1,3})?\s?(?:M€|K€|Md€|M\$|K\$|€)",
    re.I,
)
# Citation de page : (p.29 ...) / p. 2 / p.1
_PAGE = re.compile(r"\bp\.?\s?(\d{1,4})\b", re.I)
# Entités sociales du dossier (scope SOCIAL_STANDALONE) — configuration, jamais codées.
from utils.entity_aliases import entity_alias_regex as _entity_alias_regex
# F.6.8 (audit dossier réseau de soins) — « holding / groupe / dossier réseau de soins Groupe » N'EST PAS une preuve
# de consolidation. Un fait de tête de groupe = HOLDING (social mère), pas CONSOLIDÉ.
_HOLDING = re.compile(
    r"holding|société\s+m[èe]re|maison\s+m[èe]re|t[êe]te\s+de\s+groupe",
    re.I)
_CONSO_PROOF = re.compile(
    r"comptes?\s+consolid|p[ée]rim[èe]tre\s+de\s+consolidation|"
    r"liasse\s+de\s+consolidation|[ée]tats?\s+financiers?\s+consolid|"
    r"bilan\s+consolid|consolidation\s+(?:tagetik|ifrs)",
    re.I)


def _clean_amount(raw: str) -> str:
    return re.sub(r"\s+", " ", raw).strip()


def _infer_scope_entity(window: str) -> Tuple[str, Optional[str]]:
    _entity_re = _entity_alias_regex()
    m = _entity_re.search(window) if _entity_re else None
    if m:
        return "SOCIAL_STANDALONE", m.group(1).capitalize()
    # Preuve de consolidation réelle requise pour CONSOLIDATED.
    if _CONSO_PROOF.search(window):
        return "CONSOLIDATED", "Groupe (consolidé)"
    if _HOLDING.search(window):
        return "HOLDING", "Holding (mère)"  # B.1.3.23 P0-E — label neutre (ex-hardcode « dossier réseau de soins Groupe » fui en livrable dossier agroalimentaire)
    return "UNKNOWN", None


# F.6.8 (audit dossier réseau de soins) — lignes d'ACTION/OBJECTIF (pas des faits sourcés) : un
# « réduire le compte courant de 20 M€ » ou « cible -1,5 M€ d'ici T3 » est une
# recommandation, pas un fait de bilan. On ne les promeut PAS dans la table.
_ACTION_LINE = re.compile(
    r"r[ée]duire|ramener|objectif|cible\s+de|cible\s*[:=]|d['’]ici|go\s+live|"
    r"mettre\s+en\s+place|plan\s+de\s+d[ée]stock|à\s+arbitrer|recommand[ée]|"
    r"\[À\s+SOUMETTRE|\[RECOMMAND|geler|r[ée]approvisionn|sortie\s+moyenne|"
    r"au\s+plus\s+tard|exécution\s+T",
    re.I)


def extract_narrative_facts(text: str, max_facts: int = 24,
                            include_uncited: bool = False) -> List[dict]:
    """Extrait les faits financiers chiffrés du narratif, ligne par ligne, ANCRÉS
    sur la citation de page (libellé + montant + p.XX dans la même clause = haute
    précision). Par défaut on ne promeut QUE les faits page-cités (ESTIM-FILINGS) :
    les fragments sans source seraient du bruit non board-safe.

    include_uncited=True ajoute aussi les lignes libellé+montant sans page
    (ESTIM-NARRATIF) — réservé à un usage interne, désactivé par défaut.
    """
    if not text or not isinstance(text, str):
        return []
    out: List[dict] = []
    seen = set()
    _ctx_scope, _ctx_entity = "UNKNOWN", None

    def _emit(canon, value, page, scope, entity):
        key = (canon.lower(), re.sub(r"\s+", "", value.lower()).lstrip("+"))
        if key in seen:
            return False
        seen.add(key)
        label = f"{canon} {entity}" if entity else canon
        out.append({
            "label": label, "value": value, "page": page, "scope": scope,
            "epistemic": "ESTIM-FILINGS" if page else "ESTIM-NARRATIF",
        })
        return True

    def _label_of(cell):
        for label_re, canon in _LABELS:
            if label_re.search(cell):
                return canon
        return None

    for line in text.splitlines():
        if len(line) < 4:
            continue
        # — Suivi du PÉRIMÈTRE de section : un titre/ligne courte mentionnant une
        #   entité ou un périmètre (filiale A/filiale B/holding/consolidé) fixe le contexte
        #   appliqué aux lignes de tableau qui suivent.
        _is_head = (line.lstrip().startswith("#")
                    or (line.count("**") >= 2 and not _AMOUNT.search(line)))
        if _is_head:
            sc, ent = _infer_scope_entity(line)
            if sc != "UNKNOWN" or ent:
                _ctx_scope, _ctx_entity = sc, ent
            continue
        if _ACTION_LINE.search(line):
            continue

        # 1) LIGNE DE TABLEAU markdown « | Libellé | Valeur | … | » (extraction FIABLE)
        if line.count("|") >= 3:
            cells = [c.strip().strip("*").strip() for c in line.split("|")]
            cells = [c for c in cells if c]
            canon = None
            label_cell = None
            for c in cells:
                cc = _label_of(c)
                if cc:
                    canon, label_cell = cc, c
                    break
            if canon:
                value = None
                for c in cells:
                    if c is label_cell:
                        continue
                    am = _AMOUNT.search(c)
                    if am:
                        # « < 50 k€ », « > 1 300 € », « moins de 50 k€ » sont
                        # des seuils/cibles, pas des valeurs observées.
                        prefix = c[max(0, am.start() - 14):am.start()]
                        if re.search(r"(?:[<>≤≥]|moins\s+de|plus\s+de|inf[ée]rieur|sup[ée]rieur)\s*$",
                                     prefix, re.I):
                            continue
                        value = _clean_amount(am.group(0))
                        break
                if value:
                    pg = _PAGE.search(line)
                    page = int(pg.group(1)) if pg else None
                    sc, ent = _ctx_scope, _ctx_entity
                    rl_sc, rl_ent = _infer_scope_entity(line)
                    if rl_sc != "UNKNOWN":
                        sc, ent = rl_sc, rl_ent
                    if _emit(canon, value, page, sc, ent) and len(out) >= max_facts:
                        return out
            continue

        # 2) PROSE : on ne promeut QUE les lignes page-citées (ESTIM-FILINGS). La
        #    prose multi-chiffres NON sourcée crée des mésattributions → on la jette.
        pg = _PAGE.search(line)
        if not pg:
            continue
        page = int(pg.group(1))
        for label_re, canon in _LABELS:
            for lm in label_re.finditer(line):
                l_start, l_end = lm.start(), lm.end()
                am = _AMOUNT.search(line, l_end)
                if not am or (am.start() - l_end) > 70:
                    cands = [a for a in _AMOUNT.finditer(line[:l_start])]
                    am = cands[-1] if cands and (l_start - cands[-1].end()) < 40 else None
                    if not am:
                        continue
                prefix = line[max(0, am.start() - 14):am.start()]
                if re.search(r"(?:[<>≤≥]|moins\s+de|plus\s+de|inf[ée]rieur|sup[ée]rieur)\s*$",
                             prefix, re.I):
                    continue
                value = _clean_amount(am.group(0))
                w0 = max(0, l_start - 45)
                w1 = min(len(line), max(am.end(), l_end) + 45)
                scope, entity = _infer_scope_entity(line[w0:w1])
                if scope == "UNKNOWN" and _ctx_scope != "UNKNOWN":
                    scope, entity = _ctx_scope, _ctx_entity
                if _emit(canon, value, page, scope, entity) and len(out) >= max_facts:
                    return out
    return out


def promote_narrative_facts(text: str, table: Any, *, max_facts: int = 40,
                            allow_uncited: bool = False) -> int:
    """Promeut les faits narratifs page-cités dans la table (statut À VÉRIFIER +
    badge épistémique). Dédoublonne contre les faits déjà présents (même libellé
    canonique + même valeur). Renvoie le nombre de faits ajoutés.

    `table` doit exposer `.add(fact)` et `.facts` (liste de FinancialFact).
    Tolérant : toute erreur d'import/forme renvoie 0 sans lever.
    """
    try:
        from utils.financial_facts_table import FinancialFact, FactStatus
    except Exception:
        return 0
    if table is None:
        return 0

    # v62.4 terrain dossier de conseil — fail-closed. Un narratif agent sans page et sans
    # pièce source ne peut plus fabriquer un pseudo-fait financier (ex. « CA < 50
    # k€ » promu à tort en « -50 k€ »). Les faits non page-cités ne sont admis que
    # lorsqu'un appelant disposant réellement du corpus documentaire l'autorise.
    extracted = extract_narrative_facts(
        text, max_facts=max_facts, include_uncited=bool(allow_uncited))
    if not extracted:
        return 0

    def _vnorm(v: str) -> str:
        # « +12,2 M€ » et « 12,2 M€ » = même fait (le + n'est qu'emphase) ; on retire
        # le + de tête pour dédoublonner, mais PAS le - (−0,6 ≠ +0,6).
        return re.sub(r"\s+", "", str(v).lower()).lstrip("+")

    # valeurs déjà présentes (pour ne pas doublonner un FAIT déterministe)
    existing_values = set()
    for f in getattr(table, "facts", []) or []:
        existing_values.add(_vnorm(getattr(f, "value", "")))

    promoted = 0
    for d in extracted:
        vnorm = _vnorm(d["value"])
        if vnorm in existing_values:
            continue  # déjà capté en déterministe → on ne double pas
        notes = [f"[{d['epistemic']}] promu du narratif — à confirmer vs source"]
        try:
            fact = FinancialFact(
                label=d["label"],
                value=d["value"],
                source_doc="Narratif agents (page citée)" if d["page"] else "Narratif agents",
                source_page=d["page"],
                status=FactStatus.A_VERIFIER,
                confidence=0.55 if d["page"] else 0.4,
                notes=notes,
                scope=d["scope"],
                allowed_uses=["narrative"],
            )
            table.add(fact)
            existing_values.add(vnorm)
            promoted += 1
        except Exception:
            continue
    return promoted
