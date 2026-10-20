#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileForge — interface « roue » qui s'ouvre sous la souris."""
import os, sys, json, threading, subprocess, tempfile, traceback, importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("fileforge", HERE / "fileforge.py")
ff = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ff)
IS_WIN = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
IS_MAC = sys.platform == "darwin"
SEARCH_ONLY = "--search" in sys.argv   # ⌃⌥G : panneau de recherche seul, sans fichier
if sys.stdout is None or sys.stderr is None:
    ff.LOG.parent.mkdir(parents=True, exist_ok=True)
    _lf = open(ff.LOG, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _lf
    sys.stderr = sys.stderr or _lf

import webview

_alive = threading.Lock()

# Correctif pywebview (macOS) : evaluate_js partage un sémaphore global entre threads.
# Deux appels simultanés (mise à jour de la roue + réponse à un clic) se volent le signal
# et l'un reste bloqué pour toujours → roue figée. On sérialise tous les appels.
try:
    _eval_lock = threading.RLock()
    if IS_WIN:
        # Windows : on enveloppe la fonction du module (la classe de fenêtre est un type .NET)
        from webview.platforms import winforms as _plat
        _orig_mod_eval = _plat.evaluate_js

        def _safe_mod_eval(*a, **k):
            with _eval_lock:
                with _alive:
                    return _orig_mod_eval(*a, **k)
        _plat.evaluate_js = _safe_mod_eval
    else:
        if IS_LINUX:
            from webview.platforms import gtk as _plat
        else:
            from webview.platforms import cocoa as _plat
        _orig_eval = _plat.BrowserView.evaluate_js

        def _safe_eval(self, *a, **k):
            with _eval_lock:
                with _alive:
                    return _orig_eval(self, *a, **k)
        _plat.BrowserView.evaluate_js = _safe_eval
except Exception as _e:
    ff.log(f"patch evaluate_js: {_e}")

W = H = 760

CATS = [
    ("convert", "Convertir", "repeat", "#7c5cff"),
    ("edit", "Éditer", "pen-tool", "#ec4899"),
    ("pages", "Pages", "files", "#3b82f6"),
    ("compress", "Compresser", "package", "#10b981"),
    ("extract", "Extraire", "file-output", "#06b6d4"),
    ("secure", "Sécurité", "shield", "#f59e0b"),
    ("tools", "Outils", "wrench", "#8b93a7"),
]

META = {
    # PDF
    "pdf_merge": ("pages", "Fusionner", "combine"), "pdf_split": ("pages", "Diviser", "split"),
    "pdf_extract": ("pages", "Extraire des pages", "file-output"), "pdf_delete": ("pages", "Supprimer des pages", "trash-2"),
    "pdf_reorder": ("pages", "Réorganiser", "arrow-up-down"), "pdf_rotate": ("pages", "Pivoter", "rotate-cw"),
    "pdf_compress": ("compress", "Compresser le PDF", "minimize-2"), "pdf_crop": ("edit", "Rogner", "crop"),
    "pdf_to_images": ("convert", "JPG / PNG", "image"), "pdf_to_word": ("convert", "Word", "file-text"),
    "pdf_to_pptx": ("convert", "PowerPoint", "presentation"), "pdf_to_excel": ("convert", "Excel", "sheet"),
    "pdf_to_text": ("convert", "Texte / Markdown", "type"), "pdf_extract_images": ("extract", "Images", "images"),
    "pdf_protect": ("secure", "Mot de passe", "lock"), "pdf_unlock": ("secure", "Déverrouiller", "lock-open"),
    "pdf_watermark": ("edit", "Filigrane", "droplet"), "pdf_numbers": ("edit", "Numéroter", "list-ordered"),
    "pdf_sign": ("edit", "Signer", "signature"), "pdf_redact": ("secure", "Caviarder", "eye-off"),
    "pdf_ocr": ("tools", "OCR", "scan-text"), "pdf_flatten": ("tools", "Aplatir", "layers"),
    "pdf_gray": ("edit", "Noir & blanc", "contrast"), "pdf_meta": ("secure", "Métadonnées", "tag"),
    "pdf_repair": ("tools", "Réparer", "wrench"), "pdf_info": ("tools", "Infos", "info"),
    # Images
    "img_convert": ("convert", "Autre format", "repeat"), "img_resize": ("edit", "Redimensionner", "scaling"),
    "img_compress": ("compress", "Compresser", "minimize-2"), "img_crop": ("edit", "Rogner", "crop"),
    "img_rotate": ("edit", "Pivoter / miroir", "rotate-cw"), "img_strip": ("secure", "Retirer EXIF & GPS", "map-pin-off"),
    "img_to_pdf": ("convert", "PDF", "file-type"), "img_watermark": ("edit", "Filigrane", "droplet"),
    "img_gif": ("convert", "GIF animé", "film"),
    # Vidéo
    "vid_mp4": ("convert", "MP4", "video"), "vid_compress": ("compress", "Compresser", "minimize-2"),
    "vid_trim": ("edit", "Couper", "scissors"), "vid_gif": ("convert", "GIF", "film"),
    "vid_audio": ("extract", "Audio MP3", "music"), "vid_mute": ("edit", "Retirer le son", "volume-x"),
    "vid_resize": ("edit", "Redimensionner", "scaling"), "vid_rotate": ("edit", "Pivoter", "rotate-cw"),
    "vid_frame": ("extract", "Capture d'image", "camera"),
    # Audio
    "aud_convert": ("convert", "Format audio", "audio-lines"), "aud_compress": ("compress", "Compresser", "minimize-2"),
    "aud_trim": ("edit", "Couper", "scissors"), "aud_norm": ("edit", "Normaliser", "activity"),
    "aud_merge": ("tools", "Fusionner", "combine"),
    # Documents / tableurs / général
    "doc_to_pdf": ("convert", "PDF", "file-type"), "office_convert": ("convert", "Autre format", "repeat"),
    "docx_convert": ("convert", "MD / HTML / TXT", "type"), "md_html": ("convert", "HTML", "code"),
    "tab_convert": ("convert", "Excel / CSV / JSON", "sheet"), "tab_merge": ("tools", "Fusionner", "combine"),
    "make_zip": ("compress", "ZIP", "archive"), "extract_archive": ("extract", "Décompresser", "package-open"),
    "batch_rename": ("tools", "Renommer", "text-cursor-input"),
}

TYPE_COLORS = [(ff.PDF, "#ef4444"), (ff.IMG, "#22c55e"), (ff.VID, "#a855f7"), (ff.AUD, "#f59e0b"),
               (ff.OFFICE | ff.TEXT, "#3b82f6"), (ff.TAB, "#10b981"), (ff.ARC, "#94a3b8")]


class Close(Exception):
    pass


def clean(label):
    return label.split(" ", 1)[1] if label and not label[0].isalnum() else label


def meta(a):
    m = META.get(a["fn"].__name__)
    return m if m else ("tools", clean(a["label"]).split("·")[-1].strip(), "sparkles")


# ───────────────────────── pont Python ⇄ roue ─────────────────────────

class UI:
    def __init__(self):
        self._ev = threading.Event()
        self._val = None
        self._win = None
        self._label = ""
        self._accept_drop = False

    # appelé par la roue (JS)
    def answer(self, v):
        self._val = v
        self._ev.set()

    def jslog(self, m):
        ff.log("JS: " + str(m))

    # recherche de fichiers (appelée directement par la roue, hors de la boucle d'actions)
    def find_warmup(self):
        try:
            finder().INDEXED.ensure()
        except Exception as e:
            ff.log(f"recherche (préparation) : {e}")

    def find(self, q):
        try:
            fs = finder()
            if fs.index_age() is None and fs.INDEXED.count() == 0:
                fs.INDEXED.ensure()
                return {"building": True, "results": [], "info": {}}
            res, info = fs.search(str(q or ""), 12)
            return {"results": res, "info": info, "building": fs.INDEXED.building}
        except Exception:
            ff.log(traceback.format_exc())
            return {"results": [], "info": {"mode": "erreur"}}

    def _send(self, st):
        self._win.evaluate_js("FF.show(%s)" % json.dumps(st, ensure_ascii=False))

    def _wait(self, st, busy_after=True):
        self._ev.clear()
        self._val = None
        self._send(st)
        self._ev.wait()
        v = self._val
        if v is None or v == "__cancel__":
            raise ff.Cancel()
        if v == "__close__":
            raise Close()
        if busy_after:
            self._send({"mode": "busy", "text": self._label})
        return v


ui = UI()
_finder = None


def finder():
    global _finder
    if _finder is None:
        sp = importlib.util.spec_from_file_location("ff_search", HERE / "search.py")
        _finder = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(_finder)
    return _finder


def choose(items, prompt, default=None, multiple=False, ok="OK"):
    items = list(items)
    return ui._wait({"mode": "choice", "prompt": prompt, "items": items, "default": default if default in items else None})


def ask(prompt, default="", hidden=False):
    return str(ui._wait({"mode": "ask", "prompt": prompt, "default": default, "hidden": hidden})).strip()


def buttons(prompt, btns, default=None):
    return ui._wait({"mode": "card", "text": prompt, "buttons": list(btns), "default": default})


def alert(title, msg=""):
    ui._wait({"mode": "error", "text": f"{title}\n{msg}", "items": ["OK"]}, busy_after=False)


def notify(msg):
    ui._label = msg
    ui._send({"mode": "busy", "text": msg})


def _dialog(multiple=True, types=()):
    kind = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
    return ui._win.create_file_dialog(kind, allow_multiple=multiple, file_types=types) or []


def choose_file(prompt, types=None):
    r = _dialog(False, ("Images (*.png;*.jpg;*.jpeg;*.heic;*.webp;*.gif)", "Tous les fichiers (*.*)"))
    if not r:
        raise ff.Cancel()
    return r[0]


TITLE = "FileForge-Roue"


def activate():
    if IS_WIN:
        try:
            import ctypes
            u = ctypes.windll.user32
            hwnd = u.FindWindowW(None, TITLE)
            if hwnd:
                u.keybd_event(0x12, 0, 0, 0)      # astuce Alt : autorise le passage au premier plan
                u.keybd_event(0x12, 0, 2, 0)
                u.ShowWindow(hwnd, 5)
                u.SetForegroundWindow(hwnd)
        except Exception as e:
            ff.log(f"activate(win): {e}")
        return
    if IS_LINUX:
        return
    try:
        import AppKit
        from PyObjCTools import AppHelper

        def f():
            try:
                app = AppKit.NSApplication.sharedApplication()
                app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
                app.activateIgnoringOtherApps_(True)
                for w in app.windows():
                    w.setAcceptsMouseMovedEvents_(True)
                    w.makeKeyAndOrderFront_(None)
            except Exception as e:
                ff.log(f"activate(main): {e}")
        AppHelper.callAfter(f)
    except Exception as e:
        ff.log(f"activate: {e}")


def tk_call(payload):
    ui._win.hide()
    try:
        r = subprocess.run([sys.executable, str(HERE / "fileforge.py"), "--tk", json.dumps(payload)],
                           capture_output=True, text=True)
    finally:
        ui._win.show()
        activate()
    line = next((l for l in reversed(r.stdout.splitlines()) if l.startswith("{")), None)
    if not line:
        raise RuntimeError("Fenêtre d'édition : " + ((r.stderr.strip().splitlines() or ["erreur inconnue"])[-1]))
    d = json.loads(line)
    if d.get("cancel"):
        raise ff.Cancel()
    if "error" in d:
        raise RuntimeError(d["error"])
    return d["ok"]


def pick_regions(src, kind, title, hint, multi=False, start_page=0):
    tmp = Path(tempfile.mkdtemp())
    if kind == "pdf":
        import pymupdf
        p = tmp / "src.pdf"
        p.write_bytes(src.tobytes(encryption=pymupdf.PDF_ENCRYPT_NONE))
    else:
        p = tmp / "src.png"
        src.save(p)
    res = tk_call({"fn": "regions", "path": str(p), "kind": kind, "title": title, "hint": hint,
                   "multi": multi, "start_page": start_page})
    return {int(k): [tuple(r) for r in v] for k, v in res.items()}


def draw_signature():
    return Path(tk_call({"fn": "signature"}))


for _n in ("choose", "ask", "buttons", "alert", "notify", "choose_file", "pick_regions", "draw_signature"):
    setattr(ff, _n, globals()[_n])

# ───────────────────────── logique ─────────────────────────

def type_color(files):
    for group, col in TYPE_COLORS:
        if all(ff.ext(f) in group for f in files):
            return col
    return "#64748b"


def build_main(files, acts):
    cats = {c[0]: {"id": c[0], "label": c[1], "icon": c[2], "color": c[3], "actions": []} for c in CATS}
    for a in acts:
        cid, lab, ic = meta(a)
        cats[cid]["actions"].append({"id": a["fn"].__name__, "label": lab, "icon": ic, "full": clean(a["label"])})
    exts = {("dossier" if Path(f).is_dir() else ff.ext(f) or "?") for f in files}
    size = sum(Path(f).stat().st_size for f in files if Path(f).is_file())
    if len(files) == 1:
        title = Path(files[0]).name
        sub = "Dossier" if Path(files[0]).is_dir() else ff.human(size)
    else:
        title = f"{len(files)} éléments"
        sub = ", ".join(sorted(e.upper() for e in exts))[:40] + (f" · {ff.human(size)}" if size else "")
    badge = next(iter(exts)).upper() if len(exts) == 1 else "MIX"
    return {"mode": "main", "platform": sys.platform, "cats": [c for c in cats.values() if c["actions"]], "badge": badge[:6],
            "title": title, "subtitle": sub, "color": type_color(files)}


def expand(paths):
    res = []
    for p in map(Path, paths):
        if p.is_dir():
            res += sorted((str(x) for x in p.iterdir() if x.is_file() and not x.name.startswith(".")), key=ff.natural)
        elif p.exists():
            res.append(str(p))
    return res


def explorer_selection():
    """Fichiers sélectionnés dans la fenêtre de l'Explorateur au premier plan."""
    try:
        import ctypes
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        fg = ctypes.windll.user32.GetForegroundWindow()
        for w in win32com.client.Dispatch("Shell.Application").Windows():
            try:
                if int(w.HWND) == fg:
                    return [it.Path for it in w.Document.SelectedItems() if os.path.exists(it.Path)]
            except Exception:
                continue
    except Exception as e:
        ff.log(f"explorer_selection: {e}")
    return []


def gather(args):
    """Windows lance un processus par fichier sélectionné : on les regroupe en une seule roue."""
    import time
    tmp = Path(tempfile.gettempdir())
    q, lock = tmp / "fileforge_queue.txt", tmp / "fileforge_queue.lock"
    with open(q, "a", encoding="utf-8") as fh:
        fh.write("\n".join(args) + "\n")
    try:
        if lock.exists() and time.time() - lock.stat().st_mtime > 10:
            lock.unlink()
        os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        os._exit(0)
    time.sleep(0.7)
    try:
        paths = [l.strip() for l in q.read_text(encoding="utf-8").splitlines() if l.strip()]
        q.unlink()
    finally:
        lock.unlink(missing_ok=True)
    return list(dict.fromkeys(paths))


def finder_selection():
    script = ['tell application "Finder" to set s to selection as alias list', 'set out to ""',
              'repeat with a in s', 'set out to out & POSIX path of a & linefeed', 'end repeat', 'return out']
    try:
        args = []
        for l in script:
            args += ["-e", l]
        r = subprocess.run(["osascript", *args], capture_output=True, text=True, timeout=6)
        ps = [p.rstrip("/") for p in r.stdout.splitlines() if p.strip()]
        return [p for p in ps if not p.endswith(".app") and os.path.exists(p)]
    except Exception:
        return []


def win_backdrop(window):
    """Windows : WebView2 ne sait pas rendre une fenêtre réellement transparente.
    On photographie l'écran sous la fenêtre (encore cachée) et on s'en sert comme fond :
    la roue paraît flotter, ombre et bords lisses compris."""
    import base64, ctypes, io
    from ctypes import wintypes
    from PIL import ImageGrab
    u = ctypes.windll.user32
    try:
        u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))  # coordonnées en pixels physiques
    except Exception:
        pass
    hwnd = u.FindWindowW(None, TITLE)
    r = wintypes.RECT()
    if not hwnd or not u.GetWindowRect(hwnd, ctypes.byref(r)) or r.right <= r.left:
        raise RuntimeError("fenêtre introuvable")
    im = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    window.evaluate_js("document.documentElement.style.background='url(%s) 0 0/100%% 100%% no-repeat';"
                       "document.documentElement.classList.add('backdrop');true" % url)


def win_round(window):
    """Secours si la capture échoue : fenêtre découpée en disque (fond sombre, sans ombre)."""
    import ctypes
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    window.evaluate_js("document.documentElement.style.background='#16161e';true")
    hwnd = u.FindWindowW(None, TITLE)
    if hwnd:
        try:
            u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            pass
        from ctypes import wintypes
        r = wintypes.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(r))
        w = r.right - r.left
        m = int(w * (380 - 318) / 760)
        u.SetWindowRgn(hwnd, g.CreateEllipticRgn(m, m, w - m, w - m), True)


def run(window, files):
    ui._win = window
    try:
        from webview.dom import DOMEventHandler

        def on_drop(e):
            if not ui._accept_drop:
                return
            fs = [f.get("pywebviewFullPath") for f in (e.get("dataTransfer") or {}).get("files", [])]
            fs = [f for f in fs if f]
            if fs:
                ui.answer(fs)
        window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
    except Exception as e:
        ff.log(f"drop: {e}")
    if IS_WIN:
        try:
            window.events.loaded.wait(15)
            try:
                win_backdrop(window)
            except Exception as e:
                ff.log(f"backdrop: {e}")
                win_round(window)
            window.show()
            window.events.shown.wait(5)
        except Exception as e:
            ff.log(f"show(win): {e}")
    activate()
    if os.environ.get("FF_DEBUG"):
        def dbg():
            import time
            cmd = Path(tempfile.gettempdir()) / "ff_cmd.js"
            while True:
                if cmd.exists():
                    js = cmd.read_text(); cmd.unlink()
                    try:
                        r = window.evaluate_js(js)
                        (cmd.parent / "ff_cmd.out").write_text(str(r), encoding="utf-8")
                    except Exception as e:
                        (cmd.parent / "ff_cmd.out").write_text("ERR " + str(e), encoding="utf-8")
                time.sleep(0.2)
        threading.Thread(target=dbg, daemon=True).start()
    try:
        while True:
            if not files:
                ui._accept_drop = not SEARCH_ONLY
                v = ui._wait({"mode": "find", "standalone": True} if SEARCH_ONLY else {"mode": "drop"}, busy_after=False)
                ui._accept_drop = False
                if isinstance(v, dict) and v.get("find"):
                    p = v["path"]
                    if not os.path.exists(p):
                        continue
                    ff.log(f"recherche → {v['find']} {p}")
                    if v["find"] == "wheel":
                        files = [p]
                        continue
                    ff.open_path(p) if v["find"] == "open" else ff.reveal(p)
                    break
                if v == "__browse__":
                    files = sorted(_dialog(True), key=ff.natural)
                    activate()
                elif isinstance(v, list):
                    files = sorted({p for p in v if os.path.exists(p)}, key=ff.natural)
                continue
            acts = ff.available(files)
            ui._accept_drop = True
            aid = ui._wait(build_main(files, acts), busy_after=False)
            ui._accept_drop = False
            if isinstance(aid, list):
                files = sorted({p for p in aid if os.path.exists(p)}, key=ff.natural)
                continue
            act = next((a for a in acts if a["fn"].__name__ == aid), None)
            if not act:
                continue
            ui._label = clean(act["label"]) + "…"
            ui._send({"mode": "busy", "text": ui._label})
            ff.NOTES.clear()
            ff.log(f"{act['label']} ← {files}")
            try:
                outs = act["fn"](list(files)) or []
            except ff.Cancel:
                continue
            except Close:
                raise
            except Exception as e:
                # ValueError = saisie ou fichier inadapté : message clair, pas de trace technique
                ff.log(f"  ✗ {e}" if isinstance(e, ValueError) else traceback.format_exc())
                v = ui._wait({"mode": "error", "text": str(e), "items": ["Retour", "Journal", "Fermer"]}, busy_after=False)
                if v == "Journal":
                    subprocess.run(["open", "-e", str(ff.LOG)]) if IS_MAC else ff.open_path(ff.LOG)
                    break
                if v == "Fermer":
                    break
                continue
            outs = [Path(o) for o in outs if o]
            ff.log(f"  → {[str(o) for o in outs]}")
            if not outs and not ff.NOTES:
                continue
            items = (["Ouvrir"] if len(outs) == 1 else []) + (["Afficher", "Enchaîner"] if outs else []) + ["Retour", "Fermer"]
            v = ui._wait({"mode": "done", "outs": [o.name for o in outs], "notes": ff.NOTES[:4], "items": items},
                         busy_after=False)
            if v == "Ouvrir":
                ff.open_path(outs[0])
                break
            if v == "Afficher":
                ff.reveal(outs[0])
                break
            if v == "Enchaîner":
                files = expand(outs)
                continue
            if v == "Retour":
                files = [f for f in files if os.path.exists(f)]
                continue
            break
    except (Close, ff.Cancel):
        pass
    except Exception:
        ff.log(traceback.format_exc())
    finally:
        try:
            window.hide()
        except Exception:
            pass
        os._exit(0)


def position_win():
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
    pt = wintypes.POINT()
    u.GetCursorPos(ctypes.byref(pt))
    mon = u.MonitorFromPoint(pt, 2)
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    u.GetMonitorInfoW(mon, ctypes.byref(mi))
    scale = 1.0
    try:
        dx, dy = ctypes.c_uint(), ctypes.c_uint()
        ctypes.windll.shcore.GetDpiForMonitor(mon, 0, ctypes.byref(dx), ctypes.byref(dy))
        scale = dx.value / 96 or 1.0
    except Exception:
        pass
    w, h, r = W * scale, H * scale, mi.rcWork
    cx = min(max(pt.x, r.left + w / 2), r.right - w / 2)
    cy = min(max(pt.y, r.top + h / 2), r.bottom - h / 2)
    return int((cx - w / 2) / scale), int((cy - h / 2) / scale), None


def position():
    """Coordonnées (x, y, écran) pour centrer la roue sous la souris."""
    if IS_LINUX:
        return None, None, None
    if IS_WIN:
        try:
            return position_win()
        except Exception as e:
            ff.log(f"position(win): {e}")
            return None, None, None
    try:
        import AppKit
        loc = AppKit.NSEvent.mouseLocation()
        screens = list(AppKit.NSScreen.screens())
        idx = next((i for i, s in enumerate(screens) if AppKit.NSPointInRect(loc, s.frame())), 0)
        fr, vf = screens[idx].frame(), screens[idx].visibleFrame()
        if SEARCH_ONLY:
            loc = AppKit.NSMakePoint(vf.origin.x + vf.size.width / 2, vf.origin.y + vf.size.height * 0.56)
        cx = min(max(loc.x, vf.origin.x + W / 2), vf.origin.x + vf.size.width - W / 2)
        cy = min(max(loc.y, vf.origin.y + H / 2), vf.origin.y + vf.size.height - H / 2)
        x = cx - W / 2 - fr.origin.x
        y = (fr.origin.y + fr.size.height) - (cy + H / 2)
        scr = webview.screens[idx] if idx < len(webview.screens) else None
        return int(x), int(y), scr
    except Exception as e:
        ff.log(f"position: {e}")
        return None, None, None


def main():
    args = [os.path.abspath(a) for a in sys.argv[1:] if not a.startswith("--") and os.path.exists(a)]
    if IS_WIN and args:
        args = gather(args)
    if not args and not SEARCH_ONLY:
        args = explorer_selection() if IS_WIN else ([] if IS_LINUX else finder_selection())
    files = sorted(set(args), key=ff.natural)
    x, y, scr = position()
    kw = dict(width=W, height=H, frameless=True, transparent=not IS_WIN, on_top=True, resizable=False,
              easy_drag=False, shadow=False, js_api=ui, background_color="#000000")
    if IS_WIN:
        # fenêtre cachée tant que le fond n'est pas prêt (voir win_backdrop)
        kw.update(hidden=True, background_color="#1b1b24")
    if x is not None:
        kw.update(x=x, y=y)
    if scr is not None:
        kw["screen"] = scr
    win = webview.create_window(TITLE, str(HERE / "wheel.html"), **kw)
    # Filet de sécurité : si la roue ne répond plus pendant 20 s, le processus se termine.
    def watchdog():
        import time
        while True:
            time.sleep(5)
            if not _alive.acquire(timeout=20):
                ff.log("watchdog: interface bloquée, arrêt")
                os._exit(1)
            _alive.release()
    threading.Thread(target=watchdog, daemon=True).start()
    webview.start(run, (win, files), gui="gtk" if IS_LINUX else None)
    os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        ff.log(traceback.format_exc())
