#!/bin/bash
# FileForge — désinstallation macOS (ne touche pas à tes fichiers)
DEST="$HOME/Library/Application Support/FileForge"
echo "Désinstallation de FileForge…"
pkill -f "$DEST/wheel.py" 2>/dev/null
rm -rf "$HOME/Library/Services/FileForge.workflow" "$HOME/Applications/FileForge.app"
python3 - <<'PY' 2>/dev/null || true
import plistlib, subprocess
raw = subprocess.run(["defaults", "export", "pbs", "-"], capture_output=True).stdout
if raw:
    d = plistlib.loads(raw)
    d.get("NSServicesStatus", {}).pop("(null) - FileForge… - runWorkflowAsService", None)
    subprocess.run(["defaults", "import", "pbs", "-"], input=plistlib.dumps(d))
PY
/System/Library/CoreServices/pbs -update >/dev/null 2>&1
rm -rf "$DEST"
echo "FileForge a été désinstallé. Le journal reste dans ~/Library/Logs/FileForge.log."
