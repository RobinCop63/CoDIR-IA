# CoDIR IA v17.0 — Notes de version

| | |
|---|---|
| Nom public | **CoDIR IA v17.0** |
| Build technique | `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65` (build 9.4.65) |
| Date du build | 18 octobre 2026 |
| Licence | FSL-1.1-ALv2 — source disponible ; chaque version passe sous licence Apache 2.0 deux ans après sa mise à disposition (voir `LICENSE`) |
| Empreinte de l’archive publiée | SHA-256 indiqué dans les notes de publication GitHub ; empreintes de chaque fichier dans `SHA256SUMS` |
| Publication visée | 29 octobre 2026, sur décision de l’éditeur |

## Usage et livrables

CoDIR IA prépare une séance de comité de direction à partir d’un brief et de pièces fournies par l’utilisateur. Il livre un **compte rendu Word** et une **synthèse Word** — les deux livrables principaux —, une **ébauche de présentation PowerPoint** et un **dossier complet** (livrables, registres, diagnostic). Il s’adresse à un consultant, à un manager de transition ou à un dirigeant accompagné, pour un **usage supervisé** : les livrables sont une base de travail à relire, jamais une décision ni une certification.

## Ce que la v17.0 apporte

Fonctions présentes et éprouvées lors des recettes d’octobre 2026 sur des dossiers réels (une société américaine cotée en plusieurs séances, un groupe agroalimentaire français sous Windows et macOS) :

- **Mémoire d’une séance à l’autre** : statuts déclarés par le dirigeant (réalisée, reportée, abandonnée), décision du conseil reprise à l’identique dans le compte rendu, la synthèse et le deck ; une recommandation n’est jamais présentée comme une décision adoptée.
- **Discipline de preuve** : faits, hypothèses et scénarios distingués ; faits publiés lus dans les registres publics selon les identifiants disponibles ; un chiffre contredit par une pièce porte la valeur de la pièce.
- **Livraison complète avec signalements en place** (voir « Doctrine de livraison »).
- **Contrôle du deck livré** : décision alignée sur le conseil, effectif d’une autre entité affiché avec son entité et son exercice, cartes vides ou réduites à un intertitre renvoyées au compte rendu.
- **Parcours** : brief rempli dans le formulaire ou collé, écran de traitement, écran de fin, « Quitter » ; session déconnectée conservée 24 heures ; poste maintenu éveillé pendant un traitement.

## Corrections finales du build 9.4.65

Constatées sur les contre-recettes des 17 et 18 octobre 2026 (Windows et macOS) ; ce sont des constats sur ces dossiers, pas une garantie générale :

- l’effectif d’une filiale garde son entité et son exercice, dans le compte rendu, la synthèse et le deck ;
- la note Finance est conservée sous une notice unique de prudence lorsqu’aucun état financier primaire du périmètre n’est disponible ;
- une réserve comptable ne présuppose plus l’existence d’une provision ;
- une décision passée ou un événement accompli n’est plus transformé en action ;
- sans décision du conseil, la carte du deck s’intitule « Recommandation » ;
- deux valeurs égales ne sont plus déclarées contradictoires ;
- le téléchargement du dossier complet et l’icône de l’onglet fonctionnent (starlette 1.7.0).

## Doctrine de livraison

Le principe est de conserver : une quantité non étayée reste à sa place, surlignée et suivie de « ⚠ à vérifier — motif » ; l’encadré de première page compte et liste les passages signalés. Exceptions actuelles : les calculs personnels (rémunération, dividendes, statut de travailleur non salarié) sont écartés ; sans états financiers primaires du périmètre, la note Finance d’un dossier d’une personne (SASU, EURL, EI) ou une note très courte est remplacée par un cadre de prudence ; certaines formulations comptables reçoivent une réserve normalisée. Les annotations du produit sont elles-mêmes à confronter aux pièces.

## Limites connues

- Signalements nombreux (plus de 200 par compte rendu sur les dossiers de recette), dont des fausses alertes : la relecture est indispensable.
- Les pièces scannées sans couche texte ne sont pas lues (pas d’OCR en v17).
- La présentation PowerPoint est une ébauche ; les deux Word sont les livrables de référence.
- L’anglais est en préversion (interface, livrables, manuels).
- Le mode local n’est pas un mode hors ligne : les modèles d’IA sont appelés chez leurs fournisseurs ; les clés d’API sont conservées localement en clair.
- Application non signée en v17.0 : une autorisation est demandée au premier lancement (gestes dans le README) ; signature prévue en v18.
- Fermer le capot d’un portable peut mettre le poste en veille pendant un traitement.

**Limites relevées en recette (octobre 2026), à corriger en v17.5 ou v18.**
- Une action déjà décidée peut entrer au registre reformulée par l'agent (« Produire » au lieu de « Reconstituer »). Pour déclarer son statut à la séance suivante, **reprendre le libellé tel qu'il figure dans le tableau des actions du CR précédent** ; sinon CoDIR IA ne la clôt pas et le signale (aperçu « non retrouvée », section « Statuts déclarés NON appliqués » du CR).
- Un mot courant peut être relevé comme entité non vérifiée (« Parade ») : fausse alerte, à retirer à la relecture.
- Un résultat ajusté (« hors ajustement fiscal », « ajusté ») peut être signalé « réalisé contredit par la pièce » face au résultat publié : fausse alerte, la mesure ajustée n'étant pas le résultat publié ; à retirer à la relecture.
- Les pièces scannées sans couche texte ne sont pas lues (pas d'OCR en v17) ; un montant français à séparateurs d'espaces peut être mal découpé dans le tableau des faits (« 12 » pour 12 345 678,90 €) : à vérifier sur la pièce ; une obligation juridique déduite d'un effectif additionné (seuil de 249 salariés) demande une vérification du périmètre, du mode de comptage et de la règle applicable.
- Des chiffres écrits par l'agent dans le libellé d'une action (« scénarios 54 %, 55 % et 56 % ») peuvent porter « projection sans pièce » ou « cible sans pièce », y compris sur la ligne qui reprend ton statut : fausse alerte, le statut et sa date sont appliqués ; à retirer à la relecture.
- Le registre peut contenir des libellés maladroits (fragment de phrase, date en tête) et des dates écrites sous deux formes (« 01/12/2026 », « 2026-10-23 ») : contenu juste, rédaction à reprendre à la relecture.

## Preuves

- Contrats automatisés : la suite complète a été exécutée sur le zip de suite 9.4.65 extrait à blanc (6 348 passés, 0 échec, 9 ignorés, 1 écart connu marqué, 25 octobre 2026) ; le zip final n’en diffère que par des fichiers de documentation et de statut. Des contrats ne remplacent ni un run neuf sur un dossier réel ni une recette native Windows/macOS.
- Scan de vulnérabilités du 17 octobre 2026 (`pip-audit`, base OSV) sur les 83 dépendances du verrou distribué : aucune vulnérabilité connue (`Documentation/3 - Securite et conformite/VULNERABILITY_SCAN_STATUS.md`).
- SBOM CycloneDX des 83 composants, licences et empreintes (`SBOM_CycloneDX.json`, `THIRD_PARTY_NOTICES.md`).
- Essais natifs par l’éditeur sur l’archive publique : macOS le 17 octobre 2026 et Windows le 18 octobre 2026 (installation, traitement complet, téléchargement du dossier complet, arrêt).

## Installation

Voir `README.md` et les guides de `Documentation/1 - Manuels d'utilisation/` (Windows, macOS). Python standard 3.11 à 3.14 sous Windows 10/11 64 bits sur PC Intel/AMD et sous Windows 11 sur PC ARM (un Python x64 émulé sur PC ARM), et 3.11 à 3.13 sous macOS, sur Mac à puce Apple. Mac Intel, Windows 32 bits et Windows 10 sur PC ARM : non pris en charge par cette version. Sous Windows, une mise à jour depuis une version antérieure remplace automatiquement l’environnement Python construit pour une autre version ; l’ancien est conservé sous `.venv-precedent`.

## Historique condensé

- **Septembre 2026 (builds 9.4.31 à 9.4.48)** : campagne de recette sur des dossiers français et internationaux ; cohérence financière, cadrage temporel et mode rétrospectif ; archive publique construite depuis une liste blanche ; doctrine des scénarios ; verrou et SBOM complets.
- **Fin septembre 2026 (9.4.49 et 9.4.50)** : doctrine « tout livrer, tout signaler en place » ; faits financiers publiés ; modèle par défaut mis à jour.
- **1er au 8 octobre 2026 (9.4.51 à 9.4.56)** : archive publique installable ; statuts du dirigeant et décision du conseil ; écran de traitement ; documentation de publication.
- **10 au 15 octobre 2026 (9.4.57 à 9.4.64)** : écran de fin et « Quitter » ; réglages « qualité d’abord » ; statuts sur plusieurs lignes ; verrou rafraîchi et scan.
- **15 au 18 octobre 2026 (9.4.65)** : session conservée, poste maintenu éveillé, contrôle du deck livré, corrections des contre-recettes, starlette 1.7.0.

Le journal détaillé des builds est tenu par l’éditeur ; il n’est pas distribué dans l’archive publique.
