@echo off
echo 🚀 Lancement de l'Orchestrateur multi-IA v15 (Windows)
cd /d "%~dp0"

REM 1) Création de l'environnement virtuel si absent
IF NOT EXIST venv (
  echo 🔧 Création de l'environnement virtuel...
  python -m venv venv
)

REM 2) Activation de l'environnement virtuel
call venv\Scripts\activate

REM 3) Installation des dépendances
echo 📦 Installation des dépendances...
pip install -r requirements.txt

REM 4) Copie du fichier .env si absent
IF NOT EXIST .env (
  IF EXIST .env.template (
    echo 🧩 Aucun .env détecté, création à partir de .env.template...
    copy .env.template .env
    echo 👉 Ouvre le fichier .env et colle tes clés API avant une utilisation complète.
  ) ELSE (
    echo ⚠️ Aucun .env ni .env.template n'a été trouvé. Pense à les ajouter à la racine du projet.
  )
)

REM 5) Lancement de Streamlit
echo 🌐 Démarrage de l'application Streamlit...
streamlit run app.py
