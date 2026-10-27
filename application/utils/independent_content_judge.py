"""v62.13.9.4.10 — second juge de contenu, écrit indépendamment du guard.

Contre-audit 30/08/2026 : l'oracle re-jugeait les octets finaux en appelant
``board_scrutiny_guard``, c'est-à-dire le moteur qui avait déjà statué en
amont — un second avis rendu par le premier juge. Ce module est un
classifieur SÉPARÉ : il n'importe ni ``board_scrutiny_guard``, ni
``quantity_ledger``, ni ``editorial_quantity``, et n'emprunte aucune de leurs
tables. Ses lexiques, ses exemptions et sa règle de décision sont écrits pour
lui seul, à partir de la doctrine (Option B stricte), pas du code existant.

Règle unique, volontairement SUR-STRICTE (le verdict de production est
l'UNION des deux juges — une sur-rétention bloque la distribution, elle ne
fabrique jamais un faux vert) :

    une unité de contenu qui porte une grandeur non exemptée ET un lexème de
    planification, de volition ou de projection, sans certification par un
    claim du run, est retenue.

Le seul garde-fou est le passé factuel réel, calculé ici aussi de façon
autonome : un fait daté et accompli reste un fait.
"""
from __future__ import annotations

import re

# ── Grandeurs (table propre) ───────────────────────────────────────────────
_QTY_RE = re.compile(
    r"(?P<cur1>[€£$])?\s*"
    r"(?P<num>\d(?:[\d\u00A0\u202F ]*\d)?(?:[.,]\d+)?)"
    r"\s*(?P<scale>k€|M€|Md€|k|K|M|bn|Bn|Md|md)?"
    r"\s*(?P<cur2>€|£|\$|EUR|GBP|USD)?"
    r"\s*(?P<pct>%|pp\b)?", re.I)   # v62.13.9.4.11 — insensible à la casse :
# « €15m » en minuscule n'était pas mis à l'échelle (15 au lieu de 15 000 000),
# donc ni certifié ni comparé correctement. Défaut trouvé en reproduisant les
# cas L2 du contre-audit du 31/08/2026.
_WORDNUM_RE = re.compile(
    r"\b(?:deux|trois|quatre|cinq|six|sept|huit|neuf|dix|douze|quinze|vingt|"
    r"trente|quarante|cinquante|cent|cents|mille|"
    r"two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen|twenty|"
    r"thirty|forty|fifty|hundred|thousand)\b", re.I)
_SCALE = {"k": 1e3, "m": 1e6, "bn": 1e9, "md": 1e9,
          "k€": 1e3, "m€": 1e6, "md€": 1e9}
_CUR = {"€": "EUR", "EUR": "EUR", "£": "GBP", "GBP": "GBP",
        "$": "USD", "USD": "USD"}

# ── Exemptions (table propre, volontairement étroite) ──────────────────────
# ORDRE SIGNIFIANT : les motifs longs (dates complètes, versions, périodes)
# passent AVANT le millésime nu, sinon « 2026-09-01 » se réduit à « 2026 »
# et laisse « 09 » et « 01 » au jugement.
_EXEMPT_SPANS = (
    r"\bv?\d+(?:\.\d+){2,}(?:-[\w.]+)*",                # versions/builds
    r"\b\d{1,2}[/.]\d{1,2}[/.](?:19|20)\d{2}\b",        # dates
    r"\b(?:19|20)\d{2}-\d{1,2}-\d{1,2}\b",
    r"\b(?:FY|H[12]|S[12]|[QT][1-4])\s?(?:19|20)\d{2}\b",  # période datée
    r"\b[QTST][1-4](?:\s?[-–]\s?[QTST]?[1-4])?\b",        # trimestres nus
    r"\b(?:p\.|page|pages|§)\s?\d+\b",                  # appareil documentaire
    # NB : pas de \b final — après « ) » il n'y a pas de frontière de mot,
    # le groupe « (4) » serait abandonné au backtracking et « 4 » repartirait
    # au jugement (« AI Act art. 50(4) »).
    r"\bart(?:icle)?\.?\s?\d+(?:\s?\(\d+\))?(?!\w)",
    r"\bvoir\s+\d+(?:\.\d+)*\b|\bsee\s+\d+(?:\.\d+)*\b",
    r"\b(?:ISO|EN|NF|IEC|CEI|RGPD|GDPR|UE|EU)\s?\d[\d\s/-]*\b",  # normes
    r"\((?:UE|EU)\)\s?\d{4}/\d+",                       # règlements européens
    r"\b(?:r[èe]glement|regulation|directive)\s+\(?(?:UE|EU)\)?\s?\d{4}/\d+",
    r"\b100\s?%",                                        # totalité qualitative
    # composition STRUCTURELLE d'un plan : un plan « compte 5 axes » décrit
    # son architecture, il ne promet aucun livrable chiffré (les grandeurs
    # métier — centres, recrutements, montants — restent jugées).
    r"\b\d+\s?(?:axes?|piliers?|volets?|chantiers?|workstreams?|"
    r"phases?|[ée]tapes?|lots?|chapitres?|sections?|th[èe]mes?|"
    r"briques?|modules?|streams?|blocs?)\b",
    r"\b\d{9,14}\b",                                    # SIREN/SIRET
    r"\bSCN[-\w]*\d+\b",                                # registre de quarantaine
    # v62.13.9.4.10 — durée historique révolue : « following three
    # consecutive years of revenue decline » décrit un passé, pas une cible.
    r"\b(?:deux|trois|quatre|cinq|six|sept|huit|neuf|dix|"
    r"two|three|four|five|six|seven|eight|nine|ten|\d{1,2})\s+"
    r"(?:consecutive\s+|cons[ée]cutif(?:ve)?s?\s+|derni(?:ers?|[èe]res?)\s+)?"
    r"(?:ann[ée]es?|ans|mois|trimestres?|semestres?|"
    r"years?|months?|quarters?|half[-\s]years?)\b",
    r"\b(?:options?|variantes?|sc[ée]narios?|axes?|priorit[ée]s?|"
    r"hypoth[èe]ses?|volets?|piliers?)\s?(?:n°\s?)?\d+\b",   # renvoi ordinal
    r"\bB1\.\d[\d.]*\b|\bM6B\b",                        # jalons produit
    r"\b(?:couche|layer|niveau|level|slide|section|chapitre|chapter|"
    r"annexe|annex|figure|tableau|table|étape|step|phase|lot)\s?\d+\b",
    r"(?:^|[\u2022\u2713\u2714•✅⛔🔍\-–—>]\s*)\d{1,2}(?:\.\d+)*[.)]?\s",  # numérotation
    r"^\s*\d+(?:\.\d+)+\s",                            # numéro de section « 4.2 »
    r"\b(?:19|20)\d{2}\b",                              # millésime nu (en dernier)
    r"\b\d+\s?(?:salariés?|employees?)\b",              # tranche d'effectif
    r"\b\d{1,3}\s?[-–]\s?\d{1,3}\b(?=\s*(?:salariés?|employees?))",
)
# v62.13.9.4.12.7 — DATE CALENDAIRE COMPLÈTE. Le run du 02/09/2026 a bloqué
# l'export sur « avant le 15 septembre 2026 » : l'année était exemptée, pas
# le QUANTIÈME. Un jour de calendrier n'est pas une grandeur d'affaires ; le
# juger revient à interdire toute échéance datée.
_CAL_DATE_RE = re.compile(
    r"\b\d{1,2}(?:er)?\s+(?:janvier|février|fevrier|mars|avril|mai|juin|"
    r"juillet|août|aout|septembre|octobre|novembre|décembre|decembre|"
    r"january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\b", re.I)

_EXEMPT_RE = re.compile("|".join(_EXEMPT_SPANS), re.I | re.M)

# Un chiffre collé à des lettres est un CODE (M6B, C3X, B1.3), jamais une
# grandeur — classe « code produit » établie au cycle 13.9.4.
_CODE_GLUED_RE = re.compile(r"[A-Za-zÀ-ÿ]\d|\d[A-Za-zÀ-ÿ]")

# Cadre de planification : une DURÉE qui nomme la fenêtre d'un plan est le
# cadre, pas une cible chiffrée (« Plan d'action 90 jours », « 24-Month
# Reset »). Le montant qui l'accompagnerait reste, lui, jugé.
_PLAN_WINDOW_RE = re.compile(
    r"\d+\s?[-\s]?(?:jours?|mois|semaines?|ans?|années?|"
    r"days?|months?|weeks?|years?)\b", re.I)
_PLAN_WORD_RE = re.compile(
    r"\b(?:plans?|programmes?|roadmaps?|feuilles?\s+de\s+route|reset|"
    r"sprint|cycles?|horizons?|"
    # v62.13.9.4.15 — un objectif « à 30 jours » est cadré par sa durée ;
    # seule la durée est neutralisée, les montants de la ligne restent jugés.
    r"objectifs?|priorit[ée]s?|targets?|goals?|priorities)\b", re.I)

# marqueurs déjà neutralisés par la réparation : ne jamais re-retenir
# v62.13.9.4.10 — ligne d'ARBITRAGE : une alternative explicitement soumise
# à décision (« À ARBITRER — capex 10 M€/an baseline vs 15 M€/an accéléré »)
# présente des OPTIONS, pas un engagement chiffré. C'est la matière même d'un
# document de CoDIR ; le moteur A ne la retenait pas, le second juge si.
_ARBITRATION_RE = re.compile(
    r"[àa]\s+arbitrer|arbitrage\s*:|to\s+be\s+arbitrated|for\s+arbitration|"
    r"\b(?:option|sc[ée]nario|variante|hypoth[èe]se)\s*[AB1-9]\b.{0,60}\bvs\b",
    re.I)

_NEUTRALIZED_RE = re.compile(
    r"montant retir[ée]|valeur retir[ée]|amount withheld|value withheld|"
    r"à dimensionner|to be dimensioned|non établie?|not established|"
    r"à confirmer sur pièce|to be confirmed on source|à qualifier|"
    # marqueurs de SORTIE du produit (scission tags produit/contenu du
    # cycle 9.4.6) : ce sont les traces d'une retenue déjà opérée, jamais
    # du contenu à juger — les re-retenir serait une boucle.
    r"sc[ée]nario chiffr[ée] retir[ée]|quantified scenario removed|"
    r"scenario removed from the document|retir[ée] du document|"
    r"non valid[ée] — d[ée]tail conserv[ée]|not validated — detail kept|"
    r"SC[ÉE]NARIO ILLUSTRATIF|ILLUSTRATIVE SCENARIO|"
    r"proposition (?:chiffr[ée]e|quantifi[ée]e) [ée]cart[ée]e|"
    r"cible chiffr[ée]e [ée]cart[ée]e|quantified (?:item|proposal) with(?:drawn|held)|"
    r"voir l['\u2019]annexe|see the .{0,20}annex", re.I)

# ── Lexiques de projection (table propre) ──────────────────────────────────
_PLAN_LEX = (
    r"objectifs?|cibl[ée]?e?s?|ambitions?|visions?|"
    r"plans?|strat[ée]gies?|programmes?|projets?|roadmaps?|"
    r"feuilles?\s+de\s+route|trajectoires?|sc[ée]narios?|"
    r"targets?|goals?|strategy|strategies|programs?|scenarios?|"
    r"backlogs?|initiatives?|blueprints?|frameworks?")
_INTENT_LEX = (
    r"vis(?:e|ons|ez|ent|er)|veu[tx]|voulons|voulez|veulent|vouloir|"
    r"souhait\w*|d[ée]sir\w*|esp[èé]r\w*|pr[ée]voi\w*|pr[ée]voir|envisag\w*|"
    r"compte\s+(?:ouvrir|recruter|lancer|d[ée]ployer|atteindre)|"
    r"wants?|wish\w*|desir\w*|intends?|intending|aims?|aiming|"
    r"seeks?|seeking|striv\w*|plans?\s+to|expects?\s+to|"
    r"ouvrir|recruter|lancer|d[ée]ployer|cr[ée]er|construire|budg[ée]ter|"
    r"investir|financer|moderniser|r[ée]nover|migrer|former|"
    r"open|hire|launch|deploy|create|build|invest|fund|modernise|modernize|"
    r"renovate|migrate|train")
_FUTURE_LEX = (
    r"futurs?|futures?|[àa]\s+venir|upcoming|prospectives?|"
    r"souhait[ée]e?s?|d[ée]sir[ée]e?s?|desired|intended|planned|projet[ée]e?s?|"
    r"pr[ée]visionnel(?:le)?s?|sera|seront|devra|devront|"
    r"will|shall|would|d['\u2019]ici\s+(?:20\d{2}|fin)|by\s+(?:FY)?\s?20\d{2}|"
    r"[àa]\s+terme|horizon")
_PROJECTION_RE = re.compile(
    rf"\b(?:{_PLAN_LEX})\b|\b(?:{_INTENT_LEX})\b|\b(?:{_FUTURE_LEX})\b", re.I)

# ── Passé factuel (table propre) ───────────────────────────────────────────
_OWN_PAST_RE = re.compile(
    r"\b(?:a|ont|avait|avaient|est|sont|était|étaient|fut|furent)\s+"
    r"(?:[ée]t[ée]\s+)?\w+[ée]s?\b|"
    r"\b(?:r[ée]alis[ée]|livr[ée]|atteint|achev[ée]|ouvert|sign[ée]|"
    r"engag[ée]|lanc[ée]|d[ée]marr[ée]|constat[ée]|enregistr[ée])"
    r"e?s?\b|"
    r"\b(?:atteignait|atteignaient|comptait|comptaient|s['\u2019]élevait|"
    r"représentait|affichait|progressait|reculait)\b|"
    r"\b(?:was|were|had|has\s+been|have\s+been|reached|delivered|achieved|"
    r"completed|opened|signed|launched|started|recorded|changed|increased|"
    r"decreased|declined|rose|fell|"
    # v62.13.9.4.10 — récit financier au passé : le contre-audit du
    # 31/08/2026 a montré dossier anglophone coté bloqué sur « Revenue peaked FY2023 …
    # then collapsed –22% », un fait historique. Le vocabulaire de la
    # trajectoire manquait au juge indépendant.
    r"peaked|collapsed|accelerated|slowed|dropped|plunged|tumbled|"
    r"surged|jumped|grew|shrank|shrunk|rebounded|recovered|stabilised|"
    r"stabilized|deteriorated|worsened|improved|contracted|expanded|"
    r"remained|stood\s+at|came\s+in\s+at|posted|reported|"
    r"a\s+recul[ée]|a\s+progress[ée]|a\s+atteint|a\s+chut[ée]|"
    r"culmin[ée]|s['\u2019]est\s+\w+[ée])\b", re.I)
_OWN_FUTURE_OVERRIDE_RE = re.compile(
    r"\b(?:sera|seront|devra|devront|will|shall|d['\u2019]ici|by\s+(?:FY)?\s?20\d{2}|"
    r"[àa]\s+venir|upcoming|futurs?|futures?|desired|souhait[ée]e?s?)\b", re.I)

_ALLOWED_STATUS = frozenset({"CONFIRMED_ON_PAGE",
                             "DERIVED_FROM_CONFIRMED_ON_PAGE"})
_ALLOWED_TYPE = frozenset({"FACT", "DERIVED"})
_LABEL_TOK_RE = re.compile(r"[a-zà-öø-ÿ]{4,}", re.I)
# distance maximale entre un lexème de projection et la grandeur qu'il
# gouverne (caractères) — large, car le juge reste volontairement strict
_GOVERN_WINDOW = 90
# nom de structure suivant un nombre en lettres (« trois piliers »)
_STRUCTURE_NOUN_RE = re.compile(
    r"\s*(?:axes?|piliers?|volets?|chantiers?|workstreams?|phases?|"
    r"[ée]tapes?|lots?|chapitres?|sections?|th[èe]mes?|briques?|"
    r"modules?|streams?|blocs?)\b", re.I)


def _magnitude(m: re.Match) -> tuple[float, str | None, bool] | None:
    raw = (m.group("num") or "").replace("\u00A0", "").replace("\u202F", "").replace(" ", "")
    if not raw:
        return None
    seps = set(re.findall(r"[.,]", raw))
    try:
        if len(seps) == 1:
            sep = seps.pop()
            parts = raw.split(sep)
            if len(parts) == 2 and len(parts[1]) == 3 and len(parts[0]) <= 3:
                val = float("".join(parts))
            else:
                val = float(raw.replace(sep, "."))
        elif seps:
            last = max(raw.rfind("."), raw.rfind(","))
            dec = raw[last]
            val = float(raw.replace("," if dec == "." else ".", "").replace(dec, "."))
        else:
            val = float(raw)
    except ValueError:
        return None
    scale_raw = (m.group("scale") or "").lower()
    cur = m.group("cur1") or m.group("cur2") or ""
    if scale_raw in ("k€", "m€", "md€"):
        cur = "€"
    val *= _SCALE.get(scale_raw, 1.0)
    return (val, _CUR.get(cur.upper() if len(cur) > 1 else cur), bool(m.group("pct")))


def _certified(unit: str, claims) -> set[tuple]:
    """Grandeurs certifiées par les claims du run (calcul autonome)."""
    out: set[tuple] = set()
    for c in (claims or []):
        get = c.get if isinstance(c, dict) else (lambda k: getattr(c, k, None))
        # v62.13.9.4.11 — le STATUT PROBATOIRE est exigé, sans repli.
        # Le contre-audit du 31/08/2026 a montré que le second juge certifiait
        # encore une valeur sur le seul `claim_type` FACT/DERIVED — une
        # typologie de contenu, pas une preuve. Le claim binding avait été
        # durci au cycle précédent, pas ce module : l'asymétrie laissait
        # passer trois certifications abusives.
        if str(get("proof_status") or "").upper() not in _ALLOWED_STATUS:
            continue
        label = " ".join(str(get(k) or "") for k in ("label", "metric", "metric_id"))
        toks = {t.lower() for t in _LABEL_TOK_RE.findall(label)}
        if toks and not (toks & {t.lower() for t in _LABEL_TOK_RE.findall(unit)}):
            continue
        nv = get("normalized_value")
        cur = str(get("currency") or "").upper() or None
        pct = str(get("unit") or "").upper() == "PCT"
        if isinstance(nv, (int, float)):
            out.add((round(float(nv), 6), _CUR.get(cur, cur), pct))
        for comp in (get("numeric_components") or []):
            if isinstance(comp, dict) and isinstance(comp.get("value"), (int, float)):
                out.add((round(float(comp["value"]), 6),
                         _CUR.get(cur, cur), str(comp.get("kind") or "") == "pct"))
        for src in (str(get("value") or ""), str(get("display_value") or "")):
            for m in _QTY_RE.finditer(src):
                g = _magnitude(m)
                if g:
                    out.add((round(g[0], 6), g[1], g[2]))
    return out


def _failed_certification(unit: str, claims) -> str | None:
    """v62.13.9.4.11 — une certification TENTÉE et RATÉE n'est pas une
    absence de preuve : c'est un échec de preuve, et il se retient.

    Distinction posée par le contre-audit du 31/08/2026 : une grandeur qu'un
    claim prétend couvrir — même valeur — mais dont le statut probatoire est
    absent, invalide ou auto-déclaré, doit être retenue. Une grandeur qu'aucun
    claim ne revendique reste, elle, du ressort du premier juge : sans cette
    distinction, le second juge retiendrait tout fait historique non claimé et
    deviendrait censurant.
    """
    if not claims:
        return None
    masked = _EXEMPT_RE.sub(lambda m: " " * len(m.group(0)), str(unit or ""))
    masked = _CAL_DATE_RE.sub(lambda m: " " * len(m.group(0)), masked)
    magnitudes = []
    for m in _QTY_RE.finditer(masked):
        if not (m.group("num") or "").strip():
            continue
        g = _magnitude(m)
        if g is not None:
            magnitudes.append((round(g[0], 6), m.group(0).strip()))
    if not magnitudes:
        return None
    certified = _certified(unit, claims)
    for c in claims:
        get = c.get if isinstance(c, dict) else (lambda k: getattr(c, k, None))
        if str(get("proof_status") or "").upper() in _ALLOWED_STATUS:
            continue                      # statut recevable : hors périmètre
        nv = get("normalized_value")
        if not isinstance(nv, (int, float)):
            continue
        for value, raw in magnitudes:
            if abs(value - float(nv)) > 1e-6 * max(1.0, abs(float(nv))):
                continue
            if any(abs(value - e[0]) <= 1e-6 * max(1.0, abs(e[0]))
                   for e in certified):
                continue                  # certifiée par ailleurs
            return raw
    return None


def _own_factual_past(unit: str) -> bool:
    if _OWN_FUTURE_OVERRIDE_RE.search(unit):
        return False
    return bool(_OWN_PAST_RE.search(unit))


def _declared_prospective_hit(text: str, declared) -> str | None:
    """v62.13.9.4.11 (A1) — grandeur déclarée prospective à la génération.

    Le second juge consulte les déclarations comme une SOURCE, pas comme un
    moteur : il n'emprunte toujours aucune table ni aucun code au guard, son
    indépendance est intacte. La déclaration ne fait qu'ajouter des valeurs à
    retenir — jamais en retirer.
    """
    if not declared:
        return None
    # v62.13.9.4.12 — l'index localisé décide ; le jeu de valeurs nues n'est
    # accepté qu'en repli de compatibilité (il ne doit plus être produit).
    finder = getattr(declared, "declared_target_in", None)
    if callable(finder):
        entry = finder(text)
        return str(entry.get("value")) if entry else None
    for m in re.finditer(r"\d[\d\s\u00A0\u202F.,]*", text):
        raw = re.sub(r"[\s\u00A0\u202F]", "", m.group(0)).replace(",", ".")
        if re.fullmatch(r"\d+\.0+", raw):
            raw = raw.split(".")[0]
        if raw in declared:
            return m.group(0).strip()
    return None


_OPTION_CHAIN_RE = re.compile(r"\bOptions?\s+\d{1,2}(?:\s*(?:vs\.?|/|,|et|ou|and|or|[-–]|\+|&)\s*(?:Options?\s+)?\d{1,2})+\b", re.I)   # v62.13.9.4.28

_TIMESTAMP_RE = re.compile(
    r"\b\d{1,2}[/.\-]\d{1,2}[/.\-](?:19|20)\d{2}(?:\s+\d{1,2}[:h]\d{2}(?::\d{2})?)?\b"   # v62.13.9.4.31.1 — jj-mm-aaaa, jj.mm.aaaa aussi
    r"|\b(?:19|20)\d{2}-\d{2}-\d{2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?\b"
    r"|\b\d{1,2}[:h]\d{2}(?::\d{2})?\b", re.I)


_EPISTEMIC_CAVEAT_RE = re.compile(
    r"n['’]est\s+pas\s+sourc|non\s+sourc|pas\s+sourc|sans\s+source|aucune\s+source(?:\s+publique)?|"
    r"absence\s+de\s+donn[ée]e|pas\s+de\s+donn[ée]e|non\s+consolid|ne\s+fournit\s+(?:pas|aucun)|"
    r"ne\s+(?:doit|peut)\s+pas\s+[êe]tre\s+(?:repris|retenu|utilis)|n['’]est\s+pas\s+(?:v[ée]rifi|[ée]tay|confirm|document)|"
    r"not\s+sourced|unsourced|no\s+source|cannot\s+be\s+(?:verified|relied|used)|not\s+(?:verified|substantiated|documented)", re.I)
_QUOTED_FIGURE_RE = re.compile(
    r"[«\"“]\s*[^»\"”]*\d[^»\"”]*\s*[»\"”]"
    r"|\d[\d\s\u00a0.,]*\s*(?:M€|k€|Md€|€|%|M\$|bn)\s*\((?:19|20)\d{2}\)")   # v62.13.9.4.20.1 — « 800 M€ (2023) » daté

# v62.13.9.4.22 — marqueurs de planification, COPIE LOCALE (le second juge
# n'importe jamais le moteur de production, c'est son contrat) : numéro de
# rangée, cellule de priorité « | 2 », plage de dates, index de semaine,
# « (PRIORITÉ n) », « P1 », mois/année, semestre « S1 2026 ».
_PLANNING_LOCAL_RE = re.compile(
    r"^\|?\s*\*{0,2}\d{1,3}\*{0,2}\s*(?=\|)"
    r"|\|\s*\d{1,2}\s*(?:\||$)"
    r"|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\s*[–\-—]\s*\d{1,2}/\d{1,2}(?:/\d{2,4})?"
    # v62.13.9.4.29 — date courte jj/mm et repères de planning T0 / T+90 jours
    r"|(?:\b(?:avant|le|au|dès|d['’]ici|jusqu['’]au|du|entre|pour le|à partir du|before|by|on|until)\s+\d{1,2}/\d{1,2}\b|\b(?:1[3-9]|2\d|3[01])/(?:0?[1-9]|1[0-2])\b|\b(?:0?[1-9]|[12]\d|3[01])/0[1-9]\b)(?!\s*/)|\bT0\b|\b[TJM]\s?[+\-]\s?\d{1,3}(?:\s?(?:j|jours?|d|days?|m|mois|months?|s|semaines?|weeks?))?\b"
    r"|\b(?:semaines?|weeks?)\s+\d{1,2}(?:\s*[–\-]\s*\d{1,2})?\b"
    r"|\((?:priorit[ée]|priority)\s+\d{1,2}\)|\bP[1-5]\b"
    r"|\b\d{1,2}/(?:19|20)\d{2}\b|\bS[12]\s+20\d{2}\b|\bH[12]\s+20\d{2}\b"
    # v62.13.9.4.25 — « Risque n°1 », « Arbitrage #2 » : un numéro d'ordre
    # étiqueté n'est jamais une grandeur (« 1 » déclaré cible ailleurs le
    # contaminait — contre-audit v24, conclusion de synthèse).
    r"|\b(?:n[°º]|no\.?|#)\s*\d{1,3}\b"
    # v62.13.9.4.26 — « [n4] », « n4] », « A1. », « R2 — » : labels d'ordre des
    # agents (run 13:10 : le « 4 » de « [n4] » faisait retenir la décision).
    r"|\[\s*[nNdDaArR]?\s*\d{1,2}\s*\]|\(\s*[nN]\d{1,2}\s*\)|\b[nN]\d{1,2}\]|\b[ADRP]\d{1,2}(?=\s*[.:)—–-])"
    # v62.13.9.4.27 — « industrie 4.0 », « web 3.0 » : nom de génération, jamais une grandeur
    r"|\b[A-Za-zÀ-ÿ&]{3,}\s+\d\.0\b"
    # v62.13.9.4.31 — « §6 — Plan d'actions » : numéro de rubrique du sommaire
    r"|§\s*\d{1,3}\s*[—–-]?"
    # v62.13.9.4.28 — « Option 1 vs 2 vs 3 », « Option 1, 2 ou 3 » : numéros d'options
    r"|\bOptions?\s+\d{1,2}(?:\s*(?:vs\.?|/|,|et|ou|and|or|[-–]|\+|&)\s*(?:Options?\s+)?\d{1,2})+\b"
    # v62.13.9.4.32 (A) — repères de période « T1 2027 », « T1-T2 2027 », « Q3 »,
    # et numéros d'ordre étiquetés « option 2 », « phase 1 », « étape 3 » : un
    # identifiant n'est jamais une grandeur (run réel ee08f0 : le « 1 » de
    # « (T1 2027) » faisait neutraliser la phrase de recommandation). Copie
    # locale, parité avec le typeur.
    r"|\b[TQ][1-4](?:\s*[–\-—]\s*[TQ]?[1-4])?(?:\s+(?:19|20)\d{2})?\b"
    r"|\b(?:1er|2e|2nd|2ème|3e|3ème|4e|4ème|1st|2nd|3rd|4th)\s+(?:trimestre|semestre|quarter|half)\b"
    r"|\b(?:trimestre|semestre|quarter|half)\s+[1-4]\b"
    # v62.13.9.4.32 (A) — « trois options », « 2 scénarios » : compte d'éléments de structure, pas une grandeur
    r"|\b(?:\d{1,2}|deux|trois|quatre|cinq|six|two|three|four|five|six)\s+(?=(?:options?|sc[ée]narios?|axes?|phases?|[ée]tapes?|piliers?|leviers?|chantiers?|volets?|priorit[ée]s?|pistes?|alternatives?|orientations?|hypoth[èe]ses?|jalons?|trajectoires?|variantes?)\b)",
    re.I | re.M)

# v62.13.9.4.32 (A) — « option 2 », « phase 1 », « étapes 1, 2 et 3 » : le NOM est
# conservé (le juge s'en sert pour reconnaître un compte de structure), seul le
# numéro d'ordre est blanchi.
_ORDINAL_LABEL_RE = re.compile(r"(\b(?:options?|phases?|[ée]tapes?|axes?|sc[ée]narios?|lots?|volets?|piliers?|priorit[ée]s?|jalons?|leviers?|chantiers?|hypoth[èe]ses?|vagues?|niveaux?|variantes?|alternatives?|orientations?|pistes?|sprints?|versions?|ann[ée]es?|steps?|stages?|workstreams?|tracks?|waves?|levels?|years?|streams?|paliers?))(\s*(?:n[°º]|no\.?|#)?\s*\d{1,2}(?:\s*(?:/|,|et|ou|and|or|[–\-])\s*\d{1,2})*\b(?!\s*(?:%|€|k€|m€|md€|k|m|jours?|mois|ans?|semaines?|days?|months?|years?|weeks?|points?|pts|salari[ée]s|etp|fte)))", re.I)


def _blank_ordinals(text: str) -> str:
    return _ORDINAL_LABEL_RE.sub(lambda m: m.group(1) + " " * len(m.group(2)), text)


_TOOL_NOTICE_RE = re.compile(
    r"\b(?:options?|sc[ée]narios?|axes?|phases?|[ée]tapes?|piliers?|leviers?|volets?|jalons?|lots?|vagues?|"
    r"priorit[ée]s?|actions?|risques?|questions?|hypoth[èe]ses?|pillars?|streams?|steps?|items?)\s+\d{1,2}\b"
    r"(?!\s*(?:%|€|k€|M€|jours?|mois|ans?|semaines?|h\b))"   # v62.13.9.4.22 — « Option 3 » est un ordinal
    r"|\b[JD]\s*[+\-]\s*\d{1,3}\b"                        # v62.13.9.4.21 — jalons relatifs « J+30 », « D+90 »
    r"|\b[TQ][1-4]\s+20\d{2}\b|\b[SH][12]\s+20\d{2}\b"    # trimestres, semestres (« S1 2026 »)
    r"|\b\d{1,2}/(?:19|20)\d{2}\b"                       # mois/année « 10/2026 »
    r"|^\s*⚠?\s*\d+\s+claims?\(?s?\)?\b"                # « ⚠ 3 claim(s) … » : compteur de l'outil
    r"|\b\d{1,3}\s*/\s*100\b"                          # v62.13.9.4.19.4 — score sur 100
    r"|\bGrade\s+[A-E]\b"                             # grade de confiance
    r"|(?<=[A-Za-zé])\d{1,3}(?=\s*/\s*100)",             # « Cohérence80/100 » collé
    re.I)


_HEADING_NUMBER_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?\d{1,2}(?:\.\d{1,2}){0,3}(?:[.)](?=\s|$)|(?=\s+[A-ZÀ-Ÿ«\*]))"
    # v62.13.9.4.38 — « §5 — Plan d'actions », « § 2 Décisions proposées » : le numéro de
    # SECTION derrière un paragraphe (§) n'est pas une grandeur. Deux synthèses réelles
    # du 19/09/2026 ont été RETENUES parce que « 5 » et « 2 » étaient par ailleurs des
    # valeurs déclarées par un agent.
    r"|^\s*\u2063?§\s*\d{1,2}(?=\s*[—–\-:.]|\s+[A-ZÀ-Ÿ])")

# v62.13.9.4.38 — repères de phase et d'horizon : « T0 », « T+90 », « J+30 », « M+6 »,
# « S1 », « Q4 » ne sont pas des grandeurs ; « 0 » et « 90 » y sont des étiquettes.
_PHASE_MARK_RE = re.compile(r"(?<![A-Za-z0-9])(?:T|J|M|W|D|H)\s*[+\-]?\s*\d{1,3}(?![A-Za-z0-9%])|(?<![A-Za-z0-9])(?:S|Q|H)[1-4](?![A-Za-z0-9])")


# v62.13.9.4.48 — NON-QUANTITÉS, implémentation PROPRE à ce juge. Doctrine 9.4.9 : aucune table
# partagée avec la production (utils/non_quantity.py n'est pas importé ici) — deux écritures
# indépendantes n'ont pas les mêmes angles morts ; le corpus de frontières vérifie qu'elles
# s'accordent. Corpus du 27/09/2026 : « Scope 3 … roadmap », « Tier 1 pricing », « A-320 fleet
# renewal plan » étaient retenus ici comme projections chiffrées.
_OWN_NON_QUANTITY_RE48 = re.compile(
    r"\b(?:scope|tier|pillar|pilier|level|niveau|ifrs|ias|iso)s?\s?\d{1,5}(?!\s*(?:%|‰|€|\$|£|k€|m€|pts?\b|points?\b))"
    r"(?:\s*(?:,|/|et|and|ou|or|vs\.?|[-–])\s*\d{1,5})*\b"
    r"(?!\s*(?:[-–/]\s*\d|mois|months?|ans?\b|years?|jours?|days?|semaines?|weeks?))"   # une durée n'est pas un numéro
    r"|(?<=[A-Za-z])[-‑–](?!(?:19|20)\d{2}\b)\d{1,6}\b"
    r"|\b[QHST][1-4]\b",
    re.I)

# v62.13.9.4.49 — ÉCRITURE PROPRE DU JUGE (doctrine 9.4.9 : jamais d'import du moteur) pour les IDENTIFIANTS.
# Runs réels du 28/09/2026 : sur des lignes d'identité « libellé : valeur » (« Company profile: LEI: … »,
# « Entity: … — LEI … | CIK … »), ce juge lisait les chiffres de tête d'un identifiant alphanumérique comme une
# grandeur non certifiable. Un identifiant n'est pas une grandeur : jeton mêlant chiffres et lettres d'au moins
# huit signes, ou valeur qui suit un libellé d'identifiant reconnu.
# v62.13.9.4.50 — écriture propre du juge pour les MARQUEURS ORDINAUX d'une rubrique d'agent (« [PARADE 3 — NOUVELLE] »,
# « [5] À VÉRIFIER — … », « RECOMMANDATION 1 ») : un rang, pas une grandeur (échantillon du vrai CR du 30/09).
_OWN_ORDINAL_RE50 = re.compile(r"(?m)^\s*\[\s*\d{1,2}\s*\]|\[\s*[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ’' ]{2,30}\s+\d{1,2}\b(?=[^\]]{0,60}\])"
                               r"|(?i:\b(?:parade|recommandation|recommendation|d[ée]cision|decision|risque|risk|priorit[ée]|priority|"
                               r"challenge|levier|lever|chantier|workstream)\s+(?:n[°º]\s*)?\d{1,2}\b(?!\s*(?:%|€|\$|£|k€|M€|M\$)))")
# v62.13.9.4.49 — écriture propre du juge pour la pagination écrite par le produit (« 14 of 15 entries »)
_OWN_PAGINATION_RE49 = re.compile(r"(?i)(?:\b\d+\s+)?\b(?:of|sur)\s+\d+\s+(?:entries|entrées|items|éléments|lines|lignes)\b")
_OWN_IDENTIFIER_RE49 = re.compile(
    r"(?i)\b(?:LEI|CIK(?:\s+SEC)?|SIREN|SIRET|ISIN|CUSIP|TVA(?:\s+intracom\w*)?|VAT(?:\s+(?:no|number))?|RCS|EIN|DUNS|NAF|APE|IBAN|BIC|"
    r"n°\s*d['’]identification)\s*[:#n°]*\s*[A-Z0-9][A-Z0-9 .\-]{3,34}"
    r"|(?-i:\b(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{8,34}\b)")


# v62.13.9.4.48 — point 4 : CIBLES DU BRIEF, lecture PROPRE à ce juge (données reçues de
# l'appelant, aucune fonction importée de la production). Une cible que le dirigeant a écrite dans
# son brief, citée comme cible, n'est pas une grandeur projetée « non certifiée » du livrable : elle
# est signalée une fois, dans la section du brief et au registre. Présentée comme atteinte (passé
# factuel), elle redevient un chiffre à juger.
_BRIEF_STOP48 = {"de", "des", "du", "la", "le", "les", "and", "the", "of", "en", "et", "au", "aux", "sur", "par"}


def _brief_mask48(text: str, brief) -> str:
    if not brief or _own_factual_past(text):
        return text
    low = text.lower()
    years = set(re.findall(r"(?:19|20)\d{2}", text))
    out = text
    for it in brief:
        if not isinstance(it, dict) or it.get("unit") != "BRIEF_TARGET":
            continue
        words = [w for w in re.split(r"[^a-zà-ÿ0-9]+", str(it.get("metric") or "").lower())
                 if len(w) >= 2 and w not in _BRIEF_STOP48]
        if words and sum(1 for w in words if (w in low if len(w) >= 4 else re.search(rf"(?<![a-zà-ÿ]){re.escape(w)}(?![a-zà-ÿ])", low))) < (2 if len(words) >= 3 else 1):
            # v62.13.9.4.50 — écriture propre du juge : REPRISE ELLIPTIQUE d'une cible du brief (« croissance (objectif
            # de 700 M$ en FY2028) », sans le libellé de la métrique) — langage de cible, exercice de la déclaration
            # présent dans la ligne, même nature d'unité ; sinon la ligne n'est pas une reprise du brief
            _py50 = set(re.findall(r"(?:19|20)\d{2}", str(it.get("period") or "")))
            if not (_py50 and _py50 <= years and re.search(r"(?i)\b(?:objectif|cible|target|atteindre|reach|viser|aim|ambition)", text)):
                continue
            _mine50 = str(it.get("metric") or "").lower()
            if any(w.lower() not in _mine50 for w in re.findall(
                    r"(?i)\b(?:ebitda|ebit|marge|margin|r[ée]sultat|income|profit|tr[ée]sorerie|cash|dette|debt|bfr|capex|"
                    r"effectifs?|headcount|stocks?|cr[ée]ances|part\s+de\s+march[ée]|market\s+share)\b", text)):
                continue                                  # la ligne nomme une AUTRE métrique : pas une reprise
        u = str(it.get("unit_raw") or "")
        if "%" in u and "%" not in text:
            continue
        if re.search(r"[$€£]|usd|eur|gbp", u, re.I) and not re.search(r"[$€£]|usd|eur|gbp|dollar|euro", text, re.I):
            continue
        py = set(re.findall(r"(?:19|20)\d{2}", str(it.get("period") or "")))
        if py and years and not (py & years):
            continue
        val = str(it.get("value") or "")
        if not val:
            continue
        pat = re.escape(val).replace(r"\.", r"[.,]")
        out = re.sub(rf"(?<![\d.,]){pat}(?![\d])", lambda m: " " * len(m.group(0)), out)
    return out


def _own_fr_decimal50(unit: str, claims) -> str:
    """v62.13.9.4.50 — écriture propre du juge : « 79,871 M$ » est ambigu (79 871 M$ en notation anglaise, 79,871 M$
    en notation française). Quand la lecture DÉCIMALE correspond exactement à une valeur certifiée par un claim, le
    nombre est réécrit, pour ce seul jugement, à la française explicite (« 79.871 M$ »). Aucune valeur n'est inventée :
    sans claim correspondant, la lecture d'origine demeure."""
    vals = []
    for c in claims or ():
        get = c.get if isinstance(c, dict) else (lambda k, c=c: getattr(c, k, None))
        for comp in (get("numeric_components") or []):
            if isinstance(comp, dict) and isinstance(comp.get("value"), (int, float)):
                vals.append(float(comp["value"]))
    if not vals:
        return unit

    def _fix(m):
        a, b, scale = m.group(1), m.group(2), m.group(3)
        mult = {"m": 1e6, "md": 1e9, "bn": 1e9, "k": 1e3}.get(scale.lower()[:2] if scale.lower().startswith("md") else scale.lower()[:1], 1e6)
        dec = float(a + "." + b) * mult
        if any(abs(dec - v) <= 0.0005 * v for v in vals if v):
            return f"{a}.{b} {scale}"
        return m.group(0)
    return re.sub(r"(?<![\d.,])(\d{1,3}),(\d{3})\s?(M(?:d)?|m|bn|k)(?=\s?(?:\$|€|£|USD|EUR|GBP))", _fix, str(unit or ""))


def judge_unit(unit: str, claims=None, declared=None, brief=None) -> dict | None:
    """None = rien à redire ; dict = retenue motivée.

    ``declared`` : ensemble de valeurs normalisées déclarées prospectives par
    les agents (chantier A1). Elles sont retenues même quand aucun lexème de
    projection n'apparaît dans la phrase — c'est précisément le cas que le
    texte ne permet pas de trancher.
    """
    unit = _own_fr_decimal50(unit, claims)                              # v62.13.9.4.50 — virgule décimale certifiée
    text = str(unit or "").strip()
    if len(text) < 3 or _NEUTRALIZED_RE.search(text):
        return None
    if "\u2063" in text:
        return None                          # v62.13.9.4.21 — écrit par le produit
    if re.search(r"⟨\s*(?:statut|status)\s*:", text, re.I):
        return None                          # v62.13.9.4.21 — statut en marge
    # v62.13.9.4.19.6 — réserve épistémique : négation explicite du sourçage
    # ET chiffre entre guillemets → le chiffre est récusé, pas affirmé.
    if _EPISTEMIC_CAVEAT_RE.search(text) and _QUOTED_FIGURE_RE.search(text):
        return None
    # v62.13.9.4.19.3 — les masques de l'outil (numérotation, horodatage,
    # avis de l'outil) s'appliquent AUSSI au chemin « grandeur déclarée
    # prospective » : « ⚠ 3 claim(s) écartées » ne porte pas la cible « 3 ».
    # v62.13.9.4.28 — « Option 1 vs 2 vs 3 » : la chaîne est masquée EN PREMIER
    # (l'avis d'outil blanchissait « Option 1 » et laissait « 2 vs 3 » nus).
    _pre = _OPTION_CHAIN_RE.sub(lambda m: " " * len(m.group(0)), text)
    _pre = _brief_mask48(_pre, brief)                                   # v62.13.9.4.48 — cibles du brief
    _pre = _OWN_NON_QUANTITY_RE48.sub(lambda m: " " * len(m.group(0)), _pre)   # v62.13.9.4.48
    _pre = _OWN_IDENTIFIER_RE49.sub(lambda m: " " * len(m.group(0)), _pre)     # v62.13.9.4.49 — identifiants
    _pre = _OWN_PAGINATION_RE49.sub(lambda m: " " * len(m.group(0)), _pre)     # v62.13.9.4.49 — pagination
    _pre = _OWN_ORDINAL_RE50.sub(lambda m: " " * len(m.group(0)), _pre)        # v62.13.9.4.50 — marqueurs ordinaux
    _pre = _HEADING_NUMBER_RE.sub(lambda m: " " * len(m.group(0)), _pre)
    _pre = _PHASE_MARK_RE.sub(lambda m: " " * len(m.group(0)), _pre)         # v62.13.9.4.38
    _pre = _TIMESTAMP_RE.sub(lambda m: " " * len(m.group(0)), _pre)
    # v62.13.9.4.32 (A) — les repères de planification (« options 1/2/3 »,
    # « T1 2027 ») se masquent AVANT l'avis d'outil : celui-ci consommait
    # « options 1 » et laissait « /2/3 » devenir une grandeur.
    _pre = _PLANNING_LOCAL_RE.sub(lambda m: " " * len(m.group(0)), _pre)
    _pre = _blank_ordinals(_pre)
    _pre = _TOOL_NOTICE_RE.sub(lambda m: " " * len(m.group(0)), _pre)
    # v62.13.9.4.22 — PARITÉ avec le typeur : les marqueurs de planification
    # (numéro de rangée, « | 2 » de priorité, plages de dates, index de
    # semaine) que le typeur masque ne sont pas des grandeurs pour ce juge.
    _pre = _PLANNING_LOCAL_RE.sub(lambda m: " " * len(m.group(0)), _pre)   # copie INDÉPENDANTE, jamais un import du moteur
    hit = _declared_prospective_hit(_pre, declared)
    if hit is not None:
        return {"reason": "declared_prospective_magnitude", "quantity": hit}
    # v62.13.9.4.38 — la certification se juge sur le texte MASQUÉ des numéros de
    # section et des repères de phase, pas sur le texte brut : « §5 — Plan d'actions »
    # était retenu comme « claimed_but_not_certifiable » sur le 5 de sa numérotation
    # dès qu'une liste de faits de soutien existait (deux synthèses réelles du
    # 19/09/2026).
    failed = _failed_certification(_pre, claims)
    if failed is not None:
        return {"reason": "claimed_but_not_certifiable", "quantity": failed}
    if not _PROJECTION_RE.search(text):
        return None
    if _ARBITRATION_RE.search(text):
        return None
    if _own_factual_past(text):
        return None
    # PROXIMITÉ : la projection doit GOUVERNER la grandeur. Un lexème en fin
    # de paragraphe ne rend pas prospectif un nombre situé cent caractères
    # plus haut (« … l'option 2 … » suivi, trois phrases après, de
    # « l'objectif de rentabilité »). Fenêtre volontairement large.
    _spans = [m.span() for m in _PROJECTION_RE.finditer(text)]
    # v62.13.9.4.15 — la NUMÉROTATION DE TITRE en tête d'unité (« ## 2.
    # Objectifs… », « 4.1 Axe 1 : … », « 3) … ») n'est pas une grandeur : le
    # rejeu du run réel du 02/09/2026 15:04 retenait « 2 » et « 4 » comme
    # projections. Règle lexicale propre à ce juge, sans import du guard —
    # appliquée AVANT les autres exemptions pour que « Axe 1 » reste lisible
    # par le renvoi ordinal.
    masked = _HEADING_NUMBER_RE.sub(lambda m: " " * len(m.group(0)), text)
    masked = _brief_mask48(masked, brief)                                # v62.13.9.4.48 — cibles du brief
    masked = _OWN_NON_QUANTITY_RE48.sub(lambda m: " " * len(m.group(0)), masked)   # v62.13.9.4.48
    masked = _PHASE_MARK_RE.sub(lambda m: " " * len(m.group(0)), masked)   # v62.13.9.4.38
    # v62.13.9.4.19.1 — horodatage et dates complètes (« Date : 03/09/2026
    # 20:03 » sur la couverture) : « 20 » n'est pas une grandeur déclarée.
    masked = _TIMESTAMP_RE.sub(lambda m: " " * len(m.group(0)), masked)
    masked = _PLANNING_LOCAL_RE.sub(lambda m: " " * len(m.group(0)), masked)   # v62.13.9.4.22 — parité typeur ; v62.13.9.4.32 : AVANT l'avis d'outil
    masked = _blank_ordinals(masked)                                            # v62.13.9.4.32 (A) — numéros d'ordre, nom conservé
    masked = _TOOL_NOTICE_RE.sub(lambda m: " " * len(m.group(0)), masked)   # v62.13.9.4.19.3
    masked = _EXEMPT_RE.sub(lambda m: " " * len(m.group(0)), masked)
    # v62.13.9.4.49 — identifiants masqués AUSSI sur le chemin des projections (« Target entity: … CIK SEC 105132 » :
    # le mot « Target » gouvernait le numéro d'enregistrement ; témoin de la famille F2 de la contre-recette)
    masked = _OWN_IDENTIFIER_RE49.sub(lambda m: " " * len(m.group(0)), masked)
    masked = _OWN_PAGINATION_RE49.sub(lambda m: " " * len(m.group(0)), masked)
    masked = _OWN_ORDINAL_RE50.sub(lambda m: " " * len(m.group(0)), masked)
    # fenêtre de plan : la durée qui cadre un plan est neutralisée
    if _PLAN_WORD_RE.search(text):
        masked = _PLAN_WINDOW_RE.sub(lambda m: " " * len(m.group(0)), masked)
    certified = _certified(text, claims)
    for m in _QTY_RE.finditer(masked):
        if not (m.group("num") or "").strip():
            continue
        around = masked[max(0, m.start("num") - 1):m.end("num") + 1]
        if _CODE_GLUED_RE.search(around):
            continue                      # code alphanumérique, pas une grandeur
        g = _magnitude(m)
        if g is None:
            continue
        if (round(g[0], 6), g[1], g[2]) in certified:
            continue
        if not any(abs(s - m.start("num")) <= _GOVERN_WINDOW
                   or abs(e - m.start("num")) <= _GOVERN_WINDOW
                   or (s <= m.start("num") <= e)
                   for s, e in _spans):
            continue
        return {"reason": "projection_with_uncertified_magnitude",
                "quantity": text[m.start():m.end()].strip()}
    wn = _WORDNUM_RE.search(masked)
    if wn and not _STRUCTURE_NOUN_RE.match(masked[wn.end():]):
        return {"reason": "projection_with_uncertified_wordnumber",
                "quantity": wn.group(0)}
    return None
