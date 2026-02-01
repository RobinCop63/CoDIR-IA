@echo off
setlocal ENABLEDELAYEDEXPANSION

REM =============================================
REM   CoDIR IA - Launcher (Windows)
REM   Double-clic compatible
REM =============================================

REM Go to project root (this .bat is located at project root)
cd /d "%~dp0"

echo.
echo ==============================================
echo   CoDIR IA - Lancement (Windows)
echo ==============================================
echo   Dossier : %CD%
echo.

REM 0) S'assurer que le fichier .env existe et contient au moins une cle API
set "ENV_FILE=%CD%\.env"
set "ENV_TEMPLATE=%CD%\.env.template"

if not exist "%ENV_FILE%" (
  echo [0/4] Aucun .env detecte, creation...
  if exist "%ENV_TEMPLATE%" (
    copy "%ENV_TEMPLATE%" "%ENV_FILE%" >nul
  ) else (
    type nul > "%ENV_FILE%"
  )
)

call :CHECK_ENV_READY
if "%ENV_READY%"=="0" (
  echo.
  echo [ACTION] Aucune cle API detectee dans .env.
  echo          Ouverture de .env dans le Bloc-notes...
  start /wait notepad "%ENV_FILE%"
  call :CHECK_ENV_READY
)

if "%ENV_READY%"=="0" (
  echo.
  echo [ATTENTION] Aucune cle API n'a ete renseignee.
  echo            Remplissez .env puis relancez l'application.
  echo            Fichier : %ENV_FILE%
  pause
  exit /b 1
)

REM 1) Create venv if needed
if not exist ".venv" (
  echo [1/4] Creation de l'environnement virtuel...
  python -m venv .venv
  if errorlevel 1 (
    echo [ERREUR] Impossible de creer le venv. Verifiez que Python est installe.
    pause
    exit /b 1
  )
)

REM 2) Activate venv
call ".venv\Scripts\activate"
if errorlevel 1 (
  echo [ERREUR] Impossible d'activer le venv.
  pause
  exit /b 1
)

REM 3) Install requirements
echo [2/4] Installation des dependances...
python -m pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
if errorlevel 1 (
  echo [ERREUR] Erreur d'installation des dependances.
  pause
  exit /b 1
)

REM 4) Run Streamlit
echo.
echo [3/4] Demarrage de l'application...
echo.
python -m streamlit run app.py

echo.
pause

exit /b 0

:CHECK_ENV_READY
set "ENV_READY=0"
REM On considere l'environnement "pret" des qu'au moins UNE cle est renseignee
for %%K in (OPENAI_API_KEY ANTHROPIC_API_KEY GOOGLE_API_KEY GEMINI_API_KEY MISTRAL_API_KEY) do (
  for /f "usebackq tokens=1* delims==" %%A in (`findstr /i /r "^%%K=" "%ENV_FILE%"`) do (
    set "VAL=%%B"
    if not "!VAL!"=="" (
      if /I not "!VAL!"=="YOUR_KEY_HERE" if /I not "!VAL!"=="CHANGEME" if /I not "!VAL!"=="<YOUR_KEY>" (
        set "ENV_READY=1"
      )
    )
  )
)
exit /b 0
