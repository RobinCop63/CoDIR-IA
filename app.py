import streamlit as st
import os
from codir_engine import run_codir_session
from libre_engine import run_libre_session
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="CoDIR IA – Multi-IA Orchestrator",
    page_icon="🤖",
    layout="wide"
)

st.sidebar.title("⚙️ Configuration des modèles IA")

st.sidebar.markdown("### 🔑 Clés API détectées")
st.sidebar.text(f"OpenAI: {'OK' if os.getenv('OPENAI_API_KEY') else '⛔'}")
st.sidebar.text(f"Google Gemini: {'OK' if os.getenv('GOOGLE_API_KEY') else '⛔'}")
st.sidebar.text(f"Anthropic Claude: {'OK' if os.getenv('ANTHROPIC_API_KEY') else '⛔'}")
st.sidebar.text(f"Mistral: {'OK' if os.getenv('MISTRAL_API_KEY') else '⛔'}")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🧠 Modèles configurés")
st.sidebar.text(f"OpenAI model: {os.getenv('OPENAI_MODEL')}")
st.sidebar.text(f"Gemini model: {os.getenv('GEMINI_MODEL')}")
st.sidebar.text(f"Anthropic (Claude) model: {os.getenv('ANTHROPIC_MODEL')}")
st.sidebar.text(f"Mistral model: {os.getenv('MISTRAL_MODEL')}")

st.sidebar.markdown("---")
st.sidebar.markdown("📄 Les réponses peuvent être exportées en Word.")

tab_codir, tab_libre = st.tabs(["🏛️ Mode CoDIR (4 IA)", "🧩 Mode Libre (1 IA au choix)"])

with tab_codir:
    st.header("🏛️ Mode CoDIR – Analyse croisée par 4 IA")
    user_input = st.text_area("📝 Votre question", height=180)

    if st.button("🚀 Lancer le CoDIR IA"):
        if not user_input.strip():
            st.error("Merci de saisir une question.")
        else:
            results = run_codir_session(user_input)
            st.success("Terminé !")

            # Affichage des résultats (utilise outputs qui contient les textes)
            for role_name, answer in results["outputs"].items():
                if role_name == "direction_generale":  # évite doublon avec "ceo"
                    continue
                st.subheader(f"🤖 {role_name.upper()}")
                st.write(answer)

            from docx import Document
            doc = Document()
            doc.add_heading("Résultats CoDIR IA – Analyse croisée", level=1)
            doc.add_paragraph(f"Question : {user_input}")
            doc.add_heading("Réponses :", level=2)

            # Export Word (utilise outputs qui contient les textes)
            for role_name, answer in results["outputs"].items():
                if role_name == "direction_generale":  # évite doublon avec "ceo"
                    continue
                doc.add_heading(role_name.upper(), level=3)
                doc.add_paragraph(answer)

            path = "CoDIR_IA_Results.docx"
            doc.save(path)

            with open(path, "rb") as f:
                st.download_button("📥 Télécharger le Word", f, file_name=path)

with tab_libre:
    st.header("🧩 Mode Libre – Choix d'un modèle unique")
    user_input_libre = st.text_area("📝 Votre question", height=180, key="libre_input")
    provider = st.selectbox("🔍 Choisissez un fournisseur IA", ["openai", "gemini", "anthropic", "mistral"])

    if st.button("🚀 Lancer le modèle choisi"):
        if not user_input_libre.strip():
            st.error("Merci de saisir une question.")
        else:
            answer = run_libre_session(provider, user_input_libre)
            st.success("Réponse obtenue :")
            st.write(answer)

            from docx import Document
            doc = Document()
            doc.add_heading("Résultat – Mode Libre", level=1)
            doc.add_paragraph(f"Modèle utilisé : {provider}")
            doc.add_paragraph(f"Question : {user_input_libre}")
            doc.add_heading("Réponse :", level=2)
            doc.add_paragraph(answer)

            path = "CoDIR_IA_Libre_Results.docx"
            doc.save(path)

            with open(path, "rb") as f:
                st.download_button("📥 Télécharger le Word", f, file_name=path)
