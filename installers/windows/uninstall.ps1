# FileForge - désinstallation
$ErrorActionPreference = "SilentlyContinue"
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
$Dest = Join-Path $env:LOCALAPPDATA "FileForge"
Write-Host "Désinstallation de FileForge..." -ForegroundColor Cyan

Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
  Where-Object { $_.CommandLine -like "*FileForge*wheel.py*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

$hk = [Microsoft.Win32.Registry]::CurrentUser
foreach ($k in "Software\Classes\*\shell\FileForge", "Software\Classes\Directory\shell\FileForge",
               "Software\Microsoft\Windows\CurrentVersion\Uninstall\FileForge") {
  $hk.DeleteSubKeyTree($k, $false)
}
Remove-Item (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\FileForge.lnk") -Force
Remove-Item (Join-Path $env:APPDATA "Microsoft\Windows\SendTo\FileForge.lnk") -Force
Remove-Item (Join-Path ([Environment]::GetFolderPath("Desktop")) "FileForge.lnk") -Force

# Le dossier est supprimé après la fermeture de ce script (il contient ce script lui-même)
Start-Process cmd.exe -ArgumentList "/c timeout /t 2 >nul & rmdir /s /q `"$Dest`"" -WindowStyle Hidden
Write-Host "FileForge a été désinstallé. Tes fichiers personnels n'ont pas été touchés." -ForegroundColor Green
Start-Sleep -Seconds 3
