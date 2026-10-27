# Fournisseurs, sous-traitants et transferts / Providers, subprocessors and transfers

**Build :** `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`  
**Révision / Revision :** 18 octobre 2026 / 18 October 2026 — contenu inchangé depuis le 27 septembre 2026 / content unchanged since 27 September 2026 · CoDIR IA v17.0

## Français

Cette matrice décrit les connecteurs possibles et les valeurs actuellement documentées. L’activation, le rôle juridique, la région, la rétention et le mécanisme de transfert dépendent des fonctionnalités utilisées, du compte et du contrat de l’utilisateur. Confirmez les cases pour le déploiement réel avant de transmettre des données client. Les mentions « à confirmer » ne garantissent ni une absence de conservation ni un hébergement dans l’Union européenne.

Les transmissions dépendent des fonctionnalités activées et des exigences d’authentification propres à chaque service. Cette matrice ne constitue pas une garantie d’absence de tout appel réseau tant qu’aucune clé LLM n’est saisie. Vérifiez la configuration et les conditions du déploiement retenu.

| Fournisseur | Fonction | Données possibles | Activé par défaut, selon la documentation | Région / transfert à confirmer |
|---|---|---|---|---|
| OpenAI | modèles LLM | brief, extraits, instructions, contexte historique éventuellement repris | non, clé utilisateur | contrat du compte |
| Anthropic | modèles LLM (par défaut Claude Sonnet 5.5) | brief, extraits, instructions, contexte historique éventuellement repris | non | contrat du compte |
| Google / Gemini | modèles LLM | brief, extraits, instructions, contexte historique éventuellement repris | non | contrat du compte |
| Mistral AI (Paris, fournisseur européen) | modèles LLM — repli de dernier recours dans chaque rôle (`mistral-medium-latest`) | brief, extraits, instructions, contexte historique éventuellement repris | non | contrat du compte |
| Perplexity | modèle LLM et recherche — API Agent, modèle propre `perplexity/sonar` épinglé (aucun routage vers un modèle tiers) | brief, extraits, instructions, contexte historique éventuellement repris, requêtes | non | contrat du compte |
| xAI / Grok | modèle LLM | brief, extraits, instructions, contexte historique éventuellement repris | non | contrat du compte |
| Pappers | registre France ; finances des comptes déposés (dernier réalisé daté, exercices antérieurs) | SIREN, nom, requête | non | conditions Pappers |
| Companies House | registre UK ; historique des dépôts et derniers comptes iXBRL (API documents `document-api.company-information.service.gov.uk`) | numéro société | non, clé utilisateur | Royaume-Uni ; qualification transfert à documenter |
| GLEIF | LEI | identité juridique (aucun chiffre) | oui, dès qu'un LEI est renseigné — service ouvert, sans clé | service public mondial |
| SEC EDGAR | registre US ; montants XBRL des dépôts annuels (`data.sec.gov/api/xbrl/companyfacts`) | CIK, user-agent | oui, dès qu'un identifiant américain est renseigné — service ouvert, sans clé | États-Unis ; données de registre |
| OpenSanctions | conformité | identité, requête | non | contrat/configuration |

Aucun fournisseur ne doit être décrit comme sous-traitant « approuvé » sans vérification contractuelle. Les données sensibles ne doivent être envoyées qu’après validation du responsable de traitement. Cette matrice ne vaut ni approbation d’un fournisseur ni qualification de ses transferts.

## English

This matrix describes possible connectors and the currently documented values. Activation, legal role, region, retention and transfer mechanism depend on the features used, the user’s account and the applicable contract. Confirm the entries for the actual deployment before transmitting client data. “To confirm” entries guarantee neither zero retention nor European Union hosting.

Transmission depends on enabled features and on each service’s authentication requirements. This matrix does not guarantee that no network request occurs before an LLM key has been entered. Verify the selected deployment’s configuration and applicable terms.

| Provider | Function | Possible data | Enabled by default, as documented | Region / transfer to confirm |
|---|---|---|---|---|
| OpenAI | LLM models | brief, excerpts, instructions, history context where included | no; user key | account contract |
| Anthropic | LLM models (default Claude Sonnet 5.5) | brief, excerpts, instructions, history context where included | no | account contract |
| Google / Gemini | LLM models | brief, excerpts, instructions, history context where included | no | account contract |
| Mistral AI (Paris, European provider) | LLM models — last-resort fallback in every role (`mistral-medium-latest`) | brief, excerpts, instructions, history context where included | no | account contract |
| Perplexity | LLM model and search — Agent API, Perplexity's own `perplexity/sonar` model pinned (no routing to a third-party model) | brief, excerpts, instructions, history context where included, queries | no | account contract |
| xAI / Grok | LLM model | brief, excerpts, instructions, history context where included | no | account contract |
| Pappers | French registry; filed-accounts financials (last known dated figure, prior years) | SIREN, name, query | no | Pappers terms |
| Companies House | UK registry; filing history and latest iXBRL accounts (document API `document-api.company-information.service.gov.uk`) | company number | no; user key | United Kingdom; transfer assessment to document |
| GLEIF | LEI | legal identity (no figures) | yes, as soon as a LEI is entered — open service, no key | global public service |
| SEC EDGAR | US registry; XBRL amounts of annual filings (`data.sec.gov/api/xbrl/companyfacts`) | CIK, user-agent | yes, as soon as a US identifier is entered — open service, no key | United States; registry data |
| OpenSanctions | compliance | identity, query | no | contract/configuration |

No provider should be described as an “approved” processor without a contractual assessment. Sensitive data should be sent only after approval by the responsible controller. This matrix is neither provider approval nor a transfer assessment.

## Portée des gardes / Guard scope

Local ne signifie pas hors ligne. L’interface, le stockage et les gardes s’exécutent sur le poste ; les fournisseurs d’IA, registres et recherches activés reçoivent les contenus nécessaires selon les fonctions. Les gardes ne constituent ni une anonymisation ni un pare-feu avant transmission. Le brief, les extraits et, selon le contexte transmis, des éléments d’historique peuvent quitter le poste. Vérifiez vos droits et les comptes fournisseurs avant lancement.

Local does not mean offline. The interface, storage and guards run on the computer; enabled AI providers, registries and searches receive content needed by their functions. The guards are neither anonymisation nor a firewall before transmission. The brief, excerpts and, depending on submitted context, history items may leave the computer. Check your rights and provider accounts before running.
