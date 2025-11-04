@echo off
echo 🚀 Lancement de l'Orchestrateur multi-IA v15 (Windows)
cd /d "%~dp0"

REM Création de l'environnement virtuel
IF NOT EXIST venv (
  echo 🔧 Création de l'environnement virtuel...
  python -m venv venv
)

call venv\Scripts\activate

REM Installation des dépendances
echo 📦 Installation des dépendances...
pip install -r requirements.txt

REM Copie du fichier .env si absent
IF NOT EXIST .env (
  echo 🧩 Copie du fichier .env.example vers .env...
  copy .env.example .env
)

REM Lancement de Streamlit
echo 🌐 Démarrage de l'application Streamlit...
streamlit run app.py
