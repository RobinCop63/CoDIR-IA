# Où vivent mes données ? — CoDIR IA v17.0

**Logiciel :** CoDIR IA v17.0 — build `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`  
**Révision documentaire :** 18 octobre 2026  
**Usage :** professionnel supervisé

| Plateforme | Configuration | Cache | Données/historique | Logs |
|---|---|---|---|---|
| Windows | `%APPDATA%\CoDIR-IA` | `%LOCALAPPDATA%\CoDIR-IA\cache` | `%APPDATA%\CoDIR-IA\data` | configuration/logs et LocalAppData/logs installateur |
| macOS | `~/Library/Application Support/CoDIR-IA` | `…/cache` | `…/data` | `…/logs` |
| Linux | `$XDG_CONFIG_HOME/CoDIR-IA` | `$XDG_CACHE_HOME/CoDIR-IA` | config/data | config/logs |

L’ancien `~/.codir_ia` peut être lu pour migration. Après vérification, il doit être supprimé lors d’une désinstallation complète.

Les briefs et extraits nécessaires peuvent être transmis aux fournisseurs activés. Voir `PRIVACY_FR.md`, `PRIVACY_EN.md` et `SUBPROCESSORS_AND_TRANSFERS.md`.

Selon la fonction, le texte intégral du brief et le texte extrait des pièces jointes peuvent être transmis aux fournisseurs activés.

Local ne signifie pas hors ligne. L’interface, le stockage et les gardes s’exécutent sur le poste ; les fournisseurs d’IA, registres et recherches activés reçoivent les contenus nécessaires selon les fonctions. Les gardes ne constituent ni une anonymisation ni un pare-feu avant transmission. Le brief, les extraits et, selon le contexte transmis, des éléments d’historique peuvent quitter le poste. Vérifiez vos droits et les comptes fournisseurs avant lancement.

Mémoire entre CoDIR. Le code comporte un historique local par dossier et un registre d’actions horodaté. Réutilisez le même dossier — même « Libellé de dossier » d’une séance à l’autre — et vérifiez l’entité, l’identifiant, le répertoire de données et la date d’analyse. Dans le nouveau brief, précisez les décisions réellement approuvées, les actions réalisées ou reportées et les clôtures explicites. Relisez ensuite les reprises et les écarts : une proposition ne devient pas approuvée par simple répétition. Les modes rétrospectif/futur n’écrivent pas le registre vivant ; la case « Repartir de zéro — ignorer l’historique de ce dossier » (variable technique CODIR_IGNORE_HISTORY) neutralise la reprise pour un test isolé. La reprise exhaustive des décisions, actions et questions sur deux séances n’est pas certifiée par cette révision documentaire ; elle reste à vérifier sur votre dossier. Ce n’est ni une mémoire de toutes les conversations ni un apprentissage du modèle.

Les fichiers JSONL du registre résident dans le répertoire de données effectif, sous `codir_register`. Une copie de l’installation sans ce répertoire ne constitue pas une sauvegarde de la mémoire.
