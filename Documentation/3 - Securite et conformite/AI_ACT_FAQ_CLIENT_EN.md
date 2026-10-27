# Client FAQ — AI Act and transparency — CoDIR IA

**Software:** CoDIR IA v17.0 — build `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`  
**Documentation revision:** 18 October 2026  
**Use:** supervised professional use

**Build:** `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65` — initial baseline 24 August 2026; current revision stated above.

## Product role

CoDIR IA is a decision-support system built on third-party models. Depending on how it is made available, Vauquigneux Gestion may be a provider of the system and/or a downstream provider; the customer organisation is generally the deployer for its use. The actual activities determine the roles, which must be documented in the deployment assessment and contracts.

## Article 50

Article 50 transparency obligations apply from 2 August 2026. CoDIR IA informs users in the interface and deliverables. Word and PowerPoint files also receive a proprietary OOXML `AI_GENERATED` marker. This improves traceability but the project does not claim that the marker alone demonstrates the effectiveness, robustness and interoperability required by Article 50(2).

The EU Code of Practice on transparency of AI-generated content is a voluntary compliance tool. CoDIR IA v17.0 documents a mapping plan; it is not represented as a signatory or certified implementation.

## Article 50(4)

The obligation for text published to inform the public on matters of public interest depends on the intended use and publication. Supervised internal work products use conditional wording (“where applicable”) and mandatory human review.

## High-risk status

The intended use is not represented as high risk. Controls inspired by Articles 9 and 14 are voluntary. Recruitment, credit, essential-service access or significant individual decision-making requires a fresh legal qualification.

## GDPR relationship

The GDPR remains applicable to personal data processed. Roles, legal bases, notices, processing agreements and transfers must be qualified for the deployment.

## Official references

- Regulation (reference text; consult the version applicable to the deployment): https://eur-lex.europa.eu/eli/reg/2024/1689/oj
- Article 50 guidelines: https://digital-strategy.ec.europa.eu/en/policies/guidelines-ai-transparency-obligations
- Code of Practice: https://digital-strategy.ec.europa.eu/en/policies/code-practice-ai-generated-content

## Figure qualification, supervision and limits

Confirmation levels. ‘Confirmed on page’ identifies a match made by the software to an attachment and page; verify the value AND label, sign, unit and scale, period and scope. ‘Confirmed at registry’ refers to a queried registry and its consultation date; this may not match the analysed year and this route is inactive in retrospective analysis. ‘Declared, unconfirmed’ means the required match has not been established. Possible causes include an absent source, inadequate extraction, or unmatched label, unit, scale, period or scope; the status does not identify which cause applies. [NON SOURCÉ] / [UNSOURCED] means ‘declared, unconfirmed’ here, not ‘no source exists’. Nature (actual, budget, assumption, target), evidence and approval remain separate. Arithmetic reconciliation: between confirmed facts of the same period, scope and currency, the software checks that revenue − cost of sales = gross profit, and gross profit − operating expenses = operating profit when the table carries an operating-expenses total. The result is noted “reconciled” (or “reconciled within rounding” up to a 1% gap); beyond that it becomes “to verify” and stops confirming anything, its two operands carrying a note. The published value is never replaced by the computation, and this check covers these two identities only.

Deterministic guards. After model generation, local Python rules examine text and structured data. No model is called to make decisions within these guards. Doctrine “deliver everything, flag in place”: the principle is to keep. An unsupported quantity stays where it is, highlighted and followed by “⚠ to verify — reason”; a figure contradicted by a document carries the document’s value; the first-page box counts and lists the flagged passages, and the register records them. Current exceptions: personal calculations (remuneration, dividends, self-employed status) are removed; without primary financial statements for the perimeter, the Finance note of a one-person company (SASU, EURL, sole trader) or a very short note is replaced by a prudence frame; some accounting wordings receive a standard reservation, which must itself be checked against the documents. Only a technical failure prevents delivery. These checks reduce some risks; they guarantee neither error-free results, completeness nor a complete trace of every transformation. Legitimate content may be over-labelled or masked; incorrect content may escape detection. Review the Word documents and compare reservations, registers and sources before use.

The two Word documents are the main deliverables: detailed analysis and decision synthesis. The PPTX is a presentation draft to revise after reading them, not a standalone document ready to hand over. Length depends on the brief and available material; page and slide counts are indicative, not guaranteed. The complete package brings together the files actually generated, diagnostics, available registers, preparation journal and manifest.

Human review and the PPTX draft status are not a general exemption from applicable obligations. The applicability note must distinguish provider and deployer roles, intended use and the actual mode of distribution. No proprietary mark, score or test count is represented here as compliance certification.

## Features relevant to compliance

- **Stronger human oversight**: a status the leader writes in the brief (decided, completed, postponed, dropped) is never rewritten by the product; a decision an agent claims without support in the brief is flagged “decided status not established by the brief”. The agents' recommendation is no longer presented as a committee decision.
- **Figure traceability**: every value shown on a key figure card carries its fiscal year and, when it comes from a public filing (SEC, Companies House, Pappers), its source; a figure contradicted by the document or the filings is flagged with the reference value.
- **Model**: the default Anthropic model becomes Claude Sonnet 5.5, Claude Sonnet 4.5 being retired from the API on 24/11/2026. A model change can alter the shape of outputs: mandatory human review and the product's safeguards apply unchanged.
