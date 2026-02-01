# Confidentialité / Privacy (CoDIR IA)

## FR
- CoDIR IA s’exécute **localement** sur votre machine (Streamlit).
- CoDIR IA ne met pas en place de serveur distant côté projet.
- Les fichiers de sortie éventuels sont écrits **localement** (dossier `outputs/`).
- Lorsque vous utilisez un fournisseur (OpenAI / Anthropic / Google / Mistral), vos prompts et le contexte sont **envoyés au fournisseur**. La conservation et l’usage de ces données dépendent de **leurs** conditions.

Recommandations :
- Évitez d’envoyer des données sensibles sans validation interne.
- Utilisez des clés API dédiées et révocables.
- Limitez les droits et quotas côté fournisseurs.

## EN
- CoDIR IA runs **locally** on your machine (Streamlit).
- The project does not operate a remote CoDIR IA server.
- Optional exports are written **locally** (`outputs/`).
- When you use a provider (OpenAI / Anthropic / Google / Mistral), prompts and context are **sent to that vendor**. Retention and usage depend on **their** policies.

Recommendations:
- Avoid sending sensitive data without internal approval.
- Use dedicated, revocable API keys.
- Set quotas/limits on vendor accounts.
