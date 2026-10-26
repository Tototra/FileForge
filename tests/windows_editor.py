"""Pilote le vrai éditeur PDF installé sous Windows (CI).

    python windows_editor.py <dossier de résultats>

L'éditeur est lancé avec FF_DEBUG=1 : il exécute le JavaScript déposé dans %TEMP%\\ff_editor_cmd.js.
Chaque outil est utilisé avec de vrais événements de pointeur dans la page, puis le PDF enregistré est
vérifié avec PyMuPDF (texte, annotations, image, rotation) et l'original doit être resté intact.
"""
import base64, ctypes, hashlib, io, json, os, subprocess, sys, tempfile, time
from ctypes import wintypes
from pathlib import Path
from PIL import Image, ImageGrab
import pymupdf

ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
u = ctypes.windll.user32
D = Path(os.environ["LOCALAPPDATA"]) / "FileForge"
PYW = D / "venv" / "Scripts" / "pythonw.exe"
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
CMD = Path(tempfile.gettempdir()) / "ff_editor_cmd.js"
RES = CMD.parent / "ff_editor_cmd.out"
W = Path(tempfile.gettempdir()) / "Éditeur — dossier test"
W.mkdir(exist_ok=True)
fails = []


def expect(name, cond, info=""):
    print(("OK   " if cond else "FAIL ") + name, info, flush=True)
    if not cond:
        fails.append(name)
        shot(f"echec-{len(fails)}")


def shot(name):
    ImageGrab.grab(all_screens=True).save(OUT / f"ed-{name}.png")


def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def _rm(p):
    for _ in range(40):
        try:
            p.unlink(missing_ok=True); return
        except PermissionError:
            time.sleep(0.05)


def js(code, timeout=10):
    _rm(RES)
    CMD.write_text(code, encoding="utf-8")
    t = time.time()
    while time.time() - t < timeout:
        if RES.exists() and not CMD.exists():
            time.sleep(0.05)
            for _ in range(40):
                try:
                    return RES.read_text(encoding="utf-8")
                except PermissionError:
                    time.sleep(0.05)
            return ""
        time.sleep(0.05)
    CMD.unlink(missing_ok=True)
    return "TIMEOUT"


def state():
    try:
        return json.loads(js("ED.state()"))
    except ValueError:
        return {}


def idle(timeout=25, ops=None):
    t = time.time()
    while time.time() - t < timeout:
        s = state()
        if s.get("ready") and not s.get("busy") and s.get("rendered") and (ops is None or s.get("ops") == ops):
            time.sleep(0.25)
            return s
        time.sleep(0.2)
    return state()


def kill():
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*editor.py*' }"
                    " | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"], capture_output=True)


def find_window(prefix):
    buf, found = ctypes.create_unicode_buffer(256), []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        u.GetWindowTextW(h, buf, 256)
        if buf.value.startswith(prefix) and u.IsWindowVisible(h):
            found.append(h)
        return True
    u.EnumWindows(cb, 0)
    return found[0] if found else None


def launch(pdf, how="direct"):
    kill(); time.sleep(0.5)
    for f in (CMD, RES):
        f.unlink(missing_ok=True)
    env = dict(os.environ, FF_DEBUG="1")
    t0 = time.time()
    if how == "action":       # comme depuis la roue : l'action « Modifier (éditeur) »
        code = ("import sys; sys.path.insert(0, r'%s'); import fileforge as ff; ff.pdf_edit([r'%s'])" % (D, pdf))
        r = subprocess.run([str(D / "venv" / "Scripts" / "python.exe"), "-c", code], env=env, capture_output=True, text=True, timeout=60)
        print("lancement par l'action :", r.returncode, r.stdout[-500:], r.stderr[-1500:], flush=True)
    else:
        subprocess.Popen([str(PYW), str(D / "editor.py"), str(pdf)], env=env, cwd=os.environ["TEMP"])
    while time.time() - t0 < 45:
        if find_window("FileForge — Éditeur PDF") and js("typeof ED", 3).strip() == "object":
            return time.time() - t0
        time.sleep(0.3)
    return None


def outputs(stem):
    return sorted(W.glob(f"{stem}_modifié*.pdf"), key=lambda p: p.stat().st_mtime)


# ── documents de test
def make_main():
    d = pymupdf.open()
    p = d.new_page()
    p.insert_text((72, 100), "Facture n° 2026-118", fontsize=18)
    p.insert_text((72, 140), "Montant total : 1 250,00 EUR", fontsize=12)
    p.insert_text((72, 170), "Texte à surligner dans le document", fontsize=12)
    p.insert_text((72, 200), "Ligne à effacer complètement", fontsize=12)
    p.draw_rect(pymupdf.Rect(60, 400, 300, 460), color=(0, 0, 1), fill=(0.9, 0.95, 1))
    p.insert_text((72, 435), "Texte sur fond coloré", fontsize=12)
    for i in range(2):
        d.new_page().insert_text((72, 100), f"Page suivante {i + 2}", fontsize=16)
    f = W / "Facture été – client.pdf"
    d.save(f)
    return f


def make_rotated():
    d = pymupdf.open(); p = d.new_page(width=595, height=842)
    p.insert_text((72, 100), "Page pivotée à l'origine", fontsize=14)
    p.set_rotation(90)
    f = W / "pivotée.pdf"; d.save(f); return f


def make_locked():
    d = pymupdf.open(); d.new_page().insert_text((72, 100), "Secret", fontsize=14)
    f = W / "protégé.pdf"
    d.save(f, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="1234", owner_pw="owner"); return f


main = make_main()
h0 = md5(main)

# 1. ouverture depuis l'action de la roue
dt = launch(main, "action")
expect("éditeur ouvert depuis l'action « Modifier »", dt is not None, f"{dt and round(dt, 1)} s")
if dt is None:
    print("processus :", subprocess.run(["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*editor*' } | Select-Object ProcessId, CommandLine | Format-List"], capture_output=True, text=True).stdout)
    print("journal :", "\n".join((D / "FileForge.log").read_text(encoding="utf-8", errors="replace").splitlines()[-25:]))
    dt = launch(main)
    expect("éditeur ouvert directement", dt is not None, f"{dt and round(dt, 1)} s")
    if dt is None:
        print("journal :", "\n".join((D / "FileForge.log").read_text(encoding="utf-8", errors="replace").splitlines()[-25:]))
        sys.exit(1)
s = idle()
expect("pages affichées", s.get("pages") == 3 and s.get("rendered", 0) >= 1, json.dumps(s))
h = find_window("FileForge — Éditeur PDF")
if h:
    r = wintypes.RECT(); u.GetWindowRect(h, ctypes.byref(r))
    sw, sh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    expect("fenêtre de l'éditeur dans l'écran", r.left >= -8 and r.top >= -8 and r.right <= sw + 8 and r.bottom <= sh + 8,
           f"{(r.left, r.top, r.right, r.bottom)} écran {sw}x{sh}")
shot("1-ouvert")

lines = json.loads(js("ED.lines(0)") or "[]")
by = {l["text"]: l["id"] for l in lines}
expect("lignes de texte détectées", "Montant total : 1 250,00 EUR" in by, str(list(by)))


def line_point(text):
    """Point au milieu d'une ligne (coordonnées de page affichées)."""
    b = json.loads(js(f"JSON.stringify(S.pages[0].lines.find(l => l.text === {json.dumps(text)}).bbox)"))
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def pdown(x, y, page=0):
    js(f"ED.pointer({page}, 'pointerdown', {x}, {y})")


def drag(x0, y0, x1, y1, page=0, steps=6):
    pdown(x0, y0, page)
    for k in range(1, steps + 1):
        js(f"ED.pointer({page}, 'pointermove', {x0 + (x1 - x0) * k / steps}, {y0 + (y1 - y0) * k / steps})")
    js(f"ED.pointer({page}, 'pointerup', {x1}, {y1})")


n = 0
# 2. modifier une ligne existante (avec € et œ : police de secours)
js("ED.tool('edit')"); x, y = line_point("Montant total : 1 250,00 EUR"); pdown(x, y)
expect("zone de saisie ouverte sur la ligne", js("!!S.editing").strip() == "True")
js("ED.type('Montant total : 1 250,00 € (cœur)')"); shot("2-saisie"); js("ED.commit()")
n += 1; s = idle(ops=n); expect("texte modifié", s.get("ops") == n, json.dumps(s))
# 3. ajouter du texte
js("ED.tool('addtext')"); js("ED.opt('size', 14)"); pdown(72, 260)
js("ED.type('Ajouté par FileForge ✓ – merci')"); js("ED.commit()")
n += 1; s = idle(ops=n); expect("texte ajouté", s.get("ops") == n, json.dumps(s))
# 4. surligner, souligner
js("ED.tool('highlight')"); x, y = line_point("Texte à surligner dans le document")
drag(60, y - 8, 400, y + 8); n += 1; s = idle(ops=n); expect("surlignage", s.get("ops") == n, json.dumps(s))
js("ED.opt('hlStyle', 'underline')"); x, y = line_point("Facture n° 2026-118")
drag(60, y - 10, 300, y + 10); n += 1; s = idle(ops=n); expect("soulignement", s.get("ops") == n)
# 5. dessin à main levée et cadre
js("ED.tool('draw')"); pdown(100, 520)
for k in range(12):
    js(f"ED.pointer(0, 'pointermove', {100 + k * 18}, {520 + (k % 2) * 25})")
js("ED.pointer(0, 'pointerup', 320, 520)"); n += 1; s = idle(ops=n); expect("dessin", s.get("ops") == n)
js("ED.tool('rect')"); drag(50, 80, 330, 150); n += 1; s = idle(ops=n); expect("cadre", s.get("ops") == n)
# 6. effacer une ligne (contenu supprimé, pas juste masqué)
js("ED.tool('whiteout')"); x, y = line_point("Ligne à effacer complètement")
drag(65, y - 9, 330, y + 9); n += 1; s = idle(ops=n); expect("zone effacée", s.get("ops") == n)
# 7. texte modifié sur fond coloré : le fond doit rester
js("ED.tool('edit')"); x, y = line_point("Texte sur fond coloré"); pdown(x, y)
js("ED.type('Fond conservé')"); js("ED.commit()"); n += 1; s = idle(ops=n); expect("texte sur fond modifié", s.get("ops") == n)
# 8. image
buf = io.BytesIO(); Image.new("RGB", (240, 120), (220, 30, 60)).save(buf, "PNG")
js(f"ED.image('{base64.b64encode(buf.getvalue()).decode()}', 240, 120, 'logo.png')")
drag(380, 600, 520, 670); n += 1; s = idle(ops=n); expect("image insérée", s.get("ops") == n)
shot("3-modifié")
# 9. annuler puis refaire la dernière action
js("ED.undo()"); s = idle(ops=n - 1); expect("annuler", s.get("ops") == n - 1, json.dumps(s))
drag(380, 600, 520, 670); s = idle(ops=n); expect("image remise", s.get("ops") == n)
# 10. pivoter la page 2, supprimer la page 3
js("setCur(1); ED.rotate()"); n += 1; s = idle(ops=n); expect("page pivotée", s.get("ops") == n)
js("setCur(2); ED.del()"); n += 1; s = idle(ops=n); expect("page supprimée", s.get("pages") == 2, json.dumps(s))
# 11. enregistrer
before = set(outputs(main.stem))
js("ED.save()")
t = time.time()
while time.time() - t < 20 and set(outputs(main.stem)) == before:
    time.sleep(0.3)
time.sleep(0.8)
shot("4-enregistré")
new = [p for p in outputs(main.stem) if p not in before]
expect("copie enregistrée à côté de l'original", len(new) == 1, str(new))
expect("original intact", md5(main) == h0)
if new:
    d = pymupdf.open(new[0])
    p = d[0]; txt = p.get_text()
    expect("PDF : 2 pages", d.page_count == 2, str(d.page_count))
    expect("PDF : € et œ présents", "1 250,00 €" in txt and "cœur" in txt, repr(txt[:300]))
    expect("PDF : ancien montant parti", "1 250,00 EUR" not in txt)
    expect("PDF : texte ajouté", "Ajouté par FileForge" in txt)
    expect("PDF : ligne effacée supprimée du fichier", "Ligne à effacer" not in txt)
    expect("PDF : texte sur fond modifié", "Fond conservé" in txt and "Texte sur fond coloré" not in txt)
    kinds = sorted(a.type[1] for a in p.annots())
    expect("PDF : annotations", all(k in kinds for k in ("Highlight", "Underline", "Ink", "Square")), str(kinds))
    expect("PDF : image", len(p.get_images()) == 1, str(p.get_images()))
    pix = p.get_pixmap(clip=pymupdf.Rect(62, 402, 70, 410))
    expect("PDF : fond coloré conservé", pix.pixel(2, 2)[2] > 200 and pix.pixel(2, 2)[0] < 245, str(pix.pixel(2, 2)))
    expect("PDF : page 2 pivotée", d[1].rotation == 90, str(d[1].rotation))
    p.get_pixmap(dpi=80).save(OUT / "ed-resultat-page1.png")
kill()

# 12. page pivotée à l'origine : texte ajouté droit et au bon endroit
rot = make_rotated()
launch(rot); idle()
js("ED.tool('addtext')"); js("ED.opt('size', 16)"); pdown(100, 300)
js("ED.type('Ajout droit')"); js("ED.commit()"); idle(ops=1)
js("ED.save()"); time.sleep(3); kill()
o = outputs(rot.stem)
expect("page pivotée : enregistrée", bool(o))
if o:
    d = pymupdf.open(o[-1]); p = d[0]
    ws = [w for w in p.get_text("words") if w[4] == "Ajout"]
    if ws:
        disp = pymupdf.Rect(ws[0][:4]) * p.rotation_matrix
        expect("page pivotée : texte au bon endroit", abs(disp.x0 - 100) < 12 and abs(disp.y1 - 300) < 25, str(disp))
        dirs = [l["dir"] for b in p.get_text("dict")["blocks"] for l in b.get("lines", []) if "Ajout" in "".join(s["text"] for s in l["spans"])]
        expect("page pivotée : texte droit à l'écran", bool(dirs), str(dirs))
    else:
        expect("page pivotée : texte trouvé", False, p.get_text())

# 13. PDF protégé : demande du mot de passe
lk = make_locked()
launch(lk); time.sleep(2.5)
expect("protégé : fenêtre du mot de passe", js("document.getElementById('m-pass').classList.contains('in')").strip() == "True")
shot("5-mot-de-passe")
js("document.getElementById('pw').value = 'faux'; document.getElementById('pw-ok').click(); true"); time.sleep(1)
expect("protégé : mauvais mot de passe refusé", js("document.getElementById('m-pass').classList.contains('in')").strip() == "True")
js("document.getElementById('pw').value = '1234'; document.getElementById('pw-ok').click(); true")
s = idle(); expect("protégé : ouvert avec le bon mot de passe", s.get("pages") == 1, json.dumps(s))
kill()

# 14. gros document : ouverture rapide, pages rendues à la demande
d = pymupdf.open()
for i in range(150):
    d.new_page().insert_text((72, 100), f"Page {i + 1} " + "texte " * 40, fontsize=10)
big = W / "gros document.pdf"; d.save(big)
dt = launch(big); s = idle()
expect("150 pages : ouverture", s.get("pages") == 150, f"{dt and round(dt, 1)} s, {json.dumps(s)}")
expect("150 pages : rendu paresseux (pas tout d'un coup)", 0 < s.get("rendered", 0) < 30, str(s.get("rendered")))
kill()

log = (D / "FileForge.log").read_text(encoding="utf-8", errors="replace") if (D / "FileForge.log").exists() else ""
ed_errs = [l for l in log.split("\n") if "éditeur :" in l and "Traceback" in l]
expect("journal : aucune erreur de l'éditeur", not ed_errs, "\n".join(ed_errs[:3]))
print(f"\n{len(fails)} échec(s) : {fails}")
sys.exit(1 if fails else 0)
