#!/usr/bin/env bash
# FileForge — installation Linux (pensée pour Arch + Hyprland, fonctionne sur d'autres bureaux)
# Installe dans ton dossier personnel ; seules les dépendances système passent par sudo pacman.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
DEST="$DATA/fileforge"
BIN="$HOME/.local/bin"
LAUNCHER="$BIN/fileforge"

c() { printf '\033[%sm%s\033[0m\n' "$1" "$2"; }
step() { echo; c "1;36" "[$1/7] $2"; }
ok() { c "32" "      $1"; }
warn() { c "33" "      $1"; }
ask() { local r; read -r -p "      $1 [O/n] " r || true; [[ -z "$r" || "$r" =~ ^[oOyY] ]]; }

echo
c "1;35" "  ================================="
c "1;35" "        Installation de FileForge"
c "1;35" "  ================================="

# 1. Dépendances système
step 1 "Dépendances système"
PKGS=(python python-gobject gtk3 webkit2gtk-4.1 tk ffmpeg tesseract tesseract-data-fra tesseract-data-eng
      xdg-utils dbus ttf-dejavu)
if command -v pacman >/dev/null; then
  MISSING=()
  for p in "${PKGS[@]}"; do pacman -Qq "$p" >/dev/null 2>&1 || MISSING+=("$p"); done
  if ((${#MISSING[@]})); then
    echo "      À installer avec pacman : ${MISSING[*]}"
    if ask "Lancer « sudo pacman -S --needed » maintenant ?"; then
      sudo pacman -S --needed "${MISSING[@]}"
    else
      warn "Installe-les puis relance ce script."; exit 1
    fi
  fi
  ok "Dépendances présentes"
else
  warn "pacman introuvable : installe l'équivalent de : ${PKGS[*]}"
  warn "(Debian/Ubuntu : python3-gi gir1.2-webkit2-4.1 python3-tk python3-venv ffmpeg tesseract-ocr-fra)"
  ask "Continuer quand même ?" || exit 1
fi
PY=""
for cand in python3 python /usr/bin/python3 /usr/bin/python3.14 /usr/bin/python3.13 /usr/bin/python3.12; do
  p="$(command -v "$cand" 2>/dev/null)" || continue
  if "$p" -c "import gi; gi.require_version('WebKit2', '4.1'); from gi.repository import WebKit2" 2>/dev/null; then
    PY="$p"; break
  fi
done
[[ -n "$PY" ]] || { warn "WebKit2GTK 4.1 introuvable pour Python (paquets python-gobject + webkit2gtk-4.1)."; exit 1; }
ok "Python : $PY"

# 2. Fichiers
step 2 "Copie des fichiers"
pkill -f "$DEST/wheel.py" 2>/dev/null || true
mkdir -p "$DEST" "$BIN"
cp -r "$SRC/app/." "$DEST/"
cp "$SRC/uninstall.sh" "$DEST/"
chmod +x "$DEST/uninstall.sh"
ok "Installé dans $DEST"

# 3. Environnement Python privé (accès à GTK/WebKit du système)
step 3 "Bibliothèques Python (quelques minutes la première fois)"
if [[ ! -x "$DEST/venv/bin/python" ]]; then
  "$PY" -m venv --system-site-packages "$DEST/venv"
fi
"$DEST/venv/bin/python" -m pip install -q --upgrade pip
"$DEST/venv/bin/python" -m pip install -q pymupdf pymupdf4llm pdf2docx pillow openpyxl pandas xlrd odfpy \
  mammoth markdown python-pptx pywebview
"$DEST/venv/bin/python" -m pip install -q pillow-heif 2>/dev/null || warn "pillow-heif indisponible : les photos HEIC ne seront pas lues"
"$DEST/venv/bin/python" -c "import webview, pymupdf, tkinter" || { warn "Vérification des bibliothèques échouée."; exit 1; }
ok "Bibliothèques installées"

# 4. Lanceur + entrée d'application
step 4 "Lanceur"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
# FileForge : fileforge [fichiers…]  (sans argument : zone de dépôt)
if [[ \$# -eq 0 && -n "\${NAUTILUS_SCRIPT_SELECTED_FILE_PATHS:-}" ]]; then
  mapfile -t ARGS < <(printf '%s' "\$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS" | sed '/^\$/d')
  set -- "\${ARGS[@]}"
fi
export GDK_BACKEND="\${GDK_BACKEND:-wayland,x11}"
# évite un écran blanc avec certains pilotes sous Wayland
export WEBKIT_DISABLE_DMABUF_RENDERER="\${WEBKIT_DISABLE_DMABUF_RENDERER:-1}"
setsid -f "$DEST/venv/bin/python" "$DEST/wheel.py" "\$@" >/dev/null 2>&1 < /dev/null
EOF
chmod +x "$LAUNCHER"
install -Dm644 "$DEST/icon.png" "$DATA/icons/hicolor/256x256/apps/fileforge.png"
MIMES="application/pdf;image/jpeg;image/png;image/webp;image/heic;image/heif;image/tiff;image/gif;image/bmp;image/avif;video/mp4;video/quicktime;video/x-matroska;video/webm;video/x-msvideo;audio/mpeg;audio/x-wav;audio/wav;audio/flac;audio/ogg;audio/mp4;audio/aac;application/vnd.openxmlformats-officedocument.wordprocessingml.document;application/msword;application/rtf;application/vnd.oasis.opendocument.text;application/vnd.openxmlformats-officedocument.presentationml.presentation;application/vnd.ms-powerpoint;application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;application/vnd.ms-excel;text/csv;application/json;text/markdown;text/plain;text/html;application/zip;application/x-tar;application/gzip;inode/directory;"
mkdir -p "$DATA/applications"
cat > "$DATA/applications/fileforge.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=FileForge
GenericName=Boîte à outils fichiers
Comment=Convertir, compresser, éditer PDF, images, vidéos, audio, documents
Exec=$LAUNCHER %F
Icon=fileforge
Terminal=false
Categories=Utility;Office;
MimeType=$MIMES
NoDisplay=false
EOF
command -v update-desktop-database >/dev/null && update-desktop-database -q "$DATA/applications" || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$DATA/icons/hicolor" 2>/dev/null || true
case ":$PATH:" in *":$BIN:"*) ok "Commande « fileforge » disponible" ;;
  *) warn "Ajoute ~/.local/bin à ton PATH pour utiliser la commande « fileforge » dans un terminal" ;; esac

# 5. Clic droit dans les gestionnaires de fichiers
step 5 "Clic droit des gestionnaires de fichiers"
# Nautilus (GNOME Fichiers) : Scripts > FileForge
mkdir -p "$DATA/nautilus/scripts"; ln -sf "$LAUNCHER" "$DATA/nautilus/scripts/FileForge"
# Dolphin (KDE)
mkdir -p "$DATA/kio/servicemenus"
cat > "$DATA/kio/servicemenus/fileforge.desktop" <<EOF
[Desktop Entry]
Type=Service
MimeType=all/all;
Actions=fileforge;
X-KDE-Priority=TopLevel

[Desktop Action fileforge]
Name=FileForge…
Icon=fileforge
Exec=$LAUNCHER %F
EOF
chmod +x "$DATA/kio/servicemenus/fileforge.desktop"
# Nemo
mkdir -p "$DATA/nemo/actions"
cat > "$DATA/nemo/actions/fileforge.nemo_action" <<EOF
[Nemo Action]
Name=FileForge…
Comment=Convertir, compresser, éditer
Exec=$LAUNCHER %F
Icon-Name=fileforge
Selection=notnone
Extensions=any;
EOF
# PCManFM-Qt / Caja (spécification FileManager-Actions)
mkdir -p "$DATA/file-manager/actions"
cat > "$DATA/file-manager/actions/fileforge.desktop" <<EOF
[Desktop Entry]
Type=Action
Name=FileForge…
Icon=fileforge
Profiles=all;

[X-Action-Profile all]
MimeTypes=all/all;
Exec=$LAUNCHER %F
EOF
# Thunar
if command -v thunar >/dev/null || [[ -d "${XDG_CONFIG_HOME:-$HOME/.config}/Thunar" ]]; then
  "$DEST/venv/bin/python" "$DEST/linux_setup.py" thunar-add "$LAUNCHER" | sed 's/^/      /'
fi
ok "Nautilus (Scripts), Dolphin, Nemo, PCManFM-Qt, Thunar + « Ouvrir avec » partout"

# 6. Hyprland
step 6 "Hyprland"
read -r HKIND HVER < <("$DEST/venv/bin/python" "$DEST/linux_setup.py" hypr-info)
if [[ "$HKIND" == "none" ]]; then
  ok "Hyprland non détecté : étape ignorée"
else
  echo "      Hyprland $HVER détecté ($([[ $HKIND == lua ]] && echo "config Lua" || echo "hyprland.conf"))."
  echo "      Pour que la roue flotte sous la souris (sans bordure) et pour le raccourci Super+Alt+F,"
  echo "      j'ajoute un fichier fileforge.$([[ $HKIND == lua ]] && echo lua || echo conf) et UNE ligne à ta config (sauvegarde faite)."
  if ask "D'accord ?"; then
    "$DEST/venv/bin/python" "$DEST/linux_setup.py" hypr-add "$LAUNCHER" | sed 's/^/      /'
  else
    warn "Ignoré. Les règles à copier sont dans le LISEZ-MOI."
  fi
fi

# 7. Options
step 7 "Options"
if command -v soffice >/dev/null; then ok "LibreOffice détecté"
elif command -v pacman >/dev/null; then
  echo "      LibreOffice (~ 500 Mo) permet Word / PowerPoint / Excel → PDF fidèles."
  if ask "Installer libreoffice-fresh ?"; then sudo pacman -S --needed libreoffice-fresh; fi
fi

echo
c "1;32" "  FileForge est installé !"
echo
echo "  - Clic droit sur des fichiers > FileForge…   (Nautilus : clic droit > Scripts > FileForge)"
echo "  - Clic droit > Ouvrir avec > FileForge        (tous les gestionnaires de fichiers)"
echo "  - Super + Alt + F : la roue s'ouvre sous la souris ; glisse-y des fichiers"
echo "  - Terminal : fileforge fichier1.pdf fichier2.jpg …"
echo "  - Désinstaller : $DEST/uninstall.sh"
echo
