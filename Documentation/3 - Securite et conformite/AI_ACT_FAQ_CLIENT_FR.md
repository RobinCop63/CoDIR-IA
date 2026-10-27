# FAQ client — AI Act et transparence — CoDIR IA

**Logiciel :** CoDIR IA v17.0 — build `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`  
**Révision documentaire :** 18 octobre 2026  
**Usage :** professionnel supervisé

**Build :** `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65` — socle initial du 24 août 2026 ; révision courante indiquée ci-dessus.

## Q1. Quel est le statut du produit ?

CoDIR IA est un système d’aide à l’analyse construit au-dessus de modèles tiers. Vauquigneux Gestion est susceptible d’être qualifiée de fournisseur du système et/ou fournisseur en aval selon le mode de mise à disposition ; l’entreprise cliente est généralement déployeur pour son usage. Cette qualification dépend des activités réelles ; elle doit être documentée dans l’analyse du déploiement et les contrats.

## Q2. Que prévoit l’article 50 ?

Les obligations de transparence de l’article 50 s’appliquent depuis le 2 août 2026. CoDIR IA informe l’utilisateur dans l’interface et dans les livrables. Les fichiers Word/PPTX reçoivent aussi un marquage OOXML propriétaire (`AI_GENERATED`). Ce mécanisme améliore la traçabilité, mais le projet ne prétend pas qu’il suffit, seul, à démontrer l’efficacité, la robustesse et l’interopérabilité requises par l’article 50(2).

Le Code of Practice européen sur la transparence des contenus générés par IA constitue un outil volontaire. CoDIR IA v17.0 documente un plan de correspondance ; il n’est pas déclaré signataire ni certifiée.

## Q3. Que prévoit l’article 50, paragraphe 4 ?

La mention sur les textes destinés à informer le public de questions d’intérêt public dépend de l’usage et de la publication. Les livrables internes supervisés portent une mention prudente « where applicable / si applicable » et une revue humaine obligatoire.

## Q4. CoDIR IA est-il un système à haut risque ?

L’usage prévu n’est pas présenté comme un cas haut risque. Les contrôles inspirés des articles 9 et 14 sont volontaires. Un détournement vers le recrutement, le crédit, l’accès à des services essentiels ou une décision individuelle significative exige une nouvelle qualification.

## Q5. Quel lien avec le RGPD ?

Le RGPD reste applicable aux données personnelles traitées. Les rôles, bases légales, informations, contrats de sous-traitance et transferts doivent être qualifiés pour le déploiement.

## Références

- Règlement (texte de référence ; consulter la version applicable au déploiement) : https://eur-lex.europa.eu/eli/reg/2024/1689/oj
- Lignes directrices article 50 : https://digital-strategy.ec.europa.eu/en/policies/guidelines-ai-transparency-obligations
- Code of Practice : https://digital-strategy.ec.europa.eu/en/policies/code-practice-ai-generated-content

## Qualification des chiffres, supervision et limites

Niveaux de confirmation. « Confirmé à la page » indique un rapprochement effectué par le logiciel avec une pièce et une page ; vérifiez la valeur ET son libellé, le signe, l’unité et l’échelle, la période et le périmètre. « Confirmé au registre » renvoie à un registre interrogé, avec sa date de consultation ; ce n’est pas nécessairement l’exercice analysé et cette voie est inactive en analyse rétrospective. « Déclaré non confirmé » signifie que le rapprochement requis n’est pas établi. Causes possibles : source absente, extraction insuffisante, libellé, unité, échelle, période ou périmètre non rapprochés ; le statut n’indique pas laquelle. L’étiquette [NON SOURCÉ] / [UNSOURCED] signifie ici « déclaré non confirmé », non « aucune source n’existe ». La nature (réalisé, budget, hypothèse, cible), la preuve et l’approbation restent distinctes. Rapprochement arithmétique : entre faits confirmés d’une même période, d’un même périmètre et d’une même devise, le logiciel vérifie que chiffre d’affaires − coût des ventes = marge brute, et marge brute − charges d’exploitation = résultat d’exploitation lorsque la table porte un total des charges. Le résultat porte la note « rapproché » (ou « rapproché à l’arrondi près » jusqu’à 1 % d’écart) ; au-delà, il passe « à vérifier » et cesse de confirmer, ses deux opérandes portant une note. La valeur publiée n’est jamais remplacée par le calcul, et ce contrôle ne couvre que ces deux identités.

Gardes déterministes. Après la génération par les modèles, des règles Python locales examinent les textes et les données structurées. Aucun modèle n’est appelé pour décider dans ces gardes. Doctrine « tout livrer, tout signaler en place » : le principe est de conserver. Une quantité non étayée reste à sa place, surlignée et suivie de « ⚠ à vérifier — motif » ; un chiffre contredit par une pièce porte la valeur de la pièce ; l’encadré de première page compte et liste les passages signalés, et le registre les recense. Exceptions actuelles : les calculs personnels (rémunération, dividendes, statut de travailleur non salarié) sont écartés ; sans états financiers primaires du périmètre, la note Finance d’un dossier d’une personne (SASU, EURL, EI) ou une note très courte est remplacée par un cadre de prudence ; certaines formulations comptables reçoivent une réserve normalisée, elle-même à confronter aux pièces. Seule une panne technique empêche la livraison. Ces contrôles réduisent certains risques ; ils ne garantissent ni l’absence d’erreur, ni l’exhaustivité, ni une traçabilité complète de chaque transformation. Un élément légitime peut être sur-étiqueté ou masqué ; un élément incorrect peut échapper au contrôle. Relire les Word et comparer les réserves, registres et sources avant usage.

Les deux Word sont les livrables principaux : analyse détaillée et synthèse décisionnelle. Le PPTX est une ébauche de présentation à reprendre après lecture des Word, non un document autonome prêt à remettre. Le volume dépend du brief et de la matière ; les nombres de pages ou de slides sont des repères, pas une garantie. Le paquet complet réunit les fichiers effectivement produits, les diagnostics, les registres disponibles, le journal de préparation et le manifeste.

La relecture humaine et le statut d’ébauche du PPTX ne constituent pas une exemption générale des obligations applicables. La note d’applicabilité doit distinguer le rôle de fournisseur et de déployeur, l’usage prévu et le mode réel de mise à disposition. Aucun marquage propriétaire, score ou nombre de tests n’est présenté ici comme une certification de conformité.

## Fonctions utiles à la conformité

- **Supervision humaine renforcée** : un statut que le dirigeant écrit dans son brief (décidée, réalisée, reportée, abandonnée) n'est jamais réécrit par le produit ; une décision qu'un agent s'attribue sans appui dans le brief est signalée « statut « décidé » non établi par le brief ». La recommandation des agents n'est plus présentée comme une décision du CoDIR.
- **Traçabilité des chiffres** : chaque valeur affichée sur une carte clé porte son exercice et, quand elle vient d'un dépôt public (SEC, Companies House, Pappers), sa source ; un chiffre contredit par la pièce ou par les dépôts est signalé avec la valeur de référence.
- **Modèle** : le modèle Anthropic par défaut devient Claude Sonnet 5.5, Claude Sonnet 4.5 étant retiré de l'API le 24/11/2026. Un changement de modèle peut modifier la forme des sorties : la revue humaine obligatoire et les garde-fous du produit s'appliquent inchangés.
