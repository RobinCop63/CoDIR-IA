#!/bin/bash
# CoDIR IA v16.0 - macOS launcher (.command)
# Double-clickable from Finder once allowed by macOS Gatekeeper.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Candidates for launch_user.sh (support several package layouts)
CANDIDATES=(
  "$SCRIPT_DIR/mac/launch_user.sh"
  "$SCRIPT_DIR/CoDIR-IA-main/mac/launch_user.sh"
  "$SCRIPT_DIR/dist/macos/CoDIR-IA-main/mac/launch_user.sh"
  "$SCRIPT_DIR/dist/windows/CoDIR-IA-main/mac/launch_user.sh"
)

LAUNCH=""
for c in "${CANDIDATES[@]}"; do
  if [ -f "$c" ]; then
    LAUNCH="$c"
    break
  fi
done

# Fallback: search (max depth 6)
if [ -z "$LAUNCH" ]; then
  FOUND=$(find "$SCRIPT_DIR" -maxdepth 6 -type f -name "launch_user.sh" 2>/dev/null | head -n 1 || true)
  if [ -n "$FOUND" ]; then
    LAUNCH="$FOUND"
  fi
fi

if [ -z "$LAUNCH" ]; then
  echo "❌ ERREUR: launch_user.sh introuvable."
  echo "Attendu (exemples):"
  echo "  - ./mac/launch_user.sh"
  echo "  - ./CoDIR-IA-main/mac/launch_user.sh"
  echo "  - ./dist/macos/CoDIR-IA-main/mac/launch_user.sh"
  echo
  echo "📁 Contenu du dossier courant:" 
  ls -la "$SCRIPT_DIR" || true
  exit 1
fi

chmod +x "$LAUNCH" 2>/dev/null || true
"$LAUNCH"
