@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM CoDIR IA v16.5.76 - Setup Windows courant.
REM Since v16.5.75.5 - raccourci Bureau et affichage des erreurs conserves.
REM v62.12.8.3 - correctif parseur batch ; selection explicite d'un CPython standard 3.11 a 3.14 (9.4.65 : 3.10 retire, refuse par les dependances).

cd /d "%~dp0"
if "%LOCALAPPDATA%"=="" set "LOCALAPPDATA=%TEMP%"
set "INSTALL_DIR=%~dp0"
if "%APPDATA%"=="" set "APPDATA=%USERPROFILE%\AppData\Roaming"
set "CODIR_CONFIG_DIR=%APPDATA%\CoDIR-IA"
set "CODIR_CACHE_DIR=%LOCALAPPDATA%\CoDIR-IA\cache"
set "CODIR_DATA_DIR=%APPDATA%\CoDIR-IA\data"
if not exist "%CODIR_CONFIG_DIR%" mkdir "%CODIR_CONFIG_DIR%" >nul 2>&1
if not exist "%CODIR_CACHE_DIR%" mkdir "%CODIR_CACHE_DIR%" >nul 2>&1
if not exist "%CODIR_DATA_DIR%" mkdir "%CODIR_DATA_DIR%" >nul 2>&1
set "VENV_ROOT=%LOCALAPPDATA%\CoDIR-IA"
set "VENV_PATH=%VENV_ROOT%\.venv"
set "VPY=%VENV_PATH%\Scripts\python.exe"
set "VSTREAMLIT=%VENV_PATH%\Scripts\streamlit.exe"
set "PROBE_SCRIPT=%INSTALL_DIR%scripts\python_runtime_probe.py"
set "LOG_DIR=%LOCALAPPDATA%\CoDIR-IA\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
set "LOG=%LOG_DIR%\setup_windows.log"
set "PY314_DEP_FALLBACK="
set "PY312_INSTALL_TRIED="

if not exist "%INSTALL_DIR%outputs" mkdir "%INSTALL_DIR%outputs" >nul 2>&1
if not exist "%VENV_ROOT%" mkdir "%VENV_ROOT%" >nul 2>&1
> "%LOG%" echo [%date% %time%] CoDIR IA v17.0 - build v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65
>> "%LOG%" echo INSTALL_DIR=%INSTALL_DIR%
>> "%LOG%" echo VENV_PATH=%VENV_PATH%

if not exist "%PROBE_SCRIPT%" (
    echo [ERREUR] Sonde Python introuvable : %PROBE_SCRIPT%
    >> "%LOG%" echo [ERROR] python_runtime_probe.py absent
    pause
    exit /b 2
)

echo.
echo  ==========================================
echo   CoDIR IA v17.0 - Installation Windows
echo   Python standard supporte : 3.11 a 3.14
echo   Python recommande        : 3.11 ou 3.12
echo  ==========================================
echo.

REM --- [1/6] PYTHON -----------------------------------------------------------
echo  [1/6] Python...

REM 9.4.65 - cinquieme verification : Windows 10 sur ARM n emule pas les programmes x64 ;
REM CoDIR IA v17.0 y est arrete avec un message clair au lieu d echouer plus loin.
if /i not "%PROCESSOR_ARCHITECTURE%"=="ARM64" goto :ARCH_OK
set "WIN_BUILD="
for /f "usebackq delims=" %%B in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "[Environment]::OSVersion.Version.Build"`) do set "WIN_BUILD=%%B"
if not defined WIN_BUILD goto :ARCH_OK
if %WIN_BUILD% GEQ 22000 goto :ARCH_OK
echo.
echo  [ERREUR] Windows 10 sur PC ARM detecte : ce systeme n emule pas les programmes x64.
echo           CoDIR IA v17.0 necessite Windows 11 sur un PC ARM, ou un PC Intel/AMD.
>> "%LOG%" echo [ERROR] Windows 10 ARM build %WIN_BUILD% - x64 emulation unavailable
pause
exit /b 1
:ARCH_OK

:CHECK_PYTHON
set "FOUND_PY_SELECTOR="
set "FOUND_PY_EXE="
set "FOUND_VER="
set "SEEN_TOO_OLD="
set "SEEN_TOO_NEW="
set "SEEN_FREE_THREADED="
set "SEEN_NON_CPYTHON="

REM Versions standard explicites d'abord. Le launcher generique arrive en dernier.
REM 9.4.65 - essai natif du 20/10 : les etiquettes -V:3.x designent les Python x64 ; sous Windows ARM, la sonde
REM refuse le Python ARM64 natif, dont quatre dependances verrouillees n ont pas de version binaire.
set "SEEN_ARM64="
for %%C in ("py -V:3.12" "py -V:3.11" "py -V:3.13" "py -V:3.14" "py -3.12" "py -3.11" "py -3.13" "py -3.14" "python" "python3" "py") do (
    if not defined FOUND_PY_EXE call :TRY_CANDIDATE "%%~C"
)

if not defined FOUND_PY_EXE goto :INSTALL_PYTHON
goto :PYTHON_OK

:TRY_CANDIDATE
set "CAND=%~1"
set "TRY_STATUS="
set "TRY_VER="
set "TRY_EXE="
set "TRY_MSG="
set "PROBE_OUT=%TEMP%\codir_py_probe_!RANDOM!_!RANDOM!.txt"

!CAND! "%PROBE_SCRIPT%" > "!PROBE_OUT!" 2>&1
set "TRY_RC=!ERRORLEVEL!"
for /f "usebackq tokens=1,* delims==" %%A in ("!PROBE_OUT!") do (
    if /i "%%A"=="CODIR_PY_STATUS" set "TRY_STATUS=%%B"
    if /i "%%A"=="CODIR_PY_VERSION" set "TRY_VER=%%B"
    if /i "%%A"=="CODIR_PY_EXECUTABLE" set "TRY_EXE=%%B"
    if /i "%%A"=="CODIR_PY_MESSAGE" set "TRY_MSG=%%B"
)
>> "%LOG%" echo [python] candidate=!CAND! rc=!TRY_RC! status=!TRY_STATUS! version=!TRY_VER! exe=!TRY_EXE! message=!TRY_MSG!
del /q "!PROBE_OUT!" >nul 2>&1

if "!TRY_RC!"=="0" if defined TRY_EXE (
    set "FOUND_PY_SELECTOR=!CAND!"
    set "FOUND_PY_EXE=!TRY_EXE!"
    set "FOUND_VER=!TRY_VER!"
    exit /b 0
)

if /i "!TRY_STATUS!"=="FREE_THREADED" (
    set "SEEN_FREE_THREADED=1"
    echo    [INFO] !CAND! !TRY_VER! : variante free-threading/no-GIL refusee.
)
if /i "!TRY_STATUS!"=="TOO_OLD" (
    set "SEEN_TOO_OLD=1"
    echo    [INFO] !CAND! !TRY_VER! : version trop ancienne - minimum 3.11
)
if /i "!TRY_STATUS!"=="TOO_NEW" (
    set "SEEN_TOO_NEW=1"
    echo    [INFO] !CAND! !TRY_VER! : version trop recente - maximum valide 3.14
)
if /i "!TRY_STATUS!"=="NON_CPYTHON" set "SEEN_NON_CPYTHON=1"
if /i "!TRY_STATUS!"=="WINDOWS_32BIT" echo    [INFO] !CAND! !TRY_VER! : Python 32 bits refuse - un Python 64 bits est necessaire.
if /i "!TRY_STATUS!"=="WINDOWS_ARM64" (
    set "SEEN_ARM64=1"
    echo    [INFO] !CAND! !TRY_VER! : Python ARM64 natif refuse - un Python x64 est necessaire sous Windows ARM.
)
exit /b 0

:INSTALL_PYTHON
if defined PY312_INSTALL_TRIED goto :PYTHON_INSTALL_FAILED
set "PY312_INSTALL_TRIED=1"
echo.
echo    Aucun CPython standard compatible 3.11-3.14 n'a ete trouve.
if defined SEEN_FREE_THREADED echo    Une variante free-threading a ete detectee : elle ne peut pas etre utilisee.
if defined SEEN_TOO_OLD echo    Une version anterieure a Python 3.11 a ete detectee.
if defined SEEN_TOO_NEW echo    Une version posterieure a Python 3.14 a ete detectee.
if defined SEEN_NON_CPYTHON echo    Une implementation autre que CPython a ete detectee.
if defined SEEN_ARM64 echo    Seul un Python ARM64 natif a ete trouve : Python 3.12 x64 va etre installe, execute par l emulation de Windows.
echo    Installation automatique de Python 3.12 standard...
>> "%LOG%" echo [python] installation Python 3.12 standard

set "WINGET_ARCH="
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "WINGET_ARCH=--architecture x64"
where winget.exe >nul 2>&1
if not errorlevel 1 (
    winget install Python.Python.3.12 %WINGET_ARCH% --silent --accept-package-agreements --accept-source-agreements --scope user >> "%LOG%" 2>&1
    if errorlevel 1 winget upgrade Python.Python.3.12 %WINGET_ARCH% --silent --accept-package-agreements --accept-source-agreements --scope user >> "%LOG%" 2>&1
    call :REFRESH_USER_PATH
    goto :CHECK_PYTHON
)

REM 9.4.65 - sous Windows ARM aussi, la version x64 : les dependances verrouillees n existent pas toutes en ARM64.
set "PY_ARCH=amd64"
set "PY_URL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-!PY_ARCH!.exe"
set "PY_TMP=%TEMP%\codir_python_3_12_setup.exe"
echo    Telechargement depuis python.org...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_TMP%' -UseBasicParsing" >> "%LOG%" 2>&1
if not exist "%PY_TMP%" goto :PYTHON_INSTALL_FAILED
"%PY_TMP%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_pip=1 >> "%LOG%" 2>&1
set "PY_INSTALL_RC=!ERRORLEVEL!"
del /f /q "%PY_TMP%" >nul 2>&1
if not "!PY_INSTALL_RC!"=="0" goto :PYTHON_INSTALL_FAILED
call :REFRESH_USER_PATH
goto :CHECK_PYTHON

:REFRESH_USER_PATH
for /f "tokens=*" %%P in ('powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('PATH','User')"') do set "PATH=%%P;!PATH!"
exit /b 0

:PYTHON_INSTALL_FAILED
echo.
echo  [ERREUR] Impossible d'installer ou de selectionner Python 3.12 standard.
echo           Installez Python 3.12 standard depuis python.org, puis relancez.
>> "%LOG%" echo [ERROR] Python install/select failed
start "" "https://www.python.org/downloads/windows/"
pause
exit /b 1

:PYTHON_OK
echo    OK - Python !FOUND_VER! standard
echo    Interpreteur : !FOUND_PY_EXE!
echo    Selecteur    : !FOUND_PY_SELECTOR!
>> "%LOG%" echo [OK] Python !FOUND_VER! selector=!FOUND_PY_SELECTOR! exe=!FOUND_PY_EXE!

REM --- [2/6] VENV -------------------------------------------------------------
echo  [2/6] Environnement virtuel...
echo    Emplacement : %VENV_PATH%

if exist "%VPY%" (
    "%VPY%" "%PROBE_SCRIPT%" >nul 2>&1
    if errorlevel 1 (
        echo    Venv incompatible - reconstruction...
        rmdir /s /q "%VENV_PATH%" >> "%LOG%" 2>&1
    )
)

REM Py_GIL_DISABLED : contrat explicite attendu aussi sur le venv existant.
if exist "%VPY%" (
    "%VPY%" -c "import sys,sysconfig;sys.exit(1 if (sysconfig.get_config_var('Py_GIL_DISABLED') or 0) else 0)" >nul 2>&1
    if errorlevel 1 rmdir /s /q "%VENV_PATH%" >> "%LOG%" 2>&1
)

if exist "%VPY%" (
    for /f %%V in ('"%VPY%" -c "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')"') do set "VENV_MM=%%V"
    for /f %%V in ('"!FOUND_PY_EXE!" -c "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')"') do set "SELECTED_MM=%%V"
    if not "!VENV_MM!"=="!SELECTED_MM!" (
        echo    Version Python changee : !VENV_MM! vers !SELECTED_MM! - reconstruction...
        rmdir /s /q "%VENV_PATH%" >> "%LOG%" 2>&1
    )
)

if not exist "%VPY%" (
    "!FOUND_PY_EXE!" -m venv "%VENV_PATH%" >> "%LOG%" 2>&1
    if errorlevel 1 (
        echo  [ERREUR] Echec creation venv. Details : %LOG%
        pause
        exit /b 1
    )
    echo    OK - venv cree dans LOCALAPPDATA
) else (
    echo    OK - venv present
)

REM --- [3/6] DEPENDANCES ------------------------------------------------------
echo  [3/6] Dependances Python...
"%VPY%" -m pip install --upgrade pip setuptools wheel -q >> "%LOG%" 2>&1
if errorlevel 1 goto :DEPENDENCY_FAILED

REM 9.4.65 - contre-audit du 20/10 (R01) : un environnement de repli n'est jamais marque comme conforme au verrou
set "INSTALL_IS_FALLBACK="
if exist requirements.lock (
    >> "%LOG%" echo [install] requirements.lock
    "%VPY%" -m pip install --only-binary=:all: -r requirements.lock -q >> "%LOG%" 2>&1
    if errorlevel 1 (
        >> "%LOG%" echo [install] lock failed - fallback requirements.txt
        "%VPY%" -m pip install --only-binary=:all: --upgrade -r requirements.txt -q >> "%LOG%" 2>&1
        REM v62.13.9.4.33 - repli EXPLICITE : l environnement obtenu differe du lock et du SBOM
        REM 9.4.65 - essai natif Windows du 20/10 : aucune parenthese dans un echo a l interieur d un bloc, elle fermerait le bloc
        >> "%LOG%" echo [install] ATTENTION : environnement de REPLI, requirements.txt - il differe de requirements.lock et du SBOM ; a signaler au support avant usage professionnel
        > "%VENV_PATH%\INSTALL_MODE.txt" echo fallback requirements.txt
        set "INSTALL_IS_FALLBACK=1"
        echo   ATTENTION : dependances installees en mode REPLI, voir le journal - environnement non verrouille.
    ) else (
        > "%VENV_PATH%\INSTALL_MODE.txt" echo locked requirements.lock
    )
) else (
    "%VPY%" -m pip install --only-binary=:all: --upgrade -r requirements.txt -q >> "%LOG%" 2>&1
)
if errorlevel 1 goto :DEPENDENCY_FAILED

echo    OK - Dependances installees
REM 9.4.65 - verification du 19/10 (P02) : empreinte du verrou qui a construit cet environnement, relue par le lanceur
set "LOCK_FILE_SETUP=%INSTALL_DIR%requirements.lock"
set "LOCK_NOW_SETUP="
if exist "%LOCK_FILE_SETUP%" for /f "usebackq delims=" %%H in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "(Get-FileHash -LiteralPath $env:LOCK_FILE_SETUP -Algorithm SHA256).Hash"`) do set "LOCK_NOW_SETUP=%%H"
if defined LOCK_NOW_SETUP (
    if defined INSTALL_IS_FALLBACK (
        > "%VENV_PATH%\CODIR_LOCK_SHA256.txt" echo FALLBACK-%LOCK_NOW_SETUP%
        >> "%LOG%" echo [install] marqueur de REPLI enregistre : FALLBACK-%LOCK_NOW_SETUP%
    ) else (
        > "%VENV_PATH%\CODIR_LOCK_SHA256.txt" echo %LOCK_NOW_SETUP%
        >> "%LOG%" echo [install] empreinte du verrou enregistree : %LOCK_NOW_SETUP%
    )
)
> "%INSTALL_DIR%outputs\venv_path.txt" echo %VENV_PATH%
goto :DEPENDENCY_OK

:DEPENDENCY_FAILED
if not defined PY314_DEP_FALLBACK (
    echo !FOUND_VER! | findstr /b /c:"3.14." >nul
    if not errorlevel 1 (
        set "PY314_DEP_FALLBACK=1"
        set "PY312_INSTALL_TRIED="
                echo.
        echo  [ATTENTION] Un paquet binaire manque encore pour Python 3.14.
        echo              Repli automatique vers Python 3.12 standard...
        >> "%LOG%" echo [install] Python 3.14 wheels incomplete - fallback 3.12
        rmdir /s /q "%VENV_PATH%" >> "%LOG%" 2>&1
        goto :INSTALL_PYTHON
    )
)
echo.
echo  [ERREUR] Echec installation des dependances.
echo           Aucun build source n'est tente ; consultez : %LOG%
powershell -NoProfile -Command "Get-Content -Tail 25 '%LOG%'" 2>nul
pause
exit /b 1

:DEPENDENCY_OK
REM --- [4/6] RACCOURCI BUREAU -------------------------------------------------
echo  [4/6] Raccourci Bureau...
if exist "win\create_shortcut.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "win\create_shortcut.ps1" >> "%LOG%" 2>&1
    echo    OK - Raccourci cree sur le Bureau
) else (
    echo    Script raccourci absent - ignore
)

REM --- [5/6] AUTO-VERIFICATION (self-check unique Since v16.5.67) ------------
echo.
echo  ==========================================
echo   [5/6] v17.0 - Verification automatique
echo  ==========================================
echo.
"%VPY%" verify_installation.py
if errorlevel 1 (
    echo  [ATTENTION] La verification a detecte des problemes.
    echo  Streamlit demarrera, mais consultez la sortie ci-dessus.
) else (
    echo  [OK] Installation validee - CoDIR IA v17.0 build 9.4.65 operationnelle
)

REM --- [6/6] LANCEMENT --------------------------------------------------------
echo  [6/6] Lancement CoDIR IA...
echo.
echo  ==========================================
echo   Installation terminee !
echo   Navigateur : http://localhost:8501
echo   Ctrl+C pour arreter CoDIR IA
echo  ==========================================
echo.
echo  Cles API - Configuration
echo  Cles LLM requises   : OPENAI / ANTHROPIC / GOOGLE / MISTRAL / PERPLEXITY / GROK
echo  Chemin secrets.json : %%APPDATA%%\CoDIR-IA\secrets.json
echo  Cache Pappers       : %%LOCALAPPDATA%%\CoDIR-IA\pappers_cache.json
echo  Cles optionnelles   : PAPPERS_API_KEY, COMPANIES_HOUSE_API_KEY, OPENSANCTIONS_API_KEY, SEC_EDGAR_USER_AGENT
echo  Note                : Companies House utilise 1 cle principale par defaut; cle Document API distincte optionnelle (Since v16.5.70).
echo.

set "CODIR_PARSE_ENGINE=thread"
REM 9.4.65 - essai natif du 20/10 : un Quitter normal arrete Streamlit avec le code 1 ; le drapeau le signale.
set "QUIT_FLAG=%LOCALAPPDATA%\CoDIR-IA\logs\ARRET_DEMANDE.flag"
if exist "%QUIT_FLAG%" del "%QUIT_FLAG%" >nul 2>&1
"%VSTREAMLIT%" run "%INSTALL_DIR%app.py" --server.headless false --browser.gatherUsageStats false --server.port 8501 --logger.level error
set "STREAMLIT_RC=%ERRORLEVEL%"
if exist "%QUIT_FLAG%" goto :QUIT_REQUESTED
if "%STREAMLIT_RC%"=="0" (
    endlocal & exit /b 0
)
echo.
echo  [ERREUR] CoDIR IA s'est arrete avec le code %STREAMLIT_RC%.
echo           Journal installation : %LOG%
pause
endlocal & exit /b %STREAMLIT_RC%

:QUIT_REQUESTED
del "%QUIT_FLAG%" >nul 2>&1
>> "%LOG%" echo [run] arret demande par Quitter - code %STREAMLIT_RC% attendu
echo.
echo  CoDIR IA est arrete.
endlocal & exit /b 0
