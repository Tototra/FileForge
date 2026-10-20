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
EVENT_NAME = "Local\\FileForgeSearchShow"
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
VK_G = 0x47
WM_HOTKEY, WM_TIMER = 0x0312, 0x0113
RESPAWN_MS, HEALTH_MS = 2500, 30000

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.CreateMutexW.restype = wintypes.HANDLE
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


class Agent:
    def __init__(self):
        self.event = kernel32.CreateEventW(None, False, False, EVENT_NAME)   # remise à zéro automatique
        self.standby = None     # panneau chargé, caché, qui attend l'événement
        self.active = None      # panneau affiché
        self.timer = None
        self.last = 0.0

    def _spawn(self, standby):
        env = dict(os.environ, FF_AGENT_PID=str(os.getpid()))
        args = [pythonw(), str(HERE / "wheel.py"), "--search"] + (["--standby"] if standby else [])
        return subprocess.Popen(args, cwd=str(HERE), env=env, creationflags=0x08000000)

    def ensure_standby(self):
        if self.standby is None or self.standby.poll() is not None:
            self.standby = self._spawn(True)

    def schedule_standby(self, ms=RESPAWN_MS):
        self.timer = user32.SetTimer(None, 0, ms, None)

    def on_hotkey(self):
        now = time.time()
        if now - self.last < 0.25:         # rebond
            return
        self.last = now
        if self.active is not None and self.active.poll() is None:
            self.active.terminate()        # Ctrl+Alt+G une seconde fois : referme
            self.active = None
            return
        user32.AllowSetForegroundWindow(-1)  # le panneau pourra passer au premier plan
        if self.standby is not None and self.standby.poll() is None:
            kernel32.SetEvent(self.event)  # le panneau en réserve s'affiche
            self.active, self.standby = self.standby, None
        else:
            self.active = self._spawn(False)
        self.schedule_standby()            # prépare le suivant, sans gêner l'ouverture

    def run(self):
        ok = user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_G)
        log("Ctrl+Alt+G enregistré" if ok else f"Ctrl+Alt+G indisponible (déjà pris par une autre application ? erreur {ctypes.get_last_error()})")
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
                    if msg.wParam == self.timer:
                        user32.KillTimer(None, self.timer)
                        self.timer = None
                    self.ensure_standby()
            except Exception:
                log(traceback.format_exc())
        return 0


def main():
    mutex = kernel32.CreateMutexW(None, False, "Local\\FileForgeHotkeyAgent")
    if ctypes.get_last_error() == 183:     # déjà lancé
        return 0
    try:
        return Agent().run()
    finally:
        kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    sys.exit(main())
