#!/usr/bin/env python3
# FileForge — Copyright © 2026 Thomas Trahant — SPDX-License-Identifier: GPL-3.0-or-later
"""Intégration de FileForge au bureau Linux (Hyprland, Thunar).

  linux_setup.py hypr-info              -> affiche : <type> <version>   (lua | conf-new | conf-old | none)
  linux_setup.py hypr-add <lanceur>     -> écrit les règles + raccourci, ajoute UNE ligne d'inclusion
  linux_setup.py hypr-remove            -> retire tout ce qui a été ajouté
  linux_setup.py thunar-add <lanceur>   -> ajoute l'action au clic droit de Thunar
  linux_setup.py thunar-remove
Chaque fichier modifié est d'abord sauvegardé (<fichier>.avant-fileforge).
"""
import json, os, re, shutil, subprocess, sys
import xml.etree.ElementTree as ET
from pathlib import Path

HYPR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "hypr"
THUNAR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "Thunar" / "uca.xml"
TAG = "fileforge"
TITLE = "FileForge-Roue"
BIND_KEYS = ("SUPER", "ALT", "F")


def backup(p: Path):
    b = p.with_name(p.name + ".avant-fileforge")
    if p.exists() and not b.exists():
        shutil.copy2(p, b)


def hypr_version():
    for cmd in (["hyprctl", "version", "-j"], ["Hyprland", "--version"], ["hyprland", "--version"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
        except Exception:
            continue
        tag = None
        try:
            tag = json.loads(out).get("tag")
        except Exception:
            m = re.search(r"v?(\d+\.\d+(?:\.\d+)?)", out)
            tag = m.group(1) if m else None
        if tag:
            m = re.search(r"(\d+)\.(\d+)", tag)
            if m:
                return int(m.group(1)), int(m.group(2))
    return None


def hypr_info():
    lua, conf = HYPR / "hyprland.lua", HYPR / "hyprland.conf"
    v = hypr_version()
    if lua.exists():
        kind = "lua"
    elif conf.exists():
        kind = "conf-new" if (v is None or v >= (0, 53)) else "conf-old"
    else:
        kind = "none"
    return kind, (f"{v[0]}.{v[1]}" if v else "?")


def bind_taken(text):
    t = text.upper().replace(" ", "")
    return any(k in t for k in ("SUPERALT,F,", "SUPER_ALT,F,", "ALTSUPER,F,", '"SUPER+ALT+F"'))


def hypr_add(launcher):
    kind, ver = hypr_info()
    if kind == "none":
        print("Aucune configuration Hyprland trouvée : étape ignorée.")
        return
    if kind == "lua":
        main, mod = HYPR / "hyprland.lua", HYPR / "fileforge.lua"
        taken = bind_taken(main.read_text(errors="ignore"))
        body = f'''-- FileForge (ajouté par l'installateur ; supprime ce fichier et la ligne require pour l'enlever)
hl.window_rule({{
    name  = "fileforge-roue",
    match = {{ title = "^({TITLE})$" }},
    float = true,
    size  = {{ 760, 760 }},
    move  = {{ "cursor_x - (window_w * 0.5)", "cursor_y - (window_h * 0.5)" }},
    border_size = 0,
    rounding    = 0,
    no_shadow   = true,
    no_blur     = true,
    no_anim     = true,
}})
hl.window_rule({{
    name   = "fileforge-outils",
    match  = {{ title = "^(FileForge — .*)$" }},
    float  = true,
    center = true,
}})
'''
        body += ("-- raccourci non ajouté : Super+Alt+F est déjà utilisé dans ta config\n" if taken else
                 f'hl.bind("SUPER + ALT + F", hl.dsp.exec_cmd("{launcher}"))\n')
        line = 'require("fileforge")  -- FileForge'
    else:
        main, mod = HYPR / "hyprland.conf", HYPR / "fileforge.conf"
        taken = bind_taken(main.read_text(errors="ignore"))
        if kind == "conf-new":
            body = f'''# FileForge (ajouté par l'installateur ; supprime ce fichier et la ligne source pour l'enlever)
windowrule {{
    name = fileforge-roue
    match:title = ^({TITLE})$
    float = on
    size = 760 760
    move = (cursor_x-(window_w*0.5)) (cursor_y-(window_h*0.5))
    border_size = 0
    rounding = 0
    no_shadow = on
    no_blur = on
    no_anim = on
}}
windowrule {{
    name = fileforge-outils
    match:title = ^(FileForge — .*)$
    float = on
    center = on
}}
'''
        else:
            r = f"title:^({TITLE})$"
            body = "# FileForge (ajouté par l'installateur)\n" + "".join(
                f"windowrulev2 = {e}, {r}\n" for e in
                ("float", "size 760 760", "move onscreen cursor -50% -50%", "noborder", "noshadow",
                 "noblur", "rounding 0", "noanim"))
            body += "windowrulev2 = float, title:^(FileForge — .*)$\nwindowrulev2 = center, title:^(FileForge — .*)$\n"
        body += ("# raccourci non ajouté : Super+Alt+F est déjà utilisé dans ta config\n" if taken else
                 f"bind = SUPER ALT, F, exec, {launcher}\n")
        line = f"source = {mod}  # FileForge"
    mod.write_text(body, encoding="utf-8")
    text = main.read_text(errors="ignore")
    if line.split("#")[0].split("--")[0].strip() not in text:
        backup(main)
        with open(main, "a", encoding="utf-8") as fh:
            fh.write(("\n" if not text.endswith("\n") else "") + line + "\n")
    subprocess.run(["hyprctl", "reload"], capture_output=True)
    print(f"Hyprland {ver} ({'Lua' if kind == 'lua' else 'hyprland.conf'}) : règles ajoutées"
          + ("" if taken else ", raccourci Super+Alt+F"))
    if taken:
        print("ATTENTION : Super+Alt+F est déjà utilisé, choisis un autre raccourci dans " + str(mod))


def hypr_remove():
    for main, mod in ((HYPR / "hyprland.lua", HYPR / "fileforge.lua"), (HYPR / "hyprland.conf", HYPR / "fileforge.conf")):
        if main.exists():
            lines = main.read_text(errors="ignore").splitlines(keepends=True)
            keep = [l for l in lines if not (("FileForge" in l) and ("require(\"fileforge\")" in l or "fileforge.conf" in l))]
            if len(keep) != len(lines):
                main.write_text("".join(keep), encoding="utf-8")
        mod.unlink(missing_ok=True)
    subprocess.run(["hyprctl", "reload"], capture_output=True)


def thunar_add(launcher):
    THUNAR.parent.mkdir(parents=True, exist_ok=True)
    if THUNAR.exists():
        backup(THUNAR)
        tree = ET.parse(THUNAR)
        root = tree.getroot()
    else:
        root = ET.Element("actions")
        tree = ET.ElementTree(root)
    for a in list(root):
        if (a.findtext("unique-id") or "").startswith(TAG):
            root.remove(a)
    a = ET.SubElement(root, "action")
    for k, v in (("icon", "fileforge"), ("name", "FileForge…"), ("submenu", ""), ("unique-id", f"{TAG}-1"),
                 ("command", f"{launcher} %F"), ("description", "Convertir, compresser, éditer…"),
                 ("range", "*"), ("patterns", "*")):
        ET.SubElement(a, k).text = v
    for k in ("startup-notify", "directories", "audio-files", "image-files", "other-files", "text-files", "video-files"):
        ET.SubElement(a, k)
    ET.indent(tree)
    tree.write(THUNAR, encoding="UTF-8", xml_declaration=True)
    print("Thunar : action ajoutée au clic droit")


def thunar_remove():
    if not THUNAR.exists():
        return
    tree = ET.parse(THUNAR)
    root = tree.getroot()
    for a in list(root):
        if (a.findtext("unique-id") or "").startswith(TAG):
            root.remove(a)
    tree.write(THUNAR, encoding="UTF-8", xml_declaration=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    arg = sys.argv[2] if len(sys.argv) > 2 else ""
    if cmd == "hypr-info":
        print(*hypr_info())
    elif cmd == "hypr-add":
        hypr_add(arg)
    elif cmd == "hypr-remove":
        hypr_remove()
    elif cmd == "thunar-add":
        thunar_add(arg)
    elif cmd == "thunar-remove":
        thunar_remove()
    else:
        print(__doc__)
