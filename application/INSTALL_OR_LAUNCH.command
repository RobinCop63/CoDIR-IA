#!/bin/bash
# =============================================================================
# CoDIR IA v16.5.76 — INSTALL_OR_LAUNCH.command
# v62.12.8.3: standard CPython accepted (9.4.65: 3.11–3.13 on macOS, 3.14 refused by the probe); free-threaded builds rejected.
# =============================================================================

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
export CODIR_CONFIG_DIR="$HOME/Library/Application Support/CoDIR-IA"
export CODIR_CACHE_DIR="$CODIR_CONFIG_DIR/cache"
export CODIR_DATA_DIR="$CODIR_CONFIG_DIR/data"
mkdir -p "$CODIR_CONFIG_DIR" "$CODIR_CACHE_DIR" "$CODIR_DATA_DIR"

GREEN="\033[92m"; RED="\033[91m"; YELLOW="\033[93m"; BLUE="\033[94m"; BOLD="\033[1m"; END="\033[0m"

chmod +x "$0" 2>/dev/null || true
[ -f "setup_macos.sh" ] && chmod +x "setup_macos.sh" 2>/dev/null || true
[ -f "scripts/python_runtime_select.sh" ] && chmod +x "scripts/python_runtime_select.sh" 2>/dev/null || true
if [ -d "CoDIR IA.app" ]; then
    chmod +x "CoDIR IA.app/Contents/MacOS/CoDIR_IA_Launcher" 2>/dev/null || true
fi

echo ""
echo "============================================================"
echo "  🎯 CoDIR IA v17.0 — build v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65"
echo "  Installation et lancement automatiques"
echo "============================================================"
echo ""

PROBE="$DIR/scripts/python_runtime_probe.py"
if [ ! -f "$PROBE" ]; then
    echo -e "${RED}❌ Sonde de compatibilité Python introuvable : $PROBE${END}"
    read -p "Appuyez sur Entrée pour fermer..." _
    exit 2
fi

# 9.4.65 — décision de l'éditeur du 20/10 : CoDIR IA v17.0 est réservé aux Mac à puce Apple (M1 et suivants).
if [ "$(uname -m)" = "x86_64" ] && [ "$(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)" != "1" ]; then
    echo -e "${RED}❌ Mac Intel détecté : CoDIR IA v17.0 est réservé aux Mac à puce Apple (M1 et suivants).${END}"
    echo "   Une dépendance du verrou, cryptography 50, ne publie plus de version pour les Mac Intel."
    read -p "Appuyez sur Entrée pour fermer..." _
    exit 3
fi

# A compatible existing venv is authoritative; the host Python is irrelevant.
if [ -x ".venv/bin/python" ] && [ -x ".venv/bin/streamlit" ]; then
    if .venv/bin/python "$PROBE" >/dev/null 2>&1; then
        READY=1
    else
        echo -e "${YELLOW}⚠  L'environnement Python existant est incompatible ; réparation automatique.${END}"
        READY=0
    fi
else
    READY=0
fi

if [ "$READY" -ne 1 ]; then
    echo -e "${BOLD}Première utilisation ou réparation détectée.${END}"
    echo "CoDIR IA recherche un CPython standard 3.11 à 3.13."
    echo "Python 3.11 ou 3.12 reste recommandé ; les variantes free-threading/no-GIL sont refusées."
    echo ""
    echo "============================================================"
    bash setup_macos.sh
    INSTALL_RC=$?
    echo "============================================================"
    if [ "$INSTALL_RC" -ne 0 ]; then
        echo ""
        echo -e "${RED}❌ L'installation a rencontré un problème.${END}"
        echo "   Log détaillé : ~/Library/Application Support/CoDIR-IA/logs/setup_macos.log"
        echo ""
        read -p "Appuyez sur Entrée pour fermer..." _
        exit "$INSTALL_RC"
    fi
    # setup_macos.sh launches Streamlit itself. Ensure the Desktop app is also
    # Since v16.5.75.5 — Desktop shortcut also created on first install.
    APP_NAME="CoDIR IA.app"
    DESKTOP="$HOME/Desktop"
    if [ -d "$DIR/$APP_NAME" ] && [ -d "$DESKTOP" ] && [ ! -d "$DESKTOP/$APP_NAME" ]; then
        cp -r "$DIR/$APP_NAME" "$DESKTOP/$APP_NAME" 2>/dev/null || true
    fi
    exit 0
fi

echo -e "${GREEN}✓${END} Installation détectée — lancement de CoDIR IA..."
echo ""
mkdir -p outputs

APP_NAME="CoDIR IA.app"
DESKTOP="$HOME/Desktop"
if [ -d "$DIR/$APP_NAME" ] && [ -d "$DESKTOP" ] && [ ! -d "$DESKTOP/$APP_NAME" ]; then
    cp -r "$DIR/$APP_NAME" "$DESKTOP/$APP_NAME" 2>/dev/null || true
    echo -e "${GREEN}✓${END} Raccourci Bureau créé : $DESKTOP/$APP_NAME"
fi

echo "============================================================"
echo "  CoDIR IA démarre — navigateur : http://localhost:8501"
echo "  Fermez cette fenêtre ou Ctrl+C pour arrêter CoDIR IA"
echo "============================================================"
echo ""

export CODIR_PARSE_ENGINE="${CODIR_PARSE_ENGINE:-thread}"
.venv/bin/streamlit run app.py \
    --server.headless false \
    --browser.gatherUsageStats false \
    --server.port 8501 \
    --logger.level error &
_CODIR_PID=$!
trap 'kill "$_CODIR_PID" 2>/dev/null' INT TERM HUP EXIT
wait "$_CODIR_PID"
