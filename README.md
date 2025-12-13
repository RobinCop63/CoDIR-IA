# CoDIR-IA – Orchestrateur Multi-IA pour décideurs
Version 2025-12-15 – Windows & macOS

Un outil simple, local, et polyvalent pour orchestrer plusieurs IA (OpenAI, Anthropic Claude, Google Gemini, Mistral) au service des dirigeants, DAF, PMO et consultants.

## 🚀 Fonctionnalités principales
- Interface locale (Streamlit)
- Multi-fournisseurs IA (OpenAI, Claude 4.5, Gemini, Mistral…)
- Prompts de rôle intégrés
- Chargement automatique des clés API via `.env`
- Compatible Windows & macOS
- Aucun stockage des données

## 🖥️ Installation Windows
1. Télécharger le dossier `win/`.
2. Extraire sur le Bureau.
3. Lancer `launch_codir.bat`.
4. Un fichier `.env` est créé automatiquement.

## 🍎 Installation macOS
1. Télécharger le dossier `mac/`.
2. Extraire sur le Bureau.
3. Dans le Terminal :
   ```bash
   chmod +x launch_user.sh
   ./launch_user.sh
   ```

## 🔑 Configuration des API Keys
Fichier `.env` :
```
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
MISTRAL_API_KEY=
```
Renseigner uniquement les clés souhaitées.

## 📦 Structure du projet
Voir dossier principal (win, mac, providers, engines, prompts).

## ▶️ Lancer CoDIR-IA
Windows : `launch_codir.bat`  
macOS : `./launch_user.sh`

## 🛡️ Confidentialité
Aucune donnée stockée ou transmise hors API des fournisseurs.

## 📄 Licence
MIT License.
