@echo off
setlocal EnableExtensions
REM CoDIR IA v16.5.76 - lanceur Windows courant.
REM v62.10 - auto-deblocage des fichiers extraits depuis un ZIP telecharge.
REM Since v16.5.75.5 - conservation du contrat historique de creation du raccourci bureau.
set "CODIR_ROOT=%~dp0.."
if not "%CODIR_INTEGRITY_VERIFIED%"=="1" (
  if exist "%CODIR_ROOT%\DEMARRER_CODIR_IA.bat" (
    call "%CODIR_ROOT%\DEMARRER_CODIR_IA.bat" %*
    set "ROOT_RC=%ERRORLEVEL%"
    endlocal & exit /b %ROOT_RC%
  )
  echo [ERREUR] Lanceur racine introuvable : verification d'integrite impossible.
  pause
  endlocal & exit /b 12
)
REM L'integrite et le deblocage sont geres par DEMARRER_CODIR_IA.bat.
if "%APPDATA%"=="" set "APPDATA=%USERPROFILE%\AppData\Roaming"
if "%LOCALAPPDATA%"=="" set "LOCALAPPDATA=%TEMP%"
if "%CODIR_CONFIG_DIR%"=="" set "CODIR_CONFIG_DIR=%APPDATA%\CoDIR-IA"
if "%CODIR_CACHE_DIR%"=="" set "CODIR_CACHE_DIR=%LOCALAPPDATA%\CoDIR-IA\cache"
if "%CODIR_DATA_DIR%"=="" set "CODIR_DATA_DIR=%APPDATA%\CoDIR-IA\data"

REM ============================================================================
REM CoDIR IA v16.5.76 - Windows installer/launcher
REM v62.12.8.3: batch parser hotfix; no generic 'py' pre-gate. The setup selects a compatible
REM standard CPython explicitly (3.11..3.14) and rejects free-threaded builds.
REM ============================================================================

if "%LOCALAPPDATA%"=="" set "LOCALAPPDATA=%TEMP%"
set "CODIR_LOG_DIR=%LOCALAPPDATA%\CoDIR-IA\logs"
if not exist "%CODIR_LOG_DIR%" mkdir "%CODIR_LOG_DIR%" >nul 2>&1
set "DEBUG_LOG=%CODIR_LOG_DIR%\install.log"
echo === CoDIR IA v17.0 - build 9.4.65 INSTALL_OR_LAUNCH.bat === > "%DEBUG_LOG%"
echo Date  : %date% %time% >> "%DEBUG_LOG%"
echo Script: INSTALL_OR_LAUNCH.bat >> "%DEBUG_LOG%"
echo Arch  : %PROCESSOR_ARCHITECTURE% >> "%DEBUG_LOG%"
echo. >> "%DEBUG_LOG%"

cd /d "%~dp0"
echo.
echo ============================================================
echo   CoDIR IA v17.0 - build v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65
echo   Installation et lancement automatiques
echo ============================================================
echo.

set "VENV_ROOT=%LOCALAPPDATA%\CoDIR-IA"
set "VENV_PATH=%VENV_ROOT%\.venv"
set "VENV_PY=%VENV_PATH%\Scripts\python.exe"
set "VSTREAMLIT=%VENV_PATH%\Scripts\streamlit.exe"
set "PROBE=%~dp0scripts\python_runtime_probe.py"
set "LOCK_FILE=%~dp0requirements.lock"
set "LOCK_MARK=%VENV_PATH%\CODIR_LOCK_SHA256.txt"

REM A valid existing venv launches directly; host Python is irrelevant here.
if not exist "%VSTREAMLIT%" goto first_install
if not exist "%VENV_PY%" goto repair_install
if not exist "%PROBE%" goto probe_missing

"%VENV_PY%" "%PROBE%" >> "%DEBUG_LOG%" 2>&1
if errorlevel 1 goto repair_install
REM 9.4.65 - verification du 19/10 (P02) : un environnement construit pour un autre verrou n'est jamais reutilise.
REM L'empreinte du verrou livre est comparee a celle que l'installation a enregistree dans le venv.
if not exist "%LOCK_FILE%" goto launch_app
set "LOCK_NOW="
for /f "usebackq delims=" %%H in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "(Get-FileHash -LiteralPath $env:LOCK_FILE -Algorithm SHA256).Hash"`) do set "LOCK_NOW=%%H"
if not defined LOCK_NOW goto lock_check_unavailable
set "LOCK_OLD="
if exist "%LOCK_MARK%" set /p LOCK_OLD=<"%LOCK_MARK%"
if /i "%LOCK_OLD%"=="%LOCK_NOW%" goto launch_app
REM 9.4.65 - contre-audit du 20/10 (R01) : environnement de repli construit pour ce verrou : pas de reinstallation en boucle,
REM mais un avertissement a chaque lancement (le marqueur FALLBACK ne vaut pas conformite au verrou).
if /i "%LOCK_OLD%"=="FALLBACK-%LOCK_NOW%" goto lock_fallback_env
goto stale_venv

:lock_fallback_env
echo [ATTENTION] Environnement Python installe en mode de REPLI, sans le verrou requirements.lock :
echo             les versions installees peuvent differer du SBOM et du scan publies.
echo             Voir le journal d'installation ; a signaler au support avant un usage professionnel.
echo [LOG] environnement de repli (marqueur FALLBACK) - lancement avec avertissement >> "%DEBUG_LOG%"
goto launch_app

:lock_check_unavailable
echo [LOG] empreinte du verrou indisponible - environnement existant conserve >> "%DEBUG_LOG%"
goto launch_app

:stale_venv
echo [INFO] L'environnement Python existant a ete construit pour une autre version de CoDIR IA.
echo        Il est mis de cote, puis les dependances de cette version sont installees.
echo [LOG] verrou different - installe=%LOCK_OLD% livre=%LOCK_NOW% - mise de cote du venv >> "%DEBUG_LOG%"
set "VENV_BAK=%VENV_ROOT%\.venv-precedent"
set "BAK_N=1"
:stale_bak_loop
if not exist "%VENV_BAK%" goto stale_bak_ready
set /a BAK_N+=1
set "VENV_BAK=%VENV_ROOT%\.venv-precedent-%BAK_N%"
goto stale_bak_loop
:stale_bak_ready
move "%VENV_PATH%" "%VENV_BAK%" >> "%DEBUG_LOG%" 2>&1
if exist "%VENV_PATH%" goto stale_move_failed
echo        Ancien environnement conserve : %VENV_BAK%
echo [LOG] ancien venv conserve : %VENV_BAK% >> "%DEBUG_LOG%"
REM L'ancien raccourci du Bureau peut viser une version precedente : il sera recree au prochain lancement.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Remove-Item -LiteralPath (Join-Path ([Environment]::GetFolderPath('Desktop')) 'CoDIR IA.lnk') -ErrorAction SilentlyContinue" >nul 2>&1
goto first_install

:stale_move_failed
echo [ERREUR] Impossible de mettre de cote l'environnement Python existant :
echo          %VENV_PATH%
echo          Fermez toutes les fenetres de CoDIR IA, puis relancez DEMARRER_CODIR_IA.bat.
echo [LOG] echec de la mise de cote du venv >> "%DEBUG_LOG%"
pause
endlocal & exit /b 1

:repair_install
echo [INFO] L'environnement Python existant est absent ou incompatible.
echo        CoDIR IA va le reparer avec un Python standard compatible.
echo [LOG] venv absent ou incompatible - appel setup_windows.bat >> "%DEBUG_LOG%"
goto first_install

:first_install
if not exist "setup_windows.bat" goto setup_missing
echo Premiere utilisation ou reparation detectee.
echo CoDIR IA cherche automatiquement un Python standard 3.11 a 3.14.
echo Python 3.11 ou 3.12 reste recommande. Les builds free-threading sont refuses.
echo.
call setup_windows.bat
set "INSTALL_RC=%ERRORLEVEL%"
echo [LOG] setup_windows.bat returncode=%INSTALL_RC% >> "%DEBUG_LOG%"
if not "%INSTALL_RC%"=="0" goto install_failed
endlocal & exit /b 0

:launch_app
echo [OK] Installation detectee - lancement de CoDIR IA...
if not exist "outputs" mkdir outputs
if exist "win\create_shortcut.ps1" if not exist "%USERPROFILE%\Desktop\CoDIR IA.lnk" powershell -NoProfile -ExecutionPolicy Bypass -File "win\create_shortcut.ps1" >nul 2>&1
echo ============================================================
echo   CoDIR IA demarre - navigateur : http://localhost:8501
echo   Fermez cette fenetre ou Ctrl+C pour arreter CoDIR IA
echo ============================================================
set "CODIR_PARSE_ENGINE=thread"
REM 9.4.65 - essai natif du 20/10 : un Quitter normal arrete Streamlit avec le code 1 ; le drapeau le signale.
set "QUIT_FLAG=%LOCALAPPDATA%\CoDIR-IA\logs\ARRET_DEMANDE.flag"
if exist "%QUIT_FLAG%" del "%QUIT_FLAG%" >nul 2>&1
"%VSTREAMLIT%" run "%~dp0app.py" --server.headless false --browser.gatherUsageStats false --server.port 8501 --logger.level error
set "STREAMLIT_RC=%ERRORLEVEL%"
echo [LOG] Streamlit termine rc=%STREAMLIT_RC% >> "%DEBUG_LOG%"
if exist "%QUIT_FLAG%" goto :quit_requested
if "%STREAMLIT_RC%"=="0" endlocal & exit /b 0
echo.
echo [ERREUR] CoDIR IA s'est arrete avec une erreur.
echo          Consultez : %DEBUG_LOG%
pause
endlocal & exit /b %STREAMLIT_RC%

:quit_requested
del "%QUIT_FLAG%" >nul 2>&1
echo [LOG] arret demande par Quitter - code %STREAMLIT_RC% attendu >> "%DEBUG_LOG%"
echo.
echo CoDIR IA est arrete.
endlocal & exit /b 0

:probe_missing
echo [ERREUR] Le controle de compatibilite Python est introuvable : %PROBE%
echo [LOG] python_runtime_probe.py introuvable >> "%DEBUG_LOG%"
pause
endlocal & exit /b 2

:setup_missing
echo [ERREUR] setup_windows.bat est introuvable dans ce dossier.
echo          Reextrayez le ZIP complet de CoDIR IA.
echo [LOG] setup_windows.bat introuvable >> "%DEBUG_LOG%"
pause
endlocal & exit /b 2

:install_failed
echo.
echo [ERREUR] L'installation a rencontre un probleme.
echo          Log setup    : %CODIR_LOG_DIR%\setup_windows.log
echo          Log demarrage: %DEBUG_LOG%
pause
endlocal & exit /b %INSTALL_RC%
