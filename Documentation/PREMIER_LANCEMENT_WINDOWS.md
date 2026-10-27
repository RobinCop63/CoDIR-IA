# Premier lancement Windows — CoDIR IA v17.0

**Logiciel :** CoDIR IA v17.0 — build `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`  
**Révision documentaire :** 18 octobre 2026  
**Usage :** professionnel supervisé

Vérifiez le SHA-256 externe du ZIP puis le manifeste après extraction. Utilisez un dossier local non synchronisé et `DEMARRER_CODIR_IA.bat`. Le lanceur prévoit le contrôle de `SHA256SUMS` avant le déblocage ; un contrôle d’intégrité ne prouve pas que le logiciel est sans défaut.

Artefacts réellement livrés : lanceurs Windows .bat et scripts macOS .command non signés, distribués dans un ZIP ; le raccourci .app peut être créé localement. Le ZIP n’est pas présenté comme Authenticode-signé ; aucun ensemble applicatif Developer ID notarisé n’est fourni. Les avertissements du système sont attendus. Vérifiez la provenance, l’empreinte externe du ZIP et le manifeste ; ne désactivez pas globalement SmartScreen ou Gatekeeper. La décision sur les signatures, les preuves de test et l’approbation de diffusion restent hors de l’archive.

Après démarrage, vérifiez la cible, le périmètre, **la date d’analyse voulue** et les clés. Ne passez pas en LIVE pour contourner une analyse rétrospective. Les chemins configuration/cache/données sont distincts du ZIP. Les architectures déclarées doivent être confrontées à la matrice de tests natifs.

Le lanceur cherche un CPython standard compatible avec la plage prévue 3.11–3.14. Si le mode verrouillé échoue et qu’un repli requirements.txt est utilisé, l’environnement ne correspond plus exactement au verrou ni au SBOM : conservez INSTALL_MODE.txt et le journal, puis faites vérifier ce déploiement. La présence d’un lanceur ne certifie pas une plateforme ou une architecture ; consultez la matrice de tests natifs applicable. Les variantes Python free-threading / no-GIL sont refusées ; un CPython standard est requis. Windows ARM64 est prévu sous réserve de la disponibilité des wheels binaires (le lanceur sélectionne une architecture compatible) ; confrontez-le à la matrice de tests natifs.

Voir les fichiers `INSTALL_WINDOWS_FR.md` et les manuels complets dans `1 - Manuels d'utilisation`.
