#!/usr/bin/env bash
# CoDIR IA - Lancement (macOS/Linux) - PUBLIC
# Usage: chmod +x launch_user.sh && ./launch_user.sh

set -euo pipefail

# Aller dans le dossier du script
cd "$(dirname "$0")"

echo "=========================================="
echo "  🚀 Lancement de CoDIR IA (Public)"
echo "=========================================="
echo

# 1) Python3 requis
if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ Python3 introuvable."
  echo "   Installez-le avec Homebrew :  brew install python"
  exit 1
fi

# 2) .env depuis template si absent
if [ ! -f ".env" ] && [ -f ".env.template" ]; then
  echo "⚠️  Aucun .env détecté — création depuis .env.template"
  cp ".env.template" ".env"
  echo "   ➜ Ouvrez .env et ajoutez vos clés API avant une utilisation complète."
  echo
fi

# 3) Créer venv si absent
if [ ! -d "venv" ]; then
  echo "🔧 Création de l'environnement virtuel (venv)..."
  python3 -m venv venv
fi

# 4) Activer venv
# shellcheck disable=SC1091
source "venv/bin/activate"

# 5) Installer dépendances
echo
echo "🔧 Installation/mise à jour des dépendances..."
python -m pip install --upgrade pip >/dev/null
pip install -r requirements.txt

# 6) Lancer l'app
echo
echo "▶️  Démarrage de l'application (Streamlit)..."
# Fallback si 'streamlit' n'est pas dans le PATH du venv
if command -v streamlit >/dev/null 2>&1; then
  streamlit run app.py
else
  python -m streamlit run app.py
fi

echo
echo "✅ Fin de session CoDIR IA"
