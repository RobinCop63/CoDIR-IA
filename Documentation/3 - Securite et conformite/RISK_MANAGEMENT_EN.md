# Risk Management — CoDIR IA

**Software:** CoDIR IA v17.0 — build `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`  
**Documentation revision:** 18 October 2026  
**Use:** supervised professional use

**Build:** `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`  

This document describes voluntary lifecycle controls. It does not classify CoDIR IA as a high-risk AI system and is not a certification.

## Governance

- intended purpose: supervised professional working document;
- product-risk owner: Vauquigneux Gestion; deployment-risk owner: the deploying organisation;
- sensitive purpose changes require prior legal, security and data-protection review;
- version, incident, dependency and security-decision records are maintained;
- since 9.4.49, documents are delivered with in-place flags when evidence or temporal authority is not established; only a technical failure stops delivery.

## Tracked risks

| Risk | Main controls |
|---|---|
| hallucination or factual error | canonical claims, source pages, conflicts, mandatory human review |
| unsupported prospective number | in-place flagging (highlight, “⚠ to verify — reason”, first-page box), register of flagged passages, final DOCX/PPTX controls |
| incorrect entity, scope or period | canonical target, registry resolution, Temporal Core and period authority |
| data disclosure | minimisation, local configuration, provider contracts and access control |
| software-supply-chain compromise | lock file, SBOM, manifest and integrity verification |
| provider outage or API drift | fallbacks and explicit diagnostics |
| prohibited or high-impact use | terms of use and mandatory purpose re-qualification |

> **Scenario doctrine.** Unsupported scenarios and quantities remain **in place** in the body of the document, with their flags, and are recorded in the evidence register; their presence is neither validation nor approval. Removal or replacement exceptions are those described in the “Deterministic guards” section of the user manual. References to a "scenario appendix" above describe an earlier mechanism and are no longer instructions.

## Lifecycle

Identify → assess → treat → test → document → counter-audit → monitor. Security incidents follow `SECURITY_EN.md` and the CRA procedure. The incident log records the version, date, impact, treatment, decision and evidence of closure.

## Qualification and rendering risks

Deterministic guards. After model generation, local Python rules examine text and structured data. No model is called to make decisions within these guards. Doctrine “deliver everything, flag in place”: the principle is to keep. An unsupported quantity stays where it is, highlighted and followed by “⚠ to verify — reason”; a figure contradicted by a document carries the document’s value; the first-page box counts and lists the flagged passages, and the register records them. Current exceptions: personal calculations (remuneration, dividends, self-employed status) are removed; without primary financial statements for the perimeter, the Finance note of a one-person company (SASU, EURL, sole trader) or a very short note is replaced by a prudence frame; some accounting wordings receive a standard reservation, which must itself be checked against the documents. Only a technical failure prevents delivery. These checks reduce some risks; they guarantee neither error-free results, completeness nor a complete trace of every transformation. Legitimate content may be over-labelled or masked; incorrect content may escape detection. Review the Word documents and compare reservations, registers and sources before use.

Financial position established. The yes/no indicator and its reason, where available in the report or diagnostics, concern the current baseline that the engine could qualify for the retained scope and date. ‘Yes’ does not certify every figure or scenario. ‘No’ does not prove that accounts were not supplied: examine the listed documents, extractability, periods, scopes and conflicts. This global reason is not a per-figure explanation.

Memory between meetings. The code includes local case history and a timestamped action register. Reuse the same case — the same “Dossier label” from one meeting to the next — and check the entity, identifier, data directory and analysis date. State genuinely approved decisions, completed or deferred actions and explicit closures in the next brief. Then review carried-over items and changes: repetition does not approve a proposal. Retrospective/future modes do not write to the live register; the “Start fresh — ignore this folder’s history” box (technical variable CODIR_IGNORE_HISTORY) disables carry-over for an isolated test. This documentation revision does not certify exhaustive decision, action and question continuity across two meetings; verify it for your case. This is not memory of all conversations or model training.

## Risks related to public data, models and memory

| Risk | Measure |
|---|---|
| Wrong third-party public data or another scope (company accounts taken for consolidated) | Routing by identifier and jurisdiction; scope and source displayed; the document provided always comes first; any gap is flagged |
| Public service unavailable (SEC, Companies House, Pappers) | Bounded, silent collection; without a response, cards rely on the documents alone |
| Model change (Claude Sonnet 4.5 retired on 24/11/2026, Sonnet 5.5 by default) | Automatic settings migration; parameters rejected by newer models removed from the call; acceptance run on frozen inputs before release |
| Wrong memory between sessions (missed carry-over, decision wrongly attributed) | Carry-overs recognised by intent; statuses applied only from the leader's brief; agents' recommendation distinguished from a decision |
