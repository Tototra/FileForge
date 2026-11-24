"""Paquets et installateurs : build.py, manifeste signé, cohérence des versions, scripts shell/PowerShell/NSIS."""
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from conftest import ROOT, SRC, ff, load


@pytest.fixture
def build(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("ff_build", ROOT / "tools" / "build.py")
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    monkeypatch.setattr(b, "OUT", tmp_path / "downloads")
    key = tmp_path / "signing.key"
    key.write_text("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60\n")
    monkeypatch.setenv("FF_SIGNING_KEY", str(key))
    monkeypatch.setattr(b, "check_public_key", lambda pub: None)
    return b


def test_core_lists_every_runtime_module(build):
    """Tout module importé par le programme installé doit être livré."""
    import re
    shipped = set(build.CORE)
    for f in build.CORE:
        if f.endswith(".py"):
            for m in re.findall(r'HERE / "([a-z_0-9]+\.(?:py|html|js))"', (SRC / f).read_text(encoding="utf-8")):
                assert m in shipped or m.startswith("hotkey_") or m == "linux_setup.py", f"{f} charge {m}, absent des paquets"
            for m in re.findall(r'with_name\("([a-z_0-9]+\.py)"\)', (SRC / f).read_text(encoding="utf-8")):
                assert m in shipped, f"{f} lance {m}, absent des paquets"


@pytest.mark.slow
def test_build_all_packages_and_signed_manifest(build):
    if not shutil.which("makensis"):
        pytest.skip("makensis absent")
    build.main()
    out = build.OUT
    m_raw = (out / "manifest.json").read_bytes()
    m = json.loads(m_raw)
    assert m["version"] == ff.__version__
    for os_name, f in m["files"].items():
        data = (out / f["name"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == f["sha256"] and len(data) == f["bytes"]
    sig = load("ed25519", "ff_ed_b")
    pub = sig.public_key(bytes.fromhex((Path(build.os.environ["FF_SIGNING_KEY"]).read_text().strip())))
    assert sig.verify(pub, m_raw, bytes.fromhex((out / "manifest.sig").read_text().strip()))
    z = zipfile.ZipFile(out / "FileForge-macOS.zip")
    names = set(z.namelist())
    for f in build.CORE:
        assert f"FileForge-macOS/app/{f}" in names
    assert z.getinfo("FileForge-macOS/install.command").external_attr >> 16 & 0o111
    t = tarfile.open(out / "FileForge-Linux.tar.gz")
    assert {f"fileforge-linux/app/{f}" for f in build.CORE} <= set(t.getnames())
    assert (out / "FileForge-Setup.exe").read_bytes()[:2] == b"MZ"


@pytest.mark.slow
def test_build_is_reproducible(build):
    if not shutil.which("makensis"):
        pytest.skip("makensis absent")
    build.main()
    a = (build.OUT / "manifest.json").read_bytes()
    build.main()
    assert (build.OUT / "manifest.json").read_bytes() == a


def test_build_refuses_stale_windows_installer(build, monkeypatch):
    """Sans makensis, ne jamais publier l'ancien Setup.exe sous le nouveau numéro de version."""
    build.OUT.mkdir(parents=True)
    (build.OUT / "FileForge-Setup.exe").write_bytes(b"MZ ancienne version")
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: None if n == "makensis" else "/usr/bin/" + n)
    with pytest.raises(SystemExit):
        build.main()
    assert not (build.OUT / "manifest.json").exists()


def test_build_refuses_key_not_matching_updater(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("ff_build2", ROOT / "tools" / "build.py")
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    sig = load("ed25519", "ff_ed_c")
    with pytest.raises(SystemExit, match="PUBLIC_KEY"):
        b.check_public_key(sig.public_key(bytes(32)))


def test_real_signing_key_matches_updater():
    """La clé privée locale (si présente sur cet ordinateur) correspond bien à la clé publique livrée."""
    k = Path.home() / ".config" / "fileforge" / "update_signing.key"
    if not k.exists():
        pytest.skip("pas de clé de signature sur cet ordinateur")
    sig = load("ed25519", "ff_ed_d")
    up = load("updater", "ff_up_pk")
    assert sig.public_key(bytes.fromhex(k.read_text().strip())).hex() == up.PUBLIC_KEY


def test_build_refuses_without_signing_key(build, monkeypatch, tmp_path):
    monkeypatch.setenv("FF_SIGNING_KEY", str(tmp_path / "absente.key"))
    monkeypatch.setattr(build, "build_windows", lambda: (build.OUT / "w.exe", (build.OUT / "w.exe").write_bytes(b"MZ"))[0])
    monkeypatch.setattr(build, "build_macos", lambda: (build.OUT / "m.zip", (build.OUT / "m.zip").write_bytes(b"PK"))[0])
    monkeypatch.setattr(build, "build_linux", lambda: (build.OUT / "l.tgz", (build.OUT / "l.tgz").write_bytes(b"x"))[0])
    build.OUT.mkdir(parents=True)
    with pytest.raises(SystemExit, match="clé"):
        build.main()


def test_release_json_matches_version():
    rel = json.loads((ROOT / "tools" / "release.json").read_text(encoding="utf-8"))
    assert rel["version"] == ff.__version__


def test_signing_key_never_in_repo():
    r = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True)
    for f in r.stdout.split():
        if f.endswith((".key", ".pem")) or "signing" in f.lower():
            pytest.fail(f"fichier de clé suivi par git : {f}")


def test_gitignore_covers_local_state():
    gi = (ROOT / ".gitignore").read_text()
    for p in (".wrangler/", ".venv/", "*.key"):
        assert p in gi


@pytest.mark.parametrize("script", sorted(str(p.relative_to(ROOT)) for p in list((ROOT / "installers").rglob("*.sh"))
                                           + list((ROOT / "installers").rglob("*.command")) + list((ROOT / "tools").glob("*.sh"))))
def test_shell_syntax(script):
    r = subprocess.run(["bash", "-n", str(ROOT / script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_mac_installer_optional_libreoffice_step_cannot_abort():
    """Avec set -e + pipefail, une commande facultative qui échoue ne doit pas arrêter l'installation."""
    src = (ROOT / "installers/macos/install.command").read_text()
    line = next(l for l in src.splitlines() if l.strip().startswith("V=$(curl"))
    assert "|| true" in line.split("#")[0]


def test_mac_uninstaller_uses_private_python():
    src = (ROOT / "installers/macos/uninstall.command").read_text()
    assert "python3 -" not in src and "/usr/bin/python3" not in src


def test_nsis_uninstall_checks_folder():
    src = (ROOT / "installers/windows/FileForge.nsi").read_text(encoding="utf-8")
    sec = src[src.index('Section "Uninstall"'):]
    assert "FileExists" in sec and "wheel.py" in sec


def test_publish_pages_requires_committed_site():
    src = (ROOT / "tools/publish_pages.sh").read_text()
    assert "git diff --quiet" in src


def test_applescript_droplet_quotes_paths():
    src = (ROOT / "installers/macos/droplet.applescript").read_text(encoding="utf-8")
    assert "quoted form of" in src


def test_site_headers():
    h = (ROOT / "site/_headers").read_text()
    assert "X-Content-Type-Options: nosniff" in h
    assert "Content-Security-Policy" in h
