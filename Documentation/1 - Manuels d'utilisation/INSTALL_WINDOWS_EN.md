# Windows Installation — CoDIR IA v17.0 (build 9.4.65)

**Software:** CoDIR IA v17.0 — build `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`  
**Documentation revision:** 18 October 2026  
**Use:** supervised professional use

Build: `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`

## Requirements

- 64-bit Windows 10/11 on Intel/AMD (x64) PCs; Windows 11 on ARM PCs. On an ARM PC, CoDIR IA uses an x64 Python, run by the x64 emulation built into Windows 11 (Windows 10 on ARM does not emulate x64 and is not supported; the launcher stops there with a clear message), because four locked dependencies publish no ARM64 build: the launcher picks an x64 Python already installed, or installs Python 3.12 x64, and rejects a native ARM64 Python. 32-bit Windows is not supported, and a 32-bit Python is rejected;
- standard CPython 3.11–3.14; 3.11 or 3.12 recommended;
- HTTPS access to enabled providers;
- no free-threaded/no-GIL build.

## Recommended path

1. In PowerShell, run `Get-FileHash -LiteralPath ".\EXACT_ZIP_NAME.zip" -Algorithm SHA256`. Replace the example name with the received filename and compare the fingerprint with the trusted sealing reference.
2. Extract the ZIP to a local folder, preferably outside OneDrive.
3. Double-click `DEMARRER_CODIR_IA.bat`.
4. The launcher verifies every `SHA256SUMS` entry **before** any `Unblock-File` action.
5. A mismatch or missing file stops the launch: delete the folder and download again.
6. After successful verification, the launcher removes `Zone.Identifier` only from package files, selects a compatible CPython, installs the venv and displays the launch URL. The public launchers use port 8501: open the address displayed (`http://127.0.0.1:8501`). If this port is in use, close the other instance or ask your administrator to free the port, then relaunch; the launcher does not automatically select another port.

## Updating from an earlier version

Close CoDIR IA, extract the new version into a new folder, then run `DEMARRER_CODIR_IA.bat`. The launcher compares the fingerprint of the supplied dependency lock with that of the shared Python environment (`%LOCALAPPDATA%\CoDIR-IA\.venv`): if they differ, it sets the old environment aside as `.venv-precedent`, installs the supplied lock and removes the old Desktop shortcut, which is recreated at the next launch. Your settings and data (`%APPDATA%\CoDIR-IA`) are not touched. Check: `INSTALL_MODE.txt` says `locked requirements.lock`. Once checked, you may delete `.venv-precedent`. If the environment cannot be set aside because CoDIR IA is still open, the launcher stops: close every CoDIR IA window and run it again. If the dependencies could only be installed in fallback mode, without the lock, the launcher says so at every start. The “CoDIR IA” desktop shortcut goes through `DEMARRER_CODIR_IA.bat`, and therefore through the same checks.

## SmartScreen

The supplied .bat launchers are unsigned; no Authenticode-signed installer is supplied. SmartScreen may require initial confirmation. Choose “Run anyway” only after checking source, SHA and manifest.

Recommended: before extracting, right-click the zip > Properties > tick « Unblock » > OK; the first double-click then installs and launches, with no relaunch. Otherwise, on the SmartScreen screen: « More info » > « Run anyway ». Authenticode signing is planned for v18 (with Microsoft Store distribution).

## Locations

- configuration: `%APPDATA%\CoDIR-IA`;
- cache: `%LOCALAPPDATA%\CoDIR-IA\cache`;
- venv and installer logs: `%LOCALAPPDATA%\CoDIR-IA`;
- data/history: `%APPDATA%\CoDIR-IA\data`;
- outputs: `application\outputs` or the selected download location.

## Model and public sources

- **Default Anthropic model: Claude Sonnet 5.5** (`claude-sonnet-5-5`). Claude Sonnet 4.5 is retired from the API on 24/11/2026; a setting saved on an older Sonnet is migrated automatically at first launch.
- **SEC contact** (`SEC_EDGAR_USER_AGENT`, “First Last address@domain”): required to read the SEC filings of a US-listed company; without it, the SEC is not queried.
- **Companies House key** (`COMPANIES_HOUSE_API_KEY`, free on the Companies House Developer Hub): needed for UK companies; a separate document API key (`COMPANIES_HOUSE_DOCUMENT_API_KEY`) is possible as an advanced option. Accounts filed as a scanned PDF yield no value.
- **Pappers key** (`PAPPERS_API_KEY`): optional, for French companies (filed accounts, except confidential accounts).
- These settings are entered on the application's **Settings** page and saved in the configuration folder (`%APPDATA%\CoDIR-IA`). Only the company identifier is sent to these services, never your documents.

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

Close CoDIR IA, delete the installation folder, `%APPDATA%\CoDIR-IA`, `%LOCALAPPDATA%\CoDIR-IA`, outputs and shortcuts. Revoke API keys where appropriate.

## Installation, controls and limits

The launcher looks for standard CPython within the intended 3.11–3.14 range. If locked installation fails and requirements.txt fallback is used, the environment no longer exactly matches the lock or SBOM: retain INSTALL_MODE.txt and the log, then have the deployment checked. A launcher’s presence does not certify a platform or architecture; consult the applicable native-test matrix.

Local does not mean offline. The interface, storage and guards run on the computer; enabled AI providers, registries and searches receive content needed by their functions. The guards are neither anonymisation nor a firewall before transmission. The brief, excerpts and, depending on submitted context, history items may leave the computer. Check your rights and provider accounts before running.

Deterministic guards. After model generation, local Python rules examine text and structured data. No model is called to make decisions within these guards. Doctrine “deliver everything, flag in place”: the principle is to keep. An unsupported quantity stays where it is, highlighted and followed by “⚠ to verify — reason”; a figure contradicted by a document carries the document’s value; the first-page box counts and lists the flagged passages, and the register records them. Current exceptions: personal calculations (remuneration, dividends, self-employed status) are removed; without primary financial statements for the perimeter, the Finance note of a one-person company (SASU, EURL, sole trader) or a very short note is replaced by a prudence frame; some accounting wordings receive a standard reservation, which must itself be checked against the documents. Only a technical failure prevents delivery. These checks reduce some risks; they guarantee neither error-free results, completeness nor a complete trace of every transformation. Legitimate content may be over-labelled or masked; incorrect content may escape detection. Review the Word documents and compare reservations, registers and sources before use.
