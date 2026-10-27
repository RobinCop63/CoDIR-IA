"""
utils/confidence_render.py — Helpers de rendu du confidence_score + briefcheck banner
v16.5.67 — Livraison tranche 2

Ce module centralise :
1. `docx_add_confidence_block(doc, briefcheck, confidence_score, lang)`
   Insère le bandeau briefcheck WARN (si présent) + bloc confidence score
   en tête du document Word.

2. `pptx_add_confidence_slide(prs, confidence_score, briefcheck, lang)`
   Ajoute une slide dédiée confidence après la slide titre.

Les deux fonctions sont défensives : si briefcheck ou confidence_score est None
ou mal formé, elles no-op silencieusement. Aucune régression possible.
"""

from __future__ import annotations

from typing import Any, Optional

# =============================================================================
# TEXTE DE MISE EN FORME (FR / EN)
# =============================================================================

_L: dict[str, dict[str, str]] = {
    "fr": {
        "score_title":        "SCORE DE CONFIANCE DU LIVRABLE",
        "score_line":         "Score : {score}/100 — Grade {grade}",
        "score_label":        "{label}",
        "subscores_title":    "Sous-scores",
        "sq":                 "Qualité des sources",
        "mix":                "Mix de contenu",
        "cons":               "Cohérence",
        "comp":               "Complétude",
        "stab":               "Stab. exécution",
        "sect":               "Confiance secteur",
        "why_title":          "Pourquoi ce score",
        "usage_title":        "Usage recommandé",
        "work_usage_title":   "Usage du document de travail",
        "utility_title":      "UTILITÉ DÉCISIONNELLE",
        "utility_line":       "Utilité décisionnelle : {score}/100 — Niveau {band}",
        "consultant_work":    "Consultant / manager de transition",
        "sme_reflection":     "Dirigeant PME / PMI",
        "final_delivery":     "Remise telle quelle au client final",
        "codir":              "CoDIR interne",
        "client":             "Présentation client",
        "board":              "Conseil",
        "public":             "Diffusion externe",
        "actions_title":      "Actions prioritaires",
        "trend_first":        "(tendance non calculée)",
        "trend_improve":      "▲ amélioration ({delta:+d} pts vs run précédent {prev})",
        "trend_stable":       "≈ stable ({delta:+d} pts vs run précédent {prev})",
        "trend_degrade":      "▼ dégradation ({delta:+d} pts vs run précédent {prev})",
        "basic_mode_note":    ("Mode v4 basique : le score est plafonné mécaniquement "
                               "par l'absence de métriques JSON typées côté agents. "
                               "Les grades B et A requièrent des faits confirmés à la page citée."),
        "warn_title":         "AVERTISSEMENT — Données sources non fournies",
        # v16.5.65 — mode brief
        "mode_generic_title": "MODE GÉNÉRIQUE — AUCUN CONTEXTE CLIENT FOURNI",
        "mode_partial_title": "MODE PARTIEL — Brief partiellement qualifié",
        "mode_framed_title":  "MODE CADRÉ — Brief complet",
        "mode_cap_note":      "Signal pondéré avant cap brief : {raw}/100 · cap brief : {cap}/100",
        "mode_missing_title": "Pour obtenir un livrable actionnable :",
        "mode_present_title": "Leviers renseignés",
        "usage_values": {
            "OK":                      "OK",
            "OK_WITH_REVIEW":          "OK après revue senior",
            "OK_WITH_FINAL_REVIEW":    "OK après revue finale",
            "LIMITED":                 "Usage limité",
            "NO":                      "Non recommandé",
        },
    },
    "en": {
        "score_title":        "DELIVERY CONFIDENCE SCORE",
        "score_line":         "Score: {score}/100 — Grade {grade}",
        "score_label":        "{label}",
        "subscores_title":    "Sub-scores",
        "sq":                 "Source quality",
        "mix":                "Content mix",
        "cons":               "Consistency",
        "comp":               "Completeness",
        "stab":               "Exec. stability",
        "sect":               "Sector confidence",
        "why_title":          "Why this score",
        "usage_title":        "Recommended usage",
        "work_usage_title":   "Work-product use",
        "utility_title":      "DECISION USEFULNESS",
        "utility_line":       "Decision usefulness: {score}/100 — Band {band}",
        "consultant_work":    "Consultant / transition manager",
        "sme_reflection":     "SME leader reflection",
        "final_delivery":     "Final client delivery as-is",
        "codir":              "Internal CoDIR",
        "client":             "Client presentation",
        "board":              "Board",
        "public":             "External public",
        "actions_title":      "Priority actions",
        "trend_first":        "(trend not calculated)",
        "trend_improve":      "▲ improvement ({delta:+d} pts vs previous run {prev})",
        "trend_stable":       "≈ stable ({delta:+d} pts vs previous run {prev})",
        "trend_degrade":      "▼ degradation ({delta:+d} pts vs previous run {prev})",
        "basic_mode_note":    ("v4 basic mode: the score is mechanically capped by the "
                               "absence of typed JSON metrics from agents. Delivery 2 "
                               "will unlock grades B and A."),
        "warn_title":         "WARNING — Source data not provided",
        # v16.5.65 — brief mode
        "mode_generic_title": "GENERIC MODE — NO CLIENT CONTEXT PROVIDED",
        "mode_partial_title": "PARTIAL MODE — Partially qualified brief",
        "mode_framed_title":  "FRAMED MODE — Complete brief",
        "mode_cap_note":      "Weighted signal before brief cap: {raw}/100 · brief cap: {cap}/100",
        "mode_missing_title": "To produce an actionable deliverable:",
        "mode_present_title": "Levers provided",
        "usage_values": {
            "OK":                      "OK",
            "OK_WITH_REVIEW":          "OK after senior review",
            "OK_WITH_FINAL_REVIEW":    "OK after final review",
            "LIMITED":                 "Limited use",
            "NO":                      "Not recommended",
        },
    },
}


def _t(key: str, lang: str = "fr") -> str:
    lang = lang if lang in ("fr", "en") else "fr"
    return _L[lang].get(key, key)


def _grade_color_rgb(grade: str) -> tuple[int, int, int]:
    """Code couleur pour le grade. Format (R, G, B)."""
    return {
        "A": (39, 174, 96),     # vert foncé
        "B": (82, 190, 128),    # vert clair
        "C": (244, 208, 63),    # jaune
        "D": (230, 126, 34),    # orange
        "E": (203, 67, 53),     # rouge foncé
    }.get(str(grade).upper(), (127, 140, 141))  # gris


def _usage_label(code: str, lang: str) -> str:
    return _L[lang if lang in ("fr", "en") else "fr"]["usage_values"].get(str(code), str(code))


def _decision_usefulness(cs: dict) -> dict:
    value = cs.get("decision_usefulness") if isinstance(cs, dict) else None
    if not isinstance(value, dict):
        return {}
    # v62.4 — le score de preuve peut être plafonné après le calcul secondaire
    # (fidelity gate). Le rendu doit toujours afficher UNE source de vérité.
    out = dict(value)
    proof_score = int((cs or {}).get("score") or 0)
    proof_grade = str((cs or {}).get("grade") or "?")
    out["evidence_score"] = proof_score
    out["evidence_grade"] = proof_grade
    rationale = list(out.get("rationale") or [])
    if rationale:
        en = str(rationale[0]).lower().startswith("evidence")
        rationale[0] = ((f"Evidence sufficiency remains {proof_score}/100 (Grade {proof_grade}); "
                         "it limits assertions, not the exploratory value of the work product.")
                        if en else
                        (f"La solidité probatoire reste à {proof_score}/100 (Grade {proof_grade}) ; "
                         "elle limite les affirmations, pas la valeur exploratoire du document de travail."))
        out["rationale"] = rationale
    return out


def _work_product_usage_items(cs: dict, lang: str) -> list[tuple[str, str]]:
    du = _decision_usefulness(cs)
    usage = du.get("usage") if isinstance(du, dict) else None
    if not isinstance(usage, dict):
        return []
    return [
        (_t("consultant_work", lang), str(usage.get("consultant_working_document_label", "?"))),
        (_t("sme_reflection", lang), str(usage.get("sme_leader_reflection_label", "?"))),
        (_t("final_delivery", lang), str(usage.get("final_client_delivery_label", "?"))),
        (_t("public", lang), str(usage.get("external_distribution_label", "?"))),
    ]


def _trend_label(cs: dict, lang: str) -> str:
    lbl = str(cs.get("trend_label", ""))
    prev = cs.get("previous_score")
    delta = cs.get("delta")
    if lbl == "FIRST_RUN" or prev is None or delta is None:
        return _t("trend_first", lang)
    if lbl in ("STRONG_IMPROVEMENT", "IMPROVING"):
        return _t("trend_improve", lang).format(delta=delta, prev=prev)
    if lbl == "STABLE":
        return _t("trend_stable", lang).format(delta=delta, prev=prev)
    # DEGRADING / STRONG_DEGRADATION
    return _t("trend_degrade", lang).format(delta=delta, prev=prev)


# =============================================================================
# DOCX RENDER
# =============================================================================

def _docx_add_mode_banner(doc: Any,
                          briefcheck: dict,
                          lang: str,
                          Pt: Any, RGBColor: Any) -> None:
    """
    v16.5.65 — Bandeau MODE DE BRIEFING (GENERIC rouge / PARTIAL jaune).
    No-op si mode = FRAMED ou si brief_mode absent.
    """
    bm = briefcheck.get("brief_mode") or {}
    mode = str(bm.get("mode", "")).upper()
    if mode not in ("GENERIC", "PARTIAL"):
        return

    present = bm.get("present_count", 0)
    missing = bm.get("missing") or []
    score_cap = bm.get("score_cap")

    # Couleur selon criticité
    if mode == "GENERIC":
        color_rgb = RGBColor(203, 67, 53)    # rouge foncé
        title_key = "mode_generic_title"
        emoji = "🔴"
    else:  # PARTIAL
        color_rgb = RGBColor(230, 126, 34)   # orange
        title_key = "mode_partial_title"
        emoji = "🟡"

    # Titre encadré
    title_para = doc.add_paragraph()
    t_run = title_para.add_run(f"{emoji} {_t(title_key, lang)}")
    t_run.bold = True
    t_run.font.size = Pt(12)
    t_run.font.color.rgb = color_rgb

    # Sous-titre : x/4 leviers + plafond
    if mode == "PARTIAL":
        sub_para = doc.add_paragraph()
        sub_run = sub_para.add_run(f"{present}/4 leviers renseignés"
                                   if lang == "fr" else f"{present}/4 levers provided")
        sub_run.italic = True
        sub_run.font.size = Pt(10)

    # Leviers manquants
    if missing:
        miss_title = doc.add_paragraph()
        mt_run = miss_title.add_run(_t("mode_missing_title", lang))
        mt_run.bold = True
        mt_run.font.size = Pt(10)
        for m in missing:
            p = doc.add_paragraph(m, style="List Bullet")
            for run in p.runs:
                run.font.size = Pt(9)

    # Note plafond
    if score_cap is not None and score_cap < 100:
        note_para = doc.add_paragraph()
        note_run = note_para.add_run(
            f"⚠ Score plafonné mécaniquement à {score_cap}/100 (Grade "
            f"{'D' if score_cap <= 45 else 'B'} max). "
            f"Voir bloc Confidence ci-dessous."
            if lang == "fr" else
            f"⚠ Score mechanically capped at {score_cap}/100 (Grade "
            f"{'D' if score_cap <= 45 else 'B'} max). "
            f"See Confidence block below."
        )
        note_run.italic = True
        note_run.font.size = Pt(9)
        note_run.font.color.rgb = color_rgb

    doc.add_paragraph("")


def enforce_run_clarification(usage: dict, lang: str = "fr") -> dict:
    """B.1.3.23.1 candidate — conflit d'entité au brief ou contexte/faits ⇒
    usages exposés BLOQUÉS jusqu'à clarification.

    Le score réel utilise le schéma `usage_recommendation`
    (`internal_codir`, `client_presentation`, `board`, `public_external_use`).
    L'ancien helper ne couvrait que le schéma historique
    (`client`, `board`, `public`), donc le bandeau CR apparaissait mais les
    usages DOCX/PPT pouvaient rester permissifs. Ce helper accepte les deux
    schémas et ne bloque jamais l'usage CoDIR interne.
    """
    blocked = ("⛔ BLOQUÉE — RUN À CLARIFIER" if lang == "fr"
               else "⛔ BLOCKED — RUN TO CLARIFY")
    out = dict(usage or {})

    # Schéma moderne du confidence_score.
    if any(k in out for k in ("internal_codir", "client_presentation",
                              "public_external_use")):
        if "client_presentation" in out:
            out["client_presentation"] = blocked
        if "board" in out:
            out["board"] = blocked
        if "public_external_use" in out:
            out["public_external_use"] = blocked
        return out

    # Schéma historique / tests bas niveau.
    for k in ("client", "board", "public"):
        if k in out:
            out[k] = blocked
    return out


def apply_run_clarification_to_confidence(confidence_score: Optional[dict],
                                          lang: str = "fr",
                                          run_blocked: bool = False,
                                          run_block_reasons: Optional[list] = None
                                          ) -> Optional[dict]:
    """Retourne une copie du confidence_score avec usages bloqués + trace
    machine-readable. Utilisé par DOCX et PPTX pour éviter un câblage divergent.
    """
    if not (run_blocked and isinstance(confidence_score, dict)):
        return confidence_score
    out = dict(confidence_score)
    out["run_not_validatable"] = True
    out["run_block_reasons"] = list(run_block_reasons or [])
    if isinstance(out.get("usage_recommendation"), dict):
        out["usage_recommendation"] = enforce_run_clarification(
            out["usage_recommendation"], lang)
    if isinstance(out.get("usage"), dict):
        out["usage"] = enforce_run_clarification(out["usage"], lang)
    # v62.3 — a clarification conflict must not leave a high usefulness score
    # visible merely because the secondary indicator was computed upstream.
    if isinstance(out.get("decision_usefulness"), dict):
        du = dict(out["decision_usefulness"])
        if int(du.get("score") or 0) > 44:
            du["score"] = 44
            du["band"] = "E"
            du["label"] = ("Insufficient even for internal framing" if lang == "en"
                           else "Insuffisant même pour le cadrage interne")
            du.setdefault("caps", []).append({
                "code": "RUN_CLARIFICATION_RENDER_CAP", "after": 44})
        out["decision_usefulness"] = du
    return out


def docx_add_confidence_block(doc: Any,
                              briefcheck: Optional[dict],
                              confidence_score: Optional[dict],
                              lang: str = "fr",
                              run_blocked: bool = False,
                              run_block_reasons: Optional[list] = None) -> None:
    """
    Insère dans l'ordre (si données présentes) :
    - Bandeau rouge WARN briefcheck (si severity == WARN_BANNER)
    - Bloc confidence_score (score / grade / sous-scores / usage / actions)

    Import différé de python-docx pour éviter d'imposer la dep au module parent.
    No-op silencieux si les dicts sont absents.
    """
    if not briefcheck and not confidence_score:
        return
    try:
        from docx.shared import Pt, RGBColor  # type: ignore
    except Exception:
        return  # pas de docx ? no-op

    lang = lang if lang in ("fr", "en") else "fr"
    if run_blocked:  # B.1.3.23 P0-D — bandeau + usages bloqués
        try:
            _p = doc.add_paragraph()
            _r = _p.add_run(
                ("⛔ RUN À CLARIFIER — conflit détecté ("
                 + " ; ".join(run_block_reasons or ["voir alertes pipeline"])
                 + ") : présentation client, conseil et diffusion externe "
                   "BLOQUÉES tant que l'entité/le périmètre ne sont pas "
                   "clarifiés.") if lang == "fr" else
                ("⛔ RUN TO CLARIFY — conflict detected ("
                 + " ; ".join(run_block_reasons or ["see pipeline alerts"])
                 + "): client presentation, board and external distribution "
                   "BLOCKED until entity/perimeter is clarified."))
            _r.bold = True
            try:
                _r.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
            except Exception:
                pass
        except Exception:
            pass
        confidence_score = apply_run_clarification_to_confidence(
            confidence_score, lang, run_blocked, run_block_reasons)

    # 1. Bandeau briefcheck WARN
    if briefcheck and isinstance(briefcheck, dict):
        dc = briefcheck.get("doc_check") or {}
        if dc.get("severity") == "WARN_BANNER":
            banner = briefcheck.get("banner_markdown", "") or dc.get("banner_markdown", "")
            # v16.5.65 : briefcheck.banner_markdown concatène désormais mode+doc_check ;
            # on préfère donc prendre la version doc_check isolée ici
            banner_doc_only = dc.get("banner_markdown", "")
            banner = banner_doc_only or banner
            if banner:
                # Titre encadré
                warn_title = doc.add_paragraph()
                wt_run = warn_title.add_run("⚠ " + _t("warn_title", lang))
                wt_run.bold = True
                wt_run.font.size = Pt(11)
                wt_run.font.color.rgb = RGBColor(203, 67, 53)
                # Corps du bandeau — on retire les lignes de titre markdown
                body_lines = [ln for ln in banner.split("\n")
                              if ln.strip() and not ln.strip().startswith("⚠")]
                body = "\n".join(body_lines).strip()
                if body:
                    body_para = doc.add_paragraph()
                    body_run = body_para.add_run(body)
                    body_run.font.size = Pt(9)
                    body_run.italic = True
                doc.add_paragraph("")

    # 1bis. v16.5.65 — Bandeau MODE DE BRIEFING (GENERIC / PARTIAL)
    # Prioritaire visuellement : injecté AVANT le score de confiance car c'est
    # l'information la plus structurante pour un DG/DAF qui ouvre le livrable.
    if briefcheck and isinstance(briefcheck, dict):
        _docx_add_mode_banner(doc, briefcheck, lang, Pt=Pt, RGBColor=RGBColor)

    # 2. Bloc confidence_score
    if not (confidence_score and isinstance(confidence_score, dict)):
        return

    score = confidence_score.get("score", "?")
    grade = str(confidence_score.get("grade", "?")).upper()
    label = confidence_score.get("label", "")

    # Titre de bloc + score / grade en gros
    title_para = doc.add_paragraph()
    t_run = title_para.add_run(_t("score_title", lang))
    t_run.bold = True
    t_run.font.size = Pt(11)

    score_para = doc.add_paragraph()
    s_run = score_para.add_run(_t("score_line", lang).format(score=score, grade=grade))
    s_run.bold = True
    s_run.font.size = Pt(14)
    r, g, b = _grade_color_rgb(grade)
    s_run.font.color.rgb = RGBColor(r, g, b)

    # v16.5.76 item 9 — Afficher le score brut hors plafond mécanique
    # quand le brief PARTIAL/GENERIC plafonne le score final.
    # UX : montre au DAF "Tu aurais eu 84 mais ton brief PARTIAL plafonne à 70"
    cap_applied = confidence_score.get("cap_applied", False)
    if cap_applied:
        raw_score = confidence_score.get("raw_score") or confidence_score.get("score_before_mode_cap")
        brief_cap = confidence_score.get("brief_mode_cap")
        if raw_score is not None and brief_cap is not None:
            cap_para = doc.add_paragraph()
            cap_run = cap_para.add_run(
                _t("mode_cap_note", lang).format(cap=brief_cap, raw=raw_score)
            )
            cap_run.italic = True
            cap_run.font.size = Pt(9)
            cap_run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)  # gris discret

    # v62.10 — trace de score nommée et non ambiguë. Les anciennes mentions
    # « brut » pouvaient désigner le score pondéré, le score pré-fidélité ou un
    # autre stade selon la surface.
    _stages = [
        ("weighted" if lang == "en" else "pondéré", confidence_score.get("pre_cap_weighted_score")),
        ("brief cap" if lang == "en" else "après cap brief", confidence_score.get("post_brief_mode_cap_score")),
        ("structured-evidence cap" if lang == "en" else "après cap preuve structurée", confidence_score.get("post_structured_evidence_cap_score")),
        ("pre-fidelity" if lang == "en" else "pré-fidélité", confidence_score.get("pre_fidelity_score")),
        ("final evidence" if lang == "en" else "preuve finale", confidence_score.get("final_evidence_score", score)),
    ]
    _stage_bits = [f"{name} {value}/100" for name, value in _stages if value is not None]
    if _stage_bits:
        _sp = doc.add_paragraph()
        _sr = _sp.add_run(("Score stages: " if lang == "en" else "Étapes du score : ") + " → ".join(_stage_bits))
        _sr.italic = True
        _sr.font.size = Pt(8)
        _sr.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    if label:
        label_para = doc.add_paragraph()
        l_run = label_para.add_run(label)
        l_run.italic = True
        l_run.font.size = Pt(10)

    # M.5.10.4 — Language Gate : raison du plafond VISIBLE dans le CR.
    _lg = confidence_score.get("language_gate")
    if isinstance(_lg, dict) and str(_lg.get("status", "")).upper() == "CAPPED":
        _capg = _lg.get("capped_grade", grade)
        _raws = _lg.get("raw_score")
        _reason = _lg.get("reason", "")
        if lang == "en":
            _lg_txt = (f"⚠ LANGUAGE GATE — Raw score {_raws}/100 · "
                       f"capped to Grade {_capg}. Target = EN "
                       f"(screen selection). Reason: {_reason} "
                       f"({_lg.get('where','')}).")
        else:
            _tgt = str(_lg.get("target_lang") or lang or "fr").upper()
            _lg_txt = (f"⚠ LANGUAGE GATE — Score brut {_raws}/100 · "
                       f"plafonné en Grade {_capg}. Cible = {_tgt} "
                       f"(sélection écran, contrat UI-1). Raison : {_reason} "
                       f"({_lg.get('where','')}).")
        lg_para = doc.add_paragraph()
        lg_run = lg_para.add_run(_lg_txt)
        lg_run.bold = True
        lg_run.font.size = Pt(9)
        lg_run.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
        # B.1.3.6 — FIDELITY GATE : cap visible (même mécanique que le gate langue).
        _fg = confidence_score.get("fidelity_gate") if isinstance(confidence_score, dict) else None
        if isinstance(_fg, dict) and _fg.get("triggered"):
            if lang == "en":
                _fg_txt = ("⚠ FIDELITY GATE — raw "
                           f"{_fg.get('raw_score')}/100 · capped to Grade "
                           f"{_fg.get('capped_grade')}. Reason: {_fg.get('reason')}")
            else:
                _fg_txt = ("⚠ FIDELITY GATE — brut "
                           f"{_fg.get('raw_score')}/100 · plafonné en Grade "
                           f"{_fg.get('capped_grade')}. Raison : {_fg.get('reason')}")
            _fg_para = doc.add_paragraph()
            _fg_run = _fg_para.add_run(_fg_txt)
            _fg_run.bold = True
            _fg_run.font.size = Pt(9)
            _fg_run.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
        _samples = _lg.get("samples") or []
        if _samples:
            sp = doc.add_paragraph()
            sp_run = sp.add_run(
                ("Samples: " if lang == "en" else "Échantillons : ")
                + " · ".join(str(x)[:48] for x in _samples[:4]))
            sp_run.italic = True
            sp_run.font.size = Pt(8)
            sp_run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
    trend_para = doc.add_paragraph()
    tr_run = trend_para.add_run(_trend_label(confidence_score, lang))
    tr_run.italic = True
    tr_run.font.size = Pt(9)

    # v62.3 — second indicator, independent from the proof score.
    _du = _decision_usefulness(confidence_score)
    if _du:
        _du_score = _du.get("score", "?")
        _du_band = str(_du.get("band", "?")).upper()
        du_para = doc.add_paragraph()
        du_run = du_para.add_run(
            _t("utility_line", lang).format(score=_du_score, band=_du_band))
        du_run.bold = True
        du_run.font.size = Pt(12)
        _ur, _ug, _ub = _grade_color_rgb(_du_band)
        du_run.font.color.rgb = RGBColor(_ur, _ug, _ub)
        if _du.get("label"):
            du_label_para = doc.add_paragraph()
            du_label_run = du_label_para.add_run(str(_du.get("label")))
            du_label_run.italic = True
            du_label_run.font.size = Pt(9)
        for _reason in list(_du.get("rationale") or [])[:2]:
            _rp = doc.add_paragraph(str(_reason), style="List Bullet")
            for _rr in _rp.runs:
                _rr.font.size = Pt(8)

    # Sous-scores — tableau compact 3×2
    cs = confidence_score.get("component_scores") or {}
    _fg_top = confidence_score.get("fidelity_gate") if isinstance(confidence_score, dict) else None
    _fg_triggered = isinstance(_fg_top, dict) and bool(_fg_top.get("triggered"))
    if cs:
        sub_title = doc.add_paragraph()
        st_run = sub_title.add_run(_t("subscores_title", lang))
        st_run.bold = True
        st_run.font.size = Pt(10)

        sub_table = doc.add_table(rows=2, cols=3)
        sub_table.style = "Table Grid"
        items = [
            (_t("sq", lang),   (
              (lambda _sig: (
                  (f"Signal richness: {_sig}/100\nEvidence: 0 page-confirmed — not exploitable\nSource quality for score: capped")
                  if lang == "en" else
                  (f"Richesse du signal : {_sig}/100\nPreuve : 0 confirmé page — non exploitable\nQualité source pour le score : plafonnée")
              ))(confidence_score.get("financial_signal_score", cs.get("source_quality", "?")))
              if _fg_triggered else
              cs.get("source_quality", "?"))),
            (_t("mix", lang),  cs.get("content_mix", "?")),
            (_t("cons", lang), cs.get("consistency", "?")),
            (_t("comp", lang), cs.get("completeness", "?")),
            (_t("stab", lang), cs.get("run_stability", "?")),
            (_t("sect", lang), cs.get("sector_confidence", "?")),
        ]
        for idx, (name, val) in enumerate(items):
            row_idx, col_idx = divmod(idx, 3)
            cell = sub_table.cell(row_idx, col_idx)
            cell.text = (f"{name}\n{val}" if (isinstance(val, str) and "\n" in val)
                         else f"{name}\n{val}/100")
            for para in cell.paragraphs:
                for run in para.runs:
                    run.font.size = Pt(9)

    # Why — 3-4 phrases explicatives
    why = confidence_score.get("confidence_explanation") or []
    if why:
        why_title = doc.add_paragraph()
        wy_run = why_title.add_run(_t("why_title", lang))
        wy_run.bold = True
        wy_run.font.size = Pt(10)
        for phrase in why[:4]:
            p = doc.add_paragraph(phrase, style="List Bullet")
            for run in p.runs:
                run.font.size = Pt(9)

    # Usage du document de travail. La doctrine v62.3 remplace les libellés
    # Client/Board par les deux usages réellement visés et interdit la remise
    # externe telle quelle. Le schéma historique reste disponible en fallback.
    usage_items = _work_product_usage_items(confidence_score, lang)
    if not usage_items:
        usage = confidence_score.get("usage_recommendation") or {}
        if usage:
            usage_items = [
                (_t("codir", lang),  _usage_label(usage.get("internal_codir", "?"), lang)),
                (_t("client", lang),
                 (("Blocked — regenerate first" if lang == "en"
                   else "Bloqué — régénérer d'abord")
                  if confidence_score.get("completion_flagged")
                  else _usage_label(usage.get("client_presentation", "?"), lang))),
                (_t("board", lang),  _usage_label(usage.get("board", "?"), lang)),
                (_t("public", lang), _usage_label(usage.get("public_external_use", "?"), lang)),
            ]
    if usage_items:
        u_title = doc.add_paragraph()
        ut_run = u_title.add_run(
            _t("work_usage_title", lang) if _decision_usefulness(confidence_score)
            else _t("usage_title", lang))
        ut_run.bold = True
        ut_run.font.size = Pt(10)
        usage_table = doc.add_table(rows=len(usage_items), cols=2)
        usage_table.style = "Table Grid"
        for idx, (name, val) in enumerate(usage_items):
            usage_table.cell(idx, 0).text = name
            usage_table.cell(idx, 1).text = val
            for c in (usage_table.cell(idx, 0), usage_table.cell(idx, 1)):
                for para in c.paragraphs:
                    for run in para.runs:
                        run.font.size = Pt(9)

    # Actions prioritaires — relatives au point d'agenda quand disponibles.
    _du_actions = _decision_usefulness(confidence_score).get("next_best_actions") or []
    actions = _du_actions or confidence_score.get("next_best_actions") or []
    if actions:
        a_title = doc.add_paragraph()
        at_run = a_title.add_run(_t("actions_title", lang))
        at_run.bold = True
        at_run.font.size = Pt(10)
        for act in actions[:3]:
            p = doc.add_paragraph(act, style="List Number")
            for run in p.runs:
                run.font.size = Pt(9)

    # Note méthodologique discrète.
    note = doc.add_paragraph()
    _dual_note = (("Two independent indicators: evidence sufficiency and decision usefulness. "
                   "Neither authorises external distribution as-is.") if lang == "en" else
                  ("Deux indicateurs indépendants : solidité probatoire et utilité décisionnelle. "
                   "Aucun n’autorise une diffusion externe telle quelle."))
    n_run = note.add_run(_dual_note if _decision_usefulness(confidence_score)
                         else _t("basic_mode_note", lang))
    n_run.italic = True
    n_run.font.size = Pt(7)
    n_run.font.color.rgb = RGBColor(127, 140, 141)

    doc.add_paragraph("")


# =============================================================================
# PPTX RENDER
# =============================================================================

def pptx_add_mode_slide(prs: Any,
                        briefcheck: Optional[dict],
                        lang: str = "fr") -> None:
    """
    v16.5.65 — Ajoute une slide dédiée "MODE DE BRIEFING" juste après la cover.

    Affichée UNIQUEMENT si mode ∈ {GENERIC, PARTIAL}. En FRAMED ou si briefcheck
    est absent/mal formé, no-op silencieux.

    Layout :
    - Pastille géante centrée avec le code mode (rouge/orange)
    - Liste des leviers manquants
    - Note plafond + rappel template de brief
    """
    if not (briefcheck and isinstance(briefcheck, dict)):
        return
    bm = briefcheck.get("brief_mode") or {}
    mode = str(bm.get("mode", "")).upper()
    if mode not in ("GENERIC", "PARTIAL"):
        return

    try:
        from pptx.util import Inches, Pt  # type: ignore
        from pptx.dml.color import RGBColor  # type: ignore
        from pptx.enum.text import PP_ALIGN, MSO_VERTICAL_ANCHOR  # type: ignore
        from pptx.enum.shapes import MSO_SHAPE  # type: ignore
    except Exception:
        return

    lang = lang if lang in ("fr", "en") else "fr"
    present = bm.get("present_count", 0)
    missing = bm.get("missing") or []
    score_cap = bm.get("score_cap", 0)

    # Couleur selon criticité
    if mode == "GENERIC":
        fill_rgb = RGBColor(203, 67, 53)       # rouge foncé
        accent_rgb = RGBColor(231, 76, 60)     # rouge accent
        title_txt = "🔴 " + _t("mode_generic_title", lang)
        subtitle_txt = ("Aucun contexte client détecté dans le brief"
                        if lang == "fr" else "No client context detected in the brief")
    else:  # PARTIAL
        fill_rgb = RGBColor(230, 126, 34)      # orange
        accent_rgb = RGBColor(243, 156, 18)    # orange accent
        title_txt = "🟡 " + _t("mode_partial_title", lang)
        subtitle_txt = (f"{present}/4 leviers renseignés — contexte partiel"
                        if lang == "fr" else f"{present}/4 levers provided — partial context")

    # Slide (layout blank)
    blank = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[-1]
    slide = prs.slides.add_slide(blank)

    # Fond très clair
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = RGBColor(250, 250, 250)

    def _tb(x, y, w, h, text, size=12, bold=False, italic=False,
            color=(33, 37, 41), align=None):
        tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = text
        if align is not None:
            p.alignment = align
        for run in p.runs:
            run.font.size = Pt(size)
            run.font.bold = bold
            run.font.italic = italic
            cr, cg, cb = color
            run.font.color.rgb = RGBColor(cr, cg, cb)
        return tb

    # v62 — géométrie native 10×5.625" avec voie de footer réservée.
    # L'ancienne version utilisait encore les coordonnées du canevas 7.5"
    # (disclaimer à y=6.2") ; le finalizer devait le clamper et créait alors
    # un chevauchement avec le renvoi CR.

    # Titre en grand bandeau coloré en haut
    header = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                     Inches(0), Inches(0),
                                     Inches(10), Inches(0.78))
    header.name = "HCRIT:mode:title"
    header.fill.solid()
    header.fill.fore_color.rgb = fill_rgb
    header.line.fill.background()
    htf = header.text_frame
    htf.margin_left = Inches(0.3)
    htf.margin_right = Inches(0.3)
    htf.word_wrap = True
    htf.paragraphs[0].alignment = PP_ALIGN.CENTER
    htf.paragraphs[0].text = title_txt
    for run in htf.paragraphs[0].runs:
        run.font.size = Pt(22)
        run.font.bold = True
        run.font.color.rgb = RGBColor(255, 255, 255)

    # Sous-titre
    _tb(0.4, 0.90, 9.2, 0.30, subtitle_txt,
        size=14, italic=True, color=(52, 73, 94), align=PP_ALIGN.CENTER)

    # Pastille plafond
    cap_pill = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                       Inches(3.5), Inches(1.32),
                                       Inches(3.0), Inches(0.56))
    cap_pill.name = "HCRIT:mode:score-cap"
    cap_pill.fill.solid()
    cap_pill.fill.fore_color.rgb = accent_rgb
    cap_pill.line.fill.background()
    cp_tf = cap_pill.text_frame
    cp_tf.word_wrap = True
    cp_tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    cp_tf.paragraphs[0].text = (f"Score plafonné à {score_cap}/100"
                                 if lang == "fr" else f"Score capped at {score_cap}/100")
    for run in cp_tf.paragraphs[0].runs:
        run.font.size = Pt(14)
        run.font.bold = True
        run.font.color.rgb = RGBColor(255, 255, 255)

    # Titre "leviers manquants"
    _tb(0.5, 2.08, 9.0, 0.30,
        _t("mode_missing_title", lang),
        size=13, bold=True, color=(33, 37, 41))

    # Liste des leviers manquants (chaque ligne = carte horizontale)
    for idx, miss in enumerate(missing[:4]):
        y = 2.47 + idx * 0.52
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                       Inches(0.5), Inches(y),
                                       Inches(9.0), Inches(0.42))
        # A missing-brief descriptor is informative, not an executive claim;
        # it may legitimately contain a semantic ellipsis such as
        # « CA, effectif, cash, marge… ».
        card.name = f"HINFO:mode:missing:{idx}"
        card.fill.solid()
        card.fill.fore_color.rgb = RGBColor(255, 255, 255)
        card.line.color.rgb = accent_rgb
        card.line.width = Pt(1)
        ctf = card.text_frame
        ctf.margin_left = Inches(0.2)
        ctf.margin_right = Inches(0.2)
        ctf.word_wrap = True
        ctf.paragraphs[0].text = f"•  {miss}"
        for run in ctf.paragraphs[0].runs:
            run.font.size = Pt(11)
            run.font.color.rgb = RGBColor(52, 73, 94)

    # Disclaimer en bas (plus fort pour GENERIC)
    if mode == "GENERIC":
        disclaimer = (
            "Le système a produit un livrable démonstratif sur un cas-type fictif. "
            "Aucune donnée de cette présentation ne doit être utilisée comme analyse réelle."
            if lang == "fr" else
            "The system produced a demonstrative deliverable on a fictional case. "
            "No data in this presentation should be used as actual analysis."
        )
    else:  # PARTIAL
        disclaimer = (
            "Livrable exploitable en CoDIR interne. "
            "À valider avant toute présentation externe."
            if lang == "fr" else
            "Usable in internal CoDIR. To validate before any external presentation."
        )
    disclaimer_box = _tb(0.5, 4.83, 9.0, 0.26, disclaimer,
                         size=9, italic=True, color=(127, 140, 141),
                         align=PP_ALIGN.CENTER)
    try:
        disclaimer_box.name = "HNOTE:mode:disclaimer"
    except Exception:
        pass


def pptx_add_confidence_slide(prs: Any,
                              confidence_score: Optional[dict],
                              briefcheck: Optional[dict],
                              lang: str = "fr",
                              insert_after_index: int = 0) -> None:
    """
    Ajoute une slide dédiée Confidence Score juste après la slide titre.

    La slide est insérée à l'index `insert_after_index + 1` dans la deck.
    Si aucun score, no-op.
    """
    if not (confidence_score and isinstance(confidence_score, dict)):
        return
    try:
        from pptx.util import Inches, Pt  # type: ignore
        from pptx.dml.color import RGBColor  # type: ignore
        from pptx.enum.text import PP_ALIGN, MSO_VERTICAL_ANCHOR  # type: ignore
        from pptx.enum.shapes import MSO_SHAPE  # type: ignore
    except Exception:
        return

    lang = lang if lang in ("fr", "en") else "fr"
    score = confidence_score.get("score", "?")
    grade = str(confidence_score.get("grade", "?")).upper()
    label = confidence_score.get("label", "")
    cs = confidence_score.get("component_scores") or {}
    _signal_metric = confidence_score.get("financial_signal_score", cs.get("source_quality", "?"))
    r, g, b = _grade_color_rgb(grade)

    # Ajouter une slide (layout blank = index 6 comme dans le reste du deck)
    blank = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[-1]
    slide = prs.slides.add_slide(blank)

    # Fond clair
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = RGBColor(248, 249, 250)

    def _tb(x, y, w, h, text, size=12, bold=False, italic=False,
            color=(33, 37, 41), align=None):
        tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = text
        if align is not None:
            p.alignment = align
        for run in p.runs:
            run.font.size = Pt(size)
            run.font.bold = bold
            run.font.italic = italic
            cr, cg, cb = color
            run.font.color.rgb = RGBColor(cr, cg, cb)
        return tb

    # v62 — layout 10×5.625" natif. Toute la matière se termine à y=5.10",
    # avant la voie de footer/renvoi CR à y=5.32". La v61 plaçait le bandeau
    # Fidelity PAR-DESSUS les cartes et transformait la carte « Qualité des
    # sources » en bloc narratif 4 lignes, d'où la collision visible slide 20.

    # Titre
    _du = _decision_usefulness(confidence_score)
    _title = (_t("score_title", lang) + (" & " + _t("utility_title", lang) if _du else ""))
    title_box = _tb(0.4, 0.20, 9.2, 0.42, _title,
                    size=18, bold=True, color=(33, 37, 41))
    title_box.name = "HCRIT:confidence:title"

    # Pastille score/grade
    pill = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                   Inches(0.4), Inches(0.72),
                                   Inches(3.1), Inches(1.38))
    pill.name = "HCRIT:confidence:score"
    pill.fill.solid()
    pill.fill.fore_color.rgb = RGBColor(r, g, b)
    pill.line.fill.background()
    pill_tf = pill.text_frame
    pill_tf.word_wrap = True
    pill_tf.vertical_anchor = MSO_VERTICAL_ANCHOR.MIDDLE
    pill_tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    pill_tf.paragraphs[0].text = f"{score}/100"
    for run in pill_tf.paragraphs[0].runs:
        run.font.size = Pt(38)
        run.font.bold = True
        run.font.color.rgb = RGBColor(255, 255, 255)
    pp = pill_tf.add_paragraph()
    pp.alignment = PP_ALIGN.CENTER
    pp.text = f"Grade {grade}"
    for run in pp.runs:
        run.font.size = Pt(16)
        run.font.bold = True
        run.font.color.rgb = RGBColor(255, 255, 255)

    # v62.3 — utilité décisionnelle séparée du score de preuve.
    if _du:
        _du_score = _du.get("score", "?")
        _du_band = str(_du.get("band", "?")).upper()
        _dr, _dg, _db = _grade_color_rgb(_du_band)
        utility_title = _tb(3.85, 0.76, 2.25, 0.25, _t("utility_title", lang),
                            size=11, bold=True, color=(52, 73, 94))
        utility_title.name = "HCRIT:confidence:utility-title"
        utility_score = _tb(3.85, 1.02, 1.45, 0.42, f"{_du_score}/100",
                            size=24, bold=True, color=(_dr, _dg, _db))
        utility_score.name = "HCRIT:confidence:utility-score"
        utility_label = _tb(5.25, 0.94, 4.35, 0.58, str(_du.get("label", "")),
                            size=11, italic=True, color=(52, 73, 94))
        utility_label.name = "HCRIT:confidence:utility-label"
        evidence_label = _tb(3.85, 1.48, 5.75, 0.18,
                             (("Evidence: " if lang == "en" else "Preuve : ") + str(label or "")),
                             size=9, italic=True, color=(127, 140, 141))
        evidence_label.name = "HINFO:confidence:evidence-label"
    else:
        if label:
            label_box = _tb(3.85, 0.82, 5.75, 0.50, label, size=13,
                            italic=True, color=(52, 73, 94))
            label_box.name = "HCRIT:confidence:label"
        trend_box = _tb(3.85, 1.40, 5.75, 0.25,
                        _trend_label(confidence_score, lang),
                        size=10, italic=True, color=(127, 140, 141))
        trend_box.name = "HINFO:confidence:trend"

    # Les avertissements sont rassemblés dans une bande bornée au lieu de
    # trois boîtes fixes susceptibles de se chevaucher avec les cartes.
    gate_lines = []
    if confidence_score.get("run_not_validatable"):
        _reasons = confidence_score.get("run_block_reasons") or []
        _band = (("⛔ RUN TO CLARIFY — client presentation, board and external "
                  "distribution BLOCKED") if lang == "en" else
                 ("⛔ RUN À CLARIFIER — présentation client, conseil et "
                  "diffusion externe BLOQUÉS"))
        if _reasons:
            _band += " — " + " ; ".join(str(r) for r in _reasons[:2])
        # B.1.3.56 (scope B) — écho deck du verdict mission : statut unique
        # affiché avec le bandeau de blocage (même canal, jamais un 2e bandeau).
        _ms56 = str(confidence_score.get("mission_status", "") or "").strip()
        if _ms56 and _ms56 != "MISSION-GRADE":
            _band = ((f"⛔ {_ms56} — " if lang != "en" else f"⛔ {_ms56} — ")
                     + _band.lstrip("⛔ "))
        gate_lines.append(_band)

    # M.5.10.4 — Language Gate : bandeau d'avertissement VISIBLE sur la slide.
    _lg = confidence_score.get("language_gate")
    if isinstance(_lg, dict) and str(_lg.get("status", "")).upper() == "CAPPED":
        _capg = _lg.get("capped_grade", grade)
        _raws = _lg.get("raw_score")
        if lang == "en":
            _lg_band = (f"⚠ LANGUAGE GATE — raw {_raws}/100 → capped to Grade "
                        f"{_capg}. Target = EN (screen selection): English "
                        f"output contains French content "
                        f"({_lg.get('where','')}).")
        else:
            _tgt2 = str(_lg.get("target_lang") or lang or "fr").upper()
            _lg_band = (f"⚠ LANGUAGE GATE — brut {_raws}/100 → plafonné en Grade "
                        f"{_capg}. Cible = {_tgt2} (sélection écran) : résidus "
                        f"hors langue cible ({_lg.get('where','')}).")
        gate_lines.append(_lg_band)
    _fgd = confidence_score.get("fidelity_gate") if isinstance(confidence_score, dict) else None
    _fg_triggered = isinstance(_fgd, dict) and bool(_fgd.get("triggered"))
    _evidence_summary = ""
    if _fg_triggered:
        _evidence_summary = (
            (f"Signal richness: {_signal_metric}/100 · Evidence: 0 page-confirmed — not exploitable · "
             f"Source quality for score: capped")
            if lang == "en" else
            (f"Richesse du signal : {_signal_metric}/100 · Preuve : 0 confirmé page — non exploitable · "
             f"Qualité source pour le score : plafonnée")
        )
        if lang == "en":
            _fg_band = (f"⚠ FIDELITY GATE — {_fgd.get('n_pj_facts')} attachment "
                        f"fact(s), 0 page-confirmed → Grade "
                        f"{_fgd.get('capped_grade')}")
        else:
            _fg_band = (f"⚠ FIDELITY GATE — {_fgd.get('n_pj_facts')} fait(s) PJ, "
                        f"0 confirmé page → Grade {_fgd.get('capped_grade')}")
        gate_lines.append(_fg_band)

    if gate_lines:
        gate_box = _tb(3.85, 1.68, 5.75, 0.54,
                       "\n".join(str(x) for x in gate_lines[:3]),
                       size=11, bold=True, color=(192, 0, 0))
        gate_box.name = "HCRIT:confidence:gates"

    # Sous-scores — 6 mini-cartes. La valeur reste TOUJOURS scalaire : le
    # diagnostic de preuve détaillé vit dans le bandeau Fidelity ci-dessus.
    subs = [
        (_t("sq", lang),   cs.get("source_quality", _signal_metric)),
        (_t("mix", lang),  cs.get("content_mix", "?")),
        (_t("cons", lang), cs.get("consistency", "?")),
        (_t("comp", lang), cs.get("completeness", "?")),
        (_t("stab", lang), cs.get("run_stability", "?")),
        (_t("sect", lang), cs.get("sector_confidence", "?")),
    ]
    card_w, card_h = 1.45, 0.82
    for idx, (name, val) in enumerate(subs):
        col = idx % 6
        card_x = 0.4 + col * (card_w + 0.05)
        card_y = 2.48
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                        Inches(card_x), Inches(card_y),
                                        Inches(card_w), Inches(card_h))
        card.name = f"HCRIT:confidence:card:{idx}"
        # couleur selon valeur
        try:
            val_int = int(val)
        except (TypeError, ValueError):
            val_int = 50
        if val_int >= 70:
            fill = (82, 190, 128)
        elif val_int >= 50:
            fill = (244, 208, 63)
        else:
            fill = (230, 126, 34)
        card.fill.solid()
        card.fill.fore_color.rgb = RGBColor(*fill)
        card.line.fill.background()
        ctf = card.text_frame
        ctf.word_wrap = True
        ctf.margin_left = ctf.margin_right = Inches(0.08)
        ctf.margin_top = ctf.margin_bottom = Inches(0.04)
        ctf.vertical_anchor = MSO_VERTICAL_ANCHOR.MIDDLE
        ctf.paragraphs[0].alignment = PP_ALIGN.CENTER
        ctf.paragraphs[0].text = str(name)
        for run in ctf.paragraphs[0].runs:
            run.font.size = Pt(11)
            run.font.bold = True
            run.font.color.rgb = RGBColor(255, 255, 255)
        vp = ctf.add_paragraph()
        vp.alignment = PP_ALIGN.CENTER
        vp.text = f"{val}/100"
        for run in vp.runs:
            run.font.size = Pt(14)
            run.font.bold = True
            run.font.color.rgb = RGBColor(255, 255, 255)

    # The fidelity explanation remains visible, but in its own one-line lane
    # instead of being squeezed into the first mini-card (the v61 collision).
    if _evidence_summary:
        evidence_box = _tb(0.4, 3.31, 9.2, 0.19, _evidence_summary,
                           size=9, italic=True, color=(88, 96, 112),
                           align=PP_ALIGN.CENTER)
        evidence_box.name = "HINFO:confidence:evidence-summary"
        evidence_box.text_frame.margin_left = evidence_box.text_frame.margin_right = Inches(0.02)
        evidence_box.text_frame.margin_top = evidence_box.text_frame.margin_bottom = 0

    # Usage réel du document de travail + actions relatives à l'agenda.
    u_items = _work_product_usage_items(confidence_score, lang)
    if not u_items:
        usage = confidence_score.get("usage_recommendation") or {}
        if usage:
            u_items = [
                (_t("codir", lang),  _usage_label(usage.get("internal_codir", "?"), lang)),
                (_t("client", lang),
                 (("Blocked — regenerate first" if lang == "en"
                   else "Bloqué — régénérer d'abord")
                  if confidence_score.get("completion_flagged")
                  else _usage_label(usage.get("client_presentation", "?"), lang))),
                (_t("board", lang),  _usage_label(usage.get("board", "?"), lang)),
                (_t("public", lang), _usage_label(usage.get("public_external_use", "?"), lang)),
            ]
    if u_items:
        usage_title = _tb(0.4, 3.52, 4.7, 0.25,
                          _t("work_usage_title", lang) if _du else _t("usage_title", lang),
                          size=12, bold=True, color=(33, 37, 41))
        usage_title.name = "HCRIT:confidence:usage-title"
        # Short labels in the slide; the complete doctrine is available in CR.
        _short = []
        for _name, _value in u_items:
            _v = str(_value)
            _v = _v.replace("Non destiné à être remis tel quel au client final", "Non prévu")
            _v = _v.replace("Aucune diffusion externe telle quelle", "Non")
            _v = _v.replace("Not intended as a final client deliverable", "Not intended")
            _v = _v.replace("No external distribution as-is", "No")
            _short.append((_name, _v))
        u_text = "\n".join(f"• {n} : {v}" for n, v in _short)
        usage_body = _tb(0.4, 3.82, 4.7, 1.28, u_text,
                         size=11, color=(52, 73, 94))
        usage_body.name = "HCRIT:confidence:usage"

    actions = (_du.get("next_best_actions") or []) if _du else []
    actions = actions or confidence_score.get("next_best_actions") or []
    if actions:
        actions_title = _tb(5.2, 3.52, 4.4, 0.25,
                            _t("actions_title", lang),
                            size=12, bold=True, color=(33, 37, 41))
        actions_title.name = "HCRIT:confidence:actions-title"
        act_text = "\n".join(f"{i+1}. {a}" for i, a in enumerate(actions[:3]))
        actions_body = _tb(5.2, 3.82, 4.4, 1.28, act_text,
                           size=11, color=(52, 73, 94))
        actions_body.name = "HCRIT:confidence:actions"


# =============================================================================
# UI HEALTH CHECK (pour app.py self-check au démarrage)
# =============================================================================

def quick_health_check() -> dict:
    """
    Vérifie rapidement que les patches sont actifs. Retourne un dict :
    {
        'all_ok': bool,
        'flags': {'briefcheck': bool, 'confidence': bool},
        'imports': {'briefcheck': bool, 'confidence_scorer': bool},
        'errors': list[str],
        'warnings': list[str],
    }
    Utilisé par app.py pour afficher un bandeau au démarrage de Streamlit.
    """
    import os
    result = {
        "all_ok": True,
        "flags": {},
        "imports": {},
        "errors": [],
        "warnings": [],
    }

    # Flags
    bc_flag = os.getenv("CODIR_USE_BRIEFCHECK", "1").lower() in ("1", "true", "yes", "on")
    cs_flag = os.getenv("CODIR_USE_CONFIDENCE", "1").lower() in ("1", "true", "yes", "on")
    result["flags"]["briefcheck"] = bc_flag
    result["flags"]["confidence"] = cs_flag
    if not bc_flag:
        result["warnings"].append("CODIR_USE_BRIEFCHECK=0 — bandeau briefcheck désactivé.")
    if not cs_flag:
        result["warnings"].append("CODIR_USE_CONFIDENCE=0 — score de confiance désactivé.")

    # Imports
    try:
        from patches.briefcheck import run_briefcheck  # noqa
        result["imports"]["briefcheck"] = bool(run_briefcheck)
    except Exception as e:
        result["imports"]["briefcheck"] = False
        result["errors"].append(f"Import patches.briefcheck échoué : {type(e).__name__}: {e}")
        result["all_ok"] = False

    try:
        from patches.confidence_scorer import compute_delivery_confidence_score  # noqa
        result["imports"]["confidence_scorer"] = bool(compute_delivery_confidence_score)
    except Exception as e:
        result["imports"]["confidence_scorer"] = False
        result["errors"].append(f"Import patches.confidence_scorer échoué : {type(e).__name__}: {e}")
        result["all_ok"] = False

    return result


__all__ = [
    "docx_add_confidence_block",
    "pptx_add_confidence_slide",
    "pptx_add_mode_slide",             # v16.5.65
    "pptx_add_philosophy_slide",       # v16.5.67 L1
    "enrich_pptx_bytes_with_confidence",
    "quick_health_check",
]


def pptx_add_philosophy_slide(prs: Any, lang: str = "fr") -> None:
    """
    v16.5.67 — L1 Slide Philosophie insérée juste après la cover.

    Contenu : bandeau "CoDIR-IA n'est pas un décideur" + rappel philosophie
    + vocabulaire Lucidité (RECOMMANDÉ / À ARBITRER / À INVESTIGUER).

    Idempotent : si une slide avec le même titre existe déjà, ne rien faire.
    """
    try:
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN
    except Exception:
        return

    title_fr = "🎯 CoDIR-IA — Accélérateur de lucidité"
    title_en = "🎯 CoDIR-IA — Lucidity Accelerator"
    title = title_fr if lang != "en" else title_en

    # Idempotence : ne pas ré-ajouter si déjà présente
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame and title in shape.text_frame.text:
                return

    slide_layout = prs.slide_layouts[6]  # blank
    slide = prs.slides.add_slide(slide_layout)

    # Background doux
    try:
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor(0xF7, 0xF9, 0xFC)
    except Exception:
        pass

    # Géométrie RELATIVE au canevas réel (fix chantier H, 10/08/2026).
    # Les littéraux historiques (0.5 / 12.33 / 5.8 pouces) supposaient un
    # canevas 13,33×7,5″ alors que le deck est construit en 10×5,625″ :
    # 7,19 cm hors-cadre à droite et bandeau vocabulaire SOUS le bord bas.
    # Les proportions du dessin d'origine sont conservées, exprimées en
    # fractions du canevas — plus jamais de littéraux absolus ici.
    _sw, _sh = int(prs.slide_width), int(prs.slide_height)
    _margin = int(_sw * 0.0375)          # = 0.5″ sur le canevas 13,33″ d'origine
    _w = _sw - 2 * _margin

    def _y(frac: float) -> int:
        return int(_sh * frac)

    # Titre  (dessin d'origine : top 0.5″, h 1.0″ sur 7,5″ de haut)
    left, top, width, height = _margin, _y(0.5 / 7.5), _w, _y(1.0 / 7.5)
    title_box = slide.shapes.add_textbox(left, top, width, height)
    tf = title_box.text_frame
    tf.margin_left = Inches(0.1)
    tf.margin_top = Inches(0.1)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    run = p.add_run()
    run.text = title
    run.font.size = Pt(28)
    run.font.bold = True
    run.font.color.rgb = RGBColor(0x2E, 0x4A, 0x7F)

    # Corps principal
    body_text_fr = (
        "CoDIR-IA n'est PAS un décideur.\n"
        "\n"
        "Il structure votre réflexion stratégique, produit des hypothèses qualifiées,\n"
        "rend visibles vos zones de doute, et propose des arbitrages à examiner.\n"
        "\n"
        "La décision reste humaine, responsable, contextualisée.\n"
        "Vous êtes le filtre."
    )
    body_text_en = (
        "CoDIR-IA is NOT a decision-maker.\n"
        "\n"
        "It structures your strategic thinking, produces qualified hypotheses,\n"
        "makes your zones of doubt visible, and proposes arbitrations to examine.\n"
        "\n"
        "The decision remains human, accountable, contextualized.\n"
        "You are the filter."
    )
    body_text = body_text_fr if lang != "en" else body_text_en

    left, top, width, height = _margin, _y(1.7 / 7.5), _w, _y(3.5 / 7.5)
    body_box = slide.shapes.add_textbox(left, top, width, height)
    tf = body_box.text_frame
    tf.word_wrap = True
    for i, line in enumerate(body_text.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        run = p.add_run()
        run.text = line
        run.font.size = Pt(18)
        run.font.color.rgb = RGBColor(0x2C, 0x3E, 0x50)
        if "PAS un décideur" in line or "NOT a decision-maker" in line:
            run.font.bold = True
            run.font.color.rgb = RGBColor(0xC0, 0x39, 0x2B)
        if "Vous êtes le filtre" in line or "You are the filter" in line:
            run.font.bold = True
            run.font.color.rgb = RGBColor(0x2E, 0x4A, 0x7F)

    # Bandeau vocabulaire en bas
    vocab_fr = (
        "Vocabulaire CoDIR-IA : RECOMMANDÉ · À ARBITRER · À INVESTIGUER · À VÉRIFIER\n"
        "CoDIR-IA ne présente pas ses orientations comme des décisions humaines prises."
    )
    vocab_en = (
        "CoDIR-IA vocabulary: RECOMMENDED · TO BE ARBITRATED · TO INVESTIGATE · TO VERIFY\n"
        "CoDIR-IA does not present orientations as final human decisions."
    )
    vocab = vocab_fr if lang != "en" else vocab_en

    left, top, width, height = _margin, _y(5.8 / 7.5), _w, _y(1.2 / 7.5)
    vocab_box = slide.shapes.add_textbox(left, top, width, height)
    tf = vocab_box.text_frame
    tf.word_wrap = True
    for i, line in enumerate(vocab.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        run = p.add_run()
        run.text = line
        run.font.size = Pt(12)
        run.font.italic = True
        run.font.color.rgb = RGBColor(0x55, 0x55, 0x55) if i == 1 else RGBColor(0x2E, 0x4A, 0x7F)


def enrich_pptx_bytes_with_confidence(pptx_bytes: bytes,
                                       confidence_score: Optional[dict],
                                       briefcheck: Optional[dict],
                                       lang: str = "fr",
                                       run_blocked: bool = False,
                                       run_block_reasons: Optional[list] = None,
                                       deck_mode: str = "strict") -> bytes:
    """Enrich a deck with the confidence surface required by its delivery mode.

    ``working`` adds only the final evidence/usefulness slide so the oral deck
    stays within the 8-15-slide product envelope. ``strict`` keeps the historical
    philosophy + briefing-mode + confidence sequence for internal QA. On any
    enrichment error, the original bytes are returned unchanged.
    """
    if not pptx_bytes:
        return pptx_bytes
    has_any = (confidence_score and isinstance(confidence_score, dict)) or \
              (briefcheck and isinstance(briefcheck, dict))
    if not has_any:
        return pptx_bytes
    try:
        from io import BytesIO
        from pptx import Presentation  # type: ignore
        prs = Presentation(BytesIO(pptx_bytes))
        confidence_score = apply_run_clarification_to_confidence(
            confidence_score, lang, run_blocked, run_block_reasons)
        _deck_mode = str(deck_mode or "strict").strip().lower()
        if _deck_mode not in {"working", "strict"}:
            _deck_mode = "working"
        if _deck_mode == "strict":
            # QA/full deck : les slides doctrine et mode restent disponibles.
            pptx_add_philosophy_slide(prs, lang=lang)
            pptx_add_mode_slide(prs, briefcheck, lang=lang)
        # Working Deck : le cadre de prudence existe déjà dans le corps du deck ;
        # seule la conclusion Confidence est ajoutée afin de rester dans 8-15 slides.
        if confidence_score and isinstance(confidence_score, dict):
            pptx_add_confidence_slide(prs, confidence_score, briefcheck, lang=lang)
        out = BytesIO()
        prs.save(out)
        return out.getvalue()
    except Exception as e:
        import logging
        logging.getLogger("codir_ia").warning(
            f"enrich_pptx_bytes_with_confidence failed: {type(e).__name__}: {e}"
        )
        return pptx_bytes



def restamp_docx_score(docx_bytes, confidence_score, lang="fr"):
    """v62.13.9.4.40 — réaligne la ligne « Score : N/100 — Grade X » d'un Word déjà écrit sur
    le score et le grade FINAUX de la session ; le reste du document est inchangé."""
    import io
    import re as _re
    try:
        from docx import Document
        score = (confidence_score or {}).get("score")
        grade = str((confidence_score or {}).get("grade") or "").upper()
        if score is None or not grade:
            return docx_bytes
        doc = Document(io.BytesIO(docx_bytes))
        rx = _re.compile(r"(Score\s*:?\s*)\d{1,3}(/100\s*[—–-]\s*Grade\s+)[A-E]")
        changed = False
        for para in doc.paragraphs:
            if rx.search(para.text):
                for run in para.runs:
                    new = rx.sub(lambda m: f"{m.group(1)}{score}{m.group(2)}{grade}", run.text)
                    if new != run.text:
                        run.text, changed = new, True
        if not changed:
            return docx_bytes
        out = io.BytesIO(); doc.save(out)
        return out.getvalue()
    except Exception:
        return docx_bytes
