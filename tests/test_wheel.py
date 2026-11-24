"""Roue : logique Python (sans fenêtre), regroupement des sélections Windows, saisie, pages HTML."""
import json
import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from conftest import load, ff, SRC, ROOT

pytest.importorskip("webview")
W = load("wheel", "ff_wheel_t")


def test_clean_label():
    assert W.clean("📄 PDF · Fusionner") == "PDF · Fusionner"
    assert W.clean("Fusionner") == "Fusionner"


def test_every_action_in_a_known_category():
    cats = {c[0] for c in W.CATS}
    for a in ff.ACTIONS:
        cid, lab, ic = W.meta(a)
        assert cid in cats and lab and ic


def test_icons_exist_in_lucide():
    lucide = (SRC / "lucide.min.js").read_text(encoding="utf-8")
    icons = {m[2] for m in W.META.values()} | {c[2] for c in W.CATS}
    missing = []
    for ic in icons:
        key = "".join(p.capitalize() for p in ic.split("-"))
        if f'"{ic}"' not in lucide and key not in lucide:
            missing.append(ic)
    assert not missing, f"icônes inconnues de Lucide : {missing}"


def test_build_main(tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.PDF"
    a.write_bytes(b"x" * 2048)
    b.write_bytes(b"x")
    st = W.build_main([str(a), str(b)], ff.available([str(a), str(b)]))
    assert st["badge"] == "PDF" and st["title"] == "2 éléments"
    assert {c["id"] for c in st["cats"]} >= {"pages"}
    assert all(c["actions"] for c in st["cats"])


def test_build_main_folder(tmp_path):
    d = tmp_path / "dossier"
    d.mkdir()
    st = W.build_main([str(d)], ff.available([str(d)]))
    assert st["subtitle"] == "Dossier"


def test_expand_folder_natural_order(tmp_path):
    for n in ("p10.png", "p2.png", ".cache", "p1.png"):
        (tmp_path / n).write_text("x")
    (tmp_path / "sub").mkdir()
    assert [Path(p).name for p in W.expand([str(tmp_path)])] == ["p1.png", "p2.png", "p10.png"]


def test_ask_hidden_keeps_spaces(monkeypatch):
    monkeypatch.setattr(W.ui, "_wait", lambda st, busy_after=True: " mot de passe ")
    assert W.ask("Mot de passe :", hidden=True) == " mot de passe "
    assert W.ask("Nom :") == "mot de passe"


def test_wait_cancel_and_close(monkeypatch):
    sent = []
    monkeypatch.setattr(W.ui, "_send", sent.append)
    for v, exc in (("__cancel__", W.ff.Cancel), ("__close__", W.Close)):
        # la réponse arrive une fois la question envoyée (comme un clic dans la roue)
        monkeypatch.setattr(W.ui, "_send", lambda st, v=v: threading.Timer(0.05, W.ui.answer, (v,)).start())
        with pytest.raises(exc):
            W.ui._wait({"mode": "ask"})


def test_take_request(tmp_path, monkeypatch):
    monkeypatch.setattr(W.tempfile, "gettempdir", lambda: str(tmp_path))
    f = tmp_path / "x.pdf"
    f.write_text("x")
    (tmp_path / "fileforge_wheel_request.json").write_text(json.dumps([str(f), str(tmp_path / "absent.pdf")]))
    assert W.take_request() == [str(f)]
    assert W.take_request() == []


def test_gather_many_processes_one_wheel(tmp_path):
    """Windows lance un processus par fichier sélectionné : une seule roue doit recevoir TOUTE la sélection."""
    n = 24
    files = []
    for i in range(n):
        p = tmp_path / f"f{i:02d}.txt"
        p.write_text("x")
        files.append(str(p))
    tmpd = tmp_path / "tmp"
    tmpd.mkdir()
    script = tmp_path / "g.py"
    script.write_text(textwrap.dedent(f"""
        import sys, json, time, random, tempfile, importlib.util
        tempfile.tempdir = {str(tmpd)!r}
        f = sys.argv[1]
        time.sleep(random.random() * 1.2)          # démarrages étalés, comme sur un PC chargé
        sys.argv = ["wheel.py"]
        spec = importlib.util.spec_from_file_location("w", {str(SRC / "wheel.py")!r})
        w = importlib.util.module_from_spec(spec); spec.loader.exec_module(w)
        print(json.dumps(w.gather([f])))
    """))
    procs = [subprocess.Popen([sys.executable, str(script), f], stdout=subprocess.PIPE, text=True) for f in files]
    outs = []
    for p in procs:
        o, _ = p.communicate(timeout=90)
        if o.strip():
            outs.append(json.loads(o.strip().splitlines()[-1]))
    assert len(outs) == 1, f"{len(outs)} roues ouvertes au lieu d'une : {[len(x) for x in outs]}"
    assert sorted(outs[0]) == sorted(files)


# ── pages HTML : JavaScript valide et données échappées
def scripts(html):
    import re
    return [m.group(1) for m in re.finditer(r"<script(?![^>]*src)[^>]*>(.*?)</script>", html, re.S)]


@pytest.mark.parametrize("page", ["wheel.html", "editor.html"])
def test_inline_js_syntax(page, tmp_path):
    node = __import__("shutil").which("node")
    if not node:
        pytest.skip("node absent")
    for i, js in enumerate(scripts((SRC / page).read_text(encoding="utf-8"))):
        f = tmp_path / f"{page}.{i}.js"
        f.write_text(js, encoding="utf-8")
        r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_updater_inline_js_syntax(tmp_path):
    node = __import__("shutil").which("node")
    if not node:
        pytest.skip("node absent")
    up = load("updater", "ff_up_js")
    for i, js in enumerate(scripts(up.HTML)):
        f = tmp_path / f"up{i}.js"
        f.write_text(js)
        r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_site_js_syntax():
    node = __import__("shutil").which("node")
    if not node:
        pytest.skip("node absent")
    for f in (ROOT / "site" / "assets").glob("*.js"):
        r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
        assert r.returncode == 0, f"{f.name}: {r.stderr}"
