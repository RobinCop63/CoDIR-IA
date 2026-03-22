#!/bin/bash
# ======================================================
# CoDIR IA v16.3.3.22 — macOS Dev Launcher
# (foreground, with logs)
# ======================================================
cd "$(dirname "$0")/.."
mkdir -p outputs
LOG="outputs/streamlit_macos.log"

if [ ! -x ".venv/bin/python" ]; then
  echo "[INFO] .venv introuvable, lance d'abord setup_macos.command"
  exit 1
fi

".venv/bin/python" -m streamlit run app.py --server.port 8501 --browser.gatherUsageStats=false 2>&1 | tee "$LOG"
