"""
patches/extraction_fidelity.py — Cycle D, brique 1 : FIDÉLITÉ D'EXTRACTION
ligne-à-ligne (v17.1.0-B2.3-F.6.0-D1).

PROBLÈME RÉSOLU
---------------
Le ledger déterministe (`finance_shaper` / `consolidated_ledger`) construit ses
faits à partir des CLAIMS d'agents : la valeur d'un fait est celle que l'agent a
ÉCRITE, la source est la référence qu'il a CITÉE. Le `confidence_scorer` vérifie
qu'un fait POSSÈDE une source (FAIT_VERIFIED vs FAIT_ASSERTED) — mais personne ne
vérifie que la VALEUR écrite est réellement PRÉSENTE, verbatim, dans le texte
source. Un agent peut lire « 12,3 » et écrire « 13,2 », changer la période,
transposer un chiffre. Ce module comble ce trou.

PRINCIPE (déterministe, aucune valeur ni nom en dur)
----------------------------------------------------
Pour chaque fait porteur d'une valeur numérique, on cherche cette valeur dans le
corpus source fourni au moment du run, après normalisation des formats :
  - séparateurs FR/EN (« 12,3 » ↔ « 12.3 », « 12 345 » ↔ « 12,345 ») ;
  - échelles (« M », « Md/Mds », « k », « million », « milliard », « billion ») ;
  - devises et pourcentages (le « % » est une dimension distincte : « 12,3 % » ne
    matche jamais « 12,3 M€ »).

GOUVERNANCE — ASYMÉTRIE VOLONTAIRE (cardinal : zéro latitude sur la présentation
trompeuse, latitude sur l'analyse)
  - VALEUR RETROUVÉE  → signal POSITIF (« confirmée ligne-à-ligne dans la source »).
  - VALEUR NON RETROUVÉE → signal de PRUDENCE (« non retrouvée dans le corpus
    source — à vérifier »), JAMAIS une suppression ni un verdict automatique : le
    corpus finance est partiel, l'absence n'est pas une preuve d'erreur. La
    décision reste humaine (même discipline que le registre Cycle C : pas
    d'action automatique). Module SIGNAL-ONLY, fail-open.

Pur calcul → entièrement testable hors-ligne. La précision/rappel sur de vrais
documents (variété de mise en forme) se valide en run réel.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple

__all__ = [
    "FIDELITY_VERBATIM", "FIDELITY_NORMALIZED", "FIDELITY_NOT_FOUND",
    "FIDELITY_NO_NUMERIC", "FIDELITY_SOURCE_UNAVAILABLE",
    "CORPUS_NARRATIVE", "CORPUS_INPUT_CORPUS", "CORPUS_SOURCE_DOCUMENT",
    "FIDELITY_VERBATIM_ON_PAGE", "FIDELITY_NORMALIZED_ON_PAGE",
    "FIDELITY_NOT_ON_CITED_PAGE", "FIDELITY_PAGE_UNAVAILABLE", "FIDELITY_NO_CITATION",
    "normalize_number", "numeric_tokens", "is_percentage_context",
    "check_value_fidelity", "dual_corpus_fidelity",
    "annotate_facts_fidelity", "annotate_facts_fidelity_dual",
    "fidelity_summary", "fidelity_summary_dual", "fidelity_signal",
    "index_corpus_by_page", "per_fact_page_fidelity",
    "annotate_facts_per_page", "per_page_summary",
]

# Niveaux de fidélité (du plus fort au plus faible)
FIDELITY_VERBATIM   = "verbatim"      # la valeur apparaît telle quelle dans le corpus fourni
FIDELITY_NORMALIZED = "normalized"    # la valeur apparaît après normalisation (échelle/format)
FIDELITY_NOT_FOUND  = "not_found"     # valeur numérique non retrouvée dans le corpus → à vérifier
FIDELITY_NO_NUMERIC = "no_numeric"    # le fait n'a pas de valeur numérique vérifiable (qualitatif)
FIDELITY_SOURCE_UNAVAILABLE = "source_unavailable"  # AUCUN corpus à confronter → on ne peut pas conclure

# Nature du corpus confronté — HONNÊTETÉ (audit F.6.1) : le pipeline fournit
# aujourd'hui la SYNTHÈSE Finance (texte narratif généré), pas le texte de la
# source documentaire originale (page RFA/PDF/communiqué). Tant que le texte de
# page source n'est pas retenu sur le fait, on parle de COHÉRENCE vs synthèse
# Finance, pas de fidélité vs source documentaire. Le paramètre `corpus_kind`
# rend cette distinction explicite partout.
CORPUS_NARRATIVE = "narrative"          # synthèse Finance (finance_txt) — sortie agent
CORPUS_INPUT_CORPUS = "input_corpus"    # documents d'ENTRÉE donnés aux agents (brief)
CORPUS_SOURCE_DOCUMENT = "source_document"  # texte de page source original (futur, per-fait)

# F.6.6 — fidélité PER-FAIT / PER-PAGE : prouver qu'une valeur figure À LA PAGE
# qu'elle cite (source_doc + source_page), pas seulement quelque part dans le
# corpus concaténé. C'est le saut demandé par les audits F.6.1→F.6.5.
FIDELITY_VERBATIM_ON_PAGE   = "verbatim_on_page"     # valeur trouvée telle quelle à la page citée
FIDELITY_NORMALIZED_ON_PAGE = "normalized_on_page"   # trouvée à la page citée après normalisation
FIDELITY_NOT_ON_CITED_PAGE  = "not_found_on_cited_page"  # page connue mais valeur ABSENTE → mauvaise citation / hallucination
FIDELITY_PAGE_UNAVAILABLE   = "page_unavailable"     # page citée non présente dans le corpus
FIDELITY_NO_CITATION        = "no_citation"          # le fait ne cite ni document ni page


def dual_corpus_fidelity(value_text: Optional[str], input_corpus: Optional[str],
                         narrative_corpus: Optional[str] = None) -> Dict[str, Any]:
    """F.6.3 — contrôle DOUBLE CORPUS, plus proche de la vraie fidélité source.

    Vérifie la valeur d'abord contre le CORPUS D'ENTRÉE (les documents donnés aux
    agents = `brief`), corpus le plus proche de la source. Puis, si absente de
    l'entrée mais présente dans la synthèse Finance (sortie agent), lève un
    drapeau `narrative_only` = SIGNAL D'HALLUCINATION POSSIBLE (la valeur a été
    écrite par l'agent sans figurer dans les documents fournis) — exactement le
    cas que cherche un audit M&A. Renvoie {level, corpus_kind, narrative_only}.

    Reste un SIGNAL (jamais un verdict) : un corpus d'entrée partiel peut
    expliquer une absence légitime.
    """
    lvl_in = check_value_fidelity(value_text, input_corpus)
    if lvl_in in (FIDELITY_VERBATIM, FIDELITY_NORMALIZED):
        return {"level": lvl_in, "corpus_kind": CORPUS_INPUT_CORPUS,
                "narrative_only": False}
    if lvl_in in (FIDELITY_NO_NUMERIC,):
        return {"level": lvl_in, "corpus_kind": CORPUS_INPUT_CORPUS,
                "narrative_only": False}
    # non retrouvée (ou corpus d'entrée indisponible) → on regarde la synthèse
    narrative_only = False
    if narrative_corpus:
        lvl_narr = check_value_fidelity(value_text, narrative_corpus)
        if lvl_narr in (FIDELITY_VERBATIM, FIDELITY_NORMALIZED):
            narrative_only = True      # dans la synthèse, PAS dans les documents
    return {"level": lvl_in, "corpus_kind": CORPUS_INPUT_CORPUS,
            "narrative_only": narrative_only}

# Un token numérique : signe, chiffres avec séparateurs ., espaces (y c. nbsp/narrow),
# décimale optionnelle, échelle optionnelle, % optionnel.
_NUM_RE = re.compile(
    r"(?P<sign>[-−]?)\s*"
    r"(?P<int>\d{1,3}(?:[ \u00a0\u202f.,]\d{3})*|\d+)"
    r"(?:(?P<decsep>[.,])(?P<dec>\d+))?"
    r"\s*(?P<scale>milliards?|billions?|millions?|mds?|md|bn|m|k|thousands?|milliers?)?"
    r"\s*(?P<pct>%)?",
    re.IGNORECASE,
)

_REL_EPS = 1e-9


def _strip_accents_lower(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _to_canonical(int_part: str, dec_sep: Optional[str], dec_part: Optional[str],
                  scale: Optional[str]) -> Optional[float]:
    """Reconstitue la magnitude numérique canonique d'un token.

    La partie entière peut contenir des séparateurs de milliers (espace, point ou
    virgule). On lève l'ambiguïté virgule/point ainsi : le séparateur DÉCIMAL
    explicitement capté (`dec_sep`) est retiré des milliers ; tout autre `.`/`,`/
    espace dans la partie entière est un séparateur de milliers.
    """
    digits = re.sub(r"[ \u00a0\u202f.,]", "", int_part)
    if not digits.isdigit():
        return None
    val = float(digits)
    if dec_part is not None:
        try:
            val = float(f"{digits}.{dec_part}")
        except ValueError:
            return None
    if scale:
        sl = _strip_accents_lower(scale).strip().rstrip("s")  # milliards→milliard
        mult = {
            "milliard": 1e9, "billion": 1e9, "md": 1e9, "mds": 1e9, "bn": 1e9,
            "million": 1e6, "m": 1e6,
            "k": 1e3, "thousand": 1e3, "millier": 1e3, "milier": 1e3,
        }.get(sl)
        if mult:
            val *= mult
    return val


def normalize_number(text: str) -> Optional[Dict[str, Any]]:
    """Renvoie la 1re valeur numérique normalisée d'un texte, ou None.

    Résultat : {'magnitude': float, 'is_pct': bool, 'raw': str}. Exemples
    génériques : « 12,3 M€ » → 12_300_000 ; « 1,5 Md€ » → 1_500_000_000 ;
    « 12 345 » → 12345 ; « 12.3% » → is_pct=True, magnitude=12.3.
    """
    toks = numeric_tokens(text)
    return toks[0] if toks else None


def numeric_tokens(text: str) -> List[Dict[str, Any]]:
    """Tous les tokens numériques normalisés d'un texte (ordre d'apparition)."""
    if not text:
        return []
    out: List[Dict[str, Any]] = []
    for m in _NUM_RE.finditer(text):
        int_part = m.group("int")
        if int_part is None:
            continue
        mag = _to_canonical(int_part, m.group("decsep"), m.group("dec"), m.group("scale"))
        if mag is None:
            continue
        if m.group("sign") in ("-", "−"):
            mag = -mag
        out.append({
            "magnitude": mag,
            "is_pct": bool(m.group("pct")),
            "raw": m.group(0).strip(),
        })
    return out


def is_percentage_context(text: str) -> bool:
    return "%" in (text or "")


def _magnitudes_match(a: float, b: float) -> bool:
    """Égalité canonique exacte (à epsilon relatif près), OU égalité aux chiffres
    significatifs de la valeur du fait (tolère « 12,3 M€ » côté fait ↔
    « 12 345 000 » côté source : ≈ mêmes 3 c.s.)."""
    if a == 0 and b == 0:
        return True
    denom = max(abs(a), abs(b), 1.0)
    if abs(a - b) / denom <= _REL_EPS:
        return True
    sig = _sig_figs(a)
    if sig is not None and sig >= 1:
        ra = _round_sig(a, sig)
        rb = _round_sig(b, sig)
        if ra != 0 and abs(ra - rb) / max(abs(ra), 1.0) <= _REL_EPS:
            return True
    return False


def _sig_figs(x: float) -> Optional[int]:
    s = f"{abs(x):.10g}".replace(".", "").lstrip("0")
    return len(s) if s else None


def _round_sig(x: float, sig: int) -> float:
    if x == 0:
        return 0.0
    from math import floor, log10
    return round(x, -int(floor(log10(abs(x)))) + (sig - 1))


def check_value_fidelity(value_text: Optional[str],
                         source_text: Optional[str]) -> str:
    """Niveau de fidélité d'une valeur de fait vis-à-vis du corpus source.

    - FIDELITY_NO_NUMERIC si la valeur n'a pas de nombre vérifiable ;
    - FIDELITY_VERBATIM si la valeur (nettoyée) est sous-chaîne du corpus ;
    - FIDELITY_NORMALIZED si un token source a la même magnitude (et même nature
      %/non-%) après normalisation ;
    - FIDELITY_NOT_FOUND sinon.
    """
    if not value_text:
        return FIDELITY_NO_NUMERIC
    fact_tok = normalize_number(value_text)
    if fact_tok is None:
        return FIDELITY_NO_NUMERIC
    if not source_text:
        # On n'a AUCUN corpus à confronter : on ne peut pas conclure (≠ « non
        # trouvé »). Honnêteté : absence de vérification, pas verdict.
        return FIDELITY_SOURCE_UNAVAILABLE

    # 1) verbatim : sous-chaîne (espaces normalisés, y c. nbsp/narrow)
    def _ws(s: str) -> str:
        return re.sub(r"[ \u00a0\u202f]+", " ", s).strip()
    needle = _ws(value_text)
    hay = _ws(source_text)
    if needle and needle in hay:
        return FIDELITY_VERBATIM

    # 2) normalisé : même magnitude + même nature (pourcentage ou non)
    for tok in numeric_tokens(source_text):
        if tok["is_pct"] != fact_tok["is_pct"]:
            continue
        if _magnitudes_match(fact_tok["magnitude"], tok["magnitude"]):
            return FIDELITY_NORMALIZED
    return FIDELITY_NOT_FOUND


def _fact_value(fact: Any) -> Optional[str]:
    for attr in ("value", "valeur", "amount"):
        v = getattr(fact, attr, None)
        if v:
            return str(v)
    if isinstance(fact, dict):
        for k in ("value", "valeur", "amount"):
            if fact.get(k):
                return str(fact[k])
    return None


def annotate_facts_fidelity(facts: Iterable[Any],
                            source_text: Optional[str]) -> Dict[str, int]:
    """Annote chaque fait d'un attribut `fidelity` (signal-only) et renvoie un
    récapitulatif {verbatim, normalized, not_found, no_numeric}. Fail-open :
    n'altère JAMAIS la valeur d'un fait, ne supprime rien."""
    summary = {FIDELITY_VERBATIM: 0, FIDELITY_NORMALIZED: 0,
               FIDELITY_NOT_FOUND: 0, FIDELITY_NO_NUMERIC: 0,
               FIDELITY_SOURCE_UNAVAILABLE: 0}
    if facts is None:
        return summary
    for f in facts:
        try:
            level = check_value_fidelity(_fact_value(f), source_text)
        except Exception:
            level = FIDELITY_NO_NUMERIC
        try:
            if isinstance(f, dict):
                f["fidelity"] = level
            else:
                setattr(f, "fidelity", level)
        except Exception:
            pass
        summary[level] = summary.get(level, 0) + 1
    return summary


def fidelity_summary(table: Any, source_text: Optional[str],
                     corpus_kind: str = CORPUS_NARRATIVE) -> Dict[str, Any]:
    """Récapitulatif de fidélité sur les faits d'une table de ledger (cherche
    .facts / .rows / itérable). Annoté au passage. Le récap porte `corpus_kind`
    (narrative vs source_document) pour un affichage honnête en aval. Fail-open."""
    facts = None
    for attr in ("facts", "rows", "items", "entries"):
        cand = getattr(table, attr, None)
        if cand:
            facts = cand
            break
    if facts is None and isinstance(table, (list, tuple)):
        facts = table
    if facts is None:
        return {FIDELITY_VERBATIM: 0, FIDELITY_NORMALIZED: 0,
                FIDELITY_NOT_FOUND: 0, FIDELITY_NO_NUMERIC: 0,
                FIDELITY_SOURCE_UNAVAILABLE: 0, "corpus_kind": corpus_kind}
    summ = annotate_facts_fidelity(facts, source_text)
    summ["corpus_kind"] = corpus_kind
    return summ


def annotate_facts_fidelity_dual(facts: Iterable[Any], input_corpus: Optional[str],
                                 narrative_corpus: Optional[str] = None) -> Dict[str, int]:
    """F.6.3 — annote chaque fait (.fidelity contre le CORPUS D'ENTRÉE + drapeau
    .fidelity_narrative_only si la valeur n'est que dans la synthèse). Renvoie un
    récap incluant `narrative_only` (nombre de valeurs présentes dans la synthèse
    Finance mais ABSENTES des documents d'entrée = hallucinations possibles).
    Signal-only, fail-open : n'altère aucune valeur."""
    summary = {FIDELITY_VERBATIM: 0, FIDELITY_NORMALIZED: 0, FIDELITY_NOT_FOUND: 0,
               FIDELITY_NO_NUMERIC: 0, FIDELITY_SOURCE_UNAVAILABLE: 0,
               "narrative_only": 0, "corpus_kind": CORPUS_INPUT_CORPUS}
    if facts is None:
        return summary
    for f in facts:
        try:
            res = dual_corpus_fidelity(_fact_value(f), input_corpus, narrative_corpus)
            level, narr_only = res["level"], res["narrative_only"]
        except Exception:
            level, narr_only = FIDELITY_NO_NUMERIC, False
        try:
            if isinstance(f, dict):
                f["fidelity"] = level
                f["fidelity_narrative_only"] = narr_only
            else:
                setattr(f, "fidelity", level)
                setattr(f, "fidelity_narrative_only", narr_only)
        except Exception:
            pass
        summary[level] = summary.get(level, 0) + 1
        if narr_only:
            summary["narrative_only"] += 1
    return summary


def fidelity_summary_dual(table: Any, input_corpus: Optional[str],
                          narrative_corpus: Optional[str] = None) -> Dict[str, Any]:
    """Récap double-corpus sur une table de ledger (.facts / .rows / itérable)."""
    facts = None
    for attr in ("facts", "rows", "items", "entries"):
        cand = getattr(table, attr, None)
        if cand:
            facts = cand
            break
    if facts is None and isinstance(table, (list, tuple)):
        facts = table
    if facts is None:
        return {FIDELITY_VERBATIM: 0, FIDELITY_NORMALIZED: 0, FIDELITY_NOT_FOUND: 0,
                FIDELITY_NO_NUMERIC: 0, FIDELITY_SOURCE_UNAVAILABLE: 0,
                "narrative_only": 0, "corpus_kind": CORPUS_INPUT_CORPUS}
    return annotate_facts_fidelity_dual(facts, input_corpus, narrative_corpus)


_DOC_HEADER_RE = re.compile(r"^###\s*Fichier\s*:\s*(.+?)\s*$", re.MULTILINE)
# Format financial_statements_block : "--- 📄 fichier.pdf (total 180 pages) ---"
_DOC_HEADER_FS_RE = re.compile(r"^---\s*📄?\s*(.+?)\s*---\s*$", re.MULTILINE)
_PAGE_HEADER_RE = re.compile(r"^##\s*(?:Page|Slide)\s+(\d+)\s*$", re.MULTILINE)
# Format financial_statements_block : "-- p.118 --"
_PAGE_HEADER_FS_RE = re.compile(r"^--\s*p\.\s*(\d+)\s*--\s*$", re.MULTILINE)


def _norm_doc(name: Optional[str]) -> str:
    """Normalise un nom de document pour rapprochement (minuscule, sans extension,
    sans tag entre crochets/parenthèses — ex. « (total 180 pages) » —, sans chemin)."""
    if not name:
        return ""
    s = str(name).strip().lower()
    s = re.sub(r"[\[(].*?[\])]", "", s)          # retire tags [tronqué] / (total N pages)
    s = s.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]  # basename
    s = re.sub(r"\.(pdf|docx?|pptx?|xlsx?|csv|txt|md)$", "", s.strip())
    return s.strip()


def index_corpus_by_page(corpus: Optional[str]) -> Dict[str, Dict[int, str]]:
    """Parse un corpus assemblé en index {document_normalisé: {page:int -> texte}}.
    Reconnaît LES DEUX formats réels du pipeline (fail-open : {} si vide) :
      - attachments_block      : « ### Fichier: X »   + « ## Page N » / « ## Slide N »
      - financial_statements   : « --- 📄 X (total N pages) --- » + « -- p.N -- »
    Permet la fidélité PER-PAGE : retrouver le texte EXACT de la page citée."""
    index: Dict[str, Dict[int, str]] = {}
    if not corpus:
        return index
    # 1) Frontières de documents (les deux formats), triées par position
    doc_marks = [(m.start(), m.end(), _norm_doc(m.group(1)))
                 for m in _DOC_HEADER_RE.finditer(corpus)]
    doc_marks += [(m.start(), m.end(), _norm_doc(m.group(1)))
                  for m in _DOC_HEADER_FS_RE.finditer(corpus)]
    doc_marks.sort()
    if not doc_marks:
        spans = [("", 0, len(corpus))]
    else:
        spans = []
        for i, (_, end, doc) in enumerate(doc_marks):
            nxt = doc_marks[i + 1][0] if i + 1 < len(doc_marks) else len(corpus)
            spans.append((doc, end, nxt))
    # 2) Pages dans chaque document (les deux formats)
    for doc, start, end in spans:
        block = corpus[start:end]
        pages = [(m.start(), int(m.group(1)), m.end())
                 for m in _PAGE_HEADER_RE.finditer(block)]
        pages += [(m.start(), int(m.group(1)), m.end())
                  for m in _PAGE_HEADER_FS_RE.finditer(block)]
        pages.sort()
        doc_idx = index.setdefault(doc, {})
        if not pages:
            doc_idx[0] = (doc_idx.get(0, "") + "\n" + block).strip()
            continue
        for j, (p_pos, pno, p_end) in enumerate(pages):
            nxt = pages[j + 1][0] if j + 1 < len(pages) else len(block)
            doc_idx[pno] = (doc_idx.get(pno, "") + "\n" + block[p_end:nxt]).strip()
    return index


def _lookup_page_text(index: Dict[str, Dict[int, str]], source_doc: Optional[str],
                      source_page: Optional[int]) -> Optional[str]:
    """Texte de la page citée. Rapproche le document par nom normalisé (égalité
    puis inclusion). None si page introuvable."""
    if source_page is None:
        return None
    try:
        pno = int(source_page)
    except (TypeError, ValueError):
        return None
    nd = _norm_doc(source_doc)
    candidates = []
    if nd and nd in index:
        candidates.append(index[nd])
    if not candidates and nd:
        for k, v in index.items():
            if k and (nd in k or k in nd):
                candidates.append(v)
    if not candidates:
        candidates = list(index.values())   # dernier recours : un seul doc probable
        if len(candidates) != 1:
            return None
    page_txt = candidates[0].get(pno)
    return page_txt


def per_fact_page_fidelity(value_text: Optional[str], source_doc: Optional[str],
                           source_page: Optional[int],
                           page_index: Dict[str, Dict[int, str]]) -> str:
    """Fidélité PER-PAGE : la valeur figure-t-elle à LA page citée ?
    no_citation / page_unavailable / verbatim_on_page / normalized_on_page /
    not_found_on_cited_page / no_numeric."""
    if not value_text or normalize_number(value_text) is None:
        return FIDELITY_NO_NUMERIC
    if source_page is None:
        return FIDELITY_NO_CITATION
    page_txt = _lookup_page_text(page_index, source_doc, source_page)
    if page_txt is None:
        return FIDELITY_PAGE_UNAVAILABLE
    lvl = check_value_fidelity(value_text, page_txt)
    if lvl == FIDELITY_VERBATIM:
        return FIDELITY_VERBATIM_ON_PAGE
    if lvl == FIDELITY_NORMALIZED:
        return FIDELITY_NORMALIZED_ON_PAGE
    # page connue, valeur absente → mauvaise citation / hallucination de page
    return FIDELITY_NOT_ON_CITED_PAGE


def annotate_facts_per_page(facts: Iterable[Any], corpus: Optional[str]) -> Dict[str, int]:
    """Annote chaque fait (.fidelity_page) et renvoie un récap per-page incluant
    `not_found_on_cited_page` (= valeur absente de la page citée = signal fort)."""
    summary = {FIDELITY_VERBATIM_ON_PAGE: 0, FIDELITY_NORMALIZED_ON_PAGE: 0,
               FIDELITY_NOT_ON_CITED_PAGE: 0, FIDELITY_PAGE_UNAVAILABLE: 0,
               FIDELITY_NO_CITATION: 0, FIDELITY_NO_NUMERIC: 0}
    index = index_corpus_by_page(corpus)
    for f in facts or []:
        # v62.11 — vérifier le token réellement lu sur la page, pas la
        # valeur reformattée pour l'utilisateur (ex. £2,420m vs 2,420).
        val = (getattr(f, "source_value_text", None)
               or (f.get("source_value_text") if isinstance(f, dict) else None)
               or _fact_value(f))
        doc = (getattr(f, "source_doc", None)
               or (f.get("source_doc") if isinstance(f, dict) else None))
        page = (getattr(f, "source_page", None)
                or (f.get("source_page") if isinstance(f, dict) else None))
        try:
            lvl = per_fact_page_fidelity(val, doc, page, index)
        except Exception:
            lvl = FIDELITY_NO_NUMERIC
        try:
            if isinstance(f, dict):
                f["fidelity_page"] = lvl
                if lvl in (FIDELITY_VERBATIM_ON_PAGE, FIDELITY_NORMALIZED_ON_PAGE) and f.get("proof_status") != "CONFLICT":
                    f["proof_status"] = "CONFIRMED_ON_PAGE"
            else:
                setattr(f, "fidelity_page", lvl)
                if lvl in (FIDELITY_VERBATIM_ON_PAGE, FIDELITY_NORMALIZED_ON_PAGE) and getattr(f, "proof_status", "") != "CONFLICT":
                    setattr(f, "proof_status", "CONFIRMED_ON_PAGE")
        except Exception:
            pass
        summary[lvl] = summary.get(lvl, 0) + 1
    return summary


def per_page_summary(table: Any, corpus: Optional[str]) -> Dict[str, int]:
    """Récap per-page sur une table de ledger (.facts / .rows / itérable)."""
    facts = None
    for attr in ("facts", "rows", "items", "entries"):
        cand = getattr(table, attr, None)
        if cand:
            facts = cand
            break
    if facts is None and isinstance(table, (list, tuple)):
        facts = table
    if facts is None:
        return {FIDELITY_VERBATIM_ON_PAGE: 0, FIDELITY_NORMALIZED_ON_PAGE: 0,
                FIDELITY_NOT_ON_CITED_PAGE: 0, FIDELITY_PAGE_UNAVAILABLE: 0,
                FIDELITY_NO_CITATION: 0, FIDELITY_NO_NUMERIC: 0}
    return annotate_facts_per_page(facts, corpus)


def fidelity_signal(level: str, lang: str = "fr",
                    corpus_kind: str = CORPUS_NARRATIVE) -> str:
    """Phrase humaine pour un niveau de fidélité. HONNÊTETÉ : si le corpus
    confronté est la SYNTHÈSE Finance (narrative), on parle de COHÉRENCE, pas de
    fidélité vs source documentaire. Une valeur retrouvée dans le narratif ne
    prouve pas qu'elle figure dans la pièce source originale."""
    is_src = corpus_kind == CORPUS_SOURCE_DOCUMENT
    is_input = corpus_kind == CORPUS_INPUT_CORPUS
    if is_src:
        where_fr, where_en = "la source documentaire", "the source document"
    elif is_input:
        where_fr = "le corpus documentaire fourni aux agents (documents d'entrée)"
        where_en = "the document corpus given to the agents (input documents)"
    else:
        where_fr = "la synthèse Finance (≠ source documentaire originale)"
        where_en = "the Finance synthesis (≠ original source document)"
    fr = {
        FIDELITY_VERBATIM:   f"Valeur cohérente (verbatim) avec {where_fr}.",
        FIDELITY_NORMALIZED: f"Valeur cohérente avec {where_fr} (format normalisé).",
        FIDELITY_NOT_FOUND:  f"Valeur non retrouvée dans {where_fr} — à vérifier "
                             "(corpus possiblement partiel ; pas une preuve d'erreur).",
        FIDELITY_NO_NUMERIC: "Fait qualitatif — pas de valeur numérique à vérifier.",
        FIDELITY_SOURCE_UNAVAILABLE: "Aucun corpus disponible pour vérifier cette "
                             "valeur (fidélité non évaluable).",
        FIDELITY_VERBATIM_ON_PAGE:   "Valeur confirmée à la page citée (verbatim).",
        FIDELITY_NORMALIZED_ON_PAGE: "Valeur confirmée à la page citée (format normalisé).",
        FIDELITY_NOT_ON_CITED_PAGE:  "Valeur ABSENTE de la page citée — citation "
                             "erronée ou hallucination de source, à vérifier.",
        FIDELITY_PAGE_UNAVAILABLE:   "Page citée non disponible dans le corpus — "
                             "fidélité per-page non évaluable.",
        FIDELITY_NO_CITATION:        "Aucune page citée — fidélité per-page non applicable.",
    }
    en = {
        FIDELITY_VERBATIM:   f"Value consistent (verbatim) with {where_en}.",
        FIDELITY_NORMALIZED: f"Value consistent with {where_en} (normalized format).",
        FIDELITY_NOT_FOUND:  f"Value not found in {where_en} — to verify "
                             "(corpus may be partial; not proof of error).",
        FIDELITY_NO_NUMERIC: "Qualitative fact — no numeric value to verify.",
        FIDELITY_SOURCE_UNAVAILABLE: "No corpus available to verify this value "
                             "(fidelity not assessable).",
        FIDELITY_VERBATIM_ON_PAGE:   "Value confirmed on the cited page (verbatim).",
        FIDELITY_NORMALIZED_ON_PAGE: "Value confirmed on the cited page (normalized).",
        FIDELITY_NOT_ON_CITED_PAGE:  "Value ABSENT from the cited page — wrong "
                             "citation or source hallucination, to verify.",
        FIDELITY_PAGE_UNAVAILABLE:   "Cited page unavailable in corpus — per-page "
                             "fidelity not assessable.",
        FIDELITY_NO_CITATION:        "No cited page — per-page fidelity not applicable.",
    }
    return (fr if lang == "fr" else en).get(level, "")


def is_evidence_weak(per_page) -> bool:
    """F.6.10 (audit dossier réseau de soins F.6.9) — GARDE DE PREUVE.

    Renvoie True quand la fidélité per-page est trop faible pour afficher « OK » :
    soit AUCUNE valeur confirmée à la page citée, soit ≥ 50 % des faits sont sans
    citation / page indisponible / absents de la page citée. Sert à basculer le
    badge Couche 1 en DEGRADED — pour ne pas tromper l'utilisateur (consultant /
    DAF de transition) avec un « OK » rassurant sur une preuve fragile.
    """
    if not isinstance(per_page, dict) or not per_page:
        return False
    conf = (per_page.get(FIDELITY_VERBATIM_ON_PAGE, 0)
            + per_page.get(FIDELITY_NORMALIZED_ON_PAGE, 0))
    weak = (per_page.get(FIDELITY_PAGE_UNAVAILABLE, 0)
            + per_page.get(FIDELITY_NO_CITATION, 0)
            + per_page.get(FIDELITY_NOT_ON_CITED_PAGE, 0))
    tot = conf + weak
    if tot <= 0:
        return False
    return conf == 0 or (weak / tot) >= 0.5
