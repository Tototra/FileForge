"""Une action complète dans la vraie roue (macOS / Windows) : ouverture sur un PDF, choix de l'action, réponses aux
questions, écran « Terminé », fichier produit vérifié.

    .venv/bin/python tests/gui_wheel_mac.py
"""
import json, os, subprocess, sys, tempfile, time
from pathlib import Path

import pymupdf

SRC = Path(__file__).resolve().parent.parent / "src"
T = Path(tempfile.mkdtemp(prefix="ff-roue-"))
CMD, RES = Path(tempfile.gettempdir()) / "ff_cmd.js", Path(tempfile.gettempdir()) / "ff_cmd.out"
fails = []


def expect(name, cond, info=""):
    print(("OK   " if cond else "FAIL ") + name, info, flush=True)
    if not cond:
        fails.append(name)


def js(code, timeout=6):
    RES.unlink(missing_ok=True)
    CMD.write_text(code, encoding="utf-8")
    t = time.time()
    while time.time() - t < timeout:
        if RES.exists() and not CMD.exists():
            time.sleep(0.05)
            return RES.read_text(encoding="utf-8")
        time.sleep(0.05)
    CMD.unlink(missing_ok=True)
    return "TIMEOUT"


def wait_mode(want, timeout=30):
    t = time.time()
    while time.time() - t < timeout:
        if js("mode", 1).strip() == want:
            return True
        time.sleep(0.1)
    return False


def state():
    return json.loads(js("JSON.stringify(window.__st || null)") or "null")


d = pymupdf.open()
for i in range(3):
    d.new_page().insert_text((72, 100), f"Page {i + 1} - essai roue", fontsize=14)
pdf = T / "Essai roue.pdf"
d.save(pdf)

# la roue enregistre chaque état reçu (pour que le test lise les questions)
p = subprocess.Popen([sys.executable, str(SRC / "wheel.py"), str(pdf)], env=dict(os.environ, FF_DEBUG="1"))
try:
    expect("roue ouverte sur le PDF", wait_mode("main"))
    time.sleep(0.8)                 # fin de l'animation d'ouverture (un humain ne clique pas plus vite)
    js("(function(){ const o = FF.show; FF.show = function(st){ window.__st = st; return o.apply(this, arguments) }; return true })()")
    # 1. Pivoter : question « Rotation » puis « Pages »
    js("api('pdf_rotate'); true")
    expect("question « Rotation »", wait_mode("choice"))
    js("api('90° vers la droite'); true")
    expect("question « Pages à pivoter »", wait_mode("ask"))
    js("api('2'); true")
    expect("écran « Terminé »", wait_mode("done"))
    out = T / "Essai roue_pivoté.pdf"
    expect("fichier pivoté créé", out.exists() and [pg.rotation for pg in pymupdf.open(out)] == [0, 90, 0])
    # 2. « Retour » puis une action qui échoue proprement (plage invalide redemandée)
    js("api('Retour'); true")
    expect("retour à la roue", wait_mode("main"))
    js("api('pdf_extract'); true")
    expect("question « Pages à extraire »", wait_mode("ask"))
    js("api('99'); true")
    time.sleep(0.6)
    st = state() or {}
    expect("saisie invalide : redemandée avec explication", js("mode", 1).strip() == "ask" and "⚠" in (st.get("prompt") or ""),
           (st.get("prompt") or "")[:80])
    js("api('1, 3'); true")
    expect("extraction terminée", wait_mode("done"))
    ex = T / "Essai roue_extrait.pdf"
    expect("pages 1 et 3 extraites", ex.exists() and pymupdf.open(ex).page_count == 2)
    # 3. Annuler une question ferme proprement l'action
    js("api('Retour'); true")
    wait_mode("main")
    js("api('pdf_protect'); true")
    expect("question « Mot de passe »", wait_mode("ask"))
    js("api('__cancel__'); true")
    expect("annulation : retour à la roue", wait_mode("main"))
    js("api('__close__'); true")
    try:
        p.wait(8)
        expect("la roue se ferme", True)
    except subprocess.TimeoutExpired:
        expect("la roue se ferme", False)
finally:
    if p.poll() is None:
        p.kill()
print(f"\n{len(fails)} échec(s) : {fails}")
sys.exit(1 if fails else 0)
