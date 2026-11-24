"""Utilitaires du moteur : pages, temps, noms de sortie, registre des actions."""
import time
from pathlib import Path

import pytest

from conftest import ff, load

SRC = Path(ff.__file__).parent


# ── plages de pages
@pytest.mark.parametrize("s,n,exp", [
    ("", 5, [0, 1, 2, 3, 4]), ("tout", 3, [0, 1, 2]), ("*", 2, [0, 1]),
    ("1-3, 5", 6, [0, 1, 2, 4]), ("3-1", 4, [2, 1, 0]), ("2-fin", 4, [1, 2, 3]), ("fin", 4, [3]),
    ("-2", 4, [0, 1]), ("3-", 4, [2, 3]), ("1,,2", 3, [0, 1]), (" 1 - 2 ", 3, [0, 1]), ("END", 2, [1]),
])
def test_parse_ranges_ok(s, n, exp):
    assert ff.parse_ranges(s, n) == exp


@pytest.mark.parametrize("s", ["0", "6", "2-9", "abc", "1-x"])
def test_parse_ranges_errors(s):
    with pytest.raises(ValueError):
        ff.parse_ranges(s, 5)


def test_parse_ranges_huge_typo_is_fast():
    """Une faute de frappe (1-100000000) ne doit ni figer ni manger la mémoire."""
    t = time.time()
    with pytest.raises(ValueError):
        ff.parse_ranges("1-100000000", 10)
    assert time.time() - t < 0.5


def test_parse_ranges_error_message_is_french():
    with pytest.raises(ValueError) as e:
        ff.parse_ranges("abc", 5)
    assert "invalid literal" not in str(e.value)


def test_ask_pages_reasks_until_valid(ui):
    ui.set("Pages", ["99", "abc", "2"])
    assert ff.ask_pages("Pages ?", "1", 3) == [1]
    assert any("⚠" in p for p in ui.prompts)


def test_ask_int(ui):
    ui.set("Nombre", ["x", "0", "4"])
    assert ff.ask_int("Nombre ?", "2") == 4


# ── temps
@pytest.mark.parametrize("s,exp", [("83", 83), ("1:23", 83), ("0:01:23", 83), ("1,5", 1.5), ("", None), ("  ", None)])
def test_parse_time(s, exp):
    assert ff.parse_time(s) == exp


@pytest.mark.parametrize("s", ["abc", "1:xx", "-5"])
def test_parse_time_rejects_garbage_with_clear_message(s):
    with pytest.raises(ValueError) as e:
        ff.parse_time(s)
    assert "could not convert" not in str(e.value)


# ── noms de sortie
def test_unique_and_out(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_text("x")
    o = ff.out(f, "tag")
    assert o.name == "a_tag.pdf"
    o.write_text("y")
    assert ff.out(f, "tag").name == "a_tag (2).pdf"
    assert ff.out(f, "tag", "docx").name == "a_tag.docx"
    d = ff.outdir(f, "images")
    assert d.is_dir() and d.name == "a_images"
    assert ff.outdir(f, "images").name == "a_images (2)"


def test_ext():
    assert ff.ext("x.TAR.GZ") == "tar"
    assert ff.ext("Photo.JPG") == "jpg"
    assert ff.ext("sans") == ""


def test_natural_sort():
    assert sorted(["p10.pdf", "p2.pdf", "p1.pdf"], key=ff.natural) == ["p1.pdf", "p2.pdf", "p10.pdf"]


def test_human():
    assert ff.human(0) == "0 o"
    assert ff.human(1536) == "1.5 Ko"
    assert ff.human(5 * 1024 ** 3) == "5.0 Go"


def test_size_note(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"0" * 1000)
    b.write_bytes(b"0" * 400)
    ff.size_note(a, b)
    assert "−60 %" in ff.NOTES[-1]
    ff.size_note(b, a)
    assert "pas de gain" in ff.NOTES[-1]


def test_safe_port_is_free_and_ephemeral():
    import socket
    p = ff.safe_port()
    assert 49152 <= p <= 65535
    with socket.socket() as s:
        s.bind(("127.0.0.1", p))


def test_ffmpeg_available():
    assert ff.FFMPEG


def test_ff_failure_leaves_no_partial_output(tmp_path):
    """Un ffmpeg qui échoue ne doit pas laisser de fichier cassé à côté de l'original."""
    dst = tmp_path / "sortie.mp4"
    with pytest.raises(RuntimeError):
        ff.ff("-f", "lavfi", "-i", "sine=frequency=1:duration=1", "-c:a", "codec_qui_nexiste_pas", dst)
    assert not dst.exists()


# ── registre des actions
def test_every_action_has_unique_name_and_wheel_meta():
    wheel_src = (SRC / "wheel.py").read_text(encoding="utf-8")
    names = [a["fn"].__name__ for a in ff.ACTIONS]
    assert len(names) == len(set(names))
    for n in names:
        assert f'"{n}"' in wheel_src, f"{n} n'a pas d'entrée META dans wheel.py (catégorie / icône)"


def test_available_filters_by_type(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_text("x")
    png = tmp_path / "b.png"
    png.write_text("x")
    names = {a["fn"].__name__ for a in ff.available([str(pdf)])}
    assert "pdf_merge" not in names                 # il en faut 2
    assert "pdf_compress" in names and "img_resize" not in names
    both = {a["fn"].__name__ for a in ff.available([str(pdf), str(png)])}
    assert "pdf_merge" in both and "pdf_compress" not in both
    d = tmp_path / "dossier"
    d.mkdir()
    assert {a["fn"].__name__ for a in ff.available([str(d)])} >= {"make_zip"}
    assert "pdf_compress" not in {a["fn"].__name__ for a in ff.available([str(d)])}


def test_read_any_text_encodings(tmp_path):
    a = tmp_path / "u.txt"
    a.write_bytes("﻿été".encode("utf-8"))
    assert ff.read_any_text(a) == "été"
    b = tmp_path / "w.txt"
    b.write_bytes("Café €".encode("cp1252"))
    assert ff.read_any_text(b) == "Café €"


def test_version_format():
    import re
    assert re.fullmatch(r"\d+\.\d+\.\d+", ff.__version__)


def test_tessdata_prefix_set_once():
    src = (SRC / "fileforge.py").read_text(encoding="utf-8")
    assert src.count('os.environ.setdefault("TESSDATA_PREFIX"') == 1


def test_modules_import_cleanly():
    for m in ("search", "updater"):
        load(m, f"ff_test_{m}")


def test_pyflakes_clean():
    """Aucune variable inutilisée, import manquant ou nom indéfini dans src/ et tools/."""
    pyflakes = pytest.importorskip("pyflakes.api")
    from pyflakes import reporter as R
    import io
    out = io.StringIO()
    rep = R.Reporter(out, out)
    files = [str(p) for p in (SRC.glob("*.py"))] + [str(p) for p in (SRC.parent / "tools").glob("*.py")]
    n = sum(pyflakes.checkPath(f, rep) for f in files)
    assert n == 0, out.getvalue()
