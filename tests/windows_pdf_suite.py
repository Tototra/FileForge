"""Batterie de tests de toutes les actions PDF sur des documents variés (CI Windows, marche aussi ailleurs).

    python windows_pdf_suite.py <dossier de résultats> [dossier de fileforge.py]

Documents : texte accentué, 60 pages, scan sans texte, formats mélangés + page pivotée, formulaire,
annotations, chiffré, lecture seule, chemin avec accents/emoji/espaces, fichier abîmé.
Pour chaque action × document : la sortie existe et s'ouvre, le résultat a du sens (nombre de pages,
texte, rotation, chiffrement…), l'original n'a pas bougé, pas de boucle de saisie infinie, durée mesurée.
Un fichier abîmé doit donner un message d'erreur clair, jamais un plantage ni un blocage.
"""
import hashlib, io, json, os, shutil, stat, sys, tempfile, threading, time, traceback, zipfile
import importlib.util as iu
from pathlib import Path

OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
cands = [Path(sys.argv[2])] if len(sys.argv) > 2 else []
cands += [Path(os.environ.get("LOCALAPPDATA", "/nonexistent")) / "FileForge", Path(__file__).resolve().parent.parent / "src"]
SRC = next(c for c in cands if (c / "fileforge.py").exists())
spec = iu.spec_from_file_location("ff", SRC / "fileforge.py")
ff = iu.module_from_spec(spec); spec.loader.exec_module(ff)
import pymupdf
from PIL import Image, ImageDraw

T = Path(tempfile.gettempdir()) / "ff_pdf_suite"
shutil.rmtree(T, ignore_errors=True); T.mkdir()
WEIRD = T / "Dossier spécial ü 🎉 (copie)"; WEIRD.mkdir()

# ───────── réponses simulées aux questions ─────────
ASKED = {}


def _count(prompt):
    k = prompt.split("\n")[0][:60]
    ASKED[k] = ASKED.get(k, 0) + 1
    if ASKED[k] > 4:
        raise RuntimeError(f"boucle de saisie : « {k} » redemandé sans fin")


def ask(prompt, default="", hidden=False):
    _count(prompt)
    if hidden:
        return "secret"
    p = prompt.lower()
    import re
    m = re.search(r"\((\d+) pages\)", prompt)
    if m and int(m.group(1)) < 3 and "à extraire" in p:
        return "2"
    for key, v in [("à extraire", "2-3"), ("supprimer", "2"), ("pivoter", "tout"), ("nombre de pages par", "2"),
                   ("plages", "1-2; 3-fin"), ("nouvel ordre", default)]:
        if key in p:
            return v
    return default or "1"


def choose(items, prompt, default=None, multiple=False, ok="OK"):
    _count(prompt)
    for key, v in [("diviser", "Une page = un PDF"), ("rotation", "90° vers la droite")]:
        if key in prompt.lower() and v in items:
            return [v] if multiple else v
    v = default if default in items else items[0]
    return [v] if multiple else v


ff.ask, ff.choose = ask, choose
ff.buttons = lambda prompt, btns, default=None: btns[-1]
ff.notify = lambda m: None
ff.pick_regions = lambda src, kind, *a, **k: {0: [(50, 50, 300, 200)]}
ff.choose_file = lambda *a, **k: str(T / "logo.png")
ff.draw_signature = lambda: T / "logo.png"
ff.launch_editor = lambda f: None          # l'éditeur a sa propre batterie (windows_editor.py)

# ───────── documents ─────────
Image.new("RGBA", (400, 200), (30, 140, 220, 255)).save(T / "logo.png")


def png(w, h, col):
    b = io.BytesIO(); Image.new("RGB", (w, h), col).save(b, "PNG"); return b.getvalue()


def text_pdf(path, n=5, size=None):
    d = pymupdf.open()
    for i in range(n):
        p = d.new_page(**({"width": size[0], "height": size[1]} if size else {}))
        p.insert_text((72, 90), f"Page {i + 1} — Été, déjà vu, garçon, œuvre", fontsize=14)
        for r in range(5):
            for c in range(3):
                p.insert_text((80 + c * 110, 140 + r * 18), f"L{r}C{c} {r * c}", fontsize=10)
        p.insert_image(pymupdf.Rect(72, 260, 272, 360), stream=png(400, 200, (200, 80, 40)))
    d.save(path)
    return path


from PIL import ImageFont
FONT = None
for fp in [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf", Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
           Path("/System/Library/Fonts/Supplemental/Arial.ttf")]:
    if fp.exists():
        FONT = ImageFont.truetype(str(fp), 48); break
FONT = FONT or ImageFont.load_default(size=48)
DOCS = {}
DOCS["texte"] = text_pdf(T / "Texte accentué.pdf")
DOCS["60 pages"] = text_pdf(T / "Long 60 pages.pdf", 60)
d = pymupdf.open()
for i in range(3):            # « scan » : uniquement des images, aucun texte
    im = Image.new("RGB", (1240, 1754), "white"); dr = ImageDraw.Draw(im)
    for k in range(12):
        dr.text((100, 120 + k * 110), f"Facture scannee ligne {k + 1} page {i + 1}", fill=(20, 20, 20), font=FONT)
    b = io.BytesIO(); im.save(b, "JPEG", quality=70)
    d.new_page().insert_image(pymupdf.Rect(0, 0, 595, 842), stream=b.getvalue())
d.save(T / "Scan.pdf"); DOCS["scan"] = T / "Scan.pdf"
d = pymupdf.open()
for w, h in [(595, 842), (612, 792), (842, 595), (420, 595)]:
    d.new_page(width=w, height=h).insert_text((50, 80), f"Format {w}x{h}", fontsize=12)
d[2].set_rotation(90)
d.save(T / "Formats mélangés.pdf"); DOCS["formats + pivotée"] = T / "Formats mélangés.pdf"
d = pymupdf.open(); p = d.new_page(); p.insert_text((72, 80), "Formulaire d'inscription", fontsize=14)
for i, (nm, val) in enumerate([("nom", "Dupont"), ("ville", "Besançon")]):
    wd = pymupdf.Widget(); wd.field_name, wd.field_value = nm, val
    wd.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT; wd.rect = pymupdf.Rect(72, 110 + i * 40, 300, 135 + i * 40)
    p.add_widget(wd)
d.new_page().insert_text((72, 80), "Page 2", fontsize=14)
d.save(T / "Formulaire.pdf"); DOCS["formulaire"] = T / "Formulaire.pdf"
d = pymupdf.open(text_pdf(T / "_a.pdf", 3))
d[0].add_highlight_annot(pymupdf.Rect(70, 75, 300, 95)); d[1].add_text_annot((300, 300), "Note")
d.save(T / "Annoté.pdf"); d.close(); DOCS["annotations"] = T / "Annoté.pdf"
d = pymupdf.open(text_pdf(T / "_c.pdf", 3))
d.save(T / "Chiffré.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="own"); d.close()
DOCS["chiffré"] = T / "Chiffré.pdf"
ro = text_pdf(T / "Lecture seule.pdf", 3); os.chmod(ro, stat.S_IREAD); DOCS["lecture seule"] = ro
DOCS["chemin bizarre"] = text_pdf(WEIRD / "Rapport — final (v2) 'été' 🎉.pdf", 3)
raw = DOCS["texte"].read_bytes()
(T / "Abîmé.pdf").write_bytes(raw[: len(raw) // 3]); DOCS["abîmé"] = T / "Abîmé.pdf"
(T / "_a.pdf").unlink(); (T / "_c.pdf").unlink()

# ───────── vérifications par action ─────────
def pages(p):
    with pymupdf.open(p) as d:
        if d.needs_pass:
            d.authenticate("secret")
        return d.page_count


def n_in(src):
    with pymupdf.open(src) as d:
        d.needs_pass and d.authenticate("secret")
        return d.page_count, [pg.rotation for pg in d]


def check(fn, src, outs):
    """Renvoie un message si le résultat n'a pas de sens, sinon ''."""
    n, rots = n_in(src)
    pdfs = [o for o in outs if str(o).lower().endswith(".pdf") and Path(o).is_file()]
    for o in pdfs:
        with pymupdf.open(o) as d:
            if not d.needs_pass and d.page_count == 0:
                return f"{Path(o).name} vide"
    first = Path(outs[0]) if outs else None
    if fn == "pdf_split":
        k = len(list(first.glob("*.pdf")))
        return "" if k == n else f"{k} fichiers pour {n} pages"
    if fn == "pdf_extract":
        want = 2 if n >= 3 else 1
        return "" if pages(first) == want else f"{pages(first)} pages au lieu de {want}"
    if fn == "pdf_delete":
        return "" if pages(first) == n - 1 else f"{pages(first)} pages au lieu de {n - 1}"
    if fn in ("pdf_reorder", "pdf_compress", "pdf_gray", "pdf_flatten", "pdf_numbers", "pdf_watermark", "pdf_ocr",
              "pdf_repair", "pdf_meta", "pdf_redact", "pdf_sign", "pdf_crop"):
        return "" if pages(first) == n else f"{pages(first)} pages au lieu de {n}"
    if fn == "pdf_rotate":
        with pymupdf.open(first) as d:
            got = [pg.rotation for pg in d]
        want = [(r + 90) % 360 for r in rots]
        return "" if got == want else f"rotations {got} au lieu de {want}"
    if fn == "pdf_protect":
        with pymupdf.open(first) as d:
            return "" if d.needs_pass else "pas chiffré"
    if fn == "pdf_unlock":
        with pymupdf.open(first) as d:
            return "" if not d.needs_pass else "toujours chiffré"
    if fn == "pdf_to_images":
        imgs = [p for o in outs for p in (Path(o).glob("*") if Path(o).is_dir() else [Path(o)]) if p.suffix.lower() in (".jpg", ".png")]
        for p in imgs[:3]:
            Image.open(p).verify()
        return "" if len(imgs) == n else f"{len(imgs)} images pour {n} pages"
    if fn in ("pdf_to_word", "pdf_to_pptx", "pdf_to_excel"):
        for o in outs:
            if Path(o).suffix.lower() in (".docx", ".pptx", ".xlsx"):
                zipfile.ZipFile(o).testzip()
        return ""
    if fn == "pdf_to_text":
        t = Path(first).read_text(encoding="utf-8", errors="replace") if first and first.is_file() else ""
        if src.name == "Scan.pdf":
            return "" if "scann" in t.lower() else f"OCR sans résultat : {t[:80]!r}"
        return "" if "Été" in t or "Format" in t or "Formulaire" in t else f"texte introuvable : {t[:80]!r}"
    return ""


def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def run_one(a, files, timeout=240):
    res = {}

    def go():
        try:
            res["outs"] = a["fn"](list(map(str, files))) or []
        except BaseException as e:
            res["err"] = e; res["tb"] = traceback.format_exc(limit=3)
    th = threading.Thread(target=go, daemon=True); th.start(); th.join(timeout)
    if th.is_alive():
        res["err"] = TimeoutError(f"bloqué plus de {timeout} s")
    return res


rows, fails, slow = [], [], []
pdf_actions = [a for a in ff.ACTIONS if a["types"] and "pdf" in a["types"] and "Informations" not in a["label"]]
print(f"{len(pdf_actions)} actions PDF × {len(DOCS)} documents  (fileforge : {SRC})", flush=True)
for a in pdf_actions:
    fn = a["fn"].__name__
    for dname, src in DOCS.items():
        if a["minf"] > 1:
            if dname not in ("texte", "scan", "chemin bizarre"):
                continue
            files = [src, DOCS["formats + pivotée"]]
        else:
            files = [src]
        if fn == "pdf_unlock" and dname != "chiffré":
            continue
        n0 = n_in(src)[0] if dname != "abîmé" else 0
        if fn in ("pdf_extract", "pdf_delete", "pdf_split") and n0 == 1:
            continue
        before = {f: md5(f) for f in files}
        ASKED.clear(); ff.NOTES.clear()
        t0 = time.time()
        r = run_one(a, files)
        dt = time.time() - t0
        intact = all(md5(f) == h for f, h in before.items())
        status, info = "OK", ""
        if dname == "abîmé":
            # un fichier abîmé : soit l'action s'en sort (réparation), soit une erreur claire — jamais un blocage
            if isinstance(r.get("err"), TimeoutError) or "boucle" in str(r.get("err", "")):
                status, info = "FAIL", str(r["err"])
            else:
                status, info = "OK", ("erreur claire : " + str(r["err"])[:70]) if "err" in r else "réparé"
        elif "err" in r:
            status, info = "FAIL", f"{type(r['err']).__name__}: {r['err']}"
        else:
            outs = r["outs"]
            missing = [o for o in outs if not Path(o).exists() or (Path(o).is_file() and Path(o).stat().st_size == 0)]
            if missing:
                status, info = "FAIL", f"sortie manquante {missing}"
            else:
                try:
                    msg = check(fn, src, outs)
                except Exception as e:
                    msg = f"sortie illisible : {e}"
                if msg:
                    status, info = "FAIL", msg
                else:
                    info = ", ".join(Path(o).name for o in outs[:2])
                    if outs and not all(Path(o).parent == Path(src).parent or Path(o).parent.parent == Path(src).parent for o in outs):
                        status, info = "FAIL", f"sortie ailleurs qu'à côté de l'original : {outs[0]}"
        if not intact:
            status, info = "FAIL", "ORIGINAL MODIFIÉ " + info
        line = f"{status:4} {dt:6.2f}s  {a['label'][:44]:44} [{dname}] {info}"
        print(line, flush=True)
        rows.append({"action": fn, "doc": dname, "status": status, "s": round(dt, 2), "info": info})
        if status != "OK":
            fails.append(line)
            if "tb" in r:
                print("      " + r["tb"].replace("\n", "\n      "))
        if dt > (60 if dname == "60 pages" or fn == "pdf_ocr" else 20):
            slow.append(line)

# chemin bizarre : la sortie doit être dans le même dossier
(OUT / "pdf-suite.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
summary = [f"{sum(r['status'] == 'OK' for r in rows)} OK / {len(fails)} échecs sur {len(rows)} essais", "",
           "LENTS :"] + slow + ["", "ÉCHECS :"] + fails
(OUT / "pdf-suite.txt").write_text("\n".join(summary), encoding="utf-8")
print("\n" + "\n".join(summary))
os.chmod(ro, stat.S_IWRITE | stat.S_IREAD)
sys.exit(1 if fails else 0)
