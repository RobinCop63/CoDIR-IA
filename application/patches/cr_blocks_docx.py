"""v17.1.0-B2.3-F.3 — Rendu DOCX du registre d'actions + ledger marché.

Sorti dans un module dédié (sans dépendance aux SDK providers) pour être
TESTABLE hors-ligne et garder app.py mince. Fail-open : aucune exception ne
remonte ; si les artefacts sont absents, ne rend rien et renvoie 0.

Consomme directement les structures exposées par le moteur :
  result["agenda_register"]  : list[dict] (sujet/action/porteur/échéance/statut/prochaine_revue)
  result["web_facts_ledger"] : list[dict] (metric/valeur_*/annee/source_url/fiabilite/board_safe)
"""
from __future__ import annotations

from typing import Any, Dict


def _gate_echeance(value, lang: str = "fr", run_date=None):
    """M6-A0.2 (A3) + Gate 12 — flague une échéance d'action déjà passée à la
    date d'AUTORITÉ fournie. Sans autorité (None) : texte nu, AUCUN statut
    fabriqué — le sentinel « horloge système par défaut » est supprimé
    (aucune horloge sur un chemin de vérité)."""
    try:
        if run_date is None:
            return str(value if value not in (None, "") else "—")
        from patches.temporal_gate import flag_past_action_deadline
        txt, _ = flag_past_action_deadline(str(value if value not in (None, "") else "—"),
                                           run_date, lang)
        return txt
    except Exception:
        return str(value if value not in (None, "") else "—")


def _result_run_date(result):
    """Date d'autorité temporelle pour les renderers DOCX/PPTX.

    Le produit distingue deux dates :

    * la date réelle d'exécution (``run_date``), utile pour la traçabilité ;
    * la date d'analyse demandée par l'utilisateur (``analysis_as_of_date`` /
      ``temporal_frame.scenario_date``), qui gouverne les échéances lorsqu'une
      analyse rétrospective ou simulée est explicitement demandée.

    La date d'analyse prime donc toujours sur la date d'exécution. Sans date
    structurée, le renderer ne lit jamais l'horloge système et ne fabrique aucun
    statut « en retard ».
    """
    from datetime import date as _d

    def _parse(raw):
        if raw in (None, ""):
            return None
        try:
            return _d.fromisoformat(str(raw)[:10])
        except Exception:
            return None

    if not isinstance(result, dict):
        return None

    # 1) Contrat racine explicite — à privilégier pour les intégrations futures.
    for key in ("temporal_authority_date", "analysis_date", "analysis_as_of_date"):
        parsed = _parse(result.get(key))
        if parsed is not None:
            return parsed

    # 2) Cadre temporel M6-A3 : un scénario explicite gouverne les livrables.
    # Gate 13 — autorité INVALID/ERROR au contrat racine : AUCUNE autorité
    # de rendu, jamais un repli sur la date réelle (niveau 4). C'était le
    # trou P0-2 : la racine bloquait, le renderer flaguait quand même.
    _ta13 = result.get("temporal_authority")
    if isinstance(_ta13, dict) and             _ta13.get("scenario_status") in ("INVALID", "ERROR"):
        return None
    if result.get("temporal_authority_error"):
        return None
    frame = result.get("temporal_frame") or {}
    if isinstance(frame, dict):
        scenario = _parse(frame.get("scenario_date"))
        if scenario is not None and (frame.get("has_scenario") is not False):
            return scenario
        # Gate 11, intégration Claude — un scénario DEMANDÉ mais illisible ne
        # retombe jamais sur la date réelle d'exécution : ce repli recréerait
        # exactement les « deux vérités temporelles » que ce gate ferme. Sans
        # autorité lisible, aucun statut de retard n'est fabriqué.
        if frame.get("has_scenario") is True and scenario is None                 and frame.get("scenario_date") not in (None, ""):
            return None

    # 3) Diagnostic mission_governance — repli structurel si le cadre n'a pas
    #    été construit (profil/registre indisponible, ancien résultat, etc.).
    for row in result.get("diagnostics_attempts") or []:
        if not isinstance(row, dict) or row.get("role") != "mission_governance":
            continue
        parsed = _parse(row.get("analysis_as_of_date"))
        if parsed is not None:
            return parsed

    # 4) Date réelle du run — uniquement en l'absence de scénario d'analyse.
    for key in ("run_date", "date_run"):
        parsed = _parse(result.get(key))
        if parsed is not None:
            return parsed
    if isinstance(frame, dict):
        parsed = _parse(frame.get("run_as_of_date"))
        if parsed is not None:
            return parsed
    for row in result.get("diagnostics_attempts") or []:
        if not isinstance(row, dict) or row.get("role") != "run_context":
            continue
        parsed = _parse(row.get("run_date"))
        if parsed is not None:
            return parsed
    return None


def _govern_action_rows(rows, lang: str = "fr"):
    """Applique le garde au point de rendu avec un repli fail-closed."""
    try:
        from patches.codir_register_history import govern_action_status_row
        for row in (rows or []):
            govern_action_status_row(row, lang=lang)
    except Exception:
        done = {"fait", "done", "closed", "completed", "terminé", "termine"}
        for row in (rows or []):
            if isinstance(row, dict) and str(row.get("statut", "") or "").strip().lower() in done:
                row["statut"] = "To start" if lang == "en" else "À lancer"
                row["statut_conflict"] = "ACTION_STATUS_GUARD_FAILURE"
    return rows


def _status_display(row, lang: str = "fr") -> str:
    try:
        from patches.codir_register_history import action_status_display
        return action_status_display(row or {}, lang)
    except Exception:
        return str((row or {}).get("statut", "") or "—")


def _ledger_value(row: Dict[str, Any]) -> str:
    ce = row.get("valeur_centrale")
    lo, hi = row.get("valeur_basse"), row.get("valeur_haute")
    if ce is None:
        return "—"
    if lo != hi:
        return f"{lo}–{hi} (centr. {ce})"
    return f"{ce}"


def render_register_and_ledger(doc, result: Dict[str, Any], lang: str = "fr") -> int:
    """Ajoute au document Word un tableau « Registre d'actions » et un tableau
    « Faits marché (sourcés) » s'ils existent. Renvoie le nombre de tableaux
    ajoutés (0, 1 ou 2). Fail-open."""
    # Garde partagée appliquée AU RENDERER : des rows brutes peuvent arriver
    # ici sans passer par AgendaRegister.to_rows(). Le repli est fail-closed.
    _govern_action_rows(result.get("agenda_register") or [], lang)
    _run_date = _result_run_date(result)

    added = 0
    try:
        reg = result.get("agenda_register") or []
    except Exception:
        reg = []
    try:
        led = result.get("web_facts_ledger") or []
    except Exception:
        led = []

    # ── Registre d'actions ──────────────────────────────────────────────────
    if reg:
        try:
            doc.add_heading("Registre d'actions" if lang == "fr" else "Action register", level=1)
            cols = (["Sujet", "Action", "Porteur", "Échéance", "Statut", "Prochaine revue"]
                    if lang == "fr" else
                    ["Topic", "Action", "Owner", "Deadline", "Status", "Next review"])
            t = doc.add_table(rows=1, cols=len(cols))
            t.style = "Table Grid"
            for i, h in enumerate(cols):
                t.rows[0].cells[i].text = h
            for row in reg:
                c = t.add_row().cells
                c[0].text = str(row.get("sujet", "") or "—")
                c[1].text = str(row.get("action", "") or "—")
                c[2].text = str(row.get("porteur", "") or "—")
                c[3].text = _gate_echeance(row.get("echeance", ""), lang, _run_date)
                c[4].text = _status_display(row, lang)
                c[5].text = str(row.get("prochaine_revue", "") or "—")
            added += 1
        except Exception:
            pass

    # ── Faits marché (sourcés) ──────────────────────────────────────────────
    if led:
        try:
            doc.add_heading("Faits marché (sourcés)" if lang == "fr" else "Market facts (sourced)",
                            level=1)
            cols = (["Métrique", "Valeur", "Année", "Fiabilité", "Source"]      # v62.13.9.4.23 — compact
                    if lang == "fr" else
                    ["Metric", "Value", "Year", "Reliability", "Source"])
            t = doc.add_table(rows=1, cols=len(cols))
            t.style = "Table Grid"
            for i, h in enumerate(cols):
                t.rows[0].cells[i].text = h
            unsourced = "non sourcé" if lang == "fr" else "unsourced"
            for row in led:
                c = t.add_row().cells
                c[0].text = str(row.get("metric", "") or "—")
                c[1].text = _ledger_value(row)
                c[2].text = str(row.get("annee", "") or "—")
                c[3].text = str(row.get("fiabilite", "") or "—")
                _src = str(row.get("source_url", "") or "")
                import re as _re
                _dom = _re.sub(r"^https?://(?:www\.)?", "", _src).split("/")[0] if _src else ""
                c[4].text = (_dom or unsourced)
            added += 1
        except Exception:
            pass

    return added


def render_codir_history(doc, result: Dict[str, Any], lang: str = "fr") -> int:
    """Cycle C — Ajoute au CR Word la vue MULTI-SÉANCES si un historique de
    dossier existe : actions ouvertes (avec relances et statut « En retard »
    dérivé), frise CoDIR→CoDIR, et écarts de décision. Renvoie le nombre de
    blocs ajoutés. Fail-open."""
    added = 0
    try:
        ch = result.get("codir_history") or None
    except Exception:
        ch = None
    if not ch:
        return 0

    _run_date = _result_run_date(result)
    opens = ch.get("open_actions") or []
    # M.5.9 (FIX E1) — un séparateur « Axes conditionnels » ingéré par un run
    # antérieur (M.5.8) ne doit pas apparaître comme action ouverte dans le CR.
    def _is_sep_act(a):
        act = (a.get("action", "") or "").strip().lower()
        return (a.get("_separator") or a.get("_row_type") == "section_header"
                or act.startswith("axes conditionnels — hors plan principal")
                or act.startswith("conditional axes — out of the main plan"))
    opens = [a for a in opens if not _is_sep_act(a)]
    carried_in = [a for a in (ch.get("carried_in") or []) if not _is_sep_act(a)]
    _govern_action_rows(opens, lang)
    _govern_action_rows(carried_in, lang)
    timeline = ch.get("timeline") or []
    ecarts = ch.get("decision_ecarts") or []
    reapparues = ch.get("reapparues") or []  # clôturées réapparues → à arbitrer

    # ── À traiter dans ce CoDIR (issues du précédent) — feed-forward ─────────
    if carried_in:
        try:
            # 9.4.55 — contre-recette ChatGPT du 07/10 (M02) : ce tableau montre l'état REÇU en début de séance ; il affichait
            # « À lancer » des actions que tes déclarations de cette séance venaient de clore. Il est daté comme tel, et une
            # colonne donne l'état APRÈS la séance (registre courant).
            doc.add_heading(
                "À traiter dans ce CoDIR (issues du précédent)" if lang == "fr"
                else "To address in this CoDIR (carried from previous)", level=1)
            doc.add_paragraph(
                "État reçu en début de séance, avant les décisions de cette séance ; la dernière colonne donne l'état après la "
                "séance." if lang == "fr" else
                "State received at the start of the session, before this session's decisions; the last column gives the state "
                "after the session.")
            _now55 = {str(x.get("action_key") or ""): x for x in (ch.get("open_actions") or []) if isinstance(x, dict)}
            _m55 = {str(x.get("matched_key") or ""): x for x in (((result or {}).get("meta") or {}).get("brief_status_matches52")
                                                                   or []) if x.get("quality") == "certaine"}
            cols = (["Sujet", "Action", "Porteur", "Échéance", "Statut reçu", "Relances", "Après la séance"]
                    if lang == "fr" else
                    ["Topic", "Action", "Owner", "Deadline", "Status received", "Follow-ups", "After the session"])
            t = doc.add_table(rows=1, cols=len(cols))
            t.style = "Table Grid"
            for i, h in enumerate(cols):
                t.rows[0].cells[i].text = h
            for a in carried_in:
                c = t.add_row().cells
                c[0].text = str(a.get("sujet", "") or "—")
                c[1].text = str(a.get("action", "") or "—")
                c[2].text = str(a.get("porteur", "") or "—")
                c[3].text = _gate_echeance(a.get("echeance", ""), lang, _run_date)
                c[4].text = _status_display(a, lang)
                c[5].text = str(a.get("relance_count", 0))
                _k55 = str(a.get("action_key") or "")
                if _k55 in _m55:
                    _st55 = {"DONE": ("Réalisée (déclaration de cette séance)", "Completed (declared this session)"),
                             "DROPPED": ("Abandonnée (déclaration de cette séance)", "Dropped (declared this session)"),
                             "POSTPONED": ("Reportée (déclaration de cette séance)", "Postponed (declared this session)")}
                    c[6].text = _st55.get(_m55[_k55].get("status"), ("—", "—"))[0 if lang == "fr" else 1]
                elif _k55 in _now55:
                    c[6].text = _status_display(_now55[_k55], lang)
                else:
                    c[6].text = "Close" if lang == "fr" else "Closed"
            added += 1
        except Exception:
            pass

    # ── Actions ouvertes (multi-séances) ────────────────────────────────────
    if opens:
        try:
            doc.add_heading(
                "Suivi multi-séances — actions ouvertes" if lang == "fr"
                else "Multi-session tracking — open actions", level=1)
            cols = (["Sujet", "Action", "Porteur", "Échéance", "Statut",
                     "Relances", "Prochaine revue"] if lang == "fr" else
                    ["Topic", "Action", "Owner", "Deadline", "Status",
                     "Follow-ups", "Next review"])
            t = doc.add_table(rows=1, cols=len(cols))
            t.style = "Table Grid"
            for i, h in enumerate(cols):
                t.rows[0].cells[i].text = h
            for a in opens:
                c = t.add_row().cells
                c[0].text = str(a.get("sujet", "") or "—")
                c[1].text = str(a.get("action", "") or "—")
                c[2].text = str(a.get("porteur", "") or "—")
                c[3].text = _gate_echeance(a.get("echeance", ""), lang, _run_date)
                c[4].text = _status_display(a, lang)
                c[5].text = str(a.get("relance_count", 0))
                c[6].text = str(a.get("prochaine_revue", "") or "—")
            added += 1
        except Exception:
            pass

    # ── Historique CoDIR → CoDIR ────────────────────────────────────────────
    if timeline:
        try:
            doc.add_heading("Historique CoDIR → CoDIR" if lang == "fr"
                            else "CoDIR → CoDIR history", level=1)
            cols = (["Date", "Nouvelles", "Reconduites", "Relances", "Reportées",
                     "Clôturées"] if lang == "fr" else
                    ["Date", "New", "Carried", "Follow-ups", "Reported", "Closed"])
            t = doc.add_table(rows=1, cols=len(cols))
            t.style = "Table Grid"
            for i, h in enumerate(cols):
                t.rows[0].cells[i].text = h
            for r in timeline:
                c = t.add_row().cells
                c[0].text = str(r.get("run_date", "") or "—")
                c[1].text = str(r.get("created", 0))
                c[2].text = str(r.get("carried", 0))
                c[3].text = str(r.get("relance", 0))
                c[4].text = str(r.get("reported", 0))
                c[5].text = str(r.get("closed", 0))
            added += 1
        except Exception:
            pass


    # ── 9.4.53 — Statuts déclarés dans le brief et NON appliqués (contre-recette ChatGPT du 06/10, M03) ──
    # Calculés depuis la 9.4.52 mais restés dans le diagnostic : le consultant doit VOIR qu'un statut déclaré n'a pas été
    # appliqué (correspondance ambiguë ou action non retrouvée), et pourquoi.
    try:
        _m53 = list(((result or {}).get("meta") or {}).get("brief_status_matches52") or [])
        _bad53 = [x for x in _m53 if x.get("quality") in ("ambiguë", "non retrouvée")]
        if _bad53:
            doc.add_heading("Statuts déclarés dans le brief et NON appliqués" if lang == "fr"
                            else "Statuses declared in the brief and NOT applied", level=2)
            _w53 = {"DONE": ("réalisée", "completed"), "POSTPONED": ("reportée", "postponed"), "DROPPED": ("abandonnée", "dropped")}
            for x in _bad53:
                st = _w53.get(x.get("status"), (x.get("status"), x.get("status")))[0 if lang == "fr" else 1]
                if x.get("quality") == "ambiguë":
                    cand = " ; ".join(c for c in (x.get("candidates") or [])[:3] if c)
                    why = (f"correspondance ambiguë, plusieurs actions possibles ({cand}) — à préciser" if lang == "fr"
                           else f"ambiguous match, several actions fit ({cand}) — to be specified")
                else:
                    why = ("aucune action correspondante au registre — à vérifier" if lang == "fr"
                           else "no matching action in the register — to be checked")
                try:
                    doc.add_paragraph(f"« {x.get('action', '')} » → {st} : {why}", style="List Bullet")
                except Exception:
                    doc.add_paragraph(f"• « {x.get('action', '')} » → {st} : {why}")
            added += 1
    except Exception:
        pass

    # ── Écarts de décision (signal) ─────────────────────────────────────────
    if ecarts:
        try:
            doc.add_heading("Écarts de décision d'un CoDIR au suivant" if lang == "fr"
                            else "Decision changes across CoDIRs", level=2)
            for e in ecarts:
                doc.add_paragraph(
                    f"• {e.get('from','')} → {e.get('to','')}", style=None)
            added += 1
        except Exception:
            pass

    # ── Actions clôturées réapparues — À ARBITRER (pas de réouverture auto) ──
    if reapparues:
        try:
            doc.add_heading(
                "Actions clôturées réapparues — à arbitrer" if lang == "fr"
                else "Closed actions that reappeared — to arbitrate", level=2)
            doc.add_paragraph(
                "Ces actions avaient été clôturées et réapparaissent. Elles ne sont "
                "PAS rouvertes automatiquement : arbitrage humain requis."
                if lang == "fr" else
                "These actions were closed and reappeared. They are NOT reopened "
                "automatically: human arbitration required.", style=None)
            for a in reapparues:
                doc.add_paragraph(f"• {a.get('action','') or '—'}", style=None)
            added += 1
        except Exception:
            pass

    return added
