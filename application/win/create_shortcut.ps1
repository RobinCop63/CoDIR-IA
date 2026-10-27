$ErrorActionPreference = 'Continue'

# Auto-detection du dossier d'installation depuis l'emplacement du script
$root = Split-Path -Parent $PSScriptRoot

# Lire le chemin venv depuis outputs\venv_path.txt si disponible
$venvFile = Join-Path $root 'outputs\venv_path.txt'
if (Test-Path $venvFile) {
    $venvPath = (Get-Content $venvFile -Raw).Trim()
} else {
    $venvPath = Join-Path $env:LOCALAPPDATA 'CoDIR-IA\.venv'
}

$desktop  = [Environment]::GetFolderPath('Desktop')
$lnk      = Join-Path $desktop 'CoDIR IA.lnk'
$icon     = Join-Path $root 'assets\CoDIR_IA.ico'
$vbs      = Join-Path $root 'win\launch_hidden.vbs'
$wscript  = Join-Path $env:WINDIR 'System32\wscript.exe'

Write-Host "[INFO] root      = $root"
Write-Host "[INFO] venvPath  = $venvPath"
Write-Host "[INFO] icon      = $icon"
Write-Host "[INFO] lnk       = $lnk"

$wsh = New-Object -ComObject WScript.Shell
$sc  = $wsh.CreateShortcut($lnk)
# 9.4.65 - contre-audit du 20/10 (R02 bis) : le raccourci passe par la facade racine DEMARRER_CODIR_IA.bat,
# qui verifie SHA256SUMS puis l'empreinte du verrou ; repli sur le lancement masque seulement si elle est absente.
$rootDir = Split-Path -Parent $root
$facade  = Join-Path $rootDir 'DEMARRER_CODIR_IA.bat'
if (Test-Path $facade) {
    $sc.TargetPath       = $facade
    $sc.Arguments        = ''
    $sc.WorkingDirectory = $rootDir
    Write-Host "[INFO] cible     = $facade"
} else {
    $sc.TargetPath       = $wscript
    $sc.Arguments        = "`"$vbs`""
    $sc.WorkingDirectory = $root
    Write-Host "[WARN] facade racine absente : lancement masque"
}
if (Test-Path $icon) {
    $sc.IconLocation = "$icon,0"
    Write-Host "[INFO] Icone trouvee : $icon"
} else {
    Write-Host "[WARN] Icone introuvable : $icon"
}
$sc.Save()
Write-Host "[OK] Raccourci cree : $lnk"
