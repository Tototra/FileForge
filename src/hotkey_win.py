#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileForge — agent Windows du raccourci global Ctrl+Alt+G (panneau de recherche de fichiers).

Lancé à l'ouverture de session (clé Run de l'utilisateur), sans fenêtre.
- écoute Ctrl+Alt+G directement (RegisterHotKey) : pas de délai de l'Explorateur ;
- garde un panneau déjà chargé en réserve (wheel.py --search --standby) : il s'affiche aussitôt ;
- retient ce qui est tapé entre l'appui et l'instant où le champ est prêt, puis le recopie dedans :
  aucune lettre perdue, rien n'arrive dans l'application d'avant ;
- un second Ctrl+Alt+G referme le panneau ouvert.
"""
import ctypes, datetime, os, subprocess, sys, time, traceback
from ctypes import wintypes
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "FileForge" / "FileForge.log"
SHOW_EVENT, READY_EVENT = "Local\\FileForgeSearchShow", "Local\\FileForgeSearchReady"
TITLE = "FileForge-Recherche"          # titre de la fenêtre du panneau de recherche (wheel.py --search)
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
VK_G = 0x47
WM_HOTKEY, WM_TIMER, WM_QUIT = 0x0312, 0x0113, 0x0012
WM_KEYDOWN, WM_SYSKEYDOWN = 0x0100, 0x0104
RESPAWN_MS, HEALTH_MS, CAPTURE_MS = 900, 30000, 3000
MODIFIERS = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C, 0x14, 0x90, 0x91}
SPECIAL = {0x08, 0x0D, 0x1B, 0x09, 0x26, 0x28, 0x25, 0x27}   # Retour arrière, Entrée, Échap, Tab, flèches

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
for f, r in ((kernel32.CreateEventW, wintypes.HANDLE), (kernel32.CreateMutexW, wintypes.HANDLE),
             (kernel32.GetModuleHandleW, wintypes.HMODULE), (kernel32.OpenProcess, wintypes.HANDLE), (user32.SetWindowsHookExW, ctypes.c_void_p),
             (user32.GetKeyboardLayout, ctypes.c_void_p), (user32.CallNextHookEx, ctypes.c_ssize_t)):
    f.restype = r
user32.SetTimer.restype = ctypes.c_size_t
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, wintypes.HMODULE, wintypes.DWORD]
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.ToUnicodeEx.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_char_p, wintypes.LPWSTR, ctypes.c_int,
                               wintypes.UINT, ctypes.c_void_p]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


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


def visible_panel():
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
                found.append(p.value)
                return False
        return True
    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def kill_pid(pid):
    h = kernel32.OpenProcess(0x0001, False, pid)      # PROCESS_TERMINATE
    if h:
        kernel32.TerminateProcess(h, 0)
        kernel32.CloseHandle(h)


def send(inputs):
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def key_input(vk=0, scan=0, flags=0):
    i = INPUT(type=1)
    i.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return i


class Capture:
    """Retient les touches tapées pendant l'ouverture du panneau (crochet clavier bas niveau)."""

    def __init__(self):
        self.hook = None
        self.items = []
        self._proc = HOOKPROC(self._on_key)   # garder une référence

    def start(self):
        self.items = []
        if not self.hook:
            self.hook = user32.SetWindowsHookExW(13, self._proc, kernel32.GetModuleHandleW(None), 0)  # WH_KEYBOARD_LL

    def active(self):
        return bool(self.hook)

    def stop(self):
        if self.hook:
            user32.UnhookWindowsHookEx(self.hook)
            self.hook = None
        items, self.items = self.items, []
        return items

    def _char(self, vk, scan):
        state = (ctypes.c_ubyte * 256)()
        for k in (0x10, 0xA0, 0xA1):                       # Maj (Ctrl/Alt ignorés : souvent encore tenus)
            if user32.GetAsyncKeyState(k) & 0x8000:
                state[k] = state[0x10] = 0x80
        if user32.GetKeyState(0x14) & 1:                   # Verr. Maj
            state[0x14] = 0x01
        fg = user32.GetForegroundWindow()
        layout = user32.GetKeyboardLayout(user32.GetWindowThreadProcessId(fg, None))
        buf = ctypes.create_unicode_buffer(8)
        n = user32.ToUnicodeEx(vk, scan, ctypes.cast(state, ctypes.c_char_p), buf, 8, 4, layout)  # 4 : sans toucher aux touches mortes
        return buf.value[:n] if n > 0 else ""

    def _on_key(self, code, wparam, lparam):
        try:
            if code == 0:
                k = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if k.vkCode not in MODIFIERS:              # Ctrl, Alt, Maj… passent : pas de touche « collée »
                    down = wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                    hotkey_g = k.vkCode == VK_G and user32.GetAsyncKeyState(0x11) & 0x8000
                    if down and not hotkey_g:
                        if k.vkCode in SPECIAL:
                            self.items.append(("vk", k.vkCode))
                        else:
                            c = self._char(k.vkCode, k.scanCode)
                            if c and c.isprintable():
                                self.items.append(("char", c))
                    return 1                               # avalée : n'arrive pas dans l'application d'avant
        except Exception:
            log(traceback.format_exc())
        return user32.CallNextHookEx(None, code, wparam, lparam)


def replay(items):
    seq = []
    for kind, v in items:
        if kind == "char":
            for ch in v:
                seq += [key_input(0, ord(ch), 0x0004), key_input(0, ord(ch), 0x0004 | 0x0002)]   # KEYEVENTF_UNICODE
        else:
            seq += [key_input(v), key_input(v, 0, 0x0002)]
    if seq:
        send(seq)


class Agent:
    def __init__(self):
        self.show = kernel32.CreateEventW(None, False, False, SHOW_EVENT)    # remise à zéro automatique
        self.ready = kernel32.CreateEventW(None, False, False, READY_EVENT)
        self.standby = None     # panneau chargé, caché, qui attend le signal
        self.active = None      # panneau affiché
        self.respawn_timer = self.capture_timer = None
        self.last = 0.0
        self.capture = Capture()

    def _spawn(self, standby):
        env = dict(os.environ, FF_AGENT_PID=str(os.getpid()))
        args = [pythonw(), str(HERE / "wheel.py"), "--search"] + (["--standby"] if standby else [])
        # dossier de travail hors du dossier de FileForge : sinon il ne pourrait pas être supprimé à la désinstallation
        return subprocess.Popen(args, cwd=os.environ.get("TEMP") or str(Path.home()), env=env, creationflags=0x08000000)

    def ensure_standby(self):
        if self.standby is None or self.standby.poll() is not None:
            self.standby = self._spawn(True)

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
            return
        if self.capture.active():
            return                           # en train de s'ouvrir : on n'en lance pas un deuxième
        if a is not None and a.poll() is None:
            a.kill()                         # fenêtre déjà fermée, processus qui traîne
        self.active = None
        user32.AllowSetForegroundWindow(-1)  # le panneau pourra passer au premier plan
        kernel32.ResetEvent(self.ready)
        self.capture.start()
        self.capture_timer = user32.SetTimer(None, 0, CAPTURE_MS, None)
        if self.standby is not None and self.standby.poll() is None:
            kernel32.SetEvent(self.show)     # le panneau en réserve s'affiche
            self.active, self.standby = self.standby, None
        else:
            self.active = self._spawn(False)
            log("pas de réserve : ouverture directe")
        if self.respawn_timer:
            user32.KillTimer(None, self.respawn_timer)
        self.respawn_timer = user32.SetTimer(None, 0, RESPAWN_MS, None)

    def end_capture(self):
        if self.capture_timer:
            user32.KillTimer(None, self.capture_timer)
            self.capture_timer = None
        items = self.capture.stop()
        if items:
            replay(items)

    def run(self):
        ok = user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_G)
        log("Ctrl+Alt+G enregistré" if ok else
            f"Ctrl+Alt+G indisponible (déjà pris par une autre application ? erreur {ctypes.get_last_error()})")
        if not ok:
            return 2
        self.ensure_standby()
        user32.SetTimer(None, 0, HEALTH_MS, None)
        msg = wintypes.MSG()
        handles = (wintypes.HANDLE * 1)(self.ready)
        while True:
            r = user32.MsgWaitForMultipleObjects(1, handles, False, 0xFFFFFFFF, 0x04FF)   # QS_ALLINPUT
            if r == 0:                                  # le champ du panneau a le focus
                if self.capture.active():
                    self.end_capture()
                continue
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):              # PM_REMOVE
                if msg.message == WM_QUIT:
                    return 0
                try:
                    if msg.message == WM_HOTKEY:
                        self.on_hotkey()
                    elif msg.message == WM_TIMER:
                        if msg.wParam == self.capture_timer:
                            self.end_capture()      # le panneau tarde : on rend la main quand même
                        else:
                            if msg.wParam == self.respawn_timer:
                                user32.KillTimer(None, self.respawn_timer)
                                self.respawn_timer = None
                            self.ensure_standby()
                    else:
                        user32.TranslateMessage(ctypes.byref(msg))
                        user32.DispatchMessageW(ctypes.byref(msg))
                except Exception:
                    log(traceback.format_exc())


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
