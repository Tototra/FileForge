# FileForge - installation Windows (utilisateur courant, aucun droit administrateur requis)
#
#   install.ps1                 installation complète (fenêtre console)
#   install.ps1 -Step python    une seule étape (utilisé par FileForge-Setup.exe)
#
# Étapes : files, python, libs, ocr, webview, shell, libreoffice
param([string]$Step = "all", [switch]$Quiet)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try {
  if ($Quiet) {
    # l'installateur lit la sortie dans la page de code ANSI de Windows
    $acp = [Globalization.CultureInfo]::CurrentCulture.TextInfo.ANSICodePage
    [Console]::OutputEncoding = [Text.Encoding]::GetEncoding($acp)
  } else { [Console]::OutputEncoding = [Text.Encoding]::UTF8 }
} catch {}

$Self = $PSCommandPath
$Src  = Split-Path -Parent $Self
$Dest = Join-Path $env:LOCALAPPDATA "FileForge"
$Py   = Join-Path $Dest "venv\Scripts\python.exe"
$Pyw  = Join-Path $Dest "venv\Scripts\pythonw.exe"
$UvDir = Join-Path $Dest "uv"
$Uv   = Join-Path $UvDir "uv.exe"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Dest "python"
$env:UV_CACHE_DIR = Join-Path $Dest "cache"
$env:UV_NO_PROGRESS = "1"

function Say($t) { Write-Host "  $t" }
function Ok($t) { if ($Quiet) { Write-Host "  $t" } else { Write-Host "      $t" -ForegroundColor Green } }
function Title($n, $t) { if (-not $Quiet) { Write-Host ""; Write-Host "[$n] $t" -ForegroundColor Cyan } }

function Download($url, $out) {
  for ($i = 1; $i -le 3; $i++) {
    try { Invoke-WebRequest $url -OutFile $out -UseBasicParsing -TimeoutSec 300; return } catch {
      if ($i -eq 3) { throw }
      Start-Sleep -Seconds (2 * $i)
    }
  }
}

function Step-Files {
  # Ferme une éventuelle roue ouverte (mise à jour)
  Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*FileForge*wheel.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  New-Item -ItemType Directory -Force -Path $Dest | Out-Null
  if ((Resolve-Path $Src).Path.TrimEnd('\') -ne (Resolve-Path $Dest).Path.TrimEnd('\')) {
    Copy-Item -Path (Join-Path $Src "app\*") -Destination $Dest -Recurse -Force
    Copy-Item -Path (Join-Path $Src "uninstall.ps1") -Destination $Dest -Force
    Copy-Item -Path $Self -Destination $Dest -Force -ErrorAction SilentlyContinue
  }
  Get-ChildItem -Path $Dest -Recurse -File | Unblock-File -ErrorAction SilentlyContinue
  Ok "Fichiers installés dans $Dest"
}

function Get-Uv {
  if (Test-Path $Uv) { return }
  New-Item -ItemType Directory -Force -Path $UvDir | Out-Null
  $zip = Join-Path $env:TEMP "fileforge-uv.zip"
  try {
    Download "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" $zip
  } catch {
    # GitHub injoignable : même outil, publié sur PyPI
    Say "GitHub ne répond pas, téléchargement depuis PyPI..."
    $rel = Invoke-RestMethod "https://pypi.org/pypi/uv/json" -UseBasicParsing
    $whl = $rel.urls | Where-Object { $_.filename -like "*win_amd64.whl" } | Select-Object -First 1
    Download $whl.url $zip
  }
  $tmp = Join-Path $env:TEMP "fileforge-uv"
  Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
  Expand-Archive -Path $zip -DestinationPath $tmp -Force
  $found = Get-ChildItem -Path $tmp -Recurse -Filter "uv.exe" | Select-Object -First 1
  if (-not $found) { throw "uv.exe introuvable dans l'archive téléchargée." }
  Copy-Item $found.FullName $Uv -Force
  Remove-Item $zip, $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

function Step-Python {
  Get-Uv
  if (-not (Test-Path $Py)) {
    & $Uv venv (Join-Path $Dest "venv") --python 3.12 --python-preference only-managed --quiet
    if ($LASTEXITCODE -ne 0) { throw "Impossible de télécharger Python (vérifie ta connexion Internet)." }
  }
  Ok "Python prêt (privé à FileForge, n'interfère avec rien)"
}

function Step-Libs {
  Get-Uv
  $pkgs = @("pymupdf", "pymupdf4llm", "pdf2docx", "pillow", "pillow-heif", "openpyxl", "pandas", "xlrd", "odfpy",
            "mammoth", "markdown", "python-pptx", "pywebview", "pywin32", "imageio-ffmpeg", "rapidfuzz")
  for ($i = 1; $i -le 2; $i++) {
    & $Uv pip install --python $Py --quiet @pkgs
    if ($LASTEXITCODE -eq 0) { break }
    if ($i -eq 2) { throw "L'installation des bibliothèques a échoué (vérifie ta connexion Internet)." }
    Say "Nouvel essai..."
  }
  & $Py -c "import webview, pymupdf, PIL, imageio_ffmpeg, win32com.client; imageio_ffmpeg.get_ffmpeg_exe()"
  if ($LASTEXITCODE -ne 0) { throw "Les bibliothèques sont installées mais ne se chargent pas." }
  Remove-Item -Recurse -Force (Join-Path $Dest "cache") -ErrorAction SilentlyContinue
  Ok "Bibliothèques PDF, images, vidéo et interface installées"
}

function Step-Ocr {
  $Tess = Join-Path $Dest "tessdata"
  New-Item -ItemType Directory -Force -Path $Tess | Out-Null
  foreach ($l in "fra", "eng") {
    $f = Join-Path $Tess "$l.traineddata"
    if (Test-Path $f) { continue }
    try { Download "https://github.com/tesseract-ocr/tessdata_fast/raw/main/$l.traineddata" $f }
    catch {
      try { Download "https://cdn.jsdelivr.net/gh/tesseract-ocr/tessdata_fast@main/$l.traineddata" $f }
      catch { Say "Langue OCR '$l' non téléchargée (l'OCR sera indisponible pour cette langue)."; Remove-Item $f -ErrorAction SilentlyContinue }
    }
  }
  Ok "Langues OCR : français et anglais"
}

function Step-Webview {
  $wvKey = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
  $wv = @("HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$wvKey",
          "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$wvKey",
          "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$wvKey") | Where-Object { Test-Path $_ }
  if ($wv) { Ok "Moteur d'affichage WebView2 déjà présent"; return }
  Say "Installation du moteur d'affichage WebView2..."
  $wvi = Join-Path $env:TEMP "MicrosoftEdgeWebview2Setup.exe"
  Download "https://go.microsoft.com/fwlink/p/?LinkId=2124703" $wvi
  Start-Process $wvi -ArgumentList "/silent", "/install" -Wait
  Ok "WebView2 installé"
}

function Step-Shell {
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
  # clic droit dans le vide d'un dossier : ouvre la roue sur la sélection / zone de dépôt
  $k = $hk.CreateSubKey("Software\Classes\Directory\Background\shell\FileForge")
  $k.SetValue("", "FileForge..."); $k.SetValue("Icon", $ico); $k.Close()
  $c = $hk.CreateSubKey("Software\Classes\Directory\Background\shell\FileForge\command")
  $c.SetValue("", "`"$Pyw`" `"$Dest\wheel.py`""); $c.Close()

  $sh = New-Object -ComObject WScript.Shell
  function NewLnk($path, $hotkey, $extra = "") {
    $l = $sh.CreateShortcut($path)
    $l.TargetPath = $Pyw
    $l.Arguments = "`"$Dest\wheel.py`"$extra"
    $l.WorkingDirectory = $Dest
    $l.IconLocation = "$ico,0"
    $l.Description = "FileForge - convertir, compresser, éditer tes fichiers"
    if ($hotkey) { $l.Hotkey = $hotkey }
    $l.Save()
  }
  $Start = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
  NewLnk (Join-Path $Start "FileForge.lnk") "CTRL+ALT+F"
  # Ctrl+Alt+G : panneau de recherche de fichiers seul
  NewLnk (Join-Path $Start "FileForge - Rechercher un fichier.lnk") "CTRL+ALT+G" " --search"
  NewLnk (Join-Path $env:APPDATA "Microsoft\Windows\SendTo\FileForge.lnk") $null
  NewLnk (Join-Path ([Environment]::GetFolderPath("Desktop")) "FileForge.lnk") $null

  # Désinstallation visible dans Paramètres > Applications (sauf si l'installateur .exe s'en charge)
  if (-not (Test-Path (Join-Path $Dest "Uninstall.exe"))) {
    $u = $hk.CreateSubKey("Software\Microsoft\Windows\CurrentVersion\Uninstall\FileForge")
    $u.SetValue("DisplayName", "FileForge")
    $u.SetValue("Publisher", "FileForge")
    $u.SetValue("DisplayIcon", $ico)
    $u.SetValue("InstallLocation", $Dest)
    $u.SetValue("UninstallString", "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Dest\uninstall.ps1`"")
    $u.SetValue("NoModify", 1, [Microsoft.Win32.RegistryValueKind]::DWord)
    $u.SetValue("NoRepair", 1, [Microsoft.Win32.RegistryValueKind]::DWord)
    $u.Close()
  }
  Ok "Clic droit, Envoyer vers, Ctrl+Alt+F (roue), Ctrl+Alt+G (recherche) et icône sur le Bureau"
}

function Test-LibreOffice {
  foreach ($d in $env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramW6432) {
    if ($d -and (Test-Path (Join-Path $d "LibreOffice\program\soffice.exe"))) { return $true }
  }
  return $false
}

function Step-LibreOffice {
  if (Test-LibreOffice) { Ok "LibreOffice déjà installé"; return }
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Say "Installation automatique impossible (winget absent) : télécharge LibreOffice sur https://fr.libreoffice.org"
    return
  }
  Say "Téléchargement de LibreOffice (~350 Mo), Windows peut demander une autorisation..."
  winget install -e --id TheDocumentFoundation.LibreOffice --silent --accept-package-agreements --accept-source-agreements --disable-interactivity | Out-Null
  if (Test-LibreOffice) { Ok "LibreOffice installé" } else { Say "LibreOffice n'a pas pu être installé (tu pourras le faire plus tard)." }
}

$steps = [ordered]@{
  files = "Copie des fichiers"; python = "Python (privé à FileForge)"
  libs = "Bibliothèques (PDF, images, vidéo, interface) - quelques minutes la première fois"
  ocr = "Langues pour l'OCR"; webview = "Moteur d'affichage de la roue"; shell = "Intégration à l'Explorateur Windows"
}
$fn = @{ files = { Step-Files }; python = { Step-Python }; libs = { Step-Libs }; ocr = { Step-Ocr }
         webview = { Step-Webview }; shell = { Step-Shell }; libreoffice = { Step-LibreOffice } }

try {
  if ($Step -ne "all") {
    if (-not $fn.ContainsKey($Step)) { throw "Étape inconnue : $Step" }
    & $fn[$Step]
    exit 0
  }

  Write-Host ""
  Write-Host "  =================================" -ForegroundColor Magenta
  Write-Host "       Installation de FileForge" -ForegroundColor Magenta
  Write-Host "  =================================" -ForegroundColor Magenta
  $i = 0
  foreach ($k in $steps.Keys) { $i++; Title "$i/$($steps.Count)" $steps[$k]; & $fn[$k] }

  $office = Test-Path "Registry::HKEY_CLASSES_ROOT\PowerPoint.Application"
  if (-not $office -and -not (Test-LibreOffice) -and -not $Quiet) {
    Write-Host ""
    Write-Host "      LibreOffice (gratuit) permet de convertir PowerPoint et Excel en PDF sans Microsoft Office."
    $r = Read-Host "      L'installer maintenant ? (O/N)"
    if ($r -match '^(o|oui|y|yes)$') { Step-LibreOffice }
  }
  Write-Host ""
  Write-Host "  FileForge est installé !" -ForegroundColor Green
  Write-Host "  - Clic droit sur un fichier > FileForge...  (Windows 11 : Afficher d'autres options)"
  Write-Host "  - Ctrl + Alt + F dans l'Explorateur, ou l'icône FileForge du Bureau"
} catch {
  Write-Host ""
  Write-Host "  ERREUR : $($_.Exception.Message)" -ForegroundColor Red
  try { Add-Content -Path (Join-Path $Dest "FileForge.log") -Value "[install $Step] $($_ | Out-String)" -Encoding UTF8 } catch {}
  exit 1
}
