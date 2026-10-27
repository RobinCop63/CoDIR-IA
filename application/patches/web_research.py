"""v17.1.0-B2.3-F — Web-sourcing PILOTÉ PAR LES QUESTIONS DU SUJET.

Constat (run « étude de marché ») : le web-sourcing était câblé en « veille
concurrentielle » indexée sur le NOM DE SOCIÉTÉ. Pour une PME/SASU sans
empreinte web), il a cherché la société, pas le SUJET (« marché du management
de transition 2026 »). D'où des chiffres marché sortis de la mémoire du modèle,
habillés en [ESTIM-COMPARABLE], jamais réellement sourcés.

Ce module DÉRIVE des questions de recherche à partir du sujet d'agenda, puis
gouverne les sources comme les faits documentaires : URL + date + fiabilité +
fourchette basse / centrale / haute. Il NE FABRIQUE PAS de chiffres : il prépare
les requêtes et qualifie ce qui revient. L'exécution réseau passe par le module
web existant (providers en cascade), fail-open.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Tuple

from patches.agenda_genre import GenreResult, MARKET_STUDY, BIZDEV_PLAN


# ─────────────────────────────────────────────────────────────────────────────
# 1. Dérivation des questions de recherche
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ResearchQuery:
    kind: str          # market_size | growth | pricing | players | trends | positioning
    question: str      # formulation lisible (pour le CR)
    query: str         # requête web effective

    def __repr__(self) -> str:
        return f"ResearchQuery({self.kind}: {self.query!r})"


_YEAR_NOW = date.today().year


def derive_research_questions(
    brief: str,
    genre: GenreResult,
    company_name: str = "",
    sector: str = "",
    year: Optional[int] = None,
) -> List[ResearchQuery]:
    """Construit la liste des requêtes web à lancer pour un point d'agenda.

    - genre « marché » avec sujet → batterie marché (taille, croissance, prix,
      acteurs, tendances) sur le SUJET, pas sur la société.
    - volet développement (BIZDEV) → requête de positionnement.
    Renvoie [] si rien d'exploitable (le scan société historique reste géré
    ailleurs)."""
    year = year or _YEAR_NOW
    out: List[ResearchQuery] = []
    topic = (genre.research_topic or "").strip()

    if genre.wants_market_research and topic:
        out += [
            ResearchQuery("market_size", f"Taille du marché « {topic} » ({year}) ?",
                          f"marché {topic} taille chiffre d'affaires {year} France"),
            ResearchQuery("growth", f"Croissance / dynamique du marché « {topic} » ({year}) ?",
                          f"marché {topic} croissance évolution {year} {year-1} France"),
            ResearchQuery("pricing", f"Niveau de prix / TJM sur « {topic} » ?",
                          f"{topic} TJM tarif journalier moyen {year} France"),
            ResearchQuery("players", f"Acteurs principaux et parts sur « {topic} » ?",
                          f"{topic} principaux acteurs parts de marché France"),
            ResearchQuery("trends", f"Tendances structurantes « {topic} » {year}-{year+1} ?",
                          f"{topic} tendances perspectives {year} {year+1}"),
        ]

    # Volet développement d'activité : positionnement / segments porteurs.
    if (BIZDEV_PLAN in ([genre.genre] + genre.components)) and topic:
        out.append(ResearchQuery(
            "positioning", f"Segments porteurs / différenciation sur « {topic} » ?",
            f"{topic} segments porteurs différenciation {year} France"))

    return out


# ─────────────────────────────────────────────────────────────────────────────
# 2. Gouvernance des sources web (URL + date + fiabilité)
# ─────────────────────────────────────────────────────────────────────────────
# Domaines/types à fiabilité forte : sources primaires, fédérations, instituts,
# administrations, études nommées. MEDIUM : presse spécialisée, cabinets.
# WEAK : blogs, agrégateurs, contenu non daté.
_STRONG_SRC = (
    "insee.fr", "data.gouv", ".gouv.fr", "eurostat", "xerfi", "france-transition",
    "francetransition", "banque-france", "amf-france", "legifrance", "observatoire",
    "fédération", "federation", "baromètre", "barometre", "étude ", "study ",
)
_MEDIUM_SRC = (
    "lesechos", "decideurs", "daf-mag", "usine-nouvelle", "challenges", "latribune",
    "400.partners", "ghpartners", "wayden", "cabinet", "partners", "consulting",
)
_WEAK_SRC = ("blog", "medium.com", "wikipedia", "quora", "reddit", "forum")


def classify_web_reliability(url: str = "", text: str = "",
                             published: Optional[date] = None,
                             today: Optional[date] = None) -> str:
    """STRONG / MEDIUM / WEAK. Une source non datée plafonne à MEDIUM ; une source
    de plus de ~24 mois est dégradée d'un cran (le marché bouge)."""
    blob = f"{url} {text}".lower()
    level = "WEAK"
    if any(s in blob for s in _STRONG_SRC):
        level = "STRONG"
    elif any(s in blob for s in _MEDIUM_SRC):
        level = "MEDIUM"
    elif any(s in blob for s in _WEAK_SRC):
        level = "WEAK"
    else:
        level = "MEDIUM" if url else "WEAK"

    today = today or date.today()
    if published is None:
        # non daté : ne peut pas être board-safe pour un chiffre de marché
        if level == "STRONG":
            level = "MEDIUM"
    else:
        months = (today.year - published.year) * 12 + (today.month - published.month)
        if months > 24:
            level = {"STRONG": "MEDIUM", "MEDIUM": "WEAK", "WEAK": "WEAK"}[level]
    return level


# ─────────────────────────────────────────────────────────────────────────────
# 3. Fourchette basse / centrale / haute
# ─────────────────────────────────────────────────────────────────────────────
_NUM = r"(\d[\d\s\u202f.,]*)"
_UNIT = r"(Md|Mrd|bn|M|m|K|k|%)?"
_SIGN = r"([+\-]?)\s*"
_SEP = r"(?:\s*[-–]\s*|\s+à\s+|\s+to\s+|\s+et\s+|\s+and\s+)"
_RANGE_RE = re.compile(
    rf"{_SIGN}{_NUM}\s*{_UNIT}\s*(?:€|euros?|HT)?{_SEP}{_SIGN}{_NUM}\s*{_UNIT}",
    re.IGNORECASE,
)
_SINGLE_RE = re.compile(rf"{_SIGN}{_NUM}\s*{_UNIT}\s*(?:€|euros?|HT|%)", re.IGNORECASE)


def _signed(sign: str, num: str) -> Optional[float]:
    v = _to_float(num)
    if v is None:
        return None
    return -v if sign == "-" else v


def _to_float(num: str) -> Optional[float]:
    if not num:
        return None
    s = num.replace("\u202f", "").replace(" ", "").replace(",", ".")
    s = re.sub(r"\.(?=\d{3}\b)", "", s)  # séparateur milliers « 1.050 »
    try:
        return float(s)
    except ValueError:
        return None


def parse_market_range(text: str) -> Optional[Tuple[float, float, float]]:
    """« 950-1050 M€ » → (950, 1000, 1050) ; « 700 M€ » → (700, 700, 700) ;
    « +8% à +12% » → (8, 10, 12) ; « -6,2% » → (-6.2, -6.2, -6.2). Renvoie
    (bas, central, haut) ou None."""
    if not text:
        return None
    m = _RANGE_RE.search(text)
    if m:
        lo, hi = _signed(m.group(1), m.group(2)), _signed(m.group(4), m.group(5))
        if lo is not None and hi is not None:
            if hi < lo:
                lo, hi = hi, lo
            return (lo, round((lo + hi) / 2, 3), hi)
    m = _SINGLE_RE.search(text)
    if m:
        v = _signed(m.group(1), m.group(2))
        if v is not None:
            return (v, v, v)
    return None


@dataclass
class GovernedWebFact:
    metric: str
    raw: str
    low: Optional[float]
    central: Optional[float]
    high: Optional[float]
    url: str
    published: Optional[date]
    reliability: str
    note: str = ""

    def as_line(self) -> str:
        rng = ""
        if self.central is not None:
            if self.low != self.high:
                rng = f"{self.low}–{self.high} (centrale {self.central})"
            else:
                rng = f"{self.central}"
        d = self.published.isoformat() if self.published else "date n/d"
        return (f"{self.metric} : {rng or self.raw} "
                f"[{self.reliability} · {d} · {self.url or 'URL n/d'}]")


def govern_web_fact(metric: str, raw_text: str, url: str = "",
                    published: Optional[date] = None,
                    today: Optional[date] = None) -> GovernedWebFact:
    """Qualifie un chiffre marché : fourchette + fiabilité + provenance. Ne
    transforme jamais une absence de source en fait : reliability WEAK + note."""
    rng = parse_market_range(raw_text)
    lo, ce, hi = (rng if rng else (None, None, None))
    rel = classify_web_reliability(url=url, text=raw_text, published=published, today=today)
    note = "" if url else "source non explicitée — à confirmer"
    return GovernedWebFact(metric=metric, raw=raw_text.strip(), low=lo, central=ce,
                           high=hi, url=url, published=published, reliability=rel, note=note)


# ─────────────────────────────────────────────────────────────────────────────
# 4. WebFactsLedger structuré (v17.1.0-B2.3-F.2)
# ─────────────────────────────────────────────────────────────────────────────
# Parse la sortie texte de la recherche marché en LIGNES de faits gouvernés :
# métrique · valeur(fourchette) · année · source(URL) · fiabilité · board-safe.
# Borné et fail-open : on STRUCTURE ce qui est présent, on n'invente rien. Un
# fait est « board-safe » seulement s'il a une valeur, une année ET une URL de
# fiabilité ≥ MEDIUM.
_URL_IN_LINE = re.compile(r"https?://[^\s)\]]+", re.IGNORECASE)
_YEAR_IN_LINE = re.compile(r"\b(20\d{2})\b")
# Étiquette de métrique en tête de ligne/puce (avant « : » ou « — »).
_METRIC_LABEL = re.compile(r"^\s*(?:[-*•·]|\d+[.)])?\s*([^:—–]{3,60})\s*[:—–]")


@dataclass
class WebFactRow:
    metric: str
    raw: str
    low: Optional[float]
    central: Optional[float]
    high: Optional[float]
    year: Optional[int]
    url: str
    reliability: str
    board_safe: bool
    metric_class: str = "OTHER"
    scope: str = "UNKNOWN"
    nature: str = "UNKNOWN"
    decision_safe: bool = False
    value_display: str = ""

    def as_row(self) -> dict:
        return {
            "metric": self.metric, "valeur_basse": self.low, "valeur_centrale": self.central,
            "valeur_haute": self.high, "annee": self.year, "source_url": self.url,
            "fiabilite": self.reliability, "board_safe": self.board_safe,
            "metric_class": self.metric_class, "scope": self.scope,
            "nature": self.nature, "decision_safe": self.decision_safe,
            "value_display": self.value_display,
            "raw": self.raw,
        }


def _clean_markdown_cell(value: str) -> str:
    v = str(value or "").strip()
    v = re.sub(r"^[|\s]+|[|\s]+$", "", v)
    v = v.replace("**", "").replace("__", "").replace("`", "")
    return re.sub(r"\s+", " ", v).strip(" -–—")


def _split_markdown_row(line: str) -> list[str]:
    if "|" not in line:
        return []
    cells = [_clean_markdown_cell(x) for x in line.strip().strip("|").split("|")]
    if len(cells) < 2 or all(not x for x in cells):
        return []
    if all(re.fullmatch(r":?-{3,}:?", x or "") for x in cells):
        return []
    return cells


def _metric_class(metric: str) -> str:
    m = str(metric or "").lower()
    if "taille" in m or "market size" in m:
        return "MARKET_SIZE"
    if "croissance" in m or "dynamique" in m or "growth" in m or "évolution" in m:
        return "GROWTH"
    if "tjm" in m or "tarif" in m or "prix" in m or "pricing" in m:
        return "PRICING"
    if "acteur" in m or "part" in m or "player" in m:
        return "PLAYERS"
    if "segment" in m or "tendance" in m or "trend" in m:
        return "SEGMENT"
    return "OTHER"


def _scope_and_nature(metric: str, line: str, url: str) -> tuple[str, str]:
    """Classify perimeter and epistemic nature without guessing from the date.

    v62.6 is deliberately fail-closed: a generic metric class is not enough to
    assert a total-market perimeter, and the words « published/barometer » do
    not turn a forecast into an observed result.
    """
    blob = f"{metric} {line}".lower()
    domain = str(url or "").lower()
    mclass = _metric_class(metric)
    scope = "UNKNOWN"
    if "lynk-house" in domain and mclass == "GROWTH":
        scope = "SOURCE_ACTOR"
    elif re.search(r"interm[ée]di[ée]|cabinets?\s+structur", blob):
        scope = "INTERMEDIATED_MARKET"
    elif re.search(r"gr[ée][ -]?[àa][ -]?gr[ée]|march[ée]\s+direct|direct\s+market", blob):
        scope = "DIRECT_MARKET"
    elif re.search(r"march[ée]\s+(?:fran[çc]ais|total)|total\s+market|taille\s+du\s+march[ée]", blob):
        scope = "TOTAL_MARKET"

    nature = "UNKNOWN"
    if scope == "SOURCE_ACTOR":
        nature = "ACTOR_RESULT"
    elif re.search(r"\b(?:pr[ée]vision|forecast|projection|devrait|attendu|anticip[ée]|"
                   r"potentiel|pourrait|experts?\s+pr[ée]voient)\b", blob):
        nature = "FORECAST"
    elif re.search(r"\b(?:estim[ée]e?|estimation|estimate)\b", blob):
        nature = "ESTIMATE"
    elif re.search(r"\b(?:observ[ée]|r[ée]alis[ée]|mesur[ée]|constat[ée]|"
                   r"a\s+atteint|s['’]est\s+[ée]lev[ée]|recul|baisse|hausse)\b", blob):
        nature = "OBSERVED"
    return scope, nature

_UNIT_NEAR = re.compile(r"(€|\$|%|\bM€|\bk€|\bMd|\bmillion|\bmilliard|\bk\$|\bbn\b|\bm\b)", re.IGNORECASE)


def _looks_like_year_range(lo, hi, line: str) -> bool:
    """v17.1.0-B2.3-F.4.2 — « Tendances 2026-2027 » ne doit pas devenir une valeur
    2026.0–2027.0. Vrai si les bornes ressemblent à des ANNÉES et que la ligne ne
    porte aucune unité chiffrée (€/%/M€…)."""
    try:
        if lo is None or hi is None:
            return False
        if 2000 <= lo <= 2099 and 2000 <= hi <= 2099 and (hi - lo) <= 12:
            # A period is metadata, never a metric value — even when the same
            # sentence also contains a monetary unit elsewhere.
            return True
    except Exception:
        pass
    return False


def _value_display(value_text: str, line: str, *, table_row: bool) -> str:
    """Preserve the human unit without merging it with the period column.

    Numeric governance keeps low/central/high as numbers.  The presentation
    layer also needs a compact value such as ``1 000–1 500 €`` or ``+55 %``;
    reconstructing it later from floats loses the unit and caused the v62.3
    facts slide to display ``1.0–2025.0``.  Markdown table cells are already
    the authoritative boundary.  For prose, retain only the matched numeric
    token and its immediate suffix.
    """
    if table_row:
        return _clean_markdown_cell(value_text)[:80]
    raw = str(line or "")
    match = _RANGE_RE.search(raw) or _SINGLE_RE.search(raw)
    if not match:
        return ""
    token = match.group(0).strip()
    tail = raw[match.end():match.end() + 24]
    extra = re.match(r"\s*(?:€|euros?|HT(?:/jour)?|/jour|par\s+an|missions?|jours?|mois)",
                     tail, re.IGNORECASE)
    if extra:
        token += extra.group(0)
    return re.sub(r"\s+", " ", token).strip()[:80]


def build_web_facts_ledger(market_output: str, sources: Optional[List[str]] = None,
                           today: Optional[date] = None) -> List[WebFactRow]:
    """Structure les faits marché sans mélanger valeur, année et périmètre.

    Les lignes de tableaux markdown sont parsées cellule par cellule. Cela évite
    les erreurs terrain v62.3 où « 1 000-1 500 € / 2025 » devenait
    ``1.0–2025.0``. Une croissance d'un cabinet reste un résultat d'acteur et ne
    peut jamais être promue en croissance du marché.
    """
    if not market_output:
        return []
    rows: List[WebFactRow] = []
    seen = set()
    for raw in market_output.splitlines():
        line = raw.strip()
        if len(line) < 6:
            continue
        cells = _split_markdown_row(line)
        table_row = bool(cells)
        metric = ""
        value_text = line
        year = None
        if cells:
            # Ignore l'en-tête de tableau.
            if cells[0].lower() in {"métrique", "metric", "indicateur"}:
                continue
            metric = cells[0]
            value_text = cells[1] if len(cells) > 1 else line
            for c in cells[2:5]:
                ym = re.fullmatch(r"\s*(20\d{2})\s*", c)
                if ym:
                    year = int(ym.group(1))
                    break
        # v62.13.9.4.22 — contre-audit v21 (§7) : une URL n'est jamais une
        # métrique (« 1–2025, centr. 1013 » lu dans une adresse), et l'année
        # d'un libellé (« Marché 2016 — 285 à 315 M€ ») ne borne pas la plage.
        if re.match(r"^\s*(?:[-*•]\s*)?\**\s*URL\b", line, re.I) or re.match(r"^\s*(?:[-*•]\s*)?\**\s*(?:source|lien|link)\s*:\s*https?://", line, re.I):
            continue
        _value_scan = _URL_IN_LINE.sub(" ", value_text)
        _value_scan = re.sub(r"\b(?:19|20)\d{2}\b(?=\s*[—–\-:]\s*\d)", " ", _value_scan)   # « 2016 — 285 à 315 » : l'année est un repère
        rng = parse_market_range(_value_scan)
        if not rng:
            # Prose non tabulaire : repli historique, mais sans année comme valeur.
            _line_scan = re.sub(r"\b(?:19|20)\d{2}\b(?=\s*[—–\-:]\s*\d)", " ", _URL_IN_LINE.sub(" ", line))
            rng = parse_market_range(_line_scan)
        if not rng:
            continue
        lo, ce, hi = rng
        if metric.strip().upper() in ("URL", "LIEN", "LINK", "SOURCE") or (hi is not None and hi >= 1900 and hi <= 2100 and lo is not None and lo <= 12):
            continue
        if _looks_like_year_range(lo, hi, value_text):
            continue
        if not metric:
            mlab = _METRIC_LABEL.match(line)
            metric = (mlab.group(1).strip() if mlab else line[:48]).strip(" .-")
        metric = _clean_markdown_cell(metric)[:120]
        url_m = _URL_IN_LINE.search(line)
        url = url_m.group(0).rstrip(".,;|") if url_m else ""
        if year is None:
            yr_m = _YEAR_IN_LINE.search(line)
            year = int(yr_m.group(1)) if yr_m else None
            # Une valeur qui est elle-même une année sans autre année ne devient
            # pas une période de fait.
            if year is not None and re.fullmatch(r"\s*20\d{2}\s*", value_text or ""):
                year = None
        rel = classify_web_reliability(
            url=url, text=line,
            published=date(year, 6, 1) if year else None, today=today)
        if not url and rel in ("STRONG", "MEDIUM"):
            rel = "WEAK"
        mclass = _metric_class(metric)
        scope, nature = _scope_and_nature(metric, line, url)
        # UNKNOWN remains UNKNOWN.  The calendar alone is never proof that an
        # estimate/forecast has become an observed market result.
        # ``board_safe`` conserve le contrat historique (source + année +
        # fiabilité). ``decision_safe`` est le nouveau contrat plus exigeant qui
        # intègre périmètre et nature du chiffre.
        board_safe = bool(url and year and ce is not None and rel in ("STRONG", "MEDIUM"))
        decision_safe = bool(
            board_safe and scope not in {"UNKNOWN", "SOURCE_ACTOR"}
            and nature == "OBSERVED")
        key = (mclass, scope, nature, year, ce, url)
        if key in seen:
            continue
        seen.add(key)
        rows.append(WebFactRow(
            metric=metric, raw=line, low=lo, central=ce, high=hi,
            year=year, url=url, reliability=rel, board_safe=board_safe,
            metric_class=mclass, scope=scope, nature=nature,
            decision_safe=decision_safe,
            value_display=_value_display(value_text, line, table_row=table_row)))
    sourced_values = {r.central for r in rows if r.url and r.central is not None}
    return [r for r in rows if not (not r.url and r.central in sourced_values)]


def web_facts_ledger_to_markdown(rows: List[WebFactRow], lang: str = "fr") -> str:
    """Rendu lisible du ledger avec périmètre et nature du chiffre."""
    if not rows:
        return ""
    if lang == "en":
        head = ("| Metric | Value | Year | Scope | Nature | Reliability | Board-safe | Decision-safe | Source |\n"
                "|---|---|---|---|---|---|---|---|---|")
    else:
        head = ("| Métrique | Valeur | Année | Périmètre | Nature | Fiabilité | Board-safe | Décision-safe | Source |\n"
                "|---|---|---|---|---|---|---|---|---|")
    out = [head]
    for r in rows:
        if r.value_display:
            val = r.value_display
        elif r.central is None:
            val = "—"
        elif r.low != r.high:
            val = f"{r.low}–{r.high} (centr. {r.central})"
        else:
            val = f"{r.central}"
        board = "✓" if r.board_safe else "—"
        safe = "✓" if r.decision_safe else "—"
        src = r.url or ("non sourcé" if lang == "fr" else "unsourced")
        cells = [r.metric or "—", val, str(r.year or "—"), r.scope,
                 r.nature, r.reliability, board, safe, src]
        out.append("| " + " | ".join(str(c).replace("|", "/") for c in cells) + " |")
    return "\n".join(out)

