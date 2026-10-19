#!/usr/bin/env bash
# FileForge — désinstallation (ne touche pas à tes fichiers personnels)
set -uo pipefail
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
DEST="$DATA/fileforge"
echo "Désinstallation de FileForge…"
pkill -f "$DEST/wheel.py" 2>/dev/null
if [[ -x "$DEST/venv/bin/python" ]]; then
  "$DEST/venv/bin/python" "$DEST/linux_setup.py" hypr-remove
  "$DEST/venv/bin/python" "$DEST/linux_setup.py" thunar-remove
fi
rm -f "$HOME/.local/bin/fileforge" \
      "$DATA/applications/fileforge.desktop" \
      "$DATA/icons/hicolor/256x256/apps/fileforge.png" \
      "$DATA/nautilus/scripts/FileForge" \
      "$DATA/kio/servicemenus/fileforge.desktop" \
      "$DATA/nemo/actions/fileforge.nemo_action" \
      "$DATA/file-manager/actions/fileforge.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database -q "$DATA/applications"
rm -rf "$DEST"
echo "FileForge a été désinstallé. (Les dépendances pacman sont conservées ; ta signature enregistrée a été supprimée.)"
