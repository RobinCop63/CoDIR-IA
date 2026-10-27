"""
patches/brief_facts.py — M6-B B.1.3

Faits financiers du BRIEF → couche de preuve (audit dossier anglophone coté, bloquant n°2).

Le contrat B.1 (cas 6, brief-only) : un chiffre annoncé dans le brief doit
produire un fait VISIBLE, STRUCTURÉ (métrique canonique, valeur normalisée,
devise, période), TRAÇABLE (source = brief), et JAMAIS board-safe — au lieu
d'être utilisé partout dans l'analyse tout en restant absent de la table de
preuve (« Revenue missing » alors que le brief dit GBP 2.46bn).

Extraction volontairement CONSERVATRICE :
  · une ligne n'est retenue que si elle porte un mot-clé métrique reconnu
    ET une valeur que parse_value sait normaliser ;
  · pour les métriques monétaires, la DEVISE doit être explicite (€, £, $,
    GBP, EUR…) — un « 2 383 m » nu n'entre jamais (le « m » ambigu) ;
  · les lignes de QUESTIONS / horizons sont ignorées ;
  · plafond de faits pour éviter le bruit.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional

from patches.fact_identity import (
    parse_value, extract_marked_period, canonical_metric_id,
)

# (regex mot-clé, libellé FR, libellé EN, id canonique attendu, monétaire?)
_METRIC_PATTERNS = (
    (r"\bchiffre\s+d[' ]affaires\b|\bCA\b|\brevenue?s?\b|\bsales\b",
     "Chiffre d'affaires", "Revenue", "REVENUE", True),
    (r"\brésultat\s+net\b|\bnet\s+income\b|\bnet\s+profit\b|\bRN\b",
     "Résultat net", "Net income", "NET_INCOME", True),
    (r"\b(?:adjusted\s+)?operating\s+profit\b|\brésultat\s+opérationnel\b|\bEBIT\b",
     "Résultat opérationnel", "Operating profit", "", True),
    (r"\bEBITDA\b", "EBITDA", "EBITDA", "EBITDA", True),
    (r"\bdette\s+nette\b|\bnet\s+debt\b", "Dette nette", "Net debt",
     "NET_DEBT", True),
    (r"\btr[ée]sorerie\b|\bcash\b(?!\s*-?\s*flow)", "Trésorerie", "Cash",
     "", True),
    (r"\bmarge\s+brute\b|\bgross\s+margin\b", "Marge brute", "Gross margin",
     "", False),
    (r"\bmarge\s+op[ée]rationnelle\b|\boperating\s+margin\b",
     "Marge opérationnelle", "Operating margin", "", False),
    (r"\beffectifs?\b|\bheadcount\b|\bcollaborateurs\b|\bsalari[ée]s\b|\bemployees\b",
     "Effectif", "Headcount", "HEADCOUNT", False),
    (r"\b[ée]conomies?\b|\bsavings\b|\bcost\s+reduction\b",
     "Économies annoncées", "Announced savings", "", True),
)

_SKIP_LINE = re.compile(
    r"^\s*(?:Q\d\s*\[|QUESTIONS?\b|HORIZON\b|Horizon\s*:|▌|═|╔|║|╚)",
    re.IGNORECASE)

_MAX_FACTS = 8

_SENTENCE_BOUNDARY_RE = re.compile(r"(?<!\d)[.;](?!\d)|\n")


def _current_clause(text: str) -> str:
    """Retourne le fragment avant la prochaine frontière de phrase.

    B.1.3.3-chatGPT candidate : un brief peut être collé en paragraphes
    longs. L'extraction d'une valeur après une métrique ne doit pas traverser
    la phrase suivante (« savings. H1 FY26 revenue GBP 1.03bn »), sinon le
    fait savings peut voler le chiffre de revenue. Les points décimaux
    restent autorisés grâce aux lookarounds digit.

    B.1.3.4 — INTÉGRATION (protocole hybride, 3e application) : candidat
    ChatGPT (B1.3.3→candidate), les DEUX sous-constats REPRODUITS sur la
    source officielle : vol inter-phrases (savings volait GBP 1.03bn au
    revenue de la phrase suivante, période FY2026 comprise, en écrasant son
    GBP 100m légitime) + période non locale (Operating profit héritait du
    FY25 de la première phrase). Post-patch : sondes Claude vertes —
    décimales « 2.46 » préservées malgré la borne sur '.', point-virgule,
    frontière inverse, non-régression B.1.3.2/B.1.3.3 intégrale. Suite
    complète 2378 exécutée côté Claude.
    """
    m = _SENTENCE_BOUNDARY_RE.search(text or "")
    return (text or "")[:m.start()] if m else (text or "")


def _metric_sentence_context(line: str, metric_start: int, metric_end: int) -> str:
    """Contexte local de période autour d'une métrique, borné à la phrase.

    Evite d'appliquer le premier marqueur de période de la ligne à tous les
    faits de phrases suivantes : « FY25 revenue ... . H1 FY26 revenue ... ».
    """
    line = line or ""
    left = line[:metric_start]
    last_boundary = None
    for m in _SENTENCE_BOUNDARY_RE.finditer(left):
        last_boundary = m.end()
    start = last_boundary or 0
    right = line[metric_end:]
    m2 = _SENTENCE_BOUNDARY_RE.search(right)
    end = metric_end + (m2.start() if m2 else len(right))
    return line[start:end]


def extract_brief_financial_facts(brief: str, *, lang: str = "fr",
                                  scope: str = "",
                                  perimeter_entity: str = "") -> List[Any]:
    """
    Extrait les faits financiers déclarés dans le brief.
    Retourne une liste de FinancialFact prêts pour la table :
      source_doc="Brief", value = extrait tel quel, identité structurée
      (normalized_value/unit/currency/scale/period/metric_canonical_id),
      scope = niveau du contexte (le brief parle du périmètre qu'il déclare).
    Jamais board-safe : le blocker brief-only est posé par la couche §8.3
    (heuristique source_doc) ; ici on n'invente RIEN — pas de valeur sans
    devise pour une métrique monétaire.
    """
    from utils.financial_facts_table import FinancialFact, FactStatus

    facts: List[Any] = []
    seen: set = set()
    # B.1.3.12 (run 6 : « gross↵margin 67.9% ») — le brief colle des retours
    # à la ligne EN PLEINE PHRASE (wrap éditeur) : on joint une ligne à la
    # suivante quand elle ne se termine pas par une ponctuation forte et que
    # la suivante commence en minuscule — sans fusionner deux items réels.
    _norm = re.sub(r"(?m)([a-zà-ÿ0-9,%\)])[ \t]*\n[ \t]*([a-zà-ÿ(])",
                   r"\1 \2", brief or "")
    for raw_line in _norm.splitlines():
        if len(facts) >= _MAX_FACTS:
            break
        line = raw_line.strip()
        if not line or _SKIP_LINE.search(line):
            continue
        for pat, lbl_fr, lbl_en, mid_expected, monetary in _METRIC_PATTERNS:
            if len(facts) >= _MAX_FACTS:
                break
            m = re.search(pat, line, re.IGNORECASE)
            if not m:
                continue
            # Valeur : EXTRAIT porteur du nombre juste après le mot-clé —
            # jamais la queue de ligne entière (un « (-12% YoY) » plus loin
            # contaminerait l'unité en PCT).
            tail_raw = line[m.end():]
            tail = _current_clause(tail_raw).strip(" :–—-\t") or line
            val_txt = _value_excerpt(tail)
            nv, unit, currency, scale = parse_value(val_txt)
            if monetary and (nv is None or unit != "CUR" or not currency):
                # B.1.3.2-chatGPT candidate — valeur AVANT métrique :
                # « targeting ~GBP 100m of savings », « 235 M€ CA ».
                # Fallback monétaire strict : devise obligatoire après parse.
                prev_txt = _value_excerpt_before_metric(line[:m.start()])
                if prev_txt:
                    nv2, unit2, currency2, scale2 = parse_value(prev_txt)
                    if nv2 is not None and unit2 == "CUR" and currency2:
                        val_txt, nv, unit, currency, scale = (
                            prev_txt, nv2, unit2, currency2, scale2)
            if nv is None:
                continue
            if monetary:
                # devise explicite exigée — jamais de « m » ambigu
                if unit != "CUR" or not currency:
                    continue
            else:
                # non monétaire : refuser toute contamination devise, et un
                # « 2 383 m » nu (échelle M sans unité) n'est pas un effectif
                if unit == "CUR" or currency:
                    continue
                if not unit and scale in ("M", "Md"):
                    continue
                if "effectif" in lbl_fr.lower() and not unit:
                    unit = "PERSONS"
            label = lbl_fr if lang != "en" else lbl_en
            key = (label, val_txt)
            if key in seen:
                continue
            seen.add(key)
            f = FinancialFact(
                label=label, value=val_txt, status=FactStatus.FAIT,
                scope=(scope or "UNKNOWN"), source_doc="Brief")
            f.perimeter_entity = perimeter_entity or ""
            f.metric_canonical_id = (mid_expected
                                     or canonical_metric_id(label) or "OTHER")
            f.normalized_value = nv
            f.unit = unit
            f.currency = currency
            f.scale = scale
            f.period = extract_marked_period(
                _metric_sentence_context(line, m.start(), m.end()))
            f.notes = [("Déclaré dans le brief — non sourcé indépendamment"
                        if lang != "en" else
                        "Declared in brief — not independently sourced")]
            # B.1.3 — blocker de provenance posé À LA CRÉATION : même si un
            # conflit se résout plus tard, un fait déclaratif ne devient
            # jamais board-safe ni porteur de certification (défense en
            # profondeur, cohérente avec gate_financial_signal).
            try:
                _blk = list(getattr(f, "board_safe_blockers", None) or [])
                if "brief_only" not in _blk:
                    _blk.append("brief_only")
                f.board_safe_blockers = _blk
            except Exception:
                pass
            facts.append(f)
    return facts


_VAL_RE = re.compile(
    r"[~≈]?\s*-?\d[\d\s\u202F.,]*\s*"
    r"(?:%|Mds?|Md|bn|[MK]|k)?\s*(?:€|£|\$|GBP|EUR|USD|NOK|CHF)?"
    r"(?:\s*\((?:19|20)\d{2}\))?|"
    r"(?:GBP|EUR|USD|NOK|CHF|€|£|\$)\s*-?\d[\d\s\u202F.,]*\s*(?:bn|m|k|Mds?|Md|[MK])?",
    re.IGNORECASE)


_PREFERRED_VAL_RE = re.compile(
    # Valeurs explicitement financières / pourcentages / échelles : doivent
    # gagner contre les marqueurs de période en tête de queue (« Revenue FY25:
    # GBP 2.46bn » ne doit jamais extraire « 25 »). Le fallback _VAL_RE reste
    # nécessaire pour les effectifs nus (« Effectif 2024 : 2 100 »).
    r"(?:GBP|EUR|USD|NOK|CHF|€|£|\$)\s*[~≈]?\s*-?\d[\d\s\u202F.,]*\s*(?:bn|m|k|Mds?|Md|[MK])?"
    r"|[~≈]?\s*-?\d[\d\s\u202F.,]*\s*(?:%|Mds?|Md|bn|[MK]|k)\s*(?:€|£|\$|GBP|EUR|USD|NOK|CHF)?"
    r"|[~≈]?\s*-?\d[\d\s\u202F.,]*\s*(?:€|£|\$|GBP|EUR|USD|NOK|CHF)",
    re.IGNORECASE)


_LEADING_PERIOD_MARKERS = re.compile(
    r"^\s*(?:"
    r"(?:in|for|sur|au\s+titre\s+de|as\s+of|at|en|pour)\s+)?"
    r"(?:"
    r"(?:H[12]|S[12]|Q[1-4]|T[1-4])\s*(?:FY\s*)?(?:\d{2}|(?:19|20)\d{2})"
    r"|(?:FY|exercice|year)\s*(?:\d{2}|(?:19|20)\d{2})"
    r"|(?:19|20)\d{2}(?:[/-]\d{2,4})?"
    r")"
    r"(?:\s*(?:was|is|était|est|:|;|,|–|—|-))?\s*",
    re.IGNORECASE)

_LEADING_DATED_PAREN = re.compile(
    r"^\s*\([^)]*(?:ended|ending|weeks?|semaines?|clos|cl[oô]tur|to|au|as\s+at)[^)]*\)\s*[:;,–—-]?\s*",
    re.IGNORECASE)

_LEADING_YEAR_AS_VALUE = re.compile(
    # B.1.3.2-chatGPT candidate : un nombre year-like peut être la VALEUR
    # déclarative (« Effectif : 2024 collaborateurs », « CA : 2024 M€ »).
    # Dans ce cas, ne pas le nettoyer comme période. On exige une unité/devise
    # ou un marqueur de personnes juste après le nombre, et on refuse les formes
    # table-header suivies d'une autre valeur (« Revenue 2024 £m 2,383 »).
    r"^\s*(?:19|20)\d{2}\s*(?:"
    r"(?:Mds?|Md|bn|[MK]|k)\s*(?:€|£|\$|GBP|EUR|USD|NOK|CHF)"
    r"|(?:€|£|\$|GBP|EUR|USD|NOK|CHF)(?:\s*(?:bn|m|k|Mds?|Md|[MK]))?"
    r"|(?:collaborateurs?|salari[ée]s?|employees?|personnes?|people|staff)"
    r")(?=$|\s|[.,;:)])(?!\s*\d)",
    re.IGNORECASE)


def _leading_year_is_value(t: str) -> bool:
    return bool(_LEADING_YEAR_AS_VALUE.search(t or ""))


def _drop_leading_period_noise(tail: str) -> str:
    """Retire les marqueurs de période placés ENTRE la métrique et la valeur.

    Cas réel B.1.3.1-chatGPT : « Revenue FY25: GBP 2.46bn », « Gross margin
    FY26: 67.9% », « CA 2024 : 235 M€ ». Sans ce nettoyage, le premier nombre
    (« 25 », « 26 », « 2024 ») peut être lu comme valeur et la couche de preuve
    rate ou déforme le chiffre du brief. On ne touche qu'au début de la queue.

    B.1.3.2 — INTÉGRATION (protocole hybride, 1re application) : patch
    candidat ChatGPT (chatgpt_b131_candidate.diff), vérifié avant intégration
    selon la doctrine — trou REPRODUIT sur la source officielle : 6/6 cas dont
    3 CORRUPTIONS avérées (Marge brute=26, Effectif=2024, Operating margin=27)
    et 3 faits monétaires perdus. Post-patch : 6/6 corrects, année nue toujours
    refusée comme période (B.1.1), piège « 2 383 m » toujours rejeté (B.1.3).
    Intégré tel quel (conventions respectées) ; tests candidats repris.
    """
    t = (tail or "").strip(" :–—-\t")
    prev = None
    while prev != t:
        prev = t
        t = _LEADING_DATED_PAREN.sub("", t).strip(" :–—-\t")
        if _leading_year_is_value(t):
            return t
        t = _LEADING_PERIOD_MARKERS.sub("", t).strip(" :–—-\t")
        if _leading_year_is_value(t):
            return t
    return t


# 9.4.60 — contre-recette ChatGPT du 11/10/2026 (F59-01) : « passerelle entre marge brute publiée et coûts d'intrants
# — DAF · 31/10/2026 » créait une « marge brute 31 », reprise ensuite dans une action du DAF, la synthèse et le deck.
# Une DATE n'est jamais une valeur ; une valeur sans unité n'est retenue que si elle suit directement l'indicateur.
_DATE_TOKEN60 = re.compile(
    r"(?i)\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\b\d{1,2}[.-]\d{1,2}[.-]\d{4}\b|\b\d{4}-\d{2}-\d{2}\b|"
    r"\b\d{1,2}(?:er)?\s+(?:janv|févr|fevr|mars|avr|mai|juin|juil|août|aout|sept|oct|nov|déc|dec|jan|feb|mar|apr|may|"
    r"jun|jul|aug|sep)[a-zéûè]*\.?(?:\s+\d{4})?\b")
_DIRECT_LINK60 = re.compile(r"(?i)^[\s:=≈~(]*(?:(?:de|d'|à|a|of|at|est|is|was|reached|atteint|atteignait|"
                            r"d'environ|environ|about|around|approx\.?|soit)\s*)*$")


def _value_excerpt(tail: str) -> str:
    cleaned = _drop_leading_period_noise(tail)
    masked = _DATE_TOKEN60.sub(lambda mm: " " * len(mm.group(0)), cleaned)
    # Préférer les valeurs porteuses d'unité/devise/% ; une valeur nue (effectif, ratio sans symbole) n'est retenue
    # que si elle suit directement l'indicateur (« Effectif : 714 », « marge brute de 55 »).
    m = _PREFERRED_VAL_RE.search(masked)
    if m:
        return cleaned[m.start():m.end()].strip()
    m = _VAL_RE.search(masked)
    if m and _DIRECT_LINK60.match(masked[:m.start()]):
        return cleaned[m.start():m.end()].strip()
    return re.sub(r"\d", " ", masked[:60]).strip()


_METRIC_BETWEEN_VALUE_AND_CURRENT = re.compile(
    r"\b(?:CA|chiffre\s+d[' ]affaires|revenue?s?|sales|net\s+income|net\s+profit|RN|"
    r"operating\s+profit|résultat\s+op[ée]rationnel|EBITDA?|net\s+debt|dette\s+nette|"
    r"cash|tr[ée]sorerie|gross\s+margin|marge\s+brute|operating\s+margin|"
    r"marge\s+op[ée]rationnelle|headcount|effectifs?|collaborateurs?|employees?|"
    r"savings|économies?|cost\s+reduction)\b",
    re.IGNORECASE)


def _value_excerpt_before_metric(prefix: str) -> str:
    """Extraction défensive d'une valeur placée AVANT le mot-clé métrique.

    Cas terrain dossier anglophone coté/dossier industriel (composants) : « targeting ~GBP 100m of savings »,
    « GBP 100m savings target », « 235 M€ CA groupe indicatif ». Le contrat
    B.1 veut que les chiffres du brief utilisés dans l'analyse soient visibles
    dans la couche de preuve ; le premier extracteur ne regardait que la queue
    après le mot-clé.

    B.1.3.3 — INTÉGRATION (protocole hybride, 2e application) : patch
    candidat ChatGPT (B1.3.2→candidate), vérifié selon la doctrine — les
    DEUX trous REPRODUITS sur la source officielle (4/4 : valeur avant
    métrique perdue ×2 ; année-valeur « Effectif : 2024 » / « CA : 2024 M€ »
    nettoyée à tort — la perte conservatrice documentée au manifeste B.1.3.2,
    transformée ici en règle testée). Post-patch : trous fermés, 5 gardes
    candidates + invariants B.1.1/B.1.3 rejoués, frontière de phrase tenue
    (« Revenue reached GBP 2.46bn. Savings… » : pas de vol inter-phrases).
    Suite complète exécutée côté Claude (limite sandbox candidate fermée).
    Risque résiduel ACCEPTÉ et documenté : faux positif sémantique possible
    quand un montant devise précède la métrique dans la même phrase sans lui
    appartenir (« With GBP 100m at stake, savings must double » → fait
    savings) — déclaratif non board-safe, phrase rhétorique improbable en
    brief télégraphique ; à durcir seulement si un terrain réel le produit.

    Garde : on ne franchit jamais une frontière de phrase et on ne retourne
    qu'une valeur monétaire explicite dans une fenêtre courte. Cette fonction
    est appelée uniquement comme fallback MONÉTAIRE strict, donc elle ne
    transforme pas « 1,700 job cuts (~20% of headcount) » en effectif.
    """
    segment = re.split(r"[.;\n]", prefix or "")[-1]
    window = segment[-90:]
    matches = list(_PREFERRED_VAL_RE.finditer(window))
    if not matches:
        return ""
    m = matches[-1]
    between = window[m.end():]
    # Si la fenêtre entre la valeur et la métrique courante contient déjà une
    # AUTRE métrique, la valeur appartient probablement à cette métrique-là.
    # Ex. « GBP 100m savings target and revenue down 12% » : ne jamais donner
    # GBP 100m au fait Revenue.
    if _METRIC_BETWEEN_VALUE_AND_CURRENT.search(between):
        return ""
    return m.group(0).strip()


def inject_brief_facts_once(table: Any, brief: str, *, lang: str = "fr",
                            scope: str = "UNKNOWN",
                            perimeter_entity: str = "") -> List[Any]:
    """B.1.3.1 (audit P2) — injection IDEMPOTENTE des faits du brief.

    Utilisée par le chemin AMONT et par le FALLBACK de table (B.1.2) : sans
    elle, une table reconstruite en fallback repassait la couche de preuve
    mais PERDAIT les faits du brief (fuite de câblage constatée à l'audit
    du zip B.1.3). Idempotence : si la table porte déjà au moins un fait
    source_doc='Brief', on n'ajoute rien (pas de doublons).
    Retourne la liste des faits ajoutés ([] si déjà présents ou aucun).
    """
    facts = list(getattr(table, "facts", []) or [])
    if any(str(getattr(f, "source_doc", "") or "").strip().lower() == "brief"
           for f in facts):
        return []
    extracted = extract_brief_financial_facts(
        brief, lang=lang, scope=scope, perimeter_entity=perimeter_entity)
    for f in extracted:
        try:
            table.add(f)
        except Exception:
            continue
    return extracted
