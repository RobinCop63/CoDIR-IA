# Where does my data live?

**Software:** CoDIR IA v17.0 — build `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`  
**Documentation revision:** 18 October 2026  
**Use:** supervised professional use

| Platform | Configuration | Cache | Case data/history | Logs |
|---|---|---|---|---|
| Windows | `%APPDATA%\CoDIR-IA` | `%LOCALAPPDATA%\CoDIR-IA\cache` | `%APPDATA%\CoDIR-IA\data` | configuration/logs and LocalAppData/logs for the installer |
| macOS | `~/Library/Application Support/CoDIR-IA` | `…/cache` | `…/data` | `…/logs` |
| Linux | `$XDG_CONFIG_HOME/CoDIR-IA` or `~/.config/CoDIR-IA` | `$XDG_CACHE_HOME/CoDIR-IA` or configured path | configuration/data | configuration/logs |

The former `~/.codir_ia` may be read for migration. After verification, remove it during a complete uninstallation. See `PRIVACY_EN.md` and `SUBPROCESSORS_AND_TRANSFERS.md` for provider disclosures.

Local does not mean offline. The interface, storage and guards run on the computer; enabled AI providers, registries and searches receive content needed by their functions. The guards are neither anonymisation nor a firewall before transmission. The brief, excerpts and, depending on submitted context, history items may leave the computer. Check your rights and provider accounts before running.

Memory between meetings. The code includes local case history and a timestamped action register. Reuse the same case — the same “Dossier label” from one meeting to the next — and check the entity, identifier, data directory and analysis date. State genuinely approved decisions, completed or deferred actions and explicit closures in the next brief. Then review carried-over items and changes: repetition does not approve a proposal. Retrospective/future modes do not write to the live register; the “Start fresh — ignore this folder’s history” box (technical variable CODIR_IGNORE_HISTORY) disables carry-over for an isolated test. This documentation revision does not certify exhaustive decision, action and question continuity across two meetings; verify it for your case. This is not memory of all conversations or model training.

The JSONL action register is under `codir_register` in the effective data directory. Backing up the application alone does not back up case memory. Check effective paths and legacy `~/.codir_ia` data before deletion.
