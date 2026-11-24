"""Socle de la suite de tests FileForge (pytest).

    .venv/bin/python -m pytest tests          # tout
    .venv/bin/python -m pytest tests -m "not slow"

Les modules de src/ sont chargés comme le fait l'application (par chemin). Les dialogues sont simulés par `ui`
(réponses choisies par un morceau du texte de la question), et tous les fichiers d'exemple (PDF, images, sons,
vidéos, documents, tableaux, archives, LaTeX) sont fabriqués une seule fois par session dans `assets`.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import zipfile
import tarfile
import gzip
import bz2
import lzma
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
IS_MAC = sys.platform == "darwin"


def load(name, alias=None):
    spec = importlib.util.spec_from_file_location(alias or name, SRC / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ff = load("fileforge")


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: tests longs (OCR, LibreOffice, LaTeX, vidéo)")
    config.addinivalue_line("markers", "gui: ouvre de vraies fenêtres (roue, éditeur, mise à jour)")


@pytest.fixture(autouse=True)
def _isolated_log(tmp_path, monkeypatch):
    """Le journal des tests ne pollue pas celui de l'utilisateur."""
    monkeypatch.setattr(ff, "LOG", tmp_path / "FileForge.log")
    ff.NOTES.clear()
    yield
    ff.NOTES.clear()


# ───────────────────────── dialogues simulés ─────────────────────────

class FakeUI:
    """Remplace choose / ask / buttons / alert / notify / pick_regions / draw_signature / choose_file.

    ui.set("Mot de passe", "abc") : toute question contenant « Mot de passe » reçoit « abc »
    (la règle la plus récente gagne ; une valeur peut être une liste = réponses successives)."""

    def __init__(self, assets):
        self.rules = []
        self.prompts = []
        self.notes = []
        self.regions = None
        self.region_calls = []
        self.assets = assets

    def set(self, key, value):
        self.rules.append([key, value])
        return self

    def _rule(self, prompt):
        for rule in reversed(self.rules):
            k, v = rule
            if k in prompt:
                if isinstance(v, list):
                    if not v:
                        continue
                    return v.pop(0) if len(v) > 1 else v[0]
                return v
        return None

    def choose(self, items, prompt, default=None, multiple=False, ok="OK"):
        items = list(items)
        self.prompts.append(prompt)
        v = self._rule(prompt)
        if v is not None:
            if v in items:
                return v
            hit = [i for i in items if str(v) in i]
            assert hit, f"réponse {v!r} absente de {items} pour « {prompt} »"
            return hit[0]
        return default if default in items else items[0]

    def ask(self, prompt, default="", hidden=False):
        self.prompts.append(prompt)
        v = self._rule(prompt)
        return str(default if v is None else v)

    def buttons(self, prompt, btns, default=None):
        self.prompts.append(prompt)
        v = self._rule(prompt)
        return v if v is not None else list(btns)[-1]

    def alert(self, title, msg=""):
        self.prompts.append(f"{title}\n{msg}")

    def notify(self, msg):
        self.notes.append(msg)

    def choose_file(self, prompt, types=None):
        return str(self.assets / "logo.png")

    def pick_regions(self, src, kind, title, hint, multi=False, start_page=0):
        self.region_calls.append(dict(kind=kind, title=title, multi=multi, start_page=start_page))
        if callable(self.regions):
            return self.regions(src)
        return self.regions or {0: [(50.0, 50.0, 300.0, 300.0)]}

    def draw_signature(self):
        return self.assets / "logo.png"


@pytest.fixture
def ui(assets, monkeypatch):
    u = FakeUI(assets)
    for n in ("choose", "ask", "buttons", "alert", "notify", "choose_file", "pick_regions", "draw_signature"):
        monkeypatch.setattr(ff, n, getattr(u, n))
    return u


# ───────────────────────── fichiers d'exemple ─────────────────────────

def run_ff(*args):
    subprocess.run([ff.FFMPEG, "-y", "-loglevel", "error", *map(str, args)], check=True)


def make_pdfs(T):
    import pymupdf
    from PIL import Image
    import io

    def png(color, size=(200, 120)):
        b = io.BytesIO()
        Image.new("RGB", size, color).save(b, "PNG")
        return b.getvalue()

    d = pymupdf.open()
    for i in range(4):
        p = d.new_page()
        p.insert_text((72, 100), f"Page {i + 1} — Bonjour le monde, facture confidentielle", fontsize=14)
        p.draw_rect(pymupdf.Rect(72, 150, 400, 300), color=(0, 0, 1))
        p.insert_image(pymupdf.Rect(72, 450, 272, 570), stream=png((200, 80, 40)))
    d.set_metadata({"title": "Contrat Dupont", "author": "Jean Dupont", "subject": "confidentielle"})
    d.set_toc([[1, "Contrat Dupont", 1]])
    d.save(T / "doc.pdf")
    shutil.copy(T / "doc.pdf", T / "doc2.pdf")

    # page pivotée à 90° (scan classique) : « SECRET » en haut à gauche de la page NON pivotée
    d = pymupdf.open()
    p = d.new_page(width=595, height=842)
    p.insert_text((72, 100), "SECRET word here", fontsize=20)
    p.insert_text((72, 700), "public footer", fontsize=12)
    p.set_rotation(90)
    d.save(T / "rotated.pdf")

    # tableau dessiné (find_tables le détecte)
    d = pymupdf.open()
    p = d.new_page()
    x0, y0, cw, rh = 72, 100, 120, 24
    rows = [["Nom", "Âge", "Ville"], ["Alice", "30", "Paris"], ["Bob", "25", "Lyon"]]
    for r, row in enumerate(rows):
        for c, txt in enumerate(row):
            rect = pymupdf.Rect(x0 + c * cw, y0 + r * rh, x0 + (c + 1) * cw, y0 + (r + 1) * rh)
            p.draw_rect(rect, color=(0, 0, 0), width=0.8)
            p.insert_text((rect.x0 + 4, rect.y1 - 7), txt, fontsize=11)
    d.save(T / "table.pdf")

    # portrait + paysage
    d = pymupdf.open()
    d.new_page(width=595, height=842).insert_text((72, 100), "portrait", fontsize=20)
    d.new_page(width=842, height=595).insert_text((72, 100), "paysage", fontsize=20)
    d.save(T / "mixed.pdf")

    # chiffrés
    src = pymupdf.open(T / "doc.pdf")
    src.save(T / "locked.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="s3cret", owner_pw="s3cret")
    src = pymupdf.open(T / "doc.pdf")
    src.save(T / "spacepw.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=" pw ", owner_pw=" pw ")

    # scan (image seule, sans texte)
    txt = pymupdf.open()
    tp = txt.new_page()
    tp.insert_text((72, 120), "Bonjour le monde", fontsize=36)
    tp.insert_text((72, 200), "Facture numero 4521", fontsize=36)
    pix = tp.get_pixmap(dpi=200)
    d = pymupdf.open()
    sp = d.new_page()
    sp.insert_image(sp.rect, pixmap=pix)
    d.save(T / "scan.pdf")

    # formulaire + annotation
    d = pymupdf.open()
    p = d.new_page()
    w = pymupdf.Widget()
    w.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    w.field_name = "nom"
    w.field_value = "Rempli par Alice"
    w.rect = pymupdf.Rect(72, 100, 300, 130)
    p.add_widget(w)
    a = p.add_text_annot((72, 200), "Note interne")
    a.update()
    d.save(T / "form.pdf")

    # PDF abîmé (fin coupée) et faux PDF
    raw = (T / "doc.pdf").read_bytes()
    (T / "broken.pdf").write_bytes(raw[: int(len(raw) * 0.85)])
    (T / "fake.pdf").write_text("pas un pdf du tout")

    # une seule page
    d = pymupdf.open()
    d.new_page().insert_text((72, 100), "seule", fontsize=12)
    d.save(T / "one.pdf")


def find_font(*names):
    dirs = [Path("/System/Library/Fonts/Supplemental"), Path("/System/Library/Fonts"), Path("/Library/Fonts"),
            Path.home() / "Library/Fonts", Path(r"C:\Windows\Fonts"), Path("/usr/share/fonts")]
    for n in names:
        for d in dirs:
            if (d / n).exists():
                return d / n
    return None


def make_font_pdfs(T):
    """PDF dont le texte utilise une police intégrée non standard (pour l'éditeur)."""
    import pymupdf
    font = find_font("Georgia.ttf", "Verdana.ttf", "Trebuchet MS.ttf", "DejaVuSerif.ttf", "georgia.ttf")
    if not font:
        return
    (T / "fontname.txt").write_text(font.stem)
    d = pymupdf.open()
    p = d.new_page()
    p.insert_font(fontname="F0", fontfile=str(font))
    p.insert_text((72, 100), "Texte original dans une police spéciale", fontname="F0", fontsize=16, color=(0.1, 0.2, 0.6))
    p.insert_text((72, 160), "Deuxième ligne", fontname="F0", fontsize=12)
    d.save(T / "font_full.pdf")
    d.subset_fonts()
    d.save(T / "font_subset.pdf", garbage=3)


def make_images(T):
    from PIL import Image, ImageDraw, ExifTags
    im = Image.new("RGB", (1600, 1200), "white")
    ImageDraw.Draw(im).rectangle((300, 200, 1300, 1000), fill=(220, 30, 60))
    ex = Image.Exif()
    ex[0x010F] = "TestCam"
    ex[0x0110] = "Model X"
    ex[ExifTags.IFD.GPSInfo] = {1: "N", 2: (48.0, 51.0, 30.0), 3: "E", 4: (2.0, 21.0, 0.0)}
    im.save(T / "photo.jpg", quality=95, exif=ex)
    ex6 = Image.Exif()
    ex6[0x0112] = 6       # à faire pivoter de 90° à l'affichage
    Image.new("RGB", (400, 200), "blue").save(T / "oriented.jpg", exif=ex6)
    gps_exif = Image.open(T / "photo.jpg").getexif()
    im.save(T / "photo.tiff", exif=gps_exif)
    im.save(T / "photo.png", exif=gps_exif)
    im.save(T / "photo.webp", quality=90, exif=gps_exif)
    im.save(T / "photo.bmp")
    lg = Image.new("RGBA", (800, 600), (0, 0, 0, 0))
    ImageDraw.Draw(lg).ellipse((200, 150, 600, 450), fill=(30, 140, 220, 255))
    lg.save(T / "logo.png")
    Image.new("L", (300, 200), 128).save(T / "gray.png")
    pal = Image.new("P", (120, 80))
    pal.putpalette([0, 0, 0, 255, 0, 0] + [0] * 762)
    ImageDraw.Draw(pal).rectangle((20, 20, 100, 60), fill=1)
    pal.save(T / "palette.png", transparency=0)
    Image.new("CMYK", (300, 200), (0, 120, 200, 0)).save(T / "cmyk.jpg")
    Image.new("I;16", (100, 80), 30000).save(T / "deep.png")
    bd = Image.new("RGB", (500, 400), "white")
    ImageDraw.Draw(bd).rectangle((100, 80, 380, 300), fill="black")
    bd.save(T / "border.png")
    frames = [Image.new("RGB", (120, 90), c) for c in ("red", "green", "blue")]
    frames[0].save(T / "anim.gif", save_all=True, append_images=frames[1:], duration=200, loop=0)
    try:
        ff._heif()
        im.save(T / "photo.heic", quality=80, exif=gps_exif.tobytes())
    except Exception:
        pass
    try:
        im.save(T / "photo.avif", quality=60)
    except Exception:
        pass


def make_media(T):
    run_ff("-f", "lavfi", "-i", "testsrc=size=640x360:rate=25", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
           "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", T / "clip.mov")
    run_ff("-i", T / "clip.mov", "-c:v", "libvpx-vp9", "-b:v", "300k", "-deadline", "realtime", "-c:a", "libopus", T / "clip.webm")
    run_ff("-i", T / "clip.mov", "-c:v", "wmv2", "-c:a", "wmav2", T / "clip.wmv")
    run_ff("-i", T / "clip.mov", "-c:v", "mpeg4", "-c:a", "libmp3lame", T / "clip.avi")
    run_ff("-i", T / "clip.mov", "-c", "copy", T / "clip.mkv")
    run_ff("-i", T / "clip.mov", "-c:v", "copy", "-an", T / "silent.mp4")
    run_ff("-f", "lavfi", "-i", "sine=frequency=330:sample_rate=44100", "-t", "4", "-ac", "2", T / "son.wav")
    run_ff("-f", "lavfi", "-i", "sine=frequency=550:sample_rate=22050", "-t", "3", "-ac", "1", T / "mono22.wav")
    for e, codec in (("mp3", ["-c:a", "libmp3lame"]), ("opus", ["-c:a", "libopus"]), ("aac", ["-c:a", "aac"]),
                     ("aif", ["-c:a", "pcm_s16be"]), ("aiff", ["-c:a", "pcm_s16be"]), ("flac", ["-c:a", "flac"]),
                     ("ogg", ["-c:a", "libopus"]), ("m4a", ["-c:a", "aac"]), ("wma", ["-c:a", "wmav2"])):
        run_ff("-i", T / "son.wav", *codec, T / f"son.{e}")


def make_docs(T):
    (T / "notes.md").write_text(
        "# Titre été\n\nUn **paragraphe** avec é à ç € œ.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n- point 1\n- point 2\n\n"
        "```python\ndef f(x):\n    return x * 2\n```\n", encoding="utf-8")
    (T / "lisez.txt").write_text("Ligne 1\nLigne 2 accentuée é\n<b>pas du html</b>\n", encoding="utf-8")
    (T / "ansi.txt").write_bytes("Café crème à 2 €\n".encode("cp1252"))
    (T / "page.html").write_text("<html><body><h1>Bonjour</h1><p>Texte <i>riche</i> é</p><img src='logo.png'></body></html>",
                                 encoding="utf-8")
    import docx
    doc = docx.Document()
    doc.add_heading("Rapport été", 1)
    doc.add_paragraph("Un paragraphe avec des accents : à ç é œ €.")
    t = doc.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text, t.cell(1, 0).text, t.cell(1, 1).text = "A", "B", "1", "2"
    doc.save(T / "rapport.docx")
    from pptx import Presentation
    pr = Presentation()
    s = pr.slides.add_slide(pr.slide_layouts[1])
    s.shapes.title.text = "Séance 1 — été"
    pr.save(T / "slides.pptx")
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.title = "Budget"
    wb.active.append(["Poste", "Montant"])
    wb.active.append(["Café", 3.5])
    ws = wb.create_sheet("Notes")
    ws.append(["k", "v"])
    ws.append(["x", 1])
    wb.save(T / "multi.xlsx")


def make_tables(T):
    (T / "data.csv").write_text("nom;age;ville\nAlice;30;Paris\nBob;25;Lyon\n", encoding="utf-8")
    (T / "comma.csv").write_text("nom,age\nAlice,30\nBob,25\n", encoding="utf-8")
    (T / "data.tsv").write_text("nom\tage\nZoé\t41\n", encoding="utf-8")
    (T / "ansi.csv").write_bytes("nom;ville\nRené;Besançon\n".encode("cp1252"))
    (T / "data.json").write_text(json.dumps([{"nom": "Alice", "age": 30}, {"nom": "Bob", "age": 25}]), encoding="utf-8")
    (T / "dict.json").write_text(json.dumps({"clients": [{"n": 1}], "ventes": [{"m": 2}]}), encoding="utf-8")
    (T / "rapport [v2].csv").write_text("a;b\n1;2\n", encoding="utf-8")
    (T / "un_nom_de_fichier_vraiment_tres_long_A.csv").write_text("a\n1\n2\n3\n", encoding="utf-8")
    (T / "un_nom_de_fichier_vraiment_tres_long_B.csv").write_text("b\n9\n", encoding="utf-8")


def make_archives(T):
    src = T / "arch_src"
    (src / "dossier").mkdir(parents=True)
    (src / "dossier" / "a.txt").write_text("A")
    (src / "b.txt").write_text("B")
    with zipfile.ZipFile(T / "arch.zip", "w") as z:
        z.write(src / "dossier" / "a.txt", "dossier/a.txt")
        z.write(src / "b.txt", "b.txt")
        z.writestr("__MACOSX/._b.txt", "junk")
    with tarfile.open(T / "arch.tar.gz", "w:gz") as t:
        t.add(src / "dossier", "dossier")
    (T / "single.txt.gz").write_bytes(gzip.compress(b"contenu gz"))
    (T / "single.txt.bz2").write_bytes(bz2.compress(b"contenu bz2"))
    (T / "single.txt.xz").write_bytes(lzma.compress(b"contenu xz"))
    with zipfile.ZipFile(T / "evil.zip", "w") as z:
        z.writestr("../evil_outside.txt", "pwned")
        z.writestr("ok.txt", "ok")
    shutil.rmtree(src)


def make_tex(T):
    s = T / "tex_simple"
    s.mkdir()
    (s / "doc.tex").write_text("\\documentclass{article}\\begin{document}Bonjour \\LaTeX{} — été.\\end{document}\n",
                               encoding="utf-8")
    sub = T / "tex_sub"
    (sub / "chapitres").mkdir(parents=True)
    (sub / "figures").mkdir()
    (sub / "chapitres" / "intro.tex").write_text("Introduction depuis un sous-dossier.\n", encoding="utf-8")
    from PIL import Image
    Image.new("RGB", (60, 40), "red").save(sub / "figures" / "fig.png")
    (sub / "main.tex").write_text(
        "\\documentclass{article}\\usepackage{graphicx}\\begin{document}\\input{chapitres/intro}"
        "\\includegraphics[width=2cm]{figures/fig.png}\\end{document}\n", encoding="utf-8")
    err = T / "tex_err"
    err.mkdir()
    (err / "bad.tex").write_text("\\documentclass{article}\\begin{document}\\undefinedmacro\\end{document}\n")
    rc = T / "tex_rc"
    rc.mkdir()
    (rc / "doc.tex").write_text("\\documentclass{article}\\begin{document}ok\\end{document}\n")
    (rc / "latexmkrc").write_text("system('touch PWNED_BY_LATEXMKRC');\n")
    (rc / "film.mp4").write_bytes(b"\0" * 1024)
    tpl = T / "tex_tpl"
    (tpl / "rapport").mkdir(parents=True)
    (tpl / "monstyle.sty").write_text("\\newcommand{\\marque}{STYLE-PARENT}\n")
    (tpl / "rapport" / "r.tex").write_text(
        "\\documentclass{article}\\usepackage{monstyle}\\begin{document}\\marque\\end{document}\n")


@pytest.fixture(scope="session")
def assets(tmp_path_factory):
    T = tmp_path_factory.mktemp("assets")
    make_pdfs(T)
    make_font_pdfs(T)
    make_images(T)
    make_media(T)
    make_docs(T)
    make_tables(T)
    make_archives(T)
    make_tex(T)
    return T


@pytest.fixture
def get(assets, tmp_path):
    """get("doc.pdf", "logo.png") → copies fraîches dans le dossier du test (chemins str)."""
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)

    def _get(*names):
        res = []
        for n in names:
            s = assets / n
            if not s.exists():
                pytest.skip(f"fichier d'exemple indisponible sur ce système : {n}")
            d = work / n
            if s.is_dir():
                shutil.copytree(s, d, dirs_exist_ok=True)
            else:
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s, d)
            res.append(str(d))
        return res if len(res) > 1 else res[0]
    return _get


def act(name):
    """La fonction d'action enregistrée sous ce nom."""
    return next(a for a in ff.ACTIONS if a["fn"].__name__ == name)["fn"]


def probe(path):
    """Flux d'un fichier audio/vidéo (via ffmpeg -i)."""
    r = subprocess.run([ff.FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    return r.stderr


def duration(path):
    import re
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", probe(path))
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None


def pdf_text(path, password=None):
    import pymupdf
    d = pymupdf.open(str(path))
    if password:
        d.authenticate(password)
    return "\n".join(p.get_text() for p in d)
