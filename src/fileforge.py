#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FileForge — Copyright © 2026 Thomas Trahant — SPDX-License-Identifier: GPL-3.0-or-later
"""FileForge — moteur : toutes les actions (PDF, images, vidéo, audio, documents, tableurs, archives).

Chargé par la roue (wheel.py), qui fournit les dialogues. Lancé seul, il ne sert qu'aux fenêtres Tk de la roue :
    fileforge.py --tk '{"fn": "regions", …}'
"""
import os, sys, re, io, json, math, shutil, subprocess, traceback, datetime, zipfile, tarfile, gzip, tempfile
from pathlib import Path

APP = "FileForge"
__version__ = "1.3.0"
HOME_DIR = Path(__file__).resolve().parent
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
if IS_WIN:
    LOG = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "FileForge" / "FileForge.log"
elif IS_LINUX:
    LOG = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "fileforge" / "FileForge.log"
else:
    LOG = Path.home() / "Library/Logs/FileForge.log"
try:
    LOG.parent.mkdir(parents=True, exist_ok=True)
except Exception:
    pass
# langues OCR fournies par l'installateur (toutes plateformes)
if (HOME_DIR / "tessdata").is_dir():
    os.environ.setdefault("TESSDATA_PREFIX", str(HOME_DIR / "tessdata"))
if IS_LINUX and "TESSDATA_PREFIX" not in os.environ:
    for _td in ("/usr/share/tessdata", "/usr/share/tesseract-ocr/5/tessdata", "/usr/share/tesseract-ocr/4.00/tessdata"):
        if os.path.isdir(_td):
            os.environ["TESSDATA_PREFIX"] = _td
            break
NOTES = []

if IS_WIN:
    # aucune fenêtre de console quand on lance ffmpeg, LibreOffice…
    _Popen = subprocess.Popen

    class _HiddenPopen(_Popen):
        def __init__(self, *a, **k):
            k.setdefault("creationflags", 0x08000000)  # CREATE_NO_WINDOW
            super().__init__(*a, **k)
    subprocess.Popen = _HiddenPopen


# ───────── fichiers dans le cloud (iCloud « optimiser le stockage », OneDrive « à la demande ») ─────────
if IS_MAC:
    try:   # autorise ce processus à faire télécharger les fichiers iCloud non présents (sinon lecture vide)
        import ctypes as _ct
        _ct.CDLL("/usr/lib/libSystem.B.dylib").setiopolicy_np(3, 0, 2)   # VFS_MATERIALIZE_DATALESS_FILES, PROCESS, ON
    except Exception:
        pass


def _in_cloud(p):
    try:
        st = os.stat(p)
    except OSError:
        return False
    if IS_MAC:
        return bool(getattr(st, "st_flags", 0) & 0x40000000)                 # SF_DATALESS
    if IS_WIN:
        return bool(getattr(st, "st_file_attributes", 0) & 0x00440000)       # RECALL_ON_OPEN / ON_DATA_ACCESS
    return False


def materialize(files, timeout=120):
    """S'assure que les fichiers sont vraiment sur le disque (téléchargés depuis iCloud / OneDrive)."""
    import time as _t
    todo = [Path(f) for f in files if Path(f).is_file() and _in_cloud(f)]
    if not todo:
        return
    notify(f"Téléchargement depuis le cloud : {', '.join(p.name for p in todo[:3])}…")
    if IS_MAC:          # tous les téléchargements demandés d'un coup (en parallèle), avant de lire
        for p in todo:
            try:
                subprocess.Popen(["brctl", "download", str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass
    for p in todo:
        try:      # une lecture complète déclenche le téléchargement
            with open(p, "rb") as fh:
                while fh.read(1 << 20):
                    pass
        except OSError:
            pass
        if IS_MAC and _in_cloud(p):
            subprocess.run(["brctl", "download", str(p)], capture_output=True)
    t0 = _t.time()
    while _t.time() - t0 < timeout:
        left = [p for p in todo if _in_cloud(p)]
        if not left:
            log(f"cloud : {len(todo)} fichier(s) téléchargé(s) en {_t.time() - t0:.1f} s")
            return
        _t.sleep(0.3)
    raise RuntimeError(f"« {left[0].name} » est dans le cloud et n'a pas pu être téléchargé "
                       "(connexion Internet ?). Ouvre-le une fois dans le Finder / l'Explorateur puis réessaie.")


def safe_port():
    """Port libre pour le petit serveur local de pywebview, hors des ports que Chromium/WebView2 refuse
    (ex. 6697 → « ERR_UNSAFE_PORT », page blanche). Les ports éphémères (≥ 49152) ne sont jamais bloqués."""
    import random, socket
    for _ in range(50):
        p = random.randint(49200, 65000)
        with socket.socket() as so:
            try:
                so.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return None


def open_path(p):
    if IS_WIN:
        os.startfile(str(p))
    elif IS_LINUX:
        subprocess.Popen(["xdg-open", str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    else:
        subprocess.run(["open", str(p)])


def reveal(p):
    if IS_WIN:
        subprocess.Popen(f'explorer /select,"{p}"')
    elif IS_LINUX:
        # interface standard des gestionnaires de fichiers (Nautilus, Dolphin, Thunar, Nemo…)
        r = subprocess.run(["dbus-send", "--session", "--print-reply", "--dest=org.freedesktop.FileManager1",
                            "--type=method_call", "/org/freedesktop/FileManager1",
                            "org.freedesktop.FileManager1.ShowItems",
                            f"array:string:{Path(p).resolve().as_uri()}", "string:"],
                           capture_output=True, timeout=5)
        if r.returncode != 0:
            open_path(Path(p).resolve().parent)
    else:
        subprocess.run(["open", "-R", str(p)])


def font_file():
    for c in ("/System/Library/Fonts/Helvetica.ttc", r"C:\Windows\Fonts\segoeui.ttf",
              r"C:\Windows\Fonts\arial.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf",
              "/usr/share/fonts/noto/NotoSans-Regular.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/liberation/LiberationSans-Regular.ttf"):
        if os.path.exists(c):
            return c
    return "DejaVuSans.ttf"

# ───────────────────────── journal, dialogues ─────────────────────────

class Cancel(Exception):
    pass


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception:
        pass


# Dialogues : fournis par l'interface qui charge ce module (wheel.py les remplace au démarrage, les tests aussi).
def _no_ui(*a, **k):
    raise RuntimeError("Interface non chargée : lance FileForge par la roue (wheel.py).")


choose = ask = buttons = choose_file = _no_ui


def alert(title, msg=""):
    log(f"{title} {msg}")


def notify(msg):
    pass

# ───────────────────────── utilitaires fichiers ─────────────────────────

PDF = {"pdf"}
IMG = {"jpg", "jpeg", "png", "heic", "heif", "webp", "tif", "tiff", "bmp", "gif", "avif"}
VID = {"mp4", "mov", "m4v", "mkv", "avi", "webm", "wmv", "flv", "mpg", "mpeg", "3gp"}
AUD = {"mp3", "wav", "m4a", "aac", "flac", "ogg", "opus", "aiff", "aif", "wma"}
WORDS = {"docx", "doc", "rtf", "odt"}
OFFICE = WORDS | {"pptx", "ppt", "odp", "xlsx", "xls", "ods"}
TEXT = {"txt", "md", "markdown", "html", "htm"}
TEX = {"tex"}
TAB = {"csv", "tsv", "xlsx", "xls", "ods", "json"}
ARC = {"zip", "tar", "gz", "tgz", "bz2", "xz"}


def ext(p):
    p = str(p)
    for double in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if p.lower().endswith(double):
            return "tar"
    return Path(p).suffix.lower().lstrip(".")


def natural(p):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", Path(p).name.lower())]


def unique(p):
    p = Path(p)
    if not p.exists():
        return p
    i = 2
    while True:
        c = p.with_name(f"{p.stem} ({i}){p.suffix}")
        if not c.exists():
            return c
        i += 1


def out(src, tag, new_ext=None):
    src = Path(src)
    e = new_ext or src.suffix.lstrip(".")
    return unique(src.with_name(f"{src.stem}_{tag}.{e}"))


def outdir(src, tag):
    d = unique(Path(src).with_name(f"{Path(src).stem}_{tag}"))
    d.mkdir(parents=True)
    return d


def human(n):
    for u in ("o", "Ko", "Mo", "Go"):
        if n < 1024:
            return f"{n:.0f} {u}" if u == "o" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} To"


def size_note(src, dst):
    a, b = Path(src).stat().st_size, Path(dst).stat().st_size
    pct = (1 - b / a) * 100 if a else 0
    if b < a:
        NOTES.append(f"{Path(src).name} : {human(a)} → {human(b)} (−{pct:.0f} %)")
    else:
        NOTES.append(f"{Path(src).name} : pas de gain possible ({human(a)} → {human(b)}).")


def parse_ranges(s, n):
    """'1-3, 5, 8-fin' -> indices 0-based. Supporte les plages décroissantes (5-1)."""
    s = s.replace(" ", "").lower()
    if s in ("", "tout", "toutes", "all", "*"):
        return list(range(n))
    def num(x):
        if x in ("fin", "end"):
            return n
        if not x.isdigit():
            raise ValueError(f"« {part} » n'est pas compris (exemple : 1-3, 5, 8-fin).")
        v = int(x)
        if not 1 <= v <= n:
            raise ValueError(f"Page {v} hors limites (le document a {n} page{'s' if n > 1 else ''}).")
        return v

    res = []
    for part in s.split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a = 1 if a == "" else num(a)
            b = n if b == "" else num(b)
            step = 1 if b >= a else -1
            res += list(range(a, b + step, step))
        else:
            res.append(num(part))
    return [p - 1 for p in res]


def ask_pages(prompt, default, n, allow_empty=False):
    """Demande des numéros de pages ; en cas de saisie invalide, explique et redemande."""
    msg = prompt
    while True:
        s = ask(msg, default)
        if allow_empty and not s.strip():
            return []
        try:
            r = parse_ranges(s, n)
            if r:
                return r
            raise ValueError("Aucune page indiquée.")
        except ValueError as e:
            msg = f"⚠ {e}\n\n{prompt}"
            default = s


def ask_int(prompt, default, lo=1):
    q = prompt
    while True:
        v = ask(q, default).strip()
        if v.isdigit() and int(v) >= lo:
            return int(v)
        q, default = f"⚠ Indique un nombre entier (au moins {lo}).\n\n{prompt}", v


def parse_time(s):
    """« 83 », « 1:23 » ou « 0:01:23 » → secondes ; vide → None."""
    s = s.strip().replace(",", ".")
    if not s:
        return None
    if not re.fullmatch(r"\d+(\.\d+)?(:\d+(\.\d+)?){0,2}", s):
        raise ValueError(f"« {s} » n'est pas un moment compris (exemples : 83, 1:23, 0:01:23).")
    parts = [float(x) for x in s.split(":")]
    t = 0.0
    for x in parts:
        t = t * 60 + x
    return t


def install_hint(what):
    """Comment installer un composant manquant, selon le système."""
    if IS_WIN:
        return {"libreoffice": "Relance l'installateur de FileForge et coche LibreOffice, ou télécharge-le sur fr.libreoffice.org."
                }.get(what, f"Réinstalle FileForge pour récupérer {what}.")
    if IS_LINUX:
        return {"libreoffice": "sudo pacman -S libreoffice-fresh (ou apt install libreoffice)",
                "tesseract": "sudo pacman -S tesseract tesseract-data-fra", "ffmpeg": "sudo pacman -S ffmpeg"}.get(what, "")
    return {"libreoffice": "brew install --cask libreoffice", "tesseract": "brew install tesseract",
            "ffmpeg": "brew install ffmpeg"}.get(what, "")


def which(name, *extra):
    p = shutil.which(name)
    if p:
        return p
    for c in extra:
        if os.path.exists(c):
            return c
    return None


FFMPEG = which("ffmpeg", "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg")
if not FFMPEG:
    try:
        import imageio_ffmpeg
        FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        FFMPEG = None


def ff(*args):
    if not FFMPEG:
        raise RuntimeError("ffmpeg est introuvable. " + install_hint("ffmpeg"))
    r = subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *map(str, args)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        Path(str(args[-1])).unlink(missing_ok=True)        # la sortie (toujours en dernier) : pas de fichier cassé
        raise RuntimeError("ffmpeg : " + (r.stderr.strip().splitlines() or ["erreur"])[-1])


_ENC = {}


def has_encoder(name):
    """Le ffmpeg trouvé sait-il encoder avec `name` ? (celui de Homebrew n'a pas libvorbis, par exemple)"""
    if name not in _ENC:
        try:
            r = subprocess.run([FFMPEG, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20)
            _ENC.update({ln.split()[1]: True for ln in r.stdout.splitlines() if len(ln.split()) > 1 and ln.startswith(" ")})
        except Exception:
            pass
        _ENC.setdefault(name, False)
    return _ENC[name]


def has_audio(f):
    if not FFMPEG:
        return True
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", str(f)], capture_output=True, text=True)
    return "Audio:" in r.stderr


def need_audio(f):
    if not has_audio(f):
        raise ValueError(f"« {Path(f).name} » n'a pas de son.")

# ───────────────────────── registre des actions ─────────────────────────

ACTIONS = []


def action(label, types=None, minf=1):
    def deco(fn):
        ACTIONS.append(dict(label=label, types=types, minf=minf, fn=fn))
        return fn
    return deco

# ───────────────────────── fenêtres visuelles (Tk) ─────────────────────────

def _front(root):
    try:
        import AppKit
        AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except Exception:
        pass
    root.lift()
    root.attributes("-topmost", True)
    root.after(600, lambda: root.attributes("-topmost", False))
    root.focus_force()


def pick_regions(src, kind, title, hint, multi=False, start_page=0):
    """Fenêtre où l'utilisateur dessine des rectangles.
    kind='pdf' (src = document pymupdf) ou 'img' (src = image PIL).
    Retourne {page_index: [(x0,y0,x1,y1), ...]} en coordonnées source."""
    import tkinter as tk
    from PIL import Image, ImageTk
    root = tk.Tk()
    root.title(f"{APP} — {title}")
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    MW, MH = int(sw * 0.8), int(sh * 0.70)
    if kind == "pdf":
        import pymupdf
        n = src.page_count

        def render(i):
            R = src[i].rect
            z = min(MW / R.width, MH / R.height)
            pix = src[i].get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples), z
    else:
        n = 1
        base = src.convert("RGB")

        def render(i):
            z = min(MW / base.width, MH / base.height, 1.0)
            return base.resize((max(1, int(base.width * z)), max(1, int(base.height * z)))), z

    st = {"i": min(start_page, n - 1), "z": 1.0, "tk": None, "w": 1, "h": 1}
    sel = {}
    tk.Label(root, text=hint, justify="left", font=("Helvetica", 13)).pack(padx=14, pady=(12, 6), anchor="w")
    c = tk.Canvas(root, highlightthickness=1, highlightbackground="#999", cursor="crosshair")
    c.pack(padx=14)
    bar = tk.Frame(root)
    bar.pack(fill="x", padx=14, pady=12)
    lbl = tk.Label(bar, font=("Helvetica", 12))

    def show():
        img, z = render(st["i"])
        st.update(z=z, tk=ImageTk.PhotoImage(img), w=img.width, h=img.height)
        c.config(width=img.width, height=img.height)
        c.delete("all")
        c.create_image(0, 0, image=st["tk"], anchor="nw")
        for r in sel.get(st["i"], []):
            c.create_rectangle(*[v * z for v in r], outline="#e11d48", width=3)
        lbl.config(text=f"Page {st['i'] + 1} / {n}")

    drag = {"s": None, "id": None}

    def down(e):
        drag["s"] = (e.x, e.y)
        drag["id"] = c.create_rectangle(e.x, e.y, e.x, e.y, outline="#e11d48", width=2, dash=(6, 3))

    def move(e):
        if drag["id"]:
            x0, y0 = drag["s"]
            c.coords(drag["id"], x0, y0, e.x, e.y)

    def up(e):
        if not drag["id"]:
            return
        x0, y0 = drag["s"]
        drag["id"] = None
        W, H = st["w"], st["h"]
        x0, x1 = sorted((max(0, min(W, x0)), max(0, min(W, e.x))))
        y0, y1 = sorted((max(0, min(H, y0)), max(0, min(H, e.y))))
        if x1 - x0 >= 6 and y1 - y0 >= 6:
            z = st["z"]
            r = (x0 / z, y0 / z, x1 / z, y1 / z)
            if multi:
                sel.setdefault(st["i"], []).append(r)
            else:
                sel.clear()
                sel[st["i"]] = [r]
        show()

    c.bind("<ButtonPress-1>", down)
    c.bind("<B1-Motion>", move)
    c.bind("<ButtonRelease-1>", up)

    def nav(d):
        st["i"] = (st["i"] + d) % n
        show()

    if n > 1:
        tk.Button(bar, text="◀", width=3, command=lambda: nav(-1)).pack(side="left")
        lbl.pack(side="left", padx=8)
        tk.Button(bar, text="▶", width=3, command=lambda: nav(1)).pack(side="left")
        root.bind("<Left>", lambda e: nav(-1))
        root.bind("<Right>", lambda e: nav(1))
    res = {"ok": False}

    def clear():
        if multi:
            sel.pop(st["i"], None)
        else:
            sel.clear()
        show()

    def ok():
        if not sel:
            root.bell()
            return
        res["ok"] = True
        root.destroy()

    tk.Button(bar, text="Valider ✓", command=ok, default="active").pack(side="right")
    tk.Button(bar, text="Annuler", command=root.destroy).pack(side="right", padx=6)
    tk.Button(bar, text="Effacer", command=clear).pack(side="right")
    root.bind("<Return>", lambda e: ok())
    root.bind("<Escape>", lambda e: root.destroy())
    show()
    _front(root)
    root.mainloop()
    if not res["ok"]:
        raise Cancel()
    return sel


SIG_FILE = HOME_DIR / "signature.png"


def draw_signature():
    import tkinter as tk
    from PIL import Image, ImageDraw
    W, H, S = 640, 240, 3
    big = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
    dr = ImageDraw.Draw(big)
    ink = (12, 30, 90, 255)
    root = tk.Tk()
    root.title(f"{APP} — Dessine ta signature")
    tk.Label(root, text="Signe avec la souris ou le trackpad, puis clique « Valider ».",
             font=("Helvetica", 13)).pack(padx=14, pady=(12, 6))
    c = tk.Canvas(root, width=W, height=H, bg="white", highlightthickness=1, highlightbackground="#999", cursor="pencil")
    c.pack(padx=14)
    st = {"last": None, "drawn": False, "ok": False}

    def dot(x, y):
        r = 1.6 * S
        dr.ellipse([x * S - r, y * S - r, x * S + r, y * S + r], fill=ink)

    def down(e):
        st["last"] = (e.x, e.y)
        dot(e.x, e.y)

    def move(e):
        if st["last"]:
            x0, y0 = st["last"]
            c.create_line(x0, y0, e.x, e.y, width=3, capstyle="round", fill="#0c1e5a")
            dr.line([(x0 * S, y0 * S), (e.x * S, e.y * S)], fill=ink, width=int(3.2 * S))
            dot(e.x, e.y)
            st["last"] = (e.x, e.y)
            st["drawn"] = True

    def up(e):
        st["last"] = None

    def clear():
        c.delete("all")
        dr.rectangle([0, 0, W * S, H * S], fill=(0, 0, 0, 0))
        st["drawn"] = False

    def ok():
        if st["drawn"]:
            st["ok"] = True
            root.destroy()

    c.bind("<ButtonPress-1>", down)
    c.bind("<B1-Motion>", move)
    c.bind("<ButtonRelease-1>", up)
    bar = tk.Frame(root)
    bar.pack(fill="x", padx=14, pady=12)
    tk.Button(bar, text="Valider ✓", command=ok).pack(side="right")
    tk.Button(bar, text="Annuler", command=root.destroy).pack(side="right", padx=6)
    tk.Button(bar, text="Effacer", command=clear).pack(side="left")
    _front(root)
    root.mainloop()
    if not st["ok"]:
        raise Cancel()
    img = big.crop(big.getbbox())
    img.save(SIG_FILE)
    return SIG_FILE

# ───────────────────────── PDF ─────────────────────────

def open_pdf(path):
    import pymupdf
    materialize([path])
    try:
        d = pymupdf.open(str(path))
    except Exception as e:
        if not Path(path).exists():
            raise RuntimeError(f"« {Path(path).name} » est introuvable.") from e
        raise RuntimeError(f"« {Path(path).name} » n'est pas un PDF lisible (fichier abîmé, incomplet ou d'un autre format).") from e
    if d.needs_pass:
        pw = ask(f"« {Path(path).name} » est protégé par un mot de passe.\nMot de passe :", hidden=True)
        if not d.authenticate(pw):
            raise RuntimeError("Mot de passe incorrect.")
        d._ff_password = pw
    return d


def save_pdf(doc, dst, **kw):
    kw.setdefault("garbage", 3)
    kw.setdefault("deflate", True)
    doc.save(str(dst), **kw)
    return dst


def _heif():
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        try:
            pillow_heif.register_avif_opener()
        except Exception:
            pass
    except Exception:
        pass


def img_jpeg_bytes(f):
    from PIL import Image, ImageOps
    _heif()
    im = ImageOps.exif_transpose(Image.open(f))
    im = flatten(im)
    b = io.BytesIO()
    im.save(b, "JPEG", quality=92)
    return b.getvalue(), im.size


def add_image_page(doc, f, fit_a4=True):
    import pymupdf
    data, (w, h) = img_jpeg_bytes(f)
    if fit_a4:
        r = pymupdf.paper_rect("a4")
        if w > h:
            r = pymupdf.Rect(0, 0, r.height, r.width)
        page = doc.new_page(width=r.width, height=r.height)
        page.insert_image(page.rect + (28, 28, -28, -28), stream=data, keep_proportion=True)
    else:
        page = doc.new_page(width=w * 0.75, height=h * 0.75)
        page.insert_image(page.rect, stream=data)


def crop_page(page, l, t, r, b):
    import pymupdf
    R = page.rect
    v = pymupdf.Rect(R.x0 + l, R.y0 + t, R.x1 - r, R.y1 - b)
    if v.is_empty or v.width < 10 or v.height < 10:
        raise ValueError("La zone à conserver est trop petite.")
    u = v * page.derotation_matrix
    u.normalize()
    cb = page.cropbox
    new = pymupdf.Rect(cb.x0 + u.x0, cb.y0 + u.y0, cb.x0 + u.x1, cb.y0 + u.y1)
    page.set_cropbox(new & page.mediabox)


def to_page(page, r):
    """Rectangle vu à l'écran (page éventuellement pivotée) → coordonnées PDF de la page non pivotée."""
    import pymupdf
    u = pymupdf.Rect(r) * page.derotation_matrix
    u.normalize()
    return u


def content_bbox(page):
    import pymupdf
    R = page.rect
    area = R.width * R.height
    bb = pymupdf.Rect()
    for kind, rect in page.get_bboxlog():
        r = pymupdf.Rect(rect) & R
        if r.is_empty or r.width * r.height > 0.92 * area:
            continue  # ignore les fonds pleine page
        bb |= r
    return bb


def spawn(script, *args):
    """Lance un autre programme de FileForge dans son propre processus, détaché de la roue (qui se ferme aussitôt) ;
    ses erreurs de démarrage vont dans le journal."""
    exe = Path(sys.executable)
    if IS_WIN and exe.name.lower() == "python.exe" and (exe.parent / "pythonw.exe").exists():
        exe = exe.parent / "pythonw.exe"
    lf = open(LOG, "a", encoding="utf-8")
    kw = {"cwd": tempfile.gettempdir(), "stdout": lf, "stderr": lf, "stdin": subprocess.DEVNULL}
    if IS_WIN:
        kw["creationflags"] = 0x08000000 | 0x00000200   # sans console, nouveau groupe
    else:
        kw["start_new_session"] = True
    try:
        return subprocess.Popen([str(exe), str(Path(__file__).with_name(script)), *map(str, args)], **kw)
    finally:
        lf.close()


def launch_editor(f):
    return spawn("editor.py", f)


@action("📄 PDF · Modifier (éditeur)", PDF)
def pdf_edit(files):
    for f in files[:4]:
        launch_editor(f)
    return []


@action("📄 PDF · Fusionner en un seul PDF", PDF | IMG, minf=2)
def pdf_merge(files):
    import pymupdf
    od = pymupdf.open()
    for f in files:
        if ext(f) == "pdf":
            od.insert_pdf(open_pdf(f))
        else:
            add_image_page(od, f)
    NOTES.append("Ordre : alphabétique (renomme les fichiers 01_, 02_… pour imposer un ordre).")
    return [save_pdf(od, unique(Path(files[0]).with_name("Fusion.pdf")))]


@action("📄 PDF · Diviser", PDF)
def pdf_split(files):
    import pymupdf
    mode = choose(["Une page = un PDF", "Toutes les N pages", "Selon des plages (ex : 1-3; 4-8; 9-fin)"],
                  "Comment diviser ?")
    k = ask_int("Nombre de pages par fichier :", "2") if mode.startswith("Toutes") else 0
    outs = []
    for f in files:
        doc = open_pdf(f)
        n = doc.page_count
        if mode.startswith("Une"):
            groups = [[i] for i in range(n)]
        elif k:
            groups = [list(range(i, min(i + k, n))) for i in range(0, n, k)]
        else:
            q, s = f"« {Path(f).name} » ({n} pages)\nPlages séparées par des points-virgules :", "1-2; 3-fin"
            while True:
                s = ask(q, s)
                try:
                    groups = [parse_ranges(g, n) for g in s.split(";") if g.strip()]
                    if groups:
                        break
                except ValueError as e:
                    q = f"⚠ {e if not str(e).startswith('invalid') else 'Saisie non comprise.'}\n\n« {Path(f).name} » ({n} pages)\nPlages séparées par des points-virgules :"
        d = outdir(f, "divisé")
        for gi, g in enumerate(groups, 1):
            nd = pymupdf.open()
            for p in g:
                nd.insert_pdf(doc, from_page=p, to_page=p)
            lab = f"p{g[0] + 1}" if len(g) == 1 else f"p{g[0] + 1}-{g[-1] + 1}"
            save_pdf(nd, d / f"{Path(f).stem}_{gi:03d}_{lab}.pdf")
        outs.append(d)
    return outs


@action("📄 PDF · Extraire des pages", PDF)
def pdf_extract(files):
    outs = []
    for f in files:
        doc = open_pdf(f)
        if doc.page_count < 2:
            raise ValueError(f"« {Path(f).name} » n'a qu'une seule page : rien à extraire.")
        sel = ask_pages(f"Pages à extraire de « {Path(f).name} » ({doc.page_count} pages)\n"
                        "ex : 1-3, 5, 8-fin", "1", doc.page_count)
        doc.select(sel)
        outs.append(save_pdf(doc, out(f, "extrait")))
    return outs


@action("📄 PDF · Supprimer des pages", PDF)
def pdf_delete(files):
    outs = []
    for f in files:
        doc = open_pdf(f)
        n = doc.page_count
        if n < 2:
            raise ValueError(f"« {Path(f).name} » n'a qu'une seule page.")
        q = f"Pages à SUPPRIMER de « {Path(f).name} » ({n} pages)\nex : 2, 5-7"
        while True:
            rm = set(ask_pages(q, "", n))
            if len(rm) < n:
                break
            q = f"⚠ Impossible de supprimer toutes les pages.\n\nPages à SUPPRIMER de « {Path(f).name} » ({n} pages)"
        keep = [i for i in range(n) if i not in rm]
        if not keep:
            raise ValueError("Impossible de supprimer toutes les pages.")
        doc.select(keep)
        outs.append(save_pdf(doc, out(f, "modifié")))
    return outs


@action("📄 PDF · Réorganiser / inverser les pages", PDF)
def pdf_reorder(files):
    mode = choose(["Inverser l'ordre des pages", "Ordre personnalisé…"], "Réorganiser :")
    outs = []
    for f in files:
        doc = open_pdf(f)
        n = doc.page_count
        if mode.startswith("Inverser"):
            order = list(range(n - 1, -1, -1))
        else:
            order = ask_pages(f"Nouvel ordre pour « {Path(f).name} » ({n} pages)\n"
                              "ex : 3, 1, 2, 4-fin   (une page peut être répétée)", f"1-{n}", n)
        doc.select(order)
        outs.append(save_pdf(doc, out(f, "réorganisé")))
    return outs


@action("📄 PDF · Pivoter des pages", PDF)
def pdf_rotate(files):
    a = choose(["90° vers la droite", "90° vers la gauche", "180°"], "Rotation :")
    angle = {"90° vers la droite": 90, "90° vers la gauche": 270, "180°": 180}[a]
    outs = []
    for f in files:
        doc = open_pdf(f)
        pages = ask_pages(f"Pages à pivoter de « {Path(f).name} » ({doc.page_count} pages)\nex : 1, 3-5 — « tout » pour toutes",
                          "tout", doc.page_count) if doc.page_count > 1 else [0]
        for p in pages:
            pg = doc[p]
            pg.set_rotation((pg.rotation + angle) % 360)
        outs.append(save_pdf(doc, out(f, "pivoté")))
    return outs


@action("📄 PDF · Compresser", PDF)
def pdf_compress(files):
    lvl = choose(["Légère (qualité maximale)", "Recommandée", "Forte (taille minimale)"],
                 "Niveau de compression :", default="Recommandée")
    thr, tgt, q = {"L": (220, 150, 85), "R": (160, 120, 70), "F": (110, 85, 50)}[lvl[0]]
    outs = []
    for f in files:
        doc = open_pdf(f)
        try:
            doc.rewrite_images(dpi_threshold=thr, dpi_target=tgt, quality=q)
        except Exception as e:
            log(f"rewrite_images: {e}")
        try:
            doc.subset_fonts()
        except Exception:
            pass
        dst = out(f, "compressé")
        doc.save(str(dst), garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True)
        size_note(f, dst)
        outs.append(dst)
    return outs


@action("📄 PDF · Rogner", PDF)
def pdf_crop(files):
    mode = choose(["Visuellement (je dessine la zone à garder)", "Retirer des marges (en mm)",
                   "Supprimer automatiquement les marges blanches"], "Comment rogner ?")
    mm = 72 / 25.4
    outs = []
    for f in files:
        doc = open_pdf(f)
        if mode.startswith("Visuel"):
            sel = pick_regions(doc, "pdf", "Rogner",
                               "Dessine un rectangle autour de la zone à GARDER.\n"
                               "Navigue avec ◀ ▶ pour vérifier les autres pages.")
            pi, [r] = next(iter(sel.items()))
            R = doc[pi].rect
            fr = (r[0] / R.width, r[1] / R.height, r[2] / R.width, r[3] / R.height)   # zone en proportions
            scope = choose(["Toutes les pages", f"Seulement la page {pi + 1}"], "Appliquer le rognage à :")
            targets = range(doc.page_count) if scope.startswith("Toutes") else [pi]
            for p in targets:
                Q = doc[p].rect
                if p == pi or (abs(Q.width - R.width) < 1 and abs(Q.height - R.height) < 1):
                    crop_page(doc[p], r[0], r[1], R.width - r[2], R.height - r[3])
                else:   # page d'un autre format : même zone, proportionnellement
                    crop_page(doc[p], fr[0] * Q.width, fr[1] * Q.height, (1 - fr[2]) * Q.width, (1 - fr[3]) * Q.height)
        elif mode.startswith("Retirer"):
            raw = ask("Marges à retirer en mm : haut, droite, bas, gauche\n(une seule valeur = partout)", "10")
            try:
                r = raw.strip()
                if ";" not in r and " " not in r and r.count(",") >= 2:   # « 10,5,10,5 » : virgules = séparateurs
                    parts = r.split(",")
                else:                                                    # « 10; 5 », « 10, 5 », « 2,5 » (décimale)
                    parts = re.split(r"[; ]+|,(?=\s)", r)
                v = [float(x.replace(",", ".")) * mm for x in parts if x]
            except ValueError:
                raise ValueError(f"« {raw} » : indique des nombres en mm, par exemple « 10 » ou « 10; 5; 10; 5 ».") from None
            if not v or any(x < 0 for x in v):
                raise ValueError("Indique des marges positives en mm.")
            t, rr, b, l = (v * 4)[:4] if len(v) == 1 else (v + [0, 0, 0, 0])[:4]
            for pg in doc:
                crop_page(pg, l, t, rr, b)
        else:
            pad = 8
            for pg in doc:
                bb = content_bbox(pg)
                if bb.is_empty:
                    continue
                R = pg.rect
                crop_page(pg, max(0, bb.x0 - pad), max(0, bb.y0 - pad),
                          max(0, R.width - bb.x1 - pad), max(0, R.height - bb.y1 - pad))
        outs.append(save_pdf(doc, out(f, "rogné")))
    return outs


@action("📄 PDF · Convertir en images (JPG / PNG)", PDF)
def pdf_to_images(files):
    fmt = choose(["JPG", "PNG"], "Format des images :")
    dpi = int(choose(["100", "150", "200", "300"], "Résolution (DPI) — 150 écran, 300 impression :", default="150"))
    outs = []
    for f in files:
        doc = open_pdf(f)
        d = outdir(f, "images")
        for i, pg in enumerate(doc, 1):
            pix = pg.get_pixmap(dpi=dpi, alpha=False)
            p = d / f"{Path(f).stem}_page{i:03d}.{fmt.lower()}"
            if fmt == "JPG":
                pix.save(str(p), jpg_quality=90)
            else:
                pix.save(str(p))
        outs.append(d)
    return outs


@action("📄 PDF · Convertir en Word (.docx)", PDF)
def pdf_to_word(files):
    from pdf2docx import Converter
    outs = []
    notify("Conversion en Word en cours…")
    for f in files:
        doc = open_pdf(f)                     # vérifie le fichier et le mot de passe avec un message clair
        pw = getattr(doc, "_ff_password", None)
        doc.close()
        dst = unique(Path(f).with_suffix(".docx"))
        cv = Converter(str(f), password=pw)
        try:
            cv.convert(str(dst))
        except BaseException:
            dst.unlink(missing_ok=True)
            raise
        finally:
            cv.close()
        outs.append(dst)
    return outs


@action("📄 PDF · Convertir en PowerPoint (.pptx)", PDF)
def pdf_to_pptx(files):
    from pptx import Presentation
    from pptx.util import Emu
    outs = []
    for f in files:
        doc = open_pdf(f)
        prs = Presentation()
        R = doc[0].rect
        W, H = int(R.width * 12700), int(R.height * 12700)
        prs.slide_width, prs.slide_height = Emu(W), Emu(H)
        for pg in doc:
            pix = pg.get_pixmap(dpi=170, alpha=False)
            s = prs.slides.add_slide(prs.slide_layouts[6])
            k = min(W / pg.rect.width, H / pg.rect.height)       # page d'un autre format : centrée, sans déformation
            w, h = int(pg.rect.width * k), int(pg.rect.height * k)
            s.shapes.add_picture(io.BytesIO(pix.tobytes("png")), Emu((W - w) // 2), Emu((H - h) // 2), Emu(w), Emu(h))
        dst = unique(Path(f).with_suffix(".pptx"))
        prs.save(str(dst))
        outs.append(dst)
    NOTES.append("Chaque page devient une diapositive (image).")
    return outs


@action("📄 PDF · Convertir en Excel (tableaux)", PDF)
def pdf_to_excel(files):
    import openpyxl
    outs = []
    for f in files:
        doc = open_pdf(f)
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        count = 0
        for pno, pg in enumerate(doc, 1):
            for ti, t in enumerate(pg.find_tables().tables, 1):
                ws = wb.create_sheet(f"Page{pno}_Tableau{ti}"[:31])
                for row in t.extract():
                    ws.append(["" if c is None else str(c).replace("\n", " ") for c in row])
                count += 1
        if not count:
            ws = wb.create_sheet("Texte")
            for pg in doc:
                for line in pg.get_text().splitlines():
                    ws.append(re.split(r"\s{2,}", line.strip()))
            NOTES.append(f"{Path(f).name} : aucun tableau détecté, texte exporté ligne par ligne.")
        else:
            NOTES.append(f"{Path(f).name} : {count} tableau(x) extrait(s).")
        dst = unique(Path(f).with_suffix(".xlsx"))
        wb.save(str(dst))
        outs.append(dst)
    return outs


@action("📄 PDF · Convertir en texte / Markdown", PDF)
def pdf_to_text(files):
    fmt = choose(["Markdown (.md) — garde titres et tableaux", "Texte brut (.txt)"], "Format :")
    outs = []
    for f in files:
        doc = open_pdf(f)
        if fmt.startswith("Markdown"):
            import pymupdf4llm
            txt, e = pymupdf4llm.to_markdown(doc), "md"
        else:
            txt, e = "\n\n".join(p.get_text() for p in doc), "txt"
        if not txt.strip():
            # document scanné : pas de texte, on passe par l'OCR
            langs = tess_langs()
            if not langs:
                raise ValueError(f"« {Path(f).name} » ne contient aucun texte (document scanné). "
                                 "Utilise d'abord « OCR ». " + install_hint("tesseract"))
            lang = ocr_lang(langs)
            notify("Document scanné : reconnaissance du texte (OCR)…")
            txt = "\n\n".join(p.get_textpage_ocr(language=lang, dpi=300, full=True).extractText() for p in doc)
            NOTES.append("Document scanné : texte obtenu par OCR.")
            if not txt.strip():
                raise ValueError(f"Aucun texte trouvé dans « {Path(f).name} », même par OCR.")
        dst = unique(Path(f).with_suffix("." + e))
        dst.write_text(txt, encoding="utf-8")
        outs.append(dst)
    return outs


@action("📄 PDF · Extraire les images", PDF)
def pdf_extract_images(files):
    outs = []
    for f in files:
        doc = open_pdf(f)
        d = outdir(f, "images_extraites")
        seen, k = set(), 0
        for pg in doc:
            for img in pg.get_images(full=True):
                x = img[0]
                if x in seen:
                    continue
                seen.add(x)
                info = doc.extract_image(x)
                if not info or info["width"] < 32 or info["height"] < 32:
                    continue
                k += 1
                (d / f"image_{k:03d}.{info['ext']}").write_bytes(info["image"])
        NOTES.append(f"{Path(f).name} : {k} image(s) extraite(s).")
        outs.append(d)
    return outs


@action("🔒 PDF · Protéger par mot de passe", PDF)
def pdf_protect(files):
    import pymupdf
    pw = ask("Mot de passe à définir :", hidden=True)
    if not pw:
        raise ValueError("Mot de passe vide.")
    if ask("Confirme le mot de passe :", hidden=True) != pw:
        raise ValueError("Les mots de passe ne correspondent pas.")
    outs = []
    for f in files:
        doc = open_pdf(f)
        dst = out(f, "protégé")
        doc.save(str(dst), garbage=3, deflate=True, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw=pw, user_pw=pw)
        outs.append(dst)
    NOTES.append("Chiffrement AES-256.")
    return outs


@action("🔓 PDF · Retirer le mot de passe / les restrictions", PDF)
def pdf_unlock(files):
    import pymupdf
    outs = []
    for f in files:
        doc = open_pdf(f)
        # ne pas relire doc.needs_pass après authenticate : PyMuPDF enregistrerait alors des pages vides
        if not (doc.metadata or {}).get("encryption"):
            NOTES.append(f"{Path(f).name} n'était pas protégé.")
        outs.append(save_pdf(doc, out(f, "déverrouillé"), encryption=pymupdf.PDF_ENCRYPT_NONE))
    return outs


@action("💧 PDF · Ajouter un filigrane", PDF)
def pdf_watermark(files):
    import pymupdf
    text = ask("Texte du filigrane :", "CONFIDENTIEL").strip()
    if not text:
        raise ValueError("Texte du filigrane vide.")
    op = {"Discret": 0.12, "Normal": 0.22, "Marqué": 0.4}[choose(["Discret", "Normal", "Marqué"], "Intensité :", default="Normal")]
    outs = []
    for f in files:
        doc = open_pdf(f)
        for pg in doc:
            R = pg.rect
            diag = math.hypot(R.width, R.height)
            fs = min(diag * 0.7 / max(pymupdf.get_text_length(text, "helv", 1), 1), 160)
            tl = pymupdf.get_text_length(text, "helv", fs)
            ctr = pymupdf.Point(R.width / 2, R.height / 2)
            ang = math.degrees(math.atan2(R.height, R.width))
            dr = pg.derotation_matrix          # géométrie calculée sur la page vue, posée sur la page PDF
            pg.insert_text(pymupdf.Point(ctr.x - tl / 2, ctr.y + fs * 0.35) * dr, text, fontsize=fs, fontname="helv",
                           color=(0.55, 0.55, 0.55), fill_opacity=op, rotate=pg.rotation,
                           morph=(ctr * dr, pymupdf.Matrix(ang)), overlay=True)
        outs.append(save_pdf(doc, out(f, "filigrane")))
    return outs


@action("🔢 PDF · Numéroter les pages", PDF)
def pdf_numbers(files):
    import pymupdf
    fmt = choose(["1", "Page 1 / N", "1 / N", "- 1 -"], "Format :", default="Page 1 / N")
    pos = choose(["Bas centre", "Bas droite", "Bas gauche", "Haut droite"], "Position :", default="Bas centre")
    first = ask_int("Commencer la numérotation à partir de la page :", "1")
    outs = []
    for f in files:
        doc = open_pdf(f)
        N = doc.page_count - first + 1
        for i, pg in enumerate(doc):
            if i + 1 < first:
                continue
            k = i + 2 - first
            s = {"1": f"{k}", "Page 1 / N": f"Page {k} / {N}", "1 / N": f"{k} / {N}", "- 1 -": f"- {k} -"}[fmt]
            R, fs = pg.rect, 10
            tl = pymupdf.get_text_length(s, "helv", fs)
            x = {"centre": (R.width - tl) / 2, "droite": R.width - tl - 36, "gauche": 36}[pos.split()[-1]]
            y = 28 if pos.startswith("Haut") else R.height - 22
            pg.insert_text(pymupdf.Point(x, y) * pg.derotation_matrix, s, fontsize=fs, fontname="helv",
                           color=(0.25, 0.25, 0.25), rotate=pg.rotation)
        outs.append(save_pdf(doc, out(f, "numéroté")))
    return outs


@action("✍️ PDF · Signer (dessiner ou insérer une signature)", PDF)
def pdf_sign(files):
    opts = (["Utiliser ma signature enregistrée"] if SIG_FILE.exists() else []) + \
        ["Dessiner une signature", "Choisir une image (PNG, JPG…)"]
    m = choose(opts, "Signature :")
    if m.startswith("Utiliser"):
        sig = SIG_FILE
    elif m.startswith("Dessiner"):
        sig = draw_signature()
    else:
        sig = Path(choose_file("Choisis l'image de ta signature", ["public.image"]))
    # image lue en mémoire (HEIC / WebP convertis en PNG) : aucune copie de la signature dans le dossier temporaire
    data = sig.read_bytes()
    if ext(sig) in ("heic", "heif", "webp", "avif"):
        from PIL import Image
        _heif()
        b = io.BytesIO()
        Image.open(sig).save(b, "PNG")
        data = b.getvalue()
    outs = []
    for f in files:
        doc = open_pdf(f)
        sel = pick_regions(doc, "pdf", "Placer la signature",
                           "Dessine un rectangle à l'endroit où placer la signature.\n"
                           "Tu peux en placer plusieurs (sur différentes pages : ◀ ▶).",
                           multi=True, start_page=doc.page_count - 1)
        for pi, rects in sel.items():
            pg = doc[pi]
            for r in rects:
                pg.insert_image(to_page(pg, r), stream=data, keep_proportion=True, overlay=True, rotate=pg.rotation)
        outs.append(save_pdf(doc, out(f, "signé")))
    return outs


@action("⬛ PDF · Caviarder (masquer définitivement)", PDF)
def pdf_redact(files):
    import pymupdf
    m = choose(["Dessiner les zones à masquer", "Rechercher un mot / une expression"], "Caviarder :")
    words = None
    if m.startswith("Rechercher"):
        words = [w.strip() for w in ask("Mots ou expressions à masquer (séparés par ; ) :", "").split(";") if w.strip()]
        if not words:
            raise ValueError("Aucun mot à masquer.")
    outs = []
    for f in files:
        doc = open_pdf(f)
        hits = 0
        zones = {}                                    # page → rectangles (coordonnées PDF) à vider
        if words is None:
            sel = pick_regions(doc, "pdf", "Caviarder",
                               "Dessine un rectangle sur chaque zone à masquer (plusieurs possibles, sur toutes les pages).",
                               multi=True)
            for pi, rects in sel.items():
                zones[pi] = [to_page(doc[pi], r) for r in rects]   # zone dessinée sur la page vue (éventuellement pivotée)
        else:
            for pg in doc:
                zones[pg.number] = [r for w in words for r in pg.search_for(w)]
        for pi, rects in zones.items():
            pg = doc[pi]
            for r in rects:
                pg.add_redact_annot(r, fill=(0, 0, 0))
                hits += 1
            for w in pg.widgets():                    # champs texte sous une zone ou contenant un mot : vidés
                if w.field_type not in (pymupdf.PDF_WIDGET_TYPE_TEXT, pymupdf.PDF_WIDGET_TYPE_COMBOBOX):
                    continue
                val = str(w.field_value or "")
                if val.strip() and (any(w.rect.intersects(r) for r in rects)
                                    or (words and any(x.lower() in val.lower() for x in words))):
                    w.field_value = " "               # (une valeur vide laisserait l'ancien texte dans le fichier)
                    w.update()
                    hits += 1
        if not hits:
            raise ValueError(f"« {Path(f).name} » : rien à masquer (aucune occurrence trouvée)."
                             + (" Le mot est peut-être coupé en fin de ligne, ou le document est un scan (fais d'abord l'OCR)."
                                if words else ""))
        for pg in doc:
            pg.apply_redactions()
        # ce qui pourrait encore trahir le contenu : métadonnées, pièces jointes, scripts (pas le « texte caché » :
        # ce serait toute la couche de texte d'un scan passé à l'OCR)
        doc.scrub(metadata=True, xml_metadata=True, attached_files=True, embedded_files=True, javascript=True,
                  hidden_text=False, thumbnails=True, reset_fields=False, reset_responses=True, redactions=True,
                  remove_links=False)
        if words:
            def clean(t):
                for w in words:
                    t = re.sub(re.escape(w), "■■■", t, flags=re.I)
                return t
            doc.set_toc([[lv, clean(t), pg_] for lv, t, pg_ in doc.get_toc()])
        else:
            doc.set_toc([])
        NOTES.append(f"{Path(f).name} : {hits} zone(s) masquée(s) — le contenu dessous est réellement supprimé "
                     "(métadonnées et pièces jointes retirées aussi).")
        outs.append(save_pdf(doc, out(f, "caviardé"), garbage=4))
    return outs


def tess_langs():
    pref = os.environ.get("TESSDATA_PREFIX")
    if pref and Path(pref).is_dir():
        found = [x.stem for x in Path(pref).glob("*.traineddata")]
        if found:
            return found
    t = which("tesseract", "/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract")
    if not t:
        return None
    try:
        r = subprocess.run([t, "--list-langs"], capture_output=True, text=True)
        return [l.strip() for l in (r.stdout + r.stderr).splitlines()[1:] if l.strip() and " " not in l.strip()]
    except Exception:
        return None


def ocr_lang(langs):
    return "+".join(x for x in ("fra", "eng") if x in langs) or "eng"


@action("🔍 PDF · OCR — rendre un scan cherchable", PDF)
def pdf_ocr(files):
    import pymupdf
    langs = tess_langs()
    if langs is None:
        raise RuntimeError("L'OCR nécessite les langues Tesseract. " + install_hint("tesseract"))
    lang = ocr_lang(langs)
    outs = []
    notify("OCR en cours… (quelques secondes par page)")
    for f in files:
        doc = open_pdf(f)
        od = pymupdf.open()
        for pg in doc:
            pix = pg.get_pixmap(dpi=300)
            od.insert_pdf(pymupdf.open("pdf", pix.pdfocr_tobytes(language=lang)))
        outs.append(save_pdf(od, out(f, "ocr"), garbage=4))
    NOTES.append(f"Langue(s) OCR : {lang}. Le texte est maintenant sélectionnable et cherchable.")
    return outs


@action("📄 PDF · Aplatir (formulaires et annotations)", PDF)
def pdf_flatten(files):
    outs = []
    for f in files:
        doc = open_pdf(f)
        doc.bake(annots=True, widgets=True)
        outs.append(save_pdf(doc, out(f, "aplati")))
    return outs


@action("📄 PDF · Noir et blanc (niveaux de gris)", PDF)
def pdf_gray(files):
    import pymupdf
    outs = []
    for f in files:
        doc = open_pdf(f)
        od = pymupdf.open()
        for pg in doc:
            pix = pg.get_pixmap(dpi=150, colorspace=pymupdf.csGRAY)
            np_ = od.new_page(width=pg.rect.width, height=pg.rect.height)
            np_.insert_image(np_.rect, pixmap=pix)
        outs.append(save_pdf(od, out(f, "gris"), garbage=4))
    NOTES.append("Les pages sont converties en images (texte non sélectionnable — utilise l'OCR si besoin).")
    return outs


@action("🏷️ PDF · Métadonnées (titre, auteur, nettoyage)", PDF)
def pdf_meta(files):
    m = choose(["Modifier titre / auteur / sujet", "Supprimer toutes les métadonnées"], "Métadonnées :")
    outs = []
    for f in files:
        doc = open_pdf(f)
        if m.startswith("Supprimer"):
            doc.set_metadata({})
            doc.del_xml_metadata()
        else:
            md = doc.metadata or {}
            md["title"] = ask(f"Titre de « {Path(f).name} » :", md.get("title") or Path(f).stem)
            md["author"] = ask("Auteur :", md.get("author") or "")
            md["subject"] = ask("Sujet :", md.get("subject") or "")
            doc.set_metadata(md)
        outs.append(save_pdf(doc, out(f, "meta")))
    return outs


@action("🛠️ PDF · Réparer un PDF endommagé", PDF)
def pdf_repair(files):
    outs = []
    for f in files:
        doc = open_pdf(f)
        dst = out(f, "réparé")
        try:
            save_pdf(doc, dst, garbage=4, clean=True)
        except Exception as e:          # certains fichiers abîmés refusent le nettoyage des flux : on garde la structure
            log(f"réparation sans nettoyage : {e}")
            dst.unlink(missing_ok=True)
            save_pdf(doc, dst, garbage=4)
        outs.append(dst)
    return outs


@action("ℹ️ PDF · Informations", PDF)
def pdf_info(files):
    for f in files:
        doc = open_pdf(f)
        R = doc[0].rect
        md = doc.metadata or {}
        nimg = sum(len(p.get_images()) for p in doc)
        txt = sum(len(p.get_text().strip()) > 20 for p in doc)
        lines = [
            f"Pages : {doc.page_count}", f"Taille : {human(Path(f).stat().st_size)}",
            f"Format page 1 : {R.width / 72 * 25.4:.0f} × {R.height / 72 * 25.4:.0f} mm",
            f"Images : {nimg}", f"Pages avec texte : {txt}/{doc.page_count}" + ("  → probablement un scan (OCR conseillé)" if txt == 0 else ""),
            f"Chiffré : {'oui' if doc.is_encrypted else 'non'}", f"Formulaire : {'oui' if doc.is_form_pdf else 'non'}",
            f"Titre : {md.get('title') or '—'}", f"Auteur : {md.get('author') or '—'}",
            f"Créé avec : {md.get('creator') or md.get('producer') or '—'}",
        ]
        buttons(f"{Path(f).name}\n\n" + "\n".join(lines), ["OK"])
    return []

# ───────────────────────── IMAGES ─────────────────────────

def load_img(f):
    from PIL import Image, ImageOps
    _heif()
    im = Image.open(f)
    im.load()
    if animated(im) or not im.getexif().get(0x0112, 1) > 1:
        return im              # animation (garde toutes ses images) ou déjà droite
    return ImageOps.exif_transpose(im)


def animated(im):
    """Vraie animation (GIF, WebP, PNG animés) — pas une photo JPEG « MPO » ni un TIFF multipage."""
    return bool(getattr(im, "is_animated", False)) and im.format in ("GIF", "WEBP", "PNG")


def frames_map(im, fn):
    """Applique fn à chaque image d'une animation (GIF, WebP, PNG animés) ; image fixe → fn(im)."""
    if not animated(im):
        r = fn(im)
        r.info = im.info
        return r
    from PIL import ImageSequence
    res = []
    for fr in ImageSequence.Iterator(im):
        g = fn(fr.convert("RGBA"))
        g.info = {"duration": fr.info.get("duration", im.info.get("duration", 100))}
        res.append(g)
    res[0].info.update(loop=im.info.get("loop", 0))
    return res


def flatten(im, bg=(255, 255, 255)):
    from PIL import Image
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        b = Image.new("RGB", im.size, bg)
        b.paste(im, mask=im.getchannel("A"))
        return b
    return im if im.mode in ("RGB", "L") else im.convert("RGB")


PIL_FMT = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP", "heic": "HEIF", "heif": "HEIF",
           "avif": "AVIF", "tif": "TIFF", "tiff": "TIFF", "gif": "GIF", "bmp": "BMP", "ico": "ICO"}


ANIM_FMT = {"GIF", "WEBP", "PNG"}


def save_img(im, dst, quality=90, keep_exif=True):
    """Enregistre une image (ou une liste d'images = animation) dans le format de l'extension de dst."""
    e = ext(dst)
    fmt = PIL_FMT.get(e, "PNG")
    if isinstance(im, list):
        if len(im) > 1 and fmt in ANIM_FMT:
            frames = [f.convert("RGBA") for f in im]
            frames[0].save(str(dst), fmt, save_all=True, append_images=frames[1:], loop=im[0].info.get("loop", 0),
                           duration=[f.info.get("duration", 100) for f in im], **({"quality": quality} if fmt == "WEBP" else {}))
            return Path(dst)
        im = im[0]
    kw = {}
    exif = im.info.get("exif") if keep_exif else None
    if im.mode not in ("RGB", "RGBA", "L", "LA", "P", "1"):
        im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
    if fmt in ("JPEG", "BMP"):
        im = flatten(im)
        if fmt == "JPEG":
            kw = dict(quality=quality, optimize=True, progressive=True)
    elif fmt == "PNG":
        kw = dict(optimize=True)
    elif fmt in ("WEBP", "AVIF", "HEIF"):
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if im.mode in ("LA", "P") else "RGB")
        kw = dict(quality=quality)
        if fmt == "WEBP":
            kw["method"] = 6
    elif fmt == "TIFF":
        kw = dict(compression="tiff_lzw")
    elif fmt == "ICO":
        kw = dict(sizes=[(s, s) for s in (256, 128, 64, 48, 32, 16)])
    if exif and fmt in ("JPEG", "WEBP", "PNG", "HEIF", "AVIF", "TIFF"):
        kw["exif"] = exif
    if not keep_exif:
        icc = im.info.get("icc_profile")
        im = im.copy()          # nouvelle image : plus aucune balise d'origine (TIFF recopie sinon les siennes)
        im.info = {"icc_profile": icc} if icc else {}
    try:
        im.save(str(dst), fmt, **kw)
    except (RuntimeError, ValueError, OSError) as e:
        if "exif" not in kw:
            raise
        log(f"EXIF non transférable vers {fmt} ({e}) : image enregistrée sans")
        Path(dst).unlink(missing_ok=True)
        kw.pop("exif")
        im.save(str(dst), fmt, **kw)
    return Path(dst)


def writable_formats():
    from PIL import Image
    _heif()
    Image.init()
    fm = ["JPG", "PNG", "WEBP", "HEIC", "AVIF", "TIFF", "GIF", "BMP", "ICO"]
    return [x for x in fm if PIL_FMT[x.lower()] in Image.SAVE]


@action("🖼️ Image · Convertir le format", IMG)
def img_convert(files):
    fmt = choose(writable_formats(), "Convertir en :").lower()
    outs = []
    for f in files:
        if ext(f) == fmt or (ext(f), fmt) in (("jpeg", "jpg"), ("tif", "tiff"), ("heif", "heic")):
            NOTES.append(f"{Path(f).name} est déjà au format {fmt.upper()}.")
            continue
        im = load_img(f)
        outs.append(save_img(frames_map(im, lambda x: x), unique(Path(f).with_suffix("." + fmt)), quality=92))
    return outs


@action("🖼️ Image · Redimensionner", IMG)
def img_resize(files):
    from PIL import Image
    s = ask("Nouvelle taille :\n• 50%  → pourcentage\n• 1920 → plus grand côté en pixels\n• 1080x1080 → tenir dans un cadre", "50%")
    s = s.strip().lower().replace(" ", "").replace("×", "x").replace(",", ".")
    m = (re.fullmatch(r"(\d+(?:\.\d+)?)%", s) or re.fullmatch(r"(\d+)x(\d+)", s) or re.fullmatch(r"(\d+)", s))
    if not m or any(float(g) <= 0 for g in m.groups()):
        raise ValueError(f"« {s} » n'est pas compris : écris par exemple 50%, 1920 ou 1080x1080.")
    outs = []
    for f in files:
        im = load_img(f)
        w, h = im.size
        if s.endswith("%"):
            k = float(m.group(1)) / 100
        elif "x" in s:
            k = min(int(m.group(1)) / w, int(m.group(2)) / h)
        else:
            k = int(m.group(1)) / max(w, h)
        nw, nh = max(1, round(w * k)), max(1, round(h * k))
        r = frames_map(im, lambda x: x.resize((nw, nh), Image.LANCZOS))
        outs.append(save_img(r, out(f, f"{nw}x{nh}"), quality=92))
    return outs


@action("🖼️ Image · Compresser", IMG)
def img_compress(files):
    from PIL import Image
    lvl = choose(["Légère", "Recommandée", "Forte"], "Niveau de compression :", default="Recommandée")
    q, maxs = {"L": (85, None), "R": (72, 3000), "F": (55, 2000)}[lvl[0]]
    outs = []
    for f in files:
        im = load_img(f)
        e = ext(f)
        if animated(im):                                 # animation : on réduit chaque image, sans changer de format
            def shrink(x):
                x = x.copy()
                if maxs and max(x.size) > maxs:
                    x.thumbnail((maxs, maxs), Image.LANCZOS)
                return x
            dst = out(f, "compressé")
            save_img(frames_map(im, shrink), dst, quality=q)
            size_note(f, dst)
            outs.append(dst)
            continue
        if maxs and max(im.size) > maxs:
            info = im.info
            im.thumbnail((maxs, maxs), Image.LANCZOS)
            im.info = info
        if e in ("png", "gif", "bmp", "tif", "tiff") and lvl[0] == "F" and e != "gif":
            if "A" in im.getbands():
                im = im.quantize(256, method=Image.Quantize.FASTOCTREE)
            else:
                im = im.convert("RGB").quantize(256)
        dst = out(f, "compressé", "jpg" if e in ("bmp", "tif", "tiff") else None)
        save_img(im, dst, quality=q)
        size_note(f, dst)
        outs.append(dst)
    return outs


@action("✂️ Image · Rogner", IMG)
def img_crop(files):
    from PIL import Image, ImageChops
    mode = choose(["Visuellement (je dessine la zone)", "Format imposé (1:1, 16:9, 4:5…)",
                   "Supprimer automatiquement les bords unis"], "Comment rogner ?")
    ratio = None
    if mode.startswith("Format"):
        r = choose(["1:1 (carré)", "4:5 (Instagram portrait)", "16:9 (paysage)", "9:16 (story)",
                    "4:3", "3:2", "3:4", "2:3"], "Format :")
        a, b = r.split()[0].split(":")
        ratio = int(a) / int(b)
    outs = []
    for f in files:
        im = load_img(f)
        w, h = im.size
        if mode.startswith("Visuel"):
            sel = pick_regions(im, "img", f"Rogner — {Path(f).name}", "Dessine un rectangle autour de la zone à GARDER.")
            box = tuple(round(v) for v in sel[0][0])
        elif ratio:
            if w / h > ratio:
                nw = round(h * ratio)
                box = ((w - nw) // 2, 0, (w - nw) // 2 + nw, h)
            else:
                nh = round(w / ratio)
                box = (0, (h - nh) // 2, w, (h - nh) // 2 + nh)
        else:
            box = None
            if "A" in im.getbands() and im.getchannel("A").getpixel((0, 0)) < 10:
                box = im.getchannel("A").getbbox()
            if not box:
                rgb = im.convert("RGB")
                diff = ImageChops.difference(rgb, Image.new("RGB", im.size, rgb.getpixel((0, 0))))
                box = ImageChops.add(diff, diff, 2.0, -24).getbbox()
            if not box:
                NOTES.append(f"{Path(f).name} : aucun bord détecté.")
                continue
        outs.append(save_img(frames_map(im, lambda x: x.crop(box)), out(f, "rogné"), quality=93))
    return outs


@action("🔄 Image · Pivoter / retourner", IMG)
def img_rotate(files):
    from PIL import Image
    T = Image.Transpose
    m = choose(["90° vers la droite", "90° vers la gauche", "180°", "Miroir horizontal", "Miroir vertical"], "Transformation :")
    op = {"90° vers la droite": T.ROTATE_270, "90° vers la gauche": T.ROTATE_90, "180°": T.ROTATE_180,
          "Miroir horizontal": T.FLIP_LEFT_RIGHT, "Miroir vertical": T.FLIP_TOP_BOTTOM}[m]
    outs = []
    for f in files:
        im = load_img(f)
        outs.append(save_img(frames_map(im, lambda x: x.transpose(op)), out(f, "pivoté"), quality=93))
    return outs


@action("🕵️ Image · Supprimer les métadonnées (EXIF, GPS)", IMG)
def img_strip(files):
    outs = []
    for f in files:
        im = load_img(f)
        outs.append(save_img(im, out(f, "sans-meta"), quality=95, keep_exif=False))
    NOTES.append("Position GPS, appareil, date et autres données EXIF retirées.")
    return outs


@action("📄 Image · Convertir en PDF", IMG)
def img_to_pdf(files):
    import pymupdf
    one = len(files) == 1 or choose(["Un seul PDF avec toutes les images", "Un PDF par image"], "Regrouper ?").startswith("Un seul")
    fit = choose(["A4 (ajusté avec marges)", "Taille de l'image"], "Format des pages :").startswith("A4")
    if one:
        d = pymupdf.open()
        for f in files:
            add_image_page(d, f, fit)
        name = "Images.pdf" if len(files) > 1 else Path(files[0]).stem + ".pdf"
        return [save_pdf(d, unique(Path(files[0]).with_name(name)), garbage=4)]
    outs = []
    for f in files:
        d = pymupdf.open()
        add_image_page(d, f, fit)
        outs.append(save_pdf(d, unique(Path(f).with_suffix(".pdf")), garbage=4))
    return outs


@action("💧 Image · Ajouter un filigrane / copyright", IMG)
def img_watermark(files):
    from PIL import Image, ImageDraw, ImageFont
    text = ask("Texte du filigrane :", f"© {datetime.date.today().year}").strip()
    if not text:
        raise ValueError("Texte du filigrane vide.")
    pos = choose(["Bas droite", "Bas gauche", "Centre (grand)", "Mosaïque (répété en diagonale)"], "Position :")
    outs = []
    for f in files:
        im = load_img(f)
        base = im.convert("RGBA")
        W, H = base.size
        fs = max(14, int(min(W, H) * (0.12 if pos.startswith("Centre") else 0.045)))
        try:
            font = ImageFont.truetype(font_file(), fs)
        except Exception:
            font = ImageFont.load_default(size=fs)
        ov = Image.new("RGBA", base.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        x0, y0, x1, y1 = d.textbbox((0, 0), text, font=font)
        tw, th = x1 - x0, y1 - y0
        if pos.startswith("Mosa"):
            tile = Image.new("RGBA", (tw + fs * 3, th + fs * 3), (0, 0, 0, 0))
            ImageDraw.Draw(tile).text((fs, fs), text, font=font, fill=(255, 255, 255, 80))
            tile = tile.rotate(30, expand=True)
            for yy in range(-tile.height, H + tile.height, tile.height):
                for xx in range(-tile.width, W + tile.width, tile.width):
                    ov.paste(tile, (xx, yy), tile)
        else:
            m = fs
            p = {"Bas droite": (W - tw - m, H - th - m * 1.4), "Bas gauche": (m, H - th - m * 1.4),
                 "Centre (grand)": ((W - tw) / 2, (H - th) / 2)}[pos]
            d.text((p[0] + 2, p[1] + 2), text, font=font, fill=(0, 0, 0, 90))
            d.text(p, text, font=font, fill=(255, 255, 255, 190))
        res = Image.alpha_composite(base, ov)
        res.info = im.info
        if "A" not in im.getbands():
            res = res.convert("RGB")
            res.info = im.info
        outs.append(save_img(res, out(f, "filigrane"), quality=93))
    return outs


@action("🎞️ Images · Créer un GIF animé", IMG, minf=2)
def img_gif(files):
    from PIL import Image
    ms = ask_int("Durée de chaque image (millisecondes) :", "600", 20)
    width = ask_int("Largeur du GIF (pixels) :", "800", 16)
    frames = []
    for f in files:
        im = load_img(f).convert("RGB")
        im.thumbnail((width, width * 4), Image.LANCZOS)
        frames.append(im)
    W, H = max(i.width for i in frames), max(i.height for i in frames)
    canv = []
    for im in frames:
        c = Image.new("RGB", (W, H), "white")
        c.paste(im, ((W - im.width) // 2, (H - im.height) // 2))
        canv.append(c)
    dst = unique(Path(files[0]).with_name("Animation.gif"))
    canv[0].save(dst, save_all=True, append_images=canv[1:], duration=ms, loop=0, optimize=True)
    return [dst]

# ───────────────────────── VIDÉO ─────────────────────────

def check_span(a, b):
    if b is not None and b <= (a or 0):
        raise ValueError("La fin de l'extrait doit être après son début.")


def _vlabel(files):
    notify(f"Traitement vidéo en cours ({len(files)} fichier(s))… je te préviens à la fin.")


@action("🎬 Vidéo · Convertir en MP4 (compatible partout)", VID)
def vid_mp4(files):
    _vlabel(files)
    outs = []
    for f in files:
        dst = unique(Path(f).with_name(Path(f).stem + (".mp4" if ext(f) != "mp4" else "_h264.mp4")))
        ff("-i", f, "-c:v", "libx264", "-crf", "21", "-preset", "medium", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", dst)
        outs.append(dst)
    return outs


@action("🎬 Vidéo · Compresser", VID)
def vid_compress(files):
    lvl = choose(["Légère (qualité quasi identique)", "Recommandée (max 1080p)", "Forte (max 720p, idéal mail)"],
                 "Niveau :", default="Recommandée (max 1080p)")
    crf, hmax = {"L": (24, None), "R": (27, 1080), "F": (31, 720)}[lvl[0]]
    _vlabel(files)
    outs = []
    for f in files:
        dst = out(f, "compressé", "mp4")
        vf = ["-vf", f"scale=-2:'min({hmax},ih)'"] if hmax else []
        ff("-i", f, *vf, "-c:v", "libx264", "-crf", crf, "-preset", "medium", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", dst)
        size_note(f, dst)
        outs.append(dst)
    return outs


@action("🎬 Vidéo · Couper (garder un extrait)", VID)
def vid_trim(files):
    a = parse_time(ask("Début de l'extrait (ex : 1:23 ou 83 ou 0:01:23) :", "0:00"))
    b = parse_time(ask("Fin de l'extrait (vide = jusqu'à la fin) :", ""))
    check_span(a, b)
    _vlabel(files)
    outs = []
    for f in files:
        dst = out(f, "extrait", "mp4")
        to = ["-to", b] if b else []
        ff("-ss", a or 0, *to, "-i", f, "-c:v", "libx264", "-crf", "20", "-preset", "fast", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", dst)
        outs.append(dst)
    return outs


@action("🎬 Vidéo · Convertir en GIF", VID)
def vid_gif(files):
    w = int(choose(["320", "480", "640", "800"], "Largeur du GIF (px) :", default="480"))
    fps = int(choose(["10", "12", "15", "20"], "Images par seconde :", default="12"))
    a = parse_time(ask("Début (ex : 0:05, vide = début) :", ""))
    dur = parse_time(ask("Durée en secondes (vide = tout, attention aux gros fichiers) :", "6"))
    _vlabel(files)
    outs = []
    for f in files:
        dst = out(f, "anim", "gif")
        pre = (["-ss", a] if a else []) + (["-t", dur] if dur else [])
        ff(*pre, "-i", f, "-vf",
           f"fps={fps},scale={w}:-1:flags=lanczos,split[s0][s1];[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=4",
           "-loop", "0", dst)
        outs.append(dst)
    return outs


@action("🎬 Vidéo · Extraire l'audio (MP3)", VID)
def vid_audio(files):
    _vlabel(files)
    outs = []
    for f in files:
        need_audio(f)
        dst = unique(Path(f).with_suffix(".mp3"))
        ff("-i", f, "-vn", "-c:a", "libmp3lame", "-q:a", "2", dst)
        outs.append(dst)
    return outs


@action("🎬 Vidéo · Retirer le son", VID)
def vid_mute(files):
    outs = []
    for f in files:
        dst = out(f, "muet")
        ff("-i", f, "-c:v", "copy", "-an", dst)
        outs.append(dst)
    return outs


@action("🎬 Vidéo · Redimensionner (1080p / 720p / 480p / vertical)", VID)
def vid_resize(files):
    m = choose(["1080p", "720p", "480p", "Vertical 1080×1920 (recadré au centre)", "Carré 1080×1080 (recadré)"], "Taille :")
    vf = {"1080p": "scale=-2:1080", "720p": "scale=-2:720", "480p": "scale=-2:480",
          "Vertical 1080×1920 (recadré au centre)": "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
          "Carré 1080×1080 (recadré)": "scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080"}[m]
    _vlabel(files)
    outs = []
    for f in files:
        dst = out(f, m.split()[0].lower(), "mp4")
        ff("-i", f, "-vf", vf, "-c:v", "libx264", "-crf", "21", "-preset", "medium", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", dst)
        outs.append(dst)
    return outs


@action("🎬 Vidéo · Pivoter", VID)
def vid_rotate(files):
    m = choose(["90° vers la droite", "90° vers la gauche", "180°"], "Rotation :")
    vf = {"90° vers la droite": "transpose=1", "90° vers la gauche": "transpose=2", "180°": "transpose=1,transpose=1"}[m]
    _vlabel(files)
    outs = []
    for f in files:
        dst = out(f, "pivoté", "mp4")
        ff("-i", f, "-vf", vf, "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", dst)
        outs.append(dst)
    return outs


@action("🎬 Vidéo · Capturer une image", VID)
def vid_frame(files):
    t = parse_time(ask("À quel moment ? (ex : 0:12) :", "0:01")) or 0
    outs = []
    for f in files:
        dst = out(f, f"image_{int(t)}s", "jpg")
        ff("-ss", t, "-i", f, "-frames:v", "1", "-q:v", "2", dst)
        if not dst.exists() or dst.stat().st_size == 0:
            dst.unlink(missing_ok=True)
            raise ValueError(f"Le moment choisi ({t:g} s) est après la fin de « {Path(f).name} ».")
        outs.append(dst)
    return outs

# ───────────────────────── AUDIO ─────────────────────────

def acodec(e):
    """Options d'encodage audio pour un fichier de sortie d'extension `e` (son seul ou piste d'une vidéo)."""
    aac = ["-c:a", "aac", "-b:a", "192k"]
    table = {"mp3": ["-c:a", "libmp3lame", "-q:a", "2"], "m4a": aac, "aac": aac, "mp4": aac, "m4v": aac, "mov": aac,
             "mkv": aac, "3gp": aac, "wav": ["-c:a", "pcm_s16le"], "flac": ["-c:a", "flac"],
             "aiff": ["-c:a", "pcm_s16be"], "aif": ["-c:a", "pcm_s16be"], "wma": ["-c:a", "wmav2", "-b:a", "192k"],
             "wmv": ["-c:a", "wmav2", "-b:a", "192k"], "opus": ["-c:a", "libopus", "-b:a", "128k"],
             "webm": ["-c:a", "libopus", "-b:a", "128k"], "avi": ["-c:a", "libmp3lame", "-q:a", "2"],
             "flv": aac, "mpg": ["-c:a", "mp2"], "mpeg": ["-c:a", "mp2"]}
    if e == "ogg":     # le ffmpeg de Homebrew n'a pas libvorbis : encodeur Vorbis intégré (stéréo) à la place
        return ["-c:a", "libvorbis", "-q:a", "5"] if has_encoder("libvorbis") else ["-c:a", "vorbis", "-strict", "-2", "-ac", "2"]
    return table.get(e, table["mp3"])


@action("🎵 Audio · Convertir le format", AUD | VID)
def aud_convert(files):
    e = choose(["MP3", "M4A (AAC)", "WAV", "FLAC", "OGG", "AIFF"], "Convertir en :").split()[0].lower()
    outs = []
    for f in files:
        need_audio(f)
        dst = unique(Path(f).with_suffix("." + e))
        ff("-i", f, "-vn", *acodec(e), dst)
        outs.append(dst)
    return outs


@action("🎵 Audio · Compresser", AUD)
def aud_compress(files):
    br = choose(["192k (très bonne qualité)", "128k (standard)", "96k (voix / podcast)", "64k mono (voix, très léger)"],
                "Débit :", default="128k (standard)")
    outs = []
    for f in files:
        need_audio(f)
        dst = out(f, "compressé", "mp3")
        mono = ["-ac", "1"] if "mono" in br else []
        ff("-i", f, "-vn", *mono, "-c:a", "libmp3lame", "-b:a", br.split()[0], dst)
        size_note(f, dst)
        outs.append(dst)
    return outs


@action("🎵 Audio · Couper (garder un extrait)", AUD)
def aud_trim(files):
    a = parse_time(ask("Début (ex : 1:23) :", "0:00")) or 0
    b = parse_time(ask("Fin (vide = jusqu'à la fin) :", ""))
    check_span(a, b)
    fade = choose(["Sans fondu", "Fondu entrée + sortie (2 s)"], "Fondu :").startswith("Fondu")
    outs = []
    for f in files:
        dst = out(f, "extrait")
        to = ["-to", b] if b else []
        af = []
        if fade:
            dur = (b - a) if b else None
            fl = "afade=t=in:d=2"
            if dur:
                fl += f",afade=t=out:st={max(0, dur - 2)}:d=2"
            af = ["-af", fl]
        ff("-ss", a, *to, "-i", f, "-vn", *af, *acodec(ext(f)), dst)
        outs.append(dst)
    return outs


@action("🎵 Audio · Normaliser le volume", AUD | VID)
def aud_norm(files):
    outs = []
    for f in files:
        need_audio(f)
        dst = out(f, "volume-normalisé")
        keep = ["-c:v", "copy"] if ext(f) in VID else ["-vn"]
        # loudnorm travaille à 192 kHz : on revient à une fréquence standard
        ff("-i", f, *keep, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000" if ext(f) in ("opus", "webm") else "44100",
           *acodec(ext(f)), dst)
        outs.append(dst)
    return outs


@action("🎵 Audio · Fusionner (mettre bout à bout)", AUD, minf=2)
def aud_merge(files):
    dst = unique(Path(files[0]).with_name("Fusion.mp3"))
    args = []
    for f in files:
        args += ["-i", f]
    n = len(files)
    # même fréquence et mêmes canaux pour tous (sinon concat refuse des fichiers mono 22 kHz + stéréo 44 kHz)
    norm = "".join(f"[{i}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}];" for i in range(n))
    ff(*args, "-filter_complex", norm + "".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[a]",
       "-map", "[a]", "-c:a", "libmp3lame", "-q:a", "2", dst)
    return [dst]

# ───────────────────────── DOCUMENTS ─────────────────────────

CSS = ("body{font-family:sans-serif;font-size:11pt;line-height:1.45;color:#111}"
       "h1{font-size:21pt}h2{font-size:16pt}h3{font-size:13pt}"
       "code{font-family:monospace;font-size:9pt;background-color:#eef0f3;color:#b4235a}"
       # blocs de code : fond gris clair, bordure, retour à la ligne des lignes trop longues
       "pre{font-family:monospace;font-size:8.6pt;line-height:1.38;white-space:pre-wrap;background-color:#f6f8fa;"
       "border:1px solid #d6dbe1;padding:7pt 9pt;margin:6pt 0 10pt 0;color:#1f2328}"
       "pre code{background-color:transparent;color:inherit;font-size:8.6pt}"
       ".codehilite{margin:0}.lang{font-family:sans-serif;font-size:7pt;color:#8a8f98;margin:8pt 0 -4pt 0;"
       "letter-spacing:0.5pt}"
       "table{border-collapse:collapse}td,th{border:1px solid #888;padding:3px 6px}th{background:#eee}"
       "blockquote{color:#555;margin-left:14pt}")


def _code_html(code, lang):
    """Bloc de code : couleurs (Pygments si présent), lignes trop longues coupées proprement, étiquette du langage."""
    import html as H
    import re
    code = code.expandtabs(4).rstrip("\n")
    # un « mot » très long (URL, hachage…) ne passe pas à la ligne tout seul : on lui donne des points de coupure
    code = re.sub(r"\S{70,}", lambda m: "\u200b".join(m.group(0)[i:i + 60] for i in range(0, len(m.group(0)), 60)), code)
    body = None
    try:
        from pygments import highlight
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import get_lexer_by_name, guess_lexer
        from pygments.util import ClassNotFound
        try:
            lexer = get_lexer_by_name(lang) if lang else None
        except ClassNotFound:
            lexer = None
        if lexer is None and len(code) > 40:
            try:
                g = guess_lexer(code)
                lexer = g if g.analyse_text(code) > 0.3 else None
            except ClassNotFound:
                lexer = None
        if lexer is not None:
            out = highlight(code, lexer, HtmlFormatter(noclasses=True, nowrap=True, style="friendly"))
            body = out.rstrip("\n")
    except ImportError:
        pass
    if body is None:
        body = H.escape(code)
    label = f"<div class='lang'>{H.escape(lang.upper())}</div>" if lang else ""
    return f"{label}<pre><code>{body}</code></pre>"


def md_to_html(raw):
    import html as H
    import re
    try:      # CommonMark complet : blocs de code dans les listes et citations, tableaux, texte barré
        from markdown_it import MarkdownIt
        html = MarkdownIt("commonmark", {"html": True}).enable(["table", "strikethrough"]).render(raw)
    except ImportError:
        import markdown
        html = markdown.markdown(raw, extensions=["tables", "fenced_code", "sane_lists"])

    def repl(m):
        lang = (m.group(1) or "").strip()
        code = H.unescape(m.group(2))
        return _code_html(code, lang)
    return re.sub(r'<pre><code(?: class="language-([^"]+)")?>(.*?)</code></pre>', repl, html, flags=re.S)


def read_any_text(f):
    """Texte en UTF-8 ou, à défaut, dans l'encodage historique de Windows (fichiers Bloc-notes, Excel…)."""
    b = Path(f).read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode("latin-1")


def to_html(f):
    import html as H
    e = ext(f)
    raw = read_any_text(f)
    if e in ("md", "markdown"):
        return md_to_html(raw)
    if e in ("html", "htm"):
        return raw
    return "<div style='font-family:monospace;font-size:10pt'>" + H.escape(raw).replace("\n", "<br/>") + "</div>"


def html_to_pdf(html, dst, base=None):
    import pymupdf
    arch = pymupdf.Archive(str(base)) if base else None
    story = pymupdf.Story(html=html, user_css=CSS, archive=arch)
    w = pymupdf.DocumentWriter(str(dst))
    mb = pymupdf.paper_rect("a4")
    where = mb + (56, 56, -56, -56)
    more = 1
    while more:
        dev = w.begin_page(mb)
        more, _ = story.place(where)
        story.draw(dev)
        w.end_page()
    w.close()
    return dst


def soffice():
    if IS_WIN:
        # soffice.com attend la fin de la conversion (soffice.exe rend parfois la main tout de suite)
        cands = [Path(os.environ.get(v, "")) / "LibreOffice" / "program"
                 for v in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "LOCALAPPDATA")]
        # LibreOffice privé, déballé par l'installateur de FileForge
        cands += [p.parent for p in (HOME_DIR / "libreoffice").glob("**/program/soffice.com")]
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\LibreOffice\UNO\InstallPath") as k:
                cands.insert(0, Path(winreg.QueryValueEx(k, "")[0]))
        except Exception:
            pass
        for d in cands:
            for exe in ("soffice.com", "soffice.exe"):
                if (d / exe).exists():
                    return str(d / exe)
    return which("soffice", "/Applications/LibreOffice.app/Contents/MacOS/soffice",
                 str(HOME_DIR / "LibreOffice.app" / "Contents" / "MacOS" / "soffice"))


def lo_convert(src, fmt, dst):
    """Conversion via LibreOffice (headless). Retourne True si réussi."""
    so = soffice()
    if not so:
        return False
    import time
    tmp = Path(tempfile.mkdtemp())
    prof = Path(tempfile.mkdtemp())
    # copie sous un nom simple : LibreOffice gère mal certains noms (accents, espaces) sous Windows
    work = tmp / "in"
    work.mkdir()
    simple = work / ("document." + ext(src))
    shutil.copy2(src, simple)
    try:
        # profil séparé : fonctionne même si LibreOffice est déjà ouvert
        r = subprocess.run([so, f"-env:UserInstallation={prof.as_uri()}", "--headless", "--norestore",
                            "--nologo", "--nodefault", "--convert-to", fmt, "--outdir", str(tmp), str(simple)],
                           capture_output=True, timeout=300)
        res = None
        # Windows : soffice.exe rend parfois la main avant d'avoir écrit le fichier ; ailleurs, inutile d'attendre
        for _ in range(40 if IS_WIN and r.returncode == 0 else 2):
            res = next(tmp.glob("document." + fmt.split(":")[0]), None)
            if res and res.stat().st_size > 0:
                break
            time.sleep(0.5)
        if not res or res.stat().st_size == 0:
            log(f"LibreOffice ({r.returncode}) : {(r.stdout + r.stderr).decode('utf-8', 'replace').strip()[-500:]}")
            return False
        shutil.move(str(res), dst)
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(prof, ignore_errors=True)


SLIDES = {"pptx", "ppt", "odp"}
SHEETS = {"xlsx", "xls", "ods"}


def office_app(e):
    """Windows : application Microsoft Office capable d'ouvrir ce type, si elle est installée."""
    if not IS_WIN:
        return None
    prog = "PowerPoint.Application" if e in SLIDES else "Excel.Application" if e in SHEETS else "Word.Application"
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog + "\\CLSID"))
        return prog
    except Exception:
        return None


def office_com_to_pdf(src, dst):
    """Windows : conversion fidèle par Word, PowerPoint ou Excel s'ils sont installés."""
    prog = office_app(ext(src))
    if not prog:
        return False
    try:
        import pythoncom
        import win32com.client
    except Exception:
        return False
    pythoncom.CoInitialize()
    app = doc = None
    s, d = str(Path(src).resolve()), str(Path(dst).resolve())
    try:
        app = win32com.client.DispatchEx(prog)
        app.DisplayAlerts = 0 if prog != "PowerPoint.Application" else 1  # ppAlertsNone = 1
        if prog == "Word.Application":
            app.Visible = False
            doc = app.Documents.Open(s, ReadOnly=True, AddToRecentFiles=False, ConfirmConversions=False)
            doc.ExportAsFixedFormat(d, 17)                       # wdExportFormatPDF
            doc.Close(False)
        elif prog == "PowerPoint.Application":
            doc = app.Presentations.Open(s, True, False, False)  # lecture seule, sans fenêtre
            doc.SaveAs(d, 32)                                    # ppSaveAsPDF
            doc.Close()
        else:
            app.Visible = False
            doc = app.Workbooks.Open(s, 0, True)
            doc.ExportAsFixedFormat(0, d)                        # xlTypePDF
            doc.Close(False)
        return Path(d).exists() and Path(d).stat().st_size > 0
    except Exception as err:
        log(f"{prog} : {err}")
        return False
    finally:
        try:
            if app is not None:
                app.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()


def textutil_to_pdf(src, dst):
    """Secours sans LibreOffice : moteur de conversion intégré à macOS (textutil) puis mise en page A4."""
    tmp = Path(tempfile.mkdtemp())
    try:
        html = tmp / "doc.html"
        r = subprocess.run(["/usr/bin/textutil", "-convert", "html", "-output", str(html), str(src)],
                           capture_output=True, text=True)
        if r.returncode != 0 or not html.exists():
            raise RuntimeError("textutil : " + r.stderr.strip())
        h = html.read_text(encoding="utf-8", errors="replace")
        h = re.sub(r"<style[^>]*>.*?</style>", "", h, flags=re.S | re.I)
        html_to_pdf(h, dst, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@action("📝 Document · Convertir en PDF", OFFICE | TEXT)
def doc_to_pdf(files):
    outs = []
    for f in files:
        e = ext(f)
        dst = unique(Path(f).with_suffix(".pdf"))
        if e in TEXT:
            html_to_pdf(to_html(f), dst, Path(f).parent)
        elif office_app(e) and (notify("Conversion en PDF par Microsoft Office…") or office_com_to_pdf(f, dst)):
            pass
        elif soffice():
            notify("Conversion en PDF en cours…")
            if not lo_convert(f, "pdf", dst):
                raise RuntimeError(f"LibreOffice n'a pas pu convertir « {Path(f).name} ».\n"
                                   "Le fichier est peut-être protégé ou endommagé. Détails dans le journal.")
        elif e in WORDS:
            if IS_MAC:
                textutil_to_pdf(f, dst)
            elif e == "docx":
                import mammoth
                with open(f, "rb") as fh:
                    html_to_pdf(mammoth.convert_to_html(fh).value, dst)
            else:
                raise RuntimeError(f"Pour convertir les fichiers .{e} en PDF, installe LibreOffice ou Microsoft Word.")
            NOTES.append("Conversion simplifiée (installe LibreOffice pour une mise en page fidèle).")
        else:
            raise RuntimeError(f"Pour convertir les fichiers .{e} en PDF, il faut Microsoft Office ou LibreOffice (gratuit).\n"
                               + install_hint("libreoffice"))
        outs.append(dst)
    return outs


@action("📝 Office · Convertir (Word ⇄ ODT, PowerPoint, Excel…)", OFFICE)
def office_convert(files):
    if not soffice():
        raise RuntimeError("Cette action nécessite LibreOffice (gratuit).\n" + install_hint("libreoffice"))
    groups = {"docx": ["docx", "odt", "rtf", "txt", "html"], "pptx": ["pptx", "odp"], "xlsx": ["xlsx", "ods", "csv"]}
    fam = "pptx" if ext(files[0]) in ("pptx", "ppt", "odp") else "xlsx" if ext(files[0]) in ("xlsx", "xls", "ods") else "docx"
    tgt = choose([x.upper() for x in groups[fam] if x != ext(files[0])], "Convertir en :").lower()
    outs = []
    notify("Conversion en cours…")
    for f in files:
        dst = unique(Path(f).with_suffix("." + tgt))
        if tgt == "txt":
            # l'export texte de LibreOffice reste bloqué indéfiniment sur certaines versions : passage par .docx
            import mammoth
            src = Path(f)
            with tempfile.TemporaryDirectory() as td:
                if ext(f) != "docx":
                    src = Path(td) / "document.docx"
                    if not lo_convert(f, "docx", src):
                        raise RuntimeError(f"Conversion impossible pour {Path(f).name}.")
                with open(src, "rb") as fh:
                    dst.write_text(mammoth.extract_raw_text(fh).value, encoding="utf-8")
        elif not lo_convert(f, tgt, dst):
            raise RuntimeError(f"Conversion impossible pour {Path(f).name}.")
        outs.append(dst)
    return outs


@action("📝 Word · Convertir en Markdown / HTML / Texte", {"docx"})
def docx_convert(files):
    import mammoth
    fmt = choose(["Markdown (.md)", "HTML (.html)", "Texte brut (.txt)"], "Convertir en :")
    outs = []
    for f in files:
        with open(f, "rb") as fh:
            if fmt.startswith("Markdown"):
                txt, e = mammoth.convert_to_markdown(fh).value, "md"
            elif fmt.startswith("HTML"):
                body = mammoth.convert_to_html(fh).value
                txt, e = f"<!doctype html><meta charset='utf-8'><style>{CSS}</style><body>{body}</body>", "html"
            else:
                txt, e = mammoth.extract_raw_text(fh).value, "txt"
        dst = unique(Path(f).with_suffix("." + e))
        dst.write_text(txt, encoding="utf-8")
        outs.append(dst)
    return outs


@action("📝 Markdown · Convertir en HTML", {"md", "markdown"})
def md_html(files):
    outs = []
    for f in files:
        dst = unique(Path(f).with_suffix(".html"))
        import html as H
        dst.write_text(f"<!doctype html><meta charset='utf-8'><title>{H.escape(Path(f).stem)}</title>"
                       f"<style>body{{max-width:46em;margin:3em auto;padding:0 1em}}{CSS}</style>{to_html(f)}", encoding="utf-8")
        outs.append(dst)
    return outs

@action("📝 LaTeX · Compiler en PDF", TEX)
def tex_to_pdf(files):
    """Compile un ou plusieurs fichiers .tex en PDF.

    Essaie dans l'ordre : latexmk (avec xelatex ou pdflatex), xelatex,
    pdflatex, puis tectonic (moteur autonome, pas besoin d'installation TeX).
    Si aucun moteur n'est disponible, explique comment en installer un.
    """
    def _latex_engine():
        """Retourne (nom, est_latexmk, est_tectonic) pour le premier moteur trouvé."""
        if which("latexmk"):
            return ("latexmk", True, False)
        if which("xelatex"):
            return ("xelatex", False, False)
        if which("pdflatex"):
            return ("pdflatex", False, False)
        if which("tectonic"):
            return ("tectonic", False, True)
        return None, False, False

    engine_name, use_latexmk, use_tectonic = _latex_engine()
    if engine_name is None:
        raise RuntimeError(
            "Aucun moteur LaTeX trouvé.\n\n"
            + ("Installe MiKTeX (miktex.org) ou TeX Live (tug.org/texlive)." if IS_WIN
               else "Installe MacTeX : brew install --cask mactex\n"
                    "Ou tectonic (léger) : brew install tectonic" if IS_MAC
               else "sudo apt install texlive-xetex  # ou texlive-full pour les polices complètes")
        )

    outs = []
    notify("Compilation LaTeX en cours…")
    for f in files:
        f = Path(f)
        dst = unique(f.with_suffix(".pdf"))
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            copy_tex_tree(f, tmp)
            tex_in_tmp = tmp / f.name
            if use_tectonic:
                cmd = [which("tectonic"), "-o", str(tmp), str(tex_in_tmp)]
                r = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp)
            elif use_latexmk:
                # -norc : un fichier latexmkrc (du code Perl) posé à côté du .tex n'est jamais exécuté
                cmd = ["latexmk", "-norc", "-pdf", "-xelatex" if which("xelatex") else "-pdflatex",
                       "-interaction=nonstopmode", "-halt-on-error", "-output-directory=" + str(tmp), str(tex_in_tmp)]
                r = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp)
            else:
                # xelatex / pdflatex : deux passes pour les références croisées
                cmd = [engine_name, "-interaction=nonstopmode", "-halt-on-error",
                       "-output-directory", str(tmp), str(tex_in_tmp)]
                r = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp)
                if r.returncode == 0:
                    r = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp)

            pdf_out = tmp / f.with_suffix(".pdf").name
            log_src = tmp / f.with_suffix(".log").name
            if log_src.exists():            # journal à côté du .tex (utile pour corriger une erreur)
                try:
                    shutil.copy2(log_src, f.with_suffix(".log"))
                except OSError:
                    pass
            if not pdf_out.exists():          # (l'ancien PDF n'est jamais recopié : celui-ci vient de cette compilation)
                err_lines = []
                if log_src.exists():
                    for line in log_src.read_text(encoding="utf-8", errors="replace").splitlines():
                        if line.startswith("!") or "Error" in line:
                            err_lines.append(line)
                err_msg = "\n".join(err_lines[-8:]) if err_lines else (r.stderr or r.stdout or "")[-600:]
                raise RuntimeError(
                    f"La compilation de « {f.name} » a échoué.\n\n"
                    + (err_msg or f"Consulte le journal {f.with_suffix('.log').name} à côté du fichier .tex.")
                )
            shutil.move(str(pdf_out), str(dst))
        outs.append(dst)
    return outs


TEX_EXTS = {".tex", ".sty", ".cls", ".bib", ".bst", ".bbx", ".cbx", ".lbx", ".dbx", ".def", ".cfg", ".clo", ".fd", ".ltx",
            ".ist", ".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg", ".tikz", ".pgf", ".csv", ".dat", ".txt", ".ttf",
            ".otf", ".bbl", ".gls", ".nlo", ".lua", ".mp", ".pdf_tex", ".table", ".gnuplot"}
TEX_STYLE = {".sty", ".cls", ".bib", ".bst", ".bbx", ".cbx", ".lbx", ".dbx", ".def", ".cfg", ".clo", ".fd"}
TEX_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "build", "_minted"}


def copy_tex_tree(f, tmp, max_files=3000, max_bytes=150 * 1024 * 1024, big=40 * 1024 * 1024):
    """Copie dans tmp ce dont LaTeX a besoin, sans jamais exécuter ni recopier n'importe quoi :
    - dossier du .tex : tous les fichiers (sources de \\lstinputlisting, données…), sauf latexmkrc, l'ancien PDF
      compilé (une compilation ratée renverrait l'ancienne version), vidéos, sons, archives et très gros fichiers ;
    - sous-dossiers (chapitres/, figures/…) : seulement les types utiles à TeX, dans la limite d'une taille raisonnable ;
    - dossier parent : fichiers de style (modèle commun)."""
    root = f.parent
    skip_top = {f.with_suffix(".pdf").name, f.with_suffix(".log").name, "latexmkrc", ".latexmkrc"}
    heavy = {"." + e for e in VID | AUD | ARC} | {".dmg", ".iso", ".exe", ".pkg", ".app"}
    n = size = 0
    for d, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if x not in TEX_SKIP_DIRS and not x.startswith(".")]
        rel = Path(d).relative_to(root)
        top = rel == Path(".")
        for name in names:
            src = Path(d) / name
            e = Path(name).suffix.lower()
            if top and (name in skip_top or e in heavy) or not top and e not in TEX_EXTS:
                continue
            try:
                sz = src.stat().st_size
            except OSError:
                continue
            if sz > big or n >= max_files or size + sz > max_bytes:
                continue                                  # trop gros pour être utile à LaTeX : ignoré
            n += 1
            size += sz
            (tmp / rel).mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, tmp / rel / name)
    parent = root.parent
    if parent != root:
        for src in parent.iterdir():
            if src.is_file() and src.suffix.lower() in TEX_STYLE and not (tmp / src.name).exists():
                shutil.copy2(src, tmp / src.name)


# ───────────────────────── TABLEURS ─────────────────────────

def read_tables(f):
    import pandas as pd
    e = ext(f)
    if e in ("csv", "tsv"):
        return {Path(f).stem: pd.read_csv(io.StringIO(read_any_text(f)), sep="\t" if e == "tsv" else None, engine="python")}
    if e == "json":
        try:
            data = json.loads(read_any_text(f))
        except ValueError as err:
            raise ValueError(f"« {Path(f).name} » n'est pas un fichier JSON valide ({err}).") from None
        if isinstance(data, dict) and all(isinstance(v, list) for v in data.values()):
            return {k: pd.json_normalize(v) for k, v in data.items()}
        return {Path(f).stem: pd.json_normalize(data if isinstance(data, list) else [data])}
    return pd.read_excel(f, sheet_name=None)


@action("📊 Tableur · Convertir (Excel ⇄ CSV ⇄ JSON)", TAB)
def tab_convert(files):
    import pandas as pd
    tgt = choose(["Excel (.xlsx)", "CSV", "JSON"], "Convertir en :")
    sep = ";"
    if tgt == "CSV":
        sep = ";" if choose(["Point-virgule ; (Excel en français)", "Virgule ,"], "Séparateur :").startswith("Point") else ","
    outs = []
    for f in files:
        sheets = read_tables(f)
        if tgt.startswith("Excel"):
            dst = unique(Path(f).with_suffix(".xlsx"))
            names = set()
            with written(dst), pd.ExcelWriter(dst) as xw:
                for name, df in sheets.items():
                    df.to_excel(xw, sheet_name=sheet_name(name, names), index=False)
            outs.append(dst)
        else:
            for name, df in sheets.items():
                suffix = f"_{name}" if len(sheets) > 1 else ""
                dst = unique(Path(f).with_name(f"{Path(f).stem}{suffix}." + ("csv" if tgt == "CSV" else "json")))
                if tgt == "CSV":
                    df.to_csv(dst, sep=sep, index=False, encoding="utf-8-sig")
                else:
                    dst.write_text(df.to_json(orient="records", force_ascii=False, indent=2, date_format="iso"), encoding="utf-8")
                outs.append(dst)
    return outs


@action("📊 Tableur · Fusionner plusieurs fichiers en un Excel", TAB, minf=2)
def tab_merge(files):
    import pandas as pd
    mode = choose(["Une feuille par fichier", "Tout empiler dans une seule feuille"], "Fusion :")
    tables = [(f, name, df) for f in files for name, df in read_tables(f).items()]   # tout lire avant d'écrire
    dst = unique(Path(files[0]).with_name("Fusion.xlsx"))
    names = set()
    with written(dst), pd.ExcelWriter(dst) as xw:
        if mode.startswith("Une"):
            for f, name, df in tables:
                stem = Path(f).stem
                label = stem if name == stem else f"{stem} - {name}"     # classeur à plusieurs feuilles
                df.to_excel(xw, sheet_name=sheet_name(label, names), index=False)
        else:
            frames = []
            for f, name, df in tables:
                df.insert(0, "Source", Path(f).name)
                frames.append(df)
            pd.concat(frames, ignore_index=True).to_excel(xw, sheet_name="Fusion", index=False)
    return [dst]


def sheet_name(name, used):
    """Nom de feuille Excel valide (31 caractères, sans []:*?/\\) et unique dans le classeur."""
    base = re.sub(r"[\[\]:*?/\\]", "_", str(name)).strip("'") or "Feuille"
    cand, i = base[:31], 2
    while cand.lower() in used:
        suf = f" ({i})"
        cand, i = base[:31 - len(suf)] + suf, i + 1
    used.add(cand.lower())
    return cand


class written:
    """with written(dst): … — si l'écriture échoue, le fichier à moitié écrit est supprimé."""
    def __init__(self, dst):
        self.dst = Path(dst)

    def __enter__(self):
        return self.dst

    def __exit__(self, et, ev, tb):
        if et is not None:
            self.dst.unlink(missing_ok=True)
        return False

# ───────────────────────── GÉNÉRAL ─────────────────────────

@action("📦 Compresser en ZIP")
def make_zip(files):
    p0 = Path(files[0])
    dst = unique(p0.parent / ("Archive.zip" if len(files) > 1 else p0.name + ".zip"))
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in files:
            p = Path(f)
            if p.is_dir():
                for s in p.rglob("*"):
                    if s.is_file() and s.name != ".DS_Store":
                        z.write(s, s.relative_to(p.parent))
            else:
                z.write(p, p.name)
    tot = sum((s.stat().st_size for f in files for s in ([Path(f)] if Path(f).is_file() else Path(f).rglob("*")) if s.is_file()))
    NOTES.append(f"{human(tot)} → {human(dst.stat().st_size)}")
    return [dst]


@action("📦 Extraire l'archive", ARC)
def extract_archive(files):
    outs = []
    for f in files:
        name = re.sub(r"\.(tar\.gz|tar\.bz2|tar\.xz|tgz|zip|tar|gz|bz2|xz)$", "", Path(f).name, flags=re.I)
        d = unique(Path(f).with_name(name))
        if zipfile.is_zipfile(f):
            d.mkdir()
            with zipfile.ZipFile(f) as z:
                for info in z.infolist():
                    if info.filename.startswith("__MACOSX/"):
                        continue
                    z.extract(info, d)
        elif tarfile.is_tarfile(f):
            d.mkdir()
            with tarfile.open(f) as t:
                t.extractall(d, filter="data")
        elif ext(f) in ("gz", "bz2", "xz"):
            import bz2, lzma
            opener = {"gz": gzip.open, "bz2": bz2.open, "xz": lzma.open}[ext(f)]
            try:
                with written(d), opener(f, "rb") as src, open(d, "wb") as o:
                    shutil.copyfileobj(src, o)
            except (OSError, EOFError, lzma.LZMAError) as err:
                raise RuntimeError(f"« {Path(f).name} » est abîmé ou n'est pas une archive lisible ({err}).") from None
        else:
            raise RuntimeError(f"Format d'archive non pris en charge (ou fichier abîmé) : {Path(f).name}")
        outs.append(d)
    return outs


@action("🔄 FileForge · Vérifier les mises à jour", None)
def app_update(files):
    spawn("updater.py", "--manual")
    return []


@action("🏷️ Renommer en lot (numérotation)", None, minf=2)
def batch_rename(files):
    base = ask(f"Renommer {len(files)} éléments.\nNom de base (ils deviendront « Nom_01 », « Nom_02 »…) :", "Fichier").strip()
    if not base:
        raise Cancel()
    if re.search(r'[/\\:*?"<>|]', base) or base.startswith("."):
        raise ValueError("Le nom ne peut pas contenir / \\ : * ? \" < > | ni commencer par un point.")
    w = max(2, len(str(len(files))))
    preview = "\n".join(f"{Path(f).name}  →  {base}_{i:0{w}d}{Path(f).suffix}" for i, f in enumerate(files[:6], 1))
    if buttons(f"Aperçu :\n\n{preview}{chr(10) + '…' if len(files) > 6 else ''}", ["Annuler", "Renommer"]) != "Renommer":
        raise Cancel()
    done = []      # [nom d'origine, nom temporaire, nom actuel] : de quoi tout remettre en place si un fichier résiste
    try:
        for i, f in enumerate(files, 1):  # passage par des noms temporaires pour éviter les collisions
            t = Path(f).with_name(f".ff_tmp_{i}_{os.getpid()}{Path(f).suffix}")
            os.rename(f, t)
            done.append([Path(f), t, t])
        for i, item in enumerate(done, 1):
            dst = unique(item[1].with_name(f"{base}_{i:0{w}d}{item[1].suffix}"))
            os.rename(item[1], dst)
            item[2] = dst
    except OSError as e:
        # en deux temps (nouveaux noms → temporaires → noms d'origine) : un nouveau nom peut être l'ancien nom
        # d'un autre fichier, et rename écraserait ce dernier
        for step in (lambda it: (it[2], it[1]), lambda it: (it[1], it[0])):
            for it in done:
                a, b = step(it)
                if a == b or not a.exists():
                    continue
                try:
                    if b.exists():
                        raise OSError("destination occupée")
                    os.rename(a, b)
                except OSError as err:
                    log(f"renommage : impossible de remettre {a} → {b} ({err})")
        raise RuntimeError(f"Renommage annulé, rien n'a changé : {e}") from None
    return [cur for _, _, cur in done]

# ───────────────────────── sélection des actions, fenêtres Tk ─────────────────────────

def available(files):
    res = []
    for a in ACTIONS:
        if len(files) < a["minf"]:
            continue
        if a["types"] is not None and not all(Path(f).is_file() and ext(f) in a["types"] for f in files):
            continue
        res.append(a)
    return res


def tk_entry(a):
    """Fenêtres visuelles lancées par la roue dans un processus séparé."""
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        base = Path(sys.base_prefix)
        for var, pat in (("TCL_LIBRARY", "tcl8*"), ("TK_LIBRARY", "tk8*")):
            if var not in os.environ:
                hit = next((d for d in [*base.glob("tcl/" + pat), *base.glob("lib/" + pat)] if (d / "init.tcl").exists() or d.name.startswith("tk")), None)
                if hit:
                    os.environ[var] = str(hit)
    try:
        if a["fn"] == "regions":
            if a["kind"] == "pdf":
                import pymupdf
                src = pymupdf.open(a["path"])
            else:
                src = load_img(a["path"])
            r = pick_regions(src, a["kind"], a["title"], a["hint"], a.get("multi", False), a.get("start_page", 0))
            print(json.dumps({"ok": {str(k): [list(x) for x in v] for k, v in r.items()}}))
        else:
            print(json.dumps({"ok": str(draw_signature())}))
    except Cancel:
        print(json.dumps({"cancel": True}))
    except Exception as e:
        log(traceback.format_exc())
        print(json.dumps({"error": str(e)}))


if __name__ == "__main__" and len(sys.argv) > 2 and sys.argv[1] == "--tk":
    tk_entry(json.loads(sys.argv[2]))
