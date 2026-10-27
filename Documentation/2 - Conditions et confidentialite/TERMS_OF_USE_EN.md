# Terms of Use — CoDIR IA

**Software:** CoDIR IA v17.0 — build `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`  
**Documentation revision:** 18 October 2026  
**Use:** supervised professional use

**Publisher:** Vauquigneux Gestion SASU, French company number (SIREN) 102 885 654, 6 Cours des Vauquigneux, 35310 Mordelles, France  
**Updated:** contractual text unchanged since 27 September 2026; editorial revision of 18 October 2026
**Prevailing language:** French

> **Document status.** These terms govern use of CoDIR IA v17.0. They do not replace negotiated sales terms, an order form, a licence agreement or a services agreement. Services sold by the publisher require their applicable contractual documents. Permitted use of the software and a consultant’s delivery of documents to a client do not, by themselves, require an additional contract with the publisher; the consultant’s own client obligations still apply.

## 1. Purpose and intended users

CoDIR IA is a local decision-support work tool for consultants, interim managers and SME/mid-cap executives. It structures briefs, qualifies facts, exposes uncertainty and produces Word and PowerPoint working documents. It does not make decisions and does not provide legal, tax, medical, regulatory or personalised financial advice. Its analyses replace neither the expertise of the responsible professional nor a legal, tax, medical, regulatory or financial consultation required for the use concerned.

### 1bis. Deliverables and case continuity

The two Word documents are the main deliverables: detailed analysis and decision synthesis. The PPTX is a presentation draft to revise after reading them, not a standalone document ready to hand over. Length depends on the brief and available material; page and slide counts are indicative, not guaranteed. The complete package brings together the files actually generated, diagnostics, available registers, preparation journal and manifest.

Memory between meetings. The code includes local case history and a timestamped action register. Reuse the same case — the same “Dossier label” from one meeting to the next — and check the entity, identifier, data directory and analysis date. State genuinely approved decisions, completed or deferred actions and explicit closures in the next brief. Then review carried-over items and changes: repetition does not approve a proposal. Retrospective/future modes do not write to the live register; the “Start fresh — ignore this folder’s history” box (technical variable CODIR_IGNORE_HISTORY) disables carry-over for an isolated test. This documentation revision does not certify exhaustive decision, action and question continuity across two meetings; verify it for your case. This is not memory of all conversations or model training.

### 1ter. Languages

The interface, the deliverables and the manuals are available in French and in English. **English is offered as a preview in this version**: available features and known limitations are listed in the release notes. Preview status does not remove the requirement to preserve the meaning of decisions, values, dates and responsibilities; it means that parity of the editorial and financial controls with French is not certified in this version.

## 2. Software licence

The source code is made available under **FSL-1.1-ALv2**, included in `LICENSE`. Trademark and intellectual-property information is provided in `TRADEMARKS.md` and `NOTICE.md`. Third-party components remain subject to their own licences, listed in the SBOM and `THIRD_PARTY_NOTICES.md`.

## 3. Mandatory human review

The user remains responsible for their use, including the brief and attachments, lawful processing and content rights, provider selection, verification of facts/calculations/sources/periods/scopes, and any decision or disclosure. `FACT` labels, scores and confidence levels are internal product controls, not a legal audit, certification or professional assurance.

## 4. Prohibited or review-required uses

Without a specific legal, security and data-protection review, CoDIR IA must not be used for recruitment or automated assessment of individuals, decisions with legal or similarly significant effects, credit scoring, access to essential services, medical diagnosis, biometric surveillance, or classified/regulatorily protected data.

## 4bis.0 — AI Act timeline and qualification

Article 113 of Regulation (EU) 2024/1689 provides, among other things, that the transparency obligations of Article 50 apply from 2 August 2026, under their own conditions. The Digital Omnibus and any announced amending regulation are followed in regulatory monitoring; they are not relied upon here as an exemption or a deferral. Applicable qualifications, exceptions and transitional measures must be assessed in the deployment-specific applicability note using current official texts and guidance. This documentation revision is not that note.

## 4bis.1 — Important conditional clause on diversion of intended purpose

The assessment covers supervised professional preparation of diagnostics and management decisions. It does not authorise sensitive or individualised uses excluded by these terms (recruitment, credit scoring, access to essential services, health, education, law enforcement, migration, justice, or any individual decision producing legal or similarly significant effects). Any extension of functionality or intended purpose towards such uses requires a specific assessment and the prior approval of the competent responsible person. Human involvement alone does not rule out a high-risk regime.

### 4ter. Qualification of figures and statements

Confirmation levels. ‘Confirmed on page’ identifies a match made by the software to an attachment and page; verify the value AND label, sign, unit and scale, period and scope. ‘Confirmed at registry’ refers to a queried registry and its consultation date; this may not match the analysed year and this route is inactive in retrospective analysis. ‘Declared, unconfirmed’ means the required match has not been established. Possible causes include an absent source, inadequate extraction, or unmatched label, unit, scale, period or scope; the status does not identify which cause applies. [NON SOURCÉ] / [UNSOURCED] means ‘declared, unconfirmed’ here, not ‘no source exists’. Nature (actual, budget, assumption, target), evidence and approval remain separate. Arithmetic reconciliation: between confirmed facts of the same period, scope and currency, the software checks that revenue − cost of sales = gross profit, and gross profit − operating expenses = operating profit when the table carries an operating-expenses total. The result is noted “reconciled” (or “reconciled within rounding” up to a 1% gap); beyond that it becomes “to verify” and stops confirming anything, its two operands carrying a note. The published value is never replaced by the computation, and this check covers these two identities only.

Facts, assumptions and scenarios. A number found in a source may be a budget or target: being sourced does not turn it into an actual. Admitted scenarios should remain complete, readable and visibly qualified; consult the available register and diagnostics for withheld scenarios, without presuming exhaustive coverage. The product may still produce excessive qualification (false alarms): inspect tables and text as delivered, without arbitrarily filling missing values. A retained scenario is neither a certified forecast nor an approved decision. A target written in the brief and quoted as a target stays as written in the body; it is flagged once, at the top of the brief section (“management’s declarations, not certified by a document”), and in the register. A target put forward by an agent without a document stays in place, highlighted and followed by “⚠ to verify — target without supporting document”.

### 4quater. Limits of deterministic controls

Deterministic guards. After model generation, local Python rules examine text and structured data. No model is called to make decisions within these guards. Doctrine “deliver everything, flag in place”: the principle is to keep. An unsupported quantity stays where it is, highlighted and followed by “⚠ to verify — reason”; a figure contradicted by a document carries the document’s value; the first-page box counts and lists the flagged passages, and the register records them. Current exceptions: personal calculations (remuneration, dividends, self-employed status) are removed; without primary financial statements for the perimeter, the Finance note of a one-person company (SASU, EURL, sole trader) or a very short note is replaced by a prudence frame; some accounting wordings receive a standard reservation, which must itself be checked against the documents. Only a technical failure prevents delivery. These checks reduce some risks; they guarantee neither error-free results, completeness nor a complete trace of every transformation. Legitimate content may be over-labelled or masked; incorrect content may escape detection. Review the Word documents and compare reservations, registers and sources before use.

Registers and diagnostics can help locate some withheld content; neither their presence nor a check mark guarantees that all source content was retained or correctly interpreted. Missing or ambiguously qualified information needed for a decision requires verification or reprocessing. These limits neither authorise known false facts nor waive the user’s mandatory legal rights.

## 5. Data and third-party providers

Depending on enabled features, brief text, extracted attachment text, company identifiers and queries may be sent to configured providers. See `PRIVACY_EN.md` and `SUBPROCESSORS_AND_TRANSFERS.md`. Users must review the terms, processing locations, retention and transfer safeguards applicable to their own provider accounts.

Third-party public data. Depending on the identifiers available, CoDIR IA reads amounts already published by the SEC, Companies House and Pappers, and the legal identity from GLEIF. These data remain subject to their publishers' terms; they may be incomplete, late or relate to another scope (company or consolidated accounts). They never replace a document provided, are shown with their source and fiscal year, and must be checked like any figure before a decision.

## 6. Security reporting

Report vulnerabilities under `SECURITY_EN.md`. Never include API keys, unnecessary personal data or client secrets in the first message. Unsupported versions must be upgraded before incident analysis.

This upgrade requirement concerns **ordinary support**. It does not apply to the handling of a security report: qualification of the facts, statutory deadlines and preservation of evidence run from the moment of knowledge, whatever version is in use.
## 7. AI transparency

Deliverables include visible disclosure and a proprietary OOXML marker. CoDIR IA documents this marker without claiming that it alone demonstrates Article 50(2) interoperability under Regulation (EU) 2024/1689. Article 50(4) wording is conditional on the relevant use or publication. See `AI_ACT_FAQ_CLIENT_EN.md`.

## 8. Availability, updates and support

CoDIR IA v17.0 is provided as-is. External providers may change or interrupt their services. Backups, access controls and recovery plans are the deployer’s responsibility. Supported versions and security handling are described in `SECURITY_EN.md`.

## 9. Liability

Subject to mandatory law and any signed commercial agreement, the publisher does not warrant error-free operation, fitness for a particular purpose or third-party service continuity. No output may be used as an autonomous decision or distributed without human review.

## 10. Ownership of inputs and deliverables

Users retain the rights they hold in briefs and attachments. Subject to provider rights and the applicable contract, generated deliverables are intended for the user’s professional use. Users warrant that they have the necessary rights to transmit the content.

## 10bis. Trademark, logo and visual identity

The French figurative trademark “CoDIR IA” (no. 26 5245108, classes 9, 35
and 42) and its logo belong to their co-owners. The **FSL-1.1-ALv2** software
licence covers the code and grants no right in the trademark by itself.

**Free use.** The logo ships with the software: keeping it in the interface,
the documentation and the deliverables produced is permitted, including in a
modified version you redistribute, where it serves the display and operation
of the system. You may name “CoDIR IA” to truthfully refer to this software
or its origin.

**Use requiring prior written consent.** The co-owners' consent is required
for: using “CoDIR IA” or any confusingly similar sign as your own product,
service, company, trademark or domain name; any presentation suggesting a
partnership, certification or endorsement that does not exist; commercial
exploitation of the mark itself, independently of use of the software;
altering the logo, beyond technical adaptations (format, resolution, size,
monochrome variant) that do not distort the sign.

**Modified version.** If you redistribute a modified version, say so clearly,
so that its behaviour is not attributed to the co-owners.

These terms bind users of the service. Redistributors of the source-available
software are governed by the `TRADEMARKS.md` file. For the detailed
permissions and restrictions concerning the trademark and logo, see
`TRADEMARKS.md`, published with the software.

## 11. Governing law and commercial documents

French law is the reference for this notice. Governing law, jurisdiction, pricing, payment, service levels, term, termination, liability caps and confidentiality must be defined in signed commercial documents. the B2B contract checklist (not included in this distribution; provided within a contractual relationship) lists the items to contractualise.

## 12. Contact

Product contact and initial requests: https://robinsauzet.com/contact/
