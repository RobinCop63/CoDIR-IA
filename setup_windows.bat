@echo off
setlocal
cd /d "%~dp0"

if not exist "outputs" mkdir outputs
set "LOG=outputs\setup_windows.log"

> "%LOG%" echo ==================================================
>>"%LOG%" echo CoDIR IA - setup_windows (Windows)
>>"%LOG%" echo Date: %date% %time%
>>"%LOG%" echo Folder: %cd%
>>"%LOG%" echo ==================================================

echo.
echo ========================================
echo  CoDIR IA - Installation (Windows)
echo ========================================
echo.

echo [1/5] Verification de Python...

REM Prefer py launcher when available (more reliable on Windows)
where py >nul 2>&1
if %ERRORLEVEL%==0 (
  set "PY=py -3"
) else (
  set "PY=python"
)

%PY% --version >>"%LOG%" 2>&1
if errorlevel 1 (
  echo.
  echo [ERREUR] Python non detecte.
  echo Installe Python 3.11/3.12 puis relance setup.
  echo Details: %LOG%
  echo [ERROR] Python not found >>"%LOG%"
  echo.
  pause
  exit /b 1
)

echo [2/5] Creation environnement virtuel (.venv)...

%PY% -c "import venv" >>"%LOG%" 2>&1
if errorlevel 1 (
  echo.
  echo [ERREUR] Module venv indisponible dans cette installation Python.
  echo Reinstalle Python en incluant la librairie standard.
  echo Details: %LOG%
  echo [ERROR] venv module missing >>"%LOG%"
  echo.
  pause
  exit /b 1
)

if exist ".venv\Scripts\python.exe" goto VENV_OK
if exist ".venv" (
  echo [INFO] .venv partiel detecte, suppression... >>"%LOG%" 2>&1
  rmdir /s /q ".venv" >>"%LOG%" 2>&1
)

%PY% -m venv .venv >>"%LOG%" 2>&1
if errorlevel 1 (
  echo.
  echo [ERREUR] Echec creation venv.
  echo Details: %LOG%
  echo.
  pause
  exit /b 1
)

:VENV_OK
set "VPY=.venv\Scripts\python.exe"

echo [3/5] Installation des dependances (silencieux)...
"%VPY%" -m ensurepip --upgrade >>"%LOG%" 2>&1
"%VPY%" -m pip install --upgrade pip setuptools wheel >>"%LOG%" 2>&1
"%VPY%" -m pip install --upgrade -r requirements.txt >>"%LOG%" 2>&1
if errorlevel 1 (
  echo.
  echo [ERREUR] Echec installation dependances.
  echo Details: %LOG%
  echo.
  pause
  exit /b 1
)

echo [4/5] Creation du raccourci Bureau...
if exist "win\create_shortcut.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "win\create_shortcut.ps1" >>"%LOG%" 2>&1
)

echo [5/5] Lancement de CoDIR IA...
call "%~dp0launch_codir.bat"
exit /b %ERRORLEVEL%
