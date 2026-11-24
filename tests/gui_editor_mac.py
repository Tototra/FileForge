"""Test de l'éditeur PDF dans sa vraie fenêtre (macOS / Windows) : on ouvre editor.py, on modifie une ligne comme un
utilisateur (clic sur la ligne, saisie, Entrée), on enregistre, puis on vérifie le PDF produit.

    .venv/bin/python tests/gui_editor_mac.py fichier.pdf "morceau de la ligne à modifier" "nouveau texte"
"""
import json, os, subprocess, sys, tempfile, time
from pathlib import Path

import pymupdf

SRC = Path(__file__).resolve().parent.parent / "src"
pdf, needle, new = Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3]
T = Path(tempfile.gettempdir())
CMD, OUT = T / "ff_editor_cmd.js", T / "ff_editor_cmd.out"
for f in (CMD, OUT):
    f.unlink(missing_ok=True)
p = subprocess.Popen([sys.executable, str(SRC / "editor.py"), str(pdf)], env=dict(os.environ, FF_DEBUG="1"))


def js(code, timeout=30):
    OUT.unlink(missing_ok=True)
    CMD.write_text(code, encoding="utf-8")
    t = time.time()
    while time.time() - t < timeout:
        if OUT.exists():
            try:
                return OUT.read_text(encoding="utf-8")
            except OSError:
                pass
        time.sleep(0.1)
    raise TimeoutError(code[:80])


def wait(expr, timeout=40):
    t = time.time()
    while time.time() - t < timeout:
        try:
            if js(expr, 5) == "True":
                return True
        except TimeoutError:
            pass
        time.sleep(0.3)
    return False


fails = []


def expect(name, cond, info=""):
    print(("OK   " if cond else "FAIL ") + name, info, flush=True)
    if not cond:
        fails.append(name)


try:
    expect("éditeur ouvert et page rendue", wait("typeof S !== 'undefined' && !!(S.pages && S.pages[0] && S.pages[0].lines && S.pages[0].lines.length)"))
    lines = json.loads(js("JSON.stringify(S.pages[0].lines.map(l => [l.id, l.text, l.font]))"))
    target = next((l for l in lines if needle in l[1]), None)
    expect("ligne visée trouvée", target is not None, str(lines)[:200])
    fam = js(f"family(S.pages[0].lines[{target[0]}])")
    expect("la zone de saisie affiche la police de la ligne", fam.startswith('"' + target[2].split("+")[-1].split("-")[0].split(" ")[0] + '"'), fam)
    # comme un utilisateur : outil « Modifier », clic sur la ligne, saisie, Entrée
    js("setTool('edit'); true")
    js(f"""(function(){{ const P = S.pages[0]; const el = P.ov.querySelector('.ln[data-id="{target[0]}"]');
        const r = el.getBoundingClientRect();
        el.dispatchEvent(new PointerEvent('pointerdown', {{bubbles: true, clientX: r.left + 3, clientY: r.top + 3}}));
        return !!S.editing }})()""")
    expect("zone de saisie ouverte sur la ligne", js("!!S.editing") == "True")
    js(f"S.editing.el.textContent = {json.dumps(new)}; S.editing.el.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Enter', bubbles: true}})); true")
    expect("modification appliquée", wait(f"!S.editing && S.ops >= 1 && S.pages[0].lines.some(l => l.text.includes({json.dumps(new[:12])}))"))
    js("window.__saved = null; api().save().then(r => window.__saved = r); true")
    expect("enregistré", wait("!!window.__saved"))
    saved = json.loads(js("JSON.stringify(window.__saved)"))
    out = Path(saved["path"])
    d = pymupdf.open(out)
    spans = [s for b in d[0].get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"] if new[:12] in s["text"]]
    orig = [s for b in pymupdf.open(pdf)[0].get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"] if needle in s["text"]]
    norm = lambda n: n.split("+")[-1].lower().replace("-", "").replace("regular", "").replace(" ", "")
    expect("texte enregistré dans le PDF", bool(spans) and new in d[0].get_text(), d[0].get_text()[:120])
    expect("police d'origine conservée", spans and norm(spans[0]["font"]) == norm(orig[0]["font"]),
           f"{spans[0]['font'] if spans else '?'} / {orig[0]['font']}")
    expect("taille et couleur conservées", spans and abs(spans[0]["size"] - orig[0]["size"]) < 0.1 and spans[0]["color"] == orig[0]["color"])
    expect("l'original n'a pas été modifié", needle in pymupdf.open(pdf)[0].get_text())
    out.unlink(missing_ok=True)
finally:
    p.terminate()
    try:
        p.wait(5)
    except subprocess.TimeoutExpired:
        p.kill()
print(f"\n{len(fails)} échec(s) : {fails}")
sys.exit(1 if fails else 0)
