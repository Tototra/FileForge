#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileForge — recherche de fichiers par nom, en local.

Un index des fichiers du dossier personnel est gardé en cache (une ligne par fichier) et
rafraîchi en arrière-plan à chaque ouverture : la recherche est instantanée et reste à jour.

Plus tolérante que la recherche du Finder / de l'Explorateur :
- majuscules, accents, tirets, points et soulignés ignorés (« facture edf » trouve Facture_EDF.pdf) ;
- mots dans n'importe quel ordre, un mot peut viser le dossier (« impots 2024 avis ») ;
- fautes de frappe tolérées quand rien ne correspond exactement (« factrue ») ;
- type par extension ou par famille : « pdf », « photo », « video », « tableur »… ;
- les fichiers récents passent devant.

    python search.py --build          reconstruit l'index
    python search.py facture edf      cherche (test en ligne de commande)
"""
import os, sys, re, time, json, unicodedata, threading, subprocess
from pathlib import Path

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
HOME = Path.home()

if IS_WIN:
    CACHE = Path(os.environ.get("LOCALAPPDATA", str(HOME))) / "FileForge" / "cache-recherche"
elif IS_MAC:
    CACHE = HOME / "Library" / "Caches" / "FileForge"
else:
    CACHE = Path(os.environ.get("XDG_CACHE_HOME") or HOME / ".cache") / "fileforge"
INDEX = CACHE / "index-fichiers.tsv"
MAX_AGE = 15             # index plus vieux : nouveau scan en arrière-plan à l'ouverture (fichiers tout juste créés)
MAX_ENTRIES = 1_500_000

# dossiers sans intérêt pour une recherche par nom (code, caches, environnements…)
SKIP_NAMES = {
    "node_modules", ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", ".tox", ".mypy_cache",
    ".pytest_cache", ".cache", ".npm", ".yarn", ".pnpm-store", ".cargo", ".rustup", ".gradle", ".m2",
    ".Trash", "$RECYCLE.BIN", "site-packages", "dist-packages", "DerivedData", ".idea", ".vscode",
    "Pods", "build", ".next", ".nuxt", "target", ".terraform", "AppData", "Application Data",
    "Library", ".local", ".config", "Links", "Searches", "Favorites", "Contacts", "IntelGraphicsProfiles", "miniconda3", "anaconda3", ".conda", ".docker",
}
CODE_MARKERS = {".git", "package.json", "pyproject.toml", "Cargo.toml", "go.mod", "pom.xml", "build.gradle",
                "requirements.txt", ".venv", "venv", "Makefile", "CMakeLists.txt", "composer.json", "Gemfile"}
KEEP_WHOLE = (".app", ".photoslibrary", ".musiclibrary", ".fcpbundle", ".logicx", ".key", ".pages", ".numbers")
SKIP_BUNDLES = (".bundle", ".framework", ".xcodeproj", ".xcworkspace", ".lproj", ".xcassets", ".dSYM", ".plugin")
# sous-dossiers de Library utiles sur Mac (iCloud Drive)
EXTRA_ROOTS = [HOME / "Library" / "Mobile Documents" / "com~apple~CloudDocs"] if IS_MAC else []
# fichiers techniques jamais cherchés
SKIP_FILES = re.compile(r"^(\.DS_Store|desktop\.ini|Thumbs\.db|\.localized|Icon\r|ntuser\..*|NTUSER\..*)$|\.(pyc|o|tmp|crdownload|part)$", re.I)

FAMILIES = {
    "pdf": {"pdf"},
    "photo": {"jpg", "jpeg", "png", "heic", "heif", "webp", "gif", "tif", "tiff", "bmp", "raw", "cr2", "nef", "dng", "avif"},
    "image": {"jpg", "jpeg", "png", "heic", "heif", "webp", "gif", "tif", "tiff", "bmp", "svg", "avif"},
    "video": {"mp4", "mov", "m4v", "mkv", "avi", "webm", "wmv"},
    "audio": {"mp3", "m4a", "wav", "flac", "aac", "ogg", "aiff", "opus"},
    "musique": {"mp3", "m4a", "wav", "flac", "aac", "ogg", "aiff", "opus"},
    "word": {"doc", "docx", "odt", "rtf", "pages"},
    "texte": {"txt", "md", "rtf", "doc", "docx", "odt", "pages"},
    "document": {"pdf", "doc", "docx", "odt", "rtf", "pages", "txt", "md"},
    "excel": {"xls", "xlsx", "csv", "ods", "numbers"},
    "tableur": {"xls", "xlsx", "csv", "ods", "numbers"},
    "powerpoint": {"ppt", "pptx", "odp", "key"},
    "presentation": {"ppt", "pptx", "odp", "key"},
    "diapo": {"ppt", "pptx", "odp", "key"},
    "archive": {"zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz"},
    "zip": {"zip", "rar", "7z", "tar", "gz", "tgz"},
    "dossier": {"/"},
}
FAMILIES["photos"], FAMILIES["images"], FAMILIES["videos"] = FAMILIES["photo"], FAMILIES["image"], FAMILIES["video"]
FAMILIES["pdfs"], FAMILIES["dossiers"], FAMILIES["documents"] = FAMILIES["pdf"], FAMILIES["dossier"], FAMILIES["document"]


NOT_RECENT = (".lnk", ".url", ".search-ms", ".ini", ".log", ".lock", ".tsv", ".json", ".plist", ".db", ".sqlite")
DOC_EXTS = set().union(*(FAMILIES[k] for k in ("document", "image", "video", "audio", "excel", "powerpoint", "archive"))) - {"/"}


def norm(s):
    """minuscules, sans accents, séparateurs → espace"""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[\s_\-\.\,\(\)\[\]\+]+", " ", s).strip()


# ───────────────────────── index ─────────────────────────

def roots():
    rs = [HOME] + [r for r in EXTRA_ROOTS if r.is_dir()]
    if IS_WIN:
        od = os.environ.get("OneDrive")
        if od and Path(od).is_dir() and not str(Path(od)).startswith(str(HOME)):
            rs.append(Path(od))
    return rs


def scan():
    """Parcourt les racines ; renvoie [(mtime, type, chemin)].
    type : 0 fichier, 1 dossier, 2 fichier de code, 3 dossier de code (dans un dépôt git)."""
    out = []
    stack = [(str(r), 0) for r in roots()]
    seen = set()
    while stack and len(out) < MAX_ENTRIES:
        d, code = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        if not code and any(e.name in CODE_MARKERS for e in entries):
            code = 2
        for e in entries:
            n = e.name
            try:
                if e.is_dir(follow_symlinks=False):
                    if IS_WIN and (e.is_junction() if hasattr(e, "is_junction") else False):
                        continue                         # « Mes documents », « Application Data »… : boucles
                    if n.endswith(KEEP_WHOLE):           # applications, photothèques : un seul résultat
                        out.append((e.stat(follow_symlinks=False).st_mtime, 1 + code, e.path))
                        continue
                    if n in SKIP_NAMES or n.startswith(".") or n.endswith(SKIP_BUNDLES):
                        continue
                    p = e.path
                    if p in seen:
                        continue
                    seen.add(p)
                    out.append((e.stat(follow_symlinks=False).st_mtime, 1 + code, p))
                    stack.append((p, code))
                elif e.is_file(follow_symlinks=False):
                    if n.startswith(".") or SKIP_FILES.search(n):
                        continue
                    out.append((e.stat(follow_symlinks=False).st_mtime, code, e.path))
            except OSError:
                continue
    return out


def build_index():
    t = time.time()
    rows = scan()
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = INDEX.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        for m, isdir, p in rows:
            if "\n" in p or "\t" in p:
                continue
            fh.write(f"{int(m)}\t{isdir}\t{p}\n")
    os.replace(tmp, INDEX)
    return len(rows), time.time() - t


def index_age():
    try:
        return time.time() - INDEX.stat().st_mtime
    except OSError:
        return None


def refreshing():
    """Un scan est-il en cours, ou vient-il de finir sans que l'index en mémoire soit rechargé ?"""
    try:
        if time.time() - (CACHE / "scan.lock").stat().st_mtime < 120:
            return True
    except OSError:
        pass
    try:
        return INDEXED.stamp is not None and INDEX.stat().st_mtime != INDEXED.stamp
    except OSError:
        return False


def refresh_in_background():
    """Lance un scan dans un processus séparé (n'alourdit pas la roue)."""
    lock = CACHE / "scan.lock"
    try:
        if lock.exists() and time.time() - lock.stat().st_mtime < 120:
            return False
        CACHE.mkdir(parents=True, exist_ok=True)
        lock.write_text(str(os.getpid()))
    except OSError:
        return False
    kw = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if IS_WIN:
        kw["creationflags"] = 0x08000000 | 0x00004000  # pas de console, priorité basse
    else:
        kw["start_new_session"] = True
    exe = sys.executable
    if IS_WIN and exe.lower().endswith("python.exe") and Path(exe[:-10] + "pythonw.exe").exists():
        exe = exe[:-10] + "pythonw.exe"
    cmd = [exe, str(Path(__file__).resolve()), "--build"]
    if not IS_WIN:
        cmd = ["nice", "-n", "15"] + cmd
    subprocess.Popen(cmd, **kw)
    return True


class Index:
    """Index chargé en mémoire ; se recharge tout seul quand le fichier sur disque change."""

    def __init__(self):
        self.lock = threading.Lock()
        self.stamp = None
        self.paths, self.names, self.dirs, self.mtimes, self.isdir, self.code = [], [], [], [], [], []
        self.building = False
        self._load_lock = threading.Lock()

    def ensure(self):
        age = index_age()
        if age is None:
            # premier lancement : index construit ici, en tâche de fond du processus
            if not self.building:
                self.building = True
                def run():
                    try:
                        build_index()
                    finally:
                        self.building = False
                threading.Thread(target=run, daemon=True).start()
            return
        if age > MAX_AGE:
            refresh_in_background()
        self.load()

    def load(self):
        with self._load_lock:
            self._load()

    def _load(self):
        try:
            st = INDEX.stat().st_mtime
        except OSError:
            return
        if st == self.stamp:
            return
        paths, names, dirs, mtimes, isdir, code = [], [], [], [], [], []
        home = str(HOME)
        with open(INDEX, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m, d, p = line.rstrip("\n").split("\t", 2)
                paths.append(p)
                mtimes.append(int(m))
                isdir.append(d in ("1", "3"))
                code.append(d in ("2", "3"))
                i = p.rfind(os.sep)
                names.append(norm(p[i + 1:]))
                parent = p[:i]
                if parent.startswith(home):
                    parent = parent[len(home):]
                dirs.append(norm(parent))
        with self.lock:
            self.paths, self.names, self.dirs, self.mtimes, self.isdir, self.code = paths, names, dirs, mtimes, isdir, code
            self.stamp = st

    def count(self):
        return len(self.paths)


INDEXED = Index()


# ───────────────────────── recherche ─────────────────────────

def parse_query(q):
    words = norm(q).split()
    exts, terms = set(), []
    for w in words:
        if w in FAMILIES and len(words) > 1:
            exts |= FAMILIES[w]
        elif w.startswith("*") or (len(words) > 1 and w in {"jpg", "png", "heic", "mov", "mp4", "mp3", "docx", "xlsx", "pptx", "csv", "txt", "md", "zip", "key", "pages"}):
            exts.add(w.lstrip("*"))
        else:
            terms.append(w)
    return terms, exts


def _ext(name_norm):
    i = name_norm.rfind(" ")
    return name_norm[i + 1:] if i >= 0 else ""


def search(q, limit=40):
    """Renvoie (résultats, info). Chaque résultat : chemin, nom, dossier, date, taille, type."""
    ix = INDEXED
    ix.ensure()
    terms, exts = parse_query(q)
    with ix.lock:
        names, dirs, paths, mtimes, isdir, code = ix.names, ix.dirs, ix.paths, ix.mtimes, ix.isdir, ix.code
    now = time.time()
    if not terms and not exts:
        # pas de texte : fichiers récemment modifiés
        idx = sorted((i for i in range(len(paths)) if not isdir[i] and not code[i] and not paths[i].lower().endswith(NOT_RECENT)),
                     key=lambda i: -mtimes[i])[:limit]
        return [describe(paths[i], mtimes[i], isdir[i], []) for i in idx], {"mode": "recents", "total": len(paths),
                                                                            "refreshing": refreshing()}

    def type_ok(i):
        if not exts:
            return True
        if isdir[i]:
            return "/" in exts
        return _ext(names[i]) in exts

    t0 = time.time()
    hits = match(names, dirs, terms, type_ok)
    if not hits and exts:
        # « fileforge pdf » sans PDF correspondant : « pdf » redevient un simple mot
        terms, exts = norm(q).split(), set()
        hits = match(names, dirs, terms, type_ok)

    def score(i):
        n, s = names[i], 0.0
        words = n.split()
        for t in terms:
            if t in n:
                s += 10
                if any(w.startswith(t) for w in words):
                    s += 6
                if t in words:
                    s += 4
            else:
                s += 3  # trouvé seulement dans le dossier
        if terms and n.startswith(terms[0]):
            s += 5
        age_days = max(0.0, (now - mtimes[i]) / 86400)
        s += 8 / (1 + age_days / 30)          # récent : bonus
        s -= min(len(n), 80) / 40             # noms courts devant
        s -= dirs[i].count(" ") * 0.05        # moins profond devant
        if isdir[i]:
            s -= 1
        if code[i]:
            s -= 9                            # fichiers de projets de code : derrière
        elif not isdir[i] and _ext(n) in DOC_EXTS:
            s += 3                            # vrais documents : devant
        return s

    fuzzy = False
    if len(hits) < 3 and terms and len("".join(terms)) >= 4:
        # rien (ou presque) : tolérance aux fautes de frappe
        fuzzy = True
        extra = fuzzy_hits(" ".join(terms), names, limit * 2, exclude=set(hits))
        hits += [i for i in extra if type_ok(i)]
        top = hits[:limit]
    else:
        top = sorted(hits, key=score, reverse=True)[:limit]
    res = [describe(paths[i], mtimes[i], isdir[i], terms) for i in top]
    return res, {"mode": "flou" if fuzzy else "exact", "total": len(hits), "ms": int((time.time() - t0) * 1000),
                 "indexed": len(paths), "refreshing": refreshing()}


def match(names, dirs, terms, type_ok):
    hits = []
    t0 = terms[0] if terms else ""
    for i, n in enumerate(names):
        if t0 and t0 not in n and t0 not in dirs[i]:
            continue
        if not all(t in n or t in dirs[i] for t in terms) or not type_ok(i):
            continue
        hits.append(i)
        if len(hits) > 20000:
            break
    return hits


def fuzzy_hits(q, names, limit, exclude=()):
    try:
        from rapidfuzz import fuzz, process
    except ImportError:
        import difflib
        sm = difflib.SequenceMatcher(autojunk=False)
        sm.set_seq2(q)
        scored = []
        for i, n in enumerate(names):
            if i in exclude:
                continue
            sm.set_seq1(n)
            if sm.real_quick_ratio() >= 0.6 and sm.quick_ratio() >= 0.6:
                r = sm.ratio()
                if r >= 0.6:
                    scored.append((r, i))
        return [i for _, i in sorted(scored, reverse=True)[:limit]]
    m = max(3, len(q) - 1)
    cand = {i: n for i, n in enumerate(names) if len(n) >= m and i not in exclude}
    out = process.extract(q, cand, scorer=fuzz.partial_ratio, limit=limit * 4, score_cutoff=80)
    # départage : ressemblance du nom entier, puis du mot le plus proche
    def key(x):
        n = x[0]
        best = max((fuzz.ratio(q, w) for w in n.split()), default=0)
        return (x[1], best, fuzz.ratio(q, n))
    out.sort(key=key, reverse=True)
    return [k for _, _, k in out][:limit]


def describe(p, mtime, isdir, terms):
    path = Path(p)
    parent = str(path.parent)
    home = str(HOME)
    short = "~" + parent[len(home):] if parent.startswith(home) else parent
    short = short.replace("~/Library/Mobile Documents/com~apple~CloudDocs", "iCloud Drive")
    size = None
    if not isdir:
        try:
            size = path.stat().st_size
        except OSError:
            return {"path": p, "name": path.name, "dir": short, "mtime": mtime, "size": None, "kind": "gone",
                    "hl": highlight(path.name, terms)}
    e = path.suffix.lower().lstrip(".")
    kind = "folder" if isdir else next((k for k in ("pdf", "image", "video", "audio", "word", "excel", "powerpoint", "archive")
                                        if e in FAMILIES[k]), "file")
    if isdir and path.suffix.lower() == ".app":
        kind = "app"
    return {"path": p, "name": path.name, "dir": short, "mtime": mtime, "size": size, "kind": kind,
            "hl": highlight(path.name, terms)}


def highlight(name, terms):
    """Plages [début, fin] du nom qui correspondent aux mots cherchés (pour les surligner)."""
    if not terms:
        return []
    # correspondance caractère par caractère entre le nom et sa version normalisée
    flat, idx = [], []
    for i, c in enumerate(name):
        d = unicodedata.normalize("NFKD", c.lower())
        d = "".join(x for x in d if not unicodedata.combining(x))
        if re.fullmatch(r"[\s_\-\.\,\(\)\[\]\+]", c):
            d = " "
        for x in d:
            flat.append(x)
            idx.append(i)
    s = "".join(flat)
    spans = []
    for t in terms:
        for m in re.finditer(re.escape(t).replace(r"\ ", " +"), s):
            spans.append([idx[m.start()], idx[m.end() - 1] + 1])
    spans.sort()
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


if __name__ == "__main__":
    if sys.argv[1:2] == ["--build"]:
        try:
            n, dt = build_index()
            print(f"{n} éléments indexés en {dt:.1f} s → {INDEX}")
        finally:
            try:
                (CACHE / "scan.lock").unlink()
            except OSError:
                pass
    else:
        if index_age() is None:
            print("construction de l'index…", build_index())
        q = " ".join(sys.argv[1:])
        res, info = search(q, 15)
        print(json.dumps(info, ensure_ascii=False))
        for r in res:
            print(f"  {r['name']:50s} {r['dir']}")
