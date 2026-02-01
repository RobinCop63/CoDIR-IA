# CoDIR IA v16.0 — Windows + macOS (Double-click launch)

CoDIR IA = un “CoDIR augmenté” (plusieurs IA) pour structurer une décision, challenger une analyse, produire une synthèse actionnable (dirigeants, managers de transition, consultants).

✅ **Nouveauté v16.0 : lancement par double-clic + auto-création du .env** (Win & Mac)  
✅ **Setup ~5 minutes** (Python requis)  
✅ Choix du provider : **OpenAI / Gemini / Anthropic Claude / Mistral** (clé API perso)

---

## 🚀 Téléchargements (Assets)

- **Windows** : `CoDIR-IA-v16.0-windows-AUTOENV-REVIEWED-CLEAN-LICENSE2025-2026.zip`
- **macOS** : `CoDIR-IA-v16.0-macOS-DOCKREADY-AUTOENV-REVIEWED-CLEAN-LICENSE2025-2026-PAYLOADSYNC.zip`

> Le repo GitHub contient le **code source + la documentation**.  
> Les zips ci-dessus sont les **packages prêts à l’emploi** (Release assets).

---

## ✨ Highlights (v16.0)

- **Double-clic pour lancer** (Windows + macOS)
- **Auto-création / assistance .env** : tu peux renseigner tes clés sans te battre avec les fichiers cachés
- **Multi-IA / multi-providers** : tu choisis ton modèle et ton fournisseur
- **Approche “pro”** : cadre d’usage, confidentialité, responsabilité utilisateur

---

## 🧩 Ce dont tu as besoin

- **Python 3.x** installé
- Une ou plusieurs clés API (au choix) :
  - `OPENAI_API_KEY`
  - `GOOGLE_API_KEY` (Gemini)
  - `ANTHROPIC_API_KEY` (Claude)
  - `MISTRAL_API_KEY`

---

## ⚙️ Installation — en 60 secondes

### Windows
1. Télécharge `CoDIR-IA-v16.0-windows-AUTOENV-REVIEWED-CLEAN-LICENSE2025-2026.zip` et dézippe
2. **Premier lancement** : double-clique `setup_windows.bat` (installation)
3. **Ensuite (usage normal)** : double-clique `launch_codir.bat` (lancement)
4. À la première exécution, saisis tes clés quand on te le propose
5. L’app s’ouvre dans ton navigateur (Streamlit)

### macOS
1. Télécharge `CoDIR-IA-v16.0-macOS-DOCKREADY-AUTOENV-REVIEWED-CLEAN-LICENSE2025-2026-PAYLOADSYNC.zip` et dézippe
2. Double-clique `CoDIR_IA.command` (ou le lanceur fourni)
3. À la première exécution, saisis tes clés quand on te le propose
4. L’app s’ouvre dans ton navigateur (Streamlit)

> Si macOS bloque le fichier : clic droit → **Ouvrir**, puis autorise l’exécution.

---

## 🔐 Confidentialité & données (à lire avant usage)

- CoDIR IA s’exécute **localement** sur ta machine.
- **Les réponses sont générées via ton provider** : toute requête envoyée à une IA **part chez le fournisseur** correspondant (OpenAI / Google / Anthropic / Mistral), selon ta configuration.
- **Ne colle jamais** de données sensibles/confidentielles que tu n’es pas autorisé à partager.
- Les clés API restent dans ton `.env` local (non envoyé sur GitHub).

📄 Voir : **Conditions d’utilisation** + **Privacy / Data** dans le repo.

---

## 🧠 Modèles par défaut (facile à changer)

- OpenAI : `gpt-4.1-mini` (ou ton choix)
- Gemini : `gemini-2.5-flash`
- Claude : `claude-sonnet-4-5`
- Mistral : `mistral-small` (ou autre)

Tu peux modifier ces valeurs dans le `.env`.

---

## 🧯 Known issues (problèmes connus)

- **Premier lancement plus long** : création du venv + installation des dépendances.
- **macOS Gatekeeper** peut bloquer les scripts `.command` → utiliser “Ouvrir” (clic droit).
- En environnement entreprise (proxy / restrictions), l’installation des dépendances peut échouer :
  - solution : réseau perso / hotspot, ou config proxy pip.
- Si un provider n’est pas configuré (clé manquante), CoDIR IA bascule sur ceux disponibles.

Si tu bloques : ouvre une issue (ou DM sur LinkedIn) avec :
- OS (Win/macOS + version)
- message d’erreur complet
- contenu du fichier log si présent

---

## 🗺️ Roadmap

### v16.1 (patch rapide)
- Amélioration messages d’erreur + diagnostic (proxy, python, dépendances)
- Ajustements UX (sidebar, presets, texte d’aide)
- Stabilisation scripts de lancement + logs plus explicites

### v17 (feature release)
- **Pièces jointes / contexte temporaire** (upload de documents utilisés comme contexte pour les IA capables de les lire)
- Meilleure gestion des sessions / historiques (optionnel)
- “Provider health check” (test automatique des clés + modèle)
- Améliorations performance & packaging léger (sans “usine à gaz”)

---

## 🌟 Aide & feedback

✅ Tu testes ?  
1) Dis-moi ton OS (Win/Mac)  
2) Ton provider (OpenAI/Gemini/Claude/Mistral)  
3) 1 feedback (même court)

Merci à toutes celles et ceux qui testent et challengent CoDIR IA 🙏

---

# ENGLISH (quick summary)

## CoDIR IA v16.0 — Windows + macOS (Double-click launch)

CoDIR IA is a “multi-AI committee” to structure decisions, challenge assumptions and produce actionable executive summaries.

**v16.0 highlights**
- Double-click launch (Win & Mac)
- Auto `.env` creation / setup helper
- Multi-provider: OpenAI / Gemini / Claude / Mistral (your own API keys)
- Runs locally; requests go to the selected provider when you generate responses

**Downloads**
- Windows: `CoDIR-IA-v16.0-windows-AUTOENV-REVIEWED-CLEAN-LICENSE2025-2026.zip` (first run: `setup_windows.bat`, then `launch_codir.bat`)
- macOS: `CoDIR-IA-v16.0-macOS-DOCKREADY-AUTOENV-REVIEWED-CLEAN-LICENSE2025-2026-PAYLOADSYNC.zip`

**Requirements**
- Python 3.x
- API key(s): OPENAI / GOOGLE / ANTHROPIC / MISTRAL

**Known issues**
- First run may take longer (venv + deps)
- macOS Gatekeeper may require right-click → Open
- Corporate proxies may block pip installs

**Roadmap**
- v16.1: diagnostics, UX polish, launcher stability
- v17: attachments / temporary context, session options, provider health check
