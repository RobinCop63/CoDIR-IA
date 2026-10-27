# macOS Installation — CoDIR IA v17.0 (build 9.4.65)

**Software:** CoDIR IA v17.0 — build `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`  
**Documentation revision:** 18 October 2026  
**Use:** supervised professional use

Build: `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`

## Requirements

- macOS 11 or later, on Apple Silicon Macs (M1 and later). Intel Macs are not supported by this version: a locked dependency, cryptography 50, no longer publishes an Intel build;
- standard CPython 3.11–3.13; 3.11/3.12 recommended; Python 3.14 is not yet supported on macOS, as a locked dependency publishes no binary for it there;
- network access to enabled providers.

## Installation path

1. Before extraction, calculate the ZIP SHA-256 with `shasum -a 256 "EXACT_ZIP_NAME.zip"`. Replace the example name with the received filename and compare the fingerprint with a reference published by a trusted source.
2. Extract the ZIP to a local folder. From the folder containing `SHA256SUMS`, run `shasum -a 256 -c SHA256SUMS`. Do not launch the application if a file is missing or a fingerprint differs.
3. Open `Demarrer_Mac.command`. After an unidentified-app block, use System Settings > Privacy & Security > Open Anyway where offered, only after checking provenance/integrity and organisational policy. Stop on malware or tampering warnings.
4. If Homebrew is absent, the script displays the official URL and requests explicit confirmation before download/execution.
5. Removing quarantine with `xattr` is proposed separately, limited to CoDIR IA items, and may be declined.
6. If quarantine is retained, follow the authorised opening procedure above where available; do not disable Gatekeeper globally.

## Trust and signing

Artifacts actually supplied: unsigned Windows .bat launchers and macOS .command scripts in a ZIP; an .app shortcut may be created locally. The ZIP is not represented as Authenticode-signed; no Developer ID-signed and notarized application bundle is supplied. Operating-system warnings are expected. Verify provenance, the external ZIP hash and the manifest; do not disable SmartScreen or Gatekeeper globally. The signing decision, native-test evidence and release approval remain outside the archive.

## Locations

Configuration, cache, data and logs: `~/Library/Application Support/CoDIR-IA` (`cache`, `data`, `logs` subdirectories). The venv remains in the application folder.

## Locations and operation

- Python environment: `application/.venv` in the installation folder;
- configuration, cache, data and logs: `~/Library/Application Support/CoDIR-IA`;
- during processing, the Mac is kept awake (`caffeinate`); closing a laptop lid may nevertheless cause sleep;
- « Quit », on the end screen, stops CoDIR IA without leaving a Python process;
- the “CoDIR IA” desktop shortcut opens `Demarrer_Mac.command`, and therefore the same integrity check as a double-click.

## Model and public sources

- **Default Anthropic model: Claude Sonnet 5.5** (`claude-sonnet-5-5`). Claude Sonnet 4.5 is retired from the API on 24/11/2026; a setting saved on an older Sonnet is migrated automatically at first launch.
- **SEC contact** (`SEC_EDGAR_USER_AGENT`, “First Last address@domain”): required to read the SEC filings of a US-listed company; without it, the SEC is not queried.
- **Companies House key** (`COMPANIES_HOUSE_API_KEY`, free on the Companies House Developer Hub): needed for UK companies; a separate document API key (`COMPANIES_HOUSE_DOCUMENT_API_KEY`) is possible as an advanced option. Accounts filed as a scanned PDF yield no value.
- **Pappers key** (`PAPPERS_API_KEY`): optional, for French companies (filed accounts, except confidential accounts).
- These settings are entered on the application's **Settings** page and saved in the configuration folder (`~/Library/Application Support/CoDIR-IA`). Only the company identifier is sent to these services, never your documents.

### AI models by role (state checked on 18/10/2026)

| Role | Provider | Default model |
|---|---|---|
| Minutes, Finance, Strategy, retries | Anthropic | `claude-sonnet-5-5` |
| General management, Marketing, CEO, Supply Chain pre-filter | OpenAI | `gpt-5.4` |
| Supply Chain (primary) | OpenAI | `gpt-5.4` |
| Finance (second opinion), Supply Chain challenger | Google | `gemini-3.6-flash` |
| Sales | xAI | `grok-4.3` |
| Decision synthesis, web search | Perplexity (Agent API) | `perplexity/sonar` |
| Entity resolution | Anthropic | `claude-haiku-4-5-20251001` |
| Last-resort fallback, in every role | **Mistral AI (Paris), European provider** | `mistral-medium-latest` (alias kept current by Mistral) |

A setting or environment variable left on a retired model (Claude Sonnet 4.5, gpt-4.1, Gemini 2.5, Grok 3, Sonar) is migrated automatically; the Settings page flags an environment variable that overrides a setting.

**Test before the first run**: in Settings, “Test connection” checks each key (model providers, Pappers, GLEIF, SEC, OpenSanctions, Companies House); “Test reading” also checks that published amounts can be read (SEC — 10-K, Pappers — financials, Companies House — iXBRL accounts, on a UK company number you enter).

## Uninstall

Close the terminal; delete the installation folder, `~/Library/Application Support/CoDIR-IA`, the `CoDIR IA.app` shortcut, outputs and, after review, legacy `~/.codir_ia`.

Packaging note: v17 packaging retains transparency marking (AI Act art. 50(4) where applicable).

Avoid a OneDrive/Dropbox-synchronised folder for the venv and working data.

## Installation, controls and limits

The launcher looks for standard CPython within the intended 3.11–3.13 range. If locked installation fails and requirements.txt fallback is used, the environment no longer exactly matches the lock or SBOM: retain INSTALL_MODE.txt and the log, then have the deployment checked. A launcher’s presence does not certify a platform or architecture; consult the applicable native-test matrix.

Local does not mean offline. The interface, storage and guards run on the computer; enabled AI providers, registries and searches receive content needed by their functions. The guards are neither anonymisation nor a firewall before transmission. The brief, excerpts and, depending on submitted context, history items may leave the computer. Check your rights and provider accounts before running.

Deterministic guards. After model generation, local Python rules examine text and structured data. No model is called to make decisions within these guards. Doctrine “deliver everything, flag in place”: the principle is to keep. An unsupported quantity stays where it is, highlighted and followed by “⚠ to verify — reason”; a figure contradicted by a document carries the document’s value; the first-page box counts and lists the flagged passages, and the register records them. Current exceptions: personal calculations (remuneration, dividends, self-employed status) are removed; without primary financial statements for the perimeter, the Finance note of a one-person company (SASU, EURL, sole trader) or a very short note is replaced by a prudence frame; some accounting wordings receive a standard reservation, which must itself be checked against the documents. Only a technical failure prevents delivery. These checks reduce some risks; they guarantee neither error-free results, completeness nor a complete trace of every transformation. Legitimate content may be over-labelled or masked; incorrect content may escape detection. Review the Word documents and compare reservations, registers and sources before use.
