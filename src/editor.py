#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileForge — éditeur de PDF.

    editor.py document.pdf

Modifier le texte existant, ajouter du texte, surligner / souligner / barrer, dessiner, encadrer,
effacer une zone, insérer une image, pivoter ou supprimer une page, annuler.
Chaque modification est appliquée aussitôt à une copie de travail en mémoire et la page est redessinée :
ce qu'on voit est exactement ce qui sera enregistré. L'original n'est jamais modifié : « Enregistrer »
crée « document_modifié.pdf » à côté.
"""
import base64, importlib.util, io, json, os, sys, tempfile, threading, time, traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("fileforge", HERE / "fileforge.py")
ff = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ff)
IS_WIN = sys.platform == "win32"
if sys.stdout is None or sys.stderr is None:
    _lf = open(ff.LOG, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _lf
    sys.stderr = sys.stderr or _lf

import pymupdf  # noqa: E402

TITLE = "FileForge — Éditeur PDF"
BASE14 = {  # (serif, mono, gras, italique) → police PDF standard
    (False, False, False, False): "helv", (False, False, True, False): "hebo", (False, False, False, True): "heit",
    (False, False, True, True): "hebi", (True, False, False, False): "tiro", (True, False, True, False): "tibo",
    (True, False, False, True): "tiit", (True, False, True, True): "tibi", (False, True, False, False): "cour",
    (False, True, True, False): "cobo", (False, True, False, True): "coit", (False, True, True, True): "cobi",
}
LATIN1 = set(range(32, 127)) | set(range(160, 256))     # ce que couvrent les polices PDF standard (pas €, œ, ’…)


def rgb(hexcol):
    h = (hexcol or "#000000").lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def to_hex(c):
    return "#%06x" % (c & 0xFFFFFF)


class Editor:
    """Document de travail + historique des modifications (rejouable pour « Annuler »)."""

    def __init__(self, path):
        self.path = Path(path)
        self.password = None
        self.ops = []
        self.lines = {}
        self.reload()

    def reload(self):
        self.doc = pymupdf.open(self.path)
        if self.doc.needs_pass and self.password:
            self.doc.authenticate(self.password)
        for op in self.ops:
            self._apply(op)

    # ── lecture
    def info(self):
        if self.doc.is_encrypted:          # (needs_pass reste vrai après authenticate : on regarde is_encrypted)
            return {"name": self.path.name, "needs_pass": True}
        return {"name": self.path.name, "needs_pass": False, "can_undo": bool(self.ops),
                "pages": [{"w": p.rect.width, "h": p.rect.height, "rot": p.rotation} for p in self.doc]}

    def unlock(self, pw):
        if self.doc.authenticate(pw):
            self.password = pw
            return True
        return False

    def render(self, i, zoom):
        page = self.doc[i]
        zoom = max(0.2, min(float(zoom), 6))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        img = "data:image/jpeg;base64," + base64.b64encode(pix.tobytes("jpeg", jpg_quality=90)).decode()
        rot = page.rotation_matrix
        lines = []
        for b in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
            for ln in b.get("lines", []):
                spans = [s for s in ln["spans"] if s["text"].strip()]
                if not spans:
                    continue
                s0 = max(spans, key=lambda s: len(s["text"]))
                flags = s0["flags"]
                fontname = s0["font"].lower()
                lines.append({
                    "id": len(lines), "text": "".join(s["text"] for s in ln["spans"]).strip(),
                    "bbox": tuple(pymupdf.Rect(ln["bbox"]) * rot),          # en coordonnées affichées
                    "raw_bbox": tuple(ln["bbox"]), "origin": tuple(spans[0]["origin"]),
                    "size": round(s0["size"], 2), "color": to_hex(s0["color"]),
                    "bold": bool(flags & 16) or "bold" in fontname or "black" in fontname,
                    "italic": bool(flags & 2) or "italic" in fontname or "oblique" in fontname,
                    "serif": bool(flags & 4) or any(k in fontname for k in ("times", "serif", "georgia", "garamond", "roman")),
                    "mono": bool(flags & 8) or any(k in fontname for k in ("courier", "mono", "consol")),
                    "dir": tuple(ln.get("dir", (1, 0))),
                })
        self.lines[i] = lines
        return {"img": img, "w": page.rect.width, "h": page.rect.height, "rot": page.rotation, "lines": lines}

    # ── modifications
    def do(self, op):
        """Applique une modification envoyée par l'interface ; renvoie les pages à redessiner."""
        op = dict(op)
        if op["type"] == "text_edit":   # on fige le style de la ligne visée (rejouable après « Annuler »)
            ln = self.lines[op["page"]][op["line"]]
            op.update(raw_bbox=ln["raw_bbox"], origin=ln["origin"], size=ln["size"], color=op.get("color") or ln["color"],
                      bold=ln["bold"], italic=ln["italic"], serif=ln["serif"], mono=ln["mono"], old=ln["text"], dir=ln["dir"])
        elif op["type"] == "image" and "file" in op:
            op["data"] = base64.b64encode(Path(op.pop("file")).read_bytes()).decode()
        self._apply(op)
        self.ops.append(op)
        return op

    def undo(self):
        if self.ops:
            self.ops.pop()
            self.reload()
        return bool(self.ops)

    def _derot(self, page, x, y):
        return pymupdf.Point(x, y) * page.derotation_matrix

    def _rect(self, page, r):
        a, b = self._derot(page, r[0], r[1]), self._derot(page, r[2], r[3])
        return pymupdf.Rect(min(a.x, b.x), min(a.y, b.y), max(a.x, b.x), max(a.y, b.y))

    def _font(self, page, text, bold=False, italic=False, serif=False, mono=False):
        """Police standard PDF si possible (accents français compris), sinon une police du système qui a
        tous les caractères du texte (€, œ, ✓…), la plus proche possible du style d'origine."""
        if all(ord(c) in LATIN1 for c in text):
            return {"fontname": BASE14[(serif and not mono, mono, bold, italic)]}
        k = (1 if bold else 0) + (2 if italic else 0)
        cands = []
        if IS_WIN:
            win = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
            fams = ([("consola", "consolab", "consolai", "consolaz"), ("cour", "courbd", "couri", "courbi")] if mono else
                    [("times", "timesbd", "timesi", "timesbi")] if serif else
                    [("arial", "arialbd", "ariali", "arialbi"), ("segoeui", "segoeuib", "segoeuii", "segoeuiz")])
            cands += [win / (f[k] + ".ttf") for f in fams] + [win / "seguisym.ttf", win / "arialuni.ttf"]
        elif sys.platform == "darwin":
            cands += [Path("/System/Library/Fonts/Supplemental") / n for n in
                      (("Courier New.ttf",) if mono else ("Times New Roman.ttf",) if serif else ("Arial.ttf",))]
            cands += [Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")]
        cands.append(Path(ff.font_file()))
        need = {ord(c) for c in text if not c.isspace()}
        for f in cands:
            if f.exists() and self._covers(f, need):
                return {"fontname": "FF" + f.stem.replace(" ", "")[:12], "fontfile": str(f)}
        f = next((c for c in cands if c.exists()), Path(ff.font_file()))
        return {"fontname": "FF" + f.stem.replace(" ", "")[:12], "fontfile": str(f)}

    _cov = {}

    def _covers(self, f, need):
        font = self._cov.get(f)
        if font is None:
            try:
                font = self._cov[f] = pymupdf.Font(fontfile=str(f))
            except Exception:
                return False
        return all(font.has_glyph(c) for c in need)

    def _insert_text(self, page, origin, text, size, color, rotate=0, **style):
        kw = self._font(page, text, **style)
        page.insert_text(origin, text, fontsize=size, color=rgb(color), rotate=rotate, **kw)
        if "fontfile" in kw:
            self._fix_spaces(page, kw["fontname"])

    def _fix_spaces(self, page, fontname):
        """Arial & co. ont un seul dessin pour l'espace et l'espace insécable : la table de correspondance
        générée dit « insécable », et un copier-coller ou une recherche dans le PDF donnerait des espaces
        spéciales. On la corrige pour nos polices."""
        import re
        doc = page.parent
        for xref, _e, _t, _b, name, _enc in page.get_fonts():
            if name != fontname:
                continue
            t = doc.xref_get_key(xref, "ToUnicode")
            if t[0] == "xref":
                tx = int(t[1].split()[0])
                st = doc.xref_stream(tx)
                fixed = re.sub(rb"<00[aA]0>", b"<0020>", st)
                if fixed != st:
                    doc.update_stream(tx, fixed)

    def _apply(self, op):
        t = op["type"]
        if t == "delete_page":
            self.doc.delete_page(op["page"])
            return
        page = self.doc[op["page"]]
        if t == "rotate":
            page.set_rotation((page.rotation + op.get("angle", 90)) % 360)
        elif t == "text_edit":
            r = pymupdf.Rect(op["raw_bbox"])
            page.add_redact_annot(r + (-0.5, -0.5, 0.5, 0.5), fill=False)      # retire les lettres, garde le fond
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
            if op["text"].strip():
                d = op.get("dir") or (1, 0)
                rotate = {(1, 0): 0, (0, -1): 90, (-1, 0): 180, (0, 1): 270}.get((round(d[0]), round(d[1])), 0)
                self._insert_text(page, op["origin"], op["text"], op["size"], op["color"], rotate=rotate,
                                  bold=op["bold"], italic=op["italic"], serif=op["serif"], mono=op["mono"])
        elif t == "text_add":
            # (x, y) = ligne de base de la 1re ligne, en coordonnées affichées ; sur une page pivotée, le texte
            # reçoit la même rotation que la page pour apparaître droit
            for k, line in enumerate(op["text"].split("\n")):
                if not line:
                    continue
                pt = self._derot(page, op["x"], op["y"] + op["size"] * 1.25 * k)
                self._insert_text(page, pt, line, op["size"], op["color"], rotate=page.rotation,
                                  bold=op.get("bold", False), italic=op.get("italic", False), serif=op.get("serif", False))
        elif t in ("highlight", "underline", "strike"):
            area = self._rect(page, op["rect"])
            rects = self._word_rects(page, area) or [area]
            annot = {"highlight": page.add_highlight_annot, "underline": page.add_underline_annot,
                     "strike": page.add_strikeout_annot}[t](rects)
            if op.get("color"):
                annot.set_colors(stroke=rgb(op["color"]))
            annot.update()
        elif t == "ink":
            pts = [tuple(self._derot(page, x, y)) for x, y in op["points"]]
            if len(pts) >= 2:
                a = page.add_ink_annot([pts])
                a.set_colors(stroke=rgb(op.get("color")))
                a.set_border(width=op.get("width", 2))
                a.update()
        elif t == "rect":
            a = page.add_rect_annot(self._rect(page, op["rect"]))
            a.set_colors(stroke=rgb(op.get("color")))
            a.set_border(width=op.get("width", 2))
            a.update()
        elif t == "whiteout":
            page.add_redact_annot(self._rect(page, op["rect"]), fill=(1, 1, 1))
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
        elif t == "image":
            page.insert_image(self._rect(page, op["rect"]), stream=base64.b64decode(op["data"]), keep_proportion=False,
                              rotate=page.rotation)
        else:
            raise ValueError(f"modification inconnue : {t}")

    def _word_rects(self, page, area):
        """Rectangles des mots couverts par la zone tracée, regroupés par ligne (surlignage « propre »)."""
        groups = {}
        for x0, y0, x1, y1, w, b, l, _ in page.get_text("words"):
            r = pymupdf.Rect(x0, y0, x1, y1)
            inter = r & area
            if not inter.is_empty and inter.get_area() >= 0.3 * r.get_area():
                k = (b, l)
                groups[k] = (groups[k] | r) if k in groups else pymupdf.Rect(r)
        return list(groups.values())

    def save(self, dest=None):
        dest = Path(dest) if dest else ff.unique(self.path.with_name(f"{self.path.stem}_modifié.pdf"))
        self.doc.save(dest, garbage=3, deflate=True)
        ff.log(f"éditeur : {len(self.ops)} modification(s) → {dest}")
        return str(dest)


class Api:
    # attributs « _ » : pywebview n'expose (et ne parcourt) que les noms publics — un document PyMuPDF
    # ou la fenêtre exposés ici font planter WebView2 au démarrage
    def __init__(self, path):
        self._ed = Editor(path)
        self._win = None
        self._lock = threading.Lock()

    def _safe(self, f, *a):
        with self._lock:
            try:
                return f(*a)
            except Exception as e:
                ff.log("éditeur : " + traceback.format_exc())
                return {"error": str(e)}

    def info(self):
        return self._safe(self._ed.info)

    def unlock(self, pw):
        return self._safe(self._ed.unlock, pw)

    def render(self, i, zoom):
        return self._safe(self._ed.render, i, zoom)

    def do(self, op):
        def f():
            op2 = self._ed.do(op)
            return {"ok": True, "op": {k: v for k, v in op2.items() if k != "data"}, "info": self._ed.info()}
        return self._safe(f)

    def undo(self):
        return self._safe(lambda: {"ok": self._ed.undo(), "info": self._ed.info()})

    def save(self):
        return self._safe(lambda: {"path": self._ed.save(), "n": len(self._ed.ops)})

    def pick_image(self):
        kind = getattr(getattr(__import__("webview"), "FileDialog", None), "OPEN", None) or 10
        r = self._win.create_file_dialog(kind, allow_multiple=False,
                                        file_types=("Images (*.png;*.jpg;*.jpeg;*.webp;*.gif;*.bmp)", "Tous les fichiers (*.*)"))
        if not r:
            return None
        return self._safe(self._image_info, r[0])

    def _image_info(self, p):
        from PIL import Image
        with Image.open(p) as im:
            w, h = im.size
            buf = io.BytesIO()
            im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB").save(buf, "PNG")
        return {"data": base64.b64encode(buf.getvalue()).decode(), "w": w, "h": h, "name": Path(p).name}

    def open_path(self, p):
        ff.open_path(p)

    def reveal(self, p):
        ff.reveal(p)


def window_size(pref=(1280, 880)):
    """Taille de fenêtre qui tient dans l'écran (petits portables, mise à l'échelle 125–175 %)."""
    try:
        if IS_WIN:
            import ctypes
            from ctypes import wintypes
            r = wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)   # SPI_GETWORKAREA
            try:
                k = ctypes.windll.user32.GetDpiForSystem() / 96
            except Exception:
                k = 1
            aw, ah = (r.right - r.left) / k, (r.bottom - r.top) / k
            return int(min(pref[0], aw * 0.94)), int(min(pref[1], ah * 0.94))
    except Exception:
        pass
    return pref


def main():
    import webview
    if len(sys.argv) < 2 or not Path(sys.argv[1]).exists():
        ff.log("éditeur : fichier introuvable")
        return
    ff.log(f"éditeur : ouverture de {sys.argv[1]}")
    api = Api(sys.argv[1])
    w, h = window_size()
    small = (w, h) != (1280, 880)        # petit écran : fenêtre agrandie (plein écran utile), rien ne dépasse
    win = webview.create_window(f"{TITLE} — {Path(sys.argv[1]).name}", str(HERE / "editor.html"), js_api=api,
                                width=w, height=h, min_size=(760, 520), background_color="#16171f", maximized=small)
    api._win = win

    def started(window):
        if os.environ.get("FF_DEBUG"):     # tests : JavaScript déposé dans %TEMP%\ff_editor_cmd.js
            cmd = Path(tempfile.gettempdir()) / "ff_editor_cmd.js"
            while True:
                if cmd.exists():
                    mine = cmd.with_name(f"ff_editor_cmd.{os.getpid()}.js")
                    try:
                        os.replace(cmd, mine)
                        js = mine.read_text(encoding="utf-8"); mine.unlink()
                    except OSError:
                        time.sleep(0.1); continue
                    try:
                        r = window.evaluate_js(js)
                    except Exception as e:
                        r = "ERR " + str(e)
                    tmp = cmd.with_name(f"ff_editor_cmd.{os.getpid()}.out")
                    tmp.write_text(str(r), encoding="utf-8")
                    for _ in range(20):           # écriture atomique ; le test peut être en train de lire l'ancien
                        try:
                            os.replace(tmp, cmd.parent / "ff_editor_cmd.out"); break
                        except OSError:
                            time.sleep(0.05)
                time.sleep(0.1)
    webview.start(started, (win,), http_port=ff.safe_port())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        ff.log(traceback.format_exc())
