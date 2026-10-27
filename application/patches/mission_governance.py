"""
patches/mission_governance.py — v17.1.0-B2.3-F.6.7 (Closing Review / Audit Committee hardening)

Deux primitives de gouvernance pilotées par le BRIEF, absentes jusqu'ici et
révélées par le run dossier réseau de soins FY2022 :

  1. source_mode = ATTACHMENTS_ONLY
     Le brief impose « analyses fondées exclusivement sur les pièces jointes ».
     → couper Pappers / GLEIF / recherche web AVANT le run (gate amont), et le
       dire honnêtement (« non disponible — mode pièces jointes »), jamais un
       scrub silencieux.

  2. analysis_as_of_date  (≠ run_date réel)
     Le brief impose « Nous sommes début 2023 ». La date RÉELLE du run reste
     2026-06-12 (diagnostics / post-mortem), mais l'ANALYSE doit se comporter
     comme au 2023-02-15 : jalons, horizons, deck, registre s'y indexent ; une
     échéance 2023 n'est pas « en retard ».

Module déterministe, fail-open. Aucun fait codé en dur.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# 1) source_mode
# ─────────────────────────────────────────────────────────────────────────────
ATTACHMENTS_ONLY = "ATTACHMENTS_ONLY"
OPEN = "OPEN"

_ATTACH_ONLY_CUES = (
    # FR
    r"exclusivement\s+(?:sur\s+)?(?:les\s+|des\s+)?pi[èe]ces?\s+jointes",
    r"uniquement\s+(?:à\s+partir\s+)?(?:sur\s+)?(?:les\s+|des\s+)?pi[èe]ces?\s+jointes",
    r"(?:fond[ée]es?|bas[ée]es?)\s+(?:exclusivement|uniquement)\s+sur\s+(?:les\s+)?pi[èe]ces?\s+jointes",
    r"aucune\s+(?:source|donn[ée]e|recherche)\s+externe",
    r"pas\s+de\s+(?:source|donn[ée]e|recherche)\s+externe",
    r"sans\s+(?:recherche\s+web|pappers|source\s+externe|veille)",
    r"pi[èe]ces?\s+jointes?\s+(?:uniquement|exclusivement|seules)",
    # EN
    r"attachments?\s+only",
    r"(?:based\s+)?solely\s+on\s+the\s+attach",
    r"only\s+the\s+attached",
    r"no\s+external\s+(?:source|data|research)",
)
_ATTACH_ONLY_RE = re.compile("|".join(_ATTACH_ONLY_CUES), re.IGNORECASE)


def detect_source_mode(brief: str) -> str:
    """ATTACHMENTS_ONLY si le brief restreint l'analyse aux pièces jointes."""
    if brief and _ATTACH_ONLY_RE.search(brief):
        return ATTACHMENTS_ONLY
    return OPEN


def web_search_gate(external_sources_skip: bool):
    """F.6.7.1 — Décision de gate pour la veille web concurrentielle.

    Renvoie (web_enabled, skip_diag) : si les sources externes sont coupées
    (mode pièces jointes), web OFF + une ligne de diagnostic SKIPPED explicite
    (traçabilité), jamais une absence silencieuse. Sinon (True, None)."""
    if external_sources_skip:
        return False, {
            "role": "web_search", "provider": "internal",
            "model": "source_mode_gate", "status": "SKIPPED",
            "reason": "ATTACHMENTS_ONLY",
            "summary": "Veille web concurrentielle désactivée (mode pièces jointes uniquement).",
        }
    return True, None


# ─────────────────────────────────────────────────────────────────────────────
# 2) analysis_as_of_date
# ─────────────────────────────────────────────────────────────────────────────
_MONTHS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
_MONTHS_RE = "|".join(sorted(_MONTHS.keys(), key=len, reverse=True))

# Date ISO explicite : analysis_as_of_date = 2023-02-15 / as of 2023-02-15
_ISO_RE = re.compile(
    r"(?:analysis[_\s]?as[_\s]?of[_\s]?date|as\s+of|à\s+la\s+date\s+du|date\s+d['’]analyse)\s*[:=]?\s*"
    r"(20\d\d)-(\d{2})-(\d{2})",
    re.IGNORECASE,
)
# « Nous sommes [début|mi-|fin] 2023 » / « contexte : début 2023 »
_NOUS_SOMMES_RE = re.compile(
    r"(?:nous\s+sommes|contexte\s+temporel\s*:?|on\s+est|we\s+are)\s+"
    r"(?:en|au|in)?\s*"
    r"(d[ée]but|mi[\s\-]?|fin|early|mid|late|end\s+of)?\s*"
    r"(?:(" + _MONTHS_RE + r")\s+)?(20\d\d)",
    re.IGNORECASE,
)
# « à la date du 15 février 2023 »
_DATE_LITTERALE_RE = re.compile(
    r"(?:au|le|du)\s+(\d{1,2})\s+(" + _MONTHS_RE + r")\s+(20\d\d)",
    re.IGNORECASE,
)


# Gate 13 — CUES d'intention explicite (FR/EN). Une date sans cue n'est
# JAMAIS une demande de scénario.
_INTENT_CUE_RE = re.compile(
    r"(?:analysis[_ ]as[_ ]of[_ ]date\s*[=:]?|"
    r"date\s+d['’]analyse\s*:?|"
    r"analyse\s+(?:au|le)\b|"
    r"scenario\s+date\s*:?|"
    r"as\s+of\b|"
    r"on\s+se\s+place\s+(?:au|le|en)\b|"
    r"se\s+placer\s+(?:au|le|en)\b|"
    r"nous\s+sommes\s+(?:en|au|le|d[ée]but|mi|fin)\b|"
    r"on\s+est\s+(?:en|au|d[ée]but|mi|fin)\b|"
    r"we\s+are\s+(?:in|at|early|mid|late)\b|"
    r"contexte\s+temporel\s*:|"
    r"[àa]\s+la\s+date\s+d['’]analyse\s*(?:de|du|:)?)",
    re.IGNORECASE,
)
# valeur numérique : 2023-02-15 / 2023/02/15 / 15/02/2023 / 02.15.2023
_NUM_DATE_RE = re.compile(
    r"\b(\d{4}|\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{1,2})\b")
# valeur littérale : « 15 février 2023 » (sans exiger au/le/du : la cue
# précède déjà)
_LIT_DATE_RE = re.compile(
    r"(\d{1,2})(?:er)?\s+(" + _MONTHS_RE + r")\s+(20\d\d)", re.IGNORECASE)
# présence d'un motif « date-like » quelconque dans la fenêtre
_DATE_LIKE_RE = re.compile(
    r"\d{1,4}[/.\-]\d{1,2}[/.\-]\d{1,4}|\d{1,2}\s+(?:" + _MONTHS_RE +
    r")\s+20\d\d|20\d\d", re.IGNORECASE)


# Gate 14 — « as of » isolé (pour le test de position directive)
_AS_OF_ONLY_RE = re.compile(r"as\s+of\b", re.IGNORECASE)
# valeur littérale EN : « 31 December 2024 » couvert par _LIT_DATE_RE ;
# « December 31, 2024 » (mois d'abord)
_EN_LIT_DATE_RE = re.compile(
    r"(" + _MONTHS_RE + r")\s+(\d{1,2}),?\s+(20\d\d)", re.IGNORECASE)
# placeholders : intention explicite, valeur non exploitable → INVALID
# Gate 16 — frontières de mot OBLIGATOIRES sur les placeholders
# alphabétiques : « N/A » ne doit JAMAIS matcher « na » DANS « analyse »
# (bug latent gate 14, exercé par les directives naturelles).
_PLACEHOLDER_RE = re.compile(
    r"(?:\b(?:à\s+d[ée]finir|à\s+confirmer|à\s+pr[ée]ciser|"
    r"à\s+compl[ée]ter|TBD|TBC|unknown|inconnue?|pending|"
    r"to\s+be\s+defined|N/?A)\b|\?{2,})",
    re.IGNORECASE)


def _phase_to_day(phase: str) -> tuple[int, int]:
    """Mappe une phase (début/mi/fin) → (mois, jour) représentatif et stable."""
    p = (phase or "").lower().strip()
    if p.startswith(("d", "e")):      # début / early
        return (2, 15)                # ~mi-Q1
    if p.startswith(("m",)):          # mi / mid
        return (6, 30)
    if p.startswith(("f", "l")):      # fin / late / end
        return (12, 15)
    return (6, 30)                    # année seule → milieu d'année


# ── Gate 15 — grammaire d'intention : directive / valeur / résolution ──
# Cues FORTES (étiquettes/directives explicites) : sans valeur exploitable
# dans LEUR clause → INVALID (la demande existe, elle ne disparaît pas).
_STRONG_CUE_RE = re.compile(
    r"(?:analysis[_ ]as[_ ]of[_ ]date\s*[=:]?|"
    r"date\s+d['\u2019]analyse\s*:?|"
    r"scenario\s+date\s*:?|"
    r"on\s+se\s+place\s+(?:au|le|en)\b|"
    r"se\s+placer\s+(?:au|le|en)\b|"
    r"[àa]\s+la\s+date\s+d['\u2019]analyse\s*(?:de|du|:)?|"
    r"contexte\s+temporel\s*:)",
    re.IGNORECASE,
)
# Cues FAIBLES (peuvent être de la prose) : sans motif date-like dans la
# clause → simplement ignorées (bornage « l'analyse au cours de laquelle »).
_WEAK_CUE_RE = re.compile(
    r"analyse\s+(?:au|le)\b", re.IGNORECASE)
# Masques de protection : une cue niée, citée, ou décrite (titre, label,
# exemple) n'est JAMAIS une directive.
_NEGATION_RE = re.compile(
    r"(?:ne\s+pas\s+(?:utiliser|prendre|retenir|appliquer)|"
    r"sans\s+(?:utiliser|retenir)|ignor\w*|"
    r"do\s*n[o']t\s+use|not\s+use|ignore\b|disregard)",
    re.IGNORECASE,
)
_METATEXT_RE = re.compile(
    r"(?:titre|title|label|libell[ée]|intitul[ée]|exemple|example|"
    r"\be\.?g\b|citation|quote)",
    re.IGNORECASE,
)
# guillemet de CITATION : en position d'ouverture (après espace/début),
# jamais l'apostrophe interne d'un mot (« d'analyse »).
_QUOTE_OPEN_RE = re.compile(
    "(?:^|\\s)[\"\u201c\u00ab\u2018'](?=\\S)")
_CLAUSE_DELIMS = ".\n!?;"
# Gate 16 — instruction impérative après une date as-of : virgule
# optionnelle, AUCUN chiffre (une métrique a des chiffres), au moins un
# verbe directif FR/EN.
_ASOF_VERB_RE = re.compile(
    r",?\s*(?:(?:please|veuillez|merci\s+de|kindly|could\s+you|"
    r"can\s+you|would\s+you|pouvez[-\s]vous|peux[-\s]tu|il\s+faut|"
    r"we\s+need\s+to|nous\s+devons|je\s+veux\s+que\s+(?:tu|vous)|"
    r"et|and|puis|pour|to)\s+)*(?P<verb>"
    r"analys(?:e|ez|er)?|analyze|prepar(?:e|ez|er)?|pr[ée]par(?:e|ez|er)|"
    r"propos(?:e|ez|er)|present|pr[ée]sent(?:e|ez|er)|review|"
    r"[ée]valu(?:e|ez|er)|evaluate|assess|plan|recommend|recommand(?:e|ez|er)|"
    r"[ée]tabli(?:r|ssez)|establish|draw\s+up|build|construis(?:ez)?|"
    r"pr[ée]voi(?:r|yez)|projet(?:e|ez)r?|provide|conduct|"
    r"conduis(?:ez)?|create|cr[ée](?:e|ez|er)|develop|d[ée]velopp(?:e|ez|er)|"
    r"draft|r[ée]dig(?:e|ez|er)|fourni(?:r|ssez)"
    r")\b[ \t]*(?P<next>[^\s.,;:!?]*)", re.IGNORECASE)
# Gate 18 — un mot directif suivi d'une copule/auxiliaire ou d'une forme
# nominale n'est PAS un ordre : « plan was approved », « review was
# completed », « present value », « analyse financière ». Liste fermée,
# extensible, documentée en LIMITATIONS.
_ASOF_NOMINAL_NEXT = frozenset({
    "for", "of", "de", "du", "des", "approfondie", "approfondi",
    "accounts",
    "was", "were", "is", "are", "has", "have", "had", "be", "been",
    "being", "will", "would", "est", "sont", "était", "etait", "fut",
    "sera", "serait", "value", "values", "approval", "approvals",
    "completion", "financière", "financiere", "financier",
    "stratégique", "strategique", "budgétaire", "budgetaire",
    "préliminaire", "preliminaire", "complète", "complete", "complet",
    "détaillée", "detaillee", "détaillé", "detaille",
})


_ASOF_AMBIGUOUS_TOKENS = frozenset({"plan", "review", "build",
                                     "present", "analyse", "draft"})
_ASOF_LATE_COPULA_RE = re.compile(
    r"\b(?:was|were|is|are|has\s+been|had\s+been|est|[ée]tait|sont|"
    r"fut|sera)\b", re.IGNORECASE)


def _asof_tail_is_instruction(tail: str) -> bool:
    """Vrai si le tail après la date est une INSTRUCTION impérative :
    cadre modal optionnel (please, could you, pouvez-vous, il faut…),
    verbe directif à la forme de base EN TÊTE, token suivant hors
    copules/nominaux. Gate 19 — DÉSAMBIGUÏSATION SYNTAXIQUE : pour les
    tokens ambigus (plan/review/build/present/analyse), une copule plus
    loin dans la clause (« plan for FY2024 WAS approved ») signe un
    récit, jamais un ordre. Chiffres et objets restent libres."""
    m = _ASOF_VERB_RE.match(tail or "")
    if not m:
        return False
    nxt = (m.group("next") or "").strip().lower()
    if nxt in _ASOF_NOMINAL_NEXT:
        return False
    verb = (m.group("verb") or "").strip().lower()
    if verb in _ASOF_AMBIGUOUS_TOKENS and \
            _ASOF_LATE_COPULA_RE.search(tail[m.end("verb"):]):
        return False
    return True


_CLAUSE_DELIM_RE = re.compile(r"(?<!\d)\.(?!\d)|[\n!?;]")


_MD_BULLET_RE = re.compile(
    r"(?m)^[ \t]*(?:[-*>#]+|\d{1,3}[.)])[ \t]")
_MD_EMPH_RE = re.compile(r"\*\*|__|`")


def _strip_markdown_decor(text: str) -> str:
    """Gate 16 — remplace les marqueurs Markdown décoratifs (puces de
    tête de ligne, gras **/__, backticks) par des ESPACES de même
    longueur : le texte garde exactement ses positions (spans exacts)."""
    def _blank(m):
        return " " * (m.end() - m.start())
    return _MD_EMPH_RE.sub(_blank, _MD_BULLET_RE.sub(_blank, text))


def _g15_clause_bounds(brief: str, pos: int):
    """Bornes de la CLAUSE contenant pos. Délimiteurs : . \n ! ? ; — le
    point INTERNE à une date (15.02.2023) n'est JAMAIS un délimiteur
    (gate 16)."""
    start, end = 0, len(brief)
    for m in _CLAUSE_DELIM_RE.finditer(brief):
        if m.start() < pos:
            start = m.end()
        elif m.start() >= pos:
            end = m.start()
            break
    return start, end


def _g15_cue_is_protected(brief: str, cue_start: int) -> bool:
    """Négation, citation ou métatexte dans la même clause AVANT la cue →
    la cue n'est pas une directive (elle est décrite, pas donnée)."""
    c_start, _c_end = _g15_clause_bounds(brief, cue_start)
    prefix = brief[c_start:cue_start]
    # Gate 19 — modificateur HISTORIQUE adjacent : « Ancienne date
    # d'analyse », « Previous scenario date » décrivent une valeur
    # révolue, jamais une directive.
    if re.search(r"(?:ancien(?:ne)?s?|pr[ée]c[ée]dent(?:e)?s?|"
                 r"previous|former|old|obsolete|initiale?)\s*$",
                 prefix, re.IGNORECASE):
        return True
    if _NEGATION_RE.search(prefix):
        return True
    if _METATEXT_RE.search(prefix):
        return True
    if _QUOTE_OPEN_RE.search(prefix):
        return True
    return False


def parse_value_in_same_clause(clause: str):
    """Gate 15 — parse la valeur DANS LA CLAUSE de la directive, jamais une
    fenêtre arbitraire. Ordre ferme : placeholder D'ABORD (« à définir »,
    « TBD », « unknown » gagnent contre toute date située plus loin), puis
    dates numériques/littérales FR/EN.
    → ("VALID", iso, raw) | ("INVALID", None, raw) | (None, None, "")."""
    m = _PLACEHOLDER_RE.search(clause)
    if m:
        return "INVALID", None, m.group(0)
    m = _NUM_DATE_RE.search(clause)
    if m:
        raw = m.group(0)
        a, b, c = m.group(1), m.group(2), m.group(3)
        try:
            if len(a) == 4:
                y, mo, d = int(a), int(b), int(c)
            else:
                y = int(c)
                x1, x2 = int(a), int(b)
                if x1 > 12 and x2 <= 12:
                    d, mo = x1, x2
                elif x2 > 12 and x1 <= 12:
                    mo, d = x1, x2
                elif x1 > 12 and x2 > 12:
                    raise ValueError("jour et mois impossibles")
                elif x1 != x2:
                    # Gate 16 — les deux positions sont un jour ET un
                    # mois plausibles (03/04/2023 : 3 avril en Europe,
                    # 4 mars aux États-Unis) : sans locale structurée,
                    # la seule réponse sûre est fail-closed.
                    raise ValueError("format numérique ambigu sans locale")
                else:
                    d, mo = x1, x2
            return "VALID", date(y, mo, d).isoformat(), raw
        except Exception:
            return "INVALID", None, raw
    m = _LIT_DATE_RE.search(clause)
    if m:
        raw = m.group(0)
        mon = _MONTHS.get(m.group(2).lower())
        try:
            if not mon:
                raise ValueError("mois inconnu")
            return "VALID", date(int(m.group(3)), mon,
                                 int(m.group(1))).isoformat(), raw
        except Exception:
            return "INVALID", None, raw
    m = _EN_LIT_DATE_RE.search(clause)
    if m:
        raw = m.group(0)
        mon = _MONTHS.get(m.group(1).lower())
        try:
            if not mon:
                raise ValueError("mois inconnu")
            return "VALID", date(int(m.group(3)), mon,
                                 int(m.group(2))).isoformat(), raw
        except Exception:
            return "INVALID", None, raw
    return None, None, ""


def detect_global_scenario_intent(brief: str):
    """Gate 15 — collecte TOUTES les cues directives non protégées.
    Retourne [(kind, cue_match, clause_text)] :
      strong  : étiquette explicite (valeur requise dans SA clause) ;
      weak    : prose « analyse au/du/le » (candidate seulement si
                date-like dans la clause) ;
      asof    : « As of <date> » STANDALONE sur la première ligne non
                vide (aucune métrique, virgule ou commentaire) ;
      nous    : « nous sommes / on est / we are … <année> » (chaque
                occurrence est une candidate)."""
    out = []

    def _g19_neg_after(tail: str) -> bool:
        # Gate 19 — « Date d'analyse à ne pas utiliser : … », « Scenario
        # date not to be used: … » : une négation entre la cue et la
        # première valeur chiffrée décrit la valeur, elle ne la donne
        # pas. (Une négation APRÈS la date — « ne pas diffuser » — ne
        # protège pas.)
        m_neg = re.search(r"\b(?:ne\s+pas|à\s+ne\s+pas|ne\s+plus|"
                          r"à\s+ne\s+plus|not\s+to\s+be|not\s+to\s+use|"
                          r"pr[ée]c[ée]dente?|ancien(?:ne)?|previous|"
                          r"former|obsol[eè]te)\b", tail, re.IGNORECASE)
        if not m_neg:
            return False
        m_dig = re.search(r"\d", tail)
        return m_dig is None or m_neg.start() < m_dig.start()

    for m in _STRONG_CUE_RE.finditer(brief):
        if not _g15_cue_is_protected(brief, m.start()):
            _cs, ce = _g15_clause_bounds(brief, m.start())
            tail19 = brief[m.end():ce]
            if _g19_neg_after(tail19):
                continue
            out.append(("strong", m, tail19))
    for m in _WEAK_CUE_RE.finditer(brief):
        if any(k == "strong" and s0.start() <= m.start() < s0.end()
               for k, s0, _c in out):
            continue
        if not _g15_cue_is_protected(brief, m.start()):
            _cs, ce = _g15_clause_bounds(brief, m.start())
            tail19 = brief[m.end():ce]
            if _g19_neg_after(tail19):
                continue
            out.append(("weak", m, tail19))
    # As-of : première ligne non vide, ligne = directive SEULE.
    first_line, offset = "", 0
    for raw_line in brief.split("\n"):
        if raw_line.strip():
            first_line = raw_line
            break
        offset += len(raw_line) + 1
# Gate 18 — une directive « As of » peut ouvrir N'IMPORTE QUELLE
    # clause ou ligne (plus seulement la première) : contexte société,
    # titre Markdown ou phrase préalable ne masquent plus une vraie
    # demande de backtest. La sécurité est STRUCTURELLE : (a) as-of doit
    # être le PREMIER token de sa clause (« Revenue as of… » n'est
    # jamais capté) ; (b) la date doit être le PRÉFIXE immédiat ;
    # (c) le tail doit être vide (standalone) ou une INSTRUCTION
    # impérative (_asof_tail_is_instruction) ; (d) les masques
    # négation/citation/métatexte s'appliquent par occurrence.
    # Gate 19 — familles de cues temporelles en TÊTE DE CLAUSE :
    #   as of / au / à la date du   → tail standalone OU impératif ;
    #   placez-vous au / nous nous plaçons au → AUTO-DIRECTIVES (la cue
    #   EST l'ordre : le tail est libre).
    _G19_HEAD_CUE_RE = re.compile(
        r"(?:\bplacez[-\s]vous\s+au\s+|"
        r"\bnous\s+nous\s+pla[çc]ons\s+au\s+|"
        r"\bas\s+of\s+|\bà\s+la\s+date\s+du\s+|\bau\s+)",
        re.IGNORECASE)
    for m18 in _G19_HEAD_CUE_RE.finditer(brief):
        c_start, c_end = _g15_clause_bounds(brief, m18.start())
        if brief[c_start:m18.start()].strip():
            continue                     # pas en tête de clause
        if _g15_cue_is_protected(brief, m18.start()):
            continue
        _auto19 = bool(re.match(r"(?:placez|nous)", m18.group(0).strip(),
                                re.IGNORECASE))
        candidate_value = brief[m18.end():c_end].strip()
        if not candidate_value:
            continue
        st, val, raw = parse_value_in_same_clause(candidate_value)
        if st in ("VALID", "INVALID") and raw and \
                candidate_value.lower().startswith(raw.strip().lower()):
            tail = candidate_value[len(raw.strip()):].strip()
            tail_ok = (_auto19 or tail in ("", ".", "!") or
                       _asof_tail_is_instruction(tail))
            if tail_ok:
                fake = re.match(r"as\s+of\b", brief[m18.start():],
                                re.IGNORECASE)

                class _Span18:
                    def __init__(self, s0):
                        self._s0 = s0

                    def start(self):
                        return self._s0
                out.append(("asof", _Span18(m18.start()), raw.strip()))
    for m in _NOUS_SOMMES_RE.finditer(brief):
        if not _g15_cue_is_protected(brief, m.start()):
            out.append(("nous", m, m.group(0)))
    return out


def resolve_candidates(candidates):
    """Gate 15 — résolution d'unicité : 0 → NOT_REQUESTED ; une valeur
    unique (répétitions identiques comprises) → VALID ; ≥2 valeurs
    distinctes OU valide+invalide → famille INVALID avec
    error_code=TEMPORAL_AUTHORITY_CONFLICT et conflict:true (état
    canonique CONFLICT porté par ces champs) ; que des invalides →
    INVALID ; candidates avec spans toujours exposées."""
    cand_out = [{"value": v, "raw": r, "span": list(sp)}
                for st, v, r, sp in candidates]
    if not candidates:
        return {"status": "NOT_REQUESTED", "value": None, "raw": "",
                "error_code": "", "conflict": False, "candidates": []}
    valid_values = sorted({v for st, v, r, sp in candidates
                           if st == "VALID" and v})
    has_invalid = any(st == "INVALID" for st, v, r, sp in candidates)
    if len(valid_values) > 1 or (len(valid_values) == 1 and has_invalid):
        return {"status": "INVALID", "value": None,
                "raw": " | ".join(r for st, v, r, sp in candidates),
                "error_code": "TEMPORAL_AUTHORITY_CONFLICT",
                "conflict": True, "candidates": cand_out}
    if len(valid_values) == 1:
        first = next(c for c in candidates if c[0] == "VALID")
        return {"status": "VALID", "value": valid_values[0],
                "raw": first[2], "error_code": "",
                "conflict": False, "candidates": cand_out}
    first = candidates[0]
    return {"status": "INVALID", "value": None, "raw": first[2],
            "error_code": "TEMPORAL_AUTHORITY_INVALID",
            "conflict": False, "candidates": cand_out}


# ═══ Refactor Temporal Core — familles directives CONTRACTUELLES et
# legacy à DATE INTERNE. Chaque motif contient un marqueur temporel
# explicite (« analysis date », « reference date », « cut-off date »,
# « situation at/au », « as it stood », « en vous plaçant », « retenez …
# comme date ») : le risque de collision avec une date métier est
# structurellement quasi nul. Le texte matché est ensuite MASQUÉ (spans
# préservés) pour que les cues classiques ne re-matchent pas dedans.
# Correctif Temporal Core (contrat A3) — le 4e label signé :
# « À la date du <date> : » (la date AVANT le deux-points final).
_A3_DATE_DU_RE = re.compile(
    r"[àa]\s+la\s+date\s+du\s+(?P<d>[^:\n]+?)\s*:", re.IGNORECASE)
# Appartenance stricte au dénominateur A3 (préfixes des cues strong) :
# seuls ces labels sont DÉCISIONNAIRES ; toute autre cue forte est
# rétrogradée en candidate legacy confirmable (jamais VALID autonome).
# Correctif TCR-C3 — les labels A3 sont des CHAMPS, jamais des
# sous-chaînes de prose métier : ancrage au début de ligne ou de champ
# (après . ; ! ?), décoration Markdown tolérée (- * # > _ espaces).
# (« > » retiré au correctif v3 : un blockquote est une CITATION,
#  jamais un champ actif.)
_A3_FIELD_DECOR = " \t-*#_"


def _a3_field_anchored(text: str, start: int) -> bool:
    i = start - 1
    while i >= 0 and text[i] in _A3_FIELD_DECOR:
        i -= 1
    if i < 0:
        return True
    return text[i] in "\n.;!?"


# Correctif TCR-v3 — le code Markdown (inline `…` et fenced ```…```)
# n'est JAMAIS un champ actif : masqué avant toute détection.
# … et une ligne blockquote (« > … ») est une CITATION entière.
_A3_CODE_SPAN_RE = re.compile(
    r"```[\s\S]*?```|`[^`\n]+`|(?m:^[ \t]*>[^\n]*)"
    r"|<blockquote>[\s\S]*?</blockquote>|</?blockquote>"
    r"|(?m:^(?:[ ]{4,}|\t)[^\n]*)", re.IGNORECASE)


def _a3_mask_code_spans(text: str) -> str:
    return _A3_CODE_SPAN_RE.sub(lambda m: " " * len(m.group(0)), text)


# Correctif TCR-v3 — négation / obsolescence dans la clause qui PRÉCÈDE
# immédiatement le label (« Ne pas utiliser. Date d'analyse : … »,
# « Ancien paramètre. … », « Ne pas se placer.\nÀ la date du … ») :
# le label est de la prose sur un paramètre, pas une autorité.
_A3_PREV_NEGATION_RE = re.compile(
    r"(?:\bne\s+pas\b|\bne\s+plus\b|\bdo\s+not\b|\bdon['\u2019]t\b|"
    r"\bnot\s+to\b|\bancien(?:ne)?s?\b|\bprevious\b|\bdeprecated\b|"
    r"\bobsolete\b|\bp[ée]rim[ée]e?\b|\bcaduc\b|\bignorer?\b|"
    r"\b[àa]\s+[ée]viter\b|\bexemples?\b|\bexamples?\b|\bsamples?\b|"
    r"\billustrations?\b|\bquoted\b|\bcitations?\b|\bsyntaxe?s?\b)",
    re.IGNORECASE)


# Correctif TCR-v5 — ZONE DE CONTRÔLE structurelle : un label introduit
# par un EN-TÊTE métalinguistique (« Documentation : », « Format
# attendu : », « Historique : », « Exemple : » — n'importe quel « X : »
# ou « X = » nu sur la ligne non vide précédente) est du CONTENU
# documenté, jamais un champ actif. Règle POSITIONNELLE : elle remplace
# le tapis roulant lexical — aucun mot-clé à maintenir.
# Correctif TCR-v6 — ZONE DE CONTRÔLE top-level : le parser A3 ne lit
# QUE le préambule de champs du brief. La zone s'étend depuis le début
# sur les lignes consécutives de forme « Clé : valeur » / « clé =
# valeur » (clé courte, sans ponctuation forte), décorations Markdown
# tolérées. La PREMIÈRE ligne de prose, de structure documentaire
# (HTML <…>, table |, fence ```/~~~, séparateur email -----,
# blockquote >, code indenté) ou de champ mal formé FERME la zone
# définitivement : tout label au-delà appartient au corps documentaire
# et n'est JAMAIS décisionnaire. Règle structurelle : aucun lexique.
# Correctif TCR-v7 — les LIGNES DE CONTRÔLE sont exactement les quatre
# labels signés (décorations Markdown tolérées). Regex publique : la
# zone du parser ET l'assembleur de brief (bloc canonique) partagent LE
# MÊME point de vérité. Pré-filtre permissif : être reconnu ici ne
# valide rien (le parser tranche) ; ne pas l'être exclut de la zone.
A3_CONTROL_LINE_RE = re.compile(
    r"^(?:analysis_as_of_date\s*=|date\s+d['\u2019]analyse\s*:|"
    r"scenario\s+date\s*:|[àa]\s+la\s+date\s+du\b[^:\n]{0,60}:)",
    re.IGNORECASE)


def split_temporal_control_prefix(text):
    """Correctif TCR-v8 (verdict v7, P0-1) — sépare l'ENTRÉE DE CONTRÔLE
    du CONTENU MÉTIER dans un champ utilisateur brut.

    Seules les lignes de contrôle placées EN TÊTE du champ, avant toute
    prose, sont des lignes de contrôle : la première ligne non vide qui
    n'est pas un label signé arrête définitivement la lecture. Un label
    copié dans un rapport, un email, une annexe ou un bloc de code
    n'est donc JAMAIS extrait ni promu — il reste dans le corps, où le
    parser le traitera comme du contenu documentaire (inférence legacy
    confirmable au mieux, jamais CONTRACTUAL_LABEL).

    Retourne (control_lines, business_text) — la concaténation des deux
    reconstitue le champ, sans perte.
    """
    lines = (text or "").split("\n")
    ctrl, i = [], 0
    while i < len(lines):
        raw_line = lines[i]
        stripped = raw_line.strip()
        # Correctif TCR-v9 (verdict v8, P0-4) — l'INFORMATION STRUCTURELLE
        # est jugée AVANT toute normalisation : une indentation de 4
        # espaces ou une tabulation matérialise un bloc de code ; ce
        # n'est jamais un champ de contrôle, et la zone s'arrête là.
        if stripped:
            _lead = raw_line[:len(raw_line) - len(raw_line.lstrip(" \t"))]
            if "\t" in _lead or len(_lead) >= 4:
                break
        if not stripped:
            if not ctrl:
                i += 1
                continue
            break
        core = stripped.strip(" \t-*#_")
        if core and A3_CONTROL_LINE_RE.match(core):
            ctrl.append(stripped)
            i += 1
            continue
        break
    # Correctif TCR-v9 — le contenu métier conserve son INDENTATION
    # (un bloc de code doit rester reconnaissable en aval) : seules les
    # lignes vides de tête et de queue sont retirées.
    rest = "\n".join(lines[i:]).strip("\n")
    return ctrl, rest


def extract_temporal_control_lines(*texts):
    """Lignes de contrôle temporel des champs BRUTS fournis — bornées
    à leur TÊTE (cf. split_temporal_control_prefix). Utilisé par
    l'assembleur de brief pour générer le bloc canonique avant toute
    décoration."""
    out = []
    for text in texts:
        for line in split_temporal_control_prefix(text)[0]:
            if line not in out:
                out.append(line)
    return out


def _a3_control_zone_end(text: str) -> int:
    """Correctif TCR-v7 — la zone de contrôle n'est PLUS une heuristique
    de préambule « Clé : valeur » (un email, un manuel, un historique y
    répondent) : elle est le préfixe de lignes qui SONT des lignes de
    contrôle temporel (labels signés), et rien d'autre. La première
    ligne qui n'est ni vide ni un label signé FERME la zone — un
    Subject:, un Manuel:, une Société: la ferment donc immédiatement.
    Le bloc de contrôle canonique généré par l'application (brief_ui)
    satisfait cette forme par construction."""
    pos = 0
    end = 0
    for line in (text or "").split("\n"):
        nxt = pos + len(line) + 1
        stripped = line.strip()
        if not stripped:
            pos = nxt
            continue
        core = stripped.strip(" \t-*#_")
        if core and A3_CONTROL_LINE_RE.match(core):
            end = nxt - 1 if nxt - 1 <= len(text) else len(text)
            pos = nxt
            continue
        return end
    return end


def _a3_prev_line_meta_intro(text: str, start: int) -> bool:
    head = text[:start]
    nl = head.rfind("\n")
    if nl < 0:
        return False  # première ligne du brief : zone de contrôle
    prev = head[:nl].rstrip()
    nl2 = prev.rfind("\n")
    prev_line = prev[nl2 + 1:].strip()
    if not prev_line:
        return False
    _prev_core = prev_line.strip(" \t-*#_")
    if _prev_core and A3_CONTROL_LINE_RE.match(_prev_core):
        # Un label signé au-dessus n'est pas une introduction
        # documentaire : deux labels consécutifs = conflit à détecter.
        return False
    return prev_line.endswith((":", "=", "\uff1a"))


def _a3_prev_clause_negated(text: str, start: int) -> bool:
    head = text[max(0, start - 200):start]
    clauses = [c.strip(" \t-*#_>\u2014\u2013") for c in
               re.split(r"[.;!?\n]", head)]
    clauses = [c for c in clauses if c]
    if len(clauses) < 1:
        return False
    # la clause du label lui-même n'est pas encore commencée : la
    # dernière clause complète est celle qui précède le label.
    return bool(_A3_PREV_NEGATION_RE.search(clauses[-1]))


# Correctif TCR-C3 — négation/métatexte APRÈS la valeur, dans la même
# clause : « à ne pas utiliser », « ancien paramètre »… → le label est
# de la prose sur un paramètre, pas une autorité.
_A3_POST_NEGATION_RE = re.compile(
    r"(?:[àa]\s+ne\s+pas\s+utiliser|ne\s+plus\s+utiliser|"
    r"not\s+to\s+be\s+used|no\s+longer\s+(?:used|valid)|"
    r"ancien\s+param[èe]tre|former\s+parameter|obsolete|deprecated|"
    r"previous|outdated|\bancien(?:ne)?s?\b|\bp[ée]rim[ée]e?\b)",
    re.IGNORECASE)


def _a3_post_negated(text: str, value_end: int) -> bool:
    tail = text[value_end:]
    stop = len(tail)
    for ch in ".\n;!?":
        k = tail.find(ch)
        if 0 <= k < stop:
            stop = k
    return bool(_A3_POST_NEGATION_RE.search(tail[:stop]))


_A3_STRONG_PREFIX_RE = re.compile(
    r"^(?:analysis[_ ]as[_ ]of[_ ]date\s*[=:]|"
    r"date\s+d['\u2019]analyse\s*:|"
    r"scenario\s+date\s*:)", re.IGNORECASE)

_G19R_PATTERNS = (
    # (regex, is_contractual_label)
    # Correctif TCR — label NON signé A3 : rétrogradé candidate.
    (re.compile(r"date\s+de\s+r[ée]f[ée]rence\s+de\s+l['\u2019]analyse"
                r"\s*[:=]\s*(?P<d>[^.,;!?\n]+)", re.IGNORECASE), False),
    (re.compile(r"\buse\s+(?P<d>.+?)\s+as\s+the\s+"
                r"(?:analysis|reference|cut[- ]?off)\s+date\b",
                re.IGNORECASE), False),
    (re.compile(r"\bset\s+the\s+analysis\s+date\s+to\s+"
                r"(?P<d>[^.,;:!?\n]+)", re.IGNORECASE), False),
    (re.compile(r"\btake\s+(?P<d>.+?)\s+as\s+the\s+"
                r"(?:analysis|reference)\s+date\b", re.IGNORECASE), False),
    (re.compile(r"\busing\s+the\s+situation\s+(?:at|of|on)\s+"
                r"(?P<d>[^.,;:!?\n]+)", re.IGNORECASE), False),
    (re.compile(r"\bas\s+it\s+stood\s+(?:on|at)\s+"
                r"(?P<d>[^.,;:!?\n]+)", re.IGNORECASE), False),
    (re.compile(r"\ben\s+vous\s+pla[çc]ant\s+au\s+"
                r"(?P<d>[^.,;:!?\n]+)", re.IGNORECASE), False),
    (re.compile(r"\bà\s+partir\s+de\s+la\s+situation\s+au\s+"
                r"(?P<d>[^.,;:!?\n]+)", re.IGNORECASE), False),
    (re.compile(r"\bretenez\s+le\s+(?P<d>.+?)\s+comme\s+date\s+"
                r"(?:d['\u2019]analyse|de\s+r[ée]f[ée]rence)\b",
                re.IGNORECASE), False),
)


def detect_analysis_as_of(brief: str) -> dict:
    """Gate 15 — intention v4 : detect_global_scenario_intent →
    parse_value_in_same_clause → resolve_candidates.

    Une date MÉTIER (mesure, clôture, question, titre, citation,
    négation) ne modifie JAMAIS l'autorité globale. Une demande globale
    doit être explicite, LOCALE À SA CLAUSE, non niée, non citée, unique
    et parseable. Cue forte sans valeur ou avec placeholder → INVALID
    (placeholder prioritaire sur toute date plus lointaine). Plusieurs
    valeurs distinctes → CONFLICT (famille INVALID, conflict:true,
    error_code TEMPORAL_AUTHORITY_CONFLICT). Panne → ERROR."""
    try:
        if not brief:
            return {"status": "NOT_REQUESTED", "value": None, "raw": "",
                    "error_code": "", "conflict": False, "candidates": []}
        # Correctif TCR-v6 — la zone de contrôle est mesurée sur le
        # brief ORIGINAL (masque et strip préservent les positions).
        _zone_end = _a3_control_zone_end(brief)
        # Correctif TCR-v3 — le code Markdown (inline/fenced) est masqué
        # AVANT le strip décoratif : un label dans des backticks est une
        # citation, jamais un champ actif — le strip ne doit pas
        # l'exposer au parser.
        brief = _a3_mask_code_spans(brief)
        # Gate 16 — le Markdown décoratif est MASQUÉ par des espaces
        # (positions et spans préservés) avant l'analyse grammaticale :
        # « - As of … », « **As of …** » redeviennent lisibles.
        brief = _strip_markdown_decor(brief)
        candidates = []
        source_map = {}

        def _mask(text, a, b):
            return text[:a] + (" " * (b - a)) + text[b:]

        ambiguous_hit = False
        legacy_candidates = []
        # 4e label A3 — « À la date du <date> : » — DÉCISIONNAIRE.
        for mdd in list(_A3_DATE_DU_RE.finditer(brief)):
            if _g15_cue_is_protected(brief, mdd.start()):
                continue
            # Correctif TCR-C3 — hors ancrage de champ (prose métier :
            # « Le chiffre d'affaires à la date du … : 100 M€ ») ou
            # négation/métatexte post-valeur : le span est MASQUÉ sans
            # produire ni autorité ni candidate.
            if (mdd.start() >= _zone_end
                    or not _a3_field_anchored(brief, mdd.start())
                    or _a3_prev_line_meta_intro(brief, mdd.start())
                    or _a3_prev_clause_negated(brief, mdd.start())
                    or _a3_post_negated(brief, mdd.end())):
                brief = _mask(brief, mdd.start(), mdd.end())
                continue
            st, val, raw = parse_value_in_same_clause(
                (mdd.group("d") or "").strip())
            if st in ("VALID", "INVALID"):
                candidates.append((st, val, mdd.group(0).strip(),
                                   (mdd.start(), mdd.end())))
                if val:
                    source_map[val] = "CONTRACTUAL_LABEL"
            else:
                candidates.append(("INVALID", None, mdd.group(0).strip(),
                                   (mdd.start(), mdd.end())))
            brief = _mask(brief, mdd.start(), mdd.end())
        # Correctif TCR (contrat A3/A5) — les formes NATURELLES ne
        # décident plus jamais : elles produisent des CANDIDATES
        # (valeur proposée, confirmable via le champ structuré),
        # résolues en AMBIGUOUS si aucun label A3 ne gouverne.
        for rx, _was_label in _G19R_PATTERNS:
            for m19 in rx.finditer(brief):
                if _g15_cue_is_protected(brief, m19.start()):
                    continue
                d_txt = (m19.group("d") or "").strip()
                st, val, raw = parse_value_in_same_clause(d_txt)
                if st == "VALID" and val:
                    legacy_candidates.append((val, m19.group(0).strip()))
                else:
                    # directive temporelle certaine, valeur indéterminable
                    ambiguous_hit = True
                brief = _mask(brief, m19.start(), m19.end())
        for kind, m, clause in detect_global_scenario_intent(brief):
            if kind == "nous":
                mm = m
                raw = mm.group(0)
                phase, month_name, year = (mm.group(1), mm.group(2),
                                           int(mm.group(3)))
                if month_name:
                    mon = _MONTHS.get(month_name.lower(), 6)
                    day = 15
                else:
                    mon, day = _phase_to_day(phase or "")
                try:
                    _v19 = date(year, mon, day).isoformat()
                    # Correctif TCR — forme naturelle : candidate.
                    legacy_candidates.append((_v19, raw))
                except Exception:
                    ambiguous_hit = True
                continue
            if kind == "asof":
                st, val, raw = parse_value_in_same_clause(clause)
                # Correctif TCR — « as of » n'est pas un label A3 :
                # candidate confirmable, jamais autorité.
                if st == "VALID" and val:
                    legacy_candidates.append((val, f"as of {raw}".strip()))
                elif st == "INVALID":
                    ambiguous_hit = True
                continue
            st, val, raw = parse_value_in_same_clause(clause)
            prefix = m.group(0).strip()
            if st is None:
                if kind == "strong":
                    # délégation : « Contexte temporel : Nous sommes
                    # début 2023 » = UNE directive — la valeur est portée
                    # par la forme nous-sommes de la MÊME clause (déjà
                    # collectée par ailleurs) ; pas de candidate INVALID.
                    if _NOUS_SOMMES_RE.search(clause):
                        continue
                    # cue explicite sans valeur → la demande ne
                    # disparaît jamais silencieusement (label A3 →
                    # INVALID ; cue naturelle → AMBIGUOUS confirmable)
                    if _A3_STRONG_PREFIX_RE.match(prefix):
                        candidates.append(("INVALID", None, prefix,
                                           (m.start(), m.end())))
                    else:
                        ambiguous_hit = True
                continue
            _is_a3 = (kind == "strong"
                      and bool(_A3_STRONG_PREFIX_RE.match(prefix)))
            # Correctif TCR-C3 — un label A3 hors ancrage de champ
            # (« Le rapport cite Date d'analyse : … ») ou nié/métatexte
            # APRÈS la valeur (« … à ne pas utiliser ») est de la PROSE :
            # ni autorité, ni candidate, ni INVALID.
            if _is_a3 and (m.start() >= _zone_end
                           or not _a3_field_anchored(brief, m.start())
                           or _a3_prev_line_meta_intro(brief, m.start())
                           or _a3_prev_clause_negated(brief, m.start())
                           or _a3_post_negated(
                               brief, m.end() + len(raw or ""))):
                continue
            if _is_a3:
                candidates.append((st, val, f"{prefix} {raw}".strip(),
                                   (m.start(), m.end() + len(raw))))
                if val and val not in source_map:
                    source_map[val] = "CONTRACTUAL_LABEL"
            else:
                # Correctif TCR — cue forte HORS dénominateur A3
                # (« on se place au », « contexte temporel », variantes
                # sans deux-points…) : candidate confirmable.
                if st == "VALID" and val:
                    legacy_candidates.append(
                        (val, f"{prefix} {raw}".strip()))
                else:
                    ambiguous_hit = True
        out19 = resolve_candidates(candidates)
        out19["candidate_value"] = None
        out19["candidate_raw"] = ""
        if out19.get("status") == "NOT_REQUESTED" and (legacy_candidates
                                                       or ambiguous_hit):
            # Correctif TCR — inférence naturelle SANS autorité A3 :
            # jamais VALID, jamais LIVE silencieux → AMBIGUOUS avec la
            # valeur CANDIDATE exposée (confirmation une-action, champ
            # structuré, nouveau run). Plusieurs valeurs distinctes ou
            # valeur indéterminable → AMBIGUOUS sans candidate.
            vals = sorted({v for v, _ in legacy_candidates})
            cand_v = vals[0] if len(vals) == 1 and not ambiguous_hit else None
            cand_r = (legacy_candidates[0][1]
                      if cand_v and legacy_candidates else "")
            out19 = {"status": "AMBIGUOUS", "value": None,
                     "raw": (cand_r or
                             "temporal directive without determinable date"),
                     "error_code": "TEMPORAL_AUTHORITY_AMBIGUOUS",
                     "conflict": False, "candidates": [],
                     "candidate_value": cand_v, "candidate_raw": cand_r}
        out19["intent_source"] = (
            "CONTRACTUAL_LABEL" if out19.get("status") == "VALID"
            else ("LEGACY_CANDIDATE"
                  if (out19.get("status") == "AMBIGUOUS"
                      and out19.get("candidate_value")) else "NONE"))
        return out19
    except Exception:
        return {"status": "ERROR", "value": None, "raw": "detector failure",
                "error_code": "TEMPORAL_AUTHORITY_ERROR",
                "conflict": False, "candidates": []}


def detect_analysis_as_of_date(brief: str) -> Optional[str]:
    """Compat gate 11 — renvoie la date ISO si la demande est VALIDE,
    sinon None. Le tri-état vit dans detect_analysis_as_of()."""
    return detect_analysis_as_of(brief).get("value")

def reconcile_external_skip(attachments_only: bool, was_forced: bool):
    """F.6.7.1 (audit P1/P2) — réconcilie l'état UI « external_sources_skip » avec le
    mode source du brief COURANT, qui doit toujours primer sur un état UI hérité.

    Renvoie (override, forced) :
      - override : True/False à appliquer à l'état, ou None = ne pas toucher
        (préserve un choix manuel utilisateur sur un brief ouvert) ;
      - forced   : nouvelle valeur du drapeau « forcé par un brief ATTACHMENTS_ONLY ».

    Cas :
      - brief ATTACHMENTS_ONLY            → (True, True)   sources externes coupées ;
      - brief OUVERT après un attach-only → (False, False) on lève le verrou hérité ;
      - brief OUVERT sans forçage hérité  → (None, False)  on ne piétine pas l'UI.
    """
    if attachments_only:
        return True, True
    if was_forced:
        return False, False
    return None, False


# ── F.6.8 (audit dossier réseau de soins) — date d'analyse par défaut pour une revue de clôture ──
import re as _re_cr

_CLOSED_FY_PATTERNS = [
    _re_cr.compile(r"revue\s+de\s+cl[ôo]ture\s+(?:FY\s?)?20(\d{2})", _re_cr.I),
    _re_cr.compile(r"cl[ôo]ture\s+(?:annuelle\s+)?(?:FY\s?)?20(\d{2})", _re_cr.I),
    _re_cr.compile(r"arr[êe]t[ée]\s+des\s+comptes\s+(?:FY\s?)?20(\d{2})", _re_cr.I),
    _re_cr.compile(r"\bFY\s?20(\d{2})\b", _re_cr.I),
]


def infer_closing_review_as_of(brief):
    """Pour une revue de clôture FY20XX sans date d'analyse explicite, retourne une
    date d'analyse par défaut = 15 février 20(XX+1) (CODIR de clôture / Comité d'audit
    juste après l'arrêté). None si aucun exercice clos détectable.

    On ne s'appuie QUE sur des motifs forts (« revue de clôture », « clôture »,
    « arrêté des comptes », « FY ») et on prend l'exercice le PLUS FRÉQUEMMENT cité
    — pour ne pas confondre l'exercice clos avec des années incidentes (acquisitions
    post-clôture, jalons futurs…). En cas d'égalité, le plus ancien (l'exercice revu).
    """
    if not brief or not isinstance(brief, str):
        return None
    from collections import Counter
    years = []
    for rgx in _CLOSED_FY_PATTERNS:
        for m in rgx.finditer(brief):
            try:
                years.append(2000 + int(m.group(1)))
            except Exception:
                continue
    if not years:
        return None
    counts = Counter(years)
    top = counts.most_common(1)[0][1]
    fy = min(y for y, c in counts.items() if c == top)   # exercice clos revu
    return f"{fy + 1:04d}-02-15"
