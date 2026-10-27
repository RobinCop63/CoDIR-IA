"""v62.13.9.4.11 (A1) — pont entre les grandeurs DÉCLARÉES et la chaîne de sûreté.

Six cycles ont montré qu'on ne devine pas de façon fiable, à partir du texte
sérialisé, si un nombre est un fait, une cible, une option ou un instrument de
mesure. L'agent qui écrit la phrase, lui, le sait au moment où il l'écrit :
depuis la 9.4.11 il le déclare (``patches.agent_output_schema.Quantity``).

Ce module indexe ces déclarations et les met à disposition de la chaîne de
sûreté. Il ne juge rien lui-même.

DOCTRINE — asymétrie stricte, et c'est tout l'enjeu du dispositif :

    une déclaration peut RETENIR davantage, jamais RELÂCHER.

Concrètement :

- l'agent déclare ``CIBLE`` → la grandeur est prospective, point final. Aucun
  moteur textuel n'a besoin de la reconnaître, et aucun ne peut la blanchir.
  C'est le gain : la formulation cesse de compter.
- l'agent déclare ``FAIT`` → **cela ne prouve rien**. L'analyse textuelle et
  la chaîne de preuve continuent de statuer normalement. Un agent ne peut pas
  se promouvoir — règle déjà en vigueur pour les tags de claims, étendue ici
  aux grandeurs.
- déclaration absente, illisible ou ambiguë → comportement inchangé,
  c'est-à-dire l'analyse textuelle complète. Le pont est un supplément de
  rétention, jamais une condition du contrôle.

Cette asymétrie est ce qui rend le canal sûr même si le modèle se trompe ou
ment : une déclaration fautive dans le sens permissif n'a aucun effet, une
déclaration fautive dans le sens restrictif ne produit qu'une sur-rétention —
la direction que l'Option B assume depuis toujours.

Module PUR — aucune I/O, aucune dépendance sur les moteurs de jugement.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from utils.non_quantity import mask_non_quantities as _mask_nq48, WITHOUT_PERIODS as _NQ_NO_PERIODS48

__all__ = [
    "DeclaredQuantityIndex",
    "build_declared_index",
    "declared_prospective_values",
]

_NUM_RE = re.compile(r"\d[\d\s\u00A0\u202F.,]*")
# v62.13.9.4.31.1 — dates calendaires complètes : jj-mm-aaaa, jj/mm/aaaa,
# jj.mm.aaaa, aaaa-mm-jj (masquées avant toute recherche de grandeur).
_CALENDAR_DATE_RE = re.compile(
    r"\b\d{1,2}[/.\-]\d{1,2}[/.\-](?:19|20)\d{2}\b"
    r"|\b(?:19|20)\d{2}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2}\b(?![\d/.\-])")
# v62.13.9.4.32 (A) — repères de période et numéros d'ordre étiquetés
_PERIOD_LABEL_RE = re.compile(
    r"\b[TQ][1-4](?:\s*[–\-—]\s*[TQ]?[1-4])?(?:\s+(?:19|20)\d{2})?\b"
    r"|\b[SH][12](?:\s*[–\-—]\s*[SH]?[12])?(?:\s+(?:19|20)\d{2})?\b"
    r"|\b(?:1er|2e|2nd|2ème|3e|3ème|4e|4ème|1st|2nd|3rd|4th)\s+(?:trimestre|semestre|quarter|half)\b"
    r"|\b(?:trimestre|semestre|quarter|half)\s+[1-4]\b", re.I)
# v62.13.9.4.32 (A) — « trois options », « 2 scénarios » : un COMPTE d'éléments de
# structure (options, axes, phases, étapes…) n'est pas une grandeur d'affaires.
_STRUCTURE_COUNT_RE = re.compile(r"\b(?:\d{1,2}|deux|trois|quatre|cinq|six|two|three|four|five|six)\s+(?=(?:options?|sc[ée]narios?|axes?|phases?|[ée]tapes?|piliers?|leviers?|chantiers?|volets?|priorit[ée]s?|pistes?|alternatives?|orientations?|hypoth[èe]ses?|jalons?|trajectoires?|variantes?)\b)", re.I)
_ORDINAL_LABEL_RE = re.compile(r"(\b(?:options?|phases?|[ée]tapes?|axes?|sc[ée]narios?|lots?|volets?|piliers?|priorit[ée]s?|jalons?|leviers?|chantiers?|hypoth[èe]ses?|vagues?|niveaux?|variantes?|alternatives?|orientations?|pistes?|sprints?|versions?|ann[ée]es?|steps?|stages?|workstreams?|tracks?|waves?|levels?|years?|streams?|paliers?))(\s*(?:n[°º]|no\.?|#)?\s*\d{1,2}(?:\s*(?:/|,|et|ou|and|or|[–\-])\s*\d{1,2})*\b(?!\s*(?:%|€|k€|m€|md€|k|m|jours?|mois|ans?|semaines?|days?|months?|years?|weeks?|points?|pts|salari[ée]s|etp|fte)))", re.I)
_METRIC_STOPWORDS = frozenset({
    "de", "du", "des", "la", "le", "les", "un", "une", "en", "et", "ou", "au", "aux", "sur", "par", "pour",
    "vs", "the", "of", "in", "to", "and", "or", "per", "on", "at", "by", "for", "a", "an", "d", "l"})


def _metric_words(metric: str) -> list[str]:
    """Mots significatifs d'un libellé de métrique (acronymes courts compris)."""
    out: list[str] = []
    for w in re.findall(r"[\wà-ÿ]{2,}", str(metric or "").lower()):
        if w in _METRIC_STOPWORDS or w.isdigit():
            continue
        out.append(w)
    return out


_UNIT_FAMILIES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    # (famille, formes déclarées, marques attendues dans le passage)
    ("percent", ("%", "pct", "pourcent", "pour cent", "points", "pts", "pp"),
                ("%", "pour cent", "pourcent", "point", "pts")),
    ("currency", ("€", "eur", "euro", "euros", "k€", "m€", "md€", "keur", "meur", "mdeur", "k euros", "m euros",
                  "millions d'euros", "milliers d'euros", "$", "usd", "£", "gbp"),
                 ("€", "eur", "euro", "k€", "m€", "md€", "$", "usd", "£", "gbp")),
)


def _unit_family(unit: str) -> str:
    u = str(unit or "").strip().lower().replace("\u00a0", " ").replace("\u202f", " ")
    if not u:
        return ""
    for fam, forms, _marks in _UNIT_FAMILIES:
        if u in forms or any(u.endswith(f) for f in forms if len(f) <= 3):
            return fam
    return ""


def _line_has_unit_family(low: str, fam: str) -> bool:
    for f, _forms, marks in _UNIT_FAMILIES:
        if f == fam:
            return any(m in low for m in marks)
    return True
_GENERATION_RE = re.compile(r"\b[A-Za-zÀ-ÿ&]{3,}\s+\d\.0\b|\bOptions?\s+\d{1,2}(?:\s*(?:vs\.?|/|,|et|ou|and|or|[-–])\s*(?:Options?\s+)?\d{1,2})+\b")   # v62.13.9.4.27 ; 9.4.28 : chaînes d'options
_PERIOD_RE = re.compile(r"(?:FY|H[12]|S[12]|[QT][1-4])?\s?(?:19|20)\d{2}", re.I)


def _norm(raw: Any) -> str:
    s = re.sub(r"[\s\u00A0\u202F]", "", str(raw or ""))
    s = s.replace(",", ".")
    # v62.13.9.4.19.2 — « -6,2 % » déclaré « -6.2 » et cité « 6,2 » : même valeur
    s = s.lstrip("+-−")
    # « 24.0 » et « 24 » sont la même valeur déclarée
    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".")[0]
    return s


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key)
    return getattr(obj, key, None)


# v62.13.9.4.41 — UN COMPOSANT DE DATE N'EST PAS UNE GRANDEUR.
# Mesure du 23/09/2026 sur un run réel : sur trente-deux déclarations portant la valeur
# 31, la plupart étaient le « 31 » d'une date — 31 août, clôture de l'exercice ; 31
# octobre, échéance d'une action — déclarées avec l'unité « jour » et, pour certaines, la
# nature FAIT. Un fragment de date n'est ni mesuré ni confirmable à la page, et ce bruit
# rend statistiquement crédible l'apparition d'un chiffre là où il n'a rien à faire.
# Une durée reste une grandeur : « plan sur 24 mois », « délai de 45 jours » ne sont pas
# des composants de date — c'est la MÉTRIQUE qui tranche, pas l'unité seule.
_DATE_METRIC41 = re.compile(
    # « échéance » seul reste ambigu — « échéance à 30 jours » est une durée, donc une
    # grandeur : le motif exige un mot de date explicite.
    r"\bdates?\b|deadline|cl[ôo]ture|fin\s+d['’]?\s*exercice|"
    r"jour\s+(?:de\s+)?(?:fin|cl[ôo]ture)|day\s+of\b|fiscal\s+year\s+end", re.IGNORECASE)
_CAL_UNIT41 = re.compile(
    r"^(?:jours?|days?|mois|months?|ann[ée]es?|years?|"
    # v62.13.9.4.45 — l'unité peut être le NOM du mois, seul ou suivi de l'année
    # (« 31 » avec l'unité « octobre 2026 » est le 31 octobre 2026), ou une date entière.
    r"(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre|"
    r"january|february|march|april|may|june|july|august|september|october|november|december)"
    r"(?:\s+(?:19|20)\d{2})?|(?:19|20)\d{2}|\d{1,2}/\d{4})$", re.IGNORECASE)


def _is_date_component41(metric: Any, unit: Any, value: Any) -> bool:
    m = str(metric or "")
    u = str(unit or "").strip()
    # une unité qui est un mois nommé ou une année suffit : « date » dans la métrique
    # n'est plus requis quand l'unité dit elle-même que c'est un calendrier.
    _month_unit = bool(re.search(r"(?i)^(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|"
                                  r"novembre|d[ée]cembre|january|february|march|april|may|june|july|august|"
                                  r"september|october|november|december)\b", u))
    if not ((_DATE_METRIC41.search(m) and _CAL_UNIT41.match(u)) or _month_unit):
        return False
    d = re.sub(r"\D", "", str(value or ""))
    try:
        return bool(d) and 1 <= int(d) <= 31
    except ValueError:
        return False


class DeclaredQuantityIndex:
    """Index des grandeurs déclarées par les agents d'un run.

    Interrogé par valeur normalisée : une même valeur peut être déclarée
    plusieurs fois, avec des natures différentes. En cas de conflit, la
    déclaration la plus restrictive l'emporte — cohérent avec l'asymétrie du
    module.
    """

    def __init__(self) -> None:
        self._by_value: dict[str, list[dict]] = {}

    def add(self, quantity: Any, *, claim_id: str = "", role: str = "") -> None:
        value = _norm(_get(quantity, "value"))
        if not value:
            return
        entry = {
            "value": value,
            "nature": str(_get(quantity, "nature") or "FAIT").upper(),
            "modality": str(_get(quantity, "modality") or "CONSTATE").upper(),
            "time_frame": str(_get(quantity, "time_frame") or "PRESENT").upper(),
            "metric": (str(_get(quantity, "metric") or "").strip().lower() or None),
            "unit": (str(_get(quantity, "unit") or "").strip() or None),
            "period": (str(_get(quantity, "period") or "").strip().upper() or None),
            "entity": (str(_get(quantity, "entity") or "").strip().lower() or None),
            "claim_id": claim_id,
            "role": role,
        }
        entry["date_component"] = _is_date_component41(entry["metric"], entry["unit"], value)
        self._by_value.setdefault(value, []).append(entry)

    # ── interrogation ────────────────────────────────────────────────────
    def all_entries(self) -> list[dict]:
        """v62.13.9.4.37 — toutes les entrées déclarées, pour la confirmation à la page.
        v62.13.9.4.41 — hors composants de date : le « 31 » d'un 31 août n'est pas un fait
        à confirmer, et sa présence dans le corpus ne prouve rien."""
        return [e for lst in self._by_value.values() for e in lst
                if not e.get("date_component")]

    def entries_for(self, raw_value: Any) -> list[dict]:
        return list(self._by_value.get(_norm(raw_value), ()))

    def is_declared_prospective(self, raw_value: Any) -> bool:
        """Vrai si AU MOINS une déclaration de cette valeur engage l'avenir.

        « Au moins une » et non « toutes » : c'est le sens restrictif, seul
        autorisé ici. Une valeur déclarée CIBLE par un agent et FAIT par un
        autre est traitée comme une cible."""
        # v62.13.9.4.13 — MALFORMED est prospectif par prudence : on ne sait
        # pas ce que la grandeur engage, donc on retient. C'est le pendant du
        # fail-closed posé au parseur, où l'ancien repli vers FAIT détruisait
        # la qualification.
        for e in self.entries_for(raw_value):
            if e["nature"] in {"CIBLE", "OPTION", "SCENARIO", "MALFORMED"}:
                return True
            if e["modality"] in {"DECIDE", "SOUHAITE", "RECOMMANDE",
                                 "HYPOTHETIQUE", "MALFORMED"}:
                return True
            if e["time_frame"] in {"FUTUR", "MALFORMED"}:
                return True
        return False

    def is_declared_apparatus(self, raw_value: Any) -> bool:
        """Grandeur portant sur l'analyse elle-même (score, compteur).

        NB : ceci n'exempte rien à soi seul — les exemptions d'appareil
        restent décidées par la chaîne, qui reconnaît ses propres surfaces.
        L'information sert au diagnostic et au futur affinage."""
        return any(e["nature"] == "APPAREIL" for e in self.entries_for(raw_value))

    def prospective_values(self) -> set[str]:
        return {v for v in self._by_value if self.is_declared_prospective(v)}

    def line_has_declared_target(self, line: str, context: str = "") -> bool:
        """Vrai si la ligne porte un nombre déclaré prospectif ET que la
        déclaration CORRESPOND à cette ligne.

        v62.13.9.4.12 — LOCALITÉ. La version précédente comparait la seule
        valeur : « 24 » déclaré cible dans une phrase de plan contaminait
        « Effectif : 24 personnes en 2024 », un fait sans rapport. Le
        contre-audit du 31/08/2026 l'a mesuré — 9 collisions sur 10 en DOCX
        et 3 phrases mixtes sur 3 perdant leur fait historique.

        Une déclaration ne vaut désormais que pour SA métrique, SA période et
        SON entité : la ligne doit être compatible sur toutes les dimensions
        que la déclaration renseigne. Une dimension non déclarée n'impose
        rien (l'agent n'a pas menti, il n'a pas précisé) — mais une dimension
        déclarée et CONTREDITE par la ligne écarte la déclaration.
        """
        return self.declared_target_in(line) is not None

    def declared_target_in(self, line: str, context: str = "") -> dict | None:
        """Renvoie l'entrée qui gouverne la ligne, ou None.

        v62.13.9.4.48 — SERVICE UNIQUE « cible déclarée » (programme 9.4.48, point 3). Seul ce
        service décide qu'une ligne porte une grandeur déclarée prospective ; le repli à valeur,
        unité et année du mainteneur de surface (9.4.47), qui ne comparait ni la métrique ni la
        nature, est supprimé. Le contexte d'un bloc (titre de section, titre de phasage, en-tête
        de tableau) est reçu EXPLICITEMENT : il sert à retrouver la métrique et l'unité qu'une
        composante (« 2026 (T4) : 350 k€ ») ne nomme pas ; les nombres, eux, ne sont lus que dans
        la ligne, et sa période dans la ligne seule.
        """
        text = str(line or "")
        if not text or not self._by_value:
            return None
        low = (str(context or "") + " \n " + text).lower() if context else text.lower()
        line_periods = _PERIOD_RE.findall(text)
        # « 2026 (T4) », « T4 2026 », « 2026-T4 » : une composante de phasage porte sa période
        # sous des écritures variées ; la déclaration l'écrit à sa façon (« 2026-T4 »).
        for _y, _q in re.findall(r"((?:19|20)\d{2})\s*[\(\-–/ ]\s*([QTHS][1-4])\b", text, re.I):
            line_periods += [_y + _q.upper(), _q.upper() + _y]
        for _q, _y in re.findall(r"\b([QTHS][1-4])\s*[\-–/ ]?\s*((?:19|20)\d{2})", text, re.I):
            line_periods += [_y + _q.upper(), _q.upper() + _y]
        # v62.13.9.4.27 — contre-audit v25 (§5) : une année (« 2026 ») ou un nom
        # de génération (« industrie 4.0 ») n'est jamais la grandeur d'une cible
        # déclarée — « Aucun dimensionnement 2026 … » était retiré, « industrie
        # 4.0 » matchait une cible « 4 ».
        text = _GENERATION_RE.sub(lambda mm: " " * len(mm.group(0)), text)
        # v62.13.9.4.31.1 — une DATE DOCUMENTAIRE n'est jamais une grandeur :
        # « Actes du jj-mm-aaaa.pdf » ne porte pas la cible « 18 ». Contre-audit
        # du 11/09/2026 : le « 18 » d'un nom de pièce daté du
        # 18 janvier 2019 était apparié à l'hypothèse « BFR / CA = 18 % ».
        text = _CALENDAR_DATE_RE.sub(lambda mm: " " * len(mm.group(0)), text)
        # v62.13.9.4.32 (A) — un IDENTIFIANT n'est jamais une grandeur : repère
        # de période (« T1 2027 », « T1-T2 2027 », « S2 2026 », « Q3 »), numéro
        # d'ordre étiqueté (« option 2 », « phase 1 », « étape 3 », « axe 2 »),
        # chiffre collé à une lettre (« T1 », « H2 », « V2 »). Contre-audit du
        # 11/09/2026 (run réel ee08f0) : le « 1 » de « (T1 2027) » dans LA PHRASE
        # DE RECOMMANDATION était apparié à « recrutement responsable export =
        # 1 poste », la phrase était neutralisée dans les deux Word et la trame
        # retombait sur la première option. Même famille que « options 1/2/3 »
        # (contre-audit du dossier industriel).
        text = _PERIOD_LABEL_RE.sub(lambda mm: " " * len(mm.group(0)), text)
        text = _ORDINAL_LABEL_RE.sub(lambda mm: mm.group(1) + " " * len(mm.group(2)), text)   # nom conservé, numéro blanchi
        text = _STRUCTURE_COUNT_RE.sub(lambda mm: " " * len(mm.group(0)), text)
        # v62.13.9.4.48 — non-quantités : définition PARTAGÉE (utils/non_quantity.py) au lieu des
        # règles locales des 9.4.45–46 (« suivi d'une lettre », libellé d'identifiant, nom à trait
        # d'union). La règle « suivi d'une lettre » prenait « £999m » et « 10k€ » pour des
        # identifiants : une déclaration « 999 £m » n'était reconnue qu'écrite « £999 m ».
        text = _mask_nq48(text, kinds=_NQ_NO_PERIODS48)
        for m in _NUM_RE.finditer(text):
            if re.fullmatch(r"(?:19|20)\d{2}", m.group(0).strip()):
                continue
            if m.start() > 0 and text[m.start() - 1].isalpha():
                continue                                   # « T1 », « H2 » : collé à une lettre = identifiant
            # une ligne technique du produit (« Layer 1 status: ✓ OK (13 facts, 60 ms) ») n'est
            # pas une surface métier : ses nombres ne sont pas des cibles.
            if re.search(r"(?i)\b(?:layer|couche)\s+\d\s+status|\b\d+\s*ms\b|\bfacts?,\s*\d+\s*ms", text):
                continue
            for e in self.entries_for(m.group(0)):
                if not self._entry_is_prospective(e):
                    continue
                if not self._entry_matches_line(e, low, line_periods):
                    continue
                return e
        return None

    @staticmethod
    def _entry_is_prospective(e: dict) -> bool:
        return (e["nature"] in {"CIBLE", "OPTION", "SCENARIO", "MALFORMED"}
                or e["modality"] in {"DECIDE", "SOUHAITE", "RECOMMANDE",
                                     "HYPOTHETIQUE", "MALFORMED"}
                or e["time_frame"] in {"FUTUR", "MALFORMED"})

    @staticmethod
    def _entry_matches_line(e: dict, low: str, line_periods: list) -> bool:
        # métrique : au moins un mot significatif du libellé doit figurer.
        # v62.13.9.4.31.1 — les acronymes courts d'une métrique financière
        # (« BFR », « CA », « EBE », « FCF », « ROI ») SONT des mots
        # significatifs : le filtre « quatre caractères au moins » les
        # ignorait, si bien que « BFR / CA » n'exigeait plus rien et que
        # tout « 18 » d'un passage héritait de la déclaration (contre-audit
        # du 11/09/2026). Un mot court doit figurer entier ; un mot long peut
        # figurer comme racine (« croissance » dans « croissances »).
        metric = (e.get("metric") or "").strip().lower()
        if metric:
            words = _metric_words(metric)
            # v62.13.9.4.32 (A) — une métrique à PLUSIEURS mots ne s'apparie pas
            # sur un seul : « recrutement responsable export » happait toute
            # phrase contenant « export ». Deux mots au moins quand il y en a
            # deux ou plus ; le mot seul quand il n'y en a qu'un.
            if words:
                present = sum(1 for w in words if
                              (re.search(r"(?<![\wà-ÿ])" + re.escape(w) + r"(?![\wà-ÿ])", low) if len(w) < 4 else (w in low)))
                # deux mots quand la métrique en a trois ou plus (« recrutement responsable
                # export ») ; un seul suffit pour une métrique courte (« BFR / CA », « CA 2027 »)
                if present < (2 if len(words) >= 3 else 1):
                    return False
        # unité : si la déclaration porte une unité, le passage doit la porter
        # aussi (famille d'unité : « % » ne s'apparie pas à un passage sans
        # « % », « k€ » à un passage sans euro). Une déclaration RETIENT
        # davantage, jamais ne relâche : le juge de base garde son verdict.
        fam = _unit_family(e.get("unit") or "")
        if fam and not _line_has_unit_family(low, fam):
            return False
        # entité : une phrase ne répète pas le nom de la société à chaque
        # ligne (« The estate comprises 42 locations » pour l'entité
        # « Group »). L'absence n'infirme donc RIEN — seule une entité
        # explicitement CONTRAIRE écarterait la déclaration, et ce cas est
        # traité par la métrique et la période. Exiger la présence rendait
        # muettes les déclarations les plus courantes (A1T02, A1T05).
        # période : si la ligne en porte une et que la déclaration en porte
        # une autre, la déclaration est étrangère à la ligne
        period = (e.get("period") or "").strip().upper()
        if period and line_periods:
            pnorm = re.sub(r"[^0-9A-Z]", "", period)
            if pnorm and not any(re.sub(r"[^0-9A-Z]", "", str(p).upper()) == pnorm
                                 for p in line_periods):
                return False
        return True

    def __len__(self) -> int:
        return sum(len(v) for v in self._by_value.values())

    def __bool__(self) -> bool:
        return bool(self._by_value)

    # ── transport ────────────────────────────────────────────────────────
    def to_transport(self) -> dict:
        """v62.13.9.4.12 — TRANSPORT COMPLET, sans perte ni troncature.

        Le cycle précédent sérialisait une simple liste de valeurs
        (``prospective_values``). Deux conséquences, mises au jour par le
        contre-audit du 31/08/2026 : toute la LOCALITÉ était perdue — une
        valeur « 24 » déclarée cible quelque part contaminait chaque « 24 »
        légitime ailleurs (9 collisions sur 10 en DOCX) — et la liste, issue
        d'une fonction de DIAGNOSTIC, était tronquée à 50 entrées, ce qui
        faisait disparaître silencieusement les grandeurs au-delà.

        Le transport porte désormais chaque grandeur avec ses dimensions.
        C'est là qu'était toute la valeur d'A1 : l'objet structuré était bien
        construit, puis aplati en franchissant la frontière.
        """
        out = []
        for entries in self._by_value.values():
            for e in entries:
                out.append({k: e[k] for k in
                            ("value", "nature", "modality", "time_frame",
                             "metric", "unit", "period", "entity",
                             "claim_id", "role")})
        return {"version": "declared-quantities-v2",
                "count": len(out),
                "entries": out}

    def to_diagnostic(self) -> dict:
        """Forme sérialisée de l'index — COMPLÈTE et sans troncature.

        v62.13.9.4.12 : cette méthode est le point d'entrée historique du
        transport (les harnais de qualification l'appellent). Elle porte donc
        les ENTRÉES dimensionnées, et non plus un simple échantillon de
        valeurs. Le compteur et l'échantillon lisible sont conservés pour les
        journaux, mais ils ne décident plus de rien.
        """
        payload = self.to_transport()
        payload.update({
            "declared_quantities": len(self),
            "distinct_values": len(self._by_value),
            "prospective_values": sorted(self.prospective_values()),
            "prospective_values_sample": sorted(self.prospective_values())[:50],
        })
        return payload

    def to_log_summary(self) -> dict:
        """Résumé court destiné aux journaux — jamais un canal de données."""
        return {
            "declared_quantities": len(self),
            "distinct_values": len(self._by_value),
            "prospective_sample": sorted(self.prospective_values())[:20],
        }

    @classmethod
    def from_transport(cls, payload) -> "DeclaredQuantityIndex":
        """Reconstruit l'index depuis le ``result`` d'un run."""
        idx = cls()
        if not isinstance(payload, Mapping):
            return idx
        for e in (payload.get("entries") or ()):
            if isinstance(e, Mapping) and str(e.get("value") or "").strip():
                idx.add(e, claim_id=str(e.get("claim_id") or ""),
                        role=str(e.get("role") or ""))
        return idx


def build_declared_index(agent_outputs: Iterable[Any] | None) -> DeclaredQuantityIndex:
    """Construit l'index à partir des sorties d'agents parsées.

    Tolérant : une sortie absente, un champ manquant ou une forme inattendue
    sont ignorés silencieusement — l'absence de déclaration ramène simplement
    au comportement antérieur.
    """
    index = DeclaredQuantityIndex()
    for ao in (agent_outputs or ()):
        if ao is None:
            continue
        role = str(_get(ao, "role") or "")
        claims = _get(ao, "claims") or ()
        try:
            for claim in claims:
                cid = str(_get(claim, "id") or "")
                for q in (_get(claim, "quantities") or ()):
                    index.add(q, claim_id=cid, role=role)
        except Exception:
            continue
    return index


def declared_index(result: Any) -> "DeclaredQuantityIndex":
    """Index reconstruit depuis un ``result`` de run (transport v2)."""
    if not isinstance(result, Mapping):
        return DeclaredQuantityIndex()
    return DeclaredQuantityIndex.from_transport(result.get("declared_quantities"))


_BRIEF_TARGETS_CACHE48: dict = {}


def brief_declared_targets(result: Any) -> list[dict]:
    """v62.13.9.4.48 — point 4 du programme : les CIBLES DU BRIEF.

    Une grandeur déclarée prospective par un agent n'est une cible du brief que si sa valeur figure
    dans le TEXTE du brief, sur une ligne qui nomme sa métrique : la déclaration donne la structure
    (métrique, unité, période), le brief donne la provenance. Données seules — chaque consommateur
    décide : le registre type la grandeur « cible du brief » sous un cadre de cible, le juge
    indépendant applique sa propre lecture. Sans brief ou sans déclaration : liste vide, et le
    comportement antérieur s'applique (une cible reste retenue)."""
    res = result if isinstance(result, Mapping) else {}
    brief = str(((res.get("inputs") or {}).get("brief") if isinstance(res.get("inputs"), Mapping) else "")
                or res.get("brief") or "")
    if not brief.strip():
        return []
    # Coût : appelé à chaque ligne jugée (registre, mainteneur, garde, oracle). Le calcul est fait
    # UNE fois par résultat et mis en cache dans le résultat, avec son empreinte (texte du brief,
    # déclarations) ; les lignes du brief sont masquées une seule fois. Mesure du 27/09 : sans ce
    # cache, l'export du run réel 1553 passait de quelques secondes à plus de deux minutes.
    dq = res.get("declared_quantities")
    try:
        _ents = (dq or {}).get("entries") if isinstance(dq, Mapping) else None
        _fp = (hash(brief), hash(tuple((str(e.get("value")), str(e.get("metric")), str(e.get("unit")), str(e.get("period")),
                                        str(e.get("nature")), str(e.get("modality")), str(e.get("time_frame")))
                                       for e in (_ents or []) if isinstance(e, Mapping))))
    except Exception:
        _fp = None
    # Le cache vit au niveau du module (empreinte de CONTENU : texte du brief + déclarations) : les
    # appelants passent souvent un dictionnaire de contexte neuf à chaque ligne jugée.
    if _fp is not None and _fp in _BRIEF_TARGETS_CACHE48:
        return [dict(x) for x in _BRIEF_TARGETS_CACHE48[_fp]]
    idx = declared_index(res)
    out: list[dict] = []
    if idx:
        lines = []
        _in_continuity50 = False
        for l in re.split(r"[\r\n]+", brief):
            if not l.strip():
                continue
            # v62.13.9.4.50 — précision de la mention des cibles du brief (liste 9.4.49 bis, vrai run du 30/09) : n'est
            # une cible ni le BLOC DE CONTINUITÉ injecté par le produit (actions reprises « … (éch. aaaa-mm-jj) »), ni
            # l'HORIZON du brief, ni une phrase sans langage de cible, ni une ANNÉE prise pour une valeur.
            if re.match(r"(?i)\s*(?:CONTEXTE\s+[—-]\s+CoDIR\s+PR[ÉE]C[ÉE]DENT|CONTEXT\s+[—-]\s+PREVIOUS\s+CoDIR)", l):
                _in_continuity50 = True
                continue
            if _in_continuity50:
                if re.match(r"\s*(?:[•\-–—]|\d+[.)])\s", l) or re.search(r"\(\s*[ée]ch\.|\(\s*due\b", l) or l.startswith(("  ", "\t")):
                    continue
                _in_continuity50 = False
            if re.search(r"\(\s*[ée]ch\.\s*\d{4}-\d{2}-\d{2}\s*\)", l) or re.match(r"(?i)\s*horizon\s*:", l):
                continue
            if not re.search(r"(?i)\b(?:objectifs?|cibles?|targets?|maintenu[es]*|au[- ]dessus|au\s+moins|sup[ée]rieure?s?|"
                             r"croissance|growth|atteindre|reach|viser|ambition|hypoth[èe]ses?|assumptions?|≥|>)", l):
                continue
            masked = _mask_nq48(l, kinds=_NQ_NO_PERIODS48)
            lines.append((l, l.lower(), _PERIOD_RE.findall(l),
                          {_norm(m.group(0)) for m in _NUM_RE.finditer(masked)
                           if not re.fullmatch(r"(?:19|20)\d{2}", _norm(m.group(0)))}))
        seen: set = set()
        for entries in idx._by_value.values():
            for e in entries:
                if not DeclaredQuantityIndex._entry_is_prospective(e):
                    continue
                v = e["value"]
                for l, low, periods, nums in lines:
                    if v not in nums or not DeclaredQuantityIndex._entry_matches_line(e, low, periods):
                        continue
                    key = (v, _unit_family(e.get("unit") or ""), str(e.get("metric") or ""), str(e.get("period") or ""))
                    if key not in seen:
                        seen.add(key)
                        out.append({"value": v, "unit": "BRIEF_TARGET", "semantic_role": "BRIEF_TARGET",
                                    "metric": e.get("metric") or "", "unit_raw": e.get("unit") or "",
                                    "unit_family": key[1], "period": e.get("period") or "",
                                    "brief_line": l.strip()[:200]})
                    break
    if _fp is not None:
        if len(_BRIEF_TARGETS_CACHE48) >= 64:
            _BRIEF_TARGETS_CACHE48.clear()
        _BRIEF_TARGETS_CACHE48[_fp] = [dict(x) for x in out]
    return out


def brief_target_hit(line: str, raw: str, items) -> dict | None:
    """Vrai si ce nombre de la ligne est une cible du brief : même valeur, et la ligne compatible sur
    la métrique, l'unité et la période de la déclaration (même comparaison que le service)."""
    _m = _NUM_RE.search(str(raw or ""))                  # « 55 % », « 700 M$ » : la valeur seule
    v = _norm(_m.group(0)) if _m else _norm(raw)
    low = str(line or "").lower()
    periods = _PERIOD_RE.findall(str(line or ""))
    for it in items or ():
        if not isinstance(it, Mapping) or it.get("unit") != "BRIEF_TARGET" or it.get("value") != v:
            continue
        e = {"metric": it.get("metric") or "", "unit": it.get("unit_raw") or "", "period": it.get("period") or ""}
        if DeclaredQuantityIndex._entry_matches_line(e, low, periods):
            return dict(it)
    # v62.13.9.4.50 — reprise ELLIPTIQUE d'une cible du brief (échantillon du vrai CR du 30/09 : « croissance (objectif de
    # 700 M$ en FY2028) », sans le mot « chiffre d'affaires ») : même valeur, même exercice, langage de cible, et une
    # seule cible du brief porte cette valeur à cet exercice — c'est la cible du dirigeant, pas une cible d'agent.
    _OTHER_METRIC50 = (r"(?i)\b(?:ebitda|ebit|marge|margin|r[ée]sultat|income|profit|tr[ée]sorerie|cash|dette|debt|bfr|"
                       r"working\s+capital|capex|effectifs?|headcount|salari[ée]s|stocks?|inventor|cr[ée]ances|receivables|"
                       r"part\s+de\s+march[ée]|market\s+share|chiffre\s+d['’]affaires|\bca\b|revenues?|ventes|sales)")
    if re.search(r"(?i)\b(?:objectif|cible|target|atteindre|reach|viser|aim|ambition)", low):
        _cands = [it for it in (items or ()) if isinstance(it, Mapping) and it.get("unit") == "BRIEF_TARGET"
                  and it.get("value") == v and str(it.get("period") or "")
                  and str(it.get("period") or "").upper().replace(" ", "") in {("FY" + y[-4:] if not y.upper().startswith("FY") else y.upper())
                                                                                for y in periods}]
        _ur = {str(it.get("unit_raw") or "").lower() for it in _cands}
        _head50 = lambda s: " ".join(re.findall(r"[a-zà-ÿ]+", str(s or "").lower())[:2])   # « chiffre d'affaires (cible) »
        # la ligne ne doit nommer AUCUNE autre métrique que celle de la cible (« 700 M$ d'EBITDA » n'est pas la cible
        # de chiffre d'affaires du brief — contrat 9.4.48, point 4)
        # v62.13.9.4.50 — familles de métriques : « CA », « chiffre d'affaires », « revenue », « ventes » sont la même ;
        # la vérification ne porte que sur le SEGMENT de la ligne qui porte le nombre (« CA FY2028 de 700 M$ [CIBLE BRIEF],
        # marge brute supérieure à 55 % » : deux segments, deux cibles du brief)
        def _fam50(w: str) -> str:
            w = w.lower()
            if re.fullmatch(r"ca|chiffre\s+d['’]affaires|revenues?|ventes|sales", w):
                return "REVENUE"
            if re.fullmatch(r"marge|margin", w):
                return "MARGIN"
            return w
        _seg50 = low
        try:
            _pos50 = low.find(v) if v else -1
            if _pos50 >= 0:
                _a = max(low.rfind(sep, 0, _pos50) for sep in (";", "|", " ; ", ", ", "·"))
                _b_cands = [x for x in (low.find(sep, _pos50) for sep in (";", "|", ", ", "·")) if x >= 0]
                _seg50 = low[(_a + 1 if _a >= 0 else 0):(min(_b_cands) if _b_cands else len(low))]
        except Exception:
            _seg50 = low
        _named50 = {_fam50(m.group(0)) for m in re.finditer(_OTHER_METRIC50, _seg50)}
        _own50 = {_fam50(m.group(0)) for it in _cands for m in re.finditer(_OTHER_METRIC50, str(it.get("metric") or "").lower())}
        if _named50 - _own50:
            _cands = []
        if len(_cands) >= 1 and len({_head50(it.get("metric")) for it in _cands}) == 1 and (
                not any(_ur) or any(u and u.replace(" ", "") in low.replace(" ", "") for u in _ur)):
            return dict(_cands[0])
    return None


def declared_prospective_values(result: Any) -> set[str]:
    """Valeurs déclarées prospectives — compatibilité ascendante.

    ATTENTION : cette forme est SANS LOCALITÉ et ne doit plus servir à
    décider d'une retenue ; utiliser ``line_has_declared_target`` sur
    l'index, qui compare aussi métrique, période et entité.
    """
    idx = declared_index(result)
    if idx:
        return idx.prospective_values()
    payload = result.get("declared_quantities") if isinstance(result, Mapping) else None
    if isinstance(payload, Mapping):
        vals = (payload.get("prospective_values")
                or payload.get("prospective_values_sample"))
        if isinstance(vals, (list, tuple, set)):
            return {_norm(v) for v in vals if str(v).strip()}
    return set()


# =============================================================================
# v62.13.9.4.12.1 — INSTRUMENTATION DU RUN DIAGNOSTIC
# =============================================================================
#
# Le compteur natif ``declared_quantities_coverage`` compte les CLAIMS : une
# claim portant trois nombres est comptée couverte dès qu'elle possède une
# seule déclaration. Le protocole de run diagnostic exige, à juste titre, la
# couverture par OCCURRENCE NUMÉRIQUE — mesure que ce module fournit ici pour
# qu'elle n'ait pas à être recomptée à la main.
#
# Ce bloc ne participe à aucune décision de sûreté : il observe et compte.

_OCC_RE = re.compile(
    r"(?P<cur1>[€£$])?\s*(?P<num>\d[\d\s\u00A0\u202F.,]*)"
    r"\s*(?P<scale>k€|M€|Md€|bn|Md|[kKmM])?\s*(?P<cur2>€|£|\$|%)?")
# v62.13.9.4.14 — la MESURE ne doit compter que des grandeurs d'affaires.
# Le rejeu du run réel a montré que 15 des 20 occurrences réputées non
# couvertes étaient des FRAGMENTS DE DATE : les « 06 » et « 03 » de
# 06/03/2025, les « 02 » et « 09 » de 02/09/2026. L'année était exemptée,
# pas le quantième ni le mois. Un jour de calendrier n'est pas une grandeur,
# et le compter dégradait artificiellement la couverture mesurée.
# Sont également écartés les repères de période (T4 2026, Q3, S1) et les
# identifiants réglementaires (SIREN, NAF, code postal accolé à une ville).
_OCC_EXEMPT_RE = re.compile(
    r"\b[A-Za-zÀ-ÿ&]{3,}\s+\d\.0\b"                         # v62.13.9.4.27 — « industrie 4.0 » : nom de génération (contre-audit v25, C5)
    r"|\b\d{1,2}[/.\-]\d{1,2}[/.\-](?:19|20)?\d{2}\b"      # date complète
    r"|\b(?:19|20)\d{2}\b"                                   # année
    r"|\b[TQS][1-4]\b"                                        # trimestre/semestre
    r"|\bp\.\s?\d+|\bart(?:icle)?\.?\s?\d+"
    r"|\bv?\d+\.\d+(?:\.\d+)+"
    r"|\bSIREN\s*:?\s*\d[\d\s]{6,}|\bSIRET\s*:?\s*\d[\d\s]{8,}"
    r"|\b\d{2}\.?\d{2}[A-Z]\b", re.I)                        # code NAF


def audit_run_coverage(agent_outputs: Iterable[Any] | None) -> dict:
    """Mesure exigée par le protocole de run diagnostic.

    Renvoie, globalement ET par agent :
      - claims chiffrées, claims sans déclaration ;
      - occurrences numériques totales et couvertes (valeur déclarée présente
        dans la claim) ;
      - claims dont le parsing a échoué ou dont le bloc est absent ;
      - grandeurs déclarées, ventilées par nature.

    Une occurrence est « couverte » si sa valeur normalisée correspond à une
    déclaration de la MÊME claim — la localité s'apprécie donc au niveau où
    l'agent a écrit, ce qui est le seul rattachement vérifiable sans relecture.
    """
    per_agent: dict[str, dict] = {}
    for ao in (agent_outputs or ()):
        if ao is None:
            continue
        role = str(_get(ao, "role") or "inconnu")
        slot = per_agent.setdefault(role, {
            "parse_status": str(_get(ao, "parse_status") or "ABSENT"),
            "parse_errors": list(_get(ao, "parse_errors") or ())[:20],
            "claims_total": 0, "claims_with_numbers": 0,
            "claims_without_declaration": 0,
            "occurrences_total": 0, "occurrences_covered": 0,
            "declared_total": 0, "by_nature": {},
        })
        for claim in (_get(ao, "claims") or ()):
            slot["claims_total"] += 1
            text = str(_get(claim, "text") or "")
            quantities = list(_get(claim, "quantities") or ())
            declared_vals = {_norm(_get(q, "value")) for q in quantities}
            for q in quantities:
                slot["declared_total"] += 1
                nat = str(_get(q, "nature") or "?").upper()
                slot["by_nature"][nat] = slot["by_nature"].get(nat, 0) + 1
            masked = _claim_text_for_counting(text)            # v62.13.9.4.19.2
            occ = [m for m in _OCC_RE.finditer(masked)
                   if (m.group("num") or "").strip()]
            if not occ:
                continue
            slot["claims_with_numbers"] += 1
            if not quantities:
                slot["claims_without_declaration"] += 1
            for m in occ:
                slot["occurrences_total"] += 1
                if _norm(m.group("num")) in declared_vals:
                    slot["occurrences_covered"] += 1

    def _rate(num: int, den: int) -> float | None:
        return round(num / den, 4) if den else None

    total = {k: 0 for k in ("claims_total", "claims_with_numbers",
                            "claims_without_declaration", "occurrences_total",
                            "occurrences_covered", "declared_total")}
    natures: dict[str, int] = {}
    for slot in per_agent.values():
        for k in total:
            total[k] += slot[k]
        for n, c in slot["by_nature"].items():
            natures[n] = natures.get(n, 0) + c
        slot["couverture_claim"] = _rate(
            slot["claims_with_numbers"] - slot["claims_without_declaration"],
            slot["claims_with_numbers"])
        slot["couverture_occurrence"] = _rate(
            slot["occurrences_covered"], slot["occurrences_total"])

    return {
        "version": "run-coverage-v1",
        "global": {
            **total,
            "by_nature": natures,
            "couverture_claim": _rate(
                total["claims_with_numbers"] - total["claims_without_declaration"],
                total["claims_with_numbers"]),
            "couverture_occurrence": _rate(
                total["occurrences_covered"], total["occurrences_total"]),
        },
        "par_agent": per_agent,
        "agents_muets": sorted(r for r, s in per_agent.items()
                               if s["parse_status"] in ("MISSING", "ABSENT")
                               or s["declared_total"] == 0),
    }


def review_shortlist(agent_outputs: Iterable[Any] | None) -> list[dict]:
    """Pré-tri des grandeurs à relire à la main (protocole §4).

    Le protocole demande au moins trente relectures. On les priorise au lieu
    de les tirer au hasard : les ERREURS CRITIQUES d'abord — une grandeur
    prospective déclarée FAIT peut traverser toute la chaîne, alors qu'un
    fait déclaré CIBLE ne produit qu'une sur-rétention.
    """
    _PROSPECTIVE_HINT = re.compile(
        r"\b(?:objectif|cible|vise|viser|ambition|plan|strat[ée]gie|"
        r"d['\u2019]ici|horizon|futur|target|goal|aim|by\s+20\d{2}|"
        r"will|shall|sera|seront|pr[ée]voi|souhait)\w*", re.I)
    _PAST_HINT = re.compile(
        r"\b(?:[ée]tait|[ée]taient|a\s+atteint|s['\u2019][ée]levait|"
        r"constat[ée]|r[ée]alis[ée]|was|were|reached|stood\s+at|"
        r"recorded|posted|in\s+(?:19|20)\d{2})\w*", re.I)
    out: list[dict] = []
    for ao in (agent_outputs or ()):
        if ao is None:
            continue
        role = str(_get(ao, "role") or "inconnu")
        for claim in (_get(ao, "claims") or ()):
            text = str(_get(claim, "text") or "")
            for q in (_get(claim, "quantities") or ()):
                nature = str(_get(q, "nature") or "").upper()
                prosp = bool(_PROSPECTIVE_HINT.search(text))
                past = bool(_PAST_HINT.search(text))
                priority, why = None, None
                if nature == "FAIT" and prosp and not past:
                    priority, why = 1, "prospectif déclaré FAIT (erreur critique)"
                elif nature in {"CIBLE", "OPTION", "SCENARIO"} and past and not prosp:
                    priority, why = 2, "historique déclaré prospectif (sur-rétention)"
                elif nature == "APPAREIL":
                    priority, why = 3, "déclaré APPAREIL — vérifier que c'est bien une mesure de l'outil"
                # v62.13.9.4.16 — contre-audit P1-08 : la shortlist était vide
                # avec 10 MALFORMED. Toute déclaration MALFORMED est une ligne
                # de revue, localisée (rôle, claim, valeur, texte).
                elif nature == "MALFORMED" or str(_get(q, "modality") or "").upper() == "MALFORMED" \
                        or str(_get(q, "time_frame") or "").upper() == "MALFORMED":
                    priority, why = 1, "déclaration MALFORMED (nature/modalité/horizon hors contrat) — à requalifier"
                elif _get(q, "nature_raw") and str(_get(q, "nature_raw")) != "BACKFILL":
                    priority, why = 3, f"nature « {_get(q, 'nature_raw')} » rangée en {nature} — confirmer"
                if priority:
                    out.append({
                        "priority": priority, "why": why, "role": role,
                        "claim_id": str(_get(claim, "id") or ""),
                        "value": str(_get(q, "value") or ""),
                        "nature": nature,
                        "modality": str(_get(q, "modality") or ""),
                        "metric": str(_get(q, "metric") or ""),
                        "text": text[:220],
                    })
    # v62.13.9.4.16 — claims chiffrées SANS déclaration : une ligne chacune.
    for ao in (agent_outputs or ()):
        if ao is None:
            continue
        role = str(_get(ao, "role") or "inconnu")
        for claim in (_get(ao, "claims") or ()):
            text = str(_get(claim, "text") or "")
            # v62.13.9.4.19.5 — même masque que le comptage : une échéance
            # (« avant 2026-09-30 ») n'est pas une claim chiffrée non déclarée.
            if _OCC_RE.search(_claim_text_for_counting(text)) and not (_get(claim, "quantities") or ()):
                out.append({
                    "priority": 1, "why": "claim chiffrée sans aucune déclaration — à déclarer ou à retirer",
                    "role": role, "claim_id": str(_get(claim, "id") or ""),
                    "value": "", "nature": "", "modality": "", "metric": "",
                    "text": text[:220],
                })
    out.sort(key=lambda x: (x["priority"], x["role"]))
    return out


def review_shortlist_from_gate(gate: Mapping[str, Any] | None,
                               audit: Mapping[str, Any] | None) -> list[dict]:
    """v62.13.9.4.16 — lignes de revue issues de la porte : agent sous seuil,
    agent muet, gap narratif. Complète ``review_shortlist`` (grandeurs)."""
    out: list[dict] = []
    per = ((audit or {}).get("par_agent") or {}) if isinstance(audit, Mapping) else {}
    for role, s in per.items():
        if not isinstance(s, Mapping):
            continue
        tot = int(s.get("occurrences_total") or 0)
        cov = int(s.get("occurrences_covered") or 0)
        if tot and cov / tot < 0.95:
            out.append({"priority": 2, "role": role, "claim_id": "", "value": "", "nature": "",
                        "modality": "", "metric": "",
                        "why": f"agent sous seuil : {cov}/{tot} occurrences couvertes ({cov / tot:.0%})",
                        "text": ""})
    for role in ((gate or {}).get("agents_muets") or ()):
        out.append({"priority": 1, "role": str(role), "claim_id": "", "value": "", "nature": "",
                    "modality": "", "metric": "", "why": "agent muet — aucune déclaration", "text": ""})
    ng = (gate or {}).get("reprise_narrative")
    if ng is not None and ng < 0.95:
        out.append({"priority": 2, "role": "narrative", "claim_id": "", "value": "", "nature": "",
                    "modality": "", "metric": "",
                    "why": f"reprise narrative {ng:.1%} < 95 % — valeurs de la prose hors déclarations",
                    "text": ""})
    out.sort(key=lambda x: (x["priority"], x["role"]))
    return out


# v62.13.9.4.18 — BRUIT DE NARRATIVE : numérotation de titres et de listes
# (« ## 3.1 », « 2. », « 1.1. »), plages de dates « 03/09 – 17/09/2026 »,
# codes postaux, numéros de rangée — ce ne sont pas des grandeurs d'affaires
# et ils gonflaient les « valeurs orphelines » (« 1. », « 09 », « 35310 »).
_NARRATIVE_NOISE_RE = re.compile(
    r"^\s*#{1,6}\s*\d{1,2}(?:\.\d{1,2}){0,3}\.?\s+"            # titres markdown numérotés
    r"|^\s*(?:[-*•▌]\s*)?\d{1,3}(?:\.\d{1,2}){0,3}[.)]\s+"       # listes / sections numérotées
    r"|^\s*\|?\s*\d{1,3}\s*\|"                                 # numéro de rangée
    r"|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?(?:\s*[–\-—]\s*\d{1,2}/\d{1,2}(?:/\d{2,4})?)?\b"   # dates jj/mm
    r"|\b\d{5}\s+[A-ZÀ-Ÿ][a-zà-ÿ]+"                              # code postal + ville
    r"|\b(?:semaines?|weeks?|jours?|days?)\s+\d{1,2}(?:\s*[–\-]\s*\d{1,2})?\b"   # index de semaine
    r"|\b\d{1,2}(?:\.\d{1,2}){1,3}\b(?=\s*[A-ZÀ-Ÿ])"           # renvoi de section « 3.1 Titre »
    r"|\bT[1-4]\s+20\d{2}\b|\bQ[1-4]\s+20\d{2}\b"               # trimestres
    # v62.13.9.4.19 — renvois de section en milieu de phrase (« voir 2.1 »,
    # « §3.2 », « section 4.1 », « (3.) »), jours de dates (« le 31 octobre »,
    # « 12 septembre 2026 », « du 3 au 17 septembre »), heures (« 14h »),
    # dates ISO complètes : la moitié des orphelines des runs 14:50 et 15:53.
    r"|(?:§|\bsection|\bvoir|\bcf\.?|\bpoint|\bchapitre|\bpartie|\baxe|\baction)\s*\d{1,2}(?:\.\d{1,2}){0,3}\.?"
    r"|\(\s*\d{1,2}(?:\.\d{1,2}){0,3}\.?\s*\)"
    r"|\b\d{1,2}(?:\.\d{1,2}){1,3}\.?(?=\s|$|[,;:)])(?!\s*(?:%|€|k€|M€|Md€|\$|£|pts?|points|jours?|mois|ans?|h\b))"
    r"|\b(?:le|du|au|dès le|avant le|d['’]ici le|depuis le|jusqu['’]au|vers le|the|by|on|from|until)\s+\d{1,2}(?:er)?\s+(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre|january|february|march|april|may|june|july|august|september|october|november|december)\b"
    r"|\b\d{1,2}(?:er)?\s+(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre)(?:\s+20\d{2})?\b"
    r"|\b20\d{2}-\d{2}-\d{2}\b|\b\d{2}/\d{2}/20\d{2}\b"
    r"|\b\d{1,2}\s?h(?:\d{2})?\b(?!\s*/)"
    r"|\*\*\d{1,2}(?:\.\d{1,2}){1,3}\*\*"                          # « **1.3** » numéro d'action en gras
    r"|^\s*\|?\s*\*{0,2}\d{1,3}(?:\.\d{1,2}){0,3}\*{0,2}\s*(?=\|)"    # numéro de rangée, gras compris
    r"|\bJ\s*[+\-]\s*\d{1,3}\b|\bD\s*[+\-]\s*\d{1,3}\b"              # J+7, D+30 : jalons relatifs
    r"|\b(?:du|from)\s+\d{1,2}(?:er)?\s+(?:au|to)\s+\d{1,2}(?:er)?\s+(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre|january|february|march|april|may|june|july|august|september|october|november|december)\b"
    r"|https?://\S+|www\.\S+"                                          # URL (années, mois, identifiants)
    r"|\(\s*\d{5}\s*\)|\b\d{5}\s+[A-ZÀ-Ÿ]"                             # code postal « Mordelles (35310) »
    r"|(?<=\|)\s*\*{0,2}\d{1,2}[.)]\s+"                                   # v62.13.9.4.22 — numéro de liste en tête de cellule « | 1. Cartographier »
    r"|\b(?:max\.?|maximum|min\.?|minimum)\s+\d{1,4}\s*(?:car\.?|caract[èe]res?|chars?|mots?|words?|lignes?|lines?)\b"   # contrainte de format « max 65 car. »
    r"|\b\d{1,4}\s*(?:car\.?|caract[èe]res?|chars?)\s*(?:max|maximum)?\b",
    re.I | re.M)


def _clean_narrative(text: str) -> str:
    return _OCC_EXEMPT_RE.sub(" ", _NARRATIVE_NOISE_RE.sub(" ", str(text or "")))


_CLAIM_NOISE_RE = re.compile(
    r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/(?:19|20)\d{2}\b"   # dates ISO / jj/mm/aaaa
    r"|(?<=\d)\s*/\s*100\b"                                                  # « 35/100 » : dénominateur de score
    r"|\b\d+\s*:\s*1\b"                                                    # « 20:1 » : ratio
    r"|\b(?:le|du|au|d['’]ici le|avant le|dès le)\s+\d{1,2}(?:er)?\s+(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre)\b",
    re.I)


def _claim_text_for_counting(text: str) -> str:
    """v62.13.9.4.19.2 — le comptage de couverture ne lit pas les dates ISO
    (« 2026-09-10 » → « 10 »), les dénominateurs de score (« 35/100 ») ni les
    ratios (« 20:1 ») comme des occurrences à déclarer (run réel 20:23)."""
    return _OCC_EXEMPT_RE.sub(" ", _CLAIM_NOISE_RE.sub(" ", str(text or "")))


_PRIMARY_ROLES = ("strategie", "brief_codir", "marketing", "finance", "commercial",
                  "supply_chain", "synthese_decisions", "dg")


def _declared_values_of(agent_output) -> set[str]:
    """Valeurs déclarées par la SORTIE FINALE d'un agent (claims + quantités),
    quel que soit le chemin qui les a produites : bloc primaire, retry par
    chunks, complément narratif."""
    declared: set[str] = set()
    for claim in (_get(agent_output, "claims") or ()):
        for q in (_get(claim, "quantities") or ()):
            v = str(_get(q, "value") or "").strip()
            if v:
                declared.add(_norm(v))
        for m in _OCC_RE.finditer(_OCC_EXEMPT_RE.sub(" ", str(_get(claim, "text") or ""))):
            if (m.group("num") or "").strip():
                declared.add(_norm(m.group("num")))
    return declared


def claim_level_uncovered(agent_output) -> list[str]:
    """v62.13.9.4.19 — nombres présents dans le texte d'une claim et absents de
    ses quantités : c'est ce que compte la couverture par occurrence, et ce
    que le complément doit viser aussi (Finance : 119/161 au run 15:53)."""
    out: list[str] = []
    for claim in (_get(agent_output, "claims") or ()):
        declared = {_norm(str(_get(q, "value") or "")) for q in (_get(claim, "quantities") or ())}
        for m in _OCC_RE.finditer(_claim_text_for_counting(str(_get(claim, "text") or ""))):
            v = _norm(m.group("num")) if (m.group("num") or "").strip() else ""
            if v and v not in declared and v not in out:
                out.append(v)
    return out


def backfill_claim_quantities(agent_output) -> int:
    """v62.13.9.4.19.1 — TRANSFERT DE DÉCLARATION AU SEIN D'UN MÊME RÔLE.
    Le complément (9.4.18/19) déclare une valeur dans une NOUVELLE claim ;
    l'ancienne claim qui porte le même nombre dans son texte reste « sans
    déclaration » pour la couverture par occurrence (run 19:23 : 574/696,
    14 claims sans déclaration, alors que la reprise narrative est à 99 %).
    Une valeur déclarée par le générateur — même rôle, même run, avec sa
    nature, sa modalité et son horizon — est recopiée sur les claims du rôle
    qui la citent sans la déclarer. Rien n'est inventé : la déclaration est
    celle de l'agent, l'index la rattache à chaque claim qui la porte.
    Renvoie le nombre de quantités recopiées."""
    import copy as _copy
    claims = list(_get(agent_output, "claims") or ())
    by_value: dict[str, Any] = {}
    for claim in claims:
        for q in (_get(claim, "quantities") or ()):
            v = _norm(str(_get(q, "value") or ""))
            if v and v not in by_value and str(_get(q, "nature") or "") != "MALFORMED":
                by_value[v] = q
    added = 0
    _prospective_tag = re.compile(r"HYPOTH|CIBLE|OPTION|SCENARIO|ESTIM|INCERTAIN", re.I)
    _prospective_txt = re.compile(r"\b(?:cible|objectif|d['’]ici|horizon|viser|atteindre|serait|devrait|"
                                  r"scénario|hypoth[èe]se|projet[ée]|target|goal|would|should|by\s+20)\b", re.I)
    for claim in claims:
        declared = {_norm(str(_get(q, "value") or "")) for q in (_get(claim, "quantities") or ())}
        tag = str(_get(claim, "tag") or "")
        text = str(_get(claim, "text") or "")
        claim_prospective = bool(_prospective_tag.search(tag)) or bool(_prospective_txt.search(text))
        for m in _OCC_RE.finditer(_claim_text_for_counting(text)):
            v = _norm(m.group("num")) if (m.group("num") or "").strip() else ""
            if v and v not in declared and v in by_value:
                # v62.13.9.4.19.2 — rattachement PRUDENT : un FAIT n'est jamais
                # recopié dans une claim prospective (« 800 € » médiane citée
                # dans « TJM cible 1 050 € vs 800 € » devenait un FAIT
                # démenti par sa modalité), et une valeur à 1-2 chiffres sans
                # unité (« 10 » d'une date, « 3 ») n'est pas rattachée.
                src_nature = str(_get(by_value[v], "nature") or "")
                if claim_prospective and src_nature == "FAIT":
                    continue
                if len(re.sub(r"\D", "", v)) <= 2 and not str(_get(by_value[v], "unit") or "").strip():
                    # une petite valeur n'est rattachée que si, dans CETTE claim,
                    # elle est suivie d'une unité ou d'un nom (« 12 mois »,
                    # « 31 % », « 5 RDV ») — pas « au 2026-10-10 » ni « J+3 ».
                    if not re.search(r"(?<![\d.,/-])" + re.escape(m.group("num")) + r"\s?(?:%|€|k€|M€|Md€|[A-Za-zÀ-ÿ]{2,})", text):
                        continue
                try:
                    q = _copy.copy(by_value[v])
                    try:
                        q.decided_by = getattr(q, "decided_by", None)
                        q.nature_raw = "BACKFILL"          # tracé : rattachement, pas nouvelle déclaration
                    except Exception:
                        pass
                    qs = _get(claim, "quantities")
                    if isinstance(qs, list):
                        qs.append(q)
                    else:
                        claim.quantities = list(qs or ()) + [q]
                    declared.add(v); added += 1
                except Exception:
                    continue
    return added


def narrative_orphans(agent_txt: str, agent_output) -> tuple[list[str], float | None]:
    """v62.13.9.4.18 — valeurs de la narrative (hors bloc AGENT_JSON) sans
    déclaration dans la sortie finale de l'agent, et taux de reprise."""
    raw = str(agent_txt or "")
    narrative = re.sub(r"-{2,}\s*AGENT_JSON_START\s*-{2,}.*?-{2,}\s*AGENT_JSON_END\s*-{2,}", " ", raw, flags=re.S | re.I)
    narrative = _clean_narrative(narrative)
    in_narrative: set[str] = set()
    for m in _OCC_RE.finditer(narrative):
        if (m.group("num") or "").strip():
            in_narrative.add(_norm(m.group("num")))
    declared = _declared_values_of(agent_output)
    orphans = sorted(v for v in in_narrative - declared if v)
    reprise = (round((len(in_narrative) - len(orphans)) / len(in_narrative), 4) if in_narrative else None)
    return orphans, reprise


def audit_narrative_gap(archive: Iterable[Any] | None, agent_outputs: Iterable[Any] | None = None) -> dict:
    """v62.13.9.4.12.2 — mesure §3 du protocole de run diagnostic.

    Recense les nombres présents dans la NARRATIVE BRUTE d'un agent qui ne
    sont repris dans aucune claim structurée. C'est une zone que le compteur
    de couverture ne voit pas : une claim peut être parfaitement déclarée
    alors que la moitié des chiffres du texte n'a jamais donné lieu à une
    claim. Sans cette mesure, la couverture peut paraître excellente sur un
    périmètre étroit.

    La narrative est prise hors bloc AGENT_JSON — on compare ce que l'agent
    a ÉCRIT à ce qu'il a DÉCLARÉ.
    """
    per_agent: dict[str, dict] = {}
    # v62.13.9.4.18 — la mesure crédite la SORTIE FINALE de chaque agent
    # (bloc primaire + retry par chunks + complément), pas seulement le bloc
    # du premier appel ; les entrées d'archive « *_retry » ne sont pas des
    # agents.
    outputs_by_role: dict[str, Any] = {}
    for ao in (agent_outputs or ()):
        if ao is not None:
            outputs_by_role[str(_get(ao, "role") or "")] = ao
    for entry in (archive or ()):
        if not isinstance(entry, Mapping):
            continue
        role = str(entry.get("role") or "inconnu")
        if role not in _PRIMARY_ROLES:
            continue
        raw = str(entry.get("raw_output") or "")
        block = str(entry.get("agent_json_block") or "")
        narrative = raw.replace(block, " ") if block else raw
        narrative = _clean_narrative(narrative)
        in_narrative: set[str] = set()
        for m in _OCC_RE.finditer(narrative):
            if (m.group("num") or "").strip():
                in_narrative.add(_norm(m.group("num")))
        declared: set[str] = set()
        for m in _OCC_RE.finditer(block):
            if (m.group("num") or "").strip():
                declared.add(_norm(m.group("num")))
        if role in outputs_by_role:
            declared |= _declared_values_of(outputs_by_role[role])
        orphans = sorted(v for v in in_narrative - declared if v)
        slot = per_agent.setdefault(role, {})
        slot.update({
            "narrative_values": len(in_narrative),
            "declared_values": len(declared),
            "orphan_values": orphans[:80],
            "orphan_count": len(orphans),
            "taux_reprise": (round((len(in_narrative) - len(orphans))
                                   / len(in_narrative), 4)
                             if in_narrative else None),
        })
    total_nar = sum(s["narrative_values"] for s in per_agent.values())
    total_orph = sum(s["orphan_count"] for s in per_agent.values())
    return {
        "version": "narrative-gap-v1",
        "global": {
            "narrative_values": total_nar,
            "orphan_count": total_orph,
            "taux_reprise": (round((total_nar - total_orph) / total_nar, 4)
                             if total_nar else None),
        },
        "par_agent": per_agent,
    }


def a1_longitudinal(result: Any, *, out_dir: str | None = None, limit: int = 12) -> dict:
    """v62.13.9.4.16 — STABILITÉ INTER-RUNS (contre-audit P1-02 / point 4).
    « Stabilité du run : 100/100 » mesurait l'exécution isolée ; la
    reproductibilité sémantique se lit sur la SÉRIE des dossiers de run de la
    même entité (répertoire ``outputs``, ou ``CODIR_RUN_DOSSIER_DIR``).
    Renvoie la série (couverture, MALFORMED, qualifiable), la moyenne,
    l'amplitude et le nombre de runs qualifiés — le run courant inclus."""
    import glob as _glob
    import json as _json
    import os as _os
    res = result if isinstance(result, Mapping) else {}
    cur_audit = ((res.get("run_coverage_audit") or {}).get("global") or {})
    cur_gate = res.get("a1_qualification_gate") or {}
    cp = res.get("company_profile") or {}
    key = str(cp.get("company_number") or cp.get("name") or
              (res.get("inputs") or {}).get("company") or "").strip().lower()
    series: list[dict] = []
    target = out_dir or _os.environ.get("CODIR_RUN_DOSSIER_DIR") or "outputs"
    try:
        files = sorted(_glob.glob(_os.path.join(target, "diagnostic_A1_RUN-*.json")))[-limit:]
    except Exception:
        files = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                d = _json.load(fh)
            r = d.get("result") if isinstance(d.get("result"), Mapping) else d
            pcp = r.get("company_profile") or {}
            pkey = str(pcp.get("company_number") or pcp.get("name") or
                       (r.get("inputs") or {}).get("company") or "").strip().lower()
            if key and pkey and pkey != key:
                continue
            g = ((r.get("run_coverage_audit") or {}).get("global") or {})
            gate = r.get("a1_qualification_gate") or {}
            if g.get("couverture_occurrence") is None:
                continue
            series.append({
                "run_id": str(d.get("run_id") or _os.path.basename(f)),
                "build": str(d.get("build_version") or ""),
                "couverture_occurrence": float(g.get("couverture_occurrence")),
                # v62.13.9.4.27 — contre-audit v25 (§1) : l'historique affichait 0
                # MALFORMED quand la gate en comptait 1 (champ temporel invalide
                # d'une déclaration finale). Le compteur descriptif est celui de
                # la gate, jamais un sous-compteur.
                "malformed": int(gate.get("malformed") if gate.get("malformed") is not None
                                 else (g.get("by_nature") or {}).get("MALFORMED") or 0),
                "a1_qualifiable": bool(gate.get("a1_qualifiable")),
            })
        except Exception:
            continue
    if cur_audit.get("couverture_occurrence") is not None:
        cur_id = str(res.get("run_id") or "")
        if not any(s["run_id"] == cur_id for s in series):
            series.append({
                "run_id": cur_id or "(courant)",
                "build": str(res.get("build_version") or ""),
                "couverture_occurrence": float(cur_audit.get("couverture_occurrence")),
                "malformed": int(cur_gate.get("malformed") if cur_gate.get("malformed") is not None
                                 else (cur_audit.get("by_nature") or {}).get("MALFORMED") or 0),
                "a1_qualifiable": bool(cur_gate.get("a1_qualifiable")),
            })
    covs = [s["couverture_occurrence"] for s in series]
    n = len(covs)
    return {
        "version": "a1-longitudinal-v1",
        "runs": n,
        "series": series,
        "mean_coverage": (round(sum(covs) / n, 4) if n else None),
        "amplitude": (round(max(covs) - min(covs), 4) if n else None),
        "qualified_runs": sum(1 for s in series if s["a1_qualifiable"]),
        "stable": bool(n >= 5 and all(s["a1_qualifiable"] for s in series[-5:])
                       and (max(covs[-5:]) - min(covs[-5:])) <= 0.05),
        "note": ("la stabilité produit se lit sur cinq runs consécutifs qualifiés, "
                 "amplitude ≤ 5 points ; un run isolé ne la mesure pas"),
    }


def export_run_dossier(result: Any, *, out_dir: str | None = None) -> dict:
    """v62.13.9.4.12.3 — EXPORT DU DOSSIER DE RUN, brut et entier.

    Le contre-audit du 1er septembre 2026 relève un paradoxe réel : la version
    produit la mesure et ne la livre pas. Les pièces vivaient dans l'objet
    ``result``, en mémoire, et disparaissaient au rafraîchissement de la page.

    Choix délibéré : on sérialise le ``result`` COMPLET, sans consolidation ni
    format normalisé. Un dossier brut se ré-analyse ; un dossier absent, non.
    Consolider maintenant reviendrait à écrire encore du code de contrôle
    avant d'avoir la moindre donnée réelle — c'est l'inverse de ce qu'il faut
    faire. Les regroupements par agent, l'archivage des retries et le format
    normalisé de Finance seront traités, si nécessaire, à la lumière de ce que
    ce premier run montrera.

    Renvoie un descripteur : chemin, taille, SHA-256, et présence des pièces
    attendues — pour qu'un contrôle immédiat soit possible sans rouvrir le
    fichier.
    """
    import datetime as _dt
    import hashlib as _hl
    import json as _json
    import os as _os

    payload = result if isinstance(result, Mapping) else {"result": str(result)}
    # NB : ``run_id`` peut être un DICTIONNAIRE dans le résultat (contexte
    # d'analyse enrichi) — on n'en tire un identifiant que si c'est une
    # chaîne, sinon on retombe sur l'horodatage. Un nom de fichier construit
    # à partir d'un dict est invalide et fait échouer l'écriture en silence.
    def _as_id(v):
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, Mapping):
            inner = v.get("run_id")
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
        return None

    run_id = (_as_id(payload.get("run_fingerprint"))
              or _as_id(payload.get("run_id"))
              or _dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
    run_id = re.sub(r"[^A-Za-z0-9._-]", "-", run_id)[:60]
    stamp = _dt.datetime.now().isoformat(timespec="seconds")

    try:
        from version import BUILD_VERSION as _bv
    except Exception:
        _bv = "inconnu"

    expected = ("declared_quantities", "declared_quantities_coverage",
                "run_coverage_audit", "run_review_shortlist",
                "run_agent_raw_archive", "run_narrative_gap",
                "diagnostics_attempts", "meta")
    dossier = {
        "dossier_version": "run-dossier-v1",
        "build_version": _bv,
        "run_id": run_id,
        "exported_at": stamp,
        "pieces_presentes": {k: (k in payload) for k in expected},
        "result": payload,
    }

    body = _json.dumps(dossier, ensure_ascii=False, indent=2, default=str)
    raw = body.encode("utf-8")
    name = f"diagnostic_A1_{run_id}.json".replace("/", "-").replace(" ", "_")

    written = None
    target = out_dir or _os.environ.get("CODIR_RUN_DOSSIER_DIR") or "outputs"
    try:
        _os.makedirs(target, exist_ok=True)
        path = _os.path.join(target, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        written = path
    except Exception:
        written = None

    return {
        "file_name": name,
        "path": written,
        "bytes": len(raw),
        "sha256": _hl.sha256(raw).hexdigest(),
        "pieces_presentes": dossier["pieces_presentes"],
        "pieces_manquantes": sorted(k for k, v in dossier["pieces_presentes"].items() if not v),
        "payload": body,
    }


def a1_qualification_gate(result: Any) -> dict:
    """v62.13.9.4.13 — PORTE DE QUALIFICATION A1.

    Le run du 02/09/2026 affichait ``run_validatable = true`` alors que le
    canal A1 était à 63 % de couverture, deux agents muets et 21 déclarations
    incohérentes. Le mot rassurait à tort : un run peut s'exécuter
    correctement et n'être pas qualifiable.

    Cette porte sépare les concepts et n'autorise aucun arrondi favorable.
    Elle ne bloque pas l'export — la chaîne de sûreté textuelle reste le
    socle — mais elle interdit de déclarer A1 qualifié tant que les seuils du
    protocole ne sont pas atteints.
    """
    res = result if isinstance(result, Mapping) else {}
    audit = res.get("run_coverage_audit") or {}
    g = audit.get("global") or {}
    per = audit.get("par_agent") or {}

    occ = g.get("couverture_occurrence")
    missing = int(g.get("claims_without_declaration") or 0)
    mute = list(audit.get("agents_muets") or ())
    malformed = int((g.get("by_nature") or {}).get("MALFORMED") or 0)
    # v62.13.9.4.22 — contre-audit v21 (§4.2) : la porte publiait « 0 MALFORMED »
    # alors que 13 déclarations exportées avaient une MODALITÉ malformée. Le
    # comptage se fait sur l'état final exporté — nature, modalité ou horizon.
    try:
        _dq = res.get("declared_quantities")
        _entries = (_dq.get("entries") if isinstance(_dq, Mapping) else _dq) or []
        _mal_final = sum(1 for e in _entries if isinstance(e, Mapping) and "MALFORMED" in (
            str(e.get("nature") or ""), str(e.get("modality") or ""), str(e.get("time_frame") or "")))
        malformed = max(malformed, _mal_final)
    except Exception:
        pass

    # contradiction interne : une nature FAIT démentie par sa modalité
    contradictions = 0
    for e in ((res.get("declared_quantities") or {}).get("entries") or ()):
        if not isinstance(e, Mapping):
            continue
        if (e.get("nature") == "FAIT"
                and e.get("modality") in ("RECOMMANDE", "HYPOTHETIQUE",
                                          "SOUHAITE", "DECIDE")):
            contradictions += 1

    reasons: list[str] = []
    if occ is None:
        reasons.append("couverture par occurrence non mesurée")
    elif occ < 0.95:
        reasons.append(f"couverture par occurrence {occ:.1%} < 95 %")
    if missing:
        reasons.append(f"{missing} claim(s) chiffrée(s) sans déclaration")
    if mute:
        reasons.append("agent(s) muet(s) : " + ", ".join(sorted(mute)))
    if contradictions:
        reasons.append(f"{contradictions} déclaration(s) FAIT démentie(s) "
                       "par leur modalité")
    if malformed:
        reasons.append(f"{malformed} déclaration(s) MALFORMED")
    for role, s in per.items():
        if str(s.get("parse_status") or "") in ("MISSING", "PARTIAL", "ABSENT"):
            reasons.append(f"{role} : parse_status {s.get('parse_status')}")
    # v62.13.9.4.16 — contre-audit P1-01 : la porte ne jugeait que les
    # claims structurées ; la NARRATIVE réellement redistribuée au document
    # restait hors décision (23 % de reprise au run 09:55 contre 94 % sur les
    # claims). Le gap narratif est désormais une condition explicite.
    ng = res.get("run_narrative_gap") or {}
    ng_g = ng.get("global") if isinstance(ng, Mapping) else None
    reprise = None
    if isinstance(ng_g, Mapping) and ng_g.get("taux_reprise") is not None:
        try:
            reprise = float(ng_g.get("taux_reprise"))
        except (TypeError, ValueError):
            reprise = None
    if reprise is None:
        reasons.append("reprise narrative non mesurée")
    elif reprise < 0.95:
        reasons.append(f"reprise narrative {reprise:.1%} < 95 % "
                       f"({int(ng_g.get('orphan_count') or 0)} valeur(s) de la prose hors déclarations)")

    return {
        "version": "a1-gate-v2",
        "a1_qualifiable": not reasons,
        "couverture_occurrence": occ,
        "reprise_narrative": reprise,
        "contradictions_nature_modalite": contradictions,
        "malformed": malformed,
        "agents_muets": sorted(mute),
        "raisons": reasons,
    }
