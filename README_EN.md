# CoDIR IA v17.0

**Software:** CoDIR IA v17.0 — build `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`  
**Documentation revision:** 18 October 2026  
**Use:** supervised professional use

> **Language:** the interface is chosen on the welcome screen at launch (Français / English); the language of the documents is chosen separately in the brief — an English interface can produce French documents and vice versa. Version française : [README.md](README.md).

CoDIR IA prepares an on-demand management committee for consultants, interim managers and SME/industrial SME/mid-cap executives, using the selected brief and documents. The long Word report carries the analysis; the short Word synthesis presents conclusions and matters for decision. They are the two main deliverables, to be reviewed and validated by the professional. The PPTX is an editable draft to complete after reading the Word documents: selection, messages, illustrations and layout remain the professional’s work. Local case history supports continuity between meetings; it does not replace approved minutes or human validation.

## At a glance

- **Committee preparation by function**: Strategy, Finance (with a second opinion), Marketing, Sales, Supply chain (with a challenger) and General management, then a synthesis of the decisions to make.
- **Four outputs**: the Word minutes, the Word summary, an editable PowerPoint draft and the full package (control files, registers, diagnostics).
- **Keep and flag**: a doubtful figure or passage is delivered and flagged in place, with its reason (« ⚠ to verify — … »); exceptions: personal calculations are removed and, without primary financial statements, a one-person company or a very short Finance note receives a prudence frame. The annotations themselves must be reviewed.
- **Memory from one session to the next**: an action register, and statuses you declare in the brief (completed, postponed, dropped, kept, board decision), applied from that session; those that do not find their action are listed in the minutes.
- **Published facts** taken from official registers when available (SEC/EDGAR, Pappers, Companies House, GLEIF).
- **A twelve-step progress screen** during processing, then a « Package ready » screen.

## Requirements

64-bit Windows 10/11 on Intel/AMD PCs, Windows 11 on ARM PCs, or macOS on Apple silicon Macs (M1 and later); Python 3.11 to 3.14 on Windows, 3.11 to 3.13 on macOS (the launcher checks the version; on an ARM PC running Windows 11 it uses an x64 Python run by Windows emulation, and installs it if needed); Intel Macs, 32-bit Windows and Windows 10 on ARM PCs are not supported by this version; API keys for the AI providers you enable (the table of roles and models is in the installation guide); optionally, an identifier for public registers. CoDIR IA does not decide for you: every deliverable must be reviewed and validated before distribution.

## Start

Verify the external ZIP hash, extract to a local folder and check `SHA256SUMS`. Windows: `DEMARRER_CODIR_IA.bat`. macOS: `Demarrer_Mac.command`. Read the installation guide before allowing unsigned scripts. Do not disable device protection globally.

**First launch (application not signed in v17.0, signing planned for v18).** Windows: before extracting, right-click the zip > Properties > tick « Unblock » > OK — the first double-click then installs and launches; otherwise, when SmartScreen appears: « More info » > « Run anyway ». macOS: right-click `Demarrer_Mac.command` > Open, or System Settings > Privacy & Security > Open Anyway.

## Where to find information

| Need | Document |
|---|---|
| Reading path and history | [Read the documentation](Documentation/READ_THE_DOCUMENTATION_EN.md) |
| Installation/use FR and EN | `Documentation/1 - Manuels d'utilisation/` |
| Current changes and limitations | [Release notes](RELEASE_NOTES_EN.md) |
| Terms, privacy, providers | `Documentation/2 - Conditions et confidentialite/` |
| Security, AI Act, SBOM | `Documentation/3 - Securite et conformite/` |
| Status of this documentation package | [Documentation status](Documentation/ETAT_DOCUMENTAIRE.md) |
| Français | [README français](README.md) |

## Licence, data and status

Source-available **FSL-1.1-ALv2** code: `application/LICENSE`. Trademark/logo: `application/TRADEMARKS.md`. Permitted professional use and handover of outputs under the Terms do not, in themselves, require additional publisher authorisation.

Local does not mean offline. The interface, storage and guards run on the computer; enabled AI providers, registries and searches receive content needed by their functions. The guards are neither anonymisation nor a firewall before transmission. The brief, excerpts and, depending on submitted context, history items may leave the computer. Check your rights and provider accounts before running.

English remains a preview. Deterministic guards reduce some risks without guaranteeing accuracy or completeness. Controls and counters do not replace human review or the cumulative release gate. The publisher’s release decision is an act outside this archive; the published version is identified by its SHA-256 fingerprint in the release notes.

Reporting: **security@vauquigneux.com**, subject `[SECURITY CoDIR IA]`. No secrets or client documents in the first message. See `SECURITY.md` at the root and `Documentation/3 - Securite et conformite/SECURITY_EN.md`.
