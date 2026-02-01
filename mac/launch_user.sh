#!/usr/bin/env bash
# CoDIR IA - Lancement (macOS/Linux) - PUBLIC
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

# 0) Ensure .env exists early (so user can paste API keys before the first install)
if [ ! -f ".env" ]; then
  if [ -f ".env.template" ]; then
    echo "🧩 Aucun .env détecté, création à partir de .env.template..."
    cp .env.template .env
    echo "👉 Ouvrez .env et collez vos clés API avant utilisation."
  elif [ -f ".env.example" ]; then
    echo "🧩 Aucun .env détecté, création à partir de .env.example..."
    cp .env.example .env
    echo "👉 Ouvrez .env et collez vos clés API avant utilisation."
  else
    echo "🧩 Aucun modèle .env trouvé, création d'un .env minimal..."
    cat > .env <<'EOF'
# CoDIR IA - Environment variables
# Paste your API keys below
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
MISTRAL_API_KEY=
EOF
    echo "👉 Ouvrez .env et collez vos clés API avant utilisation."
  fi
fi

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

# 5) Run
echo
echo "▶️  Démarrage de l'application (Streamlit)..."
python -m streamlit run app.py
