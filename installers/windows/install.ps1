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
    Where-Object { $_.CommandLine -like "*FileForge*wheel.py*" -or $_.CommandLine -like "*FileForge*hotkey_win.py*" } |
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
  # Recherche de fichiers : entrée du menu Démarrer (sans raccourci clavier : Ctrl+Alt+G est géré par l'agent)
  NewLnk (Join-Path $Start "FileForge - Rechercher un fichier.lnk") $null " --search"
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
  # Ctrl+Alt+G : petit agent sans fenêtre, lancé à l'ouverture de session (plus rapide et fiable qu'un raccourci du menu Démarrer)
  $run = $hk.CreateSubKey("Software\Microsoft\Windows\CurrentVersion\Run")
  $run.SetValue("FileForge", "`"$Pyw`" `"$Dest\hotkey_win.py`""); $run.Close()
  Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*FileForge*hotkey_win.py*" -or $_.CommandLine -like "*FileForge*--standby*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Process -FilePath $Pyw -ArgumentList "`"$Dest\hotkey_win.py`"" -WorkingDirectory $Dest
  Ok "Clic droit, Envoyer vers, Ctrl+Alt+F (roue), Ctrl+Alt+G (recherche) et icône sur le Bureau"
}

$LoDir = Join-Path $Dest "libreoffice"   # LibreOffice privé à FileForge (sans installation système)

function Test-LibreOffice {
  foreach ($d in $env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramW6432) {
    if ($d -and (Test-Path (Join-Path $d "LibreOffice\program\soffice.exe"))) { return $true }
  }
  return [bool](Get-ChildItem $LoDir -Recurse -Filter "soffice.com" -ErrorAction SilentlyContinue | Select-Object -First 1)
}

function Test-MsOffice {
  # Word, PowerPoint et Excel tous présents : FileForge convertit avec eux, LibreOffice est inutile
  foreach ($app in "Word", "PowerPoint", "Excel") {
    if (-not (Test-Path "Registry::HKEY_CLASSES_ROOT\$app.Application\CLSID")) { return $false }
  }
  return $true
}

function Step-LibreOffice {
  if (Test-MsOffice) { Ok "Microsoft Office détecté : utilisé pour convertir Word, PowerPoint et Excel"; return }
  if (Test-LibreOffice) { Ok "LibreOffice déjà présent"; return }
  # Pas d'Office complet : FileForge récupère LibreOffice lui-même et le déballe dans son dossier.
  # « msiexec /a » extrait les fichiers sans rien installer dans Windows : aucune autorisation administrateur.
  $base = "https://download.documentfoundation.org/libreoffice/stable/"
  $vers = (Invoke-WebRequest $base -UseBasicParsing).Links.href | Where-Object { $_ -match '^\d+(\.\d+)+/$' } |
          ForEach-Object { $_.TrimEnd('/') } | Sort-Object { [version]$_ }
  $v = $vers[-1]
  $msi = Join-Path $env:TEMP "fileforge-libreoffice-$v.msi"
  Say "Téléchargement de LibreOffice $v (~350 Mo) pour convertir Word, PowerPoint et Excel..."
  if (-not (Test-Path $msi) -or (Get-Item $msi).Length -lt 100MB) {
    Download "$base$v/win/x86_64/LibreOffice_${v}_Win_x86-64.msi" $msi
  }
  Say "Préparation de LibreOffice..."
  Remove-Item $LoDir -Recurse -Force -ErrorAction SilentlyContinue
  $p = Start-Process msiexec.exe -ArgumentList "/a `"$msi`" /qn TARGETDIR=`"$LoDir`"" -Wait -PassThru
  Remove-Item $msi -Force -ErrorAction SilentlyContinue
  Get-ChildItem $LoDir -Filter "*.msi" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
  $so = Get-ChildItem $LoDir -Recurse -Filter "soffice.com" -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $so) { throw "LibreOffice n'a pas pu être préparé (code $($p.ExitCode))." }
  # vérifie qu'il démarre vraiment (bibliothèques Windows nécessaires présentes)
  $t = Join-Path $env:TEMP "ff-lo-test"; Remove-Item $t -Recurse -Force -ErrorAction SilentlyContinue
  New-Item -ItemType Directory -Force -Path $t | Out-Null
  Set-Content -Path "$t\test.txt" -Value "FileForge" -Encoding UTF8
  $prof = ([Uri](Join-Path $t "profil")).AbsoluteUri
  & $so.FullName "-env:UserInstallation=$prof" --headless --norestore --convert-to pdf --outdir $t "$t\test.txt" | Out-Null
  $ok = Test-Path "$t\test.pdf"
  Remove-Item $t -Recurse -Force -ErrorAction SilentlyContinue
  if ($ok) { Ok "LibreOffice $v prêt (privé à FileForge)" }
  else { Say "LibreOffice est installé mais ne démarre pas : FileForge fera des conversions simplifiées." }
}

$steps = [ordered]@{
  files = "Copie des fichiers"; python = "Python (privé à FileForge)"
  libs = "Bibliothèques (PDF, images, vidéo, interface) - quelques minutes la première fois"
  ocr = "Langues pour l'OCR"; webview = "Moteur d'affichage de la roue"; shell = "Intégration à l'Explorateur Windows"
  libreoffice = "Conversions Office (Microsoft Office s'il est installé, sinon LibreOffice)"
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
