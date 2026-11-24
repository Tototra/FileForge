"""Toutes les actions PDF, avec vérification du contenu produit (pas seulement « un fichier existe »)."""
import os
import tempfile
from pathlib import Path

import pymupdf
import pytest

from conftest import ff, act, pdf_text


def pages(p, pw=None):
    d = pymupdf.open(str(p))
    if pw:
        d.authenticate(pw)
    return d


def test_merge_pdf_and_images(ui, get):
    a, b, img = get("doc.pdf", "one.pdf", "photo.jpg")
    out, = act("pdf_merge")([a, b, img])
    d = pages(out)
    assert d.page_count == 4 + 1 + 1
    assert "seule" in d[4].get_text()
    assert d[5].get_images()


def test_merge_encrypted_asks_password(ui, get):
    a, b = get("doc.pdf", "locked.pdf")
    ui.set("Mot de passe", "s3cret")
    out, = act("pdf_merge")([a, b])
    assert pages(out).page_count == 8


def test_merge_wrong_password(ui, get):
    a, b = get("doc.pdf", "locked.pdf")
    ui.set("Mot de passe", "faux")
    with pytest.raises(RuntimeError, match="incorrect"):
        act("pdf_merge")([a, b])


@pytest.mark.parametrize("mode,answers,expect", [
    ("Une page", {}, 4),
    ("Toutes les N", {"Nombre de pages": "3"}, 2),
    ("Selon des plages", {"Plages": "1-2; 3-fin"}, 2),
])
def test_split(ui, get, mode, answers, expect):
    f = get("doc.pdf")
    ui.set("Comment diviser", mode)
    for k, v in answers.items():
        ui.set(k, v)
    d, = act("pdf_split")([f])
    parts = sorted(Path(d).glob("*.pdf"))
    assert len(parts) == expect
    assert sum(pages(p).page_count for p in parts) == 4


def test_split_ranges_bad_then_good(ui, get):
    f = get("doc.pdf")
    ui.set("Comment diviser", "Selon des plages").set("Plages", ["1-99", "1; 2-4"])
    d, = act("pdf_split")([f])
    assert len(list(Path(d).glob("*.pdf"))) == 2


def test_extract_pages(ui, get):
    f = get("doc.pdf")
    ui.set("Pages à extraire", "2, 4")
    out, = act("pdf_extract")([f])
    d = pages(out)
    assert d.page_count == 2
    assert "Page 2" in d[0].get_text() and "Page 4" in d[1].get_text()


def test_extract_single_page_refused(ui, get):
    with pytest.raises(ValueError):
        act("pdf_extract")([get("one.pdf")])


def test_delete_pages(ui, get):
    f = get("doc.pdf")
    ui.set("SUPPRIMER", "1, 3")
    out, = act("pdf_delete")([f])
    d = pages(out)
    assert [p.get_text()[:6] for p in d] == ["Page 2", "Page 4"]


def test_delete_all_pages_reasks(ui, get):
    f = get("doc.pdf")
    ui.set("SUPPRIMER", ["1-4", "4"])
    out, = act("pdf_delete")([f])
    assert pages(out).page_count == 3


def test_reorder_reverse_and_custom(ui, get):
    f = get("doc.pdf")
    out, = act("pdf_reorder")([f])
    assert "Page 4" in pages(out)[0].get_text()
    ui.set("Réorganiser", "personnalisé").set("Nouvel ordre", "3,1,1")
    out, = act("pdf_reorder")([f])
    d = pages(out)
    assert d.page_count == 3 and "Page 3" in d[0].get_text() and "Page 1" in d[2].get_text()


def test_rotate(ui, get):
    f = get("doc.pdf")
    ui.set("Rotation", "gauche").set("Pages à pivoter", "2")
    out, = act("pdf_rotate")([f])
    d = pages(out)
    assert [p.rotation for p in d] == [0, 270, 0, 0]


def test_compress_never_corrupts(ui, get):
    f = get("doc.pdf")
    for lvl in ("Légère", "Recommandée", "Forte"):
        ui.set("Niveau", lvl)
        out, = act("pdf_compress")([f])
        assert pages(out).page_count == 4
        assert "Bonjour le monde" in pdf_text(out)


def test_crop_margins_and_auto(ui, get):
    f = get("doc.pdf")
    ui.set("Comment rogner", "Retirer des marges").set("Marges", "10")
    out, = act("pdf_crop")([f])
    r = pages(out)[0].rect
    assert abs(r.width - (595 - 2 * 72 / 25.4 * 10)) < 1
    ui.set("Comment rogner", "automatiquement")
    out, = act("pdf_crop")([f])
    r = pages(out)[0].rect
    assert r.width < 595 and r.height < 842


def test_crop_margins_bad_input_clear_error(ui, get):
    ui.set("Comment rogner", "Retirer des marges").set("Marges", "dix")
    with pytest.raises(ValueError) as e:
        act("pdf_crop")([get("doc.pdf")])
    assert "could not convert" not in str(e.value)


def test_crop_visual_on_rotated_page(ui, get):
    """Le rognage visuel sur une page pivotée garde bien la zone dessinée (coordonnées affichées)."""
    f = get("rotated.pdf")
    src = pages(f)[0]
    shown = src.search_for("SECRET")[0] * src.rotation_matrix      # où l'utilisateur voit le mot
    shown.normalize()
    ui.set("Comment rogner", "Visuellement")
    ui.regions = {0: [tuple(shown + (-20, -20, 20, 20))]}
    out, = act("pdf_crop")([f])
    pg = pages(out)[0]
    assert "SECRET" in pg.get_text() and "public footer" not in pg.get_text()


def test_to_images(ui, get, tmp_path):
    f = get("doc.pdf")
    ui.set("Format des images", "PNG").set("Résolution", "100")
    d, = act("pdf_to_images")([f])
    imgs = sorted(Path(d).glob("*.png"))
    assert len(imgs) == 4
    from PIL import Image
    w, h = Image.open(imgs[0]).size
    assert abs(w - 595 * 100 / 72) <= 2 and abs(h - 842 * 100 / 72) <= 2


def test_to_word(ui, get):
    import docx
    out, = act("pdf_to_word")([get("doc.pdf")])
    text = "\n".join(p.text for p in docx.Document(out).paragraphs)
    assert "Bonjour le monde" in text


def test_to_word_encrypted(ui, get):
    import docx
    ui.set("Mot de passe", "s3cret")
    out, = act("pdf_to_word")([get("locked.pdf")])
    assert "Bonjour" in "\n".join(p.text for p in docx.Document(out).paragraphs)


def test_to_word_failure_leaves_nothing(ui, get, monkeypatch):
    import pdf2docx
    f = get("doc.pdf")

    def boom(self, dst, *a, **k):
        Path(dst).write_bytes(b"partiel")
        raise RuntimeError("conversion impossible")
    monkeypatch.setattr(pdf2docx.Converter, "convert", boom)
    with pytest.raises(RuntimeError):
        act("pdf_to_word")([f])
    assert not list(Path(f).parent.glob("*.docx"))


def test_to_pptx_keeps_aspect_ratio(ui, get):
    from pptx import Presentation
    out, = act("pdf_to_pptx")([get("mixed.pdf")])
    prs = Presentation(out)
    assert len(prs.slides) == 2
    pic = prs.slides[1].shapes[0]
    assert abs(pic.width / pic.height - 842 / 595) < 0.02, "la page paysage est déformée"


def test_to_excel_tables(ui, get):
    import openpyxl
    out, = act("pdf_to_excel")([get("table.pdf")])
    wb = openpyxl.load_workbook(out)
    vals = [[c.value for c in r] for r in wb.worksheets[0].iter_rows()]
    assert ["Nom", "Âge", "Ville"] in vals and ["Bob", "25", "Lyon"] in vals


def test_to_excel_no_table_exports_text(ui, get):
    import openpyxl
    out, = act("pdf_to_excel")([get("one.pdf")])
    assert openpyxl.load_workbook(out).sheetnames == ["Texte"]


@pytest.mark.parametrize("fmt,e", [("Markdown", "md"), ("Texte brut", "txt")])
def test_to_text(ui, get, fmt, e):
    ui.set("Format", fmt)
    out, = act("pdf_to_text")([get("doc.pdf")])
    assert Path(out).suffix == "." + e
    assert "Bonjour le monde" in Path(out).read_text(encoding="utf-8")


@pytest.mark.slow
def test_to_text_scanned_uses_ocr(ui, get):
    ui.set("Format", "Texte brut")
    out, = act("pdf_to_text")([get("scan.pdf")])
    t = Path(out).read_text(encoding="utf-8")
    assert "Bonjour" in t and "4521" in t


def test_extract_images(ui, get):
    d, = act("pdf_extract_images")([get("doc.pdf")])
    assert len(list(Path(d).iterdir())) == 1          # la même image sur 4 pages = 1 fichier


def test_protect_and_unlock_roundtrip(ui, get):
    f = get("doc.pdf")
    ui.set("Mot de passe à définir", "mot de passe").set("Confirme", "mot de passe")
    out, = act("pdf_protect")([f])
    d = pymupdf.open(out)
    assert d.needs_pass and not d.authenticate("faux") and d.authenticate("mot de passe")
    ui.set("Mot de passe :", "mot de passe")
    un, = act("pdf_unlock")([str(out)])
    d = pymupdf.open(un)
    assert not d.needs_pass and not d.is_encrypted
    assert "Bonjour" in d[0].get_text()


def test_protect_mismatch_and_empty(ui, get):
    ui.set("Mot de passe à définir", "a").set("Confirme", "b")
    with pytest.raises(ValueError):
        act("pdf_protect")([get("doc.pdf")])
    ui.set("Mot de passe à définir", "")
    with pytest.raises(ValueError):
        act("pdf_protect")([get("doc.pdf")])


def test_unlock_not_protected_notes(ui, get):
    act("pdf_unlock")([get("doc.pdf")])
    assert any("pas protégé" in n for n in ff.NOTES)


def test_watermark(ui, get):
    ui.set("Texte du filigrane", "CONFIDENTIEL")
    out, = act("pdf_watermark")([get("doc.pdf")])
    assert pdf_text(out).count("CONFIDENTIEL") == 4


def test_watermark_empty_text_refused(ui, get):
    ui.set("Texte du filigrane", "")
    with pytest.raises((ValueError, ff.Cancel)):
        act("pdf_watermark")([get("doc.pdf")])


def test_watermark_on_rotated_page_is_centered(ui, get):
    ui.set("Texte du filigrane", "FILIGRANE")
    out, = act("pdf_watermark")([get("rotated.pdf")])
    pg = pages(out)[0]
    r = [pymupdf.Rect(w[:4]) for w in pg.get_text("words") if "FILIGRANE" in w[4]]
    assert r
    c = (r[0] * pg.rotation_matrix)
    c.normalize()
    mid = pymupdf.Point((c.x0 + c.x1) / 2, (c.y0 + c.y1) / 2)
    assert abs(mid.x - pg.rect.width / 2) < pg.rect.width * 0.2
    assert abs(mid.y - pg.rect.height / 2) < pg.rect.height * 0.2


def test_numbers(ui, get):
    ui.set("Format", "Page 1 / N").set("Commencer", "2")
    out, = act("pdf_numbers")([get("doc.pdf")])
    d = pages(out)
    assert "Page 1 / 3" not in d[0].get_text()
    assert "Page 1 / 3" in d[1].get_text() and "Page 3 / 3" in d[3].get_text()


def test_numbers_on_rotated_page_at_bottom(ui, get):
    """Sur une page pivotée, le numéro est en bas de la page TELLE QU'ON LA VOIT."""
    ui.set("Format", "1").set("Position", "Bas centre")
    out, = act("pdf_numbers")([get("rotated.pdf")])
    pg = pages(out)[0]
    hits = [r for r in pg.search_for("1") if (r * pg.rotation_matrix).y0 > pg.rect.height * 0.85]
    assert hits, "numéro absent du bas de la page affichée"


def test_sign_places_image_where_drawn(ui, get):
    f = get("doc.pdf")
    ui.set("Signature", "Choisir une image")
    ui.regions = {3: [(100, 600, 300, 700)]}
    out, = act("pdf_sign")([f])
    d = pages(out)
    infos = d[3].get_image_info()
    assert len(infos) == 2                       # l'image d'origine + la signature
    bb = pymupdf.Rect(infos[-1]["bbox"])
    assert pymupdf.Rect(100, 600, 300, 700).contains(bb)
    assert ui.region_calls[0]["start_page"] == 3


def test_sign_on_rotated_page_lands_in_drawn_box(ui, get):
    f = get("rotated.pdf")
    ui.set("Signature", "Choisir une image")
    box = pymupdf.Rect(500, 300, 700, 450)        # coordonnées affichées (page paysage 842×595)
    ui.regions = {0: [tuple(box)]}
    out, = act("pdf_sign")([f])
    pg = pages(out)[0]
    bb = pymupdf.Rect(pg.get_image_info()[-1]["bbox"]) * pg.rotation_matrix
    bb.normalize()
    assert box.contains(pymupdf.Point((bb.x0 + bb.x1) / 2, (bb.y0 + bb.y1) / 2)), f"signature en {bb}, dessinée en {box}"


def test_sign_heic_temp_file_removed(ui, get, monkeypatch):
    f, heic = get("doc.pdf", "photo.heic")
    before = set(Path(tempfile.gettempdir()).glob("tmp*/sig.png"))
    ui.set("Signature", "Choisir une image")
    monkeypatch.setattr(ui, "choose_file", lambda *a, **k: heic)
    act("pdf_sign")([f])
    after = set(Path(tempfile.gettempdir()).glob("tmp*/sig.png"))
    assert after <= before, "la signature convertie reste dans le dossier temporaire"


# ── caviardage
def test_redact_words_removes_text_and_metadata(ui, get):
    f = get("doc.pdf")
    ui.set("Caviarder", "Rechercher").set("Mots", "confidentielle; Dupont")
    out, = act("pdf_redact")([f])
    d = pages(out)
    allt = pdf_text(out)
    assert "confidentielle" not in allt
    md = " ".join(str(v) for v in d.metadata.values())
    assert "Dupont" not in md and "confidentielle" not in md, "le mot reste dans les métadonnées"
    assert "Dupont" not in str(d.get_toc()), "le mot reste dans les signets"
    assert "Bonjour le monde" in allt


def test_redact_zero_hits_is_an_error(ui, get):
    f = get("doc.pdf")
    ui.set("Caviarder", "Rechercher").set("Mots", "introuvable")
    with pytest.raises(ValueError):
        act("pdf_redact")([f])
    assert not list(Path(f).parent.glob("*caviardé*"))


def test_redact_drawn_zone_removes_text(ui, get):
    f = get("doc.pdf")
    ui.set("Caviarder", "Dessiner")
    ui.regions = {0: [(60, 80, 560, 110)]}
    out, = act("pdf_redact")([f])
    assert "Page 1" not in pages(out)[0].get_text()
    assert "Page 2" in pages(out)[1].get_text()


def test_redact_drawn_zone_on_rotated_page(ui, get):
    """La zone est dessinée sur la page affichée (pivotée) : le texte dessous doit disparaître."""
    f = get("rotated.pdf")
    src = pages(f)[0]
    shown = src.search_for("SECRET")[0] * src.rotation_matrix
    shown.normalize()
    ui.set("Caviarder", "Dessiner")
    ui.regions = {0: [tuple(shown + (-5, -5, 5, 5))]}
    out, = act("pdf_redact")([f])
    t = pages(out)[0].get_text()
    assert "SECRET" not in t
    assert "public footer" in t


def test_redact_form_field_value_removed(ui, get):
    f = get("form.pdf")
    ui.set("Caviarder", "Rechercher").set("Mots", "Alice")
    try:
        out, = act("pdf_redact")([f])
    except ValueError:
        return                      # 0 occurrence visible : refus clair, rien n'est publié
    raw = Path(out).read_bytes()
    d = pages(out)
    assert all("Alice" not in (w.field_value or "") for p in d for w in p.widgets())
    assert b"Alice" not in raw


# ── OCR et divers
@pytest.mark.slow
def test_ocr_makes_text_searchable(ui, get):
    out, = act("pdf_ocr")([get("scan.pdf")])
    assert pages(out)[0].search_for("Bonjour")


def test_flatten_bakes_annotations_and_fields(ui, get):
    out, = act("pdf_flatten")([get("form.pdf")])
    pg = pages(out)[0]
    assert not list(pg.widgets()) and not list(pg.annots())
    assert "Rempli par Alice" in pg.get_text()


def test_gray(ui, get):
    out, = act("pdf_gray")([get("doc.pdf")])
    d = pages(out)
    assert d.page_count == 4
    pix = d[0].get_pixmap(dpi=30)
    samples = pix.samples
    n = pix.n
    assert all(abs(samples[i] - samples[i + 1]) < 3 for i in range(0, len(samples) - 2, n * 7)), "pas en gris"


def test_meta_strip(ui, get):
    ui.set("Métadonnées", "Supprimer")
    out, = act("pdf_meta")([get("doc.pdf")])
    md = pages(out).metadata
    assert not md.get("title") and not md.get("author")


def test_meta_edit(ui, get):
    ui.set("Métadonnées", "Modifier").set("Titre", "Nouveau").set("Auteur", "Zoé").set("Sujet", "s")
    out, = act("pdf_meta")([get("doc.pdf")])
    md = pages(out).metadata
    assert md["title"] == "Nouveau" and md["author"] == "Zoé"


def test_repair_broken(ui, get):
    out, = act("pdf_repair")([get("broken.pdf")])
    assert pages(out).page_count >= 1


def test_fake_pdf_clear_error(ui, get):
    with pytest.raises(RuntimeError, match="lisible"):
        act("pdf_compress")([get("fake.pdf")])


def test_info(ui, get):
    assert act("pdf_info")([get("doc.pdf")]) == []
    assert any("Pages : 4" in p for p in ui.prompts)


def test_password_with_spaces_is_kept(ui, get):
    """Le mot de passe saisi est utilisé tel quel (espaces compris) : vérifié dans test_wheel pour la saisie."""
    ui.set("Mot de passe", " pw ")
    out, = act("pdf_unlock")([get("spacepw.pdf")])
    assert not pymupdf.open(out).needs_pass


def test_original_never_modified(ui, get):
    f = get("doc.pdf")
    before = Path(f).read_bytes()
    ui.set("Mots", "Bonjour").set("Caviarder", "Rechercher")
    for name in ("pdf_compress", "pdf_rotate", "pdf_redact", "pdf_flatten", "pdf_watermark", "pdf_numbers", "pdf_repair"):
        act(name)([f])
    assert Path(f).read_bytes() == before


def test_pick_regions_temp_copy_removed(get, monkeypatch):
    """La copie déchiffrée passée à la fenêtre de sélection ne doit pas rester dans le dossier temporaire."""
    from conftest import load
    wheel = pytest.importorskip("webview") and load("wheel", "ff_wheel_regions")
    seen = {}

    def fake_tk_call(payload):
        seen["path"] = payload["path"]
        assert Path(payload["path"]).exists()
        return {"0": [[1, 2, 3, 4]]}
    monkeypatch.setattr(wheel, "tk_call", fake_tk_call)
    d = pymupdf.open(get("locked.pdf"))
    d.authenticate("s3cret")
    r = wheel.pick_regions(d, "pdf", "t", "h")
    assert r == {0: [(1, 2, 3, 4)]}
    assert not Path(seen["path"]).exists(), "copie en clair laissée dans le dossier temporaire"
    assert not Path(seen["path"]).parent.exists()


@pytest.mark.slow
def test_redact_keeps_ocr_text_layer(ui, get):
    """Régression : caviarder un scan passé à l'OCR effaçait toute sa couche de texte (texte « caché »)."""
    ocr, = act("pdf_ocr")([get("scan.pdf")])
    ui.set("Caviarder", "Rechercher").set("Mots", "Bonjour")
    out, = act("pdf_redact")([str(ocr)])
    t = pymupdf.open(out)[0].get_text()
    assert "Bonjour" not in t and "4521" in t


@pytest.mark.parametrize("raw,expect", [("10,5,10,5", [10, 5, 10, 5]), ("10; 5; 10; 5", [10, 5, 10, 5]),
                                        ("10, 5, 10, 5", [10, 5, 10, 5]), ("2,5", [2.5] * 4)])
def test_crop_margin_formats(ui, get, raw, expect):
    f = get("doc.pdf")
    ui.set("Comment rogner", "Retirer des marges").set("Marges", raw)
    out, = act("pdf_crop")([f])
    r = pages(out)[0].rect
    mm = 72 / 25.4
    t, rr, b, l = expect
    assert abs(r.width - (595 - (rr + l) * mm)) < 0.6 and abs(r.height - (842 - (t + b) * mm)) < 0.6
