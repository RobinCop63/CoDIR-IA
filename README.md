# CoDIR IA v17.0

**Logiciel :** CoDIR IA v17.0 — build `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`  
**Révision documentaire :** 18 octobre 2026  
**Usage :** professionnel supervisé

> **English speakers:** CoDIR IA is fully available in English — the interface (chosen on the welcome screen at launch) and the documents it produces. Read the English README: [README_EN.md](README_EN.md).
> **Francophones :** l'interface et les documents existent en français et en anglais ; la langue de l'interface se choisit sur l'écran d'accueil, celle des documents dans le brief.

CoDIR IA prépare un comité de direction à la demande pour les consultants, managers de transition et dirigeants de PME/PMI/ETI, à partir du brief et des pièces retenues. Le Word long porte l’analyse ; le Word synthétique en présente les conclusions et les arbitrages. Ce sont les deux livrables principaux, à relire et valider par le professionnel. Le PPTX est une ébauche éditable à compléter après lecture des Word : sélection, messages, illustrations et mise en page restent à sa charge. La mémoire locale de dossier soutient la continuité entre séances ; elle ne remplace ni un procès-verbal approuvé ni la validation humaine.

## En bref

- **Une préparation de CoDIR par fonction** : Stratégie, Finance (avec second avis), Marketing, Direction commerciale, Supply chain (avec contradicteur) et Direction générale, puis une synthèse des décisions à arbitrer.
- **Quatre sorties** : le compte rendu Word, la synthèse Word, une trame PowerPoint éditable et le dossier complet (pièces de contrôle, registres, diagnostic).
- **Conserver et signaler** : un chiffre ou un passage douteux est livré et signalé en place, avec son motif (« ⚠ à vérifier — … ») ; exceptions : les calculs personnels sont écartés et, sans états financiers primaires, un dossier d’une personne ou une note Finance très courte reçoit un cadre de prudence. Les annotations elles-mêmes sont à relire.
- **Une mémoire d'une séance à l'autre** : registre des actions, et statuts que vous déclarez dans le brief (réalisée, reportée, abandonnée, maintenue, décision du conseil), appliqués dès la séance ; ceux qui ne trouvent pas leur action sont listés au compte rendu.
- **Des faits publiés** repris des registres officiels quand ils sont disponibles (SEC/EDGAR, Pappers, Companies House, GLEIF).
- **Un suivi en douze étapes** pendant le traitement, puis un écran « Dossier prêt ».

## Prérequis

Windows 10/11 64 bits sur PC Intel/AMD, Windows 11 sur PC ARM, ou macOS sur Mac à puce Apple (M1 et suivants) ; Python 3.11 à 3.14 sous Windows, 3.11 à 3.13 sous macOS (le lanceur vérifie la version ; sur un PC ARM sous Windows 11, il utilise un Python x64 exécuté par l’émulation de Windows, et l’installe au besoin) ; Mac Intel, Windows 32 bits et Windows 10 sur PC ARM ne sont pas pris en charge par cette version ; les clés API des fournisseurs d'IA que vous activez (le tableau des rôles et des modèles figure au manuel d'installation) ; en option, un identifiant pour les registres publics. CoDIR IA ne décide pas à votre place : chaque livrable est à relire et à valider avant diffusion.

## Démarrer

Vérifiez l’empreinte externe du ZIP, extrayez dans un dossier local et contrôlez `SHA256SUMS`. Windows : `DEMARRER_CODIR_IA.bat`. macOS : `Demarrer_Mac.command`. Lisez le guide d’installation avant d’autoriser les scripts non signés. Ne désactivez pas globalement les protections du poste.

**Premier lancement (application non signée en v17.0, signature prévue en v18).** Windows : avant d'extraire, clic droit sur le zip > Propriétés > cocher « Débloquer » > OK — le premier double-clic installe puis lance ; à défaut, quand SmartScreen s'affiche : « Informations complémentaires » > « Exécuter quand même ». macOS : clic droit sur `Demarrer_Mac.command` > Ouvrir, ou Réglages Système > Confidentialité et sécurité > Ouvrir quand même.

## Où trouver quoi

| Besoin | Document |
|---|---|
| Parcours de lecture et mémoire | [Lire la documentation](Documentation/LIRE_LA_DOCUMENTATION_FR.md) |
| Installation/utilisation FR et EN | `Documentation/1 - Manuels d'utilisation/` |
| Évolutions et limites actuelles | [Notes de version](RELEASE_NOTES.md) |
| Conditions, confidentialité, tiers | `Documentation/2 - Conditions et confidentialite/` |
| Sécurité, AI Act, SBOM | `Documentation/3 - Securite et conformite/` |
| Statut de ce lot documentaire | [État documentaire](Documentation/ETAT_DOCUMENTAIRE.md) |
| English | [English README](README_EN.md) |

## Licence, données et état

Code sous **FSL-1.1-ALv2**, source disponible : voir `application/LICENSE`. Marque et logo : `application/TRADEMARKS.md`. L’usage professionnel autorisé et la remise de livrables sous les réserves des Terms n’exigent pas en eux-mêmes d’autorisation supplémentaire de l’éditeur.

Local ne signifie pas hors ligne. L’interface, le stockage et les gardes s’exécutent sur le poste ; les fournisseurs d’IA, registres et recherches activés reçoivent les contenus nécessaires selon les fonctions. Les gardes ne constituent ni une anonymisation ni un pare-feu avant transmission. Le brief, les extraits et, selon le contexte transmis, des éléments d’historique peuvent quitter le poste. Vérifiez vos droits et les comptes fournisseurs avant lancement.

L’anglais demeure en préversion. Les gardes déterministes réduisent certains risques, sans garantie d’exactitude ni d’exhaustivité. Les contrôles et compteurs ne remplacent pas la revue humaine ni la porte cumulative de publication. La décision de diffusion de l’éditeur est un acte externe à cette archive ; la version publiée est identifiée par son empreinte SHA-256 dans les notes de publication.

Signalement : **security@vauquigneux.com**, objet `[SECURITY CoDIR IA]`. Premier message sans secrets ni pièces client. Voir `SECURITY.md` à la racine et `Documentation/3 - Securite et conformite/SECURITY_FR.md`.
