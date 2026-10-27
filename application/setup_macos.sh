#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# CoDIR IA v16.5.76 — macOS setup script
# Installation guidée — confirmations explicites pour les actions de confiance
# ═══════════════════════════════════════════════════════════════════════
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
CONFIG_DIR="${CODIR_CONFIG_DIR:-$HOME/Library/Application Support/CoDIR-IA}"
export CODIR_CONFIG_DIR="$CONFIG_DIR"
export CODIR_CACHE_DIR="${CODIR_CACHE_DIR:-$CONFIG_DIR/cache}"
export CODIR_DATA_DIR="${CODIR_DATA_DIR:-$CONFIG_DIR/data}"
mkdir -p outputs "$CODIR_CACHE_DIR" "$CODIR_DATA_DIR"
chmod +x "$DIR/INSTALL_OR_LAUNCH.command" 2>/dev/null || true
LOG_DIR="$CONFIG_DIR/logs"
mkdir -p "$LOG_DIR"
chmod 700 "$CONFIG_DIR" "$LOG_DIR" 2>/dev/null || true
LOG="$LOG_DIR/setup_macos.log"
> "$LOG"
chmod 600 "$LOG" 2>/dev/null || true

RED='\033[0;31m'; GREEN='\033[0;32m'; GOLD='\033[0;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'

_log()  { echo "$(date '+%H:%M:%S') $*" >> "$LOG"; }
_ok()   { echo -e "  ${GREEN}✓${NC} $*"; _log "OK: $*"; }
_info() { echo -e "  ${CYAN}→${NC} $*"; _log "INFO: $*"; }
_warn() { echo -e "  ${GOLD}⚠${NC}  $*"; _log "WARN: $*"; }
_err()  { echo -e "  ${RED}✗${NC} $*"; _log "ERROR: $*"; }
_confirm() {
    local prompt="$1" reply
    printf "  %s [y/N] " "$prompt"
    read -r reply
    case "$reply" in y|Y|yes|YES|o|O|oui|OUI) return 0 ;; *) return 1 ;; esac
}

echo ""
echo -e "${BLUE}${BOLD}  CoDIR IA v17.0 — build v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65${NC}"
echo -e "${GOLD}  ─────────────────────────────────────────────${NC}"
echo ""

# ── Python runtime selection ─────────────────────────────────────────
PROBE_SCRIPT="$DIR/scripts/python_runtime_probe.py"
SELECTOR_SCRIPT="$DIR/scripts/python_runtime_select.sh"
if [ ! -f "$PROBE_SCRIPT" ] || [ ! -f "$SELECTOR_SCRIPT" ]; then
    _err "Sonde ou sélecteur Python absent du package."
    exit 2
fi
# shellcheck source=/dev/null
source "$SELECTOR_SCRIPT"

_py_version() {
    [ -n "${CODIR_PYTHON_BIN:-}" ] || { echo ""; return; }
    "$CODIR_PYTHON_BIN" -c "import platform; print(platform.python_version())" 2>/dev/null || echo ""
}

_install_python_312() {
    local BREW; BREW=$(_brew_exe)
    if [ -z "$BREW" ]; then
        _warn "Homebrew est absent. Son installateur officiel sera téléchargé puis exécuté."
        _info "URL : https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"
        if ! _confirm "Autoriser cette installation Homebrew ?"; then
            _warn "Installation Homebrew refusée par l’utilisateur."
            return 1
        fi
        _info "Installation Homebrew autorisée..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
            >> "$LOG" 2>&1 || return 1
        BREW=$(_brew_exe)
        [ -n "$BREW" ] && eval "$($BREW shellenv)" >> "$LOG" 2>&1
    fi
    [ -n "$BREW" ] || return 1
    _info "Installation de Python 3.12 standard via Homebrew..."
    "$BREW" install python@3.12 --quiet >> "$LOG" 2>&1 \
        || "$BREW" upgrade python@3.12 --quiet >> "$LOG" 2>&1 \
        || true
    local BPFX; BPFX=$($BREW --prefix)
    export PATH="$BPFX/opt/python@3.12/bin:$BPFX/bin:$PATH"
    return 0
}

_brew_exe() {
    local bp
    for bp in "/opt/homebrew/bin/brew" "/usr/local/bin/brew"; do
        [ -f "$bp" ] && { echo "$bp"; return; }
    done
    echo ""
}

# [1/6] PYTHON ──────────────────────────────────────────────────────
echo -e "${BOLD}[1/6]${NC} Python..."
if codir_select_python "$PROBE_SCRIPT" "$LOG"; then
    _ok "Python $CODIR_PYTHON_VERSION standard détecté ($CODIR_PYTHON_BIN)"
else
    _warn "Aucun CPython standard compatible 3.11 à 3.13 trouvé."
    [ -n "${CODIR_PYTHON_REJECTIONS:-}" ] && _info "$CODIR_PYTHON_REJECTIONS"
    _install_python_312 || true
    if ! codir_select_python "$PROBE_SCRIPT" "$LOG"; then
        _err "Impossible d'installer ou de sélectionner Python 3.12 standard."
        open "https://www.python.org/downloads/macos/" 2>/dev/null || true
        exit 1
    fi
    _ok "Python $CODIR_PYTHON_VERSION standard installé ($CODIR_PYTHON_BIN)"
fi
_log "Python : $CODIR_PYTHON_VERSION — $CODIR_PYTHON_BIN"

# [2/6] VENV ────────────────────────────────────────────────────────
echo -e "${BOLD}[2/6]${NC} Environnement virtuel..."
if [ -x ".venv/bin/python" ]; then
    if ! .venv/bin/python "$PROBE_SCRIPT" >/dev/null 2>&1; then
        _info "Venv incompatible — reconstruction..."
        rm -rf .venv
    else
        VENV_EXE=$(.venv/bin/python -c 'import sys; print(sys.executable)' 2>/dev/null || true)
        SELECTED_EXE=$("$CODIR_PYTHON_BIN" -c 'import sys; print(sys.executable)' 2>/dev/null || true)
        VENV_MM=$(.venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)
        SELECTED_MM=$("$CODIR_PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)
        if [ -n "$VENV_MM" ] && [ "$VENV_MM" != "$SELECTED_MM" ]; then
            _info "Python changé ($VENV_MM → $SELECTED_MM) — reconstruction du venv..."
            rm -rf .venv
        fi
    fi
fi
if [ ! -d ".venv" ]; then
    "$CODIR_PYTHON_BIN" -m venv .venv >> "$LOG" 2>&1 || { _err "Échec création du venv."; exit 1; }
    _ok ".venv créé avec Python $CODIR_PYTHON_VERSION"
else
    _ok ".venv présent"
fi

# [3/6] DÉPENDANCES ─────────────────────────────────────────────────
_install_dependencies_binary_only() {
    local ok=0
    .venv/bin/pip install --upgrade pip setuptools wheel -q >> "$LOG" 2>&1 || true
    if [ -f requirements.lock ]; then
        echo "[install] Mode verrouillé requirements.lock." >> "$LOG" 2>&1
        .venv/bin/pip install --only-binary=:all: -r requirements.lock -q >> "$LOG" 2>&1 && ok=1
    fi
    if [ "$ok" -ne 1 ]; then
        echo "[install] Repli requirements.txt, wheels binaires uniquement." >> "$LOG" 2>&1
        .venv/bin/pip install --only-binary=:all: --upgrade -r requirements.txt -q >> "$LOG" 2>&1 && ok=1
        # v62.13.9.4.33 — repli EXPLICITE : l'environnement obtenu diffère du lock et du SBOM
        if [ "$ok" -eq 1 ]; then
            echo "[install] ATTENTION : environnement de REPLI (requirements.txt) — il diffère de requirements.lock et du SBOM ; à signaler au support avant usage professionnel" >> "$LOG" 2>&1
            echo "fallback requirements.txt" > .venv/INSTALL_MODE.txt
            echo -e "${BOLD}ATTENTION${NC} : dépendances installées en mode REPLI (voir le journal) — environnement non verrouillé."
        fi
    else
        echo "locked requirements.lock" > .venv/INSTALL_MODE.txt
    fi
    [ "$ok" -eq 1 ]
}

echo -e "${BOLD}[3/6]${NC} Dépendances..."
if ! _install_dependencies_binary_only; then
    case "${CODIR_PYTHON_VERSION:-}" in
        3.14.*)
            _warn "Un paquet binaire manque encore pour Python 3.14."
            _info "Repli automatique vers Python 3.12 standard..."
            echo "[install] Python 3.14 wheels incomplete - automatic fallback 3.12" >> "$LOG" 2>&1
            rm -rf .venv
            _install_python_312 || { _err "Installation du repli Python 3.12 impossible."; exit 1; }
            if ! codir_select_python "$PROBE_SCRIPT" "$LOG"; then
                _err "Python 3.12 standard reste introuvable après installation."
                exit 1
            fi
            case "${CODIR_PYTHON_VERSION:-}" in
                3.12.*) ;;
                *) _err "Le repli n'a pas sélectionné Python 3.12 standard."; exit 1 ;;
            esac
            "$CODIR_PYTHON_BIN" -m venv .venv >> "$LOG" 2>&1 || { _err "Échec création du venv Python 3.12."; exit 1; }
            _install_dependencies_binary_only || {
                _err "Dépendances indisponibles même avec Python 3.12 standard."
                _info "Journal : $LOG"
                exit 1
            }
            ;;
        *)
            _err "Dépendances indisponibles pour Python $CODIR_PYTHON_VERSION ou cette architecture."
            _info "Journal : $LOG"
            exit 1
            ;;
    esac
fi
_ok "Dépendances installées"

# [4/6] ICÔNE ───────────────────────────────────────────────────────
echo -e "${BOLD}[4/6]${NC} Icône CoDIR IA..."
ICON_SRC="$DIR/assets/macos/AppIcon.png"
ICON_DIST="$DIR/assets/macos/AppIcon.icns"
# 9.4.65 — vérification du 18/10 (R01) : les fichiers distribués sont couverts par SHA256SUMS et contrôlés par
# Demarrer_Mac.command à chaque lancement ; l'icône régénérée est donc écrite HORS de l'archive (configuration
# utilisateur), jamais par-dessus le fichier distribué, qui reste intact.
ICON_BUILD="$CONFIG_DIR/AppIcon.icns"
ICON_DEST="$ICON_DIST"

# Régénérer l ICNS depuis le PNG (garantit l icone correcte apres mise a jour)
if [ -f "$ICON_SRC" ] && command -v sips &>/dev/null && command -v iconutil &>/dev/null; then
    IS="$CONFIG_DIR/AppIcon.iconset"
    rm -rf "$IS" && mkdir -p "$IS"
    for s in 16 32 64 128 256 512; do
        sips -z $s $s "$ICON_SRC"             --out "$IS/icon_${s}x${s}.png"      >> "$LOG" 2>&1
        sips -z $((s*2)) $((s*2)) "$ICON_SRC" --out "$IS/icon_${s}x${s}@2x.png" >> "$LOG" 2>&1
    done
    if iconutil -c icns "$IS" -o "$ICON_BUILD" >> "$LOG" 2>&1; then
        ICON_DEST="$ICON_BUILD"
        _ok "AppIcon.icns regenere depuis le logo CoDIR IA (copie hors de l'archive)"
    fi
    rm -rf "$IS"
elif [ -f "$ICON_DIST" ]; then
    _ok "AppIcon.icns present (pre-genere)"
else
    _warn "Icone non disponible (sips/iconutil absents)"
fi

# [5/6] RACCOURCI BUREAU ────────────────────────────────────────────
echo -e "${BOLD}[5/6]${NC} Raccourci Bureau..."
APP_NAME="CoDIR IA.app"
APP_PATH="$DIR/$APP_NAME"
DESKTOP="$HOME/Desktop"
INSTALL_DIR="$DIR"

rm -rf "$APP_PATH"
mkdir -p "$APP_PATH/Contents/MacOS" "$APP_PATH/Contents/Resources"
[ -f "$ICON_DEST" ] && cp "$ICON_DEST" "$APP_PATH/Contents/Resources/AppIcon.icns"

cat > "$APP_PATH/Contents/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleExecutable</key><string>CoDIR_IA_Launcher</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundleIdentifier</key><string>com.higestion.codiria</string>
  <key>CFBundleName</key><string>CoDIR IA</string>
  <key>CFBundleDisplayName</key><string>CoDIR IA</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>16.5.76</string>
  <key>CFBundleShortVersionString</key><string>16.5.76</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

# 9.4.65 — contre-audit du 20/10 (R02) : le raccourci ouvre la façade racine Demarrer_Mac.command, qui vérifie
# SHA256SUMS avant tout lancement ; repli sur le lanceur interne seulement si la façade est absente.
ROOT_FACADE="$(cd "$INSTALL_DIR/.." && pwd)/Demarrer_Mac.command"
[ -f "$ROOT_FACADE" ] && chmod +x "$ROOT_FACADE" >> "$LOG" 2>&1 || true
cat > "$APP_PATH/Contents/MacOS/CoDIR_IA_Launcher" << LAUNCHER
#!/bin/bash
cd "$INSTALL_DIR"
[ ! -d ".venv" ] && osascript -e 'display alert "CoDIR IA" message "Installation incomplète.\nLancez INSTALL_OR_LAUNCH.command." as critical' && exit 1
mkdir -p outputs
if [ -f "$ROOT_FACADE" ]; then open -a Terminal "$ROOT_FACADE"; else open -a Terminal "$INSTALL_DIR/INSTALL_OR_LAUNCH.command"; fi
LAUNCHER
chmod +x "$APP_PATH/Contents/MacOS/CoDIR_IA_Launcher"

# Since v16.5.60 — chmod + quarantine sur INSTALL_OR_LAUNCH.command
# Sans ça, macOS bloque l'exécution avec "pas les privilèges nécessaires"
chmod +x "$DIR/INSTALL_OR_LAUNCH.command" >> "$LOG" 2>&1 || true
_ok "INSTALL_OR_LAUNCH.command : droits d'exécution configurés"

if [ -d "$DESKTOP" ]; then
    rm -rf "$DESKTOP/$APP_NAME"
    cp -r "$APP_PATH" "$DESKTOP/$APP_NAME"
    _ok "Raccourci copié sur le Bureau"
    _info "→ Glisser sur le Dock pour un accès permanent"
fi

if command -v xattr &>/dev/null; then
    _warn "macOS peut conserver un attribut de quarantaine sur les scripts et le raccourci non signés."
    if _confirm "Retirer la quarantaine uniquement sur les fichiers CoDIR IA de ce dossier ?"; then
        xattr -cr "$APP_PATH" >> "$LOG" 2>&1 || true
        xattr -d com.apple.quarantine "$DIR/INSTALL_OR_LAUNCH.command" >> "$LOG" 2>&1 || true
        [ -d "$DESKTOP/$APP_NAME" ] && xattr -cr "$DESKTOP/$APP_NAME" >> "$LOG" 2>&1 || true
        _ok "Quarantaine retirée sur les seuls éléments CoDIR IA autorisés"
    else
        _warn "Quarantaine conservée. macOS pourra demander une ouverture manuelle via clic droit > Ouvrir."
    fi
fi

# [6/6] VÉRIFICATION + LANCEMENT ────────────────────────────────────────
echo -e "${BOLD}[6/6]${NC} Vérification automatique + lancement..."
echo ""

# Since v16.5.67 — Streamlit a besoin d'être dans le venv ; vérifier d'abord
if [ ! -f ".venv/bin/streamlit" ]; then
    _warn "streamlit absent du venv — réinstallation des dépendances..."
    if [ -f requirements.lock ]; then
      echo "[install] Mode verrouille (requirements.lock) — reproductible." >> "$LOG" 2>&1
      if ! .venv/bin/pip install -r requirements.lock -q >> "$LOG" 2>&1; then
        echo "[install] AVERTISSEMENT: requirements.lock a echoue (incompatibilite plateforme/Python). Repli FLEXIBLE sur requirements.txt." >> "$LOG" 2>&1
        .venv/bin/pip install --upgrade -r requirements.txt -q >> "$LOG" 2>&1
      fi
    else
      echo "[install] requirements.lock absent — install flexible requirements.txt." >> "$LOG" 2>&1
      .venv/bin/pip install --upgrade -r requirements.txt -q >> "$LOG" 2>&1
    fi
fi

if [ ! -f ".venv/bin/streamlit" ]; then
    _err "Impossible de lancer CoDIR IA : streamlit introuvable."
    _info "Consultez le journal : $LOG"
    read -p "Appuyez sur Entrée pour fermer..."
    exit 1
fi

# ── Informations post-installation (AVANT le lancement Streamlit qui bloque) ─
echo ""
echo -e "${BLUE}${BOLD}  Clés API — Configuration${NC}"
echo "  Dossier de configuration : ~/Library/Application Support/CoDIR-IA"
echo "  Clés API                 : ~/Library/Application Support/CoDIR-IA/secrets.json"
echo "  Réglages et cible        : ~/Library/Application Support/CoDIR-IA/settings.json"
echo "  Journaux techniques      : ~/Library/Application Support/CoDIR-IA/logs"
echo "  Clés LLM requises   : OPENAI / ANTHROPIC / GOOGLE / MISTRAL / PERPLEXITY / GROK"
echo "  Clés optionnelles   : PAPPERS_API_KEY, COMPANIES_HOUSE_API_KEY, OPENSANCTIONS_API_KEY, SEC_EDGAR_USER_AGENT"
echo "  Note                : Companies House utilise 1 clé principale par défaut ; clé Document API distincte optionnelle (Since v16.5.70)."
echo "  Obtenir Pappers     : https://www.pappers.fr/api (100 crédits gratuits)"
echo ""

# ── Since v16.5.67 — Self-check unique : verify_installation.py est la source de vérité ─
# Couvre toute la suite pytest en interne + anti-drift + mini-run end-to-end.
# Remplace les anciens blocs de validation partielle qui traînaient depuis v16.5.51.
echo ""
echo "================================================================"
echo "  v17.0 — Vérification automatique de l'installation"
echo "================================================================"
if .venv/bin/python3 verify_installation.py; then
    _ok "Installation validée — CoDIR IA v17.0 build 9.4.65 opérationnelle"
else
    _warn "La vérification a détecté des problèmes — voir sortie ci-dessus"
    _info "Streamlit démarrera quand même, possiblement en mode dégradé"
fi
echo ""

echo -e "${GREEN}${BOLD}  Prêt ✓${NC}  http://localhost:8501  (Ctrl+C pour arrêter)"
echo ""
_log "Streamlit démarré"

# F.6.7.1 — Safe shutdown : enfant contrôlé, on n'arrête que ce process CoDIR-IA.
export CODIR_PARSE_ENGINE="${CODIR_PARSE_ENGINE:-thread}"
.venv/bin/streamlit run app.py \
    --server.headless false \
    --browser.gatherUsageStats false \
    --server.port 8501 \
    --logger.level error &
_CODIR_PID=$!
trap 'kill "$_CODIR_PID" 2>/dev/null' INT TERM HUP EXIT
wait "$_CODIR_PID"
