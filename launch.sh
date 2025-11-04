#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
echo "🚀 Lancement de l'Orchestrateur multi-IA v15 (macOS/Linux)"

# Création de l'environnement virtuel
if [ ! -d "venv" ]; then
  echo "🔧 Création de l'environnement virtuel..."
  python3 -m venv venv
fi

source venv/bin/activate

# Installation des dépendances
echo "📦 Installation des dépendances..."
pip install -r requirements.txt

# Copie du fichier .env si absent
if [ ! -f ".env" ]; then
  echo "🧩 Copie du fichier .env.example vers .env..."
  cp .env.example .env
fi

# Lancement de Streamlit
echo "🌐 Démarrage de l'application Streamlit..."
streamlit run app.py
