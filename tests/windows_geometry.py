"""La roue et la recherche tiennent-elles entièrement à l'écran ? (CI Windows)

    python windows_geometry.py <dossier de résultats>

Pour chaque taille d'écran (vraie résolution changée quand le pilote le permet, sinon zone utile simulée
avec FF_WORKAREA) et chaque position de la souris (centre, coins, bords) :
  • la fenêtre de la roue est entièrement dans la zone utile du moniteur (barre des tâches exclue) ;
  • tout le dessin (anneau, catégories ouvertes, éventail des actions, étiquettes) est dans la fenêtre ;
  • une capture est prise.
"""
import ctypes, json, os, subprocess, sys, tempfile, time
from ctypes import wintypes
from pathlib import Path
from PIL import ImageGrab

ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))   # coordonnées physiques, comme la roue
u = ctypes.windll.user32
D = Path(os.environ["LOCALAPPDATA"]) / "FileForge"
PYW = D / "venv" / "Scripts" / "pythonw.exe"
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
CMD = Path(tempfile.gettempdir()) / "ff_cmd.js"
RES = CMD.parent / "ff_cmd.out"
fails, rows = [], []

import pymupdf
SAMPLE = Path(tempfile.gettempdir()) / "Géométrie test.pdf"
d = pymupdf.open(); d.new_page().insert_text((72, 100), "test", fontsize=20); d.save(SAMPLE)


def expect(name, cond, info=""):
    print(("OK   " if cond else "FAIL ") + name, info, flush=True)
    if not cond:
        fails.append(f"{name} {info}")


def js(code, timeout=8):
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


def find_window(title):
    buf, found = ctypes.create_unicode_buffer(64), []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        u.GetWindowTextW(h, buf, 64)
        if buf.value == title and u.IsWindowVisible(h):
            found.append(h)
        return True
    u.EnumWindows(cb, 0)
    return found[0] if found else None


def rect(h):
    r = wintypes.RECT(); u.GetWindowRect(h, ctypes.byref(r)); return r.left, r.top, r.right, r.bottom


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def work_area(x, y):
    mon = u.MonitorFromPoint(wintypes.POINT(x, y), 2)
    mi = MONITORINFO(); mi.cbSize = ctypes.sizeof(mi); u.GetMonitorInfoW(mon, ctypes.byref(mi))
    w = mi.rcWork
    return w.left, w.top, w.right, w.bottom


def kill_all():
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*wheel.py*' -or "
                    "$_.CommandLine -like '*hotkey_win.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
                   capture_output=True)


class DEVMODE(ctypes.Structure):
    _fields_ = [("dmDeviceName", ctypes.c_wchar * 32), ("dmSpecVersion", wintypes.WORD), ("dmDriverVersion", wintypes.WORD),
                ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD), ("dmFields", wintypes.DWORD),
                ("dmPositionX", ctypes.c_long), ("dmPositionY", ctypes.c_long), ("dmDisplayOrientation", wintypes.DWORD),
                ("dmDisplayFixedOutput", wintypes.DWORD), ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
                ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short),
                ("dmFormName", ctypes.c_wchar * 32), ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD),
                ("dmPelsWidth", wintypes.DWORD), ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD),
                ("dmDisplayFrequency", wintypes.DWORD), ("rest", ctypes.c_byte * 64)]


def resolutions():
    """Résolutions que le pilote d'affichage accepte."""
    out, i = set(), 0
    dm = DEVMODE(); dm.dmSize = ctypes.sizeof(DEVMODE) - 64
    while u.EnumDisplaySettingsW(None, i, ctypes.byref(dm)):
        out.add((dm.dmPelsWidth, dm.dmPelsHeight)); i += 1
    return out


def set_resolution(w, h):
    dm = DEVMODE(); dm.dmSize = ctypes.sizeof(DEVMODE) - 64
    u.EnumDisplaySettingsW(None, -1, ctypes.byref(dm))
    dm.dmPelsWidth, dm.dmPelsHeight, dm.dmFields = w, h, 0x00080000 | 0x00100000
    ok = u.ChangeDisplaySettingsW(ctypes.byref(dm), 0) == 0
    time.sleep(2.5)
    return ok


def screen():
    return u.GetSystemMetrics(0), u.GetSystemMetrics(1)


def open_wheel(env_extra, cursor):
    kill_all(); time.sleep(0.4)
    u.SetCursorPos(*cursor)
    env = dict(os.environ, FF_DEBUG="1", **env_extra)
    p = subprocess.Popen([str(PYW), str(D / "wheel.py"), "--direct", str(SAMPLE)], env=env)
    t = time.time()
    while time.time() - t < 40:
        if js("document.querySelector('.hub') ? 'pret' : 'non'", 3) == "pret" and find_window("FileForge-Roue"):
            time.sleep(0.6)
            return p
        time.sleep(0.3)
    return p


def check(label, env_extra, cursor):
    open_wheel(env_extra, cursor)
    h = find_window("FileForge-Roue")
    expect(f"{label} : roue affichée", h is not None)
    if not h:
        return
    x0, y0, x1, y1 = rect(h)
    wa = work_area(*cursor)
    inside = x0 >= wa[0] - 1 and y0 >= wa[1] - 1 and x1 <= wa[2] + 1 and y1 <= wa[3] + 1
    expect(f"{label} : fenêtre dans la zone utile", inside, f"fenêtre {(x0, y0, x1, y1)} zone {wa}")
    worst = None
    try:
        ncat = int(js("catItems.length"))
    except ValueError:
        ncat = 0
    for c in [-1] + list(range(ncat)):
        if c >= 0:
            js(f"openCat({c}); true"); time.sleep(0.45)
        b = js("FF.bounds()")
        try:
            b = json.loads(b)
        except ValueError:
            expect(f"{label} : mesure du dessin", False, b); return
        over = max(-b["x0"], -b["y0"], b["x1"] - b["w"], b["y1"] - b["h"])
        if worst is None or over > worst[0]:
            worst = (over, c, b)
    expect(f"{label} : tout le dessin est visible (catégories ouvertes une à une)", worst[0] <= 1.5,
           f"débord max {worst[0]:.1f} px (catégorie {worst[1]}) {worst[2]}")
    rows.append(f"{label:38} fenêtre {x1 - x0}×{y1 - y0} à ({x0},{y0}) · zone {wa} · zoom {worst[2].get('zoom')} · débord {worst[0]:.1f}")
    js(f"openCat({max(0, ncat - 1)}); true"); time.sleep(0.4)
    ImageGrab.grab(all_screens=True).save(OUT / f"geo-{label.replace(' ', '_').replace('×', 'x')}.png")


def cursors():
    w, h = screen()
    return {"centre": (w // 2, h // 2), "coin haut-gauche": (3, 3), "coin bas-droit": (w - 4, h - 4),
            "bord droit": (w - 4, h // 2), "bord bas": (w // 2, h - 4)}


# 1. résolution d'origine + zones utiles simulées (portables, mise à l'échelle 125–175 %)
base = screen()
print("écran", base, "· résolutions possibles :", sorted(resolutions()))
for wa in ["", "1366x728", "1280x680", "1097x617", "1024x700", "800x560"]:
    for name, pos in cursors().items():
        if wa and name not in ("centre", "coin bas-droit", "coin haut-gauche"):
            continue
        check(f"{wa or 'réel %dx%d' % base} {name}", {"FF_WORKAREA": wa} if wa else {}, pos)

# 2. vraies résolutions, si le pilote d'affichage le permet
avail = resolutions()
for res in [(1280, 720), (1366, 768), (1024, 768), (800, 600), (1920, 1080)]:
    if res not in avail or res == base:
        continue
    if not set_resolution(*res):
        print("résolution refusée", res); continue
    for name, pos in cursors().items():
        check(f"écran {res[0]}x{res[1]} {name}", {}, pos)
if screen() != base:
    set_resolution(*base)

# 3. la recherche (Ctrl+Alt+G) aussi
kill_all(); time.sleep(0.4)
u.SetCursorPos(*cursors()["coin bas-droit"])
p = subprocess.Popen([str(PYW), str(D / "wheel.py"), "--search"], env=dict(os.environ, FF_DEBUG="1"))
t = time.time()
while time.time() - t < 30 and not find_window("FileForge-Recherche"):
    time.sleep(0.3)
time.sleep(1.5)
h = find_window("FileForge-Recherche")
expect("recherche affichée", h is not None)
if h:
    x0, y0, x1, y1 = rect(h); wa = work_area(x0 + 5, y0 + 5)
    expect("recherche dans la zone utile", x0 >= wa[0] - 1 and y0 >= wa[1] - 1 and x1 <= wa[2] + 1 and y1 <= wa[3] + 1,
           f"{(x0, y0, x1, y1)} zone {wa}")
    ImageGrab.grab(all_screens=True).save(OUT / "geo-recherche.png")
kill_all()

(OUT / "geometry.txt").write_text("\n".join(rows + [""] + [f"ÉCHEC {f}" for f in fails]), encoding="utf-8")
print("\n".join(rows))
print(f"\n{len(fails)} échec(s)")
sys.exit(1 if fails else 0)
