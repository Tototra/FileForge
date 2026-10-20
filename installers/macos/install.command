#!/bin/bash
# FileForge — installation macOS (utilisateur courant, aucun mot de passe administrateur)
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/Library/Application Support/FileForge"
APPDIR="$HOME/Applications"
SERVICES="$HOME/Library/Services"

c() { printf '\033[%sm%s\033[0m\n' "$1" "$2"; }
step() { echo; c "1;36" "[$1/6] $2"; }
ok() { c "32" "      $1"; }
warn() { c "33" "      $1"; }
ask() { local r; read -r -p "      $1 [O/n] " r || true; [[ -z "$r" || "$r" =~ ^[oOyY] ]]; }

clear 2>/dev/null || true
c "1;35" "  ================================="
c "1;35" "        Installation de FileForge"
c "1;35" "  ================================="

# Le dossier téléchargé est marqué « provenant d'Internet » : on lève ce marquage pour nos propres fichiers.
xattr -dr com.apple.quarantine "$SRC" 2>/dev/null || true
pkill -f "$DEST/wheel.py" 2>/dev/null || true

# 1. Fichiers
step 1 "Copie des fichiers"
mkdir -p "$DEST" "$APPDIR" "$SERVICES"
cp -R "$SRC/app/." "$DEST/"
cp "$SRC/uninstall.command" "$DEST/"
ok "Installé dans ~/Library/Application Support/FileForge"

# 2. Python privé (uv) — n'interfère avec aucun Python existant
step 2 "Python (privé à FileForge)"
if [[ -x "$DEST/venv/bin/python" ]] && "$DEST/venv/bin/python" -c "import sys; assert sys.version_info >= (3, 10)" 2>/dev/null; then
  ok "Environnement existant conservé"
else
  ARCH="$(uname -m)"; [[ "$ARCH" == "arm64" ]] && UVA="aarch64" || UVA="x86_64"
  UVD="$DEST/uv"; mkdir -p "$UVD"
  if [[ ! -x "$UVD/uv" ]]; then
    curl -fsSL "https://github.com/astral-sh/uv/releases/latest/download/uv-$UVA-apple-darwin.tar.gz" | tar xz -C "$UVD" --strip-components 1
  fi
  export UV_PYTHON_INSTALL_DIR="$DEST/python" UV_CACHE_DIR="$DEST/cache"
  rm -rf "$DEST/venv"
  "$UVD/uv" venv "$DEST/venv" --python 3.12 --python-preference only-managed --quiet
  ok "Python prêt"
fi

# 3. Bibliothèques
step 3 "Bibliothèques (PDF, images, vidéo, interface) — quelques minutes la première fois"
PIP=("$DEST/venv/bin/python" -m pip install -q)
if [[ -x "$DEST/uv/uv" ]]; then
  export UV_CACHE_DIR="$DEST/cache"
  PIP=("$DEST/uv/uv" pip install --python "$DEST/venv/bin/python" --quiet)
fi
"${PIP[@]}" pymupdf pymupdf4llm pdf2docx pillow pillow-heif openpyxl pandas xlrd odfpy mammoth markdown \
  python-pptx pywebview imageio-ffmpeg rapidfuzz
rm -rf "$DEST/cache"
"$DEST/venv/bin/python" -c "import webview, pymupdf, tkinter, imageio_ffmpeg; imageio_ffmpeg.get_ffmpeg_exe()" \
  || { warn "La vérification des bibliothèques a échoué."; exit 1; }
ok "Bibliothèques installées (ffmpeg inclus)"

# 4. Langues OCR
step 4 "Langues pour l'OCR (français, anglais)"
mkdir -p "$DEST/tessdata"
for l in fra eng; do
  [[ -s "$DEST/tessdata/$l.traineddata" ]] || \
    curl -fsSL -o "$DEST/tessdata/$l.traineddata" "https://github.com/tesseract-ocr/tessdata_fast/raw/main/$l.traineddata"
done
ok "Prêtes"

# 5. Intégration au Finder
step 5 "Intégration au Finder"
cat > "$DEST/run.sh" <<'EOF'
#!/bin/zsh
# Lanceur FileForge (Action rapide du Finder, raccourci ⌃⌥F, FileForge.app)
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export LANG="fr_FR.UTF-8"
DIR="$HOME/Library/Application Support/FileForge"
mkdir -p "$HOME/Library/Logs"
"$DIR/venv/bin/python" "$DIR/wheel.py" "$@" >> "$HOME/Library/Logs/FileForge.log" 2>&1
exit 0
EOF
chmod +x "$DEST/run.sh"
# Action rapide (clic droit → Actions rapides → FileForge…)
WF="$SERVICES/FileForge.workflow/Contents"
rm -rf "$SERVICES/FileForge.workflow"; mkdir -p "$WF"
cp "$SRC/support/workflow-Info.plist" "$WF/Info.plist"
cp "$SRC/support/workflow-document.wflow" "$WF/document.wflow"
# Application (glisser-déposer, Dock, barre d'outils du Finder)
APP="$APPDIR/FileForge.app"
rm -rf "$APP"
osacompile -o "$APP" "$SRC/support/droplet.applescript"
cp "$SRC/support/FileForge.icns" "$APP/Contents/Resources/droplet.icns"
rm -f "$APP/Contents/Resources/Assets.car"
/usr/libexec/PlistBuddy -c "Set :CFBundleIconFile droplet" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" "$APP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string io.github.tototra.fileforge" "$APP/Contents/Info.plist" 2>/dev/null || true
touch "$APP"; codesign --force -s - "$APP" >/dev/null 2>&1 || true
# Raccourci ⌃⌥F pour l'Action rapide
"$DEST/venv/bin/python" - <<'EOF'
import plistlib, subprocess
raw = subprocess.run(["defaults", "export", "pbs", "-"], capture_output=True).stdout
d = plistlib.loads(raw) if raw else {}
d.setdefault("NSServicesStatus", {})["(null) - FileForge… - runWorkflowAsService"] = {
    "key_equivalent": "^~f", "enabled_context_menu": True, "enabled_services_menu": True,
    "presentation_modes": {"ContextMenu": True, "ServicesMenu": True, "TouchBar": True}}
subprocess.run(["defaults", "import", "pbs", "-"], input=plistlib.dumps(d), check=True)
EOF
/System/Library/CoreServices/pbs -flush >/dev/null 2>&1 || true
/System/Library/CoreServices/pbs -update >/dev/null 2>&1 || true
ok "Clic droit (Actions rapides), raccourci ⌃⌥F et FileForge.app dans ~/Applications"

# 6. Options
step 6 "Options"
if [[ -d "/Applications/LibreOffice.app" ]]; then ok "LibreOffice détecté"
else
  echo "      LibreOffice (gratuit) permet Word / PowerPoint / Excel → PDF fidèles."
  if command -v brew >/dev/null; then
    ask "L'installer avec Homebrew ?" && brew install --cask libreoffice || true
  else
    echo "      Sans lui, Word → PDF utilise une conversion simplifiée. Téléchargement : https://fr.libreoffice.org"
  fi
fi

echo
c "1;32" "  FileForge est installé !"
echo
echo "  - Dans le Finder : sélectionne des fichiers puis ⌃⌥F (Ctrl + Option + F)"
echo "  - ou clic droit → Actions rapides → FileForge…"
echo "  - ou glisse des fichiers sur FileForge.app (dans ton dossier Applications)"
echo
echo "  Si le clic droit n'affiche pas FileForge : Réglages Système → Général →"
echo "  Éléments de connexion et extensions → Finder → coche « FileForge… »."
echo
[[ -n "${FILEFORGE_TEST:-}" ]] || open -R "$APP" 2>/dev/null || true
