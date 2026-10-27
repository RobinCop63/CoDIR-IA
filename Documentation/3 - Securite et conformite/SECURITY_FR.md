# Politique de sécurité et divulgation coordonnée — CoDIR IA

**Logiciel :** CoDIR IA v17.0 — build `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`  
**Révision documentaire :** 18 octobre 2026  
**Usage :** professionnel supervisé

**Mise à jour :** 24 août 2026 · révision documentaire du 18 octobre 2026

## Canal de signalement actuel

Écrivez à **security@vauquigneux.com** (canal principal). En cas d'indisponibilité, le formulaire https://robinsauzet.com/contact/ sert de **repli** ; dans les deux cas, utilisez l’objet **`[SECURITY CoDIR IA]`**. Dans le premier message, indiquez uniquement : version, plateforme, catégorie d’impact, possibilité de reproduction et moyen de retour. Ne transmettez pas de secret, clé API, donnée personnelle ou preuve d’exploitation détaillée avant qu’un canal approprié soit convenu.

Ni la boîte dédiée ni le formulaire ne sont un canal chiffré de bout en bout : n’y déposez ni clés, ni mots de passe, ni documents clients. Si des éléments sensibles sont nécessaires, un canal adapté est convenu à la réponse. La mise à disposition d’une clé PGP reste une option, non une obligation déduite de cette politique.

## Versions supportées

La version courante, CoDIR IA v17.0, est supportée. Les correctifs de sécurité peuvent imposer une mise à niveau. Les anciennes versions sont analysées au cas par cas, sans garantie de correctif rétroporté.

## Délais de traitement cibles

- accusé de réception : 3 jours ouvrés ;
- première qualification : 7 jours ouvrés ;
- cadence de suivi : au moins tous les 14 jours pour un dossier ouvert.

Ces objectifs ne sont pas des SLA contractuels.

## Divulgation coordonnée

Le déclarant s’engage à éviter l’accès non autorisé, la persistance, l’exfiltration, l’altération et la publication prématurée. Vauquigneux Gestion s’engage à traiter de bonne foi les recherches raisonnables et à coordonner le calendrier de correction et de publication.

## CRA — procédure interne à partir du 11 septembre 2026

Dès que l’éditeur a CONNAISSANCE d’une vulnérabilité activement exploitée ou d’un incident sévère entrant dans le champ du règlement (UE) 2024/2847 — sans attendre sa confirmation interne —, le responsable désigné du signalement émet une alerte précoce sous 24 heures et une notification sous 72 heures via la plateforme de signalement applicable (CSIRT national / ENISA), puis les rapports selon les délais du règlement ; cette voie urgente ne passe ni par le délai de réception de trois jours ouvrés (support ordinaire — sans effet sur les délais légaux) ni par la qualification de sept jours du support ordinaire. Un faux positif de contrôle documentaire n’est pas un incident au sens du règlement. L’équipe désignée doit également préparer : alerte précoce sous 24 h ; notification sous 72 h ; rapport final de vulnérabilité au plus tard 14 jours après disponibilité d’une mesure corrective, ou rapport final d’incident dans le mois suivant la notification. Les notifications passent par la plateforme et le CSIRT coordinateur applicables. La qualification juridique et la responsabilité de fabricant doivent être confirmées pour le mode de distribution.

**Organisation actuelle :** Robin Sauzet, président de Vauquigneux Gestion, est le responsable désigné du signalement. **Aucun suppléant permanent n'est désigné à ce jour** ; en cas d'indisponibilité prévisible de plus de douze heures, un contact de secours est désigné par écrit pour la période, avec accès à la boîte. La désignation d'un relais permanent est en cours ; elle sera publiée ici lorsqu'elle sera arrêtée.

## Informations à conserver

Version et SHA, dates de connaissance, produits affectés, impact, mesures, utilisateurs concernés, journaux pertinents, décisions de divulgation, notifications et preuves de correction.

## Mesures de distribution

- manifeste SHA256SUMS vérifié ;
- dépendances verrouillées et SBOM ;
- secrets hors ZIP ;
- marquage des versions ;
- décision documentée sur la signature des artefacts réellement distribués, conservée hors archive ;
- aucune promesse de sécurité absolue.

## Référence officielle

Règlement sur la cyber-résilience (CRA) : https://eur-lex.europa.eu/eli/reg/2024/2847/oj/fra

## Signaler une vulnérabilité

Écrire à **security@vauquigneux.com**. Le premier message se limite à : la version du logiciel, la plateforme, une description non sensible et un moyen de retour. **Ne joignez ni clés, ni mots de passe, ni documents clients.** Si des éléments sensibles sont nécessaires, un canal privé adapté est convenu à la réponse. Les coordonnées et le contenu des messages reçus sont traités pour la seule instruction du signalement ; les modalités figurent dans la notice de confidentialité. Les délais internes de traitement ne s'appliquent pas aux obligations légales de signalement, qui courent à compter de la connaissance des faits.

## État réel des artefacts et preuve d’exploitation

Artefacts réellement livrés : lanceurs Windows .bat et scripts macOS .command non signés, distribués dans un ZIP ; le raccourci .app peut être créé localement. Le ZIP n’est pas présenté comme Authenticode-signé ; aucun ensemble applicatif Developer ID notarisé n’est fourni. Les avertissements du système sont attendus. Vérifiez la provenance, l’empreinte externe du ZIP et le manifeste ; ne désactivez pas globalement SmartScreen ou Gatekeeper. La décision sur les signatures, les preuves de test et l’approbation de diffusion restent hors de l’archive.

Le canal security@vauquigneux.com est le canal déclaré : sa seule mention ne constitue pas une preuve de réception. Conserver hors archive le test horodaté de réception, les accès habilités, le dispositif d’escalade et la matrice des machines testées. Les gardes sur les chiffres ne sont ni un scan de vulnérabilités ni une garantie de sécurité juridique ou financière.
