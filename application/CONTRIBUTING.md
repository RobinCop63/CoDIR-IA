# Contributing to CoDIR-IA

🇫🇷 [Version française](#contribuer-à-codir-ia-français) · 🇬🇧 [English version](#contributing-to-codir-ia-english)

---

## Contributing to CoDIR-IA (English)

Thank you for your interest in contributing to CoDIR-IA. This document explains how to propose changes, what kind of contributions are welcome, and the legal and technical requirements that govern contributions.

### Before you contribute

Three things to understand before submitting code or documentation:

1. **License.** CoDIR-IA is published under the **Functional Source License v1.1 (FSL-1.1-ALv2)**. By contributing, you agree that your contribution will be distributed under this license. See [`LICENSE`](./LICENSE).

2. **Contributor certification (CoDIR IA).** Every commit must be signed off with `git commit -s`, certifying that you have the right to submit the contribution. The CoDIR IA contributor certification is reproduced below.

3. **Maintainer prerogative.** Vauquigneux Gestion SASU retains the right to accept, request changes to, or decline any contribution. Accepted contributions become part of the project under the FSL-1.1 license.

### What kinds of contributions are welcome

- **Bug reports** with reproducible steps, environment details (OS, Python version, package versions), and expected vs actual behavior.
- **Bug fixes** with accompanying tests demonstrating the fix.
- **Feature requests** opened as issues first, for discussion before any pull request.
- **Documentation improvements** (typos, clarifications, translations FR ↔ EN).
- **New external connectors** (additional registry APIs, ERP/data source adapters) provided they respect the local-first principle and the AI Act compliance constraints.
- **Performance optimizations** with before/after benchmarks.

### What kinds of contributions are not welcome

- Pull requests that change the license terms or weaken the trademark protection.
- Contributions that introduce non-permissive dependencies (every dependency must be MIT, BSD, Apache 2.0, MPL 2.0, ISC, or PSF — see the architecture decisions — internal document, available from the maintainer on request).
- Contributions that break the local-first principle (no telemetry, no remote logging, no analytics, no automatic outbound calls outside explicitly user-configured LLM APIs).
- Cosmetic-only changes (whitespace, reformatting) without functional motivation.

### How to submit a contribution

1. **Open an issue first** for any non-trivial change. Describe the problem you're solving and your proposed approach. Wait for maintainer feedback before investing time in implementation.

2. **Fork and branch.** Fork the repository, then create a feature branch from `main` named `feature/short-description` or `fix/short-description`.

3. **Code style.**
   - Python: PEP 8, with line length ≤ 100 characters. We do not enforce a formatter, but please match the existing style.
   - Tests: every functional change should come with at least one non-sensitive `pytest` test, described in the pull request. The test directories and the full suite are not distributed with the public source: the maintainer replays the suite on the reference environment before integration. Do not attach any confidential corpus to make a command runnable.
   - Anti-drift: if you bump the version, update only `version.py` — the version anti-drift contract (internal suite, replayed by the maintainer on the reference environment) will fail if other files diverge.
   - No emojis in code, log messages, or commit messages (UI strings may contain them where editorially relevant).

4. **Commit messages.** Use clear, descriptive messages in English. Sign-off every commit:

   ```
   git commit -s -m "feat(briefcheck): support multi-line tag detection"
   ```

   The `-s` flag adds a `Signed-off-by:` line, which certifies that you have read and accept the contributor certification below.

5. **Pull request.** Open the PR against `main`. In the description, reference the issue, summarize the change, and list:
   - What was tested.
   - Whether documentation was updated.
   - Whether the change is described well enough for the maintainer to write the changelog entry (the development changelog is not distributed publicly).

6. **Review.** Expect comments. CoDIR-IA enforces high standards on traceability (every fact in the board note is sourced and confidence-scored). The same rigor applies to the code that produces those facts.

### Contributor certification (CoDIR IA)

**v62.13.9.4.34.1 — NC-02.** A previous revision of this file reproduced the Developer Certificate of Origin 1.1 while
replacing "open source licence" with "source-available licence" in clauses (a) and (b). The DCO may be copied verbatim
but not modified: presenting an altered text under that name misstated its provenance. The adapted reproduction is
withdrawn and replaced by the project's own certification below, which is not a DCO and does not claim to be one.

By signing off your commits with `git commit -s`, you certify that:

1. You wrote the contribution yourself, or you have the right to submit it under the licence of this project
   (FSL-1.1-ALv2, source-available, converting to Apache-2.0 two years after the release of each version).
2. If the contribution is based on someone else's work, you identify that work and its licence, and that licence
   permits the contribution to be distributed under the licence of this project.
3. You understand that the contribution and the record of it — including your sign-off name and e-mail address — are
   public and are kept for the lifetime of the project.
4. You grant Vauquigneux Gestion SASU the right to distribute your contribution under the licence of this project and
   under its future licence, and you understand that no right over the CoDIR IA trademark is granted to you by that
   licence (see `TRADEMARKS.md`).

The Developer Certificate of Origin 1.1 is available, unmodified, at https://developercertificate.org/ ; this project
does not use it as such. The articulation between contribution provenance, the FSL licence and the future Apache
licence is being reviewed with counsel; this certification may be replaced by a signed contributor agreement.

### Code of conduct

We expect contributors to behave respectfully, professionally, and constructively. Personal attacks, harassment, or discriminatory language are not tolerated and will result in immediate removal from the project.

### Contact

For questions that don't fit a GitHub issue: contact via [robinsauzet.com](https://robinsauzet.com).

---

## Contribuer à CoDIR-IA (français)

Merci de votre intérêt pour contribuer à CoDIR-IA. Ce document explique comment proposer des modifications, quel type de contributions est bienvenu, et les exigences juridiques et techniques applicables.

### Avant de contribuer

Trois éléments à comprendre avant de soumettre du code ou de la documentation :

1. **Licence.** CoDIR-IA est publié sous la **Functional Source License v1.1 (FSL-1.1-ALv2)**. En contribuant, vous acceptez que votre contribution soit distribuée sous cette licence. Voir [`LICENSE`](./LICENSE).

2. **Certification du contributeur (CoDIR IA).** Chaque commit doit être signé via `git commit -s`, attestant que vous disposez du droit de soumettre la contribution. La certification qui fait foi est celle du présent document, « Certification du contributeur (CoDIR IA) », publiée en anglais puis en français ; les deux versions ont le même contenu. Le Developer Certificate of Origin 1.1 est un texte externe, non modifié, que ce projet n'utilise pas comme tel.

3. **Prérogative du mainteneur.** Vauquigneux Gestion SASU se réserve le droit d'accepter, de demander des modifications ou de refuser toute contribution. Les contributions acceptées deviennent partie intégrante du projet sous licence FSL-1.1.

### Quels types de contributions sont bienvenus

- **Rapports de bug** avec étapes de reproduction, détails d'environnement (OS, version Python, versions des packages), comportement attendu vs réel.
- **Corrections de bug** accompagnées de tests démontrant la correction.
- **Demandes de fonctionnalités** ouvertes d'abord en issue, pour discussion avant toute pull request.
- **Améliorations de documentation** (coquilles, clarifications, traductions FR ↔ EN).
- **Nouveaux connecteurs externes** (APIs de registres additionnels, adaptateurs ERP/sources de données) à condition de respecter le principe local-first et les contraintes de conformité AI Act.
- **Optimisations de performance** avec benchmarks avant/après.

### Quels types de contributions ne sont pas acceptés

- Pull requests modifiant les termes de la licence ou affaiblissant la protection de la marque.
- Contributions introduisant des dépendances non permissives (toute dépendance doit être MIT, BSD, Apache 2.0, MPL 2.0, ISC ou PSF — voir les décisions d'architecture — document interne, communiqué sur demande au mainteneur).
- Contributions cassant le principe local-first (pas de télémétrie, pas de logging distant, pas d'analytics, pas d'appels sortants automatiques hors APIs LLM explicitement configurées par l'utilisateur).
- Changements purement cosmétiques (espaces, reformatages) sans motivation fonctionnelle.

### Comment soumettre une contribution

1. **Ouvrez une issue d'abord** pour toute modification non triviale. Décrivez le problème que vous résolvez et votre approche proposée. Attendez le retour du mainteneur avant d'investir du temps en implémentation.

2. **Fork et branche.** Forkez le dépôt, puis créez une branche de fonctionnalité depuis `main`, nommée `feature/courte-description` ou `fix/courte-description`.

3. **Style de code.**
   - Python : PEP 8, longueur de ligne ≤ 100 caractères. Nous n'imposons pas de formateur, mais respectez le style existant.
   - Tests : tout changement fonctionnel devrait s'accompagner d'au moins un test `pytest` non sensible, décrit dans la demande d'intégration. Les répertoires de tests et la suite complète ne sont pas distribués avec la source publique : le mainteneur rejoue la suite sur l'environnement de référence avant intégration. Ne joignez aucun corpus confidentiel pour rendre une commande exécutable.
   - Anti-drift : si vous incrémentez la version, modifiez uniquement `version.py` — le contrat de dérive de version (suite interne, rejouée par le mainteneur sur l'environnement de référence) échouera si d'autres fichiers divergent.
   - Pas d'emojis dans le code, les messages de log ou les messages de commit (les chaînes UI peuvent en contenir si éditorialement pertinent).

4. **Messages de commit.** Utilisez des messages clairs et descriptifs, en anglais. Signez chaque commit :

   ```
   git commit -s -m "feat(briefcheck): support multi-line tag detection"
   ```

   L'option `-s` ajoute une ligne `Signed-off-by:`, qui certifie que vous avez lu et acceptez la certification du contributeur (voir section anglaise ci-dessus).

5. **Pull request.** Ouvrez la PR contre `main`. Dans la description, référencez l'issue, résumez le changement, et listez :
   - Ce qui a été testé.
   - Si la documentation a été mise à jour.
   - Si le changement est décrit assez précisément pour que le mainteneur rédige l'entrée de changelog (le journal de développement n'est pas distribué publiquement).

6. **Revue.** Attendez-vous à des commentaires. CoDIR-IA impose des standards élevés de traçabilité (chaque fait dans la note CoDIR est sourcé et scoré en confiance). La même rigueur s'applique au code qui produit ces faits.

### Code de conduite

Les contributeurs sont attendus respectueux, professionnels et constructifs. Les attaques personnelles, le harcèlement ou les propos discriminatoires ne sont pas tolérés et entraîneront une exclusion immédiate du projet.

### Contact

Pour toute question ne relevant pas d'une issue GitHub : contact via [robinsauzet.com](https://robinsauzet.com).

### What validating a contribution involves

The full test suite and the development history are not distributed with the public source. A contribution is therefore
validated by the maintainer, who replays it on the reference environment before integration. Do not expect to be able to run
the full acceptance suite from your copy, and do not attach any confidential corpus to make a command runnable.

## Certification du contributeur (CoDIR IA)

En signant vos commits avec `git commit -s`, vous certifiez que :

1. Vous avez écrit la contribution, ou vous disposez du droit de la soumettre sous la licence de ce projet
   (FSL-1.1-ALv2, source disponible, convertie en Apache-2.0 deux ans après la publication de chaque version).
2. Si la contribution s'appuie sur le travail d'un tiers, vous identifiez ce travail et sa licence, et cette licence
   permet de distribuer la contribution sous la licence de ce projet.
3. Vous comprenez que la contribution et son enregistrement — nom et adresse de courriel du sign-off compris — sont
   publics et conservés pendant la vie du projet.
4. Vous concédez à Vauquigneux Gestion SASU le droit de distribuer votre contribution sous la licence de ce projet et
   sous sa licence future, et vous comprenez qu'aucun droit sur la marque CoDIR IA ne vous est concédé par cette
   licence (voir `TRADEMARKS.md`).

Le Developer Certificate of Origin 1.1 est disponible, non modifié, à l'adresse https://developercertificate.org/ ;
ce projet ne l'utilise pas comme tel.

### Ce que la validation d'une contribution suppose

La suite de tests complète et l'historique de développement ne sont pas distribués avec le code source public. Une
contribution est donc validée par le mainteneur, qui la rejoue sur l'environnement de référence avant intégration.
N'attendez pas de pouvoir exécuter la recette complète depuis votre copie, et ne joignez aucun corpus confidentiel
pour rendre une commande exécutable.
