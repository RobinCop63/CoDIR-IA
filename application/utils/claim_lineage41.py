"""v62.13.9.4.41 — FILIATION DES CLAIMS ET INVALIDATION DES DESCENDANTS.

Contre-audit du 23/09/2026, dossier américain. Un agent a écrit que « les documents
source mentionnent une marge brute de 31 % » pour un segment. Le chiffre existe bien dans
le 10-K — « Consolidated net income increased $21.4 million, or 31%, for fiscal year
2025 » — mais il porte une **croissance du résultat net**, pas une marge brute. Le produit
a accepté la claim parce que le nombre était présent dans le corpus, sans vérifier que la
GRANDEUR correspondait. Puis il en a tiré un écart non résolu, un risque de dilution, une
question au conseil, un arbitrage du dirigeant et une action datée du directeur financier.
Le garde des scénarios a retenu quelques phrases ; l'action et la question, elles, ont
survécu avec le chiffre. Un faux fait retiré qui laisse vivre ses conséquences n'est pas
retiré.

Deux mécanismes, tous deux généraux :

1. ``unsupported_document_claims`` — une phrase qui attribue un chiffre AUX PIÈCES pour
   une grandeur donnée doit être confirmable pour CETTE grandeur. La confirmation est
   fournie par l'appelant (couche de preuve) ; ce module ne connaît aucun dossier.
2. ``invalidate_descendants`` — quand un couple (valeur, grandeur) est invalidé, toute
   phrase du livrable qui le reprend est retirée avec son motif, où qu'elle se trouve :
   risque, question, arbitrage, action, conclusion.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterable, List, Sequence, Tuple

__all__ = [
    "METRIC_TERMS",
    "metric_keys_in",
    "iter_value_claims",
    "build_page_metric_index",
    "build_fact_index42",
    "confirm42",
    "unsupported_document_claims",
    "invalidate_descendants",
]

# Vocabulaire de grandeurs — général, aucun nom de société, aucune valeur de dossier.
METRIC_TERMS = {
    "GROSS_MARGIN": r"marges?\s+brutes?|gross\s+margins?",
    "OPERATING_MARGIN": r"marges?\s+op[ée]rationnelles?|marges?\s+d'exploitation|operating\s+margins?",
    "NET_MARGIN": r"marges?\s+nettes?|net\s+margins?",
    "REVENUE": r"chiffres?\s+d['’]affaires|revenues?\b|revenus?\b|net\s+sales|turnover|\bsales\b|ventes\s+nettes",
    "NET_INCOME": r"r[ée]sultats?\s+nets?|net\s+incomes?|net\s+profits?",
    "GROWTH": r"croissances?|growth|increased|augmentation|progression",
    "EBITDA": r"\bEBITDA\b",
    "HEADCOUNT": r"effectifs?|headcounts?|salari[ée]s?",
    "NET_DEBT": r"dettes?\s+nettes?|net\s+debt",
    "INVENTORIES": r"stocks?\b|inventor(?:y|ies)",
    "CASH": r"tr[ée]sorerie|cash\s+and\s+cash\s+equivalents",
    "CAPEX": r"investissements?|capital\s+expenditures?|capex",
}
_METRIC_RES = {k: re.compile(v, re.IGNORECASE) for k, v in METRIC_TERMS.items()}

# « les pièces disent que… » : une attribution explicite aux documents fournis.
_DOC_ATTRIBUTION = re.compile(
    r"source\s+documents?|les\s+pi[èe]ces|les\s+documents|d'apr[èe]s\s+(?:les|le)\s+"
    r"(?:comptes|rapport|document)|per\s+the\s+(?:10-[KQ]|annual\s+report|filing)|"
    r"dans\s+le\s+(?:10-[KQ]|rapport\s+annuel)|reported\s+in|disclosed\s+in|"
    r"referenced?\s+(?:in|a)\b|selon\s+les\s+(?:pi[èe]ces|documents)",
    re.IGNORECASE)

# Un identifiant n'est pas une valeur : « 10-K », « 8-K », « FY2025 », une année nue ou un
# numéro de section ne se confirment pas et n'invalident rien.
_VALUE = re.compile(
    r"(?<![\w.,\-])(-?\d{1,3}(?:[\s\u00a0\u202f]\d{3})+(?:[.,]\d+)?|-?\d+(?:[.,]\d+)?)"
    r"(?!\d)(?!-[A-Za-z])\s*"
    r"(%|‰|bps|pts?|k€|M€|Md€|€|\$|£|M\$|k\$|millions?|milliards?|billions?|thousands?)?",
    re.IGNORECASE)
_YEAR_ONLY = re.compile(r"^(?:19|20)\d{2}$")


def _is_value_token(raw: str, unit: str | None) -> bool:
    t = str(raw or "").strip()
    if _YEAR_ONLY.match(t) and not (unit or "").strip():
        return False
    return True

_SENTENCE = re.compile(r"[^\n]+")


def _norm_value(raw: str) -> str:
    """Forme comparable d'un nombre, indépendante des séparateurs."""
    t = str(raw or "").strip()
    if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?", t):
        t = t.replace(",", "")
    else:
        t = re.sub(r"[\s\u00a0\u202f]", "", t).replace(",", ".")
    try:
        f = float(t)
    except ValueError:
        return ""
    return f"{f:.6g}"


def _metric_spans41(line: str) -> List[Tuple[int, int, str]]:
    """Positions des grandeurs nommées dans une ligne, avec leur clé."""
    out: List[Tuple[int, int, str]] = []
    for k, rx in _METRIC_RES.items():
        for m in rx.finditer(str(line or "")):
            out.append((m.start(), m.end(), k))
    return sorted(out)


def _pairs_in_line41(line: str) -> List[Tuple[str, str]]:
    """v62.13.9.4.41b — CHAQUE VALEUR VA À SA GRANDEUR, PAS À TOUTES.

    Contre-audit du 24/09/2026 : « Gross margin 45%; net income growth 17%. » indexait
    le produit croisé des deux nombres par les trois grandeurs de la ligne, si bien
    qu'une marge brute de 17 % se trouvait « confirmée » par la croissance du résultat
    net. Une valeur est rattachée à la grandeur nommée qui la PRÉCÈDE immédiatement,
    sans franchir une ponctuation forte ; à défaut, elle n'est rattachée à rien.
    """
    line = str(line or "")
    spans = _metric_spans41(line)
    if not spans:
        return []
    out: List[Tuple[str, str]] = []
    _sep = re.compile(r"[;•|]|\.\s|\s[–—-]\s")
    for m in _VALUE.finditer(line):
        if not _is_value_token(m.group(1), m.group(2)):
            continue
        n = _norm_value(m.group(1))
        if not n:
            continue
        # v62.13.9.4.41b — la grandeur peut précéder OU suivre sa valeur : « marge brute
        # de 45 % » et « a 31% gross margin » sont la même construction, écrite dans les
        # deux ordres. On retient la plus proche, sans franchir une ponctuation forte.
        cands = []
        for start, end, key in spans:
            if end <= m.start() and not _sep.search(line[end:m.start()]):
                cands.append((m.start() - end, key))
            elif start >= m.end() and not _sep.search(line[m.end():start]):
                cands.append((start - m.end(), key))
        if not cands:
            continue
        best = min(c[0] for c in cands)
        for dist, key in cands:
            if dist == best:
                out.append((n, key))
    return out


def metric_keys_in(text: str) -> List[str]:
    """Grandeurs nommées dans un fragment de texte."""
    return [k for k, rx in _METRIC_RES.items() if rx.search(str(text or ""))]


def iter_value_claims(text: str) -> Iterable[Tuple[str, str, List[str]]]:
    """Produit (phrase, valeur normalisée, grandeur(s) réellement associée(s))."""
    for m in _SENTENCE.finditer(str(text or "")):
        line = m.group(0)
        pairs = _pairs_in_line41(line)
        seen = set()
        for n, k in pairs:
            if (n, k) in seen:
                continue
            seen.add((n, k))
            yield line, n, [k]
        # v62.13.9.4.41b — une valeur qu'on n'a pas su rattacher n'est pas une valeur
        # sans grandeur : c'est une association AMBIGUË. Une claim ambiguë se vérifie
        # contre toutes les grandeurs nommées, elle ne se dispense pas de contrôle.
        keys = metric_keys_in(line)
        if keys:
            attached = {n for n, _k in pairs}
            for v in _VALUE.finditer(line):
                if not _is_value_token(v.group(1), v.group(2)):
                    continue
                n = _norm_value(v.group(1))
                if n and n not in attached:
                    yield line, n, list(keys)


def unsupported_document_claims(
    text: str,
    confirm: Callable[[str, str], bool],
) -> List[Tuple[str, str, List[str]]]:
    """Phrases qui attribuent un chiffre aux pièces sans que la grandeur soit confirmée.

    ``confirm(value, metric_key)`` est fourni par l'appelant — en production, la couche de
    preuve : elle répond vrai si une page porte cette valeur AVEC cette grandeur. Une
    valeur présente dans le corpus mais rattachée à une autre grandeur ne confirme rien.
    """
    out: List[Tuple[str, str, List[str]]] = []
    for line, value, keys in iter_value_claims(text):
        if not _DOC_ATTRIBUTION.search(line):
            continue
        if _NEGATED_CLAIM41.search(line):
            continue                       # une assertion niée n'affirme pas une valeur
        m = _PERIOD_IN_TEXT41.search(line)
        period = _period_norm41(m.group(1) or m.group(2)) if m else ""
        # devise et échelle écrites à côté de la valeur : « £450m », « 450 M€ », « GBP 450m »
        _vm = re.search(r"(?:([£€$]|GBP|EUR|USD)\s*)?" + re.escape(str(value)) + r"\s*(k|m|bn|md|thousand|million|billion|milliers|millions|milliards)?\b", line, re.I)
        ccy = _CCY_HINT41.get((_vm.group(1) or "").lower(), "") if _vm else ""
        sc = _SCALE_HINT41.get((_vm.group(2) or "").lower(), "") if _vm else ""
        _sm = re.search(r"\b(consolidated|group|groupe|consolid[ée]s?|company|soci[ée]t[ée]|parent|statutory)\b", line, re.I)
        scope = ("CONSOLIDATED" if _sm and _sm.group(1).lower() in ("consolidated", "group", "groupe", "consolidé", "consolidés")
                 else "SOCIAL" if _sm else "")
        try:
            ok = any(confirm(value, k, period, ccy, sc, scope) for k in keys)
        except TypeError:
            try:
                ok = any(confirm(value, k, period) for k in keys)
            except TypeError:
                ok = any(confirm(value, k) for k in keys)
        if ok:
            continue
        out.append((line, value, keys))
    return out


def build_page_metric_index(pages) -> set:
    """Index des couples (valeur, grandeur) réellement portés par les pages du corpus.

    Une valeur ne confirme que la grandeur nommée SUR SA LIGNE. C'est ce qui distingue
    « 31 % » porté par une croissance de résultat net d'une marge brute de 31 % : le même
    nombre, une autre grandeur, donc aucune confirmation pour la seconde.
    """
    idx: set = set()
    for page in pages or []:
        text = getattr(page, "text", None)
        if text is None and isinstance(page, dict):
            text = page.get("text")
        for line in str(text or "").split("\n"):
            for n, k in _pairs_in_line41(line):
                idx.add((n, k))
    return idx


# v62.13.9.4.41b — CONSÉQUENCE IMPLICITE. Contre-audit du 24/09/2026 : « Therefore
# appoint the CFO to investigate this margin discrepancy » survivait au retrait du
# chiffre parce qu'elle ne le répétait pas. Une phrase qui désigne la grandeur invalidée
# par un démonstratif — « cet écart », « this margin » — est une conséquence, pas un
# énoncé indépendant. Le démonstratif doit être ACCOLÉ à la grandeur : une phrase qui
# parle de la même grandeur sans y renvoyer reste intacte. C'est un indice de langue,
# pas la filiation par dépendance déclarée : celle-ci reste à construire, et les notes
# publiques doivent le dire ainsi.
_DEICTIC41 = re.compile(
    r"\b(?:this|that|these|those|such|said|the\s+above|ce|cet|cette|ces|ledit|ladite|"
    r"celui|celle|susdit)\b", re.IGNORECASE)
_DEICTIC_WINDOW41 = 48


# Mots par lesquels une conséquence désigne le constat dont elle découle, sans le citer.
_GAP_WORD41 = re.compile(
    r"\b(?:[ée]carts?|discrepanc(?:y|ies)|anomal(?:y|ies|ie|ies)|gaps?|incoh[ée]rences?|"
    r"figures?|chiffres?|points?\s+d['’]attention)\b", re.IGNORECASE)
# Tête de grandeur : « this margin » renvoie à la marge brute invalidée sans la nommer
# en entier. Ce raccourci ne sert QUE pour la détection d'anaphore, jamais pour l'index :
# là, une correspondance approximative fabriquerait de fausses confirmations.
_METRIC_HEAD41 = {
    "GROSS_MARGIN": r"marges?|margins?", "OPERATING_MARGIN": r"marges?|margins?",
    "NET_MARGIN": r"marges?|margins?", "REVENUE": r"chiffres?\s+d['’]affaires|revenues?|sales|ventes",
    "NET_INCOME": r"r[ée]sultats?|incomes?|earnings|profits?", "GROWTH": r"croissances?|growths?",
    "EBITDA": r"ebitda", "HEADCOUNT": r"effectifs?|headcounts?", "NET_DEBT": r"dettes?|debt",
    "INVENTORIES": r"stocks?|inventor(?:y|ies)", "CASH": r"tr[ée]soreries?|cash",
    "CAPEX": r"investissements?|capex",
}
_METRIC_HEAD_RES41 = {k: re.compile(v, re.IGNORECASE) for k, v in _METRIC_HEAD41.items()}


def _is_implicit_consequence41(line: str, metrics: Sequence[str]) -> bool:
    """Une phrase qui DÉSIGNE le constat invalidé sans le citer en est une conséquence.

    Le démonstratif doit être accolé à la grandeur ou au mot qui désigne le constat
    (« cet écart », « this margin discrepancy ») : une phrase qui parle de la même
    grandeur sans y renvoyer reste intacte, et c'est ce que vérifient les contre-épreuves
    de sur-correction.
    """
    for m in _DEICTIC41.finditer(str(line or "")):
        # v62.13.9.4.43 — « report THAT revenue did not… » : ici « that » est une
        # conjonction, pas un démonstratif. Après un verbe de rapport, on ne le lit pas
        # comme un renvoi ; sinon une assertion niée passerait pour une conséquence.
        if m.group(0).lower() == "that" and re.search(
                r"\b(?:report|reports|reported|state|states|stated|indicate|indicates|indicated|"
                r"show|shows|showed|note|notes|noted|confirm|confirms|confirmed|say|says|said|"
                r"mean|means|suggest|suggests|believe|believes|conclude|concludes)\s*$",
                line[:m.start()], re.IGNORECASE):
            continue
        tail = line[m.end():m.end() + _DEICTIC_WINDOW41]
        if _GAP_WORD41.search(tail):
            return True
        for key in metrics:
            rx = _METRIC_HEAD_RES41.get(str(key).upper())
            if rx and rx.search(tail):
                return True
    return False


# v62.13.9.4.43 — L'INDEX DE PREUVE EST CELUI DES FAITS QUALIFIÉS, PAS DES NOMBRES D'UNE
# PAGE. Contre-audit du 25/09/2026 : un couple (nombre, grandeur) lu dans le texte brut
# confirmait une assertion quelle que soit sa période, sa nature ou son signe — une
# prévision confirmait un réalisé, un chiffre FY2024 confirmait FY2025. L'index se
# construit désormais sur la table de faits validée par le contrat commun : chaque
# entrée porte période, nature et périmètre, et une assertion n'est confirmée que par un
# fait de même valeur, même grandeur, même période quand elle en donne une, et de nature
# réalisée. Une assertion NIÉE n'affirme pas une valeur : elle n'est ni confirmée ni
# invalidée par ce chemin.
_PERIOD_IN_TEXT41 = re.compile(r"\bFY\s?(\d{2,4})\b|\b((?:19|20)\d{2})\b", re.IGNORECASE)
_NEGATED_CLAIM41 = re.compile(
    r"\b(?:did\s+not|does\s+not|do\s+not|not|never|n['’]a\s+pas|n['’]ont\s+pas|ne\s+\w+\s+pas|"
    r"aucun|aucune|jamais|below|under|inférieur|moins\s+de|less\s+than)\b", re.IGNORECASE)


def _period_norm41(tok: str) -> str:
    d = re.sub(r"\D", "", str(tok or ""))
    if len(d) == 2:
        d = "20" + d
    return f"FY{d}" if len(d) == 4 else ""


def build_fact_index42(facts) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    """Index (valeur, grandeur) → faits qualifiés, avec leurs dimensions."""
    idx: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for f in facts or []:
        try:
            status = str(getattr(f, "status", "") or "")
            proof = str(getattr(f, "proof_status", "") or "")
            qualified = ("FAIT" in status) and proof == "CONFIRMED_ON_PAGE"
            nature = str(getattr(f, "nature", "") or "").upper()
            keys = metric_keys_in(str(getattr(f, "label", "") or "") + " " +
                                  str(getattr(f, "metric_canonical_id", "") or "").replace("_", " "))
            nv = getattr(f, "normalized_value", None)
            # v62.13.9.4.44 (M2-01) — les DIMENSIONS font partie de l'identité du fait : la
            # valeur est indexée à son échelle propre et à son échelle affichée, jamais à
            # toutes les échelles ; devise, échelle et périmètre sont portés par l'entrée
            # et opposés à l'assertion quand elle les précise.
            vals = {}
            if nv is not None:
                n = _norm_value(str(float(nv)))
                if n:
                    vals[n] = ""
            raw_txt = str(getattr(f, "source_value_text", "") or getattr(f, "value", "") or "")
            raw = _norm_value(re.sub(r"[^\d.,\-]", "", raw_txt))
            if raw:
                vals[raw] = str(getattr(f, "scale", "") or "").lower()
            ccy = str(getattr(f, "currency", "") or "").upper()
            for v, sc in vals.items():
                for k in keys:
                    idx.setdefault((v, k), []).append({
                        "period": str(getattr(f, "period", "") or ""),
                        "nature": nature, "qualified": qualified,
                        "scope": str(getattr(f, "scope", "") or "").upper(),
                        "currency": ccy, "scale": sc,
                        "prospective": nature in ("PROSPECTIVE", "VARIATION"),
                    })
        except Exception:
            continue
    return idx


_CCY_HINT41 = {"£": "GBP", "€": "EUR", "$": "USD", "gbp": "GBP", "eur": "EUR", "usd": "USD"}
_SCALE_HINT41 = {"k": "k", "m": "m", "bn": "bn", "md": "bn", "thousand": "k", "million": "m", "billion": "bn",
                 "milliers": "k", "millions": "m", "milliards": "bn"}


def confirm42(idx, value: str, metric: str, period: str = "", currency: str = "", scale: str = "", scope: str = "") -> bool:
    """Vrai seulement si un fait QUALIFIÉ, RÉALISÉ, de même valeur et grandeur — et de même
    période, devise, échelle et périmètre quand l'assertion les donne — existe."""
    for e in idx.get((str(value), str(metric).upper()), []):
        if not e["qualified"] or e["prospective"]:
            continue
        if period and e["period"] and e["period"] != period:
            continue
        if currency and e.get("currency") and e["currency"] != currency.upper():
            continue
        if scale and e.get("scale") and e["scale"] != scale.lower():
            continue
        if scope and e.get("scope") and e["scope"] != scope.upper():
            continue
        return True
    return False


def invalidate_descendants(
    text: str,
    invalid: Sequence[Tuple[str, str]],
    lang: str = "fr",
    marker: str | None = None,
) -> Tuple[str, List[str]]:
    """Retire du texte livré toute phrase qui reprend un couple (valeur, grandeur) invalidé.

    Retourne le texte assaini et la liste des phrases retirées. Le marqueur laissé en place
    dit ce qui a été retiré et pourquoi : une suppression muette serait, elle aussi, une
    perte d'information.
    """
    if not text or not invalid:
        return str(text or ""), []
    wanted = {(_norm_value(v), str(k or "").upper()) for v, k in invalid}
    wanted = {(v, k) for v, k in wanted if v}
    if not wanted:
        return str(text), []
    # 9.4.53 — contre-recette ChatGPT du 06/10/2026 (G01, bloquant de doctrine) : la ligne entière était REMPLACÉE par
    # « [retiré — chiffre non confirmé pour cette grandeur ; voir le registre] ». Doctrine du 28/09 : rien n'est retiré,
    # tout passage douteux est livré et SIGNALÉ en place. La ligne reste, suivie du motif ; « removed » liste désormais
    # les lignes signalées (même périmètre qu'avant, pour la traçabilité).
    msg = marker or (
        " ⚠ à vérifier — chiffre non confirmé pour cette grandeur (voir le registre)"
        if str(lang).lower().startswith("fr")
        else " ⚠ to verify — figure not confirmed for this metric (see the register)")
    removed: List[str] = []
    out_lines: List[str] = []
    _last_removed_in_block = False
    for line in str(text).split("\n"):
        if line.strip().startswith("#"):
            _last_removed_in_block = False
        keys = set(metric_keys_in(line))
        hit = False
        if keys:
            for v in _VALUE.finditer(line):
                if not _is_value_token(v.group(1), v.group(2)):
                    continue
                n = _norm_value(v.group(1))
                if n and any((n, k) in wanted for k in keys):
                    hit = True
                    break
        if not hit:
            hit = _is_implicit_consequence41(line, [k for _v, k in wanted])
        # v62.13.9.4.43 — CONSÉQUENCE PAR PROXIMITÉ. Dans le même bloc qu'une ligne
        # retirée, une ligne qui nomme la grandeur ou le mot d'écart SANS porter de
        # chiffre propre en est une conséquence, même sans démonstratif (« Appoint the
        # CFO to investigate the margin gap »). Une ligne qui porte son propre chiffre est
        # jugée sur son chiffre : c'est ce qui préserve une recommandation fondée à part.
        # Le critère de proximité est le MOT D'ÉCART (gap, écart, anomalie, discrepancy),
        # pas la grandeur seule : « la marge brute du segment reste à documenter » nomme
        # la grandeur sans renvoyer au constat, et doit survivre (témoin du 24/09).
        # v62.13.9.4.44 (M2-03) — une date, une année ou une échéance n'est pas un chiffre
        # propre : « by 2026-12-15 » ne rend pas la conséquence indépendante.
        _own_figure = any(_is_value_token(v.group(1), v.group(2)) and not re.search(
            r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{2,4}", line[max(0, v.start() - 1):v.end() + 8])
            for v in _VALUE.finditer(line))
        if not hit and _last_removed_in_block and not _own_figure:
            if _GAP_WORD41.search(line):
                hit = True
        if not line.strip():
            _last_removed_in_block = False
        if hit:
            _last_removed_in_block = True
            removed.append(line.strip())
            out_lines.append(line.rstrip() + ("" if msg.strip() in line else msg))
        else:
            out_lines.append(line)
    return "\n".join(out_lines), removed
