"""Ctrl+Alt+F sous Windows : lecture de la sélection de l'Explorateur et ouverture de la roue dessus (CI).

    python windows_selection.py <dossier de résultats>
On sélectionne un fichier dans une vraie fenêtre de l'Explorateur (par l'API du Shell), puis on appelle
la fonction de l'agent qui gère Ctrl+Alt+F, exactement comme lors d'un appui.
"""
import ctypes, importlib.util, os, subprocess, sys, tempfile, time
from pathlib import Path
from PIL import ImageGrab

D = Path(os.environ["LOCALAPPDATA"]) / "FileForge"
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
CMD = Path(tempfile.gettempdir()) / "ff_cmd.js"; RES = CMD.parent / "ff_cmd.out"
fails = []


def expect(name, cond, info=""):
    print(("OK   " if cond else "FAIL ") + name, info, flush=True)
    if not cond:
        fails.append(name)


def js(code, timeout=6):
    RES.unlink(missing_ok=True); CMD.write_text(code, encoding="utf-8")
    t = time.time()
    while time.time() - t < timeout:
        if RES.exists() and not CMD.exists():
            time.sleep(0.05); return RES.read_text(encoding="utf-8")
        time.sleep(0.05)
    CMD.unlink(missing_ok=True); return "TIMEOUT"


sp = importlib.util.spec_from_file_location("hk", D / "hotkey_win.py")
hk = importlib.util.module_from_spec(sp); sp.loader.exec_module(hk)
import pythoncom, win32com.client
pythoncom.CoInitialize()

folder = Path(os.environ["USERPROFILE"]) / "Documents" / "Sélection test"
folder.mkdir(parents=True, exist_ok=True)
for n in ("Contrat de location.pdf", "Photo identité.jpg", "Notes réunion.txt"):
    (folder / n).write_bytes(b"x" * 100)
import pymupdf
d = pymupdf.open(); d.new_page().insert_text((72, 72), "Contrat"); d.save(folder / "Contrat de location.pdf")

subprocess.Popen(["explorer.exe", str(folder)])
shell = win32com.client.Dispatch("Shell.Application")
w = None
for _ in range(40):
    time.sleep(0.25)
    for x in shell.Windows():
        try:
            if Path(x.Document.Folder.Self.Path) == folder:
                w = x
        except Exception:
            pass
    if w:
        break
expect("fenêtre de l'Explorateur ouverte", w is not None)
hwnd = int(w.HWND)
time.sleep(1)


def select(names):
    for i, n in enumerate(names):
        w.Document.SelectItem(w.Document.Folder.ParseName(n), (1 | 4 | 8 | 16) if i == 0 else 1)   # sélectionne (+ désélectionne le reste au 1er)
    time.sleep(0.4)


# 1. un fichier
select(["Contrat de location.pdf"])
sel = hk.explorer_selection(hwnd)
expect("un fichier sélectionné → lu", [Path(p).name for p in sel] == ["Contrat de location.pdf"], sel)
# 2. plusieurs fichiers
select(["Contrat de location.pdf", "Photo identité.jpg"])
sel = hk.explorer_selection(hwnd)
expect("deux fichiers sélectionnés → lus", sorted(Path(p).name for p in sel) == ["Contrat de location.pdf", "Photo identité.jpg"], sel)
# 3. Windows 11 : un second onglet sur un autre dossier ne doit pas brouiller la lecture
tabs = sum(1 for x in shell.Windows() if int(x.HWND) == hwnd)
print(f"onglets dans la fenêtre : {tabs}")

# 4. l'agent lance la roue sur la sélection : temps jusqu'à la roue prête, et bon fichier affiché
select(["Contrat de location.pdf"])
ctypes.windll.user32.SetForegroundWindow(hwnd); time.sleep(0.5)
ag = hk.Agent()
os.environ["FF_DEBUG"] = "1"
t0 = time.time()
orig = hk.explorer_selection
hk.explorer_selection = lambda fg=None: orig(hwnd)      # comme si la fenêtre était au premier plan à l'appui
ag.on_wheel_hotkey()
ready = None
while time.time() - t0 < 20:
    if js("mode", timeout=1) == "main":
        ready = time.time() - t0; break
    time.sleep(0.1)
title = js("S && S.title")
expect("Ctrl+Alt+F : la roue s'ouvre sur le fichier", ready is not None and title.strip() == "Contrat de location.pdf",
       f"{ready and round(ready, 2)} s, {title!r}")
time.sleep(0.8)
ImageGrab.grab(all_screens=True).save(OUT / "sel-1-roue.png")
js("api('__close__'); true", timeout=2)
time.sleep(1)
# 5. rien de sélectionné : zone de dépôt (comportement voulu)
notes = w.Document.Folder.ParseName("Notes réunion.txt")
w.Document.SelectItem(notes, 1 | 4)     # ne garde que « Notes réunion »…
w.Document.SelectItem(notes, 0)         # …puis le désélectionne : plus rien de sélectionné
time.sleep(0.4)
sel = hk.explorer_selection(hwnd)
expect("aucune sélection → liste vide", sel == [], sel)
print(f"\n{len(fails)} échec(s) : {fails}")
sys.exit(1 if fails else 0)
