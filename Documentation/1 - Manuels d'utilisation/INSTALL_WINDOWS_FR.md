# Installation Windows — CoDIR IA v17.0 (build 9.4.65)

**Logiciel :** CoDIR IA v17.0 — build `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`  
**Révision documentaire :** 18 octobre 2026  
**Usage :** professionnel supervisé

## Prérequis

- Windows 10/11 64 bits sur PC Intel/AMD (x64) ; Windows 11 sur PC ARM. Sur un PC ARM, CoDIR IA utilise un Python x64, exécuté par l’émulation x64 intégrée à Windows 11 (Windows 10 sur ARM n’émule pas le x64 et n’est pas pris en charge ; le lanceur s’y arrête avec un message clair), car quatre dépendances du verrou ne publient pas de version ARM64 : le lanceur choisit un Python x64 déjà installé, ou installe Python 3.12 x64, et refuse un Python ARM64 natif. Windows 32 bits n’est pas pris en charge, et un Python 32 bits est refusé ;
- CPython standard 3.11 à 3.14 ; 3.11 ou 3.12 recommandés ;
- accès HTTPS aux fournisseurs activés ;
- aucun build free-threaded/no-GIL.

## Parcours recommandé

1. Dans PowerShell, exécuter `Get-FileHash -LiteralPath ".\NOM_EXACT_DU_ZIP.zip" -Algorithm SHA256`. Remplacer le nom d’exemple par celui du fichier reçu et comparer l’empreinte à la référence de scellement de confiance.
2. Extraire le ZIP dans un dossier local, idéalement hors OneDrive.
3. Double-cliquer `DEMARRER_CODIR_IA.bat`.
4. Le lanceur vérifie chaque entrée de `SHA256SUMS` **avant** toute commande `Unblock-File`.
5. En cas de mismatch ou fichier manquant, le lancement s’arrête : supprimer le dossier et retélécharger.
6. Après validation, le lanceur retire les marqueurs `Zone.Identifier` des seuls fichiers du package, sélectionne un CPython compatible, installe le venv et affiche l’URL de lancement. Les lanceurs publics utilisent le port 8501 : ouvrez l’adresse affichée (`http://127.0.0.1:8501`). Si ce port est occupé, fermez l’autre instance ou faites libérer le port par votre administrateur, puis relancez ; le lanceur ne choisit pas automatiquement un autre port.

## Mise à jour depuis une version antérieure

Fermez CoDIR IA, extrayez la nouvelle version dans un nouveau dossier, puis lancez `DEMARRER_CODIR_IA.bat`. Le lanceur compare l’empreinte du verrou des dépendances livré avec celle de l’environnement Python partagé (`%LOCALAPPDATA%\CoDIR-IA\.venv`) : si elles diffèrent, il met l’ancien environnement de côté sous `.venv-precedent`, installe le verrou livré et retire l’ancien raccourci du Bureau, recréé au lancement suivant. Vos réglages et données (`%APPDATA%\CoDIR-IA`) ne sont pas touchés. Contrôle : `INSTALL_MODE.txt` indique `locked requirements.lock`. Après vérification, vous pouvez supprimer `.venv-precedent`. Si l’environnement ne peut pas être mis de côté, parce que CoDIR IA est encore ouvert, le lanceur s’arrête : fermez toutes les fenêtres de CoDIR IA et relancez. Si les dépendances n’ont pu être installées qu’en mode de repli, sans le verrou, le lanceur l’indique à chaque démarrage. Le raccourci « CoDIR IA » du Bureau passe par `DEMARRER_CODIR_IA.bat`, donc par les mêmes contrôles.

## SmartScreen

Les lanceurs .bat livrés sont non signés ; aucun installateur Authenticode signé n’est fourni. SmartScreen peut demander une confirmation initiale. Ne choisissez « Exécuter quand même » qu’après vérification de l’origine, du SHA et du manifeste.

Geste conseillé : avant d'extraire, clic droit sur le zip > Propriétés > cocher « Débloquer » > OK ; le premier double-clic installe alors puis lance, sans relance. Sinon, à l'écran SmartScreen : « Informations complémentaires » > « Exécuter quand même ». La signature Authenticode est prévue en v18 (avec une distribution par le Microsoft Store).

## Chemins

- configuration : `%APPDATA%\CoDIR-IA` ;
- cache : `%LOCALAPPDATA%\CoDIR-IA\cache` ;
- venv et logs installateur : `%LOCALAPPDATA%\CoDIR-IA` ;
- données/historique : `%APPDATA%\CoDIR-IA\data` ;
- outputs : dossier `application\outputs` ou emplacement choisi au téléchargement.

## Modèle et sources publiques

- **Modèle Anthropic par défaut : Claude Sonnet 5.5** (`claude-sonnet-5-5`). Claude Sonnet 4.5 est retiré de l'API le 24/11/2026 ; un réglage enregistré sur un ancien Sonnet est migré automatiquement au premier lancement.
- **Contact SEC** (`SEC_EDGAR_USER_AGENT`, « Prénom Nom adresse@domaine ») : obligatoire pour lire les dépôts SEC d'une société cotée aux États-Unis ; sans lui, la SEC n'est pas interrogée.
- **Clé Companies House** (`COMPANIES_HOUSE_API_KEY`, gratuite sur le Developer Hub de Companies House) : nécessaire pour les sociétés britanniques ; une clé distincte pour l'API documents (`COMPANIES_HOUSE_DOCUMENT_API_KEY`) est possible en option avancée. Un compte déposé en PDF scanné ne donne aucune valeur.
- **Clé Pappers** (`PAPPERS_API_KEY`) : optionnelle, pour les sociétés françaises (comptes déposés, sauf comptes confidentiels).
- Ces réglages se saisissent dans la page **Réglages** de l'application et sont enregistrés dans le dossier de configuration (`%APPDATA%\CoDIR-IA`). Seul l'identifiant de la société est envoyé à ces services, jamais vos pièces.

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

Fermer CoDIR IA, supprimer le dossier d’installation, `%APPDATA%\CoDIR-IA`, `%LOCALAPPDATA%\CoDIR-IA`, les outputs et les raccourcis. Révoquer les clés API si nécessaire.

Si une installation manuelle de Python est nécessaire, activez « Add Python to PATH » ; le lanceur préfère néanmoins les sélecteurs explicites.

## Installation, contrôle et limites

Le lanceur cherche un CPython standard compatible avec la plage prévue 3.11–3.14. Si le mode verrouillé échoue et qu’un repli requirements.txt est utilisé, l’environnement ne correspond plus exactement au verrou ni au SBOM : conservez INSTALL_MODE.txt et le journal, puis faites vérifier ce déploiement. La présence d’un lanceur ne certifie pas une plateforme ou une architecture ; consultez la matrice de tests natifs applicable.

Local ne signifie pas hors ligne. L’interface, le stockage et les gardes s’exécutent sur le poste ; les fournisseurs d’IA, registres et recherches activés reçoivent les contenus nécessaires selon les fonctions. Les gardes ne constituent ni une anonymisation ni un pare-feu avant transmission. Le brief, les extraits et, selon le contexte transmis, des éléments d’historique peuvent quitter le poste. Vérifiez vos droits et les comptes fournisseurs avant lancement.

Gardes déterministes. Après la génération par les modèles, des règles Python locales examinent les textes et les données structurées. Aucun modèle n’est appelé pour décider dans ces gardes. Doctrine « tout livrer, tout signaler en place » : le principe est de conserver. Une quantité non étayée reste à sa place, surlignée et suivie de « ⚠ à vérifier — motif » ; un chiffre contredit par une pièce porte la valeur de la pièce ; l’encadré de première page compte et liste les passages signalés, et le registre les recense. Exceptions actuelles : les calculs personnels (rémunération, dividendes, statut de travailleur non salarié) sont écartés ; sans états financiers primaires du périmètre, la note Finance d’un dossier d’une personne (SASU, EURL, EI) ou une note très courte est remplacée par un cadre de prudence ; certaines formulations comptables reçoivent une réserve normalisée, elle-même à confronter aux pièces. Seule une panne technique empêche la livraison. Ces contrôles réduisent certains risques ; ils ne garantissent ni l’absence d’erreur, ni l’exhaustivité, ni une traçabilité complète de chaque transformation. Un élément légitime peut être sur-étiqueté ou masqué ; un élément incorrect peut échapper au contrôle. Relire les Word et comparer les réserves, registres et sources avant usage.
