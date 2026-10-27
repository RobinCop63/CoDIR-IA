"""v62.13.9.4.10 — liaison probatoire structurée ligne ↔ claims canoniques.

Refonte complète (contre-audit 30/08/2026, P1-948-03). Un claim ne supporte
une ligne que si TOUTES les dimensions déterminables concordent :

- **statut de preuve en liste fermée exacte** — seuls les statuts réellement
  émis par le proof layer supportent (plus de préfixes) ;
- **valeur absolue exacte** — décimale parsée (« 15,0 » = 15.0 ≠ 150 ;
  « 2,420 » = 2 420), facteur d'échelle appliqué (k/M/bn/Md), la comparaison
  porte sur la grandeur absolue : 15 M€ ≠ 15 k€ ;
- **devise** — EUR/GBP/USD déterminées des deux côtés doivent être égales ;
- **métrique** — le label du claim doit recouvrir la tête (avant « : ») ou le
  voisinage du nombre ; un montant en devise ne s'auto-suffit jamais ;
- **période** — deux périodes déterminées et différentes ⇒ pas de support ;
  une ligne datée qu'un claim non daté ne certifie pas ⇒ pas de support ;
- **entité/périmètre** — France ≠ Group(e) ; une ligne périmétrée qu'un
  claim sans périmètre ne certifie pas ⇒ pas de support ;
- **unité lexicale** (contrat 9.4.7 conservé) — « 24 mois » ne supporte
  jamais « 24 centres » ;
- une ligne prospective n'est JAMAIS supportée (un fait ne prouve pas une
  cible) ; tout parse indéterminable est fail-closed.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from utils import editorial_quantity as _EQ

# ── Statuts de preuve : listes fermées exactes (inventaire du proof layer) ──
_ALLOWED_PROOF_STATUS = frozenset({
    "CONFIRMED_ON_PAGE",
    "DERIVED_FROM_CONFIRMED_ON_PAGE",
    # v62.13.9.4.50 — faits externes : dépôt réglementaire (10-K, comptes iXBRL) et registre (Pappers). Provenance
    # exigée : la pièce publique (dépôt et date) — jamais un statut auto-déclaré
    "CONFIRMED_IN_FILING",
    "CONFIRMED_IN_REGISTRY",
})
_ALLOWED_CLAIM_TYPE = frozenset({"FACT", "DERIVED"})

_TOKEN_RE = re.compile(r"[a-zà-öø-ÿ]{4,}", re.I)
_TOKEN_STOP = {
    "dans", "pour", "avec", "sans", "sous", "vers", "chez", "cette", "leurs",
    "notre", "votre", "elles", "sont", "être", "etre", "avoir", "plus",
    "moins", "très", "tres", "tout", "tous", "toute", "toutes", "actuel",
    "actuelle", "current", "with", "without", "from", "into", "over",
    "under", "this", "that", "these", "those", "their", "there", "have",
    "been", "were", "will", "would", "should", "société", "societe",
    "company", "total", "montant", "amount", "valeur", "value", "chiffre",
    "figure", "donnée", "donnee", "data", "adjusted", "ajusté", "ajuste",
}
_METRIC_STOP = {"actuel", "actuelle", "actuels", "actuelles", "current",
                "total", "totale", "the", "les", "des"}

# v62.13.9.4.10 — têtes GÉNÉRIQUES de métrique : partagées par des métriques
# différentes, elles ne discriminent rien. « Operating margin » et « Gross
# margin » partagent « margin » — l'intersection non vide de la 9.4.9
# suffisait à les lier. Désormais, si les deux côtés portent un qualificatif
# discriminant, ces qualificatifs doivent se recouper.
_GENERIC_METRIC_HEAD = {
    # v62.13.9.4.50 — mots des ÉTIQUETTES d'agent (« [FAIT] », « [CALCUL] », « [CIBLE BRIEF] ») : ils ne discriminent
    # aucune métrique (tri du vrai CR du 30/09 : « [FAIT] Trésorerie : 58,1 M$ » n'était plus rattachée à son claim)
    "fait", "faits", "fact", "facts", "calcul", "estim", "hypothese", "hypothèse", "recommande", "recommandé",
    "cible", "brief", "derived",
    "margin", "marge", "marges", "revenue", "revenues", "profit", "profits",
    "resultat", "résultat", "résultats", "chiffre", "affaires", "sales",
    "income", "turnover", "cost", "costs", "charge", "charges",
    "change", "changed", "growth", "croissance", "variation", "evolution",
    "évolution", "increase", "decrease", "reported", "montant", "amount",
    # v62.13.9.4.11 — têtes génériques supplémentaires relevées au corpus
    # aveugle : « gross debt » vs « net debt », « free cash flow » vs
    # « operating cash flow » partagent leur tête et se liaient entre elles.
    "debt", "dette", "dettes", "cash", "flow", "flows", "tresorerie",
    "trésorerie", "ebitda", "ebit", "capex", "opex", "inventory",
    "inventories", "stocks", "headcount", "effectif", "effectifs",
    "budget", "budgets", "investment", "investments", "investissement",
    "investissements", "provision", "provisions",
}

_CUR_MAP = {"€": "EUR", "EUR": "EUR", "£": "GBP", "GBP": "GBP",
            "$": "USD", "USD": "USD"}
_SCALE_MAP = {"k": 1e3, "m": 1e6, "bn": 1e9, "md": 1e9, "b": 1e9}

_AMOUNT_RE = re.compile(
    r"(?P<cur1>[€£$])?\s*"
    r"(?P<num>\d(?:[\d\s\u00A0\u202F.,]*\d)?)\s*"
    r"(?P<scale>k€|M€|Md€|k\$|M\$|k£|M£|k|K|m|M|bn|Bn|BN|Md|md|B)?\s*"
    r"(?P<cur2>€|£|\$|EUR|GBP|USD)?"
    r"(?P<pct>\s*(?:%|pp\b))?", re.I)

_PERIOD_RE = re.compile(
    r"\b(?P<tag>FY|H[12]|S[12]|[QT][1-4])?\s*(?P<year>(?:19|20)\d{2})\b", re.I)

_SCOPE_TOKENS = {
    "france", "group", "groupe", "holding", "consolidated", "consolidé",
    "consolide", "social", "standalone", "filiale", "subsidiary", "uk",
    "spain", "germany", "italy", "usa", "europe", "emea", "apac",
    "americas", "worldwide", "monde",
}
_SCOPE_ALIASES = {"consolidé": "consolidated", "consolide": "consolidated",
                  "groupe": "group", "monde": "worldwide"}


def _parse_decimal(num: str) -> float | None:
    """« 15,0 » → 15.0 ; « 2,420 » → 2420 ; « 2,420.5 » → 2420.5 ;
    « 1 234 » → 1234. Un séparateur suivi d'exactement trois chiffres en
    groupes réguliers est un séparateur de milliers ; sinon il est décimal.
    Indéterminable ⇒ None (fail-closed)."""
    s = re.sub(r"[\s\u00A0\u202F]", "", str(num or ""))
    if not s or not re.fullmatch(r"[\d.,]+", s):
        return None
    seps = set(re.findall(r"[.,]", s))
    try:
        if not seps:
            return float(s)
        if len(seps) == 2:
            last = max(s.rfind("."), s.rfind(","))
            dec_sep = s[last]
            thou = "," if dec_sep == "." else "."
            return float(s.replace(thou, "").replace(dec_sep, "."))
        sep = seps.pop()
        parts = s.split(sep)
        if len(parts[0]) in (1, 2, 3) and all(len(p) == 3 for p in parts[1:]):
            return float("".join(parts))
        if len(parts) == 2:
            return float(parts[0] + "." + parts[1])
        return None
    except ValueError:
        return None


def _amounts(text: str, *, mask: bool = True) -> list[dict]:
    """Montants structurés : valeur absolue (échelle appliquée), devise, %."""
    src = str(text or "")
    scan = _EQ.mask_exempt(src) if mask else src
    # les positions retournées réfèrent TOUJOURS à ``scan`` — le masquage ne
    # préserve pas les longueurs, tout découpage doit se faire sur scan
    out: list[dict] = []
    for m in _AMOUNT_RE.finditer(scan):
        base = _parse_decimal(scan[m.start("num"):m.end("num")])
        if base is None:
            continue
        scale_raw = (m.group("scale") or "").lower()
        cur = m.group("cur1") or m.group("cur2") or ""
        if scale_raw in ("k€", "m€", "md€"):
            cur, scale_raw = "€", scale_raw[:-1]
        elif scale_raw in ("k$", "m$"):
            cur, scale_raw = "$", scale_raw[:-1]
        elif scale_raw in ("k£", "m£"):
            cur, scale_raw = "£", scale_raw[:-1]
        scale = _SCALE_MAP.get(scale_raw, 1.0)
        # v62.13.9.4.50 — PRÉCISION AFFICHÉE et VIRGULE DÉCIMALE (contre-recette du 30/09 : « 341,3 M$ » et
        # « 79,871 M$ », faits confirmés présentés arrondis ou à la française, n'étaient rattachés à aucun claim) :
        # tolérance d'une demi-unité du dernier chiffre affiché ; « 79,871 M » a aussi sa lecture décimale.
        _raw50 = scan[m.start("num"):m.end("num")]
        _dec50 = re.search(r"[.,](\d+)$", _raw50)
        _decimals50 = len(_dec50.group(1)) if _dec50 and not re.fullmatch(r"\d{1,3}(?:[ ,.]\d{3})+", _raw50) else 0
        _alt50 = None
        if scale > 1.0 and re.fullmatch(r"\d{1,3},\d{3}", _raw50):
            try:
                _alt50 = float(_raw50.replace(",", ".")) * scale
            except ValueError:
                _alt50 = None
        out.append({
            "tol": 0.5 * (10 ** (-_decimals50)) * scale if scale > 1.0 else 0.0,
            "alt_abs": _alt50,
            "abs": base * scale,
            "raw_int": re.sub(r"[^\d]", "", scan[m.start("num"):m.end("num")]).lstrip("0") or "0",
            "currency": _CUR_MAP.get(cur.upper() if len(cur) > 1 else cur),
            "pct": bool(m.group("pct")),
            "start": m.start(), "end": m.end(),
        })
    return out


def _periods(text: str) -> set[tuple[str | None, int]]:
    out: set[tuple[str | None, int]] = set()
    for m in _PERIOD_RE.finditer(str(text or "")):
        tag = (m.group("tag") or "").upper() or None
        out.add((tag, int(m.group("year"))))
    return out


def _periods_compatible(line_p: set, claim_p: set) -> bool:
    """La ligne datée exige un claim qui certifie la période."""
    if not line_p:
        return True
    if not claim_p:
        return False
    for tag_l, y_l in line_p:
        for tag_c, y_c in claim_p:
            if y_l == y_c and (tag_l is None or tag_c is None or tag_l == tag_c):
                return True
    return False


# v62.13.9.4.10 — ENTITÉ NOMMÉE. Le périmètre (France, Group) ne distingue
# pas deux sociétés : « dossier réseau de soins France » et « dossier industriel France » partagent leur
# périmètre et n'ont rien à voir. On compare donc les noms propres, périmètre
# et vocabulaire financier retirés. La règle ne rejette que si les DEUX
# côtés nomment une entité et qu'elles diffèrent — un claim sans nom propre
# reste utilisable.
_CAP_TOKEN_RE = re.compile(r"\b([A-ZÀ-Ý][\wÀ-ÿ'\u2019-]{2,})")
_ENTITY_STOP = {
    "revenue", "revenues", "margin", "profit", "sales", "income", "cost",
    "turnover", "inventories", "operating", "gross", "adjusted", "underlying",
    "reported", "total", "group", "groupe", "holding", "consolidated",
    "chiffre", "affaires", "marge", "resultat", "résultat", "effectif",
    "budget", "score", "current", "previous", "fiscal", "year", "half",
    "the", "this", "these", "our", "notre", "nos",
    # v62.13.9.4.11 — l'ouverture aux raisons sociales en capitales
    # (« dossier réseau de soins France ») a fait entrer les TAGS de statut dans les noms
    # d'entité : « [FACT] », « [DERIVED] ». Un tag n'a jamais nommé personne.
    "fact", "facts", "derived", "estimate", "estimated", "confirmed",
    "validated", "hypothesis", "hypothese", "hypothèse", "scenario",
    "scénario", "calcul", "incertain", "ref", "sect", "refsect",
    "target", "cible", "objectif", "goal", "plan", "todo", "wip",
}


def _entities(text: str) -> set[str]:
    out: set[str] = set()
    src = str(text or "")
    # v62.13.9.4.50 — puce et étiquettes d'agent en tête de ligne (« • [FAIT] Trésorerie : … ») retirées AVANT la règle
    # du premier mot : « Trésorerie » y était pris pour un nom propre, et la ligne de base confirmée n'était plus
    # rattachée à son claim (tri du vrai CR du 30/09)
    src = re.sub(r"^\s*(?:[•\-–—*▌✓]\s*)?(?:\[[^\]]{0,40}\]\s*)+", lambda m: " " * len(m.group(0)), src)
    # v62.13.9.4.12.5 — la MAJUSCULE DE DÉBUT DE PHRASE n'est pas un nom
    # propre : « Faiblesse structurelle : … » faisait de « Faiblesse » une
    # entité, incompatible avec le claim, et censurait un fait de registre au
    # run réel du 01/09/2026. On ne garde le premier mot que s'il est suivi
    # d'un autre mot capitalisé — « dossier réseau de soins France », « dossier de conseil » —
    # ce qui préserve les raisons sociales réelles.
    _first = re.match(r"\s*([A-ZÀ-Ý][\wÀ-ÿ'\u2019-]{2,})\s+(\S+)", src)
    if _first and not re.match(r"[A-ZÀ-Ý]", _first.group(2)):
        src = src[:_first.start(1)] + " " * len(_first.group(1)) + src[_first.end(1):]
    # les contenus entre crochets sont de l'appareil de marquage, pas des
    # noms propres : « [FACT] », « [DERIVED FROM FACTS] », « [REF_SECT] ».
    src = re.sub(r"\[[^\]]{0,40}\]", " ", src)
    for m in _CAP_TOKEN_RE.finditer(src):
        w = m.group(1)
        low = w.lower()
        if low in _ENTITY_STOP or low in _SCOPE_TOKENS or low in _SCOPE_ALIASES:
            continue
        if re.fullmatch(r"(?:FY|H[12]|S[12]|[QT][1-4])\d*", w, re.I):
            continue
        # v62.13.9.4.11 — « dossier réseau de soins France » nomme la même entité que
        # « dossier réseau de soins France » : exiger une minuscule laissait passer les
        # raisons sociales en capitales. On écarte désormais les tags et
        # identifiants par leur FORME (crochets, souligné, mot du
        # vocabulaire financier), pas par leur casse.
        if "_" in w:
            continue
        if not any(c.islower() for c in w) and len(w) <= 2:
            continue
        # pas d'exclusion par position : le nom d'entité est très souvent en
        # tête (« dossier réseau de soins France revenue: … »). C'est le vocabulaire financier
        # de _ENTITY_STOP qui écarte « Revenue », « Inventories », etc.
        out.add(low)
    return out


def _entities_compatible(line_e: set, claim_e: set) -> bool:
    """v62.13.9.4.11 — une ligne qui NOMME une entité exige un claim qui
    nomme la même. Auparavant, un claim anonyme certifiait n'importe quelle
    société : c'est la même faute que pour la période et le périmètre, où la
    règle « la ligne datée exige un claim daté » est en vigueur depuis la
    9.4.9."""
    if not line_e:
        return True
    if not claim_e:
        return False
    return bool(line_e & claim_e)


_SOURCE_REF_RE = re.compile(
    r"([\w./~-]+\.(?:pdf|docx?|xlsx?|csv|htm|html))"   # v62.13.9.4.50 — « ~ » des noms courts Windows (« STRATE~1.PDF »)
    r"(?:\s*[—,-]?\s*(?:p\.?|page)\s*(\d+))?", re.I)


def _stated_sources(text: str) -> set[tuple[str, str | None]]:
    out = set()
    for m in _SOURCE_REF_RE.finditer(str(text or "")):
        out.add((m.group(1).lower(), m.group(2)))
    return out


def _sources_compatible(line_src: set, claim_src: set) -> bool:
    """Une ligne qui CITE une pièce et une page exige un claim adossé à la
    même pièce. « wrong_source.pdf p.99 » ne peut pas être certifié par un
    claim rattaché à une autre source (contre-audit du 31/08/2026)."""
    if not line_src:
        return True
    if not claim_src:
        return False
    for doc, page in line_src:
        for cdoc, cpage in claim_src:
            # v62.13.9.4.50 — une ligne qui cite la pièce par son NOM D'USAGE (« 10-K FY2025 p.48 », « rapport annuel ») et
            # un claim adossé au fichier de ce dépôt (« …-25-000067_wdfc-20250831.pdf ») : même pièce si la page concorde
            # ou si le claim n'a pas de page. Un nom de fichier explicite différent reste incompatible (contrat du 31/08).
            _generic50 = bool(re.fullmatch(r"(?i)\s*(?:10-K|10-Q|20-F|40-F|8-K|annual\s+report|rapport\s+annuel|"
                                           r"document\s+d['’]enregistrement(?:\s+universel)?|urd|form\s+10-K)(?:\s+(?:FY)?\s?\d{2,4})?\s*", str(doc or "")))
            # nom court Windows 8.3 (« STRATE~1.PDF ») : même pièce que le fichier dont le nom commence pareil
            _short50 = re.fullmatch(r"(?i)([a-z0-9_\-]{1,6})~\d+\.[a-z0-9]{1,4}", str(doc or "").strip())
            _same_short50 = bool(_short50) and re.sub(r"[^a-z0-9]", "", str(cdoc or "").lower()).startswith(
                re.sub(r"[^a-z0-9]", "", _short50.group(1).lower()))
            if doc != cdoc and not (_generic50 and str(cdoc or "").lower().endswith(".pdf")) and not _same_short50:
                continue
            if page and cpage and page != cpage:
                continue
            return True
    return False


def _scopes(text: str) -> set[str]:
    toks = {t.lower() for t in re.findall(r"[a-zà-ÿA-ZÀ-Ÿ]{2,}", str(text or ""))}
    return {_SCOPE_ALIASES.get(t, t) for t in toks if t in _SCOPE_TOKENS}


def _scopes_compatible(line_s: set, claim_s: set) -> bool:
    """La ligne périmétrée exige un claim qui certifie le périmètre."""
    if not line_s:
        return True
    if not claim_s:
        return False
    return bool(line_s & claim_s)


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(str(text or ""))
            if t.lower() not in _TOKEN_STOP}


def _metric_label_tokens(src: str) -> set[str]:
    # v62.13.9.4.50 — un deux-points de CITATION (« (source : 10-K) », « réf. : », « cf. : ») ne délimite pas une tête
    # de métrique : « trésorerie de 58,1 M$ au 31/08/2025 (source : 10-K) » avait pour « tête » le mot « source » et
    # n'était plus rattachée au fait de trésorerie confirmé (vrai CR du 30/09).
    src = re.sub(r"(?i)[(\[]\s*(?:sources?|r[ée]f\.?|cf\.?|voir|see)\s*:[^)\]]*[)\]]", " ", str(src or ""))
    head = src.split(":", 1)[0] if ":" in src else ""
    return {w for w in re.findall(r"[a-zà-ÿA-ZÀ-Ÿ]{3,}", head.lower())
            if w not in _METRIC_STOP}


def _claim_get(claim: Any, key: str) -> Any:
    if isinstance(claim, Mapping):
        return claim.get(key)
    return getattr(claim, key, None)


def _claim_has_provenance(claim: Any) -> bool:
    """v62.13.9.4.11 — « CONFIRMÉ À LA PAGE » sans page est contradictoire.

    Un claim qui revendique ce statut sans aucune référence de pièce
    s'auto-déclare confirmé : c'est la forme la plus directe de
    l'auto-promotion, et le contre-audit du 31/08/2026 l'a exhibée. Le statut
    dérivé, lui, hérite sa provenance de ses composants et n'est pas soumis à
    la même exigence directe.
    """
    for key in ("source_doc", "source_ref", "source_page", "page"):
        if str(_claim_get(claim, key) or "").strip():
            return True
    refs = _claim_get(claim, "source_refs") or ()
    for r in refs:
        if isinstance(r, Mapping) and (r.get("source_doc") or r.get("source_page")):
            return True
        if not isinstance(r, Mapping) and str(r or "").strip():
            return True
    return bool(_claim_get(claim, "fact_instance_ids"))


def _claim_status_ok(claim: Any) -> bool:
    """v62.13.9.4.10 — le STATUT PROBATOIRE est exigé, sans repli.
    ``claim_type`` (FACT / DERIVED) est une typologie de contenu, pas une
    preuve : un claim sans ``proof_status`` recevable ne certifie rien
    (contre-audit 31/08/2026). Le repli de la 9.4.9 laissait passer un
    « FACT » auto-déclaré."""
    status = str(_claim_get(claim, "proof_status") or "").upper()
    if status not in _ALLOWED_PROOF_STATUS:
        return False
    if status == "CONFIRMED_ON_PAGE" and not _claim_has_provenance(claim):
        return False
    if status in ("CONFIRMED_IN_FILING", "CONFIRMED_IN_REGISTRY") and not (
            str(_claim_get(claim, "source_doc") or "").strip() and _claim_get(claim, "external")):
        return False
    return True


def _claim_text(claim: Any) -> str:
    parts = []
    for k in ("compact_executive_line", "executive_line", "canonical_line",
              "label", "metric", "value", "display_value", "current_display",
              "previous_display", "formula", "period", "text"):
        v = _claim_get(claim, k)
        if v not in (None, ""):
            parts.append(str(v))
    if not parts:
        parts.append(str(claim or ""))
    return " ".join(parts)


def _claim_profile(claim: Any) -> dict | None:
    """Profil probatoire structuré : montants absolus, devise, périodes,
    périmètre, tokens de métrique. None ⇒ claim non probant."""
    if not _claim_status_ok(claim):
        return None
    text = _claim_text(claim)
    amounts = _amounts(text, mask=False)
    nv = _claim_get(claim, "normalized_value")
    if isinstance(nv, (int, float)):
        cur = str(_claim_get(claim, "currency") or "").upper() or None
        unit = str(_claim_get(claim, "unit") or "").upper()
        hit = next((a for a in amounts
                    if abs(a["abs"] - float(nv)) < 1e-6 * max(1.0, abs(float(nv)))), None)
        if hit is None:
            amounts.append({"abs": float(nv), "raw_int": None,
                            "currency": _CUR_MAP.get(cur, cur),
                            "pct": unit == "PCT", "start": -1, "end": -1})
        else:
            if cur and not hit["currency"]:
                hit["currency"] = _CUR_MAP.get(cur, cur)
            if unit == "PCT":
                hit["pct"] = True
    for comp in (_claim_get(claim, "numeric_components") or []):
        if isinstance(comp, Mapping) and isinstance(comp.get("value"), (int, float)):
            v = float(comp["value"])
            if not any(abs(a["abs"] - v) < 1e-6 * max(1.0, abs(v)) for a in amounts):
                amounts.append({"abs": v, "raw_int": None, "currency": None,
                                "pct": str(comp.get("kind") or "") == "pct",
                                "start": -1, "end": -1})
    if not amounts:
        return None
    periods = _periods(text)
    for pk in ("period", "comparison_period"):
        p = _claim_get(claim, pk)
        if p:
            periods |= _periods(str(p))
    scopes = _scopes(text)
    sc = str(_claim_get(claim, "scope") or "").lower()
    if sc:
        extra = _scopes(sc)
        if not extra and "consolid" in sc:
            extra = {"consolidated"}
        elif not extra and "social" in sc:
            extra = {"social"}
        scopes |= extra
    label_src = " ".join(str(_claim_get(claim, k) or "")
                         for k in ("label", "metric", "metric_id"))
    metric_tokens = _tokens(label_src) | _metric_label_tokens(text)
    return {"amounts": amounts, "periods": periods, "scopes": scopes,
            "entities": _entities(label_src) | _entities(text),
            "sources": (_stated_sources(text)
                        | _stated_sources(" ".join(
                            f"{r.get('source_doc', '')} {r.get('source_page', '')}"
                            for r in (_claim_get(claim, "source_refs") or [])
                            if isinstance(r, Mapping)))
                        | _stated_sources(str(_claim_get(claim, "source_doc") or ""))),
            "metric": metric_tokens, "tokens": _tokens(text), "text": text}


_RATIO_WORDS50 = {
    "GROSS_PROFIT": r"marge\s+brute|gross\s+margin",
    "GROSS_MARGIN": r"marge\s+brute|gross\s+margin",     # montant de marge brute rangé sous cet identifiant
    "OPERATING_PROFIT": r"marge\s+(?:d['’]exploitation|op[ée]rationnelle|EBIT)|operating\s+margin|EBIT\s+margin",
    "NET_INCOME": r"marge\s+nette|net\s+margin",
}


def _mask_derived_ratios50(text: str, claim_list) -> str:
    """v62.13.9.4.50 — un pourcentage égal (à 0,15 pt près) au rapport de deux faits confirmés du même exercice
    (marge brute = marge brute / chiffre d'affaires…) est certifié par dérivation : il est masqué avant la liaison.
    Contre-recette du 30/09 : « Marge brute : 341,3 M$ (55,0 % du CA) » sortait « sans pièce »."""
    by = {}
    for c in claim_list:
        if not isinstance(c, dict) or not str(c.get("proof_status") or "").startswith("CONFIRMED"):
            continue
        comps = [x for x in (c.get("numeric_components") or []) if isinstance(x, dict) and x.get("kind") == "money"]
        if comps:
            by[(str(c.get("metric_id") or "").upper(), str(c.get("period") or ""))] = float(comps[0].get("value") or 0)
    out = str(text or "")
    for (metric, per), num in list(by.items()):
        rx = _RATIO_WORDS50.get(metric)
        rev = by.get(("REVENUE", per)) or by.get(("NET_SALES", per))
        if not rx or not rev or not num or not re.search(rx, out, re.I):
            continue
        ratio = 100.0 * num / rev
        def _m(mo):
            try:
                v = float(mo.group(1).replace(",", "."))
            except ValueError:
                return mo.group(0)
            return " " * len(mo.group(0)) if abs(v - ratio) <= 0.15 else mo.group(0)
        out = re.sub(r"(?<![\d.,])(\d{1,2}(?:[.,]\d{1,2})?)\s?%", _m, out)
    return out


def supports(line: str, claims: Iterable[Any] | None) -> bool:
    """Vrai seulement si TOUS les nombres non exempts de la ligne sont
    certifiés par un claim probant sur toutes les dimensions déterminables.
    Jamais vrai pour une ligne prospective ; fail-closed sur parse."""
    claim_list = [c for c in (claims or []) if c]
    if not claim_list:
        return False
    text = str(line or "")
    _orig_text50 = text                        # v62.13.9.4.50 — les SOURCES se lisent sur la ligne d'origine
    # v62.13.9.4.49 — le NOM DE LA PIÈCE citée (« — STRATE~1.PDF p.29 ») n'est pas un nombre à certifier : définition
    # partagée des non-quantités. Audit du 29/09/2026 : sans reformulation canonique, la ligne de fait garde sa pièce,
    # et le « 1 » du nom court empêchait de rattacher « £2,420m » à son claim confirmé.
    try:
        from utils.non_quantity import FILE_NAME_RE as _FNR49, SEC_FORM_RE as _SFR50
        text = _FNR49.sub(lambda m: " " * len(m.group(0)), text)
        text = _SFR50.sub(lambda m: " " * len(m.group(0)), text)      # v62.13.9.4.50 — « 10-K », « 20-F »
    except Exception:
        pass
    # v62.13.9.4.15 — FAIT DE REGISTRE EN PROSE. « structure solo (0 salarié)
    # positionnée sur le conseil en gestion (70.22Z) » : le signal d'action
    # (« structure » lu comme verbe) coupait la liaison avant tout examen,
    # et le fait Pappers — la valeur la plus certifiée du dossier — était
    # retenu. Un fait de registre reste un fait quelle que soit la phrase
    # qui le porte : quand TOUS les nombres non exempts de la ligne sont
    # des montants de registre portés par leur métrique, la ligne est
    # étayée. Les codes NAF/APE sont exempts (identifiants).
    try:
        _reg = [c for c in claim_list if isinstance(c, dict)
                and str(c.get("claim_id") or "").upper().startswith("REGISTRY-")]
        if _reg:
            _scan = re.sub(r"\b\d{2}\.?\d{2}[A-Z]\b", " ", _EQ.mask_exempt(text))
            _amts = [a for a in _amounts(_scan, mask=False)]
            if _amts:
                def _sing(w):
                    return w[:-1] if len(w) > 4 and w.endswith("s") else w
                ok = True
                for a in _amts:
                    after = re.match(r"\s*([\wà-ÿÀ-Ÿ-]+)", _scan[a["end"]:])
                    unit = _sing(after.group(1).lower()) if after else ""
                    bound = False
                    for c in _reg:
                        prof = _claim_profile(c)
                        if not prof:
                            continue
                        toks = {_sing(x.lower()) for x in prof["metric"]}
                        if unit and unit in toks and any(
                                ca["abs"] == a["abs"] for ca in prof["amounts"]):
                            bound = True
                            break
                    if not bound:
                        ok = False
                        break
                if ok:
                    return True
    except Exception:
        pass
    # primauté du passé factuel (contrat 9.4.7) : « Inventories changed by »,
    # « margin increased to » sont des FAITS — exactement ce qu'un claim
    # certifie — même quand le moteur A y voit un verbe structurel ; une
    # ligne sans passé factuel reste inéligible dès le moindre signal
    # d'action, de décision ou de prospection.
    try:
        from utils.quantity_ledger import _has_factual_past as _hfp
        _factual_past = bool(_hfp(text, "en") or _hfp(text, "fr"))
    except Exception:
        _factual_past = False
    if not _factual_past:
        if _EQ.action_signal(text) or _EQ.DECISION_VERB_RE.search(text):
            return False
        if _EQ.prospective_context(text):
            return False

    _before50 = _amounts(text, mask=True) if "%" in str(text or "") else None
    text = _mask_derived_ratios50(text, claim_list)
    # v62.13.9.4.50 — si les seuls nombres de la ligne étaient des taux certifiés par dérivation, la ligne est soutenue
    # (sinon « plus rien à certifier » valait refus : « [FACT] Operating margin: 4.8% (FY2026) » sortait non étayée)
    _yr50 = lambda a: (not a.get("pct")) and float(a.get("abs") or 0).is_integer() and 1900 <= float(a.get("abs") or 0) <= 2100
    if _before50 and not [a for a in _amounts(text, mask=True) if not _yr50(a)] and [a for a in _before50 if not _yr50(a)]:
        return True
    from utils.quantity_ledger import local_quantity_unit as _lex_unit
    scan_line = _EQ.mask_exempt(text)

    def _is_year_token(a: dict) -> bool:
        """Une année nue (1900-2099, quatre chiffres, sans devise, sans %,
        sans unité lexicale) relève du canal période, pas du canal montant."""
        if a["currency"] or a["pct"]:
            return False
        if not (a["raw_int"] and len(a["raw_int"]) == 4
                and 1900 <= a["abs"] <= 2099 and float(a["abs"]).is_integer()):
            return False
        return _lex_unit(scan_line, a["start"], a["end"],
                         scan_line[a["start"]:a["end"]]) == "BARE"

    line_amounts = [a for a in _amounts(text, mask=True)
                    if not _is_year_token(a)]
    if not line_amounts:
        return False
    line_periods = _periods(text)
    line_scopes = _scopes(text)
    line_entities = _entities(text)
    # v62.13.9.4.50 — la pièce citée se lit sur la ligne d'ORIGINE : masquer son nom (pour qu'il ne soit pas pris pour
    # des nombres) laissait « p.48 » sans pièce, et la ligne de base confirmée « [FAIT] Trésorerie : 58,1 M$ (FY2025) —
    # <fichier du dépôt> p.48 » n'était plus rattachée à son propre claim (tri du vrai CR du 30/09)
    line_sources = _stated_sources(_orig_text50)
    line_head = _metric_label_tokens(text)

    profiles = [p for p in (_claim_profile(c) for c in claim_list) if p]
    if not profiles:
        return False

    _INDET = {"BARE"}
    for amt in line_amounts:
        lo = max(0, amt["start"] - 40)
        while lo > 0 and scan_line[lo - 1].isalnum():
            lo -= 1                      # ne jamais tronquer un mot au bord
        hi = min(len(scan_line), amt["end"] + 40)
        while hi < len(scan_line) and scan_line[hi].isalnum():
            hi += 1
        window = _tokens(scan_line[lo:hi])
        lex_l = _lex_unit(scan_line, amt["start"], amt["end"],
                          scan_line[amt["start"]:amt["end"]])
        matched = False
        for prof in profiles:
            # métrique : quand le claim en nomme une, la ligne doit la
            # partager (tête avant « : » ou voisinage du nombre) — un
            # montant en devise ne s'auto-suffit jamais
            if prof["metric"]:
                # la métrique se juge à la tête et au voisinage du nombre ;
                # à défaut d'intersection locale, la ligne entière tranche
                # (un delta en fin de parenthèse n'a pas de voisinage propre)
                side = line_head | window
                if not (side & prof["metric"]) \
                        and not (_tokens(scan_line) & prof["metric"]):
                    continue
                # discrimination : deux qualificatifs distincts sur une même
                # tête générique désignent deux métriques différentes
                # les noms d'entité et de périmètre ne discriminent pas une
                # MÉTRIQUE : ils ont leur propre règle, et les laisser ici
                # faisait passer « gross margin » pour « operating margin »
                # dès que les deux lignes nommaient la même société.
                _noise = line_entities | prof["entities"] | line_scopes | prof["scopes"]
                # v62.13.9.4.12.5 — comparaison au SINGULIER : « salarié » et
                # « salariés » désignent la même métrique. Le pluriel seul
                # faisait échouer la liaison d'un fait de registre au run réel.
                def _sing(s):
                    return {w[:-1] if len(w) > 4 and w.endswith("s") else w for w in s}
                side_disc = _sing((side | line_head) - _GENERIC_METRIC_HEAD - _noise)
                claim_disc = _sing(prof["metric"] - _GENERIC_METRIC_HEAD - _noise)
                if side_disc and claim_disc and not (side_disc & claim_disc):
                    continue
            elif line_head and prof["tokens"] and not (line_head & prof["tokens"]):
                continue
            if not _periods_compatible(line_periods, prof["periods"]):
                continue
            if not _scopes_compatible(line_scopes, prof["scopes"]):
                continue
            if not _entities_compatible(line_entities, prof["entities"]):
                continue
            if not _sources_compatible(line_sources, prof["sources"]):
                continue
            for camt in prof["amounts"]:
                _tol50 = max(1e-6 * max(1.0, abs(camt["abs"])), float(amt.get("tol") or 0.0))
                if (abs(camt["abs"] - amt["abs"]) > _tol50
                        and not (amt.get("alt_abs") is not None
                                 and abs(camt["abs"] - amt["alt_abs"]) <= max(_tol50, 0.0005 * abs(camt["abs"])))):
                    continue
                if amt["pct"] != camt["pct"]:
                    continue
                if amt["currency"] and camt["currency"] and amt["currency"] != camt["currency"]:
                    continue
                if amt["currency"] and not camt["currency"]:
                    continue  # devise affirmée ⇒ devise certifiée
                if camt.get("raw_int") is not None and camt["start"] >= 0:
                    lex_c = _lex_unit(prof["text"], camt["start"], camt["end"],
                                      prof["text"][camt["start"]:camt["end"]])
                    # v62.13.9.4.12.5 — comparaison au SINGULIER ici aussi :
                    # « 0 salarié » et « 0 salariés » sont la même unité. Le
                    # contrat 9.4.7 vise à distinguer des unités DIFFÉRENTES
                    # (24 mois ≠ 24 centres), pas un accord grammatical.
                    def _s1(u: str) -> str:
                        u = str(u or "").lower()
                        return u[:-1] if len(u) > 4 and u.endswith("s") else u
                    if (lex_l not in _INDET and lex_c not in _INDET
                            and _s1(lex_l) != _s1(lex_c)):
                        continue  # 24 mois ≠ 24 centres (contrat 9.4.7)
                matched = True
                break
            if matched:
                break
        if not matched:
            return False
    return True
