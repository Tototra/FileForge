"""Batterie de tests de Ctrl+Alt+G sous Windows : vraies touches, comme un utilisateur (CI).

    python windows_hotkey.py <dossier de résultats>
L'agent installé est relancé avec FF_DEBUG=1 pour pouvoir interroger le panneau (%TEMP%\\ff_cmd.js).
"""
import ctypes, os, statistics, subprocess, sys, tempfile, time
from ctypes import wintypes
from pathlib import Path
from PIL import ImageGrab

D = Path(os.environ["LOCALAPPDATA"]) / "FileForge"
PYW = D / "venv" / "Scripts" / "pythonw.exe"
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
CMD = Path(tempfile.gettempdir()) / "ff_cmd.js"
RES = CMD.parent / "ff_cmd.out"
u = ctypes.windll.user32
fails, notes = [], []
TITLE = "FileForge-Roue"


def expect(name, cond, info=""):
    print(("OK   " if cond else "FAIL ") + name, info, flush=True)
    if not cond:
        fails.append(name)


def shot(name):
    ImageGrab.grab(all_screens=True).save(OUT / f"hk-{name}.png")


def procs(pattern):
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }"],
                       capture_output=True, text=True)
    return [l.split("|", 1) for l in r.stdout.splitlines() if "|" in l and pattern in l]


def kill(pattern):
    for pid, _ in procs(pattern):
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)


def key(vk, up=False):
    u.keybd_event(vk, 0, 2 if up else 0, 0)


def hotkey():
    for k in (0x11, 0x12, 0x47):     # Ctrl, Alt, G
        key(k)
    time.sleep(0.03)
    for k in (0x47, 0x12, 0x11):
        key(k, True)


def type_text(s):
    for ch in s:
        vk = u.VkKeyScanW(ord(ch)) & 0xFF
        key(vk); key(vk, True)
        time.sleep(0.01)


def visible_panels():
    """Fenêtres FileForge visibles (pid → hwnd)."""
    found = {}
    buf = ctypes.create_unicode_buffer(64)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        u.GetWindowTextW(hwnd, buf, 64)
        if buf.value == TITLE and u.IsWindowVisible(hwnd):
            p = wintypes.DWORD(); u.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            found[p.value] = hwnd
        return True
    u.EnumWindows(cb, 0)
    return found


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


def wait_panel(timeout=8):
    """Temps jusqu'à ce qu'un panneau soit visible ET au premier plan."""
    t = time.time()
    while time.time() - t < timeout:
        v = visible_panels()
        fg = u.GetForegroundWindow()
        if v and fg in v.values():
            return time.time() - t, v
        time.sleep(0.02)
    return None, visible_panels()


def wait_closed(timeout=5):
    t = time.time()
    while time.time() - t < timeout:
        if not visible_panels():
            return time.time() - t
        time.sleep(0.05)
    return None


def standby_ready(timeout=30):
    t = time.time()
    while time.time() - t < timeout:
        if procs("--standby"):
            time.sleep(3.5)      # le temps que la page soit chargée et l'index préparé
            return True
        time.sleep(0.3)
    return False


# ── préparation : agent relancé avec le canal de débogage
kill("hotkey_win.py"); kill("wheel.py")
time.sleep(1)
env = dict(os.environ, FF_DEBUG="1")
agent = subprocess.Popen([str(PYW), str(D / "hotkey_win.py")], env=env, cwd=str(D))
expect("agent démarré, réserve préparée", standby_ready(), "")
docs = Path(os.environ["USERPROFILE"]) / "Documents" / "Factures"
docs.mkdir(parents=True, exist_ok=True)
(docs / "Facture Free juin.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")

# 1. vitesse et premier plan, 6 essais d'affilée
times = []
for i in range(6):
    standby_ready(20)
    hotkey()
    dt, v = wait_panel()
    times.append(dt)
    if i == 0:
        time.sleep(0.6); shot("1-ouvert")
    foc = js("document.activeElement && document.activeElement.id")
    expect(f"essai {i + 1} : panneau au premier plan", dt is not None, f"{dt and round(dt, 2)} s")
    expect(f"essai {i + 1} : curseur dans le champ", foc.strip() == "fq", foc)
    key(0x1B); key(0x1B, True)              # Échap
    expect(f"essai {i + 1} : Échap ferme", wait_closed() is not None)
    time.sleep(0.4)
ok_t = [t for t in times if t]
if ok_t:
    notes.append(f"ouverture : médiane {statistics.median(ok_t):.2f} s, max {max(ok_t):.2f} s ({len(ok_t)}/6)")

# 2. on tape tout de suite après le raccourci
standby_ready(20)
hotkey()
time.sleep(0.05)
type_text("facture free")
dt, v = wait_panel()
time.sleep(1.2)
val = js("document.getElementById('fq') && document.getElementById('fq').value")
res = js("JSON.stringify(F.res.map(x => x.name))")
expect("frappe immédiate : rien de perdu", val.strip() == "facture free", repr(val))
expect("frappe immédiate : fichier trouvé", "Facture Free juin.pdf" in res, res[:120])
shot("2-frappe-immediate")
key(0x1B); key(0x1B, True); wait_closed()

# 3. second Ctrl+Alt+G : referme
standby_ready(20)
hotkey(); wait_panel()
time.sleep(0.5)
hotkey()
expect("second Ctrl+Alt+G referme", wait_closed() is not None)

# 4. depuis une autre application au premier plan (Bloc-notes)
standby_ready(20)
note = subprocess.Popen(["notepad.exe"])
time.sleep(2.5)
fg_before = u.GetForegroundWindow()
hotkey()
dt, v = wait_panel()
expect("depuis le Bloc-notes : panneau au premier plan", dt is not None, f"{dt and round(dt, 2)} s")
type_text("free")
time.sleep(0.8)
expect("depuis le Bloc-notes : la frappe va dans le panneau", js("document.getElementById('fq').value").strip() == "free")
shot("4-depuis-bloc-notes")
key(0x1B); key(0x1B, True); wait_closed()
note.kill()

# 5. appuis répétés très rapides : un seul panneau, rien ne plante
standby_ready(20)
for _ in range(5):
    hotkey(); time.sleep(0.08)
time.sleep(2.5)
n = len(visible_panels())
expect("5 appuis rapides : au plus un panneau ouvert", n <= 1, f"{n} panneau(x)")
for pid in list(visible_panels()):
    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
time.sleep(1)

# 6. clic à côté : referme
standby_ready(20)
hotkey(); dt, v = wait_panel()
u.SetCursorPos(5, 5); time.sleep(0.2)
u.mouse_event(0x0002, 0, 0, 0, 0); u.mouse_event(0x0004, 0, 0, 0, 0)
expect("clic à côté referme", wait_closed() is not None)

# 7. l'agent tient le coup et la réserve se reforme
time.sleep(4)
expect("agent toujours actif", agent.poll() is None)
expect("une seule réserve en attente", len(procs("--standby")) == 1, f"{len(procs('--standby'))}")

# 8. si la réserve a disparu (plantage), Ctrl+Alt+G marche quand même
kill("--standby"); time.sleep(0.5)
hotkey()
dt, v = wait_panel(12)
expect("sans réserve : ouverture directe", dt is not None, f"{dt and round(dt, 2)} s")
key(0x1B); key(0x1B, True); wait_closed()

agent.kill(); kill("wheel.py")
log = (D / "FileForge.log").read_text(encoding="utf-8", errors="replace") if (D / "FileForge.log").exists() else ""
expect("journal sans erreur Python", "Traceback" not in log)
(OUT / "hotkey-notes.txt").write_text("\n".join(notes), encoding="utf-8")
print("\n".join(notes))
print(f"\n{len(fails)} échec(s) : {fails}")
sys.exit(1 if fails else 0)
