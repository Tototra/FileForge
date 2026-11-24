"""Recherche de fichiers par nom : index, accents, ordre des mots, fautes de frappe, familles, surlignage."""
import os
import time
from pathlib import Path

import pytest

from conftest import load


@pytest.fixture
def S(tmp_path, monkeypatch):
    s = load("search", "ff_search_t")
    home = tmp_path / "home"
    files = {
        "Documents/Impôts 2024/Avis_impot_2024.pdf": 1,
        "Documents/Factures/Facture_EDF_mars.pdf": 2,
        "Documents/Factures/facture-orange.docx": 3,
        "Images/Vacances été/plage.HEIC": 4,
        "Images/Vacances été/montagne.jpg": 5,
        "Projets/app/package.json": 6,
        "Projets/app/facture_model.js": 7,
        "Projets/app/node_modules/facture/index.js": 8,
        "Library/Caches/facture_cache.pdf": 9,
        ".cache/facture.pdf": 10,
        "Bureau/.DS_Store": 11,
        "Bureau/Rapport final (v2).pages": 12,
    }
    for rel, age in files.items():
        p = home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
        t = time.time() - age * 86400
        os.utime(p, (t, t))
    monkeypatch.setattr(s, "HOME", home)
    monkeypatch.setattr(s, "EXTRA_ROOTS", [])
    monkeypatch.setattr(s, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(s, "INDEX", tmp_path / "cache" / "index.tsv")
    monkeypatch.setattr(s, "MAX_AGE", 10 ** 9)
    monkeypatch.setattr(s, "INDEXED", s.Index())
    s.build_index()
    return s


def names(res):
    return [r["name"] for r in res[0]]


def test_norm():
    s = load("search", "ff_search_n")
    assert s.norm("Facture_EDF-Mars.pdf") == "facture edf mars pdf"
    assert s.norm("Été  Œuvre") == "ete œuvre"


def test_index_skips_noise(S):
    paths = Path(S.INDEX).read_text(encoding="utf-8")
    assert "node_modules" not in paths and "Library" not in paths and ".cache" not in paths and ".DS_Store" not in paths


def test_words_any_order_accents_case(S):
    assert names(S.search("edf facture")) == ["Facture_EDF_mars.pdf"]
    assert "Avis_impot_2024.pdf" in names(S.search("impots 2024 avis"))
    assert "plage.HEIC" in names(S.search("vacances ete plage"))


def test_folder_word(S):
    assert set(names(S.search("factures"))) >= {"Facture_EDF_mars.pdf", "facture-orange.docx"}


def test_family_filter(S):
    assert names(S.search("facture pdf")) == ["Facture_EDF_mars.pdf"]
    assert names(S.search("vacances photo")) and all(n.lower().endswith((".heic", ".jpg")) for n in names(S.search("vacances photo")))


def test_family_word_alone_is_a_term(S):
    assert names(S.search("pdf"))


def test_code_files_ranked_last(S):
    n = names(S.search("facture"))
    assert n.index("facture_model.js") > n.index("Facture_EDF_mars.pdf")


def test_typo_tolerance(S):
    res, info = S.search("factrue")
    assert info["mode"] == "flou" and any("acture" in n for n in names((res, info)))


def test_recent_when_empty(S):
    res, info = S.search("")
    assert info["mode"] == "recents" and names((res, info))[0] == "Avis_impot_2024.pdf"


def test_highlight_maps_accents_and_separators(S):
    assert S.highlight("Été_2024.pdf", ["ete"]) == [[0, 3]]
    assert S.highlight("Facture_EDF_mars.pdf", ["edf", "facture"]) == [[0, 7], [8, 11]]
    assert S.highlight("ﬁchier.txt", ["fichier"]) == [[0, 6]]


def test_describe_gone_file(S):
    d = S.describe(str(S.HOME / "absent.pdf"), 0, False, [])
    assert d["kind"] == "gone"


def test_describe_short_dir(S):
    p = S.HOME / "Documents" / "Factures" / "Facture_EDF_mars.pdf"
    assert S.describe(str(p), 0, False, [])["dir"] == "~/Documents/Factures"


def test_index_reloads_when_file_changes(S):
    S.search("x")
    (S.HOME / "Documents" / "nouveau_contrat.pdf").write_text("x")
    S.build_index()
    later = time.time() + 5
    os.utime(S.INDEX, (later, later))
    assert "nouveau_contrat.pdf" in names(S.search("nouveau contrat"))


def test_corrupt_index_line_does_not_break_search(S):
    with open(S.INDEX, "a", encoding="utf-8") as fh:
        fh.write("ligne cassée sans tabulation\n")
    later = time.time() + 10
    os.utime(S.INDEX, (later, later))
    assert names(S.search("edf facture")) == ["Facture_EDF_mars.pdf"]


def test_symlink_loop_does_not_hang(S):
    loop = S.HOME / "Documents" / "boucle"
    loop.symlink_to(S.HOME / "Documents")
    t = time.time()
    S.build_index()
    assert time.time() - t < 5


def test_refresh_lock_prevents_parallel_scans(S, monkeypatch):
    started = []
    monkeypatch.setattr(S.subprocess, "Popen", lambda *a, **k: started.append(a))
    assert S.refresh_in_background() is True
    assert S.refresh_in_background() is False
    assert len(started) == 1
