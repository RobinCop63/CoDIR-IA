#!/bin/bash
# ============================================
# CoDIR IA v16.3.3.22 — Create macOS App Bundle
# ============================================
# Ce script crée une application .app pour le Dock
# Usage: ./mac/create_app.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
APP_NAME="CoDIR IA"
APP_PATH="$HOME/Applications/$APP_NAME.app"

echo ""
echo "===================================="
echo " Création de l'application macOS"
echo "===================================="
echo ""

# Créer la structure .app
mkdir -p "$APP_PATH/Contents/MacOS"
mkdir -p "$APP_PATH/Contents/Resources"

# Créer le script exécutable
cat > "$APP_PATH/Contents/MacOS/CoDIR-IA" << LAUNCHER
#!/bin/bash
cd "$PROJECT_DIR"
source venv/bin/activate 2>/dev/null || python3 -m venv venv && source venv/bin/activate
streamlit run app.py
LAUNCHER
chmod +x "$APP_PATH/Contents/MacOS/CoDIR-IA"

# Créer Info.plist
cat > "$APP_PATH/Contents/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>CoDIR-IA</string>
    <key>CFBundleIdentifier</key>
    <string>com.higestion.codir-ia</string>
    <key>CFBundleName</key>
    <string>CoDIR IA</string>
    <key>CFBundleDisplayName</key>
    <string>CoDIR IA</string>
    <key>CFBundleVersion</key>
    <string>16.3.3.22</string>
    <key>CFBundleShortVersionString</key>
    <string>16.3.3.22</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
</dict>
</plist>
PLIST

# Copier l'icône si disponible
if [ -f "$PROJECT_DIR/assets/macos/AppIcon.icns" ]; then
    cp "$PROJECT_DIR/assets/macos/AppIcon.icns" "$APP_PATH/Contents/Resources/AppIcon.icns"
fi

echo "[OK] Application créée : $APP_PATH"
echo ""
echo "Vous pouvez maintenant :"
echo "  1. Glisser '$APP_NAME' dans le Dock"
echo "  2. Double-cliquer pour lancer CoDIR IA"
echo ""

# Ouvrir le dossier Applications
open "$HOME/Applications"
