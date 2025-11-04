#!/usr/bin/env bash
# CoDIR IA - Lancement (macOS/Linux) - DEV
# Usage: chmod +x launch_dev.sh && ./launch_dev.sh

set -euo pipefail

cd "$(dirname "$0")"

echo "=========================================="
echo "  👨‍💻 CoDIR IA - Mode Développement"
echo "=========================================="
echo

# venv obligatoire en mode dev
if [ ! -f "venv/bin/activate" ]; then
  echo "❌ venv introuvable."
  echo "   Créez-le d'abord :"
  echo "     python3 -m venv venv"
  echo "     source venv/bin/activate"
  echo "     pip install -r requirements.txt"
  exit 1
fi

# shellcheck disable=SC1091
source "venv/bin/activate"

echo "▶️  Lancement Streamlit (dev)..."
if command -v streamlit >/dev/null 2>&1; then
  streamlit run app.py
else
  python -m streamlit run app.py
fi
