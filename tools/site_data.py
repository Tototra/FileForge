#!/usr/bin/env python3
"""Régénère site/assets/wheel-data.js à partir du vrai code de FileForge.

La démo du site affiche exactement les catégories, actions, couleurs et icônes que la roue
proposerait pour chaque fichier d'exemple.

    python3 tools/site_data.py        (nécessite pywebview installé et Node.js pour les icônes)
"""
import json, subprocess, sys, tempfile, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ["rapport.pdf", "vacances.heic", "interview.mov", "budget.xlsx"]
EXTRA_ICONS = ["circle-check", "github", "download", "apple", "monitor", "terminal", "wifi-off", "undo-2",
               "cloud-upload", "hourglass", "mouse-pointer-click"]


def main():
    sys.argv = [sys.argv[0]]
    spec = importlib.util.spec_from_file_location("wheel", ROOT / "src" / "wheel.py")
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    tmp = Path(tempfile.mkdtemp())
    demo = {}
    for name in SAMPLES:
        f = tmp / name
        f.write_text("x")
        st = w.build_main([str(f)], w.ff.available([str(f)]))
        demo[name] = {"badge": st["badge"], "color": st["color"], "cats": [
            {"label": c["label"], "icon": c["icon"], "color": c["color"],
             "actions": [{k: a[k] for k in ("id", "label", "icon", "full")} for a in c["actions"]]}
            for c in st["cats"]]}
    names = sorted({c["icon"] for v in demo.values() for c in v["cats"]}
                   | {a["icon"] for v in demo.values() for c in v["cats"] for a in c["actions"]} | set(EXTRA_ICONS))
    js = f"""
const L = require({json.dumps(str(ROOT / 'src' / 'lucide.min.js'))});
const out = {{}};
for (const n of {json.dumps(names)}) {{
  const node = L.icons[n.split('-').map(w => w[0].toUpperCase() + w.slice(1)).join('')];
  if (!node) continue;
  const kids = (Array.isArray(node[2]) ? node[2] : node).filter(Array.isArray);
  out[n] = kids.map(([t, a]) => '<' + t + ' ' + Object.entries(a).map(([k, v]) => k + '="' + v + '"').join(' ') + '/>').join('');
}}
process.stdout.write(JSON.stringify(out));
"""
    icons = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    data = json.dumps({"demo": demo, "icons": icons}, ensure_ascii=False, separators=(",", ":"))
    out = ROOT / "site" / "assets" / "wheel-data.js"
    out.write_text("/* Généré par tools/site_data.py à partir de src/ — ne pas modifier à la main */\n"
                   f"window.FF_DATA = {data};\n", encoding="utf-8")
    print(f"{out.relative_to(ROOT)} : {len(demo)} fichiers d'exemple, {len(icons)} icônes")


if __name__ == "__main__":
    main()
