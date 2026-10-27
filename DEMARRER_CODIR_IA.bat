@echo off
setlocal EnableExtensions
title CoDIR IA - Demarrage
set "CODIR_ROOT=%~dp0"
cd /d "%CODIR_ROOT%"

REM v62.13.9.2 - verifier le manifeste AVANT de retirer Mark-of-the-Web.
where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo [ERREUR] PowerShell est requis pour verifier l'integrite de la distribution.
  pause
  endlocal & exit /b 10
)
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; $root=($env:CODIR_ROOT).TrimEnd('\'); $m=Join-Path $root 'SHA256SUMS'; if(-not (Test-Path -LiteralPath $m)){throw 'SHA256SUMS absent'}; $bad=@(); Get-Content -LiteralPath $m | ForEach-Object { if($_ -match '^([0-9a-fA-F]{64})\s+(.+)$'){ $expected=$matches[1].ToLower(); $rel=$matches[2].Replace('/','\'); $f=Join-Path $root $rel; if(-not (Test-Path -LiteralPath $f)){ $bad += 'MANQUANT '+$rel } else { $actual=(Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash.ToLower(); if($actual -ne $expected){$bad += 'HASH '+$rel} } } }; if($bad.Count){$bad|ForEach-Object{Write-Host $_}; exit 11}; exit 0"
if errorlevel 1 (
  echo [ERREUR] Verification d'integrite echouee. Re-telechargez le ZIP officiel.
  pause
  endlocal & exit /b 11
)
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='SilentlyContinue'; Get-ChildItem -LiteralPath $env:CODIR_ROOT -Recurse -File | Unblock-File" >nul 2>&1

if "%APPDATA%"=="" set "APPDATA=%USERPROFILE%\AppData\Roaming"
if "%LOCALAPPDATA%"=="" set "LOCALAPPDATA=%TEMP%"
set "CODIR_CONFIG_DIR=%APPDATA%\CoDIR-IA"
set "CODIR_CACHE_DIR=%LOCALAPPDATA%\CoDIR-IA\cache"
set "CODIR_DATA_DIR=%APPDATA%\CoDIR-IA\data"
set "CODIR_INTEGRITY_VERIFIED=1"

call "%CODIR_ROOT%application\INSTALL_OR_LAUNCH.bat" %*
set "CODIR_RC=%ERRORLEVEL%"
endlocal & exit /b %CODIR_RC%
