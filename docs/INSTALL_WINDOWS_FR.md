# Installation Windows (CoDIR IA v16.0)

## Pré-requis
- Windows 10/11
- **Python 3.10+** installé (depuis python.org) et idéalement coché **"Add Python to PATH"**
- Connexion Internet (installation des dépendances + appels API)

## Installation (recommandée)
1. Téléchargez le dépôt (ou l’archive) et dézippez le dossier.
2. Dans le dossier du projet, **double-cliquez** sur : `setup_windows.bat`

Le script :
- crée l’environnement virtuel `.venv`
- installe les dépendances
- crée `.env` à partir de `.env.template` (si absent)
- **ouvre automatiquement `.env` dans le Bloc-notes** si aucune clé API n’est renseignée
- crée un **raccourci sur le Bureau** (icône CoDIR IA)

## Premier lancement
- Lancez via l’icône **CoDIR IA** sur le Bureau (ou `launch_codir.bat`).
- Si aucune clé API n’est détectée, le script ouvre `.env` automatiquement.
- Sinon, vous pouvez ouvrir `.env` et coller vos clés API (OpenAI, Anthropic, Google, Mistral).

## Dépannage rapide
- **Python non détecté** : réinstallez Python et cochez "Add Python to PATH".
- **Erreur PowerShell raccourci** : lancez quand même `launch_codir.bat` (le raccourci est optionnel).
- **Dépendances** : supprimez `.venv` puis relancez `setup_windows.bat`.
