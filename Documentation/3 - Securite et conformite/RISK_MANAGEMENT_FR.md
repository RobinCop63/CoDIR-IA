# Gestion des risques — CoDIR IA

**Logiciel :** CoDIR IA v17.0 — build `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`  
**Révision documentaire :** 18 octobre 2026  
**Usage :** professionnel supervisé

Ce document décrit des contrôles volontaires de cycle de vie. Il ne qualifie pas CoDIR IA comme système à haut risque et ne constitue pas une certification.

## 1. Gouvernance — contrôles inspirés de l’article 9

- finalité : document de travail supervisé ;
- propriétaire du risque : Vauquigneux Gestion pour le produit, déployeur pour le contexte d’usage ;
- interdiction des détournements sensibles sans revue ;
- registre des versions, incidents, dépendances et décisions de sécurité ;
- depuis la 9.4.49, livraison avec signalements en place lorsque la preuve ou l’autorité temporelle n’est pas établie ; seule une panne technique arrête la livraison.

## 2. Risques suivis

| Risque | Mesures |
|---|---|
| hallucination / erreur factuelle | claims canoniques, pages, conflits, revue humaine |
| chiffre prospectif non étayé | signalement en place (surlignage, « ⚠ à vérifier — motif », encadré de première page), registre des passages signalés, contrôles finaux DOCX/PPTX |
| mauvais périmètre ou période | résolution d’entité, Temporal Core, autorité de période |
| fuite de données | minimisation, configuration locale, contrats fournisseurs |
| compromission supply chain | lock, SBOM, manifestes, contrôle d’intégrité |
| indisponibilité fournisseur | fallbacks et diagnostic explicite |
| usage interdit | conditions d’utilisation et qualification préalable |

> **Doctrine des scénarios.** Les scénarios et quantités non étayés restent **en place** dans le corps du document, avec leurs signalements, et sont recensés dans le registre probatoire ; leur présence ne vaut ni validation ni approbation. Les exceptions de retrait ou de remplacement sont celles décrites au chapitre « Gardes déterministes » du manuel utilisateur. Les mentions d'« annexe scénarios » ci-dessus décrivent un dispositif antérieur et ne valent plus comme consigne.

## 3. Cycle et journal des incidents

Identifier → évaluer → traiter → tester → documenter → contre-auditer → surveiller. Les incidents de sécurité suivent `SECURITY_FR.md` et la procédure CRA.

Le journal des incidents conserve version, date, impact, traitement, décision et preuve de clôture.

## Risques de qualification et de restitution

Gardes déterministes. Après la génération par les modèles, des règles Python locales examinent les textes et les données structurées. Aucun modèle n’est appelé pour décider dans ces gardes. Doctrine « tout livrer, tout signaler en place » : le principe est de conserver. Une quantité non étayée reste à sa place, surlignée et suivie de « ⚠ à vérifier — motif » ; un chiffre contredit par une pièce porte la valeur de la pièce ; l’encadré de première page compte et liste les passages signalés, et le registre les recense. Exceptions actuelles : les calculs personnels (rémunération, dividendes, statut de travailleur non salarié) sont écartés ; sans états financiers primaires du périmètre, la note Finance d’un dossier d’une personne (SASU, EURL, EI) ou une note très courte est remplacée par un cadre de prudence ; certaines formulations comptables reçoivent une réserve normalisée, elle-même à confronter aux pièces. Seule une panne technique empêche la livraison. Ces contrôles réduisent certains risques ; ils ne garantissent ni l’absence d’erreur, ni l’exhaustivité, ni une traçabilité complète de chaque transformation. Un élément légitime peut être sur-étiqueté ou masqué ; un élément incorrect peut échapper au contrôle. Relire les Word et comparer les réserves, registres et sources avant usage.

Situation financière établie. Le oui/non et sa raison, lorsqu’ils sont disponibles dans le CR ou les diagnostics, portent sur la base courante que le moteur a pu qualifier au périmètre et à la date retenus. « Oui » ne certifie ni tous les chiffres ni les scénarios. « Non » ne prouve pas l’absence de comptes : examinez les pièces recensées, l’extractibilité, les périodes, les périmètres et les conflits. Cette raison globale n’est pas une explication par chiffre.

Mémoire entre CoDIR. Le code comporte un historique local par dossier et un registre d’actions horodaté. Réutilisez le même dossier — même « Libellé de dossier » d’une séance à l’autre — et vérifiez l’entité, l’identifiant, le répertoire de données et la date d’analyse. Dans le nouveau brief, précisez les décisions réellement approuvées, les actions réalisées ou reportées et les clôtures explicites. Relisez ensuite les reprises et les écarts : une proposition ne devient pas approuvée par simple répétition. Les modes rétrospectif/futur n’écrivent pas le registre vivant ; la case « Repartir de zéro — ignorer l’historique de ce dossier » (variable technique CODIR_IGNORE_HISTORY) neutralise la reprise pour un test isolé. La reprise exhaustive des décisions, actions et questions sur deux séances n’est pas certifiée par cette révision documentaire ; elle reste à vérifier sur votre dossier. Ce n’est ni une mémoire de toutes les conversations ni un apprentissage du modèle.

## Risques liés aux données publiques, aux modèles et à la mémoire

| Risque | Mesure |
|---|---|
| Donnée publique tierce erronée ou d'un autre périmètre (comptes sociaux pris pour consolidés) | Routage par identifiant et juridiction ; périmètre et source affichés ; la pièce fournie passe toujours avant ; un écart est signalé |
| Indisponibilité d'un service public (SEC, Companies House, Pappers) | Collecte bornée et silencieuse ; sans réponse, les cartes s'appuient sur les seules pièces |
| Changement de modèle (Claude Sonnet 4.5 retiré le 24/11/2026, Sonnet 5.5 par défaut) | Migration automatique des réglages ; paramètres refusés par les nouveaux modèles retirés de l'appel ; recette sur entrées figées avant diffusion |
| Mémoire erronée d'une séance à l'autre (reprise manquée, décision attribuée à tort) | Reprises reconnues par l'intention ; statuts appliqués seulement depuis le brief du dirigeant ; recommandation des agents distinguée d'une décision |
