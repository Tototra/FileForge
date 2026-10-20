"""Pilote la vraie roue installée sous Windows et prend des captures d'écran (CI).

    python windows_ui.py <dossier de résultats>
La roue est lancée avec FF_DEBUG=1 : elle exécute le JavaScript déposé dans %TEMP%\\ff_cmd.js.
"""
import ctypes, json, os, subprocess, sys, tempfile, time
from pathlib import Path
from PIL import ImageGrab

D = Path(os.environ["LOCALAPPDATA"]) / "FileForge"
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
CMD = Path(tempfile.gettempdir()) / "ff_cmd.js"
RES = CMD.parent / "ff_cmd.out"
SAMPLES = Path(os.environ.get("TEMP", ".")) / "Mes documents FileForge"
SAMPLES.mkdir(exist_ok=True)
fails = []

import pymupdf
d = pymupdf.open()
for i in range(4):
    d.new_page().insert_text((72, 100), f"Page {i + 1}", fontsize=20)
PDF = SAMPLES / "Rapport annuel été.pdf"
d.save(PDF)
from PIL import Image
Image.new("RGB", (800, 600), (40, 120, 200)).save(SAMPLES / "photo vacances.jpg")


def js(code, settle=0.9, timeout=15):
    RES.unlink(missing_ok=True)
    CMD.write_text(code, encoding="utf-8")
    t = time.time()
    while time.time() - t < timeout:
        if RES.exists() and not CMD.exists():
            time.sleep(0.05)
            r = RES.read_text(encoding="utf-8")
            time.sleep(settle)
            return r
        time.sleep(0.1)
    return "TIMEOUT"


def shot(name):
    ImageGrab.grab(all_screens=True).save(OUT / f"{name}.png")
    print("capture", name)


def expect(name, cond, info=""):
    print(("OK   " if cond else "FAIL ") + name, info)
    if not cond:
        fails.append(name)


def launch(*files):
    ctypes.windll.user32.SetCursorPos(700, 420)
    env = dict(os.environ, FF_DEBUG="1")
    p = subprocess.Popen([str(D / "venv" / "Scripts" / "pythonw.exe"), str(D / "wheel.py"), *map(str, files)], env=env)
    t = time.time()
    while time.time() - t < 40:  # attend que la roue réponde
        if js("document.querySelector('.hub') ? 'pret' : 'non'", settle=0, timeout=3) == "pret":
            time.sleep(1.2)
            return p
        time.sleep(0.5)
    return p


def mode():
    return js("mode", settle=0)


# fond réaliste : une fenêtre de l'Explorateur derrière la roue
subprocess.Popen(["explorer.exe", str(SAMPLES)])
time.sleep(4)
shot("00-bureau")

# 1. roue principale sur un PDF
p = launch(PDF)
expect("roue affichée", mode() == "main", mode())
bg = js("document.documentElement.classList.contains('backdrop')", settle=0)
expect("fond capturé (fausse transparence)", bg == "True", bg)
shot("01-roue-pdf")
for i, name in [(0, "convertir"), (2, "pages"), (5, "securite")]:
    js(f"catItems[{i}] && catItems[{i}]._p.dispatchEvent(new MouseEvent('mouseenter')); true")
    shot(f"02-categorie-{i}-{name}")
js("fanItems[0] && fanItems[0]._p.dispatchEvent(new MouseEvent('mouseenter')); true")
shot("03-action-survolee")

# 2. vraie action de bout en bout : extraire des pages, avec une saisie invalide d'abord
js("api('pdf_extract'); true", settle=1.5)
expect("demande des pages", mode() == "ask", mode())
shot("04-demande-pages")
js("document.getElementById('in').value='9'; document.getElementById('ok').click(); true", settle=1.5)
q = js("document.querySelector('.q').textContent", settle=0)
expect("saisie invalide redemandée", mode() == "ask" and "⚠" in q, q[:80])
shot("05-saisie-invalide")
js("document.getElementById('in').value='2-3'; document.getElementById('ok').click(); true", settle=3)
expect("action terminée", mode() == "done", mode())
shot("06-termine")
expect("fichier créé", any(SAMPLES.glob("*extrait*.pdf")), [x.name for x in SAMPLES.iterdir()])

# 3. états visuels restants
js("FF.show({mode:'busy',text:'Compression de la vidéo…'}); true", settle=1.2)
shot("07-en-cours")
js("FF.show({mode:'error',text:'LibreOffice n\\'a pas pu convertir « Séance 1.pptx ».',items:['Retour','Journal','Fermer']}); true", settle=1.2)
shot("08-erreur")
js("FF.show({mode:'choice',prompt:'Convertir en :',items:['JPG','PNG','WEBP','HEIC','AVIF'],default:'PNG'}); true", settle=1.2)
shot("09-choix")
js("api('__close__'); true", settle=0)
try:
    p.wait(10)
    expect("la roue se ferme", True)
except subprocess.TimeoutExpired:
    expect("la roue se ferme", False)
    p.kill()

# 4. plusieurs fichiers
p = launch(PDF, SAMPLES / "photo vacances.jpg")
expect("roue multi-fichiers", mode() == "main", js("S && S.title", settle=0))
shot("10-roue-deux-fichiers")
js("api('__close__'); true", settle=0)
time.sleep(2)

# 5. sans fichier : zone de dépôt
p = launch()
expect("zone de dépôt", mode() == "drop", mode())
shot("11-depot")
js("api('__close__'); true", settle=0)
time.sleep(2)
for q in (p,):
    if q.poll() is None:
        q.kill()

log = D / "FileForge.log"
txt = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
(OUT / "FileForge.log").write_text(txt, encoding="utf-8")
expect("aucune erreur Python dans le journal", "Traceback" not in txt)
print(f"\n{len(fails)} échec(s) : {fails}")
sys.exit(1 if fails else 0)
