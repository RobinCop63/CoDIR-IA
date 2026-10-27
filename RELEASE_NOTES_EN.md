# CoDIR IA v17.0 — Release notes

| | |
|---|---|
| Public name | **CoDIR IA v17.0** |
| Technical build | `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65` (build 9.4.65) |
| Build date | 18 October 2026 |
| Licence | FSL-1.1-ALv2 — source-available; each version becomes available under the Apache 2.0 licence two years after it is made available (see `LICENSE`) |
| Fingerprint of the published archive | SHA-256 given in the GitHub release notes; per-file fingerprints in `SHA256SUMS` |
| Target publication | 29 October 2026, at the publisher’s decision |

## Intended use and deliverables

CoDIR IA prepares a leadership-committee session from a brief and documents supplied by the user. It delivers a **Word minutes document** and a **Word synthesis** — the two main deliverables —, a **draft PowerPoint presentation** and a **complete package** (deliverables, registers, diagnostic). It is intended for a consultant, an interim manager or an accompanied business leader, for **supervised use**: the deliverables are a working basis to be reviewed, never a decision or a certification.

## What v17.0 brings

Features present and tested in the October 2026 acceptance runs on real files (a US listed company over several sessions, a French food-industry group on Windows and macOS):

- **Memory from one session to the next**: statuses declared by the leader (completed, postponed, dropped), Board decision carried identically into the minutes, the synthesis and the deck; a recommendation is never presented as an adopted decision.
- **Evidence discipline**: facts, assumptions and scenarios kept apart; published facts read from public registers depending on the identifiers available; a figure contradicted by a document carries the document’s value.
- **Complete delivery with in-place flags** (see “Delivery doctrine”).
- **Check of the delivered deck**: decision aligned with the Board, headcount of another entity shown with its entity and financial year, empty cards or cards reduced to a subheading referred to the minutes.
- **User journey**: brief filled in the form or pasted, processing screen, end screen, « Quit »; disconnected session kept for 24 hours; computer kept awake during processing.

## Final fixes in build 9.4.65

Observed in the counter-acceptance runs of 17 and 18 October 2026 (Windows and macOS); these are findings on those files, not a general guarantee:

- the headcount of a subsidiary keeps its entity and financial year, in the minutes, the synthesis and the deck;
- the Finance note is kept under a single prudence notice when no primary financial statement of the perimeter is available;
- an accounting reservation no longer presupposes that a provision exists;
- a past decision or an accomplished event is no longer turned into an action;
- without a Board decision, the deck card reads « Recommendation »;
- two equal values are no longer reported as contradictory;
- the complete-package download and the tab icon work (starlette 1.7.0).

## Delivery doctrine

The principle is to keep: an unsupported quantity stays where it is, highlighted and followed by “⚠ to verify — reason”; the first-page box counts and lists the flagged passages. Current exceptions: personal calculations (remuneration, dividends, self-employed status) are removed; without primary financial statements for the perimeter, the Finance note of a one-person company (SASU, EURL, sole trader) or a very short note is replaced by a prudence frame; some accounting wordings receive a standard reservation. The product’s annotations must themselves be checked against the documents.

## Known limits

- Many flags (over 200 per minutes document on the acceptance files), including false alarms: review is essential.
- Scanned documents without a text layer are not read (no OCR in v17).
- The PowerPoint presentation is a draft; the two Word documents are the reference deliverables.
- English is a preview (interface, deliverables, manuals).
- Local mode is not an offline mode: AI models are called at their providers; API keys are stored locally in clear text.
- Application not signed in v17.0: an authorisation is requested at first launch (steps in the README); signing planned for v18.
- Closing a laptop lid may put the computer to sleep during processing.

**Limits found in acceptance testing (October 2026), to be fixed in v17.5 or v18.**
- An already-decided action may enter the register reworded by the agent. To declare its status at the next session, **reuse the wording shown in the action table of the previous minutes**; otherwise CoDIR IA does not close it and says so (preview « not found », minutes section « Declared statuses NOT applied »).
- A common word may be flagged as an unverified entity (« Parade »): false alarm, to remove when proofreading.
- An adjusted result (« excluding the tax adjustment », « adjusted ») may be flagged « actual contradicted by the document » against the reported result: false alarm, the adjusted measure is not the reported one; to remove when proofreading.
- Scanned documents without a text layer are not read (no OCR in v17); a French amount with space separators may be mis-segmented in the facts table (« 12 » for 12,345,678.90 €): check against the document; a legal obligation inferred from an added-up headcount (249-employee threshold) requires checking scope, counting method and applicable rule.
- Figures written by the agent inside an action label (« scenarios 54 %, 55 % and 56 % ») may be flagged « unsourced projection » or « unsourced target », including on the line restating your status: false alarm, the status and its date are applied; to remove when proofreading.
- The register may hold awkward wordings (sentence fragment, leading date) and dates written two ways: correct content, wording to fix when proofreading.

## Evidence

- Automated contracts: the full suite was run on the 9.4.65 suite zip extracted from scratch (6,348 passed, 0 failed, 9 skipped, 1 known gap marked, 25 October 2026); the final zip differs from it only by documentation and status files. Contracts replace neither a fresh run on a real case nor native Windows/macOS acceptance.
- Vulnerability scan of 17 October 2026 (`pip-audit`, OSV database) on the 83 dependencies of the distributed lock: no known vulnerability (`Documentation/3 - Securite et conformite/VULNERABILITY_SCAN_STATUS.md`).
- CycloneDX SBOM of the 83 components, licences and fingerprints (`SBOM_CycloneDX.json`, `THIRD_PARTY_NOTICES.md`).
- Native tests by the publisher on the public archive: macOS on 17 October 2026 and Windows on 18 October 2026 (installation, complete processing, complete-package download, shutdown).

## Installation

See `README_EN.md` and the guides in `Documentation/1 - Manuels d'utilisation/` (Windows, macOS). Standard Python 3.11 to 3.14 on 64-bit Windows 10/11 on Intel/AMD PCs and Windows 11 on ARM PCs (an emulated x64 Python on ARM PCs), and 3.11 to 3.13 on macOS, on Apple silicon Macs. Intel Macs, 32-bit Windows and Windows 10 on ARM PCs: not supported by this version. On Windows, updating from an earlier version automatically replaces a Python environment built for another version; the old one is kept as `.venv-precedent`.

## Condensed history

- **September 2026 (builds 9.4.31 to 9.4.48)**: acceptance campaign on French and international files; financial consistency, temporal framing and retrospective mode; public archive built from an allowlist; scenario doctrine; complete lock and SBOM.
- **End of September 2026 (9.4.49 and 9.4.50)**: “deliver everything, flag in place” doctrine; published financial facts; default model updated.
- **1 to 8 October 2026 (9.4.51 to 9.4.56)**: installable public archive; leader statuses and Board decision; processing screen; publication documentation.
- **10 to 15 October 2026 (9.4.57 to 9.4.64)**: end screen and « Quit »; “quality first” settings; multi-line statuses; refreshed lock and scan.
- **15 to 18 October 2026 (9.4.65)**: session kept, computer kept awake, check of the delivered deck, counter-acceptance fixes, starlette 1.7.0.

The detailed build log is kept by the publisher; it is not distributed in the public archive.
