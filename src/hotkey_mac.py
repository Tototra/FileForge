#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileForge — agent macOS du raccourci global ⌃⌥G (panneau de recherche de fichiers).

Lancé à l'ouverture de session par un LaunchAgent (fr.fileforge.hotkey), sans icône dans le Dock.
Il ne fait qu'écouter le raccourci : à chaque ⌃⌥G il ouvre la roue en mode recherche seule
(`wheel.py --search`), ou la referme si elle est déjà ouverte.
Aucune autorisation d'accessibilité n'est nécessaire (API Carbon RegisterEventHotKey).
"""
import threading, ctypes, ctypes.util, datetime, os, subprocess, sys, time, traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = Path.home() / "Library" / "Logs" / "FileForge.log"
KEY_G, KEY_F = 5, 3              # kVK_ANSI_G, kVK_ANSI_F
MODS = 0x1000 | 0x0800          # controlKey | optionKey  →  ⌃⌥


def log(*m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] raccourci : {' '.join(map(str, m))}\n")
    except Exception:
        pass


class HotKeys:
    """Raccourcis globaux Carbon (aucune autorisation d'accessibilité nécessaire)."""

    def __init__(self):
        c = self.carbon = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Carbon"))
        c.GetApplicationEventTarget.restype = ctypes.c_void_p

        class EventTypeSpec(ctypes.Structure):
            _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]

        class EventHotKeyID(ctypes.Structure):
            _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]
        self.EventHotKeyID = EventHotKeyID
        HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
        self.four = lambda s: (ord(s[0]) << 24) | (ord(s[1]) << 16) | (ord(s[2]) << 8) | ord(s[3])
        self.callbacks = {}
        c.GetEventParameter.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                        ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p]

        def handler(_next, event, _data):
            try:
                hid = EventHotKeyID()
                c.GetEventParameter(event, self.four("----"), self.four("hkid"), None,
                                    ctypes.sizeof(hid), None, ctypes.byref(hid))
                cb = self.callbacks.get(hid.id)
                if cb:
                    cb()
            except Exception:
                log(traceback.format_exc())
            return 0

        self._cb = HANDLER(handler)            # garder une référence, sinon le rappel est libéré
        self._spec = EventTypeSpec(self.four("keyb"), 5)   # kEventHotKeyPressed
        self.target = ctypes.c_void_p(c.GetApplicationEventTarget())
        c.InstallEventHandler.argtypes = [ctypes.c_void_p, HANDLER, ctypes.c_uint32, ctypes.c_void_p,
                                          ctypes.c_void_p, ctypes.c_void_p]
        c.InstallEventHandler(self.target, self._cb, 1, ctypes.byref(self._spec), None, None)
        c.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, EventHotKeyID, ctypes.c_void_p,
                                          ctypes.c_uint32, ctypes.c_void_p]
        self.refs = []

    def register(self, hid, keycode, mods, callback):
        ref = ctypes.c_void_p()
        err = self.carbon.RegisterEventHotKey(keycode, mods, self.EventHotKeyID(self.four("FFHK"), hid), self.target, 0,
                                              ctypes.byref(ref))
        if err == 0:
            self.callbacks[hid] = callback
            self.refs.append(ref)
        return err


FINDER_SELECTION = """
tell application "Finder"
    set out to ""
    repeat with a in (selection as alias list)
        set out to out & POSIX path of a & linefeed
    end repeat
end tell
return out
"""


class Agent:
    def __init__(self):
        self.proc = None
        self.last = 0.0
        self.script = None

    def env(self):
        env = dict(os.environ)
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + env.get("PATH", "")
        env.setdefault("LANG", "fr_FR.UTF-8")
        return env

    def launch(self, args):
        with open(LOG, "a") as out:
            return subprocess.Popen([sys.executable, str(HERE / "wheel.py")] + args,
                                    cwd=str(HERE), env=self.env(), stdout=out, stderr=out)

    def on_search(self):
        now = time.time()
        if now - self.last < 0.35:              # rebond / touche maintenue
            return
        self.last = now
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()               # ⌃⌥G une seconde fois : referme le panneau
            self.proc = None
            return
        self.proc = self.launch(["--search"])

    def finder_selection(self):
        """Sélection du Finder lue dans ce processus (script compilé une fois) : bien plus rapide qu'osascript."""
        import Foundation
        if self.script is None:
            self.script = Foundation.NSAppleScript.alloc().initWithSource_(FINDER_SELECTION)
            self.script.compileAndReturnError_(None)
        res, err = self.script.executeAndReturnError_(None)
        if err or res is None:
            return []
        paths = [p.rstrip("/") for p in (res.stringValue() or "").splitlines() if p.strip()]
        return [p for p in paths if not p.endswith(".app") and os.path.exists(p)]

    def on_wheel(self):
        t = time.time()
        try:
            files = self.finder_selection()
        except Exception as e:
            files = []
            log(f"sélection du Finder illisible : {e}")
        self.launch(files or ["--no-selection"])
        log(f"⌃⌥F : {len(files)} fichier(s), sélection lue en {int((time.time() - t) * 1000)} ms")


def update_loop(agent):
    """Toutes les 6 h (et 2 min après le démarrage) : updater.py --auto, qui vérifie au plus une fois par jour.
    Nouvelle session : l'installation arrête cet agent, la fenêtre de mise à jour doit lui survivre."""
    time.sleep(120)
    while True:
        try:
            if (HERE / "updater.py").exists():
                with open(LOG, "a") as out:
                    subprocess.Popen([sys.executable, str(HERE / "updater.py"), "--auto"], cwd=str(HERE), env=agent.env(),
                                     stdout=out, stderr=out, start_new_session=True)
        except Exception as e:
            log(f"mise à jour : {e}")
        time.sleep(6 * 3600)


def main():
    import AppKit
    from PyObjCTools import AppHelper
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)   # invisible : pas d'icône dans le Dock
    agent = Agent()
    hk = HotKeys()
    for hid, key, name, cb in ((1, KEY_G, "⌃⌥G", agent.on_search), (2, KEY_F, "⌃⌥F", agent.on_wheel)):
        err = hk.register(hid, key, MODS, cb)
        log(f"{name} enregistré" if err == 0 else f"{name} indisponible (erreur {err}, déjà pris par une autre app ?)")
    # préchauffe le cache disque des modules de la roue : la première ouverture est plus rapide
    subprocess.Popen([sys.executable, "-c", "import webview, AppKit, WebKit, pymupdf"], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
    threading.Thread(target=update_loop, args=(agent,), daemon=True).start()
    AppHelper.runEventLoop(installInterrupt=True)


if __name__ == "__main__":
    main()
