# First Windows run — CoDIR IA v17.0

**Software:** CoDIR IA v17.0 — build `v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65`  
**Documentation revision:** 18 October 2026  
**Use:** supervised professional use

Verify the external ZIP hash, then the manifest after extraction. Use a local, non-synchronised folder and `DEMARRER_CODIR_IA.bat`. The launcher checks `SHA256SUMS` before unblocking; integrity checks do not prove defect-free software.

Artifacts actually supplied: unsigned Windows .bat launchers and macOS .command scripts in a ZIP; an .app shortcut may be created locally. The ZIP is not represented as Authenticode-signed; no Developer ID-signed and notarized application bundle is supplied. Operating-system warnings are expected. Verify provenance, the external ZIP hash and the manifest; do not disable SmartScreen or Gatekeeper globally. The signing decision, native-test evidence and release approval remain outside the archive.

After starting, check target, scope, **the intended analysis date** and keys. Do not use LIVE mode to bypass a retrospective analysis. Configuration/cache/data paths differ from the ZIP. Declared architectures must be compared with the native-test matrix.

The launcher looks for standard CPython within the intended 3.11–3.14 range. If locked installation fails and requirements.txt fallback is used, the environment no longer exactly matches the lock or SBOM: retain INSTALL_MODE.txt and the log, then have the deployment checked. A launcher’s presence does not certify a platform or architecture; consult the applicable native-test matrix. Free-threading / no-GIL Python builds are refused; standard CPython is required. Windows ARM64 is intended subject to binary-wheel availability (the launcher selects a compatible architecture); compare it with the native-test matrix.

See `INSTALL_WINDOWS_EN.md` and the complete manuals under `1 - Manuels d'utilisation`.
