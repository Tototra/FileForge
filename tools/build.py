#!/usr/bin/env python3
"""Construit les paquets téléchargeables dans site/downloads/.

    python3 tools/build.py

Produit :
  site/downloads/FileForge-macOS.zip
  site/downloads/FileForge-Setup.exe  (nécessite makensis)
  site/downloads/FileForge-Linux.tar.gz
  site/downloads/manifest.json   (version, tailles, empreintes SHA-256 — lu par le site et par les mises à jour)
  site/downloads/manifest.sig    (signature Ed25519 du manifeste : sans elle, aucune mise à jour n'est acceptée)

La clé privée de signature n'est jamais dans le dépôt : ~/.config/fileforge/update_signing.key
(ou le fichier indiqué par FF_SIGNING_KEY), 64 caractères hexadécimaux. Sa clé publique est dans src/updater.py.
"""
import hashlib, importlib.util, io, json, os, re, sys, tarfile, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC, ASSETS, INST = ROOT / "src", ROOT / "assets", ROOT / "installers"
OUT = ROOT / "site" / "downloads"
VERSION = re.search(r'__version__ = "([^"]+)"', (SRC / "fileforge.py").read_text(encoding="utf-8")).group(1)
CORE = ["fileforge.py", "wheel.py", "wheel.html", "search.py", "editor.py", "editor.html", "updater.py", "ed25519.py",
        "lucide.min.js"]
# horodatage fixe : archives reproductibles (même contenu → même empreinte)
EPOCH = (2026, 1, 1, 0, 0, 0)


def windows_text(data: bytes, bom: bool) -> bytes:
    t = data.decode("utf-8").replace("\r\n", "\n").replace("\n", "\r\n")
    return (b"\xef\xbb\xbf" if bom else b"") + t.encode("utf-8")


def add_zip(zf, arc, data: bytes, executable=False):
    zi = zipfile.ZipInfo(arc, EPOCH)
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.external_attr = ((0o100755 if executable else 0o100644) & 0xFFFF) << 16
    zf.writestr(zi, data, compresslevel=9)


def build_macos():
    p = OUT / "FileForge-macOS.zip"
    with zipfile.ZipFile(p, "w") as zf:
        b = "FileForge-macOS/"
        for f in CORE + ["hotkey_mac.py"]:
            add_zip(zf, b + "app/" + f, (SRC / f).read_bytes())
        add_zip(zf, b + "install.command", (INST / "macos/install.command").read_bytes(), True)
        add_zip(zf, b + "uninstall.command", (INST / "macos/uninstall.command").read_bytes(), True)
        add_zip(zf, b + "LISEZ-MOI.txt", (INST / "macos/LISEZ-MOI.txt").read_bytes())
        for f in ("droplet.applescript", "workflow-Info.plist", "workflow-document.wflow"):
            add_zip(zf, b + "support/" + f, (INST / "macos" / f).read_bytes())
        add_zip(zf, b + "support/FileForge.icns", (ASSETS / "FileForge.icns").read_bytes())
    return p


def wizard_bitmap(dst):
    """Image latérale de l'installateur (164x314) aux couleurs de FileForge."""
    from PIL import Image, ImageDraw
    w, h = 164, 314
    im = Image.new("RGB", (w, h), "#15161d")
    d = ImageDraw.Draw(im)
    for y in range(h):  # léger dégradé violet vers le bas
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(21 + 30 * t), int(22 + 10 * t), int(29 + 60 * t)))
    cols = ["#7c5cff", "#ec4899", "#3b82f6", "#10b981", "#06b6d4", "#f59e0b", "#8b93a7"]
    cx, cy, r0, r1 = w // 2, 150, 34, 66
    for i, c in enumerate(cols):  # la roue
        a0, a1 = i * 360 / 7 - 90 + 1.5, (i + 1) * 360 / 7 - 90 - 1.5
        d.pieslice([cx - r1, cy - r1, cx + r1, cy + r1], a0, a1, fill=c)
    d.ellipse([cx - r0 + 4, cy - r0 + 4, cx + r0 - 4, cy + r0 - 4], fill="#1d1e29")
    icon = Image.open(ASSETS / "icon.png").convert("RGBA").resize((40, 40), Image.LANCZOS)
    im.paste(icon, (cx - 20, cy - 20), icon)
    im.save(dst, "BMP")


def build_windows():
    """FileForge-Setup.exe : un seul fichier à double-cliquer (NSIS, compilé avec makensis)."""
    import shutil, subprocess, tempfile
    p = OUT / "FileForge-Setup.exe"
    w = INST / "windows"
    if not shutil.which("makensis"):
        # jamais l'ancien Setup.exe sous le nouveau numéro de version : chaque PC Windows le réinstallerait en boucle
        raise SystemExit("makensis introuvable : brew install makensis  (ou sudo apt install nsis)")
    st = Path(tempfile.mkdtemp())
    (st / "app").mkdir()
    for f in CORE + ["hotkey_win.py"]:
        (st / "app" / f).write_bytes((SRC / f).read_bytes())
    (st / "app" / "icon.ico").write_bytes((ASSETS / "icon.ico").read_bytes())
    (st / "install.ps1").write_bytes(windows_text((w / "install.ps1").read_bytes(), True))
    (st / "uninstall.ps1").write_bytes(windows_text((w / "uninstall.ps1").read_bytes(), True))
    wizard_bitmap(st / "wizard.bmp")
    import calendar
    env = dict(os.environ, SOURCE_DATE_EPOCH=str(calendar.timegm(EPOCH + (0, 0, 0))))   # horodatage fixe de l'exe
    r = subprocess.run(["makensis", "-V2", "-INPUTCHARSET", "UTF8", f"-DSTAGE={st}", f"-DVERSION={VERSION}",
                        f"-DOUTFILE={p}", str(w / "FileForge.nsi")], capture_output=True, text=True, env=env)
    shutil.rmtree(st, ignore_errors=True)
    if r.returncode != 0:
        raise SystemExit("makensis :\n" + r.stdout + r.stderr)
    old = OUT / "FileForge-Windows.zip"
    if old.exists():
        old.unlink()
    return p


def build_linux():
    p = OUT / "FileForge-Linux.tar.gz"
    files = [(f"app/{f}", SRC / f, False) for f in CORE + ["linux_setup.py"]]
    files += [("app/icon.png", ASSETS / "icon.png", False),
              ("install.sh", INST / "linux/install.sh", True),
              ("uninstall.sh", INST / "linux/uninstall.sh", True),
              ("LISEZ-MOI.md", INST / "linux/LISEZ-MOI.md", False)]
    import calendar
    mtime = calendar.timegm(EPOCH + (0, 0, 0))     # indépendant du fuseau horaire : archive reproductible partout
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tf:
        for d in ("fileforge-linux", "fileforge-linux/app"):
            ti = tarfile.TarInfo(d); ti.type = tarfile.DIRTYPE; ti.mode = 0o755; ti.mtime = mtime
            tf.addfile(ti)
        for arc, src, exe in files:
            data = src.read_bytes()
            ti = tarfile.TarInfo("fileforge-linux/" + arc)
            ti.size, ti.mode, ti.mtime = len(data), (0o755 if exe else 0o644), mtime
            tf.addfile(ti, io.BytesIO(data))
    import gzip
    with open(p, "wb") as fh, gzip.GzipFile(fileobj=fh, mode="wb", mtime=0, compresslevel=9) as gz:
        gz.write(buf.getvalue())
    return p


def signing_key():
    path = Path(os.environ.get("FF_SIGNING_KEY") or Path.home() / ".config" / "fileforge" / "update_signing.key")
    try:
        key = bytes.fromhex(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        raise SystemExit(f"clé de signature introuvable ou illisible : {path}\n"
                         "(sans signature, aucun ordinateur n'accepterait cette version)") from None
    if len(key) != 32:
        raise SystemExit(f"clé de signature invalide : {path}")
    spec = importlib.util.spec_from_file_location("ed25519", SRC / "ed25519.py")
    ed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ed)
    return key, ed


def check_public_key(pub):
    if pub.hex() not in (SRC / "updater.py").read_text(encoding="utf-8"):
        raise SystemExit("cette clé ne correspond pas à PUBLIC_KEY dans src/updater.py : les mises à jour seraient refusées")


def main():
    try:                                # console Windows (cp1252) : les flèches et accents ne doivent pas tout arrêter
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    OUT.mkdir(parents=True, exist_ok=True)
    key, ed = signing_key()             # vérifiée avant de construire quoi que ce soit
    # notes de version et « mise à jour importante » : tools/release.json (lu par updater.py sur chaque ordinateur)
    rel = json.loads((ROOT / "tools" / "release.json").read_text(encoding="utf-8")) if (ROOT / "tools" / "release.json").exists() else {}
    if rel.get("version") not in (None, VERSION):
        rel = {}                     # notes d'une autre version : on ne les publie pas
    manifest = {"version": VERSION, "notes": rel.get("notes", []), "required": bool(rel.get("required")), "files": {}}
    for os_name, fn in (("macos", build_macos), ("windows", build_windows), ("linux", build_linux)):
        p = fn()
        data = p.read_bytes()
        manifest["files"][os_name] = {"name": p.name, "bytes": len(data),
                                      "sha256": hashlib.sha256(data).hexdigest()}
        print(f"{p.name:28s} {len(data) / 1024:7.1f} Ko")
    raw = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    sig = ed.sign(key, raw)
    if not os.environ.get("FF_TEST_BUILD"):     # CI : clé de test, paquets jamais publiés
        check_public_key(ed.public_key(key))
    (OUT / "manifest.json").write_bytes(raw)
    (OUT / "manifest.sig").write_text(sig.hex() + "\n", encoding="ascii")
    print(f"version {VERSION} → {OUT.relative_to(ROOT) if OUT.is_relative_to(ROOT) else OUT}/manifest.json (signé)")


if __name__ == "__main__":
    main()
