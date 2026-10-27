@echo off
REM CoDIR IA v16.5.76 - build v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65 - Arret propre du serveur (Windows)
REM Arrete UNIQUEMENT le serveur CoDIR-IA de ce dossier (via PID horodate), jamais tous les python.
setlocal
set "APPDIR=%~dp0.."
set "VPY=%LOCALAPPDATA%\CoDIR-IA\.venv\Scripts\python.exe"
if not exist "%VPY%" set "VPY=python"
echo Arret de CoDIR-IA en cours...
"%VPY%" "%APPDIR%\tools\stop_codir.py"
echo.
pause
