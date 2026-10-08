# PLATINE - Desinstallateur
Write-Host ""
Write-Host "  Desinstallation de PLATINE..." -ForegroundColor Yellow
Write-Host ""

Stop-Process -Name "PLATINE" -ErrorAction SilentlyContinue
Stop-Process -Name "PLATINE-Bridge" -ErrorAction SilentlyContinue

Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\PLATINE.lnk" -ErrorAction SilentlyContinue
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\PLATINE-Bridge.lnk" -ErrorAction SilentlyContinue
Remove-Item "$([Environment]::GetFolderPath('Desktop'))\PLATINE.lnk" -ErrorAction SilentlyContinue

Remove-Item "$env:USERPROFILE\PLATINE" -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "  PLATINE a ete desinstalle." -ForegroundColor Green
Write-Host ""
Read-Host "  Entree pour fermer"