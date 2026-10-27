# Installation macOS — CoDIR IA v17.0 (build 9.4.65)

**Logiciel :** CoDIR IA v17.0 — build `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`  
**Révision documentaire :** 18 octobre 2026  
**Usage :** professionnel supervisé

## Prérequis

- macOS 11 ou plus récent, sur Mac à puce Apple (M1 et suivants). Les Mac Intel ne sont pas pris en charge par cette version : une dépendance du verrou, cryptography 50, ne publie plus de version Intel ;
- CPython standard 3.11 à 3.13 ; 3.11/3.12 recommandés ; Python 3.14 n’est pas encore pris en charge sous macOS, une dépendance du verrou n’y publiant pas de version binaire ;
- accès réseau aux fournisseurs activés.

## Parcours

1. Avant extraction, calculez le SHA-256 du ZIP avec `shasum -a 256 "NOM_EXACT_DU_ZIP.zip"`. Remplacez le nom d’exemple par celui du fichier reçu et comparez l’empreinte à une référence publiée par une source de confiance.
2. Extrayez le ZIP dans un dossier local. Depuis le dossier contenant `SHA256SUMS`, exécutez `shasum -a 256 -c SHA256SUMS`. En cas de fichier manquant ou d’empreinte différente, ne lancez pas l’application.
3. Ouvrir `Demarrer_Mac.command` via double-clic ou clic droit > Ouvrir.
4. Si Homebrew est absent, le script affiche l’URL officielle et demande une confirmation explicite avant la commande officielle `curl | bash`.
5. Le retrait de l’attribut de quarantaine par `xattr` est proposé séparément, limité aux éléments CoDIR IA, et peut être refusé.
6. Après un premier blocage, utilisez Réglages Système > Confidentialité et sécurité > Ouvrir quand même, si cette option est proposée et autorisée par votre DSI ; ne désactivez pas Gatekeeper globalement. Arrêtez en cas d’alerte de logiciel malveillant ou de fichier altéré.

## Confiance et signature

Artefacts réellement livrés : lanceurs Windows .bat et scripts macOS .command non signés, distribués dans un ZIP ; le raccourci .app peut être créé localement. Le ZIP n’est pas présenté comme Authenticode-signé ; aucun ensemble applicatif Developer ID notarisé n’est fourni. Les avertissements du système sont attendus. Vérifiez la provenance, l’empreinte externe du ZIP et le manifeste ; ne désactivez pas globalement SmartScreen ou Gatekeeper. La décision sur les signatures, les preuves de test et l’approbation de diffusion restent hors de l’archive.

## Chemins

Configuration, cache, données et logs : `~/Library/Application Support/CoDIR-IA` (sous-dossiers `cache`, `data`, `logs`). Le venv reste dans le dossier application.

## Emplacements et fonctionnement

- environnement Python : `application/.venv` dans le dossier d’installation ;
- configuration, cache, données et journaux : `~/Library/Application Support/CoDIR-IA` ;
- pendant un traitement, le Mac est maintenu éveillé (`caffeinate`) ; fermer le capot d’un portable peut néanmoins provoquer la veille ;
- « Quitter », sur l’écran de fin, arrête CoDIR IA sans laisser de processus Python ;
- le raccourci « CoDIR IA » du Bureau ouvre `Demarrer_Mac.command`, donc le même contrôle d’intégrité qu’un double-clic.

## Modèle et sources publiques

- **Modèle Anthropic par défaut : Claude Sonnet 5.5** (`claude-sonnet-5-5`). Claude Sonnet 4.5 est retiré de l'API le 24/11/2026 ; un réglage enregistré sur un ancien Sonnet est migré automatiquement au premier lancement.
- **Contact SEC** (`SEC_EDGAR_USER_AGENT`, « Prénom Nom adresse@domaine ») : obligatoire pour lire les dépôts SEC d'une société cotée aux États-Unis ; sans lui, la SEC n'est pas interrogée.
- **Clé Companies House** (`COMPANIES_HOUSE_API_KEY`, gratuite sur le Developer Hub de Companies House) : nécessaire pour les sociétés britanniques ; une clé distincte pour l'API documents (`COMPANIES_HOUSE_DOCUMENT_API_KEY`) est possible en option avancée. Un compte déposé en PDF scanné ne donne aucune valeur.
- **Clé Pappers** (`PAPPERS_API_KEY`) : optionnelle, pour les sociétés françaises (comptes déposés, sauf comptes confidentiels).
- Ces réglages se saisissent dans la page **Réglages** de l'application et sont enregistrés dans le dossier de configuration (`~/Library/Application Support/CoDIR-IA`). Seul l'identifiant de la société est envoyé à ces services, jamais vos pièces.

### Modèles d'IA par rôle (état vérifié le 18/10/2026)

| Rôle | Fournisseur | Modèle par défaut |
|---|---|---|
| Compte rendu, Finance, Stratégie, reprises | Anthropic | `claude-sonnet-5-5` |
| Direction générale, Marketing, CEO, préfiltre Supply Chain | OpenAI | `gpt-5.4` |
| Supply Chain (principal) | OpenAI | `gpt-5.4` |
| Finance (second avis), contradicteur Supply Chain | Google | `gemini-3.6-flash` |
| Direction commerciale | xAI | `grok-4.3` |
| Synthèse des décisions, recherche web | Perplexity (API Agent) | `perplexity/sonar` |
| Résolution d'entités | Anthropic | `claude-haiku-4-5-20251001` |
| Repli de dernier recours, dans chaque rôle | **Mistral AI (Paris), fournisseur européen** | `mistral-medium-latest` (alias tenu à jour par Mistral) |

Un réglage ou une variable d'environnement restés sur un modèle retiré (Claude Sonnet 4.5, gpt-4.1, Gemini 2.5, Grok 3, Sonar) sont migrés automatiquement ; la page Réglages signale une variable d'environnement qui remplace un réglage.

**Tester avant le premier run** : dans Réglages, « Tester la connexion » vérifie chaque clé (fournisseurs de modèles, Pappers, GLEIF, SEC, OpenSanctions, Companies House) ; « Tester la lecture » vérifie en plus que les montants publiés se lisent (SEC — 10-K, Pappers — finances, Companies House — comptes iXBRL, sur un numéro britannique que tu saisis).

## Désinstallation

Fermer le terminal, supprimer le dossier d’installation, `~/Library/Application Support/CoDIR-IA`, le raccourci `CoDIR IA.app`, les outputs et, après vérification, l’ancien `~/.codir_ia`.

Évitez un dossier synchronisé OneDrive/Dropbox pour le venv et les données de travail.

## Installation, contrôle et limites

Le lanceur cherche un CPython standard compatible avec la plage prévue 3.11–3.13. Si le mode verrouillé échoue et qu’un repli requirements.txt est utilisé, l’environnement ne correspond plus exactement au verrou ni au SBOM : conservez INSTALL_MODE.txt et le journal, puis faites vérifier ce déploiement. La présence d’un lanceur ne certifie pas une plateforme ou une architecture ; consultez la matrice de tests natifs applicable.

Local ne signifie pas hors ligne. L’interface, le stockage et les gardes s’exécutent sur le poste ; les fournisseurs d’IA, registres et recherches activés reçoivent les contenus nécessaires selon les fonctions. Les gardes ne constituent ni une anonymisation ni un pare-feu avant transmission. Le brief, les extraits et, selon le contexte transmis, des éléments d’historique peuvent quitter le poste. Vérifiez vos droits et les comptes fournisseurs avant lancement.

Gardes déterministes. Après la génération par les modèles, des règles Python locales examinent les textes et les données structurées. Aucun modèle n’est appelé pour décider dans ces gardes. Doctrine « tout livrer, tout signaler en place » : le principe est de conserver. Une quantité non étayée reste à sa place, surlignée et suivie de « ⚠ à vérifier — motif » ; un chiffre contredit par une pièce porte la valeur de la pièce ; l’encadré de première page compte et liste les passages signalés, et le registre les recense. Exceptions actuelles : les calculs personnels (rémunération, dividendes, statut de travailleur non salarié) sont écartés ; sans états financiers primaires du périmètre, la note Finance d’un dossier d’une personne (SASU, EURL, EI) ou une note très courte est remplacée par un cadre de prudence ; certaines formulations comptables reçoivent une réserve normalisée, elle-même à confronter aux pièces. Seule une panne technique empêche la livraison. Ces contrôles réduisent certains risques ; ils ne garantissent ni l’absence d’erreur, ni l’exhaustivité, ni une traçabilité complète de chaque transformation. Un élément légitime peut être sur-étiqueté ou masqué ; un élément incorrect peut échapper au contrôle. Relire les Word et comparer les réserves, registres et sources avant usage.
