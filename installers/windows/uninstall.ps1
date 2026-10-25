# FileForge - désinstallation
#   -Quiet : appelé par Uninstall.exe (le dossier est supprimé par celui-ci)
param([switch]$Quiet)
$ErrorActionPreference = "SilentlyContinue"
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
$Dest = Join-Path $env:LOCALAPPDATA "FileForge"
if (-not $Quiet) { Write-Host "Désinstallation de FileForge..." -ForegroundColor Cyan }

# tout ce qui tourne depuis le dossier de FileForge (roue, agent Ctrl+Alt+G, LibreOffice privé…)
$all = Get-CimInstance Win32_Process
$ours = @($all | Where-Object { ($_.ExecutablePath -and $_.ExecutablePath -like "$Dest\*") -or
                 (($_.Name -eq "pythonw.exe" -or $_.Name -eq "python.exe") -and $_.CommandLine -like "*FileForge*") })
$ids = @($ours | ForEach-Object { $_.ProcessId })
# et le moteur d'affichage (Edge WebView2) lancé par la roue
$web = @($all | Where-Object { $_.Name -eq "msedgewebview2.exe" -and $ids -contains $_.ParentProcessId })
($ours + $web) | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Milliseconds 500

$hk = [Microsoft.Win32.Registry]::CurrentUser
$run = $hk.OpenSubKey("Software\Microsoft\Windows\CurrentVersion\Run", $true)
if ($run) { $run.DeleteValue("FileForge", $false); $run.Close() }
foreach ($k in "Software\Classes\*\shell\FileForge", "Software\Classes\Directory\shell\FileForge",
               "Software\Classes\Directory\Background\shell\FileForge", "Software\Classes\SystemFileAssociations\.pdf\shell\FileForgeEdit",
               "Software\Microsoft\Windows\CurrentVersion\Uninstall\FileForge") {
  $hk.DeleteSubKeyTree($k, $false)
}
Remove-Item (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\FileForge.lnk") -Force
Remove-Item (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\FileForge - Rechercher un fichier.lnk") -Force
Remove-Item (Join-Path $env:APPDATA "Microsoft\Windows\SendTo\FileForge.lnk") -Force
Remove-Item (Join-Path ([Environment]::GetFolderPath("Desktop")) "FileForge.lnk") -Force

if (-not $Quiet) {
  # Le dossier est supprimé après la fermeture de ce script (il contient ce script lui-même)
  Start-Process cmd.exe -ArgumentList "/c timeout /t 2 >nul & rmdir /s /q `"$Dest`"" -WindowStyle Hidden
  Write-Host "FileForge a été désinstallé. Tes fichiers personnels n'ont pas été touchés." -ForegroundColor Green
  Start-Sleep -Seconds 3
}
