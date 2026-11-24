"""Documents : Markdown / texte / HTML → PDF, Office (LibreOffice), Word → MD/HTML/TXT, LaTeX."""
from pathlib import Path

import pymupdf
import pytest

from conftest import ff, act, pdf_text


@pytest.mark.parametrize("src,needle", [("notes.md", "paragraphe"), ("lisez.txt", "accentuée é"),
                                        ("ansi.txt", "Café crème à 2 €"), ("page.html", "Bonjour")])
def test_text_to_pdf(ui, get, src, needle):
    out, = act("doc_to_pdf")([get(src)])
    t = pdf_text(out)
    assert needle in t


def test_txt_is_not_interpreted_as_html(ui, get):
    out, = act("doc_to_pdf")([get("lisez.txt")])
    assert "<b>pas du html</b>" in pdf_text(out)


def test_md_euro_and_oe_rendered(ui, get):
    out, = act("doc_to_pdf")([get("notes.md")])
    assert "€ œ" in pdf_text(out)


def test_md_table_and_code(ui, get):
    out, = act("doc_to_pdf")([get("notes.md")])
    t = pdf_text(out)
    assert "def f(x):" in t and "point 1" in t


def test_md_long_document_multiple_pages(ui, get, tmp_path):
    f = tmp_path / "long.md"
    f.write_text("\n\n".join(f"Paragraphe {i} " + "texte " * 40 for i in range(200)), encoding="utf-8")
    out, = act("doc_to_pdf")([str(f)])
    d = pymupdf.open(out)
    assert d.page_count > 5 and "Paragraphe 199" in d[-1].get_text()


def test_md_html_export(ui, get):
    out, = act("md_html")([get("notes.md")])
    h = Path(out).read_text(encoding="utf-8")
    assert "<table>" in h and "<title>notes</title>" in h and "paragraphe" in h


def test_md_html_title_escaped(ui, tmp_path):
    f = tmp_path / "a<b>.md"
    f.write_text("x", encoding="utf-8")
    out, = act("md_html")([str(f)])
    assert "<title>a&lt;b&gt;</title>" in Path(out).read_text(encoding="utf-8")


@pytest.mark.parametrize("fmt,needle", [("Markdown", "Rapport été"), ("HTML", "<h1>Rapport été</h1>"), ("Texte", "accents")])
def test_docx_convert(ui, get, fmt, needle):
    ui.set("Convertir en", fmt)
    out, = act("docx_convert")([get("rapport.docx")])
    assert needle in Path(out).read_text(encoding="utf-8")


def test_docx_to_pdf(ui, get):
    out, = act("doc_to_pdf")([get("rapport.docx")])
    assert "Rapport été" in pdf_text(out)


@pytest.mark.slow
@pytest.mark.parametrize("src,needle", [("slides.pptx", "Séance 1"), ("multi.xlsx", "Café")])
def test_office_to_pdf_libreoffice(ui, get, src, needle):
    if not ff.soffice():
        pytest.skip("LibreOffice absent")
    out, = act("doc_to_pdf")([get(src)])
    assert needle in pdf_text(out)


@pytest.mark.slow
@pytest.mark.parametrize("src,tgt", [("rapport.docx", "ODT"), ("rapport.docx", "TXT"), ("slides.pptx", "ODP"),
                                     ("multi.xlsx", "ODS"), ("multi.xlsx", "CSV")])
def test_office_convert(ui, get, src, tgt):
    if not ff.soffice():
        pytest.skip("LibreOffice absent")
    ui.set("Convertir en", tgt)
    out, = act("office_convert")([get(src)])
    assert Path(out).suffix == "." + tgt.lower() and Path(out).stat().st_size > 0
    if tgt == "TXT":
        assert "Rapport été" in Path(out).read_text(encoding="utf-8-sig")


@pytest.mark.slow
def test_lo_convert_failure_is_fast(ui, tmp_path):
    """Un fichier que LibreOffice refuse ne doit pas faire attendre 20 secondes de plus."""
    import time
    if not ff.soffice():
        pytest.skip("LibreOffice absent")
    f = tmp_path / "abime.docx"
    f.write_bytes(b"PK\x03\x04 pas vraiment un docx")
    t = time.time()
    ok = ff.lo_convert(f, "pdf", tmp_path / "x.pdf")
    assert not ok and time.time() - t < 15


# ── LaTeX
def tex_engine():
    return any(ff.which(x) for x in ("latexmk", "xelatex", "pdflatex", "tectonic"))


needs_tex = pytest.mark.skipif(not tex_engine(), reason="aucun moteur LaTeX")


@pytest.mark.slow
@needs_tex
def test_tex_simple(ui, get):
    d = get("tex_simple")
    out, = act("tex_to_pdf")([str(Path(d) / "doc.tex")])
    assert "Bonjour" in pdf_text(out)


@pytest.mark.slow
@needs_tex
def test_tex_subfolders_input_and_figures(ui, get):
    d = Path(get("tex_sub"))
    out, = act("tex_to_pdf")([str(d / "main.tex")])
    doc = pymupdf.open(out)
    assert "Introduction depuis un sous-dossier" in doc[0].get_text()
    assert doc[0].get_images()


@pytest.mark.slow
@needs_tex
def test_tex_template_in_parent_folder(ui, get):
    d = Path(get("tex_tpl"))
    out, = act("tex_to_pdf")([str(d / "rapport" / "r.tex")])
    assert "STYLE-PARENT" in pdf_text(out)


@pytest.mark.slow
@needs_tex
def test_tex_error_is_reported_even_with_old_pdf(ui, get):
    d = Path(get("tex_err"))
    old = d / "bad.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "ANCIENNE VERSION")
    doc.save(old)
    with pytest.raises(RuntimeError) as e:
        act("tex_to_pdf")([str(d / "bad.tex")])
    assert "échoué" in str(e.value)
    assert sorted(p.name for p in d.glob("*.pdf")) == ["bad.pdf"]


@pytest.mark.slow
@needs_tex
def test_tex_does_not_run_latexmkrc_nor_copy_unrelated_files(ui, get, monkeypatch):
    d = Path(get("tex_rc"))
    copied = []
    import shutil
    real = shutil.copy2

    def spy(a, b, *k, **kw):
        copied.append(Path(a).name)
        return real(a, b, *k, **kw)
    monkeypatch.setattr(shutil, "copy2", spy)
    act("tex_to_pdf")([str(d / "doc.tex")])
    assert "latexmkrc" not in copied and "film.mp4" not in copied
    assert not list(d.rglob("PWNED_BY_LATEXMKRC"))


def test_tex_latexmk_gets_norc(ui, get, monkeypatch, tmp_path):
    """Avec latexmk, l'option -norc empêche d'exécuter un fichier latexmkrc posé à côté du .tex."""
    import subprocess
    d = Path(get("tex_rc"))
    calls = []
    monkeypatch.setattr(ff, "which", lambda n, *e: "/fake/latexmk" if n == "latexmk" else None)

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        if cmd[0] == "latexmk":
            outdir = next(c.split("=", 1)[1] for c in cmd if c.startswith("-output-directory="))
            out = Path(outdir) / "doc.pdf"
            doc = pymupdf.open()
            doc.new_page()
            doc.save(out)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    act("tex_to_pdf")([str(d / "doc.tex")])
    assert "-norc" in calls[0]


def test_tex_no_engine_explains(ui, get, monkeypatch):
    monkeypatch.setattr(ff, "which", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="moteur LaTeX"):
        act("tex_to_pdf")([str(Path(get("tex_simple")) / "doc.tex")])


@pytest.mark.slow
@needs_tex
def test_tex_listing_source_and_big_sibling_folder(ui, get, tmp_path):
    """Régression : \\lstinputlisting{code.py} doit trouver code.py ; un gros dossier voisin ne bloque pas."""
    d = tmp_path / "work" / "projet"
    (d / "videos").mkdir(parents=True)
    (d / "code.py").write_text("print('LISTING-OK')\n")
    (d / "videos" / "gros.pdf").write_bytes(b"%PDF" + b"0" * (45 * 1024 * 1024))
    (d / "doc.tex").write_text("\\documentclass{article}\\usepackage{listings}\\begin{document}"
                               "\\lstinputlisting{code.py}\\end{document}\n")
    out, = act("tex_to_pdf")([str(d / "doc.tex")])
    assert "LISTING" in pdf_text(out)
