"""Actions image : formats, EXIF/GPS, transparence, GIF animés, rognage, filigrane."""
from pathlib import Path

import pytest
from PIL import Image, ExifTags

from conftest import ff, act

ALL = ["photo.jpg", "photo.png", "logo.png", "gray.png", "palette.png", "cmyk.jpg", "deep.png", "photo.webp",
       "photo.tiff", "photo.bmp", "photo.heic", "photo.avif", "oriented.jpg"]


def gps(path):
    ff._heif()
    return dict(Image.open(path).getexif().get_ifd(ExifTags.IFD.GPSInfo))


@pytest.mark.parametrize("src", ALL)
@pytest.mark.parametrize("fmt", ["JPG", "PNG", "WEBP", "TIFF", "GIF", "BMP", "ICO", "HEIC", "AVIF"])
def test_convert_every_format(ui, get, src, fmt):
    if fmt not in ff.writable_formats():
        pytest.skip(f"{fmt} non disponible")
    f = get(src)
    ui.set("Convertir en", fmt)
    outs = act("img_convert")([f])
    if ff.ext(f) == fmt.lower() or (ff.ext(f), fmt) in (("jpg", "JPG"), ("tiff", "TIFF")):
        assert not outs or Path(outs[0]).suffix.lower() == "." + fmt.lower()
        return
    out, = outs
    im = Image.open(out)
    im.load()
    assert im.size[0] > 0 and Path(out).suffix == "." + fmt.lower()


def test_convert_gif_to_gif_says_why(ui, get):
    ui.set("Convertir en", "GIF")
    outs = act("img_convert")([get("anim.gif")])
    assert outs or ff.NOTES, "aucune sortie et aucune explication"


def test_convert_keeps_animation(ui, get):
    ui.set("Convertir en", "WEBP")
    out, = act("img_convert")([get("anim.gif")])
    assert getattr(Image.open(out), "n_frames", 1) == 3


def test_exif_orientation_applied(ui, get):
    ui.set("Convertir en", "PNG")
    out, = act("img_convert")([get("oriented.jpg")])
    assert Image.open(out).size == (200, 400)


@pytest.mark.parametrize("answer,size", [("50%", (800, 600)), ("400", (400, 300)), ("100x100", (100, 75))])
def test_resize(ui, get, answer, size):
    ui.set("Nouvelle taille", answer)
    out, = act("img_resize")([get("photo.jpg")])
    assert Image.open(out).size == size


@pytest.mark.parametrize("answer", ["abc", "0", "-5%", "10x"])
def test_resize_bad_input_clear_error(ui, get, answer):
    ui.set("Nouvelle taille", answer)
    with pytest.raises(ValueError) as e:
        act("img_resize")([get("photo.jpg")])
    msg = str(e.value)
    assert "invalid literal" not in msg and "could not convert" not in msg and "division" not in msg


def test_resize_keeps_animation(ui, get):
    ui.set("Nouvelle taille", "50%")
    out, = act("img_resize")([get("anim.gif")])
    im = Image.open(out)
    assert im.size == (60, 45) and getattr(im, "n_frames", 1) == 3


def test_resize_keeps_transparency(ui, get):
    ui.set("Nouvelle taille", "50%")
    out, = act("img_resize")([get("logo.png")])
    im = Image.open(out)
    assert im.mode == "RGBA" and im.getpixel((0, 0))[3] == 0


@pytest.mark.parametrize("src", ["photo.jpg", "photo.png", "logo.png", "photo.tiff", "photo.bmp", "photo.webp", "anim.gif"])
@pytest.mark.parametrize("lvl", ["Légère", "Recommandée", "Forte"])
def test_compress(ui, get, src, lvl):
    ui.set("Niveau", lvl)
    out, = act("img_compress")([get(src)])
    Image.open(out).load()
    if src == "anim.gif":
        assert getattr(Image.open(out), "n_frames", 1) == 3


def test_compress_bmp_tiff_become_jpg(ui, get):
    out, = act("img_compress")([get("photo.bmp")])
    assert Path(out).suffix == ".jpg"


@pytest.mark.parametrize("ratio,expect", [("1:1", 1.0), ("16:9", 16 / 9), ("9:16", 9 / 16)])
def test_crop_ratio(ui, get, ratio, expect):
    ui.set("Comment rogner", "Format imposé").set("Format :", ratio)
    out, = act("img_crop")([get("photo.jpg")])
    w, h = Image.open(out).size
    assert abs(w / h - expect) < 0.01


def test_crop_auto_border(ui, get):
    ui.set("Comment rogner", "automatiquement")
    out, = act("img_crop")([get("border.png")])
    assert Image.open(out).size == (281, 221)


def test_crop_auto_transparent(ui, get):
    ui.set("Comment rogner", "automatiquement")
    out, = act("img_crop")([get("logo.png")])
    assert Image.open(out).size == (401, 301)


def test_crop_auto_nothing(ui, get):
    ui.set("Comment rogner", "automatiquement")
    assert act("img_crop")([get("gray.png")]) == []
    assert "aucun bord" in ff.NOTES[-1]


def test_crop_visual(ui, get):
    ui.set("Comment rogner", "Visuellement")
    ui.regions = {0: [(10.4, 20.6, 110.2, 70.7)]}
    out, = act("img_crop")([get("photo.jpg")])
    assert Image.open(out).size == (100, 50)


@pytest.mark.parametrize("m,size", [("droite", (1200, 1600)), ("gauche", (1200, 1600)), ("180", (1600, 1200)),
                                    ("Miroir horizontal", (1600, 1200))])
def test_rotate(ui, get, m, size):
    ui.set("Transformation", m)
    out, = act("img_rotate")([get("photo.jpg")])
    assert Image.open(out).size == size


def test_rotate_right_is_clockwise(ui, get):
    f = get("border.png")
    im = Image.new("RGB", (40, 20), "white")
    im.putpixel((0, 0), (255, 0, 0))
    im.save(f)
    ui.set("Transformation", "droite")
    out, = act("img_rotate")([f])
    r = Image.open(out).convert("RGB")
    assert r.size == (20, 40) and r.getpixel((19, 0)) == (255, 0, 0)


@pytest.mark.parametrize("src", ["photo.jpg", "photo.png", "photo.tiff", "photo.webp", "photo.heic"])
def test_strip_removes_gps_and_camera(ui, get, src):
    f = get(src)
    assert gps(f), "l'exemple doit contenir une position GPS"
    out, = act("img_strip")([f])
    ff._heif()
    ex = Image.open(out).getexif()
    assert not dict(ex.get_ifd(ExifTags.IFD.GPSInfo)), f"GPS encore présent dans {Path(out).name}"
    assert ex.get(0x010F) is None, "marque de l'appareil encore présente"
    raw = Path(out).read_bytes()
    assert b"TestCam" not in raw


def test_strip_keeps_orientation_visually(ui, get):
    out, = act("img_strip")([get("oriented.jpg")])
    assert Image.open(out).size == (200, 400)


def test_convert_keeps_exif_by_default(ui, get):
    ui.set("Convertir en", "PNG")
    out, = act("img_convert")([get("photo.jpg")])
    assert Image.open(out).getexif().get(0x010F) == "TestCam"


def test_to_pdf_one_and_many(ui, get):
    import pymupdf
    a, b = get("photo.jpg", "logo.png")
    out, = act("img_to_pdf")([a, b])
    assert pymupdf.open(out).page_count == 2
    ui.set("Regrouper", "Un PDF par image").set("Format des pages", "Taille de l'image")
    outs = act("img_to_pdf")([a, b])
    assert len(outs) == 2
    r = pymupdf.open(outs[0])[0].rect
    assert abs(r.width - 1600 * 0.75) < 1


def test_to_pdf_landscape_uses_landscape_a4(ui, get):
    import pymupdf
    out, = act("img_to_pdf")([get("photo.jpg")])
    r = pymupdf.open(out)[0].rect
    assert r.width > r.height


@pytest.mark.parametrize("pos", ["Bas droite", "Bas gauche", "Centre", "Mosaïque"])
def test_watermark(ui, get, pos):
    f = get("photo.jpg")
    ui.set("Texte du filigrane", "© Test").set("Position", pos)
    out, = act("img_watermark")([f])
    a, b = Image.open(f).convert("RGB"), Image.open(out).convert("RGB")
    assert a.size == b.size and a.tobytes() != b.tobytes()


def test_watermark_keeps_alpha(ui, get):
    ui.set("Texte du filigrane", "© Test")
    out, = act("img_watermark")([get("logo.png")])
    assert Image.open(out).mode == "RGBA"


def test_watermark_empty_refused(ui, get):
    ui.set("Texte du filigrane", "")
    with pytest.raises((ValueError, ff.Cancel)):
        act("img_watermark")([get("photo.jpg")])


def test_gif_from_images(ui, get):
    a, b, c = get("photo.jpg", "logo.png", "gray.png")
    ui.set("Durée", "250").set("Largeur", "200")
    out, = act("img_gif")([a, b, c])
    im = Image.open(out)
    assert im.n_frames == 3 and im.width == 200 and im.info["duration"] == 250


def test_original_untouched(ui, get):
    f = get("photo.jpg")
    before = Path(f).read_bytes()
    for name in ("img_resize", "img_compress", "img_rotate", "img_strip", "img_watermark"):
        act(name)([f])
    assert Path(f).read_bytes() == before


def test_mpo_jpeg_is_not_an_animation(ui, get, tmp_path):
    """Régression : les JPEG « MPO » des téléphones (2 images) sortaient de travers et sans EXIF."""
    f = tmp_path / "phone.jpg"
    ex = Image.Exif()
    ex[0x0112] = 6
    ex[0x010F] = "Phone"
    a, b = Image.new("RGB", (400, 200), "red"), Image.new("RGB", (400, 200), "blue")
    a.save(f, "MPO", save_all=True, append_images=[b], exif=ex)
    assert Image.open(f).format == "MPO" and Image.open(f).n_frames == 2
    ui.set("Nouvelle taille", "50%")
    out, = act("img_resize")([str(f)])
    im = Image.open(out)
    assert im.size == (100, 200), "photo de travers"
    assert im.getexif().get(0x010F) == "Phone", "EXIF perdu"
