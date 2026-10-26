#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileForge — mises à jour.

    updater.py --auto      lancé par l'agent toutes les quelques heures : vérifie au plus une fois par jour,
                           ne montre rien s'il n'y a pas de nouvelle version (ni si « Plus tard » est récent)
    updater.py --manual    « Vérifier les mises à jour » : affiche toujours une réponse
    updater.py --check     affiche l'état en JSON (tests)

Le site publie downloads/manifest.json : version, notes, « required » (mise à jour importante, installée sans
demander), et pour chaque système le fichier d'installation et son empreinte SHA-256. Le fichier téléchargé est
refusé si son empreinte ne correspond pas. L'installation se fait en silence, par-dessus l'actuelle (réglages,
Python et LibreOffice conservés).
"""
import hashlib, importlib.util, json, os, subprocess, sys, tempfile, threading, time, traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("fileforge", HERE / "fileforge.py")
ff = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ff)
IS_WIN, IS_MAC = sys.platform == "win32", sys.platform == "darwin"
if sys.stdout is None or sys.stderr is None:
    _lf = open(ff.LOG, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _lf
    sys.stderr = sys.stderr or _lf

SITE = "https://filiforme.to-trahant.workers.dev"
MANIFEST = os.environ.get("FF_UPDATE_URL") or f"{SITE}/downloads/manifest.json"
STATE = ff.LOG.parent / "update.json"
EVERY = 20 * 3600            # au plus une vérification automatique par ~jour
SNOOZE = 3 * 86400           # « Plus tard » : on reproposera la même version dans 3 jours
OS_KEY = "windows" if IS_WIN else "macos" if IS_MAC else "linux"


def log(m):
    ff.log("mise à jour : " + m)


def vtuple(v):
    out = []
    for x in str(v).split("."):
        n = "".join(c for c in x if c.isdigit())
        out.append(int(n) if n else 0)
    return tuple(out + [0] * (4 - len(out)))


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(st):
    try:
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def fetch(url, dest=None, timeout=60):
    """Télécharge (curl, présent sur Windows 10+ et macOS : il utilise les certificats du système).
    Accepte aussi un chemin local (tests)."""
    if not url.startswith(("http://", "https://")):
        src = Path(url[7:] if url.startswith("file://") else url)
        if dest:
            dest.write_bytes(src.read_bytes()); return dest
        return src.read_bytes()
    exe = "curl.exe" if IS_WIN else "curl"
    args = [exe, "-fsSL", "--max-time", str(timeout), "--retry", "2", "-A", f"FileForge/{ff.__version__}"]
    try:
        if dest:
            r = subprocess.run(args + ["-o", str(dest), url], capture_output=True, timeout=timeout + 30)
            if r.returncode == 0:
                return dest
        else:
            r = subprocess.run(args + [url], capture_output=True, timeout=timeout + 30)
            if r.returncode == 0:
                return r.stdout
        err = r.stderr.decode(errors="replace").strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        err = str(e)
    import urllib.request          # repli
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = resp.read()
    except Exception as e:
        raise RuntimeError(f"téléchargement impossible ({err or e})")
    if dest:
        dest.write_bytes(data); return dest
    return data


def check():
    """→ dict : current, latest, newer, required, notes, file (nom, sha256, url)."""
    m = json.loads(fetch(MANIFEST, timeout=20))
    f = (m.get("files") or {}).get(OS_KEY) or {}
    if MANIFEST.startswith(("http://", "https://")):
        base = MANIFEST.rsplit("/", 1)[0]
    else:                                       # chemin local (tests), y compris avec des « \ » sous Windows
        base = os.path.dirname(MANIFEST[7:] if MANIFEST.startswith("file://") else MANIFEST)
    newer = vtuple(m.get("version", "0")) > vtuple(ff.__version__)
    return {"current": ff.__version__, "latest": m.get("version"), "newer": newer,
            "required": bool(m.get("required")) and newer, "notes": m.get("notes") or [],
            "file": dict(f, url=(f"{base}/{f['name']}" if base.startswith("http") else os.path.join(base, f["name"]))) if f.get("name") else None}


def download(info, progress=lambda p: None):
    f = info["file"]
    dest = Path(tempfile.gettempdir()) / f"FileForge-{info['latest']}-{f['name']}"
    dest.unlink(missing_ok=True)
    done = threading.Event()

    def watch():          # progression d'après la taille du fichier en cours d'écriture
        while not done.wait(0.25):
            try:
                progress(min(0.99, dest.stat().st_size / max(1, f.get("bytes", 1))))
            except OSError:
                pass
    threading.Thread(target=watch, daemon=True).start()
    try:
        fetch(f["url"], dest, timeout=600)
    finally:
        done.set()
    h = hashlib.sha256(dest.read_bytes()).hexdigest()
    if h != f.get("sha256"):
        dest.unlink(missing_ok=True)
        raise RuntimeError("le fichier téléchargé ne correspond pas à l'empreinte publiée : installation refusée")
    progress(1.0)
    return dest


def install(path):
    """Lance l'installation silencieuse et attend qu'elle se termine (l'agent et la roue sont relancés par elle)."""
    if IS_WIN:
        # détaché : l'installateur arrête l'agent qui nous a lancés
        p = subprocess.Popen([str(path), "/S"], cwd=tempfile.gettempdir(),
                             creationflags=0x00000008 | 0x00000200 | 0x01000000)   # DETACHED, NEW_GROUP, BREAKAWAY
        try:
            return p.wait(timeout=1500)
        except subprocess.TimeoutExpired:
            raise RuntimeError("l'installation ne s'est pas terminée (une autre installation de FileForge est peut-être "
                               "ouverte : ferme-la puis réessaie)")
    if IS_MAC:
        d = Path(tempfile.mkdtemp(prefix="FileForge-maj-"))
        subprocess.run(["ditto", "-x", "-k", str(path), str(d)], check=True)
        script = next(d.rglob("install.command"))
        env = dict(os.environ, FILEFORGE_UPDATE="1")
        with open(ff.LOG, "a", encoding="utf-8") as out:
            p = subprocess.Popen(["/bin/bash", str(script)], cwd=str(script.parent), env=env, stdout=out, stderr=out,
                                 stdin=subprocess.DEVNULL, start_new_session=True)   # survit à l'arrêt de l'agent
        return p.wait(timeout=3600)
    ff.open_path(f"{SITE}/#download")         # Linux : page de téléchargement
    return 0


# ───────────────────────── fenêtre ─────────────────────────
HTML = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><style>
:root{color-scheme:dark}*{box-sizing:border-box}
body{margin:0;height:100vh;display:flex;flex-direction:column;justify-content:center;padding:26px 28px;background:#16171f;color:#f2f2f7;
 font:13.5px "Segoe UI Variable Text","Segoe UI",-apple-system,system-ui,sans-serif;-webkit-user-select:none;user-select:none}
.ic{width:42px;height:42px;border-radius:12px;background:linear-gradient(135deg,#7c5cff,#ec4899);display:flex;align-items:center;justify-content:center;margin-bottom:14px}
h1{font-size:17px;margin:0 0 4px;font-weight:650}.sub{color:#9d9db3;margin:0 0 12px}
ul{margin:0 0 16px;padding-left:18px;color:#d6d6e4;line-height:1.5;max-height:110px;overflow:auto}
.row{display:flex;gap:8px;justify-content:flex-end;margin-top:auto}
button{all:unset;cursor:pointer;padding:9px 16px;border-radius:10px;font-weight:600;background:rgba(255,255,255,.08)}
button:hover{background:rgba(255,255,255,.14)}.pri{background:#7c5cff}.pri:hover{background:#8b6dff}
.bar{height:6px;border-radius:3px;background:rgba(255,255,255,.1);overflow:hidden;margin:6px 0 4px}.bar i{display:block;height:100%;width:0;background:#7c5cff;transition:width .2s}
.err{color:#fca5a5}
</style></head><body><div id="c"></div><script>
const $=s=>document.querySelector(s), api=()=>window.pywebview.api;
const ico=`<div class="ic"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></svg></div>`;
const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
window.UP={state:null, show(st){ UP.state=st; const c=$('#c');
 if(st.mode==='offer') c.innerHTML=ico+`<h1>FileForge ${esc(st.latest)} est disponible</h1><p class="sub">Tu as la version ${esc(st.current)}.${st.required?' Cette mise à jour est importante.':''}</p>`
   +(st.notes.length?`<ul>${st.notes.map(n=>`<li>${esc(n)}</li>`).join('')}</ul>`:'')
   +`<div class="row"><button id="later">Plus tard</button><button id="go" class="pri">Mettre à jour</button></div>`;
 else if(st.mode==='progress') c.innerHTML=ico+`<h1>${esc(st.title)}</h1><p class="sub">${esc(st.text||'')}</p><div class="bar"><i id="bar"></i></div>`;
 else if(st.mode==='done') c.innerHTML=ico+`<h1>${esc(st.title)}</h1><p class="sub">${esc(st.text||'')}</p><div class="row"><button id="ok" class="pri">OK</button></div>`;
 else if(st.mode==='error') c.innerHTML=ico+`<h1>Mise à jour impossible</h1><p class="sub err">${esc(st.text)}</p><div class="row"><button id="ok">Fermer</button></div>`;
 const b=k=>$(k); b('#later')&&(b('#later').onclick=()=>api().later()); b('#go')&&(b('#go').onclick=()=>api().go()); b('#ok')&&(b('#ok').onclick=()=>api().close());
 if(st.mode==='progress'&&st.p!=null) $('#bar').style.width=(st.p*100)+'%'; return true },
 progress(p){ const e=$('#bar'); if(e) e.style.width=(p*100)+'%'; return true }};
document.addEventListener('keydown',e=>{ if(e.key==='Escape'&&UP.state&&UP.state.mode!=='progress') api().close() });
window.addEventListener('pywebviewready',()=>api().ready());
</script></body></html>"""


class Api:
    def __init__(self, info, manual):
        self._info, self._manual, self._win, self._busy = info, manual, None, False
        self._first = {"mode": "offer", **{k: info[k] for k in ("current", "latest", "notes", "required")}}

    def _show(self, st):
        try:
            self._win.evaluate_js("UP.show(%s)" % json.dumps(st, ensure_ascii=False))
        except Exception:
            pass

    def ready(self):
        self._show(self._first)
        if self._info.get("required") and not self._manual:
            threading.Thread(target=self.go, daemon=True).start()
        choice = os.environ.get("FF_UPDATE_CHOICE")       # tests
        if choice:
            threading.Timer(1.5, getattr(self, "go" if choice == "install" else "later")).start()

    def later(self):
        st = load_state(); st["snoozed"] = {"version": self._info["latest"], "at": time.time()}; save_state(st)
        log(f"{self._info['latest']} reportée")
        self.close()

    def close(self):
        if not self._busy:
            self._win.destroy()

    def go(self):
        if self._busy:
            return
        self._busy = True
        info = self._info
        try:
            self._show({"mode": "progress", "title": f"Téléchargement de FileForge {info['latest']}…", "p": 0})
            path = download(info, lambda p: self._win.evaluate_js(f"UP.progress({p:.3f})"))
            self._show({"mode": "progress", "title": "Installation…", "p": 1,
                        "text": "FileForge se met à jour en arrière-plan. Ça peut prendre une minute."})
            log(f"installation de {info['latest']} ({path.name})")
            code = install(path)
            if code != 0:
                raise RuntimeError(f"l'installation s'est arrêtée (code {code}). Détails dans le journal.")
            st = load_state(); st.pop("snoozed", None); st["installed"] = {"version": info["latest"], "at": time.time()}
            save_state(st)
            log(f"{info['latest']} installée")
            self._busy = False
            self._show({"mode": "done", "title": f"FileForge {info['latest']} est installé",
                        "text": "C'est prêt : les raccourcis et le clic droit utilisent déjà la nouvelle version."})
        except Exception as e:
            log(traceback.format_exc())
            self._busy = False
            self._show({"mode": "error", "text": str(e)})


def window(info, manual):
    import webview
    api = Api(info, manual)
    if not info["newer"]:
        api._first = {"mode": "done", "title": "FileForge est à jour", "text": f"Version {info['current']}, la plus récente."}
    win = webview.create_window("FileForge — Mise à jour", html=HTML, js_api=api, width=460, height=330,
                                resizable=False, on_top=True, background_color="#16171f")
    api._win = win
    webview.start(http_port=ff.safe_port())


def error_window(msg):
    import webview

    class A:
        def ready(self):
            w.evaluate_js("UP.show(%s)" % json.dumps({"mode": "error", "text": msg}, ensure_ascii=False))

        def close(self):
            w.destroy()
    w = webview.create_window("FileForge — Mise à jour", html=HTML, js_api=A(), width=460, height=260,
                              resizable=False, on_top=True, background_color="#16171f")
    webview.start(http_port=ff.safe_port())


def main():
    mode = (sys.argv[1:2] or ["--manual"])[0]
    st = load_state()
    if mode == "--auto":
        if time.time() - st.get("last_check", 0) < EVERY and not os.environ.get("FF_UPDATE_URL"):
            return 0
    try:
        info = check()
    except Exception as e:
        log(f"vérification impossible : {e}")
        if mode == "--check":
            print(json.dumps({"error": str(e)})); return 1
        if mode == "--manual":
            error_window(f"Impossible de joindre le site de FileForge ({e}). Vérifie ta connexion Internet.")
        return 1
    st["last_check"] = time.time(); st["latest_seen"] = info["latest"]; save_state(st)
    if mode == "--check":
        print(json.dumps(info)); return 0
    if mode == "--auto":
        if not info["newer"] or not info["file"]:
            return 0
        sn = st.get("snoozed") or {}
        if not info["required"] and sn.get("version") == info["latest"] and time.time() - sn.get("at", 0) < SNOOZE:
            return 0
        log(f"{info['latest']} disponible (installée : {info['current']})")
    window(info, manual=(mode == "--manual"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log(traceback.format_exc())
