# Privacy and Data-Flow Notice — CoDIR IA

**Software:** CoDIR IA v17.0 — build `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`  
**Documentation revision:** 18 October 2026  
**Use:** supervised professional use

**Publisher:** Vauquigneux Gestion SASU, French company number (SIREN) 102 885 654, 6 Cours des Vauquigneux, 35310 Mordelles, France  
**Updated:** contractual text unchanged since 27 September 2026; editorial revision of 18 October 2026
**Status:** product notice; GDPR roles must be qualified for each deployment

## 1. No publisher telemetry and scope of this notice

CoDIR IA v17.0 has no publisher-operated application server or central publisher telemetry. It runs locally. It nevertheless stores settings, targets, caches, history, logs and deliverables on the workstation and sends data to providers enabled by the user.

Depending on the deployment, the customer organisation may be controller, Vauquigneux Gestion may act as software provider, service provider or processor, and API providers may be subprocessors or independent controllers. The signed contract and, where required, an Article 28 GDPR agreement must define those roles.

## 2. Data categories and purposes

| Category | Product purpose | Location / recipient | Indicative retention |
|---|---|---|---|
| API keys | Authenticate selected calls | local `secrets.json` | until deletion |
| Settings and canonical target | Cross-screen consistency | local `settings.json` | until changed |
| Registry/document caches | Performance, quotas, continuity | local `cache` directory | module TTL or purge |
| Case history | Follow-up continuity | local `data` directory | until deletion |
| Logs | Diagnostics and security | local `logs` directory | rotation; 14 crash-log backups |
| Briefs and extracted text | Model analysis | configured providers | provider contract |
| Company identifiers | Registry resolution; published financial facts (last known dated figure) | Pappers, Companies House, GLEIF, SEC… | provider terms |
| Deliverables | Professional working material | `outputs` and selected destination | until deletion |

**Published financial facts.** For the last-known dated figure rule and prior-year checks, CoDIR IA reads amounts the company has already published, from the SEC, Companies House and Pappers. Only the company identifier (CIK, Companies House number, SIREN) is sent, plus, for the SEC, the identifying contact it requires. No client document, brief or excerpt is sent to these services. GLEIF only provides the legal identity.

## 3. Canonical local locations

- Windows: `%APPDATA%\CoDIR-IA` for configuration and `%LOCALAPPDATA%\CoDIR-IA` for cache, venv and installer logs;
- macOS: `~/Library/Application Support/CoDIR-IA`;
- Linux: `$XDG_CONFIG_HOME/CoDIR-IA` or `~/.config/CoDIR-IA`.

The launchers explicitly set `CODIR_CONFIG_DIR` and `CODIR_CACHE_DIR` in launchers. Legacy `~/.codir_ia` locations are retained only for migration and are included in deletion instructions.

## 4. Data sent to providers

Enabled features may transmit brief text, extracted attachment text, relevant financial blocks, role instructions, legal identifiers, web/registry queries and minimal technical metadata. Raw files are sent only where a feature expressly provides for it.

Potential providers are listed in `SUBPROCESSORS_AND_TRANSFERS.md`. Role, processing location and safeguards depend on the user’s account and contract; the software must not assume a region or transfer mechanism.

## 5. Legal bases and transparency

The applicable legal basis depends on the deployment: contract, legitimate interests, legal obligation or consent where required. The controller must provide Articles 12–14 GDPR information, document the legal basis, minimise data and organise data-subject rights.

## 6. Data-subject rights

Depending on context, individuals may have rights of access, rectification, erasure, restriction, objection, portability and withdrawal of consent, and may complain to the CNIL. Requests concerning local data are handled by the organisation operating the workstation; provider-side requests follow the relevant contract and provider process.

## 7. Processing agreements and transfers

Where processing is carried out for a customer, an Article 28 agreement must define subject matter, duration, nature, purposes, data and data-subject categories, instructions, security, subprocessors, assistance, return/deletion and audits. A working template is provided in the data processing agreement template (not included in this distribution; provided on request within a contractual relationship).

Transfers outside the EEA must be mapped and supported by an adequacy decision, standard contractual clauses, BCRs or another Chapter V GDPR mechanism, with supplementary assessment where required.

## 8. Security and minimisation

Users must exclude unnecessary data, pseudonymise where possible, limit attachments to the professional need and review provider retention settings. Keys are stored locally in clear text in CoDIR IA v17.0; an enterprise secret vault is recommended for sensitive deployments.

## 9. Deletion and uninstall

Complete local deletion covers the configuration directory, cache directory, any legacy `~/.codir_ia`, installation folder, venv, outputs and shortcuts. Data already sent to a provider must be handled through that provider’s contract and tools.

## 10. Contact

Initial requests: https://robinsauzet.com/contact/. For a GDPR request related to a customer deployment, contact the controller identified in that organisation’s own privacy notice first.

## 11. Official references

- GDPR: https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng
- CNIL transparency guidance: https://www.cnil.fr/fr/conformite-rgpd-information-des-personnes-et-transparence
- CNIL processors: https://www.cnil.fr/fr/sous-traitant
- CNIL international transfers: https://www.cnil.fr/fr/les-outils-de-la-conformite/transferer-des-donnees-hors-de-lue

## Local operation, external calls and the publisher's own processing

CoDIR IA runs locally and calls the external services you enable. Providing the software does not, by itself, give Vauquigneux Gestion access to the contents of your analyses. Three things are distinct: local operation (your documents, caches and logs stay on your machine); transfers to the providers you enable, governed by your accounts and their terms; and the publisher's own processing — contact, support, security reports — described in its own section.

**Data-protection roles.** They depend on the processing actually performed. You may act on your own behalf or on behalf of a client; the providers you enable may form a processing chain that must be assessed. Before any processing of personal data on behalf of a third party, applicable instructions, safeguards, authorisations and contracts must be established — including for a free pilot or free assistance: **price is not the trigger**. Confidentiality alone, with no personal data, falls under other authorisations and does not by itself require a processing agreement.

**Sources, transfers and verification.** Availability of a document, service or interface does not grant a right to transmit or redistribute it. Terms, retention and content-use settings, and transfer safeguards depend on the services and accounts you actually use: verify them for your role. Referring to a provider's contract is not a blanket validation of every deployment.

## Processing of security reports and support requests

**Controller:** Vauquigneux Gestion SASU, publisher of CoDIR IA. **Purposes:** handling a vulnerability report or a support request, replying to you, and keeping a record of the decisions taken. **Data processed:** e-mail address, the identity you provide, the content of your message and any attachments. **Legal basis:** the publisher's legitimate interest in securing its product and handling reports; performance of pre-contractual or contractual measures where the request arises in a business relationship. **Recipients:** the authorised person(s) at the publisher; the business e-mail service hosting the `security@vauquigneux.com` mailbox, whose terms and retention settings are governed by the publisher's contract with that provider. **Retention:** the active file is kept for the time needed to handle and close the report; material needed as evidence of a regulated notification is archived separately, with restricted access, for the period justified by that purpose. **Your rights:** access, rectification, erasure, restriction and objection can be exercised at the same address; you may lodge a complaint with the CNIL. **Recommendation:** do not send secrets, unnecessary personal data or client documents.

## Guards, memory and transmission: practical boundaries

Local does not mean offline. The interface, storage and guards run on the computer; enabled AI providers, registries and searches receive content needed by their functions. The guards are neither anonymisation nor a firewall before transmission. The brief, excerpts and, depending on submitted context, history items may leave the computer. Check your rights and provider accounts before running.

Memory between meetings. The code includes local case history and a timestamped action register. Reuse the same case — the same “Dossier label” from one meeting to the next — and check the entity, identifier, data directory and analysis date. State genuinely approved decisions, completed or deferred actions and explicit closures in the next brief. Then review carried-over items and changes: repetition does not approve a proposal. Retrospective/future modes do not write to the live register; the “Start fresh — ignore this folder’s history” box (technical variable CODIR_IGNORE_HISTORY) disables carry-over for an isolated test. This documentation revision does not certify exhaustive decision, action and question continuity across two meetings; verify it for your case. This is not memory of all conversations or model training.

Registers, history, archived answers and logs may retain content absent from the deliverable body. Removing a number from Word does not erase it from other files or provider systems. Review the package before sharing; back up and delete case data under your retention policy. This revision creates no encrypted vault, remote deletion function or automatic lawfulness assessment.
