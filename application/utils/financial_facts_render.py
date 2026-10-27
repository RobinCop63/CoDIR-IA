"""
CoDIR-IA — utils/financial_facts_render.py — Since v16.5.72

Module de rendu PPTX pour la table de traçabilité des faits financiers.

Ajoute une slide dédiée "Faits financiers utilisés" si la table contient
au moins 1 fait. La slide reprend les colonnes : Statut · Fait · Valeur ·
Source · Page.

Apprentissage ChatGPT round 14 : la cohérence Word ↔ PPT est critique.
Si un chiffre est À_VÉRIFIER dans le DOCX, il doit rester À_VÉRIFIER dans
le PPTX (pas devenir affirmatif).
"""

from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, Optional


# ─────────────────────────────────────────────────────────────────────────────
# v17.2-M.2 — Sélection des faits du deck (cap 10) : importance PUIS force de preuve
# ─────────────────────────────────────────────────────────────────────────────
# Fragments de libellé classant l'IMPORTANCE de la métrique (ordre = priorité).
PRIORITY_LABELS_FRAGMENTS = (
    "revenue", "chiffre d'affaires", "ca",
    "operating profit", "résultat",
    "ebitda", "ebit",
    "net income", "résultat net",
    "free cash flow", "fcf",
    "total assets", "total actif",
    "cash and cash equivalents", "trésorerie",
    "total equity", "capitaux propres",
    "net debt", "dette nette",
    "marge", "margin",
)

# Force de preuve par statut (plus petit = plus fort → priorité d'affichage).
_DECK_STATUS_STRENGTH = {
    "FAIT": 0, "ESTIM IA": 2, "ESTIM": 2, "HYPOTHÈSE": 3,
    "À VÉRIFIER": 3, "A VÉRIFIER": 3, "NON SOURCÉ": 4,
}

# ── M.5.10.1 (Language Closure — exhaustivité) — localisation FR↔EN des
# badges de périmètre et des statuts métier de la table de faits financiers.
_SCOPE_BADGE_LOC = {
    "fr": {
        "CONSOLIDATED": "CONSOLIDÉ groupe", "HOLDING": "HOLDING social (mère)",
        "SOCIAL_STANDALONE": "SOCIAL standalone", "SEGMENT": "SEGMENT",
        "MARKET": "MARCHÉ", "ESTIMATE": "ESTIMÉ",
    },
    "en": {
        "CONSOLIDATED": "GROUP CONSOLIDATED", "HOLDING": "HOLDING standalone",
        "SOCIAL_STANDALONE": "ENTITY standalone", "SEGMENT": "SEGMENT",
        "MARKET": "MARKET", "ESTIMATE": "ESTIMATED",
    },
}

_FACT_STATUS_LOC_EN = {
    "FAIT": "FACT",
    "À VÉRIFIER": "TO VERIFY", "A VÉRIFIER": "TO VERIFY",
    "NON SOURCÉ": "UNSOURCED",
    "ESTIM IA": "AI ESTIMATE", "ESTIM": "ESTIMATE",
    "ESTIM-COMPARABLE": "ESTIMATE-COMPARABLE",
    "ESTIM-FILINGS": "ESTIMATE-FILINGS",
    "ESTIM-NARRATIF": "ESTIMATE-NARRATIVE",
    "HYPOTHÈSE": "HYPOTHESIS",
}


def loc_scope_badge(scope: str, lang: str = "fr") -> str:
    """Badge de périmètre localisé (vide si scope inconnu)."""
    table = _SCOPE_BADGE_LOC.get((lang or "fr").lower(), _SCOPE_BADGE_LOC["fr"])
    return table.get(str(scope), "")


def loc_fact_status(status: str, lang: str = "fr") -> str:
    """Statut métier localisé. En FR, renvoie tel quel ; en EN, mappe vers l'anglais."""
    s = str(status or "").strip()
    if (lang or "fr").lower() != "en":
        return s
    return _FACT_STATUS_LOC_EN.get(s.upper(), _FACT_STATUS_LOC_EN.get(s, s))


def _deck_label_priority(fact: Any) -> int:
    """Rang d'IMPORTANCE de la métrique d'après le libellé (0 = plus important)."""
    label_lower = str((fact or {}).get("label", "")).lower()
    for i, frag in enumerate(PRIORITY_LABELS_FRAGMENTS):
        if frag in label_lower:
            return i
    return 999


def _deck_fact_strength(fact: Any) -> int:
    """Rang de FORCE DE PREUVE (plus petit = plus fiable). Statut + page citée :
    un FAIT page-cité (0) passe devant un FAIT sans page (1), lui-même devant une
    estimation, etc. Sert de critère SECONDAIRE au cap des 10 lignes du deck."""
    status = str((fact or {}).get("status", "")).upper()
    base = 4
    for k, v in _DECK_STATUS_STRENGTH.items():
        if status.startswith(k.upper()):
            base = v
            break
    page = (fact or {}).get("page")
    has_page = isinstance(page, int) or (
        isinstance(page, str) and page.strip() not in ("", "—", "-", "n/a", "N/A"))
    return base * 2 - (1 if has_page else 0)


def _deck_fact_sort_key(fact: Any):
    """Clé de tri du deck : (importance métrique, force de preuve). L'importance
    reste primaire (les métriques phares mènent) ; à importance égale — et dans le
    fourre-tout des autres faits — le plus fiable (FAIT page-cité) gagne sa place."""
    return (_deck_label_priority(fact), _deck_fact_strength(fact))


# ─────────────────────────────────────────────────────────────────────────────
# Slide PPTX — Faits financiers utilisés
# ─────────────────────────────────────────────────────────────────────────────


def pptx_add_financial_facts_slide(
    prs: Any,
    financial_facts_table: Optional[dict],
    lang: str = "fr",
) -> bool:
    """
    Ajoute une slide "Faits financiers utilisés" en fin de deck.

    Args:
        prs                       : Presentation (pptx.Presentation)
        financial_facts_table     : dict avec clés 'diag', 'facts', 'markdown'
                                    (cf. codir_engine result['financial_facts_table'])
        lang                      : "fr" ou "en"

    Returns:
        True si la slide a été ajoutée, False sinon (pas assez de faits ou erreur)

    Défensif : si erreur de rendu, retourne False sans crash.
    """
    if not financial_facts_table or not isinstance(financial_facts_table, dict):
        return False

    facts = financial_facts_table.get("facts") or []
    # B.1.3.56 (P0-F56-02) — défense en profondeur : jamais de fait
    # diagnostics-only dans un rendu, même si le payload amont a fui.
    try:
        from utils.financial_facts_table import is_visible_fact as _ivf56r
        facts = [r for r in facts if _ivf56r(r)]
    except Exception:
        pass
    if len(facts) < 1:
        return False
    # B.1.3.5 (audit dossier industriel (composants) P1) — les hypothèses NARRATIVES d'agents
    # (« Narratif agents ») n'entrent pas dans la slide de preuve du deck :
    # comptées, mentionnées, jamais rendues comme faits.
    # B.1.3.6 (audit dossier anglophone coté) — le DECK porte la même réserve que le CR :
    # registre ≠ analyse ⇒ note RELATED visible sur la slide facts.
    _reg_rel136 = bool(financial_facts_table.get("registry_related_only"))
    _reg_name136 = str(financial_facts_table.get("registry_related_name") or "")
    _an_name136 = str(financial_facts_table.get("analysis_entity_name") or "")

    # B.1.3.17 (dossier industriel (composants) run 2 : Marge/Trésorerie narratives DANS la slide facts)
    # — le filtre B2.2 testait « source_doc », clé que to_row_dict n'exportait
    # pas (il exporte « source » formaté) : filtre mort sur le chemin rows.
    # On lit les DEUX clés ; source_doc est désormais aussi exporté aux rows.
    def _nsrc17(f: Any) -> str:
        if isinstance(f, dict):
            return str(f.get("source_doc") or f.get("source") or "")
        return str(getattr(f, "source_doc", "") or "")
    _narr135 = [f for f in facts if _nsrc17(f).startswith("Narratif agents")]
    if _narr135:
        facts = [f for f in facts if f not in _narr135]
        if len(facts) < 1:
            return False

    # v17.1-B2.2 — DECK NON TROMPEUR (invariant de présentation, pas de
    # suppression). On ne mélange jamais deux périmètres comme s'ils étaient
    # comparables : si une métrique existe en CONSOLIDÉ, son équivalent SOCIAL
    # standalone est relégué du tableau primaire vers une note de périmètre.
    # Le ledger, lui, conserve tout (cf. select_deck_primary).
    _integrity_note_txt = ""
    _all_facts_for_guard = list(facts)  # v17.1-B2.2.1 — avant filtrage, pour l'invariant honnêteté
    try:
        from patches.finance_shaper import select_deck_primary, integrity_note
        # B.1.3.12 (contrat table canonique CR/PPT — audit #3) : le deck
        # affichait OP+savings mais cachait les revenues brief-only qu'il
        # utilise partout ailleurs. Alignement : mêmes faits que le CR,
        # marquage « brief, not certified » par ligne conservé.
        _primary, _demoted = select_deck_primary(facts, demote_brief=False)
        facts = _primary  # v17.1-B2.2.3 — accepte une primaire VIDE ; ne JAMAIS
                          # restaurer les faits relégués (le « if _primary » d'avant
                          # réintroduisait les faibles quand tout était relégué).
        _integrity_note_txt = integrity_note(_demoted, lang=lang)
    except Exception:
        pass
    if _reg_rel136:
        _rel_note = ((f"⚠ Métadonnées registre = {_reg_name136} — entité LIÉE, "
                      f"non probantes pour {_an_name136}.") if lang == "fr" else
                     (f"⚠ Registry metadata = {_reg_name136} — RELATED entity, "
                      f"not evidentiary for {_an_name136}."))
        _integrity_note_txt = ((_integrity_note_txt + " · ") if _integrity_note_txt
                               else "") + _rel_note
    if _narr135:
        _mention = ((f"{len(_narr135)} hypothèse(s) narrative(s) d'agents au CR "
                     f"(non probantes, hors preuve)") if lang == "fr" else
                    (f"{len(_narr135)} agent narrative hypothesis(es) in the "
                     f"report (non-evidentiary)"))
        _integrity_note_txt = ((_integrity_note_txt + " · ") if _integrity_note_txt
                               else "⚠ ") + _mention
    # v17.1-B2.2 — l'invariant scorer a besoin de savoir si le scorer a tourné.
    _scorer_ok = bool(financial_facts_table.get("scorer_ok", True))

    # Patch v16.5.72.2 (audit ChatGPT round 17) — Limite et priorisation PPT.
    # Trop dense en v16.5.72.1 (Since v16.5.72.1 — 14 lignes mélangeant Revenue + Company Number).
    # Solution : prioriser les VRAIS faits financiers, limiter à 10 lignes
    # pour rester lisible. Le détail complet reste dans le DOCX.
    #
    # v17.2-M.2 — tri à DEUX critères : (1) importance de la métrique (fragment de
    # libellé), puis (2) FORCE DE PREUVE (statut + page citée). Avant, le tri
    # ignorait le statut : dans le fourre-tout « autres faits », c'est l'ordre
    # d'arrivée qui décidait quelles lignes survivaient au cap de 10 — pas la
    # fiabilité. Désormais, à importance égale, un FAIT page-cité passe devant une
    # estimation : ce sont les faits les plus fiables qui occupent les 10 places.
    sorted_facts = sorted(facts, key=_deck_fact_sort_key)
    max_rows_pptx = 10  # round 17 : 8-10 faits clés max

    diag = financial_facts_table.get("diag") or {}

    try:
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor
        from pptx.enum.shapes import MSO_SHAPE
        # M.5.10.4 — localisation EN libellé/source au rendu deck
        from utils.financial_facts_table import (
            _localize_metric_label, _localize_source,
        )

        slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank

        # ── En-tête ─────────────────────────────────────────────────────────
        # Bandeau bleu en haut
        _shape_bg = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0), Inches(0), prs.slide_width, Inches(1.0)
        )
        _shape_bg.fill.solid()
        _shape_bg.fill.fore_color.rgb = RGBColor(0x2E, 0x4A, 0x7F)
        _shape_bg.line.fill.background()

        # Titre
        title_text = (
            "📋 FAITS FINANCIERS UTILISÉS"
            if lang == "fr" else
            "📋 FINANCIAL FACTS USED"
        )
        tb_title = slide.shapes.add_textbox(
            Inches(0.4), Inches(0.15), prs.slide_width - Inches(0.8), Inches(0.5)
        )
        tb_title.name = "HCRIT:facts:title"
        tf_title = tb_title.text_frame
        tf_title.margin_top = Pt(2)
        p = tf_title.paragraphs[0]
        run = p.add_run()
        run.text = title_text
        run.font.size = Pt(20)
        run.font.bold = True
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

        # Sous-titre : score + breakdown
        score = diag.get("traceability_score", 0)
        n_solid = diag.get("n_facts_solid", 0)
        n_estim = diag.get("n_facts_estimate", 0)
        n_unsourced = diag.get("n_facts_unsourced", 0)
        n_total = diag.get("n_facts_total", 0)

        if lang == "fr":
            subtitle = (
                f"Traçabilité {score}/100 — "
                f"{n_solid} fait(s), {n_estim} estimation(s), "
                f"{n_unsourced} non sourcé(s) (total {n_total})"
            )
        else:
            subtitle = (
                f"Traceability {score}/100 — "
                f"{n_solid} fact(s), {n_estim} estimate(s), "
                f"{n_unsourced} unsourced (total {n_total})"
            )

        # v17.1-B2.2 / B2.2.1 — INVARIANT D'HONNÊTETÉ (présentation).
        # Deux gardes, pas une seule :
        #  (a) scorer KO/non tourné → libellé de revue humaine (pas de 100/100) ;
        #  (b) scorer OK mais métrique CONSOLIDÉE critique (CA, résultat net)
        #      absente → score INDICATIF (la table est incomplète, le score ne
        #      doit pas se présenter comme board-safe).
        if not _scorer_ok:
            subtitle = (
                "Score non calculé — revue humaine requise"
                if lang == "fr" else
                "Score not computed — human review required"
            )
        else:
            try:
                from patches.finance_shaper import traceability_label
                _tl = traceability_label(
                    {"traceability_score": score, "facts": _all_facts_for_guard},
                    scorer_ok=True, lang=lang,
                )
                if _tl.get("guarded"):
                    subtitle = _tl["label"]
            except Exception:
                pass
        tb_sub = slide.shapes.add_textbox(
            Inches(0.4), Inches(0.55), prs.slide_width - Inches(0.8), Inches(0.4)
        )
        tb_sub.name = "HCRIT:facts:subtitle"
        tf_sub = tb_sub.text_frame
        p_sub = tf_sub.paragraphs[0]
        run_sub = p_sub.add_run()
        run_sub.text = subtitle
        run_sub.font.size = Pt(11)
        run_sub.font.italic = True
        run_sub.font.color.rgb = RGBColor(0xE8, 0xE8, 0xF0)

        # v17.1-B2.2.3 — primaire VIDE (tous les faits relégués : social ou
        # source non board-safe). On l'affiche EXPLICITEMENT + la note
        # d'intégrité, sans restaurer de faits relégués ni laisser une table vide.
        if not sorted_facts:
            _msg = ("Aucun fait board-primary affichable — tous les faits financiers "
                    "ont été relégués (périmètre social standalone et/ou source non "
                    "board-safe). Voir la note d'intégrité ci-dessous."
                    if lang == "fr" else
                    "No board-primary fact to display — all financial facts were "
                    "demoted (social standalone scope and/or non-board-safe source). "
                    "See the integrity note below.")
            _tb_empty = slide.shapes.add_textbox(
                Inches(0.4), Inches(1.3), prs.slide_width - Inches(0.8), Inches(0.9))
            _tb_empty.text_frame.word_wrap = True
            _re = _tb_empty.text_frame.paragraphs[0].add_run()
            _re.text = _msg
            _re.font.size = Pt(12)
            _re.font.color.rgb = RGBColor(0xB0, 0x5A, 0x00)
            if _integrity_note_txt:
                _tb_n = slide.shapes.add_textbox(
                    Inches(0.4), Inches(2.3), prs.slide_width - Inches(0.8), Inches(0.9))
                _tb_n.text_frame.word_wrap = True
                _rn = _tb_n.text_frame.paragraphs[0].add_run()
                _rn.text = _integrity_note_txt
                _rn.font.size = Pt(9)
                _rn.font.italic = True
                _rn.font.color.rgb = RGBColor(0xB0, 0x5A, 0x00)
            return True

        # ── Table des faits ──────────────────────────────────────────────────
        # Patch v16.5.72.2 — Limiter à 10 faits clés priorisés (ChatGPT round 17)
        max_rows = max_rows_pptx
        n_show = min(len(sorted_facts), max_rows)

        # Position de la table : sous le bandeau
        table_left = Inches(0.3)
        table_top = Inches(1.2)
        table_width = prs.slide_width - Inches(0.6)
        # Hauteur dynamique : ~0.35 inch par ligne
        table_height = Inches(0.4 + 0.35 * (n_show + 1))

        rows = n_show + 1  # +1 pour header
        cols = 5  # Statut, Fait, Valeur, Source, Page

        table_shape = slide.shapes.add_table(
            rows, cols, table_left, table_top, table_width, table_height
        )
        table_shape.name = "HCRIT:facts:table"
        table = table_shape.table

        # Largeurs relatives au canevas réel (9,4 pouces disponibles sur le
        # deck 10 pouces) — aucune somme de colonnes ne dépasse le cadre.
        _ratios = (1.25, 2.25, 1.70, 3.40, 0.80)
        _avail = int(table_width)
        _sum = sum(_ratios)
        _widths = [max(1, int(_avail * r / _sum)) for r in _ratios]
        _widths[-1] += _avail - sum(_widths)
        for _col, _w in zip(table.columns, _widths):
            _col.width = _w

        # En-têtes
        if lang == "fr":
            headers = ["Statut", "Fait", "Valeur", "Source", "Page"]
        else:
            headers = ["Status", "Fact", "Value", "Source", "Page"]
        for i, h in enumerate(headers):
            cell = table.cell(0, i)
            cell.text = h
            for para in cell.text_frame.paragraphs:
                for r in para.runs:
                    r.font.size = Pt(10)
                    r.font.bold = True
                    r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(0x2E, 0x4A, 0x7F)

        # Lignes de données (badges + statuts localisés — M.5.10.1)
        for ridx, fact in enumerate(sorted_facts[:n_show], start=1):
            # B.1.3.8 (audit #3) — quand le registre est une entité LIÉE, chaque
            # ligne de MÉTADONNÉE du deck porte le statut, pas seulement la note
            # de bas de slide : le deck circule seul.
            _rel_row136 = (_reg_rel136 and any(
                k in str(fact.get("source", "") or "")
                for k in ("Companies House", "GLEIF", "Pappers")))
            # B.1.3.17 (dossier industriel (composants) run 2 : « ✅ FAIT » nu au deck sur le Résultat
            # net Pappers SOCIAL) — parité to_markdown_table/Zone A : le statut
            # HORS PÉRIMÈTRE REMPLACE icône+statut (⚡ conflit cumulable) ;
            # aucun suffixe brief/RELATED ne s'y accroche.
            _pm17 = (str(fact.get("perimeter_match", "") or "") == "MISMATCH")
            _cf17 = "⚡" if str(fact.get("conflict_group_id", "") or "") else ""
            if _pm17:
                # B.1.3.23 P1-H' — double qualification : hors périmètre ET
                # source faible/À VÉRIFIER s'affichent ensemble.
                _av17 = "VÉRIF" in str(fact.get("status", "") or "").upper() \
                        or "A_VERIFIER" in str(fact.get("status", "") or "").upper()
                status_text = "⛔" + _cf17 + " " + (
                    ("HORS PÉRIMÈTRE — exclu du score"
                     + (" · À VÉRIFIER (source faible)" if _av17 else ""))
                    if lang == "fr" else
                    ("OUT OF PERIMETER — excluded from score"
                     + (" · TO VERIFY (weak source)" if _av17 else "")))
            else:
                status_text = f"{fact.get('icon', '')} {loc_fact_status(fact.get('status', ''), lang)}" + (
                    (" ⚠ RELATED" if lang == "en" else " ⚠ LIÉE") if _rel_row136 else "") + (
                    (" — brief non certifié" if lang == "fr"
                     else " — brief, not certified")
                    if fact.get("brief_only") else "")
            # v17.1-B2.2 — BADGE DE PÉRIMÈTRE obligatoire : l'humain arbitre sur
            # une information lisible (ex. « [CONSOLIDÉ groupe] Résultat net »).
            _scope = str(fact.get("scope", "UNKNOWN"))
            _badge = loc_scope_badge(_scope, lang)
            # M.5.10.4 — libellé ET source localisés au rendu deck (fuite EN audit)
            _label = _localize_metric_label(str(fact.get("label", "")), lang)
            # B.1.3.17 (run 9 dossier anglophone coté : deux « Revenue » nus) — période au
            # label deck, mêmes règles que _per14 (Zone A) et to_markdown_table.
            _per17 = str(fact.get("period") or "").strip()
            if _per17:
                _label = f"{_label} ({_per17})"
            _label_disp = (f"[{_badge}] {_label}" if _badge else _label)
            row_data = [
                status_text,
                _label_disp,
                str(fact.get("value", "")),
                _localize_source(str(fact.get("source", "")), lang),
                str(fact.get("page", "—")),
            ]
            for cidx, val in enumerate(row_data):
                cell = table.cell(ridx, cidx)
                cell.text = val
                for para in cell.text_frame.paragraphs:
                    for r in para.runs:
                        r.font.size = Pt(8)
                # Alternance fond
                if ridx % 2 == 0:
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = RGBColor(0xF5, 0xF7, 0xFA)

        # Note "facts supplémentaires" si troncature
        if len(sorted_facts) > max_rows:
            tb_more = slide.shapes.add_textbox(
                Inches(0.3),
                table_top + table_height + Inches(0.1),
                prs.slide_width - Inches(0.6),
                Inches(0.4),
            )
            tf_more = tb_more.text_frame
            p_more = tf_more.paragraphs[0]
            run_more = p_more.add_run()
            n_more = len(sorted_facts) - max_rows
            run_more.text = (
                f"… {n_more} fait(s) supplémentaire(s) — détail dans le rapport Word."
                if lang == "fr" else
                f"… {n_more} additional fact(s) — full list in Word report."
            )
            run_more.font.size = Pt(9)
            run_more.font.italic = True
            run_more.font.color.rgb = RGBColor(0x70, 0x70, 0x80)

        # v17.1-B2.2 — Note d'intégrité : les faits SOCIAL standalone relégués
        # (conservés au ledger) sont signalés ici pour que rien ne soit masqué.
        if _integrity_note_txt:
            tb_note = slide.shapes.add_textbox(
                Inches(0.3),
                table_top + table_height + Inches(0.45),
                prs.slide_width - Inches(0.6),
                Inches(0.6),
            )
            p_note = tb_note.text_frame.paragraphs[0]
            tb_note.text_frame.word_wrap = True
            run_note = p_note.add_run()
            run_note.text = _integrity_note_txt
            run_note.font.size = Pt(9)
            run_note.font.italic = True
            run_note.font.color.rgb = RGBColor(0xB0, 0x5A, 0x00)

        return True

    except Exception as e:
        import logging
        logging.getLogger("codir_ia").warning(
            f"pptx_add_financial_facts_slide failed: {type(e).__name__}: {e}"
        )
        return False


def enrich_pptx_bytes_with_financial_facts(
    pptx_bytes: bytes,
    financial_facts_table: Optional[dict],
    lang: str = "fr",
) -> bytes:
    """
    Prend un PPTX sous forme de bytes, ajoute la slide Faits financiers
    si applicable, et retourne les nouveaux bytes.

    Défensif : si erreur, retourne les bytes originaux.
    """
    if not pptx_bytes:
        return pptx_bytes
    if not financial_facts_table or not isinstance(financial_facts_table, dict):
        return pptx_bytes

    facts = financial_facts_table.get("facts") or []
    # B.1.3.56 (P0-F56-02) — défense en profondeur : jamais de fait
    # diagnostics-only dans un rendu, même si le payload amont a fui.
    try:
        from utils.financial_facts_table import is_visible_fact as _ivf56r
        facts = [r for r in facts if _ivf56r(r)]
    except Exception:
        pass
    if len(facts) < 1:
        # Pas de faits à afficher — pas besoin de slide
        return pptx_bytes

    try:
        from pptx import Presentation  # type: ignore
        prs = Presentation(BytesIO(pptx_bytes))
        added = pptx_add_financial_facts_slide(
            prs, financial_facts_table, lang=lang
        )
        if not added:
            return pptx_bytes
        out = BytesIO()
        prs.save(out)
        return out.getvalue()
    except Exception as e:
        import logging
        logging.getLogger("codir_ia").warning(
            f"enrich_pptx_bytes_with_financial_facts failed: {type(e).__name__}: {e}"
        )
        return pptx_bytes


__all__ = [
    "pptx_add_financial_facts_slide",
    "enrich_pptx_bytes_with_financial_facts",
]
