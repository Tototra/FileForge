#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileForge — agent Windows du raccourci global Ctrl+Alt+G (panneau de recherche de fichiers).

Lancé à l'ouverture de session (clé Run de l'utilisateur), sans fenêtre.
- écoute Ctrl+Alt+G directement (RegisterHotKey) : pas de délai de l'Explorateur ;
- garde un panneau déjà chargé en réserve (wheel.py --search --standby) : il s'affiche aussitôt ;
- un second Ctrl+Alt+G referme le panneau ouvert.
"""
import ctypes, datetime, os, subprocess, sys, time, traceback
from ctypes import wintypes
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "FileForge" / "FileForge.log"
SHOW_EVENT = "Local\\FileForgeSearchShow"
TITLE = "FileForge-Recherche"          # titre de la fenêtre du panneau de recherche (wheel.py --search)
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
VK_G = 0x47
WM_HOTKEY, WM_TIMER, WM_QUIT = 0x0312, 0x0113, 0x0012
RESPAWN_MS, HEALTH_MS = 400, 30000      # la réserve suivante est préparée dès que le panneau est refermé

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
for f, r in ((kernel32.CreateEventW, wintypes.HANDLE), (kernel32.CreateMutexW, wintypes.HANDLE),
             (kernel32.OpenProcess, wintypes.HANDLE)):
    f.restype = r
user32.SetTimer.restype = ctypes.c_size_t
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]


def log(*m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] raccourci : {' '.join(map(str, m))}\n")
    except Exception:
        pass


def pythonw():
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.exists() else exe)


def visible_panel(with_hwnd=False):
    """Processus (pid) du panneau de recherche visible, ou None.
    (le Python d'un environnement virtuel tourne sous un petit lanceur : on se fie à la fenêtre, pas au pid lancé)"""
    found = []
    buf = ctypes.create_unicode_buffer(64)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            user32.GetWindowTextW(hwnd, buf, 64)
            if buf.value == TITLE:
                p = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
                found.append((p.value, hwnd))
                return False
        return True
    user32.EnumWindows(cb, 0)
    if not found:
        return None
    return found[0] if with_hwnd else found[0][0]


def bring_to_front(timeout=1.5):
    """L'agent vient de recevoir le raccourci : il a le droit de choisir la fenêtre active. Il l'exerce pour le panneau."""
    t = time.time()
    while time.time() - t < timeout:
        r = visible_panel(True)
        if r:
            pid, hwnd = r
            user32.SetForegroundWindow(hwnd)
            if user32.GetForegroundWindow() == hwnd:
                return int((time.time() - t) * 1000)
        time.sleep(0.015)
    return None


def kill_pid(pid):
    h = kernel32.OpenProcess(0x0001, False, pid)      # PROCESS_TERMINATE
    if h:
        kernel32.TerminateProcess(h, 0)
        kernel32.CloseHandle(h)


class Agent:
    def __init__(self):
        self.show = kernel32.CreateEventW(None, False, False, SHOW_EVENT)    # remise à zéro automatique
        self.standby = None     # panneau chargé, caché, qui attend le signal
        self.active = None      # panneau affiché (ou en train de s'afficher)
        self.opening_until = 0.0
        self.respawn_timer = None
        self.last = 0.0

    def _spawn(self, standby):
        env = dict(os.environ, FF_AGENT_PID=str(os.getpid()))
        args = [pythonw(), str(HERE / "wheel.py"), "--search"] + (["--standby"] if standby else [])
        # dossier de travail hors du dossier de FileForge : sinon il ne pourrait pas être supprimé à la désinstallation
        return subprocess.Popen(args, cwd=os.environ.get("TEMP") or str(Path.home()), env=env, creationflags=0x08000000)

    def ensure_standby(self):
        if self.standby is None or self.standby.poll() is not None:
            if visible_panel():
                return False              # pas pendant qu'on se sert du panneau : on réessaiera
            self.standby = self._spawn(True)
        return True

    def on_hotkey(self):
        now = time.time()
        if now - self.last < 0.25:           # rebond
            return
        self.last = now
        a = self.active
        shown = visible_panel()
        if shown:
            kill_pid(shown)                  # Ctrl+Alt+G une seconde fois : referme
            if a is not None and a.poll() is None:
                a.kill()
            self.active = None
            log("fermeture du panneau")
            return
        if a is not None and a.poll() is None and now < self.opening_until:
            return                           # en train de s'ouvrir : on n'en lance pas un deuxième
        if a is not None and a.poll() is None:
            a.kill()                         # fenêtre déjà fermée, processus qui traîne
        user32.AllowSetForegroundWindow(-1)  # le panneau pourra passer au premier plan
        self.opening_until = now + 3
        if self.standby is not None and self.standby.poll() is None:
            kernel32.SetEvent(self.show)     # le panneau en réserve s'affiche
            self.active, self.standby = self.standby, None
            ms = bring_to_front()
            log(f"ouverture (réserve), premier plan {'en ' + str(ms) + ' ms' if ms is not None else 'NON obtenu'}")
        else:
            self.active = self._spawn(False)
            ms = bring_to_front(6)
            log(f"pas de réserve : ouverture directe, premier plan {'en ' + str(ms) + ' ms' if ms is not None else 'NON obtenu'}")
        if self.respawn_timer:
            user32.KillTimer(None, self.respawn_timer)
        self.respawn_timer = user32.SetTimer(None, 0, RESPAWN_MS, None)

    def run(self):
        ok = user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_G)
        log("Ctrl+Alt+G enregistré" if ok else
            f"Ctrl+Alt+G indisponible (déjà pris par une autre application ? erreur {ctypes.get_last_error()})")
        if not ok:
            return 2
        self.ensure_standby()
        user32.SetTimer(None, 0, HEALTH_MS, None)
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            try:
                if msg.message == WM_HOTKEY:
                    self.on_hotkey()
                elif msg.message == WM_TIMER:
                    ready = self.ensure_standby()
                    if msg.wParam == self.respawn_timer and ready:
                        user32.KillTimer(None, self.respawn_timer)   # sinon le minuteur réessaie un peu plus tard
                        self.respawn_timer = None
            except Exception:
                log(traceback.format_exc())
        return 0


def main():
    mutex = kernel32.CreateMutexW(None, False, "Local\\FileForgeHotkeyAgent")
    if ctypes.get_last_error() == 183:       # déjà lancé
        return 0
    try:
        return Agent().run()
    finally:
        kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    sys.exit(main())
