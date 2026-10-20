#!/usr/bin/env python3
"""Construit les paquets téléchargeables dans site/downloads/.

    python3 tools/build.py

Produit :
  site/downloads/FileForge-macOS.zip
  site/downloads/FileForge-Setup.exe  (nécessite makensis)
  site/downloads/FileForge-Linux.tar.gz
  site/downloads/manifest.json   (version, tailles, empreintes SHA-256 — lu par le site)
"""
import hashlib, io, json, re, tarfile, time, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC, ASSETS, INST = ROOT / "src", ROOT / "assets", ROOT / "installers"
OUT = ROOT / "site" / "downloads"
VERSION = re.search(r'__version__ = "([^"]+)"', (SRC / "fileforge.py").read_text(encoding="utf-8")).group(1)
CORE = ["fileforge.py", "wheel.py", "wheel.html", "search.py", "lucide.min.js"]
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
        raise SystemExit("makensis introuvable : sudo apt install nsis  (ou brew install makensis)")
    st = Path(tempfile.mkdtemp())
    (st / "app").mkdir()
    for f in CORE:
        (st / "app" / f).write_bytes((SRC / f).read_bytes())
    (st / "app" / "icon.ico").write_bytes((ASSETS / "icon.ico").read_bytes())
    (st / "install.ps1").write_bytes(windows_text((w / "install.ps1").read_bytes(), True))
    (st / "uninstall.ps1").write_bytes(windows_text((w / "uninstall.ps1").read_bytes(), True))
    wizard_bitmap(st / "wizard.bmp")
    r = subprocess.run(["makensis", "-V2", "-INPUTCHARSET", "UTF8", f"-DSTAGE={st}", f"-DVERSION={VERSION}",
                        f"-DOUTFILE={p}", str(w / "FileForge.nsi")], capture_output=True, text=True)
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
    mtime = time.mktime(EPOCH + (0, 0, -1))
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


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"version": VERSION, "files": {}}
    for os_name, fn in (("macos", build_macos), ("windows", build_windows), ("linux", build_linux)):
        p = fn()
        data = p.read_bytes()
        manifest["files"][os_name] = {"name": p.name, "bytes": len(data),
                                      "sha256": hashlib.sha256(data).hexdigest()}
        print(f"{p.name:28s} {len(data) / 1024:7.1f} Ko")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"version {VERSION} → {OUT.relative_to(ROOT)}/manifest.json")


if __name__ == "__main__":
    main()
