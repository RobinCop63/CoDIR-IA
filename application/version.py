"""
CoDIR-IA — Source unique de vérité de version.

Convention : un seul endroit dans tout le code où la version est déclarée.
Tous les autres fichiers (app.py, codir_engine.py, setup scripts, docs, manuels)
soit importent depuis ici, soit sont validés par le test anti-drift.

Usage :
    from version import APP_VERSION, APP_VERSION_SHORT, RELEASE_DATE

Constantes :
    APP_VERSION        : "v16.5.76"
    APP_VERSION_SHORT  : "16.5.76"  (sans le préfixe v — pour os.path, setup.py...)
    RELEASE_DATE       : "2026-05-16"  (date de l'APP_VERSION, pas du build)
    BUILD_DATE         : "2026-09-07"  (date du build courant — réf. CITATION.cff)
    RELEASE_NAME       : "Sprint pre-packaging v17 — UX/UI quick wins, supply chain robustesse, JSON schema étendu, web search, alertes orange, delta runs"
    BUILD_VERSION      : "v17.4.3.62.13.9.4.11-M6B-B1.3.62.13.9.4.11"  (build mission-grade ; ancre anti-drift = APP_VERSION)
"""
import re

# v62.13.9.4.5 — identité de l'éditeur (AI Act art. 50(2) « provider », tag de
# couverture, marquage OOXML). Exception explicite, générique, versionnée et
# gouvernée au sens du contrat anti-hardcoding : la seule occurrence licite du
# nom de l'éditeur dans le code vit ici.
# v62.13.9.4.9 — dénomination sociale complète (contre-audit 30/08/2026,
# préconisation métadonnées) : le marquage AI Act art. 50 désigne un
# responsable juridique, qui doit porter son identité exacte.
PUBLISHER         = "Vauquigneux Gestion SASU"

APP_VERSION       = "v16.5.76"
# 9.4.65 — gel v17 (21/10/2026) : APP_VERSION reste l'ancre interne de filiation du moteur (contrats
# historiques) ; ce qui est affiché à l'utilisateur et dans les documents remis est le libellé PRODUIT.
PRODUCT_VERSION   = "v17.0"
APP_VERSION_SHORT = "16.5.76"
# RELEASE_DATE date l'APP_VERSION ci-dessus (livrée le 16/05/2026) — elle ne
# date PAS le build courant, et un contrat de test historique la verrouille.
# v62.13.9.4.9 : BUILD_DATE est ajoutée pour porter la date du build, seule
# valeur avec laquelle CITATION.cff doit s'aligner. La fusion des deux
# (APP_VERSION → v17, RELEASE_DATE → date de release) est arbitrée au gel v17,
# pas ici : renuméroter APP_VERSION sans renuméroter la ligne produit
# créerait une version « publiée deux fois ».
RELEASE_DATE      = "2026-05-16"
BUILD_DATE        = "2026-09-27"
RELEASE_NAME      = "Sprint pre-packaging v17 — UX/UI quick wins, supply chain robustesse, JSON schema étendu, web search, alertes orange, delta runs"

# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.13.9.4.9 — Fermeture du contre-audit ChatGPT 9.4.8 (NO-GO,
# 30/08/2026), cinq blockers fermés sur pièces :
#  • claim_binding REFONDU (P1-948-03) : parse décimal exact (15,0 ≠ 150),
#    échelle appliquée en valeur absolue (15 M€ ≠ 15 k€), devise affirmée ⇒
#    devise certifiée, métrique jugée tête puis voisinage puis ligne, période
#    et périmètre en dimensions dures, statuts en LISTE FERMÉE exacte ;
#    primauté du passé factuel ajoutée (« Inventories changed by » est un
#    fait). Auto-support 18/18 sur les claims réels, 7 collisions fermées.
#  • Exemption de tableau liée au CLAIM, jamais au tag (P1-948-02) :
#    _confirmed_row_cells supprimé des deux côtés de la chaîne ; la zone A du
#    proof layer survit par liaison de PROVENANCE au registre du moteur
#    (financial_facts_table), qui résiste à la forge, au détournement vers une
#    cible et à l'altération de valeur ; tables PPTX enfin jugées et réparées
#    (limite documentée en 9.4.8 levée) ; parité rangée non certifiée.
#  • INVERSION DE CHARGE sur les phrases de plan (P1-948-01) : sujet-artefact
#    de planification, volition ou qualificatif futur ⇒ toute grandeur non
#    exemptée est prospective, quel que soit le verbe — fin des grilles
#    sujet × verbe. Primauté du signal de cible étendue au STATIF ; participes
#    de volition (« desired ») exclus du passé factuel ; participes
#    d'engagement (« engagé en 2025 ») admis hors futur dominant.
#  • SECOND JUGE INDÉPENDANT (utils/independent_content_judge.py) : écrit
#    sans aucun import des moteurs de production, tables propres, verdict de
#    l'oracle par UNION, câblé aussi à la couche de décision de la réparation.
#  • FAIL-CLOSED INTÉGRAL (P1-948-04) : import des juges, extraction OOXML,
#    référentiel d'autorité et finaliseur PPTX — toute indisponibilité bloque
#    la distribution ; un juge muet n'est pas un juge favorable.
#  • Fast-path sectoriel nommé rendu GOUVERNABLE (P1-948-05) : interrupteur
#    CODIR_SECTOR_KB / CODIR_SECTOR_KB_EXCLUDE, cinq tests, protocole de
#    shadow run écrit ; le run LLM comparatif reste à la main de l'éditeur.
#  • Corpus immuable n°5 scellé (11 cibles, 2 rangées, 6 témoins) et
#    indépendance des juges prouvée par neutralisation croisée.
#  • Métadonnées : PUBLISHER porte la dénomination sociale complète,
#    BUILD_DATE ajoutée (CITATION.cff s'aligne dessus) ; RELEASE_DATE reste
#    liée à APP_VERSION, fusion arbitrée au gel v17.
#
# v17.4.3.62.13.9.4.8 — Fermeture du contre-audit ChatGPT 9.4.7 (NO-GO) :
# oracle de contenu câblé au RUNTIME (app.py, finaliseur PPTX — dégel déclaré
# du gel historique « PPTX finalizer core ») : verbatim et payloads quantifiés
# des retenues du run sur toutes les surfaces OOXML, re-jugement en appel
# séparé des surfaces de contenu sous contexte de run (doctrine 13.9.2) ; un
# survivant force DocxSafetyBlock / distributable=False même gate
# artificiellement vide, la cible est nommée ; détection générique des
# formulations prospectives inconnues (sujets-plan × verbes de contenu
# bidirectionnels, aim/strive/seek/intend/plan to, d'ici/by (FY)20XX,
# infinitifs prospectifs « à ouvrir ») ; tags de preuve de tête neutralisés à
# longueur constante (« CONFIRMED | » n'est plus un verbe au passé) ; rangées
# de preuve sous tags CONFIRMED/VALIDATED/VERIFIED/APPROVED ; « couche 1 »
# conservé verbatim (couches/layers/modules/paliers/strates = numérotation
# descriptive) ; références réglementaires typées identifiants (la bannière
# AI Act des pieds de page, jamais lue par le gate, révélée par l'oracle) ;
# claim binding probatoire (CONFIRMED*/DERIVED*/VERIFIED* seulement, identité
# de métrique par label de tête : Marge ≠ Réseau) ; suite unifiée
# tests+patches/tests (5203 collectés) adoptée comme run canonique unique ;
# dossier anglophone coté PPTX chaîne complète zéro strict, deck final hashé ; amendement
# déclaré n°1 (4_6b) ; campagne terrain RÉELLE du 13/08/2026 rejouée en
# chaîne complète (filiation SHA vérifiée) — VERT, promue cas de régression
# automatisé ; trois trous terrain fermés (HCRIT jugées sous contexte 13.9.2,
# montants tri-state retirés trace conservée, réconciliation marché
# propagée) ; parité rangée-preuve/cellule-contenu entre réparation et
# oracle ; dégels déclarés editorial_quantity et monolingual_rewriter
# (langue de ligne €/an).
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.13.9.4.7 — Fermeture du contre-audit ChatGPT 9.4.6 (NO-GO) :
# autorité structurée {valeur, unité, rôle sémantique} — une valeur nue
# n'autorise jamais ({"24"} échoue par contrat) ; primauté absolue des
# signaux de cible/projection (le passé factuel réel prime) ; oracle
# indépendant des octets finaux sur toutes les surfaces OOXML — plus aucune
# exception d'annexe, de registre SCN, de quarantaine sérialisée, entrées
# héritées neutralisées sur place ; réécritures monolingues canoniques
# (langue de la ligne, dix sorties figées, hybrides morts) ; imparfait et
# passé simple français protégés avec parité anglaise ; « score » nombre-mot
# uniquement sous déterminant numérique ; harnais brut du contre-auditeur
# rejoué à l'identique, fixtures normatives n°4/n°1/RW à empreintes figées,
# terrain dossier de conseil jusqu'aux fichiers finaux ; amendements déclarés n°1-5.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.13.9.4.6 — Fermeture du contre-audit ChatGPT 9.4.5 (NO-GO) :
# registre des quantités typé en socle unique (deny-by-default : toute
# quantité non exemptée exige un type descriptif certain ; les verbes
# affinent, n'autorisent jamais), 21 formes verbatim du contre-auditeur en
# fixture n°3 SHA-figée, replays terrains dossier industriel/dossier anglophone coté dans la suite
# obligatoire (0 résidu, appareil conservé), affichage des valeurs nues lié
# aux faits confirmés du ledger, porte étroite 13.9.2 (mot-cible + date :
# seule la date d'autorité), scission tags produit/contenu (une étiquette
# n'est jamais une preuve), pré-passe Finance spécialiste avant passe
# générique, configurations actives gouvernées (distribution neutre,
# scanner étendu, registre sectoriel documenté), marque « CoDIR IA »
# enregistrée (certificat n° 26 5245108) dans TRADEMARKS.md.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.13.9.4.5 — Fermeture du contre-audit ChatGPT 9.4.4 : liaison
# stricte par claim (métrique/unité/contexte — collision numérique fermée),
# second détecteur autonome au gate final (désaccord = blocage), fermeture
# simultanée des 20 faux négatifs et des faux positifs du corpus inédit,
# restauration qualitative R&D, contrat de sortie « retenu ⇒ réécrit ou
# retiré », scanner anti-hardcoding AST (f-strings), identité éditeur
# gouvernée (version.PUBLISHER), SBOM 83/83 licences + hashes, manuels
# restructurés (titre premier, historique en fin), gates légaux dossier réseau de soins.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.13.9.4.4 — Fermeture du contre-audit ChatGPT 9.4.3 : décision
# cardinal-déclenchée partagée (morphologie des verbes, nombres en lettres,
# plages « à », placeholders), identifiants protégés (ISO, niveaux), statuts
# neutres du guard (zéro recommandation), gate indépendant sur fichiers
# sérialisés, corpus adversarial en fixture à SHA figé, alias d'entités et KB
# sectorielle externalisés en configuration, micro-dégel du tag de couverture.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.13.9.4.3 — Généralisation éditoriale après contre-audit 9.4.2 :
# invariant de sortie (aucun cardinal non validé sur les surfaces principales,
# quel que soit le vocabulaire), décision générique action+cardinal+nom aux deux
# couches, titres jamais remplacés, littéraux de dossier retirés, guard sans
# censure des dates d'octobre. Gels v17.x maintenus (13/13).
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.13.9.4.2 — Fermeture dossier réseau de soins bornée après contre-audit 9.4.1 :
# tranches Sirene généralisées, pendule 18/18, réparation DOCX non destructive
# et idempotente, contrats dossier industriel honnêtes. Micro-dégel du board guard seul ;
# Financial Proof Layer, extracteur, Temporal Core, moteur et chaîne PPTX gelés.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.13.9.4.1 — Contrats éditoriaux dossier industriel sur artefacts réels :
# titres/qualitatif préservés, quantités d’action retenues, faits sociaux qualifiés,
# date Temporal Core avec marqueur décoratif restaurée, codes produit exclus du
# numérique, fallbacks agrégés et replay DOCX/PPTX déterministe. Aucun OCR ajouté.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.13.9.3 — Intégrité des titres HCRIT et vérité de livraison :
# les payloads commerciaux conservent leur texte complet jusqu'au renderer ;
# tout titre exécutif déjà tronqué est remplacé par une formulation qualitative
# complète avant validation ; l'UI distingue corruption OOXML, titre tronqué et
# illisibilité. SCN-009 ferme la date de fin cible du Temporal Core courant.
# Aucun OCR ajouté ; Financial Proof Layer, H-v2 et paging inchangés.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.13.9.2 — Autorité factuelle et horizon de planification : seules
# les valeurs du Temporal Core autorisent une ligne d'horizon ; les durées
# opérationnelles restent gouvernées. Les balises FACT/FAIT, noms de source et
# pages ne valent jamais preuve : chaque nombre exécutif doit correspondre à un
# claim canonique page-confirmé ou à un dérivé déterministe de même métrique et
# période. Les formulations supportées sont réécrites en claim propre.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.13.9.1 — Micro-train retiré après contre-audit : les trois horizons
# nominaux et le lexique partenaires/délai étaient fermés, mais l'exemption
# générique des durées et le carve-out FACT n'étaient pas adossés au Temporal
# Core ni au ledger. Conservé ici uniquement pour la traçabilité.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.13.8 — Autorité bornée au run courant et vue éditoriale immuable :
# historique, sources, inputs, claims et diagnostics bruts restent intouchables ;
# preuve consolidée positive uniquement sur fait groupe page-confirmé ; exemption
# date-seule stricte ; pont CSV brut/effectif/requalifications/fingerprint ;
# documentation courante FR/EN resynchronisée. Aucun OCR ajouté.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.13.7 — Correctif de scellement H1-H6 du train dossier industriel FR ;
# remplacé par v62.13.8 après sondes d'autorité historique et d'immutabilité.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.13.6 — Hotfix statique F821 : suppression d'une branche morte
# dans repair_docx_executive_numbers. Aucun changement de comportement runtime,
# de moteur analytique, de preuve, de renderer, de plateforme ou de documentation
# juridique ; la v62.13.4 reste intégralement héritée.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.13.4 — Consolidation post-run dossier anglophone coté : scénarios transposés
# et narratifs confinés, atomicité multi-nombres des claims, KPI sémantiques
# issus du ledger, conflits historiques visibles, déduplication des fallbacks
# et morphologie FR approbation/ratification. Aucun nouveau rerun dossier anglophone coté requis.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.13.2 — Durcissement des claims et doctrine Option B :
# alias métriques à frontières lexicales, ventes comparables distinctes du CA,
# morphologie d'engagement bornée, formats monétaires FR natifs, réparation
# d'emphase non destructive, scénarios chiffrés confinés en annexe Word et
# restauration des manuels complets avec guides de démarrage rapide séparés.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.13.1 — Consolidation autorité financière et surfaces exécutives :
# périodes normalisées, séparation preuve/rôle canonique, branchement du vrai
# fact_conflict_b1, claims financiers canoniques/derivés partagés Word/PPTX,
# réparation du PPTX terrain du 21/08, tables-cibles toujours quarantainées et
# réparation déterministe des fragments de section incomplets. Extracteur FS,
# Temporal Core, H2, renderer/paging restent gelés.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.13.0 — Première candidate autorité de période / contrôle numérique
# différencié, retirée après contre-audit adversarial (regroupement par période,
# dates non normalisées, fact_conflict_b1 non câblé et fixture PPTX insuffisante).
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.12.8.2 — Hotfix lanceurs Python : sélection explicite d’un
# interpréteur CPython standard, support 3.10–3.14, diagnostic distinct des
# versions trop anciennes/récentes et builds free-threading, code d’échec non
# nul et cohérence Windows/macOS. Runtime métier/DOCX/PPTX inchangé.
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.12.8.1 — Hotfix de contre-audit : import Mapping restauré,
# persistance de cible strictement ciblée (aucune date de session durable),
# isolation hermétique du profil de tests, suppression du code mort et matrice
# Python active bornée à 3.10–3.13. Runtime DOCX/PPTX v62.12.8 inchangé.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.12.8 — Stabilisation runtime et release : réparation déterministe
# du contrôle numérique DOCX sérialisé (cause probable du RuntimeError terrain),
# diagnostic explicite et E2E 86 fragments, identité cible canonique persistée,
# logger crash rotatif réel, settings atomiques/privés, documentation FR/EN,
# chemins OS, confidentialité, SBOM et cadre juridique resynchronisés.
# Financial Proof Layer, priorité PDF, Working Deck et paging inchangés.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.12.4 — Fermeture de classe du confinement des scénarios :
# quarantaine sans plafond fonctionnel, fragmentation d'annexe à 250 lignes,
# frontières FACT/FAIT et titres métier, post-audit des lignes tabulaires
# numériques orphelines, vérification exacte ZIP ↔ SHA256SUMS. Paging inchangé.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.12.2 — Fermeture adversariale des huit réserves du run dossier anglophone coté :
# budget réellement réservé aux documents financiers courants et failover review,
# vérité financière finale unique intégrant le registre, mission gate aligné,
# matérialité monétaire relative, confinement effectif des scénarios (tableaux
# inclus), post-contrôle OOXML Word/PPTX et scellement sans outputs runtime.
# Working Deck et paging inchangés.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.12 — Lot de consolidation vérité financière : autorité absolue de
# la période page-confirmée, suppression des estimations d'exercices clos,
# croissance calculée depuis les faits canoniques, scénarios chiffrés confinés
# en annexe Word, parité des claim_id Word/PPTX, extinction des messages legacy,
# hiérarchie PDF primaire, année CERFA robuste et ingestion liasse native.
# Working Deck et paging inchangés.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.11.3.2 — Stabilisation terrain dossier anglophone coté : priorisation PDF
# enrichie par un aperçu natif du contenu lorsque le navigateur fournit un nom
# court 8.3 ; cache/politique versionnés, cap preuve/utilité cohérent lorsque la
# vérité financière actuelle est absente, garde Board durcie sur les chiffres
# prospectifs et wiring des comptes détectés vers le Word. Paging inchangé.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.11.3.1 — Stabilisation du deep scan : invalidation obligatoire
# du cache après changement de priorité, hiérarchie audité > préliminaire >
# intermédiaire > présentation, diagnostic de rang/score par PDF et E2E exact
# annual-report à tirets dans un corpus riche. Aucune modification du paging.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.11.2 — Deep-scan pipeline recovery: restores the documented PDF
# budgets/constants imported by app.py, removes the silent failure path, emits
# structured diagnostics, prioritises Financial Review pages and proves the
# exact upload → deep scan → page-confirmed ledger composition on an 18-PDF
# dossier anglophone coté corpus. Financial Proof Layer semantics and Working Deck geometry
# remain unchanged.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.10.2 — Fail-closed current-financial-truth hotfix: when the
# latest registry filing is newer than the latest parsed period, a hard metric
# conflict remains, or no critical fact is page-confirmed in BOARD_SCRUTINY,
# quantified current-state claims are withheld and decision usefulness is capped
# to exploratory use. The full parser remains the separate v62.11 build.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.10 — Truth-governance micro-cycle after the dossier anglophone coté run:
# canonical registry identity drives titles and proof scope; listed groups cannot
# remain PME; two-year / 24-month horizons are multilingual and anchored to the
# actual run date; unsupported executive targets are withheld in BOARD_SCRUTINY;
# registry-period versus parsed-period traceability, localized mission statuses,
# named score stages and quieter entity diagnostics are added. The page-confirmed
# financial proof parser is deliberately deferred to the separately specified
# v62.11. Working Deck geometry remains frozen.
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.8 — Micro-cycle dossier agroalimentaire : le SIREN explicite du brief devient
# immuable face à une session obsolète ; le profil groupe industriel et la
# Supply Chain sont réconciliés depuis le brief ; l'horizon stratégique 24 mois
# est conservé ; les faits documentaires page-cités irriguent la proof layer
# sans débloquer les calculs consolidés ; Finance, registre, réserves et scores
# sont durcis. Le Working Deck v62.7 reste gelé et inchangé.
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.3.62.6 — Fermeture générique des défauts révélés par le rerun du 13/08 :
# les scénarios illustratifs sont exclus des KPI exécutifs, toutes les familles
# HCRIT passent par le même contrat de capacité, la Finance est reconstruite en
# CA brut uniquement sans preuve primaire, les preuves marché restent fail-closed,
# les alertes juridiques vides et relances automatiques de test sont neutralisées,
# et les contacts cabinets sont routés vers Commercial. Candidate terrain
# supervisée ; aucune diffusion externe telle quelle.
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# v17.4.0-M6B-B1.0 — M6-B · B.1 (couche de preuve, increment 1). Contrat :
# note référente M6-B v3 (D1-D10) + plan B.1 (E1→E8). Livré : analysis_context
# auto-prouvé (D6), schéma de fait complet + identité 5 clés (D7/E1),
# perimeter_match FULL/COVERAGE/MISMATCH + exclusion du signal (E3, fix v5
# dossier industriel (composants)), fact_conflict avec sévérité (D9/E4), garde conso D4 (E5),
# board-safe blockers posés (§8.3, gate enforcé en B.4a), run_fingerprint (E6),
# rendu minimal périmètre/conflit (E7). APP_VERSION reste l'ancre anti-drift.
# ─────────────────────────────────────────────────────────────────────────────
BUILD_VERSION = 'v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65'
BUILD_NAME    = (
    "v17.4.3.62.13.9.4.11-M6B-B1.3.62.13.9.4.11 — runtime-oracle editorial release candidate (dossier industriel/dossier réseau de soins train); "
    "Option B strict, production second judge wired into the export path (withheld verbatim and quantified payloads on "
    "ALL OOXML surfaces, separate content re-judgement under run context; a survivor forces non-distribution even with "
    "an artificially empty gate, the target is named), generic unknown-formulation detection (plan-subjects x content "
    "verbs, aim/strive/seek/intend/plan-to, d'ici/by 20XX deadlines, prospective infinitives), leading proof-tags "
    "neutralised at constant length (CONFIRMED| never whitewashes), probative claim binding (confirmed/derived/verified "
    "statuses only, head-label metric identity), couche/layer descriptive numbering, regulatory-reference identifiers, "
    "unified tests+patches/tests suite as the single canonical run, dossier anglophone coté PPTX full chain zero strict, REAL dossier de conseil "
    "field campaign (13/08/2026) replayed green through the full chain and promoted to an automated regression case; "
    "no OCR; Financial Proof Layer, Temporal Core, H-v2 and PPTX chain preserved."
)
# Historique build précédent (traçabilité in-code ; non affiché, hors __all__).
_BUILD_NAME_B136211 = (
    "v17.4.3.62.11.1-M6B-B1.3.62.11.1 — Financial Proof Layer page-confirmée, "
    "identité RC H-v2 ; pipeline deep scan restauré en v62.11.2."
)

# Historique build précédent (traçabilité in-code ; non affiché, hors __all__).
_BUILD_NAME_B13629 = (
    "v17.4.3.62.9-M6B-B1.3.62.9 — recovery temporel et lanceur Windows "
    "auto-débloquant ; protections analytiques v62.8 conservées."
)

# Historique build précédent (traçabilité in-code ; non affiché, hors __all__).
_BUILD_NAME_B13628 = (
    "v17.4.3.62.8-M6B-B1.3.62.8 — micro-cycle dossier agroalimentaire retiré après "
    "régression de liaison temporelle ; protections analytiques conservées en v62.9."
)

# Historique build précédent (traçabilité in-code ; non affiché, hors __all__).
_BUILD_NAME_B13627 = (
    "v17.4.3.62.7-M6B-B1.3.62.7 — Working Deck par défaut : 8 à 15 slides, "
    "surface orale séparée des annexes et QA stricte optionnelle."
)

# Historique build précédent (traçabilité in-code ; non affiché, hors __all__).
_BUILD_NAME_B13626 = (
    "v17.4.3.62.6-M6B-B1.3.62.6 — fermeture générique KPI/Finance/marché, "
    "garde HCRIT universelle, alertes et historique assainis."
)

# Historique build précédent (traçabilité in-code ; non affiché, hors __all__).
_BUILD_NAME_B13624 = (
    "v17.4.3.62.4-M6B-B1.3.62.4 — durcissement terrain PPTX, preuves marché, "
    "Finance et registre après le run v62.3."
)

# Historique build précédent (traçabilité in-code ; non affiché, hors __all__).
_BUILD_NAME_B13623 = (
    "v17.4.3.62.3-M6B-B1.3.62.3 — rebase sur la v62 terrain, garde OOXML "
    "et séparation de la solidité probatoire de l’utilité décisionnelle."
)

# Historique build précédent (traçabilité in-code ; non affiché, hors __all__).
_BUILD_NAME_B1362 = (
    "v17.4.3.62-M6B-B1.3.62 — correction terrain PPTX du cas de référence : "
    "géométrie native Mode/Confidence, wrap recalibré, roadmap inventaire, "
    "réparation des decks v61 et protection des abréviations."
)

# Historique build précédent (traçabilité in-code ; non affiché, hors __all__).
_BUILD_NAME_B1361 = (
    "v17.4.3.61-M6B-B1.3.61 — sécurité financière fail-closed fondée sur la "
    "preuve structurée ; gate sémantique des actions avant persistance avec "
    "quarantaine historique ; suppression des fuites de dialogue agent avant "
    "tout rendu ; propagation du statut Supply Chain avant le mapping commercial."
)

# Historique build précédent (traçabilité in-code ; non affiché, hors __all__).
_BUILD_NAME_B1318 = (
    "v17.4.3.18-M6B-B1.3.18 — COHÉRENCE SUPPLY + PLACEMENT DIAGNOSTICS "
    "(post-run certification dossier anglophone coté 10 sur 3.17 : preuve B.1 fermée, "
    "9/10 bloqué par le deck supply ; dossier industriel (composants) 3.17 certifié VERT non "
    "touché). P1 — le deck ne se contredit plus : la branche "
    "structured_invalid passait AVANT le filet _retail_kw14 (3.14) dans "
    "_slide_supply_chain (LIGHT désormais prioritaire), et la tuile "
    "synthèse disait NOT COVERED pendant que la slide disait « narrative "
    "available » — helper pur _sc_synth_tile_label_b1318 : LIGHT (CR) "
    "quand not_covered + retail. P1 — fast-path 4 retail_keywords "
    "DÉTERMINISTE avant le prefilter LLM (≥3 mots-clés distincts sur "
    "brief COMPLET + PJ ; le prefilter, fenêtre ~687 tokens, avait "
    "répondu « aucun signal supply » sur un brief "
    "inventory/stockout/markdowns — même famille que le fast-path "
    "dossier réseau de soins). P1/P2 — « Entity validation (grouped diagnostic) » (dette "
    "UX runs 8/9/10) quitte le corps métier : clé dédiée "
    "entity_validation_annex rendue en Annexe docx. RETIRÉ du scope "
    "(challenge Claude contresigné) : déplacement de la ligne "
    "fragments ; P2 dossier industriel (composants) (fidelity « PJ », correct_perimeter) au "
    "backlog post-Annexe B — certification dossier industriel (composants) 3.17 intacte, "
    "re-run dossier anglophone coté SEUL. 2541 tests (+13 : 7 comportementaux dont "
    "slide python-pptx et fast-path monkeypatché, 6 scans dont "
    "non-régression statuts dossier industriel (composants)). v16.5.76."
)

# Historique build précédent (traçabilité in-code ; non affiché, hors __all__).
_BUILD_NAME_B1317 = (
    "v17.4.3.17-M6B-B1.3.17 — FINITION LIVRABLE (post-runs de certification "
    "dossier anglophone coté 9 + dossier industriel (composants) 2 sur 3.16, cœur B.1/E3 fermé aux deux terrains, "
    "scope contresigné Robin/ChatGPT/Claude). P1 deck — TROISIÈME RENDERER "
    "découvert (financial_facts_render : le deck rend depuis les ROWS, pas "
    "la table markdown ; preuve : « 13 key » CR vs « 13 keywords » deck) : "
    "statut UNIFIÉ « ⛔ HORS PÉRIMÈTRE / OUT OF PERIMETER — exclu du score » "
    "REMPLACE icône+statut sur perimeter_match=MISMATCH (⚡ conflit "
    "cumulable, aucun suffixe brief/RELATED) ; PÉRIODE au label deck "
    "(« Revenue (FY2025) », règles _per14) ; filtre narratif B2.2 RÉPARÉ — "
    "il testait source_doc, clé jamais exportée aux rows (8e lecture morte "
    "de l'arc) : lit source_doc OU source, et to_row_dict exporte désormais "
    "source_doc. P1 signal — la condition 3.16 « len(attachments_meta or "
    "[])==0 » était MORTE-NÉE (len(dict) compte les CLÉS ; 9e lecture "
    "morte, la nôtre, validée par un scan de présence et non de "
    "comportement) : helper pur _user_files_count (filenames/file_list, "
    "notion préexistante) — à zéro fichier la ligne signal disparaît "
    "réellement ; à fichiers présents mais signal NON EFFECTIF le label "
    "devient « Fragments à consonance financière détectés — non utilisés "
    "comme faits » (map EN ; row partagée ⇒ CR ET deck). P2 langue : "
    "glossaire structurel FR→EN (_CR_FR_EN_TABLE_GLOSSARY, miroir borné "
    "aux lignes-tableau : Action recommandée / À arbitrer / Gouvernance "
    "financière / statuts registre) appliqué au même étage tardif en run "
    "EN — le texte libre archivé du registre (actions 2025) reste une "
    "DONNÉE non traduite ; « crédits » lang-aware (CR:1 du gate, run 9) ; "
    "titre annexe « Annex » EN. 2528 tests (+14 : 7 comportementaux dont "
    "deck e2e python-pptx, 7 scans). v16.5.76."
)

# Historique build précédent (traçabilité in-code ; non affiché, hors __all__).
_BUILD_NAME_B1316 = (
    "v17.4.3.16-M6B-B1.3.16 — LE BUILD « LIVRABLE 9/10 » (post-runs "
    "dossier anglophone coté 8 + dossier industriel (composants) 1, scope contresigné Robin/ChatGPT/Claude). "
    "P1 dossier anglophone coté : le marqueur de troncature ORPHELIN est retiré au "
    "resolved (le retry appendait la continuation APRÈS le marqueur posé "
    "par le gate — run 8 l.689) + FINAL HARD SCAN ceinture (un marqueur "
    "résiduel ⇒ section re-flaggée ⇒ bandeau + usage bloqué) ; "
    "_clean_bullet exige l'ESPACE après une numérotation — « 67.9% gross "
    "margin » ne devient plus jamais « 9% gross margin » (racine l.91 "
    "pptx). P1 dossier industriel (composants) : à ZÉRO fichier utilisateur la ligne « Signal "
    "financier exploitable détecté » disparaît du livrable (le label "
    "« Pièces jointes » mentait sur un bloc contexte registres — le "
    "signal reste au diagnostic) ; statut UNIFIÉ « ⛔ HORS PÉRIMÈTRE — "
    "exclu du score » remplaçant « ⛔ ✅ FAIT » juxtaposé, posé À LA "
    "SOURCE (table markdown engine → CR texte ET deck alignés d'un coup) "
    "ET en Zone A docx ; note de relégation QUALIFIÉE « Effectif "
    "(Pappers, SOCIAL standalone, 0 salariés) » ; wording Pappers "
    "différencié AFFINEMENT (« identité affinée — comptes sociaux non "
    "probants pour le périmètre groupe consolidé », <GROUPE>→<GROUPE> "
    "HYDRAULICS) vs entité liée (dossier anglophone coté) — ligne Pappers + Resolution. "
    "P2 : « consolidé » FR partout (docx + deck) ; financial_signal_score "
    "posé AU NIVEAU lu par le rendu (runs 7/8 affichaient le fallback "
    "source_quality) ; PÉRIODE aux labels de la table markdown (le deck "
    "suit). 2514 tests (+13, 1 assert FR mis à jour). v16.5.76."
)

# Versions précédentes référencées légitimement dans les CHANGELOG, README,
# release notes et commentaires historiques. Toute mention de ces versions
# dans du code ou de la documentation vivante (hors historique) est détectée
# par le test anti-drift.
HISTORICAL_VERSIONS = (
    # Gamme complète historique
    *[f"v16.5.{i}" for i in range(0, 70)],
    # Sous-versions historiques (v16.5.X.Y) — apprentissage v16.5.68 :
    # le regex anti-drift trouait sur ces patterns à 4 niveaux
    "v16.5.19.1",
    "v16.5.40.1",
    "v16.5.51.2", "v16.5.51.3",
    "v16.5.52.1", "v16.5.52.2",
    "v16.5.67.1", "v16.5.67.2", "v16.5.67.3", "v16.5.67.4", "v16.5.67.5",
    "v16.5.67.6", "v16.5.67.7", "v16.5.67.8", "v16.5.67.9",
    "v16.5.67.10", "v16.5.67.11",
    "v16.5.69",   # v16.5.69 publiée puis remplacée par v16.5.69.1 patch
    "v16.5.69.1", # v16.5.69.1 — patches sessions 1-7 pré-v16.5.70
    "v16.5.70",   # v16.5.70 publiée puis remplacée par v16.5.70.1 hotfix sommaire
    "v16.5.70.1", # v16.5.70.1 publiée puis remplacée par v16.5.70.2 (audit round 6)
    "v16.5.70.2", # v16.5.70.2 — bug crash _attachments_count, remplacée par v16.5.70.3
    "v16.5.70.3", # v16.5.70.3 — hotfix runtime, remplacée par v16.5.71 (anti-régression dossier réseau de soins)
    "v16.5.71",   # v16.5.71 — bonne idée mais score final pas encore propagé, hotfix v16.5.71.1
    "v16.5.71.1", # v16.5.71.1 — score aligné mais tests pas vraiment hermétiques + import Claude direct, hotfix v16.5.71.2
    "v16.5.71.2", # v16.5.71.2 — imports providers + header corrigés, polish docs en v16.5.71.3
    "v16.5.71.3", # v16.5.71.3 — polish partiel, README Mac restait sur fichier inexistant, fix v16.5.71.4
    "v16.5.71.4", # v16.5.71.4 — README Mac corrigé, captions UI restaient en v16.5.69, fix v16.5.71.5
    "v16.5.71.5", # v16.5.71.5 — release publique propre, base de v16.5.72 sprint Source Traceability
    "v16.5.72",   # v16.5.72 — Source Traceability (squelette), hotfix v16.5.72.1 audit ChatGPT round 16
    "v16.5.72.1", # v16.5.72.1 — Hotfix round 16 mais parsing CH text-only, hotfix v16.5.72.2 audit round 17
    "v16.5.72.2", # v16.5.72.2 — Hotfix CH FR + page tracking, mais regex permissive, hotfix v16.5.72.3 audit round 18
    "v16.5.72.3", # v16.5.72.3 — Tokenisation OK pour cas round 18, mais Note inline / nom PDF source à corriger en v16.5.72.4
    "v16.5.72.4", # v16.5.72.4 — Note inline + nom PDF + multi-année OK, mais _profile_hint non recalculé après CH/GLEIF, fix v16.5.72.5
    "v16.5.72.5", # v16.5.72.5 — Profile hint enrichi + Word A/B + README, mais bug parser sur (Note 13) 550 497 et 4 200 4 100 → refonte parser v16.5.72.6
    "v16.5.72.6", # v16.5.72.6 — Refonte parser 3 phases, mais bugs round 22 sur année + % et multi-colonnes 3 chiffres → fix v16.5.72.7
    "v16.5.72.7", # v16.5.72.7 — Round 22 P0 fixés mais bug critique log_event (TypeError missing message) bloquant en condition réelle → fix v16.5.72.8
    "v16.5.72.8", # v16.5.72.8 — log_event securise + sym corrige, mais cause metier sous-jacente non visible + lenteur Streamlit → observabilite + cache v16.5.72.9
    "v16.5.72.9", # v16.5.72.9 — observabilite + cache PJ OK, mais Pappers/CH/GLEIF appeles tous systematiquement (3-5s perdues sur non-FR) → routage intelligent v16.5.72.10
    "v16.5.72.10", # v16.5.72.10 — routage OK, mais bugs FDE: notes decimales 3,5 capturees comme valeur + match nom UI/Pappers casse + company_name_official=None → fixes v16.5.72.11
    "v16.5.72.11", # v16.5.72.11 — match nom + name_official OK + cache UI Streamlit OK, mais bug Note residuelle (3,5 seul sans valeur) toujours present sur FDE retest → fix v16.5.72.12
    "v16.5.72.12", # v16.5.72.12 — note résiduelle seule OK, mais pattern réel FDE \"3,5 + montants après\" toujours bug → fix v16.5.72.13
    "v16.5.72.13", # v16.5.72.13 — release stable testée Mac+Windows (260501), base du sprint v16.5.73 Couche 1 dans prompts agents
    "v16.5.73", # v16.5.73 — Couche 1 dans prompts agents + ancrage temporel + run_date dans diag CSV (test FDE/dossier réseau de soins/dossier anglophone coté OK)
    "v16.5.74", # v16.5.74 — Robustesse production internationale (entity_validator + uploads + budgets + multi-pays)
    "v16.5.74.1", # v16.5.74.1 — Polish documentaire (bumps résiduels verify_installation, README, manuels, vbs)
    "v16.5.75", # v16.5.75 — Parsing décimal UK + liasses fiscales FR + sous-typologie ESTIM
    "v16.5.75.1", # v16.5.75.1 — Polish racine + juridique à jour + manuels v75 (zéro changement moteur)
    "v16.5.75.2", # v16.5.75.2 — Conformité AI Act (5 sections : classification, oversight, limitations, traçabilité, intended use)
    "v16.5.75.3", # v16.5.75.3 — Performance parsing PJ (PDF natif vs scanné, parallélisation threads, progress bars Streamlit)
    "v16.5.75.4", # v16.5.75.4 — Wizard run trigger + raccourcis bureau unifiés (scan FS au clic Lancer uniquement)
    "v16.5.75.5", # v16.5.75.5 — AI Act compliance package : RISK_MANAGEMENT.md formel art.9 + FAQ DSI/RSSI + footer juridique 50(4) DOCX/PPTX + durcissement TERMS_OF_USE §4bis (calendrier sourcé + clause conditionnelle). Hotfix install Windows : conversion CRLF + suppression hack cmd /k + détection Python cascade (py/python3/python) + validation version via Python self-check infaillible. Test de non-régression CRLF (tests/test_windows_line_endings.py). 986 tests verts. release-v7 = candidate au packaging v17 validée sur Surface Laptop 7 ARM64 (test FDE 20 PJ + tests dossier de conseil + tests dossier réseau de soins).
    # Prospectives (roadmap annoncée dans help_content)
    "v16.5.76",
)

def product_label(with_build: bool = False) -> str:
    """Libellé produit affiché (9.4.65) : « CoDIR IA v17.0 », ou « CoDIR IA v17.0 (build 9.4.65) »."""
    if not with_build:
        return f"CoDIR IA {PRODUCT_VERSION}"
    m = re.search(r"(\d+\.\d+\.\d+)-M6B", BUILD_VERSION or "")
    return f"CoDIR IA {PRODUCT_VERSION} (build {m.group(1) if m else BUILD_VERSION})"


def full_version_label() -> str:
    """v17.1-A4 (A4-05) — Libellé de version lisible affiché à l'utilisateur :
    « CoDIR IA v16.5.76 — build v17.4.3.62.13.9.4.11-M6B-B1.3.62.13.9.4.11 ». L'ancre APP_VERSION reste la source
    unique anti-drift ; BUILD_VERSION expose la tranche de travail réelle."""
    return f"{APP_VERSION} — build {BUILD_VERSION}"


__all__ = [
    "APP_VERSION", "APP_VERSION_SHORT",
    "RELEASE_DATE", "RELEASE_NAME",
    "BUILD_VERSION", "BUILD_NAME",
    "full_version_label",
    "product_label",
    "PRODUCT_VERSION",
    "HISTORICAL_VERSIONS",
]
