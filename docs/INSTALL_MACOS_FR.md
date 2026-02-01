# Installation macOS (CoDIR IA v16.0)

## 2 façons de lancer CoDIR IA

### Option A — Application macOS (.app) (recommandé pour les releases)
Si vous utilisez une **release macOS** (archive distribuée), vous verrez `CoDIR-IA.app`.

✅ **Vous pouvez déplacer l'application dans Applications et/ou la mettre dans le Dock** : elle reste fonctionnelle.

**Important (dossier de travail)**
- Au premier lancement, l'application crée (ou met à jour) un dossier de travail dans :
  - `~/CoDIR-IA/CoDIR-IA-main`
- C'est dans ce dossier que seront créés : `.venv`, `.env` et vos fichiers `outputs/`.
- Vos clés API se configurent dans : `~/CoDIR-IA/CoDIR-IA-main/.env`

Au premier lancement, macOS peut bloquer l’app (Gatekeeper) :
1. Double-cliquez sur `CoDIR-IA.app`
2. Si macOS bloque : **clic droit → Ouvrir → Ouvrir**
   - Alternative : **Réglages Système → Confidentialité et sécurité → Ouvrir quand même**

Ensuite, les fois suivantes : double-clic sur `CoDIR-IA.app`.

### Option B — Lancement via script (.command ou bash)
Dans le dossier dézippé (release) :
- Double-cliquez sur `CoDIR-IA.command` (une fois autorisé par macOS)

Ou, depuis le dossier du projet (source) :
```bash
chmod +x mac/launch_user.sh
./mac/launch_user.sh
```

## Configuration des clés API
Au premier lancement, un fichier `.env` est créé automatiquement (copie de `.env.template`).
Ouvrez `.env` et renseignez **uniquement** les clés dont vous avez besoin.

👉 Si vous lancez via l’application `.app`, le fichier est ici : `~/CoDIR-IA/CoDIR-IA-main/.env`

💡 `.env` est un fichier cache sur macOS. Dans Finder : `Cmd + Shift + .`

Au premier lancement via l'application `.app`, CoDIR IA ouvre aussi `.env` dans TextEdit et cree un fichier visible `ENV_LOCATION.txt` (dans le meme dossier) qui rappelle le chemin.

## Depannage rapide
- **python3 introuvable** : installez Python 3.10+ (python.org) puis relancez.
- **Permission denied** : relancez après `chmod +x mac/launch_user.sh`.
- **Bloqué par macOS** : clic droit → Ouvrir (une seule fois).
