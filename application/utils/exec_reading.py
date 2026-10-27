"""exec_reading — règles dures de la lecture exécutive (chantier H2, spec gelée 10/08/2026).

Fonctions PURES : listes/chaînes entrantes → sélections, formats et mesures
sortantes. Aucun accès python-pptx, aucune horloge, aucun état — le câblage
dans les bâtisseurs de slides se fait ailleurs. Chaque règle ici est EN DUR
(arbitrage Robin du 10/08) ; la configurabilité éventuelle est différée à v18.

Règles portées :
- R3 — Top-N sur M, tri métier : ACTIONS par échéance croissante puis
  criticité (décision Robin) ; RISQUES par criticité puis impact € ;
  QUESTIONS dans l'ordre, N = 4. Jamais d'ellipse : la coupe est un choix
  tracé, matérialisé par un renvoi « +k autres — CR §n ».
- R5 — trio de chiffres par défaut CA · marge/EBITDA · cash (surchargeable
  par dossier via kpi_selector).
- R1 — dérivation du message-clé de couverture : première phrase de la
  synthèse, entière (pas de troncature — c'est une zone HCRIT).
- R8 — métriques audit_90s : puces par slide, mots par puce, présence des
  renvois. Les plafonds R4 (≤ 5 puces, ≤ 12 mots) sont MESURÉS ici ; la
  coupe ne s'applique qu'au NOMBRE de puces (Top-N), jamais à l'intérieur
  d'une phrase.

Tolérance de schéma : les items sont des dicts hétérogènes ; les accesseurs
essaient les alias connus et dégradent proprement (une date illisible trie
en dernier, une criticité inconnue vaut M).
"""
from __future__ import annotations
import re as _re

import re
from datetime import date as _date
from typing import Any, Dict, List, Sequence, Tuple, Mapping

# ── accesseurs tolérants ─────────────────────────────────────────────────────

_DATE_KEYS = ("echeance", "échéance", "date", "deadline", "due")
_CRIT_KEYS = ("criticite", "criticité", "critic", "priorite", "priorité",
              "priority", "severity", "prob", "probabilite", "probabilité",
              "probability")
_IMPACT_KEYS = ("impact", "impact_eur", "impact_montant", "montant", "enjeu")

_FAR_FUTURE = (9999, 12, 31)

_CRIT_RANK = {"H": 0, "HAUTE": 0, "HIGH": 0, "CRITIQUE": 0, "3": 0,
              "M": 1, "MOYENNE": 1, "MEDIUM": 1, "2": 1,
              "L": 2, "B": 2, "BASSE": 2, "FAIBLE": 2, "LOW": 2, "1": 2}


def _first(item: Dict[str, Any], keys: Sequence[str]) -> str:
    for k in keys:
        v = item.get(k)
        if v not in (None, ""):
            return str(v)
    return ""


def _validated_key(year: int, month: int, day: int) -> Tuple[int, int, int]:
    try:
        _date(int(year), int(month), int(day))
    except (TypeError, ValueError):
        return _FAR_FUTURE
    return int(year), int(month), int(day)


def parse_date_key(value: str) -> Tuple[int, int, int]:
    """Clé de tri (aaaa, mm, jj), validée calendriquement.

    Les trimestres sont normalisés à leur vraie fin de période. Une chaîne
    illisible ou une date impossible trie en dernier : H2 ne fabrique jamais
    une échéance à partir d'un bruit documentaire.
    """
    s = str(value or "").strip()
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return _validated_key(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return _validated_key(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.search(r"[TtQq]([1-4])\s*(\d{4})", s)
    if m:
        q, y = int(m.group(1)), int(m.group(2))
        ends = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
        mo, day = ends[q]
        return y, mo, day
    m = re.search(r"\b(\d{4})\b", s)
    if m:
        return int(m.group(1)), 12, 31
    return _FAR_FUTURE


def crit_rank(value: str) -> int:
    """0 = le plus critique. Inconnu → M (rang 1)."""
    s = str(value or "").strip().upper()
    if s in _CRIT_RANK:
        return _CRIT_RANK[s]
    return _CRIT_RANK.get(s[:1], 1) if s else 1


def parse_impact_eur(value: str) -> float:
    """« 2,5 M€ » → 2 500 000 ; « 300 k€ » → 300 000 ; illisible → 0."""
    s = str(value or "").replace("\u202f", " ").replace(",", ".")
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*(m|k)?\s*€", s, re.IGNORECASE)
    if not m:
        m = re.search(r"(-?\d+(?:\.\d+)?)\s*(m€|k€|meur|keur|m|k)?\b", s,
                      re.IGNORECASE)
        if not m:
            return 0.0
    mult = {"m": 1e6, "k": 1e3}.get((m.group(2) or "").lower()[:1], 1.0)
    try:
        return float(m.group(1)) * mult
    except Exception:
        return 0.0


# ── R3 : tris durs et Top-N ──────────────────────────────────────────────────

def is_semantic_action(text: str) -> bool:
    """Gate partagé du registre et des surfaces exécutives.

    La source de vérité vit dans :mod:`patches.agenda_register`. Ce relais évite
    qu'un renderer réimplémente une règle divergente et ne masque qu'un symptôme.
    Le repli est volontairement fail-closed.
    """
    try:
        from patches.agenda_register import is_semantic_action as _shared_gate
        return bool(_shared_gate(text))
    except Exception:
        s = str(text or "").strip()
        if not s or s.endswith("?"):
            return False
        # Repli minimal : une action doit commencer par une forme pilotable.
        return bool(_re.search(
            r"^\s*(?:mettre|lancer|déployer|deployer|formaliser|structurer|"
            r"créer|creer|création|creation|mise\s+en\s+place|suivre|"
            r"valider|négocier|negocier|préparer|preparer|contacter|"
            r"implement|launch|deploy|formalize|structure|create|set\s+up|"
            r"review|validate|contact)\b", s, _re.IGNORECASE))


def filter_semantic_action_rows(rows):
    """Retourne ``(lignes recevables, nombre rejeté)``.

    API historique conservée pour les renderers H2 ; la classification est
    déléguée au gate commun et ne décide plus localement.
    """
    try:
        from patches.agenda_register import filter_semantic_action_rows as _shared_filter
        kept, quarantined = _shared_filter(rows, preserve_separators=False)
        return kept, len(quarantined)
    except Exception:
        kept = []
        dropped = 0
        for row in rows or []:
            if isinstance(row, Mapping) and is_semantic_action(row.get("action", "")):
                kept.append(row)
            else:
                dropped += 1
        return kept, dropped


def sort_actions(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Échéance croissante puis criticité (décision Robin, 10/08/2026)."""
    return sorted(items, key=lambda it: (parse_date_key(_first(it, _DATE_KEYS)),
                                         crit_rank(_first(it, _CRIT_KEYS))))


def sort_risques(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Criticité puis impact € décroissant (défaut délégué, spec gelée)."""
    return sorted(items, key=lambda it: (crit_rank(_first(it, _CRIT_KEYS)),
                                         -parse_impact_eur(_first(it, _IMPACT_KEYS))))


TOP_N = {"actions_par_horizon": 3, "risques": 3, "questions": 4}





_CLOSED_ACTION_TOKENS = (
    "fait", "faite", "done", "closed", "completed", "complete",
    "terminé", "terminee", "terminée", "clôturé", "cloture", "clôturée",
    "annulé", "annule", "cancelled", "canceled", "abandonné", "abandonne",
    "rejeté", "rejete", "supprimé", "supprime",
)

def is_open_action(item: Mapping[str, Any]) -> bool:
    """True si l'action peut encore être une prochaine étape H2.

    Les actions closes/annulées restent dans le CR et l'historique, mais ne
    peuvent ni devenir « prochaine action » ni porter la prochaine échéance.
    """
    if not isinstance(item, Mapping):
        return False
    raw = _first(dict(item), ("status", "statut", "state", "etat", "état"))
    if not raw:
        return True
    norm = re.sub(r"[^a-zà-ÿ]+", " ", raw.lower()).strip()
    return not any(tok in norm for tok in _CLOSED_ACTION_TOKENS)

def select_deadline(items: List[Dict[str, Any]], reference_date: str) -> Dict[str, Any]:
    """Sélectionne la prochaine échéance relative à l'autorité du run.

    Une date passée n'est jamais présentée comme « prochaine ». S'il n'existe
    aucune date future, la plus récente date passée est renvoyée avec le statut
    ``overdue``. Les dates impossibles ou illisibles sont ignorées.
    """
    ref = parse_date_key(reference_date)
    if ref == _FAR_FUTURE:
        return {}
    dated = []
    for idx, item in enumerate(items or []):
        if not isinstance(item, dict) or not is_open_action(item):
            continue
        raw = _first(item, _DATE_KEYS)
        key = parse_date_key(raw)
        if key == _FAR_FUTURE:
            continue
        dated.append((key, idx, item, raw))
    if not dated:
        return {}
    future = [x for x in dated if x[0] >= ref]
    if future:
        key, _idx, item, raw = min(future, key=lambda x: (x[0], x[1]))
        status = "upcoming"
    else:
        key, _idx, item, raw = max(dated, key=lambda x: (x[0], -x[1]))
        status = "overdue"
    return {"date_key": key, "raw_date": raw, "status": status, "item": item}


def _risk_label(item: Any) -> str:
    if isinstance(item, dict):
        return _first(item, ("label", "risque", "risk", "titre", "title", "text"))
    return str(item or "").strip()


def select_top_risk(structured: List[Any], fallback: List[Any]) -> str:
    """Choisit le risque n°1 sur la source structurée, sinon l'ordre SWOT.

    C'est le câblage réel de la règle de criticité/impact : ``sort_risques``
    n'est plus une pièce testée mais inutilisée.
    """
    typed = [x for x in (structured or []) if isinstance(x, dict) and _risk_label(x)]
    if typed:
        ranked = sort_risques(typed)
        return _risk_label(ranked[0]) if ranked else ""
    for item in fallback or []:
        label = _risk_label(item)
        if label:
            return label
    return ""


def top_n_split(items: List[Any], n: int) -> Tuple[List[Any], int]:
    """(retenus, écartés) — k écartés alimente le renvoi, jamais une ellipse."""
    n = max(0, int(n))
    return list(items[:n]), max(0, len(items) - n)


def renvoi_label(k: int, section: str, lang: str = "fr") -> str:
    """« +k autres — CR §n ». Vide si k = 0 (pas de renvoi décoratif)."""
    if k <= 0:
        return ""
    if lang == "en":
        return f"+{k} more — see report §{section}"
    return f"+{k} autres — CR §{section}"


# ── R5 : le trio de chiffres ─────────────────────────────────────────────────

_TRIO_PATTERNS = (
    ("ca", re.compile(r"\bca\b|chiffre\s*d'affaires|revenue|sales", re.I)),
    ("marge", re.compile(r"marge|ebitda|r[ée]sultat|margin|ebit\b", re.I)),
    ("cash", re.compile(r"cash|tr[ée]so|liquidit|bfr", re.I)),
)


# v62.6 — un KPI exécutif est un FAIT court, pas un scénario de travail.
# Les chaînes ci-dessous ont toutes été observées sur les reruns dossier de conseil :
# elles sont utiles dans le CR, mais trompeuses lorsqu'elles deviennent le
# premier « chiffre clé » d'une slide de décision.
_NON_FACTUAL_KPI_RX = re.compile(
    r"\b(?:sc[ée]nario|illustrati(?:f|ve)|non\s+personnalis[ée]|hypoth[èe]se|"
    r"estimate,?\s+to\s+verify|estim\.\s*[àa]\s+v[ée]rifier|[àa]\s+v[ée]rifier|"
    r"indicati(?:f|ve)|projection|pr[ée]vision)\b|\[(?:ESTIM|HYPOTH)",
    re.IGNORECASE,
)
_MISSING_KPI_TOKENS = {
    "", "—", "-", "n/a", "na", "none", "null", "non communiqué",
    "non communique", "non disponible", "not available", "not disclosed",
    "à collecter", "a collecter", "to collect",
}


def is_executive_kpi_value(value: Any) -> bool:
    """True seulement pour une valeur suffisamment factuelle pour une carte H2.

    La prudence est volontaire : un scénario chiffré peut rester dans le Word,
    mais ne devient jamais un KPI principal ni une pastille de synthèse.  Le
    filtre ne juge pas la *justesse* du chiffre ; il empêche seulement qu'une
    hypothèse explicitement qualifiée soit re-promue comme fait par le deck.
    """
    raw = re.sub(r"\s+", " ", str(value or "")).strip()
    if raw.lower() in _MISSING_KPI_TOKENS:
        return False
    if _NON_FACTUAL_KPI_RX.search(raw):
        return False
    return True


def safe_executive_kpi_value(value: Any, fallback: str = "") -> str:
    """Valeur courte utilisable en surface exécutive, sinon ``fallback``."""
    raw = re.sub(r"\s+", " ", str(value or "")).strip()
    return raw if is_executive_kpi_value(raw) else str(fallback or "")


def kpi_selector(kpis: List[Dict[str, Any]],
                 max_n: int = 3) -> List[Dict[str, Any]]:
    """Trio CA · marge/EBITDA · cash d'abord (1 par famille), complété dans
    l'ordre du dossier, plafonné à max_n. Jamais de doublon."""
    chosen: List[Dict[str, Any]] = []
    for _fam, pat in _TRIO_PATTERNS:
        for k in kpis:
            name = str(k.get("nom") or k.get("name") or k.get("label") or "")
            if pat.search(name) and k not in chosen:
                chosen.append(k)
                break
    for k in kpis:
        if len(chosen) >= max_n:
            break
        if k not in chosen:
            chosen.append(k)
    return chosen[:max_n]


# ── R1 : message-clé de couverture ───────────────────────────────────────────

def derive_key_message(synthese: str) -> str:
    """Première phrase entière de la synthèse (zone HCRIT : pas de coupe).
    Vide si rien d'exploitable — la couverture omet alors la ligne."""
    s = re.sub(r"\s+", " ", str(synthese or "")).strip()
    if not s:
        return ""
    # v62.13.9.4.33 (lot 1) — un « ! » ou un « ? » suivi d'un mot en capitales
    # est intérieur à un nom (« dossier de conseil », « ACME! INDUSTRIES »), pas une
    # fin de phrase (contre-audit du 12/09/2026).
    m = re.search(r"^(.+?(?:[.]|[!?](?!\s+[A-ZÀ-Ÿ]{2,})))(\s|$)", s)
    return (m.group(1) if m else s).strip()



# ── R2/R4/R5 : textes exécutifs et candidats KPI ─────────────────────────────

def content_words(text: str) -> int:
    """Compte les MOTS DE CONTENU d'une ligne exécutive (hotfix terrain 11/08).

    Le tailleur R3 coupe à N mots puis AJOUTE le signal de coupe (« — CR »,
    « — report », variante interrogative) ; les bâtisseurs préfixent
    numérotation et glyphes (« 1. », « ✓ », « • »). Mesurer ces artefacts
    comme des mots faisait échouer le gate R4 sur des textes que R3 venait
    de tailler : l'exécuteur et le mesureur doivent partager UNE tokenisation.
    """
    words = str(text or "").split()
    while words and (words[0] in {"✓", "•", "-", "–", "▸"} or
                     (words[0].rstrip(".)").isdigit() and len(words[0]) <= 4)):
        words = words[1:]
    while words and words[-1] in {"?", "!"}:
        words = words[:-1]
    for k in (3, 2):
        if len(words) >= k and words[-k] in {"—", "-"} and                 words[-k + 1].rstrip(" ?!").lower() in {"cr", "report"}:
            words = words[:-k]
            break
    # Un jeton sans aucun caractère alphanumérique (« : », « — », « · ») n'est
    # pas un mot ; ce filtre ne peut que SOUS-compter vs le tailleur — jamais
    # de faux positif possible au gate.
    return sum(1 for w in words if any(ch.isalnum() for ch in w))


_TRAILING_DEADLINE_RX = re.compile(
    r"\s+(?:avant|d['’]ici|au\s+plus\s+tard(?:\s+le)?|pour|before|by)\s+"
    r"(?:le\s+)?(?:20\d{2}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/20\d{2})\s*$|"
    r"\s+(?:T[1-4]|Q[1-4])\s+20\d{2}\s*$",
    re.IGNORECASE,
)


def _cleanup_compacted_exec(text: str) -> str:
    """Nettoyage final commun aux surfaces exécutives compactées.

    La coupe ne doit jamais laisser un fragment syntaxique du type ``(ex.``,
    une virgule juste avant ``— CR`` ou une parenthèse ouverte.  Le détail
    complet reste dans le CR ; la surface courte doit, elle, rester lisible.
    """
    out = re.sub(r"\s+", " ", str(text or "")).strip()
    out = re.sub(r"[,;:]\s+(?=[—–-]\s+(?:CR|report)\b)", " ", out,
                 flags=re.IGNORECASE)
    out = re.sub(r"\(\s*(?:ex\.|e\.g\.|i\.e\.|cf\.)?\s*$", "", out,
                 flags=re.IGNORECASE).rstrip(" ,;:")
    if out.count("(") > out.count(")"):
        # Une parenthèse incomplète en fin de ligne est moins informative que
        # le renvoi explicite au CR : on retire seulement le fragment terminal.
        out = re.sub(r"\s*\([^()]*$", "", out).rstrip(" ,;:")
    return out


_UNIT_GLUE51 = re.compile(r"(\d)\s+(%|pb|pts?|bps?|M\s?\$|M\s?€|k\s?€|Md\s?€|MUSD|kUSD|MEUR|kEUR|M|k|x)(?![\w])")
_WJ51 = "\u2060"   # gluon invisible (n'est pas un blanc pour str.split)


def compact_exec_text(text: str, max_words: int = 12, lang: str = "fr",
                      max_chars: int | None = None,
                      drop_trailing_deadline: bool = False) -> Tuple[str, bool]:
    """9.4.51 — un nombre n'est JAMAIS séparé de son unité par la coupe (recette du 02/10/2026 : « La marge brute
    FY2025 est de 55,1 » — le « % » était tombé, compté comme un mot à part). Le nombre et son unité sont soudés le
    temps de la compaction, puis rendus tels qu'écrits."""
    # 9.4.53 — contre-recette ChatGPT du 06/10 (R01) : « Action déjà décidée — Reconstituer la passerelle… » ou « À
    # ARBITRER : lancer l'instruction… » devenaient, raccourcis, « Action déjà décidée » et « À ARBITRER » — l'action
    # réduite à son étiquette et à sa date. Une étiquette de tête suivie d'un engagement est retirée avant la coupe
    # (même règle que le contrat 9.4.41 : un marqueur ne remplace jamais l'engagement).
    _txt53 = str(text or "")
    _hm53 = re.match(r"(?i)^\s*(?:[ÀA]\s+(?:ARBITRER|V[ÉE]RIFIER|D[ÉE]CIDER|INVESTIGUER|SOUMETTRE(?:\s+AU\s+\w+)?)|"
                     r"ACTIONS?\s+D[ÉE]J[ÀA]\s+D[ÉE]CID[ÉE]ES?(?:\s+PAR\s+LA\s+DIRECTION)?|ORIENTATION\s+RECOMMAND[ÉE]E|"
                     r"TO\s+(?:ARBITRATE|VERIFY|DECIDE)|ALREADY\s+DECIDED)\s*(?:\([^)]{0,40}\))?\s*[:—–-]\s*", _txt53)
    if _hm53 and len(_txt53[_hm53.end():].split()) >= 3:
        _txt53 = _txt53[_hm53.end():]
        _txt53 = _txt53[:1].upper() + _txt53[1:]
    # 9.4.55 — contre-recette du 07/10 (D01) : « 14/10/2026 — Cadrage des marchés pilotes… » devenait, raccourci,
    # « 14/10/2026 » : la carte n'affichait que sa date (déjà montrée à côté). Une date de tête suivie d'un engagement est
    # retirée avant la coupe ; elle reste dans la colonne date de la carte.
    _dm55 = re.match(r"^\s*\**\s*(?:\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})\s*\**\s*[:—–-]\s*", _txt53)
    if _dm55 and len(_txt53[_dm55.end():].split()) >= 3:
        _txt53 = _txt53[_dm55.end():]
        _txt53 = _txt53[:1].upper() + _txt53[1:]
    # 9.4.57 — contre-recette ChatGPT du 10/10 (§7) : « 2026-10-15 : DAF — présenter le plafond OPEX consolidé… » donnait,
    # une fois la date retirée (9.4.55), la carte « DAF » : le PORTEUR de tête remplaçait l'action. Un porteur en tête,
    # suivi d'un engagement, est retiré avant la coupe (la carte affiche son porteur ailleurs).
    _own57 = (r"(?:DAF|DG|CFO|CEO|COO|DRH|DSI|CTO|PDG|Président(?:e)?|CoDIR|Comité\s+\w+|"
              r"Direct(?:eur|rice|ion)\s+[A-Za-zÀ-ÿ'’]+(?:\s+(?:groupe|générale?|financi[eè]re?|commercial(?:e)?|RSE|supply\s+chain|"
              r"marketing|des\s+\w+))?|Responsable\s+[A-Za-zÀ-ÿ'’]+(?:\s+[A-Za-zÀ-ÿ'’]+)?)")
    _om57 = re.match(r"^\s*\**\s*" + _own57 + r"(?:\s*[,/+&]\s*" + _own57 + r")*\s*\**\s*[:—–-]\s*", _txt53)
    if _om57 and len(_txt53[_om57.end():].split()) >= 3:
        _txt53 = _txt53[_om57.end():]
        _txt53 = _txt53[:1].upper() + _txt53[1:]
    text = _txt53
    glued = _UNIT_GLUE51.sub(lambda m: m.group(1) + _WJ51 + m.group(2), str(text or ""))
    out, cut = _compact_exec_text_impl51(glued, max_words=max_words, lang=lang, max_chars=max_chars,
                                         drop_trailing_deadline=drop_trailing_deadline)
    out = str(out or "").replace(_WJ51, " ")
    # 9.4.52 — contre-recette ChatGPT du 05/10 : « Rétablir et réaliser le stress-test … (action abandonnée … : À ARBITRER sa
    # réouverture) » devenait, raccourci, « Rétablir et réaliser le stress-test » — une proposition présentée comme une
    # exécution. Si le texte complet est une proposition à arbitrer et que la coupe a perdu cette qualification, elle revient.
    # Bornée aux PROPOSITIONS DE RÉOUVERTURE OU DE RÉTABLISSEMENT (une action close ou abandonnée que l'agent voudrait
    # reprendre) : un simple marqueur de tête (« À SOUMETTRE AU DG — Sécuriser la dette… ») reste retiré, comme le veut le
    # contrat 9.4.41 « un marqueur de tête ne remplace jamais l'engagement ».
    _pend = r"(?i)\b(?:[àa]\s+arbitrer|[àa]\s+d[ée]cider|proposition|to\s+(?:arbitrate|decide)|proposal)\b"
    _reopen = r"(?i)\b(?:r[ée]ouverture|r[ée]ouvrir|rouvrir|r[ée]tablir|r[ée]activer|reopen(?:ing)?|reinstat\w*)\b"
    if out and re.search(_reopen, str(text or "")) and not re.search(_pend, out):
        out = ("To decide: " if str(lang).lower().startswith("en") else "À arbitrer : ") + out
    return out, cut


def _compact_exec_text_impl51(text: str, max_words: int = 12, lang: str = "fr",
                              max_chars: int | None = None,
                              drop_trailing_deadline: bool = False) -> Tuple[str, bool]:
    """Retourne une formulation exécutable courte, sans ellipse silencieuse.

    La première proposition est privilégiée. Si elle dépasse le budget R4,
    la coupe est explicitement signalée par ``— CR`` / ``— report`` : le
    contenu complet reste dans le compte-rendu, conformément au partage
    surface/profondeur de la spec H2.
    """
    # v62.13.9.4.41 — UN MARQUEUR NE REMPLACE PAS L'ACTION. Mesure du 23/09/2026 :
    # « À SOUMETTRE AU DG — Sécuriser la dette bancaire… » ressortait du compactage réduit
    # à « À SOUMETTRE AU DG ». Le préfixe était gardé, l'engagement perdu. Le marqueur est
    # retiré avant compactage ; s'il ne reste rien après lui, la ligne ne vaut pas d'être
    # écrite et la fonction rend une chaîne vide, que l'appelant saura ne pas afficher.
    # v62.13.9.4.41b — UNE COUPE NE PASSE PAS AVANT LE VERBE. Mesuré le 24/09/2026 :
    # « The VP Global Brand & Innovation should publish metrics… » ressortait « The VP
    # Global Brand & Innovation and — report ». La coupe était signalée, mais le lecteur
    # ne voyait plus qu'un nom : un engagement réduit à sa personne n'est pas un
    # engagement. Le budget de mots est étendu jusqu'au verbe et à son objet immédiat ;
    # au-delà d'une marge raisonnable, l'appelant préférera ne pas rendre l'objet là.
    try:
        from patches.agenda_register import _ACTION_VERB_ANY41 as _AV41
        _src41 = str(text or "")
        _mv41 = _AV41.search(_src41.lower())
        if _mv41:
            _words41 = _src41.split()
            _upto41 = len(_src41[:_mv41.end()].split()) + 2
            if _upto41 > int(max_words) and _upto41 <= int(max_words) + 8:
                max_words = _upto41
    except Exception:
        pass
    try:
        _raw41 = str(text or "")
        _m41 = _re.match(
            r"^\s*(?:\[\d+\]\s*)?(?:[àa]\s+soumettre(?:\s+au\s+dg)?|to\s+be\s+submitted|"
            r"bloquante?|blocking|recommand[ée]e?|recommended|[àa]\s+investiguer|to\s+investigate|"
            r"[àa]\s+arbitrer|to\s+arbitrate|priorit[ée]\s*\d*)\s*[–—\-:]\s*(?P<rest>.+)$",
            _raw41, _re.IGNORECASE | _re.DOTALL)
        if _m41 and _m41.group("rest").strip():
            text = _m41.group("rest").strip()
    except Exception:
        pass
    raw = re.sub(r"\s+", " ", str(text or "")).strip(" \t\r\n•-–—")
    if not raw:
        return "", False

    # Les suffixes épistémiques font partie de la vérité du message. Ils ne
    # doivent jamais être confondus avec une seconde proposition et supprimés
    # par la compaction H2 (régression détectée sur « GBP 100m — estimate »).
    epi = re.search(
        r"(?P<suffix>\s+[—–]\s+(?:estim\.\s+à\s+vérifier|estimate,?\s+to\s+verify))$",
        raw, re.IGNORECASE,
    )
    epistemic_suffix = epi.group("suffix").strip() if epi else ""
    semantic = raw[:epi.start()].rstrip() if epi else raw
    if drop_trailing_deadline:
        semantic = _TRAILING_DEADLINE_RX.sub("", semantic).rstrip(" ,;:–—-")

    # v62 terrain — les abréviations « ex. », « e.g. », « i.e. », « cf. »
    # ne terminent pas une proposition. La v61 coupait ainsi
    # « Choisir 2 verticales métier (ex. finance …) » en
    # « Choisir 2 verticales métier (ex. », visible sur la slide Priorités.
    protected = semantic
    placeholders = {
        "ex.": "ex\u2024", "e.g.": "e\u2024g\u2024",
        "i.e.": "i\u2024e\u2024", "cf.": "cf\u2024",
    }
    for token, repl in placeholders.items():
        protected = re.sub(re.escape(token), repl, protected, flags=re.IGNORECASE)
    first = re.split(r"(?<=[.;])\s+|(?<=[!?])\s+(?![A-ZÀ-Ÿ]{2,})|\s+[—–]\s+", protected, maxsplit=1)[0].strip()   # v62.13.9.4.33 — « ACME! INDUSTRIES » n'est pas coupé
    first = first.replace("\u2024", ".")
    rendered = f"{first} {epistemic_suffix}".strip() if epistemic_suffix else first
    rendered = _cleanup_compacted_exec(rendered)
    words = [w for w in rendered.split() if w]
    if len(words) <= max_words and (max_chars is None or len(rendered) <= max_chars):
        return rendered, False

    if epistemic_suffix:
        suffix_words = epistemic_suffix.split()
        core_words = first.split()
        keep = max(1, max_words - len(suffix_words))
        while keep > 1:
            candidate = _cleanup_compacted_exec(
                " ".join(core_words[:keep] + suffix_words))
            if max_chars is None or len(candidate) <= max_chars:
                return candidate, True
            keep -= 1
        return _cleanup_compacted_exec(
            " ".join(core_words[:1] + suffix_words)), True

    suffix = ["—", "report"] if (lang or "fr").lower() == "en" else ["—", "CR"]
    keep = max(1, max_words - len(suffix))
    while keep > 1:
        candidate = _cleanup_compacted_exec(" ".join(words[:keep] + suffix))
        if max_chars is None or len(candidate) <= max_chars:
            return candidate, True
        keep -= 1
    return _cleanup_compacted_exec(" ".join(words[:1] + suffix)), True


def is_valid_headcount_candidate(value: Any) -> bool:
    """Return False when a retail-unit count is masquerading as headcount."""
    text = str(value or "").strip()
    if not text:
        return False
    retail_units = re.search(
        r"\b(?:stores?|shops?|boutiques?|magasins?|points?\s+of\s+sale|doors?)\b",
        text, re.I)
    people_units = re.search(
        r"\b(?:employees?|headcount|workforce|people|staff|salari[ée]s?|"
        r"collaborateurs?|effectif|FTEs?|ETP)\b", text, re.I)
    return not bool(retail_units and not people_units)


def build_kpi_candidates(context: Mapping[str, Any], lang: str = "fr") -> List[Dict[str, Any]]:
    """Construit les KPI H2 avec priorité financière CA / marge-EBITDA / cash.

    Les schémas terrain ne sont pas uniformes ; les alias restent bornés et
    explicitement documentés. L'effectif n'intervient qu'en complément si le
    trio financier n'est pas disponible.
    """
    cc = dict(context or {})
    en = (lang or "fr").lower() == "en"
    out: List[Dict[str, Any]] = []

    def add(label: str, value: Any, sub: Any = "") -> None:
        val = str(value or "").strip()
        if not is_executive_kpi_value(val):
            return
        if any(str(x.get("nom")) == label for x in out):
            return
        sub_txt = str(sub or "").strip()
        # Un sous-titre narratif ne doit jamais transformer un fait d'entreprise
        # en véhicule d'une tendance marché. Les sous-titres sont réservés aux
        # unités/sources courtes explicitement fournies dans ``kpis``.
        if _NON_FACTUAL_KPI_RX.search(sub_txt) or len(sub_txt) > 38:
            sub_txt = ""
        out.append({"nom": label, "val": val, "sub": sub_txt})

    # v62.13.3 — value, semantic label and proof status are one canonical
    # object. A page-confirmed adjusted operating margin must never be labelled
    # "EBITDA / margin", and a confirmed revenue fact is never "indicative".
    meta = cc.get("financial_kpi_metadata") or {}
    def meta_label(key: str, fallback: str) -> str:
        item = meta.get(key) if isinstance(meta, Mapping) else None
        return str((item or {}).get("label") or fallback)

    def meta_sub(key: str) -> str:
        # v62.13.9.4.50 — règle du dernier réalisé daté : l'exercice du fait confirmé s'affiche sous la valeur
        item = meta.get(key) if isinstance(meta, Mapping) else None
        return str((item or {}).get("sub") or "")
    add(meta_label("ca", "Revenue" if en else "Chiffre d'affaires"),
        cc.get("ca") or cc.get("revenue") or cc.get("sales"), meta_sub("ca"))
    margin_key = "marge" if cc.get("marge") else "resultat_operationnel"
    add(meta_label(margin_key, "EBITDA / margin" if en else "Marge / EBITDA"),
        cc.get("ebitda") or cc.get("marge") or cc.get("margin") or cc.get("resultat_operationnel") or cc.get("operating_result"),
        meta_sub(margin_key))
    add(meta_label("cash", "Cash" if en else "Trésorerie"),
        cc.get("cash") or cc.get("tresorerie") or cc.get("trésorerie") or cc.get("liquidite") or cc.get("liquidité") or cc.get("net_cash"),
        meta_sub("cash"))
    _headcount_candidate = cc.get("effectif") or cc.get("headcount")
    # v62.10 — semantic KPI contract: stores / shops / points of sale are not
    # employees. If invalid, headcount remains unavailable rather than guessed.
    if is_valid_headcount_candidate(_headcount_candidate):
        add("Headcount" if en else "Effectif", _headcount_candidate)
    # Candidats additionnels explicitement fournis par le dossier.
    for item in cc.get("kpis") or []:
        if isinstance(item, Mapping):
            add(str(item.get("nom") or item.get("name") or item.get("label") or "KPI"),
                item.get("val") or item.get("value"), item.get("sub") or item.get("source"))
    return out


_TITLE_MARKED50 = re.compile(r"\[(?:ESTIM|HYPOTH|CALCUL|PROJECTION|CIBLE|TARGET|ASSUMPTION)[^\]]*\]|⟨statu[ts]|⚠|"
                             r"non\s+[ée]tay|unsourced", re.I)
_TITLE_QTY50 = re.compile(r"\d+(?:[.,]\d+)?\s?(?:%|x\b|×|[£$€]|k€|M€|M\$|Md|bn|m\b|k\b|pb\b|bps?\b|points?\b)|[£$€]\s?\d", re.I)
_TITLE_DATED_FACT50 = re.compile(r"\[(?:FAIT|FAITS|FACT|FACTS)\]|\((?:FY|EX)\s?(?:19|20)\d{2}\)", re.I)


def _title_unsafe50(message: str) -> bool:
    """Passage marqué (estimation, hypothèse, cible, statut), ou grandeur qui n'est pas un fait daté du produit."""
    s = str(message or "")
    return bool(_TITLE_MARKED50.search(s) or (_TITLE_QTY50.search(s) and not _TITLE_DATED_FACT50.search(s)))


def assertion_title(prefix: str, message: str, lang: str = "fr", max_words: int = 12) -> str:
    """Titre-assertion R2 : préfixe court + message exécutable, sans rubrique.

    v62.13.9.4.50 — un titre est une composition du PRODUIT : il ne reprend jamais une grandeur ni un passage marqué
    (estimation, hypothèse, cible, statut). Le passage reste dans le corps de la diapositive, signalé en place ; le
    titre retombe sur sa forme générique (contrat d'un dossier coté britannique : une cible chiffrée d'agent
    sortait en titre, sans signalement)."""
    if _title_unsafe50(message):
        return ""
    msg, _ = compact_exec_text(message, max_words=max(4, max_words - 1), lang=lang)
    pref = str(prefix or "").strip()
    return f"{pref} : {msg}" if pref and msg else (msg or pref)

# ── R8 : métriques audit_90s ─────────────────────────────────────────────────

def word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", str(text or "").strip()) if w])


def bullets_metrics(bullets: List[str],
                    max_bullets: int = 5,
                    max_words: int = 12) -> Dict[str, Any]:
    """Mesure R4 : nombre de puces, mots par puce, dépassements. La règle du
    NOMBRE se corrige par Top-N ; les mots sont MESURÉS, jamais tronqués."""
    counts = [word_count(b) for b in bullets]
    return {
        "bullets": len(bullets),
        "bullets_over_cap": max(0, len(bullets) - max_bullets),
        "words_max": max(counts) if counts else 0,
        "bullets_over_words": sum(1 for c in counts if c > max_words),
    }
