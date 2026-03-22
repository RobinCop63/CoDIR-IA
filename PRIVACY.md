# Politique de confidentialité — CoDIR IA v16.3.3.22

*Dernière mise à jour : Février 2026*

## 1. Principe fondamental
**CoDIR IA est une application locale.** Vos données restent sur votre machine. Aucune donnée n'est envoyée aux serveurs de CoDIR IA ou de son auteur.

## 2. Données stockées localement
- Clés API : `secrets.json` (hors repo)
- Paramètres : `settings.json`
- Logs & diagnostics : `outputs/` (sans clés API)
- Exports : `outputs/` (DOCX, PPTX)

Si un dossier de configuration est utilisé :
- Windows : `%APPDATA%\CoDIR-IA\`
- macOS/Linux : `~/.config/codir-ia/`

## 3. Données non stockées
CoDIR IA ne conserve pas :
- vos documents uploadés (traités puis supprimés de l’espace temporaire),
- un historique complet des sessions (sauf export explicite),
- vos clés API dans le dépôt Git.

## 4. Données transmises aux providers IA
Lors d’une session, les prompts (et éventuellement le texte extrait des pièces jointes) sont envoyés aux APIs des providers sélectionnés (OpenAI, Anthropic, Google, Mistral). Référez‑vous à leurs politiques respectives.

## 5. Sécurité des clés API
- Les clés sont stockées localement (ex: `secrets.json`) et ignorées par Git.
- Elles ne sont jamais affichées dans les logs.

## 6. Télémétrie
CoDIR IA **ne collecte aucune télémétrie**.

## 7. Contact
Questions : GitHub Issues (voir README).

---

# Privacy Policy — CoDIR IA v16.3.3.22

*Last updated: February 2026*

## 1. Core principle
**CoDIR IA is a local application.** Your data stays on your machine. No data is sent to CoDIR IA servers (there are none) or to the author.

## 2. Locally stored data
- API keys: `secrets.json` (outside the repo)
- Settings: `settings.json`
- Logs & diagnostics: `outputs/` (no API keys)
- Exports: `outputs/` (DOCX, PPTX)

If a config directory is used:
- Windows: `%APPDATA%\CoDIR-IA\`
- macOS/Linux: `~/.config/codir-ia/`

## 3. Data not stored
CoDIR IA does not keep:
- your uploaded files (processed then removed from temporary storage),
- full session history (unless you export),
- your API keys in the Git repository.

## 4. Data sent to AI providers
During a session, prompts (and optionally extracted attachment text) are sent to the selected providers’ APIs (OpenAI, Anthropic, Google, Mistral). Please consult their own policies.

## 5. API key security
- Keys are stored locally (e.g., `secrets.json`) and ignored by Git.
- Keys are never printed in logs.

## 6. Telemetry
CoDIR IA **does not collect telemetry**.

## 7. Contact
Questions: GitHub Issues (see README).
