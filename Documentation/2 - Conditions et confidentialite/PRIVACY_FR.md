# Notice de confidentialité et flux de données — CoDIR IA

**Logiciel :** CoDIR IA v17.0 — build `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`  
**Révision documentaire :** 18 octobre 2026  
**Usage :** professionnel supervisé

**Éditeur :** Vauquigneux Gestion SASU, SIREN 102 885 654, 6 Cours des Vauquigneux, 35310 Mordelles, France  
**Date de référence initiale :** 16 mai 2026  
**Mise à jour :** texte contractuel inchangé depuis le 27 septembre 2026 ; révision éditoriale du 18 octobre 2026
**Statut :** notice produit ; les rôles RGPD doivent être qualifiés pour chaque déploiement

## 1. Absence de télémétrie éditeur et limites de cette notice

CoDIR IA v17.0 n’exploite aucun serveur applicatif propre et **aucune télémétrie éditeur** centralisée. L’application s’exécute localement. Elle conserve toutefois des réglages, cibles, caches, historiques, journaux et livrables sur le poste, et transmet des données aux fournisseurs activés par l’utilisateur.

Selon le contexte, l’entreprise cliente peut être responsable du traitement, Vauquigneux Gestion peut agir comme fournisseur du logiciel, prestataire ou sous-traitant, et les fournisseurs d’API peuvent être sous-traitants ultérieurs ou responsables distincts. Cette qualification doit être fixée dans le contrat et, si nécessaire, dans un accord conforme à l’article 28 du RGPD.

## 2. Catégories de données et finalités

| Catégorie | Finalité produit | Emplacement / destinataire | Conservation indicative |
|---|---|---|---|
| Clés API | Authentifier les appels choisis | `secrets.json`, local | Jusqu’à suppression |
| Réglages et cible canonique | Cohérence inter-écrans | `settings.json`, local | Jusqu’au changement |
| Caches registres et documents | Performance, quotas, continuité | dossier `cache`, local | TTL du module ou purge |
| Historique de dossier | Continuité de suivi | dossier `data`, local | Jusqu’à suppression |
| Journaux | Diagnostic et sécurité | dossier `logs`, local | rotation ; 14 sauvegardes pour `codir-ia.log` |
| Briefs et extraits de pièces | Analyse par les modèles | fournisseurs configurés | selon le contrat fournisseur |
| Identifiants d’entreprise | Résolution registre ; faits financiers publiés (dernier réalisé daté) | Pappers, Companies House, GLEIF, SEC… | selon le fournisseur |
| Livrables | Travail professionnel | `outputs` et emplacement choisi | jusqu’à suppression |

**Faits financiers publiés.** Pour la règle du dernier réalisé daté et les contrôles sur l'exercice antérieur, CoDIR IA lit, auprès de la SEC, de Companies House et de Pappers, des montants déjà publiés par la société. Seul l'identifiant de la société (CIK, numéro Companies House, SIREN) est envoyé, avec, pour la SEC, le contact d'identification qu'elle exige. Aucune pièce du client, aucun brief ni aucun extrait n'est transmis à ces services. GLEIF ne fournit que l'identité juridique.

## 3. Emplacements locaux canoniques

- Windows : `%APPDATA%\CoDIR-IA` (configuration) et `%LOCALAPPDATA%\CoDIR-IA` (cache, venv, logs installateur) ;
- macOS : `~/Library/Application Support/CoDIR-IA` ;
- Linux : `$XDG_CONFIG_HOME/CoDIR-IA` ou `~/.config/CoDIR-IA`.

Les lanceurs définissent explicitement `CODIR_CONFIG_DIR` et `CODIR_CACHE_DIR` dans les lanceurs. Les anciens dossiers `~/.codir_ia` restent lisibles uniquement pour migration ; la procédure de suppression les mentionne.

## 4. Données transmises

Selon les fonctions activées, peuvent être transmis : le texte du brief, le texte extrait des pièces, des blocs financiers pertinents, des instructions de rôle, des identifiants légaux, des requêtes de recherche ou registre et des métadonnées techniques minimales. Les fichiers bruts ne sont envoyés que lorsqu’une fonction le prévoit explicitement.

Les fournisseurs possibles sont documentés dans `SUBPROCESSORS_AND_TRANSFERS.md`. Le statut, le lieu de traitement et les garanties dépendent du compte et du contrat souscrits par l’utilisateur ; le logiciel ne doit pas présumer d’une région ou d’un mécanisme de transfert.

## 5. Bases légales et information des personnes

La base légale dépend du déploiement : exécution d’un contrat, intérêt légitime, obligation légale ou consentement lorsque requis. Le responsable du traitement doit remettre une information conforme aux articles 12 à 14 du RGPD, documenter sa base légale, minimiser les données et organiser l’exercice des droits.

## 6. Droits des personnes

Selon le contexte, les personnes peuvent disposer de droits d’accès, rectification, effacement, limitation, opposition, portabilité et retrait du consentement. Elles peuvent saisir la CNIL. Les demandes concernant des données locales relèvent de l’organisation qui exploite le poste ; les demandes relatives à un fournisseur doivent suivre son contrat et sa procédure.

## 7. Sous-traitance et transferts

Lorsqu’un traitement est réalisé pour le compte d’un client, un accord conforme à l’article 28 doit préciser l’objet, la durée, la nature, les finalités, les catégories de données et de personnes, les instructions, la sécurité, les sous-traitants ultérieurs, l’assistance, la restitution/suppression et l’audit. Un modèle de travail figure dans le modèle d'accord de traitement (non inclus dans cette distribution ; fourni sur demande dans le cadre contractuel).

Les transferts hors EEE doivent être cartographiés et reposer sur un mécanisme approprié : décision d’adéquation, clauses contractuelles types, BCR ou autre garantie prévue par le chapitre V du RGPD, avec évaluation complémentaire si nécessaire.

## 8. Sécurité et minimisation

L’utilisateur doit exclure les données inutiles, pseudonymiser lorsque possible, limiter les pièces au besoin professionnel et vérifier les paramètres de conservation des fournisseurs. Les clés sont locales en clair dans CoDIR IA v17.0 ; un coffre de secrets d’entreprise est recommandé pour les usages sensibles.

## 9. Effacement et désinstallation

La suppression locale complète inclut : dossier de configuration, dossier cache, ancien `~/.codir_ia` le cas échéant, dossier d’installation, venv, outputs et raccourcis. Les données déjà transmises à un fournisseur doivent être traitées selon son contrat et ses outils.

## 10. Contact

Demandes initiales : https://robinsauzet.com/contact/. Pour une demande RGPD liée à un déploiement client, contactez d’abord l’organisation responsable du traitement indiquée dans sa propre notice.

## 11. Références officielles

- RGPD : https://eur-lex.europa.eu/eli/reg/2016/679/oj/fra
- CNIL — information des personnes : https://www.cnil.fr/fr/conformite-rgpd-information-des-personnes-et-transparence
- CNIL — travailler avec un sous-traitant : https://www.cnil.fr/fr/sous-traitant
- CNIL — transferts hors UE : https://www.cnil.fr/fr/les-outils-de-la-conformite/transferer-des-donnees-hors-de-lue

## Mode local, appels externes et traitements propres à l'éditeur

CoDIR IA fonctionne localement, avec des appels aux services externes que vous activez. La mise à disposition du logiciel ne donne pas, à elle seule, à Vauquigneux Gestion un accès au contenu de vos analyses. Trois choses se distinguent : le fonctionnement local (vos pièces, vos caches et vos journaux restent sur votre poste) ; les transmissions aux fournisseurs que vous activez, régies par vos comptes et leurs conditions ; et les traitements propres à l'éditeur — contact, support, signalements de sécurité — décrits dans la section qui leur est consacrée.

**Rôles en matière de données personnelles.** Ils dépendent des traitements réellement réalisés. Vous pouvez agir pour votre propre compte ou pour celui d'un client ; les fournisseurs que vous activez peuvent former une chaîne de sous-traitance à qualifier. Avant tout traitement de données personnelles pour le compte d'un tiers, les instructions, garanties, autorisations et contrats applicables sont établis — y compris pour un pilote ou une assistance gratuits : **le prix n'est pas le déclencheur**. La seule confidentialité d'un document, sans données personnelles, relève d'autres autorisations et n'impose pas à elle seule un accord de traitement.

**Sources, transferts et vérification.** La disponibilité d'un document, d'un service ou d'une interface n'établit pas un droit de transmission ou de redistribution. Les conditions, les paramètres de conservation et d'utilisation des contenus, et les garanties de transfert dépendent des services et des comptes que vous utilisez : vérifiez-les pour votre rôle. Une référence à un contrat fournisseur ne vaut pas validation de tous les déploiements.

## Traitement des signalements de sécurité et des demandes de support

**Responsable :** Vauquigneux Gestion SASU, éditeur de CoDIR IA. **Finalités :** instruire un signalement de vulnérabilité ou une demande de support, vous répondre, et conserver la trace des décisions prises. **Données traitées :** adresse de messagerie, identité que vous communiquez, contenu de votre message et pièces que vous joignez. **Base légale :** intérêt légitime de l'éditeur à sécuriser son produit et à répondre aux signalements ; exécution de mesures précontractuelles ou contractuelles lorsque la demande s'inscrit dans une relation d'affaires. **Destinataires :** la ou les personnes habilitées chez l'éditeur ; le service de messagerie professionnelle utilisé pour héberger la boîte `security@vauquigneux.com`, dont les conditions et les paramètres de conservation relèvent du contrat de l'éditeur avec ce fournisseur. **Conservation :** le dossier actif est conservé le temps de l'instruction et de la clôture ; les éléments nécessaires à la preuve d'un signalement réglementé sont archivés séparément, avec un accès restreint, selon la durée justifiée par cette finalité. **Vos droits :** accès, rectification, effacement, limitation et opposition s'exercent à la même adresse ; vous pouvez saisir la CNIL. **Recommandation :** n'envoyez ni secrets, ni données personnelles inutiles, ni documents clients.

## Gardes, mémoire et transmission : limites pratiques

Local ne signifie pas hors ligne. L’interface, le stockage et les gardes s’exécutent sur le poste ; les fournisseurs d’IA, registres et recherches activés reçoivent les contenus nécessaires selon les fonctions. Les gardes ne constituent ni une anonymisation ni un pare-feu avant transmission. Le brief, les extraits et, selon le contexte transmis, des éléments d’historique peuvent quitter le poste. Vérifiez vos droits et les comptes fournisseurs avant lancement.

Mémoire entre CoDIR. Le code comporte un historique local par dossier et un registre d’actions horodaté. Réutilisez le même dossier — même « Libellé de dossier » d’une séance à l’autre — et vérifiez l’entité, l’identifiant, le répertoire de données et la date d’analyse. Dans le nouveau brief, précisez les décisions réellement approuvées, les actions réalisées ou reportées et les clôtures explicites. Relisez ensuite les reprises et les écarts : une proposition ne devient pas approuvée par simple répétition. Les modes rétrospectif/futur n’écrivent pas le registre vivant ; la case « Repartir de zéro — ignorer l’historique de ce dossier » (variable technique CODIR_IGNORE_HISTORY) neutralise la reprise pour un test isolé. La reprise exhaustive des décisions, actions et questions sur deux séances n’est pas certifiée par cette révision documentaire ; elle reste à vérifier sur votre dossier. Ce n’est ni une mémoire de toutes les conversations ni un apprentissage du modèle.

Les registres, historiques, réponses archivées et journaux peuvent conserver des contenus absents du corps des livrables. Le retrait d’un chiffre d’un Word n’efface pas ses occurrences dans les autres fichiers ou chez les fournisseurs. Vérifiez le paquet avant tout partage ; sauvegardez et supprimez aussi les données de dossier selon votre politique de conservation. La présente révision ne crée pas de coffre chiffré, de purge distante ni de contrôle automatisé de la licéité.
