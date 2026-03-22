@echo off
setlocal
cd /d "%~dp0"

if not exist "outputs" mkdir outputs
set "LOG=outputs\launch_codir.log"
set "SLOG=outputs\streamlit_windows.log"

> "%LOG%" echo ==================================================
>>"%LOG%" echo CoDIR IA - launch_codir (Windows)
>>"%LOG%" echo Date: %date% %time%
>>"%LOG%" echo Folder: %cd%
>>"%LOG%" echo ==================================================

echo.
echo ====================================
echo  CoDIR IA - Lancement (Windows)
echo ====================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERREUR] Environnement .venv introuvable. Lance d'abord setup_windows.bat
  echo [ERROR] .venv missing >>"%LOG%"
  echo Details: %LOG%
  echo.
  pause
  exit /b 1
)

set "PY=.venv\Scripts\python.exe"
"%PY%" -m streamlit --version >>"%LOG%" 2>&1
if errorlevel 1 (
  echo [ERREUR] Streamlit non trouve dans .venv. Relance setup_windows.bat
  echo [ERROR] streamlit missing >>"%LOG%"
  echo Details: %LOG%
  echo.
  pause
  exit /b 1
)

echo Lancement Streamlit...

start "CoDIR IA" "%PY%" -m streamlit run app.py --server.port 8501 --server.headless true --browser.gatherUsageStats false >"%SLOG%" 2>&1

REM Wait up to ~25 seconds for server to respond
set /a TRY=0
:WAIT
set /a TRY=%TRY%+1
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 http://127.0.0.1:8501 ; exit 0 } catch { exit 1 }" >nul 2>&1
if %ERRORLEVEL%==0 goto OPEN
if %TRY% GEQ 25 goto FAIL
timeout /t 1 >nul
goto WAIT

:OPEN
start "" "http://localhost:8501"
echo [OK] CoDIR IA lance sur http://localhost:8501
exit /b 0

:FAIL
echo.
echo [ERREUR] Streamlit n'a pas demarre.
echo Ouvre le log: outputs\streamlit_windows.log
echo.
pause
exit /b 1
