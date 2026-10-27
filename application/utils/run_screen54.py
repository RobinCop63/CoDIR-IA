"""9.4.54 — « écran traitement » (maquette validée par le dirigeant le 08/09/2026 ; liste des 12 étapes validée le
07/10/2026).

Pendant le run : logo, « Étape x / 12 », libellé de l'étape, barre de progression qui compte les ÉTAPES ACCOMPLIES
(jamais un pourcentage de temps), temps écoulé et durée habituelle (médiane des derniers runs, à partir de trois).
En fin de run : « Dossier prêt », dossier complet en bouton principal, compte rendu / synthèse / trame en boutons
secondaires (mêmes octets que dans le paquet), retour au brief (brief et réglages conservés), nouveau dossier, quitter.
Un livrable retenu par le contrôle final est nommé, avec sa raison.

Ce module ne fait aucun appel réseau et ne lit aucune pièce : il traduit les signaux d'avancement déjà émis par le moteur
(cb(clé, libellé)) et par l'application en un état d'écran.
"""
from __future__ import annotations

import html
import json
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

NAVY, GOLD, GLACIER, GREY = "#1E2761", "#E8B84B", "#CADCFC", "#6B7280"

# (numéro, identifiant, libellé FR, libellé EN) — liste validée le 07/10/2026
STEPS: List[tuple] = [
    (1, "documents", "Lecture des pièces", "Reading the documents"),
    (2, "sources", "Sources officielles et veille", "Official sources and watch"),
    (3, "strategie", "Stratégie — analyse en cours", "Strategy — analysis in progress"),
    (4, "brief_codir", "Préparation de la séance", "Preparing the session"),
    (5, "marketing", "Marketing — analyse en cours", "Marketing — analysis in progress"),
    (6, "finance", "Finance — analyse et second avis", "Finance — analysis and second opinion"),
    (7, "supply_chain", "Supply chain — analyse et contradicteur", "Supply chain — analysis and challenger"),
    (8, "commercial", "Direction commerciale — analyse en cours", "Sales — analysis in progress"),
    (9, "synthese_decisions", "Synthèse des décisions", "Decision synthesis"),
    (10, "direction_generale", "Direction générale — feuille de route", "General management — roadmap"),
    (11, "controles_cr", "Contrôles et compte rendu", "Checks and minutes"),
    (12, "deck_dossier", "Trame PowerPoint et dossier complet", "PowerPoint draft and full package"),
]
TOTAL = len(STEPS)


def step_for_key(key: str) -> Optional[int]:
    """Numéro d'étape d'une clé d'avancement du moteur (préfixes : « finance_gemini », « finance_challenge_claude_1 »…)."""
    k = str(key or "").lower()
    if not k:
        return None
    if k in ("web_search", "sources", "external_facts", "sec", "gleif", "pappers") or k.startswith(("web_", "external_")):
        return 2
    if k.startswith("finance"):
        return 6
    if k.startswith("supply_chain"):
        return 7
    if k in ("ceo", "dg") or k.startswith("direction_generale"):
        return 10
    if k.startswith("synthese"):
        return 9
    for n, sid, _fr, _en in STEPS:
        if k == sid or k.startswith(sid):
            return n
    return None


class RunProgress:
    """État de l'écran pendant le run. Une étape démarrée fait passer les précédentes pour « accomplies » : le
    pourcentage ne recule jamais, et une étape sans objet pour le dossier est simplement franchie."""

    def __init__(self, lang: str = "fr", durations: Optional[List[float]] = None, clock=time.monotonic):
        self.lang = "en" if str(lang).lower().startswith("en") else "fr"
        self.clock = clock
        self.t0 = clock()
        self.current = 0
        self.detail = ""
        self.durations = [float(x) for x in (durations or []) if x]
        self.finished = False

    # ── état ──────────────────────────────────────────────────────────────
    def start(self, step_no: int, detail: str = "") -> None:
        if step_no and step_no > self.current:
            self.current = min(int(step_no), TOTAL)
        self.detail = str(detail or "")

    def on_engine(self, key: str, label: str = "") -> None:
        n = step_for_key(key)
        if n:
            self.start(n, label)

    def finish(self) -> None:
        self.current = TOTAL
        self.finished = True

    @property
    def done(self) -> int:
        return TOTAL if self.finished else max(0, self.current - 1)

    @property
    def percent(self) -> int:
        return int(round(100 * self.done / TOTAL))

    def label(self) -> str:
        if not self.current:
            return "Préparation…" if self.lang == "fr" else "Preparing…"
        n, _sid, fr, en = STEPS[self.current - 1]
        return fr if self.lang == "fr" else en

    def elapsed_s(self) -> float:
        return max(0.0, self.clock() - self.t0)

    def habitual(self) -> Optional[tuple]:
        """(bas, haut) en minutes : intervalle autour de la médiane des derniers runs ; None sous trois runs."""
        if len(self.durations) < 3:
            return None
        recent = self.durations[-10:]
        med = statistics.median(recent)
        lo = min(recent) if len(recent) < 5 else statistics.quantiles(recent, n=4)[0]
        hi = max(recent) if len(recent) < 5 else statistics.quantiles(recent, n=4)[2]
        lo, hi = min(lo, med), max(hi, med)
        return (max(1, int(lo // 60)), max(1, int(round(hi / 60))))

    # ── rendu ─────────────────────────────────────────────────────────────
    def html(self, logo_b64: str = "") -> str:
        fr = self.lang == "fr"
        el = int(self.elapsed_s())
        el_txt = (f"{el // 60} min {el % 60:02d} s" if el >= 60 else f"{el} s")
        hab = self.habitual()
        times = (f"Temps écoulé {el_txt}" if fr else f"Elapsed {el_txt}")
        if hab:
            times += (f"  ·  durée habituelle {hab[0]} à {hab[1]} min (médiane de vos derniers runs)" if fr
                      else f"  ·  usual duration {hab[0]} to {hab[1]} min (median of your recent runs)")
        step_txt = (f"Étape {max(self.current, 1)} / {TOTAL}" if fr else f"Step {max(self.current, 1)} / {TOTAL}")
        note = ("Le pourcentage compte les étapes accomplies, pas le temps : une étape peut durer plus longtemps qu'une autre."
                if fr else "The percentage counts completed steps, not time: one step may take longer than another.")
        stay = ("Ne fermez pas cette fenêtre — le dossier sera prêt à la fin de la dernière étape." if fr
                else "Do not close this window — the package will be ready at the end of the last step.")
        logo = (f'<img src="data:image/png;base64,{logo_b64}" style="height:64px;margin:6px auto;display:block"/>'
                if logo_b64 else "")
        logo_small = (f'<img src="data:image/png;base64,{logo_b64}" style="height:40px;margin:18px auto 0;display:block;opacity:.85"/>'
                      if logo_b64 else "")
        return f"""
<div style="text-align:center;padding:12px 0 6px 0;font-family:inherit">
  {logo}
  <div style="font-size:2.6rem;font-weight:800;color:{NAVY};margin-top:18px">{html.escape(step_txt)}</div>
  <div style="font-size:1.15rem;color:{GREY};margin:6px 0 18px 0">{html.escape(self.label())}</div>
  <div style="display:flex;align-items:center;justify-content:center;gap:12px;max-width:720px;margin:0 auto">
    <div style="flex:1;background:{GLACIER};border-radius:14px;height:26px;overflow:hidden">
      <div style="width:{self.percent}%;background:{GOLD};height:100%;border-radius:14px;transition:width .4s"></div>
    </div>
    <div style="font-weight:700;color:{NAVY};min-width:56px;text-align:left">{self.percent} %</div>
  </div>
  <div style="color:{GREY};margin-top:14px">{html.escape(times)}</div>
  <div style="color:#9CA3AF;font-style:italic;font-size:.85rem;margin-top:6px">{html.escape(note)}</div>
  <div style="color:{GREY};margin-top:20px">{html.escape(stay)}</div>
  {logo_small}
</div>"""


# ── durées des runs précédents (médiane affichée à partir de trois runs) ───────────────────────────────────────────
def durations_path() -> Path:
    try:
        from utils.config_paths import ensure_config_dir
        return Path(ensure_config_dir()) / "run_durations.json"
    except Exception:
        return Path.home() / ".codir_ia_run_durations.json"


def load_durations(path: Optional[Path] = None) -> List[float]:
    p = Path(path or durations_path())
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return [float(x) for x in data if isinstance(x, (int, float)) and x > 0][-20:]
    except Exception:
        return []


def record_duration(seconds: float, path: Optional[Path] = None) -> None:
    p = Path(path or durations_path())
    try:
        vals = load_durations(p) + [round(float(seconds), 1)]
        p.write_text(json.dumps(vals[-20:]), encoding="utf-8")
    except Exception:
        pass


# ── écran de fin ────────────────────────────────────────────────────────────────────────────────────────────────────
def withheld_deliverables(result: Optional[Dict[str, Any]], have: Dict[str, bool], lang: str = "fr") -> List[Dict[str, str]]:
    """Livrables retenus par le contrôle final : lequel, et pourquoi (variante « un livrable retenu » de la maquette)."""
    fr = not str(lang).lower().startswith("en")
    meta = (result or {}).get("meta") or {}
    out = []
    names = {"cr": ("Compte rendu (Word)", "Minutes (Word)"), "synthese": ("Synthèse (Word)", "Summary (Word)"),
             "pptx": ("Trame PowerPoint", "PowerPoint draft")}
    reasons = {"cr": meta.get("docx_block_reason") or meta.get("docx_error"),
               "synthese": meta.get("synthesis_block_reason"),
               "pptx": meta.get("pptx_block_reason") or ((meta.get("deck_layout_gate") or {}).get("blocking_reason")
                                                          if isinstance(meta.get("deck_layout_gate"), dict) else None)}
    for k, ok in have.items():
        if not ok:
            r = str(reasons.get(k) or ("non produit par ce run — voir le diagnostic du paquet" if fr
                                       else "not produced by this run — see the package diagnostics"))
            out.append({"key": k, "name": names[k][0 if fr else 1], "reason": r[:300]})
    return out


_RESULT_KEYS54 = ("last_result", "last_docx", "last_pptx", "last_synthese_docx", "last_docx_error", "last_pptx_debug",
                  "last_pptx_layout_report", "paquet54", "quit54_confirm", "run_screen54_done",
                  "end57_active", "pkg57_downloaded", "quit57_confirm")


def back_to_brief(session) -> None:
    """« Retour au brief » : brief et réglages conservés (runs de confirmation = même brief) ; seuls les résultats partent."""
    for k in _RESULT_KEYS54:
        if k in session:
            session[k] = None


def new_dossier(session, keep=("settings", "lang", "_logo_b64_54", "page")) -> None:
    """« Nouveau dossier » : tout est effacé, sauf les réglages de l'application."""
    for k in list(session.keys()):
        if k not in keep:
            del session[k]


def quit_server() -> None:
    """« Quitter » (après confirmation) : arrête proprement le serveur local de CoDIR IA et sa chaîne de lancement
    (9.4.61 — sous Windows, un Python restait ouvert dans le gestionnaire de tâches)."""
    try:
        from pathlib import Path as _P
        from utils.process_manager import shutdown_codir_tree61
        shutdown_codir_tree61(_P(__file__).resolve().parent.parent)
    except Exception:
        import os
        os._exit(0)


def render_end_screen(st, lang: str, result: Optional[Dict[str, Any]], package: Optional[tuple], cr: Optional[tuple],
                      synthese: Optional[tuple], pptx: Optional[tuple], logo_b64: str = "", container=None) -> None:
    """Écran de fin (maquettes 2/3 et 3/3). package / cr / synthese / pptx : (octets, nom de fichier) ou None — les mêmes
    octets que ceux du paquet, jamais une seconde génération."""
    fr = not str(lang).lower().startswith("en")
    box = container or st
    have = {"cr": bool(cr and cr[0]), "synthese": bool(synthese and synthese[0]), "pptx": bool(pptx and pptx[0])}
    withheld = withheld_deliverables(result, have, lang)
    logo = (f'<img src="data:image/png;base64,{logo_b64}" style="height:60px;margin:4px auto;display:block"/>'
            if logo_b64 else "")
    title = "Dossier prêt" if fr else "Package ready"
    sub = ((f"{3 - len(withheld)} livrable(s) sur 3 prêt(s) — {len(withheld)} retenu(s) par le contrôle final"
            if withheld else "Les trois livrables et leurs pièces de contrôle sont dans le dossier complet.") if fr else
           (f"{3 - len(withheld)} of 3 deliverables ready — {len(withheld)} withheld by the final check"
            if withheld else "The three deliverables and their control files are in the full package."))
    box.markdown(f'<div style="text-align:center;margin:8px 0 14px 0">{logo}'
                 f'<div style="font-size:2.2rem;font-weight:800;color:{NAVY};margin-top:10px">{html.escape(title)}</div>'
                 f'<div style="color:{GREY};margin-top:4px">{html.escape(sub)}</div></div>', unsafe_allow_html=True)
    if package and package[0]:
        box.download_button(("⬇ Dossier complet (.zip)" if fr else "⬇ Full package (.zip)"), data=package[0],
                            file_name=package[1], mime="application/zip", type="primary", use_container_width=True,
                            key="end54_package")
    else:
        box.button(("Dossier complet — en préparation…" if fr else "Full package — being prepared…"),
                   disabled=True, use_container_width=True, key="end54_package_wait")
    c1, c2, c3 = box.columns(3)
    for col, key, item, lab_fr, lab_en, mime in (
            (c1, "cr", cr, "Compte rendu (Word)", "Minutes (Word)",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            (c2, "synthese", synthese, "Synthèse (Word)", "Summary (Word)",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            (c3, "pptx", pptx, "Trame PowerPoint", "PowerPoint draft",
             "application/vnd.openxmlformats-officedocument.presentationml.presentation")):
        if item and item[0]:
            col.download_button(lab_fr if fr else lab_en, data=item[0], file_name=item[1], mime=mime,
                                use_container_width=True, key=f"end54_{key}")
        else:
            col.button((lab_fr + " — retenu") if fr else (lab_en + " — withheld"), disabled=True,
                       use_container_width=True, key=f"end54_{key}_off")
    for w in withheld:
        box.warning((f"**{w['name']}** n'est pas livré : {w['reason']}" if fr else
                     f"**{w['name']}** is not delivered: {w['reason']}"))
    b1, b2, b3 = box.columns(3)
    if b1.button("↩ Retour au brief" if fr else "↩ Back to the brief", use_container_width=True, key="end54_back"):
        back_to_brief(st.session_state)
        st.rerun()
    if b2.button("＋ Nouveau dossier" if fr else "＋ New file", use_container_width=True, key="end54_new"):
        new_dossier(st.session_state)
        st.rerun()
    if not st.session_state.get("quit54_confirm"):
        if b3.button("⏻ Quitter" if fr else "⏻ Quit", use_container_width=True, key="end54_quit"):
            st.session_state["quit54_confirm"] = True
            st.rerun()
    else:
        b3.warning("Arrêter CoDIR IA ? Les fichiers déjà téléchargés sont conservés." if fr else
                   "Stop CoDIR IA? Files already downloaded are kept.")
        q1, q2 = b3.columns(2)
        if q1.button("Confirmer" if fr else "Confirm", key="end54_quit_yes"):
            box.info("CoDIR IA s'arrête — vous pouvez fermer cet onglet." if fr else "CoDIR IA is stopping — you may close this tab.")
            quit_server()
        if q2.button("Annuler" if fr else "Cancel", key="end54_quit_no"):
            st.session_state["quit54_confirm"] = False
            st.rerun()


# ── 9.4.57 — écrans dépouillés (demande du dirigeant du 09/10/2026, capture « Étape 7 / 12 ») ─────────────────────────
# Pendant le run, l'écran recouvre TOUTE la fenêtre (formulaire, barre latérale, en-tête) et le temps s'égrène seconde par
# seconde dans le navigateur, sans script : une animation CSS d'un nombre entier (@property) part du temps déjà écoulé.
# En fin de run, la page entière est remplacée par l'écran de fin : cinq tuiles et « Quitter », rien d'autre.

def _timer_css57(elapsed_s: int) -> str:
    e = max(0, int(elapsed_s))
    return ("<style>"
            "@property --s57{syntax:'<integer>';initial-value:0;inherits:false}"
            "@property --m57{syntax:'<integer>';initial-value:0;inherits:false}"
            "@keyframes tick57{from{--s57:0}to{--s57:86400}}"
            f".codir-t57{{animation:tick57 86400s steps(86400) {-e}s forwards;"
            "--m57:calc((var(--s57) - 30) / 60);"
            "counter-reset:min57 var(--m57) sec57 calc(var(--s57) - var(--m57) * 60)}"
            ".codir-t57::after{content:counter(min57) ' min ' counter(sec57, decimal-leading-zero) ' s'}"
            "</style>")


def overlay_html57(rp: "RunProgress", logo_b64: str = "", final: bool = False) -> str:
    """Écran de traitement plein écran (au-dessus de toute l'interface Streamlit)."""
    fr = rp.lang == "fr"
    el = int(rp.elapsed_s())
    hab = rp.habitual()
    hab_txt = ""
    if hab:
        hab_txt = (f" · durée habituelle {hab[0]} à {hab[1]} min" if fr else f" · usual duration {hab[0]} to {hab[1]} min")
    step_txt = (f"Étape {max(rp.current, 1)} / {TOTAL}" if fr else f"Step {max(rp.current, 1)} / {TOTAL}")
    label = rp.label()
    if final:
        step_txt = "Dossier prêt" if fr else "Package ready"
        label = "Ouverture des téléchargements…" if fr else "Opening the downloads…"
    note = ("Le pourcentage compte les étapes accomplies, pas le temps : une étape peut durer plus longtemps qu'une autre."
            if fr else "The percentage counts completed steps, not time: one step may take longer than another.")
    stay = ("Ne fermez pas cette fenêtre — le dossier sera prêt à la fin de la dernière étape." if fr
            else "Do not close this window — the package will be ready at the end of the last step.")
    logo = (f'<img src="data:image/png;base64,{logo_b64}" style="height:78px;display:block;margin:0 auto"/>' if logo_b64 else "")
    logo_s = (f'<img src="data:image/png;base64,{logo_b64}" style="height:46px;display:block;margin:26px auto 0;opacity:.85"/>'
              if logo_b64 else "")
    timer = (f'<span>{"Temps écoulé" if fr else "Elapsed"} </span><span class="codir-t57"></span>'
             f'<span>{html.escape(hab_txt)}</span>')
    if final:
        # 9.4.62 — recette du 14/10 : à l'état final, le compteur animé continuait de tourner et laissait croire que le
        # traitement se poursuivait ; il est FIGÉ sur la durée réelle du run
        _m, _s = divmod(el, 60)
        timer = (f'<span>{"Durée du traitement" if fr else "Processing time"} {_m} min {_s:02d} s</span>'
                 f'<span>{html.escape(hab_txt)}</span>')
    return (_timer_css57(el) +
            '<div style="position:fixed;inset:0;z-index:1000000;background:#FFFFFF;display:flex;align-items:center;'
            'justify-content:center;font-family:\'Source Sans Pro\',\'Segoe UI\',Arial,sans-serif">'
            '<div style="width:min(860px,92vw);text-align:center">'
            f'{logo}'
            f'<div style="font-size:3.2rem;font-weight:800;color:{NAVY};margin-top:34px">{html.escape(step_txt)}</div>'
            f'<div style="font-size:1.35rem;color:{GREY};margin:10px 0 26px 0">{html.escape(label)}</div>'
            '<div style="display:flex;align-items:center;gap:16px">'
            f'<div style="flex:1;background:{GLACIER};border-radius:16px;height:30px;overflow:hidden">'
            f'<div style="width:{100 if final else rp.percent}%;background:{GOLD};height:100%;border-radius:16px"></div></div>'
            f'<div style="font-weight:700;color:{NAVY};font-size:1.25rem;min-width:64px;text-align:left">'
            f'{100 if final else rp.percent} %</div></div>'
            f'<div style="color:{GREY};font-size:1.15rem;margin-top:22px">{timer}</div>'
            f'<div style="color:#9CA3AF;font-style:italic;font-size:.95rem;margin-top:10px">{html.escape(note)}</div>'
            f'<div style="color:{GREY};font-size:1.1rem;margin-top:30px">{html.escape(stay)}</div>'
            f'{logo_s}</div></div>')


_END_CSS57 = """<style>
section[data-testid="stSidebar"], div[data-testid="stSidebarCollapsedControl"], header[data-testid="stHeader"],
div[data-testid="stToolbar"], footer, div[data-testid="stDecoration"] {display:none !important}
div[data-testid="stAppViewContainer"] .block-container, div[data-testid="stMainBlockContainer"] {max-width:900px;
  padding-top:4vh}
div[data-testid="stDownloadButton"] button, div[data-testid="stButton"] button.codir-tile57 {width:100%}
.st-key-tiles57 div[data-testid="stDownloadButton"] button, .st-key-tiles57 div[data-testid="stButton"] button {
  min-height:96px; border-radius:16px; font-size:1.08rem; font-weight:600}
</style>"""


def render_end_page57(st, lang: str, result: Optional[Dict[str, Any]], package: Optional[tuple], cr: Optional[tuple],
                      synthese: Optional[tuple], pptx: Optional[tuple], logo_b64: str = "") -> None:
    """Écran de fin dépouillé : la page entière est remplacée (rien d'autre n'est affiché). Tuiles : Compte rendu,
    Synthèse, Trame PowerPoint, Dossier complet, Nouvelle séance ; « Quitter » à part, avec confirmation."""
    fr = not str(lang).lower().startswith("en")
    st.markdown(_END_CSS57, unsafe_allow_html=True)
    have = {"cr": bool(cr and cr[0]), "synthese": bool(synthese and synthese[0]), "pptx": bool(pptx and pptx[0])}
    withheld = withheld_deliverables(result, have, lang)
    logo = (f'<img src="data:image/png;base64,{logo_b64}" style="height:78px;display:block;margin:0 auto"/>' if logo_b64 else "")
    sub = ((f"{3 - len(withheld)} livrable(s) sur 3 — {len(withheld)} retenu(s) par le contrôle final" if withheld
            else "Les trois livrables sont prêts.") if fr else
           (f"{3 - len(withheld)} of 3 deliverables — {len(withheld)} withheld by the final check" if withheld
            else "The three deliverables are ready."))
    _lbl59 = str((st.session_state.get("form59") or {}).get("codir_dossier_label")
                 or st.session_state.get("codir_dossier_label") or "").strip()
    _dos59 = (f'<div style="color:{NAVY};font-size:1.05rem;margin-top:4px">'
              f'{"Dossier" if fr else "File"} : <b>{html.escape(_lbl59)}</b></div>') if _lbl59 else ""
    st.markdown(f'<div style="text-align:center">{logo}<div style="font-size:3rem;font-weight:800;color:{NAVY};'
                f'margin-top:26px">{"Dossier prêt" if fr else "Package ready"}</div>{_dos59}'
                f'<div style="color:{GREY};font-size:1.2rem;margin:8px 0 28px 0">{html.escape(sub)}</div></div>',
                unsafe_allow_html=True)
    try:
        _tiles57 = st.container(key="tiles57")          # Streamlit ≥ 1.38 : classe CSS st-key-tiles57 (tuiles)
    except TypeError:
        _tiles57 = st.container()
    _tiles57.__enter__()
    c1, c2, c3 = st.columns(3)
    for col, key, item, lab_fr, lab_en, mime in (
            (c1, "cr", cr, "📄 Compte rendu", "📄 Minutes",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            (c2, "synthese", synthese, "📄 Synthèse", "📄 Summary",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            (c3, "pptx", pptx, "📊 Trame PowerPoint", "📊 PowerPoint draft",
             "application/vnd.openxmlformats-officedocument.presentationml.presentation")):
        with col:
            if item and item[0]:
                st.download_button(lab_fr if fr else lab_en, data=item[0], file_name=item[1], mime=mime,
                                   use_container_width=True, key=f"end57_{key}")
            else:
                st.button((lab_fr + " — retenu") if fr else (lab_en + " — withheld"), disabled=True,
                          use_container_width=True, key=f"end57_{key}_off")
    if package and package[0]:
        if st.download_button(("🗂 Dossier complet" if fr else "🗂 Full package"), data=package[0], file_name=package[1],
                              mime="application/zip", type="primary", use_container_width=True, key="end57_package"):
            st.session_state["pkg57_downloaded"] = True
    else:
        st.button(("🗂 Dossier complet — en préparation…" if fr else "🗂 Full package — being prepared…"), disabled=True,
                  use_container_width=True, key="end57_package_wait")
    if st.button(("↩ Nouvelle séance" if fr else "↩ New session"), use_container_width=True, key="end57_new"):
        back_to_brief(st.session_state)
        st.session_state["end57_active"] = False
        # 9.4.59 — le brief, le libellé de dossier et les cases du formulaire sont restitués tels qu'au lancement
        for _k59, _v59 in dict(st.session_state.get("form59") or {}).items():
            # 9.4.61 — même règle à la restitution (une mise de côté antérieure à la 9.4.61 peut contenir un bouton)
            if not ((_k59.startswith("bui_") and isinstance(_v59, str)) or _k59 == "codir_dossier_label"
                    or (_k59 in ("codir_export_pptx", "codir_clean_run") and isinstance(_v59, bool))):
                continue
            try:
                st.session_state[_k59] = _v59
            except Exception:
                pass
        st.rerun()
    _tiles57.__exit__(None, None, None)
    for w in withheld:
        st.warning((f"**{w['name']}** n'est pas livré : {w['reason']}" if fr else f"**{w['name']}** is not delivered: {w['reason']}"))
    # 9.4.60 — résultat de l'enregistrement automatique du dossier complet, visible (réussite et chemin, ou échec et motif)
    _as60 = st.session_state.get("autosave60") or {}
    if _as60.get("ok"):
        st.caption((f"Dossier complet également enregistré : {_as60.get('path')}" if fr
                    else f"Full package also saved: {_as60.get('path')}"))
    elif _as60:
        st.warning((f"L'enregistrement automatique du dossier a échoué ({_as60.get('reason')}) : téléchargez-le avec la tuile "
                    f"« Dossier complet »." if fr else f"Automatic save of the package failed ({_as60.get('reason')}): "
                    f"download it with the « Full package » tile."))
    st.markdown('<div style="height:26px"></div>', unsafe_allow_html=True)
    _q1, _q2, q3 = st.columns([3, 3, 2])
    with q3:
        if not st.session_state.get("quit57_confirm"):
            if st.button("⏻ Quitter" if fr else "⏻ Quit", use_container_width=True, key="end57_quit"):
                st.session_state["quit57_confirm"] = True
                st.rerun()
        else:
            warn = (("Le dossier complet n'a pas été téléchargé — quitter quand même ?" if fr
                     else "The full package has not been downloaded — quit anyway?")
                    if (package and package[0] and not st.session_state.get("pkg57_downloaded")) else
                    ("Arrêter CoDIR IA ?" if fr else "Stop CoDIR IA?"))
            st.warning(warn)
            a, b = st.columns(2)
            if a.button("Quitter" if fr else "Quit", key="end57_quit_yes"):
                st.info("CoDIR IA s'arrête — vous pouvez fermer cet onglet." if fr else "CoDIR IA is stopping — you may close this tab.")
                quit_server()
            if b.button("Annuler" if fr else "Cancel", key="end57_quit_no"):
                st.session_state["quit57_confirm"] = False
                st.rerun()
