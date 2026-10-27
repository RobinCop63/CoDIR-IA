"""v17.1.0-B2.3-F.2 — Registre d'actions d'agenda CoDIR (minimal).

Cœur du socle « assistant d'agenda de CoDIR » : normaliser, pour un point
d'agenda, le tuple

    sujet · décision attendue · décision prise · action · porteur · échéance
    · statut · prochaine revue

Périmètre B2.3-F.2 = MINIMAL et déterministe : structure + extraction
pragmatique depuis le CR + rendu tableau. Le cycle de vie MULTI-SÉANCES
(persistance d'un CoDIR à l'autre, relances, historique de statut) est le
chantier adjoint suivant — ce module en est la fondation, pas la version finale.

Fail-open : aucune exception ne remonte ; si rien n'est exploitable, registre
vide. Aucun fait/valeur n'est inventé — on STRUCTURE ce que le CR contient.
"""
from __future__ import annotations
import re

import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional
import unicodedata


def _strip_accents(txt: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", txt or "")
                   if unicodedata.category(c) != "Mn")


# ── M.5.9 (FIX E, retex run dossier de conseil M.5.8) ───────────────────────────────
# Le séparateur « Axes conditionnels — hors plan principal » est un EN-TÊTE de
# section, pas une action : il ne doit ni être ingéré dans l'historique du
# dossier, ni s'afficher dans le suivi multi-séances. Helper de détection commun.
_SEP_PREFIXES = ("axes conditionnels — hors plan principal",
                 "conditional axes — out of the main plan")


def is_separator_row(row: dict) -> bool:
    """True si la ligne est un séparateur/section_header (pas une action)."""
    if not isinstance(row, dict):
        return False
    if row.get("_separator") or row.get("_row_type") == "section_header":
        return True
    act = (row.get("action", "") or "").strip().lower()
    return any(act.startswith(p) for p in _SEP_PREFIXES)


def _dedup_action_rows(rows: List[dict]) -> List[dict]:
    """Dédup SÛR (exact, après normalisation) — retire les doublons verbatim
    d'actions. La fusion sémantique des quasi-doublons (« suivi simple » vs
    « suivi pipeline simple ») reste un ticket M.6 (risque de fusion abusive)."""
    seen: set = set()
    out: List[dict] = []
    for r in rows:
        act = re.sub(r"\s+", " ", (r.get("action", "") or "").lower()).strip()
        act = re.sub(r"\[non sourc[ée]\]", "", act).strip()
        if not act:
            out.append(r)
            continue
        if act in seen:
            continue
        seen.add(act)
        out.append(r)
    return out


# Statuts normalisés (pas de jugement : valeur par défaut = « À lancer »).
STATUT_A_LANCER = "À lancer"
STATUT_EN_COURS = "En cours"
STATUT_FAIT = "Fait"
STATUT_BLOQUE = "Bloqué"
STATUT_A_ARBITRER = "À arbitrer"

# P0-5 temps 2 (M.5.4) — statuts EN pour le rendu du registre.
_STATUT_EN = {
    "À lancer": "To start", "En cours": "In progress", "Fait": "Done",
    "Bloqué": "Blocked", "À arbitrer": "To arbitrate",
}


@dataclass
class AgendaAction:
    action: str
    sujet: str = ""
    decision_attendue: str = ""
    decision_prise: str = ""
    porteur: str = ""
    echeance: str = ""
    statut: str = STATUT_A_LANCER
    prochaine_revue: str = ""
    source_textuelle: str = ""   # ligne d'origine (traçabilité Cycle C)
    # Champs optionnels de confirmation : l'extracteur agent ne les renseigne
    # jamais ; ils ne peuvent venir que d'une interaction/connexion fiable.
    statut_confirme: bool = False
    status_origin: str = ""
    status_evidence_ref: str = ""
    status_confirmed_by: str = ""
    status_confirmed_at: str = ""
    completed_at: str = ""
    incompatible_with_decision: bool = False   # P0-3 (M.5.6) — reclassé hors plan principal

    def as_row(self) -> dict:
        return asdict(self)


@dataclass
class AgendaRegister:
    items: List[AgendaAction] = field(default_factory=list)
    genre: str = ""
    decision_final: str = ""

    def __len__(self) -> int:
        return len(self.items)

    def to_rows(self, lang: str = "fr") -> List[dict]:
        # P0-3 (M.5.8, FIX2) — le registre rendu (CR Word + slide deck) honore
        # désormais incompatible_with_decision : les actions reclassées passent sous
        # un séparateur « Axes conditionnels — hors plan principal ». La M.5.6 ne le
        # faisait que dans to_markdown() (non utilisé par ces livrables).
        main = [a for a in self.items if not getattr(a, "incompatible_with_decision", False)]
        cond = [a for a in self.items if getattr(a, "incompatible_with_decision", False)]
        rows = _dedup_action_rows([a.as_row() for a in main])   # M.5.9 FIX E2
        if cond:
            template = (main[0] if main else cond[0]).as_row()
            sep = {k: "" for k in template}
            sep["sujet"] = "⚠️"
            sep["action"] = ("Axes conditionnels — hors plan principal (à arbitrer ; "
                             "à mener seulement si la décision de retrait n'est pas confirmée)"
                             if lang != "en" else
                             "Conditional axes — out of the main plan (to arbitrate; pursue "
                             "only if the wind-down decision is not confirmed)")
            sep["_separator"] = True
            sep["_row_type"] = "section_header"   # M.5.9 FIX E1 — type explicite : ce
            #   n'est PAS une action ; l'historique multi-séances et l'ingestion doivent
            #   l'ignorer (il fuyait comme action en M.5.8).
            rows.append(sep)
            rows += _dedup_action_rows([a.as_row() for a in cond])   # M.5.9 FIX E2
        # B.1.3.47 — garde PARTAGÉE des statuts appliquée à LA VUE (le PPT et
        # le CR consomment to_rows) : la 3.46 gouvernait l'historique, la vue
        # affichait toujours « Fait » (repro ChatGPT [1]). Skip séparateurs.
        try:
            from patches.codir_register_history import (
                govern_action_status_row, canonicalize_action_status,
            )
            for r in rows:
                govern_action_status_row(r, lang=lang)
                if not (r.get("_separator") or r.get("_row_type") == "section_header"):
                    r["_statut_canonical"] = canonicalize_action_status(
                        r.get("_statut_canonical") or r.get("statut"))
        except Exception:
            # Chemin critique : en cas de panne du garde, on ne laisse jamais
            # passer une complétion générée. Repli local fail-closed.
            _done = {"fait", "done", "closed", "completed", "terminé", "termine"}
            for r in rows:
                if str(r.get("statut", "") or "").strip().lower() in _done:
                    r["statut"] = STATUT_A_LANCER
                    r["statut_conflict"] = "ACTION_STATUS_GUARD_FAILURE"
        # M.5.10.6 — le PPT et le CR consomment to_rows(), pas to_markdown() : le
        # statut brut (« À lancer »…) fuyait dans le deck en run EN. On localise ici
        # statut + prochaine_revue sur chaque ligne d'action (jamais les séparateurs).
        if lang == "en":
            for r in rows:
                if r.get("_separator") or r.get("_row_type") == "section_header":
                    continue
                _st = r.get("statut")
                if _st:
                    r["statut"] = _STATUT_EN.get(_st, _st)
                if r.get("prochaine_revue") == "Prochain CoDIR":
                    r["prochaine_revue"] = "Next CoDIR"
        # S.2.4.1 — jamais de Sujet/Porteur vide dans le livrable : fallback localisé,
        # au lieu de laisser « — » ou la scorie « A designer ». Rien d'inventé : on
        # signale explicitement qu'il reste à qualifier/désigner.
        _sub_fb = "Topic to qualify" if lang == "en" else "Sujet à qualifier"
        _own_fb = "Owner to assign" if lang == "en" else "Porteur à désigner"
        # v62.13.9.4.22 — contre-audit v21 (§6.2) : sept lignes « Porteur à
        # désigner » alors que le texte de l'action nommait la personne
        # (« … (Robin SAUZET) »). Le porteur est extrait du texte de l'action —
        # parenthèse ou mention « porteur/responsable : X » — avant tout repli.
        _own_re = re.compile(
            r"\(\s*([A-ZÀ-Ÿ][A-Za-zÀ-ÿ'’\-]+(?:\s+[A-ZÀ-Ÿ][A-Za-zÀ-ÿ'’\-]+){1,3})\s*\)"
            r"|(?:porteur|responsable|owner|pilote|lead)\s*:\s*([A-ZÀ-Ÿ][A-Za-zÀ-ÿ'’\-]+(?:\s+[A-ZÀ-Ÿ][A-Za-zÀ-ÿ'’\-]+){0,3})", re.U)
        _not_names = {"CA", "TJM", "KPI", "CRM", "SEO", "ETI", "PME", "DAF", "DG", "RH", "GO", "NO", "NO-GO", "HT", "TTC"}
        for r in rows:
            if r.get("_separator") or r.get("_row_type") == "section_header":
                continue
            if not (r.get("sujet") or "").strip():
                r["sujet"] = _sub_fb
            if not (r.get("porteur") or "").strip():
                _txt = " ".join(str(r.get(k) or "") for k in ("action", "sujet", "livrable", "commentaire"))
                _found = ""
                for _m in _own_re.finditer(_txt):
                    _cand = (_m.group(1) or _m.group(2) or "").strip()
                    _words = _cand.split()
                    if (_cand and _cand.upper() not in _not_names and len(_words) >= 2
                            and not any(w.upper() in _not_names for w in _words) and not re.search(r"\d", _cand)):
                        _found = _cand
                        break
                r["porteur"] = _found or _own_fb
        # B.1.3.61 — dernière défense avant toute surface/persistance.
        rows, _quarantined = filter_semantic_action_rows(rows, preserve_separators=True)
        return rows

    def to_markdown(self, lang: str = "fr") -> str:
        """Markdown dérivé des MÊMES rows gouvernées que le CR et le PPT."""
        return rows_to_markdown(self.to_rows(lang), lang)


def rows_to_markdown(rows: List[dict], lang: str = "fr") -> str:
    """Rend des rows déjà gouvernées, sans relire les ``AgendaAction``.

    Utilisé après la réconciliation historique : une action clôturée qui
    réapparaît reste « À arbitrer » dans le markdown comme dans le CR/PPT.
    """
    rows = list(rows or [])
    rows, _quarantined = filter_semantic_action_rows(rows, preserve_separators=True)
    if not rows:
        return ""
    if lang == "en":
        head = ("| Topic | Action | Owner | Deadline | Status | Next review |\n"
                "|---|---|---|---|---|---|")
        sep_label = ("\n> ⚠️ **Conditional axes — out of the main plan** "
                     "(to arbitrate; pursue only if the wind-down decision is not confirmed):")
    else:
        head = ("| Sujet | Action | Porteur | Échéance | Statut | Prochaine revue |\n"
                "|---|---|---|---|---|---|")
        sep_label = ("\n> ⚠️ **Axes conditionnels — hors plan principal** "
                     "(à arbitrer ; à mener seulement si la décision de retrait n'est pas confirmée) :")
    try:
        from patches.codir_register_history import action_status_display
    except Exception:
        action_status_display = lambda r, _lang: str(r.get("statut", "") or "—")
    out = [head]
    for r in rows:
        if r.get("_separator") or r.get("_row_type") == "section_header":
            out.extend([sep_label, head])
            continue
        cells = [r.get("sujet") or "—", r.get("action") or "—",
                 r.get("porteur") or "—", r.get("echeance") or "—",
                 action_status_display(r, lang),
                 r.get("prochaine_revue") or "—"]
        out.append("| " + " | ".join(str(c).replace("|", "/") for c in cells) + " |")
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────────────
# Extraction pragmatique depuis le CR
# ─────────────────────────────────────────────────────────────────────────────
# En-têtes de sections porteuses d'actions.
_ACTION_HEADERS = re.compile(
    r"(plan d'action|plan d’action|prochaines? étapes?|next steps?|actions?\b|"
    r"feuille de route|roadmap|décisions?\b|to[\s\-]?do)",
    re.IGNORECASE,
)
# Une puce d'action : « - … », « * … », « • … », « 1. … ».
_BULLET = re.compile(r"^\s*(?:[-*•·]|\d+[.)])\s+(.*\S)\s*$")

# Porteur : « — Nom », « (Nom) », « porteur : Nom », « responsable : Nom », « owner: Nom ».
_OWNER = re.compile(
    r"(?:porteur|responsable|owner|resp\.?|pilote)\s*[:\-–]\s*([A-ZÉÈÀ][\w''.\- ]{1,40})",
    re.IGNORECASE,
)
_OWNER_PAREN = re.compile(r"[—–-]\s*([A-ZÉÈÀ][\wÀ-ÿ''.\- ]{2,40})\s*$")
# Échéance — v17.1.0-B2.3-F.4.2 : on hiérarchise par SPÉCIFICITÉ pour ne plus
# attraper une année nue qui traîne dans un constat (« comptes 2024-2025 » → 2024,
# « depuis 2021 » → 2021). Une année NUE n'est une échéance que si elle suit un
# repère temporel (avant, d'ici, fin, au plus tard, pour, à partir de, en, échéance).
_MOIS = (r"(?:janv|févr|fevr|mars|avr|mai|juin|juil|août|aout|sept|oct|nov|déc|dec"
         r"|jan|feb|mar|apr|may|jun|jul|aug|sep)\w*\.?")
_DL_DATE_ISO = re.compile(r"\b(20\d{2}[-/]\d{1,2}[-/]\d{1,2})\b")
_DL_DATE_FR = re.compile(r"\b(\d{1,2}[/.\-]\d{1,2}[/.\-]20\d{2})\b")
_DL_QUARTER = re.compile(r"\b(T[1-4]\s*20\d{2}|S[12]\s*20\d{2}|Q[1-4]\s*20\d{2})\b", re.IGNORECASE)
_DL_MONTH = re.compile(r"\b(" + _MOIS + r"\s*20\d{2})\b", re.IGNORECASE)
_DL_CUED_YEAR = re.compile(
    r"\b(?:avant|d['’]ici|d['’]ici à|fin|au plus tard|pour|à partir d[eu]|en|"
    r"échéance|deadline|d['’]ici fin|courant|"
    r"by|before|no later than|as of|from|in|due|end of|by end of|by the end of)"
    r"\s+(?:fin\s+|end\s+of\s+|the\s+end\s+of\s+)?(20\d{2})\b",
    re.IGNORECASE,
)
# Détecteur générique (pour savoir si une puce HORS section porte une échéance).
_DEADLINE = re.compile(
    r"\b(T[1-4]\s*20\d{2}|S[12]\s*20\d{2}|Q[1-4]\s*20\d{2}|" + _MOIS + r"\s*20\d{2}|"
    r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[/.\-]\d{1,2}[/.\-]20\d{2})\b",
    re.IGNORECASE,
)

# Marqueurs de statut explicites éventuels.
_STATUT_MARKERS = (
    (re.compile(r"\b(fait|réalisé(?:e|s|es)?|done|clos|terminé(?:e|s|es)?|clôturé(?:e|s|es)?)\b", re.I), STATUT_FAIT),
    (re.compile(r"\b(en cours|in progress|wip|engagé)\b", re.I), STATUT_EN_COURS),
    (re.compile(r"\b(bloqué|blocked|en attente|on hold)\b", re.I), STATUT_BLOQUE),
    (re.compile(r"\b(à arbitrer|arbitrage|to decide|à trancher)\b", re.I), STATUT_A_ARBITRER),
)

# v17.1.0-B2.3-F.4.2 — Filtre métier du registre.
# Un point d'agenda peut produire des CONSTATS, des SIGNAUX de vigilance, des
# IMPACTS, des QUESTIONS et des ACTIONS. Le registre ne doit contenir QUE des
# actions. On EXCLUT explicitement les non-actions, puis on n'INCLUT que ce qui
# porte un verbe d'action, un marqueur d'action, ou un statut explicite.
_NON_ACTION = re.compile(
    r"^\s*(?:impact|risque|enjeu|constat|cible\s+20\d{2}|"
    r"signal|signaux|note narrative|zone\s+\d)\b"
    r"|^\s*[A-Za-zÀ-ÿ][\w’'/ ]{1,28}\s+vs\s+[A-Za-zÀ-ÿ][\w’'/ ]{1,28}\s*:"   # « X vs Y : … » (vigilance)
    r"|\?\s*$"                                                                # question
    r"|^\s*(?:quel|quelle|quels|quelles|faut[- ]il|doit[- ]on|comment|pourquoi|combien)\b",
    re.IGNORECASE,
)
_ACTION_VERB = re.compile(
    r"^\s*(?:mettre|met\b|choisir|structur|initi|lanc|relanc|livr|sign|boucl|envoy|ouvr|ferm|clôtur|clotur|suivr|contact|publi|migr|renouvel|modifi|obten|cibl|réévalu|reevalu|"
    # 9.4.52 — recette du 05/10 : « Rétablir et réaliser le stress-test… » (proposition de réouverture d'une action abandonnée)
    # était mis en quarantaine « non actionnable » : la proposition disparaissait au lieu de coexister avec l'abandon
    r"rétabl|retabl|réouvr|reouvr|rouvr|réactiv|reactiv|restaur|réalis(?:er|ons)|realis(?:er|ons)|reinstat|reopen|"
    # 9.4.53 — « Fixer un plafond SG&A/CA par région » (parade d'agent nettoyée de son étiquette) partait en quarantaine
    r"fix(?:er|ons|ez)\b|plafonn|chiffr(?:er|ons)\b|quantifi|aligner|alignons|clarifi|"
    r"produ|fourni|document|transmet|"
    r"communiqu|propos|défin|defin|sécuris|securis|refond|engag(?!ement)|démarr|demarr|"
    r"finalis|recrut|contractualis|négoci|negoci|établ|etabl|constru|déploi|deploi|deploy|"
    r"men(?:er|ons)|conduir|organis|planifi|valid|arbitr|collect|récupér|recuper|"
    r"cadr|provisionn|confirm|qualifi|vérifi|verifi|action\s+(?:a|à)\s+faire\s+confirm|"
    r"fiabilis|suivr|cadenc|adhér|adher|cré(?:er|ons)|prépar|prepar|réalis|realis|"
    r"align|sélectionn|selectionn|prospect|développ|developp|rédig|redig|auditer|"
    r"implement|launch|set up|build|define|secure|review|prepare|establish|"
    r"confirm|qualify|verify|recognise|recognize|"
    # v62.13.9.4.41 — formes rencontrées sur des dossiers réels, FR et EN. La liste de
    # verbes sera toujours en retard sur les formulations des modèles : elle reste
    # fail-closed, on l'étend sur constat, jamais par anticipation.
    r"approve|approuv|close|clos(?:er|ons)|reduce|réduir|reduir|arbitrate|disclose|"
    r"present|présent|present(?:er|ons)|rebuild|restore|reconstitu|clarify|clarifi|"
    r"assess|allocate|allou|divest|c[ée]d(?:er|ons)|expand|accelerate|acc[ée]l[ée]r|"
    r"negotiate|consolidate|consolid|appoint|d[ée]sign|escalate|reconcile|rapproch|"
    r"arr[êe]t(?:er|ons)|ramen|ren[ée]goci|soumett|obtenir|obten|"
    # v62.13.9.4.41b — verbes de communication rencontrés sur dossiers réels : un
    # engagement « publier les indicateurs » est un engagement. La liste reste
    # fail-closed et s'étend sur constat, jamais par anticipation.
    r"publish|publi|report\s|rapporter|disclose|communicat|communiqu|share|partag|"
    r"provide|fournir|deliver|livrer|ensure|veiller|monitor|suivre|track|mesurer|"
    r"document|documenter|establish|[ée]tablir)",
    re.IGNORECASE,
)
# v62.13.9.4.41b — le vocabulaire d'actions est ancré en tête de phrase, ce qui convient
# pour QUALIFIER une ligne. Pour LOCALISER le verbe d'un engagement — « Action: The VP …
# should publish les indicateurs » — il faut le chercher où qu'il soit : c'est cette
# variante, non ancrée, qu'utilisent le compactage et le contrôle de livraison.
_ACTION_VERB_ANY41 = re.compile(r"\b(?:" + _ACTION_VERB.pattern.split("(?:", 1)[1],
                                re.IGNORECASE)

_ACTION_MARKER = re.compile(
    r"(recommandé|à investiguer|a investiguer|à soumettre|a soumettre|bloquant|"
    r"^\s*20\d{2}[-/]\d{1,2}[-/]\d{1,2}\s*:)",   # action datée « 2026-06-30 : … »
    re.IGNORECASE,
)
# Préfixes de marqueurs à retirer en tête d'action pour la lisibilité.
_MARKER_STRIP = re.compile(
    r"^\s*(?:\[\d+\]\s*)?(?:à soumettre au dg|a soumettre au dg|bloquante|recommandé|"
    r"recommande|à investiguer|a investiguer)\s*[–\-:]\s*",
    re.IGNORECASE,
)


_ROLE50 = re.compile(r"(?i)\b(?:direct(?:eur|rice|ion)|DG|DGA|DAF|CFO|CEO|COO|CTO|CIO|CHRO|DRH|DSI|RSE|CSR|"
                     r"responsable|head\s+of|manager|pr[ée]sident|supply\s+chain|achats|conseil|board|comit[ée]|DPO|"
                     r"secr[ée]taire\s+g[ée]n[ée]ral|contr[ôo]leur|tr[ée]sorier|juriste|legal|"
                     # v62.13.9.4.50 — fonctions et directions citées comme porteurs (recette du 01/10)
                     r"communication|finances?|marketing|commercial[e]?|ventes|sales|juridique|RH|ressources\s+humaines|"
                     r"op[ée]rations|production|qualit[ée]|IT|informatique|strat[ée]gie|logistique|CEO|COO|CMO|CSO)\b")


_OWNER_LABEL50 = re.compile(r"(?i)^\s*(?:porteurs?|qui|who|owner|responsables?|resp\.?|pilote)\s*[:：]\s*")


def _extract_owner(line: str) -> str:
    """Porteur sans l'étiquette de l'agent (« porteur : DAF » → « DAF », « QUI : CEO » → « CEO »)."""
    return _OWNER_LABEL50.sub("", _extract_owner_raw50(line)).strip(" .;,")


def _extract_owner_raw50(line: str) -> str:
    # v62.13.9.4.50 — contre-recette du 30/09 (C03) : « Présenter l'avancement ESG 2030 au comité d'audit (Directeur
    # RSE, 2026-12-15) » était attribuée à la Direction générale ; « Asie-Pacifique » devenait un porteur. Le porteur
    # donné dans la parenthèse « (Porteur, échéance) » est pris en premier, et un porteur est une FONCTION.
    mp = re.search(r"\(([^()]{2,60}?)\s*[,;·]\s*(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|[TQS][1-4]\s*\d{4})\s*\)", line)
    if mp and _ROLE50.search(_OWNER_LABEL50.sub("", mp.group(1))):
        return mp.group(1).strip(" .")
    m = _OWNER.search(line)
    if m and _ROLE50.search(m.group(1)):
        return m.group(1).strip(" .")
    m = _OWNER_PAREN.search(line)
    if m:
        cand = m.group(1).strip(" .")
        if len(cand.split()) <= 4 and not _DEADLINE.search(cand) and _ROLE50.search(cand):
            return cand
    return ""


_MEASURE_DATE50 = re.compile(r"(?i)\b(?:au|à\s+fin|fin|as\s+of|at|clos(?:e|ed)?\s+(?:le|on)|arr[êe]t[ée]s?\s+au)\s*$")
_MEASURE_NOUN50 = re.compile(r"(?i)\b(?:stocks?|inventor|tr[ée]sorerie|cash|dette|debt|cr[ée]ances|receivables|capitaux|"
                             r"effectifs?|headcount|bilan|balance\s+sheet|M\$|M€|k\$|k€|%)\b[^.;]{0,40}$")


def _extract_deadline(line: str) -> str:
    """Renvoie l'échéance la plus SPÉCIFIQue : date > mois-année > trimestre >
    année précédée d'un repère. Une année nue sans repère n'est PAS une échéance.

    v62.13.9.4.50 — contre-recette du 30/09 (C04) : « réduire les stocks (79,9 M$ au 31/08/2025, source…) » avait pour
    échéance la DATE DE MESURE des stocks, et l'action passait « En retard ». Une date introduite par « au », « à fin »,
    « arrêté au » après une grandeur mesurée n'est pas une échéance."""
    for rx in (_DL_DATE_ISO, _DL_DATE_FR, _DL_MONTH, _DL_QUARTER, _DL_CUED_YEAR):
        for m in rx.finditer(line):
            before = line[:m.start(1)]
            if _MEASURE_DATE50.search(before) and _MEASURE_NOUN50.search(before):
                continue
            return m.group(1).strip()
    return ""


# F.6.8 (audit dossier réseau de soins) — tags ÉPISTÉMIQUES (provenance/fiabilité d'un chiffre) à
# retirer AVANT la détection de statut : « [FAIT] », « – FAIT », « [ESTIM-…] »,
# « [NON SOURCÉ] » qualifient une donnée, PAS l'avancement d'une action. Sans ce
# strip, « (créance 67,1 M€ – FAIT) » fait passer l'action en statut « Fait ».
_EPISTEMIC_TAG = re.compile(
    r"\[\s*(?:FAIT|ESTIM[\w\-–]*|NON\s*SOURC\w*|REF[\s.\w]*|HYPOTH\w*|"
    r"VÉRIFIER|VERIFIER|À\s*VÉRIFIER)\s*\]|[–\-]\s*FAIT\b",
    re.IGNORECASE,
)
_EPISTEMIC_BARE = re.compile(r"\bFAIT\b")   # FAIT en MAJUSCULES = tag, pas statut


def _extract_statut(line: str) -> str:
    clean = _EPISTEMIC_BARE.sub(" ", _EPISTEMIC_TAG.sub(" ", line))
    for rx, st in _STATUT_MARKERS:
        if rx.search(clean):
            return st
    return STATUT_A_LANCER


# S.2.4.2 — préfixes d'OBJECTIF / CIBLE / KPI / IMPACT : ce sont des cibles ou des
# résultats attendus, PAS des tâches à exécuter. On ne les extrait pas comme action,
# SAUF si un vrai verbe d'action suit le préfixe (« Objectif : lancer 3 task-forces »).
# v62.13.9.4.41 — « By 2027-01-31: », « D'ici le 31/12/2026 — », « Q3 2027 : », « 2026-10-31 : »
_DATE_PREFIX41 = re.compile(
    r"^\s*(?:by|before|avant|d['’]ici(?:\s+le)?|au\s+plus\s+tard(?:\s+le)?|from|d[èe]s|"
    r"(?:[àa]\s+)?(?:horizon|[ée]ch[ée]ance)|target(?:\s+date)?)?\s*"
    r"(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/.]\d{1,2}[/.]\d{2,4}|"
    r"(?:q[1-4]|s[12]|t[1-4])\s*\d{4}|fy\s?\d{2,4}|"
    r"(?:\d{1,2}\s+)?(?:january|february|march|april|may|june|july|august|september|october|"
    r"november|december|janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|"
    r"octobre|novembre|d[ée]cembre)\.?\s*\d{0,4}|fin\s+\d{4})\s*[:：\-–—,]\s*(?P<rest>.+)$",
    re.IGNORECASE)
_TARGET_PREFIX = re.compile(
    r"^\s*(?:cible|objectif|kpi|résultat\s+attendu|resultat\s+attendu|"
    r"effet\s+attendu|horizon|impact|indicateur|target|goal|expected\s+outcome)"
    r"(?:\s+(?:recommand\w+|prioritaire|cl\w|principal\w*|majeur\w*|cible))?"
    r"\s*:\s*(.*)$",
    re.IGNORECASE)


# B.1.3.61 — gate sémantique partagé, en amont du registre ET de l'historique.
# Les formes nominales sont admises ("Création d'un CRM", "Négociation fournisseur")
# mais un constat historique chiffré ne devient jamais une action.
_ACTION_NOUN = re.compile(
    r"^\s*(?:(?:(?:en\s+retard|future|open|pending)\s+)?action\b|bilan\b|mise\s+(?:à|a)\s+jour|cl[oô]ture|d[ée]p[oô]t|mise\s+en\s+place|création|creation|lancement|launch|déploiement|deployment|"
    r"formalisation|formalization|structuration|structuring|développement|development|"
    r"optimisation|optimization|refonte|redesign|plan|audit|analyse|analysis|évaluation|evaluation|"
    r"assessment|revue|review|suivi|monitoring|pilotage|projet|project|modification|change|provision|négociation|negotiation|validation|"
    r"arbitrage|sécurisation|securing|recrutement|recruitment|préparation|preparation|"
    r"organisation|organization|planification|planning|publication|activation|définition|"
    r"definition|établissement|establishment|cartographie|mapping|réduction|reduction|"
    r"augmentation|increase|constitution|participation|inscription|registration|"
    r"sollicitation|contact|prospection|outreach|proposition|proposal|transfert|transfer|"
    r"migration|consolidation|montée\s+en\s+gamme|upgrade|update)\b",
    re.IGNORECASE,
)
_HISTORICAL_FACT = re.compile(
    r"\b(?:réalis[ée]s?|realis[ée]s?|atteints?|enregistr[ée]s?|constat[ée]s?|"
    r"observ[ée]s?|publi[ée]s?|achieved|recorded|reported|observed|published)\b",
    re.IGNORECASE,
)
_PERIOD_OR_DATE = re.compile(
    r"\b(?:S[12]|T[1-4]|Q[1-4]|FY|H[12])?\s*20\d{2}\b|"
    r"\b20\d{2}[-/]\d{1,2}(?:[-/]\d{1,2})?\b|\bexercice\b|\bN-1\b",
    re.IGNORECASE,
)
_METRIC_FACT = re.compile(
    r"^\s*[≈~]?\s*[+-]?\d[\d\s.,]*\s*(?:M€|k€|€|M\$|Md€|%|jours?|days?)\b|"
    r"\b(?:TJM|CA|chiffre\s+d['’]affaires|revenue|turnover|EBITDA|résultat\s+net|"
    r"net\s+income|effectif|headcount|top\s+\d+)\b.{0,80}(?:=|:)?\s*[+-]?\d",
    re.IGNORECASE,
)
_DECISION_INTENT = re.compile(r"\b(?:à\s+arbitrer|a\s+arbitrer|to\s+arbitrate|à\s+valider|to\s+validate)\b",
                              re.IGNORECASE)
_COMPARATOR_TARGET = re.compile(
    r"(?:<|>|≤|≥|au\s+moins|au\s+plus|minimum|maximum|objectif|cible)\s*"
    r"[+-]?\d[\d\s.,]*\s*(?:%|€|k€|M€|jours?|mois|days?|months?)", re.IGNORECASE)
_VAGUE_NOMINAL = re.compile(
    r"^\s*(?:sécurisation|optimisation|amélioration|réduction|augmentation|pilotage|suivi)"
    r"\s+(?:de\s+|du\s+|des\s+|la\s+|le\s+)?"
    r"(?:trésorerie|rentabilité|marge|pipeline|activité|performance|durée\s+moyenne)"
    r"(?:\s*\([^)]*\))?\s*$", re.IGNORECASE)
_HISTORICAL_BALANCE_FACT = re.compile(
    r"\b(?:engagements?\s+retraite|provision(?:s)?|effectif|chiffre\s+d['’]affaires|"
    r"r[ée]sultat\s+net|tr[ée]sorerie|dette|capitaux\s+propres)\b"
    r".{0,140}\b(?:au\s+)?(?:\d{2}/\d{2}/20\d{2}|20\d{2})\b"
    r".{0,100}\b\d[\d\s.,]*\s*(?:€|k€|M€|salari[ée]s?|ETP|%)\b",
    re.IGNORECASE,
)
_TRUE_ACTION_ON_FACT = re.compile(
    r"^\s*(?:faire\s+)?(?:confirmer|vérifier|verifier|évaluer|evaluer|comptabiliser|"
    r"provisionner|documenter|collecter|mettre\s+[àa]\s+jour|analyser|auditer)\b",
    re.IGNORECASE,
)


def _semantic_normalize(body: str) -> str:
    s = str(body or "").strip()
    s = re.sub(r"^\s*(?:[-*•·✓]|\d+[.)])\s+", "", s)
    s = s.replace("**", "").replace("__", "")
    s = re.sub(r"^\s*20\d{2}-\d{2}-\d{2}\s*[:\-–—]\s*", "", s)
    s = _MARKER_STRIP.sub("", s)
    return s.strip()


def is_semantic_action(text: str) -> bool:
    """True uniquement pour une action/decision pilotable.

    Gate fail-closed : verbes d'action, formes nominales d'action ou intention
    explicite d'arbitrage. Les métriques, constats historiques, objectifs/KPI et
    questions sont rejetés, même s'ils contiennent le mot « réalisé ».
    """
    # v62.5 — réserve P1 du mandat : un THÈME nominal marqué « priorité »
    # (« Sécurisation trésorerie — priorité absolue ») n'est pas une action.
    if re.search(r"priorit[ée]s?\s+absolue|—\s*priorit[ée]", str(text or ""), re.IGNORECASE):
        return False
    raw = str(text or "").strip()
    if not raw:
        return False
    # Labels symboliques structurés utilisés par certaines intégrations/tests
    # (A-RETRO, ACTION-01) : ils représentent déjà un objet d'action, pas un fait.
    if (re.fullmatch(r"[A-Z]", raw) or
            re.fullmatch(r"[A-Z][A-Z0-9 _-]{2,}", raw)) and not re.search(r"[%€$]", raw):
        return True
    if any(raw.lower().startswith(p) for p in _SEP_PREFIXES):
        return False
    # 9.4.57 — contre-recette du 10/10 (§4.5) : « À PROPOSER au dirigeant : réouverture de… » est une PROPOSITION à arbitrer ;
    # elle doit rester visible au registre (statut « À arbitrer »), pas partir en quarantaine
    if re.match(r"(?i)^\W*(?:À|A)\s+PROPOSER\b\s*(?:au\s+dirigeant|au\s+DG|au\s+CoDIR)?\s*[:—–-]?\s*\S", raw) and len(raw.split()) >= 4:
        return True
    if _NON_ACTION.search(raw) or raw.rstrip().endswith("?"):
        return False
    # 9.4.51 — contre-recette du 03/10/2026 : un FAIT DE VEILLE (« Lancement européen annoncé d'un lubrifiant… (veille…) »)
    # entrait au registre avec une échéance passée, donc « En retard ». Un fait annoncé par un tiers n'est pas une action,
    # sauf si la ligne commence par ce qu'il faut en faire (suivre, analyser, répondre…).
    if re.search(r"(?i)\(\s*veille\b|\bveille\s+(?:concurrentielle|march[ée])\b|\bannonc[ée]e?s?\b|\ba\s+annonc[ée]\b", raw) and \
            not re.match(r"(?i)^\s*(?:[àa]\s+)?(?:suivre|surveiller|analyser|[ée]valuer|[ée]tudier|r[ée]pondre|anticiper|pr[ée]parer|"
                         r"qualifier|mesurer|comparer|monitor|track|assess|respond|analy[sz]e)\b", raw):
        return False
    if re.search(r"\[\s*(?:fait|done|réalis|realis|ok)\b", raw, re.IGNORECASE):
        return False
    # v62.13.9.4.41 — PRÉFIXE DE DATE OU D'HORIZON. Un engagement daté à l'anglaise met
    # la date devant — « By 2027-01-31: Approve… » — et le gate, ancré en début de phrase,
    # le rejetait alors que le verbe est là. Mesure du 23/09/2026 : cinq engagements sur
    # sept écartés sur un dossier anglais. Le préfixe est retiré avant examen, comme le
    # sont déjà « cible : » et « objectif : » ; le reste de la règle ne bouge pas.
    _mp41 = _DATE_PREFIX41.match(raw)
    if _mp41 and _mp41.group("rest").strip():
        raw = _mp41.group("rest").strip()
    # un modal ne masque pas le verbe : « should publish » reste « publish ».
    raw = re.sub(r"^\s*(?:should|must|shall|will|needs?\s+to|has\s+to|doit|devra|devrait)\s+",
                 "", raw, flags=re.IGNORECASE)
    mt = _TARGET_PREFIX.match(raw)
    if mt:
        inner = _semantic_normalize(mt.group(1))
        return bool(_ACTION_VERB.search(inner) or _ACTION_NOUN.search(inner))
    s = _semantic_normalize(raw)
    if _TRUE_ACTION_ON_FACT.search(s):
        return True
    has_verb = bool(_ACTION_VERB.search(s))
    has_action_form = bool(has_verb or _ACTION_NOUN.search(s))
    # v62.8 — un poste historique de bilan/annexe n'est pas une action.
    # Exemple terrain : « Engagement retraite ... au 31/12/N : 123 456 € ».
    # Il devient action seulement si une instruction observable le précède
    # (« Faire confirmer... », « Comptabiliser... »).
    if _HISTORICAL_BALANCE_FACT.search(s) and not _TRUE_ACTION_ON_FACT.search(s):
        return False
    # v62.4 — un seuil/KPI formulé comme nom (« Réduction de la durée < 5
    # mois ») n'est pas une action. Il faut un verbe d'exécution explicite.
    if _COMPARATOR_TARGET.search(s) and not has_verb:
        return False
    # Les thèmes vagues (« Sécurisation trésorerie — priorité absolue ») restent
    # des enjeux tant qu'une action observable n'est pas formulée.
    if _VAGUE_NOMINAL.match(s):
        return False
    # Reproduction dossier de conseil : « 168,8 M€ réalisés au S1 2025 ».
    if _HISTORICAL_FACT.search(s) and (_PERIOD_OR_DATE.search(s) or _METRIC_FACT.search(s)):
        return False
    # Une ligne métrique/équation sans forme d'action est un fait, pas une tâche.
    if _METRIC_FACT.search(s) and not has_action_form:
        return False
    if re.search(r"=\s*[+-]?\d|\d\s*%", s) and not has_action_form:
        return False
    if has_action_form:
        return True
    # Une enveloppe/option explicitement « à arbitrer » reste un objet CoDIR.
    if _DECISION_INTENT.search(s):
        return True
    return False


def filter_semantic_action_rows(rows, preserve_separators: bool = True):
    """Retourne ``(kept, quarantined)`` sans modifier les lignes d'origine."""
    kept, quarantined = [], []
    for row in rows or []:
        if not isinstance(row, dict):
            quarantined.append(row)
            continue
        if is_separator_row(row):
            if preserve_separators:
                kept.append(row)
            continue
        if is_semantic_action(row.get("action", "")):
            kept.append(row)
        else:
            q = dict(row)
            q["semantic_quarantine_reason"] = "NOT_ACTIONABLE"
            quarantined.append(q)
    return kept, quarantined


_NOMINAL_TITLE50 = re.compile(
    r"(?i)^\s*(?:analyse|construction|d[ée]finition|d[ée]ploiement|recrutement|communication|arbitrage|mise\s+en\s+place|"
    r"validation|finalisation|optimisation|pr[ée]paration|suivi|pilotage|revue|[ée]tude|lancement|plan|feuille\s+de\s+route|"
    r"analysis|construction|definition|deployment|recruitment|communication|arbitration|review|study|launch|roadmap)\b")


def _is_real_action(body: str) -> bool:
    """Compatibilité extracteur : délègue au gate sémantique partagé.

    v62.13.9.4.50 — un TITRE NOMINAL court sans échéance (« Analyse de portefeuille produit », « Arbitrage CoDIR »,
    « Communication stakeholders ») est une rubrique de plan de travail, pas une action (contre-recette du 30/09, M01 :
    14 fragments et titres sur 66)."""
    b = re.sub(r"\*\*|__", "", str(body or "")).strip()
    if _NOMINAL_TITLE50.match(b) and len(b.split()) <= 7 and not _DEADLINE.search(b) and ":" not in b:
        return False
    return is_semantic_action(body)


def _clean_action(line: str) -> str:
    out = _MARKER_STRIP.sub("", line)
    out = out.replace("**", "").replace("__", "")            # S.2.4.3 — gras markdown brut
    out = re.sub(r"^\s*\d{4}-\d{2}-\d{2}\s*[:\-–—]\s*", "", out)  # S.2.4.3 — préfixe date -> échéance
    out = _TARGET_PREFIX.sub(r"\1", out)   # S.2.4.2 — drop préfixe « Objectif : »/« Cible : »
    out = re.sub(r"\s*\([^)]*20\d{2}[^)]*\)\s*$", "", out)
    out = re.sub(r"\s*[—–-]\s*(?:porteur|responsable|owner|pilote)\s*[:\-–].*$", "", out, flags=re.I)
    out = re.sub(r"\s*[—–-]\s*[A-ZÉÈÀ][\wÀ-ÿ''.\- ]{2,40}\s*$", "", out)
    return out.strip(" .;:—–-")


def _parse_pipe_decision(body: str):
    """v17.1.0-B2.3-F.4.2 — Lignes de décision structurées
    « action | porteur | échéance [| objectif] » : extraction propre des colonnes."""
    if body.count("|") < 2:
        return None
    segs = [s.strip() for s in body.split("|")]
    action = _clean_action(segs[0])
    if not action or not _is_real_action(segs[0]):
        return None
    porteur = segs[1] if len(segs) > 1 else ""
    # un porteur plausible est court (≤ 6 mots) et sans échéance/objectif chiffré
    if len(porteur.split()) > 6 or _DEADLINE.search(porteur):
        porteur = _extract_owner(body)
    ech = _extract_deadline(segs[2]) if len(segs) > 2 else ""
    if not ech:
        ech = _extract_deadline(body)
    objectif = segs[3] if len(segs) > 3 else ""
    return AgendaAction(action=action, porteur=porteur.strip(" .–-"),
                        echeance=ech, statut=_extract_statut(body),
                        decision_attendue=objectif[:160])


# -- S.2.4 -- inference Sujet / Porteur + dedup par similarite ------------------
# Run dossier industriel (composants) v3 : Sujet=- et Porteur=- partout, et quasi-doublons non captures
# (deux task-forces, deux road-shows). On INFERE le sujet et le porteur depuis le
# CONTENU de l'action (classification du texte present, rien d'invente), et on
# durcit la dedup via un Jaccard de tokens significatifs.

# (label, motifs) ordre specifique -> general ; 1er match gagne.
_SUJET_RULES = [
    ("Gouvernance financière",
     r"comptes?\s+consolid|(?:fournir|produire|transmettre|obtenir)\s+(?:les\s+|le\s+|des\s+)?comptes|pr[\w]*visionnel|liasse|bilan\b|\bEBITDA\b|tr[\w]*sorerie|cash[- ]?flow|compte\s+de\s+r[\w]*sultat|reporting\s+financier"),
    ("Supply Chain / Sourcing",
     r"supply\s*chain|war\s*room|sous-?traitance|fonderie|usinage|dual\s*sourcing|"
     r"internalisation|sourcing|composants?|OTIF|rupture|stock"),
    ("Capacité industrielle",
     r"extension\s+(?:de\s+)?capacit|ramp[\s-]?up|capacit[\w]*\s+industriel"),
    ("Financement",
     r"financement|cr[\w]*dit-?bail|dilution|tr[\w]*sorerie|\bCAPEX\b|subvention|"
     r"autofinancement|revolving"),
    ("Électrification / Motorisations",
     r"[\w]*lectrification|motorisation|roue\s+[\w]*lectrique|hybride"),
    ("Commercial / Niches",
     r"commercial|\bOEM\b|niches?|road-?show|task-?force|\bBTP\b|d[\w]*fense|"
     r"agricole|mines?|carri[\w]*res?|client|march[\w]*|pipeline"),
    ("Gouvernance / Stratégie",
     r"gouvernance|comit[\w]*|conseil|\bboard\b|reporting|covenant|"
     r"arbitrage|plan\s+strat[\w]*|\bcodir\b|s[\w]*ance|feuille\s+de\s+route"),
]
_PORTEUR_RULES = [
    ("Supply Chain / Achats",
     r"supply\s*chain|war\s*room|sous-?traitance|fonderie|usinage|dual\s*sourcing|"
     r"internalisation|sourcing|composants?|OTIF|stock"),
    ("DAF",
     r"financement|cr[\w]*dit-?bail|dilution|tr[\w]*sorerie|\bCAPEX\b|subvention|"
     r"autofinancement|covenant|revolving|\bcash\b|comptes?\s+consolid|(?:fournir|produire|transmettre|obtenir)\s+(?:les\s+|le\s+|des\s+)?comptes|cash[- ]?flow|pr[\w]*visionnel|liasse|bilan\b|\bEBITDA\b"),
    ("Direction industrielle",
     r"capacit|usine|industriel|production|ramp[\s-]?up"),
    ("Direction commerciale",
     r"commercial|\bOEM\b|niches?|road-?show|task-?force|\bBTP\b|d[\w]*fense|"
     r"agricole|client|march[\w]*|pipeline|vente"),
    ("Direction générale",
     r"gouvernance|comit[\w]*|conseil|\bboard\b|arbitrage|plan\s+strat[\w]*|"
     r"\bcodir\b|dir\.?\s+g[\w]*rale|direction\s+g[\w]*rale"),
]


def _infer_sujet(action: str) -> str:
    if re.search(r"(?:cabinet(?:s)?\s+de\s+transition|r[ée]f[ée]renc\w*\s+(?:dans|aupr[èe]s)\s+(?:des\s+)?cabinet|"
                 r"missions?\s+en\s+sous-?traitance|co-?mandat)", action or "", re.I):
        return "Commercial / Niches"
    for label, rx in _SUJET_RULES:
        if re.search(rx, action or "", re.IGNORECASE):
            return label
    return ""


def _infer_porteur(action: str) -> str:
    if re.search(r"(?:cabinet(?:s)?\s+de\s+transition|r[ée]f[ée]renc\w*\s+(?:dans|aupr[èe]s)\s+(?:des\s+)?cabinet|"
                 r"missions?\s+en\s+sous-?traitance|co-?mandat)", action or "", re.I):
        return "Direction commerciale"
    for label, rx in _PORTEUR_RULES:
        if re.search(rx, action or "", re.IGNORECASE):
            return label
    return ""

_CABINET_BIZDEV_RX = re.compile(
    r"(?:cabinet(?:s)?\s+(?:de\s+)?(?:management\s+de\s+)?transition|"
    r"r[ée]f[ée]renc\w*\s+(?:dans|aupr[èe]s)\s+(?:des\s+)?cabinet|"
    r"missions?\s+en\s+sous-?traitance|co-?mandat|"
    r"partenariat(?:s)?\s+cabinet|contacter\s+\d+(?:[-–]\d+)?\s+cabinet)",
    re.I)


def _normalize_action_route(action: "AgendaAction") -> "AgendaAction":
    """Force les actions d'accès aux cabinets vers le domaine commercial.

    L'origine textuelle peut être une section « Supply Chain » et ne doit pas
    primer sur la sémantique réelle de l'action dans une activité de services.
    """
    if _CABINET_BIZDEV_RX.search(str(getattr(action, "action", "") or "")):
        action.sujet = "Commercial / Niches"
        action.porteur = "Direction commerciale"
    return action



_DEDUP_STOP = {
    "de", "des", "du", "la", "le", "les", "un", "une", "sur", "pour", "et", "ou",
    "en", "au", "aux", "dediee", "dedie", "cibles", "cible", "ciblees", "technique",
    "techniques", "lancer", "lancement", "organiser", "organisation", "mettre",
    "place", "mise", "engagement", "engager",
}


_ACTION_LABELS50 = re.compile(r"(?i)\b(?:à\s+arbitrer|to\s+arbitrate|quoi|what|qui|who|quand|when)\s*[—–:-]\s*")


# 9.4.52 — recette du 05/10 : « Lancement du pilote… » et « Lancer un pilote… » sont la même intention ; la racine de 6
# lettres les séparait (« lancem » / « lancer »). Les substantifs d'action courants sont ramenés à leur verbe.
_NOUN_TO_VERB52 = {"lancement": "lancer", "realisation": "realiser", "presentation": "presenter", "deploiement": "deployer",
                   "cadrage": "cadrer", "validation": "valider", "reconstitution": "reconstituer", "fixation": "fixer",
                   "arbitrage": "arbitrer", "revision": "reviser", "preparation": "preparer", "definition": "definir",
                   "elaboration": "elaborer", "livraison": "livrer", "creation": "creer", "signature": "signer",
                   "negociation": "negocier", "evaluation": "evaluer", "analyse": "analyser", "mesure": "mesurer",
                   "launch": "launch", "launching": "launch", "rollout": "deploy", "deployment": "deploy"}


def _token_set(action: str) -> set:
    # v62.13.9.4.50 — RACINES (6 lettres) : « Communication transparente aux parties prenantes » et « Communiquer de
    # manière transparente… » sont la même intention (contre-recette du 30/09, M01 : 14 doublons sur 66)
    _low = re.sub(r"(?i)\bsg\s*&\s*a\b", " sgaratio ", re.sub(r"(?i)\bp\s*&\s*l\b", " pnl ", action or ""))   # 9.4.52
    k = re.sub(r"[^a-z0-9 ]+", " ", _strip_accents(_ACTION_LABELS50.sub(" ", _low).lower()))
    out = set()
    for w in k.split():
        m = _NOUN_TO_VERB52.get(w, w)
        if len(m) > 2 and m not in _DEDUP_STOP and w not in _DEDUP_STOP:   # même mot vide, nom ou verbe
            out.add(m[:6])
    return out


_MOIS50 = {"janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
           "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
           "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
           "september": 9, "october": 10, "november": 11, "december": 12}


def _month50(echeance: str) -> str:
    """« 2026-12-15 », « décembre 2026 », « 12/2026 » → « 2026-12 » : deux formats d'échéance du même mois (recette du
    01/10 : l'arbitrage homecare figurait deux fois, « 2026-12-15 » et « décembre 2026 »)."""
    s = str(echeance or "").strip().lower()
    m = re.match(r"((?:19|20)\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.match(r"(?:\d{1,2}/)?(\d{1,2})/((?:19|20)\d{2})", s)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    m = re.search(r"([a-zéû]+)\s+((?:19|20)\d{2})", s)
    if m and m.group(1) in _MOIS50:
        return f"{m.group(2)}-{_MOIS50[m.group(1)]:02d}"
    return ""


def _is_near_dup(action: str, echeance: str, kept: list) -> bool:
    """True si l'action recouvre fortement une action deja retenue. Deux signaux :
      - Jaccard de tokens >= 0.6 (quasi-doublon reformule, ex. « Organisation de 2
        road-shows... » vs « Organiser 2 road-shows... ») ;
      - MEME echeance + Jaccard >= 0.35 (meme reco surfacee par deux agents, ex. deux
        « Lancer une task-force ... niches » a la meme date).
    `kept` est une liste de (token_set, echeance)."""
    ts = _token_set(action)
    if not ts:
        return False
    for prev_set, prev_ech in kept:
        if not prev_set:
            continue
        jac = len(ts & prev_set) / len(ts | prev_set)
        if jac >= 0.5:
            return True
        # une reformulation qui CONTIENT l'intention d'une action déjà retenue (commentaire « … : l'option 3 est
        # cohérente avec cette action ») est la même action
        if len(prev_set) >= 3 and len(ts & prev_set) >= 0.8 * len(prev_set):
            return True
        if echeance and prev_ech and (echeance == prev_ech or (_month50(echeance) and _month50(echeance) == _month50(prev_ech))) \
                and (jac >= 0.35 or len(ts & prev_set) >= 3):
            return True               # même échéance et au moins trois racines communes : la même action reformulée
    return False


def extract_actions_from_text(text: str, sujet: str = "", lang: str = "fr") -> List[AgendaAction]:
    """Parcourt le texte, repère les sections d'actions et n'extrait que de VRAIES
    actions (verbe d'action / marqueur / statut), en excluant constats, impacts,
    questions et signaux. Fail-open (liste vide si rien)."""
    if not text:
        return []
    out: List[AgendaAction] = []
    in_action_section = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.lstrip().startswith("#") or re.match(r"^\s*\*\*.+\*\*\s*$", line) \
           or re.match(r"^\s*[A-ZÉÈ0-9][^a-z]{0,60}:?\s*$", line):
            in_action_section = bool(_ACTION_HEADERS.search(line))
            continue
        m = _BULLET.match(line)
        if not m:
            continue
        body = m.group(1).strip()
        if len(body) < 6:
            continue
        # Ligne de décision structurée « action | porteur | échéance » ?
        piped = _parse_pipe_decision(body)
        if piped is not None:
            piped.sujet = sujet or _infer_sujet(piped.action)
            if not piped.porteur:
                piped.porteur = _infer_porteur(piped.action)
            piped = _normalize_action_route(piped)
            piped.source_textuelle = body
            out.append(piped)
            continue
        # Hors section d'action : exiger une échéance pour limiter le bruit.
        if not in_action_section and not _DEADLINE.search(body):
            continue
        # Filtre métier : ne garder que les ACTIONS.
        if not _is_real_action(body):
            continue
        _act = _clean_action(body) or body
        _agenda_action = AgendaAction(
            action=_act,
            sujet=sujet or _infer_sujet(_act),
            porteur=_extract_owner(body) or _infer_porteur(_act),
            echeance=_extract_deadline(body),
            statut=_extract_statut(body),
            source_textuelle=body,
        )
        out.append(_normalize_action_route(_agenda_action))
    return out


def _dedup_key(action: str) -> str:
    """Clé de dédup robuste : minuscule, sans marqueurs/dates/ponctuation."""
    k = action.lower()
    k = re.sub(r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b|\b[tqs][1-4]\s*20\d{2}\b|\b20\d{2}\b", " ", k)
    k = re.sub(r"[^a-zà-ÿ ]+", " ", k)
    k = re.sub(r"\s+", " ", k).strip()
    return k[:70]


def build_register(decision_final: str = "", sources_texts: Optional[List[str]] = None,
                   genre: str = "", sujet: str = "",
                   prochaine_revue: str = "",
                   lang: str = "fr") -> AgendaRegister:
    """Construit le registre depuis la décision réconciliée + les textes porteurs
    d'actions (synthèse, DG, commercial…). Déduplique les actions identiques."""
    if not prochaine_revue:
        if str(genre or "").upper() in {"MARKET_STUDY", "BIZDEV_PLAN"}:
            prochaine_revue = "Next steering review" if lang == "en" else "Prochaine revue de pilotage"
        else:
            prochaine_revue = "Next CoDIR" if lang == "en" else "Prochain CoDIR"
    reg = AgendaRegister(genre=genre, decision_final=decision_final or "")
    seen = set()
    kept_sets: list = []   # S.2.4 -- token-sets retenus pour la dedup par similarite
    for txt in (sources_texts or []):
        for a in extract_actions_from_text(txt, sujet=sujet, lang=lang):
            a = _normalize_action_route(a)
            if not is_semantic_action(a.action):
                continue
            key = _dedup_key(a.action)
            if not key or key in seen:
                continue
            if _is_near_dup(a.action, a.echeance, kept_sets):   # S.2.4 -- quasi-doublons
                continue
            seen.add(key)
            kept_sets.append((_token_set(a.action), a.echeance))
            a.prochaine_revue = prochaine_revue
            # v62.13.9.4.50 — la décision RÉCONCILIÉE est la recommandation des agents, pas une décision du CoDIR
            # (contre-recette du 30/09, C01 : elle revenait à la séance suivante comme « Décision du CoDIR
            # précédent »). Elle n'est plus recopiée en « décision prise » : seul le brief du dirigeant établit une
            # décision.
            reg.items.append(a)
    return reg
