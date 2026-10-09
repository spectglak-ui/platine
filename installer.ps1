# =======================================================
#  PLATINE - Installeur double mode (dev / release)
#  Mode dev     : compile depuis C:\platine + C:\platine-bridge
#  Mode release : installe les .exe presents a cote du script
#  Usage : powershell -ExecutionPolicy Bypass -File installer.ps1
# =======================================================

param(
    [string]$WidgetSrc  = "C:\platine",
    [string]$BridgeSrc  = "C:\platine-bridge",
    [string]$InstallDir = "$env:USERPROFILE\PLATINE",
    [string]$ReleaseDir = "C:\platine-release"
)

Write-Host ""
Write-Host "  +===================================+" -ForegroundColor Cyan
Write-Host "  |    PLATINE - Installeur           |" -ForegroundColor Cyan
Write-Host "  +===================================+" -ForegroundColor Cyan
Write-Host ""

# Arreter les anciens processus
Stop-Process -Name "PLATINE" -Force -ErrorAction SilentlyContinue
Stop-Process -Name "PLATINE-Bridge" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# -- Detection du mode ------------------------------------
$widgetExe  = $null
$bridgeExe  = $null

if (Test-Path "$PSScriptRoot\PLATINE.exe")        { $widgetExe = "$PSScriptRoot\PLATINE.exe" }
if (Test-Path "$PSScriptRoot\PLATINE-Bridge.exe") { $bridgeExe = "$PSScriptRoot\PLATINE-Bridge.exe" }

$modeRelease = ($null -ne $widgetExe) -and ($null -ne $bridgeExe)

if ($modeRelease) {
    Write-Host "  Mode : RELEASE (exe precompiles detectes)" -ForegroundColor Magenta
} else {
    Write-Host "  Mode : DEV (compilation depuis les sources)" -ForegroundColor Magenta
}
Write-Host ""

# -- 1. Dossier d'installation ---------------------------
Write-Host "  [1/6] Dossier d'installation..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

if (-not $modeRelease) {
    # ---- Compilation widget ----
    if (-not (Test-Path "$WidgetSrc\main.js")) {
        Write-Host "  ERREUR : sources widget introuvables ($WidgetSrc)" -ForegroundColor Red
        Read-Host "  Entree pour quitter"; exit 1
    }
    Write-Host "  [2/6] Compilation du widget (2-3 min)..." -ForegroundColor Yellow
    Push-Location $WidgetSrc
    npm run build 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERREUR : compilation widget echouee" -ForegroundColor Red
        Pop-Location; Read-Host "  Entree pour quitter"; exit 1
    }
    $found = Get-ChildItem "$WidgetSrc\dist\*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $found) {
        Write-Host "  ERREUR : aucun exe produit" -ForegroundColor Red
        Pop-Location; Read-Host "  Entree pour quitter"; exit 1
    }
    $widgetExe = $found.FullName
    Write-Host "        -> $($found.Name)" -ForegroundColor Green
    Pop-Location

    # ---- Compilation bridge ----
    if (-not (Test-Path "$BridgeSrc\bridge.py")) {
        Write-Host "  ERREUR : sources bridge introuvables ($BridgeSrc)" -ForegroundColor Red
        Read-Host "  Entree pour quitter"; exit 1
    }
    Write-Host "  [3/6] Compilation du bridge..." -ForegroundColor Yellow
    Push-Location $BridgeSrc
    python -m PyInstaller --onefile --noconsole --name PLATINE-Bridge bridge.py 2>&1 | Out-Null
    if (-not (Test-Path "$BridgeSrc\dist\PLATINE-Bridge.exe")) {
        Write-Host "  ERREUR : compilation bridge echouee" -ForegroundColor Red
        Write-Host "  Verifiez : python -m pip install pyinstaller" -ForegroundColor Yellow
        Pop-Location; Read-Host "  Entree pour quitter"; exit 1
    }
    $bridgeExe = "$BridgeSrc\dist\PLATINE-Bridge.exe"
    Write-Host "        -> PLATINE-Bridge.exe" -ForegroundColor Green
    Pop-Location
} else {
    Write-Host "  [2/6] Widget : exe release utilise" -ForegroundColor Yellow
    Write-Host "  [3/6] Bridge : exe release utilise" -ForegroundColor Yellow
}

# -- 4. Copie vers le dossier d'installation -------------
Write-Host "  [4/6] Installation des fichiers..." -ForegroundColor Yellow
Copy-Item $widgetExe  "$InstallDir\PLATINE.exe" -Force
Copy-Item $bridgeExe  "$InstallDir\PLATINE-Bridge.exe" -Force
Write-Host "        -> $InstallDir" -ForegroundColor Green

# Script de desinstallation
$uninstallPs1 = @'
Stop-Process -Name "PLATINE" -Force -ErrorAction SilentlyContinue
Stop-Process -Name "PLATINE-Bridge" -Force -ErrorAction SilentlyContinue
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\PLATINE.lnk" -ErrorAction SilentlyContinue
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\PLATINE-Bridge.lnk" -ErrorAction SilentlyContinue
Remove-Item "$([Environment]::GetFolderPath('Desktop'))\PLATINE.lnk" -ErrorAction SilentlyContinue
Remove-Item "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PLATINE" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "$env:USERPROFILE\PLATINE" -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "PLATINE desinstalle." -ForegroundColor Green
Read-Host "Entree pour fermer"
'@
$uninstallPs1 | Out-File -FilePath "$InstallDir\uninstall.ps1" -Encoding UTF8
@'
@echo off
powershell -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
'@ | Out-File -FilePath "$InstallDir\uninstall.bat" -Encoding ASCII

# -- 5. Registre + raccourcis ----------------------------
Write-Host "  [5/6] Registre Windows + raccourcis..." -ForegroundColor Yellow
$regPath = "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PLATINE"
New-Item -Path $regPath -Force | Out-Null
Set-ItemProperty -Path $regPath -Name "DisplayName"     -Value "PLATINE"
Set-ItemProperty -Path $regPath -Name "DisplayVersion"  -Value "1.0.0"
Set-ItemProperty -Path $regPath -Name "Publisher"       -Value "PLATINE"
Set-ItemProperty -Path $regPath -Name "InstallLocation" -Value $InstallDir
Set-ItemProperty -Path $regPath -Name "DisplayIcon"     -Value "$InstallDir\PLATINE.exe"
Set-ItemProperty -Path $regPath -Name "UninstallString" -Value "$InstallDir\uninstall.bat"

$WshShell   = New-Object -ComObject WScript.Shell
$startupDir = [Environment]::GetFolderPath("Startup")
$desktopDir = [Environment]::GetFolderPath("Desktop")

$s1 = $WshShell.CreateShortcut("$startupDir\PLATINE-Bridge.lnk")
$s1.TargetPath = "$InstallDir\PLATINE-Bridge.exe"; $s1.WorkingDirectory = $InstallDir; $s1.Save()
$s2 = $WshShell.CreateShortcut("$startupDir\PLATINE.lnk")
$s2.TargetPath = "$InstallDir\PLATINE.exe"; $s2.WorkingDirectory = $InstallDir; $s2.Save()
$s3 = $WshShell.CreateShortcut("$desktopDir\PLATINE.lnk")
$s3.TargetPath = "$InstallDir\PLATINE.exe"; $s3.WorkingDirectory = $InstallDir; $s3.Save()
Write-Host "        -> Demarrage auto + bureau + registre OK" -ForegroundColor Green

# -- 6. Creation du dossier RELEASE (mode dev seulement) -
if (-not $modeRelease) {
    Write-Host "  [6/6] Creation du dossier release..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
    Copy-Item $widgetExe "$ReleaseDir\PLATINE.exe" -Force
    Copy-Item $bridgeExe "$ReleaseDir\PLATINE-Bridge.exe" -Force
    Copy-Item $PSCommandPath "$ReleaseDir\installer.ps1" -Force
    Write-Host "        -> $ReleaseDir (pret a zipper / distribuer)" -ForegroundColor Green
} else {
    Write-Host "  [6/6] Release : rien a compiler" -ForegroundColor Yellow
}

# -- Resume ----------------------------------------------
Write-Host ""
Write-Host "  +===================================+" -ForegroundColor Green
Write-Host "  |    Installation terminee !         |" -ForegroundColor Green
Write-Host "  +===================================+" -ForegroundColor Green
Write-Host ""
Write-Host "  Dossier   : $InstallDir" -ForegroundColor White
Write-Host "  Desinstall: Parametres > Applications > PLATINE" -ForegroundColor Gray
Write-Host ""
Write-Host "  Raccourcis:" -ForegroundColor White
Write-Host "    Alt+V       widget au-dessus / retour bureau" -ForegroundColor Gray
Write-Host "    Ctrl+Alt+M  masquer / afficher" -ForegroundColor Gray
Write-Host ""

$launch = Read-Host "  Lancer PLATINE maintenant ? (o/n)"
if ($launch -eq "o" -or $launch -eq "O" -or $launch -eq "") {
    Start-Process "$InstallDir\PLATINE-Bridge.exe" -WorkingDirectory $InstallDir
    Start-Sleep -Seconds 2
    Start-Process "$InstallDir\PLATINE.exe" -WorkingDirectory $InstallDir
    Write-Host "  PLATINE lance !" -ForegroundColor Green
}
Write-Host ""
Read-Host "  Entree pour fermer"