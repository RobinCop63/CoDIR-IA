#!/usr/bin/env bash
# CoDIR IA - Lancement (macOS/Linux) - DEV
# Usage:
#   chmod +x mac/launch_user.sh && ./mac/launch_user.sh
# Or from ./mac:
#   chmod +x launch_user.sh && ./launch_user.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "=========================================="
echo "  🚀 Lancement de CoDIR IA (macOS/Linux)"
echo "=========================================="
echo
echo "📁 Dossier de travail : $(pwd)"
echo

# 1) Check python
if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ python3 introuvable. Installez Python 3.10+ puis relancez."
  exit 1
fi

# 2) Create venv
if [ ! -d ".venv" ]; then
  echo "🔧 Création de l'environnement virtuel (.venv)..."
  python3 -m venv .venv
fi

# 3) Activate venv
# shellcheck disable=SC1091
source ".venv/bin/activate"

# 4) Install deps
echo "📦 Installation / mise à jour des dépendances..."
python -m pip install --upgrade pip >/dev/null
pip install -r requirements.txt

# 5) Create .env
if [ ! -f ".env" ] && [ -f ".env.template" ]; then
  echo "🧩 Aucun .env détecté, création à partir de .env.template..."
  cp .env.template .env
  echo "👉 Ouvrez .env et collez vos clés API avant utilisation."
fi

# 6) Run
echo
echo "▶️  Démarrage de l'application (Streamlit)..."
python -m streamlit run app.py
