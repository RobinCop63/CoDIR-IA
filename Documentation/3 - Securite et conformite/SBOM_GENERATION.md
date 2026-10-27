# Génération du SBOM — CoDIR IA v17.0 (build 9.4.65)

Le fichier `SBOM_CycloneDX.json` est dérivé de `application/requirements.lock`, le verrou distribué.

- Format : CycloneDX 1.5
- Nom public : CoDIR IA v17.0 — build technique `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`
- Date de l’état décrit : 17 octobre 2026
- SHA-256 du verrou : `418aa58eddcc1771f3fc50f196a1a130f52a82d72ade2422289f58739fda02f2`
- Composants Python exacts : 83 (dont `google-auth[requests]`) ; starlette 1.7.0

## Complétude

- **Licences : 83/83.** Sources : métadonnées publiées de chaque version épinglée (expression de licence, champ `License`, classifieurs Trove), tracées par la propriété `codir.license-source`. Pour `mistralai`, les métadonnées publiées ne déclarent pas de licence lisible par machine : la licence Apache-2.0 est établie sur le paquet exact du verrou, qui embarque le texte de la licence.
- **Empreintes : 83/83.** SHA-256 des artefacts de distribution exacts (wheels ou sdists) des versions épinglées, publiés sur PyPI ; le nom du fichier haché est tracé par la propriété `codir.artifact-filename`.
- **Scan de vulnérabilités : exécuté le 17 octobre 2026** (`pip-audit` 2.9.0, base OSV) sur les 83 pins exacts du verrou ci-dessus : aucune vulnérabilité connue. Résultat, périmètre et empreinte de la sortie brute : `VULNERABILITY_SCAN_STATUS.md` ; la sortie brute `SCAN_PIP_AUDIT_9_4_65_2026-10-17.json` est distribuée dans ce dossier. La propriété `codir.vulnerability-scan` du composant racine du SBOM porte le même état.

## Historique

- 14 octobre 2026 : scan propre du verrou précédent (`b0b98778…`, starlette 1.8.0) — état remplacé, décrit dans `VULNERABILITY_SCAN_STATUS.md` ; sa sortie brute est conservée par l’éditeur (preuve privée, non distribuée).
- 15 septembre 2026 : le scan d’un verrou plus ancien (`3c81ea07…`) relevait des avis sur huit paquets, montés depuis aux versions corrigées.

## Règle

Toute modification du verrou exige une nouvelle candidate, un nouveau SBOM, un nouveau scan et les revalidations correspondantes. Un scan propre est daté, non permanent : il est relancé avant chaque publication.

## English — SBOM generation

`SBOM_CycloneDX.json` is derived from the distributed lock, `application/requirements.lock`.

- Format: CycloneDX 1.5
- Public name: CoDIR IA v17.0 — technical build `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`
- State described: 17 October 2026
- Lock SHA-256: `418aa58eddcc1771f3fc50f196a1a130f52a82d72ade2422289f58739fda02f2`
- Exact Python components: 83 (including `google-auth[requests]`); starlette pinned to 1.7.0

### Completeness

- **Licences: 83/83.** Sources: the published metadata for each pinned version (licence expression, licence field, Trove classifiers), identified by `codir.license-source`. For `mistralai`, the metadata provides no machine-readable licence: the publisher established Apache-2.0 from the exact locked package, which includes the licence text.
- **Hashes: 83/83.** SHA-256 values of the selected distribution artifacts (wheels or source distributions) of the pinned versions, published on PyPI; `codir.artifact-filename` identifies each file. They describe those artifacts and do not turn the unhashed `requirements.lock` into a hash-enforced installation.
- **Vulnerability scan: run on 17 October 2026** (`pip-audit` 2.9.0, OSV database) on the 83 exact pins of the lock above: no known vulnerability. Result, scope and raw-output hash: `VULNERABILITY_SCAN_STATUS.md`; the raw output `SCAN_PIP_AUDIT_9_4_65_2026-10-17.json` is distributed in this folder. The `codir.vulnerability-scan` property of the SBOM root component states the same scan.

### History

- 14 October 2026: clean scan of the previous lock (`b0b98778…`, starlette 1.8.0) — superseded state, described in `VULNERABILITY_SCAN_STATUS.md`; its raw output is retained by the publisher (private evidence, not distributed).
- 15 September 2026: the scan of an older lock (`3c81ea07…`) reported advisories on eight packages, since updated to fixed versions.

### Rule

Any change to the lock requires a new release artifact, a new SBOM, a new scan and the corresponding revalidations. A clean scan is dated, not permanent: it is repeated before each publication, including on the publication day.
