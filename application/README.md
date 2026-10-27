# CoDIR IA v17.0

**Logiciel :** CoDIR IA v17.0 — build `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`  
**Révision documentaire :** 18 octobre 2026  
**Usage :** professionnel supervisé

![Version](https://img.shields.io/badge/version-v17.0-1E2761)
![License](https://img.shields.io/badge/license-FSL--1.1--ALv2-E8B84B)
![Tests](https://img.shields.io/badge/tests-counter--audit%20required-E8B84B)
![Python](https://img.shields.io/badge/python-3.11--3.14-blue)
**Licence / License:** `FSL-1.1-ALv2` (source-available).

CoDIR IA prépare un comité de direction à la demande pour les consultants, managers de transition et dirigeants de PME/PMI/ETI, à partir du brief et des pièces retenues. Le Word long porte l’analyse ; le Word synthétique en présente les conclusions et les arbitrages. Ce sont les deux livrables principaux, à relire et valider par le professionnel. Le PPTX est une ébauche éditable à compléter après lecture des Word : sélection, messages, illustrations et mise en page restent à sa charge. La mémoire locale de dossier soutient la continuité entre séances ; elle ne remplace ni un procès-verbal approuvé ni la validation humaine.

## Démarrage

Sous Windows, **Double-cliquer** sur `INSTALL_OR_LAUNCH.bat` via le lanceur racine recommandé. Sous macOS, double-cliquer sur `INSTALL_OR_LAUNCH.command`. Le serveur écoute localement sur `127.0.0.1:8501`. Depuis la racine de l’archive, `DEMARRER_CODIR_IA.bat` (Windows) et `Demarrer_Mac.command` (macOS) appellent ces lanceurs. Vérifiez d’abord l’empreinte externe du ZIP et `SHA256SUMS` ; lisez le guide d’installation avant d’autoriser les scripts non signés. Ne désactivez pas globalement les protections du poste.

## Où trouver quoi

| Besoin | Document |
|---|---|
| Parcours de lecture et mémoire | [Lire la documentation](../Documentation/LIRE_LA_DOCUMENTATION_FR.md) |
| Installation/utilisation FR et EN | `../Documentation/1 - Manuels d'utilisation/` |
| Évolutions et limites actuelles | [Notes de version](../RELEASE_NOTES.md) |
| Conditions, confidentialité, tiers | `../Documentation/2 - Conditions et confidentialite/` |
| Sécurité, AI Act, SBOM | `../Documentation/3 - Securite et conformite/` |
| Statut de ce lot documentaire | [État documentaire](../Documentation/ETAT_DOCUMENTAIRE.md) |
| English | [English README](README_EN.md) |

## Version courante

Nouveautés, limites connues et compatibilité : voir `../RELEASE_NOTES.md`. Sourçage des chiffres : un chiffre présenté comme un fait est confirmé à la page d'une pièce ou au registre ; un calcul fait à partir de faits confirmés expose sa formule ; tout autre chiffre est déclaré non confirmé, avec ses réserves.

## Licence, données et état

Code sous **FSL-1.1-ALv2**, source disponible : voir `LICENSE`. Marque et logo : `TRADEMARKS.md`. L’usage professionnel autorisé et la remise de livrables sous les réserves des Terms n’exigent pas en eux-mêmes d’autorisation supplémentaire de l’éditeur.

Local ne signifie pas hors ligne. L’interface, le stockage et les gardes s’exécutent sur le poste ; les fournisseurs d’IA, registres et recherches activés reçoivent les contenus nécessaires selon les fonctions. Les gardes ne constituent ni une anonymisation ni un pare-feu avant transmission. Le brief, les extraits et, selon le contexte transmis, des éléments d’historique peuvent quitter le poste. Vérifiez vos droits et les comptes fournisseurs avant lancement.

L’anglais demeure en préversion. Les gardes déterministes réduisent certains risques, sans garantie d’exactitude ni d’exhaustivité. Les contrôles et compteurs ne remplacent pas la revue humaine ni la porte cumulative de publication. CoDIR IA v17.0 — build 9.4.65 est destiné à un usage professionnel supervisé. La décision de publication et ses preuves sont conservées par l’éditeur hors de cette archive.

Signalement : **security@vauquigneux.com**, objet `[SECURITY CoDIR IA]`. Premier message sans secrets ni pièces client. Voir `SECURITY_FR.md`.

## Langues

Français et anglais. **L'anglais est proposé en préversion à cette version** : les fonctions disponibles et les limites connues sont listées dans les notes de version ; la parité des contrôles éditoriaux et financiers avec le français n'est pas certifiée à cette version.
