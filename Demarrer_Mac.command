#!/bin/bash
# CoDIR-IA — lanceur macOS (façade). Délègue au moteur situé dans application/.
# Premier double-clic = installation auto ; ensuite = lancement direct.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 9.4.65 — revue de publication du 18/10 (P03) : même contrôle d'intégrité que le lanceur Windows, avant tout lancement.
if [ ! -f "$DIR/SHA256SUMS" ]; then
  echo "[ERREUR] SHA256SUMS absent : impossible de vérifier l'intégrité de la distribution. Re-téléchargez le ZIP officiel."
  read -r -p "Appuyez sur Entrée pour fermer." _; exit 11
fi
if ! (cd "$DIR" && /usr/bin/shasum -a 256 -c --quiet SHA256SUMS); then
  echo "[ERREUR] Vérification d'intégrité échouée. Re-téléchargez le ZIP officiel."
  read -r -p "Appuyez sur Entrée pour fermer." _; exit 11
fi
export CODIR_CONFIG_DIR="$HOME/Library/Application Support/CoDIR-IA"
export CODIR_CACHE_DIR="$CODIR_CONFIG_DIR/cache"
export CODIR_DATA_DIR="$CODIR_CONFIG_DIR/data"
chmod +x "$DIR/application/INSTALL_OR_LAUNCH.command" 2>/dev/null
exec "$DIR/application/INSTALL_OR_LAUNCH.command"
