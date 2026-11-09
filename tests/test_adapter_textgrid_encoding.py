"""TextGrid files in the encodings Praat writes: UTF-16, Latin-1, UTF-8 (lacing#173)."""

from __future__ import annotations

import codecs

import pytest

pytest.importorskip("praatio")

from lacing.adapters import textgrid  # noqa: E402

TEXTGRID = """File type = "ooTextFile"
Object class = "TextGrid"

xmin = 0
xmax = 2
tiers? <exists>
size = 1
item []:
    item [1]:
        class = "IntervalTier"
        name = "words"
        xmin = 0
        xmax = 2
        intervals: size = 2
        intervals [1]:
            xmin = 0
            xmax = 1
            text = "café"
        intervals [2]:
            xmin = 1
            xmax = 2
            text = "naïve"
"""


def _labels(store):
    return sorted(a.body["text"] for a in store.all())


@pytest.mark.parametrize(
    "data",
    [
        TEXTGRID.encode("utf-8"),
        codecs.BOM_UTF8 + TEXTGRID.encode("utf-8"),
        codecs.BOM_UTF16_LE + TEXTGRID.encode("utf-16-le"),
        codecs.BOM_UTF16_BE + TEXTGRID.encode("utf-16-be"),
    ],
)
def test_bom_and_utf8_files_load_with_no_argument(tmp_path, data):
    path = tmp_path / "g.TextGrid"
    path.write_bytes(data)
    assert _labels(textgrid.load(path)) == ["café", "naïve"]
    assert _labels(textgrid.load(data)) == ["café", "naïve"]


def test_latin1_loads_with_the_keyword_and_says_so_without_it(tmp_path):
    path = tmp_path / "g.TextGrid"
    path.write_bytes(TEXTGRID.encode("latin-1"))
    assert _labels(textgrid.load(path, encoding="latin-1")) == ["café", "naïve"]
    with pytest.raises(UnicodeDecodeError, match="encoding="):
        textgrid.load(path)


def test_an_ascii_utf8_file_is_not_misread_as_utf16(tmp_path):
    path = tmp_path / "g.TextGrid"
    path.write_bytes(
        TEXTGRID.replace("café", "cafe").replace("naïve", "naive").encode()
    )
    assert _labels(textgrid.load(path)) == ["cafe", "naive"]


def test_a_missing_file_is_still_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        textgrid.load(tmp_path / "nope.TextGrid")
