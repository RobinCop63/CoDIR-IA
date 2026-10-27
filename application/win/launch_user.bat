@echo off
REM CoDIR IA v16.5.76 - Windows User Launcher
REM Resolution du venv (ordre de priorite) :
REM   1. outputs\venv_path.txt (ecrit par setup_windows.bat)
REM   2. %LOCALAPPDATA%\CoDIR-IA\.venv (chemin standard depuis v16.5.60)
REM   3. .venv local au repo (retrocompat dev/portable)

cd /d "%~dp0.."

set "VENV_PATH="

REM --- [1] outputs\venv_path.txt ---
if exist "outputs\venv_path.txt" (
  set /p VENV_PATH=<outputs\venv_path.txt
)

REM --- [2] Chemin standard LOCALAPPDATA ---
if "%VENV_PATH%"=="" (
  if exist "%LOCALAPPDATA%\CoDIR-IA\.venv\Scripts\python.exe" (
    set "VENV_PATH=%LOCALAPPDATA%\CoDIR-IA\.venv"
  )
)

REM --- [3] Fallback local ---
if "%VENV_PATH%"=="" (
  if exist ".venv\Scripts\python.exe" (
    set "VENV_PATH=.venv"
  )
)

REM Verification finale
if "%VENV_PATH%"=="" (
  echo [ERREUR] venv introuvable.
  echo   Cherche : outputs\venv_path.txt, %%LOCALAPPDATA%%\CoDIR-IA\.venv, .venv
  echo   Lance setup_windows.bat d'abord.
  pause
  exit /b 1
)

if not exist "%VENV_PATH%\Scripts\python.exe" (
  echo [ERREUR] venv corrompu a l'emplacement : %VENV_PATH%
  echo   Relance setup_windows.bat.
  pause
  exit /b 1
)

if not defined CODIR_PARSE_ENGINE set "CODIR_PARSE_ENGINE=thread"
"%VENV_PATH%\Scripts\python.exe" -m streamlit run app.py --server.headless true
