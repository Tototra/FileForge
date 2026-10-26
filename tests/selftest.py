"""Test automatique de toutes les actions FileForge (dialogues simulés)."""
import sys, shutil, subprocess, traceback, importlib.util as u
from pathlib import Path
_here = Path(__file__).resolve().parent
_src = _here / "fileforge.py" if (_here / "fileforge.py").exists() else _here.parent / "src" / "fileforge.py"
spec = u.spec_from_file_location("ff", _src)
ff = u.module_from_spec(spec); spec.loader.exec_module(ff)
import tempfile
T = Path(tempfile.gettempdir()) / "ff_test"; shutil.rmtree(T, ignore_errors=True); T.mkdir()

import pymupdf
from PIL import Image, ImageDraw
d = pymupdf.open()
for i in range(4):
    p = d.new_page()
    p.insert_text((72, 100), f"Page {i+1} — Bonjour le monde, facture confidentielle", fontsize=14)
    p.draw_rect(pymupdf.Rect(72, 150, 400, 300), color=(0, 0, 1))
    for r in range(4):
        for c in range(3):
            p.insert_text((80 + c * 100, 330 + r * 20), f"R{r}C{c}", fontsize=10)
    img = Image.new("RGB", (200, 120), (200, 80, 40)); import io; b = io.BytesIO(); img.save(b, "PNG")
    p.insert_image(pymupdf.Rect(72, 450, 272, 570), stream=b.getvalue())
d.save(T / "doc.pdf"); shutil.copy(T / "doc.pdf", T / "doc2.pdf")
im = Image.new("RGBA", (800, 600), (0, 0, 0, 0)); ImageDraw.Draw(im).ellipse((200, 150, 600, 450), fill=(30, 140, 220, 255)); im.save(T / "logo.png")
im2 = Image.new("RGB", (1600, 1200), "white"); ImageDraw.Draw(im2).rectangle((300, 200, 1300, 1000), fill=(220, 30, 60)); im2.save(T / "photo.jpg", quality=95)
Image.new("RGB", (640, 480), "green").save(T / "photo.heic") if "HEIF" in Image.SAVE else None
subprocess.run([ff.FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=25", "-f", "lavfi", "-i", "sine=frequency=440",
                "-t", "4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(T / "clip.mov")], check=True)
subprocess.run([ff.FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=330", "-t", "5", str(T / "son.wav")], check=True)
shutil.copy(T / "son.wav", T / "son2.wav")
(T / "data.csv").write_text("nom;age;ville\nAlice;30;Paris\nBob;25;Lyon\n", encoding="utf-8")
(T / "notes.md").write_text("# Titre\n\nUn **paragraphe** avec é à ç.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n- point 1\n- point 2\n", encoding="utf-8")
(T / "lisez.txt").write_text("Ligne 1\nLigne 2 accentuée é\n", encoding="utf-8")

ANS = {}
def choose(items, prompt, default=None, multiple=False, ok="OK"):
    for k, v in ANS.items():
        if k in prompt and v in items: return v
    return default if default in items else items[0]
ff.choose = choose
ff.ask = lambda prompt, default="", hidden=False: ANS.get("ask", default) if not hidden else "secret"
ff.buttons = lambda prompt, btns, default=None: btns[-1]
ff.notify = lambda m: None
ff.pick_regions = lambda src, kind, *a, **k: {0: [(50, 50, 400, 400)]}
ff.choose_file = lambda *a, **k: str(T / "logo.png")
ff.draw_signature = lambda: T / "logo.png"

F = lambda *n: [str(T / x) for x in n]
cases = {
    "pdf": F("doc.pdf"), "pdf2": F("doc.pdf", "doc2.pdf"), "img": F("photo.jpg", "logo.png"),
    "vid": F("clip.mov"), "aud": F("son.wav"), "aud2": F("son.wav", "son2.wav"), "tab": F("data.csv"),
    "md": F("notes.md"), "txt": F("lisez.txt"),
}
ok = fail = 0
for a in ff.ACTIONS:
    if "Renommer" in a["label"] or "Informations" in a["label"] or "éditeur" in a["label"] or "mises à jour" in a["label"]:
        continue
    for name, files in cases.items():
        if len(files) < a["minf"] or (a["types"] and not all(ff.ext(f) in a["types"] for f in files)):
            continue
        if a["types"] is None and name not in ("pdf2",):
            continue
        ff.NOTES.clear()
        ANS.clear()
        if "Diviser" in a["label"]: ANS.update({"Comment": "Une page = un PDF"})
        if "Supprimer des pages" in a["label"]: ANS.update({"ask": "2"})
        try:
            outs = a["fn"](list(files)) or []
            bad = [o for o in outs if not Path(o).exists() or (Path(o).is_file() and Path(o).stat().st_size == 0)]
            if bad: raise RuntimeError(f"sortie manquante {bad}")
            ok += 1
            print(f"OK   {a['label']}  [{name}] → {[Path(o).name for o in outs][:3]} {ff.NOTES[:1]}")
        except Exception as e:
            fail += 1
            print(f"FAIL {a['label']}  [{name}] : {e}")
            traceback.print_exc(limit=2)
        break
# chaînes : docx (via pdf2docx) → markdown / pdf ; zip → extract
docx = next(T.glob("doc*.docx"), None)
for lab, files in [("Word · Convertir", [docx]), ("Extraire l'archive", list(T.glob("*.zip"))[:1])]:
    a = next(x for x in ff.ACTIONS if lab in x["label"])
    try:
        print("OK  ", lab, [Path(o).name for o in a["fn"]([str(f) for f in files])])
        ok += 1
    except Exception as e:
        print("FAIL", lab, e); fail += 1
# Markdown → PDF : blocs de code lisibles (fond, couleurs, lignes longues coupées, rien de perdu)
try:
    md = T / "code.md"
    md.write_text("# Code\n\n```python\ndef f(x):\n    return x * 2  # " + "très " * 40 + "fin\n```\n\n"
                  "```\nhttps://exemple.com/" + "a" * 150 + "\n```\n", encoding="utf-8")
    a = next(x for x in ff.ACTIONS if "Document · Convertir en PDF" in x["label"])
    pdf = a["fn"]([str(md)])[0]
    pg = pymupdf.open(pdf)[0]
    txt = pg.get_text().replace("\u200b", "")
    assert "def f(x):" in txt and "fin" in txt, "code perdu"
    assert "a" * 150 in txt.replace("\n", "").replace(" ", ""), "longue ligne perdue"
    words = [w for w in pg.get_text("words")]
    assert max(w[2] for w in words) <= pg.rect.width - 30, "le code dépasse de la page"
    assert any(dr.get("fill") for dr in pg.get_drawings()), "pas de fond derrière le code"
    print("OK   Markdown → PDF : blocs de code")
    ok += 1
except Exception as e:
    print("FAIL Markdown → PDF : blocs de code :", e); fail += 1
print(f"\n{ok} OK / {fail} échecs")
