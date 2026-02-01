param(
  [string]$ShortcutName = "CoDIR IA.lnk",
  [string]$DestinationFolder = [Environment]::GetFolderPath("Desktop")
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$targetBat = Join-Path $repoRoot "launch_codir.bat"
$iconIco  = Join-Path $repoRoot "assets\CoDIR_IA.ico"

if (!(Test-Path $targetBat)) { throw "launch_codir.bat introuvable: $targetBat" }

$shortcutPath = Join-Path $DestinationFolder $ShortcutName

$wsh = New-Object -ComObject WScript.Shell
$sc = $wsh.CreateShortcut($shortcutPath)
$sc.TargetPath = $targetBat
$sc.WorkingDirectory = $repoRoot
if (Test-Path $iconIco) { $sc.IconLocation = $iconIco }
$sc.Save()

Write-Host "✅ Raccourci créé : $shortcutPath"
Write-Host "   Cible         : $targetBat"
Write-Host "   Dossier       : $repoRoot"
if (Test-Path $iconIco) { Write-Host "   Icône         : $iconIco" } else { Write-Host "   Icône         : (non trouvée)" }
