@echo off
REM =============================================
REM   CoDIR IA - Windows Launcher (Corrected)
REM   Version: 1.0.0
REM   Author: Robin Sauzet / Hi! Gestion
REM =============================================

echo.
echo ================================
echo   CoDIR IA - Windows Launcher
echo ================================
echo.

REM --- Move to script directory ---
cd /d "%~dp0"

REM --- Move to project root ---
cd ..

echo [OK] Position actuelle :
cd

REM --- Check Python installation ---
echo.
echo Vérification de Python...
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo ERREUR : Python n'est pas installé ou non accessible.
    echo Installez Python 3.10+ puis relancez.
    pause
    exit /b
)

REM --- Check venv existence ---
if not exist "venv" (
    echo.
    echo Création de l'environnement virtuel...
    python -m venv venv
)

REM --- Activate venv ---
echo.
echo Activation de l'environnement virtuel...
call venv\Scripts\activate

IF %ERRORLEVEL% NEQ 0 (
    echo ERREUR : Impossible d'activer le venv.
    pause
    exit /b
)

REM --- Install dependencies ---
echo.
echo Installation des dépendances...
pip install --upgrade pip
pip install -r requirements.txt

REM --- Create .env from template if needed ---
if not exist ".env" (
    echo.
    echo Création du fichier .env depuis .env.template...
    copy .env.template .env >nul
)

REM --- Launch CoDIR IA ---
echo.
echo Lancement de CoDIR IA...
streamlit run app.py

echo.
pause
