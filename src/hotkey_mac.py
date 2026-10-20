#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileForge — agent macOS du raccourci global ⌃⌥G (panneau de recherche de fichiers).

Lancé à l'ouverture de session par un LaunchAgent (fr.fileforge.hotkey), sans icône dans le Dock.
Il ne fait qu'écouter le raccourci : à chaque ⌃⌥G il ouvre la roue en mode recherche seule
(`wheel.py --search`), ou la referme si elle est déjà ouverte.
Aucune autorisation d'accessibilité n'est nécessaire (API Carbon RegisterEventHotKey).
"""
import ctypes, ctypes.util, datetime, os, subprocess, sys, time, traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = Path.home() / "Library" / "Logs" / "FileForge.log"
KEY_G = 5                       # kVK_ANSI_G
MODS = 0x1000 | 0x0800          # controlKey | optionKey  →  ⌃⌥


def log(*m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] raccourci : {' '.join(map(str, m))}\n")
    except Exception:
        pass


class HotKey:
    def __init__(self, callback, keycode, mods, sig="FFSG"):
        c = self.carbon = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Carbon"))
        c.GetApplicationEventTarget.restype = ctypes.c_void_p

        class EventTypeSpec(ctypes.Structure):
            _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]

        class EventHotKeyID(ctypes.Structure):
            _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]

        HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)

        def handler(_next, _event, _data):
            try:
                callback()
            except Exception:
                log(traceback.format_exc())
            return 0

        self._cb = HANDLER(handler)            # garder une référence, sinon le rappel est libéré
        four = lambda s: (ord(s[0]) << 24) | (ord(s[1]) << 16) | (ord(s[2]) << 8) | ord(s[3])
        self._spec = EventTypeSpec(four("keyb"), 5)   # kEventHotKeyPressed
        target = ctypes.c_void_p(c.GetApplicationEventTarget())
        c.InstallEventHandler.argtypes = [ctypes.c_void_p, HANDLER, ctypes.c_uint32, ctypes.c_void_p,
                                          ctypes.c_void_p, ctypes.c_void_p]
        c.InstallEventHandler(target, self._cb, 1, ctypes.byref(self._spec), None, None)
        self.ref = ctypes.c_void_p()
        c.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, EventHotKeyID, ctypes.c_void_p,
                                          ctypes.c_uint32, ctypes.c_void_p]
        self.err = c.RegisterEventHotKey(keycode, mods, EventHotKeyID(four(sig), 1), target, 0, ctypes.byref(self.ref))


class Agent:
    def __init__(self):
        self.proc = None
        self.last = 0.0

    def on_hotkey(self):
        now = time.time()
        if now - self.last < 0.35:              # rebond / touche maintenue
            return
        self.last = now
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()               # ⌃⌥G une seconde fois : referme le panneau
            self.proc = None
            return
        env = dict(os.environ)
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + env.get("PATH", "")
        env.setdefault("LANG", "fr_FR.UTF-8")
        with open(LOG, "a") as out:
            self.proc = subprocess.Popen([sys.executable, str(HERE / "wheel.py"), "--search"],
                                         cwd=str(HERE), env=env, stdout=out, stderr=out)


def main():
    import AppKit
    from PyObjCTools import AppHelper
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)   # invisible : pas d'icône dans le Dock
    agent = Agent()
    hk = HotKey(agent.on_hotkey, KEY_G, MODS)
    log("⌃⌥G enregistré" if hk.err == 0 else f"⌃⌥G indisponible (erreur {hk.err}, déjà pris par une autre app ?)")
    # préchauffe le cache disque des modules de la roue : le premier ⌃⌥G s'ouvre plus vite
    subprocess.Popen([sys.executable, "-c", "import webview, AppKit, WebKit"], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
    AppHelper.runEventLoop(installInterrupt=True)


if __name__ == "__main__":
    main()
