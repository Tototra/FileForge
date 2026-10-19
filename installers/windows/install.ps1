# FileForge - installation Windows (utilisateur courant, aucun droit administrateur requis)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

$Src  = Split-Path -Parent $MyInvocation.MyCommand.Path
$Dest = Join-Path $env:LOCALAPPDATA "FileForge"
$Py   = Join-Path $Dest "venv\Scripts\python.exe"
$Pyw  = Join-Path $Dest "venv\Scripts\pythonw.exe"

function Step($n, $t) { Write-Host ""; Write-Host "[$n/7] $t" -ForegroundColor Cyan }
function Ok($t) { Write-Host "      $t" -ForegroundColor Green }
function Ask($q) { $r = Read-Host "      $q (O/N)"; return ($r -match '^(o|oui|y|yes)$') }

Write-Host ""
Write-Host "  =================================" -ForegroundColor Magenta
Write-Host "       Installation de FileForge" -ForegroundColor Magenta
Write-Host "  =================================" -ForegroundColor Magenta

# Ferme une éventuelle roue ouverte (cas d'une mise à jour)
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like "*FileForge*wheel.py*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# 1. Fichiers de l'application
Step 1 "Copie des fichiers"
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
Copy-Item -Path (Join-Path $Src "app\*") -Destination $Dest -Recurse -Force
Copy-Item -Path (Join-Path $Src "uninstall.ps1") -Destination $Dest -Force
Get-ChildItem -Path $Dest -Recurse -File | Unblock-File -ErrorAction SilentlyContinue
Ok "Installé dans $Dest"

# 2. Python privé (via uv : n'interfère avec aucun Python déjà installé)
Step 2 "Python (privé à FileForge)"
$UvDir = Join-Path $Dest "uv"
$Uv = Join-Path $UvDir "uv.exe"
if (-not (Test-Path $Uv)) {
  $zip = Join-Path $env:TEMP "fileforge-uv.zip"
  Invoke-WebRequest "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" -OutFile $zip -UseBasicParsing
  Expand-Archive -Path $zip -DestinationPath $UvDir -Force
  Remove-Item $zip -Force
  $found = Get-ChildItem -Path $UvDir -Recurse -Filter "uv.exe" | Select-Object -First 1
  if ($found -and $found.FullName -ne $Uv) { Copy-Item $found.FullName $Uv -Force }
}
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Dest "python"
$env:UV_CACHE_DIR = Join-Path $Dest "cache"
if (-not (Test-Path $Py)) {
  & $Uv venv (Join-Path $Dest "venv") --python 3.12 --python-preference only-managed --quiet
  if ($LASTEXITCODE -ne 0) { throw "Impossible de créer l'environnement Python." }
}
Ok "Python prêt"

# 3. Bibliothèques
Step 3 "Bibliothèques (PDF, images, vidéo, interface) - quelques minutes la première fois"
& $Uv pip install --python $Py --quiet `
  pymupdf pymupdf4llm pdf2docx pillow pillow-heif openpyxl pandas xlrd odfpy mammoth markdown python-pptx `
  pywebview pywin32 imageio-ffmpeg
if ($LASTEXITCODE -ne 0) { throw "L'installation des bibliothèques a échoué." }
Remove-Item -Recurse -Force (Join-Path $Dest "cache") -ErrorAction SilentlyContinue
Ok "Bibliothèques installées (ffmpeg inclus)"

# 4. Langues OCR (français + anglais)
Step 4 "Langues pour l'OCR"
$Tess = Join-Path $Dest "tessdata"
New-Item -ItemType Directory -Force -Path $Tess | Out-Null
foreach ($l in "fra", "eng") {
  $f = Join-Path $Tess "$l.traineddata"
  if (-not (Test-Path $f)) {
    Invoke-WebRequest "https://github.com/tesseract-ocr/tessdata_fast/raw/main/$l.traineddata" -OutFile $f -UseBasicParsing
  }
}
Ok "Français et anglais"

# 5. Moteur d'affichage de la roue (WebView2, déjà présent sur Windows 10/11 à jour)
Step 5 "Moteur d'affichage de la roue"
$wvKey = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
$wv = @("HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$wvKey",
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$wvKey",
        "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$wvKey") | Where-Object { Test-Path $_ }
if ($wv) { Ok "WebView2 présent" } else {
  Write-Host "      Installation de WebView2..."
  $wvi = Join-Path $env:TEMP "MicrosoftEdgeWebview2Setup.exe"
  Invoke-WebRequest "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile $wvi -UseBasicParsing
  Start-Process $wvi -ArgumentList "/silent", "/install" -Wait
  Ok "WebView2 installé"
}

# 6. Intégration à l'Explorateur
Step 6 "Intégration à l'Explorateur Windows"
$ico = Join-Path $Dest "icon.ico"
$cmd = "`"$Pyw`" `"$Dest\wheel.py`" `"%1`""
$hk = [Microsoft.Win32.Registry]::CurrentUser
foreach ($base in "Software\Classes\*\shell\FileForge", "Software\Classes\Directory\shell\FileForge") {
  $k = $hk.CreateSubKey($base)
  $k.SetValue("", "FileForge...")
  $k.SetValue("Icon", $ico)
  $k.SetValue("MultiSelectModel", "Player")
  $k.Close()
  $c = $hk.CreateSubKey("$base\command"); $c.SetValue("", $cmd); $c.Close()
}
$sh = New-Object -ComObject WScript.Shell
function NewLnk($path, $hotkey) {
  $l = $sh.CreateShortcut($path)
  $l.TargetPath = $Pyw
  $l.Arguments = "`"$Dest\wheel.py`""
  $l.WorkingDirectory = $Dest
  $l.IconLocation = "$ico,0"
  $l.Description = "FileForge - convertir, compresser, éditer tes fichiers"
  if ($hotkey) { $l.Hotkey = $hotkey }
  $l.Save()
}
$Start = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
NewLnk (Join-Path $Start "FileForge.lnk") "CTRL+ALT+F"
NewLnk (Join-Path $env:APPDATA "Microsoft\Windows\SendTo\FileForge.lnk") $null
NewLnk (Join-Path ([Environment]::GetFolderPath("Desktop")) "FileForge.lnk") $null
# Désinstallation visible dans Paramètres > Applications
$u = $hk.CreateSubKey("Software\Microsoft\Windows\CurrentVersion\Uninstall\FileForge")
$u.SetValue("DisplayName", "FileForge")
$u.SetValue("Publisher", "FileForge")
$u.SetValue("DisplayIcon", $ico)
$u.SetValue("InstallLocation", $Dest)
$u.SetValue("UninstallString", "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Dest\uninstall.ps1`"")
$u.SetValue("NoModify", 1, [Microsoft.Win32.RegistryValueKind]::DWord)
$u.SetValue("NoRepair", 1, [Microsoft.Win32.RegistryValueKind]::DWord)
$u.Close()
Ok "Clic droit, Envoyer vers, raccourci Ctrl+Alt+F et icône sur le Bureau"

# 7. Options
Step 7 "Options"
$lo = (Test-Path "C:\Program Files\LibreOffice\program\soffice.exe") -or (Test-Path "C:\Program Files (x86)\LibreOffice\program\soffice.exe")
$word = Test-Path "Registry::HKEY_CLASSES_ROOT\Word.Application"
if ($lo) { Ok "LibreOffice détecté" }
else {
  Write-Host "      LibreOffice (gratuit, ~350 Mo) permet de convertir PowerPoint et Excel en PDF."
  if ($word) { Write-Host "      Word est installé : Word vers PDF fonctionne déjà sans LibreOffice." }
  if (Ask "Installer LibreOffice maintenant ?") {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
      winget install -e --id TheDocumentFoundation.LibreOffice --silent --accept-package-agreements --accept-source-agreements
    } else {
      Write-Host "      winget indisponible : télécharge-le sur https://fr.libreoffice.org" -ForegroundColor Yellow
    }
  }
}

Write-Host ""
Write-Host "  FileForge est installé !" -ForegroundColor Green
Write-Host ""
Write-Host "  - Clic droit sur un fichier > FileForge..."
Write-Host "    (Windows 11 : clic droit > Afficher d'autres options, ou Maj + clic droit)"
Write-Host "  - Clic droit > Envoyer vers > FileForge (pour plusieurs fichiers d'un coup)"
Write-Host "  - Ctrl + Alt + F dans l'Explorateur : la roue s'ouvre sur la sélection"
Write-Host "  - Glisser des fichiers sur l'icône FileForge du Bureau"
Write-Host ""
