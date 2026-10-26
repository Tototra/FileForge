"""Mises à jour automatiques, de bout en bout, sur la vraie installation (CI Windows et Mac).

    python update_ci.py <dossier de résultats> <dossier des installateurs construits (site/downloads)>

Un faux site local annonce la version 9.9.9 avec les installateurs fraîchement construits :
  • « Plus tard » : rien n'est installé, et la même version n'est pas reproposée tout de suite ;
  • « Mettre à jour » : téléchargement, empreinte vérifiée, installation silencieuse par-dessus,
    l'agent des raccourcis redémarre, FileForge marche toujours ;
  • une empreinte fausse est refusée ; déjà à jour → rien ne s'affiche.
"""
import hashlib, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path
from PIL import ImageGrab

IS_WIN = sys.platform == "win32"
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
BUILT = Path(sys.argv[2]).resolve()
D = Path(os.environ["LOCALAPPDATA"]) / "FileForge" if IS_WIN else Path.home() / "Library/Application Support/FileForge"
PY = D / ("venv/Scripts/pythonw.exe" if IS_WIN else "venv/bin/python")
LOG = D / "FileForge.log" if IS_WIN else Path.home() / "Library/Logs/FileForge.log"
STATE = LOG.parent / "update.json"
fails = []


def expect(name, cond, info=""):
    print(("OK   " if cond else "FAIL ") + name, info, flush=True)
    if not cond:
        fails.append(name)


def shot(name):
    try:
        ImageGrab.grab(all_screens=True).save(OUT / f"maj-{name}.png")
    except Exception as e:
        print("capture impossible", e)


def site(version, bad_sha=False, required=False):
    d = Path(tempfile.mkdtemp(prefix="ff-site-"))
    m = json.loads((BUILT / "manifest.json").read_text(encoding="utf-8"))
    m["version"], m["required"] = version, required
    m["notes"] = ["Test : nouvelle version factice", "Accents : été, œuvre"]
    for f in m["files"].values():
        shutil.copy(BUILT / f["name"], d / f["name"])
        if bad_sha:
            f["sha256"] = "0" * 64
    (d / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    return d / "manifest.json"


def run(manifest, choice=None, wait=True, timeout=1500):
    env = dict(os.environ, FF_UPDATE_URL=str(manifest))
    env.pop("FF_UPDATE_CHOICE", None)
    if choice:
        env["FF_UPDATE_CHOICE"] = choice
    kw = {"creationflags": 0x00000200} if IS_WIN else {"start_new_session": True}
    p = subprocess.Popen([str(PY), str(D / "updater.py"), "--auto"], env=env, cwd=tempfile.gettempdir(), **kw)
    if not wait:
        return p
    try:
        p.wait(timeout)
    except subprocess.TimeoutExpired:
        p.kill()
    return p


def state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def agent_running():
    if IS_WIN:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*hotkey_win.py*' } | Measure-Object | % Count"],
                           capture_output=True, text=True)
        return r.stdout.strip() not in ("", "0")
    r = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    return "fr.fileforge.hotkey" in r.stdout


def tail_log(n=30):
    try:
        return "\n".join(LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError:
        return ""


STATE.unlink(missing_ok=True)
cur = subprocess.run([str(D / ("venv/Scripts/python.exe" if IS_WIN else "venv/bin/python")), str(D / "updater.py"), "--check"],
                     env=dict(os.environ, FF_UPDATE_URL=str(site("0.0.1"))), capture_output=True, text=True)
info = json.loads(cur.stdout or "{}")
expect("version installée lisible", bool(info.get("current")), cur.stdout[:200] + cur.stderr[-300:])
expect("déjà à jour → pas de nouvelle version", info.get("newer") is False)

# 1. déjà à jour : --auto ne montre rien et s'arrête tout seul
t = time.time(); p = run(site(info.get("current", "1.0.0")), timeout=60)
expect("à jour : rien ne s'affiche, arrêt immédiat", p.returncode is not None and time.time() - t < 30, f"{time.time() - t:.1f} s")

# 2. « Plus tard »
m = site("9.9.9")
p = run(m, choice="later", wait=False)
time.sleep(1.0); shot("1-proposition")
p.wait(120)
st = state()
expect("Plus tard : version reportée", (st.get("snoozed") or {}).get("version") == "9.9.9", json.dumps(st))
t = time.time(); p = run(m, timeout=60)
expect("Plus tard : pas reproposée tout de suite", time.time() - t < 30, f"{time.time() - t:.1f} s")

# 3. empreinte fausse : refusée, rien d'installé
before = (D / "fileforge.py").stat().st_mtime
p = run(site("9.9.9", bad_sha=True), choice="install", wait=False)
time.sleep(12); shot("2-empreinte-fausse")
p.kill() if p.poll() is None else None
expect("empreinte fausse : refusée", "ne correspond pas" in tail_log(15), tail_log(6))
expect("empreinte fausse : rien n'a été installé", (D / "fileforge.py").stat().st_mtime == before)

# 4. « Mettre à jour » : installation silencieuse complète
STATE.unlink(missing_ok=True)
t = time.time()
p = run(site("9.9.9"), choice="install", wait=False)
time.sleep(4); shot("3-telechargement")
seen_progress = False
while time.time() - t < 1500:
    lg = tail_log(40)
    if "installation de 9.9.9" in lg and not seen_progress:
        seen_progress = True; time.sleep(2); shot("4-installation")
    if "9.9.9 installée" in lg or "Traceback" in lg.split("installation de 9.9.9")[-1]:
        break
    time.sleep(2)
dt = time.time() - t
time.sleep(3); shot("5-termine")
st = state()
expect("mise à jour installée", (st.get("installed") or {}).get("version") == "9.9.9", f"{dt:.0f} s · {json.dumps(st)}\n{tail_log(12)}")
expect("installée en moins de 10 min", dt < 600, f"{dt:.0f} s")
time.sleep(8)
expect("agent des raccourcis relancé après la mise à jour", agent_running())
p.kill() if p.poll() is None else None
r = subprocess.run([str(D / ("venv/Scripts/python.exe" if IS_WIN else "venv/bin/python")), "-c",
                    "import sys; sys.path.insert(0, sys.argv[1]); import fileforge, pymupdf, webview; print(fileforge.__version__)", str(D)],
                   capture_output=True, text=True)
expect("FileForge fonctionne après la mise à jour", r.returncode == 0, r.stdout.strip() + r.stderr[-300:])
for f in ("updater.py", "editor.py", "wheel.py"):
    expect(f"après la mise à jour : {f} présent", (D / f).exists())
(OUT / "maj-journal.txt").write_text(tail_log(80), encoding="utf-8")
print(f"\n{len(fails)} échec(s) : {fails}")
sys.exit(1 if fails else 0)
