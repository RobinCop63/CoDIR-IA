"""Cycle C (F.5.2) — UI Streamlit de PILOTAGE des actions multi-séances.

Isolé dans un module dédié (et non inline dans app.py) pour : (1) limiter le
rayon de blast sur l'app, (2) permettre un import/syntax-check hors-ligne,
(3) garder la logique non-Streamlit testable. Streamlit est importé
PARESSEUSEMENT dans chaque fonction → le module s'importe sans Streamlit.

Deux surfaces :
  - render_dossier_label_field : champ « Libellé de dossier » (mode NORMAL de
    regroupement multi-séances), écrit dans settings.dossier_label avant le run ;
  - render_action_pilot_ui : tableau des actions ouvertes du dossier + contrôles
    clôturer / reporter / en cours / à arbitrer / rouvrir / note.

Aucune action destructive automatique : chaque opération est déclenchée par un
clic explicite (doctrine : pas de clôture ni de réouverture auto).

Toutes les fonctions sont FAIL-OPEN : toute erreur est avalée et n'interrompt
jamais le rendu de l'app.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict


def _refresh_history(result: Dict[str, Any], dossier_id: str, lang: str = "fr") -> None:
    """F.5.2.1 — après une opération de pilotage, reconstruit la vue depuis le
    stockage et met à jour result['codir_history'] EN PLACE (result étant l'objet
    de session), pour que le rerun affiche l'état à jour et non l'ancien. Fail-open."""
    try:
        import patches.codir_register_history as C
        # Gate 15 — le refresh UI conserve l'AUTORITÉ ANALYTIQUE du
        # résultat courant : un clic ne transforme jamais une vue
        # rétrospective 2023 en vue latest.
        _auth15 = None
        try:
            _a = (result.get("temporal_authority_date") or
                  result.get("analysis_date") or "")
            if _a:
                from datetime import date as _d15
                _auth15 = _d15.fromisoformat(str(_a)[:10])
        except Exception:
            _auth15 = None
        view = C.rebuild_history_view(dossier_id, lang=lang, as_of=_auth15)
        if view and isinstance(result, dict):
            ch = result.get("codir_history")
            if isinstance(ch, dict):
                ch.update(view)
            else:
                result["codir_history"] = view
    except Exception:
        return


def render_analysis_date_field(settings, lang: str = "fr",
                               key: str = "codir_analysis_as_of_date"):
    """Temporal Core Refactor (A5) — champ « Date d'analyse
    (facultatif) » : autorité STRUCTURÉE de rang 1. ISO AAAA-MM-JJ ;
    vide = pas de scénario. Le rappel de la valeur ACTIVE est rendu
    ici même : l'utilisateur ne peut pas lancer un run rétrospectif
    sans le voir. Fail-open (module isolé)."""
    try:
        import streamlit as st
    except Exception:
        return
    try:
        # Correctif TCR-C2 (A5) — pattern « pending » Streamlit : une
        # adoption cliquée au run précédent est consommée ICI, AVANT
        # l'instanciation du widget (le seul moment où écrire la clé
        # d'un widget est autorisé par Streamlit).
        _pend = None
        try:
            _pend = st.session_state.pop(key + "_pending", None)
        except Exception:
            _pend = None
        if _pend:
            st.session_state[key] = _pend
            try:
                settings.analysis_as_of_date = _pend
            except Exception:
                pass
            st.success(("✅ Réglage structuré adopté : " + str(_pend) +
                        " — relancez l'analyse.")
                       if lang == "fr" else
                       ("✅ Structured setting adopted: " + str(_pend) +
                        " — relaunch the analysis."))
        current = ""
        try:
            current = getattr(settings, "analysis_as_of_date", "") or ""
        except Exception:
            current = ""
        label = ("Date d'analyse (facultatif) — AAAA-MM-JJ"
                 if lang == "fr" else
                 "Analysis date (optional) — YYYY-MM-DD")
        help_txt = (
            "Autorité temporelle STRUCTURÉE (prioritaire sur le texte du "
            "brief). Vide = analyse à la date du jour. Une date passée "
            "rend le run rétrospectif (lecture seule) ; une date future, "
            "une simulation. Format strict AAAA-MM-JJ — une valeur "
            "malformée bloque le run."
            if lang == "fr" else
            "STRUCTURED temporal authority (takes precedence over the "
            "brief text). Empty = analysis as of today. A past date makes "
            "the run retrospective (read-only); a future date, a "
            "simulation. Strict YYYY-MM-DD — a malformed value blocks "
            "the run.")
        val = st.text_input(label, value=current, key=key, help=help_txt,
                            placeholder="2023-02-15")
        val = (val or "").strip()
        try:
            settings.analysis_as_of_date = val
        except Exception:
            pass
        if val:
            import re as _re
            # Correctif TCR (P1) — validation CALENDAIRE réelle (toute
            # année ; 2023-02-30 rejeté), pas une simple regex.
            _cal_ok = False
            if _re.match(r"^\d{4}-\d{2}-\d{2}$", val):
                try:
                    from datetime import date as _d19
                    _d19.fromisoformat(val)
                    _cal_ok = True
                except Exception:
                    _cal_ok = False
            if _cal_ok:
                st.caption(("📌 Date d'analyse structurée ACTIVE : "
                            f"**{val}** — le prochain run sera "
                            "rétrospectif/simulé, en lecture seule."
                            if lang == "fr" else
                            f"📌 Structured analysis date ACTIVE: "
                            f"**{val}** — the next run will be "
                            "retrospective/simulated, read-only."))
            else:
                st.warning(("⚠️ Format attendu AAAA-MM-JJ — cette valeur "
                            "bloquera le run (fail-closed)."
                            if lang == "fr" else
                            "⚠️ Expected format YYYY-MM-DD — this value "
                            "will block the run (fail-closed)."))
    except Exception:
        pass


def render_temporal_intent_banner(result, settings=None, lang: str = "fr"):
    """Temporal Core Refactor (A5) — bandeau UNE-ACTION post-run.
    Inférence LEGACY appliquée → l'utilisateur le VOIT et peut adopter
    la date en réglage structuré d'un clic (jamais de modal bloquant).
    Source STRUCTURED → simple rappel. Fail-open."""
    try:
        import streamlit as st
    except Exception:
        return
    try:
        ta = (result or {}).get("temporal_authority") or {}
        src = ta.get("intent_source") or "NONE"
        ad = (result or {}).get("analysis_date") or ""
        cand = ta.get("candidate_value") or ""
        # Correctif TCR (A5) — la confirmation est PRÉ-providers : le
        # run legacy est BLOQUÉ (BLOCKED_AMBIGUOUS, zéro appel, zéro
        # coût) avec la date CANDIDATE proposée en une action. Adoption
        # → champ structuré → l'utilisateur relance (le structuré
        # domine alors la candidate du même brief).
        if src == "LEGACY_CANDIDATE" and cand:
            st.warning((
                f"📅 Date d'analyse SUGGÉRÉE par le texte du brief : "
                f"**{cand}** (candidate, non confirmée). Le run est "
                "bloqué sans aucun appel : adoptez la date en réglage "
                "structuré puis relancez, ou corrigez le brief."
                if lang == "fr" else
                f"📅 Analysis date SUGGESTED by the brief text: "
                f"**{cand}** (candidate, unconfirmed). The run is "
                "blocked with zero calls: adopt the date as a "
                "structured setting and relaunch, or fix the brief."))
            # Correctif TCR-v15 (addendum A5, verdict v14) — TROIS
            # actions. La hausse du rappel nécessaire pour qu'aucun
            # backtest ne parte en live peut produire quelques
            # candidates prudentes : l'utilisateur doit pouvoir dire
            # « ce n'est pas ma date d'analyse » et repartir en live
            # d'un clic, sans réécrire artificiellement son brief.
            _decline = ("Ce n'est pas la date d'analyse — continuer en live"
                        if lang == "fr" else
                        "This is not the analysis date — continue live")
            if st.button(_decline, key="decline_temporal_candidate"):
                # Le refus est LIÉ À L'EMPREINTE de l'entrée : modifier
                # le brief invalide la décision, qui ne peut donc pas
                # survivre à un changement de demande.
                _fp = ""
                try:
                    _fp = str((result or {}).get("temporal_authority", {})
                              .get("input_fingerprint") or "")
                except Exception:
                    _fp = ""
                if not _fp:
                    _fp = str(st.session_state.get(
                        "codir_temporal_input_fingerprint") or "")
                st.session_state["codir_temporal_candidate_declined_fp"] = _fp
                st.success("Candidate refusée — le prochain run sera live."
                           if lang == "fr" else
                           "Candidate declined — the next run will be live.")
                try:
                    st.rerun()
                except Exception:
                    pass
            btn = ("Adopter cette date en réglage structuré"
                   if lang == "fr" else "Adopt this date as a structured setting")
            if st.button(btn, key="adopt_structured_asof"):
                # Correctif TCR-C2 (A5) — adoption RÉELLE, zéro
                # exception avalée : Settings d'abord, puis la clé du
                # widget via .update() ; si Streamlit la verrouille
                # (widget déjà instancié CE run — StreamlitAPIException),
                # le chemin NOMINAL est la clé pending, consommée par le
                # champ AVANT son widget au rerun (pattern documenté).
                if settings is not None:
                    settings.analysis_as_of_date = cand
                st.session_state["codir_analysis_as_of_date_pending"] = cand
                try:
                    _StApiErr = RuntimeError
                    try:
                        from streamlit.errors import (StreamlitAPIException
                                                      as _StApiErr)
                    except ImportError:
                        pass
                    try:
                        st.session_state.update(
                            {"codir_analysis_as_of_date": cand})
                    except (_StApiErr, RuntimeError):
                        # clé verrouillée ce run → la pending posée
                        # ci-dessus fera foi au rerun (chemin nominal).
                        pass
                finally:
                    st.success(("✅ Réglage structuré adopté : " + cand +
                                " — relancez l'analyse.")
                               if lang == "fr" else
                               ("✅ Structured setting adopted: " + cand +
                                " — relaunch the analysis."))
                _rr = getattr(st, "rerun", None)
                if callable(_rr):
                    _rr()
        elif src == "STRUCTURED" and ad:
            st.caption((f"📌 Date d'analyse structurée appliquée : {ad} "
                        "(Réglages)." if lang == "fr" else
                        f"📌 Structured analysis date applied: {ad} "
                        "(Settings)."))
    except Exception:
        pass


def render_dossier_label_field(settings, lang: str = "fr", key: str = "codir_dossier_label"):
    """Champ texte « Libellé de dossier ». Écrit dans settings.dossier_label.
    À appeler AVANT le run (zone de saisie du brief). Fail-open."""
    try:
        import streamlit as st
    except Exception:
        return
    try:
        current = ""
        try:
            current = getattr(settings, "dossier_label", "") or ""
        except Exception:
            current = ""
        label = ("Libellé de dossier (recommandé — fil multi-séances)"
                 if lang == "fr" else "Dossier label (recommended — multi-session thread)")
        help_txt = ("Regroupe les CoDIR successifs d'un même dossier. Ex. : "
                    "« Société A vs Société B — M&A », « Cabinet conseil — Plan stratégique 2026-2029 », "
                    "« Société cible — suivi industriel ». Vide → repli automatique "
                    "société + genre."
                    if lang == "fr" else
                    "Groups successive CoDIRs of the same dossier. E.g. "
                    "'Company A vs Company B — M&A'. Empty → automatic fallback company + genre.")
        val = st.text_input(label, value=current, key=key, help=help_txt)
        try:
            _new59 = (val or "").strip()
            _old59 = str(getattr(settings, "dossier_label", "") or "").strip()
            settings.dossier_label = _new59
            # 9.4.59 — recette 9.4.58 : après un redémarrage, le champ reprenait un ancien libellé enregistré (séance 2
            # lancée sur le dossier de la 9.4.56). Le libellé saisi est enregistré dès qu'il change.
            if _new59 and _new59 != _old59:
                from utils.settings_store import save_settings as _ss59
                _ss59(settings)
        except Exception:
            pass
        # F.5.2.1 — sans libellé explicite, le feed-forward agents ne part PAS
        # (le dossier n'est pas connu avant la résolution d'entité). On le dit.
        if not (val or "").strip():
            st.caption("⚠️ " + ("Sans libellé de dossier : l'historique sera affiché "
                                "en fin de run, mais le contexte du CoDIR précédent ne "
                                "sera PAS injecté dans les agents. Saisissez un libellé "
                                "pour activer le feed-forward."
                                if lang == "fr" else
                                "Without a dossier label: history is shown after the run, "
                                "but the previous-CoDIR context is NOT injected into the "
                                "agents. Enter a label to enable feed-forward."))
        return val
    except Exception:
        return


def _fmt_action_label(a: Dict[str, Any], lang: str = "fr") -> str:
    txt = (a.get("action") or "—")[:70]
    ech = a.get("echeance") or ""
    statut = a.get("statut") or ""
    rel = a.get("relance_count", 0)
    bits = [txt]
    if statut:
        bits.append(f"[{statut}]")
    if ech:
        bits.append(("éch. " if lang == "fr" else "due ") + ech)
    if rel:
        bits.append(("relances " if lang == "fr" else "follow-ups ") + str(rel))
    return " · ".join(bits)


def render_action_pilot_ui(result: Dict[str, Any], lang: str = "fr",
                           key_prefix: str = "codir_pilot"):
    """Tableau des actions ouvertes + contrôles de mise à jour manuelle.
    Lit result['codir_history']. Aucune opération auto : tout passe par un clic.
    Fail-open. À appeler dans la zone d'affichage des résultats post-run."""
    try:
        import streamlit as st
    except Exception:
        return
    try:
        ch = (result or {}).get("codir_history") or None
        if not ch:
            return
        dossier_id = ch.get("dossier_id") or ""
        opens = ch.get("open_actions") or []
        reapparues = ch.get("reapparues") or []
        dsrc = ch.get("dossier_source") or ""
        if not dossier_id:
            return

        import patches.codir_register_history as C
        # Gate 16 — policy de la VUE affichée : une vue rétrospective ou
        # future est READ-ONLY (badge visible + contrôles NON rendus) ;
        # toutes les mutations manuelles passent par la même
        # TemporalExecutionPolicy que le moteur. Fail-closed.
        try:
            from patches.temporal_policy import policy_for_view as _pfv16
            _pol16 = _pfv16(result)
        except Exception:
            class _RO16:
                can_mutate_from_pilot = False
                user_message_fr = "🔒 Lecture seule."
                user_message_en = "🔒 Read-only."
            _pol16 = _RO16()

        title = ("🗂️ Pilotage des actions du dossier" if lang == "fr"
                 else "🗂️ Dossier action piloting")
        with st.expander(title, expanded=False):
            # Transparence : sur quel fil sommes-nous, et d'où vient-il.
            fil_msg = (f"Dossier : **{dossier_id}**"
                       + (f" · rattachement : _{dsrc}_" if dsrc else ""))
            st.caption(fil_msg)
            if not _pol16.can_mutate_from_pilot:
                # Refactor — libellé rendu par le TemporalStatusRenderer
                # (source unique) ; repli : messages de la policy.
                try:
                    from patches.temporal_status_renderer import (
                        temporal_status as _ts19)
                    st.warning(_ts19(_pol16, lang)["message"])
                except Exception:
                    st.warning(_pol16.user_message_fr if lang == "fr"
                               else _pol16.user_message_en)
            if dsrc and dsrc.startswith("repli"):
                st.caption("ℹ️ " + ("Aucun libellé explicite : fil déduit (société + genre). "
                                    "Saisissez un « Libellé de dossier » avant le run pour "
                                    "verrouiller le fil."
                                    if lang == "fr" else
                                    "No explicit label: thread inferred (company + genre). "
                                    "Set a 'Dossier label' before the run to lock the thread."))

            if reapparues:
                st.warning(("⚠️ " + str(len(reapparues)) + " action(s) clôturée(s) "
                            "réapparue(s) — à arbitrer (pas de réouverture auto)."
                            if lang == "fr" else
                            "⚠️ " + str(len(reapparues)) + " closed action(s) reappeared "
                            "— to arbitrate (no auto-reopen)."))

            if not opens and not reapparues:
                st.info("Aucune action ouverte sur ce dossier." if lang == "fr"
                        else "No open action on this dossier.")
                return
            if not opens:
                st.info("Aucune action ouverte — voir les réapparues à arbitrer ci-dessous."
                        if lang == "fr" else
                        "No open action — see reappeared actions to arbitrate below.")

            if opens:
                # Tableau lecture seule des actions ouvertes
                try:
                    st.table([{
                        ("Action" if lang == "fr" else "Action"): (a.get("action") or "—")[:80],
                        ("Porteur" if lang == "fr" else "Owner"): a.get("porteur") or "—",
                        ("Échéance" if lang == "fr" else "Deadline"): a.get("echeance") or "—",
                        ("Statut" if lang == "fr" else "Status"): a.get("statut") or "—",
                        ("Relances" if lang == "fr" else "Follow-ups"): a.get("relance_count", 0),
                    } for a in opens])
                except Exception:
                    pass

                # Gate 16 — READ-ONLY : aucun contrôle de mutation n'est
                # rendu (zéro bouton, zéro événement possible depuis une
                # vue rétrospective ou future).
                if not _pol16.can_mutate_from_pilot:
                    return
                # Sélecteur d'action OUVERTE + opération (clôturer/reporter/statut).
                # La réouverture est traitée plus bas, sur les actions RÉAPPARUES.
                labels = [_fmt_action_label(a, lang) for a in opens]
                idx = st.selectbox(("Action ouverte à mettre à jour" if lang == "fr"
                                    else "Open action to update"),
                                   range(len(labels)), format_func=lambda i: labels[i],
                                   key=f"{key_prefix}_sel")
                chosen = opens[idx]
                ops = (["Clôturer", "Reporter (nouvelle échéance)", "Passer en cours",
                        "Passer à arbitrer"] if lang == "fr" else
                       ["Close", "Report (new deadline)", "Set in progress",
                        "Set to arbitrate"])
                op = st.radio(("Opération" if lang == "fr" else "Operation"), ops,
                              key=f"{key_prefix}_op", horizontal=False)
                new_ech = ""
                if op == ops[1]:  # reporter
                    new_ech = st.text_input(("Nouvelle échéance (AAAA-MM-JJ)" if lang == "fr"
                                             else "New deadline (YYYY-MM-DD)"),
                                            key=f"{key_prefix}_ech")
                note = st.text_input(("Note (optionnelle)" if lang == "fr" else "Note (optional)"),
                                     key=f"{key_prefix}_note")

                if st.button(("Appliquer" if lang == "fr" else "Apply"),
                             key=f"{key_prefix}_apply"):
                    akey = chosen.get("action_key") or C.normalize_action_key(chosen.get("action", ""))
                    rid = C.make_run_id(dossier_id)
                    # Gate 17 — une seule horloge : la racine du produit
                    # (metadata_clock), jamais date.today() direct.
                    from utils.metadata_clock import run_now as _rn17
                    rdate = _rn17().date().isoformat()
                    ok = False
                    try:
                        if op == ops[0]:        # clôturer
                            ok = C.close_action(dossier_id, akey, rid, rdate, note=note)
                        elif op == ops[1]:      # reporter
                            ok = C.report_action(dossier_id, akey, rid, rdate,
                                                 new_echeance=new_ech, note=note)
                        elif op in (ops[2], ops[3]):  # en cours / à arbitrer (statut)
                            statut = (C.STATUT_EN_COURS if op == ops[2] else C.STATUT_A_ARBITRER)
                            ev = C.RegisterEvent(
                                event_type=C.EV_UPDATED, action_key=akey, run_id=rid,
                                run_date=rdate, dossier_id=dossier_id,
                                action=chosen.get("action", ""), statut=statut,
                                note=note or "Statut mis à jour (humain).")
                            ok = C.append_events(dossier_id, [ev])
                    except Exception:
                        ok = False
                    if ok:
                        _refresh_history(result, dossier_id, lang)   # MAJ immédiate
                        st.success("Mise à jour enregistrée." if lang == "fr" else "Update saved.")
                        try:
                            st.rerun()
                        except Exception:
                            pass
                    else:
                        st.error("Échec de la mise à jour." if lang == "fr" else "Update failed.")

            # ── Réapparues après clôture — À ARBITRER (réouverture explicite) ──
            if reapparues and not _pol16.can_mutate_from_pilot:
                reapparues = []
            if reapparues:
                st.divider() if hasattr(st, "divider") else None
                st.markdown("**" + ("Actions clôturées réapparues — à arbitrer"
                                    if lang == "fr" else
                                    "Closed actions that reappeared — to arbitrate") + "**")
                r_labels = [_fmt_action_label(a, lang) for a in reapparues]
                r_idx = st.selectbox(("Action réapparue" if lang == "fr"
                                      else "Reappeared action"),
                                     range(len(r_labels)),
                                     format_func=lambda i: r_labels[i],
                                     key=f"{key_prefix}_rsel")
                r_chosen = reapparues[r_idx]
                r_ops = (["Maintenir clôturée", "Rouvrir"] if lang == "fr"
                         else ["Keep closed", "Reopen"])
                r_op = st.radio(("Décision" if lang == "fr" else "Decision"), r_ops,
                                key=f"{key_prefix}_rop", horizontal=True)
                r_note = st.text_input(("Note (optionnelle) " if lang == "fr"
                                        else "Note (optional) "), key=f"{key_prefix}_rnote")
                if st.button(("Arbitrer" if lang == "fr" else "Arbitrate"),
                             key=f"{key_prefix}_rapply"):
                    rakey = (r_chosen.get("action_key")
                             or C.normalize_action_key(r_chosen.get("action", "")))
                    rid = C.make_run_id(dossier_id)
                    from utils.metadata_clock import run_now as _rn17b
                    rdate = _rn17b().date().isoformat()
                    ok = False
                    try:
                        if r_op == r_ops[1]:   # rouvrir explicitement
                            ok = C.reopen_action(dossier_id, rakey, rid, rdate, note=r_note)
                        else:                  # maintenir clôturée → clôture ré-affirmée
                            ok = C.close_action(
                                dossier_id, rakey, rid, rdate,
                                note=r_note or "Maintenue clôturée après réapparition (humain).")
                    except Exception:
                        ok = False
                    if ok:
                        _refresh_history(result, dossier_id, lang)
                        st.success("Arbitrage enregistré." if lang == "fr" else "Arbitration saved.")
                        try:
                            st.rerun()
                        except Exception:
                            pass
                    else:
                        st.error("Échec." if lang == "fr" else "Failed.")
    except Exception:
        return
