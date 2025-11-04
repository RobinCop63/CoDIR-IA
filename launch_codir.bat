@echo off
setlocal ENABLEDELAYEDEXPANSION
chcp 65001 >nul
title CODIR IA - Lancement

echo ==========================================
echo        🚀 Lancement de CODIR IA
echo ==========================================
echo.

:: Aller automatiquement dans le dossier du script
cd /d "%~dp0"

:: Vérifier requirements.txt
if not exist "requirements.txt" (
  echo ❌ ERREUR : requirements.txt introuvable.
  echo Place ce fichier .bat a la racine du projet CoDIR IA.
  pause
  exit /b 1
)

:: Vérifier Python
where python >nul 2>&1
if errorlevel 1 (
  echo ❌ ERREUR : Python 3.11+ non detecte.
  echo Installe Python puis relance.
  pause
  exit /b 1
)

:: Copier .env si absent
if not exist ".env" (
  if exist ".env.template" (
    echo ⚠️  Aucun fichier .env detecte, creation a partir du template...
    copy /y ".env.template" ".env" >nul
    echo ➜ Ouvre .env et ajoute tes cles API avant de relancer completement.
  ) else (
    echo ⚠️  Aucun .env ni template trouve.
  )
  echo.
)

:: Créer venv si absent
if not exist "venv\Scripts\activate.bat" (
  echo 🔧 Creation de l'environnement virtuel...
  python -m venv venv
)

:: Activation venv
call "venv\Scripts\activate.bat"
if errorlevel 1 (
  echo ❌ ERREUR : Echec activation venv.
  pause
  exit /b 1
)
echo ✅ Environnement Python active
echo.

:: Installer dependances
echo 🔧 Installation des dependances...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt
if errorlevel 1 (
  echo ❌ ERREUR installation dependances.
  pause
  exit /b 1
)

echo.
echo ▶️  Lancement de CoDIR IA...
echo (Ne ferme pas cette fenetre tant que l'app est ouverte)
echo.

where streamlit >nul 2>&1 && (streamlit run app.py) || (python -m streamlit run app.py)

echo.
echo ✅ Fin de session CoDIR IA
pause >nul
endlocal
