#!/usr/bin/env python3
"""Construit les paquets téléchargeables dans site/downloads/.

    python3 tools/build.py

Produit :
  site/downloads/FileForge-macOS.zip
  site/downloads/FileForge-Windows.zip
  site/downloads/FileForge-Linux.tar.gz
  site/downloads/manifest.json   (version, tailles, empreintes SHA-256 — lu par le site)
"""
import hashlib, io, json, re, tarfile, time, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC, ASSETS, INST = ROOT / "src", ROOT / "assets", ROOT / "installers"
OUT = ROOT / "site" / "downloads"
VERSION = re.search(r'__version__ = "([^"]+)"', (SRC / "fileforge.py").read_text(encoding="utf-8")).group(1)
CORE = ["fileforge.py", "wheel.py", "wheel.html", "lucide.min.js"]
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
        for f in CORE:
            add_zip(zf, b + "app/" + f, (SRC / f).read_bytes())
        add_zip(zf, b + "install.command", (INST / "macos/install.command").read_bytes(), True)
        add_zip(zf, b + "uninstall.command", (INST / "macos/uninstall.command").read_bytes(), True)
        add_zip(zf, b + "LISEZ-MOI.txt", (INST / "macos/LISEZ-MOI.txt").read_bytes())
        for f in ("droplet.applescript", "workflow-Info.plist", "workflow-document.wflow"):
            add_zip(zf, b + "support/" + f, (INST / "macos" / f).read_bytes())
        add_zip(zf, b + "support/FileForge.icns", (ASSETS / "FileForge.icns").read_bytes())
    return p


def build_windows():
    p = OUT / "FileForge-Windows.zip"
    w = INST / "windows"
    with zipfile.ZipFile(p, "w") as zf:
        b = "FileForge-Windows/"
        for f in CORE:
            add_zip(zf, b + "app/" + f, (SRC / f).read_bytes())
        add_zip(zf, b + "app/icon.ico", (ASSETS / "icon.ico").read_bytes())
        add_zip(zf, b + "install.ps1", windows_text((w / "install.ps1").read_bytes(), True))
        add_zip(zf, b + "uninstall.ps1", windows_text((w / "uninstall.ps1").read_bytes(), True))
        add_zip(zf, b + "LISEZ-MOI.txt", windows_text((w / "LISEZ-MOI.txt").read_bytes(), True))
        add_zip(zf, b + "Installer FileForge.bat", windows_text((w / "Installer FileForge.bat").read_bytes(), False))
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
