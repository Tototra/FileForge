"""Mises à jour : signature du manifeste, empreinte, miroirs, « Plus tard », installation, boucle infinie évitée."""
import hashlib
import json
import os
import sys
import time
import zipfile
from pathlib import Path

import pytest

from conftest import load, ff, SRC

sig = load("ed25519", "ff_ed25519")


@pytest.fixture
def up(tmp_path, monkeypatch):
    u = load("updater", "ff_updater_t")
    monkeypatch.setattr(u, "STATE", tmp_path / "update.json")
    monkeypatch.setattr(u.ff, "LOG", tmp_path / "log.txt")
    return u


KEY = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
PUB = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")


def test_ed25519_rfc8032_vectors():
    assert sig.public_key(KEY) == PUB
    s = sig.sign(KEY, b"")
    assert s.hex() == ("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b4"
                       "6bd25bf5f0595bbe24655141438e7a100b")
    assert sig.verify(PUB, b"", s)
    # vecteur 2 (1 octet)
    k2 = bytes.fromhex("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb")
    s2 = sig.sign(k2, b"\x72")
    assert s2.hex().startswith("92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da")
    assert sig.verify(sig.public_key(k2), b"\x72", s2)


def test_ed25519_rejects_tampering():
    s = sig.sign(KEY, b"manifest")
    assert not sig.verify(PUB, b"manifesT", s)
    assert not sig.verify(PUB, b"manifest", s[:-1] + bytes([s[-1] ^ 1]))
    assert not sig.verify(PUB, b"manifest", b"\0" * 64)
    assert not sig.verify(b"\0" * 31, b"manifest", s)
    assert not sig.verify(PUB, b"manifest", s[:63])


def test_embedded_public_key_is_valid(up):
    pk = bytes.fromhex(up.PUBLIC_KEY)
    assert len(pk) == 32 and sig.point_decompress(pk) is not None


def make_site(tmp_path, version="9.9.9", key=KEY, tamper=False, bad_sha=False, required=False, nosig=False):
    d = tmp_path / f"site-{version}-{tamper}-{bad_sha}-{nosig}"
    d.mkdir()
    payload = b"installateur factice " + version.encode()
    name = {"win32": "FileForge-Setup.exe", "darwin": "FileForge-macOS.zip"}.get(sys.platform, "FileForge-Linux.tar.gz")
    (d / name).write_bytes(payload)
    m = {"version": version, "notes": ["Nouveauté été"], "required": required,
         "files": {k: {"name": name, "bytes": len(payload), "sha256": "0" * 64 if bad_sha else hashlib.sha256(payload).hexdigest()}
                   for k in ("macos", "windows", "linux")}}
    raw = json.dumps(m, indent=2).encode()
    (d / "manifest.json").write_bytes(raw)
    if not nosig:
        s = sig.sign(key, raw)
        (d / "manifest.sig").write_text(s.hex())
    if tamper:
        m["files"]["macos"]["sha256"] = m["files"]["windows"]["sha256"] = m["files"]["linux"]["sha256"] = "1" * 64
        (d / "manifest.json").write_text(json.dumps(m, indent=2))
    return d / "manifest.json"


@pytest.fixture
def local(monkeypatch, up):
    def _use(manifest):
        monkeypatch.setenv("FF_UPDATE_URL", str(manifest))
        monkeypatch.setenv("FF_UPDATE_PUBKEY", PUB.hex())
        monkeypatch.setattr(up, "MANIFEST", str(manifest))
    return _use


def test_check_valid_signature(up, local, tmp_path):
    local(make_site(tmp_path))
    info = up.check()
    assert info["newer"] and info["latest"] == "9.9.9" and info["notes"] == ["Nouveauté été"]
    assert Path(info["file"]["url"]).exists()


def test_check_tampered_manifest_refused(up, local, tmp_path):
    local(make_site(tmp_path, tamper=True))
    with pytest.raises(RuntimeError, match="signature"):
        up.check()


def test_check_unsigned_manifest_refused(up, local, tmp_path):
    local(make_site(tmp_path, nosig=True))
    with pytest.raises(RuntimeError, match="signature"):
        up.check()


def test_check_signed_by_other_key_refused(up, local, tmp_path):
    local(make_site(tmp_path, key=bytes(range(32))))
    with pytest.raises(RuntimeError, match="signature"):
        up.check()


def test_pubkey_override_only_in_test_mode(up, monkeypatch, tmp_path):
    monkeypatch.delenv("FF_UPDATE_URL", raising=False)
    monkeypatch.setenv("FF_UPDATE_PUBKEY", PUB.hex())
    assert up.public_key() == bytes.fromhex(up.PUBLIC_KEY)


def test_mirror_fallback(up, monkeypatch, tmp_path):
    site = make_site(tmp_path)
    monkeypatch.delenv("FF_UPDATE_URL", raising=False)
    monkeypatch.setattr(up, "public_key", lambda: PUB)
    calls = []

    def fetch(url, dest=None, timeout=60):
        calls.append(url)
        if url.startswith(up.MIRRORS[0]):
            raise RuntimeError("site principal injoignable")
        return (site.parent / url.rsplit("/", 1)[1]).read_bytes()
    monkeypatch.setattr(up, "fetch", fetch)
    info = up.check()
    assert info["latest"] == "9.9.9" and info["file"]["url"].startswith(up.MIRRORS[1])
    assert any(c.startswith(up.MIRRORS[0]) for c in calls)


def test_mirror_serving_bad_signature_falls_back(up, monkeypatch, tmp_path):
    good = make_site(tmp_path)
    bad = make_site(tmp_path, tamper=True)
    monkeypatch.delenv("FF_UPDATE_URL", raising=False)
    monkeypatch.setattr(up, "public_key", lambda: PUB)

    def fetch(url, dest=None, timeout=60):
        site = bad if url.startswith(up.MIRRORS[0]) else good
        return (site.parent / url.rsplit("/", 1)[1]).read_bytes()
    monkeypatch.setattr(up, "fetch", fetch)
    assert up.check()["file"]["url"].startswith(up.MIRRORS[1])


def test_download_checks_sha(up, local, tmp_path):
    local(make_site(tmp_path))
    info = up.check()
    p = up.download(info)
    assert p.read_bytes().startswith(b"installateur factice")
    local(make_site(tmp_path, version="9.9.8", bad_sha=True))
    info = up.check()
    with pytest.raises(RuntimeError, match="empreinte"):
        up.download(info)
    assert not list(Path(p).parent.glob("FileForge-9.9.8-*"))


@pytest.mark.parametrize("a,b", [("1.2.10", "1.2.9"), ("2.0", "1.9.9"), ("1.3.0", "1.2.99"), ("1.10.0", "1.9.0")])
def test_vtuple(up, a, b):
    assert up.vtuple(a) > up.vtuple(b)
    assert up.vtuple("1.3") == up.vtuple("1.3.0")


class FakeWin:
    def __init__(self):
        self.js = []
        self.destroyed = False

    def evaluate_js(self, s):
        self.js.append(s)

    def destroy(self):
        self.destroyed = True


def states(win):
    return [json.loads(s[len("UP.show("):-1]) for s in win.js if s.startswith("UP.show(")]


def test_api_go_success(up, local, tmp_path, monkeypatch):
    local(make_site(tmp_path))
    info = up.check()
    api = up.Api(info, manual=True)
    api._win = FakeWin()
    monkeypatch.setattr(up, "install", lambda p: 0)
    api.go()
    st = states(api._win)
    assert st[-1]["mode"] == "done"
    assert json.loads(up.STATE.read_text())["installed"]["version"] == "9.9.9"


def test_api_go_install_failure_shown(up, local, tmp_path, monkeypatch):
    local(make_site(tmp_path))
    api = up.Api(up.check(), manual=True)
    api._win = FakeWin()
    monkeypatch.setattr(up, "install", lambda p: 3)
    api.go()
    assert states(api._win)[-1]["mode"] == "error"
    assert not api._busy


def test_later_snoozes(up, local, tmp_path, monkeypatch):
    local(make_site(tmp_path))
    api = up.Api(up.check(), manual=False)
    api._win = FakeWin()
    api.later()
    assert api._win.destroyed
    assert json.loads(up.STATE.read_text())["snoozed"]["version"] == "9.9.9"


def run_main(up, monkeypatch, mode):
    shown = []
    monkeypatch.setattr(up, "window", lambda info, manual: shown.append((info, manual)))
    monkeypatch.setattr(up, "error_window", lambda msg: shown.append(("error", msg)))
    monkeypatch.setattr(sys, "argv", ["updater.py", mode])
    return up.main(), shown


def test_auto_respects_snooze_and_required(up, local, tmp_path, monkeypatch):
    local(make_site(tmp_path))
    up.save_state({"snoozed": {"version": "9.9.9", "at": time.time()}})
    _, shown = run_main(up, monkeypatch, "--auto")
    assert not shown
    local(make_site(tmp_path, version="9.9.10", required=True))
    up.save_state({"snoozed": {"version": "9.9.10", "at": time.time()}})
    _, shown = run_main(up, monkeypatch, "--auto")
    assert shown and shown[0][0]["required"]


def test_auto_once_per_day(up, local, tmp_path, monkeypatch):
    local(make_site(tmp_path))
    monkeypatch.delenv("FF_UPDATE_URL")
    up.save_state({"last_check": time.time()})
    called = []
    monkeypatch.setattr(up, "check", lambda: called.append(1))
    run_main(up, monkeypatch, "--auto")
    assert not called


def test_auto_no_endless_loop_after_install(up, local, tmp_path, monkeypatch):
    """Si l'installateur publié contenait encore l'ancienne version, on ne repropose pas la même toutes les 30 min."""
    local(make_site(tmp_path))
    up.save_state({"installed": {"version": "9.9.9", "at": time.time()}})
    _, shown = run_main(up, monkeypatch, "--auto")
    assert not shown


def test_auto_up_to_date_shows_nothing(up, local, tmp_path, monkeypatch):
    local(make_site(tmp_path, version="0.0.1"))
    _, shown = run_main(up, monkeypatch, "--auto")
    assert not shown


def test_manual_up_to_date_shows_window(up, local, tmp_path, monkeypatch):
    local(make_site(tmp_path, version="0.0.1"))
    _, shown = run_main(up, monkeypatch, "--manual")
    assert shown and not shown[0][0]["newer"]


def test_manual_network_error_shows_error(up, monkeypatch, tmp_path):
    monkeypatch.setenv("FF_UPDATE_URL", str(tmp_path / "absent.json"))
    monkeypatch.setattr(up, "MANIFEST", str(tmp_path / "absent.json"))
    code, shown = run_main(up, monkeypatch, "--manual")
    assert code == 1 and shown[0][0] == "error"


def test_check_mode_prints_json_and_does_not_touch_state(up, local, tmp_path, monkeypatch, capsys):
    local(make_site(tmp_path))
    code, shown = run_main(up, monkeypatch, "--check")
    assert code == 0 and json.loads(capsys.readouterr().out)["latest"] == "9.9.9"
    assert "last_check" not in up.load_state()


def test_corrupt_state_file_ignored(up):
    up.STATE.write_text("{pas du json")
    assert up.load_state() == {}


@pytest.mark.skipif(sys.platform != "darwin", reason="installation macOS")
def test_install_mac_runs_install_command_and_cleans_up(up, tmp_path):
    z = tmp_path / "FileForge-macOS.zip"
    marker = tmp_path / "ran.txt"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("FileForge-macOS/install.command", f'#!/bin/bash\necho "$FILEFORGE_UPDATE" > "{marker}"\n')
    import tempfile
    before = set(Path(tempfile.gettempdir()).glob("FileForge-maj-*"))
    assert up.install(z) == 0
    assert marker.read_text().strip() == "1"
    assert set(Path(tempfile.gettempdir()).glob("FileForge-maj-*")) <= before, "dossier d'installation laissé dans /tmp"


def test_updater_html_escapes_notes(up):
    assert "esc(n)" in up.HTML and "esc(st.text)" in up.HTML
