"""Tableurs, archives, ZIP, renommage en lot."""
import json
import os
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from conftest import ff, act


@pytest.mark.parametrize("src", ["data.csv", "comma.csv", "data.tsv", "ansi.csv", "data.json", "multi.xlsx"])
def test_tab_convert_to_excel(ui, get, src):
    ui.set("Convertir en", "Excel")
    out, = act("tab_convert")([get(src)])
    sheets = pd.read_excel(out, sheet_name=None)
    assert sum(len(df) for df in sheets.values()) >= 1


def test_tab_convert_csv_detects_separators(ui, get):
    ui.set("Convertir en", "JSON")
    out, = act("tab_convert")([get("data.csv")])
    assert json.loads(Path(out).read_text(encoding="utf-8"))[1] == {"nom": "Bob", "age": 25, "ville": "Lyon"}
    out, = act("tab_convert")([get("ansi.csv")])
    assert json.loads(Path(out).read_text(encoding="utf-8"))[0]["ville"] == "Besançon"


def test_tab_convert_multi_sheet_to_csv(ui, get):
    ui.set("Convertir en", "CSV").set("Séparateur", "Virgule")
    outs = act("tab_convert")([get("multi.xlsx")])
    assert sorted(Path(o).name for o in outs) == ["multi_Budget.csv", "multi_Notes.csv"]
    assert Path(outs[0]).read_text(encoding="utf-8-sig").startswith("Poste,Montant")


def test_tab_convert_dict_json(ui, get):
    ui.set("Convertir en", "Excel")
    out, = act("tab_convert")([get("dict.json")])
    assert set(pd.read_excel(out, sheet_name=None)) == {"clients", "ventes"}


def test_tab_convert_invalid_json_clear_error(ui, tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("{pas du json", encoding="utf-8")
    ui.set("Convertir en", "Excel")
    with pytest.raises(ValueError) as e:
        act("tab_convert")([str(f)])
    assert "JSON" in str(e.value)


def test_tab_merge_one_sheet_per_file_no_overwrite(ui, get):
    a, b = get("data.csv", "data.json")
    ui.set("Fusion", "Une feuille par fichier")
    out, = act("tab_merge")([a, b])
    sheets = pd.read_excel(out, sheet_name=None)
    assert len(sheets) == 2
    assert all(len(df) == 2 for df in sheets.values())


def test_tab_merge_long_names_no_collision(ui, get):
    a, b = get("un_nom_de_fichier_vraiment_tres_long_A.csv", "un_nom_de_fichier_vraiment_tres_long_B.csv")
    ui.set("Fusion", "Une feuille par fichier")
    out, = act("tab_merge")([a, b])
    sheets = pd.read_excel(out, sheet_name=None)
    assert len(sheets) == 2 and sorted(len(d) for d in sheets.values()) == [1, 3]


def test_tab_merge_forbidden_sheet_chars(ui, get):
    a, b = get("rapport [v2].csv", "data.csv")
    ui.set("Fusion", "Une feuille par fichier")
    out, = act("tab_merge")([a, b])
    assert len(pd.read_excel(out, sheet_name=None)) == 2


def test_tab_merge_multi_sheet_workbook(ui, get):
    a, b = get("multi.xlsx", "data.csv")
    ui.set("Fusion", "Une feuille par fichier")
    out, = act("tab_merge")([a, b])
    assert len(pd.read_excel(out, sheet_name=None)) == 3


def test_tab_merge_stack(ui, get):
    a, b = get("data.csv", "comma.csv")
    ui.set("Fusion", "empiler")
    out, = act("tab_merge")([a, b])
    df = pd.read_excel(out)
    assert len(df) == 4 and set(df["Source"]) == {"data.csv", "comma.csv"}


def test_tab_merge_failure_leaves_no_half_file(ui, get, tmp_path):
    bad = tmp_path / "work" / "zz.json"
    a = get("data.csv")
    bad.write_text("{cassé", encoding="utf-8")
    with pytest.raises(Exception):
        act("tab_merge")([a, str(bad)])
    assert not list(Path(a).parent.glob("Fusion*.xlsx"))


# ── archives
def test_make_zip_files_and_folder(ui, get, tmp_path):
    a, b = get("doc.pdf", "photo.jpg")
    folder = tmp_path / "work" / "dossier"
    (folder / "sous").mkdir(parents=True)
    (folder / "sous" / "x.txt").write_text("x")
    (folder / ".DS_Store").write_text("junk")
    out, = act("make_zip")([a, b, str(folder)])
    names = set(zipfile.ZipFile(out).namelist())
    assert names == {"doc.pdf", "photo.jpg", "dossier/sous/x.txt"}


def test_make_zip_single(ui, get):
    out, = act("make_zip")([get("doc.pdf")])
    assert Path(out).name == "doc.pdf.zip"


def test_extract_zip_skips_macosx(ui, get):
    d, = act("extract_archive")([get("arch.zip")])
    got = sorted(str(p.relative_to(d)) for p in Path(d).rglob("*") if p.is_file())
    assert got == ["b.txt", "dossier/a.txt"]


def test_extract_targz(ui, get):
    d, = act("extract_archive")([get("arch.tar.gz")])
    assert (Path(d) / "dossier" / "a.txt").read_text() == "A"
    assert Path(d).name == "arch"


@pytest.mark.parametrize("src,content", [("single.txt.gz", "contenu gz"), ("single.txt.bz2", "contenu bz2"),
                                         ("single.txt.xz", "contenu xz")])
def test_extract_single_compressed(ui, get, src, content):
    out, = act("extract_archive")([get(src)])
    assert Path(out).name == "single.txt" and Path(out).read_text() == content


def test_extract_zip_traversal_blocked(ui, get):
    f = get("evil.zip")
    d, = act("extract_archive")([f])
    assert not (Path(f).parent.parent / "evil_outside.txt").exists()
    assert (Path(d) / "ok.txt").exists()


def test_extract_not_archive(ui, tmp_path):
    f = tmp_path / "x.zip"
    f.write_text("pas une archive")
    with pytest.raises(RuntimeError, match="non pris en charge|abîm|lisible"):
        act("extract_archive")([str(f)])


# ── renommage
def test_batch_rename(ui, tmp_path):
    fs = []
    for n in ("b.txt", "a.jpg", "c.pdf"):
        p = tmp_path / n
        p.write_text(n)
        fs.append(str(p))
    ui.set("Nom de base", "Vacances")
    outs = act("batch_rename")(sorted(fs, key=ff.natural))
    assert [Path(o).name for o in outs] == ["Vacances_01.jpg", "Vacances_02.txt", "Vacances_03.pdf"]
    assert Path(outs[0]).read_text() == "a.jpg"


def test_batch_rename_swap_names(ui, tmp_path):
    """Renommer x_02 → x_01 et x_01 → x_02 sans rien écraser."""
    a, b = tmp_path / "x_02.txt", tmp_path / "x_01.txt"
    a.write_text("A")
    b.write_text("B")
    ui.set("Nom de base", "x")
    outs = act("batch_rename")([str(a), str(b)])
    assert Path(outs[0]).read_text() == "A" and Path(outs[0]).name == "x_01.txt"
    assert Path(outs[1]).read_text() == "B"


def test_batch_rename_rollback_on_failure(ui, tmp_path, monkeypatch):
    fs = []
    for i in range(5):
        p = tmp_path / f"f{i}.txt"
        p.write_text(str(i))
        fs.append(str(p))
    real = os.rename
    calls = {"n": 0}

    def flaky(a, b):
        calls["n"] += 1
        if calls["n"] == 4:
            raise PermissionError("fichier ouvert dans une autre application")
        return real(a, b)
    monkeypatch.setattr(os, "rename", flaky)
    ui.set("Nom de base", "Nouveau")
    with pytest.raises(Exception):
        act("batch_rename")(fs)
    monkeypatch.setattr(os, "rename", real)
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"f{i}.txt" for i in range(5)], "fichiers cachés ou perdus"


def test_batch_rename_cancel(ui, tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("a")
    b.write_text("b")
    ui.set("Aperçu", "Annuler")
    with pytest.raises(ff.Cancel):
        act("batch_rename")([str(a), str(b)])
    assert a.exists() and b.exists()


def test_batch_rename_rejects_slash(ui, tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("a")
    b.write_text("b")
    ui.set("Nom de base", "../evil")
    with pytest.raises(ValueError):
        act("batch_rename")([str(a), str(b)])
    assert a.exists() and b.exists()


def test_batch_rename_rollback_never_overwrites(ui, tmp_path, monkeypatch):
    """Régression : l'annulation pouvait écraser un fichier dont l'ancien nom est le nouveau nom d'un autre."""
    names = ["Fichier_02.txt", "Fichier_01.txt", "z.txt"]
    fs = []
    for n in names:
        p = tmp_path / n
        p.write_text("contenu " + n)
        fs.append(str(p))
    real = os.rename
    calls = {"n": 0}

    def flaky(a, b):
        calls["n"] += 1
        if calls["n"] == 6:                     # échec sur le dernier renommage définitif
            raise PermissionError("verrouillé")
        return real(a, b)
    monkeypatch.setattr(os, "rename", flaky)
    ui.set("Nom de base", "Fichier")
    with pytest.raises(Exception):
        act("batch_rename")(fs)
    monkeypatch.setattr(os, "rename", real)
    for n in names:
        assert (tmp_path / n).read_text() == "contenu " + n
