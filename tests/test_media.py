"""Vidéo et audio : chaque action sur chaque format courant, durée et flux vérifiés."""
from pathlib import Path

import pytest

from conftest import ff, act, probe, duration

VIDEOS = ["clip.mov", "clip.webm", "clip.wmv", "clip.avi", "clip.mkv", "silent.mp4"]
AUDIOS = ["son.wav", "son.mp3", "son.opus", "son.aac", "son.aif", "son.aiff", "son.flac", "son.ogg", "son.m4a", "son.wma"]

pytestmark = pytest.mark.slow


@pytest.mark.parametrize("src", VIDEOS)
def test_vid_mp4(ui, get, src):
    out, = act("vid_mp4")([get(src)])
    p = probe(out)
    assert "h264" in p and Path(out).suffix == ".mp4"
    assert abs(duration(out) - 3) < 0.3


@pytest.mark.parametrize("src", VIDEOS)
def test_vid_compress(ui, get, src):
    ui.set("Niveau", "Forte")
    out, = act("vid_compress")([get(src)])
    assert "360" in probe(out)


def test_vid_compress_never_upscales(ui, get):
    ui.set("Niveau", "Recommandée")
    out, = act("vid_compress")([get("clip.mov")])
    assert "640x360" in probe(out)


@pytest.mark.parametrize("src", VIDEOS)
def test_vid_trim(ui, get, src):
    ui.set("Début", "0:01").set("Fin", "2")
    out, = act("vid_trim")([get(src)])
    assert abs(duration(out) - 1) < 0.25


def test_vid_trim_end_before_start_clear_error(ui, get):
    ui.set("Début", "2").set("Fin", "1")
    with pytest.raises(ValueError):
        act("vid_trim")([get("clip.mov")])


def test_vid_trim_from_zero(ui, get):
    ui.set("Début", "0").set("Fin", "1")
    out, = act("vid_trim")([get("clip.mov")])
    assert abs(duration(out) - 1) < 0.25


def test_vid_gif(ui, get):
    from PIL import Image
    ui.set("Largeur", "320").set("Images par seconde", "10").set("Début", "").set("Durée", "1")
    out, = act("vid_gif")([get("clip.mov")])
    im = Image.open(out)
    assert im.width == 320 and 8 <= im.n_frames <= 12


@pytest.mark.parametrize("src", ["clip.mov", "clip.webm", "clip.wmv", "clip.avi"])
def test_vid_audio(ui, get, src):
    out, = act("vid_audio")([get(src)])
    assert "mp3" in probe(out)


def test_vid_audio_without_sound_clear_error(ui, get):
    with pytest.raises((ValueError, RuntimeError)) as e:
        act("vid_audio")([get("silent.mp4")])
    assert "son" in str(e.value).lower() or "audio" in str(e.value).lower()
    assert not list(Path(get("silent.mp4")).parent.glob("silent*.mp3"))


@pytest.mark.parametrize("src", VIDEOS)
def test_vid_mute(ui, get, src):
    out, = act("vid_mute")([get(src)])
    assert "Audio:" not in probe(out) and "Video:" in probe(out)


@pytest.mark.parametrize("m,dims", [("720p", "1280x720"), ("Vertical", "1080x1920"), ("Carré", "1080x1080")])
def test_vid_resize(ui, get, m, dims):
    ui.set("Taille", m)
    out, = act("vid_resize")([get("clip.mov")])
    assert dims in probe(out)


@pytest.mark.parametrize("src", VIDEOS)
def test_vid_rotate(ui, get, src):
    ui.set("Rotation", "droite")
    out, = act("vid_rotate")([get(src)])
    assert "360x640" in probe(out)


@pytest.mark.parametrize("src", ["clip.mov", "clip.webm"])
def test_vid_frame(ui, get, src):
    from PIL import Image
    ui.set("moment", "0:01")
    out, = act("vid_frame")([get(src)])
    assert Image.open(out).size == (640, 360)


def test_vid_frame_after_end_clear_error(ui, get):
    ui.set("moment", "9:00")
    with pytest.raises((ValueError, RuntimeError)):
        act("vid_frame")([get("clip.mov")])
    assert not [p for p in Path(get("clip.mov")).parent.glob("*.jpg")]


@pytest.mark.parametrize("src", AUDIOS + ["clip.mov"])
@pytest.mark.parametrize("fmt", ["MP3", "M4A", "WAV", "FLAC", "OGG", "AIFF"])
def test_aud_convert(ui, get, src, fmt):
    ui.set("Convertir en", fmt)
    f = get(src)
    out, = act("aud_convert")([f])
    assert Path(out).suffix == "." + fmt.split()[0].lower()
    assert abs(duration(out) - duration(f)) < 0.3
    assert Path(out) != Path(f)


@pytest.mark.parametrize("src", AUDIOS)
def test_aud_compress(ui, get, src):
    ui.set("Débit", "64k")
    out, = act("aud_compress")([get(src)])
    assert "mono" in probe(out)


@pytest.mark.parametrize("src", AUDIOS)
def test_aud_trim(ui, get, src):
    ui.set("Début", "1").set("Fin", "3").set("Fondu", "Fondu")
    f = get(src)
    out, = act("aud_trim")([f])
    assert Path(out).suffix == Path(f).suffix
    assert abs(duration(out) - 2) < 0.3


@pytest.mark.parametrize("src", AUDIOS + VIDEOS[:-1])
def test_aud_norm(ui, get, src):
    f = get(src)
    out, = act("aud_norm")([f])
    assert Path(out).suffix == Path(f).suffix
    assert abs(duration(out) - duration(f)) < 0.4


def test_aud_norm_silent_video_clear_error(ui, get):
    with pytest.raises((ValueError, RuntimeError)):
        act("aud_norm")([get("silent.mp4")])


def test_aud_merge_mixed_rates(ui, get):
    a, b = get("son.wav", "mono22.wav")
    out, = act("aud_merge")([a, b])
    assert abs(duration(out) - 7) < 0.3


def test_media_failure_leaves_no_partial_file(ui, get):
    f = get("son.wav")
    Path(f).write_bytes(b"pas un son")
    with pytest.raises((RuntimeError, ValueError)):
        act("aud_compress")([f])
    assert [p.name for p in Path(f).parent.iterdir()] == ["son.wav"]
