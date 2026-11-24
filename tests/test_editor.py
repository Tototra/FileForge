"""Éditeur PDF : modification de texte (police d'origine conservée), ajouts, annotations, pages, annuler."""
import base64
from pathlib import Path

import pymupdf
import pytest

from conftest import load, ff

ed = load("editor", "ff_editor")


def open_ed(path):
    e = ed.Editor(path)
    e.render(0, 1)
    return e


def line_id(e, needle, page=0):
    e.render(page, 1)
    return next(l["id"] for l in e.lines[page] if needle in l["text"])


def spans(path, needle, page=0):
    d = pymupdf.open(str(path))
    out = []
    for b in d[page].get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for s in ln["spans"]:
                if needle in s["text"]:
                    out.append(s)
    return out


def base_font(name):
    """« ABCDEF+Georgia-Regular » et « Georgia » désignent la même police."""
    import re
    return re.sub(r"[-_ ,]|regular|mt$", "", name.split("+", 1)[-1].lower())


@pytest.mark.parametrize("src", ["font_full.pdf", "font_subset.pdf"])
def test_text_edit_keeps_original_font(get, src):
    """Bug signalé : modifier une ligne remplaçait la police d'origine par Helvetica / Arial."""
    f = get(src)
    orig = spans(f, "Texte original")[0]
    e = open_ed(f)
    e.do({"type": "text_edit", "page": 0, "line": line_id(e, "Texte original"), "text": "Texte modifié dans la même police"})
    out = e.save()
    new = spans(out, "Texte modifié")
    assert new, "le texte modifié est introuvable"
    assert base_font(new[0]["font"]) == base_font(orig["font"]), f"police {new[0]['font']} au lieu de {orig['font']}"
    assert abs(new[0]["size"] - orig["size"]) < 0.1
    assert new[0]["color"] == orig["color"]
    assert "Texte original" not in pymupdf.open(out)[0].get_text()


def test_text_edit_new_glyph_not_in_subset_still_close(get):
    """Caractères absents du sous-ensemble intégré : on retrouve la même famille sur le système, sinon proche."""
    f = get("font_subset.pdf")
    orig = spans(f, "Texte original")[0]
    e = open_ed(f)
    e.do({"type": "text_edit", "page": 0, "line": line_id(e, "Texte original"), "text": "QXZ wkyj 12345 €"})
    out = e.save()
    new = spans(out, "QXZ")
    assert new
    fam_name = base_font(orig["font"]).split("-")[0].replace(" ", "").lower()
    assert fam_name in new[0]["font"].replace(" ", "").lower(), f"{new[0]['font']} ≠ famille {fam_name}"
    assert "€" in pymupdf.open(out)[0].get_text()


def test_text_edit_standard_font_and_style(get):
    f = get("doc.pdf")
    e = open_ed(f)
    e.do({"type": "text_edit", "page": 0, "line": line_id(e, "Page 1"), "text": "Ligne remplacée été"})
    out = e.save()
    t = pymupdf.open(out)[0].get_text()
    assert "Ligne remplacée été" in t and "Page 1" not in t
    assert base_font(spans(out, "remplacée")[0]["font"]).lower().startswith("helvetica")


def test_text_edit_unicode_chars(get):
    f = get("doc.pdf")
    e = open_ed(f)
    e.do({"type": "text_edit", "page": 0, "line": line_id(e, "Page 1"), "text": "Prix : 5 € — œuvre ✓"})
    t = pymupdf.open(e.save())[0].get_text()
    assert "5 €" in t and "œuvre" in t


def test_text_edit_copy_paste_spaces_are_normal(get):
    f = get("doc.pdf")
    e = open_ed(f)
    e.do({"type": "text_edit", "page": 0, "line": line_id(e, "Page 1"), "text": "a b € c"})
    t = pymupdf.open(e.save())[0].get_text()
    assert "a b € c" in t and "\xa0" not in t


def test_text_edit_delete_line(get):
    f = get("doc.pdf")
    e = open_ed(f)
    e.do({"type": "text_edit", "page": 0, "line": line_id(e, "Page 1"), "text": ""})
    assert "Page 1" not in pymupdf.open(e.save())[0].get_text()


def test_text_edit_on_rotated_page(get):
    f = get("rotated.pdf")
    e = open_ed(f)
    e.do({"type": "text_edit", "page": 0, "line": line_id(e, "SECRET"), "text": "PUBLIC word here"})
    out = e.save()
    pg = pymupdf.open(out)[0]
    t = pg.get_text()
    assert "PUBLIC word here" in t and "SECRET" not in t
    ln = [l for b in pg.get_text("dict")["blocks"] for l in b.get("lines", []) if "PUBLIC" in "".join(s["text"] for s in l["spans"])][0]
    assert tuple(round(x) for x in ln["dir"]) == (0, -1) or tuple(round(x) for x in ln["dir"]) == (1, 0)


def test_text_add_multiline(get):
    e = open_ed(get("doc.pdf"))
    e.do({"type": "text_add", "page": 1, "x": 100, "y": 700, "text": "Ligne A\nLigne B", "size": 12, "color": "#ff0000"})
    t = pymupdf.open(e.save())[1].get_text()
    assert "Ligne A" in t and "Ligne B" in t


def test_text_add_on_rotated_page_reads_upright(get):
    e = open_ed(get("rotated.pdf"))
    e.do({"type": "text_add", "page": 0, "x": 100, "y": 100, "text": "Ajout droit", "size": 14, "color": "#000000"})
    pg = pymupdf.open(e.save())[0]
    r = pg.search_for("Ajout droit")[0] * pg.rotation_matrix
    r.normalize()
    assert r.width > r.height, "le texte ajouté apparaît de travers"
    assert abs(r.x0 - 100) < 5


@pytest.mark.parametrize("kind", ["highlight", "underline", "strike"])
def test_markup(get, kind):
    e = open_ed(get("doc.pdf"))
    e.do({"type": kind, "page": 0, "rect": [60, 80, 500, 110], "color": "#ffcc00"})
    annots = list(pymupdf.open(e.save())[0].annots())
    assert len(annots) == 1


def test_ink_rect_image(get):
    e = open_ed(get("doc.pdf"))
    e.do({"type": "ink", "page": 0, "points": [[10, 10], [50, 60], [90, 20]], "color": "#0000ff", "width": 3})
    e.do({"type": "rect", "page": 0, "rect": [100, 100, 200, 160], "color": "#00ff00"})
    logo = Path(get("logo.png")).read_bytes()
    e.do({"type": "image", "page": 0, "rect": [300, 300, 400, 375], "data": base64.b64encode(logo).decode()})
    pg = pymupdf.open(e.save())[0]
    assert len(list(pg.annots())) == 2 and len(pg.get_images()) == 2


def test_whiteout_removes_text(get):
    e = open_ed(get("doc.pdf"))
    e.do({"type": "whiteout", "page": 0, "rect": [60, 80, 560, 110]})
    assert "Page 1" not in pymupdf.open(e.save())[0].get_text()


def test_rotate_and_delete_page(get):
    e = open_ed(get("doc.pdf"))
    e.do({"type": "rotate", "page": 0, "angle": 90})
    e.do({"type": "delete_page", "page": 3})
    d = pymupdf.open(e.save())
    assert d.page_count == 3 and d[0].rotation == 90


def test_undo_replays(get):
    f = get("font_full.pdf")
    e = open_ed(f)
    e.do({"type": "text_edit", "page": 0, "line": line_id(e, "Texte original"), "text": "Un"})
    e.do({"type": "whiteout", "page": 0, "rect": [60, 140, 560, 170]})
    assert e.undo() is True
    out = e.save()
    t = pymupdf.open(out)[0].get_text()
    assert "Un" in t and "Deuxième ligne" in t
    assert base_font(spans(out, "Un")[0]["font"]) == base_font(spans(f, "Texte original")[0]["font"])
    assert e.undo() is False
    assert "Texte original" in pymupdf.open(e.save())[0].get_text()


def test_unknown_op_rejected(get):
    e = open_ed(get("doc.pdf"))
    with pytest.raises(ValueError):
        e.do({"type": "rm -rf", "page": 0})


def test_save_never_overwrites(get):
    f = get("doc.pdf")
    before = Path(f).read_bytes()
    e = open_ed(f)
    e.do({"type": "rotate", "page": 0})
    a = e.save()
    b = e.save()
    assert a != b and Path(f).read_bytes() == before
    assert Path(a).name == "doc_modifié.pdf" and Path(b).name == "doc_modifié (2).pdf"


def test_encrypted_unlock_and_save_still_protected(get):
    f = get("locked.pdf")
    e = ed.Editor(f)
    assert e.info()["needs_pass"]
    assert not e.unlock("faux")
    assert e.unlock("s3cret")
    e.render(0, 1)
    e.do({"type": "text_edit", "page": 0, "line": line_id(e, "Page 1"), "text": "Modifié"})
    out = e.save()
    d = pymupdf.open(out)
    assert d.needs_pass and d.authenticate("s3cret")
    assert "Modifié" in d[0].get_text()


def test_api_errors_are_returned_not_raised(get):
    api = ed.Api(get("doc.pdf"))
    r = api.do({"type": "inconnu", "page": 0})
    assert "error" in r
    assert api.render(99, 1).get("error")


def test_editor_html_escapes_errors():
    """Les messages d'erreur (qui peuvent contenir un nom de fichier) sont échappés avant affichage."""
    html = (Path(ff.__file__).parent / "editor.html").read_text(encoding="utf-8")
    import re
    for m in re.finditer(r"toast\(([^;]*?r\.error[^;]*?)\)", html):
        assert "esc(" in m.group(1), f"erreur non échappée : {m.group(0)}"


def test_inserted_accents_extract_correctly_with_range_tounicode(get):
    """Régression : la correction de l'espace décalait toute une plage (é → i, ç → g) dans le texte copié."""
    font = ed.system_font("Caladea-Regular") or ed.system_font("Georgia")
    if not font:
        pytest.skip("police de test absente")
    e = open_ed(get("doc.pdf"))
    new = "Une phrase réécrite : € œ ç à ê ô"
    e._insert_text(e.doc[0], (72, 300), new, 14, "#000000", font=font.stem)
    out = e.save()
    assert new in pymupdf.open(out)[0].get_text()


def test_real_office_pdf_subset_font_kept(get, tmp_path):
    """PDF exporté par un traitement de texte (polices en sous-ensemble) : la ligne modifiée reste dans sa police."""
    if not ff.soffice():
        pytest.skip("LibreOffice absent")
    src = get("rapport.docx")
    pdf = tmp_path / "rapport.pdf"
    assert ff.lo_convert(src, "pdf", pdf)
    e = open_ed(str(pdf))
    orig = spans(pdf, "accents")[0]
    new = "Une phrase réécrite : € œ ç à ê ô"
    e.do({"type": "text_edit", "page": 0, "line": line_id(e, "accents"), "text": new})
    out = e.save()
    assert new in pymupdf.open(out)[0].get_text()
    assert base_font(spans(out, "phrase")[0]["font"]) == base_font(orig["font"])


def test_subset_font_mixed_with_fallback_when_family_missing(get, tmp_path, monkeypatch):
    """Famille absente de l'ordinateur : les lettres présentes dans la police intégrée y restent, les autres
    passent dans une police de secours, et le texte reste juste au copier-coller."""
    if not ff.soffice():
        pytest.skip("LibreOffice absent")
    pdf = tmp_path / "rapport.pdf"
    assert ff.lo_convert(get("rapport.docx"), "pdf", pdf)
    monkeypatch.setattr(ed, "system_font", lambda *a, **k: None)
    e = open_ed(str(pdf))
    orig = base_font(spans(pdf, "accents")[0]["font"])
    new = "Une phrase réécrite : € œ ç à ê ô"
    e.do({"type": "text_edit", "page": 0, "line": line_id(e, "accents"), "text": new})
    out = e.save()
    pg = pymupdf.open(out)[0]
    assert new in pg.get_text().replace("\n", "")
    fonts = {base_font(s["font"]) for b in pg.get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"]
             if any(ch in s["text"] for ch in "phrase")}
    assert orig in fonts, fonts


def test_font_resource_names_unique_per_file(tmp_path):
    a, b = tmp_path / "Times New Roman.ttf", tmp_path / "Times New Roman Bold.ttf"
    assert ed.font_res_name(a) != ed.font_res_name(b)


def test_pdf_point_with_offset_mediabox_and_rotation():
    d = pymupdf.open()
    d.new_page()
    d.xref_set_key(d[0].xref, "MediaBox", "[100 200 712 992]")
    p = d[0]
    pt = pymupdf.Point(200, 300)
    ref = pt * ~p.transformation_matrix
    for rot in (90, 180, 270):
        p.set_rotation(rot)
        assert ed.pdf_point(p, pt) == ref


def test_codes_cache_is_per_page(get, tmp_path):
    """Même police, nom de ressource différent sur deux pages : chaque page garde le sien."""
    if not ff.soffice():
        pytest.skip("LibreOffice absent")
    import docx
    doc = docx.Document()
    doc.add_paragraph("Première page")
    doc.add_page_break()
    doc.add_paragraph("Seconde page")
    src = tmp_path / "deux.docx"
    doc.save(src)
    pdf = tmp_path / "deux.pdf"
    assert ff.lo_convert(src, "pdf", pdf)
    e = ed.Editor(str(pdf))
    d = e.doc
    for pg in d:
        for f in pg.get_fonts(full=True):
            enc = e._codes(pg, f[0])
            if enc:
                assert enc["res"] == f[4]
