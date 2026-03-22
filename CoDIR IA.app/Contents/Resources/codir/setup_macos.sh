#!/bin/bash
# ======================================================
# CoDIR IA v16.3.3.22 — macOS Setup (quiet UI + full logs)
# ======================================================

set -e
cd "$(dirname "$0")"

# Log destination: if launched from .app, CODIR_LOG_DIR points to user logs folder
LOG_DIR="${CODIR_LOG_DIR:-$(pwd)/outputs}"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/setup_macos.log"

mkdir -p outputs

log() { echo "$@" | tee -a "$LOG" >/dev/null; }

# Header
{
  echo ""
  echo "===================================="
  echo " CoDIR IA v16.3.3.22 - Installation"
  echo "===================================="
  echo ""
  echo "Date: $(date)"
  echo "Folder: $(pwd)"
  echo "Python3: $(command -v python3 || echo 'NOT FOUND')"
  echo ""
} > "$LOG"

echo ""
echo "===================================="
echo " CoDIR IA v16.3.3.22 - Installation"
echo "===================================="
echo ""

echo "[1/5] Verification de Python3..."
# Prefer Python >= 3.10 for Gemini (google-genai recent versions require >=3.10)
choose_python() {
  local cand
  local cands=(
    "python3.12" "python3.11" "python3.10"
    "/usr/local/bin/python3.12" "/usr/local/bin/python3.11" "/usr/local/bin/python3.10" "/usr/local/bin/python3"
    "/opt/homebrew/bin/python3.12" "/opt/homebrew/bin/python3.11" "/opt/homebrew/bin/python3.10" "/opt/homebrew/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.10/bin/python3"
    "python3"
  )
  for cand in "${cands[@]}"; do
    if command -v "$cand" >/dev/null 2>&1; then
      ver="$($cand -c 'import sys;print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || true)"
      major="${ver%%.*}"
      minor="${ver##*.}"
      if [[ "$major" == "3" ]] && [[ "$minor" =~ ^[0-9]+$ ]] && (( minor >= 10 )); then
        echo "$cand"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON_BIN="$(choose_python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  if ! command -v python3 >/dev/null 2>&1; then
    log "[ERREUR] python3 introuvable."
    log "Installe Python 3.11+ (recommande: python.org) puis relance."
  else
    pyver="$(python3 -c 'import sys;print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo "0.0")"
    log "[ERREUR] Python detecte ($pyver) est trop ancien pour activer toutes les IA (Gemini requiert Python >= 3.10)."
  fi
  # Default behaviour: guide user to install/upgrade Python
  /usr/bin/osascript -e 'display dialog "CoDIR IA nécessite Python 3.10+ (recommandé: Python 3.11 ou 3.12) pour activer toutes les IA, dont Gemini.\n\nClique OK pour ouvrir python.org, installe Python, puis relance CoDIR IA." buttons {"OK"} default button "OK" with icon caution' >/dev/null 2>&1 || true
  /usr/bin/open "https://www.python.org/downloads/macos/" >/dev/null 2>&1 || true
  exit 1
fi

log "Python choisi: $PYTHON_BIN"
$PYTHON_BIN --version >> "$LOG" 2>&1 || true

echo "[2/5] Creation de l'environnement virtuel (.venv)..."
if [ ! -x ".venv/bin/python" ]; then
  "$PYTHON_BIN" -m venv .venv >> "$LOG" 2>&1
fi

PY="$(pwd)/.venv/bin/python"

echo "[3/5] Installation des dependances..."
# Ensure pip exists even on some minimal python installs
"$PY" -m ensurepip --upgrade >> "$LOG" 2>&1 || true
"$PY" -m pip install --upgrade pip setuptools wheel >> "$LOG" 2>&1

# Install requirements with retries (network hiccups / mirrors)
REQ_OK=0
for attempt in 1 2 3; do
  echo "    - pip install (tentative $attempt/3)"
  if "$PY" -m pip install --upgrade --no-cache-dir -r requirements.txt >> "$LOG" 2>&1; then
    REQ_OK=1
    break
  fi
  sleep 1
done
if [ "$REQ_OK" -ne 1 ]; then
  log "[ERREUR] pip install a echoue."
  # Put a short hint in the log for typical macOS causes
  log "Causes frequentes: certificats SSL Python, proxy d'entreprise, python incomplet."
  exit 1
fi

echo "[4/5] Creation de l'app/raccourci (Finder)..."
if [ -x "mac/create_app.sh" ]; then
  bash "mac/create_app.sh" >> "$LOG" 2>&1 || true
fi

echo "[5/5] Finalisation..."
# Do not autostart when called from the .app launcher
if [ -z "$CODIR_NO_AUTOSTART" ]; then
  chmod +x CoDIR-IA.command >/dev/null 2>&1 || true
  ./CoDIR-IA.command >> "$LOG" 2>&1 || true
fi

echo ""
echo "[OK] Setup termine."
