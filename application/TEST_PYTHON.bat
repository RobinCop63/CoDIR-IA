@echo off
setlocal EnableExtensions EnableDelayedExpansion
title CoDIR IA - Diagnostic Python
cd /d "%~dp0"
set "LOG=%~dp0TEST_PYTHON_result.txt"
set "PROBE=%~dp0scripts\python_runtime_probe.py"
echo === TEST_PYTHON.bat - %date% %time% === > "%LOG%"
echo.
echo ============================================================
echo   Diagnostic Python CoDIR IA
echo   Compatible : CPython standard 3.11 a 3.14
echo   Recommande : 3.11 ou 3.12
echo ============================================================
echo.

if not exist "%PROBE%" (
    echo [ERREUR] Sonde absente : %PROBE%
    pause
    exit /b 2
)

for %%C in ("py -V:3.12" "py -V:3.11" "py -V:3.13" "py -V:3.14" "py -3.12" "py -3.11" "py -3.13" "py -3.14" "python" "python3" "py") do call :TEST_ONE %%C

echo.>> "%LOG%"
echo --- py -0p / py list --- >> "%LOG%"
py -0p >> "%LOG%" 2>&1
py list >> "%LOG%" 2>&1

echo.
echo Resultat detaille : %LOG%
echo Une variante free-threading est signalee explicitement et n'est pas compatible.
pause
exit /b 0

:TEST_ONE
set "CAND=%~1"
echo Test : !CAND!
echo --- !CAND! --- >> "%LOG%"
!CAND! "%PROBE%" >> "%LOG%" 2>&1
set "RC=!ERRORLEVEL!"
echo returncode=!RC! >> "%LOG%"
if "!RC!"=="0" echo   [OK] compatible
if "!RC!"=="10" echo   [NON] trop ancien
if "!RC!"=="11" echo   [NON] trop recent - maximum valide 3.14
if "!RC!"=="12" echo   [NON] variante free-threading/no-GIL
if "!RC!"=="13" echo   [NON] implementation autre que CPython
if "!RC!"=="14" echo   [NON] Python ARM64 natif - un Python x64 est necessaire sous Windows ARM
if "!RC!"=="17" echo   [NON] Python 32 bits - un Python 64 bits est necessaire
if !RC! GTR 17 echo   [ABSENT ou non executable]
echo.>> "%LOG%"
exit /b 0
