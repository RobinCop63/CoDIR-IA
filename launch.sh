#!/usr/bin/env bash
set -e

# Se placer dans le dossier du script
cd "$(dirname "$0")"

echo "🚀 Lancement de l'Orchestrateur multi-IA v15 (macOS/Linux)"

# 1) Vérification de python3
if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ Python 3 introuvable sur ce système."
  echo "   Installe-le (par exemple via Homebrew :  brew install python)"
  exit 1
fi

# 2) Création de l'environnement virtuel si nécessaire
if [ ! -d "venv" ]; then
  echo "🔧 Création de l'environnement virtuel..."
  python3 -m venv venv
fi

# 3) Activation de l'environnement virtuel
# shellcheck disable=SC1091
source venv/bin/activate

# 4) Installation des dépendances
echo "📦 Installation des dépendances..."
pip install -r requirements.txt

# 5) Création du fichier .env à partir de .env.template si absent
if [ ! -f ".env" ] && [ -f ".env.template" ]; then
  echo "🧩 Aucun .env trouvé — création à partir de .env.template"
  cp .env.template .env
  echo "   ➜ Ouvre le fichier .env et ajoute tes clés API avant une utilisation complète."
fi

# 6) Lancement de Streamlit
echo "🌐 Démarrage de l'application Streamlit..."
if command -v streamlit >/dev/null 2>&1; then
  streamlit run app.py
else
  python3 -m streamlit run app.py
fi
