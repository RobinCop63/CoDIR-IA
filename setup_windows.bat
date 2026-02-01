@echo off
setlocal ENABLEDELAYEDEXPANSION

REM =============================================
REM   CoDIR IA v16.0 - Installation Windows
REM   Double-clic pour installer + creer raccourci
REM =============================================

cd /d "%~dp0"

echo.
echo ==============================================
echo   CoDIR IA v16.0 - Installation Windows
echo ==============================================
echo.

REM 1) Verifier Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas installe ou pas dans le PATH.
    echo          Telechargez Python sur https://www.python.org/downloads/
    echo          Cochez "Add Python to PATH" lors de l'installation.
    pause
    exit /b 1
)
echo [OK] Python detecte

REM 2) Creer venv si necessaire
if not exist ".venv" (
    echo.
    echo [1/4] Creation de l'environnement virtuel...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERREUR] Impossible de creer le venv.
        pause
        exit /b 1
    )
) else (
    echo [OK] Environnement virtuel existant
)

REM 3) Activer et installer dependances
echo.
echo [2/4] Installation des dependances...
call ".venv\Scripts\activate"
python -m pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERREUR] Erreur d'installation des dependances.
    pause
    exit /b 1
)
echo [OK] Dependances installees

REM 4) Creer .env si absent
if not exist ".env" (
    echo.
    echo [3/4] Creation du fichier .env...
    if exist ".env.template" (
        copy ".env.template" ".env" >nul
        echo [OK] Fichier .env cree - IMPORTANT: editez-le pour ajouter vos cles API
    ) else (
        echo [ATTENTION] Pas de .env.template trouve. Creez un fichier .env manuellement.
    )
) else (
    echo [OK] Fichier .env existant
)

REM 4b) Ouvrir .env dans le Bloc-notes si aucune cle API n'est renseignee
set "ENV_FILE=%CD%\.env"
call :CHECK_ENV_READY
if "%ENV_READY%"=="0" (
    echo.
    echo [ACTION] Aucune cle API detectee dans .env.
    echo          Ouverture de .env dans le Bloc-notes...
    start /wait notepad "%ENV_FILE%"
    call :CHECK_ENV_READY
)

REM 5) Creer le raccourci Bureau
echo.
echo [4/4] Creation du raccourci sur le Bureau...
powershell -ExecutionPolicy Bypass -File "%~dp0win\create_shortcut.ps1"
if errorlevel 1 (
    echo [ATTENTION] Le raccourci n'a pas pu etre cree automatiquement.
    echo             Vous pouvez lancer l'app avec launch_codir.bat
) else (
    echo [OK] Raccourci cree sur le Bureau
)

echo.
echo ==============================================
echo   Installation terminee !
echo ==============================================
echo.
echo   IMPORTANT - Avant la premiere utilisation :
echo   1. Le fichier .env a ete cree (si besoin)
echo   2. Ajoutez vos cles API (OpenAI, Anthropic, etc.)
echo.
if "%ENV_READY%"=="0" (
echo   [ATTENTION] Aucune cle API n'a ete detectee. L'app ne pourra pas appeler les IA.
)
echo.
echo   Pour lancer CoDIR IA :
echo   - Double-cliquez sur l'icone "CoDIR IA" sur le Bureau
echo   - Ou double-cliquez sur launch_codir.bat
echo.
echo   NOTE: L'utilisation des API IA est payante.
echo   Les couts sont factures par chaque fournisseur
echo   (OpenAI, Anthropic, Google, Mistral).
echo.
pause

exit /b 0

:CHECK_ENV_READY
set "ENV_READY=0"
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
