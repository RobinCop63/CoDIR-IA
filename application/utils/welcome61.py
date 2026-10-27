"""9.4.61 — écran d'accueil (demande du dirigeant, 13/10/2026) : des visiteurs non francophones du dépôt public, arrêtés
par une interface en français, ignoraient qu'elle existe en anglais. Au lancement, un écran dépouillé — logo, deux choix
« Français » / « English » — fixe la langue de l'interface et rappelle que la langue des documents se choisit à part."""
import base64
import html
from pathlib import Path

NAVY = "#1F3864"
GREY = "#6B7280"


def _logo_b64() -> str:
    try:
        p = Path(__file__).resolve().parent.parent / "assets" / "CoDIR_IA.png"
        return base64.b64encode(p.read_bytes()).decode("ascii") if p.exists() else ""
    except Exception:
        return ""


def render_welcome61(st, settings, save_settings) -> bool:
    """Affiche l'écran d'accueil tant que la langue n'a pas été choisie dans la session ; True si l'écran est affiché."""
    if st.session_state.get("lang_welcome61"):
        return False
    logo = _logo_b64()
    img = (f'<img src="data:image/png;base64,{logo}" style="height:110px;margin:40px auto 10px;display:block"/>'
           if logo else "")
    st.markdown(
        f'<div style="text-align:center">{img}'
        f'<div style="font-size:2.6rem;font-weight:800;color:{NAVY};margin-top:8px">CoDIR IA</div>'
        f'<div style="color:{GREY};font-size:1.15rem;margin:6px 0 34px 0">'
        f'Choisissez la langue de l\'interface · Choose the interface language</div></div>',
        unsafe_allow_html=True)
    _l, c1, c2, _r = st.columns([1.2, 1, 1, 1.2])
    choice = None
    with c1:
        if st.button("Français", use_container_width=True, key="welcome61_fr", type="primary"):
            choice = "fr"
        st.caption("Les documents (compte rendu, synthèse, trame) peuvent être produits en français ou en anglais, "
                   "quelle que soit la langue de l'interface.")
    with c2:
        if st.button("English", use_container_width=True, key="welcome61_en", type="primary"):
            choice = "en"
        st.caption("Documents (minutes, summary, slide outline) can be produced in English or in French, "
                   "whatever the interface language.")
    if choice:
        try:
            settings.output_language = choice
            save_settings(settings)
        except Exception:
            pass
        st.session_state["_ui_lang_override_b138"] = choice
        st.session_state["lang_welcome61"] = choice
        st.rerun()
    return True
