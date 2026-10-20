"""Vitesse d'ouverture de la roue sous Windows (CI) : clic droit, Envoyer vers, Bureau, menu Démarrer.

    python windows_fast.py <dossier de résultats>
Tout passe par le lanceur « hotkey_win.py --open », exactement comme le clic droit de l'Explorateur.
"""
import json, os, statistics, subprocess, sys, tempfile, time
from pathlib import Path
from PIL import ImageGrab

D = Path(os.environ["LOCALAPPDATA"]) / "FileForge"
PYW = D / "venv" / "Scripts" / "pythonw.exe"
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
CMD = Path(tempfile.gettempdir()) / "ff_cmd.js"; RES = CMD.parent / "ff_cmd.out"
fails, notes = [], []


def expect(name, cond, info=""):
    print(("OK   " if cond else "FAIL ") + name, info, flush=True)
    if not cond:
        fails.append(name)


def js(code, timeout=4):
    RES.unlink(missing_ok=True); CMD.write_text(code, encoding="utf-8")
    t = time.time()
    while time.time() - t < timeout:
        if RES.exists() and not CMD.exists():
            time.sleep(0.02); return RES.read_text(encoding="utf-8")
        time.sleep(0.02)
    CMD.unlink(missing_ok=True); return "TIMEOUT"


def procs(pattern):
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | ForEach-Object { \"$($_.ProcessId)|$($_.WorkingSetSize)|$($_.CommandLine)\" }"],
                       capture_output=True, text=True)
    return [l.split("|", 2) for l in r.stdout.splitlines() if l.count("|") >= 2 and pattern in l]


def kill(pattern):
    for pid, _, _ in procs(pattern):
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)


def wait_ready(n=2, timeout=40, pattern="--standby"):
    """n réserves prêtes (vrai Python, pas son lanceur) ; n=1 : la roue en réserve."""
    if n == 1:
        pattern = "--standby-wheel"
    t = time.time()
    while time.time() - t < timeout:
        if len([p for p in procs(pattern) if "\\python\\cpython" in p[2]]) >= n:
            time.sleep(4); return True
        time.sleep(0.3)
    return False


def open_and_time(files, want_mode="main", timeout=15):
    t0 = time.time()
    subprocess.Popen([str(PYW), str(D / "hotkey_win.py"), "--open", *map(str, files)])
    while time.time() - t0 < timeout:
        if js("mode", timeout=0.5).strip() == want_mode:
            return time.time() - t0
        time.sleep(0.02)
    return None


def close():
    js("api('__close__'); true", timeout=2); time.sleep(1.2)


kill("hotkey_win.py"); kill("wheel.py"); time.sleep(1)
env = dict(os.environ, FF_DEBUG="1")
subprocess.Popen([str(PYW), str(D / "hotkey_win.py")], env=env, cwd=tempfile.gettempdir())
expect("agent démarré, roue et recherche en réserve", wait_ready(2))
mem = sum(int(p[1]) for p in procs("--standby") if "\\python\\cpython" in p[2]) / 2**20
notes.append(f"mémoire des deux réserves (Python) : {mem:.0f} Mo")

docs = Path(os.environ["USERPROFILE"]) / "Documents" / "Vitesse"
docs.mkdir(parents=True, exist_ok=True)
import pymupdf
d = pymupdf.open(); d.new_page().insert_text((72, 72), "Devis"); d.save(docs / "Devis cuisine.pdf")
from PIL import Image
Image.new("RGB", (400, 300), "teal").save(docs / "Plan cuisine.png")

# 1. clic droit sur un fichier, 6 fois
times = []
for i in range(6):
    wait_ready(1, 20)
    dt = open_and_time([docs / "Devis cuisine.pdf"])
    title = js("S && S.title").strip()
    expect(f"clic droit {i + 1} : roue sur le fichier", dt is not None and title == "Devis cuisine.pdf", f"{dt and round(dt, 2)} s, {title!r}")
    if dt:
        times.append(dt)
    if i == 0:
        time.sleep(0.6); ImageGrab.grab(all_screens=True).save(OUT / "fast-1-clic-droit.png")
    close()
if times:
    notes.append(f"clic droit → roue prête : médiane {statistics.median(times):.2f} s, max {max(times):.2f} s")

# 2. clic droit sur deux fichiers (Windows lance un lanceur par fichier, en même temps)
wait_ready(1, 20)
t0 = time.time()
for f in ("Devis cuisine.pdf", "Plan cuisine.png"):
    subprocess.Popen([str(PYW), str(D / "hotkey_win.py"), "--open", str(docs / f)])
dt = None
while time.time() - t0 < 15:
    if js("mode", timeout=0.5).strip() == "main":
        dt = time.time() - t0; break
    time.sleep(0.02)
title = js("S && S.title").strip()
expect("deux fichiers → une seule roue avec les deux", title == "2 éléments", f"{dt and round(dt, 2)} s, {title!r}")
close()

# 3. sans fichier (menu Démarrer, Bureau) : zone de dépôt
wait_ready(1, 20)
dt = open_and_time([], "drop")
expect("sans fichier → zone de dépôt", dt is not None, f"{dt and round(dt, 2)} s")
close()

# 4. l'agent est arrêté : le lanceur ouvre la roue lui-même
kill("hotkey_win.py"); time.sleep(1)
dt = open_and_time([docs / "Devis cuisine.pdf"], timeout=25)
expect("sans agent → la roue s'ouvre quand même", dt is not None, f"{dt and round(dt, 2)} s")
notes.append(f"sans agent (secours) : {dt and round(dt, 2)} s")
close()
kill("wheel.py")

print("\n".join(notes))
(OUT / "fast-notes.txt").write_text("\n".join(notes), encoding="utf-8")
print(f"\n{len(fails)} échec(s) : {fails}")
sys.exit(1 if fails else 0)
