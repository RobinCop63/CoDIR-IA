# Security and Coordinated Vulnerability Disclosure Policy — CoDIR IA

**Software:** CoDIR IA v17.0 — build `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`  
**Documentation revision:** 18 October 2026  
**Use:** supervised professional use

**Updated:** 24 August 2026 · documentary revision of 18 October 2026

## Current reporting channel

Write to **security@vauquigneux.com** (main channel). If it is unavailable, the form https://robinsauzet.com/contact/ is the **fallback**; use it with subject **`[SECURITY CoDIR IA]`**. In the first message, provide only the affected version, platform, impact category, whether the issue is reproducible, and a safe reply method. Do not send API keys, unnecessary personal data, client secrets or detailed exploit material until an appropriate channel has been agreed.

Neither the dedicated mailbox nor the form is an end-to-end encrypted channel: do not send keys, passwords or client documents. If sensitive material is required, an appropriate channel is agreed upon reply. Publishing a PGP key remains an option, not an obligation derived from this policy.

## Supported versions

The current version, CoDIR IA v17.0, is supported. Security fixes may require an upgrade. Older versions are assessed case by case and are not guaranteed to receive backports.

## Target response times

- acknowledgement: within 3 business days;
- initial triage: within 7 business days;
- status update: at least every 14 days for an open report.

These targets are not contractual service levels.

## Coordinated disclosure

Researchers should avoid unauthorised access, persistence, exfiltration, alteration and premature publication. Vauquigneux Gestion will handle reasonable good-faith research and coordinate remediation and publication timing where possible.

## CRA internal workflow from 11 September 2026

As soon as the publisher becomes AWARE of an actively exploited vulnerability or a severe incident within the scope of Regulation (EU) 2024/2847 — without waiting for internal confirmation —, the designated reporting officer issues an early warning within 24 hours and a notification within 72 hours through the applicable reporting platform (national CSIRT / ENISA), then the reports within the Regulation's deadlines; this urgent path goes through neither the three-working-day acknowledgement nor the seven-day qualification of ordinary support. A false positive of the documentary control is not an incident within the meaning of the Regulation. The designated team must prepare the applicable early warning within 24 hours, notification within 72 hours, and final report within the relevant statutory period (including the vulnerability final report no later than 14 days after a corrective measure becomes available, or the incident final report within one month after notification). Notifications must use the applicable reporting platform and coordinating CSIRT. Product/manufacturer qualification must be confirmed for the distribution model.

**Current organisation:** Robin Sauzet, president of Vauquigneux Gestion, is the designated reporting officer. **No permanent deputy is designated to date**; where an absence of more than twelve hours is foreseeable, a backup contact is designated in writing for that period, with access to the mailbox. The designation of a permanent deputy is in progress and will be published here once settled.

## Records to retain

Version and SHA, awareness dates, affected products, impact, mitigations, affected users, relevant logs, disclosure decisions, regulatory notifications and evidence of remediation.

## Distribution controls

- verified SHA256SUMS manifest;
- locked dependencies and SBOM;
- no secrets in the ZIP;
- version and release traceability;
- explicit signing decision for the actual artefacts and description of their unsigned state;
- no representation of absolute security.

## Official reference

Cyber Resilience Act: https://eur-lex.europa.eu/eli/reg/2024/2847/oj/eng

## Reporting a vulnerability

Write to **security@vauquigneux.com**. The initial message should contain only: the software version, the platform, a non-sensitive description and a way to reply. **Do not attach keys, passwords or client documents.** If sensitive material is required, an appropriate private channel is agreed upon reply. Contact details and message contents are processed solely to handle the report; the terms are set out in the privacy notice. Internal handling times do not apply to statutory reporting duties, which run from the moment the facts become known.

## Actual artifact status and operational evidence

Artifacts actually supplied: unsigned Windows .bat launchers and macOS .command scripts in a ZIP; an .app shortcut may be created locally. The ZIP is not represented as Authenticode-signed; no Developer ID-signed and notarized application bundle is supplied. Operating-system warnings are expected. Verify provenance, the external ZIP hash and the manifest; do not disable SmartScreen or Gatekeeper globally. The signing decision, native-test evidence and release approval remain outside the archive.

security@vauquigneux.com is the declared channel: naming it is not proof of receipt. Keep the timestamped receipt test, authorised access, escalation arrangements and tested-machine matrix outside the archive. Numerical guards are neither a vulnerability scan nor a guarantee of legal or financial security.
