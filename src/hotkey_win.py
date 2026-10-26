#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileForge — agent Windows : ouvre la roue et la recherche instantanément.

Lancé à l'ouverture de session (clé Run de l'utilisateur), sans fenêtre. Il garde deux fenêtres déjà
chargées en réserve, cachées et inactives : la roue et le panneau de recherche. Il ne fait qu'attendre :
- Ctrl+Alt+G   : panneau de recherche (un second appui le referme) ;
- Ctrl+Alt+F   : la roue sur les fichiers sélectionnés dans l'Explorateur (lus à l'instant de l'appui) ;
- clic droit > FileForge…, Envoyer vers, icône du Bureau : un petit lanceur (« --open fichiers… »)
  transmet les fichiers à l'agent, qui affiche la roue en réserve.
Sans agent, le lanceur ouvre la roue lui-même (plus lentement) : rien ne casse.
"""
import threading, ctypes, datetime, json, os, subprocess, sys, time, traceback
from ctypes import wintypes
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "FileForge"
LOG = DATA / "FileForge.log"
TMP = Path(os.environ.get("TEMP") or Path.home())
TID_FILE = DATA / "agent.tid"                    # fil de messages de l'agent (pour les lanceurs)
QUEUE = TMP / "fileforge_open_queue.txt"         # fichiers envoyés par les lanceurs du clic droit
REQUEST = TMP / "fileforge_wheel_request.json"   # fichiers à afficher par la roue en réserve
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
VK_G, VK_F = 0x47, 0x46
WM_HOTKEY, WM_TIMER, WM_QUIT = 0x0312, 0x0113, 0x0012
WM_OPEN = 0x8000 + 1                             # WM_APP + 1 : « des fichiers attendent dans la file »
RESPAWN_MS, HEALTH_MS = 400, 30000

KINDS = {   # fenêtre en réserve : titre, événement qui l'affiche, arguments de wheel.py
    "search": ("FileForge-Recherche", "Local\\FileForgeSearchShow", ["--search", "--standby"]),
    "wheel": ("FileForge-Roue", "Local\\FileForgeWheelShow", ["--standby-wheel"]),
}

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
for f, r in ((kernel32.CreateEventW, wintypes.HANDLE), (kernel32.CreateMutexW, wintypes.HANDLE),
             (kernel32.OpenProcess, wintypes.HANDLE)):
    f.restype = r
user32.SetTimer.restype = ctypes.c_size_t
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]


def log(*m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] agent : {' '.join(map(str, m))}\n")
    except Exception:
        pass


def pythonw():
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.exists() else exe)


def visible_window(title, with_hwnd=False):
    """Processus (pid) ayant une fenêtre visible de ce titre, ou None.
    (le Python d'un environnement virtuel tourne sous un petit lanceur : on se fie à la fenêtre, pas au pid lancé)"""
    found = []
    buf = ctypes.create_unicode_buffer(64)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            user32.GetWindowTextW(hwnd, buf, 64)
            if buf.value == title:
                p = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
                found.append((p.value, hwnd))
                return False
        return True
    user32.EnumWindows(cb, 0)
    if not found:
        return None
    return found[0] if with_hwnd else found[0][0]


def explorer_selection(fg=None):
    """Fichiers sélectionnés dans la fenêtre de l'Explorateur au premier plan.
    Windows 11 : tous les onglets d'une fenêtre ont le même HWND, on garde celui qui est affiché."""
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    fg = fg or user32.GetForegroundWindow()
    title = ctypes.create_unicode_buffer(260)
    user32.GetWindowTextW(fg, title, 260)
    cands = []
    for w in win32com.client.Dispatch("Shell.Application").Windows():
        try:
            if int(w.HWND) != fg:
                continue
            sel = [it.Path for it in w.Document.SelectedItems() if os.path.exists(it.Path)]
            cands.append((w, sel))
        except Exception:
            continue
    if not cands:
        return []
    if len(cands) == 1:
        return cands[0][1]
    # plusieurs onglets : celui dont la vue est visible, sinon celui dont le nom est dans le titre de la fenêtre
    for w, sel in cands:
        if tab_visible(w):
            return sel
    for w, sel in cands:
        try:
            if w.LocationName and w.LocationName in title.value:
                return sel
        except Exception:
            pass
    return next((sel for _, sel in cands if sel), [])


def tab_visible(w):
    """L'onglet de l'Explorateur correspondant à cet objet Shell est-il celui affiché ?"""
    try:
        import pythoncom
        from win32com.shell import shell
        sp = w._oleobj_.QueryInterface(pythoncom.IID_IServiceProvider)
        sb = sp.QueryService(shell.SID_STopLevelBrowser, shell.IID_IShellBrowser)
        return bool(user32.IsWindowVisible(sb.GetWindow()))
    except Exception:
        return False


def bring_to_front(title, timeout=1.5):
    """L'agent vient d'être sollicité : il a le droit de choisir la fenêtre active. Il l'exerce pour la nouvelle fenêtre."""
    t = time.time()
    while time.time() - t < timeout:
        r = visible_window(title, True)
        if r:
            user32.SetForegroundWindow(r[1])
            if user32.GetForegroundWindow() == r[1]:
                return int((time.time() - t) * 1000)
        time.sleep(0.015)
    return None


def kill_pid(pid):
    h = kernel32.OpenProcess(0x0001, False, pid)      # PROCESS_TERMINATE
    if h:
        kernel32.TerminateProcess(h, 0)
        kernel32.CloseHandle(h)


def spawn(args, env=None):
    # dossier de travail hors du dossier de FileForge : sinon il ne pourrait pas être supprimé à la désinstallation
    return subprocess.Popen([pythonw(), str(HERE / "wheel.py")] + args, cwd=str(TMP), env=env, creationflags=0x08000000)


def queue_add(paths):
    """Ajoute des fichiers à la file (plusieurs lanceurs peuvent écrire en même temps)."""
    for _ in range(50):
        try:
            with open(QUEUE, "a", encoding="utf-8") as fh:
                fh.write("".join(p + "\n" for p in paths) or "\n")
            return True
        except OSError:
            time.sleep(0.01)
    return False


def queue_take():
    try:
        tmp = QUEUE.with_suffix(".taken")
        os.replace(QUEUE, tmp)
        lines = tmp.read_text(encoding="utf-8").splitlines()
        tmp.unlink()
    except OSError:
        return []
    return list(dict.fromkeys(l.strip() for l in lines if l.strip() and os.path.exists(l.strip())))


class Agent:
    def __init__(self):
        self.events = {k: kernel32.CreateEventW(None, False, False, ev) for k, (_, ev, _) in KINDS.items()}
        self.standby = {k: None for k in KINDS}   # fenêtres chargées, cachées, qui attendent leur signal
        self.active = None                        # panneau de recherche affiché (ou en train de s'afficher)
        self.opening_until = 0.0
        self.respawn_timer = self.collect_timer = None
        self.last = 0.0
        self.last_open, self.last_files = 0.0, set()

    # ── réserves
    def ensure_standby(self):
        if any(visible_window(t) for t, _, _ in KINDS.values()):
            return False                          # pas pendant qu'on se sert d'une fenêtre : on réessaiera
        env = dict(os.environ, FF_AGENT_PID=str(os.getpid()))
        for k, (_, _, args) in KINDS.items():
            p = self.standby[k]
            if p is None or p.poll() is not None:
                self.standby[k] = spawn(args, env)
        return True

    def take_standby(self, kind):
        p = self.standby[kind]
        self.standby[kind] = None
        if self.respawn_timer:
            user32.KillTimer(None, self.respawn_timer)
        self.respawn_timer = user32.SetTimer(None, 0, RESPAWN_MS, None)
        return p if p is not None and p.poll() is None else None

    # ── roue
    def open_wheel(self, files, why):
        t = time.time()
        user32.AllowSetForegroundWindow(-1)
        p = self.take_standby("wheel")
        if p:
            tmp = REQUEST.with_suffix(".tmp")
            tmp.write_text(json.dumps(files, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, REQUEST)
            kernel32.SetEvent(self.events["wheel"])
            ms = bring_to_front(KINDS["wheel"][0])
            log(f"{why} : roue en réserve, {len(files)} fichier(s), premier plan {ms if ms is not None else 'NON obtenu'} ms")
        else:
            spawn(["--direct"] + (files or ["--no-selection"]))
            ms = bring_to_front(KINDS["wheel"][0], 6)
            log(f"{why} : pas de réserve, roue lancée ({int((time.time() - t) * 1000)} ms)")

    def on_wheel_hotkey(self):
        """Ctrl+Alt+F : la roue sur les fichiers sélectionnés dans l'Explorateur, lus à l'instant de l'appui."""
        try:
            files = explorer_selection()
        except Exception as e:
            files = []
            log(f"sélection de l'Explorateur illisible : {e}")
        self.open_wheel(files, "Ctrl+Alt+F")

    def on_open_message(self):
        """Fichiers confiés par un lanceur (clic droit, Envoyer vers, Bureau, menu Démarrer)."""
        files = queue_take()
        now = time.time()
        if files and now - self.last_open < 3 and set(files) <= self.last_files:
            return                           # lanceur d'un fichier déjà affiché (clic droit sur plusieurs fichiers)
        if files:
            # Windows lance un lanceur par fichier, pas tous en même temps : la sélection de l'Explorateur
            # donne tout de suite la liste complète, sans attendre les retardataires
            try:
                sel = explorer_selection()
            except Exception:
                sel = []
            if sel and set(files) <= set(sel):
                files = sel
        self.last_open, self.last_files = now, set(files)
        self.open_wheel(files, "clic droit")

    # ── recherche
    def on_search_hotkey(self):
        now = time.time()
        if now - self.last < 0.25:           # rebond
            return
        self.last = now
        a = self.active
        shown = visible_window(KINDS["search"][0])
        if shown:
            kill_pid(shown)                  # Ctrl+Alt+G une seconde fois : referme
            if a is not None and a.poll() is None:
                a.kill()
            self.active = None
            log("Ctrl+Alt+G : fermeture du panneau")
            return
        if a is not None and a.poll() is None and now < self.opening_until:
            return                           # en train de s'ouvrir : on n'en lance pas un deuxième
        if a is not None and a.poll() is None:
            a.kill()                         # fenêtre déjà fermée, processus qui traîne
        user32.AllowSetForegroundWindow(-1)
        self.opening_until = now + 3
        p = self.take_standby("search")
        if p:
            kernel32.SetEvent(self.events["search"])
            self.active = p
            ms = bring_to_front(KINDS["search"][0])
            log(f"Ctrl+Alt+G : panneau en réserve, premier plan {ms if ms is not None else 'NON obtenu'} ms")
        else:
            self.active = spawn(["--search"])
            bring_to_front(KINDS["search"][0], 6)
            log("Ctrl+Alt+G : pas de réserve, ouverture directe")

    def update_loop(self):
        """Toutes les 6 h (et 10 min après le démarrage) : updater.py --auto, qui vérifie au plus une fois par jour."""
        time.sleep(600)                       # 10 min après l'ouverture de session : rien ne ralentit le démarrage
        while True:
            try:
                if (HERE / "updater.py").exists():
                    subprocess.Popen([pythonw(), str(HERE / "updater.py"), "--auto"], cwd=str(TMP),
                                     creationflags=0x08000000 | 0x00000200)
            except Exception:
                log(traceback.format_exc())
            time.sleep(6 * 3600)

    def run(self):
        threading.Thread(target=self.update_loop, daemon=True).start()
        for hid, vk, name in ((1, VK_G, "Ctrl+Alt+G"), (2, VK_F, "Ctrl+Alt+F")):
            if user32.RegisterHotKey(None, hid, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, vk):
                log(f"{name} enregistré")
            else:
                log(f"{name} indisponible (déjà pris par une autre application ? erreur {ctypes.get_last_error()})")
        try:
            TID_FILE.write_text(f"{kernel32.GetCurrentThreadId()} {os.getpid()}", encoding="utf-8")
        except OSError:
            pass
        self.ensure_standby()
        user32.SetTimer(None, 0, HEALTH_MS, None)
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            try:
                if msg.message == WM_HOTKEY:
                    self.on_wheel_hotkey() if msg.wParam == 2 else self.on_search_hotkey()
                elif msg.message == WM_OPEN:
                    self.on_open_message()
                elif msg.message == WM_TIMER:
                    ready = self.ensure_standby()
                    if msg.wParam == self.respawn_timer and ready:
                        user32.KillTimer(None, self.respawn_timer)   # sinon le minuteur réessaie un peu plus tard
                        self.respawn_timer = None
            except Exception:
                log(traceback.format_exc())
        return 0


def launch(paths):
    """Lanceur du clic droit / Envoyer vers / Bureau : confie les fichiers à l'agent, sinon ouvre la roue lui-même."""
    paths = [os.path.abspath(p) for p in paths if os.path.exists(p)]
    try:
        tid, pid = map(int, TID_FILE.read_text(encoding="utf-8").split())
        h = kernel32.OpenProcess(0x00100000, False, pid)              # SYNCHRONIZE : l'agent tourne-t-il ?
        alive = bool(h) and kernel32.WaitForSingleObject(h, 0) == 0x102   # WAIT_TIMEOUT
        if h:
            kernel32.CloseHandle(h)
        if alive and queue_add(paths):
            user32.AllowSetForegroundWindow(pid)                       # lancé par l'Explorateur : on lui passe la main
            if user32.PostThreadMessageW(tid, WM_OPEN, 0, 0):
                return 0
    except (OSError, ValueError):
        pass
    subprocess.Popen([pythonw(), str(HERE / "wheel.py")] + paths, cwd=str(TMP), creationflags=0x08000000)
    return 0


def main():
    if sys.argv[1:2] == ["--open"]:
        return launch(sys.argv[2:])
    mutex = kernel32.CreateMutexW(None, False, "Local\\FileForgeHotkeyAgent")
    if ctypes.get_last_error() == 183:       # déjà lancé
        return 0
    try:
        return Agent().run()
    finally:
        kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    sys.exit(main())
