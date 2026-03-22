#!/bin/bash
cd "$(dirname "$0")"
mkdir -p outputs
LOG="outputs/streamlit_macos.log"
if [ ! -d ".venv" ]; then
  ./setup_macos.sh
  exit $?
fi
nohup ".venv/bin/python" -m streamlit run app.py --server.port 8501 --server.headless true --browser.gatherUsageStats=false > "$LOG" 2>&1 &
sleep 2
open "http://localhost:8501" >/dev/null 2>&1 || true
echo "CoDIR IA lance : http://localhost:8501"
